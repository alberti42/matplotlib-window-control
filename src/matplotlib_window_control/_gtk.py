"""GTK backends (gtk3agg, gtk3cairo, gtk4agg, gtk4cairo): Gtk.Window and Gdk.Monitor calls.

GTK 4 has no API for window positions, because Wayland gives clients none.
GTK 3 has one, which works on X11, Windows and macOS but not on Wayland.
"""

from __future__ import annotations

from gi.repository import GLib, Gdk, Gtk

from ._base import Frame, NotSupportedError, Screen, WindowControl

GTK4 = Gtk.get_major_version() >= 4


def _frame(rect):
    return Frame(rect.x, rect.y, rect.width, rect.height)


def _wayland(display):
    return "Wayland" in type(display).__name__


def _quartz(display):
    return "Quartz" in type(display).__name__


class GtkWindowControl(WindowControl):
    backend = "gtk4" if GTK4 else "gtk3"

    def __init__(self, manager, **kwargs):
        super().__init__(manager, **kwargs)
        self.window = manager.window
        self._handlers = []

    def _no_positions(self):
        return GTK4 or _wayland(self.window.get_display())

    def _gdk_frame(self):
        """Return the outer frame in GDK coordinates."""
        # GDK knows the window, and the size of its decorations, only once the
        # window is realized. show() realizes it; realize() does it without
        # showing.
        self.window.realize()
        return _frame(self.window.get_window().get_frame_extents())

    def _get_frame(self):
        win = self.window
        if GTK4:
            return Frame(None, None, win.get_width(), win.get_height())
        f = self._gdk_frame()
        if self._no_positions():
            return f._replace(x=None, y=None)
        return f

    def _set_frame(self, x, y, width, height):
        win = self.window
        if (x is not None or y is not None) and self._no_positions():
            raise NotSupportedError(
                "GTK 4 and Wayland do not let clients position windows")
        if GTK4:
            if width is not None or height is not None:
                win.set_default_size(
                    int(win.get_width() if width is None else width),
                    int(win.get_height() if height is None else height))
            return
        f = self._gdk_frame()
        if x is not None or y is not None:
            gx = f.x if x is None else x
            gy = f.y if y is None else y
            # move() takes the coordinates that get_position() returns, except
            # on macOS, where move() places the client area but get_position()
            # returns the outer frame.
            if _quartz(win.get_display()):
                _, px, py = win.get_window().get_origin()
            else:
                px, py = win.get_position()
            win.move(int(gx + px - f.x), int(gy + py - f.y))
        if width is not None or height is not None:
            # resize() sets the size without decorations.
            w, h = win.get_size()
            dw, dh = f.width - w, f.height - h
            win.resize(int((f.width if width is None else width) - dw),
                       int((f.height if height is None else height) - dh))

    def _screens(self):
        display = self.window.get_display()
        if GTK4:
            monitors = display.get_monitors()
            ms = [monitors.get_item(i) for i in range(monitors.get_n_items())]
            # GTK 4 has no primary monitor and no work area.
            return [Screen(m.get_model() or m.get_connector() or "",
                           _frame(m.get_geometry()), _frame(m.get_geometry()), False)
                    for m in ms]
        # GDK on macOS and on X11 puts (0, 0) at the top-left of the bounding
        # box of all monitors; the base class shifts to the primary monitor.
        ms = [display.get_monitor(i) for i in range(display.get_n_monitors())]
        ms.sort(key=lambda m: not m.is_primary())
        return [Screen(m.get_model() or "", _frame(m.get_geometry()),
                       _frame(m.get_workarea()), m.is_primary())
                for m in ms]

    def get_floating(self):
        if GTK4:
            raise NotSupportedError("GTK 4 has no keep-above API")
        if _quartz(self.window.get_display()):
            # GDK on macOS applies keep-above but does not report the ABOVE
            # state; return the value last set.
            return getattr(self, "_floating", False)
        gdk_window = self.window.get_window()
        return (gdk_window is not None
                and bool(gdk_window.get_state() & Gdk.WindowState.ABOVE))

    def set_floating(self, floating):
        if GTK4:
            raise NotSupportedError("GTK 4 has no keep-above API")
        self._floating = bool(floating)
        self.window.set_keep_above(self._floating)

    def _changed_later(self, *args):
        # The frame extents are updated after configure-event; read them later.
        GLib.idle_add(lambda: self._geometry_changed() and False)
        return False  # Let GTK and Matplotlib handle the event as usual.

    def _hook(self):
        signals = (["notify::default-width", "notify::default-height"] if GTK4
                   else ["configure-event"])
        self._handlers = [self.window.connect(s, self._changed_later) for s in signals]

    def _unhook(self):
        for handler in self._handlers:
            if self.window.handler_is_connected(handler):
                self.window.disconnect(handler)
        self._handlers.clear()
        super()._unhook()
