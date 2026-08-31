"""Full-proof integration: enqueue → generate bind → approve → publish caption.

No Gemini, Flow, or Instagram network. Subprocesses are mocked.
This is the contract the worker + API must keep for every brand.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from makeo import db, enqueue
from tests.helpers import ensure_master_key, make_conn
import worker


class FullPipeline(unittest.TestCase):
    def setUp(self):
        ensure_master_key()
        self.td = tempfile.TemporaryDirectory()
        self.conn = make_conn(self.td.name)

    def tearDown(self):
        self.conn.close()
        self.td.cleanup()

    def test_custom_prompt_to_posted(self):
        jid = enqueue.enqueue(
            "buzzit", prompt="8s vertical proof", caption="sidecar-caption",
            conn=self.conn,
        )
        job = db.get_job(self.conn, jid)
        self.assertEqual(job["status"], "queued")
        self.assertEqual(job["source"], "ui_custom")
        dest = enqueue.HERE / "data" / "tenants" / "buzzit" / "jobs" / jid
        self.assertTrue((dest / "brand.json").exists())

        video = dest / f"flow-{jid}-branded.mp4"
        sidecar = dest / f"flow-{jid}-branded.json"
        sidecar.write_text(json.dumps({"caption": "sidecar-caption"}), encoding="utf-8")

        def fake_generate(conn, job):
            video.write_bytes(b"fake-mp4")
            (dest / "result.json").write_text(json.dumps({
                "job_id": job["id"],
                "video": str(video),
                "sidecar": str(sidecar),
                "exit": 0,
            }), encoding="utf-8")
            path = worker.bind_result(conn, job["id"], dest)
            self.assertEqual(path, video)
            conn.execute(
                "UPDATE jobs SET status='awaiting_approval' WHERE id=?",
                (job["id"],),
            )
            conn.commit()

        with mock.patch.object(worker, "run_generate", side_effect=fake_generate):
            self.assertTrue(worker.loop_once(self.conn))

        job = db.get_job(self.conn, jid)
        self.assertEqual(job["status"], "awaiting_approval")
        self.assertTrue(job["video_relpath"].endswith(video.name))

        # two branded files already there must not steal the handle
        older = dest / "flow-old-branded.mp4"
        older.write_bytes(b"old")
        rebound = worker.bind_result(self.conn, jid, dest)
        self.assertEqual(rebound, video)

        self.conn.execute(
            "UPDATE jobs SET status='publishing', caption_override=? WHERE id=?",
            ("human-override", jid),
        )
        self.conn.commit()
        job = db.get_job(self.conn, jid)

        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = list(cmd)
            captured["env"] = kwargs.get("env") or {}
            return mock.Mock(returncode=0, stdout="ok https://instagram.com/reel/PROOF\n",
                             stderr="")

        with mock.patch.object(worker, "tenant_root", return_value=dest.parent.parent), \
             mock.patch("makeo.media.url_for_job",
                        return_value="https://example.test/public/media/x/t"), \
             mock.patch("subprocess.run", side_effect=fake_run):
            worker.run_publish(self.conn, dict(job))

        self.assertIn("--caption", captured["cmd"])
        cap = captured["cmd"][captured["cmd"].index("--caption") + 1]
        self.assertEqual(cap, "human-override")
        self.assertNotIn("sidecar-caption", captured["cmd"])
        self.assertEqual(captured["env"].get("MAKEO_JOB_ID"), jid)

        job = db.get_job(self.conn, jid)
        self.assertEqual(job["status"], "posted")
        self.assertIn("instagram.com/reel/PROOF", job["permalink"])

    def test_missing_result_fails_closed(self):
        jid = enqueue.enqueue("buzzit", prompt="will fail", conn=self.conn)

        def empty_generate(conn, job):
            dest = enqueue.HERE / "data" / "tenants" / "buzzit" / "jobs" / job["id"]
            video = worker.bind_result(conn, job["id"], dest)
            if video is None:
                conn.execute(
                    "UPDATE jobs SET status='failed', error='generate_exit=0', "
                    "finished_at=? WHERE id=?",
                    (db.now(), job["id"]),
                )
                conn.commit()

        with mock.patch.object(worker, "run_generate", side_effect=empty_generate):
            worker.loop_once(self.conn)
        job = db.get_job(self.conn, jid)
        self.assertEqual(job["status"], "failed")
        self.assertIsNone(job["video_relpath"])

    def test_publish_preferred_over_generate(self):
        q = enqueue.enqueue("buzzit", prompt="queued", conn=self.conn)
        p = enqueue.enqueue("buzzit", prompt="pub", conn=self.conn)
        self.conn.execute("UPDATE jobs SET status='publishing' WHERE id=?", (p,))
        self.conn.commit()
        with mock.patch.object(worker, "run_publish") as pub, \
             mock.patch.object(worker, "run_generate") as gen:
            worker.loop_once(self.conn)
            pub.assert_called_once()
            gen.assert_not_called()
            self.assertEqual(pub.call_args[0][1]["id"], p)
        self.assertEqual(db.get_job(self.conn, q)["status"], "queued")


class IsolationProof(unittest.TestCase):
    def test_job_env_never_keeps_host_buzzit(self):
        os.environ["IG_USER_ID"] = "buzzit-host"
        os.environ["IG_ACCESS_TOKEN"] = "buzzit-token"
        os.environ["GEMINI_API_KEY"] = "buzzit-gemini"
        try:
            with tempfile.TemporaryDirectory() as td:
                conn = make_conn(td)
                env = worker.job_env(conn, "no-such-brand")
                self.assertNotIn("IG_USER_ID", env)
                self.assertNotIn("IG_ACCESS_TOKEN", env)
                self.assertNotIn("GEMINI_API_KEY", env)
                conn.close()
        finally:
            os.environ.pop("IG_USER_ID", None)
            os.environ.pop("IG_ACCESS_TOKEN", None)
            os.environ.pop("GEMINI_API_KEY", None)


if __name__ == "__main__":
    unittest.main()
