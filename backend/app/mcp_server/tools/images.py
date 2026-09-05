"""Image/receipt ingestion tools: signed direct-to-GCS uploads, and a
server-side fetch for photos that are already hosted somewhere."""

import logging
from uuid import uuid4

from ...config import settings
from ...services import uploads
from ..wrapper import mcp_tool

logger = logging.getLogger(__name__)


@mcp_tool(read_only=False, budget="write")
def request_image_upload(filename: str, content_type: str, kind: str = "recipe_image") -> dict:
    """Get a short-lived signed PUT URL to upload a file directly to storage.

    kind="recipe_image" (JPEG/PNG/WebP; sanitized and made public once attached
    via update_recipe) or kind="receipt" (also HEIC/PDF → private receipts
    bucket).

    Upload the file bytes with an HTTP PUT to upload_url, sending exactly the
    required_headers (a ready-to-run curl_example is included). Then use
    final_url: pass it to update_recipe(image_url=...) for recipe images, or
    to create_expense(receipt_url=...) for receipts. Max 10MB; the URL
    expires in 15 minutes.
    """
    # recipe_image: the signed PUT targets the private staging bucket — the
    # backend has no visibility into these bytes until they're attached, so
    # they must never land directly in the public bucket. upload_bucket and
    # public_bucket deliberately stay separate variables here: final_url must
    # keep pointing at the public bucket (it's what gets saved as the
    # recipe's image_url and what sanitize_recipe_image matches against),
    # while the signed URL itself must point at staging. Collapsing these
    # into one variable would silently break both.
    if kind == "recipe_image":
        allowed = uploads.ALLOWED_IMAGE_TYPES
        upload_bucket = settings.gcs_staging_bucket_name
        public_bucket = settings.gcs_bucket_name
    elif kind == "receipt":
        allowed = uploads.ALLOWED_RECEIPT_TYPES
        upload_bucket = settings.gcs_receipts_bucket_name
        public_bucket = None
    else:
        raise ValueError("kind must be 'recipe_image' or 'receipt'")

    if content_type not in allowed:
        raise ValueError(
            f"Unsupported content type '{content_type}' for {kind}. Allowed: {', '.join(sorted(allowed))}"
        )

    safe_name = uploads.sanitize_filename(filename)
    if kind == "recipe_image":
        blob_name = f"{uuid4()}-{safe_name}"
        final_url = f"https://storage.googleapis.com/{public_bucket}/{blob_name}"
    else:
        blob_name = f"receipts/{uuid4()}-{safe_name}"
        final_url = f"gs://{upload_bucket}/{blob_name}"

    if settings.is_dev:
        dev_final = (
            f"https://placehold.co/800x400?text={blob_name}"
            if kind == "recipe_image"
            else f"dev://{blob_name}"
        )
        return {
            "upload_url": "dev://noop",
            "method": "PUT",
            "required_headers": {},
            "final_url": dev_final,
            "expires_in_seconds": 0,
            "note": "Dev mode: no real upload happens; use final_url directly.",
        }

    # recipe_image needs both buckets configured; receipt needs only one.
    # Reserved for is_dev above — a bucket missing in production must raise,
    # not silently fall back to the same dev-mode placeholder. That placeholder
    # is not a real upload URL; a caller saving it as a recipe's image_url or
    # an expense's receipt_url would be attaching fake data to real content.
    # config.validate_production_settings already refuses to start the
    # process in that state; this is the backstop in case that check ever has
    # a gap. Not a ValueError — this is a server misconfiguration, not bad
    # input, so it should surface through mcp_tool's generic
    # `except Exception` branch as {"error": "internal", ...} and get logged,
    # not read like something the caller could fix by retrying differently.
    if not upload_bucket or (kind == "recipe_image" and not public_bucket):
        raise uploads.StorageNotConfiguredError(
            f"backend storage is not fully configured for kind={kind!r}"
        )

    result = uploads.signed_put_url(upload_bucket, blob_name, content_type)
    header_flags = " ".join(f"-H '{k}: {v}'" for k, v in result["required_headers"].items())
    logger.info("MCP request_image_upload: kind=%s blob=%s", kind, blob_name)
    return {
        **result,
        "final_url": final_url,
        "curl_example": f"curl -X PUT {header_flags} --upload-file ./{safe_name} '{result['upload_url']}'",
    }


@mcp_tool(read_only=False, budget="write")
def upload_image_from_url(source_url: str) -> dict:
    """Copy an image from a public https URL into the recipe images bucket.

    Use when the photo is already hosted somewhere (e.g. a shared link).
    JPEG/PNG/WebP only, max 10MB, redirects are not followed. Returns
    {image_url} ready for create_recipe/update_recipe.
    """
    image_url = uploads.fetch_image_to_gcs(source_url)
    logger.info("MCP upload_image_from_url: %s", image_url)
    return {"image_url": image_url}


TOOLS = (request_image_upload, upload_image_from_url)


def register(mcp) -> None:
    """Register this module's tools on the server. Explicit, so the tool
    surface is this tuple, nothing else. Each tool's annotations (set by the
    @mcp_tool(...) decorator in wrapper.py) ride along so the server exposes
    them to clients."""
    for tool in TOOLS:
        mcp.tool(annotations=getattr(tool, "mcp_annotations", None))(tool)
