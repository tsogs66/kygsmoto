# KYGSMOTO — Motorshop Sales & Inventory

Cross-platform sales, inventory, and reporting system for motorcycle shops. Built as a modern replacement for Excel/VBA workbooks that track products, sales orders, purchases, stock levels, and monthly/yearly reports.

**Runs on:** Proxmox LXC (Docker or bare Python), Windows, and Android (installable PWA).

## Why this exists

The original Excel+VBA pattern (seen in open systems like [Sales_Inventory_Tracker](https://github.com/Manjirigajmal/Sales_Inventory_Tracker), [inventory-monitoring-excel-vba](https://github.com/Rohanborse0253/inventory-monitoring-excel-vba), and Excel POS templates) typically provides:

| Excel/VBA capability | KYGSMOTO equivalent |
| --- | --- |
| Product / Supplier / Customer sheets | Inventory, suppliers, customers APIs + UI |
| Sales Order + stock deduction | Sales / POS with live stock updates |
| Purchase Order + stock in | Purchases module |
| Reorder alerts | Low / out-of-stock badges & dashboard alerts |
| Monthly dashboards | Daily / monthly / yearly reports |
| “Processed” sales flag + stock sync | **Sales File Import** (CSV/XLSX → match SKUs → deduct stock) |

> Note: This repository did not include an uploaded `.xlsm` source file. Feature design was reverse-engineered from the repo purpose (`sales and inventory management for motorshop`) and comparable public Excel/VBA systems documented in `docs/reference-systems.md`.

## Features

- Product catalog with SKU, brand, fitment (bike model), cost/sell price, reorder level
- Point-of-sale sales with automatic stock deduction
- Purchases / stock receiving
- Manual stock adjustments + full movement history
- Dashboard KPIs (today / month / year sales, profit, inventory value)
- Comprehensive reporting: sales by day/month/category/payment, top products, inventory valuation
- **Sales report upload**: preview matches, then import and deduct stock from written sales files
- Sample motorshop seed data (oils, tires, brakes, filters, labor)
- PWA install for Android; Docker image for Proxmox LXC

## Quick start (development)

```bash
# Backend
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r backend/requirements.txt
uvicorn app.main:app --app-dir backend --reload --host 0.0.0.0 --port 8000

# Frontend (separate terminal)
cd frontend && npm install && npm run dev
```

- API/docs: http://127.0.0.1:8000/docs  
- UI (Vite): http://127.0.0.1:5173  

## Deploy

### Proxmox LXC (Docker — recommended)

```bash
# Inside the LXC (Debian/Ubuntu) with Docker installed:
git clone <this-repo> && cd kygsmoto
docker compose up -d --build
# Open http://<lxc-ip>:8000
```

Or without Docker:

```bash
chmod +x deploy/lxc-install.sh
./deploy/lxc-install.sh
```

### Windows

```bat
deploy\windows-start.bat
```

Then open http://127.0.0.1:8000

### Android

See [deploy/ANDROID.md](deploy/ANDROID.md) — open the server URL in Chrome and **Add to Home screen**.

## Sales file import (stock sync)

Upload a CSV or Excel sales export under **Sales File Import**.

### KYGS workbook (full shop load)

The repo includes `KYGS APRIL 2025.xlsm` (KYGS Motorcycle Parts & Accessories).

```bash
# CLI
source .venv/bin/activate
python backend/scripts/import_kygs.py "KYGS APRIL 2025.xlsm"

# or API / UI: Sales File Import → "Import KYGS APRIL 2025.xlsm from server"
```

What gets imported:

| Sheet | Mapped to |
| --- | --- |
| INVENTORY | Products (ending stock, cost, retail) |
| SALES | Historical sales (stock **not** re-deducted) |
| INFOSHEET | Categories, suppliers, service/labor SKUs |
| CRITICAL | Reorder levels + critical flags |
| DELISTED | Inactive products |

### Incremental sales exports

Supported column aliases (auto-detected), including KYGS `SALES` layout:

- `DATE` / Sale_Date  
- `ITEM CODE` / SKU / Part_No  
- `ITEM DESCRIPTION` / Product  
- `QTY` / Quantity  
- `PRICE` / Unit_Price  
- `DISCNT` / Discount (optional)  
- `TOTAL`  
- Invoice / Processed (optional)

Sample files:

- [`samples/kygs_sales_export.csv`](samples/kygs_sales_export.csv) — extracted from the workbook SALES sheet  
- [`samples/sample_sales_import.csv`](samples/sample_sales_import.csv) — generic demo  

When uploading a full `.xlsm`, the importer prefers the **SALES** sheet automatically.

## API overview

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/reports/dashboard` | Dashboard KPIs |
| GET | `/api/reports/sales?period=daily\|monthly\|yearly` | Sales reports |
| GET | `/api/reports/inventory` | Inventory valuation & movements |
| GET/POST | `/api/products` | Inventory CRUD |
| POST | `/api/sales` | Create sale (deduct stock) |
| POST | `/api/purchases` | Receive stock |
| POST | `/api/imports/sales/preview` | Preview sales file |
| POST | `/api/imports/sales` | Import sales file & update stock |

## Project layout

```text
backend/          FastAPI + SQLAlchemy + SQLite
frontend/         React (Vite) PWA UI
samples/          Example sales import CSV
deploy/           LXC / Windows / Android helpers
docs/             Reference notes from Excel/VBA systems
Dockerfile        Multi-stage production image
docker-compose.yml
```

## License

MIT — adapt freely for your shop.
