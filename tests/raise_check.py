"""Check raise_window() across applications: python raise_check.py BACKEND.

macOS only. Starts raise_helper.py, a second application whose window covers
ours and which is active, then checks that raise_window() brings our window in
front without taking focus, and that raise_window(with_focus=True) also makes
our application active and our window key. Exits with status 0 if all checks
pass.
"""

import subprocess
import sys
from pathlib import Path

import matplotlib

matplotlib.use(sys.argv[1])
for key in [k for k in matplotlib.rcParams if k.startswith("keymap.")]:
    matplotlib.rcParams[key] = []
# plt.pause() calls manager.show(), which raises the window again when this is
# on, and on Qt also activates it; the check must see only raise_window().
matplotlib.rcParams["figure.raise_window"] = False
# plt.pause() calls manager.show(), which raises the window again when this is
# on, and on Qt also activates it; the check must see only raise_window().
matplotlib.rcParams["figure.raise_window"] = False
import matplotlib.pyplot as plt  # noqa: E402
import os  # noqa: E402

from AppKit import (  # noqa: E402
    NSApplication,
    NSRunningApplication,
    NSWindow,
    NSWorkspace,
)

from matplotlib_window_control import window_control  # noqa: E402

ALL_APPLICATIONS = 1  # NSWindowNumberListAllApplications
failures = []


def check(name, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'} {name} {detail}")
    if not ok:
        failures.append(name)


def front_to_back():
    return list(NSWindow.windowNumbersWithOptions_(ALL_APPLICATIONS))


def in_front(a, b):
    order = front_to_back()
    return a in order and b in order and order.index(a) < order.index(b)


def active():
    return NSRunningApplication.currentApplication().isActive()


def active_application():
    """Return "us", "helper", or the name of the active application."""
    frontmost = NSWorkspace.sharedWorkspace().frontmostApplication()
    if frontmost is None:
        return None
    pid = frontmost.processIdentifier()
    if pid == os.getpid():
        return "us"
    if pid == helper.pid:
        return "helper"
    return str(frontmost.localizedName())


def state():
    """Positions of our window and the helper's, front first, and the active app."""
    order = front_to_back()
    position = {n: order.index(n) if n in order else None for n in (ours, theirs)}
    return (f"ours at {position[ours]}, helper at {position[theirs]}, "
            f"active: {active_application()}")


def helper_to_front():
    """Put the helper's window in front of ours, with our application inactive.

    Activation is cooperative on macOS 14 and later: yield it to the helper,
    which then asks for it. If another application is active, it stays so.
    """
    app = NSApplication.sharedApplication()
    if active() and app.respondsToSelector_("yieldActivationToApplication:"):
        app.yieldActivationToApplication_(
            NSRunningApplication.runningApplicationWithProcessIdentifier_(helper.pid))
    helper.stdin.write("activate\n")
    helper.stdin.flush()
    helper.stdout.readline()
    return wait_for(lambda: in_front(theirs, ours) and not active())


def wait_for(condition, seconds=3.0):
    """Process events until *condition()* holds or *seconds* pass."""
    for _ in range(int(seconds / 0.1)):
        if condition():
            return True
        plt.pause(0.1)
    return condition()


fig, ax = plt.subplots()
ax.plot([1, 3, 2])
plt.show(block=False)
plt.pause(0.6)
win = window_control(fig)
if win.get_frame().x is None:  # GTK 4: no positions.
    win.set_frame(width=700, height=500)
else:
    win.set_frame(200, 150, 700, 500)
plt.pause(0.5)
nswindow = win._nswindow()
check("NSWindow found", nswindow is not None)
if nswindow is None:
    sys.exit(1)
ours = nswindow.windowNumber()
theirs = None

(x, y), (w, h) = nswindow.frame()
helper = subprocess.Popen(
    [sys.executable, str(Path(__file__).with_name("raise_helper.py")),
     str(x), str(y), str(w), str(h)],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
try:
    theirs = int(helper.stdout.readline())
    check("before: helper in front, our application inactive", helper_to_front(),
          state())
    before = active_application()

    win.raise_window()
    check("raise_window(): ours in front", wait_for(lambda: in_front(ours, theirs)),
          state())
    plt.pause(0.5)
    check("raise_window(): the active application does not change",
          active_application() == before, f"before: {before}; now: {state()}")

    check("before: helper in front again, our application inactive",
          helper_to_front(), state())

    win.raise_window(with_focus=True)
    check("raise_window(with_focus=True): ours in front, our application active",
          wait_for(lambda: in_front(ours, theirs) and active()), state())
    check("raise_window(with_focus=True): our window key",
          wait_for(nswindow.isKeyWindow))
finally:
    helper.stdin.close()
    helper.wait(timeout=10)
plt.close(fig)
plt.pause(0.3)
print("failures:", failures)
sys.exit(1 if failures else 0)
