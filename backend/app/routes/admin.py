import logging
import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from google.cloud import storage

from ..auth import require_admin
from ..cache import cache
from ..config import settings
from ..firestore import get_db
from ..models import PageContent, Recipe, RecipeCreate, RecipeUpdate, ReceiptDeleteBody
from ..services import recipes as recipe_service
from ..services import uploads

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", dependencies=[Depends(require_admin)])


@router.get("/recipes", response_model=list[Recipe])
async def admin_list_recipes():
    db = get_db()
    docs = db.collection("recipes").order_by("created_at", direction="DESCENDING").stream()
    return [recipe_service.doc_to_recipe(doc) for doc in docs]


@router.post("/recipes", response_model=Recipe, status_code=201)
async def admin_create_recipe(body: RecipeCreate):
    db = get_db()
    try:
        return recipe_service.create_recipe(db, body, source="admin")
    except recipe_service.InvalidCategories as exc:
        raise HTTPException(status_code=422, detail=f"Unknown categories: {exc.invalid}")
    except recipe_service.SlugConflict as exc:
        raise HTTPException(
            status_code=409,
            detail=(
                f"A recipe with this title already exists "
                f"(slug '{exc.existing['slug']}', id '{exc.existing['id']}')"
            ),
        )


@router.put("/recipes/{recipe_id}", response_model=Recipe)
async def admin_update_recipe(recipe_id: str, body: RecipeUpdate):
    db = get_db()
    try:
        return recipe_service.update_recipe(db, recipe_id, body, source="admin")
    except recipe_service.InvalidCategories as exc:
        raise HTTPException(status_code=422, detail=f"Unknown categories: {exc.invalid}")
    except recipe_service.RecipeNotFound:
        raise HTTPException(status_code=404, detail="Recipe not found")


@router.delete("/recipes/{recipe_id}", status_code=204)
async def admin_delete_recipe(recipe_id: str):
    db = get_db()
    try:
        recipe_service.delete_recipe(db, recipe_id)
    except recipe_service.RecipeNotFound:
        raise HTTPException(status_code=404, detail="Recipe not found")


@router.post("/upload-image")
async def admin_upload_image(file: Annotated[UploadFile, File()]):
    """Uploads an image to GCS (production) or returns a mock URL (dev)."""
    # Bounded read: cap memory at the limit instead of buffering the whole upload
    contents = await file.read(uploads.MAX_UPLOAD_BYTES + 1)
    if len(contents) > uploads.MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 10MB)")

    # Sniff the real type — the declared content_type is client-controlled and
    # this bucket is world-readable, so the bytes are the only trustworthy input.
    try:
        content_type = uploads.verify_upload_type(contents, uploads.ALLOWED_IMAGE_TYPES)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    filename = f"{uuid.uuid4()}-{uploads.sanitize_filename(file.filename or '')}"

    if settings.is_dev or not settings.gcs_bucket_name:
        return {"url": f"https://placehold.co/800x400?text={filename}"}

    # Phone photos carry a GPS IFD. This bucket is world-readable, so uploading
    # one unmodified publishes the coordinates it was taken at. Lossless — only
    # the metadata segments go, the compressed image is untouched.
    try:
        contents = uploads.strip_image_metadata(contents, content_type)
    except uploads.MetadataStripError as exc:
        # Fail closed: better to reject an odd file than to publish its location.
        logger.warning("Rejected image that could not be stripped: %s", exc)
        raise HTTPException(status_code=400, detail="Image could not be processed")

    try:
        client = storage.Client()
        bucket = client.bucket(settings.gcs_bucket_name)
        blob = bucket.blob(filename)
        blob.cache_control = uploads.PUBLIC_IMAGE_CACHE_CONTROL
        blob.upload_from_string(contents, content_type=content_type)

        # Construct a reliable public URL
        url = f"https://storage.googleapis.com/{settings.gcs_bucket_name}/{filename}"
        return {"url": url}
    except Exception:
        logger.exception("Image upload to GCS failed")
        raise HTTPException(status_code=500, detail="Upload failed")


@router.post("/upload-receipt")
async def admin_upload_recipe_receipt(file: Annotated[UploadFile, File()]):
    """Upload a purchase receipt photo or PDF for a recipe."""
    # Bounded read: cap memory at the limit instead of buffering the whole upload
    contents = await file.read(uploads.MAX_UPLOAD_BYTES + 1)
    if len(contents) > uploads.MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 10MB)")

    try:
        content_type = uploads.verify_upload_type(contents, uploads.ALLOWED_RECEIPT_TYPES)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    filename = f"{uuid.uuid4()}-{uploads.sanitize_filename(file.filename or '')}"

    if settings.is_dev or not settings.gcs_receipts_bucket_name:
        return {"url": f"https://placehold.co/400x300?text=receipt-{filename}"}

    try:
        client = storage.Client()
        blob = client.bucket(settings.gcs_receipts_bucket_name).blob(filename)
        blob.upload_from_string(contents, content_type=content_type)
        url = f"https://storage.googleapis.com/{settings.gcs_receipts_bucket_name}/{filename}"
        return {"url": url}
    except Exception:
        logger.exception("Receipt upload to GCS failed")
        raise HTTPException(status_code=500, detail="Upload failed")


@router.delete("/recipes/{recipe_id}/receipts", status_code=204)
async def admin_delete_recipe_receipt(recipe_id: str, body: ReceiptDeleteBody):
    """Remove a single receipt URL from a recipe and delete its GCS blob."""
    url = body.url
    if not url:
        raise HTTPException(status_code=400, detail="url is required")

    db = get_db()
    doc_ref = db.collection("recipes").document(recipe_id)
    doc = doc_ref.get()

    if not doc.exists:
        raise HTTPException(status_code=404, detail="Recipe not found")

    current_urls: list[str] = doc.to_dict().get("receipt_urls", [])
    if url not in current_urls:
        raise HTTPException(status_code=404, detail="Receipt not found on this recipe")

    doc_ref.update({"receipt_urls": [u for u in current_urls if u != url]})

    uploads.delete_recipe_receipt_blob(url)

    cache.clear()


# ── Categories ────────────────────────────────────────────────────────────────

@router.get("/categories", response_model=list[str])
async def admin_get_categories():
    db = get_db()
    return recipe_service.get_categories(db)


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
