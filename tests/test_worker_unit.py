"""Unit: worker never load_env; flow lock; crash timeout."""

import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

import worker
from makeo import db
from tests.helpers import insert_brand, make_conn


class NoLoadEnv(unittest.TestCase):
    def test_module_has_no_load_env(self):
        self.assertFalse(hasattr(worker, "load_env"))
        self.assertFalse(callable(getattr(worker, "load_env", None)))


class FlowLock(unittest.TestCase):
    def test_second_lock_fails(self):
        with tempfile.TemporaryDirectory() as td:
            conn = make_conn(td)
            self.assertTrue(worker.take_flow_lock(conn, "job-a"))
            self.assertFalse(worker.take_flow_lock(conn, "job-b"))
            worker.drop_flow_lock(conn, "job-a")
            self.assertTrue(worker.take_flow_lock(conn, "job-b"))
            conn.close()


class CrashTimeout(unittest.TestCase):
    def test_old_running_marked_failed(self):
        with tempfile.TemporaryDirectory() as td:
            conn = make_conn(td)
            bid, uid = insert_brand(conn, slug="crash", assets_dir=td)
            jid = db.insert_job(conn, brand_id=bid, user_id=uid, source="ui_trend",
                                status="running")
            old = (datetime.now(timezone.utc) - timedelta(hours=3)).strftime(
                "%Y-%m-%dT%H:%M:%S")
            conn.execute("UPDATE jobs SET started_at=? WHERE id=?", (old, jid))
            conn.commit()
            with mock.patch.object(worker, "_kill_known_chrome"):
                worker.release_stale(conn)
            row = db.get_job(conn, jid)
            self.assertEqual(row["status"], "failed")
            self.assertEqual(row["error"], "worker_crash")
            conn.close()


class JobEnvPopsHost(unittest.TestCase):
    def test_sets_tenant_after_pop(self):
        os.environ["IG_USER_ID"] = "host-ig"
        os.environ["IG_ACCESS_TOKEN"] = "host-tok"
        os.environ["GEMINI_API_KEY"] = "host-gem"
        with tempfile.TemporaryDirectory() as td:
            conn = make_conn(td)
            bid, _ = insert_brand(conn, slug="envb", assets_dir=td)
            enc = db.encrypt("tenant-tok")
            conn.execute(
                "INSERT INTO ig_accounts (brand_id, ig_user_id, token_enc, auth_method) "
                "VALUES (?,?,?,?)",
                (bid, "tenant-ig", enc, "paste"),
            )
            gem = db.encrypt("tenant-gem")
            conn.execute(
                "INSERT INTO secrets (id, brand_id, kind, blob) VALUES (?,?,?,?)",
                (db.new_id(), bid, "gemini_key", gem),
            )
            conn.commit()
            env = worker.job_env(conn, bid)
            self.assertEqual(env["IG_USER_ID"], "tenant-ig")
            self.assertEqual(env["IG_ACCESS_TOKEN"], "tenant-tok")
            self.assertEqual(env["GEMINI_API_KEY"], "tenant-gem")
            conn.close()
        os.environ.pop("IG_USER_ID", None)
        os.environ.pop("IG_ACCESS_TOKEN", None)
        os.environ.pop("GEMINI_API_KEY", None)


if __name__ == "__main__":
    unittest.main()
