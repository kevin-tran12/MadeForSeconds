"""Tests for mcp_server/idempotency.py: the cache primitives directly.

test_mcp_wrapper.py::TestIdempotency checks only that wrapper.py calls this
module at the right time (before/after fn(), skipped for a rate-limited
rejection) — this file exercises get_cached_result()/store_result()
themselves.
"""

import logging
from unittest.mock import MagicMock, patch

from app.mcp_server import idempotency


class TestDocId:
    def test_same_client_and_key_produce_the_same_id(self):
        assert idempotency._doc_id("client-a", "key-1") == idempotency._doc_id("client-a", "key-1")

    def test_different_clients_with_the_same_key_produce_different_ids(self):
        """Two different callers reusing the same literal key string must
        never collide — the id is scoped per caller."""
        assert idempotency._doc_id("client-a", "key-1") != idempotency._doc_id("client-b", "key-1")

    def test_different_keys_for_the_same_client_produce_different_ids(self):
        assert idempotency._doc_id("client-a", "key-1") != idempotency._doc_id("client-a", "key-2")

    def test_id_is_a_hash_not_the_raw_key(self):
        """Firestore document ids have length/character restrictions a
        caller-supplied key could otherwise violate (or exploit, the same
        class of concern _require_safe_slug guards against elsewhere) —
        the id must never simply be the key or contain it verbatim."""
        doc_id = idempotency._doc_id("client-a", "some/../weird key")
        assert "/" not in doc_id
        assert "some" not in doc_id


class TestGetCachedResult:
    def test_returns_none_when_nothing_stored(self):
        mock_doc = MagicMock(exists=False)
        mock_db = MagicMock()
        mock_db.collection.return_value.document.return_value.get.return_value = mock_doc

        with patch("app.mcp_server.idempotency.get_db", return_value=mock_db):
            assert idempotency.get_cached_result("client-a", "key-1") is None

    def test_returns_the_stored_result(self):
        mock_doc = MagicMock(exists=True)
        mock_doc.to_dict.return_value = {"result": {"id": "r1", "slug": "recipe"}}
        mock_db = MagicMock()
        mock_db.collection.return_value.document.return_value.get.return_value = mock_doc

        with patch("app.mcp_server.idempotency.get_db", return_value=mock_db):
            result = idempotency.get_cached_result("client-a", "key-1")

        assert result == {"id": "r1", "slug": "recipe"}

    def test_a_read_failure_degrades_to_not_seen_before(self, caplog):
        with patch("app.mcp_server.idempotency.get_db", side_effect=RuntimeError("firestore down")):
            with caplog.at_level(logging.WARNING, logger="app.mcp_server.idempotency"):
                result = idempotency.get_cached_result("client-a", "key-1")  # must not raise

        assert result is None
        assert any("idempotency read failed" in r.getMessage() for r in caplog.records)


class TestStoreResult:
    def test_writes_the_result_with_a_ttl(self):
        mock_db = MagicMock()

        with patch("app.mcp_server.idempotency.get_db", return_value=mock_db):
            idempotency.store_result("client-a", "key-1", {"id": "r1"})

        written = mock_db.collection.return_value.document.return_value.set.call_args[0][0]
        assert written["result"] == {"id": "r1"}
        assert "created_at" in written
        assert "ttl" in written
        assert written["ttl"] > written["created_at"]

    def test_a_write_failure_is_swallowed_and_logged(self, caplog):
        with patch("app.mcp_server.idempotency.get_db", side_effect=RuntimeError("firestore down")):
            with caplog.at_level(logging.WARNING, logger="app.mcp_server.idempotency"):
                idempotency.store_result("client-a", "key-1", {"id": "r1"})  # must not raise

        assert any("idempotency write failed" in r.getMessage() for r in caplog.records)

    def test_a_stored_result_is_retrievable_through_the_same_pair(self):
        """End-to-end against one shared fake store (not a mock's call
        history) to prove the round trip actually works, not just that each
        function calls Firestore in isolation."""
        store: dict[str, dict] = {}

        def fake_document(doc_id):
            doc = MagicMock()
            doc.set.side_effect = lambda data: store.__setitem__(doc_id, data)

            def fake_get():
                if doc_id in store:
                    snap = MagicMock(exists=True)
                    snap.to_dict.return_value = store[doc_id]
                    return snap
                return MagicMock(exists=False)

            doc.get.side_effect = fake_get
            return doc

        mock_db = MagicMock()
        mock_db.collection.return_value.document.side_effect = fake_document

        with patch("app.mcp_server.idempotency.get_db", return_value=mock_db):
            assert idempotency.get_cached_result("client-a", "key-1") is None
            idempotency.store_result("client-a", "key-1", {"id": "r1"})
            assert idempotency.get_cached_result("client-a", "key-1") == {"id": "r1"}
            # A different key for the same client is a genuine miss.
            assert idempotency.get_cached_result("client-a", "key-2") is None
