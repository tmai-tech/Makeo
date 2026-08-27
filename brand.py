"""Append the Buzzit splash end-card to a generated video.

    python brand.py --video out/flow-123.mp4              # splash_video.gif
    python brand.py --video out/flow-123.mp4 --seconds 3
    python brand.py --video out/flow-123.mp4 --screen withdraw   # static fallback

Writes <name>-branded.mp4 next to the input and copies the caption sidecar so
approve.py/post_instagram.py pick it up unchanged.

ponytail: ffmpeg only, no moviepy/editing lib. Concat is what ffmpeg is for, and
it is already installed here.

ponytail: END-CARD, not a tracked overlay on the phone in shot. Veo renders the
phone inconsistently (present in one clip, absent in the next despite the prompt
asking for it) and when present it is handheld and moving -- a static overlay
slides off it. The end-card brands every clip regardless of what Veo produced.
"""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
SHOTS = HERE / "screenshot"
SPLASH = SHOTS / "splash_video.gif"  # animated brand card, 270x480 9:16
END_S = 3.0  # end-card duration; long enough to read the tagline, short enough
             # not to bore. The gif is 10s, so this trims it.

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def probe_audio(video, entry):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0",
         "-show_entries", f"stream={entry}",
         "-of", "default=noprint_wrappers=1:nokey=1", str(video)],
        capture_output=True, text=True)
    return (r.stdout or "").strip() or None


def probe(video, *entries):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", f"stream={','.join(entries)}",
         "-of", "default=noprint_wrappers=1:nokey=1", str(video)],
        capture_output=True, text=True, check=True).stdout.split()
    return out


def build_endcard(png, w, h, out_png):
    """Screenshot centred on black with the logo above it, at video resolution.

    ponytail: crop each screenshot to its content first. The raw PNGs are tall
    phone captures with large empty areas (Withdrawals has ~half a screen of
    blank below the last row); scaling them whole leaves the content stranded in
    the top third. Crop fractions are per-screen because the dead space differs.
    """
    logo = SHOTS / "logo.png"
    # (top_frac, height_frac) of the source to keep.
    CROP = {"withdraw": (0.07, 0.45), "feedscreen": (0.0, 1.0), "Profile": (0.0, 0.72)}
    top, keep = CROP.get(png.stem, (0.0, 1.0))
    crop = f"crop=iw:ih*{keep}:0:ih*{top}," if keep < 1.0 or top else ""

    vf = (f"[1:v]{crop}scale=-1:{int(h * 0.60)}[shot];"
          f"[2:v]scale={int(w * 0.18)}:-1[logo];"
          f"[0:v][shot]overlay=(W-w)/2:(H-h)/2+{int(h * 0.05)}[a];"
          f"[a][logo]overlay=(W-w)/2:{int(h * 0.07)}")
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y",
         "-f", "lavfi", "-i", f"color=c=black:s={w}x{h}:d=1",
         "-i", str(png), "-i", str(logo),
         "-filter_complex", vf, "-frames:v", "1", str(out_png)],
        check=True)


def add_pip(video, w, h, start):
    """Overlay the real Buzzit feed as a phone-shaped inset for the last seconds.

    ponytail: a fixed-position inset, NOT the screenshot warped onto the phone in
    her hand. Veo will not render a usable phone screen on demand -- across the
    clips so far it produced an invented app once, no phone at all once, and a
    phone edge-on once, all from prompts that asked for the screen. An inset is
    deterministic: it lands correctly on every clip whatever Veo did.
    """
    shot = SHOTS / "feedscreen.png"
    if not shot.exists():
        return video
    out = HERE / "_withpip.mp4"
    pw = int(w * 0.30)                     # inset ~30% of frame width
    # ponytail: top-RIGHT. Veo tends to put the talking head centre-left holding
    # a phone on the left, so a left inset stacks awkwardly above the real phone.
    # Right side is also clear of Instagram's own left-aligned caption chrome.
    x, y = int(w - pw - 8 - w * 0.045), int(h * 0.055)
    fade = 0.4

    # ponytail: format=yuva420p BEFORE fade, and loop the still so it has a
    # timeline. A PNG is a single frame at t=0, so fade/enable never fire on it
    # and the overlay silently never appears -- which is exactly what happened.
    vf = (f"[1:v]scale={pw}:-1,"
          f"pad=iw+8:ih+8:4:4:color=0xE8B84B,"
          f"format=yuva420p,fade=t=in:st=0:d={fade}:alpha=1,"
          f"setpts=PTS-STARTPTS+{start}/TB[pip];"
          f"[0:v][pip]overlay={x}:{y}:enable='gte(t,{start})':eof_action=pass")
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(video), "-loop", "1", "-i", str(shot),
         "-filter_complex", vf, "-c:v", "libx264", "-preset", "medium",
         "-crf", "20", "-profile:v", "high", "-level", "4.0",
         # ponytail: -shortest + faststart here too. Without -shortest the
         # looped PNG input keeps the output open past the clip, leaving a
         # trailing segment that survives the concat and makes Instagram reject
         # the final file (2207077) -- while pip-only and endcard-only each
         # publish fine on their own. Bisected stage by stage.
         "-shortest", "-movflags", "+faststart",
         "-pix_fmt", "yuv420p", "-c:a", "copy", str(out)],
        check=True)
    print(f"added Buzzit feed inset from {start}s", flush=True)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", type=Path, required=True)
    ap.add_argument("--no-pip", action="store_true",
                    help="skip the Buzzit feed inset")
    ap.add_argument("--pip-from", type=float, default=4.0,
                    help="seconds into the clip to show the feed inset")
    ap.add_argument("--screen", choices=["withdraw", "feedscreen", "Profile"],
                    help="use a static screenshot instead of the animated splash")
    ap.add_argument("--seconds", type=float, default=END_S)
    args = ap.parse_args()

    if not args.video.exists():
        sys.exit(f"no such video: {args.video}")

    w, h = probe(args.video, "width", "height")
    print(f"video is {w}x{h}", flush=True)

    tmp = HERE / "_endcard.png"
    card = HERE / "_endcard.mp4"
    out = args.video.with_name(args.video.stem + "-branded.mp4")

    try:
        if args.screen:
            png = SHOTS / f"{args.screen}.png"
            if not png.exists():
                sys.exit(f"missing {png}")
            build_endcard(png, int(w), int(h), tmp)
            src = ["-loop", "1", "-i", str(tmp)]
            vf = []
        else:
            if not SPLASH.exists():
                sys.exit(f"missing {SPLASH}")
            # ponytail: the gif is 270x480 -- same 9:16 ratio, so a straight
            # lanczos upscale to the video size is enough; no pad/crop needed.
            src = ["-i", str(SPLASH)]
            vf = ["-vf", f"scale={w}:{h}:flags=lanczos,fps=30"]

        # ponytail: match the SOURCE's sample rate, and normalise both inputs
        # with aresample+asetnsamples before concat. A card built at a different
        # rate than the clip yields an audio track Instagram silently refuses
        # (error 2207077) while the same footage without the concat publishes
        # fine -- verified by bisecting encode-only vs concat.
        sr = (probe_audio(args.video, "sample_rate") or "44100")
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", *src,
             "-f", "lavfi", "-i", f"anullsrc=channel_layout=stereo:sample_rate={sr}",
             "-t", str(args.seconds), *vf, "-c:v", "libx264", "-preset", "medium",
             "-pix_fmt", "yuv420p", "-r", "30",
             "-c:a", "aac", "-b:a", "128k", "-ar", sr, "-ac", "2", "-shortest",
             str(card)], check=True)

        main = str(args.video)
        if not args.no_pip:
            main = str(add_pip(args.video, int(w), int(h), args.pip_from))

        # ponytail: re-encode concat, not stream copy. The source and the card
        # differ in timebase/SAR and the copy demuxer produces a broken file.
        # ponytail: crf 23 not 20. At 20 the 13s output lands ~8.3MB, just over
        # Discord's 8MB upload cap, so the approval preview silently fails to
        # attach on some clips. 23 keeps it comfortably under with no visible
        # loss at 720x1280 on a phone. Instagram re-encodes anyway.
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-i", main, "-i", str(card),
             "-filter_complex",
             "[0:v]scale=%s:%s,setsar=1,fps=30,format=yuv420p[v0];"
             "[1:v]scale=%s:%s,setsar=1,fps=30,format=yuv420p[v1];"
             "[0:a]aresample=%s:async=1,aformat=sample_fmts=fltp:channel_layouts=stereo[a0];"
             "[1:a]aresample=%s:async=1,aformat=sample_fmts=fltp:channel_layouts=stereo[a1];"
             "[v0][a0][v1][a1]concat=n=2:v=1:a=1[v][a]" % (w, h, w, h, sr, sr),
             "-map", "[v]", "-map", "[a]",
             # ponytail: -shortest so the streams end together. The concat left
             # video at 11.000s and audio at 11.018s, and Instagram rejected the
             # result with the opaque 2207077. +faststart moves the moov atom to
             # the front so their fetcher can parse it without reading the file
             # to the end.
             "-shortest", "-movflags", "+faststart",
             "-c:v", "libx264", "-preset", "medium",
             "-crf", "23", "-maxrate", "4M", "-bufsize", "8M",
             # ponytail: pin profile/level. Without -level, x264 derived 6.2
             # (an 8K tier) from the maxrate/bufsize hints and Instagram
             # rejected the upload with error 2207077. The clip that published
             # fine was level 3.1. 4.0 is the safe Reels ceiling.
             "-profile:v", "high", "-level", "4.0",
             "-pix_fmt", "yuv420p", "-r", "30",
             # ponytail: sr, not a hardcoded 44100. Veo clips come out at 48kHz;
             # forcing 44.1k here re-introduced the exact rate mismatch the
             # aresample filters above exist to prevent, and Instagram rejected
             # the result with 2207077 again.
             "-c:a", "aac", "-b:a", "128k", "-ar", sr, str(out)],
            check=True)
    finally:
        tmp.unlink(missing_ok=True)
        card.unlink(missing_ok=True)
        (HERE / "_withpip.mp4").unlink(missing_ok=True)

    sidecar = args.video.with_suffix(".json")
    if sidecar.exists():
        shutil.copy(sidecar, out.with_suffix(".json"))

    # ponytail: verify what we just wrote is actually postable. Instagram's
    # rejection (error 2207077) arrives minutes later, after the container
    # upload, so catching a bad level here saves the whole round trip.
    lvl = probe(out, "level")
    if lvl and int(lvl[0]) > 42:
        sys.exit(f"encoded at H.264 level {int(lvl[0])/10} -- Instagram rejects "
                 f"above 4.2. Check the -level flag in brand.py.")

    # ponytail: catch an audio rate mismatch here, not 4 minutes later as an
    # opaque Instagram 2207077. This exact drift (48k source -> 44.1k output)
    # shipped once already because a hardcoded -ar overrode the probed rate.
    out_sr = probe_audio(out, "sample_rate")
    if out_sr and sr and out_sr != sr:
        sys.exit(f"audio rate drifted: source {sr}Hz -> output {out_sr}Hz. "
                 f"Instagram will reject this. Check the -ar flags in brand.py.")

    dur = probe(out, "duration")
    print(f"OK {out}  ({float(dur[0]):.1f}s, was {float(probe(args.video, 'duration')[0]):.1f}s, "
          f"level {int(lvl[0])/10 if lvl else '?'})")


if __name__ == "__main__":
    main()
