"""Photos where a person may be although their face isn't visible (turned away, too small, covered).

The person was recognised in photos or videos from the same directory within a few hours (the same
outing), and SigLIP sees a person in these, but no face in them is theirs. They are suggested for
you to confirm ("Is Rohit in these?"); a yes counts in Find like a recognised face, and nothing is
decided without you.
"""
from __future__ import annotations

import time
from typing import Any

import numpy as np

from ..context import Context
from .faceindex import topk_mean_sim

WINDOW_S = 3 * 3600  # the same outing: within 3 hours, in the same directory
MIN_PRESENCE = 0.4
UNCLEAR_Q = 0.45  # faces below this quality are too unclear to recognise
UNCLEAR_SIM = 0.10  # ...but still look a little like the person (strangers sit around 0 +- 0.1)
PERSON = ["a person seen from behind", "people at an event", "a person far away in a scene", "a group of people", "a person whose face is not visible"]
NOBODY = ["a photo with no people", "a landscape with nobody in it", "food on a table", "a close-up photo of an object", "a document or a screenshot"]


def _anchors(db: Any, pid: int) -> list[Any]:
    return db.q(
        """SELECT DISTINCT m.id, m.folder_id, m.rel_dir, m.taken_at FROM faces f JOIN media m ON m.id=f.media_id
           WHERE f.person_id=? AND f.state IN ('confirmed','auto','cluster') AND m.state='active' AND m.taken_at IS NOT NULL
           UNION
           SELECT m.id, m.folder_id, m.rel_dir, m.taken_at FROM media_people mp JOIN media m ON m.id=mp.media_id
           WHERE mp.person_id=? AND mp.state='confirmed' AND m.state='active' AND m.taken_at IS NOT NULL""",
        (pid, pid),
    )


def presence(c: Context, media_ids: list[int]) -> dict[int, float]:
    """How likely SigLIP thinks someone is in each photo (best frame for videos). Empty without the model."""
    ml = c.services.get("ml")
    index = c.services.get("semantic_index")
    model = ml.siglip() if ml is not None else None  # type: ignore[attr-defined]
    if model is None or index is None or not media_ids:
        return {}
    P, N = model.embed_texts(PERSON), model.embed_texts(NOBODY)

    def prob(E: np.ndarray) -> np.ndarray:
        logits = model.scale * np.concatenate([(E @ P.T).max(axis=1, keepdims=True), E @ N.T], axis=1)
        logits -= logits.max(axis=1, keepdims=True)
        ex = np.exp(logits)
        return ex[:, 0] / ex.sum(axis=1)

    out: dict[int, float] = {}
    ids, E = index.rows(media_ids)  # type: ignore[attr-defined]
    if len(ids):
        out.update(zip(ids.tolist(), prob(E).tolist()))
    owners, _, F = index.frame_matrix(media_ids)  # type: ignore[attr-defined]
    if len(owners):
        for mid, p in zip(owners.tolist(), prob(F).tolist()):
            out[mid] = max(out.get(mid, 0.0), p)
    return out


def suggestions(c: Context, pid: int, limit: int = 60, hide_private: bool = True) -> list[dict[str, Any]]:
    """Media from the same outings as the person's photos where they may be with their face hidden."""
    db = c.db
    anchors = _anchors(db, pid)
    if not anchors:
        return []
    by_dir: dict[tuple[int, str], list[float]] = {}
    for a in anchors:
        by_dir.setdefault((int(a["folder_id"]), a["rel_dir"]), []).append(float(a["taken_at"]))
    anchor_ids = {int(a["id"]) for a in anchors}
    cands: dict[int, float] = {}  # media id -> seconds to the nearest photo of the person
    for (folder, rel_dir), times in by_dir.items():
        times.sort()
        spans: list[list[float]] = []
        for t in times:  # windows around the person's photos, joined where they overlap
            if spans and t - WINDOW_S <= spans[-1][1]:
                spans[-1][1] = t + WINDOW_S
            else:
                spans.append([t - WINDOW_S, t + WINDOW_S])
        arr = np.array(times)
        for lo, hi in spans:
            for r in db.q(
                "SELECT id, taken_at FROM media WHERE folder_id=? AND rel_dir=? AND state='active' AND taken_at BETWEEN ? AND ?"
                + (" AND sens_state NOT IN ('private','review')" if hide_private else ""),
                (folder, rel_dir, lo, hi),
            ):
                mid = int(r["id"])
                if mid not in anchor_ids:
                    cands[mid] = float(np.abs(arr - float(r["taken_at"])).min())
    if not cands:
        return []
    mids = list(cands)
    seen: set[int] = set()
    for i in range(0, len(mids), 800):
        chunk = mids[i : i + 800]
        marks = ",".join("?" * len(chunk))
        seen |= {int(r[0]) for r in db.q(f"SELECT media_id FROM faces WHERE person_id=? AND media_id IN ({marks})", [pid, *chunk])}
        seen |= {int(r[0]) for r in db.q(
            f"SELECT f.media_id FROM face_votes v JOIN faces f ON f.id=v.face_id WHERE v.person_id=? AND v.vote<0 AND f.media_id IN ({marks})",
            [pid, *chunk])}
        seen |= {int(r[0]) for r in db.q(f"SELECT media_id FROM media_people WHERE person_id=? AND media_id IN ({marks})", [pid, *chunk])}
    mids = [m for m in mids if m not in seen]
    faces: list[Any] = []
    for i in range(0, len(mids), 800):
        chunk = mids[i : i + 800]
        faces += db.q(f"SELECT id, media_id, quality FROM faces WHERE media_id IN ({','.join('?' * len(chunk))})", chunk)
    with_face = {int(f["media_id"]) for f in faces}
    unclear = [f for f in faces if float(f["quality"]) < UNCLEAR_Q]
    # a face too unclear to recognise could be theirs, if it looks even a little like them; faces that
    # are all clear and someone else's mean the person isn't recognisable here, not that it's hidden
    score: dict[int, float] = {}
    if unclear:
        svc = c.services.get("people")
        E = svc.exemplars(pid) if svc is not None else np.zeros((0, 512), np.float32)  # type: ignore[attr-defined]
        if len(E):
            F = svc.index.vectors([int(f["id"]) for f in unclear])  # type: ignore[union-attr]
            sims = topk_mean_sim(F, E) if len(F) == len(unclear) else np.full(len(unclear), UNCLEAR_SIM, np.float32)
        else:
            sims = np.full(len(unclear), UNCLEAR_SIM, np.float32)
        for f, sim in zip(unclear, sims.tolist()):
            if sim >= UNCLEAR_SIM:
                m = int(f["media_id"])
                score[m] = max(score.get(m, -1.0), 0.5 + sim)
    # no face found at all, yet SigLIP sees someone (turned away, far off)
    no_face = [m for m in mids if m not in with_face]
    for m, p in presence(c, no_face).items():
        if p >= MIN_PRESENCE:
            score[m] = max(score.get(m, -1.0), p)
    mids = sorted(score, key=lambda m: (cands[m] // 1800, -score[m]))  # the same half hour first, likeliest first
    return [{"media_id": m, "minutes": int(cands[m] // 60), "presence": round(score[m], 3)} for m in mids[:limit]]


def answer(c: Context, pid: int, yes: list[int], no: list[int]) -> dict[str, int]:
    now = time.time()
    with c.db.tx() as cur:
        cur.executemany(
            """INSERT INTO media_people(media_id, person_id, state, at) VALUES(?,?,?,?)
               ON CONFLICT(media_id, person_id) DO UPDATE SET state=excluded.state, at=excluded.at""",
            [(m, pid, "confirmed", now) for m in yes] + [(m, pid, "rejected", now) for m in no],
        )
    return {"answered": len(yes) + len(no)}
