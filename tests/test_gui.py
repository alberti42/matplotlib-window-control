import os
import subprocess
import sys
from pathlib import Path

import pytest

BACKENDS = ["macosx", "qtagg", "tkagg", "wxagg", "gtk3agg", "gtk4agg"]


@pytest.mark.gui
@pytest.mark.skipif(os.environ.get("MWC_GUI_TESTS") != "1",
                    reason="opens native windows; set MWC_GUI_TESTS=1")
@pytest.mark.parametrize("backend", BACKENDS)
def test_backend(backend):
    if backend == "macosx" and sys.platform != "darwin":
        pytest.skip("macOS only")
    load = subprocess.run(
        [sys.executable, "-c",
         f"import matplotlib.pyplot as plt; plt.switch_backend({backend!r})"],
        capture_output=True, text=True, timeout=60)
    if load.returncode != 0:
        pytest.skip(f"{backend} cannot be loaded: {load.stderr.strip().splitlines()[-1]}")
    proc = subprocess.run(
        [sys.executable, str(Path(__file__).with_name("gui_check.py")), backend],
        capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stdout + proc.stderr
