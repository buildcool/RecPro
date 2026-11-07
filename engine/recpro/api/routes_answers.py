"""Your names and answers in a file (labels_io.py), and XMP sidecars for other apps (xmp.py)."""
from __future__ import annotations

import json
import os
from datetime import date
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel

from ..context import Context
from .deps import ctx

router = APIRouter()


class ExportTo(BaseModel):
    folder: str


@router.get("/api/answers/export")
def export_doc(c: Context = Depends(ctx)) -> dict[str, Any]:
    from ..labels_io import export

    return export(c)


@router.post("/api/answers/export")
def export_file(body: ExportTo, c: Context = Depends(ctx)) -> dict[str, Any]:
    """Saves the file into a folder you picked; never over an existing file."""
    from ..labels_io import counts, export

    if not os.path.isdir(body.folder):
        raise HTTPException(400, "That folder isn't there.")
    doc = export(c)
    base = os.path.join(body.folder, f"recpro-labels-{date.today().isoformat()}")
    path, n = f"{base}.json", 1
    while os.path.exists(path):
        n += 1
        path = f"{base} ({n}).json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    return {"path": path, "counts": counts(doc)}


@router.post("/api/answers/import")
def import_doc(doc: dict[str, Any] = Body(...), c: Context = Depends(ctx)) -> dict[str, Any]:
    from ..labels_io import import_

    try:
        return import_(c, doc)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.get("/api/answers/waiting")
def waiting(c: Context = Depends(ctx)) -> dict[str, int]:
    from ..labels_io import waiting as w

    return {"waiting": w(c)}


@router.get("/api/xmp")
def xmp_status() -> dict[str, Any]:
    from ..xmp import writer

    return writer.status()


@router.post("/api/xmp")
def xmp_start(c: Context = Depends(ctx)) -> dict[str, Any]:
    from ..xmp import writer

    return writer.start(c)


@router.post("/api/xmp/stop")
def xmp_stop() -> dict[str, Any]:
    from ..xmp import writer

    writer.stop.set()
    return writer.status()
