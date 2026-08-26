"""Stock intelligence: forecasting, movers, ABC and reorder advice."""
from datetime import datetime, timedelta
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import Base, SessionLocal, engine
from app.main import app
from app.models.models import Category, Product, Sale, SaleItem, Supplier
from app.services import forecast as fc


@pytest.fixture(scope="module")
def client():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def trading(client):
    """60 days of trading with three deliberately different products."""
    db = SessionLocal()
    try:
        cat = Category(name="Analytics Test")
        sup = Supplier(name="Analytics Supplier", lead_time_days=7, order_cycle_days=14)
        db.add_all([cat, sup])
        db.flush()

        runner = Product(sku="ANA-FAST", name="ANA Fast Oil", category_id=cat.id,
                         supplier_id=sup.id, cost_price=250, sell_price=330,
                         stock_qty=400, reorder_level=1)
        trickler = Product(sku="ANA-SLOW", name="ANA Slow Bearing", category_id=cat.id,
                           supplier_id=sup.id, cost_price=100, sell_price=180,
                           stock_qty=60, reorder_level=1)
        dead = Product(sku="ANA-DEAD", name="ANA Dead Fairing", category_id=cat.id,
                       supplier_id=sup.id, cost_price=900, sell_price=1400,
                       stock_qty=12, reorder_level=1)
        db.add_all([runner, trickler, dead])
        db.flush()

        # Back-date creation so the shelf-life trim does not clip the window.
        old = datetime.utcnow() - timedelta(days=120)
        for product in (runner, trickler, dead):
            product.created_at = old

        # Runner sells every day; trickler about twice a month; dead never.
        for offset in range(60, 0, -1):
            when = datetime.utcnow() - timedelta(days=offset)
            sale = Sale(invoice_no=f"ANA-{offset:04d}", sale_date=when, total=0)
            db.add(sale)
            db.flush()
            items = [SaleItem(sale_id=sale.id, product_id=runner.id, sku=runner.sku,
                              product_name=runner.name, quantity=3, unit_price=330,
                              cost_price=250, line_total=990)]
            if offset % 15 == 0:
                items.append(SaleItem(sale_id=sale.id, product_id=trickler.id,
                                      sku=trickler.sku, product_name=trickler.name,
                                      quantity=2, unit_price=180, cost_price=100,
                                      line_total=360))
            db.add_all(items)
            sale.total = sum(i.line_total for i in items)
        db.commit()
        return {"runner_id": runner.id, "trickler_id": trickler.id,
                "dead_id": dead.id, "supplier_id": sup.id}
    finally:
        db.close()


class TestMovers:
    def test_the_daily_seller_is_a_fast_mover(self, client, trading):
        rows = client.get("/api/analytics/movers",
                          params={"direction": "fast", "days": 90, "limit": 100}
                          ).json()["items"]
        entry = next(r for r in rows if r["product_id"] == trading["runner_id"])
        assert entry["movement"] == "fast"
        assert entry["sold_qty"] == 180          # 3 a day for 60 days
        assert 2.0 < entry["daily_rate"] < 4.0

    def test_the_never_sold_product_is_dead_stock(self, client, trading):
        rows = client.get("/api/analytics/movers",
                          params={"direction": "dead", "days": 90, "limit": 100}
                          ).json()["items"]
        assert trading["dead_id"] in [r["product_id"] for r in rows]

    def test_dead_stock_is_ranked_by_cash_tied_up(self, client, trading):
        rows = client.get("/api/analytics/movers",
                          params={"direction": "dead", "days": 90, "limit": 100}
                          ).json()["items"]
        values = [r["stock_value"] for r in rows]
        assert values == sorted(values, reverse=True)

    def test_the_occasional_seller_is_not_called_fast(self, client, trading):
        rows = client.get("/api/analytics/movers",
                          params={"direction": "fast", "days": 90, "limit": 100}
                          ).json()["items"]
        entry = next(r for r in rows if r["product_id"] == trading["trickler_id"])
        assert entry["movement"] in ("slow", "medium")


class TestForecast:
    def test_forecast_scales_with_the_horizon(self, client, trading):
        body = client.get(
            f"/api/analytics/products/{trading['runner_id']}/forecast",
            params={"days": 90}).json()
        f = body["forecast"]
        assert f["next_30d"] > f["next_7d"]
        assert abs(f["next_30d"] * 3 - f["next_90d"]) < 1.0

    def test_replenishment_plan_is_consistent(self, client, trading):
        plan = client.get(
            f"/api/analytics/products/{trading['runner_id']}/forecast",
            params={"days": 90}).json()["replenishment"]
        assert plan["reorder_point"] >= plan["safety_stock"]
        assert plan["economic_order_qty"] > 0
        assert plan["days_of_cover"] is not None
        assert plan["lead_time_days"] == 7

    def test_stockout_is_projected_for_a_moving_product(self, client, trading):
        plan = client.get(
            f"/api/analytics/products/{trading['runner_id']}/forecast",
            params={"days": 90}).json()["replenishment"]
        assert plan["projected_stockout"] is not None

    def test_weekday_seasonality_is_labelled_in_order(self, client, trading):
        body = client.get(
            f"/api/analytics/products/{trading['runner_id']}/forecast",
            params={"days": 90}).json()
        assert [s["day"] for s in body["weekday_seasonality"]] == \
            ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        assert len(body["weekly_demand"]) > 1

    def test_unknown_product_is_reported_cleanly(self, client, trading):
        assert client.get("/api/analytics/products/999999/forecast").status_code == 404


class TestReorder:
    def test_a_fast_mover_running_low_is_suggested(self, client, trading):
        db = SessionLocal()
        try:
            product = db.get(Product, trading["runner_id"])
            product.stock_qty = 2
            db.commit()
        finally:
            db.close()

        body = client.get("/api/analytics/reorder", params={"days": 90}).json()
        entry = next(r for r in body["suggestions"]
                     if r["product_id"] == trading["runner_id"])
        assert entry["suggested_qty"] > 0
        assert entry["urgency"] > 0
        assert entry["reason"]
        assert entry["order_cost"] == round(entry["suggested_qty"] * entry["unit_cost"], 2)

    def test_suggestions_are_ordered_by_urgency(self, client, trading):
        rows = client.get("/api/analytics/reorder",
                          params={"days": 90}).json()["suggestions"]
        scores = [r["urgency"] for r in rows]
        assert scores == sorted(scores, reverse=True)

    def test_suggested_quantity_covers_lead_time_demand(self, client, trading):
        rows = client.get("/api/analytics/reorder",
                          params={"days": 90}).json()["suggestions"]
        entry = next(r for r in rows if r["product_id"] == trading["runner_id"])
        assert entry["suggested_qty"] >= entry["daily_rate"] * entry["lead_time_days"]

    def test_a_well_stocked_dead_product_is_not_reordered(self, client, trading):
        rows = client.get("/api/analytics/reorder",
                          params={"days": 90}).json()["suggestions"]
        assert trading["dead_id"] not in [r["product_id"] for r in rows]

    def test_totals_group_by_supplier(self, client, trading):
        body = client.get("/api/analytics/reorder", params={"days": 90}).json()
        assert body["by_supplier"]
        assert abs(sum(b["cost"] for b in body["by_supplier"]) - body["total_cost"]) < 1.0


class TestAbcAndOverview:
    def test_top_earner_is_class_a(self, client, trading):
        rows = client.get("/api/analytics/abc", params={"days": 90}).json()["items"]
        entry = next(r for r in rows if r["product_id"] == trading["runner_id"])
        assert entry["abc"] == "A"

    def test_every_matrix_cell_has_a_policy(self, client, trading):
        matrix = client.get("/api/analytics/abc", params={"days": 90}).json()["matrix"]
        assert matrix and all(cell["policy"] for cell in matrix)

    def test_overview_headline_numbers(self, client, trading):
        body = client.get("/api/analytics/overview", params={"days": 90}).json()
        assert body["sku_count"] > 0
        assert set(body["movement"]) == {"fast", "medium", "slow", "dead"}
        assert body["stock_turnover_annualised"] >= 0
        assert isinstance(body["urgent"], list)


class TestSupplierLeadTime:
    def test_lead_time_defaults_apply_to_existing_suppliers(self, client):
        """The migration backfills, so a supplier created without them still works."""
        db = SessionLocal()
        try:
            sup = Supplier(name="No Lead Time Supplier")
            db.add(sup)
            db.commit()
            assert sup.lead_time_days == 7.0
            assert sup.order_cycle_days == 30.0
        finally:
            db.close()

    def test_longer_lead_time_raises_the_reorder_point(self):
        assert fc.reorder_point(2.0, 30, 0, 1.0) > fc.reorder_point(2.0, 7, 0, 1.0)


class TestMinimumObservationWindow:
    def test_one_recent_sale_is_not_extrapolated_to_daily_demand(self, client):
        db = SessionLocal()
        try:
            product = Product(sku="ANA-ONE", name="ANA One Sale Gasket",
                              cost_price=50, sell_price=90, stock_qty=10)
            db.add(product)
            db.flush()
            sale = Sale(invoice_no="ANA-ONE-1", sale_date=datetime.utcnow(), total=90)
            db.add(sale)
            db.flush()
            db.add(SaleItem(sale_id=sale.id, product_id=product.id, sku=product.sku,
                            product_name=product.name, quantity=1, unit_price=90,
                            cost_price=50, line_total=90))
            db.commit()
            product_id = product.id
        finally:
            db.close()

        body = client.get(f"/api/analytics/products/{product_id}/forecast",
                          params={"days": 90}).json()
        assert body["forecast"]["next_30d"] <= 1.5, body["forecast"]
        assert body["daily_rate"] <= 1 / 28 + 1e-6
