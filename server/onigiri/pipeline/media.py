"""ffmpeg work: probing, audio extraction, keyframe sampling, thumbnails.

Keyframes are deduplicated with a difference hash before they reach the vision model.
A talking-head reel is mostly the same frame, and paying to read the same frame sixty
times is the easiest cost mistake to make here.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

from onigiri.config import settings

log = logging.getLogger(__name__)


class MediaToolMissing(RuntimeError):
    pass


@dataclass
class ProbeResult:
    duration: float | None = None
    width: int | None = None
    height: int | None = None
    has_audio: bool = False
    has_video: bool = False


def ffmpeg_available() -> bool:
    return shutil.which(settings.ffmpeg_bin) is not None


def ffprobe_available() -> bool:
    return shutil.which(settings.ffprobe_bin) is not None


async def _run(*args: str, timeout: float = 900.0) -> tuple[int, bytes, bytes]:
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        raise
    return proc.returncode or 0, out, err


async def probe(path: Path) -> ProbeResult:
    if not ffprobe_available():
        raise MediaToolMissing("ffprobe is not installed on this machine.")
    code, out, err = await _run(
        settings.ffprobe_bin,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
        timeout=120,
    )
    if code != 0:
        raise RuntimeError(f"ffprobe failed: {err.decode(errors='replace')[:300]}")
    data = json.loads(out or b"{}")
    result = ProbeResult()
    fmt = data.get("format") or {}
    if fmt.get("duration"):
        result.duration = float(fmt["duration"])
    for stream in data.get("streams") or []:
        if stream.get("codec_type") == "audio":
            result.has_audio = True
        elif stream.get("codec_type") == "video":
            result.has_video = True
            result.width = result.width or stream.get("width")
            result.height = result.height or stream.get("height")
    return result


async def extract_audio(video: Path, dest: Path) -> Path | None:
    """Mono 16 kHz MP3: small to upload, plenty for speech recognition."""
    if not ffmpeg_available():
        raise MediaToolMissing("ffmpeg is not installed on this machine.")
    await asyncio.to_thread(dest.parent.mkdir, parents=True, exist_ok=True)
    code, _, err = await _run(
        settings.ffmpeg_bin,
        "-y",
        "-i",
        str(video),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-b:a",
        "64k",
        str(dest),
    )
    if code != 0 or not await asyncio.to_thread(_nonempty, dest):
        log.warning("audio extraction failed: %s", err.decode(errors="replace")[:300])
        return None
    return dest


def _nonempty(path: Path) -> bool:
    return path.exists() and path.stat().st_size > 0


async def split_audio(audio: Path, chunk_seconds: int, out_dir: Path) -> list[Path]:
    """Split long audio so each piece stays inside the transcription size limit."""
    await asyncio.to_thread(out_dir.mkdir, parents=True, exist_ok=True)
    pattern = out_dir / "chunk_%03d.mp3"
    code, _, err = await _run(
        settings.ffmpeg_bin,
        "-y",
        "-i",
        str(audio),
        "-f",
        "segment",
        "-segment_time",
        str(chunk_seconds),
        "-c",
        "copy",
        str(pattern),
    )
    if code != 0:
        log.warning("audio split failed: %s", err.decode(errors="replace")[:300])
        return [audio]
    chunks = sorted(await asyncio.to_thread(lambda: list(out_dir.glob("chunk_*.mp3"))))
    return chunks or [audio]


def _dhash_file(path: Path, size: int = 8) -> int | None:
    """Difference hash of a frame on disk. Runs in a worker thread."""
    try:
        data = path.read_bytes()
    except OSError:
        return None
    return _dhash(data, size) if data else None


def _dhash(data: bytes, size: int = 8) -> int:
    """Difference hash: cheap perceptual fingerprint for near-duplicate frames."""
    from PIL import Image

    with Image.open(io.BytesIO(data)) as img:
        img = img.convert("L").resize((size + 1, size), Image.Resampling.LANCZOS)
        pixels = list(img.getdata())
    bits = 0
    for row in range(size):
        base = row * (size + 1)
        for col in range(size):
            bits = (bits << 1) | int(pixels[base + col] < pixels[base + col + 1])
    return bits


def _hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


@dataclass
class Keyframe:
    index: int
    timestamp: float
    path: Path


async def extract_keyframes(
    video: Path,
    out_dir: Path,
    *,
    interval_s: float | None = None,
    max_frames: int | None = None,
    dedup_threshold: int = 8,
) -> list[Keyframe]:
    if not ffmpeg_available():
        raise MediaToolMissing("ffmpeg is not installed on this machine.")
    interval_s = interval_s or settings.keyframe_interval_s
    max_frames = max_frames or settings.max_keyframes
    await asyncio.to_thread(out_dir.mkdir, parents=True, exist_ok=True)

    pattern = out_dir / "frame_%04d.jpg"
    code, _, err = await _run(
        settings.ffmpeg_bin,
        "-y",
        "-i",
        str(video),
        "-vf",
        f"fps=1/{interval_s},scale=768:-2",
        "-q:v",
        "4",
        "-frames:v",
        str(max_frames * 3),
        str(pattern),
    )
    if code != 0:
        log.warning("keyframe extraction failed: %s", err.decode(errors="replace")[:300])
        return []

    frames = sorted(await asyncio.to_thread(lambda: list(out_dir.glob("frame_*.jpg"))))
    kept: list[Keyframe] = []
    hashes: list[int] = []
    for i, frame in enumerate(frames):
        data = frame.read_bytes()
        if not data:
            continue
        try:
            h = await asyncio.to_thread(_dhash, data)
        except Exception:
            continue
        if any(_hamming(h, prev) <= dedup_threshold for prev in hashes):
            frame.unlink(missing_ok=True)
            continue
        hashes.append(h)
        kept.append(Keyframe(index=len(kept), timestamp=round(i * interval_s, 1), path=frame))
        if len(kept) >= max_frames:
            break
    return kept


def make_thumbnail(data: bytes, max_edge: int = 800, quality: int = 82) -> tuple[bytes, int, int]:
    """Downscale an image for list and hero use. Returns (jpeg bytes, width, height)."""
    from PIL import Image, ImageOps

    with Image.open(io.BytesIO(data)) as img:
        img = ImageOps.exif_transpose(img)
        img = img.convert("RGB")
        img.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        return buf.getvalue(), img.width, img.height


def prepare_for_vision(data: bytes, max_edge: int = 1600) -> bytes:
    """Cap the resolution sent to the vision model; pages need more detail than thumbnails."""
    from PIL import Image, ImageOps

    with Image.open(io.BytesIO(data)) as img:
        img = ImageOps.exif_transpose(img)
        img = img.convert("RGB")
        if max(img.size) > max_edge:
            img.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=88, optimize=True)
        return buf.getvalue()


def image_dimensions(data: bytes) -> tuple[int | None, int | None]:
    from PIL import Image

    try:
        with Image.open(io.BytesIO(data)) as img:
            return img.width, img.height
    except Exception:
        return None, None
