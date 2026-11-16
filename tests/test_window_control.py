"""Tests of the backend-independent logic in _base.py, with a fake backend.

FakeControl keeps its frame in memory, in toolkit coordinates, and calls
_geometry_changed() when the frame changes, as the toolkit hooks do. FakeCanvas records close_event
callbacks and hands out FakeTimers, which count down only when a test calls advance().
"""

import gc

import pytest

from matplotlib_window_control import EVENTS, Frame, Screen, WindowControl, _displays
from matplotlib_window_control._base import _backend_family


@pytest.fixture(autouse=True)
def no_system_displays(monkeypatch):
    # Keep the real displays of the machine running the tests out of the fakes.
    monkeypatch.setattr(_displays, "system_displays", lambda x11=False: [])


class FakeTimer:
    """A timer that counts down only when a test calls advance()."""

    def __init__(self, interval):
        self.interval = interval
        self.single_shot = False
        self.running = False
        self.remaining = None
        self.callbacks = []

    def add_callback(self, func):
        self.callbacks.append(func)

    def start(self):
        self.running = True
        self.remaining = self.interval

    def stop(self):
        self.running = False

    def advance(self, ms):
        if not self.running:
            return
        self.remaining -= ms
        if self.remaining <= 0:
            if self.single_shot:
                self.running = False
            else:
                self.remaining = self.interval
            for func in self.callbacks:
                func()


class FakeCanvas:
    def __init__(self):
        self.close_callbacks = []
        self.timers = []

    def mpl_connect(self, name, func):
        assert name == "close_event"
        self.close_callbacks.append(func)

    def new_timer(self, interval):
        timer = FakeTimer(interval)
        self.timers.append(timer)
        return timer

    def close(self):
        for func in self.close_callbacks:
            func(None)


class FakeManager:
    def __init__(self):
        self.canvas = FakeCanvas()


class FakeControl(WindowControl):
    backend = "fake"

    def __init__(self, manager=None, *, frame=Frame(0, 0, 100, 100), screens=(),
                 **kwargs):
        super().__init__(manager or FakeManager(), **kwargs)
        self.frame = frame
        self.fake_screens = list(screens)
        self.hook_calls = 0
        self.raised = []
        self.unhook_calls = 0

    def _get_frame(self):
        return self.frame

    def _set_frame(self, x, y, width, height):
        f = self.frame
        self.frame = Frame(f.x if x is None else x, f.y if y is None else y,
                           f.width if width is None else width,
                           f.height if height is None else height)
        self._geometry_changed()

    def _screens(self):
        return self.fake_screens

    def _raise_window(self, with_focus):
        self.raised.append(with_focus)

    def _hook(self):
        self.hook_calls += 1

    def _unhook(self):
        self.unhook_calls += 1
        super()._unhook()


def screen(name, x, y, w, h, primary=False):
    return Screen(name, Frame(x, y, w, h), Frame(x, y, w, h), primary)


def record(control, events=EVENTS):
    calls = []
    for name in events:
        control.connect(name, lambda frame, name=name: calls.append((name, frame)))
    return calls


def end_timer(control, event):
    return control._end_timers[event]


# -- screen() ------------------------------------------------------------------

# A primary display, one to its left with negative x, and one above it with
# negative y.
SCREENS = [
    screen("primary", 0, 0, 1920, 1080, primary=True),
    screen("left", -1280, 200, 1280, 1024),
    screen("top", 0, -1440, 2560, 1440),
]


@pytest.mark.parametrize("frame, expected", [
    (Frame(100, 100, 800, 600), "primary"),
    (Frame(-1000, 300, 600, 400), "left"),
    (Frame(500, -1000, 800, 600), "top"),
    # The window straddles primary and left; its center (-100, 400) is on left.
    (Frame(-500, 200, 800, 400), "left"),
])
def test_screen_contains_center(frame, expected):
    control = FakeControl(frame=frame, screens=SCREENS)
    assert control.screen().name == expected


def test_screen_none_outside_every_screen():
    # Center (-500, 0) is left of primary, above left, and left of top.
    control = FakeControl(frame=Frame(-600, -100, 200, 200), screens=SCREENS)
    assert control.screen() is None


def test_screen_edges_are_half_open():
    # A center exactly on x = 0 is the right edge of left and the left edge of
    # primary; it belongs to primary. List left first, so that screen() would
    # return it if its right edge counted as inside.
    left_first = [SCREENS[1], SCREENS[0]]
    control = FakeControl(frame=Frame(-50, 400, 100, 100), screens=left_first)
    assert control.screen().name == "primary"


def test_screen_none_without_positions():
    control = FakeControl(frame=Frame(None, None, 800, 600), screens=SCREENS)
    assert control.screen() is None


# -- origin -------------------------------------------------------------------

# Toolkit coordinates as GDK reports them on macOS for a 1288-point-wide
# display left of the primary one: (0, 0) is the corner of the bounding box.
GDK_SCREENS = [
    screen("primary", 1288, 0, 3072, 1728, primary=True),
    screen("left", 0, 0, 1288, 1024),
]


def test_frames_measured_from_primary_display():
    control = FakeControl(frame=Frame(1348, 91, 700, 500), screens=GDK_SCREENS)
    assert control.get_frame() == Frame(60, 91, 700, 500)
    assert [s.frame for s in control.screens()] == [
        Frame(0, 0, 3072, 1728), Frame(-1288, 0, 1288, 1024)]


def test_set_frame_converts_to_toolkit_coordinates():
    control = FakeControl(frame=Frame(1348, 91, 700, 500), screens=GDK_SCREENS)
    control.set_frame(-1228, 60)
    assert control.frame == Frame(60, 60, 700, 500)  # On the left display.
    control.set_frame(x=100)  # y stays as it is, in toolkit coordinates.
    assert control.frame == Frame(1388, 60, 700, 500)


def test_no_primary_display_means_no_shift():
    screens = [s._replace(primary=False) for s in GDK_SCREENS]
    control = FakeControl(frame=Frame(1348, 91, 700, 500), screens=screens)
    assert control.get_frame() == Frame(1348, 91, 700, 500)


def test_get_frame_relative_to_screen():
    control = FakeControl(frame=Frame(60, 60, 700, 500), screens=GDK_SCREENS)
    left = next(s for s in control.screens() if s.name == "left")
    assert control.get_frame(screen=left) == Frame(60, 60, 700, 500)
    primary = control.screens()[0]
    assert control.get_frame(screen=primary) == Frame(-1228, 60, 700, 500)


def test_set_frame_relative_to_screen():
    control = FakeControl(frame=Frame(1348, 91, 700, 500), screens=GDK_SCREENS)
    left = next(s for s in control.screens() if s.name == "left")
    control.set_frame(100, 50, screen=left)
    assert control.frame == Frame(100, 50, 700, 500)
    assert control.get_frame(screen=left) == Frame(100, 50, 700, 500)
    control.set_frame(y=80, screen=left)  # x stays as it is.
    assert control.frame == Frame(100, 80, 700, 500)


def test_frame_relative_to_screen_without_positions():
    control = FakeControl(frame=Frame(None, None, 700, 500), screens=GDK_SCREENS)
    left = next(s for s in control.screens() if s.name == "left")
    assert control.get_frame(screen=left) == Frame(None, None, 700, 500)


def test_screen_with_shifted_coordinates():
    control = FakeControl(frame=Frame(60, 60, 700, 500), screens=GDK_SCREENS)
    assert control.screen().name == "left"


@pytest.mark.parametrize("x11_client, system_id", [(False, None), (True, "eDP-1")])
def test_x11_client_reads_x_server_displays(monkeypatch, x11_client, system_id):
    # Qt and GDK under XWayland at 150 % scaling measure the display as
    # 2560 x 1440; XRandR measures it as 5120 x 2880 and names the output.
    def system_displays(x11=False):
        if not x11:  # A Wayland session.
            return []
        s = screen("eDP-1", 0, 0, 5120, 2880, primary=True)
        return [_displays.SystemDisplay(s._replace(system_id="eDP-1"), ("eDP-1",))]

    monkeypatch.setattr(_displays, "system_displays", system_displays)
    control = FakeControl(screens=[screen("", 0, 0, 2560, 1440, primary=True)])
    monkeypatch.setattr(control, "_x11_client", lambda: x11_client)
    assert [s.system_id for s in control.screens()] == [system_id]


# -- live events ---------------------------------------------------------------

def test_move_emits_only_move():
    control = FakeControl()
    calls = record(control, ["window_move", "window_resize"])
    control.set_frame(x=50)
    assert calls == [("window_move", Frame(50, 0, 100, 100))]


def test_resize_emits_only_resize():
    control = FakeControl()
    calls = record(control, ["window_move", "window_resize"])
    control.set_frame(height=300)
    assert calls == [("window_resize", Frame(0, 0, 100, 300))]


def test_move_and_resize_emit_both():
    control = FakeControl()
    calls = record(control, ["window_move", "window_resize"])
    control.set_frame(10, 20, 30, 40)
    assert [name for name, _ in calls] == ["window_move", "window_resize"]


def test_no_change_emits_nothing():
    control = FakeControl()
    calls = record(control)
    control.set_frame(0, 0, 100, 100)
    control._geometry_changed()
    assert calls == []


def test_changes_before_connect_are_not_reported():
    control = FakeControl()
    control.frame = Frame(500, 500, 100, 100)  # Moved before anyone listened.
    calls = record(control, ["window_move"])
    control._geometry_changed()
    assert calls == []


def test_frames_without_positions():
    control = FakeControl(frame=Frame(None, None, 100, 100))
    calls = record(control, ["window_move", "window_resize"])
    control.set_frame(width=200)
    assert calls == [("window_resize", Frame(None, None, 200, 100))]


def test_unknown_event_raises():
    with pytest.raises(ValueError, match="window_moved"):
        FakeControl().connect("window_moved", print)


# -- end events ----------------------------------------------------------------

def test_end_event_once_per_gesture():
    control = FakeControl()
    calls = record(control, ["window_move_end"])
    for x in (10, 20, 30):  # Three steps of one drag.
        control.set_frame(x=x)
    assert calls == []
    timer = end_timer(control, "window_move_end")
    assert timer.single_shot and timer.running
    timer.advance(250)
    timer.advance(250)  # A single-shot timer does not fire twice.
    assert calls == [("window_move_end", Frame(30, 0, 100, 100))]


def test_each_change_restarts_the_end_delay():
    control = FakeControl()
    calls = record(control, ["window_move_end"])
    control.set_frame(x=10)
    timer = end_timer(control, "window_move_end")
    timer.advance(200)
    control.set_frame(x=20)  # 200 ms after the first step: the drag goes on.
    timer.advance(200)
    assert calls == []  # 400 ms since the first step, 200 ms since the last.
    timer.advance(50)
    assert calls == [("window_move_end", Frame(20, 0, 100, 100))]


def test_end_event_reports_frame_when_timer_fires():
    control = FakeControl()
    calls = record(control, ["window_resize_end"])
    control.set_frame(width=200)
    control.frame = Frame(0, 0, 250, 100)  # Changed again, not yet reported.
    end_timer(control, "window_resize_end").advance(250)
    assert calls == [("window_resize_end", Frame(0, 0, 250, 100))]


def test_move_and_resize_have_separate_end_timers():
    control = FakeControl()
    calls = record(control, ["window_move_end", "window_resize_end"])
    control.set_frame(x=10)
    control.set_frame(width=200)
    end_timer(control, "window_move_end").advance(250)
    assert [name for name, _ in calls] == ["window_move_end"]
    assert end_timer(control, "window_resize_end").running


@pytest.mark.parametrize("kwargs, interval", [({}, 250), ({"end_delay": 0.1}, 100)])
def test_end_delay_sets_timer_interval(kwargs, interval):
    control = FakeControl(**kwargs)
    record(control, ["window_move_end"])
    control.set_frame(x=10)
    assert end_timer(control, "window_move_end").interval == interval


# -- connect, disconnect, close ------------------------------------------------

def test_hook_installed_once():
    control = FakeControl()
    record(control)
    assert control.hook_calls == 1


def test_disconnect():
    control = FakeControl()
    calls = []
    cid = control.connect("window_move", lambda frame: calls.append(frame))
    control.disconnect(cid)
    control.set_frame(x=10)
    assert calls == []


def test_bound_method_is_held_weakly():
    class Listener:
        calls = []

        def on_move(self, frame):
            Listener.calls.append(frame)

    control = FakeControl()
    listener = Listener()
    control.connect("window_move", listener.on_move)
    del listener
    gc.collect()
    control.set_frame(x=10)
    assert Listener.calls == []


def test_close_stops_events_and_pending_end_events():
    control = FakeControl()
    calls = record(control)
    control.set_frame(x=10)
    timer = end_timer(control, "window_move_end")
    calls.clear()
    control.manager.canvas.close()
    assert control.unhook_calls == 1
    assert not timer.running and control._end_timers == {}
    control.set_frame(x=20)
    timer.advance(250)
    assert calls == []


def test_connect_after_close_hooks_again():
    control = FakeControl()
    record(control, ["window_move"])
    control.manager.canvas.close()
    calls = record(control, ["window_resize"])
    assert control.hook_calls == 2
    control.set_frame(width=200)
    assert calls == [("window_resize", Frame(0, 0, 200, 100))]


# -- dispatch ------------------------------------------------------------------

@pytest.mark.parametrize("module, family", [
    ("matplotlib.backends.backend_macosx", "macosx"),
    ("matplotlib.backends.backend_qt", "qt"),
    ("matplotlib.backends._backend_tk", "tk"),
    ("matplotlib.backends.backend_wx", "wx"),
    ("matplotlib.backends._backend_gtk", "gtk"),
    ("matplotlib.backend_bases", ""),
])
def test_backend_family_from_base_class(module, family):
    # Backends subclass these managers (e.g. FigureManagerGTK3 subclasses
    # _FigureManagerGTK), so the family is found anywhere in the MRO.
    base = type("Base", (), {"__module__": module})
    manager = type("Manager", (base,), {"__module__": "somewhere.else"})()
    assert _backend_family(manager) == family


# -- raise_window ------------------------------------------------------------------

def test_raise_window_uses_toolkit_calls_without_nswindow():
    # Off macOS, and on macOS when no NSWindow is found, the toolkit raises.
    control = FakeControl()
    control.raise_window()
    control.raise_window(with_focus=True)
    assert control.raised == [False, True]
