"""SQLite job store. WAL. Source of truth for tokens and job rows."""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
DATA = HERE / "data"
DB_PATH = DATA / "makeo.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY,
  email TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  name TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS brands (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id),
  slug TEXT UNIQUE NOT NULL,
  name TEXT NOT NULL,
  config TEXT NOT NULL,
  assets_dir TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS brand_alerts (
  id TEXT PRIMARY KEY,
  brand_id TEXT NOT NULL REFERENCES brands(id),
  kind TEXT NOT NULL,
  message TEXT NOT NULL,
  created_at TEXT NOT NULL,
  read_at TEXT
);
CREATE TABLE IF NOT EXISTS ig_accounts (
  brand_id TEXT PRIMARY KEY REFERENCES brands(id),
  ig_user_id TEXT NOT NULL,
  username TEXT,
  token_enc BLOB NOT NULL,
  token_expires_at TEXT,
  last_whoami_at TEXT
);
CREATE TABLE IF NOT EXISTS discord_targets (
  brand_id TEXT PRIMARY KEY REFERENCES brands(id),
  channel_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS schedules (
  brand_id TEXT PRIMARY KEY REFERENCES brands(id),
  enabled INTEGER NOT NULL DEFAULT 0,
  timezone TEXT NOT NULL,
  local_time TEXT NOT NULL,
  days TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  brand_id TEXT NOT NULL REFERENCES brands(id),
  user_id TEXT,
  status TEXT NOT NULL,
  source TEXT NOT NULL,
  prompt TEXT,
  caption TEXT,
  caption_override TEXT,
  config_snapshot TEXT,
  video_relpath TEXT,
  sidecar_path TEXT,
  permalink TEXT,
  last_publish_error TEXT,
  error TEXT,
  created_at TEXT NOT NULL,
  started_at TEXT,
  finished_at TEXT,
  idempotency_key TEXT UNIQUE
);
CREATE TABLE IF NOT EXISTS approvals (
  job_id TEXT PRIMARY KEY REFERENCES jobs(id),
  actor TEXT NOT NULL,
  decision TEXT NOT NULL,
  decided_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS media_tokens (
  token TEXT PRIMARY KEY,
  job_id TEXT NOT NULL REFERENCES jobs(id),
  expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS flow_locks (
  profile_key TEXT PRIMARY KEY,
  job_id TEXT,
  locked_at TEXT,
  heartbeat_at TEXT
);
CREATE TABLE IF NOT EXISTS worker_heartbeats (
  worker_id TEXT PRIMARY KEY,
  seen_at TEXT NOT NULL,
  job_id TEXT
);
CREATE TABLE IF NOT EXISTS secrets (
  id TEXT PRIMARY KEY,
  brand_id TEXT NOT NULL REFERENCES brands(id),
  kind TEXT NOT NULL,
  blob BLOB NOT NULL,
  UNIQUE(brand_id, kind)
);
"""


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def new_id() -> str:
    return uuid.uuid4().hex


def connect(path: Path | None = None) -> sqlite3.Connection:
    DATA.mkdir(parents=True, exist_ok=True)
    db = path or DB_PATH
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(users)")}
    if "name" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN name TEXT NOT NULL DEFAULT ''")
        conn.commit()


def fernet():
    raw = os.environ.get("MAKEO_MASTER_KEY")
    if not raw:
        raise RuntimeError("set MAKEO_MASTER_KEY (Fernet key)")
    from cryptography.fernet import Fernet
    return Fernet(raw.encode() if isinstance(raw, str) else raw)


def encrypt(plain: str) -> bytes:
    return fernet().encrypt(plain.encode())


def decrypt(blob: bytes) -> str:
    return fernet().decrypt(blob).decode()


def generate_master_key() -> str:
    from cryptography.fernet import Fernet
    return Fernet.generate_key().decode()


def get_brand(conn, slug: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM brands WHERE slug=?", (slug,)).fetchone()


def upsert_brand_from_json(conn, json_path: Path, user_id: str) -> str:
    import brand_config as bc
    cfg = bc.load(json_path)
    existing = get_brand(conn, cfg.slug)
    assets = str(HERE / "data" / "tenants" / cfg.slug / "assets")
    payload = json.dumps(bc.to_dict(cfg))
    if existing:
        conn.execute(
            "UPDATE brands SET name=?, config=?, assets_dir=? WHERE id=?",
            (cfg.name, payload, assets, existing["id"]),
        )
        return existing["id"]
    bid = cfg.brand_id or new_id()
    conn.execute(
        "INSERT INTO brands (id, user_id, slug, name, config, assets_dir, created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (bid, user_id, cfg.slug, cfg.name, payload, assets, now()),
    )
    return bid


def ensure_operator(conn) -> str:
    row = conn.execute("SELECT id FROM users WHERE email=?",
                       ("operator@makeo.local",)).fetchone()
    if row:
        return row["id"]
    uid = new_id()
    conn.execute(
        "INSERT INTO users (id, email, password_hash, name, created_at) VALUES (?,?,?,?,?)",
        (uid, "operator@makeo.local", "!", "Operator", now()),
    )
    return uid


def insert_job(conn, *, brand_id, user_id, source, prompt=None, caption=None,
               config_snapshot=None, idempotency_key=None, status="queued") -> str:
    jid = new_id()
    conn.execute(
        "INSERT INTO jobs (id, brand_id, user_id, status, source, prompt, caption, "
        "config_snapshot, created_at, idempotency_key) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (jid, brand_id, user_id, status, source, prompt, caption,
         config_snapshot, now(), idempotency_key),
    )
    return jid


def get_job(conn, job_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()


def add_alert(conn, brand_id: str, kind: str, message: str) -> str:
    aid = new_id()
    conn.execute(
        "INSERT INTO brand_alerts (id, brand_id, kind, message, created_at) "
        "VALUES (?,?,?,?,?)",
        (aid, brand_id, kind, message, now()),
    )
    return aid
