"""Minimal per-reader record: enough for "welcome back", the reader's cooking
experience (so the Sous Chef can pitch its answers), and a delete-my-data
endpoint — and nothing more.

Keyed by Firebase uid and holding no email or display name — the name comes
from the Google profile client-side, and the email already lives in Firebase
Auth (and in Stripe's records for donors). Data minimisation is the point.
"""

import re
import unicodedata
from datetime import datetime, timedelta, timezone

from google.cloud.firestore import DELETE_FIELD, Increment
from google.cloud.firestore_v1.base_query import FieldFilter

TOUCH_THROTTLE = timedelta(hours=1)  # one last_seen_at write per hour, not per request
_FEEDBACK_BATCH = 200

# The reader's self-described cooking experience. The level steers how much
# the assistant explains; the notes are free text ("no oven", "vegetarian",
# "learning knife skills") that the assistant treats as context, never as
# instructions — they are reader-written, so they are cleaned like a question.
COOKING_LEVELS = ("beginner", "home_cook", "confident", "professional")
DEFAULT_COOKING_LEVEL = "home_cook"
MAX_EXPERIENCE_NOTES = 300
# Zero-width and line/paragraph separators, built from code points so the
# source never carries invisible characters itself.
_ZERO_WIDTH = "".join(chr(c) for c in (*range(0x200B, 0x2010), 0x2028, 0x2029, 0xFEFF))
_CONTROL_RE = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f" + re.escape(_ZERO_WIDTH) + "]")


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(timezone.utc)


def _as_utc(value) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def clean_notes(text: str | None) -> str:
    """Reader-written free text: NFC-normalise, drop control and zero-width
    characters, collapse whitespace, cap the length."""
    if not text:
        return ""
    text = unicodedata.normalize("NFC", text)
    text = _CONTROL_RE.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:MAX_EXPERIENCE_NOTES]


def cooking_experience_from(data: dict | None) -> dict | None:
    """The stored profile, normalised for API responses; None when never set."""
    raw = (data or {}).get("cooking_experience")
    if not isinstance(raw, dict):
        return None
    level = raw.get("level") if raw.get("level") in COOKING_LEVELS else DEFAULT_COOKING_LEVEL
    updated = _as_utc(raw.get("updated_at"))
    return {
        "level": level,
        "notes": clean_notes(raw.get("notes")),
        "updated_at": updated.isoformat() if updated else None,
    }


def touch_user(db, uid: str, now: datetime | None = None) -> dict:
    """Record a visit. Returns ``returning`` (True when the record existed
    before this call), ``answers_total``, and the stored ``cooking_experience``."""
    n = _now(now)
    ref = db.collection("users").document(uid)
    snap = ref.get()
    if snap.exists:
        data = snap.to_dict() or {}
        last = _as_utc(data.get("last_seen_at"))
        if last is None or n - last >= TOUCH_THROTTLE:
            ref.update({"last_seen_at": n})
        return {
            "returning": True,
            "answers_total": int(data.get("answers_total") or 0),
            "cooking_experience": cooking_experience_from(data),
        }
    ref.set({"created_at": n, "last_seen_at": n, "answers_total": 0})
    return {"returning": False, "answers_total": 0, "cooking_experience": None}


def get_cooking_experience(db, uid: str) -> dict | None:
    snap = db.collection("users").document(uid).get()
    return cooking_experience_from(snap.to_dict()) if snap.exists else None


def set_cooking_experience(db, uid: str, level: str, notes: str | None, now: datetime | None = None) -> dict:
    """Save (or replace) the reader's cooking experience. Merged into the
    users doc so it never clobbers the visit counters."""
    if level not in COOKING_LEVELS:
        raise ValueError(f"level must be one of {COOKING_LEVELS}")
    n = _now(now)
    payload = {"level": level, "notes": clean_notes(notes), "updated_at": n}
    db.collection("users").document(uid).set(
        {"cooking_experience": payload, "last_seen_at": n}, merge=True
    )
    return {"level": level, "notes": payload["notes"], "updated_at": n.isoformat()}


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
