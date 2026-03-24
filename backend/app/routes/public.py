import re
from collections import defaultdict
from datetime import datetime, timezone
from email.utils import formatdate

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from google.cloud.firestore_v1.base_query import FieldFilter

from ..cache import cache
from ..firestore import get_db
from ..models import CategoryGroup, GroupedRecipes, PaginatedRecipes, Recipe

router = APIRouter(prefix="/api")

SITE_URL = "https://madeforseconds.pages.dev"


def _doc_to_recipe(doc) -> Recipe:
    data = doc.to_dict()
    data["id"] = doc.id
    # Migrate legacy nutrition dict {label: value} → list[{label, value, unit}]
    if isinstance(data.get("nutrition"), dict):
        data["nutrition"] = [
            {"label": k, "value": v, "unit": ""} for k, v in data["nutrition"].items()
        ]
    # Strip any leftover premium_content from Firestore docs
    data.pop("premium_content", None)
    data.pop("has_premium_content", None)
    return Recipe(**data)


@router.get("/recipes", response_model=PaginatedRecipes)
async def list_recipes(
    search: str | None = None,
    category: str | None = None,
    label: str | None = None,
    search_by: str = "all",
    limit: int = Query(default=12, ge=1, le=50),
    cursor: str | None = None,
):
    cache_key = f"recipes:{search or ''}:{category or ''}:{label or ''}:{search_by}:{limit}:{cursor or ''}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    db = get_db()
    query = db.collection("recipes").where(filter=FieldFilter("published", "==", True))

    if category:
        query = query.where(filter=FieldFilter("categories", "array_contains", category))

    if label:
        query = query.where(filter=FieldFilter("labels", "array_contains", label))

    query = query.order_by("created_at", direction="DESCENDING")

    # Apply cursor for pagination
    if cursor:
        cursor_dt = datetime.fromisoformat(cursor).replace(tzinfo=timezone.utc)
        query = query.start_after({"created_at": cursor_dt})

    if search:
        # When searching, fetch a larger batch since we filter in Python
        fetch_limit = min(limit * 5, 200)
    else:
        fetch_limit = limit + 1  # +1 to detect if there are more pages

    query = query.limit(fetch_limit)
    docs = list(query.stream())
    recipes = [_doc_to_recipe(doc) for doc in docs]

    # Firestore doesn't support ILIKE, so filter in Python.
    if search:
        pattern = re.compile(re.escape(search), re.IGNORECASE)

        def matches(r) -> bool:
            if search_by in ("all", "name"):
                if pattern.search(r.title) or pattern.search(r.description):
                    return True
            if search_by in ("all", "ingredient"):
                if any(pattern.search(ing.item) for ing in r.ingredients):
                    return True
            if search_by in ("all", "label"):
                if any(pattern.search(lbl) for lbl in r.labels):
                    return True
            return False

        filtered = [r for r in recipes if matches(r)]
        has_more = len(recipes) == fetch_limit or len(filtered) > limit
        recipes = filtered[:limit]
    else:
        has_more = len(recipes) > limit
        recipes = recipes[:limit]

    next_cursor = recipes[-1].created_at.isoformat() if recipes and has_more else None
    result = PaginatedRecipes(recipes=recipes, next_cursor=next_cursor)

    # Skip caching only when the unfiltered list is empty — that indicates
    # Firestore wasn't ready at startup, not a legitimate "no results" case.
    if recipes or search or category or label:
        cache.set(cache_key, result)
    return result


# NOTE: must remain above /recipes/{slug} — otherwise "grouped" is caught as a slug value
@router.get("/recipes/grouped", response_model=GroupedRecipes)
async def list_recipes_grouped():
    cached = cache.get("recipes:grouped")
    if cached is not None:
        return cached

    db = get_db()
    query = (
        db.collection("recipes")
        .where(filter=FieldFilter("published", "==", True))
        .order_by("created_at", direction="DESCENDING")
        .limit(50)
    )
    docs = query.stream()
    all_recipes = [_doc_to_recipe(doc) for doc in docs]

    # Recently added — newest 6
    recent = all_recipes[:6]

    # Group by category
    by_category: dict[str, list[Recipe]] = defaultdict(list)
    for recipe in all_recipes:
        for cat in recipe.categories:
            if len(by_category[cat]) < 8:
                by_category[cat].append(recipe)

    groups = [
        CategoryGroup(category=cat, recipes=recipes)
        for cat, recipes in sorted(by_category.items())
    ]

    result = GroupedRecipes(recent=recent, groups=groups)

    if all_recipes:
        cache.set("recipes:grouped", result)
    return result


@router.get("/recipes/{slug}", response_model=Recipe)
async def get_recipe(slug: str):
    cache_key = f"recipe:{slug}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    db = get_db()
    docs = (
        db.collection("recipes")
        .where(filter=FieldFilter("slug", "==", slug))
        .where(filter=FieldFilter("published", "==", True))
        .limit(1)
        .stream()
    )
    doc = next(docs, None)
    if doc is None:
        raise HTTPException(status_code=404, detail="Recipe not found")
    recipe = _doc_to_recipe(doc)
    cache.set(cache_key, recipe)
    return recipe


@router.get("/categories", response_model=list[str])
async def list_categories():
    cached = cache.get("categories")
    if cached is not None:
        return cached

    db = get_db()
    doc = db.collection("config").document("categories").get()
    result = sorted(doc.to_dict().get("list", [])) if doc.exists else []
    cache.set("categories", result)
    return result


@router.get("/pages/{page_id}")
async def get_page_content(page_id: str):
    cache_key = f"page:{page_id}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    db = get_db()
    doc = db.collection("pages").document(page_id).get()
    result = doc.to_dict() if doc.exists else {}
    cache.set(cache_key, result)
    return result


@router.get("/sitemap.xml")
async def sitemap():
    db = get_db()
    docs = (
        db.collection("recipes")
        .where(filter=FieldFilter("published", "==", True))
        .order_by("created_at", direction="DESCENDING")
        .limit(200)
        .select(["slug", "updated_at"])
        .stream()
    )

    static_urls = [
        f"<url><loc>{SITE_URL}/</loc><changefreq>weekly</changefreq><priority>1.0</priority></url>",
        f"<url><loc>{SITE_URL}/recipes</loc><changefreq>daily</changefreq><priority>0.9</priority></url>",
        f"<url><loc>{SITE_URL}/about</loc><changefreq>monthly</changefreq><priority>0.5</priority></url>",
    ]

    recipe_urls = []
    for doc in docs:
        d = doc.to_dict()
        slug = d.get("slug", "")
        updated = d.get("updated_at")
        lastmod = updated.strftime("%Y-%m-%d") if updated else ""
        url = f"<url><loc>{SITE_URL}/recipes/{slug}</loc>"
        if lastmod:
            url += f"<lastmod>{lastmod}</lastmod>"
        url += "<changefreq>monthly</changefreq><priority>0.8</priority></url>"
        recipe_urls.append(url)

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        + "".join(static_urls + recipe_urls)
        + "</urlset>"
    )
    return Response(content=xml, media_type="application/xml")


@router.get("/feed.xml")
async def rss_feed():
    db = get_db()
    docs = (
        db.collection("recipes")
        .where(filter=FieldFilter("published", "==", True))
        .order_by("created_at", direction="DESCENDING")
        .limit(20)
        .stream()
    )

    recipes = [_doc_to_recipe(doc) for doc in docs]

    def rss_date(dt) -> str:
        return formatdate(dt.timestamp(), usegmt=True)

    def xml_escape(s: str) -> str:
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("'", "&apos;").replace('"', "&quot;")

    items = []
    for r in recipes:
        url = f"{SITE_URL}/recipes/{r.slug}"
        desc = xml_escape(r.description)
        title = xml_escape(r.title)
        item = (
            f"<item>"
            f"<title>{title}</title>"
            f"<link>{url}</link>"
            f"<guid isPermaLink='true'>{url}</guid>"
            f"<description>{desc}</description>"
            f"<pubDate>{rss_date(r.created_at)}</pubDate>"
            f"</item>"
        )
        if r.image_url:
            item = item.replace("</item>", f"<enclosure url='{xml_escape(r.image_url)}' type='image/jpeg'/></item>")
        items.append(item)

    pub_date = rss_date(recipes[0].created_at) if recipes else formatdate(usegmt=True)

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">'
        "<channel>"
        "<title>MadeForSeconds</title>"
        f"<link>{SITE_URL}</link>"
        "<description>High-effort, high-reward. A collection of layered, heavy-hitting Asian classics.</description>"
        "<language>en-us</language>"
        f"<lastBuildDate>{pub_date}</lastBuildDate>"
        f'<atom:link href="{SITE_URL}/api/feed.xml" rel="self" type="application/rss+xml"/>'
        + "".join(items)
        + "</channel></rss>"
    )
    return Response(content=xml, media_type="application/rss+xml")
