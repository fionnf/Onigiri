"""End to end capture: text in, structured recipe out, with the model stubbed."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from onigiri.models import IngestJob
from onigiri.services.jobs import wait_for_background
from tests.conftest import sample_extraction

RECIPE_TEXT = """
Linsensuppe mit Zitrone
250 g rote Linsen, 2 Zwiebeln, 1 Zitrone, Salz
Zwiebeln 5 Minuten anbraten. Linsen und 1 Liter Wasser zugeben, 30 Minuten koecheln.
Mit Zitronensaft abschmecken.
"""


async def run_capture(client: AsyncClient, **payload) -> dict:
    resp = await client.post("/api/ingest", json=payload)
    assert resp.status_code == 202, resp.text
    job_id = resp.json()["id"]
    await wait_for_background()
    job = await client.get(f"/api/jobs/{job_id}")
    assert job.status_code == 200
    return job.json()


async def test_text_capture_produces_a_recipe(client: AsyncClient, stub_llm, db) -> None:
    job = await run_capture(client, text=RECIPE_TEXT)
    assert job["status"] == "done", job
    assert job["recipe_id"]

    detail = (await client.get(f"/api/recipes/{job['recipe_id']}")).json()
    assert detail["title"] == "Lentil soup with lemon"
    assert detail["title_original"] == "Linsensuppe mit Zitrone"
    assert detail["language"] == "de"
    assert detail["status"] == "ready"
    assert detail["servings"] == 4
    assert len(detail["steps"]) == 3
    items = [i["item"] for g in detail["groups"] for i in g["ingredients"]]
    assert items == ["red lentils", "onions", "lemon", "salt"]


async def test_original_language_is_kept_alongside_english(client: AsyncClient, stub_llm) -> None:
    job = await run_capture(client, text=RECIPE_TEXT)
    detail = (await client.get(f"/api/recipes/{job['recipe_id']}")).json()
    raws = [i["raw"] for g in detail["groups"] for i in g["ingredients"]]
    assert "250 g rote Linsen" in raws
    assert detail["source"]["caption"].strip().startswith("Linsensuppe")


async def test_timers_are_detected_from_steps(client: AsyncClient, stub_llm) -> None:
    job = await run_capture(client, text=RECIPE_TEXT)
    detail = (await client.get(f"/api/recipes/{job['recipe_id']}")).json()
    timers = [s["timer_seconds"] for s in detail["steps"]]
    assert timers[0] == [300]
    assert timers[1] == [1800]


async def test_seasoning_to_taste_is_marked_unscalable(client: AsyncClient, stub_llm) -> None:
    job = await run_capture(client, text=RECIPE_TEXT)
    detail = (await client.get(f"/api/recipes/{job['recipe_id']}")).json()
    salt = next(i for g in detail["groups"] for i in g["ingredients"] if i["item"] == "salt")
    assert salt["scalable"] is False


async def test_auto_tags_include_a_time_bucket(client: AsyncClient, stub_llm) -> None:
    job = await run_capture(client, text=RECIPE_TEXT)
    detail = (await client.get(f"/api/recipes/{job['recipe_id']}")).json()
    names = {t["name"] for t in detail["tags"]}
    assert {"soup", "vegetarian", "german"} <= names
    assert "under 1 hour" in names
    kinds = {t["name"]: t["kind"] for t in detail["tags"]}
    assert kinds["german"] == "cuisine"
    assert kinds["vegetarian"] == "diet"
    assert kinds["soup"] == "course"


async def test_incomplete_source_lands_in_needs_review(client: AsyncClient, stub_llm) -> None:
    stub_llm["set_recipe"]["recipe"] = sample_extraction(
        confidence=0.4,
        steps=[],
        missing=["oven temperature", "method"],
        review_reason="The caption listed ingredients but no method.",
    )
    job = await run_capture(client, text="just some ingredients")
    detail = (await client.get(f"/api/recipes/{job['recipe_id']}")).json()
    assert detail["status"] == "needs_review"
    assert "no method" in detail["review_reason"]
    assert "oven temperature" in detail["review_reason"]


async def test_non_recipe_source_is_flagged(client: AsyncClient, stub_llm) -> None:
    stub_llm["set_recipe"]["recipe"] = sample_extraction(
        is_recipe=False, ingredient_groups=[], steps=[], confidence=0.2
    )
    job = await run_capture(client, text="a photo of my cat")
    detail = (await client.get(f"/api/recipes/{job['recipe_id']}")).json()
    assert detail["status"] == "needs_review"
    assert "did not look like a recipe" in detail["review_reason"]


async def test_the_taste_profile_reaches_the_prompt(client: AsyncClient, stub_llm) -> None:
    await client.put(
        "/api/me/profile",
        json={"allergies": ["walnuts"], "diet": ["vegetarian"], "dislikes": ["coriander"]},
    )
    await run_capture(client, text=RECIPE_TEXT)
    system = stub_llm["structured"][-1]["system"]
    assert "walnuts" in system
    assert "vegetarian" in system
    assert "coriander" in system
    assert "never change, remove or substitute" in system.lower()


async def test_profile_flags_are_stored(client: AsyncClient, stub_llm) -> None:
    stub_llm["set_recipe"]["recipe"] = sample_extraction(
        profile_flags=["contains walnuts (allergy)"]
    )
    job = await run_capture(client, text=RECIPE_TEXT)
    detail = (await client.get(f"/api/recipes/{job['recipe_id']}")).json()
    assert detail["profile_flags"] == ["contains walnuts (allergy)"]


async def test_instagram_without_a_token_asks_for_the_caption(
    client: AsyncClient, stub_llm
) -> None:
    job = await run_capture(client, url="https://www.instagram.com/reel/Cabc123/")
    assert job["status"] == "needs_input"
    assert "paste the caption" in job["needs_input_reason"].lower()
    assert job["recipe_id"] is None


async def test_pasting_the_caption_rescues_the_capture(client: AsyncClient, stub_llm) -> None:
    job = await run_capture(client, url="https://www.instagram.com/reel/Cabc123/")
    assert job["status"] == "needs_input"

    resp = await client.post(f"/api/jobs/{job['id']}/input", json={"text": RECIPE_TEXT})
    assert resp.status_code == 200
    await wait_for_background()

    job = (await client.get(f"/api/jobs/{job['id']}")).json()
    assert job["status"] == "done", job
    detail = (await client.get(f"/api/recipes/{job['recipe_id']}")).json()
    assert detail["title"] == "Lentil soup with lemon"


async def test_empty_capture_is_rejected(client: AsyncClient) -> None:
    resp = await client.post("/api/ingest", json={})
    assert resp.status_code == 400


async def test_stage_log_records_progress(client: AsyncClient, stub_llm) -> None:
    job = await run_capture(client, text=RECIPE_TEXT)
    stages = [entry["stage"] for entry in job["stage_log"]]
    assert "fetching" in stages
    assert "extracting" in stages
    assert stages[-1] == "done"
    assert all(entry["note"] for entry in job["stage_log"])


async def test_web_capture_uses_structured_data_without_the_model(
    client: AsyncClient, stub_llm, monkeypatch
) -> None:
    """A site publishing schema.org data should not cost a model call."""
    from onigiri.pipeline import fetch_web

    html = """
    <html><head><title>Tomato pasta</title>
    <script type="application/ld+json">
    {"@context":"https://schema.org","@type":"Recipe","name":"Tomato pasta",
     "author":{"@type":"Person","name":"A Cook"},
     "recipeYield":"2 servings","totalTime":"PT25M",
     "recipeIngredient":["400 g tinned tomatoes","200 g spaghetti","2 cloves garlic"],
     "recipeInstructions":[{"@type":"HowToStep","text":"Boil the spaghetti for 9 minutes."},
       {"@type":"HowToStep","text":"Fry the garlic, add tomatoes, simmer 15 minutes."}]}
    </script></head><body><p>Tomato pasta recipe</p></body></html>
    """

    async def fake_download(url: str, **kw):
        return html, url

    monkeypatch.setattr(fetch_web, "download", fake_download)

    job = await run_capture(client, url="https://example.com/tomato-pasta")
    assert job["status"] == "done", job
    detail = (await client.get(f"/api/recipes/{job['recipe_id']}")).json()
    assert detail["title"] == "Tomato pasta"
    assert len(detail["steps"]) == 2
    items = [i["item"] for g in detail["groups"] for i in g["ingredients"]]
    assert "spaghetti" in " ".join(items)
    # the extractor was never asked
    assert not [c for c in stub_llm["structured"] if c["schema"] == "extracted_recipe"]


async def test_unreadable_page_asks_for_text(client: AsyncClient, stub_llm, monkeypatch) -> None:
    from onigiri.pipeline import fetch_web

    async def boom(url: str, **kw):
        raise ValueError("404 Not Found")

    monkeypatch.setattr(fetch_web, "download", boom)
    job = await run_capture(client, url="https://example.com/gone")
    assert job["status"] == "needs_input"
    assert "paste the recipe text" in job["needs_input_reason"].lower()


async def test_retry_reruns_a_failed_capture(client: AsyncClient, stub_llm, db) -> None:
    job = await run_capture(client, url="https://www.instagram.com/reel/Cabc/")
    assert job["status"] == "needs_input"

    row = await db.scalar(select(IngestJob).where(IngestJob.id == job["id"]))
    row.input_text = RECIPE_TEXT
    await db.commit()

    resp = await client.post(f"/api/jobs/{job['id']}/retry")
    assert resp.status_code == 200
    await wait_for_background()
    job = (await client.get(f"/api/jobs/{job['id']}")).json()
    assert job["status"] == "done", job


async def test_extraction_without_an_api_key_fails_clearly(client: AsyncClient) -> None:
    """No stub here: the real client is missing its key."""
    job = await run_capture(client, text=RECIPE_TEXT)
    assert job["status"] == "failed"
    assert "OPENAI_API_KEY" in job["error"]


@pytest.mark.parametrize("path", ["/api/recipes", "/api/stats", "/api/me/profile"])
async def test_endpoints_require_sign_in(app_client: AsyncClient, path: str) -> None:
    assert (await app_client.get(path)).status_code == 401
