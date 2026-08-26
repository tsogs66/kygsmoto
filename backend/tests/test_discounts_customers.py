"""Per-line discounts on parts and labour, and saved-customer handling."""
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import Base, SessionLocal, engine
from app.main import app
from app.models.models import Category, Product


@pytest.fixture(scope="module")
def client():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def shop(client):
    db = SessionLocal()
    try:
        cat = Category(name="Discount Test")
        db.add(cat)
        db.flush()
        part = Product(sku="DSC-PAD", name="Discount Brake Pad", category_id=cat.id,
                       cost_price=120, sell_price=200, stock_qty=5000, reorder_level=2)
        labour = Product(sku="LABOR-DSC", name="Discount Brake Labour", category_id=cat.id,
                         cost_price=0, sell_price=150, stock_qty=0, reorder_level=0)
        db.add_all([part, labour])
        db.commit()
        return {"part_id": part.id, "labour_id": labour.id}
    finally:
        db.close()


class TestSaleLineDiscounts:
    def test_discount_reduces_the_line_and_the_sale(self, client, shop):
        sale = client.post("/api/sales", json={
            "items": [
                {"product_id": shop["part_id"], "quantity": 2, "discount": 40},
                {"product_id": shop["labour_id"], "quantity": 1, "discount": 25},
            ],
        }).json()
        # (2 x 200 - 40) + (150 - 25) = 360 + 125
        assert sale["subtotal"] == 485
        assert sale["total"] == 485
        by_sku = {i["sku"]: i for i in sale["items"]}
        assert by_sku["DSC-PAD"]["discount"] == 40
        assert by_sku["DSC-PAD"]["line_total"] == 360
        assert by_sku["LABOR-DSC"]["discount"] == 25
        assert by_sku["LABOR-DSC"]["line_total"] == 125

    def test_a_labour_line_can_be_discounted(self, client, shop):
        """Services discount the same way parts do."""
        sale = client.post("/api/sales", json={
            "items": [{"product_id": shop["labour_id"], "quantity": 2, "discount": 100}],
        }).json()
        assert sale["items"][0]["line_total"] == 200      # 2 x 150 - 100

    def test_no_discount_is_the_default(self, client, shop):
        sale = client.post("/api/sales", json={
            "items": [{"product_id": shop["part_id"], "quantity": 1}],
        }).json()
        assert sale["items"][0]["discount"] == 0
        assert sale["items"][0]["line_total"] == 200

    def test_a_line_cannot_go_negative(self, client, shop):
        """An over-large discount is capped, never a negative line."""
        sale = client.post("/api/sales", json={
            "items": [{"product_id": shop["part_id"], "quantity": 1, "discount": 9999}],
        }).json()
        assert sale["items"][0]["line_total"] == 0
        assert sale["total"] == 0

    def test_negative_discounts_are_refused(self, client, shop):
        res = client.post("/api/sales", json={
            "items": [{"product_id": shop["part_id"], "quantity": 1, "discount": -50}],
        })
        assert res.status_code == 422

    def test_line_and_order_discounts_combine(self, client, shop):
        sale = client.post("/api/sales", json={
            "items": [{"product_id": shop["part_id"], "quantity": 2, "discount": 40}],
            "discount": 60,
        }).json()
        assert sale["subtotal"] == 360        # line discount applied
        assert sale["total"] == 300           # then the order discount


class TestJobLineDiscounts:
    def test_job_totals_account_for_line_discounts(self, client, shop):
        job = client.post("/api/jobs", json={
            "customer_name": "Discount Rider",
            "lines": [
                {"product_id": shop["part_id"], "quantity": 2, "discount": 40},
                {"product_id": shop["labour_id"], "quantity": 1, "discount": 25},
            ],
        }).json()
        assert job["parts_total"] == 360
        assert job["labour_total"] == 125
        assert job["discount_total"] == 65
        assert job["total"] == 485

    def test_discounts_carry_through_to_the_invoice(self, client, shop):
        job = client.post("/api/jobs", json={
            "lines": [{"product_id": shop["part_id"], "quantity": 2, "discount": 40}],
        }).json()
        body = client.post(f"/api/jobs/{job['id']}/checkout", json={}).json()
        assert body["sale"]["items"][0]["discount"] == 40
        assert body["sale"]["total"] == 360

    def test_a_discount_larger_than_the_line_is_refused(self, client, shop):
        res = client.post("/api/jobs", json={
            "lines": [{"product_id": shop["part_id"], "quantity": 1, "discount": 9999}],
        })
        assert res.status_code == 400
        assert "more than the line total" in res.json()["detail"]

    def test_discount_can_be_added_to_an_open_job(self, client, shop):
        job = client.post("/api/jobs", json={"lines": []}).json()
        grown = client.post(f"/api/jobs/{job['id']}/lines", json={
            "product_id": shop["labour_id"], "quantity": 1, "discount": 50,
        }).json()
        assert grown["labour_total"] == 100
        assert grown["discount_total"] == 50


class TestJobCustomers:
    def test_a_job_can_use_a_saved_customer(self, client, shop):
        customer = client.post("/api/customers", json={
            "name": "Saved Rider", "phone": "0917-000-0000",
            "motorcycle_model": "NMAX v2",
        }).json()

        job = client.post("/api/jobs", json={
            "customer_id": customer["id"], "lines": [],
        }).json()
        assert job["customer_id"] == customer["id"]
        assert job["customer_name"] == "Saved Rider", "falls back to the saved record"

    def test_a_walk_in_can_be_saved_as_a_customer(self, client, shop):
        before = len(client.get("/api/customers").json())
        job = client.post("/api/jobs", json={
            "customer_name": "New Walk-in", "contact": "0918-111-1111",
            "motorcycle": "Click 125", "save_customer": True, "lines": [],
        }).json()

        assert job["customer_id"] is not None
        customers = client.get("/api/customers").json()
        assert len(customers) == before + 1

        saved = next(c for c in customers if c["id"] == job["customer_id"])
        assert saved["name"] == "New Walk-in"
        assert saved["phone"] == "0918-111-1111"
        assert saved["motorcycle_model"] == "Click 125"

    def test_a_walk_in_is_not_saved_unless_asked(self, client, shop):
        before = len(client.get("/api/customers").json())
        job = client.post("/api/jobs", json={
            "customer_name": "Passing Trade", "lines": [],
        }).json()
        assert job["customer_id"] is None
        assert job["customer_name"] == "Passing Trade"
        assert len(client.get("/api/customers").json()) == before

    def test_saving_needs_a_name(self, client, shop):
        before = len(client.get("/api/customers").json())
        job = client.post("/api/jobs", json={
            "save_customer": True, "contact": "0919", "lines": [],
        }).json()
        assert job["customer_id"] is None, "an empty name must not create a record"
        assert len(client.get("/api/customers").json()) == before

    def test_customers_can_be_searched(self, client, shop):
        client.post("/api/customers", json={"name": "Findable Fernandez"})
        found = client.get("/api/customers", params={"q": "Fernandez"}).json()
        assert any(c["name"] == "Findable Fernandez" for c in found)


class TestMigration:
    def test_discount_columns_exist_on_both_line_tables(self, client):
        from sqlalchemy import text
        from app.core.database import engine as eng
        with eng.begin() as conn:
            for table in ("sale_items", "job_lines"):
                cols = {r[1] for r in conn.execute(text(f"PRAGMA table_info({table})"))}
                assert "discount" in cols, f"{table} is missing the discount column"
