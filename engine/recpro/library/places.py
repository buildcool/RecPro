"""Offline place names: the town, state and country a GPS position is in.

The table ships with RecPro (GeoNames' 170,000 towns of 1,000+ people, CC BY 4.0, made by
scripts/build_places.py), so no position is ever sent anywhere to be looked up.

Each position gets two names. The locality is the nearest town or neighbourhood. The city is the
biggest place close by in the same state: a photo anywhere in Pune is "Pune" even where a
neighbourhood is nearer, while a beach town 13 km from Panaji keeps its own name.
"""
from __future__ import annotations

import threading
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np

DATA = Path(__file__).resolve().parent.parent / "data" / "places.npz"
EARTH_KM = 6371.0
CITY_KM = 30.0  # how far around a city is looked for
NEAR_K = 64  # places looked at within that distance
MAX_KM = 150.0  # farther than this from any town (at sea, in the air) gets no place
# Where the local script isn't Latin, GeoNames' names are scholarly transliterations ("Thāne",
# "Manāli"); people there write them plainly ("Thane"), so those are shown plainly.
PLAIN_SPELLING = frozenset(
    "IN PK BD NP LK BT MV AF IR IQ SA AE OM QA KW BH YE JO SY LB IL PS EG SD LY RU UA BY BG RS MK GR GE AM "
    "KZ KG TJ UZ TM MN CN TW HK MO JP KR KP TH LA KH MM ET ER".split()
)


def fold(s: str) -> str:
    """For matching names as people type them: no accents, no case ("zurich" finds Zürich)."""
    return "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch)).casefold().strip()


@dataclass(frozen=True)
class Place:
    id: int  # GeoNames id, stable across updates of the table
    name: str
    admin1: str | None  # state or province
    country: str
    cc: str  # ISO country code
    lat: float
    lon: float
    pop: int


def valid(lat: float | None, lon: float | None) -> bool:
    """A real position: in range, and not 0,0 (what some cameras write when they have none)."""
    if lat is None or lon is None:
        return False
    try:
        la, lo = float(lat), float(lon)
    except (TypeError, ValueError):
        return False
    if not (-90.0 <= la <= 90.0 and -180.0 <= lo <= 180.0) or la != la or lo != lo:
        return False
    return not (abs(la) < 1e-6 and abs(lo) < 1e-6)


def _xyz(lat: Iterable[float], lon: Iterable[float]) -> np.ndarray:
    la = np.radians(np.asarray(lat, np.float64))
    lo = np.radians(np.asarray(lon, np.float64))
    return np.stack([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)], axis=-1)


def _km(chord: np.ndarray) -> np.ndarray:
    return 2.0 * np.arcsin(np.clip(np.asarray(chord, np.float64) / 2.0, 0.0, 1.0)) * EARTH_KM


def _chord(km: float) -> float:
    return float(2.0 * np.sin(km / EARTH_KM / 2.0))


class Gazetteer:
    def __init__(self, path: Path = DATA):
        from scipy.spatial import cKDTree

        with np.load(path) as d:
            self.gid = d["gid"]
            self.lat = d["lat"]
            self.lon = d["lon"]
            self.cc = d["cc"]
            self.a1 = d["a1"]
            self.pop = d["pop"]
            self.names = bytes(d["names"]).decode("utf-8").split("\n")
            self.plain = bytes(d["ascii"]).decode("utf-8").split("\n")
            self.countries = [tuple(x.split("\t", 1)) for x in bytes(d["countries"]).decode("utf-8").split("\n")]
            self.admin1 = bytes(d["admin1"]).decode("utf-8").split("\n")
            self.admin1_plain = bytes(d["admin1_ascii"]).decode("utf-8").split("\n")
            self.meta = bytes(d["meta"]).decode("utf-8")
        self.tree = cKDTree(_xyz(self.lat, self.lon))
        self.weight = np.maximum(self.pop, 1000).astype(np.float64)

    def __len__(self) -> int:
        return len(self.gid)

    def place(self, i: int) -> Place:
        a = int(self.a1[i])
        cc, country = self.countries[int(self.cc[i])]
        plain = cc in PLAIN_SPELLING
        name = (self.plain[i] or self.names[i]) if plain else self.names[i]
        admin1 = (self.admin1_plain[a] if plain else self.admin1[a]) if a >= 0 else None
        return Place(int(self.gid[i]), name, admin1, country, cc, float(self.lat[i]), float(self.lon[i]), int(self.pop[i]))

    def locate(self, lats: list[float], lons: list[float]) -> list[tuple[int, int, float] | None]:
        """For each position: (locality, city, km to the locality) as table rows, or None far from any town."""
        if not lats:
            return []
        q = _xyz(lats, lons)
        d1, i1 = self.tree.query(q, k=1)
        dk, ik = self.tree.query(q, k=NEAR_K, distance_upper_bound=_chord(CITY_KM))
        n = len(self.gid)
        out: list[tuple[int, int, float] | None] = []
        for row in range(len(q)):
            loc = int(i1[row])
            km = float(_km(d1[row]))
            if km > MAX_KM:
                out.append(None)
                continue
            near = ik[row][ik[row] < n]
            dist = _km(dk[row][ik[row] < n])
            # the city is in the same country and state as the locality: a photo taken just across a
            # border isn't in the big city on the other side
            same = (self.cc[near] == self.cc[loc]) & (self.a1[near] == self.a1[loc])
            city = loc
            if same.any():
                near, dist = near[same], dist[same]
                score = self.weight[near] / (1.0 + dist / 2.0) ** 2
                city = int(near[int(np.argmax(score))])
            out.append((loc, city, km))
        return out


_lock = threading.Lock()
_gaz: Gazetteer | None = None


def available() -> bool:
    return DATA.exists()


def gazetteer() -> Gazetteer:
    """The table, loaded once (under a second) when the first photo with GPS needs it."""
    global _gaz
    with _lock:
        if _gaz is None:
            _gaz = Gazetteer()
        return _gaz
