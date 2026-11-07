"""Cleanup test photos made from public LFW photos (development only).

    engine/.venv/Scripts/python -I scripts/make_cleanup_samples.py .testdata/lfw/lfw.tgz .testdata/cleanup-samples

Camera/       originals with camera EXIF: a burst of 3 shots 1 s apart (one shaky), and singles
Backup/       exact copies of two originals
WhatsApp Images/  a smaller, recompressed copy of an original with WhatsApp's name, and a forward
Dark/, Blurry/    very dark and badly blurred versions of other photos
truth.json records what each group should be.
"""
import io
import json
import shutil
import sys
import tarfile
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter

tgz, out = Path(sys.argv[1]), Path(sys.argv[2])
PICK = {
    "burst": "lfw/Tony_Blair/Tony_Blair_0100.jpg",
    "single1": "lfw/Hugo_Chavez/Hugo_Chavez_0060.jpg",
    "single2": "lfw/Jean_Chretien/Jean_Chretien_0050.jpg",
    "dark": "lfw/John_Ashcroft/John_Ashcroft_0050.jpg",
    "blurry": "lfw/Ariel_Sharon/Ariel_Sharon_0070.jpg",
    "forward": "lfw/Junichiro_Koizumi/Junichiro_Koizumi_0055.jpg",
}
photos: dict[str, Image.Image] = {}
with tarfile.open(tgz) as tf:
    want = {v: k for k, v in PICK.items()}
    for m in tf:
        if m.name in want:
            photos[want[m.name]] = Image.open(io.BytesIO(tf.extractfile(m).read())).convert("RGB")
missing = set(PICK) - set(photos)
if missing:
    sys.exit(f"not in the archive: {sorted(missing)}")


def big(im: Image.Image) -> Image.Image:
    return im.resize((1000, 1000), Image.Resampling.LANCZOS)


def save(im: Image.Image, path: Path, when: str | None = None, quality: int = 92) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    kw = {"quality": quality}
    if when:
        exif = Image.Exif()
        exif[0x010F] = "RecProTest"  # Make
        exif[0x0110] = "Camera One"  # Model
        exif.get_ifd(0x8769)[0x9003] = when  # DateTimeOriginal
        kw["exif"] = exif.tobytes()
    im.save(path, **kw)
    return path


if out.exists():
    shutil.rmtree(out)
cam = out / "Camera"
scene = big(photos["burst"])
b1 = save(scene.crop((40, 40, 940, 940)), cam / "IMG_5001.jpg", "2024:05:04 10:00:01")
save(scene.crop((70, 55, 970, 955)), cam / "IMG_5002.jpg", "2024:05:04 10:00:02")
save(scene.crop((90, 70, 990, 990)).filter(ImageFilter.GaussianBlur(6)), cam / "IMG_5003.jpg", "2024:05:04 10:00:03")
s1 = save(big(photos["single1"]), cam / "IMG_5101.jpg", "2024:05:05 18:30:00")
s2 = save(big(photos["single2"]), cam / "IMG_5102.jpg", "2024:05:06 09:15:00")
(out / "Backup").mkdir(parents=True)
shutil.copy2(s1, out / "Backup" / "IMG_5101.jpg")
shutil.copy2(s2, out / "Backup" / "IMG_5102 copy.jpg")
wa = out / "WhatsApp Images"
save(Image.open(s1).resize((480, 480), Image.Resampling.LANCZOS), wa / "IMG-20240505-WA0004.jpg", quality=60)
save(photos["forward"], wa / "IMG-20240507-WA0010.jpg", quality=70)
save(ImageEnhance.Brightness(big(photos["dark"])).enhance(0.06), out / "Dark" / "IMG_5201.jpg", "2024:05:08 22:00:00")
save(big(photos["blurry"]).filter(ImageFilter.GaussianBlur(14)), out / "Blurry" / "IMG_5301.jpg", "2024:05:09 12:00:00")
truth = {
    "exact": [["Camera/IMG_5101.jpg", "Backup/IMG_5101.jpg"], ["Camera/IMG_5102.jpg", "Backup/IMG_5102 copy.jpg"]],
    "copies": [["Camera/IMG_5101.jpg", "WhatsApp Images/IMG-20240505-WA0004.jpg"]],
    "bursts": [["Camera/IMG_5001.jpg", "Camera/IMG_5002.jpg", "Camera/IMG_5003.jpg"]],
    "dark": ["Dark/IMG_5201.jpg"],
    "blurry": ["Blurry/IMG_5301.jpg", "Camera/IMG_5003.jpg"],
    "forwards": ["WhatsApp Images/IMG-20240505-WA0004.jpg", "WhatsApp Images/IMG-20240507-WA0010.jpg"],
    "keep_in_burst": "Camera/IMG_5001.jpg or Camera/IMG_5002.jpg (not the shaky IMG_5003.jpg)",
}
(out / "truth.json").write_text(json.dumps(truth, indent=1), encoding="utf-8")
print("written to", out.resolve())
