"""Indian ID document detection from OCR text, plus masking of the numbers.

Each rule combines a structural check (format, checksum) with keywords printed on the card:
both together mean "sure"; only one means "please check". Stored text keeps only the last 4
characters of any ID number.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# ---- Verhoeff (Aadhaar check digit) -----------------------------------------------------
_D = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 2, 3, 4, 0, 6, 7, 8, 9, 5], [2, 3, 4, 0, 1, 7, 8, 9, 5, 6], [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
      [4, 0, 1, 2, 3, 9, 5, 6, 7, 8], [5, 9, 8, 7, 6, 0, 4, 3, 2, 1], [6, 5, 9, 8, 7, 1, 0, 4, 3, 2], [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
      [8, 7, 6, 5, 9, 3, 2, 1, 0, 4], [9, 8, 7, 6, 5, 4, 3, 2, 1, 0]]
_P = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 5, 7, 6, 2, 8, 3, 0, 9, 4], [5, 8, 0, 3, 7, 9, 6, 1, 4, 2], [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
      [9, 4, 5, 3, 1, 2, 6, 8, 7, 0], [4, 2, 8, 6, 5, 7, 3, 9, 0, 1], [2, 7, 9, 3, 8, 0, 6, 4, 1, 5], [7, 0, 4, 6, 9, 1, 3, 2, 5, 8]]


def verhoeff_ok(num: str) -> bool:
    c = 0
    for i, ch in enumerate(reversed(num)):
        c = _D[c][_P[i % 8][int(ch)]]
    return c == 0


# ---- MRZ check digits (passports, ICAO 9303) ------------------------------------------------
def _mrz_val(ch: str) -> int:
    if ch.isdigit():
        return int(ch)
    if ch == "<":
        return 0
    return ord(ch) - 55  # A=10 … Z=35


def mrz_check(field: str, digit: str) -> bool:
    if not digit.isdigit():
        return False
    w = (7, 3, 1)
    return sum(_mrz_val(c) * w[i % 3] for i, c in enumerate(field)) % 10 == int(digit)


ID_NAMES = {"aadhaar": "Aadhaar", "pan": "PAN card", "passport": "Passport", "dl": "Driving licence", "voter": "Voter ID"}


@dataclass
class IdHit:
    kind: str  # aadhaar | pan | passport | dl | voter
    score: float  # 1.0 sure-grade, 0.6 needs a check
    numbers: list[str]


AADHAAR_RE = re.compile(r"(?<!\d)([2-9]\d{3})[ \-]?(\d{4})[ \-]?(\d{4})(?!\d)")
AADHAAR_MASKED_RE = re.compile(r"(?i)(?<![\w])[x*]{4}[ \-]?[x*]{4}[ \-]?(\d{4})(?!\d)")
PAN_RE = re.compile(r"(?<![A-Z0-9])([A-Z]{3}[PCHFATBLJG][A-Z]\d{4}[A-Z])(?![A-Z0-9])")
PASSPORT_NO_RE = re.compile(r"(?<![A-Z0-9])([A-Z][0-9]{7})(?![A-Z0-9])")
MRZ1_RE = re.compile(r"P[<A-Z][A-Z<]{3}[A-Z<]{30,40}")
MRZ2_RE = re.compile(r"([A-Z0-9<]{9})([0-9<])([A-Z<]{3})(\d{6})(\d)([MF<])(\d{6})(\d)")
DL_RE = re.compile(r"(?<![A-Z0-9])([A-Z]{2})[ \-]?(\d{2})[ \-]?((?:19|20)\d{2})[ \-]?(\d{7})(?!\d)")
DL_OLD_RE = re.compile(r"(?<![A-Z0-9])([A-Z]{2}[ \-]?\d{2}[ \-/]?\d{6,11})(?![A-Z0-9])")
EPIC_RE = re.compile(r"(?<![A-Z0-9])([A-Z]{3}\d{7})(?![A-Z0-9])")

KW = {
    "aadhaar": ("aadhaar", "aadhar", "आधार", "uidai", "unique identification", "enrolment no", "enrollment no", "mera aadhaar", "vid :", "vid:"),
    "gov": ("government of india", "govt. of india", "govt of india", "भारत सरकार"),
    "pan": ("income tax department", "permanent account number", "आयकर विभाग", "स्थायी लेखा संख्या"),
    "passport": ("passport", "पासपोर्ट", "republic of india", "type p", "country code ind"),
    "dl": ("driving licence", "driving license", "driving licence no", "dl no", "transport department", "motor vehicles", "form 7", "licence to drive"),
    "voter": ("election commission of india", "elector", "भारत निर्वाचन आयोग", "electoral", "epic no", "matdata"),
}


# printed on cards next to the holder's details; a keyword alone (no number) only counts on
# something that looks like a card, not on a news article or an SMS that mentions "Aadhaar"
CARD_WORDS = ("dob", "d.o.b", "date of birth", "year of birth", "male", "female", "gender", "address", "father",
              "जन्म", "पुरुष", "महिला", "पिता", "पता")


def _has(text_low: str, key: str) -> bool:
    return any(k in text_low for k in KW[key])


def _cardish(text_low: str) -> bool:
    return any(w in text_low for w in CARD_WORDS)


def detect_ids(text: str) -> list[IdHit]:
    up = text.upper()
    low = text.lower()
    card = _cardish(low)
    hits: list[IdHit] = []
    # Aadhaar: 12 digits that pass Verhoeff (random 12-digit numbers pass 10% of the time,
    # so a keyword is needed for "sure"); masked Aadhaar (XXXX XXXX 1234) with a keyword
    nums = ["".join(m.groups()) for m in AADHAAR_RE.finditer(text)]
    valid = [n for n in nums if verhoeff_ok(n)]
    kw = _has(low, "aadhaar") or (_has(low, "gov") and ("dob" in low or "year of birth" in low or "जन्म" in text))
    if valid:
        hits.append(IdHit("aadhaar", 1.0 if kw else 0.6, valid))
    elif kw and AADHAAR_MASKED_RE.search(text):
        hits.append(IdHit("aadhaar", 1.0, []))
    elif _has(low, "aadhaar") and card:
        hits.append(IdHit("aadhaar", 0.6, []))
    # PAN: 5 letters (4th = holder type), 4 digits, 1 letter
    pans = PAN_RE.findall(up)
    if pans:
        hits.append(IdHit("pan", 1.0 if _has(low, "pan") else 0.6, pans))
    elif _has(low, "pan") and card:
        hits.append(IdHit("pan", 0.6, []))
    # Passport: machine-readable zone with valid check digits is enough on its own
    compact = up.replace(" ", "")
    mrz_ok = False
    for m in MRZ2_RE.finditer(compact):
        doc, d1, _, dob, d2, _, exp, d3 = m.groups()
        if mrz_check(doc, d1) and mrz_check(dob, d2) and mrz_check(exp, d3):
            mrz_ok = True
    if mrz_ok or (MRZ1_RE.search(compact) and _has(low, "passport")):
        hits.append(IdHit("passport", 1.0, PASSPORT_NO_RE.findall(up)[:2]))
    elif _has(low, "passport") and PASSPORT_NO_RE.search(up):
        hits.append(IdHit("passport", 0.6, PASSPORT_NO_RE.findall(up)[:2]))
    # Driving licence: state code, RTO, year of issue, 7-digit serial
    dls = ["".join(m.groups()) for m in DL_RE.finditer(up)]
    if _has(low, "dl") and (dls or DL_OLD_RE.search(up)):
        hits.append(IdHit("dl", 1.0, dls))
    elif dls or (_has(low, "dl") and card):
        hits.append(IdHit("dl", 0.6, dls))
    # Voter ID (EPIC: 3 letters, 7 digits)
    epics = EPIC_RE.findall(up)
    if _has(low, "voter") and (epics or card):
        hits.append(IdHit("voter", 1.0 if epics else 0.6, epics))
    return hits


def mask_ids(text: str) -> str:
    """Keeps only the last 4 characters of ID numbers found in the text.

    Errs towards hiding: any 12-digit number printed in groups of four (the Aadhaar layout, also
    the first 12 digits of a 16-digit VID or card number) is masked even when OCR misread a digit
    and the checksum fails.
    """

    def tail(m: re.Match, keep: int = 4) -> str:
        s = m.group(0)
        chars = [i for i, ch in enumerate(s) if ch.isalnum()]
        hide = set(chars[:-keep]) if len(chars) > keep else set()
        return "".join("X" if i in hide else ch for i, ch in enumerate(s))

    def aadhaar(m: re.Match) -> str:
        grouped = not m.group(0).isdigit()
        return tail(m) if grouped or verhoeff_ok("".join(m.groups())) else m.group(0)

    low = text.lower()
    text = AADHAAR_RE.sub(aadhaar, text)
    text = PAN_RE.sub(tail, text)
    text = DL_RE.sub(tail, text)
    text = EPIC_RE.sub(tail, text)
    if _has(low, "passport") or MRZ1_RE.search(text.upper().replace(" ", "")):
        text = PASSPORT_NO_RE.sub(tail, text)
    # machine-readable zone lines (passports): long runs of A-Z, 0-9 and <
    text = re.sub(r"(?m)^[A-Z0-9< ]{30,}$", lambda m: tail(m, 4) if m.group(0).count("<") >= 3 else m.group(0), text)
    return text
