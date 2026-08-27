"""PR 2: BrandConfig load/validate. No network."""

import json
import tempfile
import unittest
from pathlib import Path

import brand_config as bc


class LoadBuzzit(unittest.TestCase):
    def test_bundled_buzzit_loads(self):
        cfg = bc.load(bc.default_path())
        self.assertEqual(cfg.name, "Buzzit")
        self.assertEqual(cfg.slug, "buzzit")
        self.assertEqual(cfg.model, "gemini-3.6-flash")
        self.assertEqual(cfg.dedup_max_topics, 10)
        self.assertEqual(cfg.pip_from_s, 4.0)
        self.assertEqual(cfg.endcard_seconds, 3.0)
        self.assertEqual(cfg.pip_border_color, "0xE8B84B")
        self.assertIn("Buzz. Share. Earn", cfg.manual_caption)
        self.assertTrue(cfg.flow_project_url.startswith("https://labs.google/fx"))
        text = cfg.format_instructions("headline-one", "Already covered:\n- old")
        self.assertIn("headline-one", text)
        self.assertIn("Already covered", text)
        self.assertIn(cfg.hook, text)
        self.assertIn(cfg.locale.setting_rule, text)
        self.assertIn("{", text)  # JSON example survived format()


class Validation(unittest.TestCase):
    def setUp(self):
        self.base = json.loads(bc.default_path().read_text(encoding="utf-8"))
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "screenshot").mkdir()
        for name in ("logo.png", "splash_video.gif", "feedscreen.png"):
            (self.root / "screenshot" / name).write_bytes(b"x")

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, **overrides):
        data = dict(self.base)
        data.update(overrides)
        p = self.root / "cfg.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        return p

    def test_missing_name(self):
        p = self._write(name="")
        with self.assertRaises(bc.BrandConfigError) as ctx:
            bc.load(p, repo_root=self.root)
        self.assertIn("name", str(ctx.exception))

    def test_unknown_placeholder(self):
        tmpl = self.base["instructions_template"] + "\n{not_a_field}"
        p = self._write(instructions_template=tmpl)
        with self.assertRaises(bc.BrandConfigError) as ctx:
            bc.load(p, repo_root=self.root)
        self.assertIn("unknown placeholder", str(ctx.exception))

    def test_missing_required_placeholder(self):
        p = self._write(instructions_template="{brand} {headlines} {recent}")
        with self.assertRaises(bc.BrandConfigError) as ctx:
            bc.load(p, repo_root=self.root)
        self.assertIn("missing placeholder", str(ctx.exception))

    def test_feed_ssrf_blocked(self):
        p = self._write(feeds=["http://169.254.169.254/latest/meta-data"])
        with self.assertRaises(bc.BrandConfigError) as ctx:
            bc.load(p, repo_root=self.root)
        self.assertIn("allowlisted", str(ctx.exception))

    def test_asset_parent_escape(self):
        assets = dict(self.base["assets"], logo="../secret.png")
        p = self._write(assets=assets)
        with self.assertRaises(bc.BrandConfigError) as ctx:
            bc.load(p, repo_root=self.root)
        self.assertIn("relative path", str(ctx.exception))

    def test_absolute_asset_rejected(self):
        assets = dict(self.base["assets"], logo="/etc/passwd")
        p = self._write(assets=assets)
        with self.assertRaises(bc.BrandConfigError):
            bc.load(p, repo_root=self.root)


if __name__ == "__main__":
    unittest.main()
