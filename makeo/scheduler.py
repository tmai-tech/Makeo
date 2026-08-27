"""Catch-up scheduler. Compare local now in the brand TZ; never precompute UTC.

    Every minute: if local weekday is allowed AND local now >= local_time
    AND no idempotency_key=sched:{brand}:{yyyy-mm-dd}, enqueue.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from makeo import db
from makeo.enqueue import enqueue


def parse_days(raw: str) -> set[int]:
    """0=Mon .. 6=Sun, same as datetime.weekday()."""
    if not raw or raw.strip().lower() in ("all", "*"):
        return set(range(7))
    names = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
    out = set()
    for part in raw.replace(",", " ").split():
        if part.isdigit():
            out.add(int(part))
        elif part[:3].lower() in names:
            out.add(names[part[:3].lower()])
    return out or set(range(7))


def token_dead(conn, brand_id: str, now: datetime) -> bool:
    row = conn.execute(
        "SELECT token_expires_at FROM ig_accounts WHERE brand_id=?",
        (brand_id,),
    ).fetchone()
    if not row or not row["token_expires_at"]:
        return False
    try:
        exp = datetime.fromisoformat(row["token_expires_at"].replace("Z", "+00:00"))
    except ValueError:
        return False
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=now.tzinfo)
    return exp <= now


def tick(conn, now: datetime | None = None) -> list[str]:
    now = now or datetime.now().astimezone()
    created = []
    rows = conn.execute("SELECT * FROM schedules WHERE enabled=1").fetchall()
    for sch in rows:
        try:
            tz = ZoneInfo(sch["timezone"])
        except Exception:
            continue
        local = now.astimezone(tz)
        if local.weekday() not in parse_days(sch["days"]):
            continue
        hh, mm = (sch["local_time"] or "19:00").split(":")[:2]
        if (local.hour, local.minute) < (int(hh), int(mm)):
            continue
        key = f"sched:{sch['brand_id']}:{local.date().isoformat()}"
        exists = conn.execute(
            "SELECT id FROM jobs WHERE idempotency_key=?", (key,)
        ).fetchone()
        if exists:
            continue
        brand = conn.execute("SELECT slug FROM brands WHERE id=?",
                             (sch["brand_id"],)).fetchone()
        if not brand:
            continue
        if token_dead(conn, sch["brand_id"], local):
            db.insert_job(
                conn, brand_id=sch["brand_id"], user_id=None,
                source="sched_trend", status="failed",
                idempotency_key=key,
            )
            conn.execute(
                "UPDATE jobs SET error='ig_token_invalid', finished_at=? "
                "WHERE idempotency_key=?",
                (db.now(), key),
            )
            db.add_alert(conn, sch["brand_id"], "token_dead",
                         "Instagram token expired — scheduled run skipped")
            conn.commit()
            continue
        jid = enqueue(brand["slug"], source="sched_trend", conn=conn)
        conn.execute("UPDATE jobs SET idempotency_key=? WHERE id=?", (key, jid))
        conn.commit()
        created.append(jid)
    return created
