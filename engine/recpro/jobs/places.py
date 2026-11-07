"""Places pass: the town, state and country of every photo and video with a GPS position.

Offline: the place table ships with RecPro (library/places.py). Cheap: a nearest-town lookup each.
A position that isn't real (0,0, out of range) or is far from any town gets no place.
"""
from __future__ import annotations

from typing import Any

from ..context import Context
from ..library import places

PLACES_V = 1


class PlacesStage:
    name = "places"
    label = "Finding places"
    column = "place_v"
    version = PLACES_V
    kinds = ("image", "video")
    batch_size = 1000
    order = "mtime DESC"

    def __init__(self, ctx: Context):
        self.ctx = ctx

    def available(self) -> bool:
        return places.available()

    def where(self) -> str:
        return "quick_v >= 1 AND gps_lat IS NOT NULL AND gps_lon IS NOT NULL"

    def process(self, rows: list[Any]) -> None:
        ok = [r for r in rows if places.valid(r["gps_lat"], r["gps_lon"])]
        g = places.gazetteer() if ok else None
        found = g.locate([float(r["gps_lat"]) for r in ok], [float(r["gps_lon"]) for r in ok]) if g else []
        at = {int(r["id"]): f for r, f in zip(ok, found)}
        seen: dict[int, places.Place] = {}
        updates: list[tuple[Any, ...]] = []
        for r in rows:
            f = at.get(int(r["id"]))
            if f is None or g is None:
                updates.append((PLACES_V, None, None, None, int(r["id"])))
                continue
            loc, city, km = f
            pl, pc = g.place(loc), g.place(city)
            seen[pl.id] = pl
            seen[pc.id] = pc
            updates.append((PLACES_V, pl.id, pc.id, round(km, 2), int(r["id"])))
        with self.ctx.db.tx() as c:
            c.executemany(
                """INSERT INTO places(id, name, admin1, country, cc, lat, lon, pop) VALUES(?,?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET name=excluded.name, admin1=excluded.admin1, country=excluded.country,
                   cc=excluded.cc, lat=excluded.lat, lon=excluded.lon, pop=excluded.pop""",
                [(p.id, p.name, p.admin1, p.country, p.cc, p.lat, p.lon, p.pop) for p in seen.values()],
            )
            c.executemany("UPDATE media SET place_v=?, place_id=?, city_id=?, place_km=? WHERE id=?", updates)
