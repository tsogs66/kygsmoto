"""Stock adjustments, stocktakes, purchase orders and reorder advice."""
import pytest


@pytest.fixture(scope="module")
def stock(client, admin):
    sup = client.post("/api/suppliers", headers=admin,
                      json={"code": "INVSUP", "name": "Inventory Supplier",
                            "lead_time_days": 10, "order_cycle_days": 14}).json()["supplier"]
    cat = client.post("/api/categories", headers=admin,
                      json={"name": "INVTEST", "prefix": "INV"}).json()["category"]
    item = client.post("/api/items", headers=admin,
                       json={"description": "INV TEST CHAIN", "category_id": cat["id"],
                             "supplier_id": sup["id"], "unit_cost": 300,
                             "retail_price": 450, "stock_qty": 10,
                             "reorder_point": 4}).json()["item"]
    return {"supplier": sup, "category": cat, "item": item}


def _qty(client, admin, item_id):
    return client.get(f"/api/items/{item_id}", headers=admin).json()["item"]["stock_qty"]


class TestAdjustments:
    def test_positive_adjustment_adds_stock(self, client, admin, stock):
        before = _qty(client, admin, stock["item"]["id"])
        res = client.post("/api/inventory/adjust", headers=admin,
                          json={"item_id": stock["item"]["id"], "qty_delta": 5,
                                "reason": "found", "note": "Found in back room"})
        assert res.status_code == 200
        assert res.json()["balance"] == before + 5

    def test_negative_adjustment_removes_stock(self, client, admin, stock):
        before = _qty(client, admin, stock["item"]["id"])
        client.post("/api/inventory/adjust", headers=admin,
                    json={"item_id": stock["item"]["id"], "qty_delta": -3,
                          "reason": "damaged"})
        assert _qty(client, admin, stock["item"]["id"]) == before - 3

    def test_adjustment_cannot_drive_stock_negative(self, client, admin, stock):
        before = _qty(client, admin, stock["item"]["id"])
        res = client.post("/api/inventory/adjust", headers=admin,
                          json={"item_id": stock["item"]["id"], "qty_delta": -9999,
                                "reason": "lost"})
        assert res.status_code == 409
        assert _qty(client, admin, stock["item"]["id"]) == before, "must roll back"

    def test_reason_must_be_recognised(self, client, admin, stock):
        res = client.post("/api/inventory/adjust", headers=admin,
                          json={"item_id": stock["item"]["id"], "qty_delta": 1,
                                "reason": "because"})
        assert res.status_code == 400

    def test_zero_adjustment_is_refused(self, client, admin, stock):
        res = client.post("/api/inventory/adjust", headers=admin,
                          json={"item_id": stock["item"]["id"], "qty_delta": 0,
                                "reason": "correction"})
        assert res.status_code == 400


class TestStocktake:
    def test_variance_is_reported_and_applied(self, client, admin, stock):
        current = _qty(client, admin, stock["item"]["id"])
        res = client.post("/api/inventory/stocktake", headers=admin,
                          json={"lines": [{"item_id": stock["item"]["id"],
                                           "counted_qty": current - 2}],
                                "note": "Monthly count"})
        assert res.status_code == 200
        body = res.json()
        assert body["variances"][0]["variance"] == -2
        assert body["variances"][0]["value_impact"] == -600  # 2 x 300 cost
        assert _qty(client, admin, stock["item"]["id"]) == current - 2

    def test_matching_count_produces_no_variance(self, client, admin, stock):
        current = _qty(client, admin, stock["item"]["id"])
        res = client.post("/api/inventory/stocktake", headers=admin,
                          json={"lines": [{"item_id": stock["item"]["id"],
                                           "counted_qty": current}]})
        assert res.json()["variances"] == []


class TestLowStock:
    def test_items_at_or_below_reorder_point_are_flagged(self, client, admin, stock):
        item_id = stock["item"]["id"]
        current = _qty(client, admin, item_id)
        client.post("/api/inventory/stocktake", headers=admin,
                    json={"lines": [{"item_id": item_id, "counted_qty": 1}]})

        flagged = client.get("/api/inventory/low-stock", headers=admin).json()["items"]
        entry = next((i for i in flagged if i["id"] == item_id), None)
        assert entry is not None
        assert entry["status"] == "CRITICAL"
        assert entry["shortfall"] == 3  # reorder point 4, on hand 1

        client.post("/api/inventory/stocktake", headers=admin,
                    json={"lines": [{"item_id": item_id, "counted_qty": current}]})

    def test_out_of_stock_gets_its_own_status(self, client, admin, stock):
        item_id = stock["item"]["id"]
        current = _qty(client, admin, item_id)
        client.post("/api/inventory/stocktake", headers=admin,
                    json={"lines": [{"item_id": item_id, "counted_qty": 0}]})

        flagged = client.get("/api/inventory/low-stock", headers=admin).json()["items"]
        entry = next(i for i in flagged if i["id"] == item_id)
        assert entry["status"] == "OUT OF STOCK"

        client.post("/api/inventory/stocktake", headers=admin,
                    json={"lines": [{"item_id": item_id, "counted_qty": current}]})


class TestPurchaseOrders:
    def test_full_order_lifecycle(self, client, admin, stock):
        item_id = stock["item"]["id"]
        before = _qty(client, admin, item_id)

        po = client.post("/api/purchasing/orders", headers=admin, json={
            "supplier_id": stock["supplier"]["id"],
            "lines": [{"item_id": item_id, "qty_ordered": 20, "unit_cost": 310}],
        }).json()
        assert po["po"]["status"] == "draft"
        assert po["po"]["total_cost"] == 6200

        sent = client.post(f"/api/purchasing/orders/{po['po']['id']}/send",
                           headers=admin).json()
        assert sent["po"]["status"] == "ordered"
        assert sent["po"]["expected_at"], "an expected date is derived from lead time"

        # Deliver 8 of 20 first.
        line_id = po["lines"][0]["id"]
        partial = client.post(f"/api/purchasing/orders/{po['po']['id']}/receive",
                              headers=admin,
                              json={"lines": [{"po_line_id": line_id,
                                               "qty_received": 8}]}).json()
        assert partial["po"]["status"] == "partial"
        assert _qty(client, admin, item_id) == before + 8

        # Over-receiving the remainder is refused.
        too_many = client.post(f"/api/purchasing/orders/{po['po']['id']}/receive",
                               headers=admin,
                               json={"lines": [{"po_line_id": line_id, "qty_received": 99}]})
        assert too_many.status_code == 400
        assert "Only 12 outstanding" in too_many.json()["detail"]

        done = client.post(f"/api/purchasing/orders/{po['po']['id']}/receive",
                           headers=admin,
                           json={"lines": [{"po_line_id": line_id,
                                            "qty_received": 12}]}).json()
        assert done["po"]["status"] == "received"
        assert _qty(client, admin, item_id) == before + 20

    def test_receiving_updates_the_valuation_cost(self, client, admin, stock):
        item = client.get(f"/api/items/{stock['item']['id']}",
                          headers=admin).json()["item"]
        assert item["unit_cost"] == 310, "latest landed cost becomes the new cost"

    def test_order_needs_at_least_one_line(self, client, admin, stock):
        res = client.post("/api/purchasing/orders", headers=admin,
                          json={"supplier_id": stock["supplier"]["id"], "lines": []})
        assert res.status_code == 400

    def test_received_order_cannot_be_cancelled(self, client, admin, stock):
        po = client.post("/api/purchasing/orders", headers=admin, json={
            "supplier_id": stock["supplier"]["id"],
            "lines": [{"item_id": stock["item"]["id"], "qty_ordered": 1}],
        }).json()
        client.post(f"/api/purchasing/orders/{po['po']['id']}/send", headers=admin)
        client.post(f"/api/purchasing/orders/{po['po']['id']}/receive", headers=admin,
                    json={"lines": [{"po_line_id": po["lines"][0]["id"],
                                     "qty_received": 1}]})
        res = client.post(f"/api/purchasing/orders/{po['po']['id']}/cancel", headers=admin)
        assert res.status_code == 400

    def test_open_orders_count_as_incoming_stock(self, client, admin, stock):
        """An outstanding PO must suppress a duplicate reorder suggestion."""
        po = client.post("/api/purchasing/orders", headers=admin, json={
            "supplier_id": stock["supplier"]["id"],
            "lines": [{"item_id": stock["item"]["id"], "qty_ordered": 500}],
        }).json()
        client.post(f"/api/purchasing/orders/{po['po']['id']}/send", headers=admin)

        rows = client.get("/api/analytics/reorder", headers=admin,
                          params={"only_needed": False}).json()["suggestions"]
        entry = next((r for r in rows if r["item_id"] == stock["item"]["id"]), None)
        assert entry is not None
        assert entry["on_order"] == 500

        client.post(f"/api/purchasing/orders/{po['po']['id']}/cancel", headers=admin)
