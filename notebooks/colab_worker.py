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


# Served at /ui. Makeo talks to this tab with postMessage so the browser
# does not have to CORS-fetch trycloudflare.com (Cloudflare blocks that).
WORKER_UI_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Makeo catalog worker</title>
  <style>
    body { font: 16px/1.45 system-ui, sans-serif; background: #111; color: #eee; margin: 2rem; }
    code { color: #e8b84b; }
    .ok { color: #6d6; }
    .bad { color: #f88; }
  </style>
</head>
<body>
  <p id="s">Waiting for Makeo… keep this tab open.</p>
  <p>Cloudflare is done when you can read this page. Go back to Makeo and click <strong>Create look</strong>.</p>
  <script>
  function allowed(origin) {
    if (!origin) return false;
    if (origin === "https://tmai-tech.github.io") return true;
    return /^https?:\\/\\/(localhost|127\\.0\\.0\\.1)(:\\d+)?$/.test(origin);
  }
  function say(t, cls) {
    var el = document.getElementById("s");
    el.textContent = t;
    el.className = cls || "";
  }
  window.addEventListener("message", function (e) {
    if (!allowed(e.origin)) return;
    var d = e.data || {};
    if (d.type === "ping") {
      e.source.postMessage({ type: "pong", ready: true }, e.origin);
      return;
    }
    if (d.type !== "tryon" || !d.payload) return;
    say("Creating look… 1–3 minutes. Leave this tab open.");
    fetch("/tryon", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(d.payload)
    }).then(function (r) {
      if (!r.ok) {
        return r.text().then(function (t) {
          throw new Error((t || r.statusText || "try-on failed").slice(0, 240));
        });
      }
      return r.blob();
    }).then(function (blob) {
      return new Promise(function (resolve, reject) {
        var fr = new FileReader();
        fr.onload = function () { resolve(fr.result); };
        fr.onerror = reject;
        fr.readAsDataURL(blob);
      });
    }).then(function (dataUrl) {
      e.source.postMessage({ type: "result", ok: true, dataUrl: dataUrl }, e.origin);
      say("Look sent back to Makeo. You can leave this tab open.", "ok");
    }).catch(function (err) {
      var msg = (err && err.message) || String(err);
      e.source.postMessage({ type: "result", ok: false, error: msg }, e.origin);
      say(msg, "bad");
    });
  });
  if (window.opener) {
    try { window.opener.postMessage({ type: "worker-ui-ready" }, "*"); } catch (err) {}
  }
  </script>
</body>
</html>
"""


def build_app(pipe):
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import HTMLResponse, JSONResponse, Response

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
    def root(request: Request):
        accept = (request.headers.get("accept") or "").lower()
        if "text/html" in accept:
            return HTMLResponse(WORKER_UI_HTML)
        return {"ok": True, "service": "makeo-catalog-vton", "ready": pipe is not None}

    @app.get("/health")
    def health():
        return {"ok": True, "ready": pipe is not None}

    @app.get("/ui")
    def ui():
        return HTMLResponse(WORKER_UI_HTML)

    @app.post("/")
    async def tryon_root(request: Request):
        return await tryon(request)

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


def _health_ok(url: str, timeout: float = 8.0) -> bool:
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/health", timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except Exception:
        return False


def _kill_stale_cloudflared() -> None:
    subprocess.call(
        ["pkill", "-f", "/tmp/cloudflared"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _read_url(proc, pattern: str, seconds: float):
    assert proc.stdout is not None
    deadline = time.time() + seconds
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            if proc.poll() is not None:
                return None
            continue
        print(line.rstrip())
        m = re.search(pattern, line)
        if m:
            threading.Thread(target=proc.stdout.read, daemon=True).start()
            return m.group(0)
    return None


def _tunnel(port: int):
    """Return a trycloudflare URL only if /health answers. These tunnels often print a URL and then die."""
    try:
        bin_path = _ensure_cloudflared()
        proc = subprocess.Popen(
            [
                str(bin_path),
                "tunnel",
                "--no-autoupdate",
                "--edge-ip-version",
                "4",
                "--url",
                f"http://127.0.0.1:{port}",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        url = _read_url(proc, r"https://[a-z0-9-]+\.trycloudflare\.com", 35)
    except Exception as e:
        print("cloudflared failed:", e)
        return None
    if not url:
        print("cloudflared did not print a public URL")
        return None
    if not _health_ok(url, timeout=10):
        print("trycloudflare printed", url, "but /health never answered — ignoring it")
        return None
    return url


def _colab_proxy(port: int):
    try:
        from google.colab.output import eval_js
    except ImportError:
        return None
    try:
        url = eval_js("google.colab.kernel.proxyPort(%d)" % int(port))
    except Exception as e:
        print("Colab proxy URL not available:", e)
        return None
    return (url or "").rstrip("/") or None


def _localhost_run(port: int):
    try:
        proc = subprocess.Popen(
            [
                "ssh",
                "-o",
                "StrictHostKeyChecking=no",
                "-o",
                "ExitOnForwardFailure=yes",
                "-o",
                "ServerAliveInterval=30",
                "-R",
                "80:127.0.0.1:%d" % port,
                "nokey@localhost.run",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except Exception as e:
        print("localhost.run ssh failed:", e)
        return None
    url = _read_url(proc, r"https://[A-Za-z0-9.-]+\.(localhost\.run|lhr\.life)", 35)
    if url:
        print("localhost.run:", url)
    return url


def _public_urls(port: int):
    urls = []
    colab = _colab_proxy(port)
    if colab:
        print("Colab proxy:", colab)
        urls.append(colab)
        return urls
    print("No Colab proxy — trying other tunnels")
    extra = _localhost_run(port)
    if extra and extra not in urls:
        urls.append(extra)
    cf = _tunnel(port)
    if cf and cf not in urls:
        urls.append(cf)
    return urls


def serve(pipe, port: int = PORT) -> str:
    """Start the worker. Blocks (keep the Colab cell running). Returns the public URL."""
    if pipe is None:
        raise SystemExit("pipe is None — run the Load pipeline cell first")
    _ensure_web()
    import uvicorn

    _kill_stale_cloudflared()
    app = build_app(pipe)
    port = _free_port(port)
    thread = threading.Thread(
        target=lambda: uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning"),
        daemon=True,
    )
    thread.start()
    time.sleep(1.2)
    urls = _public_urls(port)
    if not urls:
        raise RuntimeError(
            "No public URL. Re-run this cell. Prefer the googleusercontent.com line if Colab printed one."
        )
    public = urls[0]
    print("\n" + "=" * 60)
    print("Makeo catalog worker is up. (json-v5)")
    print("PASTE THIS on Makeo → Catalog → Colab worker URL")
    print("(NOT colab.research.google.com, NOT a trycloudflare URL that never loads)")
    print()
    print(" ", public)
    for alt in urls[1:]:
        print(" also:", alt)
    print()
    print("Confirm /ui in a tab:")
    print(" ", public + "/ui")
    print("That page must say Waiting for Makeo — not {\"detail\":\"Not Found\"}.")
    print("Leave this cell running. Keep this Colab tab open.")
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
