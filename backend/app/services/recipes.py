"""Recipe domain service — single home for create/update/publish/delete logic.

Used by the admin REST routes and the MCP server so slug generation,
category validation, timestamps, GCS cleanup, and cache invalidation
behave identically regardless of entry point. Routes translate the
domain exceptions to HTTPExceptions; MCP tools translate them to
structured error dicts.
"""

import json
import re
from datetime import datetime, timezone

from google.cloud.firestore_v1.base_query import FieldFilter

from ..cache import cache
from ..models import AdminRecipe, Recipe, RecipeCreate, RecipeUpdate
from ..validation import get_invalid_categories
from . import receipt_ledger, uploads


class RecipeServiceError(Exception):
    """Base class for recipe domain errors."""


class RecipeNotFound(RecipeServiceError):
    pass


class SlugConflict(RecipeServiceError):
    def __init__(self, existing: dict):
        self.existing = existing
        super().__init__(f"A recipe with slug '{existing['slug']}' already exists")


class InvalidCategories(RecipeServiceError):
    def __init__(self, invalid: list[str], allowed: list[str]):
        self.invalid = invalid
        self.allowed = allowed
        super().__init__(f"Unknown categories: {invalid}")


class NotPublishable(RecipeServiceError):
    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("; ".join(problems))


def generate_slug(title: str) -> str:
    return re.sub(r"(^-|-$)", "", re.sub(r"[^a-z0-9]+", "-", title.lower()))


def _recipe_data(doc) -> dict:
    data = doc.to_dict()
    data["id"] = doc.id
    # Migrate legacy nutrition dict {label: value} → list[{label, value, unit}]
    if isinstance(data.get("nutrition"), dict):
        data["nutrition"] = [
            {"label": k, "value": v, "unit": ""} for k, v in data["nutrition"].items()
        ]
    # Strip any leftover premium_content from Firestore docs
    data.pop("premium_content", None)
    data.pop("has_premium_content", None)
    return data


def doc_to_recipe(doc) -> Recipe:
    """The public view: owner-only fields (sous_chef_notes) are dropped."""
    return Recipe(**_recipe_data(doc))


def doc_to_admin_recipe(doc) -> AdminRecipe:
    """The owner's view, for admin routes and MCP tools only."""
    return AdminRecipe(**_recipe_data(doc))


def find_by_slug(db, slug: str) -> dict | None:
    """Lightweight lookup; returns a serializable pointer dict or None."""
    docs = (
        db.collection("recipes")
        .where(filter=FieldFilter("slug", "==", slug))
        .limit(1)
        .stream()
    )
    doc = next(iter(docs), None)
    if doc is None:
        return None
    data = doc.to_dict() or {}
    updated = data.get("updated_at")
    return {
        "id": doc.id,
        "slug": data.get("slug", slug),
        "title": data.get("title", ""),
        "published": data.get("published", False),
        "updated_at": updated.isoformat() if hasattr(updated, "isoformat") else updated,
    }


def _published_by_slug_query(db, slug: str):
    return (
        db.collection("recipes")
        .where(filter=FieldFilter("slug", "==", slug))
        .where(filter=FieldFilter("published", "==", True))
        .limit(1)
        .stream()
    )


def get_published_by_slug(db, slug: str) -> Recipe | None:
    """Full published recipe by slug, or None — drafts are invisible here."""
    doc = next(iter(_published_by_slug_query(db, slug)), None)
    return doc_to_recipe(doc) if doc is not None else None


def _json_default(value):
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def get_published_doc(db, slug: str) -> dict | None:
    """Raw published recipe dict for the Sous Chef prompt.

    Keeps the admin-only fields the public ``Recipe`` model drops (the owner's
    ``sous_chef_notes``) and is JSON-safe (timestamps as ISO strings) so it can
    sit in the versioned cache, where every recipe mutation's cache.clear()
    invalidates it alongside the rendered responses.
    """
    key = f"assistant:recipe:{slug}"
    cached = cache.get(key)
    if cached is not None:
        return cached
    doc = next(iter(_published_by_slug_query(db, slug)), None)
    if doc is None:
        return None
    data = doc.to_dict() or {}
    data["id"] = doc.id
    data.pop("premium_content", None)
    data.pop("has_premium_content", None)
    safe = json.loads(json.dumps(data, default=_json_default))
    cache.set(key, safe)
    return safe


def get_all_published(db, limit: int = 200) -> list[Recipe]:
    """Newest-first published recipes — the same query main._warm_cache runs."""
    docs = (
        db.collection("recipes")
        .where(filter=FieldFilter("published", "==", True))
        .order_by("created_at", direction="DESCENDING")
        .limit(limit)
        .stream()
    )
    return [doc_to_recipe(doc) for doc in docs]


def get_categories(db) -> list[str]:
    doc = db.collection("config").document("categories").get()
    return sorted(doc.to_dict().get("list", [])) if doc.exists else []


def _validate_categories(db, categories: list[str]) -> None:
    invalid = get_invalid_categories(db, categories)
    if invalid:
        raise InvalidCategories(invalid, get_categories(db))


def _get_doc_or_raise(db, recipe_id: str):
    doc_ref = db.collection("recipes").document(recipe_id)
    doc = doc_ref.get()
    if not doc.exists:
        raise RecipeNotFound(recipe_id)
    return doc_ref, doc


def create_recipe(db, body: RecipeCreate, *, source: str) -> AdminRecipe:
    _validate_categories(db, body.categories)

    slug = generate_slug(body.title)
    existing = find_by_slug(db, slug)
    if existing is not None:
        raise SlugConflict(existing)

    now = datetime.now(timezone.utc)
    data = body.model_dump()
    data["slug"] = slug
    data["created_at"] = now
    data["updated_at"] = now
    data["created_via"] = source

    # Sanitize before committing anything. uploads.ImageSanitizationError
    # propagates to the caller as an attachment failure — a recipe must never
    # be saved pointing at an image we know we failed to strip.
    uploads.sanitize_recipe_image(data.get("image_url"))

    doc_ref = db.collection("recipes").document()
    doc_ref.set(data)
    data["id"] = doc_ref.id
    cache.clear()
    return AdminRecipe(**data)


def update_recipe(
    db, recipe_id: str, body: RecipeUpdate, *, source: str, actor: str | None = None
) -> AdminRecipe:
    if body.categories is not None:
        _validate_categories(db, body.categories)
    doc_ref, doc = _get_doc_or_raise(db, recipe_id)
    old_data = doc.to_dict()

    # exclude_unset distinguishes "field omitted" from "field set to null/empty"
    updates = body.model_dump(exclude_unset=True)
    updates["updated_at"] = datetime.now(timezone.utc)
    updates["updated_via"] = source

    image_changed = False
    old_image = ""
    if "image_url" in updates:
        old_image = old_data.get("image_url") or ""
        image_changed = old_image != (updates["image_url"] or "")
        if image_changed:
            # Sanitize the incoming image before anything is committed.
            # Attaching is the backend's first sight of an object uploaded
            # straight to GCS through a signed PUT URL (the MCP path) — the
            # only point where its metadata can still be stripped before the
            # image goes public. If this raises, the update aborts here:
            # Firestore is untouched and the old image is never deleted.
            uploads.sanitize_recipe_image(updates["image_url"])

    # An update carrying a shorter receipt_urls list detaches receipts just as
    # surely as the DELETE endpoint does, and nothing about the request says so.
    # Same ordering rule: record before the write that drops them.
    if removed := receipt_ledger.removed_receipt_urls(old_data, updates):
        receipt_ledger.record_detachment(
            db,
            receipt_urls=removed,
            recipe_id=recipe_id,
            recipe=old_data,
            reason=receipt_ledger.DETACH_REPLACED,
            source=source,
            actor=actor,
        )

    doc_ref.update(updates)

    # Delete the old image only once the new one is sanitized AND the
    # Firestore write has landed — otherwise a later failure could leave the
    # recipe with neither a valid old image nor a confirmed new one.
    if image_changed:
        uploads.delete_recipe_image_blob(old_image)

    updated = doc_ref.get().to_dict()
    updated["id"] = recipe_id
    cache.clear()
    return AdminRecipe(**updated)


def set_published(db, recipe_id: str, published: bool, *, source: str) -> tuple[Recipe, list[str]]:
    """Toggle published state. Publishing an incomplete recipe raises NotPublishable;
    soft gaps (no image/description/categories) are returned as warnings."""
    doc_ref, doc = _get_doc_or_raise(db, recipe_id)
    data = doc.to_dict()

    warnings: list[str] = []
    if published:
        has_flat = data.get("ingredients") and data.get("instructions")
        if not has_flat and not data.get("components"):
            raise NotPublishable(
                ["Recipe needs ingredients and instructions (or components) before publishing"]
            )
        if not data.get("image_url"):
            warnings.append("Recipe has no image")
        if not data.get("description"):
            warnings.append("Recipe has no description")
        if not data.get("categories"):
            warnings.append("Recipe has no categories")

    doc_ref.update({
        "published": published,
        "updated_at": datetime.now(timezone.utc),
        "updated_via": source,
    })
    updated = doc_ref.get().to_dict()
    updated["id"] = recipe_id
    cache.clear()
    return Recipe(**updated), warnings


def delete_recipe(
    db, recipe_id: str, *, source: str, require_draft: bool = False, actor: str | None = None
) -> None:
    doc_ref, doc = _get_doc_or_raise(db, recipe_id)
    data = doc.to_dict()

    if require_draft and data.get("published"):
        raise RecipeServiceError("Refusing to delete a published recipe — unpublish it first")

    # Record what the receipts belonged to before the only thing that says so
    # disappears. Deliberately before delete_recipe_image_blob and the Firestore
    # delete: if this raises, nothing has been destroyed yet.
    receipt_ledger.record_detachment(
        db,
        receipt_urls=data.get("receipt_urls") or [],
        recipe_id=recipe_id,
        recipe=data,
        reason=receipt_ledger.DETACH_RECIPE_DELETED,
        source=source,
        actor=actor,
    )

    uploads.delete_recipe_image_blob(data.get("image_url"))

    # Receipt objects are deliberately left in place. A recipe is content and
    # can be thrown away; the receipts attached to it are expense records that
    # have to survive the recipe by years. The receipts bucket enforces that
    # itself with a seven-year retention policy, so deleting them here would
    # fail regardless — and the association record written above outlives both
    # the recipe and any backup window.
    doc_ref.delete()
    cache.clear()
