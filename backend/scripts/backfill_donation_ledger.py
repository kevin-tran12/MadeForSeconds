#!/usr/bin/env python3
"""Backfill donation_transactions for one-time donations that predate the
immutable per-payment ledger (services/donation_ledger.py).

Before that ledger existed, every completed donation Checkout Session was
only ever recorded as a consolidated aggregate on the `donations` collection
(subscriptions.py::_apply_donation_checkout) — a repeat donor's total
accumulated on one doc, and each new payment overwrote the previous one's
`stripe_session_id`. Live traffic since the ledger shipped already gets a
donation_transactions row written inside the webhook's own transaction; this
script is the one-time catch-up for everything that happened before that.

Walks every completed, one-time (mode=payment) Stripe Checkout Session and
writes the same shape of record the live webhook path writes — via the same
services/donation_ledger.write_donation_record function, not a second,
divergent implementation of the same write. Keyed by Checkout Session id,
exactly like the live path, so a session the webhook already ledgered (or
that a previous run of this script already wrote) is skipped, not
duplicated: this script is safe to interrupt and re-run from the start.

DRY RUN BY DEFAULT. Pass --live to actually write. Even then, this script
only ever creates donation_transactions rows for sessions that don't already
have one — it never touches the `donations` aggregate, never modifies
Stripe, and never overwrites an existing ledger row.

    cd backend
    python scripts/backfill_donation_ledger.py --project made-for-seconds
        # dry run: prints what would be written, writes nothing

    python scripts/backfill_donation_ledger.py --project made-for-seconds --live
        # writes for real

Requires STRIPE_SECRET_KEY in the environment (the same variable the app
itself reads) and Firestore write access to the target project (ADC, same
as any other operator-run script in this directory).
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import stripe  # noqa: E402
from google.cloud.firestore import transactional  # noqa: E402

from app import config  # noqa: E402
from app.firestore import get_db  # noqa: E402
from app.routes.subscriptions import _fetch_donation_fee_net  # noqa: E402
from app.services import donation_ledger  # noqa: E402


@transactional
def _write_one(transaction, db, **record_kwargs) -> None:
    """One-document transaction per backfilled session — reuses the exact
    write the live webhook path uses (donation_ledger.write_donation_record),
    just wrapped here instead of inside the webhook's larger transaction."""
    donation_ledger.write_donation_record(transaction, db, **record_kwargs)


def _session_created_at(session) -> datetime | None:
    created = session.get("created")
    return datetime.fromtimestamp(created, tz=timezone.utc) if created else None


def run(args: argparse.Namespace) -> int:
    config.settings.gcp_project_id = args.project
    stripe.api_key = config.settings.stripe_secret_key
    if not stripe.api_key:
        print("STRIPE_SECRET_KEY is not set — nothing to backfill from.", file=sys.stderr)
        return 1

    db = get_db()
    ledger_collection = db.collection(donation_ledger.COLLECTION)

    list_kwargs = {"mode": "payment", "status": "complete", "limit": 100}
    if args.after:
        list_kwargs["created"] = {"gte": args.after}

    scanned = already_present = written = would_write = errors = 0

    for session in stripe.checkout.Session.list(**list_kwargs).auto_paging_iter():
        if args.limit and scanned >= args.limit:
            break
        scanned += 1

        session_id = session.get("id")
        if ledger_collection.document(session_id).get().exists:
            already_present += 1
            continue

        email = ((session.get("customer_details") or {}).get("email") or "").lower()
        amount_total = session.get("amount_total", 0)
        payment_intent_id = session.get("payment_intent")
        fee_cents, net_cents = _fetch_donation_fee_net(payment_intent_id)

        record_kwargs = dict(
            session_id=session_id,
            email=email or "anonymous",
            gross_cents=amount_total,
            currency=session.get("currency") or "usd",
            fee_cents=fee_cents,
            net_cents=net_cents,
            payment_intent_id=payment_intent_id,
            stripe_created_at=_session_created_at(session),
        )

        if not args.live:
            would_write += 1
            print(
                f"  [DRY RUN] would write {session_id}: "
                f"gross={amount_total}{session.get('currency', 'usd')} "
                f"fee={fee_cents} net={net_cents} email={'<redacted>' if email else 'anonymous'}"
            )
            continue

        try:
            _write_one(db.transaction(), db, now=datetime.now(timezone.utc), **record_kwargs)
            written += 1
            print(f"  [WRITTEN] {session_id}")
        except Exception as exc:
            errors += 1
            print(f"  [ERROR] {session_id}: {exc}", file=sys.stderr)

    print()
    print(f"Scanned:         {scanned}")
    print(f"Already present: {already_present}")
    if args.live:
        print(f"Written:         {written}")
        print(f"Errors:          {errors}")
    else:
        print(f"Would write:     {would_write}")
        print("\nThis was a DRY RUN — nothing was written. Pass --live to write for real.")

    return 1 if errors else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", required=True, help="GCP project id (Firestore target)")
    parser.add_argument(
        "--live", action="store_true", help="Actually write records. Without this flag, nothing is written."
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Stop after scanning this many sessions (for a small trial run)"
    )
    parser.add_argument(
        "--after", type=int, default=None, help="Only consider sessions created at/after this Unix timestamp"
    )
    return parser.parse_args()


if __name__ == "__main__":
    sys.exit(run(parse_args()))
