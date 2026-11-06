from __future__ import annotations

import logging
import time
from typing import Callable

from .config import Paths
from .db import Database
from .events import EventHub
from .settings import Settings

log = logging.getLogger("recpro")


class Context:
    """Holds the engine's long-lived services. Created once per process."""

    def __init__(self, paths: Paths, token: str, port: int = 0):
        self.paths = paths
        self.token = token
        self.port = port
        self.started_at = time.time()
        paths.ensure()
        self.db = Database(paths.db)
        self.db.migrate()
        self.events = EventHub()
        self.settings = Settings(self.db)
        self._starters: list[Callable[[], None]] = []
        self._stoppers: list[Callable[[], None]] = []
        self.services: dict[str, object] = {}

    def register(self, name: str, service: object) -> object:
        self.services[name] = service
        start = getattr(service, "start", None)
        stop = getattr(service, "stop", None)
        if callable(start):
            self._starters.append(start)
        if callable(stop):
            self._stoppers.append(stop)
        return service

    def start(self) -> None:
        for fn in self._starters:
            try:
                fn()
            except Exception:
                log.exception("service failed to start: %s", fn)

    def stop(self) -> None:
        for fn in reversed(self._stoppers):
            try:
                fn()
            except Exception:
                log.exception("service failed to stop: %s", fn)
        self.db.close_all()
