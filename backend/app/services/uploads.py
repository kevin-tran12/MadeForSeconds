"""GCS upload/cleanup helpers shared by the admin routes and the MCP server.

Signed URLs must work on Cloud Run, where the metadata-server credentials
carry no private key — signing is routed through the IAM signBlob API by
passing service_account_email + access_token to generate_signed_url.
"""

import re
from datetime import timedelta

import google.auth
from google.auth import credentials as google_auth_credentials
from google.auth.transport import requests as google_auth_requests
from google.cloud import storage

from ..config import settings

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
ALLOWED_RECEIPT_TYPES = ALLOWED_IMAGE_TYPES | {"image/heic", "application/pdf"}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB


# ── Blob naming & cleanup ─────────────────────────────────────────────────────

def gcs_blob_name(url: str, bucket_name: str) -> str | None:
    """Extract blob name from https://storage.googleapis.com/{bucket}/{blob} URL.

    Returns None for dev placeholder URLs, missing values, or a different bucket.
    """
    if not url or not bucket_name:
        return None
    prefix = f"https://storage.googleapis.com/{bucket_name}/"
    if url.startswith(prefix):
        return url[len(prefix):]
    return None


def delete_gcs_blob(bucket_name: str, blob_name: str) -> None:
    """Delete a GCS blob, silently ignoring errors.

    No-op in dev mode or when bucket/blob name is missing, so recipe
    operations are never blocked by GCS cleanup failures.
    """
    if settings.is_dev or not bucket_name or not blob_name:
        return
    try:
        storage.Client().bucket(bucket_name).blob(blob_name).delete()
    except Exception:
        pass


def delete_recipe_image_blob(url: str | None) -> None:
    """Delete a recipe image blob given its public URL (no-op for foreign URLs)."""
    if blob := gcs_blob_name(url or "", settings.gcs_bucket_name or ""):
        delete_gcs_blob(settings.gcs_bucket_name, blob)


def delete_recipe_receipt_blob(url: str | None) -> None:
    """Delete a recipe receipt blob given its public URL (no-op for foreign URLs)."""
    if blob := gcs_blob_name(url or "", settings.gcs_receipts_bucket_name or ""):
        delete_gcs_blob(settings.gcs_receipts_bucket_name, blob)


def sanitize_filename(name: str) -> str:
    """Strip path components and unsafe characters; cap length."""
    base = (name or "").replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", base)[:100]
    return cleaned or "upload"


# ── Signed URLs ───────────────────────────────────────────────────────────────

def _signing_kwargs() -> dict:
    """Extra kwargs so generate_signed_url works without a local private key.

    Service-account key files implement Signing and need nothing extra.
    Cloud Run metadata credentials cannot sign locally, so pass the SA
    email + access token and let the storage library call IAM signBlob
    (requires roles/iam.serviceAccountTokenCreator on the SA itself).
    """
    credentials, _ = google.auth.default()
    if isinstance(credentials, google_auth_credentials.Signing):
        return {}
    credentials.refresh(google_auth_requests.Request())
    email = getattr(credentials, "service_account_email", None)
    if not email or email == "default":
        return {}
    return {"service_account_email": email, "access_token": credentials.token}


def signed_get_url(bucket_name: str, blob_name: str, *, expires_minutes: int = 15) -> str:
    """Time-limited download URL for a private blob."""
    blob = storage.Client().bucket(bucket_name).blob(blob_name)
    return blob.generate_signed_url(
        version="v4",
        expiration=timedelta(minutes=expires_minutes),
        method="GET",
        **_signing_kwargs(),
    )


def signed_put_url(
    bucket_name: str,
    blob_name: str,
    content_type: str,
    *,
    max_bytes: int = MAX_UPLOAD_BYTES,
    expires_minutes: int = 15,
) -> dict:
    """Time-limited upload URL; GCS enforces the size cap server-side."""
    blob = storage.Client().bucket(bucket_name).blob(blob_name)
    size_header = {"x-goog-content-length-range": f"0,{max_bytes}"}
    url = blob.generate_signed_url(
        version="v4",
        expiration=timedelta(minutes=expires_minutes),
        method="PUT",
        content_type=content_type,
        headers=size_header,
        **_signing_kwargs(),
    )
    return {
        "upload_url": url,
        "method": "PUT",
        "required_headers": {"Content-Type": content_type, **size_header},
        "expires_in_seconds": expires_minutes * 60,
    }
