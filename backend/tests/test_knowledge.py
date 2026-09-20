"""Tests for services/knowledge.py: the corpus, retrieval, and rendering
that back the Sous Chef's cross-recipe grounding.
"""

from unittest.mock import MagicMock, patch

import pytest

from app.cache import MemoryCache
from app.services import ingredients, knowledge


def _profile(slug, name, aliases=None, **prose):
    base = {"what_it_is": "x", "role": "", "substitutions": "", "buying": "",
            "storage": "", "mistakes": "", "allergens": ""}
    base.update(prose)
    return {"slug": slug, "name": name, "aliases": aliases or [], **base}


def _doc(slug, title, secrets=None, about="", sous_chef_notes=""):
    return {"slug": slug, "title": title, "secrets": secrets or [], "about": about, "sous_chef_notes": sous_chef_notes}


def _index(profiles):
    return ingredients.build_index(profiles)


# ── chunking ─────────────────────────────────────────────────────────────────

class TestChunking:
    def test_one_chunk_per_secret(self):
        doc = _doc("ramen", "Tonkotsu Ramen", secrets=[
            {"title": "The Broth", "body": "Simmer the bones for 12 hours, skimming often."},
            {"title": "The Tare", "body": "Balance salt and umami before adding to the bowl."},
        ])
        chunks = knowledge._chunks_for(doc)
        assert [(c["kind"], c["heading"]) for c in chunks] == [
            ("secret", "The Broth"), ("secret", "The Tare"),
        ]
        assert all(c["recipe_slug"] == "ramen" and c["recipe_title"] == "Tonkotsu Ramen" for c in chunks)

    def test_secret_missing_title_or_body_is_skipped(self):
        doc = _doc("ramen", "Tonkotsu Ramen", secrets=[{"title": "", "body": "x" * 50}, {"title": "T", "body": ""}])
        assert knowledge._chunks_for(doc) == []

    def test_about_and_notes_split_into_paragraphs_over_the_minimum_length(self):
        about = "Short.\n\n" + "This paragraph is definitely long enough to survive the minimum length filter."
        doc = _doc("carbonara", "Carbonara", about=about, sous_chef_notes="Also long enough to be its own paragraph here.")
        chunks = knowledge._chunks_for(doc)
        kinds = [c["kind"] for c in chunks]
        assert kinds == ["about", "notes"]  # "Short." (6 chars) dropped
        assert "definitely long enough" in chunks[0]["body"]

    def test_chunk_body_capped_at_max_chunk_chars(self):
        doc = _doc("ramen", "Tonkotsu Ramen", secrets=[{"title": "T", "body": "x" * 1000}])
        assert len(knowledge._chunks_for(doc)[0]["body"]) == knowledge.MAX_CHUNK_CHARS

    def test_no_secrets_notes_or_about_yields_no_chunks(self):
        assert knowledge._chunks_for({"slug": "x", "title": "X"}) == []


# ── rendering ────────────────────────────────────────────────────────────────

class TestRendering:
    def test_render_profile_full(self):
        p = _profile("pork-belly", "Pork Belly", aliases=["belly pork", "samgyeopsal"],
                      what_it_is="A fatty cut from the belly.", role="fat, richness",
                      substitutions="Jowl is fattier; loin is much leaner.",
                      buying="Look for even fat/meat striping.", storage="Fridge 3 days, freeze 3 months.",
                      mistakes="Skipping the sear leaves it flabby.", allergens="")
        line = knowledge.render_profile(p)
        assert line.startswith("- Pork Belly (aka: belly pork, samgyeopsal): A fatty cut from the belly.")
        assert "Role: fat, richness" in line
        assert "Swaps: Jowl is fattier" in line
        assert "Allergens:" not in line  # empty field omitted

    def test_render_profile_no_aliases(self):
        line = knowledge.render_profile(_profile("salt", "Salt", what_it_is="A mineral."))
        assert line == "- Salt: A mineral."

    def test_ingredients_block_joins_with_newlines_and_respects_the_cap(self):
        profiles = [_profile(f"p{i}", f"Ingredient {i}", what_it_is="x" * 100) for i in range(5)]
        block = knowledge.ingredients_block(profiles)
        assert block.count("\n") == 4
        with patch.object(knowledge, "MAX_INGREDIENTS_BLOCK_CHARS", 50):
            capped = knowledge.ingredients_block(profiles)
        assert len(capped) <= 60  # one line fits, the rest are dropped

    def test_knowledge_block_renders_each_hit_kind(self):
        hits = [
            {"kind": "profile", "profile": _profile("jowl", "Pork Jowl", what_it_is="Fattier than belly.")},
            {"kind": "secret", "chunk": {"recipe_title": "Carbonara", "heading": "Why Guanciale", "body": "Fat matters."}},
            {"kind": "notes", "chunk": {"recipe_title": "Ramen", "body": "Don't skip the skim."}},
            {"kind": "about", "chunk": {"recipe_title": "Hummus", "body": "A Levantine classic."}},
        ]
        block = knowledge.knowledge_block(hits)
        lines = block.splitlines()
        assert lines[0] == "- Pork Jowl (ingredient note): Fattier than belly."
        assert lines[1] == "- From \"Carbonara\", Chef's Secret \"Why Guanciale\": Fat matters."
        assert lines[2] == "- From \"Ramen\", the chef's notes: Don't skip the skim."
        assert lines[3] == "- From \"Hummus\": A Levantine classic."


# ── KnowledgeBase.profiles_for ────────────────────────────────────────────────

class TestProfilesFor:
    def test_resolves_recipe_order_dedupes_and_caps(self):
        profiles = [_profile("garlic", "Garlic"), _profile("salt", "Salt")]
        kb = knowledge.KnowledgeBase(profiles=tuple(profiles), chunks=(), index=_index(profiles))
        doc = {"ingredients": [{"item": "garlic cloves"}, {"item": "salt"}, {"item": "garlic"}]}
        result = kb.profiles_for(doc)
        assert [p["slug"] for p in result] == ["garlic", "salt"]  # deduped, recipe order

    def test_includes_component_ingredients(self):
        profiles = [_profile("ginger", "Ginger")]
        kb = knowledge.KnowledgeBase(profiles=tuple(profiles), chunks=(), index=_index(profiles))
        doc = {"ingredients": [], "components": [{"ingredients": [{"item": "ginger"}]}]}
        assert [p["slug"] for p in kb.profiles_for(doc)] == ["ginger"]

    def test_unresolved_ingredients_are_skipped(self):
        profiles = [_profile("garlic", "Garlic")]
        kb = knowledge.KnowledgeBase(profiles=tuple(profiles), chunks=(), index=_index(profiles))
        doc = {"ingredients": [{"item": "dragonfruit"}]}
        assert kb.profiles_for(doc) == []

    def test_capped_at_max_ingredient_profiles(self):
        profiles = [_profile(f"p{i}", f"Ingredient{i}") for i in range(30)]
        kb = knowledge.KnowledgeBase(profiles=tuple(profiles), chunks=(), index=_index(profiles))
        doc = {"ingredients": [{"item": f"Ingredient{i}"} for i in range(30)]}
        assert len(kb.profiles_for(doc)) == knowledge.MAX_INGREDIENT_PROFILES


# ── KnowledgeBase.retrieve ───────────────────────────────────────────────────

class TestRetrieve:
    def _kb(self, profiles=(), chunks=()):
        return knowledge.KnowledgeBase(profiles=tuple(profiles), chunks=tuple(chunks), index=_index(list(profiles)))

    def test_phrase_match_beats_term_overlap(self):
        profiles = [
            _profile("pork-belly", "Pork Belly", what_it_is="A fatty cut used in many pork dishes."),
            _profile("pork-jowl", "Pork Jowl", what_it_is="The jowl, fattier than belly."),
        ]
        kb = self._kb(profiles)
        hits = kb.retrieve("Can I use pork jowl instead of the belly?")
        assert hits[0]["profile"]["slug"] == "pork-jowl"  # exact phrase hit outranks overlap

    def test_excludes_profiles_already_shown(self):
        profiles = [_profile("garlic", "Garlic", what_it_is="An allium used in almost everything.")]
        kb = self._kb(profiles)
        hits = kb.retrieve("tell me about garlic")
        assert hits and hits[0]["profile"]["slug"] == "garlic"
        # Already rendered in <ingredients> for the current recipe — must not repeat in <knowledge>.
        assert kb.retrieve("tell me about garlic", exclude_profiles=frozenset({"garlic"})) == []

    def test_excludes_chunks_from_the_current_recipe(self):
        chunks = ({"recipe_slug": "carbonara", "recipe_title": "Carbonara", "kind": "secret",
                   "heading": "Guanciale", "body": "Guanciale has more fat than pancetta."},)
        kb = self._kb(chunks=chunks)
        assert kb.retrieve("why guanciale not pancetta") != []
        assert kb.retrieve("why guanciale not pancetta", exclude_recipe="carbonara") == []

    def test_falls_back_to_the_previous_turn_when_the_question_alone_is_thin(self):
        profiles = [_profile("belacan", "Belacan", what_it_is="Fermented shrimp paste used in Southeast Asian cooking.")]
        kb = self._kb(profiles)
        assert kb.retrieve("how much do I use?") == []  # nothing to match on its own
        hits = kb.retrieve("how much do I use?", previous="What is belacan?")
        assert hits and hits[0]["profile"]["slug"] == "belacan"

    def test_returns_at_most_max_knowledge_hits(self):
        profiles = [_profile(f"p{i}", f"Spice{i}", what_it_is="A spice used in many recipes across the site.") for i in range(6)]
        kb = self._kb(profiles)
        hits = kb.retrieve("spice spice spice spice spice")
        assert len(hits) <= knowledge.MAX_KNOWLEDGE_HITS

    def test_no_match_returns_empty_list(self):
        assert knowledge.EMPTY.retrieve("what is dragonfruit?") == []

    def test_stable_order_for_equal_scores(self):
        profiles = [_profile("aaa", "Aaa Spice", what_it_is="spice"), _profile("bbb", "Bbb Spice", what_it_is="spice")]
        kb = self._kb(profiles)
        hits = kb.retrieve("spice spice spice")
        slugs = [h["profile"]["slug"] for h in hits]
        assert slugs == sorted(slugs)  # tie-broken by key, deterministically


# ── build_knowledge_base / get_knowledge_base ────────────────────────────────

class TestBuildAndGet:
    def _db(self, recipe_docs, profile_docs):
        db = MagicMock()

        def stream(*a, **k):
            # get_all_published_docs and list_profiles both call db.collection(...).stream();
            # route by which collection was asked for last.
            return iter(recipe_docs if db.collection.call_args[0][0] == "recipes" else profile_docs)

        db.collection.return_value = db
        db.where.return_value = db
        db.order_by.return_value = db
        db.limit.return_value = db
        db.stream.side_effect = stream
        return db

    def _recipe_doc(self, slug, title, secret_body="A long enough secret body to be a real chunk here."):
        doc = MagicMock()
        doc.id = slug
        doc.to_dict.return_value = {
            "slug": slug, "title": title,
            "secrets": [{"title": "A Secret", "body": secret_body}],
            "created_at": None, "updated_at": None,
        }
        return doc

    def _profile_doc(self, slug, name):
        doc = MagicMock()
        doc.id = slug
        doc.to_dict.return_value = {"name": name, "aliases": [], "what_it_is": "x", "role": "",
                                     "substitutions": "", "buying": "", "storage": "", "mistakes": "", "allergens": ""}
        return doc

    def test_build_combines_profiles_and_chunks(self):
        db = self._db([self._recipe_doc("ramen", "Ramen")], [self._profile_doc("garlic", "Garlic")])
        kb = knowledge.build_knowledge_base(db)
        assert [p["slug"] for p in kb.profiles] == ["garlic"]
        assert kb.chunks[0]["recipe_slug"] == "ramen"

    def test_malformed_recipe_doc_is_skipped_not_fatal(self):
        recipe_docs = [self._recipe_doc("ramen", "Ramen")]
        db = self._db(recipe_docs, [])
        with patch("app.services.knowledge.get_all_published_docs", return_value=[{"slug": "ok", "title": "Ok"}, "not-a-dict"]):
            kb = knowledge.build_knowledge_base(db)
        assert kb.chunks == ()  # neither doc has secrets/about/notes, but no crash on the bad entry

    def test_get_knowledge_base_is_cached_under_the_versioned_key(self):
        db = self._db([self._recipe_doc("ramen", "Ramen")], [self._profile_doc("garlic", "Garlic")])
        with patch("app.services.knowledge.cache", MemoryCache(ttl=60)) as mem:
            first = knowledge.get_knowledge_base(db)
            second = knowledge.get_knowledge_base(db)
        assert [p["slug"] for p in first.profiles] == [p["slug"] for p in second.profiles]
        assert mem.get(knowledge.KNOWLEDGE_CACHE_KEY) is not None

    def test_get_knowledge_base_never_raises_falls_back_to_empty(self):
        db = MagicMock()
        db.collection.side_effect = RuntimeError("Firestore is down")
        with patch("app.services.knowledge.cache", MemoryCache(ttl=60)):
            assert knowledge.get_knowledge_base(db) is knowledge.EMPTY

    def test_get_knowledge_base_falls_back_on_alias_conflict_in_stored_profiles(self):
        """A cache payload (or a manually-edited Firestore state) with two
        profiles whose keys collide must degrade to EMPTY, not 500."""
        db = self._db([], [self._profile_doc("a", "Garlic"), self._profile_doc("b", "Garlic")])
        with patch("app.services.knowledge.cache", MemoryCache(ttl=60)):
            assert knowledge.get_knowledge_base(db) is knowledge.EMPTY
