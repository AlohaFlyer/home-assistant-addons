"""1.7.13 stage 2 (Ryan, Nov 18: "fix all of these things", the FAR 117 gaps item 4's review left open). The Schedule
card only; far.py is the reference and is unchanged. Synthetic months and made-up trips only (H91xx, H92xx, H96xx; no
crew names), rendered in Chromium.

- F1: Room to 100h is 100:00 minus the busiest 672 h window that holds any part of the day. It tries the windows that
  start at a duty's start or end at its block-in (far._cum's windows, where the busiest one always is), counting a
  duty's block when the whole duty is in the window, as far.py counts a pickup's flight time (recall._trip's spans),
  and the windows ending 24:00 HST, counted leg by leg as the 100h in 672h cell counts them. The 100h in 672h cell
  stays the 672 h ending 24:00 that day. On the same line Room reads over exactly when far.py finds a 672 h window
  over 100:00 that holds the day; the one other way is a window ending 24:00 over leg by leg (a leg across its edge
  counted in part), which far.py reads '?' (may pass), never OK. Room is never more than 100h in 672h shows.
- F3: a trip with no times on file adds 0:00 block, so a window that holds an own trip with no times (no Block and no
  duties, a {} record, or no record) shows its figure with '~' (not known in full) in both flight time cells, and the
  title names the trip; the Key says so."""
import copy
import re
from datetime import date, datetime, timedelta

import pytest

import far
import recall
from test_fw1713_far_columns import CASES, JS, TURN, _midday, _st, _theme
from test_release_a_schedule_card import _src

LAST = {"2026-10": 31, "2026-11": 30, "2026-12": 31, "2027-01": 31}


def _du(*rows):
    """Duty periods in FLICA's shape: (day, dep, arr, stn, blk) in HST minutes from 00:00 of the trip's first day."""
    return [{"d": d, "dep": dep, "arr": arr, "stn": stn, "blk": blk} for d, dep, arr, stn, blk in rows]


def _line(trips, months=("2026-10", "2026-11", "2026-12")):
    """A line from [(code, start, end, lay, own record or None)]: each month on file lists the trips that touch it
    (a trip across a month end on both pages, as FLICA does), its days marked like FLICA's (the code and layover on
    the first day, '-' away, HNL the day it comes home). None = no record at all for that trip."""
    out, own = {}, {}
    for mk in months:
        days = [[f"{mk}-{d:02d}", "", ""] for d in range(1, LAST[mk] + 1)]
        items = []
        for code, a, b, lay, rec in trips:
            if a[:7] > mk or b[:7] < mk:
                continue
            items.append({"trip": code, "start": a, "end": b, "lay": lay})
            d = date.fromisoformat(a)
            while d <= date.fromisoformat(b):
                iso = d.isoformat()
                if iso[:7] == mk:
                    days[d.day - 1] = [iso, code, lay] if iso == a else [iso, "", "HNL" if iso == b else "-"]
                d += timedelta(days=1)
        out[mk] = {"items": items, "days": days, "totals": {}, "updated": "Nov 12, 2026"}
    for code, a, b, lay, rec in trips:
        if rec is not None:
            own[f"{code}|{a}"] = rec
    return _st(out, own)


def _ryan_shaped():
    """Trips shaped like a widebody line (made-up codes): two duties each, red-eyes across 24:00 HST, later duties
    starting 1:15 before departure out of domicile (PWA 2.19.b), a trip across the Nov 30 month end, two no-duty
    trips (one span, report to last block-in) and one whose second duty has no block (far.py then counts the trip's
    Block over the whole trip). Some 672 h windows go over 100:00, some do not."""
    t = lambda rep, arr, blk, du: {"report": rep, "last_arr": arr, "blk": blk, "credit": blk, "duties": du}  # noqa
    return _line([
        ("H9601", "2026-10-26", "2026-10-28", "JFK", t("14:05", "14:07", "20:31", _du(
            (0, 921, 1545, "JFK", 564), (2, 3120, 3727, "HNL", 667)))),
        ("H9602", "2026-11-01", "2026-11-04", "SIN", t("04:00", "08:08", "27:11", _du(
            (0, 320, 1121, "SIN", 801), (2, 3978, 4808, "HNL", 830)))),
        ("H9603", "2026-11-09", "2026-11-12", "SYD", t("10:55", "10:39", "20:29", _du(
            (0, 730, 1427, "SYD", 637), (3, 4427, 4959, "HNL", 592)))),
        ("H9604", "2026-11-15", "2026-11-17", "LAS", t("22:45", "11:42", "12:14", _du(
            (0, 1417, 1761, "LAS", 344), (2, 3192, 3582, "HNL", 390)))),
        ("H9605", "2026-11-18", "2026-11-20", "JFK", t("14:45", "12:40", "17:00", _du(
            (0, 945, 1425, "JFK", 480), (2, 3100, 3640, "HNL", 540)))),
        ("H9606", "2026-11-23", "2026-11-24", "LAX", {"report": "08:00", "last_arr": "16:00", "blk": "14:00",
                                                     "credit": "14:00"}),
        ("H9607", "2026-11-26", "2026-11-27", "SFO", {"report": "07:00", "last_arr": "13:30", "blk": "3:00",
                                                     "credit": "5:00"}),
        ("H9608", "2026-11-30", "2026-12-02", "KIX", t("12:45", "09:20", "17:35", _du(
            (0, 825, 1425, "KIX", 600), (2, 2985, 3440, "HNL", 455)))),
        ("H9609", "2026-12-03", "2026-12-05", "SEA", t("22:00", "22:55", "12:07", _du(
            (0, 1380, 1722, "SEA", 342), (2, 3870, 4255, "HNL", 385)))),
        ("H9610", "2026-12-08", "2026-12-10", "SFO", t("09:00", "18:00", "18:00", _du(
            (0, 600, 1140, "SFO", 540), (2, 3420, 3960, "HNL", None)))),
    ])


def _unknown(rec):
    """F3: H9205 Nov 5 has `rec` (None = no record) on a line of known 10:00 turns, Oct to Jan on file."""
    trips = [(f"H91{d:02d}", f"2026-11-{d:02d}", f"2026-11-{d:02d}", "", {"blk": "10:00", "credit": "10:00", **TURN})
             for d in (2, 12, 20)]
    trips.append(("H9205", "2026-11-05", "2026-11-05", "", rec))
    return _line(trips, ("2026-10", "2026-11", "2026-12", "2027-01"))


# item 4's lines too: nine turns at 101:20 (over), at exactly 100:00 (zero: 0:00 left, far.py OK) and a trip whose duty
# blocks add up to twice its FLICA Block (half100: far.py counts the duty blocks, so Room does)
LINES = {"midday": _midday(), "ryan": _ryan_shaped(), "over": CASES["over"], "zero": CASES["zero"],
         "half100": CASES["half100"]}
UNKNOWN = {"empty": _unknown({}), "none": _unknown(None),
           "noblk": _unknown({"report": "06:00", "last_arr": "20:00", "credit": "10:00"})}


@pytest.fixture(scope="module")
def got():
    """{(case, month): rows} for November and December (month offset 0 and 1); rows = {day: [30h, 100h, Room]}."""
    sync_api = pytest.importorskip("playwright.sync_api")
    from test_cards import _chromium
    page = ("<!doctype html><html><body><script>customElements.define('ha-card', class extends HTMLElement {});"
            "window.fetch = async () => ({ok: false, json: async () => null});</script><script>" + _src()
            + "</script></body></html>")
    out = {}
    with sync_api.sync_playwright() as p:
        b = _chromium(p)
        if not b:
            pytest.skip("no Chromium for Playwright")
        try:
            pg = b.new_page(viewport={"width": 390, "height": 844})
            pg.clock.set_fixed_time("2026-11-13T02:00:00Z")  # Nov 12 16:00 HST
            pg.set_content(page)
            pg.add_style_tag(content=_theme(False))
            for name, st in {**LINES, **UNKNOWN}.items():
                for off, mk in ((0, "2026-11"), (1, "2026-12")):
                    s = copy.deepcopy(st)
                    s["input_number.flight_watcher_month_offset"]["state"] = str(off)
                    out[(name, mk)] = pg.evaluate(JS, {"h": s, "dark": False, "shot": False})
            pg.close()
        finally:
            b.close()
    return out


def _mins(pat, s):
    m = re.search(pat, s)
    assert m, (pat, s)
    return int(m.group(1)) * 60 + int(m.group(2))


def _cells(got, name):
    """{day: (100h text, its block in minutes, Room text, its block in minutes, Room title)} over Nov and Dec."""
    out = {}
    for mk in ("2026-11", "2026-12"):
        for d, cells in got[(name, mk)]["rows"].items():
            if d[:7] != mk or len(cells) != 3:
                continue
            b, r = cells[1], cells[2]
            out[d] = (b["t"], _mins(r"\. (\d+):(\d\d) block flown or scheduled in the 672 h", b["title"]),
                      r["t"], _mins(r"\((\d+):(\d\d) flown or scheduled in the (?:672 h|28 days)", r["title"]), r["title"])
    return out


def _far_line(st):
    """far.py's view of the same line: recall.line_records, as the FAR column of a pickup reads Ryan's line."""
    months = st["sensor.flight_watcher_schedule"]["attributes"]["months"]
    own = st["sensor.flight_watcher_own_trip_times"]["attributes"]["trips"]
    return recall.line_records(months, own, date(2026, 11, 1), date(2026, 11, 30), date(2026, 11, 12))


def _far_day(mine, iso, lim):
    """far._cum on a probe that is the day itself (no flight time of its own): the windows that hold part of the day.
    Returns (over: some window surely over `lim`, its hours: the most surely in one such window when over)."""
    d0 = datetime.combine(date.fromisoformat(iso), datetime.min.time())
    probe = {"label": "the day", "report": d0, "release": d0 + timedelta(days=1), "duties": [], "flying": False}
    res, line, h = far._cum(mine + [probe], probe, far.H672, lim, "flight time", "FAR 117.23(b)(1)")
    over = "even without the pairing" in line
    assert res in ("OK", "?") and (res == "?" or not over), (res, line)
    return over, (h if over else 0.0)


def test_room_finds_the_window_ending_mid_day_that_far_finds(got):
    """F1: the 672 h from Nov 1 10:45 to Nov 29 10:45 hold 101:00 (far.legality's NO on a pickup that day). Every day
    that window holds reads over in Room, Nov 29 and Nov 1 included; the 100h in 672h cell is still the 672 h ending
    24:00 that day."""
    c = _cells(got, "midday")
    for d in range(1, 30):
        iso = f"2026-11-{d:02d}"
        assert c[iso][2] == "1:00 over" and c[iso][3] == 6060, (iso, c[iso])
    assert c["2026-11-29"][:2] == ("9:00 left", 5460)  # the 672 h ending 24:00 Nov 29: H9101 is out
    assert c["2026-11-30"][2:4] == ("9:00 left", 5460)
    assert c["2026-11-29"][4] == ("Room to 100h: 1:00 over. 100:00 minus the busiest 672 h window that holds part of "
                                  "this day (101:00 flown or scheduled in the 672 h ending 10:45 2026-11-29), looking "
                                  "back and forward (FAR 117.23(b)(1)).")
    # far.py on the same line agrees, day by day
    mine = _far_line(LINES["midday"])
    for d in range(1, 31):
        iso = f"2026-11-{d:02d}"
        assert _far_day(mine, iso, 100)[0] == (d <= 29), iso


@pytest.mark.parametrize("name", sorted(LINES))
def test_room_is_over_exactly_when_far_finds_a_window_over_100(got, name):
    """F1: on the same line, for every November day: far.py over -> Room over; Room over -> far.py over, or a window
    ending 24:00 over leg by leg (then far.py reads '?', never OK). Room's block is the larger of far.py's busiest
    window holding the day and the 100h in 672h blocks of that day and the 27 after it (the windows ending 24:00 that
    hold it), so Room never reads more than 100h in 672h."""
    c = _cells(got, name)
    mine = _far_line(LINES[name])
    n_over = n_left = 0
    for d in range(1, 31):
        iso = f"2026-11-{d:02d}"
        h24 = max(c[(date(2026, 11, d) + timedelta(days=k)).isoformat()][1] for k in range(28))
        over, _ = _far_day(mine, iso, 100)
        _, most = _far_day(mine, iso, 0)
        room = c[iso]
        assert room[3] == max(round(most * 60), h24), (iso, room, most, h24)
        assert room[2].endswith(" over") == (over or h24 > 6000), (iso, room, over, h24)
        if over:
            n_over += 1
        else:
            n_left += 1
        assert room[3] >= c[iso][1]  # never more room than the 100h in 672h cell shows
    assert n_over and n_left or name in ("over", "zero", "half100"), (name, n_over, n_left)  # the line has both
    if name == "zero":
        assert {c[f"2026-11-{d:02d}"][2] for d in range(1, 30)} == {"0:00 left"} and n_over == 0


def test_ryan_shaped_line_room_reads_far_s_windows(got):
    """F1 on the widebody-shaped line: the busiest window ending mid-day wins over the windows ending 24:00 on some
    days (Room's title then names its end, HH:MM that day), and a window across Nov 30 counts the trip across the
    month end once."""
    c = _cells(got, "ryan")
    mid = [d for d, x in c.items() if d[:7] == "2026-11" and not re.search(r"ending 24:00 ", x[4])]
    assert mid, "no day where a window ending mid-day is the busiest"
    for d in mid:
        assert re.search(r"in the 672 h ending \d\d:\d\d 2026-1[12]-\d\d\)", c[d][4]), c[d][4]


@pytest.mark.parametrize("case", sorted(UNKNOWN))
def test_a_window_holding_a_trip_with_no_times_reads_approximate(got, case):
    """F3: H9205 Nov 5 has no times on file (no Block and no duties, a {} record, or no record): it adds 0:00, so a
    cell whose window holds it shows '~' and its title says which trip. 100h in 672h: the 672 h ending 24:00 Nov 5 to
    Dec 2 hold it; Room to 100h: the windows holding Oct 8 to Dec 3 can."""
    c = _cells(got, case)
    for iso, (b, bm, r, rm, rt) in sorted(c.items()):
        d = date.fromisoformat(iso)
        in100 = date(2026, 11, 5) <= d <= date(2026, 12, 2)
        inroom = d <= date(2026, 12, 3)
        assert b.startswith("~") == in100, (case, iso, b)
        assert r.startswith("~") == inroom, (case, iso, r)
        rows = {**got[(case, "2026-11")]["rows"], **got[(case, "2026-12")]["rows"]}
        bt = rows[iso][1]["title"]
        assert ("H9205 11/05" in bt) == in100, (case, iso, bt)
        assert ("H9205 11/05" in rt) == inroom, (case, iso, rt)
        if in100:
            assert "~ = not known in full: no block times on file yet for H9205 11/05 (counted 0:00)" in bt, bt
        if inroom:
            assert "~ = not known in full: no block times on file yet for H9205 11/05 (counted 0:00)." in rt, rt
    # the known turns still count: Nov 2, 12 and 20 (30:00) in the 672 h ending 24:00 Nov 20
    assert c["2026-11-20"][:2] == ("~70:00 left", 1800)
    assert c["2026-11-04"][0] == "90:00 left"  # Nov 2's turn only, H9205 not in the window yet


def test_key_says_the_approximate_mark_covers_trips_with_no_times(got):
    """F1 and F3 in the Key: no 'windows ending 24:00 only' caveat; '~' also marks a window holding a trip whose times
    are not read yet."""
    key = dict((r[0], r[1]) for r in got[("midday", "2026-11")]["key"] if len(r) == 2)
    room, t100 = key["Room to 100h"], key["100h in 672h"]
    assert "Only windows ending 24:00 are tried" not in room and "can be less than shown" not in room
    assert "busiest 672 h (28-day) window that holds any part of that day, looking back and forward" in room
    assert ("It tries every window that starts at a duty's start or ends at its block-in, where the busiest one always "
            "is, counting a duty's block when the whole duty is in the window, as a pickup's FAR check does") in room
    assert "so it never shows more room than 100h in 672h" in room
    for k in (room, t100):
        assert "or holds a trip whose times are not read yet (it adds 0:00; hover for which)" in k, k
    heads = {h["t"]: h["title"] for h in got[("midday", "2026-11")]["heads"]}
    assert "Only those windows are tried" not in heads["Room to 100h"]
    assert ("100:00 minus the busiest 672 h window that holds any part of the day, back and forward: the windows "
            "starting at a duty's start or ending at its block-in, as a pickup's FAR check tries them, and those "
            "ending 24:00 HST.") in heads["Room to 100h"], heads["Room to 100h"]
