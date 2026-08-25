"""Shop settings and database housekeeping."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import db
from ..security import audit, current_user, require

router = APIRouter(prefix="/api/settings", tags=["settings"])

EDITABLE = {
    "shop_name", "shop_address", "shop_phone", "currency", "currency_symbol",
    "receipt_footer", "low_stock_default", "service_level_z",
    "default_lead_time_days", "session_hours",
}


class SettingsIn(BaseModel):
    values: dict[str, str]


@router.get("")
def get_settings(user=Depends(current_user)):
    rows = db.query("SELECT key, value FROM settings ORDER BY key")
    return {"settings": {r["key"]: r["value"] for r in rows}, "editable": sorted(EDITABLE)}


@router.put("")
def update_settings(body: SettingsIn, user=Depends(require("settings.manage"))):
    unknown = set(body.values) - EDITABLE
    if unknown:
        raise HTTPException(status_code=400,
                            detail=f"Not editable: {', '.join(sorted(unknown))}")

    for key in ("service_level_z", "default_lead_time_days", "session_hours"):
        if key in body.values:
            try:
                if float(body.values[key]) <= 0:
                    raise ValueError
            except ValueError:
                raise HTTPException(status_code=400,
                                    detail=f"{key} must be a positive number")

    for key, value in body.values.items():
        db.set_setting(key, value)
    audit(user, "settings.updated", "settings", "-", body.values)
    return get_settings(user)


@router.get("/health")
def health(user=Depends(require("settings.manage"))):
    """Row counts and integrity signals for the admin screen."""
    tables = ["users", "items", "categories", "suppliers", "services", "sales",
              "sale_lines", "stock_moves", "purchase_orders", "demand_history", "audit_log"]
    counts = {t: db.query_one(f"SELECT COUNT(*) AS n FROM {t}")["n"] for t in tables}

    negative = db.query_one(
        "SELECT COUNT(*) AS n FROM items WHERE stock_qty < 0"
    )["n"]
    below_cost = db.query_one(
        "SELECT COUNT(*) AS n FROM items WHERE active = 1 AND delisted = 0 "
        "AND retail_price < unit_cost AND retail_price > 0"
    )["n"]
    no_price = db.query_one(
        "SELECT COUNT(*) AS n FROM items WHERE active = 1 AND delisted = 0 AND retail_price <= 0"
    )["n"]
    orphan_moves = db.query_one(
        "SELECT COUNT(*) AS n FROM stock_moves m "
        "LEFT JOIN items i ON i.id = m.item_id WHERE i.id IS NULL"
    )["n"]

    return {
        "counts": counts,
        "warnings": {
            "negative_stock": negative,
            "priced_below_cost": below_cost,
            "missing_retail_price": no_price,
            "orphan_stock_moves": orphan_moves,
        },
        "database": db.current_db_path(),
    }
