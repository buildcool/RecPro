"""Frames from a video at an even rate, decoded once by one ffmpeg process.

ffmpeg turns the frames upright (rotation metadata) and scales them; the raw RGB stream is read
in whole frames, so a long video never sits in memory. Frame k is at k / fps seconds.
"""
from __future__ import annotations

import logging
import subprocess
import threading
from collections.abc import Iterator

import numpy as np

from .metadata import NO_WINDOW, ffmpeg_bin

log = logging.getLogger("recpro.video")

MAX_FRAMES = 600  # longer videos are sampled more sparsely


def sample_rate(duration: float | None, max_frames: int = MAX_FRAMES) -> float:
    """1 frame a second, or fewer for long videos (at least one every 10 seconds)."""
    if not duration or duration <= 0:
        return 1.0
    return max(0.1, min(1.0, max_frames / duration))


def frame_size(width: int, height: int, max_side: int) -> tuple[int, int]:
    scale = min(1.0, max_side / max(width, height))
    w = max(2, int(round(width * scale / 2)) * 2)
    h = max(2, int(round(height * scale / 2)) * 2)
    return w, h


def frames(path: str, width: int, height: int, fps: float, max_side: int = 1024, max_frames: int = MAX_FRAMES) -> Iterator[tuple[int, np.ndarray]]:
    """Yields (time in ms, RGB frame) for frames sampled at `fps`."""
    ff = ffmpeg_bin()
    if not ff:
        raise RuntimeError("ffmpeg is not available")
    w, h = frame_size(width, height, max_side)
    size = w * h * 3
    cmd = [ff, "-nostdin", "-v", "error", "-i", path, "-an", "-sn", "-vf", f"fps={fps:.6f},scale={w}:{h}:flags=area",
           "-frames:v", str(max_frames), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=NO_WINDOW)
    err: list[bytes] = []
    t = threading.Thread(target=lambda: err.append(p.stderr.read() if p.stderr else b""), daemon=True)
    t.start()
    k = 0
    try:
        assert p.stdout is not None
        while True:
            buf = p.stdout.read(size)
            if len(buf) < size:
                break
            yield int(round(k * 1000 / fps)), np.frombuffer(buf, np.uint8).reshape(h, w, 3)
            k += 1
    finally:
        if p.poll() is None:
            p.kill()
        p.wait()
        t.join(timeout=5)
    if k == 0:
        raise RuntimeError((b"".join(err).decode("utf-8", "replace").strip() or "no frames")[:300])
