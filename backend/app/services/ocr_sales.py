"""OCR + parse handwritten / photographed sales reports into editable rows."""

from __future__ import annotations

import io
import re
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.models import Product
from app.services.import_sales import find_product


def extract_text_from_image(content: bytes, filename: str = "photo.jpg") -> dict[str, Any]:
    """Run OCR on an image. Returns text + engine metadata.

    Uses Tesseract when available. Handwriting accuracy varies — the UI always
    lets the user correct rows and pick inventory items.
    """
    try:
        from PIL import Image, ImageOps, ImageFilter
    except ImportError as exc:
        raise RuntimeError("Pillow is required for photo OCR. Install pillow.") from exc

    image = Image.open(io.BytesIO(content))
    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    # Upscale small phone photos slightly and boost contrast for OCR
    w, h = image.size
    if max(w, h) < 1600:
        scale = 1600 / max(w, h)
        image = image.resize((int(w * scale), int(h * scale)))
    gray = ImageOps.grayscale(image)
    gray = ImageOps.autocontrast(gray)
    gray = gray.filter(ImageFilter.SHARPEN)

    engine = "none"
    text = ""
    try:
        import pytesseract

        text = pytesseract.image_to_string(gray) or ""
        engine = "tesseract"
    except Exception as exc:  # noqa: BLE001 — degrade gracefully without tesseract
        text = ""
        engine = f"unavailable:{exc.__class__.__name__}"

    return {
        "filename": filename,
        "engine": engine,
        "raw_text": text.strip(),
        "image_width": image.size[0],
        "image_height": image.size[1],
    }


_DATE_RE = re.compile(
    r"(?:date|dated|petsa)?\s*[:\-]?\s*"
    r"(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4}|\d{4}[\/\-\.]\d{1,2}[\/\-\.]\d{1,2})",
    re.I,
)
_QTY_PRICE_RE = re.compile(
    r"^(?P<label>.+?)\s+(?:x|×|\*)?\s*(?P<qty>\d+(?:\.\d+)?)\s+"
    r"(?:pcs?|pc|x|×)?\s*(?P<price>\d[\d,]*(?:\.\d+)?)\s*$",
    re.I,
)
_SKU_LINE_RE = re.compile(
    r"^(?P<sku>[A-Za-z0-9][A-Za-z0-9\-_/]{1,24})\s+"
    r"(?P<label>.+?)\s+(?P<qty>\d+(?:\.\d+)?)\s+"
    r"(?P<price>\d[\d,]*(?:\.\d+)?)\s*$",
)
_SIMPLE_QTY_RE = re.compile(
    r"^(?P<label>.+?)\s+(?:qty|x|×|\*)\s*(?P<qty>\d+(?:\.\d+)?)\s*$",
    re.I,
)
_TRAILING_QTY_RE = re.compile(
    r"^(?P<label>.+?)\s+(?P<qty>\d+(?:\.\d+)?)\s*$",
)


def _parse_date_from_text(text: str) -> Optional[str]:
    m = _DATE_RE.search(text)
    if not m:
        return None
    raw = m.group(1).strip()
    candidates = [raw, raw.replace(".", "/").replace("-", "/")]
    formats = (
        "%m/%d/%Y",
        "%d/%m/%Y",
        "%Y/%m/%d",
        "%m/%d/%y",
        "%d/%m/%y",
        "%Y-%m-%d",
        "%m-%d-%Y",
        "%d-%m-%Y",
    )
    for candidate in candidates:
        for fmt in formats:
            try:
                return datetime.strptime(candidate, fmt).date().isoformat()
            except ValueError:
                continue
    try:
        import pandas as pd

        dt = pd.to_datetime(raw, dayfirst=True, errors="coerce")
        if pd.notna(dt):
            return dt.date().isoformat()
    except Exception:
        pass
    return None


def _clean_label(label: str) -> str:
    label = re.sub(r"\s+", " ", label).strip(" -·•|\t")
    label = re.sub(r"^(item|product|desc|description)\s*[:\-]\s*", "", label, flags=re.I)
    return label.strip()


def parse_ocr_lines(raw_text: str) -> list[dict]:
    """Parse OCR text into candidate sales line dicts (not yet matched)."""
    default_date = _parse_date_from_text(raw_text)
    rows: list[dict] = []
    row_number = 1
    for line in raw_text.splitlines():
        line = line.strip()
        if not line or len(line) < 3:
            continue
        lower = line.lower()
        if lower.startswith(("total", "subtotal", "grand", "cash", "change", "signature", "page")):
            continue
        if _DATE_RE.fullmatch(line) or lower.startswith("date"):
            continue

        sku = None
        label = None
        qty = None
        price = None

        m = _SKU_LINE_RE.match(line)
        if m:
            sku = m.group("sku").strip()
            label = _clean_label(m.group("label"))
            qty = float(m.group("qty"))
            price = float(m.group("price").replace(",", ""))
        else:
            m = _QTY_PRICE_RE.match(line)
            if m:
                label = _clean_label(m.group("label"))
                qty = float(m.group("qty"))
                price = float(m.group("price").replace(",", ""))
            else:
                m = _SIMPLE_QTY_RE.match(line)
                if m:
                    label = _clean_label(m.group("label"))
                    qty = float(m.group("qty"))
                else:
                    m = _TRAILING_QTY_RE.match(line)
                    if m and not re.fullmatch(r"\d[\d,./\-]*", m.group("label")):
                        # Avoid treating bare numbers / dates as items
                        label = _clean_label(m.group("label"))
                        qty = float(m.group("qty"))

        if not label or qty is None or qty <= 0:
            # Keep unmatched OCR lines as editable suggestions (qty blank → user fills)
            if len(line) >= 4 and not re.fullmatch(r"[\d\s.,/\-]+", line):
                rows.append({
                    "row_number": row_number,
                    "invoice_no": None,
                    "sale_date": default_date,
                    "sku": None,
                    "product_name": _clean_label(line),
                    "quantity": 1.0,
                    "unit_price": None,
                    "customer": None,
                    "ocr_text": line,
                    "status": "needs_review",
                    "message": "Could not parse qty/price — review and select item",
                })
                row_number += 1
            continue

        # Heuristic: first token may be SKU
        if not sku:
            parts = label.split()
            if parts and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9\-_/]{2,}", parts[0]) and len(parts) > 1:
                sku = parts[0]
                label = " ".join(parts[1:])

        rows.append({
            "row_number": row_number,
            "invoice_no": None,
            "sale_date": default_date,
            "sku": sku,
            "product_name": label,
            "quantity": qty,
            "unit_price": price,
            "customer": None,
            "ocr_text": line,
            "status": "parsed",
            "message": "Parsed from photo",
        })
        row_number += 1

    return rows


def _score_product(product: Product, query: str) -> float:
    q = query.lower().strip()
    if not q:
        return 0.0
    hay = f"{product.sku} {product.name} {product.brand or ''} {product.fitment or ''}".lower()
    if product.sku.lower() == q:
        return 100.0
    if product.sku.lower() in q or q in product.sku.lower():
        return 90.0
    if product.name.lower() == q:
        return 85.0
    if q in product.name.lower():
        return 70.0 + min(15.0, len(q) / max(len(product.name), 1) * 15)
    tokens = [t for t in re.split(r"[^a-z0-9]+", q) if len(t) > 2]
    if not tokens:
        return 0.0
    hits = sum(1 for t in tokens if t in hay)
    return (hits / len(tokens)) * 60.0


def suggest_products(db: Session, query: str, limit: int = 8) -> list[dict]:
    products = db.query(Product).filter(Product.is_active.is_(True)).all()
    scored = []
    for p in products:
        score = _score_product(p, query)
        if score >= 25:
            scored.append((score, p))
    scored.sort(key=lambda x: -x[0])
    out = []
    for score, p in scored[:limit]:
        out.append({
            "id": p.id,
            "sku": p.sku,
            "name": p.name,
            "sell_price": p.sell_price,
            "cost_price": p.cost_price,
            "stock_qty": p.stock_qty,
            "score": round(score, 1),
        })
    return out


def match_ocr_rows(db: Session, rows: list[dict], mode: str = "sale") -> list[dict]:
    matched = unmatched = 0
    total_qty = 0.0
    enriched = []
    for row in rows:
        sku = row.get("sku")
        name = row.get("product_name")
        qty = float(row.get("quantity") or 0)
        product = find_product(db, sku, name)
        suggestions = []
        if not product and (sku or name):
            suggestions = suggest_products(db, f"{sku or ''} {name or ''}".strip())
            if suggestions:
                top = suggestions[0]
                if top["score"] >= 70:
                    product = db.query(Product).get(top["id"])

        entry = {
            **row,
            "matched_product_id": product.id if product else None,
            "matched_product_name": product.name if product else None,
            "current_stock": product.stock_qty if product else None,
            "suggestions": suggestions,
        }
        if product:
            matched += 1
            total_qty += qty
            default_price = product.cost_price if mode == "purchase" else product.sell_price
            if entry.get("unit_price") in (None, 0, 0.0):
                entry["unit_price"] = default_price
            entry["status"] = "matched"
            verb = "purchase receive" if mode == "purchase" else "sale import"
            entry["message"] = f"Matched {product.sku} — review before {verb}"
        else:
            unmatched += 1
            entry["status"] = "unmatched"
            entry["message"] = "Select the correct inventory item"
        enriched.append(entry)

    next_no = (enriched[-1]["row_number"] + 1) if enriched else 1
    for i in range(3):
        enriched.append({
            "row_number": next_no + i,
            "invoice_no": None,
            "sale_date": enriched[0]["sale_date"] if enriched else None,
            "sku": None,
            "product_name": None,
            "quantity": 1.0,
            "unit_price": None,
            "customer": None,
            "ocr_text": None,
            "matched_product_id": None,
            "matched_product_name": None,
            "current_stock": None,
            "suggestions": [],
            "status": "blank",
            "message": "Optional blank line — pick an item to add",
        })

    return enriched


def preview_sales_photo(db: Session, filename: str, content: bytes, mode: str = "sale") -> dict:
    ocr = extract_text_from_image(content, filename)
    parsed = parse_ocr_lines(ocr["raw_text"]) if ocr["raw_text"] else []
    if not parsed:
        parsed = [
            {
                "row_number": i,
                "invoice_no": None,
                "sale_date": None,
                "sku": None,
                "product_name": None,
                "quantity": 1.0,
                "unit_price": None,
                "customer": None,
                "ocr_text": None,
                "status": "blank",
                "message": "OCR found no lines — enter items manually from the photo",
            }
            for i in range(1, 6)
        ]
    rows = match_ocr_rows(db, parsed, mode=mode)
    matched = sum(1 for r in rows if r["status"] == "matched")
    unmatched = sum(1 for r in rows if r["status"] == "unmatched")
    total_qty = sum(float(r.get("quantity") or 0) for r in rows if r["status"] == "matched")
    kind = "purchase receive" if mode == "purchase" else "sales import"
    return {
        "filename": filename,
        "engine": ocr["engine"],
        "raw_text": ocr["raw_text"],
        "rows": rows,
        "matched_count": matched,
        "unmatched_count": unmatched,
        "total_qty": total_qty,
        "mode": mode,
        "message": (
            f"Review OCR rows, select inventory items, then confirm {kind}."
            if ocr["raw_text"]
            else f"OCR could not read the photo clearly. Enter lines manually for {kind}."
        ),
    }
