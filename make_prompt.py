"""Generate today's Veo prompt from trending headlines. Standalone twin of the
n8n morning branch (RSS -> Gemini -> prompt.txt + today.json), so a run does not
depend on n8n being up.

    set GEMINI_API_KEY=...
    python make_prompt.py

ponytail: stdlib urllib + ElementTree, no feedparser/requests. Two RSS feeds and
one flat <item><title> read is not worth a dependency.
"""

import argparse
import json
import os
import sys
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

import brand_config as bc

HERE = Path(__file__).parent
FEEDS = [
    "https://news.google.com/rss/search?q=when:1d+gen+z+OR+viral+OR+trending&hl=en-IN&gl=IN&ceid=IN:en",
    "https://trends.google.com/trending/rss?geo=IN",
]
# ponytail: 2.5-flash still appears in ListModels but 404s generateContent for
# new keys ("no longer available to new users"). Listed != usable; verified.
MODEL = "gemini-3.6-flash"
UA = {"User-Agent": "Mozilla/5.0"}  # Google RSS 404s on the default urllib agent

# What we are actually selling. Sourced from the app itself (com.buzzit.social):
# short video feed, live streaming, coins/gifts, and Cashfree UPI/bank payouts.
BRAND = """Buzzit is an Indian short-video and live-streaming app (like Instagram
Reels + live, made in India). Creators post short videos, go live, receive gifts
from viewers as coins, and withdraw those coins as real money straight to UPI or
a bank account. The pitch: you are already making reels for free somewhere else --
on Buzzit the same content pays you."""

INSTRUCTIONS = """You write ONE 8-second vertical ad for Buzzit, an Indian app, riding today's trending topic so it feels native to the feed rather than like an ad.

{brand}

Today's trending topics in India:
{headlines}

{recent}
Rules:
- Pick the ONE topic with the most genuine Gen Z pull that you can connect to Buzzit naturally. Culture, money/side-hustle, creators, internet drama, entertainment are ideal.
- Do NOT reuse any angle listed under "Already covered" above, even reworded. Pick a genuinely different story. If every strong story is already covered, take a fresh angle on a DIFFERENT headline rather than repeating one.
- The culture and memes AROUND a story are fair game, but take no political side, name no politician or party, and skip anything grim, tragic, or communal.
- The video must end on the Buzzit hook: making money from the reels you already make. The spoken line should sell that, not the news story.
- Set it in INDIA with Indian people, Indian locations, and Indian English or Hinglish. No Western cafes, no generic American settings. This is non-negotiable.
- veo_prompt must be ONE paragraph describing shot, subject, camera move, lighting, mood, and the exact spoken line. Vertical 9:16, 8 seconds. No text overlays, no logos, no watermarks (we add branding later).
- If a phone appears in shot, its screen must NEVER be blank, off, or showing a generic app. Describe it as: "the phone screen clearly facing the camera showing a vertical short-video feed app with a dark background, a video playing, and gold accent icons". A blank or invented screen wastes the shot -- the screen is the product.
- caption: max 120 chars, Gen Z Hinglish register, mention Buzzit, 3 hashtags max.

Return ONLY valid JSON:
{{"topic":"...","why_genz":"...","buzzit_link":"how it ties to Buzzit","veo_prompt":"...","caption":"..."}}"""


def recent_topics(history_dir=None, limit=10):
    """Topics already used, newest first, from the per-video sidecars.

    ponytail: the sidecars in out/ ARE the history -- no separate ledger to keep
    in sync. Without this every run picks the same dominant story: six runs in a
    row produced the same Kangana 'Gen Z lazy reel-makers' angle reworded.

    history_dir may be repo out/ (flow-*.json) or a tenant jobs/ tree
    (*/flow-*.json). Skip *-branded. limit is a count, not calendar days.
    """
    root = Path(history_dir) if history_dir else (HERE / "out")
    files = list(root.glob("flow-*.json")) + list(root.glob("*/flow-*.json"))
    files = [f for f in files if not f.stem.endswith("-branded")]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    out = []
    for f in files:
        try:
            t = json.loads(f.read_text(encoding="utf-8")).get("topic", "").strip()
        except (json.JSONDecodeError, OSError):
            continue
        if t and t not in out:
            out.append(t)
        if len(out) >= limit:
            break
    return out


def feed_urls(cfg=None):
    """Config feeds if present, else locale query builder, else Buzzit defaults."""
    if cfg is None:
        return list(FEEDS)
    if cfg.feeds:
        return list(cfg.feeds)
    return bc.build_feeds(cfg.locale, cfg.rss_query)


def llm_prompt(cfg, titles, recent):
    if cfg:
        return cfg.format_instructions("\n".join(titles), recent)
    return INSTRUCTIONS.format(
        brand=BRAND, headlines="\n".join(titles), recent=recent)


def headlines(limit=25, feeds=None):
    """Titles from both feeds, capped so the prompt stays cheap."""
    out = []
    for url in (feeds if feeds is not None else FEEDS):
        if not bc.feed_host_allowed(url):
            print(f"  warn: skip non-allowlisted feed: {url}", file=sys.stderr)
            continue
        try:
            with urllib.request.urlopen(
                urllib.request.Request(url, headers=UA), timeout=20
            ) as r:
                root = ET.fromstring(r.read())
        except Exception as e:
            print(f"  warn: feed failed ({e}): {url}", file=sys.stderr)
            continue
        got = [t.text.strip() for t in root.iter("title") if t.text and t.text.strip()]
        out += got[1:]  # first <title> is the channel name, not a story
        print(f"  {len(got) - 1} headlines from {url.split('/')[2]}", flush=True)
    # dedupe, keep order
    return list(dict.fromkeys(out))[:limit]


def gemini(prompt, key, model=None):
    model = model or MODEL
    body = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode()
    req = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        data=body,
        headers={"Content-Type": "application/json", "x-goog-api-key": key},
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        data = json.load(r)
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        sys.exit(f"unexpected Gemini response: {json.dumps(data)[:500]}")


def parse(raw):
    """Gemini likes to wrap JSON in ``` fences. Strip and parse."""
    clean = raw.replace("```json", "").replace("```", "").strip()
    try:
        d = json.loads(clean)
    except json.JSONDecodeError:
        sys.exit(f"Gemini did not return JSON: {clean[:300]}")
    missing = [k for k in ("topic", "veo_prompt", "caption") if not d.get(k)]
    if missing:
        sys.exit(f"missing field(s): {', '.join(missing)}")
    if not d.get("buzzit_link") and d.get("brand_link"):
        d["buzzit_link"] = d["brand_link"]
    if not d.get("brand_link") and d.get("buzzit_link"):
        d["brand_link"] = d["buzzit_link"]
    return d


def _parse_args(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", type=Path, help="BrandConfig JSON")
    ap.add_argument("--out-dir", type=Path, help="write prompt.txt and today.json here")
    ap.add_argument("--history-dir", type=Path,
                    help="sidecars for topic dedupe; default = --out-dir or out/")
    ap.add_argument("--demo", action="store_true")
    return ap.parse_args(argv)


def main(argv=None):
    # ponytail: Gen Z captions are emoji-heavy and the Windows console is cp1252.
    # Files are always UTF-8; only stdout needs the nudge.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = _parse_args(argv)
    if args.demo:
        demo()
        return

    cfg = bc.load(args.config) if args.config else None
    out_dir = args.out_dir or HERE
    history_dir = args.history_dir or args.out_dir or (HERE / "out")
    feeds = feed_urls(cfg)
    model = cfg.model if cfg else MODEL
    limit = cfg.headline_limit if cfg else 25
    dedup = cfg.dedup_max_topics if cfg else 10

    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        sys.exit("set GEMINI_API_KEY")

    print("fetching feeds...", flush=True)
    titles = headlines(limit=limit, feeds=feeds)
    if not titles:
        sys.exit("no headlines fetched -- both feeds failed")
    print(f"{len(titles)} headlines total, asking {model}...", flush=True)

    used = recent_topics(history_dir, limit=dedup)
    if used:
        print(f"avoiding {len(used)} recent topic(s)", flush=True)
    recent = ("Already covered (do NOT repeat these):\n"
              + "\n".join(f"- {t}" for t in used) + "\n") if used else ""

    prompt = llm_prompt(cfg, titles, recent)

    d = parse(gemini(prompt, key, model))

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "prompt.txt").write_text(d["veo_prompt"], encoding="utf-8")
    (out_dir / "today.json").write_text(json.dumps(d, indent=2), encoding="utf-8")

    print(f"\ntopic:   {d['topic']}")
    print(f"why:     {d.get('why_genz', '')}")
    print(f"buzzit:  {d.get('buzzit_link', d.get('brand_link', ''))}")
    print(f"caption: {d['caption']}")
    print(f"\nprompt.txt written ({len(d['veo_prompt'])} chars)")
    print("NOTE: this overwrote any previous prompt.txt/today.json. Generate the "
          "video before running this again, or the caption will not match it.")


def demo():
    """ponytail: one runnable check on the only non-trivial logic -- fence
    stripping and field validation. Network paths stay untested by design."""
    d = parse('```json\n{"topic":"t","veo_prompt":"p","caption":"c"}\n```')
    assert d["topic"] == "t" and d["veo_prompt"] == "p", d
    assert parse('{"topic":"t","veo_prompt":"p","caption":"c","why_genz":"w"}')["why_genz"] == "w"
    for bad in ('{"topic":"t"}', "not json at all"):
        try:
            parse(bad)
        except SystemExit:
            pass
        else:
            raise AssertionError(f"should have exited: {bad}")
    print("demo ok")


if __name__ == "__main__":
    main()
