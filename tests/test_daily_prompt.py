"""PR 3: out-dir, history-dir, manual caption, result contract."""

import json
import tempfile
import unittest
from pathlib import Path

import daily
import make_prompt


class ManualPrompt(unittest.TestCase):
    def test_writes_under_out_dir(self):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td)
            daily.write_manual_prompt("hello veo", caption="cap", out_dir=dest)
            self.assertEqual((dest / "prompt.txt").read_text(encoding="utf-8"), "hello veo")
            meta = json.loads((dest / "today.json").read_text(encoding="utf-8"))
            self.assertEqual(meta["caption"], "cap")
            self.assertEqual(meta["brand_link"], "manual")

    def test_non_buzzit_config_skips_slogan(self):
        cfg = type("C", (), {"name": "Acme", "manual_caption": "Hello Acme"})()
        with tempfile.TemporaryDirectory() as td:
            daily.write_manual_prompt("p", out_dir=td, cfg=cfg)
            meta = json.loads((Path(td) / "today.json").read_text(encoding="utf-8"))
            self.assertNotIn("Buzzit", meta["caption"])
            self.assertEqual(meta["caption"], "Hello Acme")

    def test_buzzit_default_slogan(self):
        with tempfile.TemporaryDirectory() as td:
            daily.write_manual_prompt("p", out_dir=td)
            meta = json.loads((Path(td) / "today.json").read_text(encoding="utf-8"))
            self.assertIn("Buzzit", meta["caption"])


class HistoryDir(unittest.TestCase):
    def test_sibling_job_dirs(self):
        with tempfile.TemporaryDirectory() as td:
            jobs = Path(td)
            current = jobs / "job-now"
            current.mkdir()
            a = jobs / "job-a"
            b = jobs / "job-b"
            a.mkdir()
            b.mkdir()
            (a / "flow-1.json").write_text(json.dumps({"topic": "Kangana"}), encoding="utf-8")
            (b / "flow-2.json").write_text(json.dumps({"topic": "IPL final"}), encoding="utf-8")
            (b / "flow-2-branded.json").write_text(
                json.dumps({"topic": "should-skip"}), encoding="utf-8")
            used = make_prompt.recent_topics(jobs, limit=10)
            self.assertIn("Kangana", used)
            self.assertIn("IPL final", used)
            self.assertNotIn("should-skip", used)


class ResultContract(unittest.TestCase):
    def test_write_result(self):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td)
            video = dest / "flow-abc.mp4"
            video.write_bytes(b"x")
            (dest / "flow-abc.json").write_text("{}", encoding="utf-8")
            daily.write_result(dest, "abc", video)
            payload = json.loads((dest / "result.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["job_id"], "abc")
            self.assertTrue(payload["video"].endswith("flow-abc.mp4"))
            self.assertEqual(payload["exit"], 0)

    def test_job_video_prefers_branded(self):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td)
            (dest / "flow-abc.mp4").write_bytes(b"a")
            (dest / "flow-abc-branded.mp4").write_bytes(b"b")
            got = daily.job_video(dest, "abc")
            self.assertTrue(got.name.endswith("-branded.mp4"))

    def test_job_video_missing(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertIsNone(daily.job_video(td, "nope"))


if __name__ == "__main__":
    unittest.main()
