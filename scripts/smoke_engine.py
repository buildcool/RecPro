"""Start the frozen engine the way the desktop app does and check that it answers.

    python scripts/smoke_engine.py dist/recpro-engine/recpro-engine.exe <empty data folder> [--expect-version X.Y.Z]

Output goes through a pipe in the system code page (no PYTHONIOENCODING), like the app reads
it; the engine must print its ready line, answer /api/health and /api/models with the token,
and exit by itself when its stdin closes. Standard library only, so CI runs it with any Python.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("exe")
    ap.add_argument("data_dir")
    ap.add_argument("--expect-version")
    ap.add_argument("--expect-ffmpeg", action="store_true", help="ffmpeg and ffprobe must be the copies next to the engine")
    ap.add_argument("--timeout", type=float, default=120)
    a = ap.parse_args()

    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONIOENCODING", "PYTHONUTF8", "PYTHONPATH", "PYTHONHOME")}
    env["RECPRO_TOKEN"] = token = "smoke-test-token"
    os.makedirs(a.data_dir, exist_ok=True)
    exe = os.path.abspath(a.exe)  # CreateProcess can't search a relative path written with forward slashes
    p = subprocess.Popen([exe, "--data-dir", a.data_dir, "--watch-stdin"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, env=env)
    lines: list[str] = []
    ready: dict = {}

    def read() -> None:
        assert p.stdout is not None
        for raw in p.stdout:
            line = raw.decode("utf-8", "replace").rstrip()
            lines.append(line)
            if line.startswith("RECPRO_READY "):
                ready.update(json.loads(line.split(" ", 1)[1]))

    threading.Thread(target=read, daemon=True).start()
    t0 = time.time()
    while not ready and p.poll() is None and time.time() - t0 < a.timeout:
        time.sleep(0.2)
    if not ready:
        print("engine never became ready (exit code %s). Output:\n%s" % (p.poll(), "\n".join(lines[-60:])))
        p.kill()
        return 1
    print(f"engine ready on port {ready['port']} after {time.time() - t0:.1f}s")

    def get(path: str) -> dict:
        req = urllib.request.Request(f"http://127.0.0.1:{ready['port']}{path}", headers={"X-RecPro-Token": token})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))

    ok = True
    try:
        health = get("/api/health")
        print("health:", json.dumps(health))
        if a.expect_version and health.get("version") != a.expect_version:
            print(f"version is {health.get('version')}, expected {a.expect_version}")
            ok = False
        if a.expect_ffmpeg:
            bundled = os.path.join(os.path.dirname(exe), "bin")
            tools = health.get("tools") or {}
            for tool in ("ffmpeg", "ffprobe"):
                where = tools.get(tool)
                if not where or not os.path.normcase(where).startswith(os.path.normcase(bundled)):
                    print(f"{tool} is {where!r}, not the bundled copy in {bundled}")
                    ok = False
        models = get("/api/models")
        print("models:", ", ".join(m["id"] for m in models["models"]), "| device:", json.dumps(models["device"]))
    except Exception as e:
        print("API check failed:", e)
        ok = False
    # the app stops the engine by closing stdin
    assert p.stdin is not None
    p.stdin.close()
    try:
        p.wait(timeout=20)
        print(f"engine exited with code {p.returncode} when stdin closed")
    except subprocess.TimeoutExpired:
        print("engine did not exit when stdin closed")
        p.kill()
        ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
