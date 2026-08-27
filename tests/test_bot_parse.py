"""PR 11: custom_id parse. No newest_video."""

import unittest

import bot


class CustomId(unittest.TestCase):
    def test_ok(self):
        self.assertEqual(bot.parse_custom_id("makeo:abc123:approve"),
                         ("abc123", "approve"))
        self.assertEqual(bot.parse_custom_id("makeo:abc123:reject"),
                         ("abc123", "reject"))

    def test_rejects_old_buzzit(self):
        self.assertIsNone(bot.parse_custom_id("buzzit:approve"))
        self.assertIsNone(bot.parse_custom_id("makeo:abc:maybe"))

    def test_no_newest_video(self):
        self.assertFalse(hasattr(bot, "newest_video"))
        self.assertFalse(hasattr(bot, "watch_trigger"))


if __name__ == "__main__":
    unittest.main()
