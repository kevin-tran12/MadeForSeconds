"""Shared helpers every tool module in this package uses.

tool_errors translates the domain exceptions services/recipes.py, uploads.py,
and instagram.py raise into structured dicts the model can act on — a 4xx-ish
outcome the caller can read and retry differently, not an opaque failure. It
sits directly under @mcp.tool() (applied via each module's register()) on
every tool function, so a failure never surfaces as a raw traceback to the
model or the operator.
"""

import functools
import logging

from pydantic import ValidationError

from ..services import instagram
from ..services import recipes as recipe_service

logger = logging.getLogger(__name__)


def tool_errors(fn):
    """Translate domain/validation errors into structured dicts the LLM can act on."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ValidationError as exc:
            return {
                "error": "validation_error",
                "field_errors": [
                    {
                        "field": ".".join(str(p) for p in e["loc"]),
                        "message": e["msg"],
                        "type": e["type"],
                    }
                    for e in exc.errors()
                ],
            }
        except recipe_service.SlugConflict as exc:
            return {
                "error": "slug_conflict",
                "existing": exc.existing,
                "hint": (
                    "A recipe with this slug already exists (this is usually a retry). "
                    "Use update_recipe with the existing id, or change the title."
                ),
            }
        except recipe_service.InvalidCategories as exc:
            return {
                "error": "invalid_categories",
                "invalid": exc.invalid,
                "valid_categories": exc.allowed,
            }
        except recipe_service.RecipeNotFound as exc:
            return {"error": "not_found", "message": f"Recipe not found: {exc}"}
        except recipe_service.NotPublishable as exc:
            return {"error": "not_publishable", "problems": exc.problems}
        except recipe_service.RecipeServiceError as exc:
            return {"error": "invalid_request", "message": str(exc)}
        except instagram.InstagramError as exc:
            return {
                "error": "instagram_auth" if exc.auth else "instagram",
                "message": str(exc),
            }
        except ValueError as exc:
            return {"error": "invalid_request", "message": str(exc)}
        except Exception as exc:
            logger.exception("MCP tool %s failed", fn.__name__)
            return {"error": "internal", "message": str(exc)}

    return wrapper


def iso(value) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else value
