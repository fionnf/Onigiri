"""Capture: start a job, feed it what it asked for, and watch it run."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import StreamingResponse
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from onigiri.config import settings
from onigiri.db import SessionLocal, get_db
from onigiri.models import IngestJob, JobStatus, Media, MediaKind, Source, SourceKind, User
from onigiri.pipeline.detect import classify_file, detect_kind
from onigiri.schemas import IngestRequest, JobInput, JobOut
from onigiri.security import current_user
from onigiri.services import storage
from onigiri.services.jobs import JobCapReached, check_monthly_cap, enqueue

router = APIRouter(prefix="/api", tags=["ingest"])

ACTIVE_STATUSES = {
    JobStatus.queued,
    JobStatus.fetching,
    JobStatus.transcribing,
    JobStatus.reading,
    JobStatus.extracting,
}


async def _create_job(
    db: AsyncSession,
    user: User,
    *,
    url: str | None,
    text: str | None,
    uploads: list[UploadFile] | None = None,
) -> IngestJob:
    try:
        await check_monthly_cap(db, user.id)
    except JobCapReached as exc:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(exc)) from exc

    url = (url or "").strip() or None
    text = (text or "").strip() or None
    uploads = uploads or []
    if not url and not text and not uploads:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Share a link, paste some text, or add a photo.",
        )

    job = IngestJob(user_id=user.id, input_url=url, input_text=text)
    db.add(job)
    await db.flush()

    if uploads:
        kinds = [classify_file(f.filename or "file", f.content_type) for f in uploads]
        if all(k == "other" for k in kinds):
            raise HTTPException(
                status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                "Those files are not images or videos.",
            )
        source_kind, detected_url = detect_kind(url=url, text=text, file_kinds=kinds)
        source = Source(user_id=user.id, kind=source_kind, url=detected_url)
        db.add(source)
        await db.flush()
        job.source_id = source.id

        limit = settings.max_upload_mb * 1024 * 1024
        order = 0
        for upload, kind in zip(uploads, kinds, strict=True):
            if kind == "other":
                continue
            data = await upload.read()
            if len(data) > limit:
                raise HTTPException(
                    status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    f"{upload.filename} is larger than {settings.max_upload_mb} MB.",
                )
            filename = upload.filename or f"upload-{order}"
            key = storage.build_key(user.id, filename)
            content_type = upload.content_type or storage.guess_content_type(filename)
            stored = await storage.put_bytes(key, data, content_type)
            db.add(
                Media(
                    source_id=source.id,
                    kind=MediaKind.image if kind == "image" else MediaKind.video,
                    storage_key=stored.key,
                    content_type=content_type,
                    bytes=stored.bytes,
                    order_idx=order,
                )
            )
            order += 1
        await db.flush()

    await db.commit()
    await enqueue(job.id)
    return job


@router.post("/ingest", response_model=JobOut, status_code=status.HTTP_202_ACCEPTED)
async def ingest(
    body: IngestRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
) -> IngestJob:
    return await _create_job(db, user, url=body.url, text=body.text)


@router.post("/ingest/upload", response_model=JobOut, status_code=status.HTTP_202_ACCEPTED)
async def ingest_upload(
    files: Annotated[list[UploadFile] | None, File()] = None,
    url: Annotated[str | None, Form()] = None,
    text: Annotated[str | None, Form()] = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
) -> IngestJob:
    return await _create_job(db, user, url=url, text=text, uploads=files or [])


@router.get("/jobs", response_model=list[JobOut])
async def list_jobs(
    limit: int = 20,
    active_only: bool = False,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
) -> list[IngestJob]:
    stmt = select(IngestJob).where(IngestJob.user_id == user.id)
    if active_only:
        stmt = stmt.where(IngestJob.status.in_(ACTIVE_STATUSES | {JobStatus.needs_input}))
    stmt = stmt.order_by(desc(IngestJob.created_at)).limit(min(limit, 100))
    return list((await db.scalars(stmt)).all())


async def _get_job(db: AsyncSession, user: User, job_id: uuid.UUID) -> IngestJob:
    job = await db.scalar(
        select(IngestJob).where(IngestJob.id == job_id, IngestJob.user_id == user.id)
    )
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such capture")
    return job


@router.get("/jobs/{job_id}", response_model=JobOut)
async def get_job(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
) -> IngestJob:
    return await _get_job(db, user, job_id)


@router.post("/jobs/{job_id}/input", response_model=JobOut)
async def supply_input(
    job_id: uuid.UUID,
    body: JobInput,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
) -> IngestJob:
    """Paste the caption the scraper could not get, then run the capture again."""
    job = await _get_job(db, user, job_id)
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nothing was pasted.")

    if job.source_id:
        source = await db.scalar(select(Source).where(Source.id == job.source_id))
        if source is not None:
            source.caption = ((source.caption or "") + "\n\n" + text).strip()
    job.input_text = ((job.input_text or "") + "\n\n" + text).strip()
    job.status = JobStatus.queued
    job.needs_input_reason = None
    job.error = None
    await db.commit()
    await enqueue(job.id)
    return job


@router.post("/jobs/{job_id}/input/upload", response_model=JobOut)
async def supply_input_files(
    job_id: uuid.UUID,
    files: Annotated[list[UploadFile] | None, File()] = None,
    text: Annotated[str | None, Form()] = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
) -> IngestJob:
    """Upload the video or a screenshot for a capture that could not fetch it."""
    job = await _get_job(db, user, job_id)
    files = files or []
    if not files and not (text or "").strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nothing was supplied.")

    source = None
    if job.source_id:
        source = await db.scalar(select(Source).where(Source.id == job.source_id))
    if source is None:
        kinds = [classify_file(f.filename or "f", f.content_type) for f in files]
        kind, _ = detect_kind(url=job.input_url, text=job.input_text, file_kinds=kinds)
        source = Source(user_id=user.id, kind=kind, url=job.input_url)
        db.add(source)
        await db.flush()
        job.source_id = source.id

    existing = await db.scalar(
        select(Media).where(Media.source_id == source.id).order_by(desc(Media.order_idx))
    )
    order = (existing.order_idx + 1) if existing else 0
    limit = settings.max_upload_mb * 1024 * 1024

    for upload in files:
        kind = classify_file(upload.filename or "file", upload.content_type)
        if kind == "other":
            continue
        data = await upload.read()
        if len(data) > limit:
            raise HTTPException(
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                f"{upload.filename} is larger than {settings.max_upload_mb} MB.",
            )
        filename = upload.filename or f"upload-{order}"
        content_type = upload.content_type or storage.guess_content_type(filename)
        stored = await storage.put_bytes(storage.build_key(user.id, filename), data, content_type)
        db.add(
            Media(
                source_id=source.id,
                kind=MediaKind.image if kind == "image" else MediaKind.video,
                storage_key=stored.key,
                content_type=content_type,
                bytes=stored.bytes,
                order_idx=order,
            )
        )
        order += 1

    if (text or "").strip():
        source.caption = ((source.caption or "") + "\n\n" + text.strip()).strip()
        job.input_text = ((job.input_text or "") + "\n\n" + text.strip()).strip()

    if source.kind == SourceKind.text and files:
        kinds = [classify_file(f.filename or "f", f.content_type) for f in files]
        source.kind = SourceKind.video_file if "video" in kinds else SourceKind.photo

    job.status = JobStatus.queued
    job.needs_input_reason = None
    job.error = None
    await db.commit()
    await enqueue(job.id)
    return job


@router.post("/jobs/{job_id}/retry", response_model=JobOut)
async def retry_job(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
) -> IngestJob:
    job = await _get_job(db, user, job_id)
    if job.status in ACTIVE_STATUSES:
        raise HTTPException(status.HTTP_409_CONFLICT, "That capture is already running.")
    job.status = JobStatus.queued
    job.error = None
    job.needs_input_reason = None
    await db.commit()
    await enqueue(job.id)
    return job


@router.delete("/jobs/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_job(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
) -> None:
    job = await _get_job(db, user, job_id)
    await db.delete(job)


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


@router.get("/jobs/{job_id}/events")
async def job_events(
    job_id: uuid.UUID,
    request: Request,
    user: User = Depends(current_user),
) -> StreamingResponse:
    """Server-sent events so the capture screen shows progress as it happens."""

    async def stream() -> AsyncIterator[str]:
        last_signature: str | None = None
        idle_ticks = 0
        while True:
            if await request.is_disconnected():
                return
            async with SessionLocal() as db:
                job = await db.scalar(
                    select(IngestJob).where(IngestJob.id == job_id, IngestJob.user_id == user.id)
                )
                if job is None:
                    yield _sse("error", {"detail": "No such capture"})
                    return
                payload = JobOut.model_validate(job).model_dump(mode="json")
            signature = json.dumps(payload, sort_keys=True, default=str)
            if signature != last_signature:
                last_signature = signature
                idle_ticks = 0
                yield _sse("job", payload)
            else:
                idle_ticks += 1
                if idle_ticks % 20 == 0:
                    yield ": keep-alive\n\n"

            if payload["status"] in {"done", "failed", "needs_input"}:
                return
            if idle_ticks > 1200:  # ten minutes of no change
                yield _sse("error", {"detail": "Stopped watching after ten quiet minutes."})
                return
            await asyncio.sleep(0.5)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
