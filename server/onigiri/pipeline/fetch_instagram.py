"""Instagram capture through Apify.

Instagram blocks unauthenticated fetches, so a scraping service does the work. Every
failure mode ends in a clear instruction for the owner rather than a silent empty
recipe: the job moves to `needs_input` and the UI asks for the caption or the video.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

from onigiri.config import settings

log = logging.getLogger(__name__)

APIFY_BASE = "https://api.apify.com/v2"


class InstagramUnavailable(RuntimeError):
    """Raised when the post could not be fetched; the owner is asked to paste instead."""


@dataclass
class InstagramPost:
    url: str
    caption: str | None = None
    author: str | None = None
    title: str | None = None
    image_urls: list[str] = field(default_factory=list)
    video_urls: list[str] = field(default_factory=list)
    video_duration: float | None = None
    hashtags: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def has_media(self) -> bool:
        return bool(self.image_urls or self.video_urls)


def _collect_media(item: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Walk a post and its carousel children for image and video URLs, in order."""
    images: list[str] = []
    videos: list[str] = []

    def take(node: dict[str, Any]) -> None:
        video = node.get("videoUrl") or node.get("video_url")
        if video:
            videos.append(str(video))
        for key in ("displayUrl", "display_url", "imageUrl"):
            if node.get(key):
                images.append(str(node[key]))
                break
        for img in node.get("images") or []:
            if isinstance(img, str):
                images.append(img)
            elif isinstance(img, dict) and img.get("url"):
                images.append(str(img["url"]))

    take(item)
    for child in item.get("childPosts") or item.get("sidecarItems") or []:
        if isinstance(child, dict):
            take(child)

    seen: set[str] = set()
    images = [u for u in images if not (u in seen or seen.add(u))]
    seen = set()
    videos = [u for u in videos if not (u in seen or seen.add(u))]
    return images, videos


def normalise_item(url: str, item: dict[str, Any]) -> InstagramPost:
    images, videos = _collect_media(item)
    caption = item.get("caption") or item.get("edge_media_to_caption") or None
    if isinstance(caption, dict):  # defensive: some actor versions nest it
        caption = None
    duration = item.get("videoDuration") or item.get("video_duration")
    return InstagramPost(
        url=str(item.get("url") or url),
        caption=(str(caption).strip() if caption else None),
        author=item.get("ownerUsername") or item.get("ownerFullName") or None,
        title=item.get("title") or None,
        image_urls=images,
        video_urls=videos,
        video_duration=float(duration) if duration else None,
        hashtags=[str(h) for h in (item.get("hashtags") or [])][:20],
        raw=item,
    )


async def fetch_instagram(url: str) -> InstagramPost:
    """Fetch a post or reel via the Apify actor, synchronously."""
    if not settings.apify_token:
        raise InstagramUnavailable(
            "No Apify token is configured, so Instagram posts cannot be fetched "
            "automatically. Paste the caption, or upload the video or a screenshot."
        )

    actor = settings.apify_instagram_actor
    endpoint = f"{APIFY_BASE}/acts/{actor}/run-sync-get-dataset-items"
    payload = {
        "directUrls": [url],
        "resultsType": "posts",
        "resultsLimit": 1,
        "addParentData": False,
    }

    try:
        async with httpx.AsyncClient(timeout=settings.apify_timeout_s) as client:
            resp = await client.post(endpoint, params={"token": settings.apify_token}, json=payload)
    except httpx.HTTPError as exc:
        raise InstagramUnavailable(f"Could not reach the scraping service: {exc}") from exc

    if resp.status_code == 402:
        raise InstagramUnavailable(
            "The Apify account is out of credit. Paste the caption or upload the video."
        )
    if resp.status_code >= 400:
        raise InstagramUnavailable(
            f"The scraping service returned {resp.status_code}. "
            "Paste the caption or upload the video."
        )

    try:
        items = resp.json()
    except ValueError as exc:
        raise InstagramUnavailable("The scraping service returned an unreadable reply.") from exc

    if not isinstance(items, list) or not items:
        raise InstagramUnavailable(
            "Instagram returned nothing for that link. It may be a private account or "
            "the link may point to a profile rather than a post."
        )

    item = items[0]
    if item.get("error") or item.get("errorDescription"):
        raise InstagramUnavailable(
            f"Instagram fetch failed: {item.get('errorDescription') or item.get('error')}"
        )

    post = normalise_item(url, item)
    if not post.caption and not post.has_media:
        raise InstagramUnavailable(
            "That post came back empty. Paste the caption or upload the video."
        )
    return post
