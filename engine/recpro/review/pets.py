"""Pets: animals grouped and named like people, with the same Sure / Please check / No tiers.

An animal the object detector finds (a dog, a cat, a rabbit or a parrot) gets an identity
embedding from DINOv2 base (how this particular animal looks: coat, markings, face), and from there
it's the people machinery: unnamed groups of the same animal, "Who is this?", "Is this Bruno?",
your answers final. A pet is a row in ``people`` of kind 'pet'; its animals are rows in
``animals``. A dog is never matched to, grouped with or merged into a cat.
"""
from __future__ import annotations

from typing import Any

from ..context import Context
from ..ml.objects import OBJ_V
from .people import People

# the detector's classes that can be pets, and the species they become
SPECIES = {"Dog": "dog", "Cat": "cat", "Rabbit": "rabbit", "Parrot": "parrot"}
SPECIES_NAMES = {"dog": ("Dog", "Dogs"), "cat": ("Cat", "Cats"), "rabbit": ("Rabbit", "Rabbits"), "parrot": ("Parrot", "Parrots")}
MIN_DET = 0.5  # detector score for an animal to be kept for naming
MIN_SIDE_PX = 48  # its box's shorter side on the photo as read (at most 1280 px)


def animal_quality(det_score: float, side_px: float) -> float:
    """0..1: how much one sighting can be trusted (detector confidence, and size in the photo)."""
    size_q = min(1.0, max(0.0, (side_px - 40.0) / 120.0))
    return round(float(det_score) * (0.4 + 0.6 * size_q), 4)


class Pets(People):
    KIND = "pet"
    T = "animals"
    VOTES, VFK = "animal_votes", "animal_id"
    DIM = 768  # DINOv2 base
    SENS = "sensitivity.faces"  # "How often RecPro asks you" about faces covers pets too
    COUNT_KEYS = ("pets", "pet_name", "pet_merge")
    # DINOv2 similarities sit higher than ArcFace's, and look-alike dogs come closer than
    # look-alike people. On DogFaceNet's original photos (2,800 photos of 1,016 dogs, each dog
    # found by the detector and cropped) two photos of the same dog have a median similarity of
    # 0.79 and two different dogs 0.14, with 99.9% of them below 0.74. Grouping links only from
    # 0.78: in libraries of 3 pets among 40 dogs seen once or twice (drawn 300 times from
    # DogFaceNet), 0.3 groups per library mixed two dogs, against 2.6 when linking from 0.68.
    TIERS = {"never_miss": (0.78, 0.45), "balanced": (0.76, 0.52), "fewer": (0.74, 0.58)}
    MIN_Q_AUTO = 0.45
    MARGIN = 0.06
    CLUSTER_SIM = 0.78
    CLUSTER_JOIN = 0.78
    MERGE_AUTO = 0.88
    MERGE_ASK = 0.66
    NAMED_ASK = 0.74
    MIN_CLUSTER_Q = 0.35
    SURE_RANGE = (0.72, 0.86)
    CHECK_FLOOR = 0.40
    CALIB0 = (0.64, 0.05)
    BUSY = f"SELECT EXISTS(SELECT 1 FROM media WHERE state='active' AND kind='image' AND quick_v>=1 AND width IS NOT NULL AND obj_v<{OBJ_V})"

    def _kinds(self, ids) -> dict[int, str]:
        ids = [int(i) for i in ids]
        out: dict[int, str] = {}
        for s in range(0, len(ids), 900):
            chunk = ids[s : s + 900]
            for r in self.db.q(f"SELECT id, species FROM animals WHERE id IN ({','.join('?' * len(chunk))})", chunk):
                out[r["id"]] = r["species"]
        return out

    def _person_kinds(self, pids) -> dict[int, str]:
        pids = [int(p) for p in pids]
        out: dict[int, str] = {}
        for s in range(0, len(pids), 900):
            chunk = pids[s : s + 900]
            for r in self.db.q(f"SELECT id, species FROM people WHERE id IN ({','.join('?' * len(chunk))})", chunk):
                if r["species"]:
                    out[r["id"]] = r["species"]
        return out

    def _new_group(self, c, cover_id: int, now: float) -> int:
        sp = c.execute("SELECT species FROM animals WHERE id=?", (cover_id,)).fetchone()
        return c.execute(
            "INSERT INTO people(name, kind, species, cover_face_id, created_at, updated_at) VALUES(NULL, 'pet', ?, ?, ?, ?)",
            (sp["species"] if sp else None, cover_id, now, now),
        ).lastrowid

    def _new_person(self, name: str, now: float, first: list[int] | None) -> int:
        sp = self.db.scalar("SELECT species FROM animals WHERE id=?", (first[0],)) if first else None
        return self.db.x(
            "INSERT INTO people(name, kind, species, created_at, updated_at) VALUES(?, 'pet', ?, ?, ?)", (name, sp, now, now)
        ).lastrowid

    def _brief(self, pid: int) -> dict[str, Any]:
        out = super()._brief(pid)
        out["species"] = self.db.scalar("SELECT species FROM people WHERE id=?", (pid,))
        return out


def create(ctx: Context) -> Pets:
    return Pets(ctx)
