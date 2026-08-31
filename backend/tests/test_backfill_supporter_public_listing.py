"""Unit tests for scripts/backfill_supporter_public_listing.py."""

import sys
from argparse import Namespace
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


@pytest.fixture
def backfill(monkeypatch):
    import backfill_supporter_public_listing as backfill

    monkeypatch.setattr(backfill.config.settings, "gcp_project_id", backfill.config.settings.gcp_project_id)
    return backfill


class FakeDocRef:
    def __init__(self, doc_id):
        self.id = doc_id
        self.updates = []

    def update(self, data):
        self.updates.append(data)


class FakeDoc:
    def __init__(self, doc_id, data):
        self.id = doc_id
        self.reference = FakeDocRef(doc_id)
        self._data = data

    def to_dict(self):
        return self._data


class FakeCollection:
    def __init__(self, docs):
        self._docs = docs

    def stream(self):
        return iter(self._docs)


class FakeDb:
    def __init__(self, subscribers=(), donations=()):
        self._collections = {"subscribers": FakeCollection(subscribers), "donations": FakeCollection(donations)}

    def collection(self, name):
        return self._collections[name]


def test_dry_run_never_writes(backfill):
    doc = FakeDoc("d1", {"display_name": "Alex", "name_enabled": True})  # missing public_listing
    db = FakeDb(subscribers=[doc])
    args = Namespace(project="test-project", live=False)

    with patch.object(backfill, "get_db", return_value=db):
        exit_code = backfill.run(args)

    assert exit_code == 0
    assert doc.reference.updates == []


def test_already_correct_is_left_alone(backfill):
    doc = FakeDoc("d1", {"display_name": "Alex", "name_enabled": True, "public_listing": True})
    db = FakeDb(subscribers=[doc])
    args = Namespace(project="test-project", live=True)

    with patch.object(backfill, "get_db", return_value=db):
        backfill.run(args)

    assert doc.reference.updates == []


def test_live_run_fixes_missing_field(backfill):
    doc = FakeDoc("d1", {"display_name": "Alex", "name_enabled": True})
    db = FakeDb(donations=[doc])
    args = Namespace(project="test-project", live=True)

    with patch.object(backfill, "get_db", return_value=db):
        exit_code = backfill.run(args)

    assert exit_code == 0
    assert doc.reference.updates == [{"public_listing": True}]


def test_live_run_fixes_stale_true_when_name_now_disabled(backfill):
    doc = FakeDoc("d1", {"display_name": "Alex", "name_enabled": False, "public_listing": True})
    db = FakeDb(subscribers=[doc])
    args = Namespace(project="test-project", live=True)

    with patch.object(backfill, "get_db", return_value=db):
        backfill.run(args)

    assert doc.reference.updates == [{"public_listing": False}]


def test_no_display_name_expects_false(backfill):
    doc = FakeDoc("d1", {"name_enabled": True})  # never set a display name
    db = FakeDb(donations=[doc])
    args = Namespace(project="test-project", live=True)

    with patch.object(backfill, "get_db", return_value=db):
        backfill.run(args)

    assert doc.reference.updates == [{"public_listing": False}]


def test_missing_name_enabled_field_defaults_true(backfill):
    doc = FakeDoc("d1", {"display_name": "Alex"})  # name_enabled never set
    db = FakeDb(subscribers=[doc])
    args = Namespace(project="test-project", live=True)

    with patch.object(backfill, "get_db", return_value=db):
        backfill.run(args)

    assert doc.reference.updates == [{"public_listing": True}]


def test_write_failure_is_counted_and_exits_nonzero(backfill):
    doc = FakeDoc("d1", {"display_name": "Alex", "name_enabled": True})
    doc.reference.update = MagicMock(side_effect=RuntimeError("boom"))
    db = FakeDb(subscribers=[doc])
    args = Namespace(project="test-project", live=True)

    with patch.object(backfill, "get_db", return_value=db):
        exit_code = backfill.run(args)

    assert exit_code == 1


def test_both_collections_are_scanned(backfill):
    sub_doc = FakeDoc("s1", {"display_name": "Sub", "name_enabled": True})
    don_doc = FakeDoc("d1", {"display_name": "Don", "name_enabled": True})
    db = FakeDb(subscribers=[sub_doc], donations=[don_doc])
    args = Namespace(project="test-project", live=True)

    with patch.object(backfill, "get_db", return_value=db):
        backfill.run(args)

    assert sub_doc.reference.updates == [{"public_listing": True}]
    assert don_doc.reference.updates == [{"public_listing": True}]
