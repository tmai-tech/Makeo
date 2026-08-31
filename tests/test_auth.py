"""Self-serve email/password auth (JSON + Jinja)."""

import os
import re
import tempfile
import unittest
from pathlib import Path

from cryptography.fernet import Fernet

os.environ["MAKEO_MASTER_KEY"] = Fernet.generate_key().decode()
os.environ["MAKEO_AUTH_RATE_MAX"] = "1000"


def _csrf(html: str) -> str:
    m = re.search(r'name="csrf" value="([^"]+)"', html)
    if not m:
        raise AssertionError("no csrf in page")
    return m.group(1)


class AuthApi(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        import makeo.db as dbmod
        self._orig = dbmod.DB_PATH
        dbmod.DB_PATH = Path(self.td.name) / "t.db"
        from fastapi.testclient import TestClient
        import importlib
        import app.main as main
        importlib.reload(main)
        self.main = main
        self.client = TestClient(main.app)

    def tearDown(self):
        import makeo.db as dbmod
        dbmod.DB_PATH = self._orig
        self.td.cleanup()

    def test_health(self):
        r = self.client.get("/health")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])
        self.assertTrue(r.json()["auth"])

    def test_signup_then_me(self):
        r = self.client.post("/v1/auth/signup", json={
            "name": "Ada Lovelace",
            "email": "ada@x.test",
            "password": "secret12",
            "password_confirm": "secret12",
        })
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["user"]["name"], "Ada Lovelace")
        self.assertEqual(body["user"]["email"], "ada@x.test")
        me = self.client.get("/v1/auth/me")
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["user"]["name"], "Ada Lovelace")
        home = self.client.get("/")
        self.assertEqual(home.status_code, 200)
        self.assertIn("Your brands", home.text)
        self.assertIn("Ada Lovelace", home.text)

    def test_duplicate_email(self):
        payload = {
            "name": "Ada",
            "email": "ada@x.test",
            "password": "secret12",
            "password_confirm": "secret12",
        }
        self.assertEqual(self.client.post("/v1/auth/signup", json=payload).status_code, 200)
        r = self.client.post("/v1/auth/signup", json=payload)
        self.assertEqual(r.status_code, 409)
        self.assertIn("already", r.json()["error"].lower())

    def test_password_mismatch(self):
        r = self.client.post("/v1/auth/signup", json={
            "name": "Ada",
            "email": "ada@x.test",
            "password": "secret12",
            "password_confirm": "secret99",
        })
        self.assertEqual(r.status_code, 400)
        c = self.main.conn()
        n = c.execute("SELECT count(*) AS n FROM users").fetchone()["n"]
        c.close()
        self.assertEqual(n, 0)

    def test_short_password(self):
        r = self.client.post("/v1/auth/signup", json={
            "name": "Ada",
            "email": "ada@x.test",
            "password": "short",
            "password_confirm": "short",
        })
        self.assertEqual(r.status_code, 400)

    def test_login_unknown_same_message(self):
        self.main.create_user("ada@x.test", "secret12", "Ada")
        bad = self.client.post("/v1/auth/login", json={
            "email": "nope@x.test", "password": "secret12",
        })
        wrong = self.client.post("/v1/auth/login", json={
            "email": "ada@x.test", "password": "nopexxxx",
        })
        self.assertEqual(bad.status_code, 401)
        self.assertEqual(wrong.status_code, 401)
        self.assertEqual(bad.json()["error"], wrong.json()["error"])

    def test_login_then_logout(self):
        self.main.create_user("ada@x.test", "secret12", "Ada")
        r = self.client.post("/v1/auth/login", json={
            "email": "ada@x.test", "password": "secret12",
        })
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["user"]["email"], "ada@x.test")
        self.assertEqual(self.client.get("/v1/auth/me").status_code, 200)
        out = self.client.post("/v1/auth/logout")
        self.assertEqual(out.status_code, 200)
        self.assertEqual(self.client.get("/v1/auth/me").status_code, 401)

    def test_jinja_signup(self):
        page = self.client.get("/signup")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Full name", page.text)
        r = self.client.post("/signup", data={
            "name": "Ada",
            "email": "ada@x.test",
            "password": "secret12",
            "password_confirm": "secret12",
            "csrf": _csrf(page.text),
        }, follow_redirects=False)
        self.assertIn(r.status_code, (302, 303))
        me = self.client.get("/v1/auth/me")
        self.assertEqual(me.json()["user"]["name"], "Ada")

    def test_jinja_csrf_rejected(self):
        r = self.client.post("/signup", data={
            "name": "Ada",
            "email": "ada@x.test",
            "password": "secret12",
            "password_confirm": "secret12",
            "csrf": "nope",
        })
        self.assertEqual(r.status_code, 403)

    def test_cors_preflight(self):
        r = self.client.options("/v1/auth/login", headers={
            "Origin": "https://tmai-tech.github.io",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        })
        self.assertIn(r.status_code, (200, 204))
        self.assertEqual(r.headers.get("access-control-allow-origin"),
                         "https://tmai-tech.github.io")
        self.assertEqual(r.headers.get("access-control-allow-credentials"), "true")

    def test_users_table_has_name(self):
        c = self.main.conn()
        cols = {row[1] for row in c.execute("PRAGMA table_info(users)")}
        c.close()
        self.assertIn("name", cols)


if __name__ == "__main__":
    unittest.main()
