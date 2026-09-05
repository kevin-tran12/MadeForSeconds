"""Expense creation, with the receipt/recipe-linking helpers it needs."""

import logging
from datetime import datetime, timezone

from google.cloud.firestore import transactional

from ...firestore import get_db
from ...models_expense import EXPENSE_CATEGORIES, ExpenseItem, recalculate_project_amounts
from ...routes.expenses import _write_revision_in_transaction
from ...services import uploads
from ..wrapper import mcp_tool

logger = logging.getLogger(__name__)


def _resolve_recipe_slugs(slugs: list[str]) -> dict[str, tuple[str, str]]:
    """Query Firestore for recipes by slug, return {slug: (id, title)}."""
    if not slugs:
        return {}
    db = get_db()
    docs = db.collection("recipes").where("slug", "in", slugs[:30]).stream()
    result: dict[str, tuple[str, str]] = {}
    for doc in docs:
        data = doc.to_dict()
        result[data["slug"]] = (doc.id, data.get("title", data["slug"]))
    return result


def _mcp_create_expense_logic(transaction, db, doc_ref, data: dict) -> None:
    """Commits the expense document and its first revision atomically —
    reuses routes/expenses.py's _write_revision_in_transaction rather than a
    second, divergent implementation, which is how this exact class of bug
    (expense doc and revision as two independent writes) came back a second
    time here after being fixed for the HTTP route (see that module's own
    comment on this: "a second, divergent implementation is how this class
    of bug comes back," originally said about the receipt-URL validator)."""
    transaction.set(doc_ref, data)
    _write_revision_in_transaction(
        transaction, db, doc_ref.id, 1, {**data, "id": doc_ref.id}, "mcp", "Created via MCP"
    )


_mcp_create_expense_transaction = transactional(_mcp_create_expense_logic)


@mcp_tool(read_only=False, budget="write")
def create_expense(
    date: str,
    vendor: str,
    items: list[dict],
    raw_subtotal: int,
    raw_tax: int,
    raw_total: int,
    category: str = "ingredients",
    description: str = "",
    purpose: str = "",
    transaction_id: str = "",
    merchant_id: str = "",
    receipt_url: str = "",
    currency: str = "USD",
    idempotency_key: str | None = None,
) -> dict:
    """Create a new expense entry on MadeForSeconds for tax tracking.

    All monetary values are in CENTS (integers). For example, $79.87 = 7987.

    Args:
        date: ISO date string YYYY-MM-DD (e.g. "2026-03-08")
        vendor: Store or service name (e.g. "City Farmers Market")
        items: List of line items. Each dict has:
            - name (str): Item description
            - quantity (float): Number of units (default 1.0)
            - unit_price (int): Price per unit in cents
            - total_price (int): Total price in cents (quantity × unit_price)
            - project_related (bool): Whether this item is for the project (default true)
            - recipe_slug (str, optional): Slug of the linked recipe (e.g. "tom-yum-soup")
        raw_subtotal: Receipt subtotal before tax, in cents
        raw_tax: Tax amount in cents
        raw_total: Receipt grand total in cents
        category: One of: ingredients, equipment, hosting, marketing, software, other
        description: Optional notes about this expense
        purpose: What this expense is for when not tied to a recipe (e.g. "KitchenAid mixer")
        transaction_id: Receipt transaction/reference number (e.g. "Tran# 400318")
        merchant_id: Merchant terminal/store ID (e.g. "542929807243795")
        receipt_url: final_url from request_image_upload(kind="receipt") after
            PUTting the file (a gs:// URL)
        currency: Currency code (default "USD")
        idempotency_key: Optional, <=128 chars. Pass the same value on a
            retry after a timeout to get back the original call's result
            instead of logging a second expense (see server.py's
            INSTRUCTIONS retry note).
    """
    # Validate category
    if category not in EXPENSE_CATEGORIES:
        raise ValueError(f"Invalid category '{category}'. Must be one of: {', '.join(EXPENSE_CATEGORIES)}")

    # Resolve recipe slugs to IDs
    slugs = list({item["recipe_slug"] for item in items if item.get("recipe_slug")})
    slug_map = _resolve_recipe_slugs(slugs) if slugs else {}

    # Check for unresolved slugs
    unresolved = [s for s in slugs if s not in slug_map]
    if unresolved:
        raise ValueError(f"Recipe slugs not found: {', '.join(unresolved)}")

    # Build ExpenseItem list
    expense_items = []
    for item in items:
        recipe_id = None
        recipe_name = None
        slug = item.get("recipe_slug")
        if slug and slug in slug_map:
            recipe_id, recipe_name = slug_map[slug]

        expense_items.append(
            ExpenseItem(
                name=item["name"],
                quantity=item.get("quantity", 1.0),
                unit_price=item.get("unit_price", 0),
                total_price=item.get("total_price", 0),
                project_related=item.get("project_related", True),
                recipe_id=recipe_id,
                recipe_name=recipe_name,
            )
        )

    # Calculate project amounts
    project = recalculate_project_amounts(expense_items, raw_tax, raw_subtotal)

    # Validate the uploaded receipt if provided
    receipt_data: dict = {
        "receipt_url": None,
        "receipt_filename": None,
        "receipt_content_type": None,
    }
    if receipt_url:
        receipt_data = uploads.resolve_receipt_url(receipt_url)

    # Build Firestore document
    now = datetime.now(timezone.utc)
    parsed_date = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc)

    data = {
        "date": parsed_date,
        "vendor": vendor,
        "category": category,
        "description": description,
        "purpose": purpose or None,
        "transaction_id": transaction_id,
        "merchant_id": merchant_id,
        "items": [item.model_dump() for item in expense_items],
        "raw_subtotal": raw_subtotal,
        "raw_tax": raw_tax,
        "raw_total": raw_total,
        "currency": currency,
        **project,
        **receipt_data,
        "status": "active",
        "voided_at": None,
        "void_reason": None,
        "created_at": now,
        "updated_at": now,
        "revision": 1,
        "ai_parsed": True,
    }

    db = get_db()
    doc_ref = db.collection("expenses").document()

    # Document + first revision commit atomically — see
    # _mcp_create_expense_logic's own docstring for why this reuses
    # routes/expenses.py's transactional helper rather than a second,
    # independent implementation.
    _mcp_create_expense_transaction(db.transaction(), db, doc_ref, data)
    data["id"] = doc_ref.id

    logger.info("MCP create_expense: %s %s (%s)", vendor, date, doc_ref.id)

    # Build recipe summary for response
    linked_recipes = sorted({
        item.recipe_name for item in expense_items
        if item.recipe_name
    })

    return {
        "id": doc_ref.id,
        "vendor": vendor,
        "date": date,
        "category": category,
        "item_count": len(expense_items),
        "project_total": f"${project['project_total'] / 100:.2f}",
        "raw_total": f"${raw_total / 100:.2f}",
        "linked_recipes": linked_recipes,
        "receipt_uploaded": bool(receipt_data.get("receipt_url")),
        "message": "Expense created. Review at /admin/expenses.",
    }


TOOLS = (create_expense,)


def register(mcp) -> None:
    """Register this module's tools on the server. Explicit, so the tool
    surface is this tuple, nothing else. Each tool's annotations (set by the
    @mcp_tool(...) decorator in wrapper.py) ride along so the server exposes
    them to clients."""
    for tool in TOOLS:
        mcp.tool(annotations=getattr(tool, "mcp_annotations", None))(tool)
