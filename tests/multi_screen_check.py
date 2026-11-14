"""Place a window on each display: python multi_screen_check.py BACKEND.

macOS only, and useful only with two or more displays. Cocoa's display list is
the reference: the check compares the backend's screens() with it, and compares
where the NSWindow is, in Cocoa coordinates, with where the window was placed.
Exits with status 0 if all checks pass, and 2 if there is only one display or
the backend cannot report window positions.
"""

import sys

import matplotlib

matplotlib.use(sys.argv[1])
# Typing while a test window has focus would trigger Matplotlib's shortcuts;
# "s" opens a save dialog that blocks the check until it times out.
for key in [k for k in matplotlib.rcParams if k.startswith("keymap.")]:
    matplotlib.rcParams[key] = []
import matplotlib.pyplot as plt  # noqa: E402
from AppKit import NSApplication, NSScreen  # noqa: E402

import json  # noqa: E402

from matplotlib_window_control import find_screen, window_control  # noqa: E402
from matplotlib_window_control._displays import system_displays  # noqa: E402

TOL = 2
failures = []


def close(a, b):
    return all(p is None or q is None or abs(p - q) <= TOL for p, q in zip(a, b))


def check(name, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'} {name} {detail}")
    if not ok:
        failures.append(name)


def cocoa_reference():
    """Return (name, frame, work area) for each display, in top-left coordinates."""
    screens = NSScreen.screens()
    primary_height = screens[0].frame().size.height

    def flip(rect):
        (x, y), (w, h) = rect
        return (x, primary_height - (y + h), w, h)

    return [(str(s.localizedName()), flip(s.frame()), flip(s.visibleFrame()))
            for s in screens], primary_height


def visible_nswindows():
    return [w for w in NSApplication.sharedApplication().windows()
            if w.isVisible() and w.frame().size.width > 100]


if len(NSScreen.screens()) < 2:
    print("only one display")
    sys.exit(2)

fig, ax = plt.subplots()
ax.plot([1, 3, 2])
plt.show(block=False)
plt.pause(0.6)
# Read the reference once the application runs: before that, visibleFrame
# does not leave out the menu bar on secondary displays.
reference, primary_height = cocoa_reference()
win = window_control(fig)
print("backend:", win.backend)
if win.get_frame().x is None:
    print("the backend cannot report window positions")
    sys.exit(2)

# 1. The backend reports the same displays as Cocoa, the primary first.
screens = win.screens()
check("number of screens", len(screens) == len(reference), [s.name for s in screens])
for name, frame, work_area in reference:
    match = [s for s in screens if close(s.frame, frame)]
    check(f"screen {name!r} frame", len(match) == 1, frame)
    if match:
        check(f"screen {name!r} work area", close(match[0].work_area, work_area),
              (match[0].work_area, work_area))
check("primary first", screens[0].primary and close(screens[0].frame, reference[0][1]),
      screens[0])

# 2. Place the window inside each display's work area.
for name, frame, work_area in reference:
    wx, wy, ww, wh = work_area
    target = (wx + 60, wy + 60, min(700, ww - 120), min(500, wh - 120))
    win.set_frame(*target)
    plt.pause(0.6)
    got = win.get_frame()
    check(f"on {name!r}: get_frame", close(got, target), got)
    s = win.screen()
    check(f"on {name!r}: screen()", s is not None and close(s.frame, frame),
          s and s.name)
    # Where the NSWindow is, in Cocoa coordinates (origin bottom-left, y up).
    x, y, w, h = target
    expected = (x, primary_height - (y + h), w, h)
    nswindows = visible_nswindows()
    native = [tuple(n.frame()[0]) + tuple(n.frame()[1]) for n in nswindows]
    check(f"on {name!r}: NSWindow frame", any(close(n, expected) for n in native),
          (native, expected))

# 3. Every display carries the system's identity, matched to the right one.
system = {d.screen.system_id: d.screen for d in system_displays()}
screens = win.screens()
for s in screens:
    ref = system.get(s.system_id)
    check(f"identity of {s.name!r}",
          ref is not None and close(ref.frame, s.frame) and s.name
          and (s.manufacturer, s.product, s.serial) == (ref.manufacturer, ref.product,
                                                        ref.serial),
          (s.system_id, s.manufacturer, s.product, s.serial))

# 4. Frames relative to a display.
for s in screens:
    win.set_frame(60, 60, 600, 400, screen=s)
    plt.pause(0.6)
    got = win.get_frame(screen=s)
    check(f"relative to {s.name!r}: get_frame", close(got, (60, 60, 600, 400)), got)
    x, y = s.frame.x + 60, s.frame.y + 60
    expected = (x, primary_height - (y + 400), 600, 400)
    native = [tuple(n.frame()[0]) + tuple(n.frame()[1]) for n in visible_nswindows()]
    check(f"relative to {s.name!r}: NSWindow frame",
          any(close(n, expected) for n in native), (native, expected))

# 5. A display saved as JSON is found again.
for s in screens:
    saved = json.loads(json.dumps(s._asdict()))
    found = find_screen(saved, win.screens())
    check(f"find_screen {s.name!r}", found is not None and found.system_id == s.system_id,
          found and found.name)

plt.close(fig)
plt.pause(0.3)
print("failures:", failures)
sys.exit(1 if failures else 0)
