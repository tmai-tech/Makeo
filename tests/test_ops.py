"""PR 12: 30-day retention clears job dirs."""

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from makeo import db, enqueue
from makeo import ops


class Retain(unittest.TestCase):
    def test_drops_old_job_dir(self):
        with tempfile.TemporaryDirectory() as td:
            conn = db.connect(Path(td) / "t.db")
            jid = enqueue.enqueue("buzzit", prompt="old", conn=conn)
            dest = enqueue.HERE / "data" / "tenants" / "buzzit" / "jobs" / jid
            self.assertTrue(dest.exists())
            old = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
            conn.execute(
                "UPDATE jobs SET status='posted', finished_at=? WHERE id=?",
                (old, jid),
            )
            conn.commit()
            n = ops.retain(conn)
            self.assertEqual(n, 1)
            self.assertFalse(dest.exists())
            conn.close()


if __name__ == "__main__":
    unittest.main()
