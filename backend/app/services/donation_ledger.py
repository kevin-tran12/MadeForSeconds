"""Immutable per-payment record of completed one-time donations.

``donations`` (subscriptions.py::_apply_donation_checkout) is a consolidated
aggregate keyed by email: a repeat donor's total accumulates on one document,
and each new payment overwrites ``last_donation_cents`` / ``stripe_session_id``.
That is enough for the supporter-facing total, but nothing survives that lets
a single payment be reconstructed afterward — no currency, no fee, no net, no
status, no durable Stripe reference. For a one-time gift there is no Stripe
subscription object tying repeat payments together either, so once
overwritten, that payment's own record is gone for good.

This collection is the missing per-payment record: one immutable document per
completed donation Checkout Session, written inside the same Firestore
transaction that processes the webhook event
(subscriptions.py::_process_event_logic), so the ledger entry and the
aggregate update commit together or not at all.

Deliberately mirrors receipt_ledger.py's contract: write-once, keyed by a
durable Stripe identity rather than an auto-generated id. Stripe's own
webhook ``processed_events`` reservation already keeps the same *event* from
reaching this code twice; keying by the Checkout Session id is the second,
independent guard for the same *payment* arriving under a different event
(e.g. a redelivery after the reservation's TTL has expired). Deliberately a
``.set()``, not a ``.create()``: a ``.create()`` would raise on that replay
and turn an expected, harmless redelivery into a permanently-failing webhook
that retries forever. A second write with the same identity converges to the
same document instead of producing a duplicate row.
"""

from ..log_redaction import keyed_hash as keyed_email_hash

COLLECTION = "donation_transactions"


def write_donation_record(
    transaction,
    db,
    *,
    session_id: str,
    email: str,
    gross_cents: int,
    currency: str,
    fee_cents: int | None,
    net_cents: int | None,
    payment_intent_id: str | None,
    stripe_created_at,
    now,
) -> None:
    """Write the immutable ledger record for one completed donation Checkout
    Session, as part of an active transaction — the caller commits this
    together with whatever aggregate write accompanies it, or not at all.

    fee_cents/net_cents are optional: checkout.session.completed itself
    carries no fee data, so the caller fills them via a best-effort lookup
    that may come back empty. None means "not available", never "zero".
    """
    ref = db.collection(COLLECTION).document(session_id)
    transaction.set(ref, {
        "stripe_session_id": session_id,
        "stripe_payment_intent_id": payment_intent_id,
        "email_hash": keyed_email_hash(email),
        "gross_cents": gross_cents,
        "currency": currency,
        "fee_cents": fee_cents,
        "net_cents": net_cents,
        "status": "succeeded",
        "mode": "payment",
        "stripe_created_at": stripe_created_at,
        "created_at": now,
    })
