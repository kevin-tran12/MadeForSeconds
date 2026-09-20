"""Social platform token rotation — one scheduled job for every platform.

Each configured platform is refreshed independently: a failure on one is
logged with the ``SOCIAL_REFRESH_FAILED`` marker (which drives a Cloud
Monitoring alert) and recorded on the ``config/social`` Firestore doc, and
never blocks the others. The same doc is what the MCP ``social_status`` tool
reads, so the operator can see expiry and the last error without opening
Cloud Logging.

Why this exists: the original weekly Instagram job had no alert and no
status record, so when the seeded token expired between two runs (Meta's
"Session has expired on 16-Aug-26" — the token had been seeded near the end
of its 60-day life) every attempt 500'd for weeks and nobody knew.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Callable

from ..config import settings
from . import instagram

logger = logging.getLogger(__name__)

STATUS_COLLECTION = "config"
STATUS_DOC = "social"
POSTS_COLLECTION = "social_posts"
_MAX_ERROR_CHARS = 300
# Captions are the operator's own copy, sometimes long and sometimes personal.
# The history only needs enough to recognise a post, so store a prefix and the
# real length rather than the whole thing — the same reasoning that caps
# recorded errors above.
_MAX_CAPTION_PREVIEW_CHARS = 80
_DEFAULT_RECENT_POSTS = 5

# name -> (is_configured, refresh). TikTok slots in here when it lands. Both
# are resolved lazily on purpose: settings are read at call time, and the
# refresh function is looked up on the module so tests (and future rotation
# code) can patch it.
PLATFORMS: dict[str, tuple[Callable[[], bool], Callable[[], dict]]] = {
    "instagram": (lambda: settings.instagram_configured, lambda: instagram.refresh_token()),
}


def _record(db, platform: str, entry: dict) -> None:
    """Best-effort: a status write must never turn a successful refresh into a failure."""
    try:
        db.collection(STATUS_COLLECTION).document(STATUS_DOC).set({platform: entry}, merge=True)
    except Exception:
        logger.warning("social: could not record %s status", platform, exc_info=True)


def record_post(db, platform: str, entry: dict, now: datetime | None = None) -> None:
    """Append one publish attempt to ``social_posts`` and update ``config/social``.

    Best-effort, exactly like ``_record``: a history write must never turn a
    post that actually reached Instagram into a failure the caller reports.
    An unrecorded post is a gap in the log; a raised exception here would be
    a lie about what happened.

    ``entry`` carries ``ok`` plus whatever the attempt produced (media_id,
    permalink, slug) or ``error``. A ``caption`` is replaced by its length and
    first 80 characters before anything is written.
    """
    now = now or datetime.now(timezone.utc)
    caption = entry.pop("caption", None)
    record = {**entry, "platform": platform, "at": now}
    if caption is not None:
        record["caption_chars"] = len(caption)
        record["caption_preview"] = caption[:_MAX_CAPTION_PREVIEW_CHARS]
    try:
        db.collection(POSTS_COLLECTION).document().set(record)
        if entry.get("ok"):
            _record(
                db,
                platform,
                {
                    "last_post_at": now,
                    "last_post_media_id": entry.get("media_id"),
                    "last_post_permalink": entry.get("permalink"),
                },
            )
    except Exception:
        logger.warning("social: could not record %s post", platform, exc_info=True)


def recent_posts(db, limit: int = _DEFAULT_RECENT_POSTS) -> list[dict]:
    """The most recent publish attempts, newest first. Never raises: an
    unreadable history must not take down the status tool that reports it."""
    try:
        docs = (
            db.collection(POSTS_COLLECTION)
            .order_by("at", direction="DESCENDING")
            .limit(limit)
            .stream()
        )
        return [_jsonable(doc.to_dict() or {}) for doc in docs]
    except Exception:
        logger.warning("social: could not read post history", exc_info=True)
        return []


def refresh_all(db, now: datetime | None = None) -> dict:
    """Refresh every configured platform. Returns per-platform results and the
    list of platforms that failed (the route turns a non-empty list into a 500
    so the Scheduler attempt is recorded as failed and retried)."""
    now = now or datetime.now(timezone.utc)
    results: dict[str, dict] = {}
    failed: list[str] = []
    for name, (configured, refresh) in PLATFORMS.items():
        if not configured():
            results[name] = {"skipped": "not configured"}
            continue
        try:
            outcome = refresh()
        except Exception as exc:
            message = str(exc)[:_MAX_ERROR_CHARS]
            failed.append(name)
            results[name] = {"error": message}
            # Tokens never appear in these messages (instagram.py redacts them).
            logger.error("SOCIAL_REFRESH_FAILED platform=%s error=%s", name, message)
            _record(db, name, {"last_error": message, "last_failed_at": now})
            continue
        results[name] = outcome
        entry: dict = {"last_refresh_at": now, "last_error": None, "last_failed_at": None}
        days = outcome.get("expires_in_days")
        if isinstance(days, (int, float)) and days > 0:
            entry["expires_at"] = now + timedelta(days=days)
        _record(db, name, entry)
    return {"results": results, "failed": failed, "at": now.isoformat()}


def _jsonable(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    return value


def status(db) -> dict:
    """Per-platform configuration and the last recorded refresh outcome.

    Deliberately still keyed by platform name only: publish history is a
    sibling of this mapping, not an entry in it, so the ``social_status``
    tool composes the two rather than this returning a "recent_posts"
    key that would read like another platform.
    """
    snap = db.collection(STATUS_COLLECTION).document(STATUS_DOC).get()
    data = (snap.to_dict() or {}) if getattr(snap, "exists", False) else {}
    return {
        name: {"configured": bool(configured()), **_jsonable(data.get(name) or {})}
        for name, (configured, _refresh) in PLATFORMS.items()
    }
