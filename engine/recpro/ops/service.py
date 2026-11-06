"""Safe file operations: copy → verify → (ask) → remove to Bin, with undo.

Guarantees:
* A source file is only removed after its copy was re-read and its BLAKE3 hash matched.
* A source is only removed if it is unchanged since it was copied (size + mtime).
* Every step is journaled per file in ``op_items``; interrupted operations resume.
* "Remove" moves files into ``<drive>\\.RecPro-Bin\\op-N`` (same drive, instant, restorable).
  Only "Empty bin" deletes permanently.
"""
from __future__ import annotations

import logging
import os
import shutil
import threading
import time
from datetime import datetime
from typing import Any

from blake3 import blake3

from ..context import Context
from .fsutil import BIN_DIR, ensure_bin, is_inside, lp, path_under_volume, safe_name, unique_path, unlp, volume_root

log = logging.getLogger("recpro.ops")
CHUNK = 4 * 1024 * 1024
STRUCTURES = ("keep", "flat", "date", "person")
CONFLICTS = ("rename", "skip")
REMOVABLE = ("verified", "identical")


class OpCancelled(Exception):
    pass


class Ops:
    def __init__(self, ctx: Context):
        self.ctx = ctx
        self.db = ctx.db
        self._threads: dict[int, threading.Thread] = {}
        self._pause: dict[int, threading.Event] = {}
        self._cancel: dict[int, threading.Event] = {}
        self._rate: dict[int, tuple[float, int]] = {}
        self._lock = threading.Lock()

    def start(self) -> None:
        # Operations interrupted by a crash or shutdown resume as paused, waiting for the user.
        self.db.x("UPDATE operations SET status='paused' WHERE status='running'")
        self._cleanup_parts()

    def stop(self) -> None:
        for ev in self._cancel.values():
            ev.set()

    # ------------------------------------------------------------------ planning
    def plan(
        self,
        media_ids: list[int],
        dest: str,
        structure: str = "keep",
        conflict: str = "rename",
        person_by_media: dict[int, str] | None = None,
    ) -> dict[str, Any]:
        if structure not in STRUCTURES:
            raise ValueError("Unknown folder structure")
        if conflict not in CONFLICTS:
            raise ValueError("Unknown conflict rule")
        dest = os.path.abspath(dest)
        rows = self._media_rows(media_ids)
        items, taken = [], set()
        missing, same, conflicts, identical = 0, 0, 0, 0
        total_bytes = 0
        for r in rows:
            if not os.path.exists(lp(r["path"])):
                missing += 1
                continue
            dst = self._dest_path(r, dest, structure, (person_by_media or {}).get(r["id"]))
            if os.path.normcase(dst) == os.path.normcase(r["path"]):
                same += 1
                continue
            state = "pending"
            if os.path.exists(lp(dst)) or os.path.normcase(dst) in taken:
                if os.path.exists(lp(dst)) and os.path.getsize(lp(dst)) == r["size"]:
                    identical += 1
                    state = "maybe_identical"
                else:
                    conflicts += 1
                    if conflict == "rename":
                        dst = unique_path(dst, taken)
                    else:
                        state = "skip"
            taken.add(os.path.normcase(dst))
            if state != "skip":
                total_bytes += r["size"]
            items.append({"media_id": r["id"], "src": r["path"], "dst": dst, "size": r["size"], "state": state})
        probe = dest
        while not os.path.exists(probe) and os.path.dirname(probe) != probe:
            probe = os.path.dirname(probe)
        free = shutil.disk_usage(probe).free if os.path.exists(probe) else 0
        inside_sources = [r["path"] for r in rows if is_inside(dest, os.path.dirname(r["path"]))][:1]
        return {
            "count": len(items),
            "bytes": total_bytes,
            "free": free,
            "enough_space": free > total_bytes + 50 * 1024 * 1024,
            "missing": missing,
            "same_place": same,
            "conflicts": conflicts,
            "identical": identical,
            "dest": dest,
            "dest_exists": os.path.isdir(dest),
            "inside_source": bool(inside_sources),
            "items": items,
        }

    def _media_rows(self, media_ids: list[int]) -> list[Any]:
        out = []
        ids = list(dict.fromkeys(int(i) for i in media_ids))
        for i in range(0, len(ids), 900):
            chunk = ids[i : i + 900]
            out += self.db.q(
                f"""SELECT m.*, f.path AS folder_path FROM media m JOIN folders f ON f.id=m.folder_id
                    WHERE m.id IN ({','.join('?' * len(chunk))}) AND m.state='active'""",
                chunk,
            )
        order = {mid: n for n, mid in enumerate(ids)}
        out.sort(key=lambda r: order.get(r["id"], 0))
        return out

    def _dest_path(self, r: Any, dest: str, structure: str, person: str | None) -> str:
        name = r["name"]
        if structure == "flat":
            return os.path.join(dest, name)
        if structure == "date":
            if r["taken_at"]:
                dt = datetime.fromtimestamp(r["taken_at"])
                return os.path.join(dest, f"{dt:%Y}", f"{dt:%m}", name)
            return os.path.join(dest, "Unknown date", name)
        if structure == "person":
            return os.path.join(dest, safe_name(person or "Others"), name)
        root_name = safe_name(os.path.basename(r["folder_path"].rstrip("\\/")) or "Drive")
        return os.path.join(dest, root_name, r["rel_dir"], name) if r["rel_dir"] else os.path.join(dest, root_name, name)

    # ------------------------------------------------------------------ copy
    def start_copy(
        self,
        media_ids: list[int],
        dest: str,
        structure: str = "keep",
        conflict: str = "rename",
        mode: str = "copy",
        title: str | None = None,
        person_by_media: dict[int, str] | None = None,
    ) -> int:
        p = self.plan(media_ids, dest, structure, conflict, person_by_media)
        if p["count"] == 0:
            raise ValueError("Nothing to copy: the files are missing or already in that place.")
        if not p["enough_space"]:
            raise ValueError("There isn't enough free space at the destination.")
        os.makedirs(lp(p["dest"]), exist_ok=True)
        now = time.time()
        with self.db.tx() as c:
            cur = c.execute(
                """INSERT INTO operations(kind, status, title, dest, structure, conflict, created_at, total, bytes_total)
                   VALUES(?, 'running', ?, ?, ?, ?, ?, ?, ?)""",
                ("move" if mode == "move" else "copy", title, p["dest"], structure, conflict, now, p["count"], p["bytes"]),
            )
            op_id = cur.lastrowid
            c.executemany(
                "INSERT INTO op_items(op_id, media_id, src, dst, size, state) VALUES(?,?,?,?,?,?)",
                [(op_id, it["media_id"], it["src"], it["dst"], it["size"], "skipped" if it["state"] == "skip" else "pending") for it in p["items"]],
            )
        self._spawn(op_id)
        return op_id

    def resume(self, op_id: int) -> None:
        op = self._op(op_id)
        if op["status"] not in ("paused", "failed"):
            ev = self._pause.get(op_id)
            if ev:
                ev.clear()
            return
        self.db.x("UPDATE operations SET status='running', error=NULL WHERE id=?", (op_id,))
        if op_id in self._threads and self._threads[op_id].is_alive():
            self._pause[op_id].clear()
        else:
            self._spawn(op_id)
        self._emit(op_id)

    def pause(self, op_id: int) -> None:
        ev = self._pause.get(op_id)
        if ev:
            ev.set()
        self.db.x("UPDATE operations SET status='paused' WHERE id=? AND status='running'", (op_id,))
        self._emit(op_id)

    def cancel(self, op_id: int) -> None:
        ev = self._cancel.get(op_id)
        if ev:
            ev.set()
        pe = self._pause.get(op_id)
        if pe:
            pe.clear()
        self.db.x("UPDATE operations SET status='cancelled', finished_at=? WHERE id=? AND status IN ('running','paused')", (time.time(), op_id))
        self._emit(op_id)

    def _spawn(self, op_id: int) -> None:
        self._pause[op_id] = threading.Event()
        self._cancel[op_id] = threading.Event()
        t = threading.Thread(target=self._run_copy, args=(op_id,), name=f"op-{op_id}", daemon=True)
        self._threads[op_id] = t
        t.start()

    def _wait_if_paused(self, op_id: int) -> None:
        pe, ce = self._pause[op_id], self._cancel[op_id]
        while pe.is_set():
            if ce.is_set():
                raise OpCancelled()
            time.sleep(0.2)
        if ce.is_set():
            raise OpCancelled()

    def _run_copy(self, op_id: int) -> None:
        op = self._op(op_id)
        bytes_done = self.db.scalar(
            "SELECT COALESCE(SUM(size),0) FROM op_items WHERE op_id=? AND state IN ('verified','identical','skipped','failed')",
            (op_id,),
            default=0,
        )
        self._rate[op_id] = (time.time(), bytes_done)
        self.db.x("UPDATE operations SET bytes_done=? WHERE id=?", (bytes_done, op_id))
        planned: set[str] = set()
        try:
            items = self.db.q("SELECT * FROM op_items WHERE op_id=? AND state IN ('pending','copied') ORDER BY id", (op_id,))
            for it in items:
                self._wait_if_paused(op_id)
                m0 = _mtime(it["src"])
                state, dst, h, err = self._copy_one(op_id, it, op["conflict"], planned)
                if state in REMOVABLE and _mtime(it["src"]) != m0:
                    state, err = "failed", "The original changed while it was being copied. Run the copy again."
                planned.add(os.path.normcase(dst))
                with self.db.tx() as c:
                    c.execute(
                        "UPDATE op_items SET state=?, dst=?, hash=?, error=?, src_mtime=? WHERE id=?",
                        (state, dst, h, err, m0, it["id"]),
                    )
                    c.execute(
                        """UPDATE operations SET done=(SELECT COUNT(*) FROM op_items WHERE op_id=? AND state IN ('verified','identical','skipped')),
                           failed=(SELECT COUNT(*) FROM op_items WHERE op_id=? AND state='failed') WHERE id=?""",
                        (op_id, op_id, op_id),
                    )
                self._emit(op_id)
            self.db.x("UPDATE operations SET status='done', finished_at=? WHERE id=?", (time.time(), op_id))
            if op["kind"] == "move":
                self.remove_originals(op_id, "bin")
        except OpCancelled:
            self.db.x("UPDATE operations SET status='cancelled', finished_at=? WHERE id=?", (time.time(), op_id))
        except Exception as e:  # unexpected: leave the journal so it can resume
            log.exception("operation %s failed", op_id)
            self.db.x("UPDATE operations SET status='failed', error=? WHERE id=?", (str(e)[:300], op_id))
        finally:
            self._emit(op_id, force=True)
            self.ctx.events.publish("ops.changed", {"id": op_id})
            op2 = self._op(op_id)
            if op2["status"] == "done":
                self.ctx.events.publish("library.changed", {"op": op_id})

    def _copy_one(self, op_id: int, it: Any, conflict: str, planned: set[str]) -> tuple[str, str, str | None, str | None]:
        src, dst = it["src"], it["dst"]
        if not os.path.exists(lp(src)):
            return "failed", dst, None, "The original file is missing."
        if os.path.exists(lp(dst)):
            # A file is already there: identical content counts as a verified copy.
            if os.path.getsize(lp(dst)) == os.path.getsize(lp(src)):
                hs, hd = _hash(src), _hash(dst)
                if hs == hd:
                    self._add_bytes(op_id, it["size"])
                    return "identical", dst, hs, None
            if conflict == "skip":
                self._add_bytes(op_id, it["size"])
                return "skipped", dst, None, "A different file with this name is already there."
            dst = unique_path(dst, planned)
        os.makedirs(lp(os.path.dirname(dst)), exist_ok=True)
        part = dst + ".recpro-part"
        h = blake3()
        try:
            with open(lp(src), "rb") as fi, open(lp(part), "wb") as fo:
                while True:
                    self._wait_if_paused(op_id)
                    b = fi.read(CHUNK)
                    if not b:
                        break
                    h.update(b)
                    fo.write(b)
                    self._add_bytes(op_id, len(b))
                fo.flush()
                os.fsync(fo.fileno())
            shutil.copystat(lp(src), lp(part))
            if os.path.exists(lp(dst)):
                dst = unique_path(dst, planned)
            os.rename(lp(part), lp(dst))
        except OpCancelled:
            _silent_remove(part)
            raise
        except OSError as e:
            _silent_remove(part)
            return "failed", dst, None, f"Copy failed: {e.strerror or e}"
        src_hash = h.hexdigest()
        try:
            dst_hash = _hash(dst)
        except OSError as e:
            return "failed", dst, src_hash, f"Couldn't read the copy back: {e.strerror or e}"
        if dst_hash != src_hash:
            _silent_remove(dst)
            return "failed", dst, src_hash, "The copy didn't match the original, so it was deleted. Try again."
        return "verified", dst, src_hash, None

    def _add_bytes(self, op_id: int, n: int) -> None:
        self.db.x("UPDATE operations SET bytes_done=bytes_done+? WHERE id=?", (n, op_id))
        self._emit(op_id)

    # ------------------------------------------------------------------ removal
    def remove_originals(self, op_id: int, mode: str, item_ids: list[int] | None = None) -> dict[str, Any]:
        if mode not in ("bin", "recycle", "keep"):
            raise ValueError("Unknown removal mode")
        op = self._op(op_id)
        if op["status"] != "done":
            raise ValueError("Wait until the copy has finished and been verified.")
        if mode == "keep":
            self.db.x("UPDATE operations SET removal='keep' WHERE id=?", (op_id,))
            self._emit(op_id, force=True)
            return {"removed": 0, "skipped": []}
        q = f"SELECT * FROM op_items WHERE op_id=? AND state IN ({','.join('?' * len(REMOVABLE))})"
        params: list[Any] = [op_id, *REMOVABLE]
        if item_ids:
            q += f" AND id IN ({','.join('?' * len(item_ids))})"
            params += item_ids
        items = self.db.q(q, params)
        removed, skipped = 0, []
        for it in items:
            src = it["src"]
            if not os.path.exists(lp(src)):
                skipped.append({"src": src, "reason": "Already gone"})
                continue
            if it["src_mtime"] is not None and abs(_mtime(src) - it["src_mtime"]) > 1e-3 or os.path.getsize(lp(src)) != it["size"]:
                skipped.append({"src": src, "reason": "Changed after it was copied, so it was kept."})
                continue
            if not it["dst"] or not os.path.exists(lp(it["dst"])):
                skipped.append({"src": src, "reason": "The copy is missing, so the original was kept."})
                continue
            try:
                if mode == "bin":
                    target = self._move_to_bin(src, op_id)
                    removed_to = target
                    media_state = "binned"
                else:
                    from send2trash import send2trash

                    send2trash(lp(src))
                    removed_to = "recycle"
                    media_state = "recycled"
            except OSError as e:
                skipped.append({"src": src, "reason": f"Couldn't move it: {e.strerror or e}"})
                continue
            with self.db.tx() as c:
                c.execute("UPDATE op_items SET state='removed', removed_to=? WHERE id=?", (removed_to, it["id"]))
                if it["media_id"]:
                    c.execute("UPDATE media SET state=? WHERE id=?", (media_state, it["media_id"]))
            removed += 1
        self.db.x("UPDATE operations SET removal=? WHERE id=?", (mode, op_id))
        self._emit(op_id, force=True)
        self.ctx.events.publish("ops.changed", {"id": op_id})
        self.ctx.events.publish("library.changed", {"op": op_id})
        return {"removed": removed, "skipped": skipped}

    def _move_to_bin(self, path: str, op_id: int) -> str:
        roots = [volume_root(path)]
        libs = sorted((r["path"] for r in self.db.q("SELECT path FROM folders")), key=len, reverse=True)
        lib_root = next((p for p in libs if is_inside(path, p)), None)
        if lib_root:
            roots.append(lib_root)
        last: OSError | None = None
        for root in roots:
            try:
                bin_dir = ensure_bin(root, op_id)
                rel = path_under_volume(path) if root == volume_root(path) else os.path.relpath(path, root)
                target = os.path.join(str(bin_dir), rel)
                os.makedirs(lp(os.path.dirname(target)), exist_ok=True)
                target = unique_path(target)
                os.rename(lp(path), lp(target))  # same drive: instant, no copy
                return target
            except OSError as e:
                last = e
        raise last or OSError("Couldn't move to the bin")

    # ------------------------------------------------------------------ undo / bin
    def undo(self, op_id: int) -> dict[str, Any]:
        """Removed originals come back; if nothing was removed, the copies go to the Bin."""
        op = self._op(op_id)
        removed = self.db.q("SELECT * FROM op_items WHERE op_id=? AND state='removed'", (op_id,))
        if removed:
            res = self.restore_items([r["id"] for r in removed])
            self.db.x("UPDATE operations SET removal=NULL WHERE id=?", (op_id,))
            self._emit(op_id, force=True)
            return {"restored": res["restored"], "copies_binned": 0, "skipped": res["skipped"]}
        if op["status"] in ("running", "paused"):
            raise ValueError("Pause or cancel the operation first.")
        copies = self.db.q("SELECT * FROM op_items WHERE op_id=? AND state='verified'", (op_id,))
        binned, skipped = 0, []
        for it in copies:
            dst = it["dst"]
            if not dst or not os.path.exists(lp(dst)):
                continue
            try:
                target = self._move_to_bin(dst, op_id)
            except OSError as e:
                skipped.append({"src": dst, "reason": str(e)})
                continue
            self.db.x("UPDATE op_items SET state='copy_binned', removed_to=? WHERE id=?", (target, it["id"]))
            binned += 1
        self.db.x("UPDATE operations SET status='undone', finished_at=? WHERE id=?", (time.time(), op_id))
        self._emit(op_id, force=True)
        self.ctx.events.publish("ops.changed", {"id": op_id})
        self.ctx.events.publish("library.changed", {"op": op_id})
        return {"restored": 0, "copies_binned": binned, "skipped": skipped}

    def restore_items(self, item_ids: list[int]) -> dict[str, Any]:
        restored, skipped = 0, []
        for i in range(0, len(item_ids), 900):
            chunk = item_ids[i : i + 900]
            rows = self.db.q(f"SELECT * FROM op_items WHERE id IN ({','.join('?' * len(chunk))})", chunk)
            for it in rows:
                if it["state"] not in ("removed", "copy_binned") or not it["removed_to"] or it["removed_to"] == "recycle":
                    if it["removed_to"] == "recycle":
                        skipped.append({"src": it["src"], "reason": "Restore this one from the Windows Recycle Bin."})
                    continue
                back_to = it["src"] if it["state"] == "removed" else it["dst"]
                if not os.path.exists(lp(it["removed_to"])):
                    skipped.append({"src": back_to, "reason": "It's no longer in the bin."})
                    continue
                target = back_to if not os.path.exists(lp(back_to)) else unique_path(_with_suffix(back_to, " (restored)"))
                try:
                    os.makedirs(lp(os.path.dirname(target)), exist_ok=True)
                    os.rename(lp(it["removed_to"]), lp(target))
                except OSError as e:
                    skipped.append({"src": back_to, "reason": f"Couldn't restore: {e.strerror or e}"})
                    continue
                with self.db.tx() as c:
                    if it["state"] == "removed":
                        c.execute(
                            "UPDATE op_items SET state='verified', removed_to=NULL, src=?, src_mtime=? WHERE id=?",
                            (target, _mtime(target), it["id"]),
                        )
                        if it["media_id"]:
                            c.execute("UPDATE media SET state='active', path=?, name=? WHERE id=?", (target, os.path.basename(target), it["media_id"]))
                    else:
                        c.execute("UPDATE op_items SET state='verified', removed_to=NULL, dst=? WHERE id=?", (target, it["id"]))
                        c.execute("UPDATE operations SET status='done' WHERE id=? AND status='undone'", (it["op_id"],))
                restored += 1
                _prune_empty(os.path.dirname(it["removed_to"]))
        self.ctx.events.publish("ops.changed", {})
        self.ctx.events.publish("library.changed", {})
        return {"restored": restored, "skipped": skipped}

    def bin_list(self) -> list[dict[str, Any]]:
        rows = self.db.q(
            """SELECT o.id, o.kind, o.title, o.dest, o.created_at, COUNT(i.id) AS n, COALESCE(SUM(i.size),0) AS bytes,
                      MIN(i.media_id) AS sample_media
               FROM operations o JOIN op_items i ON i.op_id=o.id
               WHERE i.state IN ('removed','copy_binned') AND i.removed_to IS NOT NULL AND i.removed_to != 'recycle'
               GROUP BY o.id ORDER BY o.created_at DESC"""
        )
        return [dict(r) for r in rows]

    def bin_items(self, op_id: int) -> list[dict[str, Any]]:
        rows = self.db.q(
            """SELECT id, media_id, src, dst, size, state, removed_to FROM op_items
               WHERE op_id=? AND state IN ('removed','copy_binned') AND removed_to != 'recycle' ORDER BY id""",
            (op_id,),
        )
        return [dict(r) for r in rows]

    def empty_bin(self, op_ids: list[int] | None = None) -> dict[str, Any]:
        """Permanently deletes binned files. Only called after the user confirms in the UI."""
        q = "SELECT * FROM op_items WHERE state IN ('removed','copy_binned') AND removed_to IS NOT NULL AND removed_to != 'recycle'"
        params: list[Any] = []
        if op_ids:
            q += f" AND op_id IN ({','.join('?' * len(op_ids))})"
            params = list(op_ids)
        rows = self.db.q(q, params)
        deleted, freed = 0, 0
        dirs: set[str] = set()
        for it in rows:
            p = it["removed_to"]
            # Safety: only ever delete inside a RecPro bin folder.
            if f"{os.sep}{BIN_DIR}{os.sep}".lower() not in unlp(lp(p)).lower():
                continue
            try:
                if os.path.exists(lp(p)):
                    freed += os.path.getsize(lp(p))
                    os.remove(lp(p))
                deleted += 1
            except OSError as e:
                log.warning("couldn't delete %s: %s", p, e)
                continue
            dirs.add(os.path.dirname(p))
            with self.db.tx() as c:
                c.execute("UPDATE op_items SET state='purged' WHERE id=?", (it["id"],))
                if it["state"] == "removed" and it["media_id"]:
                    c.execute("DELETE FROM media WHERE id=? AND state='binned'", (it["media_id"],))
        for d in dirs:
            _prune_empty(d)
        self.ctx.events.publish("ops.changed", {})
        return {"deleted": deleted, "freed": freed}

    # ------------------------------------------------------------------ queries
    def _op(self, op_id: int) -> Any:
        op = self.db.q1("SELECT * FROM operations WHERE id=?", (op_id,))
        if op is None:
            raise KeyError(op_id)
        return op

    def op_dict(self, op_id: int) -> dict[str, Any]:
        op = dict(self._op(op_id))
        counts = {
            r["state"]: r["n"]
            for r in self.db.q("SELECT state, COUNT(*) n FROM op_items WHERE op_id=? GROUP BY state", (op_id,))
        }
        op["counts"] = counts
        op["removable"] = sum(counts.get(s, 0) for s in REMOVABLE)
        t0, b0 = self._rate.get(op_id, (None, None))
        if t0 and op["status"] == "running":
            dt = time.time() - t0
            op["rate"] = (op["bytes_done"] - b0) / dt if dt > 1 else None
        return op

    def list_ops(self, limit: int = 100) -> list[dict[str, Any]]:
        ids = [r["id"] for r in self.db.q("SELECT id FROM operations ORDER BY created_at DESC LIMIT ?", (limit,))]
        return [self.op_dict(i) for i in ids]

    def items(self, op_id: int, state: str | None = None, limit: int = 500, offset: int = 0) -> list[dict[str, Any]]:
        q = "SELECT * FROM op_items WHERE op_id=?"
        params: list[Any] = [op_id]
        if state:
            q += " AND state=?"
            params.append(state)
        q += " ORDER BY id LIMIT ? OFFSET ?"
        params += [limit, offset]
        return [dict(r) for r in self.db.q(q, params)]

    _last_emit: dict[int, float] = {}

    def _emit(self, op_id: int, force: bool = False) -> None:
        now = time.time()
        if not force and now - self._last_emit.get(op_id, 0) < 0.25:
            return
        self._last_emit[op_id] = now
        try:
            self.ctx.events.publish("op.progress", self.op_dict(op_id))
        except KeyError:
            pass

    def _cleanup_parts(self) -> None:
        for r in self.db.q("SELECT dst FROM op_items WHERE state IN ('pending','copied') AND dst IS NOT NULL"):
            _silent_remove(r["dst"] + ".recpro-part")


def _hash(path: str) -> str:
    h = blake3()
    with open(lp(path), "rb") as f:
        while True:
            b = f.read(CHUNK)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def _mtime(path: str) -> float | None:
    try:
        return os.stat(lp(path)).st_mtime
    except OSError:
        return None


def _silent_remove(path: str) -> None:
    try:
        os.remove(lp(path))
    except OSError:
        pass


def _with_suffix(path: str, suffix: str) -> str:
    base, ext = os.path.splitext(path)
    return f"{base}{suffix}{ext}"


def _prune_empty(d: str) -> None:
    """Remove empty folders inside a bin after restores/purges (never above the bin)."""
    try:
        while d and BIN_DIR.lower() in d.lower() and os.path.basename(d).lower() != BIN_DIR.lower():
            if os.listdir(lp(d)):
                break
            os.rmdir(lp(d))
            d = os.path.dirname(d)
    except OSError:
        pass


def create(ctx: Context) -> Ops:
    return Ops(ctx)
