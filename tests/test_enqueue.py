"""PR 6a: schema + job-private snapshot dir."""

import json
import tempfile
import unittest
from pathlib import Path

from makeo import db, enqueue


class Schema(unittest.TestCase):
    def test_creates_tables(self):
        with tempfile.TemporaryDirectory() as td:
            conn = db.connect(Path(td) / "t.db")
            names = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            for t in ("users", "brands", "jobs", "ig_accounts", "secrets",
                      "flow_locks", "worker_heartbeats", "media_tokens"):
                self.assertIn(t, names)
            conn.close()


class Snapshot(unittest.TestCase):
    def test_enqueue_buzzit_copies_assets(self):
        with tempfile.TemporaryDirectory() as td:
            conn = db.connect(Path(td) / "t.db")
            # point enqueue HERE... enqueue.HERE is repo; that's fine
            jid = enqueue.enqueue("buzzit", prompt="test prompt", conn=conn)
            row = db.get_job(conn, jid)
            self.assertEqual(row["status"], "queued")
            self.assertEqual(row["source"], "ui_custom")
            dest = enqueue.HERE / "data" / "tenants" / "buzzit" / "jobs" / jid
            self.assertTrue((dest / "brand.json").exists())
            snap = json.loads((dest / "brand.json").read_text(encoding="utf-8"))
            self.assertEqual(snap["name"], "Buzzit")
            self.assertTrue((dest / "assets" / "logo.png").exists())
            self.assertTrue((dest / "assets" / "splash_video.gif").exists())
            conn.close()


if __name__ == "__main__":
    unittest.main()
