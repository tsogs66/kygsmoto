"""Held sales reserve the parts in them.

A basket parked at the till is a promise. These tests pin down what that
promise costs the rest of the shop: the parts stay on the shelf and in the
stock count, but they stop being free to sell.
"""
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
        cat = Category(name="Reservation Test")
        db.add(cat)
        db.flush()
        part = Product(sku="RSV-CHAIN", name="Reserve Test Chain Kit",
                       category_id=cat.id, cost_price=800, sell_price=1200,
                       stock_qty=10, reorder_level=2)
        spare = Product(sku="RSV-PLUG", name="Reserve Test Spark Plug",
                        category_id=cat.id, cost_price=90, sell_price=150,
                        stock_qty=4, reorder_level=2)
        labour = Product(sku="LABOR-RSV", name="Reserve Test Chain Fitting",
                         category_id=cat.id, cost_price=0, sell_price=250,
                         stock_qty=0, reorder_level=0)
        db.add_all([part, spare, labour])
        db.commit()
        return {"part_id": part.id, "spare_id": spare.id, "labour_id": labour.id}
    finally:
        db.close()


BASELINE = {"RSV-CHAIN": 10, "RSV-PLUG": 4, "LABOR-RSV": 0}


@pytest.fixture(autouse=True)
def _fresh_till(client, shop):
    """Start every test with an empty till and a known shelf.

    Reservations are the thing under test, so a claim or a sale left behind
    by the previous test would quietly change the next one's arithmetic.
    """
    for held in client.get("/api/holds").json()["holds"]:
        client.delete(f"/api/holds/{held['id']}")
    db = SessionLocal()
    try:
        for sku, qty in BASELINE.items():
            product = db.query(Product).filter(Product.sku == sku).one()
            product.stock_qty = qty
        db.commit()
    finally:
        db.close()
    yield


def _product(client, product_id):
    return next(p for p in client.get("/api/products").json() if p["id"] == product_id)


def _hold(client, lines, **kw):
    payload = {"customer_name": "Reserving Rider", "lines": lines}
    payload.update(kw)
    return client.post("/api/holds", json=payload)


def _sell(client, lines, **kw):
    payload = {"items": lines}
    payload.update(kw)
    return client.post("/api/sales", json=payload)


class TestWhatAHoldClaims:
    def test_a_hold_claims_its_parts_without_moving_stock(self, client, shop):
        before = _product(client, shop["part_id"])
        assert before["reserved_qty"] == 0
        assert before["available_qty"] == before["stock_qty"]

        _hold(client, [{"product_id": shop["part_id"], "quantity": 3}])

        after = _product(client, shop["part_id"])
        assert after["stock_qty"] == before["stock_qty"], "the parts are still on the shelf"
        assert after["reserved_qty"] == 3
        assert after["available_qty"] == before["stock_qty"] - 3

    def test_claims_from_several_holds_add_up(self, client, shop):
        _hold(client, [{"product_id": shop["part_id"], "quantity": 2}])
        _hold(client, [{"product_id": shop["part_id"], "quantity": 4}])
        assert _product(client, shop["part_id"])["reserved_qty"] == 6

    def test_labour_reserves_nothing(self, client, shop):
        _hold(client, [{"product_id": shop["labour_id"], "quantity": 5}])
        labour = _product(client, shop["labour_id"])
        assert labour["reserved_qty"] == 0
        assert labour["available_qty"] == labour["stock_qty"]

    def test_discarding_a_hold_releases_the_claim(self, client, shop):
        held = _hold(client, [{"product_id": shop["part_id"], "quantity": 3}]).json()
        assert _product(client, shop["part_id"])["reserved_qty"] == 3
        client.delete(f"/api/holds/{held['id']}")
        assert _product(client, shop["part_id"])["reserved_qty"] == 0

    def test_a_hold_reports_the_units_it_is_holding(self, client, shop):
        held = _hold(client, [
            {"product_id": shop["part_id"], "quantity": 3},
            {"product_id": shop["labour_id"], "quantity": 1},
        ]).json()
        assert held["reserved_units"] == 3, "labour is not stock"
        assert held["short_lines"] == 0


class TestSellingAgainstAHold:
    def test_the_counter_cannot_sell_what_is_held(self, client, shop):
        _hold(client, [{"product_id": shop["spare_id"], "quantity": 3}])
        res = _sell(client, [{"product_id": shop["spare_id"], "quantity": 2}])
        assert res.status_code == 409
        detail = res.json()["detail"]
        assert "Reserve Test Spark Plug" in detail
        assert "held at the till" in detail

    def test_what_is_left_over_still_sells(self, client, shop):
        _hold(client, [{"product_id": shop["spare_id"], "quantity": 3}])
        res = _sell(client, [{"product_id": shop["spare_id"], "quantity": 1}])
        assert res.status_code == 200, res.text

    def test_the_counter_can_override_and_sell_anyway(self, client, shop):
        _hold(client, [{"product_id": shop["spare_id"], "quantity": 3}])
        res = _sell(client, [{"product_id": shop["spare_id"], "quantity": 2}],
                    allow_shortfall=True)
        assert res.status_code == 200, res.text

    def test_splitting_a_line_does_not_slip_past_the_check(self, client, shop):
        _hold(client, [{"product_id": shop["spare_id"], "quantity": 3}])
        res = _sell(client, [
            {"product_id": shop["spare_id"], "quantity": 1},
            {"product_id": shop["spare_id"], "quantity": 1},
        ])
        assert res.status_code == 409, "two lines of one part are one claim"

    def test_releasing_the_hold_lets_the_sale_through(self, client, shop):
        held = _hold(client, [{"product_id": shop["spare_id"], "quantity": 3}]).json()
        assert _sell(client, [{"product_id": shop["spare_id"], "quantity": 2}]
                     ).status_code == 409
        client.delete(f"/api/holds/{held['id']}")
        assert _sell(client, [{"product_id": shop["spare_id"], "quantity": 2}]
                     ).status_code == 200

    def test_selling_into_negative_stock_still_works_when_nothing_is_held(
        self, client, shop
    ):
        """Parts often arrive ahead of their paperwork. That has not changed."""
        res = _sell(client, [{"product_id": shop["part_id"], "quantity": 9999}])
        assert res.status_code == 200, res.text
        assert _product(client, shop["part_id"])["stock_qty"] < 0

    def test_labour_is_never_blocked(self, client, shop):
        _hold(client, [{"product_id": shop["labour_id"], "quantity": 5}])
        res = _sell(client, [{"product_id": shop["labour_id"], "quantity": 5}])
        assert res.status_code == 200, res.text


class TestParkingAgainstAHold:
    def test_a_second_basket_cannot_claim_the_same_parts(self, client, shop):
        _hold(client, [{"product_id": shop["spare_id"], "quantity": 3}])
        res = _hold(client, [{"product_id": shop["spare_id"], "quantity": 2}])
        assert res.status_code == 409
        assert "hold anyway" in res.json()["detail"]

    def test_a_second_basket_can_take_what_is_left(self, client, shop):
        _hold(client, [{"product_id": shop["spare_id"], "quantity": 3}])
        assert _hold(client, [{"product_id": shop["spare_id"], "quantity": 1}]
                     ).status_code == 200

    def test_stock_the_shop_does_not_have_cannot_be_promised(self, client, shop):
        res = _hold(client, [{"product_id": shop["spare_id"], "quantity": 99}])
        assert res.status_code == 409, "a hold over thin air is not a promise"

    def test_but_the_counter_may_insist(self, client, shop):
        res = _hold(client, [{"product_id": shop["spare_id"], "quantity": 99}],
                    allow_shortfall=True)
        assert res.status_code == 200, res.text
        assert res.json()["lines"][0]["short"] is True, "flagged for the counter"

    def test_a_refused_hold_leaves_nothing_behind(self, client, shop):
        """The customer is created before the check runs — it must not stick."""
        before = len(client.get("/api/customers").json())
        res = _hold(client, [{"product_id": shop["spare_id"], "quantity": 99}],
                    customer_name="Ghost Rider", save_customer=True)
        assert res.status_code == 409
        assert len(client.get("/api/customers").json()) == before
        assert client.get("/api/holds").json()["count"] == 0

    def test_labour_can_always_be_parked(self, client, shop):
        res = _hold(client, [{"product_id": shop["labour_id"], "quantity": 3}])
        assert res.status_code == 200, res.text


class TestJobsSeeReservations:
    def _job(self, client, shop, quantity):
        job = client.post("/api/jobs", json={
            "customer_name": "Job Rider", "motorcycle": "Click 125",
            "lines": [{"product_id": shop["spare_id"], "quantity": quantity}],
        })
        assert job.status_code == 200, job.text
        return job.json()

    def test_a_ticket_flags_parts_held_at_the_till(self, client, shop):
        _hold(client, [{"product_id": shop["spare_id"], "quantity": 3}])
        job = self._job(client, shop, 2)
        line = job["lines"][0]
        assert line["reserved"] == 3
        assert line["available"] == line["on_hand"] - 3
        assert line["short"] is True
        assert job["short_lines"] == 1

    def test_checkout_warns_before_spending_a_parked_basket(self, client, shop):
        _hold(client, [{"product_id": shop["spare_id"], "quantity": 3}])
        job = self._job(client, shop, 2)
        res = client.post(f"/api/jobs/{job['id']}/checkout", json={})
        assert res.status_code == 409
        assert "held at the till" in res.json()["detail"]

    def test_the_mechanic_can_still_override(self, client, shop):
        _hold(client, [{"product_id": shop["spare_id"], "quantity": 3}])
        job = self._job(client, shop, 2)
        res = client.post(f"/api/jobs/{job['id']}/checkout",
                          json={"allow_negative_stock": True})
        assert res.status_code == 200, res.text
        # The hold's claim is untouched — only the shelf moved.
        assert _product(client, shop["spare_id"])["reserved_qty"] == 3

    def test_a_ticket_reserves_nothing_itself(self, client, shop):
        self._job(client, shop, 2)
        assert _product(client, shop["spare_id"])["reserved_qty"] == 0
