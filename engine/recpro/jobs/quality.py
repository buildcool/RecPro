"""Quality pass: brightness, highlights and sharpness of each photo, from its stored thumbnail.

Facts, not judgments: Cleanup finds too-dark photos from them (SigLIP can't tell dark from
blurry), and picks the sharpest, best-exposed shot of a burst. Cheap: no photo is decoded again.
Private items have no readable thumbnail, so they're skipped.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

import numpy as np
from PIL import Image

from ..context import Context
from ..library.imaging import shard

QUALITY_V = 1


def measure(path: Any) -> tuple[float, float, float] | None:
    """(mean brightness 0-255, 95th percentile, variance of the Laplacian) of a thumbnail."""
    try:
        g = np.asarray(Image.open(path).convert("L"), np.float32)
    except Exception:
        return None
    lap = g[1:-1, 1:-1] * -4 + g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:]
    return float(g.mean()), float(np.percentile(g, 95)), float(lap.var())


def too_dark(brightness: float | None, highlights: float | None) -> bool:
    """Dark overall and nothing bright in it (a night shot with lights isn't "too dark")."""
    return brightness is not None and highlights is not None and brightness < 40 and highlights < 110


class QualityStage:
    name = "quality"
    label = "Checking exposure"
    column = "quality_v"
    version = QUALITY_V
    kinds = ("image",)
    batch_size = 256
    order = "mtime DESC"

    def __init__(self, ctx: Context):
        self.ctx = ctx
        self.pool = ThreadPoolExecutor(max_workers=6, thread_name_prefix="quality")

    def available(self) -> bool:
        return True

    def where(self) -> str:
        return "quick_v >= 1 AND sens_state NOT IN ('private','review')"

    def process(self, rows: list[Any]) -> None:
        thumbs = self.ctx.paths.thumbs
        results = list(self.pool.map(lambda r: measure(shard(thumbs, int(r["id"]))), rows))
        with self.ctx.db.tx() as c:
            c.executemany(
                "UPDATE media SET quality_v=?, brightness=?, highlights=?, sharpness=? WHERE id=?",
                [(QUALITY_V, *(m if m else (None, None, None)), int(r["id"])) for r, m in zip(rows, results)],
            )
