"""One-file signed Range URLs for Instagram. Do not extract RANGE_SERVER.

Guessing a timestamp or walking ../ must 404. Token maps to exactly one file.
"""

from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from makeo import db
from makeo.enqueue import HERE

TTL = timedelta(hours=2)
PUBLIC_BASE = os.environ.get("MAKEO_PUBLIC_BASE", "http://127.0.0.1:8780")


def create_token(conn, job_id: str, ttl: timedelta = TTL) -> str:
    token = secrets.token_urlsafe(32)
    exp = (datetime.now(timezone.utc) + ttl).replace(microsecond=0).isoformat()
    conn.execute(
        "INSERT INTO media_tokens (token, job_id, expires_at) VALUES (?,?,?)",
        (token, job_id, exp),
    )
    conn.commit()
    return token


def url_for_job(conn, job_id: str) -> str | None:
    row = conn.execute(
        "SELECT token FROM media_tokens WHERE job_id=? ORDER BY expires_at DESC LIMIT 1",
        (job_id,),
    ).fetchone()
    if not row:
        token = create_token(conn, job_id)
    else:
        token = row["token"]
    return f"{PUBLIC_BASE}/public/media/{job_id}/{token}"


def resolve_file(conn, job_id: str, token: str) -> Path | None:
    row = conn.execute(
        "SELECT t.expires_at, j.video_relpath FROM media_tokens t "
        "JOIN jobs j ON j.id=t.job_id WHERE t.token=? AND t.job_id=?",
        (token, job_id),
    ).fetchone()
    if not row or not row["video_relpath"]:
        return None
    exp = row["expires_at"]
    try:
        if datetime.fromisoformat(exp.replace("Z", "+00:00")) < datetime.now(timezone.utc):
            return None
    except ValueError:
        return None
    path = (HERE / row["video_relpath"]).resolve()
    root = (HERE / "data").resolve()
    try:
        path.relative_to(root)
    except ValueError:
        # also allow repo out/ during local Buzzit tests
        try:
            path.relative_to((HERE / "out").resolve())
        except ValueError:
            return None
    if not path.is_file():
        return None
    return path


def range_headers(size: int, rng: str | None):
    """Return (status, start, length, extra_headers)."""
    if not rng:
        return 200, 0, size, {"Accept-Ranges": "bytes", "Content-Length": str(size)}
    import re
    m = re.match(r"bytes=(\d*)-(\d*)", rng.strip())
    if not m:
        return 200, 0, size, {"Accept-Ranges": "bytes", "Content-Length": str(size)}
    s, e = m.group(1), m.group(2)
    start = int(s) if s else 0
    end = int(e) if e else size - 1
    end = min(end, size - 1)
    if start > end:
        return 416, 0, 0, {}
    length = end - start + 1
    return 206, start, length, {
        "Content-Type": "video/mp4",
        "Content-Range": f"bytes {start}-{end}/{size}",
        "Content-Length": str(length),
        "Accept-Ranges": "bytes",
    }


def parse_public_path(path: str) -> tuple[str, str] | None:
    """/public/media/{job_id}/{token} — reject .. and extra segments."""
    parts = [p for p in path.split("/") if p]
    if len(parts) != 4 or parts[0] != "public" or parts[1] != "media":
        return None
    job_id, token = parts[2], parts[3]
    if ".." in job_id or ".." in token or "/" in job_id:
        return None
    return job_id, token
