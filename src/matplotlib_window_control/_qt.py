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
_SHOW = _enum(QtCore.QEvent, "Type", "Show")


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


class _ShowFilter(QtCore.QObject):
    def __init__(self, callback):
        super().__init__()
        self._callback = callback

    def eventFilter(self, obj, event):
        if event.type() == _SHOW:
            QtCore.QTimer.singleShot(0, self._callback)
        return False


class QtWindowControl(WindowControl):
    backend = "qt"

    def __init__(self, manager, **kwargs):
        super().__init__(manager, **kwargs)
        self.window = manager.window
        self._filter = None
        self._show_filter = None
        self._pending_size = None

    def _wayland(self):
        return QtGui.QGuiApplication.platformName() == "wayland"

    def _x11_client(self):
        return QtGui.QGuiApplication.platformName() == "xcb"

    def _create_native_window(self):
        # Qt knows the size of the window decorations only once the native
        # window exists. show() creates it; winId() creates it without showing.
        self.window.winId()

    def _decorations(self):
        """Return the total width and height of the decorations."""
        win = self.window
        self._create_native_window()
        if self._wayland():
            # On Wayland, QWidget.frameGeometry() leaves out the decorations
            # that Qt draws itself until the window is first resized;
            # QWindow.frameMargins() has them as soon as the window is shown.
            m = win.windowHandle().frameMargins()
            return m.left() + m.right(), m.top() + m.bottom()
        fg, g = win.frameGeometry(), win.geometry()
        return fg.width() - g.width(), fg.height() - g.height()

    def _get_frame(self):
        dw, dh = self._decorations()
        if self._wayland():  # Qt reports (0, 0) on Wayland.
            g = self.window.geometry()
            return Frame(None, None, g.width() + dw, g.height() + dh)
        return _frame(self.window.frameGeometry())

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
            dw, dh = self._decorations()
            g = win.geometry()
            win.resize(int(g.width() if width is None else width - dw),
                       int(g.height() if height is None else height - dh))
            if self._wayland() and not win.isVisible():
                self._apply_size_when_shown(width, height)

    def _apply_size_when_shown(self, width, height):
        # QtWayland creates the decorations when the window is shown, and
        # QWindow.frameMargins() reports them one event-loop turn after the
        # Show event. Set the size again then.
        def apply():
            win.removeEventFilter(self._show_filter)
            self._show_filter = None
            if self._pending_size is not None:
                self._set_frame(None, None, *self._pending_size)
                self._pending_size = None

        win = self.window
        self._pending_size = (width, height)
        if self._show_filter is None:
            self._show_filter = _ShowFilter(apply)
            win.installEventFilter(self._show_filter)

    def _screens(self):
        primary = QtGui.QGuiApplication.primaryScreen()
        screens = sorted(QtGui.QGuiApplication.screens(), key=lambda s: s != primary)
        return [Screen(s.name(), _frame(s.geometry()), _frame(s.availableGeometry()),
                       s == primary)
                for s in screens]

    def _nswindow(self):
        import objc
        # On macOS, winId() is the NSView of the window's content.
        return objc.objc_object(c_void_p=int(self.window.winId())).window()

    def _raise_window(self, with_focus):
        self.window.raise_()
        if with_focus:
            self.window.activateWindow()

    def _check_floating(self):
        if self._wayland():
            # Wayland has no keep-above request; QtWayland keeps the
            # WindowStaysOnTopHint flag, and reports it, but Mutter does not
            # keep the window above (checked by eye on GNOME 51).
            raise NotSupportedError("Wayland does not let clients keep a window above")

    def get_floating(self):
        self._check_floating()
        return bool(self.window.windowFlags() & _STAYS_ON_TOP)

    def set_floating(self, floating):
        self._check_floating()
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
