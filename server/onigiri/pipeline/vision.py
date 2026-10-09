"""Reading text out of images: recipe photos, and text burned into video frames."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from onigiri.config import settings
from onigiri.pipeline.media import prepare_for_vision
from onigiri.pipeline.prompts import PHOTO_SYSTEM
from onigiri.recipe_schema import PHOTO_JSON_SCHEMA_NAME, WirePhotoText
from onigiri.services import llm

log = logging.getLogger(__name__)

FRAMES_PER_CALL = 8


class FrameText(BaseModel):
    lines: list[str] = Field(
        description="Distinct lines of text burned into these frames, in the order seen."
    )


FRAME_SYSTEM = """\
You read text that is printed on top of cooking video frames: ingredient overlays,
step captions, quantities, oven temperatures, and titles.

Rules:
1. Report only text that is actually visible in the frames. Never guess at a partly
   covered word; skip it.
2. Ignore usernames, handles, follower counts, watermarks, "follow for more",
   subscribe prompts and platform interface text.
3. The same caption often stays on screen across several frames. Report each distinct
   line once.
4. Keep the original language and the original numbers and units exactly.
5. If no recipe-related text is visible, return an empty list.
"""


@dataclass
class PhotoReadResult:
    text: str = ""
    is_handwritten: bool = False
    has_recipe_text: bool = False
    low_confidence_lines: list[str] = field(default_factory=list)


async def read_photos(images: list[bytes], *, usage: llm.Usage | None = None) -> PhotoReadResult:
    """Read one recipe out of one or more photos (pages of the same recipe)."""
    if not images:
        return PhotoReadResult()

    content: list[dict] = [
        llm.text_part(
            "Read the recipe text from "
            + (
                f"these {len(images)} photos, which are pages of the same recipe in order."
                if len(images) > 1
                else "this photo."
            )
        )
    ]
    for data in images[:8]:
        content.append(llm.image_part(prepare_for_vision(data)))

    result: WirePhotoText = await llm.structured(
        WirePhotoText,
        PHOTO_SYSTEM,
        content,
        schema_name=PHOTO_JSON_SCHEMA_NAME,
        usage=usage,
    )
    return PhotoReadResult(
        text=result.text.strip(),
        is_handwritten=result.is_handwritten,
        has_recipe_text=result.has_recipe_text,
        low_confidence_lines=[line for line in result.low_confidence_lines if line.strip()],
    )


def _dedupe_lines(lines: list[str]) -> list[str]:
    """Drop repeats and near-repeats while preserving order."""
    out: list[str] = []
    seen: set[str] = set()
    for line in lines:
        clean = " ".join(line.split()).strip(" .")
        if len(clean) < 2:
            continue
        key = clean.lower()
        if key in seen:
            continue
        # a line already contained in a longer kept line adds nothing
        if any(key in prev.lower() for prev in out):
            continue
        out = [prev for prev in out if prev.lower() not in key]
        seen.add(key)
        out.append(clean)
    return out


async def read_keyframes(frames: list[bytes], *, usage: llm.Usage | None = None) -> str:
    """Read on-screen text from sampled video frames, in batches."""
    if not frames:
        return ""

    batches = [frames[i : i + FRAMES_PER_CALL] for i in range(0, len(frames), FRAMES_PER_CALL)]
    coros = []
    for batch_index, batch in enumerate(batches):
        content: list[dict] = [
            llm.text_part(
                f"Frames {batch_index * FRAMES_PER_CALL + 1} onwards, in time order. "
                "List the distinct on-screen text."
            )
        ]
        for data in batch:
            content.append(llm.image_part(prepare_for_vision(data, max_edge=1024)))
        coros.append(
            llm.structured(
                FrameText,
                FRAME_SYSTEM,
                content,
                schema_name="frame_text",
                effort=settings.anthropic_frame_effort,
                usage=usage,
            )
        )

    async def safe(coro):
        try:
            return await coro
        except llm.LLMNotConfigured:
            raise
        except llm.LLMError as exc:
            log.info("a batch of frames could not be read: %s", exc)
            return None

    all_lines: list[str] = []
    results = await llm.gather_limited([safe(c) for c in coros], limit=3)
    read = [res for res in results if isinstance(res, FrameText)]
    if not read:
        raise llm.LLMError("None of the video frames could be read.")
    for res in read:
        all_lines.extend(res.lines)
    return "\n".join(_dedupe_lines(all_lines))
