import re
from email.utils import formatdate

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from google.cloud.firestore_v1.base_query import FieldFilter

from ..firestore import get_db
from ..models import Recipe

router = APIRouter(prefix="/api")

SITE_URL = "https://madeforseconds.com"


def _doc_to_recipe(doc) -> Recipe:
    data = doc.to_dict()
    data["id"] = doc.id
    return Recipe(**data)


@router.get("/recipes", response_model=list[Recipe])
async def list_recipes(search: str | None = None, category: str | None = None):
    db = get_db()
    query = db.collection("recipes").where(filter=FieldFilter("published", "==", True))

    if category:
        query = query.where(filter=FieldFilter("categories", "array_contains", category))

    # Order and limit to avoid massive in-memory processing
    query = query.order_by("created_at", direction="DESCENDING").limit(50)
    docs = query.stream()

    recipes = [_doc_to_recipe(doc) for doc in docs]

    # Firestore doesn't support ILIKE, so filter in Python for search
    if search:
        pattern = re.compile(re.escape(search), re.IGNORECASE)
        recipes = [r for r in recipes if pattern.search(r.title) or pattern.search(r.description)]

    return recipes


@router.get("/recipes/{slug}", response_model=Recipe)
async def get_recipe(slug: str):
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
    return _doc_to_recipe(doc)


@router.get("/categories", response_model=list[str])
async def list_categories():
    db = get_db()
    # Only fetch categories field and limit to 100 most recent recipes
    # This is a heuristic to keep memory low while catching most categories
    docs = (
        db.collection("recipes")
        .where(filter=FieldFilter("published", "==", True))
        .order_by("created_at", direction="DESCENDING")
        .limit(100)
        .select(["categories"])
        .stream()
    )
    all_cats: set[str] = set()
    for doc in docs:
        cats = doc.to_dict().get("categories", [])
        all_cats.update(cats)
    return sorted(all_cats)


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

    items = []
    for r in recipes:
        url = f"{SITE_URL}/recipes/{r.slug}"
        desc = r.description.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        title = r.title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
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
            item = item.replace("</item>", f"<enclosure url='{r.image_url}' type='image/jpeg'/></item>")
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
