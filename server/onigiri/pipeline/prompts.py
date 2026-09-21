"""Prompt construction. The taste profile is injected here and nowhere else."""

from __future__ import annotations

from dataclasses import dataclass

from onigiri.models import Profile

EXTRACT_SYSTEM = """\
You turn messy recipe sources into one structured recipe.

Sources are captions, video transcripts, on-screen text from video frames, web page
text, or text read off a photo. They are often incomplete, out of order, in another
language, or mixed with unrelated chatter.

Rules, in order of importance:

1. Never invent. If the source does not state an amount, a temperature, a time or a
   step, leave the field null and name what is missing in `missing`. A recipe with
   three honest steps is worth more than eight guessed ones.
2. Use every part of the source. A caption may list ingredients while the transcript
   gives the method and the on-screen text gives the oven temperature. Merge them.
   When two parts disagree, prefer written text over speech, and say so in
   `review_reason`.
3. Write `title`, `item`, `preparation`, `steps`, `equipment` and `tags` in English.
   Keep the source-language title in `title_original` and set `language` to the ISO
   639-1 code of the source. If the source is already English, set `title_original`
   to null.
4. Keep `raw` for each ingredient exactly as the source wrote it, in the original
   language, including the amount. Everything else in the ingredient is normalised.
5. Split amounts properly: "2-3 cloves garlic, finely chopped" is quantity 2,
   quantity_max 3, unit "clove", item "garlic", preparation "finely chopped".
   Amounts with no number ("a handful of basil") keep quantity null and unit null.
6. Steps are imperative, one action group each, in cooking order. Do not number them.
   Keep times and temperatures inside the step text so timers can be detected.
7. `tags` are lowercase and short: cuisine, course, diet, main protein, technique.
   Between three and eight of them.
8. `confidence` is how completely the source specified the recipe: 0.9+ when
   ingredients with amounts and full method are present, 0.5 when the method is
   vague or amounts are missing, below 0.4 when you are mostly guessing structure.
9. Set `review_reason` to one short line whenever a human should check something.
   Set it to null only when the recipe is complete and unambiguous.
10. If the source is not a recipe at all, set `is_recipe` false, give the best title
    you can, and leave ingredients and steps empty.
"""

PHOTO_SYSTEM = """\
You read text off photographs of recipes: cookbook and magazine pages, handwritten
recipe cards, and screenshots of apps or web pages.

Rules:

1. Transcribe what is actually written, in the original language. Do not translate,
   do not correct, do not reorder, do not complete half-finished lines.
2. Preserve reading order. For a multi-column page, finish a column before starting
   the next. For a two-page spread, read the left page fully, then the right.
3. Keep headings, ingredient lists and method paragraphs on separate lines. Keep
   amounts attached to their ingredient.
4. Handwriting: read what you can, and put any line you are unsure of into
   `low_confidence_lines` verbatim as you read it. Never smooth over a guess.
5. If the photo has no readable recipe text, for example a photo of a finished dish,
   set `has_recipe_text` false and put any visible words in `text`.
"""


@dataclass
class ProfileContext:
    text: str

    def __bool__(self) -> bool:
        return bool(self.text.strip())


def profile_block(profile: Profile | None) -> str:
    """Render the taste profile as the part of the prompt that personalises output."""
    if profile is None:
        return ""
    lines: list[str] = []
    if profile.diet:
        lines.append(f"Diet: {', '.join(profile.diet)}")
    if profile.allergies:
        lines.append(f"Allergies (never overlook these): {', '.join(profile.allergies)}")
    if profile.dislikes:
        lines.append(f"Dislikes: {', '.join(profile.dislikes)}")
    if profile.likes:
        lines.append(f"Likes: {', '.join(profile.likes)}")
    if profile.pantry_staples:
        lines.append(f"Always in the pantry: {', '.join(profile.pantry_staples)}")
    if profile.unit_system:
        lines.append(f"Preferred units: {profile.unit_system}")
    if profile.default_servings:
        lines.append(f"Usually cooks for: {profile.default_servings}")
    if profile.notes.strip():
        lines.append(f"Notes: {profile.notes.strip()}")
    if not lines:
        return ""
    return (
        "\nThe cook you are extracting for:\n"
        + "\n".join(f"- {line}" for line in lines)
        + "\n\nUse this only to fill `profile_flags` and to choose `tags`. List in "
        "`profile_flags` any ingredient in this recipe that touches an allergy, breaks "
        "the diet, or is a known dislike, one short line each, for example "
        "'contains walnuts (allergy)'. Never change, remove or substitute an "
        "ingredient because of the profile: the recipe must stay what the source said.\n"
    )


def extract_system_prompt(profile: Profile | None) -> str:
    return EXTRACT_SYSTEM + profile_block(profile)


def build_extract_input(
    *,
    source_kind: str,
    url: str | None,
    title: str | None,
    author: str | None,
    caption: str | None,
    page_text: str | None,
    transcript: str | None,
    onscreen_text: str | None,
    photo_text: str | None,
    extra_note: str | None = None,
    limit_per_part: int = 24000,
) -> str:
    """Assemble the labelled context. Labels matter: the model is told what each part is."""
    parts: list[str] = [f"SOURCE TYPE: {source_kind}"]
    if url:
        parts.append(f"SOURCE URL: {url}")
    if author:
        parts.append(f"AUTHOR: {author}")
    if title:
        parts.append(f"SOURCE TITLE: {title}")

    def section(label: str, body: str | None, note: str = "") -> None:
        if body and body.strip():
            head = f"--- {label}{(' ' + note) if note else ''} ---"
            parts.append(f"{head}\n{body.strip()[:limit_per_part]}")

    section("CAPTION / POST TEXT", caption)
    section("PAGE TEXT", page_text)
    section(
        "SPOKEN TRANSCRIPT",
        transcript,
        "(automatic speech recognition; quantities may be misheard)",
    )
    section(
        "ON-SCREEN TEXT FROM VIDEO FRAMES",
        onscreen_text,
        "(read off the video; more reliable than the transcript for numbers)",
    )
    section("TEXT READ FROM PHOTOS", photo_text)
    if extra_note:
        parts.append(f"--- NOTE FROM THE COOK ---\n{extra_note.strip()[:4000]}")

    available = [
        name
        for name, body in (
            ("caption", caption),
            ("page text", page_text),
            ("transcript", transcript),
            ("on-screen text", onscreen_text),
            ("photo text", photo_text),
        )
        if body and body.strip()
    ]
    parts.append(
        "--- WHAT YOU HAVE ---\n"
        + (", ".join(available) if available else "nothing usable")
        + ". Anything not present in these parts is unknown to you."
    )
    return "\n\n".join(parts)


SUGGESTION_SYSTEM = """\
You maintain a cook's taste profile from evidence about what they actually do.

You are given the current profile and a list of observations: edits they made to
extracted recipes, ratings, and notes they wrote while cooking.

Propose at most three changes to the profile. A proposal must be supported by at
least two separate observations, and must not repeat something already in the
profile. Prefer durable preferences ("prefers less sugar in bakes") over one-offs
("used spelt flour once"). If the evidence does not support a change, return an
empty list. Each proposal names the profile field it belongs to: diet, allergies,
dislikes, likes, pantry_staples or notes.
"""
