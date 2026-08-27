"""Makeo worker. One process. Claims queued XOR publishing. Never load_env().

    python worker.py
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from makeo import db
from makeo.enqueue import HERE, tenant_root

CRASH_S = 2400 + 600  # bot.py daily timeout + encode budget
POLL_S = 5
WORKER_ID = "makeo-worker-1"
POP_KEYS = ("IG_USER_ID", "IG_ACCESS_TOKEN", "GEMINI_API_KEY")


def job_env(conn, brand_id: str) -> dict:
    """Copy of os.environ with host IG/Gemini popped, then tenant values set."""
    env = os.environ.copy()
    for k in POP_KEYS:
        env.pop(k, None)
    ig = conn.execute("SELECT * FROM ig_accounts WHERE brand_id=?",
                      (brand_id,)).fetchone()
    if ig:
        env["IG_USER_ID"] = ig["ig_user_id"]
        env["IG_ACCESS_TOKEN"] = db.decrypt(ig["token_enc"])
    sec = conn.execute(
        "SELECT blob FROM secrets WHERE brand_id=? AND kind='gemini_key'",
        (brand_id,)).fetchone()
    if sec:
        env["GEMINI_API_KEY"] = db.decrypt(sec["blob"])
    return env


def heartbeat(conn, job_id=None):
    conn.execute(
        "INSERT INTO worker_heartbeats (worker_id, seen_at, job_id) VALUES (?,?,?) "
        "ON CONFLICT(worker_id) DO UPDATE SET seen_at=excluded.seen_at, job_id=excluded.job_id",
        (WORKER_ID, db.now(), job_id),
    )
    conn.commit()


def release_stale(conn):
    """Mark crashed running jobs failed; drop stale flow locks; kill orphan Chrome."""
    cutoff = time.time() - CRASH_S
    rows = conn.execute("SELECT id, started_at FROM jobs WHERE status='running'").fetchall()
    for r in rows:
        started = r["started_at"] or ""
        try:
            ts = time.mktime(time.strptime(started[:19], "%Y-%m-%dT%H:%M:%S"))
        except (ValueError, TypeError):
            ts = 0
        if ts and ts < cutoff:
            conn.execute(
                "UPDATE jobs SET status='failed', error='worker_crash', finished_at=? WHERE id=?",
                (db.now(), r["id"]),
            )
    conn.execute("DELETE FROM flow_locks")
    conn.commit()
    _kill_known_chrome()


def _kill_known_chrome():
    root = HERE / "data" / "tenants"
    if not root.exists():
        return
    for profile in root.glob("*/chrome-profile"):
        # Best-effort: pkill matching this user-data-dir.
        subprocess.run(
            ["pkill", "-f", str(profile)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )


def take_flow_lock(conn, job_id: str) -> bool:
    row = conn.execute("SELECT job_id FROM flow_locks WHERE profile_key='global'").fetchone()
    if row and row["job_id"]:
        return False
    conn.execute(
        "INSERT INTO flow_locks (profile_key, job_id, locked_at, heartbeat_at) "
        "VALUES ('global',?,?,?) "
        "ON CONFLICT(profile_key) DO UPDATE SET job_id=excluded.job_id, "
        "locked_at=excluded.locked_at, heartbeat_at=excluded.heartbeat_at",
        (job_id, db.now(), db.now()),
    )
    conn.commit()
    return True


def drop_flow_lock(conn, job_id: str):
    conn.execute("DELETE FROM flow_locks WHERE profile_key='global' AND job_id=?",
                 (job_id,))
    conn.commit()


def claim(conn, status: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM jobs WHERE status=? ORDER BY created_at LIMIT 1",
        (status,),
    ).fetchone()
    if not row:
        return None
    nxt = "running" if status == "queued" else "publishing"
    cur = conn.execute(
        "UPDATE jobs SET status=?, started_at=? WHERE id=? AND status=?",
        (nxt, db.now(), row["id"], status),
    )
    conn.commit()
    if cur.rowcount != 1:
        return None
    return dict(row)


def bind_result(conn, job_id: str, out_dir: Path) -> Path | None:
    """Set video_relpath ONLY from result.json / MAKEO_RESULT. No newest_video()."""
    manifest = out_dir / "result.json"
    if not manifest.exists():
        return None
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    video = data.get("video")
    if not video or data.get("exit", 1) != 0:
        return None
    path = Path(video)
    if not path.exists():
        return None
    try:
        rel = str(path.resolve().relative_to(HERE.resolve()))
    except ValueError:
        rel = str(path)
    sidecar = data.get("sidecar")
    conn.execute(
        "UPDATE jobs SET video_relpath=?, sidecar_path=? WHERE id=?",
        (rel, sidecar, job_id),
    )
    conn.commit()
    return path


def run_generate(conn, job: dict):
    brand = conn.execute("SELECT * FROM brands WHERE id=?", (job["brand_id"],)).fetchone()
    slug = brand["slug"]
    out_dir = tenant_root(slug) / "jobs" / job["id"]
    history = tenant_root(slug) / "jobs"
    cfg = out_dir / "brand.json"
    env = job_env(conn, job["brand_id"])
    env["MAKEO_JOB_ID"] = job["id"]
    cmd = [sys.executable, str(HERE / "daily.py"),
           "--skip-approve", "--config", str(cfg),
           "--out-dir", str(out_dir), "--history-dir", str(history)]
    if job.get("prompt"):
        cmd += ["--prompt", job["prompt"]]
        if job.get("caption"):
            cmd += ["--caption", job["caption"]]
    r = subprocess.run(cmd, cwd=str(HERE), env=env)
    video = bind_result(conn, job["id"], out_dir)
    if r.returncode != 0 or video is None:
        conn.execute(
            "UPDATE jobs SET status='failed', error=?, finished_at=? WHERE id=?",
            (f"generate_exit={r.returncode}", db.now(), job["id"]),
        )
        conn.commit()
        return
    conn.execute(
        "UPDATE jobs SET status='awaiting_approval' WHERE id=?",
        (job["id"],),
    )
    conn.commit()


def run_publish(conn, job: dict):
    """IG only. No Flow lock. Caption from coalesce(override, caption)."""
    try:
        from makeo.media import url_for_job
        url = url_for_job(conn, job["id"])
    except Exception:
        url = None
    if not url:
        conn.execute(
            "UPDATE jobs SET status='publish_failed', last_publish_error=? WHERE id=?",
            ("no media url -- start media server (PR 7)", job["id"]),
        )
        conn.commit()
        return
    video = HERE / job["video_relpath"] if job.get("video_relpath") else None
    cap = job.get("caption_override") or job.get("caption") or ""
    env = job_env(conn, job["brand_id"])
    env["MAKEO_JOB_ID"] = job["id"]
    cmd = [sys.executable, str(HERE / "post_instagram.py"),
           "--video-url", url, "--caption", cap]
    if video:
        cmd += ["--video", str(video), "--config",
                str(tenant_root(_slug(conn, job["brand_id"])) / "jobs" / job["id"] / "brand.json")]
    r = subprocess.run(cmd, cwd=str(HERE), env=env, capture_output=True, text=True)
    tail = ((r.stdout or "") + (r.stderr or ""))[-900:]
    if r.returncode != 0:
        conn.execute(
            "UPDATE jobs SET status='publish_failed', last_publish_error=?, finished_at=? "
            "WHERE id=?",
            (tail, db.now(), job["id"]),
        )
        conn.commit()
        return
    permalink = next((w for w in tail.split() if "instagram.com" in w), "")
    conn.execute(
        "UPDATE jobs SET status='posted', permalink=?, finished_at=? WHERE id=?",
        (permalink, db.now(), job["id"]),
    )
    conn.commit()


def _slug(conn, brand_id: str) -> str:
    return conn.execute("SELECT slug FROM brands WHERE id=?", (brand_id,)).fetchone()["slug"]


def loop_once(conn) -> bool:
    """Claim publishing (no Flow lock) else queued (Flow lock). Never both."""
    heartbeat(conn)
    pub = claim(conn, "publishing")
    if pub:
        heartbeat(conn, pub["id"])
        run_publish(conn, pub)
        heartbeat(conn)
        return True
    queued = claim(conn, "queued")
    if not queued:
        return False
    if not take_flow_lock(conn, queued["id"]):
        conn.execute("UPDATE jobs SET status='queued', started_at=NULL WHERE id=?",
                     (queued["id"],))
        conn.commit()
        return False
    try:
        heartbeat(conn, queued["id"])
        run_generate(conn, queued)
    finally:
        drop_flow_lock(conn, queued["id"])
        heartbeat(conn)
    return True


def main():
    conn = db.connect()
    release_stale(conn)
    print("worker up", flush=True)
    try:
        while True:
            if not loop_once(conn):
                time.sleep(POLL_S)
    except KeyboardInterrupt:
        print("worker stop", flush=True)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
