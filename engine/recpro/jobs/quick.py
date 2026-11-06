"""Quick pass: metadata, thumbnail, perceptual hash and move-detection hash for every file."""
from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from ..context import Context
from ..library.hashing import quick_hash
from ..library.imaging import THUMB_MAX, open_image, phash, save_webp, shard, video_frame
from ..library.metadata import date_from_filename, image_meta, video_meta

log = logging.getLogger("recpro.quick")

QUICK_V = 1
COLUMNS = (
    "width", "height", "duration", "vcodec", "taken_at", "taken_src", "gps_lat", "gps_lon",
    "camera", "phash", "quick_hash", "has_exif_camera", "error",
)


class QuickStage:
    name = "quick"
    label = "Preparing photos"
    column = "quick_v"
    version = QUICK_V
    kinds = ("image", "video")
    batch_size = 96
    order = "mtime DESC"

    def __init__(self, ctx: Context):
        self.ctx = ctx
        workers = max(4, min(12, (os.cpu_count() or 8) // 2))
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="quick")

    def available(self) -> bool:
        return True

    def where(self) -> str:
        return ""

    def process(self, rows: list[Any]) -> None:
        results = list(self.pool.map(self._one, rows))
        with self.ctx.db.tx() as c:
            for row, res in zip(rows, results):
                sets = ", ".join(f"{k}=?" for k in COLUMNS)
                c.execute(
                    f"UPDATE media SET {sets}, quick_v=? WHERE id=?",
                    [res.get(k) for k in COLUMNS] + [QUICK_V, row["id"]],
                )

    def _save_thumb(self, row: Any, img) -> None:
        """Private items never get a readable thumbnail on disk, only a sealed one."""
        if row["sens_state"] in ("private", "review"):
            priv = self.ctx.services.get("private")
            if priv is not None:
                priv.store_cached("thumb", row["id"], img)  # type: ignore[attr-defined]
            return
        save_webp(img, shard(self.ctx.paths.thumbs, row["id"]), THUMB_MAX, quality=80)

    def _one(self, row: Any) -> dict[str, Any]:
        path = row["path"]
        out: dict[str, Any] = {"has_exif_camera": 0}
        try:
            out["quick_hash"] = quick_hash(path, row["size"])
            if row["kind"] == "image":
                raw, disp, orig = open_image(path, want=THUMB_MAX * 2)
                with raw:
                    out.update(image_meta(raw, orig))
                self._save_thumb(row, disp)
                out["phash"] = phash(disp)
            else:
                out.update(video_meta(path))
                dur = out.get("duration") or 0
                at = min(3.0, dur * 0.1) if dur else 0.0
                frame = video_frame(path, at, max_side=THUMB_MAX * 2)
                self._save_thumb(row, frame)
                out["phash"] = phash(frame)
        except Exception as e:  # unreadable/corrupt files are kept but flagged
            log.info("quick pass failed for %s: %s", path, e)
            out["error"] = f"Can't read this file: {str(e)[:160]}"
        if not out.get("taken_at"):
            t = date_from_filename(row["name"])
            if t:
                out["taken_at"], out["taken_src"] = t, "filename"
            else:
                out["taken_at"], out["taken_src"] = row["mtime"], "file"
        out.pop("orientation", None)
        return out
