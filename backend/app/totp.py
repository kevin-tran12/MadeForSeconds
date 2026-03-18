"""TOTP (Google Authenticator) 2FA for the expenses section.

Stores the TOTP secret in Firestore at ``settings/totp``.
Dev mode bypasses TOTP entirely.
"""

import base64
import logging
from datetime import datetime, timedelta, timezone
from io import BytesIO

import jwt
import pyotp
import qrcode
from fastapi import HTTPException, Request

from .config import settings
from .firestore import get_db

logger = logging.getLogger(__name__)

_TOTP_DOC_PATH = "settings"
_TOTP_DOC_ID = "totp"
_SESSION_EXPIRY_HOURS = 12


# ── Firestore ────────────────────────────────────────────────────────────────


def get_totp_config() -> dict | None:
    """Read the TOTP config from Firestore. Returns None if not set up."""
    db = get_db()
    doc = db.collection(_TOTP_DOC_PATH).document(_TOTP_DOC_ID).get()
    if doc.exists:
        return doc.to_dict()
    return None


def save_totp_config(secret: str) -> None:
    """Persist a verified TOTP secret to Firestore."""
    db = get_db()
    db.collection(_TOTP_DOC_PATH).document(_TOTP_DOC_ID).set({
        "secret": secret,
        "enabled": True,
        "created_at": datetime.now(timezone.utc),
    })


def clear_totp_config() -> None:
    """Remove the TOTP config from Firestore."""
    db = get_db()
    db.collection(_TOTP_DOC_PATH).document(_TOTP_DOC_ID).delete()


# ── TOTP operations ─────────────────────────────────────────────────────────


def generate_secret() -> str:
    """Generate a new base32 TOTP secret."""
    return pyotp.random_base32()


def generate_qr_data_uri(secret: str, email: str) -> str:
    """Build a provisioning URI and render it as a base64 QR code PNG."""
    totp = pyotp.TOTP(secret)
    uri = totp.provisioning_uri(name=email, issuer_name="MadeForSeconds")

    img = qrcode.make(uri)
    buf = BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    return f"data:image/png;base64,{b64}"


def verify_code(secret: str, code: str) -> bool:
    """Verify a 6-digit TOTP code. Allows ±30s tolerance."""
    totp = pyotp.TOTP(secret)
    return totp.verify(code, valid_window=1)


# ── Session JWT ──────────────────────────────────────────────────────────────


def create_session_token(email: str) -> str:
    """Create a TOTP session JWT valid for 12 hours."""
    now = datetime.now(timezone.utc)
    payload = {
        "email": email,
        "type": "totp_session",
        "iat": now,
        "exp": now + timedelta(hours=_SESSION_EXPIRY_HOURS),
    }
    return jwt.encode(payload, settings.subscriber_jwt_secret, algorithm="HS256")


def verify_session_token(token: str) -> str:
    """Verify a TOTP session JWT. Returns email on success, raises on failure."""
    try:
        payload = jwt.decode(
            token,
            settings.subscriber_jwt_secret,
            algorithms=["HS256"],
        )
        if payload.get("type") != "totp_session":
            raise HTTPException(status_code=403, detail="TOTP verification required")
        email = payload.get("email")
        if not email:
            raise HTTPException(status_code=403, detail="TOTP verification required")
        return email
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=403, detail="TOTP session expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=403, detail="TOTP verification required")


# ── FastAPI dependency ───────────────────────────────────────────────────────


def require_totp_session(request: Request) -> str:
    """FastAPI dependency: verify TOTP session from X-TOTP-Session header.

    - Dev mode: bypasses entirely.
    - TOTP not configured: allows access (don't lock out before setup).
    - Otherwise: requires valid session JWT.
    """
    if settings.is_dev:
        return "dev@local"

    config = get_totp_config()
    if not config or not config.get("enabled"):
        return "totp_not_configured"

    token = request.headers.get("X-TOTP-Session", "")
    if not token:
        raise HTTPException(status_code=403, detail="TOTP verification required")

    return verify_session_token(token)
