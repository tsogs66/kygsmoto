"""SQLite storage layer: connection handling and schema management."""
import os
import sqlite3
import threading
from contextlib import contextmanager

DB_PATH = os.environ.get(
    "KYGS_DB",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "kygs.db"),
)

_local = threading.local()

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS users (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    username             TEXT NOT NULL UNIQUE COLLATE NOCASE,
    full_name            TEXT NOT NULL DEFAULT '',
    password_hash        TEXT NOT NULL,
    salt                 TEXT NOT NULL,
    iterations           INTEGER NOT NULL,
    role                 TEXT NOT NULL DEFAULT 'cashier',
    active               INTEGER NOT NULL DEFAULT 1,
    must_change_password INTEGER NOT NULL DEFAULT 0,
    failed_attempts      INTEGER NOT NULL DEFAULT 0,
    locked_until         TEXT,
    last_login_at        TEXT,
    created_at           TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at           TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sessions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at TEXT NOT NULL,
    revoked    INTEGER NOT NULL DEFAULT 0,
    ip         TEXT,
    user_agent TEXT
);
CREATE INDEX IF NOT EXISTS ix_sessions_user ON sessions(user_id);

CREATE TABLE IF NOT EXISTS categories (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    name   TEXT NOT NULL UNIQUE COLLATE NOCASE,
    prefix TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS suppliers (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    code            TEXT NOT NULL UNIQUE COLLATE NOCASE,
    name            TEXT NOT NULL DEFAULT '',
    contact         TEXT NOT NULL DEFAULT '',
    phone           TEXT NOT NULL DEFAULT '',
    email           TEXT NOT NULL DEFAULT '',
    address         TEXT NOT NULL DEFAULT '',
    lead_time_days  REAL NOT NULL DEFAULT 7,
    order_cycle_days REAL NOT NULL DEFAULT 30,
    min_order_value REAL NOT NULL DEFAULT 0,
    active          INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS items (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    sku           TEXT NOT NULL UNIQUE COLLATE NOCASE,
    barcode       TEXT COLLATE NOCASE,
    description   TEXT NOT NULL,
    category_id   INTEGER REFERENCES categories(id),
    supplier_id   INTEGER REFERENCES suppliers(id),
    unit_cost     REAL NOT NULL DEFAULT 0,
    retail_price  REAL NOT NULL DEFAULT 0,
    stock_qty     REAL NOT NULL DEFAULT 0,
    reorder_point REAL NOT NULL DEFAULT 0,
    reorder_qty   REAL NOT NULL DEFAULT 0,
    location      TEXT NOT NULL DEFAULT '',
    active        INTEGER NOT NULL DEFAULT 1,
    delisted      INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_items_category ON items(category_id);
CREATE INDEX IF NOT EXISTS ix_items_supplier ON items(supplier_id);
CREATE INDEX IF NOT EXISTS ix_items_desc ON items(description);
CREATE INDEX IF NOT EXISTS ix_items_barcode ON items(barcode);

CREATE TABLE IF NOT EXISTS services (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    code    TEXT NOT NULL UNIQUE COLLATE NOCASE,
    name    TEXT NOT NULL,
    fee     REAL NOT NULL DEFAULT 0,
    minutes INTEGER NOT NULL DEFAULT 0,
    active  INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS sales (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    receipt_no      TEXT NOT NULL UNIQUE,
    ts              TEXT NOT NULL DEFAULT (datetime('now')),
    business_date   TEXT NOT NULL,
    user_id         INTEGER NOT NULL REFERENCES users(id),
    customer_name   TEXT NOT NULL DEFAULT '',
    plate_no        TEXT NOT NULL DEFAULT '',
    subtotal        REAL NOT NULL DEFAULT 0,
    discount        REAL NOT NULL DEFAULT 0,
    total           REAL NOT NULL DEFAULT 0,
    parts_total     REAL NOT NULL DEFAULT 0,
    labor_total     REAL NOT NULL DEFAULT 0,
    cost_total      REAL NOT NULL DEFAULT 0,
    profit          REAL NOT NULL DEFAULT 0,
    amount_tendered REAL NOT NULL DEFAULT 0,
    change_due      REAL NOT NULL DEFAULT 0,
    status          TEXT NOT NULL DEFAULT 'completed',
    voided_by       INTEGER REFERENCES users(id),
    voided_at       TEXT,
    void_reason     TEXT NOT NULL DEFAULT '',
    note            TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_sales_date ON sales(business_date);
CREATE INDEX IF NOT EXISTS ix_sales_user ON sales(user_id);

CREATE TABLE IF NOT EXISTS sale_lines (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    sale_id     INTEGER NOT NULL REFERENCES sales(id) ON DELETE CASCADE,
    line_type   TEXT NOT NULL DEFAULT 'item',
    item_id     INTEGER REFERENCES items(id),
    service_id  INTEGER REFERENCES services(id),
    sku         TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL,
    qty         REAL NOT NULL,
    unit_price  REAL NOT NULL,
    unit_cost   REAL NOT NULL DEFAULT 0,
    discount    REAL NOT NULL DEFAULT 0,
    total       REAL NOT NULL,
    profit      REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_lines_sale ON sale_lines(sale_id);
CREATE INDEX IF NOT EXISTS ix_lines_item ON sale_lines(item_id);

CREATE TABLE IF NOT EXISTS payments (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    sale_id   INTEGER NOT NULL REFERENCES sales(id) ON DELETE CASCADE,
    method    TEXT NOT NULL DEFAULT 'CASH',
    amount    REAL NOT NULL,
    reference TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_payments_sale ON payments(sale_id);

CREATE TABLE IF NOT EXISTS stock_moves (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            TEXT NOT NULL DEFAULT (datetime('now')),
    item_id       INTEGER NOT NULL REFERENCES items(id),
    qty_delta     REAL NOT NULL,
    balance_after REAL NOT NULL,
    move_type     TEXT NOT NULL,
    ref_type      TEXT NOT NULL DEFAULT '',
    ref_id        INTEGER,
    unit_cost     REAL NOT NULL DEFAULT 0,
    user_id       INTEGER REFERENCES users(id),
    note          TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_moves_item ON stock_moves(item_id, ts);

CREATE TABLE IF NOT EXISTS purchase_orders (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    po_no       TEXT NOT NULL UNIQUE,
    supplier_id INTEGER NOT NULL REFERENCES suppliers(id),
    status      TEXT NOT NULL DEFAULT 'draft',
    created_by  INTEGER NOT NULL REFERENCES users(id),
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    ordered_at  TEXT,
    expected_at TEXT,
    received_at TEXT,
    total_cost  REAL NOT NULL DEFAULT 0,
    note        TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS po_lines (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    po_id        INTEGER NOT NULL REFERENCES purchase_orders(id) ON DELETE CASCADE,
    item_id      INTEGER NOT NULL REFERENCES items(id),
    qty_ordered  REAL NOT NULL,
    qty_received REAL NOT NULL DEFAULT 0,
    unit_cost    REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_polines_po ON po_lines(po_id);

CREATE TABLE IF NOT EXISTS held_carts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    label      TEXT NOT NULL DEFAULT '',
    payload    TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS demand_history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id    INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    period     TEXT NOT NULL,
    qty        REAL NOT NULL DEFAULT 0,
    revenue    REAL NOT NULL DEFAULT 0,
    source     TEXT NOT NULL DEFAULT 'import',
    UNIQUE(item_id, period, source)
);
CREATE INDEX IF NOT EXISTS ix_demand_item ON demand_history(item_id, period);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        TEXT NOT NULL DEFAULT (datetime('now')),
    user_id   INTEGER REFERENCES users(id),
    username  TEXT NOT NULL DEFAULT '',
    action    TEXT NOT NULL,
    entity    TEXT NOT NULL DEFAULT '',
    entity_id TEXT NOT NULL DEFAULT '',
    detail    TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_audit_ts ON audit_log(ts);

CREATE TABLE IF NOT EXISTS monthly_summary (
    period     TEXT PRIMARY KEY,
    sales      REAL NOT NULL DEFAULT 0,
    income     REAL NOT NULL DEFAULT 0,
    expenses   REAL NOT NULL DEFAULT 0,
    net_profit REAL NOT NULL DEFAULT 0,
    cash       REAL NOT NULL DEFAULT 0,
    merchandise REAL NOT NULL DEFAULT 0,
    equity     REAL NOT NULL DEFAULT 0,
    source     TEXT NOT NULL DEFAULT 'import'
);

CREATE TABLE IF NOT EXISTS cash_drawer (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    opened_at    TEXT NOT NULL DEFAULT (datetime('now')),
    opened_by    INTEGER NOT NULL REFERENCES users(id),
    opening_cash REAL NOT NULL DEFAULT 0,
    closed_at    TEXT,
    closed_by    INTEGER REFERENCES users(id),
    counted_cash REAL,
    expected_cash REAL,
    variance     REAL,
    note         TEXT NOT NULL DEFAULT ''
);
"""

DEFAULT_SETTINGS = {
    "shop_name": "KYGS Motorcycle Parts",
    "shop_address": "",
    "shop_phone": "",
    "currency": "PHP",
    "currency_symbol": "₱",
    "receipt_footer": "Thank you and ride safe!",
    "low_stock_default": "1",
    "service_level_z": "1.65",
    "default_lead_time_days": "7",
    "session_hours": "12",
}


def connect() -> sqlite3.Connection:
    """Return this thread's connection, creating it on first use."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        _local.conn = conn
    return conn


@contextmanager
def transaction():
    """Run a block inside an IMMEDIATE transaction, rolling back on error."""
    conn = connect()
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except Exception:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def query(sql, params=()):
    return connect().execute(sql, params).fetchall()


def query_one(sql, params=()):
    return connect().execute(sql, params).fetchone()


def execute(sql, params=()):
    return connect().execute(sql, params)


def init_db():
    """Create the schema and fill in default settings."""
    conn = connect()
    conn.executescript(SCHEMA)
    for key, value in DEFAULT_SETTINGS.items():
        conn.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO NOTHING",
            (key, value),
        )


def get_setting(key, default=None):
    row = query_one("SELECT value FROM settings WHERE key = ?", (key,))
    return row["value"] if row else default


def set_setting(key, value):
    execute(
        "INSERT INTO settings(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value)),
    )
