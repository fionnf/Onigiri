"""Turn assembled source context into a stored recipe."""

from __future__ import annotations

import logging

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from onigiri.config import settings
from onigiri.models import (
    Ingredient,
    IngredientGroup,
    Profile,
    Recipe,
    RecipeStatus,
    RecipeTag,
    Source,
    Step,
    Tag,
    TagKind,
    UnitClass,
    User,
)
from onigiri.pipeline.prompts import build_extract_input, extract_system_prompt
from onigiri.recipe_schema import RECIPE_JSON_SCHEMA_NAME, ExtractedRecipe
from onigiri.services import llm
from onigiri.units import COUNT, NONE, detect_timers, lookup_unit, parse_ingredient

log = logging.getLogger(__name__)

CUISINES = {
    "italian",
    "french",
    "japanese",
    "chinese",
    "thai",
    "indian",
    "mexican",
    "spanish",
    "greek",
    "korean",
    "vietnamese",
    "turkish",
    "lebanese",
    "moroccan",
    "german",
    "swiss",
    "austrian",
    "british",
    "american",
    "swedish",
    "danish",
    "polish",
    "portuguese",
    "ethiopian",
    "peruvian",
    "brazilian",
    "caribbean",
    "nordic",
    "middle eastern",
    "mediterranean",
    "asian",
    "european",
    "irish",
    "filipino",
    "indonesian",
    "malaysian",
    "russian",
    "hungarian",
    "georgian",
    "persian",
}
COURSES = {
    "breakfast",
    "brunch",
    "lunch",
    "dinner",
    "starter",
    "appetizer",
    "main",
    "main course",
    "side",
    "side dish",
    "dessert",
    "snack",
    "drink",
    "cocktail",
    "sauce",
    "salad",
    "soup",
    "bread",
    "baking",
    "condiment",
    "preserve",
    "pasta",
    "pizza",
    "stew",
    "curry",
}
DIETS = {
    "vegetarian",
    "vegan",
    "gluten-free",
    "gluten free",
    "dairy-free",
    "dairy free",
    "pescatarian",
    "keto",
    "low-carb",
    "low carb",
    "paleo",
    "nut-free",
    "nut free",
    "high-protein",
    "high protein",
    "low-fat",
    "sugar-free",
    "halal",
    "kosher",
}
PROTEINS = {
    "chicken",
    "beef",
    "pork",
    "lamb",
    "fish",
    "salmon",
    "tuna",
    "shrimp",
    "prawn",
    "tofu",
    "tempeh",
    "eggs",
    "egg",
    "lentils",
    "chickpeas",
    "beans",
    "duck",
    "turkey",
    "seafood",
    "mushroom",
    "paneer",
    "halloumi",
}
TECHNIQUES = {
    "roast",
    "roasted",
    "grilled",
    "fried",
    "air fryer",
    "slow cooker",
    "one pot",
    "one-pot",
    "no-bake",
    "no bake",
    "sheet pan",
    "braised",
    "steamed",
    "pressure cooker",
    "instant pot",
    "baked",
    "raw",
    "fermented",
    "sous vide",
    "barbecue",
    "bbq",
    "smoked",
    "stir-fry",
    "stir fry",
    "poached",
    "confit",
    "pickled",
}


def tag_kind_for(name: str) -> TagKind:
    n = name.strip().lower()
    if n in CUISINES:
        return TagKind.cuisine
    if n in COURSES:
        return TagKind.course
    if n in DIETS:
        return TagKind.diet
    if n in PROTEINS:
        return TagKind.protein
    if n in TECHNIQUES:
        return TagKind.technique
    if n.endswith("minutes") or n.endswith("min") or n in {"quick", "weeknight", "make ahead"}:
        return TagKind.time
    return TagKind.custom


def time_bucket_tag(total_min: int | None) -> str | None:
    if not total_min or total_min <= 0:
        return None
    if total_min <= 15:
        return "under 15 min"
    if total_min <= 30:
        return "under 30 min"
    if total_min <= 60:
        return "under 1 hour"
    return "over 1 hour"


async def run_extraction(
    *,
    source: Source,
    profile: Profile | None,
    extra_note: str | None = None,
    usage: llm.Usage | None = None,
) -> ExtractedRecipe:
    """Ask the model for one structured recipe from everything we gathered."""
    content = build_extract_input(
        source_kind=source.kind.value,
        url=source.url,
        title=source.title,
        author=source.author,
        caption=source.caption,
        page_text=source.page_text,
        transcript=source.transcript_text,
        onscreen_text=source.onscreen_text,
        photo_text=source.photo_text,
        extra_note=extra_note,
    )
    return await llm.structured(
        ExtractedRecipe,
        extract_system_prompt(profile),
        content,
        schema_name=RECIPE_JSON_SCHEMA_NAME,
        model=settings.openai_extract_model,
        usage=usage,
    )


def _unit_class_for(unit: str | None, quantity: float | None) -> UnitClass:
    u = lookup_unit(unit)
    if u:
        return UnitClass(u.unit_class)
    if unit:
        return UnitClass.count
    return UnitClass.count if quantity is not None else UnitClass.none


def _clean_unit(unit: str | None) -> str | None:
    if not unit:
        return None
    u = lookup_unit(unit)
    return u.canonical if u else unit.strip()[:32] or None


# Phrases that mean "as much as it takes", which must not be multiplied.
NON_SCALABLE_PHRASES = (
    "to taste",
    "for serving",
    "to serve",
    "for garnish",
    "to garnish",
    "for dusting",
    "for sprinkling",
    "for drizzling",
    "for greasing",
    "for frying",
    "as needed",
    "plus more",
    "if needed",
    "optional extra",
)


def _is_scalable(
    item: str, raw: str, quantity: float | None, preparation: str | None = None
) -> bool:
    """A measured amount scales; seasoning to taste and garnishes do not."""
    if quantity is None:
        return False
    haystack = " ".join(filter(None, [item, raw, preparation])).lower()
    return not any(phrase in haystack for phrase in NON_SCALABLE_PHRASES)


async def get_or_create_tags(db: AsyncSession, user: User, names: list[str]) -> list[Tag]:
    """Tags are per-owner and reused, so the vocabulary stays small."""
    cleaned: list[str] = []
    for name in names:
        n = " ".join(str(name).split()).strip().lower()[:64]
        if n and n not in cleaned:
            cleaned.append(n)
    if not cleaned:
        return []

    existing = (
        await db.scalars(select(Tag).where(Tag.user_id == user.id, Tag.name.in_(cleaned)))
    ).all()
    by_name = {t.name: t for t in existing}
    out: list[Tag] = []
    for name in cleaned:
        tag = by_name.get(name)
        if tag is None:
            tag = Tag(user_id=user.id, name=name, kind=tag_kind_for(name))
            db.add(tag)
            await db.flush()
            by_name[name] = tag
        out.append(tag)
    return out


async def apply_extracted(
    db: AsyncSession,
    *,
    user: User,
    source: Source | None,
    extracted: ExtractedRecipe,
    recipe: Recipe | None = None,
) -> Recipe:
    """Write an extracted recipe to the database, replacing any previous structure."""
    if recipe is None:
        recipe = Recipe(user_id=user.id, source_id=source.id if source else None, title="")
        db.add(recipe)
        await db.flush()

    recipe.title = (extracted.title or "Untitled recipe").strip()[:300]
    recipe.title_original = extracted.title_original or None
    recipe.language = extracted.language or (source.language if source else None) or None
    recipe.description = extracted.description
    recipe.servings = extracted.servings
    recipe.servings_unit = extracted.servings_unit
    recipe.prep_min = extracted.prep_min
    recipe.cook_min = extracted.cook_min
    recipe.total_min = extracted.total_min or _sum_times(extracted)
    recipe.equipment = [e.strip() for e in extracted.equipment if e and e.strip()][:20]
    recipe.confidence = extracted.confidence
    recipe.profile_flags = list(extracted.profile_flags)

    reason_parts: list[str] = []
    if extracted.review_reason:
        reason_parts.append(extracted.review_reason.strip())
    if extracted.missing:
        reason_parts.append("Not stated in the source: " + ", ".join(extracted.missing[:8]))
    recipe.review_reason = " ".join(reason_parts)[:1000] or None

    has_content = bool(extracted.ingredient_groups and extracted.steps)
    if not extracted.is_recipe or not has_content or extracted.confidence < 0.55:
        recipe.status = RecipeStatus.needs_review
    elif extracted.review_reason or extracted.missing:
        recipe.status = RecipeStatus.needs_review
    else:
        recipe.status = RecipeStatus.ready

    if not extracted.is_recipe:
        recipe.review_reason = (
            "The source did not look like a recipe. " + (recipe.review_reason or "")
        ).strip()

    # replace structure
    await db.execute(delete(IngredientGroup).where(IngredientGroup.recipe_id == recipe.id))
    await db.execute(delete(Step).where(Step.recipe_id == recipe.id))
    await db.flush()

    for gi, group in enumerate(extracted.ingredient_groups):
        g = IngredientGroup(recipe_id=recipe.id, name=group.name, order_idx=gi)
        db.add(g)
        await db.flush()
        for ii, ing in enumerate(group.ingredients):
            raw = (ing.raw or "").strip() or ing.item
            item = (ing.item or "").strip()
            if not item:
                item = parse_ingredient(raw).item or raw
            unit = _clean_unit(ing.unit)
            db.add(
                Ingredient(
                    group_id=g.id,
                    order_idx=ii,
                    raw=raw[:500],
                    quantity=ing.quantity,
                    quantity_max=ing.quantity_max,
                    unit=unit,
                    unit_class=_unit_class_for(unit, ing.quantity),
                    item=item[:300],
                    preparation=(ing.preparation or None),
                    optional=ing.optional,
                    scalable=_is_scalable(item, raw, ing.quantity, ing.preparation),
                )
            )

    for si, step in enumerate(extracted.steps):
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

    tag_names = list(extracted.tags)
    bucket = time_bucket_tag(recipe.total_min)
    if bucket:
        tag_names.append(bucket)
    await set_auto_tags(db, user=user, recipe=recipe, names=tag_names)

    await db.flush()
    return recipe


def _sum_times(extracted: ExtractedRecipe) -> int | None:
    parts = [t for t in (extracted.prep_min, extracted.cook_min) if t]
    return sum(parts) if parts else None


async def set_auto_tags(db: AsyncSession, *, user: User, recipe: Recipe, names: list[str]) -> None:
    """Replace automatic tags, leaving anything the owner added by hand alone."""
    await db.execute(
        delete(RecipeTag).where(RecipeTag.recipe_id == recipe.id, RecipeTag.auto.is_(True))
    )
    await db.flush()
    manual = set(
        (await db.scalars(select(RecipeTag.tag_id).where(RecipeTag.recipe_id == recipe.id))).all()
    )
    tags = await get_or_create_tags(db, user, names)
    for tag in tags:
        if tag.id in manual:
            continue
        db.add(RecipeTag(recipe_id=recipe.id, tag_id=tag.id, auto=True))
        manual.add(tag.id)
    await db.flush()


def searchable_text(recipe: Recipe) -> tuple[str, str]:
    """Return (english blob, original-language blob) for the search vector."""
    english: list[str] = [recipe.title]
    if recipe.description:
        english.append(recipe.description)
    for group in recipe.groups:
        if group.name:
            english.append(group.name)
        for ing in group.ingredients:
            english.append(" ".join(filter(None, [ing.item, ing.preparation])))
    for step in recipe.steps:
        english.append(step.text)
    english.extend(rt.tag.name for rt in recipe.tags if rt.tag)
    english.extend(recipe.equipment)

    original: list[str] = []
    if recipe.title_original:
        original.append(recipe.title_original)
    for group in recipe.groups:
        original.extend(ing.raw for ing in group.ingredients)
    if recipe.notes:
        original.append(recipe.notes)
    return " \n".join(filter(None, english)), " \n".join(filter(None, original))


SEARCH_VECTOR_SQL = text(
    """
    UPDATE recipes SET search_tsv =
        setweight(to_tsvector('english', :title), 'A') ||
        setweight(to_tsvector('english', :english), 'B') ||
        setweight(to_tsvector('simple', :original), 'C')
    WHERE id = :recipe_id
    """
)


async def refresh_search_vector(db: AsyncSession, recipe: Recipe) -> None:
    """Rebuild the full-text vector: title heaviest, English body next, source text last.

    Written as explicit SQL because `setweight` takes Postgres's internal "char"
    type, which the query builder renders as varchar.
    """
    english, original = searchable_text(recipe)
    await db.execute(
        SEARCH_VECTOR_SQL,
        {
            "title": recipe.title or "",
            "english": english[:900_000],
            "original": original[:900_000],
            "recipe_id": recipe.id,
        },
    )


def embedding_text(recipe: Recipe) -> str:
    """A compact description of the recipe for semantic search."""
    items = [ing.item for group in recipe.groups for ing in group.ingredients if ing.item][:40]
    tags = [rt.tag.name for rt in recipe.tags if rt.tag]
    bits = [recipe.title]
    if recipe.description:
        bits.append(recipe.description)
    if tags:
        bits.append("Tags: " + ", ".join(tags))
    if items:
        bits.append("Ingredients: " + ", ".join(items))
    if recipe.total_min:
        bits.append(f"Takes about {recipe.total_min} minutes.")
    return "\n".join(bits)


async def refresh_embedding(
    db: AsyncSession, recipe: Recipe, *, usage: llm.Usage | None = None
) -> bool:
    """Best effort: search still works through full text if this fails."""
    try:
        vector = await llm.embed(embedding_text(recipe), usage=usage)
    except llm.LLMError as exc:
        log.info("embedding skipped for %s: %s", recipe.id, exc)
        return False
    await db.execute(
        Recipe.__table__.update().where(Recipe.id == recipe.id).values(embedding=vector)
    )
    return True


async def reindex(db: AsyncSession, recipe: Recipe, *, usage: llm.Usage | None = None) -> None:
    await db.refresh(recipe)
    await refresh_search_vector(db, recipe)
    await refresh_embedding(db, recipe, usage=usage)


__all__ = [
    "COUNT",
    "NONE",
    "apply_extracted",
    "get_or_create_tags",
    "refresh_embedding",
    "refresh_search_vector",
    "reindex",
    "run_extraction",
    "set_auto_tags",
    "tag_kind_for",
    "time_bucket_tag",
]
