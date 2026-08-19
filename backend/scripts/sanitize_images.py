#!/usr/bin/env python3
"""One-off backfill: strip metadata and set caching on existing public images.

The images bucket granted allUsers roles/storage.objectViewer, which carries
storage.objects.list — so every object was anonymously enumerable, including
images belonging to unpublished drafts. Fixing the IAM binding stops discovery,
but it does nothing about objects already published: the camera originals still
carry a GPS IFD, and anything linked from a public recipe stays readable.

This rewrites those objects in place. It imports the same strip helper the
upload path uses — a second, divergent implementation is how this bug comes
back.

Dry run by default:

    python scripts/sanitize_images.py --bucket made-for-seconds-images
    python scripts/sanitize_images.py --bucket made-for-seconds-images --apply

Needs Application Default Credentials with write access to the bucket:

    gcloud auth application-default login
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from google.cloud import storage  # noqa: E402

from app.services.uploads import (  # noqa: E402
    PUBLIC_IMAGE_CACHE_CONTROL,
    MetadataStripError,
    sniff_content_type,
    strip_image_metadata,
)

# Objects are never deleted by this script. The set of blobs not referenced by a
# published recipe cannot be computed from here — unpublished drafts hold
# references too, and they are not visible without admin credentials. Deciding
# what is genuinely orphaned is a separate job with a separate blast radius.
STRIPPABLE = {"image/jpeg", "image/png", "image/webp"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bucket", required=True, help="GCS bucket name")
    parser.add_argument(
        "--project",
        default=os.environ.get("GCP_PROJECT_ID"),
        help=(
            "GCP project (default: $GCP_PROJECT_ID). Required unless gcloud has a "
            "default project configured — it often does not."
        ),
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually rewrite objects. Without this, only reports what would change.",
    )
    parser.add_argument(
        "--backup-dir",
        default="tmp/image-backups",
        help=(
            "Where to save originals before rewriting (default: tmp/image-backups). "
            "These files still contain the GPS being removed — tmp/ is gitignored; "
            "keep them out of the repo."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    # Blob names come from uploaded filenames and can hold characters the
    # console's default encoding cannot represent — a macOS screenshot carries a
    # narrow no-break space (U+202F), which is enough to kill the run on a
    # cp1252 Windows terminal partway through.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    client = storage.Client(project=args.project)

    backup_dir = Path(args.backup_dir)
    if args.apply:
        backup_dir.mkdir(parents=True, exist_ok=True)

    changed = skipped = failed = 0

    for blob in client.list_blobs(args.bucket):
        data = blob.download_as_bytes()
        content_type = sniff_content_type(data)

        if content_type not in STRIPPABLE:
            # Not a format this can rewrite. HEIC lands here; it is not even an
            # allowed recipe-image type, so its presence is worth reporting
            # rather than silently passing over.
            print(f"  SKIP  {blob.name}  (unsupported type: {content_type})")
            skipped += 1
            continue

        try:
            cleaned = strip_image_metadata(data, content_type)
        except MetadataStripError as exc:
            print(f"  FAIL  {blob.name}  ({exc})")
            failed += 1
            continue

        needs_strip = cleaned != data
        needs_cache = blob.cache_control != PUBLIC_IMAGE_CACHE_CONTROL
        if not needs_strip and not needs_cache:
            skipped += 1
            continue

        reasons = []
        if needs_strip:
            reasons.append(f"-{len(data) - len(cleaned):,}B metadata")
        if needs_cache:
            reasons.append("cache-control")
        label = "WRITE" if args.apply else "WOULD"
        print(f"  {label} {blob.name}  ({', '.join(reasons)})")

        if args.apply:
            # Save the original first. The bucket has 7-day soft delete, but
            # recovering 20 objects through it is far more work than a local copy.
            if needs_strip:
                (backup_dir / blob.name.replace("/", "_")).write_bytes(data)
            blob.cache_control = PUBLIC_IMAGE_CACHE_CONTROL
            blob.upload_from_string(cleaned, content_type=content_type)

        changed += 1

    print()
    verb = "rewritten" if args.apply else "would be rewritten"
    print(f"{changed} {verb} · {skipped} already clean or unsupported · {failed} failed")
    if not args.apply and changed:
        print("Dry run — re-run with --apply to make these changes.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
