"""Parse a recipe from a PDF or plain text using Claude.

Production setup (TODO before deploying):
  1. Create the secret: echo -n "sk-ant-..." | gcloud secrets versions add anthropic-api-key --data-file=-
  2. In terraform/secrets.tf, add a google_secret_manager_secret resource for "anthropic-api-key"
  3. In terraform/cloud_run.tf, add an env block referencing it (same pattern as admin-emails)
"""

import base64
import os
from typing import Annotated

import anthropic
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from ..auth import require_admin

router = APIRouter(prefix="/api/admin", dependencies=[Depends(require_admin)])

SAVE_RECIPE_TOOL = {
    "name": "save_recipe",
    "description": "Save the extracted recipe data in structured form.",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Recipe title"},
            "description": {"type": "string", "description": "Short description or introduction"},
            "prep_time_minutes": {"type": "integer", "description": "Prep time in minutes"},
            "cook_time_minutes": {"type": "integer", "description": "Cook/total active time in minutes"},
            "servings": {"type": "integer", "description": "Number of servings"},
            "difficulty": {
                "type": "string",
                "enum": ["easy", "medium", "hard"],
                "description": "Recipe difficulty",
            },
            "categories": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Tags/categories e.g. ['japanese', 'noodles', 'pork']",
            },
            "ingredients": {
                "type": "array",
                "description": "All ingredients, grouped by section when the recipe has distinct components",
                "items": {
                    "type": "object",
                    "properties": {
                        "item": {"type": "string", "description": "Ingredient name"},
                        "amount": {"type": "string", "description": "Quantity as a number string, e.g. '1.5'"},
                        "unit": {"type": "string", "description": "Unit, e.g. 'cups', 'g', 'tbsp'. Empty string if none."},
                        "group": {
                            "type": "string",
                            "description": "Section name if the recipe has multiple components, e.g. 'For the broth'. Omit if flat list.",
                        },
                    },
                    "required": ["item", "amount", "unit"],
                },
            },
            "instructions": {
                "type": "array",
                "description": "Numbered steps in order",
                "items": {
                    "type": "object",
                    "properties": {
                        "step": {"type": "integer"},
                        "text": {"type": "string"},
                        "tip": {
                            "type": "string",
                            "description": "Optional cooking tip or visual cue for this step. E.g. 'The garlic should be golden, not brown' or 'Dough is ready when it springs back slowly'.",
                        },
                    },
                    "required": ["step", "text"],
                },
            },
            "nutrition": {
                "type": "array",
                "description": "Per-serving nutrition entries if present in the source",
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string", "description": "e.g. 'Calories', 'Protein', 'Vitamin C', 'Sodium'"},
                        "value": {"type": "number"},
                        "unit": {"type": "string", "description": "e.g. 'kcal', 'g', 'mg'. Empty string if none."},
                    },
                    "required": ["label", "value", "unit"],
                },
            },
        },
        "required": ["title", "ingredients", "instructions"],
    },
}


@router.post("/parse-recipe")
async def parse_recipe(
    file: Annotated[UploadFile | None, File()] = None,
    text: Annotated[str | None, Form()] = None,
):
    """Accept a PDF or plain text and return structured recipe data extracted by Claude."""
    if not file and not text:
        raise HTTPException(status_code=400, detail="Provide either a PDF file or recipe text.")

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="ANTHROPIC_API_KEY is not configured.")

    client = anthropic.Anthropic(api_key=api_key)

    # Build message content
    if file:
        if file.content_type != "application/pdf":
            raise HTTPException(status_code=400, detail="Only PDF files are supported.")
        data = await file.read()
        b64 = base64.standard_b64encode(data).decode()
        content = [
            {
                "type": "document",
                "source": {"type": "base64", "media_type": "application/pdf", "data": b64},
            },
            {"type": "text", "text": "Extract the recipe from this document and call save_recipe with the structured data."},
        ]
    else:
        content = [
            {
                "type": "text",
                "text": f"Extract the recipe from the following text and call save_recipe with the structured data.\n\n{text}",
            }
        ]

    try:
        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=4096,
            thinking={"type": "adaptive"},
            tools=[SAVE_RECIPE_TOOL],
            tool_choice={"type": "tool", "name": "save_recipe"},
            messages=[{"role": "user", "content": content}],
        )
    except anthropic.APIError as exc:
        raise HTTPException(status_code=502, detail=f"Claude API error: {exc}") from exc

    tool_use = next((b for b in response.content if b.type == "tool_use"), None)
    if not tool_use:
        raise HTTPException(status_code=502, detail="Claude did not return structured recipe data.")

    # Return the extracted data; matches RecipeFormData shape on the frontend
    return {**tool_use.input, "published": False}
