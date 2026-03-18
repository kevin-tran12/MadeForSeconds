import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime
import stripe

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
         patch("app.routes.subscriptions.httpx.AsyncClient.post") as mock_post:
        mock_settings.resend_api_key = "fake_key"
        mock_settings.frontend_url = "https://madeforseconds.com"
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
