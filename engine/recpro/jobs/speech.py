"""Speech pass: what is said in each video, with times, for search ("the video where we planned
the trip"). The last and slowest stage: one video at a time, after everything else."""
from __future__ import annotations

import logging
from typing import Any

from ..context import Context
from ..ids import mask_ids
from ..library.metadata import ffmpeg_bin
from ..library.video import audio as video_audio

log = logging.getLogger("recpro.speech")

SPEECH_V = 1


class SpeechStage:
    name = "speech"
    label = "Listening to videos"
    column = "speech_v"
    version = SPEECH_V
    kinds = ("video",)
    batch_size = 1
    order = "taken_at DESC"

    def __init__(self, ctx: Context):
        self.ctx = ctx

    @property
    def ml(self):
        return self.ctx.services["ml"]

    def available(self) -> bool:
        return bool(ffmpeg_bin()) and self.ml.speech_id() is not None  # type: ignore[attr-defined]

    def where(self) -> str:
        # private videos' words are never stored (nothing readable of them stays on disk)
        return "quick_v >= 1 AND duration IS NOT NULL AND duration >= 1 AND sens_state NOT IN ('private','review')"

    def process(self, rows: list[Any]) -> None:
        model = self.ml.speech()  # type: ignore[attr-defined]
        if model is None:
            return
        for row in rows:
            mid = int(row["id"])
            lang, segs = None, []
            try:
                pcm = video_audio(row["path"])
                if pcm is not None:
                    lang, segs = model.transcribe(pcm)
            except Exception as e:
                log.info("no speech for %s: %s", row["path"], e)
            with self.ctx.db.tx() as c:
                c.execute("DELETE FROM speech WHERE media_id=?", (mid,))
                c.executemany(
                    "INSERT INTO speech(media_id, start_ms, end_ms, lang, content) VALUES(?,?,?,?,?)",
                    [(mid, s.start_ms, s.end_ms, lang, mask_ids(s.text)) for s in segs],
                )
                c.execute("UPDATE media SET speech_v=? WHERE id=?", (SPEECH_V, mid))
            if segs:
                log.info("speech in %s: %d segments (%s)", row["name"], len(segs), lang)
