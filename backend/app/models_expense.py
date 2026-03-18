"""Pydantic models for the tax-compliant expense ledger."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


EXPENSE_CATEGORIES = [
    "ingredients",
    "equipment",
    "hosting",
    "marketing",
    "software",
    "other",
]

ExpenseCategory = Literal[
    "ingredients", "equipment", "hosting", "marketing", "software", "other"
]


class ExpenseItem(BaseModel):
    """A single line item from a receipt."""

    model_config = {"extra": "ignore"}

    name: str
    quantity: float = 1.0
    unit_price: int  # cents
    total_price: int  # cents
    project_related: bool = True
    recipe_id: str | None = None
    recipe_name: str | None = None


class ExpenseCreate(BaseModel):
    """Input model for creating a new expense."""

    date: datetime
    vendor: str
    category: ExpenseCategory = "other"
    description: str = ""
    purpose: str | None = None
    items: list[ExpenseItem] = []
    raw_subtotal: int = 0  # cents
    raw_tax: int = 0  # cents
    raw_total: int = 0  # cents
    transaction_id: str = ""
    merchant_id: str = ""
    recipe_ids: list[str] = Field(default_factory=list)
    recipe_names: list[str] = Field(default_factory=list)


class ExpenseUpdate(BaseModel):
    """Input model for updating an expense. All fields optional."""

    date: datetime | None = None
    vendor: str | None = None
    category: ExpenseCategory | None = None
    description: str | None = None
    purpose: str | None = Field(default=None)
    items: list[ExpenseItem] | None = None
    raw_subtotal: int | None = None
    raw_tax: int | None = None
    raw_total: int | None = None
    transaction_id: str | None = None
    merchant_id: str | None = None
    recipe_ids: list[str] | None = None
    recipe_names: list[str] | None = None


class Expense(BaseModel):
    """Full expense model returned from the API."""

    model_config = {"extra": "ignore"}

    id: str
    date: datetime
    vendor: str
    category: ExpenseCategory
    description: str
    purpose: str | None = None

    # Receipt identifiers
    transaction_id: str = ""
    merchant_id: str = ""

    # Receipt file
    receipt_url: str | None = None
    receipt_filename: str | None = None
    receipt_content_type: str | None = None

    # Raw receipt totals
    raw_subtotal: int
    raw_tax: int
    raw_total: int

    # Line items
    items: list[ExpenseItem] = []

    # Calculated project-only amounts
    project_subtotal: int = 0
    project_tax: int = 0
    project_total: int = 0

    # Expense-level recipe links (expense as a whole may span multiple recipes)
    recipe_ids: list[str] = Field(default_factory=list)
    recipe_names: list[str] = Field(default_factory=list)

    # Audit fields
    status: str = "active"  # "active" | "voided"
    voided_at: datetime | None = None
    void_reason: str | None = None
    created_at: datetime
    updated_at: datetime
    revision: int = 1
    ai_parsed: bool = False


class ExpenseSummary(BaseModel):
    """Lightweight model for list views (no items array)."""

    model_config = {"extra": "ignore"}

    id: str
    date: datetime
    vendor: str
    category: ExpenseCategory
    description: str
    purpose: str | None = None
    receipt_filename: str | None = None
    transaction_id: str = ""
    merchant_id: str = ""
    raw_total: int
    project_total: int
    project_tax: int
    recipe_ids: list[str] = Field(default_factory=list)
    recipe_names: list[str] = Field(default_factory=list)
    status: str
    created_at: datetime


def recalculate_project_amounts(
    items: list[ExpenseItem], raw_tax: int, raw_subtotal: int
) -> dict[str, int]:
    """Calculate project-only subtotal, proportional tax, and total.

    Returns dict with project_subtotal, project_tax, project_total (all in cents).
    """
    project_subtotal = sum(
        item.total_price for item in items if item.project_related
    )

    # Proportional tax: raw_tax * (project_subtotal / raw_subtotal)
    if raw_subtotal > 0:
        project_tax = round(raw_tax * (project_subtotal / raw_subtotal))
    else:
        project_tax = 0

    return {
        "project_subtotal": project_subtotal,
        "project_tax": project_tax,
        "project_total": project_subtotal + project_tax,
    }
