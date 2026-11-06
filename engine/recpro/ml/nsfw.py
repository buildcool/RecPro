"""NudeNet 640m body-part detector (YOLOv8 format), recall-first.

The whole photo is checked at 640 px; large photos are also checked as 4 overlapping tiles so
small exposed regions aren't missed. Exposed-part detections that sit on a face are dropped:
NudeNet confuses close-up skin (portraits) with intimate parts, and real nudity isn't centred
on someone's face.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .runtime import session

LABELS = [
    "FEMALE_GENITALIA_COVERED", "FACE_FEMALE", "BUTTOCKS_EXPOSED", "FEMALE_BREAST_EXPOSED",
    "FEMALE_GENITALIA_EXPOSED", "MALE_BREAST_EXPOSED", "ANUS_EXPOSED", "FEET_EXPOSED",
    "BELLY_COVERED", "FEET_COVERED", "ARMPITS_COVERED", "ARMPITS_EXPOSED", "FACE_MALE",
    "BELLY_EXPOSED", "MALE_GENITALIA_EXPOSED", "ANUS_COVERED", "FEMALE_BREAST_COVERED",
    "BUTTOCKS_COVERED",
]
FACE = ("FACE_FEMALE", "FACE_MALE")
EXPOSED = ("BUTTOCKS_EXPOSED", "FEMALE_BREAST_EXPOSED", "FEMALE_GENITALIA_EXPOSED", "MALE_GENITALIA_EXPOSED", "ANUS_EXPOSED")
# What makes a photo "suggestive" (swimwear, lingerie, shirtless…) and how strongly each part counts
SUGGESTIVE = {
    "FEMALE_BREAST_COVERED": 0.9,
    "FEMALE_GENITALIA_COVERED": 1.0,
    "BUTTOCKS_COVERED": 0.8,
    "BELLY_EXPOSED": 0.7,
    "MALE_BREAST_EXPOSED": 0.65,
    "ANUS_COVERED": 0.9,
}
MIN_SCORE = 0.15


@dataclass
class Det:
    label: str
    score: float
    box: tuple[float, float, float, float]  # x1, y1, x2, y2 in image pixels


def _on_face(box, faces) -> bool:
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    for f in faces:
        fx1, fy1, fx2, fy2 = f
        # centre inside the face (slightly enlarged), or the part box mostly overlaps it
        pad_x, pad_y = (fx2 - fx1) * 0.15, (fy2 - fy1) * 0.15
        if fx1 - pad_x <= cx <= fx2 + pad_x and fy1 - pad_y <= cy <= fy2 + pad_y:
            return True
        ix = max(0.0, min(box[2], fx2) - max(box[0], fx1))
        iy = max(0.0, min(box[3], fy2) - max(box[1], fy1))
        area = max(1e-6, (box[2] - box[0]) * (box[3] - box[1]))
        if ix * iy / area > 0.5:
            return True
    return False


class NudeDetector:
    def __init__(self, path: Path, use_gpu: bool = True):
        self.sess = session(path, use_gpu)
        self.inp = self.sess.get_inputs()[0].name
        self.size = 640

    def _run(self, img: np.ndarray, ox: float = 0.0, oy: float = 0.0) -> list[Det]:
        h, w = img.shape[:2]
        side = max(h, w)
        canvas = np.zeros((side, side, 3), dtype=np.uint8)
        canvas[:h, :w] = img
        x = cv2.resize(canvas, (self.size, self.size), interpolation=cv2.INTER_AREA if side > self.size else cv2.INTER_LINEAR)
        blob = (x.astype(np.float32) / 255.0).transpose(2, 0, 1)[None]
        out = self.sess.run(None, {self.inp: blob})[0][0]  # (22, N): cx, cy, w, h, 18 class scores
        cls = out[4:, :]
        best = cls.max(axis=0)
        keep = np.where(best >= MIN_SCORE)[0]
        if keep.size == 0:
            return []
        scale = side / self.size
        dets: list[Det] = []
        arg = cls[:, keep].argmax(axis=0)
        boxes = out[:4, keep].T * scale
        scores = best[keep]
        for c in np.unique(arg):
            m = np.where(arg == c)[0]
            xywh = [[float(b[0] - b[2] / 2), float(b[1] - b[3] / 2), float(b[2]), float(b[3])] for b in boxes[m]]
            idx = cv2.dnn.NMSBoxes(xywh, scores[m].astype(float).tolist(), MIN_SCORE, 0.45)
            for i in np.array(idx).reshape(-1):
                bx, by, bw, bh = xywh[i]
                dets.append(Det(LABELS[int(c)], float(scores[m][i]), (bx + ox, by + oy, bx + bw + ox, by + bh + oy)))
        return dets

    def detect(self, img: np.ndarray) -> list[Det]:
        dets = self._run(img)
        h, w = img.shape[:2]
        if max(h, w) >= 1400:
            th, tw = int(h * 0.6), int(w * 0.6)
            for y0 in (0, h - th):
                for x0 in (0, w - tw):
                    dets += self._run(img[y0 : y0 + th, x0 : x0 + tw], x0, y0)
        return dets

    def scores(self, img: np.ndarray, extra_faces: list[tuple[float, float, float, float]] | None = None) -> dict[str, float]:
        dets = self.detect(img)
        faces = [d.box for d in dets if d.label in FACE and d.score >= 0.4] + list(extra_faces or [])
        out: dict[str, float] = {}
        for d in dets:
            if d.label in FACE:
                continue
            if (d.label in EXPOSED or d.label in SUGGESTIVE) and _on_face(d.box, faces):
                continue
            out[d.label] = max(out.get(d.label, 0.0), d.score)
        return out

    @staticmethod
    def summarize(scores: dict[str, float]) -> dict[str, float]:
        """Image-level nudity and suggestive scores (0..1)."""
        nudity = max((scores.get(k, 0.0) for k in EXPOSED), default=0.0)
        suggestive = max((scores.get(k, 0.0) * wgt for k, wgt in SUGGESTIVE.items()), default=0.0)
        return {"nudity": nudity, "suggestive": suggestive}
