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

A secret that isn't configured in this environment (e.g. resend-api-key, when
that feature has never been enabled) never reaches here at all — SECRET_IDS
is built by Terraform from modules/security/secrets.tf's
local.created_secrets, which already carries null for anything not created,
and only surviving names make it into the deployed env var. That means a
NotFound at runtime is never the "not configured" case; it means a secret
Terraform's config says should exist has been deleted out of band, which is
real drift worth surfacing loudly — it may also mean mfs-backend just lost a
credential it depends on. It is treated as a per-secret failure like any
other, not a benign skip.

Every other per-secret failure is isolated to that secret: one secret's error
must not stop the others from being pruned. But isolation is not the same as
silence — any failure at all (a secret that couldn't be listed, or a single
version that failed to destroy) logs SECRET_PRUNE_ERROR and makes the whole
run return a non-2xx response, so Cloud Scheduler's bounded retry_config
(secret_pruner.tf) actually engages and the alert policy actually fires.
Retrying the whole run is safe even for the secrets that already succeeded:
plan_destructions never re-selects a version that already has a
scheduled_destroy_time (see below), so a retry's destroy calls only touch
versions still genuinely awaiting a first attempt.

A version already scheduled for delayed destruction (state DISABLED with
scheduled_destroy_time set — see
https://cloud.google.com/secret-manager/docs/delay-destruction-of-secret-versions)
is never selected as a candidate again. Without this, a retry, a manual
re-run, or next week's run landing before the 7-day version_destroy_ttl
elapses would call destroy_secret_version on a version already mid-deletion —
at best a wasted, failing API call, at worst resetting whatever destruction
clock the API keeps for it.
"""

import os

import functions_framework
from google.cloud import secretmanager
from google.cloud.secretmanager_v1.types import DestroySecretVersionRequest

PROJECT_ID = os.environ["GCP_PROJECT_ID"]

# Both matched verbatim by google_monitoring_alert_policy.secret_prune_anomaly's
# two conditions.
ANOMALY_MARKER = "SECRET_PRUNE_ANOMALY"
ERROR_MARKER = "SECRET_PRUNE_ERROR"

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
        # Presence (not the timestamp value itself) is all plan_destructions
        # needs: a DISABLED version with this set already has a destroy
        # scheduled and must never be selected again. Proto3 message fields
        # carry real field presence, so an unset Timestamp is falsy here and
        # a set one is truthy — no separate HasField check needed.
        "pending_destroy": bool(version.scheduled_destroy_time),
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
        if v["number"] < floor
        and v["state"] in ("ENABLED", "DISABLED")
        and not v.get("pending_destroy")
    ]
    return candidates, None


def process_secret(client: secretmanager.SecretManagerServiceClient, secret_id: str, write_enabled: bool) -> dict:
    """Lists, plans, and (if allowed) destroys old versions for one secret.

    Does NOT special-case a missing secret as benign. SECRET_IDS is built by
    Terraform from local.created_secrets, which already excludes anything not
    created — every name that reaches here is, per current Terraform config,
    supposed to exist. A NotFound here means real drift: someone deleted a
    configured secret out of band, or the deployment's config and its actual
    GCP state have diverged. That is exactly the kind of thing worth
    surfacing loudly (it may also mean mfs-backend just lost a credential it
    depends on), so it propagates to the caller like any other listing
    failure rather than being swallowed as "skipped".
    """
    parent = client.secret_path(PROJECT_ID, secret_id)
    versions = [_version_info(v) for v in client.list_secret_versions(parent=parent)]

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
            print(f"{ERROR_MARKER} secret={secret_id} version={v['number']}: {exc}")

    if destroyed:
        print(f"{secret_id}: destroyed versions {destroyed}")
    return {"destroyed": destroyed, "errored": errored}


@functions_framework.http
def prune_secret_versions(request):
    """Entry point. Runs every configured secret independently and returns a
    per-secret summary. Any failure at all — one secret that couldn't be
    listed, or one version within an otherwise-successful secret that failed
    to destroy — makes the whole run return 500, so Cloud Scheduler's
    retry_config engages and the alert policy has a marker to match. This is
    deliberately stricter than "only if everything failed": a single secret
    stuck erroring forever must not be able to hide behind the rest of the
    run succeeding.
    """
    secret_ids = _secret_ids_from_env()
    write_enabled_ids = _write_enabled_ids_from_env()

    client = secretmanager.SecretManagerServiceClient()
    results = {}
    any_errors = False

    for secret_id in secret_ids:
        try:
            result = process_secret(client, secret_id, secret_id in write_enabled_ids)
        except Exception as exc:  # noqa: BLE001 - isolate one secret's failure from the others
            any_errors = True
            result = {"error": str(exc)}
            print(f"{ERROR_MARKER} secret={secret_id}: {exc}")
        else:
            if result.get("errored"):
                any_errors = True
        results[secret_id] = result

    if any_errors:
        return results, 500
    return results, 200
