from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ..context import Context
from .deps import ctx
from .visibility import private_hidden

router = APIRouter()


@router.get("/api/labels")
def list_labels(grp: str | None = None, used: int = 0, c: Context = Depends(ctx)) -> list[dict[str, Any]]:
    """Categories with how many items are sure (or confirmed) for each."""
    hide = " AND m.sens_state NOT IN ('private','review')" if private_hidden(c) else ""
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
                 WHERE ml.label_id=l.id AND m.state='active' AND ml.state != 'rejected'
                 AND (ml.tier='sure' OR ml.state='confirmed'){hide}) AS count,
              (SELECT COUNT(*) FROM media_labels ml JOIN media m ON m.id=ml.media_id
                 WHERE ml.label_id=l.id AND m.state='active' AND ml.state='ai' AND ml.tier='check'{hide}) AS review
           FROM labels l WHERE {where} ORDER BY l.grp, l.name""",
        params,
    )
    out = [dict(r) for r in rows]
    return [r for r in out if r["count"] > 0] if used else out
