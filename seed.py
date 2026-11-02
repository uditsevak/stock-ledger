"""Initial masters. Each list is loaded only while its table is empty.

Materials, types and grades are the client's list. Add or rename them in Masters.
"""
from sqlmodel import Session, select

from models import Grade, Material, Shape, Vendor

# (name, is_scrap)
MATERIALS = [
    ("Brass", False), ("Copper", False), ("Cu/Ni", False),
    ("Brass Scrap", True), ("Copper Scrap", True), ("Cu/Ni Scrap", True),
]

SHAPES = ["Tube", "Rod", "Sheet", "Strip"]

GRADES = {
    "Brass": ["63/37", "70/30", "65/35", "85/15", "80/20", "90/10", "95/5", "Aluminum Brass", "AD Brass"],
    "Copper": ["DHP", "DLP", "ETP", "OFC", "OFE", "FRTP"],
    "Cu/Ni": ["90/10", "70/30", "95/5"],
}

VENDORS = ["Shreya Alloy", "A", "B", "C"]


def seed(session: Session) -> None:
    if session.exec(select(Material)).first() is None:
        for name, is_scrap in MATERIALS:
            m = Material(name=name, is_scrap=is_scrap)
            session.add(m)
            session.flush()
            for g in GRADES.get(name, []):
                session.add(Grade(material_id=m.id, name=g))
    if session.exec(select(Shape)).first() is None:
        for name in SHAPES:
            session.add(Shape(name=name))
    if session.exec(select(Vendor)).first() is None:
        for name in VENDORS:
            session.add(Vendor(name=name))
    session.commit()
