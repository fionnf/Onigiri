"""Serving scaling and metric/US conversion for a stored recipe."""

from __future__ import annotations

from dataclasses import dataclass, field

from onigiri.models import Recipe, UnitClass
from onigiri.units import (
    COUNT,
    NONE,
    WEIGHT,
    convert,
    convert_cross,
    format_quantity,
    lookup_unit,
    round_amount,
)

# Bulk measures cross to weight in metric; a teaspoon of spice stays a teaspoon.
BULK_VOLUME_UNITS = {"cup", "pint", "quart", "gallon", "fl oz", "l", "dl"}


@dataclass
class ScaledIngredient:
    id: str
    raw: str
    item: str
    preparation: str | None
    optional: bool
    quantity: float | None
    quantity_max: float | None
    unit: str | None
    display: str
    converted: bool = False
    scaled: bool = True


@dataclass
class ScaledGroup:
    id: str
    name: str | None
    ingredients: list[ScaledIngredient] = field(default_factory=list)


@dataclass
class ScaledRecipe:
    servings: float | None
    factor: float
    unit_system: str
    groups: list[ScaledGroup] = field(default_factory=list)


def _render(
    qty: float | None,
    qty_max: float | None,
    unit: str | None,
    item: str,
    preparation: str | None,
    optional: bool,
) -> str:
    bits: list[str] = []
    if qty is not None:
        text = format_quantity(qty)
        if qty_max is not None and qty_max != qty:
            text += f"–{format_quantity(qty_max)}"
        bits.append(text)
    if unit:
        u = lookup_unit(unit)
        bits.append(u.display(qty or 1) if u else unit)
    if item:
        bits.append(item)
    line = " ".join(bits)
    if preparation:
        line += f", {preparation}"
    if optional:
        line += " (optional)"
    return line


def scale_recipe(
    recipe: Recipe,
    *,
    servings: float | None = None,
    unit_system: str | None = None,
) -> ScaledRecipe:
    """Recompute every amount for a new serving count and unit system.

    Amounts the source never gave a number to are passed through untouched, and
    seasoning to taste is not multiplied.
    """
    base = recipe.servings
    factor = 1.0
    if servings and base and base > 0:
        factor = servings / base
    target_system = unit_system if unit_system in {"metric", "us"} else None

    out = ScaledRecipe(
        servings=servings or base,
        factor=round(factor, 4),
        unit_system=target_system or "original",
    )

    for group in recipe.groups:
        sg = ScaledGroup(id=str(group.id), name=group.name)
        for ing in group.ingredients:
            qty = float(ing.quantity) if ing.quantity is not None else None
            qty_max = float(ing.quantity_max) if ing.quantity_max is not None else None
            unit = ing.unit
            converted = False
            scaled = ing.scalable

            if qty is not None and ing.scalable and factor != 1.0:
                qty *= factor
                if qty_max is not None:
                    qty_max *= factor

            if (
                qty is not None
                and target_system
                and ing.unit_class
                not in (
                    UnitClass.count,
                    UnitClass.none,
                )
            ):
                u = lookup_unit(unit)
                crossed = False
                if u and target_system == "metric" and u.canonical in BULK_VOLUME_UNITS:
                    # A metric cook weighs a cup of flour; it is 125 g, not 235 ml.
                    cross = convert_cross(qty, unit, WEIGHT, ing.item, "metric")
                    if cross:
                        if qty_max is not None:
                            cm = convert_cross(qty_max, unit, WEIGHT, ing.item, "metric")
                            qty_max = cm[0] if cm else None
                        qty, unit = cross
                        crossed = converted = True
                if not crossed and u and u.system not in ("any", target_system):
                    new_qty, new_unit = convert(qty, unit, target_system, ing.item)
                    if qty_max is not None:
                        qty_max, _ = convert(qty_max, unit, target_system, ing.item)
                    qty, unit, converted = new_qty, new_unit, True

            if qty is not None:
                qty = round_amount(qty, unit)
            if qty_max is not None:
                qty_max = round_amount(qty_max, unit)

            sg.ingredients.append(
                ScaledIngredient(
                    id=str(ing.id),
                    raw=ing.raw,
                    item=ing.item or "",
                    preparation=ing.preparation,
                    optional=ing.optional,
                    quantity=qty,
                    quantity_max=qty_max,
                    unit=unit,
                    display=_render(
                        qty, qty_max, unit, ing.item or "", ing.preparation, ing.optional
                    ),
                    converted=converted,
                    scaled=scaled and factor != 1.0,
                )
            )
        out.groups.append(sg)
    return out


__all__ = ["COUNT", "NONE", "ScaledRecipe", "scale_recipe"]
