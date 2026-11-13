# matplotlib-window-control

Get and set the position and size of a Matplotlib figure window, list the displays,
keep a window above others, and receive move and resize events. The calls are the
same on the macosx, Qt, Tk, wx and GTK backends.

```python
import matplotlib.pyplot as plt
from matplotlib_window_control import window_control

fig, ax = plt.subplots()
win = window_control(fig)

win.get_frame()                      # Frame(x=100, y=150, width=640, height=572)
win.set_frame(200, 150, 800, 600)    # x, y, width, height
win.set_frame(x=300)                 # keep y and the size
win.screens()                        # [Screen(name=..., frame=..., work_area=..., primary=True), ...]
win.screen()                         # the display that contains the window center
win.set_floating(True)               # stay above windows that are not floating
cid = win.connect("window_move_end", lambda frame: print(frame))
win.disconnect(cid)
```

## Coordinates

All backends use one convention:

- The origin is the top-left corner of the primary screen, and *y* increases downward.
- Units are the toolkit's logical pixels (points on macOS).
- A window's frame is its outer rectangle, including the title bar.

Cocoa puts the origin at the bottom-left with *y* up; the macosx module converts.

## Events

| Event | When |
|---|---|
| `window_move`, `window_resize` | each time the toolkit reports a new position or size, also during a drag |
| `window_move_end`, `window_resize_end` | once, when no move or resize has been reported for `end_delay` seconds (default 0.25; set it with `window_control(fig, end_delay=...)`) |

Each callback receives the window's `Frame` after the change.

## Backends

| Backend | Window object | Limits |
|---|---|---|
| macosx | `NSWindow`, through `manager._raw_nswindow_ptr` and PyObjC | needs a Matplotlib version with `_raw_nswindow_ptr` |
| qtagg, qtcairo | `manager.window` (`QMainWindow`) | no positions on Wayland |
| tkagg, tkcairo | `manager.window` (`Tk`) | `screens()` lists one screen on Linux and Windows; see below for floating |
| wxagg, wxcairo | `manager.frame` (`wx.Frame`) | |
| gtk3agg, gtk3cairo | `manager.window` (`Gtk.Window`) | no positions on Wayland |
| gtk4agg, gtk4cairo | `manager.window` (`Gtk.Window`) | no positions, no floating |

Where the toolkit cannot report a position, `Frame.x` and `Frame.y` are None, and
setting a position raises `NotSupportedError`.

## Floating Tk windows

Matplotlib's Tk backend raises a window by setting the Tk attribute `-topmost` to 1
and then 0, each time `plt.show()` or `plt.pause()` runs. That clears floating. After
the first `set_floating(True)`, this package replaces `manager.show` on that figure
manager with a function that calls the original and then sets `-topmost` to 1 again.

## Interactive mode

With interactive mode on (`plt.ion()`, or IPython with `%matplotlib`), Matplotlib
shows a new window as it creates it, at the backend's default position. To place a
window before it appears, create it with interactive mode off:

```python
with plt.ioff():
    fig = plt.figure()
window_control(fig).set_frame(200, 150, 800, 600)
fig.show()
```

## Tests

```bash
python -m pytest                       # no windows
MWC_GUI_TESTS=1 python -m pytest       # opens a window per installed backend
python tests/gui_check.py qtagg        # one backend, with a line per check
```
