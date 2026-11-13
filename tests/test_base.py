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

