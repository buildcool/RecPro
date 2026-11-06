"""ONNX Runtime sessions on the GPU (CUDA) with CPU fallback.

In development the CUDA and cuDNN libraries come from the NVIDIA packages in the virtual
environment. The installed app doesn't carry them (1.7 GB): it downloads the same files once as
the "GPU acceleration" pack, one folder of DLLs that is loaded from here.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

log = logging.getLogger("recpro.ml")

FROZEN = bool(getattr(sys, "frozen", False))  # running as the installed app (PyInstaller)
PACK_MARKERS = ("cudart64_13.dll", "cublas64_13.dll", "cublasLt64_13.dll", "cudnn64_9.dll")

_lock = threading.Lock()
_preloaded = False
_cuda_loaded = False
_gpu_name: str | None | bool = False  # False = not probed yet
_gpu_pack: Path | None = None
_dll_dirs: list[Any] = []  # handles from os.add_dll_directory must stay alive


def nvidia_driver() -> bool:
    """An NVIDIA display driver is installed (it provides nvcuda.dll)."""
    if os.name != "nt":
        return False
    return (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "nvcuda.dll").exists()


def set_gpu_pack(folder: Path | str | None) -> None:
    """Where the installed app keeps the downloaded CUDA and cuDNN DLLs."""
    global _gpu_pack
    _gpu_pack = Path(folder) if folder else None


def gpu_pack_ready() -> bool:
    return _gpu_pack is not None and all((_gpu_pack / f).exists() for f in PACK_MARKERS)


def reload_gpu() -> None:
    """After the GPU pack is installed: load it, so sessions created from now on use the GPU."""
    global _preloaded
    with _lock:
        _preloaded = False
    _preload()


_ort_module: Any = None
_import_lock = threading.Lock()


def _ort():
    """onnxruntime, imported once: the first import must not race between threads."""
    global _ort_module
    if _ort_module is None:
        with _import_lock:
            if _ort_module is None:
                import onnxruntime as ort

                _ort_module = ort
    return _ort_module


def _preload() -> None:
    global _preloaded, _cuda_loaded
    if _preloaded:
        return
    with _lock:
        if _preloaded:
            return
        try:
            if FROZEN:
                if gpu_pack_ready():
                    d = str(_gpu_pack)
                    # cuDNN opens its sub-libraries by name, so the folder must be on the search path too
                    _dll_dirs.append(os.add_dll_directory(d))
                    os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
                    _ort().preload_dlls(cuda=True, cudnn=True, msvc=True, directory=d)
                    _cuda_loaded = True
                else:
                    _cuda_loaded = False  # no GPU pack yet: the processor does the work
            else:
                _ort().preload_dlls(cuda=True, cudnn=True, msvc=True)
                _cuda_loaded = True
        except Exception as e:  # CPU-only machines end up here
            log.info("CUDA libraries not preloaded: %s", e)
            _cuda_loaded = False
        _preloaded = True


def cuda_available() -> bool:
    _preload()
    if FROZEN and not _cuda_loaded:
        return False
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
    out: dict[str, Any] = {"provider": "CUDA" if cuda else "CPU", "name": gpu_name() if cuda else "Processor (CPU)"}
    if FROZEN and not gpu_pack_ready() and nvidia_driver():
        out["gpuPackNeeded"] = True  # an NVIDIA card is there: Settings offers the GPU pack
    return out
