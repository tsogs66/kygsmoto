"""Stock reserved by baskets parked at the till.

A held sale is a promise: the rider has gone to the ATM, and the parts in
that basket are spoken for. Reserving them means a second cashier cannot
quietly sell the last chain kit out from under the first.

The reservation is *derived* from the hold lines themselves rather than
stored as a counter on the product. There is nothing to keep in step, so
nothing can drift: delete a hold and its claim disappears with it. Stock
still moves only when a sale is rung up, so `Product.stock_qty` keeps
meaning what the shelf and the stock-take say it means. Reservations sit
on top as a claim against that count:

    available = stock_qty - reserved

Labour lines never reserve — they carry no stock to claim.
"""

from typing import Iterable, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.models import HeldSaleLine, Product

LABOUR_PREFIX = "LABOR"


def is_labour(sku: Optional[str]) -> bool:
    """The shop's convention: a SKU starting with LABOR is work, not a part."""
    return str(sku or "").upper().startswith(LABOUR_PREFIX)


def reserved_map(
    db: Session, product_ids: Optional[Iterable[int]] = None
) -> dict[int, float]:
    """How many units of each product are claimed by parked baskets."""
    query = db.query(
        HeldSaleLine.product_id,
        func.sum(HeldSaleLine.quantity),
    ).filter(
        func.upper(func.coalesce(HeldSaleLine.sku, "")).notlike(f"{LABOUR_PREFIX}%")
    )
    if product_ids is not None:
        ids = list(product_ids)
        if not ids:
            return {}
        query = query.filter(HeldSaleLine.product_id.in_(ids))
    rows = query.group_by(HeldSaleLine.product_id).all()
    return {pid: float(qty or 0) for pid, qty in rows if pid is not None}


def reserved_for(db: Session, product_id: int) -> float:
    """Units of one product claimed by parked baskets."""
    return reserved_map(db, [product_id]).get(product_id, 0.0)


def available_qty(product: Product, reserved: float) -> float:
    """What the counter can actually sell today."""
    return float(product.stock_qty or 0) - float(reserved or 0)


def _describe_shortfall(product: Product, wanted: float, reserved: float) -> str:
    """A counter-readable reason why a line cannot be promised."""
    available = available_qty(product, reserved)
    return (
        f"{product.name}: {_num(wanted)} wanted, {_num(available)} free "
        f"({_num(product.stock_qty or 0)} on hand, {_num(reserved)} held at the till)"
    )


def _num(value: float) -> str:
    value = float(value or 0)
    return str(int(value)) if value == int(value) else f"{value:g}"


def unreserved_check(
    db: Session,
    lines: list[tuple[Product, float]],
    only_when_reserved: bool = False,
) -> list[str]:
    """Which of these lines ask for more than is free, and by how much.

    Returns one description per offending line, empty when every line can
    be promised. Two lines for the same product are summed, so a basket
    cannot slip past by splitting a request in half.

    `only_when_reserved` narrows the check to lines a parked basket is
    actually competing for. The till has always been allowed to sell a
    product into negative stock — parts often arrive ahead of their
    paperwork — and that stays true; what it may not do is spend stock
    already promised to someone else.
    """
    wanted: dict[int, float] = {}
    products: dict[int, Product] = {}
    for product, quantity in lines:
        if is_labour(product.sku):
            continue
        wanted[product.id] = wanted.get(product.id, 0.0) + float(quantity or 0)
        products[product.id] = product

    if not wanted:
        return []

    reserved = reserved_map(db, wanted.keys())
    problems = []
    for product_id, quantity in wanted.items():
        product = products[product_id]
        claimed = reserved.get(product_id, 0.0)
        if only_when_reserved and claimed <= 0:
            continue
        if quantity > available_qty(product, claimed):
            problems.append(_describe_shortfall(product, quantity, claimed))
    return problems
