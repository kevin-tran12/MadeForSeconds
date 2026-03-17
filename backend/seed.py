"""Seed the Firestore emulator with sample recipes."""

import sys
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
        "nutrition": [
            {"label": "Calories",           "value": 720, "unit": "kcal"},
            {"label": "Total Fat",          "value": 28,  "unit": "g"},
            {"label": "Saturated Fat",      "value": 11,  "unit": "g"},
            {"label": "Trans Fat",          "value": 0,   "unit": "g"},
            {"label": "Cholesterol",        "value": 245, "unit": "mg"},
            {"label": "Sodium",             "value": 890, "unit": "mg"},
            {"label": "Total Carbohydrate", "value": 78,  "unit": "g"},
            {"label": "Dietary Fiber",      "value": 3,   "unit": "g"},
            {"label": "Total Sugars",       "value": 2,   "unit": "g"},
            {"label": "Protein",            "value": 38,  "unit": "g"},
        ],
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
            {"step": 3, "text": "Fold wet ingredients into dry until just combined — lumps are fine. Rest for 5 minutes."},
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
        "nutrition": [
            {"label": "Calories",           "value": 310, "unit": "kcal"},
            {"label": "Total Fat",          "value": 9,   "unit": "g"},
            {"label": "Saturated Fat",      "value": 4,   "unit": "g"},
            {"label": "Trans Fat",          "value": 0,   "unit": "g"},
            {"label": "Cholesterol",        "value": 75,  "unit": "mg"},
            {"label": "Sodium",             "value": 420, "unit": "mg"},
            {"label": "Total Carbohydrate", "value": 50,  "unit": "g"},
            {"label": "Dietary Fiber",      "value": 2,   "unit": "g"},
            {"label": "Total Sugars",       "value": 12,  "unit": "g"},
            {"label": "Protein",            "value": 8,   "unit": "g"},
        ],
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
        "nutrition": [
            {"label": "Calories",           "value": 180, "unit": "kcal"},
            {"label": "Total Fat",          "value": 10,  "unit": "g"},
            {"label": "Saturated Fat",      "value": 1.5, "unit": "g"},
            {"label": "Trans Fat",          "value": 0,   "unit": "g"},
            {"label": "Cholesterol",        "value": 0,   "unit": "mg"},
            {"label": "Sodium",             "value": 310, "unit": "mg"},
            {"label": "Total Carbohydrate", "value": 18,  "unit": "g"},
            {"label": "Dietary Fiber",      "value": 5,   "unit": "g"},
            {"label": "Total Sugars",       "value": 2,   "unit": "g"},
            {"label": "Protein",            "value": 6,   "unit": "g"},
        ],
    },
    {
        "title": "Tonkotsu Ramen",
        "slug": "tonkotsu-ramen",
        "description": "A deeply rich, milky pork bone broth with tender chashu pork, marinated soft-boiled eggs, and fresh ramen noodles. This is the real deal — it takes time, but the result is extraordinary.",
        "ingredients": [
            {"item": "pork trotters or neck bones", "amount": "1", "unit": "kg", "group": "Broth"},
            {"item": "water", "amount": "4", "unit": "L", "group": "Broth"},
            {"item": "ginger, sliced", "amount": "5", "unit": "cm", "group": "Broth"},
            {"item": "garlic cloves", "amount": "6", "unit": "", "group": "Broth"},
            {"item": "soy sauce", "amount": "4", "unit": "tbsp", "group": "Tare"},
            {"item": "mirin", "amount": "2", "unit": "tbsp", "group": "Tare"},
            {"item": "sake", "amount": "2", "unit": "tbsp", "group": "Tare"},
            {"item": "pork belly, skin-on", "amount": "500", "unit": "g", "group": "Chashu Pork"},
            {"item": "soy sauce", "amount": "100", "unit": "ml", "group": "Chashu Pork"},
            {"item": "mirin", "amount": "50", "unit": "ml", "group": "Chashu Pork"},
            {"item": "sake", "amount": "50", "unit": "ml", "group": "Chashu Pork"},
            {"item": "sugar", "amount": "2", "unit": "tbsp", "group": "Chashu Pork"},
            {"item": "eggs", "amount": "4", "unit": "", "group": "Ramen Eggs"},
            {"item": "soy sauce", "amount": "3", "unit": "tbsp", "group": "Ramen Eggs"},
            {"item": "mirin", "amount": "1", "unit": "tbsp", "group": "Ramen Eggs"},
            {"item": "fresh ramen noodles", "amount": "4", "unit": "portions", "group": "To Serve"},
            {"item": "green onions, sliced", "amount": "4", "unit": "stalks", "group": "To Serve"},
            {"item": "nori sheets", "amount": "4", "unit": "", "group": "To Serve"},
            {"item": "sesame seeds", "amount": "2", "unit": "tsp", "group": "To Serve"},
            {"item": "toasted sesame oil", "amount": "1", "unit": "tsp", "group": "To Serve"},
        ],
        "instructions": [
            {"step": 1, "text": "Blanch pork bones in boiling water for 10 minutes. Rinse thoroughly under cold water to remove impurities.", "tip": "This step is critical for a clean, white broth. Don't skip it."},
            {"step": 2, "text": "Place blanched bones in a large pot with 4L cold water, ginger, and garlic. Bring to a rolling boil over high heat."},
            {"step": 3, "text": "Boil vigorously for 3–4 hours, adding water as needed to keep bones submerged. The aggressive boil emulsifies the fat into the broth, creating the signature milky white color.", "tip": "The broth should look opaque white, like milk. If it's clear, increase the heat."},
            {"step": 4, "text": "Combine soy sauce, mirin, and sake in a small saucepan. Simmer for 5 minutes to cook off alcohol. This is your tare."},
            {"step": 5, "text": "Roll pork belly tightly and tie with kitchen twine. Sear in an oven-safe pan until browned on all sides."},
            {"step": 6, "text": "Add soy sauce, mirin, sake, and sugar to the pan. Add water to come halfway up the pork. Braise at 160°C for 2 hours, turning every 30 minutes.", "tip": "The chashu is done when you can pierce it easily with a chopstick and the edges have a lacquered, deep brown color."},
            {"step": 7, "text": "Boil eggs for exactly 6.5 minutes, then transfer to ice water. Peel and marinate in soy sauce and mirin mixture for at least 4 hours.", "tip": "The yolk should be jammy — set on the outside but still slightly soft in the center."},
            {"step": 8, "text": "Strain the broth, discarding solids. Season with tare — start with 2 tbsp per bowl and adjust to taste."},
            {"step": 9, "text": "Cook noodles per package instructions. Drain and divide into bowls."},
            {"step": 10, "text": "Ladle hot broth over noodles. Top with sliced chashu, halved ramen egg, nori, green onions, sesame seeds, and a drop of sesame oil."},
        ],
        "prep_time_minutes": 60,
        "cook_time_minutes": 240,
        "servings": 4,
        "difficulty": "hard",
        "categories": ["japanese", "noodles", "pork", "soup"],
        "image_url": "https://images.unsplash.com/photo-1569718212165-3a8278d5f624?w=800&q=80",
        "published": True,
        "nutrition": [
            {"label": "Calories",           "value": 820, "unit": "kcal"},
            {"label": "Total Fat",          "value": 34,  "unit": "g"},
            {"label": "Saturated Fat",      "value": 12,  "unit": "g"},
            {"label": "Trans Fat",          "value": 0,   "unit": "g"},
            {"label": "Cholesterol",        "value": 210, "unit": "mg"},
            {"label": "Sodium",             "value": 1850, "unit": "mg"},
            {"label": "Total Carbohydrate", "value": 68,  "unit": "g"},
            {"label": "Dietary Fiber",      "value": 3,   "unit": "g"},
            {"label": "Total Sugars",       "value": 8,   "unit": "g"},
            {"label": "Protein",            "value": 52,  "unit": "g"},
        ],
    },
]


SUPPORTERS = [
    {
        "email": "alice@example.com",
        "status": "active",
        "display_name": "Alice",
        "note": "Love the carbonara recipe!",
        "note_is_public": True,
        "total_donated_cents": 1000,
        "profile_set_at": True,
    },
    {
        "email": "bob@example.com",
        "status": "active",
        "display_name": "Bob",
        "note": None,
        "note_is_public": False,
        "total_donated_cents": 500,
        "profile_set_at": True,
    },
    {
        "email": "carol@example.com",
        "status": "active",
        "display_name": "Carol 🍝",
        "note": "Keep the recipes coming!",
        "note_is_public": True,
        "total_donated_cents": 2500,
        "profile_set_at": True,
    },
]


def main():
    force = "--force" in sys.argv
    db = Client(project="madefor-seconds-local")
    collection = db.collection("recipes")

    existing = list(collection.limit(1).stream())
    if existing and not force:
        print("Recipes already exist. Use --force to reseed.")
        return

    if force:
        print("Clearing existing recipes...")
        for doc in collection.stream():
            doc.reference.delete()
        print("Clearing existing supporters...")
        for doc in db.collection("subscribers").stream():
            doc.reference.delete()

    now = datetime.now(timezone.utc)
    for recipe in RECIPES:
        recipe["created_at"] = now
        recipe["updated_at"] = now
        doc_ref = collection.document()
        doc_ref.set(recipe)
        print(f"  Created: {recipe['title']}")

    print(f"\nSeeded {len(RECIPES)} recipes.")

    # Seed sample supporters
    existing_supporters = list(db.collection("subscribers").limit(1).stream())
    if not existing_supporters or force:
        for supporter in SUPPORTERS:
            data = {**supporter, "created_at": now, "updated_at": now}
            db.collection("subscribers").document().set(data)
            print(f"  Created supporter: {supporter['display_name']}")
        print(f"Seeded {len(SUPPORTERS)} supporters.")


if __name__ == "__main__":
    main()
