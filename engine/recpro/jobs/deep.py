"""Deep pass: faces (and, as milestones land, other AI analysis) for every photo."""
from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import numpy as np

from ..context import Context
from ..library.imaging import open_image

log = logging.getLogger("recpro.deep")

DEEP_V = 1
DECODE_MAX = 2048


def iou(a, b) -> float:
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def load_rgb(path: str, max_side: int = DECODE_MAX) -> np.ndarray | None:
    try:
        raw, disp, _ = open_image(path, want=max_side)
        raw.close()
        return np.asarray(disp, dtype=np.uint8)
    except Exception as e:
        log.info("decode failed for %s: %s", path, e)
        return None


class DeepStage:
    name = "deep"
    label = "Finding faces"
    column = "deep_v"
    version = DEEP_V
    kinds = ("image",)
    batch_size = 16
    order = "taken_at DESC"

    def __init__(self, ctx: Context):
        self.ctx = ctx
        self.pool = ThreadPoolExecutor(max_workers=max(4, min(8, (os.cpu_count() or 8) // 3)), thread_name_prefix="decode")

    @property
    def ml(self):
        return self.ctx.services["ml"]

    def available(self) -> bool:
        return self.ml.has("faces")  # type: ignore[attr-defined]

    def where(self) -> str:
        return "quick_v >= 1 AND width IS NOT NULL"

    def process(self, rows: list[Any]) -> None:
        fa = self.ml.faces()  # type: ignore[attr-defined]
        if fa is None:
            return
        images = list(self.pool.map(lambda r: load_rgb(r["path"]), rows))
        results = fa.analyze_many(images)
        new_ids: list[int] = []
        with self.ctx.db.tx() as c:
            for row, img, faces in zip(rows, images, results):
                if img is None:
                    c.execute("UPDATE media SET deep_v=?, face_count=0 WHERE id=?", (DEEP_V, row["id"]))
                    continue
                H, W = img.shape[:2]
                old = c.execute(
                    "SELECT id, x1, y1, x2, y2, person_id, state FROM faces WHERE media_id=? AND frame_ms IS NULL", (row["id"],)
                ).fetchall()
                inserted = []
                for f in faces:
                    if f.embedding is None:
                        continue
                    box = (
                        float(np.clip(f.box[0] / W, 0, 1)),
                        float(np.clip(f.box[1] / H, 0, 1)),
                        float(np.clip(f.box[2] / W, 0, 1)),
                        float(np.clip(f.box[3] / H, 0, 1)),
                    )
                    lm = (f.kps / np.array([W, H], dtype=np.float32)).astype(np.float32).tobytes()
                    cur = c.execute(
                        """INSERT INTO faces(media_id, x1, y1, x2, y2, landmarks, det_score, quality, embedding, age, male, state)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?, 'none')""",
                        (row["id"], *box, lm, f.det_score, f.quality, f.embedding.astype(np.float16).tobytes(), f.age, f.male),
                    )
                    inserted.append((cur.lastrowid, box))
                # Carry your answers over to re-detected faces (same spot in the photo).
                for o in old:
                    ob = (o["x1"], o["y1"], o["x2"], o["y2"])
                    best = max(inserted, key=lambda t: iou(ob, t[1]), default=None)
                    if best and iou(ob, best[1]) > 0.5:
                        if o["state"] == "confirmed":
                            c.execute("UPDATE faces SET person_id=?, state='confirmed', score=1 WHERE id=?", (o["person_id"], best[0]))
                        c.execute("UPDATE OR IGNORE face_votes SET face_id=? WHERE face_id=?", (best[0], o["id"]))
                    c.execute("DELETE FROM faces WHERE id=?", (o["id"],))
                c.execute("UPDATE media SET deep_v=?, face_count=? WHERE id=?", (DEEP_V, len(inserted), row["id"]))
                new_ids += [fid for fid, _ in inserted]
        people = self.ctx.services.get("people")
        if people is not None and new_ids:
            people.on_new_faces(new_ids)  # type: ignore[attr-defined]
