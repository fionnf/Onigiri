"""The ingest pipeline: from a shared link, photo or note to a stored recipe.

Every stage records what it did on the job, so the owner can see where a capture is
and why it stopped. Nothing here raises past the top: a failure becomes either
`needs_input` (the owner can rescue it by pasting the caption or uploading media) or
`failed` with the reason written down.
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from onigiri.config import settings
from onigiri.db import session_scope
from onigiri.models import (
    IngestJob,
    JobStatus,
    Media,
    MediaKind,
    Profile,
    Recipe,
    Source,
    SourceKind,
    User,
)
from onigiri.pipeline import media as mediautil
from onigiri.pipeline import vision
from onigiri.pipeline.detect import detect_kind
from onigiri.pipeline.extract import apply_extracted, reindex, run_extraction
from onigiri.pipeline.fetch_instagram import InstagramUnavailable, fetch_instagram
from onigiri.pipeline.fetch_video import (
    VideoUnavailable,
    download_url_to_file,
    fetch_video,
)
from onigiri.pipeline.fetch_web import fetch_web
from onigiri.services import llm, storage

log = logging.getLogger(__name__)

MAX_IMAGES_FOR_VISION = 8


class NeedsInput(Exception):
    """The owner has to supply something before this capture can continue."""


@dataclass
class StageWriter:
    db: AsyncSession
    job: IngestJob

    async def stage(self, status: JobStatus, note: str) -> None:
        self.job.status = status
        entry = {
            "stage": status.value,
            "note": note,
            "at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        self.job.stage_log = [*(self.job.stage_log or []), entry]
        await self.db.flush()
        await self.db.commit()
        log.info("job %s -> %s: %s", self.job.id, status.value, note)

    async def note(self, note: str) -> None:
        await self.stage(self.job.status, note)


async def _load_job(db: AsyncSession, job_id: uuid.UUID) -> tuple[IngestJob, User, Profile | None]:
    job = await db.scalar(select(IngestJob).where(IngestJob.id == job_id))
    if job is None:
        raise LookupError(f"job {job_id} not found")
    user = await db.scalar(select(User).where(User.id == job.user_id))
    if user is None:
        raise LookupError("job has no owner")
    profile = await db.scalar(select(Profile).where(Profile.user_id == user.id))
    return job, user, profile


async def _ensure_source(
    db: AsyncSession, job: IngestJob, kind: SourceKind, url: str | None
) -> Source:
    if job.source_id:
        source = await db.scalar(select(Source).where(Source.id == job.source_id))
        if source is not None:
            source.kind = kind
            source.url = source.url or url
            return source
    source = Source(user_id=job.user_id, kind=kind, url=url)
    db.add(source)
    await db.flush()
    job.source_id = source.id
    await db.flush()
    return source


async def _store_media(
    db: AsyncSession,
    source: Source,
    *,
    kind: MediaKind,
    data: bytes,
    filename: str,
    content_type: str,
    order_idx: int,
) -> Media:
    key = storage.build_key(source.user_id, filename)
    stored = await storage.put_bytes(key, data, content_type)
    width = height = None
    if kind in (MediaKind.image, MediaKind.thumbnail, MediaKind.keyframe):
        width, height = mediautil.image_dimensions(data)
    m = Media(
        source_id=source.id,
        kind=kind,
        storage_key=stored.key,
        content_type=stored.content_type,
        bytes=stored.bytes,
        width=width,
        height=height,
        order_idx=order_idx,
    )
    db.add(m)
    await db.flush()
    return m


async def _existing_media(db: AsyncSession, source: Source) -> list[Media]:
    return list(
        (
            await db.scalars(
                select(Media)
                .where(Media.source_id == source.id)
                .order_by(Media.order_idx, Media.created_at)
            )
        ).all()
    )


# --------------------------------------------------------------------------- fetch stages


async def _fetch_instagram_stage(
    db: AsyncSession, sw: StageWriter, source: Source, url: str, tmp: Path
) -> None:
    try:
        post = await fetch_instagram(url)
    except InstagramUnavailable as exc:
        if settings.ytdlp_instagram_fallback:
            await sw.note("Apify failed; trying the open downloader as a fallback.")
            try:
                await _fetch_short_video_stage(db, sw, source, url, tmp)
                return
            except (VideoUnavailable, NeedsInput):
                pass
        raise NeedsInput(str(exc)) from exc

    source.caption = post.caption
    source.author = post.author
    source.title = post.title
    source.url = post.url
    source.raw_payload = {
        k: v for k, v in post.raw.items() if k in {"id", "shortCode", "type", "timestamp", "url"}
    }
    if post.hashtags:
        source.caption = (source.caption or "") + "\n" + " ".join(f"#{h}" for h in post.hashtags)

    order = len(await _existing_media(db, source))
    for i, video_url in enumerate(post.video_urls[:2]):
        try:
            dest = await download_url_to_file(video_url, tmp / f"ig_video_{i}.mp4")
        except Exception as exc:
            await sw.note(f"Could not download the video file: {exc}")
            continue
        await _store_media(
            db,
            source,
            kind=MediaKind.video,
            data=dest.read_bytes(),
            filename=dest.name,
            content_type="video/mp4",
            order_idx=order,
        )
        order += 1
    for i, image_url in enumerate(post.image_urls[:MAX_IMAGES_FOR_VISION]):
        try:
            dest = await download_url_to_file(image_url, tmp / f"ig_image_{i}.jpg")
        except Exception as exc:
            await sw.note(f"Could not download an image: {exc}")
            continue
        await _store_media(
            db,
            source,
            kind=MediaKind.image,
            data=dest.read_bytes(),
            filename=dest.name,
            content_type="image/jpeg",
            order_idx=order,
        )
        order += 1

    caption_len = len(source.caption or "")
    await sw.note(
        f"Fetched the post: {caption_len} characters of caption, "
        f"{len(post.video_urls)} video(s), {len(post.image_urls)} image(s)."
    )
    if not source.caption and not post.has_media:
        raise NeedsInput("That post had no caption and no media we could read.")


async def _fetch_short_video_stage(
    db: AsyncSession, sw: StageWriter, source: Source, url: str, tmp: Path
) -> None:
    result = await fetch_video(url, tmp / "dl")
    source.url = result.url
    source.title = result.title
    source.author = result.author
    source.caption = result.description
    source.raw_payload = result.raw
    if result.video_path and await asyncio.to_thread(result.video_path.exists):
        order = len(await _existing_media(db, source))
        await _store_media(
            db,
            source,
            kind=MediaKind.video,
            data=await asyncio.to_thread(result.video_path.read_bytes),
            filename=result.video_path.name,
            content_type="video/mp4",
            order_idx=order,
        )
    await sw.note(
        f"Downloaded '{result.title or 'the video'}'"
        + (f", {int(result.duration)}s long" if result.duration else "")
        + "."
    )


async def _fetch_web_stage(sw: StageWriter, source: Source, url: str) -> object | None:
    result = await fetch_web(url)
    source.url = result.url
    source.title = result.title
    source.author = result.author
    source.page_text = result.page_text
    source.raw_payload = result.raw_payload or None
    if result.structured:
        await sw.note(f"'{result.title or url}' publishes a structured recipe; using it directly.")
    else:
        await sw.note(
            f"Read {len(result.page_text or '')} characters from '{result.title or url}'."
        )
    return result


# --------------------------------------------------------------------------- media stages


async def _transcribe_stage(
    db: AsyncSession, sw: StageWriter, source: Source, tmp: Path, usage: llm.Usage
) -> None:
    videos = [m for m in await _existing_media(db, source) if m.kind == MediaKind.video]
    if not videos:
        return
    if not mediautil.ffmpeg_available():
        await sw.note("ffmpeg is not installed here, so the video audio was not transcribed.")
        return

    await sw.stage(JobStatus.transcribing, "Listening to the video.")
    video = videos[0]
    local = tmp / f"video_{video.id}.mp4"
    await asyncio.to_thread(local.write_bytes, await storage.get_bytes(video.storage_key))

    try:
        info = await mediautil.probe(local)
    except Exception as exc:
        await sw.note(f"Could not inspect the video: {exc}")
        return
    video.duration_s = info.duration
    video.width, video.height = info.width, info.height
    await db.flush()

    if not info.has_audio:
        await sw.note("That video has no audio track.")
        return

    audio = await mediautil.extract_audio(local, tmp / "audio.mp3")
    if audio is None:
        await sw.note("Could not extract the audio track.")
        return

    chunks = [audio]
    if info.duration and info.duration > settings.transcribe_chunk_seconds:
        chunks = await mediautil.split_audio(
            audio, settings.transcribe_chunk_seconds, tmp / "chunks"
        )
        await sw.note(f"Split {int(info.duration)}s of audio into {len(chunks)} parts.")

    texts: list[str] = []
    segments: list[dict] = []
    offset = 0.0
    language: str | None = None
    for chunk in chunks:
        try:
            result = await llm.transcribe_file(chunk, usage=usage)
        except llm.LLMError as exc:
            await sw.note(f"Transcription failed: {exc}")
            break
        texts.append(result["text"])
        language = language or result.get("language")
        for seg in result["segments"]:
            segments.append(
                {
                    "start": round(seg["start"] + offset, 2),
                    "end": round(seg["end"] + offset, 2),
                    "text": seg["text"],
                }
            )
        offset += float(result.get("duration") or settings.transcribe_chunk_seconds)

    full = "\n".join(t for t in texts if t).strip()
    source.transcript = {"text": full, "segments": segments, "language": language}
    source.language = source.language or language
    await db.flush()
    await sw.note(
        f"Transcribed {len(full)} characters of speech."
        if full
        else "The video had no speech we could make out."
    )


async def _read_frames_stage(
    db: AsyncSession, sw: StageWriter, source: Source, tmp: Path, usage: llm.Usage
) -> Path | None:
    """Read text burned into the video and return the best frame for a hero image."""
    videos = [m for m in await _existing_media(db, source) if m.kind == MediaKind.video]
    if not videos or not mediautil.ffmpeg_available():
        return None

    await sw.stage(JobStatus.reading, "Reading the text on screen.")
    video = videos[0]
    local = tmp / f"video_{video.id}.mp4"
    if not await asyncio.to_thread(local.exists):
        await asyncio.to_thread(local.write_bytes, await storage.get_bytes(video.storage_key))

    frames = await mediautil.extract_keyframes(local, tmp / "frames")
    if not frames:
        await sw.note("No frames could be sampled from the video.")
        return None

    cover = await asyncio.to_thread(mediautil.pick_cover_frame, frames)
    cover_path = cover.path if cover else None
    try:
        text = await vision.read_keyframes([f.path.read_bytes() for f in frames], usage=usage)
    except llm.LLMError as exc:
        await sw.note(f"Could not read the on-screen text: {exc}")
        return cover_path

    source.onscreen_text = text or None
    await db.flush()
    await sw.note(
        f"Sampled {len(frames)} distinct frames and read "
        f"{len(text.splitlines()) if text else 0} lines of on-screen text."
    )
    return cover_path


async def _read_photos_stage(
    db: AsyncSession, sw: StageWriter, source: Source, usage: llm.Usage
) -> None:
    images = [m for m in await _existing_media(db, source) if m.kind == MediaKind.image]
    if not images:
        return

    await sw.stage(JobStatus.reading, f"Reading {len(images)} photo(s).")
    payloads = []
    for m in images[:MAX_IMAGES_FOR_VISION]:
        payloads.append(await storage.get_bytes(m.storage_key))

    result = await vision.read_photos(payloads, usage=usage)
    if not result.has_recipe_text and not result.text.strip():
        if source.kind == SourceKind.photo:
            raise NeedsInput(
                "There is no readable recipe text in that photo. "
                "Add a photo of the recipe itself, or type the recipe in."
            )
        await sw.note("The images carried no readable text.")
        return

    source.photo_text = result.text
    if result.low_confidence_lines:
        source.photo_text += (
            "\n\n[Lines that were hard to read: "
            + "; ".join(result.low_confidence_lines[:20])
            + "]"
        )
    await db.flush()
    await sw.note(
        f"Read {len(result.text)} characters"
        + (" of handwriting" if result.is_handwritten else "")
        + (
            f"; {len(result.low_confidence_lines)} line(s) need checking."
            if result.low_confidence_lines
            else "."
        )
    )


async def _hero_stage(
    db: AsyncSession, source: Source, recipe: Recipe, fallback_frame: Path | None
) -> None:
    """Pick and store a thumbnail so the library is not a wall of text."""
    existing = await _existing_media(db, source)
    if recipe.hero_media_id:
        return
    thumb = next((m for m in existing if m.kind == MediaKind.thumbnail), None)
    if thumb:
        recipe.hero_media_id = thumb.id
        return

    data: bytes | None = None
    image = next((m for m in existing if m.kind == MediaKind.image), None)
    if image:
        data = await storage.get_bytes(image.storage_key)
    elif fallback_frame and await asyncio.to_thread(fallback_frame.exists):
        data = await asyncio.to_thread(fallback_frame.read_bytes)

    if not data:
        return
    try:
        jpeg, width, height = mediautil.make_thumbnail(data)
    except Exception as exc:
        log.info("thumbnail failed: %s", exc)
        return
    m = await _store_media(
        db,
        source,
        kind=MediaKind.thumbnail,
        data=jpeg,
        filename="hero.jpg",
        content_type="image/jpeg",
        order_idx=len(existing),
    )
    m.width, m.height = width, height
    recipe.hero_media_id = m.id
    await db.flush()


# --------------------------------------------------------------------------- entry point


async def run_job(job_id: uuid.UUID) -> None:
    """Run one capture from start to finish. Never raises to the caller."""
    async with session_scope() as db:
        try:
            job, user, profile = await _load_job(db, job_id)
        except LookupError as exc:
            log.error("cannot run job %s: %s", job_id, exc)
            return

        sw = StageWriter(db, job)
        usage = llm.Usage()
        job.error = None
        job.needs_input_reason = None

        with tempfile.TemporaryDirectory(prefix="onigiri-") as tmpname:
            tmp = Path(tmpname)
            try:
                await _pipeline(db, sw, job, user, profile, tmp, usage)
            except NeedsInput as exc:
                job.status = JobStatus.needs_input
                job.needs_input_reason = str(exc)
                job.usage = usage.as_dict()
                await sw.stage(JobStatus.needs_input, str(exc))
            except llm.LLMNotConfigured as exc:
                job.status = JobStatus.failed
                job.error = str(exc)
                job.usage = usage.as_dict()
                await sw.stage(JobStatus.failed, str(exc))
            except Exception as exc:
                log.exception("job %s failed", job_id)
                job.status = JobStatus.failed
                job.error = f"{type(exc).__name__}: {exc}"[:2000]
                job.usage = usage.as_dict()
                await sw.stage(JobStatus.failed, job.error)


async def _pipeline(
    db: AsyncSession,
    sw: StageWriter,
    job: IngestJob,
    user: User,
    profile: Profile | None,
    tmp: Path,
    usage: llm.Usage,
) -> None:
    existing_source = (
        await db.scalar(select(Source).where(Source.id == job.source_id)) if job.source_id else None
    )
    file_kinds: list[str] = []
    if existing_source:
        for m in await _existing_media(db, existing_source):
            if m.kind == MediaKind.video:
                file_kinds.append("video")
            elif m.kind == MediaKind.image:
                file_kinds.append("image")

    kind, url = detect_kind(url=job.input_url, text=job.input_text, file_kinds=file_kinds)
    source = await _ensure_source(db, job, kind, url)

    # Anything the owner typed that is not just the link they shared.
    supplied_note = (job.input_text or "").strip()
    if supplied_note and supplied_note == (url or "").strip():
        supplied_note = ""

    # A capture that already asked for help must not go back to the service that
    # could not serve it; it works with whatever the owner supplied instead.
    was_rescued = any(
        entry.get("stage") == JobStatus.needs_input.value for entry in (job.stage_log or [])
    )
    have_content = bool(
        source.caption
        or source.page_text
        or source.photo_text
        or source.transcript_text
        or file_kinds
    )
    skip_remote_fetch = was_rescued and (have_content or supplied_note)

    await sw.stage(JobStatus.fetching, f"Starting a {kind.value} capture.")

    scraped = None
    if skip_remote_fetch:
        await sw.note("Using what you supplied instead of fetching again.")
    elif kind == SourceKind.instagram and url:
        await _fetch_instagram_stage(db, sw, source, url, tmp)
    elif kind == SourceKind.short_video and url:
        try:
            await _fetch_short_video_stage(db, sw, source, url, tmp)
        except VideoUnavailable as exc:
            raise NeedsInput(f"{exc} Paste the caption or upload the video and try again.") from exc
    elif kind == SourceKind.web and url:
        try:
            scraped = await _fetch_web_stage(sw, source, url)
        except Exception as exc:
            raise NeedsInput(
                f"Could not read that page ({exc}). Paste the recipe text instead."
            ) from exc
    else:
        await sw.note("Using what you supplied directly.")

    if supplied_note and supplied_note not in (source.caption or ""):
        source.caption = ((source.caption or "") + "\n\n" + supplied_note).strip()
    await db.flush()
    await db.commit()

    # --- media understanding
    await _transcribe_stage(db, sw, source, tmp, usage)
    hero_frame = await _read_frames_stage(db, sw, source, tmp, usage)
    if source.kind in (SourceKind.photo, SourceKind.instagram) or (
        source.kind == SourceKind.text and not source.caption
    ):
        await _read_photos_stage(db, sw, source, usage)
    await db.commit()

    # --- extraction
    await sw.stage(JobStatus.extracting, "Writing the recipe out.")
    structured = getattr(scraped, "structured", None)
    if structured is None:
        have_anything = any(
            [
                source.caption,
                source.page_text,
                source.transcript_text,
                source.onscreen_text,
                source.photo_text,
            ]
        )
        if not have_anything:
            raise NeedsInput(
                "Nothing readable came back from that source. "
                "Paste the caption or the recipe text, or upload a photo."
            )
        structured = await run_extraction(
            source=source, profile=profile, extra_note=None, usage=usage
        )

    recipe = None
    if job.recipe_id:
        recipe = await db.scalar(select(Recipe).where(Recipe.id == job.recipe_id))
    recipe = await apply_extracted(
        db, user=user, source=source, extracted=structured, recipe=recipe
    )
    job.recipe_id = recipe.id

    await _hero_stage(db, source, recipe, hero_frame)
    await db.commit()

    await reindex(db, recipe, usage=usage)
    job.usage = usage.as_dict()
    await db.flush()

    summary = f"Saved '{recipe.title}'"
    if recipe.status.value == "needs_review":
        summary += " for review"
    await sw.stage(JobStatus.done, summary + ".")


async def run_job_safely(job_id: uuid.UUID) -> None:
    """Wrapper used by the inline backend so a crash cannot take the request down."""
    try:
        await run_job(job_id)
    except Exception:
        log.exception("unhandled error running job %s", job_id)


def run_job_blocking(job_id: uuid.UUID) -> None:  # pragma: no cover - worker entry
    asyncio.run(run_job(job_id))
