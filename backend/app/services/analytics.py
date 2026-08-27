"""Turns sales history into stock intelligence: movers, ABC/XYZ and reorder plans.

The maths lives in `forecast.py` as pure functions; this module is the data
layer that feeds it from the Product / Sale / SaleItem tables.
"""
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.models import Product, Sale, SaleItem, Supplier
from app.services import forecast as fc

DEFAULT_HORIZON = 90
ORDER_COST = 150.0        # Assumed clerical + trip cost of raising one order.
HOLDING_RATE = 0.25       # Annual carrying cost as a fraction of unit cost.
SERVICE_LEVEL_Z = 1.65    # ~95% availability.
DEFAULT_LEAD_DAYS = 7.0
DEFAULT_CYCLE_DAYS = 30.0

# Never infer a demand rate from fewer than four weeks of shelf time: a single
# sale on the last day of the window would otherwise read as "one a day".
MIN_OBSERVATION_DAYS = 28


def daily_demand(db: Session, days: int = DEFAULT_HORIZON, end: date | None = None):
    """Per-product daily sold quantity over the window.

    Returns (series_by_product, start, end). Each series is a dense list of
    `days` floats — dense because the forecasting maths needs the zero days to
    measure how intermittent an item is.
    """
    end = end or date.today()
    start = end - timedelta(days=days - 1)

    rows = db.execute(
        select(
            SaleItem.product_id,
            func.date(Sale.sale_date).label("d"),
            func.sum(SaleItem.quantity).label("qty"),
        )
        .join(Sale, Sale.id == SaleItem.sale_id)
        .where(
            SaleItem.product_id.isnot(None),
            func.date(Sale.sale_date) >= start.isoformat(),
            func.date(Sale.sale_date) <= end.isoformat(),
        )
        .group_by(SaleItem.product_id, func.date(Sale.sale_date))
    ).all()

    index = {(start + timedelta(days=i)).isoformat(): i for i in range(days)}
    series: dict[int, list[float]] = {}
    for product_id, day, qty in rows:
        bucket = series.setdefault(product_id, [0.0] * days)
        pos = index.get(str(day)[:10])
        if pos is not None:
            bucket[pos] += float(qty or 0)
    return series, start, end


def trim_to_shelf_life(series, created_at, window_start):
    """Drop leading days before a product was actually sellable.

    Those days are not evidence of slow demand; counting them inflates the
    demand interval and pushes a healthy new line into the intermittent bucket.
    The shelf date is whichever came first — the record being created, or the
    earliest sale in the window.
    """
    if not series:
        return series

    offset = 0
    created = created_at.date() if isinstance(created_at, datetime) else created_at
    if created and created > window_start:
        offset = min((created - window_start).days, len(series) - 1)

    first_sale = next((i for i, v in enumerate(series) if v > 0), None)
    if first_sale is not None:
        offset = min(offset, first_sale)

    offset = max(0, min(offset, len(series) - MIN_OBSERVATION_DAYS))
    return series[offset:] if offset else series


def shelf_offset(series, created_at, window_start) -> int:
    return len(series) - len(trim_to_shelf_life(series, created_at, window_start))


def _last_sale_dates(db: Session) -> dict[int, str]:
    rows = db.execute(
        select(SaleItem.product_id, func.max(func.date(Sale.sale_date)))
        .join(Sale, Sale.id == SaleItem.sale_id)
        .where(SaleItem.product_id.isnot(None))
        .group_by(SaleItem.product_id)
    ).all()
    return {pid: str(d)[:10] for pid, d in rows if d}


def analyze(db: Session, days: int = DEFAULT_HORIZON, supplier_id: int | None = None,
            category_id: int | None = None, include_inactive: bool = False,
            end: date | None = None):
    """Build the full analytics row set: forecast, classes and replenishment plan."""
    query = select(Product, Supplier).join(
        Supplier, Supplier.id == Product.supplier_id, isouter=True
    )
    if not include_inactive:
        query = query.where(Product.is_active.is_(True))
    if supplier_id:
        query = query.where(Product.supplier_id == supplier_id)
    if category_id:
        query = query.where(Product.category_id == category_id)

    pairs = db.execute(query).all()
    series_by_product, start, end_date = daily_demand(db, days, end)
    last_sold = _last_sale_dates(db)

    results = []
    for product, supplier in pairs:
        raw = series_by_product.get(product.id, [0.0] * days)
        series = trim_to_shelf_life(raw, product.created_at, start)
        sold_qty = sum(series)

        rate, info = fc.forecast_daily_rate(series)
        sigma = fc._stdev(series) if sold_qty > 0 else rate * 0.75

        last_date = last_sold.get(product.id)
        days_since = None
        if last_date:
            days_since = (end_date - date.fromisoformat(last_date)).days

        cost = float(product.cost_price or 0)
        price = float(product.sell_price or 0)
        on_hand = float(product.stock_qty or 0)

        lead = float(getattr(supplier, "lead_time_days", None) or DEFAULT_LEAD_DAYS)
        review = float(getattr(supplier, "order_cycle_days", None) or DEFAULT_CYCLE_DAYS)

        rop = fc.reorder_point(rate, lead, review, sigma, SERVICE_LEVEL_Z)
        # An explicit reorder level set by the shop always wins if it is higher.
        effective_rop = max(rop, float(product.reorder_level or 0))

        eoq = fc.economic_order_quantity(rate * 365, ORDER_COST, cost, HOLDING_RATE)
        cover = fc.days_of_cover(on_hand, rate)
        margin = price - cost
        revenue = sold_qty * price

        results.append({
            "product_id": product.id,
            "sku": product.sku,
            "name": product.name,
            "category_id": product.category_id,
            "supplier_id": product.supplier_id,
            "supplier": supplier.name if supplier else "",
            "unit_cost": round(cost, 2),
            "sell_price": round(price, 2),
            "unit_margin": round(margin, 2),
            "margin_pct": round(margin / price * 100, 1) if price > 0 else 0.0,
            "on_hand": round(on_hand, 2),
            "stock_value": round(on_hand * cost, 2),
            "sold_qty": round(sold_qty, 2),
            "revenue": round(revenue, 2),
            "demand_value": round(max(revenue, rate * days * price), 2),
            "gross_profit": round(sold_qty * margin, 2),
            "daily_rate": round(rate, 4),
            "monthly_rate": round(rate * 30, 2),
            "forecast_30d": round(rate * 30, 1),
            "forecast_60d": round(rate * 60, 1),
            "forecast_90d": round(rate * 90, 1),
            "demand_pattern": info.get("pattern", "none"),
            "method": info.get("method", "none"),
            "cv2": round(info.get("cv2", 0.0), 3),
            "adi": round(info.get("adi", 0.0), 2),
            "xyz": fc.xyz_class(info.get("cv2", 0.0)),
            "movement": fc.movement_class(rate, days_since, days),
            "last_sold": last_date,
            "days_since_sale": days_since,
            "lead_time_days": lead,
            "review_days": review,
            "safety_stock": round(fc.safety_stock(sigma, lead, review, SERVICE_LEVEL_Z), 1),
            "reorder_point": round(effective_rop, 1),
            "reorder_level": float(product.reorder_level or 0),
            "eoq": round(eoq, 1),
            "days_of_cover": round(cover, 1) if cover is not None else None,
        })

    fc.abc_classify(results, "demand_value")
    for row in results:
        row["value_share"] = round(row["value_share"] * 100, 2)
        row["cumulative_share"] = round(row["cumulative_share"] * 100, 2)
        row["abc_xyz"] = row["abc"] + row["xyz"]
        row["urgency"] = fc.urgency_score(
            row["on_hand"], row["reorder_point"], row["daily_rate"], row["abc"]
        )
    return results, start, end_date


def _reason(row) -> str:
    """Plain-language explanation the shop owner can act on."""
    if row["on_hand"] <= 0:
        return "Out of stock" + (" — still selling" if row["daily_rate"] > 0 else "")
    if row["days_of_cover"] is not None and row["days_of_cover"] < row["lead_time_days"]:
        return (f"Only {row['days_of_cover']:.0f} days of cover left, "
                f"supplier takes {row['lead_time_days']:.0f} days")
    if row["on_hand"] < row["safety_stock"]:
        return "Below safety stock"
    if row["on_hand"] < row["reorder_point"]:
        return "At or below reorder point"
    return "Top-up to economic order quantity"


def reorder_suggestions(db: Session, days: int = DEFAULT_HORIZON,
                        supplier_id: int | None = None, only_needed: bool = True):
    """Suggested purchase quantities, ranked by urgency."""
    rows, start, end = analyze(db, days=days, supplier_id=supplier_id)
    suggestions = []

    for row in rows:
        available = row["on_hand"]
        needed = row["reorder_point"] + max(row["eoq"], 0) - available

        if row["daily_rate"] <= 0 and available > 0:
            needed = 0  # Nothing selling and stock on the shelf: do not reorder.

        suggested = max(0.0, round(needed))
        if only_needed and (suggested <= 0 or available > row["reorder_point"]):
            continue

        cover = row["days_of_cover"]
        suggestions.append({
            **row,
            "suggested_qty": suggested,
            "order_cost": round(suggested * row["unit_cost"], 2),
            "projected_stockout": (
                (end + timedelta(days=int(cover))).isoformat()
                if cover is not None and cover < 365 else None
            ),
            "reason": _reason(row),
        })

    suggestions.sort(key=lambda r: (-r["urgency"], -r["revenue"]))
    return suggestions, start, end


def movers(db: Session, days: int = DEFAULT_HORIZON, limit: int = 25,
           direction: str = "fast"):
    """Fastest moving, slowest moving, or dead stock."""
    rows, start, end = analyze(db, days=days)
    if direction == "fast":
        rows = [r for r in rows if r["daily_rate"] > 0]
        rows.sort(key=lambda r: (-r["daily_rate"], -r["revenue"]))
    elif direction == "dead":
        rows = [r for r in rows if r["movement"] == "dead" and r["on_hand"] > 0]
        rows.sort(key=lambda r: -r["stock_value"])
    else:
        rows = [r for r in rows if r["on_hand"] > 0]
        rows.sort(key=lambda r: (r["daily_rate"], -r["stock_value"]))
    return rows[:limit], start, end
