from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.models.models import Product, StockMovement


def apply_stock_change(
    db: Session,
    product: Product,
    quantity_change: float,
    movement_type: str,
    reference: Optional[str] = None,
    notes: Optional[str] = None,
) -> StockMovement:
    before = float(product.stock_qty or 0)
    after = before + quantity_change
    product.stock_qty = after
    product.updated_at = datetime.utcnow()
    movement = StockMovement(
        product_id=product.id,
        movement_type=movement_type,
        quantity_change=quantity_change,
        stock_before=before,
        stock_after=after,
        reference=reference,
        notes=notes,
    )
    db.add(movement)
    return movement


def stock_status(product: Product) -> str:
    qty = float(product.stock_qty or 0)
    reorder = float(product.reorder_level or 0)
    if qty <= 0:
        return "out"
    if qty <= reorder:
        return "low"
    return "ok"