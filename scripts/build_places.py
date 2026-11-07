"""Builds the offline place-name table RecPro uses to say where a photo was taken (development only).

    engine/.venv/Scripts/python -I scripts/build_places.py .cache/geonames engine/recpro/data/places.npz

Input, from https://download.geonames.org/export/dump/ (GeoNames, CC BY 4.0): cities1000.zip (every
town of 1,000+ people and every seat of a district), admin1CodesASCII.txt (state names) and
countryInfo.txt (country names). Output: a compressed table of name, state, country, position and
population, shipped with the engine. RecPro never looks a place up online.
"""
import datetime
import io
import sys
import zipfile
from pathlib import Path

import numpy as np

src, out = Path(sys.argv[1]), Path(sys.argv[2])

countries: dict[str, str] = {}
for line in (src / "countryInfo.txt").read_text(encoding="utf-8").splitlines():
    if line.startswith("#") or not line.strip():
        continue
    f = line.split("\t")
    countries[f[0]] = f[4]

admin1: dict[str, str] = {}
admin1_ascii: dict[str, str] = {}
for line in (src / "admin1CodesASCII.txt").read_text(encoding="utf-8").splitlines():
    f = line.split("\t")
    if len(f) >= 2 and f[1]:
        admin1[f[0]] = f[1]
        admin1_ascii[f[0]] = f[2] if len(f) > 2 and f[2] else f[1]

cc_list = sorted(countries)
cc_idx = {c: i for i, c in enumerate(cc_list)}
a1_list = sorted(admin1)
a1_idx = {c: i for i, c in enumerate(a1_list)}

rows = []
with zipfile.ZipFile(src / "cities1000.zip") as z, z.open("cities1000.txt") as fh:
    for raw in io.TextIOWrapper(fh, encoding="utf-8"):
        f = raw.rstrip("\n").split("\t")
        if len(f) < 15 or f[8] not in cc_idx or not f[1]:
            continue
        gid, name, plain, lat, lon, cc, a1, pop = int(f[0]), f[1], f[2], float(f[4]), float(f[5]), f[8], f[10], int(f[14] or 0)
        if any(ch in name + plain for ch in "\n\t"):
            continue
        rows.append((gid, name, lat, lon, cc_idx[cc], a1_idx.get(f"{cc}.{a1}", -1), pop, "" if plain == name else plain))

rows.sort(key=lambda r: r[0])
gid = np.array([r[0] for r in rows], np.int32)
lat = np.array([r[2] for r in rows], np.float32)
lon = np.array([r[3] for r in rows], np.float32)
cc = np.array([r[4] for r in rows], np.uint16)
a1 = np.array([r[5] for r in rows], np.int32)
pop = np.array([r[6] for r in rows], np.int32)


def blob(lines: list[str]) -> np.ndarray:
    return np.frombuffer("\n".join(lines).encode("utf-8"), np.uint8)


meta = f"GeoNames cities1000 (https://www.geonames.org, CC BY 4.0), built {datetime.date.today().isoformat()}, {len(rows)} places"
out.parent.mkdir(parents=True, exist_ok=True)
np.savez_compressed(
    out,
    gid=gid,
    lat=lat,
    lon=lon,
    cc=cc,
    a1=a1,
    pop=pop,
    names=blob([r[1] for r in rows]),
    ascii=blob([r[7] for r in rows]),  # the plain spelling, where it differs (Thane for Thāne)
    countries=blob([f"{c}\t{countries[c]}" for c in cc_list]),
    admin1=blob([admin1[k] for k in a1_list]),
    admin1_ascii=blob([admin1_ascii[k] for k in a1_list]),
    meta=blob([meta]),
)
print(meta)
print(f"written to {out.resolve()} ({out.stat().st_size / 1e6:.1f} MB)")
