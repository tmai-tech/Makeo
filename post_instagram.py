"""Post a video to Instagram as a Reel via the official Graph API.

    pip install requests            # only if you use --serve
    python post_instagram.py --video out/flow-123.mp4 --serve
    python post_instagram.py --video-url https://.../clip.mp4   # already hosted

Credentials come from .env next to this file (never commit it):

    IG_USER_ID=17841400000000000
    IG_ACCESS_TOKEN=EAAG...

Get both with:  python post_instagram.py --setup

ponytail: no password, no browser automation. Instagram detects Playwright and
disables accounts for it; this is the sanctioned path and the token is revocable.

ponytail: Graph API will not accept a local file -- it fetches the video from a
public URL. --serve opens a temporary tunnel so out/*.mp4 works without S3. Swap
for a real bucket if you ever want this unattended.
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
GRAPH = "https://graph.facebook.com/v21.0"
POLL_S = 5
READY_TIMEOUT_S = 300  # container processing; long videos take a while

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def load_env():
    """Read .env into os.environ. ponytail: 6 lines beats a python-dotenv dep."""
    f = HERE / ".env"
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip("'\""))


def api(path, params=None, post=False):
    params = params or {}
    url = f"{GRAPH}/{path}"
    if post:
        req = urllib.request.Request(url, data=urllib.parse.urlencode(params).encode())
    else:
        req = urllib.request.Request(f"{url}?{urllib.parse.urlencode(params)}")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        try:
            msg = json.loads(body)["error"]["message"]
        except Exception:
            msg = body[:300]
        sys.exit(f"Graph API error {e.code}: {msg}")


def post_reel(video_url, caption, ig_user, token):
    print(f"creating container for {video_url}", flush=True)
    c = api(
        f"{ig_user}/media",
        {
            "media_type": "REELS",
            "video_url": video_url,
            "caption": caption,
            "access_token": token,
        },
        post=True,
    )
    cid = c["id"]
    print(f"container {cid}, waiting for Instagram to fetch + process...", flush=True)

    # Publishing before the container is FINISHED fails; poll status_code.
    deadline = time.time() + READY_TIMEOUT_S
    while time.time() < deadline:
        time.sleep(POLL_S)
        s = api(cid, {"fields": "status_code,status", "access_token": token})
        code = s.get("status_code")
        if code == "FINISHED":
            break
        if code == "ERROR":
            sys.exit(f"Instagram rejected the video: {s.get('status', '')}")
        print(f"  {code}... {int(deadline - time.time())}s left", flush=True)
    else:
        sys.exit(f"container not ready after {READY_TIMEOUT_S}s")

    r = api(f"{ig_user}/media_publish", {"creation_id": cid, "access_token": token},
            post=True)
    return r["id"]


RANGE_SERVER = r'''
import sys, os, re
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

class H(SimpleHTTPRequestHandler):
    """SimpleHTTPRequestHandler + HTTP Range support.

    Instagram's media fetcher pulls videos with ranged requests. The stdlib
    handler ignores Range entirely and returns 200 with the whole body, and
    Instagram treats that as a failed fetch -- surfacing as the useless
    "Media upload has failed with error code 2207077" minutes later.
    """
    def log_message(self, *a):
        pass

    def send_head(self):
        rng = self.headers.get("Range")
        if not rng:
            return super().send_head()
        path = self.translate_path(self.path)
        if not os.path.isfile(path):
            return super().send_head()
        size = os.path.getsize(path)
        m = re.match(r"bytes=(\d*)-(\d*)", rng.strip())
        if not m:
            return super().send_head()
        s, e = m.group(1), m.group(2)
        start = int(s) if s else 0
        end = int(e) if e else size - 1
        end = min(end, size - 1)
        if start > end:
            self.send_error(416)
            return None
        f = open(path, "rb")
        f.seek(start)
        self.send_response(206)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        self._limit = end - start + 1
        return f

    def copyfile(self, src, dst):
        n = getattr(self, "_limit", None)
        if n is None:
            return super().copyfile(src, dst)
        while n > 0:
            chunk = src.read(min(64 * 1024, n))
            if not chunk:
                break
            dst.write(chunk)
            n -= len(chunk)

    def end_headers(self):
        if not self.headers.get("Range"):
            self.send_header("Accept-Ranges", "bytes")
        super().end_headers()

os.chdir(sys.argv[2])
ThreadingHTTPServer(("", int(sys.argv[1])), H).serve_forever()
'''


def serve(video: Path):
    """Expose one local file via a cloudflared quick tunnel. Returns (url, proc)."""
    if not video.exists():
        sys.exit(f"no such file: {video}")
    port = "8765"
    http = subprocess.Popen(
        [sys.executable, "-c", RANGE_SERVER, port, str(video.parent)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    tun = subprocess.Popen(
        ["cloudflared", "tunnel", "--url", f"http://localhost:{port}"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
    )
    for line in tun.stdout:  # the URL is announced on stderr/stdout at startup
        if ".trycloudflare.com" in line:
            base = line.split("https://")[1].split()[0].strip()
            return f"https://{base}/{video.name}", (http, tun)
    http.kill(); tun.kill()
    sys.exit("cloudflared did not report a tunnel URL -- is it installed?")


SETUP = """
Instagram Graph API setup (~30-45 min, one time)

1. Instagram app -> Settings -> Account type -> switch to BUSINESS or CREATOR.
   Personal accounts cannot use the publishing API at all.

2. Link it to a Facebook Page:
   IG app -> Settings -> Sharing to other apps -> Facebook -> pick/create a Page.

3. developers.facebook.com -> My Apps -> Create App -> type "Business".
   Add the product "Instagram Graph API".

4. Graph API Explorer (developers.facebook.com/tools/explorer):
   - pick your app, click "Generate Access Token", grant these scopes:
       instagram_basic
       instagram_content_publish
       pages_show_list
       pages_read_engagement
   - copy the short-lived token.

5. Exchange it for a long-lived one (~60 days):
   https://graph.facebook.com/v21.0/oauth/access_token
     ?grant_type=fb_exchange_token
     &client_id=APP_ID&client_secret=APP_SECRET&fb_exchange_token=SHORT_TOKEN

6. Find your IG user id:
   https://graph.facebook.com/v21.0/me/accounts?access_token=TOKEN
     -> gives PAGE_ID
   https://graph.facebook.com/v21.0/PAGE_ID?fields=instagram_business_account&access_token=TOKEN
     -> gives the IG user id

7. Write both into .env beside this script:
   IG_USER_ID=...
   IG_ACCESS_TOKEN=...

Token expires in ~60 days -- rerun step 5 to refresh.
"""


def job_scoped(args=None):
    """True when this process must not read repo .env (Makeo worker path)."""
    if os.environ.get("MAKEO_JOB_ID"):
        return True
    if args is not None and getattr(args, "config", None):
        return True
    return False


def exchange_token(short_token, app_id, app_secret):
    """Exchange a short-lived token. Returns the long-lived token string."""
    return api("oauth/access_token", {
        "grant_type": "fb_exchange_token",
        "client_id": app_id,
        "client_secret": app_secret,
        "fb_exchange_token": short_token,
    })["access_token"]


def probe_ig(ig_id, token):
    """Return {id, username, ...} or {} if the id is not readable with token."""
    try:
        return api(ig_id, {"fields": "username,name,followers_count,media_count",
                           "access_token": token})
    except SystemExit:
        return {}


def write_env(ig_id, token, long_lived=True):
    """Replace the two credential lines in .env, leaving anything else intact."""
    env = HERE / ".env"
    old = env.read_text(encoding="utf-8") if env.exists() else ""
    keep = [l for l in old.splitlines()
            if not l.strip().startswith(("IG_USER_ID=", "IG_ACCESS_TOKEN="))]
    env.write_text("\n".join(keep + [f"IG_USER_ID={ig_id}",
                                     f"IG_ACCESS_TOKEN={token}", ""]),
                   encoding="utf-8")
    life = "valid ~60 days" if long_lived else "LIFETIME UNKNOWN -- see note below"
    print(f"\nwrote {env} ({life})")
    print("verify with: python post_instagram.py --whoami")


def finish_setup(short_token, app_id, app_secret):
    """Steps 5-6 of SETUP: long-lived token + IG business id, written to .env.

    ponytail: this is three chained GETs whose only hard part is knowing the
    field names. Automating it beats pasting hand-built URLs into a browser and
    copying ids back out, which is where this setup usually goes wrong.
    """
    print("exchanging for a long-lived token...", flush=True)
    long_tok = exchange_token(short_token, app_id, app_secret)

    # ponytail: if the IG id is already known, verify it directly and skip the
    # Page walk entirely. me/accounts only lists Pages where the user holds a
    # DIRECT Page role -- a user assigned at the Business level (ads, Business
    # Suite) gets an empty list while still being able to publish.
    # DEFAULT_IG_ID (@buzzit_official) is gone -- never fall back to Buzzit.
    known = os.environ.get("IG_USER_ID")
    if known:
        me = probe_ig(known, long_tok)
        if me.get("username"):
            print(f"verified @{me['username']} directly -- skipped Page lookup")
            write_env(known, long_tok)
            return

    print("finding your Facebook Page...", flush=True)
    pages = api("me/accounts", {"access_token": long_tok}).get("data", [])
    if not pages:
        sys.exit("no Facebook Page on this account, and no IG_USER_ID to verify "
                 "directly. Either set IG_USER_ID in .env (find it in the Facebook "
                 "login consent screen), or give this user a role on the Page: "
                 "business.facebook.com/settings/pages -> Assign people")
    for p in pages:
        print(f"  page: {p.get('name')} ({p['id']})")

    # ponytail: this account manages several Pages (Max Play Digital, Buzzit.in,
    # Cosmic Shree, ...). Taking the first Page with an IG account attached would
    # silently wire the poster to whichever Page sorts first -- i.e. post Buzzit
    # ads to the wrong brand. Collect them all, then pick by name/prompt.
    found = []
    for p in pages:
        r = api(p["id"], {"fields": "instagram_business_account{id,username}",
                          "access_token": long_tok})
        iba = r.get("instagram_business_account")
        if iba:
            found.append((p.get("name", "?"), iba["id"], iba.get("username", "?")))

    if not found:
        sys.exit("no Instagram Business account linked to any Page. Switch the IG "
                 "account to Business/Creator and link it to a Page, then retry.")

    print("\nInstagram accounts reachable with this token:")
    for i, (pname, iid, uname) in enumerate(found, 1):
        print(f"  {i}. @{uname}  (id {iid}, via Page '{pname}')")

    want = (os.environ.get("IG_USERNAME") or "").lower()
    match = [f for f in found if f[2].lower() == want]
    if match:
        pname, ig_id, uname = match[0]
        print(f"\nselected @{uname} (matches IG_USERNAME={want})")
    elif not want and len(found) == 1:
        pname, ig_id, uname = found[0]
        print(f"\nselected @{uname} (only option)")
    else:
        label = f"@{want} not found. " if want else ""
        choice = input(f"\n{label}Enter the number to use: ").strip()
        try:
            pname, ig_id, uname = found[int(choice) - 1]
        except (ValueError, IndexError):
            sys.exit("no valid selection -- nothing written")
        print(f"selected @{uname}")

    write_env(ig_id, long_tok)


def whoami(skip_dotenv=False):
    if not skip_dotenv:
        load_env()
    ig, tok = os.environ.get("IG_USER_ID"), os.environ.get("IG_ACCESS_TOKEN")
    if not ig or not tok:
        sys.exit("no IG_USER_ID / IG_ACCESS_TOKEN in environment")
    me = api(ig, {"fields": "username,name,followers_count,media_count",
                  "access_token": tok})
    print(f"authenticated as @{me.get('username')} ({me.get('name', '')})")
    print(f"  id: {ig}  followers: {me.get('followers_count')}  posts: {me.get('media_count')}")

    # ponytail: a short-lived token authenticates fine today and breaks the cron
    # tomorrow. Always show the clock, never just "ok".
    d = api("debug_token", {"input_token": tok, "access_token": tok}).get("data", {})
    exp = d.get("expires_at", 0)
    if exp == 0:
        print("  token: never expires")
    else:
        hrs = (exp - time.time()) / 3600
        print(f"  token: expires in {hrs:.1f}h ({hrs / 24:.1f} days)")
        if hrs < 48:
            print("  WARNING short-lived token -- run --finish-setup for a 60-day one")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", type=Path, help="local mp4 (needs --serve)")
    ap.add_argument("--video-url", help="already-public mp4 URL")
    ap.add_argument("--caption", help="defaults to caption in today.json")
    ap.add_argument("--serve", action="store_true",
                    help="expose --video via a temporary cloudflared tunnel")
    ap.add_argument("--setup", action="store_true", help="print token setup steps")
    ap.add_argument("--finish-setup", nargs=3, metavar=("SHORT_TOKEN", "APP_ID", "APP_SECRET"),
                    help="exchange a short-lived token, look up the IG id, write .env")
    ap.add_argument("--whoami", action="store_true",
                    help="check which IG account the saved token controls")
    ap.add_argument("--save-token", metavar="TOKEN",
                    help="verify a token against IG_USER_ID in the environment "
                         "and write .env (no Buzzit default; use --finish-setup "
                         "for a long-lived exchange)")
    ap.add_argument("--config", type=Path,
                    help="BrandConfig path; with MAKEO_JOB_ID, skip repo .env")
    args = ap.parse_args()

    scoped = job_scoped(args)

    if args.setup:
        print(SETUP)
        return
    if args.finish_setup:
        if scoped:
            sys.exit("finish-setup writes .env -- not allowed on the job-scoped path")
        finish_setup(*args.finish_setup)
        return
    if args.save_token:
        if scoped:
            sys.exit("save-token writes .env -- not allowed on the job-scoped path")
        tok = args.save_token.strip()
        ig = os.environ.get("IG_USER_ID")
        if not ig:
            sys.exit("set IG_USER_ID in the environment -- no Buzzit default")
        me = api(ig, {"fields": "username", "access_token": tok})
        print(f"verified @{me['username']}")
        write_env(ig, tok, long_lived=False)
        print("\nNOTE: if this was a short-lived token it expires in ~1 hour. "
              "Run --finish-setup with your App ID + Secret for a 60-day one.")
        return
    if args.whoami:
        whoami(skip_dotenv=scoped)
        return

    if not scoped:
        load_env()
    ig_user, token = os.environ.get("IG_USER_ID"), os.environ.get("IG_ACCESS_TOKEN")
    if not ig_user or not token:
        sys.exit("missing IG_USER_ID / IG_ACCESS_TOKEN in environment "
                 "(job-scoped runs must not fall back to repo .env)")

    caption = args.caption
    if not caption:
        # Prefer the sidecar written next to THIS video -- today.json is global
        # and gets overwritten by the next make_prompt run.
        sidecar = args.video.with_suffix(".json") if args.video else None
        src = sidecar if sidecar and sidecar.exists() else HERE / "today.json"
        if not src.exists():
            sys.exit("no --caption, no sidecar, no today.json -- run make_prompt.py first")
        caption = json.loads(src.read_text(encoding="utf-8"))["caption"]
        print(f"caption from {src.name}: {caption}", flush=True)

    procs = None
    try:
        if args.video_url:
            url = args.video_url
        elif args.video and args.serve:
            url, procs = serve(args.video)
            print(f"serving at {url}", flush=True)
        else:
            sys.exit("need --video-url, or --video with --serve")

        print(f"OK published, media id: {post_reel(url, caption, ig_user, token)}")
    finally:
        for p in procs or []:
            p.kill()


if __name__ == "__main__":
    main()
