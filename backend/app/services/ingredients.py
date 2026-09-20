"""Ingredient profiles: normalising a recipe's free-text ingredient lines
into lookup keys, matching them against owner-authored profiles, and the
Firestore CRUD + coverage-gap accounting that backs the MCP authoring tools
and the admin "Ingredients" tab.

Why normalisation at all: a recipe's `item` string carries prep text and
disjunctions a reader wrote for a human ("pork belly, skin-on", "guanciale or
pancetta", "garlic cloves"), not a clean ingredient name. candidate_keys()
turns one such string into an ordered list of canonical lookup keys, most
specific first, so a profile authored under "pork belly" is found from
"pork belly, skin-on" without the owner ever normalising a recipe by hand.

Deterministic and dependency-free by design — no NLP, no external service —
so it stays fast, offline-testable, and predictable enough that an owner
reading the admin coverage tab can tell why an ingredient matched or didn't.
"""

import re
from dataclasses import dataclass
from datetime import datetime, timezone

from ..cache import cache
from ..models import IngredientProfileIn
from .users import clean_text

_COLLECTION = "ingredients"

# Bare unit/count words that name a quantity, not the ingredient itself —
# stripping one from the end of a phrase is how "garlic cloves" and "garlic"
# resolve to the same profile. Deliberately not exhaustive (no attempt at
# "bunches"/"thumbs"/"knobs" plurals): the phrases these are stripped from
# are also run through canon()'s own singularisation, so most plural counts
# never reach this list still plural in the first place.
_COUNT_NOUNS = {
    "clove", "cloves", "stalk", "stalks", "sprig", "sprigs", "bunch",
    "head", "heads", "sheet", "sheets", "slice", "slices", "piece", "pieces",
    "leaf", "leaves", "stick", "sticks", "knob", "thumb",
}

_PAREN_RE = re.compile(r"\([^)]*\)")
_PURPOSE_TAIL_RES = (
    re.compile(r"\s+(?:to|for)\s+(?:garnish|serve|serving|taste|frying|greasing)\b.*$", re.I),
    re.compile(r"\s+plus\b.*$", re.I),
    re.compile(r"\s+or\s+(?:more|to taste)$", re.I),
    re.compile(r"\s+optional$", re.I),
    re.compile(r"\s+as needed$", re.I),
)
_OR_AND_SPLIT_RE = re.compile(r"\s+(?:or|and)\s+", re.I)
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")

# The shape services/recipes.py::generate_slug() always produces (lowercase
# alnum runs joined by single hyphens, no leading/trailing hyphen). Enforced
# before every Firestore call that takes a caller-supplied slug: the client
# library's document() re-joins collection + slug with "/" and re-splits on
# it, so a slug containing "/" would be read as a nested path — not a
# document id in this collection — rather than raising outright.
_SAFE_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class IngredientNotFound(Exception):
    pass


class AliasConflict(Exception):
    """Raised when a profile's name/aliases canonicalise to a key another
    profile already owns."""

    def __init__(self, key: str, existing_slug: str):
        self.key = key
        self.existing_slug = existing_slug
        super().__init__(f"{key!r} already maps to profile {existing_slug!r}")


def _singularize(word: str) -> str:
    if word.endswith("ies") and len(word) > 3:
        return word[:-3] + "y"
    if re.search(r"(?:ch|sh|ss|x|z)es$", word):
        return word[:-2]
    if word.endswith("oes"):
        return word[:-2]
    if word.endswith("s") and not word.endswith(("ss", "us")):
        return word[:-1]
    return word


def canon(phrase: str) -> str:
    """Lowercase, punctuation-to-space, collapsed whitespace, singularise the
    last word. Applied to both a recipe item's candidate keys and a
    profile's own name/aliases — what matters is that the two sides agree,
    not that the result reads naturally on its own."""
    text = clean_text(phrase, 300).lower()
    text = _NON_ALNUM_RE.sub(" ", text).strip()
    if not text:
        return ""
    words = text.split()
    words[-1] = _singularize(words[-1])
    return " ".join(words)


def _strip_to_head(item: str) -> str:
    """clean -> lowercase -> drop parentheticals -> keep text before the
    first comma -> strip a trailing purpose clause ("... to garnish", "...
    plus more", "... optional", "... as needed"). Shared first stage for
    both candidate_keys and primary_keys."""
    text = clean_text(item, 300).lower()
    text = _PAREN_RE.sub("", text)
    text = text.split(",", 1)[0].strip()
    for pattern in _PURPOSE_TAIL_RES:
        text = pattern.sub("", text).strip()
    return text


def _leading_word_drop_chain(phrase: str) -> list[str]:
    """[phrase, phrase minus its first word, minus its first two words, ...],
    stopping at the last single word — a one-word phrase is never dropped to
    nothing."""
    words = phrase.split()
    return [" ".join(words[i:]) for i in range(len(words))]


def _candidates_for_phrase(phrase: str) -> list[str]:
    """One already-split phrase → its own raw (pre-canon) candidate strings:
    the phrase itself, then progressively fewer leading words — except when
    the phrase ends in a bare count/unit noun ("garlic cloves"), where the
    unit is dropped outright rather than singularised, since "clove" alone
    is not a useful lookup key but "garlic" is."""
    if not phrase.split():
        return []
    reduced = _reduce_units(phrase)
    if reduced != phrase:
        return [phrase] + _leading_word_drop_chain(reduced)
    return _leading_word_drop_chain(phrase)


def _reduce_units(phrase: str) -> str:
    """Strip a trailing count/unit noun, if the phrase has one to spare —
    "garlic cloves" -> "garlic", but "garlic" (already one word) is left
    alone. Keeps primary_keys' grouping unit-insensitive: "garlic cloves" in
    one recipe and "garlic" in another are the same ingredient for coverage
    and for resolve()'s exact/fallback classification."""
    words = phrase.split()
    if len(words) > 1 and words[-1] in _COUNT_NOUNS:
        return " ".join(words[:-1])
    return phrase


def primary_keys(item: str) -> list[str]:
    """The head phrase, or — for an "X or Y" ingredient — each disjunct,
    with a trailing count/unit noun stripped. What coverage() groups an
    ingredient by, and what counts as an "exact" match in
    ProfileIndex.resolve (anything found only through a shorter candidate is
    a "fallback" match instead)."""
    text = _strip_to_head(item)
    if not text:
        return []
    parts = [p.strip() for p in _OR_AND_SPLIT_RE.split(text) if p.strip()]
    if len(parts) > 1:
        return [canon(_reduce_units(p)) for p in parts]
    return [canon(_reduce_units(text))]


def candidate_keys(item: str) -> list[str]:
    """Ordered, deduped canonical lookup keys for one raw recipe ingredient
    item string, most specific first. For an "X or Y" item the whole
    disjunction is candidate 0 (so a profile aliased to the exact phrase
    wins first), followed by each disjunct's own reductions."""
    text = _strip_to_head(item)
    if not text:
        return []
    parts = [p.strip() for p in _OR_AND_SPLIT_RE.split(text) if p.strip()]

    keys: list[str] = []
    seen: set[str] = set()

    def add(raw: str) -> None:
        key = canon(raw)
        if key and key not in seen:
            seen.add(key)
            keys.append(key)

    if len(parts) > 1:
        add(text)
        for part in parts:
            for raw in _candidates_for_phrase(part):
                add(raw)
    else:
        for raw in _candidates_for_phrase(text):
            add(raw)
    return keys


def recipe_items(doc: dict) -> list[str]:
    """Every ingredient item string in a recipe doc — top-level plus every
    component's — deduped case-insensitively, in the recipe's own order.
    Mirrors services/assistant.py's stores_block iteration."""
    items: list[str] = []
    seen: set[str] = set()
    all_ingredients = list(doc.get("ingredients") or []) + [
        ing
        for comp in (doc.get("components") or [])
        if isinstance(comp, dict)
        for ing in (comp.get("ingredients") or [])
    ]
    for ing in all_ingredients:
        name = (ing.get("item") or "").strip() if isinstance(ing, dict) else ""
        key = name.lower()
        if name and key not in seen:
            seen.add(key)
            items.append(name)
    return items


@dataclass(frozen=True)
class ProfileIndex:
    by_slug: dict[str, dict]
    by_key: dict[str, str]  # canonical key -> profile slug

    def resolve(self, item: str) -> tuple[str, str] | None:
        """(slug, via) for a raw recipe item string, or None. via is "exact"
        when the matching key is one of the item's own primary_keys (its
        head or, for a disjunction, one of its parts), "fallback" when the
        match only came from a shorter or unit-stripped candidate — e.g.
        "light soy sauce" matching a "soy sauce" profile."""
        primary = set(primary_keys(item))
        for key in candidate_keys(item):
            slug = self.by_key.get(key)
            if slug:
                return slug, "exact" if key in primary else "fallback"
        return None


def build_index(profiles: list[dict]) -> ProfileIndex:
    """Build the alias -> slug lookup. Raises AliasConflict if two different
    profiles' name/aliases canonicalise to the same key."""
    by_slug = {p["slug"]: p for p in profiles}
    by_key: dict[str, str] = {}
    for profile in profiles:
        keys = {canon(profile["name"])} | {canon(alias) for alias in profile.get("aliases", [])}
        for key in keys:
            if not key:
                continue
            if key in by_key and by_key[key] != profile["slug"]:
                raise AliasConflict(key, by_key[key])
            by_key[key] = profile["slug"]
    return ProfileIndex(by_slug=by_slug, by_key=by_key)


def coverage(profiles: list[dict], docs: list[dict]) -> list[dict]:
    """Every distinct ingredient across `docs` (published recipes), with
    which recipes use it and whether a profile covers it — for the admin
    "Ingredients" tab and the MCP list_ingredients tool.

    Grouped by primary_keys, not every candidate_keys reduction: "garlic
    cloves" in one recipe and "garlic" in another count as the same
    ingredient here, but "guanciale or pancetta" counts as guanciale AND
    pancetta separately, not as one combined row. Sorted by recipe count
    descending, so the ingredients worth writing a profile for come first.
    """
    index = build_index(profiles)
    rows: dict[str, dict] = {}
    for doc in docs:
        title = doc.get("title") or doc.get("slug") or ""
        for item in recipe_items(doc):
            keys = primary_keys(item)
            if not keys:
                continue
            resolved = index.resolve(item)
            for key in keys:
                row = rows.setdefault(key, {
                    "key": key,
                    "display": item.strip(),
                    "recipes": [],
                    "recipe_count": 0,
                    "covered": False,
                    "profile_slug": None,
                    "via": None,
                })
                if title not in row["recipes"]:
                    row["recipes"].append(title)
                    row["recipe_count"] += 1
                if resolved:
                    row["covered"] = True
                    row["profile_slug"], row["via"] = resolved
    return sorted(rows.values(), key=lambda row: (-row["recipe_count"], row["key"]))


def _require_safe_slug(slug: str) -> None:
    if not _SAFE_SLUG_RE.match(slug or ""):
        raise ValueError(f"invalid ingredient slug: {slug!r}")


def list_profiles(db) -> list[dict]:
    """Every ingredient profile in Firestore, as {**fields, "slug": doc id}."""
    return [{**(doc.to_dict() or {}), "slug": doc.id} for doc in db.collection(_COLLECTION).stream()]


def get_profile(db, slug: str) -> dict | None:
    _require_safe_slug(slug)
    doc = db.collection(_COLLECTION).document(slug).get()
    if not doc.exists:
        return None
    return {**(doc.to_dict() or {}), "slug": doc.id}


def upsert_profile(db, slug: str, body: dict, *, source: str) -> tuple[dict, bool]:
    """Validate `body`, write it to ingredients/{slug}, and clear the cache.

    `slug` is the intended document id (the caller computes it, typically
    via generate_slug(name)) — set() on a known id, so a retried call with
    the same slug and body converges rather than creating a duplicate.

    Raises AliasConflict if the candidate's name/aliases collide with a
    DIFFERENT existing profile's keys — checked before anything is written.
    """
    _require_safe_slug(slug)
    cleaned = {
        "name": clean_text(body.get("name"), 80),
        "aliases": [clean_text(alias, 60) for alias in (body.get("aliases") or [])],
        "what_it_is": clean_text(body.get("what_it_is"), 300),
        "role": clean_text(body.get("role"), 200),
        "substitutions": clean_text(body.get("substitutions"), 400),
        "buying": clean_text(body.get("buying"), 250),
        "storage": clean_text(body.get("storage"), 200),
        "mistakes": clean_text(body.get("mistakes"), 250),
        "allergens": clean_text(body.get("allergens"), 100),
    }
    validated = IngredientProfileIn.model_validate(cleaned)

    other_profiles = [p for p in list_profiles(db) if p["slug"] != slug]
    build_index(other_profiles + [{**validated.model_dump(), "slug": slug}])  # raises AliasConflict

    doc_ref = db.collection(_COLLECTION).document(slug)
    existing = doc_ref.get()
    created = not existing.exists
    now = datetime.now(timezone.utc)

    data = validated.model_dump()
    data["updated_at"] = now
    data["updated_via"] = source
    data["created_at"] = now if created else (existing.to_dict() or {}).get("created_at", now)

    doc_ref.set(data)
    cache.clear()
    return {**data, "slug": slug}, created


def delete_profile(db, slug: str) -> bool:
    """True if a profile existed and was deleted; False if there was none."""
    _require_safe_slug(slug)
    doc_ref = db.collection(_COLLECTION).document(slug)
    if not doc_ref.get().exists:
        return False
    doc_ref.delete()
    cache.clear()
    return True
