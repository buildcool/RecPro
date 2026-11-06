"""Per-face facial expression (HSEmotion EfficientNet-B2, 8 AffectNet classes)."""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from .runtime import session

CLASSES = ["angry", "contempt", "disgust", "fear", "happy", "neutral", "sad", "surprise"]
MEAN = np.array([0.485, 0.456, 0.406], np.float32)
STD = np.array([0.229, 0.224, 0.225], np.float32)


class EmotionModel:
    def __init__(self, path: Path, use_gpu: bool = True):
        self.sess = session(path, use_gpu)
        self.inp = self.sess.get_inputs()[0].name
        shape = self.sess.get_inputs()[0].shape
        self.size = int(shape[2]) if isinstance(shape[2], int) else 260
        self.batch_fixed = isinstance(shape[0], int)

    def predict(self, img: np.ndarray, boxes: list[np.ndarray]) -> list[tuple[str, float]]:
        """(emotion, probability) for each face box (x1, y1, x2, y2 in pixels)."""
        if not boxes:
            return []
        h, w = img.shape[:2]
        crops = []
        for b in boxes:
            x1, y1, x2, y2 = (float(v) for v in b[:4])
            mx, my = (x2 - x1) * 0.1, (y2 - y1) * 0.1
            x1, y1 = max(0, int(x1 - mx)), max(0, int(y1 - my))
            x2, y2 = min(w, int(x2 + mx)), min(h, int(y2 + my))
            face = img[y1:y2, x1:x2] if x2 > x1 and y2 > y1 else img
            x = cv2.resize(face, (self.size, self.size), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
            crops.append(((x - MEAN) / STD).transpose(2, 0, 1))
        blob = np.stack(crops).astype(np.float32)
        if self.batch_fixed:
            logits = np.concatenate([self.sess.run(None, {self.inp: blob[i : i + 1]})[0] for i in range(len(blob))])
        else:
            logits = self.sess.run(None, {self.inp: blob})[0]
        logits = logits - logits.max(axis=1, keepdims=True)
        p = np.exp(logits)
        p /= p.sum(axis=1, keepdims=True)
        return [(CLASSES[int(i)], float(row[int(i)])) for row, i in zip(p, p.argmax(axis=1))]
