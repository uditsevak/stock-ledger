"""Reports. Run:  python -m pytest -q tests"""
from datetime import date, timedelta

from conftest import OWNER, login

c = login(*OWNER)
day = lambda n: (date.today() - timedelta(days=n)).isoformat()  # noqa: E731


def ok(r):
    assert r.status_code == 200, r.text
    return r.json()


def table(rep, key):
    return next(t for t in rep["tables"] if t["key"] == key)


def test_reports():
    metal = ok(c.post("/api/materials", json={"name": "Rpt Metal"}))["id"]
    scrap_mat = ok(c.post("/api/materials", json={"name": "Rpt Scrap", "is_scrap": True}))["id"]
    grade = ok(c.post("/api/grades", json={"name": "R1", "material_id": metal}))["id"]
    tube = next(x["id"] for x in ok(c.get("/api/meta"))["shapes"] if x["name"] == "Tube")
    raw = {"stage": "RAW", "material_id": metal, "shape_id": tube, "grade_id": grade, "size": "20 mm"}
    drawn = {**raw, "stage": "FG", "size": "18 mm"}  # what comes back from the vendor
    party = ok(c.post("/api/parties", json={"name": "Rpt Party"}))["id"]
    assert c.post("/api/vendors", json={"name": "Bad GST", "gstin": "XX123"}).status_code == 400
    vendor = ok(c.post("/api/vendors", json={"name": "Rpt Vendor", "gstin": "27abcde1234f1z5"}))
    assert vendor["gstin"] == "27ABCDE1234F1Z5"

    ok(c.post("/api/entries/purchase", json={"date": day(10), "spec": raw, "party_id": party, "qty": 1000}))
    lo1 = ok(c.post("/api/entries/labour-out", json={"date": day(8), "vendor_id": vendor["id"], "spec": raw, "qty": 600}))
    ok(c.post("/api/entries/labour-in", json={"date": day(5), "lot_id": lo1["lot_id"], "recv": drawn, "recv_qty": 500,
                                              "scrap_material_id": scrap_mat, "scrap_qty": 70, "close": True, "ref_no": "JW-9"}))
    lo2 = ok(c.post("/api/entries/labour-out", json={"date": day(5), "vendor_id": vendor["id"], "spec": raw, "qty": 200}))
    ok(c.post("/api/entries/sale", json={"date": day(0), "spec": drawn, "party_id": party, "qty": 100}))

    # reconciliation: opening + in - out = closing, and closing today = live stock
    rec = table(ok(c.get(f"/api/reports/reconciliation?date_from={day(8)}&date_to={day(0)}")), "reconciliation")
    row = {r["item"]: r for r in rec["rows"]}
    R20, R18 = "Rpt Metal Tube · R1 · 20 mm (Raw)", "Rpt Metal Tube · R1 · 18 mm (Finished)"
    assert (row[R20]["opening"], row[R20]["job_out"], row[R20]["closing"]) == (1000, 800, 200)
    assert (row[R18]["job_in"], row[R18]["sale"], row[R18]["closing"]) == (500, 100, 400)
    assert (row[R18]["stage"], row[R18]["material"], row[R18]["shape"], row[R18]["grade"], row[R18]["size"]) == \
        ("Finished", "Rpt Metal", "Tube", "R1", "18 mm")
    assert row["Rpt Scrap"]["closing"] == 70 and row["Rpt Scrap"]["shape"] == ""
    live = {i["name"]: i["stock"] for i in ok(c.get("/api/stock"))["items"]}
    assert all(r["closing"] == live[r["item"]] for r in rec["rows"] if r["item"].startswith("Rpt"))
    early = table(ok(c.get(f"/api/reports/reconciliation?date_from={day(10)}&date_to={day(10)}")), "reconciliation")
    assert R18 not in [r["item"] for r in early["rows"]]  # nothing happened to it that day
    assert c.get(f"/api/reports/reconciliation?date_from={day(0)}&date_to={day(5)}").status_code == 400

    # vendor pending: only the open challan, aged 5 days
    vp = ok(c.get("/api/reports/vendor-pending"))
    mine = [r for r in table(vp, "vendor-challans")["rows"] if r["vendor"] == "Rpt Vendor"]
    assert [(r["challan_no"], r["pending"], r["days_out"], r["bucket"]) for r in mine] == \
        [(lo2["challan_no"], 200, 5, "0–90 days")]
    summ = next(r for r in table(vp, "vendor-summary")["rows"] if r["vendor"] == "Rpt Vendor")
    assert summ["pending"] == 200 and summ["0–90 days"] == 200

    # burn: 600 sent, 570 back, 30 burnt = 5%
    burn = ok(c.get(f"/api/reports/burn?date_from={day(8)}&date_to={day(0)}"))
    ch = next(r for r in table(burn, "burn-challans")["rows"] if r["challan_no"] == lo1["challan_no"])
    assert (ch["sent"], ch["received"], ch["scrap"], ch["burn"], ch["burn_pct"]) == (600, 500, 70, 30, 5.0)
    bv = next(r for r in table(burn, "burn-by-vendor")["rows"] if r["vendor"] == "Rpt Vendor")
    assert (bv["sent"], bv["burn"], bv["burn_pct"]) == (600, 30, 5.0)
    bm = next(r for r in table(burn, "burn-by-material")["rows"] if r["material"] == "Rpt Metal")
    assert (bm["sent"], bm["received"], bm["burn"]) == (600, 500, 30)
