import sys

import matplotlib
import pytest

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from matplotlib_window_control import Frame, UnsupportedBackendError, window_control  # noqa: E402


def test_agg_is_unsupported():
    fig = plt.figure()
    with pytest.raises(UnsupportedBackendError):
        window_control(fig)
    plt.close(fig)


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS only")
def test_cocoa_to_frame():
    from matplotlib_window_control._macos import _to_frame
    # A 100x50 window whose bottom-left is at (10, 20) on a 1000-point-high
    # primary screen has its top-left 1000 - (20 + 50) = 930 points down.
    assert _to_frame(((10, 20), (100, 50)), 1000) == Frame(10, 930, 100, 50)
