"""Faces across a video's sampled frames: tracks, then one identity per person per video.

A track follows a face from frame to frame (similar embedding, or a weaker match where the box
barely moved). Tracks of the same person that never share a frame are then merged, so a person
who leaves and comes back is still one face of the video, with several time spans. Keeping one
face per person per video is what the people matching expects (a person is in a photo once).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

LINK_COS = 0.40  # same face in the next frames
LINK_COS_NEAR = 0.20  # ...or a weaker match where the box barely moved (turning, motion blur)
LINK_IOU = 0.30
MAX_GAP = 3  # sampled frames a face may be missing from its track
MERGE_COS = 0.45  # two tracks of one video are the same person
TOP_K = 8  # embedding = quality-weighted mean of the best frames


@dataclass
class FrameFace:
    idx: int  # sampled frame number
    t_ms: int
    box: np.ndarray  # x1, y1, x2, y2 as fractions of the frame
    kps: np.ndarray  # 5 x 2 as fractions of the frame
    emb: np.ndarray  # L2-normalized
    det_score: float
    quality: float
    age: float | None = None
    male: float | None = None


@dataclass
class Identity:
    members: list[FrameFace]
    embedding: np.ndarray
    best: FrameFace
    spans: list[tuple[int, int]] = field(default_factory=list)
    age: float | None = None
    male: float | None = None


def _iou(a: np.ndarray, b: np.ndarray) -> float:
    x1, y1, x2, y2 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return float(inter / ua) if ua > 0 else 0.0


def _unit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n > 0 else v


def mean_embedding(members: list[FrameFace], top_k: int = TOP_K) -> np.ndarray:
    best = sorted(members, key=lambda f: -f.quality)[:top_k]
    w = np.array([max(0.05, f.quality) for f in best], np.float32)
    return _unit((np.stack([f.emb for f in best]) * w[:, None]).sum(axis=0))


def build_tracks(frames: list[list[FrameFace]], max_gap: int = MAX_GAP) -> list[list[FrameFace]]:
    done: list[list[FrameFace]] = []
    active: list[dict] = []  # {"members", "mean", "last"}
    for idx, faces in enumerate(frames):
        still = []
        for tr in active:
            if idx - tr["last"].idx <= max_gap + 1:
                still.append(tr)
            else:
                done.append(tr["members"])  # missing for too long: the track ends
        active = still
        pairs = []
        for ti, tr in enumerate(active):
            for fj, f in enumerate(faces):
                s = float(tr["mean"] @ f.emb)
                near = _iou(tr["last"].box, f.box)
                if s >= LINK_COS or (s >= LINK_COS_NEAR and near >= LINK_IOU):
                    pairs.append((s + 0.5 * near, ti, fj))
        pairs.sort(reverse=True)
        used_t: set[int] = set()
        used_f: set[int] = set()
        for _, ti, fj in pairs:
            if ti in used_t or fj in used_f:
                continue
            used_t.add(ti)
            used_f.add(fj)
            tr, f = active[ti], faces[fj]
            tr["members"].append(f)
            n = len(tr["members"])
            tr["mean"] = _unit(tr["mean"] * (n - 1) + f.emb)
            tr["last"] = f
        for fj, f in enumerate(faces):
            if fj not in used_f:
                active.append({"members": [f], "mean": f.emb.copy(), "last": f})
    done += [tr["members"] for tr in active]
    return done


def merge_tracks(tracks: list[list[FrameFace]], merge_cos: float = MERGE_COS) -> list[list[FrameFace]]:
    """Joins tracks of the same person that never appear in the same frame."""
    groups = [{"members": list(t), "frames": {f.idx for f in t}, "mean": mean_embedding(t)} for t in tracks]
    while len(groups) > 1:
        best, pair = merge_cos, None
        for i in range(len(groups)):
            for j in range(i + 1, len(groups)):
                if groups[i]["frames"] & groups[j]["frames"]:
                    continue
                s = float(groups[i]["mean"] @ groups[j]["mean"])
                if s >= best:
                    best, pair = s, (i, j)
        if pair is None:
            break
        i, j = pair
        a, b = groups[i], groups.pop(j)
        a["members"] += b["members"]
        a["frames"] |= b["frames"]
        a["mean"] = mean_embedding(a["members"])
    return [sorted(g["members"], key=lambda f: f.idx) for g in groups]


def spans_of(times: list[int], step_ms: int, end_ms: int, gap_steps: int = MAX_GAP + 1) -> list[tuple[int, int]]:
    """Sampled times where something is seen, as (start, end) ranges in ms."""
    out: list[tuple[int, int]] = []
    for t in sorted(times):
        if out and t - out[-1][1] <= (gap_steps - 1) * step_ms:
            out[-1] = (out[-1][0], min(end_ms, t + step_ms))
        else:
            out.append((t, min(end_ms, t + step_ms)))
    return out


def identities(frames: list[list[FrameFace]], step_ms: int, end_ms: int) -> list[Identity]:
    out = []
    for members in merge_tracks(build_tracks(frames)):
        best = max(members, key=lambda f: (f.quality, f.det_score))
        if len(members) < 2 and best.det_score < 0.6:
            continue  # a single weak detection is more likely noise than a person
        ages = [f.age for f in members if f.age is not None]
        males = [f.male for f in members if f.male is not None]
        out.append(
            Identity(
                members=members,
                embedding=mean_embedding(members),
                best=best,
                spans=spans_of([f.t_ms for f in members], step_ms, end_ms),
                age=float(np.median(ages)) if ages else None,
                male=float(np.median(males)) if males else None,
            )
        )
    return out


def point_spans(points: list[tuple[int, float]], threshold: float, end_ms: int, step_ms: int) -> list[tuple[int, int, float]]:
    """Ranges where a per-frame score reaches a threshold. Each sampled point lasts until the next
    one (scene frames are kept only when the picture changes); runs are joined: (start, end, max)."""
    pts = sorted(points)
    out: list[tuple[int, int, float]] = []
    for i, (t, v) in enumerate(pts):
        nxt = pts[i + 1][0] if i + 1 < len(pts) else min(end_ms, t + step_ms)
        if v < threshold:
            continue
        if out and out[-1][1] >= t:
            s, _, m = out[-1]
            out[-1] = (s, max(nxt, t + 1), max(m, v))
        else:
            out.append((t, max(nxt, t + 1), v))
    return out
