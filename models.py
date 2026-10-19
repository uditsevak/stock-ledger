"""Database tables.

Stock is never stored. It is always SUM(movement.qty) over non-deleted entries,
so the numbers can't drift. Every entry (purchase, sale, labour out/in, opening)
is one row in `entry` plus one or more signed rows in `movement`.
"""
from datetime import date as Date, datetime
from typing import Optional

from pydantic import NaiveDatetime
from sqlmodel import Field, SQLModel


class ItemType:
    RAW = "RAW"
    FG = "FG"
    SCRAP = "SCRAP"
    ALL = (RAW, FG, SCRAP)


class EntryType:
    OPENING = "OPENING"
    PURCHASE = "PURCHASE"
    SALE = "SALE"
    LABOUR_OUT = "LABOUR_OUT"
    LABOUR_IN = "LABOUR_IN"


class LotStatus:
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class Role:
    EDITOR = "EDITOR"  # can add/edit/delete everything, manage users
    VIEWER = "VIEWER"  # read-only
    ALL = (EDITOR, VIEWER)


def now() -> datetime:
    return datetime.now()


class Item(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    hsn: str = ""
    type: str = ItemType.RAW  # RAW / FG / SCRAP
    unit: str = "kg"
    active: bool = True


class Party(SQLModel, table=True):
    """Suppliers and customers (one list, added from the entry screens)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    gstin: str = ""
    phone: str = ""
    active: bool = True
    created_at: NaiveDatetime = Field(default_factory=now)


class Vendor(SQLModel, table=True):
    """Job workers that material is sent to for labour."""
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    gstin: str = ""
    active: bool = True


class Entry(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    entry_type: str = Field(index=True)
    date: Date = Field(index=True)
    party_id: Optional[int] = Field(default=None, foreign_key="party.id")
    vendor_id: Optional[int] = Field(default=None, foreign_key="vendor.id")
    lot_id: Optional[int] = Field(default=None, foreign_key="labourlot.id", index=True)
    ref_no: str = ""  # bill no. / invoice no. / challan no.
    remarks: str = ""
    created_at: NaiveDatetime = Field(default_factory=now)
    updated_at: Optional[NaiveDatetime] = None
    deleted_at: Optional[NaiveDatetime] = Field(default=None, index=True)


class Movement(SQLModel, table=True):
    """Signed stock movement. +qty adds to stock, -qty removes."""
    id: Optional[int] = Field(default=None, primary_key=True)
    entry_id: int = Field(foreign_key="entry.id", index=True)
    item_id: int = Field(foreign_key="item.id", index=True)
    qty: float
    role: str = ""  # IN / OUT / FG / SCRAP


class LabourLot(SQLModel, table=True):
    """One Labour Out challan. Labour In entries are booked against it."""
    id: Optional[int] = Field(default=None, primary_key=True)
    challan_no: str = Field(index=True)
    vendor_id: int = Field(foreign_key="vendor.id")
    item_id: int = Field(foreign_key="item.id")
    qty_out: float
    date_out: Date
    out_entry_id: Optional[int] = Field(default=None, foreign_key="entry.id")
    is_opening: bool = False  # material already with vendor at go-live
    status: str = LotStatus.OPEN
    burn_qty: float = 0.0  # set when the lot is closed
    closed_date: Optional[Date] = None
    closed_by_entry_id: Optional[int] = None


class AuditLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    at: NaiveDatetime = Field(default_factory=now)
    action: str  # CREATE / UPDATE / DELETE / MASTER
    entry_id: Optional[int] = None
    user_id: Optional[int] = None  # who did it (None for rows from before login existed)
    detail: str = ""  # JSON snapshot


class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    role: str = Role.VIEWER
    pw_hash: str
    active: bool = True
    created_at: NaiveDatetime = Field(default_factory=now)


class LoginSession(SQLModel, table=True):
    """One row per logged-in browser. Only a hash of the cookie token is stored."""
    token_hash: str = Field(primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    created_at: NaiveDatetime = Field(default_factory=now)
