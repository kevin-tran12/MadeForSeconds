"""Unit tests for seed.py's sample data, and the fixture that depends on it.

The reason this file exists: on 2026-09-05 the Sous Chef eval was run for the
first time since PR #106 wrote it, and 20 of its 21 cases could not run at all.
Seven named `thai-basil-chicken`, a recipe that never existed anywhere, and
thirteen named `hainanese-chicken-rice`, which is in production but was never
in seed.py. Nothing caught it because the eval is not a CI gate and every rules
PR since #106 had marked it "Not run" — so the fixture drifted from the seed
data for months, silently.

test_eval_fixture_slugs_are_seeded is the guard for that. The rest check the
ingredient profiles are actually loadable and resolvable, since an unusable
profile fails the same silent way (the knowledge base swallows bad profiles and
falls back to EMPTY by design).

seed.py imports only google.cloud.firestore.Client at module level and opens no
connection until main(), so importing it here is safe.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import seed  # noqa: E402

from app.models import IngredientProfileIn  # noqa: E402
from app.services import ingredients  # noqa: E402
from app.services.recipes import generate_slug  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sous_chef_eval.json"
EVAL_CASES = json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]
SEEDED_SLUGS = {recipe["slug"] for recipe in seed.RECIPES}


@pytest.mark.parametrize("case", EVAL_CASES, ids=lambda c: c["id"])
def test_eval_fixture_slugs_are_seeded(case):
    """Every eval case names a recipe seed.py actually seeds.

    A case naming an unseeded recipe cannot run anywhere: eval_sous_chef.py
    reports "recipe X not published here" and counts it a failure, so the case
    is dead weight that still costs a line in the table.
    """
    assert case["slug"] in SEEDED_SLUGS, (
        f"{case['id']} names {case['slug']!r}, which seed.py does not seed "
        f"(seeded: {sorted(SEEDED_SLUGS)}). Add the recipe to seed.py's RECIPES "
        f"or repoint the case."
    )


def test_eval_fixture_case_ids_are_unique():
    ids = [case["id"] for case in EVAL_CASES]
    assert len(ids) == len(set(ids))


def test_seeded_recipes_have_unique_slugs_and_are_published():
    slugs = [recipe["slug"] for recipe in seed.RECIPES]
    assert len(slugs) == len(set(slugs))
    # get_published_doc only ever returns published docs, so an unpublished
    # sample recipe would be invisible to the eval and to the site alike.
    assert all(recipe["published"] for recipe in seed.RECIPES)


@pytest.mark.parametrize("profile", seed.INGREDIENT_PROFILES, ids=lambda p: p["slug"])
def test_seeded_profile_validates_and_matches_its_slug(profile):
    """Each sample profile passes the real model and carries the slug
    generate_slug(name) would produce.

    seed.py hardcodes the slug rather than importing generate_slug, because the
    staging-seed pipeline job runs it as a bare script without the app's
    settings; this test is what keeps the hardcoded value honest.
    """
    body = {k: v for k, v in profile.items() if k != "slug"}
    IngredientProfileIn.model_validate(body)  # prose cap, field lengths, aliases
    assert profile["slug"] == generate_slug(profile["name"])


def test_seeded_profiles_do_not_collide():
    """No two sample profiles claim the same lookup key.

    upsert_profile raises AliasConflict on a collision, so a colliding pair
    would make the profiles unwritable through the normal authoring path even
    though seed.py's raw set() would happily store them.
    """
    ingredients.build_index(
        [{**{k: v for k, v in p.items() if k != "slug"}, "slug": p["slug"]} for p in seed.INGREDIENT_PROFILES]
    )


def test_seeded_profiles_resolve_from_the_recipe_items_that_need_them():
    """The profile cases in the eval fixture depend on these exact resolutions.

    profile-jowl-vs-belly needs the ramen's own "pork belly, skin-on" line to
    resolve to the pork-belly profile (that is what puts it in <ingredients>),
    and needs "pork jowl" to resolve to jowl rather than falling back to belly
    on the shared "pork" token.
    """
    index = ingredients.build_index(
        [{**{k: v for k, v in p.items() if k != "slug"}, "slug": p["slug"]} for p in seed.INGREDIENT_PROFILES]
    )
    ramen = next(r for r in seed.RECIPES if r["slug"] == "tonkotsu-ramen")
    # recipe_items is what KnowledgeBase.profiles_for iterates, so it covers
    # both shapes: this ramen lists its items top-level, the Hainanese recipe
    # carries them inside components.
    belly_item = next(item for item in ingredients.recipe_items(ramen) if "pork belly" in item)

    assert index.resolve(belly_item)[0] == "pork-belly"
    assert index.resolve("pork jowl")[0] == "pork-jowl"
    assert index.resolve("belacan")[0] == "belacan"
