"""Unit tests for scripts/backfill_donation_ledger.py's pure/testable logic.

The script's own job — walk real Stripe history, write real Firestore
documents — is only provable by actually running it against a real target
(dry run first, per its own docstring). What's tested here is the control
flow a live run can't cheaply prove wasn't a fluke:

  - dry run never calls the write path, regardless of what it finds
  - a session already ledgered is skipped, not duplicated (idempotency)
  - --live routes through the same transactional write the webhook path
    uses, not a second implementation of it
  - --limit and --after are honored
  - a write failure is counted and turns into a non-zero exit code, rather
    than being swallowed
"""

import sys
from argparse import Namespace
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


@pytest.fixture
def backfill(monkeypatch):
    import backfill_donation_ledger as backfill

    # run() mutates the real app.config.settings singleton in place (same
    # pattern as the other operator scripts in this directory) — pydantic
    # settings only reads env vars at construction time, which already
    # happened at import, so the fake key has to be set directly rather than
    # via monkeypatch.setenv. monkeypatch.setattr still reverts it (and
    # gcp_project_id, which run() also mutates) at teardown either way.
    monkeypatch.setattr(backfill.config.settings, "gcp_project_id", backfill.config.settings.gcp_project_id)
    monkeypatch.setattr(backfill.config.settings, "stripe_secret_key", "sk_test_fake")
    return backfill


class FakeDocSnapshot:
    def __init__(self, exists):
        self.exists = exists


class FakeDocRef:
    def __init__(self, exists):
        self._exists = exists

    def get(self):
        return FakeDocSnapshot(self._exists)


class FakeCollection:
    def __init__(self, existing_ids):
        self._existing_ids = existing_ids

    def document(self, doc_id):
        return FakeDocRef(doc_id in self._existing_ids)


class FakeDb:
    def __init__(self, existing_ids=()):
        self._collection = FakeCollection(set(existing_ids))

    def collection(self, name):
        return self._collection

    def transaction(self):
        return MagicMock()


def _session(session_id, amount_total=1000, email="donor@example.com", payment_intent="pi_1", created=1_700_000_000):
    return {
        "id": session_id,
        "amount_total": amount_total,
        "currency": "usd",
        "customer_details": {"email": email} if email else {},
        "payment_intent": payment_intent,
        "created": created,
    }


def _patch_stripe_list(backfill, sessions):
    mock_list = MagicMock()
    mock_list.auto_paging_iter.return_value = iter(sessions)
    return patch.object(backfill.stripe.checkout.Session, "list", return_value=mock_list)


def test_dry_run_never_writes(backfill):
    db = FakeDb(existing_ids=set())
    args = Namespace(project="test-project", live=False, limit=None, after=None)
    with (
        patch.object(backfill, "get_db", return_value=db),
        _patch_stripe_list(backfill, [_session("cs_1")]),
        patch.object(backfill, "_fetch_donation_fee_net", return_value=(30, 970)),
        patch.object(backfill, "_write_one") as mock_write,
    ):
        exit_code = backfill.run(args)

    assert exit_code == 0
    mock_write.assert_not_called()


def test_already_present_session_is_skipped_not_duplicated(backfill):
    db = FakeDb(existing_ids={"cs_existing"})
    args = Namespace(project="test-project", live=True, limit=None, after=None)
    with (
        patch.object(backfill, "get_db", return_value=db),
        _patch_stripe_list(backfill, [_session("cs_existing")]),
        patch.object(backfill, "_fetch_donation_fee_net", return_value=(None, None)),
        patch.object(backfill, "_write_one") as mock_write,
    ):
        exit_code = backfill.run(args)

    assert exit_code == 0
    mock_write.assert_not_called()


def test_live_run_writes_new_sessions_through_the_shared_write_path(backfill):
    db = FakeDb(existing_ids=set())
    args = Namespace(project="test-project", live=True, limit=None, after=None)
    with (
        patch.object(backfill, "get_db", return_value=db),
        _patch_stripe_list(backfill, [_session("cs_new", amount_total=500, payment_intent="pi_new")]),
        patch.object(backfill, "_fetch_donation_fee_net", return_value=(15, 485)) as mock_fee,
        patch.object(backfill, "_write_one") as mock_write,
    ):
        exit_code = backfill.run(args)

    assert exit_code == 0
    mock_fee.assert_called_once_with("pi_new")
    mock_write.assert_called_once()
    call_kwargs = mock_write.call_args.kwargs
    assert call_kwargs["session_id"] == "cs_new"
    assert call_kwargs["gross_cents"] == 500
    assert call_kwargs["fee_cents"] == 15
    assert call_kwargs["net_cents"] == 485
    assert call_kwargs["payment_intent_id"] == "pi_new"


def test_live_run_write_failure_is_counted_and_exits_nonzero(backfill):
    db = FakeDb(existing_ids=set())
    args = Namespace(project="test-project", live=True, limit=None, after=None)
    with (
        patch.object(backfill, "get_db", return_value=db),
        _patch_stripe_list(backfill, [_session("cs_fail")]),
        patch.object(backfill, "_fetch_donation_fee_net", return_value=(None, None)),
        patch.object(backfill, "_write_one", side_effect=RuntimeError("boom")),
    ):
        exit_code = backfill.run(args)

    assert exit_code == 1


def test_limit_stops_after_n_sessions(backfill):
    db = FakeDb(existing_ids=set())
    args = Namespace(project="test-project", live=False, limit=2, after=None)
    with (
        patch.object(backfill, "get_db", return_value=db),
        _patch_stripe_list(backfill, [_session("cs_1"), _session("cs_2"), _session("cs_3")]),
        patch.object(backfill, "_fetch_donation_fee_net", return_value=(None, None)) as mock_fee,
    ):
        backfill.run(args)

    assert mock_fee.call_count == 2


def test_after_is_passed_through_to_the_stripe_list_call(backfill):
    db = FakeDb(existing_ids=set())
    args = Namespace(project="test-project", live=False, limit=None, after=1_650_000_000)
    mock_list = MagicMock()
    mock_list.auto_paging_iter.return_value = iter([])
    with (
        patch.object(backfill, "get_db", return_value=db),
        patch.object(backfill.stripe.checkout.Session, "list", return_value=mock_list) as mock_session_list,
    ):
        backfill.run(args)

    call_kwargs = mock_session_list.call_args.kwargs
    assert call_kwargs["created"] == {"gte": 1_650_000_000}


def test_missing_stripe_key_aborts_before_any_api_call(backfill):
    backfill.config.settings.stripe_secret_key = ""
    args = Namespace(project="test-project", live=False, limit=None, after=None)

    with patch.object(backfill.stripe.checkout.Session, "list") as mock_list:
        exit_code = backfill.run(args)

    assert exit_code == 1
    mock_list.assert_not_called()


def test_anonymous_donor_gets_anonymous_email_not_empty_string(backfill):
    db = FakeDb(existing_ids=set())
    args = Namespace(project="test-project", live=True, limit=None, after=None)
    with (
        patch.object(backfill, "get_db", return_value=db),
        _patch_stripe_list(backfill, [_session("cs_anon", email=None)]),
        patch.object(backfill, "_fetch_donation_fee_net", return_value=(None, None)),
        patch.object(backfill, "_write_one") as mock_write,
    ):
        backfill.run(args)

    assert mock_write.call_args.kwargs["email"] == "anonymous"
