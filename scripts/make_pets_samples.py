"""Builds .testdata/pets-samples: dogs to group and name, and photos with everyday things.

Sources (downloaded separately, see docs/DEVELOPMENT.md):
- DogFaceNet's original photos (Hugging Face dimidagd/DogFaceNet_large, unpacked to JPEGs with a
  labels.json of photo -> dog): DOGS dogs with three photos each.
- The Open Images validation photos and their checked labels (sample.json: photo id -> {class: 1/0}):
  a few photos per thing in THINGS.

Usage: python -I scripts/make_pets_samples.py <dogfacenet dir> <open images dir> <out dir>
"""
from __future__ import annotations

import json
import shutil
import sys
from collections import defaultdict
from pathlib import Path

from PIL import Image

DOGS = 4
THINGS = {"Cat": 3, "Laptop": 2, "Couch": 2, "Guitar": 2, "Car": 2}


def readable(p: Path) -> bool:
    try:
        with Image.open(p) as im:
            return im.width >= 300 and im.height >= 300
    except Exception:
        return False


def main(dfn: Path, oi: Path, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    labels = json.loads((dfn / "labels.json").read_text())
    by_dog: dict[int, list[str]] = defaultdict(list)
    for f, dog in sorted(labels.items()):
        by_dog[dog].append(f)
    picked = 0
    for dog, files in sorted(by_dog.items()):
        good = [f for f in files if readable(dfn / f)]
        if len(good) < 3:
            continue
        for k, f in enumerate(good[:3]):
            shutil.copyfile(dfn / f, out / f"dog{picked + 1}_{k + 1}.jpg")
        picked += 1
        if picked == DOGS:
            break
    truth = json.loads((oi / "sample.json").read_text())
    used: set[str] = set()
    for thing, n in THINGS.items():
        ids = [i for i, t in sorted(truth.items()) if t.get(thing) == 1 and i not in used and (oi / "img" / f"{i}.jpg").exists()]
        for i in ids[:n]:
            used.add(i)
            shutil.copyfile(oi / "img" / f"{i}.jpg", out / f"{thing.lower()}_{i}.jpg")
    print(f"{picked} dogs x 3 photos and {len(used)} photos of things in {out}")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
