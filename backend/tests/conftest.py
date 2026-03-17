import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from app.main import app
from app.firestore import get_db
from app.auth import require_admin


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
    with (
        patch("app.routes.admin.get_db", return_value=mock),
        patch("app.routes.public.get_db", return_value=mock),
        patch("app.routes.subscriptions.get_db", return_value=mock),
    ):
        app.dependency_overrides[get_db] = lambda: mock
        yield mock


@pytest.fixture
def mock_admin():
    """Returns a mock admin email."""
    return "admin@madeforseconds.com"


@pytest.fixture(autouse=True)
def cleanup_overrides():
    """Ensure dependency overrides are cleaned up between tests."""
    yield
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(require_admin, None)


@pytest.fixture
def authenticated_client(client, mock_admin):
    """Provides a client that bypasses admin authentication."""
    app.dependency_overrides[require_admin] = lambda: mock_admin
    yield client
