"""Serve FASHN VTON from a Colab T4 so the Makeo catalog page can call it.

Run only after `pipe` is loaded in the notebook:

    import notebooks.colab_worker as w   # or exec this file
    w.serve(pipe)

Prints a https://….trycloudflare.com URL. Paste that on Makeo → Catalog.
Leave this cell running. Do not close the Colab tab.
"""
from __future__ import annotations

import io
import os
import re
import stat
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

PORT = 8766
CF_BIN = Path("/tmp/cloudflared")


def _ensure_web():
    try:
        import fastapi  # noqa: F401
        import uvicorn  # noqa: F401
    except ImportError:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "-q", "fastapi", "uvicorn", "python-multipart"]
        )


def _ensure_cloudflared() -> Path:
    if CF_BIN.is_file():
        return CF_BIN
    url = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64"
    print("Downloading cloudflared…")
    urllib.request.urlretrieve(url, CF_BIN)
    CF_BIN.chmod(CF_BIN.stat().st_mode | stat.S_IEXEC)
    return CF_BIN


def _open_image(data: bytes):
    from PIL import Image

    return Image.open(io.BytesIO(data)).convert("RGB")


def build_app(pipe):
    from fastapi import FastAPI, File, Form, HTTPException, UploadFile
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse, Response

    app = FastAPI(title="Makeo catalog worker")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    lock = threading.Lock()

    @app.get("/")
    def root():
        return {"ok": True, "service": "makeo-catalog-vton", "ready": pipe is not None}

    @app.get("/health")
    def health():
        return {"ok": True, "ready": pipe is not None}

    @app.post("/tryon")
    async def tryon(
        person: UploadFile = File(...),
        garment: UploadFile = File(...),
        category: str = Form("one-pieces"),
        garment_photo_type: str = Form("flat-lay"),
        steps: int = Form(20),
        guidance: float = Form(1.5),
        seed: int = Form(42),
    ):
        if category not in ("tops", "bottoms", "one-pieces"):
            raise HTTPException(400, "category must be tops, bottoms, or one-pieces")
        if garment_photo_type not in ("flat-lay", "model"):
            raise HTTPException(400, "garment_photo_type must be flat-lay or model")
        steps = max(10, min(int(steps), 50))
        person_b = await person.read()
        garment_b = await garment.read()
        if not person_b or not garment_b:
            raise HTTPException(400, "person and garment images are required")
        if len(person_b) + len(garment_b) > 20 * 1024 * 1024:
            raise HTTPException(400, "images too large (keep under 10 MB each)")
        try:
            person_im = _open_image(person_b)
            garment_im = _open_image(garment_b)
        except Exception as e:
            raise HTTPException(400, f"could not read images: {e}") from e
        if not lock.acquire(blocking=False):
            raise HTTPException(429, "worker is busy — try again in a minute")
        try:
            result = pipe(
                person_image=person_im,
                garment_image=garment_im,
                category=category,
                garment_photo_type=garment_photo_type,
                num_samples=1,
                num_timesteps=steps,
                guidance_scale=float(guidance),
                seed=int(seed),
                segmentation_free=True,
            )
        except Exception as e:
            raise HTTPException(500, f"try-on failed: {e}") from e
        finally:
            lock.release()
        buf = io.BytesIO()
        result.images[0].save(buf, format="PNG")
        return Response(content=buf.getvalue(), media_type="image/png")

    @app.get("/ready")
    def ready():
        return JSONResponse({"ok": True, "busy": lock.locked()})

    return app


def _tunnel(port: int) -> str:
    bin_path = _ensure_cloudflared()
    proc = subprocess.Popen(
        [str(bin_path), "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{port}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    url = None
    assert proc.stdout is not None
    deadline = time.time() + 45
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            if proc.poll() is not None:
                break
            continue
        print(line.rstrip())
        m = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", line)
        if m:
            url = m.group(0)
            break
    if not url:
        raise RuntimeError("cloudflared did not print a public URL")
    threading.Thread(target=proc.stdout.read, daemon=True).start()
    return url


def serve(pipe, port: int = PORT) -> str:
    """Start the worker. Blocks (keep the Colab cell running). Returns the public URL."""
    if pipe is None:
        raise SystemExit("pipe is None — run the Load pipeline cell first")
    _ensure_web()
    import uvicorn

    app = build_app(pipe)
    thread = threading.Thread(
        target=lambda: uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning"),
        daemon=True,
    )
    thread.start()
    time.sleep(1.2)
    public = _tunnel(port)
    print("\n" + "=" * 60)
    print("Makeo catalog worker is up.")
    print("Paste this URL on Makeo → Catalog → Colab worker URL:")
    print(" ", public)
    print("Leave this cell running. Keep the Colab tab open.")
    print("=" * 60 + "\n")
    try:
        while True:
            time.sleep(60)
            print(time.strftime("%H:%M:%S"), "worker still running", public, flush=True)
    except KeyboardInterrupt:
        print("worker stopped")
    return public


if __name__ == "__main__":
    import __main__

    serve(getattr(__main__, "pipe", None))
