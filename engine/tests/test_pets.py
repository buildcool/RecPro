"""Things and pets: the objects pass (with a stand-in detector), pets grouped and named like people
and kept apart by species, found by name, and search by everyday words for things."""
from __future__ import annotations

import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

from recpro.api.app import create_app
from recpro.jobs.objects import ObjectsStage, category_scores, pet_candidates
from recpro.ml.objects import CLASS, LABELS, Obj, decode, display
from recpro.review.query import parse, run
from recpro.review.search import search_people
from tests.conftest import add_and_index

H = {"X-RecPro-Token": "test-token", "host": "127.0.0.1"}
DIM = 768


def _unit(v):
    return v / np.linalg.norm(v)


def _seed_pets(ctx, per=8, strangers=4, seed=2):
    """Two dogs, a cat whose look is close to the first dog's (only its species keeps them apart),
    and a few animals seen once; one per photo."""
    rng = np.random.default_rng(seed)
    db, now = ctx.db, time.time()
    with db.tx() as c:
        c.execute("INSERT INTO folders(path, added_at, status) VALUES('X:/pets', ?, 'ready')", (now,))
    dog1, dog2 = _unit(rng.normal(size=DIM)), _unit(rng.normal(size=DIM))
    cat1 = _unit(dog1 + rng.normal(scale=0.012, size=DIM))  # about 0.83 to the first dog's photos
    looks = [("dog", 0, dog1), ("dog", 1, dog2), ("cat", 2, cat1)]
    rows = [(sp, k, _unit(cen + rng.normal(scale=0.014, size=DIM))) for sp, k, cen in looks for _ in range(per)]  # about 0.87 apart
    rows += [("dog", -1, _unit(rng.normal(size=DIM))) for _ in range(strangers)]
    truth: dict[int, int] = {}
    with db.tx() as c:
        for i, (sp, k, emb) in enumerate(rows, 1):
            c.execute(
                "INSERT INTO media(id, folder_id, path, rel_dir, name, ext, kind, size, mtime, added_at, quick_v, deep_v, obj_v, width, height, taken_at) "
                "VALUES(?, 1, ?, '', ?, '.jpg', 'image', 1000, 0, ?, 1, 2, 1, 100, 100, ?)",
                (i, f"X:/pets/{i}.jpg", f"{i}.jpg", now, now - i * 3600),
            )
            aid = c.execute(
                "INSERT INTO animals(media_id, species, x1, y1, x2, y2, det_score, quality, embedding, state) VALUES(?,?, .2, .2, .7, .8, .9, .9, ?, 'none')",
                (i, sp, emb.astype(np.float16).tobytes()),
            ).lastrowid
            truth[aid] = k
    pets = ctx.services["pets"]
    pets.index.load_rows(db.q("SELECT id, media_id, quality, embedding FROM animals"))
    with pets._lock:
        pets._pending.update(truth)
    pets.ready = True
    return pets, truth, (dog1, dog2, cat1)


def _add_sighting(ctx, pets, species, emb):
    now = time.time()
    mid = ctx.db.scalar("SELECT MAX(id) FROM media") + 1
    ctx.db.x(
        "INSERT INTO media(id, folder_id, path, rel_dir, name, ext, kind, size, mtime, added_at, quick_v, obj_v, width, height) "
        "VALUES(?, 1, ?, '', ?, '.jpg', 'image', 1000, 0, ?, 1, 1, 100, 100)",
        (mid, f"X:/pets/{mid}.jpg", f"{mid}.jpg", now),
    )
    aid = ctx.db.x(
        "INSERT INTO animals(media_id, species, x1, y1, x2, y2, det_score, quality, embedding, state) VALUES(?,?, .1, .1, .5, .5, .9, .9, ?, 'none')",
        (mid, species, emb.astype(np.float16).tobytes()),
    ).lastrowid
    pets.on_new_faces([aid])
    return aid


def test_pets_are_grouped_by_animal_and_never_across_species(ctx):
    pets, truth, _ = _seed_pets(ctx)
    pets.assign_pending()
    pets.cluster()
    groups = ctx.db.q("SELECT person_id, COUNT(*) n FROM animals WHERE state='cluster' GROUP BY person_id")
    assert sorted(g["n"] for g in groups) == [8, 8, 8]
    for g in groups:
        members = [r["id"] for r in ctx.db.q("SELECT id FROM animals WHERE person_id=?", (g["person_id"],))]
        assert len({truth[a] for a in members}) == 1, "a group holds one animal"
        kind, species = ctx.db.q1("SELECT kind, species FROM people WHERE id=?", (g["person_id"],))
        assert kind == "pet" and species == ("cat" if truth[members[0]] == 2 else "dog")
    once = [a for a, k in truth.items() if k == -1]
    assert ctx.db.scalar(f"SELECT COUNT(*) FROM animals WHERE person_id IS NOT NULL AND id IN ({','.join(map(str, once))})") == 0
    # people know nothing of pets
    assert ctx.services["people"].name_suggestions() == []
    assert [b["kind"] for b in pets.name_suggestions()] == ["pet"] * 3


def test_naming_a_pet_finds_its_new_photos_but_not_the_cat_that_looks_alike(ctx):
    pets, truth, (dog1, _, cat1) = _seed_pets(ctx)
    pets.assign_pending()
    pets.cluster()
    first = next(a for a, k in truth.items() if k == 0)
    bruno = ctx.db.scalar("SELECT person_id FROM animals WHERE id=?", (first,))
    pets.rename(bruno, "Bruno")
    assert ctx.db.scalar("SELECT COUNT(*) FROM animals WHERE person_id=? AND state='auto'", (bruno,)) == 8
    rng = np.random.default_rng(9)
    new_dog = _add_sighting(ctx, pets, "dog", _unit(dog1 + rng.normal(scale=0.014, size=DIM)))
    new_cat = _add_sighting(ctx, pets, "cat", _unit(cat1 + rng.normal(scale=0.014, size=DIM)))
    pets.assign_pending()
    assert tuple(ctx.db.q1("SELECT person_id, state FROM animals WHERE id=?", (new_dog,))) == (bruno, "auto")
    assert ctx.db.scalar("SELECT person_id FROM animals WHERE id=?", (new_cat,)) != bruno
    # "not Bruno" sticks, and undo takes it back
    pets.answer(bruno, [], [new_dog])
    assert ctx.db.scalar("SELECT person_id FROM animals WHERE id=?", (new_dog,)) is None
    pets.rescore_person(bruno)
    assert ctx.db.scalar("SELECT person_id FROM animals WHERE id=?", (new_dog,)) is None
    assert pets.undo_last()
    assert ctx.db.scalar("SELECT person_id FROM animals WHERE id=?", (new_dog,)) == bruno


def test_pets_through_the_api_search_and_find(ctx):
    pets, truth, _ = _seed_pets(ctx)
    pets.assign_pending()
    pets.cluster()
    first = next(a for a, k in truth.items() if k == 0)
    bruno = ctx.db.scalar("SELECT person_id FROM animals WHERE id=?", (first,))
    pets.rename(bruno, "Bruno")
    now = time.time()
    rohit = ctx.db.x("INSERT INTO people(name, kind, created_at, updated_at) VALUES('Rohit', 'human', ?, ?)", (now, now)).lastrowid
    shared = ctx.db.scalar("SELECT media_id FROM animals WHERE id=?", (first,))
    ctx.db.x(
        "INSERT INTO faces(media_id, x1, y1, x2, y2, det_score, quality, embedding, person_id, state) VALUES(?, .1, .1, .2, .2, .9, .9, ?, ?, 'confirmed')",
        (shared, np.zeros(512, np.float16).tobytes(), rohit),
    )
    client = TestClient(create_app(ctx))
    named = client.get("/api/people?kind=pet&named=1", headers=H).json()
    assert [(p["name"], p["count"], p["species"], p["kind"]) for p in named] == [("Bruno", 8, "dog", "pet")]
    assert [p["name"] for p in client.get("/api/people?named=1", headers=H).json()] == ["Rohit"]
    d = client.get(f"/api/people/{bruno}", headers=H).json()
    assert d["kind"] == "pet" and d["coverage"]["found"] == 8
    assert [(x["name"], x["n"]) for x in d["companions"]] == [("Rohit", 1)]
    months = client.get(f"/api/timeline?person_id={bruno}", headers=H).json()["months"]
    assert sum(m["count"] for m in months) == 8
    assert client.post(f"/api/people/{bruno}/merge", json={"into": rohit}, headers=H).status_code == 400
    media = client.get(f"/api/media/{shared}", headers=H).json()
    assert [(a["species"], a["person_name"]) for a in media["animals"]] == [("dog", "Bruno")]
    # find and search by the pet's name
    res = search_people(ctx, [bruno])
    assert len(res["sure"]) == 8 and {it["det"] for it in res["sure"]} == {"animal"}
    assert len(run(ctx, "Bruno")["sure"]) == 8
    assert len(run(ctx, "Bruno smiling")["sure"]) == 8, "an expression filter doesn't drop a pet's photos"
    # answers through the API, and undo
    victim = ctx.db.scalar("SELECT id FROM animals WHERE person_id=? LIMIT 1", (bruno,))
    assert client.post(f"/api/animals/{victim}/not", json={"person_id": bruno}, headers=H).status_code == 200
    assert ctx.db.scalar("SELECT person_id FROM animals WHERE id=?", (victim,)) is None
    assert client.post("/api/review/undo", headers=H).json()["undone"] is True
    assert ctx.db.scalar("SELECT person_id FROM animals WHERE id=?", (victim,)) == bruno
    r = client.post(f"/api/animals/{victim}/assign", json={"name": "Sheru"}, headers=H).json()
    assert tuple(ctx.db.q1("SELECT name, kind, species FROM people WHERE id=?", (r["person_id"],))) == ("Sheru", "pet", "dog")
    assert client.get("/api/review/faces?kind=pet", headers=H).json()["kind"] == "pet"
    counts = client.get("/api/review/counts", headers=H).json()
    assert {"pets", "pet_name", "pet_merge", "faces"} <= set(counts)


class _Detector:
    """Stands in for D-FINE: a dog, a laptop, an umbrella and a person in every photo."""

    def detect_many(self, images, min_score=0.3):
        out = []
        for img in images:
            if img is None:
                out.append([])
                continue
            out.append([
                Obj(CLASS["Dog"], 0.92, (0.1, 0.1, 0.8, 0.9)),
                Obj(CLASS["Cat"], 0.55, (0.11, 0.1, 0.8, 0.9)),  # the same animal, a second guess
                Obj(CLASS["Laptop"], 0.81, (0.5, 0.5, 0.9, 0.9)),
                Obj(CLASS["Umbrella"], 0.35, (0.0, 0.0, 0.05, 0.05)),
                Obj(CLASS["Person"], 0.9, (0.6, 0.0, 1.0, 1.0)),  # someone at the right, by the dog
            ])
        return out


class _Look:
    dim = DIM

    def embed(self, crops):
        return np.stack([_unit(np.ones(DIM) + 0.01 * k) for k in range(len(crops))]).astype(np.float32)


def test_the_objects_pass_stores_things_categories_and_animals(ctx, library_dir, monkeypatch):
    add_and_index(ctx, library_dir)
    ml = ctx.services["ml"]
    monkeypatch.setattr(ml, "objects_id", lambda: "objects")
    monkeypatch.setattr(ml, "objects", lambda: _Detector())
    monkeypatch.setattr(ml, "petlook", lambda: _Look())
    ctx.services["taxonomy"]  # seeds the categories
    stage = ObjectsStage(ctx)
    rows = ctx.db.q("SELECT * FROM media")
    # the face detector took the dog's face for a person's in one photo, and found a real face in another
    first, second = rows[0]["id"], rows[1]["id"]
    zero = np.zeros(512, np.float16).tobytes()
    dog_face = ctx.db.x(
        "INSERT INTO faces(media_id, x1, y1, x2, y2, det_score, quality, embedding, state) VALUES(?, .3, .3, .5, .5, .6, .8, ?, 'cluster')", (first, zero)
    ).lastrowid
    ctx.services["people"].index.load_rows(ctx.db.q("SELECT id, media_id, quality, embedding FROM faces"))
    person_face = ctx.db.x(
        "INSERT INTO faces(media_id, x1, y1, x2, y2, det_score, quality, embedding, state) VALUES(?, .65, .2, .75, .3, .9, .9, ?, 'none')", (second, zero)
    ).lastrowid
    stage.process(rows)
    assert tuple(ctx.db.q1("SELECT state, quality, person_id FROM faces WHERE id=?", (dog_face,))) == ("animal", 0, None)
    assert dog_face not in ctx.services["people"].index.pos, "an animal's face leaves people"
    assert ctx.db.scalar("SELECT state FROM faces WHERE id=?", (person_face,)) == "none", "a face on a person stays"
    n = len(rows)
    assert ctx.db.scalar("SELECT COUNT(*) FROM media WHERE obj_v=1") == n
    assert ctx.db.scalar("SELECT COUNT(*) FROM objects") == 5 * n
    assert ctx.db.scalar("SELECT COUNT(*) FROM animals WHERE species='dog'") == n, "one animal per photo, not a dog and a cat"
    dog_tier = ctx.db.q("SELECT ml.tier FROM media_labels ml JOIN labels l ON l.id=ml.label_id WHERE l.key='pet.dog'")
    assert len(dog_tier) == n and {r["tier"] for r in dog_tier} == {"sure"}
    # read again: a named pet stays named
    aid = ctx.db.scalar("SELECT id FROM animals LIMIT 1")
    now = time.time()
    pid = ctx.db.x("INSERT INTO people(name, kind, species, created_at, updated_at) VALUES('Bruno', 'pet', 'dog', ?, ?)", (now, now)).lastrowid
    ctx.db.x("UPDATE animals SET person_id=?, state='confirmed' WHERE id=?", (pid, aid))
    ctx.db.x("INSERT INTO animal_votes(animal_id, person_id, vote, at) VALUES(?, ?, 1, ?)", (aid, pid, now))
    mid = ctx.db.scalar("SELECT media_id FROM animals WHERE id=?", (aid,))
    stage.process(ctx.db.q("SELECT * FROM media WHERE id=?", (mid,)))
    new = ctx.db.q1("SELECT id, person_id, state FROM animals WHERE media_id=?", (mid,))
    assert new["id"] != aid and (new["person_id"], new["state"]) == (pid, "confirmed")
    assert ctx.db.scalar("SELECT animal_id FROM animal_votes WHERE person_id=?", (pid,)) == new["id"]
    # what the photo's details show
    client = TestClient(create_app(ctx))
    things = client.get(f"/api/media/{mid}", headers=H).json()["things"]
    assert [t["name"] for t in things] == ["Dog", "Laptop", "Cat"]


def test_search_by_things(ctx, library_dir):
    add_and_index(ctx, library_dir)
    ctx.services["taxonomy"]
    a, b, c3 = [r["id"] for r in ctx.db.q("SELECT id FROM media ORDER BY id LIMIT 3")]
    umbrella = CLASS["Umbrella"]
    ctx.db.x("INSERT INTO objects(media_id, cls, score, x1, y1, x2, y2) VALUES(?, ?, 0.85, .1, .1, .5, .5)", (a, umbrella))
    ctx.db.x("INSERT INTO objects(media_id, cls, score, x1, y1, x2, y2) VALUES(?, ?, 0.45, .1, .1, .5, .5)", (b, umbrella))
    ctx.db.x("INSERT INTO objects(media_id, cls, score, x1, y1, x2, y2) VALUES(?, ?, 0.20, .1, .1, .5, .5)", (c3, umbrella))
    res = run(ctx, "umbrellas")
    assert [it["id"] for it in res["sure"]] == [a] and [it["id"] for it in res["check"]] == [b]
    assert [o["name"] for o in res["parsed"]["objects"]] == ["Umbrella"]
    p = parse(ctx, "laptop on sofa")
    assert [lab["name"] for lab in p["labels"]] == ["Laptop", "Sofa"] and p["text"] == ""
    assert [lab["name"] for lab in parse(ctx, "puppies")["labels"]] == ["Dogs"]
    assert parse(ctx, "beach sunset")["text"] == "beach sunset" and not parse(ctx, "beach sunset")["objects"]
    assert parse(ctx, "teddy bear")["objects"][0]["name"] == "Soft toy"


def test_decoding_names_and_animals_kept():
    logits = np.full((300, len(LABELS)), -9.0, np.float32)
    logits[0, CLASS["Dog"]] = 3.0  # 0.95
    logits[1, 0] = 9.0  # "None" is never a detection
    logits[2, CLASS["Cell Phone"]] = -0.5  # 0.38
    boxes = np.tile(np.array([[0.5, 0.5, 0.4, 0.6]], np.float32), (300, 1))
    found = decode(logits, boxes, min_score=0.3)
    assert [(LABELS[o.cls], round(o.score, 2)) for o in found] == [("Dog", 0.95), ("Cell Phone", 0.38)]
    assert found[0].box == pytest.approx((0.3, 0.2, 0.7, 0.8))
    assert display(CLASS["Cell Phone"]) == "Mobile phone" and display(CLASS["Dinning Table"]) == "Dining table"
    assert display(CLASS["Potted Plant"]) == "Potted plant"
    # a tiny thing counts for less; an animal from smaller
    far_car = Obj(CLASS["Car"], 0.9, (0.0, 0.0, 0.03, 0.03))
    assert category_scores([far_car])["object.car"] < 0.3
    small_dog = Obj(CLASS["Dog"], 0.9, (0.0, 0.0, 0.05, 0.05))
    assert category_scores([small_dog])["pet.dog"] > 0.85
    kept = pet_candidates([Obj(CLASS["Dog"], 0.9, (0.1, 0.1, 0.6, 0.6)), Obj(CLASS["Cat"], 0.6, (0.12, 0.1, 0.6, 0.6)),
                           Obj(CLASS["Cat"], 0.9, (0.0, 0.0, 0.02, 0.02))], 1000, 800)
    assert [sp for _, sp, _ in kept] == ["dog"], "one animal per box, none too small to tell apart"
