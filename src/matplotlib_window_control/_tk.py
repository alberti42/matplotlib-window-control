"""Tk backends (tkagg, tkcairo): `wm geometry` and `wm attributes` on the Tk window."""

from __future__ import annotations

import re
import sys

from ._base import Frame, Screen, WindowControl

_GEOMETRY = re.compile(r"(\d+)x(\d+)\+(-?\d+)\+(-?\d+)")


class TkWindowControl(WindowControl):
    backend = "tk"

    def __init__(self, manager, **kwargs):
        super().__init__(manager, **kwargs)
        self.window = manager.window

    def _geometry(self):
        """Return the client size, the frame position, and the decoration sizes."""
        win = self.window
        win.update_idletasks()
        m = _GEOMETRY.fullmatch(win.wm_geometry())
        w, h, x, y = map(int, m.groups())
        # `wm geometry` gives the position of the outer frame and the size of
        # the client area; winfo_root{x,y} give the position of the client area.
        border = max(win.winfo_rootx() - x, 0)
        title = max(win.winfo_rooty() - y, 0)
        return w, h, x, y, border, title

    def get_frame(self):
        w, h, x, y, border, title = self._geometry()
        return Frame(x, y, w + 2 * border, h + title + border)

    def set_frame(self, x=None, y=None, width=None, height=None):
        w, h, x0, y0, border, title = self._geometry()
        x = x0 if x is None else int(x)
        y = y0 if y is None else int(y)
        w = w if width is None else int(width) - 2 * border
        h = h if height is None else int(height) - title - border
        self.window.wm_geometry(f"{w}x{h}+{x}+{y}")

    def screens(self):
        if sys.platform == "darwin":
            from ._macos import cocoa_screens
            return cocoa_screens()
        # Tk reports one screen: on X11 the whole X screen, on Windows the
        # primary display.
        win = self.window
        f = Frame(0, 0, win.winfo_screenwidth(), win.winfo_screenheight())
        return [Screen("", f, f, True)]

    def get_floating(self):
        return bool(int(self.window.wm_attributes("-topmost")))

    def set_floating(self, floating):
        self._floating = bool(floating)
        self.window.wm_attributes("-topmost", 1 if floating else 0)
        if floating and not getattr(self, "_show_wrapped", False):
            # FigureManagerTk.show() raises the window by setting -topmost to
            # 1 and then 0, and plt.show() and plt.pause() call it. Set
            # -topmost again after it.
            show = self.manager.show

            def show_and_keep_floating(*args, **kwargs):
                show(*args, **kwargs)
                if self._floating:
                    self.window.wm_attributes("-topmost", 1)

            self.manager.show = show_and_keep_floating
            self._show_wrapped = True

    def _hook(self):
        # Every child widget of the window also has the window's bind tag, so
        # filter on event.widget. During the event, winfo_rooty can still hold
        # the old value; read the geometry once Tk is idle. The binding is
        # never removed: on Python < 3.13, unbind() removes every binding for
        # the sequence.
        if getattr(self, "_bound", False):
            return
        self._bound = True
        self.window.bind(
            "<Configure>",
            lambda event: (self.window.after_idle(self._geometry_changed)
                           if event.widget is self.window else None),
            add="+")
