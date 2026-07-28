"""Quotation / Detailed Invoice Register purchase OCR parsing + item-code match."""

from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import Base, SessionLocal, engine
from app.main import app
from app.models.models import Category, Product
from app.services.ocr_sales import (
    looks_like_invoice_register,
    match_ocr_rows,
    parse_invoice_register,
    parse_ocr_lines,
    preview_sales_photo,
)


SAMPLE_INVOICE = """
QUOTATION / Detailed Invoice Register
1/1/2025 To 4/4/2025
04/04/2025
Tran No: 00000000000018051
Customer: KYGS MP
Address: SAN ANTONIO ZAMBALES
04/04/25 09:10 AM
Inv No: 00-000000000018051
Item Code Description Quantity UOM Price Amount
1732 OIL HAVOLINE EZY 1LTR 12 PCS 187.00 2,244.00
1733 OIL HAVOLINE EZY 800ML 12 PCS 148.00 1,776.00
1812 OIL YAMALUBE BLUE CORE LTR 13 PCS 296.00 3,848.00
RS8GEAROIL RS8 GEAR OIL SCOOTER RACING 120ML 30 PCS 48.00 1,440.00
OILG GEAR OIL JVT 30 PCS 47.00 1,410.00
GFRWG WIRE H.D 2 PCS 340.00 680.00
1151 FUEL HOSE MSB 18M OR 59FT 2 RL 250.00 500.00
HTEWH TIMING GEAR TMX YAKIMOTO 5 SET 292.00 1,460.00
KBCWL KNUCKLE BEARING C100/W125/BONUS110 LIMAN 5 PCS 79.00 395.00
KBMRL KNUCKLE BEARING MIO/RS100/STX LIMAN 5 SET 91.00 455.00
78 BATTERY OD 12N7BL 3 PCS 670.00 2,010.00
85 BATTERY OD YTX5L 5 PCS 530.00 2,650.00
SPR34 TIRE SPRINT 250X17 JUMBO 8PLY 3 PCS 405.00 1,215.00
M275X18MX2 TIRE MAXIMUS 275X18 TT MX20B 3 PCS 527.00 1,581.00
Totals 21,664.00
Discount 0.00
Grand Total 21,664.00
"""

MULTI_INVOICE = """
QUOTATION Detailed Invoice Register
1/1/2025 To 4/15/2025
04/15/2025
Tran No: 000000000000018262
04/15/25 10:07 AM
Inv No: 00-000000000018262
Item Code Description Quantity UOM Price Amount
1806 OIL SHELL AX7 800ML 12 PCS 225.00 2,700.00
VS1B VS1 BIG ORIGINAL (250ML) 10 PCS 164.00 1,640.00
1232 GEAR OIL YAMALUBE 36 PCS 61.00 2,196.00
Grand Total 9,496.00

Tran No: 000000000000018263
04/15/25 10:07 AM
Inv No: 00-000000000018263
TQ80X80TL TIRE QUICK 80X80X14 TL 2 PCS 870.00 1,740.00
CPR88EA-9 SPARKPLUG NGK W125 CPR8EA-9 20 PCS 108.00 2,160.00
82 BATTERY OD 4L 5 PCS 445.00 2,225.00
M275X18MX2 TIRE MAXIMUS 275X18 TT MX20B 2 PCS 527.00 1,054.00
Grand Total 42,814.00
"""


def _seed(db):
    cat = Category(name="Invoice Parts")
    db.add(cat)
    db.flush()
    samples = [
        ("1732", "OIL HAVOLINE EZY 1LTR", 187, 220),
        ("RS8GEAROIL", "RS8 GEAR OIL SCOOTER RACING 120ML", 48, 65),
        ("M275X18MX2", "TIRE MAXIMUS 275X18 TT MX20B", 527, 650),
        ("78", "BATTERY OD 12N7BL", 670, 800),
        ("CPR88EA-9", "SPARKPLUG NGK W125 CPR8EA-9", 108, 140),
        ("TQ80X80TL", "TIRE QUICK 80X80X14 TL", 870, 980),
        ("1806", "OIL SHELL AX7 800ML", 225, 280),
    ]
    for sku, name, cost, sell in samples:
        db.add(
            Product(
                sku=sku,
                name=name,
                category_id=cat.id,
                cost_price=cost,
                sell_price=sell,
                stock_qty=10,
                reorder_level=2,
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


def test_detect_invoice_register():
    assert looks_like_invoice_register(SAMPLE_INVOICE) is True
    assert looks_like_invoice_register("Date: 04/15/2025\nTEST-OIL Motul 2 650") is False


def test_parse_invoice_register_lines():
    rows = parse_invoice_register(SAMPLE_INVOICE)
    assert len(rows) == 14
    codes = [r["sku"] for r in rows]
    assert "1732" in codes
    assert "RS8GEAROIL" in codes
    assert "M275X18MX2" in codes
    assert "78" in codes
    oil = next(r for r in rows if r["sku"] == "1732")
    assert oil["quantity"] == 12
    assert oil["uom"] == "PCS"
    assert oil["unit_price"] == 187.0
    assert oil["line_amount"] == 2244.0
    assert oil["sale_date"] == "2025-04-04"
    assert oil["invoice_no"] and "18051" in oil["invoice_no"]
    hose = next(r for r in rows if r["sku"] == "1151")
    assert hose["uom"] == "RL"
    gear = next(r for r in rows if r["sku"] == "HTEWH")
    assert gear["uom"] == "SET"


def test_parse_ocr_lines_prefers_register():
    rows = parse_ocr_lines(SAMPLE_INVOICE)
    assert len(rows) >= 14
    assert all(r.get("sku") for r in rows)


def test_multi_invoice_sections():
    rows = parse_invoice_register(MULTI_INVOICE)
    assert len(rows) >= 7
    invs = {r["invoice_no"] for r in rows}
    assert any(i and "18262" in i for i in invs)
    assert any(i and "18263" in i for i in invs)
    assert all(r["sale_date"] == "2025-04-15" for r in rows)


def test_item_code_matches_inventory(client):
    db = SessionLocal()
    try:
        parsed = parse_invoice_register(SAMPLE_INVOICE)
        rows = match_ocr_rows(db, parsed, mode="purchase")
        matched = [r for r in rows if r["status"] == "matched"]
        codes = {r["sku"] for r in matched}
        assert "1732" in codes
        assert "RS8GEAROIL" in codes
        assert "M275X18MX2" in codes
        assert "78" in codes
        oil = next(r for r in matched if r["sku"] == "1732")
        assert oil["unit_price"] == 187.0  # invoice Price kept as unit cost
    finally:
        db.close()


def test_preview_purchase_invoice_document_type(client):
    db = SessionLocal()
    try:
        out = preview_sales_photo(
            db,
            "invoice.jpg",
            b"",
            mode="purchase",
            ocr_result={"filename": "invoice.jpg", "engine": "test", "raw_text": SAMPLE_INVOICE},
        )
        assert out["document_type"] == "invoice_register"
        assert out["matched_count"] >= 4
        assert "Invoice Register" in out["message"] or "Item Code" in out["message"]
    finally:
        db.close()


def test_confirm_multi_invoice_creates_separate_purchases(client):
    products = {p["sku"]: p for p in client.get("/api/products").json()}
    rows = [
        {
            "row_number": 1,
            "invoice_no": "00-000000000018262",
            "sale_date": "2025-04-15",
            "sku": "1806",
            "quantity": 12,
            "unit_price": 225,
            "matched_product_id": products["1806"]["id"],
            "include": True,
        },
        {
            "row_number": 2,
            "invoice_no": "00-000000000018263",
            "sale_date": "2025-04-15",
            "sku": "TQ80X80TL",
            "quantity": 2,
            "unit_price": 870,
            "matched_product_id": products["TQ80X80TL"]["id"],
            "include": True,
        },
    ]
    r = client.post(
        "/api/imports/purchases/confirm-rows",
        json={"filename": "multi-inv.jpg", "purchase_date": "2025-04-15", "rows": rows},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["purchases_created"] == 2
    assert body["rows_imported"] == 2
    assert len(body.get("po_nos") or []) == 2
