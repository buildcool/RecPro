"""Library folders: add/remove, scanning, and live watching for changes."""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

from ..context import Context
from .scanner import ScanResult, norm, reconcile, walk

log = logging.getLogger("recpro.library")


class Library:
    def __init__(self, ctx: Context):
        self.ctx = ctx
        self.db = ctx.db
        self._scan_lock = threading.Lock()
        self._queue: list[int] = []
        self._queue_cv = threading.Condition()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._observer = None
        self._watched: dict[int, Any] = {}
        self._dirty: dict[int, float] = {}
        self.scanning_folder: int | None = None

    # ---- lifecycle ----------------------------------------------------------
    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="library-scan", daemon=True)
        self._thread.start()
        threading.Thread(target=self._debounce_loop, name="library-watch", daemon=True).start()
        self._start_watcher()
        # rescan everything on startup to catch changes made while RecPro was closed
        for r in self.db.q("SELECT id FROM folders ORDER BY id"):
            self.request_scan(r["id"])

    def stop(self) -> None:
        self._stop.set()
        with self._queue_cv:
            self._queue_cv.notify_all()
        if self._observer is not None:
            try:
                self._observer.stop()
            except Exception:
                pass

    # ---- folders ------------------------------------------------------------
    def list_folders(self) -> list[dict[str, Any]]:
        rows = self.db.q(
            """SELECT f.*,
                 COALESCE(SUM(CASE WHEN m.kind='image' AND m.state='active' THEN 1 END),0) AS photos,
                 COALESCE(SUM(CASE WHEN m.kind='video' AND m.state='active' THEN 1 END),0) AS videos,
                 COALESCE(SUM(CASE WHEN m.state='active' THEN m.size END),0) AS bytes
               FROM folders f LEFT JOIN media m ON m.folder_id=f.id
               GROUP BY f.id ORDER BY f.path COLLATE NOCASE"""
        )
        out = []
        for r in rows:
            d = dict(r)
            d["recursive"] = bool(d["recursive"])
            d["watch"] = bool(d["watch"])
            d["online"] = os.path.isdir(d["path"])
            if not d["online"]:
                d["status"] = "offline"
            elif self.scanning_folder == d["id"]:
                d["status"] = "scanning"
            out.append(d)
        return out

    def add_folders(self, paths: list[str], recursive: bool = True) -> dict[str, Any]:
        added, skipped = [], []
        data_dir = norm(self.ctx.paths.data)
        for raw in paths:
            p = os.path.abspath(os.path.expanduser(raw.strip().strip('"')))
            if not os.path.isdir(p):
                skipped.append({"path": raw, "reason": "This folder doesn't exist or isn't reachable."})
                continue
            pn = norm(p)
            if pn == data_dir or pn.startswith(data_dir + os.sep) or data_dir.startswith(pn + os.sep):
                skipped.append({"path": p, "reason": "This folder holds RecPro's own data, so it can't be added."})
                continue
            if len(Path(p).parts) <= 1:
                pass  # whole drive is allowed
            existing = self.db.q("SELECT id, path FROM folders")
            covered = next((r for r in existing if pn == norm(r["path"]) or pn.startswith(norm(r["path"]) + os.sep)), None)
            if covered:
                skipped.append({"path": p, "reason": f"Already included in {covered['path']}."})
                continue
            children = [r for r in existing if norm(r["path"]).startswith(pn + os.sep)]
            now = time.time()
            with self.db.tx() as c:
                cur = c.execute(
                    "INSERT INTO folders(path, recursive, added_at, status) VALUES(?,?,?, 'pending')",
                    (p, 1 if recursive else 0, now),
                )
                fid = cur.lastrowid
                # A new parent folder absorbs folders already in the library (keeps all analysis).
                for ch in children:
                    rel_prefix = os.path.relpath(ch["path"], p)
                    for m in c.execute("SELECT id, rel_dir FROM media WHERE folder_id=?", (ch["id"],)).fetchall():
                        rd = rel_prefix if not m["rel_dir"] else os.path.join(rel_prefix, m["rel_dir"])
                        c.execute("UPDATE media SET folder_id=?, rel_dir=? WHERE id=?", (fid, rd, m["id"]))
                    c.execute("DELETE FROM folders WHERE id=?", (ch["id"],))
            added.append({"id": fid, "path": p, "absorbed": [ch["path"] for ch in children]})
            self.request_scan(fid)
        if added:
            self._start_watcher()
            self.ctx.events.publish("library.changed", {"added": [a["id"] for a in added]})
        return {"added": added, "skipped": skipped}

    def remove_folder(self, folder_id: int) -> None:
        """Removes the folder from the library. Files on disk are never touched."""
        thumbs = [r["id"] for r in self.db.q("SELECT id FROM media WHERE folder_id=?", (folder_id,))]
        with self.db.tx() as c:
            c.execute("DELETE FROM folders WHERE id=?", (folder_id,))
        self._start_watcher()
        from .imaging import shard

        for mid in thumbs:
            for base in (self.ctx.paths.thumbs, self.ctx.paths.previews):
                try:
                    shard(base, mid).unlink(missing_ok=True)
                except OSError:
                    pass
        self.ctx.events.publish("library.changed", {"removed": folder_id})

    def update_folder(self, folder_id: int, values: dict[str, Any]) -> None:
        sets, params = [], []
        if "watch" in values:
            sets.append("watch=?")
            params.append(1 if values["watch"] else 0)
        if "recursive" in values:
            sets.append("recursive=?")
            params.append(1 if values["recursive"] else 0)
        if "excluded" in values:
            sets.append("excluded=?")
            params.append(json.dumps([os.path.abspath(x) for x in values["excluded"]]))
        if not sets:
            return
        params.append(folder_id)
        self.db.x(f"UPDATE folders SET {', '.join(sets)} WHERE id=?", params)
        self._start_watcher()
        self.request_scan(folder_id)

    # ---- scanning -------------------------------------------------------------
    def request_scan(self, folder_id: int) -> None:
        with self._queue_cv:
            if folder_id not in self._queue:
                self._queue.append(folder_id)
            self._queue_cv.notify()

    def is_scanning(self) -> bool:
        return self.scanning_folder is not None or bool(self._queue)

    def _run(self) -> None:
        while not self._stop.is_set():
            with self._queue_cv:
                while not self._queue and not self._stop.is_set():
                    self._queue_cv.wait(timeout=5)
                if self._stop.is_set():
                    return
                fid = self._queue.pop(0)
            try:
                self.scan_folder(fid)
            except Exception:
                log.exception("scan failed for folder %s", fid)

    def scan_folder(self, folder_id: int) -> ScanResult | None:
        row = self.db.q1("SELECT * FROM folders WHERE id=?", (folder_id,))
        if row is None:
            return None
        result = ScanResult()
        if not os.path.isdir(row["path"]):
            self.db.x("UPDATE folders SET status='offline' WHERE id=?", (folder_id,))
            self.ctx.events.publish("library.changed", {"offline": folder_id})
            return result
        with self._scan_lock:
            self.scanning_folder = folder_id
            self.db.x("UPDATE folders SET status='scanning' WHERE id=?", (folder_id,))
            self.ctx.events.publish("library.changed", {"scanning": folder_id})
            try:
                excluded = {norm(x) for x in json.loads(row["excluded"] or "[]")}
                t0 = time.time()
                files = walk(row["path"], bool(row["recursive"]), excluded, str(self.ctx.paths.data), result)
                reconcile(self.db, folder_id, files, result)
                self.db.x(
                    "UPDATE folders SET status='ready', last_scan_at=?, file_count=?, skipped_cloud=? WHERE id=?",
                    (time.time(), result.found, result.skipped_cloud, folder_id),
                )
                log.info(
                    "scanned %s: %d files (+%d ~%d moved %d missing %d cloud-only %d) in %.1fs",
                    row["path"], result.found, result.added, result.changed, result.moved, result.missing,
                    result.skipped_cloud, time.time() - t0,
                )
            finally:
                self.scanning_folder = None
        self.ctx.events.publish("library.changed", {"scanned": folder_id, "added": result.added})
        indexer = self.ctx.services.get("indexer")
        if indexer is not None:
            indexer.wake()  # type: ignore[attr-defined]
        return result

    # ---- watching -----------------------------------------------------------------
    def _start_watcher(self) -> None:
        try:
            from watchdog.events import FileSystemEventHandler
            from watchdog.observers import Observer
        except Exception:
            return
        folders = {r["id"]: r["path"] for r in self.db.q("SELECT id, path FROM folders WHERE watch=1")}
        if self._observer is None:
            self._observer = Observer()
            self._observer.daemon = True
            self._observer.start()
        lib = self

        class Handler(FileSystemEventHandler):
            def __init__(self, fid: int):
                self.fid = fid

            def on_any_event(self, event):  # noqa: D401
                if event.is_directory and event.event_type == "modified":
                    return
                p = str(getattr(event, "dest_path", "") or event.src_path).lower()
                if ".recpro-bin" in p or p.endswith((".recpro-part", ".tmp")):
                    return
                lib._dirty[self.fid] = time.time()

        for fid, watch in list(self._watched.items()):
            if fid not in folders:
                try:
                    self._observer.unschedule(watch)
                except Exception:
                    pass
                del self._watched[fid]
        for fid, path in folders.items():
            if fid in self._watched or not os.path.isdir(path):
                continue
            try:
                self._watched[fid] = self._observer.schedule(Handler(fid), path, recursive=True)
            except Exception as e:
                log.warning("cannot watch %s: %s", path, e)

    def _debounce_loop(self) -> None:
        while not self._stop.wait(1.0):
            now = time.time()
            for fid, t in list(self._dirty.items()):
                if now - t >= 3.0:
                    self._dirty.pop(fid, None)
                    self.request_scan(fid)


def create(ctx: Context) -> Library:
    return Library(ctx)
