"""GCS upload/cleanup helpers shared by the admin routes and the MCP server.

Signed URLs must work on Cloud Run, where the metadata-server credentials
carry no private key — signing is routed through the IAM signBlob API by
passing service_account_email + access_token to generate_signed_url.
"""

import ipaddress
import re
import socket
import urllib.parse
from datetime import timedelta
from uuid import uuid4

import google.auth
import httpx
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


# ── Content sniffing ──────────────────────────────────────────────────────────

# HEIC/HEIF brands that may appear at bytes 8..12 of an ISO-BMFF container.
_HEIF_BRANDS = {b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1", b"heim", b"heis"}


def sniff_content_type(data: bytes) -> str | None:
    """Identify an upload from its magic bytes, ignoring any declared type.

    A browser-supplied Content-Type is attacker-controlled: renaming
    payload.html to photo.jpg is enough to get "image/jpeg" declared. Since
    the images bucket is world-readable, a file stored under an image type but
    holding markup would be served straight back to visitors. Trust the bytes.

    Returns None when the format is not recognised, which callers treat as a
    rejection rather than a pass.
    """
    if len(data) < 12:
        return None
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[4:8] == b"ftyp" and data[8:12] in _HEIF_BRANDS:
        return "image/heic"
    if data[:5] == b"%PDF-":
        return "application/pdf"
    return None


def verify_upload_type(data: bytes, allowed: set[str]) -> str:
    """Return the sniffed content type, or raise ValueError if disallowed.

    The returned value — not the client's declared type — is what should be
    handed to GCS, so the stored object's metadata always matches its bytes.
    """
    actual = sniff_content_type(data)
    if actual is None:
        raise ValueError(
            "Unrecognised file format. Allowed: " + ", ".join(sorted(allowed))
        )
    if actual not in allowed:
        raise ValueError(
            f"File content is {actual}, which is not permitted here. "
            "Allowed: " + ", ".join(sorted(allowed))
        )
    return actual


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


def fetch_image_to_gcs(source_url: str) -> str:
    """Fetch an image from a public https URL into the images bucket.

    SSRF guards: https only, the resolved address must be public, redirects
    are not followed, content-type must be an allowed image type, and the
    body is capped at MAX_UPLOAD_BYTES. (DNS-rebinding TOCTOU between the
    resolution check and the fetch is accepted risk — the tool sits behind
    MCP bearer auth and is only invoked by the admin.)

    Returns the public URL of the stored image. Raises ValueError on any
    rejected input.
    """
    parsed = urllib.parse.urlparse(source_url)
    if parsed.scheme != "https":
        raise ValueError("Only https:// URLs are allowed")
    if not parsed.hostname:
        raise ValueError("Invalid URL: no hostname")

    try:
        infos = socket.getaddrinfo(parsed.hostname, parsed.port or 443, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        raise ValueError(f"Could not resolve host: {exc}")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (
            ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_reserved or ip.is_multicast or ip.is_unspecified
        ):
            raise ValueError("URL resolves to a non-public address")

    data = b""
    with httpx.Client(follow_redirects=False, timeout=10.0) as client:
        with client.stream("GET", source_url) as resp:
            if resp.status_code != 200:
                raise ValueError(f"Fetch failed: HTTP {resp.status_code} (redirects are not followed)")
            content_type = resp.headers.get("content-type", "").split(";")[0].strip()
            if content_type not in ALLOWED_IMAGE_TYPES:
                raise ValueError(
                    f"Unsupported content type '{content_type}'. Allowed: {', '.join(sorted(ALLOWED_IMAGE_TYPES))}"
                )
            for chunk in resp.iter_bytes():
                data += chunk
                if len(data) > MAX_UPLOAD_BYTES:
                    raise ValueError(f"Image exceeds {MAX_UPLOAD_BYTES // 1024 // 1024}MB limit")

    filename = sanitize_filename(parsed.path.rsplit("/", 1)[-1] or "image")
    blob_name = f"{uuid4()}-{filename}"

    if settings.is_dev or not settings.gcs_bucket_name:
        return f"https://placehold.co/800x400?text={blob_name}"

    storage.Client().bucket(settings.gcs_bucket_name).blob(blob_name).upload_from_string(
        data, content_type=content_type
    )
    return f"https://storage.googleapis.com/{settings.gcs_bucket_name}/{blob_name}"


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
