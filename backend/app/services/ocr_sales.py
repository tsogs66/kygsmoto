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

    Fast path: one downscaled grayscale pass. Avoids multi-pass hangs on
    large phone photos. Handwriting still needs review in the UI.
    """
    try:
        from PIL import Image, ImageOps, ImageFilter, ImageEnhance
    except ImportError as exc:
        raise RuntimeError("Pillow is required for photo OCR. Install pillow.") from exc

    try:
        image = Image.open(io.BytesIO(content))
        image.load()  # force decode now (fail fast on corrupt/HEIC without plugin)
    except Exception as exc:  # noqa: BLE001
        return {
            "filename": filename,
            "engine": f"image-open-failed:{exc.__class__.__name__}",
            "raw_text": "",
            "image_width": 0,
            "image_height": 0,
            "error": str(exc),
        }

    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")

    # Cap size — phone photos (12MP+) make Tesseract appear stuck
    max_side = 1600
    w, h = image.size
    longest = max(w, h)
    if longest > max_side:
        scale = max_side / longest
        image = image.resize((max(1, int(w * scale)), max(1, int(h * scale))))
    elif longest < 900:
        scale = 900 / longest
        image = image.resize((max(1, int(w * scale)), max(1, int(h * scale))))

    gray = ImageOps.grayscale(image)
    gray = ImageOps.autocontrast(gray)
    gray = ImageEnhance.Contrast(gray).enhance(1.5)
    gray = gray.filter(ImageFilter.SHARPEN)

    engine = "none"
    text = ""
    try:
        import pytesseract

        # Single fast pass (psm 6). Extra passes caused long "Working…" hangs.
        text = pytesseract.image_to_string(gray, config="--oem 3 --psm 6") or ""
        if not text.strip():
            # One fallback only if empty
            text = pytesseract.image_to_string(gray, config="--oem 3 --psm 4") or ""
            engine = "tesseract/psm4" if text.strip() else "tesseract-empty"
        else:
            engine = "tesseract/psm6"
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

# Quotation / Detailed Invoice Register (supplier printed purchase invoices)
_UOM_TOKEN = r"(?:PCS?|PC|RL|SET|SETS|PCK|PACK|BOX|UNIT|UN|EA|CTN|ROLL|LTR|LTRS?|KG|BTL|BOTTLE)"
_INVOICE_ITEM_RE = re.compile(
    rf"^(?P<code>[A-Za-z0-9][A-Za-z0-9\-_/]{{0,40}})\s+"
    rf"(?P<desc>.+?)\s+"
    rf"(?P<qty>\d+(?:\.\d+)?)\s+"
    rf"(?P<uom>{_UOM_TOKEN})\s+"
    rf"(?P<price>\d[\d,]*(?:\.\d+)?)\s+"
    rf"(?P<amount>\d[\d,]*(?:\.\d+)?)\s*$",
    re.I,
)
# OCR sometimes drops UOM: CODE DESC QTY PRICE AMOUNT
_INVOICE_ITEM_NO_UOM_RE = re.compile(
    r"^(?P<code>[A-Za-z0-9][A-Za-z0-9\-_/]{0,40})\s+"
    r"(?P<desc>.+?)\s+"
    r"(?P<qty>\d+(?:\.\d+)?)\s+"
    r"(?P<price>\d[\d,]*(?:\.\d+)?)\s+"
    r"(?P<amount>\d[\d,]*(?:\.\d+)?)\s*$",
)
_TRAN_NO_RE = re.compile(r"(?:tran(?:saction)?\s*no\.?|tran\s*#)\s*[:#]?\s*([0-9\-]+)", re.I)
_INV_NO_RE = re.compile(r"(?:inv(?:oice)?\s*no\.?|inv\s*#)\s*[:#]?\s*([0-9\-]+)", re.I)
_DATETIME_LINE_RE = re.compile(
    r"^(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4})\s+(\d{1,2}:\d{2}\s*(?:AM|PM)?)\s*$",
    re.I,
)
_SKIP_INVOICE_LINE_RE = re.compile(
    r"^(item\s*code|description|quantity|uom|price|amount|customer|address|"
    r"totals?|sub\s*totals?|grand\s*totals?|discount|page\s*\d|"
    r"quotation|detailed\s+invoice|invoice\s+register|"
    r"\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4}\s+to\s+)",
    re.I,
)


def _normalize_ocr(text: str) -> str:
    """Normalize common OCR confusions for matching."""
    t = text.lower().strip()
    t = t.replace("—", "-").replace("–", "-")
    # Don't blindly replace O→0 globally (destroys words); only in sku-like tokens later
    t = re.sub(r"\s+", " ", t)
    return t


def _sku_normalize(text: str) -> str:
    """Normalize SKU / supplier item codes for matching (strip noise, OCR confusions)."""
    t = text.upper().strip()
    t = t.replace(" ", "").replace("_", "-")
    # Common OCR confusions inside codes (apply after stripping spaces)
    # Keep hyphenated structure; map lookalikes only on alphanumeric runs
    out = []
    for ch in t:
        if ch == "O":
            out.append("0")  # O→0 often in numeric segments; reversible via compare both forms
        elif ch == "I" or ch == "L":
            out.append("1")
        elif ch == "S":
            out.append("5")
        elif ch == "B":
            out.append("8")
        else:
            out.append(ch)
    return "".join(out)


def _sku_key(text: str) -> str:
    """Loose key: uppercase, strip non-alnum (for RS8GEAROIL vs RS8-GEAR-OIL)."""
    return re.sub(r"[^A-Z0-9]", "", (text or "").upper())


def _sku_variants(text: str) -> set[str]:
    raw = (text or "").strip().upper()
    if not raw:
        return set()
    variants = {
        raw,
        raw.replace(" ", ""),
        raw.replace("_", "-"),
        raw.replace("-", ""),
        _sku_key(raw),
        _sku_normalize(raw),
        _sku_key(_sku_normalize(raw)),
    }
    # Also keep form without OCR confusion map
    plain = raw.replace(" ", "").replace("_", "-")
    variants.add(plain)
    variants.add(re.sub(r"[^A-Z0-9]", "", plain))
    return {v for v in variants if v}


def _money(raw: str) -> float:
    return float(str(raw).replace(",", "").strip())


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

        dt = pd.to_datetime(raw, dayfirst=False, errors="coerce")
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


def looks_like_invoice_register(raw_text: str) -> bool:
    """Detect Quotation / Detailed Invoice Register purchase documents."""
    if not raw_text:
        return False
    lower = raw_text.lower()
    signals = 0
    if "quotation" in lower or "invoice register" in lower or "detailed invoice" in lower:
        signals += 2
    if "item code" in lower and "description" in lower:
        signals += 2
    if re.search(r"\btran\s*no", lower) or re.search(r"\binv\s*no", lower):
        signals += 1
    if re.search(r"\buom\b", lower) and re.search(r"\bamount\b", lower):
        signals += 1
    # Many lines look like CODE … QTY UOM PRICE AMOUNT
    hits = sum(1 for line in raw_text.splitlines() if _INVOICE_ITEM_RE.match(line.strip()))
    if hits >= 2:
        signals += 2
    elif hits == 1:
        signals += 1
    return signals >= 2


def parse_invoice_register(raw_text: str) -> list[dict]:
    """Parse printed Quotation / Detailed Invoice Register purchase invoices.

    Columns: Item Code | Description | Quantity | UOM | Price | Amount
    Supports multiple Tran/Inv sections on one page (separate invoice_no + date).
    Unit cost = Price (not Amount).
    """
    fallback_date = _parse_date_from_text(raw_text)
    current_date = fallback_date
    current_invoice: Optional[str] = None
    rows: list[dict] = []
    row_number = 1

    for raw_line in raw_text.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line or len(line) < 3:
            continue

        # Transaction / invoice section headers
        tm = _TRAN_NO_RE.search(line)
        im = _INV_NO_RE.search(line)
        if tm or im:
            inv = None
            if im:
                inv = im.group(1).lstrip("0") or im.group(1)
                # Prefer readable inv no; keep last significant digits
                inv = im.group(1).strip()
            elif tm:
                inv = tm.group(1).strip()
            current_invoice = inv
            # Date may sit on same line
            parsed = _parse_date_from_text(line)
            if parsed:
                current_date = parsed
            continue

        dm = _DATETIME_LINE_RE.match(line)
        if dm:
            parsed = _parse_date_value(dm.group(1))
            if parsed:
                current_date = parsed
            continue

        if _SKIP_INVOICE_LINE_RE.match(line):
            # Range title may still hold a useful end date
            if re.search(r"\bto\b", line, re.I):
                dates = _DATE_TOKEN_RE.findall(line)
                if dates:
                    parsed = _parse_date_value(dates[-1])
                    if parsed and not current_date:
                        current_date = parsed
            continue

        lower = line.lower()
        if lower.startswith(("total", "subtotal", "grand", "discount", "cash", "change", "customer:", "address:")):
            continue

        # Pure date header
        if _DATE_LINE_RE.match(line) or (_DATE_TOKEN_RE.fullmatch(line) and len(line) <= 14):
            parsed = _parse_date_from_text(line)
            if parsed:
                current_date = parsed
            continue

        uom = None
        m = _INVOICE_ITEM_RE.match(line)
        if m:
            uom = m.group("uom").upper()
            if uom == "PC":
                uom = "PCS"
        else:
            m = _INVOICE_ITEM_NO_UOM_RE.match(line)
            if not m:
                continue
            # Guard: description must have letters (avoid numeric junk)
            if not re.search(r"[A-Za-z]{2,}", m.group("desc")):
                continue

        code = m.group("code").strip().upper()
        # Skip header leftovers mistaken as codes
        if code.lower() in {"item", "code", "qty", "uom", "price", "amount", "description"}:
            continue
        desc = _clean_label(m.group("desc"))
        qty = float(m.group("qty"))
        price = _money(m.group("price"))
        amount = _money(m.group("amount"))
        if qty <= 0 or price < 0:
            continue
        # If OCR swapped price/amount, prefer amount/qty when amount ≈ qty*price fails badly
        expected = round(qty * price, 2)
        if amount > 0 and price > 0 and abs(expected - amount) > max(1.0, amount * 0.15):
            # Maybe price was OCR'd as amount column only — derive unit from amount
            derived = round(amount / qty, 2)
            if derived > 0:
                price = derived

        rows.append({
            "row_number": row_number,
            "invoice_no": current_invoice,
            "sale_date": current_date,
            "sku": code,
            "product_name": desc,
            "quantity": qty,
            "unit_price": price,
            "uom": uom,
            "line_amount": amount,
            "customer": None,
            "ocr_text": raw_line.strip(),
            "status": "parsed",
            "message": f"Invoice item {code}" + (f" · Inv {current_invoice}" if current_invoice else ""),
        })
        row_number += 1

    return rows


def parse_ocr_lines(raw_text: str) -> list[dict]:
    """Parse OCR text into candidate sales/purchase lines with **per-line dates**.

    Prefer Quotation/Invoice Register table parsing when that layout is detected;
    otherwise use free-form handwritten heuristics.
    """
    if looks_like_invoice_register(raw_text):
        register_rows = parse_invoice_register(raw_text)
        if register_rows:
            return register_rows

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
        uom = None

        # Try invoice-style line even outside full-document detection
        inv_m = _INVOICE_ITEM_RE.match(line)
        if inv_m:
            sku = inv_m.group("code").strip().upper()
            label = _clean_label(inv_m.group("desc"))
            qty = float(inv_m.group("qty"))
            uom = inv_m.group("uom").upper()
            price = _money(inv_m.group("price"))
        else:
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
                    "uom": None,
                    "line_amount": None,
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
            "sku": sku.upper() if sku else None,
            "product_name": label,
            "quantity": qty,
            "unit_price": price,
            "uom": uom,
            "line_amount": round(qty * price, 2) if price is not None else None,
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
    prod_keys = _sku_variants(product.sku or "")
    query_keys = _sku_variants(q)

    score = 0.0
    # Exact / normalized item-code match (supplier invoice Item Code ↔ inventory SKU)
    if prod_keys & query_keys:
        return 100.0
    if sku == q or sku_n == q_sku:
        return 100.0
    # Query may be "1732 OIL HAVOLINE…" — score against first token as code
    first = (query.strip().split() or [""])[0]
    first_keys = _sku_variants(first)
    if first_keys and (prod_keys & first_keys):
        return 100.0
    if sku and (sku in q or q in sku):
        score = max(score, 92.0)
    if sku_n and len(sku_n) >= 3 and (sku_n in q_sku or q_sku in sku_n):
        score = max(score, 90.0)
    # Fuzzy SKU (OCR typos) — require enough length to avoid false hits on "78"
    if sku_n and len(sku_n) >= 4:
        ratio = SequenceMatcher(None, sku_n, q_sku).ratio()
        if ratio >= 0.75:
            score = max(score, 70.0 + ratio * 25.0)
        # Also fuzzy against first token only
        first_n = _sku_normalize(first)
        if first_n and len(first_n) >= 3:
            r2 = SequenceMatcher(None, sku_n, first_n).ratio()
            if r2 >= 0.86:
                score = max(score, 85.0 + r2 * 10.0)
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
    return _rank_products(products, query, limit=limit)


def _rank_products(products: list[Product], query: str, limit: int = 12) -> list[dict]:
    q = _normalize_ocr(query)
    if not q:
        return []
    # Cheap prefilter: require any token overlap / substring before fuzzy
    q_tokens = [t for t in _token_set(q) if len(t) >= 2]
    shortlist: list[Product] = []
    for p in products:
        hay = f"{p.sku} {p.name} {p.brand or ''}".lower()
        if any(t in hay for t in q_tokens) or (p.sku and p.sku.lower() in q) or (q[:4] in hay):
            shortlist.append(p)
        elif len(shortlist) < 80 and SequenceMatcher(None, (p.name or "").lower()[:40], q[:40]).ratio() > 0.4:
            shortlist.append(p)
    if not shortlist:
        shortlist = products[:200]  # fallback sample if tokens useless

    scored = []
    for p in shortlist:
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
    """Find inventory SKU / supplier item code mentioned inside OCR text."""
    if not text:
        return None
    hay = text.upper()
    hay_key = _sku_key(hay)
    hay_norm = _sku_normalize(hay)
    # Prefer longer codes first so M275X18MX2 beats 275
    ranked = sorted(
        (p for p in products if p.sku and len(p.sku) >= 2),
        key=lambda p: len(p.sku or ""),
        reverse=True,
    )
    # Exact / normalized code containment
    for p in ranked:
        variants = _sku_variants(p.sku or "")
        for v in variants:
            if len(v) < 2:
                continue
            # Short numeric codes (e.g. 78, 85) require token boundary
            if v.isdigit() and len(v) <= 3:
                if re.search(rf"(?<![A-Z0-9]){re.escape(v)}(?![A-Z0-9])", hay_key):
                    return p
                continue
            if v in hay_key or v in hay_norm or v in hay.replace(" ", ""):
                return p

    # Limited fuzzy only on OCR code-like tokens
    chunks = re.findall(r"[A-Z0-9\-/]{3,}", _sku_normalize(text))
    if not chunks:
        return None
    best: tuple[float, Optional[Product]] = (0.0, None)
    for p in ranked[:500]:
        sku_n = _sku_normalize(p.sku or "")
        if len(sku_n) < 3:
            continue
        for chunk in chunks:
            ratio = SequenceMatcher(None, sku_n, chunk).ratio()
            need = 0.92 if len(sku_n) <= 4 else 0.86
            if ratio > best[0] and ratio >= need:
                best = (ratio, p)
    return best[1] if best[0] else None


def match_ocr_rows(db: Session, rows: list[dict], mode: str = "sale") -> list[dict]:
    products = db.query(Product).filter(Product.is_active.is_(True)).all()
    by_id = {p.id: p for p in products}
    by_variant: dict[str, Product] = {}
    for p in products:
        for v in _sku_variants(p.sku or ""):
            if v and v not in by_variant:
                by_variant[v] = p

    enriched = []
    for row in rows:
        sku = row.get("sku")
        name = row.get("product_name")
        ocr_text = row.get("ocr_text") or ""
        qty = float(row.get("quantity") or 0)
        query = f"{sku or ''} {name or ''}".strip() or ocr_text

        product = None
        if sku:
            for v in _sku_variants(str(sku)):
                product = by_variant.get(v)
                if product:
                    break
        if not product:
            product = find_product(db, sku, name)
        if not product:
            product = _match_sku_in_text(products, f"{sku or ''} {ocr_text} {name or ''}")

        suggestions = _rank_products(products, query, limit=12) if query else []
        auto_threshold = 50 if sku else 58
        if not product and suggestions:
            top = suggestions[0]
            if top["score"] >= auto_threshold:
                product = by_id.get(top["id"])

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
            uom = entry.get("uom")
            uom_bit = f" · {uom}" if uom else ""
            entry["message"] = f"Matched {product.sku}{uom_bit} — review before {verb}"
        else:
            entry["status"] = "unmatched"
            code_bit = f"Item code {sku}" if sku else "No SKU"
            entry["message"] = (
                f"{code_bit} · top: {suggestions[0]['sku']}" if suggestions else f"{code_bit} — search inventory"
            )
        if entry.get("line_amount") in (None, 0, 0.0) and entry.get("unit_price") and qty:
            entry["line_amount"] = round(float(entry["unit_price"]) * qty, 2)
        enriched.append(entry)

    next_no = (enriched[-1]["row_number"] + 1) if enriched else 1
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
            "uom": None,
            "line_amount": None,
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


def preview_sales_photo(
    db: Session,
    filename: str,
    content: bytes,
    mode: str = "sale",
    ocr_result: Optional[dict] = None,
) -> dict:
    try:
        ocr = ocr_result if ocr_result is not None else extract_text_from_image(content, filename)
    except Exception as exc:  # noqa: BLE001 — never hang the UI on OCR crash
        ocr = {
            "filename": filename,
            "engine": f"error:{exc.__class__.__name__}",
            "raw_text": "",
            "error": str(exc),
        }

    raw = ocr.get("raw_text") or ""
    register = looks_like_invoice_register(raw)
    parsed = parse_ocr_lines(raw) if raw else []
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
                "uom": None,
                "line_amount": None,
                "customer": None,
                "ocr_text": None,
                "status": "blank",
                "message": "OCR found no lines — enter items manually from the photo",
            }
            for i in range(1, 6)
        ]
    try:
        rows = match_ocr_rows(db, parsed, mode=mode)
    except Exception as exc:  # noqa: BLE001
        rows = [
            {
                **r,
                "matched_product_id": None,
                "matched_product_name": None,
                "current_stock": None,
                "suggestions": [],
                "status": "unmatched",
                "message": f"Match skipped: {exc}",
            }
            for r in parsed
        ]

    matched = sum(1 for r in rows if r.get("status") == "matched")
    unmatched = sum(1 for r in rows if r.get("status") == "unmatched")
    total_qty = sum(float(r.get("quantity") or 0) for r in rows if r.get("status") == "matched")
    dates = sorted({r.get("sale_date") for r in rows if r.get("sale_date")})
    invoices = sorted({r.get("invoice_no") for r in rows if r.get("invoice_no")})
    kind = "purchase receive" if mode == "purchase" else "sales import"
    date_note = f" Dates found: {', '.join(dates)}." if dates else ""
    inv_note = f" Invoices: {', '.join(invoices)}." if invoices else ""
    err = ocr.get("error")
    if err:
        msg = f"Could not read image ({err}). Enter lines manually for {kind}."
    elif raw and register:
        msg = (
            f"Detected Quotation / Invoice Register — matched Item Codes to inventory. "
            f"Review qty, unit cost (Price), then confirm {kind}.{date_note}{inv_note}"
        )
    elif raw:
        msg = (
            f"Review OCR rows (each line keeps its own date), select inventory items, "
            f"then confirm {kind}.{date_note}{inv_note}"
        )
    else:
        msg = (
            f"OCR returned no text ({ocr.get('engine')}). "
            f"Enter lines manually for {kind}, or try a clearer / well-lit photo."
        )
    return {
        "filename": filename,
        "engine": ocr.get("engine") or "none",
        "raw_text": raw,
        "rows": rows,
        "matched_count": matched,
        "unmatched_count": unmatched,
        "total_qty": total_qty,
        "mode": mode,
        "document_type": "invoice_register" if register else "freeform",
        "message": msg,
    }
