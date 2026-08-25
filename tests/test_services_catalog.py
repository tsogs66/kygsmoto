"""The labour catalogue seeder must be additive, idempotent and stock-free."""
import pytest

from backend.seed import services_catalog


@pytest.fixture(scope="module")
def seeded(client, admin):
    """Run the seeder against the test database."""
    before = client.get("/api/services", headers=admin,
                        params={"active_only": False}).json()["services"]
    added, skipped = services_catalog.run()
    return {"before": before, "added": added, "skipped": skipped}


def test_seeder_adds_the_catalog(seeded):
    assert len(seeded["added"]) > 40, "the common-jobs catalogue should be substantial"


def test_every_job_is_available_at_the_till(client, admin, seeded):
    services = client.get("/api/services", headers=admin).json()["services"]
    names = {s["name"] for s in services}
    for group, name, fee in services_catalog.CATALOG:
        assert name in names, f"{name} missing from the till"


def test_running_twice_adds_nothing(seeded):
    added, skipped = services_catalog.run()
    assert added == [], "seeder must be idempotent"
    assert len(skipped) == len(services_catalog.CATALOG)


def test_no_duplicate_names_or_codes(client, admin, seeded):
    services = client.get("/api/services", headers=admin,
                          params={"active_only": False}).json()["services"]
    names = [s["name"].upper() for s in services]
    codes = [s["code"].upper() for s in services]
    assert len(names) == len(set(names))
    assert len(codes) == len(set(codes))


def test_existing_workbook_rates_are_not_overwritten(client, admin, seeded):
    """Anything already priced by the shop must keep its own fee."""
    after = {s["name"]: s["fee"] for s in
             client.get("/api/services", headers=admin,
                        params={"active_only": False}).json()["services"]}
    for original in seeded["before"]:
        assert after[original["name"]] == original["fee"]


def test_jobs_are_labour_not_inventory(client, admin, seeded):
    """A seeded job must not appear as a stocked item."""
    for group, name, fee in services_catalog.CATALOG[:12]:
        found = client.get("/api/items", headers=admin,
                           params={"q": name, "status": "all"}).json()
        assert found["total"] == 0, f"{name} should not exist as an inventory item"


def test_selling_a_seeded_job_moves_no_stock(client, admin, seeded):
    services = client.get("/api/services", headers=admin).json()["services"]
    job = next(s for s in services if s["name"] == "CVT OVERHAUL")

    moves_before = client.get("/api/inventory/moves", headers=admin,
                              params={"limit": 1000}).json()["moves"]
    sale = client.post("/api/pos/sales", headers=admin, json={
        "lines": [{"line_type": "service", "service_id": job["id"], "qty": 1}],
    }).json()["sale"]
    moves_after = client.get("/api/inventory/moves", headers=admin,
                             params={"limit": 1000}).json()["moves"]

    assert sale["labor_total"] == job["fee"]
    assert sale["parts_total"] == 0
    assert sale["cost_total"] == 0
    assert sale["profit"] == job["fee"], "labour is all margin — no cost of goods"
    assert len(moves_after) == len(moves_before), "labour must not touch stock"


def test_zero_fee_mode_prices_nothing(client, admin):
    """--zero-fees lets a shop set every rate itself."""
    added, _ = services_catalog.run(dry_run=True, zero_fees=True)
    assert all(fee == 0 for _, _, fee in added) or added == []


def test_database_path_follows_the_environment(monkeypatch, tmp_path):
    """Regression: the path must resolve per call, not at import time.

    Binding it at import made the whole suite depend on whether KYGS_DB was set
    before backend.app.db was first imported.
    """
    from backend.app import db

    target = tmp_path / "elsewhere.db"
    monkeypatch.setenv("KYGS_DB", str(target))
    assert db.current_db_path() == str(target)

    monkeypatch.delenv("KYGS_DB")
    assert db.current_db_path() == db.DEFAULT_DB_PATH
