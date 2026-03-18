import pytest
from unittest.mock import MagicMock

def test_list_pending_supporters(authenticated_client, mock_db):
    """Verifies that only supporters with pending notes are returned."""
    mock_doc = MagicMock()
    mock_doc.id = "sub1"
    mock_doc.to_dict.return_value = {
        "email": "test@example.com",
        "display_name": "Test",
        "note_pending": "Please approve me",
        "note_pending_public": True
    }
    
    # Mocking both subscribers and donations collections
    mock_db.collection.side_effect = [
        MagicMock(stream=MagicMock(return_value=iter([mock_doc]))), # subscribers
        MagicMock(stream=MagicMock(return_value=iter([])))        # donations
    ]
    
    response = authenticated_client.get("/api/admin/supporters/pending")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == "sub1"
    assert data[0]["note_pending"] == "Please approve me"

def test_approve_note(authenticated_client, mock_db):
    """Verifies that a note is moved from pending to live."""
    mock_doc = MagicMock()
    mock_doc.exists = True
    mock_doc.to_dict.return_value = {
        "note_pending": "Good note",
        "note_pending_public": True
    }
    mock_db.collection.return_value.document.return_value.get.return_value = mock_doc
    
    response = authenticated_client.post("/api/admin/supporters/subscribers/sub1/approve-note")
    assert response.status_code == 200
    assert response.json()["approved"] is True
    
    # Check that update was called
    mock_db.collection.return_value.document.return_value.update.assert_called_once()
    args = mock_db.collection.return_value.document.return_value.update.call_args[0][0]
    assert args["note"] == "Good note"
    assert args["note_pending"] is None

def test_reject_note(authenticated_client, mock_db):
    """Verifies that a pending note is cleared."""
    mock_doc = MagicMock()
    mock_doc.exists = True
    mock_db.collection.return_value.document.return_value.get.return_value = mock_doc
    
    response = authenticated_client.post("/api/admin/supporters/subscribers/sub1/reject-note")
    assert response.status_code == 200
    assert response.json()["rejected"] is True
    
    # Check that update was called with note_pending=None
    mock_db.collection.return_value.document.return_value.update.assert_called_once()
    args = mock_db.collection.return_value.document.return_value.update.call_args[0][0]
    assert args["note_pending"] is None

def test_toggle_name_visibility(authenticated_client, mock_db):
    """Verifies flipping name_enabled."""
    mock_doc = MagicMock()
    mock_doc.exists = True
    mock_doc.to_dict.return_value = {"name_enabled": True}
    mock_db.collection.return_value.document.return_value.get.return_value = mock_doc
    
    response = authenticated_client.post("/api/admin/supporters/subscribers/sub1/toggle-name")
    assert response.status_code == 200
    assert response.json()["name_enabled"] is False

def test_toggle_note_visibility(authenticated_client, mock_db):
    """Verifies flipping note_enabled."""
    mock_doc = MagicMock()
    mock_doc.exists = True
    mock_doc.to_dict.return_value = {"note_enabled": True}
    mock_db.collection.return_value.document.return_value.get.return_value = mock_doc
    
    response = authenticated_client.post("/api/admin/supporters/subscribers/sub1/toggle-note")
    assert response.status_code == 200
    assert response.json()["note_enabled"] is False

def test_list_all_supporters(authenticated_client, mock_db):
    """Verifies that all supporters with display names are returned."""
    mock_doc = MagicMock()
    mock_doc.id = "sub1"
    mock_doc.to_dict.return_value = {
        "display_name": "Supporter 1",
        "amount_cents": 1000,
        "status": "active"
    }
    
    mock_db.collection.side_effect = [
        MagicMock(stream=MagicMock(return_value=iter([mock_doc]))),
        MagicMock(stream=MagicMock(return_value=iter([])))
    ]
    
    response = authenticated_client.get("/api/admin/supporters/all")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["display_name"] == "Supporter 1"
