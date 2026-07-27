"""Parse sales report files (CSV/XLSX) and sync inventory stock from sold quantities.

Compatible with common Excel VBA sales export layouts such as:
- Order_ID, Date, Product, Qty, Unit_Price, Customer, Total_Amount, Processed
- Invoice/SKU/Product/Qty/Price style motorshop sales sheets
"""

from __future__ import annotations

import io
import json
import re
from collections import defaultdict
from datetime import datetime, date
from typing import Any, Optional

import pandas as pd
from sqlalchemy.orm import Session

from app.models.models import (
    Customer,
    ImportBatch,
    Product,
    Sale,
    SaleItem,
)
from app.services.stock import apply_stock_change


HEADER_ALIASES = {
    "invoice_no": [
        "invoice_no", "invoice", "invoice#", "invoice_number", "order_id", "order id",
        "sale_id", "receipt", "receipt_no", "or_no", "si_no", "inv",
    ],
    "sale_date": [
        "sale_date", "date", "order_date", "transaction_date", "sales_date", "datetime",
    ],
    "sku": [
        # KYGS VBA workbook uses ITEM CODE
        "item_code", "item code", "sku", "item_id", "item id", "product_code",
        "product_no", "product no", "part_no", "part number", "code", "barcode",
    ],
    "product_name": [
        # KYGS VBA workbook uses ITEM DESCRIPTION
        "item_description", "item description", "product", "product_name", "item",
        "item_name", "description", "part_name", "product name",
    ],
    "quantity": [
        "qty", "quantity", "qty_sold", "sold_qty", "units", "pcs", "sales_quantity",
    ],
    "unit_price": [
        "unit_price", "price", "rate", "sell_price", "sales_price", "unit price", "mrp",
        "retail_price",
    ],
    "discount": [
        "discount", "discnt", "disc", "sales_discount",
    ],
    "customer": [
        "customer", "customer_name", "client", "buyer",
    ],
    "total": [
        "total", "total_amount", "line_total", "amount", "sales_amount", "ealant",
    ],
    "processed": [
        "processed", "imported", "done",
    ],
}


def _norm(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")


def _map_columns(columns: list[str]) -> dict[str, str]:
    normalized = {_norm(c): c for c in columns}
    mapping: dict[str, str] = {}
    for canonical, aliases in HEADER_ALIASES.items():
        for alias in aliases:
            key = _norm(alias)
            if key in normalized:
                mapping[canonical] = normalized[key]
                break
    return mapping


def _parse_date(value: Any) -> Optional[datetime]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    if isinstance(value, (int, float)):
        # Excel serial date
        try:
            return pd.to_datetime(float(value), unit="D", origin="1899-12-30").to_pydatetime()
        except Exception:
            pass
    try:
        return pd.to_datetime(str(value), dayfirst=False).to_pydatetime()
    except Exception:
        return None


def _to_float(value: Any, default: float = 0.0) -> float:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "").replace("₱", "").replace("P", "")
    try:
        return float(text)
    except ValueError:
        return default


def _pick_sales_sheet(excel: pd.ExcelFile) -> str:
    """Prefer KYGS 'SALES' sheet; else first sheet whose headers look like sales."""
    names = list(excel.sheet_names)
    for preferred in ("SALES", "Sales", "sales", "sales recipt", "Sales_Data"):
        if preferred in names:
            return preferred
    for name in names:
        preview = excel.parse(name, nrows=5)
        cols = {_norm(c) for c in preview.columns}
        if ({"item_code", "sku", "product"} & cols) and ({"qty", "quantity"} & cols):
            return name
        # KYGS sometimes has junk in row1; try header=1
        preview2 = excel.parse(name, header=1, nrows=5)
        cols2 = {_norm(c) for c in preview2.columns}
        if ({"item_code", "date"} & cols2) and ({"qty", "quantity"} & cols2):
            return name
    return names[0]


def _normalize_kygs_sales_frame(df: pd.DataFrame) -> pd.DataFrame:
    """If first row is not headers (KYGS SALES has totals in row 1), promote real header."""
    cols = [_norm(c) for c in df.columns]
    looks_like_header = ("date" in cols or "item_code" in cols) and (
        "qty" in cols or "quantity" in cols
    )
    if looks_like_header:
        return df

    # Scan first few rows for DATE / ITEM CODE header row
    for i in range(min(5, len(df))):
        values = [_norm(v) for v in df.iloc[i].tolist()]
        if "date" in values and ("item_code" in values or "sku" in values) and "qty" in values:
            new_cols = [str(v).strip() if v is not None and str(v) != "nan" else f"col_{j}" for j, v in enumerate(df.iloc[i].tolist())]
            body = df.iloc[i + 1 :].copy()
            body.columns = new_cols
            return body.reset_index(drop=True)
    return df


def read_sales_dataframe(filename: str, content: bytes) -> pd.DataFrame:
    lower = filename.lower()
    buffer = io.BytesIO(content)
    if lower.endswith((".xlsx", ".xlsm", ".xls")):
        excel = pd.ExcelFile(buffer)
        sheet = _pick_sales_sheet(excel)
        df = excel.parse(sheet)
        df = _normalize_kygs_sales_frame(df)
        # KYGS SALES: if still wrong, force header row 1 (0-index) after totals row
        cols = [_norm(c) for c in df.columns]
        if not (("item_code" in cols or "sku" in cols) and ("qty" in cols or "quantity" in cols)):
            df2 = excel.parse(sheet, header=1)
            df2 = _normalize_kygs_sales_frame(df2)
            cols2 = [_norm(c) for c in df2.columns]
            if ("item_code" in cols2 or "sku" in cols2) and ("qty" in cols2 or "quantity" in cols2):
                df = df2
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
        df = _normalize_kygs_sales_frame(df)
    else:
        raise ValueError("Unsupported file type. Upload CSV or Excel (.xlsx/.xlsm)")
    df = df.dropna(how="all")
    df.columns = [str(c).strip() for c in df.columns]
    return df


def find_product(db: Session, sku: Optional[str], product_name: Optional[str]) -> Optional[Product]:
    if sku:
        product = db.query(Product).filter(Product.sku == str(sku).strip()).first()
        if product:
            return product
        product = db.query(Product).filter(Product.barcode == str(sku).strip()).first()
        if product:
            return product
    if product_name:
        name = str(product_name).strip()
        product = db.query(Product).filter(Product.name.ilike(name)).first()
        if product:
            return product
        product = (
            db.query(Product)
            .filter(Product.name.ilike(f"%{name}%"))
            .order_by(Product.id.asc())
            .first()
        )
        if product:
            return product
    return None


def preview_sales_file(db: Session, filename: str, content: bytes) -> dict:
    df = read_sales_dataframe(filename, content)
    mapping = _map_columns(list(df.columns))
    if "quantity" not in mapping or ("sku" not in mapping and "product_name" not in mapping):
        raise ValueError(
            "Could not detect required columns. Need Quantity plus SKU or Product name. "
            f"Found columns: {list(df.columns)}"
        )

    rows = []
    matched = unmatched = 0
    total_qty = 0.0
    for idx, record in df.iterrows():
        row_number = int(idx) + 2  # header is row 1
        sku = str(record[mapping["sku"]]).strip() if "sku" in mapping else None
        if sku in ("", "nan", "None"):
            sku = None
        product_name = str(record[mapping["product_name"]]).strip() if "product_name" in mapping else None
        if product_name in ("", "nan", "None"):
            product_name = None
        qty = _to_float(record[mapping["quantity"]], 0)
        unit_price = _to_float(record[mapping["unit_price"]], 0) if "unit_price" in mapping else None
        invoice_no = str(record[mapping["invoice_no"]]).strip() if "invoice_no" in mapping else None
        sale_date = _parse_date(record[mapping["sale_date"]]) if "sale_date" in mapping else None
        customer = str(record[mapping["customer"]]).strip() if "customer" in mapping else None

        if "processed" in mapping:
            processed = str(record[mapping["processed"]]).strip().lower()
            if processed in {"yes", "y", "true", "1", "processed", "done"}:
                rows.append({
                    "row_number": row_number,
                    "invoice_no": invoice_no,
                    "sale_date": sale_date.isoformat() if sale_date else None,
                    "sku": sku,
                    "product_name": product_name,
                    "quantity": qty,
                    "unit_price": unit_price,
                    "customer": customer,
                    "matched_product_id": None,
                    "matched_product_name": None,
                    "current_stock": None,
                    "status": "skipped",
                    "message": "Already marked Processed in file",
                })
                continue

        if qty <= 0:
            rows.append({
                "row_number": row_number,
                "invoice_no": invoice_no,
                "sale_date": sale_date.isoformat() if sale_date else None,
                "sku": sku,
                "product_name": product_name,
                "quantity": qty,
                "unit_price": unit_price,
                "customer": customer,
                "matched_product_id": None,
                "matched_product_name": None,
                "current_stock": None,
                "status": "error",
                "message": "Invalid quantity",
            })
            unmatched += 1
            continue

        product = find_product(db, sku, product_name)
        if not product:
            unmatched += 1
            rows.append({
                "row_number": row_number,
                "invoice_no": invoice_no,
                "sale_date": sale_date.isoformat() if sale_date else None,
                "sku": sku,
                "product_name": product_name,
                "quantity": qty,
                "unit_price": unit_price,
                "customer": customer,
                "matched_product_id": None,
                "matched_product_name": None,
                "current_stock": None,
                "status": "unmatched",
                "message": "No matching product in inventory",
            })
            continue

        matched += 1
        total_qty += qty
        rows.append({
            "row_number": row_number,
            "invoice_no": invoice_no,
            "sale_date": sale_date.isoformat() if sale_date else None,
            "sku": sku or product.sku,
            "product_name": product_name or product.name,
            "quantity": qty,
            "unit_price": unit_price if unit_price is not None else product.sell_price,
            "customer": customer,
            "matched_product_id": product.id,
            "matched_product_name": product.name,
            "current_stock": product.stock_qty,
            "status": "matched",
            "message": f"Will deduct {qty} from stock ({product.stock_qty})",
        })

    return {
        "filename": filename,
        "rows": rows,
        "matched_count": matched,
        "unmatched_count": unmatched,
        "total_qty": total_qty,
    }


def import_sales_file(
    db: Session,
    filename: str,
    content: bytes,
    deduct_stock: bool = True,
    skip_processed: bool = True,
) -> dict:
    df = read_sales_dataframe(filename, content)
    mapping = _map_columns(list(df.columns))
    if "quantity" not in mapping or ("sku" not in mapping and "product_name" not in mapping):
        raise ValueError(
            "Could not detect required columns. Need Quantity plus SKU or Product name. "
            f"Found columns: {list(df.columns)}"
        )

    batch = ImportBatch(
        filename=filename,
        file_type=filename.rsplit(".", 1)[-1].lower(),
        status="processing",
        rows_total=len(df),
    )
    db.add(batch)
    db.flush()

    # Group line items by invoice so one sale can have many products
    grouped: dict[str, list[dict]] = defaultdict(list)
    unmatched: list[str] = []
    skipped = 0
    imported_rows = 0
    stock_deducted = 0.0

    for idx, record in df.iterrows():
        sku = str(record[mapping["sku"]]).strip() if "sku" in mapping else None
        if sku in ("", "nan", "None"):
            sku = None
        product_name = str(record[mapping["product_name"]]).strip() if "product_name" in mapping else None
        if product_name in ("", "nan", "None"):
            product_name = None
        qty = _to_float(record[mapping["quantity"]], 0)
        unit_price = _to_float(record[mapping["unit_price"]], 0) if "unit_price" in mapping else None
        invoice_no = str(record[mapping["invoice_no"]]).strip() if "invoice_no" in mapping else None
        sale_date = _parse_date(record[mapping["sale_date"]]) if "sale_date" in mapping else datetime.utcnow()
        customer_name = str(record[mapping["customer"]]).strip() if "customer" in mapping else None

        if skip_processed and "processed" in mapping:
            processed = str(record[mapping["processed"]]).strip().lower()
            if processed in {"yes", "y", "true", "1", "processed", "done"}:
                skipped += 1
                continue

        if qty <= 0:
            skipped += 1
            continue

        product = find_product(db, sku, product_name)
        if not product:
            label = sku or product_name or f"row-{idx}"
            unmatched.append(str(label))
            skipped += 1
            continue

        # KYGS SALES has no invoice column — group by calendar day
        if invoice_no and invoice_no not in ("", "nan", "None"):
            key = invoice_no
        else:
            day = (sale_date or datetime.utcnow()).strftime("%Y-%m-%d")
            key = f"KYGS-{day.replace('-', '')}"
        grouped[key].append({
            "product": product,
            "qty": qty,
            "unit_price": unit_price if unit_price not in (None, 0) else product.sell_price,
            "sale_date": sale_date or datetime.utcnow(),
            "customer_name": customer_name,
            "invoice_no": invoice_no,
        })
        imported_rows += 1

    sales_created = 0
    for invoice_key, lines in grouped.items():
        existing = db.query(Sale).filter(Sale.invoice_no == invoice_key).first()
        if existing:
            # Append as unique imported invoice to avoid duplicates
            invoice_key = f"{invoice_key}-IMP{batch.id}-{sales_created + 1}"

        customer_id = None
        customer_name = lines[0].get("customer_name")
        if customer_name and customer_name not in ("", "nan", "None"):
            customer = db.query(Customer).filter(Customer.name.ilike(customer_name)).first()
            if not customer:
                customer = Customer(name=customer_name)
                db.add(customer)
                db.flush()
            customer_id = customer.id

        sale = Sale(
            invoice_no=invoice_key,
            sale_date=lines[0]["sale_date"],
            customer_id=customer_id,
            payment_method="cash",
            payment_status="paid",
            source="import",
            import_batch_id=batch.id,
            notes=f"Imported from {filename}",
        )
        subtotal = 0.0
        for line in lines:
            product: Product = line["product"]
            qty = float(line["qty"])
            unit_price = float(line["unit_price"])
            line_total = qty * unit_price
            subtotal += line_total
            sale.items.append(
                SaleItem(
                    product_id=product.id,
                    sku=product.sku,
                    product_name=product.name,
                    quantity=qty,
                    unit_price=unit_price,
                    cost_price=product.cost_price,
                    line_total=line_total,
                )
            )
            if deduct_stock:
                apply_stock_change(
                    db,
                    product,
                    -qty,
                    movement_type="import",
                    reference=invoice_key,
                    notes=f"Stock deducted from sales file import ({filename})",
                )
                stock_deducted += qty
        sale.subtotal = subtotal
        sale.total = subtotal
        sale.amount_paid = subtotal
        db.add(sale)
        sales_created += 1

    batch.rows_imported = imported_rows
    batch.rows_skipped = skipped
    batch.stock_deducted = stock_deducted
    batch.unmatched_skus = json.dumps(sorted(set(unmatched)))
    batch.summary = (
        f"Created {sales_created} sales; imported {imported_rows} lines; "
        f"skipped {skipped}; deducted {stock_deducted} units from stock"
    )
    batch.status = "completed"
    db.commit()
    db.refresh(batch)

    return {
        "batch_id": batch.id,
        "filename": filename,
        "rows_total": batch.rows_total,
        "rows_imported": batch.rows_imported,
        "rows_skipped": batch.rows_skipped,
        "stock_deducted": batch.stock_deducted,
        "unmatched_skus": sorted(set(unmatched)),
        "sales_created": sales_created,
        "message": batch.summary,
    }


def import_sales_rows(
    db: Session,
    filename: str,
    rows: list[dict],
    deduct_stock: bool = True,
) -> dict:
    """Import corrected/previewed sales rows (CSV confirm or OCR review).

    Each row may include ``matched_product_id`` (preferred), or sku/product_name.
    Blank / zero-qty rows are skipped.
    """
    batch = ImportBatch(
        filename=filename,
        file_type=filename.rsplit(".", 1)[-1].lower() if "." in filename else "ocr",
        status="processing",
        rows_total=len(rows),
    )
    db.add(batch)
    db.flush()

    grouped: dict[str, list[dict]] = defaultdict(list)
    unmatched: list[str] = []
    skipped = 0
    imported_rows = 0
    stock_deducted = 0.0

    for row in rows:
        qty = _to_float(row.get("quantity"), 0)
        if qty <= 0:
            skipped += 1
            continue
        if row.get("include") is False:
            skipped += 1
            continue

        product = None
        pid = row.get("matched_product_id") or row.get("product_id")
        if pid:
            product = db.query(Product).get(int(pid))
        if not product:
            product = find_product(db, row.get("sku"), row.get("product_name"))
        if not product:
            label = row.get("sku") or row.get("product_name") or f"row-{row.get('row_number')}"
            unmatched.append(str(label))
            skipped += 1
            continue

        sale_date = _parse_date(row.get("sale_date")) or datetime.utcnow()
        invoice_no = row.get("invoice_no")
        if invoice_no:
            invoice_no = str(invoice_no).strip()
            if invoice_no in ("", "nan", "None"):
                invoice_no = None
        if invoice_no:
            key = invoice_no
        else:
            day = sale_date.strftime("%Y-%m-%d")
            key = f"OCR-{day.replace('-', '')}"

        unit_price = row.get("unit_price")
        unit_price = _to_float(unit_price, 0) if unit_price not in (None, "") else product.sell_price
        if unit_price <= 0:
            unit_price = product.sell_price

        grouped[key].append({
            "product": product,
            "qty": qty,
            "unit_price": unit_price,
            "sale_date": sale_date,
            "customer_name": row.get("customer"),
            "invoice_no": invoice_no,
        })
        imported_rows += 1

    sales_created = 0
    for invoice_key, lines in grouped.items():
        existing = db.query(Sale).filter(Sale.invoice_no == invoice_key).first()
        if existing:
            invoice_key = f"{invoice_key}-IMP{batch.id}-{sales_created + 1}"

        customer_id = None
        customer_name = lines[0].get("customer_name")
        if customer_name and str(customer_name).strip() not in ("", "nan", "None"):
            customer = db.query(Customer).filter(Customer.name.ilike(str(customer_name).strip())).first()
            if not customer:
                customer = Customer(name=str(customer_name).strip())
                db.add(customer)
                db.flush()
            customer_id = customer.id

        sale = Sale(
            invoice_no=invoice_key,
            sale_date=lines[0]["sale_date"],
            customer_id=customer_id,
            payment_method="cash",
            payment_status="paid",
            source="import",
            import_batch_id=batch.id,
            notes=f"Imported from {filename}",
        )
        subtotal = 0.0
        for line in lines:
            product: Product = line["product"]
            qty = float(line["qty"])
            unit_price = float(line["unit_price"])
            line_total = qty * unit_price
            subtotal += line_total
            sale.items.append(
                SaleItem(
                    product_id=product.id,
                    sku=product.sku,
                    product_name=product.name,
                    quantity=qty,
                    unit_price=unit_price,
                    cost_price=product.cost_price,
                    line_total=line_total,
                )
            )
            if deduct_stock and not str(product.sku).upper().startswith("LABOR"):
                apply_stock_change(
                    db,
                    product,
                    -qty,
                    movement_type="import",
                    reference=invoice_key,
                    notes=f"Stock deducted from sales import ({filename})",
                )
                stock_deducted += qty
        sale.subtotal = subtotal
        sale.total = subtotal
        sale.amount_paid = subtotal
        db.add(sale)
        sales_created += 1

    if imported_rows == 0 and sales_created == 0:
        batch.status = "failed"
        batch.summary = "No valid rows to import — select products and quantities first"
        batch.rows_imported = 0
        batch.rows_skipped = skipped
        db.commit()
        raise ValueError(batch.summary)

    batch.rows_imported = imported_rows
    batch.rows_skipped = skipped
    batch.stock_deducted = stock_deducted
    batch.unmatched_skus = json.dumps(sorted(set(unmatched)))
    batch.summary = (
        f"Created {sales_created} sales; imported {imported_rows} lines; "
        f"skipped {skipped}; deducted {stock_deducted} units from stock"
    )
    batch.status = "completed"
    db.commit()
    db.refresh(batch)

    return {
        "batch_id": batch.id,
        "filename": filename,
        "rows_total": batch.rows_total,
        "rows_imported": batch.rows_imported,
        "rows_skipped": batch.rows_skipped,
        "stock_deducted": batch.stock_deducted,
        "unmatched_skus": sorted(set(unmatched)),
        "sales_created": sales_created,
        "message": batch.summary,
    }


def import_purchase_rows(
    db: Session,
    filename: str,
    rows: list[dict],
    supplier_id: Optional[int] = None,
    notes: Optional[str] = None,
    purchase_date: Optional[Any] = None,
) -> dict:
    """Post corrected OCR/manual rows as a stock-receiving purchase."""
    from app.models.models import Purchase, PurchaseItem

    def _next_po() -> str:
        last = db.query(Purchase).order_by(Purchase.id.desc()).first()
        if not last or not last.po_no:
            return "PO-1001"
        digits = "".join(ch for ch in last.po_no if ch.isdigit())
        n = int(digits or "1000") + 1
        return f"PO-{n}"

    batch = ImportBatch(
        filename=filename,
        file_type=filename.rsplit(".", 1)[-1].lower() if "." in filename else "ocr",
        status="processing",
        rows_total=len(rows),
    )
    db.add(batch)
    db.flush()

    parsed_date = _parse_date(purchase_date) if purchase_date else None
    lines: list[dict] = []
    unmatched: list[str] = []
    skipped = 0

    for row in rows:
        qty = _to_float(row.get("quantity"), 0)
        if qty <= 0 or row.get("include") is False:
            skipped += 1
            continue
        product = None
        pid = row.get("matched_product_id") or row.get("product_id")
        if pid:
            product = db.query(Product).get(int(pid))
        if not product:
            product = find_product(db, row.get("sku"), row.get("product_name"))
        if not product:
            label = row.get("sku") or row.get("product_name") or f"row-{row.get('row_number')}"
            unmatched.append(str(label))
            skipped += 1
            continue

        row_date = _parse_date(row.get("purchase_date") or row.get("sale_date"))
        if row_date and not parsed_date:
            parsed_date = row_date

        cost = row.get("unit_cost")
        if cost in (None, ""):
            cost = row.get("unit_price")
        unit_cost = _to_float(cost, 0)
        if unit_cost <= 0:
            unit_cost = float(product.cost_price or 0)

        lines.append({"product": product, "qty": qty, "unit_cost": unit_cost})

    if not lines:
        batch.status = "failed"
        batch.summary = "No valid purchase lines — select products and quantities first"
        batch.rows_imported = 0
        batch.rows_skipped = skipped
        db.commit()
        raise ValueError(batch.summary)

    po_no = _next_po()
    purchase = Purchase(
        po_no=po_no,
        purchase_date=parsed_date or datetime.utcnow(),
        supplier_id=supplier_id,
        notes=notes or f"Imported from {filename}",
    )
    subtotal = 0.0
    stock_added = 0.0
    for line in lines:
        product = line["product"]
        qty = float(line["qty"])
        unit_cost = float(line["unit_cost"])
        line_total = qty * unit_cost
        subtotal += line_total
        purchase.items.append(
            PurchaseItem(
                product_id=product.id,
                quantity=qty,
                unit_cost=unit_cost,
                line_total=line_total,
            )
        )
        product.cost_price = unit_cost
        apply_stock_change(
            db,
            product,
            qty,
            movement_type="purchase",
            reference=po_no,
            notes=f"Stock received from purchase OCR/import ({filename})",
        )
        stock_added += qty

    purchase.subtotal = subtotal
    purchase.total = subtotal
    db.add(purchase)

    batch.rows_imported = len(lines)
    batch.rows_skipped = skipped
    batch.stock_deducted = 0
    batch.unmatched_skus = json.dumps(sorted(set(unmatched)))
    batch.summary = (
        f"Created purchase {po_no}; imported {len(lines)} lines; "
        f"skipped {skipped}; added {stock_added} units to stock"
    )
    batch.status = "completed"
    db.commit()
    db.refresh(batch)

    return {
        "batch_id": batch.id,
        "filename": filename,
        "po_no": po_no,
        "rows_imported": len(lines),
        "rows_skipped": skipped,
        "stock_added": stock_added,
        "unmatched_skus": sorted(set(unmatched)),
        "purchases_created": 1,
        "message": batch.summary,
    }