"""Drive Google Flow: submit a prompt, wait for the new video, download it.

Setup (once):
    pip install playwright
    python -m playwright install chromium
    python flow_video.py --login      # sign in, then press Enter in the terminal

Daily:
    python flow_video.py --prompt-file prompt.txt
    python flow_video.py --prompt "8s vertical, ..."

ponytail: dedicated browser profile only. Playwright cannot drive Chrome's live
"User Data" dir on Windows -- launch_persistent_context times out because Chrome's
launcher hands off to a new process and exits. Verified, not assumed. Upside: this
runs alongside your normal Chrome, no need to close 24 tabs every morning.

ponytail: selectors are contenteditable + accessible-name + menu label. Flow ships
no data-testid, so expect breakage on redeploys; re-check by dumping the DOM.
English UI only -- "Create"/"Download" are matched by visible text.
"""

import argparse
import sys
import time
from pathlib import Path

from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

# Override with --project once you know which project the new account owns.
PROJECT_URL = "https://labs.google/fx/tools/flow/project/84c30188-252c-4b46-bdb7-99a4699f66e7"
PROFILE_DIR = Path(__file__).parent / ".chrome-profile"
OUT_DIR = Path(__file__).parent / "out"
SHOTS_DIR = Path(__file__).parent / "shots"

GEN_TIMEOUT_S = 900  # 15 min; Veo renders run several minutes
POLL_S = 10


def fail(page, msg):
    """Loud failure: screenshot + non-zero exit. Never silently continue."""
    SHOTS_DIR.mkdir(exist_ok=True)
    shot = SHOTS_DIR / f"fail-{int(time.time())}.png"
    try:
        page.screenshot(path=str(shot), full_page=True)
    except Exception:
        shot = "(screenshot failed)"
    sys.exit(f"FAILED: {msg}\nScreenshot: {shot}")


def snapshot_tiles(page):
    """Fingerprint the gallery so we can spot a genuinely new item.

    Uses thumbnail srcs rather than position: a queued render can finish out of
    order, so 'top tile' is not reliably 'the one I just asked for'.
    """
    return set(
        page.evaluate(
            """() => Array.from(document.querySelectorAll('img[src], video[src], video source[src]'))
                         .map(e => e.src || e.getAttribute('src'))
                         .filter(Boolean)"""
        )
    )


def submit_prompt(page, prompt):
    # ponytail: Flow's composer is a contenteditable div, NOT an input with a
    # placeholder attribute -- "What do you want to create?" is rendered text
    # inside it. get_by_placeholder can never match, and fill() does not work on
    # contenteditable. Verified against the live DOM, not assumed.
    box = page.locator('div[contenteditable="true"]').last
    try:
        box.wait_for(state="visible", timeout=60_000)
    except PWTimeout:
        fail(page, "prompt box (contenteditable) not found -- Flow redeployed again?")

    box.click()
    page.keyboard.type(prompt)

    # The Create button carries aria-disabled, which flips once the box has text.
    # That is the only semantic signal Flow exposes on this control.
    create = page.get_by_role("button", name="Create").last
    for _ in range(30):
        if create.get_attribute("aria-disabled") == "false":
            break
        time.sleep(0.5)
    else:
        fail(page, "Create button never enabled -- did the prompt text register?")
    create.click()


def render_progress(page):
    """Percent still showing on any in-flight tile, e.g. '8%'. None when done.

    ponytail: this, not a new thumbnail src, is the completion signal. Flow
    lazy-loads existing tiles and swaps in placeholder thumbs as you scroll, so
    "a src appeared that wasn't there before" fires long before OUR render lands
    -- it fired on pre-existing videos and we tried to download a 8%-complete
    tile. Verified from a failure screenshot.
    """
    pcts = page.evaluate(
        """() => Array.from(document.querySelectorAll('div,span'))
                     .map(e => (e.childElementCount === 0 ? (e.textContent||'').trim() : ''))
                     .filter(t => /^\\d{1,3}%$/.test(t))"""
    )
    return pcts or None


def wait_for_new_media(page, before, deadline):
    """Wait for OUR render: see a percent badge appear, then see it disappear.

    ponytail: never return early just because an unseen media src showed up.
    Flow lazy-loads the existing gallery and Veo queues under load, so in the
    first seconds after submit there is no badge yet and plenty of "new" srcs --
    that path downloaded two wrong videos (a stale clip, then a previous run's).
    Requiring the badge to appear first is what actually identifies our job.
    """
    while time.time() < deadline:
        time.sleep(POLL_S)
        if render_progress(page):
            break
        print(f"  queued, waiting for render to start... "
              f"{int(deadline - time.time())}s budget left", flush=True)
    else:
        return None

    while time.time() < deadline:
        pcts = render_progress(page)
        if not pcts:
            time.sleep(POLL_S)  # let the finished thumbnail swap in
            return {s for s in snapshot_tiles(page) - before if s.startswith("http")} or True
        print(f"  rendering {','.join(pcts)}... {int(deadline - time.time())}s budget left",
              flush=True)
        time.sleep(POLL_S)
    return None


def download_newest(page, out_dir):
    """Fetch the newest tile's video bytes straight from its media URL.

    ponytail: no hover-menu clicking. Flow exposes no aria-haspopup="menu" and
    shows no per-tile download button on hover -- the old '...' -> Download path
    matched nothing. Every <video> carries a getMediaUrlRedirect src, so fetch it
    in-page (browser session = auth, no cookie copying) and write the bytes.
    Newest tile is first in DOM order.
    """
    srcs = page.evaluate(
        """() => Array.from(document.querySelectorAll('video'))
                     .map(e => e.src).filter(s => s && s.startsWith('http'))"""
    )
    if not srcs:
        fail(page, "no <video> src found in gallery")

    # ponytail: page.request, not in-page fetch(). getMediaUrlRedirect 302s to a
    # different origin, so a page-context fetch dies on CORS ("Failed to fetch").
    # The APIRequestContext follows redirects server-side with the same cookies.
    resp = page.request.get(srcs[0], timeout=180_000)
    if not resp.ok:
        fail(page, f"media fetch failed: {resp.status} {resp.status_text}")

    out_dir.mkdir(exist_ok=True)
    dest = out_dir / f"flow-{int(time.time())}.mp4"
    dest.write_bytes(resp.body())
    if dest.stat().st_size < 10_000:  # a real 8s clip is ~MBs; tiny = error page
        fail(page, f"downloaded file suspiciously small: {dest.stat().st_size} bytes")
    return dest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt")
    ap.add_argument("--prompt-file", type=Path)
    ap.add_argument("--login", action="store_true", help="open browser to sign in, then exit")
    ap.add_argument("--project", default=PROJECT_URL, help="Flow project URL to drive")
    ap.add_argument("--out", type=Path, default=OUT_DIR)
    ap.add_argument("--chromium", action="store_true", help="bundled Chromium instead of Chrome")
    ap.add_argument("--headless", action="store_true", help="not recommended: Google flags it")
    args = ap.parse_args()

    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            str(PROFILE_DIR),
            headless=args.headless,
            channel=None if args.chromium else "chrome",
            accept_downloads=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        # Chrome opens its own startup tab, but Playwright may connect before it
        # exists; without this wait, new_page() drives an invisible second tab.
        for _ in range(20):
            if ctx.pages:
                break
            time.sleep(0.25)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.bring_to_front()

        if args.login:
            page.goto("https://labs.google/fx/tools/flow", timeout=60_000,
                      wait_until="domcontentloaded")
            print(f"landed on {page.url}", flush=True)
            input("Sign in, open your project, then press Enter to save the session... ")
            print(f"final URL (use as --project): {page.url}")
            ctx.close()
            return

        prompt = args.prompt
        if args.prompt_file:
            prompt = args.prompt_file.read_text(encoding="utf-8").strip()
        if not prompt:
            sys.exit("need --prompt or --prompt-file")

        print(f"navigating to {args.project}", flush=True)
        # ponytail: no networkidle -- Flow holds sockets open and never goes idle.
        # The prompt box appearing is the real ready signal; submit_prompt waits on it.
        page.goto(args.project, timeout=90_000, wait_until="domcontentloaded")
        print(f"landed on {page.url}", flush=True)

        if "accounts.google.com" in page.url:
            fail(page, "not signed in -- run: python flow_video.py --login")

        before = snapshot_tiles(page)
        print(f"gallery has {len(before)} media before submit", flush=True)

        submit_prompt(page, prompt)
        print("prompt submitted, waiting for render...", flush=True)

        if not wait_for_new_media(page, before, time.time() + GEN_TIMEOUT_S):
            fail(page, f"no new media after {GEN_TIMEOUT_S}s -- still queued, or selector changed")

        dest = download_newest(page, args.out)

        # ponytail: pin the caption to THIS video. today.json is overwritten by
        # every make_prompt run, so a later run silently leaves the caption
        # describing a different clip -- that already happened once and would
        # have posted a dating-app video captioned about saving money.
        meta = Path(__file__).parent / "today.json"
        if meta.exists():
            dest.with_suffix(".json").write_text(
                meta.read_text(encoding="utf-8"), encoding="utf-8")

        print(f"OK {dest}")
        ctx.close()


if __name__ == "__main__":
    main()
