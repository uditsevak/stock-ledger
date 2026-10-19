"""Shared test setup: a temp data dir, and a helper that returns a logged-in client."""
import os
import sys
import tempfile
from pathlib import Path

os.environ["STOCK_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402

OWNER = ("Owner", "owner-pass")


def login(name, password):
    """Log in as an existing user; the very first call also runs first-time setup."""
    c = TestClient(main.app)
    st = c.get("/api/auth/state").json()
    if st["setup_needed"]:
        assert c.post("/api/auth/setup", json={"name": name, "password": password, "code": "WRONG"}).status_code == 400
        r = c.post("/api/auth/setup", json={"name": name, "password": password, "code": main.SETUP_CODE})
    else:
        uid = next(u["id"] for u in st["users"] if u["name"] == name)
        r = c.post("/api/auth/login", json={"user_id": uid, "password": password})
    assert r.status_code == 200, r.text
    return c
