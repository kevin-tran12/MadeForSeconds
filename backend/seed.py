"""Seed the Firestore emulator with sample recipes."""

from datetime import datetime, timezone

from google.cloud.firestore import Client

RECIPES = [
    {
        "title": "Classic Spaghetti Carbonara",
        "slug": "classic-spaghetti-carbonara",
        "description": "A rich and creamy Roman pasta made with eggs, Pecorino Romano, guanciale, and black pepper. No cream needed.",
        "ingredients": [
            {"item": "spaghetti", "amount": "400", "unit": "g"},
            {"item": "guanciale or pancetta", "amount": "200", "unit": "g"},
            {"item": "eggs", "amount": "4", "unit": ""},
            {"item": "Pecorino Romano, grated", "amount": "100", "unit": "g"},
            {"item": "black pepper, freshly ground", "amount": "1", "unit": "tsp"},
            {"item": "salt", "amount": "", "unit": "to taste"},
        ],
        "instructions": [
            {"step": 1, "text": "Bring a large pot of salted water to boil and cook spaghetti until al dente."},
            {"step": 2, "text": "While pasta cooks, fry guanciale in a large pan over medium heat until crispy. Remove from heat."},
            {"step": 3, "text": "Whisk eggs with Pecorino and a generous amount of black pepper in a bowl."},
            {"step": 4, "text": "Reserve 1 cup pasta water. Drain pasta and add to the pan with guanciale off heat."},
            {"step": 5, "text": "Pour egg mixture over pasta, tossing quickly and adding pasta water a splash at a time until creamy."},
            {"step": 6, "text": "Serve immediately with extra Pecorino and black pepper."},
        ],
        "prep_time_minutes": 10,
        "cook_time_minutes": 20,
        "servings": 4,
        "difficulty": "medium",
        "categories": ["pasta", "italian", "quick"],
        "image_url": "https://images.unsplash.com/photo-1612874742237-6526221588e3?w=800&q=80",
        "published": True,
    },
    {
        "title": "Fluffy Buttermilk Pancakes",
        "slug": "fluffy-buttermilk-pancakes",
        "description": "Weekend-worthy pancakes that are light, fluffy, and golden. A simple batter with a secret: let it rest.",
        "ingredients": [
            {"item": "all-purpose flour", "amount": "1.5", "unit": "cups"},
            {"item": "buttermilk", "amount": "1.25", "unit": "cups"},
            {"item": "egg", "amount": "1", "unit": ""},
            {"item": "butter, melted", "amount": "3", "unit": "tbsp"},
            {"item": "sugar", "amount": "1", "unit": "tbsp"},
            {"item": "baking powder", "amount": "1.5", "unit": "tsp"},
            {"item": "baking soda", "amount": "0.5", "unit": "tsp"},
            {"item": "salt", "amount": "0.5", "unit": "tsp"},
        ],
        "instructions": [
            {"step": 1, "text": "Whisk flour, sugar, baking powder, baking soda, and salt in a large bowl."},
            {"step": 2, "text": "In another bowl, whisk buttermilk, egg, and melted butter together."},
            {"step": 3, "text": "Fold wet ingredients into dry until just combined \u2014 lumps are fine. Rest for 5 minutes."},
            {"step": 4, "text": "Heat a non-stick pan or griddle over medium heat and lightly butter it."},
            {"step": 5, "text": "Pour 1/4 cup batter per pancake. Cook until bubbles form and edges look set, about 2 min."},
            {"step": 6, "text": "Flip and cook 1 more minute until golden. Serve with maple syrup."},
        ],
        "prep_time_minutes": 5,
        "cook_time_minutes": 15,
        "servings": 4,
        "difficulty": "easy",
        "categories": ["breakfast", "vegetarian", "quick"],
        "image_url": "https://images.unsplash.com/photo-1567620905732-2d1ec7ab7445?w=800&q=80",
        "published": True,
    },
    {
        "title": "Roasted Garlic Hummus",
        "slug": "roasted-garlic-hummus",
        "description": "Silky smooth hummus with deep roasted garlic flavor. Far better than store-bought and takes only minutes to blend.",
        "ingredients": [
            {"item": "canned chickpeas, drained (reserve liquid)", "amount": "400", "unit": "g"},
            {"item": "tahini", "amount": "3", "unit": "tbsp"},
            {"item": "garlic cloves, roasted", "amount": "4", "unit": ""},
            {"item": "lemon juice", "amount": "3", "unit": "tbsp"},
            {"item": "olive oil, plus more to serve", "amount": "2", "unit": "tbsp"},
            {"item": "cumin", "amount": "0.5", "unit": "tsp"},
            {"item": "salt", "amount": "", "unit": "to taste"},
            {"item": "paprika and parsley to garnish", "amount": "", "unit": ""},
        ],
        "instructions": [
            {"step": 1, "text": "To roast garlic: wrap unpeeled cloves in foil with a drizzle of oil, roast at 200C/400F for 30 min until soft. Squeeze out flesh."},
            {"step": 2, "text": "Add chickpeas, tahini, roasted garlic, lemon juice, olive oil, cumin, and salt to a food processor."},
            {"step": 3, "text": "Blend for 3 minutes, adding reserved chickpea liquid a tablespoon at a time until very smooth."},
            {"step": 4, "text": "Taste and adjust seasoning. Transfer to a bowl, drizzle with olive oil, sprinkle paprika and parsley."},
        ],
        "prep_time_minutes": 5,
        "cook_time_minutes": 30,
        "servings": 6,
        "difficulty": "easy",
        "categories": ["snack", "vegetarian", "vegan", "make-ahead"],
        "image_url": "https://images.unsplash.com/photo-1585325701954-b9e08b5cfb71?w=800&q=80",
        "published": True,
    },
]


def main():
    db = Client(project="madefor-seconds-local")
    collection = db.collection("recipes")

    # Check if recipes already exist
    existing = list(collection.limit(1).stream())
    if existing:
        print("Recipes already exist, skipping seed.")
        return

    now = datetime.now(timezone.utc)
    for recipe in RECIPES:
        recipe["created_at"] = now
        recipe["updated_at"] = now
        doc_ref = collection.document()
        doc_ref.set(recipe)
        print(f"  Created: {recipe['title']}")

    print(f"\nSeeded {len(RECIPES)} recipes.")


if __name__ == "__main__":
    main()
