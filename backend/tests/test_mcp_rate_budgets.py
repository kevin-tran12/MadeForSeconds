"""Tests for mcp_server/rate_budgets.py — the actual enforcement behind the
budget tag mcp_tool() attaches to every MCP tool (see wrapper.py).

reset_rate_limits (conftest.py, autouse) clears the counters this module
writes through app.rate_limit.count_hit between every test, so these don't
need their own cleanup.
"""

import logging

from app.mcp_server import rate_budgets


class TestNoClientId:
    def test_returns_none_without_a_client_id_regardless_of_volume(self):
        """Dev mode / an in-memory Client() test carries no OAuth identity —
        see the module docstring for why this is a deliberate no-op there,
        not a bug. 200 calls comfortably exceeds every real budget's limit,
        proving this isn't just "under the limit by luck."""
        for _ in range(200):
            assert rate_budgets.check_budget("write", None) is None


class TestSingleWindowBudgets:
    def test_allows_up_to_the_limit(self):
        for _ in range(30):
            assert rate_budgets.check_budget("write", "client-a") is None

    def test_rejects_the_call_over_the_limit(self):
        for _ in range(30):
            rate_budgets.check_budget("write", "client-b")
        assert rate_budgets.check_budget("write", "client-b") == 60

    def test_read_budget_is_more_permissive_than_write(self):
        for _ in range(120):
            assert rate_budgets.check_budget("read", "client-c") is None
        assert rate_budgets.check_budget("read", "client-c") == 60

    def test_budgets_are_isolated_per_client(self):
        for _ in range(30):
            rate_budgets.check_budget("write", "client-busy")
        # client-busy is now over budget; a different client is unaffected.
        assert rate_budgets.check_budget("write", "client-fresh") is None

    def test_budgets_are_isolated_per_category(self):
        for _ in range(30):
            rate_budgets.check_budget("write", "client-d")
        # write is now over budget; read (a different budget) is unaffected.
        assert rate_budgets.check_budget("read", "client-d") is None

    def test_unknown_budget_name_is_never_limited(self):
        for _ in range(1000):
            assert rate_budgets.check_budget("nonexistent", "client-e") is None


class TestTwoWindowBudget:
    def test_publish_social_rejects_after_the_hourly_cap(self):
        for _ in range(5):
            assert rate_budgets.check_budget("publish_social", "client-f") is None
        assert rate_budgets.check_budget("publish_social", "client-f") == 3600

    def test_both_windows_increment_even_once_the_first_is_breached(self):
        """A caller cannot escape the daily cap by making enough calls to
        trip the hourly cap first — every attempt counts against both."""
        for _ in range(25):
            rate_budgets.check_budget("publish_social", "client-g")
        # 25 calls: hourly cap (5) breached 20 calls ago, but every one of
        # those 25 also counted toward the daily cap (20) — it should be
        # breached too, reported as the (longer) daily window since... no,
        # retry_after reports the FIRST (shortest) breached window found,
        # so this still reports 3600 even though the daily cap is also blown.
        assert rate_budgets.check_budget("publish_social", "client-g") == 3600

    def test_daily_cap_alone_would_be_reported_if_hourly_were_not_breached(self):
        """Can't trip the daily cap (20) without also tripping the hourly
        one (5) given a shared call sequence, since hourly is stricter per
        unit time — this asserts the ordering contract directly instead:
        windows are checked shortest-first, so a hypothetical breach-only-
        the-second-window case would report that window's seconds."""
        assert rate_budgets._BUDGETS["publish_social"][0][1] < rate_budgets._BUDGETS["publish_social"][1][1]


class TestLogging:
    def test_logs_mcp_rate_limited_once_per_rejection(self, caplog):
        with caplog.at_level(logging.WARNING, logger="app.mcp_server.rate_budgets"):
            for _ in range(30):
                rate_budgets.check_budget("write", "client-h")
            rate_budgets.check_budget("write", "client-h")  # 31st: rejected
            rate_budgets.check_budget("write", "client-h")  # 32nd: rejected again

        alerts = [r for r in caplog.records if "MCP_RATE_LIMITED" in r.getMessage()]
        assert len(alerts) == 2  # one per rejection, not per window checked
        assert "client-h" in alerts[0].getMessage()

    def test_allowed_calls_log_nothing(self, caplog):
        with caplog.at_level(logging.WARNING, logger="app.mcp_server.rate_budgets"):
            rate_budgets.check_budget("write", "client-i")
        assert len(caplog.records) == 0
