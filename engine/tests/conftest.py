from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
from PIL import Image

from recpro.bootstrap import build_context
from recpro.config import Paths


@pytest.fixture()
def ctx(tmp_path: Path):
    c = build_context(Paths(tmp_path / "data"), "test-token")
    # Never create a bin at a real drive root during tests.
    c.services["ops"].bin_root_override = str(tmp_path / "binroot")
    yield c
    c.stop()


@pytest.fixture()
def library_dir(tmp_path: Path) -> Path:
    root = tmp_path / "Photos"
    (root / "Trip").mkdir(parents=True)
    # Noise images so files are realistically sized (the scanner ignores files under 512 bytes).
    for i in range(5):
        Image.effect_noise((96 + i, 72), 60 + i).convert("RGB").save(root / "Trip" / f"img_{i}.jpg", quality=90)
    Image.effect_noise((80, 60), 50).convert("RGB").save(root / "top.png")
    return root


def wait_for(fn, timeout: float = 15.0, interval: float = 0.05):
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(interval)
    raise AssertionError("timed out waiting for condition")


def add_and_index(ctx, folder: Path):
    lib = ctx.services["library"]
    res = lib.add_folders([str(folder)])
    fid = res["added"][0]["id"]
    lib.scan_folder(fid)
    quick = ctx.services["indexer"]
    from recpro.jobs.quick import QuickStage

    stage = QuickStage(ctx)
    rows = ctx.db.q("SELECT * FROM media WHERE quick_v < 1")
    if rows:
        stage.process(rows)
    return fid


def files_in(p: Path) -> list[str]:
    return sorted(str(x.relative_to(p)) for x in p.rglob("*") if x.is_file())


os.environ.setdefault("RECPRO_TEST", "1")
