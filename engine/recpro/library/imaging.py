"""Image decoding, thumbnails, previews and perceptual hashes."""
from __future__ import annotations

import io
import os
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

try:
    import pillow_heif

    pillow_heif.register_heif_opener()
except Exception:  # pragma: no cover - optional
    pillow_heif = None

from .metadata import NO_WINDOW, ffmpeg_bin

Image.MAX_IMAGE_PIXELS = 400_000_000  # large panoramas are fine; still guards decompression bombs

THUMB_MAX = 400
PREVIEW_MAX = 2048


def shard(base: Path, media_id: int, ext: str = ".webp") -> Path:
    return base / f"{media_id // 1000:04d}" / f"{media_id}{ext}"


def open_image(path: str, want: int | None = None) -> tuple[Image.Image, Image.Image, tuple[int, int]]:
    """Returns (raw image for metadata, display-oriented RGB image, original raw size).

    For JPEGs ``draft`` makes libjpeg decode at 1/2, 1/4 or 1/8 scale, which is much faster.
    """
    im = Image.open(path)
    orig_size = im.size
    if want and im.format == "JPEG":
        try:
            im.draft("RGB", (want, want))
        except Exception:
            pass
    disp = ImageOps.exif_transpose(im)
    if disp is None:
        disp = im
    if disp.mode not in ("RGB",):
        if disp.mode in ("RGBA", "LA", "P") and ("transparency" in disp.info or disp.mode != "P"):
            bg = Image.new("RGB", disp.size, (255, 255, 255))
            rgba = disp.convert("RGBA")
            bg.paste(rgba, mask=rgba.getchannel("A"))
            disp = bg
        else:
            disp = disp.convert("RGB")
    if want and max(disp.size) > want:
        disp.thumbnail((want, want), Image.Resampling.LANCZOS if max(disp.size) < want * 3 else Image.Resampling.BILINEAR)
    return im, disp, orig_size


def save_webp(img: Image.Image, dest: Path, max_side: int, quality: int = 80) -> tuple[int, int]:
    dest.parent.mkdir(parents=True, exist_ok=True)
    out = img
    if max(img.size) > max_side:
        out = img.copy()
        out.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    tmp = dest.with_suffix(".tmp")
    out.save(tmp, "WEBP", quality=quality, method=4)
    os.replace(tmp, dest)
    return out.size


def webp_bytes(img: Image.Image, max_side: int, quality: int = 80) -> bytes:
    out = img
    if max(img.size) > max_side:
        out = img.copy()
        out.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    out.save(buf, "WEBP", quality=quality, method=4)
    return buf.getvalue()


def phash(img: Image.Image) -> int:
    """64-bit DCT perceptual hash (signed, to fit SQLite INTEGER)."""
    from scipy.fft import dct

    g = np.asarray(img.convert("L").resize((32, 32), Image.Resampling.LANCZOS), dtype=np.float32)
    d = dct(dct(g, axis=0, norm="ortho"), axis=1, norm="ortho")[:8, :8]
    med = np.median(d.flatten()[1:])
    bits = (d > med).flatten()
    v = 0
    for b in bits:
        v = (v << 1) | int(b)
    if v >= 1 << 63:
        v -= 1 << 64
    return v


def hamming(a: int, b: int) -> int:
    return bin((a ^ b) & 0xFFFFFFFFFFFFFFFF).count("1")


def video_frame(path: str, at_sec: float, max_side: int = 1280) -> Image.Image:
    ff = ffmpeg_bin()
    if not ff:
        raise RuntimeError("ffmpeg is not available")
    vf = f"scale='if(gt(iw,ih),min({max_side},iw),-2)':'if(gt(iw,ih),-2,min({max_side},ih))'"
    cmd = [ff, "-nostdin", "-v", "error", "-ss", f"{max(0.0, at_sec):.3f}", "-i", path, "-frames:v", "1", "-vf", vf, "-f", "image2pipe", "-vcodec", "mjpeg", "-q:v", "3", "-"]
    cp = subprocess.run(cmd, capture_output=True, stdin=subprocess.DEVNULL, timeout=60, creationflags=NO_WINDOW)
    if cp.returncode != 0 or not cp.stdout:
        if at_sec > 0:
            return video_frame(path, 0.0, max_side)
        raise RuntimeError(cp.stderr.decode("utf-8", "replace")[:300] or "no frame")
    return Image.open(io.BytesIO(cp.stdout)).convert("RGB")
