"""PR 7: one-file Range path + catch-up scheduler."""

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from makeo import db, media, scheduler


class MediaPath(unittest.TestCase):
    def test_parse_ok(self):
        self.assertEqual(
            media.parse_public_path("/public/media/abc/tok"),
            ("abc", "tok"),
        )

    def test_traversal_rejected(self):
        self.assertIsNone(media.parse_public_path("/public/media/abc/../other.mp4"))
        self.assertIsNone(media.parse_public_path("/public/media/abc/tok/../x"))
        self.assertIsNone(media.parse_public_path("/public/media/abc/tok/extra"))

    def test_resolve_prefix(self):
        with tempfile.TemporaryDirectory() as td:
            conn = db.connect(Path(td) / "t.db")
            uid = db.ensure_operator(conn)
            bid = db.new_id()
            conn.execute(
                "INSERT INTO brands (id,user_id,slug,name,config,assets_dir,created_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (bid, uid, "m", "M", "{}", td, db.now()),
            )
            jid = db.insert_job(conn, brand_id=bid, user_id=uid, source="ui_trend")
            # path outside data/ and out/ must 404
            conn.execute("UPDATE jobs SET video_relpath=? WHERE id=?",
                         ("/etc/passwd", jid))
            tok = media.create_token(conn, jid)
            self.assertIsNone(media.resolve_file(conn, jid, tok))
            conn.close()


class Scheduler(unittest.TestCase):
    def test_catch_up_after_minute(self):
        with tempfile.TemporaryDirectory() as td:
            conn = db.connect(Path(td) / "t.db")
            uid = db.ensure_operator(conn)
            # reuse buzzit json via enqueue path — insert brand+schedule only
            bid = db.new_id()
            conn.execute(
                "INSERT INTO brands (id,user_id,slug,name,config,assets_dir,created_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (bid, uid, "schedbrand", "S", "{}", td, db.now()),
            )
            conn.execute(
                "INSERT INTO schedules (brand_id, enabled, timezone, local_time, days) "
                "VALUES (?,?,?,?,?)",
                (bid, 1, "Asia/Kolkata", "19:00", "all"),
            )
            conn.commit()
            local = datetime(2026, 8, 27, 19, 40, tzinfo=ZoneInfo("Asia/Kolkata"))
            # no brands/schedbrand.json — enqueue will fail. Use brands/buzzit by slug update
            conn.execute("UPDATE brands SET slug='buzzit' WHERE id=?", (bid,))
            conn.commit()
            made = scheduler.tick(conn, now=local)
            self.assertEqual(len(made), 1)
            again = scheduler.tick(conn, now=local)
            self.assertEqual(again, [])
            conn.close()

    def test_before_local_time_skips(self):
        with tempfile.TemporaryDirectory() as td:
            conn = db.connect(Path(td) / "t.db")
            uid = db.ensure_operator(conn)
            bid = db.new_id()
            conn.execute(
                "INSERT INTO brands (id,user_id,slug,name,config,assets_dir,created_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (bid, uid, "buzzit", "B", "{}", td, db.now()),
            )
            conn.execute(
                "INSERT INTO schedules (brand_id, enabled, timezone, local_time, days) "
                "VALUES (?,?,?,?,?)",
                (bid, 1, "Asia/Kolkata", "19:00", "all"),
            )
            conn.commit()
            local = datetime(2026, 8, 27, 18, 59, tzinfo=ZoneInfo("Asia/Kolkata"))
            self.assertEqual(scheduler.tick(conn, now=local), [])
            conn.close()


if __name__ == "__main__":
    unittest.main()
