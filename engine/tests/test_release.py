"""Release guarantees: one version everywhere, and a GPU pack that matches the lock file."""
from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

from recpro import __version__
from recpro.ml.models import GPU_WHEELS, MODELS, applicable, spec

ROOT = Path(__file__).resolve().parents[2]


def test_one_version_everywhere():
    engine = tomllib.loads((ROOT / "engine" / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    versions = {"engine/pyproject.toml": engine, "recpro.__version__": __version__}
    for rel in ("package.json", "desktop/package.json", "ui/package.json"):
        versions[rel] = json.loads((ROOT / rel).read_text(encoding="utf-8"))["version"]
    lock = json.loads((ROOT / "package-lock.json").read_text(encoding="utf-8"))
    versions["package-lock.json"] = lock["version"]
    for ws in ("desktop", "ui"):
        versions[f"package-lock.json packages/{ws}"] = lock["packages"][ws]["version"]
    assert len(set(versions.values())) == 1, versions
    assert re.fullmatch(r"\d+\.\d+\.\d+", engine)


def test_gpu_pack_matches_the_locked_cuda_libraries():
    lock = tomllib.loads((ROOT / "engine" / "uv.lock").read_text(encoding="utf-8"))
    locked = {p["name"]: p["version"] for p in lock["package"] if p["name"].startswith("nvidia-")}
    assert dict(GPU_WHEELS) == locked, "update GPU_WHEELS in ml/models.py to the versions in uv.lock"


def test_gpu_pack_is_only_offered_by_the_installed_app():
    gpu = spec("gpu")
    assert gpu.installed_app_only and gpu.pypi_wheels
    assert gpu not in applicable(), "a development run has the CUDA libraries already"
    assert len(applicable()) == len(MODELS) - 1


def test_dll_extraction_keeps_only_flat_dlls(tmp_path):
    import zipfile

    from recpro.ml.models import ModelManager

    whl = tmp_path / "pkg.whl"
    with zipfile.ZipFile(whl, "w") as z:
        z.writestr("nvidia/cu13/bin/x86_64/cudart64_13.dll", b"MZ fake")
        z.writestr("nvidia/cu13/include/cuda.h", b"/* header */")
        z.writestr("../../evil.dll", b"MZ outside")
    mm = ModelManager(tmp_path / "models", events=None, strict_offline=lambda: False)
    dest = tmp_path / "models" / "gpu" / "cuda13"
    mm._extract_dlls(whl, dest)
    assert sorted(p.name for p in dest.iterdir()) == ["cudart64_13.dll", "evil.dll"]
    assert not (tmp_path / "evil.dll").exists(), "names are flattened: nothing lands outside the folder"
