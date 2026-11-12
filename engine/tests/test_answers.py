"""Names and answers to a file and back on "another PC", saved searches, and XMP sidecars."""
from __future__ import annotations

import json
import shutil
import xml.etree.ElementTree as ET

import numpy as np

from recpro import labels_io, xmp
from recpro.api import routes_search
from recpro.bootstrap import build_context
from recpro.config import Paths
from recpro.jobs.deep import DEEP_V
from recpro.ml.objects import OBJ_V
from recpro.review.hidden import answer as hidden_answer
from tests.conftest import add_and_index, wait_for
from tests.test_cleanup import photo

BOX1 = (0.1, 0.1, 0.3, 0.4)
BOX2 = (0.5, 0.2, 0.7, 0.5)


def add_face(ctx, media_id, box, seed):
    """A face as the face pass would store it (synthetic vector)."""
    rng = np.random.default_rng(seed)
    emb = rng.normal(size=512)
    emb /= np.linalg.norm(emb)
    fid = ctx.db.x(
        "INSERT INTO faces(media_id, x1, y1, x2, y2, det_score, quality, embedding, state) VALUES(?,?,?,?,?,.9,.9,?,'none')",
        (media_id, *box, emb.astype(np.float16).tobytes()),
    ).lastrowid
    ctx.db.x("UPDATE media SET deep_v=?, face_count=face_count+1 WHERE id=?", (DEEP_V, media_id))
    ctx.services["people"].index.load_rows(ctx.db.q("SELECT id, media_id, quality, embedding FROM faces"))
    return fid


def photos(root, n=4):
    for i in range(n):
        photo(root / f"IMG_{i}.jpg", seed=40 + i)


def ids(ctx):
    return {r["name"]: r["id"] for r in ctx.db.q("SELECT id, name FROM media")}


def test_names_and_answers_go_to_another_pc(ctx, tmp_path):
    photos(tmp_path / "A")
    add_and_index(ctx, tmp_path / "A")
    a = ids(ctx)
    people = ctx.services["people"]
    f1 = add_face(ctx, a["IMG_0.jpg"], BOX1, 1)
    f2 = add_face(ctx, a["IMG_1.jpg"], BOX2, 2)
    pid = people.create_person("Asha", [f1])
    people.answer(pid, [], [f2])
    hidden_answer(ctx, pid, [a["IMG_2.jpg"]], [])  # in it, though her face isn't visible
    tax, travel = ctx.services["taxonomy"], ctx.services["labels"].id("activity.travel")
    tax.answer(travel, [a["IMG_0.jpg"]], [a["IMG_1.jpg"]])
    ctx.db.x("UPDATE media SET sens_state='private' WHERE id=?", (a["IMG_3.jpg"],))
    tax.answer(travel, [a["IMG_3.jpg"]], [])  # about a private photo: stays on this PC
    doc = labels_io.export(ctx)
    assert labels_io.counts(doc) == {"people": 1, "faces": 2, "photos": 1, "pets": 0, "animals": 0, "categories": 1, "answers": 2}
    text = json.dumps(doc)
    assert "IMG_0" not in text and tmp_path.name not in text  # photos by content, never by where they are

    # another PC: the same photos in another folder, not read yet when the file is imported
    shutil.copytree(tmp_path / "A", tmp_path / "B")
    c2 = build_context(Paths(tmp_path / "data2"), "t2")
    try:
        res = labels_io.import_(c2, doc)
        assert res["people_added"] == 1 and res["waiting"] == 5
        add_and_index(c2, tmp_path / "B")
        b = ids(c2)
        travel2 = c2.services["labels"].id("activity.travel")
        c2.services["taxonomy"].answer(travel2, [b["IMG_1.jpg"]], [])  # your own answer here: the file says no
        labels_io.apply_waiting(c2, list(b.values()))  # the photos are read: answers about them apply

        def state(name):
            return c2.db.scalar("SELECT state FROM media_labels WHERE label_id=? AND media_id=?", (travel2, b[name]))

        assert state("IMG_0.jpg") == "confirmed" and state("IMG_1.jpg") == "confirmed"  # yours stays
        pid2 = c2.db.scalar("SELECT id FROM people WHERE name='Asha'")
        assert c2.db.scalar("SELECT state FROM media_people WHERE media_id=? AND person_id=?", (b["IMG_2.jpg"], pid2)) == "confirmed"
        assert labels_io.waiting(c2) == 2  # the faces wait for the face pass
        g1 = add_face(c2, b["IMG_0.jpg"], BOX1, 3)
        g2 = add_face(c2, b["IMG_1.jpg"], (0.5001, 0.2, 0.7, 0.5), 4)  # found again, a hair apart
        labels_io.apply_waiting(c2, [b["IMG_0.jpg"], b["IMG_1.jpg"]])
        assert c2.db.scalar("SELECT person_id FROM faces WHERE id=?", (g1,)) == pid2
        assert c2.db.scalar("SELECT vote FROM face_votes WHERE face_id=? AND person_id=?", (g2, pid2)) == -1
        assert labels_io.waiting(c2) == 0
        again = labels_io.import_(c2, doc)  # importing twice changes nothing
        assert again.get("faces_applied", 0) == 0 and again.get("answers_applied", 0) == 0 and again["people_matched"] == 1
    finally:
        c2.stop()


def add_animal(ctx, media_id, box, seed, species="dog"):
    """An animal as the objects pass would store it (synthetic look)."""
    rng = np.random.default_rng(seed)
    emb = rng.normal(size=768)
    emb /= np.linalg.norm(emb)
    aid = ctx.db.x(
        "INSERT INTO animals(media_id, species, x1, y1, x2, y2, det_score, quality, embedding, state) VALUES(?,?,?,?,?,?,.9,.9,?,'none')",
        (media_id, species, *box, emb.astype(np.float16).tobytes()),
    ).lastrowid
    ctx.db.x("UPDATE media SET obj_v=? WHERE id=?", (OBJ_V, media_id))
    ctx.services["pets"].index.load_rows(ctx.db.q("SELECT id, media_id, quality, embedding FROM animals"))
    return aid


def test_pets_go_to_another_pc_too(ctx, tmp_path):
    photos(tmp_path / "A", n=2)
    add_and_index(ctx, tmp_path / "A")
    a = ids(ctx)
    pets = ctx.services["pets"]
    d1 = add_animal(ctx, a["IMG_0.jpg"], BOX1, 1)
    d2 = add_animal(ctx, a["IMG_1.jpg"], BOX2, 2)
    pid = pets.create_person("Bruno", [d1])
    pets.answer(pid, [], [d2])
    doc = labels_io.export(ctx)
    assert (labels_io.counts(doc)["pets"], labels_io.counts(doc)["animals"]) == (1, 2)
    assert doc["pets"][0]["name"] == "Bruno" and doc["pets"][0]["species"] == "dog" and doc["people"] == []

    shutil.copytree(tmp_path / "A", tmp_path / "B")
    c2 = build_context(Paths(tmp_path / "data2"), "t2")
    try:
        res = labels_io.import_(c2, doc)
        assert res["pets_added"] == 1 and res["waiting"] == 2
        add_and_index(c2, tmp_path / "B")
        b = ids(c2)
        labels_io.apply_waiting(c2, list(b.values()))
        assert labels_io.waiting(c2) == 2  # the photos are read; their animals aren't looked for yet
        g1 = add_animal(c2, b["IMG_0.jpg"], BOX1, 3)
        g2 = add_animal(c2, b["IMG_1.jpg"], (0.5001, 0.2, 0.7, 0.5), 4)  # found again, a hair apart
        labels_io.apply_waiting(c2, [b["IMG_0.jpg"], b["IMG_1.jpg"]])
        pid2 = c2.db.scalar("SELECT id FROM people WHERE name='Bruno'")
        assert tuple(c2.db.q1("SELECT kind, species FROM people WHERE id=?", (pid2,))) == ("pet", "dog")
        assert c2.db.scalar("SELECT person_id FROM animals WHERE id=?", (g1,)) == pid2
        assert c2.db.scalar("SELECT vote FROM animal_votes WHERE animal_id=? AND person_id=?", (g2, pid2)) == -1
        assert labels_io.waiting(c2) == 0
        assert c2.db.scalar("SELECT COUNT(*) FROM people WHERE kind='human'") == 0, "a pet never comes back as a person"
    finally:
        c2.stop()


def test_a_file_that_isnt_ours_is_refused(ctx):
    for bad in ({}, {"format": "something-else"}, {"format": "recpro-labels", "version": 99}):
        try:
            labels_io.import_(ctx, bad)
        except ValueError:
            continue
        raise AssertionError(f"accepted {bad}")


def test_saved_searches(ctx):
    s = routes_search.save_search(routes_search.SavedSearch(name=" Goa trips ", q="Goa trip", overrides={"years": []}), c=ctx)
    assert s["name"] == "Goa trips" and s["overrides"] == {"years": []}
    routes_search.rename_search(s["id"], routes_search.SavedRename(name="Beach days"), c=ctx)
    assert [x["name"] for x in routes_search.saved_searches(c=ctx)] == ["Beach days"]
    routes_search.delete_search(s["id"], c=ctx)
    assert routes_search.saved_searches(c=ctx) == []


def test_xmp_sidecars_never_touch_another_apps_file_or_a_private_photo(ctx, tmp_path):
    root = tmp_path / "A"
    photos(root, 5)
    add_and_index(ctx, root)
    a = ids(ctx)
    people = ctx.services["people"]
    people.create_person("Asha", [add_face(ctx, a["IMG_0.jpg"], BOX1, 1)])
    tax, travel = ctx.services["taxonomy"], ctx.services["labels"].id("activity.travel")
    tax.answer(travel, [a["IMG_1.jpg"], a["IMG_2.jpg"], a["IMG_3.jpg"]], [])
    theirs = root / "IMG_2.jpg.xmp"
    theirs.write_text("<x:xmpmeta xmlns:x='adobe:ns:meta/'><!-- Lightroom edits --></x:xmpmeta>", encoding="utf-8")
    ctx.db.x("UPDATE media SET sens_state='private' WHERE id=?", (a["IMG_3.jpg"],))
    w = xmp.Writer()
    w.start(ctx)
    wait_for(lambda: not w.status()["running"])
    st = w.status()
    assert st["written"] == 2 and st["kept_theirs"] == 1 and st["nothing"] == 1 and st["total"] == 4 and not st["error"]
    mine = (root / "IMG_0.jpg.xmp").read_text(encoding="utf-8")
    ET.fromstring(mine)  # well-formed
    assert "<rdf:li>Asha</rdf:li>" in mine and "People|Asha" in mine
    assert "Travel" in (root / "IMG_1.jpg.xmp").read_text(encoding="utf-8")
    assert "Lightroom edits" in theirs.read_text(encoding="utf-8")
    assert not (root / "IMG_3.jpg.xmp").exists()  # private: never
    w2 = xmp.Writer()  # a second run updates RecPro's own files
    w2.start(ctx)
    wait_for(lambda: not w2.status()["running"])
    assert w2.status()["written"] == 2
