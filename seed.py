"""Initial masters. Runs only when the database is empty.

Items come from the client's Product/HSN list (27 items). Fittings are seeded
as FG and scraps as SCRAP; everything else as RAW. Change types in Masters.
"""
from sqlmodel import Session, select

from models import Item, ItemType, Vendor

R, F, S = ItemType.RAW, ItemType.FG, ItemType.SCRAP

ITEMS = [
    ("Aluminium Profile", "76042990", R),
    ("Aluminium Section", "76042100", R),
    ("Brass Fitting", "", F),
    ("Brass Goli", "7419", R),
    ("Brass Pipe/Tube", "74112100", R),
    ("Brass Plate", "7409", R),
    ("Brass Rod", "74072120", R),
    ("Brass Sheet", "74092900", R),
    ("Brass Tube", "74112100", R),
    ("Copper Alloys Flats/Strips", "7409", R),
    ("Copper Alloys Rod", "74072910", R),
    ("Copper Bar and Rod", "74071020-30", R),
    ("Copper Bar", "74071010", R),
    ("Copper Flat (Old)", "74091900", R),
    ("Copper Nickel Fitting", "7412", F),
    ("Copper Nickel Rod", "74072110", R),
    ("Copper Nickel Scraps", "75030010", S),
    ("Copper Nickel Scrap", "74040019", S),
    ("Copper Nickel Tube/Pipe", "74112200", R),
    ("Copper Pipe Fittings", "74122090", F),
    ("Copper Scrap", "74040012", S),
    ("Copper Scrap", "74040019", S),
    ("Copper Sheets", "74091100", R),
    ("Copper Sheet", "74091900", R),
    ("Copper Strips/Flat", "74091900", R),
    ("Copper Tube Fitting", "74121000", F),
    ("Copper Tube/Pipe", "74111000", R),
]

VENDORS = ["Shreya Alloy", "A", "B", "C"]


def seed(session: Session) -> None:
    if session.exec(select(Item)).first() is None:
        for name, hsn, typ in ITEMS:
            session.add(Item(name=name, hsn=hsn, type=typ, unit="kg"))
    if session.exec(select(Vendor)).first() is None:
        for name in VENDORS:
            session.add(Vendor(name=name))
    session.commit()
