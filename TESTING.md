# Testing

## What the tests cover

All automated tests have run on two machines:

- macOS, with a Kuycon G32P and an iPad as a second display (Sidecar), Python 3.13,
  the Matplotlib fork with `_raw_nswindow_ptr`, PySide6, Tk 9.0, wxPython 4.3.2,
  GTK 3.24 and GTK 4.24.
- Fedora 45 with GNOME 51 on Wayland (2026-11-15), one display (an iMac panel, 3840 ×
  2160 at 150 % scaling), Python 3.13, Matplotlib 3.11.2, PySide6 6.12, Tk 9.0,
  GTK 3.24 and GTK 4.24; no wxPython. `tests/gui_check.py` passes for Qt, GTK 3 and
  GTK 4 as Wayland clients, for Tk under XWayland, and for Qt (`QT_QPA_PLATFORM=xcb`)
  and GTK 3 (`GDK_BACKEND=x11`) under XWayland. Under XWayland, `screens()` on Tk, Qt
  and GTK 3 has the output name from XRandR as `system_id`. Floating on Qt under
  Wayland was checked by eye: Mutter ignores it.

| Test | Covers |
|---|---|
| `tests/test_window_control.py` | the logic in `_base.py` with a fake backend: events, end-event timing, `screen()`, the primary-display shift, `screen=` |
| `tests/test_find_screen.py` | the matching rules of `find_screen()` |
| `tests/test_displays.py` | EDID decoding, Windows device paths, matching toolkit displays to system displays |
| `tests/gui_check.py` | every operation on a real window, for one backend |
| `tests/multi_screen_check.py` | placement and identity on each display; macOS only, two or more displays |
| `tests/raise_check.py` | `raise_window()` across applications, with and without focus; macOS only |

One manual check was run on 2026-11-14: after switching the primary display from
the Kuycon to the iPad, `find_screen()` with the identity saved before the switch,
plus `set_frame(..., screen=)`, put the window back at the saved offset from the
Kuycon's corner on every backend.

## Untested cases

These cases have not been run. Each row says what could break and how to check it.

### Platforms

| Case | What could break | How to check |
|---|---|---|
| Linux, X11 server | XWayland was tested, a real X server was not: several outputs, the shift from the bounding-box corner to the primary output, EDID from XRandR (XWayland gives none), window managers other than Mutter | run `tests/gui_check.py` for each backend in an X11 session; print `window_control(fig).screens()` and compare with `xrandr --props` |
| Linux, Wayland with several displays, or KDE | the display list and the `primary` flag (GDK on Wayland names no primary display); KWin may treat sizes and decorations differently from Mutter | run `tests/gui_check.py` and print `screens()` |
| Windows | `EnumDisplayMonitors` and the registry EDID lookup; displays with negative coordinates; the device name `\\.\DISPLAY1` matching Qt and wx screen names | run `tests/gui_check.py`; print `screens()` and compare with the display settings |
| Display scaling on X11 and Windows | toolkits that report logical pixels while the system reports physical ones; matching assumes one scale for all displays, so mixed scaling (e.g. 100 % and 150 %) can leave displays without identity | print `screens()` with mixed scaling and check the identity fields |
| GTK 3 on X11 | `move()` and `get_position()` relative to the frame under window managers other than Mutter | `tests/gui_check.py gtk3agg` under two or three window managers |
| Tk on Linux | `_NET_FRAME_EXTENTS` and `wm geometry +x+y` under window managers other than Mutter; window managers that do not set `_NET_FRAME_EXTENTS` fall back to the older method | `tests/gui_check.py tkagg` |

### Displays

| Case | What could break | How to check |
|---|---|---|
| Reboot | macOS display UUIDs, X11 output names or Windows device paths changing | save `s._asdict()` for each display, reboot, run `find_screen()` |
| Two identical monitors without serial numbers | `system_id` not telling them apart, or swapping after a reboot | save both, reboot, and check that each window returns to its own monitor |
| Swapping cables between identical monitors | `find_screen()` should return None for both, not the wrong monitor | save, swap cables, run `find_screen()` |
| Unplugging a display | `find_screen()` should return None; a window left on the removed display | save, unplug, run `find_screen()` and `screens()` |
| Displays changed while a window is open | `screens()` and the end events after the change | change the arrangement while a figure is shown |
| Monitors that report a text serial | the EDID text serial on X11 and Windows; on macOS only the numeric serial is read | print `screens()` with such a monitor attached |

### Use

| Case | What could break | How to check |
|---|---|---|
| Dragging and resizing with the mouse | end events: one per gesture, and an early end event when the mouse holds still for longer than `end_delay` mid-drag | connect all four events and drag by hand |
| IPython with `%matplotlib` | windows shown before `set_frame()`; the `plt.ioff()` recipe in the README | run the recipe in IPython |
| Floating on X11 and Windows | `-topmost`, `STAY_ON_TOP`, `WindowStaysOnTopHint` and `set_keep_above()` there; the Tk `manager.show` wrapper. On Mutter under XWayland the window manager sets `_NET_WM_STATE_ABOVE` for GTK 3; the stacking was not checked by eye | `tests/gui_check.py` checks the reported state only; check the stacking by eye |
| `raise_window()` on Linux and Windows | raising above other applications without focus; Windows' foreground restrictions; Wayland's activation protocol; GTK 4 taking focus | put another application's window over the figure, call `raise_window()` and `raise_window(with_focus=True)`, check by eye |
| GTK on macOS with two windows of the same title | `raise_window()` finds the `NSWindow` by title; with duplicate titles it falls back to the GTK calls, which do not raise above other applications | give two figures the same title and call `raise_window()` |

### Versions

| Case | What could break | How to check |
|---|---|---|
| PyQt5, PyQt6 | the enum lookup in `_qt.py` | `tests/gui_check.py qtagg` with each binding installed |
| Python 3.10 to 3.12 | syntax and library differences; `pyproject.toml` declares `>=3.10` | run the tests on each version |
| Released Matplotlib (3.8 and later) | backend class names used by `window_control()`; the macosx backend needs `_raw_nswindow_ptr`, which no release has yet | run the tests against each release |
| Tk 8.6 | `wm geometry` and `-topmost` behavior | `tests/gui_check.py tkagg` with Tk 8.6 |
