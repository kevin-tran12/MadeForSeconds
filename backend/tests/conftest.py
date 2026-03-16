import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.firestore import get_db
from app.auth import require_admin
from unittest.mock import MagicMock

@pytest.fixture(scope="session")
def client():
    """Provides a TestClient for FastAPI, managed at the session level to avoid lifespan re-initialization errors."""
    with TestClient(app) as c:
        yield c

@pytest.fixture
def mock_db():
    """Provides a mocked Firestore client."""
    mock = MagicMock()
    # Reset app overrides to use this specific mock for each test
    app.dependency_overrides[get_db] = lambda: mock
    return mock

@pytest.fixture
def mock_admin():
    """Returns a mock admin email."""
    return "admin@madeforseconds.com"

@pytest.fixture(autouse=True)
def cleanup_overrides():
    """Ensure dependency overrides are cleaned up between tests."""
    yield
    # Keep the session-level client but allow individual tests to mock DB
    if get_db in app.dependency_overrides:
        del app.dependency_overrides[get_db]
    if require_admin in app.dependency_overrides:
        del app.dependency_overrides[require_admin]

@pytest.fixture
def authenticated_client(client, mock_admin):
    """Provides a client that bypasses admin authentication."""
    app.dependency_overrides[require_admin] = lambda: mock_admin
    yield client
