"""Internal endpoints invoked by infrastructure (Cloud Scheduler), not end users.

The Cloud Run service is publicly invokable, so these routes authenticate the
caller at the application layer by verifying a Google-signed OIDC ID token: it
must be signed by Google, carry the authorized invoker service account's email,
and (when configured) match the expected audience. Anything else → 403.
"""

import logging

from fastapi import APIRouter, HTTPException, Request
from google.api_core.exceptions import GoogleAPICallError
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from ..config import settings
from ..firestore import get_db
from ..services import instagram, social, usage_stats
from ..services.email import send_email

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/internal")

_google_request = google_requests.Request()


def _verify_oidc_caller(request: Request, audience: str) -> None:
    """Authorize the caller via its Google OIDC token (no-op in dev).

    All internal endpoints are invoked by the same backend service account
    (Cloud Scheduler mints an OIDC token as this SA — see terraform/scheduler.tf),
    so the invoker-email check is shared; only the expected audience differs
    per endpoint (it's the endpoint's own URL, per OIDC best practice).
    """
    if settings.is_dev:
        return

    invoker = settings.instagram_refresh_invoker_email
    if not invoker:
        # Fail closed: with no authorized invoker configured, nobody may call this.
        raise HTTPException(status_code=403, detail="Internal endpoint is not configured")

    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = auth[7:]

    if not audience:
        raise HTTPException(status_code=503, detail="Endpoint audience not configured")

    try:
        claims = id_token.verify_oauth2_token(token, _google_request, audience=audience)
    except Exception:
        logger.warning("Internal OIDC token verification failed", exc_info=True)
        raise HTTPException(status_code=403, detail="Invalid OIDC token")

    if not claims.get("email_verified") or claims.get("email") != invoker:
        raise HTTPException(status_code=403, detail="Caller not authorized")


@router.post("/instagram/refresh-token")
def refresh_instagram_token(request: Request) -> dict:
    """Rotate the Instagram long-lived token. Invoked on a schedule by Cloud Scheduler."""
    _verify_oidc_caller(request, settings.instagram_refresh_audience)
    result = instagram.refresh_token()
    logger.info("Instagram token refresh invoked: refreshed=%s", result.get("refreshed"))
    return result


@router.post("/social/refresh-tokens")
def refresh_social_tokens(request: Request) -> dict:
    """Rotate every configured social platform's token (Instagram today).

    Invoked twice a month by Cloud Scheduler (social-token-refresh). Each
    platform is attempted independently; any failure logs
    SOCIAL_REFRESH_FAILED (alerted on) and turns the response into a 500 so
    the Scheduler attempt is recorded as failed and retried.
    """
    _verify_oidc_caller(request, settings.social_refresh_audience or settings.instagram_refresh_audience)
    result = social.refresh_all(get_db())
    logger.info("Social token refresh invoked: failed=%s", result["failed"])
    if result["failed"]:
        raise HTTPException(status_code=500, detail={"code": "social_refresh_failed", **result})
    return result


@router.post("/usage/weekly-report")
async def weekly_usage_report(request: Request) -> dict:
    """Email a weekly aggregate usage summary. Invoked on a schedule by Cloud Scheduler."""
    _verify_oidc_caller(request, settings.usage_report_audience)
    try:
        summary = usage_stats.get_weekly_summary()
    except GoogleAPICallError:
        # Best-effort internal cron job — a transient Cloud Logging error (e.g.
        # quota exhaustion) shouldn't 500 and trigger a Cloud Scheduler retry
        # storm against an already-exhausted read quota.
        logger.warning("Weekly usage report: failed to read Cloud Logging", exc_info=True)
        return {"sent": False, "reason": "log-read-failed"}

    paths_html = "".join(f"<li>{p['path']} — {p['count']}</li>" for p in summary["top_paths"]) or "<li>(no requests)</li>"
    html = f"""
        <p>Backend traffic for the past {summary["window_days"]} days:</p>
        <ul>
            <li>Total requests: {summary["total_requests"]}</li>
            <li>Distinct visitors: {summary["distinct_visitors"]}</li>
            <li>Errors: {summary["error_count"]}</li>
        </ul>
        <p>Top paths:</p>
        <ul>{paths_html}</ul>
    """
    await send_email(settings.alert_email, "Weekly site usage — MadeForSeconds", html)
    logger.info(
        "Weekly usage report sent: requests=%s visitors=%s errors=%s",
        summary["total_requests"],
        summary["distinct_visitors"],
        summary["error_count"],
    )
    return summary
