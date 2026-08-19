import logging
import re
from datetime import datetime, timezone

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from google.cloud.firestore import Increment, transactional
from pydantic import BaseModel, Field

from ..config import settings
from ..firestore import get_db
from ..rate_limit import rate_limit
from ..services.email import send_email
from ..subscriber_auth import create_cancel_token, verify_cancel_token

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/subscribe")

# Configure Stripe once at import time (thread-safe, no per-request mutation)
stripe.api_key = settings.stripe_secret_key

# How stale a "processing" webhook-event reservation must be before we assume
# the worker that created it crashed and it's safe to reclaim and reprocess.
_STALE_RESERVATION_SECONDS = 120


class WebhookProcessingError(Exception):
    """Raised by _handle_* functions when a webhook can't be processed yet
    (e.g. a referenced subscriber doc doesn't exist), so the caller re-raises
    and Stripe retries with backoff."""


def _reserve_event_logic(transaction, ref, event_type: str) -> str:
    """Decide whether this webhook event should be processed, and if so,
    write the reservation. Split out from _reserve_event (below) as a plain
    function so the decision logic is directly unit-testable without going
    through Firestore's transaction-retry machinery.

    Returns "reserved" (caller should process the event) or "skip".
    """
    snapshot = ref.get(transaction=transaction)
    now = datetime.now(timezone.utc)
    if snapshot.exists:
        data = snapshot.to_dict() or {}
        status = data.get("status")
        created_at = data.get("created_at")
        age = (now - created_at).total_seconds() if created_at else None
        if status == "completed":
            return "skip"
        if status == "processing" and age is not None and age < _STALE_RESERVATION_SECONDS:
            return "skip"
        # Stuck reservation (worker crashed before cleanup) — reclaim it.
    transaction.set(ref, {"type": event_type, "status": "processing", "created_at": now})
    return "reserved"


# The read-and-conditionally-write above runs inside one Firestore
# transaction, so two concurrent deliveries of the same (possibly stale)
# event can't both win the reservation — Firestore's optimistic concurrency
# lets only one transaction touching this doc commit; the other is retried
# automatically by the client library and will see the winner's fresh
# reservation on its retry.
_reserve_event = transactional(_reserve_event_logic)


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

    event_id = event.get("id", "")
    event_type = event["type"]
    data = event["data"]["object"]

    db = get_db()
    ref = db.collection("processed_events").document(event_id) if event_id else None

    # Idempotency: atomically reserve this event id before processing. The
    # read-and-conditionally-write happens inside one Firestore transaction,
    # so two concurrent deliveries (or a concurrent delivery plus a stale
    # crashed reservation) can't both win — see _reserve_event's docstring.
    if ref is not None:
        outcome = _reserve_event(db.transaction(), ref, event_type)
        if outcome == "skip":
            logger.info(f"Skipping event {event_id} (already processed or in flight)")
            return {"status": "ok"}

    try:
        if event_type == "checkout.session.completed":
            if data.get("mode") == "subscription":
                await _handle_subscription_checkout(data)
            elif data.get("mode") == "payment":
                await _handle_donation_checkout(data)

        elif event_type == "customer.subscription.updated":
            await _handle_subscription_updated(data)

        elif event_type == "customer.subscription.deleted":
            await _handle_subscription_deleted(data)

        elif event_type == "invoice.payment_failed":
            await _handle_payment_failed(data)

        elif event_type == "invoice.payment_succeeded":
            await _handle_payment_succeeded(data)
    except Exception as exc:
        if ref is not None:
            # Release the reservation so a legitimate Stripe retry can
            # re-reserve and fully reprocess this event.
            ref.delete()
        logger.exception(f"Webhook handler failed for event {event_id} ({event_type})")
        await _alert(
            f"Webhook processing failed: {event_type}",
            f"event_id={event_id}<br>error={exc}",
        )
        raise  # -> FastAPI 500 -> Stripe retries with backoff

    if ref is not None:
        ref.update({"status": "completed", "processed_at": datetime.now(timezone.utc)})

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
            logger.warning(f"Stripe subscription already canceled: {subscription_id}")

    db.collection("subscribers").document(doc.id).update({
        "status": "canceled",
        "updated_at": datetime.now(timezone.utc),
    })

    logger.info(f"Subscription canceled via email confirmation: {email}")
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


# ── Webhook handlers ─────────────────────────────────────────────────────────

async def _handle_subscription_checkout(data: dict) -> None:
    """Handle checkout.session.completed for subscription mode."""
    customer_id = data.get("customer")
    subscription_id = data.get("subscription")
    email = data.get("customer_details", {}).get("email", "").lower()
    amount_total = data.get("amount_total", 0)

    if not email:
        logger.warning("Subscription checkout missing email")
        await _alert(
            "Subscription checkout missing email",
            f"customer={customer_id}<br>subscription={subscription_id}<br>"
            "Stripe never captured an email for this checkout — retrying won't add one; "
            "needs manual reconciliation in the Stripe dashboard.",
        )
        return

    db = get_db()
    existing = (
        db.collection("subscribers")
        .where("email", "==", email)
        .limit(1)
        .stream()
    )
    existing_doc = next(existing, None)

    now = datetime.now(timezone.utc)
    subscriber_data = {
        "email": email,
        "stripe_customer_id": customer_id,
        "stripe_subscription_id": subscription_id,
        "status": "active",
        "total_donated_cents": amount_total,
        "updated_at": now,
    }

    if existing_doc:
        subscriber_data["total_donated_cents"] = Increment(amount_total)
        db.collection("subscribers").document(existing_doc.id).update(subscriber_data)
        logger.info(f"Updated subscriber: {email}")
    else:
        subscriber_data["created_at"] = now
        db.collection("subscribers").add(subscriber_data)
        logger.info(f"Created subscriber: {email}")


async def _handle_subscription_updated(data: dict) -> None:
    """Handle customer.subscription.updated."""
    subscription_id = data.get("id")
    status = data.get("status")
    current_period_end = data.get("current_period_end")

    db = get_db()
    docs = (
        db.collection("subscribers")
        .where("stripe_subscription_id", "==", subscription_id)
        .limit(1)
        .stream()
    )
    doc = next(docs, None)
    if doc is None:
        raise WebhookProcessingError(f"Subscription updated but no subscriber found: {subscription_id}")

    update_data: dict = {
        "status": status,
        "updated_at": datetime.now(timezone.utc),
    }
    if current_period_end:
        update_data["current_period_end"] = datetime.fromtimestamp(
            current_period_end, tz=timezone.utc
        )

    db.collection("subscribers").document(doc.id).update(update_data)
    logger.info(f"Subscription {subscription_id} updated to status: {status}")


async def _handle_subscription_deleted(data: dict) -> None:
    """Handle customer.subscription.deleted."""
    subscription_id = data.get("id")

    db = get_db()
    docs = (
        db.collection("subscribers")
        .where("stripe_subscription_id", "==", subscription_id)
        .limit(1)
        .stream()
    )
    doc = next(docs, None)
    if doc is None:
        raise WebhookProcessingError(f"Subscription deleted but no subscriber found: {subscription_id}")

    db.collection("subscribers").document(doc.id).update({
        "status": "canceled",
        "updated_at": datetime.now(timezone.utc),
    })
    logger.info(f"Subscription canceled: {subscription_id}")


async def _handle_payment_failed(data: dict) -> None:
    """Handle invoice.payment_failed."""
    subscription_id = data.get("subscription")
    if not subscription_id:
        return

    db = get_db()
    docs = (
        db.collection("subscribers")
        .where("stripe_subscription_id", "==", subscription_id)
        .limit(1)
        .stream()
    )
    doc = next(docs, None)
    if doc is None:
        raise WebhookProcessingError(f"Payment failed but no subscriber found: {subscription_id}")

    db.collection("subscribers").document(doc.id).update({
        "status": "past_due",
        "updated_at": datetime.now(timezone.utc),
    })
    logger.info(f"Payment failed for subscription: {subscription_id}")


async def _handle_payment_succeeded(data: dict) -> None:
    """Handle invoice.payment_succeeded — increment total_donated_cents for recurring payments.

    Skips the initial subscription invoice (billing_reason=subscription_create) because
    that amount is already recorded by _handle_subscription_checkout.
    """
    subscription_id = data.get("subscription")
    amount_paid = data.get("amount_paid", 0)  # in cents
    billing_reason = data.get("billing_reason", "")

    if not subscription_id or not amount_paid:
        return

    # The first invoice is already counted in _handle_subscription_checkout
    if billing_reason == "subscription_create":
        logger.info(f"Skipping initial invoice for subscription {subscription_id} (already counted at checkout)")
        return

    db = get_db()
    docs = (
        db.collection("subscribers")
        .where("stripe_subscription_id", "==", subscription_id)
        .limit(1)
        .stream()
    )
    doc = next(docs, None)
    if doc is None:
        raise WebhookProcessingError(f"Payment succeeded but no subscriber found: {subscription_id}")

    db.collection("subscribers").document(doc.id).update({
        "total_donated_cents": Increment(amount_paid),
        "updated_at": datetime.now(timezone.utc),
    })
    logger.info(f"Payment succeeded for subscription {subscription_id}: +{amount_paid} cents")


async def _handle_donation_checkout(data: dict) -> None:
    """Handle checkout.session.completed for one-time donation payments.

    Consolidates by email — repeat donors get their total accumulated on one doc.
    """
    email = data.get("customer_details", {}).get("email", "").lower()
    amount_total = data.get("amount_total", 0)
    session_id = data.get("id")
    now = datetime.now(timezone.utc)

    db = get_db()

    if email:
        # Check if this donor already has a doc — consolidate by email
        existing = (
            db.collection("donations")
            .where("email", "==", email)
            .limit(1)
            .stream()
        )
        existing_doc = next(existing, None)
        if existing_doc:
            db.collection("donations").document(existing_doc.id).update({
                "total_donated_cents": Increment(amount_total),
                "last_donation_cents": amount_total,
                "last_donated_at": now,
                "updated_at": now,
            })
            logger.info(f"Repeat donation: +{amount_total} cents from {email}")
            return

    db.collection("donations").add({
        "email": email or "anonymous",
        "amount_cents": amount_total,
        "total_donated_cents": amount_total,
        "stripe_session_id": session_id,
        "created_at": now,
    })
    logger.info(f"New donation recorded: {amount_total} cents from {email or 'anonymous'}")
