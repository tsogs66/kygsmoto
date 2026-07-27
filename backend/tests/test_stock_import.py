"""Tests for stock CSV import and KYGS extract samples."""

from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import Base, SessionLocal, engine
from app.main import app
from app.models.models import Product
from app.services.import_stock import import_stock_file, preview_stock_file
from app.services.kygs_import import import_kygs_workbook

ROOT = Path(__file__).resolve().parents[2]
WORKBOOK = ROOT / "KYGS APRIL 2025.xlsm"
INVENTORY_CSV = ROOT / "samples" / "kygs_current_inventory.csv"
STOCK_TMPL = ROOT / "samples" / "kygs_stock_upload_template.csv"


@pytest.fixture(scope="module")
def stock_db():
    if not WORKBOOK.exists():
        pytest.skip("KYGS workbook not present")
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    import_kygs_workbook(db, WORKBOOK, replace_existing=True)
    yield db
    db.close()


def test_extracted_samples_exist():
    assert INVENTORY_CSV.exists()
    assert STOCK_TMPL.exists()
    assert (ROOT / "samples" / "kygs_sales_export.csv").exists()
    # inventory extract should be large
    assert INVENTORY_CSV.stat().st_size > 50_000


def test_stock_preview_set_mode(stock_db):
    content = STOCK_TMPL.read_bytes()
    preview = preview_stock_file(stock_db, STOCK_TMPL.name, content, mode="set")
    assert preview["matched_count"] >= 1
    assert preview["mode"] == "set"


def test_stock_import_set_updates_qty(stock_db):
    # Use a tiny CSV for one known SKU
    product = stock_db.query(Product).filter(Product.sku == "OIL061").first()
    assert product is not None
    csv = b"ITEM CODE,DESCRIPTION,ENDING STOCKS\nOIL061,GREASE HI-TEMP 10G - KOBY,99\n"
    result = import_stock_file(stock_db, "oil_set.csv", csv, mode="set")
    assert result["rows_updated"] == 1
    stock_db.refresh(product)
    assert product.stock_qty == 99


def test_stock_import_adjust(stock_db):
    product = stock_db.query(Product).filter(Product.sku == "OIL061").first()
    before = float(product.stock_qty)
    csv = b"ITEM CODE,ADJUST\nOIL061,5\n"
    result = import_stock_file(stock_db, "oil_adj.csv", csv, mode="adjust")
    assert result["rows_updated"] == 1
    stock_db.refresh(product)
    assert product.stock_qty == before + 5


def test_stock_api_endpoints(stock_db):
    with TestClient(app) as client:
        content = STOCK_TMPL.read_bytes()
        preview = client.post(
            "/api/imports/stock/preview",
            files={"file": ("kygs_stock_upload_template.csv", content, "text/csv")},
            data={"mode": "set"},
        )
        assert preview.status_code == 200
        body = preview.json()
        assert body["matched_count"] >= 1
