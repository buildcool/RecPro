"""Trips (days away from home), events (celebrations) and On this day."""
from __future__ import annotations

from datetime import date

import numpy as np
from PIL import Image

from recpro import memories
from recpro.api import routes_memories, visibility
from tests.test_places import gps_photo, index_places

PUNE = (18.5204, 73.8567)


def camera_photo(path, when, seed=0):
    """A camera photo with no location (a second camera, or location off)."""
    rng = np.random.default_rng(seed)
    im = Image.fromarray(rng.integers(0, 255, (30, 40, 3), dtype=np.uint8)).resize((640, 480), Image.Resampling.BICUBIC)
    exif = Image.Exif()
    exif[0x010F], exif[0x0110] = "RecProTest", "Camera Two"
    exif.get_ifd(0x8769)[0x9003] = when
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path, quality=90, exif=exif.tobytes())


def library(tmp_path):
    lib = tmp_path / "Lib" / "Camera"
    seed = iter(range(100, 200))
    for day in ("2023:01:02", "2023:01:05", "2023:02:01", "2023:03:01"):  # at home
        gps_photo(lib / f"home-{day[5:7]}{day[8:]}.jpg", *PUNE, when=f"{day} 10:00:00", seed=next(seed))
    for name, lat, lon, when in (  # 4 days across Goa
        ("goa-1.jpg", 15.5439, 73.7553, "2023:01:14 16:30:00"),
        ("goa-2.jpg", 15.5733, 73.7407, "2023:01:15 11:00:00"),
        ("goa-3.jpg", 15.4909, 73.8278, "2023:01:16 10:30:00"),
        ("goa-4.jpg", 15.0100, 74.0232, "2023:01:17 12:00:00"),
        ("sinhagad.jpg", 18.3664, 73.7559, "2023:01:20 12:00:00"),  # 25 km out: a day out, not a trip
        ("lonavla-1.jpg", 18.7546, 73.4062, "2023:01:22 12:00:00"),  # 64 km: a day trip
        ("lonavla-2.jpg", 18.7481, 73.4072, "2023:01:22 15:00:00"),
        ("paris-1.jpg", 48.8584, 2.2945, "2023:06:08 19:00:00"),
        ("paris-2.jpg", 48.8606, 2.3376, "2023:06:09 11:00:00"),
        ("versailles.jpg", 48.8049, 2.1204, "2023:06:10 14:00:00"),
    ):
        gps_photo(lib / name, lat, lon, when=when, seed=next(seed))
    camera_photo(lib / "goa-no-location.jpg", "2023:01:15 20:00:00", seed=next(seed))  # location off, in Goa
    camera_photo(lib / "home-no-location.jpg", "2023:02:01 18:00:00", seed=next(seed))
    return tmp_path / "Lib"


def trips(ctx):
    memories.forget()
    return {t["name"]: t for t in memories.analyse(ctx)["trips"]}


def test_trips_are_the_days_away_from_home(ctx, tmp_path):
    index_places(ctx, library(tmp_path))
    a = memories.analyse(ctx)
    assert a["home"]["name"] == "Pune" and not a["home"]["chosen"]
    assert [t["name"] for t in a["trips"]] == ["Paris", "Lonavla", "Goa"]  # newest first
    goa = next(t for t in a["trips"] if t["name"] == "Goa")  # moved around the state: named after it
    names = {ctx.db.scalar("SELECT name FROM media WHERE id=?", (i,)) for i in goa["ids"]}
    assert names == {"goa-1.jpg", "goa-2.jpg", "goa-3.jpg", "goa-4.jpg", "goa-no-location.jpg"}
    assert goa["days"] == 4 and goa["n"] == 5 and goa["cover"] in goa["ids"]
    paris = next(t for t in a["trips"] if t["name"] == "Paris")  # mostly Paris, a day at Versailles
    assert [x["name"] for x in paris["towns"]] == ["Paris", "Versailles"] and paris["country"] == "France"
    res = routes_memories.memory(key=goa["key"], c=ctx)
    assert [d["date"] for d in res["days"]] == ["2023-01-14", "2023-01-15", "2023-01-16", "2023-01-17"]
    assert res["days"][0]["place"] == "Calangute" and len(res["days"][1]["items"]) == 2
    assert "ids" not in res["memory"]


def test_a_home_you_choose_moves_the_trips(ctx, tmp_path):
    index_places(ctx, library(tmp_path))
    goa_town = ctx.db.scalar("SELECT city_id FROM media WHERE name='goa-1.jpg'")
    ctx.settings.update({"places.home_city_id": goa_town})
    try:
        memories.forget()
        a = memories.analyse(ctx)
        assert a["home"]["name"] == "Calangute" and a["home"]["chosen"]
        got = {t["name"]: t["n"] for t in a["trips"]}
        # Goa is home now; Sinhagad is away too, two days before Lonavla, so it joins that trip.
        # The Pune days are single photos days apart: not trips
        assert got == {"Paris": 3, "Lonavla": 3}
    finally:
        ctx.settings.update({"places.home_city_id": None})


def test_a_private_trip_is_left_out_while_locked(ctx, tmp_path, monkeypatch):
    index_places(ctx, library(tmp_path))
    ctx.db.x("UPDATE media SET sens_state='private' WHERE name IN ('paris-1.jpg', 'paris-2.jpg', 'versailles.jpg')")
    monkeypatch.setattr(visibility, "private_hidden", lambda c: True)
    assert "Paris" not in trips(ctx)
    monkeypatch.setattr(visibility, "private_hidden", lambda c: False)  # unlocked, shown everywhere
    paris = trips(ctx)["Paris"]
    assert paris["n"] == 3 and paris["cover"] is None  # never a private cover


def test_an_event_is_a_celebration_in_a_good_part_of_a_few_hours(ctx, tmp_path):
    lib = tmp_path / "Lib" / "Camera"
    for i in range(8):  # a birthday: 8 shots in 2 hours, the cake in 4 of them
        h, m = divmod(18 * 60 + i * 15, 60)
        camera_photo(lib / f"bday-{i}.jpg", f"2023:03:05 {h:02d}:{m:02d}:00", seed=i)
    for i in range(8):  # a dinner where 2 shots look like a party: not an event
        camera_photo(lib / f"dinner-{i}.jpg", f"2023:03:10 20:{i * 5:02d}:00", seed=50 + i)
    index_places(ctx, tmp_path / "Lib")
    db = ctx.db
    labels = ctx.services["labels"]
    bday, party = labels.id("activity.birthday"), labels.id("activity.party")
    for name, lid in [*((f"bday-{i}.jpg", bday) for i in range(4)), *((f"dinner-{i}.jpg", party) for i in range(2))]:
        mid = db.scalar("SELECT id FROM media WHERE name=?", (name,))
        db.x("INSERT INTO media_labels(media_id, label_id, score, tier, state, source) VALUES(?,?,0.9,'sure','ai','{}')", (mid, lid))
    memories.forget()
    events = memories.analyse(ctx)["events"]
    assert [(e["name"], e["n"]) for e in events] == [("Birthday", 8)]


def test_on_this_day_leaves_out_screenshots_and_private_items(ctx, tmp_path):
    lib = tmp_path / "Lib" / "Camera"
    camera_photo(lib / "a.jpg", "2023:11:07 10:00:00", seed=1)
    camera_photo(lib / "b.jpg", "2021:11:07 09:00:00", seed=2)
    camera_photo(lib / "screenshot.jpg", "2022:11:07 12:00:00", seed=3)
    camera_photo(lib / "private.jpg", "2024:11:07 12:00:00", seed=4)
    camera_photo(lib / "this-year.jpg", "2026:11:07 08:00:00", seed=5)
    camera_photo(lib / "other-day.jpg", "2023:11:08 10:00:00", seed=6)
    index_places(ctx, tmp_path / "Lib")
    db = ctx.db
    shot = db.scalar("SELECT id FROM labels WHERE grp='screenshot' ORDER BY id LIMIT 1")
    db.x("INSERT INTO media_labels(media_id, label_id, score, tier, state, source) VALUES((SELECT id FROM media WHERE name='screenshot.jpg'),?,0.9,'sure','ai','{}')", (shot,))
    db.x("UPDATE media SET sens_state='private' WHERE name='private.jpg'")
    res = memories.on_this_day(ctx, today=date(2026, 11, 7))
    assert [(y["year"], y["years_ago"], y["n"]) for y in res["years"]] == [(2023, 3, 1), (2021, 5, 1)]
    assert res["date"] == "11-07"
