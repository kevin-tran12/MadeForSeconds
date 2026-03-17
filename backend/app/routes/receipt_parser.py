"""Parse a receipt image or PDF using Claude Vision to extract line items."""

import base64
import os

import anthropic
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from typing import Annotated

from ..auth import require_admin

router = APIRouter(prefix="/api/admin/expenses", dependencies=[Depends(require_admin)])

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp", "application/pdf"}

EXTRACT_RECEIPT_TOOL = {
    "name": "extract_receipt",
    "description": "Extract structured data from a receipt image or PDF.",
    "input_schema": {
        "type": "object",
        "properties": {
            "vendor": {
                "type": "string",
                "description": "Store or vendor name as printed on the receipt",
            },
            "date": {
                "type": "string",
                "description": "Purchase date in ISO format YYYY-MM-DD. If unclear, use today.",
            },
            "items": {
                "type": "array",
                "description": "All line items on the receipt, including non-food items",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Item description as shown on receipt",
                        },
                        "quantity": {
                            "type": "number",
                            "description": "Quantity purchased (default 1 if not shown)",
                        },
                        "unit_price_cents": {
                            "type": "integer",
                            "description": "Unit price in cents (e.g. $4.99 → 499)",
                        },
                        "total_price_cents": {
                            "type": "integer",
                            "description": "Line total in cents (quantity × unit price)",
                        },
                    },
                    "required": ["name", "quantity", "unit_price_cents", "total_price_cents"],
                },
            },
            "subtotal_cents": {
                "type": "integer",
                "description": "Subtotal before tax in cents",
            },
            "tax_cents": {
                "type": "integer",
                "description": "Total tax amount in cents",
            },
            "total_cents": {
                "type": "integer",
                "description": "Grand total including tax in cents",
            },
            "currency": {
                "type": "string",
                "description": "Currency code e.g. CAD, USD",
            },
        },
        "required": ["vendor", "date", "items", "subtotal_cents", "tax_cents", "total_cents"],
    },
}


@router.post("/parse-receipt")
async def parse_receipt(file: Annotated[UploadFile, File()]):
    """Upload a receipt image or PDF and extract structured line items using Claude Vision."""
    if not file.content_type or file.content_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"File must be an image (JPEG/PNG/WebP) or PDF. Got: {file.content_type}",
        )

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="ANTHROPIC_API_KEY is not configured.")

    data = await file.read()
    if len(data) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File too large (max 10MB)")

    b64 = base64.standard_b64encode(data).decode()
    client = anthropic.Anthropic(api_key=api_key)

    # Build message content based on file type
    if file.content_type == "application/pdf":
        content = [
            {
                "type": "document",
                "source": {"type": "base64", "media_type": "application/pdf", "data": b64},
            },
            {
                "type": "text",
                "text": (
                    "Extract all line items from this receipt and call extract_receipt with the data. "
                    "Include ALL items shown, even non-food items. "
                    "Convert all prices to integer cents (e.g. $4.99 → 499). "
                    "If a price is unclear, make your best estimate."
                ),
            },
        ]
    else:
        content = [
            {
                "type": "image",
                "source": {"type": "base64", "media_type": file.content_type, "data": b64},
            },
            {
                "type": "text",
                "text": (
                    "Extract all line items from this receipt image and call extract_receipt with the data. "
                    "Include ALL items shown, even non-food items. "
                    "Convert all prices to integer cents (e.g. $4.99 → 499). "
                    "If a price is unclear from the image, make your best estimate."
                ),
            },
        ]

    try:
        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=2048,
            tools=[EXTRACT_RECEIPT_TOOL],
            tool_choice={"type": "tool", "name": "extract_receipt"},
            messages=[{"role": "user", "content": content}],
        )
    except anthropic.APIError as exc:
        raise HTTPException(status_code=502, detail=f"Claude API error: {exc}") from exc

    tool_use = next((b for b in response.content if b.type == "tool_use"), None)
    if not tool_use:
        raise HTTPException(status_code=502, detail="Claude did not return structured receipt data.")

    result = tool_use.input

    # Normalise item field names to match the expense model
    items = []
    for item in result.get("items", []):
        items.append(
            {
                "name": item.get("name", ""),
                "quantity": item.get("quantity", 1),
                "unit_price": item.get("unit_price_cents", 0),
                "total_price": item.get("total_price_cents", 0),
                "project_related": True,  # default — user unchecks non-project items
            }
        )

    return {
        "vendor": result.get("vendor", ""),
        "date": result.get("date", ""),
        "items": items,
        "raw_subtotal": result.get("subtotal_cents", 0),
        "raw_tax": result.get("tax_cents", 0),
        "raw_total": result.get("total_cents", 0),
        "currency": result.get("currency", "CAD"),
    }
