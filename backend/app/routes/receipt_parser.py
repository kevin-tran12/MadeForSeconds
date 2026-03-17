"""Parse a receipt image or PDF using local OCR (pytesseract + pdfplumber).

No external API calls — runs fully in-process.
- PDF with embedded text → pdfplumber extracts text directly
- Image (JPEG/PNG/WebP) → pytesseract OCRs via Tesseract binary
"""

import re
from datetime import datetime
from io import BytesIO
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from ..auth import require_admin

router = APIRouter(prefix="/api/admin/expenses", dependencies=[Depends(require_admin)])

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp", "application/pdf"}


# ── Text extraction ──────────────────────────────────────────────────────────


def _extract_text_from_pdf(data: bytes) -> str:
    import pdfplumber

    with pdfplumber.open(BytesIO(data)) as pdf:
        pages_text = []
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                pages_text.append(text)
        return "\n".join(pages_text)


def _extract_text_from_image(data: bytes, content_type: str) -> str:
    import pytesseract
    from PIL import Image

    image = Image.open(BytesIO(data))
    # Convert to RGB if needed (e.g. RGBA PNG)
    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    return pytesseract.image_to_string(image)


# ── Parsing helpers ──────────────────────────────────────────────────────────


def _extract_vendor(lines: list[str]) -> str:
    """First meaningful non-empty line is usually the store name."""
    for line in lines[:5]:
        cleaned = line.strip()
        # Skip lines that look like addresses or phone numbers
        if cleaned and not re.match(r"^[\d\s\-\(\)\+\.]+$", cleaned):
            return cleaned
    return ""


# Date patterns in order of specificity
_DATE_PATTERNS = [
    (r"\b(\d{4}[-/]\d{2}[-/]\d{2})\b", "%Y-%m-%d"),
    (r"\b(\d{2}[-/]\d{2}[-/]\d{4})\b", "%m/%d/%Y"),
    (r"\b(\d{2}[-/]\d{2}[-/]\d{2})\b", "%m/%d/%y"),
    (r"\b((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2}[,\s]+\d{4})\b", "%B %d, %Y"),
    (r"\b(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4})\b", "%d %B %Y"),
]


def _extract_date(text: str) -> str:
    """Scan for a date pattern and return ISO YYYY-MM-DD, or today as fallback."""
    for pattern, fmt in _DATE_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            raw = match.group(1).replace("/", "-")
            try:
                # Normalise separators for strptime
                raw_normalised = re.sub(r"[-/]", "/", match.group(1))
                fmt_normalised = fmt.replace("-", "/")
                parsed = datetime.strptime(raw_normalised, fmt_normalised)
                return parsed.strftime("%Y-%m-%d")
            except ValueError:
                continue
    return datetime.today().strftime("%Y-%m-%d")


def _dollars_to_cents(amount_str: str) -> int:
    """Convert a dollar string like '$4.99' or '4,99' to integer cents."""
    cleaned = re.sub(r"[^\d.]", "", amount_str.replace(",", "."))
    try:
        return round(float(cleaned) * 100)
    except ValueError:
        return 0


# Keywords that signal a subtotal/tax/total line rather than an item
_TOTAL_KEYWORDS = re.compile(
    r"\b(sub[\s-]?total|subtotal|hst|gst|pst|qst|tax|total|amount due|"
    r"balance|change|cash|visa|mastercard|debit|credit|savings?|discount|"
    r"coupon|reward|points|tip|gratuity)\b",
    re.IGNORECASE,
)

_PRICE_AT_END = re.compile(r"^(.+?)\s+\$?([\d,]+\.\d{2})\s*$")
_QTY_X_PRICE = re.compile(r"(\d+)\s*[x@]\s*\$?([\d,.]+)", re.IGNORECASE)


def _extract_items(lines: list[str]) -> list[dict]:
    """Extract line items — lines that end with a price but aren't totals/taxes."""
    items = []
    prev_line = ""
    for line in lines:
        line = line.strip()
        match = _PRICE_AT_END.match(line)
        if not match:
            prev_line = line
            continue

        description, price_str = match.group(1).strip(), match.group(2)

        # Skip lines that are clearly summary rows
        if _TOTAL_KEYWORDS.search(description):
            prev_line = line
            continue

        # Skip very short descriptions (likely noise)
        if len(description) < 2:
            prev_line = line
            continue

        total_cents = _dollars_to_cents(price_str)
        quantity = 1.0
        unit_price_cents = total_cents

        # Check for "2 @ $3.99" or "2 x 3.99" on this line or the previous line
        qty_match = _QTY_X_PRICE.search(line) or _QTY_X_PRICE.search(prev_line)
        if qty_match:
            quantity = float(qty_match.group(1))
            unit_price_cents = _dollars_to_cents(qty_match.group(2))
            total_cents = round(quantity * unit_price_cents)

        items.append(
            {
                "name": description,
                "quantity": quantity,
                "unit_price": unit_price_cents,
                "total_price": total_cents,
                "project_related": True,
            }
        )
        prev_line = line

    return items


_SUBTOTAL_KW = re.compile(r"\bsub[\s-]?total\b", re.IGNORECASE)
_TAX_KW = re.compile(r"\b(hst|gst|pst|qst|tax)\b", re.IGNORECASE)
_TOTAL_KW = re.compile(r"\b(total|amount due|balance)\b", re.IGNORECASE)
_PRICE = re.compile(r"\$?([\d,]+\.\d{2})")


def _extract_totals(lines: list[str]) -> dict[str, int]:
    """Find subtotal, tax, and total lines by keyword anchors."""
    subtotal = tax = total = 0
    for line in lines:
        prices = _PRICE.findall(line)
        if not prices:
            continue
        last_price = _dollars_to_cents(prices[-1])
        if _SUBTOTAL_KW.search(line):
            subtotal = last_price
        elif _TAX_KW.search(line):
            tax += last_price  # accumulate multiple tax lines (HST + PST etc.)
        elif _TOTAL_KW.search(line):
            # Only take the last "total" line encountered (grand total)
            total = last_price
    return {"subtotal": subtotal, "tax": tax, "total": total}


# ── Endpoint ─────────────────────────────────────────────────────────────────


@router.post("/parse-receipt")
async def parse_receipt(file: Annotated[UploadFile, File()]):
    """OCR a receipt image or extract text from a PDF, then parse into structured data."""
    if not file.content_type or file.content_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"File must be an image (JPEG/PNG/WebP) or PDF. Got: {file.content_type}",
        )

    data = await file.read()
    if len(data) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File too large (max 10MB)")

    try:
        if file.content_type == "application/pdf":
            raw_text = _extract_text_from_pdf(data)
        else:
            raw_text = _extract_text_from_image(data, file.content_type)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Could not read file: {exc}") from exc

    if not raw_text or not raw_text.strip():
        raise HTTPException(
            status_code=422,
            detail="No text could be extracted from the file. Try a clearer image.",
        )

    lines = [l for l in raw_text.splitlines() if l.strip()]

    vendor = _extract_vendor(lines)
    date = _extract_date(raw_text)
    items = _extract_items(lines)
    totals = _extract_totals(lines)

    # If no items parsed but we have a total, surface a single "unknown" item
    # so the user has something to work with
    if not items and totals["total"] > 0:
        items = [
            {
                "name": "Unknown item",
                "quantity": 1.0,
                "unit_price": totals["total"] - totals["tax"],
                "total_price": totals["total"] - totals["tax"],
                "project_related": True,
            }
        ]

    return {
        "vendor": vendor,
        "date": date,
        "items": items,
        "raw_subtotal": totals["subtotal"] or (totals["total"] - totals["tax"]),
        "raw_tax": totals["tax"],
        "raw_total": totals["total"],
        "currency": "CAD",
    }
