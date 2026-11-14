"""macosx backend: native NSWindow calls through PyObjC.

Cocoa puts the origin at the bottom-left of the primary screen with *y* up;
this module converts to and from the top-left, *y*-down convention of `Frame`.
"""

from __future__ import annotations

import objc
from AppKit import (
    NSFloatingWindowLevel,
    NSNormalWindowLevel,
    NSScreen,
    NSWindowDidMoveNotification,
    NSWindowDidResizeNotification,
)
from Foundation import NSNotificationCenter, NSOperationQueue

from ._base import Frame, Screen, UnsupportedBackendError, WindowControl


def _primary_height():
    return NSScreen.screens()[0].frame().size.height


def _to_frame(rect, primary_height):
    (x, y), (w, h) = rect
    return Frame(x, primary_height - (y + h), w, h)


def cocoa_screens() -> list[Screen]:
    """Return the displays from ``+[NSScreen screens]``, in `Frame` coordinates."""
    screens = NSScreen.screens()
    primary_height = screens[0].frame().size.height
    result = []
    for i, s in enumerate(screens):
        name = s.localizedName() if s.respondsToSelector_("localizedName") else ""
        result.append(Screen(str(name),
                             _to_frame(s.frame(), primary_height),
                             _to_frame(s.visibleFrame(), primary_height),
                             i == 0))
    return result


class MacOSWindowControl(WindowControl):
    backend = "macosx"

    def __init__(self, manager, **kwargs):
        ptr = getattr(manager, "_raw_nswindow_ptr", None)
        if ptr is None:
            if not hasattr(type(manager), "_raw_nswindow_ptr"):
                raise UnsupportedBackendError(
                    "The macosx backend of this Matplotlib version does not "
                    "provide FigureManager._raw_nswindow_ptr")
            raise UnsupportedBackendError("The window has been closed")
        super().__init__(manager, **kwargs)
        self.nswindow = objc.objc_object(c_void_p=ptr)
        self._observers = []

    def _get_frame(self):
        return _to_frame(self.nswindow.frame(), _primary_height())

    def _set_frame(self, x, y, width, height):
        f = self._get_frame()
        x = f.x if x is None else x
        y = f.y if y is None else y
        width = f.width if width is None else width
        height = f.height if height is None else height
        self.nswindow.setFrame_display_(
            ((x, _primary_height() - (y + height)), (width, height)), True)

    def _screens(self):
        return cocoa_screens()

    def get_floating(self):
        return self.nswindow.level() >= NSFloatingWindowLevel

    def set_floating(self, floating):
        self.nswindow.setLevel_(
            NSFloatingWindowLevel if floating else NSNormalWindowLevel)

    def _hook(self):
        # The window delegate is Matplotlib's view; observe notifications instead.
        center = NSNotificationCenter.defaultCenter()
        for name in (NSWindowDidMoveNotification, NSWindowDidResizeNotification):
            self._observers.append(
                center.addObserverForName_object_queue_usingBlock_(
                    name, self.nswindow, NSOperationQueue.mainQueue(),
                    lambda notification: self._geometry_changed()))

    def _unhook(self):
        center = NSNotificationCenter.defaultCenter()
        for observer in self._observers:
            center.removeObserver_(observer)
        self._observers.clear()
        super()._unhook()
