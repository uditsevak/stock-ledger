"""End-to-end API test. Run:  python -m pytest -q tests   (from the project folder)"""
import sqlite3
from datetime import date, timedelta

import main
from conftest import OWNER, login

c = login(*OWNER)
TODAY = date.today().isoformat()


def ok(r):
    assert r.status_code == 200, r.text
    return r.json()


def err(r, needle):
    assert r.status_code >= 400, r.text
    assert needle.lower() in r.json()["detail"].lower(), r.json()["detail"]


def masters():
    m = ok(c.get("/api/meta"))
    mat = {x["name"]: x["id"] for x in m["materials"]}
    shape = {x["name"]: x["id"] for x in m["shapes"]}
    grade = {(x["material_id"], x["name"]): x["id"] for x in m["grades"]}
    return m, mat, shape, grade


def stock(name):
    st = ok(c.get("/api/stock"))
    return next((i["stock"] for i in st["items"] if i["name"] == name), None)


def test_seeded_masters():
    m, mat, shape, grade = masters()
    assert list(mat)[:6] == ["Brass", "Copper", "Cu/Ni", "Brass Scrap", "Copper Scrap", "Cu/Ni Scrap"]
    assert [x["is_scrap"] for x in m["materials"][:6]] == [False, False, False, True, True, True]
    assert list(shape)[:4] == ["Tube", "Rod", "Sheet", "Strip"]
    names = lambda metal: [x["name"] for x in m["grades"] if x["material_id"] == mat[metal]]  # noqa: E731
    assert names("Brass")[:9] == ["63/37", "70/30", "65/35", "85/15", "80/20", "90/10", "95/5", "Aluminum Brass", "AD Brass"]
    assert names("Copper")[:6] == ["DHP", "DLP", "ETP", "OFC", "OFE", "FRTP"]
    assert names("Cu/Ni")[:3] == ["90/10", "70/30", "95/5"]
    assert [v["name"] for v in m["vendors"]][:4] == ["Shreya Alloy", "A", "B", "C"]


def test_full_flow():
    # other test files share this DB, so count entries relative to what's already there
    n0, all0 = len(ok(c.get("/api/entries"))), len(ok(c.get("/api/entries?include_deleted=true")))
    _, mat, shape, grade = masters()
    brass, copper, b_scrap = mat["Brass"], mat["Copper"], mat["Brass Scrap"]
    rod = {"material_id": brass, "shape_id": shape["Rod"], "grade_id": grade[(brass, "63/37")], "size": "12 mm"}
    shreya = ok(c.get("/api/meta"))["vendors"][0]["id"]
    party = ok(c.post("/api/parties", json={"name": "Party A"}))
    err(c.post("/api/parties", json={"name": "party a"}), "already exists")
    P = {"date": TODAY, "party_id": party["id"]}

    # what a stock line needs
    err(c.post("/api/entries/purchase", json={**P, "spec": {}, "qty": 1}), "select material")
    err(c.post("/api/entries/purchase", json={**P, "spec": {**rod, "shape_id": None}, "qty": 1}), "select type")
    err(c.post("/api/entries/purchase", json={**P, "spec": {**rod, "grade_id": None}, "qty": 1}), "select brass grade")
    err(c.post("/api/entries/purchase", json={**P, "spec": {**rod, "grade_id": grade[(copper, "DHP")]}, "qty": 1}),
        "not a brass grade")

    # Purchase 200 of Brass Rod 63/37 12 mm, with bill no. and HSN
    pur = ok(c.post("/api/entries/purchase", json={**P, "spec": rod, "qty": 200, "ref_no": "B-1", "hsn": "74072120"}))
    line = "Brass Rod · 63/37 · 12 mm"
    assert pur["lines"][0]["item_name"] == line and pur["hsn"] == "74072120"
    assert stock(line) == 200
    assert len(ok(c.get("/api/entries?q=74072120"))) == 1  # HSN is searchable
    err(c.post("/api/entries/purchase", json={**P, "date": (date.today() + timedelta(days=1)).isoformat(),
                                              "spec": rod, "qty": 1}), "future")

    # size is matched loosely ("12MM" = "12 mm"), but another size is its own stock line
    sale_16 = {**P, "spec": {**rod, "size": "16 mm"}, "qty": 1}
    err(c.post("/api/entries/sale", json=sale_16), "not enough stock of brass rod · 63/37 · 16 mm")
    rod_id = pur["lines"][0]["item_id"]
    assert [i["id"] for i in ok(c.get("/api/meta"))["items"] if i["name"].startswith("Brass Rod · 63/37")] == [rod_id]

    # Labour out 200
    nc = ok(c.get("/api/labour/next-challan"))["challan_no"]
    assert nc == "LO-0001"
    lo = ok(c.post("/api/entries/labour-out", json={"date": TODAY, "vendor_id": shreya,
                                                     "spec": {**rod, "size": " 12MM "}, "qty": 200}))
    assert lo["ref_no"] == "LO-0001" and lo["lines"][0]["item_id"] == rod_id
    assert stock(line) == 0
    err(c.post("/api/entries/labour-out", json={"date": TODAY, "vendor_id": shreya, "spec": rod, "qty": 1}),
        "not enough stock")
    lot = ok(c.get(f"/api/lots?vendor_id={shreya}"))[0]
    assert lot["pending"] == 200 and lot["spec"]["grade_id"] == rod["grade_id"] and lot["material_name"] == "Brass"

    # Labour in: rod comes back drawn to 10 mm, plus brass scrap. Partial, then close -> 180 / 10 / 10 burn
    back = {**rod, "size": "10 mm"}
    LI = {"date": TODAY, "lot_id": lot["id"]}
    err(c.post("/api/entries/labour-in", json={**LI, "recv": back, "recv_qty": 1, "scrap_material_id": brass,
                                               "scrap_qty": 1}), "which scrap")
    li1 = ok(c.post("/api/entries/labour-in", json={**LI, "recv": back, "recv_qty": 100,
                                                     "scrap_material_id": b_scrap, "scrap_qty": 5}))
    assert ok(c.get("/api/lots"))[0]["pending"] == 95
    err(c.post("/api/entries/labour-in", json={**LI, "recv": back, "recv_qty": 96}), "more than")
    li2 = ok(c.post("/api/entries/labour-in", json={**LI, "recv": back, "recv_qty": 80, "scrap_material_id": b_scrap,
                                                     "scrap_qty": 5, "close": True}))
    assert li2["closes_lot"] and li2["burn"] == 10
    closed = ok(c.get("/api/lots?status=CLOSED"))[0]
    assert (closed["recv_in"], closed["scrap_in"], closed["burn"], closed["burn_pct"]) == (180, 10, 10, 5.0)
    assert ok(c.get("/api/lots")) == []
    rod10 = "Brass Rod · 63/37 · 10 mm"
    assert stock(rod10) == 180 and stock("Brass Scrap") == 10

    # Sales
    sell = {**P, "spec": back, "qty": 50}
    sale = ok(c.post("/api/entries/sale", json=sell))
    assert stock(rod10) == 130
    err(c.post("/api/entries/sale", json={**sell, "qty": 131}), "not enough stock")

    # Delete rules
    err(c.delete(f"/api/entries/{li1['id']}"), "closing")
    ok(c.delete(f"/api/entries/{li2['id']}"))  # reopens the lot
    reopened = ok(c.get("/api/lots"))[0]
    assert reopened["pending"] == 95 and reopened["status"] == "OPEN"
    assert stock(rod10) == 50
    err(c.delete(f"/api/entries/{pur['id']}"), "not enough stock")
    err(c.delete(f"/api/entries/{lo['id']}"), "delete those first")

    # Edit labour out: 150 ok (stock back +50), 100 fails (105 already received), other grade fails
    body = {"date": TODAY, "vendor_id": shreya, "spec": rod, "qty": 150, "challan_no": "LO-0001"}
    ok(c.put(f"/api/entries/{lo['id']}", json=body))
    assert stock(line) == 50 and ok(c.get("/api/lots"))[0]["pending"] == 45
    err(c.put(f"/api/entries/{lo['id']}", json={**body, "qty": 100}), "more than")
    err(c.put(f"/api/entries/{lo['id']}", json={**body, "spec": {**rod, "grade_id": grade[(brass, "70/30")]}}),
        "can't change")
    err(c.put(f"/api/entries/{li1['id']}", json={}), "can't be edited")
    form = ok(c.get(f"/api/entries/{lo['id']}"))["form"]
    assert form["spec"] == {**rod, "size": "12 mm"} and form["qty"] == 150

    # Edit sale qty up beyond stock fails, down works
    err(c.put(f"/api/entries/{sale['id']}", json={**sell, "qty": 101}), "not enough stock")
    ok(c.put(f"/api/entries/{sale['id']}", json={**sell, "qty": 40}))
    assert stock(rod10) == 60

    # Opening stock (scrap: type/grade/size ignored) + material already with vendor at go-live
    cu_sheet = {"material_id": copper, "shape_id": shape["Sheet"], "grade_id": grade[(copper, "ETP")], "size": "1.5 x 600"}
    ok(c.post("/api/entries/opening", json={"date": TODAY, "spec": cu_sheet, "qty": 75.5}))
    op = ok(c.post("/api/entries/opening", json={"date": TODAY, "spec": {**rod, "material_id": b_scrap}, "qty": 3}))
    assert op["lines"][0]["item_name"] == "Brass Scrap"
    ok(c.post("/api/entries/labour-out", json={"date": TODAY, "vendor_id": shreya, "spec": cu_sheet, "qty": 30,
                                                "is_opening": True, "challan_no": "OLD-7"}))
    assert stock("Copper Sheet · ETP · 1.5 x 600") == 75.5
    err(c.post("/api/entries/labour-out", json={"date": TODAY, "vendor_id": shreya, "spec": cu_sheet, "qty": 1,
                                                 "challan_no": "old-7"}), "already used")
    assert ok(c.get("/api/labour/next-challan"))["challan_no"] == "LO-0002"

    # Close a lot with nothing back -> everything is burn
    old_lot = next(l for l in ok(c.get("/api/lots")) if l["challan_no"] == "OLD-7")
    r = ok(c.post("/api/entries/labour-in", json={"date": TODAY, "lot_id": old_lot["id"], "close": True}))
    assert r["burn"] == 30

    # Ledger + filters + detail
    led = ok(c.get("/api/entries"))
    assert len(led) == n0 + 8
    rod10_id = li1["lines"][0]["item_id"]
    assert len(ok(c.get(f"/api/entries?item_id={rod10_id}"))) == 2  # li1 + sale
    assert len(ok(c.get("/api/entries?q=party a"))) == 2
    assert len(ok(c.get("/api/entries?include_deleted=true"))) == all0 + 9
    det = ok(c.get(f"/api/entries/{sale['id']}"))
    assert det["form"]["qty"] == 40 and [(h["action"], h["by"]) for h in det["history"]] == [("CREATE", "Owner"), ("UPDATE", "Owner")]

    # Backup
    r = c.get("/api/backup")
    assert r.status_code == 200 and r.content[:15] == b"SQLite format 3"


def test_masters():
    _, mat, shape, grade = masters()
    brass = mat["Brass"]
    # add a grade and a type, then use them
    g = ok(c.post("/api/grades", json={"name": "Mst 60/40", "material_id": brass}))
    err(c.post("/api/grades", json={"name": "mst 60/40", "material_id": brass}), "already has grade")
    err(c.post("/api/grades", json={"name": "X", "material_id": mat["Brass Scrap"]}), "scrap has no grades")
    ok(c.post("/api/grades", json={"name": "Mst 60/40", "material_id": mat["Copper"]}))  # same name, other metal: fine
    hollow = ok(c.post("/api/shapes", json={"name": "Mst Hollow"}))
    err(c.post("/api/shapes", json={"name": "tube"}), "already exists")
    spec = {"material_id": brass, "shape_id": hollow["id"], "grade_id": g["id"], "size": "Mst-1"}
    ok(c.post("/api/entries/opening", json={"date": TODAY, "spec": spec, "qty": 5}))
    assert stock("Brass Mst Hollow · Mst 60/40 · Mst-1") == 5

    # renaming a master renames its stock lines
    ok(c.put(f"/api/grades/{g['id']}", json={"name": "Mst 61/39", "material_id": brass}))
    assert stock("Brass Mst Hollow · Mst 61/39 · Mst-1") == 5
    # used masters can't change what they are
    err(c.put(f"/api/grades/{g['id']}", json={"name": "Mst 61/39", "material_id": mat["Copper"]}), "already used")
    err(c.put(f"/api/materials/{brass}", json={"name": "Brass", "is_scrap": True}), "already used")
    # a new metal with no grades needs no grade
    zinc = ok(c.post("/api/materials", json={"name": "Mst Zinc"}))
    err(c.post("/api/materials", json={"name": "mst zinc"}), "already exists")
    ok(c.post("/api/entries/opening", json={"date": TODAY, "spec": {"material_id": zinc["id"], "shape_id": hollow["id"]},
                                            "qty": 1}))
    assert stock("Mst Zinc Mst Hollow") == 1
    # hiding keeps it in the list (frontend hides inactive ones from pickers)
    ok(c.put(f"/api/shapes/{hollow['id']}", json={"name": "Mst Hollow", "active": False}))
    assert next(s for s in ok(c.get("/api/meta"))["shapes"] if s["id"] == hollow["id"])["active"] is False
    ok(c.post("/api/vendors", json={"name": "D"}))


def test_old_flat_item_db_is_reset(tmp_path, monkeypatch):
    db, backups = tmp_path / "stock.db", tmp_path / "backups"
    backups.mkdir()
    con = sqlite3.connect(db)
    con.executescript("""CREATE TABLE item (id INTEGER PRIMARY KEY, name TEXT, hsn TEXT);
                         INSERT INTO item VALUES (1, 'Brass Rod', '7407');
                         CREATE TABLE entry (id INTEGER PRIMARY KEY); CREATE TABLE movement (id INTEGER PRIMARY KEY);
                         CREATE TABLE user (id INTEGER PRIMARY KEY, name TEXT); INSERT INTO user VALUES (1, 'Kept');""")
    con.commit()
    con.close()
    monkeypatch.setattr(main, "DB_PATH", db)
    monkeypatch.setattr(main, "BACKUP_DIR", backups)
    main.reset_flat_item_tables()
    con = sqlite3.connect(db)
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert tables == {"user"} and con.execute("SELECT name FROM user").fetchall() == [("Kept",)]
    con.close()
    [copy] = backups.glob("before-material-grades-*.db")
    assert sqlite3.connect(copy).execute("SELECT name FROM item").fetchall() == [("Brass Rod",)]
    main.reset_flat_item_tables()  # new-shape or already-reset DB: nothing happens
    assert len(list(backups.iterdir())) == 1
