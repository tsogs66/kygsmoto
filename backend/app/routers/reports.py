"""Sales, profit, inventory and cashier reporting."""
import csv
import io
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from .. import db
from ..security import require
from ..services import analytics

router = APIRouter(prefix="/api/reports", tags=["reports"])


def _range(date_from, date_to, default_days=30):
    end = date.fromisoformat(date_to) if date_to else date.today()
    start = date.fromisoformat(date_from) if date_from else end - timedelta(days=default_days - 1)
    return start.isoformat(), end.isoformat()


@router.get("/dashboard")
def dashboard(user=Depends(require("reports.view"))):
    """Today / this month at a glance, plus a 30-day trend line."""
    today = date.today().isoformat()
    month_start = date.today().replace(day=1).isoformat()

    def totals(clause, params):
        row = db.query_one(
            f"""SELECT COUNT(*) AS receipts,
                       COALESCE(SUM(total), 0) AS sales,
                       COALESCE(SUM(parts_total), 0) AS parts,
                       COALESCE(SUM(labor_total), 0) AS labor,
                       COALESCE(SUM(profit), 0) AS profit,
                       COALESCE(SUM(discount), 0) AS discount
                  FROM sales WHERE status = 'completed' AND {clause}""",
            params,
        )
        data = {k: round(float(row[k] or 0), 2) for k in row.keys()}
        data["receipts"] = int(row["receipts"])
        data["average_sale"] = round(data["sales"] / data["receipts"], 2) if data["receipts"] else 0
        return data

    trend = db.query(
        """SELECT business_date AS d, SUM(total) AS sales, SUM(profit) AS profit,
                  COUNT(*) AS receipts
             FROM sales
            WHERE status = 'completed' AND business_date >= date('now', '-29 days')
         GROUP BY business_date ORDER BY business_date"""
    )
    stock = db.query_one(
        """SELECT COUNT(*) AS skus, COALESCE(SUM(stock_qty * unit_cost), 0) AS cost_value,
                  COALESCE(SUM(stock_qty * retail_price), 0) AS retail_value,
                  COALESCE(SUM(CASE WHEN stock_qty <= 0 THEN 1 ELSE 0 END), 0) AS out_of_stock,
                  COALESCE(SUM(CASE WHEN stock_qty <= reorder_point THEN 1 ELSE 0 END), 0) AS critical
             FROM items WHERE active = 1 AND delisted = 0"""
    )
    return {
        "today": totals("business_date = ?", (today,)),
        "month": totals("business_date >= ?", (month_start,)),
        "stock": {
            "skus": int(stock["skus"]),
            "cost_value": round(float(stock["cost_value"]), 2),
            "retail_value": round(float(stock["retail_value"]), 2),
            "potential_margin": round(
                float(stock["retail_value"]) - float(stock["cost_value"]), 2
            ),
            "out_of_stock": int(stock["out_of_stock"]),
            "critical": int(stock["critical"]),
        },
        "trend": [
            {"date": r["d"], "sales": round(float(r["sales"]), 2),
             "profit": round(float(r["profit"]), 2), "receipts": r["receipts"]}
            for r in trend
        ],
    }


@router.get("/sales-summary")
def sales_summary(
    date_from: str | None = None,
    date_to: str | None = None,
    group_by: str = Query(default="day", pattern="^(day|week|month)$"),
    user=Depends(require("reports.view")),
):
    start, end = _range(date_from, date_to)
    bucket = {
        "day": "business_date",
        "week": "strftime('%Y-W%W', business_date)",
        "month": "strftime('%Y-%m', business_date)",
    }[group_by]

    rows = db.query(
        f"""SELECT {bucket} AS period, COUNT(*) AS receipts,
                   SUM(total) AS sales, SUM(parts_total) AS parts, SUM(labor_total) AS labor,
                   SUM(cost_total) AS cost, SUM(profit) AS profit, SUM(discount) AS discount
              FROM sales
             WHERE status = 'completed' AND business_date BETWEEN ? AND ?
          GROUP BY period ORDER BY period""",
        (start, end),
    )
    periods = [
        {
            "period": r["period"], "receipts": r["receipts"],
            "sales": round(float(r["sales"] or 0), 2),
            "parts": round(float(r["parts"] or 0), 2),
            "labor": round(float(r["labor"] or 0), 2),
            "cost": round(float(r["cost"] or 0), 2),
            "profit": round(float(r["profit"] or 0), 2),
            "discount": round(float(r["discount"] or 0), 2),
            "margin_pct": round(float(r["profit"] or 0) / float(r["sales"]) * 100, 1)
                          if float(r["sales"] or 0) > 0 else 0.0,
        }
        for r in rows
    ]
    totals = {
        key: round(sum(p[key] for p in periods), 2)
        for key in ("sales", "parts", "labor", "cost", "profit", "discount")
    }
    totals["receipts"] = sum(p["receipts"] for p in periods)
    totals["margin_pct"] = (
        round(totals["profit"] / totals["sales"] * 100, 1) if totals["sales"] > 0 else 0.0
    )
    return {"range": {"from": start, "to": end}, "group_by": group_by,
            "periods": periods, "totals": totals}


@router.get("/top-items")
def top_items(
    date_from: str | None = None,
    date_to: str | None = None,
    by: str = Query(default="revenue", pattern="^(revenue|qty|profit)$"),
    limit: int = Query(default=25, le=200),
    user=Depends(require("reports.view")),
):
    start, end = _range(date_from, date_to)
    order = {"revenue": "revenue", "qty": "qty", "profit": "profit"}[by]
    rows = db.query(
        f"""SELECT l.item_id, l.sku, l.description, l.line_type,
                   SUM(l.qty) AS qty, SUM(l.total) AS revenue, SUM(l.profit) AS profit
              FROM sale_lines l JOIN sales s ON s.id = l.sale_id
             WHERE s.status = 'completed' AND s.business_date BETWEEN ? AND ?
          GROUP BY l.item_id, l.service_id, l.description
          ORDER BY {order} DESC LIMIT ?""",
        (start, end, limit),
    )
    return {
        "range": {"from": start, "to": end},
        "by": by,
        "items": [
            {**dict(r), "qty": round(float(r["qty"]), 2),
             "revenue": round(float(r["revenue"]), 2),
             "profit": round(float(r["profit"]), 2)}
            for r in rows
        ],
    }


@router.get("/category-performance")
def category_performance(date_from: str | None = None, date_to: str | None = None,
                         user=Depends(require("reports.view"))):
    start, end = _range(date_from, date_to)
    rows = db.query(
        """SELECT COALESCE(c.name, 'UNCATEGORISED') AS category,
                  SUM(l.qty) AS qty, SUM(l.total) AS revenue, SUM(l.profit) AS profit
             FROM sale_lines l
             JOIN sales s ON s.id = l.sale_id
             LEFT JOIN items i ON i.id = l.item_id
             LEFT JOIN categories c ON c.id = i.category_id
            WHERE s.status = 'completed' AND l.line_type = 'item'
              AND s.business_date BETWEEN ? AND ?
         GROUP BY category ORDER BY revenue DESC""",
        (start, end),
    )
    stock = {
        r["category"]: round(float(r["value"] or 0), 2)
        for r in db.query(
            """SELECT COALESCE(c.name, 'UNCATEGORISED') AS category,
                      SUM(i.stock_qty * i.unit_cost) AS value
                 FROM items i LEFT JOIN categories c ON c.id = i.category_id
                WHERE i.active = 1 AND i.delisted = 0 GROUP BY category"""
        )
    }
    return {
        "range": {"from": start, "to": end},
        "categories": [
            {
                "category": r["category"],
                "qty": round(float(r["qty"] or 0), 2),
                "revenue": round(float(r["revenue"] or 0), 2),
                "profit": round(float(r["profit"] or 0), 2),
                "stock_value": stock.get(r["category"], 0.0),
            }
            for r in rows
        ],
    }


@router.get("/inventory-valuation")
def inventory_valuation(user=Depends(require("reports.financial"))):
    rows = db.query(
        """SELECT COALESCE(c.name, 'UNCATEGORISED') AS category,
                  COUNT(*) AS skus, SUM(i.stock_qty) AS units,
                  SUM(i.stock_qty * i.unit_cost) AS cost_value,
                  SUM(i.stock_qty * i.retail_price) AS retail_value
             FROM items i LEFT JOIN categories c ON c.id = i.category_id
            WHERE i.active = 1 AND i.delisted = 0
         GROUP BY category ORDER BY cost_value DESC"""
    )
    categories = [
        {
            "category": r["category"], "skus": r["skus"],
            "units": round(float(r["units"] or 0), 2),
            "cost_value": round(float(r["cost_value"] or 0), 2),
            "retail_value": round(float(r["retail_value"] or 0), 2),
            "potential_margin": round(
                float(r["retail_value"] or 0) - float(r["cost_value"] or 0), 2
            ),
        }
        for r in rows
    ]
    return {
        "categories": categories,
        "totals": {
            "skus": sum(c["skus"] for c in categories),
            "units": round(sum(c["units"] for c in categories), 2),
            "cost_value": round(sum(c["cost_value"] for c in categories), 2),
            "retail_value": round(sum(c["retail_value"] for c in categories), 2),
            "potential_margin": round(sum(c["potential_margin"] for c in categories), 2),
        },
    }


@router.get("/profit-and-loss")
def profit_and_loss(date_from: str | None = None, date_to: str | None = None,
                    user=Depends(require("reports.financial"))):
    """Trading account for the period: parts margin plus labour income."""
    start, end = _range(date_from, date_to)
    row = db.query_one(
        """SELECT COALESCE(SUM(parts_total), 0) AS parts,
                  COALESCE(SUM(labor_total), 0) AS labor,
                  COALESCE(SUM(cost_total), 0) AS cogs,
                  COALESCE(SUM(discount), 0) AS discounts,
                  COALESCE(SUM(total), 0) AS net_sales,
                  COUNT(*) AS receipts
             FROM sales WHERE status = 'completed' AND business_date BETWEEN ? AND ?""",
        (start, end),
    )
    parts = round(float(row["parts"]), 2)
    labor = round(float(row["labor"]), 2)
    cogs = round(float(row["cogs"]), 2)
    net_sales = round(float(row["net_sales"]), 2)
    gross_profit = round(parts - cogs, 2)

    purchases = db.query_one(
        """SELECT COALESCE(SUM(m.qty_delta * m.unit_cost), 0) AS v
             FROM stock_moves m
            WHERE m.move_type = 'purchase' AND date(m.ts) BETWEEN ? AND ?""",
        (start, end),
    )["v"]

    return {
        "range": {"from": start, "to": end},
        "receipts": int(row["receipts"]),
        "parts_sales": parts,
        "service_income": labor,
        "discounts_given": round(float(row["discounts"]), 2),
        "net_sales": net_sales,
        "cost_of_goods_sold": cogs,
        "gross_profit_on_parts": gross_profit,
        "total_gross_profit": round(gross_profit + labor, 2),
        "gross_margin_pct": round((gross_profit + labor) / net_sales * 100, 1)
                            if net_sales > 0 else 0.0,
        "stock_purchased": round(float(purchases), 2),
    }


@router.get("/cashier")
def cashier_report(date_from: str | None = None, date_to: str | None = None,
                   user=Depends(require("reports.view"))):
    """Per-cashier takings and tender breakdown — the shift (X/Z) read."""
    start, end = _range(date_from, date_to, default_days=1)
    rows = db.query(
        """SELECT u.id, u.username, u.full_name, COUNT(*) AS receipts,
                  SUM(s.total) AS sales, SUM(s.discount) AS discounts, SUM(s.profit) AS profit
             FROM sales s JOIN users u ON u.id = s.user_id
            WHERE s.status = 'completed' AND s.business_date BETWEEN ? AND ?
         GROUP BY u.id ORDER BY sales DESC""",
        (start, end),
    )
    tenders = db.query(
        """SELECT p.method, SUM(p.amount) AS amount, COUNT(*) AS count
             FROM payments p JOIN sales s ON s.id = p.sale_id
            WHERE s.status = 'completed' AND s.business_date BETWEEN ? AND ?
         GROUP BY p.method ORDER BY amount DESC""",
        (start, end),
    )
    voids = db.query(
        """SELECT s.receipt_no, s.total, s.void_reason, u.username AS voided_by, s.voided_at
             FROM sales s LEFT JOIN users u ON u.id = s.voided_by
            WHERE s.status = 'voided' AND s.business_date BETWEEN ? AND ?
         ORDER BY s.id DESC""",
        (start, end),
    )
    return {
        "range": {"from": start, "to": end},
        "cashiers": [
            {**dict(r), "sales": round(float(r["sales"] or 0), 2),
             "discounts": round(float(r["discounts"] or 0), 2),
             "profit": round(float(r["profit"] or 0), 2)}
            for r in rows
        ],
        "tenders": [
            {"method": t["method"], "amount": round(float(t["amount"]), 2),
             "count": t["count"]}
            for t in tenders
        ],
        "voids": [dict(v) for v in voids],
    }


@router.get("/export/{dataset}")
def export_csv(
    dataset: str,
    date_from: str | None = None,
    date_to: str | None = None,
    days: int = 90,
    user=Depends(require("reports.view")),
):
    """Download any core dataset as CSV for Excel or the accountant."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)

    if dataset == "inventory":
        writer.writerow(["SKU", "Description", "Category", "Supplier", "Unit Cost",
                         "Retail Price", "Stock Qty", "Stock Value", "Reorder Point"])
        for r in db.query(
            """SELECT i.sku, i.description, COALESCE(c.name,'') AS category,
                      COALESCE(s.code,'') AS supplier, i.unit_cost, i.retail_price,
                      i.stock_qty, i.reorder_point
                 FROM items i
                 LEFT JOIN categories c ON c.id = i.category_id
                 LEFT JOIN suppliers s ON s.id = i.supplier_id
                WHERE i.active = 1 AND i.delisted = 0 ORDER BY i.description"""
        ):
            writer.writerow([
                r["sku"], r["description"], r["category"], r["supplier"],
                r["unit_cost"], r["retail_price"], r["stock_qty"],
                round(float(r["stock_qty"]) * float(r["unit_cost"]), 2), r["reorder_point"],
            ])

    elif dataset == "sales":
        start, end = _range(date_from, date_to)
        writer.writerow(["Receipt", "Date", "Cashier", "Customer", "Item Code",
                         "Description", "Qty", "Price", "Discount", "Total", "Profit"])
        for r in db.query(
            """SELECT s.receipt_no, s.business_date, u.username, s.customer_name,
                      l.sku, l.description, l.qty, l.unit_price, l.discount, l.total, l.profit
                 FROM sale_lines l
                 JOIN sales s ON s.id = l.sale_id
                 JOIN users u ON u.id = s.user_id
                WHERE s.status = 'completed' AND s.business_date BETWEEN ? AND ?
             ORDER BY s.id, l.id""",
            (start, end),
        ):
            writer.writerow(list(r))

    elif dataset == "reorder":
        rows, _, _ = analytics.reorder_suggestions(days=days)
        writer.writerow(["Urgency", "SKU", "Description", "Supplier", "On Hand", "On Order",
                         "Reorder Point", "Suggested Qty", "Unit Cost", "Order Cost",
                         "Days Cover", "Reason"])
        for r in rows:
            writer.writerow([
                r["urgency"], r["sku"], r["description"], r["supplier"], r["on_hand"],
                r["on_order"], r["reorder_point"], r["suggested_qty"], r["unit_cost"],
                r["order_cost"], r["days_of_cover"], r["reason"],
            ])

    elif dataset == "movers":
        rows, _, _ = analytics.analyze(days=days)
        rows.sort(key=lambda r: -r["daily_rate"])
        writer.writerow(["SKU", "Description", "Category", "Movement", "ABC-XYZ",
                         "Sold Qty", "Revenue", "Gross Profit", "Monthly Forecast",
                         "On Hand", "Days Cover"])
        for r in rows:
            writer.writerow([
                r["sku"], r["description"], r["category"], r["movement"], r["abc_xyz"],
                r["sold_qty"], r["revenue"], r["gross_profit"], r["monthly_rate"],
                r["on_hand"], r["days_of_cover"],
            ])
    else:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=404,
            detail="Unknown dataset. Use inventory, sales, reorder or movers.",
        )

    buffer.seek(0)
    filename = f"kygs-{dataset}-{date.today().isoformat()}.csv"
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
