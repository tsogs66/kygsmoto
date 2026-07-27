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
- Dashboard KPIs (today / week / month / year), month picker, top movers & profitable-item graphs (by sales / qty / profit)
- Comprehensive reporting: daily / weekly / monthly / yearly, category charts, product performance
- Inventory column sorting + soft-delete stock; sales item search + week/month/year history filters
- **Sales report upload**: preview matches, then import and deduct stock from written sales files
- Empty DB on first start — import the KYGS workbook / stock CSV, or add products manually (no hard-coded demo sales/inventory)
- **Backdate sales** on POS with a sale date/time picker
- **Handwritten sales photo scan** (OCR) with editable review — correct qty/price/date and select inventory items before import
- PWA install for Android; Docker image for Proxmox LXC (includes Tesseract OCR)

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

**Full step-by-step (create CT, Console login, Docker on Debian, clone, open app):**  
👉 **[deploy/PROXMOX.md](deploy/PROXMOX.md)**

Quick path on the **PVE host**:

```bash
# 1) Create nested Debian LXC (adjust CTID / storage / bridge / template)
pct create 210 local:vztmpl/debian-12-standard_12.7-1_amd64.tar.zst \
  --hostname kygsmoto --memory 2048 --cores 2 --swap 512 \
  --rootfs local-lvm:16 --net0 name=eth0,bridge=vmbr0,ip=dhcp \
  --unprivileged 1 --features nesting=1,keyctl=1 --onboot 1 --start 1

# 2) Enter CT (no Console password needed)
pct enter 210
```

Inside the **LXC** (Debian Bookworm — do **not** use `docker-compose-v2`):

```bash
apt update && apt install -y docker.io git curl \
  && systemctl enable --now docker \
  && mkdir -p /usr/local/lib/docker/cli-plugins \
  && curl -fsSL https://github.com/docker/compose/releases/download/v2.32.4/docker-compose-linux-x86_64 \
       -o /usr/local/lib/docker/cli-plugins/docker-compose \
  && chmod +x /usr/local/lib/docker/cli-plugins/docker-compose \
  && cd ~ && rm -rf kygsmoto \
  && git clone -b cursor/kygsmoto-sales-inventory-9004 https://github.com/tsogs66/kygsmoto.git \
  && cd kygsmoto \
  && docker compose up -d --build \
  && echo "Open http://$(hostname -I | awk '{print $1}'):8000"
```

**Autoupdate later:**

```bash
cd ~/kygsmoto && ./deploy/autoupdate.sh --branch cursor/kygsmoto-sales-inventory-9004
```

- **Web app:** `http://<lxc-ip>:8000` — **no app login** (auth not implemented yet)  
- **Console `kygsmoto login:`:** Linux root only — set with `pct exec 210 -- passwd` on the PVE host  
- Helper scripts: [`deploy/create-lxc.sh`](deploy/create-lxc.sh) · [`deploy/autoupdate.sh`](deploy/autoupdate.sh)

Or without Docker (Python build inside the CT):

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

- [`samples/kygs_current_inventory.csv`](samples/kygs_current_inventory.csv) — **current inventory** extracted from the workbook (~1,867 SKUs)  
- [`samples/kygs_sales_export.csv`](samples/kygs_sales_export.csv) — **sales lines** extracted from the SALES sheet  
- [`samples/kygs_stock_upload_template.csv`](samples/kygs_stock_upload_template.csv) — small stock-upload template  
- [`samples/sample_sales_import.csv`](samples/sample_sales_import.csv) — generic demo  

Re-extract anytime:

```bash
python backend/scripts/extract_kygs_csv.py "KYGS APRIL 2025.xlsm" samples
```

### Stock CSV upload

UI: **Import / Stock Upload** → Stock CSV section.

| Mode | Behavior |
| --- | --- |
| `set` | Absolute stock from `ENDING STOCKS` / `QTY` |
| `adjust` | Add/subtract using `ADJUST` (or qty as delta) |
| `upsert` | Like `set`, and create missing SKUs |

API: `POST /api/imports/stock/preview` and `POST /api/imports/stock` (`mode=set|adjust|upsert`).

When uploading a full `.xlsm` for sales, the importer prefers the **SALES** sheet automatically.

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
