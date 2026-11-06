"""People: matching faces to people, clustering unknown faces, learning from answers.

Every face/person judgment lands in a tier:
  * Sure   (state 'auto'):      applied automatically, shown as AI until you confirm
  * Check  (state 'suggested'): goes to the Review inbox, never silently dropped
  * No     (state 'none'):      not applied
Your answers ('confirmed' state and face_votes) are never overwritten.
"""
from __future__ import annotations

import logging
import math
import threading
import time
import uuid
from typing import Any

import numpy as np

from ..context import Context
from .faceindex import FaceIndex, topk_mean_sim

log = logging.getLogger("recpro.people")

TIERS = {"never_miss": (0.50, 0.22), "balanced": (0.47, 0.28), "fewer": (0.44, 0.34)}
MEMBER = ("confirmed", "auto", "cluster")
MIN_Q_AUTO = 0.35  # low-quality faces are never decided automatically
MARGIN = 0.06  # if two people score this close, ask instead of guessing
CLUSTER_SIM = 0.48
CLUSTER_JOIN = 0.50
MERGE_AUTO = 0.62
MERGE_ASK = 0.40
MAX_EXEMPLARS = 200
MIN_CLUSTER_Q = 0.30


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


class People:
    def __init__(self, ctx: Context):
        self.ctx = ctx
        self.db = ctx.db
        self.index = FaceIndex()
        self._lock = threading.RLock()
        self._pending: set[int] = set()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._new_since_cluster = 0
        self._last_cluster = 0.0
        self._undo: list[list[tuple]] = []
        self._ref: dict[str, tuple[np.ndarray, float, float]] = {}  # token -> (embedding, quality, created)
        self._calib: tuple[float, float] | None = None  # (center, width) learned from answers
        self.ready = False

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        threading.Thread(target=self._boot, name="people", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def _boot(self) -> None:
        t0 = time.time()
        rows = self.db.q("SELECT id, media_id, quality, embedding FROM faces")
        self.index.load_rows(rows)
        self._fit_calibration()
        self.ready = True
        log.info("face index ready: %d faces in %.1fs", len(self.index), time.time() - t0)
        # faces that were never matched (e.g. engine stopped mid-way)
        pend = [r["id"] for r in self.db.q("SELECT id FROM faces WHERE state='none' AND person_id IS NULL")]
        if pend:
            with self._lock:
                self._pending.update(pend)
            self._wake.set()
        self._loop()

    def on_new_faces(self, face_ids: list[int]) -> None:
        rows = []
        for i in range(0, len(face_ids), 900):
            chunk = face_ids[i : i + 900]
            rows += self.db.q(f"SELECT id, media_id, quality, embedding FROM faces WHERE id IN ({','.join('?' * len(chunk))})", chunk)
        self.index.load_rows(rows)
        with self._lock:
            self._pending.update(face_ids)
            self._new_since_cluster += len(face_ids)
        self._wake.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._wake.wait(3.0)
            self._wake.clear()
            if self._stop.is_set():
                return
            try:
                changed = self.assign_pending()
                busy = bool(
                    self.db.scalar(
                        "SELECT EXISTS(SELECT 1 FROM media WHERE state='active' AND kind='image' AND quick_v>=1 AND width IS NOT NULL AND deep_v<1)",
                        default=0,
                    )
                )
                due = self._new_since_cluster > 0 and (
                    not busy or self._new_since_cluster >= 400 or time.time() - self._last_cluster > 90
                )
                if due:
                    changed = self.cluster() or changed
                if changed:
                    self.publish()
            except Exception:
                log.exception("people loop")

    def publish(self) -> None:
        self.ctx.events.publish("people.changed", {})
        self.ctx.events.publish("review.counts", self.review_counts())

    # ------------------------------------------------------------------ thresholds & calibration
    def thresholds(self) -> tuple[float, float]:
        mode = str(self.ctx.settings.get("sensitivity.faces", "never_miss"))
        sure, check = TIERS.get(mode, TIERS["never_miss"])
        if self._calib:
            c, w = self._calib
            # score where the learned probability is 96% (sure) and 3% (check)
            sure_l = c + w * math.log(0.96 / 0.04)
            check_l = c + w * math.log(0.03 / 0.97)
            sure = float(np.clip((sure + sure_l) / 2, 0.40, 0.62))
            check = float(np.clip(min(check, check_l) if mode == "never_miss" else (check + check_l) / 2, 0.15, sure - 0.06))
        return sure, check

    def probability(self, score: float) -> float:
        c, w = self._calib or (0.36, 0.045)
        return _sigmoid((score - c) / w)

    def _fit_calibration(self) -> None:
        """1-D logistic fit of your yes/no answers against the match score."""
        votes = self.db.q("SELECT face_id, person_id, vote FROM face_votes")
        if len(votes) < 15:
            self._calib = None
            return
        by_person: dict[int, list[tuple[int, int]]] = {}
        for v in votes:
            by_person.setdefault(v["person_id"], []).append((v["face_id"], v["vote"]))
        xs, ys = [], []
        for pid, lst in by_person.items():
            E = self.exemplars(pid, exclude={f for f, _ in lst})
            if len(E) == 0:
                continue
            F = self.index.vectors([f for f, _ in lst])
            s = topk_mean_sim(F, E)
            for (fid, vote), sc in zip(lst, s):
                xs.append(float(sc))
                ys.append(1 if vote > 0 else 0)
        if sum(ys) < 8 or len(ys) - sum(ys) < 5:
            self._calib = None
            return
        from sklearn.linear_model import LogisticRegression

        lr = LogisticRegression(C=10.0).fit(np.array(xs).reshape(-1, 1), np.array(ys))
        a, b = float(lr.coef_[0][0]), float(lr.intercept_[0])
        if a <= 1.0:
            self._calib = None
            return
        self._calib = (-b / a, 1.0 / a)

    # ------------------------------------------------------------------ exemplars
    def exemplars(self, pid: int, exclude: set[int] | None = None) -> np.ndarray:
        rows = self.db.q(
            f"""SELECT id FROM faces WHERE person_id=? AND state IN ({','.join('?' * len(MEMBER))})
                ORDER BY (state='confirmed') DESC, quality DESC LIMIT ?""",
            (pid, *MEMBER, MAX_EXEMPLARS),
        )
        ids = [r["id"] for r in rows if not exclude or r["id"] not in exclude]
        E = self.index.vectors(ids) if ids else np.zeros((0, 512), np.float32)
        refs = self.db.q("SELECT embedding FROM ref_faces WHERE person_id=?", (pid,))
        if refs:
            R = np.stack([np.frombuffer(r["embedding"], dtype=np.float16).astype(np.float32) for r in refs])
            E = np.concatenate([E, R]) if len(E) else R
        if len(E):
            E = E[np.linalg.norm(E, axis=1) > 0.5]
        return E

    def centroid(self, pid: int) -> np.ndarray | None:
        E = self.exemplars(pid)
        if len(E) == 0:
            return None
        c = E.mean(axis=0)
        return c / (np.linalg.norm(c) + 1e-9)

    def _named(self) -> list[Any]:
        return self.db.q("SELECT id, name FROM people WHERE name IS NOT NULL AND hidden=0 AND kind='human'")

    def _no_votes(self, face_ids) -> dict[int, set[int]]:
        out: dict[int, set[int]] = {}
        ids = list(face_ids)
        for i in range(0, len(ids), 900):
            chunk = ids[i : i + 900]
            for r in self.db.q(f"SELECT face_id, person_id FROM face_votes WHERE vote<0 AND face_id IN ({','.join('?' * len(chunk))})", chunk):
                out.setdefault(r["face_id"], set()).add(r["person_id"])
        return out

    # ------------------------------------------------------------------ matching new faces
    def assign_pending(self) -> bool:
        with self._lock:
            ids = list(self._pending)
            self._pending.clear()
        if not ids:
            return False
        with self._lock:
            rows = []
            for i in range(0, len(ids), 900):
                chunk = ids[i : i + 900]
                rows += self.db.q(
                    f"SELECT id, media_id, quality FROM faces WHERE state='none' AND person_id IS NULL AND id IN ({','.join('?' * len(chunk))})",
                    chunk,
                )
            if not rows:
                return False
            fids = [r["id"] for r in rows]
            F = self.index.vectors(fids)
            named = self._named()
            sure, check = self.thresholds()
            nov = self._no_votes(fids)
            scores = np.full((len(fids), len(named)), -1.0, np.float32)
            for j, p in enumerate(named):
                E = self.exemplars(p["id"])
                if len(E):
                    scores[:, j] = topk_mean_sim(F, E)
            for i, fid in enumerate(fids):
                for j, p in enumerate(named):
                    if p["id"] in nov.get(fid, ()):
                        scores[i, j] = -1.0
            updates: list[tuple] = []
            used: dict[int, set[int]] = {}  # media -> persons already given (one face per person per photo)
            for mid, pid in self.db.q(
                f"""SELECT media_id, person_id FROM faces WHERE person_id IS NOT NULL AND state IN ('confirmed','auto','suggested')
                    AND media_id IN ({','.join('?' * len({r['media_id'] for r in rows}))})""",
                list({r["media_id"] for r in rows}),
            ):
                used.setdefault(mid, set()).add(pid)
            order = np.argsort(-scores.max(axis=1)) if len(named) else np.arange(len(fids))
            unmatched: list[int] = []
            for i in order:
                r = rows[i]
                if not len(named):
                    unmatched.append(r["id"])
                    continue
                ranked = np.argsort(-scores[i])
                choice = None
                for j in ranked:
                    if scores[i, j] < check:
                        break
                    if named[j]["id"] in used.get(r["media_id"], set()):
                        continue
                    choice = j
                    break
                if choice is None:
                    unmatched.append(r["id"])
                    continue
                s = float(scores[i, choice])
                second = float(np.partition(scores[i], -2)[-2]) if len(named) > 1 else -1.0
                state = "auto" if (s >= sure and r["quality"] >= MIN_Q_AUTO and s - second >= MARGIN) else "suggested"
                used.setdefault(r["media_id"], set()).add(named[choice]["id"])
                updates.append((named[choice]["id"], state, s, r["id"]))
            # Faces that match no named person may belong to an unnamed group
            joins = self._join_unnamed(unmatched)
            with self.db.tx() as c:
                c.executemany("UPDATE faces SET person_id=?, state=?, score=? WHERE id=? AND state='none'", updates)
                c.executemany("UPDATE faces SET person_id=?, state='cluster', score=? WHERE id=? AND state='none'", joins)
            return bool(updates or joins)

    def _join_unnamed(self, face_ids: list[int]) -> list[tuple]:
        if not face_ids:
            return []
        unnamed = self.db.q("SELECT id FROM people WHERE name IS NULL AND hidden=0 AND kind='human'")
        if not unnamed:
            return []
        cents, pids = [], []
        for p in unnamed:
            c = self.centroid(p["id"])
            if c is not None:
                cents.append(c)
                pids.append(p["id"])
        if not cents:
            return []
        F = self.index.vectors(face_ids)
        S = F @ np.stack(cents).T
        media_of = {
            r["id"]: r["media_id"]
            for r in self.db.q(f"SELECT id, media_id FROM faces WHERE id IN ({','.join('?' * len(face_ids))})", face_ids)
        }
        taken = {
            (r["media_id"], r["person_id"])
            for r in self.db.q(
                f"SELECT media_id, person_id FROM faces WHERE person_id IN ({','.join('?' * len(pids))}) AND media_id IN ({','.join('?' * len(set(media_of.values())))})",
                [*pids, *set(media_of.values())],
            )
        }
        out = []
        for i in np.argsort(-S.max(axis=1)):
            fid = face_ids[i]
            j = int(np.argmax(S[i]))
            key = (media_of.get(fid), pids[j])
            if S[i, j] >= CLUSTER_JOIN and key not in taken:
                out.append((pids[j], float(S[i, j]), fid))
                taken.add(key)
        return out

    # ------------------------------------------------------------------ clustering unknown faces
    def cluster(self) -> bool:
        with self._lock:
            self._new_since_cluster = 0
            self._last_cluster = time.time()
            rows = self.db.q(
                "SELECT id, media_id, quality FROM faces WHERE person_id IS NULL AND state='none' AND quality >= ?",
                (MIN_CLUSTER_Q,),
            )
            if len(rows) < 3:
                return self._auto_merge_unnamed()
            ids = np.array([r["id"] for r in rows], np.int64)
            media = np.array([r["media_id"] for r in rows], np.int64)
            F = self.index.vectors(ids)
            n = len(ids)
            k = min(8, n - 1)
            nbrs: list[set[int]] = [set() for _ in range(n)]
            sims: dict[tuple[int, int], float] = {}
            chunk = 512
            for s in range(0, n, chunk):
                S = F[s : s + chunk] @ F.T
                for i in range(S.shape[0]):
                    S[i, s + i] = -1.0
                    # never link two faces from the same photo
                    S[i, media == media[s + i]] = -1.0
                part = np.argpartition(-S, k - 1, axis=1)[:, :k] if k > 0 else np.zeros((S.shape[0], 0), int)
                for i in range(S.shape[0]):
                    for j in part[i]:
                        v = float(S[i, j])
                        if v >= CLUSTER_SIM:
                            nbrs[s + i].add(int(j))
                            sims[(s + i, int(j))] = v
            parent = list(range(n))

            def find(x: int) -> int:
                while parent[x] != x:
                    parent[x] = parent[parent[x]]
                    x = parent[x]
                return x

            for i in range(n):
                for j in nbrs[i]:
                    if i in nbrs[j]:  # mutual nearest neighbours only: avoids chaining two people
                        a, b = find(i), find(j)
                        if a != b:
                            parent[a] = b
            comps: dict[int, list[int]] = {}
            for i in range(n):
                comps.setdefault(find(i), []).append(i)
            now = time.time()
            created = 0
            with self.db.tx() as c:
                for members in comps.values():
                    if len(members) < 3:
                        continue
                    # One face per photo per person: a chain through other photos can link two
                    # faces of the same photo; keep the one closest to the group's centre.
                    cent0 = F[members].mean(axis=0)
                    by_media: dict[int, int] = {}
                    for i in members:
                        j = by_media.get(int(media[i]))
                        if j is None or float(F[i] @ cent0) > float(F[j] @ cent0):
                            by_media[int(media[i])] = i
                    members = list(by_media.values())
                    if len(members) < 3:
                        continue
                    cover = max(members, key=lambda i: rows[i]["quality"])
                    cur = c.execute(
                        "INSERT INTO people(name, kind, cover_face_id, created_at, updated_at) VALUES(NULL, 'human', ?, ?, ?)",
                        (int(ids[cover]), now, now),
                    )
                    pid = cur.lastrowid
                    cent = F[members].mean(axis=0)
                    cent /= np.linalg.norm(cent) + 1e-9
                    c.executemany(
                        "UPDATE faces SET person_id=?, state='cluster', score=? WHERE id=? AND state='none'",
                        [(pid, float(F[i] @ cent), int(ids[i])) for i in members],
                    )
                    created += 1
            if created:
                log.info("clustering: %d new groups from %d unknown faces", created, n)
            merged = self._auto_merge_unnamed()
            return bool(created or merged)

    def _auto_merge_unnamed(self) -> bool:
        unnamed = [r["id"] for r in self.db.q("SELECT id FROM people WHERE name IS NULL AND hidden=0 AND kind='human'")]
        if len(unnamed) < 2:
            return False
        cents = {pid: self.centroid(pid) for pid in unnamed}
        cents = {k: v for k, v in cents.items() if v is not None}
        keys = list(cents)
        if len(keys) < 2:
            return False
        C = np.stack([cents[k] for k in keys])
        S = C @ C.T
        np.fill_diagonal(S, -1)
        merged = False
        gone: set[int] = set()
        for i, j in zip(*np.where(S >= MERGE_AUTO)):
            a, b = keys[i], keys[j]
            if a in gone or b in gone or a >= b:
                continue
            self.merge(b, a, publish=False)
            gone.add(b)
            merged = True
        return merged

    # ------------------------------------------------------------------ rescoring after answers
    def rescore_person(self, pid: int) -> int:
        """Re-evaluates faces against a person whose examples changed. Returns how many settled."""
        E = self.exemplars(pid)
        if len(E) == 0:
            return 0
        sure, check = self.thresholds()
        ids, scores = self.index.score_all(E)
        if len(ids) == 0:
            return 0
        cand = np.where(scores >= check - 0.03)[0]
        cand_ids = [int(ids[i]) for i in cand]
        info = {}
        for i in range(0, len(cand_ids), 900):
            chunk = cand_ids[i : i + 900]
            for r in self.db.q(f"SELECT id, person_id, state, media_id, quality FROM faces WHERE id IN ({','.join('?' * len(chunk))})", chunk):
                info[r["id"]] = r
        # faces currently pointing at this person but no longer close enough
        for r in self.db.q("SELECT id, person_id, state, media_id, quality FROM faces WHERE person_id=? AND state IN ('suggested','auto')", (pid,)):
            info.setdefault(r["id"], r)
        nov = self._no_votes(info.keys())
        score_of = {int(ids[i]): float(scores[i]) for i in cand}
        claimed: dict[int, set[int]] = {}
        for r in self.db.q("SELECT media_id, id FROM faces WHERE person_id=? AND state IN ('confirmed','auto')", (pid,)):
            claimed.setdefault(r["media_id"], set()).add(r["id"])
        settled = 0
        updates = []
        for fid, r in info.items():
            if r["state"] == "confirmed" or pid in nov.get(fid, ()):
                continue
            if r["person_id"] not in (None, pid) and r["state"] != "cluster":
                continue  # belongs to someone else
            s = score_of.get(fid)
            if s is None:
                fp = self.index.vectors([fid])
                s = float(topk_mean_sim(fp, E)[0])
            other_in_photo = claimed.get(r["media_id"], set()) - {fid}
            if s >= sure and r["quality"] >= MIN_Q_AUTO and not other_in_photo:
                new = "auto"
            elif s >= check and not other_in_photo:
                new = "suggested"
            else:
                new = None
            if new is None:
                if r["person_id"] == pid and r["state"] in ("suggested", "auto"):
                    updates.append((None, "none", None, fid))
                    settled += 1 if r["state"] == "suggested" else 0
                continue
            if r["person_id"] == pid and r["state"] == new:
                continue
            if r["person_id"] == pid and r["state"] == "suggested" and new == "auto":
                settled += 1
            if r["state"] == "cluster" and new == "suggested":
                continue  # don't pull faces out of an unnamed group just to ask
            updates.append((pid, new, s, fid))
            if new == "auto":
                claimed.setdefault(r["media_id"], set()).add(fid)
        with self.db.tx() as c:
            c.executemany("UPDATE faces SET person_id=?, state=?, score=? WHERE id=? AND state!='confirmed'", updates)
        freed = [u[3] for u in updates if u[0] is None]
        if freed:
            with self._lock:
                self._pending.update(freed)
            self._wake.set()
        return settled

    # ------------------------------------------------------------------ answers
    def answer(self, pid: int, yes: list[int], no: list[int]) -> dict[str, Any]:
        now = time.time()
        with self._lock:
            touched = list(set(yes) | set(no))
            before = []
            for i in range(0, len(touched), 900):
                chunk = touched[i : i + 900]
                before += [
                    (r["id"], r["person_id"], r["state"], r["score"])
                    for r in self.db.q(f"SELECT id, person_id, state, score FROM faces WHERE id IN ({','.join('?' * len(chunk))})", chunk)
                ]
            self._undo.append([("faces", before), ("votes", pid, touched)])
            self._undo = self._undo[-30:]
            with self.db.tx() as c:
                for fid in yes:
                    c.execute("UPDATE faces SET person_id=?, state='confirmed', score=1 WHERE id=?", (pid, fid))
                    c.execute("INSERT OR REPLACE INTO face_votes(face_id, person_id, vote, at) VALUES(?,?,1,?)", (fid, pid, now))
                for fid in no:
                    c.execute("INSERT OR REPLACE INTO face_votes(face_id, person_id, vote, at) VALUES(?,?,-1,?)", (fid, pid, now))
                    c.execute("UPDATE faces SET person_id=NULL, state='none', score=NULL WHERE id=? AND person_id=?", (fid, pid))
                c.execute("UPDATE people SET updated_at=? WHERE id=?", (now, pid))
                if yes:
                    c.execute("UPDATE people SET cover_face_id=COALESCE(cover_face_id, ?) WHERE id=?", (yes[0], pid))
            self._pending.update(no)
            self._wake.set()
            if len(self._undo) % 5 == 0:
                self._fit_calibration()
            settled = self.rescore_person(pid)
        self.publish()
        remaining = self.db.scalar("SELECT COUNT(*) FROM faces WHERE person_id=? AND state='suggested'", (pid,), default=0)
        return {"settled": settled, "remaining": remaining}

    def undo_last(self) -> bool:
        with self._lock:
            if not self._undo:
                return False
            entry = self._undo.pop()
            faces = entry[0][1]
            _, pid, touched = entry[1]
            with self.db.tx() as c:
                for fid, person_id, state, score in faces:
                    c.execute("UPDATE faces SET person_id=?, state=?, score=? WHERE id=?", (person_id, state, score, fid))
                for fid in touched:
                    c.execute("DELETE FROM face_votes WHERE face_id=? AND person_id=?", (fid, pid))
            self.rescore_person(pid)
        self.publish()
        return True

    # ------------------------------------------------------------------ people management
    def rename(self, pid: int, name: str | None) -> None:
        name = (name or "").strip() or None
        now = time.time()
        with self._lock:
            with self.db.tx() as c:
                c.execute("UPDATE people SET name=?, updated_at=? WHERE id=?", (name, now, pid))
                # Naming a group turns its grouped faces into sure matches for that person
                if name:
                    c.execute("UPDATE faces SET state='auto' WHERE person_id=? AND state='cluster'", (pid,))
            if name:
                self.rescore_person(pid)
        self.publish()

    def find_by_name(self, name: str, exclude: int | None = None) -> Any:
        return self.db.q1(
            "SELECT id, name FROM people WHERE lower(name)=lower(?) AND id != ? AND kind='human'",
            (name.strip(), exclude or -1),
        )

    def merge(self, src: int, dst: int, publish: bool = True) -> None:
        """Moves everything from person `src` into `dst` and deletes `src`."""
        if src == dst:
            return
        with self._lock:
            dst_named = self.db.scalar("SELECT name FROM people WHERE id=?", (dst,))
            with self.db.tx() as c:
                c.execute(
                    "UPDATE faces SET person_id=?, state=CASE WHEN state='cluster' AND ? IS NOT NULL THEN 'auto' ELSE state END WHERE person_id=?",
                    (dst, dst_named, src),
                )
                c.execute("UPDATE OR IGNORE face_votes SET person_id=? WHERE person_id=?", (dst, src))
                c.execute("DELETE FROM face_votes WHERE person_id=?", (src,))
                c.execute("UPDATE ref_faces SET person_id=? WHERE person_id=?", (dst, src))
                c.execute("DELETE FROM person_pairs WHERE a=? OR b=?", (src, src))
                c.execute("DELETE FROM people WHERE id=?", (src,))
                # Two AI-assigned faces of the same photo can't both be this person: keep the best
                dupes = c.execute(
                    """SELECT media_id FROM faces WHERE person_id=? AND state IN ('auto','cluster','suggested')
                       GROUP BY media_id HAVING COUNT(*) > 1""",
                    (dst,),
                ).fetchall()
                freed = []
                for d in dupes:
                    fs = c.execute(
                        "SELECT id FROM faces WHERE person_id=? AND media_id=? AND state IN ('auto','cluster','suggested') ORDER BY score DESC",
                        (dst, d["media_id"]),
                    ).fetchall()
                    for f in fs[1:]:
                        c.execute("UPDATE faces SET person_id=NULL, state='none', score=NULL WHERE id=?", (f["id"],))
                        freed.append(f["id"])
            if freed:
                self._pending.update(freed)
                self._wake.set()
            if dst_named:
                self.rescore_person(dst)
        if publish:
            self.publish()

    def create_person(self, name: str, face_ids: list[int] | None = None, ref_tokens: list[str] | None = None) -> int:
        now = time.time()
        with self._lock:
            existing = self.find_by_name(name)
            if existing:
                pid = existing["id"]
            else:
                pid = self.db.x(
                    "INSERT INTO people(name, kind, created_at, updated_at) VALUES(?, 'human', ?, ?)", (name.strip(), now, now)
                ).lastrowid
            if face_ids:
                self.answer(pid, face_ids, [])
            for t in ref_tokens or []:
                ref = self._ref.get(t)
                if ref is not None:
                    self.db.x(
                        "INSERT INTO ref_faces(person_id, embedding, quality, created_at) VALUES(?,?,?,?)",
                        (pid, ref[0].astype(np.float16).tobytes(), ref[1], now),
                    )
            self.rescore_person(pid)
        self.publish()
        return pid

    def set_not_same(self, a: int, b: int) -> None:
        lo, hi = min(a, b), max(a, b)
        self.db.x("INSERT OR REPLACE INTO person_pairs(a, b, same, at) VALUES(?,?,0,?)", (lo, hi, time.time()))
        self.publish()

    # ------------------------------------------------------------------ reference photos
    def add_reference(self, emb: np.ndarray, quality: float) -> str:
        now = time.time()
        for t, (_, _, created) in list(self._ref.items()):
            if now - created > 3600 * 6:
                self._ref.pop(t, None)
        token = uuid.uuid4().hex
        self._ref[token] = (emb.astype(np.float32), float(quality), now)
        return token

    def reference(self, token: str) -> np.ndarray | None:
        r = self._ref.get(token)
        return r[0] if r else None

    # ------------------------------------------------------------------ review queue
    def review_counts(self) -> dict[str, int]:
        faces = self.db.scalar(
            """SELECT COUNT(*) FROM faces f JOIN people p ON p.id=f.person_id JOIN media m ON m.id=f.media_id
               WHERE f.state='suggested' AND p.hidden=0 AND p.name IS NOT NULL AND m.state='active'""",
            default=0,
        )
        name = self.db.scalar(
            """SELECT COUNT(*) FROM people p WHERE p.name IS NULL AND p.hidden=0 AND p.kind='human'
               AND (SELECT COUNT(*) FROM faces f WHERE f.person_id=p.id) >= 3""",
            default=0,
        )
        merge = len(self.merge_suggestions(limit=50))
        out = {"faces": faces, "name": name, "merge": merge}
        extra = self.ctx.services.get("labels")
        if extra is not None:
            try:
                out.update(extra.review_counts())  # type: ignore[attr-defined]
            except Exception:
                pass
        out["total"] = sum(v for k, v in out.items() if k != "total")
        return out

    def review_faces(self, pid: int | None, limit: int = 12) -> dict[str, Any]:
        if pid is None:
            r = self.db.q1(
                """SELECT f.person_id AS pid, COUNT(*) n FROM faces f JOIN people p ON p.id=f.person_id JOIN media m ON m.id=f.media_id
                   WHERE f.state='suggested' AND p.hidden=0 AND p.name IS NOT NULL AND m.state='active'
                   GROUP BY f.person_id ORDER BY n DESC LIMIT 1"""
            )
            if r is None:
                return {"person": None, "items": [], "remaining": 0}
            pid = r["pid"]
        person = self.db.q1("SELECT id, name, cover_face_id FROM people WHERE id=?", (pid,))
        rows = self.db.q(
            """SELECT f.id, f.media_id, f.score, f.quality, m.phash, m.sens_state FROM faces f JOIN media m ON m.id=f.media_id
               WHERE f.person_id=? AND f.state='suggested' AND m.state='active'""",
            (pid,),
        )
        # Most informative first: closest to a coin flip, then higher quality
        def key(r):
            p = self.probability(r["score"] or 0)
            return (abs(p - 0.5), -r["quality"])

        rows = sorted(rows, key=key)
        # One representative per near-identical photo (bursts): answers spread through rescoring
        seen_hash: list[int] = []
        items = []
        for r in rows:
            ph = r["phash"]
            if ph is not None and any(bin((ph ^ h) & 0xFFFFFFFFFFFFFFFF).count("1") <= 4 for h in seen_hash):
                continue
            if ph is not None:
                seen_hash.append(ph)
            items.append(
                {
                    "face_id": r["id"],
                    "media_id": r["media_id"],
                    "score": round(float(r["score"] or 0), 3),
                    "probability": round(self.probability(r["score"] or 0), 3),
                    "quality": r["quality"],
                    "private": r["sens_state"] == "private",
                }
            )
            if len(items) >= limit:
                break
        known = [
            r["id"]
            for r in self.db.q(
                "SELECT id FROM faces WHERE person_id=? AND state IN ('confirmed','auto','cluster') ORDER BY (state='confirmed') DESC, quality DESC LIMIT 4",
                (pid,),
            )
        ]
        return {"person": dict(person) if person else None, "known": known, "items": items, "remaining": len(rows)}

    def merge_suggestions(self, limit: int = 10) -> list[dict[str, Any]]:
        people = self.db.q(
            """SELECT p.id, p.name, p.cover_face_id, (SELECT COUNT(*) FROM faces f WHERE f.person_id=p.id AND f.state IN ('confirmed','auto','cluster')) n
               FROM people p WHERE p.hidden=0 AND p.kind='human'"""
        )
        people = [p for p in people if p["n"] >= 2]
        if len(people) < 2:
            return []
        cents, keep = [], []
        for p in people:
            c = self.centroid(p["id"])
            if c is not None:
                cents.append(c)
                keep.append(p)
        if len(keep) < 2:
            return []
        C = np.stack(cents)
        S = C @ C.T
        np.fill_diagonal(S, -1)
        answered = {(r["a"], r["b"]) for r in self.db.q("SELECT a, b FROM person_pairs")}
        pairs = []
        for i, j in zip(*np.where(S >= MERGE_ASK)):
            if i >= j:
                continue
            a, b = keep[i], keep[j]
            if (min(a["id"], b["id"]), max(a["id"], b["id"])) in answered:
                continue
            if a["name"] and b["name"] and a["name"].lower() != b["name"].lower() and S[i, j] < 0.5:
                continue  # two different names: only ask when quite similar
            pairs.append((float(S[i, j]), a, b))
        pairs.sort(key=lambda t: -t[0])
        out = []
        for sim, a, b in pairs[:limit]:
            out.append({"similarity": round(sim, 3), "a": self._brief(a["id"]), "b": self._brief(b["id"])})
        return out

    def _brief(self, pid: int) -> dict[str, Any]:
        p = self.db.q1("SELECT id, name, cover_face_id FROM people WHERE id=?", (pid,))
        faces = [
            r["id"]
            for r in self.db.q(
                "SELECT id FROM faces WHERE person_id=? AND state IN ('confirmed','auto','cluster') ORDER BY quality DESC LIMIT 4", (pid,)
            )
        ]
        count = self.db.scalar(
            "SELECT COUNT(DISTINCT media_id) FROM faces WHERE person_id=? AND state IN ('confirmed','auto','cluster')", (pid,), default=0
        )
        return {"id": p["id"], "name": p["name"], "cover_face_id": p["cover_face_id"] or (faces[0] if faces else None), "faces": faces, "count": count}

    def name_suggestions(self, limit: int = 8) -> list[dict[str, Any]]:
        rows = self.db.q(
            """SELECT p.id, COUNT(f.id) n FROM people p JOIN faces f ON f.person_id=p.id
               WHERE p.name IS NULL AND p.hidden=0 AND p.kind='human' GROUP BY p.id HAVING n >= 3 ORDER BY n DESC LIMIT ?""",
            (limit,),
        )
        return [self._brief(r["id"]) for r in rows]

    # ------------------------------------------------------------------ coverage
    def coverage(self, pid: int) -> dict[str, Any]:
        found = self.db.scalar(
            """SELECT COUNT(DISTINCT f.media_id) FROM faces f JOIN media m ON m.id=f.media_id
               WHERE f.person_id=? AND f.state IN ('confirmed','auto','cluster') AND m.state='active'""",
            (pid,),
            default=0,
        )
        sugg = self.db.q(
            "SELECT f.score FROM faces f JOIN media m ON m.id=f.media_id WHERE f.person_id=? AND f.state='suggested' AND m.state='active'",
            (pid,),
        )
        expected = sum(self.probability(r["score"] or 0) for r in sugg)
        # near misses: faces just below the "please check" line
        E = self.exemplars(pid)
        near = 0.0
        if len(E):
            sure, check = self.thresholds()
            _, sc = self.index.score_all(E)
            band = sc[(sc >= check - 0.08) & (sc < check)]
            near = float(sum(self.probability(float(x)) for x in band))
        denom = found + expected + near
        pct = 100.0 if denom <= 0 else 100.0 * found / denom
        return {"found": found, "to_check": len(sugg), "expected_in_check": round(expected, 1), "near_misses": round(near, 1), "percent": round(pct, 1)}


def create(ctx: Context) -> People:
    return People(ctx)
