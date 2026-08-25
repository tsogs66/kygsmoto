# KYGS POS &amp; Inventory Management

An all-in-one point of sale, stock control and demand-forecasting system for
**KYGS Motorcycle Parts** — a motorcycle parts and service shop.

It replaces the `KYGS APRIL 2025.xlsm` workbook: the same 1,867 items, 21
categories, 6 suppliers and 45 labour rates, but with real user accounts, a
live till, an auditable stock ledger, and forecasting that tells the shop what
to reorder before it runs out.

---

## Quick start

### Docker (recommended if you already run Docker)

Listens on **port 8001**, so it will not collide with anything already on 8000:

```bash
docker compose up -d --build
docker compose logs kygspos | grep -A3 "First run"     # the generated admin password
docker compose run --rm kygspos \
    python -m backend.seed.import_xlsm "/app/KYGS APRIL 2025.xlsm"
docker compose restart kygspos
```

The database lives on the named volume `kygspos_data` at `/data/kygs.db`, so it
survives rebuilds. Change the host port by editing the left-hand number under
`ports:` in `docker-compose.yml`.

Back it up from the host with:

```bash
docker run --rm -v kygspos_data:/d -v "$PWD":/b alpine \
    cp /d/kygs.db /b/kygs-$(date +%F).db
```

### Without Docker

```bash
./run.sh                      # http://127.0.0.1:8000
./run.sh --lan                # let other tills on the shop network connect
```

On first run the server creates an `admin` account and prints a generated
password **once** to the console. You are required to change it at first
sign-in. To set your own instead:

```bash
KYGS_ADMIN_PASSWORD='ChooseSomething123' ./run.sh
```

### Load the existing workbook

```bash
python3 -m backend.seed.import_xlsm "KYGS APRIL 2025.xlsm"
```

The import is idempotent — re-running it updates matched records rather than
duplicating them. It reports any item code the workbook uses twice.

### Add the common labour jobs

The workbook supplies the 45 rates KYGS already charges. This adds the other
jobs a motorcycle shop does — CVT work, brake bleeding, electrical repairs,
wheel work, PMS — as labour lines that carry no stock:

```bash
python3 -m backend.seed.services_catalog --dry-run   # preview
python3 -m backend.seed.services_catalog             # apply
python3 -m backend.seed.services_catalog --zero-fees # add them unpriced
```

Also idempotent, and it never overwrites a rate the shop already set. The
suggested fees follow the shop's own rate card, but **review them in
Admin → Services before trading on them**.

### Tests

```bash
pip install -r requirements-dev.txt
python3 -m pytest tests/ -q          # 106 tests
```

---

## What it does

### Point of sale
Barcode or keyword search, parts and labour on the same receipt, split
payments (cash / GCash / bank / card), held sales, printable receipts, and a
cash drawer that reconciles counted cash against expected.

Every sale is one atomic transaction: if any line fails — an oversell, a bad
payment — nothing is committed and no stock moves. Stock never silently goes
negative at the till.

### Stock control
Full item master with cost, retail price, reorder point, supplier and shelf
location. Adjustments require a reason from a fixed list; physical stocktakes
record every variance and its peso impact. Nothing is ever deleted — items are
delisted so history and receipt reprints keep working.

Every quantity change writes a `stock_moves` row with the balance after the
move, so any figure can be traced back to the sale, delivery or adjustment
that caused it.

### Purchasing
Draft → ordered → partly received → received, with partial deliveries and
over-receipt protection. Booking in a delivery updates the item's valuation
cost. Quantities on open orders count as incoming stock, so the system will not
tell you to reorder something already on its way.

### Demand forecasting and reorder advice
This is the part the spreadsheet could not do.

A parts counter sells most of its 1,800+ lines a handful of times a month, so
the demand series are mostly zeros with occasional spikes. Ordinary
exponential smoothing biases badly on that shape, so each item's history is
first classified by the **Syntetos-Boylan** scheme — average demand interval
against the squared coefficient of variation:

| Pattern | Meaning | Forecast method |
|---|---|---|
| Smooth | Sells often, steady quantity | Holt's linear trend |
| Erratic | Sells often, jumpy quantity | Holt's linear trend |
| Intermittent | Sells rarely, steady quantity | Croston / SBA |
| Lumpy | Sells rarely, jumpy quantity | Croston / SBA |

From the resulting daily demand rate the system computes, per item:

- **Safety stock** — `z × σ × √(lead time + review period)`
- **Reorder point** — lead-time demand plus safety stock
- **Economic order quantity** — the Wilson EOQ
- **Days of cover** and a projected stockout date
- **Movement class** — fast / medium / slow / dead
- **ABC × XYZ** — value against predictability, each cell with a stocking policy

The *What to order* screen ranks every suggestion by an urgency score
(shortfall, cover remaining, and ABC class), explains each one in plain
language ("Only 3 days of cover left, supplier takes 7 days"), groups the total
cost by supplier, and can turn the whole list into draft purchase orders in one
click.

Two design decisions worth knowing about:

- **Cold start.** On day one there is no till history, so items fall back to
  the demand imported from the workbook, flagged in the UI as `imported`. Items
  with no evidence anywhere are reported honestly as having no demand data
  rather than being guessed at.
- **Minimum observation window.** A rate is never inferred from fewer than 28
  days of shelf time. Without that floor a single sale on the window's last day
  reads as "one a day" and would order months of stock off one transaction.

### Reporting
Sales by day / week / month, top items by revenue, quantity or profit,
category performance, per-cashier takings with a tender breakdown and a void
log, a trading account, and stock valuation at cost and retail. Inventory,
sales, reorder and movement data all export to CSV.

---

## Users and roles

Passwords are hashed with PBKDF2-SHA256 (240,000 iterations, per-user salt).
Sessions are server-side bearer tokens that can be revoked; five failed
sign-ins lock an account for 15 minutes. Login errors are deliberately
identical whether or not the username exists.

| | Cashier | Manager | Admin |
|---|:---:|:---:|:---:|
| Sell at the till | ✅ | ✅ | ✅ |
| Look up stock | ✅ | ✅ | ✅ |
| Basic sales figures | ✅ | ✅ | ✅ |
| Discounts and voids | — | ✅ | ✅ |
| Stock adjustments, stocktakes | — | ✅ | ✅ |
| Purchasing and receiving | — | ✅ | ✅ |
| Forecasting and financial reports | — | ✅ | ✅ |
| User accounts | — | — | ✅ |

Sensitive actions — sign-ins, voids, discounts, adjustments, price changes,
user changes — are written to an append-only audit log with the user, the
entity and what changed.

---

## Layout

```
backend/
  app/
    main.py              FastAPI app, first-run admin bootstrap
    db.py                SQLite schema and transaction helpers
    security.py          Password hashing, sessions, role permissions
    routers/             auth, catalog, pos, inventory, purchasing,
                         analytics_api, reports, settings_api
    services/
      forecast.py        Croston/SBA, Holt, EOQ, safety stock, ABC — pure maths
      analytics.py       Applies the maths to live sales data
  seed/import_xlsm.py       Workbook importer
  seed/services_catalog.py  Common motorcycle labour jobs
frontend/                Vanilla ES modules, no build step
tests/                   106 tests
Dockerfile               Container image (database on a /data volume)
docker-compose.yml       Runs on host port 8001
```

**Stack:** Python 3.11+, FastAPI, SQLite (WAL). The front end is plain ES
modules with no framework, bundler or CDN — the shop PC can run this offline
and it will still work in five years.

**Dependencies** are deliberately minimal: FastAPI, uvicorn, pydantic, and
openpyxl for the one-off import. Password hashing and session tokens use only
the Python standard library.

---

## Notes for the shop

- **Back up `backend/kygs.db`.** That single file is the whole business. Copy it
  somewhere else daily; the container or PC it runs on is not a backup.
- **Keep supplier lead times accurate.** The reorder point is calculated from
  them, so a wrong lead time produces wrong advice. Set them under
  *Admin → Suppliers*.
- **Service level** (*Admin → Shop settings*) trades stock against stockouts.
  1.65 targets roughly 95% availability; raise it to hold more buffer, lower it
  to free up cash.
- The workbook's `JOURNAL`, `LEDGER` and `BALANCE SHEET` sheets are
  double-entry bookkeeping and are **not** imported — the till does not track
  operating expenses, so it produces a trading account rather than a full profit
  and loss statement. The 21 months of monthly trading history are imported for
  reference.
