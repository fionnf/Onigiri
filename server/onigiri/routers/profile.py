"""The taste profile and the suggestions the app makes about it."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from onigiri.db import get_db
from onigiri.models import Profile, ProfileSuggestion, SuggestionStatus, User
from onigiri.schemas import ProfileOut, ProfileUpdate, SuggestionOut
from onigiri.security import current_user
from onigiri.services import memory

router = APIRouter(prefix="/api/me", tags=["profile"])


async def get_or_create_profile(db: AsyncSession, user: User) -> Profile:
    profile = await db.scalar(select(Profile).where(Profile.user_id == user.id))
    if profile is None:
        profile = Profile(user_id=user.id)
        db.add(profile)
        await db.flush()
    return profile


def _clean_list(values: list[str]) -> list[str]:
    out: list[str] = []
    for v in values:
        cleaned = " ".join(str(v).split()).strip().lower()[:80]
        if cleaned and cleaned not in out:
            out.append(cleaned)
    return out[:60]


@router.get("/profile", response_model=ProfileOut)
async def read_profile(
    db: AsyncSession = Depends(get_db), user: User = Depends(current_user)
) -> Profile:
    return await get_or_create_profile(db, user)


@router.put("/profile", response_model=ProfileOut)
async def update_profile(
    body: ProfileUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
) -> Profile:
    profile = await get_or_create_profile(db, user)
    data = body.model_dump(exclude_unset=True)
    for field in ("diet", "allergies", "dislikes", "likes", "pantry_staples"):
        if field in data and data[field] is not None:
            setattr(profile, field, _clean_list(data[field]))
    if data.get("unit_system"):
        profile.unit_system = data["unit_system"]
    if "default_servings" in data:
        profile.default_servings = data["default_servings"]
    if data.get("notes") is not None:
        profile.notes = data["notes"][:4000]
    await db.flush()
    return profile


@router.get("/profile/suggestions", response_model=list[SuggestionOut])
async def list_suggestions(
    db: AsyncSession = Depends(get_db), user: User = Depends(current_user)
) -> list[ProfileSuggestion]:
    return await memory.open_suggestions(db, user.id)


@router.post("/profile/suggestions/refresh", response_model=list[SuggestionOut])
async def refresh_suggestions(
    db: AsyncSession = Depends(get_db), user: User = Depends(current_user)
) -> list[ProfileSuggestion]:
    """Look over what the owner has been doing and propose profile changes."""
    profile = await get_or_create_profile(db, user)
    await memory.generate_suggestions(db, user_id=user.id, profile=profile)
    await db.flush()
    return await memory.open_suggestions(db, user.id)


async def _get_suggestion(
    db: AsyncSession, user: User, suggestion_id: uuid.UUID
) -> ProfileSuggestion:
    suggestion = await db.scalar(
        select(ProfileSuggestion).where(
            ProfileSuggestion.id == suggestion_id, ProfileSuggestion.user_id == user.id
        )
    )
    if suggestion is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such suggestion")
    return suggestion


@router.post("/profile/suggestions/{suggestion_id}/accept", response_model=ProfileOut)
async def accept_suggestion(
    suggestion_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
) -> Profile:
    suggestion = await _get_suggestion(db, user, suggestion_id)
    profile = await get_or_create_profile(db, user)
    memory.apply_suggestion(profile, suggestion)
    suggestion.status = SuggestionStatus.accepted
    await db.flush()
    return profile


@router.post("/profile/suggestions/{suggestion_id}/dismiss", status_code=status.HTTP_204_NO_CONTENT)
async def dismiss_suggestion(
    suggestion_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
) -> None:
    suggestion = await _get_suggestion(db, user, suggestion_id)
    suggestion.status = SuggestionStatus.dismissed
    await db.flush()
