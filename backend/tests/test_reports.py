import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

def test_summary_by_year(totp_authenticated_client, mock_db):
    """Correct totals and category breakdown for a year."""
    mock_doc = MagicMock()
    mock_doc.id = "exp_1"
    mock_doc.to_dict.return_value = {
        "date": datetime(2024, 1, 1, tzinfo=timezone.utc),
        "vendor": "AWS",
        "category": "software",
        "raw_total": 1000,
        "project_total": 1000,
        "project_tax": 100,
        "status": "active"
    }
    
    # _fetch_expenses calls query.stream()
    mock_db.collection.return_value.where.return_value.where.return_value.where.return_value.stream.return_value = iter([mock_doc])
    
    response = totp_authenticated_client.get("/api/admin/reports/summary?year=2024")
    assert response.status_code == 200
    data = response.json()
    assert data["total_expenses"] == 1000
    assert data["by_category"]["software"]["count"] == 1

def test_summary_empty(totp_authenticated_client, mock_db):
    """Zero totals when no expenses."""
    mock_db.collection.return_value.where.return_value.where.return_value.where.return_value.stream.return_value = iter([])
    
    response = totp_authenticated_client.get("/api/admin/reports/summary?year=2024")
    assert response.status_code == 200
    assert response.json()["total_expenses"] == 0
    assert response.json()["expense_count"] == 0

def test_export_csv(totp_authenticated_client, mock_db):
    """Returns CSV with correct headers and data rows."""
    mock_doc = MagicMock()
    mock_doc.id = "exp_1"
    mock_doc.to_dict.return_value = {
        "date": datetime(2024, 1, 1, tzinfo=timezone.utc),
        "vendor": "AWS",
        "category": "software",
        "project_total": 1234,
        "status": "active"
    }
    mock_db.collection.return_value.where.return_value.where.return_value.where.return_value.stream.return_value = iter([mock_doc])
    
    response = totp_authenticated_client.get("/api/admin/reports/export/csv?year=2024")
    assert response.status_code == 200
    assert "text/csv" in response.headers["Content-Type"]
    assert "AWS" in response.text
    assert "$12.34" in response.text
    assert "TOTAL" in response.text # Summary row

def test_export_pdf(totp_authenticated_client, mock_db):
    """Returns PDF content-type, non-empty body."""
    mock_doc = MagicMock()
    mock_doc.id = "exp_1"
    mock_doc.to_dict.return_value = {
        "date": datetime(2024, 1, 1, tzinfo=timezone.utc),
        "vendor": "AWS",
        "category": "software",
        "project_total": 1000,
        "status": "active"
    }
    mock_db.collection.return_value.where.return_value.where.return_value.where.return_value.stream.return_value = iter([mock_doc])
    
    response = totp_authenticated_client.get("/api/admin/reports/export/pdf?year=2024")
    assert response.status_code == 200
    assert "application/pdf" in response.headers["Content-Type"]
    assert len(response.content) > 0
