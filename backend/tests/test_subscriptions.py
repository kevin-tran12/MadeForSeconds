import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta, timezone
import stripe
from google.api_core.exceptions import AlreadyExists
from google.cloud.firestore import Increment
from app.routes.subscriptions import WebhookProcessingError

@pytest.fixture(autouse=True)
def mock_stripe_settings():
    with patch("app.routes.subscriptions.settings") as mock_settings:
        mock_settings.stripe_secret_key = "sk_test_123"
        mock_settings.stripe_product_id = "prod_123"
        mock_settings.cors_origins = ["https://madeforseconds.com"]
        mock_settings.stripe_webhook_secret = "whsec_123"
        mock_settings.frontend_url = "https://madeforseconds.com"
        yield mock_settings

def test_create_checkout_subscription(client, mock_stripe):
    """Verifies Stripe session creation for recurring mode."""
    mock_stripe.checkout.Session.create.return_value = MagicMock(url="https://stripe.com/checkout")
    
    payload = {
        "success_url": "https://madeforseconds.com/success",
        "cancel_url": "https://madeforseconds.com/cancel",
        "amount_cents": 1000,
        "one_time": False
    }
    
    response = client.post("/api/subscribe/checkout", json=payload)
    assert response.status_code == 200
    assert response.json()["checkout_url"] == "https://stripe.com/checkout"
    
    mock_stripe.checkout.Session.create.assert_called_once()
    args = mock_stripe.checkout.Session.create.call_args[1]
    assert args["mode"] == "subscription"

def test_create_checkout_one_time(client, mock_stripe):
    """Verifies Stripe session creation for payment mode."""
    mock_stripe.checkout.Session.create.return_value = MagicMock(url="https://stripe.com/checkout")
    
    payload = {
        "success_url": "https://madeforseconds.com/success",
        "cancel_url": "https://madeforseconds.com/cancel",
        "amount_cents": 1000,
        "one_time": True
    }
    
    response = client.post("/api/subscribe/checkout", json=payload)
    assert response.status_code == 200
    assert response.json()["checkout_url"] == "https://stripe.com/checkout"
    
    args = mock_stripe.checkout.Session.create.call_args[1]
    assert args["mode"] == "payment"

def test_create_checkout_invalid_amount(client):
    """Rejects amounts outside bounds."""
    payload = {
        "success_url": "https://madeforseconds.com/success",
        "cancel_url": "https://madeforseconds.com/cancel",
        "amount_cents": 50, # Too low
    }
    response = client.post("/api/subscribe/checkout", json=payload)
    assert response.status_code == 400

def test_webhook_checkout_completed_subscription(client, mock_db, mock_stripe):
    """Verifies that a completed subscription checkout creates/updates a subscriber."""
    # Mock stripe.Webhook.construct_event
    with patch("app.routes.subscriptions.stripe.Webhook.construct_event") as mock_construct:
        mock_construct.return_value = {
            "id": "evt_123",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "mode": "subscription",
                    "customer": "cus_123",
                    "subscription": "sub_123",
                    "customer_details": {"email": "test@example.com"},
                    "amount_total": 1000
                }
            }
        }
        
        # Idempotency check: event does not exist
        mock_db.collection.return_value.document.return_value.get.return_value.exists = False
        
        # Subscriber lookup: does not exist
        mock_db.collection.return_value.where.return_value.limit.return_value.stream.return_value = iter([])
        
        response = client.post("/api/subscribe/webhook", content=b"payload", headers={"stripe-signature": "sig"})
        assert response.status_code == 200
        
        # Check that subscriber was added
        # collection("subscribers").add(...)
        mock_db.collection.assert_any_call("subscribers")
        mock_db.collection.return_value.add.assert_called_once()

def test_webhook_invalid_signature(client):
    """Returns 400 on bad sig."""
    # Patch only the construct_event function, so stripe.SignatureVerificationError is still the real class
    with patch("stripe.Webhook.construct_event") as mock_construct:
        mock_construct.side_effect = stripe.SignatureVerificationError("Invalid signature", "sig_header")
        response = client.post("/api/subscribe/webhook", content=b"payload", headers={"stripe-signature": "bad"})
        assert response.status_code == 400

def test_session_info_valid(client, mock_stripe, mock_db):
    """Returns email and payment type for a valid session."""
    mock_session = MagicMock()
    mock_session.payment_status = "paid"
    mock_session.mode = "subscription"
    mock_session.amount_total = 1000
    mock_session.customer_details.email = "test@example.com"
    mock_session.id = "sess_123"
    mock_stripe.checkout.Session.retrieve.return_value = mock_session
    
    # Subscriber lookup for already_set_up
    mock_doc = MagicMock()
    mock_doc.to_dict.return_value = {"setup_session_id": "sess_123"}
    mock_db.collection.return_value.where.return_value.limit.return_value.stream.return_value = iter([mock_doc])
    
    response = client.get("/api/subscribe/session-info?session_id=sess_123")
    assert response.status_code == 200
    assert response.json()["email"] == "test@example.com"
    assert response.json()["already_set_up"] is True

def test_setup_profile(client, mock_stripe, mock_db):
    """Writes display_name and note_pending to Firestore."""
    mock_session = MagicMock()
    mock_session.payment_status = "paid"
    mock_session.mode = "subscription"
    mock_session.customer_details.email = "test@example.com"
    mock_session.id = "sess_123"
    mock_stripe.checkout.Session.retrieve.return_value = mock_session
    
    # Existing subscriber lookup
    mock_doc = MagicMock()
    mock_doc.id = "sub_doc_123"
    mock_doc.to_dict.return_value = {"setup_session_id": "other_sess"}
    mock_db.collection.return_value.where.return_value.limit.return_value.stream.return_value = iter([mock_doc])
    
    payload = {
        "session_id": "sess_123",
        "display_name": "New Name",
        "note": "New Note",
        "note_is_public": True
    }
    
    response = client.post("/api/subscribe/setup-profile", json=payload)
    assert response.status_code == 200
    assert response.json()["display_name"] == "New Name"
    
    # Verify update call
    mock_db.collection.return_value.document.return_value.update.assert_called_once()
    args = mock_db.collection.return_value.document.return_value.update.call_args[0][0]
    assert args["display_name"] == "New Name"
    assert args["note_pending"] == "New Note"

def test_cancel_request_sends_email(client, mock_db):
    """Verifies that cancel request finds subscriber and 'sends' email."""
    mock_doc = MagicMock()
    mock_doc.to_dict.return_value = {"email": "test@example.com"}
    mock_db.collection.return_value.where.return_value.where.return_value.limit.return_value.stream.return_value = iter([mock_doc])
    
    with patch("app.routes.subscriptions.settings") as mock_settings, \
         patch("app.services.email.settings") as mock_email_settings, \
         patch("app.services.email.httpx.AsyncClient.post") as mock_post:
        mock_settings.frontend_url = "https://madeforseconds.com"
        mock_email_settings.resend_api_key = "fake_key"
        mock_post.return_value = MagicMock(status_code=200)
        
        response = client.post("/api/subscribe/cancel-request", json={"email": "test@example.com"})
        assert response.status_code == 200
        mock_post.assert_called_once()

def test_cancel_confirm_valid_token(client, mock_db, mock_stripe):
    """Cancels Stripe subscription with valid token."""
    with patch("app.routes.subscriptions.verify_cancel_token", return_value="test@example.com"):
        mock_doc = MagicMock()
        mock_doc.id = "sub_doc_1"
        mock_doc.to_dict.return_value = {"stripe_subscription_id": "sub_123"}
        mock_db.collection.return_value.where.return_value.where.return_value.limit.return_value.stream.return_value = iter([mock_doc])
        
        response = client.post("/api/subscribe/cancel-confirm", json={"token": "valid_token"})
        assert response.status_code == 200
        mock_stripe.Subscription.cancel.assert_called_once_with("sub_123")
        mock_db.collection.return_value.document.return_value.update.assert_called_once()

def test_public_supporters_list(client, mock_db):
    """Returns only name_enabled supporters."""
    # Subscriber doc
    sub_doc = MagicMock()
    sub_doc.to_dict.return_value = {
        "display_name": "Sub 1",
        "name_enabled": True,
        "status": "active"
    }
    # Donation doc
    don_doc = MagicMock()
    don_doc.to_dict.return_value = {
        "display_name": "Don 1",
        "name_enabled": False # Should be hidden
    }
    
    mock_db.collection.side_effect = [
        MagicMock(where=MagicMock(return_value=MagicMock(stream=MagicMock(return_value=iter([sub_doc]))))), # subscribers
        MagicMock(stream=MagicMock(return_value=iter([don_doc]))) # donations
    ]
    
    response = client.get("/api/subscribe/supporters")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["display_name"] == "Sub 1"


# ── Webhook idempotency (atomic reservation) ─────────────────────────────────

def _subscription_checkout_event(event_id="evt_1", email="test@example.com", amount_total=1000):
    return {
        "id": event_id,
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "mode": "subscription",
                "customer": "cus_123",
                "subscription": "sub_123",
                "customer_details": {"email": email} if email else {},
                "amount_total": amount_total,
            }
        },
    }


def test_webhook_duplicate_completed_event_skipped(client, mock_db, mock_stripe):
    """A redelivered event whose reservation is already 'completed' is skipped entirely."""
    with patch("app.routes.subscriptions.stripe.Webhook.construct_event") as mock_construct:
        mock_construct.return_value = _subscription_checkout_event()
        mock_db.collection.return_value.document.return_value.create.side_effect = AlreadyExists("dup")
        mock_db.collection.return_value.document.return_value.get.return_value.to_dict.return_value = {
            "status": "completed"
        }

        response = client.post("/api/subscribe/webhook", content=b"payload", headers={"stripe-signature": "sig"})
        assert response.status_code == 200
        mock_db.collection.return_value.add.assert_not_called()


def test_webhook_fresh_processing_reservation_skipped(client, mock_db, mock_stripe):
    """A concurrent delivery of the same event, still within the reservation, is skipped."""
    with patch("app.routes.subscriptions.stripe.Webhook.construct_event") as mock_construct:
        mock_construct.return_value = _subscription_checkout_event()
        mock_db.collection.return_value.document.return_value.create.side_effect = AlreadyExists("dup")
        mock_db.collection.return_value.document.return_value.get.return_value.to_dict.return_value = {
            "status": "processing",
            "created_at": datetime.now(timezone.utc),
        }

        response = client.post("/api/subscribe/webhook", content=b"payload", headers={"stripe-signature": "sig"})
        assert response.status_code == 200
        mock_db.collection.return_value.add.assert_not_called()


def test_webhook_stale_processing_reservation_reclaimed_and_reprocessed(client, mock_db, mock_stripe):
    """A reservation stuck in 'processing' past the staleness window is reclaimed and reprocessed."""
    with patch("app.routes.subscriptions.stripe.Webhook.construct_event") as mock_construct:
        mock_construct.return_value = _subscription_checkout_event()
        mock_db.collection.return_value.document.return_value.create.side_effect = AlreadyExists("dup")
        mock_db.collection.return_value.document.return_value.get.return_value.to_dict.return_value = {
            "status": "processing",
            "created_at": datetime.now(timezone.utc) - timedelta(seconds=200),
        }
        mock_db.collection.return_value.where.return_value.limit.return_value.stream.return_value = iter([])

        response = client.post("/api/subscribe/webhook", content=b"payload", headers={"stripe-signature": "sig"})
        assert response.status_code == 200
        mock_db.collection.return_value.add.assert_called_once()


def test_webhook_handler_exception_deletes_reservation_and_alerts(client, mock_db, mock_stripe):
    """A failing handler releases the reservation (so Stripe's retry can reprocess),
    alerts, and re-raises (-> FastAPI 500 -> Stripe retries with backoff).

    TestClient's default raise_server_exceptions=True means the unhandled
    exception propagates into the test rather than becoming a response object
    here, same as any other uncaught-exception route in this app — assert the
    cleanup/alert side effects happened before it did.
    """
    with (
        patch("app.routes.subscriptions.stripe.Webhook.construct_event") as mock_construct,
        patch("app.routes.subscriptions._handle_subscription_checkout", side_effect=RuntimeError("boom")),
        patch("app.routes.subscriptions._alert") as mock_alert,
    ):
        mock_construct.return_value = _subscription_checkout_event()

        with pytest.raises(RuntimeError):
            client.post("/api/subscribe/webhook", content=b"payload", headers={"stripe-signature": "sig"})

        mock_db.collection.return_value.document.return_value.delete.assert_called_once()
        mock_alert.assert_called_once()


# ── Silent-loss paths ─────────────────────────────────────────────────────────

def test_subscription_checkout_missing_email_alerts_and_returns_200(client, mock_db, mock_stripe):
    with (
        patch("app.routes.subscriptions.stripe.Webhook.construct_event") as mock_construct,
        patch("app.routes.subscriptions._alert") as mock_alert,
    ):
        mock_construct.return_value = _subscription_checkout_event(email=None)

        response = client.post("/api/subscribe/webhook", content=b"payload", headers={"stripe-signature": "sig"})
        assert response.status_code == 200
        mock_alert.assert_called_once()
        assert "missing email" in mock_alert.call_args[0][0].lower()
        mock_db.collection.return_value.add.assert_not_called()


@pytest.mark.parametrize(
    "event_type,data",
    [
        ("customer.subscription.updated", {"id": "sub_123", "status": "past_due"}),
        ("customer.subscription.deleted", {"id": "sub_123"}),
        (
            "invoice.payment_failed",
            {"subscription": "sub_123"},
        ),
        (
            "invoice.payment_succeeded",
            {"subscription": "sub_123", "amount_paid": 500, "billing_reason": "invoice"},
        ),
    ],
)
def test_webhook_event_with_no_matching_subscriber_raises(client, mock_db, mock_stripe, event_type, data):
    """Event-ordering races (e.g. .updated arriving before checkout.session.completed
    finishes) must force a Stripe retry rather than silently drop the event."""
    with (
        patch("app.routes.subscriptions.stripe.Webhook.construct_event") as mock_construct,
        patch("app.routes.subscriptions._alert") as mock_alert,
    ):
        mock_construct.return_value = {
            "id": "evt_race",
            "type": event_type,
            "data": {"object": data},
        }
        mock_db.collection.return_value.where.return_value.limit.return_value.stream.return_value = iter([])

        with pytest.raises(WebhookProcessingError):
            client.post("/api/subscribe/webhook", content=b"payload", headers={"stripe-signature": "sig"})

        mock_db.collection.return_value.document.return_value.delete.assert_called_once()
        mock_alert.assert_called_once()


# ── Safe amount accumulation (Increment, not read-then-write) ────────────────

def test_subscription_checkout_existing_subscriber_uses_increment(client, mock_db, mock_stripe):
    with patch("app.routes.subscriptions.stripe.Webhook.construct_event") as mock_construct:
        mock_construct.return_value = _subscription_checkout_event(amount_total=500)
        existing_doc = MagicMock()
        existing_doc.id = "doc_1"
        mock_db.collection.return_value.where.return_value.limit.return_value.stream.return_value = iter([existing_doc])

        response = client.post("/api/subscribe/webhook", content=b"payload", headers={"stripe-signature": "sig"})
        assert response.status_code == 200

        update_calls = mock_db.collection.return_value.document.return_value.update.call_args_list
        amount_updates = [
            c.args[0]["total_donated_cents"]
            for c in update_calls
            if c.args and "total_donated_cents" in c.args[0]
        ]
        assert len(amount_updates) == 1
        assert isinstance(amount_updates[0], Increment)


def test_payment_succeeded_uses_increment(client, mock_db, mock_stripe):
    with patch("app.routes.subscriptions.stripe.Webhook.construct_event") as mock_construct:
        mock_construct.return_value = {
            "id": "evt_pay",
            "type": "invoice.payment_succeeded",
            "data": {"object": {"subscription": "sub_123", "amount_paid": 700, "billing_reason": "invoice"}},
        }
        existing_doc = MagicMock()
        existing_doc.id = "doc_1"
        mock_db.collection.return_value.where.return_value.limit.return_value.stream.return_value = iter([existing_doc])

        response = client.post("/api/subscribe/webhook", content=b"payload", headers={"stripe-signature": "sig"})
        assert response.status_code == 200

        update_calls = mock_db.collection.return_value.document.return_value.update.call_args_list
        amount_updates = [
            c.args[0]["total_donated_cents"]
            for c in update_calls
            if c.args and "total_donated_cents" in c.args[0]
        ]
        assert len(amount_updates) == 1
        assert isinstance(amount_updates[0], Increment)


def test_donation_checkout_repeat_donor_uses_increment(client, mock_db, mock_stripe):
    with patch("app.routes.subscriptions.stripe.Webhook.construct_event") as mock_construct:
        mock_construct.return_value = {
            "id": "evt_don",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "mode": "payment",
                    "id": "sess_123",
                    "customer_details": {"email": "donor@example.com"},
                    "amount_total": 300,
                }
            },
        }
        existing_doc = MagicMock()
        existing_doc.id = "doc_1"
        mock_db.collection.return_value.where.return_value.limit.return_value.stream.return_value = iter([existing_doc])

        response = client.post("/api/subscribe/webhook", content=b"payload", headers={"stripe-signature": "sig"})
        assert response.status_code == 200

        update_calls = mock_db.collection.return_value.document.return_value.update.call_args_list
        amount_updates = [
            c.args[0]["total_donated_cents"]
            for c in update_calls
            if c.args and "total_donated_cents" in c.args[0]
        ]
        assert len(amount_updates) == 1
        assert isinstance(amount_updates[0], Increment)


def test_donation_checkout_new_anonymous_donor_creates_doc(client, mock_db, mock_stripe):
    """One-time donation with no email — previously-untested event shape."""
    with patch("app.routes.subscriptions.stripe.Webhook.construct_event") as mock_construct:
        mock_construct.return_value = {
            "id": "evt_anon",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "mode": "payment",
                    "id": "sess_456",
                    "customer_details": {},
                    "amount_total": 200,
                }
            },
        }

        response = client.post("/api/subscribe/webhook", content=b"payload", headers={"stripe-signature": "sig"})
        assert response.status_code == 200
        mock_db.collection.return_value.add.assert_called_once()
        added = mock_db.collection.return_value.add.call_args[0][0]
        assert added["email"] == "anonymous"


# ── Rate limiting on subscribe endpoints ─────────────────────────────────────

def test_cancel_request_rate_limited_after_three_attempts(client, mock_db):
    mock_db.collection.return_value.where.return_value.where.return_value.limit.return_value.stream.return_value = iter([])

    for _ in range(3):
        response = client.post("/api/subscribe/cancel-request", json={"email": "test@example.com"})
        assert response.status_code == 200

    response = client.post("/api/subscribe/cancel-request", json={"email": "test@example.com"})
    assert response.status_code == 429
    assert response.headers["retry-after"] == "600"


def test_checkout_rate_limited_after_twenty_attempts(client, mock_stripe):
    mock_stripe.checkout.Session.create.return_value = MagicMock(url="https://stripe.com/checkout")
    payload = {
        "success_url": "https://madeforseconds.com/success",
        "cancel_url": "https://madeforseconds.com/cancel",
        "amount_cents": 1000,
        "one_time": True,
    }
    for _ in range(20):
        assert client.post("/api/subscribe/checkout", json=payload).status_code == 200

    response = client.post("/api/subscribe/checkout", json=payload)
    assert response.status_code == 429
