"""Makeo web: email/password auth, brands, compose, approve. One process."""

from __future__ import annotations

import json
import os
import re
import secrets
import sqlite3
import time
from collections import defaultdict
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

import brand_config as bc
from makeo import db, enqueue, media, scheduler

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
TEMPLATES = Jinja2Templates(directory=str(HERE / "templates"))
ALLOWED_ASSET = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".mp4"}
MIN_PASSWORD = 8
LOGIN_ERROR = "Email or password is wrong."
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_AUTH_WINDOW = 600
_AUTH_HITS: dict[str, list[float]] = defaultdict(list)

app = FastAPI(title="Makeo")

_same_site = (os.environ.get("MAKEO_COOKIE_SAMESITE") or "lax").lower()
if _same_site not in ("lax", "strict", "none"):
    _same_site = "lax"
_https_only = os.environ.get("MAKEO_COOKIE_SECURE", "").lower() in ("1", "true", "yes")
if _same_site == "none":
    _https_only = True
app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("MAKEO_SESSION", "dev-only"),
    same_site=_same_site,
    https_only=_https_only,
)


def cors_origins() -> list[str]:
    origins = [
        "https://tmai-tech.github.io",
        "http://127.0.0.1:8780",
        "http://localhost:8780",
        "http://127.0.0.1:4173",
        "http://localhost:4173",
    ]
    extra = (os.environ.get("MAKEO_PUBLIC_ORIGIN") or "").strip().rstrip("/")
    if extra and extra not in origins:
        origins.append(extra)
    return origins


app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)
app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")


def conn():
    return db.connect()


def current_user(request: Request):
    uid = request.session.get("uid")
    if not uid:
        return None
    c = conn()
    row = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    c.close()
    return row


def require_user(request: Request):
    u = current_user(request)
    if not u:
        return None
    return u


def csrf_token(request: Request) -> str:
    tok = request.session.get("csrf")
    if not tok:
        tok = secrets.token_urlsafe(32)
        request.session["csrf"] = tok
    return tok


def check_csrf(request: Request, token: str):
    if not token or token != request.session.get("csrf"):
        raise PermissionError("csrf")


def owned_brand(c, user, brand_id):
    row = c.execute("SELECT * FROM brands WHERE id=?", (brand_id,)).fetchone()
    if not row or row["user_id"] != user["id"]:
        return None
    return row


def ctx(request, user=None, **extra):
    extra.setdefault("alerts", [])
    extra.setdefault("csrf", csrf_token(request))
    extra["user"] = user
    extra["request"] = request
    return extra


def user_public(row) -> dict:
    name = ""
    try:
        name = row["name"] or ""
    except (IndexError, KeyError):
        name = ""
    return {"id": row["id"], "name": name, "email": row["email"]}


def display_name(user) -> str:
    if not user:
        return ""
    try:
        name = (user["name"] or "").strip()
    except (IndexError, KeyError):
        name = ""
    return name or user["email"]


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def validate_signup(name: str, email: str, password: str, password_confirm: str):
    name = (name or "").strip()
    email = normalize_email(email)
    if len(name) < 2 or len(name) > 80:
        return None, "Enter your name (2–80 characters)."
    if not _EMAIL_RE.match(email):
        return None, "Enter a valid email."
    if len(password or "") < MIN_PASSWORD:
        return None, "Password must be at least 8 characters."
    if password != password_confirm:
        return None, "Password and confirmation do not match."
    return {"name": name, "email": email, "password": password}, None


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def auth_rate_max() -> int:
    try:
        return max(1, int(os.environ.get("MAKEO_AUTH_RATE_MAX") or "10"))
    except ValueError:
        return 10


def rate_limited(request: Request) -> bool:
    ip = client_ip(request)
    now = time.time()
    hits = [t for t in _AUTH_HITS[ip] if now - t < _AUTH_WINDOW]
    if len(hits) >= auth_rate_max():
        _AUTH_HITS[ip] = hits
        return True
    hits.append(now)
    _AUTH_HITS[ip] = hits
    return False


def origin_ok(request: Request) -> bool:
    origin = (request.headers.get("origin") or "").rstrip("/")
    if not origin:
        return True
    return origin in {o.rstrip("/") for o in cors_origins()}


async def read_json(request: Request) -> dict:
    try:
        data = await request.json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


@app.exception_handler(PermissionError)
async def permission_error(request: Request, exc: PermissionError):
    want_json = "application/json" in (request.headers.get("accept") or "")
    if str(exc) == "csrf":
        if want_json:
            return JSONResponse({"ok": False, "error": "csrf"}, 403)
        return HTMLResponse("csrf", 403)
    if want_json:
        return JSONResponse({"ok": False, "error": "forbidden"}, 403)
    return HTMLResponse("forbidden", 403)


@app.get("/health")
def health():
    return {"ok": True, "auth": True}


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", 302)
    c = conn()
    brands = c.execute("SELECT * FROM brands WHERE user_id=? ORDER BY name",
                       (user["id"],)).fetchall()
    alerts = c.execute(
        "SELECT a.* FROM brand_alerts a JOIN brands b ON b.id=a.brand_id "
        "WHERE b.user_id=? AND a.read_at IS NULL ORDER BY a.created_at DESC LIMIT 10",
        (user["id"],)).fetchall()
    c.close()
    return TEMPLATES.TemplateResponse(
        request, "home.html", ctx(request, user, brands=brands, alerts=alerts))


@app.get("/login", response_class=HTMLResponse)
def login_get(request: Request):
    if current_user(request):
        return RedirectResponse("/", 302)
    return TEMPLATES.TemplateResponse(
        request, "login.html", ctx(request, error=None))


@app.post("/login")
def login_post(request: Request, email: str = Form(), password: str = Form(),
               csrf: str = Form("")):
    check_csrf(request, csrf)
    if rate_limited(request):
        return TEMPLATES.TemplateResponse(
            request, "login.html",
            ctx(request, error="Too many tries. Wait a few minutes."),
            status_code=429)
    c = conn()
    row = c.execute("SELECT * FROM users WHERE email=?",
                    (normalize_email(email),)).fetchone()
    c.close()
    if not row or not _verify(row["password_hash"], password):
        return TEMPLATES.TemplateResponse(
            request, "login.html",
            ctx(request, error=LOGIN_ERROR), status_code=401)
    request.session["uid"] = row["id"]
    return RedirectResponse("/", 302)


@app.get("/signup", response_class=HTMLResponse)
def signup_get(request: Request):
    if current_user(request):
        return RedirectResponse("/", 302)
    return TEMPLATES.TemplateResponse(
        request, "signup.html", ctx(request, error=None))


@app.post("/signup")
def signup_post(request: Request, name: str = Form(""), email: str = Form(""),
                password: str = Form(""), password_confirm: str = Form(""),
                csrf: str = Form("")):
    check_csrf(request, csrf)
    if rate_limited(request):
        return TEMPLATES.TemplateResponse(
            request, "signup.html",
            ctx(request, error="Too many tries. Wait a few minutes."),
            status_code=429)
    data, err = validate_signup(name, email, password, password_confirm)
    if err:
        return TEMPLATES.TemplateResponse(
            request, "signup.html", ctx(request, error=err), status_code=400)
    try:
        uid = create_user(data["email"], data["password"], data["name"])
    except sqlite3.IntegrityError:
        return TEMPLATES.TemplateResponse(
            request, "signup.html",
            ctx(request, error="That email already has an account. Sign in."),
            status_code=409)
    request.session["uid"] = uid
    return RedirectResponse("/", 302)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", 302)


@app.post("/v1/auth/signup")
async def api_signup(request: Request):
    if not origin_ok(request):
        return JSONResponse({"ok": False, "error": "origin not allowed"}, 403)
    if rate_limited(request):
        return JSONResponse({"ok": False, "error": "Too many tries. Wait a few minutes."}, 429)
    body = await read_json(request)
    data, err = validate_signup(
        body.get("name", ""), body.get("email", ""),
        body.get("password", ""),
        body.get("password_confirm", body.get("confirm", "")),
    )
    if err:
        return JSONResponse({"ok": False, "error": err}, 400)
    try:
        uid = create_user(data["email"], data["password"], data["name"])
    except sqlite3.IntegrityError:
        return JSONResponse(
            {"ok": False, "error": "That email already has an account. Sign in."}, 409)
    request.session["uid"] = uid
    c = conn()
    row = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    c.close()
    return {"ok": True, "user": user_public(row)}


@app.post("/v1/auth/login")
async def api_login(request: Request):
    if not origin_ok(request):
        return JSONResponse({"ok": False, "error": "origin not allowed"}, 403)
    if rate_limited(request):
        return JSONResponse({"ok": False, "error": "Too many tries. Wait a few minutes."}, 429)
    body = await read_json(request)
    email = normalize_email(body.get("email", ""))
    password = body.get("password") or ""
    c = conn()
    row = c.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    c.close()
    if not row or not _verify(row["password_hash"], password):
        return JSONResponse({"ok": False, "error": LOGIN_ERROR}, 401)
    request.session["uid"] = row["id"]
    return {"ok": True, "user": user_public(row)}


@app.post("/v1/auth/logout")
def api_logout(request: Request):
    request.session.clear()
    return {"ok": True}


@app.get("/v1/auth/me")
def api_me(request: Request):
    user = current_user(request)
    if not user:
        return JSONResponse({"ok": False, "error": "not signed in"}, 401)
    return {"ok": True, "user": user_public(user)}


@app.get("/brands/new", response_class=HTMLResponse)
def brand_new(request: Request):
    user = require_user(request)
    if not user:
        return RedirectResponse("/login", 302)
    return TEMPLATES.TemplateResponse(
        request, "brand_form.html", ctx(request, user, brand=None, cfg=None))


@app.post("/brands/new")
async def brand_new_post(request: Request):
    user = require_user(request)
    if not user:
        return RedirectResponse("/login", 302)
    form = await request.form()
    check_csrf(request, form.get("csrf", ""))
    return _save_brand(request, user, None, form)


@app.get("/brands/{brand_id}", response_class=HTMLResponse)
def brand_get(request: Request, brand_id: str):
    user = require_user(request)
    if not user:
        return RedirectResponse("/login", 302)
    c = conn()
    brand = owned_brand(c, user, brand_id)
    c.close()
    if not brand:
        return HTMLResponse("not found", 404)
    cfg = json.loads(brand["config"])
    return TEMPLATES.TemplateResponse(
        request, "brand_form.html",
        ctx(request, user, brand=brand, cfg=_cfg_obj(cfg)))


@app.post("/brands/{brand_id}")
async def brand_post(request: Request, brand_id: str):
    user = require_user(request)
    if not user:
        return RedirectResponse("/login", 302)
    form = await request.form()
    check_csrf(request, form.get("csrf", ""))
    return _save_brand(request, user, brand_id, form)


def _cfg_obj(d: dict):
    loc = d.get("locale") or {}

    class L:
        region = loc.get("region", "IN")
        setting_rule = loc.get("setting_rule", "")

    class C:
        pitch = d.get("pitch", "")
        hook = d.get("hook", "")
        tone = d.get("tone", "")
        locale = L()
        phone_screen_rule = d.get("phone_screen_rule", "")
        caption_template = d.get("caption_template", "")
        flow_project_url = d.get("flow_project_url", "")

    return C()


def _save_brand(request, user, brand_id, form):
    c = conn()
    if brand_id:
        brand = owned_brand(c, user, brand_id)
        if not brand:
            c.close()
            return HTMLResponse("not found", 404)
        cfg = json.loads(brand["config"])
    else:
        cfg = bc.to_dict(bc.load(bc.default_path()))
        cfg["name"] = form.get("name")
        cfg["slug"] = form.get("slug")
        cfg["brand_id"] = form.get("slug")
        brand_id = db.new_id()
        assets_dir = str(ROOT / "data" / "tenants" / cfg["slug"] / "assets")
        Path(assets_dir).mkdir(parents=True, exist_ok=True)
        c.execute(
            "INSERT INTO brands (id,user_id,slug,name,config,assets_dir,created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (brand_id, user["id"], cfg["slug"], cfg["name"], json.dumps(cfg),
             assets_dir, db.now()),
        )
        brand = c.execute("SELECT * FROM brands WHERE id=?", (brand_id,)).fetchone()

    cfg["name"] = form.get("name") or cfg.get("name")
    cfg["slug"] = form.get("slug") or cfg.get("slug")
    cfg["pitch"] = form.get("pitch") or cfg.get("pitch")
    cfg["hook"] = form.get("hook") or cfg.get("hook")
    cfg["tone"] = form.get("tone") or ""
    cfg.setdefault("locale", {})
    cfg["locale"]["region"] = form.get("region") or "IN"
    cfg["locale"]["setting_rule"] = form.get("setting_rule") or ""
    cfg["phone_screen_rule"] = form.get("phone_screen_rule") or ""
    cfg["caption_template"] = form.get("caption_template") or ""
    cfg["flow_project_url"] = form.get("flow_project_url") or ""

    assets_dir = Path(brand["assets_dir"])
    assets_dir.mkdir(parents=True, exist_ok=True)
    for field, key in (("logo", "logo"), ("splash", "splash"), ("pip_image", "pip_image")):
        up = form.get(field)
        if up is not None and getattr(up, "filename", None):
            ext = Path(up.filename).suffix.lower()
            if ext not in ALLOWED_ASSET:
                c.close()
                return HTMLResponse("bad asset type", 400)
            dest = assets_dir / f"{key}{ext}"
            dest.write_bytes(up.file.read())
            cfg.setdefault("assets", {})[key] = dest.name

    c.execute("UPDATE brands SET name=?, slug=?, config=?, assets_dir=? WHERE id=?",
              (cfg["name"], cfg["slug"], json.dumps(cfg), str(assets_dir), brand_id))
    gem = (form.get("gemini_key") or "").strip()
    if gem:
        blob = db.encrypt(gem)
        c.execute(
            "INSERT INTO secrets (id, brand_id, kind, blob) VALUES (?,?,?,?) "
            "ON CONFLICT(brand_id, kind) DO UPDATE SET blob=excluded.blob",
            (db.new_id(), brand_id, "gemini_key", blob),
        )
    c.commit()
    c.close()
    return RedirectResponse(f"/brands/{brand_id}", 302)


def _verify(stored: str, password: str) -> bool:
    if stored.startswith("$argon2"):
        from argon2 import PasswordHasher
        try:
            PasswordHasher().verify(stored, password)
            return True
        except Exception:
            return False
    return False


def hash_password(password: str) -> str:
    from argon2 import PasswordHasher
    return PasswordHasher().hash(password)


# --- PR 9: compose ---

@app.get("/brands/{brand_id}/compose", response_class=HTMLResponse)
def compose_get(request: Request, brand_id: str):
    user = require_user(request)
    if not user:
        return RedirectResponse("/login", 302)
    c = conn()
    brand = owned_brand(c, user, brand_id)
    if not brand:
        c.close()
        return HTMLResponse("not found", 404)
    jobs = c.execute(
        "SELECT * FROM jobs WHERE brand_id=? ORDER BY created_at DESC LIMIT 30",
        (brand_id,)).fetchall()
    queued = c.execute(
        "SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running')").fetchone()[0]
    alerts = c.execute(
        "SELECT * FROM brand_alerts WHERE brand_id=? AND read_at IS NULL",
        (brand_id,)).fetchall()
    c.close()
    return TEMPLATES.TemplateResponse(
        request, "compose.html",
        ctx(request, user, brand=brand, jobs=jobs, queued=queued, alerts=alerts))


@app.post("/brands/{brand_id}/compose")
def compose_post(request: Request, brand_id: str,
                 csrf: str = Form(""), prompt: str = Form(""), caption: str = Form("")):
    check_csrf(request, csrf)
    user = require_user(request)
    if not user:
        return RedirectResponse("/login", 302)
    c = conn()
    brand = owned_brand(c, user, brand_id)
    if not brand:
        c.close()
        return HTMLResponse("not found", 404)
    # write live config so enqueue can snapshot
    live = ROOT / "data" / "tenants" / brand["slug"] / "brand.json"
    live.parent.mkdir(parents=True, exist_ok=True)
    live.write_text(brand["config"], encoding="utf-8")
    c.close()
    prompt = (prompt or "").strip() or None
    enqueue.enqueue(brand["slug"], prompt=prompt, caption=caption or None,
                    source="ui_custom" if prompt else "ui_trend")
    return RedirectResponse(f"/brands/{brand_id}/compose", 302)


@app.get("/brands/{brand_id}/catalog", response_class=HTMLResponse)
def catalog_get(request: Request, brand_id: str):
    user = require_user(request)
    if not user:
        return RedirectResponse("/login", 302)
    c = conn()
    brand = owned_brand(c, user, brand_id)
    c.close()
    if not brand:
        return HTMLResponse("not found", 404)
    cfg = json.loads(brand["config"] or "{}")
    return TEMPLATES.TemplateResponse(
        request, "catalog.html",
        ctx(request, user, brand=brand, worker_url=cfg.get("catalog_worker_url") or ""))


@app.post("/brands/{brand_id}/catalog")
def catalog_post(request: Request, brand_id: str,
                 csrf: str = Form(""), worker_url: str = Form("")):
    check_csrf(request, csrf)
    user = require_user(request)
    if not user:
        return RedirectResponse("/login", 302)
    c = conn()
    brand = owned_brand(c, user, brand_id)
    if not brand:
        c.close()
        return HTMLResponse("not found", 404)
    cfg = json.loads(brand["config"] or "{}")
    cfg["catalog_worker_url"] = (worker_url or "").strip().rstrip("/")
    c.execute("UPDATE brands SET config=? WHERE id=?", (json.dumps(cfg), brand_id))
    c.commit()
    c.close()
    return RedirectResponse(f"/brands/{brand_id}/catalog", 302)


# --- PR 10: approve + IG ---

@app.get("/brands/{brand_id}/inbox", response_class=HTMLResponse)
def inbox(request: Request, brand_id: str):
    user = require_user(request)
    if not user:
        return RedirectResponse("/login", 302)
    c = conn()
    brand = owned_brand(c, user, brand_id)
    if not brand:
        c.close()
        return HTMLResponse("not found", 404)
    jobs = c.execute(
        "SELECT * FROM jobs WHERE brand_id=? AND status IN "
        "('awaiting_approval','publish_failed','posted','rejected') "
        "ORDER BY created_at DESC LIMIT 30",
        (brand_id,)).fetchall()
    c.close()
    return TEMPLATES.TemplateResponse(
        request, "inbox.html", ctx(request, user, brand=brand, jobs=jobs))


def _job_owned(c, user, job_id):
    job = db.get_job(c, job_id)
    if not job:
        return None, None
    brand = owned_brand(c, user, job["brand_id"])
    if not brand:
        return None, None
    return job, brand


@app.post("/v1/jobs/{job_id}/approve")
def approve(request: Request, job_id: str, csrf: str = Form(""), caption: str = Form("")):
    check_csrf(request, csrf)
    user = require_user(request)
    if not user:
        return RedirectResponse("/login", 302)
    c = conn()
    job, brand = _job_owned(c, user, job_id)
    if not job:
        c.close()
        return HTMLResponse("not found", 404)
    if caption:
        c.execute("UPDATE jobs SET caption_override=? WHERE id=?", (caption, job_id))
    cur = c.execute(
        "UPDATE jobs SET status='publishing' WHERE id=? AND status IN ('approved','awaiting_approval')",
        (job_id,),
    )
    if cur.rowcount:
        c.execute(
            "INSERT OR REPLACE INTO approvals (job_id, actor, decision, decided_at) "
            "VALUES (?,?,?,?)",
            (job_id, user["id"], "approve", db.now()),
        )
        media.create_token(c, job_id)
    c.commit()
    c.close()
    return RedirectResponse(f"/brands/{brand['id']}/inbox", 302)


@app.post("/v1/jobs/{job_id}/reject")
def reject(request: Request, job_id: str, csrf: str = Form("")):
    check_csrf(request, csrf)
    user = require_user(request)
    if not user:
        return RedirectResponse("/login", 302)
    c = conn()
    job, brand = _job_owned(c, user, job_id)
    if not job:
        c.close()
        return HTMLResponse("not found", 404)
    c.execute(
        "UPDATE jobs SET status='rejected', finished_at=? WHERE id=? AND status='awaiting_approval'",
        (db.now(), job_id),
    )
    c.execute(
        "INSERT OR REPLACE INTO approvals (job_id, actor, decision, decided_at) VALUES (?,?,?,?)",
        (job_id, user["id"], "reject", db.now()),
    )
    c.commit()
    bid = brand["id"]
    c.close()
    return RedirectResponse(f"/brands/{bid}/inbox", 302)


@app.post("/v1/jobs/{job_id}/retry-publish")
def retry_publish(request: Request, job_id: str, csrf: str = Form("")):
    check_csrf(request, csrf)
    user = require_user(request)
    if not user:
        return RedirectResponse("/login", 302)
    c = conn()
    job, brand = _job_owned(c, user, job_id)
    if not job:
        c.close()
        return HTMLResponse("not found", 404)
    c.execute(
        "UPDATE jobs SET status='publishing' WHERE id=? AND status='publish_failed'",
        (job_id,),
    )
    media.create_token(c, job_id)
    c.commit()
    bid = brand["id"]
    c.close()
    return RedirectResponse(f"/brands/{bid}/inbox", 302)


@app.get("/jobs/{job_id}/preview")
def preview(request: Request, job_id: str):
    user = require_user(request)
    if not user:
        return HTMLResponse("auth", 401)
    c = conn()
    job, brand = _job_owned(c, user, job_id)
    c.close()
    if not job or not job["video_relpath"]:
        return HTMLResponse("not found", 404)
    path = (ROOT / job["video_relpath"]).resolve()
    try:
        path.relative_to((ROOT / "data").resolve())
    except ValueError:
        return HTMLResponse("not found", 404)
    return FileResponse(path, media_type="video/mp4")


@app.get("/brands/{brand_id}/instagram", response_class=HTMLResponse)
def ig_get(request: Request, brand_id: str):
    user = require_user(request)
    if not user:
        return RedirectResponse("/login", 302)
    c = conn()
    brand = owned_brand(c, user, brand_id)
    if not brand:
        c.close()
        return HTMLResponse("not found", 404)
    ig = c.execute("SELECT * FROM ig_accounts WHERE brand_id=?", (brand_id,)).fetchone()
    c.close()
    return TEMPLATES.TemplateResponse(
        request, "instagram.html", ctx(request, user, brand=brand, ig=ig))


@app.post("/brands/{brand_id}/instagram")
def ig_post(request: Request, brand_id: str, csrf: str = Form(""),
            ig_user_id: str = Form(""), access_token: str = Form("")):
    check_csrf(request, csrf)
    user = require_user(request)
    if not user:
        return RedirectResponse("/login", 302)
    c = conn()
    brand = owned_brand(c, user, brand_id)
    if not brand:
        c.close()
        return HTMLResponse("not found", 404)
    import post_instagram as igmod
    me = igmod.probe_ig(ig_user_id.strip(), access_token.strip())
    username = (me or {}).get("username") or ""
    enc = db.encrypt(access_token.strip())
    c.execute(
        "INSERT INTO ig_accounts (brand_id, ig_user_id, username, token_enc, last_whoami_at) "
        "VALUES (?,?,?,?,?) "
        "ON CONFLICT(brand_id) DO UPDATE SET ig_user_id=excluded.ig_user_id, "
        "username=excluded.username, token_enc=excluded.token_enc, last_whoami_at=excluded.last_whoami_at",
        (brand_id, ig_user_id.strip(), username, enc, db.now()),
    )
    c.commit()
    c.close()
    return RedirectResponse(f"/brands/{brand_id}/instagram", 302)


@app.get("/public/media/{job_id}/{token}")
def public_media(job_id: str, token: str, request: Request):
    c = conn()
    path = media.resolve_file(c, job_id, token)
    c.close()
    if path is None:
        return HTMLResponse("not found", 404)
    rng = request.headers.get("range")
    size = path.stat().st_size
    status, start, length, headers = media.range_headers(size, rng)
    if status == 416:
        return Response(status_code=416)
    data = path.read_bytes()[start:start + length]
    return Response(content=data, status_code=status, media_type="video/mp4", headers=headers)


@app.post("/internal/jobs/{job_id}/discord-approve")
def internal_discord(request: Request, job_id: str):
    key = request.headers.get("X-Makeo-Worker-Key", "")
    if key != os.environ.get("MAKEO_WORKER_KEY", ""):
        return HTMLResponse("forbidden", 403)
    c = conn()
    job = db.get_job(c, job_id)
    if not job:
        c.close()
        return HTMLResponse("not found", 404)
    c.execute(
        "UPDATE jobs SET status='publishing' WHERE id=? AND status IN ('awaiting_approval','approved')",
        (job_id,),
    )
    media.create_token(c, job_id)
    c.commit()
    c.close()
    return {"ok": True}


@app.on_event("startup")
def _startup():
    db.connect().close()

    async def _sched():
        import asyncio
        while True:
            await asyncio.sleep(60)
            c = conn()
            try:
                scheduler.tick(c)
            finally:
                c.close()

    import asyncio
    try:
        asyncio.get_event_loop().create_task(_sched())
    except Exception:
        pass


def create_user(email: str, password: str, name: str = "") -> str:
    c = conn()
    uid = db.new_id()
    c.execute(
        "INSERT INTO users (id, email, password_hash, name, created_at) VALUES (?,?,?,?,?)",
        (uid, email.strip().lower(), hash_password(password), (name or "").strip(), db.now()),
    )
    c.commit()
    c.close()
    return uid


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8780, workers=1)
