"""Login + roles. Run:  python -m pytest -q tests"""
from fastapi.testclient import TestClient

import main
from conftest import OWNER, login


def test_login_and_roles():
    anon = TestClient(main.app)
    editor = login(*OWNER)  # first-time setup if this test runs first

    # setup can't be repeated once a user exists
    assert main.SETUP_CODE is None  # cleared once the first editor exists
    assert anon.post("/api/auth/setup", json={"name": "Hacker", "password": "1234", "code": "x"}).status_code == 409
    # not logged in: data is closed, login screen info is open
    assert anon.get("/api/meta").status_code == 401
    assert anon.post("/api/items", json={"name": "X"}).status_code == 401
    st = anon.get("/api/auth/state").json()
    assert st["me"] is None and "role" not in st["users"][0]

    # editor adds a viewer
    r = editor.post("/api/users", json={"name": "Ramesh", "role": "VIEWER", "password": "12"})
    assert r.status_code == 400 and "at least" in r.json()["detail"]
    ramesh = editor.post("/api/users", json={"name": "Ramesh", "role": "VIEWER", "password": "view-pass"}).json()
    assert editor.post("/api/users", json={"name": "ramesh", "password": "abcd"}).status_code == 400  # dup name

    viewer = login("Ramesh", "view-pass")
    assert viewer.get("/api/auth/state").json()["me"]["role"] == "VIEWER"
    assert viewer.get("/api/meta").status_code == 200
    assert viewer.get("/api/stock").status_code == 200
    for r in (viewer.post("/api/items", json={"name": "Viewer Item"}),
              viewer.post("/api/entries/opening", json={"date": "2024-01-01", "item_id": 1, "qty": 5}),
              viewer.delete("/api/entries/1"),
              viewer.get("/api/backup"),
              viewer.get("/api/users"),
              viewer.put(f"/api/users/{ramesh['id']}", json={"name": "Ramesh", "role": "EDITOR"})):
        assert r.status_code == 403, r.text

    # wrong password, then lockout after 5 tries, even with the right password
    bad = lambda pw: anon.post("/api/auth/login", json={"user_id": ramesh["id"], "password": pw})
    for _ in range(main.MAX_FAILS):
        assert bad("nope").json()["detail"] == "Wrong password."
    assert bad("view-pass").status_code == 429
    main.FAILS.clear()

    # changing a password logs that user out; deactivating locks them out
    editor.put(f"/api/users/{ramesh['id']}", json={"name": "Ramesh", "role": "VIEWER", "password": "new-pass"})
    assert viewer.get("/api/meta").status_code == 401
    viewer = login("Ramesh", "new-pass")
    editor.put(f"/api/users/{ramesh['id']}", json={"name": "Ramesh", "role": "VIEWER", "active": False})
    assert viewer.get("/api/meta").status_code == 401
    assert "Ramesh" not in [u["name"] for u in anon.get("/api/auth/state").json()["users"]]

    # can't remove the last editor
    me = editor.get("/api/auth/state").json()["me"]
    r = editor.put(f"/api/users/{me['id']}", json={"name": me["name"], "role": "VIEWER"})
    assert r.status_code == 400 and "at least one active editor" in r.json()["detail"]

    # logout ends the session
    assert editor.post("/api/auth/logout").status_code == 200
    assert editor.get("/api/meta").status_code == 401


def test_password_hash():
    h = main.hash_pw("secret")
    assert h != main.hash_pw("secret")  # salted
    assert main.check_pw("secret", h) and not main.check_pw("Secret", h)
    assert not main.check_pw("secret", "garbage")


def test_reset_password_cli():
    login(*OWNER).post("/api/users", json={"name": "Forgetful", "role": "VIEWER", "password": "old-pass"})
    assert "No user" in main.reset_password("Nobody", "abcd")
    assert "at least" in main.reset_password("Forgetful", "ab")
    assert "Done" in main.reset_password("forgetful", "new-pass")
    me = login("Forgetful", "new-pass").get("/api/auth/state").json()["me"]
    assert me["role"] == "EDITOR" and me["active"]


def test_hardening():
    editor = login(*OWNER)
    anon = TestClient(main.app)
    # no public API map
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert anon.get(path).status_code == 404
    # security headers everywhere, and API data not cached
    r = anon.get("/")
    assert r.headers["x-frame-options"] == "DENY" and "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert editor.get("/api/meta").headers["cache-control"] == "no-store"
    # bad edit input is a friendly 422, not a crash
    party = editor.post("/api/parties", json={"name": "Hardening Party"}).json()["id"]
    item = editor.get("/api/meta").json()["items"][0]["id"]
    e = editor.post("/api/entries/purchase", json={"date": "2024-01-02", "item_id": item, "party_id": party, "qty": 5}).json()
    r = editor.put(f"/api/entries/{e['id']}", json={"date": "2024-01-02", "item_id": item, "party_id": party, "qty": -3})
    assert r.status_code == 422 and r.json()["detail"][0]["loc"][-1] == "qty"
    assert editor.delete(f"/api/entries/{e['id']}").status_code == 200  # leave the shared test DB as found
    # length limits
    assert editor.post("/api/parties", json={"name": "x" * 121}).status_code == 422
    assert anon.post("/api/auth/login", json={"user_id": 1, "password": "x" * 129}).status_code == 422
    assert editor.get("/api/entries?limit=0").status_code == 422
    # backup download leaves no file behind
    before = set(main.BACKUP_DIR.iterdir())
    r = editor.get("/api/backup")
    assert r.status_code == 200 and r.content[:15] == b"SQLite format 3"
    assert set(main.BACKUP_DIR.iterdir()) == before
