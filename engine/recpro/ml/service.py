from __future__ import annotations

import logging
import threading
from typing import Any

from ..context import Context
from . import runtime
from .models import ModelManager

log = logging.getLogger("recpro.ml")


class ML:
    """Owns the model manager and lazily-created inference engines."""

    def __init__(self, ctx: Context):
        self.ctx = ctx
        self.models = ModelManager(ctx.paths.models, ctx.events, lambda: bool(ctx.settings.get("privacy.strict_offline")))
        self._lock = threading.Lock()
        self._engines: dict[str, Any] = {}
        self.models.on_installed.append(self._on_installed)
        runtime.set_gpu_pack(self.models.path("gpu"))

    def start(self) -> None:
        self.models.start()

    def stop(self) -> None:
        self.models.stop()

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
            return fa

    def nsfw(self):
        if not self.has("nudenet"):
            return None
        with self._lock:
            d = self._engines.get("nudenet")
            if d is None:
                from .nsfw import NudeDetector

                d = NudeDetector(self.models.path("nudenet") / "640m.onnx", use_gpu=self.use_gpu)
                self._engines["nudenet"] = d
            return d

    def emotion(self):
        if not self.has("emotion"):
            return None
        with self._lock:
            m = self._engines.get("emotion")
            if m is None:
                from .emotion import EmotionModel

                m = EmotionModel(self.models.path("emotion") / "enet_b2_8.onnx", use_gpu=self.use_gpu)
                self._engines["emotion"] = m
            return m

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
            return m

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
            return s

    def _on_installed(self, model_id: str) -> None:
        with self._lock:
            self._engines.pop(model_id, None)
            if model_id == "gpu":
                # models loaded so far run on the processor: load them again on the graphics card
                self._engines.clear()
        if model_id == "gpu":
            runtime.reload_gpu()
        if model_id in ("faces", "nudenet", "siglip2", "siglip2-fast"):
            # videos watched without this model are watched again with it
            self.ctx.db.x("UPDATE media SET video_v=0 WHERE kind='video'")
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
