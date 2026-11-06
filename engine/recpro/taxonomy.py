"""Built-in and custom categories scored from stored SigLIP 2 embeddings.

Built-in categories are prompt ensembles. Because every photo's embedding is stored, a new or
changed category is scored across the whole library instantly, without re-reading any photo.
After enough of your answers a category also gets a personal classifier (logistic regression on
the embeddings), which joins SigLIP as a second source.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any

import numpy as np

from .context import Context
from .labels import LabelDef

log = logging.getLogger("recpro.taxonomy")

TAXONOMY_V = 3  # v2: relative (group softmax) scoring; v3: "it's text" alternatives, private content on absolute scores


def _d(key: str, name: str, grp: str, *prompts: str) -> LabelDef:
    return LabelDef(f"{grp}.{key}", name, grp, list(prompts))


BUILTIN: list[LabelDef] = [
    # activities
    _d("working", "Working", "activity", "a person working on a laptop", "people in an office meeting", "someone working at a desk"),
    _d("studying", "Studying", "activity", "a student studying with books", "a classroom with students", "someone doing homework"),
    _d("eating", "Eating together", "activity", "people eating a meal together", "a family dinner at a table", "friends eating at a restaurant"),
    _d("cooking", "Cooking", "activity", "a person cooking in a kitchen", "food being cooked in a pan"),
    _d("party", "Party", "activity", "a party with friends", "people celebrating at a party", "a night out with friends"),
    _d("dancing", "Dancing", "activity", "people dancing", "a dance performance"),
    _d("sports", "Sports", "activity", "people playing a sport", "a cricket match", "a football game", "playing badminton"),
    _d("gym", "Gym and workout", "activity", "a person working out in a gym", "lifting weights", "doing yoga"),
    _d("swimming", "Swimming", "activity", "people swimming in a pool", "a person swimming"),
    _d("travel", "Travel", "activity", "a tourist sightseeing at a famous landmark", "a travel photo on vacation", "people on a trip"),
    _d("driving", "Driving", "activity", "a person driving a car", "a road trip in a car"),
    _d("shopping", "Shopping", "activity", "people shopping in a mall", "a market with shops"),
    _d("praying", "Praying and worship", "activity", "people praying in a temple", "a religious ceremony", "a puja ceremony"),
    _d("wedding", "Wedding", "activity", "a wedding ceremony", "a bride and groom", "an Indian wedding"),
    _d("birthday", "Birthday", "activity", "a birthday celebration with a cake", "blowing out birthday candles"),
    _d("festival", "Festival", "activity", "Diwali celebration with lights and diyas", "Holi festival with colors", "a festival celebration", "Ganesh festival"),
    _d("concert", "Concert", "activity", "a live music concert", "a crowd at a concert"),
    _d("watching_tv", "Watching TV or movies", "activity", "people watching TV", "watching a movie in a cinema"),
    _d("gaming", "Gaming", "activity", "a person playing video games", "a gaming setup"),
    _d("selfie", "Selfie", "activity", "a selfie", "a close-up selfie taken with a phone"),
    _d("sleeping", "Sleeping", "activity", "a person sleeping", "a baby sleeping"),
    _d("hiking", "Hiking", "activity", "people hiking on a trail", "trekking in the mountains"),
    _d("music", "Playing music", "activity", "a person playing a guitar", "a person playing a musical instrument"),
    # moods
    _d("happy", "Happy moments", "mood", "happy smiling people", "people laughing together", "a joyful moment"),
    _d("calm", "Calm", "mood", "a calm peaceful scene", "a quiet relaxing moment"),
    _d("sad", "Sad", "mood", "a sad person crying", "a sad moment"),
    _d("celebration", "Celebration", "mood", "people celebrating", "a celebration with decorations"),
    _d("funny", "Funny", "mood", "a funny photo", "people making funny faces"),
    # places and scenes
    _d("beach", "Beach", "place", "a beach with the sea", "people at the beach"),
    _d("mountains", "Mountains", "place", "mountains", "a mountain landscape"),
    _d("city", "City", "place", "a city street", "a city skyline with buildings"),
    _d("home", "At home", "place", "inside a living room at home", "a bedroom at home"),
    _d("office", "Office", "place", "an office interior", "a workplace with desks"),
    _d("restaurant", "Restaurant", "place", "inside a restaurant", "a cafe"),
    _d("temple", "Temple", "place", "a Hindu temple", "a place of worship", "a church or mosque"),
    _d("park", "Park and garden", "place", "a park with trees", "a garden with flowers"),
    _d("night", "Night", "place", "a photo taken at night", "city lights at night"),
    _d("sunset", "Sunset", "place", "a sunset", "a sunrise sky"),
    _d("snow", "Snow", "place", "snow", "a snowy landscape"),
    _d("car_inside", "In a car", "place", "inside a car", "a car dashboard"),
    _d("airport", "Airport and flights", "place", "an airport", "a view from an airplane window"),
    _d("stage", "Stage and events", "place", "a stage with a performer", "an event hall with an audience"),
    # entertainment
    _d("screen_movie", "Movies and TV", "entertainment", "a photo of a TV screen showing a movie", "a cinema screen"),
    _d("meme", "Memes", "entertainment", "an internet meme with text", "a funny meme image"),
    _d("good_morning", "Greetings and wishes", "entertainment", "a good morning greeting image with flowers and text", "a festival wishes greeting card image"),
    # objects
    _d("laptop", "Laptop", "object", "a laptop", "a laptop computer on a desk"),
    _d("phone", "Mobile phone", "object", "a mobile phone", "a smartphone in a hand"),
    _d("desktop", "Desktop computer", "object", "a desktop computer with a monitor", "a computer monitor and keyboard"),
    _d("sofa", "Sofa", "object", "a sofa", "a couch in a living room"),
    _d("fridge", "Fridge", "object", "a refrigerator", "a fridge in a kitchen"),
    _d("tv", "Television", "object", "a television", "a TV on a wall"),
    _d("car", "Car", "object", "a car", "a parked car"),
    _d("motorbike", "Motorbike and scooter", "object", "a motorbike", "a scooter"),
    _d("bicycle", "Bicycle", "object", "a bicycle"),
    _d("food", "Food", "object", "a plate of food", "delicious food on a table", "Indian food"),
    _d("cake", "Cake and sweets", "object", "a cake", "sweets and desserts"),
    _d("flowers", "Flowers", "object", "flowers", "a bouquet of flowers"),
    _d("guitar", "Guitar", "object", "a guitar"),
    _d("books", "Books", "object", "books", "a bookshelf"),
    _d("watch", "Watch", "object", "a wrist watch"),
    _d("jewelry", "Jewelry", "object", "gold jewelry", "a necklace and earrings"),
    _d("money", "Money", "object", "money", "cash and banknotes"),
    _d("drinks", "Drinks", "object", "drinks in glasses", "a cup of tea or coffee"),
    # pets and animals
    _d("dog", "Dogs", "pet", "a dog", "a puppy"),
    _d("cat", "Cats", "pet", "a cat", "a kitten"),
    _d("bird", "Birds", "pet", "a bird", "a parrot"),
    _d("cow", "Cows", "pet", "a cow"),
    _d("horse", "Horses", "pet", "a horse"),
    _d("fish", "Fish", "pet", "fish in an aquarium"),
    # documents
    _d("document", "Documents", "document", "a photo of a printed document with text", "a scanned paper document"),
    _d("receipt", "Receipts and bills", "document", "a shopping receipt", "a bill or invoice"),
    _d("notes", "Handwritten notes", "document", "handwritten notes on paper", "a notebook page with handwriting"),
    _d("whiteboard", "Whiteboard", "document", "a whiteboard with writing"),
    _d("certificate", "Certificates", "document", "a certificate", "a degree certificate"),
    _d("id_card", "ID cards", "document", "an identity card", "a government ID card", "a photo ID card with a face"),
    _d("ticket", "Tickets and boarding passes", "document", "a ticket", "a boarding pass", "a train ticket"),
    _d("qr", "QR codes", "document", "a QR code"),
    # screenshots
    _d("screenshot", "Screenshots", "screenshot", "a screenshot of a phone screen", "a screenshot of an app"),
    _d("chat", "Chat screenshots", "screenshot", "a screenshot of a chat conversation", "a WhatsApp chat screenshot"),
    _d("social", "Social media posts", "screenshot", "a screenshot of an Instagram post", "a social media post screenshot"),
    _d("payment", "Payments", "screenshot", "a screenshot of a payment app showing a transaction", "a UPI payment successful screen"),
    _d("map", "Maps", "screenshot", "a screenshot of a map"),
    _d("webpage", "Web pages", "screenshot", "a screenshot of a website", "a screenshot of a news article"),
    _d("code", "Code", "screenshot", "a screenshot of programming code"),
    _d("video_call", "Video calls", "screenshot", "a screenshot of a video call"),
    # people types (image level; per-face age/gender/emotion are separate filters)
    _d("group_photo", "Group photos", "people", "a group photo of many people", "a family group photo"),
    _d("couple", "Couples", "people", "a couple posing together"),
    _d("kids", "Kids", "people", "children playing", "a child"),
    _d("baby", "Babies", "people", "a baby", "a newborn baby"),
    _d("elderly", "Elderly", "people", "an elderly person", "grandparents"),
]

# Within each group, categories compete against "nothing special here" prompts (a softmax at
# SigLIP's temperature). SigLIP's absolute sigmoid stays low for short prompts, so relative
# scoring is what makes "is this a beach?" work.
GENERIC_BG = ["a photo", "a photo of people", "a portrait photo of a person", "an everyday photo of a scene", "an abstract colorful image"]
# Text-heavy images (documents, chats, bills, cards) aren't photos of activities, places or things.
# Without these alternatives the softmax had to pick a category anyway: a WhatsApp chat about a
# party became "Party", a white ID card "Snow", an invoice for a laptop repair "Laptop". People
# keeps its own alternatives (a headshot looks like an ID photo, and "Elderly" lost real matches).
TEXT_BG = [
    "a page of printed text", "a screenshot of a chat with text messages", "a printed form or bill",
    "a plain white background", "large text on a plain background",
]
ID_BG = "an identity card with a photo and printed text"
BACKGROUND: dict[str, list[str]] = {
    "activity": ["a portrait photo of a person", "people posing for a photo", "a close-up photo of a face", "an abstract colorful image", "a photo of an object", *TEXT_BG],
    "mood": ["a neutral photo", "a portrait photo of a person", "an everyday photo", "an abstract colorful image", *TEXT_BG],
    "place": ["a close-up portrait photo of a person", "a photo with a plain background", "an abstract colorful image", "a photo of an object", *TEXT_BG, ID_BG],
    "people": ["a photo of a single adult person", "a photo with no people", "an abstract colorful image"],
    "object": ["a portrait photo of a person", "a photo of people", "a photo of a landscape", "an abstract colorful image", *TEXT_BG, ID_BG],
    "pet": ["a photo with no animals", "a photo of a person", "a photo of people", "an abstract colorful image", *TEXT_BG, ID_BG],
    "document": [
        "a photo of people", "a photo of a scene", "a portrait photo of a person", "an abstract colorful image",
        "a screenshot of a phone screen", "a screenshot of a chat with text messages", "a screenshot of an app",
    ],
    "screenshot": [
        "a photo taken with a camera", "a portrait photo of a person", "a photo of people", "an abstract colorful image", "a graphic illustration",
        "a photo of a printed paper document", "a paper receipt", ID_BG,
    ],
    "entertainment": ["a normal photo", "a photo of people", "a portrait photo of a person", "an abstract colorful image", *TEXT_BG, ID_BG],
}
# Private content is scored on SigLIP's own (absolute) probability, with NudeNet alongside. A
# softmax against a few "ordinary photo" prompts can't cover every kind of photo: measured on 733
# safe photos it put 158 in Private and 354 in "please check" (absolute scores: 0 and 8).
ABSOLUTE_ONLY = ("sensitive",)


def score_labels(model, E: np.ndarray, defs: list[LabelDef], cache: dict | None = None) -> dict[str, dict[str, np.ndarray]]:
    """Per label: {"siglip_rel": relative probability, "siglip": SigLIP's absolute probability}.

    Private content gets only the absolute probability (see ABSOLUTE_ONLY).
    """
    cache = cache if cache is not None else {}

    def emb(texts: tuple[str, ...]) -> np.ndarray:
        if texts not in cache:
            cache[texts] = model.embed_texts(list(texts))
        return cache[texts]

    groups: dict[str, list[LabelDef]] = {}
    for d in defs:
        if not d.prompts:
            continue
        # each of your own categories competes only with generic backgrounds
        key = d.key if d.grp == "custom" else d.grp
        groups.setdefault(key, []).append(d)
    out: dict[str, dict[str, np.ndarray]] = {}
    for gkey, ds in groups.items():
        sims = np.stack([(E @ emb(tuple(d.prompts)).T).max(axis=1) for d in ds], axis=1)
        if ds[0].grp in ABSOLUTE_ONLY:
            absolute = model.prob(sims)
            for i, d in enumerate(ds):
                out[d.key] = {"siglip": absolute[:, i]}
            continue
        bg = BACKGROUND.get(ds[0].grp, GENERIC_BG)
        bg_sims = E @ emb(tuple(bg)).T
        logits = model.scale * np.concatenate([sims, bg_sims], axis=1)
        logits -= logits.max(axis=1, keepdims=True)
        P = np.exp(logits)
        P /= P.sum(axis=1, keepdims=True)
        absolute = model.prob(sims)
        for i, d in enumerate(ds):
            out[d.key] = {"siglip_rel": P[:, i], "siglip": absolute[:, i]}
    return out


GROUPS = [
    ("activity", "Activities"),
    ("mood", "Moods"),
    ("place", "Places"),
    ("people", "People"),
    ("object", "Things"),
    ("pet", "Pets and animals"),
    ("id", "ID documents"),
    ("document", "Documents"),
    ("screenshot", "Screenshots"),
    ("entertainment", "Entertainment"),
    ("custom", "Your categories"),
]


class Taxonomy:
    def __init__(self, ctx: Context):
        self.ctx = ctx
        self.db = ctx.db
        self._lock = threading.RLock()
        labels = ctx.services["labels"]
        labels.seed(BUILTIN)  # type: ignore[attr-defined]

    def start(self) -> None:
        threading.Thread(target=self._maybe_rescore, name="taxonomy", daemon=True).start()

    # ---- definitions ---------------------------------------------------------------
    def defs(self) -> list[LabelDef]:
        out = list(BUILTIN)
        for r in self.db.q("SELECT key, name, grp, prompts FROM labels WHERE builtin=0 AND enabled=1"):
            out.append(LabelDef(r["key"], r["name"], r["grp"], json.loads(r["prompts"] or "[]")))
        return out

    def _maybe_rescore(self) -> None:
        """When the built-in taxonomy changes between versions, re-score from stored embeddings."""
        v = self.db.scalar("SELECT value FROM settings WHERE key='taxonomy.version'")
        if v == str(TAXONOMY_V):
            return
        index = self.ctx.services.get("semantic_index")
        for _ in range(600):  # wait for the embeddings to load
            if index is None or index.ready:  # type: ignore[attr-defined]
                break
            time.sleep(0.2)
        try:
            self.drop_relative_private_scores()
            n = self.rescore(list(BUILTIN))
            with self.db.tx() as c:
                c.execute(
                    "INSERT INTO settings(key, value) VALUES('taxonomy.version', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (str(TAXONOMY_V),),
                )
            log.info("taxonomy v%d scored over %d photos", TAXONOMY_V, n)
        except Exception:
            log.exception("taxonomy rescore failed")

    def drop_relative_private_scores(self) -> int:
        """v3: private content no longer uses relative scores; forget the ones stored since v2."""
        from .labels import SENSITIVE_KEYS

        labels = self.ctx.services["labels"]
        ids = [labels.id(k) for k in SENSITIVE_KEYS]  # type: ignore[attr-defined]
        marks = ",".join("?" * len(ids))
        cur = self.db.x(
            "UPDATE media_labels SET source=json_remove(source, '$.siglip_rel')"
            f" WHERE label_id IN ({marks}) AND json_valid(source) AND json_extract(source, '$.siglip_rel') IS NOT NULL",
            ids,
        )
        n = cur.rowcount or 0
        if n:
            labels.retier("sensitive")  # type: ignore[attr-defined]
            log.info("dropped %d relative private-content scores", n)
        return n

    # ---- scoring -------------------------------------------------------------------
    def rescore(self, defs: list[LabelDef]) -> int:
        """Score categories for every photo and video that already has embeddings."""
        ml = self.ctx.services["ml"]
        model = ml.siglip()  # type: ignore[attr-defined]
        index = self.ctx.services.get("semantic_index")
        if model is None or index is None:
            return 0
        ids, E = index.matrix()  # type: ignore[attr-defined]
        labels = self.ctx.services["labels"]
        # relative scores need the whole group, so score the groups these labels belong to
        grps = {d.grp for d in defs}
        full = [d for d in self.defs() if d.grp in grps and (d.grp != "custom" or d.key in {x.key for x in defs})]
        scores = score_labels(model, E, full) if len(ids) else {}
        mids = ids.tolist()
        for d in full:
            sc = scores.get(d.key)
            if sc is None:
                continue
            personal = self._personal_scores(d.key, E)
            items = []
            for k, mid in enumerate(mids):
                vals = {"siglip_rel": float(sc["siglip_rel"][k]), "siglip": float(sc["siglip"][k])}
                if personal is not None:
                    vals["personal"] = float(personal[k])
                items.append((mid, d.key, vals, d.grp))
            for s in range(0, len(items), 5000):
                labels.record_many(items[s : s + 5000])  # type: ignore[attr-defined]
        self._rescore_videos(full, model, index)
        self.ctx.events.publish("labels.changed", {})
        return len(ids)

    def _rescore_videos(self, defs: list[LabelDef], model, index) -> None:
        """Videos: the same categories over their scene frames (best score in the video, and spans)."""
        from .framelabels import store_spans, video_labels

        owners, times, E = index.frame_matrix()  # type: ignore[attr-defined]
        if len(owners) == 0:
            return
        labels = self.ctx.services["labels"]
        scores = score_labels(model, E, defs)
        for d in defs:
            personal = self._personal_scores(d.key, E) if d.key in scores else None
            if personal is not None:
                scores[d.key]["personal"] = personal
        vids = sorted({int(m) for m in owners})
        ends = {int(r["id"]): int(round((r["duration"] or 0) * 1000)) for r in self.db.q(
            f"SELECT id, duration FROM media WHERE id IN ({','.join('?' * len(vids))})", vids)}
        records, spans = video_labels(labels, defs, scores, owners, times, ends)
        for s in range(0, len(records), 5000):
            labels.record_many(records[s : s + 5000])  # type: ignore[attr-defined]
        store_spans(self.db, labels, spans, [(m, d.key) for m in vids for d in defs if d.key in scores])

    # ---- custom categories ---------------------------------------------------------------
    def create(self, name: str, prompts: list[str]) -> int:
        name = name.strip()
        prompts = [p.strip() for p in prompts if p.strip()] or [name]
        key = "custom." + "".join(ch if ch.isalnum() else "_" for ch in name.lower())[:40] + f"_{int(time.time())}"
        labels = self.ctx.services["labels"]
        labels.seed([LabelDef(key, name, "custom", prompts)])  # type: ignore[attr-defined]
        self.db.x("UPDATE labels SET builtin=0 WHERE key=?", (key,))
        lid = labels.id(key)  # type: ignore[attr-defined]
        threading.Thread(target=self.rescore, args=([LabelDef(key, name, "custom", prompts)],), daemon=True).start()
        self._invalidate_stage()
        return lid

    def update(self, label_id: int, name: str | None, prompts: list[str] | None) -> None:
        r = self.db.q1("SELECT key, name, grp, prompts, builtin FROM labels WHERE id=?", (label_id,))
        if r is None or r["builtin"]:
            raise PermissionError("Built-in categories can't be edited.")
        new_prompts = [p.strip() for p in (prompts or json.loads(r["prompts"] or "[]")) if p.strip()]
        self.db.x("UPDATE labels SET name=?, prompts=? WHERE id=?", (name or r["name"], json.dumps(new_prompts), label_id))
        threading.Thread(target=self.rescore, args=([LabelDef(r["key"], name or r["name"], r["grp"], new_prompts)],), daemon=True).start()
        self._invalidate_stage()

    def delete(self, label_id: int) -> None:
        r = self.db.q1("SELECT builtin FROM labels WHERE id=?", (label_id,))
        if r is None:
            return
        if r["builtin"]:
            raise PermissionError("Built-in categories can't be deleted.")
        with self.db.tx() as c:
            c.execute("DELETE FROM media_labels WHERE label_id=?", (label_id,))
            c.execute("DELETE FROM labels WHERE id=?", (label_id,))
        self._invalidate_stage()
        self.ctx.events.publish("labels.changed", {})

    def _invalidate_stage(self) -> None:
        ix = self.ctx.services.get("indexer")
        if ix is None:
            return
        for st in ix.stages:  # type: ignore[attr-defined]
            if st.name in ("semantic", "video"):
                st.invalidate_prompts()

    # ---- answers and the personal classifier ------------------------------------------------
    def answer(self, label_id: int, yes: list[int], no: list[int]) -> dict[str, int]:
        with self.db.tx() as c:
            for mid in yes:
                c.execute(
                    """INSERT INTO media_labels(media_id, label_id, score, tier, state, source) VALUES(?,?,1,'sure','confirmed','{}')
                       ON CONFLICT(media_id, label_id) DO UPDATE SET state='confirmed'""",
                    (mid, label_id),
                )
            for mid in no:
                c.execute(
                    """INSERT INTO media_labels(media_id, label_id, score, tier, state, source) VALUES(?,?,0,'no','rejected','{}')
                       ON CONFLICT(media_id, label_id) DO UPDATE SET state='rejected'""",
                    (mid, label_id),
                )
        r = self.db.q1("SELECT key, name, grp, prompts FROM labels WHERE id=?", (label_id,))
        learned = 0
        if r is not None and r["grp"] == "id":
            # with "Treat ID documents as private" on, your answer hides or shows the photo
            self.ctx.services["labels"].update_sens_state([*yes, *no])  # type: ignore[attr-defined]
        if r is not None and r["prompts"] not in (None, "", "[]"):
            pos = self.db.scalar("SELECT COUNT(*) FROM media_labels WHERE label_id=? AND state='confirmed'", (label_id,), default=0)
            neg = self.db.scalar("SELECT COUNT(*) FROM media_labels WHERE label_id=? AND state='rejected'", (label_id,), default=0)
            if pos >= 8 and neg >= 8:
                threading.Thread(
                    target=self.rescore, args=([LabelDef(r["key"], r["name"], r["grp"], json.loads(r["prompts"] or "[]"))],), daemon=True
                ).start()
                learned = 1
        self.ctx.events.publish("labels.changed", {})
        return {"answered": len(yes) + len(no), "learning": learned}

    def _personal_scores(self, key: str, E: np.ndarray) -> np.ndarray | None:
        """Probability from a logistic regression trained on your answers for this category."""
        labels = self.ctx.services["labels"]
        try:
            lid = labels.id(key)  # type: ignore[attr-defined]
        except KeyError:
            return None
        rows = self.db.q("SELECT media_id, state FROM media_labels WHERE label_id=? AND state IN ('confirmed','rejected')", (lid,))
        pos = [r["media_id"] for r in rows if r["state"] == "confirmed"]
        neg = [r["media_id"] for r in rows if r["state"] == "rejected"]
        if len(pos) < 8 or len(neg) < 8:
            return None
        index = self.ctx.services["semantic_index"]
        X_pos, X_neg = index.vectors(pos), index.vectors(neg)  # type: ignore[attr-defined]
        X = np.concatenate([X_pos, X_neg])
        y = np.array([1] * len(X_pos) + [0] * len(X_neg))
        if len(set(y)) < 2:
            return None
        from sklearn.linear_model import LogisticRegression

        clf = LogisticRegression(C=1.0, class_weight="balanced", max_iter=500).fit(X, y)
        return clf.predict_proba(E)[:, 1]


def create(ctx: Context) -> Taxonomy:
    return Taxonomy(ctx)
