"""Finding recipes: full text, fuzzy title, and meaning, fused into one ranking.

Three retrievers disagree usefully. Full text nails exact words, trigram catches
typos and partial titles, and the embedding catches "something cozy with lentils".
Reciprocal rank fusion merges them without having to normalise three different score
scales against each other.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from onigiri.models import (
    CollectionItem,
    Recipe,
    RecipeStatus,
    RecipeTag,
)
from onigiri.services import llm

log = logging.getLogger(__name__)

RRF_K = 60
FTS_LIMIT = 120
TRGM_LIMIT = 60
VECTOR_LIMIT = 60
TRGM_THRESHOLD = 0.12


@dataclass
class SearchFilters:
    tag_ids: list[uuid.UUID] | None = None
    collection_id: uuid.UUID | None = None
    status: RecipeStatus | None = None
    max_total_min: int | None = None
    favorite: bool | None = None
    source_kind: str | None = None


def _apply_filters(stmt: Select, user_id: uuid.UUID, f: SearchFilters) -> Select:
    stmt = stmt.where(Recipe.user_id == user_id)
    if f.status is not None:
        stmt = stmt.where(Recipe.status == f.status)
    if f.favorite is not None:
        stmt = stmt.where(Recipe.favorite.is_(f.favorite))
    if f.max_total_min:
        stmt = stmt.where(and_(Recipe.total_min.is_not(None), Recipe.total_min <= f.max_total_min))
    if f.collection_id:
        stmt = stmt.where(
            Recipe.id.in_(
                select(CollectionItem.recipe_id).where(
                    CollectionItem.collection_id == f.collection_id
                )
            )
        )
    if f.tag_ids:
        for tag_id in f.tag_ids:
            stmt = stmt.where(
                Recipe.id.in_(select(RecipeTag.recipe_id).where(RecipeTag.tag_id == tag_id))
            )
    return stmt


async def _fts_ids(
    db: AsyncSession, user_id: uuid.UUID, q: str, f: SearchFilters
) -> list[uuid.UUID]:
    tsquery = func.websearch_to_tsquery("english", q)
    simple_query = func.websearch_to_tsquery("simple", q)
    condition = or_(Recipe.search_tsv.op("@@")(tsquery), Recipe.search_tsv.op("@@")(simple_query))
    rank = func.greatest(
        func.ts_rank_cd(Recipe.search_tsv, tsquery),
        func.ts_rank_cd(Recipe.search_tsv, simple_query),
    )
    stmt = select(Recipe.id).where(condition).order_by(rank.desc()).limit(FTS_LIMIT)
    stmt = _apply_filters(stmt, user_id, f)
    return list((await db.scalars(stmt)).all())


async def _trigram_ids(
    db: AsyncSession, user_id: uuid.UUID, q: str, f: SearchFilters
) -> list[uuid.UUID]:
    sim = func.similarity(Recipe.title, q)
    stmt = select(Recipe.id).where(sim > TRGM_THRESHOLD).order_by(sim.desc()).limit(TRGM_LIMIT)
    stmt = _apply_filters(stmt, user_id, f)
    return list((await db.scalars(stmt)).all())


async def _vector_ids(
    db: AsyncSession, user_id: uuid.UUID, q: str, f: SearchFilters
) -> list[uuid.UUID]:
    try:
        vector = await llm.embed(q)
    except llm.LLMError as exc:
        log.debug("semantic search unavailable: %s", exc)
        return []
    distance = Recipe.embedding.cosine_distance(vector)
    stmt = (
        select(Recipe.id)
        .where(Recipe.embedding.is_not(None))
        .order_by(distance)
        .limit(VECTOR_LIMIT)
    )
    stmt = _apply_filters(stmt, user_id, f)
    return list((await db.scalars(stmt)).all())


def reciprocal_rank_fusion(
    rankings: list[tuple[list[uuid.UUID], float]], k: int = RRF_K
) -> list[uuid.UUID]:
    """Fuse ranked id lists. Each list contributes weight/(k + rank)."""
    scores: dict[uuid.UUID, float] = {}
    for ids, weight in rankings:
        for rank, rid in enumerate(ids, start=1):
            scores[rid] = scores.get(rid, 0.0) + weight / (k + rank)
    return [rid for rid, _ in sorted(scores.items(), key=lambda kv: kv[1], reverse=True)]


ORDERINGS: dict[str, Any] = {
    "recent": Recipe.updated_at.desc(),
    "added": Recipe.created_at.desc(),
    "title": Recipe.title.asc(),
    "time": Recipe.total_min.asc().nulls_last(),
}


async def search_recipes(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    q: str | None = None,
    filters: SearchFilters | None = None,
    sort: str = "recent",
    limit: int = 40,
    offset: int = 0,
    semantic: bool = True,
) -> tuple[list[Recipe], int]:
    """Return a page of recipes and the total number that matched."""
    f = filters or SearchFilters()
    query = (q or "").strip()

    if not query:
        base = _apply_filters(select(Recipe), user_id, f)
        total = await db.scalar(
            _apply_filters(select(func.count()).select_from(Recipe), user_id, f)
        )
        stmt = base.order_by(ORDERINGS.get(sort, ORDERINGS["recent"])).limit(limit).offset(offset)
        rows = list((await db.scalars(stmt)).unique().all())
        return rows, int(total or 0)

    fts = await _fts_ids(db, user_id, query, f)
    trgm = await _trigram_ids(db, user_id, query, f)
    vec = await _vector_ids(db, user_id, query, f) if semantic else []

    fused = reciprocal_rank_fusion([(fts, 1.0), (trgm, 0.6), (vec, 0.8)])
    total = len(fused)
    page_ids = fused[offset : offset + limit]
    if not page_ids:
        return [], total

    rows = list((await db.scalars(select(Recipe).where(Recipe.id.in_(page_ids)))).unique().all())
    order = {rid: i for i, rid in enumerate(page_ids)}
    rows.sort(key=lambda r: order.get(r.id, 10**6))
    return rows, total


async def similar_recipes(
    db: AsyncSession, *, user_id: uuid.UUID, recipe: Recipe, limit: int = 6
) -> list[Recipe]:
    """Recipes close to this one in meaning, for 'more like this'."""
    if recipe.embedding is None:
        return []
    distance = Recipe.embedding.cosine_distance(recipe.embedding)
    stmt = (
        select(Recipe)
        .where(
            Recipe.user_id == user_id,
            Recipe.id != recipe.id,
            Recipe.embedding.is_not(None),
        )
        .order_by(distance)
        .limit(limit)
    )
    return list((await db.scalars(stmt)).unique().all())
