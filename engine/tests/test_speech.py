"""Speech in videos: decoded sound, stored segments with times, search that jumps to the words,
and nothing kept for private videos."""
from __future__ import annotations

import shutil
import subprocess

import numpy as np
import pytest

from recpro.ml.speech import Segment
from tests.conftest import add_and_index

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg is needed to make the test videos")


def make(folder, name, with_sound=True, seconds=3):
    folder.mkdir(parents=True, exist_ok=True)
    args = ["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=gray:s=160x120:d={seconds}:r=10"]
    if with_sound:
        args += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", "-c:a", "aac"]
    subprocess.run([*args, "-pix_fmt", "yuv420p", "-shortest", str(folder / name)], check=True)


class FakeTranscriber:
    def __init__(self):
        self.calls = 0

    def transcribe(self, pcm):
        self.calls += 1
        assert pcm.dtype == np.float32 and pcm.size > 16000
        return "en", [Segment(1000, 2500, "The family dinner moved to Sunday."), Segment(2500, 3000, "See you there.")]


def test_sound_is_decoded_for_speech_and_silent_videos_have_none(tmp_path):
    from recpro.library.video import audio

    make(tmp_path, "talk.mp4")
    make(tmp_path, "silent.mp4", with_sound=False)
    pcm = audio(str(tmp_path / "talk.mp4"))
    assert pcm is not None and abs(pcm.size - 3 * 16000) < 4000
    assert audio(str(tmp_path / "silent.mp4")) is None


def test_speech_pass_and_search_jump_to_the_words(ctx, tmp_path, monkeypatch):
    folder = tmp_path / "Videos"
    make(folder, "VID_20240301_090000.mp4")
    add_and_index(ctx, folder)
    fake = FakeTranscriber()
    ml = ctx.services["ml"]
    monkeypatch.setattr(ml, "speech", lambda: fake)
    monkeypatch.setattr(ml, "speech_id", lambda: "speech")
    from recpro.jobs.speech import SpeechStage
    from recpro.review.query import run

    db = ctx.db
    row = db.q1("SELECT * FROM media WHERE kind='video'")
    mid = row["id"]
    SpeechStage(ctx).process([row])
    segs = db.q("SELECT start_ms, end_ms, lang, content FROM speech WHERE media_id=? ORDER BY start_ms", (mid,))
    assert [(r["start_ms"], r["end_ms"], r["lang"]) for r in segs] == [(1000, 2500, "en"), (2500, 3000, "en")]
    assert db.scalar("SELECT speech_v FROM media WHERE id=?", (mid,)) == 1

    res = run(ctx, "family dinner")
    hit = next(h for h in res["sure"] + res["check"] if h["id"] == mid)
    assert hit["text_match"] and hit["at_ms"] == 1000
    assert hit["spans"][0]["start_ms"] == 1000

    # private videos keep nothing readable: their words are deleted, and they aren't listened to
    ctx.services["private"].on_became_private([mid])
    assert db.scalar("SELECT COUNT(*) FROM speech WHERE media_id=?", (mid,)) == 0
    db.x("UPDATE media SET sens_state='private', speech_v=0 WHERE id=?", (mid,))
    stage = SpeechStage(ctx)
    assert db.scalar(f"SELECT COUNT(*) FROM media WHERE kind='video' AND speech_v < 1 AND {stage.where()}") == 0
    # cleared again: listened to again
    ctx.services["private"].on_became_clear([mid])
    assert db.scalar("SELECT speech_v FROM media WHERE id=?", (mid,)) == 0
