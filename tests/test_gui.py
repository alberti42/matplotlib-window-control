import os
import subprocess
import sys
from pathlib import Path

import pytest

BACKENDS = ["macosx", "qtagg", "tkagg", "wxagg", "gtk3agg", "gtk4agg"]

# Homebrew's GLib 2.90.1 typelib names libgobject-2.0.0.dylib without a
# directory, so PyGObject finds the library only on the fallback search path.
ENV = dict(os.environ)
if sys.platform == "darwin" and os.path.isdir("/opt/homebrew/lib"):
    ENV["DYLD_FALLBACK_LIBRARY_PATH"] = ":".join(
        filter(None, [ENV.get("DYLD_FALLBACK_LIBRARY_PATH"), "/opt/homebrew/lib"]))

gui = pytest.mark.skipif(os.environ.get("MWC_GUI_TESTS") != "1",
                         reason="opens native windows; set MWC_GUI_TESTS=1")


def run_script(script, backend):
    """Run tests/<script> for *backend*; skip if the backend cannot be loaded."""
    if backend == "macosx" and sys.platform != "darwin":
        pytest.skip("macOS only")
    load = subprocess.run(
        [sys.executable, "-c",
         f"import matplotlib.pyplot as plt; plt.switch_backend({backend!r})"],
        capture_output=True, text=True, timeout=60, env=ENV)
    if load.returncode != 0:
        pytest.skip(f"{backend} cannot be loaded: {load.stderr.strip().splitlines()[-1]}")
    return subprocess.run(
        [sys.executable, str(Path(__file__).with_name(script)), backend],
        capture_output=True, text=True, timeout=120, env=ENV)


@pytest.mark.gui
@gui
@pytest.mark.parametrize("backend", BACKENDS)
def test_backend(backend):
    proc = run_script("gui_check.py", backend)
    assert proc.returncode == 0, proc.stdout + proc.stderr


@pytest.mark.gui
@gui
@pytest.mark.skipif(sys.platform != "darwin", reason="uses Cocoa as the reference")
@pytest.mark.parametrize("backend", BACKENDS)
def test_multi_screen(backend):
    proc = run_script("multi_screen_check.py", backend)
    if proc.returncode == 2:
        pytest.skip(proc.stdout.strip().splitlines()[-1])
    assert proc.returncode == 0, proc.stdout + proc.stderr
