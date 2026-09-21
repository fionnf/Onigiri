"""Request and response shapes for the HTTP API."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from onigiri.models import JobStatus, RecipeStatus, SourceKind, TagKind


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --------------------------------------------------------------------------- auth


class LoginRequest(BaseModel):
    email: str
    password: str


class MeResponse(BaseModel):
    id: uuid.UUID
    email: str


# --------------------------------------------------------------------------- profile


class ProfileOut(ORMModel):
    diet: list[str] = []
    allergies: list[str] = []
    dislikes: list[str] = []
    likes: list[str] = []
    pantry_staples: list[str] = []
    unit_system: str = "metric"
    default_servings: int | None = None
    notes: str = ""
    updated_at: datetime | None = None


class ProfileUpdate(BaseModel):
    diet: list[str] | None = None
    allergies: list[str] | None = None
    dislikes: list[str] | None = None
    likes: list[str] | None = None
    pantry_staples: list[str] | None = None
    unit_system: Literal["metric", "us"] | None = None
    default_servings: int | None = Field(default=None, ge=1, le=100)
    notes: str | None = None


class SuggestionOut(ORMModel):
    id: uuid.UUID
    text: str
    field: str | None
    value: str | None
    evidence: dict[str, Any] = {}
    status: str
    created_at: datetime


# --------------------------------------------------------------------------- media & source


class MediaOut(ORMModel):
    id: uuid.UUID
    kind: str
    content_type: str | None = None
    width: int | None = None
    height: int | None = None
    duration_s: float | None = None
    url: str | None = None


class TranscriptSegment(BaseModel):
    start: float
    end: float
    text: str


class SourceOut(ORMModel):
    id: uuid.UUID
    kind: SourceKind
    url: str | None = None
    title: str | None = None
    author: str | None = None
    caption: str | None = None
    page_text: str | None = None
    onscreen_text: str | None = None
    photo_text: str | None = None
    transcript_text: str | None = None
    transcript_segments: list[TranscriptSegment] = []
    language: str | None = None
    fetched_at: datetime | None = None
    media: list[MediaOut] = []


# --------------------------------------------------------------------------- recipes


class IngredientOut(ORMModel):
    id: uuid.UUID
    order_idx: int
    raw: str
    quantity: float | None = None
    quantity_max: float | None = None
    unit: str | None = None
    unit_class: str
    item: str | None = None
    preparation: str | None = None
    optional: bool
    scalable: bool
    display: str = ""


class IngredientGroupOut(ORMModel):
    id: uuid.UUID
    name: str | None = None
    order_idx: int
    ingredients: list[IngredientOut] = []


class StepOut(ORMModel):
    id: uuid.UUID
    order_idx: int
    text: str
    timer_seconds: list[int] = []
    section: str | None = None


class TagOut(ORMModel):
    id: uuid.UUID
    name: str
    kind: TagKind
    auto: bool = False


class CookLogOut(ORMModel):
    id: uuid.UUID
    cooked_at: datetime
    rating: int | None = None
    notes: str | None = None
    servings_made: float | None = None


class RecipeSummary(ORMModel):
    id: uuid.UUID
    title: str
    title_original: str | None = None
    description: str | None = None
    language: str | None = None
    status: RecipeStatus
    confidence: float | None = None
    review_reason: str | None = None
    total_min: int | None = None
    servings: float | None = None
    favorite: bool
    hero_url: str | None = None
    tags: list[TagOut] = []
    source_kind: SourceKind | None = None
    source_url: str | None = None
    updated_at: datetime
    created_at: datetime


class RecipeDetail(RecipeSummary):
    servings_unit: str | None = None
    prep_min: int | None = None
    cook_min: int | None = None
    equipment: list[str] = []
    notes: str = ""
    profile_flags: list[str] = []
    groups: list[IngredientGroupOut] = []
    steps: list[StepOut] = []
    cook_log: list[CookLogOut] = []
    source: SourceOut | None = None


class RecipeList(BaseModel):
    items: list[RecipeSummary]
    total: int
    limit: int
    offset: int


class IngredientIn(BaseModel):
    raw: str | None = None
    quantity: float | None = None
    quantity_max: float | None = None
    unit: str | None = None
    item: str | None = None
    preparation: str | None = None
    optional: bool = False
    scalable: bool = True


class IngredientGroupIn(BaseModel):
    name: str | None = None
    ingredients: list[IngredientIn] = []


class StepIn(BaseModel):
    text: str
    section: str | None = None


class RecipeCreate(BaseModel):
    title: str
    description: str | None = None
    servings: float | None = None
    servings_unit: str | None = None
    prep_min: int | None = None
    cook_min: int | None = None
    total_min: int | None = None
    equipment: list[str] = []
    notes: str = ""
    groups: list[IngredientGroupIn] = []
    steps: list[StepIn] = []
    tags: list[str] = []


class RecipeUpdate(BaseModel):
    title: str | None = None
    title_original: str | None = None
    description: str | None = None
    language: str | None = None
    servings: float | None = None
    servings_unit: str | None = None
    prep_min: int | None = None
    cook_min: int | None = None
    total_min: int | None = None
    equipment: list[str] | None = None
    notes: str | None = None
    favorite: bool | None = None
    status: RecipeStatus | None = None
    groups: list[IngredientGroupIn] | None = None
    steps: list[StepIn] | None = None
    tags: list[str] | None = None


class ScaledIngredientOut(BaseModel):
    id: str
    raw: str
    item: str
    preparation: str | None = None
    optional: bool
    quantity: float | None = None
    quantity_max: float | None = None
    unit: str | None = None
    display: str
    converted: bool
    scaled: bool


class ScaledGroupOut(BaseModel):
    id: str
    name: str | None = None
    ingredients: list[ScaledIngredientOut]


class ScaledRecipeOut(BaseModel):
    servings: float | None
    factor: float
    unit_system: str
    groups: list[ScaledGroupOut]


class CookLogIn(BaseModel):
    rating: int | None = Field(default=None, ge=1, le=5)
    notes: str | None = None
    servings_made: float | None = None
    cooked_at: datetime | None = None


# --------------------------------------------------------------------------- jobs


class IngestRequest(BaseModel):
    url: str | None = None
    text: str | None = None


class JobOut(ORMModel):
    id: uuid.UUID
    status: JobStatus
    input_url: str | None = None
    recipe_id: uuid.UUID | None = None
    source_id: uuid.UUID | None = None
    stage_log: list[dict[str, Any]] = []
    needs_input_reason: str | None = None
    error: str | None = None
    usage: dict[str, Any] = {}
    created_at: datetime
    updated_at: datetime


class JobInput(BaseModel):
    text: str | None = None


# --------------------------------------------------------------------------- tags etc.


class TagCreate(BaseModel):
    name: str
    kind: TagKind = TagKind.custom


class TagUpdate(BaseModel):
    name: str | None = None
    kind: TagKind | None = None


class TagWithCount(ORMModel):
    id: uuid.UUID
    name: str
    kind: TagKind
    count: int = 0


class CollectionCreate(BaseModel):
    name: str


class CollectionUpdate(BaseModel):
    name: str | None = None
    order_idx: int | None = None


class CollectionOut(ORMModel):
    id: uuid.UUID
    name: str
    order_idx: int
    count: int = 0


class LibraryStats(BaseModel):
    total: int
    needs_review: int
    ready: int
    favorites: int
    jobs_running: int
    jobs_last_30_days: int
    usage_last_30_days: dict[str, Any]
