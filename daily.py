"""Whole pipeline in one command: trend -> prompt -> video -> approve -> post.

    python daily.py            # generate, then wait for approval
    python daily.py --public   # approval page reachable from your phone

ponytail: subprocess chaining, not imports. Each step already works standalone
and prints its own progress; running them as processes keeps one failing step
from taking the others down, and lets you rerun any stage by hand.
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import brand_config as bc

HERE = Path(__file__).parent
BUZZIT_SLOGAN = "Buzz. Share. Earn. Only on Buzzit 💸 #Buzzit #CreatorEconomy"


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


def default_manual_caption(cfg, caption):
    if caption:
        return caption
    if cfg and cfg.name.lower() != "buzzit":
        return cfg.manual_caption or f"{cfg.name}"
    if cfg and cfg.manual_caption:
        return cfg.manual_caption
    return BUZZIT_SLOGAN


def write_manual_prompt(text, caption=None, out_dir=None, cfg=None):
    """Stand in for make_prompt.py when the prompt comes from a human.

    ponytail: writes the SAME two files (prompt.txt + today.json) the trend path
    writes, so everything downstream -- flow_video, the sidecar, approve, post --
    works unchanged. No second code path to keep in sync.
    """
    dest = Path(out_dir) if out_dir else HERE
    dest.mkdir(parents=True, exist_ok=True)
    cap = default_manual_caption(cfg, caption)
    (dest / "prompt.txt").write_text(text, encoding="utf-8")
    (dest / "today.json").write_text(json.dumps({
        "topic": "Custom prompt",
        "why_genz": "manually written",
        "buzzit_link": "manual",
        "brand_link": "manual",
        "veo_prompt": text,
        "caption": cap,
    }, indent=2), encoding="utf-8")
    print(f"prompt.txt written ({len(text)} chars)", flush=True)


def newest_video(out_dir=None):
    # ponytail: exclude *-branded.mp4. It is newer by mtime than the source it was
    # made from, so --skip-generate would pick it up and brand it a second time.
    # Local-dev helper only. Worker must never call this (MAKEO_JOB_ID path).
    root = Path(out_dir) if out_dir else (HERE / "out")
    vids = sorted((p for p in root.glob("flow-*.mp4")
                   if not p.stem.endswith("-branded")),
                  key=lambda p: p.stat().st_mtime)
    if not vids:
        sys.exit(f"no video in {root} -- did flow_video.py fail?")
    return vids[-1]


def job_video(out_dir, job_id):
    """Resolve the file this job produced. Never glob-by-mtime."""
    root = Path(out_dir)
    branded = root / f"flow-{job_id}-branded.mp4"
    raw = root / f"flow-{job_id}.mp4"
    if branded.exists():
        return branded
    if raw.exists():
        return raw
    return None


def write_result(out_dir, job_id, video, exit_code=0):
    sidecar = video.with_suffix(".json") if video else None
    payload = {
        "job_id": job_id,
        "video": str(video) if video else None,
        "sidecar": str(sidecar) if sidecar and sidecar.exists() else None,
        "exit": exit_code,
    }
    dest = Path(out_dir) / "result.json"
    dest.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"MAKEO_RESULT={json.dumps(payload, separators=(',', ':'))}", flush=True)
    return dest


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
    ap.add_argument("--config", type=Path, help="BrandConfig JSON")
    ap.add_argument("--out-dir", type=Path, help="write artifacts here")
    ap.add_argument("--history-dir", type=Path,
                    help="topic history for make_prompt.py")
    args = ap.parse_args()

    cfg = bc.load(args.config) if args.config else None
    out_dir = args.out_dir
    job_id = os.environ.get("MAKEO_JOB_ID") or None
    if args.no_brand and job_id:
        sys.exit(
            "MAKEO_JOB_ID runs cannot use --no-brand. "
            "Makeo will not publish an unbranded Reel; PiP can be off via pip_enabled."
        )

    if not args.skip_generate:
        if args.prompt or args.ask_prompt:
            text = args.prompt or ask_for_prompt()
            write_manual_prompt(text, args.caption, out_dir=out_dir, cfg=cfg)
            print("=== 1/4 using your prompt ===", flush=True)
        else:
            print("=== 1/4 picking today's trend ===", flush=True)
            mp = ["make_prompt.py"]
            if args.config:
                mp += ["--config", args.config]
            if out_dir:
                mp += ["--out-dir", out_dir]
            if args.history_dir:
                mp += ["--history-dir", args.history_dir]
            run(*mp)
        print("\n=== 2/4 generating video (this takes a few minutes) ===", flush=True)
        prompt_file = (out_dir / "prompt.txt") if out_dir else Path("prompt.txt")
        flow = ["flow_video.py", "--prompt-file", prompt_file, "--headless"]
        if out_dir:
            flow += ["--out", out_dir]
        project = None
        profile = None
        if cfg:
            project = cfg.flow_project_url or None
            profile = cfg.flow_profile_dir or None
        if project:
            flow += ["--project", project]
        if profile:
            flow += ["--profile-dir", profile]
        run(*flow)

    if job_id:
        video = job_video(out_dir or (HERE / "out"), job_id)
        if video is None and not args.skip_generate:
            # PR 4 names files flow-{job_id}.mp4; until then accept newest
            # only when MAKEO_JOB_ID is unset. With job id set, missing file
            # is a hard fail so the worker cannot pick yesterday's clip.
            video = None
        if video is None and not job_id:
            video = newest_video(out_dir)
    else:
        video = newest_video(out_dir)

    if video is None:
        if job_id and args.skip_approve:
            write_result(out_dir or HERE, job_id, None, exit_code=1)
        sys.exit("no video for this job -- did flow_video.py fail?")

    if not args.no_brand:
        print("\n=== 3/4 adding brand end-card ===", flush=True)
        cmd = ["brand.py", "--video", video]
        if args.screen:
            cmd += ["--screen", args.screen]
        if args.no_pip:
            cmd.append("--no-pip")
        if args.config:
            cmd += ["--config", args.config]
        if out_dir:
            cmd += ["--work-dir", out_dir]
        run(*cmd)
        branded = video.with_name(video.stem + "-branded.mp4")
        if branded.exists():
            video = branded

    if job_id:
        write_result(out_dir or HERE, job_id, video, exit_code=0)

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
