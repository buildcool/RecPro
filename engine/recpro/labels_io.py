"""Your names and answers in a file, to take to a new PC, a reinstall, or keep as a backup.

Photos are matched by content (their size and a hash of their first and last 64 KB, the identity
RecPro already uses to follow moved files), never by path, so the file still works after your
folders move or on another drive.

In it: each person's name (birthdate, hidden), every face you said is or isn't them, the photos
you said they're in though their face isn't visible, and every category answer, with your own
categories' descriptions. Not in it: anything about private photos, or the private categories.
Those answers stay on this PC.

Importing never overrides an answer you've already given here. Answers for photos that aren't
read yet (a new install still going through your folders) wait in the library and apply as the
photos are read, and faces as they're found.
"""
from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

from .context import Context

FORMAT = "recpro-labels"
VERSION = 1
IOU_MIN = 0.6  # the same detector finds the same box; this allows for GPU/CPU rounding
FRAME_MS = 1500  # a video's face: the frame it was seen in, give or take
SHOWN = "m.state='active' AND m.quick_hash IS NOT NULL AND m.sens_state NOT IN ('private','review')"


def export(c: Context) -> dict[str, Any]:
    people = []
    for p in c.db.q("SELECT * FROM people WHERE name IS NOT NULL ORDER BY name COLLATE NOCASE"):
        faces = c.db.q(
            f"""SELECT v.vote, f.x1, f.y1, f.x2, f.y2, f.frame_ms, m.quick_hash FROM face_votes v
                JOIN faces f ON f.id=v.face_id JOIN media m ON m.id=f.media_id WHERE v.person_id=? AND {SHOWN}
                ORDER BY m.quick_hash""",
            (p["id"],),
        )
        photos = c.db.q(
            f"""SELECT mp.state, m.quick_hash FROM media_people mp JOIN media m ON m.id=mp.media_id
                WHERE mp.person_id=? AND {SHOWN} ORDER BY m.quick_hash""",
            (p["id"],),
        )
        if not faces and not photos:
            continue
        people.append({
            "name": p["name"], "birthdate": p["birthdate"], "hidden": bool(p["hidden"]),
            "faces": [{"photo": f["quick_hash"], "frame": f["frame_ms"], "box": [round(float(f[k]), 5) for k in ("x1", "y1", "x2", "y2")],
                       "answer": "yes" if f["vote"] > 0 else "no"} for f in faces],
            "photos": [{"photo": r["quick_hash"], "answer": "yes" if r["state"] == "confirmed" else "no"} for r in photos],
        })
    categories = []
    for lab in c.db.q("SELECT * FROM labels WHERE grp != 'sensitive' ORDER BY grp, name"):
        answers = c.db.q(
            f"""SELECT ml.state, m.quick_hash FROM media_labels ml JOIN media m ON m.id=ml.media_id
                WHERE ml.label_id=? AND ml.state IN ('confirmed','rejected') AND {SHOWN} ORDER BY m.quick_hash""",
            (lab["id"],),
        )
        custom = not lab["builtin"]
        if not answers and not custom:
            continue
        categories.append({
            "key": lab["key"], "name": lab["name"], "group": lab["grp"],
            "description": json.loads(lab["prompts"] or "[]") if custom else None,
            "answers": [{"photo": r["quick_hash"], "answer": "yes" if r["state"] == "confirmed" else "no"} for r in answers],
        })
    return {
        "format": FORMAT, "version": VERSION, "exported": datetime.now().isoformat(timespec="seconds"),
        "about": "RecPro names and answers. Photos are identified by content, not by path. Private photos are left out.",
        "people": people, "categories": categories,
    }


def counts(doc: dict[str, Any]) -> dict[str, int]:
    return {
        "people": len(doc.get("people", [])),
        "faces": sum(len(p.get("faces", [])) for p in doc.get("people", [])),
        "photos": sum(len(p.get("photos", [])) for p in doc.get("people", [])),
        "categories": len(doc.get("categories", [])),
        "answers": sum(len(x.get("answers", [])) for x in doc.get("categories", [])),
    }


def _iou(a: list[float], b: list[float]) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def import_(c: Context, doc: dict[str, Any]) -> dict[str, int]:
    if not isinstance(doc, dict) or doc.get("format") != FORMAT:
        raise ValueError("This isn't a RecPro labels file.")
    if int(doc.get("version", 0)) > VERSION:
        raise ValueError("This file comes from a newer RecPro. Update RecPro, then import it.")
    stats: Counter[str] = Counter()
    items: list[tuple[str, str, dict[str, Any]]] = []
    people = c.services["people"]
    for cat in doc.get("categories", []):
        key = str(cat.get("key", ""))
        if not c.db.scalar("SELECT 1 FROM labels WHERE key=?", (key,)):
            desc = cat.get("description")
            tax = c.services.get("taxonomy")
            if desc is None or tax is None or not str(cat.get("name", "")).strip():
                stats["categories_unknown"] += 1
                continue
            # one of your own categories: made again here, or the one already here with its name
            same = c.db.q1("SELECT key FROM labels WHERE builtin=0 AND lower(name)=lower(?)", (cat["name"],))
            if same is not None:
                key = same["key"]
            else:
                lid = tax.create(str(cat["name"]), [str(x) for x in desc])  # type: ignore[attr-defined]
                key = c.db.scalar("SELECT key FROM labels WHERE id=?", (lid,))
                stats["categories_added"] += 1
        items += [("label", str(a["photo"]), {"key": key, "answer": a["answer"]}) for a in cat.get("answers", [])]
    for p in doc.get("people", []):
        name = str(p.get("name") or "").strip()
        if not name:
            continue
        found = people.find_by_name(name)  # type: ignore[attr-defined]
        if found is not None:
            pid = int(found["id"])
            stats["people_matched"] += 1
        else:
            pid = people.create_person(name)  # type: ignore[attr-defined]
            stats["people_added"] += 1
        if p.get("birthdate"):
            c.db.x("UPDATE people SET birthdate=COALESCE(birthdate, ?) WHERE id=?", (p["birthdate"], pid))
        if p.get("hidden"):
            c.db.x("UPDATE people SET hidden=1 WHERE id=?", (pid,))
        items += [("face", str(f["photo"]), {"pid": pid, "name": name, "frame": f.get("frame"), "box": f["box"], "answer": f["answer"]})
                  for f in p.get("faces", [])]
        items += [("photo", str(x["photo"]), {"pid": pid, "name": name, "answer": x["answer"]}) for x in p.get("photos", [])]
    left = _apply(c, items, stats)
    _wait(c, left)
    stats["waiting"] = len(left)
    if stats["people_added"] or stats["people_matched"]:
        people.publish()  # type: ignore[attr-defined]
    c.events.publish("labels.changed", {})
    return dict(stats)


def _person(c: Context, d: dict[str, Any]) -> int | None:
    if c.db.scalar("SELECT 1 FROM people WHERE id=?", (d.get("pid"),)):
        return int(d["pid"])
    found = c.services["people"].find_by_name(d.get("name") or "")  # type: ignore[attr-defined]
    return int(found["id"]) if found is not None else None


def _apply(c: Context, items: list[tuple[str, str, dict[str, Any]]], stats: Counter[str]) -> list[tuple[str, str, dict[str, Any]]]:
    """Applies what can be applied now; returns what has to wait for photos or faces still to come."""
    from .jobs.deep import DEEP_V
    from .jobs.video import VIDEO_V

    if not items:
        return []
    by_hash: dict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
    for kind, h, d in items:
        by_hash[h].append((kind, d))
    hashes = list(by_hash)
    media: dict[str, list[Any]] = defaultdict(list)
    for i in range(0, len(hashes), 900):
        chunk = hashes[i : i + 900]
        for r in c.db.q(f"SELECT id, quick_hash, kind, deep_v, video_v FROM media WHERE state='active' AND quick_hash IN ({','.join('?' * len(chunk))})", chunk):
            media[r["quick_hash"]].append(r)
    label_ids = {r["key"]: int(r["id"]) for r in c.db.q("SELECT id, key FROM labels")}
    labels: dict[int, dict[str, set[int]]] = defaultdict(lambda: {"yes": set(), "no": set()})
    faces: dict[int, dict[str, set[int]]] = defaultdict(lambda: {"yes": set(), "no": set()})
    photos: dict[int, dict[str, set[int]]] = defaultdict(lambda: {"yes": set(), "no": set()})
    left: list[tuple[str, str, dict[str, Any]]] = []
    for h, its in by_hash.items():
        ms = media.get(h)
        if not ms:
            left += [(k, h, d) for k, d in its]
            continue
        for kind, d in its:
            side = "yes" if d.get("answer") == "yes" else "no"
            if kind == "label":
                lid = label_ids.get(d["key"])
                if lid is None:
                    stats["categories_unknown"] += 1
                    continue
                labels[lid][side].update(int(m["id"]) for m in ms)
                continue
            pid = _person(c, d)
            if pid is None:
                stats["people_gone"] += 1
                continue
            if kind == "photo":
                photos[pid][side].update(int(m["id"]) for m in ms)
                continue
            best, best_iou = None, 0.0
            for m in ms:
                cand = c.db.q("SELECT id, x1, y1, x2, y2, frame_ms FROM faces WHERE media_id=?", (m["id"],))
                for f in cand:
                    if d.get("frame") is not None and f["frame_ms"] is not None and abs(int(f["frame_ms"]) - int(d["frame"])) > FRAME_MS:
                        continue
                    iou = _iou([f["x1"], f["y1"], f["x2"], f["y2"]], d["box"])
                    if iou > best_iou:
                        best, best_iou = int(f["id"]), iou
            if best is not None and best_iou >= IOU_MIN:
                faces[pid][side].add(best)
            elif any((m["kind"] == "video" and m["video_v"] >= VIDEO_V) or (m["kind"] != "video" and m["deep_v"] >= DEEP_V) for m in ms):
                stats["faces_unmatched"] += 1  # the photo's faces have been looked for: this one isn't there
            else:
                left.append((kind, h, d))
    # never over an answer already given here
    tax = c.services.get("taxonomy")
    for lid, s in labels.items():
        mids = sorted(s["yes"] | s["no"])
        given = set()
        for i in range(0, len(mids), 900):
            chunk = mids[i : i + 900]
            given |= {int(r["media_id"]) for r in c.db.q(
                f"SELECT media_id FROM media_labels WHERE label_id=? AND state IN ('confirmed','rejected') AND media_id IN ({','.join('?' * len(chunk))})",
                [lid, *chunk])}
        yes, no = sorted(s["yes"] - given), sorted(s["no"] - s["yes"] - given)
        stats["kept_yours"] += len(given)
        if (yes or no) and tax is not None:
            tax.answer(lid, yes, no)  # type: ignore[attr-defined]
            stats["answers_applied"] += len(yes) + len(no)
    people = c.services["people"]
    for pid, s in faces.items():
        fids = sorted(s["yes"] | s["no"])
        taken = set()
        for i in range(0, len(fids), 900):
            chunk = fids[i : i + 900]
            q = ",".join("?" * len(chunk))
            taken |= {int(r["face_id"]) for r in c.db.q(f"SELECT face_id FROM face_votes WHERE person_id=? AND face_id IN ({q})", [pid, *chunk])}
            # a face you've confirmed as someone else here stays theirs
            taken |= {int(r["id"]) for r in c.db.q(f"SELECT id FROM faces WHERE state='confirmed' AND person_id IS NOT NULL AND person_id!=? AND id IN ({q})", [pid, *chunk])}
        yes, no = sorted(s["yes"] - taken), sorted(s["no"] - s["yes"] - taken)
        stats["kept_yours"] += len(taken)
        if yes or no:
            people.answer(pid, yes, no)  # type: ignore[attr-defined]
            stats["faces_applied"] += len(yes) + len(no)
    if photos:
        from .review.hidden import answer as hidden_answer

        for pid, s in photos.items():
            mids = sorted(s["yes"] | s["no"])
            given = {int(r["media_id"]) for r in c.db.q(
                f"SELECT media_id FROM media_people WHERE person_id=? AND media_id IN ({','.join('?' * len(mids))})", [pid, *mids])}
            yes, no = sorted(s["yes"] - given), sorted(s["no"] - s["yes"] - given)
            stats["kept_yours"] += len(given)
            if yes or no:
                hidden_answer(c, pid, yes, no)
                stats["photos_applied"] += len(yes) + len(no)
    return left


def _wait(c: Context, items: list[tuple[str, str, dict[str, Any]]]) -> None:
    if items:
        now = time.time()
        with c.db.tx() as cur:
            cur.executemany(
                "INSERT INTO pending_answers(kind, hash, data, created_at) VALUES(?,?,?,?)",
                [(k, h, json.dumps(d), now) for k, h, d in items],
            )


def waiting(c: Context) -> int:
    return int(c.db.scalar("SELECT COUNT(*) FROM pending_answers", default=0))


def apply_waiting(c: Context, media_ids: list[int]) -> int:
    """After photos are read or their faces found: the imported answers that were waiting for them."""
    if not media_ids or not c.db.scalar("SELECT 1 FROM pending_answers LIMIT 1"):
        return 0
    hashes: set[str] = set()
    for i in range(0, len(media_ids), 900):
        chunk = media_ids[i : i + 900]
        hashes |= {r["quick_hash"] for r in c.db.q(
            f"SELECT DISTINCT quick_hash FROM media WHERE id IN ({','.join('?' * len(chunk))}) AND quick_hash IN (SELECT hash FROM pending_answers)", chunk)}
    if not hashes:
        return 0
    rows = c.db.q(f"SELECT * FROM pending_answers WHERE hash IN ({','.join('?' * len(hashes))})", list(hashes))
    items = [(r["kind"], r["hash"], json.loads(r["data"])) for r in rows]
    stats: Counter[str] = Counter()
    left = _apply(c, items, stats)
    with c.db.tx() as cur:
        cur.executemany("DELETE FROM pending_answers WHERE id=?", [(r["id"],) for r in rows])
    _wait(c, left)
    applied = len(items) - len(left)
    if applied:
        c.events.publish("labels.changed", {})
    return applied
