"""ORM to DTO conversion, kept out of the routers."""

from __future__ import annotations

from onigiri.models import Media, Recipe, Source
from onigiri.schemas import (
    IngredientGroupOut,
    IngredientOut,
    MediaOut,
    RecipeDetail,
    RecipeSummary,
    SourceOut,
    StepOut,
    TagOut,
    TranscriptSegment,
)
from onigiri.services.scaling import _render


def media_url(media: Media | None) -> str | None:
    return f"/api/media/{media.id}" if media else None


def media_out(media: Media) -> MediaOut:
    return MediaOut(
        id=media.id,
        kind=media.kind.value,
        content_type=media.content_type,
        width=media.width,
        height=media.height,
        duration_s=media.duration_s,
        url=media_url(media),
    )


def tag_outs(recipe: Recipe) -> list[TagOut]:
    out = [
        TagOut(id=rt.tag.id, name=rt.tag.name, kind=rt.tag.kind, auto=rt.auto)
        for rt in recipe.tags
        if rt.tag
    ]
    out.sort(key=lambda t: (t.kind.value, t.name))
    return out


def ingredient_out(ing) -> IngredientOut:
    qty = float(ing.quantity) if ing.quantity is not None else None
    qty_max = float(ing.quantity_max) if ing.quantity_max is not None else None
    return IngredientOut(
        id=ing.id,
        order_idx=ing.order_idx,
        raw=ing.raw,
        quantity=qty,
        quantity_max=qty_max,
        unit=ing.unit,
        unit_class=ing.unit_class.value,
        item=ing.item,
        preparation=ing.preparation,
        optional=ing.optional,
        scalable=ing.scalable,
        display=_render(qty, qty_max, ing.unit, ing.item or "", ing.preparation, ing.optional),
    )


def source_out(source: Source | None) -> SourceOut | None:
    if source is None:
        return None
    transcript = source.transcript or {}
    return SourceOut(
        id=source.id,
        kind=source.kind,
        url=source.url,
        title=source.title,
        author=source.author,
        caption=source.caption,
        page_text=source.page_text,
        onscreen_text=source.onscreen_text,
        photo_text=source.photo_text,
        transcript_text=transcript.get("text") or None,
        transcript_segments=[
            TranscriptSegment(**s) for s in (transcript.get("segments") or [])[:2000]
        ],
        language=source.language,
        fetched_at=source.fetched_at,
        media=[media_out(m) for m in source.media],
    )


def recipe_summary(recipe: Recipe) -> RecipeSummary:
    return RecipeSummary(
        id=recipe.id,
        title=recipe.title,
        title_original=recipe.title_original,
        description=recipe.description,
        language=recipe.language,
        status=recipe.status,
        confidence=recipe.confidence,
        review_reason=recipe.review_reason,
        total_min=recipe.total_min,
        servings=recipe.servings,
        favorite=recipe.favorite,
        hero_url=media_url(recipe.hero_media),
        tags=tag_outs(recipe),
        source_kind=recipe.source.kind if recipe.source else None,
        source_url=recipe.source.url if recipe.source else None,
        updated_at=recipe.updated_at,
        created_at=recipe.created_at,
    )


def recipe_detail(recipe: Recipe, *, include_source: bool = True) -> RecipeDetail:
    base = recipe_summary(recipe)
    return RecipeDetail(
        **base.model_dump(),
        servings_unit=recipe.servings_unit,
        prep_min=recipe.prep_min,
        cook_min=recipe.cook_min,
        equipment=list(recipe.equipment or []),
        notes=recipe.notes or "",
        profile_flags=list(recipe.profile_flags or []),
        groups=[
            IngredientGroupOut(
                id=g.id,
                name=g.name,
                order_idx=g.order_idx,
                ingredients=[ingredient_out(i) for i in g.ingredients],
            )
            for g in recipe.groups
        ],
        steps=[
            StepOut(
                id=s.id,
                order_idx=s.order_idx,
                text=s.text,
                timer_seconds=list(s.timer_seconds or []),
                section=s.section,
            )
            for s in recipe.steps
        ],
        cook_log=[
            {
                "id": c.id,
                "cooked_at": c.cooked_at,
                "rating": c.rating,
                "notes": c.notes,
                "servings_made": c.servings_made,
            }
            for c in recipe.cook_log
        ],
        source=source_out(recipe.source) if include_source else None,
    )
