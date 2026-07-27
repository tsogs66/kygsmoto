"""Minimal fixtures for API tests (no hard-coded shop seed)."""

from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import Base, SessionLocal, engine
from app.main import app
from app.models.models import Category, Product


def _seed_minimal(db):
    cat = Category(name="Test Oils")
    db.add(cat)
    db.flush()
    db.add(
        Product(
            sku="TEST-OIL-1L",
            name="Test Motul Oil 1L",
            category_id=cat.id,
            cost_price=480,
            sell_price=650,
            stock_qty=24,
            reorder_level=6,
        )
    )
    db.add(
        Product(
            sku="TEST-SPARK-1",
            name="Test Spark Plug",
            category_id=cat.id,
            cost_price=180,
            sell_price=280,
            stock_qty=50,
            reorder_level=12,
        )
    )
    db.add(
        Product(
            sku="TEST-LABOR",
            name="Test Change Oil Labor",
            category_id=cat.id,
            cost_price=0,
            sell_price=100,
            stock_qty=999,
            reorder_level=0,
        )
    )
    db.commit()


@pytest.fixture(scope="module")
def client():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    _seed_minimal(db)
    db.close()
    with TestClient(app) as c:
        yield c


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_dashboard_and_products(client):
    dash = client.get("/api/reports/dashboard").json()
    assert dash["total_products"] >= 2
    products = client.get("/api/products").json()
    assert any(p["sku"] == "TEST-OIL-1L" for p in products)


def test_sale_deducts_stock(client):
    products = client.get("/api/products").json()
    product = next(p for p in products if p["sku"] == "TEST-SPARK-1")
    before = product["stock_qty"]
    r = client.post(
        "/api/sales",
        json={
            "payment_method": "cash",
            "items": [{"product_id": product["id"], "quantity": 1}],
        },
    )
    assert r.status_code == 200
    updated = client.get("/api/products").json()
    after = next(p for p in updated if p["sku"] == "TEST-SPARK-1")["stock_qty"]
    assert after == before - 1


def test_sales_file_import_deducts_stock(client):
    products = client.get("/api/products").json()
    oil = next(p for p in products if p["sku"] == "TEST-OIL-1L")
    before = oil["stock_qty"]

    sample = Path(__file__).resolve().parents[2] / "samples" / "sample_sales_import.csv"
    content = sample.read_bytes()

    preview = client.post(
        "/api/imports/sales/preview",
        files={"file": ("sample_sales_import.csv", content, "text/csv")},
    )
    assert preview.status_code == 200
    body = preview.json()
    assert body["matched_count"] >= 1

    result = client.post(
        "/api/imports/sales",
        files={"file": ("sample_sales_import.csv", content, "text/csv")},
        data={"deduct_stock": "true", "skip_processed": "true"},
    )
    assert result.status_code == 200
    data = result.json()
    assert data["stock_deducted"] > 0

    updated = client.get("/api/products").json()
    after = next(p for p in updated if p["sku"] == "TEST-OIL-1L")["stock_qty"]
    assert after == before - 2


def test_delete_product_soft(client):
    created = client.post(
        "/api/products",
        json={"sku": "TMP-DEL-1", "name": "Temp Delete", "stock_qty": 3, "sell_price": 10, "cost_price": 5},
    ).json()
    r = client.delete(f"/api/products/{created['id']}")
    assert r.status_code == 200
    assert r.json()["mode"] == "soft"
    active = client.get("/api/products").json()
    assert not any(p["sku"] == "TMP-DEL-1" for p in active)
    inactive = client.get("/api/products?include_inactive=true").json()
    gone = next(p for p in inactive if p["sku"] == "TMP-DEL-1")
    assert gone["is_active"] is False
    assert float(gone["stock_qty"]) == 0


def test_sales_search_and_period(client):
    r = client.get("/api/sales?q=spark&period=yearly&year=2026")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_purge_hardcoded_demo_removes_sample_skus(client):
    """Startup purge should strip leftover SAMPLE_* inventory/sales."""
    from app.core.database import SessionLocal
    from app.models.models import AppMeta, Product, Sale, SaleItem, Customer
    from app.services.seed import DEMO_SKUS, purge_hardcoded_demo

    db = SessionLocal()
    try:
        db.query(AppMeta).filter(AppMeta.key == "demo_cleared").delete()
        demo = Product(sku="MOT-7100-1L", name="Motul demo", cost_price=1, sell_price=2, stock_qty=5)
        db.add(demo)
        db.flush()
        sale = Sale(invoice_no="SI-1014", payment_method="cash", source="manual", subtotal=2, total=2)
        sale.items.append(
            SaleItem(
                product_id=demo.id,
                sku=demo.sku,
                product_name=demo.name,
                quantity=1,
                unit_price=2,
                cost_price=1,
                line_total=2,
            )
        )
        db.add(sale)
        db.add(Customer(name="Juan Dela Cruz"))
        db.commit()

        result = purge_hardcoded_demo(db)
        assert result["purged"] is True
        assert db.query(Product).filter(Product.sku.in_(DEMO_SKUS)).count() == 0
        assert db.query(Sale).filter(Sale.invoice_no == "SI-1014").count() == 0
        assert db.query(Customer).filter(Customer.name == "Juan Dela Cruz").count() == 0
        assert db.query(Product).filter(Product.sku == "TEST-OIL-1L").count() == 1
    finally:
        db.close()


def test_dashboard_month_selector(client):
    r = client.get("/api/reports/dashboard?year=2026&month=4")
    assert r.status_code == 200
    data = r.json()
    assert data["selected_year"] == 2026
    assert data["selected_month"] == 4
    assert "top_products_month" in data
    assert "top_profit_month" in data
    assert "sales_week" in data


def test_product_performance(client):
    r = client.get("/api/reports/product-performance?period=monthly&metric=profit")
    assert r.status_code == 200
    assert "items" in r.json()


def test_monthly_report(client):
    r = client.get("/api/reports/sales?period=weekly")
    assert r.status_code == 200
    data = r.json()
    assert "total_sales" in data
    assert data["period"] == "weekly"
