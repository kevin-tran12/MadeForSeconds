from google.cloud.firestore import Client

from .config import settings

_client: Client | None = None


def get_db() -> Client:
    global _client
    if _client is None:
        _client = Client(project=settings.gcp_project_id)
    return _client
