"""PR 8–10: waitlisted login and owner-only job mutation."""

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


class AppFlow(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        import makeo.db as dbmod
        self._orig = dbmod.DB_PATH
        dbmod.DB_PATH = Path(self.td.name) / "t.db"
        from fastapi.testclient import TestClient
        import importlib
        import app.main as main
        importlib.reload(main)
        from app.main import create_user, app
        create_user("owner@x.test", "secret")
        create_user("other@x.test", "secret")
        self.client = TestClient(app)
        self.main = main

    def tearDown(self):
        import makeo.db as dbmod
        dbmod.DB_PATH = self._orig
        self.td.cleanup()

    def _login(self, email):
        page = self.client.get("/login")
        r = self.client.post("/login", data={
            "email": email, "password": "secret", "csrf": _csrf(page.text),
        }, follow_redirects=False)
        self.assertIn(r.status_code, (302, 303))

    def test_waitlisted_unknown(self):
        page = self.client.get("/login")
        r = self.client.post("/login", data={
            "email": "nope@x.test", "password": "x", "csrf": _csrf(page.text),
        })
        self.assertEqual(r.status_code, 401)

    def test_login_sees_home(self):
        self._login("owner@x.test")
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Your brands", r.text)

    def test_other_user_cannot_approve(self):
        from makeo import db
        self._login("owner@x.test")
        c = db.connect()
        owner = c.execute("SELECT id FROM users WHERE email=?",
                          ("owner@x.test",)).fetchone()
        bid = db.new_id()
        c.execute(
            "INSERT INTO brands (id,user_id,slug,name,config,assets_dir,created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (bid, owner["id"], "own", "Own", "{}", self.td.name, db.now()),
        )
        jid = db.insert_job(c, brand_id=bid, user_id=owner["id"], source="ui_trend",
                            status="awaiting_approval")
        c.commit()
        c.close()
        self.client.get("/logout")
        self._login("other@x.test")
        page = self.client.get("/brands/new")
        r = self.client.post(f"/v1/jobs/{jid}/approve", data={
            "csrf": _csrf(page.text), "caption": "hacked",
        })
        self.assertIn(r.status_code, (403, 404))
        c = db.connect()
        job = db.get_job(c, jid)
        self.assertEqual(job["status"], "awaiting_approval")
        c.close()


if __name__ == "__main__":
    unittest.main()
