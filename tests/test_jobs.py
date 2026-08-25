"""Job queue: ticket lifecycle, stock timing and the pending-work board."""
import pytest


@pytest.fixture(scope="module")
def shop(client, admin):
    cat = client.post("/api/categories", headers=admin,
                      json={"name": "JOBTEST", "prefix": "JOB"}).json()["category"]
    sup = client.post("/api/suppliers", headers=admin,
                      json={"code": "JOBSUP"}).json()["supplier"]
    part = client.post("/api/items", headers=admin,
                       json={"description": "JOB TEST BRAKE PAD", "category_id": cat["id"],
                             "supplier_id": sup["id"], "unit_cost": 120,
                             "retail_price": 200, "stock_qty": 10}).json()["item"]
    svc = client.post("/api/services", headers=admin,
                      json={"name": "JOB TEST BRAKE JOB", "fee": 150}).json()["service"]
    return {"part": part, "service": svc}


def _stock(client, admin, item_id):
    return client.get(f"/api/items/{item_id}", headers=admin).json()["item"]["stock_qty"]


def _new_job(client, admin, shop, **kw):
    payload = {
        "customer_name": "Pedro Santos", "plate_no": "abc 1234",
        "motorcycle": "Mio i125", "complaint": "Front brake squealing",
        "lines": [
            {"line_type": "item", "item_id": shop["part"]["id"], "qty": 2},
            {"line_type": "service", "service_id": shop["service"]["id"], "qty": 1},
        ],
    }
    payload.update(kw)
    res = client.post("/api/pos/jobs", headers=admin, json=payload)
    assert res.status_code == 200, res.text
    return res.json()


class TestCreation:
    def test_job_opens_with_parts_and_labour(self, client, admin, shop):
        body = _new_job(client, admin, shop)
        assert body["job"]["status"] == "queued"
        assert body["job"]["job_no"].startswith("JOB")
        assert body["job"]["plate_no"] == "ABC 1234", "plates are normalised to upper case"
        # 2 x 200 parts + 150 labour
        assert body["totals"]["parts"] == 400
        assert body["totals"]["labour"] == 150
        assert body["totals"]["total"] == 550

    def test_opening_a_job_does_not_move_stock(self, client, admin, shop):
        """A queued job must not hold stock the counter could still sell."""
        before = _stock(client, admin, shop["part"]["id"])
        _new_job(client, admin, shop)
        assert _stock(client, admin, shop["part"]["id"]) == before

    def test_job_numbers_are_sequential(self, client, admin, shop):
        a = _new_job(client, admin, shop)["job"]["job_no"]
        b = _new_job(client, admin, shop)["job"]["job_no"]
        assert int(b.split("-")[1]) == int(a.split("-")[1]) + 1

    def test_a_job_can_start_empty(self, client, admin, shop):
        body = _new_job(client, admin, shop, lines=[])
        assert body["totals"]["total"] == 0

    def test_bad_priority_is_refused(self, client, admin, shop):
        res = client.post("/api/pos/jobs", headers=admin,
                          json={"priority": "screaming", "lines": []})
        assert res.status_code == 400


class TestWorkflow:
    def test_status_moves_forward_and_stamps_times(self, client, admin, shop):
        job = _new_job(client, admin, shop)["job"]

        started = client.patch(f"/api/pos/jobs/{job['id']}", headers=admin,
                               json={"status": "in_progress"}).json()["job"]
        assert started["status"] == "in_progress"
        assert started["started_at"], "starting work should stamp the time"

        ready = client.patch(f"/api/pos/jobs/{job['id']}", headers=admin,
                             json={"status": "ready"}).json()["job"]
        assert ready["status"] == "ready"
        assert ready["ready_at"]

    def test_completed_cannot_be_set_by_hand(self, client, admin, shop):
        """Finishing must go through payment, or the sale would never be recorded."""
        job = _new_job(client, admin, shop)["job"]
        res = client.patch(f"/api/pos/jobs/{job['id']}", headers=admin,
                           json={"status": "completed"})
        assert res.status_code == 400
        assert "taking payment" in res.json()["detail"]

    def test_cancelled_job_is_frozen(self, client, admin, shop):
        job = _new_job(client, admin, shop)["job"]
        client.post(f"/api/pos/jobs/{job['id']}/cancel", headers=admin,
                    json={"reason": "Customer took the bike home"})

        assert client.patch(f"/api/pos/jobs/{job['id']}", headers=admin,
                            json={"status": "in_progress"}).status_code == 409
        assert client.post(f"/api/pos/jobs/{job['id']}/lines", headers=admin,
                           json={"line_type": "service",
                                 "service_id": shop["service"]["id"],
                                 "qty": 1}).status_code == 409

    def test_cancelling_needs_a_reason(self, client, admin, shop):
        job = _new_job(client, admin, shop)["job"]
        assert client.post(f"/api/pos/jobs/{job['id']}/cancel", headers=admin,
                           json={"reason": "no"}).status_code == 422

    def test_lines_can_be_added_and_removed_while_open(self, client, admin, shop):
        body = _new_job(client, admin, shop)
        job_id = body["job"]["id"]

        grown = client.post(f"/api/pos/jobs/{job_id}/lines", headers=admin,
                            json={"line_type": "service",
                                  "service_id": shop["service"]["id"],
                                  "qty": 1}).json()
        assert grown["totals"]["labour"] == 300

        line_id = grown["lines"][-1]["id"]
        shrunk = client.delete(f"/api/pos/jobs/{job_id}/lines/{line_id}",
                               headers=admin).json()
        assert shrunk["totals"]["labour"] == 150


class TestShortages:
    def test_a_line_beyond_stock_is_flagged(self, client, admin, shop):
        """The counter should see a shortage before it reaches payment."""
        body = _new_job(client, admin, shop, lines=[
            {"line_type": "item", "item_id": shop["part"]["id"], "qty": 999},
        ])
        assert body["totals"]["short_lines"] == 1
        assert body["lines"][0]["short"] is True

    def test_an_available_line_is_not_flagged(self, client, admin, shop):
        body = _new_job(client, admin, shop)
        assert body["totals"]["short_lines"] == 0


class TestCheckout:
    def test_checkout_creates_a_sale_and_moves_stock_then(self, client, admin, shop):
        before = _stock(client, admin, shop["part"]["id"])
        job = _new_job(client, admin, shop)["job"]

        res = client.post(f"/api/pos/jobs/{job['id']}/checkout", headers=admin,
                          json={"amount_tendered": 1000})
        assert res.status_code == 200, res.text
        body = res.json()

        assert body["sale"]["total"] == 550
        assert body["sale"]["parts_total"] == 400
        assert body["sale"]["labor_total"] == 150
        assert body["sale"]["cost_total"] == 240      # 2 x 120
        assert body["sale"]["profit"] == 310
        assert body["sale"]["change_due"] == 450
        assert body["sale"]["plate_no"] == "ABC 1234"

        assert _stock(client, admin, shop["part"]["id"]) == before - 2, \
            "stock moves at checkout"
        assert body["job"]["status"] == "completed"
        assert body["job"]["sale_id"] == body["sale"]["id"]

    def test_a_completed_job_cannot_be_charged_twice(self, client, admin, shop):
        job = _new_job(client, admin, shop)["job"]
        client.post(f"/api/pos/jobs/{job['id']}/checkout", headers=admin,
                    json={"amount_tendered": 1000})
        again = client.post(f"/api/pos/jobs/{job['id']}/checkout", headers=admin,
                            json={"amount_tendered": 1000})
        assert again.status_code == 400
        assert "already completed" in again.json()["detail"]

    def test_an_empty_job_cannot_be_charged(self, client, admin, shop):
        job = _new_job(client, admin, shop, lines=[])["job"]
        res = client.post(f"/api/pos/jobs/{job['id']}/checkout", headers=admin,
                          json={"amount_tendered": 100})
        assert res.status_code == 400

    def test_checkout_beyond_stock_is_blocked_and_job_stays_open(self, client, admin, shop):
        job = _new_job(client, admin, shop, lines=[
            {"line_type": "item", "item_id": shop["part"]["id"], "qty": 999},
        ])["job"]

        res = client.post(f"/api/pos/jobs/{job['id']}/checkout", headers=admin,
                          json={"amount_tendered": 99999})
        assert res.status_code == 409

        still = client.get(f"/api/pos/jobs/{job['id']}", headers=admin).json()["job"]
        assert still["status"] in ("queued", "in_progress", "ready"), \
            "a failed checkout must leave the job workable"
        assert still["sale_id"] is None

    def test_receipt_records_the_job_number(self, client, admin, shop):
        job = _new_job(client, admin, shop)["job"]
        body = client.post(f"/api/pos/jobs/{job['id']}/checkout", headers=admin,
                           json={"amount_tendered": 1000}).json()
        assert job["job_no"] in body["sale"]["note"]


class TestBoard:
    def test_board_reports_open_work(self, client, admin, shop):
        board = client.get("/api/pos/jobs/board", headers=admin).json()
        assert board["open_total"] >= 1
        assert board["open_value"] >= 0
        assert all(j["status"] in ("queued", "in_progress", "ready") for j in board["jobs"])

    def test_urgent_jobs_sort_first(self, client, admin, shop):
        _new_job(client, admin, shop, priority="urgent", customer_name="Urgent Rider")
        board = client.get("/api/pos/jobs/board", headers=admin).json()
        assert board["jobs"][0]["priority"] == "urgent"

    def test_board_tracks_how_long_work_has_waited(self, client, admin, shop):
        board = client.get("/api/pos/jobs/board", headers=admin).json()
        assert all(j["hours_open"] is not None for j in board["jobs"])

    def test_completed_jobs_leave_the_board(self, client, admin, shop):
        job = _new_job(client, admin, shop)["job"]
        client.post(f"/api/pos/jobs/{job['id']}/checkout", headers=admin,
                    json={"amount_tendered": 1000})
        board = client.get("/api/pos/jobs/board", headers=admin).json()
        assert job["id"] not in [j["id"] for j in board["jobs"]]

    def test_jobs_can_be_searched_by_plate(self, client, admin, shop):
        _new_job(client, admin, shop, plate_no="XYZ 9999")
        found = client.get("/api/pos/jobs", headers=admin,
                           params={"q": "XYZ 9999"}).json()["jobs"]
        assert found and found[0]["plate_no"] == "XYZ 9999"


class TestPermissions:
    def test_a_cashier_can_run_the_queue(self, client, admin, shop):
        client.post("/api/auth/users", headers=admin,
                    json={"username": "jobtill", "password": "JobTill123", "role": "cashier"})
        login = client.post("/api/auth/login",
                            json={"username": "jobtill", "password": "JobTill123"})
        headers = {"Authorization": f"Bearer {login.json()['token']}"}

        assert client.get("/api/pos/jobs/board", headers=headers).status_code == 200
        created = client.post("/api/pos/jobs", headers=headers,
                              json={"customer_name": "Walk-in", "lines": []})
        assert created.status_code == 200

    def test_a_cashier_cannot_discount_a_job_line(self, client, admin, shop):
        login = client.post("/api/auth/login",
                            json={"username": "jobtill", "password": "JobTill123"})
        headers = {"Authorization": f"Bearer {login.json()['token']}"}
        job = client.post("/api/pos/jobs", headers=headers,
                          json={"lines": []}).json()["job"]

        res = client.post(f"/api/pos/jobs/{job['id']}/lines", headers=headers,
                          json={"line_type": "service", "service_id": shop["service"]["id"],
                                "qty": 1, "discount": 50})
        assert res.status_code == 403
