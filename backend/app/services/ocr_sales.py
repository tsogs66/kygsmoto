"""OCR + parse handwritten / photographed sales reports into editable rows."""

from __future__ import annotations

import io
import re
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.models import Product
from app.services.import_sales import find_product


def extract_text_from_image(content: bytes, filename: str = "photo.jpg") -> dict[str, Any]:
    """Run OCR on an image. Returns text + engine metadata.

    Uses Tesseract when available. Tries several preprocess + PSM modes and
    keeps the richest reading. Handwriting still needs review in the UI.
    """
    try:
        from PIL import Image, ImageOps, ImageFilter, ImageEnhance
    except ImportError as exc:
        raise RuntimeError("Pillow is required for photo OCR. Install pillow.") from exc

    image = Image.open(io.BytesIO(content))
    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    w, h = image.size
    if max(w, h) < 1800:
        scale = 1800 / max(w, h)
        image = image.resize((int(w * scale), int(h * scale)))

    variants: list[Image.Image] = []
    gray = ImageOps.grayscale(image)
    gray = ImageOps.autocontrast(gray)
    variants.append(gray.filter(ImageFilter.SHARPEN))
    variants.append(ImageEnhance.Contrast(gray).enhance(1.8).filter(ImageFilter.SHARPEN))
    # Binary-ish threshold for faded ink
    variants.append(gray.point(lambda x: 255 if x > 160 else 0))

    engine = "none"
    text = ""
    try:
        import pytesseract

        configs = [
            "--oem 3 --psm 6",   # assume uniform block of text
            "--oem 3 --psm 4",   # single column
            "--oem 3 --psm 11",  # sparse text
        ]
        candidates: list[str] = []
        for img in variants:
            for cfg in configs:
                try:
                    t = pytesseract.image_to_string(img, config=cfg) or ""
                    if t.strip():
                        candidates.append(t.strip())
                except Exception:
                    continue
        if candidates:
            # Prefer the reading with most alphanumeric content / lines
            text = max(
                candidates,
                key=lambda t: (len(re.findall(r"[A-Za-z0-9]{2,}", t)), t.count("\n"), len(t)),
            )
            engine = f"tesseract/{len(candidates)}-passes"
        else:
            engine = "tesseract-empty"
    except Exception as exc:  # noqa: BLE001
        text = ""
        engine = f"unavailable:{exc.__class__.__name__}"

    return {
        "filename": filename,
        "engine": engine,
        "raw_text": text.strip(),
        "image_width": image.size[0],
        "image_height": image.size[1],
    }


_DATE_TOKEN_RE = re.compile(
    r"(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4}|\d{4}[\/\-\.]\d{1,2}[\/\-\.]\d{1,2})"
)
_DATE_LINE_RE = re.compile(
    r"^(?:date|dated|petsa|or|invoice)?\s*[:\-]?\s*"
    r"(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4}|\d{4}[\/\-\.]\d{1,2}[\/\-\.]\d{1,2})\s*$",
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
_INLINE_DATE_PREFIX = re.compile(
    r"^(?P<date>\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4})\s+[-:]?\s*(?P<rest>.+)$"
)


def _normalize_ocr(text: str) -> str:
    """Normalize common OCR confusions for matching."""
    t = text.lower().strip()
    t = t.replace("—", "-").replace("–", "-")
    # Don't blindly replace O→0 globally (destroys words); only in sku-like tokens later
    t = re.sub(r"\s+", " ", t)
    return t


def _sku_normalize(text: str) -> str:
    t = text.upper().strip()
    t = t.replace(" ", "").replace("_", "-")
    # Common OCR: O/0 I/1 S/5 B/8 in codes
    return t


def _parse_date_value(raw: str) -> Optional[str]:
    raw = raw.strip()
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


def _parse_date_from_text(text: str) -> Optional[str]:
    m = _DATE_TOKEN_RE.search(text)
    if not m:
        return None
    return _parse_date_value(m.group(1))


def _clean_label(label: str) -> str:
    label = re.sub(r"\s+", " ", label).strip(" -·•|\t")
    label = re.sub(r"^(item|product|desc|description)\s*[:\-]\s*", "", label, flags=re.I)
    # Strip trailing currency symbols / pesos markers
    label = re.sub(r"\s*[₱P]\s*$", "", label)
    return label.strip()


def parse_ocr_lines(raw_text: str) -> list[dict]:
    """Parse OCR text into candidate sales lines with **per-line dates**.

    Date headers update the current date for following item lines. Inline dates
    on a line override for that line only.
    """
    fallback_date = _parse_date_from_text(raw_text)
    current_date = fallback_date
    rows: list[dict] = []
    row_number = 1

    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line or len(line) < 2:
            continue
        lower = line.lower()
        if lower.startswith(("total", "subtotal", "grand", "cash", "change", "signature", "page", "amount due")):
            continue

        # Pure date header → update context for subsequent lines
        if _DATE_LINE_RE.match(line) or (_DATE_TOKEN_RE.fullmatch(line) and len(line) <= 14):
            parsed = _parse_date_from_text(line)
            if parsed:
                current_date = parsed
            continue
        if lower.startswith("date") and _DATE_TOKEN_RE.search(line) and len(line) < 40:
            parsed = _parse_date_from_text(line)
            if parsed:
                current_date = parsed
            # If the line is only a date header, skip; otherwise may continue as item
            if not re.search(r"[A-Za-z]{3,}", line.replace("date", "").replace("Date", "")):
                continue

        line_date = current_date
        # Inline date at start of item line
        im = _INLINE_DATE_PREFIX.match(line)
        if im:
            parsed = _parse_date_value(im.group("date"))
            if parsed:
                line_date = parsed
                current_date = parsed  # carry forward
                line = im.group("rest").strip()

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
                        label = _clean_label(m.group("label"))
                        qty = float(m.group("qty"))

        if not label or qty is None or qty <= 0:
            if len(line) >= 4 and not re.fullmatch(r"[\d\s.,/\-]+", line):
                rows.append({
                    "row_number": row_number,
                    "invoice_no": None,
                    "sale_date": line_date,
                    "sku": None,
                    "product_name": _clean_label(line),
                    "quantity": 1.0,
                    "unit_price": None,
                    "customer": None,
                    "ocr_text": raw_line.strip(),
                    "status": "needs_review",
                    "message": "Could not parse qty/price — review and select item",
                })
                row_number += 1
            continue

        if not sku:
            parts = label.split()
            if parts and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9\-_/]{2,}", parts[0]) and len(parts) > 1:
                sku = parts[0]
                label = " ".join(parts[1:])

        rows.append({
            "row_number": row_number,
            "invoice_no": None,
            "sale_date": line_date,
            "sku": sku,
            "product_name": label,
            "quantity": qty,
            "unit_price": price,
            "customer": None,
            "ocr_text": raw_line.strip(),
            "status": "parsed",
            "message": "Parsed from photo",
        })
        row_number += 1

    return rows


def _token_set(text: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", _normalize_ocr(text)) if len(t) > 1}


def _score_product(product: Product, query: str) -> float:
    q = _normalize_ocr(query)
    if not q:
        return 0.0
    sku = (product.sku or "").lower()
    name = (product.name or "").lower()
    brand = (product.brand or "").lower()
    fitment = (product.fitment or "").lower()
    hay = f"{sku} {name} {brand} {fitment}"
    sku_n = _sku_normalize(product.sku or "")
    q_sku = _sku_normalize(q)

    score = 0.0
    if sku == q or sku_n == q_sku:
        return 100.0
    if sku and (sku in q or q in sku):
        score = max(score, 92.0)
    if sku_n and len(sku_n) >= 3 and (sku_n in q_sku or q_sku in sku_n):
        score = max(score, 90.0)
    # Fuzzy SKU (OCR typos)
    if sku_n and len(sku_n) >= 3:
        ratio = SequenceMatcher(None, sku_n, q_sku).ratio()
        if ratio >= 0.75:
            score = max(score, 70.0 + ratio * 25.0)
    if name == q:
        score = max(score, 88.0)
    if q and name and q in name:
        score = max(score, 72.0 + min(18.0, len(q) / max(len(name), 1) * 18))
    name_ratio = SequenceMatcher(None, name, q).ratio() if name and q else 0.0
    if name_ratio >= 0.55:
        score = max(score, name_ratio * 85.0)

    q_tokens = _token_set(q)
    hay_tokens = _token_set(hay)
    if q_tokens:
        hits = 0.0
        for t in q_tokens:
            if t in hay_tokens:
                hits += 1.0
            else:
                # partial token fuzzy
                best = max((SequenceMatcher(None, t, ht).ratio() for ht in hay_tokens), default=0)
                if best >= 0.8:
                    hits += 0.7
        token_score = (hits / len(q_tokens)) * 75.0
        score = max(score, token_score)

    if brand and brand in q:
        score = max(score, score + 5)
    return min(score, 100.0)


def suggest_products(db: Session, query: str, limit: int = 12) -> list[dict]:
    products = db.query(Product).filter(Product.is_active.is_(True)).all()
    scored = []
    for p in products:
        score = _score_product(p, query)
        if score >= 20:
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


def _match_sku_in_text(products: list[Product], text: str) -> Optional[Product]:
    """Find inventory SKU mentioned inside free OCR text."""
    if not text:
        return None
    hay = _sku_normalize(text)
    # Longest SKU first to avoid short false hits
    ranked = sorted(products, key=lambda p: len(p.sku or ""), reverse=True)
    for p in ranked:
        sku_n = _sku_normalize(p.sku or "")
        if len(sku_n) < 3:
            continue
        if sku_n in hay:
            return p
        # Fuzzy window: any contiguous chunk similar to SKU
        for m in re.finditer(r"[A-Z0-9\-/]{3,}", hay):
            chunk = m.group(0)
            if SequenceMatcher(None, sku_n, chunk).ratio() >= 0.86:
                return p
    return None


def match_ocr_rows(db: Session, rows: list[dict], mode: str = "sale") -> list[dict]:
    products = db.query(Product).filter(Product.is_active.is_(True)).all()
    enriched = []
    for row in rows:
        sku = row.get("sku")
        name = row.get("product_name")
        ocr_text = row.get("ocr_text") or ""
        qty = float(row.get("quantity") or 0)
        query = f"{sku or ''} {name or ''} {ocr_text}".strip()

        product = find_product(db, sku, name)
        if not product:
            product = _match_sku_in_text(products, query)

        suggestions = suggest_products(db, query, limit=12) if query else []
        if not product and suggestions:
            top = suggestions[0]
            # Auto-accept stronger inventory matches (incl. fuzzy OCR)
            if top["score"] >= 58:
                product = next((p for p in products if p.id == top["id"]), None)

        # Always attach suggestions (include matched product at top)
        if product:
            suggestions = [
                {
                    "id": product.id,
                    "sku": product.sku,
                    "name": product.name,
                    "sell_price": product.sell_price,
                    "cost_price": product.cost_price,
                    "stock_qty": product.stock_qty,
                    "score": 100.0,
                },
                *[s for s in suggestions if s["id"] != product.id],
            ][:12]

        entry = {
            **row,
            "matched_product_id": product.id if product else None,
            "matched_product_name": product.name if product else None,
            "current_stock": product.stock_qty if product else None,
            "suggestions": suggestions,
        }
        if product:
            default_price = product.cost_price if mode == "purchase" else product.sell_price
            if entry.get("unit_price") in (None, 0, 0.0):
                entry["unit_price"] = default_price
            entry["status"] = "matched"
            verb = "purchase receive" if mode == "purchase" else "sale import"
            entry["message"] = f"Matched {product.sku} — review before {verb}"
        else:
            entry["status"] = "unmatched"
            entry["message"] = (
                f"Top suggestion: {suggestions[0]['sku']}" if suggestions else "Select inventory item (use search)"
            )
        enriched.append(entry)

    next_no = (enriched[-1]["row_number"] + 1) if enriched else 1
    # Carry last known date into blank helper rows
    last_date = None
    for r in reversed(enriched):
        if r.get("sale_date"):
            last_date = r["sale_date"]
            break
    for i in range(3):
        enriched.append({
            "row_number": next_no + i,
            "invoice_no": None,
            "sale_date": last_date,
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
            "message": "Optional blank line — search & pick an item",
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
    dates = sorted({r.get("sale_date") for r in rows if r.get("sale_date")})
    kind = "purchase receive" if mode == "purchase" else "sales import"
    date_note = f" Dates found: {', '.join(dates)}." if dates else ""
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
            f"Review OCR rows (each line keeps its own date), select inventory items, then confirm {kind}.{date_note}"
            if ocr["raw_text"]
            else f"OCR could not read the photo clearly. Enter lines manually for {kind}."
        ),
    }
