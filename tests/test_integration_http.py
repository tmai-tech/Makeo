"""Integration: FastAPI login, CSRF, brand isolation, compose, approve, media."""

import json
import os
import re
import tempfile
import unittest
from pathlib import Path

from cryptography.fernet import Fernet

os.environ["MAKEO_MASTER_KEY"] = Fernet.generate_key().decode()


def _csrf(html: str) -> str:
    m = re.search(r'name="csrf" value="([^"]+)"', html)
    if not m:
        raise AssertionError("no csrf in page")
    return m.group(1)


class HttpApp(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        import makeo.db as dbmod
        self._orig = dbmod.DB_PATH
        dbmod.DB_PATH = Path(self.td.name) / "t.db"
        import importlib
        import app.main as main
        importlib.reload(main)
        from fastapi.testclient import TestClient
        from app.main import create_user, app
        create_user("owner@x.test", "secret")
        create_user("other@x.test", "secret")
        self.client = TestClient(app)
        self.main = main

    def tearDown(self):
        import makeo.db as dbmod
        dbmod.DB_PATH = self._orig
        self.td.cleanup()

    def _login(self, email="owner@x.test"):
        page = self.client.get("/login")
        r = self.client.post("/login", data={
            "email": email, "password": "secret", "csrf": _csrf(page.text),
        }, follow_redirects=False)
        self.assertIn(r.status_code, (302, 303))

    def test_home_redirects_when_logged_out(self):
        r = self.client.get("/", follow_redirects=False)
        self.assertIn(r.status_code, (302, 303))
        self.assertIn("/login", r.headers.get("location", ""))

    def test_bad_csrf_rejected(self):
        self._login()
        with self.assertRaises(Exception):
            self.client.post("/brands/new", data={
                "name": "X", "slug": "x", "csrf": "nope",
            })

    def test_create_brand_and_compose_enqueues(self):
        self._login()
        page = self.client.get("/brands/new")
        r = self.client.post("/brands/new", data={
            "name": "Acme", "slug": "acme", "pitch": "p", "hook": "h",
            "csrf": _csrf(page.text),
        }, follow_redirects=False)
        self.assertIn(r.status_code, (302, 303))
        loc = r.headers["location"]
        self.assertIn("/brands/", loc)
        bid = loc.rstrip("/").split("/")[-1]
        compose = self.client.get(f"/brands/{bid}/compose")
        self.assertEqual(compose.status_code, 200)
        r = self.client.post(f"/brands/{bid}/compose", data={
            "csrf": _csrf(compose.text),
            "prompt": "8s vertical test",
            "caption": "hello",
        }, follow_redirects=False)
        self.assertIn(r.status_code, (302, 303))
        from makeo import db
        c = db.connect()
        job = c.execute(
            "SELECT * FROM jobs WHERE brand_id=? ORDER BY created_at DESC",
            (bid,),
        ).fetchone()
        c.close()
        self.assertIsNotNone(job)
        self.assertEqual(job["status"], "queued")
        self.assertEqual(job["source"], "ui_custom")
        self.assertEqual(job["prompt"], "8s vertical test")

    def test_approve_sets_publishing_and_override(self):
        from makeo import db
        self._login()
        c = db.connect()
        owner = c.execute("SELECT id FROM users WHERE email=?",
                          ("owner@x.test",)).fetchone()
        bid = db.new_id()
        c.execute(
            "INSERT INTO brands (id,user_id,slug,name,config,assets_dir,created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (bid, owner["id"], "appr", "A", "{}", self.td.name, db.now()),
        )
        jid = db.insert_job(c, brand_id=bid, user_id=owner["id"], source="ui_trend",
                            status="awaiting_approval", caption="sidecar")
        c.commit()
        c.close()
        page = self.client.get(f"/brands/{bid}/inbox")
        r = self.client.post(f"/v1/jobs/{jid}/approve", data={
            "csrf": _csrf(page.text), "caption": "override-now",
        }, follow_redirects=False)
        self.assertIn(r.status_code, (302, 303))
        c = db.connect()
        job = db.get_job(c, jid)
        c.close()
        self.assertEqual(job["status"], "publishing")
        self.assertEqual(job["caption_override"], "override-now")

    def test_reject_stays_off_publish(self):
        from makeo import db
        self._login()
        c = db.connect()
        owner = c.execute("SELECT id FROM users WHERE email=?",
                          ("owner@x.test",)).fetchone()
        bid = db.new_id()
        c.execute(
            "INSERT INTO brands (id,user_id,slug,name,config,assets_dir,created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (bid, owner["id"], "rej", "R", "{}", self.td.name, db.now()),
        )
        jid = db.insert_job(c, brand_id=bid, user_id=owner["id"], source="ui_trend",
                            status="awaiting_approval")
        c.commit()
        c.close()
        page = self.client.get(f"/brands/{bid}/inbox")
        self.client.post(f"/v1/jobs/{jid}/reject", data={"csrf": _csrf(page.text)})
        c = db.connect()
        job = db.get_job(c, jid)
        c.close()
        self.assertEqual(job["status"], "rejected")

    def test_retry_publish_from_failed(self):
        from makeo import db
        self._login()
        c = db.connect()
        owner = c.execute("SELECT id FROM users WHERE email=?",
                          ("owner@x.test",)).fetchone()
        bid = db.new_id()
        c.execute(
            "INSERT INTO brands (id,user_id,slug,name,config,assets_dir,created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (bid, owner["id"], "rtry", "R", "{}", self.td.name, db.now()),
        )
        jid = db.insert_job(c, brand_id=bid, user_id=owner["id"], source="ui_trend",
                            status="publish_failed")
        c.commit()
        c.close()
        page = self.client.get(f"/brands/{bid}/inbox")
        self.client.post(f"/v1/jobs/{jid}/retry-publish",
                         data={"csrf": _csrf(page.text)})
        c = db.connect()
        job = db.get_job(c, jid)
        c.close()
        self.assertEqual(job["status"], "publishing")

    def test_media_traversal_http_404(self):
        r = self.client.get("/public/media/abc/../other.mp4")
        self.assertEqual(r.status_code, 404)

    def test_discord_internal_requires_key(self):
        os.environ["MAKEO_WORKER_KEY"] = "secret-worker"
        try:
            r = self.client.post("/internal/jobs/nope/discord-approve")
            self.assertEqual(r.status_code, 403)
        finally:
            os.environ.pop("MAKEO_WORKER_KEY", None)

    def test_other_user_cannot_see_brand(self):
        from makeo import db
        self._login()
        c = db.connect()
        owner = c.execute("SELECT id FROM users WHERE email=?",
                          ("owner@x.test",)).fetchone()
        bid = db.new_id()
        c.execute(
            "INSERT INTO brands (id,user_id,slug,name,config,assets_dir,created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (bid, owner["id"], "priv", "P", "{}", self.td.name, db.now()),
        )
        c.commit()
        c.close()
        self.client.get("/logout")
        self._login("other@x.test")
        r = self.client.get(f"/brands/{bid}")
        self.assertEqual(r.status_code, 404)


if __name__ == "__main__":
    unittest.main()
