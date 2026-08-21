"""Tests for the durable receipt-association record (app/services/receipt_ledger.py).

A receipt object survives seven years under the bucket retention policy. The
recipe document naming it does not. These tests pin the property that makes the
retained object evidence rather than an anonymous scan: the association is
written down, durably, before anything removes it — on all three paths that can
remove it, and *not* written when nothing was detached.

The ordering tests matter most. A record written for a detachment that then
failed is a harmless duplicate; a detachment with no record cannot be undone.
"""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.models import RecipeUpdate
from app.services import receipt_ledger
from app.services import recipes as svc


R1 = "https://storage.googleapis.com/test-receipts/r1.jpg"
R2 = "https://storage.googleapis.com/test-receipts/r2.pdf"


def _unlink(client, recipe_id, url):
    """DELETE with a JSON body — TestClient.delete() does not accept json=."""
    return client.request(
        "DELETE",
        f"/api/admin/recipes/{recipe_id}/receipts",
        content=json.dumps({"url": url}),
        headers={"Content-Type": "application/json"},
    )


def _chain_db():
    """Chainable Firestore mock matching the conftest pattern."""
    mock = MagicMock()
    mock.collection.return_value = mock
    mock.document.return_value = mock
    mock.where.return_value = mock
    mock.order_by.return_value = mock
    mock.limit.return_value = mock
    mock.select.return_value = mock
    return mock


def _recipe(**over):
    data = {
        "title": "Braised Short Ribs",
        "slug": "braised-short-ribs",
        "categories": ["dinner"],
        "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "created_via": "admin",
        "receipt_urls": [],
        "published": False,
        "image_url": None,
    }
    data.update(over)
    return data


def _written_payloads(db):
    """The record bodies handed to batch.set(), in order."""
    return [call.args[1] for call in db.batch.return_value.set.call_args_list]


# ── record_detachment ─────────────────────────────────────────────────────────

class TestRecordDetachment:
    def test_writes_one_record_per_url_in_a_single_batch(self):
        db = _chain_db()

        count = receipt_ledger.record_detachment(
            db,
            receipt_urls=[R1, R2],
            recipe_id="rec-1",
            recipe=_recipe(),
            reason=receipt_ledger.DETACH_RECIPE_DELETED,
            source="admin",
            actor="admin@example.com",
        )

        assert count == 2
        payloads = _written_payloads(db)
        assert [p["receipt_url"] for p in payloads] == [R1, R2]
        # One commit, not one per URL: a recipe's receipts record all-or-nothing.
        db.batch.return_value.commit.assert_called_once()
        assert receipt_ledger.COLLECTION in [c.args[0] for c in db.collection.call_args_list]

    def test_record_carries_the_identity_the_recipe_is_about_to_take_with_it(self):
        db = _chain_db()
        recipe = _recipe(title="Pho Bo", slug="pho-bo", categories=["soup", "dinner"])

        receipt_ledger.record_detachment(
            db,
            receipt_urls=[R1],
            recipe_id="rec-9",
            recipe=recipe,
            reason=receipt_ledger.DETACH_UNLINKED,
            source="admin",
            actor="admin@example.com",
        )

        payload = _written_payloads(db)[0]
        # Snapshotted, not referenced — the recipe may not exist a moment later.
        assert payload["recipe_id"] == "rec-9"
        assert payload["recipe_title"] == "Pho Bo"
        assert payload["recipe_slug"] == "pho-bo"
        assert payload["recipe_categories"] == ["soup", "dinner"]
        assert payload["recipe_created_via"] == "admin"
        assert payload["reason"] == receipt_ledger.DETACH_UNLINKED
        assert payload["detached_via"] == "admin"
        assert payload["detached_by"] == "admin@example.com"
        assert isinstance(payload["detached_at"], datetime)

    def test_no_receipts_writes_nothing(self):
        db = _chain_db()

        assert receipt_ledger.record_detachment(
            db,
            receipt_urls=[],
            recipe_id="rec-1",
            recipe=_recipe(),
            reason=receipt_ledger.DETACH_RECIPE_DELETED,
            source="admin",
        ) == 0

        db.batch.assert_not_called()

    def test_blank_urls_are_skipped(self):
        db = _chain_db()

        count = receipt_ledger.record_detachment(
            db,
            receipt_urls=["", R1, None],
            recipe_id="rec-1",
            recipe=_recipe(),
            reason=receipt_ledger.DETACH_UNLINKED,
            source="mcp",
        )

        assert count == 1
        assert [p["receipt_url"] for p in _written_payloads(db)] == [R1]


# ── removed_receipt_urls ──────────────────────────────────────────────────────

class TestRemovedReceiptUrls:
    def test_field_omitted_means_left_alone_not_cleared(self):
        """exclude_unset: an absent key must never read as "remove everything"."""
        assert receipt_ledger.removed_receipt_urls(
            {"receipt_urls": [R1, R2]}, {"title": "New title"}
        ) == []

    def test_shortened_list_reports_the_dropped_url(self):
        assert receipt_ledger.removed_receipt_urls(
            {"receipt_urls": [R1, R2]}, {"receipt_urls": [R1]}
        ) == [R2]

    def test_cleared_list_reports_all(self):
        assert receipt_ledger.removed_receipt_urls(
            {"receipt_urls": [R1, R2]}, {"receipt_urls": []}
        ) == [R1, R2]

    def test_null_list_reports_all(self):
        assert receipt_ledger.removed_receipt_urls(
            {"receipt_urls": [R1]}, {"receipt_urls": None}
        ) == [R1]

    def test_additions_report_nothing(self):
        assert receipt_ledger.removed_receipt_urls(
            {"receipt_urls": [R1]}, {"receipt_urls": [R1, R2]}
        ) == []


# ── delete_recipe ─────────────────────────────────────────────────────────────

class TestDeleteRecipeRecordsAssociation:
    def test_records_every_receipt_before_the_document_goes(self):
        db = _chain_db()
        doc = MagicMock()
        doc.exists = True
        doc.to_dict.return_value = _recipe(receipt_urls=[R1, R2])
        db.get.return_value = doc

        with (
            patch("app.services.recipes.cache"),
            patch("app.services.uploads.delete_recipe_image_blob"),
        ):
            svc.delete_recipe(db, "rec-1", source="admin", actor="admin@example.com")

        payloads = _written_payloads(db)
        assert [p["receipt_url"] for p in payloads] == [R1, R2]
        assert {p["reason"] for p in payloads} == {receipt_ledger.DETACH_RECIPE_DELETED}
        db.delete.assert_called_once()

    def test_a_failed_ledger_write_leaves_the_recipe_intact(self):
        """The ordering guarantee. Nothing is destroyed if the record can't be kept."""
        db = _chain_db()
        doc = MagicMock()
        doc.exists = True
        doc.to_dict.return_value = _recipe(receipt_urls=[R1], image_url="https://x/i.jpg")
        db.get.return_value = doc

        with (
            patch("app.services.recipes.cache"),
            patch("app.services.uploads.delete_recipe_image_blob") as img_deleter,
            patch(
                "app.services.receipt_ledger.record_detachment",
                side_effect=RuntimeError("firestore unavailable"),
            ),
        ):
            with pytest.raises(RuntimeError):
                svc.delete_recipe(db, "rec-1", source="admin")

        db.delete.assert_not_called()
        img_deleter.assert_not_called()

    def test_mcp_deletion_is_attributed_to_mcp_with_no_admin_actor(self):
        """Provenance survives the interface it came through.

        An agent deleting a draft over MCP has no admin email behind it, so the
        record has to say "mcp" and leave detached_by null rather than silently
        looking like an admin action.
        """
        db = _chain_db()
        doc = MagicMock()
        doc.exists = True
        doc.to_dict.return_value = _recipe(receipt_urls=[R1])
        db.get.return_value = doc

        with (
            patch("app.services.recipes.cache"),
            patch("app.services.uploads.delete_recipe_image_blob"),
        ):
            svc.delete_recipe(db, "rec-1", source="mcp", require_draft=True)

        payload = _written_payloads(db)[0]
        assert payload["detached_via"] == "mcp"
        assert payload["detached_by"] is None

    def test_recipe_without_receipts_records_nothing(self):
        db = _chain_db()
        doc = MagicMock()
        doc.exists = True
        doc.to_dict.return_value = _recipe(receipt_urls=[])
        db.get.return_value = doc

        with (
            patch("app.services.recipes.cache"),
            patch("app.services.uploads.delete_recipe_image_blob"),
        ):
            svc.delete_recipe(db, "rec-1", source="mcp")

        db.batch.assert_not_called()
        db.delete.assert_called_once()


# ── update_recipe ─────────────────────────────────────────────────────────────

class TestUpdateRecipeRecordsAssociation:
    def test_dropping_a_receipt_via_update_is_recorded(self):
        """The path the review did not name: PUT with a shorter receipt_urls list.

        This detaches a receipt exactly as the DELETE endpoint does, and nothing
        in the request says so. Without this, the unlink endpoint would be
        guarded while the ordinary update route silently bypassed the guard.
        """
        db = _chain_db()
        doc = MagicMock()
        doc.exists = True
        doc.to_dict.return_value = _recipe(receipt_urls=[R1, R2])
        db.get.return_value = doc

        with patch("app.services.recipes.cache"):
            svc.update_recipe(
                db,
                "rec-1",
                RecipeUpdate(receipt_urls=[R1]),
                source="admin",
                actor="admin@example.com",
            )

        payloads = _written_payloads(db)
        assert [p["receipt_url"] for p in payloads] == [R2]
        assert payloads[0]["reason"] == receipt_ledger.DETACH_REPLACED

    def test_update_that_does_not_touch_receipts_records_nothing(self):
        db = _chain_db()
        doc = MagicMock()
        doc.exists = True
        doc.to_dict.return_value = _recipe(receipt_urls=[R1])
        db.get.return_value = doc

        with patch("app.services.recipes.cache"):
            svc.update_recipe(db, "rec-1", RecipeUpdate(title="Renamed"), source="admin")

        db.batch.assert_not_called()

    def test_adding_a_receipt_records_nothing(self):
        db = _chain_db()
        doc = MagicMock()
        doc.exists = True
        doc.to_dict.return_value = _recipe(receipt_urls=[R1])
        db.get.return_value = doc

        with patch("app.services.recipes.cache"):
            svc.update_recipe(db, "rec-1", RecipeUpdate(receipt_urls=[R1, R2]), source="admin")

        db.batch.assert_not_called()


# ── admin unlink endpoint ─────────────────────────────────────────────────────

class TestUnlinkEndpointRecordsAssociation:
    def _doc(self, urls):
        doc = MagicMock()
        doc.exists = True
        doc.to_dict.return_value = _recipe(receipt_urls=urls)
        return doc

    def test_unlink_records_the_association_and_the_admin_who_did_it(
        self, authenticated_client, mock_db, mock_admin, mock_cache
    ):
        mock_db.collection.return_value.document.return_value.get.return_value = self._doc([R1])

        response = _unlink(authenticated_client, "rec-1", R1)

        assert response.status_code == 204
        payloads = _written_payloads(mock_db)
        assert len(payloads) == 1
        assert payloads[0]["receipt_url"] == R1
        assert payloads[0]["reason"] == receipt_ledger.DETACH_UNLINKED
        assert payloads[0]["detached_by"] == mock_admin

    def test_a_failed_ledger_write_leaves_the_receipt_attached(
        self, authenticated_client, mock_db, mock_cache
    ):
        mock_db.collection.return_value.document.return_value.get.return_value = self._doc([R1])

        with patch(
            "app.services.receipt_ledger.record_detachment",
            side_effect=RuntimeError("firestore unavailable"),
        ):
            with pytest.raises(RuntimeError):
                _unlink(authenticated_client, "rec-1", R1)

        mock_db.collection.return_value.document.return_value.update.assert_not_called()

    def test_unknown_url_is_rejected_before_anything_is_recorded(
        self, authenticated_client, mock_db, mock_cache
    ):
        mock_db.collection.return_value.document.return_value.get.return_value = self._doc([R1])

        response = _unlink(authenticated_client, "rec-1", R2)

        assert response.status_code == 404
        mock_db.batch.assert_not_called()
