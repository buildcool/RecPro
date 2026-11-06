from __future__ import annotations

import ctypes
import os
import re
from pathlib import Path

BIN_DIR = ".RecPro-Bin"
_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def lp(path: str) -> str:
    """Windows long-path form for paths that might exceed MAX_PATH."""
    if os.name != "nt":
        return path
    p = os.path.abspath(path)
    if p.startswith("\\\\?\\") or len(p) < 240:
        return p
    if p.startswith("\\\\"):
        return "\\\\?\\UNC\\" + p[2:]
    return "\\\\?\\" + p


def unlp(path: str) -> str:
    if path.startswith("\\\\?\\UNC\\"):
        return "\\\\" + path[8:]
    if path.startswith("\\\\?\\"):
        return path[4:]
    return path


def safe_name(s: str, fallback: str = "Unnamed") -> str:
    s = _INVALID.sub("_", s).strip().rstrip(".")
    return s[:120] or fallback


def volume_root(path: str) -> str:
    p = os.path.abspath(path)
    drive, _ = os.path.splitdrive(p)
    if drive:
        return drive + os.sep
    return os.sep


def path_under_volume(path: str) -> str:
    """Path relative to its volume root (drive letter or UNC share stripped)."""
    p = os.path.abspath(path)
    drive, rest = os.path.splitdrive(p)
    return rest.lstrip("\\/")


def same_volume(a: str, b: str) -> bool:
    return os.path.normcase(volume_root(a)) == os.path.normcase(volume_root(b))


def is_inside(child: str, parent: str) -> bool:
    c = os.path.normcase(os.path.abspath(child))
    p = os.path.normcase(os.path.abspath(parent))
    return c == p or c.startswith(p.rstrip("\\/") + os.sep)


def unique_path(path: str, taken: set[str] | None = None) -> str:
    """'name.jpg' -> 'name (1).jpg' until it's free on disk and not already planned."""
    taken = taken or set()
    base, ext = os.path.splitext(path)
    cand = path
    i = 1
    while os.path.exists(lp(cand)) or os.path.normcase(cand) in taken:
        cand = f"{base} ({i}){ext}"
        i += 1
    return cand


def hide(path: str) -> None:
    if os.name != "nt":
        return
    try:
        attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))
        if attrs != -1:
            ctypes.windll.kernel32.SetFileAttributesW(str(path), attrs | 0x2)
    except Exception:
        pass


def ensure_bin(root: str, op_id: int) -> Path:
    b = Path(root) / BIN_DIR
    fresh = not b.exists()
    b.mkdir(parents=True, exist_ok=True)
    if fresh:
        hide(str(b))
        try:
            (b / "README.txt").write_text(
                "Files moved here by RecPro after they were copied and verified.\n"
                "Restore or permanently delete them from RecPro > History and bin.\n",
                encoding="utf-8",
            )
        except OSError:
            pass
    d = b / f"op-{op_id}"
    d.mkdir(parents=True, exist_ok=True)
    return d
