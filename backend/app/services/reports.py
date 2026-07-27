from calendar import monthrange
from datetime import datetime, date, timedelta
from typing import Optional

from sqlalchemy import func, extract, case
from sqlalchemy.orm import Session, joinedload

from app.core.config import settings
from app.models.models import Product, Sale, SaleItem, Category, StockMovement
from app.services.stock import stock_status


def _period_bounds(period: str, year: Optional[int] = None, month: Optional[int] = None):
    today = date.today()
    year = year or today.year
    month = month or today.month
    if period == "daily":
        start = datetime.combine(today, datetime.min.time())
        end = datetime.combine(today, datetime.max.time())
    elif period == "monthly":
        start = datetime(year, month, 1)
        end = datetime(year, month, monthrange(year, month)[1], 23, 59, 59)
    elif period == "yearly":
        start = datetime(year, 1, 1)
        end = datetime(year, 12, 31, 23, 59, 59)
    else:
        raise ValueError("period must be daily, monthly, or yearly")
    return start, end


def dashboard(db: Session) -> dict:
    today = date.today()
    month_start = datetime(today.year, today.month, 1)
    year_start = datetime(today.year, 1, 1)
    today_start = datetime.combine(today, datetime.min.time())

    products = db.query(Product).filter(Product.is_active.is_(True)).all()
    low = [p for p in products if stock_status(p) == "low"]
    out = [p for p in products if stock_status(p) == "out"]

    inv_cost = sum((p.stock_qty or 0) * (p.cost_price or 0) for p in products)
    inv_retail = sum((p.stock_qty or 0) * (p.sell_price or 0) for p in products)

    def sales_sum(start: datetime) -> tuple[float, int, float]:
        rows = (
            db.query(Sale)
            .options(joinedload(Sale.items))
            .filter(Sale.sale_date >= start)
            .all()
        )
        total = sum(s.total or 0 for s in rows)
        profit = 0.0
        for s in rows:
            for item in s.items:
                profit += (item.unit_price - item.cost_price) * item.quantity
        return total, len(rows), profit

    sales_today, tx_today, _ = sales_sum(today_start)
    sales_month, tx_month, profit_month = sales_sum(month_start)
    sales_year, _, _ = sales_sum(year_start)

    top = (
        db.query(
            SaleItem.product_name,
            func.sum(SaleItem.quantity).label("qty"),
            func.sum(SaleItem.line_total).label("amount"),
        )
        .join(Sale)
        .filter(Sale.sale_date >= month_start)
        .group_by(SaleItem.product_name)
        .order_by(func.sum(SaleItem.line_total).desc())
        .limit(5)
        .all()
    )

    recent = (
        db.query(Sale)
        .options(joinedload(Sale.customer), joinedload(Sale.items))
        .order_by(Sale.sale_date.desc())
        .limit(8)
        .all()
    )

    # last 6 months trend
    trend = []
    for i in range(5, -1, -1):
        mdate = (today.replace(day=1) - timedelta(days=i * 28)).replace(day=1)
        # normalize month
        y, m = mdate.year, mdate.month
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
        "total_products": len(products),
        "low_stock_count": len(low),
        "out_of_stock_count": len(out),
        "inventory_value_cost": round(inv_cost, 2),
        "inventory_value_retail": round(inv_retail, 2),
        "sales_today": round(sales_today, 2),
        "sales_month": round(sales_month, 2),
        "sales_year": round(sales_year, 2),
        "profit_month": round(profit_month, 2),
        "transactions_today": tx_today,
        "transactions_month": tx_month,
        "top_products": [
            {"name": r.product_name, "qty": float(r.qty or 0), "amount": float(r.amount or 0)}
            for r in top
        ],
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
                product_map[key] = {"name": key, "qty": 0.0, "amount": 0.0}
            product_map[key]["qty"] += item.quantity
            product_map[key]["amount"] += item.line_total

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
        "by_category": [{"category": k, "total": round(v, 2)} for k, v in sorted(by_category.items(), key=lambda x: -x[1])],
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