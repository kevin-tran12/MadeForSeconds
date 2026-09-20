"""Typed MCP tool input models that don't already live in app/models.py or
app/models_expense.py (S10 of the MCP hardening epic).

Recipe-shaped inputs (Ingredient, Instruction, NutritionEntry, RecipeSecret,
RecipeComponent) are reused directly from app/models.py by the tools that
need them — the MCP tools and the admin HTTP routes describe the exact same
recipe shape, so one set of field names and length limits, not two that
could quietly drift apart.

ExpenseItemInput below is NOT reused from app/models_expense.py's
ExpenseItem, because the two describe different things: ExpenseItem is what
actually gets persisted (recipe_id/recipe_name, already resolved) — this is
what an MCP caller supplies instead (recipe_slug, resolved server-side by
tools/expenses.py's _resolve_recipe_slugs before an ExpenseItem is built).
Giving the MCP surface its own input model here, rather than stretching
ExpenseItem to serve both jobs, keeps "what a caller sends" and "what gets
stored" as two things that can evolve independently.
"""

from pydantic import BaseModel


class ExpenseItemInput(BaseModel):
    """A single receipt line item, as create_expense's MCP tool accepts it.

    Defaults match the shape the tool accepted before this model existed
    (a plain list[dict] read with .get(key, default)) — unit_price and
    total_price default to 0 rather than being required, same as before.
    """

    name: str
    quantity: float = 1.0
    unit_price: int = 0  # cents
    total_price: int = 0  # cents
    project_related: bool = True
    recipe_slug: str | None = None
