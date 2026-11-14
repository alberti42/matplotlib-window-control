"""Tests of the backend-independent logic in _base.py, with a fake backend.

FakeControl keeps its frame in memory and calls _geometry_changed() when the
frame changes, as the toolkit hooks do. FakeCanvas records close_event
callbacks and hands out FakeTimers, which count down only when a test calls advance().
"""

import gc

import pytest

from matplotlib_window_control import EVENTS, Frame, Screen, WindowControl
from matplotlib_window_control._base import _backend_family


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
        self.unhook_calls = 0

    def get_frame(self):
        return self.frame

    def set_frame(self, x=None, y=None, width=None, height=None):
        f = self.frame
        self.frame = Frame(f.x if x is None else x, f.y if y is None else y,
                           f.width if width is None else width,
                           f.height if height is None else height)
        self._geometry_changed()

    def screens(self):
        return self.fake_screens

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
