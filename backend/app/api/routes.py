from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session, joinedload
from pathlib import Path

from app.core.database import get_db
from app.services import analytics, forecast
from sqlalchemy import func

from app.models.models import (
    Category,
    Customer,
    ImportBatch,
    Job,
    JobLine,
    Product,
    Purchase,
    PurchaseItem,
    Sale,
    SaleItem,
    Supplier,
)
from app.schemas import (
    CategoryCreate,
    JobCancel,
    JobCheckout,
    JobCreate,
    JobLineIn,
    JobUpdate,
    CategoryOut,
    CustomerCreate,
    CustomerOut,
    DashboardOut,
    ImportBatchOut,
    ImportPreviewOut,
    ImportResultOut,
    InventoryReportOut,
    OcrPreviewOut,
    PeriodReportOut,
    ProductCreate,
    ProductOut,
    ProductUpdate,
    PurchaseCreate,
    PurchaseImportResultOut,
    PurchaseOut,
    PurchaseRowsImportIn,
    PurchaseUpdate,
    SaleCreate,
    SaleItemIn,
    SaleOut,
    SalesRowsImportIn,
    StockAdjust,
    SupplierCreate,
    SupplierOut,
    WorkbookImportOut,
    StockPreviewOut,
    StockImportOut,
    ProductPerformanceOut,
)
from app.services import reports as report_service
from app.services.import_sales import import_purchase_rows, import_sales_file, import_sales_rows, preview_sales_file
from app.services.import_stock import import_stock_file, preview_stock_file
from app.services.kygs_import import import_kygs_workbook
from app.services.ocr_sales import preview_sales_photo, suggest_products
from app.services.seed import purge_hardcoded_demo
from app.services.stock import apply_stock_change, stock_status

router = APIRouter()


@router.post("/admin/purge-demo")
def admin_purge_demo(force: bool = Query(False), db: Session = Depends(get_db)):
    """Remove leftover hard-coded demo inventory/sales from older builds.

    Pass force=true to run again even if already cleared once.
    """
    if force:
        from app.models.models import AppMeta

        db.query(AppMeta).filter(AppMeta.key == "demo_cleared").delete()
        db.commit()
    return purge_hardcoded_demo(db)


def _product_out(p: Product) -> ProductOut:
    return ProductOut(
        id=p.id,
        sku=p.sku,
        name=p.name,
        brand=p.brand,
        category_id=p.category_id,
        supplier_id=p.supplier_id,
        description=p.description,
        fitment=p.fitment,
        unit=p.unit,
        cost_price=p.cost_price,
        sell_price=p.sell_price,
        stock_qty=p.stock_qty,
        reorder_level=p.reorder_level,
        location=p.location,
        barcode=p.barcode,
        is_active=p.is_active,
        category_name=p.category.name if p.category else None,
        supplier_name=p.supplier.name if p.supplier else None,
        stock_status=stock_status(p),
    )


def _sale_out(s: Sale) -> SaleOut:
    return SaleOut(
        id=s.id,
        invoice_no=s.invoice_no,
        sale_date=s.sale_date,
        customer_id=s.customer_id,
        customer_name=s.customer.name if s.customer else None,
        payment_method=s.payment_method,
        payment_status=s.payment_status,
        amount_paid=s.amount_paid,
        subtotal=s.subtotal,
        discount=s.discount,
        tax=s.tax,
        total=s.total,
        notes=s.notes,
        source=s.source,
        items=[
            {
                "id": i.id,
                "product_id": i.product_id,
                "sku": i.sku,
                "product_name": i.product_name,
                "quantity": i.quantity,
                "unit_price": i.unit_price,
                "cost_price": i.cost_price,
                "discount": i.discount or 0.0,
                "line_total": i.line_total,
            }
            for i in s.items
        ],
    )


def _purchase_out(p: Purchase) -> PurchaseOut:
    return PurchaseOut(
        id=p.id,
        po_no=p.po_no,
        purchase_date=p.purchase_date,
        supplier_id=p.supplier_id,
        supplier_name=p.supplier.name if p.supplier else None,
        subtotal=p.subtotal,
        total=p.total,
        notes=p.notes,
        has_receipt=bool(getattr(p, "receipt_path", None)),
        receipt_filename=getattr(p, "receipt_filename", None),
        items=[
            {
                "id": i.id,
                "product_id": i.product_id,
                "product_name": i.product.name if i.product else None,
                "sku": i.product.sku if i.product else None,
                "quantity": i.quantity,
                "unit_cost": i.unit_cost,
                "line_total": i.line_total,
            }
            for i in p.items
        ],
    )


def _next_no(db: Session, model, field: str, prefix: str) -> str:
    count = db.query(model).count() + 1
    return f"{prefix}-{1000 + count}"


# ---- Masters ----
@router.get("/categories", response_model=list[CategoryOut])
def list_categories(db: Session = Depends(get_db)):
    return db.query(Category).order_by(Category.name).all()


@router.post("/categories", response_model=CategoryOut)
def create_category(payload: CategoryCreate, db: Session = Depends(get_db)):
    if db.query(Category).filter(Category.name == payload.name).first():
        raise HTTPException(400, "Category already exists")
    obj = Category(**payload.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.get("/suppliers", response_model=list[SupplierOut])
def list_suppliers(db: Session = Depends(get_db)):
    return db.query(Supplier).order_by(Supplier.name).all()


@router.post("/suppliers", response_model=SupplierOut)
def create_supplier(payload: SupplierCreate, db: Session = Depends(get_db)):
    obj = Supplier(**payload.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.get("/customers", response_model=list[CustomerOut])
def list_customers(q: Optional[str] = None, db: Session = Depends(get_db)):
    query = db.query(Customer)
    if q:
        like = f"%{q}%"
        query = query.filter((Customer.name.ilike(like)) | (Customer.phone.ilike(like)))
    return query.order_by(Customer.name).all()


@router.post("/customers", response_model=CustomerOut)
def create_customer(payload: CustomerCreate, db: Session = Depends(get_db)):
    obj = Customer(**payload.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


# ---- Products / Inventory ----
@router.get("/products", response_model=list[ProductOut])
def list_products(
    q: Optional[str] = None,
    category_id: Optional[int] = None,
    low_stock: bool = False,
    include_inactive: bool = False,
    db: Session = Depends(get_db),
):
    query = db.query(Product).options(joinedload(Product.category), joinedload(Product.supplier))
    if not include_inactive:
        query = query.filter(Product.is_active.is_(True))
    if q:
        like = f"%{q}%"
        query = query.filter(
            (Product.name.ilike(like))
            | (Product.sku.ilike(like))
            | (Product.brand.ilike(like))
            | (Product.fitment.ilike(like))
        )
    if category_id:
        query = query.filter(Product.category_id == category_id)
    products = query.order_by(Product.name).all()
    if low_stock:
        products = [p for p in products if stock_status(p) in {"low", "out"}]
    return [_product_out(p) for p in products]


@router.post("/products", response_model=ProductOut)
def create_product(payload: ProductCreate, db: Session = Depends(get_db)):
    if db.query(Product).filter(Product.sku == payload.sku).first():
        raise HTTPException(400, "SKU already exists")
    obj = Product(**payload.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    obj = (
        db.query(Product)
        .options(joinedload(Product.category), joinedload(Product.supplier))
        .get(obj.id)
    )
    return _product_out(obj)


@router.put("/products/{product_id}", response_model=ProductOut)
def update_product(product_id: int, payload: ProductUpdate, db: Session = Depends(get_db)):
    obj = db.query(Product).get(product_id)
    if not obj:
        raise HTTPException(404, "Product not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(obj, key, value)
    db.commit()
    obj = (
        db.query(Product)
        .options(joinedload(Product.category), joinedload(Product.supplier))
        .get(product_id)
    )
    return _product_out(obj)


@router.post("/products/{product_id}/adjust", response_model=ProductOut)
def adjust_stock(product_id: int, payload: StockAdjust, db: Session = Depends(get_db)):
    obj = db.query(Product).get(product_id)
    if not obj:
        raise HTTPException(404, "Product not found")
    apply_stock_change(db, obj, payload.quantity_change, "adjust", notes=payload.notes)
    db.commit()
    obj = (
        db.query(Product)
        .options(joinedload(Product.category), joinedload(Product.supplier))
        .get(product_id)
    )
    return _product_out(obj)


@router.delete("/products/{product_id}")
def delete_product(
    product_id: int,
    hard: bool = Query(False),
    db: Session = Depends(get_db),
):
    """Delete stock item. Soft-deletes by default (is_active=false, stock zeroed).
    hard=true permanently removes if unused in sales/purchases."""
    obj = db.query(Product).get(product_id)
    if not obj:
        raise HTTPException(404, "Product not found")
    if hard:
        from app.models.models import SaleItem, PurchaseItem, StockMovement
        used = (
            db.query(SaleItem).filter(SaleItem.product_id == product_id).first()
            or db.query(PurchaseItem).filter(PurchaseItem.product_id == product_id).first()
        )
        if used:
            raise HTTPException(400, "Product is used in sales/purchases — use soft delete")
        db.query(StockMovement).filter(StockMovement.product_id == product_id).delete()
        db.delete(obj)
        db.commit()
        return {"ok": True, "mode": "hard", "id": product_id}
    # soft delete
    if float(obj.stock_qty or 0) != 0:
        apply_stock_change(db, obj, -float(obj.stock_qty or 0), "adjust", notes="Deleted / cleared stock")
    obj.is_active = False
    db.commit()
    return {"ok": True, "mode": "soft", "id": product_id}


# ---- Sales ----
@router.get("/sales", response_model=list[SaleOut])
def list_sales(
    limit: int = 200,
    q: Optional[str] = None,
    period: Optional[str] = None,
    year: Optional[int] = None,
    month: Optional[int] = None,
    db: Session = Depends(get_db),
):
    query = db.query(Sale).options(joinedload(Sale.customer), joinedload(Sale.items))
    if period in {"daily", "weekly", "monthly", "yearly"}:
        from app.services.reports import _period_bounds
        start, end = _period_bounds(period, year, month)
        query = query.filter(Sale.sale_date >= start, Sale.sale_date <= end)
    sales = query.order_by(Sale.sale_date.desc()).limit(limit).all()
    if q:
        like = q.strip().lower()
        filtered = []
        for s in sales:
            hay = " ".join(
                [
                    s.invoice_no or "",
                    s.customer.name if s.customer else "",
                    *[f"{i.sku or ''} {i.product_name or ''}" for i in s.items],
                ]
            ).lower()
            if like in hay:
                filtered.append(s)
        sales = filtered
    return [_sale_out(s) for s in sales]


@router.get("/sales/{sale_id}", response_model=SaleOut)
def get_sale(sale_id: int, db: Session = Depends(get_db)):
    sale = (
        db.query(Sale)
        .options(joinedload(Sale.customer), joinedload(Sale.items))
        .get(sale_id)
    )
    if not sale:
        raise HTTPException(404, "Sale not found")
    return _sale_out(sale)


@router.post("/sales", response_model=SaleOut)
def create_sale(payload: SaleCreate, db: Session = Depends(get_db)):
    if not payload.items:
        raise HTTPException(400, "Sale requires at least one item")
    sale = Sale(
        invoice_no=_next_no(db, Sale, "invoice_no", "SI"),
        sale_date=payload.sale_date or datetime.utcnow(),
        customer_id=payload.customer_id,
        payment_method=payload.payment_method,
        payment_status=payload.payment_status,
        discount=payload.discount,
        tax=payload.tax,
        notes=payload.notes,
        source="manual",
    )
    subtotal = 0.0
    for item in payload.items:
        product = db.query(Product).get(item.product_id)
        if not product:
            raise HTTPException(400, f"Product {item.product_id} not found")
        unit_price = item.unit_price if item.unit_price is not None else product.sell_price
        gross = item.quantity * unit_price
        discount = min(max(item.discount, 0.0), gross)   # never below zero
        line_total = gross - discount
        subtotal += line_total
        sale.items.append(
            SaleItem(
                product_id=product.id,
                sku=product.sku,
                product_name=product.name,
                quantity=item.quantity,
                unit_price=unit_price,
                cost_price=product.cost_price,
                discount=discount,
                line_total=line_total,
            )
        )
        if not product.sku.startswith("LABOR"):
            apply_stock_change(
                db,
                product,
                -item.quantity,
                "sale",
                reference=sale.invoice_no,
            )
    sale.subtotal = subtotal
    sale.total = subtotal - payload.discount + payload.tax
    sale.amount_paid = payload.amount_paid if payload.amount_paid is not None else sale.total
    db.add(sale)
    db.commit()
    sale = (
        db.query(Sale)
        .options(joinedload(Sale.customer), joinedload(Sale.items))
        .get(sale.id)
    )
    return _sale_out(sale)


# ---- Purchases ----
@router.get("/purchases", response_model=list[PurchaseOut])
def list_purchases(db: Session = Depends(get_db)):
    rows = (
        db.query(Purchase)
        .options(joinedload(Purchase.supplier), joinedload(Purchase.items).joinedload(PurchaseItem.product))
        .order_by(Purchase.purchase_date.desc())
        .all()
    )
    return [_purchase_out(p) for p in rows]


@router.get("/purchases/{purchase_id}", response_model=PurchaseOut)
def get_purchase(purchase_id: int, db: Session = Depends(get_db)):
    purchase = (
        db.query(Purchase)
        .options(joinedload(Purchase.supplier), joinedload(Purchase.items).joinedload(PurchaseItem.product))
        .get(purchase_id)
    )
    if not purchase:
        raise HTTPException(404, "Purchase not found")
    return _purchase_out(purchase)


@router.post("/purchases", response_model=PurchaseOut)
def create_purchase(payload: PurchaseCreate, db: Session = Depends(get_db)):
    if not payload.items:
        raise HTTPException(400, "Purchase requires items")
    purchase = Purchase(
        po_no=_next_no(db, Purchase, "po_no", "PO"),
        purchase_date=(
            (payload.purchase_date.replace(tzinfo=None) if payload.purchase_date.tzinfo else payload.purchase_date)
            if payload.purchase_date
            else datetime.utcnow()
        ),
        supplier_id=payload.supplier_id,
        notes=payload.notes,
    )
    subtotal = 0.0
    for item in payload.items:
        product = db.query(Product).get(item.product_id)
        if not product:
            raise HTTPException(400, f"Product {item.product_id} not found")
        unit_cost = item.unit_cost if item.unit_cost is not None else product.cost_price
        line_total = item.quantity * unit_cost
        subtotal += line_total
        purchase.items.append(
            PurchaseItem(
                product_id=product.id,
                quantity=item.quantity,
                unit_cost=unit_cost,
                line_total=line_total,
            )
        )
        product.cost_price = unit_cost
        apply_stock_change(db, product, item.quantity, "purchase", reference=purchase.po_no)
    purchase.subtotal = subtotal
    purchase.total = subtotal
    db.add(purchase)
    db.commit()
    purchase = (
        db.query(Purchase)
        .options(joinedload(Purchase.supplier), joinedload(Purchase.items).joinedload(PurchaseItem.product))
        .get(purchase.id)
    )
    return _purchase_out(purchase)


@router.put("/purchases/{purchase_id}", response_model=PurchaseOut)
def update_purchase(purchase_id: int, payload: PurchaseUpdate, db: Session = Depends(get_db)):
    """Edit purchase header + line items; stock is adjusted by quantity deltas."""
    purchase = (
        db.query(Purchase)
        .options(joinedload(Purchase.supplier), joinedload(Purchase.items).joinedload(PurchaseItem.product))
        .filter(Purchase.id == purchase_id)
        .first()
    )
    if not purchase:
        raise HTTPException(404, "Purchase not found")
    if not payload.items:
        raise HTTPException(400, "Purchase requires at least one item")

    # Always apply header fields from the edit payload (frontend sends full form).
    purchase.supplier_id = payload.supplier_id
    purchase.notes = payload.notes
    if payload.purchase_date is not None:
        # Strip tzinfo so SQLite stores the wall-clock time the user picked.
        pdt = payload.purchase_date
        purchase.purchase_date = pdt.replace(tzinfo=None) if getattr(pdt, "tzinfo", None) else pdt

    old_items = {i.id: i for i in list(purchase.items)}
    seen_ids: set[int] = set()
    subtotal = 0.0

    for item in payload.items:
        product = db.get(Product, item.product_id)
        if not product:
            raise HTTPException(400, f"Product {item.product_id} not found")
        unit_cost = item.unit_cost if item.unit_cost is not None else product.cost_price
        qty = float(item.quantity)
        if qty <= 0:
            raise HTTPException(400, "Quantity must be greater than 0")
        line_total = qty * unit_cost
        subtotal += line_total

        old = old_items.get(item.id) if item.id else None
        if old and old.product_id == item.product_id:
            delta = qty - float(old.quantity)
            if abs(delta) > 1e-9:
                apply_stock_change(
                    db,
                    product,
                    delta,
                    "adjust",
                    reference=purchase.po_no,
                    notes=f"Purchase {purchase.po_no} line edited",
                )
            old.quantity = qty
            old.unit_cost = unit_cost
            old.line_total = line_total
            seen_ids.add(old.id)
        else:
            if old:
                old_product = db.get(Product, old.product_id)
                if old_product:
                    apply_stock_change(
                        db,
                        old_product,
                        -float(old.quantity),
                        "adjust",
                        reference=purchase.po_no,
                        notes=f"Purchase {purchase.po_no} line replaced",
                    )
                db.delete(old)
                seen_ids.add(old.id)
            apply_stock_change(
                db,
                product,
                qty,
                "purchase",
                reference=purchase.po_no,
                notes=f"Purchase {purchase.po_no} line added/updated",
            )
            purchase.items.append(
                PurchaseItem(
                    product_id=product.id,
                    quantity=qty,
                    unit_cost=unit_cost,
                    line_total=line_total,
                )
            )
        product.cost_price = unit_cost

    # Removed lines → reverse stock and delete
    for oid, old in old_items.items():
        if oid not in seen_ids:
            old_product = db.get(Product, old.product_id)
            if old_product:
                apply_stock_change(
                    db,
                    old_product,
                    -float(old.quantity),
                    "adjust",
                    reference=purchase.po_no,
                    notes=f"Purchase {purchase.po_no} line removed",
                )
            db.delete(old)

    purchase.subtotal = subtotal
    purchase.total = subtotal
    db.add(purchase)
    db.commit()
    db.expire_all()
    purchase = (
        db.query(Purchase)
        .options(joinedload(Purchase.supplier), joinedload(Purchase.items).joinedload(PurchaseItem.product))
        .filter(Purchase.id == purchase_id)
        .first()
    )
    return _purchase_out(purchase)


@router.post("/purchases/{purchase_id}/receipt")
async def upload_purchase_receipt(
    purchase_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Attach a receipt photo/PDF to an existing purchase entry."""
    from app.core.config import settings

    purchase = db.query(Purchase).get(purchase_id)
    if not purchase:
        raise HTTPException(404, "Purchase not found")
    filename = file.filename or "receipt.jpg"
    lower = filename.lower()
    if not any(lower.endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".webp", ".pdf", ".gif", ".bmp")):
        if not (file.content_type or "").startswith(("image/", "application/pdf")):
            raise HTTPException(400, "Upload an image or PDF receipt")
    content = await file.read()
    if not content:
        raise HTTPException(400, "Empty file")
    if len(content) > 15 * 1024 * 1024:
        raise HTTPException(400, "Receipt too large (max 15MB)")

    receipts_dir = settings.upload_dir / "receipts"
    receipts_dir.mkdir(parents=True, exist_ok=True)
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in filename)[:120]
    stored = f"po{purchase_id}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{safe}"
    dest = receipts_dir / stored
    dest.write_bytes(content)

    # Remove previous receipt file if present
    old = getattr(purchase, "receipt_path", None)
    if old:
        try:
            Path(old).unlink(missing_ok=True)
        except Exception:
            pass

    purchase.receipt_filename = filename
    purchase.receipt_path = str(dest)
    db.commit()
    return {
        "ok": True,
        "purchase_id": purchase_id,
        "receipt_filename": filename,
        "has_receipt": True,
        "message": f"Receipt attached to {purchase.po_no}",
    }


@router.get("/purchases/{purchase_id}/receipt")
def get_purchase_receipt(purchase_id: int, db: Session = Depends(get_db)):
    purchase = db.query(Purchase).get(purchase_id)
    if not purchase:
        raise HTTPException(404, "Purchase not found")
    path = getattr(purchase, "receipt_path", None)
    if not path or not Path(path).exists():
        raise HTTPException(404, "No receipt uploaded for this purchase")
    return FileResponse(
        path,
        filename=purchase.receipt_filename or Path(path).name,
        media_type=None,
    )


@router.delete("/purchases/{purchase_id}/receipt")
def delete_purchase_receipt(purchase_id: int, db: Session = Depends(get_db)):
    purchase = db.query(Purchase).get(purchase_id)
    if not purchase:
        raise HTTPException(404, "Purchase not found")
    path = getattr(purchase, "receipt_path", None)
    if path:
        try:
            Path(path).unlink(missing_ok=True)
        except Exception:
            pass
    purchase.receipt_path = None
    purchase.receipt_filename = None
    db.commit()
    return {"ok": True, "purchase_id": purchase_id, "has_receipt": False}


# ---- Reports ----
@router.get("/reports/dashboard", response_model=DashboardOut)
def get_dashboard(
    year: Optional[int] = None,
    month: Optional[int] = None,
    db: Session = Depends(get_db),
):
    return report_service.dashboard(db, year=year, month=month)


@router.get("/reports/product-performance", response_model=ProductPerformanceOut)
def get_product_performance(
    period: str = Query("monthly", pattern="^(weekly|monthly|yearly)$"),
    year: Optional[int] = None,
    month: Optional[int] = None,
    metric: str = Query("amount", pattern="^(amount|qty|profit)$"),
    limit: int = 10,
    db: Session = Depends(get_db),
):
    return report_service.product_performance(db, period=period, year=year, month=month, metric=metric, limit=limit)


@router.get("/reports/sales", response_model=PeriodReportOut)
def get_sales_report(
    period: str = Query("monthly", pattern="^(daily|weekly|monthly|yearly)$"),
    year: Optional[int] = None,
    month: Optional[int] = None,
    db: Session = Depends(get_db),
):
    return report_service.period_report(db, period, year, month)


@router.get("/reports/inventory", response_model=InventoryReportOut)
def get_inventory_report(db: Session = Depends(get_db)):
    return report_service.inventory_report(db)


# ---- Sales file import / stock sync ----
@router.post("/imports/sales/preview", response_model=ImportPreviewOut)
async def preview_import(file: UploadFile = File(...), db: Session = Depends(get_db)):
    content = await file.read()
    try:
        return preview_sales_file(db, file.filename or "upload.csv", content)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/imports/sales", response_model=ImportResultOut)
async def run_import(
    file: UploadFile = File(...),
    deduct_stock: bool = Form(True),
    skip_processed: bool = Form(True),
    db: Session = Depends(get_db),
):
    content = await file.read()
    # persist upload
    from app.core.config import settings

    dest = settings.upload_dir / f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{file.filename}"
    dest.write_bytes(content)
    try:
        return import_sales_file(
            db,
            file.filename or dest.name,
            content,
            deduct_stock=deduct_stock,
            skip_processed=skip_processed,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/imports/sales/ocr-preview", response_model=OcrPreviewOut)
async def ocr_preview_sales_photo(
    file: UploadFile = File(...),
    mode: str = Form("sale"),
    db: Session = Depends(get_db),
):
    """OCR a handwritten / photographed sales or purchase report into editable rows."""
    import asyncio
    from app.core.config import settings
    from app.services.ocr_sales import extract_text_from_image

    filename = file.filename or "sales-photo.jpg"
    if not re_search_image(filename, file.content_type):
        raise HTTPException(400, "Upload a photo (jpg, png, webp, bmp). Convert HEIC to JPG first.")
    content = await file.read()
    if not content:
        raise HTTPException(400, "Empty image upload")
    if len(content) > 12 * 1024 * 1024:
        raise HTTPException(400, "Image too large (max 12MB). Compress or take a closer photo.")
    try:
        dest = settings.upload_dir / f"ocr_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{filename}"
        dest.write_bytes(content)
    except Exception:
        pass

    ocr_mode = "purchase" if mode == "purchase" else "sale"
    try:
        # OCR image decode+tesseract off the event loop; DB matching stays here
        ocr = await asyncio.wait_for(
            asyncio.to_thread(extract_text_from_image, content, filename),
            timeout=40.0,
        )
    except asyncio.TimeoutError as exc:
        raise HTTPException(
            504,
            "OCR timed out after 40s. Try a smaller/clearer JPG, or enter lines manually.",
        ) from exc
    except Exception as exc:  # noqa: BLE001
        ocr = {"filename": filename, "engine": f"error:{exc.__class__.__name__}", "raw_text": "", "error": str(exc)}

    try:
        return preview_sales_photo(db, filename, content, mode=ocr_mode, ocr_result=ocr)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"OCR failed: {exc}") from exc


@router.post("/imports/sales/confirm-rows", response_model=ImportResultOut)
def confirm_sales_rows(payload: SalesRowsImportIn, db: Session = Depends(get_db)):
    """Confirm corrected OCR / preview rows into sales (with optional stock deduct)."""
    rows = [r.model_dump() for r in payload.rows]
    try:
        return import_sales_rows(
            db,
            payload.filename or "ocr-sales",
            rows,
            deduct_stock=payload.deduct_stock,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/imports/purchases/ocr-preview", response_model=OcrPreviewOut)
async def ocr_preview_purchase_photo(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """OCR a Quotation/Invoice Register or handwritten purchase photo into editable receive rows."""
    import asyncio
    from app.core.config import settings
    from app.services.ocr_sales import extract_text_from_image

    filename = file.filename or "purchase-photo.jpg"
    if not re_search_image(filename, file.content_type):
        raise HTTPException(400, "Upload a photo (jpg, png, webp, bmp). Convert HEIC to JPG first.")
    content = await file.read()
    if not content:
        raise HTTPException(400, "Empty image upload")
    if len(content) > 12 * 1024 * 1024:
        raise HTTPException(400, "Image too large (max 12MB). Compress or take a closer photo.")
    try:
        dest = settings.upload_dir / f"ocr_po_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{filename}"
        dest.write_bytes(content)
    except Exception:
        pass
    try:
        ocr = await asyncio.wait_for(
            asyncio.to_thread(extract_text_from_image, content, filename),
            timeout=40.0,
        )
    except asyncio.TimeoutError as exc:
        raise HTTPException(
            504,
            "OCR timed out after 40s. Try a smaller/clearer JPG, or enter lines manually.",
        ) from exc
    except Exception as exc:  # noqa: BLE001
        ocr = {"filename": filename, "engine": f"error:{exc.__class__.__name__}", "raw_text": "", "error": str(exc)}
    try:
        return preview_sales_photo(db, filename, content, mode="purchase", ocr_result=ocr)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"OCR failed: {exc}") from exc


@router.post("/imports/purchases/confirm-rows", response_model=PurchaseImportResultOut)
def confirm_purchase_rows(payload: PurchaseRowsImportIn, db: Session = Depends(get_db)):
    """Confirm corrected OCR rows as a purchase (stock increase)."""
    rows = [r.model_dump() for r in payload.rows]
    try:
        return import_purchase_rows(
            db,
            payload.filename or "ocr-purchase",
            rows,
            supplier_id=payload.supplier_id,
            notes=payload.notes,
            purchase_date=payload.purchase_date,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/imports/product-suggestions")
def product_suggestions(q: str = Query(..., min_length=1), db: Session = Depends(get_db)):
    return suggest_products(db, q, limit=12)


def re_search_image(filename: str, content_type: Optional[str]) -> bool:
    name = (filename or "").lower()
    if any(name.endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".heic")):
        return True
    if content_type and content_type.startswith("image/"):
        return True
    return False


@router.get("/imports", response_model=list[ImportBatchOut])
def list_imports(db: Session = Depends(get_db)):
    return db.query(ImportBatch).order_by(ImportBatch.created_at.desc()).limit(50).all()

@router.post("/imports/workbook", response_model=WorkbookImportOut)
async def import_workbook(
    file: UploadFile = File(...),
    replace_existing: bool = Form(True),
    db: Session = Depends(get_db),
):
    """Import full KYGS .xlsm workbook (INVENTORY + SALES + INFOSHEET + CRITICAL + DELISTED)."""
    from app.core.config import settings

    content = await file.read()
    filename = file.filename or "kygs.xlsm"
    if not filename.lower().endswith((".xlsm", ".xlsx", ".xls")):
        raise HTTPException(400, "Upload a KYGS Excel workbook (.xlsm/.xlsx)")

    dest = settings.upload_dir / f"workbook_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{filename}"
    dest.write_bytes(content)
    try:
        return import_kygs_workbook(db, dest, replace_existing=replace_existing)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/imports/workbook/local", response_model=WorkbookImportOut)
def import_workbook_local(
    path: str = Form("KYGS APRIL 2025.xlsm"),
    replace_existing: bool = Form(True),
    db: Session = Depends(get_db),
):
    """Import workbook from a local path (repo root or absolute)."""
    candidate = Path(path)
    if not candidate.is_absolute():
        repo_root = Path(__file__).resolve().parents[3]
        for base in (repo_root, Path.cwd(), Path("/workspace")):
            trial = base / path
            if trial.exists():
                candidate = trial
                break
    if not candidate.exists():
        raise HTTPException(404, f"Workbook not found: {path}")
    try:
        return import_kygs_workbook(db, candidate, replace_existing=replace_existing)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

@router.post("/imports/stock/preview", response_model=StockPreviewOut)
async def preview_stock_import(
    file: UploadFile = File(...),
    mode: str = Form("set"),
    db: Session = Depends(get_db),
):
    """Preview CSV/Excel stock file (set / adjust / upsert)."""
    content = await file.read()
    try:
        return preview_stock_file(db, file.filename or "stock.csv", content, mode=mode)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/imports/stock", response_model=StockImportOut)
async def run_stock_import(
    file: UploadFile = File(...),
    mode: str = Form("set"),
    db: Session = Depends(get_db),
):
    """Upload CSV/Excel to manage stock levels.

    Modes:
    - set: absolute ENDING STOCKS / QTY
    - adjust: add/subtract qty (or ADJUST column)
    - upsert: set stock and create missing SKUs
    """
    from app.core.config import settings

    content = await file.read()
    dest = settings.upload_dir / f"stock_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{file.filename}"
    dest.write_bytes(content)
    try:
        return import_stock_file(db, file.filename or dest.name, content, mode=mode)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc



# ---------------------------------------------------------------------------
# Stock intelligence: demand forecasting and replenishment planning.
# ---------------------------------------------------------------------------


@router.get("/analytics/movers")
def analytics_movers(
    direction: str = Query("fast", pattern="^(fast|slow|dead)$"),
    days: int = Query(90, ge=7, le=730),
    limit: int = Query(25, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """Fast movers (restock priorities), slow movers and dead stock (cash traps)."""
    rows, start, end = analytics.movers(db, days=days, limit=limit, direction=direction)
    return {
        "direction": direction,
        "window": {"from": start.isoformat(), "to": end.isoformat(), "days": days},
        "count": len(rows),
        "items": rows,
    }


@router.get("/analytics/reorder")
def analytics_reorder(
    days: int = Query(90, ge=7, le=730),
    supplier_id: Optional[int] = None,
    only_needed: bool = True,
    db: Session = Depends(get_db),
):
    """What to buy, how much, from whom, and why — ranked by urgency."""
    rows, start, end = analytics.reorder_suggestions(
        db, days=days, supplier_id=supplier_id, only_needed=only_needed
    )

    by_supplier: dict[str, dict] = {}
    for row in rows:
        key = row["supplier"] or "UNASSIGNED"
        bucket = by_supplier.setdefault(
            key, {"supplier": key, "supplier_id": row["supplier_id"],
                  "lines": 0, "units": 0.0, "cost": 0.0}
        )
        bucket["lines"] += 1
        bucket["units"] += row["suggested_qty"]
        bucket["cost"] = round(bucket["cost"] + row["order_cost"], 2)

    return {
        "window": {"from": start.isoformat(), "to": end.isoformat(), "days": days},
        "count": len(rows),
        "total_cost": round(sum(r["order_cost"] for r in rows), 2),
        "by_supplier": sorted(by_supplier.values(), key=lambda b: -b["cost"]),
        "suggestions": rows,
    }


@router.get("/analytics/abc")
def analytics_abc(days: int = Query(90, ge=7, le=730), db: Session = Depends(get_db)):
    """ABC (value) x XYZ (predictability) matrix for stocking policy."""
    rows, start, end = analytics.analyze(db, days=days)

    matrix: dict[str, int] = {}
    summary: dict[str, dict] = {}
    for row in rows:
        matrix[row["abc_xyz"]] = matrix.get(row["abc_xyz"], 0) + 1
        bucket = summary.setdefault(
            row["abc"], {"class": row["abc"], "items": 0, "revenue": 0.0,
                         "stock_value": 0.0, "gross_profit": 0.0}
        )
        bucket["items"] += 1
        bucket["revenue"] = round(bucket["revenue"] + row["revenue"], 2)
        bucket["stock_value"] = round(bucket["stock_value"] + row["stock_value"], 2)
        bucket["gross_profit"] = round(bucket["gross_profit"] + row["gross_profit"], 2)

    policy = {
        "AX": "Top value, predictable — keep tight stock, order little and often",
        "AY": "Top value, variable — hold extra safety stock",
        "AZ": "Top value, erratic — review by hand every cycle",
        "BX": "Mid value, predictable — automate on reorder point",
        "BY": "Mid value, variable — moderate safety stock",
        "BZ": "Mid value, erratic — order to demand",
        "CX": "Low value, predictable — bulk buy, review rarely",
        "CY": "Low value, variable — bulk buy",
        "CZ": "Low value, erratic — order only when asked for",
    }
    return {
        "window": {"from": start.isoformat(), "to": end.isoformat(), "days": days},
        "summary": sorted(summary.values(), key=lambda b: b["class"]),
        "matrix": [{"cell": k, "items": v, "policy": policy.get(k, "")}
                   for k, v in sorted(matrix.items())],
        "items": rows,
    }


@router.get("/analytics/overview")
def analytics_overview(days: int = Query(90, ge=7, le=730), db: Session = Depends(get_db)):
    """Headline stock-health numbers for the management dashboard."""
    rows, start, end = analytics.analyze(db, days=days)

    counts = {"fast": 0, "medium": 0, "slow": 0, "dead": 0}
    dead_value = stock_value = cogs = 0.0
    for row in rows:
        counts[row["movement"]] = counts.get(row["movement"], 0) + 1
        stock_value += row["stock_value"]
        cogs += row["sold_qty"] * row["unit_cost"]
        if row["movement"] == "dead":
            dead_value += row["stock_value"]

    out_of_stock = [r for r in rows if r["on_hand"] <= 0]
    below_rop = [r for r in rows if 0 < r["on_hand"] <= r["reorder_point"]]
    fast_out = [r for r in out_of_stock if r["movement"] == "fast"]

    suggestions, _, _ = analytics.reorder_suggestions(db, days=days)
    denominator = stock_value if stock_value > 0 else 1

    return {
        "window": {"from": start.isoformat(), "to": end.isoformat(), "days": days},
        "sku_count": len(rows),
        "stock_value": round(stock_value, 2),
        "movement": counts,
        "dead_stock_value": round(dead_value, 2),
        "dead_stock_pct": round(dead_value / denominator * 100, 1),
        "out_of_stock": len(out_of_stock),
        "fast_movers_out_of_stock": len(fast_out),
        "below_reorder_point": len(below_rop),
        "reorder_lines": len(suggestions),
        "reorder_cost": round(sum(s["order_cost"] for s in suggestions), 2),
        "stock_turnover_annualised": round((cogs / denominator) * (365 / days), 2),
        "urgent": suggestions[:10],
        "at_risk_fast_movers": sorted(fast_out, key=lambda r: -r["revenue"])[:10],
    }


@router.get("/analytics/products/{product_id}/forecast")
def analytics_product_forecast(
    product_id: int,
    days: int = Query(180, ge=30, le=730),
    db: Session = Depends(get_db),
):
    """Detailed outlook for one product: pattern, projection and reorder plan."""
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(404, "Product not found")

    supplier = db.get(Supplier, product.supplier_id) if product.supplier_id else None
    lead = float(getattr(supplier, "lead_time_days", None) or analytics.DEFAULT_LEAD_DAYS)
    review = float(getattr(supplier, "order_cycle_days", None) or analytics.DEFAULT_CYCLE_DAYS)

    series_map, start, end = analytics.daily_demand(db, days)
    raw = series_map.get(product_id, [0.0] * days)
    offset = analytics.shelf_offset(raw, product.created_at, start)
    series = raw[offset:]
    series_start = start + timedelta(days=offset)

    rate, info = forecast.forecast_daily_rate(series)
    sigma = forecast._stdev(series)
    rop = forecast.reorder_point(rate, lead, review, sigma, analytics.SERVICE_LEVEL_Z)
    eoq = forecast.economic_order_quantity(
        rate * 365, analytics.ORDER_COST, float(product.cost_price or 0),
        analytics.HOLDING_RATE,
    )
    cover = forecast.days_of_cover(float(product.stock_qty or 0), rate)

    weekly = forecast.seasonal_indices(series, 7)
    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    weekday_of_start = series_start.weekday()
    seasonality = [
        {"day": day_names[(weekday_of_start + i) % 7], "index": round(weekly[i], 3)}
        for i in range(7)
    ]
    seasonality.sort(key=lambda s: day_names.index(s["day"]))

    buckets = [
        {"week_of": (series_start + timedelta(days=offset_days)).isoformat(),
         "qty": round(sum(series[offset_days:offset_days + 7]), 2)}
        for offset_days in range(0, len(series), 7)
    ]

    return {
        "product": {
            "id": product.id, "sku": product.sku, "name": product.name,
            "stock_qty": float(product.stock_qty or 0),
            "cost_price": float(product.cost_price or 0),
            "sell_price": float(product.sell_price or 0),
            "reorder_level": float(product.reorder_level or 0),
            "supplier": supplier.name if supplier else "",
        },
        "window": {"from": start.isoformat(), "to": end.isoformat(), "days": days,
                   "measured_from": series_start.isoformat()},
        "pattern": info,
        "daily_rate": round(rate, 4),
        "forecast": {
            "next_7d": round(rate * 7, 1),
            "next_30d": round(rate * 30, 1),
            "next_90d": round(rate * 90, 1),
        },
        "replenishment": {
            "lead_time_days": lead,
            "review_days": review,
            "safety_stock": round(
                forecast.safety_stock(sigma, lead, review, analytics.SERVICE_LEVEL_Z), 1),
            "reorder_point": round(rop, 1),
            "economic_order_qty": round(eoq, 1),
            "days_of_cover": round(cover, 1) if cover is not None else None,
            "projected_stockout": (
                (end + timedelta(days=int(cover))).isoformat()
                if cover is not None and cover < 365 else None
            ),
        },
        "weekly_demand": buckets,
        "weekday_seasonality": seasonality,
    }


# ---------------------------------------------------------------------------
# Job queue: work tickets for bikes in the shop.
# ---------------------------------------------------------------------------

OPEN_JOB_STATUSES = ("queued", "in_progress", "ready")
ALL_JOB_STATUSES = OPEN_JOB_STATUSES + ("completed", "cancelled")
JOB_TRANSITIONS = {
    "queued": {"in_progress", "ready", "cancelled"},
    "in_progress": {"ready", "queued", "cancelled"},
    "ready": {"in_progress", "cancelled"},   # completed happens via checkout
    "completed": set(),
    "cancelled": set(),
}
JOB_STAMP = {"in_progress": "started_at", "ready": "ready_at"}


def _is_labour(sku: Optional[str]) -> bool:
    """Labour follows the shop's existing convention: SKU starting with LABOR."""
    return str(sku or "").upper().startswith("LABOR")


def _job_out(job: Job) -> dict:
    parts = labour = discount_total = 0.0
    lines = []
    for line in job.lines:
        line_discount = float(line.discount or 0)
        total = round(line.quantity * line.unit_price - line_discount, 2)
        discount_total += line_discount
        on_hand = float(line.product.stock_qty or 0) if line.product else 0.0
        labour_line = _is_labour(line.sku)
        # Flag shortages now so the counter is not surprised at payment.
        short = (not labour_line) and on_hand < line.quantity
        lines.append({
            "id": line.id,
            "product_id": line.product_id,
            "sku": line.sku,
            "product_name": line.product_name,
            "quantity": line.quantity,
            "unit_price": line.unit_price,
            "discount": line_discount,
            "line_total": total,
            "is_labour": labour_line,
            "on_hand": on_hand,
            "short": short,
        })
        if labour_line:
            labour += total
        else:
            parts += total

    hours_open = None
    if job.created_at:
        end = job.completed_at or job.cancelled_at or datetime.utcnow()
        hours_open = int((end - job.created_at).total_seconds() // 3600)

    return {
        "id": job.id,
        "job_no": job.job_no,
        "status": job.status,
        "priority": job.priority,
        "customer_id": job.customer_id,
        "customer_name": job.customer_name or (job.customer.name if job.customer else ""),
        "contact": job.contact or "",
        "plate_no": job.plate_no or "",
        "motorcycle": job.motorcycle or "",
        "complaint": job.complaint or "",
        "notes": job.notes or "",
        "mechanic": job.mechanic or "",
        "created_at": job.created_at,
        "started_at": job.started_at,
        "ready_at": job.ready_at,
        "completed_at": job.completed_at,
        "cancelled_at": job.cancelled_at,
        "cancel_reason": job.cancel_reason or "",
        "sale_id": job.sale_id,
        "invoice_no": job.sale.invoice_no if job.sale else None,
        "hours_open": hours_open,
        "lines": lines,
        "line_count": len(lines),
        "parts_total": round(parts, 2),
        "labour_total": round(labour, 2),
        "discount_total": round(discount_total, 2),
        "total": round(parts + labour, 2),
        "short_lines": sum(1 for line in lines if line["short"]),
    }


def _get_job(db: Session, job_id: int) -> Job:
    job = (
        db.query(Job)
        .options(joinedload(Job.lines).joinedload(JobLine.product),
                 joinedload(Job.customer), joinedload(Job.sale))
        .filter(Job.id == job_id)
        .first()
    )
    if not job:
        raise HTTPException(404, "Job not found")
    return job


@router.get("/jobs/board")
def job_board(db: Session = Depends(get_db)):
    """Counts and the open queue — what the shop is working on right now."""
    counts = {status: 0 for status in ALL_JOB_STATUSES}
    for status, total in db.query(Job.status, func.count(Job.id)).group_by(Job.status).all():
        counts[status] = total

    jobs = (
        db.query(Job)
        .options(joinedload(Job.lines).joinedload(JobLine.product),
                 joinedload(Job.customer), joinedload(Job.sale))
        .filter(Job.status.in_(OPEN_JOB_STATUSES))
        .all()
    )
    out = [_job_out(job) for job in jobs]
    # Urgent first, then closest to release, then longest waiting.
    stage = {"ready": 0, "in_progress": 1, "queued": 2}
    out.sort(key=lambda j: (0 if j["priority"] == "urgent" else 1,
                            stage.get(j["status"], 3),
                            j["created_at"] or datetime.utcnow()))

    return {
        "counts": counts,
        "open_total": sum(counts[s] for s in OPEN_JOB_STATUSES),
        "open_value": round(sum(j["total"] for j in out), 2),
        "jobs": out,
    }


@router.get("/jobs")
def list_jobs(
    status: Optional[str] = None,
    q: str = "",
    limit: int = Query(100, le=500),
    db: Session = Depends(get_db),
):
    query = db.query(Job).options(
        joinedload(Job.lines).joinedload(JobLine.product),
        joinedload(Job.customer), joinedload(Job.sale),
    )
    if status == "open":
        query = query.filter(Job.status.in_(OPEN_JOB_STATUSES))
    elif status:
        query = query.filter(Job.status == status)
    if q:
        like = f"%{q}%"
        query = query.filter(
            Job.job_no.like(like) | Job.customer_name.like(like)
            | Job.plate_no.like(like) | Job.motorcycle.like(like)
        )
    jobs = query.order_by(Job.id.desc()).limit(limit).all()
    return {"jobs": [_job_out(job) for job in jobs]}


@router.get("/jobs/{job_id}")
def get_job(job_id: int, db: Session = Depends(get_db)):
    return _job_out(_get_job(db, job_id))


@router.post("/jobs")
def create_job(payload: JobCreate, db: Session = Depends(get_db)):
    if payload.priority not in ("normal", "urgent"):
        raise HTTPException(400, "Priority must be normal or urgent")

    customer_id = payload.customer_id
    # Keep the counter's typing: optionally turn a walk-in into a saved customer
    # so the next visit can be looked up instead of re-keyed.
    if customer_id is None and payload.save_customer and (payload.customer_name or "").strip():
        customer = Customer(
            name=payload.customer_name.strip(),
            phone=(payload.contact or "").strip() or None,
            motorcycle_model=(payload.motorcycle or "").strip() or None,
        )
        db.add(customer)
        db.flush()
        customer_id = customer.id

    job = Job(
        job_no=_next_no(db, Job, "job_no", "JOB"),
        customer_id=customer_id,
        customer_name=(payload.customer_name or "").strip() or None,
        contact=(payload.contact or "").strip() or None,
        plate_no=(payload.plate_no or "").strip().upper() or None,
        motorcycle=(payload.motorcycle or "").strip() or None,
        complaint=(payload.complaint or "").strip() or None,
        notes=(payload.notes or "").strip() or None,
        mechanic=(payload.mechanic or "").strip() or None,
        priority=payload.priority,
    )
    for line in payload.lines:
        job.lines.append(_build_job_line(db, line))

    db.add(job)
    db.commit()
    return _job_out(_get_job(db, job.id))


def _build_job_line(db: Session, line: JobLineIn) -> JobLine:
    product = db.get(Product, line.product_id)
    if not product:
        raise HTTPException(400, f"Product {line.product_id} not found")
    if line.quantity <= 0:
        raise HTTPException(400, "Quantity must be greater than 0")
    unit_price = line.unit_price if line.unit_price is not None else product.sell_price
    gross = line.quantity * unit_price
    if line.discount > gross:
        raise HTTPException(400, "Discount cannot be more than the line total")
    return JobLine(
        product_id=product.id,
        sku=product.sku,
        product_name=product.name,
        quantity=line.quantity,
        unit_price=unit_price,
        discount=line.discount,
    )


@router.patch("/jobs/{job_id}")
def update_job(job_id: int, payload: JobUpdate, db: Session = Depends(get_db)):
    job = _get_job(db, job_id)
    data = payload.model_dump(exclude_none=True)

    if "status" in data:
        new = data["status"]
        if new not in ALL_JOB_STATUSES:
            raise HTTPException(400, f"Status must be one of {list(ALL_JOB_STATUSES)}")
        if new == "completed":
            raise HTTPException(
                400, "Finish a job by taking payment, not by setting its status."
            )
        if new != job.status and new not in JOB_TRANSITIONS[job.status]:
            raise HTTPException(409, f"A {job.status} job cannot move to {new}.")
        stamp = JOB_STAMP.get(new)
        if stamp and getattr(job, stamp) is None:
            setattr(job, stamp, datetime.utcnow())
    if "priority" in data and data["priority"] not in ("normal", "urgent"):
        raise HTTPException(400, "Priority must be normal or urgent")

    for field, value in data.items():
        setattr(job, field, value)
    db.commit()
    return _job_out(_get_job(db, job_id))


@router.post("/jobs/{job_id}/lines")
def add_job_line(job_id: int, payload: JobLineIn, db: Session = Depends(get_db)):
    job = _get_job(db, job_id)
    if job.status not in OPEN_JOB_STATUSES:
        raise HTTPException(409, f"Cannot add work to a {job.status} job")
    job.lines.append(_build_job_line(db, payload))
    db.commit()
    return _job_out(_get_job(db, job_id))


@router.delete("/jobs/{job_id}/lines/{line_id}")
def remove_job_line(job_id: int, line_id: int, db: Session = Depends(get_db)):
    job = _get_job(db, job_id)
    if job.status not in OPEN_JOB_STATUSES:
        raise HTTPException(409, f"Cannot change a {job.status} job")
    line = db.query(JobLine).filter(JobLine.id == line_id,
                                    JobLine.job_id == job_id).first()
    if line:
        db.delete(line)
        db.commit()
    return _job_out(_get_job(db, job_id))


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: int, payload: JobCancel, db: Session = Depends(get_db)):
    job = _get_job(db, job_id)
    if job.status not in OPEN_JOB_STATUSES:
        raise HTTPException(400, f"Job is already {job.status}")
    job.status = "cancelled"
    job.cancelled_at = datetime.utcnow()
    job.cancel_reason = payload.reason
    db.commit()
    return _job_out(_get_job(db, job_id))


@router.post("/jobs/{job_id}/checkout")
def checkout_job(job_id: int, payload: JobCheckout, db: Session = Depends(get_db)):
    """Turn a finished job into a sale. Stock moves here, and only here."""
    job = _get_job(db, job_id)
    if job.status not in OPEN_JOB_STATUSES:
        raise HTTPException(400, f"Job is already {job.status}")
    if not job.lines:
        raise HTTPException(400, "Add parts or labour before taking payment")

    snapshot = _job_out(job)
    if snapshot["short_lines"] and not payload.allow_negative_stock:
        short = [l["product_name"] for l in snapshot["lines"] if l["short"]]
        raise HTTPException(
            409,
            "Not enough stock for: " + ", ".join(short[:3])
            + ("…" if len(short) > 3 else "")
            + ". Receive stock, reduce the line, or confirm to sell anyway.",
        )

    # Reuse the shop's own sale path so stock, labour and numbering behave
    # exactly as they do for a walk-in sale.
    sale_payload = SaleCreate(
        customer_id=job.customer_id,
        payment_method=payload.payment_method,
        payment_status=payload.payment_status,
        discount=payload.discount,
        notes=f"{job.job_no} {job.motorcycle or ''}".strip(),
        items=[
            SaleItemIn(product_id=line.product_id, quantity=line.quantity,
                       unit_price=line.unit_price, discount=float(line.discount or 0))
            for line in job.lines
        ],
    )
    sale_out = create_sale(sale_payload, db)

    job.status = "completed"
    job.completed_at = datetime.utcnow()
    job.sale_id = sale_out["id"] if isinstance(sale_out, dict) else sale_out.id
    db.commit()

    return {"job": _job_out(_get_job(db, job_id)), "sale": sale_out}
