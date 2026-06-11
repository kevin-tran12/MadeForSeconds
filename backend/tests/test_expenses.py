import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

def test_create_expense(totp_authenticated_client, mock_db):
    """Creates doc with calculated project amounts."""
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

def test_create_expense_writes_audit_trail(totp_authenticated_client, mock_db):
    """Revision 1 written to expense_revisions."""
    mock_db.collection.return_value.document.return_value.id = "exp_123"
    
    payload = {
        "date": "2024-01-01T00:00:00Z",
        "vendor": "AWS",
        "category": "software",
        "items": []
    }
    
    response = totp_authenticated_client.post("/api/admin/expenses", json=payload)
    assert response.status_code == 201
    
    # Check that revision was written. 
    # There are 2 calls to set(): 1 for expenses doc, 1 for revision doc.
    assert mock_db.collection.return_value.document.return_value.set.call_count == 2

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

def test_update_expense(totp_authenticated_client, mock_db, sample_expense_doc):
    """Recalculates project amounts, increments revision."""
    old_doc = sample_expense_doc(id="exp_123", revision=1, vendor="Old")
    new_doc = sample_expense_doc(id="exp_123", revision=2, vendor="New")
    
    mock_db.collection.return_value.document.return_value.get.side_effect = [old_doc, new_doc]
    
    payload = {"vendor": "New"}
    response = totp_authenticated_client.put("/api/admin/expenses/exp_123", json=payload)
    assert response.status_code == 200
    assert response.json()["revision"] == 2
    assert response.json()["vendor"] == "New"

def test_void_expense(totp_authenticated_client, mock_db, sample_expense_doc):
    """Sets status=voided, voided_at, void_reason."""
    mock_doc = sample_expense_doc(id="exp_123", status="active")
    mock_db.collection.return_value.document.return_value.get.return_value = mock_doc
    
    response = totp_authenticated_client.post("/api/admin/expenses/exp_123/void?reason=test")
    assert response.status_code == 200
    assert response.json()["voided"] is True
    
    mock_db.collection.return_value.document.return_value.update.assert_called_once()
    args = mock_db.collection.return_value.document.return_value.update.call_args[0][0]
    assert args["status"] == "voided"
    assert args["void_reason"] == "test"

def test_upload_receipt_dev_mode(totp_authenticated_client):
    """Returns mock path."""
    with patch("app.routes.expenses.settings") as mock_settings:
        mock_settings.is_dev = True
        file_data = {"file": ("receipt.pdf", b"pdf-content", "application/pdf")}
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

    with patch("app.services.uploads.signed_get_url", return_value="https://signed.example/r") as signer:
        response = totp_authenticated_client.get("/api/admin/expenses/exp_123/receipt")

    assert response.status_code == 200
    assert response.json()["url"] == "https://signed.example/r"
    assert response.json()["filename"] == "r.pdf"
    signer.assert_called_once_with("my-receipts", "receipts/uuid-r.pdf")
