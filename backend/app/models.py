from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field

# Input bounds — generous for real recipes, tight enough that a malformed or
# hostile payload can't balloon a Firestore doc toward its 1 MiB limit.
Title = Annotated[str, Field(min_length=1, max_length=200)]
ShortText = Annotated[str, Field(max_length=2000)]
LongText = Annotated[str, Field(max_length=10_000)]
Url = Annotated[str, Field(max_length=2000)]
Minutes = Annotated[int, Field(ge=0, le=100_000)]


class Ingredient(BaseModel):
    item: Annotated[str, Field(max_length=300)]
    amount: Annotated[str, Field(max_length=50)]
    unit: Annotated[str, Field(max_length=50)]
    group: Annotated[str, Field(max_length=100)] | None = None


class Instruction(BaseModel):
    step: int
    text: ShortText
    tip: Annotated[str, Field(max_length=1000)] | None = None


class NutritionEntry(BaseModel):
    label: Annotated[str, Field(max_length=100)]
    value: float
    unit: Annotated[str, Field(max_length=20)] = ""


class RecipeSecret(BaseModel):
    title: Annotated[str, Field(max_length=200)]
    body: LongText


class RecipeComponent(BaseModel):
    """A sub-recipe within a multi-component dish (e.g. the rice in Hainanese Chicken Rice)."""
    title: Annotated[str, Field(max_length=200)]
    description: ShortText | None = None
    ingredients: Annotated[list[Ingredient], Field(max_length=100)] = []
    prep_steps: Annotated[list[Instruction], Field(max_length=50)] = []
    instructions: Annotated[list[Instruction], Field(max_length=100)] = []
    prep_time_minutes: Minutes | None = None
    cook_time_minutes: Minutes | None = None
    yield_description: Annotated[str, Field(max_length=200)] | None = None  # e.g. "About ½–¾ cup" for sauces


class RecipeCreate(BaseModel):
    title: Title
    description: ShortText = ""
    about: LongText | None = None
    ingredients: Annotated[list[Ingredient], Field(max_length=100)] = []
    prep_steps: Annotated[list[Instruction], Field(max_length=50)] = []
    instructions: Annotated[list[Instruction], Field(max_length=100)] = []
    prep_time_minutes: Minutes = 0
    cook_time_minutes: Minutes = 0
    servings: Annotated[int, Field(ge=1, le=1000)] = 1
    difficulty: Literal["easy", "medium", "hard"] = "easy"
    categories: Annotated[list[str], Field(max_length=20)] = []
    image_url: Url | None = None
    published: bool = False
    nutrition: Annotated[list[NutritionEntry], Field(max_length=30)] = []
    components: Annotated[list[RecipeComponent], Field(max_length=5)] | None = None
    receipt_urls: Annotated[list[Url], Field(max_length=20)] = []
    labels: Annotated[list[str], Field(max_length=30)] = []
    secrets: Annotated[list[RecipeSecret], Field(max_length=20)] = []


class RecipeUpdate(BaseModel):
    title: Title | None = None
    description: ShortText | None = None
    about: LongText | None = None
    ingredients: Annotated[list[Ingredient], Field(max_length=100)] | None = None
    prep_steps: Annotated[list[Instruction], Field(max_length=50)] | None = None
    instructions: Annotated[list[Instruction], Field(max_length=100)] | None = None
    prep_time_minutes: Minutes | None = None
    cook_time_minutes: Minutes | None = None
    servings: Annotated[int, Field(ge=1, le=1000)] | None = None
    difficulty: Literal["easy", "medium", "hard"] | None = None
    categories: Annotated[list[str], Field(max_length=20)] | None = None
    image_url: Url | None = None
    published: bool | None = None
    nutrition: Annotated[list[NutritionEntry], Field(max_length=30)] | None = None
    components: Annotated[list[RecipeComponent], Field(max_length=5)] | None = None
    receipt_urls: Annotated[list[Url], Field(max_length=20)] | None = None
    labels: Annotated[list[str], Field(max_length=30)] | None = None
    secrets: Annotated[list[RecipeSecret], Field(max_length=20)] | None = None


class Recipe(BaseModel):
    id: str
    title: str
    slug: str
    description: str
    about: str | None = None
    ingredients: list[Ingredient]
    prep_steps: list[Instruction] = []
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
    secrets: list[RecipeSecret] = []


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
