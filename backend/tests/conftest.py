import base64
import io
from fractions import Fraction

import pytest
from unittest.mock import MagicMock, patch
from fastapi import Request
from fastapi.testclient import TestClient
from PIL import Image, PngImagePlugin
from app.main import app
from app.firestore import get_db
from app.auth import UserIdentity, optional_user, require_admin, require_user
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
        patch("app.routes.me.get_db", return_value=mock),
        patch("app.routes.assistant.get_db", return_value=mock),
        patch("app.routes.internal.get_db", return_value=mock),
        patch("app.totp.get_db", return_value=mock),
    ):
        app.dependency_overrides[get_db] = lambda: mock
        yield mock


def _chain_db():
    """A Firestore-client MagicMock whose chainable query methods
    (collection/document/where/order_by/limit/select/start_after) all return
    itself, so a test can set .stream.side_effect / .get.return_value on one
    object regardless of how deep the tool under test chains the query.

    start_after was added for S7's cursor pagination (list_recipes) — an
    unconfigured MagicMock method returns a fresh, unrelated child mock by
    default, which silently breaks the chain: a cursor-carrying call's
    .limit(...).stream() then runs against that unrelated mock instead of
    this one, its default (empty) iteration, not whatever .stream.side_effect
    was actually configured for. Caught this exact way once, not by
    inspection — the first pagination test written against a fixture missing
    this line failed with an empty second page for no visible reason.
    """
    mock = MagicMock()
    mock.collection.return_value = mock
    mock.document.return_value = mock
    mock.where.return_value = mock
    mock.order_by.return_value = mock
    mock.limit.return_value = mock
    mock.select.return_value = mock
    mock.start_after.return_value = mock
    return mock


@pytest.fixture
def mcp_db():
    """A mocked Firestore client for the MCP tool suite.

    Each app.mcp_server.tools.<domain> module binds its own `get_db` name
    (the package has no single shared import to patch since the mcp_server
    split), so this patches the four that call it — recipes, ingredients,
    social, expenses; images.py never touches Firestore — plus the recipe
    and ingredient services' own cache bindings (each imports its own
    `cache` reference, so both need patching independently), the same
    combination test_mcp_tools.py's own `db` fixture used to provide via a
    single `app.mcp_server.get_db` patch. Also patches
    app.mcp_server.audit.get_db (S13's audit trail, called from every
    read_only=False tool via wrapper.py) — without it, every mutating-tool
    test here would additionally attempt a real Firestore write and log a
    WARNING on the (swallowed, but noisy) failure. Uses its own separate
    mock rather than reusing `mock`: several existing tests assert exact
    call counts on `mock` itself (e.g. `db.set.assert_not_called()`), and
    audit's own unrelated `.set()` call would silently break those.
    """
    mock = _chain_db()
    with (
        patch("app.mcp_server.tools.recipes.get_db", return_value=mock),
        patch("app.mcp_server.tools.ingredients.get_db", return_value=mock),
        patch("app.mcp_server.tools.social.get_db", return_value=mock),
        patch("app.mcp_server.tools.expenses.get_db", return_value=mock),
        patch("app.mcp_server.audit.get_db", return_value=_chain_db()),
        patch("app.services.recipes.cache"),
        patch("app.services.ingredients.cache"),
    ):
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
    app.dependency_overrides.pop(require_user, None)
    app.dependency_overrides.pop(optional_user, None)
    app.dependency_overrides.pop(require_totp_session, None)


@pytest.fixture(autouse=True)
def reset_rate_limits():
    """Rate-limit counters live in module-level singletons for the whole
    test session, and TestClient requests all share one IP by default —
    reset counters before each test so rate-limited routes don't flake
    based on execution order/count across the suite.

    Covers both cache backends: MemoryCache keeps counters in a plain dict
    (`_counters`), but RedisCache keeps them in real Redis under the
    `{_NS}:rl:*` prefix (see cache.py's `incr_with_ttl`) — when REDIS_URL is
    set (e.g. under `docker compose exec backend pytest`, which points at a
    real Redis container), only clearing `_counters` leaves every prior
    test's counts sitting in Redis, so rate-limit-boundary tests fail
    depending on how much other traffic already ran in the same session.
    """
    from app.cache import cache
    from app.rate_limit import _fallback
    if hasattr(cache, "_counters"):
        cache._counters.clear()
    elif hasattr(cache, "_r"):
        keys = cache._r.keys(f"{cache._NS}:rl:*")
        if keys:
            cache._r.delete(*keys)
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
def mock_user():
    """A signed-in, non-admin reader (the Sous Chef free tier)."""
    return UserIdentity(email="reader@example.com", uid="uid-reader", is_admin=False)


@pytest.fixture
def user_client(client, mock_user):
    """Provides a client that bypasses reader authentication as mock_user."""
    def override(request: Request):
        request.state.user = mock_user
        return mock_user
    app.dependency_overrides[require_user] = override
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
        patch("app.routes.public.cache", new=mock),
        patch("app.routes.subscriptions.cache", new=mock),
        patch("app.routes.admin.cache", new=mock),
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

# The signatures above are enough to exercise sniffing, but they are not decodable
# images — they have no IEND chunk, no scan segment. Anything that goes through the
# upload *route* now also passes through metadata stripping, which fails closed on
# input it cannot parse, so route tests need genuinely valid files. These are 2x2
# solid-colour images carrying no metadata of their own.
REAL_PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAEklEQVR4nGM8YaPBwMDAxAAGAA7a"
    "ATDQ5FyAAAAAAElFTkSuQmCC"
)
REAL_WEBP_BYTES = base64.b64decode(
    "UklGRjwAAABXRUJQVlA4IDAAAADwAQCdASoCAAIAAUAmJaACdLoB+AAEgwAA/u4KZ/5BcsLrka/9"
    "pZ+pZ+pZ/ioAAAA="
)

# Images carrying real EXIF/GPS/text metadata, for the sanitize/strip tests in
# test_uploads_hardening.py and test_uploads_service.py. Built rather than
# committed as blobs so the tags being asserted on are visible in the test.

def _exif_with_gps():
    image = Image.new("RGB", (8, 8))
    exif = image.getexif()
    exif[0x010F] = "TestMake"
    gps = exif.get_ifd(0x8825)
    gps[1], gps[2] = "N", (Fraction(33), Fraction(56), Fraction(1744, 100))
    gps[3], gps[4] = "W", (Fraction(83), Fraction(56), Fraction(4590, 100))
    return exif


def _image_with_metadata(fmt: str) -> bytes:
    image = Image.new("RGB", (8, 8), (120, 80, 40))
    buffer = io.BytesIO()
    if fmt == "PNG":
        text = PngImagePlugin.PngInfo()
        text.add_text("Comment", "kitchen, home address")
        image.save(buffer, format=fmt, pnginfo=text, exif=_exif_with_gps())
    else:
        image.save(buffer, format=fmt, exif=_exif_with_gps())
    return buffer.getvalue()


def _gps_tag_count(data: bytes) -> int:
    exif = Image.open(io.BytesIO(data)).getexif()
    return len(exif.get_ifd(0x8825)) if exif else 0
