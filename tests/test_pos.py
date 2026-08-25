"""Selling, stock movement, voids, discounts and the cash drawer."""
import pytest


@pytest.fixture(scope="module")
def shop(client, admin):
    """A supplier, a category, two stocked parts and one service."""
    cat = client.post("/api/categories", headers=admin,
                      json={"name": "TESTOIL", "prefix": "TOIL"}).json()["category"]
    sup = client.post("/api/suppliers", headers=admin,
                      json={"code": "TESTSUP", "name": "Test Supplier",
                            "lead_time_days": 7, "order_cycle_days": 14}).json()["supplier"]

    def make(desc, cost, price, qty, rop=2):
        return client.post("/api/items", headers=admin,
                           json={"description": desc, "category_id": cat["id"],
                                 "supplier_id": sup["id"], "unit_cost": cost,
                                 "retail_price": price, "stock_qty": qty,
                                 "reorder_point": rop}).json()["item"]

    svc = client.post("/api/services", headers=admin,
                      json={"name": "TEST CHANGE OIL", "fee": 70}).json()["service"]

    client.post("/api/auth/users", headers=admin,
                json={"username": "postill", "full_name": "Till Operator",
                      "password": "TillUser123", "role": "cashier"})

    return {"category": cat, "supplier": sup, "service": svc,
            "oil": make("TEST OIL 1L", 250, 330, 20),
            "plug": make("TEST SPARK PLUG", 60, 100, 5)}


def test_sku_follows_the_shops_prefix_convention(shop):
    assert shop["oil"]["sku"].startswith("TOIL")


def test_sale_decrements_stock_and_records_profit(client, admin, shop):
    before = client.get(f"/api/items/{shop['oil']['id']}",
                        headers=admin).json()["item"]["stock_qty"]

    res = client.post("/api/pos/sales", headers=admin, json={
        "lines": [
            {"line_type": "item", "item_id": shop["oil"]["id"], "qty": 2},
            {"line_type": "service", "service_id": shop["service"]["id"], "qty": 1},
        ],
        "amount_tendered": 1000,
        "customer_name": "Juan Dela Cruz",
    })
    assert res.status_code == 200, res.text
    sale = res.json()["sale"]

    # 2 x 330 parts + 70 labour = 730; cost 2 x 250 = 500; profit 230.
    assert sale["total"] == 730
    assert sale["parts_total"] == 660
    assert sale["labor_total"] == 70
    assert sale["cost_total"] == 500
    assert sale["profit"] == 230
    assert sale["change_due"] == 270

    after = client.get(f"/api/items/{shop['oil']['id']}",
                       headers=admin).json()["item"]["stock_qty"]
    assert after == before - 2


def test_sale_writes_a_stock_ledger_entry(client, admin, shop):
    moves = client.get("/api/inventory/moves", headers=admin,
                       params={"item_id": shop["oil"]["id"], "move_type": "sale"}).json()["moves"]
    assert moves, "a sale must leave an audit trail in the stock ledger"
    assert moves[0]["qty_delta"] == -2


def test_overselling_is_blocked_with_a_useful_message(client, admin, shop):
    res = client.post("/api/pos/sales", headers=admin, json={
        "lines": [{"line_type": "item", "item_id": shop["plug"]["id"], "qty": 999}],
    })
    assert res.status_code == 409
    assert "Only 5 left" in res.json()["detail"]


def test_failed_sale_leaves_stock_untouched(client, admin, shop):
    """A part-valid basket must roll back completely, not half-sell."""
    before = client.get(f"/api/items/{shop['oil']['id']}",
                        headers=admin).json()["item"]["stock_qty"]

    res = client.post("/api/pos/sales", headers=admin, json={
        "lines": [
            {"line_type": "item", "item_id": shop["oil"]["id"], "qty": 1},
            {"line_type": "item", "item_id": shop["plug"]["id"], "qty": 999},
        ],
    })
    assert res.status_code == 409

    after = client.get(f"/api/items/{shop['oil']['id']}",
                       headers=admin).json()["item"]["stock_qty"]
    assert after == before, "the good line must not have been committed"


def test_empty_basket_is_refused(client, admin):
    res = client.post("/api/pos/sales", headers=admin, json={"lines": []})
    assert res.status_code == 400


def test_underpayment_is_refused(client, admin, shop):
    res = client.post("/api/pos/sales", headers=admin, json={
        "lines": [{"line_type": "item", "item_id": shop["plug"]["id"], "qty": 1}],
        "payments": [{"method": "CASH", "amount": 10}],
    })
    assert res.status_code == 400
    assert "but the sale is" in res.json()["detail"]


def test_unknown_payment_method_is_refused(client, admin, shop):
    res = client.post("/api/pos/sales", headers=admin, json={
        "lines": [{"line_type": "item", "item_id": shop["plug"]["id"], "qty": 1}],
        "payments": [{"method": "CRYPTO", "amount": 100}],
    })
    assert res.status_code == 400


def test_split_payment_is_accepted(client, admin, shop):
    res = client.post("/api/pos/sales", headers=admin, json={
        "lines": [{"line_type": "item", "item_id": shop["oil"]["id"], "qty": 1}],
        "payments": [{"method": "CASH", "amount": 130},
                     {"method": "GCASH", "amount": 200, "reference": "GC-99"}],
        "amount_tendered": 330,
    })
    assert res.status_code == 200
    assert len(res.json()["payments"]) == 2


def test_cashier_cannot_discount(client, shop):
    login = client.post("/api/auth/login",
                        json={"username": "postill", "password": "TillUser123"})
    headers = {"Authorization": f"Bearer {login.json()['token']}"}
    res = client.post("/api/pos/sales", headers=headers, json={
        "lines": [{"line_type": "item", "item_id": shop["plug"]["id"], "qty": 1}],
        "order_discount": 50,
    })
    assert res.status_code == 403
    assert "cannot apply discounts" in res.json()["detail"]


def test_void_returns_stock_and_requires_a_reason(client, admin, shop):
    sale = client.post("/api/pos/sales", headers=admin, json={
        "lines": [{"line_type": "item", "item_id": shop["plug"]["id"], "qty": 2}],
        "amount_tendered": 200,
    }).json()["sale"]

    after_sale = client.get(f"/api/items/{shop['plug']['id']}",
                            headers=admin).json()["item"]["stock_qty"]

    assert client.post(f"/api/pos/sales/{sale['id']}/void", headers=admin,
                       json={"reason": "no"}).status_code == 422

    res = client.post(f"/api/pos/sales/{sale['id']}/void", headers=admin,
                      json={"reason": "Customer changed their mind"})
    assert res.status_code == 200
    assert res.json()["sale"]["status"] == "voided"

    restored = client.get(f"/api/items/{shop['plug']['id']}",
                          headers=admin).json()["item"]["stock_qty"]
    assert restored == after_sale + 2


def test_a_sale_cannot_be_voided_twice(client, admin, shop):
    sale = client.post("/api/pos/sales", headers=admin, json={
        "lines": [{"line_type": "item", "item_id": shop["plug"]["id"], "qty": 1}],
    }).json()["sale"]
    client.post(f"/api/pos/sales/{sale['id']}/void", headers=admin,
                json={"reason": "First void"})
    res = client.post(f"/api/pos/sales/{sale['id']}/void", headers=admin,
                      json={"reason": "Second void"})
    assert res.status_code == 400
    assert "already voided" in res.json()["detail"]


def test_receipt_numbers_are_sequential_per_day(client, admin, shop):
    a = client.post("/api/pos/sales", headers=admin, json={
        "lines": [{"line_type": "service", "service_id": shop["service"]["id"], "qty": 1}],
    }).json()["sale"]["receipt_no"]
    b = client.post("/api/pos/sales", headers=admin, json={
        "lines": [{"line_type": "service", "service_id": shop["service"]["id"], "qty": 1}],
    }).json()["sale"]["receipt_no"]

    date_a, seq_a = a.split("-")
    date_b, seq_b = b.split("-")
    assert date_a == date_b
    assert int(seq_b) == int(seq_a) + 1


def test_cash_drawer_reconciles(client, admin):
    client.post("/api/pos/drawer/open", headers=admin, json={"opening_cash": 1000})
    drawer = client.get("/api/pos/drawer", headers=admin).json()["drawer"]
    assert drawer is not None
    assert drawer["opening_cash"] == 1000

    # Opening a second session while one is live must be refused.
    assert client.post("/api/pos/drawer/open", headers=admin,
                       json={"opening_cash": 500}).status_code == 409

    expected = drawer["expected_cash"]
    res = client.post("/api/pos/drawer/close", headers=admin,
                      json={"counted_cash": expected - 50})
    assert res.status_code == 200
    assert res.json()["variance"] == -50
    assert res.json()["status"] == "short"
