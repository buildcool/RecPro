"""Entry point of the frozen engine (PyInstaller): the same as `python -m recpro.server`.

RECPRO_DUMP_STACKS=<seconds> prints every thread's stack that often (for a frozen engine that
seems stuck; it has no debugger).
"""

import multiprocessing
import os
import sys


def main() -> None:
    multiprocessing.freeze_support()
    if os.environ.get("RECPRO_DUMP_STACKS"):
        import faulthandler

        faulthandler.dump_traceback_later(float(os.environ["RECPRO_DUMP_STACKS"]), repeat=True)
    # The desktop app reads stdout through a pipe, which Windows opens in the system code page
    # (cp1252): a file name in Hindi in a log line must not stop the engine.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except Exception:
            pass
    from recpro.server import main as serve

    serve()


if __name__ == "__main__":
    main()
