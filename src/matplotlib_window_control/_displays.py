"""Display identity from the operating system, matched to the toolkit's displays.

The toolkits report display geometry in the same units as window frames, but
little identity: on macOS, wx and GTK 3 report no names at all. This module
asks the operating system for each display's EDID data and identifier, and
copies them onto the toolkit's `Screen` objects.
"""

from __future__ import annotations

import ctypes
import struct
import sys
import warnings
from typing import NamedTuple

from ._base import Frame, Screen


class SystemDisplay(NamedTuple):
    screen: Screen  # Geometry measured from the primary display, identity set.
    aliases: tuple = ()  # Other names a toolkit may give the display.


# -- EDID ----------------------------------------------------------------------

def pnp_id(code):
    """Decode the 16-bit EDID manufacturer code into its three letters, e.g. "GKT"."""
    if not 0 < code < 0x8000:
        return None
    letters = "".join(chr(((code >> shift) & 31) + 64) for shift in (10, 5, 0))
    return letters if letters.isalpha() and letters.isupper() else None


def parse_edid(data):
    """Return the manufacturer, product, serial and name in an EDID block."""
    if len(data) < 128 or data[:8] != b"\x00\xff\xff\xff\xff\xff\xff\x00":
        return {}
    manufacturer = pnp_id(struct.unpack(">H", data[8:10])[0])
    product, serial_number = struct.unpack("<HI", data[10:16])
    serial_text = name = None
    for i in range(54, 126, 18):  # Four 18-byte descriptors.
        d = data[i:i + 18]
        if d[:3] == b"\x00\x00\x00" and d[3] in (0xFF, 0xFC):
            text = d[5:].split(b"\n")[0].decode("ascii", "replace").strip()
            if d[3] == 0xFF:
                serial_text = text or None
            else:
                name = text or None
    # Monitors often leave the numeric serial at 0 and fill in the text one.
    serial = serial_text or (str(serial_number) if serial_number else None)
    return {"manufacturer": manufacturer, "product": product, "serial": serial,
            "name": name}


# -- macOS ---------------------------------------------------------------------

def _macos_displays():
    from AppKit import NSScreen

    cg = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
    colorsync = ctypes.CDLL("/System/Library/Frameworks/ColorSync.framework/ColorSync")
    cf = ctypes.CDLL(
        "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
    for f in ("CGDisplayVendorNumber", "CGDisplayModelNumber", "CGDisplaySerialNumber"):
        getattr(cg, f).restype = ctypes.c_uint32
        getattr(cg, f).argtypes = [ctypes.c_uint32]
    colorsync.CGDisplayCreateUUIDFromDisplayID.restype = ctypes.c_void_p
    colorsync.CGDisplayCreateUUIDFromDisplayID.argtypes = [ctypes.c_uint32]
    cf.CFUUIDCreateString.restype = ctypes.c_void_p
    cf.CFUUIDCreateString.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    cf.CFStringGetCString.restype = ctypes.c_bool
    cf.CFStringGetCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long,
                                      ctypes.c_uint32]
    cf.CFRelease.argtypes = [ctypes.c_void_p]
    utf8 = 0x08000100

    def uuid_string(display_id):
        uuid = colorsync.CGDisplayCreateUUIDFromDisplayID(display_id)
        if not uuid:
            return None
        string = cf.CFUUIDCreateString(None, uuid)
        buf = ctypes.create_string_buffer(64)
        ok = cf.CFStringGetCString(string, buf, len(buf), utf8)
        cf.CFRelease(string)
        cf.CFRelease(uuid)
        return buf.value.decode() if ok else None

    screens = NSScreen.screens()
    primary_height = screens[0].frame().size.height

    def flip(rect):
        (x, y), (w, h) = rect
        return Frame(x, primary_height - (y + h), w, h)

    result = []
    for i, s in enumerate(screens):
        display_id = int(s.deviceDescription()["NSScreenNumber"])
        serial = cg.CGDisplaySerialNumber(display_id)
        name = s.localizedName() if s.respondsToSelector_("localizedName") else ""
        result.append(SystemDisplay(Screen(
            str(name), flip(s.frame()), flip(s.visibleFrame()), i == 0,
            manufacturer=pnp_id(cg.CGDisplayVendorNumber(display_id)),
            product=cg.CGDisplayModelNumber(display_id) or None,
            serial=str(serial) if serial else None,
            system_id=uuid_string(display_id))))
    return result


# -- dispatch and matching -----------------------------------------------------

_warned = set()


def system_displays():
    """Return the displays as the operating system reports them, or [].

    The lookups run once per call; a failure gives a warning, once per kind,
    and an empty list, so that a broken lookup never breaks window control.
    """
    try:
        if sys.platform == "darwin":
            return _macos_displays()
    except Exception as e:  # noqa: BLE001 - system-specific, best effort.
        if sys.platform not in _warned:
            _warned.add(sys.platform)
            warnings.warn(f"matplotlib_window_control could not read display identity "
                          f"on {sys.platform}: {e!r}", RuntimeWarning, stacklevel=3)
    return []


def _close(a, b, tol=1):
    return all(abs(p - q) <= tol for p, q in zip(a, b))


def _unique(candidates):
    return candidates[0] if len(candidates) == 1 else None


def match_display(screen, displays, offset=(0, 0), scale=None):
    """Return the system display that is *screen*, or None.

    Match the frame; then the name, which on X11 and Windows a toolkit may
    give as the connector or device name; then the frame moved by *offset*,
    for toolkits that put (0, 0) elsewhere and name no primary display; then
    the frame scaled by *scale*, for toolkits that report logical pixels
    while the system reports physical ones.
    """
    found = _unique([d for d in displays if _close(d.screen.frame, screen.frame)])
    if found is None and screen.name:
        found = _unique([d for d in displays
                         if screen.name in (d.screen.name, d.screen.system_id, *d.aliases)])
    if found is None and offset != (0, 0):
        dx, dy = offset
        found = _unique([d for d in displays if _close(
            d.screen.frame._replace(x=d.screen.frame.x + dx, y=d.screen.frame.y + dy),
            screen.frame)])
    if found is None and scale:
        found = _unique([d for d in displays
                         if _close([v * scale for v in d.screen.frame], screen.frame, 2)])
    return found


def attach_identity(screens, displays):
    """Copy the identity of each matching system display onto *screens*.

    If no screen in *screens* is marked primary, mark the one that matches
    the system's primary display.
    """
    if not displays or not screens:
        return screens
    scale = None
    primary = next((s for s in screens if s.primary), None)
    system_primary = next((d for d in displays if d.screen.primary), None)
    if primary and system_primary and system_primary.screen.frame.width:
        scale = primary.frame.width / system_primary.screen.frame.width
    # The offset between the corners of the two bounding boxes.
    offset = (min(s.frame.x for s in screens) - min(d.screen.frame.x for d in displays),
              min(s.frame.y for s in screens) - min(d.screen.frame.y for d in displays))
    result = []
    for s in screens:
        d = match_display(s, displays, offset, scale)
        if d is not None:
            s = s._replace(name=s.name or d.screen.name,
                           manufacturer=d.screen.manufacturer, product=d.screen.product,
                           serial=d.screen.serial, system_id=d.screen.system_id,
                           primary=s.primary or (primary is None and d.screen.primary))
        result.append(s)
    return result
