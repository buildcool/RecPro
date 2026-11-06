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


class HiddenAnswer(BaseModel):
    yes: list[int] = []
    no: list[int] = []


@router.get("/api/review/hidden")
def hidden_people(c: Context = Depends(ctx)) -> list[dict[str, Any]]:
    """Named people with photos from the same outings where their face may be hidden."""
    from ..review.hidden import suggestions
    from .visibility import private_hidden

    hide = private_hidden(c)
    people = c.db.q(
        """SELECT p.id, p.name, p.cover_face_id, COUNT(*) n FROM people p JOIN faces f ON f.person_id=p.id
           WHERE p.name IS NOT NULL AND p.hidden=0 AND f.state IN ('confirmed','auto','cluster')
           GROUP BY p.id ORDER BY n DESC LIMIT 40"""
    )
    out = []
    for p in people:
        k = len(suggestions(c, p["id"], limit=200, hide_private=hide))
        if k:
            out.append({"id": p["id"], "name": p["name"], "cover_face_id": p["cover_face_id"], "count": k})
    return out


@router.get("/api/review/hidden/{person_id}")
def hidden_for(person_id: int, limit: int = 48, c: Context = Depends(ctx)) -> dict[str, Any]:
    from ..review.hidden import suggestions
    from .routes_media import item_dict
    from .visibility import check_pending, private_hidden

    p = c.db.q1("SELECT id, name FROM people WHERE id=?", (person_id,))
    if p is None:
        raise HTTPException(404, "Person not found")
    sug = suggestions(c, person_id, limit=min(limit, 200), hide_private=private_hidden(c))
    rows = {}
    ids = [s["media_id"] for s in sug]
    if ids:
        rows = {r["id"]: r for r in c.db.q(f"SELECT * FROM media WHERE id IN ({','.join('?' * len(ids))})", ids)}
    priv = c.services.get("private")
    blur = True if priv is None else bool(priv.blur_enabled())  # type: ignore[attr-defined]
    chk = check_pending(c)
    items = []
    for s in sug:
        r = rows.get(s["media_id"])
        if r is not None:
            items.append({**item_dict(r, chk, blur), "minutes": s["minutes"], "presence": s["presence"]})
    return {"person": dict(p), "items": items}


@router.post("/api/review/hidden/{person_id}/answer")
def hidden_answer(person_id: int, body: HiddenAnswer, c: Context = Depends(ctx)) -> dict[str, Any]:
    from ..review.hidden import answer

    if c.db.q1("SELECT id FROM people WHERE id=?", (person_id,)) is None:
        raise HTTPException(404, "Person not found")
    out = answer(c, person_id, body.yes, body.no)
    c.events.publish("people.changed", {})
    return out


@router.get("/api/review/name")
def name_suggestions(limit: int = 8, c: Context = Depends(ctx)) -> list[dict[str, Any]]:
    return _svc(c).name_suggestions(limit)
