import pytest
from datetime import datetime
from pydantic import ValidationError
from app.models import RecipeCreate, RecipeUpdate
from app.models_expense import ExpenseCreate, ExpenseUpdate, ExpenseItem, recalculate_project_amounts


def test_recipe_create_validation():
    # Required fields: title
    with pytest.raises(ValidationError):
        RecipeCreate()
    
    recipe = RecipeCreate(title="Test Recipe")
    assert recipe.title == "Test Recipe"
    assert recipe.published is False
    assert recipe.difficulty == "easy"


def test_recipe_update_all_optional():
    # All fields should be optional
    update = RecipeUpdate()
    assert update.title is None
    
    update = RecipeUpdate(title="New Title")
    assert update.title == "New Title"


def test_expense_create_validation():
    # Required fields: date, vendor
    with pytest.raises(ValidationError):
        ExpenseCreate()
    
    expense = ExpenseCreate(
        date=datetime(2024, 1, 1),
        vendor="Test Vendor"
    )
    assert expense.vendor == "Test Vendor"
    assert expense.category == "other"


def test_recalculate_project_amounts():
    items = [
        ExpenseItem(name="Item 1", unit_price=1000, total_price=1000, project_related=True),
        ExpenseItem(name="Item 2", unit_price=2000, total_price=2000, project_related=False),
    ]
    # Total subtotal = 3000
    # Project subtotal = 1000
    # Raw tax = 300
    # Proportional tax = 300 * (1000 / 3000) = 100
    
    result = recalculate_project_amounts(items, raw_tax=300, raw_subtotal=3000)
    assert result["project_subtotal"] == 1000
    assert result["project_tax"] == 100
    assert result["project_total"] == 1100


def test_recalculate_zero_raw_subtotal():
    items = []
    result = recalculate_project_amounts(items, raw_tax=300, raw_subtotal=0)
    assert result["project_subtotal"] == 0
    assert result["project_tax"] == 0
    assert result["project_total"] == 0


def test_expense_category_enum():
    with pytest.raises(ValidationError):
        ExpenseCreate(
            date=datetime(2024, 1, 1),
            vendor="Test Vendor",
            category="invalid-category"
        )
    
    expense = ExpenseCreate(
        date=datetime(2024, 1, 1),
        vendor="Test Vendor",
        category="software"
    )
    assert expense.category == "software"
