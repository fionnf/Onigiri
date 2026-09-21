"""Unit table, ingredient-amount parsing, conversion and scaling.

Base units: millilitres for volume, grams for weight, centimetres for length.
Volume/weight crossings use a small density table keyed on the ingredient name;
when no density is known the amount is left in its original class.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from fractions import Fraction

VOLUME = "volume"
WEIGHT = "weight"
COUNT = "count"
LENGTH = "length"
NONE = "none"


@dataclass(frozen=True)
class Unit:
    canonical: str
    unit_class: str
    factor: float  # amount in base units for 1 of this unit
    system: str  # "metric", "us" or "any"
    plural: str | None = None

    def display(self, qty: float) -> str:
        if self.plural and qty != 1:
            return self.plural
        return self.canonical


_UNITS: list[tuple[Unit, tuple[str, ...]]] = [
    # volume - metric
    (
        Unit("ml", VOLUME, 1.0, "metric"),
        ("ml", "milliliter", "millilitre", "milliliters", "millilitres", "cc"),
    ),
    (Unit("cl", VOLUME, 10.0, "metric"), ("cl", "centiliter", "centilitre")),
    (Unit("dl", VOLUME, 100.0, "metric"), ("dl", "deciliter", "decilitre")),
    (Unit("l", VOLUME, 1000.0, "metric"), ("l", "liter", "litre", "liters", "litres")),
    # volume - US customary
    # Spoon measures are read in both systems, so they scale but never convert.
    (Unit("tsp", VOLUME, 4.928922, "any"), ("tsp", "t", "teaspoon", "teaspoons", "tsps")),
    (
        Unit("tbsp", VOLUME, 14.786765, "any"),
        ("tbsp", "tbs", "tbl", "T", "tablespoon", "tablespoons", "tbsps"),
    ),
    (Unit("fl oz", VOLUME, 29.573530, "us"), ("fl oz", "floz", "fluid ounce", "fluid ounces")),
    (Unit("cup", VOLUME, 236.588236, "us", "cups"), ("cup", "cups", "c")),
    (Unit("pint", VOLUME, 473.176473, "us", "pints"), ("pint", "pints", "pt")),
    (Unit("quart", VOLUME, 946.352946, "us", "quarts"), ("quart", "quarts", "qt")),
    (Unit("gallon", VOLUME, 3785.411784, "us", "gallons"), ("gallon", "gallons", "gal")),
    # weight
    (Unit("g", WEIGHT, 1.0, "metric"), ("g", "gram", "grams", "gr", "gramm", "gramme")),
    (Unit("mg", WEIGHT, 0.001, "metric"), ("mg", "milligram", "milligrams")),
    (Unit("kg", WEIGHT, 1000.0, "metric"), ("kg", "kilo", "kilos", "kilogram", "kilograms")),
    (Unit("oz", WEIGHT, 28.349523, "us"), ("oz", "ounce", "ounces")),
    (Unit("lb", WEIGHT, 453.592370, "us", "lbs"), ("lb", "lbs", "pound", "pounds")),
    # length (tin and pan sizes)
    (Unit("cm", LENGTH, 1.0, "metric"), ("cm", "centimeter", "centimetre")),
    (Unit("mm", LENGTH, 0.1, "metric"), ("mm", "millimeter", "millimetre")),
    (Unit("inch", LENGTH, 2.54, "us", "inches"), ("inch", "inches", "in", '"')),
    # countable "units" - never converted, only scaled
    (Unit("piece", COUNT, 1.0, "any", "pieces"), ("piece", "pieces", "pc", "pcs")),
    (Unit("clove", COUNT, 1.0, "any", "cloves"), ("clove", "cloves")),
    (Unit("slice", COUNT, 1.0, "any", "slices"), ("slice", "slices")),
    (Unit("can", COUNT, 1.0, "any", "cans"), ("can", "cans", "tin", "tins")),
    (Unit("jar", COUNT, 1.0, "any", "jars"), ("jar", "jars")),
    (
        Unit("packet", COUNT, 1.0, "any", "packets"),
        ("packet", "packets", "pack", "packs", "package", "packages", "sachet", "sachets"),
    ),
    (Unit("bunch", COUNT, 1.0, "any", "bunches"), ("bunch", "bunches")),
    (Unit("sprig", COUNT, 1.0, "any", "sprigs"), ("sprig", "sprigs")),
    (Unit("stalk", COUNT, 1.0, "any", "stalks"), ("stalk", "stalks", "stick", "sticks")),
    (Unit("head", COUNT, 1.0, "any", "heads"), ("head", "heads")),
    (Unit("handful", COUNT, 1.0, "any", "handfuls"), ("handful", "handfuls")),
    (Unit("pinch", COUNT, 1.0, "any", "pinches"), ("pinch", "pinches")),
    (Unit("dash", COUNT, 1.0, "any", "dashes"), ("dash", "dashes")),
    (Unit("drop", COUNT, 1.0, "any", "drops"), ("drop", "drops")),
    (Unit("leaf", COUNT, 1.0, "any", "leaves"), ("leaf", "leaves")),
]

ALIASES: dict[str, Unit] = {}
for _unit, _names in _UNITS:
    for _n in _names:
        ALIASES.setdefault(_n.lower(), _unit)
    ALIASES.setdefault(_unit.canonical.lower(), _unit)

BY_CANONICAL: dict[str, Unit] = {u.canonical: u for u, _ in _UNITS}

# Preference order when rendering a converted amount, largest first.
_LADDER: dict[tuple[str, str], list[str]] = {
    (VOLUME, "metric"): ["l", "ml"],
    (VOLUME, "us"): ["gallon", "quart", "cup", "fl oz", "tbsp", "tsp"],
    (WEIGHT, "metric"): ["kg", "g"],
    (WEIGHT, "us"): ["lb", "oz"],
    (LENGTH, "metric"): ["cm"],
    (LENGTH, "us"): ["inch"],
}

# grams per millilitre, matched on the longest substring of the ingredient name.
DENSITIES: dict[str, float] = {
    "water": 1.0,
    "milk": 1.03,
    "buttermilk": 1.03,
    "cream": 1.0,
    "yogurt": 1.03,
    "yoghurt": 1.03,
    "stock": 1.0,
    "broth": 1.0,
    "wine": 0.99,
    "vinegar": 1.01,
    "soy sauce": 1.15,
    "oil": 0.918,
    "olive oil": 0.918,
    "butter": 0.911,
    "honey": 1.42,
    "maple syrup": 1.32,
    "molasses": 1.4,
    "golden syrup": 1.43,
    "all-purpose flour": 0.53,
    "plain flour": 0.53,
    "bread flour": 0.55,
    "flour": 0.53,
    "wholemeal flour": 0.51,
    "whole wheat flour": 0.51,
    "cornstarch": 0.63,
    "cornflour": 0.63,
    "cocoa powder": 0.41,
    "cocoa": 0.41,
    "powdered sugar": 0.56,
    "icing sugar": 0.56,
    "confectioners sugar": 0.56,
    "brown sugar": 0.93,
    "caster sugar": 0.85,
    "granulated sugar": 0.845,
    "sugar": 0.845,
    "salt": 1.2,
    "rice": 0.85,
    "oats": 0.4,
    "rolled oats": 0.4,
    "breadcrumbs": 0.4,
    "panko": 0.25,
    "lentils": 0.85,
    "chocolate chips": 0.6,
    "nuts": 0.5,
    "almonds": 0.6,
    "walnuts": 0.47,
    "parmesan": 0.4,
    "grated cheese": 0.4,
    "cheese": 0.45,
}

_FRACTION_CHARS = {
    "¼": Fraction(1, 4),
    "½": Fraction(1, 2),
    "¾": Fraction(3, 4),
    "⅓": Fraction(1, 3),
    "⅔": Fraction(2, 3),
    "⅛": Fraction(1, 8),
    "⅜": Fraction(3, 8),
    "⅝": Fraction(5, 8),
    "⅞": Fraction(7, 8),
    "⅕": Fraction(1, 5),
    "⅙": Fraction(1, 6),
    "⅐": Fraction(1, 7),
}

_NUMBER_WORDS = {
    "a": 1.0,
    "an": 1.0,
    "one": 1.0,
    "two": 2.0,
    "three": 3.0,
    "four": 4.0,
    "five": 5.0,
    "six": 6.0,
    "seven": 7.0,
    "eight": 8.0,
    "nine": 9.0,
    "ten": 10.0,
    "eleven": 11.0,
    "twelve": 12.0,
    "half": 0.5,
    "quarter": 0.25,
    "dozen": 12.0,
}

_PREP_WORDS = (
    "chopped",
    "finely chopped",
    "roughly chopped",
    "diced",
    "minced",
    "sliced",
    "thinly sliced",
    "grated",
    "shredded",
    "melted",
    "softened",
    "room temperature",
    "beaten",
    "peeled",
    "crushed",
    "toasted",
    "drained",
    "rinsed",
    "cubed",
    "julienned",
    "halved",
    "quartered",
    "divided",
    "packed",
    "sifted",
    "at room temperature",
    "plus more for serving",
    "finely grated",
    "freshly ground",
    "trimmed",
    "deseeded",
    "seeded",
    "zested",
    "juiced",
)


_FRACTION_EXPANSIONS = {
    "\N{VULGAR FRACTION ONE QUARTER}": " 1/4",
    "\N{VULGAR FRACTION ONE HALF}": " 1/2",
    "\N{VULGAR FRACTION THREE QUARTERS}": " 3/4",
    "\N{VULGAR FRACTION ONE THIRD}": " 1/3",
    "\N{VULGAR FRACTION TWO THIRDS}": " 2/3",
    "\N{VULGAR FRACTION ONE EIGHTH}": " 1/8",
    "\N{VULGAR FRACTION THREE EIGHTHS}": " 3/8",
    "\N{VULGAR FRACTION FIVE EIGHTHS}": " 5/8",
    "\N{VULGAR FRACTION SEVEN EIGHTHS}": " 7/8",
    "\N{VULGAR FRACTION ONE FIFTH}": " 1/5",
    "\N{VULGAR FRACTION ONE SIXTH}": " 1/6",
    "\N{VULGAR FRACTION ONE SEVENTH}": " 1/7",
}


def normalise_text(text: str) -> str:
    """Normalise whitespace and spell vulgar fractions out as n/d.

    The expansion has to happen before NFKC. NFKC rewrites "1<one half>" as
    "11/2", which then reads as eleven halves rather than one and a half.
    """
    for glyph, replacement in _FRACTION_EXPANSIONS.items():
        if glyph in text:
            text = text.replace(glyph, replacement)
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\N{FRACTION SLASH}", "/").replace("\N{NO-BREAK SPACE}", " ")
    return " ".join(text.split()).strip()


def parse_number(token: str) -> float | None:
    """Parse '1', '1.5', '1/2', '1 1/2', vulgar fractions and number words."""
    token = normalise_text(token).strip()
    if not token:
        return None
    if token.lower() in _NUMBER_WORDS:
        return _NUMBER_WORDS[token.lower()]

    total = 0.0
    for part in token.split():
        try:
            total += float(Fraction(part.replace(",", ".")))
        except (ValueError, ZeroDivisionError):
            return None
    return total


def lookup_unit(token: str | None) -> Unit | None:
    if not token:
        return None
    t = normalise_text(token).lower().strip(" .")
    if t in ALIASES:
        return ALIASES[t]
    if t.endswith("s") and t[:-1] in ALIASES:
        return ALIASES[t[:-1]]
    return None


def unit_class_of(unit: str | None) -> str:
    u = lookup_unit(unit)
    return u.unit_class if u else (NONE if not unit else COUNT)


@dataclass
class ParsedAmount:
    quantity: float | None = None
    quantity_max: float | None = None
    unit: str | None = None
    unit_class: str = NONE
    item: str = ""
    preparation: str | None = None
    optional: bool = False
    raw: str = ""


_QTY_RE = re.compile(
    r"^\s*(?P<qty>(?:\d+[\s ]*\d?/\d|\d+(?:[.,]\d+)?|[¼-¾⅐-⅞])"
    r"(?:\s*[¼-¾⅐-⅞])?)"
    r"(?:\s*(?:-|–|—|to)\s*"
    r"(?P<qty2>\d+(?:[.,]\d+)?|[¼-¾⅐-⅞]|\d+\s*\d?/\d))?\s*",
    re.IGNORECASE,
)


def parse_ingredient(line: str) -> ParsedAmount:
    """Best-effort parse of a free-text ingredient line.

    The LLM extractor normally supplies structured fields; this is the fallback for
    manual entry and for validating what the model returned.
    """
    raw = normalise_text(line)
    out = ParsedAmount(raw=raw)
    text = raw

    # optional markers
    if re.search(r"\(\s*optional\s*\)|,\s*optional\b|\boptional\b\s*:?$", text, re.I):
        out.optional = True
        text = re.sub(r"\(\s*optional\s*\)|,\s*optional\b|\boptional\b\s*:?$", "", text, flags=re.I)

    text = text.strip(" -–•*\t")

    m = _QTY_RE.match(text)
    if m and m.group("qty"):
        q = parse_number(m.group("qty"))
        if q is not None:
            out.quantity = q
            if m.group("qty2"):
                out.quantity_max = parse_number(m.group("qty2"))
            text = text[m.end() :]
    else:
        first = text.split(" ", 1)[0].lower().strip(".,")
        if first in _NUMBER_WORDS and first not in {"a", "an"}:
            out.quantity = _NUMBER_WORDS[first]
            text = text.split(" ", 1)[1] if " " in text else ""

    # "a handful of basil" is one handful; drop the article so the unit is visible
    tokens = text.split()
    if tokens and tokens[0].lower() in {"a", "an"} and len(tokens) > 1:
        if lookup_unit(tokens[1].strip(".,")):
            out.quantity = out.quantity if out.quantity is not None else 1.0
            tokens = tokens[1:]
            text = " ".join(tokens)

    # unit: try two-word then one-word
    if tokens:
        two = " ".join(tokens[:2]).lower().strip(".,")
        one = tokens[0].lower().strip(".,")
        u = lookup_unit(two)
        if u:
            out.unit, out.unit_class = u.canonical, u.unit_class
            tokens = tokens[2:]
        else:
            u = lookup_unit(one)
            if u:
                out.unit, out.unit_class = u.canonical, u.unit_class
                tokens = tokens[1:]
    text = " ".join(tokens)

    text = re.sub(r"^\s*(of|de|von)\s+", "", text, flags=re.I).strip()

    # preparation after a comma, or a known prep phrase in parentheses
    prep: str | None = None
    if "," in text:
        head, tail = text.split(",", 1)
        if tail.strip():
            prep = tail.strip()
            text = head.strip()
    paren = re.search(r"\(([^)]*)\)", text)
    if paren:
        inner = paren.group(1).strip()
        if any(w in inner.lower() for w in _PREP_WORDS):
            prep = f"{prep}, {inner}" if prep else inner
            text = (text[: paren.start()] + text[paren.end() :]).strip()

    out.item = re.sub(r"\s{2,}", " ", text).strip(" ,.;")
    out.preparation = prep
    if out.unit is None and out.quantity is not None:
        out.unit_class = COUNT if out.item else NONE
    return out


def density_for(item: str | None) -> float | None:
    if not item:
        return None
    low = item.lower()
    best: tuple[int, float] | None = None
    for key, dens in DENSITIES.items():
        if key in low and (best is None or len(key) > best[0]):
            best = (len(key), dens)
    return best[1] if best else None


def to_base(quantity: float, unit: str | None) -> tuple[float, str] | None:
    u = lookup_unit(unit)
    if not u:
        return None
    return quantity * u.factor, u.unit_class


def convert(
    quantity: float, unit: str | None, target_system: str, item: str | None = None
) -> tuple[float, str | None]:
    """Convert an amount into the target system, crossing volume/weight when a density is known."""
    u = lookup_unit(unit)
    if u is None or u.unit_class in (COUNT, NONE):
        return quantity, unit
    if u.system == target_system or u.system == "any":
        return _pick_unit(quantity * u.factor, u.unit_class, target_system)

    base = quantity * u.factor
    return _pick_unit(base, u.unit_class, target_system)


def convert_cross(
    quantity: float, unit: str | None, to_class: str, item: str | None, target_system: str
) -> tuple[float, str | None] | None:
    """Convert between volume and weight using the density table, if we know the ingredient."""
    u = lookup_unit(unit)
    if u is None or u.unit_class == to_class or u.unit_class in (COUNT, NONE):
        return None
    dens = density_for(item)
    if dens is None:
        return None
    base = quantity * u.factor
    if u.unit_class == VOLUME and to_class == WEIGHT:
        return _pick_unit(base * dens, WEIGHT, target_system)
    if u.unit_class == WEIGHT and to_class == VOLUME:
        return _pick_unit(base / dens, VOLUME, target_system)
    return None


def _pick_unit(base_qty: float, unit_class: str, system: str) -> tuple[float, str | None]:
    ladder = _LADDER.get((unit_class, system))
    if not ladder:
        ladder = _LADDER.get((unit_class, "metric"))
    if not ladder:
        return base_qty, None
    for name in ladder:
        u = BY_CANONICAL[name]
        value = base_qty / u.factor
        if value >= 1 or name == ladder[-1]:
            return value, u.canonical
    return base_qty, ladder[-1]


def round_amount(value: float, unit: str | None) -> float:
    """Round to something a cook would actually measure."""
    u = lookup_unit(unit)
    cls = u.unit_class if u else COUNT
    name = u.canonical if u else None

    if cls == COUNT or name is None:
        if value < 1:
            return round(value * 4) / 4 or 0.25
        return round(value * 2) / 2 if value < 3 else round(value)

    if name in {"g", "ml"}:
        if value < 10:
            return round(value * 2) / 2
        if value < 100:
            return round(value)
        if value < 1000:
            return round(value / 5) * 5
        return round(value / 10) * 10
    if name in {"kg", "l"}:
        return round(value, 2)
    if name in {"tsp", "tbsp"}:
        return _nearest_fraction(value, 8)
    if name in {"cup", "pint", "quart", "gallon", "fl oz"}:
        return _nearest_fraction(value, 8 if value < 4 else 4)
    if name in {"oz", "lb"}:
        return _nearest_fraction(value, 4)
    return round(value, 2)


def _nearest_fraction(value: float, denom: int) -> float:
    if value <= 0:
        return 0.0
    step = 1 / denom
    snapped = round(value / step) * step
    if snapped == 0:
        snapped = step
    return round(snapped, 4)


_UNICODE_FRACTIONS = {
    Fraction(1, 2): "½",
    Fraction(1, 3): "⅓",
    Fraction(2, 3): "⅔",
    Fraction(1, 4): "¼",
    Fraction(3, 4): "¾",
    Fraction(1, 8): "⅛",
    Fraction(3, 8): "⅜",
    Fraction(5, 8): "⅝",
    Fraction(7, 8): "⅞",
}


def format_quantity(value: float | None, use_fractions: bool = True) -> str:
    """Render a number the way a recipe would: 1½ rather than 1.5."""
    if value is None:
        return ""
    if abs(value - round(value)) < 1e-6:
        return str(round(value))
    if use_fractions:
        frac = Fraction(value).limit_denominator(8)
        whole = int(frac)
        rest = frac - whole
        if rest in _UNICODE_FRACTIONS and abs(float(frac) - value) < 0.02:
            glyph = _UNICODE_FRACTIONS[rest]
            return f"{whole}{glyph}" if whole else glyph
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text


def scale_quantity(quantity: float | None, factor: float) -> float | None:
    if quantity is None:
        return None
    return quantity * factor


def detect_timers(text: str) -> list[int]:
    """Find durations in a step so the UI can offer a timer. Returns seconds."""
    seconds: list[int] = []
    pattern = re.compile(
        r"(?P<a>\d+(?:[.,]\d+)?)\s*(?:-|–|to)?\s*(?P<b>\d+(?:[.,]\d+)?)?\s*"
        r"(?P<unit>hours?|hrs?|h\b|minutes?|mins?|m\b|seconds?|secs?|s\b)",
        re.IGNORECASE,
    )
    for m in pattern.finditer(text):
        unit = m.group("unit").lower()
        value = float((m.group("b") or m.group("a")).replace(",", "."))
        if unit.startswith(("hour", "hr", "h")):
            mult = 3600
        elif unit.startswith(("min", "m")):
            mult = 60
        else:
            mult = 1
        secs = round(value * mult)
        if 5 <= secs <= 24 * 3600 and secs not in seconds:
            seconds.append(secs)
    return seconds[:4]
