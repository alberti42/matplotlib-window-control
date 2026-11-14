"""Backend-independent part of the window control: data types, events, dispatch."""

from __future__ import annotations

from typing import Callable, NamedTuple

from matplotlib import cbook

EVENTS = ("window_move", "window_resize", "window_move_end", "window_resize_end")


class Frame(NamedTuple):
    """A rectangle in global screen coordinates.

    The origin is the top-left corner of the primary screen and *y* increases
    downward. Units are the toolkit's logical pixels (points on macOS). For a
    window, the rectangle is the outer frame, including the title bar.

    *x* and *y* are None when the toolkit cannot report positions (GTK 4, and
    Qt or GTK 3 on Wayland).
    """

    x: float | None
    y: float | None
    width: float
    height: float


class Screen(NamedTuple):
    """A display: its geometry from the toolkit, its identity from the system.

    The identity fields are None when the system does not report them. Use
    `find_screen` to find a saved display among the attached ones.
    """

    name: str
    frame: Frame
    work_area: Frame  # The frame without menu bar, dock or task bar.
    primary: bool
    # The three-letter manufacturer code from the monitor's EDID, e.g. "GKT".
    manufacturer: str | None = None
    # The product code from the monitor's EDID.
    product: int | None = None
    # The serial number from the monitor's EDID; many monitors report none.
    serial: str | None = None
    # The system's identifier for the display: the display UUID on macOS, the
    # output (connector) name on X11, e.g. "DP-1", and the monitor device path
    # on Windows. It tells identical monitors without serial numbers apart.
    system_id: str | None = None


_IDENTITY = ("name", "manufacturer", "product", "serial", "system_id")


def find_screen(saved, screens):
    """Return the display in *screens* that is the monitor *saved*, or None.

    *saved* is a `Screen`, or a mapping with its identity fields, such as
    ``screen._asdict()`` stored as JSON. The first rule that matches exactly
    one display decides:

    1. Same manufacturer, product and serial number.
    2. Same manufacturer, product and `Screen.system_id`, for monitors without
       serial numbers: the same model on the same port.
    3. Same manufacturer and product, if one such display is attached.
    4. Same name, if one such display is attached.

    A display of the same model with a different serial number is a different
    monitor; no rule matches it. Return None if no rule matches exactly one
    display.
    """
    if isinstance(saved, Screen):
        want = {k: getattr(saved, k) for k in _IDENTITY}
    else:
        want = {k: saved.get(k) for k in _IDENTITY}
    model = (want["manufacturer"], want["product"])
    candidates = [s for s in screens
                  if not (want["serial"] and s.serial and s.serial != want["serial"])]

    def same_model(s):
        return (s.manufacturer, s.product) == model

    rules = []
    if want["serial"]:
        rules.append(lambda s: same_model(s) and s.serial == want["serial"])
    if want["system_id"]:
        rules.append(lambda s: same_model(s) and s.system_id == want["system_id"])
    if model != (None, None):
        rules.append(same_model)
    if want["name"]:
        rules.append(lambda s: s.name == want["name"])
    for rule in rules:
        found = [s for s in candidates if rule(s)]
        if len(found) == 1:
            return found[0]
    return None


class UnsupportedBackendError(TypeError):
    """The figure is not shown by a GUI backend that this package supports."""


class NotSupportedError(NotImplementedError):
    """The toolkit, or the display server, cannot perform this operation."""


class WindowControl:
    """Control of the window that shows one Matplotlib figure.

    Do not instantiate this class; call `window_control` with a figure.
    Backend modules subclass it and implement the methods that raise
    `NotImplementedError` here.
    """

    backend = ""

    def __init__(self, manager, *, end_delay=0.25):
        self.manager = manager
        self._callbacks = cbook.CallbackRegistry(signals=EVENTS)
        self._end_delay_ms = int(end_delay * 1000)
        self._end_timers = {}
        self._hooked = False
        self._last = None
        manager.canvas.mpl_connect("close_event", lambda event: self._unhook())

    # -- geometry -----------------------------------------------------------
    #
    # Backend modules implement _get_frame, _set_frame and _screens in the
    # toolkit's own coordinates. The public methods shift them so that (0, 0)
    # is the top-left corner of the primary display: toolkits differ there
    # (GDK on macOS and X11 put it at the corner of the bounding box of all
    # displays).

    def _get_frame(self) -> Frame:
        """Return the outer frame of the window, in toolkit coordinates."""
        raise NotImplementedError

    def _set_frame(self, x, y, width, height) -> None:
        """Set the outer frame, in toolkit coordinates; None keeps a value."""
        raise NotImplementedError

    def _screens(self) -> list[Screen]:
        """Return the displays, in toolkit coordinates."""
        raise NotImplementedError

    def _origin(self, screens=None):
        """Return the top-left corner of the primary display, in toolkit coordinates."""
        for s in self._screens() if screens is None else screens:
            if s.primary:
                return s.frame.x, s.frame.y
        return 0, 0

    def _corner(self, screen):
        """Return the point that *x* and *y* are measured from, in toolkit coordinates."""
        ox, oy = self._origin()
        if screen is not None:
            ox, oy = ox + screen.frame.x, oy + screen.frame.y
        return ox, oy

    def get_frame(self, screen: Screen | None = None) -> Frame:
        """Return the outer frame of the window.

        With *screen*, a `Screen` from `screens` or `find_screen`, *x* and *y*
        are measured from the top-left corner of that display.
        """
        f = self._get_frame()
        if f.x is None:
            return f
        ox, oy = self._corner(screen)
        return f._replace(x=f.x - ox, y=f.y - oy)

    def set_frame(self, x=None, y=None, width=None, height=None, *,
                  screen: Screen | None = None) -> None:
        """Move and/or resize the window so that its outer frame is the given one.

        Pass None for *x* and *y* to keep the position, or for *width* and
        *height* to keep the size. With *screen*, a `Screen` from `screens` or
        `find_screen`, *x* and *y* are measured from the top-left corner of
        that display.
        """
        if x is not None or y is not None:
            ox, oy = self._corner(screen)
            x = None if x is None else x + ox
            y = None if y is None else y + oy
        self._set_frame(x, y, width, height)

    def screens(self) -> list[Screen]:
        """Return the displays known to the toolkit; the primary one first."""
        screens = self._screens()
        ox, oy = self._origin(screens)

        def shifted(f):
            return f._replace(x=f.x - ox, y=f.y - oy)

        return [s._replace(frame=shifted(s.frame), work_area=shifted(s.work_area))
                for s in screens]

    def screen(self) -> Screen | None:
        """Return the display that contains the center of the window.

        Return None if no display contains it, or if the toolkit cannot report
        the window position.
        """
        f = self.get_frame()
        if f.x is None:
            return None
        cx, cy = f.x + f.width / 2, f.y + f.height / 2
        for s in self.screens():
            sf = s.frame
            if sf.x <= cx < sf.x + sf.width and sf.y <= cy < sf.y + sf.height:
                return s
        return None

    # -- stacking -----------------------------------------------------------

    def get_floating(self) -> bool:
        """Return whether the window stays above windows that are not floating."""
        raise NotImplementedError

    def set_floating(self, floating: bool) -> None:
        """Make the window stay above windows that are not floating, or undo it."""
        raise NotImplementedError

    # -- events -------------------------------------------------------------

    def connect(self, event: str, func: Callable[[Frame], object]) -> int:
        """Call *func(frame)* when *event* happens; return a connection id.

        *event* is one of:

        - ``"window_move"``, ``"window_resize"``: each time the toolkit reports
          a new position or size, also during a drag.
        - ``"window_move_end"``, ``"window_resize_end"``: once, when no move or
          resize has been reported for *end_delay* seconds.

        *frame* is the outer frame after the change. As with
        `matplotlib.cbook.CallbackRegistry`, a bound method is held through a
        weak reference.
        """
        if event not in EVENTS:
            raise ValueError(f"{event!r} is not one of {EVENTS}")
        cid = self._callbacks.connect(event, func)
        if not self._hooked:
            self._last = self.get_frame()
            self._hook()
            self._hooked = True
        return cid

    def disconnect(self, cid: int) -> None:
        """Remove the callback with connection id *cid*."""
        self._callbacks.disconnect(cid)

    def _hook(self):
        """Ask the toolkit to call `_geometry_changed` on moves and resizes."""
        raise NotImplementedError

    def _unhook(self):
        """Undo `_hook`; called when the figure is closed."""
        # Drop the timers while the toolkit objects still exist; some backends
        # stop a timer again when it is garbage-collected.
        for timer in self._end_timers.values():
            timer.stop()
        self._end_timers.clear()
        self._hooked = False

    def _geometry_changed(self):
        if not self._hooked:
            return
        frame = self.get_frame()
        last, self._last = self._last, frame
        if last is None:
            return
        if (frame.x, frame.y) != (last.x, last.y):
            self._callbacks.process("window_move", frame)
            self._restart_end_timer("window_move_end")
        if (frame.width, frame.height) != (last.width, last.height):
            self._callbacks.process("window_resize", frame)
            self._restart_end_timer("window_resize_end")

    def _restart_end_timer(self, event):
        timer = self._end_timers.get(event)
        if timer is None:
            timer = self.manager.canvas.new_timer(interval=self._end_delay_ms)
            timer.single_shot = True
            timer.add_callback(
                lambda: self._callbacks.process(event, self.get_frame()))
            self._end_timers[event] = timer
        timer.stop()
        timer.start()


def _backend_family(manager) -> str:
    modules = {cls.__module__ for cls in type(manager).__mro__}
    if "matplotlib.backends.backend_macosx" in modules:
        return "macosx"
    if "matplotlib.backends.backend_qt" in modules:
        return "qt"
    if "matplotlib.backends._backend_tk" in modules:
        return "tk"
    if "matplotlib.backends.backend_wx" in modules:
        return "wx"
    if "matplotlib.backends._backend_gtk" in modules:
        return "gtk"
    return ""


def window_control(figure, *, end_delay=0.25) -> WindowControl:
    """Return the `WindowControl` for the window that shows *figure*.

    *figure* is a `~matplotlib.figure.Figure` or its figure manager. Repeated
    calls for the same figure return the same object; *end_delay* applies only
    to the first call.
    """
    manager = getattr(getattr(figure, "canvas", None), "manager", figure)
    control = getattr(manager, "_matplotlib_window_control", None)
    if control is not None:
        return control
    family = _backend_family(manager)
    if family == "macosx":
        from ._macos import MacOSWindowControl as cls
    elif family == "qt":
        from ._qt import QtWindowControl as cls
    elif family == "tk":
        from ._tk import TkWindowControl as cls
    elif family == "wx":
        from ._wx import WxWindowControl as cls
    elif family == "gtk":
        from ._gtk import GtkWindowControl as cls
    else:
        raise UnsupportedBackendError(
            f"{type(manager).__name__} is not the figure manager of a supported "
            "GUI backend (macosx, Qt, Tk, wx, GTK)")
    control = cls(manager, end_delay=end_delay)
    manager._matplotlib_window_control = control
    return control
