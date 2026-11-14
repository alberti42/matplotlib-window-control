"""Tests of EDID decoding and of matching toolkit displays to system displays."""

from matplotlib_window_control import Frame, Screen
from matplotlib_window_control._displays import (
    SystemDisplay,
    attach_identity,
    parse_edid,
    pnp_id,
)

# The first 128 bytes of the EDID of a Kuycon G32P: manufacturer GKT, product
# 12837, numeric serial 0, no text serial, name "Kuycon G32P".
KUYCON_EDID = bytes.fromhex(
    "00ffffffffffff001d7425320000000015230104c5462778393d78ad5143b0260f50552108"
    "00d1c0010181c0a9c0010101010101010150d000a0f0703e8030203500bc862100001e0000"
    "00fc004b7579636f6e20473332500a20000000fd00303cffff8c010a202020202020000000"
    "10000000000000000000000000000002a1")


def with_text_serial(edid, text):
    """Return *edid* with its last descriptor replaced by a text serial."""
    descriptor = b"\x00\x00\x00\xff\x00" + text.encode().ljust(13, b"\n")[:13]
    return edid[:108] + descriptor + edid[126:]


def test_pnp_id():
    assert pnp_id(0x1D74) == "GKT"
    assert pnp_id(0) is None
    assert pnp_id(1633775724) is None  # Not a 16-bit EDID code.


def test_parse_kuycon_edid():
    assert parse_edid(KUYCON_EDID) == {
        "manufacturer": "GKT", "product": 12837, "serial": None, "name": "Kuycon G32P"}


def test_text_serial_preferred_over_numeric():
    edid = bytearray(with_text_serial(KUYCON_EDID, "ABC123"))
    edid[12:16] = (4242).to_bytes(4, "little")
    assert parse_edid(bytes(edid))["serial"] == "ABC123"


def test_numeric_serial_when_no_text_serial():
    edid = bytearray(KUYCON_EDID)
    edid[12:16] = (4242).to_bytes(4, "little")
    assert parse_edid(bytes(edid))["serial"] == "4242"


def test_not_an_edid():
    assert parse_edid(b"\x00" * 128) == {}
    assert parse_edid(KUYCON_EDID[:100]) == {}


# -- matching --------------------------------------------------------------------

def screen(name, x, y, w, h, primary=False, **identity):
    return Screen(name, Frame(x, y, w, h), Frame(x, y, w, h), primary, **identity)


KUYCON = SystemDisplay(screen("Kuycon G32P", 0, 0, 3072, 1728, True, manufacturer="GKT",
                              product=12837, system_id="uuid-kuycon"))
IPAD = SystemDisplay(screen("Sidecar Display", -1288, 0, 1288, 1024, serial="2787956091",
                            system_id="uuid-ipad"))


def identities(screens):
    return [(s.name, s.system_id, s.primary) for s in screens]


def test_match_by_frame_fills_in_missing_names():
    # wx and GTK 3 on macOS report no names.
    toolkit = [screen("", 0, 0, 3072, 1728, True), screen("", -1288, 0, 1288, 1024)]
    assert identities(attach_identity(toolkit, [KUYCON, IPAD])) == [
        ("Kuycon G32P", "uuid-kuycon", True), ("Sidecar Display", "uuid-ipad", False)]


def test_match_by_connector_name():
    # Qt on X11 names a display by its output, which is the system_id there.
    dp1 = SystemDisplay(screen("DELL U2720Q", 0, 0, 3840, 2160, True, system_id="DP-1"))
    dp2 = SystemDisplay(screen("DELL U2720Q", 3840, 0, 3840, 2160, system_id="DP-2"))
    toolkit = [screen("DP-2", 1920, 0, 1920, 1080), screen("DP-1", 0, 0, 1920, 1080, True)]
    assert [s.system_id for s in attach_identity(toolkit, [dp1, dp2])] == ["DP-2", "DP-1"]


def test_match_moved_bounding_box_and_mark_primary():
    # GTK 4 on macOS: (0, 0) at the corner of the bounding box, no primary.
    toolkit = [screen("unit-1", 1288, 0, 3072, 1728), screen("unit-2", 0, 0, 1288, 1024)]
    assert identities(attach_identity(toolkit, [KUYCON, IPAD])) == [
        ("unit-1", "uuid-kuycon", True), ("unit-2", "uuid-ipad", False)]


def test_match_scaled_frames():
    # A toolkit that reports logical pixels at scale 2 while the system
    # reports physical pixels.
    a = SystemDisplay(screen("A", 0, 0, 3840, 2160, True, system_id="a"))
    b = SystemDisplay(screen("B", 3840, 0, 3840, 2160, system_id="b"))
    toolkit = [screen("", 0, 0, 1920, 1080, True), screen("", 1920, 0, 1920, 1080)]
    assert [s.system_id for s in attach_identity(toolkit, [a, b])] == ["a", "b"]


def test_identical_names_without_other_match_get_no_identity():
    a = SystemDisplay(screen("Kuycon G32P", 0, 0, 3072, 1728, True, system_id="a"))
    b = SystemDisplay(screen("Kuycon G32P", 3072, 0, 3072, 1728, system_id="b"))
    # Frames that match neither display, at any offset or scale.
    toolkit = [screen("Kuycon G32P", 0, 0, 1000, 700, True)]
    assert attach_identity(toolkit, [a, b])[0].system_id is None


def test_no_system_displays():
    toolkit = [screen("", 0, 0, 100, 100, True)]
    assert attach_identity(toolkit, []) == toolkit
