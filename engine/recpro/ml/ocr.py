"""Text reading with PaddleOCR PP-OCRv5 (ONNX): DB text detection + CTC line recognition.

English (PP-OCRv5) reads every line; Devanagari (Hindi/Marathi, PP-OCRv3) is tried on lines the
English model isn't sure about, and the more confident reading wins. PaddleOCR models were
trained on BGR images, so images are converted before inference.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .runtime import session

DET_MAX_SIDE = 1600
DET_THRESH = 0.3
BOX_THRESH = 0.6
UNCLIP = 1.5
REC_H = 48
REC_MAX_W = 1600
MEAN = np.array([0.485, 0.456, 0.406], np.float32)
STD = np.array([0.229, 0.224, 0.225], np.float32)


@dataclass
class Line:
    box: np.ndarray  # 4 x 2 points (image pixels): tl, tr, br, bl
    text: str
    score: float
    lang: str


def _order(pts: np.ndarray) -> np.ndarray:
    s = pts.sum(axis=1)
    d = np.diff(pts, axis=1).ravel()
    return np.array([pts[np.argmin(s)], pts[np.argmin(d)], pts[np.argmax(s)], pts[np.argmax(d)]], np.float32)


class Recognizer:
    def __init__(self, model: Path, dict_path: Path, lang: str, use_gpu: bool):
        self.sess = session(model, use_gpu)
        self.inp = self.sess.get_inputs()[0].name
        chars = [ln.rstrip("\n").rstrip("\r") for ln in dict_path.read_text(encoding="utf-8").splitlines()]
        self.chars = ["<blank>"] + chars + [" "]
        self.lang = lang

    def __call__(self, crops: list[np.ndarray]) -> list[tuple[str, float]]:
        out: list[tuple[str, float] | None] = [None] * len(crops)
        order = sorted(range(len(crops)), key=lambda i: crops[i].shape[1] / max(1, crops[i].shape[0]))
        for s in range(0, len(order), 16):
            idx = order[s : s + 16]
            ws = [min(REC_MAX_W, max(16, int(math.ceil(REC_H * crops[i].shape[1] / max(1, crops[i].shape[0]))))) for i in idx]
            W = max(ws)
            batch = np.zeros((len(idx), 3, REC_H, W), np.float32)
            for k, (i, w) in enumerate(zip(idx, ws)):
                im = cv2.resize(crops[i], (w, REC_H), interpolation=cv2.INTER_LINEAR).astype(np.float32)
                im = (im / 255.0 - 0.5) / 0.5
                batch[k, :, :, :w] = im.transpose(2, 0, 1)
            probs = self.sess.run(None, {self.inp: batch})[0]  # (B, T, C)
            for k, i in enumerate(idx):
                p = probs[k]
                ids = p.argmax(axis=1)
                conf = p.max(axis=1)
                text, scores, prev = [], [], -1
                for t, c in enumerate(ids):
                    if c != prev and c != 0 and c < len(self.chars):
                        text.append(self.chars[c])
                        scores.append(float(conf[t]))
                    prev = c
                out[i] = ("".join(text).strip(), float(np.mean(scores)) if scores else 0.0)
        return [o or ("", 0.0) for o in out]


class OCR:
    def __init__(self, folder: Path, use_gpu: bool = True, languages: tuple[str, ...] = ("en", "hi")):
        folder = Path(folder)
        self.det = session(folder / "detection" / "v5" / "det.onnx", use_gpu)
        self.det_in = self.det.get_inputs()[0].name
        self.rec_en = Recognizer(folder / "languages" / "english" / "rec.onnx", folder / "languages" / "english" / "dict.txt", "en", use_gpu)
        self.rec_hi = None
        hi = folder / "languages" / "hindi"
        if "hi" in languages and (hi / "rec.onnx").exists():
            self.rec_hi = Recognizer(hi / "rec.onnx", hi / "dict.txt", "hi", use_gpu)

    # ---- detection -----------------------------------------------------------------
    def detect(self, rgb: np.ndarray, max_side: int = DET_MAX_SIDE) -> list[np.ndarray]:
        h, w = rgb.shape[:2]
        scale = min(1.0, max_side / max(h, w))
        nh = max(32, int(round(h * scale / 32)) * 32)
        nw = max(32, int(round(w * scale / 32)) * 32)
        bgr = cv2.resize(rgb[:, :, ::-1], (nw, nh), interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR)
        x = ((bgr.astype(np.float32) / 255.0 - MEAN) / STD).transpose(2, 0, 1)[None]
        prob = self.det.run(None, {self.det_in: np.ascontiguousarray(x)})[0][0, 0]
        mask = (prob > DET_THRESH).astype(np.uint8)
        contours, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        sx, sy = w / nw, h / nh
        boxes = []
        for cnt in contours[:1000]:
            if len(cnt) < 4:
                continue
            rect = cv2.minAreaRect(cnt)
            if min(rect[1]) < 3:
                continue
            pts = cv2.boxPoints(rect)
            # mean probability inside the box
            x0, y0 = np.clip(np.floor(pts.min(axis=0)).astype(int), 0, [nw - 1, nh - 1])
            x1, y1 = np.clip(np.ceil(pts.max(axis=0)).astype(int), 0, [nw - 1, nh - 1])
            m = np.zeros((y1 - y0 + 1, x1 - x0 + 1), np.uint8)
            cv2.fillPoly(m, [(pts - [x0, y0]).astype(np.int32)], 1)
            region = prob[y0 : y1 + 1, x0 : x1 + 1]
            if m.sum() == 0 or float(region[m.astype(bool)].mean()) < BOX_THRESH:
                continue
            # unclip: grow the box by area * ratio / perimeter on every side
            (cx, cy), (bw, bh), ang = rect
            d = bw * bh * UNCLIP / max(1e-6, 2 * (bw + bh))
            big = cv2.boxPoints(((cx, cy), (bw + 2 * d, bh + 2 * d), ang))
            big[:, 0] = np.clip(big[:, 0] * sx, 0, w - 1)
            big[:, 1] = np.clip(big[:, 1] * sy, 0, h - 1)
            q = _order(big)
            if min(np.linalg.norm(q[0] - q[1]), np.linalg.norm(q[0] - q[3])) < 4:
                continue
            boxes.append(q)
        boxes.sort(key=lambda q: (round(float(q[:, 1].min()) / 12), float(q[:, 0].min())))
        return boxes

    @staticmethod
    def crop(rgb: np.ndarray, q: np.ndarray) -> np.ndarray:
        w = int(max(np.linalg.norm(q[0] - q[1]), np.linalg.norm(q[3] - q[2])))
        h = int(max(np.linalg.norm(q[0] - q[3]), np.linalg.norm(q[1] - q[2])))
        w, h = max(w, 2), max(h, 2)
        M = cv2.getPerspectiveTransform(q.astype(np.float32), np.array([[0, 0], [w, 0], [w, h], [0, h]], np.float32))
        out = cv2.warpPerspective(rgb, M, (w, h), borderMode=cv2.BORDER_REPLICATE, flags=cv2.INTER_CUBIC)
        if h / max(1, w) >= 1.5:
            out = np.rot90(out)
        return np.ascontiguousarray(out[:, :, ::-1])  # BGR for PaddleOCR

    # ---- all together --------------------------------------------------------------------
    def read(self, rgb: np.ndarray) -> list[Line]:
        # The detector likes text 10-40 px tall: big headings at high resolution merge into blobs,
        # while phone screenshots (tall, small text) need more pixels.
        h, w = rgb.shape[:2]
        tall = max(h, w) / max(1, min(h, w)) >= 1.7
        boxes = self.detect(rgb, 1600 if tall else 1280)
        if not boxes:
            boxes = self.detect(rgb, 960)
        if not boxes:
            return []
        crops = [self.crop(rgb, q) for q in boxes]
        en = self.rec_en(crops)
        lines = [Line(q, t, s, "en") for q, (t, s) in zip(boxes, en)]
        if self.rec_hi is not None:
            # both scripts read every line; the more confident reading wins (English on near-ties)
            hi = self.rec_hi(crops)
            for i, (t, s) in enumerate(hi):
                if t and s > lines[i].score + 0.02:
                    lines[i] = Line(boxes[i], t, s, "hi")
        return [ln for ln in lines if ln.text and ln.score >= 0.5]

    @staticmethod
    def text_of(lines: list[Line]) -> str:
        """Lines joined in reading order (one per line, nearby boxes on a row joined by spaces)."""
        rows: list[list[Line]] = []
        for ln in lines:
            y = float(ln.box[:, 1].mean())
            hgt = float(np.linalg.norm(ln.box[0] - ln.box[3]))
            if rows and abs(float(np.mean([r.box[:, 1].mean() for r in rows[-1]])) - y) < hgt * 0.6:
                rows[-1].append(ln)
            else:
                rows.append([ln])
        return "\n".join(" ".join(r.text for r in sorted(row, key=lambda r: float(r.box[:, 0].min()))) for row in rows)
