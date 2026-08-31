"""Admin-only expense ledger routes for tax tracking."""

import logging
import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from google.cloud import storage
from google.cloud.firestore import transactional

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


def _validate_receipt_url(receipt_url: str) -> dict:
    """Re-validate a client-supplied receipt_url before it reaches a write,
    translating uploads.resolve_receipt_url's outcomes into HTTP responses:
    a bad or unresolvable URL is the caller's mistake (400); anything else
    (a GCS outage, a transient auth failure) is ours, logged and reported
    generically like every other GCS call in this router."""
    try:
        return uploads.resolve_receipt_url(receipt_url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception:
        logger.exception("Receipt URL validation failed for %s", receipt_url)
        raise HTTPException(status_code=500, detail="Failed to validate receipt")


def _write_revision_in_transaction(
    transaction, db, expense_id: str, revision: int, snapshot: dict, changed_by: str, summary: str
) -> None:
    """Write an immutable revision snapshot for audit trail, as part of an
    active transaction — never called outside one, so the revision and
    whatever expense-document write accompanies it commit together or not
    at all."""
    revision_ref = db.collection("expense_revisions").document()
    transaction.set(
        revision_ref,
        {
            "expense_id": expense_id,
            "revision": revision,
            "snapshot": snapshot,
            "changed_by": changed_by,
            "changed_at": datetime.now(timezone.utc),
            "change_summary": summary,
        },
    )


# ── CRUD ─────────────────────────────────────────────────────────────────────
#
# Every mutation below commits its expense-document write and its
# expense_revisions audit write inside one Firestore transaction — a
# timeout, quota failure, or crash between "write the expense" and "write
# the revision" (previously two independent operations) can no longer leave
# one without the other. update/void additionally read the current document
# *inside* the transaction rather than before it starts, which is what makes
# the revision-number increment safe under concurrent requests: if two
# updates race, Firestore's own optimistic-concurrency check invalidates
# whichever transaction's read set went stale first and retries it
# automatically, so the retried one recomputes its revision against the
# other's already-committed state instead of colliding on the same number.


def _create_expense_logic(transaction, db, doc_ref, data: dict, admin_email: str) -> None:
    transaction.set(doc_ref, data)
    _write_revision_in_transaction(
        transaction, db, doc_ref.id, 1, {**data, "id": doc_ref.id}, admin_email, "Created"
    )


_create_expense_transaction = transactional(_create_expense_logic)


@router.post("", response_model=Expense, status_code=201)
async def create_expense(body: ExpenseCreate, request: Request):
    """Create a new expense entry. The document and its first revision
    commit atomically."""
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

    # Receipt: re-validate against the receipts bucket rather than trusting
    # the client-supplied filename/content-type — same validator the MCP
    # create_expense tool uses, so there is one implementation, not two.
    if body.receipt_url:
        data.update(_validate_receipt_url(body.receipt_url))
    else:
        data["receipt_url"] = None
        data["receipt_filename"] = None
        data["receipt_content_type"] = None

    doc_ref = db.collection("expenses").document()
    admin_email = request.state.admin_email  # always set by require_admin

    _create_expense_transaction(db.transaction(), db, doc_ref, data, admin_email)

    data["id"] = doc_ref.id
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


def _update_expense_logic(transaction, db, doc_ref, raw_updates: dict, admin_email: str) -> dict:
    # Read phase — must happen before any write in this transaction, and
    # must be the read that decides everything below, not a pre-transaction
    # read: this is what lets Firestore's own retry-on-conflict machinery
    # keep two concurrent updates from computing the same revision number.
    snapshot = doc_ref.get(transaction=transaction)
    if not snapshot.exists:
        raise HTTPException(status_code=404, detail="Expense not found")

    existing = snapshot.to_dict()
    if existing.get("status") == "voided":
        raise HTTPException(status_code=400, detail="Cannot update a voided expense")

    updates = dict(raw_updates)  # never mutate the caller's dict — Firestore
    # may retry this function on contention, and a mutated-in-place dict
    # would compound across retries.

    # Recalculate project amounts if items or raw values changed. Needs
    # `existing` for its fallback raw_tax/raw_subtotal, so this can only
    # happen after the transactional read above, not before it.
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

    # Write phase — revision snapshot captures the PRE-change state, same as
    # before; both writes are buffered in this one transaction and commit
    # together (or, on a raised exception above, neither commits at all).
    _write_revision_in_transaction(
        transaction, db, doc_ref.id, new_revision, {**existing, "id": doc_ref.id}, admin_email, "Updated"
    )
    transaction.update(doc_ref, updates)

    # Merged rather than re-read after commit: `.update()` sets exactly
    # these fields and nothing else server-computed, so this is identical to
    # what a post-commit `.get()` would show, at the cost of one fewer read.
    return {**existing, **updates}


_update_expense_transaction = transactional(_update_expense_logic)


@router.put("/{expense_id}", response_model=Expense)
async def update_expense(expense_id: str, body: ExpenseUpdate, request: Request):
    """Update an expense. The revision snapshot and the update commit
    atomically — a failure between them, or two updates racing on the same
    revision number, are no longer possible."""
    db = get_db()
    doc_ref = db.collection("expenses").document(expense_id)
    updates = body.model_dump(exclude_none=True)
    admin_email = request.state.admin_email  # always set by require_admin

    # Re-validate before the transaction starts: this is a GCS call, and a
    # Firestore transaction can retry its body on contention, which must
    # never re-trigger an external network call.
    if "receipt_url" in updates:
        updates.update(_validate_receipt_url(updates["receipt_url"]))

    merged = _update_expense_transaction(db.transaction(), db, doc_ref, updates, admin_email)
    merged["id"] = expense_id
    return Expense(**merged)


def _void_expense_logic(transaction, db, doc_ref, reason: str, admin_email: str) -> None:
    snapshot = doc_ref.get(transaction=transaction)
    if not snapshot.exists:
        raise HTTPException(status_code=404, detail="Expense not found")

    existing = snapshot.to_dict()
    if existing.get("status") == "voided":
        raise HTTPException(status_code=400, detail="Expense is already voided")

    now = datetime.now(timezone.utc)
    new_revision = existing.get("revision", 1) + 1

    _write_revision_in_transaction(
        transaction, db, doc_ref.id, new_revision, {**existing, "id": doc_ref.id}, admin_email, "Voided"
    )
    transaction.update(
        doc_ref,
        {
            "status": "voided",
            "voided_at": now,
            "void_reason": reason,
            "updated_at": now,
            "revision": new_revision,
        },
    )


_void_expense_transaction = transactional(_void_expense_logic)


@router.post("/{expense_id}/void")
async def void_expense(expense_id: str, request: Request, reason: str = ""):
    """Void an expense (no deletes allowed — audit trail). Revision snapshot
    and the status change commit atomically, same guarantee as
    update_expense."""
    db = get_db()
    doc_ref = db.collection("expenses").document(expense_id)
    admin_email = request.state.admin_email  # always set by require_admin

    _void_expense_transaction(db.transaction(), db, doc_ref, reason, admin_email)

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
    if len(parts) != 2 or not parts[1]:
        raise HTTPException(status_code=500, detail="Invalid receipt storage path")
    bucket_name, blob_path = parts

    if bucket_name != settings.gcs_receipts_bucket_name:
        raise HTTPException(status_code=500, detail="Invalid receipt storage path")

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
