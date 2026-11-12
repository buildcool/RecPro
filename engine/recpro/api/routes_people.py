from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..context import Context
from .deps import ctx
from .visibility import private_hidden

router = APIRouter()
MEMBER_SQL = "('confirmed','auto','cluster')"


class PersonPatch(BaseModel):
    name: str | None = None
    birthdate: str | None = None
    hidden: bool | None = None
    cover_face_id: int | None = None
    merge_if_exists: bool = False


class PersonCreate(BaseModel):
    name: str
    face_ids: list[int] | None = None
    ref_tokens: list[str] | None = None


class MergeBody(BaseModel):
    into: int


class AssignBody(BaseModel):
    person_id: int | None = None
    name: str | None = None


def _svc(c: Context):
    s = c.services.get("people")
    if s is None:
        raise HTTPException(503, "People service unavailable")
    return s


def _people_rows(c: Context, where: str, params: list[Any], limit: int) -> list[dict[str, Any]]:
    priv = " AND m.sens_state NOT IN ('private','review')" if private_hidden(c) else ""
    rows = c.db.q(
        f"""SELECT p.id, p.name, p.cover_face_id, p.hidden, p.birthdate, p.kind,
              (SELECT COUNT(DISTINCT f.media_id) FROM faces f JOIN media m ON m.id=f.media_id
                 WHERE f.person_id=p.id AND f.state IN {MEMBER_SQL} AND m.state='active'{priv}) AS count,
              (SELECT COUNT(*) FROM faces f JOIN media m ON m.id=f.media_id
                 WHERE f.person_id=p.id AND f.state='suggested' AND m.state='active') AS review,
              -- the chosen cover while it's still theirs, else their clearest face. (Two subqueries,
              -- not one ordered by p.cover_face_id: SQLite before 3.39 can't see the outer table
              -- from a subquery's ORDER BY, and the installed app can be built with one.)
              COALESCE(
                (SELECT f.id FROM faces f WHERE f.id=p.cover_face_id AND f.person_id=p.id AND f.state IN {MEMBER_SQL}),
                (SELECT f.id FROM faces f WHERE f.person_id=p.id AND f.state IN {MEMBER_SQL} ORDER BY f.quality DESC LIMIT 1)
              ) AS best_face
           FROM people p WHERE {where} ORDER BY count DESC, p.id LIMIT ?""",
        [*params, limit],
    )
    out = []
    for r in rows:
        d = dict(r)
        d["cover_face_id"] = d.pop("best_face") or d["cover_face_id"]
        d["hidden"] = bool(d["hidden"])
        out.append(d)
    return out


@router.get("/api/people")
def list_people(named: int | None = None, hidden: int = 0, limit: int = 500, min_count: int = 1, c: Context = Depends(ctx)) -> list[dict[str, Any]]:
    where = "p.kind='human' AND p.hidden=?"
    params: list[Any] = [hidden]
    if named == 1:
        where += " AND p.name IS NOT NULL"
    elif named == 0:
        where += " AND p.name IS NULL"
    rows = _people_rows(c, where, params, min(limit, 2000))
    return [r for r in rows if r["count"] >= min_count or (r["name"] and r["review"] > 0)]


@router.get("/api/people/{pid}")
def get_person(pid: int, c: Context = Depends(ctx)) -> dict[str, Any]:
    rows = _people_rows(c, "p.id=?", [pid], 1)
    if not rows:
        raise HTTPException(404, "Person not found")
    p = rows[0]
    svc = _svc(c)
    p["coverage"] = svc.coverage(pid)
    p["companions"] = [
        dict(r)
        for r in c.db.q(
            f"""SELECT o.person_id AS id, pp.name, COUNT(DISTINCT o.media_id) AS n,
                  (SELECT f2.id FROM faces f2 WHERE f2.person_id=o.person_id AND f2.state IN {MEMBER_SQL} ORDER BY f2.quality DESC LIMIT 1) AS face_id
               FROM faces f JOIN faces o ON o.media_id=f.media_id AND o.person_id != f.person_id
               JOIN people pp ON pp.id=o.person_id
               WHERE f.person_id=? AND f.state IN {MEMBER_SQL} AND o.state IN {MEMBER_SQL} AND pp.name IS NOT NULL AND pp.hidden=0
               GROUP BY o.person_id ORDER BY n DESC LIMIT 8""",
            (pid,),
        )
    ]
    return p


@router.patch("/api/people/{pid}")
def patch_person(pid: int, body: PersonPatch, c: Context = Depends(ctx)) -> Any:
    svc = _svc(c)
    if c.db.q1("SELECT id FROM people WHERE id=?", (pid,)) is None:
        raise HTTPException(404, "Person not found")
    if body.name is not None and body.name.strip():
        other = svc.find_by_name(body.name, exclude=pid)
        if other is not None:
            if not body.merge_if_exists:
                return JSONResponse(
                    {"detail": f"There's already someone called {other['name']}.", "conflict": {"id": other["id"], "name": other["name"]}},
                    status_code=409,
                )
            svc.merge(pid, other["id"])
            return {"id": other["id"], "merged": True}
        svc.rename(pid, body.name)
    elif body.name is not None:
        svc.rename(pid, None)
    sets, params = [], []
    if body.birthdate is not None:
        sets.append("birthdate=?")
        params.append(body.birthdate or None)
    if body.hidden is not None:
        sets.append("hidden=?")
        params.append(1 if body.hidden else 0)
    if body.cover_face_id is not None:
        sets.append("cover_face_id=?")
        params.append(body.cover_face_id)
    if sets:
        c.db.x(f"UPDATE people SET {', '.join(sets)} WHERE id=?", [*params, pid])
        svc.publish()
    return {"id": pid, "merged": False}


@router.post("/api/people")
def create_person(body: PersonCreate, c: Context = Depends(ctx)) -> dict[str, Any]:
    if not body.name.strip():
        raise HTTPException(400, "Enter a name.")
    pid = _svc(c).create_person(body.name, body.face_ids, body.ref_tokens)
    return {"id": pid}


@router.post("/api/people/{pid}/merge")
def merge_person(pid: int, body: MergeBody, c: Context = Depends(ctx)) -> dict[str, Any]:
    _svc(c).merge(pid, body.into)
    return {"id": body.into}


@router.get("/api/people/{pid}/faces")
def person_faces(pid: int, state: str | None = None, limit: int = 200, c: Context = Depends(ctx)) -> list[dict[str, Any]]:
    q = "SELECT f.id, f.media_id, f.state, f.score, f.quality FROM faces f JOIN media m ON m.id=f.media_id WHERE f.person_id=? AND m.state='active'"
    params: list[Any] = [pid]
    if state:
        q += " AND f.state=?"
        params.append(state)
    q += " ORDER BY f.quality DESC LIMIT ?"
    params.append(min(limit, 2000))
    return [dict(r) for r in c.db.q(q, params)]


@router.post("/api/faces/{face_id}/assign")
def assign_face(face_id: int, body: AssignBody, c: Context = Depends(ctx)) -> dict[str, Any]:
    svc = _svc(c)
    pid = body.person_id
    if pid is None:
        if not body.name or not body.name.strip():
            raise HTTPException(400, "Choose a person or enter a name.")
        existing = svc.find_by_name(body.name)
        pid = existing["id"] if existing else svc.create_person(body.name)
    old = c.db.q1("SELECT person_id, state FROM faces WHERE id=?", (face_id,))
    if old and old["person_id"] and old["person_id"] != pid and old["state"] in ("confirmed", "auto", "suggested"):
        svc.answer(old["person_id"], [], [face_id])
    return {"person_id": pid, **svc.answer(pid, [face_id], [])}


@router.post("/api/faces/{face_id}/not")
def not_person(face_id: int, body: AssignBody, c: Context = Depends(ctx)) -> dict[str, Any]:
    if body.person_id is None:
        raise HTTPException(400, "person_id is required")
    return _svc(c).answer(body.person_id, [], [face_id])
