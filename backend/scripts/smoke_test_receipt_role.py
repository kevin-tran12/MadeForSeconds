#!/usr/bin/env python3
"""Post-deploy smoke test for the receipts bucket's IAM role.

Unit tests mock every GCS call, so they cannot catch a wrong deployed IAM
grant. `smoke_test_image_pipeline.py` solves this for the images/staging
buckets by exercising the real path against the real buckets and cleaning up
afterward — but the receipts bucket carries a 7-year retention policy
(terraform/modules/storage/buckets.tf), so an object written there for a
test can never be deleted. This script instead creates a throwaway scratch
bucket with the SAME custom role bound that the real receipts bucket uses,
and runs the real receipt code paths against it as the impersonated backend
service account — never touching the real receipts bucket at all.

This is a real-GCS IAM integration test, not a full-stack receipt test: it
proves the deployed permission set is correct for the exact storage
operations the app performs. It does NOT exercise authenticated HTTP/MCP
transport (auth middleware, TOTP, WorkOS OAuth), FastAPI request/response
handling, or the Firestore expense-receipt association — every app function
below is called in-process, the same way smoke_test_image_pipeline.py calls
recipe_service.create_recipe() directly rather than through a real HTTP
request.

Run it after any change to the receipts bucket's IAM (Epic 2, story 2.2):

    cd backend
    python scripts/smoke_test_receipt_role.py --project made-for-seconds

Prerequisites — NOT fully covered by this repo's Terraform. The operator
needs:
  - roles/iam.serviceAccountTokenCreator on the backend SA, to impersonate
    it for the exercise phase. This one IS granted by Terraform
    (service_accounts.tf's backend_operator_impersonation).
  - storage.buckets.{create,delete,get,update,getIamPolicy,setIamPolicy} and
    storage.objects.{list,delete} on the project, for scratch-bucket
    lifecycle. Terraform does NOT grant these to the operator (only
    roles/storage.objectAdmin on the separate Terraform state bucket) — this
    script relies on the operator's own broader project-level access (e.g.
    Owner/Editor), which is standard for whoever runs `terraform apply`, but
    is a real gap if a narrower operator identity is ever introduced.

Unlike smoke_test_image_pipeline.py, this does NOT require the operator to
pre-authenticate with `gcloud auth application-default login
--impersonate-service-account=...` — the script builds impersonated
credentials for the exercise phase itself and uses the operator's own
ambient credentials, unimpersonated, for scratch-bucket setup/teardown — a
single invocation handles both.

Steps:
  0. (operator identity) Create a scratch bucket — soft-delete explicitly
     disabled (new buckets default to 7 days of it, which would leave the
     bucket recoverable-but-orphaned for a week even after a "successful"
     delete; confirmed live on an earlier run of this script) — and bind it
     the same custom role (--role-id, default mfsReceiptsUploader) the real
     receipts bucket uses, on the real backend SA.
  0b. Wait for the IAM grant to actually take effect. Cloud Storage documents
     access changes as eventually consistent (commonly ~1 minute, sometimes
     several), so exercising the role immediately after binding it risks a
     false-negative 403 that has nothing to do with whether the role is
     correct. Polls with bounded exponential backoff + jitter; a persistent
     denial past the deadline is a real failure, not swallowed.
  1. (impersonated as the backend SA) Direct SDK upload — calls the actual
     admin route function app.routes.expenses.upload_receipt() with a real
     UploadFile. Exercises storage.objects.create through the exact code
     path production uses.
  2. get_blob validation — calls app.mcp_server._resolve_receipt_url() on
     the URL step 1 returned. Exercises storage.objects.get and confirms
     the content-type round-trips correctly.
  3. Signed PUT — calls app.mcp_server.request_image_upload(kind="receipt")
     for a second object, then performs a real unauthenticated HTTP PUT to
     the returned signed URL (this is the request GCS actually checks IAM
     against — signed-URL generation itself does not touch object IAM).
  4. get_blob validation again, on the object step 3's PUT created — proves
     the signed-PUT path and the direct-upload path both leave a readable
     object.
  5. Signed GET + HTTP GET — calls app.services.uploads.signed_get_url() on
     the step-1 object, then performs a real HTTP GET against it and
     confirms the bytes match exactly what was uploaded.
  6. Negative checks, impersonated: list the bucket (must be denied — the
     custom role grants no storage.objects.list), and attempt to overwrite
     and delete an existing object (both must be denied).

Cleanup, as the operator (the impersonated identity cannot delete the
bucket — it has no storage.buckets.delete grant, by design): guarded by an
outer try/finally covering everything from bucket creation onward, so a
failure at any step (including the propagation wait) still triggers it.
Retries transient delete failures, then verifies the bucket is actually
gone rather than trusting a non-raising delete call. If cleanup cannot be
verified, the script exits non-zero even if every functional check passed —
a passing IAM test is not the point if it silently orphans cloud resources.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import random
import sys
import time
import uuid
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import google.auth  # noqa: E402
import google.cloud.storage as gcs_module  # noqa: E402
import httpx  # noqa: E402
from google.api_core.exceptions import Forbidden, NotFound  # noqa: E402
from google.auth import impersonated_credentials  # noqa: E402
from starlette.datastructures import UploadFile  # noqa: E402

from app import config, mcp_server  # noqa: E402
from app.routes import expenses  # noqa: E402
from app.services import uploads  # noqa: E402


class SmokeTestFailure(Exception):
    pass


def wait_until(
    check: Callable[[], bool],
    *,
    deadline_seconds: float = 120.0,
    initial_delay: float = 1.0,
    max_delay: float = 15.0,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.monotonic,
) -> int:
    """Poll check() with exponential backoff + jitter until it returns True.

    Returns the number of attempts taken. Raises TimeoutError if check()
    never returns True before deadline_seconds elapses (measured via `now`,
    not attempt count, so a slow check() doesn't silently grant extra
    retries). `sleep`/`now` are injectable so this is testable without
    actually waiting — see tests/test_smoke_test_receipt_role.py.
    """
    start = now()
    delay = initial_delay
    attempt = 0
    while True:
        attempt += 1
        if check():
            return attempt
        elapsed = now() - start
        if elapsed >= deadline_seconds:
            raise TimeoutError(f"condition not met after {attempt} attempts over {elapsed:.1f}s")
        sleep(delay + random.uniform(0, delay * 0.25))
        delay = min(delay * 2, max_delay)


def _check(label: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}" + (f" — {detail}" if detail and not condition else ""))
    if not condition:
        raise SmokeTestFailure(f"{label}: {detail}")


def _denied(callable_, *args, **kwargs) -> bool:
    """True if calling callable_ raises a permission-denied error."""
    try:
        callable_(*args, **kwargs)
        return False
    except Forbidden:
        return True
    except Exception as exc:
        # google-cloud-storage sometimes surfaces a 403 as a bare
        # google.api_core exception subtype other than Forbidden depending
        # on transport — treat any 403 in the message as a denial too.
        return "403" in str(exc)


def run(args: argparse.Namespace) -> int:
    backend_sa_email = args.backend_sa_email or f"mfs-backend@{args.project}.iam.gserviceaccount.com"
    role = f"projects/{args.project}/roles/{args.role_id}"
    bucket_name = f"{args.project}-receipts-smoketest-{uuid.uuid4().hex[:8]}"

    # Operator's own ambient credentials — used for scratch-bucket lifecycle
    # only. Captured before any monkeypatching below.
    operator_client = gcs_module.Client(project=args.project)

    print(f"Target: project={args.project} backend_sa={backend_sa_email} role={role}")
    print(f"Scratch bucket: {bucket_name}")

    bucket_created = False
    cleanup_ok = False
    test_result = 1  # pessimistic default — overwritten only on a real outcome below

    try:
        # ── 0: scratch bucket, same role as production ─────────────────────
        print("\n[0] Creating scratch bucket (soft-delete disabled) and binding the production role")
        bucket = gcs_module.Bucket(operator_client, bucket_name)
        bucket.soft_delete_policy.retention_duration_seconds = 0
        bucket.iam_configuration.uniform_bucket_level_access_enabled = True
        bucket = operator_client.create_bucket(bucket, location=args.region)
        bucket_created = True
        policy = bucket.get_iam_policy(requested_policy_version=3)
        policy.bindings.append({"role": role, "members": {f"serviceAccount:{backend_sa_email}"}})
        bucket.set_iam_policy(policy)
        _check("scratch bucket created and role bound", True)

        # Point the real app config at the scratch bucket, same technique as
        # smoke_test_image_pipeline.py: exercise the actual settings object,
        # not a mock of it.
        config.settings.environment = "production"
        config.settings.gcp_project_id = args.project
        config.settings.gcs_receipts_bucket_name = bucket_name

        # ── Impersonation: run the app's own storage.Client()/
        # google.auth.default() calls as the backend SA, without needing the
        # operator to switch their own ADC. Every module that does
        # `from google.cloud import storage` (or a local import inside a
        # function, as mcp_server._resolve_receipt_url does) looks up
        # `storage.Client` on the shared module object at call time, so
        # patching the attribute here covers all of them.
        source_credentials, _ = google.auth.default()
        impersonated = impersonated_credentials.Credentials(
            source_credentials=source_credentials,
            target_principal=backend_sa_email,
            target_scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        real_client_cls = gcs_module.Client
        real_auth_default = google.auth.default
        gcs_module.Client = lambda *a, **kw: real_client_cls(*a, credentials=impersonated, project=args.project, **{k: v for k, v in kw.items() if k not in ("credentials", "project")})
        google.auth.default = lambda *a, **kw: (impersonated, args.project)

        try:
            # ── 0b: wait for the IAM grant to actually be live ──────────────
            print("\n[0b] Waiting for IAM propagation")
            impersonated_bucket = gcs_module.Client().bucket(bucket_name)

            def _role_is_active() -> bool:
                try:
                    impersonated_bucket.blob("__iam_propagation_probe__").exists()
                    return True
                except Forbidden:
                    return False

            try:
                attempts = wait_until(_role_is_active, deadline_seconds=args.propagation_timeout)
                _check(f"role active after {attempts} attempt(s)", True)
            except TimeoutError as exc:
                _check("role became active before the deadline", False, str(exc))

            # ── 1: direct SDK upload, through the real admin route function ─
            print("\n[1] Direct SDK upload (app.routes.expenses.upload_receipt)")
            payload = b"%PDF-1.4 smoke-test receipt, not a real PDF structure"
            upload_file = UploadFile(filename="smoketest-receipt.pdf", file=io.BytesIO(payload))
            upload_file.headers = {"content-type": "application/pdf"}
            result = asyncio.run(expenses.upload_receipt(upload_file))
            receipt_url_1 = result["receipt_url"]
            _check("direct upload succeeded", receipt_url_1.startswith(f"gs://{bucket_name}/receipts/"), receipt_url_1)

            # ── 2: get_blob validation on the direct-uploaded object ────────
            print("\n[2] get_blob validation (app.mcp_server._resolve_receipt_url)")
            resolved_1 = mcp_server._resolve_receipt_url(receipt_url_1)
            _check("blob found and content-type round-tripped", resolved_1["receipt_content_type"] in ("application/pdf", "application/octet-stream"), str(resolved_1))

            # ── 3: signed PUT, then a real HTTP PUT against it ──────────────
            print("\n[3] Signed PUT (app.mcp_server.request_image_upload) + real HTTP PUT")
            put_info = mcp_server.request_image_upload("smoketest-receipt-2.jpg", "image/jpeg", kind="receipt")
            receipt_url_2 = put_info["final_url"]
            put_payload = b"\xff\xd8\xff smoke-test bytes, not a real JPEG"
            put_resp = httpx.put(
                put_info["upload_url"],
                content=put_payload,
                headers=put_info["required_headers"],
                timeout=30.0,
            )
            _check("signed PUT succeeds", put_resp.status_code in (200, 201), f"HTTP {put_resp.status_code}: {put_resp.text}")

            # ── 4: get_blob validation on the signed-PUT object ─────────────
            print("\n[4] get_blob validation on the signed-PUT object")
            resolved_2 = mcp_server._resolve_receipt_url(receipt_url_2)
            _check("PUT'd blob is found via get_blob", resolved_2["receipt_url"] == receipt_url_2, str(resolved_2))

            # ── 5: signed GET, then a real HTTP GET, byte-for-byte ──────────
            print("\n[5] Signed GET (app.services.uploads.signed_get_url) + real HTTP GET")
            blob_path_1 = receipt_url_1[len(f"gs://{bucket_name}/"):]
            signed_get = uploads.signed_get_url(bucket_name, blob_path_1)
            get_resp = httpx.get(signed_get, timeout=30.0)
            _check("signed GET succeeds", get_resp.status_code == 200, f"HTTP {get_resp.status_code}")
            _check("downloaded bytes match what was uploaded", get_resp.content == payload)

            # ── 6: negative checks, impersonated ─────────────────────────────
            print("\n[6] Negative checks (impersonated as the backend SA)")
            impersonated_client = gcs_module.Client()
            _check(
                "list is denied",
                _denied(lambda: list(impersonated_client.list_blobs(bucket_name, max_results=1))),
            )
            _check(
                "overwrite is denied",
                _denied(lambda: impersonated_bucket.blob(blob_path_1).upload_from_string(b"overwritten")),
            )
            _check(
                "delete is denied",
                _denied(lambda: impersonated_bucket.blob(blob_path_1).delete()),
            )

            print("\nAll checks passed.")
            test_result = 0

        except SmokeTestFailure as exc:
            print(f"\nSMOKE TEST FAILED: {exc}")
            test_result = 1

        finally:
            # Restore ambient identity before cleanup — the impersonated SA
            # cannot delete the bucket (it has no storage.buckets.delete
            # grant, by design), only the operator can.
            gcs_module.Client = real_client_cls
            google.auth.default = real_auth_default

    finally:
        if bucket_created:
            print("\nCleaning up...")
            cleanup_ok = _delete_bucket_with_verification(operator_client, bucket_name)
            if cleanup_ok:
                print(f"  deleted scratch bucket {bucket_name} and everything in it — verified gone")
            else:
                print(f"  WARNING: could not confirm scratch bucket {bucket_name} was fully removed")
                print(f"  check and delete manually: gcloud storage rm -r gs://{bucket_name}")
        else:
            cleanup_ok = True  # nothing was ever created

    if not cleanup_ok:
        return 1
    return test_result


def _delete_bucket_with_verification(client, bucket_name: str, *, attempts: int = 3) -> bool:
    """Best-effort delete with retry, then confirm the bucket is actually gone.

    A delete call that doesn't raise is not proof of anything by itself —
    verify with a separate lookup rather than trusting it.
    """
    for attempt in range(1, attempts + 1):
        try:
            client.bucket(bucket_name).delete(force=True)
            break
        except NotFound:
            break
        except Exception as exc:
            if attempt == attempts:
                print(f"  delete failed after {attempts} attempts: {exc}")
                return False
            time.sleep(2 * attempt)
    try:
        return not client.bucket(bucket_name).exists()
    except Exception as exc:
        print(f"  could not verify deletion: {exc}")
        return False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", required=True, help="GCP project id")
    parser.add_argument("--region", default="us-central1", help="Region for the scratch bucket")
    parser.add_argument("--backend-sa-email", default=None, help="Default: mfs-backend@{project}.iam.gserviceaccount.com")
    parser.add_argument("--role-id", default="mfsReceiptsUploader", help="Custom role id the real receipts bucket uses")
    parser.add_argument(
        "--propagation-timeout",
        type=float,
        default=120.0,
        help="Max seconds to wait for the IAM grant to take effect before failing (default: 120)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
