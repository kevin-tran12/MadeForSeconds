"""Internal endpoints invoked by infrastructure (Cloud Scheduler), not end users.

The Cloud Run service is publicly invokable, so these routes authenticate the
caller at the application layer by verifying a Google-signed OIDC ID token: it
must be signed by Google, carry the authorized invoker service account's email,
and (when configured) match the expected audience. Anything else → 403.
"""

import logging

from fastapi import APIRouter, HTTPException, Request
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from ..config import settings
from ..services import instagram

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/internal")

_google_request = google_requests.Request()


def _verify_oidc_caller(request: Request) -> None:
    """Authorize the caller via its Google OIDC token (no-op in dev)."""
    if settings.is_dev:
        return

    invoker = settings.instagram_refresh_invoker_email
    if not invoker:
        # Fail closed: with no authorized invoker configured, nobody may call this.
        raise HTTPException(status_code=403, detail="Refresh endpoint is not configured")

    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = auth[7:]

    try:
        claims = id_token.verify_oauth2_token(
            token,
            _google_request,
            audience=settings.instagram_refresh_audience or None,
        )
    except Exception as exc:
        raise HTTPException(status_code=403, detail=f"Invalid OIDC token: {exc}")

    if not claims.get("email_verified") or claims.get("email") != invoker:
        raise HTTPException(status_code=403, detail="Caller not authorized")


@router.post("/instagram/refresh-token")
def refresh_instagram_token(request: Request) -> dict:
    """Rotate the Instagram long-lived token. Invoked on a schedule by Cloud Scheduler."""
    _verify_oidc_caller(request)
    result = instagram.refresh_token()
    logger.info("Instagram token refresh invoked: refreshed=%s", result.get("refreshed"))
    return result
