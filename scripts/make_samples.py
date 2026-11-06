"""Creates synthetic sample media for development/testing (no personal data).

Usage: engine/.venv/Scripts/python scripts/make_samples.py <out_dir>
"""
import random
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

from PIL import Image, ImageDraw

out = Path(sys.argv[1] if len(sys.argv) > 1 else ".testdata/samples")
out.mkdir(parents=True, exist_ok=True)
random.seed(7)


def exif_bytes(dt: datetime, orientation: int = 1, model: str = "Pixel 7") -> bytes:
    im = Image.new("RGB", (1, 1))
    ex = im.getexif()
    ex[0x010F] = "Google"
    ex[0x0110] = model
    ex[0x0112] = orientation
    ex[0x0132] = dt.strftime("%Y:%m:%d %H:%M:%S")
    sub = ex.get_ifd(0x8769)
    sub[0x9003] = dt.strftime("%Y:%m:%d %H:%M:%S")
    return ex.tobytes()


def picture(w: int, h: int, seed: int) -> Image.Image:
    rnd = random.Random(seed)
    im = Image.new("RGB", (w, h), tuple(rnd.randint(40, 200) for _ in range(3)))
    d = ImageDraw.Draw(im)
    for _ in range(14):
        x0, y0 = rnd.randint(0, w), rnd.randint(0, h)
        r = rnd.randint(min(w, h) // 20, min(w, h) // 4)
        d.ellipse([x0 - r, y0 - r, x0 + r, y0 + r], fill=tuple(rnd.randint(0, 255) for _ in range(3)))
    return im


base = datetime(2023, 1, 15, 10, 30)
sub = out / "Trips" / "Goa 2023"
sub.mkdir(parents=True, exist_ok=True)
for i in range(24):
    dt = base + timedelta(days=i * 23, hours=i)
    w, h = random.choice([(4000, 3000), (3000, 4000), (1920, 1080)])
    orient = 6 if i % 7 == 0 else 1
    target = sub if i < 8 else out
    picture(w, h, i).save(target / f"IMG_{dt:%Y%m%d_%H%M%S}.jpg", quality=88, exif=exif_bytes(dt, orient))

# screenshot-like PNG without camera EXIF
shot = Image.new("RGB", (1080, 2400), (245, 245, 245))
d = ImageDraw.Draw(shot)
for y in range(200, 2300, 180):
    d.rounded_rectangle([60 if (y // 180) % 2 else 400, y, 680 if (y // 180) % 2 else 1020, y + 120], 30, fill=(220, 248, 198) if (y // 180) % 2 else (255, 255, 255))
shot.save(out / "Screenshot_2024-02-03-21-15-09.png")

# WhatsApp-style name, no EXIF
picture(1280, 960, 99).save(out / "IMG-20240115-WA0001.jpg", quality=80)

# duplicate of one image in another folder
dup = out / "Backup"
dup.mkdir(exist_ok=True)
first = sorted(sub.glob("*.jpg"))[0]
shutil.copy2(first, dup / first.name)

ff = shutil.which("ffmpeg")
if ff:
    for i, (size, dur) in enumerate([("1280x720", 3), ("720x1280", 2)]):
        subprocess.run(
            [ff, "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc=size={size}:rate=25:duration={dur}",
             "-f", "lavfi", "-i", f"sine=frequency=440:duration={dur}", "-shortest",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
             "-metadata", f"creation_time=2023-0{i + 5}-10T12:00:00Z", str(out / f"VID_2023060{i}_120000.mp4")],
            check=True,
        )
print("samples written to", out.resolve())
