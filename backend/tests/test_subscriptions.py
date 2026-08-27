import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta, timezone
import stripe
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

@pytest.fixture
def mock_process_event():
    """Patches the whole transactional webhook-processing function so route
    tests can verify outer wiring (outcome -> alert dispatch, exception ->
    alert + raise) without depending on Firestore's transaction-retry
    machinery. That machinery and the processing/business logic itself are
    covered by direct unit tests of _process_event_logic / _apply_* /
    _read_existing_doc further down, using plain fakes instead of mocking
    the Firestore SDK's internals."""
    with patch("app.routes.subscriptions._process_event") as mock:
        yield mock

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


# ── Webhook processing: fakes (no Firestore SDK / transaction-retry machinery) ──

class FakeDocRef:
    """Stand-in for a Firestore DocumentReference."""
    def __init__(self, doc_id="fake-doc"):
        self.id = doc_id


class FakeSnapshot:
    def __init__(self, exists, data=None, ref=None):
        self.exists = exists
        self._data = data or {}
        self.reference = ref or FakeDocRef()

    def to_dict(self):
        return self._data


class FakeTransaction:
    """Minimal stand-in for a Firestore Transaction — just records
    .set()/.update() calls; doesn't simulate real commit/rollback atomicity
    (that's the SDK's job, not something mockable here — see the docstring
    on test_process_event_logic_no_matching_subscriber_raises_without_committing)."""
    def __init__(self):
        self.set_calls = []
        self.update_calls = []

    def set(self, ref, data):
        self.set_calls.append((ref, data))

    def update(self, ref, data):
        self.update_calls.append((ref, data))


class FakeRef:
    """Stand-in for the processed_events DocumentReference (the reservation doc)."""
    def __init__(self, snapshot):
        self._snapshot = snapshot

    def get(self, transaction=None):
        return self._snapshot


class FakeQuery:
    def __init__(self, docs):
        self._docs = docs

    def where(self, *a, **kw):
        return self

    def limit(self, *a, **kw):
        return self

    def stream(self, transaction=None):
        return iter(self._docs)


class FakeCollection:
    """Stand-in for a Firestore CollectionReference — .where(...) returns
    pre-seeded query results, .document() generates a fresh ref (mirrors
    the real client-side-generated-ID behavior used instead of .add())."""
    def __init__(self, docs=None):
        self._docs = docs or []

    def where(self, *a, **kw):
        return FakeQuery(self._docs)

    def document(self):
        return FakeDocRef("new-doc")


class FakeDb:
    """Stand-in for the Firestore Client — routes collection(name) to
    pre-seeded fake collections; unlisted collections are empty."""
    def __init__(self, **collections):
        self._collections = collections

    def collection(self, name):
        return self._collections.get(name, FakeCollection())


_NOW = datetime.now(timezone.utc)


class _FakeStripeObject:
    """Mimics stripe.StripeObject well enough to catch what a plain-dict
    mock can't: __getitem__ and __contains__ work, but .get() raises
    AttributeError, same as the real object stripe.Webhook.construct_event
    returns in production. Recursively wraps nested dicts so
    event["data"]["object"] behaves the same way too."""

    def __init__(self, data: dict):
        self._data = {k: _FakeStripeObject(v) if isinstance(v, dict) else v for k, v in data.items()}

    def __getitem__(self, key):
        return self._data[key]

    def __contains__(self, key):
        return key in self._data

    def to_dict(self):
        return {k: v.to_dict() if isinstance(v, _FakeStripeObject) else v for k, v in self._data.items()}


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


# ── _read_existing_doc ───────────────────────────────────────────────────────

def test_read_existing_doc_subscription_checkout_finds_by_email():
    from app.routes.subscriptions import _read_existing_doc
    existing = FakeSnapshot(exists=True, data={"email": "a@b.com"})
    db = FakeDb(subscribers=FakeCollection(docs=[existing]))
    data = {"mode": "subscription", "customer_details": {"email": "a@b.com"}}
    assert _read_existing_doc(FakeTransaction(), db, "checkout.session.completed", data) is existing


def test_read_existing_doc_no_email_returns_none():
    from app.routes.subscriptions import _read_existing_doc
    db = FakeDb(subscribers=FakeCollection(docs=[FakeSnapshot(exists=True)]))
    data = {"mode": "subscription", "customer_details": {}}
    assert _read_existing_doc(FakeTransaction(), db, "checkout.session.completed", data) is None


def test_read_existing_doc_subscription_updated_by_id():
    from app.routes.subscriptions import _read_existing_doc
    existing = FakeSnapshot(exists=True)
    db = FakeDb(subscribers=FakeCollection(docs=[existing]))
    assert _read_existing_doc(FakeTransaction(), db, "customer.subscription.updated", {"id": "sub_1"}) is existing


def test_read_existing_doc_not_found_returns_none():
    from app.routes.subscriptions import _read_existing_doc
    db = FakeDb(subscribers=FakeCollection(docs=[]))
    assert _read_existing_doc(FakeTransaction(), db, "customer.subscription.updated", {"id": "sub_1"}) is None


# ── _apply_* (write-phase business logic) ────────────────────────────────────

def test_apply_subscription_checkout_missing_email():
    from app.routes.subscriptions import _apply_subscription_checkout
    txn = FakeTransaction()
    outcome = _apply_subscription_checkout(txn, FakeDb(), {"customer_details": {}}, None, _NOW)
    assert outcome == "missing_email"
    assert txn.set_calls == [] and txn.update_calls == []


def test_apply_subscription_checkout_new_subscriber_sets_plain_total():
    from app.routes.subscriptions import _apply_subscription_checkout
    txn = FakeTransaction()
    db = FakeDb(subscribers=FakeCollection())
    data = {
        "customer": "cus_1", "subscription": "sub_1",
        "customer_details": {"email": "a@b.com"}, "amount_total": 1000,
    }
    outcome = _apply_subscription_checkout(txn, db, data, None, _NOW)
    assert outcome == "processed"
    assert len(txn.set_calls) == 1
    _, payload = txn.set_calls[0]
    assert payload["email"] == "a@b.com"
    assert payload["total_donated_cents"] == 1000  # plain int on create — nothing to increment yet


def test_apply_subscription_checkout_existing_subscriber_uses_increment():
    from app.routes.subscriptions import _apply_subscription_checkout
    txn = FakeTransaction()
    existing = FakeSnapshot(exists=True, data={"email": "a@b.com"})
    data = {
        "customer": "cus_1", "subscription": "sub_1",
        "customer_details": {"email": "a@b.com"}, "amount_total": 500,
    }
    outcome = _apply_subscription_checkout(txn, FakeDb(), data, existing, _NOW)
    assert outcome == "processed"
    assert len(txn.update_calls) == 1
    ref, payload = txn.update_calls[0]
    assert ref is existing.reference
    assert isinstance(payload["total_donated_cents"], Increment)


def test_apply_subscription_updated_not_found_raises():
    from app.routes.subscriptions import _apply_subscription_updated
    with pytest.raises(WebhookProcessingError):
        _apply_subscription_updated(FakeTransaction(), {"id": "sub_1"}, None, _NOW)


def test_apply_subscription_updated_found_updates_status():
    from app.routes.subscriptions import _apply_subscription_updated
    txn = FakeTransaction()
    existing = FakeSnapshot(exists=True)
    outcome = _apply_subscription_updated(txn, {"id": "sub_1", "status": "past_due"}, existing, _NOW)
    assert outcome == "processed"
    assert txn.update_calls[0][1]["status"] == "past_due"


def test_apply_subscription_deleted_not_found_raises():
    from app.routes.subscriptions import _apply_subscription_deleted
    with pytest.raises(WebhookProcessingError):
        _apply_subscription_deleted(FakeTransaction(), {"id": "sub_1"}, None, _NOW)


def test_apply_subscription_deleted_found_cancels():
    from app.routes.subscriptions import _apply_subscription_deleted
    txn = FakeTransaction()
    existing = FakeSnapshot(exists=True)
    outcome = _apply_subscription_deleted(txn, {"id": "sub_1"}, existing, _NOW)
    assert outcome == "processed"
    assert txn.update_calls[0][1]["status"] == "canceled"


def test_apply_payment_failed_no_subscription_id_ignored():
    from app.routes.subscriptions import _apply_payment_failed
    txn = FakeTransaction()
    outcome = _apply_payment_failed(txn, {}, None, _NOW)
    assert outcome == "ignored"
    assert txn.update_calls == []


def test_apply_payment_failed_not_found_raises():
    from app.routes.subscriptions import _apply_payment_failed
    with pytest.raises(WebhookProcessingError):
        _apply_payment_failed(FakeTransaction(), {"subscription": "sub_1"}, None, _NOW)


def test_apply_payment_succeeded_subscription_create_ignored():
    from app.routes.subscriptions import _apply_payment_succeeded
    txn = FakeTransaction()
    data = {"subscription": "sub_1", "amount_paid": 500, "billing_reason": "subscription_create"}
    outcome = _apply_payment_succeeded(txn, data, None, _NOW)
    assert outcome == "ignored"
    assert txn.update_calls == []


def test_apply_payment_succeeded_not_found_raises():
    from app.routes.subscriptions import _apply_payment_succeeded
    data = {"subscription": "sub_1", "amount_paid": 500, "billing_reason": "invoice"}
    with pytest.raises(WebhookProcessingError):
        _apply_payment_succeeded(FakeTransaction(), data, None, _NOW)


def test_apply_payment_succeeded_uses_increment():
    from app.routes.subscriptions import _apply_payment_succeeded
    txn = FakeTransaction()
    existing = FakeSnapshot(exists=True)
    data = {"subscription": "sub_1", "amount_paid": 700, "billing_reason": "invoice"}
    outcome = _apply_payment_succeeded(txn, data, existing, _NOW)
    assert outcome == "processed"
    assert isinstance(txn.update_calls[0][1]["total_donated_cents"], Increment)


def test_apply_donation_checkout_repeat_donor_uses_increment():
    from app.routes.subscriptions import _apply_donation_checkout
    txn = FakeTransaction()
    existing = FakeSnapshot(exists=True)
    data = {"customer_details": {"email": "donor@example.com"}, "amount_total": 300, "id": "sess_1"}
    outcome = _apply_donation_checkout(txn, FakeDb(), data, existing, _NOW)
    assert outcome == "processed"
    assert isinstance(txn.update_calls[0][1]["total_donated_cents"], Increment)


def test_apply_donation_checkout_anonymous_creates_new_doc():
    from app.routes.subscriptions import _apply_donation_checkout
    txn = FakeTransaction()
    db = FakeDb(donations=FakeCollection())
    data = {"customer_details": {}, "amount_total": 200, "id": "sess_2"}
    outcome = _apply_donation_checkout(txn, db, data, None, _NOW)
    assert outcome == "processed"
    assert txn.set_calls[0][1]["email"] == "anonymous"


# ── _process_event_logic (full read+write phase, exactly-once processing) ───

def test_process_event_logic_absent_reservation_processes_and_completes():
    from app.routes.subscriptions import _process_event_logic
    txn = FakeTransaction()
    ref = FakeRef(FakeSnapshot(exists=False))
    db = FakeDb(subscribers=FakeCollection())
    data = {
        "mode": "subscription", "customer": "cus_1", "subscription": "sub_1",
        "customer_details": {"email": "a@b.com"}, "amount_total": 1000,
    }
    outcome = _process_event_logic(txn, ref, db, "checkout.session.completed", data, _NOW)
    assert outcome == "processed"
    # reservation "processing" write + the new subscriber doc write
    assert len(txn.set_calls) == 2
    # exactly one completion update, and it happens after both set() calls
    assert len(txn.update_calls) == 1
    assert txn.update_calls[0][1]["status"] == "completed"


def test_process_event_logic_completed_reservation_skips_without_mutation():
    from app.routes.subscriptions import _process_event_logic
    txn = FakeTransaction()
    ref = FakeRef(FakeSnapshot(exists=True, data={"status": "completed"}))
    outcome = _process_event_logic(txn, ref, FakeDb(), "checkout.session.completed", {"mode": "subscription"}, _NOW)
    assert outcome == "skip"
    assert txn.set_calls == [] and txn.update_calls == []


def test_process_event_logic_fresh_processing_skips():
    from app.routes.subscriptions import _process_event_logic
    txn = FakeTransaction()
    ref = FakeRef(FakeSnapshot(exists=True, data={"status": "processing", "created_at": _NOW}))
    outcome = _process_event_logic(txn, ref, FakeDb(), "checkout.session.completed", {"mode": "subscription"}, _NOW)
    assert outcome == "skip"
    assert txn.set_calls == [] and txn.update_calls == []


def test_process_event_logic_stale_processing_reclaims_and_reprocesses():
    from app.routes.subscriptions import _process_event_logic
    stale = _NOW - timedelta(seconds=200)
    txn = FakeTransaction()
    ref = FakeRef(FakeSnapshot(exists=True, data={"status": "processing", "created_at": stale}))
    db = FakeDb(donations=FakeCollection())
    data = {"mode": "payment", "customer_details": {}, "amount_total": 200, "id": "sess_1"}
    outcome = _process_event_logic(txn, ref, db, "checkout.session.completed", data, _NOW)
    assert outcome == "processed"
    assert len(txn.update_calls) == 1  # reclaimed and fully reprocessed, not just skipped


def test_process_event_logic_missing_email_still_completes():
    from app.routes.subscriptions import _process_event_logic
    txn = FakeTransaction()
    ref = FakeRef(FakeSnapshot(exists=False))
    data = {"mode": "subscription", "customer_details": {}}
    outcome = _process_event_logic(txn, ref, FakeDb(), "checkout.session.completed", data, _NOW)
    assert outcome == "missing_email"
    # unrecoverable-by-retry: still marked completed rather than left dangling
    assert txn.update_calls[0][1]["status"] == "completed"


def test_process_event_logic_no_matching_subscriber_raises_without_completing():
    """A real Firestore transaction discards every buffered write (including
    the reservation write below) when the wrapped function raises — that
    all-or-nothing rollback is the SDK's guarantee, not something a fake
    object can simulate. What this test can and does verify is this
    function's own control flow: it must never reach the completion write
    once _apply_mutation has raised, since that write is exactly what a real
    transaction would also refuse to commit."""
    from app.routes.subscriptions import _process_event_logic
    txn = FakeTransaction()
    ref = FakeRef(FakeSnapshot(exists=False))
    db = FakeDb(subscribers=FakeCollection())  # empty -> no matching subscriber
    with pytest.raises(WebhookProcessingError):
        _process_event_logic(txn, ref, db, "customer.subscription.updated", {"id": "sub_1"}, _NOW)
    assert txn.update_calls == []


# ── Webhook route wiring (processing patched via mock_process_event) ────────

def test_webhook_missing_event_id_returns_400_and_alerts(client, mock_db):
    with (
        patch("app.routes.subscriptions.stripe.Webhook.construct_event") as mock_construct,
        patch("app.routes.subscriptions._alert") as mock_alert,
    ):
        mock_construct.return_value = {"id": "", "type": "checkout.session.completed", "data": {"object": {}}}
        response = client.post("/api/subscribe/webhook", content=b"payload", headers={"stripe-signature": "sig"})
        assert response.status_code == 400
        mock_alert.assert_called_once()


def test_webhook_skip_outcome_returns_ok_without_alert(client, mock_db, mock_process_event):
    mock_process_event.return_value = "skip"
    with (
        patch("app.routes.subscriptions.stripe.Webhook.construct_event") as mock_construct,
        patch("app.routes.subscriptions._alert") as mock_alert,
    ):
        mock_construct.return_value = _subscription_checkout_event()
        response = client.post("/api/subscribe/webhook", content=b"payload", headers={"stripe-signature": "sig"})
        assert response.status_code == 200
        mock_alert.assert_not_called()


def test_webhook_processed_outcome_returns_ok_without_alert(client, mock_db, mock_process_event):
    mock_process_event.return_value = "processed"
    with (
        patch("app.routes.subscriptions.stripe.Webhook.construct_event") as mock_construct,
        patch("app.routes.subscriptions._alert") as mock_alert,
    ):
        mock_construct.return_value = _subscription_checkout_event()
        response = client.post("/api/subscribe/webhook", content=b"payload", headers={"stripe-signature": "sig"})
        assert response.status_code == 200
        mock_alert.assert_not_called()


def test_webhook_missing_email_outcome_alerts(client, mock_db, mock_process_event):
    mock_process_event.return_value = "missing_email"
    with (
        patch("app.routes.subscriptions.stripe.Webhook.construct_event") as mock_construct,
        patch("app.routes.subscriptions._alert") as mock_alert,
    ):
        mock_construct.return_value = _subscription_checkout_event()
        response = client.post("/api/subscribe/webhook", content=b"payload", headers={"stripe-signature": "sig"})
        assert response.status_code == 200
        mock_alert.assert_called_once()
        assert "missing email" in mock_alert.call_args[0][0].lower()


def test_webhook_process_event_exception_alerts_and_raises(client, mock_db, mock_process_event):
    """TestClient's default raise_server_exceptions=True means the unhandled
    exception propagates into the test rather than becoming a response
    object — same as any other uncaught-exception route in this app."""
    mock_process_event.side_effect = RuntimeError("boom")
    with (
        patch("app.routes.subscriptions.stripe.Webhook.construct_event") as mock_construct,
        patch("app.routes.subscriptions._alert") as mock_alert,
    ):
        mock_construct.return_value = _subscription_checkout_event()
        with pytest.raises(RuntimeError):
            client.post("/api/subscribe/webhook", content=b"payload", headers={"stripe-signature": "sig"})
        mock_alert.assert_called_once()


def test_webhook_handles_real_stripe_event_object_not_just_a_dict(client, mock_db, mock_process_event):
    """Regression test for a bug live-QA caught: every other webhook test in
    this file mocks construct_event to return a plain dict, but the real
    stripe.Webhook.construct_event returns a typed stripe.Event that supports
    __getitem__/__contains__, not .get(). Only this test's mock reproduces
    that distinction, exercising the hasattr(event, "to_dict") conversion in
    stripe_webhook()."""
    mock_process_event.return_value = "processed"
    with (
        patch("app.routes.subscriptions.stripe.Webhook.construct_event") as mock_construct,
        patch("app.routes.subscriptions._alert") as mock_alert,
    ):
        mock_construct.return_value = _FakeStripeObject(_subscription_checkout_event())
        response = client.post("/api/subscribe/webhook", content=b"payload", headers={"stripe-signature": "sig"})
        assert response.status_code == 200
        mock_alert.assert_not_called()


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
