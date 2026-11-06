"""Faces that aren't visible: photos from the same outing as a person's photos are suggested,
and a yes counts in Find like a recognised face."""
from __future__ import annotations

import time

import numpy as np
from PIL import Image

from recpro.review.hidden import answer, suggestions
from recpro.review.search import search_people
from tests.conftest import add_and_index

T0 = time.mktime((2024, 5, 4, 10, 0, 0, 0, 0, -1))


def _library(tmp_path, ctx):
    trip, other = tmp_path / "Lib" / "Goa", tmp_path / "Lib" / "Other"
    trip.mkdir(parents=True)
    other.mkdir(parents=True)
    for i in range(6):
        Image.effect_noise((96, 72), 40 + i).convert("RGB").save(trip / f"IMG_{i}.jpg", quality=90)
    Image.effect_noise((96, 72), 70).convert("RGB").save(other / "IMG_x.jpg", quality=90)
    add_and_index(ctx, tmp_path / "Lib")
    db = ctx.db
    ids = {r["name"]: r["id"] for r in db.q("SELECT id, name FROM media")}
    # IMG_0 and IMG_1 show Rohit's face; IMG_2..4 are later the same day; IMG_5 is the next day
    when = {"IMG_0.jpg": 0, "IMG_1.jpg": 600, "IMG_2.jpg": 900, "IMG_3.jpg": 3 * 3600, "IMG_4.jpg": 1800, "IMG_5.jpg": 26 * 3600, "IMG_x.jpg": 300}
    for name, dt in when.items():
        db.x("UPDATE media SET taken_at=? WHERE id=?", (T0 + dt, ids[name]))
    pid = ctx.services["people"].create_person("Rohit")
    emb = np.zeros(512, np.float16).tobytes()
    # a face too unclear to recognise in every other photo (there's no image model in tests)
    for name in when:
        if name not in ("IMG_0.jpg", "IMG_1.jpg"):
            db.x("INSERT INTO faces(media_id, x1, y1, x2, y2, det_score, quality, embedding, state) VALUES(?, 0.1, 0.1, 0.2, 0.2, 0.5, 0.2, ?, 'none')",
                 (ids[name], emb))
    for name in ("IMG_0.jpg", "IMG_1.jpg"):
        db.x(
            """INSERT INTO faces(media_id, x1, y1, x2, y2, det_score, quality, embedding, person_id, state)
               VALUES(?, 0.2, 0.2, 0.5, 0.6, 0.9, 0.8, ?, ?, 'confirmed')""",
            (ids[name], emb, pid),
        )
    return pid, ids


def test_photos_from_the_same_outing_are_suggested_closest_first(ctx, tmp_path):
    pid, ids = _library(tmp_path, ctx)
    sug = [s["media_id"] for s in suggestions(ctx, pid)]
    # same folder within 3 hours of a photo of him, nearest first; not the next day, not another folder
    assert sug == [ids["IMG_2.jpg"], ids["IMG_4.jpg"], ids["IMG_3.jpg"]]
    # a photo whose faces are all clear (someone else's) isn't a "face not visible" case
    ctx.db.x("UPDATE faces SET quality=0.9 WHERE media_id=?", (ids["IMG_4.jpg"],))
    assert ids["IMG_4.jpg"] not in [s["media_id"] for s in suggestions(ctx, pid)]


def test_a_yes_counts_in_find_and_answers_are_not_asked_again(ctx, tmp_path):
    pid, ids = _library(tmp_path, ctx)
    before = search_people(ctx, [pid])
    assert before["hidden_more"] == 3
    assert ids["IMG_2.jpg"] not in {h["id"] for h in before["sure"]}
    answer(ctx, pid, yes=[ids["IMG_2.jpg"]], no=[ids["IMG_3.jpg"]])
    left = [s["media_id"] for s in suggestions(ctx, pid)]
    assert left == [ids["IMG_4.jpg"]]
    after = search_people(ctx, [pid])
    hit = next(h for h in after["sure"] if h["id"] == ids["IMG_2.jpg"])
    assert hit["face_id"] is None and hit["tier"] == "sure"
    assert ids["IMG_3.jpg"] not in {h["id"] for h in after["sure"] + after["check"]}
    assert after["hidden_more"] == 1
