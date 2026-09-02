"""Minimal per-reader record: enough for "welcome back" and a delete-my-data
endpoint, and nothing more.

Keyed by Firebase uid and holding no email or display name — the name comes
from the Google profile client-side, and the email already lives in Firebase
Auth (and in Stripe's records for donors). Data minimisation is the point.
"""

from datetime import datetime, timedelta, timezone

from google.cloud.firestore import DELETE_FIELD, Increment
from google.cloud.firestore_v1.base_query import FieldFilter

TOUCH_THROTTLE = timedelta(hours=1)  # one last_seen_at write per hour, not per request
_FEEDBACK_BATCH = 200


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(timezone.utc)


def _as_utc(value) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def touch_user(db, uid: str, now: datetime | None = None) -> dict:
    """Record a visit. Returns ``{"returning": bool, "answers_total": int}`` —
    ``returning`` is True when the record existed before this call."""
    n = _now(now)
    ref = db.collection("users").document(uid)
    snap = ref.get()
    if snap.exists:
        data = snap.to_dict() or {}
        last = _as_utc(data.get("last_seen_at"))
        if last is None or n - last >= TOUCH_THROTTLE:
            ref.update({"last_seen_at": n})
        return {"returning": True, "answers_total": int(data.get("answers_total") or 0)}
    ref.set({"created_at": n, "last_seen_at": n, "answers_total": 0})
    return {"returning": False, "answers_total": 0}


def increment_answers(db, uid: str, now: datetime | None = None) -> None:
    db.collection("users").document(uid).set(
        {"answers_total": Increment(1), "last_answer_at": _now(now)}, merge=True
    )


def delete_user_data(db, uid: str, user_hash: str) -> dict:
    """Erase what the assistant stored about a reader: the users doc, their
    feedback (found by hashed email), and the uid link on any supporter
    record. Stripe-derived donation records themselves stay — they are
    financial records, and they hold no data the reader did not give Stripe."""
    users_deleted = 0
    ref = db.collection("users").document(uid)
    if ref.get().exists:
        ref.delete()
        users_deleted = 1

    feedback_deleted = 0
    while True:
        docs = list(
            db.collection("assistant_feedback")
            .where(filter=FieldFilter("user_hash", "==", user_hash))
            .limit(_FEEDBACK_BATCH)
            .stream()
        )
        if not docs:
            break
        batch = db.batch()
        for doc in docs:
            batch.delete(doc.reference)
        batch.commit()
        feedback_deleted += len(docs)
        if len(docs) < _FEEDBACK_BATCH:
            break

    links_removed = 0
    for collection in ("subscribers", "donations"):
        docs = db.collection(collection).where(filter=FieldFilter("uid", "==", uid)).stream()
        for doc in docs:
            doc.reference.update({"uid": DELETE_FIELD})
            links_removed += 1

    return {
        "users_deleted": users_deleted,
        "feedback_deleted": feedback_deleted,
        "supporter_links_removed": links_removed,
    }
