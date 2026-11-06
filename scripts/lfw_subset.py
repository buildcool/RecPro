"""Builds a small two-folder test library from the LFW archive (development only).

Usage: python -I scripts/lfw_subset.py <lfw.tgz> <out_dir>
Ten people with many photos are split across FolderA/FolderB; single-photo people are
added as strangers. Ground truth is written to <out_dir>/truth.json.
"""
import json
import random
import sys
import tarfile
from collections import defaultdict
from pathlib import Path

src, out = Path(sys.argv[1]), Path(sys.argv[2])
random.seed(42)
PEOPLE = 10
PER_PERSON = 40
STRANGERS = 300

with tarfile.open(src, "r:gz") as tar:
    members = [m for m in tar.getmembers() if m.isfile() and m.name.lower().endswith(".jpg")]
    by_person = defaultdict(list)
    for m in members:
        parts = m.name.split("/")
        if len(parts) >= 3:
            by_person[parts[1]].append(m)
    many = sorted((p for p, ms in by_person.items() if len(ms) >= 40), key=lambda p: -len(by_person[p]))[:PEOPLE]
    singles = [p for p, ms in by_person.items() if len(ms) == 1]
    random.shuffle(singles)
    truth: dict[str, str] = {}
    picks = []
    for p in many:
        ms = sorted(by_person[p], key=lambda m: m.name)
        random.shuffle(ms)
        for i, m in enumerate(ms[:PER_PERSON]):
            picks.append((m, "FolderA" if i % 2 == 0 else "FolderB", p))
    for p in singles[:STRANGERS]:
        picks.append((by_person[p][0], random.choice(["FolderA", "FolderB"]), "_stranger"))
    for m, folder, person in picks:
        dest = out / folder / Path(m.name).name
        dest.parent.mkdir(parents=True, exist_ok=True)
        f = tar.extractfile(m)
        if f is None:
            continue
        dest.write_bytes(f.read())
        truth[str(dest.relative_to(out)).replace("\\", "/")] = person
(out / "truth.json").write_text(json.dumps({"people": many, "files": truth}, indent=1), encoding="utf-8")
print(f"{len(truth)} images, people: {', '.join(many)}")
