"""Universal search parsing, the private/children guard, and category thresholds."""
from __future__ import annotations

import time

from recpro.labels import THRESHOLDS, Labels, source_key
from recpro.review.query import parse, run


def _person(ctx, name):
    now = time.time()
    return ctx.db.x("INSERT INTO people(name, kind, created_at, updated_at) VALUES(?, 'human', ?, ?)", (name, now, now)).lastrowid


def test_parse_understands_people_dates_ages_and_text(ctx):
    _person(ctx, "Rohit Sharma")
    p = parse(ctx, "Rohit Sharma and old men in suits at the beach 2023 videos")
    assert [x["name"] for x in p["people"]] == ["Rohit Sharma"]
    assert p["years"] == [2023]
    assert p["kind"] == "video"
    assert p["age"] == (60, 120) and p["gender"] == "male"  # "old" survives "men"
    assert p["text"] == "suits beach"


def test_parse_emotion_and_group_size(ctx):
    p = parse(ctx, "happy group")
    assert p["emotion"] == "happy"
    assert p["size"] == (3, 1000)
    assert p["text"] == ""


def test_category_name_becomes_a_filter(ctx):
    ctx.services["taxonomy"]  # seeds the built-in categories
    p = parse(ctx, "Beach")
    assert [lab["name"] for lab in p["labels"]] == ["Beach"]


def test_private_content_never_combined_with_children(ctx):
    res = run(ctx, "nude girls")
    assert res["refused"]
    assert res["sure"] == [] and res["check"] == []


def test_subjective_groups_need_more_confidence():
    assert source_key("siglip_rel", "mood") == "siglip_rel_strict"
    assert source_key("siglip_rel", "place") == "siglip_rel"
    assert source_key("siglip", "sensitive") == "siglip_sensitive"
    assert Labels.tier_of("siglip_rel", 0.55, "balanced") == "sure"
    assert Labels.tier_of("siglip_rel_strict", 0.55, "balanced") == "check"
    # never-miss always asks at least as early as balanced
    for src, modes in THRESHOLDS.items():
        assert modes["never_miss"][0] <= modes["balanced"][0], src
