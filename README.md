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
win.screens()                        # [Screen(name="Kuycon G32P", frame=..., primary=True, ...), ...]
win.screen()                         # the display that contains the window center
win.set_floating(True)               # stay above windows that are not floating
win.raise_window()                   # bring to the front, without taking focus
win.raise_window(with_focus=True)    # bring to the front and give it focus
cid = win.connect("window_move_end", lambda frame: print(frame))
win.disconnect(cid)
```

## Coordinates

All backends use one convention:

- The origin is the top-left corner of the primary display, and *y* increases downward.
- Units are the toolkit's logical pixels (points on macOS).
- A window's frame is its outer rectangle, including the title bar.

Cocoa puts the origin at the bottom-left with *y* up, and GDK and X11 put it at the
top-left of the bounding box of all displays; the package converts both.

A position measured from the primary display changes when the primary display
changes. To keep a window on one display, measure from that display instead:

```python
s = win.screen()
win.get_frame(screen=s)                      # x and y from the top-left corner of s
win.set_frame(60, 60, 800, 600, screen=s)
```

## Identifying displays

Each `Screen` has identity fields, read from the operating system:

| Field | Content |
|---|---|
| `manufacturer` | the three-letter manufacturer code from the monitor's EDID, e.g. `"GKT"` |
| `product` | the product code from the EDID |
| `serial` | the serial number from the EDID, or None; many monitors report none |
| `system_id` | the display UUID on macOS, the output name on X11 (e.g. `"DP-1"`), the monitor device path on Windows |

`find_screen(saved, screens)` finds a saved display among the attached ones. *saved*
can be a `Screen` or `screen._asdict()` loaded from JSON:

```python
import json
from matplotlib_window_control import find_screen

saved = json.dumps({"screen": s._asdict(), "frame": win.get_frame(screen=s)})
# ... in a later run:
data = json.loads(saved)
s = find_screen(data["screen"], win.screens())
if s is not None:
    win.set_frame(*data["frame"], screen=s)
```

The first rule that matches exactly one display decides:

1. same manufacturer, product and serial number;
2. same manufacturer, product and `system_id`: for monitors without serial numbers,
   the same model on the same port;
3. same manufacturer and product, if one such display is attached;
4. same name, if one such display is attached.

A display of the same model with a different serial number is a different monitor
and never matches. Two identical monitors without serial numbers can be told apart
only by `system_id`; after moving them to other ports, `find_screen` returns None
for both.

The identity comes from CoreGraphics on macOS, from XRandR on X11, and from the
Win32 API and the registry on Windows. The Windows code has not been tested yet. On
Wayland the fields are None, except on Tk: Tk runs under XWayland, and XRandR gives the
output name (`name` and `system_id`), but no EDID.

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
| qtagg, qtcairo | `manager.window` (`QMainWindow`) | no positions and no floating on Wayland |
| tkagg, tkcairo | `manager.window` (`Tk`) | `screens()` comes from the system on Linux and Windows; runs under XWayland in a Wayland session; see below for floating |
| wxagg, wxcairo | `manager.frame` (`wx.Frame`) | |
| gtk3agg, gtk3cairo | `manager.window` (`Gtk.Window`) | no positions and no floating on Wayland |
| gtk4agg, gtk4cairo | `manager.window` (`Gtk.Window`) | no positions, no floating |

Where the toolkit cannot report a position, `Frame.x` and `Frame.y` are None, and
setting a position raises `NotSupportedError`.

## Floating windows

A floating window stays above windows that are not floating. Wayland gives clients no
way to keep a window above, so on Wayland `set_floating()` and `get_floating()` raise
`NotSupportedError` on Qt and GTK; GTK 4 has no keep-above call anywhere.

Each toolkit picks its own window level for floating, so floating windows of different
backends do not stack as equals. On macOS, the `NSWindow` levels are:

| Backend | Level |
|---|---|
| GTK 3 | 1 |
| macosx | 3 |
| Qt, wx | 8 |
| Tk | 19 |

A floating Tk window stays above a floating macosx window.

### Tk

Matplotlib's Tk backend raises a window by setting the Tk attribute `-topmost` to 1
and then 0, each time `plt.show()` or `plt.pause()` runs. That clears floating. After
the first `set_floating(True)`, this package replaces `manager.show` on that figure
manager with a function that calls the original and then sets `-topmost` to 1 again.

## Raising windows

`raise_window()` brings the window in front of other windows, also of other
applications, and leaves the keyboard focus where it is. `raise_window(with_focus=True)`
also makes the application active and gives the window focus.

On macOS, a background application cannot raise its windows above the frontmost
application with the toolkits' own calls, so every backend calls the `NSWindow`:
`orderFrontRegardless` without focus, `activateIgnoringOtherApps:` and
`makeKeyAndOrderFront:` with focus. GTK gives no handle to the `NSWindow`; the package
finds it by the window title, which Matplotlib sets per figure, when exactly one
visible window has that title.

Elsewhere the package uses the toolkit's calls, and the platform decides:

- Windows limits which process may take the foreground; it may flash the taskbar
  button instead.
- Wayland gives focus only through its activation protocol.
- GTK 4 has no call that raises without focus; `raise_window()` uses `present()`,
  which may take focus.

Matplotlib raises a window itself each time `plt.show()` or `plt.pause()` runs, while
the rcParam `figure.raise_window` is True (the default). The Qt backend also activates
the window then, so a loop that calls `plt.pause()` takes focus on every call. Set
`matplotlib.rcParams["figure.raise_window"] = False` to raise windows only when you
call `raise_window()`.

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

`TESTING.md` lists what the tests cover and the cases that have not been tested.

```bash
python -m pytest                       # no windows
MWC_GUI_TESTS=1 python -m pytest       # opens a window per installed backend
python tests/gui_check.py qtagg        # one backend, with a line per check
python tests/multi_screen_check.py qtagg   # macOS with two or more displays
python tests/raise_check.py qtagg          # macOS: raising across applications
```

With Homebrew's GLib 2.90.1, `from gi.repository import GLib` fails with an
`AssertionError`: its `GLib-2.0.typelib` names `libgobject-2.0.0.dylib` without a
directory. Run GTK with `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib`;
`tests/test_gui.py` sets it.
