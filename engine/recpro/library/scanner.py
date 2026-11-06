"""Walks library folders and reconciles what's on disk with the database.

Change detection is by (size, mtime). A file that disappeared and reappears elsewhere
with the same quick hash keeps its row (and therefore its faces, labels and answers).
"""
from __future__ import annotations

import logging
import os
import stat as stat_mod
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..db import Database
from .formats import CLOUD_ONLY_MASK, FILE_ATTRIBUTE_SYSTEM, SKIP_DIRS, kind_for
from .hashing import quick_hash

log = logging.getLogger("recpro.scan")


@dataclass
class FoundFile:
    path: str
    rel_dir: str
    name: str
    ext: str
    kind: str
    size: int
    mtime: float


@dataclass
class ScanResult:
    found: int = 0
    added: int = 0
    changed: int = 0
    moved: int = 0
    missing: int = 0
    skipped_cloud: int = 0
    errors: list[str] = field(default_factory=list)


def norm(p: str | Path) -> str:
    return os.path.normcase(os.path.abspath(str(p)))


def walk(root: str, recursive: bool, excluded: set[str], data_dir: str, result: ScanResult) -> list[FoundFile]:
    out: list[FoundFile] = []
    root_abs = os.path.abspath(root)
    stack = [root_abs]
    data_norm = norm(data_dir)
    while stack:
        d = stack.pop()
        try:
            it = os.scandir(d)
        except OSError as e:
            result.errors.append(f"{d}: {e.strerror or e}")
            continue
        with it:
            for e in it:
                name = e.name
                try:
                    if e.is_dir(follow_symlinks=False):
                        if not recursive:
                            continue
                        low = name.lower()
                        if low in SKIP_DIRS or name.startswith((".", "$")):
                            continue
                        full = e.path
                        if norm(full) in excluded or norm(full) == data_norm:
                            continue
                        try:
                            st = e.stat(follow_symlinks=False)
                            attrs = getattr(st, "st_file_attributes", 0)
                            if attrs & FILE_ATTRIBUTE_SYSTEM or stat_mod.S_ISLNK(st.st_mode):
                                continue
                            # skip junctions / reparse points to avoid loops
                            if attrs & 0x400:  # FILE_ATTRIBUTE_REPARSE_POINT
                                continue
                        except OSError:
                            continue
                        stack.append(full)
                        continue
                    if not e.is_file(follow_symlinks=False):
                        continue
                    ext = os.path.splitext(name)[1].lower()
                    kind = kind_for(ext)
                    if kind is None:
                        continue
                    st = e.stat(follow_symlinks=False)
                    attrs = getattr(st, "st_file_attributes", 0)
                    if attrs & CLOUD_ONLY_MASK:
                        result.skipped_cloud += 1
                        continue
                    if st.st_size < 512:
                        continue
                    rel = os.path.relpath(d, root_abs)
                    out.append(
                        FoundFile(
                            path=e.path,
                            rel_dir="" if rel == "." else rel,
                            name=name,
                            ext=ext,
                            kind=kind,
                            size=st.st_size,
                            mtime=st.st_mtime,
                        )
                    )
                except OSError as err:
                    result.errors.append(f"{e.path}: {err.strerror or err}")
    result.found = len(out)
    return out


def reconcile(db: Database, folder_id: int, files: list[FoundFile], result: ScanResult) -> list[int]:
    """Insert/update/mark-missing. Returns ids of media whose analysis must (re)run."""
    existing = {
        r["path"]: r
        for r in db.q(
            "SELECT id, path, size, mtime, state, quick_hash FROM media WHERE folder_id=?",
            (folder_id,),
        )
    }
    now = time.time()
    seen: set[str] = set()
    new_files: list[FoundFile] = []
    changed: list[tuple[int, FoundFile]] = []
    revived: list[int] = []

    for f in files:
        row = existing.get(f.path)
        seen.add(f.path)
        if row is None:
            new_files.append(f)
            continue
        if row["state"] == "missing":
            revived.append(row["id"])
        if row["size"] != f.size or abs(row["mtime"] - f.mtime) > 1e-3:
            changed.append((row["id"], f))
    changed_ids = [mid for mid, _ in changed]

    gone = [r for p, r in existing.items() if p not in seen and r["state"] == "active"]

    # Detect moves: a file that vanished and a new file with the same quick hash.
    moved_pairs: list[tuple[int, FoundFile]] = []
    if gone and new_files:
        gone_by_hash: dict[str, list[int]] = {}
        for r in gone:
            if r["quick_hash"]:
                gone_by_hash.setdefault(r["quick_hash"], []).append(r["id"])
        if gone_by_hash:
            remaining = []
            for f in new_files:
                try:
                    qh = quick_hash(f.path, f.size)
                except OSError:
                    remaining.append(f)
                    continue
                ids = gone_by_hash.get(qh)
                if ids:
                    moved_pairs.append((ids.pop(), f))
                else:
                    remaining.append(f)
            new_files = remaining
    moved_ids = {mid for mid, _ in moved_pairs}

    with db.tx() as c:
        for mid, f in moved_pairs:
            c.execute(
                "UPDATE media SET path=?, rel_dir=?, name=?, ext=?, mtime=?, state='active' WHERE id=?",
                (f.path, f.rel_dir, f.name, f.ext, f.mtime, mid),
            )
        c.executemany(
            """INSERT INTO media(folder_id, path, rel_dir, name, ext, kind, size, mtime, added_at)
               VALUES(?,?,?,?,?,?,?,?,?)
               ON CONFLICT(path) DO UPDATE SET folder_id=excluded.folder_id, rel_dir=excluded.rel_dir""",
            [(folder_id, f.path, f.rel_dir, f.name, f.ext, f.kind, f.size, f.mtime, now) for f in new_files],
        )
        for mid, f in changed:
            # content changed: everything must be recomputed (answers on old faces go with them)
            c.execute("DELETE FROM faces WHERE media_id=?", (mid,))
            c.execute("DELETE FROM media_labels WHERE media_id=? AND state='ai'", (mid,))
            c.execute("DELETE FROM embeddings WHERE media_id=?", (mid,))
            c.execute(
                """UPDATE media SET size=?, mtime=?, quick_v=0, sens_v=0, deep_v=0, text_v=0, video_v=0,
                   sens_state='unchecked', sens_score=NULL, face_count=0, content_hash=NULL, quick_hash=NULL,
                   error=NULL WHERE id=?""",
                (f.size, f.mtime, mid),
            )
        for mid in revived:
            c.execute("UPDATE media SET state='active' WHERE id=? AND state='missing'", (mid,))
        for r in gone:
            if r["id"] in moved_ids:
                continue
            c.execute("UPDATE media SET state='missing' WHERE id=? AND state='active'", (r["id"],))

    result.added += len(new_files)
    result.changed += len(changed_ids)
    result.moved += len(moved_pairs)
    result.missing += len(gone) - len(moved_pairs)
    return changed_ids
