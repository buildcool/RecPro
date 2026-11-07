from __future__ import annotations

import base64
import json
import time
from typing import Any

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ..context import Context
from ..library.imaging import open_image, webp_bytes
from ..review.search import search_people
from .deps import ctx

router = APIRouter()


class PeopleSearch(BaseModel):
    people: list[int] = []
    mode: str = "any"  # any | all | alone
    exclude: list[int] = []
    ref_tokens: list[str] = []
    folder_ids: list[int] | None = None
    kinds: list[str] | None = None
    date_from: float | None = None
    date_to: float | None = None


class TextSearch(BaseModel):
    q: str
    overrides: dict[str, Any] | None = None


@router.post("/api/search")
def universal_search(body: TextSearch, c: Context = Depends(ctx)) -> dict[str, Any]:
    from ..review.query import run

    if not body.q.strip():
        raise HTTPException(400, "Type what you're looking for.")
    return run(c, body.q, body.overrides)


class SavedSearch(BaseModel):
    name: str
    q: str
    overrides: dict[str, Any] | None = None


class SavedRename(BaseModel):
    name: str


def _saved(r: Any) -> dict[str, Any]:
    return {"id": r["id"], "name": r["name"], "q": r["q"], "overrides": json.loads(r["overrides"]) if r["overrides"] else None,
            "created_at": r["created_at"]}


@router.get("/api/searches")
def saved_searches(c: Context = Depends(ctx)) -> list[dict[str, Any]]:
    """Searches you saved; they run again each time, so new photos join them."""
    return [_saved(r) for r in c.db.q("SELECT * FROM saved_searches ORDER BY name COLLATE NOCASE")]


@router.post("/api/searches")
def save_search(body: SavedSearch, c: Context = Depends(ctx)) -> dict[str, Any]:
    name, q = body.name.strip()[:80], body.q.strip()
    if not name or not q:
        raise HTTPException(400, "Give the search a name.")
    sid = c.db.x(
        "INSERT INTO saved_searches(name, q, overrides, created_at) VALUES(?,?,?,?)",
        (name, q, json.dumps(body.overrides) if body.overrides else None, time.time()),
    ).lastrowid
    return _saved(c.db.q1("SELECT * FROM saved_searches WHERE id=?", (sid,)))


@router.patch("/api/searches/{sid}")
def rename_search(sid: int, body: SavedRename, c: Context = Depends(ctx)) -> dict[str, Any]:
    name = body.name.strip()[:80]
    if not name:
        raise HTTPException(400, "Give the search a name.")
    c.db.x("UPDATE saved_searches SET name=? WHERE id=?", (name, sid))
    r = c.db.q1("SELECT * FROM saved_searches WHERE id=?", (sid,))
    if r is None:
        raise HTTPException(404, "That saved search isn't there any more.")
    return _saved(r)


@router.delete("/api/searches/{sid}")
def delete_search(sid: int, c: Context = Depends(ctx)) -> dict[str, bool]:
    c.db.x("DELETE FROM saved_searches WHERE id=?", (sid,))
    return {"ok": True}


@router.get("/api/search/parse")
def parse_query(q: str, c: Context = Depends(ctx)) -> dict[str, Any]:
    from ..review.query import parse

    return parse(c, q)


@router.post("/api/search/people")
def people_search(body: PeopleSearch, c: Context = Depends(ctx)) -> dict[str, Any]:
    if not body.people and not body.ref_tokens:
        raise HTTPException(400, "Choose at least one person or a photo of them.")
    if body.mode not in ("any", "all", "alone"):
        raise HTTPException(400, "Unknown mode")
    if c.services.get("people") is None:
        raise HTTPException(503, "People service unavailable")
    return search_people(
        c, body.people, body.mode, body.exclude, body.ref_tokens, body.folder_ids, body.kinds, body.date_from, body.date_to
    )


@router.post("/api/search/ref-faces")
async def reference_faces(request: Request, c: Context = Depends(ctx)) -> dict[str, Any]:
    """Faces found in photos you provide (file paths or uploads). Nothing leaves this PC."""
    ml = c.services.get("ml")
    people = c.services.get("people")
    fa = ml.faces() if ml else None  # type: ignore[attr-defined]
    if fa is None or people is None:
        raise HTTPException(409, "Face recognition isn't set up yet. Download the AI models in Settings.")
    images: list[tuple[str, Any]] = []
    ctype = request.headers.get("content-type", "")
    if ctype.startswith("multipart/"):
        form = await request.form()
        for _, v in form.multi_items():
            if hasattr(v, "read"):
                data = await v.read()
                images.append((getattr(v, "filename", "photo"), data))
    else:
        body = await request.json()
        for p in body.get("paths", [])[:20]:
            images.append((p, p))
    out = []
    import io

    from PIL import Image

    for name, src in images[:20]:
        try:
            if isinstance(src, (bytes, bytearray)):
                im = Image.open(io.BytesIO(src))
                from PIL import ImageOps

                disp = ImageOps.exif_transpose(im).convert("RGB")
                disp.thumbnail((2048, 2048))
            else:
                raw, disp, _ = open_image(src, want=2048)
                raw.close()
        except Exception as e:
            out.append({"source": name, "error": f"Can't open this photo: {e}", "faces": []})
            continue
        arr = np.asarray(disp, dtype=np.uint8)
        faces = fa.analyze(arr)
        found = []
        for f in sorted(faces, key=lambda f: -(f.box[2] - f.box[0])):
            if f.embedding is None:
                continue
            x1, y1, x2, y2 = (float(v) for v in f.box)
            side = max(x2 - x1, y2 - y1) * 1.6
            cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
            crop = disp.crop((int(cx - side / 2), int(cy - side / 2), int(cx + side / 2), int(cy + side / 2)))
            data = base64.b64encode(webp_bytes(crop.resize((160, 160)), 160, 85)).decode()
            token = people.add_reference(f.embedding, f.quality)  # type: ignore[attr-defined]
            found.append({"token": token, "crop": f"data:image/webp;base64,{data}", "quality": round(f.quality, 3)})
        out.append({"source": name, "faces": found, "error": None if found else "No face found in this photo."})
    return {"images": out}
