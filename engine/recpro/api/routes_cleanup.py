from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..context import Context
from .deps import ctx

router = APIRouter()
KINDS = ("exact", "copies", "bursts", "blurry", "dark", "forwards")


class BinRequest(BaseModel):
    media_ids: list[int]
    title: str = "Cleanup"
    # exact duplicates: file -> the copy that stays (removed only if their full hashes match)
    same_as: dict[int, int] | None = None
    # copies and similar shots: file -> the one that stays (removed only while that one is there)
    keeps: dict[int, int] | None = None


@router.get("/api/cleanup")
def summary(c: Context = Depends(ctx)) -> dict[str, Any]:
    from ..cleanup import summary as s

    return s(c)


@router.get("/api/cleanup/{kind}")
def listing(kind: str, offset: int = 0, limit: int = 40, c: Context = Depends(ctx)) -> dict[str, Any]:
    from ..cleanup import listing as ls

    if kind not in KINDS:
        raise HTTPException(404, "Unknown kind of cleanup")
    return ls(c, kind, max(0, offset), min(max(1, limit), 200))


@router.post("/api/cleanup/bin")
def to_bin(body: BinRequest, c: Context = Depends(ctx)) -> dict[str, Any]:
    """Moves the chosen files to the RecPro Bin as one operation (Undo in History)."""
    from ..cleanup import forget

    if not body.media_ids:
        raise HTTPException(400, "Choose at least one file.")
    ops = c.services.get("ops")
    if ops is None:
        raise HTTPException(503, "File operations are unavailable")
    res = ops.bin_media(body.media_ids, body.title.strip()[:120] or "Cleanup", body.same_as, body.keeps)  # type: ignore[attr-defined]
    forget()
    return res
