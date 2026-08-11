"""Budget circuit breaker for the MadeForSeconds Cloud Run backend.

Two entry points, deployed as two Gen2 functions from this one source zip:

  kill_cloud_run   Pub/Sub-triggered by billing budget notifications. When actual
                   spend crosses the budget, scales the backend to 0 instances.
  reset_cloud_run  HTTP-triggered by a monthly Cloud Scheduler job. Restores the
                   backend to 1 instance so the breaker re-closes at month rollover.

The log markers below are matched by a Cloud Monitoring log-based alert policy
(see terraform/billing.tf). Changing their text breaks that alert.
"""

import base64
import json
import os

import functions_framework
from google.cloud import run_v2


PROJECT_ID = os.environ["GCP_PROJECT_ID"]
REGION = os.environ.get("GCP_REGION", "us-central1")
SERVICE_NAME = os.environ.get("CLOUD_RUN_SERVICE", "mfs-backend")

# Matched verbatim by google_monitoring_alert_policy.budget_breaker_tripped.
TRIPPED_MARKER = "BUDGET_BREAKER_TRIPPED"
RESET_MARKER = "BUDGET_BREAKER_RESET"

# Steady-state scaling, kept in sync with the scaling block in cloud_run.tf.
NORMAL_MAX_INSTANCES = 1


def _service_path(client: run_v2.ServicesClient) -> str:
    return client.service_path(PROJECT_ID, REGION, SERVICE_NAME)


def _set_max_instances(client: run_v2.ServicesClient, service, max_instances: int):
    """Apply a new max-instance count to an already-fetched service."""
    service.template.scaling.max_instance_count = max_instances
    service.template.scaling.min_instance_count = 0
    operation = client.update_service(request=run_v2.UpdateServiceRequest(service=service))
    return operation.result()


@functions_framework.cloud_event
def kill_cloud_run(cloud_event):
    """Scale the backend to 0 when actual spend crosses the budget."""
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
    # "cost >= budget" would scale the service to 0 on any malformed message.
    if budget_amount <= 0:
        print(f"Ignoring budget notification with no budgetAmount: {budget_notification}")
        return

    if cost_amount < budget_amount:
        print(f"Cost ${cost_amount} still under budget ${budget_amount}, skipping.")
        return

    print(
        f"{TRIPPED_MARKER} cost=${cost_amount} budget=${budget_amount} "
        f"service={SERVICE_NAME} — scaling to 0 instances."
    )

    client = run_v2.ServicesClient()
    service = client.get_service(name=_service_path(client))
    result = _set_max_instances(client, service, 0)

    print(f"Cloud Run service {SERVICE_NAME} disabled. Revision: {result.latest_ready_revision}")


@functions_framework.http
def reset_cloud_run(request):
    """Restore the backend to normal scaling. Idempotent — safe to run monthly."""
    client = run_v2.ServicesClient()
    service = client.get_service(name=_service_path(client))

    current = service.template.scaling.max_instance_count
    if current == NORMAL_MAX_INSTANCES:
        # The common case: the breaker never tripped this month. Returning
        # early avoids churning a pointless new Cloud Run revision.
        msg = f"{SERVICE_NAME} already at {NORMAL_MAX_INSTANCES} max instances, nothing to reset."
        print(msg)
        return msg, 200

    print(
        f"{RESET_MARKER} service={SERVICE_NAME} max_instances={current}"
        f"->{NORMAL_MAX_INSTANCES} — restoring service."
    )

    result = _set_max_instances(client, service, NORMAL_MAX_INSTANCES)

    msg = f"Cloud Run service {SERVICE_NAME} restored. Revision: {result.latest_ready_revision}"
    print(msg)
    return msg, 200
