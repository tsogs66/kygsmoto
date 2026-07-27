"""Import CSV/Excel stock files to set or adjust inventory quantities.

Supported headers (aliases):
  ITEM CODE / SKU / barcode
  DESCRIPTION / product name (optional, for upsert)
  ENDING STOCKS / STOCK / QTY / QUANTITY
  UNIT PRICE / COST (optional)
  RETAIL PRICE / PRICE (optional)
  CATEGORY / SUPPLIER (optional, for upsert)
  ADJUST / DELTA (optional — used when mode=adjust if present)

Modes:
  set     — stock_qty becomes the CSV value (absolute)
  adjust  — stock_qty += CSV qty (or ADJUST column)
  upsert  — like set, but create missing SKUs
"""

from __future__ import annotations

import io
import json
import re
from datetime import datetime
from typing import Any, Optional

import pandas as pd
from sqlalchemy.orm import Session

from app.models.models import Category, ImportBatch, Product, Supplier
from app.services.stock import apply_stock_change


STOCK_ALIASES = {
    "sku": [
        "item_code", "item code", "sku", "code", "barcode", "product_code", "part_no",
    ],
    "product_name": [
        "description", "item_description", "item description", "product", "product_name",
        "name", "item",
    ],
    "stock": [
        "ending_stocks", "ending stock", "ending_stocks_", "stock", "stocks", "stock_qty",
        "qty", "quantity", "on_hand", "available", "total_stocks",
    ],
    "adjust": [
        "adjust", "adjustment", "delta", "change", "qty_change", "quantity_change",
    ],
    "cost_price": [
        "unit_price", "cost", "cost_price", "purchase_price",
    ],
    "sell_price": [
        "retail_price", "sell_price", "price", "mrp",
    ],
    "category": ["category", "cat"],
    "supplier": ["supplier", "vendor"],
}


def _norm(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")


def _map_columns(columns: list[str]) -> dict[str, str]:
    normalized = {_norm(c): c for c in columns}
    mapping: dict[str, str] = {}
    for canonical, aliases in STOCK_ALIASES.items():
        for alias in aliases:
            key = _norm(alias)
            if key in normalized:
                mapping[canonical] = normalized[key]
                break
    return mapping


def _to_float(value: Any, default: float = 0.0) -> float:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "").replace("₱", "")
    try:
        return float(text)
    except ValueError:
        return default


def _to_str(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def read_stock_dataframe(filename: str, content: bytes) -> pd.DataFrame:
    lower = filename.lower()
    buffer = io.BytesIO(content)
    if lower.endswith((".xlsx", ".xlsm", ".xls")):
        # Prefer INVENTORY sheet when present (KYGS workbook)
        excel = pd.ExcelFile(buffer)
        sheet = "INVENTORY" if "INVENTORY" in excel.sheet_names else excel.sheet_names[0]
        df = excel.parse(sheet, header=None)
        # Find header row containing ITEM CODE / CATEGORY
        header_idx = None
        for i in range(min(10, len(df))):
            vals = [_norm(v) for v in df.iloc[i].tolist()]
            if "item_code" in vals or ("sku" in vals and "stock" in vals):
                header_idx = i
                break
            if "category" in vals and "item_code" in vals:
                header_idx = i
                break
        if header_idx is not None:
            cols = [str(v).strip() if pd.notna(v) else f"col_{j}" for j, v in enumerate(df.iloc[header_idx].tolist())]
            df = df.iloc[header_idx + 1 :].copy()
            df.columns = cols
        else:
            buffer.seek(0)
            df = pd.read_excel(buffer, sheet_name=sheet)
    elif lower.endswith(".csv"):
        df = None
        for enc in ("utf-8-sig", "utf-8", "latin-1"):
            try:
                buffer.seek(0)
                df = pd.read_csv(buffer, encoding=enc)
                break
            except Exception:
                df = None
        if df is None:
            raise ValueError("Unable to read CSV file")
    else:
        raise ValueError("Unsupported file type. Upload CSV or Excel (.xlsx/.xlsm)")
    df = df.dropna(how="all")
    df.columns = [str(c).strip() for c in df.columns]
    return df


def _get_or_create_category(db: Session, name: str, cache: dict[str, Category]) -> Optional[Category]:
    if not name:
        return None
    key = name.upper()
    if key in cache:
        return cache[key]
    obj = db.query(Category).filter(Category.name.ilike(name)).first()
    if not obj:
        obj = Category(name=name)
        db.add(obj)
        db.flush()
    cache[key] = obj
    return obj


def _get_or_create_supplier(db: Session, name: str, cache: dict[str, Supplier]) -> Optional[Supplier]:
    if not name:
        return None
    key = name.upper()
    if key in cache:
        return cache[key]
    obj = db.query(Supplier).filter(Supplier.name.ilike(name)).first()
    if not obj:
        obj = Supplier(name=name)
        db.add(obj)
        db.flush()
    cache[key] = obj
    return obj


def preview_stock_file(db: Session, filename: str, content: bytes, mode: str = "set") -> dict:
    if mode not in {"set", "adjust", "upsert"}:
        raise ValueError("mode must be set, adjust, or upsert")
    df = read_stock_dataframe(filename, content)
    mapping = _map_columns(list(df.columns))
    if "sku" not in mapping:
        raise ValueError(
            "Could not detect SKU / ITEM CODE column. "
            f"Found columns: {list(df.columns)}"
        )
    if "stock" not in mapping and "adjust" not in mapping:
        raise ValueError(
            "Could not detect STOCK / QTY / ENDING STOCKS column. "
            f"Found columns: {list(df.columns)}"
        )

    rows = []
    matched = unmatched = created_preview = 0
    for idx, record in df.iterrows():
        row_number = int(idx) + 2
        sku = _to_str(record[mapping["sku"]])
        if not sku or sku.upper() == "ITEM CODE":
            continue
        name = _to_str(record[mapping["product_name"]]) if "product_name" in mapping else ""
        stock_val = _to_float(record[mapping["stock"]], 0) if "stock" in mapping else None
        adjust_val = _to_float(record[mapping["adjust"]], 0) if "adjust" in mapping else None
        product = db.query(Product).filter(Product.sku == sku).first()
        if not product and name:
            product = db.query(Product).filter(Product.name.ilike(name)).first()

        if not product:
            unmatched += 1
            status = "will_create" if mode == "upsert" else "unmatched"
            if mode == "upsert":
                created_preview += 1
            rows.append({
                "row_number": row_number,
                "sku": sku,
                "product_name": name or None,
                "csv_stock": stock_val,
                "csv_adjust": adjust_val,
                "current_stock": None,
                "new_stock": stock_val if mode != "adjust" else adjust_val,
                "status": status,
                "message": "Will create product" if mode == "upsert" else "SKU not found",
            })
            continue

        matched += 1
        current = float(product.stock_qty or 0)
        if mode == "adjust":
            delta = adjust_val if adjust_val is not None else (stock_val or 0)
            new_stock = current + delta
            msg = f"Adjust {delta:+} → {new_stock}"
        else:
            new_stock = stock_val if stock_val is not None else current
            delta = new_stock - current
            msg = f"Set {current} → {new_stock} ({delta:+})"
        rows.append({
            "row_number": row_number,
            "sku": product.sku,
            "product_name": product.name,
            "csv_stock": stock_val,
            "csv_adjust": adjust_val,
            "current_stock": current,
            "new_stock": new_stock,
            "status": "matched",
            "message": msg,
        })

    return {
        "filename": filename,
        "mode": mode,
        "rows": rows,
        "matched_count": matched,
        "unmatched_count": unmatched,
        "will_create_count": created_preview,
    }


def import_stock_file(
    db: Session,
    filename: str,
    content: bytes,
    mode: str = "set",
) -> dict:
    preview = preview_stock_file(db, filename, content, mode=mode)
    df = read_stock_dataframe(filename, content)
    mapping = _map_columns(list(df.columns))

    batch = ImportBatch(
        filename=filename,
        file_type=filename.rsplit(".", 1)[-1].lower(),
        status="processing",
        rows_total=len(df),
    )
    db.add(batch)
    db.flush()

    updated = created = skipped = 0
    unmatched: list[str] = []
    total_delta = 0.0
    cat_cache: dict[str, Category] = {}
    sup_cache: dict[str, Supplier] = {}

    for idx, record in df.iterrows():
        sku = _to_str(record[mapping["sku"]])
        if not sku or sku.upper() == "ITEM CODE":
            skipped += 1
            continue
        name = _to_str(record[mapping["product_name"]]) if "product_name" in mapping else sku
        stock_val = _to_float(record[mapping["stock"]], 0) if "stock" in mapping else None
        adjust_val = _to_float(record[mapping["adjust"]], 0) if "adjust" in mapping else None
        cost = _to_float(record[mapping["cost_price"]], 0) if "cost_price" in mapping else None
        sell = _to_float(record[mapping["sell_price"]], 0) if "sell_price" in mapping else None
        category_name = _to_str(record[mapping["category"]]) if "category" in mapping else ""
        supplier_name = _to_str(record[mapping["supplier"]]) if "supplier" in mapping else ""

        product = db.query(Product).filter(Product.sku == sku).first()
        if not product:
            if mode != "upsert":
                unmatched.append(sku)
                skipped += 1
                continue
            category = _get_or_create_category(db, category_name or "MISCELLANEOUS", cat_cache)
            supplier = _get_or_create_supplier(db, supplier_name, sup_cache)
            initial = stock_val if stock_val is not None else (adjust_val or 0)
            product = Product(
                sku=sku,
                name=name or sku,
                category_id=category.id if category else None,
                supplier_id=supplier.id if supplier else None,
                cost_price=cost or 0,
                sell_price=sell or cost or 0,
                stock_qty=0,
                reorder_level=2,
                barcode=sku,
                is_active=True,
            )
            db.add(product)
            db.flush()
            apply_stock_change(
                db,
                product,
                initial,
                "adjust",
                reference=f"STOCK-CSV-{batch.id}",
                notes=f"Created via stock CSV upsert ({filename})",
            )
            total_delta += initial
            created += 1
            continue

        before = float(product.stock_qty or 0)
        if mode == "adjust":
            delta = adjust_val if adjust_val is not None else (stock_val or 0)
        else:
            target = stock_val if stock_val is not None else before
            delta = target - before

        if cost is not None and cost > 0:
            product.cost_price = cost
        if sell is not None and sell > 0:
            product.sell_price = sell

        if abs(delta) > 1e-9:
            apply_stock_change(
                db,
                product,
                delta,
                "adjust",
                reference=f"STOCK-CSV-{batch.id}",
                notes=f"Stock {mode} from {filename}",
            )
            total_delta += delta
            updated += 1
        else:
            skipped += 1

    batch.rows_imported = updated + created
    batch.rows_skipped = skipped + len(unmatched)
    batch.stock_deducted = -total_delta  # negative means net stock added in this field's naming
    batch.unmatched_skus = json.dumps(sorted(set(unmatched))) if unmatched else None
    batch.summary = (
        f"Stock CSV ({mode}): updated {updated}, created {created}, "
        f"skipped {skipped}, unmatched {len(set(unmatched))}, net qty change {total_delta:+.2f}"
    )
    batch.status = "completed"
    db.commit()
    db.refresh(batch)

    return {
        "batch_id": batch.id,
        "filename": filename,
        "mode": mode,
        "rows_total": batch.rows_total,
        "rows_updated": updated,
        "rows_created": created,
        "rows_skipped": skipped,
        "unmatched_skus": sorted(set(unmatched)),
        "net_qty_change": total_delta,
        "message": batch.summary,
        "preview": preview,
    }
