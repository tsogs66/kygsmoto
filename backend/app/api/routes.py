from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.models.models import (
    Category,
    Customer,
    ImportBatch,
    Product,
    Purchase,
    PurchaseItem,
    Sale,
    SaleItem,
    Supplier,
)
from app.schemas import (
    CategoryCreate,
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
    SaleCreate,
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
from pathlib import Path

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
        line_total = item.quantity * unit_price
        subtotal += line_total
        sale.items.append(
            SaleItem(
                product_id=product.id,
                sku=product.sku,
                product_name=product.name,
                quantity=item.quantity,
                unit_price=unit_price,
                cost_price=product.cost_price,
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


@router.post("/purchases", response_model=PurchaseOut)
def create_purchase(payload: PurchaseCreate, db: Session = Depends(get_db)):
    if not payload.items:
        raise HTTPException(400, "Purchase requires items")
    purchase = Purchase(
        po_no=_next_no(db, Purchase, "po_no", "PO"),
        purchase_date=payload.purchase_date or datetime.utcnow(),
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
    """OCR a handwritten purchase / delivery receipt into editable receive rows."""
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

