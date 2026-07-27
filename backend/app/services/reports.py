from calendar import monthrange
from datetime import datetime, date, timedelta
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.core.config import settings
from app.models.models import Product, Sale, SaleItem, StockMovement
from app.services.stock import stock_status


def _period_bounds(
    period: str,
    year: Optional[int] = None,
    month: Optional[int] = None,
    week_start: Optional[date] = None,
):
    today = date.today()
    year = year or today.year
    month = month or today.month
    if period == "daily":
        start = datetime.combine(today, datetime.min.time())
        end = datetime.combine(today, datetime.max.time())
    elif period == "weekly":
        base = week_start or (today - timedelta(days=today.weekday()))
        start = datetime.combine(base, datetime.min.time())
        end = datetime.combine(base + timedelta(days=6), datetime.max.time())
    elif period == "monthly":
        start = datetime(year, month, 1)
        end = datetime(year, month, monthrange(year, month)[1], 23, 59, 59)
    elif period == "yearly":
        start = datetime(year, 1, 1)
        end = datetime(year, 12, 31, 23, 59, 59)
    else:
        raise ValueError("period must be daily, weekly, monthly, or yearly")
    return start, end


def _product_stats(db: Session, start: datetime, end: datetime, limit: int = 10) -> list[dict]:
    rows = (
        db.query(
            SaleItem.product_name,
            SaleItem.sku,
            func.sum(SaleItem.quantity).label("qty"),
            func.sum(SaleItem.line_total).label("amount"),
            func.sum((SaleItem.unit_price - SaleItem.cost_price) * SaleItem.quantity).label("profit"),
        )
        .join(Sale)
        .filter(Sale.sale_date >= start, Sale.sale_date <= end)
        .group_by(SaleItem.product_name, SaleItem.sku)
        .all()
    )
    items = [
        {
            "name": r.product_name,
            "sku": r.sku,
            "qty": float(r.qty or 0),
            "amount": float(r.amount or 0),
            "profit": float(r.profit or 0),
        }
        for r in rows
    ]
    return items


def product_performance(
    db: Session,
    period: str = "monthly",
    year: Optional[int] = None,
    month: Optional[int] = None,
    metric: str = "amount",
    limit: int = 10,
) -> dict:
    if metric not in {"amount", "qty", "profit"}:
        raise ValueError("metric must be amount, qty, or profit")
    start, end = _period_bounds(period if period in {"weekly", "monthly", "yearly"} else "monthly", year, month)
    items = _product_stats(db, start, end, limit=500)
    key = {"amount": "amount", "qty": "qty", "profit": "profit"}[metric]
    ranked = sorted(items, key=lambda x: x[key], reverse=True)[:limit]
    return {
        "period": period,
        "metric": metric,
        "start_date": start.date(),
        "end_date": end.date(),
        "year": start.year,
        "month": start.month,
        "items": ranked,
    }


def dashboard(
    db: Session,
    year: Optional[int] = None,
    month: Optional[int] = None,
) -> dict:
    today = date.today()
    year = year or today.year
    month = month or today.month
    month_start = datetime(year, month, 1)
    month_end = datetime(year, month, monthrange(year, month)[1], 23, 59, 59)
    year_start = datetime(year, 1, 1)
    year_end = datetime(year, 12, 31, 23, 59, 59)
    today_start = datetime.combine(today, datetime.min.time())
    week_start = today - timedelta(days=today.weekday())
    week_begin = datetime.combine(week_start, datetime.min.time())

    products = db.query(Product).filter(Product.is_active.is_(True)).all()
    low = [p for p in products if stock_status(p) == "low"]
    out = [p for p in products if stock_status(p) == "out"]

    inv_cost = sum((p.stock_qty or 0) * (p.cost_price or 0) for p in products)
    inv_retail = sum((p.stock_qty or 0) * (p.sell_price or 0) for p in products)

    def sales_sum(start: datetime, end: Optional[datetime] = None) -> tuple[float, int, float]:
        q = db.query(Sale).options(joinedload(Sale.items)).filter(Sale.sale_date >= start)
        if end:
            q = q.filter(Sale.sale_date <= end)
        rows = q.all()
        total = sum(s.total or 0 for s in rows)
        profit = 0.0
        for s in rows:
            for item in s.items:
                profit += (item.unit_price - item.cost_price) * item.quantity
        return total, len(rows), profit

    sales_today, tx_today, _ = sales_sum(today_start)
    sales_week, _, _ = sales_sum(week_begin)
    sales_month, tx_month, profit_month = sales_sum(month_start, month_end)
    sales_year, _, profit_year = sales_sum(year_start, year_end)

    top_month = sorted(
        _product_stats(db, month_start, month_end),
        key=lambda x: x["amount"],
        reverse=True,
    )[:10]
    top_year = sorted(
        _product_stats(db, year_start, year_end),
        key=lambda x: x["amount"],
        reverse=True,
    )[:10]
    top_profit_month = sorted(
        _product_stats(db, month_start, month_end),
        key=lambda x: x["profit"],
        reverse=True,
    )[:10]
    top_profit_year = sorted(
        _product_stats(db, year_start, year_end),
        key=lambda x: x["profit"],
        reverse=True,
    )[:10]

    recent = (
        db.query(Sale)
        .options(joinedload(Sale.customer), joinedload(Sale.items))
        .order_by(Sale.sale_date.desc())
        .limit(8)
        .all()
    )

    trend = []
    for i in range(5, -1, -1):
        # step back months from selected month
        m_idx = month - 1 - i
        y = year
        while m_idx < 0:
            m_idx += 12
            y -= 1
        m = m_idx + 1
        start = datetime(y, m, 1)
        end = datetime(y, m, monthrange(y, m)[1], 23, 59, 59)
        total = (
            db.query(func.coalesce(func.sum(Sale.total), 0.0))
            .filter(Sale.sale_date >= start, Sale.sale_date <= end)
            .scalar()
        )
        trend.append({"label": start.strftime("%b %Y"), "total": float(total or 0)})

    return {
        "shop_name": settings.shop_name,
        "selected_year": year,
        "selected_month": month,
        "total_products": len(products),
        "low_stock_count": len(low),
        "out_of_stock_count": len(out),
        "inventory_value_cost": round(inv_cost, 2),
        "inventory_value_retail": round(inv_retail, 2),
        "sales_today": round(sales_today, 2),
        "sales_week": round(sales_week, 2),
        "sales_month": round(sales_month, 2),
        "sales_year": round(sales_year, 2),
        "profit_month": round(profit_month, 2),
        "profit_year": round(profit_year, 2),
        "transactions_today": tx_today,
        "transactions_month": tx_month,
        "top_products": top_month[:5],
        "top_products_month": top_month,
        "top_products_year": top_year,
        "top_profit_month": top_profit_month,
        "top_profit_year": top_profit_year,
        "low_stock_items": [
            {
                "id": p.id,
                "sku": p.sku,
                "name": p.name,
                "stock_qty": p.stock_qty,
                "reorder_level": p.reorder_level,
                "status": stock_status(p),
            }
            for p in (out + low)[:12]
        ],
        "recent_sales": [
            {
                "id": s.id,
                "invoice_no": s.invoice_no,
                "sale_date": s.sale_date.isoformat(),
                "total": s.total,
                "customer": s.customer.name if s.customer else "Walk-in",
                "items": len(s.items),
            }
            for s in recent
        ],
        "monthly_trend": trend,
    }


def period_report(
    db: Session,
    period: str,
    year: Optional[int] = None,
    month: Optional[int] = None,
) -> dict:
    start, end = _period_bounds(period, year, month)
    sales = (
        db.query(Sale)
        .options(joinedload(Sale.items).joinedload(SaleItem.product).joinedload(Product.category))
        .filter(Sale.sale_date >= start, Sale.sale_date <= end)
        .all()
    )

    total_sales = sum(s.total or 0 for s in sales)
    total_cost = 0.0
    items_sold = 0.0
    by_day: dict[str, float] = {}
    by_month: dict[str, float] = {}
    by_category: dict[str, float] = {}
    by_payment: dict[str, float] = {}
    product_map: dict[str, dict] = {}

    for sale in sales:
        day_key = sale.sale_date.strftime("%Y-%m-%d")
        month_key = sale.sale_date.strftime("%Y-%m")
        by_day[day_key] = by_day.get(day_key, 0) + (sale.total or 0)
        by_month[month_key] = by_month.get(month_key, 0) + (sale.total or 0)
        by_payment[sale.payment_method] = by_payment.get(sale.payment_method, 0) + (sale.total or 0)
        for item in sale.items:
            total_cost += (item.cost_price or 0) * item.quantity
            items_sold += item.quantity
            cat = "Uncategorized"
            if item.product and item.product.category:
                cat = item.product.category.name
            by_category[cat] = by_category.get(cat, 0) + item.line_total
            key = item.product_name
            if key not in product_map:
                product_map[key] = {"name": key, "qty": 0.0, "amount": 0.0, "profit": 0.0}
            product_map[key]["qty"] += item.quantity
            product_map[key]["amount"] += item.line_total
            product_map[key]["profit"] += (item.unit_price - item.cost_price) * item.quantity

    top_products = sorted(product_map.values(), key=lambda x: x["amount"], reverse=True)[:15]

    return {
        "period": period,
        "start_date": start.date(),
        "end_date": end.date(),
        "total_sales": round(total_sales, 2),
        "total_cost": round(total_cost, 2),
        "gross_profit": round(total_sales - total_cost, 2),
        "transaction_count": len(sales),
        "items_sold": items_sold,
        "by_day": [{"date": k, "total": round(v, 2)} for k, v in sorted(by_day.items())],
        "by_month": [{"month": k, "total": round(v, 2)} for k, v in sorted(by_month.items())],
        "by_category": [
            {"category": k, "total": round(v, 2)}
            for k, v in sorted(by_category.items(), key=lambda x: -x[1])
        ],
        "by_payment": [{"method": k, "total": round(v, 2)} for k, v in by_payment.items()],
        "top_products": top_products,
    }


def inventory_report(db: Session) -> dict:
    products = (
        db.query(Product)
        .options(joinedload(Product.category))
        .filter(Product.is_active.is_(True))
        .all()
    )
    value_cost = sum((p.stock_qty or 0) * (p.cost_price or 0) for p in products)
    value_retail = sum((p.stock_qty or 0) * (p.sell_price or 0) for p in products)
    total_units = sum(p.stock_qty or 0 for p in products)

    by_category: dict[str, dict] = {}
    low_stock = []
    for p in products:
        cat = p.category.name if p.category else "Uncategorized"
        if cat not in by_category:
            by_category[cat] = {"category": cat, "skus": 0, "units": 0.0, "value_cost": 0.0}
        by_category[cat]["skus"] += 1
        by_category[cat]["units"] += p.stock_qty or 0
        by_category[cat]["value_cost"] += (p.stock_qty or 0) * (p.cost_price or 0)
        status = stock_status(p)
        if status in {"low", "out"}:
            low_stock.append({
                "id": p.id,
                "sku": p.sku,
                "name": p.name,
                "category": cat,
                "stock_qty": p.stock_qty,
                "reorder_level": p.reorder_level,
                "status": status,
                "cost_price": p.cost_price,
                "sell_price": p.sell_price,
            })

    movements = (
        db.query(StockMovement)
        .options(joinedload(StockMovement.product))
        .order_by(StockMovement.created_at.desc())
        .limit(50)
        .all()
    )

    return {
        "total_skus": len(products),
        "total_units": total_units,
        "value_at_cost": round(value_cost, 2),
        "value_at_retail": round(value_retail, 2),
        "low_stock": low_stock,
        "by_category": list(by_category.values()),
        "movements": [
            {
                "id": m.id,
                "product": m.product.name if m.product else None,
                "sku": m.product.sku if m.product else None,
                "type": m.movement_type,
                "change": m.quantity_change,
                "before": m.stock_before,
                "after": m.stock_after,
                "reference": m.reference,
                "created_at": m.created_at.isoformat(),
            }
            for m in movements
        ],
    }
