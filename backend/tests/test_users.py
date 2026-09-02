"""Unit tests for the minimal reader record (app/services/users.py)."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from google.cloud.firestore import DELETE_FIELD

from app.services import users

NOW = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)


def _chain_db():
    mock = MagicMock()
    for name in ("collection", "document", "where", "limit"):
        getattr(mock, name).return_value = mock
    return mock


def test_touch_user_creates_record_on_first_visit():
    db = _chain_db()
    db.get.return_value.exists = False
    assert users.touch_user(db, "uid-1", NOW) == {"returning": False, "answers_total": 0}
    db.set.assert_called_once_with({"created_at": NOW, "last_seen_at": NOW, "answers_total": 0})
    db.update.assert_not_called()


def test_touch_user_marks_returning_and_refreshes_last_seen():
    db = _chain_db()
    db.get.return_value.exists = True
    db.get.return_value.to_dict.return_value = {
        "last_seen_at": NOW - timedelta(hours=2),
        "answers_total": 7,
    }
    assert users.touch_user(db, "uid-1", NOW) == {"returning": True, "answers_total": 7}
    db.update.assert_called_once_with({"last_seen_at": NOW})
    db.set.assert_not_called()


def test_touch_user_throttles_last_seen_writes():
    db = _chain_db()
    db.get.return_value.exists = True
    db.get.return_value.to_dict.return_value = {"last_seen_at": NOW - timedelta(minutes=5)}
    assert users.touch_user(db, "uid-1", NOW)["returning"] is True
    db.update.assert_not_called()


def test_touch_user_treats_naive_timestamps_as_utc():
    db = _chain_db()
    db.get.return_value.exists = True
    naive = (NOW - timedelta(days=1)).replace(tzinfo=None)
    db.get.return_value.to_dict.return_value = {"last_seen_at": naive}
    users.touch_user(db, "uid-1", NOW)
    db.update.assert_called_once()


def test_increment_answers_merges_a_counter_transform():
    db = _chain_db()
    users.increment_answers(db, "uid-1", NOW)
    args, kwargs = db.set.call_args
    assert kwargs == {"merge": True}
    assert args[0]["last_answer_at"] == NOW
    assert type(args[0]["answers_total"]).__name__ == "Increment"


def test_delete_user_data_removes_record_feedback_and_links():
    db = _chain_db()
    db.get.return_value.exists = True
    feedback = [MagicMock(), MagicMock()]
    subscriber = MagicMock()
    db.stream.side_effect = [iter(feedback), iter([subscriber]), iter([])]

    result = users.delete_user_data(db, "uid-1", "hash-1")

    assert result == {"users_deleted": 1, "feedback_deleted": 2, "supporter_links_removed": 1}
    db.delete.assert_called_once()
    batch = db.batch.return_value
    assert batch.delete.call_count == 2
    batch.commit.assert_called_once()
    subscriber.reference.update.assert_called_once_with({"uid": DELETE_FIELD})


def test_delete_user_data_is_a_noop_for_unknown_reader():
    db = _chain_db()
    db.get.return_value.exists = False
    db.stream.side_effect = lambda *a, **k: iter([])
    assert users.delete_user_data(db, "uid-x", "hash-x") == {
        "users_deleted": 0, "feedback_deleted": 0, "supporter_links_removed": 0,
    }
    db.delete.assert_not_called()
    db.batch.assert_not_called()
