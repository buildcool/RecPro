"""Test videos for the video pass, made from public LFW photos (development only).

    engine/.venv/Scripts/python -I scripts/make_video_samples.py .testdata/lfw/lfw.tgz .testdata/video-samples

slideshow_h264.mp4 / slideshow_hevc.mp4 (18 s, 1280x720): Colin Powell 0-8 s, George W Bush 8-14 s,
Colin Powell again 14-18 s, with a spoken sentence (Windows text-to-speech) from about 1 s.
truth.json records who is on screen when and what is said.
"""
import io
import json
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

from PIL import Image

tgz, out = Path(sys.argv[1]), Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
PLAN = [("Colin_Powell", [150, 151, 152, 153]), ("George_W_Bush", [300, 301, 302]), ("Colin_Powell", [160, 161])]
SECONDS = 2
SAY = "This is the speech test. The family dinner moved to Sunday evening at the lake house."

wanted = {f"lfw/{name}/{name}_{i:04d}.jpg" for name, idx in PLAN for i in idx}
photos: dict[str, Image.Image] = {}
with tarfile.open(tgz) as tf:
    for m in tf:
        if m.name in wanted:
            photos[m.name] = Image.open(io.BytesIO(tf.extractfile(m).read())).convert("RGB")
missing = wanted - set(photos)
if missing:
    sys.exit(f"not in the archive: {sorted(missing)}")

truth: dict = {"people": [], "speech": SAY}
with tempfile.TemporaryDirectory(dir=out) as tmp:
    tmp = Path(tmp)
    lines, t = [], 0
    for name, idx in PLAN:
        start = t
        for i in idx:
            canvas = Image.new("RGB", (1280, 720), (24, 24, 28))
            ph = photos[f"lfw/{name}/{name}_{i:04d}.jpg"].resize((720, 720), Image.Resampling.LANCZOS)
            canvas.paste(ph, (280, 0))
            f = tmp / f"{len(lines):03d}.png"
            canvas.save(f)
            lines += [f"file '{f.as_posix()}'", f"duration {SECONDS}"]
            t += SECONDS
        truth["people"].append({"name": name.replace("_", " "), "start_ms": start * 1000, "end_ms": t * 1000})
    lines.append(lines[-2])  # the concat demuxer needs the last file once more
    (tmp / "list.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    wav = tmp / "say.wav"
    ps = ("Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
          f"$s.SetOutputToWaveFile('{wav}'); $s.Speak('{SAY}'); $s.Dispose()")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True)
    hevc = ["-tag:v", "hvc1", "-x265-params", "log-level=error"]
    for codec, name, extra in (("libx264", "slideshow_h264.mp4", []), ("libx265", "slideshow_hevc.mp4", hevc)):
        subprocess.run(
            ["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(tmp / "list.txt"),
             "-itsoffset", "1", "-i", str(wav), "-map", "0:v", "-map", "1:a", "-vf", "fps=25,format=yuv420p",
             "-c:v", codec, *extra, "-c:a", "aac", "-t", str(t), str(out / name)],
            check=True,
        )
(out / "truth.json").write_text(json.dumps(truth, indent=1), encoding="utf-8")
print("written to", out.resolve())
