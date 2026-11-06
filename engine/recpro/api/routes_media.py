from __future__ import annotations

import mimetypes
import os
from pathlib import Path
from typing import Any, Iterator

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response, StreamingResponse

from ..context import Context
from ..library.imaging import PREVIEW_MAX, open_image, save_webp, shard, video_frame
from .deps import ctx
from .visibility import check_pending, private_hidden, visible_sql

router = APIRouter()

MONTH_SQL = "strftime('%Y-%m', m.taken_at, 'unixepoch', 'localtime')"


def _filters(
    c: Context,
    folder_id: int | None = None,
    rel_dir: str | None = None,
    kind: str | None = None,
    person_id: int | None = None,
    label_id: int | None = None,
    private_only: bool = False,
    label_grp: str | None = None,
) -> tuple[str, list[Any]]:
    where = ["m.state='active'"]
    params: list[Any] = []
    if private_only:
        priv = c.services.get("private")
        if not (priv and priv.is_unlocked()):  # type: ignore[attr-defined]
            raise HTTPException(423, "Unlock Private to see these items.")
        where.append("m.sens_state IN ('private','review')")
    elif private_hidden(c):
        where.append("m.sens_state NOT IN ('private','review')")
    if folder_id is not None:
        where.append("m.folder_id=?")
        params.append(folder_id)
    if rel_dir is not None:
        where.append("(m.rel_dir=? OR m.rel_dir LIKE ?)")
        params += [rel_dir, rel_dir.rstrip("\\/") + os.sep + "%"]
    if kind in ("image", "video"):
        where.append("m.kind=?")
        params.append(kind)
    if person_id is not None:
        where.append(
            "EXISTS (SELECT 1 FROM faces f WHERE f.media_id=m.id AND f.person_id=? AND f.state IN ('confirmed','auto','cluster'))"
        )
        params.append(person_id)
    if label_id is not None:
        where.append("EXISTS (SELECT 1 FROM media_labels ml WHERE ml.media_id=m.id AND ml.label_id=? AND ml.state!='rejected' AND (ml.tier='sure' OR ml.state='confirmed'))")
        params.append(label_id)
    if label_grp:
        where.append(
            "EXISTS (SELECT 1 FROM media_labels ml JOIN labels l ON l.id=ml.label_id WHERE ml.media_id=m.id AND l.grp=?"
            " AND ml.state!='rejected' AND (ml.tier='sure' OR ml.state='confirmed'))"
        )
        params.append(label_grp)
    return " AND ".join(where), params


def item_dict(r: Any, chk_pending: bool, priv_blur: bool) -> dict[str, Any]:
    return {
        "id": r["id"],
        "kind": r["kind"],
        "w": r["width"],
        "h": r["height"],
        "t": r["taken_at"],
        "dur": r["duration"],
        "faces": r["face_count"],
        "priv": bool(priv_blur and r["sens_state"] in ("private", "review")),
        "chk": bool(chk_pending and r["sens_state"] == "unchecked"),
        "v": r["quick_v"],
        "err": bool(r["error"]) and r["quick_v"] > 0 and not r["width"],
    }


def _blur_private(c: Context) -> bool:
    priv = c.services.get("private")
    return True if priv is None else bool(priv.blur_enabled())  # type: ignore[attr-defined]


@router.get("/api/timeline")
def timeline(
    folder_id: int | None = None,
    rel_dir: str | None = None,
    kind: str | None = None,
    person_id: int | None = None,
    label_id: int | None = None,
    label_grp: str | None = None,
    private_only: bool = False,
    c: Context = Depends(ctx),
) -> dict[str, Any]:
    where, params = _filters(c, folder_id, rel_dir, kind, person_id, label_id, private_only, label_grp)
    rows = c.db.q(
        f"SELECT {MONTH_SQL} AS ym, COUNT(*) AS n FROM media m WHERE {where} GROUP BY ym ORDER BY ym DESC",
        params,
    )
    months = [{"ym": r["ym"] or "0000-00", "count": r["n"]} for r in rows]
    return {"months": months, "total": sum(m["count"] for m in months)}


@router.get("/api/media/month")
def media_month(
    ym: str,
    folder_id: int | None = None,
    rel_dir: str | None = None,
    kind: str | None = None,
    person_id: int | None = None,
    label_id: int | None = None,
    label_grp: str | None = None,
    private_only: bool = False,
    c: Context = Depends(ctx),
) -> list[dict[str, Any]]:
    where, params = _filters(c, folder_id, rel_dir, kind, person_id, label_id, private_only, label_grp)
    if ym == "0000-00":
        where += " AND m.taken_at IS NULL"
    else:
        where += f" AND {MONTH_SQL}=?"
        params.append(ym)
    rows = c.db.q(f"SELECT m.* FROM media m WHERE {where} ORDER BY m.taken_at DESC, m.id DESC", params)
    chk = check_pending(c)
    blur = _blur_private(c)
    return [item_dict(r, chk, blur) for r in rows]


@router.get("/api/media/ids")
def media_ids(
    folder_id: int | None = None,
    rel_dir: str | None = None,
    kind: str | None = None,
    person_id: int | None = None,
    label_id: int | None = None,
    label_grp: str | None = None,
    private_only: bool = False,
    c: Context = Depends(ctx),
) -> list[int]:
    """All ids of a view in timeline order (for the viewer and range selection)."""
    where, params = _filters(c, folder_id, rel_dir, kind, person_id, label_id, private_only, label_grp)
    rows = c.db.q(
        f"SELECT m.id FROM media m WHERE {where} ORDER BY {MONTH_SQL} DESC, m.taken_at DESC, m.id DESC",
        params,
    )
    return [r[0] for r in rows]


@router.post("/api/media/items")
def media_items(body: dict[str, Any], c: Context = Depends(ctx)) -> list[dict[str, Any]]:
    """Fetch grid items for an explicit list of ids (search results, selections)."""
    ids = [int(i) for i in body.get("ids", [])][:20000]
    if not ids:
        return []
    out: dict[int, dict[str, Any]] = {}
    chk = check_pending(c)
    blur = _blur_private(c)
    for i in range(0, len(ids), 900):
        chunk = ids[i : i + 900]
        for r in c.db.q(f"SELECT * FROM media m WHERE id IN ({','.join('?' * len(chunk))})", chunk):
            out[r["id"]] = item_dict(r, chk, blur)
    return [out[i] for i in ids if i in out]


@router.post("/api/media/paths")
def media_paths(body: dict[str, Any], c: Context = Depends(ctx)) -> dict[str, str]:
    """File paths for dragging files out of the app (private items only when unlocked)."""
    ids = [int(i) for i in body.get("ids", [])][:5000]
    out: dict[str, str] = {}
    hide = private_hidden(c)
    priv = c.services.get("private")
    unlocked = bool(priv and priv.is_unlocked())  # type: ignore[attr-defined]
    for i in range(0, len(ids), 900):
        chunk = ids[i : i + 900]
        for r in c.db.q(f"SELECT id, path, sens_state FROM media WHERE state='active' AND id IN ({','.join('?' * len(chunk))})", chunk):
            if r["sens_state"] in ("private", "review") and hide and not unlocked:
                continue
            out[str(r["id"])] = r["path"]
    return out


@router.get("/api/media/{media_id}")
def media_detail(media_id: int, c: Context = Depends(ctx)) -> dict[str, Any]:
    r = c.db.q1(
        "SELECT m.*, f.path AS folder_path FROM media m JOIN folders f ON f.id=m.folder_id WHERE m.id=?",
        (media_id,),
    )
    if r is None:
        raise HTTPException(404, "Not found")
    if r["sens_state"] in ("private", "review") and private_hidden(c):
        priv = c.services.get("private")
        if not (priv and priv.is_unlocked()):  # type: ignore[attr-defined]
            raise HTTPException(423, "This item is private. Unlock Private to see it.")
    faces = c.db.q(
        """SELECT f.id, f.x1, f.y1, f.x2, f.y2, f.person_id, p.name AS person_name, f.state, f.score, f.frame_ms,
                  f.age, f.male, f.emotion
           FROM faces f LEFT JOIN people p ON p.id=f.person_id WHERE f.media_id=? ORDER BY f.frame_ms, f.x1""",
        (media_id,),
    )
    labels = c.db.q(
        """SELECT ml.label_id, l.key, l.name, l.grp, ml.score, ml.tier, ml.state, ml.t_start_ms, ml.t_end_ms
           FROM media_labels ml JOIN labels l ON l.id=ml.label_id
           WHERE ml.media_id=? AND (ml.tier!='no' OR ml.state='confirmed') ORDER BY ml.score DESC""",
        (media_id,),
    )
    text = c.db.scalar("SELECT group_concat(content, ' ') FROM texts WHERE media_id=?", (media_id,))
    d = {k: r[k] for k in r.keys() if k not in ("phash", "quick_hash", "content_hash")}
    d["faces"] = [dict(f) for f in faces]
    d["labels"] = [dict(l) for l in labels]
    if r["kind"] == "video":
        from ..review.moments import face_spans, label_spans

        fs = face_spans(c.db, [f["id"] for f in faces])
        for f in d["faces"]:
            f["spans"] = [{"start_ms": s, "end_ms": e} for s, e in fs.get(f["id"], [])]
        # a private video only gets this far while Private is unlocked
        d["label_spans"] = label_spans(c.db, [media_id], [l["label_id"] for l in labels]).get(media_id, [])
    d["text"] = text
    return d


# ---------------------------------------------------------------------------
# Binary endpoints (thumbnails, previews, originals)
# ---------------------------------------------------------------------------
CACHE = {"Cache-Control": "private, max-age=604800"}


def _row(c: Context, media_id: int) -> Any:
    r = c.db.q1("SELECT * FROM media WHERE id=?", (media_id,))
    if r is None:
        raise HTTPException(404, "Not found")
    return r


def _locked_private(c: Context, r: Any) -> bool:
    if r["sens_state"] not in ("private", "review"):
        return False
    priv = c.services.get("private")
    return not (priv and priv.is_unlocked())  # type: ignore[attr-defined]


def _private_bytes(c: Context, kind: str, media_id: int) -> bytes | None:
    priv = c.services.get("private")
    if priv is None:
        return None
    return priv.read_cached(kind, media_id)  # type: ignore[attr-defined]


@router.get("/media/thumb/{media_id}")
def thumb(media_id: int, c: Context = Depends(ctx)) -> Response:
    r = _row(c, media_id)
    if r["sens_state"] in ("private", "review"):
        if _locked_private(c, r):
            return Response(LOCKED_SVG, media_type="image/svg+xml", headers={"Cache-Control": "no-store"})
        data = _private_bytes(c, "thumb", media_id)
        if data is not None:
            return Response(data, media_type="image/webp", headers={"Cache-Control": "no-store"})
    p = shard(c.paths.thumbs, media_id)
    if not p.exists():
        return Response(PENDING_SVG, media_type="image/svg+xml", headers={"Cache-Control": "no-store"})
    return FileResponse(p, media_type="image/webp", headers=CACHE)


@router.get("/media/preview/{media_id}")
def preview(media_id: int, c: Context = Depends(ctx)) -> Response:
    r = _row(c, media_id)
    if _locked_private(c, r):
        raise HTTPException(423, "Private item")
    if r["sens_state"] in ("private", "review"):
        data = _private_bytes(c, "preview", media_id)
        if data is not None:
            return Response(data, media_type="image/webp", headers={"Cache-Control": "no-store"})
    p = shard(c.paths.previews, media_id)
    if not p.exists() or p.stat().st_mtime < r["mtime"]:
        try:
            if r["kind"] == "image":
                raw, disp, _ = open_image(r["path"], want=PREVIEW_MAX)
                raw.close()
            else:
                dur = r["duration"] or 0
                disp = video_frame(r["path"], min(3.0, dur * 0.1) if dur else 0.0, max_side=PREVIEW_MAX)
        except FileNotFoundError:
            raise HTTPException(404, "The original file is missing. Its drive may be disconnected.")
        except Exception as e:
            raise HTTPException(415, f"Can't open this file: {e}")
        if r["sens_state"] in ("private", "review"):
            priv = c.services.get("private")
            if priv is not None:
                data = priv.store_cached("preview", media_id, disp)  # type: ignore[attr-defined]
                return Response(data, media_type="image/webp", headers={"Cache-Control": "no-store"})
        save_webp(disp, p, PREVIEW_MAX, quality=86)
    return FileResponse(p, media_type="image/webp", headers=CACHE)


@router.get("/media/original/{media_id}")
def original(media_id: int, request: Request, c: Context = Depends(ctx)) -> Response:
    r = _row(c, media_id)
    if _locked_private(c, r):
        raise HTTPException(423, "Private item")
    path = Path(r["path"])
    if not path.exists():
        raise HTTPException(404, "The original file is missing. Its drive may be disconnected.")
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    if path.suffix.lower() in (".mov",):
        mime = "video/mp4"  # most .mov files are H.264/HEVC in an MP4-compatible container
    return range_response(path, mime, request.headers.get("range"))


def range_response(path: Path, mime: str, range_header: str | None) -> Response:
    size = path.stat().st_size
    headers = {"Accept-Ranges": "bytes", "Cache-Control": "no-store"}
    if not range_header or not range_header.startswith("bytes="):
        return FileResponse(path, media_type=mime, headers=headers)
    try:
        spec = range_header[6:].split(",")[0].strip()
        start_s, end_s = spec.split("-")
        if start_s == "":
            length = int(end_s)
            start, end = max(0, size - length), size - 1
        else:
            start = int(start_s)
            end = int(end_s) if end_s else size - 1
        end = min(end, size - 1)
        if start > end or start >= size:
            raise ValueError
    except ValueError:
        return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})

    def body() -> Iterator[bytes]:
        with open(path, "rb") as f:
            f.seek(start)
            remaining = end - start + 1
            while remaining > 0:
                chunk = f.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    headers.update({"Content-Range": f"bytes {start}-{end}/{size}", "Content-Length": str(end - start + 1)})
    return StreamingResponse(body(), status_code=206, media_type=mime, headers=headers)


@router.get("/media/face/{face_id}")
def face_crop(face_id: int, size: int = Query(160, ge=48, le=512), c: Context = Depends(ctx)) -> Response:
    f = c.db.q1("SELECT f.*, m.sens_state, m.path, m.kind, m.duration, m.mtime FROM faces f JOIN media m ON m.id=f.media_id WHERE f.id=?", (face_id,))
    if f is None:
        raise HTTPException(404, "Not found")
    if f["sens_state"] in ("private", "review"):
        priv = c.services.get("private")
        if not (priv and priv.is_unlocked()):  # type: ignore[attr-defined]
            return Response(LOCKED_SVG, media_type="image/svg+xml", headers={"Cache-Control": "no-store"})
    cache = c.paths.faces / f"{face_id // 1000:04d}" / f"{face_id}_{size}.webp"
    if f["sens_state"] not in ("private", "review") and cache.exists():
        return FileResponse(cache, media_type="image/webp", headers=CACHE)
    from ..library.facecrop import crop_face

    try:
        img = crop_face(c, f, size)
    except FileNotFoundError:
        return Response(PENDING_SVG, media_type="image/svg+xml", headers={"Cache-Control": "no-store"})
    if f["sens_state"] in ("private", "review"):
        from ..library.imaging import webp_bytes

        return Response(webp_bytes(img, size, 82), media_type="image/webp", headers={"Cache-Control": "no-store"})
    save_webp(img, cache, size, quality=82)
    return FileResponse(cache, media_type="image/webp", headers=CACHE)


LOCKED_SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><rect width="100" height="100" fill="#6d3fd9" opacity="0.18"/>'
    b'<g fill="none" stroke="#6d3fd9" stroke-width="5" stroke-linecap="round"><rect x="33" y="46" width="34" height="26" rx="5"/>'
    b'<path d="M40 46v-7a10 10 0 0 1 20 0v7"/></g></svg>'
)
PENDING_SVG = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><rect width="100" height="100" fill="#8c8b85" opacity="0.15"/></svg>'
