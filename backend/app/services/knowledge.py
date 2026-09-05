"""Cross-recipe grounding for the Sous Chef: owner-authored ingredient
profiles, plus every published recipe's Chef's Secrets, ``about``, and
``sous_chef_notes`` made retrievable from any page — not just the recipe
on screen.

Keyed + lexical, not vectors. For the recipe on screen, its own
ingredients resolve deterministically via services.ingredients.ProfileIndex
and ride inside the cached ``<recipe>`` block, exactly like ``<stores>``
(see ``KnowledgeBase.profiles_for`` and ``assistant._recipe_block``). For a
question naming an ingredient that isn't on the page — or for a spoke with
no single recipe in front of it — ``KnowledgeBase.retrieve`` scores this
module's corpus by simple lexical overlap and the caller renders the top
few into the last, uncached user turn as ``<knowledge>``. No embeddings, no
new infrastructure: Firestore's ``find_nearest`` vector search is the
documented upgrade path once the corpus passes roughly a thousand entries,
which is not this catalogue's size for a long while yet.

Both blocks are owner-authored content — profiles approved by the owner
through the MCP tools or the admin tab, secrets/notes/about the owner wrote
on the recipe itself — so they are trusted the same way ``<recipe>`` is;
see CORE_RULES in services/assistant.py.
"""

import logging
import re
from dataclasses import dataclass

from ..cache import cache
from ..models import PROFILE_PROSE_FIELDS
from . import ingredients
from .recipes import get_all_published_docs

logger = logging.getLogger(__name__)

KNOWLEDGE_CACHE_KEY = "assistant:knowledge"  # versioned: any recipe or profile write rebuilds it
CATALOGUE_LIMIT = 200

# Per recipe block: prod tops out around 37 ingredient lines, 19 average.
MAX_INGREDIENT_PROFILES = 24
MAX_INGREDIENTS_BLOCK_CHARS = 16_000  # ≈4k tokens — the token-cost knob

MAX_CHUNK_CHARS = 600
_MIN_PARAGRAPH_CHARS = 40
MAX_KNOWLEDGE_HITS = 3
MAX_KNOWLEDGE_BLOCK_CHARS = 2_400
MIN_SCORE = 2

_KIND_RANK = {"profile": 0, "secret": 1, "notes": 2, "about": 3}

_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n+")
_STOPWORDS = frozenset({
    "the", "a", "an", "and", "or", "of", "in", "on", "for", "to", "with", "is", "are",
    "this", "that", "it", "its", "be", "as", "by", "from", "at", "into", "your", "you",
    "i", "can", "what", "how", "do", "does", "did", "not", "but", "if", "so", "than",
})


def _canon_words(text: str) -> str:
    """Every word of `text`, lowercased and individually singularised via
    ingredients.canon (a single word is a valid one-word "phrase" to it) —
    so a phrase match against a profile's name still hits a reader's plural
    ("pork jowls" vs a "pork jowl" profile)."""
    words = re.findall(r"[a-z0-9]+", text.lower())
    return " ".join(ingredients.canon(w) for w in words if w)


def _terms(text: str) -> set[str]:
    return {w for w in _canon_words(text).split() if len(w) > 2 and w not in _STOPWORDS}


def _paragraphs(text: str) -> list[str]:
    if not text:
        return []
    return [p.strip() for p in _PARAGRAPH_SPLIT_RE.split(text.strip()) if len(p.strip()) >= _MIN_PARAGRAPH_CHARS]


def _chunks_for(doc: dict) -> list[dict]:
    """One chunk per Chef's Secret, plus one per paragraph of ``about`` and
    of ``sous_chef_notes`` — the corpus that makes source (b) (the owner's
    existing writing) retrievable with zero new authoring."""
    slug, title = doc.get("slug", ""), doc.get("title", "")
    chunks: list[dict] = []
    for secret in doc.get("secrets") or []:
        if not isinstance(secret, dict):
            continue
        heading = (secret.get("title") or "").strip()
        body = (secret.get("body") or "").strip()
        if heading and body:
            chunks.append({
                "recipe_slug": slug, "recipe_title": title, "kind": "secret",
                "heading": heading, "body": body[:MAX_CHUNK_CHARS],
            })
    for para in _paragraphs(doc.get("about") or ""):
        chunks.append({"recipe_slug": slug, "recipe_title": title, "kind": "about", "heading": "", "body": para[:MAX_CHUNK_CHARS]})
    for para in _paragraphs(doc.get("sous_chef_notes") or ""):
        chunks.append({"recipe_slug": slug, "recipe_title": title, "kind": "notes", "heading": "", "body": para[:MAX_CHUNK_CHARS]})
    return chunks


def _json_safe_profile(profile: dict) -> dict:
    safe = dict(profile)
    for field in ("created_at", "updated_at"):
        value = safe.get(field)
        if hasattr(value, "isoformat"):
            safe[field] = value.isoformat()
    return safe


def _profile_body(profile: dict) -> str:
    segments = [(profile.get("what_it_is") or "").strip()]
    for label, field in (
        ("Role", "role"), ("Swaps", "substitutions"), ("Buy", "buying"),
        ("Store", "storage"), ("Mistakes", "mistakes"), ("Allergens", "allergens"),
    ):
        value = (profile.get(field) or "").strip()
        if value:
            segments.append(f"{label}: {value}")
    return " ".join(s for s in segments if s)


def render_profile(profile: dict) -> str:
    name = profile.get("name", "")
    aliases = profile.get("aliases") or []
    header = f"- {name} (aka: {', '.join(aliases)}):" if aliases else f"- {name}:"
    return f"{header} {_profile_body(profile)}"


def ingredients_block(profiles: list[dict]) -> str:
    """Byte-stable rendering (relies on `profiles` already being in a
    deterministic order) of the profiles that ride inside the cached
    <ingredients> block — see KnowledgeBase.profiles_for."""
    lines: list[str] = []
    total = 0
    for profile in profiles:
        line = render_profile(profile)
        if total + len(line) > MAX_INGREDIENTS_BLOCK_CHARS:
            break
        lines.append(line)
        total += len(line) + 1
    return "\n".join(lines)


def _render_hit(hit: dict) -> str:
    if hit["kind"] == "profile":
        profile = hit["profile"]
        return f"- {profile.get('name', '')} (ingredient note): {_profile_body(profile)}"
    chunk = hit["chunk"]
    title = chunk.get("recipe_title", "")
    if hit["kind"] == "secret":
        return f"- From \"{title}\", Chef's Secret \"{chunk.get('heading', '')}\": {chunk.get('body', '')}"
    if hit["kind"] == "notes":
        return f"- From \"{title}\", the chef's notes: {chunk.get('body', '')}"
    return f"- From \"{title}\": {chunk.get('body', '')}"  # about


def knowledge_block(hits: list[dict]) -> str:
    lines: list[str] = []
    total = 0
    for hit in hits:
        line = _render_hit(hit)
        if total + len(line) > MAX_KNOWLEDGE_BLOCK_CHARS:
            break
        lines.append(line)
        total += len(line) + 1
    return "\n".join(lines)


def _profile_score(profile: dict, canon_question: str, query_terms: set[str]) -> int:
    """A whole-word phrase hit on the profile's name or an alias outranks
    everything ("pork jowl" must beat a mere overlap on "pork"). Otherwise,
    term overlap: a hit on the name/alias words ("strong") counts triple a
    hit in the prose body."""
    names = [profile.get("name", ""), *profile.get("aliases", [])]
    best_phrase = 0
    for name in names:
        key = _canon_words(name)
        if key and re.search(rf"(?<!\w){re.escape(key)}(?!\w)", canon_question):
            best_phrase = max(best_phrase, 10 + len(key.split()))
    if best_phrase:
        return best_phrase

    strong_terms = {t for name in names for t in _terms(name)}
    body_terms = _terms(" ".join(profile.get(field, "") for field in PROFILE_PROSE_FIELDS))
    return 3 * len(query_terms & strong_terms) + len(query_terms & body_terms)


def _chunk_score(chunk: dict, query_terms: set[str]) -> int:
    strong_terms = _terms(chunk.get("heading", ""))
    body_terms = _terms(chunk.get("body", ""))
    return 3 * len(query_terms & strong_terms) + len(query_terms & body_terms)


@dataclass(frozen=True)
class KnowledgeBase:
    profiles: tuple[dict, ...]
    chunks: tuple[dict, ...]
    index: "ingredients.ProfileIndex"

    def profiles_for(self, doc: dict) -> list[dict]:
        """Profiles for this recipe's own ingredients, in the recipe's own
        order, deduped by slug, capped at MAX_INGREDIENT_PROFILES — what
        rides inside the cached <ingredients> block."""
        seen: set[str] = set()
        out: list[dict] = []
        for item in ingredients.recipe_items(doc):
            resolved = self.index.resolve(item)
            if not resolved:
                continue
            slug = resolved[0]
            if slug in seen:
                continue
            seen.add(slug)
            profile = self.index.by_slug.get(slug)
            if profile:
                out.append(profile)
                if len(out) >= MAX_INGREDIENT_PROFILES:
                    break
        return out

    def _candidate_hits(self, canon_q: str, terms: set[str], *,
                         exclude_profiles: frozenset, exclude_recipe: str | None) -> list[tuple]:
        hits: list[tuple] = []
        for profile in self.profiles:
            slug = profile.get("slug", "")
            if slug in exclude_profiles:
                continue
            score = _profile_score(profile, canon_q, terms)
            if score >= MIN_SCORE:
                hits.append((score, _KIND_RANK["profile"], slug, {"kind": "profile", "profile": profile}))
        for chunk in self.chunks:
            if chunk.get("recipe_slug") == exclude_recipe:
                continue
            score = _chunk_score(chunk, terms)
            if score >= MIN_SCORE:
                key = f"{chunk.get('recipe_slug')}|{chunk.get('kind')}|{chunk.get('heading', '')}"
                hits.append((score, _KIND_RANK[chunk["kind"]], key, {"kind": chunk["kind"], "chunk": chunk}))
        return hits

    def retrieve(self, question: str, previous: str | None = None, *,
                 exclude_profiles: frozenset = frozenset(), exclude_recipe: str | None = None) -> list[dict]:
        """Top MAX_KNOWLEDGE_HITS profiles/chunks for `question`, excluding
        anything already shown for the current recipe (`exclude_profiles`,
        `exclude_recipe`). Falls back to also scoring `previous` (the prior
        user turn) when the question alone doesn't reach MAX_KNOWLEDGE_HITS —
        a bare follow-up ("and for 12 people?") still finds what the last
        turn was about."""
        hits = self._candidate_hits(
            _canon_words(question), _terms(question),
            exclude_profiles=exclude_profiles, exclude_recipe=exclude_recipe,
        )
        if len(hits) < MAX_KNOWLEDGE_HITS and previous:
            seen = {h[2] for h in hits}
            more = self._candidate_hits(
                _canon_words(previous), _terms(previous),
                exclude_profiles=exclude_profiles, exclude_recipe=exclude_recipe,
            )
            hits += [h for h in more if h[2] not in seen]
        hits.sort(key=lambda h: (-h[0], h[1], h[2]))
        return [h[3] for h in hits[:MAX_KNOWLEDGE_HITS]]

    def to_payload(self) -> dict:
        return {"profiles": list(self.profiles), "chunks": list(self.chunks)}

    @classmethod
    def from_payload(cls, payload: dict) -> "KnowledgeBase":
        profiles = tuple(payload.get("profiles") or [])
        chunks = tuple(payload.get("chunks") or [])
        return cls(profiles=profiles, chunks=chunks, index=ingredients.build_index(list(profiles)))


EMPTY = KnowledgeBase(profiles=(), chunks=(), index=ingredients.ProfileIndex(by_slug={}, by_key={}))


def build_knowledge_base(db) -> KnowledgeBase:
    docs = get_all_published_docs(db, limit=CATALOGUE_LIMIT)
    profiles = [_json_safe_profile(p) for p in ingredients.list_profiles(db)]
    chunks = tuple(chunk for doc in docs if isinstance(doc, dict) for chunk in _chunks_for(doc))
    index = ingredients.build_index(profiles)
    return KnowledgeBase(profiles=tuple(profiles), chunks=chunks, index=index)


def get_knowledge_base(db) -> KnowledgeBase:
    """Cached under the versioned key; any recipe or profile write clears
    it via cache.clear(), same as get_published_doc/get_catalogue_index.

    Never raises: a malformed profile, a transient Firestore error, or a
    stale/corrupted cache payload all fall back to EMPTY rather than
    breaking an answer that doesn't even need the knowledge base.
    """
    try:
        cached = cache.get(KNOWLEDGE_CACHE_KEY)
        if isinstance(cached, dict):
            return KnowledgeBase.from_payload(cached)
        kb = build_knowledge_base(db)
        cache.set(KNOWLEDGE_CACHE_KEY, kb.to_payload())
        return kb
    except Exception:
        logger.warning("knowledge base unavailable (non-fatal): falling back to empty", exc_info=True)
        return EMPTY
