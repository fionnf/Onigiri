"""The unit engine decides whether a scaled recipe is usable, so it is tested hard."""

from __future__ import annotations

import pytest

from onigiri.units import (
    convert,
    convert_cross,
    density_for,
    detect_timers,
    format_quantity,
    lookup_unit,
    parse_ingredient,
    parse_number,
    round_amount,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1", 1.0),
        ("2.5", 2.5),
        ("2,5", 2.5),
        ("1/2", 0.5),
        ("3/4", 0.75),
        ("1 1/2", 1.5),
        ("1½", 1.5),
        ("¼", 0.25),
        ("⅔", pytest.approx(2 / 3)),
        ("two", 2.0),
        ("half", 0.5),
        ("dozen", 12.0),
    ],
)
def test_parse_number(text: str, expected: float) -> None:
    assert parse_number(text) == expected


def test_parse_number_rejects_words() -> None:
    assert parse_number("some") is None
    assert parse_number("") is None


@pytest.mark.parametrize(
    ("alias", "canonical"),
    [
        ("grams", "g"),
        ("Gramm", "g"),
        ("kilograms", "kg"),
        ("ounces", "oz"),
        ("pounds", "lb"),
        ("tablespoons", "tbsp"),
        ("Tbs", "tbsp"),
        ("teaspoon", "tsp"),
        ("cups", "cup"),
        ("millilitres", "ml"),
        ("cloves", "clove"),
        ("tins", "can"),
    ],
)
def test_unit_aliases(alias: str, canonical: str) -> None:
    unit = lookup_unit(alias)
    assert unit is not None
    assert unit.canonical == canonical


def test_parse_ingredient_full_line() -> None:
    p = parse_ingredient("2-3 cloves garlic, finely chopped")
    assert p.quantity == 2
    assert p.quantity_max == 3
    assert p.unit == "clove"
    assert p.item == "garlic"
    assert p.preparation == "finely chopped"
    assert p.optional is False


def test_parse_ingredient_metric_and_optional() -> None:
    p = parse_ingredient("250 g plain flour (optional)")
    assert p.quantity == 250
    assert p.unit == "g"
    assert p.item == "plain flour"
    assert p.optional is True


def test_parse_ingredient_mixed_fraction() -> None:
    p = parse_ingredient("1 1/2 cups whole milk")
    assert p.quantity == 1.5
    assert p.unit == "cup"
    assert p.item == "whole milk"


def test_parse_ingredient_no_amount() -> None:
    p = parse_ingredient("a handful of basil leaves")
    assert p.unit == "handful"
    assert "basil" in p.item


def test_parse_ingredient_bare_item() -> None:
    p = parse_ingredient("Salt and pepper")
    assert p.quantity is None
    assert p.unit is None
    assert p.item == "Salt and pepper"


def test_convert_weight_us_to_metric() -> None:
    # 1 lb is 454 g, not 0.45 kg: the ladder picks the unit a cook would write.
    qty, unit = convert(1, "lb", "metric")
    assert unit == "g"
    assert qty == pytest.approx(453.6, rel=1e-3)

    qty, unit = convert(5, "lb", "metric")
    assert unit == "kg"
    assert qty == pytest.approx(2.268, rel=1e-3)


def test_convert_volume_metric_to_us() -> None:
    qty, unit = convert(500, "ml", "us")
    assert unit == "cup"
    assert qty == pytest.approx(2.11, rel=1e-2)


def test_convert_leaves_counts_alone() -> None:
    assert convert(3, "clove", "metric") == (3, "clove")
    assert convert(2, None, "us") == (2, None)


def test_cross_conversion_uses_density() -> None:
    qty, unit = convert_cross(2, "cup", "weight", "all-purpose flour", "metric")
    assert unit == "g"
    assert qty == pytest.approx(250, abs=5)


def test_cross_conversion_without_density_returns_none() -> None:
    assert convert_cross(1, "cup", "weight", "chopped rhubarb", "metric") is None


def test_density_prefers_longest_match() -> None:
    assert density_for("brown sugar") == 0.93
    assert density_for("granulated sugar") == 0.845


@pytest.mark.parametrize(
    ("value", "unit", "expected"),
    [
        (250.4, "g", 250),
        (7.3, "g", 7.5),
        (1234.0, "g", 1230),
        (0.26, "tsp", 0.25),
        (1.49, "cup", 1.5),
    ],
)
def test_round_amount(value: float, unit: str, expected: float) -> None:
    assert round_amount(value, unit) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("value", "expected"),
    [(1.0, "1"), (1.5, "1½"), (0.25, "¼"), (2.0, "2"), (0.75, "¾")],
)
def test_format_quantity(value: float, expected: str) -> None:
    assert format_quantity(value) == expected


def test_detect_timers() -> None:
    assert detect_timers("Simmer for 20 minutes, stirring.") == [1200]
    assert detect_timers("Bake 11 to 12 minutes.") == [720]
    assert detect_timers("Rest 1 hour then 30 min more.") == [3600, 1800]


def test_detect_timers_ignores_nonsense() -> None:
    assert detect_timers("Heat the oven to 180C.") == []
    assert detect_timers("Use 2 eggs.") == []
