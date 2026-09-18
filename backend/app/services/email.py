"""Outbound transactional email via Resend.

Falls back to logging the content in dev (or whenever resend_api_key isn't
set) instead of sending, same as the cancellation-email behavior this was
extracted from.
"""

import logging

import httpx

from ..config import settings

logger = logging.getLogger(__name__)


async def send_email(to: str, subject: str, html: str) -> None:
    if not settings.resend_api_key:
        logger.info("[DEV] Email to %s: %s\n%s", to, subject, html)
        return

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {settings.resend_api_key}"},
            json={
                "from": settings.resend_from,
                "to": [to],
                "subject": subject,
                "html": html,
            },
            timeout=10.0,
        )

    # Sending stays best-effort — callers treat email as non-fatal (see
    # subscriptions._alert) — but a rejection must not pass silently. Resend
    # answers 403 for an unverified `from` domain, which previously looked
    # identical to success from here.
    if resp.status_code >= 400:
        logger.error(
            "Resend rejected email to %s (%s): %s %s",
            to,
            subject,
            resp.status_code,
            resp.text,
        )
