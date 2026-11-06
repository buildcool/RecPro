"""Screenshot detection and "which app is this?" from file facts and OCR text."""
from __future__ import annotations

import re

# common phone/desktop screen sizes (portrait and landscape both accepted)
SCREEN_SIZES = {
    (1080, 2400), (1080, 2340), (1080, 2280), (1080, 2220), (1080, 2160), (1080, 1920), (1080, 2412), (1080, 2408),
    (720, 1600), (720, 1520), (720, 1280), (1170, 2532), (1179, 2556), (1284, 2778), (1290, 2796), (1242, 2688),
    (828, 1792), (750, 1334), (1125, 2436), (1440, 3200), (1440, 3120), (1440, 3088), (1440, 2560), (1440, 3040),
    (1220, 2712), (1260, 2800), (1236, 2676), (1080, 2460), (1176, 2480), (1200, 2640),
    (1920, 1080), (2560, 1440), (1366, 768), (1536, 864), (1280, 720), (3840, 2160), (2880, 1800), (2560, 1600),
    (1440, 900), (1600, 900), (1680, 1050), (1920, 1200), (2736, 1824), (2256, 1504), (3000, 2000),
}
NAME_RE = re.compile(r"(?i)(screenshot|screen[ _-]?shot|screen[ _-]?capture|scrn|capture|snip|screen_\d)")

APPS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    # key: (strong signs, weaker signs)
    "whatsapp": (("whatsapp", "end-to-end encrypted", "tap for contact info", "tap here for contact info"), ("typing...", "typing…", "last seen", "forwarded", "voice call", "online")),
    "instagram": (("instagram", "liked by", "view all comments", "reels"), ("followers", "following", "story")),
    "payment": (
        ("upi transaction id", "upi ref", "utr", "phonepe", "google pay", "paytm", "bhim", "payment successful", "paid to", "transaction successful"),
        ("upi", "₹", "debited", "credited", "rs."),
    ),
    "telegram": (("telegram",), ("subscribers", "pinned message")),
    "facebook": (("facebook", "messenger"), ("write a comment", "most relevant")),
    "youtube": (("youtube", "subscribe"), ("views", "shorts")),
    "x_twitter": (("retweet", "reposted", "tweet", "x.com"), ("for you",)),
    "shopping": (("amazon", "flipkart", "myntra", "meesho", "add to cart", "order placed", "out for delivery"), ("delivered", "order #", "your order")),
    "email": (("gmail", "inbox", "compose"), ("reply all", "forward", "to me")),
    "bank_sms": (("a/c", "acct", "available bal", "avl bal", "otp is", "one time password"), ("credited", "debited", "otp")),
    "map": (("google maps", "directions", "your location", "start navigation"), ("km", "min drive")),
}

APP_NAMES = {
    "whatsapp": "WhatsApp",
    "instagram": "Instagram",
    "payment": "Payments",
    "telegram": "Telegram",
    "facebook": "Facebook",
    "youtube": "YouTube",
    "x_twitter": "X (Twitter)",
    "shopping": "Shopping and orders",
    "email": "Email",
    "bank_sms": "Bank messages",
    "map": "Maps",
}
# one category per app; payments and maps share the SigLIP categories of the same name
APP_KEY = {a: f"screenshot.{a}" for a in APPS}
APP_HAS_PROMPTS = ("payment", "map")
# chat apps and social apps also count towards the broader "Chat" and "Social media" categories
APP_ALSO = {
    "whatsapp": "screenshot.chat",
    "telegram": "screenshot.chat",
    "instagram": "screenshot.social",
    "facebook": "screenshot.social",
    "x_twitter": "screenshot.social",
}


def looks_like_screenshot(name: str, ext: str, width: int | None, height: int | None, has_camera: bool) -> float:
    """0..1: file facts that say "screenshot" (no camera, screen-sized, named like one)."""
    score = 0.0
    if NAME_RE.search(name or ""):
        score = max(score, 0.9)
    if width and height and not has_camera:
        if (width, height) in SCREEN_SIZES or (height, width) in SCREEN_SIZES:
            score = max(score, 0.75 if ext.lower() == ".png" else 0.6)
        elif ext.lower() == ".png" and 1.9 <= max(width, height) / max(1, min(width, height)) <= 2.4:
            score = max(score, 0.55)
    return score


def detect_apps(text: str) -> dict[str, float]:
    low = text.lower()
    out: dict[str, float] = {}
    for key, (strong, weak) in APPS.items():
        s = sum(1 for k in strong if k in low)
        w = sum(1 for k in weak if k in low)
        if s:
            out[key] = 0.95
        elif w >= 2:
            out[key] = 0.6
    return out
