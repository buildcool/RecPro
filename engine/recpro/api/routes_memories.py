"""Trips, events and On this day (see memories.py)."""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from ..context import Context
from .deps import ctx
from .visibility import check_pending

router = APIRouter()


@router.get("/api/memories")
def memories(c: Context = Depends(ctx)) -> dict[str, Any]:
    """Home, and every trip and event, newest first."""
    from ..memories import analyse, public

    a = analyse(c)
    h = a["home"]
    return {
        "home": {k: h[k] for k in ("id", "name", "admin1", "country", "chosen")} if h else None,
        "trips": [public(t) for t in a["trips"]],
        "events": [public(e) for e in a["events"]],
    }


@router.get("/api/memories/on-this-day")
def on_this_day(date: str | None = Query(None, pattern=r"^\d{2}-\d{2}$"), c: Context = Depends(ctx)) -> dict[str, Any]:
    """What you took on this date (MM-DD, today if not given) in earlier years."""
    from ..memories import on_this_day as otd

    return otd(c, date)


@router.get("/api/memories/{key}")
def memory(key: str, c: Context = Depends(ctx)) -> dict[str, Any]:
    """One trip or event, its photos and videos day by day."""
    from ..memories import find, public
    from .routes_media import _blur_private, item_dict

    m = find(c, key)
    if m is None:
        raise HTTPException(404, "That trip or event isn't there any more.")
    ids = m["ids"]
    rows: dict[int, Any] = {}
    for i in range(0, len(ids), 900):
        chunk = ids[i : i + 900]
        for r in c.db.q(f"SELECT * FROM media WHERE id IN ({','.join('?' * len(chunk))})", chunk):
            rows[int(r["id"])] = r
    chk, blur = check_pending(c), _blur_private(c)
    days: list[dict[str, Any]] = []
    for mid in ids:
        r = rows.get(mid)
        if r is None:
            continue
        d = datetime.fromtimestamp(float(r["taken_at"])).date().isoformat()
        if not days or days[-1]["date"] != d:
            days.append({"date": d, "items": [], "towns": Counter()})
        days[-1]["items"].append(item_dict(r, chk, blur))
        if r["city_id"]:
            days[-1]["towns"][int(r["city_id"])] += 1
    town_ids = {t for d in days for t in d["towns"]}
    names = {int(r["id"]): r["name"] for r in c.db.q(f"SELECT id, name FROM places WHERE id IN ({','.join('?' * len(town_ids))})", list(town_ids))} if town_ids else {}
    out = []
    for d in days:
        top = [names[t] for t, _ in d.pop("towns").most_common(2) if t in names]
        out.append({**d, "place": " and ".join(top) if top else None})
    return {"memory": public(m), "days": out}
