"""Display identity from the operating system, matched to the toolkit's displays.

The toolkits report display geometry in the same units as window frames, but
little identity: on macOS, wx and GTK 3 report no names at all. This module
asks the operating system for each display's EDID data and identifier, and
copies them onto the toolkit's `Screen` objects.
"""

from __future__ import annotations

import ctypes
import os
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


# -- X11 -----------------------------------------------------------------------
#
# Untested on Linux: written from the Xlib and XRandR headers. X11 puts (0, 0)
# at the top-left of the bounding box of all outputs; the frames here are
# moved so that the primary output starts at (0, 0). The system_id is the
# output (connector) name, e.g. "DP-1".

class _XRRScreenResources(ctypes.Structure):
    _fields_ = [("timestamp", ctypes.c_ulong), ("configTimestamp", ctypes.c_ulong),
                ("ncrtc", ctypes.c_int), ("crtcs", ctypes.POINTER(ctypes.c_ulong)),
                ("noutput", ctypes.c_int), ("outputs", ctypes.POINTER(ctypes.c_ulong)),
                ("nmode", ctypes.c_int), ("modes", ctypes.c_void_p)]


class _XRROutputInfo(ctypes.Structure):
    _fields_ = [("timestamp", ctypes.c_ulong), ("crtc", ctypes.c_ulong),
                ("name", ctypes.c_char_p), ("nameLen", ctypes.c_int),
                ("mm_width", ctypes.c_ulong), ("mm_height", ctypes.c_ulong),
                ("connection", ctypes.c_ushort), ("subpixel_order", ctypes.c_ushort),
                ("ncrtc", ctypes.c_int), ("crtcs", ctypes.POINTER(ctypes.c_ulong)),
                ("nclone", ctypes.c_int), ("clones", ctypes.POINTER(ctypes.c_ulong)),
                ("nmode", ctypes.c_int), ("npreferred", ctypes.c_int),
                ("modes", ctypes.POINTER(ctypes.c_ulong))]


class _XRRCrtcInfo(ctypes.Structure):
    _fields_ = [("timestamp", ctypes.c_ulong), ("x", ctypes.c_int), ("y", ctypes.c_int),
                ("width", ctypes.c_uint), ("height", ctypes.c_uint),
                ("mode", ctypes.c_ulong), ("rotation", ctypes.c_ushort),
                ("noutput", ctypes.c_int), ("outputs", ctypes.POINTER(ctypes.c_ulong)),
                ("rotations", ctypes.c_ushort), ("npossible", ctypes.c_int),
                ("possible", ctypes.POINTER(ctypes.c_ulong))]


def _x11_libraries():
    import ctypes.util

    paths = {"X11": ctypes.util.find_library("X11"),
             "Xrandr": ctypes.util.find_library("Xrandr")}
    if sys.platform == "darwin":  # XQuartz, for running this code on macOS.
        paths = {"X11": "/opt/X11/lib/libX11.dylib",
                 "Xrandr": "/opt/X11/lib/libXrandr.dylib"}
    if not all(paths.values()):
        raise OSError("libX11 or libXrandr not found")
    x11, xrandr = ctypes.CDLL(paths["X11"]), ctypes.CDLL(paths["Xrandr"])
    p, ulong = ctypes.c_void_p, ctypes.c_ulong
    x11.XOpenDisplay.restype = p
    x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x11.XCloseDisplay.argtypes = [p]
    x11.XDefaultRootWindow.restype = ulong
    x11.XDefaultRootWindow.argtypes = [p]
    x11.XInternAtom.restype = ulong
    x11.XInternAtom.argtypes = [p, ctypes.c_char_p, ctypes.c_int]
    x11.XFree.argtypes = [p]
    xrandr.XRRGetScreenResourcesCurrent.restype = ctypes.POINTER(_XRRScreenResources)
    xrandr.XRRGetScreenResourcesCurrent.argtypes = [p, ulong]
    xrandr.XRRFreeScreenResources.argtypes = [p]
    xrandr.XRRGetOutputInfo.restype = ctypes.POINTER(_XRROutputInfo)
    xrandr.XRRGetOutputInfo.argtypes = [p, p, ulong]
    xrandr.XRRFreeOutputInfo.argtypes = [p]
    xrandr.XRRGetCrtcInfo.restype = ctypes.POINTER(_XRRCrtcInfo)
    xrandr.XRRGetCrtcInfo.argtypes = [p, p, ulong]
    xrandr.XRRFreeCrtcInfo.argtypes = [p]
    xrandr.XRRGetOutputPrimary.restype = ulong
    xrandr.XRRGetOutputPrimary.argtypes = [p, ulong]
    xrandr.XRRGetOutputProperty.restype = ctypes.c_int
    xrandr.XRRGetOutputProperty.argtypes = [
        p, ulong, ulong, ctypes.c_long, ctypes.c_long, ctypes.c_int, ctypes.c_int,
        ulong, ctypes.POINTER(ulong), ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ulong), ctypes.POINTER(ulong),
        ctypes.POINTER(ctypes.POINTER(ctypes.c_ubyte))]
    return x11, xrandr


def _x11_edid(x11, xrandr, display, output, atom):
    if not atom:
        return b""
    actual_type, nitems, after = ctypes.c_ulong(), ctypes.c_ulong(), ctypes.c_ulong()
    actual_format = ctypes.c_int()
    data = ctypes.POINTER(ctypes.c_ubyte)()
    # Length is in 32-bit units: 128 of them hold 512 bytes, enough for an
    # EDID base block and three extension blocks.
    status = xrandr.XRRGetOutputProperty(
        display, output, atom, 0, 128, False, False, 0, ctypes.byref(actual_type),
        ctypes.byref(actual_format), ctypes.byref(nitems), ctypes.byref(after),
        ctypes.byref(data))
    if status != 0 or not data:
        return b""
    try:
        return bytes(data[:nitems.value]) if actual_format.value == 8 else b""
    finally:
        x11.XFree(data)


def _x11_displays():
    x11, xrandr = _x11_libraries()
    display = x11.XOpenDisplay(None)
    if not display:
        raise OSError("cannot open the X display")
    try:
        root = x11.XDefaultRootWindow(display)
        resources = xrandr.XRRGetScreenResourcesCurrent(display, root)
        if not resources:
            raise OSError("XRRGetScreenResourcesCurrent failed")
        edid_atom = x11.XInternAtom(display, b"EDID", True)
        primary_output = xrandr.XRRGetOutputPrimary(display, root)
        outputs = []
        try:
            res = resources.contents
            for i in range(res.noutput):
                output = res.outputs[i]
                info = xrandr.XRRGetOutputInfo(display, resources, output)
                if not info:
                    continue
                try:
                    o = info.contents
                    if o.connection != 0 or not o.crtc:  # Not connected or off.
                        continue
                    crtc = xrandr.XRRGetCrtcInfo(display, resources, o.crtc)
                    if not crtc:
                        continue
                    c = crtc.contents
                    frame = Frame(c.x, c.y, c.width, c.height)
                    xrandr.XRRFreeCrtcInfo(crtc)
                    name = o.name.decode(errors="replace")
                    edid = parse_edid(_x11_edid(x11, xrandr, display, output, edid_atom))
                    outputs.append((output == primary_output, name, frame, edid))
                finally:
                    xrandr.XRRFreeOutputInfo(info)
        finally:
            xrandr.XRRFreeScreenResources(resources)
    finally:
        x11.XCloseDisplay(display)
    if not outputs:
        return []
    if not any(primary for primary, *_ in outputs):  # No primary set: X picks
        outputs[0] = (True, *outputs[0][1:])          # the first output.
    ox, oy = next(f[:2] for primary, _, f, _ in outputs if primary)
    result = []
    for primary, name, f, edid in outputs:
        f = Frame(f.x - ox, f.y - oy, f.width, f.height)
        result.append(SystemDisplay(Screen(
            edid.get("name") or name, f, f, primary,
            manufacturer=edid.get("manufacturer"), product=edid.get("product"),
            serial=edid.get("serial"), system_id=name), aliases=(name,)))
    return result


# -- Windows -------------------------------------------------------------------
#
# Untested on Windows: written from the Win32 documentation. Windows already
# puts (0, 0) at the top-left of the primary monitor. The system_id is the
# monitor device path, which contains the EDID manufacturer and product codes
# and an instance ID that differs per port.

def parse_device_id(device_id):
    """Split a monitor device path into its hardware ID and instance ID.

    For "\\\\?\\DISPLAY#GKT3225#5&2f0a&0&UID4352#{e6f07b5f-...}" return
    ("GKT3225", "5&2f0a&0&UID4352", "GKT", 12837), or None.
    """
    parts = device_id.split("#")
    if len(parts) < 3 or len(parts[1]) < 7:
        return None
    hardware_id, instance = parts[1], parts[2]
    try:
        product = int(hardware_id[3:7], 16)
    except ValueError:
        product = None
    return hardware_id, instance, hardware_id[:3], product


def _windows_edid(hardware_id, instance):
    import winreg

    key = (rf"SYSTEM\CurrentControlSet\Enum\DISPLAY\{hardware_id}\{instance}"
           r"\Device Parameters")
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as k:
            return bytes(winreg.QueryValueEx(k, "EDID")[0])
    except OSError:
        return b""


def _windows_displays():
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32")

    class MONITORINFOEXW(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD),
                    ("szDevice", wintypes.WCHAR * 32)]

    class DISPLAY_DEVICEW(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("DeviceName", wintypes.WCHAR * 32),
                    ("DeviceString", wintypes.WCHAR * 128),
                    ("StateFlags", wintypes.DWORD), ("DeviceID", wintypes.WCHAR * 128),
                    ("DeviceKey", wintypes.WCHAR * 128)]

    MONITORENUMPROC = ctypes.WINFUNCTYPE(
        wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT),
        wintypes.LPARAM)
    user32.EnumDisplayMonitors.argtypes = [wintypes.HDC, ctypes.c_void_p,
                                           MONITORENUMPROC, wintypes.LPARAM]
    user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.c_void_p]
    user32.EnumDisplayDevicesW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
                                           ctypes.c_void_p, wintypes.DWORD]
    EDD_GET_DEVICE_INTERFACE_NAME = 1
    MONITORINFOF_PRIMARY = 1

    def frame(r):
        return Frame(r.left, r.top, r.right - r.left, r.bottom - r.top)

    infos = []

    def callback(hmonitor, hdc, rect, data):
        info = MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(info)
        if user32.GetMonitorInfoW(hmonitor, ctypes.byref(info)):
            infos.append((frame(info.rcMonitor), frame(info.rcWork),
                          bool(info.dwFlags & MONITORINFOF_PRIMARY), info.szDevice))
        return True

    user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(callback), 0)
    result = []
    for f, work_area, primary, device in infos:
        dd = DISPLAY_DEVICEW()
        dd.cb = ctypes.sizeof(dd)
        found = user32.EnumDisplayDevicesW(device, 0, ctypes.byref(dd),
                                           EDD_GET_DEVICE_INTERFACE_NAME)
        device_id = dd.DeviceID if found else ""
        parsed = parse_device_id(device_id)
        edid = parse_edid(_windows_edid(*parsed[:2])) if parsed else {}
        result.append(SystemDisplay(Screen(
            edid.get("name") or (dd.DeviceString if found else "") or device,
            f, work_area, primary,
            manufacturer=edid.get("manufacturer") or (parsed[2] if parsed else None),
            product=edid.get("product") or (parsed[3] if parsed else None),
            serial=edid.get("serial"), system_id=device_id or device),
            aliases=(device,)))
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
        if sys.platform == "win32":
            return _windows_displays()
        if sys.platform.startswith("linux") and os.environ.get("DISPLAY") \
                and not os.environ.get("WAYLAND_DISPLAY"):
            return _x11_displays()
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
