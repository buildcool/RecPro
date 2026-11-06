"""Freeze the engine into dist/recpro-engine/ (PyInstaller, one folder) for the desktop app.

    cd engine
    uv sync --no-default-groups --group build       # the app's own dependencies, no CUDA, + PyInstaller
    uv run --no-sync python ../scripts/build_engine.py
    ..\\dist\\recpro-engine\\recpro-engine.exe --version

The NVIDIA CUDA and cuDNN libraries are left out on purpose (1.7 GB, over the installer's 2 GB
limit together with everything else): the installed app downloads them once as its GPU pack.
ffmpeg and ffprobe are added to dist/recpro-engine/bin by the desktop workflow.
Set RECPRO_DIST / RECPRO_BUILD to put the output and PyInstaller's work folder elsewhere.
"""
from __future__ import annotations

import os
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = Path(os.environ.get("RECPRO_DIST", ROOT / "dist"))
WORK = Path(os.environ.get("RECPRO_BUILD", ROOT / ".cache" / "pyinstaller"))

# imported by name at run time (services, uvicorn's protocol and loop choice, watchdog's observer,
# send2trash's platform module), so PyInstaller can't see them in the code
COLLECT_SUBMODULES = ["recpro", "uvicorn", "watchdog", "send2trash", "websockets", "httptools"]
COLLECT_ALL = ["pillow_heif", "faster_whisper", "ctranslate2"]  # libheif DLLs next to the module; the voice
# detector model shipped inside faster-whisper; CTranslate2's own DLLs (MKL/oneDNN, cuDNN loader)
COPY_METADATA = ["recpro-engine", "fastapi", "uvicorn", "pydantic", "starlette", "onnxruntime-gpu", "tokenizers", "faster-whisper", "ctranslate2",
                 "scikit-learn", "argon2-cffi", "pynacl", "pillow-heif", "watchdog", "python-multipart"]
EXCLUDE = ["tkinter", "matplotlib", "IPython", "pytest", "torch", "tensorflow", "pandas", "skimage", "nvidia",
           "PyQt5", "PySide6", "notebook"]


def main() -> int:
    try:
        distribution("nvidia-cudnn-cu13")
        print("note: CUDA libraries are installed in this environment; they are excluded from the build")
    except PackageNotFoundError:
        pass
    args = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--console", "--noupx",
            "--name", "recpro-engine", "--distpath", str(DIST), "--workpath", str(WORK / "work"), "--specpath", str(WORK)]
    for m in COLLECT_SUBMODULES:
        args += ["--collect-submodules", m]
    for m in COLLECT_ALL:
        args += ["--collect-all", m]
    for m in COPY_METADATA:
        try:
            distribution(m)
            args += ["--copy-metadata", m]
        except PackageNotFoundError:
            print(f"(skip metadata for {m}: not installed)")
    for m in EXCLUDE:
        args += ["--exclude-module", m]
    args.append(str(ROOT / "scripts" / "engine_entry.py"))
    print(" ".join(args), flush=True)
    return subprocess.call(args, cwd=ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
