"""Reads dates, dimensions, camera and GPS from images (EXIF) and videos (ffprobe)."""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger("recpro.meta")

EXIF_IFD = 0x8769
GPS_IFD = 0x8825
TAG_ORIENTATION = 0x0112
TAG_MAKE = 0x010F
TAG_MODEL = 0x0110
TAG_DATETIME = 0x0132
TAG_DATETIME_ORIGINAL = 0x9003
TAG_DATETIME_DIGITIZED = 0x9004
TAG_OFFSET_ORIGINAL = 0x9011

_FFPROBE = shutil.which("ffprobe")
_FFMPEG = shutil.which("ffmpeg")
NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def ffmpeg_bin() -> str | None:
    return _FFMPEG


def ffprobe_bin() -> str | None:
    return _FFPROBE


def parse_exif_dt(s: Any, offset: Any = None) -> float | None:
    if not s or not isinstance(s, str):
        return None
    s = s.strip().replace("\x00", "")
    m = re.match(r"(\d{4})[:\-](\d{2})[:\-](\d{2})[ T](\d{2}):(\d{2}):(\d{2})", s)
    if not m:
        return None
    y, mo, d, h, mi, se = (int(x) for x in m.groups())
    if y < 1971 or mo < 1 or mo > 12 or d < 1 or d > 31:
        return None
    try:
        if isinstance(offset, str) and re.match(r"^[+-]\d{2}:\d{2}$", offset.strip()):
            sign = 1 if offset.strip()[0] == "+" else -1
            oh, om = (int(x) for x in offset.strip()[1:].split(":"))
            from datetime import timedelta

            tz = timezone(sign * timedelta(hours=oh, minutes=om))
            return datetime(y, mo, d, h, mi, se, tzinfo=tz).timestamp()
        return time.mktime((y, mo, d, h, mi, se, 0, 0, -1))
    except (ValueError, OverflowError):
        return None


_FILENAME_PATTERNS = [
    # IMG_20230105_123456, VID_20230105_123456, PXL_20230105_123456789, 20230105_123456
    re.compile(r"(?<!\d)(20\d{2}|19\d{2})(\d{2})(\d{2})[_\-\s]?(\d{2})(\d{2})(\d{2})"),
    # Screenshot_2023-01-05-12-34-56, 2023-01-05 12.34.56, WhatsApp Image 2023-01-05 at 12.34.56
    re.compile(r"(?<!\d)(20\d{2}|19\d{2})-(\d{2})-(\d{2})(?:[ _\-]|\sat\s)(\d{2})[.\-:](\d{2})[.\-:](\d{2})"),
    # IMG-20230105-WA0001 (date only)
    re.compile(r"(?<!\d)(20\d{2})(\d{2})(\d{2})-WA\d+", re.I),
    re.compile(r"(?<!\d)(20\d{2})-(\d{2})-(\d{2})(?!\d)"),
]


def date_from_filename(name: str) -> float | None:
    for pat in _FILENAME_PATTERNS:
        m = pat.search(name)
        if not m:
            continue
        g = [int(x) for x in m.groups()]
        y, mo, d = g[0], g[1], g[2]
        h, mi, se = (g[3], g[4], g[5]) if len(g) >= 6 else (12, 0, 0)
        if not (1990 <= y <= 2100 and 1 <= mo <= 12 and 1 <= d <= 31 and h < 24 and mi < 60 and se < 61):
            continue
        try:
            return time.mktime((y, mo, d, h, mi, min(se, 59), 0, 0, -1))
        except (ValueError, OverflowError):
            continue
    return None


def _ratio(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        try:
            n, d = v
            return float(n) / float(d)
        except Exception:
            return float("nan")


def gps_from_exif(gps: dict) -> tuple[float | None, float | None]:
    try:
        lat_v, lat_ref = gps.get(2), gps.get(1)
        lon_v, lon_ref = gps.get(4), gps.get(3)
        if not lat_v or not lon_v:
            return None, None
        lat = _ratio(lat_v[0]) + _ratio(lat_v[1]) / 60 + _ratio(lat_v[2]) / 3600
        lon = _ratio(lon_v[0]) + _ratio(lon_v[1]) / 60 + _ratio(lon_v[2]) / 3600
        if str(lat_ref).upper().startswith("S"):
            lat = -lat
        if str(lon_ref).upper().startswith("W"):
            lon = -lon
        if lat != lat or lon != lon or (abs(lat) < 1e-6 and abs(lon) < 1e-6) or abs(lat) > 90 or abs(lon) > 180:
            return None, None
        return round(lat, 6), round(lon, 6)
    except Exception:
        return None, None


def image_meta(im, orig_size: tuple[int, int] | None = None) -> dict[str, Any]:
    """Extract metadata from an opened (not yet transposed) PIL image."""
    out: dict[str, Any] = {}
    try:
        exif = im.getexif()
    except Exception:
        exif = None
    w, h = orig_size or im.size
    orientation = 1
    if exif:
        orientation = int(exif.get(TAG_ORIENTATION, 1) or 1)
        make = str(exif.get(TAG_MAKE, "") or "").strip("\x00 ").strip()
        model = str(exif.get(TAG_MODEL, "") or "").strip("\x00 ").strip()
        if model:
            out["camera"] = model if make and model.lower().startswith(make.lower().split()[0]) else f"{make} {model}".strip()
            out["has_exif_camera"] = 1
        try:
            sub = exif.get_ifd(EXIF_IFD)
        except Exception:
            sub = {}
        t = parse_exif_dt(sub.get(TAG_DATETIME_ORIGINAL), sub.get(TAG_OFFSET_ORIGINAL)) or parse_exif_dt(
            sub.get(TAG_DATETIME_DIGITIZED)
        ) or parse_exif_dt(exif.get(TAG_DATETIME))
        if t:
            out["taken_at"] = t
            out["taken_src"] = "exif"
        try:
            gps = exif.get_ifd(GPS_IFD)
            if gps:
                lat, lon = gps_from_exif(gps)
                if lat is not None:
                    out["gps_lat"], out["gps_lon"] = lat, lon
        except Exception:
            pass
    if orientation in (5, 6, 7, 8):
        w, h = h, w
    out["width"], out["height"] = w, h
    out["orientation"] = orientation
    return out


_ISO6709 = re.compile(r"([+-]\d+(?:\.\d+)?)([+-]\d+(?:\.\d+)?)")


def video_meta(path: str) -> dict[str, Any]:
    if not _FFPROBE:
        raise RuntimeError("ffprobe is not available")
    cp = subprocess.run(
        [_FFPROBE, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path],
        capture_output=True,
        stdin=subprocess.DEVNULL,
        timeout=60,
        creationflags=NO_WINDOW,
    )
    if cp.returncode != 0:
        raise RuntimeError(cp.stderr.decode("utf-8", "replace")[:300] or "ffprobe failed")
    info = json.loads(cp.stdout.decode("utf-8", "replace") or "{}")
    fmt = info.get("format", {}) or {}
    vstreams = [s for s in info.get("streams", []) if s.get("codec_type") == "video" and not (s.get("disposition") or {}).get("attached_pic")]
    out: dict[str, Any] = {}
    try:
        out["duration"] = float(fmt.get("duration") or (vstreams[0].get("duration") if vstreams else 0) or 0) or None
    except (TypeError, ValueError):
        out["duration"] = None
    if vstreams:
        v = vstreams[0]
        w, h = int(v.get("width") or 0), int(v.get("height") or 0)
        rot = 0
        try:
            rot = int(float((v.get("tags") or {}).get("rotate", 0)))
        except (TypeError, ValueError):
            rot = 0
        for sd in v.get("side_data_list", []) or []:
            if "rotation" in sd:
                try:
                    rot = int(float(sd["rotation"]))
                except (TypeError, ValueError):
                    pass
        if abs(rot) % 180 == 90:
            w, h = h, w
        out["width"], out["height"] = w or None, h or None
        out["vcodec"] = v.get("codec_name")
    tags = {k.lower(): v for k, v in (fmt.get("tags") or {}).items()}
    ct = tags.get("com.apple.quicktime.creationdate") or tags.get("creation_time")
    if ct:
        try:
            s = str(ct).replace("Z", "+00:00")
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt.year > 1971:
                out["taken_at"] = dt.timestamp()
                out["taken_src"] = "video"
        except ValueError:
            pass
    loc = tags.get("com.apple.quicktime.location.iso6709") or tags.get("location")
    if loc:
        m = _ISO6709.match(str(loc))
        if m:
            lat, lon = float(m.group(1)), float(m.group(2))
            if abs(lat) <= 90 and abs(lon) <= 180 and (abs(lat) > 1e-6 or abs(lon) > 1e-6):
                out["gps_lat"], out["gps_lon"] = lat, lon
    model = tags.get("com.apple.quicktime.model") or tags.get("model")
    if model:
        out["camera"] = str(model)
        out["has_exif_camera"] = 1
    return out
