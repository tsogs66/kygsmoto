from datetime import datetime, date
from typing import Optional

from sqlalchemy import (
    String,
    Integer,
    Float,
    Text,
    DateTime,
    Date,
    ForeignKey,
    Boolean,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    products: Mapped[list["Product"]] = relationship(back_populates="category")


class Supplier(Base):
    __tablename__ = "suppliers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    contact_person: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Replenishment planning: how long an order takes to arrive, and how often we
    # order from this supplier. Both feed the reorder point calculation.
    lead_time_days: Mapped[float] = mapped_column(Float, default=7.0)
    order_cycle_days: Mapped[float] = mapped_column(Float, default=30.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    products: Mapped[list["Product"]] = relationship(back_populates="supplier")
    purchases: Mapped[list["Purchase"]] = relationship(back_populates="supplier")


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    motorcycle_model: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    sales: Mapped[list["Sale"]] = relationship(back_populates="customer")


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (UniqueConstraint("sku", name="uq_product_sku"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sku: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(250), nullable=False, index=True)
    brand: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    category_id: Mapped[Optional[int]] = mapped_column(ForeignKey("categories.id"), nullable=True)
    supplier_id: Mapped[Optional[int]] = mapped_column(ForeignKey("suppliers.id"), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    fitment: Mapped[Optional[str]] = mapped_column(String(250), nullable=True)  # e.g. Honda Click, Yamaha Mio
    unit: Mapped[str] = mapped_column(String(40), default="pc")
    cost_price: Mapped[float] = mapped_column(Float, default=0.0)
    sell_price: Mapped[float] = mapped_column(Float, default=0.0)
    stock_qty: Mapped[float] = mapped_column(Float, default=0.0)
    reorder_level: Mapped[float] = mapped_column(Float, default=5.0)
    location: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    barcode: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    category: Mapped[Optional[Category]] = relationship(back_populates="products")
    supplier: Mapped[Optional[Supplier]] = relationship(back_populates="products")
    stock_movements: Mapped[list["StockMovement"]] = relationship(back_populates="product")


class Sale(Base):
    __tablename__ = "sales"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_no: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    sale_date: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    customer_id: Mapped[Optional[int]] = mapped_column(ForeignKey("customers.id"), nullable=True)
    payment_method: Mapped[str] = mapped_column(String(40), default="cash")
    payment_status: Mapped[str] = mapped_column(String(40), default="paid")  # paid, partial, unpaid
    amount_paid: Mapped[float] = mapped_column(Float, default=0.0)
    subtotal: Mapped[float] = mapped_column(Float, default=0.0)
    discount: Mapped[float] = mapped_column(Float, default=0.0)
    tax: Mapped[float] = mapped_column(Float, default=0.0)
    total: Mapped[float] = mapped_column(Float, default=0.0)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(40), default="manual")  # manual, import
    import_batch_id: Mapped[Optional[int]] = mapped_column(ForeignKey("import_batches.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    customer: Mapped[Optional[Customer]] = relationship(back_populates="sales")
    items: Mapped[list["SaleItem"]] = relationship(back_populates="sale", cascade="all, delete-orphan")
    import_batch: Mapped[Optional["ImportBatch"]] = relationship(back_populates="sales")


class SaleItem(Base):
    __tablename__ = "sale_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sale_id: Mapped[int] = mapped_column(ForeignKey("sales.id"), nullable=False)
    product_id: Mapped[Optional[int]] = mapped_column(ForeignKey("products.id"), nullable=True)
    sku: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    product_name: Mapped[str] = mapped_column(String(250), nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    unit_price: Mapped[float] = mapped_column(Float, nullable=False)
    cost_price: Mapped[float] = mapped_column(Float, default=0.0)
    line_total: Mapped[float] = mapped_column(Float, nullable=False)

    sale: Mapped[Sale] = relationship(back_populates="items")
    product: Mapped[Optional[Product]] = relationship()


class Purchase(Base):
    __tablename__ = "purchases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    po_no: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    purchase_date: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    supplier_id: Mapped[Optional[int]] = mapped_column(ForeignKey("suppliers.id"), nullable=True)
    subtotal: Mapped[float] = mapped_column(Float, default=0.0)
    total: Mapped[float] = mapped_column(Float, default=0.0)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    receipt_filename: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    receipt_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    supplier: Mapped[Optional[Supplier]] = relationship(back_populates="purchases")
    items: Mapped[list["PurchaseItem"]] = relationship(back_populates="purchase", cascade="all, delete-orphan")


class PurchaseItem(Base):
    __tablename__ = "purchase_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    purchase_id: Mapped[int] = mapped_column(ForeignKey("purchases.id"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    unit_cost: Mapped[float] = mapped_column(Float, nullable=False)
    line_total: Mapped[float] = mapped_column(Float, nullable=False)

    purchase: Mapped[Purchase] = relationship(back_populates="items")
    product: Mapped[Product] = relationship()


class StockMovement(Base):
    __tablename__ = "stock_movements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False, index=True)
    movement_type: Mapped[str] = mapped_column(String(40), nullable=False)  # sale, purchase, adjust, import
    quantity_change: Mapped[float] = mapped_column(Float, nullable=False)
    stock_before: Mapped[float] = mapped_column(Float, nullable=False)
    stock_after: Mapped[float] = mapped_column(Float, nullable=False)
    reference: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    product: Mapped[Product] = relationship(back_populates="stock_movements")


class ImportBatch(Base):
    __tablename__ = "import_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="completed")
    rows_total: Mapped[int] = mapped_column(Integer, default=0)
    rows_imported: Mapped[int] = mapped_column(Integer, default=0)
    rows_skipped: Mapped[int] = mapped_column(Integer, default=0)
    stock_deducted: Mapped[float] = mapped_column(Float, default=0.0)
    unmatched_skus: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    sales: Mapped[list[Sale]] = relationship(back_populates="import_batch")


class Job(Base):
    """A work ticket for a motorcycle left in the shop.

    Collects the parts and labour for one bike while work is under way, then
    converts into a Sale at checkout. Stock moves at checkout and nowhere else,
    so a bike waiting in the queue never holds parts the counter could sell.
    """

    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_no: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    priority: Mapped[str] = mapped_column(String(20), default="normal")
    customer_id: Mapped[Optional[int]] = mapped_column(ForeignKey("customers.id"), nullable=True)
    customer_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    contact: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    plate_no: Mapped[Optional[str]] = mapped_column(String(30), nullable=True, index=True)
    motorcycle: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    complaint: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    mechanic: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    ready_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    cancel_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sale_id: Mapped[Optional[int]] = mapped_column(ForeignKey("sales.id"), nullable=True)

    customer: Mapped[Optional[Customer]] = relationship()
    sale: Mapped[Optional[Sale]] = relationship()
    lines: Mapped[list["JobLine"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )


class JobLine(Base):
    """One part or labour line on a job ticket.

    Labour follows the shop's existing convention: a product whose SKU starts
    with LABOR, which carries no stock.
    """

    __tablename__ = "job_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    sku: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    product_name: Mapped[str] = mapped_column(String(250), nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    unit_price: Mapped[float] = mapped_column(Float, nullable=False)
    added_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    job: Mapped[Job] = relationship(back_populates="lines")
    product: Mapped[Product] = relationship()


class AppMeta(Base):
    __tablename__ = "app_meta"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)