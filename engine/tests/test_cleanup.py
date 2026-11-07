"""Cleanup: duplicate, copy and burst groups with the best shot kept, WhatsApp forwards, and removal
that only ever moves files to the RecPro Bin (Undo brings them back)."""
from __future__ import annotations

import os
import shutil
import time

import numpy as np
from PIL import Image, ImageFilter

from recpro import cleanup
from tests.conftest import add_and_index


def photo(path, seed=1, size=(640, 480), blur=0):
    rng = np.random.default_rng(seed)
    base = rng.integers(0, 255, (size[1] // 16, size[0] // 16, 3), dtype=np.uint8)
    im = Image.fromarray(base).resize(size, Image.Resampling.BICUBIC)  # smooth shapes, like a real scene
    edges = Image.fromarray(rng.integers(0, 255, (size[1], size[0], 3), dtype=np.uint8)).filter(ImageFilter.GaussianBlur(1))
    im = Image.blend(im, edges, 0.25)
    if blur:
        im = im.filter(ImageFilter.GaussianBlur(blur))
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path, quality=92)
    return path


def test_exact_duplicates_go_to_the_bin_and_undo_brings_them_back(ctx, tmp_path):
    lib = tmp_path / "Lib"
    a = photo(lib / "Trip" / "IMG_1001.jpg", 1)
    shutil.copy2(a, lib / "Backup" / "IMG_1001.jpg") if (lib / "Backup").mkdir(parents=True) is None else None
    shutil.copy2(a, lib / "Trip" / "IMG_1001 (1).jpg")
    add_and_index(ctx, lib)
    cleanup.forget()
    groups = cleanup.listing(ctx, "exact")["groups"]
    assert len(groups) == 1 and len(groups[0]) == 3
    keep = next(x for x in groups[0] if x["keep"])
    extra = [x["id"] for x in groups[0] if not x["keep"]]
    res = ctx.services["ops"].bin_media(extra, "Cleanup: duplicates", {m: keep["id"] for m in extra})
    assert res["removed"] == 2 and not res["skipped"]
    db = ctx.db
    assert db.scalar("SELECT COUNT(*) FROM media WHERE state='binned'") == 2
    assert os.path.exists(keep["path"])
    assert sum(1 for x in groups[0] if os.path.exists(x["path"])) == 1
    op = db.q1("SELECT kind, title FROM operations WHERE id=?", (res["op_id"],))
    assert op["kind"] == "cleanup" and op["title"] == "Cleanup: duplicates"
    undo = ctx.services["ops"].undo(res["op_id"])
    assert undo["restored"] == 2
    assert all(os.path.exists(x["path"]) for x in groups[0])
    assert db.scalar("SELECT COUNT(*) FROM media WHERE state='active'") == 3
    # restored cleanup files are plain files again, not copies the copy flow could remove
    assert db.scalar("SELECT COUNT(*) FROM op_items WHERE op_id=? AND state='restored'", (res["op_id"],)) == 2
    assert ctx.services["ops"].op_dict(res["op_id"])["removable"] == 0


def test_a_lookalike_with_a_different_middle_is_never_removed(ctx, tmp_path):
    lib = tmp_path / "Lib"
    a = photo(lib / "A" / "x.jpg", 2, size=(2000, 1500))
    data = bytearray(a.read_bytes())
    assert len(data) > 3 * 65536, "the change must fall between the first and last 64 KB"
    mid = len(data) // 2
    data[mid] ^= 0xFF  # same size, same first and last 64 KB, different content
    (lib / "B").mkdir(parents=True)
    (lib / "B" / "x.jpg").write_bytes(bytes(data))
    add_and_index(ctx, lib)
    cleanup.forget()
    g = cleanup.listing(ctx, "exact")["groups"]
    assert len(g) == 1, "the quick hash groups them for display"
    keep, other = g[0][0]["id"], g[0][1]["id"]
    res = ctx.services["ops"].bin_media([other], "Cleanup: duplicates", {other: keep})
    assert res["removed"] == 0 and "Not an exact copy" in res["skipped"][0]["reason"]
    assert os.path.exists(ctx.db.scalar("SELECT path FROM media WHERE id=?", (other,)))


def test_a_smaller_copy_is_grouped_and_the_larger_original_kept(ctx, tmp_path):
    lib = tmp_path / "Lib"
    a = photo(lib / "Camera" / "IMG_2001.jpg", 3, size=(1280, 960))
    Image.open(a).resize((640, 480), Image.Resampling.LANCZOS).save(lib / "Camera" / "IMG-20240501-WA0007.jpg", quality=70)
    photo(lib / "Camera" / "IMG_2002.jpg", 99)  # unrelated
    add_and_index(ctx, lib)
    cleanup.forget()
    g = cleanup.listing(ctx, "copies")["groups"]
    assert len(g) == 1 and len(g[0]) == 2
    kept = next(x for x in g[0] if x["keep"])
    assert kept["name"] == "IMG_2001.jpg"


def test_the_sharpest_shot_of_a_burst_is_kept(ctx, tmp_path):
    lib = tmp_path / "Lib" / "Party"
    scene = photo(tmp_path / "scene.jpg", 4, size=(900, 680))
    big = Image.open(scene)
    sharp = lib / "IMG_3001.jpg"
    lib.mkdir(parents=True)
    big.crop((0, 0, 640, 480)).save(sharp, quality=92)  # two shots of one scene, the camera moved a little
    big.crop((150, 110, 790, 590)).filter(ImageFilter.GaussianBlur(3)).save(lib / "IMG_3002.jpg", quality=92)
    photo(lib / "IMG_3003.jpg", 5)  # a different scene a few seconds later
    add_and_index(ctx, tmp_path / "Lib")
    db = ctx.db
    t = time.time() - 86400
    ids = {r["name"]: r["id"] for r in db.q("SELECT id, name FROM media")}
    for k, name in enumerate(("IMG_3001.jpg", "IMG_3002.jpg", "IMG_3003.jpg")):
        db.x("UPDATE media SET taken_at=? WHERE id=?", (t + 5 * k, ids[name]))
    rng = np.random.default_rng(0)
    v = rng.normal(size=16)
    same = v / np.linalg.norm(v)
    other = rng.normal(size=16)
    other /= np.linalg.norm(other)
    ctx.services["semantic_index"].add([(ids["IMG_3001.jpg"], same), (ids["IMG_3002.jpg"], same), (ids["IMG_3003.jpg"], other)])
    cleanup.forget()
    g = cleanup.listing(ctx, "bursts")["groups"]
    assert len(g) == 1 and {x["name"] for x in g[0]} == {"IMG_3001.jpg", "IMG_3002.jpg"}
    assert next(x for x in g[0] if x["keep"])["name"] == sharp.name


def test_whatsapp_forwards_are_found_by_name_and_folder(ctx, tmp_path):
    lib = tmp_path / "Lib"
    photo(lib / "WhatsApp Images" / "IMG-20240512-WA0003.jpg", 6)
    photo(lib / "Media" / "IMG-20240513-WA0011.jpg", 7)
    photo(lib / "Media" / "IMG_4001.jpg", 8)
    add_and_index(ctx, lib)
    cleanup.forget()
    names = {x["name"] for x in cleanup.listing(ctx, "forwards")["items"]}
    assert names == {"IMG-20240512-WA0003.jpg", "IMG-20240513-WA0011.jpg"}
    s = cleanup.summary(ctx)
    assert s["forwards"]["files"] == 2


def test_too_dark_is_measured_and_a_night_shot_with_lights_is_not(ctx, tmp_path):
    from recpro.jobs.quality import QualityStage

    lib = tmp_path / "Lib"
    lib.mkdir()
    rng = np.random.default_rng(3)
    Image.fromarray((rng.integers(0, 18, (480, 640, 3))).astype(np.uint8)).save(lib / "IMG_6001.jpg", quality=90)  # nearly black
    night = (rng.integers(0, 25, (480, 640, 3))).astype(np.uint8)
    night[100:180, 200:420] = 250  # city lights
    Image.fromarray(night).save(lib / "IMG_6002.jpg", quality=90)
    photo(lib / "IMG_6003.jpg", 9)
    add_and_index(ctx, lib)
    db = ctx.db
    QualityStage(ctx).process(db.q("SELECT * FROM media"))
    assert db.scalar("SELECT COUNT(*) FROM media WHERE quality_v=1 AND brightness IS NOT NULL") == 3
    cleanup.forget()
    names = {x["name"] for x in cleanup.listing(ctx, "dark")["items"]}
    assert names == {"IMG_6001.jpg"}
