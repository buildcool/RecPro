"""In-memory index of face (or animal) embeddings for fast matching (float16, growable)."""
from __future__ import annotations

import threading

import numpy as np

DIM = 512


class FaceIndex:
    def __init__(self, dim: int = DIM) -> None:
        self.dim = dim
        self._lock = threading.RLock()
        self._cap = 0
        self._n = 0
        self.ids = np.zeros(0, np.int64)
        self.media = np.zeros(0, np.int64)
        self.quality = np.zeros(0, np.float32)
        self.emb = np.zeros((0, dim), np.float16)
        self.valid = np.zeros(0, bool)
        self.pos: dict[int, int] = {}

    def __len__(self) -> int:
        return len(self.pos)

    def _grow(self, need: int) -> None:
        if self._n + need <= self._cap:
            return
        cap = max(1024, self._cap * 2, self._n + need)
        for name, shape, dt in (
            ("ids", (cap,), np.int64),
            ("media", (cap,), np.int64),
            ("quality", (cap,), np.float32),
            ("emb", (cap, self.dim), np.float16),
            ("valid", (cap,), bool),
        ):
            new = np.zeros(shape, dt)
            old = getattr(self, name)
            new[: self._n] = old[: self._n]
            setattr(self, name, new)
        self._cap = cap

    def add(self, ids, media, quality, emb16: np.ndarray) -> None:
        with self._lock:
            n = len(ids)
            if n == 0:
                return
            self._grow(n)
            s = self._n
            self.ids[s : s + n] = ids
            self.media[s : s + n] = media
            self.quality[s : s + n] = quality
            self.emb[s : s + n] = emb16
            self.valid[s : s + n] = True
            for i, fid in enumerate(ids):
                old = self.pos.get(int(fid))
                if old is not None:
                    self.valid[old] = False
                self.pos[int(fid)] = s + i
            self._n += n

    def remove(self, ids) -> None:
        with self._lock:
            for fid in ids:
                p = self.pos.pop(int(fid), None)
                if p is not None:
                    self.valid[p] = False

    def load_rows(self, rows) -> None:
        ids, media, q, emb = [], [], [], []
        for r in rows:
            ids.append(r["id"])
            media.append(r["media_id"])
            q.append(r["quality"])
            emb.append(np.frombuffer(r["embedding"], dtype=np.float16))
        if ids:
            self.add(np.array(ids), np.array(media), np.array(q, np.float32), np.stack(emb))

    def vectors(self, ids) -> np.ndarray:
        """float32 vectors for face ids (missing ids give zero rows)."""
        with self._lock:
            idx = [self.pos.get(int(i), -1) for i in ids]
            out = np.zeros((len(idx), self.dim), np.float32)
            have = [k for k, p in enumerate(idx) if p >= 0]
            if have:
                out[have] = self.emb[[idx[k] for k in have]].astype(np.float32)
            return out

    def snapshot(self):
        """(ids, media, quality, emb16) of all valid faces (copies of the index arrays)."""
        with self._lock:
            n = self._n
            mask = self.valid[:n]
            return self.ids[:n][mask].copy(), self.media[:n][mask].copy(), self.quality[:n][mask].copy(), self.emb[:n][mask].copy()

    def score_all(self, E: np.ndarray, k: int = 3, chunk: int = 20000) -> tuple[np.ndarray, np.ndarray]:
        """(face ids, top-k mean similarity to E) for every face, without copying the index."""
        with self._lock:
            n = self._n
            ids_out, sc_out = [], []
            for s in range(0, n, chunk):
                v = self.valid[s : s + chunk]
                if not v.any():
                    continue
                F = self.emb[s : s + chunk][v].astype(np.float32)
                ids_out.append(self.ids[s : s + chunk][v].copy())
                sc_out.append(topk_mean_sim(F, E, k))
            if not ids_out:
                return np.zeros(0, np.int64), np.zeros(0, np.float32)
            return np.concatenate(ids_out), np.concatenate(sc_out)

    def subset(self, face_ids) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """(ids, media, emb32) for the given face ids that exist in the index."""
        with self._lock:
            rows = [(int(f), self.pos[int(f)]) for f in face_ids if int(f) in self.pos]
            if not rows:
                return np.zeros(0, np.int64), np.zeros(0, np.int64), np.zeros((0, self.dim), np.float32)
            fids = np.array([r[0] for r in rows], np.int64)
            ps = np.array([r[1] for r in rows], np.int64)
            return fids, self.media[ps].copy(), self.emb[ps].astype(np.float32)


def topk_mean_sim(F: np.ndarray, E: np.ndarray, k: int = 3, chunk: int = 20000) -> np.ndarray:
    """For each row of F, the mean of its k highest cosine similarities to rows of E."""
    if len(E) == 0 or len(F) == 0:
        return np.full(len(F), -1.0, np.float32)
    k = max(1, min(k, len(E)))
    out = np.empty(len(F), np.float32)
    for s in range(0, len(F), chunk):
        S = F[s : s + chunk] @ E.T
        if k == 1:
            out[s : s + chunk] = S.max(axis=1)
        else:
            part = np.partition(S, -k, axis=1)[:, -k:]
            out[s : s + chunk] = part.mean(axis=1)
    return out
