"""Tests for KYGS workbook import and tuned sales-column mapping."""

from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import Base, SessionLocal, engine
from app.main import app
from app.models.models import Product, Sale
from app.services.import_sales import _map_columns, read_sales_dataframe
from app.services.kygs_import import import_kygs_workbook

WORKBOOK = Path(__file__).resolve().parents[2] / "KYGS APRIL 2025.xlsm"


@pytest.fixture(scope="module")
def kygs_db():
    if not WORKBOOK.exists():
        pytest.skip("KYGS workbook not present")
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    result = import_kygs_workbook(db, WORKBOOK, replace_existing=True)
    yield db, result
    db.close()


def test_kygs_column_aliases():
    mapping = _map_columns(
        ["DATE", "ITEM CODE", "ITEM DESCRIPTION", "QTY", "PRICE", "DISCNT", "TOTAL"]
    )
    assert mapping["sale_date"] == "DATE"
    assert mapping["sku"] == "ITEM CODE"
    assert mapping["product_name"] == "ITEM DESCRIPTION"
    assert mapping["quantity"] == "QTY"
    assert mapping["unit_price"] == "PRICE"
    assert mapping["discount"] == "DISCNT"
    assert mapping["total"] == "TOTAL"


def test_read_kygs_sales_sheet():
    if not WORKBOOK.exists():
        pytest.skip("KYGS workbook not present")
    content = WORKBOOK.read_bytes()
    df = read_sales_dataframe(WORKBOOK.name, content)
    cols = [c.upper() for c in df.columns]
    assert "ITEM CODE" in cols or "ITEM_CODE" in [c.replace(" ", "_") for c in cols]
    assert len(df) >= 20


def test_import_kygs_workbook_counts(kygs_db):
    db, result = kygs_db
    assert result["products_created"] >= 1800
    assert result["services_created"] >= 20
    assert result["categories"] >= 15
    assert result["suppliers"] >= 5
    assert result["sale_lines"] >= 20
    assert db.query(Product).filter(Product.is_active.is_(True)).count() >= 1800
    assert db.query(Sale).count() >= 1
    oil = db.query(Product).filter(Product.sku == "OIL061").first()
    assert oil is not None
    assert oil.stock_qty == 42  # ending stock from workbook


def test_workbook_local_api(kygs_db):
    # DB already imported; call API in keep mode via TestClient would replace —
    # just verify health + products endpoint against running models.
    with TestClient(app) as client:
        products = client.get("/api/products?q=OIL061").json()
        assert any(p["sku"] == "OIL061" for p in products)
        dash = client.get("/api/reports/dashboard").json()
        assert dash["total_products"] >= 1800
