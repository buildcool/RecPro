"""Background indexing: runs analysis stages over media rows until everything is current.

Each stage owns a version column on ``media``. A row needs a stage when its column is below
the stage's version. State lives in the database, so indexing resumes after a restart.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Any, Protocol

from ..context import Context

log = logging.getLogger("recpro.indexer")


class Stage(Protocol):
    name: str
    label: str
    column: str
    version: int
    kinds: tuple[str, ...]
    batch_size: int
    order: str

    def available(self) -> bool: ...
    def where(self) -> str: ...
    def process(self, rows: list[Any]) -> None: ...


class Indexer:
    def __init__(self, ctx: Context):
        self.ctx = ctx
        self.db = ctx.db
        self.stages: list[Stage] = []
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._rates: dict[str, deque[tuple[float, int]]] = {}
        self._focus: set[int] = set()
        self._last_status: dict | None = None
        self.current: str | None = None

    def add_stage(self, stage: Stage) -> None:
        self.stages.append(stage)
        self._rates[stage.name] = deque(maxlen=50)

    # ---- control ------------------------------------------------------------
    def start(self) -> None:
        from .deep import DeepStage
        from .quick import QuickStage
        from .semantic import SemanticStage
        from .sens import SensStage

        # Order = priority: thumbnails first so the gallery fills fast, the private check before
        # anything is shown unblurred, then faces and understanding.
        defaults = [QuickStage(self.ctx), SensStage(self.ctx), DeepStage(self.ctx), SemanticStage(self.ctx)]
        names = {s.name for s in self.stages}
        for st in reversed(defaults):
            if st.name not in names:
                self.stages.insert(0, st)
                self._rates[st.name] = deque(maxlen=50)
        threading.Thread(target=self._run, name="indexer", daemon=True).start()
        threading.Thread(target=self._status_loop, name="indexer-status", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def wake(self) -> None:
        self._wake.set()

    @property
    def paused(self) -> bool:
        return bool(self.ctx.settings.get("performance.paused"))

    def pause(self) -> None:
        self.ctx.settings.update({"performance.paused": True})
        self.publish_status(force=True)

    def resume(self) -> None:
        self.ctx.settings.update({"performance.paused": False})
        self.wake()
        self.publish_status(force=True)

    def focus(self, folder_ids: list[int]) -> None:
        """Process these folders first (e.g. the ones the user is searching right now)."""
        self._focus = set(folder_ids)
        self.wake()

    # ---- loop -----------------------------------------------------------------
    def _next_rows(self, st: Stage) -> list[Any]:
        kinds = ",".join(f"'{k}'" for k in st.kinds)
        focus = ""
        if self._focus:
            focus = f"CASE WHEN folder_id IN ({','.join(str(int(i)) for i in self._focus)}) THEN 0 ELSE 1 END, "
        extra = st.where()
        sql = (
            f"SELECT * FROM media WHERE state='active' AND {st.column} < ? AND kind IN ({kinds})"
            f"{(' AND ' + extra) if extra else ''} ORDER BY {focus}{st.order} LIMIT ?"
        )
        return self.db.q(sql, (st.version, st.batch_size))

    def _run(self) -> None:
        time.sleep(0.5)
        while not self._stop.is_set():
            if self.paused:
                self._wake.wait(2.0)
                self._wake.clear()
                continue
            did = False
            for st in self.stages:
                try:
                    if not st.available():
                        continue
                    rows = self._next_rows(st)
                except Exception:
                    log.exception("stage %s selection failed", st.name)
                    continue
                if not rows:
                    continue
                self.current = st.name
                t0 = time.time()
                try:
                    st.process(rows)
                except Exception:
                    log.exception("stage %s failed on a batch; marking rows so they don't loop", st.name)
                    with self.db.tx() as c:
                        c.executemany(
                            f"UPDATE media SET {st.column}=?, error=COALESCE(error,'') || ? WHERE id=?",
                            [(st.version, f"[{st.name} failed]", r["id"]) for r in rows],
                        )
                self._rates[st.name].append((time.time(), len(rows)))
                self.ctx.events.publish_throttled("media.updated", {"stage": st.name}, interval=1.5)
                did = True
                break  # always restart from the highest-priority stage
            self.current = None
            if not did:
                self._wake.wait(5.0)
                self._wake.clear()

    # ---- status -----------------------------------------------------------------
    def _rate(self, name: str) -> float | None:
        q = self._rates.get(name)
        if not q or len(q) < 2:
            return None
        now = time.time()
        recent = [(t, n) for t, n in q if now - t < 30]
        if len(recent) < 2:
            return None
        span = recent[-1][0] - recent[0][0]
        if span <= 0:
            return None
        return sum(n for _, n in recent[1:]) / span

    def status(self) -> dict[str, Any]:
        stages: dict[str, Any] = {}
        running = False
        total_media = self.db.scalar("SELECT COUNT(*) FROM media WHERE state='active'", default=0)
        for st in self.stages:
            try:
                if not st.available():
                    continue
                kinds = ",".join(f"'{k}'" for k in st.kinds)
                extra = st.where()
                base = f"FROM media WHERE state='active' AND kind IN ({kinds})" + (f" AND {extra}" if extra else "")
                total = self.db.scalar(f"SELECT COUNT(*) {base}", default=0)
                done = self.db.scalar(f"SELECT COUNT(*) {base} AND {st.column} >= ?", (st.version,), default=0)
            except Exception:
                continue
            stages[st.name] = {"label": st.label, "done": done, "total": total, "rate": self._rate(st.name)}
            if done < total:
                running = True
        lib = self.ctx.services.get("library")
        scanning = bool(lib and lib.is_scanning())  # type: ignore[attr-defined]
        remaining = [(s["total"] - s["done"], s["rate"]) for s in stages.values() if s["total"] > s["done"]]
        eta = None
        if remaining and all(r for _, r in remaining):
            eta = sum(n / r for n, r in remaining)
        return {
            "running": running,
            "paused": self.paused,
            "scanning": scanning,
            "phase": self.current or "",
            "stages": stages,
            "totalMedia": total_media,
            "etaSec": eta,
        }

    def publish_status(self, force: bool = False) -> None:
        st = self.status()
        cmp = {k: v for k, v in st.items() if k != "etaSec"}
        if force or cmp != self._last_status:
            self._last_status = cmp
            self.ctx.events.publish("status", st)

    def _status_loop(self) -> None:
        while not self._stop.wait(1.0):
            try:
                self.publish_status()
                self.ctx.events.flush()
            except Exception:
                log.exception("status loop")


def create(ctx: Context) -> Indexer:
    return Indexer(ctx)
