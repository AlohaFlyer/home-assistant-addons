from datetime import date, datetime

from far import far_check, free_30_in_168, window


def d(day, hh, mm=0):
    return datetime(2026, 11, day, hh, mm)


def test_window_release_includes_debrief_and_rolls_over():
    assert window(date(2026, 11, 26), date(2026, 11, 27), "15:30", "05:55") == (d(26, 15, 30), d(27, 6, 10))
    assert window(date(2026, 11, 26), None, "15:30", "21:00") == (d(26, 15, 30), d(26, 21, 15))
    assert window(date(2026, 11, 26), None, "", "21:00") is None


def test_ok_with_plenty_of_rest():
    mine = [(d(3, 8), d(4, 20), 12.0), (d(20, 8), d(21, 20), 12.0)]
    assert far_check((d(10, 9), d(11, 18), 11.0), mine) == "OK"


def test_conflict_and_short_rest():
    mine = [(d(3, 8), d(4, 20), 12.0)]
    assert far_check((d(4, 10), d(5, 18), 11.0), mine) == "Conflict"
    assert far_check((d(5, 4), d(6, 18), 11.0), mine) == "Rest 8:00 before"
    assert far_check((d(5, 6, 30), d(6, 18), 11.0), mine) == "OK (CBA rest 10:30)"
    assert far_check((d(1, 6), d(2, 23), 11.0), mine) == "Rest 9:00 after"


def test_30_in_168():
    # back-to-back trips leaving only 26 h gaps in the week before the pickup
    mine = [(d(3, 0), d(4, 22), 10.0), (d(6, 0), d(7, 22), 10.0)]
    assert not free_30_in_168([m for m in mine] + [(d(9, 0), d(10, 0), 5.0)], d(9, 0))
    assert far_check((d(9, 0), d(10, 0), 5.0), mine) == "No 30h/168h"


def test_flight_time_cap():
    mine = [(d(2, 8), d(4, 8), 40.0), (d(8, 8), d(10, 8), 40.0)]
    assert far_check((d(15, 8), d(16, 8), 25.0), mine) == "FT 105h/672h"


def test_unknown_neighbour_times():
    mine = [(d(3, 0), d(4, 23, 59), 0.0, True)]
    assert far_check((d(5, 12), d(6, 18), 11.0), mine) == "?"
