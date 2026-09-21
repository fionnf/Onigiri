"""Browsing, reading, editing, scaling and cooking recipes."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from onigiri.db import get_db
from onigiri.models import (
    CookLog,
    Ingredient,
    IngredientGroup,
    ObservationKind,
    Profile,
    Recipe,
    RecipeStatus,
    RecipeTag,
    SourceKind,
    Step,
    Tag,
    User,
)
from onigiri.pipeline.extract import (
    _is_scalable,
    get_or_create_tags,
    refresh_embedding,
    refresh_search_vector,
    run_extraction,
)
from onigiri.pipeline.extract import apply_extracted as apply_extracted_recipe
from onigiri.schemas import (
    CookLogIn,
    CookLogOut,
    RecipeCreate,
    RecipeDetail,
    RecipeList,
    RecipeSummary,
    RecipeUpdate,
    ScaledRecipeOut,
    TagCreate,
)
from onigiri.security import current_user
from onigiri.serializers import recipe_detail, recipe_summary
from onigiri.services import memory
from onigiri.services.scaling import scale_recipe
from onigiri.services.search import SearchFilters, search_recipes, similar_recipes
from onigiri.units import detect_timers, lookup_unit, parse_ingredient

router = APIRouter(prefix="/api/recipes", tags=["recipes"])


async def _get_recipe(db: AsyncSession, user: User, recipe_id: uuid.UUID) -> Recipe:
    recipe = await db.scalar(
        select(Recipe).where(Recipe.id == recipe_id, Recipe.user_id == user.id)
    )
    if recipe is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such recipe")
    return recipe


@router.get("", response_model=RecipeList)
async def list_recipes(
    q: str | None = None,
    tag: Annotated[list[uuid.UUID] | None, Query()] = None,
    collection: uuid.UUID | None = None,
    recipe_status: Annotated[RecipeStatus | None, Query(alias="status")] = None,
    favorite: bool | None = None,
    max_total_min: int | None = None,
    sort: str = "recent",
    limit: int = Query(default=40, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    semantic: bool = True,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
) -> RecipeList:
    rows, total = await search_recipes(
        db,
        user_id=user.id,
        q=q,
        filters=SearchFilters(
            tag_ids=tag,
            collection_id=collection,
            status=recipe_status,
            favorite=favorite,
            max_total_min=max_total_min,
        ),
        sort=sort,
        limit=limit,
        offset=offset,
        semantic=semantic,
    )
    return RecipeList(
        items=[recipe_summary(r) for r in rows], total=total, limit=limit, offset=offset
    )


@router.get("/{recipe_id}", response_model=RecipeDetail)
async def get_recipe(
    recipe_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
) -> RecipeDetail:
    return recipe_detail(await _get_recipe(db, user, recipe_id))


@router.get("/{recipe_id}/similar", response_model=list[RecipeSummary])
async def get_similar(
    recipe_id: uuid.UUID,
    limit: int = Query(default=6, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
) -> list[RecipeSummary]:
    recipe = await _get_recipe(db, user, recipe_id)
    rows = await similar_recipes(db, user_id=user.id, recipe=recipe, limit=limit)
    return [recipe_summary(r) for r in rows]


def _unit_class_enum(unit: str | None, quantity: float | None):
    from onigiri.models import UnitClass

    u = lookup_unit(unit)
    if u:
        return UnitClass(u.unit_class)
    if unit:
        return UnitClass.count
    return UnitClass.count if quantity is not None else UnitClass.none


async def _replace_groups(db: AsyncSession, recipe: Recipe, groups: list) -> None:
    await db.execute(delete(IngredientGroup).where(IngredientGroup.recipe_id == recipe.id))
    await db.flush()
    for gi, group in enumerate(groups):
        g = IngredientGroup(recipe_id=recipe.id, name=group.name, order_idx=gi)
        db.add(g)
        await db.flush()
        for ii, ing in enumerate(group.ingredients):
            raw = (ing.raw or "").strip()
            item = (ing.item or "").strip()
            quantity, quantity_max = ing.quantity, ing.quantity_max
            unit, preparation = ing.unit, ing.preparation
            if raw and not item:
                parsed = parse_ingredient(raw)
                item = parsed.item or raw
                if quantity is None:
                    quantity, quantity_max = parsed.quantity, parsed.quantity_max
                unit = unit or parsed.unit
                preparation = preparation or parsed.preparation
            if not raw:
                bits = []
                if quantity is not None:
                    from onigiri.units import format_quantity

                    bits.append(format_quantity(quantity))
                if unit:
                    bits.append(unit)
                if item:
                    bits.append(item)
                raw = " ".join(bits).strip() or item
            u = lookup_unit(unit)
            db.add(
                Ingredient(
                    group_id=g.id,
                    order_idx=ii,
                    raw=raw[:500],
                    quantity=quantity,
                    quantity_max=quantity_max,
                    unit=(u.canonical if u else (unit or None)),
                    unit_class=_unit_class_enum(unit, quantity),
                    item=(item or raw)[:300],
                    preparation=preparation,
                    optional=ing.optional,
                    # Seasoning "to taste" and garnishes should not multiply.
                    scalable=ing.scalable and _is_scalable(item or raw, raw, quantity, preparation),
                )
            )
    await db.flush()


async def _replace_steps(db: AsyncSession, recipe: Recipe, steps: list) -> None:
    await db.execute(delete(Step).where(Step.recipe_id == recipe.id))
    await db.flush()
    for si, step in enumerate(steps):
        text = (step.text or "").strip()
        if not text:
            continue
        db.add(
            Step(
                recipe_id=recipe.id,
                order_idx=si,
                text=text,
                timer_seconds=detect_timers(text),
                section=step.section,
            )
        )
    await db.flush()


async def _set_manual_tags(db: AsyncSession, user: User, recipe: Recipe, names: list[str]) -> None:
    tags = await get_or_create_tags(db, user, names)
    wanted = {t.id for t in tags}
    await db.execute(delete(RecipeTag).where(RecipeTag.recipe_id == recipe.id))
    await db.flush()
    for tag in tags:
        db.add(RecipeTag(recipe_id=recipe.id, tag_id=tag.id, auto=False))
    await db.flush()
    _ = wanted


@router.post("", response_model=RecipeDetail, status_code=status.HTTP_201_CREATED)
async def create_recipe(
    body: RecipeCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
) -> RecipeDetail:
    recipe = Recipe(
        user_id=user.id,
        title=body.title.strip()[:300] or "Untitled recipe",
        description=body.description,
        servings=body.servings,
        servings_unit=body.servings_unit,
        prep_min=body.prep_min,
        cook_min=body.cook_min,
        total_min=body.total_min,
        equipment=body.equipment,
        notes=body.notes,
        status=RecipeStatus.ready,
        confidence=1.0,
    )
    db.add(recipe)
    await db.flush()
    await _replace_groups(db, recipe, body.groups)
    await _replace_steps(db, recipe, body.steps)
    if body.tags:
        await _set_manual_tags(db, user, recipe, body.tags)
    await db.flush()
    await db.refresh(recipe)
    await refresh_search_vector(db, recipe)
    await refresh_embedding(db, recipe)
    await db.commit()
    await db.refresh(recipe)
    return recipe_detail(recipe)


@router.patch("/{recipe_id}", response_model=RecipeDetail)
async def update_recipe(
    recipe_id: uuid.UUID,
    body: RecipeUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
) -> RecipeDetail:
    recipe = await _get_recipe(db, user, recipe_id)
    before = {
        "servings": recipe.servings,
        "total_min": recipe.total_min,
        "title": recipe.title,
        "notes": recipe.notes,
    }

    data = body.model_dump(exclude_unset=True)
    for field in (
        "title",
        "title_original",
        "description",
        "language",
        "servings",
        "servings_unit",
        "prep_min",
        "cook_min",
        "total_min",
        "equipment",
        "notes",
        "favorite",
        "status",
    ):
        if field in data and data[field] is not None:
            setattr(recipe, field, data[field])

    ingredients_changed = None
    if body.groups is not None:
        previous = [
            f"{i.quantity or ''}{i.unit or ''} {i.item}"
            for g in recipe.groups
            for i in g.ingredients
        ]
        await _replace_groups(db, recipe, body.groups)
        await db.refresh(recipe)
        current = [
            f"{i.quantity or ''}{i.unit or ''} {i.item}"
            for g in recipe.groups
            for i in g.ingredients
        ]
        removed = [p for p in previous if p not in current]
        added = [c for c in current if c not in previous]
        if removed or added:
            ingredients_changed = (
                f"ingredients changed in '{recipe.title}': "
                + (f"removed {', '.join(removed[:4])}. " if removed else "")
                + (f"added {', '.join(added[:4])}." if added else "")
            ).strip()

    if body.steps is not None:
        await _replace_steps(db, recipe, body.steps)
    if body.tags is not None:
        await _set_manual_tags(db, user, recipe, body.tags)

    if body.status is None and recipe.status == RecipeStatus.needs_review:
        # An edit is the owner saying they have looked at it.
        if any(k in data for k in ("groups", "steps", "title", "servings")):
            recipe.status = RecipeStatus.ready
            recipe.review_reason = None

    recipe.updated_at = datetime.now(UTC)
    await db.flush()
    await db.refresh(recipe)

    after = {
        "servings": recipe.servings,
        "total_min": recipe.total_min,
        "title": recipe.title,
        "notes": recipe.notes,
        "ingredients_changed": ingredients_changed,
    }
    described = memory.describe_edit(before, after)
    if described:
        await memory.record(
            db, user_id=user.id, kind=ObservationKind.edit, text=described, recipe_id=recipe.id
        )

    await refresh_search_vector(db, recipe)
    await refresh_embedding(db, recipe)
    await db.commit()
    await db.refresh(recipe)
    return recipe_detail(recipe)


@router.delete("/{recipe_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_recipe(
    recipe_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
) -> None:
    recipe = await _get_recipe(db, user, recipe_id)
    await db.delete(recipe)


@router.post("/{recipe_id}/reextract", response_model=RecipeDetail)
async def reextract(
    recipe_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
) -> RecipeDetail:
    """Run the extractor again over the stored source, with the current taste profile."""
    recipe = await _get_recipe(db, user, recipe_id)
    if recipe.source is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "This recipe has no stored source to re-read."
        )
    profile = await db.scalar(select(Profile).where(Profile.user_id == user.id))
    extracted = await run_extraction(source=recipe.source, profile=profile)
    recipe = await apply_extracted_recipe(
        db, user=user, source=recipe.source, extracted=extracted, recipe=recipe
    )
    await db.flush()
    await db.refresh(recipe)
    await refresh_search_vector(db, recipe)
    await refresh_embedding(db, recipe)
    await db.commit()
    await db.refresh(recipe)
    return recipe_detail(recipe)


@router.get("/{recipe_id}/scaled", response_model=ScaledRecipeOut)
async def get_scaled(
    recipe_id: uuid.UUID,
    servings: float | None = Query(default=None, gt=0, le=1000),
    units: str | None = Query(default=None, pattern="^(metric|us|original)$"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
) -> ScaledRecipeOut:
    recipe = await _get_recipe(db, user, recipe_id)
    unit_system = None if units in (None, "original") else units
    scaled = scale_recipe(recipe, servings=servings, unit_system=unit_system)
    return ScaledRecipeOut.model_validate(scaled, from_attributes=True)


@router.post("/{recipe_id}/cooklog", response_model=CookLogOut, status_code=201)
async def add_cook_log(
    recipe_id: uuid.UUID,
    body: CookLogIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
) -> CookLog:
    recipe = await _get_recipe(db, user, recipe_id)
    entry = CookLog(
        recipe_id=recipe.id,
        rating=body.rating,
        notes=body.notes,
        servings_made=body.servings_made,
        cooked_at=body.cooked_at or datetime.now(UTC),
    )
    db.add(entry)
    text = f"cooked '{recipe.title}'"
    if body.rating:
        text += f" and rated it {body.rating}/5"
    if body.notes:
        text += f"; note: {body.notes[:200]}"
    await memory.record(
        db,
        user_id=user.id,
        kind=ObservationKind.rating if body.rating else ObservationKind.cooked,
        text=text,
        recipe_id=recipe.id,
    )
    await db.flush()
    return entry


@router.delete("/{recipe_id}/cooklog/{log_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_cook_log(
    recipe_id: uuid.UUID,
    log_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
) -> None:
    await _get_recipe(db, user, recipe_id)
    entry = await db.scalar(
        select(CookLog).where(CookLog.id == log_id, CookLog.recipe_id == recipe_id)
    )
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such cook log entry")
    await db.delete(entry)


@router.post("/{recipe_id}/tags", response_model=RecipeDetail)
async def add_tag(
    recipe_id: uuid.UUID,
    body: TagCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
) -> RecipeDetail:
    recipe = await _get_recipe(db, user, recipe_id)
    tags = await get_or_create_tags(db, user, [body.name])
    if not tags:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That tag name is empty.")
    tag = tags[0]
    exists = await db.scalar(
        select(RecipeTag).where(RecipeTag.recipe_id == recipe.id, RecipeTag.tag_id == tag.id)
    )
    if exists is None:
        db.add(RecipeTag(recipe_id=recipe.id, tag_id=tag.id, auto=False))
    await db.flush()
    await db.refresh(recipe)
    await refresh_search_vector(db, recipe)
    await db.commit()
    await db.refresh(recipe)
    return recipe_detail(recipe)


@router.delete("/{recipe_id}/tags/{tag_id}", response_model=RecipeDetail)
async def remove_tag(
    recipe_id: uuid.UUID,
    tag_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
) -> RecipeDetail:
    recipe = await _get_recipe(db, user, recipe_id)
    await db.execute(
        delete(RecipeTag).where(RecipeTag.recipe_id == recipe.id, RecipeTag.tag_id == tag_id)
    )
    await db.flush()
    await db.refresh(recipe)
    await refresh_search_vector(db, recipe)
    await db.commit()
    await db.refresh(recipe)
    return recipe_detail(recipe)


def recipe_to_markdown(recipe: Recipe) -> str:
    lines = [f"# {recipe.title}"]
    if recipe.title_original and recipe.title_original != recipe.title:
        lines.append(f"*{recipe.title_original}*")
    if recipe.description:
        lines += ["", recipe.description]

    meta = []
    if recipe.servings:
        meta.append(f"Serves {recipe.servings:g} {recipe.servings_unit or ''}".strip())
    if recipe.prep_min:
        meta.append(f"Prep {recipe.prep_min} min")
    if recipe.cook_min:
        meta.append(f"Cook {recipe.cook_min} min")
    if recipe.total_min:
        meta.append(f"Total {recipe.total_min} min")
    if meta:
        lines += ["", " · ".join(meta)]

    tags = [rt.tag.name for rt in recipe.tags if rt.tag]
    if tags:
        lines += ["", "Tags: " + ", ".join(sorted(tags))]

    lines += ["", "## Ingredients"]
    for group in recipe.groups:
        if group.name:
            lines += ["", f"### {group.name}"]
        for ing in group.ingredients:
            lines.append(f"- {ing.raw}")

    lines += ["", "## Method"]
    for i, step in enumerate(recipe.steps, start=1):
        lines.append(f"{i}. {step.text}")

    if recipe.equipment:
        lines += ["", "## Equipment", *[f"- {e}" for e in recipe.equipment]]
    if recipe.notes:
        lines += ["", "## Notes", recipe.notes]
    if recipe.source and recipe.source.url:
        lines += ["", f"Source: {recipe.source.url}"]
    return "\n".join(lines) + "\n"


@router.get("/{recipe_id}/export.md")
async def export_markdown(
    recipe_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
) -> Response:
    recipe = await _get_recipe(db, user, recipe_id)
    safe = "".join(c for c in recipe.title if c.isalnum() or c in " -_").strip()[:60] or "recipe"
    return Response(
        content=recipe_to_markdown(recipe),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{safe}.md"'},
    )


__all__ = ["SourceKind", "Tag", "recipe_to_markdown", "router"]
