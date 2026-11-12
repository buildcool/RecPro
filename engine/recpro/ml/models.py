"""AI model manifest and downloader.

Models are downloaded once, on request, into ``<data>/models``. Downloads resume after an
interruption and every file is verified: pinned SHA-256 for release assets, the Hugging Face
LFS SHA-256 (or git blob SHA-1 for small files) for repository files, and PyPI's SHA-256 for
the NVIDIA wheels of the GPU pack. Nothing is uploaded.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import threading
import time
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger("recpro.models")
UA = "RecPro-model-downloader/0.1"
CHUNK = 1024 * 1024


@dataclass
class FileSpec:
    url: str
    dest: str  # relative to models dir
    size: int | None = None
    sha256: str | None = None
    git_sha1: str | None = None
    archive: str | None = None  # "zip": extract models into dest (a folder); "dlls": only the DLLs
    accept: str | None = None  # Accept header (GitHub API asset downloads need application/octet-stream)


@dataclass
class ModelSpec:
    id: str
    name: str
    purpose: str
    license: str
    profiles: tuple[str, ...]
    approx_size: int
    files: list[FileSpec] = field(default_factory=list)
    hf_repo: str | None = None  # file list fetched from the Hugging Face API
    hf_subdirs: tuple[str, ...] = ()
    hf_skip: tuple[str, ...] = ("rknpu",)
    folder: str = ""  # install folder (relative)
    required_files: tuple[str, ...] = ()  # relative to folder; presence = installed
    params: dict = field(default_factory=dict)  # model constants not in the ONNX export
    pypi_wheels: tuple[tuple[str, str], ...] = ()  # (package, version): the DLLs of their Windows wheels
    installed_app_only: bool = False  # offered only by the installed app on a PC with an NVIDIA GPU


GH = "https://github.com"

# The CUDA 13 and cuDNN 9 runtime that onnxruntime-gpu needs. Development gets it from the
# "cuda" dependency group; the installed app downloads the same versions (a test keeps the two
# in step with uv.lock).
GPU_WHEELS: tuple[tuple[str, str], ...] = (
    ("nvidia-cuda-runtime", "13.5.37"),
    ("nvidia-cublas", "13.10.0.20"),
    ("nvidia-cufft", "12.5.0.14"),
    ("nvidia-curand", "10.4.5.25"),
    ("nvidia-cuda-nvrtc", "13.5.37"),
    ("nvidia-nvjitlink", "13.5.37"),
    ("nvidia-cudnn-cu13", "9.28.0.42"),
)

MODELS: list[ModelSpec] = [
    ModelSpec(
        id="gpu",
        name="GPU acceleration (NVIDIA CUDA 13 and cuDNN 9)",
        purpose="Runs the AI on your NVIDIA graphics card, many times faster than on the processor",
        license="NVIDIA CUDA and cuDNN runtime licenses (NVIDIA's own packages from PyPI)",
        profiles=("best", "fast"),
        approx_size=1_169_000_000,
        folder="gpu/cuda13",
        pypi_wheels=GPU_WHEELS,
        required_files=("cudart64_13.dll", "cublas64_13.dll", "cublasLt64_13.dll", "cudnn64_9.dll"),
        installed_app_only=True,
    ),
    ModelSpec(
        id="faces",
        name="Face recognition (InsightFace antelopev2)",
        purpose="Finds faces, recognizes people, estimates age and gender",
        license="Non-commercial research use (personal use only)",
        profiles=("best", "fast"),
        approx_size=360_662_982,
        folder="faces/antelopev2",
        files=[
            FileSpec(
                url=f"{GH}/deepinsight/insightface/releases/download/v0.7/antelopev2.zip",
                dest="faces/antelopev2",
                size=360_662_982,
                sha256="8e182f14fc6e80b3bfa375b33eb6cff7ee05d8ef7633e738d1c89021dcf0c5c5",
                archive="zip",
            )
        ],
        required_files=("scrfd_10g_bnkps.onnx", "glintr100.onnx", "genderage.onnx"),
    ),
    ModelSpec(
        id="siglip2",
        name="Image understanding (SigLIP 2 SO400M, multilingual)",
        purpose="Search by description, activities, moods, scenes, objects and documents",
        license="Apache-2.0",
        profiles=("best",),
        approx_size=4_579_446_815,
        folder="siglip2/so400m-384",
        hf_repo="immich-app/ViT-SO400M-16-SigLIP2-384__webli",
        hf_subdirs=("visual", "textual", ""),
        required_files=("visual/model.onnx", "textual/model.onnx", "textual/tokenizer.json"),
        # from timm/ViT-SO400M-16-SigLIP2-384 open_clip_model.safetensors (logit_scale is log-scale)
        params={"logit_scale": 4.6991615, "logit_bias": -15.932409},
    ),
    ModelSpec(
        id="siglip2-fast",
        name="Image understanding (SigLIP 2 B/16, multilingual)",
        purpose="Faster, smaller search model",
        license="Apache-2.0",
        profiles=("fast",),
        approx_size=1_500_000_000,
        folder="siglip2/b16-224",
        hf_repo="immich-app/ViT-B-16-SigLIP2__webli",
        hf_subdirs=("visual", "textual", ""),
        required_files=("visual/model.onnx", "textual/model.onnx", "textual/tokenizer.json"),
        params={"logit_scale": 4.7244534, "logit_bias": -16.771725},
    ),
    ModelSpec(
        id="emotion",
        name="Facial expressions (HSEmotion EfficientNet-B2)",
        purpose="Happy, sad, surprised, angry… for each face",
        license="Apache-2.0",
        profiles=("best", "fast"),
        approx_size=30_779_724,
        folder="emotion",
        files=[
            FileSpec(
                url="https://raw.githubusercontent.com/sb-ai-lab/EmotiEffLib/main/models/affectnet_emotions/onnx/enet_b2_8.onnx",
                dest="emotion/enet_b2_8.onnx",
                size=30_779_724,
                git_sha1="a7cb612cbab1ce3d50dd52e57285fb2c7ea6d0d9",
            )
        ],
        required_files=("enet_b2_8.onnx",),
    ),
    ModelSpec(
        id="ocr",
        name="Text reading (PaddleOCR PP-OCRv5, English + Hindi/Marathi)",
        purpose="Reads text in photos and screenshots; finds ID documents",
        license="Apache-2.0",
        profiles=("best", "fast"),
        approx_size=101_000_000,
        folder="ocr",
        hf_repo="monkt/paddleocr-onnx",
        hf_subdirs=("detection/v5", "languages/english", "languages/hindi"),
        required_files=("detection/v5/det.onnx", "languages/english/rec.onnx", "languages/english/dict.txt"),
    ),
    ModelSpec(
        id="nudenet",
        name="Private content detector (NudeNet 640m)",
        purpose="Finds nudity and suggestive content for the Private section",
        license="AGPL-3.0 (personal use)",
        profiles=("best", "fast"),
        approx_size=103_538_690,
        folder="nudenet",
        files=[
            # The plain release link redirects to a sign-in page; the API asset endpoint doesn't.
            FileSpec(
                url="https://api.github.com/repos/notAI-tech/NudeNet/releases/assets/176832019",
                dest="nudenet/640m.onnx",
                size=103_538_690,
                accept="application/octet-stream",
            )
        ],
        required_files=("640m.onnx",),
    ),
]

# Things and animals with where they are (D-FINE on Objects365; a smaller detector for the fast
# set), and how each animal looks (DINOv2 base) to tell pets apart. The pet model is the same for
# both sets, so a pet's photos stay comparable after switching. Files are pinned to a commit of
# the ONNX conversions and to their SHA-256.
HF = "https://huggingface.co"
OBJECT_MODELS: list[ModelSpec] = [
    ModelSpec(
        id="objects",
        name="Things and animals (D-FINE X, Objects365)",
        purpose="Finds 365 kinds of things and animals in photos, and where they are",
        license="Apache-2.0",
        profiles=("best",),
        approx_size=126_313_084,
        folder="objects/dfine-x",
        files=[
            FileSpec(
                url=f"{HF}/onnx-community/dfine_x_obj365-ONNX/resolve/8b0ccdfc94d2a405acaaeceade13b6d2b4fccd16/onnx/model_fp16.onnx",
                dest="objects/dfine-x/detector.onnx",
                size=126_313_084,
                sha256="2abdf558041e63785b366b5dcd4e8a541b7d6908fe1c966a1306ec71a7a35ee2",
            )
        ],
        required_files=("detector.onnx",),
    ),
    ModelSpec(
        id="objects-fast",
        name="Things and animals (D-FINE M, Objects365)",
        purpose="Smaller, faster detector for things and animals",
        license="Apache-2.0",
        profiles=("fast",),
        approx_size=79_212_285,
        folder="objects/dfine-m",
        files=[
            FileSpec(
                url=f"{HF}/onnx-community/dfine_m_obj365-ONNX/resolve/f78e69849ffb6dfacbc648b61a11b3af83a06204/onnx/model.onnx",
                dest="objects/dfine-m/detector.onnx",
                size=79_212_285,
                sha256="2fb7d73e2df5be2b1032381d191d6d26d1bca44b23d3eb79af1cbd9e3b19356c",
            )
        ],
        required_files=("detector.onnx",),
    ),
    ModelSpec(
        id="pets",
        name="Pet recognition (DINOv2 base)",
        purpose="Tells your pets apart, so you can name them and find each one",
        license="Apache-2.0",
        profiles=("best", "fast"),
        approx_size=346_608_174,
        folder="pets/dinov2-base",
        files=[
            FileSpec(
                url=f"{HF}/onnx-community/dinov2-base-ONNX/resolve/9a1732c724ef0847dcedf00d3d5a93f61dea0370/onnx/model.onnx",
                dest="pets/dinov2-base/model.onnx",
                size=346_608_174,
                sha256="f16115e628d65b7cc7b1e16c504e2af682169aabf3fff4edfe906118f522e204",
            )
        ],
        required_files=("model.onnx",),
    ),
]
MODELS += OBJECT_MODELS

# Speech is appended to the manifest below, after the image models.
SPEECH_MODELS: list[ModelSpec] = [
    ModelSpec(
        id="speech",
        name="Speech recognition (Whisper large-v3 turbo)",
        purpose="Turns what is said in videos into searchable text (Hindi, English and 97 more languages)",
        license="MIT",
        profiles=("best",),
        approx_size=1_622_000_000,
        folder="speech/large-v3-turbo",
        hf_repo="dropbox-dash/faster-whisper-large-v3-turbo",  # formerly mobiuslabsgmbh/
        hf_subdirs=("",),
        required_files=("model.bin", "config.json", "tokenizer.json", "preprocessor_config.json"),
    ),
    ModelSpec(
        id="speech-fast",
        name="Speech recognition (Whisper small)",
        purpose="Smaller, faster speech recognition",
        license="MIT",
        profiles=("fast",),
        approx_size=486_000_000,
        folder="speech/small",
        hf_repo="Systran/faster-whisper-small",
        hf_subdirs=("",),
        required_files=("model.bin", "config.json", "tokenizer.json"),
    ),
]
MODELS += SPEECH_MODELS

PINNED_FILE = "pinned-hashes.json"  # sha256 of release assets, recorded at first verified download


def spec(model_id: str) -> ModelSpec:
    for m in MODELS:
        if m.id == model_id:
            return m
    raise KeyError(model_id)


def applies(m: ModelSpec) -> bool:
    """The GPU pack only matters to the installed app on a PC with an NVIDIA card."""
    if not m.installed_app_only:
        return True
    from .runtime import FROZEN, nvidia_driver

    return FROZEN and nvidia_driver()


def applicable() -> list[ModelSpec]:
    return [m for m in MODELS if applies(m)]


class ModelManager:
    def __init__(self, models_dir: Path, events, strict_offline: Callable[[], bool]):
        self.dir = Path(models_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.events = events
        self.strict_offline = strict_offline
        self._queue: list[str] = []
        self._cv = threading.Condition()
        self._progress: dict[str, dict[str, Any]] = {}
        self._cancel: set[str] = set()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.on_installed: list[Callable[[str], None]] = []

    # ---- status -------------------------------------------------------------------
    def installed(self, model_id: str) -> bool:
        m = spec(model_id)
        base = self.dir / m.folder
        return all((base / f).exists() for f in m.required_files) and (base / ".verified").exists()

    def path(self, model_id: str) -> Path:
        return self.dir / spec(model_id).folder

    def status(self) -> list[dict[str, Any]]:
        out = []
        for m in applicable():
            p = self._progress.get(m.id)
            out.append(
                {
                    "id": m.id,
                    "name": m.name,
                    "purpose": m.purpose,
                    "license": m.license,
                    "profiles": list(m.profiles),
                    "size": m.approx_size,
                    "installed": self.installed(m.id),
                    "queued": m.id in self._queue,
                    "progress": p,
                }
            )
        return out

    # ---- control --------------------------------------------------------------------
    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="model-download", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        with self._cv:
            self._cv.notify_all()

    def request(self, ids: list[str]) -> None:
        if self.strict_offline():
            raise PermissionError("Strict offline is on. Turn it off in Settings to download models.")
        with self._cv:
            for i in ids:
                if not applies(spec(i)):
                    continue
                if not self.installed(i) and i not in self._queue and self._progress.get(i, {}).get("state") != "downloading":
                    self._queue.append(i)
            self._cv.notify()
        self._emit()

    def cancel(self, model_id: str) -> None:
        with self._cv:
            if model_id in self._queue:
                self._queue.remove(model_id)
        self._cancel.add(model_id)
        self._emit()

    def _emit(self) -> None:
        try:
            self.events.publish_throttled("models.progress", self.status(), interval=0.5)
        except Exception:
            pass

    def _run(self) -> None:
        while not self._stop.is_set():
            with self._cv:
                while not self._queue and not self._stop.is_set():
                    self._cv.wait(5)
                if self._stop.is_set():
                    return
                mid = self._queue.pop(0)
            self._cancel.discard(mid)
            try:
                self._install(mid)
                self._progress[mid] = {"state": "installed"}
                for cb in self.on_installed:
                    try:
                        cb(mid)
                    except Exception:
                        log.exception("on_installed callback failed")
            except _Cancelled:
                self._progress[mid] = {"state": "cancelled"}
            except Exception as e:
                log.exception("model %s failed", mid)
                self._progress[mid] = {"state": "failed", "error": str(e)[:300]}
            self._emit()
            self.events.publish("models.changed", {"id": mid})

    # ---- installing ---------------------------------------------------------------------
    def _install(self, mid: str) -> None:
        m = spec(mid)
        if self.strict_offline():
            raise PermissionError("Strict offline is on")
        base = self.dir / m.folder
        base.mkdir(parents=True, exist_ok=True)
        files = list(m.files)
        if m.hf_repo:
            files += self._hf_files(m)
        if m.pypi_wheels:
            files += self._pypi_files(m)
        total = sum(f.size or 0 for f in files)
        prog = {"state": "downloading", "bytes_done": 0, "bytes_total": total, "file": ""}
        self._progress[mid] = prog
        done_before = 0
        pinned = self._pinned()
        for f in files:
            prog["file"] = os.path.basename(f.dest)
            target = self.dir / f.dest
            if f.archive in ("zip", "dlls"):
                zpath = self.dir / "downloads" / (os.path.basename(f.url))
                if not (zpath.exists() and f.size and zpath.stat().st_size == f.size and self._verify(zpath, f, pinned)):
                    self._download(mid, f, zpath, prog, done_before, pinned)
                if f.archive == "dlls":
                    self._extract_dlls(zpath, target)
                else:
                    self._extract_zip(zpath, target)
                zpath.unlink(missing_ok=True)
            else:
                if target.exists() and f.size and target.stat().st_size == f.size and self._verify(target, f, pinned, quick=True):
                    pass
                else:
                    self._download(mid, f, target, prog, done_before, pinned)
            done_before += f.size or 0
            prog["bytes_done"] = done_before
            self._emit()
        missing = [r for r in m.required_files if not (base / r).exists()]
        if missing:
            raise RuntimeError(f"Model files missing after download: {', '.join(missing)}")
        (base / ".verified").write_text(json.dumps({"at": time.time(), "files": len(files)}), encoding="utf-8")

    def _download(self, mid: str, f: FileSpec, target: Path, prog: dict, done_before: int, pinned: dict) -> None:
        """Downloads with automatic resume: dropped connections are retried from where they stopped."""
        last: Exception | None = None
        for attempt in range(5):
            try:
                self._download_once(mid, f, target, prog, done_before, pinned)
                return
            except (_Cancelled, PermissionError):
                raise
            except _ChecksumError:
                raise
            except Exception as e:  # network hiccup, truncated response, timeout
                last = e
                log.info("download of %s interrupted (%s), retrying (%d)", target.name, e, attempt + 1)
                time.sleep(min(2 ** attempt, 15))
        raise RuntimeError(f"{target.name}: download kept failing ({last})")

    def _download_once(self, mid: str, f: FileSpec, target: Path, prog: dict, done_before: int, pinned: dict) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        part = target.with_name(target.name + ".part")
        have = part.stat().st_size if part.exists() else 0
        if f.size and have > f.size:
            part.unlink()
            have = 0
        req = urllib.request.Request(f.url, headers={"User-Agent": UA})
        if f.accept:
            req.add_header("Accept", f.accept)
        if have:
            req.add_header("Range", f"bytes={have}-")
        with urllib.request.urlopen(req, timeout=60) as resp:
            ctype = (resp.headers.get("Content-Type") or "").lower()
            if ctype.startswith("text/html"):
                raise _ChecksumError(f"{target.name}: the server sent a web page instead of the model file")
            if have and resp.status != 206:
                have = 0  # server ignored the range: start over
            mode = "ab" if have else "wb"
            with open(part, mode) as out:
                got = have
                while True:
                    if mid in self._cancel or self._stop.is_set():
                        raise _Cancelled()
                    b = resp.read(CHUNK)
                    if not b:
                        break
                    out.write(b)
                    got += len(b)
                    prog["bytes_done"] = done_before + got
                    self._emit()
        if f.size and part.stat().st_size != f.size:
            raise RuntimeError(f"incomplete download ({part.stat().st_size} of {f.size} bytes)")
        if not self._verify(part, f, pinned):
            part.unlink(missing_ok=True)
            raise _ChecksumError(f"{target.name}: checksum mismatch, the file was discarded")
        os.replace(part, target)

    def _verify(self, path: Path, f: FileSpec, pinned: dict, quick: bool = False) -> bool:
        expected = f.sha256 or pinned.get(f.url)
        if expected:
            return _sha256(path) == expected
        if f.git_sha1:
            return _git_blob_sha1(path) == f.git_sha1
        if quick:
            return True
        # First download of an unpinned release asset: record its hash for future checks.
        pinned[f.url] = _sha256(path)
        self._save_pinned(pinned)
        return True

    def _pinned(self) -> dict:
        p = self.dir / PINNED_FILE
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_pinned(self, data: dict) -> None:
        (self.dir / PINNED_FILE).write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _hf_files(self, m: ModelSpec) -> list[FileSpec]:
        out: list[FileSpec] = []
        for sub in m.hf_subdirs:
            url = f"https://huggingface.co/api/models/{m.hf_repo}/tree/main" + (f"/{sub}" if sub else "")
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as resp:
                entries = json.loads(resp.read().decode("utf-8"))
            for e in entries:
                if e.get("type") != "file":
                    continue
                path = e["path"]
                if any(part in m.hf_skip for part in path.split("/")):
                    continue
                if path in (".gitattributes", "README.md"):
                    continue
                lfs = e.get("lfs") or {}
                out.append(
                    FileSpec(
                        url=f"https://huggingface.co/{m.hf_repo}/resolve/main/{path}",
                        dest=f"{m.folder}/{path}",
                        size=lfs.get("size") or e.get("size"),
                        sha256=lfs.get("oid") if lfs else None,
                        git_sha1=None if lfs else e.get("oid"),
                    )
                )
        return out

    def _pypi_files(self, m: ModelSpec) -> list[FileSpec]:
        """Each package's Windows wheel, with the size and SHA-256 that PyPI publishes."""
        out: list[FileSpec] = []
        for name, version in m.pypi_wheels:
            req = urllib.request.Request(f"https://pypi.org/pypi/{name}/{version}/json", headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as resp:
                info = json.loads(resp.read().decode("utf-8"))
            wheel = next((u for u in info.get("urls", []) if u.get("filename", "").endswith("-win_amd64.whl")), None)
            if wheel is None:
                raise RuntimeError(f"{name} {version} has no Windows download on PyPI")
            out.append(FileSpec(url=wheel["url"], dest=m.folder, size=wheel["size"], sha256=wheel["digests"]["sha256"], archive="dlls"))
        return out

    def _extract_dlls(self, zpath: Path, dest: Path) -> None:
        """A wheel is a zip: keep only its DLLs, all in one folder (ONNX Runtime loads them from there)."""
        dest.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zpath) as z:
            for info in z.infolist():
                name = os.path.basename(info.filename)  # flatten, no path traversal
                if info.is_dir() or not name.lower().endswith(".dll"):
                    continue
                tmp = dest / (name + ".part")
                with z.open(info) as src, open(tmp, "wb") as out:
                    shutil.copyfileobj(src, out, CHUNK)
                os.replace(tmp, dest / name)

    def _extract_zip(self, zpath: Path, dest: Path) -> None:
        dest.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zpath) as z:
            for info in z.infolist():
                if info.is_dir():
                    continue
                name = os.path.basename(info.filename)  # flatten nested folders, no path traversal
                if not name or not name.lower().endswith((".onnx", ".json", ".txt")):
                    continue
                with z.open(info) as src, open(dest / name, "wb") as out:
                    shutil.copyfileobj(src, out, CHUNK)


class _Cancelled(Exception):
    pass


class _ChecksumError(Exception):
    pass


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(CHUNK * 4)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def _git_blob_sha1(path: Path) -> str:
    size = path.stat().st_size
    h = hashlib.sha1()
    h.update(f"blob {size}\0".encode())
    with open(path, "rb") as f:
        while True:
            b = f.read(CHUNK * 4)
            if not b:
                break
            h.update(b)
    return h.hexdigest()
