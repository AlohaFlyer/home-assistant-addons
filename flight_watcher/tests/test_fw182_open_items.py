"""1.8.2: the items its own recheck left open, plus the transition audit's S10 and P5 (Nov 24, 2026).

- failed-past-month-never-retried: a closed month whose read failed once is retried once its back-off is over (it
  was ranked last for ever, and the next month, due on every read, always took the spare load first).
- failed-totals-every-read-when-nothing-due: a totals page that failed is tried once an hour, also when no other month
  is due.
- press-deferred-when-totals-2h-old: a refresh press whose read gives the spare load to the totals is answered by the
  check right after, inside the card's 3 min wait.
- refresh-current-month-mobile-totals: a refresh of the current month on the mobile path reads its Block / Credit too.
- mutations-survive-new-guards: tests for the 1.8.2 guards a mutation removed with no test failing.
- dead-helpers-stale-docstring: no dead parameter, docstrings that say what the code does.
- S10: a carry-in trip two months list (Nov 30) is loaded once on Check now.
- P5: the mobile schedule page of December that starts with the carry-in rows (Nov 30, Dec 1) is dated right.

Review 2 of these fixes: Check now reads the current month's totals too (mobile path); every good Schedule Lookup page
keeps the month list, and the old list stands while its page fails (a failing current month page is loaded hourly, as
the totals, and never starves the other months); only a refresh press starts the check after a deferral at once; the
refresh test asserts the figure the sensor shows; tests for the press guard on loads left and the P5 anchor.

FLICA is never reached: a fake browser answers with synthetic pages (made-up pairings H39xx, "Doe, Jane" 10001)."""
import inspect
import json
import logging
import random
import re
from datetime import date, timedelta

import pytest

import pot
import test_fw182_sched_fresh as SF
from test_fw181_pot_month import at, page
from test_fw182_sched_fresh import DEC6, MIN, _cmd, _ct, _items, _lines, _tick, _w
from test_release_a_flica import INVALID, mk, real_fl  # noqa: F401

H = 3600
STUB = ("own_trip_times", "publish_working_flight", "versions_check", "uploads_check", "capture",
        "detail_probe", "pot_details", "email_check", "pickup_check", "tradeboard_check", "requests_check",
        "grid_check", "publish_finds", "publish_tickets", "enrich", "swap_scan", "drop_scan",
        "publish_near_misses")


def _loop(W, F, full=False, lo=300, hi=420, rnd=None):
    """One check's schedule part (as _tick) and then the next check's time as the main loop has it: right away when
    the check asked for one (WAKE_DUE: a wake from inside the check, a pilot's at his floor), else 5 to 7 min later
    (the add-on's normal pace)."""
    W.WAKE_DUE["at"] = 0.0
    got = _tick(W, F, full=full, step=0)
    if W.WAKE_DUE["at"]:
        W.CLOCK.t = max(W.CLOCK.t + 1, W.WAKE_DUE["at"])
    else:
        W.CLOCK.t += (rnd or random).uniform(lo, hi)
    return got


def _gaps(ts):
    return [b - a for a, b in zip(ts, ts[1:])]


def _median(v):
    return sorted(v)[len(v) // 2]


# ---------------------------------------------------------------- failed-past-month-never-retried
def _octo_run(mk, mobile, always=False, hours=30, seed=21):
    """October's Schedule Lookup page is not a schedule once (always: on every load) from the start; the schedule part
    of a check every 5 to 7 min. Returns W, F, the October loads [(hour, bad)] and every schedule load."""
    W, F = _w(mk, mobile=mobile)
    F.bad.add("1026")
    rnd, t0, octo, every = random.Random(seed), W.CLOCK.t, [], []
    while W.CLOCK.t < t0 + hours * H:
        got = _loop(W, F, rnd=rnd)
        every += got
        for t, bd in got:
            if bd == "1026":
                octo.append(((t - t0) / H, "1026" in F.bad))
                if not always:
                    F.bad.discard("1026")
    return W, F, octo, every


def test_failed_closed_month_is_retried_after_its_back_off_lookup_path(mk):
    """1.8.2 (failed-past-month-never-retried): October fails once; it is read again after its 1 h back-off (and one
    read), then once a day. December keeps its 30 min cadence meanwhile."""
    W, F, octo, every = _octo_run(mk, mobile=False)
    assert octo and octo[0][1] is True, octo
    assert len(octo) >= 2 and octo[1][1] is False, octo  # it was never loaded again (sched_other_fail kept n 1)
    assert 1.0 <= octo[1][0] - octo[0][0] <= 2.3, octo  # its 1 h back-off, one read, then the next read
    assert "2026-10" not in (W.S.get("sched_other_fail") or {})
    assert all(b[0] - a[0] >= 23.5 for a, b in zip(octo[1:], octo[2:])), octo  # then once a day
    dec = [t for t, bd in every if bd == "1226"]
    assert max(_gaps(dec)) <= 75 * MIN and _median(_gaps(dec)) <= 37 * MIN, [round(g / 60) for g in _gaps(dec)]


def test_failed_closed_month_is_retried_after_its_back_off_mobile_path(mk):
    W, F, octo, every = _octo_run(mk, mobile=True)
    assert octo and octo[0][1] is True, octo
    assert len(octo) >= 2 and octo[1][1] is False, octo
    assert 1.0 <= octo[1][0] - octo[0][0] <= 2.3, octo
    assert "2026-10" not in (W.S.get("sched_other_fail") or {})
    dec = [t for t, bd in every if bd == "1226"]
    assert max(_gaps(dec)) <= 140 * MIN and _median(_gaps(dec)) <= 70 * MIN, [round(g / 60) for g in _gaps(dec)]


def test_a_closed_month_that_keeps_failing_is_tried_once_per_back_off_step(mk):
    """Its back-off: 1 h, 2 h, 4 h, then 6 h; one load each step (after the step and at most one read more)."""
    W, F, octo, every = _octo_run(mk, mobile=False, always=True, hours=30)
    hours = [h for h, _ in octo]
    steps = [min(6.0, 2.0 ** i) for i in range(len(hours) - 1)]
    assert len(hours) >= 5, hours  # it was tried once (then never: ranked last for ever)
    for g, s in zip(_gaps(hours), steps):
        assert s <= g <= s + 1.3, (hours, steps)  # never twice in a step, never skipped for good
    assert all(bad for _, bad in octo)
    dec = [t for t, bd in every if bd == "1226"]
    assert max(_gaps(dec)) <= 75 * MIN and _median(_gaps(dec)) <= 37 * MIN


def test_a_failing_month_is_ordered_last_until_it_waited_a_read_past_its_back_off(mk):
    W, F = _w(mk)
    t = W.CLOCK.t
    W.S["schedule"] = {"2026-11": {"items": [], "days": [], "src": "lookup", "read_ts": t}}
    W.S["sched_other_fail"] = {"2026-12": {"n": 1, "next": t}}  # its back-off ends now
    assert W.other_months_order(("1026", "1126", "1226"), "2026-11") == ["2026-10", "2026-12"]
    W.CLOCK.t = t + 29 * MIN  # still inside one read past it
    assert W.other_months_order(("1026", "1126", "1226"), "2026-11") == ["2026-10", "2026-12"]
    W.CLOCK.t = t + 30 * MIN  # it waited a read: ordered like any month again (a future month first)
    assert W.other_months_order(("1026", "1126", "1226"), "2026-11") == ["2026-12", "2026-10"]
    W.S["sched_other_fail"] = {"2026-12": {"n": "x", "next": "bad"}}  # an odd value from an older state
    assert W.other_months_order(("1026", "1126", "1226"), "2026-11") == ["2026-12", "2026-10"]


# ---------------------------------------------------------------- failed-totals-every-read-when-nothing-due
def test_a_failing_totals_page_is_tried_hourly_when_no_other_month_is_due(mk):
    """Mobile path, November's Schedule Lookup page (the totals) fails and every other month backs off: the totals
    page is loaded once an hour (it was on every read)."""
    W, F = _w(mk, mobile=True)
    for _ in range(6):
        _tick(W, F, step=30 * MIN)  # the totals, December and October in hand
    F.bad.add("1126")
    W.S["sched_other_fail"] = {m: {"n": 4, "next": W.CLOCK.t + 6 * H} for m in ("2026-10", "2026-12")}
    t0, every = W.CLOCK.t, []
    while W.CLOCK.t < t0 + 4 * H:
        every += _tick(W, F)
    tot = [t for t, bd in every if bd == "1126"]
    reads = [t for t, bd in every if bd == "mobile"]
    assert len(reads) >= 8, reads
    assert 3 <= len(tot) <= 5 and min(_gaps(tot)) >= 60 * MIN, [round((t - t0) / 60) for t in tot]
    assert W.S["schedule"]["2026-11"]["totals"]["credit"] == "85:00"  # the figures last stored stay


def _credit(monkeypatch, credit):
    """FLICA's totals changed: every Schedule Lookup page from now on shows this Credit ('91.00')."""
    lk = SF._lk
    monkeypatch.setattr(SF, "_lk", lambda bd, trips, months=SF.LISTED, c=credit: lk(bd, trips, months, c))


def _hourly(ts, t0, hours):
    """How many of the times ts fall in each hour from t0."""
    return [sum(1 for t in ts if t0 + h * H <= t < t0 + (h + 1) * H) for h in range(hours)]


def test_a_failing_current_month_lookup_page_never_starves_the_other_months(mk):
    """Review 2 (current-lookup-page-fails-starves-other-months, failing-list-page-still-every-read-for-3h): only
    November's Schedule Lookup page fails, the totals page and the only page the month list was kept from. Every good
    page of another month carries the same month list and keeps it, so December keeps its cadence past 6 h and
    November's page is loaded once an hour at most (as the totals). It was loaded on every read from about 4.6 h, as
    the totals one read and the list page the next, December never again; the lookup breaker stopped it at 7.6 h)."""
    W, F = _w(mk, mobile=True)
    for _ in range(6):
        _tick(W, F, step=30 * MIN)
    F.bad.add("1126")
    t0, every = W.CLOCK.t, []
    while W.CLOCK.t < t0 + 14 * H:
        every += _tick(W, F)
    tot = [t for t, bd in every if bd == "1126"]
    dec = [t for t, bd in every if bd == "1226"]
    assert max(_hourly(tot, t0, 14)) <= 1 and min(_gaps(tot)) >= 59 * MIN, _hourly(tot, t0, 14)
    assert min(_hourly(dec, t0, 14)) >= 1, _hourly(dec, t0, 14)  # December every hour, past 6 h too
    assert max(_gaps(dec)) <= 2 * H + 15 * MIN and _median(_gaps(dec)) <= 70 * MIN, [round(g / 60) for g in _gaps(dec)]
    assert W.BRK.allow("lookup") and W.S["schedule"]["2026-11"]["totals"]["credit"] == "85:00"
    assert W.CLOCK.t - W.S["lookup_months"]["at"] < 2 * H  # the list kept by December's pages


def test_a_failing_list_page_with_no_other_month_due_is_loaded_hourly_and_the_old_list_stands(mk):
    """Review 2 (failing-list-page-still-every-read-for-3h), early in the month: FLICA lists only the closed October
    and November (December not out yet), and November's page fails. No good page keeps the list for 6 h (October is
    read once a day): the old list stands while the page it comes from fails, so that page is loaded once an hour (as
    the totals) and October is still read once a day. It was loaded on every read (the totals, then the list page)
    until the lookup breaker stopped it, and October was never read again."""
    W, F = _w(mk, mobile=True)
    F.months = ["1026", "1126"]
    for _ in range(6):
        _tick(W, F, step=30 * MIN)
    F.bad.add("1126")
    t0, every = W.CLOCK.t, []
    while W.CLOCK.t < t0 + 50 * H:
        every += _tick(W, F)
    tot = [t for t, bd in every if bd == "1126"]
    octo = [t for t, bd in every if bd == "1026"]
    assert max(_hourly(tot, t0, 50)) <= 1 and min(_gaps(tot)) >= 59 * MIN, _hourly(tot, t0, 50)
    assert len(tot) >= 40, len(tot)  # tried hourly, never given up
    assert len(octo) == 2 and all(23.5 * H <= g <= 26 * H for g in _gaps(octo)), [(t - t0) / H for t in octo]
    assert W.BRK.allow("lookup")
    F.bad.discard("1126")  # the page works again: the list is read from it
    while W.CLOCK.t < t0 + 52 * H:
        _tick(W, F)
    assert W.CLOCK.t - W.S["lookup_months"]["at"] < 1.5 * H and W.S["sched_totals"]["ok"] is True


# ---------------------------------------------------------------- press-deferred-when-totals-2h-old
def _mobile_after_dec(mk, instance=""):
    """Mobile path, normal reads until the read before loaded December; then the next read is due and the totals are
    2 h old (marks kept coming, or the closed month's daily turn)."""
    W, F = _w(mk, instance, mobile=True)
    rnd = random.Random(6)
    for _ in range(12):
        _tick(W, F, step=5 * MIN)
    while [bd for _, bd in _tick(W, F, step=rnd.uniform(300, 420))] != ["mobile", "1226"]:
        pass
    W.CLOCK.t = W.S["sched_checked_at"] + 31 * MIN
    W.S["sched_totals"]["at"] = W.CLOCK.t - 125 * MIN
    W.S["machine"], W.S["last_check_ts"] = "idle", W.CLOCK.t - 120
    return W, F


def _press_seq(W, F, month="2026-12", n=4):
    assert _cmd(W, json.dumps({"month": month})) is True
    t_press, seq = W.CLOCK.t, []
    for _ in range(n):
        got = _loop(W, F, rnd=random.Random(2))
        seq.append(((got[0][0] - t_press) / 60 if got else None, [bd for _, bd in got],
                    (W.S.get("sched_refresh") or {}).get("state")))
    return seq


def test_a_press_the_totals_put_off_is_read_by_the_check_right_after(mk):
    """The press's read gives its spare load to the totals (2 h old, December read at the read before): December's
    mark forces the next check's read, and that check runs right after (it was 5 to 7 min later, past the card's 3 min
    wait: 'Not refreshed: no new read from FLICA in 3 min' first)."""
    W, F = _mobile_after_dec(mk)
    seq = _press_seq(W, F)
    assert seq[0][1] == ["mobile", "1126"] and seq[0][2] == "queued", seq
    assert seq[1][1] == ["mobile", "1226"] and seq[1][2] == "read", seq
    assert seq[1][0] <= 3, seq  # inside the card's RF_WAIT_MS (3 min)
    assert seq[2][1] == [] and seq[3][1] == [], seq  # 4 loads in all, no loop
    assert W.S["sched_totals"]["ok"] is True and not W.S.get("sched_stale")


def test_a_pilots_press_the_totals_put_off_waits_only_for_his_check_floor(mk):
    W, F = _mobile_after_dec(mk, "pilot2")
    seq = _press_seq(W, F)
    assert [s[1] for s in seq[:2]] == [["mobile", "1126"], ["mobile", "1226"]], seq
    assert seq[1][2] == "read" and seq[1][0] <= 3, seq


# ---------------------------------------------------------------- refresh-current-month-mobile-totals
def test_a_refresh_of_the_current_month_on_the_mobile_path_reads_its_totals_too(mk, monkeypatch):
    """Ryan's 'if I don't think that it's right': the press for November re-reads the mobile page and its Block /
    Credit (the totals were 30 min old and December took the spare load; the card said Refreshed with totals up to
    2 h old). Review 2 (tests-assert-loads-not-what-ryan-sees): FLICA's Credit changed before the press, and the
    schedule sensor the card reads shows the new figure, not the one stored before."""
    W, F = _w(mk, mobile=True)
    for _ in range(4):
        _tick(W, F, step=30 * MIN)
    W.S["sched_totals"]["at"] = W.CLOCK.t - 30 * MIN
    W.S["schedule"]["2026-12"]["read_ts"] = W.CLOCK.t - 31 * MIN  # December is due
    W.S["machine"] = "idle"
    assert W.MQ.last(f"{W.T}/schedule")["months"]["2026-11"]["totals"]["credit"] == "85:00"
    _credit(monkeypatch, "91.00")
    assert _cmd(W, json.dumps({"month": "2026-11"})) is True
    got = _tick(W, F)
    sensor = W.MQ.last(f"{W.T}/schedule")
    assert sensor["months"]["2026-11"]["totals"]["credit"] == "91:00", sensor["months"]["2026-11"]["totals"]
    assert sensor["refresh"]["month"] == "2026-11" and sensor["refresh"]["state"] == "read", sensor["refresh"]
    assert [bd for _, bd in got] == ["mobile", "1126"], got
    assert W.totals_age("2026-11") <= 7 * MIN and W.S["sched_totals"]["ok"] is True
    assert W.S["sched_refresh"]["state"] == "read"
    W.CLOCK.t = W.S["sched_checked_at"] + 31 * MIN
    assert [bd for _, bd in _tick(W, F)] == ["mobile", "1226"]  # December at the next read (it waited one)


def test_a_current_month_press_hands_a_marked_months_read_to_the_next_check(mk):
    """A trigger marked December; a press for November in the same check: November's totals first, then December at
    the check right after (its mark is not lost and forces one read). Review 2: a trigger's mark (Check now's own
    waits for the next due read: test_check_now_on_the_mobile_path_reads_the_totals_then_the_marked_month)."""
    W, F = _w(mk, mobile=True)
    for _ in range(4):
        _tick(W, F, step=30 * MIN)
    W.S["sched_totals"]["at"] = W.CLOCK.t - 30 * MIN
    W.S["machine"] = "idle"
    assert W.mark_stale("2026-12", "his own trip H3913 2026-12-04 is in the open time pot") is True
    assert _cmd(W, json.dumps({"month": "2026-11"})) is True
    seq = [[bd for _, bd in _loop(W, F)] for _ in range(3)]
    assert seq == [["mobile", "1126"], ["mobile", "1226"], []], seq
    assert not W.S.get("sched_stale")


def test_a_current_month_press_on_the_lookup_path_needs_no_totals_load(mk):
    W, F = _w(mk)
    _tick(W, F)
    W.S["machine"] = "idle"
    assert _cmd(W, json.dumps({"month": "2026-11"})) is True
    got = [bd for _, bd in _tick(W, F)]
    assert got[0] == "1126" and len(got) <= 2 and got.count("1126") == 1, got


# ---------------------------------------------------------------- mutations-survive-new-guards
def _seat(W, F, monkeypatch):
    W.OPTS["my_name"] = "Doe"
    crew = {"now": [["FO", "DOE, JANE"]]}
    monkeypatch.setattr(W, "parse_detail", lambda html: {"report": "08:00", "last_arr": "18:00", "blk": "10:00",
                                                         "credit": "12:00", "crew": crew["now"], "duties": []})
    return crew


def test_guard_seat_trigger_rearms_when_his_seat_is_set_again(mk, caplog, monkeypatch):
    """(1) seat_trigger: the seat set again ends the evidence, so a later change fires a second read."""
    W, F = _w(mk)
    _tick(W, F)
    crew = _seat(W, F, monkeypatch)
    W.own_trip_times(F.fl, full=True)
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        crew["now"] = [["FO", "ROE, PAT"]]
        W.own_trip_times(F.fl, full=True)  # off the trip: fires
        assert [bd for _, bd in _tick(W, F)] == ["1126", "1226"]
        crew["now"] = [["FO", "DOE, JANE"]]
        W.CLOCK.t += 10 * MIN
        W.own_trip_times(F.fl, full=True)  # back on it: the evidence ends
        assert "H3913|2026-12-04" not in W.S["sched_trig"]["a"]
        crew["now"] = [["FO", "ROE, PAT"]]
        W.CLOCK.t += 10 * MIN
        W.own_trip_times(F.fl, full=True)  # off again: a new change, a second read
    assert len(_lines(caplog, "schedule 2026-12: read early (own trip H3913 2026-12-04")) == 2


def test_guard_pot_row_seen_time_keeps_a_7_h_row_from_firing_twice(mk, caplog):
    """(2) pot_own_trigger refreshes the evidence's seen time on every check the row is in the pot: a row in the pot
    for 7 h, gone for one check and back fires no second read."""
    W, F = _w(mk)
    _tick(W, F)
    row = {"pairing": "H3913", "start": "04Dec", "dates": "04Dec"}
    t0 = W.CLOCK.t
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        while W.CLOCK.t < t0 + 7 * H:
            W.pot_own_trigger({"2026-12": {"H3913|04Dec": row}}, {"2026-12"})
            _tick(W, F)
        W.pot_own_trigger({"2026-12": {}}, {"2026-12"})  # one check without it
        _tick(W, F)
        W.pot_own_trigger({"2026-12": {"H3913|04Dec": row}}, {"2026-12"})  # back
    assert len(_lines(caplog, "schedule 2026-12: read early")) == 1
    assert W.S["sched_trig"]["b"]["H3913|2026-12-04"]["fired"] is True


def test_guard_lookup_totals_with_no_load_left_does_not_count_as_their_turn(mk):
    """(3) lookup_totals raises SchedFull before it stamps sched_totals: a read with no load left is not the totals'
    turn (they would wait an hour unloaded)."""
    W, F = _w(mk, mobile=True)
    _tick(W, F)
    before = json.dumps(W.S.get("sched_totals"), sort_keys=True)
    n = len(F.fl.loads)
    W.SCHED_READ["left"] = 0
    try:
        try:
            W.lookup_totals(F.fl, "2026-11")
            raised = False
        except W.SchedFull:
            raised = True
    finally:
        W.SCHED_READ["left"] = None
    assert raised and json.dumps(W.S.get("sched_totals"), sort_keys=True) == before and len(F.fl.loads) == n


def test_guard_seat_evidence_goes_with_its_trip(mk, monkeypatch):
    """(4) own_trip_times prunes the seat trigger's evidence of a trip no longer on his schedule."""
    W, F = _w(mk)
    _tick(W, F)
    crew = _seat(W, F, monkeypatch)
    W.own_trip_times(F.fl, full=True)
    crew["now"] = [["FO", "ROE, PAT"]]
    W.own_trip_times(F.fl, full=True)
    assert "H3913|2026-12-04" in W.S["sched_trig"]["a"]
    F.pg["1226"] = list(DEC6)
    _tick(W, F)  # December now holds the Dec 6 trip
    assert _items(W, "2026-12") == [("H3913", "2026-12-06")]
    W.own_trip_times(F.fl)
    assert "H3913|2026-12-04" not in W.S["sched_trig"]["a"]


def test_guard_crewtrac_evidence_is_dropped_once_its_month_is_the_current_one(mk):
    """(5) sched_triggers_fire drops a CrewTrac month's evidence once that month is the current one (it is read every
    30 min anyway; a mark would be refused for ever)."""
    W, F = _w(mk, t=at(2026, 12, 3, 12, 0))
    W.S["sched_trig"] = {"a": {}, "b": {}, "c": {"2026-12": {"month": "2026-12", "sid": "s1", "fired": False,
                                                           "why": "the CrewTrac check differs in December 2026",
                                                           "at": W.CLOCK.t - 10 * MIN}}}
    W.sched_triggers_fire()
    assert "2026-12" not in W.S["sched_trig"]["c"]


def test_guard_the_most_overdue_late_month_goes_first(mk):
    """(6) other_months_order: of two months that already waited a read, the most overdue first."""
    W, F = _w(mk)
    t = W.CLOCK.t
    W.S["schedule"] = {"2026-11": {"items": [], "days": [], "src": "lookup", "read_ts": t},
                       "2026-12": {"items": [], "days": [], "src": "lookup", "read_ts": t - 150 * MIN},
                       "2027-01": {"items": [], "days": [], "src": "lookup", "read_ts": t - 330 * MIN}}
    bds = ("1126", "1226", "0127")
    assert W.other_months_order(bds, "2026-11") == ["2027-01", "2026-12"]
    W.S["schedule"]["2027-01"]["read_ts"] = t - 10 * MIN  # January fresh, December late: December first
    assert W.other_months_order(bds, "2026-11") == ["2026-12", "2027-01"]


def test_guard_a_current_month_read_on_lookup_stamps_its_totals(mk):
    """A current month read on Schedule Lookup carries its totals: they count as loaded at that read's start."""
    W, F = _w(mk)
    _tick(W, F)
    assert W.S["sched_totals"] == {"month": "2026-11", "at": W.S["sched_checked_at"], "ok": True}
    assert W.totals_age("2026-11") < 7 * MIN


def test_guard_an_old_month_list_names_no_next_month(mk):
    """next_other_month names no month while the month list is older than LOOKUP_MONTHS_KEEP_S (other_months_check
    then loads the list page first)."""
    W, F = _w(mk)
    _tick(W, F)
    W.CLOCK.t += 31 * MIN
    assert W.next_other_month("2026-11")[0] in ("2026-10", "2026-12")
    W.S["lookup_months"]["at"] = W.CLOCK.t - W.LOOKUP_MONTHS_KEEP_S - 1
    assert W.next_other_month("2026-11") == ("", "")


# ---------------------------------------------------------------- dead-helpers-stale-docstring
def test_no_dead_parameter_and_the_docstrings_say_what_decides_the_spare_load(mk):
    W, F = _w(mk)
    assert list(inspect.signature(W.other_months_pending).parameters) == ["cur_month"]
    doc = W.other_months_pending.__doc__
    assert "this read's last load goes to it" not in doc and "totals_first" in doc
    src = inspect.getsource(W)
    assert len(re.findall(r"\btotals_stale\(", src)) >= 2  # defined and called (it had no caller)
    assert "stale_only" not in src


# ---------------------------------------------------------------- S10: a carry-in trip loaded once
def _it(trip, start, end, lay):
    return {"trip": trip, "start": start, "end": end, "lay": lay}


def test_s10_a_carry_in_trip_both_months_list_is_loaded_once_on_check_now(mk, monkeypatch):
    """H3907 Nov 30 to Dec 2 is November's carry-in and the first row of December's page too: Check now loads its
    pairing page once (it was twice: one wasted paced FLICA load per carry-in). H3907 Dec 12 (the same pairing number
    in December) is its own trip and loaded too."""
    W, F = _w(mk, t=at(2026, 11, 23, 9, 0))
    carry = _it("H3907", "2026-11-30", "2026-12-02", "KIX")
    W.S["schedule"] = {
        "2026-11": {"month": "2026-11", "days": [], "src": "lookup", "items": [_it("H3901", "2026-11-05", "2026-11-06",
                                                                                   "LAX"), carry]},
        "2026-12": {"month": "2026-12", "days": [], "src": "lookup",
                    "items": [dict(carry), _it("H3913", "2026-12-06", "2026-12-08", "LAS"),
                              _it("H3907", "2026-12-12", "2026-12-14", "JFK")]}}
    _seat(W, F, monkeypatch)
    for full in (True, True):
        n = len(F.fl.loads)
        W.own_trip_times(F.fl, full=full)
        got = [re.search(r"PID=(\w+)&DATE=(\d+)", u).groups() for _, u in F.fl.loads[n:] if "mobilepairing" in u]
        assert sorted(got) == [("H3901", "20261105"), ("H3907", "20261130"), ("H3907", "20261212"),
                               ("H3913", "20261206")], got
    assert set(W.S["own_trips"]) >= {"H3907|2026-11-30", "H3907|2026-12-12", "H3913|2026-12-06"}


# ---------------------------------------------------------------- P5: December's mobile page with carry-in rows
DOW7 = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")


def _mob(hdr, start, end, trips, totals=""):
    """A synthetic mobile schedule page (pot.parse_schedule's layout) whose rows run from start to end (dates);
    trips {date: (activity, layover)}; hdr 'Dec 2026'."""
    rows, d = [], start
    while d <= end:
        act, lay = trips.get(d, ("", "-"))
        rows.append(f"<tr><td>{DOW7[d.weekday()]}</td><td>{d.day:02d}</td><td>{act or '-'}</td><td>{lay or '-'}</td>"
                    "</tr>")
        d += timedelta(days=1)
    return (f"<html><body><div>{hdr} Schedule</div><table><tr><td>Schedule Updated:<br>Nov 23, 2026 06:50:44 HA</td>"
            "</tr></table><table border=1><tr><th>Day</th><th>Pairing</th><th>Layover</th></tr>" + "".join(rows) +
            f"</table>{totals}</body></html>")


def _dec_trips():
    t = {date(2026, 11, 30): ("<a>H3907</a>", "KIX"), date(2026, 12, 1): ("", "-"), date(2026, 12, 2): ("", "HNL"),
         date(2026, 12, 6): ("<a>H3913</a>", "LAS"), date(2026, 12, 7): ("", "-"), date(2026, 12, 8): ("", "HNL"),
         date(2026, 12, 30): ("<a>H3920</a>", "SEA"), date(2026, 12, 31): ("", "-"), date(2027, 1, 1): ("", "HNL")}
    for d in range(18, 25):
        t[date(2026, 12, d)] = ("VAC", "-")
    return t


DEC_CARRY = _mob("Dec 2026", date(2026, 11, 30), date(2027, 1, 1), _dec_trips())


def test_p5_a_december_page_that_starts_with_the_carry_in_rows_is_dated_right():
    s = pot.parse_schedule(DEC_CARRY)
    assert s["month"] == "2026-12"
    assert s["days"][0] == ["2026-11-30", "H3907", "KIX"] and s["days"][1][0] == "2026-12-01", s["days"][:3]
    assert s["days"][-1][0] == "2027-01-01" and len(s["days"]) == 33
    assert [(i["trip"], i["start"], i["end"]) for i in s["items"]] == [
        ("H3907", "2026-11-30", "2026-12-02"), ("H3913", "2026-12-06", "2026-12-08"),
        ("VAC", "2026-12-18", "2026-12-24"), ("H3920", "2026-12-30", "2027-01-01")]
    # no Days Off on the page (the OT drop view): December's own days are counted, never the carry-in's
    work = {"2026-11-30", "2026-12-01", "2026-12-02", "2026-12-06", "2026-12-07", "2026-12-08", "2026-12-30",
            "2026-12-31"}
    assert s["totals"]["days_off"] == 31 - len([d for d in work if d.startswith("2026-12")])


def test_p5_pages_without_carry_in_rows_and_the_year_change_are_unchanged():
    for st in (date(2026, 12, 1), date(2026, 12, 2)):  # the calendar month's start, the bid period's start
        s = pot.parse_schedule(_mob("Dec 2026", st, date(2026, 12, 31), _dec_trips()))
        assert s["month"] == "2026-12" and s["days"][0][0] == st.isoformat(), s["days"][:2]
        assert ("H3913", "2026-12-06") in [(i["trip"], i["start"]) for i in s["items"]]
    # January's page that starts with Dec 31 (a carry-in): last year's December
    jan = {date(2026, 12, 31): ("<a>H3930</a>", "LAX"), date(2027, 1, 1): ("", "HNL")}
    s = pot.parse_schedule(_mob("Jan 2027", date(2026, 12, 31), date(2027, 1, 30), jan))
    assert s["month"] == "2027-01" and s["days"][0] == ["2026-12-31", "H3930", "LAX"]
    assert s["items"][0] == {"trip": "H3930", "start": "2026-12-31", "end": "2027-01-01", "lay": "LAX"}
    # November's page with its Dec 1 row (the bid period's last day) still rolls forward
    s = pot.parse_schedule(_mob("Nov 2026", date(2026, 11, 1), date(2026, 12, 1), {}))
    assert (s["month"], s["days"][0][0], s["days"][-1][0]) == ("2026-11", "2026-11-01", "2026-12-01")


def test_p5_the_watcher_stores_the_carry_in_page_as_december_with_the_right_dates(mk):
    """Dec 3: Schedule Lookup refused, the learned mobile page is December's with its carry-in rows first."""
    W = mk(t=at(2026, 12, 3, 9, 0))
    W.S["own_emp"] = "10001"
    W.S["sched_shape"] = W.S["sched_shape_mobile"] = "/full/mobileschedule.cgi?BCID=001.{n}&From=MainMenu"

    def answer(u):
        if "mobileschedule" in u:
            return DEC_CARRY
        return INVALID
    fl = real_fl(W, answer)
    W.schedule_check(fl, force=True)
    dec = W.S["schedule"]["2026-12"]
    assert dec["days"][0][0] == "2026-11-30"
    assert [(i["trip"], i["start"]) for i in dec["items"]][:2] == [("H3907", "2026-11-30"), ("H3913", "2026-12-06")]
    assert all("2026-11-30" <= d[0] <= "2027-01-01" for d in dec["days"]), dec["days"]


# ---------------------------------------------------------------- the cadence through check() itself
def _setup(mk, instance="", mobile=False, t=None):
    pots = {"003.152": page([("H3902", "28Nov")]), "003.153": page([("H3911", "12Dec")])}
    W, F = _w(mk, instance, t=t or at(2026, 11, 23, 0, 0), mobile=mobile, pots=pots)
    for f in STUB:
        setattr(W, f, lambda *a, **k: None)
    W.close_in_check = lambda *a, **k: ({}, "ok")
    W.crew_index_check = lambda *a, **k: "ok"
    W.S["pot_month"], W.S["pot_urls"] = "Both", {}
    return W, F


def _run(W, F, hours, seed=1, hook=None):
    """check() every 5 to 7 min (or right after one that asked for it, as the main loop), hours long: every schedule
    load [(time, bd or 'mobile')] and the loads of each read."""
    rnd, t0, loads, reads = random.Random(seed), W.CLOCK.t, [], []
    while W.CLOCK.t < t0 + hours * H:
        if hook:
            hook(W, F)
        n, before = len(F.fl.loads), W.S.get("sched_checked_at")
        W.WAKE_DUE["at"] = 0.0
        W.RUN.update(check=True, aborted="", skipped=set())
        try:
            assert W.check(F.fl) == "ok"
        finally:
            W.RUN["check"] = False
        got = F.sched(n)
        loads += got
        if W.S.get("sched_checked_at") != before:
            reads.append(got)
        W.CLOCK.t = max(W.CLOCK.t + 1, W.WAKE_DUE["at"]) if W.WAKE_DUE["at"] else W.CLOCK.t + rnd.uniform(300, 420)
    return t0, loads, reads


def _cadence(W, F, hours, mobile):
    t0, loads, reads = _run(W, F, hours)
    dec = [t for t, bd in loads if bd == "1226"]
    octo = [t for t, bd in loads if bd == "1026"]
    g = _gaps(dec)
    assert max(len(r) for r in reads) <= 2, reads
    if mobile:
        assert _median(g) <= 70 * MIN and max(g) <= 2 * H + 15 * MIN, [round(x / 60) for x in g]
        tot = [t for t, bd in loads if bd == "1126"]
        assert max(_gaps(tot)) <= 2 * H + 15 * MIN, [round(x / 60) for x in _gaps(tot)]
    else:
        assert _median(g) <= 35 * MIN + 30 and max(g) <= 75 * MIN, [round(x / 60) for x in g]
    assert hours // 24 <= len(octo) <= hours // 24 + 1 and all(23.5 * H <= x <= 26 * H for x in _gaps(octo)), octo
    return loads


def test_cadence_through_check_lookup_path_48_h(mk):
    W, F = _setup(mk)
    _cadence(W, F, 48, mobile=False)


def test_cadence_through_check_mobile_path_48_h_a_pilot(mk):
    W, F = _setup(mk, "pilot2", mobile=True)
    _cadence(W, F, 48, mobile=True)


def test_cadence_through_check_october_fails_once_then_reads(mk):
    """Ryan's Dec 1 case in small: the closed month's page is wrong once; it is read again within about 2 h."""
    W, F = _setup(mk)
    F.bad.add("1026")

    def hook(W, F):  # wrong once: from the check after its first load on, October's page is right
        if any("bd=1026" in u for _, u in F.fl.loads):
            F.bad.discard("1026")
    t0, loads, reads = _run(W, F, 30, hook=hook)
    octo = [(t - t0) / H for t, bd in loads if bd == "1026"]
    assert len(octo) >= 2 and octo[1] - octo[0] <= 2.3, octo
    assert W.S["schedule"]["2026-10"]["src"] == "lookup" and "2026-10" not in (W.S.get("sched_other_fail") or {})


def test_cadence_crewtrac_and_pot_triggers_still_fire_once(mk, caplog, monkeypatch):
    """The early reads are unchanged: a CrewTrac mismatch in December reads it at once, once."""
    W, F = _w(mk)
    _tick(W, F)
    snap = {"pulled_at": "2026-11-23T10:00:00Z", "trips": [], "months": {}}
    _ct(W, monkeypatch, snap, [{"trip": "H3913", "start": "2026-12-04", "ok": False, "line": "x"}])
    W.CLOCK.t += 10 * MIN
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        W.crewtrac_check()
        got = [[bd for _, bd in _loop(W, F)] for _ in range(3)]
    assert got[0] == ["1126", "1226"] and got[1:] == [[], []], got
    assert len(_lines(caplog, "schedule 2026-12: read early")) == 1


# ---------------------------------------------------------------- review 2: check-now-mobile-totals-still-stale
def _until_read(W, F, n=20):
    """The schedule part of the checks (paced 5 to 7 min) up to the first that reads: [(seconds after the read before
    started, [bd or 'mobile'])], the checks that loaded nothing first."""
    t_read, seq = W.S["sched_checked_at"], []
    for _ in range(n):
        got = [bd for _, bd in _loop(W, F, rnd=random.Random(4))]
        seq.append((W.S["sched_checked_at"] - t_read if got else None, got))
        if got:
            break
    assert all(not r for _, r in seq[:-1]), seq
    return seq


def _mobile_settled(mk, instance=""):
    """Mobile path, four reads 30 min apart (the totals, December and October in hand); then the totals are 30 min
    old and December is due."""
    W, F = _w(mk, instance, mobile=True)
    for _ in range(4):
        _tick(W, F, step=30 * MIN)
    W.S["sched_totals"]["at"] = W.CLOCK.t - 30 * MIN
    W.S["schedule"]["2026-12"]["read_ts"] = W.CLOCK.t - 31 * MIN
    W.S["machine"], W.S["last_check_ts"] = "idle", W.CLOCK.t - 120
    return W, F


@pytest.mark.parametrize("instance", ["", "pilot2"])
def test_check_now_on_the_mobile_path_reads_the_totals_then_the_marked_month(mk, monkeypatch, instance):
    """Check now (Ryan, Both; a pilot, This month) re-reads the current month's Block / Credit as 1.8.1 did (it gave
    the spare load to the December it marked, the totals shown up to 1 to 2 h old). December, marked by Check now,
    goes first at the next due read: no check started early for it (no card waits on Check now) and no second
    schedule read (Check now loads what it did before: two pages)."""
    W, F = _mobile_settled(mk, instance)
    _credit(monkeypatch, "91.00")
    first = [bd for _, bd in _loop(W, F, full=True, rnd=random.Random(5))]
    assert first == ["mobile", "1126"], first
    assert W.WAKE_DUE["at"] == 0.0  # the next check at its pace
    assert W.MQ.last(f"{W.T}/schedule")["months"]["2026-11"]["totals"]["credit"] == "91:00"
    assert W.totals_age("2026-11") <= 7 * MIN and W.S["sched_totals"]["ok"] is True
    seq = _until_read(W, F)
    assert seq[-1][1] == ["mobile", "1226"] and seq[-1][0] >= 30 * MIN, seq  # the next due read, none forced before
    assert not W.S.get("sched_stale")


def test_check_now_reads_the_totals_at_most_once_in_5_min(mk):
    """Check now right after a read that loaded the totals: December takes the spare load (the totals are fresh)."""
    W, F = _mobile_settled(mk)
    W.S["sched_totals"]["at"] = W.CLOCK.t - 3 * MIN
    assert [bd for _, bd in _loop(W, F, full=True)] == ["mobile", "1226"]
    assert not W.S.get("sched_stale")


def test_check_now_on_the_lookup_path_needs_no_totals_load(mk):
    """The current month read on Schedule Lookup carries its totals: Check now's spare load goes to December."""
    W, F = _w(mk)
    for _ in range(4):
        _tick(W, F, step=30 * MIN)
    W.S["schedule"]["2026-12"]["read_ts"] = W.CLOCK.t - 10 * MIN  # fresh: only Check now's mark reads it
    assert [bd for _, bd in _loop(W, F, full=True)] == ["1126", "1226"]
    assert not W.S.get("sched_stale")


# ---------------------------------------------------------------- review 2: defer-mark-wake-adds-a-full-check
def test_a_trigger_mark_the_totals_put_off_waits_for_the_next_paced_check(mk):
    """The totals 2 h old take a read over a trigger's mark (his own trip in the pot, a CrewTrac mismatch...): the
    mark forces the next check's read at its normal pace. Only a refresh press (the card's 3 min wait) starts the
    next check at once, which costs one more check (its pot pages too); a trigger cost one before."""
    W, F = _mobile_after_dec(mk)
    assert W.mark_stale("2026-12", "his own trip H3913 2026-12-04 is in the open time pot") is True
    first = [bd for _, bd in _loop(W, F, rnd=random.Random(2))]
    assert first == ["mobile", "1126"], first
    assert W.WAKE_DUE["at"] == 0.0 and W.S["sched_stale"]["2026-12"]["forced"] is False
    rest = [[bd for _, bd in _loop(W, F, rnd=random.Random(3))] for _ in range(3)]
    assert rest == [["mobile", "1226"], [], []], rest
    assert not W.S.get("sched_stale")


def test_a_trigger_deferral_starts_no_extra_check_through_check(mk):
    """The same through check() (Pot month Both): 20 min after the trigger, one check every 5 to 7 min, none early."""
    W, F = _setup(mk, mobile=True)
    rnd = random.Random(6)
    for _ in range(12):
        _tick(W, F, step=5 * MIN)
    while [bd for _, bd in _tick(W, F, step=rnd.uniform(300, 420))] != ["mobile", "1226"]:
        pass
    W.CLOCK.t = W.S["sched_checked_at"] + 31 * MIN
    W.S["sched_totals"]["at"] = W.CLOCK.t - 125 * MIN
    W.S["machine"], W.S["last_check_ts"] = "idle", W.CLOCK.t - 120
    assert W.mark_stale("2026-12", "the CrewTrac check differs in December 2026") is True
    t0, loads, reads = _run(W, F, 20 / 60, seed=2)
    got = [[bd for _, bd in r] for r in reads]
    assert got == [["mobile", "1126"], ["mobile", "1226"]], got
    assert reads[1][0][0] - reads[0][0][0] >= 5 * MIN, [round((t - t0) / 60, 1) for t, _ in loads]  # not at once


# ---------------------------------------------------------------- review 2: new-guards-without-tests
def test_a_current_month_press_that_used_both_loads_hands_no_mark_on(mk):
    """(a) The November press's read: its first page fails, so the current month used both loads. December's mark (a
    refresh press too) was forced by this check: it is not handed to a check started at once (a mark never loops,
    sched_stale_force) and December is read at the next due read."""
    W, F = _mobile_settled(mk)
    ans = F.answer
    F.fl = real_fl(W, lambda u: INVALID if "BCID=002." in u else ans(u))  # a learned shape that no longer works
    W.S["sched_shape"] = "/full/mobileschedule.cgi?BCID=002.{n}&From=MainMenu"
    assert _cmd(W, json.dumps({"month": "2026-12"})) is True
    assert _cmd(W, json.dumps({"month": "2026-11"})) is True
    t_press = W.CLOCK.t
    first = [bd for _, bd in _loop(W, F, rnd=random.Random(2))]
    assert first == ["mobile", "mobile"], first
    assert W.WAKE_DUE["at"] == 0.0 and W.S["sched_stale"]["2026-12"]["forced"] is True
    assert (W.S["sched_refresh"]["month"], W.S["sched_refresh"]["state"]) == ("2026-11", "read")
    seq = _until_read(W, F)
    assert seq[-1][1] == ["mobile", "1226"] and seq[-1][0] >= 30 * MIN, seq  # the next due read
    assert W.S["sched_checked_at"] - t_press >= 30 * MIN and not W.S.get("sched_stale"), seq


def test_p5_a_carry_in_row_from_the_21st_to_the_29th_is_the_month_before():
    """(b) A December page whose rows start on the 25th (a long carry-in trip) or the 21st of November: those rows are
    November's (the anchor is the 20th, as inflt.parse_cm_month's)."""
    for d0 in (25, 21):
        trips = {date(2026, 11, d0): ("<a>H3909</a>", "SYD"), date(2026, 11, d0 + 1): ("", "-"),
                 date(2026, 11, d0 + 2): ("", "HNL"), date(2026, 12, 6): ("<a>H3913</a>", "LAS"),
                 date(2026, 12, 7): ("", "HNL")}
        s = pot.parse_schedule(_mob("Dec 2026", date(2026, 11, d0), date(2026, 12, 31), trips))
        assert s["month"] == "2026-12" and s["days"][0] == [f"2026-11-{d0}", "H3909", "SYD"], (d0, s["days"][:2])
        assert s["days"][-1][0] == "2026-12-31" and len(s["days"]) == 31 + 30 - d0 + 1, d0
        assert [(i["trip"], i["start"], i["end"]) for i in s["items"]] == [
            ("H3909", f"2026-11-{d0}", f"2026-11-{d0 + 2}"), ("H3913", "2026-12-06", "2026-12-07")], s["items"]
        assert s["totals"]["days_off"] == 31 - 2  # December's own days: never the carry-in's
    # a first row on the 20th or before is the header's month (a page that starts its own month)
    s = pot.parse_schedule(_mob("Dec 2026", date(2026, 12, 1), date(2026, 12, 31), {}))
    assert s["days"][0][0] == "2026-12-01"
