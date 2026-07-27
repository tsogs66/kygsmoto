#!/usr/bin/env python3
"""Extract SALES and current INVENTORY CSVs from KYGS APRIL 2025.xlsm."""

from __future__ import annotations

import csv
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def shared_strings(z: zipfile.ZipFile) -> list[str]:
    try:
        root = ET.fromstring(z.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    out = []
    for si in root.findall("m:si", NS):
        texts = [
            t.text or ""
            for t in si.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t")
        ]
        out.append("".join(texts))
    return out


def sheet_paths(z: zipfile.ZipFile) -> dict[str, str]:
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    rid = {r.attrib["Id"]: r.attrib["Target"] for r in rels}
    out = {}
    for sh in wb.findall("m:sheets/m:sheet", NS):
        name = sh.attrib["name"]
        target = rid[sh.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]]
        path = target if target.startswith("xl/") else f"xl/{target.lstrip('/')}"
        out[name] = path
    return out


def load_cells(z: zipfile.ZipFile, path: str, ss: list[str]) -> dict[int, dict[str, object]]:
    root = ET.fromstring(z.read(path))
    rows: dict[int, dict[str, object]] = defaultdict(dict)
    for c in root.findall(".//m:sheetData/m:row/m:c", NS):
        ref = c.attrib.get("r")
        if not ref:
            continue
        m = re.match(r"([A-Z]+)(\d+)", ref)
        if not m:
            continue
        col, row = m.group(1), int(m.group(2))
        v = c.find("m:v", NS)
        if v is None or v.text is None:
            continue
        val: object = v.text
        if c.attrib.get("t") == "s":
            val = ss[int(val)]
        else:
            try:
                if "." in str(val) or "e" in str(val).lower():
                    val = float(val)
                else:
                    val = int(val)
            except ValueError:
                pass
        rows[row][col] = val
    return rows


def cell(rows, r, c, default=""):
    v = rows.get(r, {}).get(c, default)
    if v is None:
        return default
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


def excel_date(v) -> str:
    try:
        return (datetime(1899, 12, 30) + timedelta(days=float(v))).strftime("%Y-%m-%d")
    except Exception:
        return str(v)


def extract(workbook: Path, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(workbook) as z:
        ss = shared_strings(z)
        sheets = sheet_paths(z)
        inv = load_cells(z, sheets["INVENTORY"], ss)
        sales = load_cells(z, sheets["SALES"], ss)

    inv_path = out_dir / "kygs_current_inventory.csv"
    with inv_path.open("w", newline="", encoding="utf-8") as fp:
        w = csv.writer(fp)
        w.writerow([
            "CATEGORY",
            "ITEM CODE",
            "DESCRIPTION",
            "SUPPLIER",
            "UNIT PRICE",
            "OPENING STOCKS",
            "PURCHASE QUANTITY",
            "SALES QUANTITY",
            "ENDING STOCKS",
            "RETAIL PRICE",
        ])
        inv_rows = 0
        for r in sorted(inv):
            if r < 4:
                continue
            sku = str(cell(inv, r, "B", "")).strip()
            name = str(cell(inv, r, "C", "")).strip()
            if not sku or not name or sku.upper() == "ITEM CODE":
                continue
            w.writerow([
                cell(inv, r, "A"),
                sku,
                name,
                cell(inv, r, "D"),
                cell(inv, r, "E", 0),
                cell(inv, r, "F", 0),
                cell(inv, r, "I", 0),
                cell(inv, r, "N", 0),
                cell(inv, r, "P", 0),
                cell(inv, r, "M", 0),
            ])
            inv_rows += 1

    sales_path = out_dir / "kygs_sales_export.csv"
    with sales_path.open("w", newline="", encoding="utf-8") as fp:
        w = csv.writer(fp)
        w.writerow(["DATE", "ITEM CODE", "ITEM DESCRIPTION", "QTY", "PRICE", "DISCNT", "TOTAL"])
        sales_rows = 0
        for r in sorted(sales):
            if r < 3:
                continue
            sku = str(cell(sales, r, "B", "")).strip()
            if not sku:
                continue
            w.writerow([
                excel_date(cell(sales, r, "A")),
                sku,
                cell(sales, r, "C"),
                cell(sales, r, "D", 0),
                cell(sales, r, "E", 0),
                cell(sales, r, "F", 0),
                cell(sales, r, "G", 0),
            ])
            sales_rows += 1

    # Minimal stock-management template (ITEM CODE + ENDING STOCKS)
    stock_path = out_dir / "kygs_stock_upload_template.csv"
    with stock_path.open("w", newline="", encoding="utf-8") as fp:
        w = csv.writer(fp)
        w.writerow(["ITEM CODE", "DESCRIPTION", "ENDING STOCKS", "UNIT PRICE", "RETAIL PRICE", "CATEGORY", "SUPPLIER"])
        # first 15 inventory rows as examples
        count = 0
        for r in sorted(inv):
            if r < 4:
                continue
            sku = str(cell(inv, r, "B", "")).strip()
            name = str(cell(inv, r, "C", "")).strip()
            if not sku or not name:
                continue
            w.writerow([
                sku,
                name,
                cell(inv, r, "P", 0),
                cell(inv, r, "E", 0),
                cell(inv, r, "M", 0),
                cell(inv, r, "A"),
                cell(inv, r, "D"),
            ])
            count += 1
            if count >= 20:
                break

    return {
        "inventory_csv": str(inv_path),
        "inventory_rows": inv_rows,
        "sales_csv": str(sales_path),
        "sales_rows": sales_rows,
        "stock_template_csv": str(stock_path),
    }


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    workbook = Path(sys.argv[1]) if len(sys.argv) > 1 else root / "KYGS APRIL 2025.xlsm"
    out_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else root / "samples"
    if not workbook.exists():
        print(f"Workbook not found: {workbook}", file=sys.stderr)
        return 1
    result = extract(workbook, out_dir)
    print(
        f"Wrote {result['inventory_rows']} inventory rows → {result['inventory_csv']}\n"
        f"Wrote {result['sales_rows']} sales rows → {result['sales_csv']}\n"
        f"Stock template → {result['stock_template_csv']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
