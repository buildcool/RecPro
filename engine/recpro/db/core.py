from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator

from .schema import MIGRATIONS


class Database:
    """Thread-safe SQLite access: one connection per thread, writes serialized by a lock.

    Connections run in autocommit mode; use ``tx()`` for multi-statement atomic writes.
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        self._local = threading.local()
        self.write_lock = threading.RLock()
        self._all: list[sqlite3.Connection] = []
        self._all_lock = threading.Lock()

    def conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "conn", None)
        if c is None:
            c = sqlite3.connect(self.path, isolation_level=None, check_same_thread=False, timeout=30)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA synchronous=NORMAL")
            c.execute("PRAGMA foreign_keys=ON")
            c.execute("PRAGMA busy_timeout=30000")
            c.execute("PRAGMA temp_store=MEMORY")
            c.execute("PRAGMA cache_size=-65536")
            self._local.conn = c
            with self._all_lock:
                self._all.append(c)
        return c

    def migrate(self) -> int:
        c = self.conn()
        with self.write_lock:
            version = c.execute("PRAGMA user_version").fetchone()[0]
            for i, sql in enumerate(MIGRATIONS, start=1):
                if i <= version:
                    continue
                c.execute("BEGIN IMMEDIATE")
                try:
                    for stmt in _split_sql(sql):
                        c.execute(stmt)
                    c.execute(f"PRAGMA user_version={i}")
                    c.execute("COMMIT")
                except Exception:
                    c.execute("ROLLBACK")
                    raise
            return c.execute("PRAGMA user_version").fetchone()[0]

    # -- reads -------------------------------------------------------------
    def q(self, sql: str, params: Iterable[Any] | dict = ()) -> list[sqlite3.Row]:
        return self.conn().execute(sql, params).fetchall()

    def q1(self, sql: str, params: Iterable[Any] | dict = ()) -> sqlite3.Row | None:
        return self.conn().execute(sql, params).fetchone()

    def scalar(self, sql: str, params: Iterable[Any] | dict = (), default: Any = None) -> Any:
        row = self.conn().execute(sql, params).fetchone()
        return default if row is None or row[0] is None else row[0]

    # -- writes ------------------------------------------------------------
    def x(self, sql: str, params: Iterable[Any] | dict = ()) -> sqlite3.Cursor:
        with self.write_lock:
            return self.conn().execute(sql, params)

    def xmany(self, sql: str, rows: Iterable[Iterable[Any]]) -> None:
        with self.tx() as c:
            c.executemany(sql, rows)

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        with self.write_lock:
            c = self.conn()
            c.execute("BEGIN IMMEDIATE")
            try:
                yield c
            except BaseException:
                c.execute("ROLLBACK")
                raise
            else:
                c.execute("COMMIT")

    def close_all(self) -> None:
        with self._all_lock:
            for c in self._all:
                try:
                    c.close()
                except Exception:
                    pass
            self._all.clear()
        self._local = threading.local()


def _split_sql(script: str) -> list[str]:
    """Split a migration script into statements (no semicolons inside our literals)."""
    out = []
    for part in script.split(";"):
        s = part.strip()
        if s:
            out.append(s)
    return out
