"""Control the windows of Matplotlib figures across GUI backends.

Get and set a window's position and size, list the displays, keep a window
above others, and receive move and resize events, with the same calls on the
macosx, Qt, Tk, wx and GTK backends::

    import matplotlib.pyplot as plt
    from matplotlib_window_control import window_control

    fig = plt.figure()
    win = window_control(fig)
    win.set_frame(100, 100, 800, 600)
    win.connect("window_move_end", lambda frame: print(frame))
"""

from ._base import (
    EVENTS,
    Frame,
    NotSupportedError,
    Screen,
    UnsupportedBackendError,
    WindowControl,
    window_control,
)

__all__ = [
    "EVENTS",
    "Frame",
    "NotSupportedError",
    "Screen",
    "UnsupportedBackendError",
    "WindowControl",
    "window_control",
]
__version__ = "0.1.0"
