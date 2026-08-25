"""Stock adjustments, receiving without a PO, and physical stocktakes."""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from .. import db
from ..security import audit, require

router = APIRouter(prefix="/api/inventory", tags=["inventory"])

ADJUSTMENT_REASONS = {
    "damaged", "lost", "expired", "found", "correction",
    "customer_return", "supplier_return", "internal_use",
}


class AdjustIn(BaseModel):
    item_id: int
    qty_delta: float = Field(description="Positive adds stock, negative removes it")
    reason: str
    note: str = ""


class StocktakeLine(BaseModel):
    item_id: int
    counted_qty: float


class StocktakeIn(BaseModel):
    lines: list[StocktakeLine]
    note: str = ""


class ReceiveLine(BaseModel):
    item_id: int
    qty: float = Field(gt=0)
    unit_cost: float | None = None


class ReceiveIn(BaseModel):
    supplier_id: int | None = None
    lines: list[ReceiveLine]
    reference: str = ""
    note: str = ""


def _apply_move(item_id, qty_delta, move_type, user, unit_cost=None, note="",
                ref_type="", ref_id=None):
    """Move stock and write the ledger entry. Caller owns the transaction."""
    item = db.query_one("SELECT * FROM items WHERE id = ?", (item_id,))
    if item is None:
        raise HTTPException(status_code=404, detail=f"Item {item_id} not found")

    balance = float(item["stock_qty"] or 0) + qty_delta
    db.execute(
        "UPDATE items SET stock_qty = ?, updated_at = datetime('now') WHERE id = ?",
        (balance, item_id),
    )
    db.execute(
        """INSERT INTO stock_moves(item_id, qty_delta, balance_after, move_type, ref_type,
                                   ref_id, unit_cost, user_id, note)
           VALUES(?,?,?,?,?,?,?,?,?)""",
        (item_id, qty_delta, balance, move_type, ref_type, ref_id,
         unit_cost if unit_cost is not None else item["unit_cost"], user["id"], note),
    )
    return item, balance


@router.post("/adjust")
def adjust_stock(body: AdjustIn, user=Depends(require("inventory.adjust"))):
    if body.reason not in ADJUSTMENT_REASONS:
        raise HTTPException(
            status_code=400,
            detail=f"Reason must be one of {sorted(ADJUSTMENT_REASONS)}",
        )
    if body.qty_delta == 0:
        raise HTTPException(status_code=400, detail="Adjustment quantity cannot be zero")

    with db.transaction():
        item, balance = _apply_move(
            body.item_id, body.qty_delta, "adjustment", user,
            note=f"{body.reason}: {body.note}".strip(": "),
        )
        if balance < 0:
            raise HTTPException(
                status_code=409,
                detail=f"That adjustment would leave {item['description']} at {balance:g}. "
                       "Stock cannot go negative — record a stocktake instead.",
            )

    audit(user, "stock.adjusted", "item", body.item_id,
          {"sku": item["sku"], "delta": body.qty_delta, "reason": body.reason,
           "balance": balance})
    return {"item_id": body.item_id, "sku": item["sku"], "balance": balance}


@router.post("/receive")
def receive_stock(body: ReceiveIn, user=Depends(require("purchasing.receive"))):
    """Book in a delivery that arrived without a purchase order raised first."""
    if not body.lines:
        raise HTTPException(status_code=400, detail="Nothing to receive")

    received = []
    with db.transaction():
        for line in body.lines:
            item, balance = _apply_move(
                line.item_id, line.qty, "purchase", user, unit_cost=line.unit_cost,
                note=f"Direct receipt {body.reference}".strip(),
            )
            if line.unit_cost is not None and line.unit_cost != item["unit_cost"]:
                # Latest landed cost becomes the new valuation cost.
                db.execute(
                    "UPDATE items SET unit_cost = ?, updated_at = datetime('now') WHERE id = ?",
                    (line.unit_cost, line.item_id),
                )
            received.append({"item_id": line.item_id, "sku": item["sku"], "balance": balance})

    audit(user, "stock.received", "receipt", body.reference or "-",
          {"lines": len(received), "supplier_id": body.supplier_id})
    return {"received": received}


@router.post("/stocktake")
def stocktake(body: StocktakeIn, user=Depends(require("inventory.stocktake"))):
    """Reconcile system stock to a physical count, logging every variance."""
    if not body.lines:
        raise HTTPException(status_code=400, detail="No counted lines supplied")

    variances = []
    with db.transaction():
        for line in body.lines:
            item = db.query_one("SELECT * FROM items WHERE id = ?", (line.item_id,))
            if item is None:
                raise HTTPException(status_code=404, detail=f"Item {line.item_id} not found")

            delta = line.counted_qty - float(item["stock_qty"] or 0)
            if delta == 0:
                continue
            _apply_move(
                line.item_id, delta, "stocktake", user,
                note=f"Counted {line.counted_qty:g}, system {item['stock_qty']:g}. {body.note}",
            )
            variances.append({
                "item_id": item["id"], "sku": item["sku"], "description": item["description"],
                "system_qty": float(item["stock_qty"] or 0), "counted_qty": line.counted_qty,
                "variance": delta, "value_impact": round(delta * float(item["unit_cost"] or 0), 2),
            })

    audit(user, "stock.stocktake", "stocktake", "-",
          {"counted": len(body.lines), "variances": len(variances),
           "value_impact": round(sum(v["value_impact"] for v in variances), 2)})
    return {
        "counted": len(body.lines),
        "variances": variances,
        "total_value_impact": round(sum(v["value_impact"] for v in variances), 2),
    }


@router.get("/moves")
def list_moves(
    item_id: int | None = None,
    move_type: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = Query(default=200, le=1000),
    user=Depends(require("inventory.view")),
):
    where, params = ["1=1"], []
    if item_id:
        where.append("m.item_id = ?")
        params.append(item_id)
    if move_type:
        where.append("m.move_type = ?")
        params.append(move_type)
    if date_from:
        where.append("date(m.ts) >= ?")
        params.append(date_from)
    if date_to:
        where.append("date(m.ts) <= ?")
        params.append(date_to)

    rows = db.query(
        f"""SELECT m.*, i.sku, i.description, u.username
              FROM stock_moves m
              JOIN items i ON i.id = m.item_id
              LEFT JOIN users u ON u.id = m.user_id
             WHERE {' AND '.join(where)}
          ORDER BY m.id DESC LIMIT ?""",
        (*params, limit),
    )
    return {"moves": [dict(r) for r in rows]}


@router.get("/low-stock")
def low_stock(user=Depends(require("inventory.view"))):
    """Items at or below their configured reorder point — the CRITICAL list."""
    rows = db.query(
        """SELECT i.*, c.name AS category, s.code AS supplier
             FROM items i
             LEFT JOIN categories c ON c.id = i.category_id
             LEFT JOIN suppliers s ON s.id = i.supplier_id
            WHERE i.active = 1 AND i.delisted = 0 AND i.stock_qty <= i.reorder_point
         ORDER BY (i.stock_qty - i.reorder_point), i.description"""
    )
    out = []
    for row in rows:
        entry = dict(row)
        entry["status"] = "OUT OF STOCK" if row["stock_qty"] <= 0 else "CRITICAL"
        entry["shortfall"] = round(
            max(float(row["reorder_point"] or 0) - float(row["stock_qty"] or 0), 0), 2
        )
        out.append(entry)
    return {"count": len(out), "items": out}
