"""End-to-end API test. Run:  python -m pytest -q tests   (from the project folder)"""
from datetime import date, timedelta

from conftest import OWNER, login

c = login(*OWNER)
TODAY = date.today().isoformat()


def ok(r):
    assert r.status_code == 200, r.text
    return r.json()


def err(r, needle):
    assert r.status_code >= 400, r.text
    assert needle.lower() in r.json()["detail"].lower(), r.json()["detail"]


def item_id(meta, name, hsn=None):
    return next(i["id"] for i in meta["items"] if i["name"] == name and (hsn is None or i["hsn"] == hsn))


def stock(name, hsn=None):
    st = ok(c.get("/api/stock"))
    return next(i["stock"] for i in st["items"] if i["name"] == name and (hsn is None or i["hsn"] == hsn))


def test_full_flow():
    # other test files share this DB, so count entries relative to what's already there
    n0, all0 = len(ok(c.get("/api/entries"))), len(ok(c.get("/api/entries?include_deleted=true")))
    meta = ok(c.get("/api/meta"))
    assert len(meta["items"]) == 27
    assert [v["name"] for v in meta["vendors"]] == ["Shreya Alloy", "A", "B", "C"]
    rod = item_id(meta, "Brass Rod")
    fit = item_id(meta, "Brass Fitting")
    scrap = item_id(meta, "Copper Scrap", "74040012")
    bar = item_id(meta, "Copper Bar")
    shreya = meta["vendors"][0]["id"]

    party = ok(c.post("/api/parties", json={"name": "Party A"}))
    err(c.post("/api/parties", json={"name": "party a"}), "already exists")

    # Purchase 200
    pur = ok(c.post("/api/entries/purchase", json={"date": TODAY, "item_id": rod, "party_id": party["id"],
                                                    "qty": 200, "ref_no": "B-1"}))
    assert stock("Brass Rod") == 200
    err(c.post("/api/entries/purchase", json={"date": (date.today() + timedelta(days=1)).isoformat(),
                                              "item_id": rod, "party_id": party["id"], "qty": 1}), "future")

    # Labour out 200
    nc = ok(c.get("/api/labour/next-challan"))["challan_no"]
    assert nc == "LO-0001"
    lo = ok(c.post("/api/entries/labour-out", json={"date": TODAY, "vendor_id": shreya, "item_id": rod, "qty": 200}))
    assert lo["ref_no"] == "LO-0001"
    assert stock("Brass Rod") == 0
    err(c.post("/api/entries/labour-out", json={"date": TODAY, "vendor_id": shreya, "item_id": rod, "qty": 1}),
        "not enough stock")
    lots = ok(c.get(f"/api/lots?vendor_id={shreya}"))
    lot = lots[0]
    assert lot["pending"] == 200

    # Labour in: partial, then close -> 180 FG / 10 scrap / 10 burn
    li1 = ok(c.post("/api/entries/labour-in", json={"date": TODAY, "lot_id": lot["id"], "fg_item_id": fit,
                                                     "fg_qty": 100, "scrap_item_id": scrap, "scrap_qty": 5}))
    assert ok(c.get("/api/lots"))[0]["pending"] == 95
    err(c.post("/api/entries/labour-in", json={"date": TODAY, "lot_id": lot["id"], "fg_item_id": fit,
                                               "fg_qty": 96}), "more than")
    li2 = ok(c.post("/api/entries/labour-in", json={"date": TODAY, "lot_id": lot["id"], "fg_item_id": fit,
                                                     "fg_qty": 80, "scrap_item_id": scrap, "scrap_qty": 5,
                                                     "close": True}))
    assert li2["closes_lot"] and li2["burn"] == 10
    closed = ok(c.get("/api/lots?status=CLOSED"))[0]
    assert (closed["fg_in"], closed["scrap_in"], closed["burn"], closed["burn_pct"]) == (180, 10, 10, 5.0)
    assert ok(c.get("/api/lots")) == []
    assert stock("Brass Fitting") == 180 and stock("Copper Scrap", "74040012") == 10

    # Sales
    sale = ok(c.post("/api/entries/sale", json={"date": TODAY, "item_id": fit, "party_id": party["id"], "qty": 50}))
    assert stock("Brass Fitting") == 130
    err(c.post("/api/entries/sale", json={"date": TODAY, "item_id": fit, "party_id": party["id"], "qty": 131}),
        "not enough stock")

    # Delete rules
    err(c.delete(f"/api/entries/{li1['id']}"), "closing")
    ok(c.delete(f"/api/entries/{li2['id']}"))  # reopens the lot
    reopened = ok(c.get("/api/lots"))[0]
    assert reopened["pending"] == 95 and reopened["status"] == "OPEN"
    assert stock("Brass Fitting") == 50
    err(c.delete(f"/api/entries/{pur['id']}"), "not enough stock")
    err(c.delete(f"/api/entries/{lo['id']}"), "delete those first")

    # Edit labour out: 150 ok (stock back +50), 100 fails (105 already received)
    body = {"date": TODAY, "vendor_id": shreya, "item_id": rod, "qty": 150, "challan_no": "LO-0001"}
    ok(c.put(f"/api/entries/{lo['id']}", json=body))
    assert stock("Brass Rod") == 50 and ok(c.get("/api/lots"))[0]["pending"] == 45
    err(c.put(f"/api/entries/{lo['id']}", json={**body, "qty": 100}), "more than")
    err(c.put(f"/api/entries/{li1['id']}", json={}), "can't be edited")

    # Edit sale qty up beyond stock fails, down works
    sb = {"date": TODAY, "item_id": fit, "party_id": party["id"], "qty": 101}
    err(c.put(f"/api/entries/{sale['id']}", json=sb), "not enough stock")
    ok(c.put(f"/api/entries/{sale['id']}", json={**sb, "qty": 40}))
    assert stock("Brass Fitting") == 60

    # Opening stock + material already with vendor at go-live
    ok(c.post("/api/entries/opening", json={"date": TODAY, "item_id": bar, "qty": 75.5}))
    ok(c.post("/api/entries/labour-out", json={"date": TODAY, "vendor_id": shreya, "item_id": bar, "qty": 30,
                                                "is_opening": True, "challan_no": "OLD-7"}))
    assert stock("Copper Bar") == 75.5
    err(c.post("/api/entries/labour-out", json={"date": TODAY, "vendor_id": shreya, "item_id": bar, "qty": 1,
                                                 "challan_no": "old-7"}), "already used")
    assert ok(c.get("/api/labour/next-challan"))["challan_no"] == "LO-0002"

    # Close a lot with nothing back -> everything is burn
    old_lot = next(l for l in ok(c.get("/api/lots")) if l["challan_no"] == "OLD-7")
    r = ok(c.post("/api/entries/labour-in", json={"date": TODAY, "lot_id": old_lot["id"], "close": True}))
    assert r["burn"] == 30

    # Ledger + filters + detail
    led = ok(c.get("/api/entries"))
    assert len(led) == n0 + 7
    assert len(ok(c.get(f"/api/entries?item_id={fit}"))) == 2  # li1 + sale
    assert len(ok(c.get("/api/entries?q=party a"))) == 2
    assert len(ok(c.get("/api/entries?include_deleted=true"))) == all0 + 8
    det = ok(c.get(f"/api/entries/{sale['id']}"))
    assert det["form"]["qty"] == 40 and [(h["action"], h["by"]) for h in det["history"]] == [("CREATE", "Owner"), ("UPDATE", "Owner")]

    # Masters
    new = ok(c.post("/api/items", json={"name": "Brass Fitting Finished", "hsn": "7419", "type": "FG"}))
    ok(c.put(f"/api/items/{new['id']}", json={**new, "active": False}))
    err(c.post("/api/items", json={"name": "Copper Scrap", "hsn": "74040012", "type": "SCRAP"}), "already exists")
    ok(c.post("/api/vendors", json={"name": "D"}))

    # Backup
    r = c.get("/api/backup")
    assert r.status_code == 200 and r.content[:15] == b"SQLite format 3"
