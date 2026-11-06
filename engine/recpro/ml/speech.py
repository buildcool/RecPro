"""Speech in videos as text with times: faster-whisper (CTranslate2) running Whisper.

CTranslate2's GPU build needs CUDA 12's cuBLAS, and RecPro carries CUDA 13, so speech normally runs
on the processor (int8, all physical cores); on a PC that has CUDA 12 it uses the graphics card. It
listens only where the voice detector hears speech, and drops segments Whisper itself thinks are
not speech (music, noise), which keeps it from inventing text over silence.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np

log = logging.getLogger("recpro.speech")


@dataclass
class Segment:
    start_ms: int
    end_ms: int
    text: str


class Transcriber:
    def __init__(self, folder: Path, use_gpu: bool = True, threads: int | None = None):
        from faster_whisper import WhisperModel

        self.model = None
        self.device = "cpu"
        if use_gpu:
            try:
                m = WhisperModel(str(folder), device="cuda", compute_type="float16")
                list(m.transcribe(np.zeros(16000, np.float32), beam_size=1)[0])  # the GPU libraries load on first use
                self.model, self.device = m, "cuda"
            except Exception as e:
                log.info("speech runs on the processor (%s)", str(e).splitlines()[0][:160] if str(e) else type(e).__name__)
        if self.model is None:
            cores = threads or max(4, (os.cpu_count() or 8) // 2)
            self.model = WhisperModel(str(folder), device="cpu", compute_type="int8", cpu_threads=cores)

    def transcribe(self, audio: np.ndarray) -> tuple[str | None, list[Segment]]:
        """audio: 16 kHz mono float32. Returns (language, segments)."""
        segments, info = self.model.transcribe(
            audio,
            beam_size=5,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
            condition_on_previous_text=False,  # one bad segment can't drag the rest into a loop
        )
        out: list[Segment] = []
        for s in segments:
            text = (s.text or "").strip()
            if not text or (s.no_speech_prob > 0.6 and s.avg_logprob < -1.0):
                continue
            out.append(Segment(int(round(s.start * 1000)), int(round(s.end * 1000)), text))
        return getattr(info, "language", None), out
