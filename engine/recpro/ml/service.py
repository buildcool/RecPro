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

    def _on_installed(self, model_id: str) -> None:
        with self._lock:
            self._engines.pop(model_id, None)
        indexer = self.ctx.services.get("indexer")
        if indexer is not None:
            indexer.wake()  # type: ignore[attr-defined]


def create(ctx: Context) -> ML:
    return ML(ctx)
