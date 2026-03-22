"""Cloud Function triggered by budget alerts to disable Cloud Run when costs exceed threshold."""

import base64
import json
import os

import functions_framework
from google.cloud import run_v2


PROJECT_ID = os.environ["GCP_PROJECT_ID"]
REGION = os.environ.get("GCP_REGION", "us-central1")
SERVICE_NAME = "mfs-backend"


@functions_framework.cloud_event
def kill_cloud_run(cloud_event):
    """Disable Cloud Run service by setting max instances to 0."""
    data = base64.b64decode(cloud_event.data["message"]["data"]).decode("utf-8")
    budget_notification = json.loads(data)

    cost_amount = budget_notification.get("costAmount", 0)
    budget_amount = budget_notification.get("budgetAmount", 0)

    # Only kill if actual cost exceeds budget
    if float(cost_amount) < float(budget_amount):
        print(f"Cost ${cost_amount} still under budget ${budget_amount}, skipping.")
        return

    print(f"ALERT: Cost ${cost_amount} exceeded budget ${budget_amount}. Disabling Cloud Run service.")

    client = run_v2.ServicesClient()
    service_path = client.service_path(PROJECT_ID, REGION, SERVICE_NAME)

    service = client.get_service(name=service_path)
    service.template.scaling.max_instance_count = 0
    service.template.scaling.min_instance_count = 0

    update_request = run_v2.UpdateServiceRequest(service=service)
    operation = client.update_service(request=update_request)
    result = operation.result()

    print(f"Cloud Run service {SERVICE_NAME} disabled. Revision: {result.latest_ready_revision}")
