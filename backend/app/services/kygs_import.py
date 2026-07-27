"""Import KYGS Motorcycle Parts Excel/VBA workbook (.xlsm) into KYGSMOTO.

Tuned for sheets found in ``KYGS APRIL 2025.xlsm``:
- INVENTORY — category, item code, description, supplier, costs, stocks
- SALES — DATE, ITEM CODE, ITEM DESCRIPTION, QTY, PRICE, DISCNT, TOTAL
- INFOSHEET — service fees, categories, suppliers, next SKU counters
- CRITICAL — reorder margin + OKAY/CRITICAL status
- DELISTED — inactive products
- ORDER — suggested reorder quantities (notes only)
"""

from __future__ import annotations

import re
import zipfile
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.models import (
    AppMeta,
    Category,
    Customer,
    Product,
    Sale,
    SaleItem,
    StockMovement,
    Supplier,
    Purchase,
    PurchaseItem,
    ImportBatch,
)
from app.services.stock import apply_stock_change

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL_NS = {"r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}


def _col_row(ref: str) -> tuple[str, int]:
    m = re.match(r"([A-Z]+)(\d+)", ref)
    if not m:
        raise ValueError(f"Bad cell ref: {ref}")
    return m.group(1), int(m.group(2))


def _shared_strings(z: zipfile.ZipFile) -> list[str]:
    try:
        root = ET.fromstring(z.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    out: list[str] = []
    for si in root.findall("m:si", NS):
        texts = [
            t.text or ""
            for t in si.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t")
        ]
        out.append("".join(texts))
    return out


def _sheet_map(z: zipfile.ZipFile) -> dict[str, str]:
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    rid_to_target = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels}
    sheets: dict[str, str] = {}
    for sh in wb.findall("m:sheets/m:sheet", NS):
        name = sh.attrib["name"]
        rid = sh.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]
        target = rid_to_target[rid].replace("\\", "/").lstrip("/")
        path = target if target.startswith("xl/") else f"xl/{target}"
        sheets[name] = path
    return sheets


def _load_sheet_cells(z: zipfile.ZipFile, path: str, ss: list[str]) -> dict[int, dict[str, Any]]:
    root = ET.fromstring(z.read(path))
    rows: dict[int, dict[str, Any]] = defaultdict(dict)
    for c in root.findall(".//m:sheetData/m:row/m:c", NS):
        ref = c.attrib.get("r")
        if not ref:
            continue
        col, row = _col_row(ref)
        v = c.find("m:v", NS)
        is_el = c.find("m:is", NS)
        val: Any = None
        if v is not None and v.text is not None:
            val = v.text
            if c.attrib.get("t") == "s":
                try:
                    val = ss[int(val)]
                except Exception:
                    pass
            elif c.attrib.get("t") != "s":
                # numeric
                try:
                    if "." in val or "E" in val or "e" in val:
                        val = float(val)
                    else:
                        ival = int(val)
                        val = ival
                except ValueError:
                    pass
        elif is_el is not None:
            texts = [
                t.text or ""
                for t in is_el.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t")
            ]
            val = "".join(texts)
        if val is None or (isinstance(val, str) and not val.strip()):
            continue
        rows[row][col] = val
    return rows


def _to_float(value: Any, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "").replace("₱", "").replace("P", "")
    try:
        return float(text)
    except ValueError:
        return default


def _to_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _excel_serial_to_datetime(value: Any) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    try:
        serial = float(value)
        if serial > 20000:  # Excel serial-ish
            return datetime(1899, 12, 30) + timedelta(days=serial)
    except (TypeError, ValueError):
        pass
    try:
        return datetime.fromisoformat(str(value).replace("/", "-"))
    except ValueError:
        return None


def _get_or_create_category(db: Session, name: str, cache: dict[str, Category]) -> Category:
    key = name.strip().upper()
    if key in cache:
        return cache[key]
    obj = db.query(Category).filter(Category.name.ilike(name.strip())).first()
    if not obj:
        obj = Category(name=name.strip())
        db.add(obj)
        db.flush()
    cache[key] = obj
    return obj


def _get_or_create_supplier(db: Session, name: str, cache: dict[str, Supplier]) -> Optional[Supplier]:
    if not name or not name.strip():
        return None
    key = name.strip().upper()
    if key in cache:
        return cache[key]
    obj = db.query(Supplier).filter(Supplier.name.ilike(name.strip())).first()
    if not obj:
        obj = Supplier(name=name.strip())
        db.add(obj)
        db.flush()
    cache[key] = obj
    return obj


def clear_transactional_data(db: Session) -> None:
    """Remove seeded/demo transactional data before a full KYGS load."""
    db.query(SaleItem).delete()
    db.query(Sale).delete()
    db.query(PurchaseItem).delete()
    db.query(Purchase).delete()
    db.query(StockMovement).delete()
    db.query(ImportBatch).delete()
    db.query(Product).delete()
    db.query(Customer).delete()
    db.query(Supplier).delete()
    db.query(Category).delete()
    db.query(AppMeta).filter(AppMeta.key.in_(["seeded", "kygs_imported"])).delete()
    db.commit()


def import_kygs_workbook(
    db: Session,
    path: Path | str,
    *,
    replace_existing: bool = True,
    import_sales: bool = True,
    import_services: bool = True,
    import_delisted: bool = True,
) -> dict:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Workbook not found: {path}")

    if replace_existing:
        clear_transactional_data(db)

    with zipfile.ZipFile(path) as z:
        ss = _shared_strings(z)
        sheets = _sheet_map(z)
        required = ["INVENTORY", "SALES", "INFOSHEET"]
        missing = [s for s in required if s not in sheets]
        if missing:
            raise ValueError(f"Missing sheets {missing}. Found: {list(sheets)}")

        inventory_rows = _load_sheet_cells(z, sheets["INVENTORY"], ss)
        sales_rows = _load_sheet_cells(z, sheets["SALES"], ss)
        info_rows = _load_sheet_cells(z, sheets["INFOSHEET"], ss)
        critical_rows = _load_sheet_cells(z, sheets["CRITICAL"], ss) if "CRITICAL" in sheets else {}
        delisted_rows = _load_sheet_cells(z, sheets["DELISTED"], ss) if "DELISTED" in sheets else {}

    cat_cache: dict[str, Category] = {}
    supplier_cache: dict[str, Supplier] = {}
    product_by_sku: dict[str, Product] = {}

    # --- INFOSHEET: categories + suppliers + services ---
    for r in range(2, 50):
        cols = info_rows.get(r, {})
        cat_name = _to_str(cols.get("F"))
        if cat_name:
            _get_or_create_category(db, cat_name, cat_cache)
        for col in ("D", "J"):
            sup = _to_str(cols.get(col))
            if sup and sup.lower() != "supplier":
                _get_or_create_supplier(db, sup, supplier_cache)

    services_created = 0
    if import_services:
        svc_cat = _get_or_create_category(db, "SERVICE LABOR", cat_cache)
        for r in range(2, 80):
            cols = info_rows.get(r, {})
            name = _to_str(cols.get("A"))
            fee = _to_float(cols.get("B"))
            if not name or name.lower() == "services":
                continue
            if fee <= 0 and "service" not in name.lower():
                # still allow named services with fee
                if fee < 0:
                    continue
            sku = f"SVC-{r-1:03d}"
            product = Product(
                sku=sku,
                name=name,
                brand="KYGSMOTO",
                category_id=svc_cat.id,
                description="Shop service / labor from INFOSHEET",
                unit="job",
                cost_price=0,
                sell_price=fee,
                stock_qty=9999,
                reorder_level=0,
                is_active=True,
            )
            db.add(product)
            db.flush()
            product_by_sku[sku] = product
            services_created += 1

    # --- CRITICAL: description -> reorder margin ---
    critical_margin: dict[str, float] = {}
    critical_status: dict[str, str] = {}
    for r in sorted(critical_rows):
        if r == 1:
            continue
        cols = critical_rows[r]
        desc = _to_str(cols.get("B")).upper()
        if not desc or desc == "DESCRIPTION":
            continue
        margin = _to_float(cols.get("C"), 1)
        status = _to_str(cols.get("E")).upper() or "OKAY"
        critical_margin[desc] = margin
        critical_status[desc] = status

    # --- INVENTORY ---
    products_created = 0
    for r in sorted(inventory_rows):
        if r < 4:
            continue
        cols = inventory_rows[r]
        sku = _to_str(cols.get("B"))
        name = _to_str(cols.get("C"))
        if not sku or not name or sku.upper() == "ITEM CODE":
            continue
        category_name = _to_str(cols.get("A")) or "MISCELLANEOUS"
        supplier_name = _to_str(cols.get("D"))
        cost = _to_float(cols.get("E"))
        retail = _to_float(cols.get("M"))
        ending = _to_float(cols.get("P"))
        # Prefer CRITICAL margin; else default 2 (or 1 for low-volume)
        reorder = critical_margin.get(name.upper(), 2.0)
        category = _get_or_create_category(db, category_name, cat_cache)
        supplier = _get_or_create_supplier(db, supplier_name, supplier_cache)

        if sku.upper() in product_by_sku:
            # Duplicate SKU rows in workbook — keep latest ending stock / prices
            existing = product_by_sku[sku.upper()]
            before = float(existing.stock_qty or 0)
            existing.name = name
            existing.category_id = category.id
            existing.supplier_id = supplier.id if supplier else existing.supplier_id
            existing.cost_price = cost
            existing.sell_price = retail if retail > 0 else cost
            existing.stock_qty = ending
            existing.reorder_level = reorder
            existing.is_active = True
            db.add(
                StockMovement(
                    product_id=existing.id,
                    movement_type="adjust",
                    quantity_change=ending - before,
                    stock_before=before,
                    stock_after=ending,
                    reference="KYGS-INVENTORY-DUP",
                    notes=f"Duplicate SKU row merged from {path.name}",
                )
            )
            continue

        product = Product(
            sku=sku,
            name=name,
            brand=None,
            category_id=category.id,
            supplier_id=supplier.id if supplier else None,
            description=name,
            fitment=None,
            unit="pc",
            cost_price=cost,
            sell_price=retail if retail > 0 else cost,
            stock_qty=ending,
            reorder_level=reorder,
            location=None,
            barcode=sku,
            is_active=True,
        )
        db.add(product)
        db.flush()
        product_by_sku[sku.upper()] = product
        products_created += 1

        # Opening movement snapshot (no delta math — ending already final)
        db.add(
            StockMovement(
                product_id=product.id,
                movement_type="adjust",
                quantity_change=ending,
                stock_before=0,
                stock_after=ending,
                reference="KYGS-INVENTORY",
                notes=f"Imported ending stock from {path.name}",
            )
        )

    # --- DELISTED ---
    delisted_count = 0
    if import_delisted:
        for r in sorted(delisted_rows):
            if r < 2:
                continue
            cols = delisted_rows[r]
            sku = _to_str(cols.get("B"))
            name = _to_str(cols.get("C"))
            if not sku or not name:
                continue
            if sku.upper() in product_by_sku:
                product_by_sku[sku.upper()].is_active = False
                delisted_count += 1
                continue
            category = _get_or_create_category(db, _to_str(cols.get("A")) or "DELISTED", cat_cache)
            supplier = _get_or_create_supplier(db, _to_str(cols.get("D")), supplier_cache)
            product = Product(
                sku=sku,
                name=name,
                category_id=category.id,
                supplier_id=supplier.id if supplier else None,
                cost_price=_to_float(cols.get("E")),
                sell_price=_to_float(cols.get("F")),
                stock_qty=0,
                reorder_level=_to_float(cols.get("G"), 1),
                is_active=False,
                barcode=sku,
            )
            db.add(product)
            db.flush()
            product_by_sku[sku.upper()] = product
            delisted_count += 1

    # --- SALES (historical; do NOT deduct stock again — ending stocks already net of sales) ---
    sales_created = 0
    sale_lines = 0
    unmatched_skus: list[str] = []
    if import_sales:
        # Group by date into daily invoices
        by_date: dict[str, list[dict]] = defaultdict(list)
        for r in sorted(sales_rows):
            if r < 3:
                continue
            cols = sales_rows[r]
            sku = _to_str(cols.get("B"))
            name = _to_str(cols.get("C"))
            qty = _to_float(cols.get("D"))
            price = _to_float(cols.get("E"))
            discount = _to_float(cols.get("F"))
            total = _to_float(cols.get("G"))
            sale_date = _excel_serial_to_datetime(cols.get("A"))
            if not sku or qty <= 0:
                continue
            if not sale_date:
                sale_date = datetime.utcnow()
            key = sale_date.strftime("%Y-%m-%d")
            by_date[key].append(
                {
                    "sku": sku,
                    "name": name,
                    "qty": qty,
                    "price": price,
                    "discount": discount,
                    "total": total if total else qty * price - discount,
                    "sale_date": sale_date,
                }
            )

        walkin = db.query(Customer).filter(Customer.name == "Walk-in Customer").first()
        if not walkin:
            walkin = Customer(name="Walk-in Customer")
            db.add(walkin)
            db.flush()

        for day, lines in sorted(by_date.items()):
            invoice_no = f"KYGS-{day.replace('-', '')}"
            sale = Sale(
                invoice_no=invoice_no,
                sale_date=lines[0]["sale_date"],
                customer_id=walkin.id,
                payment_method="cash",
                payment_status="paid",
                source="kygs_workbook",
                notes=f"Imported from {path.name} SALES sheet (stock not re-deducted)",
                discount=sum(l["discount"] for l in lines),
            )
            subtotal = 0.0
            for line in lines:
                product = product_by_sku.get(line["sku"].upper())
                if not product:
                    unmatched_skus.append(line["sku"])
                    # still record orphan line without product_id
                    sale.items.append(
                        SaleItem(
                            product_id=None,
                            sku=line["sku"],
                            product_name=line["name"] or line["sku"],
                            quantity=line["qty"],
                            unit_price=line["price"],
                            cost_price=0,
                            line_total=line["total"],
                        )
                    )
                else:
                    sale.items.append(
                        SaleItem(
                            product_id=product.id,
                            sku=product.sku,
                            product_name=product.name,
                            quantity=line["qty"],
                            unit_price=line["price"] or product.sell_price,
                            cost_price=product.cost_price,
                            line_total=line["total"],
                        )
                    )
                subtotal += line["total"]
                sale_lines += 1
            sale.subtotal = subtotal + sale.discount
            sale.total = subtotal
            sale.amount_paid = sale.total
            db.add(sale)
            sales_created += 1

    batch = ImportBatch(
        filename=path.name,
        file_type="xlsm",
        status="completed",
        rows_total=products_created + sale_lines,
        rows_imported=products_created + sale_lines,
        rows_skipped=len(unmatched_skus),
        stock_deducted=0,
        unmatched_skus=",".join(sorted(set(unmatched_skus))) if unmatched_skus else None,
        summary=(
            f"KYGS workbook import: {products_created} products, {services_created} services, "
            f"{delisted_count} delisted, {sales_created} sale invoices ({sale_lines} lines), "
            f"{len(set(unmatched_skus))} unmatched sale SKUs"
        ),
    )
    db.add(batch)
    db.merge(AppMeta(key="seeded", value="1"))
    db.merge(AppMeta(key="kygs_imported", value=path.name))
    db.commit()

    return {
        "filename": path.name,
        "products_created": products_created,
        "services_created": services_created,
        "delisted_count": delisted_count,
        "categories": len(cat_cache),
        "suppliers": len(supplier_cache),
        "sales_created": sales_created,
        "sale_lines": sale_lines,
        "unmatched_skus": sorted(set(unmatched_skus)),
        "batch_id": batch.id,
        "message": batch.summary,
    }
