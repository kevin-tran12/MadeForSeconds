import re

from fastapi import APIRouter, HTTPException
from google.cloud.firestore_v1.base_query import FieldFilter

from ..firestore import get_db
from ..models import Recipe

router = APIRouter(prefix="/api")


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

    query = query.order_by("created_at", direction="DESCENDING")
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
    docs = (
        db.collection("recipes")
        .where(filter=FieldFilter("published", "==", True))
        .select(["categories"])
        .stream()
    )
    all_cats: set[str] = set()
    for doc in docs:
        cats = doc.to_dict().get("categories", [])
        all_cats.update(cats)
    return sorted(all_cats)
