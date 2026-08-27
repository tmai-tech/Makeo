"""Nightly ops: IG token slide-refresh and 30-day video retention.

    python -m makeo.ops
"""

from __future__ import annotations

import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from makeo import db
from makeo.enqueue import HERE, tenant_root

RETENTION_DAYS = 30


def slide_refresh(conn) -> int:
    """Exchange long-lived tokens using platform META_APP_ID / META_APP_SECRET."""
    app_id = os.environ.get("META_APP_ID")
    secret = os.environ.get("META_APP_SECRET")
    if not app_id or not secret:
        return 0
    import post_instagram as ig
    n = 0
    for row in conn.execute("SELECT * FROM ig_accounts").fetchall():
        try:
            tok = db.decrypt(row["token_enc"])
            fresh = ig.exchange_token(tok, app_id, secret)
        except Exception as e:
            db.add_alert(conn, row["brand_id"], "token_refresh_failed", str(e)[:300])
            continue
        conn.execute(
            "UPDATE ig_accounts SET token_enc=?, last_whoami_at=? WHERE brand_id=?",
            (db.encrypt(fresh), db.now(), row["brand_id"]),
        )
        n += 1
    conn.commit()
    return n


def retain(conn, now: datetime | None = None) -> int:
    """Delete job dirs older than 30 days after posted/rejected."""
    now = now or datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=RETENTION_DAYS)).replace(microsecond=0).isoformat()
    rows = conn.execute(
        "SELECT j.id, j.brand_id, b.slug FROM jobs j JOIN brands b ON b.id=j.brand_id "
        "WHERE j.status IN ('posted','rejected','failed') AND j.finished_at IS NOT NULL "
        "AND j.finished_at < ?",
        (cutoff,),
    ).fetchall()
    removed = 0
    for r in rows:
        dest = tenant_root(r["slug"]) / "jobs" / r["id"]
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
            removed += 1
        conn.execute(
            "UPDATE jobs SET video_relpath=NULL, sidecar_path=NULL WHERE id=?",
            (r["id"],),
        )
    # fail-screenshots older than retention under job shots/ already go with the dir
    conn.commit()
    return removed


def main():
    c = db.connect()
    try:
        print(f"refreshed {slide_refresh(c)} tokens")
        print(f"retained {retain(c)} job dirs")
    finally:
        c.close()


if __name__ == "__main__":
    main()
