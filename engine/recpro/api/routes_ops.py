from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..context import Context
from .deps import ctx

router = APIRouter()


class CopyRequest(BaseModel):
    media_ids: list[int]
    dest: str
    structure: str = "keep"
    conflict: str = "rename"
    mode: str = "copy"  # copy | move
    title: str | None = None
    person_by_media: dict[int, str] | None = None


class RemoveRequest(BaseModel):
    mode: str  # bin | recycle | keep
    item_ids: list[int] | None = None


class RestoreRequest(BaseModel):
    item_ids: list[int] | None = None
    op_id: int | None = None


class EmptyRequest(BaseModel):
    op_ids: list[int] | None = None
    confirm: bool = False


def _ops(c: Context):
    o = c.services.get("ops")
    if o is None:
        raise HTTPException(503, "File operations unavailable")
    return o


@router.post("/api/ops/plan")
def plan(body: CopyRequest, c: Context = Depends(ctx)) -> dict[str, Any]:
    try:
        p = _ops(c).plan(body.media_ids, body.dest, body.structure, body.conflict, body.person_by_media)
    except ValueError as e:
        raise HTTPException(400, str(e))
    p["items"] = p["items"][:200]  # preview only
    return p


@router.post("/api/ops/copy")
def copy(body: CopyRequest, c: Context = Depends(ctx)) -> dict[str, Any]:
    try:
        op_id = _ops(c).start_copy(
            body.media_ids, body.dest, body.structure, body.conflict, body.mode, body.title, body.person_by_media
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _ops(c).op_dict(op_id)


@router.get("/api/ops")
def list_ops(c: Context = Depends(ctx)) -> list[dict[str, Any]]:
    return _ops(c).list_ops()


@router.get("/api/ops/{op_id}")
def get_op(op_id: int, c: Context = Depends(ctx)) -> dict[str, Any]:
    try:
        return _ops(c).op_dict(op_id)
    except KeyError:
        raise HTTPException(404, "Operation not found")


@router.get("/api/ops/{op_id}/items")
def op_items(op_id: int, state: str | None = None, limit: int = 500, offset: int = 0, c: Context = Depends(ctx)) -> list[dict[str, Any]]:
    return _ops(c).items(op_id, state, min(limit, 2000), offset)


@router.post("/api/ops/{op_id}/pause")
def pause(op_id: int, c: Context = Depends(ctx)) -> dict[str, Any]:
    _ops(c).pause(op_id)
    return _ops(c).op_dict(op_id)


@router.post("/api/ops/{op_id}/resume")
def resume(op_id: int, c: Context = Depends(ctx)) -> dict[str, Any]:
    _ops(c).resume(op_id)
    return _ops(c).op_dict(op_id)


@router.post("/api/ops/{op_id}/retry")
def retry(op_id: int, c: Context = Depends(ctx)) -> dict[str, Any]:
    try:
        _ops(c).retry_failed(op_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _ops(c).op_dict(op_id)


@router.post("/api/ops/{op_id}/cancel")
def cancel(op_id: int, c: Context = Depends(ctx)) -> dict[str, Any]:
    _ops(c).cancel(op_id)
    return _ops(c).op_dict(op_id)


@router.post("/api/ops/{op_id}/remove")
def remove(op_id: int, body: RemoveRequest, c: Context = Depends(ctx)) -> dict[str, Any]:
    try:
        return _ops(c).remove_originals(op_id, body.mode, body.item_ids)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/api/ops/{op_id}/undo")
def undo(op_id: int, c: Context = Depends(ctx)) -> dict[str, Any]:
    try:
        return _ops(c).undo(op_id)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/api/bin")
def bin_list(c: Context = Depends(ctx)) -> list[dict[str, Any]]:
    return _ops(c).bin_list()


@router.get("/api/bin/{op_id}")
def bin_items(op_id: int, c: Context = Depends(ctx)) -> list[dict[str, Any]]:
    return _ops(c).bin_items(op_id)


@router.post("/api/bin/restore")
def bin_restore(body: RestoreRequest, c: Context = Depends(ctx)) -> dict[str, Any]:
    ops = _ops(c)
    ids = list(body.item_ids or [])
    if body.op_id is not None:
        ids += [i["id"] for i in ops.bin_items(body.op_id)]
    if not ids:
        raise HTTPException(400, "Nothing to restore")
    return ops.restore_items(ids)


@router.post("/api/bin/empty")
def bin_empty(body: EmptyRequest, c: Context = Depends(ctx)) -> dict[str, Any]:
    if not body.confirm:
        raise HTTPException(400, "Emptying the bin deletes files permanently. Confirm to continue.")
    return _ops(c).empty_bin(body.op_ids)
