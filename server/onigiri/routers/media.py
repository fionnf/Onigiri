"""Serving stored media. Everything is private, so nothing is public by URL."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from onigiri.config import settings
from onigiri.db import get_db
from onigiri.models import Media, Source, User
from onigiri.security import current_user
from onigiri.services import storage

router = APIRouter(prefix="/api/media", tags=["media"])


@router.get("/{media_id}")
async def get_media(
    media_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
) -> Response:
    media = await db.scalar(
        select(Media)
        .join(Source, Source.id == Media.source_id)
        .where(Media.id == media_id, Source.user_id == user.id)
    )
    if media is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such file")

    if settings.use_s3:
        url = storage.signed_url(media.storage_key)
        if url:
            return RedirectResponse(url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)

    try:
        data = await storage.get_bytes(media.storage_key)
    except FileNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That file is gone") from exc

    return Response(
        content=data,
        media_type=media.content_type or "application/octet-stream",
        headers={"Cache-Control": "private, max-age=86400"},
    )
