"""Private pre-check: runs right after thumbnails, before anything is shown unblurred."""
from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import numpy as np

from ..context import Context
from ..library.imaging import video_frame
from .deep import load_rgb

log = logging.getLogger("recpro.sens")

SENS_V = 2  # v2: exposed-part detections on faces are ignored


class SensStage:
    name = "sens"
    label = "Private check"
    column = "sens_v"
    version = SENS_V
    kinds = ("image", "video")
    batch_size = 24
    order = "mtime DESC"

    def __init__(self, ctx: Context):
        self.ctx = ctx
        self.pool = ThreadPoolExecutor(max_workers=max(4, min(8, (os.cpu_count() or 8) // 3)), thread_name_prefix="sens")

    def available(self) -> bool:
        return self.ctx.services["ml"].has("nudenet")  # type: ignore[attr-defined]

    def where(self) -> str:
        return "quick_v >= 1 AND width IS NOT NULL"

    def _frames(self, row: Any) -> list[np.ndarray]:
        if row["kind"] == "image":
            img = load_rgb(row["path"], 1280)
            return [img] if img is not None else []
        dur = row["duration"] or 0
        out = []
        for frac in (0.1, 0.5, 0.9) if dur > 2 else (0.0,):
            try:
                out.append(np.asarray(video_frame(row["path"], dur * frac, max_side=960), dtype=np.uint8))
            except Exception:
                continue
        return out

    def process(self, rows: list[Any]) -> None:
        ml = self.ctx.services["ml"]
        det = ml.nsfw()  # type: ignore[attr-defined]
        fa = ml.faces()  # type: ignore[attr-defined]
        labels = self.ctx.services["labels"]
        if det is None:
            return
        frames = list(self.pool.map(self._frames, rows))
        done = []
        for row, imgs in zip(rows, frames):
            nud, sug = 0.0, 0.0
            for img in imgs:
                faces = []
                if fa is not None:
                    try:
                        boxes, _ = fa.detect(img, thresh=0.5)
                        faces = [tuple(float(v) for v in b[:4]) for b in boxes]
                    except Exception:
                        faces = []
                s = det.summarize(det.scores(img, faces))
                nud, sug = max(nud, s["nudity"]), max(sug, s["suggestive"])
            labels.record(row["id"], "sensitive.nudity", {"nudenet": nud}, "sensitive")  # type: ignore[attr-defined]
            labels.record(row["id"], "sensitive.suggestive", {"nudenet": sug}, "sensitive")  # type: ignore[attr-defined]
            done.append(row["id"])
        with self.ctx.db.tx() as c:
            c.executemany("UPDATE media SET sens_v=? WHERE id=?", [(SENS_V, i) for i in done])
        labels.update_sens_state(done)  # type: ignore[attr-defined]
