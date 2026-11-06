"""In-memory index of SigLIP 2 image embeddings (float16) for search and categories."""
from __future__ import annotations

import logging
import threading
import time

import numpy as np

from .context import Context

log = logging.getLogger("recpro.semindex")


class SemanticIndex:
    def __init__(self, ctx: Context):
        self.ctx = ctx
        self._lock = threading.RLock()
        self.model: str | None = None
        self.ids = np.zeros(0, np.int64)
        self.E = np.zeros((0, 0), np.float16)
        self.pos: dict[int, int] = {}
        self.ready = False

    def start(self) -> None:
        threading.Thread(target=self.load, name="semindex", daemon=True).start()

    def _model_name(self) -> str | None:
        ml = self.ctx.services.get("ml")
        if ml is None:
            return None
        mid = ml.semantic_id()  # type: ignore[attr-defined]
        if mid is None:
            return None
        from .ml.models import spec

        return f"siglip2-{spec(mid).folder.split('/')[-1]}"

    def load(self) -> None:
        t0 = time.time()
        name = self._model_name()
        with self._lock:
            self.model = name
            if name is None:
                self.ready = True
                return
            rows = self.ctx.db.q("SELECT media_id, vec FROM embeddings WHERE model=? AND frame_ms=-1", (name,))
            if rows:
                self.ids = np.array([r["media_id"] for r in rows], np.int64)
                self.E = np.stack([np.frombuffer(r["vec"], dtype=np.float16) for r in rows])
            else:
                self.ids = np.zeros(0, np.int64)
                self.E = np.zeros((0, 0), np.float16)
            self.pos = {int(m): i for i, m in enumerate(self.ids)}
            self.ready = True
        log.info("semantic index: %d photos in %.1fs", len(self.ids), time.time() - t0)
        # warm up the model so the first search doesn't wait for it to load
        try:
            ml = self.ctx.services.get("ml")
            model = ml.siglip() if ml else None  # type: ignore[attr-defined]
            if model is not None:
                from .taxonomy import GENERIC_BG

                model.embed_texts(GENERIC_BG)
        except Exception:
            log.exception("semantic warm-up failed")

    def add(self, items: list[tuple[int, np.ndarray]]) -> None:
        if not items:
            return
        with self._lock:
            new_ids, new_vecs = [], []
            for mid, e in items:
                e16 = e.astype(np.float16)
                if mid in self.pos:
                    self.E[self.pos[mid]] = e16
                else:
                    new_ids.append(mid)
                    new_vecs.append(e16)
            if new_ids:
                V = np.stack(new_vecs)
                self.E = V if self.E.size == 0 else np.concatenate([self.E, V])
                start = len(self.ids)
                self.ids = np.concatenate([self.ids, np.array(new_ids, np.int64)])
                for k, mid in enumerate(new_ids):
                    self.pos[mid] = start + k

    def matrix(self) -> tuple[np.ndarray, np.ndarray]:
        with self._lock:
            if self.E.size == 0:
                return np.zeros(0, np.int64), np.zeros((0, 0), np.float32)
            return self.ids.copy(), self.E.astype(np.float32)

    def vectors(self, media_ids: list[int]) -> np.ndarray:
        with self._lock:
            idx = [self.pos[m] for m in media_ids if m in self.pos]
            if not idx:
                return np.zeros((0, self.E.shape[1] if self.E.size else 0), np.float32)
            return self.E[idx].astype(np.float32)

    def scores(self, q: np.ndarray, media_ids: list[int] | None = None, chunk: int = 50000) -> tuple[np.ndarray, np.ndarray]:
        """Cosine similarity of a text/image embedding with photos (optionally a subset)."""
        with self._lock:
            if self.E.size == 0:
                return np.zeros(0, np.int64), np.zeros(0, np.float32)
            if media_ids is not None:
                idx = np.array([self.pos[m] for m in media_ids if m in self.pos], np.int64)
                if idx.size == 0:
                    return np.zeros(0, np.int64), np.zeros(0, np.float32)
                return self.ids[idx].copy(), (self.E[idx].astype(np.float32) @ q).astype(np.float32)
            out = np.empty(len(self.ids), np.float32)
            for s in range(0, len(self.ids), chunk):
                out[s : s + chunk] = self.E[s : s + chunk].astype(np.float32) @ q
            return self.ids.copy(), out


def create(ctx: Context) -> SemanticIndex:
    return SemanticIndex(ctx)
