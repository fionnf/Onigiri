"""OpenAI access: structured extraction, vision reading, transcription, embeddings.

All calls go through here so that model names, usage accounting and error handling
live in one place. The schema sanitiser turns a Pydantic model into a schema the
structured-outputs API accepts in strict mode.
"""

from __future__ import annotations

import asyncio
import base64
import copy
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from onigiri.config import settings

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    """Raised when the model cannot be reached or returns something unusable."""


class LLMNotConfigured(LLMError):
    pass


# Keywords the structured-outputs strict mode rejects.
_UNSUPPORTED_KEYS = {
    "default",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "multipleOf",
    "minLength",
    "maxLength",
    "pattern",
    "format",
    "minItems",
    "maxItems",
    "uniqueItems",
    "examples",
    "$comment",
    "contentEncoding",
    "contentMediaType",
    "minProperties",
    "maxProperties",
}


def strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Convert a Pydantic model into a strict JSON schema.

    Strict mode requires every property to be listed in `required` and every object
    to forbid extra properties. Optional fields stay expressible because Pydantic
    renders them as a union with null.
    """
    schema = copy.deepcopy(model.model_json_schema())

    def walk(node: Any) -> Any:
        if isinstance(node, list):
            return [walk(n) for n in node]
        if not isinstance(node, dict):
            return node
        node = {k: walk(v) for k, v in node.items() if k not in _UNSUPPORTED_KEYS}
        if node.get("type") == "object" or "properties" in node:
            props = node.get("properties", {})
            node["additionalProperties"] = False
            node["required"] = list(props.keys())
        return node

    return walk(schema)


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


_client: Any = None


def get_client() -> Any:
    global _client
    if _client is None:
        if not settings.openai_api_key:
            raise LLMNotConfigured(
                "OPENAI_API_KEY is not set. Add it to the environment to enable extraction."
            )
        from openai import AsyncOpenAI

        _client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            max_retries=3,
            timeout=180.0,
        )
    return _client


def reset_client() -> None:
    """Used by tests to drop a cached client."""
    global _client
    _client = None


def image_part(data: bytes, content_type: str = "image/jpeg") -> dict[str, Any]:
    b64 = base64.b64encode(data).decode()
    return {"type": "image_url", "image_url": {"url": f"data:{content_type};base64,{b64}"}}


def text_part(text: str) -> dict[str, Any]:
    return {"type": "text", "text": text}


async def structured(
    schema_model: type[T],
    system: str,
    content: str | list[dict[str, Any]],
    *,
    schema_name: str,
    model: str | None = None,
    usage: Usage | None = None,
    temperature: float | None = 0.1,
) -> T:
    """Call the model and validate the reply against `schema_model`."""
    client = get_client()
    model_name = model or settings.openai_extract_model
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": content},
    ]
    kwargs: dict[str, Any] = {
        "model": model_name,
        "messages": messages,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": schema_name,
                "strict": True,
                "schema": strict_schema(schema_model),
            },
        },
    }
    if temperature is not None:
        kwargs["temperature"] = temperature

    try:
        resp = await client.chat.completions.create(**kwargs)
    except Exception as exc:
        msg = str(exc)
        if "temperature" in msg and temperature is not None:
            kwargs.pop("temperature")
            resp = await client.chat.completions.create(**kwargs)
        else:
            raise LLMError(f"{model_name} call failed: {exc}") from exc

    if usage is not None and getattr(resp, "usage", None):
        usage.input_tokens += resp.usage.prompt_tokens or 0
        usage.output_tokens += resp.usage.completion_tokens or 0
        usage.add_call(schema_name)

    choice = resp.choices[0]
    if getattr(choice.message, "refusal", None):
        raise LLMError(f"Model refused: {choice.message.refusal}")
    raw = choice.message.content or ""
    try:
        return schema_model.model_validate_json(raw)
    except ValidationError as exc:
        raise LLMError(f"Model returned data that did not match the schema: {exc}") from exc


async def transcribe_file(
    path: str | Path, *, language: str | None = None, usage: Usage | None = None
) -> dict[str, Any]:
    """Transcribe an audio file. Returns {'text', 'segments', 'language'}."""
    client = get_client()
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


async def embed(text: str, *, usage: Usage | None = None) -> list[float]:
    client = get_client()
    trimmed = text[:8000]
    resp = await client.embeddings.create(model=settings.openai_embed_model, input=trimmed)
    if usage is not None:
        usage.input_tokens += getattr(resp.usage, "prompt_tokens", 0) or 0
        usage.add_call("embed")
    return list(resp.data[0].embedding)


async def embed_many(texts: list[str], *, usage: Usage | None = None) -> list[list[float]]:
    if not texts:
        return []
    client = get_client()
    resp = await client.embeddings.create(
        model=settings.openai_embed_model, input=[t[:8000] for t in texts]
    )
    if usage is not None:
        usage.input_tokens += getattr(resp.usage, "prompt_tokens", 0) or 0
        usage.add_call("embed")
    return [list(d.embedding) for d in resp.data]


async def gather_limited(coros: list[Any], limit: int = 4) -> list[Any]:
    """Run coroutines with bounded concurrency, preserving order."""
    sem = asyncio.Semaphore(limit)

    async def run(c: Any) -> Any:
        async with sem:
            return await c

    return await asyncio.gather(*(run(c) for c in coros))
