"""Short-lived signed tokens for email-confirmed supporter actions.

Two token types share one signing secret and one shape:

- ``cancel`` — confirms a recurring-donation cancellation (sent by
  /cancel-request, consumed by /cancel-confirm).
- ``link``   — proves control of the email a donation was made with, so a
  signed-in reader can attach that donation to their Google account
  (sent by /link-request, consumed by /link-confirm).

The ``type`` claim is checked on verification, so a cancel token can never be
replayed as a link token or vice versa.
"""

import logging
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import HTTPException

from .config import settings

logger = logging.getLogger(__name__)

TOKEN_TTL = timedelta(hours=1)


def _create_token(email: str, type_: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {"email": email, "type": type_, "iat": now, "exp": now + TOKEN_TTL}
    return jwt.encode(payload, settings.subscriber_jwt_secret, algorithm="HS256")


def _verify_token(token: str, type_: str, *, what: str) -> str:
    """Verify a token of the given type and return its email.

    Raises HTTPException(400) with a message naming ``what`` ("Cancel link",
    "Link") on expiry or tampering, so the two flows keep distinct copy.
    """
    try:
        payload = jwt.decode(token, settings.subscriber_jwt_secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=400, detail=f"{what} has expired. Please request a new one.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=400, detail=f"Invalid {what.lower()}")
    if payload.get("type") != type_:
        raise HTTPException(status_code=400, detail="Invalid token type")
    email = payload.get("email")
    if not email:
        raise HTTPException(status_code=400, detail="Invalid token")
    return email


def create_cancel_token(email: str) -> str:
    """Create a short-lived signed token for subscription cancellation."""
    return _create_token(email, "cancel")


def verify_cancel_token(token: str) -> str:
    """Verify a cancel token and return the email. Raises HTTPException on failure."""
    return _verify_token(token, "cancel", what="Cancel link")


def create_link_token(email: str) -> str:
    """Create a short-lived signed token for linking a donation to an account."""
    return _create_token(email, "link")


def verify_link_token(token: str) -> str:
    """Verify a link token and return the email. Raises HTTPException on failure."""
    return _verify_token(token, "link", what="Link")
