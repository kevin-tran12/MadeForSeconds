"""Tests for mcp_server/audit.py: target extraction per tool category and
the best-effort write behavior.

test_mcp_wrapper.py::TestAuditTrail checks only that wrapper.py calls this
module at the right time (mutating tools, not read-only ones) with the
right arguments — this file exercises record()/_build_target() directly.
"""

import logging
from unittest.mock import MagicMock, patch

from app.mcp_server import audit


class TestBuildTargetRecipeTools:
    def test_update_recipe_takes_recipe_id_from_kwargs(self):
        target = audit._build_target("update_recipe", {"recipe_id": "r1", "title": "New"}, {"id": "r1"})
        assert target == {"recipe_id": "r1"}

    def test_create_recipe_has_no_id_argument_so_target_comes_from_the_result(self):
        target = audit._build_target("create_recipe", {"title": "New Dish"}, {"id": "r2", "slug": "new-dish"})
        assert target == {"recipe_id": "r2", "slug": "new-dish"}

    def test_a_failed_create_recipe_has_no_id_anywhere(self):
        """Nothing was created, so there is nothing to name — an empty
        target is the honest answer, not a guess."""
        target = audit._build_target("create_recipe", {"title": "New Dish"}, {"error": "slug_conflict"})
        assert target == {}

    def test_delete_recipe_takes_recipe_id_from_kwargs_even_on_failure(self):
        target = audit._build_target("delete_recipe", {"recipe_id": "ghost", "confirm_title": "X"},
                                      {"error": "not_found"})
        assert target == {"recipe_id": "ghost"}


class TestBuildTargetOtherTools:
    def test_create_expense_target_comes_from_the_result_id(self):
        target = audit._build_target("create_expense", {"vendor": "Store"}, {"id": "e1"})
        assert target == {"expense_id": "e1"}

    def test_publish_instagram_post_captures_the_media_id(self):
        target = audit._build_target("publish_instagram_post", {"image_url": "https://x"}, {"id": "media1"})
        assert target == {"media_id": "media1"}

    def test_publish_recipe_to_instagram_captures_both_the_recipe_and_the_media(self):
        target = audit._build_target(
            "publish_recipe_to_instagram", {"slug": "carbonara", "recipe_id": "r1"}, {"id": "media2"},
        )
        assert target == {"media_id": "media2", "recipe_id": "r1", "slug": "carbonara"}

    def test_upsert_ingredient_prefers_the_resolved_slug_from_the_result(self):
        """The slug kwarg is often blank on a first-time create (the tool
        computes it from the name) — the result's resolved slug is the
        authoritative one whenever it's present."""
        target = audit._build_target("upsert_ingredient", {"name": "Garlic", "slug": ""}, {"slug": "garlic"})
        assert target == {"ingredient_slug": "garlic"}

    def test_delete_ingredient_takes_the_slug_from_kwargs(self):
        target = audit._build_target("delete_ingredient", {"slug": "garlic"}, {"deleted": True, "slug": "garlic"})
        assert target == {"ingredient_slug": "garlic"}

    def test_upload_tools_have_no_target_field_in_this_schema(self):
        assert audit._build_target("request_image_upload", {"filename": "x.jpg"}, {"upload_url": "..."}) == {}
        assert audit._build_target("upload_image_from_url", {"source_url": "https://x"}, {"image_url": "..."}) == {}

    def test_unknown_tool_name_has_no_target(self):
        assert audit._build_target("some_future_tool", {"a": 1}, {"id": "x"}) == {}


class TestRecord:
    def test_writes_the_full_expected_shape(self):
        mock_db = MagicMock()
        with patch("app.mcp_server.audit.get_db", return_value=mock_db):
            audit.record(
                "update_recipe", {"recipe_id": "r1", "title": "New"}, {"id": "r1"}, "client-a", None, "mcp:client-a",
            )

        mock_db.collection.assert_called_once_with("mcp_audit")
        doc = mock_db.collection.return_value.document.return_value.set.call_args[0][0]
        assert doc["tool"] == "update_recipe"
        assert doc["ok"] is True
        assert doc["error"] is None
        assert doc["client_id"] == "client-a"
        assert doc["subject"] is None
        assert doc["actor"] == "mcp:client-a"
        assert doc["target"] == {"recipe_id": "r1"}
        assert doc["arg_keys"] == ["recipe_id", "title"]
        assert "at" in doc

    def test_arg_keys_never_carry_values_only_names(self):
        """The whole point of arg_keys: it is a record of WHAT was passed,
        never the actual (possibly sensitive, possibly large) argument
        values themselves."""
        mock_db = MagicMock()
        with patch("app.mcp_server.audit.get_db", return_value=mock_db):
            audit.record(
                "create_recipe",
                {"title": "Secret Family Recipe", "sous_chef_notes": "Don't tell anyone about the ingredient"},
                {"id": "r1"},
                None,
                None,
                "mcp",
            )

        doc = mock_db.collection.return_value.document.return_value.set.call_args[0][0]
        assert doc["arg_keys"] == ["sous_chef_notes", "title"]
        serialized = str(doc)
        assert "Secret Family Recipe" not in serialized
        assert "Don't tell anyone" not in serialized

    def test_a_write_failure_is_swallowed_and_logged(self, caplog):
        with patch("app.mcp_server.audit.get_db", side_effect=RuntimeError("firestore down")):
            with caplog.at_level(logging.WARNING, logger="app.mcp_server.audit"):
                audit.record(
                    "update_recipe", {"recipe_id": "r1"}, {"id": "r1"}, None, None, "mcp",
                )  # must not raise

        assert any("mcp audit write failed" in r.getMessage() for r in caplog.records)
