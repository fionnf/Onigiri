"""The Claude boundary: request shape, error mapping, and the flat wire format."""

from __future__ import annotations

from types import SimpleNamespace

import anthropic
import httpx2
import pytest

from onigiri.config import settings
from onigiri.recipe_schema import WireIngredient, WireRecipe, WireStep, to_extracted
from onigiri.services import llm


def wire(**overrides) -> WireRecipe:
    data = dict(
        is_recipe=True,
        title="Red lentil soup",
        title_original="Linsensuppe",
        language="DE",
        description="",
        servings=4,
        servings_unit="servings",
        prep_min=0,
        cook_min=25,
        total_min=0,
        ingredients=[
            WireIngredient(
                group="",
                raw="250 g rote Linsen",
                quantity=250,
                quantity_max=0,
                unit="g",
                item="red lentils",
                preparation="",
                optional=False,
            ),
            WireIngredient(
                group="Topping",
                raw="1 Zitrone",
                quantity=1,
                quantity_max=0,
                unit="",
                item="lemon",
                preparation="zested",
                optional=True,
            ),
            WireIngredient(
                group="",
                raw="Salz",
                quantity=0,
                quantity_max=0,
                unit="",
                item="salt",
                preparation="to taste",
                optional=False,
            ),
        ],
        steps=[WireStep(section="", text="Simmer 20 minutes."), WireStep(section="", text=" ")],
        equipment=[" pot ", ""],
        tags=["Soup", " German "],
        confidence=1.4,
        missing=["fat for frying"],
        review_reason="",
        profile_flags=[],
    )
    data.update(overrides)
    return WireRecipe(**data)


def test_empty_and_zero_become_unknown() -> None:
    r = to_extracted(wire())
    assert r.description is None
    assert r.prep_min is None
    assert r.total_min is None
    assert r.cook_min == 25
    assert r.review_reason is None
    salt = r.ingredient_groups[0].ingredients[1]
    assert salt.quantity is None
    assert salt.unit is None
    assert salt.preparation == "to taste"


def test_groups_are_rebuilt_in_order() -> None:
    r = to_extracted(wire())
    assert [g.name for g in r.ingredient_groups] == [None, "Topping"]
    assert [i.item for i in r.ingredient_groups[0].ingredients] == ["red lentils", "salt"]
    assert r.ingredient_groups[1].ingredients[0].optional is True


def test_values_are_cleaned() -> None:
    r = to_extracted(wire())
    assert r.language == "de"
    assert r.tags == ["soup", "german"]
    assert r.equipment == ["pot"]
    assert r.confidence == 1.0
    assert [s.text for s in r.steps] == ["Simmer 20 minutes."]


def test_a_range_needs_a_larger_upper_bound() -> None:
    bad = wire(
        ingredients=[
            WireIngredient(
                group="",
                raw="2 eggs",
                quantity=2,
                quantity_max=2,
                unit="",
                item="eggs",
                preparation="",
                optional=False,
            ),
        ]
    )
    assert to_extracted(bad).ingredient_groups[0].ingredients[0].quantity_max is None


def test_english_title_is_not_repeated_as_original() -> None:
    assert to_extracted(wire(title_original="red lentil SOUP")).title_original is None


def test_wire_schema_has_no_optional_or_union_fields() -> None:
    """Claude rejects schemas with many optional or nullable fields as too complex."""
    from onigiri.recipe_schema import WirePhotoText

    def walk(node, found):
        if isinstance(node, dict):
            if "properties" in node:
                found["optional"] += len(set(node["properties"]) - set(node.get("required", [])))
            if "anyOf" in node or isinstance(node.get("type"), list):
                found["union"] += 1
            for value in node.values():
                walk(value, found)
        elif isinstance(node, list):
            for value in node:
                walk(value, found)
        return found

    for model in (WireRecipe, WirePhotoText):
        found = walk(model.model_json_schema(), {"optional": 0, "union": 0})
        assert found == {"optional": 0, "union": 0}, model.__name__


# --------------------------------------------------------------------------- client


class FakeMessages:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls: list[dict] = []

    async def parse(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.response


def fake_response(*, parsed=None, stop_reason="end_turn", stop_details=None):
    return SimpleNamespace(
        parsed_output=parsed,
        stop_reason=stop_reason,
        stop_details=stop_details,
        model=settings.anthropic_model,
        usage=SimpleNamespace(input_tokens=120, output_tokens=40),
    )


@pytest.fixture
def fake_claude(monkeypatch):
    def install(**kwargs):
        messages = FakeMessages(**kwargs)
        client = SimpleNamespace(beta=SimpleNamespace(messages=messages))
        monkeypatch.setattr(llm, "_claude", client)
        return messages

    yield install
    llm.reset_clients()


def status_error(cls, status: int):
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx2.Response(status, request=request, json={"error": {"message": "x"}})
    return cls("x", response=response, body=None)


async def test_request_uses_fallback_effort_and_schema(fake_claude) -> None:
    messages = fake_claude(response=fake_response(parsed=wire()))
    usage = llm.Usage()
    result = await llm.structured(
        WireRecipe, "system text", "content", schema_name="extracted_recipe", usage=usage
    )
    assert isinstance(result, WireRecipe)
    call = messages.calls[0]
    assert call["model"] == settings.anthropic_model
    assert call["fallbacks"] == "default"
    assert call["betas"] == [llm.FALLBACK_BETA]
    assert call["output_format"] is WireRecipe
    assert call["output_config"] == {"effort": settings.anthropic_effort}
    assert call["system"] == "system text"
    assert usage.as_dict()["input_tokens"] == 120
    assert usage.calls == {"extracted_recipe": 1}


async def test_effort_can_be_overridden(fake_claude) -> None:
    messages = fake_claude(response=fake_response(parsed=wire()))
    await llm.structured(WireRecipe, "s", "c", schema_name="frame_text", effort="low")
    assert messages.calls[0]["output_config"] == {"effort": "low"}


async def test_refusal_is_reported_not_parsed(fake_claude) -> None:
    fake_claude(
        response=fake_response(
            stop_reason="refusal", stop_details=SimpleNamespace(category="bio", explanation=None)
        )
    )
    with pytest.raises(llm.LLMDeclined, match=r"declined.*bio.*Paste the recipe text"):
        await llm.structured(WireRecipe, "s", "c", schema_name="extracted_recipe")


async def test_truncated_answer_is_an_error(fake_claude) -> None:
    fake_claude(response=fake_response(stop_reason="max_tokens"))
    with pytest.raises(llm.LLMError, match="ran out of room"):
        await llm.structured(WireRecipe, "s", "c", schema_name="extracted_recipe")


async def test_rejected_key_says_so(fake_claude) -> None:
    fake_claude(error=status_error(anthropic.AuthenticationError, 401))
    with pytest.raises(llm.LLMNotConfigured, match="ANTHROPIC_API_KEY was rejected"):
        await llm.structured(WireRecipe, "s", "c", schema_name="extracted_recipe")


async def test_rate_limit_is_explained(fake_claude) -> None:
    fake_claude(error=status_error(anthropic.RateLimitError, 429))
    with pytest.raises(llm.LLMError, match="rate limiting"):
        await llm.structured(WireRecipe, "s", "c", schema_name="extracted_recipe")


async def test_missing_key_is_clear(monkeypatch) -> None:
    llm.reset_clients()
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    with pytest.raises(llm.LLMNotConfigured, match="ANTHROPIC_API_KEY is not set"):
        await llm.structured(WireRecipe, "s", "c", schema_name="extracted_recipe")


def test_images_use_the_anthropic_block_shape() -> None:
    part = llm.image_part(b"\xff\xd8abc", "image/jpeg")
    assert part["type"] == "image"
    assert part["source"]["type"] == "base64"
    assert part["source"]["media_type"] == "image/jpeg"
    assert part["source"]["data"] == "/9hhYmM="


async def test_speech_and_embeddings_need_openai(monkeypatch) -> None:
    llm.reset_clients()
    monkeypatch.setattr(settings, "openai_api_key", "")
    assert llm.speech_available() is False
    with pytest.raises(llm.LLMNotConfigured):
        await llm.embed("lentil soup")
