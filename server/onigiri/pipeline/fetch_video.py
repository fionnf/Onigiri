"""Download videos and their descriptions with yt-dlp (TikTok, YouTube, and friends)."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from onigiri.config import settings

log = logging.getLogger(__name__)


class VideoUnavailable(RuntimeError):
    pass


@dataclass
class VideoFetchResult:
    url: str
    title: str | None = None
    author: str | None = None
    description: str | None = None
    duration: float | None = None
    video_path: Path | None = None
    thumbnail_url: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)
    subtitles_text: str | None = None


def _ytdlp_sync(url: str, out_dir: Path, download: bool) -> dict[str, Any]:
    import yt_dlp

    opts: dict[str, Any] = {
        "outtmpl": str(out_dir / "%(id)s.%(ext)s"),
        "format": "bv*[height<=1080]+ba/b[height<=1080]/b",
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": True,
        "retries": 3,
        "socket_timeout": 30,
        "writesubtitles": False,
        "writeautomaticsub": False,
        "ignoreerrors": False,
        "max_filesize": settings.max_upload_mb * 1024 * 1024,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=download)
        return ydl.sanitize_info(info)


async def fetch_video(url: str, out_dir: Path, *, download: bool = True) -> VideoFetchResult:
    await asyncio.to_thread(out_dir.mkdir, parents=True, exist_ok=True)
    try:
        info = await asyncio.to_thread(_ytdlp_sync, url, out_dir, download)
    except Exception as exc:
        raise VideoUnavailable(f"Could not download that video: {exc}") from exc

    if not info:
        raise VideoUnavailable("The downloader returned nothing for that link.")

    duration = info.get("duration")
    if duration and duration > settings.max_video_seconds:
        raise VideoUnavailable(
            f"That video is {int(duration // 60)} minutes long, over the "
            f"{settings.max_video_seconds // 60} minute limit."
        )

    path: Path | None = None
    if download:
        path = await asyncio.to_thread(_largest_file, out_dir)

    return VideoFetchResult(
        url=info.get("webpage_url") or url,
        title=info.get("title"),
        author=info.get("uploader") or info.get("channel") or info.get("uploader_id"),
        description=info.get("description"),
        duration=float(duration) if duration else None,
        video_path=path,
        thumbnail_url=info.get("thumbnail"),
        raw={
            k: info.get(k)
            for k in ("id", "extractor", "webpage_url", "title", "uploader", "duration", "tags")
        },
    )


def _largest_file(out_dir: Path) -> Path | None:
    candidates = sorted(
        (p for p in out_dir.iterdir() if p.is_file() and p.suffix != ".part"),
        key=lambda p: p.stat().st_size,
        reverse=True,
    )
    return candidates[0] if candidates else None


async def download_url_to_file(url: str, dest: Path, *, timeout: float = 120.0) -> Path:
    """Plain HTTP download, used for media URLs the scraper hands back."""
    import httpx

    await asyncio.to_thread(dest.parent.mkdir, parents=True, exist_ok=True)
    limit = settings.max_upload_mb * 1024 * 1024
    total = 0
    async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
        async with client.stream("GET", url) as resp:
            resp.raise_for_status()
            with dest.open("wb") as fh:
                async for chunk in resp.aiter_bytes(64 * 1024):
                    total += len(chunk)
                    if total > limit:
                        raise VideoUnavailable("That file is larger than the upload limit.")
                    fh.write(chunk)
    return dest
