"""Database models for the recipe bank."""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from onigiri.config import settings
from onigiri.db import Base


def _utcnow() -> datetime:
    """Python-side update timestamp.

    A server-side `onupdate` leaves the attribute expired after a flush, so
    serialising the object afterwards triggers lazy IO outside the async context.
    """
    return datetime.now(UTC)


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=_utcnow,
        nullable=False,
    )


# --------------------------------------------------------------------------- enums


class SourceKind(str, enum.Enum):
    instagram = "instagram"
    short_video = "short_video"
    web = "web"
    photo = "photo"
    video_file = "video_file"
    text = "text"


class MediaKind(str, enum.Enum):
    image = "image"
    video = "video"
    audio = "audio"
    keyframe = "keyframe"
    thumbnail = "thumbnail"


class JobStatus(str, enum.Enum):
    queued = "queued"
    fetching = "fetching"
    transcribing = "transcribing"
    reading = "reading"
    extracting = "extracting"
    done = "done"
    needs_input = "needs_input"
    failed = "failed"


class RecipeStatus(str, enum.Enum):
    draft = "draft"
    needs_review = "needs_review"
    ready = "ready"


class UnitClass(str, enum.Enum):
    volume = "volume"
    weight = "weight"
    count = "count"
    length = "length"
    none = "none"


class TagKind(str, enum.Enum):
    cuisine = "cuisine"
    course = "course"
    diet = "diet"
    protein = "protein"
    time = "time"
    technique = "technique"
    custom = "custom"


class SuggestionStatus(str, enum.Enum):
    open = "open"
    accepted = "accepted"
    dismissed = "dismissed"


def _enum(e: type[enum.Enum], name: str) -> Enum:
    return Enum(e, name=name, values_callable=lambda x: [i.value for i in x])


# --------------------------------------------------------------------------- user


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _uuid_pk()
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)

    profile: Mapped[Profile | None] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )


class Profile(Base):
    """The taste profile: the app's memory of who it is cooking for."""

    __tablename__ = "profile"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    diet: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, nullable=False)
    allergies: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, nullable=False)
    dislikes: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, nullable=False)
    likes: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, nullable=False)
    pantry_staples: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, nullable=False)
    unit_system: Mapped[str] = mapped_column(String(16), default="metric", nullable=False)
    default_servings: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=_utcnow, nullable=False
    )

    user: Mapped[User] = relationship(back_populates="profile")


# --------------------------------------------------------------------------- sources


class Source(Base):
    """Everything captured verbatim from the outside world, kept for provenance."""

    __tablename__ = "sources"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[SourceKind] = mapped_column(_enum(SourceKind, "source_kind"), nullable=False)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    author: Mapped[str | None] = mapped_column(Text, nullable=True)
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    onscreen_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    photo_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcript: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    raw_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    media: Mapped[list[Media]] = relationship(
        back_populates="source",
        cascade="all, delete-orphan",
        order_by="Media.order_idx",
        lazy="selectin",
    )

    @property
    def transcript_text(self) -> str:
        if not self.transcript:
            return ""
        return (self.transcript or {}).get("text", "") or ""


class Media(Base):
    __tablename__ = "media"

    id: Mapped[uuid.UUID] = _uuid_pk()
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sources.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[MediaKind] = mapped_column(_enum(MediaKind, "media_kind"), nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    order_idx: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    source: Mapped[Source] = relationship(back_populates="media")


# --------------------------------------------------------------------------- jobs


class IngestJob(Base, TimestampMixin):
    __tablename__ = "ingest_jobs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sources.id", ondelete="SET NULL"), nullable=True
    )
    recipe_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recipes.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[JobStatus] = mapped_column(
        _enum(JobStatus, "job_status"), default=JobStatus.queued, nullable=False, index=True
    )
    input_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    stage_log: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    needs_input_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    usage: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    source: Mapped[Source | None] = relationship()


# --------------------------------------------------------------------------- recipes


class Recipe(Base, TimestampMixin):
    __tablename__ = "recipes"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sources.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    title_original: Mapped[str | None] = mapped_column(Text, nullable=True)
    language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    servings: Mapped[float | None] = mapped_column(Float, nullable=True)
    servings_unit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    prep_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cook_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hero_media_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("media.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[RecipeStatus] = mapped_column(
        _enum(RecipeStatus, "recipe_status"), default=RecipeStatus.draft, nullable=False
    )
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    review_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    profile_flags: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    equipment: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, nullable=False)
    favorite: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    search_tsv: Mapped[str | None] = mapped_column(TSVECTOR, nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(settings.embedding_dim), nullable=True
    )

    source: Mapped[Source | None] = relationship(lazy="selectin")
    hero_media: Mapped[Media | None] = relationship(lazy="selectin", foreign_keys=[hero_media_id])
    groups: Mapped[list[IngredientGroup]] = relationship(
        back_populates="recipe",
        cascade="all, delete-orphan",
        order_by="IngredientGroup.order_idx",
        lazy="selectin",
    )
    steps: Mapped[list[Step]] = relationship(
        back_populates="recipe",
        cascade="all, delete-orphan",
        order_by="Step.order_idx",
        lazy="selectin",
    )
    tags: Mapped[list[RecipeTag]] = relationship(
        back_populates="recipe", cascade="all, delete-orphan", lazy="selectin"
    )
    cook_log: Mapped[list[CookLog]] = relationship(
        back_populates="recipe",
        cascade="all, delete-orphan",
        order_by="CookLog.cooked_at.desc()",
        lazy="selectin",
    )

    __table_args__ = (
        Index("ix_recipes_user_updated", "user_id", "updated_at"),
        Index("ix_recipes_user_status", "user_id", "status"),
        Index("ix_recipes_search_tsv", "search_tsv", postgresql_using="gin"),
        Index(
            "ix_recipes_title_trgm",
            "title",
            postgresql_using="gin",
            postgresql_ops={"title": "gin_trgm_ops"},
        ),
    )


class IngredientGroup(Base):
    __tablename__ = "ingredient_groups"

    id: Mapped[uuid.UUID] = _uuid_pk()
    recipe_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recipes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    order_idx: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    recipe: Mapped[Recipe] = relationship(back_populates="groups")
    ingredients: Mapped[list[Ingredient]] = relationship(
        back_populates="group",
        cascade="all, delete-orphan",
        order_by="Ingredient.order_idx",
        lazy="selectin",
    )


class Ingredient(Base):
    __tablename__ = "ingredients"

    id: Mapped[uuid.UUID] = _uuid_pk()
    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ingredient_groups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    order_idx: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    raw: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    quantity_max: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    unit_class: Mapped[UnitClass] = mapped_column(
        _enum(UnitClass, "unit_class"), default=UnitClass.none, nullable=False
    )
    item: Mapped[str | None] = mapped_column(Text, nullable=True)
    preparation: Mapped[str | None] = mapped_column(Text, nullable=True)
    optional: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    scalable: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    group: Mapped[IngredientGroup] = relationship(back_populates="ingredients")

    __table_args__ = (
        Index(
            "ix_ingredients_item_trgm",
            "item",
            postgresql_using="gin",
            postgresql_ops={"item": "gin_trgm_ops"},
        ),
    )


class Step(Base):
    __tablename__ = "steps"

    id: Mapped[uuid.UUID] = _uuid_pk()
    recipe_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recipes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    order_idx: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    timer_seconds: Mapped[list[int]] = mapped_column(ARRAY(Integer), default=list, nullable=False)
    section: Mapped[str | None] = mapped_column(Text, nullable=True)

    recipe: Mapped[Recipe] = relationship(back_populates="steps")


# --------------------------------------------------------------------------- tags


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[TagKind] = mapped_column(
        _enum(TagKind, "tag_kind"), default=TagKind.custom, nullable=False
    )

    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_tag_user_name"),)


class RecipeTag(Base):
    __tablename__ = "recipe_tags"

    recipe_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recipes.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True
    )
    auto: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    recipe: Mapped[Recipe] = relationship(back_populates="tags")
    tag: Mapped[Tag] = relationship(lazy="selectin")


class Collection(Base, TimestampMixin):
    __tablename__ = "collections"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    order_idx: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_collection_user_name"),)


class CollectionItem(Base):
    __tablename__ = "collection_items"

    collection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("collections.id", ondelete="CASCADE"), primary_key=True
    )
    recipe_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recipes.id", ondelete="CASCADE"), primary_key=True
    )
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# --------------------------------------------------------------------------- memory


class CookLog(Base):
    __tablename__ = "cook_log"

    id: Mapped[uuid.UUID] = _uuid_pk()
    recipe_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recipes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    cooked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    rating: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    servings_made: Mapped[float | None] = mapped_column(Float, nullable=True)

    recipe: Mapped[Recipe] = relationship(back_populates="cook_log")

    __table_args__ = (
        CheckConstraint("rating is null or (rating >= 1 and rating <= 5)", name="ck_rating_range"),
    )


class ProfileSuggestion(Base):
    """A proposed change to the taste profile, inferred from what the owner does."""

    __tablename__ = "profile_suggestions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    field: Mapped[str | None] = mapped_column(String(32), nullable=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    status: Mapped[SuggestionStatus] = mapped_column(
        _enum(SuggestionStatus, "suggestion_status"), default=SuggestionStatus.open, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("user_id", "field", "value", name="uq_suggestion_user_field_value"),
    )


class ObservationKind(str, enum.Enum):
    edit = "edit"
    rating = "rating"
    note = "note"
    cooked = "cooked"


class Observation(Base):
    """Small facts about what the owner actually does, used to propose profile changes."""

    __tablename__ = "observations"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    recipe_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recipes.id", ondelete="CASCADE"), nullable=True
    )
    kind: Mapped[ObservationKind] = mapped_column(
        _enum(ObservationKind, "observation_kind"), nullable=False
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
