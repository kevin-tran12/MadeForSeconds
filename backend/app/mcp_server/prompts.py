"""MCP prompts: the three workflows worth starting from a slash command.

A prompt is a *starting point the operator picks*, not something the model
invokes on its own. Each one composes data the tools already expose into the
brief that has, until now, lived in ``server.py``'s INSTRUCTIONS and in the
operator's head.

The approval rule is repeated inside every prompt that can lead to a public
or persisted write, rather than being stated once in INSTRUCTIONS. A prompt
may be the first thing in a fresh conversation, so it cannot assume the
model has read anything else.

Like ``resources.py``, this module must not import the ``mcp`` SDK (see
``test_mcp_transport.py``'s AST check) — it reaches it only through the
``mcp`` object ``register`` receives.
"""

from .tools.ingredients import list_ingredients
from .tools.recipes import _lookup_recipe
from .tools.social import build_social_kit

_APPROVAL = (
    "Show the drafts to the operator and wait for explicit approval. "
    "Never publish, post, or save anything unasked."
)


def draft_social_post(slug: str) -> str:
    """Draft Instagram and TikTok posts for a recipe, in the site's voice."""
    kit = build_social_kit(slug=slug)
    recipe = kit["recipe"]
    voice = kit["brand_voice"]
    tags = kit["hashtags"]
    limits = kit["platforms"]["instagram"]

    lines = [
        f"Draft social posts for \"{recipe['title']}\" ({recipe['url']}).",
        "",
        "THE DISH",
        f"- {recipe['description'] or 'No description written yet.'}",
        f"- Key ingredients: {', '.join(recipe['key_ingredients']) or 'none listed'}",
        f"- Chef's Secrets on the page: {', '.join(recipe['secret_titles']) or 'none'}",
        f"- Image: {recipe['image_url'] or 'MISSING — publish_recipe_to_instagram will fail without one'}",
        "",
        "VOICE",
        f"- Tone: {voice['tone']}",
        f"- Do: {voice['do']}",
        f"- Don't: {voice['dont']}",
        f"- Call to action: {voice['cta']}",
        "",
        "HASHTAGS",
        f"- Always: {', '.join(tags['brand']) or '(none)'}",
        f"- From this recipe: {', '.join(tags['recipe']) or '(none)'}",
        f"- Pick a few: {', '.join(tags['cuisine'] + tags['niche']) or '(none)'}",
        f"- At most {limits['max_hashtags']} in total; caption at most {limits['max_caption_chars']} characters.",
        "",
        "WHAT TO PRODUCE",
    ]
    lines += [f"{i}. {step}" for i, step in enumerate(kit["workflow"], start=1)]
    lines += ["", _APPROVAL]
    return "\n".join(lines)


def review_before_publish(recipe_id: str) -> str:
    """Check a draft recipe for the gaps that block or weaken publishing."""
    recipe = _lookup_recipe(recipe_id=recipe_id)

    has_components = bool(recipe.components)
    component_items = [ing for comp in (recipe.components or []) for ing in comp.ingredients]
    component_steps = [step for comp in (recipe.components or []) for step in comp.instructions]

    blocking: list[str] = []
    if not (recipe.ingredients or component_items):
        blocking.append("no ingredients (publish_recipe will refuse)")
    if not (recipe.instructions or component_steps):
        blocking.append("no instructions (publish_recipe will refuse)")

    warnings: list[str] = []
    if not recipe.image_url:
        warnings.append("no image — the card and any Instagram post need one")
    if not recipe.description:
        warnings.append("no description — this is the blurb on the card and in search results")
    if not recipe.categories:
        warnings.append("no categories — the recipe will not appear under any filter")
    if not recipe.secrets:
        warnings.append("no Chef's Secrets — these are what the Sous Chef quotes to readers")
    if not recipe.sous_chef_notes:
        warnings.append("no sous_chef_notes — private guidance the Sous Chef uses but never shows")

    lines = [
        f"Review \"{recipe.title}\" ({recipe.id}) before publishing.",
        f"Currently {'published' if recipe.published else 'a draft'}"
        f"{'; built from components' if has_components else ''}.",
        "",
        "BLOCKING",
    ]
    lines += [f"- {item}" for item in blocking] or ["- none"]
    lines += ["", "WORTH FIXING FIRST"]
    lines += [f"- {item}" for item in warnings] or ["- none"]
    lines += [
        "",
        "Read the recipe, judge whether the method is actually followable by a home cook, "
        "and list anything vague, out of order, or missing a temperature or time.",
        "Fix what the operator approves with update_recipe, then publish_recipe when they say so.",
        _APPROVAL,
    ]
    return "\n".join(lines)


def draft_ingredient_profiles(limit: int = 10) -> str:
    """Draft profiles for the most-used ingredients that have none yet."""
    rows = list_ingredients(coverage="missing", limit=limit)
    # list_ingredients wears @mcp_tool, so a failure comes back as an error
    # dict rather than raising. Say so: silently rendering "no gaps" would
    # tell the operator the catalogue is fully covered when the read failed.
    if "error" in rows:
        detail = rows.get("message") or rows["error"]
        return (
            f"Could not read ingredient coverage: {detail}\n"
            'Call list_ingredients(coverage="missing") directly to see the failure.'
        )
    uncovered = rows.get("ingredients", [])

    lines = [
        "Draft ingredient profiles for the Sous Chef's knowledge base.",
        "",
        f"Covered so far: {rows.get('covered_count', 0)} of {rows.get('total_count', 0)} "
        "distinct ingredients across the published catalogue.",
        "",
        "MOST-USED GAPS (recipe count in brackets)",
    ]
    lines += [
        f"- {row['display']} [{row['recipe_count']}] — used in: {', '.join(row['recipes'][:4])}"
        for row in uncovered
    ] or ["- none: every ingredient on the site already has a profile."]
    lines += [
        "",
        "FOR EACH ONE, ABOUT 150 WORDS IN THE OWNER'S VOICE",
        "- what it is, plainly",
        "- its role in a dish: fat, acid, umami, aromatic, or texture",
        "- substitutions: what works, what does not, and what changes if you swap",
        "- buying: what to look for, and where",
        "- storage",
        "- the mistakes readers actually make",
        "- allergens, if any",
        "",
        "Aliases must include the forms recipes really use (\"garlic cloves\", \"green onions\"), "
        "or the profile will not match the ingredient line it belongs to.",
        "Keep the prose fields under 1,000 characters in total per profile, or the save is rejected.",
        "",
        f"{_APPROVAL} Save approved profiles one at a time with upsert_ingredient, which is keyed "
        "by slug and safe to retry.",
    ]
    return "\n".join(lines)


PROMPTS = (
    (draft_social_post, "Draft social posts for a recipe, in the site's voice."),
    (review_before_publish, "Check a draft recipe for what blocks or weakens publishing."),
    (draft_ingredient_profiles, "Draft profiles for the most-used ingredients that lack one."),
)


def register(mcp) -> None:
    """Register this module's prompts. Explicit, so the prompt surface is
    exactly PROMPTS and nothing registers by import."""
    for fn, description in PROMPTS:
        mcp.prompt(description=description)(fn)
