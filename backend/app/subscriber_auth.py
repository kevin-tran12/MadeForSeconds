import logging
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import HTTPException

from .config import settings

logger = logging.getLogger(__name__)


def create_cancel_token(email: str) -> str:
    """Create a short-lived signed token for subscription cancellation."""
    now = datetime.now(timezone.utc)
    payload = {
        "email": email,
        "type": "cancel",
        "iat": now,
        "exp": now + timedelta(hours=1),
    }
    return jwt.encode(payload, settings.subscriber_jwt_secret, algorithm="HS256")


def verify_cancel_token(token: str) -> str:
    """Verify a cancel token and return the email. Raises HTTPException on failure."""
    try:
        payload = jwt.decode(
            token,
            settings.subscriber_jwt_secret,
            algorithms=["HS256"],
        )
        if payload.get("type") != "cancel":
            raise HTTPException(status_code=400, detail="Invalid token type")
        email = payload.get("email")
        if not email:
            raise HTTPException(status_code=400, detail="Invalid token")
        return email
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=400, detail="Cancel link has expired. Please request a new one.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=400, detail="Invalid cancel link")
