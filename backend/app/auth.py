import logging
from typing import NamedTuple

from fastapi import Depends, HTTPException, Request
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from .config import settings

logger = logging.getLogger(__name__)

_google_request = google_requests.Request()


class UserIdentity(NamedTuple):
    """A verified reader — any Google account, not just admins.

    This is the identity behind per-account Sous Chef quotas and supporter
    matching. `is_admin` is decided server-side from ADMIN_EMAILS so the
    frontend never has to guess.
    """

    email: str
    uid: str
    is_admin: bool


DEV_USER = UserIdentity(email="dev@local", uid="dev-admin", is_admin=True)


def _dev_bypass(request: Request) -> bool:
    return settings.is_dev and request.headers.get("X-Dev-Admin") == "true"


def _get_token(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    return auth[7:]


def require_admin(request: Request) -> str:
    """FastAPI dependency that verifies the caller is an admin.

    In development mode, accepts the ``X-Dev-Admin: true`` header
    without token verification so the local frontend can bypass auth.

    Returns the admin email address.
    """
    # Dev bypass
    if settings.is_dev and request.headers.get("X-Dev-Admin") == "true":
        request.state.admin_email = "dev@local"
        return "dev@local"

    token = _get_token(request)

    try:
        claims = id_token.verify_firebase_token(token, _google_request, audience=settings.gcp_project_id)
    except Exception:
        # Log the reason server-side; the caller only learns the token was rejected.
        logger.warning("Admin token verification failed", exc_info=True)
        raise HTTPException(status_code=401, detail="Invalid token")

    email: str = claims.get("email", "")
    if email not in settings.admin_email_set:
        raise HTTPException(status_code=403, detail="Not an admin")

    request.state.admin_email = email
    return email


def require_user(request: Request) -> UserIdentity:
    """FastAPI dependency: any signed-in Google account with a verified email.

    Unlike ``require_admin`` this never checks ADMIN_EMAILS — it only proves
    who the caller is. The same ``X-Dev-Admin`` bypass applies in development
    (the local frontend always sends it), so no separate dev wiring is needed.
    """
    if _dev_bypass(request):
        request.state.user = DEV_USER
        return DEV_USER

    token = _get_token(request)

    try:
        claims = id_token.verify_firebase_token(token, _google_request, audience=settings.gcp_project_id)
    except Exception:
        logger.warning("User token verification failed", exc_info=True)
        raise HTTPException(status_code=401, detail="Invalid token")

    email = (claims.get("email") or "").strip().lower()
    if not email or not claims.get("email_verified", False):
        raise HTTPException(status_code=403, detail="A verified email address is required")

    uid = claims.get("sub") or claims.get("user_id") or ""
    if not uid:
        raise HTTPException(status_code=401, detail="Invalid token")

    admin_emails = {e.lower() for e in settings.admin_email_set}
    identity = UserIdentity(email=email, uid=uid, is_admin=email in admin_emails)
    request.state.user = identity
    return identity


def optional_user(request: Request) -> UserIdentity | None:
    """Like ``require_user``, but anonymous callers get ``None`` instead of a 401.

    A caller who does present credentials must present valid ones — a bad
    token is still rejected rather than silently treated as anonymous.
    """
    if _dev_bypass(request):
        return require_user(request)
    if not request.headers.get("Authorization"):
        return None
    return require_user(request)
