"""The app's memory of its cook: observations in, profile suggestions out."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from onigiri.models import (
    CookLog,
    Observation,
    ObservationKind,
    Profile,
    ProfileSuggestion,
    Recipe,
    RecipeTag,
    SuggestionStatus,
    Tag,
)
from onigiri.pipeline.prompts import SUGGESTION_SYSTEM
from onigiri.services import llm

log = logging.getLogger(__name__)

MIN_OBSERVATIONS = 6
PROFILE_FIELDS = {"diet", "allergies", "dislikes", "likes", "pantry_staples", "notes"}


class Suggestion(BaseModel):
    text: str = Field(description="One line the owner sees, e.g. 'Prefers less sugar in bakes'.")
    field: str = Field(
        description="One of diet, allergies, dislikes, likes, pantry_staples, notes."
    )
    value: str = Field(description="The value to add to that field, short and lowercase.")
    evidence: list[str] = Field(description="The observations that support this, quoted briefly.")


class SuggestionList(BaseModel):
    suggestions: list[Suggestion]


async def record(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    kind: ObservationKind,
    text: str,
    recipe_id: uuid.UUID | None = None,
) -> None:
    text = " ".join(text.split())[:500]
    if not text:
        return
    db.add(Observation(user_id=user_id, recipe_id=recipe_id, kind=kind, text=text))


def describe_edit(before: dict, after: dict) -> str | None:
    """Describe an edit in one line, or return None when it is not worth remembering."""
    interesting = []
    for key in ("servings", "total_min", "title"):
        if key in after and before.get(key) != after.get(key):
            interesting.append(f"{key}: {before.get(key)!r} -> {after.get(key)!r}")
    if after.get("ingredients_changed"):
        interesting.append(str(after["ingredients_changed"]))
    if after.get("notes") and after.get("notes") != before.get("notes"):
        interesting.append(f"note: {str(after['notes'])[:160]}")
    return "; ".join(interesting)[:500] or None


async def gather_evidence(db: AsyncSession, user_id: uuid.UUID, days: int = 180) -> list[str]:
    """Everything the suggester is allowed to reason from."""
    since = datetime.now(UTC) - timedelta(days=days)
    lines: list[str] = []

    observations = (
        await db.scalars(
            select(Observation)
            .where(Observation.user_id == user_id, Observation.created_at >= since)
            .order_by(desc(Observation.created_at))
            .limit(120)
        )
    ).all()
    for o in observations:
        lines.append(f"[{o.kind.value}] {o.text}")

    rated = (
        await db.execute(
            select(Recipe.title, CookLog.rating, CookLog.notes)
            .join(CookLog, CookLog.recipe_id == Recipe.id)
            .where(Recipe.user_id == user_id, CookLog.cooked_at >= since)
            .order_by(desc(CookLog.cooked_at))
            .limit(60)
        )
    ).all()
    for title, rating, notes in rated:
        bit = f"[cooked] {title}"
        if rating:
            bit += f", rated {rating}/5"
        if notes:
            bit += f", note: {notes[:160]}"
        lines.append(bit)

    top_tags = (
        await db.execute(
            select(Tag.name, func.count().label("n"))
            .join(RecipeTag, RecipeTag.tag_id == Tag.id)
            .join(Recipe, Recipe.id == RecipeTag.recipe_id)
            .join(CookLog, CookLog.recipe_id == Recipe.id)
            .where(Recipe.user_id == user_id, CookLog.rating >= 4)
            .group_by(Tag.name)
            .order_by(desc("n"))
            .limit(12)
        )
    ).all()
    for name, n in top_tags:
        if n >= 2:
            lines.append(f"[pattern] cooked and rated 4+ with tag '{name}' {n} times")

    return lines


def describe_profile(profile: Profile | None) -> str:
    if profile is None:
        return "The profile is empty."
    parts = []
    for field in ("diet", "allergies", "dislikes", "likes", "pantry_staples"):
        values = getattr(profile, field) or []
        if values:
            parts.append(f"{field}: {', '.join(values)}")
    if profile.notes.strip():
        parts.append(f"notes: {profile.notes.strip()[:500]}")
    return "\n".join(parts) if parts else "The profile is empty."


async def generate_suggestions(
    db: AsyncSession, *, user_id: uuid.UUID, profile: Profile | None
) -> list[ProfileSuggestion]:
    """Propose profile changes. Returns only what is new."""
    evidence = await gather_evidence(db, user_id)
    if len(evidence) < MIN_OBSERVATIONS:
        return []

    content = (
        "CURRENT PROFILE\n"
        + describe_profile(profile)
        + "\n\nOBSERVATIONS\n"
        + "\n".join(f"- {line}" for line in evidence[:120])
    )
    try:
        result = await llm.structured(
            SuggestionList,
            SUGGESTION_SYSTEM,
            content,
            schema_name="profile_suggestions",
            temperature=0.2,
        )
    except llm.LLMError as exc:
        log.info("suggestion generation skipped: %s", exc)
        return []

    existing = {
        (s.field, (s.value or "").lower())
        for s in (
            await db.scalars(select(ProfileSuggestion).where(ProfileSuggestion.user_id == user_id))
        ).all()
    }

    created: list[ProfileSuggestion] = []
    for s in result.suggestions[:3]:
        field = s.field.strip().lower()
        value = " ".join(s.value.split()).strip().lower()[:200]
        if field not in PROFILE_FIELDS or not value:
            continue
        if (field, value) in existing:
            continue
        if profile is not None and field != "notes":
            current = [v.lower() for v in (getattr(profile, field, None) or [])]
            if value in current:
                continue
        suggestion = ProfileSuggestion(
            user_id=user_id,
            text=s.text.strip()[:300],
            field=field,
            value=value,
            evidence={"lines": s.evidence[:5]},
        )
        db.add(suggestion)
        existing.add((field, value))
        created.append(suggestion)

    await db.flush()
    return created


def apply_suggestion(profile: Profile, suggestion: ProfileSuggestion) -> None:
    field = suggestion.field or ""
    value = suggestion.value or ""
    if not field or not value:
        return
    if field == "notes":
        profile.notes = (profile.notes + "\n" + value).strip() if profile.notes else value
        return
    current = list(getattr(profile, field, None) or [])
    if value not in current:
        current.append(value)
    setattr(profile, field, current)


async def open_suggestions(db: AsyncSession, user_id: uuid.UUID) -> list[ProfileSuggestion]:
    return list(
        (
            await db.scalars(
                select(ProfileSuggestion)
                .where(
                    ProfileSuggestion.user_id == user_id,
                    ProfileSuggestion.status == SuggestionStatus.open,
                )
                .order_by(desc(ProfileSuggestion.created_at))
            )
        ).all()
    )
