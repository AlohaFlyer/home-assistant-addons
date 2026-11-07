from datetime import date, datetime

from far import free_30_in_168, window


def d(day, hh, mm=0):
    return datetime(2026, 11, day, hh, mm)


def test_window_release_includes_debrief_and_rolls_over():
    assert window(date(2026, 11, 26), date(2026, 11, 27), "15:30", "05:55") == (d(26, 15, 30), d(27, 6, 10))
    assert window(date(2026, 11, 26), None, "15:30", "21:00") == (d(26, 15, 30), d(26, 21, 15))
    assert window(date(2026, 11, 26), None, "", "21:00") is None


def test_30_in_168():
    # back-to-back trips leaving only 26 h gaps in the week before the pickup
    mine = [(d(3, 0), d(4, 22), 10.0), (d(6, 0), d(7, 22), 10.0)]
    assert not free_30_in_168([m for m in mine] + [(d(9, 0), d(10, 0), 5.0)], d(9, 0))
    assert free_30_in_168(mine, d(14, 0))
