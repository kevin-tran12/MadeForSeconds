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


def test_recipe_create_field_bounds():
    """Input fields are bounded so a payload can't balloon Firestore docs."""
    with pytest.raises(ValidationError):
        RecipeCreate(title="")  # empty title

    with pytest.raises(ValidationError):
        RecipeCreate(title="x" * 201)  # title too long

    with pytest.raises(ValidationError):
        RecipeCreate(title="ok", about="x" * 10_001)  # about too long

    with pytest.raises(ValidationError):
        RecipeCreate(title="ok", servings=0)  # servings must be >= 1

    with pytest.raises(ValidationError):
        RecipeCreate(
            title="ok",
            ingredients=[{"item": "x" * 301, "amount": "1", "unit": "cup"}],
        )

    with pytest.raises(ValidationError):
        RecipeCreate(title="ok", prep_time_minutes=-1)

    # Realistic recipe is untouched by the bounds
    recipe = RecipeCreate(
        title="Hainanese Chicken Rice",
        about="A beloved dish..." * 50,
        ingredients=[{"item": "Chicken", "amount": "1", "unit": "whole"}] * 40,
        servings=6,
    )
    assert recipe.servings == 6


def test_recipe_update_field_bounds():
    with pytest.raises(ValidationError):
        RecipeUpdate(title="")

    with pytest.raises(ValidationError):
        RecipeUpdate(description="x" * 2001)

    assert RecipeUpdate(title="Fine").title == "Fine"


# ── sous_chef_notes: owner-only, never on the public model ────────────────────

def test_public_recipe_model_drops_sous_chef_notes():
    from app.models import AdminRecipe, Recipe
    data = {
        "id": "r1", "title": "T", "slug": "t", "description": "", "ingredients": [],
        "instructions": [], "prep_time_minutes": 0, "cook_time_minutes": 0, "servings": 1,
        "difficulty": "easy", "categories": [], "image_url": None, "published": True,
        "created_at": datetime(2026, 1, 1), "updated_at": datetime(2026, 1, 1),
        "sous_chef_notes": "private",
    }
    assert "sous_chef_notes" not in Recipe(**data).model_dump()
    assert AdminRecipe(**data).sous_chef_notes == "private"
    assert AdminRecipe(**{k: v for k, v in data.items() if k != "sous_chef_notes"}).sous_chef_notes is None


def test_sous_chef_notes_is_optional_and_bounded():
    assert RecipeCreate(title="T").sous_chef_notes is None
    assert RecipeCreate(title="T", sous_chef_notes="x").sous_chef_notes == "x"
    assert RecipeUpdate(sous_chef_notes=None).model_dump(exclude_unset=True) == {"sous_chef_notes": None}
    with pytest.raises(ValidationError):
        RecipeCreate(title="T", sous_chef_notes="x" * 10_001)
