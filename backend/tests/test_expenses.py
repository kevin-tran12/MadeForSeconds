import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

from conftest import JPEG_BYTES, NOT_A_MEDIA_FILE, PDF_BYTES


# ── Fakes for transactional logic tests (no Firestore SDK / transaction-retry
# machinery) — same shape as test_subscriptions.py's fakes, adapted for
# expenses' single-document read instead of a query. mock_db (a MagicMock)
# cannot stand in for a real google.cloud.firestore.Transaction, so route-
# level tests below patch out the whole _*_transaction function instead
# (mock_expense_transactions), and these fakes exercise the real _*_logic
# functions directly, bypassing @transactional's retry wrapper. ────────────


class FakeDocRef:
    def __init__(self, doc_id="fake-expense"):
        self.id = doc_id


class FakeSnapshot:
    def __init__(self, exists, data=None):
        self.exists = exists
        self._data = data or {}

    def to_dict(self):
        return self._data


class FakeTransaction:
    """Minimal stand-in for a Firestore Transaction — just records
    .set()/.update() calls; doesn't simulate real commit/rollback atomicity
    (that's the SDK's job, not something a fake can prove — see the
    docstring on test_update_expense_logic_voided_raises_without_writing)."""

    def __init__(self):
        self.set_calls = []
        self.update_calls = []

    def set(self, ref, data):
        self.set_calls.append((ref, data))

    def update(self, ref, data):
        self.update_calls.append((ref, data))


class FakeDocRefWithSnapshot(FakeDocRef):
    """A doc ref that also knows how to .get() itself — for the ref passed
    into _update_expense_logic / _void_expense_logic (they call
    doc_ref.get(transaction=...))."""

    def __init__(self, doc_id, snapshot: FakeSnapshot):
        super().__init__(doc_id)
        self._snapshot = snapshot

    def get(self, transaction=None):
        return self._snapshot


class FakeCollection:
    def __init__(self):
        self._n = 0

    def document(self):
        self._n += 1
        return FakeDocRef(f"new-revision-{self._n}")


class FakeDb:
    def collection(self, name):
        return FakeCollection()


@pytest.fixture
def mock_expense_transactions():
    """Patches out all three transactional expense-mutation functions so
    route tests exercise request handling (status codes, response shape,
    calling convention) without depending on Firestore's transaction-retry
    machinery. The logic those functions wrap is covered directly by the
    _*_logic tests below, the same split test_subscriptions.py already uses
    for _process_event / _process_event_logic."""
    with (
        patch("app.routes.expenses._create_expense_transaction") as mock_create,
        patch("app.routes.expenses._update_expense_transaction") as mock_update,
        patch("app.routes.expenses._void_expense_transaction") as mock_void,
    ):
        yield {"create": mock_create, "update": mock_update, "void": mock_void}


# ── Route wiring (transactions patched via mock_expense_transactions) ──────


def test_create_expense(totp_authenticated_client, mock_db, mock_expense_transactions):
    """Creates doc with calculated project amounts; route returns 201 with
    the computed data regardless of what the (mocked) transaction did."""
    mock_db.collection.return_value.document.return_value.id = "exp_123"

    payload = {
        "date": "2024-01-01T00:00:00Z",
        "vendor": "AWS",
        "category": "software",
        "items": [
            {"name": "Hosting", "quantity": 1, "unit_price": 1000, "total_price": 1000, "project_related": True}
        ],
        "raw_subtotal": 1000,
        "raw_tax": 100,
        "raw_total": 1100
    }

    response = totp_authenticated_client.post("/api/admin/expenses", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["project_subtotal"] == 1000
    assert data["project_tax"] == 100
    assert data["project_total"] == 1100
    assert data["id"] == "exp_123"
    mock_expense_transactions["create"].assert_called_once()


def test_create_expense_commits_via_one_transaction_call(totp_authenticated_client, mock_db, mock_expense_transactions):
    """The route makes exactly one call into the transactional function —
    the atomicity guarantee (doc + revision commit together) lives inside
    that function, verified separately by test_create_expense_logic_*
    below, not by counting individual .set() calls at the route layer
    anymore (there's no non-transactional .set() left to count)."""
    mock_db.collection.return_value.document.return_value.id = "exp_123"

    payload = {
        "date": "2024-01-01T00:00:00Z",
        "vendor": "AWS",
        "category": "software",
        "items": []
    }

    response = totp_authenticated_client.post("/api/admin/expenses", json=payload)
    assert response.status_code == 201
    mock_expense_transactions["create"].assert_called_once()


def test_create_expense_receipt_url_validated_and_normalized(
    totp_authenticated_client, mock_db, mock_expense_transactions
):
    """A receipt_url in the create payload is re-validated against the
    receipts bucket, and the validator's filename/content-type — not the
    client's — end up in the document written inside the transaction."""
    mock_db.collection.return_value.document.return_value.id = "exp_123"

    payload = {
        "date": "2024-01-01T00:00:00Z",
        "vendor": "AWS",
        "category": "software",
        "items": [],
        "receipt_url": "gs://receipts-bucket/receipts/uuid-invoice.pdf",
        "receipt_filename": "client-supplied-name.pdf",
        "receipt_content_type": "text/plain",
    }

    with patch(
        "app.routes.expenses.uploads.resolve_receipt_url",
        return_value={
            "receipt_url": "gs://receipts-bucket/receipts/uuid-invoice.pdf",
            "receipt_filename": "invoice.pdf",
            "receipt_content_type": "application/pdf",
        },
    ) as resolver:
        response = totp_authenticated_client.post("/api/admin/expenses", json=payload)

    assert response.status_code == 201
    resolver.assert_called_once_with("gs://receipts-bucket/receipts/uuid-invoice.pdf")
    call_args = mock_expense_transactions["create"].call_args[0]
    # (transaction, db, doc_ref, data, admin_email)
    written = call_args[3]
    assert written["receipt_filename"] == "invoice.pdf"
    assert written["receipt_content_type"] == "application/pdf"


def test_create_expense_invalid_receipt_url_rejected(
    totp_authenticated_client, mock_db, mock_expense_transactions
):
    """An unresolvable receipt_url is rejected before the transaction ever
    starts — no expense document is written pointing at an object that
    isn't actually there."""
    payload = {
        "date": "2024-01-01T00:00:00Z",
        "vendor": "AWS",
        "category": "software",
        "items": [],
        "receipt_url": "https://evil.example/r.pdf",
    }

    with patch(
        "app.routes.expenses.uploads.resolve_receipt_url",
        side_effect=ValueError("receipt_url must be a gs:// URL in the receipts bucket."),
    ):
        response = totp_authenticated_client.post("/api/admin/expenses", json=payload)

    assert response.status_code == 400
    mock_expense_transactions["create"].assert_not_called()


def test_create_expense_receipt_validation_outage_returns_clean_500(
    totp_authenticated_client, mock_db, mock_expense_transactions
):
    """An unexpected failure validating the receipt (e.g. a GCS outage) is
    logged and reported as a generic 500 — same convention as every other
    GCS call in this router — rather than an unhandled exception."""
    payload = {
        "date": "2024-01-01T00:00:00Z",
        "vendor": "AWS",
        "category": "software",
        "items": [],
        "receipt_url": "gs://receipts-bucket/receipts/uuid-invoice.pdf",
    }

    with patch(
        "app.routes.expenses.uploads.resolve_receipt_url",
        side_effect=RuntimeError("GCS unavailable"),
    ):
        response = totp_authenticated_client.post("/api/admin/expenses", json=payload)

    assert response.status_code == 500
    mock_expense_transactions["create"].assert_not_called()


def test_list_expenses_by_year(totp_authenticated_client, mock_db):
    """Filters by date range."""
    # Mocking stream to return one doc
    mock_doc = MagicMock()
    mock_doc.id = "exp_1"
    mock_doc.to_dict.return_value = {
        "date": datetime(2024, 1, 1, tzinfo=timezone.utc),
        "vendor": "AWS",
        "category": "software",
        "description": "Hosting",
        "raw_total": 1000,
        "project_total": 1000,
        "project_tax": 100,
        "status": "active",
        "created_at": datetime(2024, 1, 1, tzinfo=timezone.utc)
    }

    mock_db.collection.return_value.where.return_value.where.return_value.where.return_value.order_by.return_value.stream.return_value = iter([mock_doc])

    response = totp_authenticated_client.get("/api/admin/expenses?year=2024")
    assert response.status_code == 200
    assert len(response.json()) == 1

def test_get_expense(totp_authenticated_client, mock_db, sample_expense_doc):
    """Returns full expense with items."""
    mock_doc = sample_expense_doc(id="exp_123")
    mock_db.collection.return_value.document.return_value.get.return_value = mock_doc

    response = totp_authenticated_client.get("/api/admin/expenses/exp_123")
    assert response.status_code == 200
    assert response.json()["vendor"] == "Test Vendor"
    assert len(response.json()["items"]) == 1

def test_update_expense(totp_authenticated_client, mock_db, mock_expense_transactions):
    """Route passes the request body through to the transactional function
    and returns its merged result as the response."""
    mock_expense_transactions["update"].return_value = {
        "vendor": "New",
        "date": "2024-01-01T00:00:00Z",
        "category": "software",
        "description": "",
        "raw_subtotal": 10000,
        "raw_tax": 500,
        "raw_total": 10500,
        "project_subtotal": 10000,
        "project_tax": 500,
        "project_total": 10500,
        "items": [],
        "status": "active",
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-02T00:00:00Z",
        "revision": 2,
    }

    payload = {"vendor": "New"}
    response = totp_authenticated_client.put("/api/admin/expenses/exp_123", json=payload)
    assert response.status_code == 200
    assert response.json()["revision"] == 2
    assert response.json()["vendor"] == "New"
    assert response.json()["id"] == "exp_123"

    mock_expense_transactions["update"].assert_called_once()
    call_args = mock_expense_transactions["update"].call_args[0]
    # (transaction, db, doc_ref, updates, admin_email)
    assert call_args[3] == {"vendor": "New"}


def test_update_expense_receipt_url_validated_and_normalized(
    totp_authenticated_client, mock_db, mock_expense_transactions
):
    """A receipt_url in the update payload is re-validated before the
    transaction starts (a GCS call must never live inside a function
    Firestore may retry), and the validator's fields — not the client's —
    are what reach the transaction."""
    mock_expense_transactions["update"].return_value = {
        "vendor": "AWS",
        "date": "2024-01-01T00:00:00Z",
        "category": "software",
        "description": "",
        "raw_subtotal": 10000,
        "raw_tax": 500,
        "raw_total": 10500,
        "project_subtotal": 10000,
        "project_tax": 500,
        "project_total": 10500,
        "items": [],
        "status": "active",
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-02T00:00:00Z",
        "revision": 2,
        "receipt_url": "gs://receipts-bucket/receipts/uuid-invoice.pdf",
        "receipt_filename": "invoice.pdf",
        "receipt_content_type": "application/pdf",
    }

    payload = {
        "receipt_url": "gs://receipts-bucket/receipts/uuid-invoice.pdf",
        "receipt_filename": "client-supplied-name.pdf",
        "receipt_content_type": "text/plain",
    }

    with patch(
        "app.routes.expenses.uploads.resolve_receipt_url",
        return_value={
            "receipt_url": "gs://receipts-bucket/receipts/uuid-invoice.pdf",
            "receipt_filename": "invoice.pdf",
            "receipt_content_type": "application/pdf",
        },
    ) as resolver:
        response = totp_authenticated_client.put("/api/admin/expenses/exp_123", json=payload)

    assert response.status_code == 200
    resolver.assert_called_once_with("gs://receipts-bucket/receipts/uuid-invoice.pdf")
    call_args = mock_expense_transactions["update"].call_args[0]
    updates = call_args[3]
    assert updates["receipt_filename"] == "invoice.pdf"
    assert updates["receipt_content_type"] == "application/pdf"


def test_update_expense_invalid_receipt_url_rejected(
    totp_authenticated_client, mock_db, mock_expense_transactions
):
    """An unresolvable receipt_url is rejected before the update transaction
    runs — no revision gets written over a bogus association."""
    payload = {"receipt_url": "https://evil.example/r.pdf"}

    with patch(
        "app.routes.expenses.uploads.resolve_receipt_url",
        side_effect=ValueError("receipt_url must be a gs:// URL in the receipts bucket."),
    ):
        response = totp_authenticated_client.put("/api/admin/expenses/exp_123", json=payload)

    assert response.status_code == 400
    mock_expense_transactions["update"].assert_not_called()


def test_void_expense(totp_authenticated_client, mock_db, mock_expense_transactions):
    """Sets status=voided via the transactional function; route returns the
    fixed acknowledgement shape regardless of the transaction's internals."""
    response = totp_authenticated_client.post("/api/admin/expenses/exp_123/void?reason=test")
    assert response.status_code == 200
    assert response.json()["voided"] is True

    mock_expense_transactions["void"].assert_called_once()
    call_args = mock_expense_transactions["void"].call_args[0]
    # (transaction, db, doc_ref, reason, admin_email)
    assert call_args[3] == "test"


def test_update_expense_propagates_not_found(totp_authenticated_client, mock_db, mock_expense_transactions):
    """A 404 raised inside the transactional function surfaces as the
    route's own response, not a 500 — HTTPException raised inside a
    @transactional-wrapped function propagates through normally."""
    from fastapi import HTTPException

    mock_expense_transactions["update"].side_effect = HTTPException(status_code=404, detail="Expense not found")
    response = totp_authenticated_client.put("/api/admin/expenses/missing", json={"vendor": "New"})
    assert response.status_code == 404


def test_void_expense_propagates_already_voided(totp_authenticated_client, mock_db, mock_expense_transactions):
    from fastapi import HTTPException

    mock_expense_transactions["void"].side_effect = HTTPException(status_code=400, detail="Expense is already voided")
    response = totp_authenticated_client.post("/api/admin/expenses/exp_123/void")
    assert response.status_code == 400


def test_upload_receipt_dev_mode(totp_authenticated_client):
    """Returns mock path."""
    with patch("app.routes.expenses.settings") as mock_settings:
        mock_settings.is_dev = True
        file_data = {"file": ("receipt.pdf", PDF_BYTES, "application/pdf")}
        response = totp_authenticated_client.post("/api/admin/expenses/upload-receipt", files=file_data)
        assert response.status_code == 200
        assert "dev://" in response.json()["receipt_url"]

def test_get_receipt_url(totp_authenticated_client, mock_db, sample_expense_doc):
    """Returns signed URL structure (mocked)."""
    mock_doc = sample_expense_doc(id="exp_123", receipt_url="dev://receipts/test.pdf")
    mock_db.collection.return_value.document.return_value.get.return_value = mock_doc

    response = totp_authenticated_client.get("/api/admin/expenses/exp_123/receipt")
    assert response.status_code == 200
    assert response.json()["url"] == "dev://receipts/test.pdf"

def test_get_receipt_gcs_uses_cloud_run_safe_signing(totp_authenticated_client, mock_db, sample_expense_doc):
    """gs:// receipts go through the IAM signBlob helper (works on Cloud Run)."""
    mock_doc = sample_expense_doc(
        id="exp_123",
        receipt_url="gs://my-receipts/receipts/uuid-r.pdf",
        receipt_filename="r.pdf",
        receipt_content_type="application/pdf",
    )
    mock_db.collection.return_value.document.return_value.get.return_value = mock_doc

    with patch("app.routes.expenses.settings") as mock_settings:
        mock_settings.gcs_receipts_bucket_name = "my-receipts"
        with patch("app.services.uploads.signed_get_url", return_value="https://signed.example/r") as signer:
            response = totp_authenticated_client.get("/api/admin/expenses/exp_123/receipt")

    assert response.status_code == 200
    assert response.json()["url"] == "https://signed.example/r"
    assert response.json()["filename"] == "r.pdf"
    signer.assert_called_once_with("my-receipts", "receipts/uuid-r.pdf")


def test_get_receipt_wrong_bucket_rejected(totp_authenticated_client, mock_db, sample_expense_doc):
    """A receipt_url naming a bucket other than the configured receipts
    bucket is rejected rather than signed — defends persisted data that
    predates validation, or was written by a path other than this app's own
    (validated) writers."""
    mock_doc = sample_expense_doc(id="exp_123", receipt_url="gs://some-other-bucket/receipts/r.pdf")
    mock_db.collection.return_value.document.return_value.get.return_value = mock_doc

    with patch("app.routes.expenses.settings") as mock_settings:
        mock_settings.gcs_receipts_bucket_name = "my-receipts"
        response = totp_authenticated_client.get("/api/admin/expenses/exp_123/receipt")

    assert response.status_code == 500


def test_get_receipt_pathless_gs_url_rejected(totp_authenticated_client, mock_db, sample_expense_doc):
    """A gs://bucket URL with no object path must not raise an unhandled
    IndexError."""
    mock_doc = sample_expense_doc(id="exp_123", receipt_url="gs://my-receipts")
    mock_db.collection.return_value.document.return_value.get.return_value = mock_doc

    with patch("app.routes.expenses.settings") as mock_settings:
        mock_settings.gcs_receipts_bucket_name = "my-receipts"
        response = totp_authenticated_client.get("/api/admin/expenses/exp_123/receipt")

    assert response.status_code == 500


# ── _create_expense_logic (atomic doc + first revision) ─────────────────────


def test_create_expense_logic_writes_doc_and_revision_in_one_transaction():
    from app.routes.expenses import _create_expense_logic

    txn = FakeTransaction()
    db = FakeDb()
    doc_ref = FakeDocRef("exp_1")
    data = {"vendor": "AWS", "revision": 1}

    _create_expense_logic(txn, db, doc_ref, data, "admin@example.com")

    assert len(txn.set_calls) == 2
    (expense_ref, expense_data), (revision_ref, revision_data) = txn.set_calls
    assert expense_ref is doc_ref
    assert expense_data == data  # stored without an "id" key, same as before
    assert revision_data["expense_id"] == "exp_1"
    assert revision_data["revision"] == 1
    assert revision_data["snapshot"] == {**data, "id": "exp_1"}
    assert revision_data["change_summary"] == "Created"
    assert revision_data["changed_by"] == "admin@example.com"


# ── _update_expense_logic (atomic read-validate-revision-write) ─────────────


def test_update_expense_logic_missing_raises():
    from app.routes.expenses import _update_expense_logic
    from fastapi import HTTPException

    ref = FakeDocRefWithSnapshot("exp_1", FakeSnapshot(exists=False))
    with pytest.raises(HTTPException) as exc_info:
        _update_expense_logic(FakeTransaction(), FakeDb(), ref, {"vendor": "New"}, "admin@example.com")
    assert exc_info.value.status_code == 404


def test_update_expense_logic_voided_raises_without_writing():
    """A real Firestore transaction discards every buffered write when the
    wrapped function raises — that all-or-nothing rollback is the SDK's
    guarantee, not something a fake object can simulate. What this test can
    and does verify is this function's own control flow: it must never
    reach either write once the voided check fails, since those writes are
    exactly what a real transaction would also refuse to commit."""
    from app.routes.expenses import _update_expense_logic
    from fastapi import HTTPException

    ref = FakeDocRefWithSnapshot("exp_1", FakeSnapshot(exists=True, data={"status": "voided", "revision": 3}))
    txn = FakeTransaction()
    with pytest.raises(HTTPException) as exc_info:
        _update_expense_logic(txn, FakeDb(), ref, {"vendor": "New"}, "admin@example.com")
    assert exc_info.value.status_code == 400
    assert txn.set_calls == []
    assert txn.update_calls == []


def test_update_expense_logic_increments_revision_from_the_transactional_read():
    """The new revision is computed from the value just read inside this
    transaction, not a value the caller passed in — this is what lets two
    concurrent updates avoid colliding on the same revision number (a
    real transaction retries automatically if its read set goes stale;
    recomputing from a stale caller-supplied number would defeat that)."""
    from app.routes.expenses import _update_expense_logic

    existing = {"vendor": "Old", "status": "active", "revision": 5, "raw_tax": 0, "raw_subtotal": 0}
    ref = FakeDocRefWithSnapshot("exp_1", FakeSnapshot(exists=True, data=existing))
    txn = FakeTransaction()

    result = _update_expense_logic(txn, FakeDb(), ref, {"vendor": "New"}, "admin@example.com")

    assert result["revision"] == 6
    (revision_ref, revision_data), = [c for c in txn.set_calls]
    assert revision_data["revision"] == 6
    assert revision_data["snapshot"]["revision"] == 5  # pre-change state
    (updated_ref, updated_data), = txn.update_calls
    assert updated_ref is ref
    assert updated_data["revision"] == 6
    assert updated_data["vendor"] == "New"


def test_update_expense_logic_recalculates_project_amounts_from_existing_raw_values():
    """items-only update falls back to the EXISTING document's raw_tax /
    raw_subtotal, which only the transactional read can supply — this is
    why the recalculation has to live inside _update_expense_logic and not
    before the transaction starts."""
    from app.routes.expenses import _update_expense_logic

    existing = {
        "vendor": "AWS", "status": "active", "revision": 1,
        "raw_tax": 100, "raw_subtotal": 1000,
    }
    ref = FakeDocRefWithSnapshot("exp_1", FakeSnapshot(exists=True, data=existing))
    updates = {
        "items": [
            {"name": "Hosting", "quantity": 1, "unit_price": 1000, "total_price": 1000, "project_related": True}
        ]
    }

    result = _update_expense_logic(FakeTransaction(), FakeDb(), ref, updates, "admin@example.com")

    assert result["project_subtotal"] == 1000
    assert result["project_tax"] == 100
    assert result["project_total"] == 1100


def test_update_expense_logic_does_not_mutate_caller_dict():
    """Firestore may retry a transactional function on contention — a dict
    mutated in place across retries would compound (e.g. re-adding
    updated_at/revision on top of a previous attempt's)."""
    from app.routes.expenses import _update_expense_logic

    existing = {"vendor": "Old", "status": "active", "revision": 1}
    ref = FakeDocRefWithSnapshot("exp_1", FakeSnapshot(exists=True, data=existing))
    caller_updates = {"vendor": "New"}

    _update_expense_logic(FakeTransaction(), FakeDb(), ref, caller_updates, "admin@example.com")

    assert caller_updates == {"vendor": "New"}


# ── _void_expense_logic (atomic read-validate-revision-write) ───────────────


def test_void_expense_logic_missing_raises():
    from app.routes.expenses import _void_expense_logic
    from fastapi import HTTPException

    ref = FakeDocRefWithSnapshot("exp_1", FakeSnapshot(exists=False))
    with pytest.raises(HTTPException) as exc_info:
        _void_expense_logic(FakeTransaction(), FakeDb(), ref, "test", "admin@example.com")
    assert exc_info.value.status_code == 404


def test_void_expense_logic_already_voided_raises_without_writing():
    from app.routes.expenses import _void_expense_logic
    from fastapi import HTTPException

    ref = FakeDocRefWithSnapshot("exp_1", FakeSnapshot(exists=True, data={"status": "voided", "revision": 2}))
    txn = FakeTransaction()
    with pytest.raises(HTTPException) as exc_info:
        _void_expense_logic(txn, FakeDb(), ref, "test", "admin@example.com")
    assert exc_info.value.status_code == 400
    assert txn.set_calls == []
    assert txn.update_calls == []


def test_void_expense_logic_writes_revision_and_status_together():
    from app.routes.expenses import _void_expense_logic

    existing = {"vendor": "AWS", "status": "active", "revision": 1}
    ref = FakeDocRefWithSnapshot("exp_1", FakeSnapshot(exists=True, data=existing))
    txn = FakeTransaction()

    _void_expense_logic(txn, FakeDb(), ref, "no longer needed", "admin@example.com")

    assert len(txn.set_calls) == 1  # the revision
    assert len(txn.update_calls) == 1  # the status change
    (_, revision_data), = txn.set_calls
    assert revision_data["revision"] == 2
    assert revision_data["change_summary"] == "Voided"
    (updated_ref, updated_data), = txn.update_calls
    assert updated_ref is ref
    assert updated_data["status"] == "voided"
    assert updated_data["void_reason"] == "no longer needed"
    assert updated_data["revision"] == 2
