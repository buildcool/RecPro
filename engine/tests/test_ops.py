from __future__ import annotations

import os
from pathlib import Path

import pytest

from recpro.ops.fsutil import BIN_DIR
from tests.conftest import add_and_index, wait_for


def _ops(ctx):
    return ctx.services["ops"]


def _wait_done(ctx, op_id):
    return wait_for(lambda: _ops(ctx).op_dict(op_id)["status"] in ("done", "failed", "cancelled") and _ops(ctx).op_dict(op_id))


def test_copy_verifies_and_keeps_structure(ctx, library_dir, tmp_path):
    add_and_index(ctx, library_dir)
    ids = [r["id"] for r in ctx.db.q("SELECT id FROM media ORDER BY id")]
    dest = tmp_path / "Out"
    op = _ops(ctx).start_copy(ids, str(dest), structure="keep")
    res = _wait_done(ctx, op)
    assert res["status"] == "done"
    assert res["counts"].get("verified") == len(ids)
    copied = sorted(str(p.relative_to(dest)) for p in dest.rglob("*") if p.is_file())
    assert os.path.join("Photos", "Trip", "img_0.jpg") in copied
    assert os.path.join("Photos", "top.png") in copied
    # originals untouched until the user decides
    assert (library_dir / "top.png").exists()
    assert not list(dest.rglob("*.recpro-part"))


def test_remove_to_bin_then_undo_restores_exactly(ctx, library_dir, tmp_path):
    add_and_index(ctx, library_dir)
    ids = [r["id"] for r in ctx.db.q("SELECT id FROM media ORDER BY id")]
    before = {p: p.read_bytes() for p in library_dir.rglob("*") if p.is_file()}
    op = _ops(ctx).start_copy(ids, str(tmp_path / "Out"), structure="flat")
    _wait_done(ctx, op)
    r = _ops(ctx).remove_originals(op, "bin")
    assert r["removed"] == len(ids)
    assert not any(p.exists() for p in before)
    states = {row["state"] for row in ctx.db.q("SELECT state FROM media")}
    assert states == {"binned"}
    # The bin lives on the same drive (here: the test's bin root), with a README
    bin_dir = tmp_path / "binroot" / BIN_DIR
    assert (bin_dir / "README.txt").exists()
    assert list((bin_dir / f"op-{op}").rglob("top.png"))
    u = _ops(ctx).undo(op)
    assert u["restored"] == len(ids)
    for p, data in before.items():
        assert p.exists() and p.read_bytes() == data
    assert {row["state"] for row in ctx.db.q("SELECT state FROM media")} == {"active"}


def test_changed_original_is_never_removed(ctx, library_dir, tmp_path):
    add_and_index(ctx, library_dir)
    mid = ctx.db.scalar("SELECT id FROM media WHERE name='top.png'")
    op = _ops(ctx).start_copy([mid], str(tmp_path / "Out"), structure="flat")
    _wait_done(ctx, op)
    src = library_dir / "top.png"
    src.write_bytes(src.read_bytes() + b"changed")
    os.utime(src, (src.stat().st_atime, src.stat().st_mtime + 10))
    r = _ops(ctx).remove_originals(op, "bin")
    assert r["removed"] == 0
    assert src.exists()
    assert "Changed" in r["skipped"][0]["reason"]


def test_identical_file_at_destination_counts_as_verified(ctx, library_dir, tmp_path):
    add_and_index(ctx, library_dir)
    mid = ctx.db.scalar("SELECT id FROM media WHERE name='top.png'")
    dest = tmp_path / "Out"
    dest.mkdir()
    (dest / "top.png").write_bytes((library_dir / "top.png").read_bytes())
    op = _ops(ctx).start_copy([mid], str(dest), structure="flat")
    res = _wait_done(ctx, op)
    assert res["counts"].get("identical") == 1
    assert len(list(dest.iterdir())) == 1


def test_conflict_rename_keeps_both(ctx, library_dir, tmp_path):
    add_and_index(ctx, library_dir)
    mid = ctx.db.scalar("SELECT id FROM media WHERE name='top.png'")
    dest = tmp_path / "Out"
    dest.mkdir()
    (dest / "top.png").write_bytes(b"different content")
    op = _ops(ctx).start_copy([mid], str(dest), structure="flat", conflict="rename")
    res = _wait_done(ctx, op)
    assert res["counts"].get("verified") == 1
    assert sorted(p.name for p in dest.iterdir()) == ["top (1).png", "top.png"]
    assert (dest / "top.png").read_bytes() == b"different content"


def test_interrupted_copy_resumes(ctx, library_dir, tmp_path):
    add_and_index(ctx, library_dir)
    ids = [r["id"] for r in ctx.db.q("SELECT id FROM media ORDER BY id")]
    ops = _ops(ctx)
    op = ops.start_copy(ids, str(tmp_path / "Out"), structure="flat")
    _wait_done(ctx, op)
    # Simulate a crash mid-way: mark two items pending again and leave a partial file
    items = ctx.db.q("SELECT * FROM op_items WHERE op_id=? ORDER BY id LIMIT 2", (op,))
    for it in items:
        os.remove(it["dst"])
        Path(it["dst"] + ".recpro-part").write_bytes(b"partial")
        ctx.db.x("UPDATE op_items SET state='pending' WHERE id=?", (it["id"],))
    ctx.db.x("UPDATE operations SET status='running' WHERE id=?", (op,))
    ops.start()  # what happens at engine startup
    assert ops.op_dict(op)["status"] == "paused"
    assert not list((tmp_path / "Out").glob("*.recpro-part"))
    ops.resume(op)
    res = _wait_done(ctx, op)
    assert res["status"] == "done"
    assert res["counts"].get("verified") == len(ids)


def test_empty_bin_only_deletes_inside_bin(ctx, library_dir, tmp_path):
    add_and_index(ctx, library_dir)
    mid = ctx.db.scalar("SELECT id FROM media WHERE name='top.png'")
    op = _ops(ctx).start_copy([mid], str(tmp_path / "Out"), structure="flat")
    _wait_done(ctx, op)
    _ops(ctx).remove_originals(op, "bin")
    item = ctx.db.q1("SELECT * FROM op_items WHERE op_id=?", (op,))
    assert BIN_DIR in item["removed_to"]
    res = _ops(ctx).empty_bin([op])
    assert res["deleted"] == 1
    assert not os.path.exists(item["removed_to"])
    assert (tmp_path / "Out" / "top.png").exists()  # the copy is untouched
    assert ctx.db.scalar("SELECT COUNT(*) FROM media WHERE id=?", (mid,)) == 0


def test_move_mode_bins_originals_after_verify(ctx, library_dir, tmp_path):
    add_and_index(ctx, library_dir)
    mid = ctx.db.scalar("SELECT id FROM media WHERE name='top.png'")
    op = _ops(ctx).start_copy([mid], str(tmp_path / "Out"), structure="flat", mode="move")
    wait_for(lambda: _ops(ctx).op_dict(op)["removal"] == "bin")
    assert not (library_dir / "top.png").exists()
    assert (tmp_path / "Out" / "top.png").exists()


@pytest.mark.parametrize("structure,expected", [("date", "Unknown date"), ("person", "Asha")])
def test_structures(ctx, library_dir, tmp_path, structure, expected):
    add_and_index(ctx, library_dir)
    mid = ctx.db.scalar("SELECT id FROM media WHERE name='top.png'")
    ctx.db.x("UPDATE media SET taken_at=NULL WHERE id=?", (mid,))
    p = _ops(ctx).plan([mid], str(tmp_path / "Out"), structure=structure, person_by_media={mid: "Asha"})
    assert expected in p["items"][0]["dst"]
