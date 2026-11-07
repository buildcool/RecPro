"""SigLIP 2 image and text embeddings (multilingual), for search and categories."""
from __future__ import annotations

import string
import threading
import time
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

from .runtime import session

_PUNCT = str.maketrans("", "", string.punctuation)


def canonicalize(text: str) -> str:
    """OpenCLIP's text cleaning for SigLIP: no punctuation, lower case, single spaces."""
    text = text.replace("_", " ").translate(_PUNCT).lower()
    return " ".join(text.split()).strip()


class Siglip:
    def __init__(self, folder: Path, use_gpu: bool = True, logit_scale: float = 4.6991615, logit_bias: float = -15.932409):
        folder = Path(folder)
        self.scale = float(np.exp(logit_scale))
        self.bias = float(logit_bias)
        self._vpath, self._use_gpu = folder / "visual" / "model.onnx", use_gpu
        self._visual = session(self._vpath, use_gpu)
        self._vlock = threading.Lock()
        self._vused = time.monotonic()
        # The text tower (≈1.7 GB, mostly a 256k-token embedding) stays on the CPU: it only encodes
        # search queries and category prompts (cached), and keeping it off the GPU avoids
        # overflowing 8 GB of VRAM into slow shared memory.
        self.textual = session(folder / "textual" / "model.onnx", use_gpu=False, threads=8)
        self.v_in = self.visual.get_inputs()[0].name
        self.t_in = self.textual.get_inputs()[0].name
        shape = self.visual.get_inputs()[0].shape
        self.size = int(shape[2]) if isinstance(shape[2], int) else 384
        self.batch_fixed = isinstance(shape[0], int)
        self.ctx_len = int(self.textual.get_inputs()[0].shape[1])
        from tokenizers import Tokenizer

        self.tok = Tokenizer.from_file(str(folder / "textual" / "tokenizer.json"))
        self.dim = int(self.visual.get_outputs()[0].shape[-1])
        self._lock = threading.Lock()
        self.name = f"siglip2-{folder.name}"
        # Prompt embeddings persist across restarts (the text tower runs on the CPU)
        self._cache_path = folder / "text-cache.npz"
        self._disk: dict[str, np.ndarray] = {}
        self._dirty = 0
        try:
            with np.load(self._cache_path, allow_pickle=False) as z:
                keys = list(z["keys"])
                vecs = z["vecs"]
                self._disk = {str(k): vecs[i] for i, k in enumerate(keys)}
        except Exception:
            self._disk = {}

    # ---- images ----------------------------------------------------------------------
    @property
    def visual(self):
        """The image tower, on the graphics card; loaded again if it was let go while idle."""
        with self._vlock:
            if self._visual is None:
                self._visual = session(self._vpath, self._use_gpu)
            self._vused = time.monotonic()
            return self._visual

    def release_gpu(self, idle_s: float) -> bool:
        """Lets the image tower go after idle_s seconds unused, giving its graphics memory back.
        The text tower stays: it runs on the processor and every search needs it."""
        with self._vlock:
            if self._visual is None or time.monotonic() - self._vused < idle_s:
                return False
            self._visual = None
            return True

    def preprocess(self, img: np.ndarray) -> np.ndarray:
        x = cv2.resize(img, (self.size, self.size), interpolation=cv2.INTER_CUBIC)  # "squash", like training
        return ((x.astype(np.float32) / 255.0 - 0.5) / 0.5).transpose(2, 0, 1)

    def embed_images(self, imgs: list[np.ndarray]) -> np.ndarray:
        if not imgs:
            return np.zeros((0, self.dim), np.float32)
        out = []
        if self.batch_fixed:
            for im in imgs:
                out.append(self.visual.run(None, {self.v_in: self.preprocess(im)[None]})[0][0])
        else:
            blob = np.stack([self.preprocess(im) for im in imgs])
            out = list(self.visual.run(None, {self.v_in: blob})[0])
        e = np.stack(out).astype(np.float32)
        return e / (np.linalg.norm(e, axis=1, keepdims=True) + 1e-9)

    # ---- text -------------------------------------------------------------------------
    def tokenize(self, text: str) -> np.ndarray:
        ids = self.tok.encode(canonicalize(text)).ids[: self.ctx_len]
        if ids and ids[-1] != 1:
            ids[-1:] = [1]  # make sure <eos> survives truncation
        arr = np.zeros((1, self.ctx_len), dtype=np.int32)
        arr[0, : len(ids)] = ids
        return arr

    def embed_text(self, text: str) -> np.ndarray:
        key = canonicalize(text)
        v = self._disk.get(key)
        if v is not None:
            return v.astype(np.float32)
        v = _cached_text(self, text)
        self._disk[key] = v.astype(np.float16)
        self._dirty += 1
        if self._dirty >= 8:
            self.save_cache()
        return v

    def save_cache(self) -> None:
        if not self._dirty:
            return
        try:
            keys = np.array(list(self._disk.keys()))
            vecs = np.stack(list(self._disk.values())).astype(np.float16)
            tmp = self._cache_path.with_suffix(".tmp.npz")
            np.savez(tmp, keys=keys, vecs=vecs)
            tmp.replace(self._cache_path)
            self._dirty = 0
        except Exception:
            pass

    def embed_texts(self, texts: list[str]) -> np.ndarray:
        out = np.stack([self.embed_text(t) for t in texts]) if texts else np.zeros((0, self.dim), np.float32)
        self.save_cache()
        return out

    def prob(self, cos: np.ndarray) -> np.ndarray:
        """SigLIP's own sigmoid: how likely the text describes the image (0..1)."""
        return 1.0 / (1.0 + np.exp(-(self.scale * cos + self.bias)))


@lru_cache(maxsize=4096)
def _cached_text(model: Siglip, text: str) -> np.ndarray:
    with model._lock:
        e = model.textual.run(None, {model.t_in: model.tokenize(text)})[0][0].astype(np.float32)
    return e / (np.linalg.norm(e) + 1e-9)
