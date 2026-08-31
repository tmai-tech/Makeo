"""Serve FASHN VTON from a Colab T4 so the Makeo catalog page can call it.

Run only after `pipe` is loaded in the notebook:

    import notebooks.colab_worker as w   # or exec this file
    w.serve(pipe)

Prints a https://….trycloudflare.com URL. Paste that on Makeo → Catalog.
Leave this cell running. Do not close the Colab tab.
"""
import base64
import io
import re
import socket
import stat
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

PORT = 8766
CF_BIN = Path("/tmp/cloudflared")
MAX_IMAGE_BYTES = 10 * 1024 * 1024


def decode_image_field(value: str) -> bytes:
    """Accept a data URL or raw base64 string from the Makeo catalog page."""
    s = (value or "").strip()
    if not s:
        raise ValueError("empty image")
    if s.lower().startswith("data:") and "," in s:
        s = s.split(",", 1)[1]
    s = re.sub(r"\s+", "", s)
    try:
        data = base64.b64decode(s, validate=False)
    except Exception as e:
        raise ValueError(f"not base64: {e}") from e
    if not data:
        raise ValueError("empty image")
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError("image too large (keep under 10 MB)")
    return data


def parse_tryon_payload(data):
    """Pull person/garment bytes out of a JSON object. No FastAPI types."""
    if not isinstance(data, dict):
        raise ValueError("JSON object required")
    person = data.get("person")
    garment = data.get("garment")
    if not person or not garment:
        raise ValueError("person and garment images are required")
    category = data.get("category") or "one-pieces"
    photo_type = data.get("garment_photo_type") or "flat-lay"
    if category not in ("tops", "bottoms", "one-pieces"):
        raise ValueError("category must be tops, bottoms, or one-pieces")
    if photo_type not in ("flat-lay", "model"):
        raise ValueError("garment_photo_type must be flat-lay or model")
    try:
        steps = max(10, min(int(data.get("steps", 20)), 50))
    except (TypeError, ValueError) as e:
        raise ValueError("steps must be a number") from e
    try:
        guidance = float(data.get("guidance", 1.5))
        seed = int(data.get("seed", 42))
    except (TypeError, ValueError) as e:
        raise ValueError("guidance and seed must be numbers") from e
    return {
        "person": decode_image_field(str(person)),
        "garment": decode_image_field(str(garment)),
        "category": category,
        "garment_photo_type": photo_type,
        "steps": steps,
        "guidance": guidance,
        "seed": seed,
    }


def _free_port(start: int = PORT) -> int:
    for port in range(start, start + 20):
        sock = socket.socket()
        try:
            sock.bind(("127.0.0.1", port))
            return port
        except OSError:
            continue
        finally:
            sock.close()
    raise RuntimeError("no free local port for the catalog worker")


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
    from fastapi import FastAPI, HTTPException, Request
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

    @app.middleware("http")
    async def cors_on_errors(request, call_next):
        try:
            resp = await call_next(request)
        except Exception as exc:
            resp = JSONResponse({"detail": str(exc)}, status_code=500)
        resp.headers.setdefault("access-control-allow-origin", "*")
        return resp

    @app.get("/")
    def root():
        return {"ok": True, "service": "makeo-catalog-vton", "ready": pipe is not None}

    @app.get("/health")
    def health():
        return {"ok": True, "ready": pipe is not None}

    @app.post("/tryon")
    async def tryon(request: Request):
        try:
            data = await request.json()
        except Exception:
            raise HTTPException(400, "expected a JSON body with person and garment")
        try:
            payload = parse_tryon_payload(data)
            person_im = _open_image(payload["person"])
            garment_im = _open_image(payload["garment"])
        except ValueError as e:
            raise HTTPException(400, f"could not read images: {e}") from e
        except Exception as e:
            raise HTTPException(400, f"could not read images: {e}") from e
        if not lock.acquire(blocking=False):
            raise HTTPException(429, "worker is busy — try again in a minute")
        try:
            result = pipe(
                person_image=person_im,
                garment_image=garment_im,
                category=payload["category"],
                garment_photo_type=payload["garment_photo_type"],
                num_samples=1,
                num_timesteps=payload["steps"],
                guidance_scale=payload["guidance"],
                seed=payload["seed"],
                segmentation_free=True,
            )
            image = result.images[0]
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(500, f"try-on failed: {e}") from e
        finally:
            if lock.locked():
                lock.release()
        buf = io.BytesIO()
        image.save(buf, format="PNG")
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
    port = _free_port(port)
    thread = threading.Thread(
        target=lambda: uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning"),
        daemon=True,
    )
    thread.start()
    time.sleep(1.2)
    public = _tunnel(port)
    print("\n" + "=" * 60)
    print("Makeo catalog worker is up. (json-v2)")
    print("PASTE THIS on Makeo → Catalog → Colab worker URL")
    print("(NOT colab.research.google.com)")
    print()
    print(" ", public)
    print()
    print("Leave this cell running. Keep this Colab tab open.")
    print("If Makeo still cannot reach the worker, you are on an old cell — stop this cell and run it again.")
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
