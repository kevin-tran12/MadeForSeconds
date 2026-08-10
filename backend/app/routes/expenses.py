"""Admin-only expense ledger routes for tax tracking."""

import logging
import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from google.cloud import storage

from ..auth import require_admin
from ..config import settings
from ..firestore import get_db
from ..models_expense import (
    Expense,
    ExpenseCreate,
    ExpenseSummary,
    ExpenseUpdate,
    recalculate_project_amounts,
)
from ..services import uploads
from ..totp import require_totp_session

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/admin/expenses",
    dependencies=[Depends(require_admin), Depends(require_totp_session)],
)

MAX_RECEIPT_SIZE = 10 * 1024 * 1024  # 10 MB
ALLOWED_RECEIPT_TYPES = {"image/jpeg", "image/png", "image/webp", "application/pdf"}


def _doc_to_expense(doc) -> Expense:
    """Convert a Firestore document to an Expense model."""
    data = doc.to_dict()
    data["id"] = doc.id
    return Expense(**data)


def _doc_to_summary(doc) -> ExpenseSummary:
    """Convert a Firestore document to a lightweight ExpenseSummary."""
    data = doc.to_dict()
    data["id"] = doc.id
    return ExpenseSummary(**data)


def _write_revision(
    db, expense_id: str, revision: int, snapshot: dict, changed_by: str, summary: str
) -> None:
    """Write an immutable revision snapshot for audit trail."""
    db.collection("expense_revisions").document().set(
        {
            "expense_id": expense_id,
            "revision": revision,
            "snapshot": snapshot,
            "changed_by": changed_by,
            "changed_at": datetime.now(timezone.utc),
            "change_summary": summary,
        }
    )


# ── CRUD ─────────────────────────────────────────────────────────────────────


@router.post("", response_model=Expense, status_code=201)
async def create_expense(body: ExpenseCreate, request: Request):
    """Create a new expense entry with audit trail."""
    db = get_db()
    now = datetime.now(timezone.utc)

    data = body.model_dump()

    # Calculate project amounts from items
    project = recalculate_project_amounts(body.items, body.raw_tax, body.raw_subtotal)
    data.update(project)

    # Audit fields
    data["status"] = "active"
    data["voided_at"] = None
    data["void_reason"] = None
    data["created_at"] = now
    data["updated_at"] = now
    data["revision"] = 1
    data["ai_parsed"] = False

    # Receipt fields (set later via upload-receipt + update)
    data["receipt_url"] = None
    data["receipt_filename"] = None
    data["receipt_content_type"] = None

    doc_ref = db.collection("expenses").document()
    doc_ref.set(data)

    data["id"] = doc_ref.id

    # Write first revision
    admin_email = request.state.admin_email  # always set by require_admin
    _write_revision(db, doc_ref.id, 1, data, admin_email, "Created")

    return Expense(**data)


@router.get("", response_model=list[ExpenseSummary])
async def list_expenses(
    year: int,
    month: int | None = None,
    category: str | None = None,
    status: str = "active",
):
    """List expenses filtered by year, optional month, category, and status."""
    db = get_db()

    # Build date range
    if month:
        start = datetime(year, month, 1, tzinfo=timezone.utc)
        if month == 12:
            end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
        else:
            end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    else:
        start = datetime(year, 1, 1, tzinfo=timezone.utc)
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)

    query = db.collection("expenses")
    query = query.where("status", "==", status)
    query = query.where("date", ">=", start)
    query = query.where("date", "<", end)
    query = query.order_by("date", direction="DESCENDING")

    docs = list(query.stream())

    # Filter by category in Python (avoids needing a 3-field composite index)
    if category:
        docs = [d for d in docs if d.to_dict().get("category") == category]

    return [_doc_to_summary(doc) for doc in docs]


@router.get("/{expense_id}", response_model=Expense)
async def get_expense(expense_id: str):
    """Get a single expense with full item details."""
    db = get_db()
    doc = db.collection("expenses").document(expense_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Expense not found")
    return _doc_to_expense(doc)


@router.put("/{expense_id}", response_model=Expense)
async def update_expense(expense_id: str, body: ExpenseUpdate, request: Request):
    """Update an expense. Writes a revision snapshot before applying changes."""
    db = get_db()
    doc_ref = db.collection("expenses").document(expense_id)
    doc = doc_ref.get()

    if not doc.exists:
        raise HTTPException(status_code=404, detail="Expense not found")

    existing = doc.to_dict()

    if existing.get("status") == "voided":
        raise HTTPException(status_code=400, detail="Cannot update a voided expense")

    updates = body.model_dump(exclude_none=True)

    # Recalculate project amounts if items or raw values changed
    if "items" in updates:
        from ..models_expense import ExpenseItem

        items = [ExpenseItem(**i) for i in updates["items"]]
        raw_tax = updates.get("raw_tax", existing.get("raw_tax", 0))
        raw_subtotal = updates.get("raw_subtotal", existing.get("raw_subtotal", 0))
        project = recalculate_project_amounts(items, raw_tax, raw_subtotal)
        updates.update(project)

    now = datetime.now(timezone.utc)
    new_revision = existing.get("revision", 1) + 1
    updates["updated_at"] = now
    updates["revision"] = new_revision

    # Write revision BEFORE applying update (immutable audit trail)
    admin_email = request.state.admin_email  # always set by require_admin
    _write_revision(
        db, expense_id, new_revision, {**existing, "id": expense_id}, admin_email, "Updated"
    )

    doc_ref.update(updates)

    updated_doc = doc_ref.get()
    return _doc_to_expense(updated_doc)


@router.post("/{expense_id}/void")
async def void_expense(expense_id: str, request: Request, reason: str = ""):
    """Void an expense (no deletes allowed — audit trail)."""
    db = get_db()
    doc_ref = db.collection("expenses").document(expense_id)
    doc = doc_ref.get()

    if not doc.exists:
        raise HTTPException(status_code=404, detail="Expense not found")

    existing = doc.to_dict()
    if existing.get("status") == "voided":
        raise HTTPException(status_code=400, detail="Expense is already voided")

    now = datetime.now(timezone.utc)
    new_revision = existing.get("revision", 1) + 1

    admin_email = request.state.admin_email  # always set by require_admin
    _write_revision(
        db, expense_id, new_revision, {**existing, "id": expense_id}, admin_email, "Voided"
    )

    doc_ref.update(
        {
            "status": "voided",
            "voided_at": now,
            "void_reason": reason,
            "updated_at": now,
            "revision": new_revision,
        }
    )

    return {"voided": True, "expense_id": expense_id}


# ── Receipt Upload ───────────────────────────────────────────────────────────


@router.post("/upload-receipt")
async def upload_receipt(file: Annotated[UploadFile, File()]):
    """Upload a receipt image or PDF to private GCS bucket (or mock in dev)."""
    # Bounded read: cap memory at the limit instead of buffering the whole upload
    contents = await file.read(MAX_RECEIPT_SIZE + 1)
    if len(contents) > MAX_RECEIPT_SIZE:
        raise HTTPException(status_code=413, detail="File too large (max 10MB)")

    # Sniff the real type rather than trusting the client's declared one.
    try:
        content_type = uploads.verify_upload_type(contents, ALLOWED_RECEIPT_TYPES)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    safe_name = uploads.sanitize_filename(file.filename or "")
    filename = f"receipts/{uuid.uuid4()}-{safe_name}"

    if settings.is_dev or not settings.gcs_receipts_bucket_name:
        # Dev mode: return mock path
        return {
            "receipt_url": f"dev://{filename}",
            "receipt_filename": safe_name,
            "receipt_content_type": content_type,
        }

    try:
        client = storage.Client()
        bucket = client.bucket(settings.gcs_receipts_bucket_name)
        blob = bucket.blob(filename)
        blob.upload_from_string(contents, content_type=content_type)

        # Store the GCS path — NOT a public URL (bucket is private)
        return {
            "receipt_url": f"gs://{settings.gcs_receipts_bucket_name}/{filename}",
            "receipt_filename": safe_name,
            "receipt_content_type": content_type,
        }
    except Exception:
        logger.exception("Expense receipt upload to GCS failed")
        raise HTTPException(status_code=500, detail="Upload failed")


@router.get("/{expense_id}/receipt")
async def get_receipt(expense_id: str):
    """Generate a time-limited signed URL for a receipt in private GCS."""
    db = get_db()
    doc = db.collection("expenses").document(expense_id).get()

    if not doc.exists:
        raise HTTPException(status_code=404, detail="Expense not found")

    data = doc.to_dict()
    receipt_url = data.get("receipt_url")

    if not receipt_url:
        raise HTTPException(status_code=404, detail="No receipt attached")

    # Dev mode: return the mock path directly
    if receipt_url.startswith("dev://"):
        return {"url": receipt_url, "filename": data.get("receipt_filename")}

    # Parse gs:// path
    if not receipt_url.startswith("gs://"):
        raise HTTPException(status_code=500, detail="Invalid receipt storage path")

    parts = receipt_url[5:].split("/", 1)
    bucket_name = parts[0]
    blob_path = parts[1]

    try:
        # Routed through IAM signBlob so it works on Cloud Run, where the
        # metadata-server credentials have no local private key.
        signed_url = uploads.signed_get_url(bucket_name, blob_path)
        return {
            "url": signed_url,
            "filename": data.get("receipt_filename"),
            "content_type": data.get("receipt_content_type"),
        }
    except Exception:
        logger.exception("Signed receipt URL generation failed for expense %s", expense_id)
        raise HTTPException(status_code=500, detail="Failed to generate signed URL")
