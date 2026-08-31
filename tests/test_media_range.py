"""Unit: Range headers, token TTL, path prefix."""

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from makeo import db, media
from tests.helpers import insert_brand, make_conn


class RangeHeaders(unittest.TestCase):
    def test_full_body(self):
        status, start, length, headers = media.range_headers(1000, None)
        self.assertEqual(status, 200)
        self.assertEqual(start, 0)
        self.assertEqual(length, 1000)
        self.assertEqual(headers["Accept-Ranges"], "bytes")

    def test_partial(self):
        status, start, length, headers = media.range_headers(1000, "bytes=0-99")
        self.assertEqual(status, 206)
        self.assertEqual(start, 0)
        self.assertEqual(length, 100)
        self.assertEqual(headers["Content-Range"], "bytes 0-99/1000")

    def test_unsatisfiable(self):
        status, start, length, _ = media.range_headers(100, "bytes=200-300")
        self.assertEqual(status, 416)


class TokenAndPrefix(unittest.TestCase):
    def test_expired_token_is_none(self):
        with tempfile.TemporaryDirectory() as td:
            conn = make_conn(td)
            bid, uid = insert_brand(conn, slug="exp", assets_dir=td)
            jid = db.insert_job(conn, brand_id=bid, user_id=uid, source="ui_trend")
            tok = media.create_token(conn, jid, ttl=timedelta(seconds=-10))
            # force expiry in the past
            past = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
            conn.execute("UPDATE media_tokens SET expires_at=? WHERE token=?", (past, tok))
            conn.commit()
            self.assertIsNone(media.resolve_file(conn, jid, tok))
            conn.close()

    def test_url_for_job_creates_token(self):
        with tempfile.TemporaryDirectory() as td:
            conn = make_conn(td)
            bid, uid = insert_brand(conn, slug="url", assets_dir=td)
            jid = db.insert_job(conn, brand_id=bid, user_id=uid, source="ui_trend")
            url = media.url_for_job(conn, jid)
            self.assertIn(jid, url)
            self.assertIn("/public/media/", url)
            conn.close()

    def test_wrong_token_none(self):
        with tempfile.TemporaryDirectory() as td:
            conn = make_conn(td)
            bid, uid = insert_brand(conn, slug="badtok", assets_dir=td)
            jid = db.insert_job(conn, brand_id=bid, user_id=uid, source="ui_trend")
            media.create_token(conn, jid)
            self.assertIsNone(media.resolve_file(conn, jid, "not-the-token"))
            conn.close()


if __name__ == "__main__":
    unittest.main()
