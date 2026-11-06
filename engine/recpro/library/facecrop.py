from __future__ import annotations

from typing import Any

from PIL import Image

from .imaging import PREVIEW_MAX, open_image, shard, video_frame


def crop_face(ctx, f: Any, size: int) -> Image.Image:
    """Square crop around a face box (normalized coords) with a comfortable margin."""
    if f["frame_ms"] is not None and f["kind"] == "video":
        img = video_frame(f["path"], f["frame_ms"] / 1000.0, max_side=1280)
    else:
        prev = shard(ctx.paths.previews, f["media_id"])
        if prev.exists() and f["sens_state"] != "private":
            img = Image.open(prev).convert("RGB")
        else:
            raw, img, _ = open_image(f["path"], want=PREVIEW_MAX)
            raw.close()
    W, H = img.size
    x1, y1, x2, y2 = f["x1"] * W, f["y1"] * H, f["x2"] * W, f["y2"] * H
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    side = max(x2 - x1, y2 - y1) * 1.6
    side = max(side, 24)
    left, top = cx - side / 2, cy - side / 2 - side * 0.05
    box = (int(round(left)), int(round(top)), int(round(left + side)), int(round(top + side)))
    crop = img.crop(box)  # PIL pads out-of-bounds areas with black
    return crop.resize((size, size), Image.Resampling.LANCZOS)
