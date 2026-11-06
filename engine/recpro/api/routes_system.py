from __future__ import annotations

import asyncio
import json
import os
import shutil
import string
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect

from .. import __version__
from ..context import Context
from .deps import ctx

router = APIRouter()


@router.get("/api/health")
def health(c: Context = Depends(ctx)) -> dict[str, Any]:
    gpu = None
    ml = c.services.get("ml")
    if ml is not None:
        gpu = ml.device_info()  # type: ignore[attr-defined]
    return {
        "ok": True,
        "version": __version__,
        "dataDir": str(c.paths.data),
        "localOnly": True,
        "strictOffline": bool(c.settings.get("privacy.strict_offline")),
        "gpu": gpu,
    }


@router.get("/api/settings")
def get_settings(c: Context = Depends(ctx)) -> dict[str, Any]:
    return c.settings.all()


@router.patch("/api/settings")
def patch_settings(values: dict[str, Any], c: Context = Depends(ctx)) -> dict[str, Any]:
    try:
        out = c.settings.update(values)
    except KeyError as e:
        raise HTTPException(400, str(e))
    c.events.publish("settings", out)
    return out


@router.get("/api/fs/drives")
def drives() -> list[dict[str, Any]]:
    out = []
    if os.name == "nt":
        for letter in string.ascii_uppercase:
            root = f"{letter}:\\"
            if os.path.exists(root):
                try:
                    du = shutil.disk_usage(root)
                    out.append({"path": root, "total": du.total, "free": du.free})
                except OSError:
                    out.append({"path": root, "total": None, "free": None})
    else:
        du = shutil.disk_usage("/")
        out.append({"path": "/", "total": du.total, "free": du.free})
    return out


@router.get("/api/fs/list")
def list_dir(path: str) -> dict[str, Any]:
    """Folder browser used when no native picker is available (browser dev mode)."""
    p = Path(path)
    if not p.is_dir():
        raise HTTPException(404, "Folder not found")
    dirs = []
    try:
        with os.scandir(p) as it:
            for e in it:
                try:
                    if e.is_dir(follow_symlinks=False) and not e.name.startswith(("$", ".")):
                        dirs.append({"name": e.name, "path": e.path})
                except OSError:
                    continue
    except PermissionError:
        raise HTTPException(403, "No permission to read this folder")
    dirs.sort(key=lambda d: d["name"].lower())
    return {"path": str(p), "parent": str(p.parent) if p.parent != p else None, "dirs": dirs}


@router.get("/api/fs/free")
def free_space(path: str) -> dict[str, Any]:
    p = Path(path)
    probe = p
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    du = shutil.disk_usage(probe)
    return {"path": str(p), "free": du.free, "total": du.total}


@router.websocket("/ws")
async def ws_events(ws: WebSocket) -> None:
    c: Context = ws.app.state.ctx
    await ws.accept()
    q = c.events.subscribe()
    try:
        status = c.services.get("indexer")
        if status is not None:
            await ws.send_text(json.dumps({"type": "status", "data": status.status()}))  # type: ignore[attr-defined]
        while True:
            msg = await q.get()
            await ws.send_text(json.dumps(msg, default=str))
    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
    except Exception:
        pass
    finally:
        c.events.unsubscribe(q)
