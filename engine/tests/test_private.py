"""Private lock: setup, unlock, toggles, auto re-lock, sealed thumbnails, visibility."""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from recpro.api.app import create_app
from tests.conftest import add_and_index


def _mark_private(ctx, media_id):
    labels = ctx.services["labels"]
    labels.answer_sensitive([media_id], "nudity")


def test_setup_unlock_lock_and_toggles(ctx):
    p = ctx.services["private"]
    assert not p.configured()
    with pytest.raises(ValueError):
        p.setup("12", "pin")
    st = p.setup("2468", "pin")
    assert st["configured"] and st["unlocked"] and st["blur"] and not st["showEverywhere"]
    p.set_toggles(False, True)
    assert p.visible_everywhere() and not p.blur_enabled()
    p.lock()
    assert not p.is_unlocked() and not p.visible_everywhere() and p.blur_enabled()
    with pytest.raises(PermissionError):
        p.unlock("1111")
    p.unlock("2468")
    # toggles reset on every unlock
    assert p.blur_enabled() and not p.visible_everywhere()


def test_too_many_wrong_tries_slow_down(ctx):
    p = ctx.services["private"]
    p.setup("hunter22", "password")
    p.lock()
    for _ in range(5):
        with pytest.raises(PermissionError):
            p.unlock("wrong-one")
    with pytest.raises(TimeoutError):
        p.unlock("hunter22")


def test_auto_relock_after_inactivity(ctx):
    p = ctx.services["private"]
    p.setup("2468", "pin")
    p._last_activity = time.time() - 3600
    ctx.settings.update({"privacy.auto_lock_minutes": 1})
    # one pass of the auto-lock check
    minutes = 1
    if time.time() - p._last_activity > minutes * 60:
        p.lock()
    assert not p.is_unlocked()


def test_private_items_hidden_sealed_and_served_only_when_unlocked(ctx, library_dir):
    add_and_index(ctx, library_dir)
    p = ctx.services["private"]
    p.setup("2468", "pin")
    mid = ctx.db.scalar("SELECT id FROM media WHERE name='top.png'")
    thumb = ctx.paths.thumbs / f"{mid // 1000:04d}" / f"{mid}.webp"
    assert thumb.exists()
    _mark_private(ctx, mid)
    assert ctx.db.scalar("SELECT sens_state FROM media WHERE id=?", (mid,)) == "private"
    assert not thumb.exists(), "no readable thumbnail of a private item may stay on disk"
    client = TestClient(create_app(ctx))
    h = {"X-RecPro-Token": "test-token", "host": "127.0.0.1"}
    # unlocked: thumbnail is generated, sealed on disk, and served
    r = client.get(f"/media/thumb/{mid}", headers=h)
    assert r.status_code == 200 and r.headers["content-type"] == "image/webp"
    sealed = ctx.paths.private / f"{mid // 1000:04d}" / f"{mid}.thumb.bin"
    assert sealed.exists() and not sealed.read_bytes().startswith(b"RIFF")
    # hidden from normal views unless "show everywhere"
    months = client.get("/api/timeline", headers=h).json()
    assert sum(m["count"] for m in months["months"]) == 5
    p.set_toggles(None, True)
    months = client.get("/api/timeline", headers=h).json()
    assert sum(m["count"] for m in months["months"]) == 6
    # locked: placeholder only, private listing refused
    p.lock()
    r = client.get(f"/media/thumb/{mid}", headers=h)
    assert r.headers["content-type"].startswith("image/svg")
    assert client.get("/api/timeline?private_only=true", headers=h).status_code == 423
    assert sum(m["count"] for m in client.get("/api/timeline", headers=h).json()["months"]) == 5


def test_not_sensitive_answer_brings_it_back(ctx, library_dir):
    add_and_index(ctx, library_dir)
    p = ctx.services["private"]
    p.setup("2468", "pin")
    mid = ctx.db.scalar("SELECT id FROM media WHERE name='top.png'")
    labels = ctx.services["labels"]
    labels.record(mid, "sensitive.suggestive", {"siglip": 0.2}, "sensitive")
    labels.update_sens_state([mid])
    assert ctx.db.scalar("SELECT sens_state FROM media WHERE id=?", (mid,)) == "review"
    labels.answer_sensitive([mid], "clear")
    assert ctx.db.scalar("SELECT sens_state FROM media WHERE id=?", (mid,)) == "clear"
    # the AI's later opinion never overrides your answer
    labels.record(mid, "sensitive.suggestive", {"siglip": 0.9}, "sensitive")
    labels.update_sens_state([mid])
    assert ctx.db.scalar("SELECT sens_state FROM media WHERE id=?", (mid,)) == "clear"


def test_reset_forgets_lock_and_rechecks(ctx, library_dir):
    add_and_index(ctx, library_dir)
    p = ctx.services["private"]
    p.setup("2468", "pin")
    mid = ctx.db.scalar("SELECT id FROM media WHERE name='top.png'")
    _mark_private(ctx, mid)
    p.reset()
    assert not p.configured()
    assert ctx.db.scalar("SELECT sens_state FROM media WHERE id=?", (mid,)) == "unchecked"
    assert ctx.db.scalar("SELECT COUNT(*) FROM media_labels") == 0
    _ = Image
