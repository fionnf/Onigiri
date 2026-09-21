from __future__ import annotations

import pytest

from onigiri.models import SourceKind
from onigiri.pipeline.detect import classify_file, detect_kind, find_url


@pytest.mark.parametrize(
    ("url", "kind"),
    [
        ("https://www.instagram.com/reel/Cabc123/", SourceKind.instagram),
        ("https://instagram.com/p/Cabc/", SourceKind.instagram),
        ("https://www.tiktok.com/@cook/video/123", SourceKind.short_video),
        ("https://youtu.be/abc", SourceKind.short_video),
        ("https://smittenkitchen.com/2024/01/soup/", SourceKind.web),
    ],
)
def test_detect_url_kinds(url: str, kind: SourceKind) -> None:
    assert detect_kind(url=url, text=None)[0] is kind


def test_url_is_found_inside_shared_text() -> None:
    text = "Check this out https://www.instagram.com/reel/Cx1/ looks great"
    kind, url = detect_kind(url=None, text=text)
    assert kind is SourceKind.instagram
    assert url == "https://www.instagram.com/reel/Cx1/"


def test_trailing_punctuation_is_trimmed() -> None:
    assert find_url("see https://example.com/recipe.") == "https://example.com/recipe"


def test_files_decide_when_there_is_no_url() -> None:
    assert detect_kind(url=None, text=None, file_kinds=["image"])[0] is SourceKind.photo
    assert detect_kind(url=None, text=None, file_kinds=["video"])[0] is SourceKind.video_file
    assert detect_kind(url=None, text=None, file_kinds=["image", "video"])[0] is (
        SourceKind.video_file
    )


def test_plain_text_is_text() -> None:
    assert detect_kind(url=None, text="200g flour, 2 eggs")[0] is SourceKind.text


@pytest.mark.parametrize(
    ("name", "ctype", "expected"),
    [
        ("a.jpg", None, "image"),
        ("a.HEIC", None, "image"),
        ("clip.mp4", None, "video"),
        ("x", "image/webp", "image"),
        ("x", "video/quicktime", "video"),
        ("notes.txt", "text/plain", "other"),
    ],
)
def test_classify_file(name: str, ctype: str | None, expected: str) -> None:
    assert classify_file(name, ctype) == expected
