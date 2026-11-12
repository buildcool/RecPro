"""Universal search: understands people and pets, dates, kinds, ages, emotions, folders, places,
categories and things, and sends whatever is left to SigLIP 2 as a description ("a sunset at a
beach"). A query made only of things ("dog", "laptop sofa", "umbrella") uses what the categories
and the object detector found, with their Sure / Please check tiers."""
from __future__ import annotations

import json
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
# search words that are also the name of a town somewhere ("May"): never taken as a place
PLACE_SKIP = frozenset(STOP | set(MONTHS) | set(KIND_WORDS) | set(AGE_WORDS) | set(GENDER_WORDS) | set(EMOTION_WORDS) | set(SIZE_WORDS))
# with a place named, these say nothing more: "Goa trip" is the photos taken in Goa
TRIP_WORDS = {"trip", "trips", "tour", "travel", "travels", "vacation", "vacations", "holiday", "holidays", "visit", "journey"}
# everyday words for the categories the detector backs up (and their other spellings)
CATEGORY_WORDS = {
    **dict.fromkeys(("dog", "dogs", "puppy", "puppies", "doggy"), "pet.dog"),
    **dict.fromkeys(("cat", "cats", "kitten", "kittens", "kitty"), "pet.cat"),
    **dict.fromkeys(("bird", "birds"), "pet.bird"),
    **dict.fromkeys(("cow", "cows"), "pet.cow"),
    **dict.fromkeys(("horse", "horses"), "pet.horse"),
    **dict.fromkeys(("fish", "fishes"), "pet.fish"),
    **dict.fromkeys(("laptop", "laptops", "notebook"), "object.laptop"),
    **dict.fromkeys(("phone", "phones", "mobile", "mobiles", "smartphone", "smartphones", "cellphone"), "object.phone"),
    **dict.fromkeys(("computer", "computers", "desktop", "pc"), "object.desktop"),
    **dict.fromkeys(("sofa", "sofas", "couch", "couches"), "object.sofa"),
    **dict.fromkeys(("fridge", "fridges", "refrigerator"), "object.fridge"),
    **dict.fromkeys(("tv", "television", "tvs"), "object.tv"),
    **dict.fromkeys(("car", "cars"), "object.car"),
    **dict.fromkeys(("bike", "bikes", "motorbike", "motorbikes", "motorcycle", "motorcycles", "scooter", "scooters", "scooty"), "object.motorbike"),
    **dict.fromkeys(("bicycle", "bicycles", "cycle", "cycles"), "object.bicycle"),
    **dict.fromkeys(("cake", "cakes", "sweets", "dessert", "desserts"), "object.cake"),
    **dict.fromkeys(("flower", "flowers"), "object.flowers"),
    **dict.fromkeys(("guitar", "guitars"), "object.guitar"),
    **dict.fromkeys(("book", "books"), "object.books"),
    **dict.fromkeys(("watch", "watches"), "object.watch"),
    **dict.fromkeys(("jewellery", "jewelry"), "object.jewelry"),
    **dict.fromkeys(("drink", "drinks"), "object.drinks"),
}
# other words for things the detector knows (its own names are understood already)
OBJECT_SYNONYMS = {
    **dict.fromkeys(("teddy", "teddy bear", "teddy bears", "teddies"), ("Stuffed Toy",)),
    **dict.fromkeys(("specs", "spectacles", "sunglasses", "goggles"), ("Glasses",)),
    **dict.fromkeys(("mug", "mugs"), ("Cup",)),
    **dict.fromkeys(("cupboard", "cupboards", "almirah", "wardrobe", "shelf", "shelves"), ("Cabinet/shelf",)),
    **dict.fromkeys(("bag", "bags"), ("Handbag/Satchel", "Backpack", "Briefcase")),
    **dict.fromkeys(("purse", "purses"), ("Wallet/Purse", "Handbag/Satchel")),
    **dict.fromkeys(("suitcase", "suitcases"), ("Luggage",)),
    **dict.fromkeys(("ac", "air conditioner"), ("Air Conditioner",)),
    **dict.fromkeys(("plane", "planes", "aeroplane", "aeroplanes", "flight"), ("Airplane",)),
    **dict.fromkeys(("auto", "autos", "auto rickshaw", "tuk tuk"), ("Rickshaw",)),
    **dict.fromkeys(("earbuds", "earphones"), ("earphone",)),
    **dict.fromkeys(("ipad", "ipads"), ("Tablet",)),
    **dict.fromkeys(("bus", "buses"), ("Bus",)),
}
SENSITIVE_WORDS = {"nude", "nudes", "naked", "nudity", "sexy", "sex", "sexual", "porn", "lingerie", "bikini", "romance", "romantic", "kissing", "kiss", "intimate", "private"}


def parse(c: Context, q: str) -> dict[str, Any]:
    text = " " + q.strip() + " "
    out: dict[str, Any] = {"people": [], "years": [], "months": [], "kind": None, "age": None, "gender": None,
                           "emotion": None, "size": None, "labels": [], "objects": [], "folders": [], "places": [], "text": "", "sensitive": False}
    low = text.lower()
    # people: longest names first
    named = sorted(c.db.q("SELECT id, name, kind FROM people WHERE name IS NOT NULL AND hidden=0"), key=lambda r: -len(r["name"]))
    for p in named:
        pat = re.compile(r"(?<![\w])" + re.escape(p["name"].lower()) + r"(?![\w])")
        if pat.search(low):
            out["people"].append({"id": p["id"], "name": p["name"], "kind": p["kind"]})
            low = pat.sub(" ", low)
    # folders by their last name segment
    for f in c.db.q("SELECT id, path FROM folders"):
        base = os.path.basename(f["path"].rstrip("\\/")).lower()
        if len(base) >= 3 and re.search(r"(?<![\w])" + re.escape(base) + r"(?![\w])", low):
            out["folders"].append({"id": f["id"], "name": os.path.basename(f["path"].rstrip("\\/"))})
            low = low.replace(base, " ")
    # places where there are photos: a town, a state or a country ("Goa", "Pune", "France"),
    # matched without accents or case
    low = _match_places(c, low, out["places"])
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
        elif w in STOP or (out["places"] and w in TRIP_WORDS):
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
        # only things ("dog", "laptop sofa", "umbrella"): their categories and what the detector saw
        things = _things(c, rest)
        if things is not None:
            out["labels"] += things[0]
            out["objects"] += things[1]
            out["text"] = ""
    return out


def _object_words() -> dict[str, tuple[str, list[int]]]:
    """word -> (name shown, detector classes) for the things the detector knows by name."""
    from ..ml.objects import CLASS, LABELS, display

    words: dict[str, tuple[str, list[int]]] = {}
    for i, raw in enumerate(LABELS):
        if i == 0 or raw == "Person":
            continue
        name = display(i)
        for form in {name.lower(), raw.lower()}:
            if "/" in form or len(form) < 3:
                continue
            for w in (form, form + "s", form[:-1] + "ies" if form.endswith("y") else form + "es"):
                cur = words.get(w)
                words[w] = (cur[0], cur[1] + [i]) if cur and i not in cur[1] else (cur or (name, [i]))
    for w in ("tennis", "french", "target", "cue"):  # in a search these mean something else
        words.pop(w, None)
    for w, names in OBJECT_SYNONYMS.items():
        cls = [CLASS[n] for n in names]
        words[w] = (display(cls[0]), cls)
    return words


def _things(c: Context, words: list[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]] | None:
    """Categories and detector classes for a query of only things, or None if any word isn't one."""
    if not words:
        return None
    vocab = _object_words()
    labels: list[dict[str, Any]] = []
    objects: list[dict[str, Any]] = []
    i = 0
    while i < len(words):
        two = " ".join(words[i : i + 2])
        if i + 1 < len(words) and two in vocab:  # "wine glass", "teddy bear"…
            name, classes = vocab[two]
            objects.append({"name": name, "classes": classes})
            i += 2
            continue
        w = words[i]
        key = CATEGORY_WORDS.get(w)
        if key is not None:
            lab = c.db.q1("SELECT id, name, grp FROM labels WHERE key=? AND enabled=1", (key,))
            if lab is None:
                return None
            if all(x["id"] != lab["id"] for x in labels):
                labels.append({"id": lab["id"], "name": lab["name"], "grp": lab["grp"]})
        elif w in vocab:
            name, classes = vocab[w]
            objects.append({"name": name, "classes": classes})
        else:
            return None
        i += 1
    return labels, objects


def library_places(c: Context) -> list[tuple[str, str, list[int]]]:
    """(folded name, name as shown, the place ids it covers) for every town, state and country
    with photos, longest names first. A state covers all its towns; a town is a city or a locality."""
    from ..library.places import fold

    rows = c.db.q(
        """SELECT p.id, p.name, p.admin1, p.country FROM places p
           WHERE p.id IN (SELECT city_id FROM media WHERE city_id IS NOT NULL)
              OR p.id IN (SELECT place_id FROM media WHERE place_id IS NOT NULL)"""
    )
    by: dict[str, tuple[str, set[int]]] = {}
    for r in rows:
        for name in (r["name"], r["admin1"], r["country"]):
            if name and len(name) >= 3:
                k = fold(name)
                by.setdefault(k, (name, set()))[1].add(int(r["id"]))
    return sorted(((k, v[0], sorted(v[1])) for k, v in by.items()), key=lambda x: -len(x[0]))


def _match_places(c: Context, low: str, found: list[dict[str, Any]]) -> str:
    """Finds place names in the query and takes them out of it. Matched on a copy without accents
    (only the copy: folding would also strip the virama from Hindi words)."""
    from ..library.places import fold

    if c.db.scalar("SELECT 1 FROM media WHERE city_id IS NOT NULL LIMIT 1") is None:
        return low
    plain = fold(low)
    for key, name, ids in library_places(c):
        if key in PLACE_SKIP:
            continue
        pat = re.compile(r"(?<![\w])" + re.escape(key) + r"(?![\w])")
        if not pat.search(plain):
            continue
        found.append({"name": name, "ids": ids})
        plain = pat.sub(" ", plain)
        for form in {key, name.lower()}:
            low = re.sub(r"(?<![\w])" + re.escape(form) + r"(?![\w])", " ", low)
    return low


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
    if p.get("places"):  # any of the places named
        ids = json.dumps(sorted({i for pl in p["places"] for i in pl["ids"]}))
        where.append("(m.city_id IN (SELECT value FROM json_each(?)) OR m.place_id IN (SELECT value FROM json_each(?)))")
        params += [ids, ids]
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
    det_check, det_sure = _det_thresholds(c)
    for ob in p.get("objects") or []:
        where.append(f"EXISTS (SELECT 1 FROM objects o WHERE o.media_id=m.id AND o.cls IN ({','.join('?' * len(ob['classes']))}) AND o.score >= ?)")
        params += [*ob["classes"], det_check]
    rows = db.q(f"SELECT m.id, m.taken_at FROM media m WHERE {' AND '.join(where)}", params)
    cand = [r["id"] for r in rows]
    taken = {r["id"]: r["taken_at"] or 0 for r in rows}

    scores: dict[int, tuple[str, float]] = {mid: ("sure", 1.0) for mid in cand}
    if cand and (p["labels"] or p.get("objects")):
        # a category or a thing the AI isn't sure of makes the photo a "please check"
        unsure = _unsure(c, cand, [lab["id"] for lab in p["labels"]], p.get("objects") or [], det_sure)
        scores = {mid: (("check", 0.5) if mid in unsure else ("sure", 1.0)) for mid in cand}
    moments: dict[int, dict[str, Any]] = {}  # videos: where the match is
    # people narrow the set (all named people together)
    if p["people"] and cand:
        from .search import search_people

        res = search_people(c, [x["id"] for x in p["people"]], mode="all" if len(p["people"]) > 1 else "any")
        hits = res["sure"] + res["check"]
        if p["emotion"]:
            # "Rohit smiling": the expression must be on Rohit's own face (a pet's photos stay)
            pet_hits = [h for h in hits if h.get("det") == "animal"]
            hits = [h for h in hits if h.get("det") != "animal"]
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
            hits = [h for h in hits if h["face_id"] in ok_faces] + pet_hits
        tiers = {h["id"]: (h["tier"], h["score"]) for h in hits}
        scores = {mid: tiers[mid] for mid in cand if mid in tiers}
        moments = {h["id"]: {"spans": h["spans"], "at_ms": h["at_ms"]} for h in hits if h.get("spans")}
    if face_conds and not p["people"] and scores:
        # "old men", "smiling kids": in a video, when the faces that match are on screen
        from .moments import face_spans

        vids = [r["id"] for r in db.q(f"SELECT id FROM media WHERE kind='video' AND id IN ({','.join('?' * len(scores))})", list(scores))] if len(scores) < 30000 else []
        if vids:
            fq = db.q(
                f"""SELECT f.id, f.media_id FROM faces f WHERE f.media_id IN ({','.join('?' * len(vids))}) AND f.quality >= 0.25
                    AND {' AND '.join(face_conds)}""",
                [*vids, *fparams],
            )
            fs = face_spans(db, [r["id"] for r in fq])
            label = " ".join(w for w in q.split() if w)
            for r in fq:
                sp = [{"name": label, "start_ms": s, "end_ms": e} for s, e in fs.get(r["id"], [])]
                if sp:
                    cur = moments.setdefault(r["media_id"], {"spans": []})
                    cur["spans"] = sorted(cur["spans"] + sp, key=lambda x: x["start_ms"])
                    cur["at_ms"] = cur["spans"][0]["start_ms"]
    if p["labels"] and scores:
        from .moments import label_spans

        vids = [r["id"] for r in db.q(f"SELECT id FROM media WHERE kind='video' AND id IN ({','.join('?' * len(scores))})", list(scores))] if len(scores) < 30000 else []
        for mid, sp in label_spans(db, vids, [lab["id"] for lab in p["labels"]]).items():
            if mid not in moments:
                moments[mid] = {"spans": sp, "at_ms": sp[0]["start_ms"]}
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
            ids, E = index.rows(list(scores))  # type: ignore[attr-defined]
            best = dict(zip(ids.tolist(), _relative(model, E, T, B).tolist())) if len(ids) else {}
            # videos: every scene frame competes; the best one says where the match is
            owners, times, Ef = index.frame_matrix(list(scores))  # type: ignore[attr-defined]
            if len(owners):
                pf = _relative(model, Ef, T, B)
                for mid, t, pr in zip(owners.tolist(), times.tolist(), pf.tolist()):
                    if pr > best.get(mid, -1.0):
                        best[mid] = pr
                        moments[mid] = {"at_ms": t, "spans": [{"name": sem_text, "start_ms": t, "end_ms": t + 2000}]}
            sure_t, check_t = _text_thresholds(c)
            new: dict[int, tuple[str, float]] = {}
            for mid, pr in best.items():
                base_tier, base_s = scores[mid]
                if pr >= sure_t:
                    tier = base_tier
                elif pr >= check_t:
                    tier = "check"
                else:
                    continue
                new[mid] = (tier, float(pr) if not p["people"] else min(base_s, float(pr)))
            scores = new
        # words inside photos (OCR) and said in videos also count
        text_hits = _text_matches(c, sem_text, set(cand))
        for mid, said in _speech_matches(c, sem_text, set(cand)).items():
            text_hits.add(mid)
            sp = [{"name": f"“{sem_text}”", "start_ms": s, "end_ms": e} for s, e in said]
            moments[mid] = {"spans": sp, "at_ms": sp[0]["start_ms"]}
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
        if mid in moments:
            it.update(moments[mid])
        (sure if tier == "sure" else check).append(it)
    hidden = 0
    if hide:
        hidden = db.scalar("SELECT COUNT(*) FROM media WHERE state='active' AND sens_state IN ('private','review')", default=0) if (p["sensitive"]) else 0
    return {"query": q, "parsed": p, "sure": sure, "check": check, "hidden_private": hidden, "took_ms": int((time.time() - t0) * 1000)}


def _relative(model: Any, E: np.ndarray, T: np.ndarray, B: np.ndarray) -> np.ndarray:
    """The description against "nothing special" descriptions, at SigLIP's temperature, per row."""
    sq = np.maximum(E @ T[0], E @ T[1])
    logits = model.scale * np.concatenate([sq[:, None], E @ B.T], axis=1)
    logits -= logits.max(axis=1, keepdims=True)
    ex = np.exp(logits)
    return ex[:, 0] / ex.sum(axis=1)


def _det_thresholds(c: Context) -> tuple[float, float]:
    """(please check, sure) for a thing the detector saw, at the categories' sensitivity."""
    from ..labels import THRESHOLDS

    mode = str(c.settings.get("sensitivity.categories", "balanced"))
    return THRESHOLDS["det"].get(mode, THRESHOLDS["det"]["balanced"])


def _unsure(c: Context, mids: list[int], label_ids: list[int], objects: list[dict[str, Any]], det_sure: float) -> set[int]:
    """The photos where one of the categories is only "please check", or a thing was seen only faintly."""
    out: set[int] = set()
    for i in range(0, len(mids), 900):
        chunk = mids[i : i + 900]
        marks = ",".join("?" * len(chunk))
        for lid in label_ids:
            out |= {
                int(r[0])
                for r in c.db.q(
                    f"SELECT media_id FROM media_labels WHERE label_id=? AND media_id IN ({marks}) AND state!='confirmed' AND tier!='sure'",
                    [lid, *chunk],
                )
            }
        for ob in objects:
            cls = ",".join("?" * len(ob["classes"]))
            strong = {
                int(r[0])
                for r in c.db.q(f"SELECT DISTINCT media_id FROM objects WHERE cls IN ({cls}) AND score >= ? AND media_id IN ({marks})", [*ob["classes"], det_sure, *chunk])
            }
            out |= set(chunk) - strong
    return out


def _text_thresholds(c: Context) -> tuple[float, float]:
    mode = str(c.settings.get("sensitivity.categories", "balanced"))
    return {"never_miss": (0.50, 0.10), "balanced": (0.50, 0.18), "fewer": (0.45, 0.28)}.get(mode, (0.50, 0.18))


def _speech_matches(c: Context, text: str, allowed: set[int]) -> dict[int, list[tuple[int, int]]]:
    """Videos where the words are said, with when."""
    if len(text) < 3:
        return {}
    try:
        rows = c.db.q(
            "SELECT media_id, start_ms, end_ms FROM speech WHERE speech MATCH ? ORDER BY media_id, start_ms LIMIT 5000",
            ('"' + text.replace('"', " ") + '"',),
        )
    except Exception:
        return {}
    out: dict[int, list[tuple[int, int]]] = {}
    for r in rows:
        mid = int(r["media_id"])
        if mid in allowed:
            out.setdefault(mid, []).append((int(r["start_ms"]), int(r["end_ms"])))
    return out


def _text_matches(c: Context, text: str, allowed: set[int]) -> set[int]:
    if len(text) < 3:
        return set()
    try:
        rows = c.db.q("SELECT DISTINCT media_id FROM texts WHERE texts MATCH ? LIMIT 5000", ('"' + text.replace('"', " ") + '"',))
    except Exception:
        return set()
    return {int(r["media_id"]) for r in rows if int(r["media_id"]) in allowed}
