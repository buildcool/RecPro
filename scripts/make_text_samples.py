"""Synthetic text images for testing OCR, ID and screenshot rules (development only).

Everything is fake and marked SPECIMEN; ID numbers are random with valid checksums.
Usage: engine/.venv/Scripts/python -I scripts/make_text_samples.py <out_dir>
"""
import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

out = Path(sys.argv[1] if len(sys.argv) > 1 else ".testdata/text-samples")
out.mkdir(parents=True, exist_ok=True)
random.seed(11)
FONTS = Path("C:/Windows/Fonts")


def font(size: int, name: str = "arial.ttf") -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(str(FONTS / name), size)
    except OSError:
        return ImageFont.load_default()


# Verhoeff tables (Aadhaar check digit)
D = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 2, 3, 4, 0, 6, 7, 8, 9, 5], [2, 3, 4, 0, 1, 7, 8, 9, 5, 6], [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
     [4, 0, 1, 2, 3, 9, 5, 6, 7, 8], [5, 9, 8, 7, 6, 0, 4, 3, 2, 1], [6, 5, 9, 8, 7, 1, 0, 4, 3, 2], [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
     [8, 7, 6, 5, 9, 3, 2, 1, 0, 4], [9, 8, 7, 6, 5, 4, 3, 2, 1, 0]]
P = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 5, 7, 6, 2, 8, 3, 0, 9, 4], [5, 8, 0, 3, 7, 9, 6, 1, 4, 2], [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
     [9, 4, 5, 3, 1, 2, 6, 8, 7, 0], [4, 2, 8, 6, 5, 7, 3, 9, 0, 1], [2, 7, 9, 3, 8, 0, 6, 4, 1, 5], [7, 0, 4, 6, 9, 1, 3, 2, 5, 8]]
INV = [0, 4, 3, 2, 1, 5, 6, 7, 8, 9]


def verhoeff_digit(num: str) -> int:
    c = 0
    for i, ch in enumerate(reversed(num)):
        c = D[c][P[(i + 1) % 8][int(ch)]]
    return INV[c]


def fake_aadhaar() -> str:
    body = str(random.randint(2, 9)) + "".join(str(random.randint(0, 9)) for _ in range(10))
    n = body + str(verhoeff_digit(body))
    return f"{n[:4]} {n[4:8]} {n[8:]}"


def fake_pan() -> str:
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    return "".join(random.choice(letters) for _ in range(3)) + "P" + random.choice(letters) + f"{random.randint(0, 9999):04d}" + random.choice(letters)


# WhatsApp-style chat screenshot
im = Image.new("RGB", (1080, 2400), (236, 229, 221))
d = ImageDraw.Draw(im)
d.rectangle([0, 0, 1080, 220], fill=(7, 94, 84))
d.text((40, 70), "WhatsApp", font=font(56, "arialbd.ttf"), fill="white")
d.text((40, 140), "Test Friend  typing...", font=font(40), fill=(220, 240, 235))
msgs = [("Hey, are you coming to the party tonight?", False), ("Yes! I will bring the cake", True), ("Great, see you at 8 pm", False), ("Forwarded: meeting moved to Monday", True)]
y = 320
for text, mine in msgs:
    f = font(44)
    w = int(d.textlength(text, font=f)) + 60
    x = 1080 - w - 40 if mine else 40
    d.rounded_rectangle([x, y, x + w, y + 110], 28, fill=(220, 248, 198) if mine else "white")
    d.text((x + 30, y + 30), text, font=f, fill=(20, 20, 20))
    y += 170
d.text((40, 2280), "Message", font=font(44), fill=(130, 130, 130))
im.save(out / "Screenshot_20240512-201530_WhatsApp.png")

# UPI payment screen
im = Image.new("RGB", (1080, 2340), "white")
d = ImageDraw.Draw(im)
d.text((300, 300), "Payment Successful", font=font(64, "arialbd.ttf"), fill=(16, 128, 64))
d.text((380, 460), "Rs 1,250.00", font=font(90, "arialbd.ttf"), fill=(20, 20, 20))
d.text((120, 700), "Paid to Test Shop", font=font(52), fill=(40, 40, 40))
d.text((120, 800), "UPI Transaction ID: 41" + "".join(str(random.randint(0, 9)) for _ in range(10)), font=font(44), fill=(70, 70, 70))
d.text((120, 880), "Google Pay  -  UPI", font=font(44), fill=(70, 70, 70))
im.save(out / "Screenshot_20240601-104500.png")

# English document photo (JPEG)
im = Image.new("RGB", (1600, 2000), (250, 249, 245))
d = ImageDraw.Draw(im)
d.text((120, 120), "INVOICE 4521", font=font(80, "arialbd.ttf"), fill=(20, 20, 20))
body = ["Bill to: Test Customer", "Item: Laptop repair service", "Amount due: Rs 3,400", "Thank you for your business", "Please pay within 15 days"]
for i, line in enumerate(body):
    d.text((120, 320 + i * 110), line, font=font(56), fill=(30, 30, 30))
im.save(out / "IMG_20240302_101010.jpg", quality=90)

# SPECIMEN Aadhaar-style card
aadhaar = fake_aadhaar()
im = Image.new("RGB", (1400, 880), (255, 255, 255))
d = ImageDraw.Draw(im)
d.rectangle([0, 0, 1400, 120], fill=(255, 153, 51))
d.text((40, 30), "GOVERNMENT OF INDIA", font=font(56, "arialbd.ttf"), fill=(20, 20, 20))
d.text((900, 40), "SPECIMEN", font=font(48, "arialbd.ttf"), fill=(200, 0, 0))
d.rectangle([60, 180, 360, 560], fill=(200, 200, 200))
d.text((420, 200), "Test Person", font=font(52), fill=(20, 20, 20))
d.text((420, 290), "DOB: 01/01/1990", font=font(48), fill=(20, 20, 20))
d.text((420, 370), "Gender: Male", font=font(48), fill=(20, 20, 20))
d.text((380, 650), aadhaar, font=font(84, "arialbd.ttf"), fill=(20, 20, 20))
d.text((420, 780), "Aadhaar - Unique Identification", font=font(40), fill=(60, 60, 60))
im.save(out / "IMG_20240105_090000.jpg", quality=92)

# SPECIMEN PAN-style card
pan = fake_pan()
im = Image.new("RGB", (1400, 880), (235, 245, 255))
d = ImageDraw.Draw(im)
d.text((60, 40), "INCOME TAX DEPARTMENT", font=font(56, "arialbd.ttf"), fill=(20, 20, 80))
d.text((60, 120), "GOVT. OF INDIA      SPECIMEN", font=font(44), fill=(20, 20, 80))
d.text((60, 300), "Permanent Account Number", font=font(44), fill=(40, 40, 40))
d.text((60, 370), pan, font=font(84, "arialbd.ttf"), fill=(20, 20, 20))
d.text((60, 520), "TEST PERSON", font=font(52), fill=(20, 20, 20))
im.save(out / "IMG_20240106_090000.jpg", quality=92)

# Hindi line
im = Image.new("RGB", (1400, 400), "white")
d = ImageDraw.Draw(im)
d.text((60, 120), "नमस्ते दुनिया भारत", font=font(96, "Nirmala.ttc"), fill=(20, 20, 20))
im.save(out / "hindi_line.png")

(out / "truth.txt").write_text(f"aadhaar={aadhaar}\npan={pan}\n", encoding="utf-8")
print("written to", out.resolve(), "| aadhaar", aadhaar, "| pan", pan)
