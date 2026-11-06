"""Text in photos: ID rules, number masking, screenshot checks, and the text pass end to end.

Every ID number here is synthetic: random digits with a valid checksum, or the ICAO 9303
specimen passport ("Anna Maria Eriksson" of Utopia). No real document is used.
"""
from __future__ import annotations

import random

import numpy as np
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from recpro.api.app import create_app
from recpro.ids import detect_ids, mask_ids, mrz_check, verhoeff_ok
from recpro.jobs.text import TextStage, wants_text
from recpro.screens import detect_apps, looks_like_screenshot
from tests.conftest import add_and_index

# Verhoeff tables, to make test numbers with a valid check digit
_D = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 2, 3, 4, 0, 6, 7, 8, 9, 5], [2, 3, 4, 0, 1, 7, 8, 9, 5, 6], [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
      [4, 0, 1, 2, 3, 9, 5, 6, 7, 8], [5, 9, 8, 7, 6, 0, 4, 3, 2, 1], [6, 5, 9, 8, 7, 1, 0, 4, 3, 2], [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
      [8, 7, 6, 5, 9, 3, 2, 1, 0, 4], [9, 8, 7, 6, 5, 4, 3, 2, 1, 0]]
_P = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 5, 7, 6, 2, 8, 3, 0, 9, 4], [5, 8, 0, 3, 7, 9, 6, 1, 4, 2], [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
      [9, 4, 5, 3, 1, 2, 6, 8, 7, 0], [4, 2, 8, 6, 5, 7, 3, 9, 0, 1], [2, 7, 9, 3, 8, 0, 6, 4, 1, 5], [7, 0, 4, 6, 9, 1, 3, 2, 5, 8]]
_INV = [0, 4, 3, 2, 1, 5, 6, 7, 8, 9]


def fake_aadhaar(seed: int) -> str:
    rnd = random.Random(seed)
    body = str(rnd.randint(2, 9)) + "".join(str(rnd.randint(0, 9)) for _ in range(10))
    c = 0
    for i, ch in enumerate(reversed(body)):
        c = _D[c][_P[(i + 1) % 8][int(ch)]]
    return body + str(_INV[c])


def spaced(n: str) -> str:
    return f"{n[:4]} {n[4:8]} {n[8:]}"


def broken(n: str) -> str:
    """Same number with the last digit changed: the checksum no longer matches."""
    return n[:-1] + str((int(n[-1]) + 1) % 10)


MRZ1 = "P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<"
MRZ2 = "L898902C36UTO7408122F1204159ZE184226B<<<<<10"


# ---- checksums -----------------------------------------------------------------------------
def test_verhoeff_accepts_valid_numbers_and_catches_typos():
    for seed in range(20):
        n = fake_aadhaar(seed)
        assert verhoeff_ok(n)
        assert not verhoeff_ok(broken(n))
        swapped = n[:5] + n[6] + n[5] + n[7:]
        if swapped != n:
            assert not verhoeff_ok(swapped), "Verhoeff catches swapped neighbouring digits"


def test_mrz_check_digits_on_the_icao_specimen():
    assert mrz_check("L898902C3", "6")
    assert mrz_check("740812", "2")
    assert mrz_check("120415", "9")
    assert not mrz_check("L898902C3", "5")


# ---- ID rules ------------------------------------------------------------------------------
def kinds(text: str) -> dict[str, float]:
    return {h.kind: h.score for h in detect_ids(text)}


def test_aadhaar_needs_number_and_words_for_sure():
    n = fake_aadhaar(1)
    card = f"GOVERNMENT OF INDIA\nTest Person\nDOB: 01/01/1990\nMale\n{spaced(n)}\nAadhaar - Unique Identification"
    hits = detect_ids(card)
    assert [(h.kind, h.score) for h in hits] == [("aadhaar", 1.0)] and hits[0].numbers == [n]
    # the number alone: please check
    assert kinds(f"ref {spaced(n)}") == {"aadhaar": 0.6}
    # a misread digit still lands in "please check" because the card's words are there
    assert kinds(card.replace(spaced(n), spaced(broken(n)))) == {"aadhaar": 0.6}
    # a masked Aadhaar printout with its words is sure
    assert kinds("Unique Identification Authority of India\nAadhaar no. XXXX XXXX 4821\nDOB 1990")["aadhaar"] == 1.0


def test_words_alone_only_count_on_something_card_like():
    assert kinds("Link your Aadhaar with your bank account before 31 March to keep using UPI.") == {}
    assert kinds("Income Tax Department: your refund has been processed.") == {}
    assert kinds("Aadhaar\nName: Test Person\nDOB: 01/01/1990\nMale")["aadhaar"] == 0.6


def test_pan_card():
    card = "INCOME TAX DEPARTMENT\nGOVT. OF INDIA\nPermanent Account Number\nABCPE1234F\nTEST PERSON\nDate of Birth 01/01/1990"
    assert kinds(card) == {"pan": 1.0}
    assert kinds("PAN: ABCPE1234F") == {"pan": 0.6}
    # 4th letter must be a holder type (P, C, H, F, A, T, B, L, J, G)
    assert "pan" not in kinds("ABCXE1234F")
    # a GSTIN contains a PAN, but isn't a PAN card
    assert "pan" not in kinds("GSTIN 27ABCPE1234F1Z5")


def test_passport_machine_readable_zone():
    text = f"REPUBLIC OF UTOPIA\nPASSPORT\n{MRZ1}\n{MRZ2}"
    assert kinds(text)["passport"] == 1.0
    # check digits alone are enough even when OCR missed the printed words
    assert kinds(MRZ2)["passport"] == 1.0
    bad = MRZ2.replace("7408122", "7408123")
    assert "passport" not in kinds(bad)


def test_driving_licence_and_voter_id():
    assert kinds("Driving Licence\nDL No: MH12 20110012345\nDOB: 01-01-1990")["dl"] == 1.0
    assert kinds("MH12 20110012345")["dl"] == 0.6
    assert kinds("ELECTION COMMISSION OF INDIA\nIdentity Card\nABC1234567\nElector's Name: Test")["voter"] == 1.0
    assert "voter" not in kinds("Order ABC1234567 shipped")


def test_masking_keeps_only_the_last_four():
    n = fake_aadhaar(2)
    text = f"Aadhaar {spaced(n)}\nPAN ABCPE1234F\nDL MH12 20110012345\nEPIC ABC1234567"
    m = mask_ids(text)
    assert n not in m.replace(" ", "") and spaced(n) not in m
    assert f"XXXX XXXX {n[8:]}" in m
    assert "ABCPE1234F" not in m and "234F" in m
    assert "20110012345" not in m and "ABC1234567" not in m
    # grouped like an Aadhaar: hidden even when a misread digit breaks the checksum
    assert spaced(broken(n)) not in mask_ids(f"Aadhaar {spaced(broken(n))}")
    # an ordinary 12-digit reference (no groups, no checksum) stays searchable
    ref = broken(fake_aadhaar(3))
    assert ref in mask_ids(f"UPI Ref No {ref}")
    # passports: number and machine-readable lines
    p = mask_ids(f"PASSPORT\nPassport No. J8369854\n{MRZ1}\n{MRZ2}")
    assert "J8369854" not in p and "L898902C3" not in p and "ERIKSSON" not in p


# ---- screenshots ---------------------------------------------------------------------------
def test_screenshot_file_facts():
    assert looks_like_screenshot("Screenshot_20240512-201530_WhatsApp.png", ".png", 1080, 2400, False) == 0.9
    assert looks_like_screenshot("IMG_1234.png", ".png", 1080, 2400, False) == 0.75
    assert looks_like_screenshot("IMG_1234.jpg", ".jpg", 1080, 2400, False) == 0.6
    assert looks_like_screenshot("IMG_1234.jpg", ".jpg", 1080, 2400, True) == 0.0, "camera photos aren't screenshots"
    assert looks_like_screenshot("IMG_1234.jpg", ".jpg", 4000, 3000, False) == 0.0


def test_app_detection():
    chat = "WhatsApp\nTest Friend typing...\nHey, are you coming tonight?\nMessages are end-to-end encrypted"
    assert detect_apps(chat)["whatsapp"] == 0.95
    pay = "Payment Successful\nRs 1,250.00\nPaid to Test Shop\nUPI Transaction ID: 412345678901"
    assert detect_apps(pay)["payment"] == 0.95
    assert detect_apps("A quiet evening by the lake") == {}


def test_which_photos_get_read():
    assert wants_text({"doc": 0.12}, 0.0) == (True, False)
    assert wants_text({"doc": 0.6}, 0.0) == (True, True), "likely documents are also tried rotated"
    assert wants_text({}, 0.9)[0], "named like a screenshot"
    assert not wants_text({"screen": 0.1, "other": 0.2}, 0.0)[0]
    assert wants_text({"other": 0.35}, 0.0)[0], "memes and greetings with clear scores"
    assert not wants_text({}, 0.0)[0]


# ---- the text pass end to end -----------------------------------------------------------------
class FakeOCR:
    """Stands in for PaddleOCR: tall images read as a chat, wide ones as an ID card."""

    def __init__(self, card_text: str, chat_text: str):
        self.card_text, self.chat_text = card_text, chat_text
        self.calls = 0

    def read(self, img: np.ndarray):
        self.calls += 1
        return ["tall"] if img.shape[0] > img.shape[1] else ["wide"]

    def text_of(self, lines) -> str:
        return self.chat_text if lines == ["tall"] else self.card_text


def _make_files(root):
    root.mkdir(parents=True)
    im = Image.new("RGB", (1080, 2400), (236, 229, 221))
    ImageDraw.Draw(im).rectangle([0, 0, 1080, 220], fill=(7, 94, 84))
    im.save(root / "Screenshot_20240512-201530.png")
    Image.effect_noise((700, 440), 40).convert("RGB").save(root / "IMG_20240105_090000.jpg", quality=90)
    Image.effect_noise((640, 480), 40).convert("RGB").save(root / "IMG_20240106_120000.jpg", quality=90)


def test_text_pass_finds_ids_and_apps_and_masks_numbers(ctx, tmp_path, monkeypatch):
    root = tmp_path / "Phone"
    _make_files(root)
    add_and_index(ctx, root)
    n = fake_aadhaar(4)
    card = f"GOVERNMENT OF INDIA\nTest Person\nDOB: 01/01/1990\nMale\n{spaced(n)}\nAadhaar - Unique Identification"
    chat = "WhatsApp\nTest Friend typing...\nAre you coming to the party tonight?\nMessages are end-to-end encrypted"
    fake = FakeOCR(card, chat)
    ml = ctx.services["ml"]
    monkeypatch.setattr(ml, "ocr", lambda: fake)
    labels = ctx.services["labels"]
    db = ctx.db
    card_id = db.scalar("SELECT id FROM media WHERE name='IMG_20240105_090000.jpg'")
    shot_id = db.scalar("SELECT id FROM media WHERE name LIKE 'Screenshot%'")
    plain_id = db.scalar("SELECT id FROM media WHERE name='IMG_20240106_120000.jpg'")
    # what the semantic pass would have said: the card looks like an ID card; the other photo only
    # looks a little like a video call, which doesn't make it worth reading
    labels.record_many([
        (card_id, "document.id_card", {"siglip_rel": 0.6}, "document"),
        (plain_id, "screenshot.video_call", {"siglip_rel": 0.4}, "screenshot"),
    ])

    TextStage(ctx).process(db.q("SELECT * FROM media ORDER BY id"))

    def tier(mid: int, key: str) -> str | None:
        return db.scalar(
            "SELECT ml.tier FROM media_labels ml JOIN labels l ON l.id=ml.label_id WHERE ml.media_id=? AND l.key=?", (mid, key)
        )

    assert tier(card_id, "id.aadhaar") == "sure"
    assert tier(shot_id, "screenshot.screenshot") == "sure"
    assert tier(shot_id, "screenshot.whatsapp") == "sure" and tier(shot_id, "screenshot.chat") == "sure"
    assert tier(plain_id, "id.aadhaar") is None
    assert fake.calls == 2, "a photo with nothing text-like isn't read"
    # stored text is searchable, with the ID number masked
    stored = db.scalar("SELECT content FROM texts WHERE media_id=?", (card_id,))
    assert n not in stored.replace(" ", "") and f"XXXX XXXX {n[8:]}" in stored
    hits = {r[0] for r in db.q("SELECT media_id FROM texts WHERE texts MATCH ?", ('"party tonight"',))}
    assert hits == {shot_id}
    assert db.scalar("SELECT text_v FROM media WHERE id=?", (plain_id,)) == 1

    # ID documents appear in Explore under their own group
    client = TestClient(create_app(ctx))
    h = {"X-RecPro-Token": "test-token", "host": "127.0.0.1"}
    groups = {g["key"]: g for g in client.get("/api/explore", headers=h).json()}
    assert [l["key"] for l in groups["id"]["labels"]] == ["id.aadhaar"]

    # "Treat ID documents as private": hidden while on, back when off
    ctx.settings.update({"privacy.ids_private": True})
    labels.refresh_id_privacy()
    assert db.scalar("SELECT sens_state FROM media WHERE id=?", (card_id,)) == "private"
    assert db.scalar("SELECT sens_state FROM media WHERE id=?", (shot_id,)) != "private"
    assert "id" not in {g["key"] for g in client.get("/api/explore", headers=h).json()}
    p = ctx.services["private"]
    p.setup("2468", "pin")
    assert p.state()["counts"]["ids"] == 1
    r = client.get("/api/timeline?private_only=true&label_grp=id", headers=h).json()
    assert r["total"] == 1
    ctx.settings.update({"privacy.ids_private": False})
    labels.refresh_id_privacy()
    assert db.scalar("SELECT sens_state FROM media WHERE id=?", (card_id,)) == "clear"


def test_rejecting_an_id_label_brings_the_photo_back(ctx, tmp_path, monkeypatch):
    root = tmp_path / "Phone"
    _make_files(root)
    add_and_index(ctx, root)
    ctx.settings.update({"privacy.ids_private": True})
    labels = ctx.services["labels"]
    db = ctx.db
    mid = db.scalar("SELECT id FROM media WHERE name='IMG_20240106_120000.jpg'")
    labels.record_many([(mid, "id.pan", {"ocr": 1.0}, "id")])
    labels.update_sens_state([mid])
    assert db.scalar("SELECT sens_state FROM media WHERE id=?", (mid,)) == "private"
    ctx.services["taxonomy"].answer(labels.id("id.pan"), [], [mid])
    assert db.scalar("SELECT sens_state FROM media WHERE id=?", (mid,)) == "clear"
    _ = monkeypatch
