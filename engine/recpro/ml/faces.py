"""Face detection (SCRFD), alignment, recognition (ArcFace R100) and age/gender.

Accuracy choices for "never miss":
* Detection runs at two scales (640 for large faces, 1280 for small faces in group shots)
  and the results are merged with NMS.
* The detector threshold is low (0.40); weak detections get a low quality instead of being
  dropped, so they can be asked about rather than silently missed.
* Embeddings average the face and its mirror image (test-time augmentation).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .runtime import session

ARCFACE_DST = np.array(
    [[38.2946, 51.6963], [73.5318, 51.5014], [56.0252, 71.7366], [41.5493, 92.3655], [70.7299, 92.2041]],
    dtype=np.float32,
)

DET_THRESH = 0.40
NMS_IOU = 0.4
MIN_FACE_PX = 16
MAX_FACES = 64


@dataclass
class Face:
    box: np.ndarray  # x1, y1, x2, y2 in image pixels
    kps: np.ndarray  # 5 x 2
    det_score: float
    embedding: np.ndarray | None = None  # 512, L2-normalized
    quality: float = 0.0
    age: float | None = None
    male: float | None = None


def umeyama(src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    """Least-squares similarity transform (rotation, uniform scale, translation)."""
    num, dim = src.shape
    src_mean, dst_mean = src.mean(0), dst.mean(0)
    src_d, dst_d = src - src_mean, dst - dst_mean
    A = dst_d.T @ src_d / num
    d = np.ones(dim)
    if np.linalg.det(A) < 0:
        d[dim - 1] = -1
    T = np.eye(dim + 1)
    U, S, Vt = np.linalg.svd(A)
    rank = np.linalg.matrix_rank(A)
    if rank == 0:
        return T[:2]
    if rank == dim - 1:
        if np.linalg.det(U) * np.linalg.det(Vt) > 0:
            T[:dim, :dim] = U @ Vt
        else:
            s = d[dim - 1]
            d[dim - 1] = -1
            T[:dim, :dim] = U @ np.diag(d) @ Vt
            d[dim - 1] = s
    else:
        T[:dim, :dim] = U @ np.diag(d) @ Vt
    var = src_d.var(axis=0).sum()
    scale = (S @ d) / var if var > 0 else 1.0
    T[:dim, dim] = dst_mean - scale * (T[:dim, :dim] @ src_mean)
    T[:dim, :dim] *= scale
    return T[:2].astype(np.float32)


def nms(dets: np.ndarray, thresh: float) -> list[int]:
    x1, y1, x2, y2, scores = dets[:, 0], dets[:, 1], dets[:, 2], dets[:, 3], dets[:, 4]
    areas = (x2 - x1 + 1) * (y2 - y1 + 1)
    order = scores.argsort()[::-1]
    keep: list[int] = []
    while order.size > 0:
        i = order[0]
        keep.append(int(i))
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        w = np.maximum(0.0, xx2 - xx1 + 1)
        h = np.maximum(0.0, yy2 - yy1 + 1)
        inter = w * h
        ovr = inter / (areas[i] + areas[order[1:]] - inter)
        order = order[np.where(ovr <= thresh)[0] + 1]
    return keep


class FaceAnalyzer:
    def __init__(self, folder: Path, use_gpu: bool = True):
        folder = Path(folder)
        self.det = session(folder / "scrfd_10g_bnkps.onnx", use_gpu)
        self.rec = session(folder / "glintr100.onnx", use_gpu)
        self.ga = session(folder / "genderage.onnx", use_gpu)
        self.det_in = self.det.get_inputs()[0].name
        outs = self.det.get_outputs()
        self.det_outs = [o.name for o in outs]
        self.batched = len(outs[0].shape) == 3
        self.fmc = 3
        self.strides = (8, 16, 32)
        self.num_anchors = 2
        self.use_kps = len(outs) == 9
        self._anchors: dict[tuple[int, int, int], np.ndarray] = {}
        self.rec_in = self.rec.get_inputs()[0].name
        self.ga_in = self.ga.get_inputs()[0].name
        self.provider = self.det.get_providers()[0]

    # ------------------------------------------------------------------ detection
    def _anchor_centers(self, h: int, w: int, stride: int) -> np.ndarray:
        key = (h, w, stride)
        c = self._anchors.get(key)
        if c is None:
            c = np.stack(np.mgrid[:h, :w][::-1], axis=-1).astype(np.float32)
            c = (c * stride).reshape((-1, 2))
            if self.num_anchors > 1:
                c = np.stack([c] * self.num_anchors, axis=1).reshape((-1, 2))
            self._anchors[key] = c
        return c

    def _detect_at(self, img: np.ndarray, size: int, thresh: float) -> tuple[np.ndarray, np.ndarray]:
        h, w = img.shape[:2]
        im_ratio = h / w
        if im_ratio > 1:
            nh, nw = size, max(1, int(round(size / im_ratio)))
        else:
            nw, nh = size, max(1, int(round(size * im_ratio)))
        scale = nh / h
        resized = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR)
        canvas = np.zeros((size, size, 3), dtype=np.float32)
        canvas[:nh, :nw] = resized
        blob = ((canvas - 127.5) / 128.0).transpose(2, 0, 1)[None].astype(np.float32)
        outs = self.det.run(self.det_outs, {self.det_in: blob})
        scores_l, boxes_l, kps_l = [], [], []
        for idx, stride in enumerate(self.strides):
            scores = outs[idx]
            bbox = outs[idx + self.fmc] * stride
            kps = outs[idx + self.fmc * 2] * stride if self.use_kps else None
            if self.batched:
                scores, bbox = scores[0], bbox[0]
                kps = kps[0] if kps is not None else None
            scores = scores.reshape(-1)
            centers = self._anchor_centers(size // stride, size // stride, stride)
            pos = np.where(scores >= thresh)[0]
            if pos.size == 0:
                continue
            c = centers[pos]
            b = bbox.reshape(-1, 4)[pos]
            boxes = np.stack([c[:, 0] - b[:, 0], c[:, 1] - b[:, 1], c[:, 0] + b[:, 2], c[:, 1] + b[:, 3]], axis=1)
            scores_l.append(scores[pos])
            boxes_l.append(boxes)
            if kps is not None:
                k = kps.reshape(-1, 10)[pos]
                pts = np.empty((k.shape[0], 5, 2), dtype=np.float32)
                pts[:, :, 0] = c[:, 0:1] + k[:, 0::2]
                pts[:, :, 1] = c[:, 1:2] + k[:, 1::2]
                kps_l.append(pts)
        if not scores_l:
            return np.zeros((0, 5), np.float32), np.zeros((0, 5, 2), np.float32)
        scores = np.concatenate(scores_l)
        boxes = np.concatenate(boxes_l) / scale
        kpss = np.concatenate(kps_l) / scale
        dets = np.hstack([boxes, scores[:, None]]).astype(np.float32)
        keep = nms(dets, NMS_IOU)
        return dets[keep], kpss[keep]

    def detect(self, img: np.ndarray, thresh: float = DET_THRESH) -> tuple[np.ndarray, np.ndarray]:
        h, w = img.shape[:2]
        dets, kps = self._detect_at(img, 640, thresh)
        if max(h, w) >= 1100:
            d2, k2 = self._detect_at(img, 1280, thresh)
            if len(d2):
                dets = np.concatenate([dets, d2]) if len(dets) else d2
                kps = np.concatenate([kps, k2]) if len(kps) else k2
                keep = nms(dets, NMS_IOU)
                dets, kps = dets[keep], kps[keep]
        if len(dets) > MAX_FACES:
            order = np.argsort(-(dets[:, 4] * (dets[:, 2] - dets[:, 0])))[:MAX_FACES]
            dets, kps = dets[order], kps[order]
        return dets, kps

    # ------------------------------------------------------------------ recognition
    @staticmethod
    def align(img: np.ndarray, kps: np.ndarray, size: int = 112) -> np.ndarray:
        M = umeyama(kps.astype(np.float32), ARCFACE_DST * (size / 112.0))
        return cv2.warpAffine(img, M, (size, size), borderValue=0.0)

    def embed(self, crops: list[np.ndarray]) -> np.ndarray:
        if not crops:
            return np.zeros((0, 512), np.float32)
        arr = np.stack(crops).astype(np.float32)
        both = np.concatenate([arr, arr[:, :, ::-1, :]], axis=0)  # + mirrored
        blob = ((both - 127.5) / 127.5).transpose(0, 3, 1, 2)
        out = []
        for i in range(0, blob.shape[0], 64):
            out.append(self.rec.run(None, {self.rec_in: np.ascontiguousarray(blob[i : i + 64])})[0])
        feats = np.concatenate(out)
        n = arr.shape[0]
        emb = feats[:n] + feats[n:]
        emb /= np.linalg.norm(emb, axis=1, keepdims=True) + 1e-9
        return emb.astype(np.float32)

    def gender_age(self, img: np.ndarray, boxes: np.ndarray) -> list[tuple[float, float]]:
        if len(boxes) == 0:
            return []
        crops = []
        for b in boxes:
            w, h = b[2] - b[0], b[3] - b[1]
            cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
            s = 96.0 / (max(w, h) * 1.5)
            M = np.array([[s, 0, 48 - cx * s], [0, s, 48 - cy * s]], dtype=np.float32)
            crops.append(cv2.warpAffine(img, M, (96, 96), borderValue=0.0))
        blob = np.stack(crops).astype(np.float32).transpose(0, 3, 1, 2)
        out = []
        for i in range(0, blob.shape[0], 64):
            out.append(self.ga.run(None, {self.ga_in: np.ascontiguousarray(blob[i : i + 64])})[0])
        pred = np.concatenate(out)
        res = []
        for p in pred:
            g = p[:2] - p[:2].max()
            e = np.exp(g)
            male = float(e[1] / e.sum())
            res.append((male, float(np.clip(p[2] * 100.0, 0, 100))))
        return res

    # ------------------------------------------------------------------ quality
    @staticmethod
    def quality(box: np.ndarray, kps: np.ndarray, det_score: float, crop: np.ndarray) -> float:
        side = float(min(box[2] - box[0], box[3] - box[1]))
        q_size = float(np.clip((side - 20) / 70, 0, 1))
        q_det = float(np.clip((det_score - 0.4) / 0.4, 0, 1))
        le, re, nose = kps[0], kps[1], kps[2]
        eye_d = float(np.linalg.norm(re - le)) + 1e-6
        mid = (le + re) / 2
        yaw = abs(float(nose[0] - mid[0])) / eye_d
        roll = abs(math.degrees(math.atan2(float(re[1] - le[1]), float(re[0] - le[0]))))
        q_pose = float(np.clip(1 - yaw / 0.55, 0, 1)) * float(np.clip(1 - max(0.0, roll - 25) / 45, 0, 1))
        gray = cv2.cvtColor(crop.astype(np.uint8), cv2.COLOR_RGB2GRAY)
        lap = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        q_blur = float(np.clip((math.log1p(lap) - math.log1p(15)) / (math.log1p(400) - math.log1p(15)), 0, 1))
        return round(0.3 * q_size + 0.2 * q_det + 0.25 * q_pose + 0.25 * q_blur, 4)

    # ------------------------------------------------------------------ all together
    def analyze_many(self, images: list[np.ndarray]) -> list[list[Face]]:
        """Detect in each image, then embed all faces of all images in one batch."""
        per_image: list[list[Face]] = []
        crops: list[np.ndarray] = []
        owners: list[tuple[int, int]] = []
        for ii, img in enumerate(images):
            faces: list[Face] = []
            if img is None:
                per_image.append(faces)
                continue
            dets, kpss = self.detect(img)
            for j in range(len(dets)):
                box, kps = dets[j, :4], kpss[j]
                if min(box[2] - box[0], box[3] - box[1]) < MIN_FACE_PX:
                    continue
                crop = self.align(img, kps)
                f = Face(box=box, kps=kps, det_score=float(dets[j, 4]))
                f.quality = self.quality(box, kps, f.det_score, crop)
                faces.append(f)
                crops.append(crop)
                owners.append((ii, len(faces) - 1))
            if faces:
                for f, (male, age) in zip(faces, self.gender_age(img, np.stack([f.box for f in faces]))):
                    f.male, f.age = male, age
            per_image.append(faces)
        if crops:
            emb = self.embed(crops)
            for (ii, j), e in zip(owners, emb):
                per_image[ii][j].embedding = e
        return per_image

    def analyze(self, img: np.ndarray) -> list[Face]:
        return self.analyze_many([img])[0]
