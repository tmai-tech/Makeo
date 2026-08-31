"""Unit: SQLite schema, Fernet, OAuth-ready auth_method."""

import os
import tempfile
import unittest
from pathlib import Path

from tests.helpers import ensure_master_key, make_conn

from makeo import db


class SchemaAndCrypto(unittest.TestCase):
    def setUp(self):
        ensure_master_key()
        self.td = tempfile.TemporaryDirectory()
        self.conn = make_conn(self.td.name)

    def tearDown(self):
        self.conn.close()
        self.td.cleanup()

    def test_required_tables(self):
        names = {r[0] for r in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        for t in ("users", "brands", "jobs", "ig_accounts", "secrets",
                  "flow_locks", "worker_heartbeats", "media_tokens",
                  "schedules", "approvals", "brand_alerts"):
            self.assertIn(t, names)

    def test_encrypt_roundtrip(self):
        blob = db.encrypt("tenant-token")
        self.assertIsInstance(blob, (bytes, memoryview))
        self.assertEqual(db.decrypt(bytes(blob)), "tenant-token")

    def test_missing_master_key_fails(self):
        old = os.environ.pop("MAKEO_MASTER_KEY", None)
        try:
            with self.assertRaises(RuntimeError):
                db.fernet()
        finally:
            if old:
                os.environ["MAKEO_MASTER_KEY"] = old

    def test_auth_method_column(self):
        cols = {r[1] for r in self.conn.execute("PRAGMA table_info(ig_accounts)")}
        self.assertIn("auth_method", cols)

    def test_insert_and_get_job(self):
        uid = db.ensure_operator(self.conn)
        bid = db.new_id()
        self.conn.execute(
            "INSERT INTO brands (id,user_id,slug,name,config,assets_dir,created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (bid, uid, "u", "U", "{}", self.td.name, db.now()),
        )
        jid = db.insert_job(self.conn, brand_id=bid, user_id=uid, source="ui_trend")
        self.conn.commit()
        row = db.get_job(self.conn, jid)
        self.assertEqual(row["status"], "queued")
        self.assertEqual(row["source"], "ui_trend")
        self.assertIsNone(row["caption_override"])


class MigrateExisting(unittest.TestCase):
    def test_adds_auth_method_to_old_table(self):
        ensure_master_key()
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "old.db"
            import sqlite3
            raw = sqlite3.connect(str(path))
            raw.execute(
                "CREATE TABLE ig_accounts (brand_id TEXT PRIMARY KEY, "
                "ig_user_id TEXT, username TEXT, token_enc BLOB, "
                "token_expires_at TEXT, last_whoami_at TEXT)"
            )
            raw.commit()
            raw.close()
            conn = db.connect(path)
            cols = {r[1] for r in conn.execute("PRAGMA table_info(ig_accounts)")}
            self.assertIn("auth_method", cols)
            conn.close()


if __name__ == "__main__":
    unittest.main()
