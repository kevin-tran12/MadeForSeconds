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
    assert args["public_listing"] is True


def test_setup_profile_existing_doc_with_name_disabled_stays_unlisted(client, mock_stripe, mock_db):
    """A supporter who previously had their name hidden by an admin
    (name_enabled=False) doesn't get silently re-listed just by setting a
    new display name — public_listing has to fold in the existing
    name_enabled value, not assume it's on."""
    mock_session = MagicMock()
    mock_session.payment_status = "paid"
    mock_session.mode = "subscription"
    mock_session.customer_details.email = "test@example.com"
    mock_session.id = "sess_456"
    mock_stripe.checkout.Session.retrieve.return_value = mock_session

    mock_doc = MagicMock()
    mock_doc.id = "sub_doc_123"
    mock_doc.to_dict.return_value = {"setup_session_id": "other_sess", "name_enabled": False}
    mock_db.collection.return_value.where.return_value.limit.return_value.stream.return_value = iter([mock_doc])

    payload = {"session_id": "sess_456", "display_name": "New Name", "note": "", "note_is_public": False}
    response = client.post("/api/subscribe/setup-profile", json=payload)
    assert response.status_code == 200

    args = mock_db.collection.return_value.document.return_value.update.call_args[0][0]
    assert args["public_listing"] is False


def test_setup_profile_new_donation_doc_sets_public_listing(client, mock_stripe, mock_db):
    mock_session = MagicMock()
    mock_session.payment_status = "paid"
    mock_session.mode = "payment"
    mock_session.customer_details.email = "donor@example.com"
    mock_session.id = "sess_789"
    mock_session.amount_total = 500
    mock_stripe.checkout.Session.retrieve.return_value = mock_session

    mock_db.collection.return_value.where.return_value.limit.return_value.stream.return_value = iter([])

    payload = {"session_id": "sess_789", "display_name": "Donor Name", "note": "", "note_is_public": False}
    response = client.post("/api/subscribe/setup-profile", json=payload)
    assert response.status_code == 200

    args = mock_db.collection.return_value.add.call_args[0][0]
    assert args["public_listing"] is True


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

def _supporters_query_mocks(sub_docs, don_docs):
    """Builds the two per-collection query-chain mocks list_supporters issues:
    .where("public_listing", "==", True).order_by(...).limit(...).stream()."""
    sub_collection = MagicMock()
    sub_collection.where.return_value.order_by.return_value.limit.return_value.stream.return_value = iter(sub_docs)
    don_collection = MagicMock()
    don_collection.where.return_value.order_by.return_value.limit.return_value.stream.return_value = iter(don_docs)
    return sub_collection, don_collection


def test_public_supporters_list(client, mock_db, mock_cache):
    """Returns publicly-listed supporters sorted by total donated, highest first."""
    sub_doc = MagicMock()
    sub_doc.to_dict.return_value = {"display_name": "Sub 1", "total_donated_cents": 500}
    don_doc = MagicMock()
    don_doc.to_dict.return_value = {"display_name": "Don 1", "total_donated_cents": 1000}

    sub_collection, don_collection = _supporters_query_mocks([sub_doc], [don_doc])
    mock_db.collection.side_effect = [sub_collection, don_collection]

    response = client.get("/api/subscribe/supporters")
    assert response.status_code == 200
    data = response.json()
    assert [s["display_name"] for s in data] == ["Don 1", "Sub 1"]

    # The query filters on the denormalised flag server-side rather than
    # streaming everything and filtering in Python.
    sub_collection.where.assert_called_once_with("public_listing", "==", True)
    don_collection.where.assert_called_once_with("public_listing", "==", True)


def test_supporters_query_is_bounded_by_limit(client, mock_db, mock_cache):
    """Each collection read is a LIMIT query, not a full scan — the query
    itself is bounded regardless of how many supporters actually exist."""
    from app.routes.subscriptions import _SUPPORTERS_MAX_LIMIT

    sub_collection, don_collection = _supporters_query_mocks([], [])
    mock_db.collection.side_effect = [sub_collection, don_collection]

    response = client.get("/api/subscribe/supporters")
    assert response.status_code == 200

    sub_collection.where.return_value.order_by.return_value.limit.assert_called_once_with(_SUPPORTERS_MAX_LIMIT)
    don_collection.where.return_value.order_by.return_value.limit.assert_called_once_with(_SUPPORTERS_MAX_LIMIT)


def test_supporters_response_respects_requested_limit(client, mock_db, mock_cache):
    """A caller-supplied ?limit= slices the (already bounded) result further,
    on top of the server-side cap — proves the response size tracks the
    requested page size, not whatever the query happened to return."""
    docs = [
        MagicMock(to_dict=MagicMock(return_value={"display_name": f"Supporter {i}", "total_donated_cents": i}))
        for i in range(10)
    ]
    sub_collection, don_collection = _supporters_query_mocks(docs, [])
    mock_db.collection.side_effect = [sub_collection, don_collection]

    response = client.get("/api/subscribe/supporters?limit=3")
    assert response.status_code == 200
    assert len(response.json()) == 3


def test_supporters_list_is_cached_across_requests(client, mock_db, mock_cache):
    """A second request must not re-query Firestore — the cache is checked
    first and only populated on a miss."""
    sub_doc = MagicMock()
    sub_doc.to_dict.return_value = {"display_name": "Sub 1", "total_donated_cents": 500}
    sub_collection, don_collection = _supporters_query_mocks([sub_doc], [])
    mock_db.collection.side_effect = [sub_collection, don_collection]

    first = client.get("/api/subscribe/supporters")
    assert first.status_code == 200
    mock_cache.set.assert_called_once()
    cached_value = mock_cache.set.call_args[0][1]

    mock_cache.get.return_value = cached_value
    mock_db.collection.side_effect = AssertionError("second request should not hit Firestore")

    second = client.get("/api/subscribe/supporters")
    assert second.status_code == 200
    assert second.json() == first.json()


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
    def __init__(self, snapshot, event_id="evt_fake"):
        self._snapshot = snapshot
        self.id = event_id

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

    def document(self, doc_id=None):
        return FakeDocRef(doc_id or "new-doc")


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


def _donation_checkout_event(event_id="evt_don_1", email="donor@example.com", amount_total=1000, payment_intent="pi_123"):
    return {
        "id": event_id,
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "mode": "payment",
                "customer_details": {"email": email} if email else {},
                "amount_total": amount_total,
                "payment_intent": payment_intent,
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
    assert payload["public_listing"] is False  # no display_name yet


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
    # No display_name/name_enabled on this fixture, so recompute -> False.
    assert payload["public_listing"] is False


def test_apply_subscription_checkout_resubscribe_restores_public_listing():
    """A resubscribe (existing subscriber, new checkout session) must
    restore public_listing from the still-stored display preference —
    not leave it wherever a prior cancellation last set it."""
    from app.routes.subscriptions import _apply_subscription_checkout
    txn = FakeTransaction()
    existing = FakeSnapshot(
        exists=True,
        data={"email": "a@b.com", "display_name": "Ann", "name_enabled": True, "public_listing": False},
    )
    data = {
        "customer": "cus_1", "subscription": "sub_1",
        "customer_details": {"email": "a@b.com"}, "amount_total": 500,
    }
    outcome = _apply_subscription_checkout(txn, FakeDb(), data, existing, _NOW)
    assert outcome == "processed"
    assert txn.update_calls[0][1]["public_listing"] is True


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


def test_apply_subscription_updated_past_due_clears_public_listing():
    """A lapsed subscriber must vanish from the public list even though
    display_name/name_enabled never changed — list_supporters no longer
    filters on status in Python, so public_listing has to track it."""
    from app.routes.subscriptions import _apply_subscription_updated
    txn = FakeTransaction()
    existing = FakeSnapshot(exists=True, data={"display_name": "Ann", "name_enabled": True, "public_listing": True})
    _apply_subscription_updated(txn, {"id": "sub_1", "status": "past_due"}, existing, _NOW)
    assert txn.update_calls[0][1]["public_listing"] is False


def test_apply_subscription_updated_reactivated_recomputes_public_listing():
    """Recovering back to active must re-derive public_listing from the
    subscriber's own display preference, not just flip it back to True."""
    from app.routes.subscriptions import _apply_subscription_updated
    txn = FakeTransaction()
    existing = FakeSnapshot(exists=True, data={"display_name": "Ann", "name_enabled": False, "public_listing": False})
    _apply_subscription_updated(txn, {"id": "sub_1", "status": "active"}, existing, _NOW)
    assert txn.update_calls[0][1]["public_listing"] is False  # name_enabled=False -> still excluded


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
    assert txn.update_calls[0][1]["public_listing"] is False


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


def test_apply_payment_failed_clears_public_listing():
    from app.routes.subscriptions import _apply_payment_failed
    txn = FakeTransaction()
    existing = FakeSnapshot(exists=True, data={"display_name": "Ann", "name_enabled": True, "public_listing": True})
    _apply_payment_failed(txn, {"subscription": "sub_1"}, existing, _NOW)
    assert txn.update_calls[0][1]["public_listing"] is False


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
    # A repeat donation still gets its own immutable ledger row — the
    # aggregate increment above is not a substitute for it.
    assert len(txn.set_calls) == 1
    ledger_ref, ledger_payload = txn.set_calls[0]
    assert ledger_ref.id == "sess_1"
    assert ledger_payload["gross_cents"] == 300


def test_apply_donation_checkout_anonymous_creates_new_doc():
    from app.routes.subscriptions import _apply_donation_checkout
    txn = FakeTransaction()
    db = FakeDb(donations=FakeCollection())
    data = {"customer_details": {}, "amount_total": 200, "id": "sess_2"}
    outcome = _apply_donation_checkout(txn, db, data, None, _NOW)
    assert outcome == "processed"
    # set_calls[0] is the ledger row, set_calls[1] is the donations aggregate doc.
    assert len(txn.set_calls) == 2
    assert txn.set_calls[1][1]["email"] == "anonymous"
    assert txn.set_calls[1][1]["public_listing"] is False


# ── donation_transactions ledger ─────────────────────────────────────────────

def test_apply_donation_checkout_writes_ledger_record_keyed_by_session_id():
    from app.routes.subscriptions import _apply_donation_checkout
    from app.services import donation_ledger
    txn = FakeTransaction()
    db = FakeDb(donations=FakeCollection())
    data = {
        "customer_details": {"email": "Donor@Example.com"},
        "amount_total": 500,
        "currency": "usd",
        "id": "sess_ledger_1",
        "payment_intent": "pi_123",
        "created": 1_700_000_000,
    }
    _apply_donation_checkout(txn, db, data, None, _NOW, fee_cents=15, net_cents=485)

    ledger_ref, ledger_payload = txn.set_calls[0]
    assert ledger_ref.id == "sess_ledger_1"
    assert ledger_payload["stripe_session_id"] == "sess_ledger_1"
    assert ledger_payload["stripe_payment_intent_id"] == "pi_123"
    assert ledger_payload["email_hash"] == donation_ledger.keyed_email_hash("Donor@Example.com")
    assert ledger_payload["gross_cents"] == 500
    assert ledger_payload["currency"] == "usd"
    assert ledger_payload["fee_cents"] == 15
    assert ledger_payload["net_cents"] == 485
    assert ledger_payload["status"] == "succeeded"
    assert ledger_payload["mode"] == "payment"
    assert ledger_payload["created_at"] == _NOW


def test_apply_donation_checkout_ledger_record_survives_missing_fee_data():
    """fee_cents/net_cents default to None (not 0) when the caller couldn't
    fetch them — the webhook must never fail or fabricate a fee just
    because the best-effort Stripe lookup came back empty."""
    from app.routes.subscriptions import _apply_donation_checkout
    txn = FakeTransaction()
    db = FakeDb(donations=FakeCollection())
    data = {"customer_details": {}, "amount_total": 100, "id": "sess_ledger_2"}
    _apply_donation_checkout(txn, db, data, None, _NOW)

    _, ledger_payload = txn.set_calls[0]
    assert ledger_payload["fee_cents"] is None
    assert ledger_payload["net_cents"] is None


def test_fetch_donation_fee_net_no_payment_intent_returns_none():
    from app.routes.subscriptions import _fetch_donation_fee_net
    assert _fetch_donation_fee_net(None) == (None, None)


def test_fetch_donation_fee_net_success():
    from app.routes.subscriptions import _fetch_donation_fee_net
    fake_intent = {"latest_charge": {"balance_transaction": {"fee": 32, "net": 468}}}
    with patch("app.routes.subscriptions.stripe.PaymentIntent.retrieve", return_value=fake_intent) as mock_retrieve:
        result = _fetch_donation_fee_net("pi_abc")
    assert result == (32, 468)
    mock_retrieve.assert_called_once_with("pi_abc", expand=["latest_charge.balance_transaction"])


def test_fetch_donation_fee_net_stripe_error_returns_none_without_raising():
    from app.routes.subscriptions import _fetch_donation_fee_net
    with patch(
        "app.routes.subscriptions.stripe.PaymentIntent.retrieve",
        side_effect=stripe.APIConnectionError("network down"),
    ):
        assert _fetch_donation_fee_net("pi_abc") == (None, None)


def test_fetch_donation_fee_net_missing_balance_transaction_returns_none():
    from app.routes.subscriptions import _fetch_donation_fee_net
    fake_intent = {"latest_charge": None}
    with patch("app.routes.subscriptions.stripe.PaymentIntent.retrieve", return_value=fake_intent):
        assert _fetch_donation_fee_net("pi_abc") == (None, None)


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


def test_process_event_logic_stamps_ttl_on_reservation():
    from app.routes.subscriptions import _process_event_logic, _PROCESSED_EVENTS_TTL_DAYS
    txn = FakeTransaction()
    ref = FakeRef(FakeSnapshot(exists=False))
    db = FakeDb(subscribers=FakeCollection())
    data = {
        "mode": "subscription", "customer": "cus_1", "subscription": "sub_1",
        "customer_details": {"email": "a@b.com"}, "amount_total": 1000,
    }
    _process_event_logic(txn, ref, db, "checkout.session.completed", data, _NOW)
    reservation_payload = txn.set_calls[0][1]
    assert reservation_payload["ttl"] == _NOW + timedelta(days=_PROCESSED_EVENTS_TTL_DAYS)


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


def test_webhook_donation_checkout_fetches_fee_and_threads_to_process_event(client, mock_db, mock_process_event):
    """The webhook route's donation-fee lookup runs before _process_event and
    its result is passed through — verified at the route layer since that's
    where the two are wired together (both are separately unit-tested on
    their own: _fetch_donation_fee_net above, the ledger write in
    _apply_donation_checkout's tests)."""
    mock_process_event.return_value = "processed"
    with (
        patch("app.routes.subscriptions.stripe.Webhook.construct_event") as mock_construct,
        patch("app.routes.subscriptions._alert"),
        patch(
            "app.routes.subscriptions._fetch_donation_fee_net", return_value=(25, 975)
        ) as mock_fetch_fee,
    ):
        mock_construct.return_value = _donation_checkout_event(payment_intent="pi_xyz")
        response = client.post("/api/subscribe/webhook", content=b"payload", headers={"stripe-signature": "sig"})

    assert response.status_code == 200
    mock_fetch_fee.assert_called_once_with("pi_xyz")
    call_args = mock_process_event.call_args[0]
    # (transaction, ref, db, event_type, data, now, fee_cents, net_cents)
    assert call_args[-2:] == (25, 975)


def test_webhook_subscription_checkout_skips_fee_lookup(client, mock_db, mock_process_event):
    """The fee lookup is scoped to donation (mode=payment) checkouts only —
    a subscription checkout must not trigger a pointless Stripe API call."""
    mock_process_event.return_value = "processed"
    with (
        patch("app.routes.subscriptions.stripe.Webhook.construct_event") as mock_construct,
        patch("app.routes.subscriptions._alert"),
        patch("app.routes.subscriptions._fetch_donation_fee_net") as mock_fetch_fee,
    ):
        mock_construct.return_value = _subscription_checkout_event()
        response = client.post("/api/subscribe/webhook", content=b"payload", headers={"stripe-signature": "sig"})

    assert response.status_code == 200
    mock_fetch_fee.assert_not_called()


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


# ── Account linking: checkout prefill + webhook uid ─────────────────────────

_CHECKOUT = {
    "success_url": "https://madeforseconds.com/success",
    "cancel_url": "https://madeforseconds.com/cancel",
    "amount_cents": 500,
    "one_time": True,
}


def _as_reader(email="reader@example.com", uid="uid-reader"):
    from app.auth import UserIdentity, optional_user
    from app.main import app
    app.dependency_overrides[optional_user] = lambda: UserIdentity(email, uid, False)


def test_create_checkout_prefills_signed_in_reader(client, mock_stripe):
    _as_reader()
    mock_stripe.checkout.Session.create.return_value = MagicMock(url="https://stripe.com/checkout")
    assert client.post("/api/subscribe/checkout", json=_CHECKOUT).status_code == 200
    args = mock_stripe.checkout.Session.create.call_args[1]
    assert args["customer_email"] == "reader@example.com"
    assert args["client_reference_id"] == "uid-reader"


def test_create_checkout_anonymous_has_no_prefill(client, mock_stripe):
    mock_stripe.checkout.Session.create.return_value = MagicMock(url="https://stripe.com/checkout")
    assert client.post("/api/subscribe/checkout", json={**_CHECKOUT, "one_time": False}).status_code == 200
    args = mock_stripe.checkout.Session.create.call_args[1]
    assert "customer_email" not in args and "client_reference_id" not in args


def test_create_checkout_skips_prefill_for_dev_placeholder_email(client, mock_stripe):
    """Stripe rejects "dev@local"; a prefilled dev checkout would fail outright."""
    _as_reader(email="dev@local", uid="dev-admin")
    mock_stripe.checkout.Session.create.return_value = MagicMock(url="https://stripe.com/checkout")
    assert client.post("/api/subscribe/checkout", json=_CHECKOUT).status_code == 200
    assert "customer_email" not in mock_stripe.checkout.Session.create.call_args[1]


def test_apply_subscription_checkout_stores_uid_from_client_reference_id():
    from app.routes.subscriptions import _apply_subscription_checkout
    base = {"customer": "cus_1", "subscription": "sub_1", "customer_details": {"email": "a@b.com"}, "amount_total": 1000}
    txn = FakeTransaction()
    _apply_subscription_checkout(txn, FakeDb(subscribers=FakeCollection()), {**base, "client_reference_id": "uid-1"}, None, _NOW)
    assert txn.set_calls[0][1]["uid"] == "uid-1"
    txn = FakeTransaction()
    _apply_subscription_checkout(txn, FakeDb(subscribers=FakeCollection()), base, None, _NOW)
    assert "uid" not in txn.set_calls[0][1]


def test_apply_donation_checkout_stores_uid_on_new_and_repeat_records():
    from app.routes.subscriptions import _apply_donation_checkout
    data = {"customer_details": {"email": "donor@example.com"}, "amount_total": 300, "id": "sess_1", "client_reference_id": "uid-1"}
    txn = FakeTransaction()
    _apply_donation_checkout(txn, FakeDb(donations=FakeCollection()), data, None, _NOW)
    assert txn.set_calls[1][1]["uid"] == "uid-1"  # [0] is the ledger row
    txn = FakeTransaction()
    _apply_donation_checkout(txn, FakeDb(), data, FakeSnapshot(exists=True), _NOW)
    assert txn.update_calls[0][1]["uid"] == "uid-1"
    txn = FakeTransaction()
    _apply_donation_checkout(txn, FakeDb(donations=FakeCollection()), {"customer_details": {}, "amount_total": 200, "id": "sess_2"}, None, _NOW)
    assert "uid" not in txn.set_calls[1][1]


# ── Account linking: link-request / link-confirm ─────────────────────────────

def test_link_request_is_generic_when_no_record_exists(client, mock_db):
    from unittest.mock import AsyncMock
    mock_db.stream.side_effect = lambda *a, **k: iter([])
    with patch("app.routes.subscriptions.send_email", new_callable=AsyncMock) as send:
        response = client.post("/api/subscribe/link-request", json={"email": "Nobody@Example.com"})
    assert response.status_code == 200
    assert response.json()["message"].startswith("If a donation exists")
    send.assert_not_awaited()


def test_link_request_emails_a_signed_link_when_a_record_exists(client, mock_db):
    from unittest.mock import AsyncMock
    mock_db.stream.side_effect = lambda *a, **k: iter([MagicMock()])
    with patch("app.routes.subscriptions.send_email", new_callable=AsyncMock) as send:
        response = client.post("/api/subscribe/link-request", json={"email": "Donor@Example.com"})
    assert response.status_code == 200
    assert response.json()["message"].startswith("If a donation exists")  # same body either way
    send.assert_awaited_once()
    to, subject, html = send.await_args[0]
    assert to == "donor@example.com"
    assert "/support/link/?token=" in html


def test_link_confirm_requires_a_signed_in_reader(client, mock_db):
    assert client.post("/api/subscribe/link-confirm", json={"token": "t"}).status_code == 401


def test_link_confirm_attaches_uid_and_refreshes_supporter_status(user_client, mock_db):
    from app.cache import cache
    cache.clear()
    record = MagicMock()
    record.to_dict.return_value = {"email": "donor@example.com", "status": "active"}
    mock_db.stream.side_effect = lambda *a, **k: iter([record])
    with patch("app.routes.subscriptions.verify_link_token", return_value="donor@example.com"):
        response = user_client.post("/api/subscribe/link-confirm", json={"token": "t"})
    assert response.status_code == 200
    body = response.json()
    assert body["linked"] == 2  # the chained mock answers for subscribers and donations alike
    assert body["supporter"] is True
    assert record.reference.update.call_args[0][0]["uid"] == "uid-reader"
    cache.clear()


def test_link_confirm_404_when_the_email_has_no_records(user_client, mock_db):
    mock_db.stream.side_effect = lambda *a, **k: iter([])
    with patch("app.routes.subscriptions.verify_link_token", return_value="donor@example.com"):
        assert user_client.post("/api/subscribe/link-confirm", json={"token": "t"}).status_code == 404


def test_link_and_cancel_tokens_are_not_interchangeable():
    from fastapi import HTTPException
    from app.subscriber_auth import (
        create_cancel_token, create_link_token, verify_cancel_token, verify_link_token,
    )
    assert verify_link_token(create_link_token("a@b.com")) == "a@b.com"
    assert verify_cancel_token(create_cancel_token("a@b.com")) == "a@b.com"
    with pytest.raises(HTTPException) as exc:
        verify_link_token(create_cancel_token("a@b.com"))
    assert exc.value.status_code == 400
    with pytest.raises(HTTPException):
        verify_cancel_token(create_link_token("a@b.com"))
    with pytest.raises(HTTPException) as exc:
        verify_link_token("not-a-token")
    assert exc.value.detail == "Invalid link"
