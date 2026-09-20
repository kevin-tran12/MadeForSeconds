"""Per-tool rate budgets for the MCP surface (S5 of the MCP hardening epic).

Every tool is tagged with a budget category ("read" | "write" |
"publish_social") by @mcp_tool(budget=...) — see wrapper.py, which is what
actually calls check_budget() before running a tool. A budget is shared
across every tool in its category for one caller, not tracked per individual
tool: the 31st write-budget call in a minute is rejected regardless of
whether it's create_recipe, update_recipe, or nine other write tools mixed
together — that is what "budget" means here, as distinct from "quota per
tool name."

Reuses rate_limit.py's count_hit (the same atomic-incr-with-fallback
primitive the HTTP rate limiters already use), keyed by the caller's OAuth
client_id rather than an IP, since that is the only identity an MCP caller
carries.

Deliberately does NOT enforce anything when there is no client_id (dev mode,
or an in-memory Client() test): dev's MCP server runs fully unauthenticated,
trusted to a single operator (see server.py's own docstring on this), so
there is no "many callers" scenario to protect against there, and this keeps
every existing test that calls a tool function directly — none of which sets
up a real OAuth context — behaviorally unaffected. Production is the only
place a client_id is ever present, and therefore the only place this has any
effect.
"""

import logging

from ..rate_limit import count_hit

logger = logging.getLogger(__name__)

# (limit, window_seconds) pairs per budget, shortest window first — the
# order check_budget() reports a breach determines which retry_after_seconds
# a caller sees, and the shortest applicable wait is the most useful answer.
_BUDGETS: dict[str, tuple[tuple[int, int], ...]] = {
    "read": ((120, 60),),
    "write": ((30, 60),),
    "publish_social": ((5, 3600), (20, 86400)),
}


def check_budget(budget: str, client_id: str | None) -> int | None:
    """None if the call is allowed. Otherwise the number of seconds the
    caller should wait before retrying (the shortest breached window).

    Always increments every one of the budget's windows, even after finding
    a breach in an earlier one, so consumption stays honest across windows
    regardless of which one happens to reject first — a caller cannot use up
    "free" daily-budget attempts just by first tripping the hourly cap.
    """
    if client_id is None:
        return None
    windows = _BUDGETS.get(budget)
    if not windows:
        return None

    retry_after: int | None = None
    for limit, window_seconds in windows:
        key = f"mcp:{budget}:{window_seconds}:{client_id}"
        count = count_hit(key, window_seconds)
        if count > limit and retry_after is None:
            retry_after = window_seconds

    if retry_after is not None:
        # Once per rejection, not per window: a two-window budget breaching
        # both still logs a single line naming the tighter one.
        logger.warning(
            "MCP_RATE_LIMITED budget=%s client_id=%s retry_after_seconds=%s",
            budget, client_id, retry_after,
        )
    return retry_after
