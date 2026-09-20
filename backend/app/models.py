from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

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


# The seven prose fields of an ingredient profile, and the cap on their
# combined length — the block services/knowledge.py renders straight into
# the prompt, so this is a token-cost knob, not just a Firestore-doc-size
# guard. ~1,000 chars is ~180 tokens typical, ~250 worst case for a profile
# that uses every field to its individual max.
PROFILE_PROSE_FIELDS = ("what_it_is", "role", "substitutions", "buying", "storage", "mistakes", "allergens")
MAX_PROFILE_CHARS = 1_000


class IngredientProfileIn(BaseModel):
    """An owner-authored ingredient profile: what it is, its role in a dish,
    what stands in for it, buying, storage, common mistakes, allergens.

    Callers (services/ingredients.py) run every string through
    services.users.clean_text before validating here, the same convention
    every other free-text field in this app follows — this model only
    enforces shape and length, it does not sanitise.
    """

    name: Annotated[str, Field(min_length=1, max_length=80)]
    aliases: Annotated[list[Annotated[str, Field(max_length=60)]], Field(max_length=12)] = []
    what_it_is: Annotated[str, Field(min_length=1, max_length=300)]
    role: Annotated[str, Field(max_length=200)] = ""  # fat / acid / umami / aromatic / texture
    substitutions: Annotated[str, Field(max_length=400)] = ""  # what works, what doesn't, what changes
    buying: Annotated[str, Field(max_length=250)] = ""
    storage: Annotated[str, Field(max_length=200)] = ""
    mistakes: Annotated[str, Field(max_length=250)] = ""
    allergens: Annotated[str, Field(max_length=100)] = ""

    @model_validator(mode="after")
    def _normalise_aliases_and_cap_prose(self) -> "IngredientProfileIn":
        # Dedup case-insensitively, drop blanks, and drop anything that's
        # just the name spelled differently — a "garlic" profile listing
        # "garlic" as its own alias buys nothing and doubles up in coverage.
        seen = {self.name.strip().casefold()}
        deduped: list[str] = []
        for alias in self.aliases:
            alias = alias.strip()
            key = alias.casefold()
            if alias and key not in seen:
                seen.add(key)
                deduped.append(alias)
        self.aliases = deduped

        total = sum(len(getattr(self, field)) for field in PROFILE_PROSE_FIELDS)
        if total > MAX_PROFILE_CHARS:
            raise ValueError(
                f"profile prose is {total} chars, over the {MAX_PROFILE_CHARS}-char cap "
                "(this block is rendered directly into the assistant's prompt)"
            )
        return self


class IngredientProfile(IngredientProfileIn):
    slug: str
    created_at: datetime
    updated_at: datetime
    updated_via: Literal["mcp", "admin"]


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
    # Owner-only guidance for the Sous Chef assistant (substitutions that work,
    # ones that don't, known pitfalls). Never rendered publicly — see AdminRecipe.
    sous_chef_notes: LongText | None = None


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
    sous_chef_notes: LongText | None = None


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


class AdminRecipe(Recipe):
    """The recipe as the owner sees it: everything in ``Recipe`` plus fields
    that must never reach a reader.

    ``Recipe`` is the public model and pydantic drops unknown keys, so a
    Firestore doc carrying ``sous_chef_notes`` serialises without it on every
    public route by construction — only admin routes and MCP tools use this
    subclass. The Sous Chef prompt reads the raw doc instead.
    """

    sous_chef_notes: str | None = None


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
