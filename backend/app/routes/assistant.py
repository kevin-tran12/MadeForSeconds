"""The Sous Chef endpoints: status, ask (Server-Sent Events), and feedback.

Dependency order on /ask, deliberately: the per-IP limiter, then "is the
feature configured", then the signed-in reader's entitlement (a quota peek
that consumes nothing), then the spend cap. A paused or unmetered budget
therefore never burns a question, and an anonymous caller never reaches the
budget check.
"""

import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Literal

import anthropic
import anyio
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..auth import UserIdentity, require_user
from ..config import settings
from ..firestore import get_db
from ..log_redaction import keyed_hash
from ..rate_limit import rate_limit
from ..services import assistant, entitlements, knowledge, llm_budget, pii, spokes, users
from ..services.entitlements import Entitlement
from ..services.recipes import get_published_doc
from ..services.users import clean_text

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/assistant")

FEEDBACK_TTL = timedelta(days=180)  # matches google_firestore_field.assistant_feedback_ttl


# ── Request models ────────────────────────────────────────────────────────────

class HistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=assistant.MAX_MESSAGE_CHARS)


class ClarifyAnswer(BaseModel):
    """One answer to one question the chef asked. The text also rides in the
    question itself, where the model reads it; this copy is what gets checked."""

    kind: Literal["location", "equipment", "quantity", "diet", "other"] = "other"
    text: str = Field(min_length=1, max_length=300)


class AskContext(BaseModel):
    servings: int = Field(ge=1, le=1000)
    unit_system: Literal["imperial", "metric"] = "imperial"
    # Set by the client for every send after the chef asked its questions, so
    # a thread only ever has one round of them.
    clarified: bool = False
    answers: list[ClarifyAnswer] = Field(default=[], max_length=assistant.MAX_CLARIFY_QUESTIONS)


class AskRequest(BaseModel):
    slug: str = Field(min_length=1, max_length=200)
    question: str = Field(min_length=1, max_length=assistant.MAX_QUESTION_CHARS)
    history: list[HistoryMessage] = Field(default=[], max_length=assistant.MAX_HISTORY)
    context: AskContext


class FeedbackRequest(BaseModel):
    slug: str = Field(min_length=1, max_length=200)
    question: str = Field(min_length=1, max_length=assistant.MAX_QUESTION_CHARS)
    answer: str = Field(min_length=1, max_length=6000)
    rating: Literal["up", "down"]
    comment: str = Field(default="", max_length=300)


# ── Dependencies ──────────────────────────────────────────────────────────────

def require_assistant_configured() -> None:
    if not settings.assistant_configured:
        raise HTTPException(
            status_code=503,
            detail={"code": "not_configured", "message": "The Sous Chef is taking a break."},
        )


async def require_assistant_entitlement(
    request: Request, user: UserIdentity = Depends(require_user)
) -> Entitlement:
    """Peek at the reader's allowance without consuming it; 429 when spent."""
    db = get_db()
    ent = await anyio.to_thread.run_sync(entitlements.peek_entitlement, db, user.email, user.uid)
    if ent.remaining <= 0:
        raise HTTPException(
            status_code=429,
            detail=entitlements.quota_exhausted_detail(ent),
            headers={"Retry-After": str(entitlements.retry_after_seconds(ent))},
        )
    request.state.entitlement = ent
    return ent


def require_llm_budget() -> None:
    try:
        paused = llm_budget.is_paused()
    except llm_budget.BudgetUnavailable:
        raise HTTPException(
            status_code=503,
            detail={"code": "budget_unavailable", "message": "The Sous Chef can't count its spend right now, so it's sitting this one out."},
        )
    if paused:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "spend_cap",
                "message": "The Sous Chef has used this month's budget. Back on the 1st.",
                "resets_at": llm_budget.resets_at().isoformat(),
            },
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"


def _record_spend(cost_micro: int) -> int | None:
    """Best-effort after the fact; the pre-flight check is the hard stop."""
    if cost_micro <= 0:
        return None
    try:
        return llm_budget.add_spend_micro(cost_micro)
    except llm_budget.BudgetUnavailable:
        logger.error("assistant: spend counter unavailable, %d micro-dollars unrecorded", cost_micro)
        return None


def _usage_dict(usage: dict | None) -> dict | None:
    """The token counters the client sees; searches ride in `searches`."""
    if usage is None:
        return None
    return {field: int(usage.get(field, 0)) for field in llm_budget.TOKEN_FIELDS}


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/status")
async def assistant_status() -> dict:
    """Public: lets the drawer show "off" or "paused" before asking anyone to sign in."""
    configured = settings.assistant_configured
    paused = False
    if configured:
        try:
            paused = llm_budget.is_paused()
        except llm_budget.BudgetUnavailable:
            paused = False  # the ask path is what fails closed
    return {
        "configured": configured,
        "paused": paused,
        "resets_at": llm_budget.resets_at().isoformat(),
        "quotas": {
            "free": settings.assistant_free_daily_quota,
            "supporter": settings.assistant_supporter_daily_quota,
            "supporter_monthly": settings.assistant_supporter_monthly_quota,
        },
        "levels": list(users.COOKING_LEVELS),
    }


@router.post(
    "/ask",
    dependencies=[
        Depends(rate_limit("assistant_ask", 30, 600)),
        Depends(require_assistant_configured),
    ],
)
async def ask(
    body: AskRequest,
    request: Request,
    ent: Entitlement = Depends(require_assistant_entitlement),
    _budget: None = Depends(require_llm_budget),
) -> StreamingResponse:
    user: UserIdentity = request.state.user
    try:
        question = assistant.sanitize_question(body.question)
    except assistant.InvalidQuestion:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_question", "message": "Ask that in plain words and I'm happy to help."},
        )

    # Before anything else: no personal details reach the model, a log line,
    # or Firestore. History is checked too — a crafted client can replay what
    # was refused a turn ago. Nothing is consumed and nothing is stored.
    answers = body.context.answers
    kind = pii.first_personal_info([question, *(m.content for m in body.history), *(a.text for a in answers)])
    if kind:
        logger.info("assistant refused personal_info kind=%s user=%s", kind, keyed_hash(user.email)[:12])
        raise HTTPException(status_code=400, detail=pii.refusal_detail(kind))

    # The one location answer allowed is a zip code — not a city, not a shop.
    if any(a.kind == "location" and not pii.is_zip(a.text) for a in answers):
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_question", "message": "A five-digit zip code is all I need — nothing else about where you are."},
        )

    db = get_db()

    def _load():
        doc = get_published_doc(db, body.slug)
        if doc is None:
            return None, "", None, knowledge.EMPTY
        return (
            doc, assistant.get_catalogue_index(db), users.get_cooking_experience(db, user.uid),
            knowledge.get_knowledge_base(db),
        )

    # Firestore round-trips off the event loop: this response then pins the
    # single instance's loop for the length of the stream.
    doc, catalogue, reader, kb = await anyio.to_thread.run_sync(_load)
    if doc is None:
        raise HTTPException(status_code=404, detail={"code": "recipe_not_found", "message": "Recipe not found"})

    history = assistant.normalize_history([m.model_dump() for m in body.history])

    # The hub, before the response opens: which specialist answers this, and
    # therefore which rules and which slice of the recipe get assembled. A
    # router that errors falls to the general spoke, which sees everything.
    router_cost = 0
    try:
        spoke, router_usage = await assistant.route(question, assistant.last_user_message(history))
        router_cost = llm_budget.cost_micro_usd(router_usage, settings.assistant_classifier_model)
    except Exception:
        logger.warning("assistant: router failed, falling back to %s", spokes.DEFAULT_SPOKE, exc_info=True)
        spoke = spokes.DEFAULT_SPOKE

    kwargs = None
    if spoke != spokes.OFFTOPIC_SPOKE:
        # Web search is a supporter perk on the one spoke that needs it, and
        # only while the month has room: at $0.01 a search it is ~50x an
        # ordinary answer, so it has its own ceiling under the spend cap.
        can_search = (
            spokes.get(spoke).web_search and ent.supporter and llm_budget.searches_available()
        )
        try:
            kwargs = assistant.build_request(
                spoke=spoke,
                recipe_doc=doc,
                catalogue=catalogue,
                question=question,
                history=history,
                view=body.context.model_dump(),
                reader=reader,
                clarified=body.context.clarified,
                supporter=ent.supporter,
                can_search=can_search,
                knowledge_base=kb,
            )
        except assistant.PromptTooLong:
            raise HTTPException(status_code=413, detail={"code": "prompt_too_long", "message": "That's a long one — start a fresh chat."})

    # Consume, then re-check: two requests can both pass the peek.
    ent = entitlements.consume_quota(ent)
    if ent.day_used > ent.day_limit or (ent.month_limit is not None and ent.month_used > ent.month_limit):
        entitlements.refund_quota(ent)
        _record_spend(router_cost)  # the router already ran; nothing goes unrecorded
        raise HTTPException(
            status_code=429,
            detail=entitlements.quota_exhausted_detail(ent),
            headers={"Retry-After": str(entitlements.retry_after_seconds(ent))},
        )

    return StreamingResponse(
        _events(kwargs, spoke, router_cost, ent, user, body.slug),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _events(kwargs: dict | None, spoke: str, router_cost: int, ent: Entitlement, user: UserIdentity, slug: str):
    started = time.monotonic()
    user_tag = keyed_hash(user.email)[:12]
    sent_any = False
    finished = False
    answer_parts: list[str] = []
    searches_seen = 0
    prompt_chars = len(assistant.CORE_RULES) + sum(len(json.dumps(m)) for m in (kwargs or {}).get("messages", []))

    yield sse("meta", {"quota": ent.to_dict()})

    # Off-topic never reaches the main model, but it still costs the reader a
    # question so probing isn't free.
    if kwargs is None:
        finished = True
        yield sse("delta", {"text": assistant.REFUSAL_TEXT})
        month = _record_spend(router_cost)
        yield sse("done", {
            "usage": None, "cost_micro_usd": router_cost, "stop_reason": "refused",
            "truncated": False, "refused": True, "searches": 0, "spoke": spoke, "quota": ent.to_dict(),
        })
        logger.info(
            "assistant refused slug=%s spoke=%s cost_micro=%d month_micro=%s user=%s ms=%d",
            slug, spoke, router_cost, month, user_tag, int((time.monotonic() - started) * 1000),
        )
        return

    # The answer. At most two calls: if the chef asks a reader only for things
    # it may never ask, every question is dropped and it is asked again with
    # the tool switched off, so the reader gets an answer either way.
    final = None
    questions: list[dict] = []
    sources: list[dict] = []
    usage = llm_budget.empty_usage()
    try:
        for attempt in range(2):
            asked: list[dict] = []
            try:
                async for kind, payload in assistant.stream_answer(kwargs):
                    if kind == "delta":
                        answer_parts.append(payload)
                        sent_any = True
                        yield sse("delta", {"text": payload})
                    elif kind == "status":
                        searches_seen += 1  # billed even if the reader leaves mid-search
                        yield sse("status", {"state": payload})
                    elif kind == "clarify":
                        asked = payload
                    elif kind == "sources":
                        sources = payload
                    elif kind == "final":
                        final = payload
            except anthropic.RateLimitError:
                finished = True
                if not sent_any:
                    entitlements.refund_quota(ent)
                _record_spend(router_cost)
                logger.warning("assistant: upstream rate limited slug=%s user=%s", slug, user_tag)
                yield sse("error", {"code": "upstream_busy", "message": "The Sous Chef is slammed right now — try again in a moment."})
                return
            except anthropic.WorkloadIdentityError:
                # The federation exchange itself failed — a rule that no longer
                # matches, an archived rule, a workspace-scoped rule with no
                # workspace id. It subclasses AnthropicError, not
                # APIStatusError, so without this clause it escapes the
                # generator, tears the SSE stream mid-response, and the reader
                # is left with an empty bubble and a consumed question. Logged
                # at ERROR because no amount of retrying fixes it.
                finished = True
                if not sent_any:
                    entitlements.refund_quota(ent)
                _record_spend(router_cost)
                logger.error(
                    "assistant: federation token exchange failed slug=%s user=%s — check the deny reason "
                    "on Workload identity → History in the Claude Console", slug, user_tag, exc_info=True,
                )
                yield sse("error", {"code": "upstream_error", "message": "The Sous Chef dropped the pan — try again."})
                return
            except (anthropic.APIStatusError, anthropic.APIConnectionError, anthropic.APITimeoutError):
                finished = True
                if not sent_any:
                    entitlements.refund_quota(ent)
                _record_spend(router_cost)
                logger.warning("assistant: upstream error slug=%s user=%s", slug, user_tag, exc_info=True)
                yield sse("error", {"code": "upstream_error", "message": "The Sous Chef dropped the pan — try again."})
                return

            if final is not None:
                usage = llm_budget.add_usage(usage, final.usage)
                llm_budget.add_searches(final.searches)
            questions = assistant.clean_clarify_questions(asked)
            if asked and not questions and attempt == 0:
                logger.warning("assistant: clarifying questions all refused slug=%s spoke=%s", slug, spoke)
                kwargs = {**kwargs, "tool_choice": {"type": "none"}}
                continue
            break

        finished = True
        answer = "".join(answer_parts)
        cost = router_cost + llm_budget.cost_micro_usd(usage, settings.assistant_model)
        month = _record_spend(cost)
        stop_reason = final.stop_reason if final is not None else None
        # From the accumulated usage, not the last final: a clarify re-issue is
        # a second call, and both calls' searches are billed.
        searches = usage["web_search_requests"]

        if questions:
            # The chef asked, not the reader: give the question back, keep the
            # spend, and leave the thread waiting for one round of answers.
            ent = entitlements.refund_quota(ent)
            yield sse("clarify", {"questions": questions})
            yield sse("done", {
                "usage": _usage_dict(usage),
                "cost_micro_usd": cost,
                "stop_reason": stop_reason,
                "truncated": final.truncated if final is not None else False,
                "refused": False,
                "clarifying": True,
                "searches": searches,
                "spoke": spoke,
                "quota": ent.to_dict(),
            })
            logger.info(
                "assistant clarified slug=%s spoke=%s clarify=%d cost_micro=%d month_micro=%s user=%s ms=%d",
                slug, spoke, len(questions), cost, month, user_tag, int((time.monotonic() - started) * 1000),
            )
            return

        if stop_reason == "refusal":
            yield sse("error", {"code": "refused", "message": assistant.API_REFUSAL_TEXT})
            logger.info("assistant refused slug=%s spoke=%s stop=refusal user=%s", slug, spoke, user_tag)
            return
        if assistant.leaks_rules(answer):
            yield sse("error", {"code": "refused", "message": assistant.API_REFUSAL_TEXT})
            logger.warning("assistant: leak_blocked slug=%s user=%s", slug, user_tag)
            return

        try:
            await anyio.to_thread.run_sync(users.increment_answers, get_db(), user.uid)
        except Exception:
            logger.warning("assistant: could not increment answers_total", exc_info=True)

        if sources:
            # Shown under the answer: a searched claim has to say where it came from.
            yield sse("sources", {"sources": sources})

        u = _usage_dict(usage) or {}
        yield sse("done", {
            "usage": _usage_dict(usage),
            "cost_micro_usd": cost,
            "stop_reason": stop_reason,
            "truncated": final.truncated if final is not None else False,
            "refused": False,
            "clarifying": False,
            "searches": searches,
            "spoke": spoke,
            "quota": ent.to_dict(),
        })
        logger.info(
            "assistant answered slug=%s spoke=%s in=%d cache_read=%d cache_write=%d out=%d searches=%d cost_micro=%d month_micro=%s stop=%s req=%s user=%s ms=%d",
            slug, spoke, u.get("input_tokens", 0), u.get("cache_read_input_tokens", 0),
            u.get("cache_creation_input_tokens", 0), u.get("output_tokens", 0), searches, cost, month,
            stop_reason, final.request_id if final is not None else None, user_tag,
            int((time.monotonic() - started) * 1000),
        )
    finally:
        if not finished:
            # The client went away mid-stream: the usage never arrived, so
            # charge a conservative estimate rather than leave spend unaccounted.
            estimate = router_cost + llm_budget.estimate_micro(
                prompt_chars, sum(len(p) for p in answer_parts), settings.assistant_model, searches=searches_seen
            )
            _record_spend(estimate)
            logger.info("assistant: client disconnected slug=%s user=%s estimated_micro=%d", slug, user_tag, estimate)


@router.post("/feedback", dependencies=[Depends(rate_limit("assistant_feedback", 30, 3600))])
async def feedback(body: FeedbackRequest, user: UserIdentity = Depends(require_user)) -> dict:
    """A thumbs up/down on an answer. The only place reader text is stored,
    opt-in per answer, keyed by hashed email, and expired after 180 days."""
    kind = pii.first_personal_info([body.question, body.answer, body.comment])
    if kind:
        logger.info("assistant feedback refused personal_info kind=%s user=%s", kind, keyed_hash(user.email)[:12])
        raise HTTPException(status_code=400, detail=pii.refusal_detail(kind))

    now = datetime.now(timezone.utc)
    doc = {
        "slug": body.slug,
        "rating": body.rating,
        "question": clean_text(body.question, 500),
        "answer": clean_text(body.answer, 2000),
        "comment": clean_text(body.comment, 300),
        "model": settings.assistant_model,
        "user_hash": keyed_hash(user.email),
        "created_at": now,
        "ttl": now + FEEDBACK_TTL,
    }
    db = get_db()
    await anyio.to_thread.run_sync(lambda: db.collection("assistant_feedback").add(doc))
    return {"recorded": True}
