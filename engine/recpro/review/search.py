"""Find people (and pets) across folders: tiered results (Sure / Please check), grouped by folder."""
from __future__ import annotations

import os
import time
from typing import Any

import numpy as np

from ..context import Context
from ..ml.objects import OBJ_V
from .faceindex import topk_mean_sim


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
    where, params = _scope_sql(c, folder_ids, kinds, date_from, date_to)
    asked = [*people_ids, *(exclude_ids or [])]
    who = db.q(f"SELECT id, kind, species FROM people WHERE id IN ({','.join('?' * len(asked))})", asked) if asked else []
    kind_of = {int(r["id"]): r["kind"] for r in who}
    species_of = {int(r["id"]): r["species"] for r in who if r["species"]}  # a pet matches its own species only
    pets_asked = any(kind_of.get(int(p)) == "pet" for p in asked)

    # Each kind of sighting with what's needed to score it: a person's faces, a pet's animals.
    seen: dict[str, tuple[Any, list[int], dict[int, Any], np.ndarray, dict[int, set[int]], float, float]] = {}

    def sightings(kind: str):
        if kind not in seen:
            s_ = c.services["pets" if kind == "pet" else "people"]
            extra = ", f.species" if kind == "pet" else ""
            rows_ = db.q(  # an animal's face isn't a person's
                f"SELECT f.id, f.media_id, f.person_id, f.state, f.quality{extra} FROM {s_.T} f JOIN media m ON m.id=f.media_id WHERE {where} AND f.state != 'animal'",  # type: ignore[attr-defined]
                params,
            )
            ids_ = [r["id"] for r in rows_]
            vec = s_.index.vectors(ids_) if ids_ else np.zeros((0, s_.DIM), np.float32)  # type: ignore[attr-defined]
            sure_, check_ = s_.thresholds()  # type: ignore[attr-defined]
            seen[kind] = (s_, ids_, {r["id"]: r for r in rows_}, vec, s_._no_votes(ids_) if ids_ else {}, sure_, check_)  # type: ignore[attr-defined]
        return seen[kind]

    _, face_ids, by_face, _, _, _, _ = sightings("human")
    faces = list(by_face.values())
    scanned = db.scalar(f"SELECT COUNT(*) FROM media m WHERE {where}", params, default=0)
    pets_pending = f" OR m.obj_v < {OBJ_V}" if pets_asked else ""
    pending = db.scalar(
        f"""SELECT COUNT(*) FROM media m WHERE {where} AND m.width IS NOT NULL
            AND ((m.kind='image' AND (m.deep_v < 1{pets_pending})) OR (m.kind='video' AND m.video_v < 1))""",
        params,
        default=0,
    )
    # Process what's being searched first
    if pending:
        ix = c.services.get("indexer")
        fids = folder_ids or [r["id"] for r in db.q("SELECT id FROM folders")]
        if ix is not None:
            ix.focus(fids)  # type: ignore[attr-defined]

    def kind(pid: int | None) -> str:
        return kind_of.get(int(pid), "human") if pid is not None else "human"

    def exemplars(pid: int) -> np.ndarray:
        return sightings(kind(pid))[0].exemplars(pid)

    targets: list[tuple[str, int | None, np.ndarray]] = []
    for pid in people_ids:
        targets.append((f"p{pid}", pid, exemplars(pid)))
    if ref_tokens:
        refs = [svc.reference(t) for t in ref_tokens]  # type: ignore[attr-defined]
        refs = [r for r in refs if r is not None]
        if refs:
            targets.append(("ref", None, np.stack(refs)))
    excl = []
    for pid in exclude_ids or []:
        excl.append((f"x{pid}", pid, exemplars(pid)))

    def tier_for(key_pid: int | None, E: np.ndarray) -> dict[int, tuple[str, float, int]]:
        """media_id -> (tier, score, face_id) for one target (a pet's: its animals)."""
        out: dict[int, tuple[str, float, int]] = {}
        own, det_ids, by_det, F, nov, sure_thr, check_thr = sightings(kind(key_pid))
        min_q = own.MIN_Q_AUTO
        if len(det_ids) == 0:
            return out
        s = topk_mean_sim(F, E) if len(E) else np.full(len(det_ids), -1.0, np.float32)
        want = species_of.get(int(key_pid)) if key_pid is not None else None
        for i, fid in enumerate(det_ids):
            f = by_det[fid]
            if want and f["species"] != want:
                continue
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
                    tier = "sure" if sc >= sure_thr and f["quality"] >= min_q else "check"
                else:
                    if sc >= sure_thr and f["quality"] >= min_q:
                        tier = "sure"
                    elif sc >= check_thr:
                        tier = "check"
                    else:
                        continue
            else:
                if sc >= sure_thr and f["quality"] >= min_q:
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
    # photos where you said the person is, though their face isn't visible
    for _, pid, d in per_target:
        if pid is None:
            continue
        for r in db.q(
            f"""SELECT mp.media_id FROM media_people mp JOIN media m ON m.id=mp.media_id
                WHERE mp.person_id=? AND mp.state='confirmed' AND {where}""",
            [pid, *params],
        ):
            d.setdefault(int(r["media_id"]), ("sure", 1.0, None))  # type: ignore[arg-type]
    # every searched person's face in a media (a video shows when each is on screen)
    matched: dict[int, set[tuple[int, int | None]]] = {}
    for _, pid, d in per_target:
        if kind(pid) == "pet":
            continue  # pets are found in photos only
        for mid, (_, _, fid) in d.items():
            if fid is not None:
                matched.setdefault(mid, set()).add((fid, pid if pid is not None else by_face[fid]["person_id"]))
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
        for r in db.q("SELECT media_id FROM media_people WHERE person_id=? AND state='confirmed'", (pid,)):
            combined.pop(int(r["media_id"]), None)

    # "Rohit may also be in N photos where his face isn't visible": a pointer to Review
    hidden_more = 0
    if len(people_ids) == 1 and not ref_tokens and kind(people_ids[0]) == "human":
        from ..api.visibility import private_hidden
        from .hidden import suggestions

        hidden_more = len(suggestions(c, people_ids[0], limit=200, hide_private=private_hidden(c)))
    if not combined:
        return {**_empty(scanned, pending, time.time() - t0), "hidden_more": hidden_more}

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
    from .moments import people_moments

    moments = people_moments(db, {m: matched.get(m, set()) for m in mids if rows.get(m) is not None and rows[m]["kind"] == "video"}, names)

    chk = check_pending(c)
    hidden_private = 0
    groups: dict[str, dict[str, Any]] = {}
    sure_items, check_items = [], []
    for mid, v in combined.items():
        r = rows.get(mid)
        if r is None:
            continue
        if r["sens_state"] in ("private", "review") and not show_private:
            hidden_private += 1
            continue
        folder = os.path.join(r["folder_path"], r["rel_dir"]) if r["rel_dir"] else r["folder_path"]
        it = item_dict(r, chk, blur)
        it.update(
            {
                "tier": v["tier"],
                "score": round(v["score"], 3),
                "face_id": v["face_id"],
                "det": "animal" if kind(v["person_id"]) == "pet" else "face",  # which crop face_id is
                "person_id": v["person_id"],
                "person_name": names.get(v["person_id"]),
                "folder": folder,
                **moments.get(mid, {}),
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
        "hidden_more": hidden_more,
        "scanned": scanned,
        "pending": pending,
        "took_ms": int((time.time() - t0) * 1000),
    }


def _empty(scanned: int, pending: int, took: float) -> dict[str, Any]:
    return {"sure": [], "check": [], "groups": [], "hidden_private": 0, "scanned": scanned, "pending": pending, "took_ms": int(took * 1000)}
