"""Database bootstrap — no hard-coded demo sales/inventory.

Shop data comes from KYGS workbook import, CSV uploads, or manual entry.
"""

from sqlalchemy.orm import Session

from app.models.models import AppMeta, Product


def seed_if_empty(db: Session) -> None:
    """Mark DB as initialized without inserting sample products/sales."""
    existing = db.query(AppMeta).filter(AppMeta.key == "seeded").first()
    if existing:
        return
    # Walk-in customer is useful for POS but keep masters empty
    if db.query(Product).count() == 0:
        from app.models.models import Customer

        if not db.query(Customer).filter(Customer.name == "Walk-in Customer").first():
            db.add(Customer(name="Walk-in Customer"))
    db.add(AppMeta(key="seeded", value="1"))
    db.commit()
