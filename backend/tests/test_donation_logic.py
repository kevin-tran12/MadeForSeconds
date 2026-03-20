import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

@patch("app.routes.subscriptions.settings")
@patch("stripe.checkout.Session.create")
def test_create_checkout_donation_logic(mock_stripe_create, mock_settings):
    """Verify that checkout sessions use donation terminology and tax codes."""
    mock_stripe_create.return_value = MagicMock(url="https://stripe.com/test")
    mock_settings.stripe_secret_key = "sk_test_mock"
    mock_settings.cors_origins = ["http://localhost:5173"]
    
    # 1. Test One-time donation
    response = client.post("/api/subscribe/checkout", json={
        "amount_cents": 100,
        "success_url": "http://localhost:5173/success",
        "cancel_url": "http://localhost:5173/cancel",
        "one_time": True
    })
    
    assert response.status_code == 200
    # Check mock call for one-time
    args, kwargs = mock_stripe_create.call_args
    assert kwargs["mode"] == "payment"
    assert kwargs["submit_type"] == "donate"
    assert kwargs["line_items"][0]["price_data"]["product_data"]["tax_code"] == "txcd_00000000"
    assert kwargs["line_items"][0]["price_data"]["product_data"]["name"] == "MadeForSeconds Donation"

    # 2. Test Monthly recurring donation
    response = client.post("/api/subscribe/checkout", json={
        "amount_cents": 100,
        "success_url": "http://localhost:5173/success",
        "cancel_url": "http://localhost:5173/cancel",
        "one_time": False
    })
    
    assert response.status_code == 200
    # Check mock call for recurring
    args, kwargs = mock_stripe_create.call_args
    assert kwargs["mode"] == "subscription"
    # Ad-hoc product for subscription
    assert kwargs["line_items"][0]["price_data"]["product_data"]["tax_code"] == "txcd_00000000"
    assert kwargs["line_items"][0]["price_data"]["product_data"]["name"] == "MadeForSeconds Monthly Donation"
