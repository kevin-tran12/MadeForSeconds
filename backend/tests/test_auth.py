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


# ── require_user / optional_user (any verified Google account) ───────────────

from app.auth import DEV_USER, UserIdentity, optional_user, require_user  # noqa: E402


def _prod_settings(mock_settings):
    mock_settings.is_dev = False
    mock_settings.admin_email_set = {"admin@test.com"}
    mock_settings.gcp_project_id = "test-project"


def test_require_user_dev_bypass(mock_request):
    with patch("app.auth.settings") as mock_settings:
        mock_settings.is_dev = True
        mock_request.headers = {"X-Dev-Admin": "true"}
        assert require_user(mock_request) == DEV_USER
        assert mock_request.state.user == DEV_USER


def test_require_user_valid_token_lowercases_email(mock_request):
    with patch("app.auth.settings") as mock_settings, \
         patch("app.auth.id_token.verify_firebase_token") as mock_verify:
        _prod_settings(mock_settings)
        mock_request.headers = {"Authorization": "Bearer valid-token"}
        mock_verify.return_value = {"email": " Reader@Example.com ", "email_verified": True, "sub": "uid-1"}

        identity = require_user(mock_request)
        assert identity == UserIdentity(email="reader@example.com", uid="uid-1", is_admin=False)
        assert mock_request.state.user == identity


def test_require_user_marks_admin_emails(mock_request):
    with patch("app.auth.settings") as mock_settings, \
         patch("app.auth.id_token.verify_firebase_token") as mock_verify:
        _prod_settings(mock_settings)
        mock_request.headers = {"Authorization": "Bearer valid-token"}
        mock_verify.return_value = {"email": "Admin@Test.com", "email_verified": True, "sub": "uid-a"}
        assert require_user(mock_request).is_admin is True


def test_require_user_rejects_unverified_email(mock_request):
    with patch("app.auth.settings") as mock_settings, \
         patch("app.auth.id_token.verify_firebase_token") as mock_verify:
        _prod_settings(mock_settings)
        mock_request.headers = {"Authorization": "Bearer valid-token"}
        mock_verify.return_value = {"email": "reader@example.com", "email_verified": False, "sub": "uid-1"}
        with pytest.raises(HTTPException) as exc:
            require_user(mock_request)
        assert exc.value.status_code == 403


def test_require_user_rejects_missing_email_or_uid(mock_request):
    with patch("app.auth.settings") as mock_settings, \
         patch("app.auth.id_token.verify_firebase_token") as mock_verify:
        _prod_settings(mock_settings)
        mock_request.headers = {"Authorization": "Bearer valid-token"}
        mock_verify.return_value = {"email_verified": True, "sub": "uid-1"}
        with pytest.raises(HTTPException) as exc:
            require_user(mock_request)
        assert exc.value.status_code == 403
        mock_verify.return_value = {"email": "reader@example.com", "email_verified": True}
        with pytest.raises(HTTPException) as exc:
            require_user(mock_request)
        assert exc.value.status_code == 401


def test_require_user_invalid_token(mock_request):
    with patch("app.auth.settings") as mock_settings, \
         patch("app.auth.id_token.verify_firebase_token") as mock_verify:
        _prod_settings(mock_settings)
        mock_request.headers = {"Authorization": "Bearer bad"}
        mock_verify.side_effect = Exception("Invalid token")
        with pytest.raises(HTTPException) as exc:
            require_user(mock_request)
        assert exc.value.status_code == 401


def test_optional_user_anonymous_is_none(mock_request):
    with patch("app.auth.settings") as mock_settings:
        _prod_settings(mock_settings)
        mock_request.headers = {}
        assert optional_user(mock_request) is None


def test_optional_user_with_token_returns_identity(mock_request):
    with patch("app.auth.settings") as mock_settings, \
         patch("app.auth.id_token.verify_firebase_token") as mock_verify:
        _prod_settings(mock_settings)
        mock_request.headers = {"Authorization": "Bearer valid-token"}
        mock_verify.return_value = {"email": "reader@example.com", "email_verified": True, "sub": "uid-1"}
        assert optional_user(mock_request).uid == "uid-1"


def test_optional_user_bad_token_is_still_rejected(mock_request):
    with patch("app.auth.settings") as mock_settings, \
         patch("app.auth.id_token.verify_firebase_token") as mock_verify:
        _prod_settings(mock_settings)
        mock_request.headers = {"Authorization": "Bearer bad"}
        mock_verify.side_effect = Exception("Invalid token")
        with pytest.raises(HTTPException) as exc:
            optional_user(mock_request)
        assert exc.value.status_code == 401
