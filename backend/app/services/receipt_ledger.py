"""Append-only record of what a receipt object was attached to.

A receipt in the receipts bucket outlives everything that names it. The bucket
enforces seven-year retention (terraform/modules/storage/buckets.tf), but the
recipe document listing it in ``receipt_urls`` is ordinary content — editable,
deletable, and not a financial record.

Receipts reached through the ``expenses`` ledger are fine: an expense is never
deleted, only voided, and every change writes an immutable snapshot into
``expense_revisions`` (routes/expenses.py::_write_revision). Receipts attached
directly to a *recipe* have none of that. The recipe document is the only live
record of what the object is, so detaching it left a file that survives for
seven years with nothing saying what it was — an anonymous scan rather than
evidence. Firestore backups covered the association for fourteen weeks and then
stopped, which is why the backup depth was carrying weight it should not have to.

This module writes the association down before the link goes away, so it
outlives both the recipe and any backup window.

Deliberately mirrors the ``expense_revisions`` contract: write-once, never
updated, never deleted, and written *before* the mutation it describes. Recipes
carry no amounts or tax categories — there is no financial classification to
capture here, and inventing one would be worse than recording none. What a
receipt cost belongs in ``expenses``; this answers the narrower question of
which recipe an orphaned object came from, and when it stopped belonging to it.
"""

import logging
from datetime import datetime, timezone

COLLECTION = "receipt_associations"

# Why a receipt stopped being attached to its recipe.
DETACH_UNLINKED = "unlinked"  # DELETE /api/admin/recipes/{id}/receipts
DETACH_RECIPE_DELETED = "recipe_deleted"  # the whole recipe went away
DETACH_REPLACED = "replaced_by_update"  # a recipe update dropped it from the list

logger = logging.getLogger(__name__)


def record_detachment(
    db,
    *,
    receipt_urls: list[str],
    recipe_id: str,
    recipe: dict,
    reason: str,
    source: str,
    actor: str | None = None,
) -> int:
    """Write one immutable association record per receipt URL. Returns the count.

    Call this **before** the write that removes the association, never after.
    The ordering is the whole safety property: if this raises, the caller
    aborts and the link is still intact, which is recoverable. A record written
    for a detachment that then failed is a harmless duplicate; a detachment with
    no record is the thing that cannot be undone.

    Batched so that a recipe holding several receipts records all of them or
    none — a partial write here would be indistinguishable from receipts that
    were never attached.
    """
    urls = [url for url in receipt_urls if url]
    if not urls:
        return 0

    detached_at = datetime.now(timezone.utc)
    batch = db.batch()

    for url in urls:
        batch.set(
            db.collection(COLLECTION).document(),
            {
                "receipt_url": url,
                "recipe_id": recipe_id,
                # Snapshotted, not referenced: the recipe is about to stop
                # existing, so a foreign key would point at nothing.
                "recipe_title": recipe.get("title", ""),
                "recipe_slug": recipe.get("slug", ""),
                "recipe_categories": recipe.get("categories", []),
                "recipe_created_at": recipe.get("created_at"),
                "recipe_created_via": recipe.get("created_via"),
                "reason": reason,
                "detached_at": detached_at,
                "detached_via": source,
                "detached_by": actor,
            },
        )

    batch.commit()
    logger.info(
        "Recorded %d receipt association(s) for recipe %s (%s)", len(urls), recipe_id, reason
    )
    return len(urls)


def removed_receipt_urls(old_data: dict, updates: dict) -> list[str]:
    """URLs present on the recipe but absent from an update's ``receipt_urls``.

    Only meaningful when the update actually carries the field — ``updates``
    comes from ``model_dump(exclude_unset=True)``, so an omitted key means "left
    alone" and must not be read as "cleared".
    """
    if "receipt_urls" not in updates:
        return []

    incoming = set(updates.get("receipt_urls") or [])
    return [url for url in (old_data.get("receipt_urls") or []) if url not in incoming]
