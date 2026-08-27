"""Held sales: parking a cart at the till with enough detail to identify it."""
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import Base, SessionLocal, engine
from app.main import app
from app.models.models import Category, Customer, Product


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
        cat = Category(name="Hold Test")
        db.add(cat)
        db.flush()
        part = Product(sku="HLD-OIL", name="Hold Test Oil", category_id=cat.id,
                       cost_price=250, sell_price=330, stock_qty=100, reorder_level=2)
        labour = Product(sku="LABOR-HLD", name="Hold Test Change Oil", category_id=cat.id,
                         cost_price=0, sell_price=70, stock_qty=0, reorder_level=0)
        saved = Customer(name="Held Rider", phone="0917-111-2222",
                         motorcycle_model="Click 125")
        db.add_all([part, labour, saved])
        db.commit()
        return {"part_id": part.id, "labour_id": labour.id, "customer_id": saved.id}
    finally:
        db.close()


def _stock(client, product_id):
    return next(p for p in client.get("/api/products").json()
                if p["id"] == product_id)["stock_qty"]


def _hold(client, shop, **kw):
    payload = {
        "customer_name": "Walk-in Wally", "plate_no": "abc 1234",
        "motorcycle": "Mio i125", "label": "Gone to the ATM",
        "lines": [
            {"product_id": shop["part_id"], "quantity": 2},
            {"product_id": shop["labour_id"], "quantity": 1},
        ],
    }
    payload.update(kw)
    res = client.post("/api/holds", json=payload)
    assert res.status_code == 200, res.text
    return res.json()


class TestHolding:
    def test_a_cart_can_be_parked_with_its_totals(self, client, shop):
        held = _hold(client, shop)
        assert held["reference"].startswith("HOLD-")
        assert held["parts_total"] == 660        # 2 x 330
        assert held["labour_total"] == 70
        assert held["total"] == 730
        assert held["line_count"] == 2

    def test_identification_is_recorded(self, client, shop):
        held = _hold(client, shop)
        assert held["customer_name"] == "Walk-in Wally"
        assert held["plate_no"] == "ABC 1234", "plates normalise to upper case"
        assert held["motorcycle"] == "Mio i125"
        assert held["label"] == "Gone to the ATM"

    def test_holding_does_not_touch_stock(self, client, shop):
        """A hold is not a sale — the parts are still on the shelf.

        They are reserved rather than sold, so the stock count stays true to
        the shelf while the basket waits. See test_reservations.py.
        """
        before = _stock(client, shop["part_id"])
        _hold(client, shop)
        assert _stock(client, shop["part_id"]) == before

    def test_an_empty_hold_is_refused(self, client, shop):
        res = client.post("/api/holds", json={"lines": []})
        assert res.status_code == 400
        assert "Nothing to hold" in res.json()["detail"]

    def test_line_discounts_are_kept(self, client, shop):
        held = _hold(client, shop, lines=[
            {"product_id": shop["part_id"], "quantity": 2, "discount": 60},
        ])
        assert held["discount_total"] == 60
        assert held["total"] == 600

    def test_an_over_large_discount_is_refused(self, client, shop):
        res = client.post("/api/holds", json={
            "lines": [{"product_id": shop["part_id"], "quantity": 1, "discount": 9999}],
        })
        assert res.status_code == 400

    def test_unknown_product_is_refused(self, client, shop):
        res = client.post("/api/holds", json={
            "lines": [{"product_id": 999999, "quantity": 1}],
        })
        assert res.status_code == 400

    def test_references_are_unique(self, client, shop):
        a = _hold(client, shop)["reference"]
        b = _hold(client, shop)["reference"]
        assert a != b


class TestCustomerOnHold:
    def test_a_saved_customer_can_be_attached(self, client, shop):
        held = _hold(client, shop, customer_id=shop["customer_id"], customer_name=None)
        assert held["customer_id"] == shop["customer_id"]
        assert held["customer_name"] == "Held Rider", "falls back to the saved record"

    def test_a_walk_in_can_be_saved_while_holding(self, client, shop):
        before = len(client.get("/api/customers").json())
        held = _hold(client, shop, customer_name="Saved At Hold",
                     contact="0920-333-4444", motorcycle="Raider 150",
                     save_customer=True)
        assert held["customer_id"] is not None

        customers = client.get("/api/customers").json()
        assert len(customers) == before + 1
        saved = next(c for c in customers if c["id"] == held["customer_id"])
        assert saved["phone"] == "0920-333-4444"
        assert saved["motorcycle_model"] == "Raider 150"

    def test_a_walk_in_is_not_saved_unless_asked(self, client, shop):
        before = len(client.get("/api/customers").json())
        held = _hold(client, shop, customer_name="Just Passing")
        assert held["customer_id"] is None
        assert len(client.get("/api/customers").json()) == before


class TestListingAndResuming:
    def test_holds_are_listed_oldest_first(self, client, shop):
        body = client.get("/api/holds").json()
        assert body["count"] >= 2
        times = [h["created_at"] for h in body["holds"]]
        assert times == sorted(times), "oldest first, so nothing is forgotten"
        assert body["total_value"] > 0

    def test_holds_report_how_long_they_have_waited(self, client, shop):
        body = client.get("/api/holds").json()
        assert all(h["held_for_minutes"] is not None for h in body["holds"])

    def test_a_hold_can_be_found_by_plate(self, client, shop):
        _hold(client, shop, plate_no="ZZZ 8888")
        found = client.get("/api/holds", params={"q": "ZZZ 8888"}).json()["holds"]
        assert found and found[0]["plate_no"] == "ZZZ 8888"

    def test_a_hold_can_be_found_by_customer(self, client, shop):
        _hold(client, shop, customer_name="Findable Held")
        found = client.get("/api/holds", params={"q": "Findable"}).json()["holds"]
        assert found and found[0]["customer_name"] == "Findable Held"

    def test_a_hold_can_be_fetched_for_resuming(self, client, shop):
        held = _hold(client, shop)
        fetched = client.get(f"/api/holds/{held['id']}").json()
        assert fetched["id"] == held["id"]
        assert len(fetched["lines"]) == 2
        # Enough to rebuild the cart exactly.
        line = fetched["lines"][0]
        assert {"product_id", "quantity", "unit_price", "discount"} <= set(line)

    def test_a_hold_can_be_discarded(self, client, shop):
        held = _hold(client, shop)
        res = client.delete(f"/api/holds/{held['id']}")
        assert res.status_code == 200
        assert res.json()["reference"] == held["reference"]
        assert client.get(f"/api/holds/{held['id']}").status_code == 404

    def test_discarding_a_hold_leaves_stock_alone(self, client, shop):
        before = _stock(client, shop["part_id"])
        held = _hold(client, shop)
        client.delete(f"/api/holds/{held['id']}")
        assert _stock(client, shop["part_id"]) == before

    def test_resuming_and_selling_moves_stock_once(self, client, shop):
        """The till rebuilds the cart from the hold, clears it, then sells.

        Clearing comes first: while the hold stands it has the parts reserved,
        and the sale would rightly refuse to spend them.
        """
        before = _stock(client, shop["part_id"])
        held = _hold(client, shop)
        client.delete(f"/api/holds/{held['id']}")

        sale = client.post("/api/sales", json={
            "customer_id": held["customer_id"],
            "items": [
                {"product_id": l["product_id"], "quantity": l["quantity"],
                 "unit_price": l["unit_price"], "discount": l["discount"]}
                for l in held["lines"]
            ],
        }).json()

        assert sale["total"] == held["total"]
        assert _stock(client, shop["part_id"]) == before - 2
        assert client.get(f"/api/holds/{held['id']}").status_code == 404
