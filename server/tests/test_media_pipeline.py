"""Video and photo capture, exercising ffmpeg for real with stubbed model calls."""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import AsyncClient

from onigiri.pipeline import media as mediautil
from onigiri.services.jobs import wait_for_background

FIXTURES = Path(__file__).parent / "fixtures"
CLIP = FIXTURES / "clip.mp4"
PAGE = FIXTURES / "page.jpg"

needs_ffmpeg = pytest.mark.skipif(
    not mediautil.ffmpeg_available(), reason="ffmpeg is not installed"
)


@needs_ffmpeg
async def test_probe_reads_streams() -> None:
    info = await mediautil.probe(CLIP)
    assert info.has_video is True
    assert info.has_audio is True
    assert info.duration == pytest.approx(6.0, abs=1.0)
    assert info.width == 640


@needs_ffmpeg
async def test_audio_extraction_produces_a_file(tmp_path: Path) -> None:
    out = await mediautil.extract_audio(CLIP, tmp_path / "a.mp3")
    assert out is not None
    assert out.stat().st_size > 1000


@needs_ffmpeg
async def test_keyframes_are_sampled_and_deduplicated(tmp_path: Path) -> None:
    frames = await mediautil.extract_keyframes(
        CLIP, tmp_path / "frames", interval_s=0.5, max_frames=20
    )
    assert frames, "expected at least one frame"
    # The clip is a moving test pattern, so frames differ, but never more than asked.
    assert len(frames) <= 20
    assert all(f.path.exists() and f.path.stat().st_size > 0 for f in frames)
    assert [f.timestamp for f in frames] == sorted(f.timestamp for f in frames)


@needs_ffmpeg
async def test_identical_frames_collapse_to_one(tmp_path: Path) -> None:
    """A static shot must not be read sixty times."""
    import subprocess

    static = tmp_path / "static.mp4"
    subprocess.run(  # noqa: ASYNC221 - a one-off fixture build, not hot-path work
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=navy:size=320x240:rate=10:duration=5",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(static),
        ],
        check=True,
        capture_output=True,
    )
    frames = await mediautil.extract_keyframes(
        static, tmp_path / "f2", interval_s=0.5, max_frames=20
    )
    assert len(frames) == 1


def test_thumbnail_is_downscaled_jpeg() -> None:
    data, width, height = mediautil.make_thumbnail(PAGE.read_bytes(), max_edge=400)
    assert max(width, height) == 400
    assert data[:2] == b"\xff\xd8"  # JPEG magic
    assert len(data) < PAGE.stat().st_size


def test_vision_preparation_caps_resolution() -> None:
    data = mediautil.prepare_for_vision(PAGE.read_bytes(), max_edge=500)
    width, height = mediautil.image_dimensions(data)
    assert max(width, height) == 500


@needs_ffmpeg
async def test_video_upload_is_transcribed_and_read(
    client: AsyncClient, stub_llm, monkeypatch
) -> None:
    from onigiri.pipeline import vision

    async def fake_read_keyframes(frames, **kw) -> str:
        assert frames, "frames should reach the vision step"
        return "250g FLOUR\nBAKE 20 MIN"

    monkeypatch.setattr(vision, "read_keyframes", fake_read_keyframes)

    with CLIP.open("rb") as fh:
        resp = await client.post(
            "/api/ingest/upload", files={"files": ("clip.mp4", fh, "video/mp4")}
        )
    assert resp.status_code == 202, resp.text
    await wait_for_background()

    job = (await client.get(f"/api/jobs/{resp.json()['id']}")).json()
    assert job["status"] == "done", job

    detail = (await client.get(f"/api/recipes/{job['recipe_id']}")).json()
    source = detail["source"]
    assert source["kind"] == "video_file"
    assert source["transcript_text"] == "stub transcript"
    assert "250g FLOUR" in source["onscreen_text"]
    # a frame became the hero image
    assert detail["hero_url"]

    stages = [entry["stage"] for entry in job["stage_log"]]
    assert "transcribing" in stages
    assert "reading" in stages


async def test_photo_upload_is_read_and_stored(client: AsyncClient, stub_llm, monkeypatch) -> None:
    from onigiri.pipeline import vision

    async def fake_read_photos(images, **kw):
        assert len(images) == 1
        return vision.PhotoReadResult(
            text="Lentil Soup\n250 g red lentils\n2 onions",
            is_handwritten=False,
            has_recipe_text=True,
            low_confidence_lines=["2 onions"],
        )

    monkeypatch.setattr(vision, "read_photos", fake_read_photos)

    with PAGE.open("rb") as fh:
        resp = await client.post(
            "/api/ingest/upload", files={"files": ("page.jpg", fh, "image/jpeg")}
        )
    assert resp.status_code == 202
    await wait_for_background()

    job = (await client.get(f"/api/jobs/{resp.json()['id']}")).json()
    assert job["status"] == "done", job

    detail = (await client.get(f"/api/recipes/{job['recipe_id']}")).json()
    assert "250 g red lentils" in detail["source"]["photo_text"]
    assert "hard to read" in detail["source"]["photo_text"]
    assert detail["hero_url"]

    media_resp = await client.get(detail["hero_url"])
    assert media_resp.status_code == 200
    assert media_resp.headers["content-type"].startswith("image/")


async def test_photo_without_recipe_text_asks_for_more(
    client: AsyncClient, stub_llm, monkeypatch
) -> None:
    from onigiri.pipeline import vision

    async def fake_read_photos(images, **kw):
        return vision.PhotoReadResult(text="", has_recipe_text=False)

    monkeypatch.setattr(vision, "read_photos", fake_read_photos)

    with PAGE.open("rb") as fh:
        resp = await client.post(
            "/api/ingest/upload", files={"files": ("dish.jpg", fh, "image/jpeg")}
        )
    await wait_for_background()
    job = (await client.get(f"/api/jobs/{resp.json()['id']}")).json()
    assert job["status"] == "needs_input"
    assert "no readable recipe text" in job["needs_input_reason"].lower()


async def test_non_media_upload_is_rejected(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/ingest/upload", files={"files": ("notes.txt", b"hello", "text/plain")}
    )
    assert resp.status_code == 415


@needs_ffmpeg
async def test_every_new_caption_survives_deduplication(tmp_path: Path) -> None:
    """Text-overlay reels change only the caption; each caption must be read."""
    import subprocess

    from PIL import Image, ImageDraw, ImageFont

    font = ImageFont.load_default(size=40)
    captions = ["SHAKSHUKA", "1 onion + 1 pepper", "400 g tomatoes", "4 eggs", "feta + parsley"]
    for n, caption in enumerate(captions):
        img = Image.new("RGB", (720, 1280), (58, 42, 30))
        ImageDraw.Draw(img).text((120, 600), caption, font=font, fill="white")
        img.save(tmp_path / f"c{n}.png")
    clip = tmp_path / "captions.mp4"
    subprocess.run(  # noqa: ASYNC221 - a one-off fixture build, not hot-path work
        [
            "ffmpeg",
            "-y",
            "-framerate",
            "1/3",
            "-i",
            str(tmp_path / "c%d.png"),
            "-r",
            "24",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(clip),
        ],
        check=True,
        capture_output=True,
    )
    frames = await mediautil.extract_keyframes(clip, tmp_path / "frames", interval_s=1.0)
    assert len(frames) == len(captions)
