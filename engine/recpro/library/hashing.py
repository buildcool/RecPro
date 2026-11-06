from __future__ import annotations

import os

from blake3 import blake3

CHUNK = 4 * 1024 * 1024
EDGE = 64 * 1024


def quick_hash(path: str, size: int | None = None) -> str:
    """Cheap identity for move detection: size + first and last 64 KB."""
    if size is None:
        size = os.path.getsize(path)
    h = blake3()
    h.update(size.to_bytes(8, "little"))
    with open(path, "rb") as f:
        h.update(f.read(EDGE))
        if size > 2 * EDGE:
            f.seek(size - EDGE)
            h.update(f.read(EDGE))
    return h.hexdigest()[:32]


def full_hash(path: str) -> str:
    h = blake3()
    with open(path, "rb") as f:
        while True:
            b = f.read(CHUNK)
            if not b:
                break
            h.update(b)
    return h.hexdigest()
