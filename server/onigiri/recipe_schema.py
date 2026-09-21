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
