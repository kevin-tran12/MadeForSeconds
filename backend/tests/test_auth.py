import pytest
from unittest.mock import MagicMock, patch
from fastapi import HTTPException, Request
from app.auth import require_admin


@pytest.fixture
def mock_request():
    request = MagicMock(spec=Request)
    request.headers = {}
    request.state = MagicMock()
    return request


def test_dev_mode_auth_bypass(mock_request):
    with patch("app.auth.settings") as mock_settings:
        mock_settings.is_dev = True
        mock_request.headers = {"X-Dev-Admin": "true"}
        
        email = require_admin(mock_request)
        assert email == "dev@local"
        assert mock_request.state.admin_email == "dev@local"


def test_dev_mode_no_header(mock_request):
    with patch("app.auth.settings") as mock_settings:
        mock_settings.is_dev = True
        mock_request.headers = {}
        
        with pytest.raises(HTTPException) as exc:
            require_admin(mock_request)
        assert exc.value.status_code == 401


def test_prod_mode_valid_jwt(mock_request):
    with patch("app.auth.settings") as mock_settings, \
         patch("app.auth.id_token.verify_firebase_token") as mock_verify:
        
        mock_settings.is_dev = False
        mock_settings.admin_email_set = {"admin@test.com"}
        mock_settings.gcp_project_id = "test-project"
        mock_request.headers = {"Authorization": "Bearer valid-token"}
        mock_verify.return_value = {"email": "admin@test.com"}
        
        email = require_admin(mock_request)
        assert email == "admin@test.com"
        assert mock_request.state.admin_email == "admin@test.com"


def test_prod_mode_non_admin_email(mock_request):
    with patch("app.auth.settings") as mock_settings, \
         patch("app.auth.id_token.verify_firebase_token") as mock_verify:
        
        mock_settings.is_dev = False
        mock_settings.admin_email_set = {"admin@test.com"}
        mock_settings.gcp_project_id = "test-project"
        mock_request.headers = {"Authorization": "Bearer valid-token"}
        mock_verify.return_value = {"email": "not-admin@test.com"}
        
        with pytest.raises(HTTPException) as exc:
            require_admin(mock_request)
        assert exc.value.status_code == 403


def test_prod_mode_invalid_jwt(mock_request):
    with patch("app.auth.settings") as mock_settings, \
         patch("app.auth.id_token.verify_firebase_token") as mock_verify:
        
        mock_settings.is_dev = False
        mock_request.headers = {"Authorization": "Bearer invalid-token"}
        mock_verify.side_effect = Exception("Invalid token")
        
        with pytest.raises(HTTPException) as exc:
            require_admin(mock_request)
        assert exc.value.status_code == 401
