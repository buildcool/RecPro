from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..context import Context
from .deps import ctx
from .visibility import check_pending, private_hidden

router = APIRouter()

SURE = "ml.state != 'rejected' AND (ml.tier='sure' OR ml.state='confirmed')"


class LabelCreate(BaseModel):
    name: str
    prompts: list[str] = []


class LabelPatch(BaseModel):
    name: str | None = None
    prompts: list[str] | None = None


class LabelAnswer(BaseModel):
    yes: list[int] = []
    no: list[int] = []


def _hide(c: Context) -> str:
    return " AND m.sens_state NOT IN ('private','review')" if private_hidden(c) else ""


@router.get("/api/labels")
def list_labels(grp: str | None = None, used: int = 0, c: Context = Depends(ctx)) -> list[dict[str, Any]]:
    """Categories with how many items are sure (or confirmed) for each."""
    hide = _hide(c)
    where = "l.enabled=1"
    params: list[Any] = []
    if grp:
        where += " AND l.grp=?"
        params.append(grp)
    if private_hidden(c) and grp != "sensitive":
        where += " AND l.grp != 'sensitive'"
    rows = c.db.q(
        f"""SELECT l.id, l.key, l.name, l.grp, l.builtin,
              (SELECT COUNT(*) FROM media_labels ml JOIN media m ON m.id=ml.media_id
                 WHERE ml.label_id=l.id AND m.state='active' AND {SURE}{hide}) AS count,
              (SELECT COUNT(*) FROM media_labels ml JOIN media m ON m.id=ml.media_id
                 WHERE ml.label_id=l.id AND m.state='active' AND ml.state='ai' AND ml.tier='check'{hide}) AS review
           FROM labels l WHERE {where} ORDER BY l.grp, l.name""",
        params,
    )
    out = [dict(r) for r in rows]
    return [r for r in out if r["count"] > 0] if used else out


@router.get("/api/explore")
def explore(c: Context = Depends(ctx)) -> list[dict[str, Any]]:
    from ..taxonomy import GROUPS

    hide = _hide(c)
    rows = c.db.q(
        f"""SELECT l.id, l.key, l.name, l.grp, l.builtin,
              (SELECT COUNT(*) FROM media_labels ml JOIN media m ON m.id=ml.media_id
                 WHERE ml.label_id=l.id AND m.state='active' AND {SURE}{hide}) AS count,
              (SELECT ml.media_id FROM media_labels ml JOIN media m ON m.id=ml.media_id
                 WHERE ml.label_id=l.id AND m.state='active' AND {SURE}{hide} ORDER BY ml.state='confirmed' DESC, ml.score DESC LIMIT 1) AS cover,
              (SELECT m.quick_v FROM media m WHERE m.id=(SELECT ml.media_id FROM media_labels ml JOIN media m2 ON m2.id=ml.media_id
                 WHERE ml.label_id=l.id AND m2.state='active' AND {SURE.replace('ml.', 'ml.')} ORDER BY ml.score DESC LIMIT 1)) AS cover_v
           FROM labels l WHERE l.enabled=1 AND l.grp != 'sensitive' ORDER BY l.name"""
    )
    by_grp: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_grp.setdefault(r["grp"], []).append(dict(r))
    out = []
    for key, name in GROUPS:
        labels = [x for x in by_grp.get(key, []) if x["count"] > 0 or key == "custom"]
        labels.sort(key=lambda x: -x["count"])
        if labels or key == "custom":
            out.append({"key": key, "name": name, "labels": labels})
    return out


@router.get("/api/labels/{label_id}")
def label_detail(label_id: int, c: Context = Depends(ctx)) -> dict[str, Any]:
    r = c.db.q1("SELECT id, key, name, grp, prompts, builtin FROM labels WHERE id=?", (label_id,))
    if r is None:
        raise HTTPException(404, "Category not found")
    if r["grp"] == "sensitive" and private_hidden(c):
        priv = c.services.get("private")
        if not (priv and priv.is_unlocked()):  # type: ignore[attr-defined]
            raise HTTPException(423, "Unlock Private first.")
    import json

    hide = _hide(c) if r["grp"] != "sensitive" else ""
    d = dict(r)
    d["prompts"] = json.loads(r["prompts"] or "[]")
    d["count"] = c.db.scalar(
        f"SELECT COUNT(*) FROM media_labels ml JOIN media m ON m.id=ml.media_id WHERE ml.label_id=? AND m.state='active' AND {SURE}{hide}",
        (label_id,),
        default=0,
    )
    d["maybe"] = c.db.scalar(
        f"SELECT COUNT(*) FROM media_labels ml JOIN media m ON m.id=ml.media_id WHERE ml.label_id=? AND m.state='active' AND ml.state='ai' AND ml.tier='check'{hide}",
        (label_id,),
        default=0,
    )
    d["answers"] = c.db.scalar("SELECT COUNT(*) FROM media_labels WHERE label_id=? AND state IN ('confirmed','rejected')", (label_id,), default=0)
    return d


@router.get("/api/labels/{label_id}/maybe")
def label_maybe(label_id: int, limit: int = 48, c: Context = Depends(ctx)) -> list[dict[str, Any]]:
    from .routes_media import item_dict

    r = c.db.q1("SELECT grp FROM labels WHERE id=?", (label_id,))
    if r is None:
        raise HTTPException(404, "Category not found")
    hide = _hide(c) if r["grp"] != "sensitive" else ""
    priv = c.services.get("private")
    blur = True if priv is None else bool(priv.blur_enabled())  # type: ignore[attr-defined]
    chk = check_pending(c)
    rows = c.db.q(
        f"""SELECT m.*, ml.score AS lscore FROM media_labels ml JOIN media m ON m.id=ml.media_id
            WHERE ml.label_id=? AND m.state='active' AND ml.state='ai' AND ml.tier='check'{hide}
            ORDER BY ml.score DESC LIMIT ?""",
        (label_id, min(limit, 500)),
    )
    out = []
    for row in rows:
        it = item_dict(row, chk, blur)
        it["score"] = round(row["lscore"], 3)
        out.append(it)
    return out


@router.post("/api/labels/{label_id}/answer")
def label_answer(label_id: int, body: LabelAnswer, c: Context = Depends(ctx)) -> dict[str, Any]:
    tax = c.services.get("taxonomy")
    if tax is None:
        raise HTTPException(503, "Categories unavailable")
    return tax.answer(label_id, body.yes, body.no)  # type: ignore[attr-defined]


@router.post("/api/labels")
def create_label(body: LabelCreate, c: Context = Depends(ctx)) -> dict[str, Any]:
    tax = c.services.get("taxonomy")
    if tax is None:
        raise HTTPException(503, "Categories unavailable")
    if not body.name.strip():
        raise HTTPException(400, "Give the category a name.")
    if c.services["ml"].semantic_id() is None:  # type: ignore[attr-defined]
        raise HTTPException(409, "Download the AI models first (Settings → AI models).")
    return {"id": tax.create(body.name, body.prompts)}  # type: ignore[attr-defined]


@router.patch("/api/labels/{label_id}")
def update_label(label_id: int, body: LabelPatch, c: Context = Depends(ctx)) -> dict[str, Any]:
    try:
        c.services["taxonomy"].update(label_id, body.name, body.prompts)  # type: ignore[attr-defined]
    except PermissionError as e:
        raise HTTPException(403, str(e))
    return {"ok": True}


@router.delete("/api/labels/{label_id}")
def delete_label(label_id: int, c: Context = Depends(ctx)) -> dict[str, Any]:
    try:
        c.services["taxonomy"].delete(label_id)  # type: ignore[attr-defined]
    except PermissionError as e:
        raise HTTPException(403, str(e))
    return {"ok": True}
