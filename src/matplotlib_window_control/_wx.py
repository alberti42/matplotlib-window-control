"""wx backends (wxagg, wxcairo): wx.Frame and wx.Display calls."""

from __future__ import annotations

import wx

from ._base import Frame, Screen, WindowControl


def _frame(rect):
    return Frame(rect.x, rect.y, rect.width, rect.height)


class WxWindowControl(WindowControl):
    backend = "wx"

    def __init__(self, manager, **kwargs):
        super().__init__(manager, **kwargs)
        self.window = manager.frame

    def _get_frame(self):
        return _frame(self.window.GetRect())  # The outer frame on all platforms.

    def _set_frame(self, x, y, width, height):
        f = self._get_frame()
        if x is not None or y is not None:
            # SetPosition accepts -1 as a coordinate; Move treats it as "unchanged".
            self.window.SetPosition(wx.Point(int(f.x if x is None else x),
                                             int(f.y if y is None else y)))
        if width is not None or height is not None:
            self.window.SetSize(wx.Size(int(f.width if width is None else width),
                                        int(f.height if height is None else height)))

    def _screens(self):
        displays = [wx.Display(i) for i in range(wx.Display.GetCount())]
        displays.sort(key=lambda d: not d.IsPrimary())
        return [Screen(d.GetName(), _frame(d.GetGeometry()), _frame(d.GetClientArea()),
                       d.IsPrimary())
                for d in displays]

    def _nswindow(self):
        import objc
        # On macOS, GetHandle() is the NSView of the frame's content.
        return objc.objc_object(c_void_p=int(self.window.GetHandle())).window()

    def _raise_window(self, with_focus):
        self.window.Raise()
        if with_focus:
            self.window.SetFocus()

    def get_floating(self):
        return bool(self.window.GetWindowStyleFlag() & wx.STAY_ON_TOP)

    def set_floating(self, floating):
        style = self.window.GetWindowStyleFlag()
        style = style | wx.STAY_ON_TOP if floating else style & ~wx.STAY_ON_TOP
        self.window.SetWindowStyleFlag(style)

    def _on_event(self, event):
        event.Skip()  # Let Matplotlib's handlers run too.
        self._geometry_changed()

    def _hook(self):
        self.window.Bind(wx.EVT_MOVE, self._on_event)
        self.window.Bind(wx.EVT_SIZE, self._on_event)

    def _unhook(self):
        if self._hooked:
            for evt in (wx.EVT_MOVE, wx.EVT_SIZE):
                try:
                    self.window.Unbind(evt, handler=self._on_event)
                except RuntimeError:  # The C++ frame has been deleted.
                    pass
        super()._unhook()
