from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..context import Context
from .deps import ctx

router = APIRouter()


class SecretBody(BaseModel):
    secret: str
    kind: str = "pin"


class Toggles(BaseModel):
    blur: bool | None = None
    showEverywhere: bool | None = None


class ResetBody(BaseModel):
    confirm: bool = False


class SensitiveAnswer(BaseModel):
    media_ids: list[int]
    label: str  # clear | romance | suggestive | nudity | sexual


def _p(c: Context):
    p = c.services.get("private")
    if p is None:
        raise HTTPException(503, "Private service unavailable")
    return p


@router.get("/api/private/state")
def state(c: Context = Depends(ctx)) -> dict[str, Any]:
    return _p(c).state()


@router.post("/api/private/setup")
def setup(body: SecretBody, c: Context = Depends(ctx)) -> dict[str, Any]:
    try:
        return _p(c).setup(body.secret, body.kind)
    except PermissionError as e:
        raise HTTPException(409, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/api/private/unlock")
def unlock(body: SecretBody, c: Context = Depends(ctx)) -> dict[str, Any]:
    try:
        return _p(c).unlock(body.secret)
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except TimeoutError as e:
        raise HTTPException(429, str(e))
    except LookupError as e:
        raise HTTPException(409, str(e))


@router.post("/api/private/lock")
def lock(c: Context = Depends(ctx)) -> dict[str, Any]:
    _p(c).lock()
    return _p(c).state()


@router.post("/api/private/activity")
def activity(c: Context = Depends(ctx)) -> dict[str, Any]:
    _p(c).activity()
    return {"ok": True}


@router.patch("/api/private/toggles")
def toggles(body: Toggles, c: Context = Depends(ctx)) -> dict[str, Any]:
    try:
        return _p(c).set_toggles(body.blur, body.showEverywhere)
    except PermissionError as e:
        raise HTTPException(423, str(e))


@router.post("/api/private/reset")
def reset(body: ResetBody, c: Context = Depends(ctx)) -> dict[str, Any]:
    if not body.confirm:
        raise HTTPException(400, "Confirm to reset Private.")
    _p(c).reset()
    return _p(c).state()


@router.get("/api/review/sensitive")
def sensitive_queue(limit: int = 24, c: Context = Depends(ctx)) -> dict[str, Any]:
    p = _p(c)
    labels = c.services["labels"]
    count = labels.review_counts()["sensitive"]  # type: ignore[attr-defined]
    if not p.is_unlocked():
        return {"locked": True, "items": [], "remaining": count}
    return {"locked": False, "items": labels.sensitive_review(min(limit, 96)), "remaining": count}  # type: ignore[attr-defined]


@router.post("/api/review/sensitive/answer")
def sensitive_answer(body: SensitiveAnswer, c: Context = Depends(ctx)) -> dict[str, Any]:
    if not _p(c).is_unlocked():
        raise HTTPException(423, "Unlock Private first.")
    try:
        return c.services["labels"].answer_sensitive(body.media_ids, body.label)  # type: ignore[attr-defined]
    except ValueError as e:
        raise HTTPException(400, str(e))
