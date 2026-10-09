"""The contract between the language model and the database.

`ExtractedRecipe` is what the extractor must return. It is deliberately strict:
every field the model is unsure about has an explicit "unknown" representation so
that a missing step is visible as missing rather than invented.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

UnitClassLiteral = Literal["volume", "weight", "count", "length", "none"]


class ExtractedIngredient(BaseModel):
    raw: str = Field(description="The ingredient exactly as it appeared in the source.")
    quantity: float | None = Field(
        default=None, description="Numeric amount, null when the source gives none."
    )
    quantity_max: float | None = Field(
        default=None, description="Upper bound when the source gives a range such as 2-3."
    )
    unit: str | None = Field(
        default=None, description="Unit as written, e.g. g, ml, tbsp, cup, clove. Null if none."
    )
    item: str = Field(description="The ingredient itself, in English, without amount or prep.")
    preparation: str | None = Field(
        default=None, description="Preparation note such as 'finely chopped'."
    )
    optional: bool = False


class ExtractedIngredientGroup(BaseModel):
    name: str | None = Field(
        default=None, description="Group heading such as 'For the sauce'. Null if ungrouped."
    )
    ingredients: list[ExtractedIngredient]


class ExtractedStep(BaseModel):
    text: str = Field(description="One instruction, in English, in the imperative.")
    section: str | None = Field(default=None, description="Optional heading this step sits under.")


class ExtractedRecipe(BaseModel):
    is_recipe: bool = Field(
        description="False when the source contains no recipe at all; everything else may be empty."
    )
    title: str = Field(description="Recipe title in English.")
    title_original: str | None = Field(
        default=None, description="Title in the source language, when that is not English."
    )
    language: str | None = Field(
        default=None, description="ISO 639-1 code of the source language, e.g. en, de, it."
    )
    description: str | None = Field(
        default=None, description="One or two sentences. Null if the source gives none."
    )
    servings: float | None = None
    servings_unit: str | None = Field(
        default=None, description="What a serving is, e.g. 'servings', 'cookies', 'loaf'."
    )
    prep_min: int | None = None
    cook_min: int | None = None
    total_min: int | None = None
    ingredient_groups: list[ExtractedIngredientGroup] = Field(default_factory=list)
    steps: list[ExtractedStep] = Field(default_factory=list)
    equipment: list[str] = Field(default_factory=list)
    tags: list[str] = Field(
        default_factory=list,
        description="Lowercase tags: cuisine, course, diet, main protein, technique.",
    )
    confidence: float = Field(
        ge=0.0, le=1.0, description="How completely the source specified this recipe."
    )
    missing: list[str] = Field(
        default_factory=list,
        description="Names of things the source did not state, e.g. 'oven temperature'.",
    )
    review_reason: str | None = Field(
        default=None,
        description="One line on why a human should check this, or null when nothing is missing.",
    )
    profile_flags: list[str] = Field(
        default_factory=list,
        description="Conflicts with the cook's allergies, diet or dislikes. Empty when none.",
    )


class ExtractedPhotoText(BaseModel):
    """What the vision model reads off a photo before any recipe structure is imposed."""

    text: str = Field(description="All readable text, in reading order, original language.")
    is_handwritten: bool = False
    has_recipe_text: bool = Field(
        description="False for a photo of a finished dish with no readable recipe."
    )
    low_confidence_lines: list[str] = Field(
        default_factory=list, description="Lines that were hard to read and need checking."
    )


RECIPE_JSON_SCHEMA_NAME = "extracted_recipe"
PHOTO_JSON_SCHEMA_NAME = "photo_text"


# --------------------------------------------------------------------------- wire format
#
# What Claude is actually asked to return. Claude's structured outputs compile the
# schema into a grammar, and every optional field or nullable union multiplies its
# size: the richer model above, with nested optional fields, is rejected as "too
# complex". So the wire format is flat and has no optional or nullable fields at all.
# "Unknown" is an empty string or 0, and `to_extracted` turns those back into None.


class WireIngredient(BaseModel):
    group: str = Field(
        description="Heading this ingredient sits under, e.g. 'For the sauce'. Empty if none."
    )
    raw: str = Field(description="The ingredient exactly as the source wrote it, amount included.")
    quantity: float = Field(description="Numeric amount. 0 when the source gives no number.")
    quantity_max: float = Field(description="Upper bound of a range such as 2-3, else 0.")
    unit: str = Field(description="Unit as written, e.g. g, ml, tbsp, cup, clove. Empty if none.")
    item: str = Field(description="The ingredient itself, in English, without amount or prep.")
    preparation: str = Field(description="Preparation such as 'finely chopped'. Empty if none.")
    optional: bool


class WireStep(BaseModel):
    section: str = Field(description="Heading this step sits under. Empty if none.")
    text: str = Field(description="One instruction, in English, in the imperative.")


class WireRecipe(BaseModel):
    is_recipe: bool = Field(description="False when the source contains no recipe at all.")
    title: str = Field(description="Recipe title in English.")
    title_original: str = Field(
        description="Title in the source language when that is not English, else empty."
    )
    language: str = Field(description="ISO 639-1 code of the source language, e.g. en, de.")
    description: str = Field(description="One or two sentences, or empty if the source has none.")
    servings: float = Field(description="How many it serves. 0 when the source does not say.")
    servings_unit: str = Field(description="What a serving is, e.g. 'servings', 'cookies'.")
    prep_min: int = Field(description="Preparation minutes. 0 when not stated.")
    cook_min: int = Field(description="Cooking minutes. 0 when not stated.")
    total_min: int = Field(description="Total minutes. 0 when not stated.")
    ingredients: list[WireIngredient]
    steps: list[WireStep]
    equipment: list[str]
    tags: list[str] = Field(description="3 to 8 lowercase tags: cuisine, course, diet, protein.")
    confidence: float = Field(description="0 to 1: how completely the source specified this.")
    missing: list[str] = Field(description="Things the source did not state.")
    review_reason: str = Field(
        description="One line on what a human should check, or empty when nothing is missing."
    )
    profile_flags: list[str] = Field(
        description="Conflicts with the cook's allergies, diet or dislikes. Empty when none."
    )


class WirePhotoText(BaseModel):
    text: str = Field(description="All readable text, in reading order, original language.")
    is_handwritten: bool
    has_recipe_text: bool = Field(
        description="False for a photo of a finished dish with no readable recipe."
    )
    low_confidence_lines: list[str] = Field(
        description="Lines that were hard to read and need checking. Empty when none."
    )


def _text(value: str) -> str | None:
    value = (value or "").strip()
    return value or None


def _positive(value: float) -> float | None:
    return value if value and value > 0 else None


def _minutes(value: int) -> int | None:
    return value if value and value > 0 else None


def to_extracted(wire: WireRecipe) -> ExtractedRecipe:
    """Convert Claude's flat answer into the richer shape the rest of the app uses."""
    groups: list[ExtractedIngredientGroup] = []
    by_name: dict[str, ExtractedIngredientGroup] = {}
    for ing in wire.ingredients:
        name = (ing.group or "").strip()
        group = by_name.get(name)
        if group is None:
            group = ExtractedIngredientGroup(name=name or None, ingredients=[])
            by_name[name] = group
            groups.append(group)
        quantity = _positive(ing.quantity)
        quantity_max = _positive(ing.quantity_max)
        if quantity is not None and quantity_max is not None and quantity_max <= quantity:
            quantity_max = None
        group.ingredients.append(
            ExtractedIngredient(
                raw=(ing.raw or ing.item).strip(),
                quantity=quantity,
                quantity_max=quantity_max,
                unit=_text(ing.unit),
                item=(ing.item or ing.raw).strip(),
                preparation=_text(ing.preparation),
                optional=ing.optional,
            )
        )

    language = _text(wire.language)
    title_original = _text(wire.title_original)
    if title_original and title_original.casefold() == wire.title.strip().casefold():
        title_original = None

    return ExtractedRecipe(
        is_recipe=wire.is_recipe,
        title=wire.title.strip() or "Untitled recipe",
        title_original=title_original,
        language=language.lower()[:8] if language else None,
        description=_text(wire.description),
        servings=_positive(wire.servings),
        servings_unit=_text(wire.servings_unit),
        prep_min=_minutes(wire.prep_min),
        cook_min=_minutes(wire.cook_min),
        total_min=_minutes(wire.total_min),
        ingredient_groups=groups,
        steps=[
            ExtractedStep(text=s.text.strip(), section=_text(s.section))
            for s in wire.steps
            if s.text and s.text.strip()
        ],
        equipment=[e.strip() for e in wire.equipment if e and e.strip()],
        tags=[t.strip().lower() for t in wire.tags if t and t.strip()],
        confidence=min(1.0, max(0.0, wire.confidence)),
        missing=[m.strip() for m in wire.missing if m and m.strip()],
        review_reason=_text(wire.review_reason),
        profile_flags=[f.strip() for f in wire.profile_flags if f and f.strip()],
    )
