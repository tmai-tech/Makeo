"""Shared fixtures for unit and integration tests. No network."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet

from makeo import db


def ensure_master_key() -> str:
    key = os.environ.get("MAKEO_MASTER_KEY")
    if not key:
        key = Fernet.generate_key().decode()
        os.environ["MAKEO_MASTER_KEY"] = key
    return key


def make_conn(td: str):
    ensure_master_key()
    return db.connect(Path(td) / "makeo.db")


def insert_brand(conn, slug="tbrand", name="T", user_id=None, assets_dir=""):
    uid = user_id or db.ensure_operator(conn)
    bid = db.new_id()
    conn.execute(
        "INSERT INTO brands (id,user_id,slug,name,config,assets_dir,created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (bid, uid, slug, name, "{}", assets_dir or tempfile.gettempdir(), db.now()),
    )
    conn.commit()
    return bid, uid
