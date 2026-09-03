"""Route tests for /api/me (reader profile + delete-my-data)."""

from unittest.mock import MagicMock

import pytest

from app.cache import cache


@pytest.fixture(autouse=True)
def _fresh_cache():
    # The supporter lookup is cached per hashed email for 5 minutes; every
    # test here uses the same reader with a different Firestore state.
    cache.clear()
    yield
    cache.clear()


def _empty_streams(mock_db):
    mock_db.stream.side_effect = lambda *a, **k: iter([])
    mock_db.get.return_value.exists = False


def test_me_requires_a_signed_in_reader(client, mock_db):
    _empty_streams(mock_db)
    response = client.get("/api/me")
    assert response.status_code == 401


def test_me_dev_bypass_header_is_the_dev_admin(client, mock_db):
    _empty_streams(mock_db)
    response = client.get("/api/me", headers={"X-Dev-Admin": "true"})
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "dev@local" and body["is_admin"] is True


def test_me_returns_profile_and_free_allowance(user_client, mock_db):
    _empty_streams(mock_db)
    response = user_client.get("/api/me")
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "reader@example.com"
    assert body["is_admin"] is False
    assert body["supporter"] is False
    assert body["returning"] is False
    assert body["assistant"]["day"] == {"limit": 5, "used": 0}
    assert body["assistant"]["month"] is None
    assert body["assistant"]["remaining"] == 5
    # First visit creates the users record.
    mock_db.set.assert_called_once()


def test_me_recognises_a_returning_supporter(user_client, mock_db):
    subscriber = MagicMock()
    subscriber.to_dict.return_value = {"email": "reader@example.com", "status": "active"}
    mock_db.stream.side_effect = lambda *a, **k: iter([subscriber])
    mock_db.get.return_value.exists = True
    mock_db.get.return_value.to_dict.return_value = {"answers_total": 3}

    body = user_client.get("/api/me").json()
    assert body["supporter"] is True
    assert body["returning"] is True
    assert body["answers_total"] == 3
    assert body["assistant"]["day"]["limit"] == 50
    assert body["assistant"]["month"]["limit"] == 400


def test_delete_my_data(user_client, mock_db):
    _empty_streams(mock_db)
    mock_db.get.return_value.exists = True
    response = user_client.delete("/api/me/data")
    assert response.status_code == 200
    assert response.json() == {
        "deleted": True, "users_deleted": 1, "feedback_deleted": 0, "supporter_links_removed": 0,
    }


def test_delete_my_data_requires_a_signed_in_reader(client, mock_db):
    assert client.delete("/api/me/data").status_code == 401


# ── cooking experience ───────────────────────────────────────────────────────

def test_me_includes_cooking_experience(user_client, mock_db):
    from datetime import datetime, timezone
    mock_db.stream.side_effect = lambda *a, **k: iter([])
    mock_db.get.return_value.exists = True
    mock_db.get.return_value.to_dict.return_value = {
        "cooking_experience": {"level": "beginner", "notes": "no oven",
                               "updated_at": datetime(2026, 9, 1, tzinfo=timezone.utc)},
    }
    body = user_client.get("/api/me").json()
    assert body["cooking_experience"] == {"level": "beginner", "notes": "no oven", "updated_at": "2026-09-01T00:00:00+00:00"}


def test_update_experience_round_trip(user_client, mock_db):
    response = user_client.put("/api/me/experience", json={"level": "confident", "notes": "  wok,  no oven "})
    assert response.status_code == 200
    saved = response.json()["cooking_experience"]
    assert saved["level"] == "confident" and saved["notes"] == "wok, no oven"
    args, kwargs = mock_db.set.call_args
    assert kwargs == {"merge": True}
    assert args[0]["cooking_experience"]["level"] == "confident"


def test_update_experience_rejects_unknown_level(user_client, mock_db):
    assert user_client.put("/api/me/experience", json={"level": "wizard"}).status_code == 422
    mock_db.set.assert_not_called()


def test_update_experience_requires_a_signed_in_reader(client, mock_db):
    assert client.put("/api/me/experience", json={"level": "beginner"}).status_code == 401
