"""End-to-end checks that the forecasting actually produces useful shop advice."""
from datetime import date, timedelta

import pytest


@pytest.fixture(scope="module")
def trading(client, admin):
    """Simulate 60 days of trading with three deliberately different items."""
    sup = client.post("/api/suppliers", headers=admin,
                      json={"code": "ANASUP", "name": "Analytics Supplier",
                            "lead_time_days": 7, "order_cycle_days": 14}).json()["supplier"]
    cat = client.post("/api/categories", headers=admin,
                      json={"name": "ANATEST", "prefix": "ANA"}).json()["category"]

    def make(desc, cost, price, qty):
        return client.post("/api/items", headers=admin,
                           json={"description": desc, "category_id": cat["id"],
                                 "supplier_id": sup["id"], "unit_cost": cost,
                                 "retail_price": price, "stock_qty": qty,
                                 "reorder_point": 1}).json()["item"]

    # Runner: sells every day. Trickler: about twice a month. Shelf-warmer: never.
    runner = make("ANA FAST OIL", 250, 330, 400)
    trickler = make("ANA SLOW BEARING", 100, 180, 60)
    dead = make("ANA DEAD FAIRING", 900, 1400, 12)

    today = date.today()
    for offset in range(60, 0, -1):
        day = (today - timedelta(days=offset)).isoformat()
        lines = [{"line_type": "item", "item_id": runner["id"], "qty": 3}]
        if offset % 15 == 0:
            lines.append({"line_type": "item", "item_id": trickler["id"], "qty": 2})
        res = client.post("/api/pos/sales", headers=admin,
                          json={"lines": lines, "business_date": day})
        assert res.status_code == 200, res.text

    return {"runner": runner, "trickler": trickler, "dead": dead,
            "supplier": sup, "category": cat}


class TestMovers:
    def test_the_daily_seller_is_ranked_a_fast_mover(self, client, admin, trading):
        rows = client.get("/api/analytics/movers", headers=admin,
                          params={"direction": "fast", "days": 90, "limit": 500}
                          ).json()["items"]
        entry = next(r for r in rows if r["item_id"] == trading["runner"]["id"])
        assert entry["movement"] == "fast"
        # 3 a day for 60 days.
        assert entry["sold_qty"] == 180
        assert 2.0 < entry["daily_rate"] < 4.0

    def test_the_never_sold_item_shows_as_dead_stock(self, client, admin, trading):
        rows = client.get("/api/analytics/movers", headers=admin,
                          params={"direction": "dead", "days": 90, "limit": 500}
                          ).json()["items"]
        ids = [r["item_id"] for r in rows]
        assert trading["dead"]["id"] in ids

    def test_dead_stock_is_ranked_by_the_cash_it_ties_up(self, client, admin, trading):
        rows = client.get("/api/analytics/movers", headers=admin,
                          params={"direction": "dead", "days": 90, "limit": 500}
                          ).json()["items"]
        values = [r["stock_value"] for r in rows]
        assert values == sorted(values, reverse=True)

    def test_the_occasional_seller_is_not_called_fast(self, client, admin, trading):
        rows = client.get("/api/analytics/movers", headers=admin,
                          params={"direction": "fast", "days": 90, "limit": 500}
                          ).json()["items"]
        entry = next(r for r in rows if r["item_id"] == trading["trickler"]["id"])
        assert entry["movement"] in ("slow", "medium")


class TestForecastEndpoint:
    def test_forecast_scales_with_the_horizon(self, client, admin, trading):
        body = client.get(f"/api/analytics/items/{trading['runner']['id']}/forecast",
                          headers=admin, params={"days": 90}).json()
        f = body["forecast"]
        assert f["next_30d"] > f["next_7d"]
        assert abs(f["next_30d"] * 3 - f["next_90d"]) < 1.0

    def test_a_daily_seller_is_classified_as_smooth(self, client, admin, trading):
        body = client.get(f"/api/analytics/items/{trading['runner']['id']}/forecast",
                          headers=admin, params={"days": 90}).json()
        assert body["pattern"]["pattern"] in ("smooth", "erratic")

    def test_replenishment_plan_is_internally_consistent(self, client, admin, trading):
        plan = client.get(f"/api/analytics/items/{trading['runner']['id']}/forecast",
                          headers=admin, params={"days": 90}).json()["replenishment"]
        assert plan["reorder_point"] >= plan["safety_stock"]
        assert plan["economic_order_qty"] > 0
        assert plan["days_of_cover"] is not None

    def test_stockout_date_is_projected_for_a_moving_item(self, client, admin, trading):
        plan = client.get(f"/api/analytics/items/{trading['runner']['id']}/forecast",
                          headers=admin, params={"days": 90}).json()["replenishment"]
        assert plan["projected_stockout"] is not None
        assert plan["projected_stockout"] > date.today().isoformat()

    def test_weekly_history_is_returned_for_charting(self, client, admin, trading):
        body = client.get(f"/api/analytics/items/{trading['runner']['id']}/forecast",
                          headers=admin, params={"days": 90}).json()
        assert len(body["weekly_demand"]) > 1
        assert len(body["weekday_seasonality"]) == 7

    def test_unknown_item_is_reported_cleanly(self, client, admin):
        assert client.get("/api/analytics/items/999999/forecast",
                          headers=admin).status_code == 404


class TestReorderSuggestions:
    def test_a_fast_mover_running_low_is_suggested_first(self, client, admin, trading):
        item_id = trading["runner"]["id"]
        client.post("/api/inventory/stocktake", headers=admin,
                    json={"lines": [{"item_id": item_id, "counted_qty": 2}]})

        body = client.get("/api/analytics/reorder", headers=admin,
                          params={"days": 90}).json()
        entry = next(r for r in body["suggestions"] if r["item_id"] == item_id)

        assert entry["suggested_qty"] > 0
        assert entry["urgency"] > 0
        assert entry["reason"]
        assert entry["order_cost"] == round(entry["suggested_qty"] * entry["unit_cost"], 2)

    def test_suggestions_are_ordered_by_urgency(self, client, admin, trading):
        rows = client.get("/api/analytics/reorder", headers=admin,
                          params={"days": 90}).json()["suggestions"]
        scores = [r["urgency"] for r in rows]
        assert scores == sorted(scores, reverse=True)

    def test_suggested_quantity_covers_lead_time_demand(self, client, admin, trading):
        rows = client.get("/api/analytics/reorder", headers=admin,
                          params={"days": 90}).json()["suggestions"]
        entry = next(r for r in rows if r["item_id"] == trading["runner"]["id"])
        lead_demand = entry["daily_rate"] * entry["lead_time_days"]
        assert entry["suggested_qty"] >= lead_demand

    def test_a_well_stocked_dead_item_is_not_reordered(self, client, admin, trading):
        rows = client.get("/api/analytics/reorder", headers=admin,
                          params={"days": 90}).json()["suggestions"]
        ids = [r["item_id"] for r in rows]
        assert trading["dead"]["id"] not in ids

    def test_totals_are_grouped_by_supplier(self, client, admin, trading):
        body = client.get("/api/analytics/reorder", headers=admin,
                          params={"days": 90}).json()
        assert body["by_supplier"]
        assert abs(sum(b["cost"] for b in body["by_supplier"]) - body["total_cost"]) < 1.0

    def test_auto_draft_orders_are_created_per_supplier(self, client, admin, trading):
        res = client.post("/api/purchasing/orders/auto", headers=admin,
                          json={"supplier_id": trading["supplier"]["id"], "days": 90})
        assert res.status_code == 200
        body = res.json()
        assert body["created"] >= 1
        po = body["orders"][0]["po"]
        assert po["status"] == "draft"
        assert po["supplier_id"] == trading["supplier"]["id"]

        for order in body["orders"]:
            client.post(f"/api/purchasing/orders/{order['po']['id']}/cancel", headers=admin)


class TestAbcAnalysis:
    def test_the_top_earner_lands_in_class_a(self, client, admin, trading):
        rows = client.get("/api/analytics/abc", headers=admin,
                          params={"days": 90}).json()["items"]
        entry = next(r for r in rows if r["item_id"] == trading["runner"]["id"])
        assert entry["abc"] == "A"
        assert entry["abc_xyz"].startswith("A")

    def test_every_matrix_cell_carries_a_stocking_policy(self, client, admin, trading):
        matrix = client.get("/api/analytics/abc", headers=admin,
                            params={"days": 90}).json()["matrix"]
        assert matrix
        assert all(cell["policy"] for cell in matrix)


class TestOverview:
    def test_headline_numbers_are_present(self, client, admin, trading):
        body = client.get("/api/analytics/overview", headers=admin,
                          params={"days": 90}).json()
        assert body["sku_count"] > 0
        assert body["stock_value"] > 0
        assert set(body["movement"]) >= {"fast", "medium", "slow", "dead"}
        assert body["stock_turnover_annualised"] >= 0
        assert isinstance(body["urgent"], list)


class TestReports:
    def test_sales_summary_totals_match_the_periods(self, client, admin, trading):
        body = client.get("/api/reports/sales-summary", headers=admin,
                          params={"date_from": (date.today() - timedelta(days=90)).isoformat(),
                                  "group_by": "day"}).json()
        assert body["periods"]
        assert abs(sum(p["sales"] for p in body["periods"]) - body["totals"]["sales"]) < 0.01

    def test_profit_and_loss_reconciles(self, client, admin, trading):
        body = client.get("/api/reports/profit-and-loss", headers=admin,
                          params={"date_from": (date.today() - timedelta(days=90)).isoformat()}
                          ).json()
        assert (abs(body["gross_profit_on_parts"]
                    - (body["parts_sales"] - body["cost_of_goods_sold"])) < 0.01)
        assert (abs(body["total_gross_profit"]
                    - (body["gross_profit_on_parts"] + body["service_income"])) < 0.01)

    def test_dashboard_returns_stock_and_trend(self, client, admin, trading):
        body = client.get("/api/reports/dashboard", headers=admin).json()
        assert body["stock"]["skus"] > 0
        assert "trend" in body

    def test_top_items_ranks_the_runner_first_by_quantity(self, client, admin, trading):
        rows = client.get("/api/reports/top-items", headers=admin,
                          params={"by": "qty", "limit": 5,
                                  "date_from": (date.today() - timedelta(days=90)).isoformat()}
                          ).json()["items"]
        assert rows[0]["item_id"] == trading["runner"]["id"]

    def test_csv_export_downloads(self, client, admin, trading):
        for dataset in ("inventory", "sales", "reorder", "movers"):
            res = client.get(f"/api/reports/export/{dataset}", headers=admin)
            assert res.status_code == 200, dataset
            assert "text/csv" in res.headers["content-type"]
            assert len(res.text.splitlines()) >= 1

    def test_unknown_export_is_rejected(self, client, admin):
        assert client.get("/api/reports/export/nonsense", headers=admin).status_code == 404

    def test_financial_reports_are_closed_to_cashiers(self, client, admin):
        client.post("/api/auth/users", headers=admin,
                    json={"username": "anatill", "password": "AnaTill123", "role": "cashier"})
        login = client.post("/api/auth/login",
                            json={"username": "anatill", "password": "AnaTill123"})
        headers = {"Authorization": f"Bearer {login.json()['token']}"}
        assert client.get("/api/reports/profit-and-loss", headers=headers).status_code == 403
        assert client.get("/api/reports/dashboard", headers=headers).status_code == 200


class TestSeasonalityAlignment:
    def test_weekday_labels_match_the_measured_window(self, client, admin, trading):
        """Trimming the lead-in must not shift the weekday the demand is credited to."""
        from datetime import datetime

        body = client.get(f"/api/analytics/items/{trading['runner']['id']}/forecast",
                          headers=admin, params={"days": 90}).json()
        measured = datetime.fromisoformat(body["window"]["measured_from"]).date()
        assert body["weekly_demand"][0]["week_of"] == measured.isoformat()

        names = [s["day"] for s in body["weekday_seasonality"]]
        assert names == ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


class TestColdStart:
    def test_imported_history_is_not_written_off_as_dead(self, client, admin):
        """A line whose only evidence is the workbook must still be graded on it."""
        from backend.app import db

        sup = client.post("/api/suppliers", headers=admin,
                          json={"code": "COLDSUP", "lead_time_days": 7}).json()["supplier"]
        item = client.post("/api/items", headers=admin,
                           json={"description": "COLD START CLUTCH", "supplier_id": sup["id"],
                                 "unit_cost": 200, "retail_price": 300,
                                 "stock_qty": 3}).json()["item"]
        # 30 units in one month: a clear fast mover, but no till data at all.
        db.execute(
            "INSERT INTO demand_history(item_id, period, qty, revenue, source) "
            "VALUES(?, '2025-04', 30, 9000, 'workbook')",
            (item["id"],),
        )

        rows = client.get("/api/analytics/movers", headers=admin,
                          params={"direction": "fast", "days": 90, "limit": 500}
                          ).json()["items"]
        entry = next((r for r in rows if r["item_id"] == item["id"]), None)
        assert entry is not None, "history-only items must still be analysed"
        assert entry["movement_basis"] == "history"
        assert entry["movement"] == "fast"

    def test_overview_separates_evidence_sources(self, client, admin, trading):
        body = client.get("/api/analytics/overview", headers=admin,
                          params={"days": 90}).json()
        ev = body["evidence"]
        assert ev["from_imported_history"] >= 1
        assert ev["from_till"] >= 1
        assert sum(ev.values()) == body["sku_count"]


class TestAbcAtColdStart:
    def test_history_only_items_are_ranked_by_value(self, client, admin):
        """ABC must work before the till has recorded anything."""
        from backend.app import db

        sup = client.post("/api/suppliers", headers=admin,
                          json={"code": "ABCSUP", "lead_time_days": 7}).json()["supplier"]
        big = client.post("/api/items", headers=admin,
                          json={"description": "ABC BIG TICKET TYRE", "supplier_id": sup["id"],
                                "unit_cost": 900, "retail_price": 1300,
                                "stock_qty": 20}).json()["item"]
        db.execute(
            "INSERT INTO demand_history(item_id, period, qty, revenue, source) "
            "VALUES(?, '2025-04', 120, 156000, 'workbook')",
            (big["id"],),
        )
        rows = client.get("/api/analytics/abc", headers=admin,
                          params={"days": 90}).json()["items"]
        entry = next(r for r in rows if r["item_id"] == big["id"])
        assert entry["demand_value"] > 0
        assert entry["abc"] == "A"


class TestMinimumObservationWindow:
    def test_one_recent_sale_does_not_imply_daily_demand(self, client, admin):
        """A single sale today must not be extrapolated to one a day."""
        sup = client.post("/api/suppliers", headers=admin,
                          json={"code": "ONESUP", "lead_time_days": 7}).json()["supplier"]
        item = client.post("/api/items", headers=admin,
                           json={"description": "ONE SALE ONLY GASKET",
                                 "supplier_id": sup["id"], "unit_cost": 50,
                                 "retail_price": 90, "stock_qty": 10}).json()["item"]
        client.post("/api/pos/sales", headers=admin,
                    json={"lines": [{"line_type": "item", "item_id": item["id"], "qty": 1}]})

        body = client.get(f"/api/analytics/items/{item['id']}/forecast",
                          headers=admin, params={"days": 90}).json()
        # One unit observed over at least 28 days is at most ~1.1 a month.
        assert body["forecast"]["next_30d"] <= 1.5, body["forecast"]
        assert body["daily_rate"] <= 1 / 28 + 1e-6

    def test_a_single_sale_does_not_trigger_a_huge_order(self, client, admin):
        rows = client.get("/api/analytics/reorder", headers=admin,
                          params={"days": 90, "only_needed": False}).json()["suggestions"]
        entry = next((r for r in rows
                      if r["description"] == "ONE SALE ONLY GASKET"), None)
        assert entry is not None
        assert entry["suggested_qty"] < 50, entry
