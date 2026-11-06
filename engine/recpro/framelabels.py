"""Categories and private content of videos, from their frames.

The whole video gets the best score any of its frames reaches (a beach in part of the video makes
it a beach video), and each category also gets the time ranges where it reaches "please check"
or better, so the viewer can mark them and a search can jump there.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from .ml.tracks import point_spans


def spans_for(labels: Any, grp: str, per_source: dict[str, list[tuple[int, float]]], end_ms: int, step_ms: int) -> list[tuple[int, int, float]]:
    """Union of the ranges where any source reaches its own "please check" threshold."""
    out: list[tuple[int, int, float]] = []
    for src, pts in per_source.items():
        thr = labels.check_threshold(src, grp)
        if thr is None or not pts:
            continue
        out += point_spans(pts, thr, end_ms, step_ms)
    out.sort()
    merged: list[tuple[int, int, float]] = []
    for s, e, v in out:
        if merged and s <= merged[-1][1]:
            ps, pe, pv = merged[-1]
            merged[-1] = (ps, max(pe, e), max(pv, v))
        else:
            merged.append((s, e, v))
    return merged


def video_labels(
    labels: Any,
    defs: list[Any],
    scores: dict[str, dict[str, np.ndarray]],
    owners: np.ndarray,
    times: np.ndarray,
    ends: dict[int, int],
    step_ms: int = 2000,
    extra: dict[tuple[int, str], dict[str, list[tuple[int, float]]]] | None = None,
) -> tuple[list[tuple[int, str, dict[str, float], str]], dict[tuple[int, str], list[tuple[int, int, float]]]]:
    """Per video and label: values for Labels.record_many (max per source) and time spans.

    scores: score_labels() over the frames (rows of owners/times). extra: more per-frame points
    for a (video, label), e.g. NudeNet on every sampled frame.
    """
    records: list[tuple[int, str, dict[str, float], str]] = []
    spans: dict[tuple[int, str], list[tuple[int, int, float]]] = {}
    extra = extra or {}
    rows_of: dict[int, np.ndarray] = {int(m): np.flatnonzero(owners == m) for m in np.unique(owners)} if len(owners) else {}
    vids = set(rows_of) | {m for m, _ in extra}
    for d in defs:
        per = scores.get(d.key, {})
        for mid in vids:
            idx = rows_of.get(mid, np.zeros(0, np.int64))
            pts = {src: [(int(times[i]), float(arr[i])) for i in idx] for src, arr in per.items() if len(idx)}
            for src, more in extra.get((mid, d.key), {}).items():
                pts[src] = pts.get(src, []) + list(more)
            if not any(pts.values()):
                continue
            records.append((mid, d.key, {src: max(v for _, v in p) for src, p in pts.items() if p}, d.grp))
            sp = spans_for(labels, d.grp, pts, ends.get(mid, int(max(t for p in pts.values() for t, _ in p)) + step_ms), step_ms)
            if sp:
                spans[(mid, d.key)] = sp
    return records, spans


def store_spans(db: Any, labels: Any, spans: dict[tuple[int, str], list[tuple[int, int, float]]], replace: list[tuple[int, str]]) -> None:
    """Writes label spans, first clearing the (video, label) pairs in `replace`."""
    with db.tx() as c:
        c.executemany("DELETE FROM label_spans WHERE media_id=? AND label_id=?", [(m, labels.id(k)) for m, k in replace])
        c.executemany(
            "INSERT INTO label_spans(media_id, label_id, start_ms, end_ms, score) VALUES(?,?,?,?,?)",
            [(m, labels.id(k), s, e, round(v, 4)) for (m, k), sp in spans.items() for s, e, v in sp],
        )
