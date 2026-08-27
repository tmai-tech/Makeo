"""Whole pipeline in one command: trend -> prompt -> video -> approve -> post.

    python daily.py            # generate, then wait for approval
    python daily.py --public   # approval page reachable from your phone

ponytail: subprocess chaining, not imports. Each step already works standalone
and prints its own progress; running them as processes keeps one failing step
from taking the others down, and lets you rerun any stage by hand.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent


def run(*cmd):
    r = subprocess.run([sys.executable, *[str(c) for c in cmd]], cwd=str(HERE))
    if r.returncode:
        sys.exit(f"step failed: {' '.join(str(c) for c in cmd)}")


def ask_for_prompt():
    print("Paste your Veo prompt, then Enter (blank line cancels):", flush=True)
    text = input("> ").strip()
    if not text:
        sys.exit("no prompt given -- nothing to do")
    return text


def write_manual_prompt(text, caption=None):
    """Stand in for make_prompt.py when the prompt comes from a human.

    ponytail: writes the SAME two files (prompt.txt + today.json) the trend path
    writes, so everything downstream -- flow_video, the sidecar, approve, post --
    works unchanged. No second code path to keep in sync.
    """
    (HERE / "prompt.txt").write_text(text, encoding="utf-8")
    (HERE / "today.json").write_text(json.dumps({
        "topic": "Custom prompt",
        "why_genz": "manually written",
        "buzzit_link": "manual",
        "veo_prompt": text,
        "caption": caption or "Buzz. Share. Earn. Only on Buzzit 💸 #Buzzit #CreatorEconomy",
    }, indent=2), encoding="utf-8")
    print(f"prompt.txt written ({len(text)} chars)", flush=True)


def newest_video():
    # ponytail: exclude *-branded.mp4. It is newer by mtime than the source it was
    # made from, so --skip-generate would pick it up and brand it a second time.
    vids = sorted((p for p in (HERE / "out").glob("flow-*.mp4")
                   if not p.stem.endswith("-branded")),
                  key=lambda p: p.stat().st_mtime)
    if not vids:
        sys.exit("no video in out/ -- did flow_video.py fail?")
    return vids[-1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--public", action="store_true",
                    help="expose the approval page so you can approve from a phone")
    ap.add_argument("--skip-generate", action="store_true",
                    help="approve the newest existing video instead of making a new one")
    ap.add_argument("--prompt", help="your own Veo prompt instead of a trend pick")
    ap.add_argument("--ask-prompt", action="store_true",
                    help="type the prompt interactively at the terminal")
    ap.add_argument("--caption", help="caption to post with a --prompt video")
    ap.add_argument("--no-brand", action="store_true",
                    help="skip the Buzzit end-card")
    ap.add_argument("--skip-approve", action="store_true",
                    help="generate and brand only -- the caller handles approval "
                         "(used by bot.py, which approves with Discord buttons)")
    # ponytail: no default -- brand.py uses the animated splash gif unless a
    # screenshot is named. Defaulting to "withdraw" here silently overrode that
    # and every scheduled run got the static card instead of the splash.
    ap.add_argument("--screen", choices=["withdraw", "feedscreen", "Profile"],
                    help="use a static app screenshot instead of the splash gif")
    ap.add_argument("--no-pip", action="store_true",
                    help="skip the Buzzit feed inset overlay")
    args = ap.parse_args()

    if not args.skip_generate:
        if args.prompt or args.ask_prompt:
            text = args.prompt or ask_for_prompt()
            write_manual_prompt(text, args.caption)
            print("=== 1/4 using your prompt ===", flush=True)
        else:
            print("=== 1/4 picking today's trend ===", flush=True)
            run("make_prompt.py")
        print("\n=== 2/4 generating video (this takes a few minutes) ===", flush=True)
        run("flow_video.py", "--prompt-file", "prompt.txt", "--headless")

    video = newest_video()

    if not args.no_brand:
        print("\n=== 3/4 adding Buzzit end-card ===", flush=True)
        cmd = ["brand.py", "--video", video]
        if args.screen:
            cmd += ["--screen", args.screen]
        if args.no_pip:
            cmd.append("--no-pip")
        run(*cmd)
        branded = video.with_name(video.stem + "-branded.mp4")
        if branded.exists():
            video = branded

    if args.skip_approve:
        print(f"\nready: {video}", flush=True)
        return

    print(f"\n=== 4/4 approval for {video.name} ===", flush=True)
    cmd = ["approve.py", "--video", video]
    if args.public:
        cmd.append("--public")
    run(*cmd)


if __name__ == "__main__":
    main()
