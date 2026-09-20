"""Idempotency keys for side-effecting MCP tools (S15 of the MCP hardening
epic). See wrapper.py for where this is actually invoked.

An optional `idempotency_key` argument lets create_recipe, create_expense,
publish_instagram_post, and publish_recipe_to_instagram be retried safely
after a timeout: the same (client_id, key) pair returns the first call's
result on a repeat, without the underlying mutation (a second Firestore
write, a second Instagram post) happening a second time.

Deliberately the simple read-before-write shape, not
routes/subscriptions.py's transactional "processing" reservation: that
machinery exists there to guard against Stripe genuinely redelivering the
same webhook concurrently from multiple worker processes. An MCP client is
a single synchronous caller awaiting one response before making its next
call — there is no concurrent-redelivery scenario to guard against here,
only a client-side retry after a timeout, which by construction arrives
strictly after the first call has already returned (successfully) or
failed. The narrow gap this leaves — two calls sharing a key dispatched
at truly the same instant — is not a threat model for a single-owner
site's own MCP client.

No Terraform composite index (nothing ever queries this collection, only
point-reads/writes by document id) but one TTL field
(terraform/modules/storage/firestore.tf, mirroring processed_events_ttl and
assistant_feedback_ttl) so `mcp_idempotency` does not grow unbounded.
"""

import hashlib
import logging
from datetime import datetime, timedelta, timezone

from ..firestore import get_db

logger = logging.getLogger(__name__)

COLLECTION = "mcp_idempotency"
TTL_HOURS = 24
MAX_KEY_LENGTH = 128


def _doc_id(client_id: str, key: str) -> str:
    """sha256(client_id + key), never the raw key as the Firestore document
    id — a key is caller-supplied free text, and Firestore document ids
    have length and character restrictions ("/" in particular) a raw key
    could otherwise violate or, worse, be crafted to exploit (the same
    class of concern _require_safe_slug guards against in
    services/ingredients.py, applied here by hashing instead of validating,
    since a key has no readable-id use case the way a slug does)."""
    return hashlib.sha256(f"{client_id}:{key}".encode()).hexdigest()


def get_cached_result(client_id: str, key: str):
    """The stored result from an earlier call with this (client_id, key)
    pair, or None if there isn't one (never called before, expired, or the
    read itself failed). Best-effort: a read failure must degrade to
    "not seen before" — repeating the mutation — rather than raising and
    failing a call idempotency was only ever meant to make safer.
    """
    try:
        doc = get_db().collection(COLLECTION).document(_doc_id(client_id, key)).get()
    except Exception:
        logger.warning("mcp idempotency read failed", exc_info=True)
        return None
    if not doc.exists:
        return None
    return (doc.to_dict() or {}).get("result")


def store_result(client_id: str, key: str, result) -> None:
    """Best-effort — a write failure here means a retry within the TTL
    window repeats the mutation instead of returning the cached result,
    strictly worse than a cache hit but never worse than having no
    idempotency key at all, and never fails the call itself."""
    now = datetime.now(timezone.utc)
    try:
        get_db().collection(COLLECTION).document(_doc_id(client_id, key)).set({
            "result": result,
            "created_at": now,
            "ttl": now + timedelta(hours=TTL_HOURS),
        })
    except Exception:
        logger.warning("mcp idempotency write failed", exc_info=True)
