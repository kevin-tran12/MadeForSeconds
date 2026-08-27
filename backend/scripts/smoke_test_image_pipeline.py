#!/usr/bin/env python3
"""Post-deploy smoke test for the recipe-image upload pipeline.

Unit tests mock every GCS call — they prove the application logic is
correct, but they cannot catch a wrong deployed IAM grant, a missing env var,
a signed-URL header mismatch, an unexpected bucket policy, or promotion
behaving differently against real GCS than against a mock. This script
exercises the real path end to end against the real target project.

Run it after any `terraform apply` or backend deploy that touches image
uploads, the staging bucket, or their IAM — before normal traffic starts
relying on the new revision. It is NOT part of CI, and it is a manual,
operator-only gate: it needs real credentials with write access to the
target project's Firestore and the images/staging buckets, and it is not
something to run unattended against production on every push.

    gcloud auth application-default login \\
        --impersonate-service-account=<backend-sa-email>
    cd backend
    python scripts/smoke_test_image_pipeline.py \\
        --project made-for-seconds \\
        --backend-url "$(terraform -chdir=../terraform output -raw cloud_run_url)"

Impersonating the backend service account (rather than using the operator's
own, typically broader, ADC) means the GCS/Firestore calls below run under
the SAME IAM the deployed revision actually has — a grant missing from the
backend SA specifically will fail here even if the operator's own account
would have papered over it. This requires the operator to hold
roles/iam.serviceAccountTokenCreator on the backend SA (granted via
terraform/modules/security/service_accounts.tf's backend_operator_impersonation
resource).

What this script does NOT prove: it calls application code in-process, not
through the deployed HTTP surface. It does not verify that a real MCP client
can authenticate through /mcp (interactive WorkOS OAuth) or that the admin
web UI can authenticate through /api/admin/* (Firebase ID token) — neither
has a non-interactive, scriptable auth path today, and building one is a
separate, larger effort. The --backend-url health check below covers "did
the deployed revision start with valid config", not "can a real client log
in to it".

Steps:
  0. GET {backend_url}/api/health — confirms the deployed Cloud Run revision
     actually started. validate_production_settings() runs at import time,
     before the FastAPI app object exists, so a bad/missing env var
     crash-loops the revision and it never receives traffic; a passing
     health check is direct evidence the live revision has valid config.
  1. Request a signed staging-bucket PUT URL — exercises signed_put_url and
     the backend SA's IAM on the staging bucket.
  2. PUT a JPEG carrying GPS EXIF to it — exercises the signed URL itself.
  3. Confirm the staged object is NOT anonymously readable — staging bucket
     IAM / public_access_prevention.
  4. Attach it to a disposable recipe via the real create_recipe() — this is
     what triggers promotion (sanitize_public_image_blob ->
     _promote_staged_image), not a call into that internal function directly.
  5. Confirm the promoted PUBLIC object has no GPS EXIF and carries the
     immutable Cache-Control header.
  6. Confirm the Firestore recipe document holds the promoted public URL.
  7. Confirm the staged copy was deleted after promotion.
  8. Reject-path check: stage a non-image payload and confirm create_recipe
     raises rather than silently promoting it — and that no Firestore
     document is left behind by the aborted attempt.

Cleans up the disposable recipe and every object this run could have
created — in both buckets, under both generated blob names — in a `finally`,
whether the run passed or failed at any step. Cleanup is idempotent and
tolerates objects that were never created or already deleted; anything it
could not remove is reported at the end rather than silently dropped.
"""

from __future__ import annotations

import argparse
import io
import sys
import uuid
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402
from google.cloud.exceptions import NotFound  # noqa: E402
from PIL import Image  # noqa: E402

from app import config  # noqa: E402
from app.models import RecipeCreate  # noqa: E402
from app.services import recipes as recipe_service  # noqa: E402
from app.services import uploads  # noqa: E402


def _gps_jpeg() -> bytes:
    """A real, decodable JPEG carrying a GPS IFD — same shape as a phone photo."""
    image = Image.new("RGB", (8, 8), (120, 80, 40))
    exif = image.getexif()
    gps = exif.get_ifd(0x8825)
    gps[1], gps[2] = "N", (Fraction(33), Fraction(56), Fraction(1744, 100))
    gps[3], gps[4] = "W", (Fraction(83), Fraction(56), Fraction(4590, 100))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", exif=exif)
    return buffer.getvalue()


def _gps_tag_count(data: bytes) -> int:
    exif = Image.open(io.BytesIO(data)).getexif()
    return len(exif.get_ifd(0x8825)) if exif else 0


class SmokeTestFailure(Exception):
    pass


def _check(label: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}" + (f" — {detail}" if detail and not condition else ""))
    if not condition:
        raise SmokeTestFailure(f"{label}: {detail}")


def _cleanup_blob(bucket, blob_name: str, leftover: list[str]) -> None:
    """Best-effort delete, idempotent whether or not the object ever existed."""
    try:
        bucket.blob(blob_name).delete()
    except NotFound:
        pass
    except Exception as exc:
        leftover.append(f"{bucket.name}/{blob_name}: {exc}")


def run(args: argparse.Namespace) -> int:
    # Point the real app config at the target project rather than importing
    # under a mocked settings object — this script's whole point is proving
    # the actual deployed configuration works, so it must use it. is_dev is a
    # computed property (reads `environment`); it has no setter.
    config.settings.environment = "production"
    config.settings.gcp_project_id = args.project
    config.settings.gcs_bucket_name = args.images_bucket
    config.settings.gcs_staging_bucket_name = args.staging_bucket

    from google.cloud import firestore, storage

    storage_client = storage.Client(project=args.project)
    db = firestore.Client(project=args.project)

    recipe_id: str | None = None
    reject_recipe_id: str | None = None
    marker = uuid.uuid4().hex[:8]
    # Generated before `try` — pure local computation that can't fail, so
    # `finally` always has both names to sweep regardless of where the run
    # aborts.
    blob_name = f"{uuid.uuid4()}-smoketest.jpg"
    reject_blob_name = f"{uuid.uuid4()}-smoketest-reject.txt"

    try:
        print(f"Target: project={args.project} images={args.images_bucket} staging={args.staging_bucket}")

        # ── 0: the deployed revision is actually up with valid config ──────
        print("\n[0] Deployed revision health check")
        health_resp = httpx.get(f"{args.backend_url}/api/health", timeout=30.0)
        _check(
            "deployed revision responds healthy",
            health_resp.status_code == 200 and health_resp.json().get("status") == "ok",
            f"HTTP {health_resp.status_code}: {health_resp.text}",
        )

        # ── 1–3: signed PUT into staging, confirm it isn't public ──────────
        print("\n[1-3] Signed upload into staging")
        signed = uploads.signed_put_url(args.staging_bucket, blob_name, "image/jpeg")
        payload = _gps_jpeg()
        put_resp = httpx.put(
            signed["upload_url"],
            content=payload,
            headers=signed["required_headers"],
            timeout=30.0,
        )
        _check("signed PUT succeeds", put_resp.status_code in (200, 201), f"HTTP {put_resp.status_code}")

        anon_get = httpx.get(f"https://storage.googleapis.com/{args.staging_bucket}/{blob_name}")
        _check(
            "staged object is not anonymously readable",
            anon_get.status_code in (401, 403),
            f"HTTP {anon_get.status_code}",
        )

        # ── 4: attach via the real create_recipe — triggers promotion ──────
        print("\n[4] Attaching via create_recipe (triggers promotion)")
        public_url = f"https://storage.googleapis.com/{args.images_bucket}/{blob_name}"
        recipe = recipe_service.create_recipe(
            db,
            RecipeCreate(title=f"SMOKE TEST {marker} — safe to delete", image_url=public_url),
            source="smoke-test",
        )
        recipe_id = recipe.id
        _check("create_recipe succeeded", True)

        # ── 5: promoted object is clean and cacheable ───────────────────────
        print("\n[5] Verifying the promoted public object")
        public_blob = storage_client.bucket(args.images_bucket).get_blob(blob_name)
        _check("promoted object exists in the public bucket", public_blob is not None)
        # Read cache_control BEFORE downloading — an authenticated media
        # download responds with its own "Cache-Control: no-cache, no-store"
        # header, and the client library writes those response headers back
        # onto the blob object. Reading it after download() reports what the
        # download response said, not what is actually stored on the object.
        stored_cache_control = public_blob.cache_control
        promoted_bytes = public_blob.download_as_bytes()
        _check("GPS metadata removed", _gps_tag_count(promoted_bytes) == 0, "GPS IFD still present")
        _check(
            "Cache-Control is set for long-lived immutable caching",
            stored_cache_control == uploads.PUBLIC_IMAGE_CACHE_CONTROL,
            f"got {stored_cache_control!r}",
        )
        anon_public = httpx.get(public_url)
        _check("promoted object is anonymously readable", anon_public.status_code == 200)

        # ── 6: Firestore holds the promoted URL ─────────────────────────────
        print("\n[6] Verifying Firestore")
        stored = db.collection("recipes").document(recipe_id).get().to_dict()
        _check("Firestore image_url matches the promoted public URL", stored.get("image_url") == public_url)

        # ── 7: staged copy is gone ───────────────────────────────────────────
        print("\n[7] Verifying the staged copy was cleaned up")
        staged_still_there = storage_client.bucket(args.staging_bucket).get_blob(blob_name)
        _check("staged copy deleted after promotion", staged_still_there is None)

        # ── 8: reject path — non-image payload must not promote ────────────
        print("\n[8] Reject path: non-image content must not be promoted")
        reject_signed = uploads.signed_put_url(args.staging_bucket, reject_blob_name, "image/jpeg")
        httpx.put(
            reject_signed["upload_url"],
            content=b"not an image, just text pretending to be one",
            headers=reject_signed["required_headers"],
            timeout=30.0,
        )
        reject_public_url = f"https://storage.googleapis.com/{args.images_bucket}/{reject_blob_name}"
        try:
            bad_recipe = recipe_service.create_recipe(
                db,
                RecipeCreate(title=f"SMOKE TEST {marker} REJECT — should not exist", image_url=reject_public_url),
                source="smoke-test",
            )
            reject_recipe_id = bad_recipe.id
            _check("non-image content was rejected", False, "create_recipe did not raise")
        except uploads.ImageSanitizationError:
            _check("non-image content raised ImageSanitizationError", True)
        found = list(db.collection("recipes").where("title", "==", f"SMOKE TEST {marker} REJECT — should not exist").stream())
        _check("no Firestore document left behind by the rejected attempt", len(found) == 0)
        promoted_reject = storage_client.bucket(args.images_bucket).get_blob(reject_blob_name)
        _check("rejected content was not promoted to the public bucket", promoted_reject is None)

        print("\nAll checks passed.")
        return 0

    except SmokeTestFailure as exc:
        print(f"\nSMOKE TEST FAILED: {exc}")
        return 1
    finally:
        print("\nCleaning up...")
        # Firestore documents first — delete_recipe is the only thing that
        # removes them, and it already best-effort-deletes the promoted
        # image itself (delete_gcs_blob swallows its own errors).
        if recipe_id:
            try:
                recipe_service.delete_recipe(db, recipe_id, source="smoke-test")
                print(f"  deleted disposable recipe {recipe_id} (and its promoted image)")
            except Exception as exc:
                print(f"  WARNING: could not clean up recipe {recipe_id}: {exc}")
        if reject_recipe_id:
            try:
                recipe_service.delete_recipe(db, reject_recipe_id, source="smoke-test")
                print(f"  deleted disposable reject-path recipe {reject_recipe_id}")
            except Exception as exc:
                print(f"  WARNING: could not clean up recipe {reject_recipe_id}: {exc}")

        # Unconditional sweep of every object this run could have created, in
        # both buckets, under both blob names — covers every failure point
        # above: a crash before create_recipe() (staged object, never
        # attached), or promotion succeeding but the Firestore write inside
        # create_recipe() failing afterward (public object, no recipe to
        # find it by). Idempotent: an already-deleted or never-created blob
        # just hits the NotFound branch.
        images_bucket = storage_client.bucket(args.images_bucket)
        staging_bucket = storage_client.bucket(args.staging_bucket)
        leftover: list[str] = []
        _cleanup_blob(staging_bucket, blob_name, leftover)
        _cleanup_blob(images_bucket, blob_name, leftover)
        _cleanup_blob(staging_bucket, reject_blob_name, leftover)
        _cleanup_blob(images_bucket, reject_blob_name, leftover)
        if leftover:
            print("  WARNING: could not remove the following objects — check and delete manually:")
            for item in leftover:
                print(f"    {item}")
        else:
            print("  no leftover objects in staging or public buckets")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", required=True, help="GCP project id")
    parser.add_argument(
        "--backend-url",
        required=True,
        help="Deployed Cloud Run URL, e.g. $(terraform -chdir=../terraform output -raw cloud_run_url)",
    )
    parser.add_argument("--images-bucket", default=None, help="Public images bucket (default: {project}-images)")
    parser.add_argument("--staging-bucket", default=None, help="Staging bucket (default: {project}-images-staging)")
    args = parser.parse_args()
    args.backend_url = args.backend_url.rstrip("/")
    args.images_bucket = args.images_bucket or f"{args.project}-images"
    args.staging_bucket = args.staging_bucket or f"{args.project}-images-staging"
    return args


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
