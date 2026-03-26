"""Remote MCP server for creating recipes and expenses from Claude conversations.

Claude Projects on claude.ai connect to this via Streamable HTTP.
The user develops a recipe by chatting with Claude, then Claude
calls the create_recipe tool to save it as an unpublished draft.
For expenses, the user pastes a receipt image, Claude parses it
visually, and calls create_expense to record it with receipt upload.
"""

import mimetypes
import os
import re
from datetime import datetime, timezone
from uuid import uuid4

from mcp.server.fastmcp import FastMCP

from .config import settings
from .firestore import get_db
from .models import Ingredient, Instruction, NutritionEntry, RecipeComponent, RecipeCreate, RecipeSecret
from .validation import get_invalid_categories
from .models_expense import (
    EXPENSE_CATEGORIES,
    ExpenseItem,
    recalculate_project_amounts,
)


mcp = FastMCP(
    "MadeForSeconds Recipe Creator",
    stateless_http=True,
)


def _generate_slug(title: str) -> str:
    return re.sub(r"(^-|-$)", "", re.sub(r"[^a-z0-9]+", "-", title.lower()))


# ── Expense helpers ──────────────────────────────────────────────────────────


_ALLOWED_RECEIPT_TYPES = {"image/jpeg", "image/png", "image/webp", "application/pdf"}
_MAX_RECEIPT_SIZE = 10 * 1024 * 1024  # 10 MB


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


def _upload_receipt(file_path: str) -> dict:
    """Read a local file and upload to GCS (or return dev mock path).

    Returns dict with receipt_url, receipt_filename, receipt_content_type.
    """
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"Receipt file not found: {file_path}")

    filename = os.path.basename(file_path)
    content_type, _ = mimetypes.guess_type(file_path)
    if not content_type or content_type not in _ALLOWED_RECEIPT_TYPES:
        raise ValueError(
            f"Unsupported file type: {content_type}. "
            f"Allowed: {', '.join(sorted(_ALLOWED_RECEIPT_TYPES))}"
        )

    data = open(file_path, "rb").read()
    if len(data) > _MAX_RECEIPT_SIZE:
        raise ValueError(f"File too large ({len(data)} bytes). Max: {_MAX_RECEIPT_SIZE // 1024 // 1024}MB")

    blob_name = f"receipts/{uuid4()}-{filename}"

    if settings.is_dev:
        return {
            "receipt_url": f"dev://{blob_name}",
            "receipt_filename": filename,
            "receipt_content_type": content_type,
        }

    from google.cloud import storage

    client = storage.Client()
    bucket = client.bucket(settings.gcs_receipts_bucket_name)
    blob = bucket.blob(blob_name)
    blob.upload_from_string(data, content_type=content_type)

    return {
        "receipt_url": f"gs://{settings.gcs_receipts_bucket_name}/{blob_name}",
        "receipt_filename": filename,
        "receipt_content_type": content_type,
    }


def _write_revision(db, expense_id: str, revision: int, snapshot: dict, summary: str) -> None:
    """Write an immutable revision snapshot for audit trail."""
    db.collection("expense_revisions").document().set(
        {
            "expense_id": expense_id,
            "revision": revision,
            "snapshot": snapshot,
            "changed_by": "mcp",
            "changed_at": datetime.now(timezone.utc),
            "change_summary": summary,
        }
    )


# ── Tools ────────────────────────────────────────────────────────────────────


@mcp.tool()
def create_recipe(
    title: str,
    description: str = "",
    about: str | None = None,
    ingredients: list[dict] = [],
    prep_steps: list[dict] = [],
    instructions: list[dict] = [],
    prep_time_minutes: int = 0,
    cook_time_minutes: int = 0,
    servings: int = 1,
    difficulty: str = "easy",
    categories: list[str] = [],
    nutrition: list[dict] = [],
    image_url: str | None = None,
    components: list[dict] | None = None,
    secrets: list[dict] = [],
) -> dict:
    """Create a new recipe draft on MadeForSeconds.

    The recipe is saved as unpublished. Review and publish it from the admin dashboard.

    Each ingredient dict must have: item (str), amount (str), unit (str), and optionally group (str).
    Each instruction/prep_step dict must have: step (int), text (str), and optionally tip (str).
    Each nutrition dict must have: label (str), value (float), unit (str).
    Each secret dict must have: title (str), body (str).
    Difficulty must be one of: easy, medium, hard.
    about is optional — cultural/historical context, richer than the description.
    image_url is optional — a publicly accessible URL to the recipe photo.

    For multi-component dishes (e.g. Hainanese Chicken Rice with separate rice, sauces):
      Pass components as a list of up to 5 dicts, each with:
        title (str), description (str, optional),
        ingredients (list[dict]), prep_steps (list[dict], optional), instructions (list[dict]),
        prep_time_minutes (int, optional), cook_time_minutes (int, optional),
        yield_description (str, optional — e.g. "About ½ cup" for sauces).
      When components is provided, top-level ingredients/instructions should be empty.
    """
    # Build components if provided
    parsed_components = None
    if components:
        parsed_components = [
            RecipeComponent(
                title=c["title"],
                description=c.get("description"),
                ingredients=[Ingredient(**ing) for ing in c.get("ingredients", [])],
                prep_steps=[Instruction(**s) for s in c.get("prep_steps", [])],
                instructions=[Instruction(**inst) for inst in c.get("instructions", [])],
                prep_time_minutes=c.get("prep_time_minutes"),
                cook_time_minutes=c.get("cook_time_minutes"),
                yield_description=c.get("yield_description"),
            )
            for c in components[:5]  # cap at 5
        ]

    # Validate through Pydantic models
    recipe = RecipeCreate(
        title=title,
        description=description,
        about=about,
        ingredients=[Ingredient(**ing) for ing in ingredients],
        prep_steps=[Instruction(**s) for s in prep_steps],
        instructions=[Instruction(**inst) for inst in instructions],
        prep_time_minutes=prep_time_minutes,
        cook_time_minutes=cook_time_minutes,
        servings=servings,
        difficulty=difficulty,
        categories=categories,
        nutrition=[NutritionEntry(**n) for n in nutrition],
        image_url=image_url,
        published=False,
        components=parsed_components,
        secrets=[RecipeSecret(**s) for s in secrets],
    )

    db = get_db()

    # Validate categories against admin-configured allowed list
    invalid = get_invalid_categories(db, recipe.categories)
    if invalid:
        allowed_doc = db.collection("config").document("categories").get()
        allowed = sorted(allowed_doc.to_dict().get("list", [])) if allowed_doc.exists else []
        return {
            "error": f"Unknown categories: {invalid}. Allowed: {', '.join(allowed)}",
        }

    now = datetime.now(timezone.utc)
    data = recipe.model_dump()
    data["slug"] = _generate_slug(recipe.title)
    data["created_at"] = now
    data["updated_at"] = now

    doc_ref = db.collection("recipes").document()
    doc_ref.set(data)

    return {
        "id": doc_ref.id,
        "slug": data["slug"],
        "title": recipe.title,
        "message": "Recipe created as draft. Review and publish at /admin.",
    }


@mcp.tool()
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
    receipt_file_path: str = "",
    currency: str = "USD",
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
        receipt_file_path: Absolute path to receipt image/PDF on disk to upload
        currency: Currency code (default "USD")
    """
    # Validate category
    if category not in EXPENSE_CATEGORIES:
        return {"error": f"Invalid category '{category}'. Must be one of: {', '.join(EXPENSE_CATEGORIES)}"}

    # Resolve recipe slugs to IDs
    slugs = list({item["recipe_slug"] for item in items if item.get("recipe_slug")})
    slug_map = _resolve_recipe_slugs(slugs) if slugs else {}

    # Check for unresolved slugs
    unresolved = [s for s in slugs if s not in slug_map]
    if unresolved:
        return {"error": f"Recipe slugs not found: {', '.join(unresolved)}"}

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

    # Upload receipt if path provided
    receipt_data: dict = {
        "receipt_url": None,
        "receipt_filename": None,
        "receipt_content_type": None,
    }
    if receipt_file_path:
        try:
            receipt_data = _upload_receipt(receipt_file_path)
        except (FileNotFoundError, ValueError) as exc:
            return {"error": str(exc)}

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
    doc_ref.set(data)
    data["id"] = doc_ref.id

    # Write first revision
    _write_revision(db, doc_ref.id, 1, data, "Created via MCP")

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


class _BearerAuthMiddleware:
    """ASGI middleware that validates Authorization: Bearer <token> against MCP_API_KEY."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            # The MCP SDK validates that requests arrive on localhost and rejects
            # anything else (e.g. the Cloud Run service hostname or a Cloudflare
            # proxy host).  Rewriting the Host header here satisfies that check
            # without changing the actual network path.  If the SDK removes this
            # restriction in a future release, this rewrite can be dropped.
            server = scope.get("server") or ("localhost", 8000)
            host_value = f"localhost:{server[1]}".encode()
            headers = [
                (b"host", host_value) if k == b"host" else (k, v)
                for k, v in scope.get("headers", [])
            ]
            scope = {**scope, "headers": headers}

            if settings.mcp_api_key:
                auth = dict(headers).get(b"authorization", b"").decode()
                if auth != f"Bearer {settings.mcp_api_key}":
                    response = b'{"error": "Unauthorized"}'
                    await send({
                        "type": "http.response.start",
                        "status": 401,
                        "headers": [(b"content-type", b"application/json")],
                    })
                    await send({"type": "http.response.body", "body": response})
                    return
        await self.app(scope, receive, send)


def create_mcp_app():
    """Create the ASGI app for mounting on FastAPI.

    Returns (inner_app, wrapped_app) — inner_app exposes .lifespan for FastAPI,
    wrapped_app adds bearer token auth and is what gets mounted.
    """
    inner = mcp.streamable_http_app()
    return inner, _BearerAuthMiddleware(inner)
