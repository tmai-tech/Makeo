"""Unit: prompt parse, template vs fallback, feed allowlist."""

import unittest

import make_prompt


class Parse(unittest.TestCase):
    def test_fences(self):
        d = make_prompt.parse(
            '```json\n{"topic":"t","veo_prompt":"p","caption":"c"}\n```'
        )
        self.assertEqual(d["topic"], "t")
        self.assertEqual(d["veo_prompt"], "p")

    def test_brand_link_alias(self):
        d = make_prompt.parse(
            '{"topic":"t","veo_prompt":"p","caption":"c","brand_link":"tie"}'
        )
        self.assertEqual(d["buzzit_link"], "tie")

    def test_missing_fields_exit(self):
        with self.assertRaises(SystemExit):
            make_prompt.parse('{"topic":"t"}')


class Template(unittest.TestCase):
    def test_config_template(self):
        cfg = type("C", (), {
            "format_instructions": lambda self, h, r: f"CFG|{h}|{r}",
        })()
        text = make_prompt.llm_prompt(cfg, ["A"], "old")
        self.assertTrue(text.startswith("CFG|"))
        self.assertNotIn("You write ONE 8-second", text)

    def test_default_without_config(self):
        text = make_prompt.llm_prompt(None, ["A"], "")
        self.assertIn("You write ONE 8-second", text)

    def test_ssrf_feed_skipped(self):
        self.assertEqual(
            make_prompt.headlines(limit=3, feeds=["http://127.0.0.1/secret"]),
            [],
        )


if __name__ == "__main__":
    unittest.main()
