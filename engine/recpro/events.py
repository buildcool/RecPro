from __future__ import annotations

import asyncio
import threading
import time
from typing import Any


class EventHub:
    """Fan-out of engine events to connected WebSocket clients.

    Worker threads call ``publish``; delivery happens on the server's asyncio loop.
    ``publish_throttled`` coalesces chatty events (progress) to at most one per interval.
    """

    def __init__(self) -> None:
        self.loop: asyncio.AbstractEventLoop | None = None
        self.clients: set[asyncio.Queue] = set()
        self._throttle: dict[str, tuple[float, Any]] = {}
        self._pending: dict[str, Any] = {}
        self._lock = threading.Lock()

    def attach(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        self.clients.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self.clients.discard(q)

    def publish(self, type_: str, data: Any = None) -> None:
        loop = self.loop
        if loop is None or loop.is_closed():
            return
        msg = {"type": type_, "data": data, "at": time.time()}
        try:
            loop.call_soon_threadsafe(self._deliver, msg)
        except RuntimeError:
            pass

    def publish_throttled(self, type_: str, data: Any = None, interval: float = 0.25) -> None:
        now = time.monotonic()
        with self._lock:
            last = self._throttle.get(type_)
            if last is not None and now - last[0] < interval:
                # remember the newest payload; it will be flushed by the next publish or flush()
                self._pending[type_] = data
                return
            self._throttle[type_] = (now, data)
            self._pending.pop(type_, None)
        self.publish(type_, data)

    def flush(self) -> None:
        with self._lock:
            pending = dict(self._pending)
            self._pending.clear()
            now = time.monotonic()
            for k, v in pending.items():
                self._throttle[k] = (now, v)
        for k, v in pending.items():
            self.publish(k, v)

    def _deliver(self, msg: dict) -> None:
        for q in list(self.clients):
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                # slow client: drop oldest to keep up
                try:
                    q.get_nowait()
                    q.put_nowait(msg)
                except Exception:
                    pass
