"""Purchase edit + receipt attachment tests."""

from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import Base, SessionLocal, engine, ensure_sqlite_columns
from app.main import app
from app.models.models import Category, Product


def _seed(db):
    cat = Category(name="Parts")
    db.add(cat)
    db.flush()
    db.add(
        Product(
            sku="PO-OIL-1",
            name="Purchase Oil",
            category_id=cat.id,
            cost_price=100,
            sell_price=150,
            stock_qty=10,
            reorder_level=2,
        )
    )
    db.add(
        Product(
            sku="PO-SPARK-1",
            name="Purchase Spark",
            category_id=cat.id,
            cost_price=50,
            sell_price=80,
            stock_qty=20,
            reorder_level=2,
        )
    )
    db.commit()


@pytest.fixture(scope="module")
def client():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    ensure_sqlite_columns()
    db = SessionLocal()
    _seed(db)
    db.close()
    with TestClient(app) as c:
        yield c


def test_create_edit_purchase_adjusts_stock(client):
    products = client.get("/api/products").json()
    oil = next(p for p in products if p["sku"] == "PO-OIL-1")
    spark = next(p for p in products if p["sku"] == "PO-SPARK-1")

    created = client.post(
        "/api/purchases",
        json={
            "purchase_date": "2025-05-01T10:00:00",
            "items": [{"product_id": oil["id"], "quantity": 5, "unit_cost": 100}],
        },
    )
    assert created.status_code == 200
    po = created.json()
    assert po["po_no"]
    after_create = next(p for p in client.get("/api/products").json() if p["sku"] == "PO-OIL-1")
    assert after_create["stock_qty"] == 15

    line_id = po["items"][0]["id"]
    updated = client.put(
        f"/api/purchases/{po['id']}",
        json={
            "purchase_date": "2025-05-02T11:00:00",
            "notes": "corrected",
            "items": [
                {"id": line_id, "product_id": oil["id"], "quantity": 3, "unit_cost": 110},
                {"product_id": spark["id"], "quantity": 2, "unit_cost": 50},
            ],
        },
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["notes"] == "corrected"
    assert body["purchase_date"].startswith("2025-05-02")
    assert len(body["items"]) == 2

    products2 = client.get("/api/products").json()
    oil2 = next(p for p in products2 if p["sku"] == "PO-OIL-1")
    spark2 = next(p for p in products2 if p["sku"] == "PO-SPARK-1")
    # 15 + (3-5) = 13
    assert oil2["stock_qty"] == 13
    # 20 + 2 = 22
    assert spark2["stock_qty"] == 22

    # Frontend-style naive datetime-local payload must persist wall-clock time
    line_ids = [i["id"] for i in body["items"]]
    again = client.put(
        f"/api/purchases/{po['id']}",
        json={
            "supplier_id": None,
            "purchase_date": "2025-06-15T14:30:00",
            "notes": "afternoon delivery",
            "items": [
                {"id": line_ids[0], "product_id": oil["id"], "quantity": 4, "unit_cost": 110},
                {"id": line_ids[1], "product_id": spark["id"], "quantity": 2, "unit_cost": 50},
            ],
        },
    )
    assert again.status_code == 200
    again_body = again.json()
    assert again_body["purchase_date"].startswith("2025-06-15T14:30")
    assert again_body["notes"] == "afternoon delivery"
    assert again_body["total"] == 4 * 110 + 2 * 50
    listed = client.get("/api/purchases").json()
    row = next(p for p in listed if p["id"] == po["id"])
    assert row["purchase_date"].startswith("2025-06-15T14:30")
    assert row["notes"] == "afternoon delivery"
    assert row["total"] == again_body["total"]


def test_purchase_receipt_upload(client, tmp_path):
    products = client.get("/api/products").json()
    oil = next(p for p in products if p["sku"] == "PO-OIL-1")
    po = client.post(
        "/api/purchases",
        json={"items": [{"product_id": oil["id"], "quantity": 1, "unit_cost": 100}]},
    ).json()

    img = Image.new("RGB", (120, 80), "white")
    path = tmp_path / "receipt.jpg"
    img.save(path)
    content = path.read_bytes()

    up = client.post(
        f"/api/purchases/{po['id']}/receipt",
        files={"file": ("receipt.jpg", content, "image/jpeg")},
    )
    assert up.status_code == 200
    assert up.json()["has_receipt"] is True

    got = client.get(f"/api/purchases/{po['id']}")
    assert got.json()["has_receipt"] is True

    receipt = client.get(f"/api/purchases/{po['id']}/receipt")
    assert receipt.status_code == 200
    assert receipt.content[:2] == b"\xff\xd8"  # jpeg

    deleted = client.delete(f"/api/purchases/{po['id']}/receipt")
    assert deleted.status_code == 200
    assert client.get(f"/api/purchases/{po['id']}").json()["has_receipt"] is False
