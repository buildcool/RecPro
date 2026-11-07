"""Trips, events and "On this day": photos grouped the way you'd remember them.

Trips come from where the photos were taken. Home is the town you set, or the one with photos on
the most different days. A trip is a run of photos 50+ km from home, with no photo at home in
between and never 2½ days without one. It's named after where most of it happened: a town, or
the state or country when it moved around (a beach holiday across Goa is "Goa"). Camera photos
without a location taken during it (a second camera, location off) belong to it too.

Events are a few hours of camera photos (6 or more) where a celebration shows in a good part of
them: a wedding, a birthday, a festival, a party, a concert. Named after it, and the town.

On this day: what you took on today's date in earlier years. Screenshots, documents, IDs,
greetings, memes and blurry or dark shots are left out, and so are private items, even while
Private is open: the Home screen is no place for them.

Everything is worked out from the library when asked (cached for a minute): nothing to keep in
step, and your answers (a category you rejected, a photo you moved) count straight away.
"""
from __future__ import annotations

import threading
import time
from collections import Counter
from datetime import date, datetime
from typing import Any

import numpy as np

from .context import Context

AWAY_KM = 50.0
TRIP_GAP_S = 60 * 3600  # 2½ days without a photo away from home ends a trip
TRIP_MIN = 2
EVENT_GAP_S = 3 * 3600
EVENT_MIN = 6
EVENT_SHARE = 0.25
EVENT_LABELS = {
    "activity.wedding": "Wedding",
    "activity.birthday": "Birthday",
    "activity.festival": "Festival",
    "activity.party": "Party",
    "activity.concert": "Concert",
}
# not memories: label groups and keys whose photos On this day leaves out
NOT_MEMORY_GROUPS = ("screenshot", "document", "id", "quality")
NOT_MEMORY_KEYS = ("entertainment.good_morning", "entertainment.meme")
SURE = "ml.state!='rejected' AND (ml.tier='sure' OR ml.state='confirmed')"

_lock = threading.Lock()
_cache: dict[str, Any] = {}


def _hidden(c: Context) -> bool:
    from .api.visibility import private_hidden

    return private_hidden(c)


def _km(lat: Any, lon: Any, lat0: float, lon0: float) -> np.ndarray:
    la, lo = np.radians(np.asarray(lat, np.float64)), np.radians(np.asarray(lon, np.float64))
    la0, lo0 = np.radians(lat0), np.radians(lon0)
    h = np.sin((la - la0) / 2) ** 2 + np.cos(la) * np.cos(la0) * np.sin((lo - lo0) / 2) ** 2
    return 2 * 6371.0 * np.arcsin(np.sqrt(np.clip(h, 0.0, 1.0)))


def home(c: Context) -> dict[str, Any] | None:
    """Home: the town set in Places, or the one with photos on the most different days."""
    hid = c.settings.get("places.home_city_id")
    if hid:
        r = c.db.q1("SELECT * FROM places WHERE id=?", (hid,))
        if r is not None:
            return {**dict(r), "chosen": True}
    r = c.db.q1(
        """SELECT p.*, COUNT(DISTINCT date(m.taken_at, 'unixepoch', 'localtime')) AS days FROM media m JOIN places p ON p.id=m.city_id
           WHERE m.state='active' AND m.taken_at IS NOT NULL GROUP BY p.id ORDER BY days DESC, COUNT(*) DESC LIMIT 1"""
    )
    return {**dict(r), "chosen": False} if r is not None else None


def _best(rows: list[Any]) -> Any | None:
    """The photo to show for a group: never a private one; photos of people, sharp, then the middle one."""
    shown = [r for r in rows if r["sens_state"] not in ("private", "review")]
    if not shown:
        return None
    mid = shown[len(shown) // 2]["taken_at"] or 0
    return max(shown, key=lambda r: (r["kind"] == "image", (r["face_count"] or 0) > 0, min(r["sharpness"] or 0, 400), -abs((r["taken_at"] or 0) - mid)))


def _summary(kind: str, members: list[Any], name: str, **extra: Any) -> dict[str, Any]:
    cover = _best(members)
    start, end = float(members[0]["taken_at"]), float(members[-1]["taken_at"])
    days = (datetime.fromtimestamp(end).date() - datetime.fromtimestamp(start).date()).days + 1
    return {
        "key": f"{kind[0]}{int(members[0]['id'])}", "kind": kind, "name": name, "start": start, "end": end, "days": days,
        "n": len(members), "cover": cover["id"] if cover else None, "cover_v": cover["quick_v"] if cover else None,
        "ids": [int(r["id"]) for r in members], **extra,
    }


def _trip_name(towns: Counter, info: dict[int, Any], h: dict[str, Any]) -> str:
    total = sum(towns.values())
    top, n = towns.most_common(1)[0]
    if len(towns) == 1 or n / total >= 0.6:
        return info[top]["name"]
    states = {info[i]["admin1"] for i in towns}
    countries = {info[i]["country"] for i in towns}
    if len(states) == 1 and None not in states and states != {h.get("admin1")}:
        return str(next(iter(states)))
    if len(countries) == 1 and countries != {h.get("country")}:
        return str(next(iter(countries)))
    a, b = (info[i]["name"] for i, _ in towns.most_common(2))
    return f"{a} and {b}"


COLS = "m.id, m.taken_at, m.gps_lat, m.gps_lon, m.city_id, m.kind, m.sens_state, m.face_count, m.quick_v, m.sharpness"


def _trips(c: Context, hide: str, h: dict[str, Any] | None) -> list[dict[str, Any]]:
    if h is None:
        return []
    rows = c.db.q(f"SELECT {COLS} FROM media m WHERE m.state='active'{hide} AND m.city_id IS NOT NULL AND m.taken_at IS NOT NULL ORDER BY m.taken_at, m.id")
    if not rows:
        return []
    away = _km([r["gps_lat"] for r in rows], [r["gps_lon"] for r in rows], h["lat"], h["lon"]) >= AWAY_KM
    runs: list[list[Any]] = []
    cur: list[Any] = []
    for r, out in zip(rows, away):
        if not out:  # back home
            if cur:
                runs.append(cur)
            cur = []
            continue
        if cur and float(r["taken_at"]) - float(cur[-1]["taken_at"]) > TRIP_GAP_S:
            runs.append(cur)
            cur = []
        cur.append(r)
    if cur:
        runs.append(cur)
    runs = [run for run in runs if len(run) >= TRIP_MIN]
    if not runs:
        return []
    ids = {int(r["city_id"]) for run in runs for r in run}
    info = {int(r["id"]): r for r in c.db.q(f"SELECT * FROM places WHERE id IN ({','.join('?' * len(ids))})", list(ids))}
    trips = []
    for run in runs:
        towns = Counter(int(r["city_id"]) for r in run)
        # camera photos without a location, taken while away
        extra = c.db.q(
            f"""SELECT {COLS} FROM media m WHERE m.state='active'{hide} AND m.city_id IS NULL AND m.gps_lat IS NULL
                AND m.taken_src='exif' AND m.has_exif_camera=1 AND m.taken_at BETWEEN ? AND ?""",
            (run[0]["taken_at"], run[-1]["taken_at"]),
        )
        members = sorted(run + list(extra), key=lambda r: (r["taken_at"], r["id"]))
        trips.append(_summary(
            "trip", members, _trip_name(towns, info, h),
            towns=[{"id": i, "name": info[i]["name"], "admin1": info[i]["admin1"], "n": n} for i, n in towns.most_common()],
            country=info[towns.most_common(1)[0][0]]["country"],
        ))
    return trips


def _events(c: Context, hide: str) -> list[dict[str, Any]]:
    keys = list(EVENT_LABELS)
    sure: dict[int, set[str]] = {}
    for r in c.db.q(
        f"""SELECT ml.media_id, l.key FROM media_labels ml JOIN labels l ON l.id=ml.label_id
            WHERE l.key IN ({','.join('?' * len(keys))}) AND {SURE}""",
        keys,
    ):
        sure.setdefault(int(r["media_id"]), set()).add(r["key"])
    if not sure:
        return []
    rows = c.db.q(
        f"""SELECT {COLS} FROM media m WHERE m.state='active'{hide} AND m.taken_at IS NOT NULL
            AND ((m.kind='image' AND m.taken_src='exif' AND m.has_exif_camera=1) OR (m.kind='video' AND m.taken_src='video'))
            ORDER BY m.taken_at, m.id"""
    )
    sessions: list[list[Any]] = []
    for r in rows:
        if sessions and float(r["taken_at"]) - float(sessions[-1][-1]["taken_at"]) <= EVENT_GAP_S:
            sessions[-1].append(r)
        else:
            sessions.append([r])
    names: dict[int, str] = {}
    events = []
    for s in sessions:
        if len(s) < EVENT_MIN:
            continue
        counts = Counter(k for r in s for k in sure.get(int(r["id"]), ()))
        if not counts:
            continue
        key, n = counts.most_common(1)[0]
        if n < max(3, EVENT_SHARE * len(s)):
            continue
        town = Counter(int(r["city_id"]) for r in s if r["city_id"]).most_common(1)
        where = ""
        if town:
            tid = town[0][0]
            if tid not in names:
                names[tid] = c.db.scalar("SELECT name FROM places WHERE id=?", (tid,), default="")
            where = f" in {names[tid]}" if names[tid] else ""
        events.append(_summary("event", s, f"{EVENT_LABELS[key]}{where}", label=key))
    return events


def analyse(c: Context, max_age: float = 60.0) -> dict[str, Any]:
    """Trips and events, cached briefly per view (locked or not), library size and home."""
    hidden = _hidden(c)
    key = (hidden, c.db.scalar("SELECT COUNT(*) FROM media WHERE state='active'", default=0),
           c.db.scalar("SELECT COUNT(*) FROM media WHERE city_id IS NOT NULL", default=0), c.settings.get("places.home_city_id"))
    with _lock:
        hit = _cache.get("all")
        if hit and hit["key"] == key and time.time() - hit["at"] < max_age:
            return hit
        hide = " AND m.sens_state NOT IN ('private','review')" if hidden else ""
        h = home(c)
        trips = _trips(c, hide, h)
        events = _events(c, hide)
        trips.sort(key=lambda t: -t["start"])
        events.sort(key=lambda e: -e["start"])
        out = {"at": time.time(), "key": key, "home": h, "trips": trips, "events": events}
        _cache["all"] = out
        return out


def forget() -> None:
    with _lock:
        _cache.clear()


def public(m: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in m.items() if k != "ids"}


def find(c: Context, key: str) -> dict[str, Any] | None:
    a = analyse(c)
    return next((m for m in a["trips"] + a["events"] if m["key"] == key), None)


def on_this_day(c: Context, md: str | None = None, today: date | None = None) -> dict[str, Any]:
    """Photos and videos taken on this date (MM-DD) in earlier years, by year, newest year first."""
    from .api.routes_media import item_dict
    from .api.visibility import check_pending

    today = today or date.today()
    md = md or today.strftime("%m-%d")
    groups = "','".join(NOT_MEMORY_GROUPS)
    keys = "','".join(NOT_MEMORY_KEYS)
    rows = c.db.q(
        f"""SELECT m.* FROM media m WHERE m.state='active' AND m.sens_state NOT IN ('private','review')
              AND m.taken_at IS NOT NULL AND m.taken_src IN ('exif','video','filename')
              AND strftime('%m-%d', m.taken_at, 'unixepoch', 'localtime') = ?
              AND CAST(strftime('%Y', m.taken_at, 'unixepoch', 'localtime') AS INTEGER) < ?
              AND NOT EXISTS (SELECT 1 FROM media_labels ml JOIN labels l ON l.id=ml.label_id WHERE ml.media_id=m.id AND {SURE}
                              AND (l.grp IN ('{groups}') OR l.key IN ('{keys}')))
            ORDER BY m.taken_at, m.id""",
        (md, today.year),
    )
    chk = check_pending(c)
    by: dict[int, list[Any]] = {}
    for r in rows:
        by.setdefault(datetime.fromtimestamp(float(r["taken_at"])).year, []).append(r)
    years = []
    for y in sorted(by, reverse=True):
        items = by[y]
        cover = _best(items)
        years.append({
            "year": y, "years_ago": today.year - y, "n": len(items),
            "cover": cover["id"] if cover else None,
            "items": [item_dict(r, chk, True) for r in items],
        })
    return {"date": md, "years": years}
