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
"""

import base64
import json
import os

import functions_framework
from google.cloud import run_v2
from google.iam.v1 import iam_policy_pb2, policy_pb2


PROJECT_ID = os.environ["GCP_PROJECT_ID"]
REGION = os.environ.get("GCP_REGION", "us-central1")
SERVICE_NAME = os.environ.get("CLOUD_RUN_SERVICE", "mfs-backend")

# Matched verbatim by google_monitoring_alert_policy.budget_breaker_tripped.
TRIPPED_MARKER = "BUDGET_BREAKER_TRIPPED"
RESET_MARKER = "BUDGET_BREAKER_RESET"

# The binding that makes the backend a public API. Mirrors
# google_cloud_run_v2_service_iam_member.public in terraform/cloud_run.tf.
INVOKER_ROLE = "roles/run.invoker"
PUBLIC_MEMBER = "allUsers"


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
        # trip — return without rewriting an identical policy.
        print(f"{SERVICE_NAME} is already private, breaker already tripped.")
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


@functions_framework.http
def reset_cloud_run(request):
    """Restore public access. Idempotent — safe to run monthly."""
    client = run_v2.ServicesClient()
    resource = _service_path(client)
    policy = _get_policy(client, resource)

    if _is_public(policy):
        # The common case: the breaker never tripped this month.
        msg = f"{SERVICE_NAME} is already public, nothing to reset."
        print(msg)
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
    return msg, 200
