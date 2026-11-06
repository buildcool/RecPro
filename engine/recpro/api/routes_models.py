from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..context import Context
from ..ml.models import MODELS
from .deps import ctx

router = APIRouter()


class DownloadRequest(BaseModel):
    ids: list[str] | None = None
    profile: str | None = None  # best | fast


def _ml(c: Context):
    ml = c.services.get("ml")
    if ml is None:
        raise HTTPException(503, "AI service unavailable")
    return ml


@router.get("/api/models")
def list_models(c: Context = Depends(ctx)) -> dict[str, Any]:
    ml = _ml(c)
    return {"models": ml.models.status(), "device": ml.device_info(), "profile": c.settings.get("models.profile")}


@router.post("/api/models/download")
def download(body: DownloadRequest, c: Context = Depends(ctx)) -> dict[str, Any]:
    ml = _ml(c)
    ids = body.ids
    if not ids:
        profile = body.profile or c.settings.get("models.profile") or "best"
        ids = [m.id for m in MODELS if profile in m.profiles]
        if body.profile:
            c.settings.update({"models.profile": profile})
    try:
        ml.models.request(ids)
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except KeyError as e:
        raise HTTPException(400, f"Unknown model {e}")
    return {"queued": ids}


@router.post("/api/models/{model_id}/cancel")
def cancel(model_id: str, c: Context = Depends(ctx)) -> dict[str, Any]:
    _ml(c).models.cancel(model_id)
    return {"ok": True}
