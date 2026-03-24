from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class Ingredient(BaseModel):
    item: str
    amount: str
    unit: str
    group: str | None = None


class Instruction(BaseModel):
    step: int
    text: str
    tip: str | None = None


class NutritionEntry(BaseModel):
    label: str
    value: float
    unit: str = ""


class RecipeComponent(BaseModel):
    """A sub-recipe within a multi-component dish (e.g. the rice in Hainanese Chicken Rice)."""
    title: str
    description: str | None = None
    ingredients: list[Ingredient] = []
    instructions: list[Instruction] = []
    prep_time_minutes: int | None = None
    cook_time_minutes: int | None = None
    yield_description: str | None = None  # e.g. "About ½–¾ cup" for sauces


class RecipeCreate(BaseModel):
    title: str
    description: str = ""
    ingredients: list[Ingredient] = []
    instructions: list[Instruction] = []
    prep_time_minutes: int = 0
    cook_time_minutes: int = 0
    servings: int = 1
    difficulty: Literal["easy", "medium", "hard"] = "easy"
    categories: list[str] = []
    image_url: str | None = None
    published: bool = False
    nutrition: list[NutritionEntry] = []
    components: list[RecipeComponent] | None = None
    receipt_urls: list[str] = []
    labels: list[str] = []


class RecipeUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    ingredients: list[Ingredient] | None = None
    instructions: list[Instruction] | None = None
    prep_time_minutes: int | None = None
    cook_time_minutes: int | None = None
    servings: int | None = None
    difficulty: Literal["easy", "medium", "hard"] | None = None
    categories: list[str] | None = None
    image_url: str | None = None
    published: bool | None = None
    nutrition: list[NutritionEntry] | None = None
    components: list[RecipeComponent] | None = None
    receipt_urls: list[str] | None = None
    labels: list[str] | None = None


class Recipe(BaseModel):
    id: str
    title: str
    slug: str
    description: str
    ingredients: list[Ingredient]
    instructions: list[Instruction]
    prep_time_minutes: int
    cook_time_minutes: int
    servings: int
    difficulty: Literal["easy", "medium", "hard"]
    categories: list[str]
    image_url: str | None
    published: bool
    created_at: datetime
    updated_at: datetime
    nutrition: list[NutritionEntry] = []
    components: list[RecipeComponent] | None = None
    receipt_urls: list[str] = []
    labels: list[str] = []


class PaginatedRecipes(BaseModel):
    recipes: list[Recipe]
    next_cursor: str | None = None


class CategoryGroup(BaseModel):
    category: str
    recipes: list[Recipe]


class GroupedRecipes(BaseModel):
    recent: list[Recipe]
    groups: list[CategoryGroup]


class PageContent(BaseModel):
    data: dict[str, str]


class ReceiptDeleteBody(BaseModel):
    url: str
