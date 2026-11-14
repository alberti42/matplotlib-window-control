"""A second application for raise_check.py: python raise_helper.py X Y W H.

Opens a window at the given Cocoa frame and makes this application active.
Prints the window number. Each line read from stdin makes it active again;
end of input quits.
"""

import sys
import threading

from AppKit import (
    NSApplication,
    NSApplicationActivationPolicyRegular,
    NSBackingStoreBuffered,
    NSWindow,
    NSWindowStyleMaskTitled,
)
from PyObjCTools import AppHelper

x, y, w, h = map(float, sys.argv[1:5])
app = NSApplication.sharedApplication()
app.setActivationPolicy_(NSApplicationActivationPolicyRegular)
window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
    ((x, y), (w, h)), NSWindowStyleMaskTitled, NSBackingStoreBuffered, False)
window.setTitle_("raise_check helper")


def activate():
    # Bring the window to the front even if activation is refused, then ask
    # to become active: with -activate (macOS 14 and later) this succeeds when
    # the active application has yielded activation to this one.
    window.orderFrontRegardless()
    window.makeKeyAndOrderFront_(None)
    if app.respondsToSelector_("activate"):
        app.activate()
    else:
        app.activateIgnoringOtherApps_(True)
    print(window.windowNumber(), flush=True)


def read_stdin():
    for _ in sys.stdin:
        AppHelper.callAfter(activate)
    AppHelper.callAfter(AppHelper.stopEventLoop)


AppHelper.callAfter(activate)
threading.Thread(target=read_stdin, daemon=True).start()
AppHelper.runEventLoop()
