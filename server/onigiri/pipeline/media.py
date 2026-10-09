"""ffmpeg work: probing, audio extraction, keyframe sampling, thumbnails.

Repeated keyframes are dropped before they reach the vision model, because a static
shot read sixty times costs sixty times as much. A frame is dropped only when it is
nearly identical to the frame kept just before it, so a new caption on an unchanged
background always survives.
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

try:
    # iPhones save photos as HEIC. Registering the opener lets Pillow read them, so
    # they are converted to JPEG for Claude and for thumbnails like any other photo.
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:  # pragma: no cover - optional at import, required in the image
    log.warning("pillow-heif is not installed; HEIC photos cannot be read")


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


SIGNATURE_WIDTH = 128
# A pixel counts as changed when its grey level moves by more than this. Sensor grain
# and compression noise stay under it; text appearing or disappearing does not.
PIXEL_CHANGE = 25
# A frame is new when at least this share of its pixels changed since the last kept
# frame. Measured on 720x1280 clips: a single 40 px caption line swapping changes
# 0.4 to 0.5 percent, a grainy static shot changes none.
MIN_CHANGED_SHARE = 0.001


def _signature(path: Path):  # returns a numpy array
    """A small greyscale copy of a frame, aspect kept, for telling new frames from repeats."""
    import numpy as np
    from PIL import Image

    with Image.open(path) as img:
        height = max(1, round(img.height * SIGNATURE_WIDTH / img.width))
        small = img.convert("L").resize((SIGNATURE_WIDTH, height), Image.Resampling.BOX)
        return np.asarray(small, dtype=np.int16)


def changed_share(a, b) -> float:  # numpy arrays from _signature
    import numpy as np

    return float((np.abs(a - b) > PIXEL_CHANGE).mean())


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
    min_changed_share: float = MIN_CHANGED_SHARE,
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
    last = None
    for i, frame in enumerate(frames):
        try:
            signature = await asyncio.to_thread(_signature, frame)
        except Exception:  # a corrupt frame should not stop the job
            continue
        # Compare with the last kept frame only. Comparing with every kept frame
        # threw away new captions that merely looked like an earlier one.
        if last is not None and changed_share(signature, last) < min_changed_share:
            await asyncio.to_thread(frame.unlink, missing_ok=True)
            continue
        last = signature
        kept.append(Keyframe(index=len(kept), timestamp=round(i * interval_s, 1), path=frame))
        if len(kept) >= max_frames:
            break
    return kept


def _detail(path: Path) -> float:
    """How much there is to see in a frame: spread of brightness plus colour."""
    import numpy as np
    from PIL import Image

    with Image.open(path) as img:
        small = np.asarray(img.convert("RGB").resize((96, 96)), dtype=np.float32)
    grey = small.mean(axis=2)
    colour = np.abs(small[..., 0] - small[..., 1]) + np.abs(small[..., 1] - small[..., 2])
    return float(grey.std() + 0.5 * colour.mean())


def pick_cover_frame(frames: list[Keyframe]) -> Keyframe | None:
    """The frame to show in the library.

    Reels usually end on the finished dish, so look in the second half, and take the
    frame with the most going on rather than a dark transition or a title card.
    """
    if not frames:
        return None
    candidates = frames[len(frames) // 2 :] or frames
    scored = []
    for frame in candidates:
        try:
            scored.append((_detail(frame.path), frame.index, frame))
        except Exception:  # an unreadable frame is simply not a candidate
            continue
    if not scored:
        return candidates[-1]
    return max(scored, key=lambda item: (item[0], item[1]))[2]


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
