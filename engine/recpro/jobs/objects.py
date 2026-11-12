"""Objects pass: things and animals with where they are (D-FINE on Objects365), the categories
they back up (a laptop, a sofa, a dog…), and every dog, cat, rabbit or parrot's look (DINOv2) so
pets can be grouped and named."""
from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import numpy as np

from ..context import Context
from ..ml.objects import CLASS, LABELS, OBJ_V, Obj
from ..review.pets import MIN_DET, MIN_SIDE_PX, SPECIES, animal_quality
from .deep import iou, load_rgb

log = logging.getLogger("recpro.objects")

DECODE = 1280  # the detector sees 640 px; pets are cropped from this
STORE_MIN = 0.30  # detections kept (search, categories and pets set their own bars)
MAX_PER_PHOTO = 100

# Categories the detector backs up, and the detector classes that count for each. On 1,244 Open
# Images photos with checked labels, D-FINE X's mean average precision over these was 0.93 (dogs,
# cats and birds 0.99-1.00). "TV or monitor" is one class, so it backs up neither Television nor
# Desktop.
DET_CATEGORIES: dict[str, tuple[str, ...]] = {
    "object.laptop": ("Laptop",),
    "object.phone": ("Cell Phone",),
    "object.desktop": ("Computer Box",),
    "object.sofa": ("Couch",),
    "object.fridge": ("Refrigerator",),
    "object.car": ("Car", "SUV", "Van", "Sports Car", "Pickup Truck"),
    "object.motorbike": ("Motorcycle", "Scooter"),
    "object.bicycle": ("Bicycle",),
    "object.cake": ("Cake", "Dessert", "Donut", "Cookies", "Pie", "Egg tart", "Ice cream"),
    "object.flowers": ("Flower",),
    "object.guitar": ("Guitar",),
    "object.books": ("Book",),
    "object.watch": ("Watch",),
    "object.jewelry": ("Necklace", "Bracelet", "Ring"),
    "object.drinks": ("Cup", "Wine Glass"),
    "pet.dog": ("Dog",),
    "pet.cat": ("Cat",),
    "pet.bird": ("Wild Bird", "Parrot", "Duck", "Pigeon", "Goose", "Swan", "Chicken", "Penguin"),
    "pet.cow": ("Cow", "Yak"),
    "pet.horse": ("Horse", "Donkey"),
    "pet.fish": ("Other Fish", "Goldfish"),
}
_CAT_CLASSES = {k: {CLASS[n] for n in v} for k, v in DET_CATEGORIES.items()}
# A thing this small in the photo (share of its area) counts for less: a car far down the street
# doesn't make a photo of a car. Animals count from smaller.
FULL_AREA = {"object": 0.01, "pet": 0.002}


# Animals with a face the face detector can take for a person's (a dog looking at the camera)
ANIMALS_WITH_FACES = {CLASS[n] for n in (
    "Dog", "Cat", "Horse", "Cow", "Sheep", "Rabbit", "Bear", "Monkey", "Pig", "Deer", "Lion", "Elephant", "Zebra",
    "Giraffe", "Camel", "Donkey", "Yak", "Antelope", "Seal", "Parrot", "Wild Bird",
)}
ANIMAL_MIN, PERSON_MIN = 0.5, 0.4


def mark_animal_faces(c, media_id: int) -> list[int]:
    """A photo's faces that are an animal's: inside an animal the detector found and on no person.
    They become state 'animal' with quality 0, so they're never grouped, matched or counted as
    people. Your own answers are left alone. Inside the caller's transaction; returns their ids."""
    objs = c.execute(
        "SELECT cls, x1, y1, x2, y2 FROM objects WHERE media_id=? AND frame_ms IS NULL AND ((cls=? AND score >= ?) OR score >= ?)",
        (media_id, CLASS["Person"], PERSON_MIN, ANIMAL_MIN),
    ).fetchall()
    animals = [o for o in objs if o["cls"] in ANIMALS_WITH_FACES]
    if not animals:
        return []
    people = [o for o in objs if o["cls"] == CLASS["Person"]]

    def on(cx: float, cy: float, boxes) -> bool:
        return any(b["x1"] <= cx <= b["x2"] and b["y1"] <= cy <= b["y2"] for b in boxes)

    out = []
    for f in c.execute(
        "SELECT id, x1, y1, x2, y2 FROM faces WHERE media_id=? AND frame_ms IS NULL AND state NOT IN ('confirmed','animal')", (media_id,)
    ).fetchall():
        cx, cy = (f["x1"] + f["x2"]) / 2, (f["y1"] + f["y2"]) / 2
        if on(cx, cy, animals) and not on(cx, cy, people):
            out.append(int(f["id"]))
    if out:
        c.executemany("UPDATE faces SET person_id=NULL, state='animal', score=NULL, quality=0 WHERE id=?", [(i,) for i in out])
        c.execute("UPDATE media SET face_count=(SELECT COUNT(*) FROM faces WHERE media_id=? AND state!='animal') WHERE id=?", (media_id, media_id))
    return out


def category_scores(objs: list[Obj]) -> dict[str, float]:
    """The detector's score for each category it backs up (0 when it saw nothing of it)."""
    out: dict[str, float] = {}
    for key, classes in _CAT_CLASSES.items():
        full = FULL_AREA[key.split(".")[0]]
        best = 0.0
        for o in objs:
            if o.cls in classes:
                best = max(best, o.score * min(1.0, (o.area / full) ** 0.5))
        out[key] = round(best, 4)
    return out


def pet_candidates(objs: list[Obj], w: int, h: int) -> list[tuple[Obj, str, float]]:
    """Animals clear enough to tell apart: (detection, species, shorter side in pixels)."""
    out: list[tuple[Obj, str, float]] = []
    for o in sorted(objs, key=lambda o: -o.score):
        sp = SPECIES.get(LABELS[o.cls])
        if sp is None or o.score < MIN_DET:
            continue
        side = min((o.box[2] - o.box[0]) * w, (o.box[3] - o.box[1]) * h)
        if side < MIN_SIDE_PX:
            continue
        if any(iou(o.box, x.box) > 0.6 for x, _, _ in out):
            continue  # the same animal under a second guess of its species
        out.append((o, sp, side))
    return out


class ObjectsStage:
    name = "objects"
    label = "Finding things and pets"
    column = "obj_v"
    version = OBJ_V
    kinds = ("image",)
    batch_size = 16
    order = "taken_at DESC"

    def __init__(self, ctx: Context):
        self.ctx = ctx
        self.pool = ThreadPoolExecutor(max_workers=max(4, min(8, (os.cpu_count() or 8) // 3)), thread_name_prefix="objects")

    @property
    def ml(self):
        return self.ctx.services["ml"]

    def available(self) -> bool:
        return self.ml.objects_id() is not None  # type: ignore[attr-defined]

    def where(self) -> str:
        return "quick_v >= 1 AND width IS NOT NULL"

    def process(self, rows: list[Any]) -> None:
        det = self.ml.objects()  # type: ignore[attr-defined]
        if det is None:
            return
        look = self.ml.petlook()  # type: ignore[attr-defined]
        from ..ml.petlook import square_crop

        imgs = list(self.pool.map(lambda r: load_rgb(r["path"], DECODE), rows))
        found = det.detect_many(imgs, min_score=STORE_MIN)
        # Animals to tell apart need the pet model; without it they wait (photos with one are read
        # again when it's installed).
        cands: list[tuple[int, Obj, str, float]] = []
        for k, (img, objs) in enumerate(zip(imgs, found)):
            if img is not None and look is not None:
                cands += [(k, o, sp, side) for o, sp, side in pet_candidates(objs, img.shape[1], img.shape[0])]
        crops = [square_crop(imgs[k], o.box) for k, o, _, _ in cands]  # type: ignore[index]
        E = look.embed(crops) if crops else np.zeros((0, 1), np.float32)
        animals: dict[int, list[tuple[Obj, str, float, np.ndarray]]] = {}
        for (k, o, sp, side), e in zip(cands, E):
            animals.setdefault(k, []).append((o, sp, side, e))

        new_ids: list[int] = []
        removed: list[int] = []
        animal_faces: list[int] = []
        records: list[tuple[int, str, dict[str, float], str]] = []
        with self.ctx.db.tx() as c:
            for k, (row, img, objs) in enumerate(zip(rows, imgs, found)):
                mid = row["id"]
                c.execute("DELETE FROM objects WHERE media_id=? AND frame_ms IS NULL", (mid,))
                if img is None:
                    c.execute("UPDATE media SET obj_v=? WHERE id=?", (OBJ_V, mid))
                    continue
                c.executemany(
                    "INSERT INTO objects(media_id, cls, score, x1, y1, x2, y2) VALUES(?,?,?,?,?,?,?)",
                    [(mid, o.cls, round(o.score, 4), *(round(v, 4) for v in o.box)) for o in objs[:MAX_PER_PHOTO]],
                )
                for key, v in category_scores(objs).items():
                    records.append((mid, key, {"det": v}, key.split(".")[0]))
                animal_faces += mark_animal_faces(c, mid)
                if look is not None:
                    ins, gone = self._store_animals(c, mid, animals.get(k, []))
                    new_ids += ins
                    removed += gone
                c.execute("UPDATE media SET obj_v=? WHERE id=?", (OBJ_V, mid))
        labels = self.ctx.services.get("labels")
        if labels is not None and records:
            labels.record_many(records)  # type: ignore[attr-defined]
        people = self.ctx.services.get("people")
        if people is not None and animal_faces:
            people.index.remove(animal_faces)  # type: ignore[attr-defined]
            people.publish()  # type: ignore[attr-defined]
        pets = self.ctx.services.get("pets")
        if pets is not None:
            if removed:
                pets.index.remove(removed)  # type: ignore[attr-defined]
            if new_ids:
                pets.on_new_faces(new_ids)  # type: ignore[attr-defined]

    @staticmethod
    def _store_animals(c, mid: int, found: list[tuple[Obj, str, float, np.ndarray]]) -> tuple[list[int], list[int]]:
        """Replaces a photo's animals. One found again at the same spot keeps everything known about
        it: which pet it is (your answers and the AI's), your votes, and covers that use it."""
        old = c.execute("SELECT id, x1, y1, x2, y2, species FROM animals WHERE media_id=? AND frame_ms IS NULL", (mid,)).fetchall()
        inserted: list[tuple[int, tuple[float, float, float, float], str]] = []
        for o, sp, side, e in found:
            cur = c.execute(
                """INSERT INTO animals(media_id, species, x1, y1, x2, y2, det_score, quality, embedding, state)
                   VALUES(?,?,?,?,?,?,?,?,?, 'none')""",
                (mid, sp, *(round(v, 4) for v in o.box), round(o.score, 4), animal_quality(o.score, side), e.astype(np.float16).tobytes()),
            )
            inserted.append((cur.lastrowid, o.box, sp))
        carried: set[int] = set()
        removed: list[int] = []
        for r in old:
            ob = (r["x1"], r["y1"], r["x2"], r["y2"])
            best = max((t for t in inserted if t[2] == r["species"]), key=lambda t: iou(ob, t[1]), default=None)
            if best and iou(ob, best[1]) > 0.5 and best[0] not in carried:
                carried.add(best[0])
                prev = c.execute("SELECT person_id, state, score FROM animals WHERE id=?", (r["id"],)).fetchone()
                if prev and prev["person_id"] is not None:
                    c.execute("UPDATE animals SET person_id=?, state=?, score=? WHERE id=?", (prev["person_id"], prev["state"], prev["score"], best[0]))
                c.execute("UPDATE OR IGNORE animal_votes SET animal_id=? WHERE animal_id=?", (best[0], r["id"]))
                c.execute("UPDATE people SET cover_face_id=? WHERE cover_face_id=? AND kind='pet'", (best[0], r["id"]))
            c.execute("DELETE FROM animals WHERE id=?", (r["id"],))
            removed.append(r["id"])
        return [t[0] for t in inserted], removed
