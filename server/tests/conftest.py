"""Test fixtures.

The environment is configured before any application module is imported, so the
engine binds to the test database rather than the development one.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator

TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://onigiri:onigiri@127.0.0.1:5432/onigiri_test"
)
os.environ["DATABASE_URL"] = TEST_DB_URL
os.environ["ENVIRONMENT"] = "test"
os.environ["SECRET_KEY"] = "test-secret-key"
os.environ["OWNER_EMAIL"] = "cook@test.local"
os.environ["OWNER_PASSWORD"] = "test-password"
os.environ["JOB_BACKEND"] = "inline"
os.environ["MEDIA_DIR"] = "./.media-test"
# Environment variables outrank .env files, so blanking them here keeps a real key in the
# developer's .env from ever being used, or billed, by the test suite.
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["OPENAI_API_KEY"] = ""
os.environ["APIFY_TOKEN"] = ""

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

import onigiri.models  # noqa: E402,F401 - registers every table on Base.metadata
from onigiri.db import Base, SessionLocal, engine  # noqa: E402
from onigiri.recipe_schema import (  # noqa: E402
    ExtractedIngredient,
    ExtractedIngredientGroup,
    ExtractedRecipe,
    ExtractedStep,
    WireIngredient,
    WireRecipe,
    WireStep,
)


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="session", autouse=True)
async def _schema() -> AsyncIterator[None]:
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


@pytest.fixture(autouse=True)
async def _clean_tables(_schema: None) -> AsyncIterator[None]:
    """Each test starts from an empty bank."""
    async with engine.begin() as conn:
        tables = ", ".join(f'"{t.name}"' for t in reversed(Base.metadata.sorted_tables))
        await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    yield


@pytest.fixture
async def app_client() -> AsyncIterator[AsyncClient]:
    from onigiri.main import app, ensure_owner

    await ensure_owner()
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers={"Origin": "http://localhost:8000"},
    ) as client:
        yield client


@pytest.fixture
async def client(app_client: AsyncClient) -> AsyncClient:
    """A signed-in client."""
    resp = await app_client.post(
        "/api/auth/login",
        json={"email": "cook@test.local", "password": "test-password"},
    )
    assert resp.status_code == 200, resp.text
    return app_client


@pytest.fixture
async def db() -> AsyncIterator:
    async with SessionLocal() as session:
        yield session
        await session.commit()


def sample_extraction(**overrides) -> ExtractedRecipe:
    data = {
        "is_recipe": True,
        "title": "Lentil soup with lemon",
        "title_original": "Linsensuppe mit Zitrone",
        "language": "de",
        "description": "A thick winter soup finished with lemon.",
        "servings": 4,
        "servings_unit": "bowls",
        "prep_min": 10,
        "cook_min": 35,
        "total_min": 45,
        "ingredient_groups": [
            ExtractedIngredientGroup(
                name=None,
                ingredients=[
                    ExtractedIngredient(
                        raw="250 g rote Linsen", quantity=250, unit="g", item="red lentils"
                    ),
                    ExtractedIngredient(
                        raw="2 Zwiebeln, gewürfelt",
                        quantity=2,
                        unit=None,
                        item="onions",
                        preparation="diced",
                    ),
                    ExtractedIngredient(raw="1 Zitrone", quantity=1, unit=None, item="lemon"),
                    ExtractedIngredient(
                        raw="Salz nach Geschmack", item="salt", preparation="to taste"
                    ),
                ],
            )
        ],
        "steps": [
            ExtractedStep(text="Fry the onions for 5 minutes until soft."),
            ExtractedStep(text="Add the lentils and 1 litre of water, simmer 30 minutes."),
            ExtractedStep(text="Finish with lemon juice and salt."),
        ],
        "equipment": ["large pot"],
        "tags": ["soup", "vegetarian", "german", "lentils"],
        "confidence": 0.92,
        "missing": [],
        "review_reason": None,
        "profile_flags": [],
    }
    data.update(overrides)
    return ExtractedRecipe(**data)


def to_wire(recipe: ExtractedRecipe) -> WireRecipe:
    """What Claude would have sent to produce `recipe`: flat, with "" and 0 for unknown."""
    return WireRecipe(
        is_recipe=recipe.is_recipe,
        title=recipe.title,
        title_original=recipe.title_original or "",
        language=recipe.language or "",
        description=recipe.description or "",
        servings=recipe.servings or 0,
        servings_unit=recipe.servings_unit or "",
        prep_min=recipe.prep_min or 0,
        cook_min=recipe.cook_min or 0,
        total_min=recipe.total_min or 0,
        ingredients=[
            WireIngredient(
                group=group.name or "",
                raw=ing.raw,
                quantity=ing.quantity or 0,
                quantity_max=ing.quantity_max or 0,
                unit=ing.unit or "",
                item=ing.item,
                preparation=ing.preparation or "",
                optional=ing.optional,
            )
            for group in recipe.ingredient_groups
            for ing in group.ingredients
        ],
        steps=[WireStep(section=s.section or "", text=s.text) for s in recipe.steps],
        equipment=recipe.equipment,
        tags=recipe.tags,
        confidence=recipe.confidence,
        missing=recipe.missing,
        review_reason=recipe.review_reason or "",
        profile_flags=recipe.profile_flags,
    )


@pytest.fixture
def stub_llm(monkeypatch: pytest.MonkeyPatch):
    """Replace every model call with something deterministic."""
    from onigiri.services import llm

    calls: dict[str, list] = {"structured": [], "embed": [], "transcribe": []}
    recipe_holder = {"recipe": sample_extraction()}

    async def fake_structured(schema_model, system, content, *, schema_name, **kw):
        calls["structured"].append({"schema": schema_name, "system": system, "content": content})
        if schema_name == "extracted_recipe":
            return to_wire(recipe_holder["recipe"])
        return schema_model.model_construct()

    async def fake_embed(text_in: str, **kw) -> list[float]:
        calls["embed"].append(text_in)
        seed = sum(ord(c) for c in text_in[:200]) or 1
        return [((seed * (i + 1)) % 1000) / 1000 for i in range(1536)]

    async def fake_transcribe(path, **kw):
        calls["transcribe"].append(str(path))
        return {"text": "stub transcript", "segments": [], "language": "en", "duration": 10}

    monkeypatch.setattr(llm, "structured", fake_structured)
    monkeypatch.setattr(llm, "embed", fake_embed)
    monkeypatch.setattr(llm, "transcribe_file", fake_transcribe)
    calls["set_recipe"] = recipe_holder  # type: ignore[assignment]
    return calls


@pytest.fixture
def new_uuid():
    return uuid.uuid4
