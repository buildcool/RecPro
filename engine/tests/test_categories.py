"""Category scoring: private content uses absolute scores only; relative ones can't hide a photo."""
from __future__ import annotations

import zlib

import numpy as np

from recpro.labels import SENSITIVE
from recpro.taxonomy import BACKGROUND, BUILTIN, TEXT_BG, score_labels
from tests.conftest import add_and_index


class FakeSiglip:
    """Deterministic stand-in for SigLIP 2: one random unit vector per prompt list."""

    scale = 100.0

    def embed_texts(self, texts: list[str]) -> np.ndarray:
        rng = np.random.default_rng(zlib.crc32("|".join(texts).encode()))
        v = rng.normal(size=(len(texts), 8))
        return v / np.linalg.norm(v, axis=1, keepdims=True)

    def prob(self, cos: np.ndarray) -> np.ndarray:
        return 1.0 / (1.0 + np.exp(-(10.0 * cos - 5.0)))


def test_private_content_gets_only_absolute_scores():
    rng = np.random.default_rng(3)
    E = rng.normal(size=(4, 8))
    E /= np.linalg.norm(E, axis=1, keepdims=True)
    activity = [d for d in BUILTIN if d.grp == "activity"][:3]
    out = score_labels(FakeSiglip(), E, list(SENSITIVE) + activity)
    for d in SENSITIVE:
        assert set(out[d.key]) == {"siglip"}, "no relative score for private content"
    for d in activity:
        assert set(out[d.key]) == {"siglip", "siglip_rel"}
        assert np.all((out[d.key]["siglip_rel"] >= 0) & (out[d.key]["siglip_rel"] <= 1))


def test_text_images_have_somewhere_to_go():
    # documents and chats must not be forced into photo categories; People keeps its own list
    for grp in ("activity", "mood", "place", "object", "pet", "entertainment"):
        assert set(TEXT_BG) <= set(BACKGROUND[grp]), grp
    assert not set(TEXT_BG) & set(BACKGROUND["people"])
    assert "sensitive" not in BACKGROUND


def _state(ctx, mid: int) -> str:
    return ctx.db.scalar("SELECT sens_state FROM media WHERE id=?", (mid,))


def test_a_relative_score_never_makes_a_photo_private(ctx, library_dir):
    add_and_index(ctx, library_dir)
    labels = ctx.services["labels"]
    mid = ctx.db.scalar("SELECT id FROM media WHERE name='top.png'")
    labels.record_many([(mid, "sensitive.sexual", {"siglip_rel": 0.95, "siglip": 0.0001}, "sensitive")])
    labels.update_sens_state([mid])
    assert _state(ctx, mid) == "clear"
    # the absolute score and NudeNet still count
    labels.record_many([(mid, "sensitive.nudity", {"nudenet": 0.7}, "sensitive")])
    labels.update_sens_state([mid])
    assert _state(ctx, mid) == "private"


def test_upgrade_forgets_stored_relative_private_scores(ctx, library_dir):
    add_and_index(ctx, library_dir)
    labels = ctx.services["labels"]
    db = ctx.db
    mid = db.scalar("SELECT id FROM media WHERE name='top.png'")
    lid = labels.id("sensitive.sexual")
    # what v2 stored for a new photo: a relative score that made it "sure"
    db.x(
        "INSERT INTO media_labels(media_id, label_id, score, tier, state, source) VALUES(?,?,0.9,'sure','ai',?)",
        (mid, lid, '{"siglip_rel": 0.9, "siglip": 0.0001}'),
    )
    db.x("UPDATE media SET sens_state='private' WHERE id=?", (mid,))
    assert ctx.services["taxonomy"].drop_relative_private_scores() == 1
    row = db.q1("SELECT tier, source FROM media_labels WHERE media_id=? AND label_id=?", (mid, lid))
    assert row["tier"] == "no" and "siglip_rel" not in row["source"]
    assert _state(ctx, mid) == "clear"
    # your own answers are never touched
    labels.answer_sensitive([mid], "romance")
    assert ctx.services["taxonomy"].drop_relative_private_scores() == 0
    assert _state(ctx, mid) == "private"
