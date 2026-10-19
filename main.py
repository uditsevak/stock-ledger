"""Stock Ledger — local FastAPI app.

Run:  python main.py      (or start.bat / start.sh)
Open: http://localhost:8000 on this PC, http://<this-pc-ip>:8000 on phones.
"""
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
import time
from contextvars import ContextVar
from datetime import date, datetime, timedelta
from datetime import date as Date
from pathlib import Path
from typing import Optional

from fastapi import Body, Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field as PField, ValidationError
from starlette.background import BackgroundTask
from sqlalchemy import delete, event, func
from sqlmodel import Session, SQLModel, create_engine, select

from models import (AuditLog, Entry, EntryType, Item, ItemType, LabourLot, LoginSession,
                    LotStatus, Movement, Party, Role, User, Vendor, now)
from seed import seed

BASE = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("STOCK_DATA_DIR", BASE / "data"))
BACKUP_DIR = DATA_DIR / "backups"
DATA_DIR.mkdir(parents=True, exist_ok=True)
BACKUP_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "stock.db"

engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_conn, _):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA journal_mode=WAL")
    cur.close()


EPS = 1e-6
WRITE_LOCK = threading.Lock()  # two editors: serialise writes so stock checks can't race


# ---------------------------------------------------------------- auth

COOKIE = "sl_session"
SESSION_DAYS = 30
MIN_PASSWORD = 4
MAX_FAILS, LOCK_SECONDS = 5, 300
# ponytail: in-memory lockout, resets on restart; fine for a single server process
FAILS: dict = {}  # user_id or "setup" -> (failed tries, locked until epoch secs)
SETUP_CODE: Optional[str] = None  # one-time code for first-run setup, printed in the server window
EDITOR_ONLY_READS = ("/api/backup", "/api/users")  # backup holds password hashes
CURRENT_USER: ContextVar[Optional[int]] = ContextVar("current_user", default=None)


def hash_pw(pw: str) -> str:
    salt = os.urandom(16)
    return f"scrypt${salt.hex()}${hashlib.scrypt(pw.encode(), salt=salt, n=2**14, r=8, p=1).hex()}"


def check_pw(pw: str, stored: str) -> bool:
    try:
        _, salt, digest = stored.split("$")
        got = hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1).hex()
    except ValueError:
        return False
    return hmac.compare_digest(got, digest)


def check_lock(key):
    _, until = FAILS.get(key, (0, 0.0))
    if time.time() < until:
        bad(f"Too many wrong tries. Wait {int((until - time.time()) // 60) + 1} min and try again.", 429)


def record_fail(key):
    fails = FAILS.get(key, (0, 0.0))[0] + 1
    FAILS[key] = (0, time.time() + LOCK_SECONDS) if fails >= MAX_FAILS else (fails, 0.0)


def ensure_setup_code():
    """While no user exists, setup needs a code that only someone at the server can see."""
    global SETUP_CODE
    with Session(engine) as s:
        if s.exec(select(User)).first():
            SETUP_CODE = None
            return
    if not SETUP_CODE:
        SETUP_CODE = secrets.token_hex(3).upper()
        print(f"\n  First-time setup code: {SETUP_CODE}\n  Type it on the setup screen to create the first editor.\n", flush=True)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def user_for_token(s: Session, token: Optional[str]) -> Optional[User]:
    row = s.get(LoginSession, token_hash(token)) if token else None
    if not row or row.created_at < datetime.now() - timedelta(days=SESSION_DAYS):
        return None
    u = s.get(User, row.user_id)
    return u if u and u.active else None


async def require_login(request: Request):
    """Runs before every route. /api/auth/* is open; the rest needs a login,
    and anything that changes data (or reads users/backup) needs an editor."""
    path = request.url.path
    if not path.startswith("/api/") or path.startswith("/api/auth/"):
        return
    with Session(engine) as s:
        u = user_for_token(s, request.cookies.get(COOKIE))
    if not u:
        bad("Please log in.", 401)
    if u.role != Role.EDITOR and (request.method != "GET" or path.startswith(EDITOR_ONLY_READS)):
        bad("You have view-only access. Ask an editor to make changes.", 403)
    CURRENT_USER.set(u.id)  # audit() reads this


app = FastAPI(title="Stock Ledger", dependencies=[Depends(require_login)],
              docs_url=None, redoc_url=None, openapi_url=None)  # no public map of the API

SECURITY_HEADERS = {
    # Alpine.js evaluates its x- attributes, hence 'unsafe-eval'. Nothing loads from other sites.
    "Content-Security-Policy": "default-src 'self'; script-src 'self' 'unsafe-eval'; "
                               "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
                               "frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
}


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers.update(SECURITY_HEADERS)
    if request.url.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"  # don't leave stock data in the browser cache
    return resp


# ---------------------------------------------------------------- helpers

def get_session():
    with Session(engine) as session:
        yield session  # nothing is committed unless an endpoint calls commit()


def q3(x: float) -> float:
    return round(float(x) + 0.0, 3)


def bad(msg: str, code: int = 400):
    raise HTTPException(status_code=code, detail=msg)


def fmt(x: float) -> str:
    x = q3(x)
    return f"{x:,.3f}".rstrip("0").rstrip(".")


def check_date(d: date):
    if d > date.today():
        bad("Date can't be in the future.")


def get_item(s: Session, item_id: Optional[int], label="Material") -> Item:
    it = s.get(Item, item_id) if item_id else None
    if not it:
        bad(f"Select a {label.lower()}.")
    return it


def get_party(s: Session, party_id: Optional[int]) -> Party:
    p = s.get(Party, party_id) if party_id else None
    if not p:
        bad("Select a party.")
    return p


def get_vendor(s: Session, vendor_id: Optional[int]) -> Vendor:
    v = s.get(Vendor, vendor_id) if vendor_id else None
    if not v:
        bad("Select a vendor.")
    return v


def stock_map(s: Session, item_ids=None) -> dict:
    stmt = (select(Movement.item_id, func.coalesce(func.sum(Movement.qty), 0.0))
            .join(Entry, Entry.id == Movement.entry_id)
            .where(Entry.deleted_at.is_(None))
            .group_by(Movement.item_id))
    if item_ids:
        stmt = stmt.where(Movement.item_id.in_(list(item_ids)))
    return {iid: q3(q) for iid, q in s.exec(stmt).all()}


def ensure_stock(s: Session, item_ids):
    """Flush pending changes, then make sure no affected item went negative."""
    item_ids = {i for i in item_ids if i}
    if not item_ids:
        return
    s.flush()
    stock = stock_map(s, item_ids)
    for iid in item_ids:
        q = stock.get(iid, 0.0)
        if q < -EPS:
            it = s.get(Item, iid)
            have = q3(q)
            bad(f"Not enough stock of {it.name}. This would make it {fmt(have)} {it.unit}.")


def lot_received(s: Session, lot_ids=None) -> dict:
    """{lot_id: {'FG': qty, 'SCRAP': qty, 'count': n}} from live Labour In entries."""
    stmt = (select(Entry.lot_id, Movement.role, func.sum(Movement.qty))
            .join(Movement, Movement.entry_id == Entry.id)
            .where(Entry.entry_type == EntryType.LABOUR_IN, Entry.deleted_at.is_(None))
            .group_by(Entry.lot_id, Movement.role))
    cnt = (select(Entry.lot_id, func.count(Entry.id))
           .where(Entry.entry_type == EntryType.LABOUR_IN, Entry.deleted_at.is_(None))
           .group_by(Entry.lot_id))
    if lot_ids is not None:
        stmt = stmt.where(Entry.lot_id.in_(list(lot_ids)))
        cnt = cnt.where(Entry.lot_id.in_(list(lot_ids)))
    out: dict = {}
    for lid, role, q in s.exec(stmt).all():
        out.setdefault(lid, {"FG": 0.0, "SCRAP": 0.0, "count": 0})[role] = q3(q)
    for lid, n in s.exec(cnt).all():
        out.setdefault(lid, {"FG": 0.0, "SCRAP": 0.0, "count": 0})["count"] = n
    return out


def lot_view(s: Session, lot: LabourLot, rec: Optional[dict] = None) -> dict:
    if rec is None:
        rec = lot_received(s, [lot.id]).get(lot.id, {})
    fg, scrap = rec.get("FG", 0.0), rec.get("SCRAP", 0.0)
    burn = lot.burn_qty if lot.status == LotStatus.CLOSED else 0.0
    pending = 0.0 if lot.status != LotStatus.OPEN else q3(lot.qty_out - fg - scrap)
    item, vendor = s.get(Item, lot.item_id), s.get(Vendor, lot.vendor_id)
    end = lot.closed_date or date.today()
    return {
        "id": lot.id, "challan_no": lot.challan_no, "status": lot.status,
        "vendor_id": lot.vendor_id, "vendor_name": vendor.name if vendor else "?",
        "item_id": lot.item_id, "item_name": item.name if item else "?",
        "hsn": item.hsn if item else "", "unit": item.unit if item else "kg",
        "date_out": lot.date_out.isoformat(), "qty_out": q3(lot.qty_out),
        "fg_in": fg, "scrap_in": scrap, "burn": q3(burn), "pending": pending,
        "burn_pct": round(burn / lot.qty_out * 100, 2) if lot.qty_out and burn else 0.0,
        "receipts": rec.get("count", 0), "days_out": (end - lot.date_out).days,
        "is_opening": lot.is_opening, "out_entry_id": lot.out_entry_id,
        "closed_date": lot.closed_date.isoformat() if lot.closed_date else None,
    }


def ensure_lot(s: Session, lot: LabourLot):
    s.flush()
    v = lot_view(s, lot)
    if lot.status == LotStatus.OPEN and v["pending"] < -EPS:
        got = v["fg_in"] + v["scrap_in"]
        bad(f"Challan {lot.challan_no}: received {fmt(got)} kg is more than the "
            f"{fmt(lot.qty_out)} kg sent.")


def entry_view(s: Session, e: Entry) -> dict:
    party = s.get(Party, e.party_id) if e.party_id else None
    vendor = s.get(Vendor, e.vendor_id) if e.vendor_id else None
    lot = s.get(LabourLot, e.lot_id) if e.lot_id else None
    lines = []
    for m in s.exec(select(Movement).where(Movement.entry_id == e.id)).all():
        it = s.get(Item, m.item_id)
        lines.append({"item_id": m.item_id, "item_name": it.name, "hsn": it.hsn,
                      "unit": it.unit, "qty": q3(m.qty), "role": m.role})
    v = {
        "id": e.id, "entry_type": e.entry_type, "date": e.date.isoformat(),
        "party_id": e.party_id, "party_name": party.name if party else None,
        "vendor_id": e.vendor_id, "vendor_name": vendor.name if vendor else None,
        "lot_id": e.lot_id, "challan_no": lot.challan_no if lot else None,
        "ref_no": e.ref_no, "remarks": e.remarks, "lines": lines,
        "created_at": e.created_at.isoformat(timespec="seconds"),
        "updated_at": e.updated_at.isoformat(timespec="seconds") if e.updated_at else None,
        "deleted_at": e.deleted_at.isoformat(timespec="seconds") if e.deleted_at else None,
        "is_opening": False, "closes_lot": False, "burn": 0.0,
    }
    if e.entry_type == EntryType.LABOUR_OUT and lot:
        v["is_opening"] = lot.is_opening
        if lot.is_opening:
            it = s.get(Item, lot.item_id)
            v["lines"] = [{"item_id": it.id, "item_name": it.name, "hsn": it.hsn,
                           "unit": it.unit, "qty": -q3(lot.qty_out), "role": "OUT"}]
        v["lot_status"] = lot.status
    if e.entry_type == EntryType.LABOUR_IN and lot and lot.closed_by_entry_id == e.id \
            and lot.status == LotStatus.CLOSED:
        v["closes_lot"] = True
        v["burn"] = q3(lot.burn_qty)
    return v


def audit(s: Session, action: str, entry_id: Optional[int], detail):
    s.add(AuditLog(action=action, entry_id=entry_id, user_id=CURRENT_USER.get(),
                   detail=json.dumps(detail, default=str, ensure_ascii=False)))


def next_challan(s: Session) -> str:
    n = 0
    for c in s.exec(select(LabourLot.challan_no)).all():
        m = re.fullmatch(r"LO-(\d+)", c or "")
        if m:
            n = max(n, int(m.group(1)))
    return f"LO-{n + 1:04d}"


# ---------------------------------------------------------------- payloads

NAME = PField(max_length=120)
REF = PField("", max_length=60)
REMARKS = PField("", max_length=500)
PASSWORD = PField(max_length=128)


class PurchaseBody(BaseModel):
    date: Date
    item_id: int
    party_id: int
    qty: float = PField(gt=0)
    ref_no: str = REF
    remarks: str = REMARKS


class SaleBody(PurchaseBody):
    pass


class OpeningBody(BaseModel):
    date: Date
    item_id: int
    qty: float = PField(gt=0)
    remarks: str = REMARKS


class LabourOutBody(BaseModel):
    date: Date
    vendor_id: int
    item_id: int
    qty: float = PField(gt=0)
    challan_no: str = REF
    remarks: str = REMARKS
    is_opening: bool = False


class LabourInBody(BaseModel):
    date: Date
    lot_id: int
    fg_item_id: Optional[int] = None
    fg_qty: float = PField(default=0, ge=0)
    scrap_item_id: Optional[int] = None
    scrap_qty: float = PField(default=0, ge=0)
    close: bool = False
    ref_no: str = REF
    remarks: str = REMARKS


class ItemBody(BaseModel):
    name: str = NAME
    hsn: str = PField("", max_length=20)
    type: str = ItemType.RAW
    unit: str = PField("kg", max_length=10)
    active: bool = True


class PartyBody(BaseModel):
    name: str = NAME
    gstin: str = PField("", max_length=20)
    phone: str = PField("", max_length=30)
    active: bool = True


class VendorBody(BaseModel):
    name: str = NAME
    gstin: str = PField("", max_length=20)
    active: bool = True


# ---------------------------------------------------------------- entry writers

def _reset_movements(s: Session, e: Entry) -> set:
    old = s.exec(select(Movement).where(Movement.entry_id == e.id)).all()
    ids = {m.item_id for m in old}
    for m in old:
        s.delete(m)
    s.flush()
    return ids


def write_simple(s: Session, e: Entry, etype: str, b) -> Entry:
    """Purchase / Sale / Opening: one movement each."""
    check_date(b.date)
    item = get_item(s, b.item_id)
    e.entry_type, e.date, e.remarks = etype, b.date, b.remarks.strip()
    if etype in (EntryType.PURCHASE, EntryType.SALE):
        e.party_id = get_party(s, b.party_id).id
        e.ref_no = b.ref_no.strip()
    s.add(e)
    s.flush()
    old_ids = _reset_movements(s, e)
    sign, role = (-1, "OUT") if etype == EntryType.SALE else (1, "IN")
    s.add(Movement(entry_id=e.id, item_id=item.id, qty=sign * q3(b.qty), role=role))
    ensure_stock(s, old_ids | {item.id})
    return e


def write_labour_out(s: Session, e: Entry, b: LabourOutBody, lot: Optional[LabourLot]) -> Entry:
    check_date(b.date)
    item = get_item(s, b.item_id)
    vendor = get_vendor(s, b.vendor_id)
    challan = (b.challan_no or "").strip() or next_challan(s)
    dup = s.exec(select(LabourLot).where(func.lower(LabourLot.challan_no) == challan.lower(),
                                         LabourLot.status != LotStatus.CANCELLED)).first()
    if dup and (lot is None or dup.id != lot.id):
        bad(f"Challan no. {challan} is already used.")

    if lot is not None:
        rec = lot_received(s, [lot.id]).get(lot.id, {})
        if rec.get("count"):
            if lot.status == LotStatus.CLOSED:
                bad("This challan is closed. Delete its closing Labour In entry first.")
            if b.item_id != lot.item_id or b.vendor_id != lot.vendor_id:
                bad("Material/vendor can't change after Labour In entries are made against this challan.")
            if b.is_opening != lot.is_opening:
                bad("Can't change the opening-balance option after Labour In entries are made.")

    e.entry_type, e.date = EntryType.LABOUR_OUT, b.date
    e.vendor_id, e.ref_no, e.remarks = vendor.id, challan, b.remarks.strip()
    s.add(e)
    s.flush()
    if lot is None:
        lot = LabourLot(challan_no=challan, vendor_id=vendor.id, item_id=item.id,
                        qty_out=q3(b.qty), date_out=b.date, out_entry_id=e.id,
                        is_opening=b.is_opening)
    lot.challan_no, lot.vendor_id, lot.item_id = challan, vendor.id, item.id
    lot.qty_out, lot.date_out, lot.is_opening = q3(b.qty), b.date, b.is_opening
    s.add(lot)
    s.flush()
    e.lot_id = lot.id
    old_ids = _reset_movements(s, e)
    if not b.is_opening:
        s.add(Movement(entry_id=e.id, item_id=item.id, qty=-q3(b.qty), role="OUT"))
    ensure_stock(s, old_ids | {item.id})
    ensure_lot(s, lot)
    return e


def write_labour_in(s: Session, b: LabourInBody) -> Entry:
    check_date(b.date)
    lot = s.get(LabourLot, b.lot_id)
    if not lot or lot.status == LotStatus.CANCELLED:
        bad("Select a challan.")
    if lot.status == LotStatus.CLOSED:
        bad(f"Challan {lot.challan_no} is already closed.")
    if b.date < lot.date_out:
        bad(f"Date is before the challan date ({lot.date_out.strftime('%d-%m-%Y')}).")
    fg_qty, scrap_qty = q3(b.fg_qty), q3(b.scrap_qty)
    if fg_qty <= 0 and scrap_qty <= 0 and not b.close:
        bad("Enter finished or scrap quantity.")
    fg_item = get_item(s, b.fg_item_id, "Finished item") if fg_qty > 0 else None
    scrap_item = get_item(s, b.scrap_item_id, "Scrap item") if scrap_qty > 0 else None

    e = Entry(entry_type=EntryType.LABOUR_IN, date=b.date, vendor_id=lot.vendor_id,
              lot_id=lot.id, ref_no=b.ref_no.strip(), remarks=b.remarks.strip())
    s.add(e)
    s.flush()
    if fg_item:
        s.add(Movement(entry_id=e.id, item_id=fg_item.id, qty=fg_qty, role="FG"))
    if scrap_item:
        s.add(Movement(entry_id=e.id, item_id=scrap_item.id, qty=scrap_qty, role="SCRAP"))
    ensure_lot(s, lot)
    pending = lot_view(s, lot)["pending"]
    if b.close or pending <= EPS:
        lot.status = LotStatus.CLOSED
        lot.burn_qty = q3(max(pending, 0.0))
        lot.closed_date = b.date
        lot.closed_by_entry_id = e.id
        s.add(lot)
        s.flush()
    return e


# ---------------------------------------------------------------- routes: entries

def _commit_entry(s: Session, e: Entry, action: str) -> dict:
    s.flush()
    v = entry_view(s, e)
    audit(s, action, e.id, v)
    s.commit()
    return v


@app.post("/api/entries/purchase")
def create_purchase(b: PurchaseBody, s: Session = Depends(get_session)):
    with WRITE_LOCK:
        return _commit_entry(s, write_simple(s, Entry(entry_type=EntryType.PURCHASE, date=b.date),
                                             EntryType.PURCHASE, b), "CREATE")


@app.post("/api/entries/sale")
def create_sale(b: SaleBody, s: Session = Depends(get_session)):
    with WRITE_LOCK:
        return _commit_entry(s, write_simple(s, Entry(entry_type=EntryType.SALE, date=b.date),
                                             EntryType.SALE, b), "CREATE")


@app.post("/api/entries/opening")
def create_opening(b: OpeningBody, s: Session = Depends(get_session)):
    with WRITE_LOCK:
        return _commit_entry(s, write_simple(s, Entry(entry_type=EntryType.OPENING, date=b.date),
                                             EntryType.OPENING, b), "CREATE")


@app.post("/api/entries/labour-out")
def create_labour_out(b: LabourOutBody, s: Session = Depends(get_session)):
    with WRITE_LOCK:
        e = write_labour_out(s, Entry(entry_type=EntryType.LABOUR_OUT, date=b.date), b, None)
        return _commit_entry(s, e, "CREATE")


@app.post("/api/entries/labour-in")
def create_labour_in(b: LabourInBody, s: Session = Depends(get_session)):
    with WRITE_LOCK:
        return _commit_entry(s, write_labour_in(s, b), "CREATE")


def _live_entry(s: Session, entry_id: int) -> Entry:
    e = s.get(Entry, entry_id)
    if not e or e.deleted_at:
        bad("Entry not found.", 404)
    return e


@app.get("/api/entries/{entry_id}")
def get_entry(entry_id: int, s: Session = Depends(get_session)):
    e = s.get(Entry, entry_id)
    if not e:
        bad("Entry not found.", 404)
    v = entry_view(s, e)
    form: dict = {"date": e.date.isoformat(), "remarks": e.remarks}
    mv = s.exec(select(Movement).where(Movement.entry_id == e.id)).first()
    if e.entry_type in (EntryType.PURCHASE, EntryType.SALE, EntryType.OPENING) and mv:
        form.update(item_id=mv.item_id, qty=abs(q3(mv.qty)))
        if e.entry_type != EntryType.OPENING:
            form.update(party_id=e.party_id, ref_no=e.ref_no)
    elif e.entry_type == EntryType.LABOUR_OUT:
        lot = s.get(LabourLot, e.lot_id)
        form.update(vendor_id=lot.vendor_id, item_id=lot.item_id, qty=q3(lot.qty_out),
                    challan_no=lot.challan_no, is_opening=lot.is_opening)
    v["form"] = form
    names = {u.id: u.name for u in s.exec(select(User)).all()}
    v["history"] = [{"at": a.at.isoformat(timespec="seconds"), "action": a.action,
                     "by": names.get(a.user_id)}
                    for a in s.exec(select(AuditLog).where(AuditLog.entry_id == e.id)
                                    .order_by(AuditLog.id)).all()]
    return v


def parse(model, body: dict):
    """Validate like FastAPI does for normal bodies (422 + field messages, not a crash)."""
    try:
        return model(**body)
    except ValidationError as err:
        raise RequestValidationError(err.errors(include_url=False, include_context=False))


@app.put("/api/entries/{entry_id}")
def update_entry(entry_id: int, body: dict = Body(...), s: Session = Depends(get_session)):
    with WRITE_LOCK:
        e = _live_entry(s, entry_id)
        before = entry_view(s, e)
        t = e.entry_type
        if t == EntryType.PURCHASE:
            write_simple(s, e, t, parse(PurchaseBody, body))
        elif t == EntryType.SALE:
            write_simple(s, e, t, parse(SaleBody, body))
        elif t == EntryType.OPENING:
            write_simple(s, e, t, parse(OpeningBody, body))
        elif t == EntryType.LABOUR_OUT:
            write_labour_out(s, e, parse(LabourOutBody, body), s.get(LabourLot, e.lot_id))
        else:
            bad("Labour In entries can't be edited. Delete it and enter again.")
        e.updated_at = now()
        s.add(e)
        s.flush()
        after = entry_view(s, e)
        audit(s, "UPDATE", e.id, {"before": before, "after": after})
        s.commit()
        return after


@app.delete("/api/entries/{entry_id}")
def delete_entry(entry_id: int, s: Session = Depends(get_session)):
    with WRITE_LOCK:
        e = _live_entry(s, entry_id)
        snap = entry_view(s, e)
        item_ids = {m.item_id for m in s.exec(select(Movement).where(Movement.entry_id == e.id)).all()}
        lot = s.get(LabourLot, e.lot_id) if e.lot_id else None

        if e.entry_type == EntryType.LABOUR_OUT and lot:
            if lot_received(s, [lot.id]).get(lot.id, {}).get("count"):
                bad("Labour In entries exist against this challan. Delete those first.")
            lot.status = LotStatus.CANCELLED
            s.add(lot)
        elif e.entry_type == EntryType.LABOUR_IN and lot:
            if lot.status == LotStatus.CLOSED:
                if lot.closed_by_entry_id != e.id:
                    bad(f"Challan {lot.challan_no} is closed. Delete its closing Labour In entry first.")
                lot.status, lot.burn_qty = LotStatus.OPEN, 0.0
                lot.closed_date, lot.closed_by_entry_id = None, None
                s.add(lot)

        e.deleted_at = now()
        s.add(e)
        ensure_stock(s, item_ids)
        audit(s, "DELETE", e.id, snap)
        s.commit()
        return {"ok": True}


@app.get("/api/entries")
def list_entries(
    entry_type: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    item_id: Optional[int] = None,
    party_id: Optional[int] = None,
    vendor_id: Optional[int] = None,
    q: Optional[str] = None,
    include_deleted: bool = False,
    limit: int = Query(300, ge=1, le=2000),
    s: Session = Depends(get_session),
):
    stmt = select(Entry)
    if not include_deleted:
        stmt = stmt.where(Entry.deleted_at.is_(None))
    if entry_type:
        stmt = stmt.where(Entry.entry_type == entry_type)
    if date_from:
        stmt = stmt.where(Entry.date >= date_from)
    if date_to:
        stmt = stmt.where(Entry.date <= date_to)
    if party_id:
        stmt = stmt.where(Entry.party_id == party_id)
    if vendor_id:
        stmt = stmt.where(Entry.vendor_id == vendor_id)
    stmt = stmt.order_by(Entry.date.desc(), Entry.id.desc())
    out, needle = [], (q or "").strip().lower()
    for e in s.exec(stmt).all():
        v = entry_view(s, e)
        if item_id and not any(l["item_id"] == item_id for l in v["lines"]):
            continue
        if needle:
            hay = " ".join(str(x or "") for x in (
                v["party_name"], v["vendor_name"], v["ref_no"], v["remarks"], v["challan_no"],
                *[l["item_name"] for l in v["lines"]])).lower()
            if needle not in hay:
                continue
        out.append(v)
        if len(out) >= limit:
            break
    return out


# ---------------------------------------------------------------- routes: lots & stock

@app.get("/api/labour/next-challan")
def api_next_challan(s: Session = Depends(get_session)):
    return {"challan_no": next_challan(s)}


@app.get("/api/lots")
def list_lots(vendor_id: Optional[int] = None, status: Optional[str] = "OPEN",
              s: Session = Depends(get_session)):
    stmt = select(LabourLot).where(LabourLot.status != LotStatus.CANCELLED)
    if vendor_id:
        stmt = stmt.where(LabourLot.vendor_id == vendor_id)
    if status and status != "ALL":
        stmt = stmt.where(LabourLot.status == status)
    lots = s.exec(stmt.order_by(LabourLot.date_out, LabourLot.id)).all()
    rec = lot_received(s, [l.id for l in lots])
    return [lot_view(s, l, rec.get(l.id, {})) for l in lots]


@app.get("/api/stock")
def get_stock(s: Session = Depends(get_session)):
    stock = stock_map(s)
    items = [{"id": i.id, "name": i.name, "hsn": i.hsn, "type": i.type, "unit": i.unit,
              "active": i.active, "stock": stock.get(i.id, 0.0)}
             for i in s.exec(select(Item).order_by(Item.name)).all()]
    lots = s.exec(select(LabourLot).where(LabourLot.status == LotStatus.OPEN)
                  .order_by(LabourLot.date_out)).all()
    rec = lot_received(s, [l.id for l in lots])
    return {"items": items, "with_vendors": [lot_view(s, l, rec.get(l.id, {})) for l in lots]}


@app.get("/api/meta")
def meta(s: Session = Depends(get_session)):
    stock = stock_map(s)
    return {
        "today": date.today().isoformat(),
        "items": [{"id": i.id, "name": i.name, "hsn": i.hsn, "type": i.type, "unit": i.unit,
                   "active": i.active, "stock": stock.get(i.id, 0.0)}
                  for i in s.exec(select(Item).order_by(Item.name)).all()],
        "parties": [p.model_dump(mode="json") for p in
                    s.exec(select(Party).order_by(func.lower(Party.name))).all()],
        "vendors": [v.model_dump(mode="json") for v in s.exec(select(Vendor).order_by(Vendor.id)).all()],
    }


# ---------------------------------------------------------------- routes: masters

def _clean(name: str, what: str) -> str:
    name = " ".join((name or "").split())
    if not name:
        bad(f"{what} name is required.")
    return name


@app.post("/api/items")
def create_item(b: ItemBody, s: Session = Depends(get_session)):
    return _save_item(s, Item(), b)


@app.put("/api/items/{item_id}")
def update_item(item_id: int, b: ItemBody, s: Session = Depends(get_session)):
    it = s.get(Item, item_id) or bad("Item not found.", 404)
    return _save_item(s, it, b)


def _save_item(s: Session, it: Item, b: ItemBody):
    with WRITE_LOCK:
        name, hsn = _clean(b.name, "Item"), b.hsn.strip()
        if b.type not in ItemType.ALL:
            bad("Type must be RAW, FG or SCRAP.")
        dup = s.exec(select(Item).where(func.lower(Item.name) == name.lower(), Item.hsn == hsn)).first()
        if dup and dup.id != it.id:
            bad(f"{name} ({hsn or 'no HSN'}) already exists.")
        it.name, it.hsn, it.type = name, hsn, b.type
        it.unit, it.active = (b.unit.strip() or "kg"), b.active
        s.add(it)
        s.flush()
        audit(s, "MASTER", None, {"item": it.model_dump(mode="json")})
        s.commit()
        s.refresh(it)
        return it


@app.post("/api/parties")
def create_party(b: PartyBody, s: Session = Depends(get_session)):
    return _save_party(s, Party(), b)


@app.put("/api/parties/{party_id}")
def update_party(party_id: int, b: PartyBody, s: Session = Depends(get_session)):
    p = s.get(Party, party_id) or bad("Party not found.", 404)
    return _save_party(s, p, b)


def _save_party(s: Session, p: Party, b: PartyBody):
    with WRITE_LOCK:
        name = _clean(b.name, "Party")
        dup = s.exec(select(Party).where(func.lower(Party.name) == name.lower())).first()
        if dup and dup.id != p.id:
            bad(f"Party '{dup.name}' already exists. Pick it from the list.")
        p.name, p.gstin, p.phone, p.active = name, b.gstin.strip().upper(), b.phone.strip(), b.active
        s.add(p)
        s.flush()
        audit(s, "MASTER", None, {"party": p.model_dump(mode="json")})
        s.commit()
        s.refresh(p)
        return p


@app.post("/api/vendors")
def create_vendor(b: VendorBody, s: Session = Depends(get_session)):
    return _save_vendor(s, Vendor(), b)


@app.put("/api/vendors/{vendor_id}")
def update_vendor(vendor_id: int, b: VendorBody, s: Session = Depends(get_session)):
    v = s.get(Vendor, vendor_id) or bad("Vendor not found.", 404)
    return _save_vendor(s, v, b)


def _save_vendor(s: Session, v: Vendor, b: VendorBody):
    with WRITE_LOCK:
        name = _clean(b.name, "Vendor")
        dup = s.exec(select(Vendor).where(func.lower(Vendor.name) == name.lower())).first()
        if dup and dup.id != v.id:
            bad(f"Vendor '{dup.name}' already exists.")
        gstin = b.gstin.strip().upper()
        if gstin and not re.fullmatch(r"\d{2}[A-Z0-9]{13}", gstin):
            bad("GSTIN should be 15 characters, starting with the 2-digit state code.")
        v.name, v.gstin, v.active = name, gstin, b.active
        s.add(v)
        s.flush()
        audit(s, "MASTER", None, {"vendor": v.model_dump(mode="json")})
        s.commit()
        s.refresh(v)
        return v


# ---------------------------------------------------------------- routes: login & users

class SetupBody(BaseModel):
    name: str = NAME
    password: str = PASSWORD
    code: str = PField("", max_length=20)


class LoginBody(BaseModel):
    user_id: int
    password: str = PASSWORD


class UserBody(BaseModel):
    name: str = NAME
    role: str = Role.VIEWER
    active: bool = True
    password: str = PField("", max_length=128)  # blank on edit = keep current password


def user_view(u: User) -> dict:
    return {"id": u.id, "name": u.name, "role": u.role, "active": u.active}


def check_password(pw: str):
    if len(pw) < MIN_PASSWORD:
        bad(f"Password must be at least {MIN_PASSWORD} characters.")


def start_session(s: Session, u: User, request: Request, response: Response) -> dict:
    token = secrets.token_urlsafe(32)
    s.execute(delete(LoginSession).where(  # tidy expired logins
        LoginSession.created_at < datetime.now() - timedelta(days=SESSION_DAYS)))
    s.add(LoginSession(token_hash=token_hash(token), user_id=u.id))
    s.commit()
    response.set_cookie(COOKIE, token, max_age=SESSION_DAYS * 86400, httponly=True, samesite="lax",
                        secure=request.url.scheme == "https")
    return user_view(u)


@app.get("/api/auth/state")
def auth_state(request: Request, s: Session = Depends(get_session)):
    """Everything the login screen needs. Names only, no roles."""
    users = s.exec(select(User).order_by(func.lower(User.name))).all()
    me = user_for_token(s, request.cookies.get(COOKIE))
    return {"setup_needed": not users,
            "users": [{"id": u.id, "name": u.name} for u in users if u.active],
            "me": user_view(me) if me else None}


@app.post("/api/auth/setup")
def auth_setup(b: SetupBody, request: Request, response: Response, s: Session = Depends(get_session)):
    """First run only: create the first editor. Needs the code printed in the server window."""
    with WRITE_LOCK:
        if s.exec(select(User)).first():
            bad("Already set up. Log in instead.", 409)
        check_lock("setup")
        if not SETUP_CODE or not hmac.compare_digest(b.code.strip().upper(), SETUP_CODE):
            record_fail("setup")
            bad("Wrong setup code. It is shown in the window where the app was started.")
        check_password(b.password)
        u = User(name=_clean(b.name, "Your"), role=Role.EDITOR, pw_hash=hash_pw(b.password))
        s.add(u)
        s.flush()
        out = start_session(s, u, request, response)
        ensure_setup_code()  # clears it
        return out


@app.post("/api/auth/login")
def auth_login(b: LoginBody, request: Request, response: Response, s: Session = Depends(get_session)):
    u = s.get(User, b.user_id)
    if not u or not u.active:
        bad("Select your name.")
    check_lock(u.id)
    if not check_pw(b.password, u.pw_hash):
        record_fail(u.id)
        bad("Wrong password.")
    FAILS.pop(u.id, None)
    return start_session(s, u, request, response)


@app.post("/api/auth/logout")
def auth_logout(request: Request, response: Response, s: Session = Depends(get_session)):
    token = request.cookies.get(COOKIE)
    row = s.get(LoginSession, token_hash(token)) if token else None
    if row:
        s.delete(row)
        s.commit()
    response.delete_cookie(COOKIE)
    return {"ok": True}


@app.get("/api/users")
def list_users(s: Session = Depends(get_session)):
    return [user_view(u) for u in s.exec(select(User).order_by(func.lower(User.name))).all()]


@app.post("/api/users")
def create_user(b: UserBody, request: Request, s: Session = Depends(get_session)):
    check_password(b.password)
    return _save_user(s, User(pw_hash=""), b, request)


@app.put("/api/users/{user_id}")
def update_user(user_id: int, b: UserBody, request: Request, s: Session = Depends(get_session)):
    u = s.get(User, user_id) or bad("User not found.", 404)
    if b.password:
        check_password(b.password)
    return _save_user(s, u, b, request)


def _save_user(s: Session, u: User, b: UserBody, request: Request):
    with WRITE_LOCK:
        name = _clean(b.name, "User")
        if b.role not in Role.ALL:
            bad("Role must be EDITOR or VIEWER.")
        dup = s.exec(select(User).where(func.lower(User.name) == name.lower())).first()
        if dup and dup.id != u.id:
            bad(f"User '{dup.name}' already exists.")
        u.name, u.role, u.active = name, b.role, b.active
        if b.password:
            u.pw_hash = hash_pw(b.password)
        s.add(u)
        s.flush()
        if not s.exec(select(User).where(User.role == Role.EDITOR, User.active)).first():
            bad("Keep at least one active editor, or nobody can make changes.")
        if u.id and (b.password or not u.active):  # log them out everywhere except this browser
            mine = token_hash(request.cookies.get(COOKIE) or "")
            s.execute(delete(LoginSession).where(
                LoginSession.user_id == u.id, LoginSession.token_hash != mine))
        audit(s, "MASTER", None, {"user": user_view(u)})
        s.commit()
        s.refresh(u)
        return user_view(u)


# ---------------------------------------------------------------- routes: reports
# Each report returns {"tables": [{key, title, cols, rows, total?}]}. cols are
# [field, label, kind]; kind is "num" (qty), "pct", "date", "days" or "" (text).
# The browser draws every table the same way and exports any of them as CSV.

AGING_BUCKETS = ((90, "0–90 days"), (180, "91–180 days"), (365, "181–365 days"), (10**9, "Over 1 year"))


def check_period(date_from: date, date_to: date):
    if date_from > date_to:
        bad("From date is after To date.")


def _sum_rows(rows, fields) -> dict:
    return {f: q3(sum(r[f] for r in rows)) for f in fields}


def _pct(part: float, whole: float) -> float:
    return round(part / whole * 100, 2) if whole else 0.0


@app.get("/api/reports/reconciliation")
def report_reconciliation(date_from: date, date_to: date, s: Session = Depends(get_session)):
    """Per item: opening + in − out = closing, over the period."""
    check_period(date_from, date_to)
    moves = (select(Movement.item_id, Entry.entry_type, func.sum(Movement.qty))
             .join(Entry, Entry.id == Movement.entry_id).where(Entry.deleted_at.is_(None))
             .group_by(Movement.item_id, Entry.entry_type))
    before: dict = {}
    for iid, _, q in s.exec(moves.where(Entry.date < date_from)).all():
        before[iid] = before.get(iid, 0.0) + q
    during: dict = {}
    for iid, et, q in s.exec(moves.where(Entry.date >= date_from, Entry.date <= date_to)).all():
        during.setdefault(iid, {})[et] = q
    fields = ("opening", "purchase", "opening_entry", "job_in", "job_out", "sale", "closing")
    rows = []
    order = {t: n for n, t in enumerate(ItemType.ALL)}
    for it in sorted(s.exec(select(Item)).all(), key=lambda i: (order.get(i.type, 9), i.name.lower())):
        d = during.get(it.id, {})
        r = {"item": it.name, "hsn": it.hsn, "type": it.type, "unit": it.unit,
             "opening": q3(before.get(it.id, 0.0)),
             "purchase": q3(d.get(EntryType.PURCHASE, 0.0)),
             "opening_entry": q3(d.get(EntryType.OPENING, 0.0)),
             "job_in": q3(d.get(EntryType.LABOUR_IN, 0.0)),
             "job_out": q3(-d.get(EntryType.LABOUR_OUT, 0.0)),
             "sale": q3(-d.get(EntryType.SALE, 0.0))}
        r["closing"] = q3(r["opening"] + r["purchase"] + r["opening_entry"] + r["job_in"]
                          - r["job_out"] - r["sale"])
        if any(abs(r[f]) > EPS for f in fields):
            rows.append(r)
    cols = [["item", "Item", ""], ["hsn", "HSN", ""], ["type", "Type", ""], ["unit", "Unit", ""],
            ["opening", "Opening", "num"], ["purchase", "Purchased", "num"],
            ["opening_entry", "Opening entry", "num"], ["job_out", "Job work out", "num"],
            ["job_in", "Job work in", "num"], ["sale", "Sold", "num"], ["closing", "Closing", "num"]]
    return {"tables": [{"key": "reconciliation", "title": "Item reconciliation", "cols": cols, "rows": rows}]}


@app.get("/api/reports/vendor-pending")
def report_vendor_pending(s: Session = Depends(get_session)):
    """Material with vendors right now, by how long it has been out."""
    lots = s.exec(select(LabourLot).where(LabourLot.status == LotStatus.OPEN)
                  .order_by(LabourLot.date_out, LabourLot.id)).all()
    rec = lot_received(s, [l.id for l in lots])
    rows = []
    for l in lots:
        v = lot_view(s, l, rec.get(l.id, {}))
        rows.append({"vendor": v["vendor_name"], "challan_no": v["challan_no"], "date_out": v["date_out"],
                     "item": v["item_name"], "sent": v["qty_out"], "received": q3(v["fg_in"] + v["scrap_in"]),
                     "pending": v["pending"], "days_out": v["days_out"],
                     "bucket": next(b for lim, b in AGING_BUCKETS if v["days_out"] <= lim)})
    names = [b for _, b in AGING_BUCKETS]
    summary = []
    for vendor in sorted({r["vendor"] for r in rows}, key=str.lower):
        mine = [r for r in rows if r["vendor"] == vendor]
        row = {"vendor": vendor, "challans": len(mine), "pending": q3(sum(r["pending"] for r in mine))}
        row.update({b: q3(sum(r["pending"] for r in mine if r["bucket"] == b)) for b in names})
        summary.append(row)
    total = {"vendor": "Total", "challans": len(rows), **_sum_rows(summary, ["pending", *names])}
    return {"tables": [
        {"key": "vendor-summary", "title": "Pending by vendor (kg)",
         "cols": [["vendor", "Vendor", ""], ["challans", "Challans", ""],
                  *[[b, b, "num"] for b in names], ["pending", "Total pending", "num"]],
         "rows": summary, "total": total},
        {"key": "vendor-challans", "title": "Open challans",
         "cols": [["vendor", "Vendor", ""], ["challan_no", "Challan", ""], ["date_out", "Sent on", "date"],
                  ["item", "Material", ""], ["sent", "Sent", "num"], ["received", "Received", "num"],
                  ["pending", "Pending", "num"], ["days_out", "Days out", "days"]],
         "rows": rows},
    ]}


@app.get("/api/reports/burn")
def report_burn(date_from: date, date_to: date, s: Session = Depends(get_session)):
    """Loss on challans closed in the period."""
    check_period(date_from, date_to)
    lots = s.exec(select(LabourLot).where(LabourLot.status == LotStatus.CLOSED,
                                          LabourLot.closed_date >= date_from,
                                          LabourLot.closed_date <= date_to)
                  .order_by(LabourLot.closed_date, LabourLot.id)).all()
    rec = lot_received(s, [l.id for l in lots])
    rows = []
    for l in lots:
        v = lot_view(s, l, rec.get(l.id, {}))
        rows.append({"vendor": v["vendor_name"], "challan_no": v["challan_no"], "item": v["item_name"],
                     "date_out": v["date_out"], "closed": v["closed_date"], "sent": v["qty_out"],
                     "fg": v["fg_in"], "scrap": v["scrap_in"], "burn": v["burn"], "burn_pct": v["burn_pct"]})
    qty = ["sent", "fg", "scrap", "burn"]

    def group(field, label):
        out = []
        for key in sorted({r[field] for r in rows}, key=str.lower):
            g = _sum_rows([r for r in rows if r[field] == key], qty)
            out.append({field: key, "challans": sum(1 for r in rows if r[field] == key), **g,
                        "burn_pct": _pct(g["burn"], g["sent"])})
        tot = _sum_rows(rows, qty)
        return {"key": f"burn-by-{field}", "title": f"Burn by {label}",
                "cols": [[field, label.capitalize(), ""], ["challans", "Challans", ""],
                         *[[f, n, "num"] for f, n in zip(qty, ("Sent", "Finished", "Scrap", "Burn"))],
                         ["burn_pct", "Burn %", "pct"]],
                "rows": out, "total": {field: "Total", "challans": len(rows), **tot,
                                       "burn_pct": _pct(tot["burn"], tot["sent"])}}

    return {"tables": [
        group("vendor", "vendor"), group("item", "material"),
        {"key": "burn-challans", "title": "Closed challans",
         "cols": [["vendor", "Vendor", ""], ["challan_no", "Challan", ""], ["item", "Material", ""],
                  ["date_out", "Sent on", "date"], ["closed", "Closed on", "date"], ["sent", "Sent", "num"],
                  ["fg", "Finished", "num"], ["scrap", "Scrap", "num"], ["burn", "Burn", "num"],
                  ["burn_pct", "Burn %", "pct"]],
         "rows": rows},
    ]}


# ---------------------------------------------------------------- backup

def make_backup(path: Path) -> Path:
    src = sqlite3.connect(DB_PATH)
    dst = sqlite3.connect(path)
    with dst:
        src.backup(dst)
    dst.close()
    src.close()
    return path


def daily_auto_backup(keep: int = 30):
    if not DB_PATH.exists():
        return
    target = BACKUP_DIR / f"auto-{date.today().isoformat()}.db"
    if not target.exists():
        make_backup(target)
    autos = sorted(BACKUP_DIR.glob("auto-*.db"))
    for old in autos[:-keep]:
        old.unlink(missing_ok=True)


def _backup_loop():
    """The app may run for weeks without a restart, so check for today's copy every hour."""
    while True:
        time.sleep(3600)
        try:
            daily_auto_backup()
        except Exception as err:  # keep the loop alive; the next hour tries again
            print(f"Automatic backup failed: {err}", flush=True)


@app.get("/api/backup")
def download_backup():
    path = make_backup(BACKUP_DIR / f"download-{secrets.token_hex(4)}.db")
    return FileResponse(path, filename=f"stock-{datetime.now():%Y%m%d-%H%M%S}.db",
                        media_type="application/octet-stream",
                        background=BackgroundTask(path.unlink, missing_ok=True))  # temp copy, delete once sent


# ---------------------------------------------------------------- startup + static

def init_db():
    SQLModel.metadata.create_all(engine)
    with engine.begin() as conn:  # create_all doesn't add columns to existing tables
        for table, col, ddl in (("auditlog", "user_id", "INTEGER"),
                                ("vendor", "gstin", "VARCHAR NOT NULL DEFAULT ''")):
            if col not in {r[1] for r in conn.exec_driver_sql(f"PRAGMA table_info({table})")}:
                conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
    with Session(engine) as s:
        seed(s)
    daily_auto_backup()


init_db()  # runs on import, so tables exist before the first request
ensure_setup_code()
threading.Thread(target=_backup_loop, daemon=True).start()
app.mount("/", StaticFiles(directory=BASE / "static", html=True), name="static")


def reset_password(name: str, password: str) -> str:
    """Locked-out recovery, run on the PC itself: makes `name` an active editor with a new password."""
    if len(password) < MIN_PASSWORD:
        return f"Password must be at least {MIN_PASSWORD} characters."
    with Session(engine) as s:
        u = s.exec(select(User).where(func.lower(User.name) == name.strip().lower())).first()
        if not u:
            return f"No user called '{name}'. Users: " + ", ".join(x.name for x in s.exec(select(User)).all())
        u.pw_hash, u.role, u.active = hash_pw(password), Role.EDITOR, True
        s.add(u)
        s.execute(delete(LoginSession).where(LoginSession.user_id == u.id))
        s.commit()
        return f"Done. {u.name} is an active editor with the new password."


if __name__ == "__main__":
    import sys
    if sys.argv[1:2] == ["reset-password"] and len(sys.argv) == 4:
        sys.exit(print(reset_password(sys.argv[2], sys.argv[3])))
    import uvicorn
    # One process only: WRITE_LOCK and the login lockout live in this process's memory.
    uvicorn.run(app, host=os.environ.get("HOST", "0.0.0.0"), port=int(os.environ.get("PORT", "8000")))
