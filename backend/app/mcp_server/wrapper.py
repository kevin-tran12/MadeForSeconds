"""mcp_tool(): the single decorator behind every MCP tool in this package.

Replaces errors.py's tool_errors (absorbed here verbatim — see the exception
handling below, unchanged from before) and adds what S4 and S5 of the MCP
hardening epic need on top:

- **Annotations.** read_only/destructive/idempotent/open_world become the
  tool's `ToolAnnotations`, attached to the function as `.mcp_annotations` so
  each module's register() can hand them to `mcp.tool(annotations=...)`
  without constructing `ToolAnnotations` itself. These are advisory hints per
  the MCP spec — the SDK does not enforce them, a client might (e.g. to gate
  a destructive call behind confirmation).
- **Budget.** `.mcp_budget` tags which rate-limit bucket ("read" | "write" |
  "publish_social") the call belongs to, enforced by
  `rate_budgets.check_budget()` before the underlying tool ever runs — see
  that module for the actual limits and why enforcement is a no-op without a
  caller identity (dev mode). A rejection returns
  `{"error": "rate_limited", "retry_after_seconds": N}` without calling the
  wrapped function at all.
- **Outcome log.** One structured `MCP_TOOL` line per call, success or
  translated-error alike, plus a WARNING `MCP_TOOL_FAILED` line when the
  error kind indicates something broke rather than the caller simply passing
  bad input (pattern: services/social.py's `SOCIAL_REFRESH_FAILED` marker —
  a static, grep/log-metric-friendly token in the message, not just a level).
  Logged via `extra={"json_fields": {...}}` — a real attribute
  `google.cloud.logging_v2.handlers.handlers.CloudLoggingHandler` looks for
  by name (verified in its source: it merges `record.json_fields` into the
  Cloud Logging structured payload) and the production logging setup in
  main.py already uses (`cloud_logging.Client().setup_logging()`), not a
  convention this repo had already established elsewhere — this is the
  first call site. Carries only ids, never argument values: RedactionFilter
  scrubs a record's rendered message, not its extra fields, so anything
  free-form has no business landing there.
- **Audit trail.** `audit.record(...)` (see that module) writes one
  best-effort Firestore doc per mutating call (`read_only=False` only —
  reads are never audited), success or failure alike, capturing WHAT was
  touched (`target`) and WHICH argument names were passed (`arg_keys`,
  never values) but never the mutation's actual payload.
- **Idempotency keys.** A tool that declares an `idempotency_key` parameter
  (see idempotency.py) gets it checked here, generically, before the tool
  runs: a repeat call with the same (client_id, key) returns the first
  call's cached result without the underlying mutation happening again.
  Only around the real call/exception path, deliberately not the rate-limit
  short-circuit above — a rejection was never actually attempted, so
  caching it would make a later, legitimate retry (once the budget window
  passes) incorrectly replay a stale rejection forever.
"""

import functools
import logging

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.types import ToolAnnotations
from pydantic import ValidationError

from ..services import ingredients
from ..services import instagram
from ..services import recipes as recipe_service
from . import audit, idempotency, rate_budgets

logger = logging.getLogger(__name__)

# Error kinds that mean something actually broke (a bug, a downstream outage,
# a misconfiguration) rather than the caller simply passing bad input the
# tool was designed to reject (validation_error, not_found, slug_conflict,
# alias_conflict, confirm_title_mismatch, invalid_request, invalid_categories,
# not_publishable). Those latter kinds are expected, routine tool output —
# alerting on them would just be noise.
_ALERT_ERROR_KINDS = frozenset({"internal", "instagram", "instagram_auth"})


def _current_caller() -> tuple[str | None, str | None]:
    """(client_id, subject) of the OAuth caller, or (None, None) outside an
    authenticated request (dev mode, or an in-memory Client() test) —
    get_access_token() itself already returns None rather than raising in
    that case. subject is WorkOSTokenVerifier's AccessToken.subject, which
    that verifier does not populate today (see mcp_auth.py) — always None
    in practice until it does, kept here (and in the audit doc) so nothing
    needs to change when it does."""
    token = get_access_token()
    if not token:
        return None, None
    return token.client_id, token.subject


def mcp_tool(
    *,
    read_only: bool,
    destructive: bool = False,
    idempotent: bool = False,
    open_world: bool = False,
    budget: str = "read",
):
    """Decorator factory — the one wrapper every tool function in tools/*.py
    wears, applied via each module's register() as
    `mcp.tool(annotations=getattr(tool, "mcp_annotations", None))(tool)`.
    """
    annotations = ToolAnnotations(
        read_only_hint=read_only,
        destructive_hint=destructive,
        idempotent_hint=idempotent,
        open_world_hint=open_world,
    )

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            client_id, subject = _current_caller()
            retry_after = rate_budgets.check_budget(budget, client_id)
            if retry_after is not None:
                # Skip fn() entirely — falls through to the single shared
                # outcome-log block below rather than duplicating it here.
                result = {"error": "rate_limited", "retry_after_seconds": retry_after}
                return _log_outcome_and_return(
                    tool_name=fn.__name__, result=result, client_id=client_id,
                    subject=subject, read_only=read_only, kwargs=kwargs,
                )

            idempotency_key = kwargs.get("idempotency_key")
            if idempotency_key and len(idempotency_key) > idempotency.MAX_KEY_LENGTH:
                result = {
                    "error": "invalid_request",
                    "message": f"idempotency_key must be at most {idempotency.MAX_KEY_LENGTH} characters",
                }
                return _log_outcome_and_return(
                    tool_name=fn.__name__, result=result, client_id=client_id,
                    subject=subject, read_only=read_only, kwargs=kwargs,
                )
            if idempotency_key and client_id:
                cached = idempotency.get_cached_result(client_id, idempotency_key)
                if cached is not None:
                    # A repeat within the TTL window — return the first
                    # call's result without running fn() (and its real
                    # Firestore write / Instagram call) a second time.
                    return _log_outcome_and_return(
                        tool_name=fn.__name__, result=cached, client_id=client_id,
                        subject=subject, read_only=read_only, kwargs=kwargs,
                    )

            try:
                result = fn(*args, **kwargs)
            except ValidationError as exc:
                result = {
                    "error": "validation_error",
                    "field_errors": [
                        {
                            "field": ".".join(str(p) for p in e["loc"]),
                            "message": e["msg"],
                            "type": e["type"],
                        }
                        for e in exc.errors()
                    ],
                }
            except recipe_service.SlugConflict as exc:
                result = {
                    "error": "slug_conflict",
                    "existing": exc.existing,
                    "hint": (
                        "A recipe with this slug already exists (this is usually a retry). "
                        "Use update_recipe with the existing id, or change the title."
                    ),
                }
            except recipe_service.InvalidCategories as exc:
                result = {
                    "error": "invalid_categories",
                    "invalid": exc.invalid,
                    "valid_categories": exc.allowed,
                }
            except recipe_service.RecipeNotFound as exc:
                result = {"error": "not_found", "message": f"Recipe not found: {exc}"}
            except recipe_service.NotPublishable as exc:
                result = {"error": "not_publishable", "problems": exc.problems}
            except recipe_service.RecipeServiceError as exc:
                result = {"error": "invalid_request", "message": str(exc)}
            except ingredients.AliasConflict as exc:
                result = {
                    "error": "alias_conflict",
                    "key": exc.key,
                    "existing_slug": exc.existing_slug,
                    "hint": (
                        f"{exc.key!r} already belongs to the profile {exc.existing_slug!r}. "
                        "Add it as an alias there instead, or pick a different name/alias."
                    ),
                }
            except ingredients.IngredientNotFound as exc:
                result = {"error": "not_found", "message": f"Ingredient not found: {exc}"}
            except instagram.InstagramError as exc:
                result = {
                    "error": "instagram_auth" if exc.auth else "instagram",
                    "message": str(exc),
                }
            except ValueError as exc:
                result = {"error": "invalid_request", "message": str(exc)}
            except Exception as exc:
                logger.exception("MCP tool %s failed", fn.__name__)
                result = {"error": "internal", "message": str(exc)}

            if idempotency_key and client_id:
                idempotency.store_result(client_id, idempotency_key, result)

            return _log_outcome_and_return(
                tool_name=fn.__name__, result=result, client_id=client_id,
                subject=subject, read_only=read_only, kwargs=kwargs,
            )

        wrapper.mcp_annotations = annotations
        wrapper.mcp_budget = budget
        return wrapper

    return decorator


def _log_outcome_and_return(
    tool_name: str, result, client_id: str | None, subject: str | None, read_only: bool, kwargs: dict,
):
    """The one MCP_TOOL outcome log line (plus a WARNING MCP_TOOL_FAILED
    marker for error kinds that mean something broke) and the one
    audit.record() call, shared by both the rate-limit short-circuit and
    the normal call/exception path above so there is exactly one place each
    of those happens, not two copies that could drift out of sync."""
    error_kind = result.get("error") if isinstance(result, dict) else None
    ok = error_kind is None
    logger.info(
        "MCP_TOOL tool=%s ok=%s error=%s",
        tool_name,
        ok,
        error_kind,
        extra={"json_fields": {"tool": tool_name, "ok": ok, "error": error_kind, "client_id": client_id}},
    )
    if error_kind in _ALERT_ERROR_KINDS:
        logger.warning("MCP_TOOL_FAILED tool=%s error=%s client_id=%s", tool_name, error_kind, client_id)
    if not read_only:
        audit.record(tool_name, kwargs, result, client_id, subject)
    return result


def iso(value) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else value
