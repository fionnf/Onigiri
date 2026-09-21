"""Scaling uses detached ORM objects, so these run without a database."""

from __future__ import annotations

import uuid

import pytest

from onigiri.models import Ingredient, IngredientGroup, Recipe, UnitClass
from onigiri.services.scaling import scale_recipe


def ing(raw: str, qty=None, unit=None, item="", cls=UnitClass.none, scalable=True, **kw):
    return Ingredient(
        id=uuid.uuid4(),
        order_idx=0,
        raw=raw,
        quantity=qty,
        unit=unit,
        unit_class=cls,
        item=item,
        optional=kw.get("optional", False),
        scalable=scalable,
        preparation=kw.get("preparation"),
        quantity_max=kw.get("quantity_max"),
    )


def build(ingredients, servings=4.0) -> Recipe:
    group = IngredientGroup(id=uuid.uuid4(), name=None, order_idx=0)
    group.ingredients = ingredients
    recipe = Recipe(id=uuid.uuid4(), title="Test", servings=servings)
    recipe.groups = [group]
    return recipe


def displays(scaled) -> list[str]:
    return [i.display for g in scaled.groups for i in g.ingredients]


def test_doubling_multiplies_amounts() -> None:
    recipe = build([ing("200 g flour", 200, "g", "flour", UnitClass.weight)], servings=4)
    scaled = scale_recipe(recipe, servings=8)
    assert scaled.factor == 2.0
    assert displays(scaled) == ["400 g flour"]


def test_halving_uses_fractions_for_spoons() -> None:
    recipe = build([ing("1 tsp salt", 1, "tsp", "salt", UnitClass.volume)], servings=4)
    scaled = scale_recipe(recipe, servings=2)
    assert displays(scaled) == ["½ tsp salt"]


def test_seasoning_for_serving_is_not_scaled() -> None:
    recipe = build(
        [ing("flaky salt, for serving", None, None, "flaky salt", scalable=False)], servings=4
    )
    scaled = scale_recipe(recipe, servings=40)
    assert displays(scaled) == ["flaky salt"]


def test_amounts_without_numbers_pass_through() -> None:
    recipe = build([ing("a handful of basil", None, "handful", "basil", UnitClass.count)])
    scaled = scale_recipe(recipe, servings=8)
    assert displays(scaled) == ["handful basil"]


def test_cup_becomes_grams_in_metric() -> None:
    recipe = build(
        [ing("2 cups all-purpose flour", 2, "cup", "all-purpose flour", UnitClass.volume)]
    )
    scaled = scale_recipe(recipe, unit_system="metric")
    assert displays(scaled) == ["250 g all-purpose flour"]
    assert scaled.groups[0].ingredients[0].converted is True


def test_unknown_density_stays_volume_in_metric() -> None:
    recipe = build([ing("1 cup rhubarb", 1, "cup", "chopped rhubarb", UnitClass.volume)])
    scaled = scale_recipe(recipe, unit_system="metric")
    assert scaled.groups[0].ingredients[0].unit == "ml"


def test_spoons_never_convert() -> None:
    recipe = build([ing("1 tbsp olive oil", 1, "tbsp", "olive oil", UnitClass.volume)])
    assert displays(scale_recipe(recipe, unit_system="metric")) == ["1 tbsp olive oil"]
    assert displays(scale_recipe(recipe, unit_system="us")) == ["1 tbsp olive oil"]


def test_grams_become_ounces_in_us() -> None:
    recipe = build([ing("500 g beef", 500, "g", "beef", UnitClass.weight)])
    scaled = scale_recipe(recipe, unit_system="us")
    assert scaled.groups[0].ingredients[0].unit == "lb"
    assert scaled.groups[0].ingredients[0].quantity == pytest.approx(1.0, abs=0.13)


def test_counts_never_convert() -> None:
    recipe = build([ing("2 eggs", 2, None, "eggs", UnitClass.count)])
    assert displays(scale_recipe(recipe, unit_system="metric")) == ["2 eggs"]


def test_ranges_scale_together() -> None:
    recipe = build(
        [ing("2-3 cloves garlic", 2, "clove", "garlic", UnitClass.count, quantity_max=3)],
        servings=4,
    )
    scaled = scale_recipe(recipe, servings=8)
    first = scaled.groups[0].ingredients[0]
    assert first.quantity == 4
    assert first.quantity_max == 6
    assert "4–6" in first.display


def test_no_servings_on_recipe_means_no_scaling() -> None:
    recipe = build([ing("200 g flour", 200, "g", "flour", UnitClass.weight)], servings=None)
    scaled = scale_recipe(recipe, servings=8)
    assert scaled.factor == 1.0
    assert displays(scaled) == ["200 g flour"]


def test_optional_marker_survives_scaling() -> None:
    recipe = build(
        [ing("1 tbsp honey", 1, "tbsp", "honey", UnitClass.volume, optional=True)], servings=2
    )
    assert displays(scale_recipe(recipe, servings=4)) == ["2 tbsp honey (optional)"]
