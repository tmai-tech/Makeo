"""Approval gate: post the video to a chat channel, publish to Instagram only
after a human clicks Approve.

    python approve.py --video out/flow-1785152594.mp4

Serves a small local page, sends a chat card linking to it, and blocks until you
click Approve or Reject. Approve -> calls post_instagram.py. Reject -> exits.

Config in .env (see .env.example):
    CHAT_WEBHOOK=https://chat.googleapis.com/v1/spaces/...   (or Discord/Slack)
    APPROVE_PORT=8770

ponytail: stdlib http.server, no Flask. One page with two buttons does not need
a web framework. The tunnel already exists for the video, so the same
cloudflared process serves the approval page -- approve from your phone.

ponytail: state is a module-level dict, not a DB. One pending video at a time,
by design -- this is a daily pipeline, not a queue.
"""

import argparse
import json
import os
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

HERE = Path(__file__).parent
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DECISION = {"value": None}
_done = threading.Event()

PAGE = """<!doctype html><meta name=viewport content="width=device-width,initial-scale=1">
<title>Approve Buzzit post</title>
<style>
 body{{font-family:system-ui,sans-serif;max-width:520px;margin:0 auto;padding:24px;
      background:#111;color:#eee}}
 video{{width:100%;border-radius:12px;background:#000}}
 .cap{{background:#1c1c1c;padding:14px;border-radius:10px;margin:16px 0;line-height:1.5}}
 button{{font-size:17px;padding:14px 20px;border:0;border-radius:10px;width:100%;
         margin-top:10px;cursor:pointer;font-weight:600}}
 .ok{{background:#1a7f37;color:#fff}} .no{{background:#3a3a3a;color:#eee}}
 .done{{text-align:center;padding:48px 0;font-size:19px}}
</style>
<h2>{topic}</h2>
<video src="/video.mp4" controls playsinline></video>
<div class=cap>{caption}</div>
<form method=POST action=/decide><button class=ok name=d value=approve>Approve &amp; post to Instagram</button></form>
<form method=POST action=/decide><button class=no name=d value=reject>Reject</button></form>
"""


class Handler(BaseHTTPRequestHandler):
    meta = {}
    video = None

    def log_message(self, *a):
        pass  # ponytail: quiet; the pipeline prints its own progress

    def _send(self, body, ctype="text/html; charset=utf-8", code=200):
        b = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path == "/video.mp4":
            self._send(self.video.read_bytes(), "video/mp4")
        elif self.path in ("/", "/index.html"):
            import html

            self._send(PAGE.format(
                topic=html.escape(self.meta.get("topic", "Today's video")),
                caption=html.escape(self.meta.get("caption", "")),
            ))
        else:
            self._send("not found", code=404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        d = urllib.parse.parse_qs(self.rfile.read(n).decode()).get("d", [""])[0]
        DECISION["value"] = d
        self._send(f"<div class=done>{'Approved -- posting now.' if d == 'approve' else 'Rejected. Nothing posted.'}"
                   "<br><br>You can close this tab.</div>")
        _done.set()


def notify(webhook, url, meta):
    """Post a card/message linking to the approval page.

    ponytail: one function for Google Chat, Discord and Slack -- they differ only
    in the JSON key. Detect by hostname instead of a provider config.
    """
    topic = meta.get("topic", "Today's video")
    caption = meta.get("caption", "")
    why = meta.get("buzzit_link") or meta.get("why_genz", "")

    if "discord" in webhook:
        # Discord renders embeds properly; a bare link is harder to scan.
        body = {"embeds": [{
            "title": f"Approve: {topic}"[:250],
            "url": url,
            "description": (f"**Caption**\n{caption}\n\n**Angle**\n{why}")[:4000],
            "color": 0x5865F2,
            "footer": {"text": "Click the title to watch and approve"},
        }]}
    else:  # Slack and Google Chat both take a plain "text" field
        body = {"text": f"*{topic}*\n\n{caption}\n\nReview and approve: {url}"}

    # ponytail: Discord sits behind Cloudflare, which 403s (error 1010) on the
    # default Python-urllib User-Agent. A real UA string is required, not optional.
    req = urllib.request.Request(
        webhook, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json",
                 "User-Agent": "BuzzitApprovalBot/1.0 (+https://buzzit.in)"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            r.read()
        print("sent approval card to chat", flush=True)
    except urllib.error.HTTPError as e:
        print(f"WARN chat notify failed ({e.code}): {e.read().decode()[:200]}",
              file=sys.stderr)
        print(f"Approve manually at: {url}", flush=True)


_tunnel = {"proc": None, "url": None}


def start_tunnel(port):
    """Spawn cloudflared and return (public_url, proc)."""
    p = subprocess.Popen(
        ["cloudflared", "tunnel", "--url", f"http://localhost:{port}"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    for line in p.stdout:
        if ".trycloudflare.com" in line:
            u = "https://" + line.split("https://")[1].split()[0].strip()
            _tunnel["proc"], _tunnel["url"] = p, u
            return u, p
    p.kill()
    sys.exit("cloudflared did not report a URL -- is it installed?")


def keep_tunnel_alive(port):
    """Respawn the tunnel if it dies while we wait for a human."""
    while not _done.is_set():
        time.sleep(15)
        p = _tunnel["proc"]
        if p and p.poll() is not None and not _done.is_set():
            print("  tunnel died, restarting...", flush=True)
            try:
                u, _ = start_tunnel(port)
                print(f"  new approval URL: {u}", flush=True)
                hook = os.environ.get("CHAT_WEBHOOK")
                if hook and Handler.meta:
                    notify(hook, u, Handler.meta)  # resend so the link works
            except SystemExit:
                return


def load_env():
    f = HERE / ".env"
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip("'\""))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", type=Path, required=True)
    ap.add_argument("--port", type=int, default=int(os.environ.get("APPROVE_PORT", 8770)))
    ap.add_argument("--public", action="store_true",
                    help="expose the approval page via cloudflared (approve from phone)")
    args = ap.parse_args()

    load_env()
    if not args.video.exists():
        sys.exit(f"no such video: {args.video}")

    sidecar = args.video.with_suffix(".json")
    meta = json.loads(sidecar.read_text(encoding="utf-8")) if sidecar.exists() else {}
    if not meta.get("caption"):
        sys.exit(f"no caption sidecar next to {args.video.name} -- regenerate it")

    Handler.meta, Handler.video = meta, args.video
    srv = HTTPServer(("0.0.0.0", args.port), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    url = f"http://localhost:{args.port}/"
    tun = None
    if args.public:
        url, tun = start_tunnel(args.port)
        # ponytail: quick tunnels die after a few minutes -- long enough to send
        # the card, not long enough for a human to come back and click. A dead
        # tunnel turns Approve into a 502 and the click is lost silently, which
        # already cost one run. Watch it and respawn.
        threading.Thread(target=keep_tunnel_alive, args=(args.port,),
                         daemon=True).start()

    print(f"approval page: {url}", flush=True)
    hook = os.environ.get("CHAT_WEBHOOK")
    if hook:
        notify(hook, url, meta)
    else:
        print("no CHAT_WEBHOOK set -- open the URL above to approve", flush=True)

    print("waiting for decision (Ctrl-C to abort)...", flush=True)
    try:
        _done.wait()
    except KeyboardInterrupt:
        print("\naborted, nothing posted")
        return
    finally:
        if tun:
            tun.kill()

    if DECISION["value"] != "approve":
        print("rejected -- nothing posted")
        return

    print("approved -> publishing to Instagram", flush=True)
    r = subprocess.run(
        [sys.executable, str(HERE / "post_instagram.py"),
         "--video", str(args.video), "--serve"],
        cwd=str(HERE))
    sys.exit(r.returncode)


if __name__ == "__main__":
    main()
