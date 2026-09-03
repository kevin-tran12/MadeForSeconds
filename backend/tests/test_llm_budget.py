"""Unit tests for the Sous Chef monthly spend meter (app/services/llm_budget.py)."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.cache import MemoryCache, RedisCache
from app.services import llm_budget as budget


def _usage(**counts):
    base = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
    }
    base.update(counts)
    return SimpleNamespace(**base)


def _settings(is_dev=True, cap=10.0):
    s = MagicMock()
    s.is_dev = is_dev
    s.assistant_monthly_cap_usd = cap
    return s


# ── price table ───────────────────────────────────────────────────────────────

def test_cost_micro_usd_matches_list_prices():
    # $2/MTok x 412 + $0.20/MTok x 3180 + $10/MTok x 221 = $0.003670
    usage = _usage(input_tokens=412, cache_read_input_tokens=3180, output_tokens=221)
    assert budget.cost_micro_usd(usage, "claude-sonnet-5") == 3670


def test_cost_rounds_up_never_down():
    # One Haiku cache-read token is a tenth of a micro-dollar.
    assert budget.cost_micro_usd(_usage(cache_read_input_tokens=1), "claude-haiku-4-5") == 1


def test_cost_accepts_dicts_and_missing_fields_count_zero():
    assert budget.cost_micro_usd({"input_tokens": 100}, "claude-sonnet-5") == 200
    assert budget.cost_micro_usd({"input_tokens": None}, "claude-sonnet-5") == 0


def test_price_table_falls_back_by_family_then_to_sonnet():
    sonnet = budget.PRICES_MICRO_PER_MTOK["claude-sonnet-5"]
    haiku = budget.PRICES_MICRO_PER_MTOK["claude-haiku-4-5"]
    assert budget.price_table("claude-sonnet-5-20260101") is sonnet
    assert budget.price_table("claude-haiku-4-5-20251001") is haiku
    # Unknown ids charge at the dearest known table, so they can only over-count.
    assert budget.price_table("something-else") is sonnet


def test_estimate_micro_uses_chars_per_token():
    # 400 chars is ~100 tokens each way: 100 x $2/MTok + 100 x $10/MTok = $0.0012
    assert budget.estimate_micro(400, 400, "claude-sonnet-5") == 1200


# ── month bookkeeping ─────────────────────────────────────────────────────────

def test_month_key_and_resets_at_are_utc_month_based():
    now = datetime(2026, 12, 15, 23, 30, tzinfo=timezone.utc)
    assert budget.month_key(now) == "llm:spend:2026-12"
    assert budget.resets_at(now) == datetime(2027, 1, 1, tzinfo=timezone.utc)
    september = datetime(2026, 9, 2, tzinfo=timezone.utc)
    assert budget.resets_at(september) == datetime(2026, 10, 1, tzinfo=timezone.utc)


# ── counter semantics ─────────────────────────────────────────────────────────

def test_dev_memory_backend_counts_and_pauses_at_cap():
    with patch("app.services.llm_budget.settings", _settings(is_dev=True, cap=10.0)), \
         patch("app.services.llm_budget.cache", MemoryCache(ttl=60)):
        assert budget.get_month_spend_micro() == 0
        assert budget.add_spend_micro(9_999_999) == 9_999_999
        assert budget.is_paused() is False
        assert budget.add_spend_micro(1) == 10_000_000
        assert budget.is_paused() is True
        summary = budget.summary()
        assert summary["available"] is True and summary["paused"] is True
        assert summary["spent_usd"] == 10.0


def test_prod_memory_backend_fails_closed():
    """Redis unreachable at startup leaves a MemoryCache singleton in production;
    a counter that resets on every cold start must not be trusted with the cap."""
    with patch("app.services.llm_budget.settings", _settings(is_dev=False)), \
         patch("app.services.llm_budget.cache", MemoryCache(ttl=60)):
        with pytest.raises(budget.BudgetUnavailable):
            budget.get_month_spend_micro()
        with pytest.raises(budget.BudgetUnavailable):
            budget.add_spend_micro(1)
        assert budget.summary()["available"] is False


def test_prod_redis_error_fails_closed():
    redis = MagicMock(spec=RedisCache)
    redis.get_counter.return_value = None
    redis.incr_by_with_ttl.return_value = None
    with patch("app.services.llm_budget.settings", _settings(is_dev=False)), \
         patch("app.services.llm_budget.cache", redis):
        with pytest.raises(budget.BudgetUnavailable):
            budget.get_month_spend_micro()
        with pytest.raises(budget.BudgetUnavailable):
            budget.add_spend_micro(5)


def test_add_spend_uses_month_key_and_40_day_ttl():
    redis = MagicMock(spec=RedisCache)
    redis.incr_by_with_ttl.return_value = 42
    now = datetime(2026, 9, 2, tzinfo=timezone.utc)
    with patch("app.services.llm_budget.settings", _settings(is_dev=False)), \
         patch("app.services.llm_budget.cache", redis):
        assert budget.add_spend_micro(42, now) == 42
    redis.incr_by_with_ttl.assert_called_once_with("llm:spend:2026-09", 42, 40 * 86_400)


def test_negative_spend_is_rejected():
    with pytest.raises(ValueError):
        budget.add_spend_micro(-1)
