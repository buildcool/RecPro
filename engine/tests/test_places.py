"""Places: the town, state and country of each photo from its GPS position, named offline;
places listed, mapped and searched, with private photos left out while locked."""
from __future__ import annotations

import numpy as np
from PIL import Image
from PIL.TiffImagePlugin import IFDRational

from recpro.api import routes_places, visibility
from recpro.jobs.places import PlacesStage
from recpro.library.places import fold, gazetteer
from recpro.review import query
from tests.conftest import add_and_index


def _dms(v):
    v = abs(v)
    d = int(v)
    m = int((v - d) * 60)
    return IFDRational(d, 1), IFDRational(m, 1), IFDRational(round((v - d - m / 60) * 3600 * 1000), 1000)


def gps_photo(path, lat, lon, when="2024:01:15 10:00:00", seed=0):
    rng = np.random.default_rng(seed)
    im = Image.fromarray(rng.integers(0, 255, (30, 40, 3), dtype=np.uint8)).resize((640, 480), Image.Resampling.BICUBIC)
    exif = Image.Exif()
    exif[0x010F], exif[0x0110] = "RecProTest", "Camera Two"
    exif.get_ifd(0x8769)[0x9003] = when
    gps = exif.get_ifd(0x8825)
    gps[1], gps[2] = ("N" if lat >= 0 else "S"), _dms(lat)
    gps[3], gps[4] = ("E" if lon >= 0 else "W"), _dms(lon)
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path, quality=90, exif=exif.tobytes())
    return path


def index_places(ctx, lib):
    add_and_index(ctx, lib)
    PlacesStage(ctx).process(ctx.db.q("SELECT * FROM media WHERE gps_lat IS NOT NULL"))


def test_a_town_belongs_to_the_biggest_place_close_by_in_the_same_state():
    g = gazetteer()

    def where(lat, lon):
        r = g.locate([lat], [lon])[0]
        if r is None:
            return None
        city = g.place(r[1])
        return g.place(r[0]).name, city.name, city.admin1, city.country

    assert where(18.5308, 73.8475)[1:] == ("Pune", "Maharashtra", "India")  # a neighbourhood of Pune
    assert where(15.5439, 73.7553)[1] == "Calangute"  # a beach town 13 km from Panaji keeps its name
    assert where(48.5727, 7.8155)[3] == "Germany"  # Kehl: Strasbourg is just across the border
    assert where(19.2183, 72.9781)[1] == "Thane"  # shown as people there write it, not "Thāne"
    assert where(48.8606, 2.3376)[2] == "Île-de-France"  # accents kept where the script is Latin
    assert where(14.0, 65.0) is None  # far out at sea
    assert fold("Île-de-France") == "ile-de-france" and fold("नमस्ते") != "नमस्ते"


def test_photos_with_gps_get_their_place(ctx, tmp_path):
    lib = tmp_path / "Lib"
    gps_photo(lib / "a.jpg", 15.5439, 73.7553, seed=1)
    gps_photo(lib / "b.jpg", 48.8584, 2.2945, seed=2)
    gps_photo(lib / "c.jpg", 14.0, 65.0, seed=3)
    Image.new("RGB", (64, 64), "white").save(lib / "d.jpg")  # no GPS
    index_places(ctx, lib)
    db = ctx.db
    got = {r["name"]: r["city"] for r in db.q("SELECT m.name, p.name AS city FROM media m LEFT JOIN places p ON p.id=m.city_id")}
    assert got == {"a.jpg": "Calangute", "b.jpg": "Paris", "c.jpg": None, "d.jpg": None}
    assert db.scalar("SELECT COUNT(*) FROM media WHERE place_v=1") == 3  # the photo without GPS isn't looked at
    res = routes_places.places(c=ctx)
    assert [(p["name"], p["admin1"], p["n"]) for p in res["places"]] == [("Calangute", "Goa", 1), ("Paris", "Île-de-France", 1)]
    assert res["located"] == 2 and res["with_gps"] == 3
    dots = routes_places.clusters(cell=10.0, s=-90, w=-180, n=90, e=180, c=ctx)["clusters"]
    assert sorted(d["name"] for d in dots) == ["Calangute", "Paris"] and all(d["n"] == 1 for d in dots)
    paris = next(p for p in res["places"] if p["name"] == "Paris")
    items = routes_places.place_media(city=paris["id"], admin1=None, cc=None, s=None, w=None, n=None, e=None, offset=0, limit=50, c=ctx)
    assert items["total"] == 1 and items["items"][0]["id"] == paris["cover"]


def test_the_biggest_towns_label_the_map():
    res = routes_places.towns(s=18.0, w=73.0, n=19.0, e=74.5, limit=5)["towns"]
    assert len(res) == 5 and res[0]["name"] == "Pune" and res[0]["pop"] >= res[-1]["pop"]


def test_dots_either_side_of_a_grid_line_become_one():
    from collections import Counter

    a = {"lat": 9.6, "lon": 76.0, "n": 3, "best": None, "towns": Counter({1: 3}), "bounds": [9.6, 76.0, 9.6, 76.0]}
    b = {"lat": 10.4, "lon": 76.1, "n": 2, "best": None, "towns": Counter({1: 1, 2: 1}), "bounds": [10.4, 76.1, 10.4, 76.1]}
    far = {"lat": 30.0, "lon": 76.0, "n": 1, "best": None, "towns": Counter({3: 1}), "bounds": [30.0, 76.0, 30.0, 76.0]}
    out = routes_places._merge_close([b, far, a], cell=10.0)
    assert [d["n"] for d in out] == [5, 1]
    # town 1 had photos in both squares: it counts once
    assert len(out[0]["towns"]) == 2 and out[0]["bounds"] == [9.6, 76.0, 10.4, 76.1]


def test_a_private_photo_is_left_out_while_locked(ctx, tmp_path, monkeypatch):
    lib = tmp_path / "Lib"
    gps_photo(lib / "a.jpg", 48.8584, 2.2945, seed=4)
    gps_photo(lib / "b.jpg", 48.8606, 2.3376, when="2024:01:16 10:00:00", seed=5)
    index_places(ctx, lib)
    db = ctx.db
    db.x("UPDATE media SET sens_state='private' WHERE name='b.jpg'")
    public = db.scalar("SELECT id FROM media WHERE name='a.jpg'")
    monkeypatch.setattr(visibility, "private_hidden", lambda c: True)
    res = routes_places.places(c=ctx)
    assert res["places"][0]["n"] == 1 and res["places"][0]["cover"] == public
    assert routes_places.clusters(cell=10.0, s=-90, w=-180, n=90, e=180, c=ctx)["clusters"][0]["n"] == 1
    box = routes_places.place_media(city=None, admin1=None, cc="FR", s=None, w=None, n=None, e=None, offset=0, limit=50, c=ctx)
    assert box["total"] == 1
    monkeypatch.setattr(visibility, "private_hidden", lambda c: False)  # unlocked, shown everywhere
    res = routes_places.places(c=ctx)
    assert res["places"][0]["n"] == 2 and res["places"][0]["cover"] == public  # never a private cover


def test_search_by_place(ctx, tmp_path):
    lib = tmp_path / "Lib"
    gps_photo(lib / "calangute.jpg", 15.5439, 73.7553, when="2023:01:14 16:30:00", seed=6)
    gps_photo(lib / "panjim.jpg", 15.4909, 73.8278, when="2023:01:16 10:30:00", seed=7)
    gps_photo(lib / "paris.jpg", 48.8584, 2.2945, when="2023:06:08 19:00:00", seed=8)
    gps_photo(lib / "goa-2024.jpg", 15.5733, 73.7407, when="2024:02:01 11:00:00", seed=9)
    index_places(ctx, lib)

    def names(q):
        res = query.run(ctx, q)
        return sorted(ctx.db.scalar("SELECT name FROM media WHERE id=?", (x["id"],)) for x in res["sure"] + res["check"])

    p = query.parse(ctx, "Goa trip 2023")
    assert [x["name"] for x in p["places"]] == ["Goa"] and p["years"] == [2023] and p["text"] == ""
    assert names("Goa trip 2023") == ["calangute.jpg", "panjim.jpg"]
    assert names("goa") == ["calangute.jpg", "goa-2024.jpg", "panjim.jpg"]
    assert names("Calangute") == ["calangute.jpg"]
    assert names("ile-de-france") == ["paris.jpg"]  # no accents needed
    assert names("paris 2024") == []
    assert names("India or France") == ["calangute.jpg", "goa-2024.jpg", "panjim.jpg", "paris.jpg"]
