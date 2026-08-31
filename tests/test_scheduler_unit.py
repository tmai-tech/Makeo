"""Unit: weekday parse and dead-token skip."""

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from makeo import db, scheduler
from tests.helpers import insert_brand, make_conn


class ParseDays(unittest.TestCase):
    def test_all(self):
        self.assertEqual(scheduler.parse_days("all"), set(range(7)))
        self.assertEqual(scheduler.parse_days("*"), set(range(7)))

    def test_names(self):
        self.assertEqual(scheduler.parse_days("mon,wed,fri"), {0, 2, 4})


class TokenDead(unittest.TestCase):
    def test_expired_token_enqueues_failed(self):
        with tempfile.TemporaryDirectory() as td:
            conn = make_conn(td)
            bid, uid = insert_brand(conn, slug="buzzit", assets_dir=td)
            past = datetime(2020, 1, 1, tzinfo=timezone.utc).isoformat()
            conn.execute(
                "INSERT INTO ig_accounts (brand_id, ig_user_id, token_enc, "
                "token_expires_at, auth_method) VALUES (?,?,?,?,?)",
                (bid, "1", b"x", past, "paste"),
            )
            conn.execute(
                "INSERT INTO schedules (brand_id, enabled, timezone, local_time, days) "
                "VALUES (?,?,?,?,?)",
                (bid, 1, "Asia/Kolkata", "00:00", "all"),
            )
            conn.commit()
            local = datetime(2026, 8, 27, 19, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
            made = scheduler.tick(conn, now=local)
            self.assertEqual(made, [])
            row = conn.execute(
                "SELECT status, error FROM jobs WHERE brand_id=?", (bid,)
            ).fetchone()
            self.assertEqual(row["status"], "failed")
            self.assertEqual(row["error"], "ig_token_invalid")
            conn.close()

    def test_token_dead_false_when_missing(self):
        with tempfile.TemporaryDirectory() as td:
            conn = make_conn(td)
            bid, _ = insert_brand(conn, slug="notok", assets_dir=td)
            now = datetime.now(timezone.utc)
            self.assertFalse(scheduler.token_dead(conn, bid, now))
            conn.close()


if __name__ == "__main__":
    unittest.main()
