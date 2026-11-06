"""Videos: face tracks become one face per person per video with time spans; private content and
categories get spans; scene frames reach the search index; results say where in the video."""
from __future__ import annotations

import shutil
import subprocess

import numpy as np
import pytest

from recpro.ml.faces import Face
from recpro.ml.tracks import FrameFace, build_tracks, identities, merge_tracks, point_spans, spans_of
from tests.conftest import add_and_index
from tests.test_categories import FakeSiglip

rng = np.random.default_rng(7)


def unit(v):
    return v / np.linalg.norm(v)


A, B = unit(rng.normal(size=512)), unit(rng.normal(size=512))


def noisy(e, s=0.25):
    return unit(e + s * unit(rng.normal(size=512)))


def ff(idx, emb, box=(0.4, 0.2, 0.6, 0.5), q=0.8, det=0.9):
    return FrameFace(idx, idx * 1000, np.array(box, np.float32), np.zeros((5, 2), np.float32), emb, det, q)


# ---- tracks ------------------------------------------------------------------------------------
def test_a_person_who_comes_back_is_one_face_with_two_spans():
    frames = [[ff(i, noisy(A))] for i in range(8)] + [[ff(i, noisy(B))] for i in range(8, 14)] + [[ff(i, noisy(A))] for i in range(14, 18)]
    people = identities(frames, 1000, 18000)
    assert len(people) == 2
    spans = sorted(p.spans for p in people)
    assert spans == [[(0, 8000), (14000, 18000)], [(8000, 14000)]]


def test_two_people_on_screen_together_are_never_merged():
    look_alike = unit(A + 0.9 * B)  # similar enough to A to tempt a merge
    frames = [[ff(i, noisy(A, 0.1), (0.1, 0.2, 0.3, 0.5)), ff(i, noisy(look_alike, 0.1), (0.6, 0.2, 0.8, 0.5))] for i in range(6)]
    assert len(merge_tracks(build_tracks(frames))) == 2


def test_a_face_turning_away_stays_in_its_track_when_it_barely_moves():
    side = unit(A + 1.6 * unit(rng.normal(size=512)))  # weak match, same place
    frames = [[ff(0, A)], [ff(1, side)], [ff(2, A)]]
    assert len(build_tracks(frames)) == 1


def test_a_single_weak_detection_is_not_a_person():
    assert identities([[ff(0, A, det=0.45)]], 1000, 1000) == []


def test_spans_join_short_gaps_and_points_last_until_the_next():
    assert spans_of([0, 1000, 2000, 7000, 8000], 1000, 9000) == [(0, 3000), (7000, 9000)], "4 missed frames: two appearances"
    assert spans_of([0, 4000], 1000, 5000) == [(0, 5000)], "up to 3 missed frames (blur, a turned head) is the same appearance"
    pts = [(0, 0.1), (2000, 0.7), (4000, 0.8), (6000, 0.2)]
    assert point_spans(pts, 0.5, 8000, 2000) == [(2000, 6000, 0.8)]


# ---- the video pass end to end -------------------------------------------------------------------
class FakeFaces:
    """A red frame shows person A, a blue frame person B (embeddings from the frame colour)."""

    def analyze_many(self, images):
        out = []
        for im in images:
            r, b = float(im[..., 0].mean()), float(im[..., 2].mean())
            emb = noisy(A, 0.1) if r > b else noisy(B, 0.1)
            h, w = im.shape[:2]
            out.append([Face(box=np.array([w * 0.3, h * 0.2, w * 0.6, h * 0.7], np.float32), kps=np.zeros((5, 2), np.float32),
                             det_score=0.9, embedding=emb.astype(np.float32), quality=0.8, age=40.0, male=0.9)])
        return out


class FakeNude:
    """Blue frames are "nudity" (stand-in for NudeNet)."""

    def scores(self, img, boxes):
        return float(img[..., 2].mean()) / 255.0

    def summarize(self, s):
        return {"nudity": 0.9 if s > 0.5 else 0.0, "suggestive": 0.0}


class FakeVideoSiglip(FakeSiglip):
    name = "siglip2-fake"
    dim = 8

    def embed_images(self, imgs):
        out = []
        for im in imgs:
            v = np.zeros(8)
            v[0 if im[..., 0].mean() > im[..., 2].mean() else 1] = 1.0
            out.append(v)
        return np.array(out, np.float32)


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg is needed to make and read the test video")
def test_video_pass_people_spans_private_spans_and_scenes(ctx, tmp_path, monkeypatch):
    folder = tmp_path / "Videos"
    folder.mkdir()
    video = folder / "VID_20240101_120000.mp4"
    # red 0-2 s, blue 2-6 s, red 6-8 s
    lavfi = "color=c=red:s=320x240:d=2:r=10[a];color=c=blue:s=320x240:d=4:r=10[b];color=c=red:s=320x240:d=2:r=10[c];[a][b][c]concat=n=3:v=1:a=0"
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-filter_complex", lavfi, "-pix_fmt", "yuv420p", str(video)], check=True)
    add_and_index(ctx, folder)
    ml = ctx.services["ml"]
    monkeypatch.setattr(ml, "faces", lambda: FakeFaces())
    monkeypatch.setattr(ml, "nsfw", lambda: FakeNude())
    monkeypatch.setattr(ml, "siglip", lambda: FakeVideoSiglip())
    from recpro.jobs.video import VideoStage

    db = ctx.db
    row = db.q1("SELECT * FROM media WHERE kind='video'")
    assert row["duration"] and row["width"] == 320
    VideoStage(ctx).process([row])
    mid = row["id"]

    faces = db.q("SELECT id, frame_ms FROM faces WHERE media_id=? ORDER BY id", (mid,))
    assert len(faces) == 2, "one face per person per video"
    spans = sorted([tuple(map(tuple, db.q("SELECT start_ms, end_ms FROM face_spans WHERE face_id=? ORDER BY start_ms", (f["id"],)))) for f in faces])
    assert spans == [((0, 2000), (6000, 8000)), ((2000, 6000),)]
    nud = db.q(
        "SELECT ls.start_ms, ls.end_ms FROM label_spans ls JOIN labels l ON l.id=ls.label_id WHERE ls.media_id=? AND l.key='sensitive.nudity'", (mid,)
    )
    assert [(r["start_ms"], r["end_ms"]) for r in nud] == [(2000, 6000)]
    assert db.scalar("SELECT sens_state FROM media WHERE id=?", (mid,)) == "private"
    scenes = db.q("SELECT frame_ms FROM embeddings WHERE media_id=? AND frame_ms>=0 ORDER BY frame_ms", (mid,))
    assert [r["frame_ms"] for r in scenes] == [0, 2000, 6000], "a frame is kept when the picture changes"
    owners, times, _ = ctx.services["semantic_index"].frame_matrix([mid])
    assert times.tolist() == [0, 2000, 6000]
    assert db.scalar("SELECT video_v FROM media WHERE id=?", (mid,)) == 1

    # analyzed again: the same people keep their names
    pid = ctx.services["people"].create_person("Test Red") if hasattr(ctx.services["people"], "create_person") else None
    if pid is not None:
        db.x("UPDATE faces SET person_id=?, state='confirmed' WHERE id=?", (pid, faces[0]["id"]))
        VideoStage(ctx).process([db.q1("SELECT * FROM media WHERE id=?", (mid,))])
        assert db.scalar("SELECT COUNT(*) FROM faces WHERE media_id=? AND person_id=? AND state='confirmed'", (mid, pid)) == 1

    # Find says where in the video the person is
    from recpro.review.search import search_people

    if pid is not None:
        priv = ctx.services["private"]
        assert search_people(ctx, [pid])["hidden_private"] == 1, "the video is private: hidden while locked"
        priv.setup("2468", "pin")
        priv.set_toggles(None, True)  # unlocked, shown everywhere
        res = search_people(ctx, [pid])
        hit = next(h for h in res["sure"] + res["check"] if h["id"] == mid)
        assert [(s["start_ms"], s["end_ms"]) for s in hit["spans"]] == [(0, 2000), (6000, 8000)]
        assert hit["at_ms"] == 0 and hit["spans"][0]["name"] == "Test Red"
