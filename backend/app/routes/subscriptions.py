import logging
import re
from datetime import datetime, timedelta, timezone

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from google.cloud.firestore import Increment, transactional
from pydantic import BaseModel, Field

from ..config import settings
from ..firestore import get_db
from ..log_redaction import keyed_hash
from ..rate_limit import rate_limit
from ..services import donation_ledger
from ..services.email import send_email
from ..subscriber_auth import create_cancel_token, verify_cancel_token

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/subscribe")

# Configure Stripe once at import time (thread-safe, no per-request mutation)
stripe.api_key = settings.stripe_secret_key

# How stale a "processing" webhook-event reservation must be before we assume
# the worker that created it crashed and it's safe to reclaim and reprocess.
_STALE_RESERVATION_SECONDS = 120

# Retention for processed_events docs, stamped as the `ttl` field on write.
# Must outlive any window in which Stripe could redeliver or replay this
# event, or a replay after this doc expires would look like a brand-new
# event and get double-processed. Automatic retries stop after 3 days, but
# manual replay (dashboard/CLI, via the List Events API) is possible for any
# event Stripe still has on file — and "Stripe only returns events created
# in the last 30 days" (https://docs.stripe.com/webhooks/process-undelivered-events),
# which is the real ceiling this needs to match, not the 24h idempotency-key
# minimum. The actual deletion is done by the Firestore TTL policy in
# terraform/modules/storage/firestore.tf (google_firestore_field.processed_events_ttl) —
# keep the two in sync.
_PROCESSED_EVENTS_TTL_DAYS = 30


class WebhookProcessingError(Exception):
    """Raised by _apply_* functions when a webhook can't be processed yet
    (e.g. a referenced subscriber doc doesn't exist), aborting the
    transaction so the caller re-raises and Stripe retries with backoff."""


def _read_existing_doc(transaction, db, event_type: str, data: dict):
    """Read phase: the one query a given event type needs, if any (pure
    read — part of the transaction's read set, must happen before any
    writes). Returns a DocumentSnapshot or None."""
    if event_type == "checkout.session.completed":
        email = (data.get("customer_details") or {}).get("email", "").lower()
        if not email:
            return None
        collection = "subscribers" if data.get("mode") == "subscription" else "donations"
        docs = list(
            db.collection(collection).where("email", "==", email).limit(1).stream(transaction=transaction)
        )
        return docs[0] if docs else None

    if event_type in (
        "customer.subscription.updated",
        "customer.subscription.deleted",
        "invoice.payment_failed",
        "invoice.payment_succeeded",
    ):
        subscription_id = (
            data.get("id") if event_type.startswith("customer.subscription") else data.get("subscription")
        )
        if not subscription_id:
            return None
        docs = list(
            db.collection("subscribers")
            .where("stripe_subscription_id", "==", subscription_id)
            .limit(1)
            .stream(transaction=transaction)
        )
        return docs[0] if docs else None

    return None


def _apply_subscription_checkout(transaction, db, data: dict, existing_doc, now, event_id=None) -> str:
    customer_id = data.get("customer")
    subscription_id = data.get("subscription")
    email = (data.get("customer_details") or {}).get("email", "").lower()
    amount_total = data.get("amount_total", 0)

    if not email:
        return "missing_email"

    subscriber_data = {
        "email": email,
        "stripe_customer_id": customer_id,
        "stripe_subscription_id": subscription_id,
        "status": "active",
        "total_donated_cents": amount_total,
        "updated_at": now,
    }

    # Logged by event_id, not email/customer/subscription id — Cloud Logging
    # is this project's log sink, and log access shouldn't double as
    # supporter-list access. event_id is what an operator actually needs to
    # correlate this line with Stripe's own dashboard.
    if existing_doc:
        subscriber_data["total_donated_cents"] = Increment(amount_total)
        transaction.update(existing_doc.reference, subscriber_data)
        logger.info("Updated subscriber (event=%s)", event_id)
    else:
        subscriber_data["created_at"] = now
        new_ref = db.collection("subscribers").document()
        transaction.set(new_ref, subscriber_data)
        logger.info("Created subscriber (event=%s)", event_id)
    return "processed"


def _apply_subscription_updated(transaction, data: dict, existing_doc, now, event_id=None) -> str:
    status = data.get("status")
    current_period_end = data.get("current_period_end")

    if existing_doc is None:
        raise WebhookProcessingError(f"Subscription updated but no subscriber found (event={event_id})")

    update_data: dict = {"status": status, "updated_at": now}
    if current_period_end:
        update_data["current_period_end"] = datetime.fromtimestamp(current_period_end, tz=timezone.utc)

    transaction.update(existing_doc.reference, update_data)
    logger.info("Subscription updated to status %s (event=%s)", status, event_id)
    return "processed"


def _apply_subscription_deleted(transaction, data: dict, existing_doc, now, event_id=None) -> str:
    if existing_doc is None:
        raise WebhookProcessingError(f"Subscription deleted but no subscriber found (event={event_id})")

    transaction.update(existing_doc.reference, {"status": "canceled", "updated_at": now})
    logger.info("Subscription canceled (event=%s)", event_id)
    return "processed"


def _apply_payment_failed(transaction, data: dict, existing_doc, now, event_id=None) -> str:
    subscription_id = data.get("subscription")
    if not subscription_id:
        return "ignored"
    if existing_doc is None:
        raise WebhookProcessingError(f"Payment failed but no subscriber found (event={event_id})")

    transaction.update(existing_doc.reference, {"status": "past_due", "updated_at": now})
    logger.info("Payment failed (event=%s)", event_id)
    return "processed"


def _apply_payment_succeeded(transaction, data: dict, existing_doc, now, event_id=None) -> str:
    """Handle invoice.payment_succeeded — increment total_donated_cents for recurring payments.

    Skips the initial subscription invoice (billing_reason=subscription_create) because
    that amount is already recorded by _apply_subscription_checkout.
    """
    subscription_id = data.get("subscription")
    amount_paid = data.get("amount_paid", 0)  # in cents
    billing_reason = data.get("billing_reason", "")

    if not subscription_id or not amount_paid:
        return "ignored"
    if billing_reason == "subscription_create":
        logger.info("Skipping initial invoice, already counted at checkout (event=%s)", event_id)
        return "ignored"
    if existing_doc is None:
        raise WebhookProcessingError(f"Payment succeeded but no subscriber found (event={event_id})")

    transaction.update(existing_doc.reference, {
        "total_donated_cents": Increment(amount_paid),
        "updated_at": now,
    })
    logger.info("Payment succeeded: +%d cents (event=%s)", amount_paid, event_id)
    return "processed"


def _apply_donation_checkout(
    transaction, db, data: dict, existing_doc, now, fee_cents=None, net_cents=None, event_id=None
) -> str:
    """Handle checkout.session.completed for one-time donation payments.

    Consolidates by email on the `donations` aggregate — repeat donors get
    their total accumulated on one doc — but every payment, repeat or not,
    also gets its own immutable row in `donation_transactions` (the ledger
    the aggregate alone can't reconstruct: currency, fee, net, status, a
    durable Stripe reference). Both writes land in this same transaction, so
    they commit together or not at all.
    """
    email = (data.get("customer_details") or {}).get("email", "").lower()
    amount_total = data.get("amount_total", 0)
    session_id = data.get("id")
    created = data.get("created")

    donation_ledger.write_donation_record(
        transaction,
        db,
        session_id=session_id,
        email=email or "anonymous",
        gross_cents=amount_total,
        currency=data.get("currency") or "usd",
        fee_cents=fee_cents,
        net_cents=net_cents,
        payment_intent_id=data.get("payment_intent"),
        stripe_created_at=datetime.fromtimestamp(created, tz=timezone.utc) if created else None,
        now=now,
    )

    if email and existing_doc:
        transaction.update(existing_doc.reference, {
            "total_donated_cents": Increment(amount_total),
            "last_donation_cents": amount_total,
            "last_donated_at": now,
            "updated_at": now,
        })
        logger.info("Repeat donation: +%d cents (event=%s)", amount_total, event_id)
        return "processed"

    new_ref = db.collection("donations").document()
    transaction.set(new_ref, {
        "email": email or "anonymous",
        "amount_cents": amount_total,
        "total_donated_cents": amount_total,
        "stripe_session_id": session_id,
        "created_at": now,
    })
    logger.info("New donation recorded: %d cents (event=%s)", amount_total, event_id)
    return "processed"


def _apply_mutation(
    transaction, db, event_type: str, data: dict, existing_doc, now, fee_cents=None, net_cents=None, event_id=None
) -> str:
    """Write phase: the actual business mutation for a given event type,
    dispatched the same way the old per-event _handle_* functions were,
    but writing through the shared transaction instead of directly."""
    if event_type == "checkout.session.completed":
        mode = data.get("mode")
        if mode == "subscription":
            return _apply_subscription_checkout(transaction, db, data, existing_doc, now, event_id)
        if mode == "payment":
            return _apply_donation_checkout(transaction, db, data, existing_doc, now, fee_cents, net_cents, event_id)
        return "ignored"

    if event_type == "customer.subscription.updated":
        return _apply_subscription_updated(transaction, data, existing_doc, now, event_id)

    if event_type == "customer.subscription.deleted":
        return _apply_subscription_deleted(transaction, data, existing_doc, now, event_id)

    if event_type == "invoice.payment_failed":
        return _apply_payment_failed(transaction, data, existing_doc, now, event_id)

    if event_type == "invoice.payment_succeeded":
        return _apply_payment_succeeded(transaction, data, existing_doc, now, event_id)

    return "ignored"


def _process_event_logic(
    transaction, ref, db, event_type: str, data: dict, now, fee_cents=None, net_cents=None
) -> str:
    """One transaction covers both the event reservation AND the business
    mutation, so a crash between "apply the change" and "mark the event
    completed" can no longer let a reclaim double-apply it — either both
    happen or neither does.

    Raising (e.g. WebhookProcessingError) aborts the WHOLE transaction:
    nothing is committed, not even the reservation, so a Stripe retry starts
    completely fresh with no cleanup needed.

    fee_cents/net_cents are an already-fetched, best-effort donation-fee
    lookup (see _fetch_donation_fee_net) — computed before this transaction
    starts, never inside it, since it's a Stripe API call and this function
    can be retried on contention.

    Returns an outcome string ("skip", "missing_email", "processed",
    "ignored") the caller uses to decide whether to alert.
    """
    # ---- READ PHASE — nothing written yet. Firestore's Python client
    # forbids reads after the first write within one transaction, so every
    # read this event might need happens here, before any write below. ----
    snapshot = ref.get(transaction=transaction)
    if snapshot.exists:
        d = snapshot.to_dict() or {}
        status, created_at = d.get("status"), d.get("created_at")
        age = (now - created_at).total_seconds() if created_at else None
        if status == "completed":
            return "skip"
        if status == "processing" and age is not None and age < _STALE_RESERVATION_SECONDS:
            return "skip"
        # else: absent, or a stale "processing" reservation — reclaim below.

    existing_doc = _read_existing_doc(transaction, db, event_type, data)

    # ---- WRITE PHASE ----
    transaction.set(ref, {
        "type": event_type,
        "status": "processing",
        "created_at": now,
        "ttl": now + timedelta(days=_PROCESSED_EVENTS_TTL_DAYS),
    })
    outcome = _apply_mutation(transaction, db, event_type, data, existing_doc, now, fee_cents, net_cents, ref.id)
    transaction.update(ref, {"status": "completed", "processed_at": now, "outcome": outcome})
    return outcome


# Firestore's optimistic concurrency lets only one transaction touching this
# reservation doc commit at a time — a concurrent or racing retry is
# automatically retried by the client library and will see the winner's
# fresh state (completed, or a fresh "processing" reservation) on its retry.
_process_event = transactional(_process_event_logic)


def _fetch_donation_fee_net(payment_intent_id: str | None) -> tuple[int | None, int | None]:
    """Best-effort fee/net lookup for a completed one-time donation, via the
    PaymentIntent's balance transaction.

    checkout.session.completed itself carries no fee data, and this is a
    Stripe API call — it must run before _process_event's transaction
    starts (a retried transaction body must never re-trigger it), and it
    must never raise: a Stripe hiccup here must not fail the webhook or
    block the ledger record's gross/currency/status, which are the part
    that matters. (None, None) means "not available", not "zero fee".
    """
    if not payment_intent_id:
        return None, None
    try:
        intent = stripe.PaymentIntent.retrieve(
            payment_intent_id, expand=["latest_charge.balance_transaction"]
        )
        charge = intent.get("latest_charge")
        balance_transaction = charge.get("balance_transaction") if charge else None
        if not balance_transaction:
            return None, None
        return balance_transaction.get("fee"), balance_transaction.get("net")
    except Exception:
        logger.warning(
            "Could not fetch fee/net for payment_intent %s", payment_intent_id, exc_info=True
        )
        return None, None


async def _alert(subject: str, detail: str) -> None:
    """Best-effort ops alert to settings.alert_email. Never raises — a failed
    alert send must not mask or replace the original webhook error."""
    if not settings.alert_email:
        logger.warning("alert_email not configured, dropping alert: %s — %s", subject, detail)
        return
    try:
        await send_email(settings.alert_email, f"[MadeForSeconds] {subject}", f"<p>{detail}</p>")
    except Exception:
        logger.exception("Failed to send alert email: %s", subject)


def _sanitize(text: str, max_len: int) -> str:
    """Strip whitespace, collapse internal whitespace runs, remove control characters, enforce max length."""
    if not text:
        return ""
    # Remove control characters (keep normal unicode letters, emoji, punctuation)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    # Collapse multiple whitespace into single space
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_len]


# ── Request/Response models ──────────────────────────────────────────────────

class CheckoutRequest(BaseModel):
    success_url: str
    cancel_url: str
    amount_cents: int  # amount in cents (min 100 = $1)
    one_time: bool = False  # True for one-time donation, False for monthly subscription
    # Client-generated UUID so a retried request can't create a second session
    idempotency_key: str | None = Field(default=None, max_length=64)


class CheckoutResponse(BaseModel):
    checkout_url: str


class SessionInfoResponse(BaseModel):
    email: str
    payment_type: str  # "subscription" | "one_time"
    amount_cents: int
    already_set_up: bool


class SetupProfileRequest(BaseModel):
    session_id: str
    display_name: str = ""
    note: str = ""
    note_is_public: bool = False


class SetupProfileResponse(BaseModel):
    display_name: str | None
    note: str | None
    note_is_public: bool


class CancelRequest(BaseModel):
    email: str


class CancelConfirmRequest(BaseModel):
    token: str


class Supporter(BaseModel):
    display_name: str
    note: str | None = None


# ── Routes ───────────────────────────────────────────────────────────────────

def _validate_redirect_url(url: str) -> None:
    """Ensure redirect URLs point to our frontend — prevents open-redirect attacks."""
    # Check against all allowed origins (supports multiple frontends: custom domain + pages.dev)
    for origin in settings.cors_origins:
        allowed = origin.rstrip("/")
        if url.startswith(allowed + "/") or url == allowed:
            return
    raise HTTPException(status_code=400, detail="Invalid redirect URL")


@router.post(
    "/checkout",
    response_model=CheckoutResponse,
    dependencies=[Depends(rate_limit("checkout", 20, 3600))],
)
async def create_checkout(body: CheckoutRequest):
    """Create a Stripe Checkout session for a subscription or one-time donation."""

    if not settings.stripe_secret_key:
        raise HTTPException(status_code=503, detail="Subscriptions not configured")

    if body.amount_cents < 100 or body.amount_cents > 50000:
        raise HTTPException(status_code=400, detail="Amount must be between $1 and $500")

    _validate_redirect_url(body.success_url)
    _validate_redirect_url(body.cancel_url)

    # Stripe dedupes retried requests carrying the same key for 24h
    idempotency = (
        {"idempotency_key": f"checkout-{body.idempotency_key}"} if body.idempotency_key else {}
    )

    try:
        if body.one_time:
            # One-time donation
            session = stripe.checkout.Session.create(
                mode="payment",
                submit_type="donate",
                line_items=[{
                    "price_data": {
                        "currency": "usd",
                        "product_data": {
                            "name": "MadeForSeconds Donation",
                            "tax_code": "txcd_00000000",
                        },
                        "unit_amount": body.amount_cents,
                    },
                    "quantity": 1,
                }],
                success_url=body.success_url,
                cancel_url=body.cancel_url,
                **idempotency,
            )
        else:
            # Monthly recurring donation
            session = stripe.checkout.Session.create(
                mode="subscription",
                # Note: submit_type='donate' is not supported by Stripe for subscriptions,
                # so we use a clear product name instead.
                line_items=[{
                    "price_data": {
                        "currency": "usd",
                        "product_data": {
                            "name": "MadeForSeconds Monthly Donation",
                            "tax_code": "txcd_00000000",
                        },
                        "unit_amount": body.amount_cents,
                        "recurring": {"interval": "month"},
                    },
                    "quantity": 1,
                }],
                success_url=body.success_url,
                cancel_url=body.cancel_url,
                **idempotency,
            )
    except stripe.StripeError as e:
        logger.error("Stripe checkout error: %s", e)
        raise HTTPException(status_code=502, detail=str(e.user_message or "Payment service error"))

    return CheckoutResponse(checkout_url=session.url)


@router.post("/webhook")
async def stripe_webhook(request: Request):
    """Handle Stripe webhook events for subscriptions and donations."""
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.stripe_webhook_secret
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    # construct_event returns a typed stripe.Event in production — it supports
    # __getitem__ and __contains__ (used below and throughout
    # _apply_*/_read_existing_doc) but not dict methods like .get(), which
    # every one of those functions relies on. Converting once here, at the
    # boundary, keeps the rest of the file's dict-shaped type hints accurate.
    # Test fixtures mock construct_event to return a plain dict directly —
    # hasattr guards against calling .to_dict() on something that's already one.
    if hasattr(event, "to_dict"):
        event = event.to_dict()
    event_id = event.get("id", "")
    event_type = event["type"]
    data = event["data"]["object"]

    if not event_id:
        # Stripe always includes an id on genuine webhook events; this would
        # mean a malformed payload that nonetheless passed signature
        # verification. Can't be safely deduplicated or retried into success.
        logger.error(f"Stripe event missing id, cannot process safely: {event_type}")
        await _alert("Webhook event missing id", f"type={event_type} — cannot be safely deduplicated or processed")
        raise HTTPException(status_code=400, detail="Event missing id")

    db = get_db()
    ref = db.collection("processed_events").document(event_id)
    now = datetime.now(timezone.utc)

    # Best-effort donation fee/net lookup — an extra Stripe API call, so it
    # happens once here, before the transaction, never inside it (see
    # _fetch_donation_fee_net's own docstring). Scoped to exactly the event
    # shape _apply_donation_checkout will actually use it for.
    fee_cents = net_cents = None
    if event_type == "checkout.session.completed" and data.get("mode") == "payment":
        fee_cents, net_cents = _fetch_donation_fee_net(data.get("payment_intent"))

    # The reservation and the business mutation both happen inside one
    # Firestore transaction (_process_event) — see its docstring for why
    # that's needed for exactly-once processing, not just a race-free
    # reservation. Raising aborts the whole transaction; nothing commits,
    # so a Stripe retry starts completely fresh with no cleanup needed here.
    try:
        outcome = _process_event(db.transaction(), ref, db, event_type, data, now, fee_cents, net_cents)
    except Exception as exc:
        logger.exception(f"Webhook processing failed for event {event_id} ({event_type})")
        await _alert(
            f"Webhook processing failed: {event_type}",
            f"event_id={event_id}<br>error={exc}",
        )
        raise  # -> FastAPI 500 -> Stripe retries with backoff

    if outcome == "skip":
        logger.info(f"Skipping event {event_id} (already processed or in flight)")
    elif outcome == "missing_email":
        await _alert(
            "Subscription checkout missing email",
            f"event_id={event_id}<br>Stripe never captured an email for this checkout — "
            "retrying won't add one; needs manual reconciliation in the Stripe dashboard.",
        )

    return {"status": "ok"}


@router.get(
    "/session-info",
    response_model=SessionInfoResponse,
    dependencies=[Depends(rate_limit("session_info", 30, 600))],
)
async def get_session_info(session_id: str):
    """Get info about a completed Stripe checkout session (no auth required — session_id is the proof)."""
    try:
        session = stripe.checkout.Session.retrieve(session_id)
    except stripe.InvalidRequestError:
        raise HTTPException(status_code=404, detail="Session not found")
    except stripe.StripeError as e:
        logger.error("Stripe session retrieval error: %s", e)
        raise HTTPException(status_code=502, detail="Payment service error")

    if session.payment_status != "paid":
        raise HTTPException(status_code=400, detail="Payment not completed")

    email = (session.customer_details.email or "").lower() if session.customer_details else ""
    payment_type = "subscription" if session.mode == "subscription" else "one_time"
    amount_cents = session.amount_total or 0

    # Check if profile was already set up for this session
    already_set_up = False
    db = get_db()

    if payment_type == "subscription":
        docs = db.collection("subscribers").where("email", "==", email).limit(1).stream()
        doc = next(docs, None)
        if doc:
            data = doc.to_dict()
            already_set_up = data.get("setup_session_id") == session.id
    else:
        # Look up by email; consider already set up only if this exact session was used
        docs = db.collection("donations").where("email", "==", email).limit(1).stream()
        doc = next(docs, None)
        if doc:
            data = doc.to_dict()
            already_set_up = data.get("setup_session_id") == session.id

    return SessionInfoResponse(
        email=email,
        payment_type=payment_type,
        amount_cents=amount_cents,
        already_set_up=already_set_up,
    )


@router.post(
    "/setup-profile",
    response_model=SetupProfileResponse,
    dependencies=[Depends(rate_limit("setup_profile", 5, 600))],
)
async def setup_profile(body: SetupProfileRequest):
    """Set display name and note after payment. Uses Stripe session_id as proof — no login needed."""
    # Verify the session with Stripe
    try:
        session = stripe.checkout.Session.retrieve(body.session_id)
    except stripe.InvalidRequestError:
        raise HTTPException(status_code=404, detail="Session not found")
    except stripe.StripeError as e:
        logger.error("Stripe session retrieval error: %s", e)
        raise HTTPException(status_code=502, detail="Payment service error")

    if session.payment_status != "paid":
        raise HTTPException(status_code=400, detail="Payment not completed")

    email = (session.customer_details.email or "").lower() if session.customer_details else ""
    if not email:
        raise HTTPException(status_code=400, detail="No email associated with this payment")

    display_name = _sanitize(body.display_name, max_len=50)
    note = _sanitize(body.note, max_len=280)

    db = get_db()
    now = datetime.now(timezone.utc)

    update_data = {
        "display_name": display_name or None,
        # Notes require admin approval before going public.
        # Store as note_pending; approved ones are moved to note/note_is_public by admin.
        "note_pending": note or None,
        "note_pending_public": body.note_is_public if note else False,
        "profile_set_at": now,
        "setup_session_id": body.session_id,
        "updated_at": now,
    }

    if session.mode == "subscription":
        docs = db.collection("subscribers").where("email", "==", email).limit(1).stream()
        doc = next(docs, None)
        if doc:
            existing = doc.to_dict()
            # Only block exact replay of the same session (prevent double-submit)
            if existing.get("setup_session_id") == body.session_id:
                raise HTTPException(status_code=409, detail="This payment has already been set up")
            db.collection("subscribers").document(doc.id).update(update_data)
        else:
            # Webhook may not have fired yet — create the doc
            update_data["email"] = email
            update_data["status"] = "active"
            update_data["created_at"] = now
            db.collection("subscribers").add(update_data)
    else:
        # One-time donation — look up by email so repeat donors update their existing shoutout
        docs = db.collection("donations").where("email", "==", email).limit(1).stream()
        doc = next(docs, None)
        if doc:
            existing = doc.to_dict()
            # Only block exact replay of the same session (prevent double-submit)
            if existing.get("setup_session_id") == body.session_id:
                raise HTTPException(status_code=409, detail="This payment has already been set up")
            db.collection("donations").document(doc.id).update(update_data)
        else:
            # Webhook may not have fired yet — create the doc
            update_data["email"] = email
            update_data["amount_cents"] = session.amount_total or 0
            update_data["total_donated_cents"] = session.amount_total or 0
            update_data["stripe_session_id"] = session.id
            update_data["created_at"] = now
            db.collection("donations").add(update_data)

    return SetupProfileResponse(
        display_name=display_name or None,
        note=note or None,
        note_is_public=False,  # notes are pending approval; not live yet
    )


@router.post("/cancel-request", dependencies=[Depends(rate_limit("cancel_request", 3, 600))])
async def cancel_request(body: CancelRequest):
    """Request subscription cancellation. Sends a confirmation email."""
    email = body.email.strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="Email is required")

    # Always return the same message (no info leak)
    generic_msg = {"message": "If an active subscription exists for this email, a confirmation link has been sent."}

    db = get_db()
    docs = (
        db.collection("subscribers")
        .where("email", "==", email)
        .where("status", "==", "active")
        .limit(1)
        .stream()
    )
    doc = next(docs, None)
    if doc is None:
        return generic_msg

    # Generate cancel token and send email
    token = create_cancel_token(email)
    cancel_url = f"{settings.frontend_url}/support/cancel?token={token}"

    try:
        await send_email(
            email,
            "Confirm your subscription cancellation",
            f"""
                <p>Hi,</p>
                <p>We received a request to cancel your MadeForSeconds subscription.</p>
                <p>Click the link below to confirm (expires in 1 hour):</p>
                <p><a href="{cancel_url}">Cancel my subscription</a></p>
                <p>If you didn't request this, you can safely ignore this email.</p>
                <p>— MadeForSeconds</p>
            """,
        )
    except Exception:
        logger.exception("Failed to send cancellation email")
        raise HTTPException(status_code=500, detail="Failed to send confirmation email. Please try again.")

    return generic_msg


@router.post("/cancel-confirm", dependencies=[Depends(rate_limit("cancel_confirm", 5, 600))])
async def cancel_confirm(body: CancelConfirmRequest):
    """Confirm subscription cancellation using a signed token from email."""
    email = verify_cancel_token(body.token)

    db = get_db()
    docs = (
        db.collection("subscribers")
        .where("email", "==", email)
        .where("status", "==", "active")
        .limit(1)
        .stream()
    )
    doc = next(docs, None)
    if doc is None:
        raise HTTPException(status_code=404, detail="No active subscription found")

    data = doc.to_dict()
    subscription_id = data.get("stripe_subscription_id")

    if subscription_id:
    
        try:
            stripe.Subscription.cancel(subscription_id)
        except stripe.InvalidRequestError:
            logger.warning("Stripe subscription already canceled (doc=%s)", doc.id)

    db.collection("subscribers").document(doc.id).update({
        "status": "canceled",
        "updated_at": datetime.now(timezone.utc),
    })

    # No Stripe event_id in this flow — it's a direct user action (a link
    # click), not webhook processing. keyed_hash lets repeated log lines
    # about the same person still correlate without logging their email.
    logger.info("Subscription canceled via email confirmation (donor=%s)", keyed_hash(email))
    return {"message": "Your subscription has been canceled. Thank you for your support!"}


@router.get("/supporters", response_model=list[Supporter])
async def list_supporters(limit: int | None = None):
    """Return display names and public notes of supporters, sorted by total donated."""
    db = get_db()
    supporters = []

    # Active subscribers with display names
    sub_docs = db.collection("subscribers").where("status", "==", "active").stream()
    for doc in sub_docs:
        data = doc.to_dict()
        name = data.get("display_name")
        if name and data.get("name_enabled", True):
            note = data.get("note") if (data.get("note_is_public") and data.get("note_enabled", True)) else None
            total = data.get("total_donated_cents", 0)
            supporters.append({"display_name": name, "note": note, "total": total})

    # One-time donors with display names
    donation_docs = db.collection("donations").stream()
    for doc in donation_docs:
        data = doc.to_dict()
        name = data.get("display_name")
        if name and data.get("name_enabled", True):
            note = data.get("note") if (data.get("note_is_public") and data.get("note_enabled", True)) else None
            total = data.get("total_donated_cents", data.get("amount_cents", 0))
            supporters.append({"display_name": name, "note": note, "total": total})

    # Sort by total donated (top donors first)
    supporters.sort(key=lambda s: s.get("total", 0), reverse=True)

    if limit and limit > 0:
        supporters = supporters[:limit]

    return [Supporter(display_name=s["display_name"], note=s.get("note")) for s in supporters]

