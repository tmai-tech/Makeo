"""PR 6b: result.json bind; never newest_video; env pop."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import worker
from makeo import db


class BindResult(unittest.TestCase):
    def test_binds_only_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            conn = db.connect(Path(td) / "t.db")
            uid = db.ensure_operator(conn)
            bid = db.new_id()
            conn.execute(
                "INSERT INTO brands (id,user_id,slug,name,config,assets_dir,created_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (bid, uid, "t", "T", "{}", td, db.now()),
            )
            jid = db.insert_job(conn, brand_id=bid, user_id=uid, source="ui_trend")
            out = Path(td) / "job"
            out.mkdir()
            older = out / "flow-old-branded.mp4"
            older.write_bytes(b"old")
            (out / "result.json").write_text(json.dumps({
                "job_id": jid, "video": str(out / "missing.mp4"), "exit": 0,
            }), encoding="utf-8")
            self.assertIsNone(worker.bind_result(conn, jid, out))
            real = out / f"flow-{jid}-branded.mp4"
            real.write_bytes(b"new")
            (out / "result.json").write_text(json.dumps({
                "job_id": jid, "video": str(real), "sidecar": None, "exit": 0,
            }), encoding="utf-8")
            got = worker.bind_result(conn, jid, out)
            self.assertEqual(got, real)
            row = db.get_job(conn, jid)
            self.assertTrue(row["video_relpath"].endswith(real.name))
            conn.close()

    def test_missing_manifest_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            conn = db.connect(Path(td) / "t.db")
            self.assertIsNone(worker.bind_result(conn, "x", Path(td)))
            conn.close()


class EnvPop(unittest.TestCase):
    def test_pops_host_ig(self):
        os.environ["IG_USER_ID"] = "buzzit-host"
        os.environ["IG_ACCESS_TOKEN"] = "buzzit-token"
        os.environ["GEMINI_API_KEY"] = "host-gemini"
        with tempfile.TemporaryDirectory() as td:
            conn = db.connect(Path(td) / "t.db")
            env = worker.job_env(conn, "no-such-brand")
            self.assertNotIn("IG_USER_ID", env)
            self.assertNotIn("IG_ACCESS_TOKEN", env)
            self.assertNotIn("GEMINI_API_KEY", env)
            conn.close()
        os.environ.pop("IG_USER_ID", None)
        os.environ.pop("IG_ACCESS_TOKEN", None)
        os.environ.pop("GEMINI_API_KEY", None)


class Claim(unittest.TestCase):
    def test_publish_preferred_over_queued(self):
        with tempfile.TemporaryDirectory() as td:
            conn = db.connect(Path(td) / "t.db")
            uid = db.ensure_operator(conn)
            bid = db.new_id()
            conn.execute(
                "INSERT INTO brands (id,user_id,slug,name,config,assets_dir,created_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (bid, uid, "t2", "T", "{}", td, db.now()),
            )
            q = db.insert_job(conn, brand_id=bid, user_id=uid, source="ui_trend")
            p = db.insert_job(conn, brand_id=bid, user_id=uid, source="ui_trend",
                              status="publishing")
            conn.commit()
            with mock.patch.object(worker, "run_publish") as pub, \
                 mock.patch.object(worker, "run_generate") as gen:
                worker.loop_once(conn)
                pub.assert_called_once()
                gen.assert_not_called()
                self.assertEqual(pub.call_args[0][1]["id"], p)
            conn.close()


if __name__ == "__main__":
    unittest.main()
