import logging
import re
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

import httpx
import stripe
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..config import settings
from ..firestore import get_db
from ..subscriber_auth import create_cancel_token, verify_cancel_token

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/subscribe")

# Simple in-memory rate limiter
_rate_attempts: dict[str, list[float]] = defaultdict(list)
CANCEL_RATE_LIMIT = 3  # max attempts
CANCEL_RATE_WINDOW = 600  # 10 minutes


def _sanitize(text: str, max_len: int) -> str:
    """Strip whitespace, collapse internal whitespace runs, remove control characters, enforce max length."""
    if not text:
        return ""
    # Remove control characters (keep normal unicode letters, emoji, punctuation)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    # Collapse multiple whitespace into single space
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_len]


def _check_rate_limit(ip: str, limit: int = CANCEL_RATE_LIMIT, window: int = CANCEL_RATE_WINDOW) -> None:
    now = time.time()
    _rate_attempts[ip] = [t for t in _rate_attempts[ip] if now - t < window]
    if len(_rate_attempts[ip]) >= limit:
        raise HTTPException(status_code=429, detail="Too many attempts. Try again later.")
    _rate_attempts[ip].append(now)


def _get_stripe() -> None:
    """Configure stripe with the secret key."""
    stripe.api_key = settings.stripe_secret_key


# ── Request/Response models ──────────────────────────────────────────────────

class CheckoutRequest(BaseModel):
    success_url: str
    cancel_url: str
    amount_cents: int  # amount in cents (min 100 = $1)
    one_time: bool = False  # True for one-time donation, False for monthly subscription


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

@router.post("/checkout", response_model=CheckoutResponse)
async def create_checkout(body: CheckoutRequest):
    """Create a Stripe Checkout session for a subscription or one-time donation."""
    _get_stripe()

    if not settings.stripe_secret_key or not settings.stripe_product_id:
        raise HTTPException(status_code=503, detail="Subscriptions not configured")

    if body.amount_cents < 100 or body.amount_cents > 50000:
        raise HTTPException(status_code=400, detail="Amount must be between $1 and $500")

    if body.one_time:
        # One-time payment
        session = stripe.checkout.Session.create(
            mode="payment",
            line_items=[{
                "price_data": {
                    "currency": "usd",
                    "product_data": {"name": "Support MadeForSeconds"},
                    "unit_amount": body.amount_cents,
                },
                "quantity": 1,
            }],
            success_url=body.success_url,
            cancel_url=body.cancel_url,
        )
    else:
        # Monthly subscription
        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{
                "price_data": {
                    "currency": "usd",
                    "product": settings.stripe_product_id,
                    "unit_amount": body.amount_cents,
                    "recurring": {"interval": "month"},
                },
                "quantity": 1,
            }],
            success_url=body.success_url,
            cancel_url=body.cancel_url,
        )

    return CheckoutResponse(checkout_url=session.url)


@router.post("/webhook")
async def stripe_webhook(request: Request):
    """Handle Stripe webhook events for subscriptions and donations."""
    _get_stripe()

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

    event_type = event["type"]
    data = event["data"]["object"]

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

    return {"status": "ok"}


@router.get("/session-info", response_model=SessionInfoResponse)
async def get_session_info(session_id: str):
    """Get info about a completed Stripe checkout session (no auth required — session_id is the proof)."""
    _get_stripe()

    try:
        session = stripe.checkout.Session.retrieve(session_id)
    except stripe.InvalidRequestError:
        raise HTTPException(status_code=404, detail="Session not found")

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


@router.post("/setup-profile", response_model=SetupProfileResponse)
async def setup_profile(body: SetupProfileRequest):
    """Set display name and note after payment. Uses Stripe session_id as proof — no login needed."""
    _get_stripe()

    # Verify the session with Stripe
    try:
        session = stripe.checkout.Session.retrieve(body.session_id)
    except stripe.InvalidRequestError:
        raise HTTPException(status_code=404, detail="Session not found")

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


@router.post("/cancel-request")
async def cancel_request(body: CancelRequest, request: Request):
    """Request subscription cancellation. Sends a confirmation email."""
    ip = request.client.host if request.client else "unknown"
    _check_rate_limit(ip)

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

    if settings.resend_api_key:
        try:
            async with httpx.AsyncClient() as client:
                await client.post(
                    "https://api.resend.com/emails",
                    headers={"Authorization": f"Bearer {settings.resend_api_key}"},
                    json={
                        "from": "MadeForSeconds <noreply@madeforseconds.com>",
                        "to": [email],
                        "subject": "Confirm your subscription cancellation",
                        "html": f"""
                            <p>Hi,</p>
                            <p>We received a request to cancel your MadeForSeconds subscription.</p>
                            <p>Click the link below to confirm (expires in 1 hour):</p>
                            <p><a href="{cancel_url}">Cancel my subscription</a></p>
                            <p>If you didn't request this, you can safely ignore this email.</p>
                            <p>— MadeForSeconds</p>
                        """,
                    },
                    timeout=10.0,
                )
        except Exception:
            logger.exception("Failed to send cancellation email")
            raise HTTPException(status_code=500, detail="Failed to send confirmation email. Please try again.")
    else:
        # Dev mode: log the cancel link
        logger.info(f"[DEV] Cancel link for {email}: {cancel_url}")

    return generic_msg


@router.post("/cancel-confirm")
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
        _get_stripe()
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
async def list_supporters(limit: Optional[int] = None):
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
        # Keep existing total and add to it
        existing_data = existing_doc.to_dict()
        existing_total = existing_data.get("total_donated_cents", 0)
        subscriber_data["total_donated_cents"] = existing_total + amount_total
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
        logger.warning(f"Subscription updated but no subscriber found: {subscription_id}")
        return

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
        return

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
        return

    db.collection("subscribers").document(doc.id).update({
        "status": "past_due",
        "updated_at": datetime.now(timezone.utc),
    })
    logger.info(f"Payment failed for subscription: {subscription_id}")


async def _handle_payment_succeeded(data: dict) -> None:
    """Handle invoice.payment_succeeded — increment total_donated_cents for recurring payments."""
    subscription_id = data.get("subscription")
    amount_paid = data.get("amount_paid", 0)  # in cents

    if not subscription_id or not amount_paid:
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
        return

    existing_data = doc.to_dict()
    existing_total = existing_data.get("total_donated_cents", 0)

    db.collection("subscribers").document(doc.id).update({
        "total_donated_cents": existing_total + amount_paid,
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
            existing_data = existing_doc.to_dict()
            prev_total = existing_data.get("total_donated_cents", existing_data.get("amount_cents", 0))
            db.collection("donations").document(existing_doc.id).update({
                "total_donated_cents": prev_total + amount_total,
                "last_donation_cents": amount_total,
                "last_donated_at": now,
                "updated_at": now,
            })
            logger.info(f"Repeat donation: +{amount_total} cents from {email} (new total: {prev_total + amount_total})")
            return

    db.collection("donations").add({
        "email": email or "anonymous",
        "amount_cents": amount_total,
        "total_donated_cents": amount_total,
        "stripe_session_id": session_id,
        "created_at": now,
    })
    logger.info(f"New donation recorded: {amount_total} cents from {email or 'anonymous'}")
