"""Tags, collections, library statistics and the whole-bank export."""

from __future__ import annotations

import io
import json
import uuid
import zipfile
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import delete, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from onigiri.db import get_db
from onigiri.models import (
    Collection,
    CollectionItem,
    IngestJob,
    JobStatus,
    Recipe,
    RecipeStatus,
    RecipeTag,
    Tag,
    User,
)
from onigiri.schemas import (
    CollectionCreate,
    CollectionOut,
    CollectionUpdate,
    LibraryStats,
    TagUpdate,
    TagWithCount,
)
from onigiri.security import current_user
from onigiri.serializers import recipe_detail

router = APIRouter(prefix="/api", tags=["library"])


# --------------------------------------------------------------------------- tags


@router.get("/tags", response_model=list[TagWithCount])
async def list_tags(
    db: AsyncSession = Depends(get_db), user: User = Depends(current_user)
) -> list[TagWithCount]:
    rows = (
        await db.execute(
            select(Tag.id, Tag.name, Tag.kind, func.count(RecipeTag.recipe_id).label("n"))
            .outerjoin(RecipeTag, RecipeTag.tag_id == Tag.id)
            .where(Tag.user_id == user.id)
            .group_by(Tag.id, Tag.name, Tag.kind)
            .order_by(desc("n"), Tag.name)
        )
    ).all()
    return [TagWithCount(id=r[0], name=r[1], kind=r[2], count=r[3]) for r in rows]


@router.patch("/tags/{tag_id}", response_model=TagWithCount)
async def update_tag(
    tag_id: uuid.UUID,
    body: TagUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
) -> TagWithCount:
    tag = await db.scalar(select(Tag).where(Tag.id == tag_id, Tag.user_id == user.id))
    if tag is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such tag")
    if body.name:
        name = " ".join(body.name.split()).strip().lower()[:64]
        clash = await db.scalar(
            select(Tag).where(Tag.user_id == user.id, Tag.name == name, Tag.id != tag.id)
        )
        if clash is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, "A tag with that name exists.")
        tag.name = name
    if body.kind:
        tag.kind = body.kind
    await db.flush()
    count = await db.scalar(
        select(func.count()).select_from(RecipeTag).where(RecipeTag.tag_id == tag.id)
    )
    return TagWithCount(id=tag.id, name=tag.name, kind=tag.kind, count=int(count or 0))


@router.delete("/tags/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tag(
    tag_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
) -> None:
    tag = await db.scalar(select(Tag).where(Tag.id == tag_id, Tag.user_id == user.id))
    if tag is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such tag")
    await db.delete(tag)


# --------------------------------------------------------------------------- collections


async def _collection_counts(db: AsyncSession, user: User) -> dict[uuid.UUID, int]:
    rows = (
        await db.execute(
            select(CollectionItem.collection_id, func.count())
            .join(Collection, Collection.id == CollectionItem.collection_id)
            .where(Collection.user_id == user.id)
            .group_by(CollectionItem.collection_id)
        )
    ).all()
    return {r[0]: r[1] for r in rows}


@router.get("/collections", response_model=list[CollectionOut])
async def list_collections(
    db: AsyncSession = Depends(get_db), user: User = Depends(current_user)
) -> list[CollectionOut]:
    rows = (
        await db.scalars(
            select(Collection)
            .where(Collection.user_id == user.id)
            .order_by(Collection.order_idx, Collection.name)
        )
    ).all()
    counts = await _collection_counts(db, user)
    return [
        CollectionOut(id=c.id, name=c.name, order_idx=c.order_idx, count=counts.get(c.id, 0))
        for c in rows
    ]


@router.post("/collections", response_model=CollectionOut, status_code=201)
async def create_collection(
    body: CollectionCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
) -> CollectionOut:
    name = " ".join(body.name.split()).strip()[:120]
    if not name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Give the collection a name.")
    clash = await db.scalar(
        select(Collection).where(Collection.user_id == user.id, Collection.name == name)
    )
    if clash is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "You already have that collection.")
    highest = await db.scalar(
        select(func.max(Collection.order_idx)).where(Collection.user_id == user.id)
    )
    collection = Collection(user_id=user.id, name=name, order_idx=(highest or 0) + 1)
    db.add(collection)
    await db.flush()
    return CollectionOut(
        id=collection.id, name=collection.name, order_idx=collection.order_idx, count=0
    )


@router.patch("/collections/{collection_id}", response_model=CollectionOut)
async def update_collection(
    collection_id: uuid.UUID,
    body: CollectionUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
) -> CollectionOut:
    collection = await db.scalar(
        select(Collection).where(Collection.id == collection_id, Collection.user_id == user.id)
    )
    if collection is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such collection")
    if body.name:
        collection.name = " ".join(body.name.split()).strip()[:120]
    if body.order_idx is not None:
        collection.order_idx = body.order_idx
    await db.flush()
    counts = await _collection_counts(db, user)
    return CollectionOut(
        id=collection.id,
        name=collection.name,
        order_idx=collection.order_idx,
        count=counts.get(collection.id, 0),
    )


@router.delete("/collections/{collection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_collection(
    collection_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
) -> None:
    collection = await db.scalar(
        select(Collection).where(Collection.id == collection_id, Collection.user_id == user.id)
    )
    if collection is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such collection")
    await db.delete(collection)


async def _owned_collection(db: AsyncSession, user: User, collection_id: uuid.UUID) -> Collection:
    collection = await db.scalar(
        select(Collection).where(Collection.id == collection_id, Collection.user_id == user.id)
    )
    if collection is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such collection")
    return collection


@router.post("/collections/{collection_id}/items/{recipe_id}", status_code=204)
async def add_to_collection(
    collection_id: uuid.UUID,
    recipe_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
) -> None:
    await _owned_collection(db, user, collection_id)
    recipe = await db.scalar(
        select(Recipe).where(Recipe.id == recipe_id, Recipe.user_id == user.id)
    )
    if recipe is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such recipe")
    exists = await db.scalar(
        select(CollectionItem).where(
            CollectionItem.collection_id == collection_id,
            CollectionItem.recipe_id == recipe_id,
        )
    )
    if exists is None:
        db.add(CollectionItem(collection_id=collection_id, recipe_id=recipe_id))
        await db.flush()


@router.delete("/collections/{collection_id}/items/{recipe_id}", status_code=204)
async def remove_from_collection(
    collection_id: uuid.UUID,
    recipe_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
) -> None:
    await _owned_collection(db, user, collection_id)
    await db.execute(
        delete(CollectionItem).where(
            CollectionItem.collection_id == collection_id,
            CollectionItem.recipe_id == recipe_id,
        )
    )


# --------------------------------------------------------------------------- stats & export


@router.get("/stats", response_model=LibraryStats)
async def stats(
    db: AsyncSession = Depends(get_db), user: User = Depends(current_user)
) -> LibraryStats:
    since = datetime.now(UTC) - timedelta(days=30)

    async def count_recipes(*conditions) -> int:
        return int(
            await db.scalar(
                select(func.count())
                .select_from(Recipe)
                .where(Recipe.user_id == user.id, *conditions)
            )
            or 0
        )

    active = {
        JobStatus.queued,
        JobStatus.fetching,
        JobStatus.transcribing,
        JobStatus.reading,
        JobStatus.extracting,
    }
    jobs_running = int(
        await db.scalar(
            select(func.count())
            .select_from(IngestJob)
            .where(IngestJob.user_id == user.id, IngestJob.status.in_(active))
        )
        or 0
    )
    recent_jobs = (
        await db.scalars(
            select(IngestJob).where(IngestJob.user_id == user.id, IngestJob.created_at >= since)
        )
    ).all()
    usage = {"input_tokens": 0, "output_tokens": 0, "audio_seconds": 0.0, "calls": {}}
    for job in recent_jobs:
        u = job.usage or {}
        usage["input_tokens"] += int(u.get("input_tokens") or 0)
        usage["output_tokens"] += int(u.get("output_tokens") or 0)
        usage["audio_seconds"] += float(u.get("audio_seconds") or 0)
        for name, n in (u.get("calls") or {}).items():
            usage["calls"][name] = usage["calls"].get(name, 0) + n
    usage["audio_seconds"] = round(usage["audio_seconds"], 1)

    return LibraryStats(
        total=await count_recipes(),
        needs_review=await count_recipes(Recipe.status == RecipeStatus.needs_review),
        ready=await count_recipes(Recipe.status == RecipeStatus.ready),
        favorites=await count_recipes(Recipe.favorite.is_(True)),
        jobs_running=jobs_running,
        jobs_last_30_days=len(recent_jobs),
        usage_last_30_days=usage,
    )


@router.get("/export")
async def export_everything(
    db: AsyncSession = Depends(get_db), user: User = Depends(current_user)
) -> Response:
    """A zip of every recipe as Markdown, plus one JSON file with the lot."""
    from onigiri.routers.recipes import recipe_to_markdown

    recipes = list(
        (await db.scalars(select(Recipe).where(Recipe.user_id == user.id).order_by(Recipe.title)))
        .unique()
        .all()
    )

    buffer = io.BytesIO()
    payload = []
    used: set[str] = set()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for recipe in recipes:
            safe = (
                "".join(c for c in recipe.title if c.isalnum() or c in " -_").strip()[:60]
                or "recipe"
            )
            name = safe
            n = 2
            while name.lower() in used:
                name = f"{safe} ({n})"
                n += 1
            used.add(name.lower())
            zf.writestr(f"recipes/{name}.md", recipe_to_markdown(recipe))
            payload.append(recipe_detail(recipe).model_dump(mode="json"))
        zf.writestr(
            "onigiri-export.json",
            json.dumps(
                {
                    "exported_at": datetime.now(UTC).isoformat(),
                    "count": len(payload),
                    "recipes": payload,
                },
                indent=2,
                default=str,
            ),
        )

    stamp = datetime.now(UTC).strftime("%Y-%m-%d")
    return Response(
        content=buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="onigiri-{stamp}.zip"'},
    )
