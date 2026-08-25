"""Turns sales history into stock intelligence: movers, ABC/XYZ and reorder plans."""
from datetime import date, datetime, timedelta

from .. import db
from . import forecast as fc

DEFAULT_HORIZON = 90
# Never infer a demand rate from fewer than four weeks of shelf time. Without
# this floor a single sale on the last day of the window trims the series to one
# day and reads as "one a day", which would order months of stock off one sale.
MIN_OBSERVATION_DAYS = 28
ORDER_COST = 150.0      # Assumed clerical + trip cost of raising one purchase order.
HOLDING_RATE = 0.25     # Annual carrying cost as a fraction of unit cost.


def _parse_date(value):
    if isinstance(value, date):
        return value
    if not value:
        return None
    return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()


def daily_demand(days=DEFAULT_HORIZON, end=None):
    """Per-item daily sold quantity over the window.

    Returns (series_by_item, start, end) where each series is a dense list of
    `days` floats ending on `end` — dense because the forecasting maths needs
    the zero days to measure how intermittent an item is.
    """
    end = _parse_date(end) or date.today()
    start = end - timedelta(days=days - 1)

    rows = db.query(
        """SELECT l.item_id, s.business_date AS d, SUM(l.qty) AS qty
             FROM sale_lines l
             JOIN sales s ON s.id = l.sale_id
            WHERE s.status = 'completed'
              AND l.item_id IS NOT NULL
              AND s.business_date BETWEEN ? AND ?
         GROUP BY l.item_id, s.business_date""",
        (start.isoformat(), end.isoformat()),
    )

    index = {(start + timedelta(days=i)).isoformat(): i for i in range(days)}
    series = {}
    for row in rows:
        bucket = series.setdefault(row["item_id"], [0.0] * days)
        pos = index.get(str(row["d"])[:10])
        if pos is not None:
            bucket[pos] += float(row["qty"] or 0)
    return series, start, end


def trim_to_shelf_life(series, created_at, window_start):
    """Drop the leading days before an item was actually sellable.

    Those days are not evidence of slow demand; counting them inflates the
    average demand interval and pushes a healthy new line into the intermittent
    bucket. The shelf date is whichever came first — the record being created or
    the earliest sale in the window — because imported items are created today
    but carry older history.
    """
    if not series:
        return series

    offset = 0
    created = _parse_date(created_at)
    if created and created > window_start:
        offset = min((created - window_start).days, len(series) - 1)

    first_sale = next((i for i, v in enumerate(series) if v > 0), None)
    if first_sale is not None:
        offset = min(offset, first_sale)

    # Keep at least the minimum observation window, where the data allows it.
    offset = max(0, min(offset, len(series) - MIN_OBSERVATION_DAYS))
    return series[offset:] if offset else series


def shelf_offset(series, created_at, window_start):
    """How many leading days trim_to_shelf_life would drop from this series."""
    return len(series) - len(trim_to_shelf_life(series, created_at, window_start))


def _history_daily_rate(item_ids):
    """Fallback daily rate from imported monthly history, for items with no POS sales yet.

    Without this, every item looks dead on day one of the rollout and the
    reorder advice would be useless until months of till data accumulate.
    """
    if not item_ids:
        return {}
    placeholders = ",".join("?" * len(item_ids))
    rows = db.query(
        f"""SELECT item_id, SUM(qty) AS qty, COUNT(DISTINCT period) AS months
              FROM demand_history
             WHERE item_id IN ({placeholders})
          GROUP BY item_id""",
        tuple(item_ids),
    )
    return {
        r["item_id"]: (float(r["qty"] or 0) / max(int(r["months"] or 1), 1)) / 30.0
        for r in rows
    }


def _last_sale_dates():
    rows = db.query(
        """SELECT l.item_id, MAX(s.business_date) AS last_date
             FROM sale_lines l
             JOIN sales s ON s.id = l.sale_id
            WHERE s.status = 'completed' AND l.item_id IS NOT NULL
         GROUP BY l.item_id"""
    )
    return {r["item_id"]: str(r["last_date"])[:10] for r in rows}


def analyze(days=DEFAULT_HORIZON, include_inactive=False, supplier_id=None,
            category_id=None, end=None):
    """Build the full analytics row set: forecast, classes and replenishment plan."""
    z = float(db.get_setting("service_level_z", "1.65"))
    default_lead = float(db.get_setting("default_lead_time_days", "7"))

    where = ["1=1"]
    params = []
    if not include_inactive:
        where.append("i.active = 1 AND i.delisted = 0")
    if supplier_id:
        where.append("i.supplier_id = ?")
        params.append(supplier_id)
    if category_id:
        where.append("i.category_id = ?")
        params.append(category_id)

    items = db.query(
        f"""SELECT i.*, c.name AS category, sup.code AS supplier_code,
                   sup.id AS sup_id,
                   COALESCE(sup.lead_time_days, ?) AS lead_time_days,
                   COALESCE(sup.order_cycle_days, 30) AS order_cycle_days
              FROM items i
              LEFT JOIN categories c ON c.id = i.category_id
              LEFT JOIN suppliers sup ON sup.id = i.supplier_id
             WHERE {' AND '.join(where)}""",
        (default_lead, *params),
    )

    series_by_item, start, end_date = daily_demand(days, end)
    last_sold = _last_sale_dates()
    ids = [row["id"] for row in items]
    history_rate = _history_daily_rate(ids)

    # Quantities already on order reduce what we need to buy again.
    on_order = {
        r["item_id"]: float(r["qty"] or 0)
        for r in db.query(
            """SELECT pl.item_id, SUM(pl.qty_ordered - pl.qty_received) AS qty
                 FROM po_lines pl JOIN purchase_orders po ON po.id = pl.po_id
                WHERE po.status IN ('ordered', 'partial')
             GROUP BY pl.item_id"""
        )
    }

    results = []
    for item in items:
        item_id = item["id"]
        series = series_by_item.get(item_id, [0.0] * days)
        sold_qty = sum(series)

        series = trim_to_shelf_life(series, item["created_at"], start)

        rate, info = fc.forecast_daily_rate(series)
        source = "pos"
        if sold_qty == 0 and history_rate.get(item_id, 0) > 0:
            # No till history yet — lean on the imported workbook history.
            rate = history_rate[item_id]
            info = {"pattern": "history", "cv2": 0.0, "adi": 0.0, "method": "history-average"}
            source = "history"

        sigma = fc._stdev(series) if sold_qty > 0 else rate * 0.75

        last_date = last_sold.get(item_id)
        days_since = (end_date - _parse_date(last_date)).days if last_date else None

        cost = float(item["unit_cost"] or 0)
        price = float(item["retail_price"] or 0)
        on_hand = float(item["stock_qty"] or 0)
        incoming = on_order.get(item_id, 0.0)

        lead = float(item["lead_time_days"] or default_lead)
        review = float(item["order_cycle_days"] or 30)

        rop = fc.reorder_point(rate, lead, review, sigma, z)
        # An explicit per-item minimum from the shop always wins if it is higher.
        manual_rop = float(item["reorder_point"] or 0)
        effective_rop = max(rop, manual_rop)

        annual_demand = rate * 365
        eoq = fc.economic_order_quantity(annual_demand, ORDER_COST, cost, HOLDING_RATE)
        cover = fc.days_of_cover(on_hand, rate)

        revenue = sold_qty * price
        margin = price - cost
        # Value at the demand rate actually being forecast, so ABC still ranks
        # correctly for lines whose only evidence is the imported history and
        # whose till revenue is therefore still zero.
        demand_value = max(revenue, rate * days * price)
        results.append({
            "item_id": item_id,
            "sku": item["sku"],
            "description": item["description"],
            "category": item["category"] or "",
            "category_id": item["category_id"],
            "supplier": item["supplier_code"] or "",
            "supplier_id": item["sup_id"],
            "unit_cost": round(cost, 2),
            "retail_price": round(price, 2),
            "unit_margin": round(margin, 2),
            "margin_pct": round(margin / price * 100, 1) if price > 0 else 0.0,
            "on_hand": round(on_hand, 2),
            "on_order": round(incoming, 2),
            "stock_value": round(on_hand * cost, 2),
            "sold_qty": round(sold_qty, 2),
            "revenue": round(revenue, 2),
            "demand_value": round(demand_value, 2),
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
            # An item whose only evidence is the imported workbook is graded on
            # that demand rate alone. Ageing it out by recency would brand every
            # line "dead" on day one, before the till has recorded anything.
            "movement": fc.movement_class(
                rate, 0 if source == "history" else days_since, days
            ),
            "movement_basis": source,
            "last_sold": last_date,
            "days_since_sale": days_since,
            "lead_time_days": lead,
            "review_days": review,
            "safety_stock": round(fc.safety_stock(sigma, lead, review, z), 1),
            "reorder_point": round(effective_rop, 1),
            "eoq": round(eoq, 1),
            "days_of_cover": round(cover, 1) if cover is not None else None,
            "data_source": source,
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


def reorder_suggestions(days=DEFAULT_HORIZON, supplier_id=None, only_needed=True):
    """Suggested purchase quantities, ranked by urgency and grouped-ready by supplier."""
    rows, start, end = analyze(days=days, supplier_id=supplier_id)
    suggestions = []

    for row in rows:
        available = row["on_hand"] + row["on_order"]
        target = row["reorder_point"] + max(row["eoq"], 0)
        needed = target - available

        if row["daily_rate"] <= 0 and row["on_hand"] > 0:
            needed = 0  # Nothing selling and stock on the shelf: do not reorder.

        suggested = max(0.0, round(needed))
        if suggested <= 0 and only_needed:
            continue
        if only_needed and available > row["reorder_point"]:
            continue

        stockout_days = row["days_of_cover"]
        entry = dict(row)
        entry.update({
            "suggested_qty": suggested,
            "order_cost": round(suggested * row["unit_cost"], 2),
            "projected_stockout": (
                (end + timedelta(days=int(stockout_days))).isoformat()
                if stockout_days is not None and stockout_days < 365 else None
            ),
            "reason": _reason(row, available),
        })
        suggestions.append(entry)

    suggestions.sort(key=lambda r: (-r["urgency"], -r["revenue"]))
    return suggestions, start, end


def _reason(row, available):
    """Plain-language explanation the shop owner can act on."""
    if available <= 0:
        return "Out of stock" + (" — still selling" if row["daily_rate"] > 0 else "")
    if row["days_of_cover"] is not None and row["days_of_cover"] < row["lead_time_days"]:
        return (f"Only {row['days_of_cover']:.0f} days of cover left, "
                f"supplier takes {row['lead_time_days']:.0f} days")
    if available < row["safety_stock"]:
        return "Below safety stock"
    if available < row["reorder_point"]:
        return "At or below reorder point"
    return "Top-up to economic order quantity"


def movers(days=DEFAULT_HORIZON, limit=25, direction="fast"):
    """Fastest or slowest moving items over the window."""
    rows, start, end = analyze(days=days)
    if direction == "fast":
        # Filter on forecast demand, not till quantity, so lines carried by the
        # imported history are ranked too rather than silently dropped.
        rows = [r for r in rows if r["daily_rate"] > 0]
        rows.sort(key=lambda r: (-r["daily_rate"], -r["revenue"]))
    elif direction == "dead":
        rows = [r for r in rows if r["movement"] == "dead" and r["on_hand"] > 0]
        rows.sort(key=lambda r: -r["stock_value"])
    else:
        rows = [r for r in rows if r["on_hand"] > 0]
        rows.sort(key=lambda r: (r["daily_rate"], -r["stock_value"]))
    return rows[:limit], start, end
