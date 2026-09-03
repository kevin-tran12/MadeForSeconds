"""Who may ask the Sous Chef, and how much — the one swappable policy layer.

Everything the ask endpoint knows about identity and fairness comes through
this module; swapping the gating policy (anonymous with cookie quotas,
supporters-only, …) means changing it here, not in the route.

Supporter = the signed-in reader's uid or email matches an active monthly
subscriber, or a one-time donor within the last 30 days. Quotas are counted
per hashed email (no raw email in a key) per UTC day and — for supporters —
per UTC month, falling back to an in-process counter when Redis errors: this
is the fairness layer, the spend cap in ``llm_budget`` is the hard stop.
"""

import logging
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from google.cloud.firestore_v1.base_query import FieldFilter

from ..cache import MemoryCache, cache
from ..config import settings
from ..log_redaction import keyed_hash
from .llm_budget import resets_at as month_resets_at

logger = logging.getLogger(__name__)

SUPPORTER_CACHE_TTL = 300  # seconds a supporter lookup is trusted before re-querying
DONATION_WINDOW = timedelta(days=30)
DAY_QUOTA_TTL = 90_000  # > 24 h; the key is date-stamped so it resets at UTC midnight anyway
MONTH_QUOTA_TTL = 40 * 86_400

# Same role as rate_limit._fallback: keep counting through a Redis outage.
_fallback = MemoryCache(ttl=MONTH_QUOTA_TTL)


@dataclass(frozen=True)
class Entitlement:
    email: str
    uid: str
    supporter: bool
    day_limit: int
    day_used: int
    month_limit: int | None  # None = no monthly ceiling (free tier)
    month_used: int
    day_resets_at: datetime
    month_resets_at: datetime

    @property
    def day_remaining(self) -> int:
        return max(self.day_limit - self.day_used, 0)

    @property
    def month_remaining(self) -> int | None:
        if self.month_limit is None:
            return None
        return max(self.month_limit - self.month_used, 0)

    @property
    def remaining(self) -> int:
        if self.month_remaining is None:
            return self.day_remaining
        return min(self.day_remaining, self.month_remaining)

    @property
    def exhausted_scope(self) -> str | None:
        """Which limit blocks the next question, if any ("day" or "month")."""
        if self.month_remaining == 0:
            return "month"
        if self.day_remaining == 0:
            return "day"
        return None

    @property
    def resets_at(self) -> datetime:
        return self.month_resets_at if self.exhausted_scope == "month" else self.day_resets_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "supporter": self.supporter,
            "day": {"limit": self.day_limit, "used": self.day_used},
            "month": (
                {"limit": self.month_limit, "used": self.month_used}
                if self.month_limit is not None
                else None
            ),
            "remaining": self.remaining,
            "resets_at": self.resets_at.isoformat(),
        }


# ── Supporter lookup ───────────────────────────────────────────────────────────

def _now(now: datetime | None) -> datetime:
    return now or datetime.now(timezone.utc)


def _as_utc(value) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _first_row(db, collection: str, field: str, value: str) -> dict | None:
    docs = (
        db.collection(collection)
        .where(filter=FieldFilter(field, "==", value))
        .limit(1)
        .stream()
    )
    doc = next(iter(docs), None)
    return (doc.to_dict() or {}) if doc is not None else None


def _lookup(db, collection: str, email: str, uid: str) -> dict | None:
    """Supporter records are keyed by the email Stripe saw; a ``uid`` is stored
    on them once a signed-in donor checks out. uid first (exact), then email."""
    row = _first_row(db, collection, "uid", uid) if uid else None
    if row is None and email:
        row = _first_row(db, collection, "email", email)
    return row


def _lookup_supporter(db, email: str, uid: str, now: datetime) -> bool:
    subscriber = _lookup(db, "subscribers", email, uid)
    if subscriber and subscriber.get("status") == "active":
        return True
    donation = _lookup(db, "donations", email, uid)
    if donation:
        # First-time donation docs carry only created_at — subscriptions.py
        # writes last_donated_at on repeat donations only.
        when = _as_utc(donation.get("last_donated_at")) or _as_utc(donation.get("created_at"))
        if when is not None and now - when <= DONATION_WINDOW:
            return True
    return False


def is_supporter(db, email: str, uid: str, now: datetime | None = None) -> bool:
    """Cached (5 min) supporter check. The cache key hashes the email so the
    shared cache never holds a raw address; cache.clear() on any admin or
    profile mutation drops it early, which is fine."""
    email = (email or "").strip().lower()
    n = _now(now)
    key = f"assistant:supporter:{keyed_hash(email or uid)}"
    cached = cache.get(key)
    if isinstance(cached, dict) and n.timestamp() - float(cached.get("at", 0)) < SUPPORTER_CACHE_TTL:
        return bool(cached.get("supporter"))
    result = _lookup_supporter(db, email, uid, n)
    cache.set(key, {"supporter": result, "at": n.timestamp()})
    return result


# ── Quota counters ─────────────────────────────────────────────────────────────

def _hash_prefix(email: str) -> str:
    return keyed_hash(email)[:24]


def day_key(email: str, day: date) -> str:
    return f"llm:quota:{_hash_prefix(email)}:{day.isoformat()}"


def month_key(email: str, when: datetime) -> str:
    return f"llm:quota-month:{_hash_prefix(email)}:{when:%Y-%m}"


def _read_counter(key: str) -> int:
    value = cache.get_counter(key)
    if value is None:
        logger.warning("quota: backend unavailable reading a counter, using local fallback")
        value = _fallback.get_counter(key) or 0
    return value


def _add_counter(key: str, amount: int, ttl: int) -> int:
    value = cache.incr_by_with_ttl(key, amount, ttl)
    if value is None:
        logger.warning("quota: backend unavailable updating a counter, using local fallback")
        value = _fallback.incr_by_with_ttl(key, amount, ttl) or 0
    return value


def _day_resets_at(now: datetime) -> datetime:
    return datetime.combine(now.date() + timedelta(days=1), time.min, tzinfo=timezone.utc)


def peek_entitlement(db, email: str, uid: str, now: datetime | None = None) -> Entitlement:
    """Current limits and usage for a reader, without consuming anything."""
    n = _now(now)
    email = (email or "").strip().lower()
    supporter = is_supporter(db, email, uid, n)
    if supporter:
        day_limit = settings.assistant_supporter_daily_quota
        month_limit: int | None = settings.assistant_supporter_monthly_quota
        month_used = _read_counter(month_key(email, n))
    else:
        day_limit = settings.assistant_free_daily_quota
        month_limit = None
        month_used = 0
    return Entitlement(
        email=email,
        uid=uid,
        supporter=supporter,
        day_limit=day_limit,
        day_used=_read_counter(day_key(email, n.date())),
        month_limit=month_limit,
        month_used=month_used,
        day_resets_at=_day_resets_at(n),
        month_resets_at=month_resets_at(n),
    )


def consume_quota(ent: Entitlement, now: datetime | None = None) -> Entitlement:
    """Count one question against the reader's day (and month) counters and
    return the updated entitlement. The caller re-checks ``remaining`` on the
    result, so two concurrent requests cannot both slip past the peek."""
    n = _now(now)
    day_used = _add_counter(day_key(ent.email, n.date()), 1, DAY_QUOTA_TTL)
    month_used = ent.month_used
    if ent.month_limit is not None:
        month_used = _add_counter(month_key(ent.email, n), 1, MONTH_QUOTA_TTL)
    return replace(ent, day_used=day_used, month_used=month_used)


def refund_quota(ent: Entitlement, now: datetime | None = None) -> None:
    """Give a question back (the upstream call failed before any answer)."""
    n = _now(now)
    _add_counter(day_key(ent.email, n.date()), -1, DAY_QUOTA_TTL)
    if ent.month_limit is not None:
        _add_counter(month_key(ent.email, n), -1, MONTH_QUOTA_TTL)


def quota_exhausted_detail(ent: Entitlement) -> dict[str, Any]:
    """The 429 body the ask endpoint returns; the frontend keys off ``code``."""
    scope = ent.exhausted_scope or "day"
    limit = ent.month_limit if scope == "month" else ent.day_limit
    if ent.supporter:
        message = f"You have used your {limit} Sous Chef questions for this {scope}."
    else:
        message = (
            f"You have used today's {limit} free Sous Chef questions. "
            f"Supporters get {settings.assistant_supporter_daily_quota} a day."
        )
    return {
        "code": "quota_exhausted",
        "scope": scope,
        "supporter": ent.supporter,
        "limit": limit,
        "resets_at": ent.resets_at.isoformat(),
        "message": message,
    }


def retry_after_seconds(ent: Entitlement, now: datetime | None = None) -> int:
    return max(int((ent.resets_at - _now(now)).total_seconds()), 1)
