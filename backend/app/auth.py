from fastapi import Depends, HTTPException, Request
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from .config import settings

_google_request = google_requests.Request()


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
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"Invalid token: {exc}")

    email: str = claims.get("email", "")
    if email not in settings.admin_email_set:
        raise HTTPException(status_code=403, detail="Not an admin")

    request.state.admin_email = email
    return email
