#!/usr/bin/env python3
"""Backfill the `public_listing` field on subscriber/donation docs that
predate it (services/donation_ledger.py's PR sibling for the supporter list).

The public supporter endpoint (subscriptions.py::list_supporters) used to
stream every `subscribers` and `donations` document and filter/sort in
Python. `public_listing` — a denormalised boolean equal to
`bool(display_name) and name_enabled` — replaces that with a bounded,
indexed query (terraform/modules/storage/firestore.tf), computed and kept
current at every write that can change either input field
(subscriptions.py::setup_profile, the webhook's two checkout-apply paths,
admin.py::toggle_name).

Every document written *after* that shipped already carries a correct
`public_listing`. Documents that predate it have no such field at all — and
a missing field never matches a Firestore equality filter, so without this
backfill those supporters would just silently stop appearing in the public
list once the read path switches over to the indexed query. This script is
the one-time catch-up: it recomputes `public_listing` from each document's
current display_name/name_enabled and writes it, but only where the stored
value is missing or wrong. Safe to interrupt and re-run — recomputing from
current truth is deterministic, so re-running it is a no-op wherever the
last run already got it right.

DRY RUN BY DEFAULT. Pass --live to actually write.

    cd backend
    python scripts/backfill_supporter_public_listing.py --project made-for-seconds
    python scripts/backfill_supporter_public_listing.py --project made-for-seconds --live
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import config  # noqa: E402
from app.firestore import get_db  # noqa: E402
from app.routes.subscriptions import compute_public_listing, _public_listing_for_status  # noqa: E402

COLLECTIONS = ("subscribers", "donations")


def _expected_public_listing(collection: str, data: dict) -> bool:
    """subscribers has a status lifecycle (active/past_due/canceled) that
    must also gate public_listing — see _public_listing_for_status's own
    docstring — donations has no such field and was never filtered on one."""
    if collection == "subscribers":
        return _public_listing_for_status(data, data.get("status", ""))
    return compute_public_listing(data.get("display_name"), data.get("name_enabled", True))


def run(args: argparse.Namespace) -> int:
    config.settings.gcp_project_id = args.project
    db = get_db()

    scanned = correct = would_fix = fixed = errors = 0

    for collection in COLLECTIONS:
        for doc in db.collection(collection).stream():
            scanned += 1
            data = doc.to_dict() or {}
            expected = _expected_public_listing(collection, data)

            if data.get("public_listing") == expected:
                correct += 1
                continue

            if not args.live:
                would_fix += 1
                print(f"  [DRY RUN] would set {collection}/{doc.id}.public_listing = {expected}")
                continue

            try:
                doc.reference.update({"public_listing": expected})
                fixed += 1
                print(f"  [FIXED] {collection}/{doc.id} -> public_listing = {expected}")
            except Exception as exc:
                errors += 1
                print(f"  [ERROR] {collection}/{doc.id}: {exc}", file=sys.stderr)

    print()
    print(f"Scanned:         {scanned}")
    print(f"Already correct: {correct}")
    if args.live:
        print(f"Fixed:           {fixed}")
        print(f"Errors:          {errors}")
    else:
        print(f"Would fix:       {would_fix}")
        print("\nThis was a DRY RUN — nothing was written. Pass --live to write for real.")

    return 1 if errors else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", required=True, help="GCP project id (Firestore target)")
    parser.add_argument(
        "--live", action="store_true", help="Actually write records. Without this flag, nothing is written."
    )
    return parser.parse_args()


if __name__ == "__main__":
    sys.exit(run(parse_args()))
