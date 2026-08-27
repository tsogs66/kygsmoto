from datetime import datetime, date
from typing import Optional

from pydantic import BaseModel, Field, ConfigDict


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- Categories ---
class CategoryCreate(BaseModel):
    name: str
    description: Optional[str] = None


class CategoryOut(ORMModel):
    id: int
    name: str
    description: Optional[str] = None


# --- Suppliers ---
class SupplierCreate(BaseModel):
    name: str
    contact_person: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    notes: Optional[str] = None


class SupplierOut(ORMModel):
    id: int
    name: str
    contact_person: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    notes: Optional[str] = None


# --- Customers ---
class CustomerCreate(BaseModel):
    name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    motorcycle_model: Optional[str] = None
    notes: Optional[str] = None


class CustomerOut(ORMModel):
    id: int
    name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    motorcycle_model: Optional[str] = None
    notes: Optional[str] = None


# --- Products ---
class ProductCreate(BaseModel):
    sku: str
    name: str
    brand: Optional[str] = None
    category_id: Optional[int] = None
    supplier_id: Optional[int] = None
    description: Optional[str] = None
    fitment: Optional[str] = None
    unit: str = "pc"
    cost_price: float = 0
    sell_price: float = 0
    stock_qty: float = 0
    reorder_level: float = 5
    location: Optional[str] = None
    barcode: Optional[str] = None
    is_active: bool = True


class ProductUpdate(BaseModel):
    sku: Optional[str] = None
    name: Optional[str] = None
    brand: Optional[str] = None
    category_id: Optional[int] = None
    supplier_id: Optional[int] = None
    description: Optional[str] = None
    fitment: Optional[str] = None
    unit: Optional[str] = None
    cost_price: Optional[float] = None
    sell_price: Optional[float] = None
    reorder_level: Optional[float] = None
    location: Optional[str] = None
    barcode: Optional[str] = None
    is_active: Optional[bool] = None


class ProductOut(ORMModel):
    id: int
    sku: str
    name: str
    brand: Optional[str] = None
    category_id: Optional[int] = None
    supplier_id: Optional[int] = None
    description: Optional[str] = None
    fitment: Optional[str] = None
    unit: str
    cost_price: float
    sell_price: float
    stock_qty: float
    reorder_level: float
    location: Optional[str] = None
    barcode: Optional[str] = None
    is_active: bool
    category_name: Optional[str] = None
    supplier_name: Optional[str] = None
    stock_status: Optional[str] = None
    reserved_qty: float = 0.0
    available_qty: Optional[float] = None


class StockAdjust(BaseModel):
    quantity_change: float
    notes: Optional[str] = None


# --- Sales ---
class SaleItemIn(BaseModel):
    product_id: int
    quantity: float = Field(gt=0)
    unit_price: Optional[float] = None
    discount: float = Field(default=0.0, ge=0)


class SaleCreate(BaseModel):
    customer_id: Optional[int] = None
    payment_method: str = "cash"
    payment_status: str = "paid"
    amount_paid: Optional[float] = None
    discount: float = 0
    tax: float = 0
    notes: Optional[str] = None
    sale_date: Optional[datetime] = None
    allow_shortfall: bool = False
    items: list[SaleItemIn]


class SaleItemOut(ORMModel):
    id: int
    product_id: Optional[int] = None
    sku: Optional[str] = None
    product_name: str
    quantity: float
    unit_price: float
    cost_price: float
    discount: float = 0.0
    line_total: float


class SaleOut(ORMModel):
    id: int
    invoice_no: str
    sale_date: datetime
    customer_id: Optional[int] = None
    customer_name: Optional[str] = None
    payment_method: str
    payment_status: str
    amount_paid: float
    subtotal: float
    discount: float
    tax: float
    total: float
    notes: Optional[str] = None
    source: str
    items: list[SaleItemOut] = []


# --- Purchases ---
class PurchaseItemIn(BaseModel):
    id: Optional[int] = None  # existing line id when editing
    product_id: int
    quantity: float = Field(gt=0)
    unit_cost: Optional[float] = None


class PurchaseCreate(BaseModel):
    supplier_id: Optional[int] = None
    notes: Optional[str] = None
    purchase_date: Optional[datetime] = None
    items: list[PurchaseItemIn]


class PurchaseUpdate(BaseModel):
    supplier_id: Optional[int] = None
    notes: Optional[str] = None
    purchase_date: Optional[datetime] = None
    items: list[PurchaseItemIn]


class PurchaseItemOut(ORMModel):
    id: int
    product_id: int
    product_name: Optional[str] = None
    sku: Optional[str] = None
    quantity: float
    unit_cost: float
    line_total: float


class PurchaseOut(ORMModel):
    id: int
    po_no: str
    purchase_date: datetime
    supplier_id: Optional[int] = None
    supplier_name: Optional[str] = None
    subtotal: float
    total: float
    notes: Optional[str] = None
    has_receipt: bool = False
    receipt_filename: Optional[str] = None
    items: list[PurchaseItemOut] = []


# --- Import ---
class ImportPreviewRow(BaseModel):
    row_number: int
    invoice_no: Optional[str] = None
    sale_date: Optional[str] = None
    sku: Optional[str] = None
    product_name: Optional[str] = None
    quantity: Optional[float] = None
    unit_price: Optional[float] = None
    uom: Optional[str] = None
    line_amount: Optional[float] = None
    customer: Optional[str] = None
    matched_product_id: Optional[int] = None
    matched_product_name: Optional[str] = None
    current_stock: Optional[float] = None
    status: str
    message: Optional[str] = None


class ImportPreviewOut(BaseModel):
    filename: str
    rows: list[ImportPreviewRow]
    matched_count: int
    unmatched_count: int
    total_qty: float


class OcrSuggestion(BaseModel):
    id: int
    sku: str
    name: str
    sell_price: float
    cost_price: float = 0
    stock_qty: float
    score: float = 0


class OcrPreviewRow(ImportPreviewRow):
    ocr_text: Optional[str] = None
    suggestions: list[OcrSuggestion] = []
    include: bool = True


class OcrPreviewOut(BaseModel):
    filename: str
    engine: str = "none"
    raw_text: str = ""
    rows: list[OcrPreviewRow]
    matched_count: int
    unmatched_count: int
    total_qty: float
    message: str = ""
    mode: str = "sale"
    document_type: str = "freeform"


class SalesRowConfirm(BaseModel):
    row_number: Optional[int] = None
    invoice_no: Optional[str] = None
    sale_date: Optional[str] = None
    purchase_date: Optional[str] = None
    sku: Optional[str] = None
    product_name: Optional[str] = None
    quantity: Optional[float] = None
    unit_price: Optional[float] = None
    unit_cost: Optional[float] = None
    uom: Optional[str] = None
    line_amount: Optional[float] = None
    customer: Optional[str] = None
    matched_product_id: Optional[int] = None
    product_id: Optional[int] = None
    include: bool = True


class SalesRowsImportIn(BaseModel):
    filename: str = "ocr-sales"
    deduct_stock: bool = True
    rows: list[SalesRowConfirm]


class PurchaseRowsImportIn(BaseModel):
    filename: str = "ocr-purchase"
    supplier_id: Optional[int] = None
    notes: Optional[str] = None
    purchase_date: Optional[str] = None
    rows: list[SalesRowConfirm]


class PurchaseImportResultOut(BaseModel):
    batch_id: Optional[int] = None
    filename: str
    po_no: Optional[str] = None
    po_nos: list[str] = []
    rows_imported: int
    rows_skipped: int
    stock_added: float
    unmatched_skus: list[str] = []
    purchases_created: int
    message: str


class ImportResultOut(BaseModel):
    batch_id: int
    filename: str
    rows_total: int
    rows_imported: int
    rows_skipped: int
    stock_deducted: float
    unmatched_skus: list[str] = []
    sales_created: int
    message: str


class ImportBatchOut(ORMModel):
    id: int
    filename: str
    file_type: str
    status: str
    rows_total: int
    rows_imported: int
    rows_skipped: int
    stock_deducted: float
    unmatched_skus: Optional[str] = None
    summary: Optional[str] = None
    created_at: datetime


class WorkbookImportOut(BaseModel):
    filename: str
    products_created: int
    services_created: int
    delisted_count: int
    categories: int
    suppliers: int
    sales_created: int
    sale_lines: int
    unmatched_skus: list[str] = []
    batch_id: int
    message: str


class StockPreviewRow(BaseModel):
    row_number: int
    sku: Optional[str] = None
    product_name: Optional[str] = None
    csv_stock: Optional[float] = None
    csv_adjust: Optional[float] = None
    current_stock: Optional[float] = None
    new_stock: Optional[float] = None
    status: str
    message: Optional[str] = None


class StockPreviewOut(BaseModel):
    filename: str
    mode: str
    rows: list[StockPreviewRow]
    matched_count: int
    unmatched_count: int
    will_create_count: int = 0


class StockImportOut(BaseModel):
    batch_id: int
    filename: str
    mode: str
    rows_total: int
    rows_updated: int
    rows_created: int
    rows_skipped: int
    unmatched_skus: list[str] = []
    net_qty_change: float
    message: str


# --- Reports ---
class DashboardOut(BaseModel):
    shop_name: str
    selected_year: int = 0
    selected_month: int = 0
    total_products: int
    low_stock_count: int
    out_of_stock_count: int
    inventory_value_cost: float
    inventory_value_retail: float
    sales_today: float
    sales_week: float = 0
    sales_month: float
    sales_year: float
    profit_month: float
    profit_year: float = 0
    transactions_today: int
    transactions_month: int
    top_products: list[dict]
    top_products_month: list[dict] = []
    top_products_year: list[dict] = []
    top_profit_month: list[dict] = []
    top_profit_year: list[dict] = []
    low_stock_items: list[dict]
    recent_sales: list[dict]
    monthly_trend: list[dict]


class ProductPerformanceOut(BaseModel):
    period: str
    metric: str
    start_date: date
    end_date: date
    year: int
    month: int
    items: list[dict]


class PeriodReportOut(BaseModel):
    period: str
    start_date: date
    end_date: date
    total_sales: float
    total_cost: float
    gross_profit: float
    transaction_count: int
    items_sold: float
    by_day: list[dict] = []
    by_month: list[dict] = []
    by_category: list[dict] = []
    by_payment: list[dict] = []
    top_products: list[dict] = []


class InventoryReportOut(BaseModel):
    total_skus: int
    total_units: float
    value_at_cost: float
    value_at_retail: float
    low_stock: list[dict]
    by_category: list[dict]
    movements: list[dict] = []

# ---- Job queue ----


class JobLineIn(BaseModel):
    product_id: int
    quantity: float = Field(gt=0)
    unit_price: Optional[float] = None
    discount: float = Field(default=0.0, ge=0)


class JobCreate(BaseModel):
    customer_id: Optional[int] = None
    save_customer: bool = False
    customer_name: Optional[str] = None
    contact: Optional[str] = None
    plate_no: Optional[str] = None
    motorcycle: Optional[str] = None
    complaint: Optional[str] = None
    notes: Optional[str] = None
    mechanic: Optional[str] = None
    priority: str = "normal"
    lines: list[JobLineIn] = []


class JobUpdate(BaseModel):
    status: Optional[str] = None
    priority: Optional[str] = None
    customer_name: Optional[str] = None
    contact: Optional[str] = None
    plate_no: Optional[str] = None
    motorcycle: Optional[str] = None
    complaint: Optional[str] = None
    notes: Optional[str] = None
    mechanic: Optional[str] = None


class JobCancel(BaseModel):
    reason: str = Field(min_length=3)


class JobLinesIn(BaseModel):
    """A basket of work added to a ticket in one go — e.g. a cart from the till."""

    lines: list[JobLineIn]


class JobCheckout(BaseModel):
    payment_method: str = "cash"
    payment_status: str = "paid"
    discount: float = 0.0
    allow_negative_stock: bool = False

# ---- Held sales ----


class HeldSaleLineIn(BaseModel):
    product_id: int
    quantity: float = Field(gt=0)
    unit_price: Optional[float] = None
    discount: float = Field(default=0.0, ge=0)


class HeldSaleCreate(BaseModel):
    label: Optional[str] = None
    customer_id: Optional[int] = None
    customer_name: Optional[str] = None
    contact: Optional[str] = None
    plate_no: Optional[str] = None
    motorcycle: Optional[str] = None
    note: Optional[str] = None
    payment_method: str = "cash"
    save_customer: bool = False
    allow_shortfall: bool = False
    lines: list[HeldSaleLineIn]
