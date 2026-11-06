"""Where in a video something is: people's on-screen spans and categories' spans."""
from __future__ import annotations

from typing import Any


def face_spans(db: Any, face_ids: list[int]) -> dict[int, list[tuple[int, int]]]:
    out: dict[int, list[tuple[int, int]]] = {}
    for i in range(0, len(face_ids), 900):
        chunk = face_ids[i : i + 900]
        for r in db.q(
            f"SELECT face_id, start_ms, end_ms FROM face_spans WHERE face_id IN ({','.join('?' * len(chunk))}) ORDER BY start_ms",
            chunk,
        ):
            out.setdefault(int(r["face_id"]), []).append((int(r["start_ms"]), int(r["end_ms"])))
    return out


def label_spans(db: Any, media_ids: list[int], label_ids: list[int]) -> dict[int, list[dict[str, Any]]]:
    out: dict[int, list[dict[str, Any]]] = {}
    if not media_ids or not label_ids:
        return out
    for i in range(0, len(media_ids), 800):
        chunk = media_ids[i : i + 800]
        for r in db.q(
            f"""SELECT ls.media_id, ls.label_id, l.name, ls.start_ms, ls.end_ms FROM label_spans ls JOIN labels l ON l.id=ls.label_id
                WHERE ls.media_id IN ({','.join('?' * len(chunk))}) AND ls.label_id IN ({','.join('?' * len(label_ids))}) ORDER BY ls.start_ms""",
            [*chunk, *label_ids],
        ):
            out.setdefault(int(r["media_id"]), []).append(
                {"label_id": r["label_id"], "name": r["name"], "start_ms": r["start_ms"], "end_ms": r["end_ms"]}
            )
    return out


def people_moments(db: Any, matched: dict[int, set[tuple[int, int | None]]], names: dict[int, str]) -> dict[int, dict[str, Any]]:
    """media -> {"spans": [...], "at_ms": first start} for the matched (face, person) pairs of videos."""
    fids = sorted({fid for pairs in matched.values() for fid, _ in pairs})
    spans = face_spans(db, fids)
    out: dict[int, dict[str, Any]] = {}
    for mid, pairs in matched.items():
        sp = [
            {"person_id": pid, "name": names.get(pid) if pid else None, "start_ms": s, "end_ms": e}
            for fid, pid in pairs
            for s, e in spans.get(fid, [])
        ]
        if sp:
            sp.sort(key=lambda x: x["start_ms"])
            out[mid] = {"spans": sp, "at_ms": sp[0]["start_ms"]}
    return out
