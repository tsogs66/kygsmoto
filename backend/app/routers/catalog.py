"""Items, categories, suppliers and shop services."""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from .. import db
from ..security import audit, current_user, require

router = APIRouter(prefix="/api", tags=["catalog"])


class ItemIn(BaseModel):
    sku: str | None = None
    barcode: str | None = None
    description: str
    category_id: int | None = None
    supplier_id: int | None = None
    unit_cost: float = 0
    retail_price: float = 0
    stock_qty: float = 0
    reorder_point: float = 0
    reorder_qty: float = 0
    location: str = ""
    active: bool = True
    delisted: bool = False


class ItemPatch(BaseModel):
    barcode: str | None = None
    description: str | None = None
    category_id: int | None = None
    supplier_id: int | None = None
    unit_cost: float | None = None
    retail_price: float | None = None
    reorder_point: float | None = None
    reorder_qty: float | None = None
    location: str | None = None
    active: bool | None = None
    delisted: bool | None = None


class CategoryIn(BaseModel):
    name: str
    prefix: str = ""


class SupplierIn(BaseModel):
    code: str
    name: str = ""
    contact: str = ""
    phone: str = ""
    email: str = ""
    address: str = ""
    lead_time_days: float = 7
    order_cycle_days: float = 30
    min_order_value: float = 0
    active: bool = True


class ServiceIn(BaseModel):
    code: str | None = None
    name: str
    fee: float = 0
    minutes: int = 0
    active: bool = True


def _next_sku(category_id: int | None) -> str:
    """Generate the next SKU using the shop's CATEGORY-PREFIX + running number style."""
    prefix = "GEN"
    if category_id:
        row = db.query_one("SELECT prefix, name FROM categories WHERE id = ?", (category_id,))
        if row:
            prefix = (row["prefix"] or row["name"][:3]).upper()

    rows = db.query(
        "SELECT sku FROM items WHERE sku LIKE ? ORDER BY sku", (f"{prefix}%",)
    )
    highest = 0
    for row in rows:
        tail = row["sku"][len(prefix):]
        if tail.isdigit():
            highest = max(highest, int(tail))
    return f"{prefix}{highest + 1:03d}"


# ------------------------------------------------------------------- items

@router.get("/items")
def list_items(
    q: str = "",
    category_id: int | None = None,
    supplier_id: int | None = None,
    status: str = "active",
    low_stock: bool = False,
    limit: int = Query(default=100, le=2000),
    offset: int = 0,
    user=Depends(require("inventory.view")),
):
    where, params = ["1=1"], []
    if status == "active":
        where.append("i.active = 1 AND i.delisted = 0")
    elif status == "delisted":
        where.append("i.delisted = 1")
    elif status == "inactive":
        where.append("i.active = 0")

    if q:
        where.append("(i.description LIKE ? OR i.sku LIKE ? OR i.barcode = ?)")
        params += [f"%{q}%", f"{q}%", q]
    if category_id:
        where.append("i.category_id = ?")
        params.append(category_id)
    if supplier_id:
        where.append("i.supplier_id = ?")
        params.append(supplier_id)
    if low_stock:
        where.append("i.stock_qty <= i.reorder_point")

    clause = " AND ".join(where)
    total = db.query_one(f"SELECT COUNT(*) AS n FROM items i WHERE {clause}", tuple(params))["n"]
    rows = db.query(
        f"""SELECT i.*, c.name AS category, s.code AS supplier
              FROM items i
              LEFT JOIN categories c ON c.id = i.category_id
              LEFT JOIN suppliers s ON s.id = i.supplier_id
             WHERE {clause}
          ORDER BY i.description
             LIMIT ? OFFSET ?""",
        (*params, limit, offset),
    )
    return {"total": total, "items": [dict(r) for r in rows]}


@router.get("/items/lookup")
def lookup(code: str, user=Depends(require("inventory.view"))):
    """Barcode / SKU scan used by the POS terminal."""
    row = db.query_one(
        """SELECT i.*, c.name AS category, s.code AS supplier
             FROM items i
             LEFT JOIN categories c ON c.id = i.category_id
             LEFT JOIN suppliers s ON s.id = i.supplier_id
            WHERE (i.barcode = ? OR i.sku = ?) AND i.active = 1""",
        (code.strip(), code.strip()),
    )
    if row is None:
        raise HTTPException(status_code=404, detail=f"No active item matches '{code}'")
    return dict(row)


@router.get("/items/{item_id}")
def get_item(item_id: int, user=Depends(require("inventory.view"))):
    row = db.query_one(
        """SELECT i.*, c.name AS category, s.code AS supplier
             FROM items i
             LEFT JOIN categories c ON c.id = i.category_id
             LEFT JOIN suppliers s ON s.id = i.supplier_id
            WHERE i.id = ?""",
        (item_id,),
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Item not found")

    moves = db.query(
        "SELECT * FROM stock_moves WHERE item_id = ? ORDER BY id DESC LIMIT 50", (item_id,)
    )
    history = db.query(
        "SELECT period, qty, revenue FROM demand_history WHERE item_id = ? ORDER BY period",
        (item_id,),
    )
    recent = db.query(
        """SELECT s.business_date AS d, SUM(l.qty) AS qty, SUM(l.total) AS revenue
             FROM sale_lines l JOIN sales s ON s.id = l.sale_id
            WHERE l.item_id = ? AND s.status = 'completed'
         GROUP BY s.business_date ORDER BY s.business_date DESC LIMIT 90""",
        (item_id,),
    )
    return {
        "item": dict(row),
        "moves": [dict(m) for m in moves],
        "history": [dict(h) for h in history],
        "recent_sales": [dict(r) for r in recent],
    }


@router.post("/items")
def create_item(body: ItemIn, user=Depends(require("inventory.edit"))):
    sku = (body.sku or "").strip().upper() or _next_sku(body.category_id)
    if db.query_one("SELECT id FROM items WHERE sku = ?", (sku,)):
        raise HTTPException(status_code=409, detail=f"SKU {sku} already exists")
    if body.retail_price < body.unit_cost:
        # Allowed (clearance happens) but worth recording deliberately.
        audit(user, "item.priced_below_cost", "item", sku,
              {"cost": body.unit_cost, "price": body.retail_price})

    cur = db.execute(
        """INSERT INTO items(sku, barcode, description, category_id, supplier_id, unit_cost,
                             retail_price, stock_qty, reorder_point, reorder_qty, location,
                             active, delisted)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (sku, body.barcode, body.description.strip(), body.category_id, body.supplier_id,
         body.unit_cost, body.retail_price, body.stock_qty, body.reorder_point,
         body.reorder_qty, body.location, int(body.active), int(body.delisted)),
    )
    item_id = cur.lastrowid
    if body.stock_qty:
        db.execute(
            "INSERT INTO stock_moves(item_id, qty_delta, balance_after, move_type, "
            "ref_type, unit_cost, user_id, note) VALUES(?,?,?,'opening','item',?,?,?)",
            (item_id, body.stock_qty, body.stock_qty, body.unit_cost, user["id"],
             "Opening stock on item creation"),
        )
    audit(user, "item.created", "item", item_id, {"sku": sku})
    return {"item": dict(db.query_one("SELECT * FROM items WHERE id = ?", (item_id,)))}


@router.patch("/items/{item_id}")
def update_item(item_id: int, body: ItemPatch, user=Depends(require("inventory.edit"))):
    row = db.query_one("SELECT * FROM items WHERE id = ?", (item_id,))
    if row is None:
        raise HTTPException(status_code=404, detail="Item not found")

    data = body.model_dump(exclude_none=True)
    if not data:
        return {"item": dict(row)}

    changes = {k: {"from": row[k], "to": v} for k, v in data.items() if row[k] != v}
    sets = ", ".join(f"{k} = ?" for k in data)
    values = [int(v) if isinstance(v, bool) else v for v in data.values()]
    db.execute(
        f"UPDATE items SET {sets}, updated_at = datetime('now') WHERE id = ?",
        (*values, item_id),
    )
    if changes:
        audit(user, "item.updated", "item", item_id, changes)
    return {"item": dict(db.query_one("SELECT * FROM items WHERE id = ?", (item_id,)))}


@router.delete("/items/{item_id}")
def delist_item(item_id: int, user=Depends(require("inventory.edit"))):
    """Items are delisted, never deleted, so sales history stays intact."""
    row = db.query_one("SELECT * FROM items WHERE id = ?", (item_id,))
    if row is None:
        raise HTTPException(status_code=404, detail="Item not found")
    db.execute(
        "UPDATE items SET delisted = 1, active = 0, updated_at = datetime('now') WHERE id = ?",
        (item_id,),
    )
    audit(user, "item.delisted", "item", item_id, {"sku": row["sku"]})
    return {"ok": True, "delisted": True}


# -------------------------------------------------------------- categories

@router.get("/categories")
def list_categories(user=Depends(current_user)):
    rows = db.query(
        """SELECT c.*, COUNT(i.id) AS item_count,
                  COALESCE(SUM(i.stock_qty * i.unit_cost), 0) AS stock_value
             FROM categories c
             LEFT JOIN items i ON i.category_id = c.id AND i.active = 1 AND i.delisted = 0
         GROUP BY c.id ORDER BY c.name"""
    )
    return {"categories": [dict(r) for r in rows]}


@router.post("/categories")
def create_category(body: CategoryIn, user=Depends(require("inventory.edit"))):
    if db.query_one("SELECT id FROM categories WHERE name = ?", (body.name,)):
        raise HTTPException(status_code=409, detail="Category already exists")
    prefix = (body.prefix or body.name[:3]).upper()
    cur = db.execute(
        "INSERT INTO categories(name, prefix) VALUES(?,?)", (body.name.strip().upper(), prefix)
    )
    audit(user, "category.created", "category", cur.lastrowid, {"name": body.name})
    return {"category": dict(db.query_one("SELECT * FROM categories WHERE id = ?",
                                          (cur.lastrowid,)))}


# --------------------------------------------------------------- suppliers

@router.get("/suppliers")
def list_suppliers(user=Depends(current_user)):
    rows = db.query(
        """SELECT s.*, COUNT(i.id) AS item_count,
                  COALESCE(SUM(i.stock_qty * i.unit_cost), 0) AS stock_value
             FROM suppliers s
             LEFT JOIN items i ON i.supplier_id = s.id AND i.active = 1 AND i.delisted = 0
         GROUP BY s.id ORDER BY s.code"""
    )
    return {"suppliers": [dict(r) for r in rows]}


@router.post("/suppliers")
def create_supplier(body: SupplierIn, user=Depends(require("inventory.edit"))):
    if db.query_one("SELECT id FROM suppliers WHERE code = ?", (body.code,)):
        raise HTTPException(status_code=409, detail="Supplier code already exists")
    cur = db.execute(
        """INSERT INTO suppliers(code, name, contact, phone, email, address, lead_time_days,
                                 order_cycle_days, min_order_value, active)
           VALUES(?,?,?,?,?,?,?,?,?,?)""",
        (body.code.strip().upper(), body.name, body.contact, body.phone, body.email,
         body.address, body.lead_time_days, body.order_cycle_days, body.min_order_value,
         int(body.active)),
    )
    audit(user, "supplier.created", "supplier", cur.lastrowid, {"code": body.code})
    return {"supplier": dict(db.query_one("SELECT * FROM suppliers WHERE id = ?",
                                          (cur.lastrowid,)))}


@router.patch("/suppliers/{supplier_id}")
def update_supplier(supplier_id: int, body: SupplierIn, user=Depends(require("inventory.edit"))):
    if db.query_one("SELECT id FROM suppliers WHERE id = ?", (supplier_id,)) is None:
        raise HTTPException(status_code=404, detail="Supplier not found")
    db.execute(
        """UPDATE suppliers SET code=?, name=?, contact=?, phone=?, email=?, address=?,
                  lead_time_days=?, order_cycle_days=?, min_order_value=?, active=?
            WHERE id = ?""",
        (body.code.strip().upper(), body.name, body.contact, body.phone, body.email,
         body.address, body.lead_time_days, body.order_cycle_days, body.min_order_value,
         int(body.active), supplier_id),
    )
    audit(user, "supplier.updated", "supplier", supplier_id, body.model_dump())
    return {"supplier": dict(db.query_one("SELECT * FROM suppliers WHERE id = ?",
                                          (supplier_id,)))}


# ---------------------------------------------------------------- services

@router.get("/services")
def list_services(active_only: bool = True, user=Depends(current_user)):
    clause = "WHERE active = 1" if active_only else ""
    rows = db.query(f"SELECT * FROM services {clause} ORDER BY name")
    return {"services": [dict(r) for r in rows]}


@router.post("/services")
def create_service(body: ServiceIn, user=Depends(require("inventory.edit"))):
    code = (body.code or "").strip().upper()
    if not code:
        count = db.query_one("SELECT COUNT(*) AS n FROM services")["n"]
        code = f"SVC{count + 1:03d}"
    if db.query_one("SELECT id FROM services WHERE code = ?", (code,)):
        raise HTTPException(status_code=409, detail="Service code already exists")
    cur = db.execute(
        "INSERT INTO services(code, name, fee, minutes, active) VALUES(?,?,?,?,?)",
        (code, body.name.strip(), body.fee, body.minutes, int(body.active)),
    )
    audit(user, "service.created", "service", cur.lastrowid, {"name": body.name})
    return {"service": dict(db.query_one("SELECT * FROM services WHERE id = ?",
                                         (cur.lastrowid,)))}


@router.patch("/services/{service_id}")
def update_service(service_id: int, body: ServiceIn, user=Depends(require("inventory.edit"))):
    if db.query_one("SELECT id FROM services WHERE id = ?", (service_id,)) is None:
        raise HTTPException(status_code=404, detail="Service not found")
    db.execute(
        "UPDATE services SET name = ?, fee = ?, minutes = ?, active = ? WHERE id = ?",
        (body.name.strip(), body.fee, body.minutes, int(body.active), service_id),
    )
    audit(user, "service.updated", "service", service_id, body.model_dump())
    return {"service": dict(db.query_one("SELECT * FROM services WHERE id = ?", (service_id,)))}
