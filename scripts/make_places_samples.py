"""Places and trips test photos made from public LFW photos (development only).

    engine/.venv/Scripts/python -I scripts/make_places_samples.py .testdata/lfw/lfw.tgz .testdata/places-samples .testdata/lfw-lib

Every photo has camera EXIF, a capture time and a GPS position, and sits in one Camera/ folder the
way a phone keeps them, so places and trips have to come from the photos, not from folder names:
  home in Pune on ordinary days over 18 months (one at Sinhagad fort, 25 km out: a day out, not a trip)
  Goa, 4 days in Jan 2023 · Jaipur, Oct 2023 · Paris and Versailles, Jun 2024 · a Lonavala weekend, Jul 2024
Odd/ has a position of 0,0 (what some cameras write when they have none) and one far out at sea:
neither gets a place. Two photos at home fall on today's date, one and three years back, for "On
this day". LFW photos already in the third folder are left out so nothing is a duplicate.
truth.json records the town each photo should be in and the trips.
"""
import io
import json
import shutil
import sys
import tarfile
from datetime import date
from pathlib import Path

from PIL import Image
from PIL.TiffImagePlugin import IFDRational

tgz, out = Path(sys.argv[1]), Path(sys.argv[2])
avoid = {p.name for p in Path(sys.argv[3]).rglob("*.jpg")} if len(sys.argv) > 3 else set()

HOME = [  # (taken, lat, lon, town expected)
    ("2023:03:05 18:15:00", 18.5308, 73.8475, "Pune"),
    ("2023:04:16 10:10:00", 18.5362, 73.8940, "Pune"),
    ("2023:06:11 19:30:00", 18.5074, 73.8077, "Pune"),
    ("2023:08:20 12:00:00", 18.3664, 73.7559, None),  # Sinhagad fort: whatever village is nearest
    ("2023:11:12 20:00:00", 18.5204, 73.8567, "Pune"),
    ("2024:01:26 09:00:00", 18.5204, 73.8567, "Pune"),
    ("2024:03:24 17:00:00", 18.5362, 73.8940, "Pune"),
    ("2024:05:12 11:00:00", 18.5308, 73.8475, "Pune"),
    ("2024:08:15 08:30:00", 18.5074, 73.8077, "Pune"),
]
TRIPS = {
    "Goa": [
        ("2023:01:14 16:30:00", 15.5439, 73.7553, "Calangute"),
        ("2023:01:14 18:15:00", 15.5445, 73.7540, "Calangute"),
        ("2023:01:15 11:00:00", 15.5733, 73.7407, "Anjuna"),
        ("2023:01:15 17:30:00", 15.5810, 73.7380, None),
        ("2023:01:16 10:30:00", 15.4909, 73.8278, "Panjim"),
        ("2023:01:16 15:00:00", 15.5009, 73.9116, None),
        ("2023:01:17 12:00:00", 15.0100, 74.0232, None),
        ("2023:01:17 18:00:00", 15.0089, 74.0235, None),
    ],
    "Jaipur": [
        ("2023:10:20 17:00:00", 26.9239, 75.8267, "Jaipur"),
        ("2023:10:21 10:00:00", 26.9855, 75.8513, "Jaipur"),
        ("2023:10:21 16:00:00", 26.9258, 75.8237, "Jaipur"),
        ("2023:10:22 09:00:00", 26.9124, 75.7873, "Jaipur"),
    ],
    "Paris": [
        ("2024:06:08 19:00:00", 48.8584, 2.2945, "Paris"),
        ("2024:06:09 11:00:00", 48.8606, 2.3376, "Paris"),
        ("2024:06:10 14:00:00", 48.8049, 2.1204, "Versailles"),
        ("2024:06:11 10:00:00", 48.8867, 2.3431, "Paris"),
    ],
    "Lonavala": [
        ("2024:07:13 12:00:00", 18.7546, 73.4062, "Lonavla"),
        ("2024:07:14 10:00:00", 18.7481, 73.4072, "Lonavla"),
    ],
}
ODD = [("2024:08:01 12:00:00", 0.0, 0.0, None), ("2024:08:02 12:00:00", 14.0, 65.0, None)]
# for "On this day": two evenings at home on today's date, one and three years back
for back in (1, 3):
    t = date.today()
    d = t.replace(year=t.year - back, day=28) if (t.month, t.day) == (2, 29) else t.replace(year=t.year - back)
    HOME.append((f"{d:%Y:%m:%d} 17:30:00", 18.5308, 73.8475, "Pune"))
PEOPLE = ["Laura_Bush", "Vladimir_Putin", "Serena_Williams", "Jacques_Chirac", "Arnold_Schwarzenegger", "Kofi_Annan",
          "Luiz_Inacio_Lula_da_Silva", "Andre_Agassi", "Silvio_Berlusconi", "Nancy_Pelosi", "Tom_Ridge", "Lleyton_Hewitt"]

need = len(HOME) + sum(len(v) for v in TRIPS.values()) + len(ODD)
faces: list[Image.Image] = []
with tarfile.open(tgz) as tf:
    for m in tf:
        name = m.name.rsplit("/", 1)[-1]
        if m.isfile() and name.endswith(".jpg") and name.rsplit("_", 1)[0] in PEOPLE and name not in avoid:
            faces.append(Image.open(io.BytesIO(tf.extractfile(m).read())).convert("RGB"))
            if len(faces) == need:
                break
if len(faces) < need:
    sys.exit(f"only {len(faces)} of {need} photos found in the archive")


def dms(v: float) -> tuple[IFDRational, IFDRational, IFDRational]:
    v = abs(v)
    d = int(v)
    m = int((v - d) * 60)
    s = (v - d - m / 60) * 3600
    return IFDRational(d, 1), IFDRational(m, 1), IFDRational(round(s * 1000), 1000)


def save(im: Image.Image, path: Path, when: str, lat: float, lon: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exif = Image.Exif()
    exif[0x010F] = "RecProTest"  # Make
    exif[0x0110] = "Camera Two"  # Model
    exif.get_ifd(0x8769)[0x9003] = when  # DateTimeOriginal
    gps = exif.get_ifd(0x8825)
    gps[1] = "N" if lat >= 0 else "S"
    gps[2] = dms(lat)
    gps[3] = "E" if lon >= 0 else "W"
    gps[4] = dms(lon)
    im.resize((1000, 1000), Image.Resampling.BICUBIC).save(path, quality=90, exif=exif.tobytes())


if out.exists():
    shutil.rmtree(out)
truth: dict = {"photos": {}, "home": "Pune", "trips": []}
it = iter(faces)


def name_for(when: str) -> str:
    d, t = when.split(" ")
    return f"IMG_{d.replace(':', '')}_{t.replace(':', '')}.jpg"


for when, lat, lon, town in HOME:
    rel = f"Camera/{name_for(when)}"
    save(next(it), out / rel, when, lat, lon)
    truth["photos"][rel] = town
for trip, shots in TRIPS.items():
    for when, lat, lon, town in shots:
        rel = f"Camera/{name_for(when)}"
        save(next(it), out / rel, when, lat, lon)
        truth["photos"][rel] = town
    truth["trips"].append({"place": trip, "from": shots[0][0][:10].replace(":", "-"), "to": shots[-1][0][:10].replace(":", "-"),
                           "photos": [f"Camera/{name_for(s[0])}" for s in shots]})
for when, lat, lon, _ in ODD:
    rel = f"Odd/{name_for(when)}"
    save(next(it), out / rel, when, lat, lon)
    truth["photos"][rel] = "(none)"
(out / "truth.json").write_text(json.dumps(truth, indent=1), encoding="utf-8")
print(f"{need} photos written to {out.resolve()}")
