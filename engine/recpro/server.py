"""Engine entrypoint: ``python -m recpro.server --data-dir <dir>``.

Binds to 127.0.0.1 on a random free port, prints ``RECPRO_READY {"port": N}`` on stdout,
and exits when its parent (the desktop app) closes stdin.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import secrets
import socket
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path


def _watch_parent(stdin_watch: bool) -> None:
    if not stdin_watch:
        return

    def run() -> None:
        try:
            while sys.stdin.read(1):
                pass
        except Exception:
            pass
        os._exit(0)

    threading.Thread(target=run, name="parent-watch", daemon=True).start()


def main(argv: list[str] | None = None) -> None:
    from . import __version__

    ap = argparse.ArgumentParser(prog="recpro-engine")
    ap.add_argument("--version", action="version", version=f"recpro-engine {__version__}")
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--origin", action="append", default=[], help="extra allowed CORS origin")
    ap.add_argument("--watch-stdin", action="store_true", help="exit when stdin closes (set by the desktop app)")
    args = ap.parse_args(argv)

    from .config import Paths

    paths = Paths(Path(args.data_dir).resolve())
    paths.ensure()
    handler = RotatingFileHandler(paths.logs / "engine.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[handler, logging.StreamHandler(sys.stderr)],
    )

    token = os.environ.get("RECPRO_TOKEN") or secrets.token_hex(32)

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    sock.bind(("127.0.0.1", args.port))
    sock.listen(128)
    port = sock.getsockname()[1]

    from .bootstrap import build_context
    from .api.app import create_app

    ctx = build_context(paths, token, port)
    app = create_app(ctx, extra_origins=args.origin)

    import uvicorn

    config = uvicorn.Config(app, log_level="warning", access_log=False, lifespan="on")
    server = uvicorn.Server(config)
    _watch_parent(args.watch_stdin)
    print("RECPRO_READY " + json.dumps({"port": port}), flush=True)
    server.run(sockets=[sock])


if __name__ == "__main__":
    main()
