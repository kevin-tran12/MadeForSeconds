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


EXPENSES = [
    {
        "date": datetime(2026, 1, 15, tzinfo=timezone.utc),
        "vendor": "H Mart",
        "category": "ingredients",
        "description": "Weekly grocery run for ramen and carbonara ingredients",
        "purpose": None,
        "transaction_id": "Tran# 100234",
        "merchant_id": "8829301742",
        "items": [
            {"name": "Pork Trotters", "quantity": 1.0, "unit_price": 899, "total_price": 899, "project_related": True, "recipe_id": None, "recipe_name": None, "_slug": "tonkotsu-ramen"},
            {"name": "Fresh Ramen Noodles", "quantity": 4.0, "unit_price": 249, "total_price": 996, "project_related": True, "recipe_id": None, "recipe_name": None, "_slug": "tonkotsu-ramen"},
            {"name": "Nori Sheets 10pk", "quantity": 1.0, "unit_price": 399, "total_price": 399, "project_related": True, "recipe_id": None, "recipe_name": None, "_slug": "tonkotsu-ramen"},
            {"name": "Guanciale", "quantity": 1.0, "unit_price": 699, "total_price": 699, "project_related": True, "recipe_id": None, "recipe_name": None, "_slug": "classic-spaghetti-carbonara"},
            {"name": "Pecorino Romano", "quantity": 1.0, "unit_price": 549, "total_price": 549, "project_related": True, "recipe_id": None, "recipe_name": None, "_slug": "classic-spaghetti-carbonara"},
            {"name": "Coca-Cola 12pk", "quantity": 1.0, "unit_price": 599, "total_price": 599, "project_related": False, "recipe_id": None, "recipe_name": None},
        ],
        "raw_subtotal": 4141,
        "raw_tax": 331,
        "raw_total": 4472,
    },
    {
        "date": datetime(2026, 1, 28, tzinfo=timezone.utc),
        "vendor": "Amazon",
        "category": "equipment",
        "description": "Kitchen thermometer for candy and deep frying",
        "purpose": "Instant-read thermometer",
        "transaction_id": "111-2345678-9012345",
        "merchant_id": "",
        "items": [
            {"name": "ThermoPro TP19H Instant Read Thermometer", "quantity": 1.0, "unit_price": 1599, "total_price": 1599, "project_related": True, "recipe_id": None, "recipe_name": None},
        ],
        "raw_subtotal": 1599,
        "raw_tax": 128,
        "raw_total": 1727,
    },
    {
        "date": datetime(2026, 2, 5, tzinfo=timezone.utc),
        "vendor": "Costco",
        "category": "ingredients",
        "description": "Bulk tahini and chickpeas for hummus batch",
        "purpose": None,
        "transaction_id": "4820-01-0205",
        "merchant_id": "COSTCO #482",
        "items": [
            {"name": "Organic Tahini 32oz", "quantity": 1.0, "unit_price": 899, "total_price": 899, "project_related": True, "recipe_id": None, "recipe_name": None, "_slug": "roasted-garlic-hummus"},
            {"name": "Chickpeas 6-pack", "quantity": 1.0, "unit_price": 599, "total_price": 599, "project_related": True, "recipe_id": None, "recipe_name": None, "_slug": "roasted-garlic-hummus"},
            {"name": "Olive Oil 1L", "quantity": 1.0, "unit_price": 1199, "total_price": 1199, "project_related": True, "recipe_id": None, "recipe_name": None, "_slug": "roasted-garlic-hummus"},
            {"name": "Paper Towels 12pk", "quantity": 1.0, "unit_price": 1899, "total_price": 1899, "project_related": False, "recipe_id": None, "recipe_name": None},
        ],
        "raw_subtotal": 4596,
        "raw_tax": 152,
        "raw_total": 4748,
    },
    {
        "date": datetime(2026, 2, 14, tzinfo=timezone.utc),
        "vendor": "Cloudflare",
        "category": "hosting",
        "description": "Annual domain renewal",
        "purpose": "madeforseconds.com domain renewal",
        "transaction_id": "CF-2026-0214",
        "merchant_id": "",
        "items": [
            {"name": "Domain renewal - madeforseconds.com", "quantity": 1.0, "unit_price": 1099, "total_price": 1099, "project_related": True, "recipe_id": None, "recipe_name": None},
        ],
        "raw_subtotal": 1099,
        "raw_tax": 0,
        "raw_total": 1099,
    },
    {
        "date": datetime(2026, 2, 20, tzinfo=timezone.utc),
        "vendor": "Whole Foods",
        "category": "ingredients",
        "description": "Buttermilk and maple syrup for pancake recipe shoot",
        "purpose": None,
        "transaction_id": "WF-8821-0220",
        "merchant_id": "WF Store #8821",
        "items": [
            {"name": "Organic Buttermilk 1qt", "quantity": 1.0, "unit_price": 449, "total_price": 449, "project_related": True, "recipe_id": None, "recipe_name": None, "_slug": "fluffy-buttermilk-pancakes"},
            {"name": "Vermont Maple Syrup 12oz", "quantity": 1.0, "unit_price": 899, "total_price": 899, "project_related": True, "recipe_id": None, "recipe_name": None, "_slug": "fluffy-buttermilk-pancakes"},
            {"name": "Unsalted Butter", "quantity": 1.0, "unit_price": 549, "total_price": 549, "project_related": True, "recipe_id": None, "recipe_name": None, "_slug": "fluffy-buttermilk-pancakes"},
            {"name": "All-Purpose Flour 5lb", "quantity": 1.0, "unit_price": 499, "total_price": 499, "project_related": True, "recipe_id": None, "recipe_name": None, "_slug": "fluffy-buttermilk-pancakes"},
        ],
        "raw_subtotal": 2396,
        "raw_tax": 0,
        "raw_total": 2396,
    },
    {
        "date": datetime(2026, 3, 1, tzinfo=timezone.utc),
        "vendor": "B&H Photo",
        "category": "equipment",
        "description": "Ring light for overhead recipe photography",
        "purpose": "18-inch ring light with stand",
        "transaction_id": "BH-9922134",
        "merchant_id": "",
        "items": [
            {"name": "Neewer 18\" LED Ring Light Kit", "quantity": 1.0, "unit_price": 4599, "total_price": 4599, "project_related": True, "recipe_id": None, "recipe_name": None},
        ],
        "raw_subtotal": 4599,
        "raw_tax": 409,
        "raw_total": 5008,
    },
    {
        "date": datetime(2026, 3, 8, tzinfo=timezone.utc),
        "vendor": "City Farmers Market #6",
        "category": "ingredients",
        "description": "Asian groceries — herbs, shrimp, coconut milk",
        "purpose": None,
        "transaction_id": "Tran# 400318",
        "merchant_id": "542929807243795",
        "items": [
            {"name": "Mint / Hung Lui LB", "quantity": 1.0, "unit_price": 230, "total_price": 230, "project_related": True, "recipe_id": None, "recipe_name": None},
            {"name": "Rau Ram LB", "quantity": 1.0, "unit_price": 375, "total_price": 375, "project_related": True, "recipe_id": None, "recipe_name": None},
            {"name": "Yellow Turmeric LB", "quantity": 1.0, "unit_price": 533, "total_price": 533, "project_related": True, "recipe_id": None, "recipe_name": None},
            {"name": "Puffed Fried Tofu 10oz", "quantity": 2.0, "unit_price": 339, "total_price": 678, "project_related": True, "recipe_id": None, "recipe_name": None},
            {"name": "Bean Sprouts / Gia Tuoi", "quantity": 1.31, "unit_price": 99, "total_price": 130, "project_related": True, "recipe_id": None, "recipe_name": None},
            {"name": "Ginger Root LB", "quantity": 0.29, "unit_price": 249, "total_price": 72, "project_related": True, "recipe_id": None, "recipe_name": None},
            {"name": "6/10 Black Tiger Shrimp H/O", "quantity": 1.0, "unit_price": 1863, "total_price": 1863, "project_related": True, "recipe_id": None, "recipe_name": None},
            {"name": "Coconut Milk 14oz", "quantity": 2.0, "unit_price": 219, "total_price": 438, "project_related": True, "recipe_id": None, "recipe_name": None},
            {"name": "Halal Chicken Whole LB", "quantity": 1.0, "unit_price": 1390, "total_price": 1390, "project_related": False, "recipe_id": None, "recipe_name": None},
        ],
        "raw_subtotal": 5709,
        "raw_tax": 157,
        "raw_total": 5866,
    },
    {
        "date": datetime(2026, 1, 10, tzinfo=timezone.utc),
        "vendor": "Target",
        "category": "equipment",
        "description": "Returned — wrong size cutting board",
        "purpose": "Bamboo cutting board (wrong size)",
        "transaction_id": "TGT-01-0110-4421",
        "merchant_id": "TGT Store #4421",
        "items": [
            {"name": "Large Bamboo Cutting Board", "quantity": 1.0, "unit_price": 2499, "total_price": 2499, "project_related": True, "recipe_id": None, "recipe_name": None},
        ],
        "raw_subtotal": 2499,
        "raw_tax": 200,
        "raw_total": 2699,
        "_voided": True,
        "_void_reason": "Returned to store — wrong size",
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

    # Seed sample expenses
    if force:
        print("Clearing existing expenses...")
        for doc in db.collection("expenses").stream():
            doc.reference.delete()
        for doc in db.collection("expense_revisions").stream():
            doc.reference.delete()

    existing_expenses = list(db.collection("expenses").limit(1).stream())
    if not existing_expenses or force:
        # Build slug → (id, title) map from seeded recipes
        slug_map = {}
        for doc in db.collection("recipes").stream():
            d = doc.to_dict()
            slug_map[d.get("slug", "")] = (doc.id, d.get("title", ""))

        for expense in EXPENSES:
            # Resolve recipe slugs in items
            items = []
            for item in expense["items"]:
                item_copy = {k: v for k, v in item.items() if not k.startswith("_")}
                slug = item.get("_slug")
                if slug and slug in slug_map:
                    item_copy["recipe_id"] = slug_map[slug][0]
                    item_copy["recipe_name"] = slug_map[slug][1]
                items.append(item_copy)

            # Calculate project amounts
            project_subtotal = sum(i["total_price"] for i in items if i.get("project_related", True))
            raw_subtotal = expense["raw_subtotal"]
            raw_tax = expense["raw_tax"]
            project_tax = round(raw_tax * (project_subtotal / raw_subtotal)) if raw_subtotal > 0 else 0

            is_voided = expense.get("_voided", False)
            data = {
                "date": expense["date"],
                "vendor": expense["vendor"],
                "category": expense["category"],
                "description": expense["description"],
                "purpose": expense.get("purpose"),
                "transaction_id": expense.get("transaction_id", ""),
                "merchant_id": expense.get("merchant_id", ""),
                "items": items,
                "raw_subtotal": raw_subtotal,
                "raw_tax": raw_tax,
                "raw_total": expense["raw_total"],
                "project_subtotal": project_subtotal,
                "project_tax": project_tax,
                "project_total": project_subtotal + project_tax,
                "receipt_url": None,
                "receipt_filename": None,
                "receipt_content_type": None,
                "status": "voided" if is_voided else "active",
                "voided_at": now if is_voided else None,
                "void_reason": expense.get("_void_reason") if is_voided else None,
                "created_at": now,
                "updated_at": now,
                "revision": 1,
                "ai_parsed": False,
            }

            doc_ref = db.collection("expenses").document()
            doc_ref.set(data)

            # Write initial revision
            db.collection("expense_revisions").document().set({
                "expense_id": doc_ref.id,
                "revision": 1,
                "snapshot": {**data, "id": doc_ref.id},
                "changed_by": "seed",
                "changed_at": now,
                "change_summary": "Seeded",
            })

            status_label = " [VOIDED]" if is_voided else ""
            print(f"  Created expense: {expense['vendor']} — ${expense['raw_total'] / 100:.2f}{status_label}")

        print(f"Seeded {len(EXPENSES)} expenses.")


if __name__ == "__main__":
    main()
