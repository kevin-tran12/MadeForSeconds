from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class Ingredient(BaseModel):
    item: str
    amount: str
    unit: str


class Instruction(BaseModel):
    step: int
    text: str


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
    rating: int | None = None


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
    rating: int | None = None


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
    rating: int | None = None
