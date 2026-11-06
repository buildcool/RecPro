"""Playable copies of videos the app's player can't open (HEVC on PCs without its decoder, old codecs).

Made on demand, when the viewer can't play a video: H.264 (on the NVIDIA encoder when there is one,
else x264), the longer side at most 1280 px, AAC sound, fast start, kept in previews/ next to the
thumbnails. Private videos never get one, because it would be a readable copy on disk.
"""
from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from ..context import Context
from .imaging import shard
from .metadata import NO_WINDOW, ffmpeg_bin

log = logging.getLogger("recpro.playable")

ENCODERS = (
    ["-c:v", "h264_nvenc", "-preset", "p4", "-rc", "vbr", "-cq", "24"],
    ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23"],
)
SCALE = "scale='if(gt(iw,ih),min(1280,iw),-2)':'if(gt(iw,ih),-2,min(1280,ih))'"


class Playable:
    def __init__(self, ctx: Context):
        self.ctx = ctx
        self._jobs: dict[int, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def start(self) -> None:
        threading.Thread(target=self.cleanup, name="playable-cleanup", daemon=True).start()

    def path(self, media_id: int) -> Path:
        return shard(self.ctx.paths.previews, media_id, ".mp4")

    def state(self, media_id: int) -> dict[str, Any]:
        if self.path(media_id).exists():
            return {"state": "ready", "progress": 100}
        with self._lock:
            return dict(self._jobs.get(media_id, {"state": "none", "progress": 0}))

    def request(self, row: Any) -> dict[str, Any]:
        if row["sens_state"] in ("private", "review"):
            raise PermissionError("Private videos don't get a playable copy. Open it in your video player.")
        if not ffmpeg_bin():
            raise RuntimeError("ffmpeg is not available")
        mid = int(row["id"])
        with self._lock:
            if self.path(mid).exists() or self._jobs.get(mid, {}).get("state") == "making":
                pass
            else:
                self._jobs[mid] = {"state": "making", "progress": 0}
                threading.Thread(target=self._make, args=(dict(row),), name=f"playable-{mid}", daemon=True).start()
        return self.state(mid)

    def _set(self, mid: int, **kw: Any) -> None:
        with self._lock:
            self._jobs.setdefault(mid, {}).update(kw)
        self.ctx.events.publish_throttled("playable", {"id": mid, **self.state(mid)}, interval=0.5)

    def _make(self, row: dict[str, Any]) -> None:
        mid = int(row["id"])
        final = self.path(mid)
        final.parent.mkdir(parents=True, exist_ok=True)
        tmp = final.with_name(f"{mid}.part.mp4")
        dur = float(row.get("duration") or 0)
        t0 = time.time()
        err = ""
        for enc in ENCODERS:
            cmd = [ffmpeg_bin(), "-nostdin", "-v", "error", "-y", "-i", row["path"], "-map", "0:v:0", "-map", "0:a:0?", "-vf", SCALE,
                   *enc, "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart",
                   "-progress", "pipe:1", "-nostats", str(tmp)]
            p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=NO_WINDOW)
            assert p.stdout is not None
            for raw in p.stdout:
                line = raw.decode("utf-8", "replace").strip()
                if line.startswith("out_time_us=") and dur > 0:
                    try:
                        self._set(mid, progress=min(99, int(int(line.split("=", 1)[1]) / 1e6 / dur * 100)))
                    except ValueError:
                        pass
            p.wait()
            err = (p.stderr.read().decode("utf-8", "replace") if p.stderr else "")[-300:]
            if p.returncode == 0 and tmp.exists() and tmp.stat().st_size > 0:
                os.replace(tmp, final)
                log.info("playable copy of %s in %.1fs (%s)", row["path"], time.time() - t0, enc[1])
                with self._lock:
                    self._jobs.pop(mid, None)
                self._set(mid)
                return
            tmp.unlink(missing_ok=True)
        log.info("no playable copy of %s: %s", row["path"], err)
        self._set(mid, state="failed", error=err.strip().splitlines()[-1] if err.strip() else "ffmpeg failed")

    def forget(self, media_ids: list[int]) -> None:
        """Deletes the copies of these videos (they became private, or are gone)."""
        for mid in media_ids:
            for p in (self.path(mid), self.path(mid).with_name(f"{mid}.part.mp4")):
                try:
                    p.unlink(missing_ok=True)
                except OSError:
                    pass

    def cleanup(self) -> None:
        """At start-up: copies of videos that are private, removed or gone are deleted."""
        base = self.ctx.paths.previews
        if not base.exists():
            return
        files = list(base.glob("*/*.mp4"))
        ids = []
        for f in files:
            try:
                ids.append(int(f.name.split(".")[0]))
            except ValueError:
                continue
        keep = set()
        for i in range(0, len(ids), 900):
            chunk = ids[i : i + 900]
            keep |= {
                int(r["id"])
                for r in self.ctx.db.q(
                    f"SELECT id FROM media WHERE id IN ({','.join('?' * len(chunk))}) AND state='active' AND sens_state NOT IN ('private','review')",
                    chunk,
                )
            }
        self.forget([i for i in ids if i not in keep])


def create(ctx: Context) -> Playable:
    return Playable(ctx)
