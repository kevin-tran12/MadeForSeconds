"""Recipe domain service — single home for create/update/publish/delete logic.

Used by the admin REST routes and the MCP server so slug generation,
category validation, timestamps, GCS cleanup, and cache invalidation
behave identically regardless of entry point. Routes translate the
domain exceptions to HTTPExceptions; MCP tools translate them to
structured error dicts.
"""

import re
from datetime import datetime, timezone

from google.cloud.firestore_v1.base_query import FieldFilter

from ..cache import cache
from ..models import Recipe, RecipeCreate, RecipeUpdate
from ..validation import get_invalid_categories
from . import uploads


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


def doc_to_recipe(doc) -> Recipe:
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
    return Recipe(**data)


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


def create_recipe(db, body: RecipeCreate, *, source: str) -> Recipe:
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
    return Recipe(**data)


def update_recipe(db, recipe_id: str, body: RecipeUpdate, *, source: str) -> Recipe:
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

    doc_ref.update(updates)

    # Delete the old image only once the new one is sanitized AND the
    # Firestore write has landed — otherwise a later failure could leave the
    # recipe with neither a valid old image nor a confirmed new one.
    if image_changed:
        uploads.delete_recipe_image_blob(old_image)

    updated = doc_ref.get().to_dict()
    updated["id"] = recipe_id
    cache.clear()
    return Recipe(**updated)


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


def delete_recipe(db, recipe_id: str, *, require_draft: bool = False) -> None:
    doc_ref, doc = _get_doc_or_raise(db, recipe_id)
    data = doc.to_dict()

    if require_draft and data.get("published"):
        raise RecipeServiceError("Refusing to delete a published recipe — unpublish it first")

    uploads.delete_recipe_image_blob(data.get("image_url"))
    for url in data.get("receipt_urls") or []:
        uploads.delete_recipe_receipt_blob(url)

    doc_ref.delete()
    cache.clear()
