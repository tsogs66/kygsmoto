"""OCR sales parsing + confirm-rows import tests."""

from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import Base, SessionLocal, engine
from app.main import app
from app.models.models import Category, Product
from app.services.ocr_sales import parse_ocr_lines, preview_sales_photo


def _seed(db):
    cat = Category(name="Test Parts")
    db.add(cat)
    db.flush()
    db.add(
        Product(
            sku="TEST-OIL-1L",
            name="Test Motul Oil 1L",
            category_id=cat.id,
            cost_price=400,
            sell_price=650,
            stock_qty=20,
            reorder_level=5,
        )
    )
    db.add(
        Product(
            sku="TEST-SPARK-1",
            name="Test Spark Plug",
            category_id=cat.id,
            cost_price=100,
            sell_price=280,
            stock_qty=40,
            reorder_level=5,
        )
    )
    db.commit()


@pytest.fixture(scope="module")
def client():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    _seed(db)
    db.close()
    with TestClient(app) as c:
        yield c


def test_parse_ocr_lines_basic():
    text = """
    Date: 04/15/2025
    TEST-OIL-1L Motul Oil 2 650
    Test Spark Plug x4 280
    Total 1860
    """
    rows = parse_ocr_lines(text)
    assert len(rows) >= 2
    assert rows[0]["sale_date"] == "2025-04-15"
    assert rows[0]["quantity"] == 2
    assert any(r["quantity"] == 4 for r in rows)


def test_parse_ocr_multi_date_context():
    text = """
    04/10/2025
    TEST-OIL-1L Motul Oil 1 650
    04/12/2025
    TEST-SPARK-1 Spark Plug 2 280
    04/12/2025 Motul Oil x1 650
    """
    rows = parse_ocr_lines(text)
    assert len(rows) >= 3
    dates = [r["sale_date"] for r in rows]
    assert "2025-04-10" in dates
    assert "2025-04-12" in dates
    # First item follows first date header
    assert rows[0]["sale_date"] == "2025-04-10"
    assert rows[1]["sale_date"] == "2025-04-12"


def test_sale_date_override(client):
    products = client.get("/api/products").json()
    product = next(p for p in products if p["sku"] == "TEST-SPARK-1")
    r = client.post(
        "/api/sales",
        json={
            "payment_method": "cash",
            "sale_date": "2025-04-10T09:30:00",
            "items": [{"product_id": product["id"], "quantity": 1}],
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["sale_date"].startswith("2025-04-10")


def test_inventory_fuzzy_match(client):
    from app.core.database import SessionLocal
    from app.services.ocr_sales import match_ocr_rows

    db = SessionLocal()
    try:
        rows = match_ocr_rows(
            db,
            [
                {
                    "row_number": 1,
                    "sale_date": "2025-04-10",
                    "sku": None,
                    "product_name": "Test Motul Oil",
                    "quantity": 1,
                    "unit_price": None,
                    "ocr_text": "Test Motul Oil 1 650",
                },
                {
                    "row_number": 2,
                    "sale_date": "2025-04-11",
                    "sku": "TEST-SPARK-1",
                    "product_name": "spark",
                    "quantity": 2,
                    "unit_price": None,
                    "ocr_text": "TEST-SPARK-1 spark 2",
                },
            ],
            mode="sale",
        )
        matched = [r for r in rows if r["status"] == "matched"]
        assert len(matched) >= 2
        assert matched[0]["sale_date"] == "2025-04-10"
        assert matched[1]["sale_date"] == "2025-04-11"
        assert matched[0]["suggestions"]
    finally:
        db.close()


def test_confirm_rows_import(client):
    products = client.get("/api/products").json()
    oil = next(p for p in products if p["sku"] == "TEST-OIL-1L")
    before = oil["stock_qty"]
    r = client.post(
        "/api/imports/sales/confirm-rows",
        json={
            "filename": "handwritten.jpg",
            "deduct_stock": True,
            "rows": [
                {
                    "row_number": 1,
                    "sale_date": "2025-03-01",
                    "matched_product_id": oil["id"],
                    "quantity": 2,
                    "unit_price": 650,
                    "include": True,
                }
            ],
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["sales_created"] == 1
    assert data["stock_deducted"] == 2
    updated = client.get("/api/products").json()
    after = next(p for p in updated if p["sku"] == "TEST-OIL-1L")["stock_qty"]
    assert after == before - 2


def test_ocr_preview_endpoint(client, tmp_path):
    # Create a simple image with printed text (OCR may or may not read it)
    img = Image.new("RGB", (800, 400), "white")
    draw = ImageDraw.Draw(img)
    draw.text((40, 40), "Date 04/15/2025", fill="black")
    draw.text((40, 100), "TEST-OIL-1L Motul Oil 2 650", fill="black")
    path = tmp_path / "sales.jpg"
    img.save(path, format="JPEG")
    content = path.read_bytes()

    r = client.post(
        "/api/imports/sales/ocr-preview",
        files={"file": ("sales.jpg", content, "image/jpeg")},
    )
    assert r.status_code == 200
    body = r.json()
    assert "rows" in body
    assert body["filename"] == "sales.jpg"
    # Even if OCR fails, blank editable rows are returned
    assert len(body["rows"]) >= 1


def test_purchase_date_override(client):
    products = client.get("/api/products").json()
    product = next(p for p in products if p["sku"] == "TEST-OIL-1L")
    r = client.post(
        "/api/purchases",
        json={
            "purchase_date": "2025-02-01T08:00:00",
            "items": [{"product_id": product["id"], "quantity": 3, "unit_cost": 400}],
        },
    )
    assert r.status_code == 200
    assert r.json()["purchase_date"].startswith("2025-02-01")


def test_confirm_purchase_rows(client):
    products = client.get("/api/products").json()
    spark = next(p for p in products if p["sku"] == "TEST-SPARK-1")
    before = spark["stock_qty"]
    r = client.post(
        "/api/imports/purchases/confirm-rows",
        json={
            "filename": "delivery.jpg",
            "purchase_date": "2025-02-15",
            "rows": [
                {
                    "row_number": 1,
                    "matched_product_id": spark["id"],
                    "quantity": 5,
                    "unit_cost": 180,
                    "include": True,
                }
            ],
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["purchases_created"] == 1
    assert data["stock_added"] == 5
    updated = client.get("/api/products").json()
    after = next(p for p in updated if p["sku"] == "TEST-SPARK-1")["stock_qty"]
    assert after == before + 5


def test_preview_sales_photo_with_forced_text(client):
    db = SessionLocal()
    try:
        # Empty image bytes still go through match path via parse of empty → blanks
        blank = Image.new("RGB", (100, 60), "white")
        buf = Path("/tmp/blank_ocr.jpg")
        blank.save(buf)
        result = preview_sales_photo(db, "blank.jpg", buf.read_bytes())
        assert result["matched_count"] == 0
        assert len(result["rows"]) >= 1
    finally:
        db.close()
