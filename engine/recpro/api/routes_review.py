from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..context import Context
from .deps import ctx

router = APIRouter()


class FaceAnswer(BaseModel):
    person_id: int
    yes: list[int] = []
    no: list[int] = []


class MergeAnswer(BaseModel):
    a: int
    b: int
    same: bool


def _svc(c: Context):
    s = c.services.get("people")
    if s is None:
        raise HTTPException(503, "People service unavailable")
    return s


@router.get("/api/review/counts")
def counts(c: Context = Depends(ctx)) -> dict[str, int]:
    return _svc(c).review_counts()


@router.get("/api/review/faces")
def review_faces(person_id: int | None = None, limit: int = 12, c: Context = Depends(ctx)) -> dict[str, Any]:
    return _svc(c).review_faces(person_id, min(max(limit, 1), 48))


@router.post("/api/review/faces/answer")
def answer_faces(body: FaceAnswer, c: Context = Depends(ctx)) -> dict[str, Any]:
    if not body.yes and not body.no:
        raise HTTPException(400, "Nothing to answer")
    return _svc(c).answer(body.person_id, body.yes, body.no)


@router.post("/api/review/undo")
def undo(c: Context = Depends(ctx)) -> dict[str, Any]:
    return {"undone": _svc(c).undo_last()}


@router.get("/api/review/merge")
def merge_suggestions(limit: int = 10, c: Context = Depends(ctx)) -> list[dict[str, Any]]:
    return _svc(c).merge_suggestions(limit)


@router.post("/api/review/merge/answer")
def merge_answer(body: MergeAnswer, c: Context = Depends(ctx)) -> dict[str, Any]:
    svc = _svc(c)
    if body.same:
        a = c.db.q1("SELECT id, name FROM people WHERE id=?", (body.a,))
        b = c.db.q1("SELECT id, name FROM people WHERE id=?", (body.b,))
        if not a or not b:
            raise HTTPException(404, "Person not found")
        # keep the named one (or the bigger group)
        src, dst = (a, b) if (b["name"] and not a["name"]) else (b, a)
        svc.merge(src["id"], dst["id"])
        return {"merged_into": dst["id"]}
    svc.set_not_same(body.a, body.b)
    return {"merged_into": None}


@router.get("/api/review/name")
def name_suggestions(limit: int = 8, c: Context = Depends(ctx)) -> list[dict[str, Any]]:
    return _svc(c).name_suggestions(limit)
