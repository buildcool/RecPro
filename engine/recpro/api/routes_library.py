from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..context import Context
from .deps import ctx

router = APIRouter()


class AddFolders(BaseModel):
    paths: list[str]
    recursive: bool = True


class FolderPatch(BaseModel):
    watch: bool | None = None
    recursive: bool | None = None
    excluded: list[str] | None = None


def _lib(c: Context):
    lib = c.services.get("library")
    if lib is None:
        raise HTTPException(503, "Library service unavailable")
    return lib


@router.get("/api/folders")
def list_folders(c: Context = Depends(ctx)) -> list[dict[str, Any]]:
    return _lib(c).list_folders()


@router.post("/api/folders")
def add_folders(body: AddFolders, c: Context = Depends(ctx)) -> dict[str, Any]:
    if not body.paths:
        raise HTTPException(400, "Choose at least one folder.")
    return _lib(c).add_folders(body.paths, body.recursive)


@router.patch("/api/folders/{folder_id}")
def patch_folder(folder_id: int, body: FolderPatch, c: Context = Depends(ctx)) -> dict[str, Any]:
    _lib(c).update_folder(folder_id, body.model_dump(exclude_none=True))
    return {"ok": True}


@router.delete("/api/folders/{folder_id}")
def remove_folder(folder_id: int, c: Context = Depends(ctx)) -> dict[str, Any]:
    _lib(c).remove_folder(folder_id)
    return {"ok": True}


@router.post("/api/folders/{folder_id}/rescan")
def rescan(folder_id: int, c: Context = Depends(ctx)) -> dict[str, Any]:
    _lib(c).request_scan(folder_id)
    return {"ok": True}


@router.post("/api/folders/rescan-all")
def rescan_all(c: Context = Depends(ctx)) -> dict[str, Any]:
    lib = _lib(c)
    for r in c.db.q("SELECT id FROM folders"):
        lib.request_scan(r["id"])
    return {"ok": True}


@router.get("/api/index/status")
def index_status(c: Context = Depends(ctx)) -> dict[str, Any]:
    ix = c.services.get("indexer")
    return ix.status() if ix else {}  # type: ignore[attr-defined]


@router.post("/api/index/pause")
def pause(c: Context = Depends(ctx)) -> dict[str, Any]:
    c.services["indexer"].pause()  # type: ignore[attr-defined]
    return {"ok": True}


@router.post("/api/index/resume")
def resume(c: Context = Depends(ctx)) -> dict[str, Any]:
    c.services["indexer"].resume()  # type: ignore[attr-defined]
    return {"ok": True}


@router.get("/api/stats")
def stats(c: Context = Depends(ctx)) -> dict[str, Any]:
    db = c.db
    priv = c.services.get("private")
    hide_private = not (priv and priv.visible_everywhere())  # type: ignore[attr-defined]
    hidden_clause = " AND sens_state NOT IN ('private','review')" if hide_private else ""
    r = db.q1(
        f"""SELECT COALESCE(SUM(kind='image'),0) photos, COALESCE(SUM(kind='video'),0) videos, COALESCE(SUM(size),0) bytes
            FROM media WHERE state='active'{hidden_clause}"""
    )
    people = db.scalar("SELECT COUNT(*) FROM people WHERE hidden=0 AND kind='human'", default=0)
    named = db.scalar("SELECT COUNT(*) FROM people WHERE hidden=0 AND name IS NOT NULL AND kind='human'", default=0)
    review = 0
    rv = c.services.get("people")
    if rv is not None:
        try:
            review = int(rv.review_counts().get("total", 0))  # type: ignore[attr-defined]
        except Exception:
            review = 0
    private_hidden = db.scalar("SELECT COUNT(*) FROM media WHERE state='active' AND sens_state IN ('private','review')", default=0) if hide_private else 0
    return {
        "photos": r["photos"],
        "videos": r["videos"],
        "bytes": r["bytes"],
        "folders": db.scalar("SELECT COUNT(*) FROM folders", default=0),
        "people": people,
        "named_people": named,
        "review": review,
        "private_hidden": private_hidden,
    }
