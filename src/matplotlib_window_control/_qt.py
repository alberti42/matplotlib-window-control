"""Qt backends (qtagg, qtcairo): QMainWindow calls through matplotlib.backends.qt_compat."""

from __future__ import annotations

from matplotlib.backends.qt_compat import QtCore, QtGui

from ._base import Frame, NotSupportedError, Screen, WindowControl


def _enum(owner, scope, name):
    # PyQt6 and PySide6 need the scoped name; PyQt5 also accepts the flat one.
    scoped = getattr(owner, scope, None)
    if scoped is not None and hasattr(scoped, name):
        return getattr(scoped, name)
    return getattr(owner, name)


_STAYS_ON_TOP = _enum(QtCore.Qt, "WindowType", "WindowStaysOnTopHint")
_MOVE = _enum(QtCore.QEvent, "Type", "Move")
_RESIZE = _enum(QtCore.QEvent, "Type", "Resize")


def _frame(rect):
    return Frame(rect.x(), rect.y(), rect.width(), rect.height())


class _GeometryFilter(QtCore.QObject):
    def __init__(self, control):
        super().__init__()
        self._control = control

    def eventFilter(self, obj, event):
        if event.type() in (_MOVE, _RESIZE):
            self._control._geometry_changed()
        return False  # Let Qt and Matplotlib handle the event as usual.


class QtWindowControl(WindowControl):
    backend = "qt"

    def __init__(self, manager, **kwargs):
        super().__init__(manager, **kwargs)
        self.window = manager.window
        self._filter = None

    def _wayland(self):
        return QtGui.QGuiApplication.platformName() == "wayland"

    def _create_native_window(self):
        # Qt knows the size of the window decorations only once the native
        # window exists. show() creates it; winId() creates it without showing.
        self.window.winId()

    def _get_frame(self):
        self._create_native_window()
        f = _frame(self.window.frameGeometry())
        if self._wayland():  # Qt reports (0, 0) on Wayland.
            return f._replace(x=None, y=None)
        return f

    def _set_frame(self, x, y, width, height):
        win = self.window
        self._create_native_window()
        if x is not None or y is not None:
            if self._wayland():
                raise NotSupportedError("Wayland does not let clients position windows")
            f = win.frameGeometry()
            win.move(int(f.x() if x is None else x), int(f.y() if y is None else y))
        if width is not None or height is not None:
            # resize() sets the size without decorations.
            fg, g = win.frameGeometry(), win.geometry()
            dw, dh = fg.width() - g.width(), fg.height() - g.height()
            win.resize(int((fg.width() if width is None else width) - dw),
                       int((fg.height() if height is None else height) - dh))

    def _screens(self):
        primary = QtGui.QGuiApplication.primaryScreen()
        screens = sorted(QtGui.QGuiApplication.screens(), key=lambda s: s != primary)
        return [Screen(s.name(), _frame(s.geometry()), _frame(s.availableGeometry()),
                       s == primary)
                for s in screens]

    def get_floating(self):
        return bool(self.window.windowFlags() & _STAYS_ON_TOP)

    def set_floating(self, floating):
        visible = self.window.isVisible()
        self.window.setWindowFlag(_STAYS_ON_TOP, bool(floating))
        if visible:  # Changing the window flags hides the window.
            self.window.show()

    def _hook(self):
        self._filter = _GeometryFilter(self)
        self.window.installEventFilter(self._filter)

    def _unhook(self):
        if self._filter is not None:
            try:
                self.window.removeEventFilter(self._filter)
            except RuntimeError:  # The C++ window has been deleted.
                pass
            self._filter = None
        super()._unhook()
