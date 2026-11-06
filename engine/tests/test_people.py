"""People logic with synthetic face vectors (no GPU or models needed)."""
from __future__ import annotations

import time

import numpy as np

from recpro.review.search import search_people


def _unit(v):
    return v / np.linalg.norm(v)


def _seed_library(ctx, n_people=3, per_person=8, strangers=6, seed=1):
    rng = np.random.default_rng(seed)
    db = ctx.db
    now = time.time()
    with db.tx() as c:
        c.execute("INSERT INTO folders(path, added_at, status) VALUES('X:/lib', ?, 'ready')", (now,))
    centers = [_unit(rng.normal(size=512)) for _ in range(n_people)]
    truth: dict[int, int] = {}  # face id -> person index (-1 stranger)
    mid = 0
    rows = []
    for p, cen in enumerate(centers):
        for k in range(per_person):
            rows.append((p, _unit(cen + rng.normal(scale=0.035, size=512))))
    for _ in range(strangers):
        rows.append((-1, _unit(rng.normal(size=512))))
    with db.tx() as c:
        for p, emb in rows:
            mid += 1
            c.execute(
                "INSERT INTO media(id, folder_id, path, rel_dir, name, ext, kind, size, mtime, added_at, quick_v, deep_v, width, height) "
                "VALUES(?, 1, ?, '', ?, '.jpg', 'image', 1000, 0, ?, 1, 1, 100, 100)",
                (mid, f"X:/lib/{mid}.jpg", f"{mid}.jpg", now),
            )
            fid = c.execute(
                "INSERT INTO faces(media_id, x1, y1, x2, y2, det_score, quality, embedding, state) VALUES(?, .3, .3, .6, .6, .9, .9, ?, 'none')",
                (mid, emb.astype(np.float16).tobytes()),
            ).lastrowid
            truth[fid] = p
    people = ctx.services["people"]
    people.index.load_rows(db.q("SELECT id, media_id, quality, embedding FROM faces"))
    with people._lock:
        people._pending.update(truth)
    people.ready = True
    return people, truth


def test_grouping_and_naming(ctx):
    people, truth = _seed_library(ctx)
    people.assign_pending()
    people.cluster()
    groups = ctx.db.q("SELECT person_id, COUNT(*) n FROM faces WHERE state='cluster' GROUP BY person_id")
    assert len(groups) == 3
    assert all(g["n"] == 8 for g in groups)
    # every group is pure
    for g in groups:
        members = [r["id"] for r in ctx.db.q("SELECT id FROM faces WHERE person_id=?", (g["person_id"],))]
        assert len({truth[f] for f in members}) == 1
    # strangers stay ungrouped
    strangers = [f for f, p in truth.items() if p == -1]
    assert ctx.db.scalar(f"SELECT COUNT(*) FROM faces WHERE person_id IS NOT NULL AND id IN ({','.join(map(str, strangers))})") == 0

    pid = groups[0]["person_id"]
    people.rename(pid, "Asha")
    assert ctx.db.scalar("SELECT COUNT(*) FROM faces WHERE person_id=? AND state='auto'", (pid,)) == 8


def test_no_answer_sticks_and_undo(ctx):
    people, truth = _seed_library(ctx)
    people.assign_pending()
    people.cluster()
    pid = ctx.db.scalar("SELECT person_id FROM faces WHERE state='cluster' LIMIT 1")
    people.rename(pid, "Ravi")
    victim = ctx.db.scalar("SELECT id FROM faces WHERE person_id=? LIMIT 1", (pid,))
    people.answer(pid, [], [victim])
    assert ctx.db.scalar("SELECT person_id FROM faces WHERE id=?", (victim,)) is None
    # re-scoring never puts it back
    people.rescore_person(pid)
    assert ctx.db.scalar("SELECT COALESCE(person_id, 0) FROM faces WHERE id=?", (victim,)) != pid
    assert people.undo_last()
    assert ctx.db.scalar("SELECT COUNT(*) FROM face_votes WHERE face_id=?", (victim,)) == 0


def test_find_tiers_and_exclusivity(ctx):
    people, truth = _seed_library(ctx)
    people.assign_pending()
    people.cluster()
    pid = ctx.db.scalar("SELECT person_id FROM faces WHERE state='cluster' LIMIT 1")
    people.rename(pid, "Meera")
    res = search_people(ctx, [pid])
    found = {h["id"] for h in res["sure"]}
    target = {r["media_id"] for r in ctx.db.q("SELECT media_id FROM faces WHERE person_id=?", (pid,))}
    assert found == target
    assert res["check"] == [] or all(h["score"] < 0.5 for h in res["check"])
    # a face you confirmed for someone else is never offered for this person
    other = next(f for f, p in truth.items() if p != -1 and f not in {r["id"] for r in ctx.db.q("SELECT id FROM faces WHERE person_id=?", (pid,))})
    other_pid = ctx.db.scalar("SELECT person_id FROM faces WHERE id=?", (other,))
    if other_pid is None:
        other_pid = people.create_person("Other")
    people.answer(other_pid, [other], [])
    res2 = search_people(ctx, [pid])
    other_media = ctx.db.scalar("SELECT media_id FROM faces WHERE id=?", (other,))
    assert other_media not in {h["id"] for h in res2["sure"] + res2["check"]}


def test_never_two_faces_of_one_photo_in_a_group(ctx):
    people, _ = _seed_library(ctx, n_people=1, per_person=6, strangers=0)
    # duplicate the person's face inside one photo (mirror, poster…)
    row = ctx.db.q1("SELECT media_id, embedding FROM faces LIMIT 1")
    with ctx.db.tx() as c:
        fid = c.execute(
            "INSERT INTO faces(media_id, x1, y1, x2, y2, det_score, quality, embedding, state) VALUES(?, .7, .3, .9, .6, .9, .9, ?, 'none')",
            (row["media_id"], row["embedding"]),
        ).lastrowid
    people.index.load_rows(ctx.db.q("SELECT id, media_id, quality, embedding FROM faces WHERE id=?", (fid,)))
    people.cluster()
    per_media = ctx.db.q("SELECT media_id, person_id, COUNT(*) n FROM faces WHERE person_id IS NOT NULL GROUP BY media_id, person_id")
    assert all(r["n"] == 1 for r in per_media)
