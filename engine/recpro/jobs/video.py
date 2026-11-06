"""Video pass: faces, private content and scenes through the whole video, with times.

Frames are sampled at 1 a second (sparser for videos over 10 minutes) and decoded once. Faces are
tracked from frame to frame and kept as one face per person per video, with the time spans the
person is on screen. NudeNet checks every sampled frame. SigLIP 2 embeds a frame every 2 seconds
and keeps it when the picture changed, for categories (best score in the video, with spans) and
for searching moments. Runs after the photo stages, one video at a time.
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np

from ..context import Context
from ..framelabels import store_spans, video_labels
from ..labels import SENSITIVE
from ..library.metadata import ffmpeg_bin
from ..library.video import frames as video_frames
from ..library.video import sample_rate
from ..ml.tracks import FrameFace, identities

log = logging.getLogger("recpro.video")

VIDEO_V = 1
FRAME_SIDE = 1024  # one detector pass finds faces down to ~26 px
CHUNK = 16
SCENE_STEP_MS = 2000  # SigLIP looks at a frame this often...
SCENE_SAME = 0.92  # ...and keeps it only when it differs from the last one kept
CARRY_COS = 0.5  # a re-detected person keeps who they are


class VideoStage:
    name = "video"
    label = "Watching videos"
    column = "video_v"
    version = VIDEO_V
    kinds = ("video",)
    batch_size = 1
    order = "taken_at DESC"

    def __init__(self, ctx: Context):
        self.ctx = ctx
        self._prompt_cache: dict = {}

    @property
    def ml(self):
        return self.ctx.services["ml"]

    def available(self) -> bool:
        ml = self.ml
        return bool(ffmpeg_bin()) and (ml.has("faces") or ml.has("nudenet") or ml.semantic_id() is not None)  # type: ignore[attr-defined]

    def where(self) -> str:
        return "quick_v >= 1 AND width IS NOT NULL AND duration IS NOT NULL"

    def invalidate_prompts(self) -> None:
        self._prompt_cache.clear()

    def label_defs(self) -> list[Any]:
        defs = list(SENSITIVE)
        tax = self.ctx.services.get("taxonomy")
        if tax is not None:
            defs += tax.defs()  # type: ignore[attr-defined]
        return defs

    # ---- analysis ------------------------------------------------------------------------------
    def process(self, rows: list[Any]) -> None:
        for row in rows:
            try:
                self._one(row)
            except Exception as e:
                log.info("video %s not analyzed: %s", row["path"], e)
                with self.ctx.db.tx() as c:
                    c.execute("UPDATE media SET video_v=?, error=? WHERE id=?", (VIDEO_V, f"video: {str(e)[:200]}", row["id"]))

    def _one(self, row: Any) -> None:
        ml = self.ml
        fa = ml.faces()  # type: ignore[attr-defined]
        det = ml.nsfw()  # type: ignore[attr-defined]
        sig = ml.siglip()  # type: ignore[attr-defined]
        mid = int(row["id"])
        dur_ms = int(round(float(row["duration"]) * 1000))
        fps = sample_rate(row["duration"])
        step_ms = int(round(1000 / fps))
        face_frames: list[list[FrameFace]] = []
        nude_pts: list[tuple[int, float]] = []
        sug_pts: list[tuple[int, float]] = []
        scenes: list[tuple[int, np.ndarray]] = []
        pending: list[tuple[int, np.ndarray]] = []
        last_t = -SCENE_STEP_MS

        def flush(batch: list[tuple[int, np.ndarray]]) -> None:
            imgs = [im for _, im in batch]
            found = fa.analyze_many(imgs) if fa is not None else [[] for _ in imgs]
            for (t, im), faces in zip(batch, found):
                H, W = im.shape[:2]
                ff = []
                for f in faces:
                    if f.embedding is None:
                        continue
                    ff.append(FrameFace(len(face_frames), t, np.array([f.box[0] / W, f.box[1] / H, f.box[2] / W, f.box[3] / H], np.float32),
                                        (f.kps / np.array([W, H], np.float32)).astype(np.float32), f.embedding.astype(np.float32),
                                        float(f.det_score), float(f.quality), f.age, f.male))
                face_frames.append(ff)
                if det is not None:
                    boxes = [tuple(float(v) for v in f.box[:4]) for f in faces if f.det_score >= 0.5]
                    s = det.summarize(det.scores(im, boxes))
                    nude_pts.append((t, float(s["nudity"])))
                    sug_pts.append((t, float(s["suggestive"])))
            if sig is not None and pending:
                E = sig.embed_images([im for _, im in pending])
                for (t, _), e in zip(pending, E):
                    if not scenes or float(scenes[-1][1] @ e) < SCENE_SAME:
                        scenes.append((t, e.astype(np.float32)))
                pending.clear()

        batch: list[tuple[int, np.ndarray]] = []
        for t, im in video_frames(row["path"], int(row["width"]), int(row["height"]), fps, FRAME_SIDE):
            im = np.ascontiguousarray(im)
            batch.append((t, im))
            if sig is not None and t - last_t >= SCENE_STEP_MS:
                pending.append((t, im))
                last_t = t
            if len(batch) >= CHUNK:
                flush(batch)
                batch = []
        if batch:
            flush(batch)

        people = identities(face_frames, step_ms, dur_ms) if fa is not None else []
        self._store_faces(mid, people, fa is not None)
        self._store_labels(mid, sig, scenes, nude_pts, sug_pts, dur_ms, step_ms, det is not None)
        log.info("video %s: %d frames, %d people, %d scenes", row["name"], len(face_frames), len(people), len(scenes))

    # ---- storing ---------------------------------------------------------------------------------
    def _store_faces(self, mid: int, people: list, ran: bool) -> None:
        if not ran:
            return
        new_ids: list[int] = []
        removed: list[int] = []
        with self.ctx.db.tx() as c:
            old = c.execute("SELECT id, person_id, state, score, embedding FROM faces WHERE media_id=? AND frame_ms IS NOT NULL", (mid,)).fetchall()
            inserted: list[tuple[int, np.ndarray]] = []
            for p in people:
                b = p.best
                cur = c.execute(
                    """INSERT INTO faces(media_id, frame_ms, track_id, x1, y1, x2, y2, landmarks, det_score, quality, embedding, age, male, state)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?, 'none')""",
                    (mid, b.t_ms, len(inserted), *[float(v) for v in np.clip(b.box, 0, 1)], b.kps.astype(np.float32).tobytes(),
                     b.det_score, b.quality, p.embedding.astype(np.float16).tobytes(), p.age, p.male),
                )
                fid = int(cur.lastrowid)
                c.executemany("INSERT INTO face_spans(face_id, start_ms, end_ms) VALUES(?,?,?)", [(fid, s, e) for s, e in p.spans])
                inserted.append((fid, p.embedding))
            # analyzed again: the same person keeps your answers, the AI's match, votes and covers
            taken: set[int] = set()
            for o in old:
                oe = np.frombuffer(o["embedding"], np.float16).astype(np.float32)
                cands = [(float(oe @ e), fid) for fid, e in inserted if fid not in taken]
                s, fid = max(cands, default=(0.0, None))
                if fid is not None and s >= CARRY_COS:
                    taken.add(fid)
                    if o["person_id"] is not None:
                        c.execute("UPDATE faces SET person_id=?, state=?, score=? WHERE id=?", (o["person_id"], o["state"], o["score"], fid))
                    c.execute("UPDATE OR IGNORE face_votes SET face_id=? WHERE face_id=?", (fid, o["id"]))
                    c.execute("UPDATE people SET cover_face_id=? WHERE cover_face_id=?", (fid, o["id"]))
                c.execute("DELETE FROM faces WHERE id=?", (o["id"],))
                removed.append(int(o["id"]))
            c.execute("UPDATE media SET face_count=? WHERE id=?", (len(inserted), mid))
            new_ids = [fid for fid, _ in inserted]
        svc = self.ctx.services.get("people")
        if svc is not None and removed:
            svc.index.remove(removed)  # type: ignore[attr-defined]
        if svc is not None and new_ids:
            svc.on_new_faces(new_ids)  # type: ignore[attr-defined]

    def _store_labels(self, mid: int, sig, scenes, nude_pts, sug_pts, dur_ms: int, step_ms: int, nudenet: bool) -> None:
        labels = self.ctx.services["labels"]
        defs = self.label_defs() if sig is not None else list(SENSITIVE)
        extra: dict[tuple[int, str], dict[str, list[tuple[int, float]]]] = {}
        if nudenet:
            extra[(mid, "sensitive.nudity")] = {"nudenet": nude_pts}
            extra[(mid, "sensitive.suggestive")] = {"nudenet": sug_pts}
        if sig is not None and scenes:
            from ..taxonomy import score_labels

            E = np.stack([e for _, e in scenes])
            scores = score_labels(sig, E, defs, self._prompt_cache)
            owners = np.full(len(scenes), mid, np.int64)
            times = np.array([t for t, _ in scenes], np.int64)
        else:
            scores, owners, times = {}, np.zeros(0, np.int64), np.zeros(0, np.int64)
        records, spans = video_labels(labels, defs, scores, owners, times, {mid: dur_ms}, SCENE_STEP_MS if sig else step_ms, extra)
        labels.record_many(records)  # type: ignore[attr-defined]
        store_spans(self.ctx.db, labels, spans, [(mid, d.key) for d in defs])
        if sig is not None:
            with self.ctx.db.tx() as c:
                c.execute("DELETE FROM embeddings WHERE media_id=? AND model=? AND frame_ms>=0", (mid, sig.name))
                c.executemany(
                    "INSERT INTO embeddings(media_id, model, frame_ms, vec) VALUES(?,?,?,?)",
                    [(mid, sig.name, t, e.astype(np.float16).tobytes()) for t, e in scenes],
                )
            index = self.ctx.services.get("semantic_index")
            if index is not None:
                index.set_frames(mid, scenes)  # type: ignore[attr-defined]
        with self.ctx.db.tx() as c:
            c.execute("UPDATE media SET video_v=? WHERE id=?", (VIDEO_V, mid))
        labels.update_sens_state([mid])  # type: ignore[attr-defined]
