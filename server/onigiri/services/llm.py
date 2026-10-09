"""Model access.

Claude reads every recipe: structured extraction, photos, and text in video frames.
Claude has no speech-to-text or embedding endpoint, so those two stay on OpenAI and
are optional: without OPENAI_API_KEY a video is read from its caption and on-screen
text only, and search runs on full text and fuzzy matching without the semantic leg.
"""

from __future__ import annotations

import asyncio
import base64
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

import anthropic
from pydantic import BaseModel, ValidationError

from onigiri.config import settings

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# Server-side refusal fallback: if a safety classifier declines a request, the API
# re-runs it on the model Anthropic recommends for that category, in the same call.
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLMError(RuntimeError):
    """The model could not be reached or returned something unusable."""


class LLMNotConfigured(LLMError):
    """A key the requested feature needs is missing."""


class LLMDeclined(LLMError):
    """The model, and its fallback, declined the request."""


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    audio_seconds: float = 0.0
    calls: dict[str, int] = field(default_factory=dict)

    def add_call(self, name: str) -> None:
        self.calls[name] = self.calls.get(name, 0) + 1

    def merge(self, other: Usage) -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.audio_seconds += other.audio_seconds
        for k, v in other.calls.items():
            self.calls[k] = self.calls.get(k, 0) + v

    def as_dict(self) -> dict[str, Any]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "audio_seconds": round(self.audio_seconds, 1),
            "calls": self.calls,
        }


# --------------------------------------------------------------------------- clients

_claude: anthropic.AsyncAnthropic | None = None
_openai: Any = None


def get_claude() -> anthropic.AsyncAnthropic:
    global _claude
    if _claude is None:
        if not settings.anthropic_api_key:
            raise LLMNotConfigured(
                "ANTHROPIC_API_KEY is not set. Add it to the environment to read recipes."
            )
        _claude = anthropic.AsyncAnthropic(
            api_key=settings.anthropic_api_key,
            max_retries=3,
            timeout=settings.anthropic_timeout_s,
        )
    return _claude


def get_openai() -> Any:
    global _openai
    if _openai is None:
        if not settings.openai_api_key:
            raise LLMNotConfigured("OPENAI_API_KEY is not set.")
        from openai import AsyncOpenAI

        _openai = AsyncOpenAI(api_key=settings.openai_api_key, max_retries=3, timeout=180.0)
    return _openai


def reset_clients() -> None:
    """Drop cached clients, so a changed key takes effect. Used by tests."""
    global _claude, _openai, _embed_paused_until
    _claude = None
    _openai = None
    _embed_paused_until = 0.0


def speech_available() -> bool:
    return bool(settings.openai_api_key)


# --------------------------------------------------------------------------- content


def image_part(data: bytes, content_type: str = "image/jpeg") -> dict[str, Any]:
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": content_type,
            "data": base64.standard_b64encode(data).decode("ascii"),
        },
    }


def text_part(text: str) -> dict[str, Any]:
    return {"type": "text", "text": text}


# --------------------------------------------------------------------------- Claude


async def structured(
    schema_model: type[T],
    system: str,
    content: str | list[dict[str, Any]],
    *,
    schema_name: str,
    effort: str | None = None,
    usage: Usage | None = None,
    max_tokens: int = 16000,
) -> T:
    """Ask Claude for one object matching `schema_model`, validated on the way back."""
    client = get_claude()
    try:
        response = await client.beta.messages.parse(
            model=settings.anthropic_model,
            max_tokens=max_tokens,
            betas=[FALLBACK_BETA],
            fallbacks="default",
            system=system,
            output_config={"effort": effort or settings.anthropic_effort},
            output_format=schema_model,
            messages=[{"role": "user", "content": content}],
        )
    except anthropic.AuthenticationError as exc:
        raise LLMNotConfigured(
            "ANTHROPIC_API_KEY was rejected. Check the key, or create a new one."
        ) from exc
    except anthropic.PermissionDeniedError as exc:
        raise LLMError(f"This API key cannot use {settings.anthropic_model}.") from exc
    except anthropic.RateLimitError as exc:
        raise LLMError("Claude is rate limiting this key. Try again in a minute.") from exc
    except anthropic.BadRequestError as exc:
        raise LLMError(f"Claude rejected the request: {exc.message}") from exc
    except anthropic.APIStatusError as exc:
        raise LLMError(f"Claude returned an error ({exc.status_code}).") from exc
    except anthropic.APIConnectionError as exc:
        raise LLMError("Could not reach Claude. Check the network.") from exc
    except ValidationError as exc:
        raise LLMError(f"Claude's answer did not match the {schema_name} shape: {exc}") from exc

    if usage is not None:
        usage.input_tokens += response.usage.input_tokens or 0
        usage.output_tokens += response.usage.output_tokens or 0
        usage.add_call(schema_name)

    if response.stop_reason == "refusal":
        details = response.stop_details
        category = getattr(details, "category", None) if details else None
        raise LLMDeclined(
            "Claude declined to read this source"
            + (f" ({category})" if category else "")
            + ". Paste the recipe text instead."
        )
    if response.stop_reason == "max_tokens":
        raise LLMError("Claude ran out of room before finishing. Try a shorter source.")

    parsed = response.parsed_output
    if parsed is None:
        raise LLMError(f"Claude returned no {schema_name}.")
    log.info(
        "%s via %s: %s in, %s out",
        schema_name,
        response.model,
        response.usage.input_tokens,
        response.usage.output_tokens,
    )
    return parsed


# --------------------------------------------------------------------------- OpenAI


async def transcribe_file(
    path: str | Path, *, language: str | None = None, usage: Usage | None = None
) -> dict[str, Any]:
    """Transcribe audio with OpenAI. Returns {'text', 'segments', 'language', 'duration'}."""
    client = get_openai()
    p = Path(path)
    payload = await asyncio.to_thread(p.read_bytes)

    async def _call(response_format: str) -> Any:
        kwargs: dict[str, Any] = {
            "model": settings.openai_stt_model,
            "file": (p.name, payload, "audio/mpeg"),
            "response_format": response_format,
        }
        if language:
            kwargs["language"] = language
        return await client.audio.transcriptions.create(**kwargs)

    try:
        result = await _call("verbose_json")
    except Exception:
        try:
            result = await _call("json")
        except Exception as exc:
            raise LLMError(f"Transcription failed: {exc}") from exc

    data = result.model_dump() if hasattr(result, "model_dump") else dict(result)
    segments = [
        {
            "start": round(float(s.get("start", 0.0)), 2),
            "end": round(float(s.get("end", 0.0)), 2),
            "text": (s.get("text") or "").strip(),
        }
        for s in (data.get("segments") or [])
    ]
    if usage is not None:
        usage.audio_seconds += float(data.get("duration") or 0.0)
        usage.add_call("transcribe")
    return {
        "text": (data.get("text") or "").strip(),
        "segments": segments,
        "language": data.get("language"),
        "duration": data.get("duration"),
    }


# After a failed embedding, skip the semantic leg for a while instead of making every
# search wait on a provider that is down or a key that is wrong.
EMBED_COOLDOWN_S = 300.0
_embed_paused_until = 0.0


async def embed(text: str, *, usage: Usage | None = None, fast: bool = False) -> list[float]:
    """Embedding for semantic search. Optional: callers treat LLMError as 'skip it'.

    `fast` is for the search box: one short attempt, so a slow provider never holds up
    results that full-text search can already give.
    """
    global _embed_paused_until
    client = get_openai()
    loop = asyncio.get_running_loop()
    if loop.time() < _embed_paused_until:
        raise LLMError("Semantic search is paused after a recent failure.")
    if fast:
        client = client.with_options(timeout=4.0, max_retries=0)
    try:
        resp = await client.embeddings.create(model=settings.openai_embed_model, input=text[:8000])
    except Exception as exc:
        _embed_paused_until = loop.time() + EMBED_COOLDOWN_S
        raise LLMError(f"Embedding failed: {exc}") from exc
    if usage is not None:
        usage.input_tokens += getattr(resp.usage, "prompt_tokens", 0) or 0
        usage.add_call("embed")
    return list(resp.data[0].embedding)


# --------------------------------------------------------------------------- helpers


async def gather_limited(coros: list[Any], limit: int = 4) -> list[Any]:
    """Run coroutines with bounded concurrency, preserving order."""
    sem = asyncio.Semaphore(limit)

    async def run(c: Any) -> Any:
        async with sem:
            return await c

    return await asyncio.gather(*(run(c) for c in coros))
