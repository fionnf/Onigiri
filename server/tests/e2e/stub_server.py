"""Run the real app with Claude stubbed, for the browser tests.

Everything else is real: the database, storage, ffmpeg, the job pipeline, the built
web app and its service worker. Only the paid model calls are replaced, with answers
derived from what was actually sent, so a test can tell its input reached Claude.
"""

from __future__ import annotations

import os
import re

import uvicorn

from onigiri.pipeline import vision
from onigiri.recipe_schema import WireIngredient, WireRecipe, WireStep
from onigiri.services import llm


def _first_caption_line(content) -> str:
    text = (
        content
        if isinstance(content, str)
        else " ".join(part.get("text", "") for part in content if isinstance(part, dict))
    )
    match = re.search(r"--- (?:CAPTION / POST TEXT|TEXT READ FROM PHOTOS) ---\n(.+)", text)
    return (match.group(1) if match else "Untitled").strip()[:80]


async def fake_structured(schema_model, system, content, *, schema_name, **kwargs):
    if schema_model is WireRecipe:
        title = _first_caption_line(content)
        return WireRecipe(
            is_recipe=True,
            title=title,
            title_original="",
            language="en",
            description="",
            servings=2,
            servings_unit="servings",
            prep_min=5,
            cook_min=20,
            total_min=25,
            ingredients=[
                WireIngredient(
                    group="",
                    raw="200 g red lentils",
                    quantity=200,
                    quantity_max=0,
                    unit="g",
                    item="red lentils",
                    preparation="",
                    optional=False,
                ),
                WireIngredient(
                    group="",
                    raw="1 onion",
                    quantity=1,
                    quantity_max=0,
                    unit="",
                    item="onion",
                    preparation="chopped",
                    optional=False,
                ),
            ],
            steps=[
                WireStep(section="", text="Fry the onion for 5 minutes."),
                WireStep(section="", text="Add the lentils and simmer for 20 minutes."),
            ],
            equipment=[],
            tags=["soup"],
            confidence=0.9,
            missing=[],
            review_reason="",
            profile_flags=[],
        )
    raise llm.LLMError(f"stub has no answer for {schema_name}")


async def fake_read_photos(images, **kwargs):
    sizes = ", ".join(str(len(data)) for data in images)
    return vision.PhotoReadResult(
        text=f"Photographed tomato soup\n(received {len(images)} photo, {sizes} bytes)",
        has_recipe_text=True,
    )


llm.structured = fake_structured
vision.read_photos = fake_read_photos

from onigiri.main import app  # noqa: E402 - after the stubs are in place

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ["PORT"]), log_level="warning")
