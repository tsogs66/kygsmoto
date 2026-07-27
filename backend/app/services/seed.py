"""Database bootstrap — never insert hard-coded demo sales/inventory.

Shop data comes only from KYGS workbook import, CSV uploads, or manual entry.
One-time purge removes leftover SAMPLE_* rows from older app versions.
"""

from sqlalchemy.orm import Session, joinedload

from app.models.models import (
    AppMeta,
    Category,
    Customer,
    Product,
    Purchase,
    PurchaseItem,
    Sale,
    SaleItem,
    StockMovement,
    Supplier,
)

# Exact SKUs / names from the removed SAMPLE_* seed lists
DEMO_SKUS = {
    "MOT-7100-1L",
    "MOT-5100-1L",
    "BRK-FLUID-DOT4",
    "SPK-CR7HIX",
    "AIR-FILTER-CLICK",
    "OIL-FILTER-MIO",
    "TIRE-70-90-17",
    "TIRE-80-90-17",
    "PAD-CLICK-FR",
    "SHOE-REAR-UNIV",
    "BAT-GTZ5S",
    "BULB-H4",
    "CHAIN-428H-120",
    "SPRKT-14T",
    "SPRKT-38T",
    "MIRROR-PAIR",
    "GRIP-SOFT",
    "HELMET-HALF",
    "CVR-RAIN",
    "LABOR-CCO",
}

DEMO_CUSTOMERS = {
    "Juan Dela Cruz",
    "Maria Santos",
    "Pedro Reyes",
    "Ana Lopez",
}

DEMO_SUPPLIERS = {
    "Motul Philippines",
    "Honda Genuine Parts",
    "Yamaha Racing Parts",
    "IRC Tires PH",
    "Bosch Auto Parts",
}

DEMO_CATEGORIES = {
    "Engine Parts",
    "Oils & Fluids",
    "Tires & Wheels",
    "Brakes",
    "Electrical",
    "Body & Accessories",
    "Transmission",
    "Service Labor",
}

DEMO_SALE_INVOICES = {f"SI-{1000 + i}" for i in range(1, 16)}
DEMO_PURCHASE_POS = {"PO-1001"}


def _ensure_walkin(db: Session) -> None:
    if not db.query(Customer).filter(Customer.name == "Walk-in Customer").first():
        db.add(Customer(name="Walk-in Customer"))


def purge_hardcoded_demo(db: Session) -> dict:
    """Remove leftover hard-coded demo inventory/sales from older builds.

    Runs once per database (AppMeta key ``demo_cleared``). Safe if KYGS data
    was imported — only known demo SKUs / sample master records are deleted.
    """
    flag = db.query(AppMeta).filter(AppMeta.key == "demo_cleared").first()
    if flag:
        return {"purged": False, "reason": "already_cleared"}

    demo_products = db.query(Product).filter(Product.sku.in_(DEMO_SKUS)).all()
    demo_product_ids = {p.id for p in demo_products}

    # Seeded sales invoices (SI-1001..SI-1015) and purchase PO-1001
    demo_sales = (
        db.query(Sale)
        .options(joinedload(Sale.items))
        .filter(Sale.invoice_no.in_(DEMO_SALE_INVOICES))
        .all()
    )
    demo_sale_ids = {s.id for s in demo_sales}

    # Also drop any remaining sale lines tied only to demo products
    if demo_product_ids:
        orphan_items = (
            db.query(SaleItem)
            .filter(SaleItem.product_id.in_(demo_product_ids))
            .all()
        )
        for item in orphan_items:
            demo_sale_ids.add(item.sale_id)

    sales_deleted = 0
    for sale_id in list(demo_sale_ids):
        db.query(SaleItem).filter(SaleItem.sale_id == sale_id).delete(synchronize_session=False)
        db.query(Sale).filter(Sale.id == sale_id).delete(synchronize_session=False)
        sales_deleted += 1

    purchases_deleted = 0
    demo_purchases = db.query(Purchase).filter(Purchase.po_no.in_(DEMO_PURCHASE_POS)).all()
    for pur in demo_purchases:
        db.query(PurchaseItem).filter(PurchaseItem.purchase_id == pur.id).delete(synchronize_session=False)
        db.delete(pur)
        purchases_deleted += 1

    if demo_product_ids:
        db.query(PurchaseItem).filter(PurchaseItem.product_id.in_(demo_product_ids)).delete(
            synchronize_session=False
        )
        db.query(StockMovement).filter(StockMovement.product_id.in_(demo_product_ids)).delete(
            synchronize_session=False
        )
        db.query(SaleItem).filter(SaleItem.product_id.in_(demo_product_ids)).delete(
            synchronize_session=False
        )
        db.query(Product).filter(Product.id.in_(demo_product_ids)).delete(synchronize_session=False)

    customers_deleted = (
        db.query(Customer)
        .filter(Customer.name.in_(DEMO_CUSTOMERS))
        .delete(synchronize_session=False)
    )
    suppliers_deleted = (
        db.query(Supplier)
        .filter(Supplier.name.in_(DEMO_SUPPLIERS))
        .delete(synchronize_session=False)
    )

    # Drop demo categories that no longer have products
    categories_deleted = 0
    for cat in db.query(Category).filter(Category.name.in_(DEMO_CATEGORIES)).all():
        still_used = db.query(Product).filter(Product.category_id == cat.id).count()
        if still_used == 0:
            db.delete(cat)
            categories_deleted += 1

    _ensure_walkin(db)
    db.merge(AppMeta(key="demo_cleared", value="1"))
    db.merge(AppMeta(key="seeded", value="1"))
    db.commit()

    return {
        "purged": True,
        "products_deleted": len(demo_product_ids),
        "sales_deleted": sales_deleted,
        "purchases_deleted": purchases_deleted,
        "customers_deleted": int(customers_deleted or 0),
        "suppliers_deleted": int(suppliers_deleted or 0),
        "categories_deleted": categories_deleted,
    }


def seed_if_empty(db: Session) -> None:
    """Mark DB initialized without inserting sample products or sales."""
    purge_hardcoded_demo(db)

    existing = db.query(AppMeta).filter(AppMeta.key == "seeded").first()
    if existing:
        return

    _ensure_walkin(db)
    db.add(AppMeta(key="seeded", value="1"))
    db.commit()
