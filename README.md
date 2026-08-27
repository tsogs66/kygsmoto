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
- **Job queue** for bikes in the shop — parts and labour on one ticket, stock moves at checkout
- **Held sales** — park a basket at the till, identified by customer/plate, and it *reserves* its parts
- **Handwritten sales photo scan** (OCR) with editable review — correct qty/price/date and select inventory items before import
- PWA install for Android; Docker image for Proxmox LXC (includes Tesseract OCR)
- **No internet needed to look right** — fonts ship inside the image, so the
  app renders identically on a box with no route out

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
| GET/POST | `/api/holds` | Park a basket at the till; reserves its parts |
| DELETE | `/api/holds/{id}` | Discard or clear a hold, releasing its claim |
| GET/POST | `/api/jobs` | Job tickets for bikes in the shop |
| POST | `/api/jobs/{id}/checkout` | Turn a finished job into a sale |
| POST | `/api/purchases` | Receive stock |
| POST | `/api/imports/sales/preview` | Preview sales file |
| POST | `/api/imports/sales` | Import sales file & update stock |

## Held sales reserve stock

A basket parked at the till is a promise, so the parts in it stop being free
to sell. Nothing moves: the parts are still on the shelf, and `stock_qty`
keeps agreeing with the stock-take. What changes is what the counter may
spend:

```text
available = stock_qty − everything held
```

The claim is derived from the hold's own lines, so there is no counter to
keep in step — discard the hold and the claim goes with it. Labour reserves
nothing. Products report `reserved_qty` and `available_qty`, the POS item
list shows what is free, and a job ticket flags parts a held basket has
claimed.

Two guards enforce it, and both can be overridden with `allow_shortfall`
after the counter has been told what they are spending:

- A **sale** is refused only when it would eat into a reservation. With
  nothing held the till behaves exactly as before, negative stock included —
  parts often arrive ahead of their paperwork.
- A **hold** is refused when the shop cannot back it, since a promise over
  stock that is not there is not a promise.

Job checkout keeps its own `allow_negative_stock` confirmation, which now
also covers parts reserved at the till.

## Fonts

Oswald (headings, wordmark) and IBM Plex Sans (everything else) are served
from `frontend/public/fonts/`, not from Google. The shop's box may have no
route out, and the counter should look like the counter when the line is
down — fetching them remotely made the app's appearance depend on the
internet, and a failed fetch fell back silently to whatever face the device
had.

Both are the variable fonts, so one file covers every weight of a family:
115 KB for all four, against 418 KB of static instances. Each family ships
`latin` and `latin-ext`; `latin-ext` is not optional, because the peso sign
₱ (U+20B1) lives in its range. The service worker precaches all four, so an
installed app has them offline too.

Both faces are under the SIL Open Font License 1.1 — see
`frontend/public/fonts/OFL.txt`.

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
