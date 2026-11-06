"""Find people across folders: tiered results (Sure / Please check), grouped by folder."""
from __future__ import annotations

import os
import time
from typing import Any

import numpy as np

from ..context import Context
from .faceindex import topk_mean_sim
from .people import MIN_Q_AUTO


def _scope_sql(c: Context, folder_ids: list[int] | None, kinds: list[str] | None, date_from: float | None, date_to: float | None) -> tuple[str, list[Any]]:
    where = ["m.state='active'"]
    params: list[Any] = []
    if folder_ids:
        where.append(f"m.folder_id IN ({','.join('?' * len(folder_ids))})")
        params += folder_ids
    if kinds:
        where.append(f"m.kind IN ({','.join('?' * len(kinds))})")
        params += kinds
    if date_from is not None:
        where.append("m.taken_at >= ?")
        params.append(date_from)
    if date_to is not None:
        where.append("m.taken_at <= ?")
        params.append(date_to)
    return " AND ".join(where), params


def search_people(
    c: Context,
    people_ids: list[int],
    mode: str = "any",
    exclude_ids: list[int] | None = None,
    ref_tokens: list[str] | None = None,
    folder_ids: list[int] | None = None,
    kinds: list[str] | None = None,
    date_from: float | None = None,
    date_to: float | None = None,
) -> dict[str, Any]:
    t0 = time.time()
    svc = c.services["people"]
    db = c.db
    sure_thr, check_thr = svc.thresholds()  # type: ignore[attr-defined]
    where, params = _scope_sql(c, folder_ids, kinds, date_from, date_to)

    faces = db.q(
        f"""SELECT f.id, f.media_id, f.person_id, f.state, f.quality FROM faces f JOIN media m ON m.id=f.media_id WHERE {where}""",
        params,
    )
    scanned = db.scalar(f"SELECT COUNT(*) FROM media m WHERE {where}", params, default=0)
    pending = db.scalar(
        f"SELECT COUNT(*) FROM media m WHERE {where} AND m.kind='image' AND m.width IS NOT NULL AND m.deep_v < 1", params, default=0
    )
    # Process what's being searched first
    if pending:
        ix = c.services.get("indexer")
        fids = folder_ids or [r["id"] for r in db.q("SELECT id FROM folders")]
        if ix is not None:
            ix.focus(fids)  # type: ignore[attr-defined]

    face_ids = [f["id"] for f in faces]
    by_face = {f["id"]: f for f in faces}
    targets: list[tuple[str, int | None, np.ndarray]] = []
    for pid in people_ids:
        targets.append((f"p{pid}", pid, svc.exemplars(pid)))  # type: ignore[attr-defined]
    if ref_tokens:
        refs = [svc.reference(t) for t in ref_tokens]  # type: ignore[attr-defined]
        refs = [r for r in refs if r is not None]
        if refs:
            targets.append(("ref", None, np.stack(refs)))
    excl = []
    for pid in exclude_ids or []:
        excl.append((f"x{pid}", pid, svc.exemplars(pid)))  # type: ignore[attr-defined]

    nov = svc._no_votes(face_ids) if face_ids else {}  # type: ignore[attr-defined]
    F = svc.index.vectors(face_ids) if face_ids else np.zeros((0, 512), np.float32)  # type: ignore[attr-defined]

    def tier_for(key_pid: int | None, E: np.ndarray) -> dict[int, tuple[str, float, int]]:
        """media_id -> (tier, score, face_id) for one target."""
        out: dict[int, tuple[str, float, int]] = {}
        if len(face_ids) == 0:
            return out
        s = topk_mean_sim(F, E) if len(E) else np.full(len(face_ids), -1.0, np.float32)
        for i, fid in enumerate(face_ids):
            f = by_face[fid]
            sc = float(s[i])
            st, owner = f["state"], f["person_id"]
            if key_pid is not None:
                if key_pid in nov.get(fid, ()):
                    continue
                if owner == key_pid and st == "confirmed":
                    sc, tier = 1.0, "sure"
                elif owner not in (None, key_pid) and st == "confirmed":
                    continue  # it's someone else, you said so
                elif owner == key_pid and st == "auto":
                    tier = "sure"
                elif owner == key_pid and st == "cluster":
                    tier = "sure"
                elif owner == key_pid and st == "suggested":
                    tier = "sure" if sc >= sure_thr and f["quality"] >= MIN_Q_AUTO else "check"
                else:
                    if sc >= sure_thr and f["quality"] >= MIN_Q_AUTO:
                        tier = "sure"
                    elif sc >= check_thr:
                        tier = "check"
                    else:
                        continue
            else:
                if sc >= sure_thr and f["quality"] >= MIN_Q_AUTO:
                    tier = "sure"
                elif sc >= check_thr:
                    tier = "check"
                else:
                    continue
            prev = out.get(f["media_id"])
            rank = (1 if tier == "sure" else 0, sc)
            if prev is None or rank > ((1 if prev[0] == "sure" else 0), prev[1]):
                out[f["media_id"]] = (tier, sc, fid)
        return out

    per_target = [(key, pid, tier_for(pid, E)) for key, pid, E in targets]
    combined: dict[int, dict[str, Any]] = {}
    if mode == "all" and per_target:
        common = set(per_target[0][2])
        for _, _, d in per_target[1:]:
            common &= set(d)
        for mid in common:
            tiers = [d[mid] for _, _, d in per_target]
            tier = "sure" if all(t[0] == "sure" for t in tiers) else "check"
            weakest = min(tiers, key=lambda t: (t[0] == "sure", t[1]))
            pid = next((p for (_, p, d) in per_target if d[mid] == weakest), None)
            combined[mid] = {"tier": tier, "score": weakest[1], "face_id": weakest[2], "person_id": pid}
    else:
        for _, pid, d in per_target:
            for mid, (tier, sc, fid) in d.items():
                prev = combined.get(mid)
                if prev is None or (tier == "sure" and prev["tier"] != "sure") or (tier == prev["tier"] and sc > prev["score"]):
                    combined[mid] = {"tier": tier, "score": sc, "face_id": fid, "person_id": pid}
    if mode == "alone" and combined:
        counts: dict[int, int] = {}
        for f in faces:
            if f["quality"] >= 0.25:
                counts[f["media_id"]] = counts.get(f["media_id"], 0) + 1
        combined = {mid: v for mid, v in combined.items() if counts.get(mid, 0) <= 1}
    for _, pid, E in excl:
        for mid, (tier, _, _) in tier_for(pid, E).items():
            if tier == "sure":
                combined.pop(mid, None)

    if not combined:
        return _empty(scanned, pending, time.time() - t0)

    mids = list(combined)
    rows: dict[int, Any] = {}
    for i in range(0, len(mids), 900):
        chunk = mids[i : i + 900]
        for r in db.q(
            f"""SELECT m.*, f.path AS folder_path FROM media m JOIN folders f ON f.id=m.folder_id WHERE m.id IN ({','.join('?' * len(chunk))})""",
            chunk,
        ):
            rows[r["id"]] = r
    priv_svc = c.services.get("private")
    show_private = bool(priv_svc and priv_svc.visible_everywhere())  # type: ignore[attr-defined]
    blur = True if priv_svc is None else bool(priv_svc.blur_enabled())  # type: ignore[attr-defined]
    names = {r["id"]: r["name"] for r in db.q("SELECT id, name FROM people")}
    from ..api.routes_media import item_dict
    from ..api.visibility import check_pending

    chk = check_pending(c)
    hidden_private = 0
    groups: dict[str, dict[str, Any]] = {}
    sure_items, check_items = [], []
    for mid, v in combined.items():
        r = rows.get(mid)
        if r is None:
            continue
        if r["sens_state"] == "private" and not show_private:
            hidden_private += 1
            continue
        folder = os.path.join(r["folder_path"], r["rel_dir"]) if r["rel_dir"] else r["folder_path"]
        it = item_dict(r, chk, blur)
        it.update(
            {
                "tier": v["tier"],
                "score": round(v["score"], 3),
                "face_id": v["face_id"],
                "person_id": v["person_id"],
                "person_name": names.get(v["person_id"]),
                "folder": folder,
            }
        )
        g = groups.setdefault(folder, {"folder": folder, "sure": 0, "check": 0})
        g[v["tier"]] += 1
        (sure_items if v["tier"] == "sure" else check_items).append(it)
    sure_items.sort(key=lambda x: (x["folder"].lower(), -(x["t"] or 0)))
    check_items.sort(key=lambda x: -x["score"])
    return {
        "sure": sure_items,
        "check": check_items,
        "groups": sorted(groups.values(), key=lambda g: g["folder"].lower()),
        "hidden_private": hidden_private,
        "scanned": scanned,
        "pending": pending,
        "took_ms": int((time.time() - t0) * 1000),
    }


def _empty(scanned: int, pending: int, took: float) -> dict[str, Any]:
    return {"sure": [], "check": [], "groups": [], "hidden_private": 0, "scanned": scanned, "pending": pending, "took_ms": int(took * 1000)}
