"""Categories ("labels") with ask-when-unsure tiers: private content now, the full taxonomy later.

Each label has one or more score sources (``nudenet``, ``siglip``). A source's value is
compared against that source's thresholds for the current sensitivity, and the label's tier is
the best tier any source reaches. Your answers (confirmed / rejected) always win.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from .context import Context
from .ids import ID_NAMES
from .screens import APP_HAS_PROMPTS, APP_KEY, APP_NAMES

log = logging.getLogger("recpro.labels")

# (check, sure) per source and sensitivity setting
THRESHOLDS: dict[str, dict[str, tuple[float, float]]] = {
    "nudenet": {"never_miss": (0.25, 0.55), "balanced": (0.35, 0.55), "fewer": (0.45, 0.50)},
    "siglip_sensitive": {"never_miss": (0.05, 0.45), "balanced": (0.10, 0.45), "fewer": (0.20, 0.40)},
    "siglip": {"never_miss": (0.05, 0.35), "balanced": (0.10, 0.35), "fewer": (0.20, 0.30)},
    # relative SigLIP score: the category against "nothing special" prompts in its group
    "siglip_rel": {"never_miss": (0.12, 0.50), "balanced": (0.20, 0.50), "fewer": (0.30, 0.45)},
    # subjective groups (moods, kinds of people, memes): only very clear cases are "sure"
    "siglip_rel_strict": {"never_miss": (0.20, 0.70), "balanced": (0.30, 0.70), "fewer": (0.40, 0.65)},
    "siglip_strict": {"never_miss": (0.08, 0.45), "balanced": (0.15, 0.45), "fewer": (0.25, 0.40)},
    # your personal classifier for a category (trained on your answers)
    "personal": {"never_miss": (0.30, 0.80), "balanced": (0.40, 0.80), "fewer": (0.50, 0.75)},
    # rules on text read from the photo: 1.0 when a number's format/checksum and the card's own
    # words agree, 0.6 when only one of them is there (see ids.py and screens.py)
    "ocr": {"never_miss": (0.50, 0.90), "balanced": (0.50, 0.90), "fewer": (0.55, 0.90)},
    # file facts: named like a screenshot (0.9), screen-sized without a camera (0.55-0.75)
    "file": {"never_miss": (0.50, 0.85), "balanced": (0.55, 0.85), "fewer": (0.65, 0.85)},
    # the object detector (D-FINE) found the thing in the photo, scaled down when it's tiny
    "det": {"never_miss": (0.30, 0.60), "balanced": (0.40, 0.60), "fewer": (0.50, 0.55)},
}

STRICT_GROUPS = ("mood", "people", "entertainment", "quality")


def source_key(src: str, grp: str) -> str:
    """Private content and subjective groups use their own thresholds.

    Private content counts only SigLIP's absolute probability and NudeNet: relative scores (a
    softmax against "ordinary photo" prompts) push ordinary photos and documents into Private, so
    a stored relative score is ignored (the key returned isn't in THRESHOLDS).
    """
    if grp == "sensitive":
        if f"{src}_sensitive" in THRESHOLDS:
            return f"{src}_sensitive"
        return src if src == "nudenet" else f"{src}_ignored"
    if grp in STRICT_GROUPS and f"{src}_strict" in THRESHOLDS:
        return f"{src}_strict"
    return src


@dataclass
class LabelDef:
    key: str
    name: str
    grp: str
    prompts: list[str] = field(default_factory=list)
    sources: tuple[str, ...] = ("siglip",)


SENSITIVE: list[LabelDef] = [
    LabelDef(
        "sensitive.romance",
        "Romance",
        "sensitive",
        [
            "a couple kissing",
            "two people kissing on the lips",
            "a romantic couple hugging closely",
            "a couple cuddling in bed",
            "a romantic intimate moment between two lovers",
        ],
    ),
    LabelDef(
        "sensitive.suggestive",
        "Suggestive",
        "sensitive",
        [
            "a person posing in lingerie",
            "a woman in a bikini",
            "a person in underwear",
            "a sexy seductive pose",
            "a shirtless man posing",
        ],
        ("siglip", "nudenet"),
    ),
    LabelDef(
        "sensitive.nudity",
        "Nudity",
        "sensitive",
        ["a nude person", "a naked body", "a photo with nudity"],
        ("siglip", "nudenet"),
    ),
    LabelDef(
        "sensitive.sexual",
        "Sexual",
        "sensitive",
        ["sexual activity", "people having sex", "an explicit sexual act", "pornography"],
    ),
]

SENSITIVE_KEYS = tuple(d.key for d in SENSITIVE)

# Categories filled from text read in the photo (no prompts: SigLIP doesn't score them)
TEXT_LABELS: list[LabelDef] = [
    *(LabelDef(f"id.{k}", name, "id", [], ("ocr",)) for k, name in ID_NAMES.items()),
    *(LabelDef(APP_KEY[a], name, "screenshot", [], ("ocr",)) for a, name in APP_NAMES.items() if a not in APP_HAS_PROMPTS),
]
ID_KEYS = tuple(f"id.{k}" for k in ID_NAMES)


class Labels:
    def __init__(self, ctx: Context):
        self.ctx = ctx
        self.db = ctx.db
        self._ids: dict[str, int] = {}
        self._lock = threading.Lock()
        self.seed(SENSITIVE + TEXT_LABELS)
        self._modes = self._current_modes()
        self._ids_private = self.ids_private()

    def _current_modes(self) -> tuple[str, str]:
        return (str(self.ctx.settings.get("sensitivity.sensitive")), str(self.ctx.settings.get("sensitivity.categories")))

    def ids_private(self) -> bool:
        return bool(self.ctx.settings.get("privacy.ids_private", False))

    def start(self) -> None:
        # thresholds may have changed between versions: re-tier stored scores once at startup
        threading.Thread(target=self.retier, name="labels-retier", daemon=True).start()

    def on_settings(self) -> None:
        modes = self._current_modes()
        if modes != self._modes:
            self._modes = modes
            threading.Thread(target=self.retier, name="labels-retier", daemon=True).start()
        ids_private = self.ids_private()
        if ids_private != self._ids_private:
            self._ids_private = ids_private
            threading.Thread(target=self.refresh_id_privacy, name="labels-ids", daemon=True).start()

    def refresh_id_privacy(self) -> int:
        """After "Treat ID documents as private" changes: hide or show every ID document."""
        ids = [self.id(k) for k in ID_KEYS]
        mids = [r[0] for r in self.db.q(f"SELECT DISTINCT media_id FROM media_labels WHERE label_id IN ({','.join('?' * len(ids))})", ids)]
        self.update_sens_state(mids)
        return len(mids)

    def seed(self, defs: list[LabelDef]) -> None:
        with self.db.tx() as c:
            for d in defs:
                c.execute(
                    """INSERT INTO labels(key, name, grp, prompts, builtin) VALUES(?,?,?,?,1)
                       ON CONFLICT(key) DO UPDATE SET name=excluded.name, grp=excluded.grp, prompts=excluded.prompts""",
                    (d.key, d.name, d.grp, json.dumps(d.prompts)),
                )
        self._ids = {r["key"]: r["id"] for r in self.db.q("SELECT id, key FROM labels")}

    def id(self, key: str) -> int:
        if key not in self._ids:
            self._ids = {r["key"]: r["id"] for r in self.db.q("SELECT id, key FROM labels")}
        return self._ids[key]

    def mode(self, grp: str) -> str:
        k = "sensitivity.sensitive" if grp == "sensitive" else "sensitivity.categories"
        return str(self.ctx.settings.get(k, "never_miss"))

    def check_threshold(self, src: str, grp: str) -> float | None:
        """The "please check" threshold of a source for a group (None: the source doesn't count)."""
        source = source_key(src, grp)
        if source not in THRESHOLDS:
            return None
        return THRESHOLDS[source].get(self.mode(grp), THRESHOLDS[source]["never_miss"])[0]

    @staticmethod
    def tier_of(source: str, value: float, mode: str) -> str:
        chk, sure = THRESHOLDS[source].get(mode, THRESHOLDS[source]["never_miss"])
        return "sure" if value >= sure else "check" if value >= chk else "no"

    def record(self, media_id: int, key: str, values: dict[str, float], grp: str) -> tuple[str, float]:
        """Stores the AI's view of one label for one item (never overriding your answer)."""
        mode = self.mode(grp)
        order = {"no": 0, "check": 1, "sure": 2}
        best, score, src_best = "no", 0.0, None
        for src, v in values.items():
            source = source_key(src, grp)
            if source not in THRESHOLDS:
                continue
            t = self.tier_of(source, v, mode)
            if order[t] > order[best] or (t == best and v > score):
                best, score, src_best = t, v, src
        lid = self.id(key)
        existing = self.db.q1("SELECT state, source FROM media_labels WHERE media_id=? AND label_id=?", (media_id, lid))
        if existing is not None and existing["source"] and existing["source"].startswith("{"):
            # keep other sources' values (e.g. NudeNet from the pre-check when SigLIP runs later)
            try:
                merged = {**json.loads(existing["source"]), **values}
            except ValueError:
                merged = values
            if merged != values:
                return self.record_merged(media_id, key, merged, grp, existing["state"])
        if best == "no" and score < 0.01:
            if existing is not None and existing["state"] == "ai":
                self.db.x("DELETE FROM media_labels WHERE media_id=? AND label_id=?", (media_id, lid))
            return best, score
        self.db.x(
            """INSERT INTO media_labels(media_id, label_id, score, tier, state, source) VALUES(?,?,?,?, 'ai', ?)
               ON CONFLICT(media_id, label_id) DO UPDATE SET score=excluded.score, tier=excluded.tier, source=excluded.source""",
            (media_id, lid, round(score, 4), best, json.dumps({k: round(v, 4) for k, v in values.items()})),
        )
        return best, score

    def record_many(self, items: list[tuple[int, str, dict[str, float], str]]) -> None:
        """Bulk version of record(): (media_id, key, values, grp). One query + one transaction."""
        if not items:
            return
        order = {"no": 0, "check": 1, "sure": 2}
        lids = {key: self.id(key) for _, key, _, _ in items}
        mids = sorted({m for m, _, _, _ in items})
        existing: dict[tuple[int, int], str] = {}
        for i in range(0, len(mids), 900):
            chunk = mids[i : i + 900]
            for r in self.db.q(
                f"SELECT media_id, label_id, source FROM media_labels WHERE media_id IN ({','.join('?' * len(chunk))})", chunk
            ):
                existing[(r["media_id"], r["label_id"])] = r["source"] or ""
        modes = {g: self.mode(g) for g in {g for _, _, _, g in items}}
        upserts, deletes = [], []
        for mid, key, values, grp in items:
            lid = lids[key]
            prev = existing.get((mid, lid))
            merged = dict(values)
            if prev and prev.startswith("{"):
                try:
                    merged = {**json.loads(prev), **values}
                except ValueError:
                    pass
            best, score = "no", 0.0
            for src, v in merged.items():
                source = source_key(src, grp)
                if source not in THRESHOLDS:
                    continue
                t = self.tier_of(source, float(v), modes[grp])
                if order[t] > order[best] or (t == best and v > score):
                    best, score = t, float(v)
            if prev is None and best == "no" and score < 0.01:
                continue
            upserts.append((mid, lid, round(score, 4), best, json.dumps({k: round(float(v), 4) for k, v in merged.items()})))
        with self.db.tx() as c:
            c.executemany(
                """INSERT INTO media_labels(media_id, label_id, score, tier, state, source) VALUES(?,?,?,?, 'ai', ?)
                   ON CONFLICT(media_id, label_id) DO UPDATE SET score=excluded.score, tier=excluded.tier, source=excluded.source""",
                upserts,
            )
            c.executemany("DELETE FROM media_labels WHERE media_id=? AND label_id=? AND state='ai'", deletes)

    def record_merged(self, media_id: int, key: str, values: dict[str, float], grp: str, state: str) -> tuple[str, float]:
        mode = self.mode(grp)
        order = {"no": 0, "check": 1, "sure": 2}
        best, score = "no", 0.0
        for src, v in values.items():
            source = source_key(src, grp)
            if source not in THRESHOLDS:
                continue
            t = self.tier_of(source, v, mode)
            if order[t] > order[best] or (t == best and v > score):
                best, score = t, v
        self.db.x(
            "UPDATE media_labels SET score=?, tier=?, source=? WHERE media_id=? AND label_id=?",
            (round(score, 4), best, json.dumps({k: round(v, 4) for k, v in values.items()}), media_id, self.id(key)),
        )
        return best, score

    def retier(self, grp: str | None = None) -> int:
        """Recompute AI tiers from stored scores (after a threshold or sensitivity change)."""
        q = "SELECT ml.media_id, ml.label_id, ml.source, l.grp FROM media_labels ml JOIN labels l ON l.id=ml.label_id WHERE ml.state='ai'"
        params: list[Any] = []
        if grp:
            q += " AND l.grp=?"
            params.append(grp)
        order = {"no": 0, "check": 1, "sure": 2}
        updates = []
        touched: set[int] = set()
        for r in self.db.q(q, params):
            try:
                values = json.loads(r["source"] or "{}")
            except ValueError:
                continue
            mode = self.mode(r["grp"])
            best, score = "no", 0.0
            for src, v in values.items():
                source = source_key(src, r["grp"])
                if source not in THRESHOLDS:
                    continue
                t = self.tier_of(source, float(v), mode)
                if order[t] > order[best] or (t == best and v > score):
                    best, score = t, float(v)
            updates.append((best, round(score, 4), r["media_id"], r["label_id"]))
            if r["grp"] == "sensitive":
                touched.add(r["media_id"])
        with self.db.tx() as c:
            c.executemany("UPDATE media_labels SET tier=?, score=? WHERE media_id=? AND label_id=?", updates)
        if touched:
            self.update_sens_state(list(touched))
        return len(updates)

    # ---- private state ----------------------------------------------------------------
    def update_sens_state(self, media_ids: list[int]) -> dict[int, str]:
        """clear / review / private from the sensitive labels (your answers win)."""
        if not media_ids:
            return {}
        sens_ids = [self.id(k) for k in SENSITIVE_KEYS]
        # with "Treat ID documents as private" on, an ID document (AI sure or confirmed by you) is
        # private too; "please check" IDs stay visible and wait in the ID category instead
        id_ids = set(self.id(k) for k in ID_KEYS) if self.ids_private() else set()
        watch = [*sens_ids, *id_ids]
        out: dict[int, str] = {}
        changed_private: list[int] = []
        changed_clear: list[int] = []
        for i in range(0, len(media_ids), 900):
            chunk = media_ids[i : i + 900]
            rows = self.db.q(
                f"""SELECT m.id, m.sens_state, ml.label_id, ml.tier, ml.state, ml.score FROM media m
                    LEFT JOIN media_labels ml ON ml.media_id=m.id AND ml.label_id IN ({','.join('?' * len(watch))})
                    WHERE m.id IN ({','.join('?' * len(chunk))})""",
                [*watch, *chunk],
            )
            per: dict[int, list[Any]] = {}
            id_doc: set[int] = set()
            prev: dict[int, str] = {}
            for r in rows:
                prev[r["id"]] = r["sens_state"]
                if r["tier"] is None:
                    continue
                if r["label_id"] in id_ids:
                    if r["state"] == "confirmed" or (r["state"] == "ai" and r["tier"] == "sure"):
                        id_doc.add(r["id"])
                else:
                    per.setdefault(r["id"], []).append(r)
            for mid in chunk:
                labs = per.get(mid, [])
                if mid in id_doc:
                    st = "private"
                elif any(l["state"] == "confirmed" for l in labs):
                    st = "private"
                elif labs and all(l["state"] == "rejected" for l in labs):
                    st = "clear"
                elif any(l["state"] == "ai" and l["tier"] == "sure" for l in labs):
                    st = "private"
                elif any(l["state"] == "ai" and l["tier"] == "check" for l in labs):
                    st = "review"
                else:
                    st = "clear"
                score = max((l["score"] for l in labs if l["state"] != "rejected"), default=0.0)
                out[mid] = st
                p = prev.get(mid)
                if p != st:
                    if st in ("private", "review") and p not in ("private", "review"):
                        changed_private.append(mid)
                    elif st == "clear" and p in ("private", "review"):
                        changed_clear.append(mid)
                self.db.x("UPDATE media SET sens_state=?, sens_score=? WHERE id=?", (st, score, mid))
        priv = self.ctx.services.get("private")
        if priv is not None:
            if changed_private:
                priv.on_became_private(changed_private)  # type: ignore[attr-defined]
            if changed_clear:
                priv.on_became_clear(changed_clear)  # type: ignore[attr-defined]
        if changed_private or changed_clear:
            self.ctx.events.publish("private.changed", {})
        return out

    # ---- review -----------------------------------------------------------------------
    def review_counts(self) -> dict[str, int]:
        n = self.db.scalar("SELECT COUNT(*) FROM media WHERE state='active' AND sens_state='review'", default=0)
        return {"sensitive": n}

    def sensitive_review(self, limit: int = 24) -> list[dict[str, Any]]:
        sens_ids = [self.id(k) for k in SENSITIVE_KEYS]
        rows = self.db.q(
            f"""SELECT m.id, m.quick_v, m.width, m.height, m.kind, MAX(ml.score) AS score,
                  (SELECT l.key FROM media_labels x JOIN labels l ON l.id=x.label_id
                     WHERE x.media_id=m.id AND x.label_id IN ({','.join('?' * len(sens_ids))}) ORDER BY x.score DESC LIMIT 1) AS top
                FROM media m JOIN media_labels ml ON ml.media_id=m.id AND ml.label_id IN ({','.join('?' * len(sens_ids))})
                WHERE m.state='active' AND m.sens_state='review' GROUP BY m.id ORDER BY score DESC LIMIT ?""",
            [*sens_ids, *sens_ids, limit],
        )
        return [dict(r) for r in rows]

    def answer_sensitive(self, media_ids: list[int], label: str) -> dict[str, int]:
        """label: 'clear' or one of romance/suggestive/nudity/sexual."""
        now = time.time()
        sens_ids = {k: self.id(k) for k in SENSITIVE_KEYS}
        with self.db.tx() as c:
            for mid in media_ids:
                if label == "clear":
                    for lid in sens_ids.values():
                        c.execute(
                            """INSERT INTO media_labels(media_id, label_id, score, tier, state, source) VALUES(?,?,0,'no','rejected','you')
                               ON CONFLICT(media_id, label_id) DO UPDATE SET state='rejected'""",
                            (mid, lid),
                        )
                else:
                    key = f"sensitive.{label}"
                    if key not in sens_ids:
                        raise ValueError("Unknown label")
                    c.execute(
                        """INSERT INTO media_labels(media_id, label_id, score, tier, state, source) VALUES(?,?,1,'sure','confirmed','you')
                           ON CONFLICT(media_id, label_id) DO UPDATE SET state='confirmed'""",
                        (mid, sens_ids[key]),
                    )
        self.update_sens_state(media_ids)
        _ = now
        people = self.ctx.services.get("people")
        if people is not None:
            people.publish()  # type: ignore[attr-defined]
        return {"answered": len(media_ids)}


def create(ctx: Context) -> Labels:
    return Labels(ctx)
