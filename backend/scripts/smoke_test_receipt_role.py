#!/usr/bin/env python3
"""Post-deploy smoke test for the receipts bucket's IAM role.

Unit tests mock every GCS call, so they cannot catch a wrong deployed IAM
grant. `smoke_test_image_pipeline.py` solves this for the images/staging
buckets by exercising the real path against the real buckets and cleaning up
afterward — but the receipts bucket carries a 7-year retention policy
(terraform/modules/storage/buckets.tf), so an object written there for a
test can never be deleted. This script instead creates a throwaway scratch
bucket (no retention, deleted at the end) with the SAME custom role bound
that the real receipts bucket uses, and runs the real receipt code paths
against it as the impersonated backend service account — never touching the
real receipts bucket at all.

Run it after any change to the receipts bucket's IAM (Epic 2, story 2.2):

    cd backend
    python scripts/smoke_test_receipt_role.py --project made-for-seconds

Unlike smoke_test_image_pipeline.py, this does NOT require the operator to
pre-authenticate with `gcloud auth application-default login
--impersonate-service-account=...` — the script builds impersonated
credentials for the exercise phase itself (requires the operator's own ADC
to hold roles/iam.serviceAccountTokenCreator on the backend SA, granted via
service_accounts.tf's backend_operator_impersonation) and uses the
operator's own ambient credentials, unimpersonated, for scratch-bucket
setup/teardown — a single invocation handles both.

Steps:
  0. (operator identity) Create a scratch bucket; bind it the same custom
     role (--role-id, default mfsReceiptsUploader) the real receipts bucket
     uses, on the real backend SA.
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

Cleans up by deleting the entire scratch bucket, as the operator (not the
impersonated identity, which cannot delete it), in a `finally` block
regardless of where the run stops.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import google.auth  # noqa: E402
import google.cloud.storage as gcs_module  # noqa: E402
import httpx  # noqa: E402
from google.api_core.exceptions import Forbidden  # noqa: E402
from google.auth import impersonated_credentials  # noqa: E402
from starlette.datastructures import UploadFile  # noqa: E402

from app import config, mcp_server  # noqa: E402
from app.routes import expenses  # noqa: E402
from app.services import uploads  # noqa: E402


class SmokeTestFailure(Exception):
    pass


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

    # ── 0: scratch bucket, same role as production ─────────────────────────
    print("\n[0] Creating scratch bucket and binding the production role")
    bucket = operator_client.create_bucket(bucket_name, location=args.region)
    policy = bucket.get_iam_policy(requested_policy_version=3)
    policy.bindings.append({"role": role, "members": {f"serviceAccount:{backend_sa_email}"}})
    bucket.set_iam_policy(policy)
    _check("scratch bucket created and role bound", True)

    # Point the real app config at the scratch bucket, same technique as
    # smoke_test_image_pipeline.py: exercise the actual settings object, not
    # a mock of it.
    config.settings.environment = "production"
    config.settings.gcp_project_id = args.project
    config.settings.gcs_receipts_bucket_name = bucket_name

    # ── Impersonation: run the app's own storage.Client()/google.auth.default()
    # calls as the backend SA, without needing the operator to switch their
    # own ADC. Every module that does `from google.cloud import storage` (or
    # a local `from google.cloud import storage` inside a function, as
    # mcp_server._resolve_receipt_url does) looks up `storage.Client` on the
    # shared module object at call time, so patching the attribute here
    # covers all of them.
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

    receipt_url_1 = None
    receipt_url_2 = None

    try:
        # ── 1: direct SDK upload, through the real admin route function ────
        print("\n[1] Direct SDK upload (app.routes.expenses.upload_receipt)")
        payload = b"%PDF-1.4 smoke-test receipt, not a real PDF structure"
        upload_file = UploadFile(filename="smoketest-receipt.pdf", file=io.BytesIO(payload))
        upload_file.headers = {"content-type": "application/pdf"}
        result = asyncio.run(expenses.upload_receipt(upload_file))
        receipt_url_1 = result["receipt_url"]
        _check("direct upload succeeded", receipt_url_1.startswith(f"gs://{bucket_name}/receipts/"), receipt_url_1)

        # ── 2: get_blob validation on the direct-uploaded object ───────────
        print("\n[2] get_blob validation (app.mcp_server._resolve_receipt_url)")
        resolved_1 = mcp_server._resolve_receipt_url(receipt_url_1)
        _check("blob found and content-type round-tripped", resolved_1["receipt_content_type"] in ("application/pdf", "application/octet-stream"), str(resolved_1))

        # ── 3: signed PUT, then a real HTTP PUT against it ─────────────────
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

        # ── 4: get_blob validation on the signed-PUT object ────────────────
        print("\n[4] get_blob validation on the signed-PUT object")
        resolved_2 = mcp_server._resolve_receipt_url(receipt_url_2)
        _check("PUT'd blob is found via get_blob", resolved_2["receipt_url"] == receipt_url_2, str(resolved_2))

        # ── 5: signed GET, then a real HTTP GET, byte-for-byte ─────────────
        print("\n[5] Signed GET (app.services.uploads.signed_get_url) + real HTTP GET")
        blob_path_1 = receipt_url_1[len(f"gs://{bucket_name}/"):]
        signed_get = uploads.signed_get_url(bucket_name, blob_path_1)
        get_resp = httpx.get(signed_get, timeout=30.0)
        _check("signed GET succeeds", get_resp.status_code == 200, f"HTTP {get_resp.status_code}")
        _check("downloaded bytes match what was uploaded", get_resp.content == payload)

        # ── 6: negative checks, impersonated ────────────────────────────────
        print("\n[6] Negative checks (impersonated as the backend SA)")
        impersonated_client = gcs_module.Client()
        impersonated_bucket = impersonated_client.bucket(bucket_name)
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
        return 0

    except SmokeTestFailure as exc:
        print(f"\nSMOKE TEST FAILED: {exc}")
        return 1

    finally:
        # Restore ambient identity before cleanup — the impersonated SA
        # cannot delete the bucket (it has no storage.buckets.delete grant,
        # by design), only the operator can.
        gcs_module.Client = real_client_cls
        google.auth.default = real_auth_default

        print("\nCleaning up...")
        try:
            operator_client.bucket(bucket_name).delete(force=True)
            print(f"  deleted scratch bucket {bucket_name} and everything in it")
        except Exception as exc:
            print(f"  WARNING: could not delete scratch bucket {bucket_name}: {exc}")
            print(f"  delete it manually: gcloud storage rm -r gs://{bucket_name}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", required=True, help="GCP project id")
    parser.add_argument("--region", default="us-central1", help="Region for the scratch bucket")
    parser.add_argument("--backend-sa-email", default=None, help="Default: mfs-backend@{project}.iam.gserviceaccount.com")
    parser.add_argument("--role-id", default="mfsReceiptsUploader", help="Custom role id the real receipts bucket uses")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
