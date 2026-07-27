import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Ensure imports resolve
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import Base, SessionLocal, engine
from app.main import app
from app.services.seed import seed_if_empty


@pytest.fixture(scope="module")
def client():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    seed_if_empty(db)
    db.close()
    with TestClient(app) as c:
        yield c


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_dashboard_and_products(client):
    dash = client.get("/api/reports/dashboard").json()
    assert dash["total_products"] > 0
    products = client.get("/api/products").json()
    assert any(p["sku"] == "MOT-7100-1L" for p in products)


def test_sale_deducts_stock(client):
    products = client.get("/api/products").json()
    product = next(p for p in products if p["sku"] == "SPK-CR7HIX")
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
    after = next(p for p in updated if p["sku"] == "SPK-CR7HIX")["stock_qty"]
    assert after == before - 1


def test_sales_file_import_deducts_stock(client):
    products = client.get("/api/products").json()
    oil = next(p for p in products if p["sku"] == "MOT-7100-1L")
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
    assert body["unmatched_count"] >= 1

    result = client.post(
        "/api/imports/sales",
        files={"file": ("sample_sales_import.csv", content, "text/csv")},
        data={"deduct_stock": "true", "skip_processed": "true"},
    )
    assert result.status_code == 200
    data = result.json()
    assert data["stock_deducted"] > 0
    assert "UNKNOWN-SKU" in data["unmatched_skus"]

    updated = client.get("/api/products").json()
    after = next(p for p in updated if p["sku"] == "MOT-7100-1L")["stock_qty"]
    assert after == before - 2


def test_monthly_report(client):
    r = client.get("/api/reports/sales?period=monthly")
    assert r.status_code == 200
    data = r.json()
    assert "total_sales" in data
    assert "gross_profit" in data
