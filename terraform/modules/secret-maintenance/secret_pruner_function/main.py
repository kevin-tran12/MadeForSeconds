"""Secret Manager version pruner for MadeForSeconds.

HTTP-triggered by a weekly Cloud Scheduler job (secret_pruner.tf). For every
secret in SECRET_IDS, destroys old versions past the newest two ENABLED ones —
Secret Manager bills per active version above a 6-version free allowance
aggregated across the whole billing account, and these secrets otherwise never
lose a version once added.

Selection rule: the newest ENABLED version and its immediate ENABLED
predecessor are never destroyed, regardless of how many DISABLED versions sit
between or above them — see plan_destructions below. If the numerically
latest version of a secret is not ENABLED at all (a rotation added a version
and never enabled it, or something disabled it by hand), the whole secret is
skipped this run and SECRET_PRUNE_ANOMALY is logged (matched by
google_monitoring_alert_policy.secret_prune_anomaly) rather than guessing
which older version is "really" current.

Dry-run by default: a secret is only ever actually destroyed if its secret_id
appears in WRITE_ENABLED_SECRET_IDS. Every other secret still runs the full
listing and selection logic and logs exactly what it would have destroyed, so
the dry-run log output is a preview of the real thing, not a stub.

destroy_secret_version is called with each version's own etag, so a
concurrent state change on that specific version (someone hand-disabling it,
or a second run overlapping) is rejected by the API rather than silently
overwritten.

A secret that does not exist in this environment (e.g. resend-api-key, when
that feature has never been enabled) is reported as skipped, not an error —
SECRET_IDS is built from modules/security/secrets.tf's local.created_secrets,
which already carries null for anything not created; only names that survive
that filter reach here, but an out-of-band deletion could still race it.
Every other per-secret failure is isolated to that secret: one secret's error
must not stop the others from being pruned. The run only returns a non-2xx
response when it made no safe progress at all, so Cloud Scheduler's bounded
retry_config (secret_pruner.tf) has something worth retrying.
"""

import os

import functions_framework
from google.api_core.exceptions import NotFound
from google.cloud import secretmanager
from google.cloud.secretmanager_v1.types import DestroySecretVersionRequest

PROJECT_ID = os.environ["GCP_PROJECT_ID"]

# Matched verbatim by google_monitoring_alert_policy.secret_prune_anomaly.
ANOMALY_MARKER = "SECRET_PRUNE_ANOMALY"

# Sorting versions by number is equivalent to sorting by create_time — Secret
# Manager version numbers are assigned monotonically and never reused — and
# avoids parsing timestamps entirely.
KEEP_ENABLED_COUNT = 2


def _secret_ids_from_env() -> list[str]:
    raw = os.environ.get("SECRET_IDS", "")
    return [s for s in raw.split(",") if s]


def _write_enabled_ids_from_env() -> set[str]:
    raw = os.environ.get("WRITE_ENABLED_SECRET_IDS", "")
    return {s for s in raw.split(",") if s}


def _version_number(name: str) -> int:
    """`projects/P/secrets/S/versions/N` -> N. Versions are never reused, so
    this is a stable, timestamp-free sort key."""
    return int(name.rsplit("/", 1)[-1])


def _version_info(version) -> dict:
    return {
        "number": _version_number(version.name),
        "name": version.name,
        "state": version.state.name,
        "etag": version.etag,
    }


def plan_destructions(versions: list[dict], keep_enabled_count: int = KEEP_ENABLED_COUNT):
    """Pure selection logic — no GCP calls, so every rule here is directly
    unit-testable without mocking a client.

    Returns (candidates, anomaly): candidates is the list of version dicts
    that are safe to destroy; anomaly is a string reason (or None) when the
    numerically latest version is not ENABLED, in which case candidates is
    always empty — the whole secret is left untouched this run.
    """
    if not versions:
        return [], None

    latest = max(versions, key=lambda v: v["number"])
    if latest["state"] != "ENABLED":
        return [], f"latest version {latest['number']} is {latest['state']}, not ENABLED"

    enabled_sorted = sorted(
        (v for v in versions if v["state"] == "ENABLED"),
        key=lambda v: v["number"],
        reverse=True,
    )
    protected = enabled_sorted[:keep_enabled_count]
    floor = min(v["number"] for v in protected)

    candidates = [
        v for v in versions
        if v["number"] < floor and v["state"] in ("ENABLED", "DISABLED")
    ]
    return candidates, None


def process_secret(client: secretmanager.SecretManagerServiceClient, secret_id: str, write_enabled: bool) -> dict:
    """Lists, plans, and (if allowed) destroys old versions for one secret.

    Never raises for a missing secret — that is a normal "not configured in
    this environment" outcome, reported as skipped. Any other failure while
    listing propagates to the caller, which isolates it per-secret.
    """
    parent = client.secret_path(PROJECT_ID, secret_id)
    try:
        versions = [_version_info(v) for v in client.list_secret_versions(parent=parent)]
    except NotFound:
        return {"skipped": "secret not found"}

    candidates, anomaly = plan_destructions(versions)

    if anomaly:
        print(f"{ANOMALY_MARKER} secret={secret_id}: {anomaly}")
        return {"anomaly": anomaly}

    if not write_enabled:
        would_destroy = [v["number"] for v in candidates]
        if would_destroy:
            print(f"[dry-run] {secret_id}: would destroy versions {would_destroy}")
        return {"dry_run_would_destroy": would_destroy}

    destroyed = []
    errored = []
    for v in candidates:
        try:
            client.destroy_secret_version(
                request=DestroySecretVersionRequest(name=v["name"], etag=v["etag"])
            )
            destroyed.append(v["number"])
        except Exception as exc:  # noqa: BLE001 - isolate one bad version from the rest of this secret
            errored.append({"version": v["number"], "error": str(exc)})

    if destroyed:
        print(f"{secret_id}: destroyed versions {destroyed}")
    return {"destroyed": destroyed, "errored": errored}


@functions_framework.http
def prune_secret_versions(request):
    """Entry point. Runs every configured secret independently and returns a
    per-secret summary. 500 only when every secret failed outright — a mix of
    successes/skips/anomalies and a few hard errors still returns 200, since
    the run made real progress and a scheduler retry would just repeat the
    part that already worked.
    """
    secret_ids = _secret_ids_from_env()
    write_enabled_ids = _write_enabled_ids_from_env()

    client = secretmanager.SecretManagerServiceClient()
    results = {}
    hard_errors = 0

    for secret_id in secret_ids:
        try:
            results[secret_id] = process_secret(client, secret_id, secret_id in write_enabled_ids)
        except Exception as exc:  # noqa: BLE001 - isolate one secret's failure from the others
            hard_errors += 1
            results[secret_id] = {"error": str(exc)}
            print(f"Error processing {secret_id}: {exc}")

    if secret_ids and hard_errors == len(secret_ids):
        return results, 500
    return results, 200
