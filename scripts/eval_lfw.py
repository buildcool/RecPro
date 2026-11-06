"""End-to-end accuracy check on the LFW test library (development only).

1. Waits for indexing and grouping to finish.
2. Grouping quality: for each true person, the share of their photos in their biggest group
   (completeness) and how clean that group is (purity).
3. Names each person's biggest group, then runs Find for each person:
   recall/precision of "Sure", and recall when "Please check" items are included.
4. Answers the Review questions with the ground truth (like a user would), then measures again.

Usage: engine/.venv/Scripts/python scripts/eval_lfw.py <engine_url> <token> <library_root>
"""
import json
import sqlite3
import sys
import time
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

URL, TOKEN, ROOT = sys.argv[1], sys.argv[2], Path(sys.argv[3])
DB = Path(sys.argv[4]) if len(sys.argv) > 4 else Path(".devdata/recpro.db")
truth = json.loads((ROOT / "truth.json").read_text(encoding="utf-8"))
label_of = {str((ROOT / k).resolve()).lower(): v for k, v in truth["files"].items()}
PEOPLE = truth["people"]


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(URL + path, data=data, method=method, headers={"X-RecPro-Token": TOKEN, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode() or "null")


def db():
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    return c


# 1. wait for analysis + grouping
t0 = time.time()
while True:
    st = call("GET", "/api/index/status")
    deep = st["stages"].get("deep", {})
    if deep and deep["done"] >= deep["total"] and not st["scanning"]:
        break
    print(f"  analyzing… {deep.get('done', 0)}/{deep.get('total', '?')}", end="\r")
    time.sleep(2)
time.sleep(8)  # let the people loop assign and group
print(f"analysis done in {time.time() - t0:.0f}s" + " " * 20)

with db() as c:
    rows = c.execute(
        """SELECT f.id, f.person_id, f.state, m.path FROM faces f JOIN media m ON m.id=f.media_id
           WHERE m.state='active'"""
    ).fetchall()
media_label = {}
groups = defaultdict(list)
for r in rows:
    lab = label_of.get(str(Path(r["path"]).resolve()).lower())
    media_label[r["path"]] = lab
    if r["person_id"] is not None:
        groups[r["person_id"]].append(lab)

# 2. grouping quality
print("\nGrouping (completeness = share of the person's photos in their biggest group, purity = how clean that group is)")
best_group = {}
for p in PEOPLE:
    total = sum(1 for v in truth["files"].values() if v == p)
    cand = sorted(((gid, Counter(labs)[p], len(labs)) for gid, labs in groups.items() if Counter(labs)[p] > 0), key=lambda t: -t[1])
    if not cand:
        print(f"  {p:28s} no group")
        continue
    gid, n_p, n_all = cand[0]
    best_group[p] = gid
    print(f"  {p:28s} completeness {n_p / total:6.1%}  purity {n_p / n_all:6.1%}  groups {len(cand)}")

# 3. name groups and search
for p, gid in best_group.items():
    call("PATCH", f"/api/people/{gid}", {"name": p.replace("_", " "), "merge_if_exists": True})
time.sleep(3)
named = {x["name"]: x["id"] for x in call("GET", "/api/people?named=1")}


def measure(tag):
    print(f"\nFind ({tag}): recall of Sure / Sure+Check, precision of Sure, questions asked")
    tot = Counter()
    for p in PEOPLE:
        pid = named.get(p.replace("_", " "))
        if pid is None:
            continue
        res = call("POST", "/api/search/people", {"people": [pid], "mode": "any"})
        ids_sure = {h["id"] for h in res["sure"]}
        ids_check = {h["id"] for h in res["check"]}
        with db() as c:
            paths = {r["id"]: r["path"] for r in c.execute("SELECT id, path FROM media")}
        lab = lambda i: label_of.get(str(Path(paths[i]).resolve()).lower())  # noqa: E731
        truth_ids = {i for i in paths if lab(i) == p}
        tp_s = len(ids_sure & truth_ids)
        tp_all = len((ids_sure | ids_check) & truth_ids)
        prec = tp_s / len(ids_sure) if ids_sure else 1.0
        print(f"  {p:28s} sure {tp_s / len(truth_ids):6.1%}  +check {tp_all / len(truth_ids):6.1%}  precision {prec:6.1%}  questions {len(ids_check)}")
        tot["truth"] += len(truth_ids)
        tot["tp_s"] += tp_s
        tot["tp_all"] += tp_all
        tot["sure"] += len(ids_sure)
        tot["q"] += len(ids_check)
    print(
        f"  {'ALL':28s} sure {tot['tp_s'] / tot['truth']:6.1%}  +check {tot['tp_all'] / tot['truth']:6.1%}  "
        f"precision {tot['tp_s'] / max(1, tot['sure']):6.1%}  questions {tot['q']}"
    )


measure("before answering questions")

# 4. answer review questions with ground truth
answered = 0
for _ in range(200):
    q = call("GET", "/api/review/faces?limit=24")
    if not q["person"] or not q["items"]:
        break
    pname = q["person"]["name"].replace(" ", "_")
    yes, no = [], []
    with db() as c:
        for it in q["items"]:
            path = c.execute("SELECT path FROM media WHERE id=?", (it["media_id"],)).fetchone()["path"]
            (yes if label_of.get(str(Path(path).resolve()).lower()) == pname else no).append(it["face_id"])
    call("POST", "/api/review/faces/answer", {"person_id": q["person"]["id"], "yes": yes, "no": no})
    answered += len(yes) + len(no)
print(f"\nanswered {answered} review questions with the ground truth")
time.sleep(3)
measure("after answering")
