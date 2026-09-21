"""Read a recipe off a web page.

Two paths: `recipe-scrapers` understands several hundred recipe sites and returns
structured data directly, which costs nothing and never hallucinates. Anything else
falls back to readable text extraction, which the language model then reads.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

from onigiri.recipe_schema import (
    ExtractedIngredient,
    ExtractedIngredientGroup,
    ExtractedRecipe,
    ExtractedStep,
)
from onigiri.units import parse_ingredient

log = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0 Safari/537.36"
)


@dataclass
class WebFetchResult:
    url: str
    title: str | None = None
    author: str | None = None
    page_text: str | None = None
    image_urls: list[str] = field(default_factory=list)
    structured: ExtractedRecipe | None = None
    raw_payload: dict[str, Any] = field(default_factory=dict)


async def download(url: str, *, timeout: float = 30.0) -> tuple[str, str]:
    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=timeout,
        headers={"User-Agent": USER_AGENT, "Accept-Language": "en,de;q=0.8"},
    ) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.text, str(resp.url)


def _scrape_sync(html: str, url: str) -> dict[str, Any] | None:
    """Run recipe-scrapers. Returns a plain dict so nothing library-specific escapes."""
    try:
        from recipe_scrapers import scrape_html
    except ImportError:  # pragma: no cover
        return None

    try:
        scraper = scrape_html(html, org_url=url, supported_only=False)
    except Exception:
        return None

    def safe(name: str) -> Any:
        try:
            return getattr(scraper, name)()
        except Exception:
            return None

    data = {
        "title": safe("title"),
        "author": safe("author"),
        "total_time": safe("total_time"),
        "prep_time": safe("prep_time"),
        "cook_time": safe("cook_time"),
        "yields": safe("yields"),
        "image": safe("image"),
        "ingredients": safe("ingredients") or [],
        "ingredient_groups": None,
        "instructions_list": safe("instructions_list") or [],
        "description": safe("description"),
        "cuisine": safe("cuisine"),
        "category": safe("category"),
        "language": safe("language"),
        "equipment": safe("equipment") or [],
    }
    try:
        groups = scraper.ingredient_groups()
        data["ingredient_groups"] = [
            {"purpose": g.purpose, "ingredients": list(g.ingredients)} for g in groups
        ]
    except Exception:
        pass
    return data


def _parse_yields(value: Any) -> tuple[float | None, str | None]:
    if not value:
        return None, None
    text = str(value).strip()
    import re

    m = re.search(r"(\d+(?:[.,]\d+)?)", text)
    qty = float(m.group(1).replace(",", ".")) if m else None
    unit = re.sub(r"^\s*\d+(?:[.,]\d+)?\s*", "", text).strip() or None
    return qty, unit


def structured_from_scraper(data: dict[str, Any]) -> ExtractedRecipe | None:
    """Turn schema.org recipe data into our own shape, with no model call."""
    ingredients_present = bool(data.get("ingredients") or data.get("ingredient_groups"))
    steps_present = bool(data.get("instructions_list"))
    if not (ingredients_present and steps_present and data.get("title")):
        return None

    groups: list[ExtractedIngredientGroup] = []
    raw_groups = data.get("ingredient_groups")
    if raw_groups:
        for g in raw_groups:
            items = [_ingredient_from_line(line) for line in g.get("ingredients", [])]
            if items:
                groups.append(ExtractedIngredientGroup(name=g.get("purpose"), ingredients=items))
    if not groups:
        items = [_ingredient_from_line(line) for line in data.get("ingredients", [])]
        if items:
            groups.append(ExtractedIngredientGroup(name=None, ingredients=items))

    steps = [
        ExtractedStep(text=s.strip()) for s in data.get("instructions_list", []) if s and s.strip()
    ]
    servings, servings_unit = _parse_yields(data.get("yields"))

    tags = [
        t.strip().lower()
        for t in [data.get("cuisine"), data.get("category")]
        if t and isinstance(t, str)
    ]

    return ExtractedRecipe(
        is_recipe=True,
        title=str(data["title"]).strip(),
        title_original=None,
        language=(data.get("language") or "en")[:5].lower() or None,
        description=(data.get("description") or None),
        servings=servings,
        servings_unit=servings_unit,
        prep_min=_as_int(data.get("prep_time")),
        cook_min=_as_int(data.get("cook_time")),
        total_min=_as_int(data.get("total_time")),
        ingredient_groups=groups,
        steps=steps,
        equipment=[str(e) for e in (data.get("equipment") or []) if e][:12],
        tags=tags,
        confidence=0.95,
        missing=[],
        review_reason=None,
        profile_flags=[],
    )


def _as_int(value: Any) -> int | None:
    try:
        n = int(value)
        return n if n > 0 else None
    except (TypeError, ValueError):
        return None


def _ingredient_from_line(line: str) -> ExtractedIngredient:
    parsed = parse_ingredient(line)
    return ExtractedIngredient(
        raw=parsed.raw,
        quantity=parsed.quantity,
        quantity_max=parsed.quantity_max,
        unit=parsed.unit,
        item=parsed.item or parsed.raw,
        preparation=parsed.preparation,
        optional=parsed.optional,
    )


def _readable_text_sync(html: str, url: str) -> tuple[str | None, str | None]:
    try:
        import trafilatura
    except ImportError:  # pragma: no cover
        return None, None
    text = trafilatura.extract(
        html, include_comments=False, include_tables=True, favor_recall=True, url=url
    )
    title = None
    try:
        meta = trafilatura.extract_metadata(html)
        title = getattr(meta, "title", None) if meta else None
    except Exception:
        pass
    return text, title


async def fetch_web(url: str) -> WebFetchResult:
    html, final_url = await download(url)
    result = WebFetchResult(url=final_url)

    data = await asyncio.to_thread(_scrape_sync, html, final_url)
    if data:
        result.raw_payload = {k: v for k, v in data.items() if k != "ingredient_groups"}
        result.title = data.get("title")
        result.author = data.get("author")
        if data.get("image"):
            result.image_urls.append(str(data["image"]))
        result.structured = structured_from_scraper(data)

    text, meta_title = await asyncio.to_thread(_readable_text_sync, html, final_url)
    result.page_text = text
    result.title = result.title or meta_title
    if not result.page_text and result.structured is None:
        raise ValueError("Could not read any text from that page.")
    return result
