from datetime import datetime, timedelta
import random

from sqlalchemy.orm import Session

from app.models.models import (
    AppMeta,
    Category,
    Customer,
    Product,
    Sale,
    SaleItem,
    Supplier,
    Purchase,
    PurchaseItem,
)
from app.services.stock import apply_stock_change


SAMPLE_CATEGORIES = [
    ("Engine Parts", "Pistons, filters, spark plugs, gaskets"),
    ("Oils & Fluids", "Engine oil, brake fluid, coolant"),
    ("Tires & Wheels", "Motorcycle tires and tubes"),
    ("Brakes", "Brake pads, shoes, discs"),
    ("Electrical", "Batteries, bulbs, CDI, wiring"),
    ("Body & Accessories", "Mirrors, grips, covers, helmets"),
    ("Transmission", "Chains, sprockets, clutch parts"),
    ("Service Labor", "Shop labor / service fees"),
]

SAMPLE_SUPPLIERS = [
    ("Motul Philippines", "Sales Desk", "09171234501", "orders@motul.ph"),
    ("Honda Genuine Parts", "Parts Counter", "09181234502", "parts@honda.ph"),
    ("Yamaha Racing Parts", "Distributor", "09191234503", "dist@yamaha.ph"),
    ("IRC Tires PH", "Wholesale", "09201234504", "wholesale@irc.ph"),
    ("Bosch Auto Parts", "B2B", "09211234505", "b2b@bosch.ph"),
]

SAMPLE_PRODUCTS = [
    ("MOT-7100-1L", "Motul 7100 4T 10W-40 1L", "Motul", "Oils & Fluids", "Universal 4-stroke", 480, 650, 24, 6),
    ("MOT-5100-1L", "Motul 5100 4T 10W-40 1L", "Motul", "Oils & Fluids", "Scooter / underbone", 380, 520, 30, 8),
    ("BRK-FLUID-DOT4", "Brake Fluid DOT 4 500ml", "Bosch", "Oils & Fluids", "Universal", 120, 180, 40, 10),
    ("SPK-CR7HIX", "NGK Spark Plug CR7HIX", "NGK", "Engine Parts", "Honda Click / Beat", 180, 280, 50, 12),
    ("AIR-FILTER-CLICK", "Air Filter Honda Click 125i", "Honda", "Engine Parts", "Honda Click 125i", 95, 160, 20, 5),
    ("OIL-FILTER-MIO", "Oil Filter Yamaha Mio", "Yamaha", "Engine Parts", "Yamaha Mio / NMAX", 85, 140, 18, 5),
    ("TIRE-70-90-17", "IRC Tire 70/90-17 Front", "IRC", "Tires & Wheels", "Underbone", 780, 1100, 12, 4),
    ("TIRE-80-90-17", "IRC Tire 80/90-17 Rear", "IRC", "Tires & Wheels", "Underbone", 850, 1200, 10, 4),
    ("PAD-CLICK-FR", "Brake Pad Front Honda Click", "Honda", "Brakes", "Honda Click", 220, 350, 16, 4),
    ("SHOE-REAR-UNIV", "Brake Shoe Rear Universal", "OEM", "Brakes", "Scooter rear drum", 150, 250, 22, 6),
    ("BAT-GTZ5S", "Battery GTZ5S MF", "Yuasa", "Electrical", "Scooter / underbone", 980, 1350, 8, 3),
    ("BULB-H4", "Headlight Bulb H4 12V", "Philips", "Electrical", "Universal", 160, 250, 25, 8),
    ("CHAIN-428H-120", "Drive Chain 428H 120L", "DID", "Transmission", "Underbone", 620, 890, 9, 3),
    ("SPRKT-14T", "Front Sprocket 14T", "OEM", "Transmission", "Common underbone", 180, 280, 14, 4),
    ("SPRKT-38T", "Rear Sprocket 38T", "OEM", "Transmission", "Common underbone", 280, 420, 10, 3),
    ("MIRROR-PAIR", "Side Mirror Pair Chrome", "OEM", "Body & Accessories", "Universal", 220, 380, 15, 4),
    ("GRIP-SOFT", "Handle Grip Soft Rubber Pair", "OEM", "Body & Accessories", "Universal", 80, 150, 28, 8),
    ("HELMET-HALF", "Half Face Helmet Standard", "KYG", "Body & Accessories", "One size", 450, 750, 6, 2),
    ("CVR-RAIN", "Motorcycle Rain Cover XL", "KYG", "Body & Accessories", "Big bike / scooter", 280, 450, 11, 3),
    ("LABOR-CCO", "Change Oil Labor", "KYGSMOTO", "Service Labor", "Shop service", 0, 100, 999, 0),
]

SAMPLE_CUSTOMERS = [
    ("Juan Dela Cruz", "09170001111", "Honda Click 125i"),
    ("Maria Santos", "09180002222", "Yamaha Mio i 125"),
    ("Pedro Reyes", "09190003333", "Suzuki Raider R150"),
    ("Ana Lopez", "09200004444", "Honda Beat"),
    ("Walk-in Customer", None, None),
]


def seed_if_empty(db: Session) -> None:
    existing = db.query(AppMeta).filter(AppMeta.key == "seeded").first()
    if existing:
        return
    if db.query(Product).count() > 0:
        db.add(AppMeta(key="seeded", value="1"))
        db.commit()
        return

    cats = {}
    for name, desc in SAMPLE_CATEGORIES:
        c = Category(name=name, description=desc)
        db.add(c)
        db.flush()
        cats[name] = c

    suppliers = []
    for name, contact, phone, email in SAMPLE_SUPPLIERS:
        s = Supplier(name=name, contact_person=contact, phone=phone, email=email)
        db.add(s)
        db.flush()
        suppliers.append(s)

    products = []
    for sku, name, brand, cat, fitment, cost, sell, stock, reorder in SAMPLE_PRODUCTS:
        p = Product(
            sku=sku,
            name=name,
            brand=brand,
            category_id=cats[cat].id,
            supplier_id=suppliers[random.randint(0, len(suppliers) - 1)].id,
            fitment=fitment,
            cost_price=cost,
            sell_price=sell,
            stock_qty=stock,
            reorder_level=reorder,
            unit="pc" if cat != "Oils & Fluids" else "bot",
            location="A-" + sku[-3:],
        )
        db.add(p)
        db.flush()
        products.append(p)

    customers = []
    for name, phone, moto in SAMPLE_CUSTOMERS:
        c = Customer(name=name, phone=phone, motorcycle_model=moto)
        db.add(c)
        db.flush()
        customers.append(c)

    # Seed a purchase
    purchase = Purchase(
        po_no="PO-1001",
        purchase_date=datetime.utcnow() - timedelta(days=20),
        supplier_id=suppliers[0].id,
        notes="Initial stock replenishment",
    )
    subtotal = 0.0
    for p in products[:6]:
        qty = 10
        line = qty * p.cost_price
        subtotal += line
        purchase.items.append(
            PurchaseItem(product_id=p.id, quantity=qty, unit_cost=p.cost_price, line_total=line)
        )
        apply_stock_change(db, p, qty, "purchase", reference="PO-1001", notes="Seed purchase")
    purchase.subtotal = subtotal
    purchase.total = subtotal
    db.add(purchase)

    # Seed recent sales
    for i in range(1, 16):
        sale_date = datetime.utcnow() - timedelta(days=random.randint(0, 40), hours=random.randint(0, 10))
        customer = random.choice(customers)
        sale = Sale(
            invoice_no=f"SI-{1000 + i}",
            sale_date=sale_date,
            customer_id=customer.id,
            payment_method=random.choice(["cash", "gcash", "card"]),
            payment_status="paid",
            source="manual",
        )
        chosen = random.sample(products, k=random.randint(1, 3))
        subtotal = 0.0
        for p in chosen:
            if p.sku.startswith("LABOR"):
                qty = 1
            else:
                qty = random.randint(1, 2)
            line_total = qty * p.sell_price
            subtotal += line_total
            sale.items.append(
                SaleItem(
                    product_id=p.id,
                    sku=p.sku,
                    product_name=p.name,
                    quantity=qty,
                    unit_price=p.sell_price,
                    cost_price=p.cost_price,
                    line_total=line_total,
                )
            )
            if not p.sku.startswith("LABOR"):
                apply_stock_change(db, p, -qty, "sale", reference=sale.invoice_no)
        sale.subtotal = subtotal
        sale.total = subtotal
        sale.amount_paid = subtotal
        db.add(sale)

    db.add(AppMeta(key="seeded", value="1"))
    db.commit()