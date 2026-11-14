# Testing

## What the tests cover

All automated tests have run on macOS only, on one machine: a Kuycon G32P and an
iPad as a second display (Sidecar), with Python 3.13, the Matplotlib fork with
`_raw_nswindow_ptr`, PySide6, Tk 9.0, wxPython 4.3.2, GTK 3.24 and GTK 4.24.

| Test | Covers |
|---|---|
| `tests/test_window_control.py` | the logic in `_base.py` with a fake backend: events, end-event timing, `screen()`, the primary-display shift, `screen=` |
| `tests/test_find_screen.py` | the matching rules of `find_screen()` |
| `tests/test_displays.py` | EDID decoding, Windows device paths, matching toolkit displays to system displays |
| `tests/gui_check.py` | every operation on a real window, for one backend |
| `tests/multi_screen_check.py` | placement and identity on each display; macOS only, two or more displays |

One manual check was run on 2026-11-14: after switching the primary display from
the Kuycon to the iPad, `find_screen()` with the identity saved before the switch,
plus `set_frame(..., screen=)`, put the window back at the saved offset from the
Kuycon's corner on every backend.

## Untested cases

These cases have not been run. Each row says what could break and how to check it.

### Platforms

| Case | What could break | How to check |
|---|---|---|
| Linux, X11 | the shift from the bounding-box corner to the primary output; the XRandR ctypes structures; `system_id` as the output name; Qt's screen names matching output names | run `tests/gui_check.py` for each backend; print `window_control(fig).screens()` and compare with `xrandr --props` |
| Linux, Wayland | positions should be None and setting one should raise `NotSupportedError`; the identity fields should be None | run `tests/gui_check.py` under a Wayland session (Qt, GTK 3, GTK 4) |
| Windows | `EnumDisplayMonitors` and the registry EDID lookup; displays with negative coordinates; the device name `\\.\DISPLAY1` matching Qt and wx screen names | run `tests/gui_check.py`; print `screens()` and compare with the display settings |
| Display scaling on X11 and Windows | toolkits that report logical pixels while the system reports physical ones; matching assumes one scale for all displays, so mixed scaling (e.g. 100 % and 150 %) can leave displays without identity | print `screens()` with mixed scaling and check the identity fields |
| GTK 3 on X11 | `move()` and `get_position()` relative to the frame under different window managers | `tests/gui_check.py gtk3agg` under two or three window managers |
| Tk on Linux | `wm geometry` and the decoration sizes under different window managers | `tests/gui_check.py tkagg` |

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
| Floating on Linux and Windows | `-topmost`, `STAY_ON_TOP`, `WindowStaysOnTopHint` and `set_keep_above()` there; the Tk `manager.show` wrapper | `tests/gui_check.py` checks the reported state only; check the stacking by eye |

### Versions

| Case | What could break | How to check |
|---|---|---|
| PyQt5, PyQt6 | the enum lookup in `_qt.py` | `tests/gui_check.py qtagg` with each binding installed |
| Python 3.10 to 3.12 | syntax and library differences; `pyproject.toml` declares `>=3.10` | run the tests on each version |
| Released Matplotlib (3.8 and later) | backend class names used by `window_control()`; the macosx backend needs `_raw_nswindow_ptr`, which no release has yet | run the tests against each release |
| Tk 8.6 | `wm geometry` and `-topmost` behavior | `tests/gui_check.py tkagg` with Tk 8.6 |
