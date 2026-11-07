"""Places: where photos were taken, from their GPS position, named offline (library/places.py).

Private items follow the usual rule: left out while Private is locked. A place's cover photo is
never a private one.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query

from ..context import Context
from .deps import ctx
from .visibility import check_pending, visible_sql

router = APIRouter()

# the photo shown for a place: never a private one; photos of people, then the latest
COVER_ORDER = "m2.kind='image' DESC, m2.face_count > 0 DESC, m2.taken_at DESC"


@router.get("/api/places")
def places(c: Context = Depends(ctx)) -> dict[str, Any]:
    """Every town with photos (by city), its state and country, how many, a cover and the dates."""
    vis = visible_sql(c, "m")
    rows = c.db.q(
        f"""SELECT p.id, p.name, p.admin1, p.country, p.cc, p.lat, p.lon, COUNT(*) AS n,
                   MIN(m.taken_at) AS first, MAX(m.taken_at) AS last,
                   (SELECT m2.id FROM media m2 WHERE m2.city_id=p.id AND m2.state='active'
                      AND m2.sens_state NOT IN ('private','review') ORDER BY {COVER_ORDER} LIMIT 1) AS cover
            FROM media m JOIN places p ON p.id=m.city_id WHERE {vis} GROUP BY p.id ORDER BY n DESC, p.name"""
    )
    located = sum(int(r["n"]) for r in rows)
    with_gps = c.db.scalar(f"SELECT COUNT(*) FROM media m WHERE {vis} AND m.gps_lat IS NOT NULL", default=0)
    out = [dict(r) for r in rows]
    covers = [r["cover"] for r in out if r["cover"] is not None]
    v = {int(r["id"]): r["quick_v"] for r in c.db.q(f"SELECT id, quick_v FROM media WHERE id IN ({','.join('?' * len(covers))})", covers)} if covers else {}
    for r in out:
        r["cover_v"] = v.get(r["cover"])
    return {"places": out, "located": located, "with_gps": with_gps}


@router.get("/api/places/clusters")
def clusters(
    cell: float = Query(5.0, gt=0, le=90),
    s: float = Query(-90, ge=-90, le=90),
    w: float = Query(-180, ge=-180, le=180),
    n: float = Query(90, ge=-90, le=90),
    e: float = Query(180, ge=-180, le=180),
    c: Context = Depends(ctx),
) -> dict[str, Any]:
    """The map's dots: photos grouped on a grid of `cell` degrees, within the area shown."""
    vis = visible_sql(c, "m")
    rows = c.db.q(
        f"""SELECT m.id, m.gps_lat AS lat, m.gps_lon AS lon, m.kind, m.sens_state, m.face_count, m.taken_at, m.city_id, m.place_id, m.quick_v
            FROM media m WHERE {vis} AND m.city_id IS NOT NULL
              AND m.gps_lat BETWEEN ? AND ? AND m.gps_lon BETWEEN ? AND ?""",
        (s, n, w, e),
    )
    if not rows:
        return {"clusters": []}
    lat = np.array([float(r["lat"]) for r in rows])
    lon = np.array([float(r["lon"]) for r in rows])
    key = np.floor(lat / cell).astype(np.int64) * 100_000 + np.floor(lon / cell).astype(np.int64)
    _, inv, counts = np.unique(key, return_inverse=True, return_counts=True)
    groups = np.split(np.argsort(inv, kind="stable"), np.cumsum(counts)[:-1])
    dots = []
    for g in groups:
        members = [rows[int(i)] for i in g]
        shown = [r for r in members if r["sens_state"] not in ("private", "review")]
        dots.append({
            "lat": float(lat[g].mean()), "lon": float(lon[g].mean()), "n": len(members),
            "best": max(shown, key=lambda r: (r["kind"] == "image", (r["face_count"] or 0) > 0, r["taken_at"] or 0)) if shown else None,
            "towns": Counter(int(r["city_id"]) for r in members),
            "spots": Counter(int(r["place_id"] or r["city_id"]) for r in members),
            "bounds": [float(lat[g].min()), float(lon[g].min()), float(lat[g].max()), float(lon[g].max())],
        })
    dots = _merge_close(dots, cell)
    ids = {t for d in dots for t in d["towns"]} | {t for d in dots for t in d["spots"]}
    names = {int(r["id"]): r["name"] for r in c.db.q(f"SELECT id, name FROM places WHERE id IN ({','.join('?' * len(ids))})", list(ids))}
    return {"clusters": [
        {
            "lat": d["lat"], "lon": d["lon"], "n": d["n"], "bounds": d["bounds"],
            "cover": d["best"]["id"] if d["best"] else None, "cover_v": d["best"]["quick_v"] if d["best"] else None,
            "name": names.get(d["towns"].most_common(1)[0][0]), "towns": len(d["towns"]),
            # the neighbourhood or village most of them were taken in: for labels when the map is close
            "locality": names.get(d["spots"].most_common(1)[0][0]),
        }
        for d in dots
    ]}


@router.get("/api/places/towns")
def towns(
    s: float = Query(..., ge=-90, le=90),
    w: float = Query(..., ge=-180, le=180),
    n: float = Query(..., ge=-90, le=90),
    e: float = Query(..., ge=-180, le=180),
    limit: int = Query(40, ge=1, le=200),
) -> dict[str, Any]:
    """The biggest towns in an area, to label the map. From the place table that ships with RecPro,
    not from anyone's photos."""
    from ..library.places import available, gazetteer

    if not available():
        return {"towns": []}
    g = gazetteer()
    idx = np.nonzero((g.lat >= s) & (g.lat <= n) & (g.lon >= w) & (g.lon <= e))[0]
    if len(idx) > limit:
        idx = idx[np.argsort(-g.pop[idx], kind="stable")[:limit]]
    out = [g.place(int(i)) for i in idx]
    return {"towns": [{"id": p.id, "name": p.name, "lat": p.lat, "lon": p.lon, "pop": p.pop} for p in sorted(out, key=lambda p: -p.pop)]}


def _merge_close(dots: list[dict[str, Any]], cell: float) -> list[dict[str, Any]]:
    """Dots from neighbouring grid squares can sit almost on top of each other on screen (Pune and
    Goa straddling a line): the bigger takes in any closer than a square (about two dots wide, so
    circles never overlap), measured as the map draws it (Mercator: latitude stretches away from
    the equator)."""
    near = cell
    def y(lat: float) -> float:
        return float(np.degrees(np.log(np.tan(np.pi / 4 + np.radians(max(-85.0, min(85.0, lat))) / 2))))

    dots = sorted(dots, key=lambda d: -d["n"])
    taken = [False] * len(dots)
    out = []
    for i, a in enumerate(dots):
        if taken[i]:
            continue
        group = [a]
        for j in range(i + 1, len(dots)):
            b = dots[j]
            if not taken[j] and abs(b["lon"] - a["lon"]) < near and abs(y(b["lat"]) - y(a["lat"])) < near:
                taken[j] = True
                group.append(b)
        if len(group) > 1:
            n = sum(d["n"] for d in group)
            towns: Counter[int] = Counter()
            spots: Counter[int] = Counter()
            for d in group:
                towns.update(d["towns"])
                spots.update(d.get("spots", {}))
            a = {
                "n": n,
                "lat": sum(d["lat"] * d["n"] for d in group) / n,
                "lon": sum(d["lon"] * d["n"] for d in group) / n,
                "best": a["best"] or next((d["best"] for d in group if d["best"]), None),
                "towns": towns,  # a town split by a grid line counts once
                "spots": spots,
                "bounds": [min(d["bounds"][0] for d in group), min(d["bounds"][1] for d in group),
                           max(d["bounds"][2] for d in group), max(d["bounds"][3] for d in group)],
            }
        out.append(a)
    return out


@router.get("/api/places/media")
def place_media(
    city: int | None = None,
    admin1: str | None = None,
    cc: str | None = None,
    s: float | None = None,
    w: float | None = None,
    n: float | None = None,
    e: float | None = None,
    offset: int = 0,
    limit: int = Query(200, ge=1, le=1000),
    c: Context = Depends(ctx),
) -> dict[str, Any]:
    """Photos and videos of one town, state or country, or of an area of the map; newest first."""
    from .routes_media import _blur_private, item_dict

    where = [visible_sql(c, "m"), "m.city_id IS NOT NULL"]
    params: list[Any] = []
    if city is not None:
        where.append("m.city_id=?")
        params.append(city)
    if cc:
        where.append("m.city_id IN (SELECT id FROM places WHERE cc=?)")
        params.append(cc)
    if admin1:
        where.append("m.city_id IN (SELECT id FROM places WHERE admin1=?)")
        params.append(admin1)
    box = (s, w, n, e)
    if any(v is not None for v in box):
        if any(v is None for v in box):
            raise HTTPException(400, "An area needs all four sides.")
        where.append("m.gps_lat BETWEEN ? AND ? AND m.gps_lon BETWEEN ? AND ?")
        params += [s, n, w, e]
    if len(where) == 2:
        raise HTTPException(400, "Say which place.")
    cond = " AND ".join(where)
    total = c.db.scalar(f"SELECT COUNT(*) FROM media m WHERE {cond}", params, default=0)
    rows = c.db.q(f"SELECT m.* FROM media m WHERE {cond} ORDER BY m.taken_at DESC, m.id DESC LIMIT ? OFFSET ?", [*params, limit, max(0, offset)])
    chk, blur = check_pending(c), _blur_private(c)
    return {"total": total, "items": [item_dict(r, chk, blur) for r in rows]}
