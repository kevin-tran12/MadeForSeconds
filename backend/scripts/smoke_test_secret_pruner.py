#!/usr/bin/env python3
"""Post-deploy smoke test for the secret-pruner Cloud Function.

test_main.py mocks the Secret Manager client entirely, so it verifies our own
selection/orchestration logic but cannot catch a wrong deployed IAM grant, a
wrong OIDC audience, a Scheduler-invocation misconfiguration, broken function
packaging, or how the real API actually behaves under delayed destruction.
This script exercises those, against the real deployed function and the real
`secret-pruner-canary` secret (terraform/modules/secret-maintenance/
secret_pruner.tf) — NEVER a real application secret. That is not a
configurable option: CANARY_SECRET_ID below is the only secret this script
will ever write to, enforced by _require_canary_secret() immediately before
the first mutating call. Earlier versions of this script took --secret-id as
a CLI flag; that was removed because pointing it at a real secret (e.g.
stripe-secret-key) would have written fake payloads as that secret's newest
versions and then scheduled them for destruction — a real outage, not a test
failure.

Three parts:

  A. Authenticated boundary — mints a real OIDC identity token by
     impersonating the real secret-pruner service account (the same identity
     Cloud Scheduler's job authenticates as) and POSTs it directly to the
     deployed function's URL, exactly like Cloud Scheduler does. Also runs
     `gcloud scheduler jobs run` on the real deployed job, so the Scheduler
     wiring itself (not just the function in isolation) gets exercised too.
     Requires a clean 200 with no per-secret error anywhere in the response —
     not just "the canary looks fine" — because a smoke test that shrugs off
     another secret's failure is a smoke test that can miss a real problem.

  B. Destroy/recovery cycle via direct API — calls the Secret Manager API
     directly, as the same impersonated secret-pruner identity, to destroy a
     version it just added and confirm the deployed pruning algorithm
     (imported straight from secret_pruner_function/main.py, not
     reimplemented here) no longer selects it afterward, then restores it
     using the operator's own broader credentials — secret-pruner's role
     deliberately excludes secretmanager.versions.enable, same reasoning as
     the receipts role excluding delete. Proves the custom role's IAM
     actually behaves as designed against production Secret Manager, and
     that plan_destructions' pending_destroy exclusion holds against a real
     API response.

  C. (--test-write-path, opt-in, off by default) Real deployed write path —
     temporarily flips the deployed function's own WRITE_ENABLED_SECRET_IDS
     env var (via `gcloud functions deploy --update-env-vars`, not Terraform)
     to include only the canary, re-invokes the real function, and confirms
     the response shows the function's OWN write-path code actually called
     destroy_secret_version for real — something Part B's direct-API
     approach never exercises, since it bypasses the function entirely.
     Always reverts the env var afterward and verifies the revert, even on
     failure; a revert that can't be confirmed is a hard failure with the
     exact remediation command printed, since leaving a Cloud Function
     mis-configured is worse than a failed test run. Off by default: this
     does two live redeploys of the function (env var only, no rebuild, but
     still a real production config change each way) and cannot be rehearsed
     against a function that doesn't exist until you've applied this story's
     Terraform at least once — opt in once you trust the basic Parts A/B.

Deliberately NOT automated even with --test-write-path: touching
secret_pruner_write_enabled_ids or running `terraform apply`. Part C's env
var flip goes around Terraform entirely and always reverts to whatever
Terraform already has deployed, so a `terraform plan` right after this script
exits should show no diff from it having run. The actual, permanent
allowlisting of a real secret stays a deliberate `terraform apply`, done by a
human, per docs/DEPLOYMENT.md § Secret version pruning.

Part A (and Part C, if used) invoke the real shared function endpoint, which
processes every configured secret on each call, not just the canary —
harmless today (WRITE_ENABLED_SECRET_IDS starts empty by design), but once
real secrets are eventually allowlisted, running this script also triggers a
real production pruning pass on them, same as Cloud Scheduler's own weekly
call would. Not a bug, just worth knowing before running this on a whim
after the drill.

Run it after any change to secret-pruner's IAM or the deployed function:

    cd backend
    python scripts/smoke_test_secret_pruner.py --project made-for-seconds

Prerequisites:
  - roles/iam.serviceAccountTokenCreator on the secret-pruner SA, to
    impersonate it. Granted by Terraform (secret_pruner.tf's
    pruner_operator_impersonation, mirroring backend_operator_impersonation).
  - secretmanager.versions.{add,enable,list,destroy} on the project via the
    operator's own broader access (roles/owner, or roles/secretmanager.admin)
    for setup/restore/cleanup — secret-pruner's own role deliberately can't
    do all of this, by design, so the operator's identity does the parts the
    pruner shouldn't be able to.
  - With --test-write-path: cloudfunctions.functions.update (or broader, e.g.
    roles/cloudfunctions.developer) to flip the deployed env var.
  - logging.logEntries.list on the project (roles/logging.viewer or
    broader), to confirm the triggered Cloud Scheduler attempt actually
    completed via its AttemptFinished log entry — see
    _find_attempt_finished_log.
  - gcloud CLI on PATH and authenticated (`gcloud auth login` /
    `application-default login`) — resolved via shutil.which and invoked
    with shell=False always, so arguments are never shell-interpreted
    regardless of content; every other call goes through the Python client
    libraries directly.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
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

# The only secret this script will ever write to. Not a CLI flag — see the
# module docstring for why that was removed.
CANARY_SECRET_ID = "secret-pruner-canary"


class SmokeTestFailure(Exception):
    pass


def _import_pruner_main(project: str):
    os.environ.setdefault("GCP_PROJECT_ID", project)
    import main as pruner_main  # noqa: PLC0415 - deliberately deferred, see the sys.path comment above

    return pruner_main


def _require_canary_secret(secret_path: str) -> None:
    """Defense in depth, called immediately before the first mutating call.
    CANARY_SECRET_ID is already a hardcoded constant with no CLI override, so
    this should be unreachable in practice — it exists so a future refactor
    that accidentally re-threads a different secret_id through here fails
    loudly instead of quietly writing fake versions onto a real secret."""
    if not secret_path.endswith(f"/secrets/{CANARY_SECRET_ID}"):
        raise SmokeTestFailure(
            f"refusing to mutate {secret_path!r} — this script only ever writes to "
            f"the disposable {CANARY_SECRET_ID!r} secret, and that is not configurable."
        )


def _check(label: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}" + (f" — {detail}" if detail and not condition else ""))
    if not condition:
        raise SmokeTestFailure(f"{label}: {detail}")


def _version_number(name: str) -> int:
    return int(name.rsplit("/", 1)[-1])


def _resolve_gcloud() -> str:
    path = shutil.which("gcloud")
    if not path:
        raise SmokeTestFailure("gcloud CLI not found on PATH")
    return path


def _run_gcloud(argv: list[str], *, timeout: float = 600.0) -> subprocess.CompletedProcess:
    """shell=False on every platform — argv is passed as a literal list, so
    no shell ever parses it, regardless of what project/region/function-name
    values it contains. The previous version used shell=(sys.platform ==
    "win32"), which Bandit correctly flags as B602: a plausible-looking but
    real command-injection surface, since Windows' CreateProcess can invoke
    gcloud's .CMD wrapper directly once shutil.which resolves its full path —
    shell=True was never actually necessary to make this work on Windows."""
    gcloud = _resolve_gcloud()
    try:
        return subprocess.run([gcloud, *argv], capture_output=True, text=True, shell=False, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise SmokeTestFailure(f"gcloud {' '.join(argv)} timed out after {timeout}s") from exc


def _run_gcloud_checked(argv: list[str], *, timeout: float = 600.0) -> str:
    result = _run_gcloud(argv, timeout=timeout)
    if result.returncode != 0:
        raise SmokeTestFailure(f"gcloud {' '.join(argv)} failed (exit {result.returncode}): {result.stderr}")
    return result.stdout.strip()


def _get_function_url(project: str, region: str, function_name: str) -> str:
    url = _run_gcloud_checked([
        "functions", "describe", function_name,
        "--gen2", "--region", region, "--project", project,
        "--format=value(serviceConfig.uri)",
    ])
    if not url:
        raise SmokeTestFailure(f"gcloud returned no URL for function {function_name}")
    return url


def _get_write_enabled_env(project: str, region: str, function_name: str) -> str:
    return _run_gcloud_checked([
        "functions", "describe", function_name,
        "--gen2", "--region", region, "--project", project,
        "--format=value(serviceConfig.environmentVariables.WRITE_ENABLED_SECRET_IDS)",
    ])


def _write_enabled_env_flag(value: str) -> str:
    # --update-env-vars is itself a comma-separated KEY=VALUE dict flag, but
    # WRITE_ENABLED_SECRET_IDS's own value is *also* comma-separated (a list
    # of secret ids) — gcloud would otherwise split "admin-emails,
    # instagram-access-token" into two dict entries, the second of which
    # ("instagram-access-token") has no "=" and fails to parse. ^:^ switches
    # the flag's own entry delimiter to ":", so commas inside the value stay
    # literal (see `gcloud topic escaping`). ":" is safe unconditionally:
    # Secret Manager secret ids are restricted to [a-zA-Z0-9-_] and can never
    # contain one, so this is correct whether value has zero, one, or many
    # secret ids — no need to special-case by content.
    #
    # Empty value ("") is deliberate, not omitted: it sets the key to an
    # explicit empty string, matching exactly what Terraform's
    # join(",", sort(var.write_enabled_secret_ids)) deploys when the
    # allowlist is empty. Using --remove-env-vars instead would drop the key
    # entirely, which the function's os.environ.get(..., "") tolerates but
    # which is not what a `terraform plan` afterward would expect to see.
    return f"--update-env-vars=^:^WRITE_ENABLED_SECRET_IDS={value}"


def _set_write_enabled_env(project: str, region: str, function_name: str, value: str) -> None:
    _run_gcloud_checked([
        "functions", "deploy", function_name,
        "--gen2", "--region", region, "--project", project,
        _write_enabled_env_flag(value),
    ], timeout=300.0)


def _utc_now_iso() -> str:
    import datetime

    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _find_attempt_finished_log(project: str, job_name: str, since_iso: str) -> dict | None:
    """The earliest AttemptFinished log entry for this job at or after
    since_iso, or None if none has landed yet.

    Deliberately NOT `gcloud scheduler jobs describe`'s lastAttemptTime/status
    fields — the API documents lastAttemptTime as when the attempt STARTED
    and status as "the response for the last attempted execution", two
    separate pieces of information with no guarantee they update atomically.
    A describe() call can observe a just-advanced lastAttemptTime while
    status still reflects the PREVIOUS attempt, which would let this check
    pass before the triggered attempt has actually authenticated or
    completed. Cloud Scheduler's own troubleshooting guidance is to
    correlate AttemptStarted/AttemptFinished log entries instead — confirmed
    against this project's real logs: a successful AttemptFinished has
    severity INFO and no jsonPayload.status field at all; a failed one has
    severity ERROR and jsonPayload.status set to a google.rpc.Code name
    (e.g. "INTERNAL") — both pulled from `cloudscheduler.googleapis.com/executions`.
    """
    filter_str = (
        f'resource.type="cloud_scheduler_job" '
        f'resource.labels.job_id="{job_name}" '
        f'jsonPayload."@type"="type.googleapis.com/google.cloud.scheduler.logging.AttemptFinished" '
        f'timestamp>="{since_iso}"'
    )
    raw = _run_gcloud_checked([
        "logging", "read", filter_str,
        "--project", project, "--order=asc", "--limit=1",
        "--format=json(severity,jsonPayload.status,jsonPayload.debugInfo)",
    ])
    entries = json.loads(raw) if raw else []
    return entries[0] if entries else None


def _wait_for_scheduler_attempt(
    project: str, region: str, job_name: str, since_iso: str,
    *, deadline_seconds: float = 180.0, poll_interval: float = 5.0,
    sleep=time.sleep, now=time.monotonic,
) -> None:
    """Polls Cloud Logging until an AttemptFinished entry for this job lands
    at or after since_iso (the time this script triggered it — must be
    recorded BEFORE calling `gcloud scheduler jobs run`, since that command
    only forces dispatch and says nothing about whether the HTTP target
    actually authenticated or completed) and confirms it succeeded. Raises
    SmokeTestFailure either if that attempt failed (severity ERROR / a
    jsonPayload.status present) or if no AttemptFinished entry appears
    before the deadline — log delivery to Cloud Logging is itself not
    instant, so the deadline needs real margin beyond the function's own
    typical runtime, not just enough for the HTTP round trip.
    """
    del region  # kept for call-site symmetry with the other scheduler helpers; the log filter doesn't need it
    deadline = now() + deadline_seconds
    while True:
        entry = _find_attempt_finished_log(project, job_name, since_iso)
        if entry is not None:
            severity = entry.get("severity", "INFO")
            status = entry.get("jsonPayload", {}).get("status")
            if severity == "ERROR" or status:
                debug_info = entry.get("jsonPayload", {}).get("debugInfo", "")
                raise SmokeTestFailure(f"scheduler job {job_name}'s triggered attempt failed: status={status} debugInfo={debug_info!r}")
            return
        if now() >= deadline:
            raise SmokeTestFailure(f"scheduler job {job_name} recorded no AttemptFinished log entry within {deadline_seconds}s of being triggered (since={since_iso})")
        sleep(poll_interval)


def _check_response_is_clean(body: dict) -> None:
    """Requires no error AND no anomaly on ANY secret in the response, not
    just the canary — a smoke test that shrugs off drift or a failure on an
    unrelated secret can miss a real problem in the same deployed function."""
    errored = {sid: r for sid, r in body.items() if isinstance(r, dict) and (r.get("error") or r.get("errored"))}
    _check("no secret reported an error in the response", not errored, str(errored))
    anomalous = {sid: r for sid, r in body.items() if isinstance(r, dict) and r.get("anomaly")}
    _check("no secret reported an anomaly in the response", not anomalous, str(anomalous))


def _destroy_with_retry(client, version_name: str, attempts: int = 3) -> bool:
    """Best-effort — a version already destroyed fails with FailedPrecondition
    on a repeat destroy, which is a successful cleanup outcome (already
    gone), not a real failure."""
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


def _cleanup_and_verify_healthy(pruner_main, operator_client, secret_path: str) -> bool:
    """Destroys exactly what plan_destructions says is safe to destroy right
    now — never a blanket "destroy everything this run added", which would
    include the numerically newest added version and leave the canary's
    latest version DISABLED, guaranteeing a SECRET_PRUNE_ANOMALY on the very
    next scheduled run. The two most-recently-added versions stay ENABLED
    (they're the algorithm's own protected floor), so the canary is left in
    the same healthy 2-enabled state normal operation converges to — and,
    as a bonus, this also sweeps up any leftover cruft from a prior run of
    this same script.

    Returns False (never raises) if any destroy fails or if the canary is
    somehow left anomalous anyway — every caller must treat False as a hard
    failure, not a warning to shrug off.
    """
    versions = [pruner_main._version_info(v) for v in operator_client.list_secret_versions(parent=secret_path)]
    candidates, _ = pruner_main.plan_destructions(versions)

    ok = True
    for v in candidates:
        ok &= _destroy_with_retry(operator_client, v["name"])

    versions_after = [pruner_main._version_info(v) for v in operator_client.list_secret_versions(parent=secret_path)]
    _, anomaly_after = pruner_main.plan_destructions(versions_after)
    if anomaly_after is not None:
        print(f"  WARNING: canary left anomalous after cleanup: {anomaly_after}")
        print(f"  Remediation: gcloud secrets versions list {CANARY_SECRET_ID}, then either")
        print(f"    gcloud secrets versions enable <version> --secret={CANARY_SECRET_ID}   (if its value is fine)")
        print(f"    gcloud secrets versions add {CANARY_SECRET_ID} --data-file=-           (to rotate a fresh one on top)")
        ok = False

    if ok:
        print(f"  cleanup left {CANARY_SECRET_ID} in a healthy state (latest version ENABLED, no anomaly)")
    return ok


def _test_authenticated_boundary(args, pruner_base_creds, function_url: str) -> None:
    print("\n[A] Authenticated invocation of the real deployed function")
    id_token_creds = impersonated_credentials.IDTokenCredentials(
        target_credentials=pruner_base_creds,
        target_audience=function_url,
        include_email=True,
    )
    id_token_creds.refresh(GoogleAuthRequest())
    resp = httpx.post(function_url, headers={"Authorization": f"Bearer {id_token_creds.token}"}, timeout=60.0)
    _check("function returns a clean 200", resp.status_code == 200, f"HTTP {resp.status_code}: {resp.text}")
    body = resp.json()
    _check_response_is_clean(body)
    _check(f"{CANARY_SECRET_ID} appears in the response", CANARY_SECRET_ID in body, str(body))
    canary_result = body[CANARY_SECRET_ID]
    _check(
        "response shape matches a real run (dry-run preview or destroy result)",
        "dry_run_would_destroy" in canary_result or "destroyed" in canary_result,
        str(canary_result),
    )

    print(f"\n[A2] Confirming the deployed Cloud Scheduler job dispatches and completes ({args.scheduler_job_name})")
    trigger_time = _utc_now_iso()  # recorded BEFORE dispatch, so the log filter can't miss the resulting attempt
    _run_gcloud_checked(["scheduler", "jobs", "run", args.scheduler_job_name, "--location", args.region, "--project", args.project])
    _wait_for_scheduler_attempt(args.project, args.region, args.scheduler_job_name, trigger_time)
    _check("scheduler-triggered attempt completed successfully", True)


def _test_destroy_recovery_cycle(pruner_main, operator_client, pruner_client, secret_path: str, run_id: str) -> list[dict]:
    """Returns the list of version dicts this added — informational only
    (e.g. for tests to assert against). run()'s cleanup does NOT depend on
    this return value: it re-lists the secret's actual current state instead,
    specifically so a failure here partway through (after some adds but
    before this returns) still gets cleaned up."""
    print("\n[B] Destroy/recovery cycle against the real Secret Manager API")
    added_versions: list[dict] = []
    print(f"  Adding 3 versions tagged smoke-test-{run_id}-{{a,b,c}}")
    for label in ("a", "b", "c"):
        payload = f"smoke-test-{run_id}-{label}".encode()
        version = operator_client.add_secret_version(request=AddSecretVersionRequest(parent=secret_path, payload=SecretPayload(data=payload)))
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
    pruner_client.destroy_secret_version(request=DestroySecretVersionRequest(name=target_version_info["name"], etag=target_version_info["etag"]))

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
    operator_client.enable_secret_version(request=EnableSecretVersionRequest(name=target_version_info["name"]))
    accessed = operator_client.access_secret_version(name=target_version_info["name"])
    _check("restored version's value is intact", accessed.payload.data == target["payload"], accessed.payload.data)

    return added_versions


def _test_real_write_path(args, pruner_main, operator_client, pruner_base_creds, function_url: str, secret_path: str) -> None:
    """--test-write-path only. Flips the deployed function's own env var
    (never Terraform), so its OWN write-path code — not this script calling
    the API directly, as Part B does — is what performs the destroy. Always
    reverts in its own finally, and treats a revert that can't be confirmed
    as a hard failure with the exact fix-it command printed, regardless of
    how the rest of this function went.
    """
    print("\n[C] Real deployed write path (--test-write-path)")
    original = _get_write_enabled_env(args.project, args.region, args.function_name)
    print(f"  current WRITE_ENABLED_SECRET_IDS={original!r} — will restore this exact value afterward")

    flipped = False
    try:
        print(f"  Deploying with WRITE_ENABLED_SECRET_IDS={CANARY_SECRET_ID} (env var only, no source change)")
        _set_write_enabled_env(args.project, args.region, args.function_name, CANARY_SECRET_ID)
        flipped = True
        _check(
            "deployed env var actually updated",
            _get_write_enabled_env(args.project, args.region, args.function_name) == CANARY_SECRET_ID,
            "describe did not reflect the update",
        )

        versions_before = [pruner_main._version_info(v) for v in operator_client.list_secret_versions(parent=secret_path)]
        candidates, anomaly = pruner_main.plan_destructions(versions_before)
        _check("no anomaly reported for the canary before the real write-path call", anomaly is None, str(anomaly))
        _check("there is a candidate for the deployed function to actually destroy", len(candidates) > 0, "nothing prunable right now — run Part B first or add another version")
        expected_target = candidates[0]["number"]

        id_token_creds = impersonated_credentials.IDTokenCredentials(target_credentials=pruner_base_creds, target_audience=function_url, include_email=True)
        id_token_creds.refresh(GoogleAuthRequest())
        resp = httpx.post(function_url, headers={"Authorization": f"Bearer {id_token_creds.token}"}, timeout=120.0)
        _check("real write-path invocation returns a clean 200", resp.status_code == 200, f"HTTP {resp.status_code}: {resp.text}")
        body = resp.json()
        _check_response_is_clean(body)
        canary_result = body.get(CANARY_SECRET_ID, {})
        _check(
            f"the deployed function's own code destroyed version {expected_target}",
            expected_target in canary_result.get("destroyed", []),
            str(canary_result),
        )

        versions_after = [pruner_main._version_info(v) for v in operator_client.list_secret_versions(parent=secret_path)]
        destroyed_info = next(v for v in versions_after if v["number"] == expected_target)
        _check("that version is now DISABLED with a scheduled destruction", destroyed_info["state"] == "DISABLED" and destroyed_info["pending_destroy"], str(destroyed_info))

        print(f"  Restoring version {expected_target} as the operator")
        operator_client.enable_secret_version(name=destroyed_info["name"])

    finally:
        if flipped:
            print(f"  Reverting WRITE_ENABLED_SECRET_IDS to {original!r}")
            _set_write_enabled_env(args.project, args.region, args.function_name, original)
            reverted_to = _get_write_enabled_env(args.project, args.region, args.function_name)
            if reverted_to != original:
                raise SmokeTestFailure(
                    f"could not confirm WRITE_ENABLED_SECRET_IDS was reverted to {original!r} (describe shows {reverted_to!r}). "
                    f"Fix immediately: gcloud functions deploy {args.function_name} --gen2 --region {args.region} "
                    f"--project {args.project} {_write_enabled_env_flag(original)}"
                )
            print("  reverted and confirmed")


def run(args: argparse.Namespace) -> int:
    pruner_sa_email = args.pruner_sa_email or f"secret-pruner@{args.project}.iam.gserviceaccount.com"
    run_id = uuid.uuid4().hex[:8]
    pruner_main = _import_pruner_main(args.project)

    print(f"Target: project={args.project} pruner_sa={pruner_sa_email} secret={CANARY_SECRET_ID}")

    operator_creds, _ = google.auth.default()
    operator_client = secretmanager.SecretManagerServiceClient(credentials=operator_creds)

    pruner_base_creds = impersonated_credentials.Credentials(
        source_credentials=operator_creds,
        target_principal=pruner_sa_email,
        target_scopes=["https://www.googleapis.com/auth/cloud-platform"],
    )
    pruner_client = secretmanager.SecretManagerServiceClient(credentials=pruner_base_creds)

    secret_path = operator_client.secret_path(args.project, CANARY_SECRET_ID)
    _require_canary_secret(secret_path)

    test_result = 1  # pessimistic default — overwritten only on a real outcome below

    try:
        function_url = _get_function_url(args.project, args.region, args.function_name)
        print(f"  function URL: {function_url}")

        _test_authenticated_boundary(args, pruner_base_creds, function_url)
        _test_destroy_recovery_cycle(pruner_main, operator_client, pruner_client, secret_path, run_id)

        if args.test_write_path:
            _test_real_write_path(args, pruner_main, operator_client, pruner_base_creds, function_url, secret_path)

        print("\nAll checks passed.")
        test_result = 0

    except Exception as exc:  # noqa: BLE001 - deliberately broad, not just SmokeTestFailure: Part B/C's
        # direct destroy/enable/access calls aren't individually wrapped, so a real
        # GoogleAPICallError from any of them must still land here (finally below
        # always runs regardless of exception type, but without this broad catch
        # the exception would propagate past run() with an unhandled traceback
        # instead of the same graceful "SMOKE TEST FAILED" + exit 1 as any other
        # failure).
        print(f"\nSMOKE TEST FAILED: {exc}")
        test_result = 1

    finally:
        # Unconditional, not gated on "did we get far enough to add
        # versions" — _cleanup_and_verify_healthy re-derives ground truth
        # from a fresh listing every time, so it's a safe, cheap no-op when
        # nothing needs cleaning, and it's the only thing standing between a
        # failure at ANY point above (mid-add, mid-destroy, mid-restore, or
        # in a verification _check afterward) and orphaned test versions.
        # Gating this on a mutation list populated only by a helper's normal
        # return was the previous, confirmed-broken design: an exception
        # raised after the first add() but before that helper returned left
        # the caller's list empty and skipped cleanup entirely.
        print("\nCleaning up test versions...")
        cleanup_ok = _cleanup_and_verify_healthy(pruner_main, operator_client, secret_path)
        if not cleanup_ok:
            print(f"  WARNING: cleanup could not confirm {CANARY_SECRET_ID} was left healthy — see remediation above")

    if not cleanup_ok:
        return 1
    return test_result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", required=True, help="GCP project id")
    parser.add_argument("--region", default="us-central1", help="Region the function is deployed in")
    parser.add_argument("--function-name", default="secret-pruner", help="Deployed Cloud Function name")
    parser.add_argument("--scheduler-job-name", default="secret-version-pruner", help="Deployed Cloud Scheduler job name")
    parser.add_argument("--pruner-sa-email", default=None, help="Default: secret-pruner@{project}.iam.gserviceaccount.com")
    parser.add_argument(
        "--test-write-path", action="store_true",
        help="Also exercise the real deployed write path via a temporary env-var flip (two live redeploys). Off by default — see the module docstring's Part C.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
