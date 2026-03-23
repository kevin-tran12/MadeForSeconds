import re
import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from google.cloud import storage

from ..auth import require_admin
from ..cache import cache
from ..config import settings
from ..firestore import get_db
from ..models import PageContent, Recipe, RecipeCreate, RecipeUpdate

router = APIRouter(prefix="/api/admin", dependencies=[Depends(require_admin)])


def _doc_to_recipe(doc) -> Recipe:
    data = doc.to_dict()
    data["id"] = doc.id
    # Migrate legacy nutrition dict {label: value} → list[{label, value, unit}]
    if isinstance(data.get("nutrition"), dict):
        data["nutrition"] = [
            {"label": k, "value": v, "unit": ""} for k, v in data["nutrition"].items()
        ]
    return Recipe(**data)


def _generate_slug(title: str) -> str:
    return re.sub(r"(^-|-$)", "", re.sub(r"[^a-z0-9]+", "-", title.lower()))


def _validate_categories(db, categories: list[str]) -> None:
    """Raises 422 if any submitted category is not in the allowed list."""
    if not categories:
        return
    doc = db.collection("config").document("categories").get()
    if not doc.exists:
        return  # no list configured yet — allow anything
    allowed: set[str] = set(doc.to_dict().get("list", []))
    if not allowed:
        return
    invalid = [c for c in categories if c not in allowed]
    if invalid:
        raise HTTPException(status_code=422, detail=f"Unknown categories: {invalid}")


@router.get("/recipes", response_model=list[Recipe])
async def admin_list_recipes():
    db = get_db()
    docs = db.collection("recipes").order_by("created_at", direction="DESCENDING").stream()
    return [_doc_to_recipe(doc) for doc in docs]


@router.post("/recipes", response_model=Recipe, status_code=201)
async def admin_create_recipe(body: RecipeCreate):
    db = get_db()
    _validate_categories(db, body.categories)
    now = datetime.now(timezone.utc)
    data = body.model_dump()
    data["slug"] = _generate_slug(body.title)
    data["created_at"] = now
    data["updated_at"] = now

    doc_ref = db.collection("recipes").document()
    doc_ref.set(data)

    data["id"] = doc_ref.id
    cache.clear()
    return Recipe(**data)


@router.put("/recipes/{recipe_id}", response_model=Recipe)
async def admin_update_recipe(recipe_id: str, body: RecipeUpdate):
    db = get_db()
    if body.categories is not None:
        _validate_categories(db, body.categories)
    doc_ref = db.collection("recipes").document(recipe_id)
    doc = doc_ref.get()

    if not doc.exists:
        raise HTTPException(status_code=404, detail="Recipe not found")

    updates = body.model_dump(exclude_none=True)
    updates["updated_at"] = datetime.now(timezone.utc)
    doc_ref.update(updates)

    updated = doc_ref.get().to_dict()
    updated["id"] = recipe_id
    cache.clear()
    return Recipe(**updated)


@router.delete("/recipes/{recipe_id}", status_code=204)
async def admin_delete_recipe(recipe_id: str):
    db = get_db()
    doc_ref = db.collection("recipes").document(recipe_id)
    doc = doc_ref.get()

    if not doc.exists:
        raise HTTPException(status_code=404, detail="Recipe not found")

    doc_ref.delete()
    cache.clear()


@router.post("/upload-image")
async def admin_upload_image(file: Annotated[UploadFile, File()]):
    """Uploads an image to GCS (production) or returns a mock URL (dev)."""
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")

    filename = f"{uuid.uuid4()}-{file.filename}"

    if settings.is_dev or not settings.gcs_bucket_name:
        return {"url": f"https://placehold.co/800x400?text={filename}"}

    try:
        client = storage.Client()
        bucket = client.bucket(settings.gcs_bucket_name)
        blob = bucket.blob(filename)

        # Stream upload directly from the file object - bypasses memory
        blob.upload_from_file(file.file, content_type=file.content_type)

        # Construct a reliable public URL
        url = f"https://storage.googleapis.com/{settings.gcs_bucket_name}/{filename}"
        return {"url": url}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Upload failed: {exc}")


# ── Categories ────────────────────────────────────────────────────────────────

@router.get("/categories", response_model=list[str])
async def admin_get_categories():
    db = get_db()
    doc = db.collection("config").document("categories").get()
    return sorted(doc.to_dict().get("list", [])) if doc.exists else []


@router.put("/categories", response_model=list[str])
async def admin_update_categories(body: dict):
    new_list: list[str] = body.get("list", [])
    db = get_db()
    db.collection("config").document("categories").set({"list": new_list})
    cache.clear()
    return sorted(new_list)


# ── Page content ───────────────────────────────────────────────────────────────

@router.get("/pages/{page_id}")
async def admin_get_page(page_id: str):
    db = get_db()
    doc = db.collection("pages").document(page_id).get()
    return doc.to_dict() if doc.exists else {}


@router.put("/pages/{page_id}")
async def admin_update_page(page_id: str, body: PageContent):
    db = get_db()
    db.collection("pages").document(page_id).set(body.data)
    cache.clear()
    return body.data


# ── Supporter note moderation ─────────────────────────────────────────────────

@router.get("/supporters/pending")
async def list_pending_notes():
    """List all supporters with pending (unapproved) notes for admin review."""
    db = get_db()
    pending = []

    for collection in ("subscribers", "donations"):
        docs = db.collection(collection).stream()
        for doc in docs:
            data = doc.to_dict()
            if data.get("note_pending"):
                pending.append({
                    "id": doc.id,
                    "collection": collection,
                    "email": data.get("email", ""),
                    "display_name": data.get("display_name", ""),
                    "note_pending": data.get("note_pending"),
                    "note_pending_public": data.get("note_pending_public", False),
                })
    return pending


@router.post("/supporters/{collection}/{doc_id}/approve-note")
async def approve_note(collection: str, doc_id: str):
    """Approve a pending note — moves it to the live note field."""
    if collection not in ("subscribers", "donations"):
        raise HTTPException(status_code=400, detail="Invalid collection")

    db = get_db()
    doc_ref = db.collection(collection).document(doc_id)
    doc = doc_ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Supporter not found")

    data = doc.to_dict()
    note = data.get("note_pending")
    if not note:
        raise HTTPException(status_code=400, detail="No pending note")

    doc_ref.update({
        "note": note,
        "note_is_public": data.get("note_pending_public", False),
        "note_pending": None,
        "note_pending_public": None,
        "updated_at": datetime.now(timezone.utc),
    })
    return {"approved": True, "note": note}


@router.post("/supporters/{collection}/{doc_id}/reject-note")
async def reject_note(collection: str, doc_id: str):
    """Reject a pending note — clears it without publishing."""
    if collection not in ("subscribers", "donations"):
        raise HTTPException(status_code=400, detail="Invalid collection")

    db = get_db()
    doc_ref = db.collection(collection).document(doc_id)
    doc = doc_ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Supporter not found")

    doc_ref.update({
        "note_pending": None,
        "note_pending_public": None,
        "updated_at": datetime.now(timezone.utc),
    })
    return {"rejected": True}


@router.get("/supporters/all")
async def list_all_supporters():
    """List all supporters who have a display name set, for admin management."""
    db = get_db()
    results = []

    for collection in ("subscribers", "donations"):
        docs = db.collection(collection).stream()
        for doc in docs:
            data = doc.to_dict()
            if data.get("display_name"):
                results.append({
                    "id": doc.id,
                    "collection": collection,
                    "email": data.get("email", ""),
                    "display_name": data.get("display_name"),
                    "name_enabled": data.get("name_enabled", True),
                    "note": data.get("note"),
                    "note_is_public": data.get("note_is_public", False),
                    "note_enabled": data.get("note_enabled", True),
                    "note_pending": data.get("note_pending"),
                    "total_donated_cents": data.get("total_donated_cents", data.get("amount_cents", 0)),
                    "status": data.get("status", "one_time"),
                })

    results.sort(key=lambda r: r.get("total_donated_cents", 0), reverse=True)
    return results


@router.post("/supporters/{collection}/{doc_id}/toggle-note")
async def toggle_note(collection: str, doc_id: str):
    """Toggle visibility of a supporter's live note."""
    if collection not in ("subscribers", "donations"):
        raise HTTPException(status_code=400, detail="Invalid collection")

    db = get_db()
    doc_ref = db.collection(collection).document(doc_id)
    doc = doc_ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Supporter not found")

    current = doc.to_dict().get("note_enabled", True)
    doc_ref.update({
        "note_enabled": not current,
        "updated_at": datetime.now(timezone.utc),
    })
    return {"note_enabled": not current}


@router.post("/supporters/{collection}/{doc_id}/toggle-name")
async def toggle_name(collection: str, doc_id: str):
    """Toggle visibility of a supporter's display name (and note)."""
    if collection not in ("subscribers", "donations"):
        raise HTTPException(status_code=400, detail="Invalid collection")

    db = get_db()
    doc_ref = db.collection(collection).document(doc_id)
    doc = doc_ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Supporter not found")

    current = doc.to_dict().get("name_enabled", True)
    doc_ref.update({
        "name_enabled": not current,
        "updated_at": datetime.now(timezone.utc),
    })
    return {"name_enabled": not current}
