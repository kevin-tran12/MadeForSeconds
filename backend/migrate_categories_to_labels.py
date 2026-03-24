#!/usr/bin/env python3
"""
Migrate recipe categories → labels.

Recipes historically stored free-form tags (e.g. "chinese", "beef") in the
`categories` field. Categories are now admin-controlled from
config/categories.list. This script moves any value that is NOT in the
allowed list from `categories` into `labels`.

Usage:
  # Preview changes without writing:
  python migrate_categories_to_labels.py --dry-run

  # Against the local Firestore emulator:
  FIRESTORE_EMULATOR_HOST=firestore:8080 python migrate_categories_to_labels.py --dry-run
  FIRESTORE_EMULATOR_HOST=firestore:8080 python migrate_categories_to_labels.py

  # Against production (uses Application Default Credentials):
  python migrate_categories_to_labels.py --dry-run
  python migrate_categories_to_labels.py

Run inside the backend container:
  docker compose exec backend bash -c "cd /app && FIRESTORE_EMULATOR_HOST=firestore:8080 python migrate_categories_to_labels.py --dry-run"
"""
import argparse
import os

from google.cloud import firestore


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate recipe categories to labels")
    parser.add_argument("--dry-run", action="store_true", help="Print changes without writing")
    args = parser.parse_args()

    project = os.environ.get("GCP_PROJECT_ID") or os.environ.get("GOOGLE_CLOUD_PROJECT")
    db = firestore.Client(project=project) if project else firestore.Client()

    # Load the admin-configured allowed category list
    cat_doc = db.collection("config").document("categories").get()
    allowed: set[str] = set(cat_doc.to_dict().get("list", [])) if cat_doc.exists else set()
    print(f"Allowed categories ({len(allowed)}): {sorted(allowed)}\n")
    if not allowed:
        print("WARNING: No allowed categories found. Every category value will move to labels.")
        print("         Set up your categories first if that is not intended.\n")

    batch = db.batch()
    batch_size = 0
    updated = 0
    skipped = 0

    for doc in db.collection("recipes").stream():
        data = doc.to_dict()
        current_cats: list[str] = data.get("categories", [])
        current_labels: list[str] = data.get("labels", [])

        to_move = [c for c in current_cats if c not in allowed]
        if not to_move:
            skipped += 1
            continue

        new_cats = [c for c in current_cats if c in allowed]

        # Merge into labels — deduplicate while preserving order
        seen: dict[str, None] = dict.fromkeys(current_labels)
        for val in to_move:
            seen.setdefault(val, None)
        new_labels = list(seen)

        title = data.get("title", doc.id)
        print(f"  {title!r}")
        print(f"    categories: {current_cats!r}")
        print(f"             → {new_cats!r}")
        print(f"    labels:     {current_labels!r}")
        print(f"             → {new_labels!r}\n")

        if not args.dry_run:
            batch.update(doc.reference, {"categories": new_cats, "labels": new_labels})
            batch_size += 1
            # Firestore batch limit is 500 writes
            if batch_size >= 500:
                batch.commit()
                batch = db.batch()
                batch_size = 0

        updated += 1

    if not args.dry_run and batch_size > 0:
        batch.commit()

    print("─" * 50)
    verb = "would be updated" if args.dry_run else "updated"
    prefix = "DRY RUN — " if args.dry_run else ""
    print(f"{prefix}{updated} recipe(s) {verb}, {skipped} already clean.")


if __name__ == "__main__":
    main()
