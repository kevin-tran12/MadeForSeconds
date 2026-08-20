"""GCS upload/cleanup helpers shared by the admin routes and the MCP server.

Signed URLs must work on Cloud Run, where the metadata-server credentials
carry no private key — signing is routed through the IAM signBlob API by
passing service_account_email + access_token to generate_signed_url.
"""

import ipaddress
import logging
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

logger = logging.getLogger(__name__)

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


# ── Metadata stripping ────────────────────────────────────────────────────────
#
# Phone cameras embed a GPS IFD in EXIF. The images bucket is world-readable, so
# an unstripped kitchen photo publishes the coordinates it was taken at.
#
# These strip containers rather than re-encoding through an imaging library. A
# Pillow round-trip would be five lines, but re-encoding a JPEG is lossy — every
# pass degrades the photo, and the photos are the product. Dropping the metadata
# segments leaves the compressed image data byte-for-byte identical.


class MetadataStripError(ValueError):
    """Raised when an image cannot be parsed well enough to strip metadata.

    Deliberately fails closed. Returning the original bytes on a parse failure
    would silently publish the GPS this function exists to remove.
    """


# APP1 carries EXIF (and the GPS IFD within it) plus XMP; APP13 carries
# Photoshop/IPTC records. APP0 (JFIF) and APP14 (Adobe colour transform) are
# kept — they describe how to decode the image, and dropping APP14 shifts
# colours on YCCK/CMYK files.
_JPEG_STRIP_MARKERS = frozenset({0xE1, 0xED})
_JPEG_COMMENT_MARKER = 0xFE

# PNG: the four critical chunks plus the ancillary ones that affect rendering.
# Everything else — eXIf, tEXt, iTXt, zTXt, tIME — carries no pixel information.
_PNG_KEEP_CHUNKS = frozenset({
    b"IHDR", b"PLTE", b"IDAT", b"IEND",
    b"tRNS", b"gAMA", b"cHRM", b"sRGB", b"iCCP", b"sBIT", b"bKGD", b"pHYs",
})

# WebP RIFF chunks holding metadata rather than pixels.
_WEBP_STRIP_CHUNKS = frozenset({b"EXIF", b"XMP "})


def _strip_jpeg(data: bytes) -> bytes:
    """Drop EXIF/XMP/IPTC/comment segments, preserving the entropy-coded scan."""
    if data[:2] != b"\xff\xd8":
        raise MetadataStripError("not a JPEG")

    out = bytearray(b"\xff\xd8")
    i, n = 2, len(data)
    while i < n - 1:
        if data[i] != 0xFF:
            raise MetadataStripError(f"desynchronised at byte {i}")
        marker = data[i + 1]

        # Fill bytes: any number of 0xFF may precede a marker.
        if marker == 0xFF:
            i += 1
            continue
        # Standalone markers carry no length field.
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            out += data[i:i + 2]
            i += 2
            continue
        # Start of scan: entropy-coded data runs to the end. Nothing after this
        # point is a metadata segment, so copy it through untouched.
        if marker == 0xDA:
            out += data[i:]
            return bytes(out)
        if marker == 0xD9:  # end of image
            out += data[i:i + 2]
            i += 2
            continue

        if i + 4 > n:
            raise MetadataStripError("truncated segment header")
        seglen = int.from_bytes(data[i + 2:i + 4], "big")
        end = i + 2 + seglen
        if seglen < 2 or end > n:
            raise MetadataStripError("segment length out of bounds")

        if marker not in _JPEG_STRIP_MARKERS and marker != _JPEG_COMMENT_MARKER:
            out += data[i:end]
        i = end

    return bytes(out)


def _strip_png(data: bytes) -> bytes:
    """Keep only chunks that affect decoding; drop textual and EXIF chunks."""
    signature = b"\x89PNG\r\n\x1a\n"
    if data[:8] != signature:
        raise MetadataStripError("not a PNG")

    out = bytearray(signature)
    i, n = 8, len(data)
    saw_end = False
    while i + 12 <= n:
        length = int.from_bytes(data[i:i + 4], "big")
        chunk_type = data[i + 4:i + 8]
        end = i + 12 + length  # length + type + payload + CRC
        if end > n:
            raise MetadataStripError("chunk length out of bounds")
        if chunk_type in _PNG_KEEP_CHUNKS:
            out += data[i:end]
        i = end
        if chunk_type == b"IEND":
            saw_end = True
            break

    if not saw_end:
        raise MetadataStripError("no IEND chunk")
    return bytes(out)


def _strip_webp(data: bytes) -> bytes:
    """Drop EXIF/XMP RIFF chunks and clear their flags in the VP8X header."""
    if data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        raise MetadataStripError("not a WebP")

    body = bytearray()
    i, n = 12, len(data)
    while i + 8 <= n:
        chunk_type = data[i:i + 4]
        size = int.from_bytes(data[i + 4:i + 8], "little")
        end = i + 8 + size + (size & 1)  # chunks pad to an even length
        if end > n:
            raise MetadataStripError("chunk size out of bounds")

        if chunk_type not in _WEBP_STRIP_CHUNKS:
            chunk = bytearray(data[i:end])
            # VP8X advertises which optional chunks follow. Leaving the EXIF and
            # XMP bits set after removing those chunks makes the file malformed.
            if chunk_type == b"VP8X" and len(chunk) >= 9:
                chunk[8] &= ~0b00001100
            body += chunk
        i = end

    out = bytearray(b"RIFF")
    out += (4 + len(body)).to_bytes(4, "little")
    out += b"WEBP"
    out += body
    return bytes(out)


_STRIPPERS = {
    "image/jpeg": _strip_jpeg,
    "image/png": _strip_png,
    "image/webp": _strip_webp,
}


def strip_image_metadata(data: bytes, content_type: str) -> bytes:
    """Return image bytes with location and identifying metadata removed.

    Lossless: the compressed image data is untouched, only container-level
    metadata is dropped. Raises MetadataStripError rather than returning the
    original bytes when parsing fails — this is a privacy control, so failing
    closed is the point.

    Content types with no stripper (HEIC, PDF) are returned unchanged. Neither
    is an allowed recipe-image type; receipts are private and stay as uploaded.
    """
    stripper = _STRIPPERS.get(content_type)
    if stripper is None:
        return data
    return stripper(data)


# Blob names are UUID-prefixed, so the bytes behind a given name never change —
# which is exactly the condition `immutable` requires.
PUBLIC_IMAGE_CACHE_CONTROL = "public, max-age=31536000, immutable"


class ImageSanitizationError(ValueError):
    """Raised when a recipe image is identified as one of ours but could not
    be sanitized.

    Distinct from a plain `False` return, which means "nothing to do" — dev
    mode, a foreign URL, a type this module doesn't strip (HEIC/PDF), or an
    object already clean. This means "we found an object that needed
    sanitizing and failed", and callers must treat it as an attachment
    failure: do not save a recipe pointing at it, and do not delete the image
    it would have replaced.
    """


def sanitize_public_image_blob(blob_name: str) -> bool:
    """Strip metadata and set caching on an image already sitting in the bucket.

    The MCP flow hands out a signed PUT URL, so the client uploads directly to
    GCS and the backend never sees those bytes — they cannot be cleaned on the
    way in. The backend does learn the object's name when the URL is attached to
    a recipe, which is the first and only chance to clean it.

    Returns True if the object was rewritten, False if there was nothing to do.
    Raises ImageSanitizationError — not silently — when the object exists and
    needs sanitizing but the attempt fails (permission error, GCS outage,
    unparseable bytes despite a recognised signature). A save that ignored
    that failure would publish a recipe pointing at a still-unsanitized image
    with no record anything went wrong.
    """
    bucket_name = settings.gcs_bucket_name
    if settings.is_dev or not bucket_name or not blob_name:
        return False

    try:
        blob = storage.Client().bucket(bucket_name).get_blob(blob_name)
    except Exception as exc:
        raise ImageSanitizationError(
            f"could not reach GCS to sanitize {blob_name}"
        ) from exc

    if blob is None:
        # image_url names an object in our own bucket that doesn't exist —
        # a broken reference, not a legitimate "nothing to sanitize" case.
        raise ImageSanitizationError(f"{blob_name} does not exist in {bucket_name}")

    try:
        data = blob.download_as_bytes()
    except Exception as exc:
        raise ImageSanitizationError(f"could not download {blob_name}") from exc

    content_type = sniff_content_type(data)
    if content_type not in _STRIPPERS:
        # Not a format this module strips. HEIC/PDF aren't allowed recipe-image
        # types to begin with, so this is unexpected but not itself unsafe —
        # nothing here claims to have cleaned it.
        return False

    try:
        cleaned = strip_image_metadata(data, content_type)
    except MetadataStripError as exc:
        raise ImageSanitizationError(
            f"could not parse {blob_name} to strip its metadata"
        ) from exc

    if cleaned == data and blob.cache_control == PUBLIC_IMAGE_CACHE_CONTROL:
        return False

    try:
        blob.cache_control = PUBLIC_IMAGE_CACHE_CONTROL
        blob.upload_from_string(cleaned, content_type=content_type)
    except Exception as exc:
        raise ImageSanitizationError(f"could not write sanitized {blob_name}") from exc

    return True


def sanitize_recipe_image(url: str | None) -> bool:
    """Sanitize a recipe image given its public URL (no-op for foreign URLs).

    Propagates ImageSanitizationError from sanitize_public_image_blob — see
    that function's docstring. Callers must not catch-and-ignore it.
    """
    if blob := gcs_blob_name(url or "", settings.gcs_bucket_name or ""):
        return sanitize_public_image_blob(blob)
    return False


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
