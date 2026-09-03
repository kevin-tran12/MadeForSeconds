"""Monthly LLM spend metering for the Sous Chef assistant.

Anthropic spend is outside the GCP budget breaker, so the app keeps its own
hard cap: every answer's cost (from the API's usage counters and a fixed
price table) is added to a per-month Redis counter, and the ask endpoint
refuses once it reaches ``ASSISTANT_MONTHLY_CAP_USD``.

Fail-closed rule: in production the counter must live in Redis. If REDIS_URL
is unset, unreachable at startup (cache.py silently falls back to an
in-memory cache), or errors on a call, ``BudgetUnavailable`` is raised and the
caller refuses to answer — an in-memory counter on a scale-to-zero instance
would reset on every cold start and silently un-cap spend. Local dev (no
Redis) keeps the in-memory counter; it only has to be honest within a session.

Amounts are integer micro-dollars (1e-6 USD) so Redis INCRBY stays exact.
"""

import logging
import math
from datetime import datetime, timezone

from ..cache import RedisCache, cache
from ..config import settings

logger = logging.getLogger(__name__)

MICRO = 1_000_000  # micro-dollars per dollar

# List prices in micro-dollars per million tokens (USD/MTok × 1e6). Cache
# reads are 0.1× the input price, cache writes 1.25× (5-minute TTL).
PRICES_MICRO_PER_MTOK: dict[str, dict[str, int]] = {
    "claude-sonnet-5": {
        "input_tokens": 2_000_000,
        "output_tokens": 10_000_000,
        "cache_read_input_tokens": 200_000,
        "cache_creation_input_tokens": 2_500_000,
    },
    "claude-haiku-4-5": {
        "input_tokens": 1_000_000,
        "output_tokens": 5_000_000,
        "cache_read_input_tokens": 100_000,
        "cache_creation_input_tokens": 1_250_000,
    },
}
_DEFAULT_PRICE_MODEL = "claude-sonnet-5"

# Outlives the month it counts, so a cost that lands just after midnight on
# the 1st (a stream that started on the 31st) never hits an expired key.
SPEND_TTL_SECONDS = 40 * 86_400

_CHARS_PER_TOKEN = 4  # rough; only used when a stream is cut off before usage arrives


class BudgetUnavailable(RuntimeError):
    """The spend counter cannot be read or written durably — refuse to answer."""


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(timezone.utc)


def month_key(now: datetime | None = None) -> str:
    """Counter key for the UTC month containing `now` (lives under the cache's
    ``mfs:rl:`` prefix, outside the versioned content namespace)."""
    return f"llm:spend:{_now(now):%Y-%m}"


def resets_at(now: datetime | None = None) -> datetime:
    """First instant of the next UTC month."""
    n = _now(now)
    if n.month == 12:
        return datetime(n.year + 1, 1, 1, tzinfo=timezone.utc)
    return datetime(n.year, n.month + 1, 1, tzinfo=timezone.utc)


def cap_micro() -> int:
    return int(round(settings.assistant_monthly_cap_usd * MICRO))


def price_table(model: str) -> dict[str, int]:
    """Prices for `model`, falling back by family ("sonnet", "haiku") and then
    to the Sonnet table — the dearest one known — so an unrecognised model id
    can only ever over-count, never under-count."""
    if model in PRICES_MICRO_PER_MTOK:
        return PRICES_MICRO_PER_MTOK[model]
    for family in ("sonnet", "haiku"):
        if family in model:
            return PRICES_MICRO_PER_MTOK[f"claude-{family}-5" if family == "sonnet" else "claude-haiku-4-5"]
    logger.warning("No price table for model %s; charging at %s rates", model, _DEFAULT_PRICE_MODEL)
    return PRICES_MICRO_PER_MTOK[_DEFAULT_PRICE_MODEL]


def _usage_value(usage, field: str) -> int:
    value = usage.get(field) if isinstance(usage, dict) else getattr(usage, field, None)
    return int(value or 0)


def cost_micro_usd(usage, model: str) -> int:
    """Cost of one API response in micro-dollars, rounded up.

    `usage` is the SDK's Usage object (or an equivalent dict); the four token
    counters are read by name and a missing or None counter counts as zero.
    """
    prices = price_table(model)
    total = sum(_usage_value(usage, field) * price for field, price in prices.items())
    return math.ceil(total / MICRO)


def estimate_micro(input_chars: int, output_chars: int, model: str) -> int:
    """Rough cost for a stream cut off before its final usage arrived — better
    to over-count a disconnect than to leave spend unaccounted."""
    prices = price_table(model)
    input_tokens = math.ceil(max(input_chars, 0) / _CHARS_PER_TOKEN)
    output_tokens = math.ceil(max(output_chars, 0) / _CHARS_PER_TOKEN)
    total = input_tokens * prices["input_tokens"] + output_tokens * prices["output_tokens"]
    return math.ceil(total / MICRO)


def _durable_backend() -> bool:
    """Whether the active cache can hold a counter honestly across restarts."""
    return settings.is_dev or isinstance(cache, RedisCache)


def get_month_spend_micro(now: datetime | None = None) -> int:
    if not _durable_backend():
        raise BudgetUnavailable("the spend counter needs Redis in production")
    value = cache.get_counter(month_key(now))
    if value is None:
        raise BudgetUnavailable("the spend counter backend is unavailable")
    return value


def add_spend_micro(amount: int, now: datetime | None = None) -> int:
    """Add `amount` micro-dollars to this month's counter; returns the new total."""
    if amount < 0:
        raise ValueError("spend is never refunded")
    if not _durable_backend():
        raise BudgetUnavailable("the spend counter needs Redis in production")
    total = cache.incr_by_with_ttl(month_key(now), amount, SPEND_TTL_SECONDS)
    if total is None:
        raise BudgetUnavailable("the spend counter backend is unavailable")
    return total


def is_paused(now: datetime | None = None) -> bool:
    return get_month_spend_micro(now) >= cap_micro()


def summary(now: datetime | None = None) -> dict:
    """Operator-facing snapshot; reports unavailability instead of raising."""
    base = {
        "cap_usd": settings.assistant_monthly_cap_usd,
        "resets_at": resets_at(now).isoformat(),
    }
    try:
        spent = get_month_spend_micro(now)
    except BudgetUnavailable as exc:
        return {**base, "available": False, "reason": str(exc)}
    return {
        **base,
        "available": True,
        "spent_usd": round(spent / MICRO, 4),
        "paused": spent >= cap_micro(),
    }
