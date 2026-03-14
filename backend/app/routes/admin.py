import re
import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from google.cloud import storage

from ..auth import require_admin
from ..config import settings
from ..firestore import get_db
from ..models import Recipe, RecipeCreate, RecipeUpdate

router = APIRouter(prefix="/api/admin", dependencies=[Depends(require_admin)])


def _doc_to_recipe(doc) -> Recipe:
    data = doc.to_dict()
    data["id"] = doc.id
    return Recipe(**data)


def _generate_slug(title: str) -> str:
    return re.sub(r"(^-|-$)", "", re.sub(r"[^a-z0-9]+", "-", title.lower()))


@router.get("/recipes", response_model=list[Recipe])
async def admin_list_recipes():
    db = get_db()
    docs = db.collection("recipes").order_by("created_at", direction="DESCENDING").stream()
    return [_doc_to_recipe(doc) for doc in docs]


@router.post("/recipes", response_model=Recipe, status_code=201)
async def admin_create_recipe(body: RecipeCreate):
    db = get_db()
    now = datetime.now(timezone.utc)
    data = body.model_dump()
    data["slug"] = _generate_slug(body.title)
    data["created_at"] = now
    data["updated_at"] = now

    doc_ref = db.collection("recipes").document()
    doc_ref.set(data)

    data["id"] = doc_ref.id
    return Recipe(**data)


@router.put("/recipes/{recipe_id}", response_model=Recipe)
async def admin_update_recipe(recipe_id: str, body: RecipeUpdate):
    db = get_db()
    doc_ref = db.collection("recipes").document(recipe_id)
    doc = doc_ref.get()

    if not doc.exists:
        raise HTTPException(status_code=404, detail="Recipe not found")

    updates = body.model_dump(exclude_none=True)
    updates["updated_at"] = datetime.now(timezone.utc)
    doc_ref.update(updates)

    updated = doc_ref.get().to_dict()
    updated["id"] = recipe_id
    return Recipe(**updated)


@router.delete("/recipes/{recipe_id}", status_code=204)
async def admin_delete_recipe(recipe_id: str):
    db = get_db()
    doc_ref = db.collection("recipes").document(recipe_id)
    doc = doc_ref.get()

    if not doc.exists:
        raise HTTPException(status_code=404, detail="Recipe not found")

    doc_ref.delete()


@router.post("/upload-image")
async def admin_upload_image(file: Annotated[UploadFile, File()]):
    """Uploads an image to GCS (production) or returns a mock URL (dev)."""
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")

    # Limit file size to 5MB (checked via SpoolFile size if possible, or just trust client/proxy limits)
    # Note: For Cloud Run, we rely on the 512Mi limit we set.

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

        return {"url": url}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Upload failed: {exc}")
