"""XMP sidecar files next to your photos, so other photo apps (Lightroom, digiKam, darktable, Windows)
see the people, categories and places RecPro found.

Only when you ask (Settings → Your labels). For IMG_1234.jpg RecPro writes IMG_1234.jpg.xmp with
the people in it (the faces you confirmed and the ones it's sure of), its categories and its place,
as keywords. The photo itself is never touched. A sidecar another app made is never overwritten:
only files RecPro wrote are updated. Private photos never get one, not even while Private is open,
and the private categories and ID documents are never written.

Face areas aren't written: apps disagree on how to place them on rotated photos.
"""
from __future__ import annotations

import os
import threading
import time
from datetime import datetime
from typing import Any
from xml.sax.saxutils import escape, quoteattr

from .context import Context
from .ops.fsutil import lp

NS = "http://ns.recpro.local/1.0/"
SKIP_GROUPS = ("sensitive", "id", "quality")
BATCH = 500


def sidecar(path: str) -> str:
    return path + ".xmp"


def ours(path: str) -> bool | None:
    """True if RecPro wrote this sidecar, False if another app did, None if there's none."""
    try:
        with open(lp(path), "rb") as f:
            head = f.read(65536)
    except FileNotFoundError:
        return None
    return NS.encode() in head


def _bag(tag: str, values: list[str], kind: str = "Bag") -> str:
    if not values:
        return ""
    items = "".join(f"<rdf:li>{escape(v)}</rdf:li>" for v in values)
    return f"   <{tag}><rdf:{kind}>{items}</rdf:{kind}></{tag}>\n"


def build(people: list[str], categories: list[str], place: dict[str, Any] | None) -> str:
    where = [x for x in ((place or {}).get(k) for k in ("country", "admin1", "city", "locality")) if x]
    keywords = sorted(set(people) | set(categories) | set(where[2:]))
    lr = [f"People|{p}" for p in people] + [f"Categories|{c}" for c in categories] + (["Places|" + "|".join(where)] if where else [])
    dk = [x.replace("|", "/") for x in lr]
    attrs = [f"recpro:written={quoteattr(datetime.now().isoformat(timespec='seconds'))}"]
    if place:
        for k, v in (("photoshop:City", place.get("city")), ("photoshop:State", place.get("admin1")), ("photoshop:Country", place.get("country"))):
            if v:
                attrs.append(f"{k}={quoteattr(str(v))}")
    return (
        '<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>\n'
        '<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="RecPro">\n'
        ' <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">\n'
        '  <rdf:Description rdf:about=""\n'
        f'    xmlns:recpro="{NS}"\n'
        '    xmlns:dc="http://purl.org/dc/elements/1.1/"\n'
        '    xmlns:lr="http://ns.adobe.com/lightroom/1.0/"\n'
        '    xmlns:digiKam="http://www.digikam.org/ns/1.0/"\n'
        '    xmlns:Iptc4xmpExt="http://iptc.org/std/Iptc4xmpExt/2008-02-29/"\n'
        '    xmlns:photoshop="http://ns.adobe.com/photoshop/1.0/"\n'
        f'    {" ".join(attrs)}>\n'
        + _bag("dc:subject", keywords)
        + _bag("lr:hierarchicalSubject", lr)
        + _bag("digiKam:TagsList", dk, "Seq")
        + _bag("Iptc4xmpExt:PersonInImage", people)
        + "  </rdf:Description>\n </rdf:RDF>\n</x:xmpmeta>\n"
        '<?xpacket end="w"?>\n'
    )


def facts(c: Context, media_ids: list[int]) -> dict[int, dict[str, Any]]:
    """People, categories and place for each photo: only what's sure or confirmed."""
    q = ",".join("?" * len(media_ids))
    out: dict[int, dict[str, Any]] = {m: {"people": set(), "categories": set(), "place": None} for m in media_ids}
    for r in c.db.q(
        f"""SELECT f.media_id, p.name FROM faces f JOIN people p ON p.id=f.person_id
            WHERE f.media_id IN ({q}) AND f.state IN ('confirmed','auto') AND p.name IS NOT NULL AND p.hidden=0""",
        media_ids,
    ):
        out[int(r["media_id"])]["people"].add(r["name"])
    for r in c.db.q(
        f"""SELECT mp.media_id, p.name FROM media_people mp JOIN people p ON p.id=mp.person_id
            WHERE mp.media_id IN ({q}) AND mp.state='confirmed' AND p.name IS NOT NULL AND p.hidden=0""",
        media_ids,
    ):
        out[int(r["media_id"])]["people"].add(r["name"])
    skip = "','".join(SKIP_GROUPS)
    for r in c.db.q(
        f"""SELECT ml.media_id, l.name FROM media_labels ml JOIN labels l ON l.id=ml.label_id
            WHERE ml.media_id IN ({q}) AND l.enabled=1 AND l.grp NOT IN ('{skip}')
              AND ml.state!='rejected' AND (ml.state='confirmed' OR ml.tier='sure')""",
        media_ids,
    ):
        out[int(r["media_id"])]["categories"].add(r["name"])
    for r in c.db.q(
        f"""SELECT m.id, pc.name AS city, pc.admin1, pc.country, pl.name AS locality FROM media m
            JOIN places pc ON pc.id=m.city_id LEFT JOIN places pl ON pl.id=m.place_id WHERE m.id IN ({q})""",
        media_ids,
    ):
        out[int(r["id"])]["place"] = {
            "city": r["city"], "admin1": r["admin1"], "country": r["country"],
            "locality": r["locality"] if r["locality"] != r["city"] else None,
        }
    return out


class Writer:
    """Writes sidecars in the background; one run at a time."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.state: dict[str, Any] = {"running": False, "done": 0, "total": 0, "written": 0, "kept_theirs": 0, "nothing": 0, "failed": 0,
                                      "finished_at": None, "error": None}

    def status(self) -> dict[str, Any]:
        with self.lock:
            return dict(self.state)

    def start(self, c: Context) -> dict[str, Any]:
        with self.lock:
            if self.state["running"]:
                return dict(self.state)
            total = int(c.db.scalar("SELECT COUNT(*) FROM media WHERE state='active' AND sens_state NOT IN ('private','review')", default=0))
            self.state = {"running": True, "done": 0, "total": total, "written": 0, "kept_theirs": 0, "nothing": 0, "failed": 0,
                          "finished_at": None, "error": None}
            self.stop.clear()
        threading.Thread(target=self._run, args=(c,), name="xmp", daemon=True).start()
        return self.status()

    def _bump(self, **kw: int) -> None:
        with self.lock:
            for k, v in kw.items():
                self.state[k] += v

    def _run(self, c: Context) -> None:
        last = 0
        try:
            while not self.stop.is_set():
                rows = c.db.q(
                    """SELECT id, path FROM media WHERE state='active' AND sens_state NOT IN ('private','review') AND id > ?
                       ORDER BY id LIMIT ?""",
                    (last, BATCH),
                )
                if not rows:
                    break
                last = int(rows[-1]["id"])
                info = facts(c, [int(r["id"]) for r in rows])
                for r in rows:
                    if self.stop.is_set():
                        break
                    f = info[int(r["id"])]
                    people, cats = sorted(f["people"]), sorted(f["categories"])
                    if not people and not cats and not f["place"]:
                        self._bump(done=1, nothing=1)
                        continue
                    dst = sidecar(r["path"])
                    if ours(dst) is False:
                        self._bump(done=1, kept_theirs=1)
                        continue
                    try:
                        tmp = dst + ".recpro-tmp"
                        with open(lp(tmp), "w", encoding="utf-8", newline="\n") as fh:
                            fh.write(build(people, cats, f["place"]))
                        os.replace(lp(tmp), lp(dst))
                        self._bump(done=1, written=1)
                    except OSError:
                        self._bump(done=1, failed=1)
                c.events.publish_throttled("xmp.progress", self.status(), interval=1.0)
        except Exception as e:  # reported, not raised: this runs in the background
            with self.lock:
                self.state["error"] = str(e)
        finally:
            with self.lock:
                self.state["running"] = False
                self.state["finished_at"] = time.time()
            c.events.publish("xmp.progress", self.status())


writer = Writer()
