#!/usr/bin/env python3
"""Post-deploy smoke test for the secret-pruner Cloud Function.

test_main.py mocks the Secret Manager client entirely, so it verifies our own
selection/orchestration logic but cannot catch a wrong deployed IAM grant, a
wrong OIDC audience, a Scheduler-invocation misconfiguration, broken function
packaging, or how the real API actually behaves under delayed destruction.
This script exercises those, against the real deployed function and the real
`secret-pruner-canary` secret (terraform/modules/secret-maintenance/
secret_pruner.tf) — never a real application secret.

Two halves, deliberately split:

  A. Authenticated boundary — mints a real OIDC identity token by
     impersonating the real secret-pruner service account (the same identity
     Cloud Scheduler's job authenticates as) and POSTs it directly to the
     deployed function's URL, exactly like Cloud Scheduler does. This proves
     the OIDC audience, the IAM invoker binding, the function's packaging,
     and its ability to list the canary's versions under its real IAM grant
     all actually work. It does NOT assume or require any particular
     write-enabled state — it just confirms the canary secret appears in the
     response with a shape (`dry_run_would_destroy` or `destroyed`) matching
     whatever WRITE_ENABLED_SECRET_IDS is currently deployed with.

  B. Destroy/recovery cycle — calls the Secret Manager API directly, as the
     same impersonated secret-pruner identity, to destroy a version it just
     added and confirm the deployed pruning algorithm (imported straight from
     secret_pruner_function/main.py, not reimplemented here) no longer
     selects it afterward, then restores it using the operator's own broader
     credentials — secret-pruner's role deliberately excludes
     secretmanager.versions.enable, same reasoning as the receipts role
     excluding delete. This proves the custom role's IAM actually behaves as
     designed against production Secret Manager, and that plan_destructions'
     pending_destroy exclusion holds against a real API response, not just
     the mocks in test_main.py.

Deliberately NOT automated: flipping secret_pruner_write_enabled_ids via
`terraform apply` and re-running through the real deployed write path.
Unlike smoke_test_receipt_role.py's scratch bucket (created and destroyed via
direct API calls, entirely outside Terraform), that would mean this script
running `terraform apply` against the *entire* root module — a materially
larger blast radius than any existing smoke test takes on. That flip, and the
end-to-end drill through the real deployed write path, stays the manual
procedure in docs/DEPLOYMENT.md § Secret version pruning. What this script
proves — the exact IAM/algorithm boundary that manual drill also exercises —
is what a mocked test suite structurally cannot.

Part A invokes the real shared function endpoint, which processes every
configured secret on each call, not just the canary — harmless today
(WRITE_ENABLED_SECRET_IDS starts empty by design), but once real secrets are
eventually allowlisted, running this script also triggers a real production
pruning pass on them, same as Cloud Scheduler's own weekly call would. Not a
bug, just worth knowing before running this on a whim after the drill.

Run it after any change to secret-pruner's IAM or the deployed function:

    cd backend
    python scripts/smoke_test_secret_pruner.py --project made-for-seconds

Prerequisites:
  - roles/iam.serviceAccountTokenCreator on the secret-pruner SA, to
    impersonate it. Granted by Terraform (secret_pruner.tf's
    pruner_operator_impersonation, mirroring backend_operator_impersonation).
  - secretmanager.versions.{add,enable,list} on the project via the
    operator's own broader access (roles/owner, or roles/secretmanager.admin)
    for setup/restore/cleanup — secret-pruner's own role deliberately can't
    do all of this, by design, so the operator's identity does the parts the
    pruner shouldn't be able to.
  - gcloud CLI on PATH and authenticated (`gcloud auth login` /
    `application-default login`) — used once to resolve the deployed
    function's URL; every other call goes through the Python client
    libraries directly.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# The deployed function's own source — imported directly so this script tests
# the exact same algorithm that's live, not a reimplementation of it that
# could silently drift from what secret_pruner.tf actually deploys. Not
# imported at module scope: main.py reads GCP_PROJECT_ID from the environment
# at import time (it's a Cloud Function, so that's always set by the time it
# runs for real), which this script doesn't know until argparse has run —
# see _import_pruner_main below.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "terraform" / "modules" / "secret-maintenance" / "secret_pruner_function"))

import google.auth  # noqa: E402
import httpx  # noqa: E402
from google.api_core.exceptions import GoogleAPICallError  # noqa: E402
from google.auth import impersonated_credentials  # noqa: E402
from google.auth.transport.requests import Request as GoogleAuthRequest  # noqa: E402
from google.cloud import secretmanager  # noqa: E402
from google.cloud.secretmanager_v1.types import (  # noqa: E402
    AddSecretVersionRequest,
    DestroySecretVersionRequest,
    EnableSecretVersionRequest,
    SecretPayload,
)


def _import_pruner_main(project: str):
    os.environ.setdefault("GCP_PROJECT_ID", project)
    import main as pruner_main  # noqa: PLC0415 - deliberately deferred, see the sys.path comment above

    return pruner_main


class SmokeTestFailure(Exception):
    pass


def _check(label: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}" + (f" — {detail}" if detail and not condition else ""))
    if not condition:
        raise SmokeTestFailure(f"{label}: {detail}")


def _version_number(name: str) -> int:
    return int(name.rsplit("/", 1)[-1])


def _get_function_url(project: str, region: str, function_name: str) -> str:
    """One gcloud CLI call — resolving a Gen2 function's URI has no stable,
    already-pinned Python client surface as simple as this in the versions
    used elsewhere in this repo, and every other call in this script goes
    through the Python libraries directly."""
    result = subprocess.run(
        [
            "gcloud", "functions", "describe", function_name,
            "--gen2", "--region", region, "--project", project,
            "--format=value(serviceConfig.uri)",
        ],
        capture_output=True, text=True, check=True, shell=(sys.platform == "win32"),
    )
    url = result.stdout.strip()
    if not url:
        raise SmokeTestFailure(f"could not resolve URL for function {function_name}: {result.stderr}")
    return url


def run(args: argparse.Namespace) -> int:
    pruner_sa_email = args.pruner_sa_email or f"secret-pruner@{args.project}.iam.gserviceaccount.com"
    run_id = uuid.uuid4().hex[:8]
    pruner_main = _import_pruner_main(args.project)

    print(f"Target: project={args.project} pruner_sa={pruner_sa_email} secret={args.secret_id}")

    # Operator's own ambient credentials — setup/restore/cleanup only.
    operator_creds, _ = google.auth.default()
    operator_client = secretmanager.SecretManagerServiceClient(credentials=operator_creds)

    # Base impersonated credentials for secret-pruner — used both to mint the
    # OIDC token for part A and to build a Secret Manager client for part B.
    pruner_base_creds = impersonated_credentials.Credentials(
        source_credentials=operator_creds,
        target_principal=pruner_sa_email,
        target_scopes=["https://www.googleapis.com/auth/cloud-platform"],
    )
    pruner_client = secretmanager.SecretManagerServiceClient(credentials=pruner_base_creds)

    secret_path = operator_client.secret_path(args.project, args.secret_id)
    added_versions: list[dict] = []  # cleanup target, populated as soon as each add succeeds

    try:
        # ── A: authenticated boundary — real deployed function, real OIDC ──
        print("\n[A] Authenticated invocation of the real deployed function")
        function_url = _get_function_url(args.project, args.region, args.function_name)
        print(f"  function URL: {function_url}")

        id_token_creds = impersonated_credentials.IDTokenCredentials(
            target_credentials=pruner_base_creds,
            target_audience=function_url,
            include_email=True,
        )
        id_token_creds.refresh(GoogleAuthRequest())
        resp = httpx.post(
            function_url,
            headers={"Authorization": f"Bearer {id_token_creds.token}"},
            timeout=60.0,
        )
        _check("function is reachable and authenticates the OIDC token", resp.status_code in (200, 500), f"HTTP {resp.status_code}: {resp.text}")
        body = resp.json()
        _check(f"{args.secret_id} appears in the response", args.secret_id in body, str(body))
        canary_result = body[args.secret_id]
        _check(
            "response shape matches a real run (dry-run preview or destroy result)",
            "dry_run_would_destroy" in canary_result or "destroyed" in canary_result,
            str(canary_result),
        )

        # ── B: destroy/recovery cycle, direct API, real delayed-destroy ────
        print("\n[B] Destroy/recovery cycle against the real Secret Manager API")
        print(f"  Adding 3 versions tagged smoke-test-{run_id}-{{a,b,c}}")
        for label in ("a", "b", "c"):
            payload = f"smoke-test-{run_id}-{label}".encode()
            version = operator_client.add_secret_version(
                request=AddSecretVersionRequest(parent=secret_path, payload=SecretPayload(data=payload))
            )
            added_versions.append({"label": label, "number": _version_number(version.name), "name": version.name, "payload": payload})
        target = added_versions[0]  # "a" — oldest of our 3, guaranteed prunable relative to b/c
        print(f"  target version: {target['number']} (payload={target['payload']!r})")

        versions_before = [pruner_main._version_info(v) for v in operator_client.list_secret_versions(parent=secret_path)]
        candidates, anomaly = pruner_main.plan_destructions(versions_before)
        _check("no anomaly reported for the canary", anomaly is None, str(anomaly))
        candidate_numbers = {v["number"] for v in candidates}
        _check(f"target version {target['number']} is selected for destruction", target["number"] in candidate_numbers, str(candidate_numbers))
        _check("the other two added versions are protected, not selected", {v["number"] for v in added_versions[1:]}.isdisjoint(candidate_numbers))

        target_version_info = next(v for v in versions_before if v["number"] == target["number"])
        print(f"  Destroying version {target['number']} as the impersonated secret-pruner identity")
        pruner_client.destroy_secret_version(
            request=DestroySecretVersionRequest(name=target_version_info["name"], etag=target_version_info["etag"])
        )

        versions_after_destroy = [pruner_main._version_info(v) for v in operator_client.list_secret_versions(parent=secret_path)]
        destroyed_info = next(v for v in versions_after_destroy if v["number"] == target["number"])
        _check("destroyed version is now DISABLED", destroyed_info["state"] == "DISABLED", destroyed_info["state"])
        _check("destroyed version has a scheduled destruction", destroyed_info["pending_destroy"] is True, str(destroyed_info))

        candidates_after, _ = pruner_main.plan_destructions(versions_after_destroy)
        _check(
            "the pruning algorithm no longer selects the destroyed version",
            target["number"] not in {v["number"] for v in candidates_after},
            str({v["number"] for v in candidates_after}),
        )

        print(f"  Restoring version {target['number']} as the operator (secret-pruner's role excludes .enable by design)")
        operator_client.enable_secret_version(
            request=EnableSecretVersionRequest(name=target_version_info["name"])
        )
        accessed = operator_client.access_secret_version(name=target_version_info["name"])
        _check("restored version's value is intact", accessed.payload.data == target["payload"], accessed.payload.data)

        print("\nAll checks passed.")
        return 0

    except SmokeTestFailure as exc:
        print(f"\nSMOKE TEST FAILED: {exc}")
        return 1

    finally:
        if added_versions:
            print("\nCleaning up test versions...")
            cleanup_ok = True
            for v in added_versions:
                cleanup_ok &= _destroy_with_retry(operator_client, v["name"])
            if cleanup_ok:
                print(f"  scheduled destruction for all {len(added_versions)} test versions (7-day version_destroy_ttl, same as production)")
            else:
                print(f"  WARNING: could not confirm cleanup of every test version on {args.secret_id} — check manually: gcloud secrets versions list {args.secret_id}")


def _destroy_with_retry(client, version_name: str, attempts: int = 3) -> bool:
    """Best-effort — a version already destroyed by the test itself (the
    target) fails with FailedPrecondition on a repeat destroy, which is a
    successful cleanup outcome (already gone), not a real failure."""
    for attempt in range(1, attempts + 1):
        try:
            client.destroy_secret_version(name=version_name)
            return True
        except GoogleAPICallError as exc:
            if "already" in str(exc).lower() or "DESTROYED" in str(exc):
                return True
            if attempt == attempts:
                print(f"  could not destroy {version_name} after {attempts} attempts: {exc}")
                return False
            time.sleep(2 * attempt)
    return False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", required=True, help="GCP project id")
    parser.add_argument("--region", default="us-central1", help="Region the function is deployed in")
    parser.add_argument("--function-name", default="secret-pruner", help="Deployed Cloud Function name")
    parser.add_argument("--pruner-sa-email", default=None, help="Default: secret-pruner@{project}.iam.gserviceaccount.com")
    parser.add_argument("--secret-id", default="secret-pruner-canary", help="Which secret to test against — never point this at a real application secret")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
