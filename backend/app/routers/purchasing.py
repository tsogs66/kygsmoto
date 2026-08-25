"""Purchase orders: raise, send, receive — including auto-built suggested orders."""
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import db
from ..security import audit, require
from ..services import analytics

router = APIRouter(prefix="/api/purchasing", tags=["purchasing"])


class POLineIn(BaseModel):
    item_id: int
    qty_ordered: float = Field(gt=0)
    unit_cost: float | None = None


class POIn(BaseModel):
    supplier_id: int
    lines: list[POLineIn]
    expected_at: str | None = None
    note: str = ""


class ReceiveLineIn(BaseModel):
    po_line_id: int
    qty_received: float = Field(ge=0)
    unit_cost: float | None = None


class ReceivePOIn(BaseModel):
    lines: list[ReceiveLineIn]
    note: str = ""


class AutoPOIn(BaseModel):
    supplier_id: int | None = None
    days: int = 90
    max_lines: int = 100
    min_urgency: float = 0


def _next_po_no() -> str:
    stamp = date.today().strftime("%Y%m")
    row = db.query_one(
        "SELECT po_no FROM purchase_orders WHERE po_no LIKE ? ORDER BY po_no DESC LIMIT 1",
        (f"PO{stamp}-%",),
    )
    nxt = int(row["po_no"].split("-")[1]) + 1 if row else 1
    return f"PO{stamp}-{nxt:03d}"


def _po_payload(po_id: int):
    po = db.query_one(
        """SELECT po.*, s.code AS supplier_code, s.name AS supplier_name,
                  s.lead_time_days, u.username AS created_by_name
             FROM purchase_orders po
             JOIN suppliers s ON s.id = po.supplier_id
             JOIN users u ON u.id = po.created_by
            WHERE po.id = ?""",
        (po_id,),
    )
    if po is None:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    lines = db.query(
        """SELECT pl.*, i.sku, i.description, i.stock_qty
             FROM po_lines pl JOIN items i ON i.id = pl.item_id
            WHERE pl.po_id = ? ORDER BY pl.id""",
        (po_id,),
    )
    return {"po": dict(po), "lines": [dict(r) for r in lines]}


@router.get("/orders")
def list_orders(status: str | None = None, supplier_id: int | None = None,
                limit: int = 100, user=Depends(require("purchasing.view"))):
    where, params = ["1=1"], []
    if status:
        where.append("po.status = ?")
        params.append(status)
    if supplier_id:
        where.append("po.supplier_id = ?")
        params.append(supplier_id)

    rows = db.query(
        f"""SELECT po.*, s.code AS supplier_code, u.username AS created_by_name,
                   (SELECT COUNT(*) FROM po_lines WHERE po_id = po.id) AS line_count
              FROM purchase_orders po
              JOIN suppliers s ON s.id = po.supplier_id
              JOIN users u ON u.id = po.created_by
             WHERE {' AND '.join(where)}
          ORDER BY po.id DESC LIMIT ?""",
        (*params, limit),
    )
    return {"orders": [dict(r) for r in rows]}


@router.get("/orders/{po_id}")
def get_order(po_id: int, user=Depends(require("purchasing.view"))):
    return _po_payload(po_id)


@router.post("/orders")
def create_order(body: POIn, user=Depends(require("purchasing.edit"))):
    if not body.lines:
        raise HTTPException(status_code=400, detail="A purchase order needs at least one line")
    if db.query_one("SELECT id FROM suppliers WHERE id = ?", (body.supplier_id,)) is None:
        raise HTTPException(status_code=404, detail="Supplier not found")

    with db.transaction():
        po_no = _next_po_no()
        cur = db.execute(
            """INSERT INTO purchase_orders(po_no, supplier_id, created_by, expected_at, note)
               VALUES(?,?,?,?,?)""",
            (po_no, body.supplier_id, user["id"], body.expected_at, body.note),
        )
        po_id = cur.lastrowid

        total = 0.0
        for line in body.lines:
            item = db.query_one("SELECT * FROM items WHERE id = ?", (line.item_id,))
            if item is None:
                raise HTTPException(status_code=404, detail=f"Item {line.item_id} not found")
            cost = line.unit_cost if line.unit_cost is not None else float(item["unit_cost"] or 0)
            db.execute(
                "INSERT INTO po_lines(po_id, item_id, qty_ordered, unit_cost) VALUES(?,?,?,?)",
                (po_id, line.item_id, line.qty_ordered, cost),
            )
            total += cost * line.qty_ordered

        db.execute("UPDATE purchase_orders SET total_cost = ? WHERE id = ?",
                   (round(total, 2), po_id))

    audit(user, "po.created", "purchase_order", po_id,
          {"po_no": po_no, "lines": len(body.lines), "total": round(total, 2)})
    return _po_payload(po_id)


@router.post("/orders/{po_id}/send")
def send_order(po_id: int, user=Depends(require("purchasing.edit"))):
    """Mark a draft as ordered; from here its quantities count as incoming stock."""
    po = db.query_one("SELECT * FROM purchase_orders WHERE id = ?", (po_id,))
    if po is None:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    if po["status"] != "draft":
        raise HTTPException(status_code=400, detail=f"Order is already {po['status']}")

    supplier = db.query_one("SELECT * FROM suppliers WHERE id = ?", (po["supplier_id"],))
    expected = po["expected_at"] or (
        date.today() + timedelta(days=float(supplier["lead_time_days"] or 7))
    ).isoformat()
    db.execute(
        "UPDATE purchase_orders SET status = 'ordered', ordered_at = datetime('now'), "
        "expected_at = ? WHERE id = ?",
        (expected, po_id),
    )
    audit(user, "po.sent", "purchase_order", po_id, {"po_no": po["po_no"]})
    return _po_payload(po_id)


@router.post("/orders/{po_id}/receive")
def receive_order(po_id: int, body: ReceivePOIn, user=Depends(require("purchasing.receive"))):
    """Book in a delivery against an order, supporting partial receipts."""
    with db.transaction():
        po = db.query_one("SELECT * FROM purchase_orders WHERE id = ?", (po_id,))
        if po is None:
            raise HTTPException(status_code=404, detail="Purchase order not found")
        if po["status"] in ("received", "cancelled"):
            raise HTTPException(status_code=400, detail=f"Order is already {po['status']}")

        for entry in body.lines:
            line = db.query_one(
                "SELECT * FROM po_lines WHERE id = ? AND po_id = ?", (entry.po_line_id, po_id)
            )
            if line is None:
                raise HTTPException(status_code=404,
                                    detail=f"Line {entry.po_line_id} is not on this order")
            if entry.qty_received <= 0:
                continue

            outstanding = float(line["qty_ordered"]) - float(line["qty_received"])
            if entry.qty_received > outstanding + 1e-9:
                raise HTTPException(
                    status_code=400,
                    detail=f"Only {outstanding:g} outstanding on that line, "
                           f"you entered {entry.qty_received:g}",
                )

            cost = entry.unit_cost if entry.unit_cost is not None else float(line["unit_cost"])
            item = db.query_one("SELECT * FROM items WHERE id = ?", (line["item_id"],))
            balance = float(item["stock_qty"] or 0) + entry.qty_received

            db.execute(
                "UPDATE items SET stock_qty = ?, unit_cost = ?, updated_at = datetime('now') "
                "WHERE id = ?",
                (balance, cost, line["item_id"]),
            )
            db.execute(
                """INSERT INTO stock_moves(item_id, qty_delta, balance_after, move_type,
                                           ref_type, ref_id, unit_cost, user_id, note)
                   VALUES(?,?,?,'purchase','purchase_order',?,?,?,?)""",
                (line["item_id"], entry.qty_received, balance, po_id, cost, user["id"],
                 f"{po['po_no']} {body.note}".strip()),
            )
            db.execute(
                "UPDATE po_lines SET qty_received = qty_received + ?, unit_cost = ? WHERE id = ?",
                (entry.qty_received, cost, line["id"]),
            )

        remaining = db.query_one(
            "SELECT COALESCE(SUM(qty_ordered - qty_received), 0) AS n FROM po_lines "
            "WHERE po_id = ?",
            (po_id,),
        )["n"]
        status = "received" if remaining <= 1e-9 else "partial"
        db.execute(
            "UPDATE purchase_orders SET status = ?, "
            "received_at = CASE WHEN ? = 'received' THEN datetime('now') ELSE received_at END "
            "WHERE id = ?",
            (status, status, po_id),
        )

    audit(user, "po.received", "purchase_order", po_id,
          {"po_no": po["po_no"], "status": status, "lines": len(body.lines)})
    return _po_payload(po_id)


@router.post("/orders/{po_id}/cancel")
def cancel_order(po_id: int, user=Depends(require("purchasing.edit"))):
    po = db.query_one("SELECT * FROM purchase_orders WHERE id = ?", (po_id,))
    if po is None:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    if po["status"] in ("received", "cancelled"):
        raise HTTPException(status_code=400, detail=f"Order is already {po['status']}")
    db.execute("UPDATE purchase_orders SET status = 'cancelled' WHERE id = ?", (po_id,))
    audit(user, "po.cancelled", "purchase_order", po_id, {"po_no": po["po_no"]})
    return _po_payload(po_id)


@router.post("/orders/auto")
def auto_order(body: AutoPOIn, user=Depends(require("purchasing.edit"))):
    """Turn the reorder suggestions straight into draft POs, one per supplier."""
    suggestions, _, _ = analytics.reorder_suggestions(
        days=body.days, supplier_id=body.supplier_id, only_needed=True
    )
    suggestions = [
        s for s in suggestions
        if s["suggested_qty"] > 0 and s["supplier_id"] and s["urgency"] >= body.min_urgency
    ][: body.max_lines]

    if not suggestions:
        raise HTTPException(
            status_code=400,
            detail="Nothing needs reordering right now for the selected filters.",
        )

    by_supplier = {}
    for row in suggestions:
        by_supplier.setdefault(row["supplier_id"], []).append(row)

    created = []
    for supplier_id, rows in by_supplier.items():
        payload = POIn(
            supplier_id=supplier_id,
            lines=[
                POLineIn(item_id=r["item_id"], qty_ordered=r["suggested_qty"],
                         unit_cost=r["unit_cost"])
                for r in rows
            ],
            note=f"Auto-generated from {body.days}-day demand forecast",
        )
        created.append(create_order(payload, user))

    return {"created": len(created), "orders": created}
