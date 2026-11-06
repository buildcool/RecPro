"""ONNX Runtime sessions on the GPU (CUDA) with CPU fallback."""
from __future__ import annotations

import logging
import os
import subprocess
import threading
from pathlib import Path
from typing import Any

log = logging.getLogger("recpro.ml")

_lock = threading.Lock()
_preloaded = False
_gpu_name: str | None | bool = False  # False = not probed yet


def _ort():
    import onnxruntime as ort

    return ort


def _preload() -> None:
    global _preloaded
    if _preloaded:
        return
    with _lock:
        if _preloaded:
            return
        try:
            _ort().preload_dlls(cuda=True, cudnn=True, msvc=True)
        except Exception as e:  # CPU-only machines end up here
            log.info("CUDA libraries not preloaded: %s", e)
        _preloaded = True


def cuda_available() -> bool:
    _preload()
    try:
        return "CUDAExecutionProvider" in _ort().get_available_providers()
    except Exception:
        return False


def providers(use_gpu: bool) -> list[Any]:
    out: list[Any] = []
    if use_gpu and cuda_available():
        out.append(
            (
                "CUDAExecutionProvider",
                {
                    "device_id": 0,
                    "arena_extend_strategy": "kSameAsRequested",
                    "cudnn_conv_algo_search": "HEURISTIC",
                    "do_copy_in_default_stream": True,
                },
            )
        )
    out.append("CPUExecutionProvider")
    return out


def session(path: Path | str, use_gpu: bool = True, threads: int | None = None):
    ort = _ort()
    so = ort.SessionOptions()
    so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    so.log_severity_level = 3
    if threads:
        so.intra_op_num_threads = threads
    sess = ort.InferenceSession(str(path), sess_options=so, providers=providers(use_gpu))
    log.info("loaded %s on %s", Path(path).name, sess.get_providers()[0])
    return sess


def gpu_name() -> str | None:
    global _gpu_name
    if _gpu_name is not False:
        return _gpu_name  # type: ignore[return-value]
    name = None
    try:
        cp = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
            capture_output=True,
            stdin=subprocess.DEVNULL,
            timeout=10,
            creationflags=0x08000000 if os.name == "nt" else 0,
        )
        if cp.returncode == 0:
            name = cp.stdout.decode("utf-8", "replace").strip().splitlines()[0]
    except Exception:
        name = None
    _gpu_name = name
    return name


def device_info(use_gpu: bool) -> dict[str, Any]:
    cuda = use_gpu and cuda_available()
    return {"provider": "CUDA" if cuda else "CPU", "name": gpu_name() if cuda else "Processor (CPU)"}
