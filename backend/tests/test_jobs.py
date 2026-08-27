"""Job queue: ticket lifecycle, stock timing and the pending-work board."""
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
        cat = Category(name="Job Test Parts")
        db.add(cat)
        db.flush()
        # Ample stock: these tests check out repeatedly, and a small balance
        # would couple them to each other's execution order.
        part = Product(sku="JOB-PAD", name="Job Test Brake Pad", category_id=cat.id,
                       cost_price=120, sell_price=200, stock_qty=5000, reorder_level=2)
        # Deliberately scarce, used only by the shortage tests.
        scarce = Product(sku="JOB-RARE", name="Job Test Rare Cam", category_id=cat.id,
                         cost_price=800, sell_price=1200, stock_qty=1, reorder_level=1)
        # Labour follows the shop's LABOR-* convention: carries no stock.
        labour = Product(sku="LABOR-BRAKE", name="Brake Job Labour", category_id=cat.id,
                         cost_price=0, sell_price=150, stock_qty=0, reorder_level=0)
        db.add_all([part, scarce, labour])
        db.commit()
        return {"part_id": part.id, "labour_id": labour.id, "scarce_id": scarce.id}
    finally:
        db.close()


def _stock(client, product_id):
    return next(p for p in client.get("/api/products").json()
                if p["id"] == product_id)["stock_qty"]


def _new_job(client, shop, **kw):
    payload = {
        "customer_name": "Pedro Santos", "plate_no": "abc 1234",
        "motorcycle": "Mio i125", "complaint": "Front brake squealing",
        "lines": [
            {"product_id": shop["part_id"], "quantity": 2},
            {"product_id": shop["labour_id"], "quantity": 1},
        ],
    }
    payload.update(kw)
    res = client.post("/api/jobs", json=payload)
    assert res.status_code == 200, res.text
    return res.json()


class TestCreation:
    def test_job_opens_with_parts_and_labour(self, client, shop):
        job = _new_job(client, shop)
        assert job["status"] == "queued"
        assert job["job_no"].startswith("JOB-")
        assert job["plate_no"] == "ABC 1234", "plates are normalised to upper case"
        assert job["parts_total"] == 400      # 2 x 200
        assert job["labour_total"] == 150
        assert job["total"] == 550

    def test_labour_is_recognised_by_the_shops_sku_convention(self, client, shop):
        job = _new_job(client, shop)
        labour_lines = [l for l in job["lines"] if l["is_labour"]]
        assert len(labour_lines) == 1
        assert labour_lines[0]["sku"].startswith("LABOR")

    def test_opening_a_job_does_not_move_stock(self, client, shop):
        before = _stock(client, shop["part_id"])
        _new_job(client, shop)
        assert _stock(client, shop["part_id"]) == before

    def test_a_job_can_start_empty(self, client, shop):
        assert _new_job(client, shop, lines=[])["total"] == 0

    def test_bad_priority_is_refused(self, client, shop):
        assert client.post("/api/jobs",
                           json={"priority": "screaming", "lines": []}).status_code == 400

    def test_unknown_product_is_refused(self, client, shop):
        res = client.post("/api/jobs",
                          json={"lines": [{"product_id": 999999, "quantity": 1}]})
        assert res.status_code == 400


class TestWorkflow:
    def test_status_moves_forward_and_stamps_times(self, client, shop):
        job = _new_job(client, shop)
        started = client.patch(f"/api/jobs/{job['id']}",
                               json={"status": "in_progress"}).json()
        assert started["status"] == "in_progress"
        assert started["started_at"]

        ready = client.patch(f"/api/jobs/{job['id']}", json={"status": "ready"}).json()
        assert ready["status"] == "ready"
        assert ready["ready_at"]

    def test_completed_cannot_be_set_by_hand(self, client, shop):
        job = _new_job(client, shop)
        res = client.patch(f"/api/jobs/{job['id']}", json={"status": "completed"})
        assert res.status_code == 400
        assert "taking payment" in res.json()["detail"]

    def test_cancelled_job_is_frozen(self, client, shop):
        job = _new_job(client, shop)
        client.post(f"/api/jobs/{job['id']}/cancel", json={"reason": "Customer took it home"})
        assert client.patch(f"/api/jobs/{job['id']}",
                            json={"status": "in_progress"}).status_code == 409
        assert client.post(f"/api/jobs/{job['id']}/lines",
                           json={"product_id": shop["labour_id"],
                                 "quantity": 1}).status_code == 409

    def test_cancelling_needs_a_reason(self, client, shop):
        job = _new_job(client, shop)
        assert client.post(f"/api/jobs/{job['id']}/cancel",
                           json={"reason": "no"}).status_code == 422

    def test_lines_can_be_added_and_removed_while_open(self, client, shop):
        job = _new_job(client, shop)
        grown = client.post(f"/api/jobs/{job['id']}/lines",
                            json={"product_id": shop["labour_id"], "quantity": 1}).json()
        assert grown["labour_total"] == 300

        line_id = grown["lines"][-1]["id"]
        shrunk = client.delete(f"/api/jobs/{job['id']}/lines/{line_id}").json()
        assert shrunk["labour_total"] == 150


class TestShortages:
    def test_a_line_beyond_stock_is_flagged(self, client, shop):
        job = _new_job(client, shop,
                       lines=[{"product_id": shop["scarce_id"], "quantity": 999}])
        assert job["short_lines"] == 1
        assert job["lines"][0]["short"] is True

    def test_labour_is_never_short(self, client, shop):
        """Labour carries no stock, so it must never be flagged."""
        job = _new_job(client, shop,
                       lines=[{"product_id": shop["labour_id"], "quantity": 99}])
        assert job["short_lines"] == 0

    def test_checkout_is_blocked_when_stock_is_short(self, client, shop):
        job = _new_job(client, shop,
                       lines=[{"product_id": shop["scarce_id"], "quantity": 999}])
        res = client.post(f"/api/jobs/{job['id']}/checkout", json={})
        assert res.status_code == 409
        assert "Not enough free stock" in res.json()["detail"]

        still = client.get(f"/api/jobs/{job['id']}").json()
        assert still["status"] in ("queued", "in_progress", "ready")
        assert still["sale_id"] is None

    def test_shortage_can_be_overridden_deliberately(self, client, shop):
        job = _new_job(client, shop,
                       lines=[{"product_id": shop["scarce_id"], "quantity": 999}])
        res = client.post(f"/api/jobs/{job['id']}/checkout",
                          json={"allow_negative_stock": True})
        assert res.status_code == 200
        assert res.json()["job"]["status"] == "completed"


class TestCheckout:
    def test_checkout_creates_a_sale_and_moves_stock_then(self, client, shop):
        before = _stock(client, shop["part_id"])
        job = _new_job(client, shop)

        body = client.post(f"/api/jobs/{job['id']}/checkout", json={}).json()
        assert body["sale"]["total"] == 550
        assert body["job"]["status"] == "completed"
        assert body["job"]["sale_id"] == body["sale"]["id"]
        assert body["job"]["invoice_no"] == body["sale"]["invoice_no"]

        assert _stock(client, shop["part_id"]) == before - 2, "stock moves at checkout"

    def test_labour_does_not_deduct_stock_at_checkout(self, client, shop):
        before = _stock(client, shop["labour_id"])
        job = _new_job(client, shop,
                       lines=[{"product_id": shop["labour_id"], "quantity": 3}])
        client.post(f"/api/jobs/{job['id']}/checkout", json={})
        assert _stock(client, shop["labour_id"]) == before

    def test_a_completed_job_cannot_be_charged_twice(self, client, shop):
        job = _new_job(client, shop)
        client.post(f"/api/jobs/{job['id']}/checkout", json={})
        again = client.post(f"/api/jobs/{job['id']}/checkout", json={})
        assert again.status_code == 400
        assert "already completed" in again.json()["detail"]

    def test_an_empty_job_cannot_be_charged(self, client, shop):
        job = _new_job(client, shop, lines=[])
        assert client.post(f"/api/jobs/{job['id']}/checkout", json={}).status_code == 400

    def test_the_sale_records_the_job_number(self, client, shop):
        job = _new_job(client, shop)
        body = client.post(f"/api/jobs/{job['id']}/checkout", json={}).json()
        assert job["job_no"] in body["sale"]["notes"]

    def test_discount_carries_to_the_sale(self, client, shop):
        job = _new_job(client, shop)
        body = client.post(f"/api/jobs/{job['id']}/checkout",
                           json={"discount": 50}).json()
        assert body["sale"]["total"] == 500


class TestBoard:
    def test_board_reports_open_work(self, client, shop):
        _new_job(client, shop)
        board = client.get("/api/jobs/board").json()
        assert board["open_total"] >= 1
        assert all(j["status"] in ("queued", "in_progress", "ready")
                   for j in board["jobs"])

    def test_urgent_jobs_sort_first(self, client, shop):
        _new_job(client, shop, priority="urgent", customer_name="Urgent Rider")
        board = client.get("/api/jobs/board").json()
        assert board["jobs"][0]["priority"] == "urgent"

    def test_board_tracks_waiting_time(self, client, shop):
        board = client.get("/api/jobs/board").json()
        assert all(j["hours_open"] is not None for j in board["jobs"])

    def test_completed_jobs_leave_the_board(self, client, shop):
        job = _new_job(client, shop)
        client.post(f"/api/jobs/{job['id']}/checkout", json={})
        board = client.get("/api/jobs/board").json()
        assert job["id"] not in [j["id"] for j in board["jobs"]]

    def test_jobs_can_be_searched_by_plate(self, client, shop):
        _new_job(client, shop, plate_no="XYZ 9999")
        found = client.get("/api/jobs", params={"q": "XYZ 9999"}).json()["jobs"]
        assert found and found[0]["plate_no"] == "XYZ 9999"


class TestAddingACartToATicket:
    """The till pushes a whole basket onto a bike already in the shop.

    Parts and labour arrive together on one call, so a counter that has just
    rung up a chain kit and a fitting charge does not have to add them one at
    a time and hope nothing was missed.
    """

    def _bulk(self, client, job_id, lines):
        return client.post(f"/api/jobs/{job_id}/lines/bulk", json={"lines": lines})

    def test_a_cart_of_parts_and_labour_lands_in_one_call(self, client, shop):
        job = _new_job(client, shop, lines=[])
        res = self._bulk(client, job["id"], [
            {"product_id": shop["part_id"], "quantity": 2},
            {"product_id": shop["labour_id"], "quantity": 1},
        ])
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["line_count"] == 2
        assert body["parts_total"] == 400      # 2 x 200
        assert body["labour_total"] == 150

    def test_lines_are_added_to_what_is_already_there(self, client, shop):
        job = _new_job(client, shop)           # opens with 2 parts + 1 labour
        assert job["line_count"] == 2
        body = self._bulk(client, job["id"], [
            {"product_id": shop["part_id"], "quantity": 1},
        ]).json()
        assert body["line_count"] == 3, "the cart adds to the ticket, it does not replace it"

    def test_discounts_survive_the_trip(self, client, shop):
        job = _new_job(client, shop, lines=[])
        body = self._bulk(client, job["id"], [
            {"product_id": shop["part_id"], "quantity": 2, "discount": 50},
        ]).json()
        assert body["discount_total"] == 50
        assert body["total"] == 350

    def test_pushing_a_cart_does_not_move_stock(self, client, shop):
        """Stock still moves at checkout and nowhere else."""
        before = _stock(client, shop["part_id"])
        job = _new_job(client, shop, lines=[])
        self._bulk(client, job["id"], [{"product_id": shop["part_id"], "quantity": 3}])
        assert _stock(client, shop["part_id"]) == before

    def test_one_bad_line_rejects_the_whole_cart(self, client, shop):
        job = _new_job(client, shop, lines=[])
        res = self._bulk(client, job["id"], [
            {"product_id": shop["part_id"], "quantity": 1},
            {"product_id": 999999, "quantity": 1},
        ])
        assert res.status_code == 400
        after = client.get(f"/api/jobs/{job['id']}").json()
        assert after["line_count"] == 0, "half a cart on the ticket is worse than none"

    def test_an_empty_cart_is_refused(self, client, shop):
        job = _new_job(client, shop, lines=[])
        assert self._bulk(client, job["id"], []).status_code == 400

    def test_a_closed_ticket_takes_nothing(self, client, shop):
        job = _new_job(client, shop)
        client.post(f"/api/jobs/{job['id']}/checkout", json={})
        res = self._bulk(client, job["id"], [
            {"product_id": shop["part_id"], "quantity": 1},
        ])
        assert res.status_code == 409
        assert "completed" in res.json()["detail"]
