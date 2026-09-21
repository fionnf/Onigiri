"""Media storage: S3-compatible object storage in production, local disk in dev."""

from __future__ import annotations

import asyncio
import hashlib
import mimetypes
import os
import uuid
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from onigiri.config import settings


@dataclass
class StoredObject:
    key: str
    bytes: int
    content_type: str


@lru_cache
def _s3_client():  # pragma: no cover - requires credentials
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        region_name=settings.s3_region,
        aws_access_key_id=settings.s3_access_key_id,
        aws_secret_access_key=settings.s3_secret_access_key,
        config=Config(signature_version="s3v4", retries={"max_attempts": 3}),
    )


def build_key(user_id: uuid.UUID, filename: str, prefix: str = "media") -> str:
    ext = Path(filename).suffix.lower()[:12]
    digest = hashlib.sha256(f"{uuid.uuid4()}{filename}".encode()).hexdigest()[:24]
    return f"{prefix}/{user_id}/{digest}{ext}"


def guess_content_type(filename: str, fallback: str = "application/octet-stream") -> str:
    return mimetypes.guess_type(filename)[0] or fallback


def _local_path(key: str) -> Path:
    path = Path(settings.media_dir) / key
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _put_sync(key: str, data: bytes, content_type: str) -> StoredObject:
    if settings.use_s3:
        _s3_client().put_object(
            Bucket=settings.s3_bucket, Key=key, Body=data, ContentType=content_type
        )
    else:
        _local_path(key).write_bytes(data)
    return StoredObject(key=key, bytes=len(data), content_type=content_type)


async def put_bytes(key: str, data: bytes, content_type: str) -> StoredObject:
    return await asyncio.to_thread(_put_sync, key, data, content_type)


async def put_file(key: str, path: str | os.PathLike[str], content_type: str) -> StoredObject:
    data = await asyncio.to_thread(Path(path).read_bytes)
    return await put_bytes(key, data, content_type)


def _get_sync(key: str) -> bytes:
    if settings.use_s3:
        obj = _s3_client().get_object(Bucket=settings.s3_bucket, Key=key)
        return obj["Body"].read()
    return _local_path(key).read_bytes()


async def get_bytes(key: str) -> bytes:
    return await asyncio.to_thread(_get_sync, key)


def _delete_sync(key: str) -> None:
    if settings.use_s3:
        _s3_client().delete_object(Bucket=settings.s3_bucket, Key=key)
    else:
        p = _local_path(key)
        if p.exists():
            p.unlink()


async def delete(key: str) -> None:
    await asyncio.to_thread(_delete_sync, key)


def public_url(key: str) -> str | None:
    if settings.s3_public_base_url:
        return f"{settings.s3_public_base_url.rstrip('/')}/{key}"
    return None


def signed_url(key: str, expires_s: int = 3600) -> str | None:
    if not settings.use_s3:  # pragma: no cover
        return None
    return _s3_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.s3_bucket, "Key": key},
        ExpiresIn=expires_s,
    )
