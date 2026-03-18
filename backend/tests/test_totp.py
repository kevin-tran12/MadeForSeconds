import pytest
from unittest.mock import MagicMock, patch
import pyotp
from app.totp import create_session_token

def test_totp_status_not_configured(authenticated_client):
    """Returns {enabled: false} when no config exists."""
    with patch("app.routes.totp.get_totp_config", return_value=None):
        response = authenticated_client.get("/api/admin/totp/status")
        assert response.status_code == 200
        assert response.json() == {"enabled": False}

def test_totp_status_configured(authenticated_client):
    """Returns {enabled: true} when config exists."""
    with patch("app.routes.totp.get_totp_config", return_value={"enabled": True, "secret": "ABC"}):
        response = authenticated_client.get("/api/admin/totp/status")
        assert response.status_code == 200
        assert response.json() == {"enabled": True}

def test_totp_setup_returns_secret_and_qr(authenticated_client):
    """Secret is base32, QR is data URI."""
    with patch("app.routes.totp.get_totp_config", return_value=None):
        response = authenticated_client.post("/api/admin/totp/setup")
        assert response.status_code == 200
        assert "secret" in response.json()
        assert "qr_code" in response.json()
        assert response.json()["qr_code"].startswith("data:image/png;base64,")

def test_totp_confirm_setup_valid_code(authenticated_client, mock_db):
    """Persists config, returns session token."""
    secret = pyotp.random_base32()
    totp = pyotp.TOTP(secret)
    code = totp.now()
    
    response = authenticated_client.post("/api/admin/totp/confirm-setup", json={
        "secret": secret,
        "code": code
    })
    assert response.status_code == 200
    assert "token" in response.json()
    # Check mock_db calls via the actual helper functions
    mock_db.collection.assert_any_call("settings")

def test_totp_confirm_setup_invalid_code(authenticated_client):
    """400 on wrong code."""
    secret = pyotp.random_base32()
    response = authenticated_client.post("/api/admin/totp/confirm-setup", json={
        "secret": secret,
        "code": "000000"
    })
    assert response.status_code == 400

def test_totp_verify_valid(authenticated_client):
    """Returns session token."""
    secret = pyotp.random_base32()
    totp = pyotp.TOTP(secret)
    code = totp.now()
    
    with patch("app.routes.totp.get_totp_config", return_value={"enabled": True, "secret": secret}):
        response = authenticated_client.post("/api/admin/totp/verify", json={"code": code})
        assert response.status_code == 200
        assert "token" in response.json()

def test_totp_reset_valid(authenticated_client, mock_db):
    """Clears Firestore config."""
    secret = pyotp.random_base32()
    totp = pyotp.TOTP(secret)
    code = totp.now()
    
    with patch("app.routes.totp.get_totp_config", return_value={"enabled": True, "secret": secret}):
        response = authenticated_client.post("/api/admin/totp/reset", json={"code": code})
        assert response.status_code == 200
        mock_db.collection.return_value.document.return_value.delete.assert_called_once()

def test_totp_session_middleware_dev_bypass():
    """Dev mode skips TOTP check."""
    from app.totp import require_totp_session
    mock_request = MagicMock()
    with patch("app.totp.settings") as mock_settings:
        mock_settings.is_dev = True
        result = require_totp_session(mock_request)
        assert result == "dev@local"

def test_totp_session_middleware_no_setup():
    """Allows access when TOTP not yet configured."""
    from app.totp import require_totp_session
    mock_request = MagicMock()
    with patch("app.totp.settings") as mock_settings, \
         patch("app.totp.get_totp_config", return_value=None):
        mock_settings.is_dev = False
        result = require_totp_session(mock_request)
        assert result == "totp_not_configured"

def test_totp_session_middleware_valid_token():
    """Passes with valid JWT in header."""
    from app.totp import require_totp_session
    mock_request = MagicMock()

    with patch("app.totp.settings") as mock_settings, \
         patch("app.totp.get_totp_config", return_value={"enabled": True}):
        mock_settings.is_dev = False
        mock_settings.subscriber_jwt_secret = "dev-subscriber-secret-change-in-prod"

        # Create the token inside the patch so sign and verify use the same secret
        token = create_session_token("admin@test.com")
        mock_request.headers = {"X-TOTP-Session": token}

        result = require_totp_session(mock_request)
        assert result == "admin@test.com"
