"""Text pass: reads the words in documents and screenshots, then finds ID documents and apps.

Only photos that look like they hold text are read (documents, ID cards, screenshots, memes by
the stored category scores, or files that look like screenshots), so a library of camera photos
costs little. ID numbers are masked before the text is stored for search.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import numpy as np

from ..context import Context
from ..ids import detect_ids, mask_ids
from ..screens import APP_ALSO, APP_KEY, detect_apps, looks_like_screenshot
from .deep import load_rgb

log = logging.getLogger("recpro.text")

TEXT_V = 1
READ_MAX_SIDE = 2400  # recognition crops come from this image; detection runs smaller
# Which photos to read, from the stored category scores. Generous for documents and ID cards so
# none is missed; stricter for screenshots and memes. Video calls don't count: news and event
# photos score on them and hold little text (on 733 face photos this cut reads from 269 to 81
# without losing any real text).
DOC_GATE = 0.10
SCREEN_GATE = 0.15
MEME_GATE = 0.30
FILE_GATE = 0.5  # named like a screenshot, or screen-sized without a camera
DOC_GROUPS = ("document", "id")
SCREEN_GROUPS = ("screenshot",)
SCREEN_SKIP = ("screenshot.video_call",)
OTHER_KEYS = ("entertainment.meme", "entertainment.good_morning")


def wants_text(cat: dict[str, float], shot: float) -> tuple[bool, bool]:
    """(read this photo?, try it rotated when little text is found?)"""
    doc = cat.get("doc", 0.0)
    read = shot >= FILE_GATE or doc >= DOC_GATE or cat.get("screen", 0.0) >= SCREEN_GATE or cat.get("other", 0.0) >= MEME_GATE
    return read, doc >= 0.3


class TextStage:
    name = "text"
    label = "Reading text"
    column = "text_v"
    version = TEXT_V
    kinds = ("image",)
    batch_size = 8
    order = "taken_at DESC"

    def __init__(self, ctx: Context):
        self.ctx = ctx
        self.pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="text")

    @property
    def ml(self):
        return self.ctx.services["ml"]

    def available(self) -> bool:
        return self.ml.has("ocr")  # type: ignore[attr-defined]

    def where(self) -> str:
        # wait for the category scores that decide what to read, when that model is installed
        # private items' words are never stored (nothing readable of them stays on disk)
        if self.ml.semantic_id() is not None:  # type: ignore[attr-defined]
            return "quick_v >= 1 AND sem_v >= 1 AND width IS NOT NULL AND sens_state NOT IN ('private','review')"
        return "quick_v >= 1 AND width IS NOT NULL AND sens_state NOT IN ('private','review')"

    # ---- which photos to read --------------------------------------------------------------
    def _category_scores(self, ids: list[int]) -> dict[int, dict[str, float]]:
        """Per photo: the best document / screenshot / meme-like category score."""
        out: dict[int, dict[str, float]] = {}
        groups = (*DOC_GROUPS, *SCREEN_GROUPS)
        rows = self.ctx.db.q(
            f"""SELECT ml.media_id, l.grp, l.key, ml.score FROM media_labels ml JOIN labels l ON l.id=ml.label_id
                WHERE ml.media_id IN ({','.join('?' * len(ids))}) AND ml.state != 'rejected'
                  AND (l.grp IN ({','.join('?' * len(groups))}) OR l.key IN ({','.join('?' * len(OTHER_KEYS))}))""",
            [*ids, *groups, *OTHER_KEYS],
        )
        for r in rows:
            if r["key"] in SCREEN_SKIP:
                continue
            kind = "doc" if r["grp"] in DOC_GROUPS else "screen" if r["grp"] in SCREEN_GROUPS else "other"
            d = out.setdefault(r["media_id"], {})
            d[kind] = max(d.get(kind, 0.0), float(r["score"] or 0))
        return out

    @staticmethod
    def screenshot_score(r: Any) -> float:
        return looks_like_screenshot(r["name"], r["ext"], r["width"], r["height"], bool(r["has_exif_camera"]))

    # ---- reading ------------------------------------------------------------------------------
    def _read(self, path: str, ocr: Any, doc_like: bool) -> str:
        img = load_rgb(path, READ_MAX_SIDE)
        if img is None:
            return ""
        text = ocr.text_of(ocr.read(img))
        if doc_like and len(text) < 20:
            # documents and ID cards photographed sideways or upside down
            for k in (1, 3, 2):
                alt = ocr.text_of(ocr.read(np.ascontiguousarray(np.rot90(img, k))))
                if len(alt) > len(text) + 10:
                    text = alt
        return text

    def process(self, rows: list[Any]) -> None:
        ocr = self.ml.ocr()  # type: ignore[attr-defined]
        if ocr is None:
            return
        labels = self.ctx.services["labels"]
        cats = self._category_scores([r["id"] for r in rows])
        shots = {r["id"]: self.screenshot_score(r) for r in rows}
        todo: list[tuple[Any, bool]] = []
        for r in rows:
            read, doc_like = wants_text(cats.get(r["id"], {}), shots[r["id"]])
            if read:
                todo.append((r, doc_like))
        texts = list(self.pool.map(lambda t: self._read(t[0]["path"], ocr, t[1]), todo)) if todo else []
        read = {r["id"]: t for (r, _), t in zip(todo, texts)}

        records: list[tuple[int, str, dict[str, float], str]] = []
        id_media: list[int] = []
        with self.ctx.db.tx() as c:
            for r in rows:
                mid = r["id"]
                shot = shots[mid]
                if shot:
                    records.append((mid, "screenshot.screenshot", {"file": shot}, "screenshot"))
                c.execute("DELETE FROM texts WHERE media_id=? AND kind='ocr'", (mid,))
                text = read.get(mid, "")
                if text:
                    c.execute("INSERT INTO texts(media_id, kind, content) VALUES(?, 'ocr', ?)", (mid, mask_ids(text)))
                    for hit in detect_ids(text):
                        records.append((mid, f"id.{hit.kind}", {"ocr": hit.score}, "id"))
                        id_media.append(mid)
                    # app names only on screenshots (a payment QR standee in a shop is a photo)
                    if shot >= 0.5 or cats.get(mid, {}).get("screen", 0.0) >= 0.3:
                        for app, s in detect_apps(text).items():
                            records.append((mid, APP_KEY[app], {"ocr": s}, "screenshot"))
                            if app in APP_ALSO:
                                records.append((mid, APP_ALSO[app], {"ocr": s}, "screenshot"))
                c.execute("UPDATE media SET text_v=? WHERE id=?", (TEXT_V, mid))
        labels.record_many(records)  # type: ignore[attr-defined]
        if id_media:
            labels.update_sens_state(sorted(set(id_media)))  # type: ignore[attr-defined]
        if todo:
            log.info("read text in %d of %d photos", len(todo), len(rows))
