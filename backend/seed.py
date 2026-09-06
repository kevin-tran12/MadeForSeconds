"""Seed sample recipes/supporters/expenses/pages into Firestore.

Defaults to the local emulator project (docker-compose's normal use — see
docker-compose.yml / ci.yml's E2E job). Pass --project to target a real
project instead — e.g. staging, seeded once by .github/workflows/deploy.yml
so its Playwright run has real content to assert against. Safe to call on
every merge: without --force this is a no-op once recipes already exist, so
repeated pipeline runs never re-wipe staging's data.

The ingredient profiles (INGREDIENT_PROFILES) are sample data for
scripts/eval_sous_chef.py's profile cases. They are effectively local-only:
main() returns early when recipes already exist, so a staging run that is
already seeded never reaches them, and staging's Sous Chef keeps answering
with no profiles, exactly as production does until the owner authors real
ones. A fresh emulator (or --force) is what seeds them."""

import argparse
from datetime import datetime, timedelta, timezone

from google.cloud.firestore import Client

RECIPES = [
    {
        "title": "Classic Spaghetti Carbonara",
        "slug": "classic-spaghetti-carbonara",
        "description": "A rich and creamy Roman pasta made with eggs, Pecorino Romano, guanciale, and black pepper. No cream needed.",
        "about": (
            "Carbonara is one of Rome's four canonical pasta dishes — the others being cacio e pepe, amatriciana, "
            "and gricia. Its origins are debated: some attribute it to Roman coal miners (carbonari) who made it "
            "on long work camps in the Apennines, others to Allied soldiers in WWII who combined their rations of "
            "bacon and powdered eggs with local pasta. What's undisputed is that true carbonara contains no cream — "
            "the silkiness comes entirely from the emulsification of eggs, aged cheese, starchy pasta water, and fat. "
            "In Rome, guanciale (cured pork cheek) is non-negotiable; its higher fat content and distinct flavor "
            "cannot be replicated by pancetta, let alone bacon."
        ),
        "prep_steps": [
            {"step": 1, "text": "Remove guanciale from packaging and cut into 1cm lardons (thick strips). The rind can be left on — it renders beautifully.", "tip": "If using pancetta, cut similarly. The pieces should be chunky, not shaved thin."},
            {"step": 2, "text": "Grate Pecorino Romano finely — a microplane or the small holes on a box grater work best. You want it almost powdery so it melts into the sauce without clumping."},
            {"step": 3, "text": "Combine eggs and grated Pecorino in a bowl. Season generously with freshly cracked black pepper. Whisk until smooth and set aside at room temperature.", "tip": "Room-temperature egg mixture is crucial — cold eggs hitting hot pasta can scramble instead of emulsify."},
        ],
        "secrets": [
            {
                "title": "The Emulsification Window",
                "body": (
                    "Carbonara lives and dies in about 30 seconds. The egg mixture must hit the pasta when it's "
                    "hot enough to cook the eggs gently but not so hot that they scramble. The sweet spot is "
                    "roughly 65–70°C (150–160°F). Pulling the pan off heat completely before adding the eggs — "
                    "and using pasta water aggressively — gives you control over that temperature. The starch in "
                    "the pasta water stabilizes the emulsion the same way cornstarch stabilizes a custard."
                ),
            },
            {
                "title": "Why Guanciale, Not Pancetta",
                "body": (
                    "Guanciale (pork cheek) has a higher fat-to-meat ratio than pancetta (pork belly) and a "
                    "more pronounced, funky depth from the curing process. When rendered, its fat becomes the "
                    "cooking medium for the sauce — a flavor you simply cannot replicate with pancetta. "
                    "In traditional Roman kitchens, substituting pancetta is considered acceptable; "
                    "using bacon is not."
                ),
            },
        ],
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
    # The production Hainanese Chicken Rice, copied verbatim (four components, no
    # top-level ingredients, no secrets) so tests/fixtures/sous_chef_eval.json's
    # cases run against the emulator. Re-fetch with the MCP get_recipe tool if
    # the live recipe changes; drift is harmless for a sample.
    {
        "title": "Hainanese Chicken Rice (海南鸡饭)",
        "slug": "hainanese-chicken-rice",
        "description": "Hainanese chicken rice looks minimalist on the plate, but the dish is really a flavor system: the chicken gives broth and fat, the rice absorbs both, and the sauces sharpen everything. The rice is the anchor — when the rice is right, glossy, aromatic, and savory, you can eat a bowl of it alone and still feel satisfied. This is a balanced home batch for 4 servings, scaled so nothing feels excessive while still maintaining proper ratios used in hawker kitchens. MSG is included intentionally; it deepens the chicken flavor rather than making the dish salty.",
        "about": None,
        "ingredients": [],
        "prep_steps": [],
        "instructions": [],
        "prep_time_minutes": 35,
        "cook_time_minutes": 55,
        "servings": 4,
        "difficulty": "medium",
        "categories": [
            "Chinese",
            "Singaporean",
            "Malaysian",
            "Rice Dishes"
        ],
        "image_url": "https://storage.googleapis.com/made-for-seconds-images/b85f04b6-4867-4730-a53c-a7bf27096d97-738FE502-5014-4631-9EE3-17041029FBDA.JPG",
        "published": True,
        "nutrition": [
            {
                "label": "Calories",
                "value": 685.0,
                "unit": "kcal"
            },
            {
                "label": "Total Fat",
                "value": 28.0,
                "unit": "g"
            },
            {
                "label": "Saturated Fat",
                "value": 8.0,
                "unit": "g"
            },
            {
                "label": "Trans Fat",
                "value": 0.0,
                "unit": "g"
            },
            {
                "label": "Polyunsaturated Fat",
                "value": 5.0,
                "unit": "g"
            },
            {
                "label": "Monounsaturated Fat",
                "value": 12.0,
                "unit": "g"
            },
            {
                "label": "Cholesterol",
                "value": 145.0,
                "unit": "mg"
            },
            {
                "label": "Sodium",
                "value": 1120.0,
                "unit": "mg"
            },
            {
                "label": "Total Carbohydrate",
                "value": 58.0,
                "unit": "g"
            },
            {
                "label": "Dietary Fiber",
                "value": 1.5,
                "unit": "g"
            },
            {
                "label": "Total Sugars",
                "value": 3.0,
                "unit": "g"
            },
            {
                "label": "Added Sugars",
                "value": 1.0,
                "unit": "g"
            },
            {
                "label": "Protein",
                "value": 46.0,
                "unit": "g"
            },
            {
                "label": "Vitamin A",
                "value": 35.0,
                "unit": "mcg"
            },
            {
                "label": "Vitamin C",
                "value": 18.0,
                "unit": "mg"
            },
            {
                "label": "Vitamin K",
                "value": 12.0,
                "unit": "mcg"
            },
            {
                "label": "Niacin",
                "value": 14.0,
                "unit": "mg"
            },
            {
                "label": "Vitamin B6",
                "value": 0.8,
                "unit": "mg"
            },
            {
                "label": "Folate",
                "value": 28.0,
                "unit": "mcg"
            },
            {
                "label": "Calcium",
                "value": 35.0,
                "unit": "mg"
            },
            {
                "label": "Iron",
                "value": 2.8,
                "unit": "mg"
            },
            {
                "label": "Potassium",
                "value": 420.0,
                "unit": "mg"
            },
            {
                "label": "Phosphorus",
                "value": 310.0,
                "unit": "mg"
            },
            {
                "label": "Zinc",
                "value": 3.2,
                "unit": "mg"
            },
            {
                "label": "Selenium",
                "value": 32.0,
                "unit": "mcg"
            }
        ],
        "components": [
            {
                "title": "Hainanese Poached Chicken",
                "description": "Gentle poaching keeps the meat silky and produces the broth needed for the rice and sauces. Done when thickest part of thigh reaches 165°F / 74°C.",
                "ingredients": [
                    {
                        "item": "whole chicken, cleaned",
                        "amount": "1",
                        "unit": "whole (3–3½ lb)",
                        "group": "Poaching"
                    },
                    {
                        "item": "water",
                        "amount": "2.5",
                        "unit": "L",
                        "group": "Poaching"
                    },
                    {
                        "item": "ginger, sliced",
                        "amount": "30",
                        "unit": "g",
                        "group": "Poaching"
                    },
                    {
                        "item": "scallions, smashed",
                        "amount": "2",
                        "unit": "",
                        "group": "Poaching"
                    },
                    {
                        "item": "salt",
                        "amount": "2",
                        "unit": "tsp",
                        "group": "Poaching"
                    },
                    {
                        "item": "MSG",
                        "amount": "0.75",
                        "unit": "tsp",
                        "group": "Poaching"
                    },
                    {
                        "item": "cold water",
                        "amount": "1.5",
                        "unit": "L",
                        "group": "Ice Bath"
                    },
                    {
                        "item": "ice",
                        "amount": "1",
                        "unit": "cup",
                        "group": "Ice Bath"
                    },
                    {
                        "item": "sesame oil",
                        "amount": "0.5",
                        "unit": "tsp",
                        "group": "Glaze"
                    }
                ],
                "prep_steps": [],
                "instructions": [
                    {
                        "step": 1,
                        "text": "Rub the entire chicken with 2 tsp salt, gently massaging the skin. Rinse thoroughly under cold water.",
                        "tip": "This removes impurities and tightens the skin so it cooks smooth instead of loose and wrinkled."
                    },
                    {
                        "step": 2,
                        "text": "In a large pot combine 2.5L water, sliced ginger, smashed scallions, and MSG. Bring to a gentle simmer.",
                        "tip": "MSG strengthens the natural chicken flavor of the broth without increasing saltiness."
                    },
                    {
                        "step": 3,
                        "text": "Lower the chicken into the pot breast-side down. The water should barely bubble. Simmer 30–35 minutes.",
                        "tip": "If the water boils aggressively the meat will tighten and the broth becomes cloudy."
                    },
                    {
                        "step": 4,
                        "text": "Transfer the chicken immediately to an ice bath for 5 minutes.",
                        "tip": "Rapid cooling firms the skin and creates the slightly gelatinous texture prized in Singapore hawker stalls."
                    },
                    {
                        "step": 5,
                        "text": "Remove chicken from the ice bath and let it rest 10 minutes. Rub lightly with sesame oil.",
                        "tip": "Sesame oil gives the glossy finish typical of restaurant chicken rice."
                    }
                ],
                "prep_time_minutes": 15,
                "cook_time_minutes": 35,
                "yield_description": None
            },
            {
                "title": "Hainanese Chicken Rice",
                "description": "This is the heart of the dish. Each grain should smell like ginger, garlic, and chicken fat.",
                "ingredients": [
                    {
                        "item": "jasmine rice, rinsed well",
                        "amount": "2",
                        "unit": "cups",
                        "group": None
                    },
                    {
                        "item": "chicken fat (skimmed from broth or rendered from cavity)",
                        "amount": "2",
                        "unit": "tbsp",
                        "group": None
                    },
                    {
                        "item": "shallots, finely diced",
                        "amount": "2",
                        "unit": "",
                        "group": None
                    },
                    {
                        "item": "garlic, minced",
                        "amount": "3",
                        "unit": "cloves",
                        "group": None
                    },
                    {
                        "item": "ginger, minced",
                        "amount": "15",
                        "unit": "g",
                        "group": None
                    },
                    {
                        "item": "pandan leaf, tied into a knot (optional)",
                        "amount": "1",
                        "unit": "",
                        "group": None
                    },
                    {
                        "item": "hot chicken broth",
                        "amount": "2.25",
                        "unit": "cups",
                        "group": None
                    },
                    {
                        "item": "salt",
                        "amount": "0.5",
                        "unit": "tsp",
                        "group": None
                    },
                    {
                        "item": "MSG",
                        "amount": "0.5",
                        "unit": "tsp",
                        "group": None
                    }
                ],
                "prep_steps": [],
                "instructions": [
                    {
                        "step": 1,
                        "text": "Rinse 2 cups jasmine rice under cold water until mostly clear. Drain completely.",
                        "tip": "Removing excess starch keeps grains fluffy instead of sticky."
                    },
                    {
                        "step": 2,
                        "text": "Heat 2 tbsp chicken fat in a pot over medium heat. Add diced shallots, minced garlic, and minced ginger. Cook until fragrant and lightly golden.",
                        "tip": "This aromatic base is what makes the rice smell incredible even before broth is added."
                    },
                    {
                        "step": 3,
                        "text": "Add the rinsed rice and stir for 2 minutes so every grain is coated in fat.",
                        "tip": "Toasting seals the grain surface and keeps the rice separate."
                    },
                    {
                        "step": 4,
                        "text": "Add 2¼ cups hot chicken broth, salt, MSG, and pandan leaf. Bring to a simmer, cover, and cook 15 minutes on very low heat.",
                        "tip": "The broth should taste slightly salty before cooking — rice absorbs seasoning."
                    },
                    {
                        "step": 5,
                        "text": "Turn off heat and rest 10 minutes covered. Fluff gently with chopsticks.",
                        "tip": "Chopsticks separate grains without crushing them."
                    }
                ],
                "prep_time_minutes": 10,
                "cook_time_minutes": 18,
                "yield_description": None
            },
            {
                "title": "Hainanese Chili Sauce",
                "description": "Bright, spicy, and slightly savory.",
                "ingredients": [
                    {
                        "item": "red Fresno chilies",
                        "amount": "4",
                        "unit": "",
                        "group": None
                    },
                    {
                        "item": "Thai bird chili (optional)",
                        "amount": "1",
                        "unit": "",
                        "group": None
                    },
                    {
                        "item": "garlic cloves",
                        "amount": "4",
                        "unit": "",
                        "group": None
                    },
                    {
                        "item": "ginger",
                        "amount": "30",
                        "unit": "g",
                        "group": None
                    },
                    {
                        "item": "galangal",
                        "amount": "5",
                        "unit": "g",
                        "group": None
                    },
                    {
                        "item": "salt",
                        "amount": "0.5",
                        "unit": "tsp",
                        "group": None
                    },
                    {
                        "item": "sugar",
                        "amount": "1",
                        "unit": "tsp",
                        "group": None
                    },
                    {
                        "item": "MSG",
                        "amount": "0.25",
                        "unit": "tsp",
                        "group": None
                    },
                    {
                        "item": "light soy sauce",
                        "amount": "1.5",
                        "unit": "tbsp",
                        "group": None
                    },
                    {
                        "item": "chicken fat",
                        "amount": "2",
                        "unit": "tbsp",
                        "group": None
                    },
                    {
                        "item": "chicken broth",
                        "amount": "1–3",
                        "unit": "tbsp",
                        "group": None
                    }
                ],
                "prep_steps": [],
                "instructions": [
                    {
                        "step": 1,
                        "text": "Blend chilies, garlic, ginger, and galangal until coarse. Season with salt, sugar, MSG, and soy sauce.",
                        "tip": None
                    },
                    {
                        "step": 2,
                        "text": "Heat chicken fat until hot, then bloom the blended aromatics in the oil for 30 seconds. Stir in chicken broth to reach desired consistency.",
                        "tip": "Too long in oil dulls the chili aroma — 30 seconds is enough."
                    }
                ],
                "prep_time_minutes": None,
                "cook_time_minutes": None,
                "yield_description": "About ½–¾ cup"
            },
            {
                "title": "Ginger Scallion Sauce",
                "description": "Warm, aromatic, and deeply savory.",
                "ingredients": [
                    {
                        "item": "ginger, minced",
                        "amount": "80",
                        "unit": "g",
                        "group": None
                    },
                    {
                        "item": "scallions, sliced",
                        "amount": "2",
                        "unit": "",
                        "group": None
                    },
                    {
                        "item": "salt",
                        "amount": "0.5",
                        "unit": "tsp",
                        "group": None
                    },
                    {
                        "item": "sugar",
                        "amount": "0.25",
                        "unit": "tsp",
                        "group": None
                    },
                    {
                        "item": "MSG",
                        "amount": "0.25",
                        "unit": "tsp",
                        "group": None
                    },
                    {
                        "item": "chicken fat",
                        "amount": "3",
                        "unit": "tbsp",
                        "group": None
                    },
                    {
                        "item": "sesame oil",
                        "amount": "1",
                        "unit": "tsp",
                        "group": None
                    }
                ],
                "prep_steps": [],
                "instructions": [
                    {
                        "step": 1,
                        "text": "Combine minced ginger and sliced scallions in a heatproof bowl. Season with salt, sugar, and MSG.",
                        "tip": None
                    },
                    {
                        "step": 2,
                        "text": "Heat chicken fat and sesame oil until very hot. Pour the hot oil over the seasoned ginger mixture and stir.",
                        "tip": "Pouring hot oil over the ginger releases aroma while preventing the bitterness that comes from frying it directly."
                    }
                ],
                "prep_time_minutes": None,
                "cook_time_minutes": None,
                "yield_description": "About ½ cup"
            }
        ],
        "receipt_urls": [],
        "labels": [
            "chinese",
            "singaporean",
            "malaysian",
            "chicken",
            "rice",
            "poultry"
        ],
        "secrets": [],
        "sous_chef_notes": None
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


CATEGORIES = [
    "breakfast",
    "dessert",
    "italian",
    "japanese",
    "make-ahead",
    "noodles",
    "pasta",
    "pork",
    "quick",
    "seafood",
    "snack",
    "soup",
    "vegan",
    "vegetarian",
]

HOME_PAGE = {
    "hero_title": "Made for Seconds",
    "hero_subtitle": "The kitchen's a mess. The food's good.",
}

ABOUT_PAGE = {
    "heading": "About MadeForSeconds",
    "body": (
        "MadeForSeconds is where I keep and share the recipes I cook.\n\n"
        "It started as a place to organize my own recipes so they didn't get lost in random notes, "
        "screenshots, and half-written documents. Eventually it turned into this site.\n\n"
        "My background is a bit all over the place. I spent most of my early working years in the food "
        "and service industry starting at 16, mostly serving and bartending, with some time around kitchens "
        "as well. Restaurants teach you a lot about food, but they also teach speed, repetition, and how to "
        "handle chaos while people are hungry.\n\n"
        "In my mid-20s I moved into software engineering and spent the next four years building applications. "
        "More recently I've been moving deeper into cloud infrastructure.\n\n"
        "This project sits somewhere in the overlap of those worlds. It's a place for recipes I want to keep "
        "cooking and also a small technical playground where I can build something real.\n\n"
        "The food here doesn't stick to one cuisine or style. Some recipes are quick things to make on a "
        "random night. Others take time. If it tastes good and I want to make it again, it gets written down here.\n\n"
        "No long life stories before the recipe. Just ingredients, steps, and food that works."
    ),
    "callout_title": "Why \"MadeForSeconds\"?",
    "callout_body": "Because the best compliment a dish can get is someone going back for another plate.",
    "follow_heading": "Follow the Journey",
    "thank_you_message": "Thank you to everyone who has supported this site. You help keep it going.",
}


# Sample ingredient profiles for the Sous Chef's knowledge base — the shape of
# models.IngredientProfileIn, seeded so scripts/eval_sous_chef.py's profile
# cases (profile-jowl-vs-belly, knowledge-belacan-off-page, profiles-cached)
# run locally. "slug" is what generate_slug(name) produces; tests/test_seed.py
# checks that so seed.py needs no app import (the staging-seed job runs it
# without the app's environment).
INGREDIENT_PROFILES = [
    {
        "slug": "pork-belly",
        "name": "pork belly",
        "aliases": ["belly", "samgyeopsal", "liempo"],
        "what_it_is": (
            "The fatty slab from the underside of the pig: layers of fat and meat with the skin on top. "
            "It is what the chashu in this ramen is rolled from, and what samgyeopsal and lechon kawali are built on."
        ),
        "role": "Fat and richness. The layers render slowly and baste the meat from inside, so a long braise turns it silky rather than dry.",
        "substitutions": (
            "Pork shoulder works for a braise but is leaner and firmer: expect a drier, shreddier result. "
            "Pork jowl goes the other way, fattier and richer than belly, so trim less and skim more. "
            "Bacon does not work here; it is cured and smoked."
        ),
        "buying": "One skin-on slab with even, straight layers of fat and meat, not a thin, wavy end piece. Asian grocers sell it in the right shape for rolling.",
        "storage": "Two days raw in the fridge, well wrapped. Braised belly keeps four days and slices cleanly once chilled overnight.",
        "mistakes": "Slicing it warm (it shreds; chill it first), and rendering over too high a heat so the outside scorches before the fat gives.",
        "allergens": "",
    },
    {
        "slug": "pork-jowl",
        "name": "pork jowl",
        "aliases": ["jowl", "pork cheek", "hangjeongsal", "guanciale cut"],
        "what_it_is": (
            "The cheek: a small cut with a higher fat-to-meat ratio than belly, marbled all the way through "
            "rather than in layers. Cured, it becomes guanciale."
        ),
        "role": "Fat, more of it than belly. It renders into a richer, silkier braise and the meat stays moist even when pushed.",
        "substitutions": (
            "It stands in for pork belly in chashu and braises: expect more rendered fat, so trim less before and skim more after. "
            "It is fattier than belly, never leaner. Belly stands in for jowl the other way, slightly leaner."
        ),
        "buying": "Sold as a skin-on flap at Korean and Chinese butchers, often labelled hangjeongsal or pork cheek; look for firm white fat.",
        "storage": "Two days raw in the fridge, well wrapped; freezes well for three months.",
        "mistakes": "Treating it like a lean cut and trimming the fat away; the fat is the point. And slicing it thick for a sear: it wants thin slices or a long braise.",
        "allergens": "",
    },
    {
        "slug": "belacan",
        "name": "belacan",
        "aliases": ["shrimp paste", "terasi", "kapi"],
        "what_it_is": (
            "Malaysian fermented shrimp paste, sold as a dense dark block. Pungent raw, deeply savoury once toasted; "
            "the backbone of sambal belacan and the sambal on nasi lemak."
        ),
        "role": "Umami and salt. A small toasted piece gives a whole sambal or stir-fry its savoury depth.",
        "substitutions": "Thai kapi and Indonesian terasi are the same thing under other names. Fish sauce gives salt and some funk but not the body; miso is not a substitute.",
        "buying": "A firm, dry block, dark brown to purple, from any Southeast Asian grocer. Avoid soft, crumbly or greyish blocks.",
        "storage": "Wrapped twice and kept in the fridge it lasts a year. It smells, so seal it in a jar.",
        "mistakes": "Using it raw: toast a slice in a dry pan or in foil until fragrant first. And using too much; start with a thumbnail-sized piece.",
        "allergens": "Shellfish (shrimp).",
    },
]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", default="madefor-seconds-local", help="GCP project id (default: the local emulator project)")
    parser.add_argument("--force", action="store_true", help="Clear existing recipes/subscribers/expenses/ingredient profiles and reseed")
    args = parser.parse_args()

    force = args.force
    db = Client(project=args.project)
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
        print("Clearing existing ingredient profiles...")
        for doc in db.collection("ingredients").stream():
            doc.reference.delete()

    now = datetime.now(timezone.utc)
    # One second apart, newest first, so RECIPES' own order IS the order the
    # site shows. Recipe lists sort by created_at DESCENDING, and with equal
    # timestamps Firestore falls back to document id — which is random per
    # seed run, so "the first recipe" used to be a coin flip. That cost a
    # ~1-in-5 E2E flake (the multi-component recipe renders no top-level
    # Instructions heading) and hid a real cursor page-skip, since start_after
    # keyed on created_at alone cannot separate tied documents. Seconds, not
    # microseconds, so the gap survives any timestamp rounding.
    for offset, recipe in enumerate(RECIPES):
        stamp = now - timedelta(seconds=offset)
        recipe["created_at"] = stamp
        recipe["updated_at"] = stamp
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

    # Seed sample ingredient profiles (ingredients/{slug}). updated_via must be
    # a value models.IngredientProfile accepts, so "admin", not "seed".
    # Unreachable on an already-seeded project because of the early return
    # above — see the module docstring.
    existing_profiles = list(db.collection("ingredients").limit(1).stream())
    if not existing_profiles or force:
        for profile in INGREDIENT_PROFILES:
            data = {k: v for k, v in profile.items() if k != "slug"}
            data.update({"created_at": now, "updated_at": now, "updated_via": "admin"})
            db.collection("ingredients").document(profile["slug"]).set(data)
            print(f"  Created ingredient profile: {profile['name']}")
        print(f"Seeded {len(INGREDIENT_PROFILES)} ingredient profiles.")

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

    # Seed config/categories (idempotent — only writes if missing or --force)
    cat_doc = db.collection("config").document("categories").get()
    if not cat_doc.exists or force:
        db.collection("config").document("categories").set({"list": CATEGORIES})
        print(f"Seeded {len(CATEGORIES)} categories into config/categories.")
    else:
        print("config/categories already exists, skipping.")

    # Seed page content (idempotent)
    for page_id, content in [("home", HOME_PAGE), ("about", ABOUT_PAGE)]:
        page_doc = db.collection("pages").document(page_id).get()
        if not page_doc.exists or force:
            db.collection("pages").document(page_id).set(content)
            print(f"Seeded pages/{page_id}.")
        else:
            print(f"pages/{page_id} already exists, skipping.")


if __name__ == "__main__":
    main()
