"""Run every WindowControl operation on a real window: python gui_check.py BACKEND.

Exits with status 0 if all checks pass. Prints one line per check.
"""

import sys

import matplotlib

matplotlib.use(sys.argv[1])
import matplotlib.pyplot as plt  # noqa: E402

from matplotlib_window_control import NotSupportedError, window_control  # noqa: E402

TOL = 2  # Toolkits round to whole pixels.


def settle(seconds=0.6):
    plt.pause(seconds)


def close(a, b):
    return all(p is None or q is None or abs(p - q) <= TOL for p, q in zip(a, b))


def native_level(frame):
    """Return the level of the visible NSWindow with this frame (macOS), or None.

    Every toolkit on macOS draws into an NSWindow; find it by its frame,
    converted to top-left coordinates.
    """
    if sys.platform != "darwin" or frame.x is None:
        return None
    from AppKit import NSApplication, NSScreen
    primary_height = NSScreen.screens()[0].frame().size.height
    for nswindow in NSApplication.sharedApplication().windows():
        (x, y), (w, h) = nswindow.frame()
        if nswindow.isVisible() and close((x, primary_height - (y + h), w, h), frame):
            return nswindow.level()
    return None


def check(name, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'} {name} {detail}")
    if not ok:
        failures.append(name)


failures = []
fig, ax = plt.subplots()
ax.plot([1, 3, 2])
plt.show(block=False)
settle()

win = window_control(fig, end_delay=0.2)
check("same object on second call", window_control(fig) is win)
print("backend:", win.backend)
f0 = win.get_frame()
check("get_frame", f0.width > 0 and f0.height > 0, f0)

positions = f0.x is not None
target = (200, 150, 700, 500)
if positions:
    win.set_frame(*target)
    settle()
    f1 = win.get_frame()
    check("set_frame", close(f1, target), f1)
    win.set_frame(x=260)
    settle()
    f2 = win.get_frame()
    check("set_frame x only", close(f2, (260, 150, 700, 500)), f2)
else:
    try:
        win.set_frame(*target)
        check("set_frame raises NotSupportedError", False)
    except NotSupportedError:
        check("set_frame raises NotSupportedError", True)
    win.set_frame(width=700, height=500)
    settle()
    f1 = win.get_frame()
    check("set_frame size only", close(f1, (None, None, 700, 500)), f1)

screens = win.screens()
check("screens", len(screens) > 0, screens)
if positions:
    check("screen", win.screen() is not None, win.screen())

try:
    win.set_floating(True)
    settle(0.3)
    on, level_on = win.get_floating(), native_level(win.get_frame())
    win.set_floating(False)
    settle(0.3)
    off, level_off = win.get_floating(), native_level(win.get_frame())
    check("floating round trip", on and not off, (on, off))
    if sys.platform == "darwin":
        # get_floating() can only report what the toolkit reports; the
        # NSWindow level is what decides the stacking.
        check("floating NSWindow level", level_on and level_on > 0 and level_off == 0,
              (level_on, level_off))
except NotSupportedError as e:
    print("SKIP floating:", e)

events = []
for name in ("window_move", "window_resize", "window_move_end", "window_resize_end"):
    win.connect(name, lambda frame, name=name: events.append((name, frame)))
f = win.get_frame()
if positions:
    win.set_frame(f.x + 40, f.y + 30)
    settle()
win.set_frame(width=f.width - 60, height=f.height - 40)
settle()
names = {e[0] for e in events}
expected = ({"window_move", "window_move_end"} if positions else set()) | {
    "window_resize", "window_resize_end"}
check("events", expected <= names, sorted(names))
ends = [e for e in events if e[0].endswith("_end")]
check("one end event per gesture", len(ends) == len(expected) // 2, ends)

# Each argument of set_frame alone keeps the other three.
f = win.get_frame()
single = [("width", f.width - 50), ("height", f.height - 50)]
if positions:
    single = [("y", f.y + 25)] + single
for name, value in single:
    win.set_frame(**{name: value})
    settle()
    f = f._replace(**{name: value})
    check(f"set_frame {name} only", close(win.get_frame(), f), win.get_frame())

calls = []
cid = win.connect("window_resize", lambda frame: calls.append(frame))
win.disconnect(cid)
win.set_frame(width=f.width + 50)
settle()
check("disconnect", calls == [], calls)

# A second figure has its own control, and changing it leaves the first alone.
fig2 = plt.figure()
plt.show(block=False)
settle()
win2 = window_control(fig2)
check("second figure, second control", win2 is not win)
f = win.get_frame()
win2.set_frame(width=f.width - 100, height=f.height - 100,
               **({"x": f.x + 100, "y": f.y + 100} if positions else {}))
settle()
check("second figure leaves first alone", close(win.get_frame(), f), win.get_frame())
plt.close(fig2)
settle(0.3)

n = len(events)
plt.close(fig)
settle(0.3)
check("no events after close", len(events) == n, events[n:])

# The README's recipe: set the frame before the window is first shown.
with plt.ioff():
    fig3 = plt.figure()
win3 = window_control(fig3)
target = (300, 200, 600, 450) if positions else (None, None, 600, 450)
win3.set_frame(*target)
fig3.show()
settle()
check("set_frame before show", close(win3.get_frame(), target), win3.get_frame())
plt.close(fig3)
settle(0.3)
print("failures:", failures)
sys.exit(1 if failures else 0)
