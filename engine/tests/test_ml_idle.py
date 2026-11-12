"""Models unused for a while give their memory back, and load again when needed."""
from __future__ import annotations

import threading
import time

from recpro.ml import semantic
from recpro.ml.semantic import Siglip


class Engine:
    pass


class ImageTower:
    def __init__(self):
        self.asked = []

    def release_gpu(self, idle_s):
        self.asked.append(idle_s)
        return True


def test_idle_models_are_let_go_and_busy_ones_kept(ctx):
    ml = ctx.services["ml"]
    old, now = time.monotonic() - 600, time.monotonic()
    ml._engines.update({"faces": Engine(), "nudenet": Engine(), "siglip2": ImageTower()})
    ml._used.update({"faces": old, "nudenet": now, "siglip2": now})
    freed = ml.release_idle(300)
    assert "faces" in freed and "faces" not in ml._engines  # idle ten minutes: let go
    assert "nudenet" in ml._engines  # just used: kept
    # SigLIP decides for its image tower itself (searches keep using the text tower)
    assert "siglip2" in ml._engines and ml._engines["siglip2"].asked == [300]


def test_siglip_lets_its_image_tower_go_and_loads_it_again(monkeypatch):
    loads = []
    monkeypatch.setattr(semantic, "session", lambda path, use_gpu, **kw: loads.append(path) or object())
    s = Siglip.__new__(Siglip)  # no model files: only the tower handling is under test
    s._vpath, s._use_gpu, s._vlock = "visual/model.onnx", True, threading.Lock()
    s._visual, s._vused = object(), time.monotonic() - 1000
    assert s.release_gpu(300) is True and s._visual is None
    tower = s.visual  # the next photo loads it again
    assert tower is not None and loads == ["visual/model.onnx"]
    assert s.release_gpu(300) is False  # just used


def test_a_batch_that_runs_out_of_graphics_memory_is_tried_again(ctx, library_dir):
    from tests.conftest import add_and_index

    add_and_index(ctx, library_dir)
    ix = ctx.services["indexer"]
    rows = ctx.db.q("SELECT * FROM media")
    calls = []

    class Stage:
        name, column, version = "objects", "obj_v", 1

        def process(self, rows):
            calls.append(len(rows))
            if len(calls) == 1:
                raise RuntimeError("[ONNXRuntimeError] : 1 : FAIL : CUDA failure 2: out of memory ; GPU=0")
            ctx.db.x("UPDATE media SET obj_v=1")

    assert ix._process(Stage(), rows) is False, "tried again shortly, not marked as failed"
    assert ctx.db.scalar("SELECT COUNT(*) FROM media WHERE error IS NOT NULL OR obj_v != 0") == 0
    assert ix._process(Stage(), rows) is True and calls == [len(rows), len(rows)]

    class Broken(Stage):
        def process(self, rows):
            raise ValueError("a photo it can't read")

    assert ix._process(Broken(), rows) is True
    assert ctx.db.scalar("SELECT COUNT(*) FROM media WHERE error LIKE '%[objects failed]%'") == len(rows)
