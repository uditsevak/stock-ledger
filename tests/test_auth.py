"""Login + permissions. Run:  python -m pytest -q tests"""
from fastapi.testclient import TestClient

import main
from conftest import OWNER, login, rm
from models import Perm


def test_login_and_permissions():
    anon = TestClient(main.app)
    owner = login(*OWNER)  # first-time setup if this test runs first

    # setup can't be repeated once a user exists, and the first user is the owner with everything
    assert main.SETUP_CODE is None  # cleared once the first owner exists
    assert anon.post("/api/auth/setup", json={"name": "Hacker", "password": "1234", "code": "x"}).status_code == 409
    me = owner.get("/api/auth/state").json()["me"]
    assert all(me[p] for p in Perm.ALL)
    # not logged in: data is closed, login screen info is open
    assert anon.get("/api/meta").status_code == 401
    assert anon.post("/api/materials", json={"name": "X"}).status_code == 401
    st = anon.get("/api/auth/state").json()
    assert st["me"] is None and set(st["users"][0]) == {"id", "name"}

    # the owner adds people and ticks what each may do
    r = owner.post("/api/users", json={"name": "Ramesh", "password": "12"})
    assert r.status_code == 400 and "at least" in r.json()["detail"]
    ramesh = owner.post("/api/users", json={"name": "Ramesh", "password": "view-pass"}).json()  # view only
    assert not any(ramesh[p] for p in Perm.ALL)
    assert owner.post("/api/users", json={"name": "ramesh", "password": "abcd"}).status_code == 400  # dup name
    writer = owner.post("/api/users", json={"name": "Wasim", "password": "write-pass", "can_write": True}).json()
    owner.post("/api/users", json={"name": "Dinesh", "password": "del-pass", "can_delete": True})
    owner.post("/api/users", json={"name": "Meena", "password": "mast-pass", "can_masters": True})

    scrap = next(m["id"] for m in owner.get("/api/meta").json()["materials"] if m["is_scrap"])
    party = owner.post("/api/parties", json={"name": "Perm Party"}).json()["id"]
    body = {"date": "2024-01-03", "spec": {"material_id": scrap}, "party_id": party, "qty": 2}

    def denied(r, needle):
        assert r.status_code == 403, r.text
        assert needle in r.json()["detail"], r.json()["detail"]

    # viewer: looks only
    viewer = login("Ramesh", "view-pass")
    assert viewer.get("/api/meta").status_code == 200 and viewer.get("/api/stock").status_code == 200
    denied(viewer.post("/api/entries/opening", json={**body, "date": "2024-01-01"}), "can't add or change entries")
    denied(viewer.post("/api/parties", json={"name": "Viewer Party"}), "can't add or change entries")
    denied(viewer.post("/api/materials", json={"name": "Viewer Metal"}), "can't change materials")
    denied(rm(viewer, 1), "can't delete")
    for r in (viewer.get("/api/backup"), viewer.get("/api/backup/status"), viewer.get("/api/users"),
              viewer.put(f"/api/users/{ramesh['id']}", json={"name": "Ramesh", "is_owner": True})):
        denied(r, "Only the owner")

    # writer: adds and edits entries and parties, can't delete or touch masters/users
    w = login("Wasim", "write-pass")
    e = w.post("/api/entries/purchase", json=body).json()
    assert w.put(f"/api/entries/{e['id']}", json={**body, "qty": 3}).status_code == 200
    assert w.post("/api/parties", json={"name": "Writer Party"}).status_code == 200
    denied(rm(w, e["id"]), "can't delete")
    denied(w.post("/api/grades", json={"name": "W1", "material_id": 1}), "can't change materials")
    denied(w.get("/api/users"), "Only the owner")

    # deleter: deletes with a reason, nothing else
    d = login("Dinesh", "del-pass")
    denied(d.post("/api/entries/purchase", json=body), "can't add or change entries")
    assert d.request("DELETE", f"/api/entries/{e['id']}").status_code == 422  # no reason at all
    r = rm(d, e["id"], "  ab ")
    assert r.status_code == 400 and "why" in r.json()["detail"]
    assert rm(d, e["id"], "Entered twice  by mistake").status_code == 200
    gone = owner.get(f"/api/entries/{e['id']}").json()
    assert (gone["delete_reason"], gone["deleted_by"]) == ("Entered twice by mistake", "Dinesh") and gone["deleted_at"]
    assert gone["history"][-1]["action"] == "DELETE" and gone["history"][-1]["by"] == "Dinesh"

    # masters: materials/grades/vendors only
    m = login("Meena", "mast-pass")
    assert m.post("/api/grades", json={"name": "Perm 1", "material_id": 1}).status_code == 200
    assert m.post("/api/vendors", json={"name": "Perm Vendor"}).status_code == 200
    assert m.post("/api/parties", json={"name": "Masters Party"}).status_code == 200
    denied(m.post("/api/entries/purchase", json=body), "can't add or change entries")

    # the owner takes a permission away: it applies on the very next request, no re-login
    owner.put(f"/api/users/{writer['id']}", json={"name": "Wasim", "can_write": False})
    denied(w.post("/api/entries/purchase", json=body), "can't add or change entries")

    # wrong password, then lockout after 5 tries, even with the right password
    bad = lambda pw: anon.post("/api/auth/login", json={"user_id": ramesh["id"], "password": pw})  # noqa: E731
    for _ in range(main.MAX_FAILS):
        assert bad("nope").json()["detail"] == "Wrong password."
    assert bad("view-pass").status_code == 429
    main.FAILS.clear()

    # changing a password logs that user out; deactivating locks them out
    owner.put(f"/api/users/{ramesh['id']}", json={"name": "Ramesh", "password": "new-pass"})
    assert viewer.get("/api/meta").status_code == 401
    viewer = login("Ramesh", "new-pass")
    owner.put(f"/api/users/{ramesh['id']}", json={"name": "Ramesh", "active": False})
    assert viewer.get("/api/meta").status_code == 401
    assert "Ramesh" not in [u["name"] for u in anon.get("/api/auth/state").json()["users"]]

    # an old page that doesn't send the checkboxes (e.g. renaming a user) leaves them as they are
    meena = next(u for u in owner.get("/api/users").json() if u["name"] == "Meena")
    owner.put(f"/api/users/{meena['id']}", json={"name": "Meena R", "role": "EDITOR"})
    after = next(u for u in owner.get("/api/users").json() if u["id"] == meena["id"])
    assert after["name"] == "Meena R" and after["can_masters"] and not after["can_write"]

    # can't remove the last owner
    r = owner.put(f"/api/users/{me['id']}", json={"name": me["name"], "is_owner": False})
    assert r.status_code == 400 and "at least one active owner" in r.json()["detail"]

    # logout ends the session
    assert owner.post("/api/auth/logout").status_code == 200
    assert owner.get("/api/meta").status_code == 401


def test_old_editor_viewer_users_are_upgraded(tmp_path):
    """Databases from before the checkboxes: editors get everything, viewers get view only."""
    eng = main.create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with eng.begin() as conn:
        for ddl in ("CREATE TABLE user (id INTEGER PRIMARY KEY, name TEXT, role TEXT, pw_hash TEXT, active BOOLEAN)",
                    "CREATE TABLE auditlog (id INTEGER PRIMARY KEY, user_id INTEGER)",
                    "CREATE TABLE vendor (id INTEGER PRIMARY KEY, gstin TEXT)",
                    "CREATE TABLE entry (id INTEGER PRIMARY KEY)",
                    "INSERT INTO user VALUES (1, 'Boss', 'EDITOR', 'x', 1), (2, 'Ram', 'VIEWER', 'x', 1)"):
            conn.exec_driver_sql(ddl)
        main.add_missing_columns(conn)
        rows = conn.exec_driver_sql(f"SELECT name, {', '.join(Perm.ALL)} FROM user ORDER BY id").fetchall()
    assert [tuple(r) for r in rows] == [("Boss", 1, 1, 1, 1), ("Ram", 0, 0, 0, 0)]
    with eng.begin() as conn:
        main.add_missing_columns(conn)  # second start: nothing changes
        assert conn.exec_driver_sql("SELECT is_owner FROM user WHERE id = 2").scalar() == 0


def test_password_hash():
    h = main.hash_pw("secret")
    assert h != main.hash_pw("secret")  # salted
    assert main.check_pw("secret", h) and not main.check_pw("Secret", h)
    assert not main.check_pw("secret", "garbage")


def test_reset_password_cli():
    login(*OWNER).post("/api/users", json={"name": "Forgetful", "password": "old-pass"})
    assert "No user" in main.reset_password("Nobody", "abcd")
    assert "at least" in main.reset_password("Forgetful", "ab")
    assert "Done" in main.reset_password("forgetful", "new-pass")
    me = login("Forgetful", "new-pass").get("/api/auth/state").json()["me"]
    assert me["active"] and all(me[p] for p in Perm.ALL)


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
    # the app's own files are re-checked on every load, so an update is never half-applied in a browser
    for path in ("/", "/app.js", "/app.css"):
        assert anon.get(path).headers["cache-control"] == "no-cache", path
    # bad edit input is a friendly 422, not a crash
    party = editor.post("/api/parties", json={"name": "Hardening Party"}).json()["id"]
    scrap = next(m["id"] for m in editor.get("/api/meta").json()["materials"] if m["is_scrap"])
    body = {"date": "2024-01-02", "spec": {"material_id": scrap}, "party_id": party, "qty": 5}
    e = editor.post("/api/entries/purchase", json=body).json()
    r = editor.put(f"/api/entries/{e['id']}", json={**body, "qty": -3})
    assert r.status_code == 422 and r.json()["detail"][0]["loc"][-1] == "qty"
    assert rm(editor, e["id"]).status_code == 200  # leave the shared test DB as found
    # length limits
    assert editor.post("/api/parties", json={"name": "x" * 121}).status_code == 422
    assert anon.post("/api/auth/login", json={"user_id": 1, "password": "x" * 129}).status_code == 422
    assert editor.get("/api/entries?limit=0").status_code == 422
    # backup download leaves no file behind
    before = set(main.BACKUP_DIR.iterdir())
    r = editor.get("/api/backup")
    assert r.status_code == 200 and r.content[:15] == b"SQLite format 3"
    assert set(main.BACKUP_DIR.iterdir()) == before
