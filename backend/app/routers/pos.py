"""Point of sale: carts, tendering, receipts, voids and the cash drawer."""
import json
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import db
from ..security import audit, current_user, has_permission, require

router = APIRouter(prefix="/api/pos", tags=["pos"])


class CartLine(BaseModel):
    line_type: str = "item"          # "item" (stocked part) or "service" (labour)
    item_id: int | None = None
    service_id: int | None = None
    qty: float = Field(gt=0)
    unit_price: float | None = None  # Overrides the catalogue price when permitted.
    discount: float = 0              # Peso amount off this line.
    description: str | None = None   # Only used for ad-hoc service lines.


class PaymentIn(BaseModel):
    method: str = "CASH"
    amount: float
    reference: str = ""


class SaleIn(BaseModel):
    lines: list[CartLine]
    payments: list[PaymentIn] = []
    customer_name: str = ""
    plate_no: str = ""
    order_discount: float = 0
    amount_tendered: float = 0
    note: str = ""
    business_date: str | None = None
    allow_negative_stock: bool = False


class VoidIn(BaseModel):
    reason: str = Field(min_length=3)


class HoldIn(BaseModel):
    label: str = ""
    payload: dict


class DrawerOpen(BaseModel):
    opening_cash: float = 0
    note: str = ""


class DrawerClose(BaseModel):
    counted_cash: float
    note: str = ""


VALID_PAYMENT_METHODS = {"CASH", "GCASH", "BANK", "CARD", "CHARGE"}


def _next_receipt_no(business_date: str) -> str:
    """Sequential per-day receipt number, e.g. 20250425-0007."""
    stamp = business_date.replace("-", "")
    row = db.query_one(
        "SELECT receipt_no FROM sales WHERE receipt_no LIKE ? ORDER BY receipt_no DESC LIMIT 1",
        (f"{stamp}-%",),
    )
    nxt = int(row["receipt_no"].split("-")[1]) + 1 if row else 1
    return f"{stamp}-{nxt:04d}"


@router.post("/sales")
def create_sale(body: SaleIn, user=Depends(require("pos.sell"))):
    if not body.lines:
        raise HTTPException(status_code=400, detail="Cannot complete a sale with no lines")

    business_date = body.business_date or date.today().isoformat()
    discounting = body.order_discount > 0 or any(l.discount > 0 for l in body.lines)
    if discounting and not has_permission(user, "pos.discount"):
        raise HTTPException(
            status_code=403,
            detail="Your role cannot apply discounts — ask a manager to authorise this sale.",
        )

    for payment in body.payments:
        if payment.method.upper() not in VALID_PAYMENT_METHODS:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown payment method '{payment.method}'. "
                       f"Use one of {sorted(VALID_PAYMENT_METHODS)}.",
            )

    # Everything below is one atomic unit: stock must not move if tendering fails.
    with db.transaction():
        prepared, subtotal, cost_total = [], 0.0, 0.0
        parts_total, labor_total = 0.0, 0.0

        for line in body.lines:
            if line.line_type == "item":
                if not line.item_id:
                    raise HTTPException(status_code=400, detail="Item line is missing item_id")
                item = db.query_one("SELECT * FROM items WHERE id = ?", (line.item_id,))
                if item is None:
                    raise HTTPException(status_code=404,
                                        detail=f"Item {line.item_id} not found")
                if not item["active"]:
                    raise HTTPException(status_code=400,
                                        detail=f"{item['description']} is not active for sale")

                available = float(item["stock_qty"] or 0)
                if line.qty > available and not body.allow_negative_stock:
                    raise HTTPException(
                        status_code=409,
                        detail=f"Only {available:g} left of {item['description']} "
                               f"({item['sku']}) — you asked for {line.qty:g}.",
                    )

                unit_price = (
                    line.unit_price
                    if line.unit_price is not None and has_permission(user, "pos.discount")
                    else float(item["retail_price"] or 0)
                )
                unit_cost = float(item["unit_cost"] or 0)
                total = round(unit_price * line.qty - line.discount, 2)
                prepared.append({
                    "line_type": "item", "item_id": item["id"], "service_id": None,
                    "sku": item["sku"], "description": item["description"],
                    "qty": line.qty, "unit_price": unit_price, "unit_cost": unit_cost,
                    "discount": line.discount, "total": total,
                    "profit": round(total - unit_cost * line.qty, 2),
                    "balance_after": available - line.qty,
                })
                parts_total += total
                cost_total += unit_cost * line.qty

            elif line.line_type == "service":
                if line.service_id:
                    svc = db.query_one("SELECT * FROM services WHERE id = ?", (line.service_id,))
                    if svc is None:
                        raise HTTPException(status_code=404,
                                            detail=f"Service {line.service_id} not found")
                    name, fee, svc_id = svc["name"], float(svc["fee"] or 0), svc["id"]
                else:
                    if not line.description:
                        raise HTTPException(
                            status_code=400,
                            detail="A custom labour line needs a description",
                        )
                    name, fee, svc_id = line.description, 0.0, None

                unit_price = line.unit_price if line.unit_price is not None else fee
                total = round(unit_price * line.qty - line.discount, 2)
                prepared.append({
                    "line_type": "service", "item_id": None, "service_id": svc_id,
                    "sku": "", "description": name, "qty": line.qty,
                    "unit_price": unit_price, "unit_cost": 0.0,
                    "discount": line.discount, "total": total, "profit": total,
                    "balance_after": None,
                })
                labor_total += total
            else:
                raise HTTPException(status_code=400,
                                    detail=f"Unknown line type '{line.line_type}'")

            subtotal += prepared[-1]["total"]

        total_due = round(subtotal - body.order_discount, 2)
        if total_due < 0:
            raise HTTPException(status_code=400,
                                detail="Order discount is larger than the sale total")

        payments = body.payments or [
            PaymentIn(method="CASH", amount=total_due)
        ]
        paid = round(sum(p.amount for p in payments), 2)
        if paid + 0.005 < total_due:
            raise HTTPException(
                status_code=400,
                detail=f"Payments total {paid:.2f} but the sale is {total_due:.2f}",
            )

        tendered = body.amount_tendered or paid
        change_due = round(max(tendered - total_due, 0), 2)
        profit = round(total_due - cost_total, 2)
        receipt_no = _next_receipt_no(business_date)

        cur = db.execute(
            """INSERT INTO sales(receipt_no, business_date, user_id, customer_name, plate_no,
                                 subtotal, discount, total, parts_total, labor_total,
                                 cost_total, profit, amount_tendered, change_due, note)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (receipt_no, business_date, user["id"], body.customer_name.strip(),
             body.plate_no.strip().upper(), round(subtotal, 2), body.order_discount,
             total_due, round(parts_total, 2), round(labor_total, 2), round(cost_total, 2),
             profit, tendered, change_due, body.note),
        )
        sale_id = cur.lastrowid

        for line in prepared:
            db.execute(
                """INSERT INTO sale_lines(sale_id, line_type, item_id, service_id, sku,
                                          description, qty, unit_price, unit_cost, discount,
                                          total, profit)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (sale_id, line["line_type"], line["item_id"], line["service_id"], line["sku"],
                 line["description"], line["qty"], line["unit_price"], line["unit_cost"],
                 line["discount"], line["total"], line["profit"]),
            )
            if line["line_type"] == "item":
                db.execute(
                    "UPDATE items SET stock_qty = stock_qty - ?, updated_at = datetime('now') "
                    "WHERE id = ?",
                    (line["qty"], line["item_id"]),
                )
                db.execute(
                    """INSERT INTO stock_moves(item_id, qty_delta, balance_after, move_type,
                                               ref_type, ref_id, unit_cost, user_id, note)
                       VALUES(?,?,?,'sale','sale',?,?,?,?)""",
                    (line["item_id"], -line["qty"], line["balance_after"], sale_id,
                     line["unit_cost"], user["id"], receipt_no),
                )

        for payment in payments:
            db.execute(
                "INSERT INTO payments(sale_id, method, amount, reference) VALUES(?,?,?,?)",
                (sale_id, payment.method.upper(), payment.amount, payment.reference),
            )

    audit(user, "sale.completed", "sale", sale_id,
          {"receipt": receipt_no, "total": total_due, "lines": len(prepared)})
    return get_sale(sale_id, user)


@router.get("/sales")
def list_sales(
    date_from: str | None = None,
    date_to: str | None = None,
    user_id: int | None = None,
    status: str | None = None,
    q: str = "",
    limit: int = 100,
    offset: int = 0,
    user=Depends(require("reports.view")),
):
    where, params = ["1=1"], []
    if date_from:
        where.append("s.business_date >= ?")
        params.append(date_from)
    if date_to:
        where.append("s.business_date <= ?")
        params.append(date_to)
    if user_id:
        where.append("s.user_id = ?")
        params.append(user_id)
    if status:
        where.append("s.status = ?")
        params.append(status)
    if q:
        where.append("(s.receipt_no LIKE ? OR s.customer_name LIKE ? OR s.plate_no LIKE ?)")
        params += [f"%{q}%", f"%{q}%", f"%{q}%"]

    clause = " AND ".join(where)
    total = db.query_one(f"SELECT COUNT(*) AS n FROM sales s WHERE {clause}", tuple(params))["n"]
    rows = db.query(
        f"""SELECT s.*, u.username AS cashier
              FROM sales s JOIN users u ON u.id = s.user_id
             WHERE {clause}
          ORDER BY s.id DESC LIMIT ? OFFSET ?""",
        (*params, min(limit, 500), offset),
    )
    return {"total": total, "sales": [dict(r) for r in rows]}


@router.get("/sales/{sale_id}")
def get_sale(sale_id: int, user=Depends(require("reports.view"))):
    sale = db.query_one(
        "SELECT s.*, u.username AS cashier FROM sales s JOIN users u ON u.id = s.user_id "
        "WHERE s.id = ?",
        (sale_id,),
    )
    if sale is None:
        raise HTTPException(status_code=404, detail="Sale not found")
    lines = db.query("SELECT * FROM sale_lines WHERE sale_id = ? ORDER BY id", (sale_id,))
    pays = db.query("SELECT * FROM payments WHERE sale_id = ? ORDER BY id", (sale_id,))
    return {
        "sale": dict(sale),
        "lines": [dict(r) for r in lines],
        "payments": [dict(r) for r in pays],
        "shop": {
            "name": db.get_setting("shop_name", ""),
            "address": db.get_setting("shop_address", ""),
            "phone": db.get_setting("shop_phone", ""),
            "footer": db.get_setting("receipt_footer", ""),
            "currency_symbol": db.get_setting("currency_symbol", "P"),
        },
    }


@router.post("/sales/{sale_id}/void")
def void_sale(sale_id: int, body: VoidIn, user=Depends(require("pos.void"))):
    """Reverse a completed sale and return its parts to stock."""
    with db.transaction():
        sale = db.query_one("SELECT * FROM sales WHERE id = ?", (sale_id,))
        if sale is None:
            raise HTTPException(status_code=404, detail="Sale not found")
        if sale["status"] != "completed":
            raise HTTPException(status_code=400,
                                detail=f"Sale is already {sale['status']}")

        lines = db.query(
            "SELECT * FROM sale_lines WHERE sale_id = ? AND item_id IS NOT NULL", (sale_id,)
        )
        for line in lines:
            db.execute(
                "UPDATE items SET stock_qty = stock_qty + ?, updated_at = datetime('now') "
                "WHERE id = ?",
                (line["qty"], line["item_id"]),
            )
            balance = db.query_one(
                "SELECT stock_qty FROM items WHERE id = ?", (line["item_id"],)
            )["stock_qty"]
            db.execute(
                """INSERT INTO stock_moves(item_id, qty_delta, balance_after, move_type,
                                           ref_type, ref_id, unit_cost, user_id, note)
                   VALUES(?,?,?,'void','sale',?,?,?,?)""",
                (line["item_id"], line["qty"], balance, sale_id, line["unit_cost"],
                 user["id"], f"Void {sale['receipt_no']}: {body.reason}"),
            )

        db.execute(
            "UPDATE sales SET status = 'voided', voided_by = ?, voided_at = datetime('now'), "
            "void_reason = ? WHERE id = ?",
            (user["id"], body.reason, sale_id),
        )

    audit(user, "sale.voided", "sale", sale_id,
          {"receipt": sale["receipt_no"], "reason": body.reason, "total": sale["total"]})
    return get_sale(sale_id, user)


# ------------------------------------------------------------- held carts

@router.get("/holds")
def list_holds(user=Depends(require("pos.sell"))):
    rows = db.query(
        "SELECT h.*, u.username FROM held_carts h JOIN users u ON u.id = h.user_id "
        "ORDER BY h.id DESC"
    )
    return {"holds": [{**dict(r), "payload": json.loads(r["payload"])} for r in rows]}


@router.post("/holds")
def hold_cart(body: HoldIn, user=Depends(require("pos.sell"))):
    cur = db.execute(
        "INSERT INTO held_carts(user_id, label, payload) VALUES(?,?,?)",
        (user["id"], body.label.strip(), json.dumps(body.payload)),
    )
    return {"id": cur.lastrowid}


@router.delete("/holds/{hold_id}")
def drop_hold(hold_id: int, user=Depends(require("pos.sell"))):
    db.execute("DELETE FROM held_carts WHERE id = ?", (hold_id,))
    return {"ok": True}


# ------------------------------------------------------------ cash drawer

@router.get("/drawer")
def current_drawer(user=Depends(require("pos.sell"))):
    row = db.query_one(
        "SELECT d.*, u.username AS opened_by_name FROM cash_drawer d "
        "JOIN users u ON u.id = d.opened_by WHERE d.closed_at IS NULL "
        "ORDER BY d.id DESC LIMIT 1"
    )
    if row is None:
        return {"drawer": None}

    cash_in = db.query_one(
        """SELECT COALESCE(SUM(p.amount), 0) AS cash
             FROM payments p JOIN sales s ON s.id = p.sale_id
            WHERE p.method = 'CASH' AND s.status = 'completed' AND s.ts >= ?""",
        (row["opened_at"],),
    )["cash"]
    change_out = db.query_one(
        "SELECT COALESCE(SUM(change_due), 0) AS c FROM sales "
        "WHERE status = 'completed' AND ts >= ?",
        (row["opened_at"],),
    )["c"]

    expected = round(float(row["opening_cash"]) + float(cash_in) - float(change_out), 2)
    return {"drawer": {**dict(row), "cash_sales": round(float(cash_in), 2),
                       "change_given": round(float(change_out), 2),
                       "expected_cash": expected}}


@router.post("/drawer/open")
def open_drawer(body: DrawerOpen, user=Depends(require("pos.sell"))):
    if db.query_one("SELECT id FROM cash_drawer WHERE closed_at IS NULL"):
        raise HTTPException(status_code=409, detail="A drawer session is already open")
    cur = db.execute(
        "INSERT INTO cash_drawer(opened_by, opening_cash, note) VALUES(?,?,?)",
        (user["id"], body.opening_cash, body.note),
    )
    audit(user, "drawer.opened", "cash_drawer", cur.lastrowid,
          {"opening_cash": body.opening_cash})
    return current_drawer(user)


@router.post("/drawer/close")
def close_drawer(body: DrawerClose, user=Depends(require("pos.sell"))):
    state = current_drawer(user)["drawer"]
    if state is None:
        raise HTTPException(status_code=404, detail="No drawer session is open")

    expected = state["expected_cash"]
    variance = round(body.counted_cash - expected, 2)
    db.execute(
        "UPDATE cash_drawer SET closed_at = datetime('now'), closed_by = ?, counted_cash = ?, "
        "expected_cash = ?, variance = ?, note = ? WHERE id = ?",
        (user["id"], body.counted_cash, expected, variance, body.note, state["id"]),
    )
    audit(user, "drawer.closed", "cash_drawer", state["id"],
          {"expected": expected, "counted": body.counted_cash, "variance": variance})
    return {
        "id": state["id"],
        "expected_cash": expected,
        "counted_cash": body.counted_cash,
        "variance": variance,
        "status": "balanced" if abs(variance) < 0.01 else
                  ("over" if variance > 0 else "short"),
    }
