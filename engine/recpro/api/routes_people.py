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
# A pet is a "person" of kind 'pet' whose sightings are animals instead of faces
TABLE = {"human": "faces", "pet": "animals"}


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


def _svc(c: Context, kind: str = "human"):
    s = c.services.get("pets" if kind == "pet" else "people")
    if s is None:
        raise HTTPException(503, "Pets service unavailable" if kind == "pet" else "People service unavailable")
    return s


def kind_of(c: Context, pid: int) -> str:
    k = c.db.scalar("SELECT kind FROM people WHERE id=?", (pid,))
    if k is None:
        raise HTTPException(404, "Person not found")
    return str(k)


def _people_rows(c: Context, where: str, params: list[Any], limit: int, kind: str = "human") -> list[dict[str, Any]]:
    priv = " AND m.sens_state NOT IN ('private','review')" if private_hidden(c) else ""
    t = TABLE.get(kind, "faces")
    rows = c.db.q(
        f"""SELECT p.id, p.name, p.cover_face_id, p.hidden, p.birthdate, p.kind, p.species,
              (SELECT COUNT(DISTINCT f.media_id) FROM {t} f JOIN media m ON m.id=f.media_id
                 WHERE f.person_id=p.id AND f.state IN {MEMBER_SQL} AND m.state='active'{priv}) AS count,
              (SELECT COUNT(*) FROM {t} f JOIN media m ON m.id=f.media_id
                 WHERE f.person_id=p.id AND f.state='suggested' AND m.state='active') AS review,
              -- the chosen cover while it's still theirs, else their clearest face. (Two subqueries,
              -- not one ordered by p.cover_face_id: SQLite before 3.39 can't see the outer table
              -- from a subquery's ORDER BY, and the installed app can be built with one.)
              COALESCE(
                (SELECT f.id FROM {t} f WHERE f.id=p.cover_face_id AND f.person_id=p.id AND f.state IN {MEMBER_SQL}),
                (SELECT f.id FROM {t} f WHERE f.person_id=p.id AND f.state IN {MEMBER_SQL} ORDER BY f.quality DESC LIMIT 1)
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
def list_people(
    named: int | None = None, hidden: int = 0, limit: int = 500, min_count: int = 1, kind: str = "human", c: Context = Depends(ctx)
) -> list[dict[str, Any]]:
    """People, or with kind=pet the pets."""
    if kind not in TABLE:
        raise HTTPException(400, "kind is human or pet")
    where = "p.kind=? AND p.hidden=?"
    params: list[Any] = [kind, hidden]
    if named == 1:
        where += " AND p.name IS NOT NULL"
    elif named == 0:
        where += " AND p.name IS NULL"
    rows = _people_rows(c, where, params, min(limit, 2000), kind)
    return [r for r in rows if r["count"] >= min_count or (r["name"] and r["review"] > 0)]


@router.get("/api/people/{pid}")
def get_person(pid: int, c: Context = Depends(ctx)) -> dict[str, Any]:
    kind = kind_of(c, pid)
    rows = _people_rows(c, "p.id=?", [pid], 1, kind)
    if not rows:
        raise HTTPException(404, "Person not found")
    p = rows[0]
    svc = _svc(c, kind)
    p["coverage"] = svc.coverage(pid)
    if kind == "pet":
        # the people most often in a pet's photos
        p["companions"] = [
            dict(r)
            for r in c.db.q(
                f"""SELECT f.person_id AS id, pp.name, COUNT(DISTINCT f.media_id) AS n,
                      (SELECT f2.id FROM faces f2 WHERE f2.person_id=f.person_id AND f2.state IN {MEMBER_SQL} ORDER BY f2.quality DESC LIMIT 1) AS face_id
                   FROM animals a JOIN faces f ON f.media_id=a.media_id JOIN people pp ON pp.id=f.person_id
                   WHERE a.person_id=? AND a.state IN {MEMBER_SQL} AND f.state IN {MEMBER_SQL} AND pp.name IS NOT NULL AND pp.hidden=0
                   GROUP BY f.person_id ORDER BY n DESC LIMIT 8""",
                (pid,),
            )
        ]
        return p
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
    svc = _svc(c, kind_of(c, pid))
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
    kind = kind_of(c, pid)
    if kind_of(c, body.into) != kind:
        raise HTTPException(400, "A pet and a person can't be merged.")
    _svc(c, kind).merge(pid, body.into)
    return {"id": body.into}


@router.get("/api/people/{pid}/faces")
def person_faces(pid: int, state: str | None = None, limit: int = 200, c: Context = Depends(ctx)) -> list[dict[str, Any]]:
    """A person's faces, or a pet's animals."""
    t = TABLE[kind_of(c, pid)]
    q = f"SELECT f.id, f.media_id, f.state, f.score, f.quality FROM {t} f JOIN media m ON m.id=f.media_id WHERE f.person_id=? AND m.state='active'"
    params: list[Any] = [pid]
    if state:
        q += " AND f.state=?"
        params.append(state)
    q += " ORDER BY f.quality DESC LIMIT ?"
    params.append(min(limit, 2000))
    return [dict(r) for r in c.db.q(q, params)]


def _tally(c: Context, kind: str, pid: int) -> dict[str, int]:
    """After an answer: the photos the person (or pet) is in now, and how many wait in Review."""
    t = TABLE[kind]
    return {
        "count": int(c.db.scalar(f"SELECT COUNT(DISTINCT media_id) FROM {t} WHERE person_id=? AND state IN {MEMBER_SQL}", (pid,), default=0)),
        "to_check": int(c.db.scalar(f"SELECT COUNT(*) FROM {t} WHERE person_id=? AND state='suggested'", (pid,), default=0)),
    }


@router.post("/api/faces/{face_id}/assign")
def assign_face(face_id: int, body: AssignBody, c: Context = Depends(ctx)) -> dict[str, Any]:
    """This face is that person (or a new person with this name)."""
    svc = _svc(c)
    old = c.db.q1("SELECT person_id, state FROM faces WHERE id=?", (face_id,))
    if old is None:
        raise HTTPException(404, "Not found")
    pid = body.person_id
    if pid is None:
        if not body.name or not body.name.strip():
            raise HTTPException(400, "Choose a person or enter a name.")
        existing = svc.find_by_name(body.name)
        new = existing is None
        pid = existing["id"] if existing else svc.create_person(body.name)
    elif kind_of(c, pid) != "human":
        raise HTTPException(400, "That's a pet, not a person.")
    else:
        new = False
    if old["person_id"] and old["person_id"] != pid and old["state"] in ("confirmed", "auto", "suggested"):
        svc.answer(old["person_id"], [], [face_id])
    return {"person_id": pid, **svc.answer(pid, [face_id], []), "new": new, **_tally(c, "human", pid)}


@router.post("/api/faces/{face_id}/not")
def not_person(face_id: int, body: AssignBody, c: Context = Depends(ctx)) -> dict[str, Any]:
    if body.person_id is None:
        raise HTTPException(400, "person_id is required")
    return _svc(c).answer(body.person_id, [], [face_id])


@router.post("/api/animals/{animal_id}/assign")
def assign_animal(animal_id: int, body: AssignBody, c: Context = Depends(ctx)) -> dict[str, Any]:
    """This animal is that pet (or a new pet with this name)."""
    svc = _svc(c, "pet")
    old = c.db.q1("SELECT person_id, state FROM animals WHERE id=?", (animal_id,))
    if old is None:
        raise HTTPException(404, "Not found")
    pid = body.person_id
    if pid is None:
        if not body.name or not body.name.strip():
            raise HTTPException(400, "Choose a pet or enter a name.")
        existing = svc.find_by_name(body.name)
        if existing is None:
            if old["person_id"] and old["state"] in ("confirmed", "auto", "suggested"):
                svc.answer(old["person_id"], [], [animal_id])
            pid = svc.create_person(body.name, [animal_id])  # finds its other photos as it goes
            return {"person_id": pid, "settled": 0, "remaining": 0, "new": True, **_tally(c, "pet", pid)}
        pid = existing["id"]
    elif kind_of(c, pid) != "pet":
        raise HTTPException(400, "That's a person, not a pet.")
    if old["person_id"] and old["person_id"] != pid and old["state"] in ("confirmed", "auto", "suggested"):
        svc.answer(old["person_id"], [], [animal_id])
    return {"person_id": pid, **svc.answer(pid, [animal_id], []), "new": False, **_tally(c, "pet", pid)}


@router.post("/api/animals/{animal_id}/not")
def not_pet(animal_id: int, body: AssignBody, c: Context = Depends(ctx)) -> dict[str, Any]:
    if body.person_id is None:
        raise HTTPException(400, "person_id is required")
    return _svc(c, "pet").answer(body.person_id, [], [animal_id])
