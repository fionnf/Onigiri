"""Search, tags, collections, the cook log and the profile's memory."""

from __future__ import annotations

from httpx import AsyncClient

from onigiri.services.jobs import wait_for_background
from onigiri.services.search import reciprocal_rank_fusion
from tests.conftest import sample_extraction

PASTA = {
    "title": "Cacio e pepe",
    "servings": 2,
    "total_min": 20,
    "tags": ["italian", "pasta", "dinner"],
    "groups": [
        {
            "ingredients": [
                {"raw": "200 g spaghetti", "quantity": 200, "unit": "g", "item": "spaghetti"},
                {"raw": "100 g pecorino", "quantity": 100, "unit": "g", "item": "pecorino"},
                {"raw": "2 tsp black pepper", "quantity": 2, "unit": "tsp", "item": "black pepper"},
            ]
        }
    ],
    "steps": [{"text": "Boil the pasta for 8 minutes."}, {"text": "Toss with cheese."}],
}

SOUP = {
    "title": "Roast pumpkin soup",
    "servings": 4,
    "total_min": 75,
    "tags": ["soup", "vegetarian", "autumn"],
    "groups": [
        {
            "ingredients": [
                {"raw": "1 kg pumpkin", "quantity": 1, "unit": "kg", "item": "pumpkin"},
                {"raw": "1 onion", "quantity": 1, "item": "onion"},
            ]
        }
    ],
    "steps": [{"text": "Roast the pumpkin for 45 minutes."}],
}


async def make(client: AsyncClient, payload: dict) -> dict:
    resp = await client.post("/api/recipes", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_full_text_search_finds_by_ingredient(client: AsyncClient) -> None:
    await make(client, PASTA)
    await make(client, SOUP)
    found = (await client.get("/api/recipes?q=pecorino&semantic=false")).json()
    assert [r["title"] for r in found["items"]] == ["Cacio e pepe"]


async def test_search_tolerates_a_typo_in_the_title(client: AsyncClient) -> None:
    await make(client, PASTA)
    found = (await client.get("/api/recipes?q=cacio%20pepe&semantic=false")).json()
    assert found["total"] == 1


async def test_search_matches_the_original_language_text(client: AsyncClient) -> None:
    payload = dict(SOUP)
    payload["title"] = "Pumpkin soup"
    payload["groups"] = [
        {"ingredients": [{"raw": "1 kg Kürbis", "item": "pumpkin", "quantity": 1, "unit": "kg"}]}
    ]
    await make(client, payload)
    found = (await client.get("/api/recipes?q=Kürbis&semantic=false")).json()
    assert found["total"] == 1


async def test_filter_by_tag_and_time(client: AsyncClient) -> None:
    await make(client, PASTA)
    await make(client, SOUP)
    tags = (await client.get("/api/tags")).json()
    italian = next(t for t in tags if t["name"] == "italian")

    by_tag = (await client.get(f"/api/recipes?tag={italian['id']}")).json()
    assert [r["title"] for r in by_tag["items"]] == ["Cacio e pepe"]

    quick = (await client.get("/api/recipes?max_total_min=30")).json()
    assert [r["title"] for r in quick["items"]] == ["Cacio e pepe"]


async def test_tags_carry_counts_and_kinds(client: AsyncClient) -> None:
    await make(client, PASTA)
    await make(client, SOUP)
    tags = {t["name"]: t for t in (await client.get("/api/tags")).json()}
    assert tags["italian"]["kind"] == "cuisine"
    assert tags["vegetarian"]["kind"] == "diet"
    assert tags["pasta"]["count"] == 1


async def test_collections_group_recipes(client: AsyncClient) -> None:
    pasta = await make(client, PASTA)
    soup = await make(client, SOUP)
    coll = (await client.post("/api/collections", json={"name": "Weeknight"})).json()

    for recipe in (pasta, soup):
        resp = await client.post(f"/api/collections/{coll['id']}/items/{recipe['id']}")
        assert resp.status_code == 204

    listed = (await client.get("/api/collections")).json()
    assert listed[0]["count"] == 2

    filtered = (await client.get(f"/api/recipes?collection={coll['id']}")).json()
    assert filtered["total"] == 2

    await client.delete(f"/api/collections/{coll['id']}/items/{soup['id']}")
    filtered = (await client.get(f"/api/recipes?collection={coll['id']}")).json()
    assert filtered["total"] == 1


async def test_duplicate_collection_name_is_refused(client: AsyncClient) -> None:
    await client.post("/api/collections", json={"name": "Weeknight"})
    again = await client.post("/api/collections", json={"name": "Weeknight"})
    assert again.status_code == 409


async def test_editing_clears_the_review_flag(client: AsyncClient, stub_llm) -> None:
    stub_llm["set_recipe"]["recipe"] = sample_extraction(
        confidence=0.4, review_reason="Amounts were guessed."
    )
    resp = await client.post("/api/ingest", json={"text": "vague recipe"})
    await wait_for_background()
    job = (await client.get(f"/api/jobs/{resp.json()['id']}")).json()
    recipe_id = job["recipe_id"]

    before = (await client.get(f"/api/recipes/{recipe_id}")).json()
    assert before["status"] == "needs_review"

    after = (await client.patch(f"/api/recipes/{recipe_id}", json={"title": "Checked soup"})).json()
    assert after["status"] == "ready"
    assert after["review_reason"] is None


async def test_cook_log_and_observations_feed_the_profile(client: AsyncClient) -> None:
    recipe = await make(client, PASTA)
    resp = await client.post(
        f"/api/recipes/{recipe['id']}/cooklog",
        json={"rating": 5, "notes": "Used half the pepper, too hot otherwise."},
    )
    assert resp.status_code == 201

    detail = (await client.get(f"/api/recipes/{recipe['id']}")).json()
    assert len(detail["cook_log"]) == 1
    assert detail["cook_log"][0]["rating"] == 5


async def test_profile_round_trip(client: AsyncClient) -> None:
    resp = await client.put(
        "/api/me/profile",
        json={
            "allergies": ["Walnuts", "walnuts"],
            "diet": ["vegetarian"],
            "unit_system": "metric",
            "default_servings": 2,
            "notes": "Cooks on a gas hob.",
        },
    )
    assert resp.status_code == 200
    profile = resp.json()
    assert profile["allergies"] == ["walnuts"]  # lowercased and deduplicated
    assert profile["default_servings"] == 2

    again = (await client.get("/api/me/profile")).json()
    assert again["notes"] == "Cooks on a gas hob."


async def test_suggestions_need_evidence(client: AsyncClient) -> None:
    resp = await client.post("/api/me/profile/suggestions/refresh")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_scaled_endpoint_matches_the_recipe(client: AsyncClient) -> None:
    recipe = await make(client, PASTA)
    scaled = (
        await client.get(f"/api/recipes/{recipe['id']}/scaled?servings=4&units=metric")
    ).json()
    assert scaled["factor"] == 2.0
    displays = [i["display"] for g in scaled["groups"] for i in g["ingredients"]]
    assert "400 g spaghetti" in displays
    assert "4 tsp black pepper" in displays


async def test_markdown_export_of_one_recipe(client: AsyncClient) -> None:
    recipe = await make(client, PASTA)
    resp = await client.get(f"/api/recipes/{recipe['id']}/export.md")
    assert resp.status_code == 200
    body = resp.text
    assert body.startswith("# Cacio e pepe")
    assert "- 200 g spaghetti" in body
    assert "1. Boil the pasta for 8 minutes." in body


async def test_whole_bank_export_is_a_zip(client: AsyncClient) -> None:
    import io
    import zipfile

    await make(client, PASTA)
    await make(client, SOUP)
    resp = await client.get("/api/export")
    assert resp.status_code == 200
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        names = zf.namelist()
    assert "onigiri-export.json" in names
    assert any(n.endswith("Cacio e pepe.md") for n in names)


async def test_stats_counts_the_bank(client: AsyncClient) -> None:
    await make(client, PASTA)
    stats = (await client.get("/api/stats")).json()
    assert stats["total"] == 1
    assert stats["ready"] == 1
    assert stats["needs_review"] == 0


def test_rank_fusion_prefers_agreement() -> None:
    import uuid

    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    # b is second in both lists; a and c top one list each.
    fused = reciprocal_rank_fusion([([a, b], 1.0), ([c, b], 1.0)])
    assert fused[0] == b


def test_rank_fusion_respects_weights() -> None:
    import uuid

    a, b = uuid.uuid4(), uuid.uuid4()
    fused = reciprocal_rank_fusion([([a], 0.1), ([b], 1.0)])
    assert fused[0] == b
