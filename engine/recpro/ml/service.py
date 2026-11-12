from __future__ import annotations

import gc
import logging
import os
import threading
import time
from typing import Any

from ..context import Context
from . import runtime
from .models import ModelManager

log = logging.getLogger("recpro.ml")

# Models unused this long give their memory back (graphics memory above all: games and other apps
# want it) and load again when needed, in a second or two. RECPRO_IDLE_RELEASE_S overrides it.
IDLE_S = float(os.environ.get("RECPRO_IDLE_RELEASE_S", "300"))


class ML:
    """Owns the model manager and lazily-created inference engines."""

    def __init__(self, ctx: Context):
        self.ctx = ctx
        self.models = ModelManager(ctx.paths.models, ctx.events, lambda: bool(ctx.settings.get("privacy.strict_offline")))
        self._lock = threading.Lock()
        self._engines: dict[str, Any] = {}
        self._used: dict[str, float] = {}  # engine -> when it was last handed out
        self._stop = threading.Event()
        self.models.on_installed.append(self._on_installed)
        runtime.set_gpu_pack(self.models.path("gpu"))

    def start(self) -> None:
        self.models.start()
        threading.Thread(target=self._reap, name="ml-idle", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
        self.models.stop()

    def _reap(self) -> None:
        while not self._stop.wait(min(60.0, max(1.0, IDLE_S / 5))):
            try:
                self.release_idle()
            except Exception:
                log.exception("couldn't release idle models")

    def release_idle(self, idle_s: float = IDLE_S) -> list[str]:
        """Lets go of models unused for idle_s seconds. SigLIP keeps its text tower for searches."""
        now = time.monotonic()
        freed: list[str] = []
        with self._lock:
            for key in list(self._engines):
                eng = self._engines[key]
                if hasattr(eng, "release_gpu"):
                    if eng.release_gpu(idle_s):
                        freed.append(f"{key} (image tower)")
                elif now - self._used.get(key, now) >= idle_s:
                    del self._engines[key]
                    self._used.pop(key, None)
                    freed.append(key)
        if freed:
            gc.collect()  # the sessions go now, and with them their memory
            log.info("released after %.0f s idle: %s", idle_s, ", ".join(freed))
        return freed

    def _hand_out(self, key: str, eng: Any) -> Any:
        self._used[key] = time.monotonic()
        return eng

    @property
    def use_gpu(self) -> bool:
        return bool(self.ctx.settings.get("performance.use_gpu", True))

    def device_info(self) -> dict[str, Any]:
        return runtime.device_info(self.use_gpu)

    def has(self, model_id: str) -> bool:
        return self.models.installed(model_id)

    def faces(self):
        """FaceAnalyzer (detector + recognizer + age/gender), or None if not installed."""
        if not self.has("faces"):
            return None
        with self._lock:
            fa = self._engines.get("faces")
            if fa is None:
                from .faces import FaceAnalyzer

                fa = FaceAnalyzer(self.models.path("faces"), use_gpu=self.use_gpu)
                self._engines["faces"] = fa
            return self._hand_out("faces", fa)

    def nsfw(self):
        if not self.has("nudenet"):
            return None
        with self._lock:
            d = self._engines.get("nudenet")
            if d is None:
                from .nsfw import NudeDetector

                d = NudeDetector(self.models.path("nudenet") / "640m.onnx", use_gpu=self.use_gpu)
                self._engines["nudenet"] = d
            return self._hand_out("nudenet", d)

    def emotion(self):
        if not self.has("emotion"):
            return None
        with self._lock:
            m = self._engines.get("emotion")
            if m is None:
                from .emotion import EmotionModel

                m = EmotionModel(self.models.path("emotion") / "enet_b2_8.onnx", use_gpu=self.use_gpu)
                self._engines["emotion"] = m
            return self._hand_out("emotion", m)

    def ocr(self):
        if not self.has("ocr"):
            return None
        langs = tuple(self.ctx.settings.get("ocr.languages", ["en", "hi"]) or ["en"])
        key = f"ocr:{','.join(langs)}"
        with self._lock:
            m = self._engines.get(key)
            if m is None:
                from .ocr import OCR

                # the languages changed: free the old reader's GPU memory first
                for k in [k for k in self._engines if k.startswith("ocr:")]:
                    del self._engines[k]
                m = OCR(self.models.path("ocr"), use_gpu=self.use_gpu, languages=langs)
                self._engines[key] = m
            return self._hand_out(key, m)

    def speech_id(self) -> str | None:
        """Which speech model to use: the profile's choice if installed, else whichever is."""
        prefer = "speech" if self.ctx.settings.get("models.profile", "best") == "best" else "speech-fast"
        for mid in (prefer, "speech", "speech-fast"):
            if self.has(mid):
                return mid
        return None

    def speech(self):
        mid = self.speech_id()
        if mid is None:
            return None
        with self._lock:
            m = self._engines.get(mid)
            if m is None:
                from .speech import Transcriber

                m = Transcriber(self.models.path(mid), use_gpu=self.use_gpu)
                self._engines[mid] = m
            return self._hand_out(mid, m)

    def semantic_id(self) -> str | None:
        """Which SigLIP model to use: the profile's choice if installed, else whichever is."""
        prefer = "siglip2" if self.ctx.settings.get("models.profile", "best") == "best" else "siglip2-fast"
        for mid in (prefer, "siglip2", "siglip2-fast"):
            if self.has(mid):
                return mid
        return None

    def siglip(self):
        mid = self.semantic_id()
        if mid is None:
            return None
        with self._lock:
            s = self._engines.get(mid)
            if s is None:
                from .models import spec
                from .semantic import Siglip

                p = spec(mid).params
                s = Siglip(self.models.path(mid), use_gpu=self.use_gpu, logit_scale=p["logit_scale"], logit_bias=p["logit_bias"])
                self._engines[mid] = s
            return self._hand_out(mid, s)

    def objects_id(self) -> str | None:
        """Which object detector to use: the profile's choice if installed, else whichever is."""
        prefer = "objects" if self.ctx.settings.get("models.profile", "best") == "best" else "objects-fast"
        for mid in (prefer, "objects", "objects-fast"):
            if self.has(mid):
                return mid
        return None

    def objects(self):
        """The object detector (D-FINE), or None if not installed."""
        mid = self.objects_id()
        if mid is None:
            return None
        key = f"{mid}:detector"
        with self._lock:
            d = self._engines.get(key)
            if d is None:
                from .objects import ObjectDetector

                d = ObjectDetector(self.models.path(mid) / "detector.onnx", use_gpu=self.use_gpu)
                self._engines[key] = d
            return self._hand_out(key, d)

    def petlook(self):
        """DINOv2 for telling animals apart, or None if not installed."""
        if not self.has("pets"):
            return None
        with self._lock:
            m = self._engines.get("pets")
            if m is None:
                from .petlook import PetLook

                m = PetLook(self.models.path("pets") / "model.onnx", use_gpu=self.use_gpu)
                self._engines["pets"] = m
            return self._hand_out("pets", m)

    def _on_installed(self, model_id: str) -> None:
        with self._lock:
            self._engines.pop(model_id, None)
            for k in [k for k in self._engines if k.startswith(f"{model_id}:")]:
                del self._engines[k]
            if model_id == "gpu":
                # models loaded so far run on the processor: load them again on the graphics card
                self._engines.clear()
        if model_id == "gpu":
            runtime.reload_gpu()
        if model_id in ("faces", "nudenet", "siglip2", "siglip2-fast"):
            # videos watched without this model are watched again with it
            self.ctx.db.x("UPDATE media SET video_v=0 WHERE kind='video'")
        if model_id == "pets":
            # photos read before the pet model arrived: read again those with an animal to tell apart
            from .objects import CLASS
            from ..review.pets import MIN_DET, SPECIES

            classes = ",".join(str(CLASS[n]) for n in SPECIES)
            self.ctx.db.x(
                f"UPDATE media SET obj_v=0 WHERE id IN (SELECT DISTINCT media_id FROM objects WHERE cls IN ({classes}) AND score >= ?)"
                " AND id NOT IN (SELECT media_id FROM animals)",
                (MIN_DET,),
            )
        if model_id == "emotion":
            # photos analyzed before the expression model arrived get their faces' expressions now
            self.ctx.db.x(
                "UPDATE media SET deep_v=1 WHERE id IN (SELECT DISTINCT media_id FROM faces WHERE emotion IS NULL AND frame_ms IS NULL)"
            )
        indexer = self.ctx.services.get("indexer")
        if indexer is not None:
            indexer.wake()  # type: ignore[attr-defined]


def create(ctx: Context) -> ML:
    return ML(ctx)
