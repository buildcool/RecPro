"""Cleanup: duplicates, copies and bursts (with the best shot picked), blurry or dark photos, and
WhatsApp forwards. Nothing is removed here: the Cleanup screen sends what you choose to the RecPro
Bin through Ops.bin_media, one operation in History that Undo reverses.

* Exact duplicates: the same bytes (grouped by the quick hash; the full hash is checked again
  before anything moves).
* Copies: the same picture at another size or compression (perceptual hash within 6 bits, and
  SigLIP agrees). The original camera file at the largest size is kept.
* Bursts: shots of the same moment (same directory, under a minute apart, SigLIP nearly the same).
  The sharpest, best-exposed shot with the clearest faces is kept.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
import threading
import time
from typing import Any

import numpy as np

from .context import Context

COPY_HAMMING = 6
COPY_COS = 0.85  # the hash already says "same picture"; SigLIP only rules out flat images
BURST_GAP_S = 60
BURST_COS = 0.95  # shots of one moment; different photos of one person at one event sit lower
WA_NAME = re.compile(r"^(IMG|VID|AUD|PTT|STK)-\d{8}-WA\d{3,}", re.I)
_cache: dict[str, Any] = {}
_lock = threading.Lock()


def _media(c: Context, where: str = "", params: tuple = ()) -> list[Any]:
    from .api.visibility import private_hidden

    hide = " AND sens_state NOT IN ('private','review')" if private_hidden(c) else ""
    return c.db.q(f"SELECT * FROM media WHERE state='active'{hide}{(' AND ' + where) if where else ''}", params)


def is_forward(row: Any) -> bool:
    """WhatsApp's own names (IMG-20240512-WA0012.jpg) or its folders ("WhatsApp Images", "WhatsApp
    Video"), and no camera behind it."""
    if row["has_exif_camera"]:
        return False
    if WA_NAME.match(row["name"] or ""):
        return True
    return any(part.lower().startswith("whatsapp") for part in Path(row["path"] or "").parent.parts)


def _hamming(a: int, b: int) -> int:
    return bin((a ^ b) & 0xFFFFFFFFFFFFFFFF).count("1")


def _exposure_sharpness(c: Context, row: Any) -> tuple[float, float]:
    """(sharpness = variance of the Laplacian, exposure 0..1), from the quality pass or the thumbnail."""
    sharp, bright = row["sharpness"], row["brightness"]
    if sharp is None or bright is None:
        from .jobs.quality import measure
        from .library.imaging import shard

        m = measure(shard(c.paths.thumbs, int(row["id"])))
        if m is None:
            return 0.0, 0.5
        bright, _, sharp = m
    return float(sharp), max(0.0, 1.0 - abs(float(bright) - 125.0) / 125.0)


def _best(c: Context, members: list[Any], kind: str) -> list[dict[str, Any]]:
    """Members with a score and the one to keep marked."""
    out = []
    if kind == "copies":
        # the original camera file at the largest size, unless it's clearly blurrier (an upscaled or
        # smoothed copy can be larger and still worse)
        sharp = {int(r["id"]): _exposure_sharpness(c, r)[0] for r in members}
        top = max(sharp.values(), default=0.0) or 1.0
        for r in members:
            pixels = (r["width"] or 0) * (r["height"] or 0)
            score = (2.0 if r["has_exif_camera"] else 0.0) - (1.0 if is_forward(r) else 0.0) + pixels / 1e8 + (r["size"] or 0) / 1e10
            # only a big drop counts (under half the sharpest copy), and then it outweighs being the original
            score -= 4.0 * max(0.0, 0.5 - sharp[int(r["id"])] / top) / 0.5
            out.append({"row": r, "score": score, "sharpness": round(sharp[int(r["id"])], 1)})
    else:
        faces: dict[int, float] = {}
        ids = [int(r["id"]) for r in members]
        for f in c.db.q(f"SELECT media_id, MAX(quality) q FROM faces WHERE media_id IN ({','.join('?' * len(ids))}) GROUP BY media_id", ids):
            faces[int(f["media_id"])] = float(f["q"] or 0)
        metrics = {int(r["id"]): _exposure_sharpness(c, r) for r in members}
        top = max((m[0] for m in metrics.values()), default=1.0) or 1.0
        for r in members:
            sharp, expo = metrics[int(r["id"])]
            score = 0.5 * (sharp / top) + 0.2 * expo + 0.3 * faces.get(int(r["id"]), 0.0)
            out.append({"row": r, "score": score, "sharpness": round(sharp, 1), "exposure": round(expo, 3)})
    keep = max(out, key=lambda x: x["score"])
    for x in out:
        x["keep"] = x is keep
    return out


def exact_groups(c: Context) -> list[list[Any]]:
    rows = _media(c, "quick_hash IN (SELECT quick_hash FROM media WHERE state='active' AND quick_hash IS NOT NULL GROUP BY quick_hash HAVING COUNT(*) > 1)")
    by: dict[str, list[Any]] = {}
    for r in rows:
        by.setdefault(r["quick_hash"], []).append(r)
    return [g for g in by.values() if len(g) > 1]


def copy_groups(c: Context, exclude: set[int]) -> list[list[Any]]:
    """Same picture, other size or compression: perceptual hash buckets, confirmed by SigLIP."""
    rows = [r for r in _media(c, "phash IS NOT NULL AND kind='image'") if int(r["id"]) not in exclude]
    buckets: dict[tuple[int, int], list[int]] = {}
    for i, r in enumerate(rows):
        h = int(r["phash"]) & 0xFFFFFFFFFFFFFFFF
        for band in range(4):  # 4 bands of 16 bits: near hashes share at least one band
            buckets.setdefault((band, (h >> (16 * band)) & 0xFFFF), []).append(i)
    parent = list(range(len(rows)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    index = c.services.get("semantic_index")
    pairs = set()
    for idx in buckets.values():
        if len(idx) < 2 or len(idx) > 200:  # a huge bucket is a flat pattern (black frames), not copies
            continue
        for a in range(len(idx)):
            for b in range(a + 1, len(idx)):
                i, j = idx[a], idx[b]
                if (i, j) in pairs or _hamming(int(rows[i]["phash"]), int(rows[j]["phash"])) > COPY_HAMMING:
                    continue
                ri, rj = rows[i], rows[j]
                if ri["has_exif_camera"] and rj["has_exif_camera"] and abs(float(ri["taken_at"] or 0) - float(rj["taken_at"] or 0)) >= 1:
                    continue  # two camera shots taken at different moments: a burst, not a copy
                pairs.add((i, j))
    if not pairs:
        return []
    ids_needed = sorted({int(rows[k]["id"]) for p in pairs for k in p})
    vec: dict[int, np.ndarray] = {}
    if index is not None:
        got, E = index.rows(ids_needed)  # type: ignore[attr-defined]
        vec = {int(m): e for m, e in zip(got.tolist(), E)}
    for i, j in pairs:
        a, b = int(rows[i]["id"]), int(rows[j]["id"])
        if a in vec and b in vec and float(vec[a] @ vec[b]) < COPY_COS:
            continue  # look alike to the hash only (plain backgrounds)
        parent[find(i)] = find(j)
    groups: dict[int, list[Any]] = {}
    for k in {k for p in pairs for k in p}:
        groups.setdefault(find(k), []).append(rows[k])
    return [g for g in groups.values() if len(g) > 1]


def burst_groups(c: Context, exclude: set[int]) -> list[list[Any]]:
    """Shots of the same moment: same directory, < 1 minute apart, SigLIP nearly the same."""
    index = c.services.get("semantic_index")
    if index is None:
        return []
    rows = [r for r in _media(c, "taken_at IS NOT NULL AND kind='image'") if int(r["id"]) not in exclude]
    rows.sort(key=lambda r: (r["folder_id"], r["rel_dir"], r["taken_at"]))
    got, E = index.rows([int(r["id"]) for r in rows])  # type: ignore[attr-defined]
    vec = {int(m): e for m, e in zip(got.tolist(), E)}
    groups: list[list[Any]] = []
    cur: list[Any] = []
    for r in rows:
        prev = cur[-1] if cur else None
        same = (
            prev is not None
            and (prev["folder_id"], prev["rel_dir"]) == (r["folder_id"], r["rel_dir"])
            and float(r["taken_at"]) - float(prev["taken_at"]) <= BURST_GAP_S
            and int(r["id"]) in vec
            and int(prev["id"]) in vec
            and float(vec[int(r["id"])] @ vec[int(prev["id"])]) >= BURST_COS
        )
        if same:
            cur.append(r)
        else:
            if len(cur) > 1:
                groups.append(cur)
            cur = [r]
    if len(cur) > 1:
        groups.append(cur)
    return groups


def _labelled(c: Context, keys: tuple[str, ...]) -> list[Any]:
    from .api.visibility import private_hidden

    hide = " AND m.sens_state NOT IN ('private','review')" if private_hidden(c) else ""
    return c.db.q(
        f"""SELECT DISTINCT m.*, ml.score AS lscore FROM media m JOIN media_labels ml ON ml.media_id=m.id JOIN labels l ON l.id=ml.label_id
            WHERE m.state='active'{hide} AND l.key IN ({','.join('?' * len(keys))}) AND ml.state!='rejected'
            AND (ml.tier='sure' OR ml.state='confirmed') ORDER BY ml.score DESC""",
        keys,
    )


def analyse(c: Context, max_age: float = 60.0) -> dict[str, Any]:
    """All cleanup groups, cached briefly (the library changes while it's indexed)."""
    with _lock:
        hit = _cache.get("all")
        if hit and time.time() - hit["at"] < max_age:
            return hit
        from .jobs.quality import too_dark

        exact = exact_groups(c)
        # an exact duplicate's extra files stay out of the other groups; one file stands for them
        extra = {int(r["id"]) for g in exact for r in sorted(g, key=lambda r: int(r["id"]))[1:]}
        copies = copy_groups(c, extra)
        taken = extra | {int(r["id"]) for g in copies for r in g}
        bursts = burst_groups(c, taken)
        # too dark: a fact from the pixels (SigLIP calls dark photos "blurry" as often as "dark")
        dark = [r for r in _media(c, "kind='image' AND brightness IS NOT NULL") if too_dark(r["brightness"], r["highlights"])]
        dark_ids = {int(r["id"]) for r in dark}
        blurry = [r for r in _labelled(c, ("quality.blurry", "quality.accidental")) if int(r["id"]) not in dark_ids]
        forwards = [r for r in _media(c, "has_exif_camera=0") if is_forward(r)]
        greet = {int(r["id"]) for r in _labelled(c, ("entertainment.good_morning", "entertainment.meme"))}
        forwards.sort(key=lambda r: (int(r["id"]) not in greet, -(r["taken_at"] or 0)))
        out = {"at": time.time(), "exact": exact, "copies": copies, "bursts": bursts, "blurry": blurry, "dark": dark,
               "forwards": forwards, "greetings": greet}
        _cache["all"] = out
        return out


def forget() -> None:
    with _lock:
        _cache.clear()


def summary(c: Context) -> dict[str, Any]:
    a = analyse(c)

    def groups(gs: list[list[Any]], kind: str) -> dict[str, Any]:
        extra = 0
        files = 0
        for g in gs:
            files += len(g) - 1
            sizes = sorted((int(r["size"] or 0) for r in g), reverse=True)
            extra += sum(sizes[1:]) if kind == "exact" else sum(sizes) - max(sizes)
        return {"groups": len(gs), "files": files, "bytes": extra}

    def flat(rows: list[Any]) -> dict[str, Any]:
        return {"files": len(rows), "bytes": sum(int(r["size"] or 0) for r in rows)}

    return {
        "exact": groups(a["exact"], "exact"),
        "copies": groups(a["copies"], "copies"),
        "bursts": groups(a["bursts"], "bursts"),
        "blurry": flat(a["blurry"]),
        "dark": flat(a["dark"]),
        "forwards": {**flat(a["forwards"]), "greetings": sum(1 for r in a["forwards"] if int(r["id"]) in a["greetings"])},
    }


def listing(c: Context, kind: str, offset: int = 0, limit: int = 50) -> dict[str, Any]:
    from .api.routes_media import item_dict
    from .api.visibility import check_pending

    a = analyse(c)
    priv = c.services.get("private")
    blur = True if priv is None else bool(priv.blur_enabled())  # type: ignore[attr-defined]
    chk = check_pending(c)

    def item(r: Any, **kw: Any) -> dict[str, Any]:
        folder = c.db.scalar("SELECT path FROM folders WHERE id=?", (r["folder_id"],), default="")
        return {**item_dict(r, chk, blur), "path": r["path"], "name": r["name"], "size": r["size"],
                "folder": os.path.join(folder, r["rel_dir"]) if r["rel_dir"] else folder, **kw}

    if kind in ("exact", "copies", "bursts"):
        gs = a[kind]
        page = gs[offset : offset + limit]
        out = []
        for g in page:
            if kind == "exact":
                ranked = _best(c, g, "copies")  # keep the original-looking one
            else:
                ranked = _best(c, g, kind)
            out.append([item(x["row"], keep=x["keep"], score=round(x["score"], 3), sharpness=x.get("sharpness")) for x in ranked])
        return {"kind": kind, "total": len(gs), "groups": out}
    rows = a[kind]
    return {"kind": kind, "total": len(rows), "items": [item(r, greeting=int(r["id"]) in a["greetings"]) if kind == "forwards" else item(r)
                                                         for r in rows[offset : offset + limit]]}
