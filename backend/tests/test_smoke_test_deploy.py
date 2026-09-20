"""Unit tests for scripts/smoke_test_deploy.py's cold-start retry helper.

The rest of the script (HTTP calls against a real Cloud Run URL) is only
exercised by actually running it, per its own docstring — what's tested
here is the one piece of logic a live run can't cheaply prove wasn't a
fluke: _get_tolerating_cold_start actually retries through a timeout
instead of failing on the first one, and still fails loudly once every
attempt is exhausted.
"""

import sys
import urllib.error
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


@pytest.fixture
def smoke(monkeypatch):
    import smoke_test_deploy as smoke

    monkeypatch.setattr(smoke.time, "sleep", lambda s: None)  # no real waiting between retries
    return smoke


def test_succeeds_immediately_without_retrying(smoke):
    with patch.object(smoke, "_get", return_value=(200, b'{"status":"ok"}')) as mock_get:
        result = smoke._get_tolerating_cold_start("https://example.test/api/health")
    assert result == (200, b'{"status":"ok"}')
    mock_get.assert_called_once()


def test_retries_through_a_timeout_then_succeeds(smoke):
    with patch.object(
        smoke, "_get", side_effect=[TimeoutError("cold"), TimeoutError("cold"), (200, b"{}")]
    ) as mock_get:
        result = smoke._get_tolerating_cold_start("https://example.test/api/health", attempts=4)
    assert result == (200, b"{}")
    assert mock_get.call_count == 3


def test_raises_the_last_error_once_every_attempt_is_exhausted(smoke):
    with patch.object(smoke, "_get", side_effect=TimeoutError("still cold")) as mock_get:
        with pytest.raises(TimeoutError, match="still cold"):
            smoke._get_tolerating_cold_start("https://example.test/api/health", attempts=3)
    assert mock_get.call_count == 3


def test_urlerror_is_also_retried_not_just_timeout(smoke):
    with patch.object(
        smoke, "_get", side_effect=[urllib.error.URLError("connection refused"), (200, b"{}")]
    ) as mock_get:
        result = smoke._get_tolerating_cold_start("https://example.test/api/health", attempts=3)
    assert result == (200, b"{}")
    assert mock_get.call_count == 2


# ── _check_mcp_requires_auth (S9) ─────────────────────────────────────────────
#
# Same rationale as the cold-start retry tests above: a live run only ever
# proves the check passed against one real revision at one moment — these
# prove the assertion itself is correct by feeding it the two failure shapes
# a compliant vs. a broken /mcp mount would actually produce.

def test_passes_on_a_401_with_resource_metadata_in_the_challenge(smoke):
    headers = {"WWW-Authenticate": 'Bearer error="invalid_token", resource_metadata="https://x/.well-known/oauth-protected-resource/mcp"'}
    with patch.object(smoke, "_post_json", return_value=(401, b"", headers)):
        smoke._check_mcp_requires_auth("https://example.test")  # must not raise


def test_fails_on_a_401_missing_resource_metadata(smoke):
    """A 401 alone isn't enough — a client can't discover WorkOS AuthKit
    without the resource_metadata pointer in the challenge."""
    with patch.object(smoke, "_post_json", return_value=(401, b"", {"WWW-Authenticate": "Bearer"})):
        with pytest.raises(smoke.SmokeTestFailure):
            smoke._check_mcp_requires_auth("https://example.test")


def test_fails_when_the_endpoint_does_not_require_auth_at_all(smoke):
    with patch.object(smoke, "_post_json", return_value=(200, b"{}", {})):
        with pytest.raises(smoke.SmokeTestFailure):
            smoke._check_mcp_requires_auth("https://example.test")


# ── _post_json header case-sensitivity (regression) ───────────────────────────
#
# Caught for real against a live Cloud Run candidate revision: an earlier
# version of _post_json converted the response headers with dict(resp.headers),
# which silently discards email.message.Message's native case-insensitive
# .get() — Cloud Run's front end returned the challenge as a lowercased
# `www-authenticate` header, and the exact-case lookup in
# _check_mcp_requires_auth always found nothing, failing every deploy at this
# check regardless of whether WorkOS's challenge was actually correct. This
# mocks urlopen directly (not _post_json, which the tests above already do)
# so it exercises the real header-handling code the bug lived in.

def test_post_json_reads_a_lowercased_header_case_insensitively(smoke):
    from email.message import Message
    from unittest.mock import MagicMock

    fake_headers = Message()
    fake_headers["www-authenticate"] = 'Bearer resource_metadata="https://x/.well-known/oauth-protected-resource/mcp"'

    fake_resp = MagicMock()
    fake_resp.status = 401
    fake_resp.read.return_value = b""
    fake_resp.headers = fake_headers
    fake_resp.__enter__.return_value = fake_resp
    fake_resp.__exit__.return_value = False

    with patch.object(smoke.urllib.request, "urlopen", return_value=fake_resp):
        status, _, headers = smoke._post_json("https://example.test/mcp", {})

    assert status == 401
    # The exact casing this script's own check code looks up by — this is
    # the precise line that returned "" before the fix.
    assert "resource_metadata" in headers.get("WWW-Authenticate", "")
