"""Semantic pass: SigLIP 2 image embeddings (for search) and prompt-based categories."""
from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import numpy as np

from ..context import Context
from ..labels import SENSITIVE
from .deep import load_rgb

log = logging.getLogger("recpro.semantic")

SEM_V = 1


class SemanticStage:
    name = "semantic"
    label = "Understanding photos"
    column = "sem_v"
    version = SEM_V
    kinds = ("image",)
    batch_size = 16
    order = "taken_at DESC"

    def __init__(self, ctx: Context):
        self.ctx = ctx
        self.pool = ThreadPoolExecutor(max_workers=max(4, min(8, (os.cpu_count() or 8) // 3)), thread_name_prefix="sem")
        self._prompt_cache: dict[str, tuple[list[Any], np.ndarray, list[int]]] = {}

    @property
    def ml(self):
        return self.ctx.services["ml"]

    def available(self) -> bool:
        return self.ml.semantic_id() is not None  # type: ignore[attr-defined]

    def where(self) -> str:
        return "quick_v >= 1 AND width IS NOT NULL"

    def label_matrix(self, model) -> tuple[list[Any], np.ndarray, list[int]]:
        """(label defs, prompt embedding matrix, label index of each prompt)."""
        key = model.name
        cached = self._prompt_cache.get(key)
        if cached is not None:
            return cached
        defs = list(SENSITIVE)
        extra = self.ctx.services.get("taxonomy")
        if extra is not None:
            defs += extra.defs()  # type: ignore[attr-defined]
        prompts, owner = [], []
        for i, d in enumerate(defs):
            for p in d.prompts:
                prompts.append(p)
                owner.append(i)
        T = model.embed_texts(prompts)
        self._prompt_cache[key] = (defs, T, owner)
        return defs, T, owner

    def invalidate_prompts(self) -> None:
        self._prompt_cache.clear()

    def process(self, rows: list[Any]) -> None:
        model = self.ml.siglip()  # type: ignore[attr-defined]
        if model is None:
            return
        labels = self.ctx.services["labels"]
        imgs = list(self.pool.map(lambda r: load_rgb(r["path"], 768), rows))
        ok = [(r, im) for r, im in zip(rows, imgs) if im is not None]
        E = model.embed_images([im for _, im in ok]) if ok else np.zeros((0, model.dim), np.float32)
        defs, T, owner = self.label_matrix(model)
        P = model.prob(E @ T.T) if len(ok) else np.zeros((0, len(owner)))
        owner_arr = np.array(owner)
        with self.ctx.db.tx() as c:
            for (r, _), e in zip(ok, E):
                c.execute(
                    "INSERT OR REPLACE INTO embeddings(media_id, model, frame_ms, vec) VALUES(?,?,-1,?)",
                    (r["id"], model.name, e.astype(np.float16).tobytes()),
                )
        for k, (r, _) in enumerate(ok):
            for i, d in enumerate(defs):
                p = float(P[k, owner_arr == i].max()) if (owner_arr == i).any() else 0.0
                labels.record(r["id"], d.key, {"siglip": p}, d.grp)  # type: ignore[attr-defined]
        with self.ctx.db.tx() as c:
            c.executemany("UPDATE media SET sem_v=? WHERE id=?", [(SEM_V, r["id"]) for r in rows])
        labels.update_sens_state([r["id"] for r in rows])  # type: ignore[attr-defined]
        index = self.ctx.services.get("semantic_index")
        if index is not None:
            index.add([(r["id"], e) for (r, _), e in zip(ok, E)])  # type: ignore[attr-defined]
