"""Instagram publishing, and the social-kit drafting tools.

Everything Claude needs to draft posts consistently. Brand voice and hashtag
tiers live on Firestore pages/social (editable from the admin Pages UI — see
src/pages/AdminPageEditPage.tsx); the defaults below apply until the owner
writes their own. No server-side LLM call anywhere in this flow: the MCP
client is the model that drafts.
"""

import logging

from ...config import settings
from ...firestore import get_db
from ...services import instagram
from ...services import social
from ..errors import tool_errors
from .recipes import _lookup_recipe

logger = logging.getLogger(__name__)


def _hashtag(text: str) -> str:
    """Turn a category/label into a bare hashtag word (alnum, lowercase)."""
    return "".join(c for c in text.lower() if c.isalnum())


def _build_recipe_caption(recipe) -> str:
    """Compose a default caption from a recipe: title, blurb, link, hashtags."""
    link = f"{settings.frontend_url.rstrip('/')}/recipes/{recipe.slug}/"
    tags = ["madeforseconds"]
    for raw in [*recipe.categories, *recipe.labels]:
        tag = _hashtag(raw)
        if tag and tag not in tags:
            tags.append(tag)
        if len(tags) >= 8:
            break
    parts = [recipe.title]
    if recipe.description:
        parts.append(recipe.description)
    parts.append(f"Full recipe: {link}")
    parts.append(" ".join(f"#{t}" for t in tags))
    return "\n\n".join(parts)


@tool_errors
def publish_instagram_post(image_url: str, caption: str = "") -> dict:
    """Publish a single image to the linked Instagram account.

    image_url must be a public https JPEG (recipe images in the site's GCS
    bucket work directly). caption <= 2200 chars and <= 30 hashtags. Returns
    the new media id and permalink. Subject to Instagram's 25-posts/24h limit;
    PNG/WebP images may be rejected by Instagram — prefer JPEG.
    """
    result = instagram.publish_image(image_url, caption)
    logger.info("MCP publish_instagram_post: media=%s", result.get("id"))
    return {**result, "message": "Posted to Instagram."}


@tool_errors
def publish_recipe_to_instagram(
    slug: str = "", recipe_id: str = "", caption: str | None = None
) -> dict:
    """Publish a recipe's photo to Instagram, building a caption if omitted.

    Looks up the recipe by slug or id, requires it to have an image, and posts
    it. When caption is None a caption is built from the recipe's title,
    description, link, and hashtags. Pass an explicit caption to override.
    """
    recipe = _lookup_recipe(recipe_id=recipe_id, slug=slug)
    if not recipe.image_url:
        raise ValueError("recipe has no image; attach one first (request_image_upload)")
    text = caption if caption is not None else _build_recipe_caption(recipe)
    result = instagram.publish_image(recipe.image_url, text)
    logger.info("MCP publish_recipe_to_instagram: recipe=%s media=%s", recipe.slug, result.get("id"))
    return {**result, "slug": recipe.slug, "title": recipe.title, "message": "Posted to Instagram."}


_SOCIAL_KIT_DEFAULTS = {
    "tone": (
        "Authentic, approachable, personal, culturally respectful. Teach something "
        "in every post; sound like a friend who cooks, not a brand."
    ),
    "do": (
        "Lead with the dish and the moment; name the cuisine and the technique; "
        "give one concrete tip; end by inviting a question."
    ),
    "dont": (
        "No clickbait, no 'secret hack', no all-caps, at most one emoji per line, "
        "no health or nutrition claims."
    ),
    "cta": "Full recipe on madeforseconds.com — link in bio.",
    "hashtags_brand": "madeforseconds, homecooking",
    "hashtags_cuisine": "asianfood, malaysianfood, singaporefood, vietnamesefood, chinesefood, thaifood",
    "hashtags_niche": "laksa, hainanesechickenrice, bakkutteh, rendang, satay",
}

_SOCIAL_PLATFORMS = {
    "instagram": {
        "max_caption_chars": instagram.MAX_CAPTION_CHARS,
        "max_hashtags": instagram.MAX_HASHTAGS,
        "posts_per_day": 25,
        "image": "public https JPEG — the recipe's GCS image works as-is",
        "publish_with": "publish_recipe_to_instagram(slug, caption=...) or publish_instagram_post(image_url, caption)",
    },
    "tiktok": {
        "max_caption_chars": 2200,
        "note": (
            "Draft only. TikTok's Content Posting API needs an audited app and photo/video "
            "served from a verified domain (backlogged) — hand the caption and shot list to "
            "the operator to post manually."
        ),
    },
}


def _social_settings(db) -> dict:
    doc = db.collection("pages").document("social").get()
    data = (doc.to_dict() or {}) if getattr(doc, "exists", False) else {}
    overrides = {k: v for k, v in data.items() if isinstance(v, str) and v.strip()}
    return {**_SOCIAL_KIT_DEFAULTS, **overrides}


def _tag_list(csv: str) -> list[str]:
    tags: list[str] = []
    for raw in csv.split(","):
        tag = _hashtag(raw.strip().lstrip("#"))
        if tag and tag not in tags:
            tags.append(tag)
    return tags


@tool_errors
def get_social_kit(recipe_id: str = "", slug: str = "") -> dict:
    """Everything needed to draft social posts for a recipe.

    Returns {recipe, brand_voice, hashtags, platforms, workflow}: a recipe
    summary with its public URL, image, key ingredients and "Chef's Secrets"
    titles; the site's brand voice (tone / do / don't / call to action);
    hashtag tiers (brand — always; recipe — from its categories and labels;
    cuisine and niche — pick a few); per-platform limits; and the steps to
    follow. Draft, show the operator, and only publish after approval.
    """
    recipe = _lookup_recipe(recipe_id=recipe_id, slug=slug)
    voice = _social_settings(get_db())

    ingredients = recipe.ingredients or [ing for comp in (recipe.components or []) for ing in comp.ingredients]
    key_ingredients = [ing.item for ing in ingredients if ing.item][:8]
    recipe_tags: list[str] = []
    for raw in [*recipe.categories, *recipe.labels]:
        tag = _hashtag(raw)
        if tag and tag not in recipe_tags:
            recipe_tags.append(tag)

    return {
        "recipe": {
            "id": recipe.id,
            "slug": recipe.slug,
            "title": recipe.title,
            "url": f"{settings.frontend_url.rstrip('/')}/recipes/{recipe.slug}/",
            "description": recipe.description,
            "about": (recipe.about or "")[:600] or None,
            "image_url": recipe.image_url,
            "categories": recipe.categories,
            "labels": recipe.labels,
            "servings": recipe.servings,
            "prep_time_minutes": recipe.prep_time_minutes,
            "cook_time_minutes": recipe.cook_time_minutes,
            "difficulty": recipe.difficulty,
            "key_ingredients": key_ingredients,
            "secret_titles": [s.title for s in recipe.secrets],
        },
        "brand_voice": {k: voice[k] for k in ("tone", "do", "dont", "cta")},
        "hashtags": {
            "brand": _tag_list(voice["hashtags_brand"]),
            "recipe": recipe_tags,
            "cuisine": _tag_list(voice["hashtags_cuisine"]),
            "niche": _tag_list(voice["hashtags_niche"]),
        },
        "platforms": _SOCIAL_PLATFORMS,
        "workflow": [
            "Draft an Instagram caption: a hook line, two or three lines on the dish or the "
            "technique, one concrete tip, then the call to action; hashtags last — brand + recipe "
            "+ a few cuisine/niche, at most 30 in total.",
            "Draft a TikTok caption (<= 2200 chars) plus a 15-second shot list of five or six shots.",
            "Show both drafts to the operator and wait for explicit approval — never post unasked.",
            "After approval: publish_recipe_to_instagram(slug, caption=<approved caption>) — the "
            "recipe must have an image. TikTok is draft-only: hand it over for manual posting.",
            "Report the Instagram permalink back.",
        ],
    }


@tool_errors
def social_status() -> dict:
    """Per-platform social publishing health: configured?, last successful
    refresh, token expiry, and the last error — as recorded by the
    twice-monthly social-token-refresh job. Use it to tell the operator when
    a token has lapsed and a re-auth is needed."""
    return {
        "platforms": social.status(get_db()),
        "refresh_schedule": "04:00 UTC on the 1st and the 15th (Cloud Scheduler job social-token-refresh)",
    }


TOOLS = (publish_instagram_post, publish_recipe_to_instagram, get_social_kit, social_status)


def register(mcp) -> None:
    """Register this module's tools on the server. Explicit, so the tool
    surface is this tuple, nothing else."""
    for tool in TOOLS:
        mcp.tool()(tool)
