import pytest
from unittest.mock import MagicMock, patch
from fastapi import Request
from fastapi.testclient import TestClient
from app.main import app
from app.firestore import get_db
from app.auth import require_admin
from app.totp import require_totp_session


@pytest.fixture(scope="session")
def client():
    """Provides a TestClient for FastAPI, managed at the session level to avoid lifespan re-initialization errors."""
    with TestClient(app) as c:
        yield c


@pytest.fixture
def mock_db():
    """Provides a mocked Firestore client.

    Patches get_db both in FastAPI's dependency injection system AND directly
    in each route module (routes call get_db() directly, not via Depends).
    """
    mock = MagicMock()
    
    # Make all chainable methods return the same mock to simplify mocking deep chains
    mock.collection.return_value = mock
    mock.document.return_value = mock
    mock.where.return_value = mock
    mock.order_by.return_value = mock
    mock.limit.return_value = mock
    mock.select.return_value = mock
    
    with (
        patch("app.routes.admin.get_db", return_value=mock),
        patch("app.routes.public.get_db", return_value=mock),
        patch("app.routes.subscriptions.get_db", return_value=mock),
        patch("app.routes.expenses.get_db", return_value=mock),
        patch("app.routes.reports.get_db", return_value=mock),
        patch("app.totp.get_db", return_value=mock),
    ):
        app.dependency_overrides[get_db] = lambda: mock
        yield mock


@pytest.fixture
def mock_admin():
    """Returns a mock admin email."""
    return "admin@madeforseconds.com"


@pytest.fixture
def mock_totp_session():
    """Returns a mock TOTP session ID."""
    return "mock-totp-session-id"


@pytest.fixture(autouse=True)
def cleanup_overrides():
    """Ensure dependency overrides are cleaned up between tests."""
    yield
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(require_admin, None)
    app.dependency_overrides.pop(require_totp_session, None)


@pytest.fixture(autouse=True)
def reset_rate_limits():
    """Rate-limit counters live in module-level singletons for the whole
    test session, and TestClient requests all share one IP by default —
    reset counters before each test so rate-limited routes don't flake
    based on execution order/count across the suite."""
    from app.cache import cache
    from app.rate_limit import _fallback
    if hasattr(cache, "_counters"):
        cache._counters.clear()
    _fallback._counters.clear()
    yield


@pytest.fixture
def authenticated_client(client, mock_admin):
    """Provides a client that bypasses admin authentication and sets request.state.admin_email."""
    def override(request: Request):
        request.state.admin_email = mock_admin
        return mock_admin
    app.dependency_overrides[require_admin] = override
    yield client


@pytest.fixture
def totp_authenticated_client(authenticated_client, mock_totp_session):
    """Provides a client that bypasses both admin and TOTP authentication."""
    app.dependency_overrides[require_totp_session] = lambda: mock_totp_session
    yield authenticated_client


@pytest.fixture
def mock_cache():
    """Patches the app.cache singleton with a MagicMock."""
    with (
        patch("app.cache.cache") as mock,
        patch("app.routes.public.cache", new=mock)
    ):
        mock.get.return_value = None
        yield mock


@pytest.fixture
def mock_stripe():
    """Patches the stripe module in the subscriptions route."""
    with patch("app.routes.subscriptions.stripe") as mock:
        yield mock


@pytest.fixture
def sample_recipe_doc():
    """Returns a factory that creates MagicMock Firestore documents for recipes."""
    def _create(id="test-recipe", **data):
        doc = MagicMock()
        doc.id = id
        doc.exists = True
        payload = {
            "title": "Test Recipe",
            "slug": "test-recipe",
            "description": "A delicious test recipe",
            "ingredients": [{"item": "Test Ingredient", "amount": "1", "unit": "cup", "group": "Main"}],
            "instructions": [{"step": 1, "text": "Step 1", "tip": "Tip 1"}],
            "prep_time_minutes": 10,
            "cook_time_minutes": 20,
            "servings": 4,
            "difficulty": "easy",
            "categories": ["test"],
            "published": True,
            "image_url": "https://example.com/image.jpg",
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z",
            "nutrition": [],
            "components": None
        }
        payload.update(data)
        doc.to_dict.return_value = payload
        return doc
    return _create


@pytest.fixture
def sample_expense_doc():
    """Returns a factory that creates MagicMock Firestore documents for expenses."""
    def _create(id="test-expense", **data):
        doc = MagicMock()
        doc.id = id
        doc.exists = True
        payload = {
            "vendor": "Test Vendor",
            "date": "2024-01-01T00:00:00Z",
            "category": "software",
            "description": "Test expense",
            "purpose": "Test purpose",
            "transaction_id": "tx_123",
            "merchant_id": "merch_123",
            "receipt_url": None,
            "receipt_filename": None,
            "receipt_content_type": None,
            "items": [
                {
                    "name": "Test Item",
                    "quantity": 1,
                    "unit_price": 10000,
                    "total_price": 10000,
                    "project_related": True,
                }
            ],
            "raw_subtotal": 10000,
            "raw_tax": 500,
            "raw_total": 10500,
            "project_subtotal": 10000,
            "project_tax": 500,
            "project_total": 10500,
            "status": "active",
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z",
            "revision": 1,
            "ai_parsed": False,
            "recipe_ids": [],
            "recipe_names": [],
            "voided_at": None,
            "void_reason": None
        }
        payload.update(data)
        doc.to_dict.return_value = payload
        return doc
    return _create


# ── Upload fixtures ───────────────────────────────────────────────────────────
# Uploads are validated by magic bytes (services/uploads.sniff_content_type),
# not by the declared Content-Type, so test payloads need real file signatures.
# sniff_content_type requires at least 12 bytes, hence the padding.

JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 16
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
WEBP_BYTES = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 12
HEIC_BYTES = b"\x00\x00\x00\x18" + b"ftyp" + b"heic" + b"\x00" * 12
PDF_BYTES = b"%PDF-1.4\n" + b"\x00" * 16

# Content that no sniffer should accept — the "renamed .html to .jpg" case.
NOT_A_MEDIA_FILE = b"<html><body>hello</body></html>"
