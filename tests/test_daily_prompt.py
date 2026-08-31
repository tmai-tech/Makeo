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


class ConfigTemplate(unittest.TestCase):
    def test_llm_prompt_uses_instructions_template(self):
        cfg = type("C", (), {
            "format_instructions": lambda self, h, r: f"TMPL|{h}|{r}",
        })()
        text = make_prompt.llm_prompt(cfg, ["Topic A"], "Already covered:\n- old")
        self.assertTrue(text.startswith("TMPL|"))
        self.assertIn("Topic A", text)
        self.assertNotIn("You write ONE 8-second", text)

    def test_no_config_keeps_repo_default(self):
        text = make_prompt.llm_prompt(None, ["Topic A"], "")
        self.assertIn("You write ONE 8-second", text)

    def test_empty_feeds_use_locale_builder(self):
        cfg = type("C", (), {
            "feeds": [],
            "locale": make_prompt.bc.Locale(language="en-IN", region="IN"),
            "rss_query": "",
        })()
        urls = make_prompt.feed_urls(cfg)
        self.assertTrue(all(make_prompt.bc.feed_host_allowed(u) for u in urls))
        self.assertIn("geo=IN", urls[1])

    def test_headlines_skip_ssrf_host(self):
        titles = make_prompt.headlines(limit=5, feeds=["http://127.0.0.1/secret"])
        self.assertEqual(titles, [])


class NoUnbrandedJob(unittest.TestCase):
    def test_job_id_rejects_no_brand(self):
        import os
        import subprocess
        import sys
        env = os.environ.copy()
        env["MAKEO_JOB_ID"] = "job-unbranded"
        r = subprocess.run(
            [sys.executable, "daily.py", "--no-brand", "--skip-generate", "--skip-approve"],
            cwd=str(Path(__file__).resolve().parents[1]),
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("no-brand", (r.stderr or r.stdout or "").lower())


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
