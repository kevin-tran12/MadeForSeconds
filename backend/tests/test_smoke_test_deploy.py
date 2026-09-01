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
