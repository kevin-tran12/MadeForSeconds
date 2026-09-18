"""Tests for app/services/email.py.

Resend is never called — httpx is mocked at the service layer. These cover the
two things that were previously unguarded: the sender is configuration, not a
hardcoded domain, and a rejection from Resend is logged rather than swallowed.
"""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import email as email_service


@pytest.mark.asyncio
async def test_dev_fallback_logs_instead_of_sending(caplog):
    """With no API key the service logs the message and never touches httpx."""
    with patch("app.services.email.settings") as s, \
         patch("app.services.email.httpx.AsyncClient.post") as mock_post:
        s.resend_api_key = ""
        with caplog.at_level(logging.INFO, logger="app.services.email"):
            await email_service.send_email("someone@example.com", "Subject", "<p>Body</p>")

    mock_post.assert_not_called()
    # The recipient is redacted by the log-redaction filter (PR #80) before it
    # reaches a handler — asserting on the redacted form keeps that guarantee.
    assert "[DEV] Email to [redacted-email]" in caplog.text


@pytest.mark.asyncio
async def test_from_header_tracks_the_configured_sender():
    """The sender comes from settings, not a hardcoded domain."""
    with patch("app.services.email.settings") as s, \
         patch("app.services.email.httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        s.resend_api_key = "fake_key"
        s.resend_from = "MadeForSeconds <hello@example.test>"
        mock_post.return_value = MagicMock(status_code=200)

        await email_service.send_email("someone@example.com", "Subject", "<p>Body</p>")

    payload = mock_post.call_args.kwargs["json"]
    assert payload["from"] == "MadeForSeconds <hello@example.test>"
    assert payload["to"] == ["someone@example.com"]


@pytest.mark.asyncio
async def test_a_rejection_is_logged_not_swallowed(caplog):
    """Resend answers 403 for an unverified `from` domain — it must not pass silently."""
    with patch("app.services.email.settings") as s, \
         patch("app.services.email.httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        s.resend_api_key = "fake_key"
        s.resend_from = "MadeForSeconds <noreply@unverified.test>"
        mock_post.return_value = MagicMock(
            status_code=403,
            text='{"message":"The domain is not verified."}',
        )

        with caplog.at_level(logging.ERROR, logger="app.services.email"):
            await email_service.send_email("someone@example.com", "Subject", "<p>Body</p>")

    assert "Resend rejected email to [redacted-email]" in caplog.text
    assert "403" in caplog.text
    assert "not verified" in caplog.text


@pytest.mark.asyncio
async def test_a_successful_send_logs_no_error(caplog):
    """The happy path stays quiet."""
    with patch("app.services.email.settings") as s, \
         patch("app.services.email.httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        s.resend_api_key = "fake_key"
        s.resend_from = "MadeForSeconds <hello@example.test>"
        mock_post.return_value = MagicMock(status_code=200)

        with caplog.at_level(logging.ERROR, logger="app.services.email"):
            await email_service.send_email("someone@example.com", "Subject", "<p>Body</p>")

    assert caplog.text == ""
