"""Work out what kind of thing the owner just shared."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from onigiri.models import SourceKind

INSTAGRAM_HOSTS = {"instagram.com", "www.instagram.com", "instagr.am", "m.instagram.com"}
SHORT_VIDEO_HOSTS = {
    "tiktok.com",
    "www.tiktok.com",
    "vm.tiktok.com",
    "m.tiktok.com",
    "youtube.com",
    "www.youtube.com",
    "youtu.be",
    "m.youtube.com",
    "facebook.com",
    "www.facebook.com",
    "fb.watch",
    "twitter.com",
    "x.com",
    "www.x.com",
    "pinterest.com",
    "www.pinterest.com",
    "pin.it",
}

_URL_RE = re.compile(r"https?://[^\s<>\"')]+", re.IGNORECASE)

IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif", "image/gif"}
VIDEO_TYPES = {"video/mp4", "video/quicktime", "video/webm", "video/x-matroska", "video/mpeg"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".gif"}
VIDEO_EXTS = {".mp4", ".mov", ".webm", ".mkv", ".m4v", ".avi"}


def find_url(text: str | None) -> str | None:
    if not text:
        return None
    m = _URL_RE.search(text)
    return m.group(0).rstrip(".,);]") if m else None


def host_of(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def is_instagram(url: str) -> bool:
    return host_of(url) in INSTAGRAM_HOSTS


def is_short_video(url: str) -> bool:
    host = host_of(url)
    if host in SHORT_VIDEO_HOSTS:
        # A YouTube watch page may be a long cooking video; still handled by yt-dlp.
        return True
    return False


def classify_file(filename: str, content_type: str | None) -> str:
    ct = (content_type or "").lower().split(";")[0]
    ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    if ct in IMAGE_TYPES or ext in IMAGE_EXTS:
        return "image"
    if ct in VIDEO_TYPES or ext in VIDEO_EXTS:
        return "video"
    if ct.startswith("image/"):
        return "image"
    if ct.startswith("video/"):
        return "video"
    return "other"


def detect_kind(
    *, url: str | None, text: str | None, file_kinds: list[str] | None = None
) -> tuple[SourceKind, str | None]:
    """Return the source kind and the URL to work with, if any."""
    file_kinds = file_kinds or []
    if url is None and text:
        url = find_url(text)

    if url:
        if is_instagram(url):
            return SourceKind.instagram, url
        if is_short_video(url):
            return SourceKind.short_video, url
        return SourceKind.web, url

    if any(k == "video" for k in file_kinds):
        return SourceKind.video_file, None
    if any(k == "image" for k in file_kinds):
        return SourceKind.photo, None
    return SourceKind.text, None
