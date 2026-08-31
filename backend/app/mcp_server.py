"""Remote MCP server for managing recipes and expenses from Claude conversations.

Claude clients (Claude Code, claude.ai Projects) connect via Streamable HTTP.
The full workflow happens without the admin web UI:

1. ``list_categories`` / ``list_recipes`` to discover existing content
2. ``create_recipe`` to save a draft (slug conflicts return a pointer to the
   existing recipe instead of writing a duplicate)
3. ``update_recipe`` to iterate on the draft
4. ``request_image_upload`` for a signed PUT URL (curl the file to GCS), or
   ``upload_image_from_url`` when the photo is already hosted somewhere —
   then attach via ``update_recipe(image_url=...)``
5. ``publish_recipe`` once complete

Expenses: upload the receipt with ``request_image_upload(kind="receipt")``,
PUT the file, then pass the returned ``final_url`` to ``create_expense``.
"""

import functools
import logging
from datetime import datetime, timezone
from urllib.parse import urlparse
from uuid import uuid4

from google.cloud.firestore import transactional
from google.cloud.firestore_v1.base_query import FieldFilter
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.server import Settings as FastMCPSettings
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import ValidationError

from .config import settings
from .mcp_auth import WorkOSTokenVerifier
from .firestore import get_db
from .models import RecipeCreate, RecipeUpdate
from .models_expense import (
    EXPENSE_CATEGORIES,
    ExpenseItem,
    recalculate_project_amounts,
)
from .routes.expenses import _write_revision_in_transaction
from .services import instagram
from .services import recipes as recipe_service
from .services import uploads

logger = logging.getLogger(__name__)

# pydantic-settings 2.15 detects FastMCP's generic lifespan annotation as an
# unresolved forward reference. Rebuild it before FastMCP constructs Settings
# so environment-backed settings remain fully resolved and warning-free. MCP
# 2.x removes this API entirely, so this can go with the planned 2.x migration.
FastMCPSettings.model_rebuild()

_INSTRUCTIONS = """Manage MadeForSeconds recipes and expenses.

Recipe workflow: list_categories → create_recipe (saved as draft) →
update_recipe to iterate → request_image_upload + update_recipe(image_url=...)
to attach a photo → publish_recipe. Use list_recipes/get_recipe to inspect
existing content before creating — duplicate titles are rejected with a
pointer to the existing recipe.

Note: the backend scales to zero; the first call after idle may take ~10s.
If a call times out, retry once before reporting an error."""

# OAuth: WorkOS AuthKit is the authorization server; this MCP server is the resource
# server. When auth is configured the SDK serves /.well-known/oauth-protected-resource,
# enforces tokens on /mcp, and emits a compliant WWW-Authenticate challenge on 401.
# Dev runs unauthenticated (no WorkOS dependency), matching the require_admin dev bypass.
if settings.is_dev:
    _auth = None
    _token_verifier = None
    # No DNS-rebinding host restriction locally — requests arrive as localhost:8000.
    _transport_security = TransportSecuritySettings(enable_dns_rebinding_protection=False)
else:
    _auth = AuthSettings(
        issuer_url=settings.workos_issuer_url,
        resource_server_url=settings.mcp_resource_url,
        # Blank (the default) keeps prior behaviour — no scope beyond a
        # valid, owned token (see mcp_auth.WorkOSTokenVerifier) is required.
        required_scopes=settings.mcp_required_scopes_list or None,
    )
    _token_verifier = WorkOSTokenVerifier()
    _resource_host = urlparse(settings.mcp_resource_url).netloc
    _transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[_resource_host, f"{_resource_host}:*", "localhost", "localhost:*"],
    )

mcp = FastMCP(
    "MadeForSeconds Recipe Creator",
    stateless_http=True,
    instructions=_INSTRUCTIONS,
    auth=_auth,
    token_verifier=_token_verifier,
    transport_security=_transport_security,
)


def _tool_errors(fn):
    """Translate domain/validation errors into structured dicts the LLM can act on."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ValidationError as exc:
            return {
                "error": "validation_error",
                "field_errors": [
                    {
                        "field": ".".join(str(p) for p in e["loc"]),
                        "message": e["msg"],
                        "type": e["type"],
                    }
                    for e in exc.errors()
                ],
            }
        except recipe_service.SlugConflict as exc:
            return {
                "error": "slug_conflict",
                "existing": exc.existing,
                "hint": (
                    "A recipe with this slug already exists (this is usually a retry). "
                    "Use update_recipe with the existing id, or change the title."
                ),
            }
        except recipe_service.InvalidCategories as exc:
            return {
                "error": "invalid_categories",
                "invalid": exc.invalid,
                "valid_categories": exc.allowed,
            }
        except recipe_service.RecipeNotFound as exc:
            return {"error": "not_found", "message": f"Recipe not found: {exc}"}
        except recipe_service.NotPublishable as exc:
            return {"error": "not_publishable", "problems": exc.problems}
        except recipe_service.RecipeServiceError as exc:
            return {"error": "invalid_request", "message": str(exc)}
        except instagram.InstagramError as exc:
            return {
                "error": "instagram_auth" if exc.auth else "instagram",
                "message": str(exc),
            }
        except ValueError as exc:
            return {"error": "invalid_request", "message": str(exc)}
        except Exception as exc:
            logger.exception("MCP tool %s failed", fn.__name__)
            return {"error": "internal", "message": str(exc)}

    return wrapper


def _iso(value) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else value


# ── Recipe tools ──────────────────────────────────────────────────────────────


@mcp.tool()
@_tool_errors
def list_recipes(published: bool | None = None, search: str = "", limit: int = 20) -> dict:
    """List recipes (drafts and published) as lightweight summaries.

    published: filter by state (True/False), or omit for all.
    search: case-insensitive substring match on the title.
    Returns {recipes: [{id, slug, title, published, updated_at, categories,
    labels, has_image}], count}.
    """
    db = get_db()
    limit = max(1, min(limit, 100))
    query = db.collection("recipes")
    if published is not None:
        query = query.where(filter=FieldFilter("published", "==", published))
    docs = (
        query.order_by("created_at", direction="DESCENDING")
        .limit(100 if search else limit)
        .select(["slug", "title", "published", "updated_at", "categories", "labels", "image_url"])
        .stream()
    )

    items = []
    needle = search.lower()
    for doc in docs:
        data = doc.to_dict() or {}
        if needle and needle not in data.get("title", "").lower():
            continue
        items.append({
            "id": doc.id,
            "slug": data.get("slug", ""),
            "title": data.get("title", ""),
            "published": data.get("published", False),
            "updated_at": _iso(data.get("updated_at")),
            "categories": data.get("categories", []),
            "labels": data.get("labels", []),
            "has_image": bool(data.get("image_url")),
        })
        if len(items) >= limit:
            break
    return {"recipes": items, "count": len(items)}


def _lookup_recipe(recipe_id: str = "", slug: str = ""):
    """Fetch a recipe document by id or slug (drafts included).

    Returns the parsed Recipe model. Raises RecipeNotFound / ValueError.
    """
    db = get_db()
    if recipe_id:
        doc = db.collection("recipes").document(recipe_id).get()
        if not doc.exists:
            raise recipe_service.RecipeNotFound(recipe_id)
    elif slug:
        docs = (
            db.collection("recipes")
            .where(filter=FieldFilter("slug", "==", slug))
            .limit(1)
            .stream()
        )
        doc = next(iter(docs), None)
        if doc is None:
            raise recipe_service.RecipeNotFound(slug)
    else:
        raise ValueError("Provide recipe_id or slug")
    return recipe_service.doc_to_recipe(doc)


@mcp.tool()
@_tool_errors
def get_recipe(recipe_id: str = "", slug: str = "") -> dict:
    """Fetch a full recipe by id or slug (drafts included)."""
    return _lookup_recipe(recipe_id, slug).model_dump(mode="json")


@mcp.tool()
@_tool_errors
def list_categories() -> dict:
    """List the admin-configured categories valid for create_recipe/update_recipe."""
    return {"categories": recipe_service.get_categories(get_db())}


@mcp.tool()
@_tool_errors
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
    labels: list[str] = [],
    nutrition: list[dict] = [],
    image_url: str | None = None,
    components: list[dict] | None = None,
    secrets: list[dict] = [],
) -> dict:
    """Create a new recipe draft on MadeForSeconds.

    The recipe is saved unpublished — finish it with update_recipe, attach a
    photo (request_image_upload), then publish_recipe.

    Each ingredient dict: item (str), amount (str), unit (str), optional group (str).
    Each instruction/prep_step dict: step (int), text (str), optional tip (str).
    Each nutrition dict: label (str), value (float), unit (str).
    Each secret dict: title (str), body (str).
    difficulty: easy | medium | hard.
    categories: must come from list_categories. labels are free-form tags.
    about is optional cultural/historical context, richer than description.
    image_url is optional — a publicly accessible URL to the recipe photo.

    For multi-component dishes (e.g. Hainanese Chicken Rice with separate rice,
    sauces): pass components as up to 5 dicts, each with title (str), optional
    description, ingredients, optional prep_steps, instructions, optional
    prep/cook_time_minutes, optional yield_description. With components, leave
    top-level ingredients/instructions empty.

    On slug conflict (usually a retry) this returns a pointer to the existing
    recipe instead of creating a duplicate.
    """
    body = RecipeCreate.model_validate({
        "title": title,
        "description": description,
        "about": about,
        "ingredients": ingredients,
        "prep_steps": prep_steps,
        "instructions": instructions,
        "prep_time_minutes": prep_time_minutes,
        "cook_time_minutes": cook_time_minutes,
        "servings": servings,
        "difficulty": difficulty,
        "categories": categories,
        "labels": labels,
        "nutrition": nutrition,
        "image_url": image_url,
        "published": False,
        "components": components[:5] if components else None,
        "secrets": secrets,
    })

    recipe = recipe_service.create_recipe(get_db(), body, source="mcp")
    logger.info("MCP create_recipe: %s (%s)", recipe.title, recipe.id)
    return {
        "id": recipe.id,
        "slug": recipe.slug,
        "title": recipe.title,
        "message": (
            "Recipe created as draft. Iterate with update_recipe, attach an image "
            "via request_image_upload, then publish_recipe."
        ),
    }


_CLEARABLE_FIELDS = {"about", "image_url", "components"}


@mcp.tool()
@_tool_errors
def update_recipe(
    recipe_id: str,
    title: str | None = None,
    description: str | None = None,
    about: str | None = None,
    ingredients: list[dict] | None = None,
    prep_steps: list[dict] | None = None,
    instructions: list[dict] | None = None,
    prep_time_minutes: int | None = None,
    cook_time_minutes: int | None = None,
    servings: int | None = None,
    difficulty: str | None = None,
    categories: list[str] | None = None,
    labels: list[str] | None = None,
    nutrition: list[dict] | None = None,
    image_url: str | None = None,
    components: list[dict] | None = None,
    secrets: list[dict] | None = None,
    clear_fields: list[str] = [],
) -> dict:
    """Update fields of an existing recipe (draft or published).

    Only the fields you pass are changed. List fields (ingredients,
    instructions, labels, ...) are replaced WHOLE — call get_recipe first and
    send back the complete modified list. The slug never changes, even when
    the title does. Published state cannot be set here — use
    publish_recipe/unpublish_recipe.

    To null an optional field (about, image_url, components), name it in
    clear_fields instead of passing null.
    """
    provided = {
        "title": title,
        "description": description,
        "about": about,
        "ingredients": ingredients,
        "prep_steps": prep_steps,
        "instructions": instructions,
        "prep_time_minutes": prep_time_minutes,
        "cook_time_minutes": cook_time_minutes,
        "servings": servings,
        "difficulty": difficulty,
        "categories": categories,
        "labels": labels,
        "nutrition": nutrition,
        "image_url": image_url,
        "components": components,
        "secrets": secrets,
    }
    updates = {k: v for k, v in provided.items() if v is not None}
    for field in clear_fields:
        if field not in _CLEARABLE_FIELDS:
            raise ValueError(f"clear_fields supports only: {sorted(_CLEARABLE_FIELDS)}")
        updates[field] = None
    if not updates:
        raise ValueError("No fields to update")

    body = RecipeUpdate.model_validate(updates)
    recipe = recipe_service.update_recipe(get_db(), recipe_id, body, source="mcp")
    logger.info("MCP update_recipe: %s (%s) field_count=%d", recipe.title, recipe.id, len(updates))
    return {
        "id": recipe.id,
        "slug": recipe.slug,
        "title": recipe.title,
        "published": recipe.published,
        "updated_fields": sorted(updates),
        "message": "Recipe updated.",
    }


@mcp.tool()
@_tool_errors
def publish_recipe(recipe_id: str) -> dict:
    """Publish a recipe so it appears on the public site.

    Fails if the recipe has no ingredients+instructions (or components).
    Soft gaps — missing image, description, or categories — are returned
    as warnings, not errors.
    """
    recipe, warnings = recipe_service.set_published(get_db(), recipe_id, True, source="mcp")
    logger.info("MCP publish_recipe: %s (%s)", recipe.title, recipe.id)
    return {
        "id": recipe.id,
        "slug": recipe.slug,
        "published": True,
        "public_url": f"{settings.frontend_url}/recipes/{recipe.slug}/",
        "warnings": warnings,
    }


@mcp.tool()
@_tool_errors
def unpublish_recipe(recipe_id: str) -> dict:
    """Take a published recipe off the public site (back to draft)."""
    recipe, _ = recipe_service.set_published(get_db(), recipe_id, False, source="mcp")
    logger.info("MCP unpublish_recipe: %s (%s)", recipe.title, recipe.id)
    return {"id": recipe.id, "slug": recipe.slug, "published": False}


@mcp.tool()
@_tool_errors
def delete_recipe(recipe_id: str, confirm_title: str) -> dict:
    """Delete a DRAFT recipe and its stored image.

    Any attached receipts are kept — they are expense records under seven-year
    retention, so deleting the recipe unlinks them rather than destroying them.

    Published recipes must be unpublished first. confirm_title must exactly
    match the recipe's title — fetch it with get_recipe if unsure.
    """
    db = get_db()
    doc = db.collection("recipes").document(recipe_id).get()
    if not doc.exists:
        raise recipe_service.RecipeNotFound(recipe_id)
    actual_title = (doc.to_dict() or {}).get("title", "")
    if confirm_title != actual_title:
        return {
            "error": "confirm_title_mismatch",
            "message": "confirm_title must exactly match the recipe title.",
            "expected_title": actual_title,
        }

    recipe_service.delete_recipe(db, recipe_id, source="mcp", require_draft=True)
    logger.info("MCP delete_recipe: %s (%s)", actual_title, recipe_id)
    return {"deleted": True, "id": recipe_id, "title": actual_title}


# ── Image / receipt ingestion ─────────────────────────────────────────────────


@mcp.tool()
@_tool_errors
def request_image_upload(filename: str, content_type: str, kind: str = "recipe_image") -> dict:
    """Get a short-lived signed PUT URL to upload a file directly to storage.

    kind="recipe_image" (JPEG/PNG/WebP; sanitized and made public once attached
    via update_recipe) or kind="receipt" (also HEIC/PDF → private receipts
    bucket).

    Upload the file bytes with an HTTP PUT to upload_url, sending exactly the
    required_headers (a ready-to-run curl_example is included). Then use
    final_url: pass it to update_recipe(image_url=...) for recipe images, or
    to create_expense(receipt_url=...) for receipts. Max 10MB; the URL
    expires in 15 minutes.
    """
    # recipe_image: the signed PUT targets the private staging bucket — the
    # backend has no visibility into these bytes until they're attached, so
    # they must never land directly in the public bucket. upload_bucket and
    # public_bucket deliberately stay separate variables here: final_url must
    # keep pointing at the public bucket (it's what gets saved as the
    # recipe's image_url and what sanitize_recipe_image matches against),
    # while the signed URL itself must point at staging. Collapsing these
    # into one variable would silently break both.
    if kind == "recipe_image":
        allowed = uploads.ALLOWED_IMAGE_TYPES
        upload_bucket = settings.gcs_staging_bucket_name
        public_bucket = settings.gcs_bucket_name
    elif kind == "receipt":
        allowed = uploads.ALLOWED_RECEIPT_TYPES
        upload_bucket = settings.gcs_receipts_bucket_name
        public_bucket = None
    else:
        raise ValueError("kind must be 'recipe_image' or 'receipt'")

    if content_type not in allowed:
        raise ValueError(
            f"Unsupported content type '{content_type}' for {kind}. Allowed: {', '.join(sorted(allowed))}"
        )

    safe_name = uploads.sanitize_filename(filename)
    if kind == "recipe_image":
        blob_name = f"{uuid4()}-{safe_name}"
        final_url = f"https://storage.googleapis.com/{public_bucket}/{blob_name}"
    else:
        blob_name = f"receipts/{uuid4()}-{safe_name}"
        final_url = f"gs://{upload_bucket}/{blob_name}"

    if settings.is_dev:
        dev_final = (
            f"https://placehold.co/800x400?text={blob_name}"
            if kind == "recipe_image"
            else f"dev://{blob_name}"
        )
        return {
            "upload_url": "dev://noop",
            "method": "PUT",
            "required_headers": {},
            "final_url": dev_final,
            "expires_in_seconds": 0,
            "note": "Dev mode: no real upload happens; use final_url directly.",
        }

    # recipe_image needs both buckets configured; receipt needs only one.
    # Reserved for is_dev above — a bucket missing in production must raise,
    # not silently fall back to the same dev-mode placeholder. That placeholder
    # is not a real upload URL; a caller saving it as a recipe's image_url or
    # an expense's receipt_url would be attaching fake data to real content.
    # config.validate_production_settings already refuses to start the
    # process in that state; this is the backstop in case that check ever has
    # a gap. Not a ValueError — this is a server misconfiguration, not bad
    # input, so it should surface through _tool_errors' generic
    # `except Exception` branch as {"error": "internal", ...} and get logged,
    # not read like something the caller could fix by retrying differently.
    if not upload_bucket or (kind == "recipe_image" and not public_bucket):
        raise uploads.StorageNotConfiguredError(
            f"backend storage is not fully configured for kind={kind!r}"
        )

    result = uploads.signed_put_url(upload_bucket, blob_name, content_type)
    header_flags = " ".join(f"-H '{k}: {v}'" for k, v in result["required_headers"].items())
    logger.info("MCP request_image_upload: kind=%s blob=%s", kind, blob_name)
    return {
        **result,
        "final_url": final_url,
        "curl_example": f"curl -X PUT {header_flags} --upload-file ./{safe_name} '{result['upload_url']}'",
    }


@mcp.tool()
@_tool_errors
def upload_image_from_url(source_url: str) -> dict:
    """Copy an image from a public https URL into the recipe images bucket.

    Use when the photo is already hosted somewhere (e.g. a shared link).
    JPEG/PNG/WebP only, max 10MB, redirects are not followed. Returns
    {image_url} ready for create_recipe/update_recipe.
    """
    image_url = uploads.fetch_image_to_gcs(source_url)
    logger.info("MCP upload_image_from_url: %s", image_url)
    return {"image_url": image_url}


# ── Instagram publishing ──────────────────────────────────────────────────────


def _hashtag(text: str) -> str:
    """Turn a category/label into a bare hashtag word (alnum, lowercase)."""
    return "".join(c for c in text.lower() if c.isalnum())


def _build_recipe_caption(recipe) -> str:
    """Compose a default caption from a recipe: title, blurb, link, hashtags."""
    link = f"{settings.frontend_url.rstrip('/')}/recipes/{recipe.slug}/"
    tags = ["madeforseconds"]
    for raw in [*recipe.categories, *recipe.labels]:
        tag = _hashtag(raw)
        if tag and tag not in tags:
            tags.append(tag)
        if len(tags) >= 8:
            break
    parts = [recipe.title]
    if recipe.description:
        parts.append(recipe.description)
    parts.append(f"Full recipe: {link}")
    parts.append(" ".join(f"#{t}" for t in tags))
    return "\n\n".join(parts)


@mcp.tool()
@_tool_errors
def publish_instagram_post(image_url: str, caption: str = "") -> dict:
    """Publish a single image to the linked Instagram account.

    image_url must be a public https JPEG (recipe images in the site's GCS
    bucket work directly). caption <= 2200 chars and <= 30 hashtags. Returns
    the new media id and permalink. Subject to Instagram's 25-posts/24h limit;
    PNG/WebP images may be rejected by Instagram — prefer JPEG.
    """
    result = instagram.publish_image(image_url, caption)
    logger.info("MCP publish_instagram_post: media=%s", result.get("id"))
    return {**result, "message": "Posted to Instagram."}


@mcp.tool()
@_tool_errors
def publish_recipe_to_instagram(
    slug: str = "", recipe_id: str = "", caption: str | None = None
) -> dict:
    """Publish a recipe's photo to Instagram, building a caption if omitted.

    Looks up the recipe by slug or id, requires it to have an image, and posts
    it. When caption is None a caption is built from the recipe's title,
    description, link, and hashtags. Pass an explicit caption to override.
    """
    recipe = _lookup_recipe(recipe_id=recipe_id, slug=slug)
    if not recipe.image_url:
        raise ValueError("recipe has no image; attach one first (request_image_upload)")
    text = caption if caption is not None else _build_recipe_caption(recipe)
    result = instagram.publish_image(recipe.image_url, text)
    logger.info("MCP publish_recipe_to_instagram: recipe=%s media=%s", recipe.slug, result.get("id"))
    return {**result, "slug": recipe.slug, "title": recipe.title, "message": "Posted to Instagram."}


# ── Expense helpers ───────────────────────────────────────────────────────────


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


@mcp.tool()
@_tool_errors
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


def create_mcp_app():
    """Create the ASGI app for mounting on FastAPI.

    Auth is handled by the SDK (OAuth resource server) when configured — see the
    FastMCP construction above. Returns (inner_app, mounted_app); both are the
    same Starlette app — the first exposes ``.router.lifespan_context`` for
    FastAPI's lifespan, the second is what gets mounted at ``/``.
    """
    app = mcp.streamable_http_app()
    return app, app
