"""Generates desktop/assets/icon.png, icon.ico and drag.png (run with the engine venv)."""
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "desktop" / "assets"
OUT.mkdir(parents=True, exist_ok=True)

ACCENT = (37, 99, 235, 255)
WHITE = (255, 255, 255, 255)


def icon(size: int) -> Image.Image:
    s = size * 4  # supersample for smooth edges
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    r = int(s * 0.22)
    d.rounded_rectangle([0, 0, s - 1, s - 1], radius=r, fill=ACCENT)
    # lens ring
    cx, cy = s * 0.5, s * 0.5
    R = s * 0.33
    w = max(2, int(s * 0.06))
    d.ellipse([cx - R, cy - R, cx + R, cy + R], outline=WHITE, width=w)
    # person inside the lens: head + shoulders
    hr = s * 0.085
    hy = cy - s * 0.07
    d.ellipse([cx - hr, hy - hr, cx + hr, hy + hr], fill=WHITE)
    sw, sh = s * 0.17, s * 0.11
    sy = cy + s * 0.07
    d.pieslice([cx - sw, sy - sh * 0.2, cx + sw, sy + sh * 1.8], 180, 360, fill=WHITE)
    # clip shoulders to the lens interior
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).ellipse([cx - R + w, cy - R + w, cx + R - w, cy + R - w], fill=255)
    person = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    pd = ImageDraw.Draw(person)
    pd.ellipse([cx - hr, hy - hr, cx + hr, hy + hr], fill=WHITE)
    pd.pieslice([cx - sw, sy - sh * 0.2, cx + sw, sy + sh * 1.8], 180, 360, fill=WHITE)
    base = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    bd = ImageDraw.Draw(base)
    bd.rounded_rectangle([0, 0, s - 1, s - 1], radius=r, fill=ACCENT)
    bd.ellipse([cx - R, cy - R, cx + R, cy + R], outline=WHITE, width=w)
    base.paste(person, (0, 0), Image.composite(person.getchannel("A"), Image.new("L", (s, s), 0), mask))
    return base.resize((size, size), Image.LANCZOS)


big = icon(512)
big.save(OUT / "icon.png")
big.save(OUT / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
icon(32).save(OUT / "drag.png")
print("icons written to", OUT)
