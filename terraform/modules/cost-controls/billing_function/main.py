"""Budget circuit breaker for the MadeForSeconds Cloud Run backend.

Two entry points, deployed as two Gen2 functions from this one source zip:

  kill_cloud_run   Pub/Sub-triggered by billing budget notifications. When actual
                   spend crosses the budget, revokes public access to the backend.
  reset_cloud_run  HTTP-triggered by a monthly Cloud Scheduler job. Restores
                   public access so the breaker re-closes at month rollover.

Mechanism: add/remove `allUsers` from the service's `roles/run.invoker` binding.

Why not scale to zero — the obvious approach, and the one this function used to
take. In Cloud Run v2, `max_instance_count = 0` is proto3's default value, so it
serializes as *unset* and the API applies its default cap instead. Setting it to
0 does not stop the service; in this project it silently raised the cap from 1
to 20, making a "kill" increase spend exposure 20x. There is no value of
max_instance_count that means "serve nothing".

Revoking invoker is what actually stops the spend: the service already scales to
zero, so idle cost is nil and the cost driver is requests. No requests get
through, so no instances start. It is also a single setIamPolicy call — no new
revision, no image re-resolution — which avoids the run.developer /
artifactregistry.reader / iam.serviceAccounts.actAs / run.operations.get chain
that a service update requires, every link of which failed in turn.

The log markers below are matched by a Cloud Monitoring log-based alert policy
(see terraform/billing.tf). Changing their text breaks that alert.

Both entry points also publish/clear a status file in the public images bucket
(STATUS_BUCKET) — src/lib/site-status.ts's only way to tell a deliberate
cost-cap pause from a genuine outage, since the revoked invoker binding makes
Cloud Run reject at the edge with no CORS headers, indistinguishable from the
site being down for any other reason. That file is a secondary signal, not
the safety mechanism: the IAM revoke/restore always happens first and
unconditionally, so a GCS hiccup can never block or reorder it. But a
status-file operation that still fails after _retry's own attempts is not
silently swallowed either: kill_cloud_run raises so Eventarc's
RETRY_POLICY_RETRY redelivers the notification, and reset_cloud_run returns a
non-2xx response so Cloud Scheduler's retry_config retries the call — the
external retry mechanisms that already existed for the IAM call now cover the
status file too. Both are safe to retry this way: the IAM side is idempotent
(gated on _is_public(policy)), so a retry only re-attempts the status file,
never a redundant setIamPolicy call. The frontend still treats a missing or
stale status file as "cannot confirm why", never as proof of anything, since
even these retries are finite.
"""

import base64
import datetime
import json
import os
import time

import functions_framework
from google.api_core.exceptions import NotFound
from google.cloud import run_v2, storage
from google.iam.v1 import iam_policy_pb2, policy_pb2


PROJECT_ID = os.environ["GCP_PROJECT_ID"]
REGION = os.environ.get("GCP_REGION", "us-central1")
SERVICE_NAME = os.environ.get("CLOUD_RUN_SERVICE", "mfs-backend")
STATUS_BUCKET = os.environ["STATUS_BUCKET"]

# Matched verbatim by google_monitoring_alert_policy.budget_breaker_tripped.
TRIPPED_MARKER = "BUDGET_BREAKER_TRIPPED"
RESET_MARKER = "BUDGET_BREAKER_RESET"

# The binding that makes the backend a public API. Mirrors
# google_cloud_run_v2_service_iam_member.public in terraform/cloud_run.tf.
INVOKER_ROLE = "roles/run.invoker"
PUBLIC_MEMBER = "allUsers"

# Read by src/lib/site-status.ts via VITE_STATUS_URL. Object name, not a path —
# STATUS_BUCKET is the public images bucket (module.storage.images_bucket_name),
# reused rather than standing up a dedicated bucket for one small file; it
# already grants allUsers get (not list) on every object it holds.
STATUS_OBJECT_NAME = "status.json"


class StatusFileError(RuntimeError):
    """Raised by kill_cloud_run when status.json could not be written/confirmed
    after _retry's attempts are exhausted, so Eventarc's RETRY_POLICY_RETRY
    (billing.tf) redelivers the notification instead of the failure being
    silently swallowed. reset_cloud_run never raises this — its failure path
    is a non-2xx response instead, since Cloud Scheduler's retry_config
    triggers on HTTP status, not on exceptions.
    """


def _retry(operation, *, attempts: int = 3, delay_seconds: float = 1.0):
    """A handful of immediate in-process retries for a GCS call — a fast first
    layer under the external retries kill_cloud_run/reset_cloud_run now
    trigger when even these are exhausted (see StatusFileError and the 503
    return below). Those external retries are much coarser: Eventarc
    redelivery only comes every ~20-30 min for as long as the budget stays
    over, and Cloud Scheduler's retry_config is 3 immediate HTTP retries
    triggered by a non-2xx response, not something tied to the once-a-month
    schedule itself. A status signal stuck wrong for even a few minutes is a
    bad visitor experience regardless of what eventually cleans it up.
    NotFound is never worth retrying — a missing object does not become
    present by asking again — so it always propagates immediately regardless
    of how many attempts remain.
    """
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            return operation()
        except NotFound:
            raise
        except Exception as exc:  # noqa: BLE001 - re-raised to the caller below
            last_exc = exc
            if attempt < attempts - 1:
                time.sleep(delay_seconds)
    raise last_exc


def _upload_status_blob(blob) -> None:
    payload = json.dumps(
        {
            "status": "budget_cap",
            "since": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
    )
    # Object metadata carries no Cache-Control by default, and GCS applies its
    # own default of up to an hour for public reads in that case
    # (https://cloud.google.com/storage/docs/caching) — exactly wrong for a
    # signal that has to reflect a trip or reset within seconds, not up to an
    # hour stale in either direction.
    blob.cache_control = "no-store"
    blob.upload_from_string(payload, content_type="application/json")


def _write_status_file() -> bool:
    """Publish the confirmed budget-cap signal, with a fresh `since`.

    Call this only at the moment the pause actually begins — the redelivered/
    already-tripped path calls _ensure_status_file instead, so a retried
    notification cannot keep resetting the original pause time.

    Returns True on success, False if every _retry attempt failed. Never
    raises itself — reports success/failure as a bool and leaves it to the
    caller, which turns False into a StatusFileError (see module docstring).
    """
    try:
        blob = storage.Client().bucket(STATUS_BUCKET).blob(STATUS_OBJECT_NAME)
        _retry(lambda: _upload_status_blob(blob))
        print(f"Wrote {STATUS_OBJECT_NAME} to gs://{STATUS_BUCKET}/{STATUS_OBJECT_NAME}")
        return True
    except Exception as exc:  # noqa: BLE001 - reported to the caller as a bool, never raised here
        print(f"Could not write {STATUS_OBJECT_NAME}: {exc}")
        return False


def _ensure_status_file() -> bool:
    """Self-heal only: write status.json if and only if it is currently
    missing, so a redelivered "already tripped" notification can recover from
    a prior failed write without clobbering the `since` an earlier, genuine
    trip already recorded.

    Returns True if the file is confirmed present (already there, or just
    written), False if the existence check or the write itself failed after
    retries. Never raises — see _write_status_file.
    """
    try:
        blob = storage.Client().bucket(STATUS_BUCKET).blob(STATUS_OBJECT_NAME)
        if _retry(blob.exists):
            return True
        _retry(lambda: _upload_status_blob(blob))
        print(f"{STATUS_OBJECT_NAME} was missing on an already-tripped check — wrote it")
        return True
    except Exception as exc:  # noqa: BLE001 - reported to the caller as a bool, never raised here
        print(f"Could not ensure {STATUS_OBJECT_NAME}: {exc}")
        return False


def _delete_status_file() -> bool:
    """Clear the confirmed budget-cap signal.

    Returns True on success — "already absent" counts as success, not failure
    — or False if the delete failed after retries. Never raises;
    reset_cloud_run turns False into a non-2xx response so Cloud Scheduler's
    retry_config gets a chance to retry the call.
    """
    blob = storage.Client().bucket(STATUS_BUCKET).blob(STATUS_OBJECT_NAME)
    try:
        _retry(blob.delete)
        print(f"Deleted {STATUS_OBJECT_NAME}")
        return True
    except NotFound:
        print(f"{STATUS_OBJECT_NAME} already absent, nothing to delete")
        return True
    except Exception as exc:  # noqa: BLE001 - reported to the caller as a bool, never raised here
        print(f"Could not delete {STATUS_OBJECT_NAME} after retries: {exc}")
        return False


def _service_path(client: run_v2.ServicesClient) -> str:
    return client.service_path(PROJECT_ID, REGION, SERVICE_NAME)


def _get_policy(client: run_v2.ServicesClient, resource: str) -> policy_pb2.Policy:
    return client.get_iam_policy(request=iam_policy_pb2.GetIamPolicyRequest(resource=resource))


def _set_policy(client: run_v2.ServicesClient, resource: str, policy: policy_pb2.Policy):
    return client.set_iam_policy(
        request=iam_policy_pb2.SetIamPolicyRequest(resource=resource, policy=policy)
    )


def _is_public(policy: policy_pb2.Policy) -> bool:
    return any(
        b.role == INVOKER_ROLE and PUBLIC_MEMBER in b.members for b in policy.bindings
    )


@functions_framework.cloud_event
def kill_cloud_run(cloud_event):
    """Revoke public access to the backend when actual spend crosses the budget."""
    data = base64.b64decode(cloud_event.data["message"]["data"]).decode("utf-8")
    budget_notification = json.loads(data)

    # Budget notifications arrive on every update (~every 20-30 min), and
    # forecast-threshold notifications arrive with actual spend still low.
    # Comparing *actual* cost is what keeps those from tripping the breaker.
    try:
        cost_amount = float(budget_notification.get("costAmount", 0) or 0)
        budget_amount = float(budget_notification.get("budgetAmount", 0) or 0)
    except (TypeError, ValueError):
        # A malformed payload must not raise: the Eventarc trigger is set to
        # RETRY_POLICY_RETRY, so an exception here becomes a redelivery hot loop.
        print(f"Ignoring budget notification with unparseable amounts: {budget_notification}")
        return

    # budget_amount == 0 means the field was missing entirely — treating that as
    # "cost >= budget" would revoke public access on any malformed message.
    if budget_amount <= 0:
        print(f"Ignoring budget notification with no budgetAmount: {budget_notification}")
        return

    if cost_amount < budget_amount:
        print(f"Cost ${cost_amount} still under budget ${budget_amount}, skipping.")
        return

    client = run_v2.ServicesClient()
    resource = _service_path(client)
    policy = _get_policy(client, resource)

    if not _is_public(policy):
        # Already tripped. Eventarc redelivers the same notification for as long
        # as the budget stays over, so this is the steady state after the first
        # trip — return without rewriting an identical policy. _ensure_ (not
        # _write_): this redelivery is what lets a prior write failure catch
        # up, but it must not overwrite an already-correct file and reset the
        # `since` a genuine trip already recorded.
        print(f"{SERVICE_NAME} is already private, breaker already tripped.")
        if not _ensure_status_file():
            # All retries exhausted. Raise (rather than return) so Eventarc's
            # RETRY_POLICY_RETRY (billing.tf) redelivers this notification —
            # the IAM side is already correct and idempotent, so the retry
            # only re-attempts the status file.
            raise StatusFileError(f"Could not confirm {STATUS_OBJECT_NAME} after retries")
        return

    print(
        f"{TRIPPED_MARKER} cost=${cost_amount} budget=${budget_amount} "
        f"service={SERVICE_NAME} — revoking public access."
    )

    for binding in policy.bindings:
        if binding.role == INVOKER_ROLE:
            binding.members.remove(PUBLIC_MEMBER)
    # Drop bindings left with no members — setIamPolicy rejects empty bindings.
    remaining = [b for b in policy.bindings if b.members]
    del policy.bindings[:]
    policy.bindings.extend(remaining)

    _set_policy(client, resource, policy)

    print(f"Public access to {SERVICE_NAME} revoked. The site is now returning 403.")
    if not _write_status_file():
        # All retries exhausted. Raise so Eventarc redelivers — the retry
        # re-enters via the "already tripped" branch above (IAM is already
        # revoked and stuck there), which calls _ensure_status_file instead of
        # _write_status_file again. That is correct: _ensure_ finds the file
        # missing (this write is what failed) and writes it fresh, which is
        # exactly right since there is no genuine prior `since` to preserve.
        raise StatusFileError(f"Could not write {STATUS_OBJECT_NAME} after retries")


@functions_framework.http
def reset_cloud_run(request):
    """Restore public access. Idempotent — safe to run monthly."""
    client = run_v2.ServicesClient()
    resource = _service_path(client)
    policy = _get_policy(client, resource)

    if _is_public(policy):
        # The common case: the breaker never tripped this month. Still clear
        # the status file — a stale one left by a prior best-effort delete
        # failure would otherwise keep telling visitors the site is paused
        # after it is already back, indefinitely.
        msg = f"{SERVICE_NAME} is already public, nothing to reset."
        print(msg)
        if not _delete_status_file():
            # All retries exhausted. Return non-2xx so Cloud Scheduler's
            # retry_config (billing.tf) retries the call — the IAM side is
            # already correct and idempotent, so the retry only re-attempts
            # the delete.
            return f"{msg} Failed to clear {STATUS_OBJECT_NAME}.", 503
        return msg, 200

    print(f"{RESET_MARKER} service={SERVICE_NAME} — restoring public access.")

    for binding in policy.bindings:
        if binding.role == INVOKER_ROLE:
            binding.members.append(PUBLIC_MEMBER)
            break
    else:
        policy.bindings.append(
            policy_pb2.Binding(role=INVOKER_ROLE, members=[PUBLIC_MEMBER])
        )

    _set_policy(client, resource, policy)

    msg = f"Public access to {SERVICE_NAME} restored."
    print(msg)
    if not _delete_status_file():
        return f"{msg} Failed to clear {STATUS_OBJECT_NAME}.", 503
    return msg, 200
