"""In-memory index of SigLIP 2 embeddings (float16) for search and categories.

Photos have one embedding each. Videos have one per scene (a frame is kept when the picture
changes), with its time, so a search can say where in the video the match is.
"""
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
        # videos: media id -> (frame times in ms, embeddings)
        self.frames: dict[int, tuple[np.ndarray, np.ndarray]] = {}
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
            grouped: dict[int, list] = {}
            for r in self.ctx.db.q("SELECT media_id, frame_ms, vec FROM embeddings WHERE model=? AND frame_ms>=0 ORDER BY media_id, frame_ms", (name,)):
                grouped.setdefault(int(r["media_id"]), []).append((int(r["frame_ms"]), np.frombuffer(r["vec"], dtype=np.float16)))
            self.frames = {m: (np.array([t for t, _ in v], np.int64), np.stack([e for _, e in v])) for m, v in grouped.items()}
            self.ready = True
        log.info("semantic index: %d photos, %d videos in %.1fs", len(self.ids), len(self.frames), time.time() - t0)
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

    def set_frames(self, media_id: int, items: list[tuple[int, np.ndarray]]) -> None:
        """A video's scene frames (replacing what was there)."""
        with self._lock:
            if items:
                self.frames[media_id] = (np.array([t for t, _ in items], np.int64), np.stack([e.astype(np.float16) for _, e in items]))
            else:
                self.frames.pop(media_id, None)

    def frame_matrix(self, media_ids: list[int] | None = None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """(video id per row, frame time per row, embeddings) for all videos or some."""
        with self._lock:
            keys = list(self.frames) if media_ids is None else [m for m in media_ids if m in self.frames]
            if not keys:
                return np.zeros(0, np.int64), np.zeros(0, np.int64), np.zeros((0, 0), np.float32)
            owners = np.concatenate([np.full(len(self.frames[m][0]), m, np.int64) for m in keys])
            times = np.concatenate([self.frames[m][0] for m in keys])
            E = np.concatenate([self.frames[m][1] for m in keys]).astype(np.float32)
            return owners, times, E

    def matrix(self) -> tuple[np.ndarray, np.ndarray]:
        with self._lock:
            if self.E.size == 0:
                return np.zeros(0, np.int64), np.zeros((0, 0), np.float32)
            return self.ids.copy(), self.E.astype(np.float32)

    def rows(self, media_ids: list[int]) -> tuple[np.ndarray, np.ndarray]:
        """(ids, embeddings) of the photos among media_ids that have one."""
        with self._lock:
            idx = [self.pos[m] for m in media_ids if m in self.pos]
            if not idx:
                return np.zeros(0, np.int64), np.zeros((0, self.E.shape[1] if self.E.size else 0), np.float32)
            return self.ids[idx].copy(), self.E[idx].astype(np.float32)

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
