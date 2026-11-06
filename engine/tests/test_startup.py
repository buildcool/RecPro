"""The engine must not depend on import timing: the frozen app starts from a clean interpreter."""
from __future__ import annotations

import subprocess
import sys


def test_quick_pass_hash_from_many_threads_in_a_fresh_interpreter():
    # The frozen engine starts with nothing imported. phash used to import SciPy on first use, so
    # its BLAS DLL was first loaded from a quick-pass worker thread, and that load never returned
    # (every thread stuck, 0 of 29 photos prepared). It has to load on the importing thread.
    code = (
        "import sys\n"
        "from concurrent.futures import ThreadPoolExecutor\n"
        "from PIL import Image\n"
        "from recpro.library.imaging import phash\n"
        "assert 'scipy.fft' in sys.modules, 'SciPy must be loaded by the import, not by the first worker thread'\n"
        "imgs = [Image.effect_noise((64, 48), 40 + i).convert('RGB') for i in range(24)]\n"
        "with ThreadPoolExecutor(12) as ex: print(len(set(ex.map(phash, imgs))))\n"
    )
    cp = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120)
    assert cp.returncode == 0, cp.stderr
    assert int(cp.stdout.strip()) > 1
