import json

from matplotlib_window_control import Frame, Screen, find_screen

F = Frame(0, 0, 100, 100)


def monitor(name="Kuycon G32P", manufacturer="GKT", product=12837, serial=None,
            system_id=None):
    return Screen(name, F, F, False, manufacturer, product, serial, system_id)


def test_identical_monitors_told_apart_by_serial_after_swapping_ports():
    saved = monitor(serial="A100", system_id="DP-1")
    a = monitor(serial="A100", system_id="DP-2")  # The same unit, now on DP-2.
    b = monitor(serial="B200", system_id="DP-1")
    assert find_screen(saved, [b, a]) is a


def test_identical_monitors_without_serial_told_apart_by_port():
    saved = monitor(system_id="DP-2")
    a = monitor(system_id="DP-1")
    b = monitor(system_id="DP-2")
    assert find_screen(saved, [a, b]) is b


def test_identical_monitors_without_serial_on_new_ports_are_ambiguous():
    saved = monitor(system_id="DP-3")
    assert find_screen(saved, [monitor(system_id="DP-1"), monitor(system_id="DP-2")]) is None


def test_single_monitor_of_a_model_found_on_another_port():
    saved = monitor(system_id="DP-1")
    other = monitor(name="iPad", manufacturer=None, product=None, system_id="DP-1")
    kuycon = monitor(system_id="HDMI-1")
    assert find_screen(saved, [other, kuycon]) is kuycon


def test_different_serial_is_a_different_monitor_even_on_the_same_port():
    saved = monitor(serial="A100", system_id="DP-1")
    replacement = monitor(serial="B200", system_id="DP-1")
    assert find_screen(saved, [replacement]) is None


def test_saved_serial_matches_a_monitor_whose_serial_cannot_be_read():
    # E.g. saved on Linux, where the EDID text serial is read, and restored on
    # a system that reports none.
    saved = monitor(serial="A100", system_id="DP-1")
    unread = monitor(serial=None, system_id="DP-1")
    assert find_screen(saved, [unread]) is unread


def test_name_when_the_system_reports_no_identity():
    saved = monitor(manufacturer=None, product=None, name="Kuycon G32P")
    found = monitor(manufacturer=None, product=None, name="Kuycon G32P")
    other = monitor(manufacturer=None, product=None, name="Sidecar Display")
    assert find_screen(saved, [other, found]) is found


def test_monitor_not_attached():
    saved = monitor(serial="A100")
    other = monitor(name="iPad", manufacturer=None, product=None)
    assert find_screen(saved, [other]) is None


def test_saved_as_json():
    a = monitor(system_id="DP-1")
    b = monitor(system_id="DP-2")
    saved = json.loads(json.dumps(b._asdict()))
    assert find_screen(saved, [a, b]) is b


def test_serial_match_wins_over_a_port_match():
    saved = monitor(serial="A100", system_id="DP-1")
    moved = monitor(serial="A100", system_id="DP-2")  # The saved unit, moved.
    unread = monitor(serial=None, system_id="DP-1")  # Another unit, serial unread.
    assert find_screen(saved, [unread, moved]) is moved
