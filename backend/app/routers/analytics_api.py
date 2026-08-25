"""Forecast-driven endpoints: movers, ABC/XYZ, reorder advice and item outlook."""
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query

from .. import db
from ..security import require
from ..services import analytics
from ..services import forecast as fc

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("/movers")
def movers(
    direction: str = Query(default="fast", pattern="^(fast|slow|dead)$"),
    days: int = Query(default=90, ge=7, le=730),
    limit: int = Query(default=25, ge=1, le=500),
    user=Depends(require("analytics.view")),
):
    """Fast movers (restock priorities), slow movers and dead stock (cash traps)."""
    rows, start, end = analytics.movers(days=days, limit=limit, direction=direction)
    return {
        "direction": direction,
        "window": {"from": start.isoformat(), "to": end.isoformat(), "days": days},
        "count": len(rows),
        "items": rows,
    }


@router.get("/reorder")
def reorder(
    days: int = Query(default=90, ge=7, le=730),
    supplier_id: int | None = None,
    only_needed: bool = True,
    user=Depends(require("analytics.view")),
):
    """What to buy, how much, from whom, and why — ranked by urgency."""
    rows, start, end = analytics.reorder_suggestions(
        days=days, supplier_id=supplier_id, only_needed=only_needed
    )

    by_supplier = {}
    for row in rows:
        key = row["supplier"] or "UNASSIGNED"
        bucket = by_supplier.setdefault(
            key, {"supplier": key, "supplier_id": row["supplier_id"],
                  "lines": 0, "units": 0.0, "cost": 0.0}
        )
        bucket["lines"] += 1
        bucket["units"] += row["suggested_qty"]
        bucket["cost"] = round(bucket["cost"] + row["order_cost"], 2)

    return {
        "window": {"from": start.isoformat(), "to": end.isoformat(), "days": days},
        "count": len(rows),
        "total_cost": round(sum(r["order_cost"] for r in rows), 2),
        "by_supplier": sorted(by_supplier.values(), key=lambda b: -b["cost"]),
        "suggestions": rows,
    }


@router.get("/abc")
def abc_analysis(days: int = Query(default=90, ge=7, le=730),
                 user=Depends(require("analytics.view"))):
    """ABC (value) x XYZ (predictability) matrix for stocking policy."""
    rows, start, end = analytics.analyze(days=days)

    matrix, summary = {}, {}
    for row in rows:
        matrix[row["abc_xyz"]] = matrix.get(row["abc_xyz"], 0) + 1
        bucket = summary.setdefault(
            row["abc"], {"class": row["abc"], "items": 0, "revenue": 0.0,
                         "stock_value": 0.0, "gross_profit": 0.0}
        )
        bucket["items"] += 1
        bucket["revenue"] = round(bucket["revenue"] + row["revenue"], 2)
        bucket["stock_value"] = round(bucket["stock_value"] + row["stock_value"], 2)
        bucket["gross_profit"] = round(bucket["gross_profit"] + row["gross_profit"], 2)

    policy = {
        "AX": "Top value, predictable — keep tight stock, order little and often",
        "AY": "Top value, variable — hold extra safety stock",
        "AZ": "Top value, erratic — review by hand every cycle",
        "BX": "Mid value, predictable — automate on reorder point",
        "BY": "Mid value, variable — moderate safety stock",
        "BZ": "Mid value, erratic — order to demand",
        "CX": "Low value, predictable — bulk buy, review rarely",
        "CY": "Low value, variable — bulk buy",
        "CZ": "Low value, erratic — order only when asked for",
    }
    return {
        "window": {"from": start.isoformat(), "to": end.isoformat(), "days": days},
        "summary": sorted(summary.values(), key=lambda b: b["class"]),
        "matrix": [
            {"cell": k, "items": v, "policy": policy.get(k, "")}
            for k, v in sorted(matrix.items())
        ],
        "items": rows,
    }


@router.get("/items/{item_id}/forecast")
def item_forecast(item_id: int, days: int = Query(default=180, ge=30, le=730),
                  user=Depends(require("analytics.view"))):
    """Detailed outlook for one item: pattern, projection and replenishment plan."""
    item = db.query_one(
        """SELECT i.*, c.name AS category, s.code AS supplier,
                  COALESCE(s.lead_time_days, 7) AS lead_time_days,
                  COALESCE(s.order_cycle_days, 30) AS order_cycle_days
             FROM items i
             LEFT JOIN categories c ON c.id = i.category_id
             LEFT JOIN suppliers s ON s.id = i.supplier_id
            WHERE i.id = ?""",
        (item_id,),
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")

    series_map, start, end = analytics.daily_demand(days)
    raw_series = series_map.get(item_id, [0.0] * days)
    offset = analytics.shelf_offset(raw_series, item["created_at"], start)
    series = raw_series[offset:]
    series_start = start + timedelta(days=offset)
    rate, info = fc.forecast_daily_rate(series)

    weekly = fc.seasonal_indices(series, 7)
    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    weekday_of_start = series_start.weekday()
    seasonality = [
        {"day": day_names[(weekday_of_start + i) % 7], "index": round(weekly[i], 3)}
        for i in range(7)
    ]
    seasonality.sort(key=lambda s: day_names.index(s["day"]))

    z = float(db.get_setting("service_level_z", "1.65"))
    lead = float(item["lead_time_days"])
    review = float(item["order_cycle_days"])
    sigma = fc._stdev(series)
    rop = fc.reorder_point(rate, lead, review, sigma, z)
    eoq = fc.economic_order_quantity(
        rate * 365, analytics.ORDER_COST, float(item["unit_cost"] or 0), analytics.HOLDING_RATE
    )
    cover = fc.days_of_cover(float(item["stock_qty"] or 0), rate)

    # Weekly buckets keep the chart readable over a long window.
    buckets = []
    for week_start in range(0, len(series), 7):
        chunk = series[week_start:week_start + 7]
        buckets.append({
            "week_of": (series_start + timedelta(days=week_start)).isoformat(),
            "qty": round(sum(chunk), 2),
        })

    history = db.query(
        "SELECT period, qty, revenue FROM demand_history WHERE item_id = ? ORDER BY period",
        (item_id,),
    )
    return {
        "item": dict(item),
        "window": {"from": start.isoformat(), "to": end.isoformat(), "days": days,
                   "measured_from": series_start.isoformat()},
        "pattern": info,
        "daily_rate": round(rate, 4),
        "forecast": {
            "next_7d": round(rate * 7, 1),
            "next_30d": round(rate * 30, 1),
            "next_90d": round(rate * 90, 1),
        },
        "replenishment": {
            "lead_time_days": lead,
            "review_days": review,
            "safety_stock": round(fc.safety_stock(sigma, lead, review, z), 1),
            "reorder_point": round(rop, 1),
            "economic_order_qty": round(eoq, 1),
            "days_of_cover": round(cover, 1) if cover is not None else None,
            "projected_stockout": (
                (end + timedelta(days=int(cover))).isoformat()
                if cover is not None and cover < 365 else None
            ),
        },
        "weekly_demand": buckets,
        "weekday_seasonality": seasonality,
        "monthly_history": [dict(r) for r in history],
    }


@router.get("/overview")
def overview(days: int = Query(default=90, ge=7, le=730),
             user=Depends(require("analytics.view"))):
    """Headline stock-health numbers for the management dashboard."""
    rows, start, end = analytics.analyze(days=days)

    counts = {"fast": 0, "medium": 0, "slow": 0, "dead": 0}
    basis = {"pos": 0, "history": 0}
    never_sold = 0
    dead_value = stock_value = 0.0
    for row in rows:
        counts[row["movement"]] = counts.get(row["movement"], 0) + 1
        basis[row["movement_basis"]] = basis.get(row["movement_basis"], 0) + 1
        stock_value += row["stock_value"]
        if row["movement"] == "dead":
            dead_value += row["stock_value"]
        if row["sold_qty"] == 0 and row["movement_basis"] == "pos":
            never_sold += 1

    out_of_stock = [r for r in rows if r["on_hand"] <= 0]
    below_rop = [r for r in rows if 0 < r["on_hand"] <= r["reorder_point"]]
    fast_out = [r for r in out_of_stock if r["movement"] == "fast"]

    suggestions, _, _ = analytics.reorder_suggestions(days=days)
    cogs = sum(r["sold_qty"] * r["unit_cost"] for r in rows)
    avg_stock_value = stock_value if stock_value > 0 else 1
    turnover = (cogs / avg_stock_value) * (365 / days)

    return {
        "window": {"from": start.isoformat(), "to": end.isoformat(), "days": days},
        "sku_count": len(rows),
        "stock_value": round(stock_value, 2),
        "movement": counts,
        "evidence": {
            "from_till": basis.get("pos", 0) - never_sold,
            "from_imported_history": basis.get("history", 0),
            "no_demand_data": never_sold,
        },
        "dead_stock_value": round(dead_value, 2),
        "dead_stock_pct": round(dead_value / avg_stock_value * 100, 1),
        "out_of_stock": len(out_of_stock),
        "fast_movers_out_of_stock": len(fast_out),
        "below_reorder_point": len(below_rop),
        "reorder_lines": len(suggestions),
        "reorder_cost": round(sum(s["order_cost"] for s in suggestions), 2),
        "stock_turnover_annualised": round(turnover, 2),
        "urgent": suggestions[:10],
        "at_risk_fast_movers": sorted(fast_out, key=lambda r: -r["revenue"])[:10],
    }
