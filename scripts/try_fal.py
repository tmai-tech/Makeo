"""One-shot fal.ai text-to-video test for the explore/fal-ai branch.

Usage:
  FAL_KEY=... python scripts/try_fal.py
  FAL_KEY=... python scripts/try_fal.py --model veo --prompt "A shop owner holding a handmade bag"
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

MODELS = {
    "ltx-fast": {
        "id": "fal-ai/ltx-2.3/text-to-video/fast",
        "body": lambda prompt: {
            "prompt": prompt,
            "duration": 6,
            "resolution": "1080p",
            "aspect_ratio": "9:16",
            "generate_audio": True,
        },
    },
    "veo": {
        "id": "fal-ai/veo3.1",
        "body": lambda prompt: {
            "prompt": prompt,
            "aspect_ratio": "9:16",
            "duration": "8s",
            "generate_audio": True,
        },
    },
}


def req(url: str, key: str, data: dict | None = None) -> dict:
    headers = {"Authorization": f"Key {key}", "Content-Type": "application/json"}
    raw = None if data is None else json.dumps(data).encode()
    request = urllib.request.Request(url, data=raw, headers=headers, method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(request, timeout=60) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        raise SystemExit(f"fal.ai HTTP {e.code}: {body[:800]}") from e


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--model", choices=sorted(MODELS), default="ltx-fast")
    p.add_argument("--prompt", default="A smiling person in a small shop holding a handmade bag, warm light, phone video, 9:16.")
    p.add_argument("--out", default="out/fal-try.mp4")
    args = p.parse_args()
    key = (os.environ.get("FAL_KEY") or "").strip()
    if not key:
        print("Set FAL_KEY to your fal.ai API key from https://fal.ai/dashboard/keys", file=sys.stderr)
        return 2
    spec = MODELS[args.model]
    endpoint = spec["id"]
    print(f"Submitting {endpoint}…")
    started = req(f"https://queue.fal.run/{endpoint}", key, spec["body"](args.prompt))
    status_url = started.get("status_url") or f"https://queue.fal.run/{endpoint}/requests/{started['request_id']}/status"
    result_url = started.get("response_url") or f"https://queue.fal.run/{endpoint}/requests/{started['request_id']}"
    for i in range(48):
        time.sleep(5)
        st = req(status_url + ("&" if "?" in status_url else "?") + "logs=1", key)
        print(f"  {st.get('status')}  queue={st.get('queue_position')}  try={i + 1}")
        if st.get("status") == "COMPLETED":
            if st.get("error"):
                raise SystemExit(st["error"])
            break
    else:
        raise SystemExit("fal.ai did not finish in 4 minutes")
    out = req(result_url, key)
    video = ((out.get("video") or {}) if isinstance(out.get("video"), dict) else {})
    href = video.get("url") or out.get("video_url")
    if not href:
        raise SystemExit("No video URL in result: " + json.dumps(out)[:400])
    dest = Path(args.out)
    dest.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(href, dest)
    print(f"Saved {dest} ({dest.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
