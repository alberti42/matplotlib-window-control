"""Tk backends (tkagg, tkcairo): `wm geometry` and `wm attributes` on the Tk window."""

from __future__ import annotations

import ctypes
import re
import sys

from ._base import Frame, Screen, WindowControl

_GEOMETRY = re.compile(r"(\d+)x(\d+)\+(-?\d+)\+(-?\d+)")


class _X11:
    """The libX11 calls that read a window's `_NET_FRAME_EXTENTS`, on one connection."""

    def __init__(self, display_name):
        import ctypes.util

        path = ctypes.util.find_library("X11")
        if not path:
            raise OSError("libX11 not found")
        x11 = self.lib = ctypes.CDLL(path)
        p, ulong = ctypes.c_void_p, ctypes.c_ulong
        x11.XOpenDisplay.restype = p
        x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
        x11.XInternAtom.restype = ulong
        x11.XInternAtom.argtypes = [p, ctypes.c_char_p, ctypes.c_int]
        x11.XQueryTree.argtypes = [p, ulong, ctypes.POINTER(ulong), ctypes.POINTER(ulong),
                                   ctypes.POINTER(ctypes.POINTER(ulong)),
                                   ctypes.POINTER(ctypes.c_uint)]
        x11.XGetWindowProperty.argtypes = [
            p, ulong, ulong, ctypes.c_long, ctypes.c_long, ctypes.c_int, ulong,
            ctypes.POINTER(ulong), ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ulong),
            ctypes.POINTER(ulong), ctypes.POINTER(ctypes.POINTER(ctypes.c_ubyte))]
        x11.XFree.argtypes = [p]
        self.display = x11.XOpenDisplay(display_name.encode())
        if not self.display:
            raise OSError(f"cannot open the X display {display_name!r}")
        self.atom = x11.XInternAtom(self.display, b"_NET_FRAME_EXTENTS", False)

    def parent(self, window):
        x11, ulong = self.lib, ctypes.c_ulong
        root, parent, n = ulong(), ulong(), ctypes.c_uint()
        children = ctypes.POINTER(ulong)()
        if not x11.XQueryTree(self.display, window, ctypes.byref(root), ctypes.byref(parent),
                              ctypes.byref(children), ctypes.byref(n)):
            return None
        if children:
            x11.XFree(children)
        return parent.value

    def frame_extents(self, window):
        """Return _NET_FRAME_EXTENTS (left, right, top, bottom) of *window*, or None."""
        x11, ulong = self.lib, ctypes.c_ulong
        actual_type, actual_format = ulong(), ctypes.c_int()
        nitems, after = ulong(), ulong()
        data = ctypes.POINTER(ctypes.c_ubyte)()
        x11.XGetWindowProperty(self.display, window, self.atom, 0, 4, False, 6,  # CARDINAL
                               ctypes.byref(actual_type), ctypes.byref(actual_format),
                               ctypes.byref(nitems), ctypes.byref(after), ctypes.byref(data))
        if not data:
            return None
        try:
            if actual_format.value != 32 or nitems.value != 4:
                return None
            # Xlib returns 32-bit items as C longs.
            return tuple(ctypes.cast(data, ctypes.POINTER(ctypes.c_long))[:4])
        finally:
            x11.XFree(data)


_x11_connections = {}


class TkWindowControl(WindowControl):
    backend = "tk"

    def __init__(self, manager, **kwargs):
        super().__init__(manager, **kwargs)
        self.window = manager.window
        self._pending_size = None

    def _x11(self):
        """Return an `_X11` for the window's X display, or None if Tk does not use X11."""
        win = self.window
        if win.tk.call("tk", "windowingsystem") != "x11":
            return None
        name = win.winfo_screen()
        if name not in _x11_connections:
            try:
                _x11_connections[name] = _X11(name)
            except OSError:
                _x11_connections[name] = None
        return _x11_connections[name]

    def _extents(self):
        """Return the visible decoration sizes (left, right, top, bottom), or None.

        On X11 the window manager publishes them as _NET_FRAME_EXTENTS on Tk's
        wrapper window, the parent of winfo_id(), once the window is mapped.
        """
        x11 = self._x11()
        if x11 is None:
            return None
        self.window.update_idletasks()
        wrapper = x11.parent(self.window.winfo_id())
        return x11.frame_extents(wrapper) if wrapper else None

    def _geometry(self):
        """Return the client size, the frame position, and the decoration sizes."""
        win = self.window
        win.update_idletasks()
        m = _GEOMETRY.fullmatch(win.wm_geometry())
        w, h, x, y = map(int, m.groups())
        extents = self._extents()
        if extents is not None:
            # Window managers that draw shadows around the frame (Mutter with
            # mutter-x11-frames) make `wm geometry` report the corner of the
            # invisible border until Tk moves the window, and the corner of the
            # visible frame after. The client position and _NET_FRAME_EXTENTS
            # give the visible frame in both cases.
            left, right, top, bottom = extents
            return (w, h, win.winfo_rootx() - left, win.winfo_rooty() - top,
                    left, right, top, bottom)
        # `wm geometry` gives the position of the outer frame and the size of
        # the client area; winfo_root{x,y} give the position of the client area.
        border = max(win.winfo_rootx() - x, 0)
        title = max(win.winfo_rooty() - y, 0)
        return w, h, x, y, border, border, title, border

    def _get_frame(self):
        w, h, x, y, left, right, top, bottom = self._geometry()
        return Frame(x, y, w + left + right, h + top + bottom)

    def _set_frame(self, x, y, width, height):
        w, h, x0, y0, left, right, top, bottom = self._geometry()
        x = x0 if x is None else int(x)
        y = y0 if y is None else int(y)
        w = w if width is None else int(width) - left - right
        h = h if height is None else int(height) - top - bottom
        # On X11, `wm geometry +x+y` asks for the outer frame at (x, y) with
        # north-west gravity, which places the visible frame there.
        self.window.wm_geometry(f"{w}x{h}+{x}+{y}")
        if (width is not None or height is not None) and self._x11() is not None \
                and self._extents() is None:
            self._apply_size_when_mapped(width, height)

    def _apply_size_when_mapped(self, width, height):
        # The window manager publishes _NET_FRAME_EXTENTS only once the window
        # is mapped; Mutter answers _NET_REQUEST_FRAME_EXTENTS with zeros.
        # Set the size again when the extents are known.
        first = self._pending_size is None
        self._pending_size = (width, height)
        if first:
            self.window.bind("<Map>", self._on_map, add="+")

    def _on_map(self, event, tries=50):
        if event is not None and event.widget is not self.window:
            return
        if self._pending_size is None:
            return
        if self._extents() is None:
            if tries:
                self.window.after(10, self._on_map, None, tries - 1)
            return
        width, height = self._pending_size
        self._pending_size = None
        self._set_frame(None, None, width, height)

    def _screens(self):
        if sys.platform == "darwin":
            from ._macos import cocoa_screens
            return cocoa_screens()
        # Tk has no list of displays; ask the system (X11, Windows), whose
        # pixels are Tk's pixels there.
        from ._displays import system_displays
        displays = system_displays()
        if displays:
            return [d.screen for d in displays]
        # Tk reports one screen: on X11 the whole X screen, on Windows the
        # primary display.
        win = self.window
        f = Frame(0, 0, win.winfo_screenwidth(), win.winfo_screenheight())
        return [Screen("", f, f, True)]

    def _nswindow(self):
        import ctypes

        import objc
        try:
            get = ctypes.CDLL(None).Tk_MacOSXGetNSWindowForDrawable
        except (OSError, AttributeError):
            return None
        get.restype = ctypes.c_void_p
        get.argtypes = [ctypes.c_void_p]
        ptr = get(ctypes.c_void_p(self.window.winfo_id()))
        return objc.objc_object(c_void_p=ptr) if ptr else None

    def _raise_window(self, with_focus):
        win = self.window
        if with_focus:
            win.lift()
            win.focus_force()
        elif getattr(self, "_floating", False):
            win.lift()
        else:
            # lift() alone does not go above other applications on Windows;
            # setting -topmost and clearing it does, as Matplotlib's show() does.
            win.wm_attributes("-topmost", 1)
            win.wm_attributes("-topmost", 0)

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
