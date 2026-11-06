"""Universal search: understands people, dates, kinds, ages, emotions, folders and categories,
and sends whatever is left to SigLIP 2 as a description ("laptop on a sofa")."""
from __future__ import annotations

import os
import re
import time
from datetime import datetime
from typing import Any

import numpy as np

from ..context import Context

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"], 1)}
MONTHS.update({k[:3]: v for k, v in list(MONTHS.items())})

AGE_WORDS = {
    "baby": (0, 3), "babies": (0, 3), "infant": (0, 3), "toddler": (1, 4),
    "kid": (3, 12), "kids": (3, 12), "child": (3, 12), "children": (3, 12),
    "teen": (13, 19), "teens": (13, 19), "teenager": (13, 19),
    "old": (60, 120), "elderly": (60, 120), "senior": (60, 120), "seniors": (60, 120), "grandparents": (60, 120),
}
GENDER_WORDS = {
    "girl": ("female", (0, 17)), "girls": ("female", (0, 17)), "boy": ("male", (0, 17)), "boys": ("male", (0, 17)),
    "woman": ("female", (18, 120)), "women": ("female", (18, 120)), "lady": ("female", (18, 120)), "ladies": ("female", (18, 120)),
    "man": ("male", (18, 120)), "men": ("male", (18, 120)), "female": ("female", None), "male": ("male", None),
}
EMOTION_WORDS = {
    "happy": "happy", "smiling": "happy", "smile": "happy", "laughing": "happy",
    "sad": "sad", "crying": "sad", "angry": "angry", "surprised": "surprise", "shocked": "surprise",
    "scared": "fear", "afraid": "fear", "disgusted": "disgust", "serious": "neutral",
}
SIZE_WORDS = {"alone": (1, 1), "solo": (1, 1), "single": (1, 1), "couple": (2, 2), "pair": (2, 2),
              "group": (3, 1000), "groups": (3, 1000), "crowd": (7, 1000)}
KIND_WORDS = {"video": "video", "videos": "video", "clip": "video", "clips": "video",
              "photo": "image", "photos": "image", "picture": "image", "pictures": "image", "pic": "image", "pics": "image", "image": "image", "images": "image"}
STOP = {"with", "and", "of", "the", "a", "an", "in", "at", "on", "from", "my", "me", "all", "show", "find", "only", "together", "to", "for", "&"}
# Words split on spaces and punctuation, not on \w: Python's \w skips the vowel signs of Hindi,
# Marathi and other Indic scripts, which cut "नमस्ते" into "नमस" + "त".
WORD_RE = re.compile(r"[^\s,.;:!?()\[\]{}\"“”&/+|]+")
SENSITIVE_WORDS = {"nude", "nudes", "naked", "nudity", "sexy", "sex", "sexual", "porn", "lingerie", "bikini", "romance", "romantic", "kissing", "kiss", "intimate", "private"}


def parse(c: Context, q: str) -> dict[str, Any]:
    text = " " + q.strip() + " "
    out: dict[str, Any] = {"people": [], "years": [], "months": [], "kind": None, "age": None, "gender": None,
                           "emotion": None, "size": None, "labels": [], "folders": [], "text": "", "sensitive": False}
    low = text.lower()
    # people: longest names first
    named = sorted(c.db.q("SELECT id, name FROM people WHERE name IS NOT NULL AND hidden=0"), key=lambda r: -len(r["name"]))
    for p in named:
        pat = re.compile(r"(?<![\w])" + re.escape(p["name"].lower()) + r"(?![\w])")
        if pat.search(low):
            out["people"].append({"id": p["id"], "name": p["name"]})
            low = pat.sub(" ", low)
    # folders by their last name segment
    for f in c.db.q("SELECT id, path FROM folders"):
        base = os.path.basename(f["path"].rstrip("\\/")).lower()
        if len(base) >= 3 and re.search(r"(?<![\w])" + re.escape(base) + r"(?![\w])", low):
            out["folders"].append({"id": f["id"], "name": os.path.basename(f["path"].rstrip("\\/"))})
            low = low.replace(base, " ")
    # years and relative years
    now = datetime.now()
    for y in re.findall(r"(?<!\d)(19[5-9]\d|20[0-4]\d)(?!\d)", low):
        out["years"].append(int(y))
    low = re.sub(r"(?<!\d)(19[5-9]\d|20[0-4]\d)(?!\d)", " ", low)
    if "last year" in low:
        out["years"].append(now.year - 1)
        low = low.replace("last year", " ")
    if "this year" in low:
        out["years"].append(now.year)
        low = low.replace("this year", " ")
    words = WORD_RE.findall(low)
    rest: list[str] = []
    for w in words:
        if w in MONTHS:
            out["months"].append(MONTHS[w])
        elif w in KIND_WORDS and out["kind"] is None:
            out["kind"] = KIND_WORDS[w]
        elif w in GENDER_WORDS:
            g, rng = GENDER_WORDS[w]
            out["gender"] = g
            if rng and out["age"] is None:  # "old men": keep the age word's range
                out["age"] = rng
        elif w in AGE_WORDS:
            out["age"] = AGE_WORDS[w]
        elif w in EMOTION_WORDS:
            out["emotion"] = EMOTION_WORDS[w]  # checked on the faces, not in the description
        elif w in SIZE_WORDS:
            out["size"] = SIZE_WORDS[w]
        elif w in STOP:
            continue
        else:
            if w in SENSITIVE_WORDS:
                out["sensitive"] = True
            rest.append(w)
    out["text"] = " ".join(rest).strip()
    # a single word that is exactly a category name becomes a category filter
    if out["text"]:
        lab = c.db.q1("SELECT id, name, grp FROM labels WHERE lower(name)=? AND enabled=1", (out["text"].lower(),))
        if lab is not None:
            out["labels"].append({"id": lab["id"], "name": lab["name"], "grp": lab["grp"]})
    return out


def run(c: Context, q: str, overrides: dict[str, Any] | None = None, limit: int = 2000) -> dict[str, Any]:
    t0 = time.time()
    p = parse(c, q)
    if overrides:
        p.update(overrides)  # a removed chip arrives as null or an empty list
    if p["sensitive"] and p["age"] and p["age"][0] < 18:
        return {"query": q, "parsed": p, "refused": "Private content can't be combined with searches for children.", "sure": [], "check": []}
    db = c.db
    from ..api.visibility import private_hidden

    where = ["m.state='active'"]
    params: list[Any] = []
    hide = private_hidden(c)
    if hide:
        where.append("m.sens_state NOT IN ('private','review')")
    if p["kind"]:
        where.append("m.kind=?")
        params.append(p["kind"])
    if p["folders"]:
        where.append(f"m.folder_id IN ({','.join('?' * len(p['folders']))})")
        params += [f["id"] for f in p["folders"]]
    if p["years"]:
        where.append(f"CAST(strftime('%Y', m.taken_at, 'unixepoch', 'localtime') AS INTEGER) IN ({','.join('?' * len(p['years']))})")
        params += p["years"]
    if p["months"]:
        where.append(f"CAST(strftime('%m', m.taken_at, 'unixepoch', 'localtime') AS INTEGER) IN ({','.join('?' * len(p['months']))})")
        params += p["months"]
    face_conds = []
    fparams: list[Any] = []
    if p["age"]:
        face_conds.append("f.age BETWEEN ? AND ?")
        fparams += list(p["age"])
    if p["gender"]:
        face_conds.append("f.male >= 0.5" if p["gender"] == "male" else "f.male < 0.5")
    # The expression model's probabilities are flat; negative expressions are over-predicted
    # on neutral faces, so they need more confidence than "happy".
    floor = {"happy": 0.30, "neutral": 0.30, "surprise": 0.35, "sad": 0.40, "fear": 0.40}.get(p["emotion"] or "", 0.45)
    if p["emotion"] and not p["people"]:
        face_conds.append("f.emotion=? AND f.emotion_score >= ?")
        fparams += [p["emotion"], floor]
    if face_conds:
        where.append(f"EXISTS (SELECT 1 FROM faces f WHERE f.media_id=m.id AND f.quality >= 0.25 AND {' AND '.join(face_conds)})")
        params += fparams
    if p["size"]:
        lo, hi = p["size"]
        where.append("(SELECT COUNT(*) FROM faces f WHERE f.media_id=m.id AND f.quality >= 0.3) BETWEEN ? AND ?")
        params += [lo, hi]
    for lab in p["labels"]:
        where.append("EXISTS (SELECT 1 FROM media_labels ml WHERE ml.media_id=m.id AND ml.label_id=? AND ml.state!='rejected' AND (ml.tier!='no' OR ml.state='confirmed'))")
        params.append(lab["id"])
    rows = db.q(f"SELECT m.id, m.taken_at FROM media m WHERE {' AND '.join(where)}", params)
    cand = [r["id"] for r in rows]
    taken = {r["id"]: r["taken_at"] or 0 for r in rows}

    scores: dict[int, tuple[str, float]] = {mid: ("sure", 1.0) for mid in cand}
    # people narrow the set (all named people together)
    if p["people"] and cand:
        from .search import search_people

        res = search_people(c, [x["id"] for x in p["people"]], mode="all" if len(p["people"]) > 1 else "any")
        hits = res["sure"] + res["check"]
        if p["emotion"]:
            # "Rohit smiling": the expression must be on Rohit's own face
            fids = [h["face_id"] for h in hits]
            ok_faces: set[int] = set()
            for i in range(0, len(fids), 900):
                chunk = fids[i : i + 900]
                ok_faces |= {
                    r["id"]
                    for r in db.q(
                        f"SELECT id FROM faces WHERE id IN ({','.join('?' * len(chunk))}) AND emotion=? AND emotion_score >= ?",
                        [*chunk, p["emotion"], floor],
                    )
                }
            hits = [h for h in hits if h["face_id"] in ok_faces]
        tiers = {h["id"]: (h["tier"], h["score"]) for h in hits}
        scores = {mid: tiers[mid] for mid in cand if mid in tiers}
    # free text via SigLIP 2 (only when it isn't just a category name we already applied)
    sem_text = p["text"] if not p["labels"] else ""
    text_hits: set[int] = set()
    if sem_text and scores:
        model = c.services["ml"].siglip()  # type: ignore[attr-defined]
        index = c.services.get("semantic_index")
        if model is not None and index is not None:
            from ..taxonomy import GENERIC_BG

            # Relative score: the description against "nothing special" descriptions, at SigLIP's
            # temperature (absolute SigLIP probabilities stay low for short queries).
            T = model.embed_texts([sem_text, f"a photo of {sem_text}"])
            B = model.embed_texts([b for b in GENERIC_BG if b.lower() != sem_text.lower()])
            ids, s1 = index.scores(T[0], list(scores))  # type: ignore[attr-defined]
            _, s2 = index.scores(T[1], list(scores))  # type: ignore[attr-defined]
            sq = np.maximum(s1, s2)
            sb = np.stack([index.scores(b, list(scores))[1] for b in B], axis=1)  # type: ignore[attr-defined]
            logits = model.scale * np.concatenate([sq[:, None], sb], axis=1)
            logits -= logits.max(axis=1, keepdims=True)
            ex = np.exp(logits)
            prob = ex[:, 0] / ex.sum(axis=1)
            sure_t, check_t = _text_thresholds(c)
            new: dict[int, tuple[str, float]] = {}
            for mid, pr in zip(ids.tolist(), prob.tolist()):
                base_tier, base_s = scores[mid]
                if pr >= sure_t:
                    tier = base_tier
                elif pr >= check_t:
                    tier = "check"
                else:
                    continue
                new[mid] = (tier, float(pr) if not p["people"] else min(base_s, float(pr)))
            scores = new
        # words inside photos (OCR) also count
        text_hits = _text_matches(c, sem_text, set(cand))
        for mid in text_hits:
            if mid not in scores or scores[mid][0] != "sure":
                scores[mid] = ("sure", 0.99)
    ranked = sorted(scores.items(), key=lambda kv: (kv[1][0] != "sure", -kv[1][1] if sem_text else -taken.get(kv[0], 0)))
    ranked = ranked[:limit]
    from ..api.routes_media import item_dict
    from ..api.visibility import check_pending

    priv = c.services.get("private")
    blur = True if priv is None else bool(priv.blur_enabled())  # type: ignore[attr-defined]
    chk = check_pending(c)
    ids = [mid for mid, _ in ranked]
    rowmap = {}
    for i in range(0, len(ids), 900):
        chunk = ids[i : i + 900]
        for r in db.q(f"SELECT * FROM media WHERE id IN ({','.join('?' * len(chunk))})", chunk):
            rowmap[r["id"]] = r
    sure, check = [], []
    for mid, (tier, s) in ranked:
        r = rowmap.get(mid)
        if r is None:
            continue
        it = item_dict(r, chk, blur)
        it["tier"], it["score"] = tier, round(s, 3)
        it["text_match"] = mid in text_hits
        (sure if tier == "sure" else check).append(it)
    hidden = 0
    if hide:
        hidden = db.scalar("SELECT COUNT(*) FROM media WHERE state='active' AND sens_state IN ('private','review')", default=0) if (p["sensitive"]) else 0
    return {"query": q, "parsed": p, "sure": sure, "check": check, "hidden_private": hidden, "took_ms": int((time.time() - t0) * 1000)}


def _text_thresholds(c: Context) -> tuple[float, float]:
    mode = str(c.settings.get("sensitivity.categories", "balanced"))
    return {"never_miss": (0.50, 0.10), "balanced": (0.50, 0.18), "fewer": (0.45, 0.28)}.get(mode, (0.50, 0.18))


def _text_matches(c: Context, text: str, allowed: set[int]) -> set[int]:
    if len(text) < 3:
        return set()
    try:
        rows = c.db.q("SELECT DISTINCT media_id FROM texts WHERE texts MATCH ? LIMIT 5000", ('"' + text.replace('"', " ") + '"',))
    except Exception:
        return set()
    return {int(r["media_id"]) for r in rows if int(r["media_id"]) in allowed}
