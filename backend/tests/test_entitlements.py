"""Unit tests for Sous Chef entitlements (app/services/entitlements.py)."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.cache import cache
from app.services import entitlements as ent

NOW = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)
EMAIL = "reader@example.com"
UID = "uid-reader"


# A tiny Firestore stand-in that honours the where(filter=FieldFilter(...))
# equality the service issues, so the uid-then-email lookup order is real.
class _Query:
    def __init__(self, rows):
        self.rows = rows

    def where(self, filter=None, **_):
        return _Query([r for r in self.rows if r.get(filter.field_path) == filter.value])

    def limit(self, n):
        return _Query(self.rows[:n])

    def stream(self):
        for row in self.rows:
            doc = MagicMock()
            doc.to_dict.return_value = dict(row)
            yield doc


class _Db:
    def __init__(self, **collections):
        self.collections = collections
        self.calls = 0

    def collection(self, name):
        self.calls += 1
        return _Query(self.collections.get(name, []))


@pytest.fixture(autouse=True)
def _fresh_cache():
    cache.clear()
    if hasattr(cache, "_counters"):
        cache._counters.clear()
    ent._fallback._counters.clear()
    yield
    cache.clear()


def _settings(free=5, day=50, month=400):
    s = MagicMock()
    s.assistant_free_daily_quota = free
    s.assistant_supporter_daily_quota = day
    s.assistant_supporter_monthly_quota = month
    return s


# ── supporter lookup ──────────────────────────────────────────────────────────

def test_active_subscriber_by_email_is_supporter():
    db = _Db(subscribers=[{"email": EMAIL, "status": "active"}])
    assert ent.is_supporter(db, EMAIL, UID, NOW) is True


def test_canceled_subscriber_is_not_supporter():
    db = _Db(subscribers=[{"email": EMAIL, "status": "canceled"}])
    assert ent.is_supporter(db, EMAIL, UID, NOW) is False


def test_uid_link_wins_over_a_different_checkout_email():
    db = _Db(subscribers=[{"email": "other@example.com", "uid": UID, "status": "active"}])
    assert ent.is_supporter(db, EMAIL, UID, NOW) is True


def test_first_donation_uses_created_at_when_last_donated_at_missing():
    db = _Db(donations=[{"email": EMAIL, "created_at": NOW - timedelta(days=10)}])
    assert ent.is_supporter(db, EMAIL, UID, NOW) is True


def test_old_donation_is_not_supporter():
    db = _Db(donations=[{"email": EMAIL, "last_donated_at": NOW - timedelta(days=31)}])
    assert ent.is_supporter(db, EMAIL, UID, NOW) is False


def test_supporter_lookup_is_cached_for_five_minutes():
    db = _Db(subscribers=[{"email": EMAIL, "status": "active"}])
    assert ent.is_supporter(db, EMAIL, UID, NOW) is True
    first = db.calls
    assert ent.is_supporter(db, EMAIL, UID, NOW + timedelta(seconds=299)) is True
    assert db.calls == first  # served from cache
    ent.is_supporter(db, EMAIL, UID, NOW + timedelta(seconds=301))
    assert db.calls > first  # re-queried after the TTL


def test_supporter_cache_key_holds_no_raw_email():
    if not hasattr(cache, "_store"):
        pytest.skip("inspects the in-memory cache store")
    ent.is_supporter(_Db(), EMAIL, UID, NOW)
    keys = list(cache._store.keys())
    assert keys and all(EMAIL not in k for k in keys)


# ── quota keys and limits ─────────────────────────────────────────────────────

def test_quota_keys_hash_the_email_and_are_stable():
    key = ent.day_key(EMAIL, NOW.date())
    assert EMAIL not in key
    assert key == ent.day_key(EMAIL, NOW.date())
    assert key.endswith(":2026-09-02")
    assert ent.month_key(EMAIL, NOW).endswith(":2026-09")


def test_free_reader_limits():
    with patch("app.services.entitlements.settings", _settings()):
        e = ent.peek_entitlement(_Db(), EMAIL, UID, NOW)
    assert (e.supporter, e.day_limit, e.month_limit, e.remaining) == (False, 5, None, 5)
    assert e.to_dict()["month"] is None
    assert e.resets_at == datetime(2026, 9, 3, tzinfo=timezone.utc)


def test_supporter_limits():
    db = _Db(subscribers=[{"email": EMAIL, "status": "active"}])
    with patch("app.services.entitlements.settings", _settings()):
        e = ent.peek_entitlement(db, EMAIL, UID, NOW)
    assert (e.supporter, e.day_limit, e.month_limit, e.remaining) == (True, 50, 400, 50)
    assert e.to_dict()["month"] == {"limit": 400, "used": 0}


def test_consume_and_refund_roundtrip_both_counters():
    db = _Db(subscribers=[{"email": EMAIL, "status": "active"}])
    with patch("app.services.entitlements.settings", _settings()):
        e = ent.peek_entitlement(db, EMAIL, UID, NOW)
        e = ent.consume_quota(e, NOW)
        e = ent.consume_quota(e, NOW)
        assert (e.day_used, e.month_used, e.remaining) == (2, 2, 48)
        ent.refund_quota(e, NOW)
        again = ent.peek_entitlement(db, EMAIL, UID, NOW)
    assert (again.day_used, again.month_used) == (1, 1)


def test_month_ceiling_blocks_before_the_day_limit():
    e = ent.Entitlement(
        email=EMAIL, uid=UID, supporter=True,
        day_limit=50, day_used=3, month_limit=400, month_used=400,
        day_resets_at=datetime(2026, 9, 3, tzinfo=timezone.utc),
        month_resets_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
    )
    assert e.remaining == 0
    assert e.exhausted_scope == "month"
    assert e.resets_at == datetime(2026, 10, 1, tzinfo=timezone.utc)
    detail = ent.quota_exhausted_detail(e)
    assert detail["code"] == "quota_exhausted"
    assert (detail["scope"], detail["limit"], detail["supporter"]) == ("month", 400, True)
    assert ent.retry_after_seconds(e, NOW) == int((e.resets_at - NOW).total_seconds())


def test_free_reader_exhausted_detail_points_at_supporter_tier():
    e = ent.Entitlement(
        email=EMAIL, uid=UID, supporter=False,
        day_limit=5, day_used=5, month_limit=None, month_used=0,
        day_resets_at=datetime(2026, 9, 3, tzinfo=timezone.utc),
        month_resets_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
    )
    with patch("app.services.entitlements.settings", _settings()):
        detail = ent.quota_exhausted_detail(e)
    assert detail["scope"] == "day" and detail["supporter"] is False
    assert "Supporters get 50" in detail["message"]


def test_counters_fall_back_to_local_memory_when_backend_errors():
    broken = MagicMock()
    broken.get.return_value = None
    broken.get_counter.return_value = None
    broken.incr_by_with_ttl.return_value = None
    with patch("app.services.entitlements.cache", broken), \
         patch("app.services.entitlements.settings", _settings()):
        e = ent.peek_entitlement(_Db(), EMAIL, UID, NOW)
        e = ent.consume_quota(e, NOW)
        assert e.day_used == 1
        assert ent.peek_entitlement(_Db(), EMAIL, UID, NOW).day_used == 1
