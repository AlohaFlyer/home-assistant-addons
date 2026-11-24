"""1.8.2 (Nov 23, 2026): the other months of the pilot's schedule are kept fresh, read early on his own signals, and the
schedule card has a refresh button (Ryan: "Maybe we need to add a little refresh button in the upper right corner of
my schedule if I don't think that it's right, but also maybe it should just always be right.").

The cause: Ryan's Dec 4 trip was swapped for the Dec 6 one about 00:53 to 01:03 HST; the Watcher's December read at
00:56 caught FLICA's page before the swap posted and December was read again only about 8 h later (6 h freshness, the
6 h sched_prev_at gate, the closed October taking the spare load first). Now a future month is fresh 30 min, a past
one 24 h, the spare load of a read goes to a due future month (the current month's totals first once they are an hour
old, on the mobile path), and four signals read a month early: (a) his seat gone from one of his own trips of another
month, (b) one of his own trips of another month in the open time pot, (c) a CrewTrac mismatch in another month, (d)
Check now. Each fires once per evidence and a month at most every 5 min. FLICA is never reached: a fake browser
answers with synthetic pages (made-up pairings H39xx, "Doe, Jane" 10001)."""
import calendar
import json
import logging
import os
import types

import pytest

import cards
import portal as PT
import roles
from test_fw181_pot_month import at, page
from test_release_a_flica import INVALID, _mobile, mk, real_fl  # noqa: F401

DOW = ("SU", "MO", "TU", "WE", "TH", "FR", "SA")
LISTED = ("1026", "1126", "1226")
MIN = 60
WWW = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "www")


def _lk(bd, trips, months=LISTED, credit="85.00"):
    """Tools > Schedule Lookup for the pilot's own number (inflt.parse_cm_month's layout), synthetic: trips is
    [(day, pairing, layover)], months the BlockDates FLICA lists."""
    y, m = 2000 + int(bd[2:]), int(bd[:2])
    n, dow0 = calendar.monthrange(y, m)[1], (calendar.monthrange(y, m)[0] + 1) % 7
    code = {d: (t, lay) for d, t, lay in trips}

    def task(d):
        trip, lay = code.get(f"{d:02d}", ("", ""))
        return (f'TAry[TAry.length]=new Task(1, "{DOW[(dow0 + d - 1) % 7]}", "{d:02d}", "{trip}", "{lay}", '
                f'"{y}{m:02d}{d:02d}");')
    tasks = "".join(task(d) for d in range(1, n + 1))
    opts = "".join(f'<option value="{b}"{" selected" if b == bd else ""}> M' for b in months)
    return (f'<html><script>function pair(pr){{}} {tasks}</script><select name="BlockDates">{opts}</select>'
            " DOE, JANE (Emp# 10001) Schedule Last Updated: Nov 22, 2026 13:52:55 HA<TABLE><TR><TD Colspan=2"
            " Class='left'>Block &nbsp;&nbsp;</TD>\n<TD Colspan=2 Class='right'>70.00 &nbsp;&nbsp;</TD></TR><TR><TD"
            f" Colspan=2 Class='left'>Credit &nbsp;&nbsp;</TD>\n<TD Colspan=2 Class='right'>{credit} &nbsp;&nbsp;</TD>"
            "</TR></TABLE></html>")


NOV_MOBILE = _mobile(2026, 11, 30, 0, {5: ("H3901", "LAX", 1)}).replace("<p>Block 80.00</p><p>Credit 90.00</p>", "")
DEC4, DEC6 = [("04", "H3913", "SYD")], [("06", "H3913", "SYD")]


class Flica:
    """The fake FLICA: Schedule Lookup pages from pg {bd: trips}, the mobile schedule (mobile path) or INVALID, the
    open time pots from pots {bcid: html}, pairing pages from pair."""

    def __init__(self, W, mobile=False, pg=None, pots=None):
        self.pg = {"1026": [("03", "H3905", "LAX")], "1126": [("05", "H3901", "LAX")], "1226": list(DEC4)}
        self.pg.update(pg or {})
        self.months, self.mobile, self.pots, self.pair = list(LISTED), mobile, pots or {}, "<html>pairing</html>"
        self.bad = set()  # months (bd) whose Schedule Lookup page is not a schedule
        self.fl = real_fl(W, self.answer)
        self.W = W

    def answer(self, u):
        if "cmschedules" in u:
            bd = u.split("bd=")[1][:4]
            if bd in self.bad:
                return "<html><body>Schedule Lookup: no schedule for that crew member</body></html>"
            return _lk(bd, self.pg[bd], self.months) if bd in self.pg and bd in self.months else INVALID
        if "mobileschedule" in u:
            return NOV_MOBILE if self.mobile else INVALID
        if "opentimepot" in u:
            return self.pots.get(self.W.bcid(u), INVALID)
        if "mobilepairing" in u:
            return self.pair
        return "<html><body>x</body></html>"

    def sched(self, since=0):
        """(time, bd or 'mobile') of every schedule load from index since."""
        out = []
        for t, u in self.fl.loads[since:]:
            if "cmschedules" in u:
                out.append((t, u.split("bd=")[1][:4]))
            elif "mobileschedule" in u:
                out.append((t, "mobile"))
        return out


def _w(mk, instance="", t=None, mobile=False, **kw):
    W = mk(instance, t=t or at(2026, 11, 23, 0, 0))
    W.S["own_emp"] = "10001"
    if mobile:  # the admin's learned mobile page (no Block / Credit on it: FW-0019's totals load)
        W.S["sched_shape"] = W.S["sched_shape_mobile"] = "/full/mobileschedule.cgi?BCID=001.{n}&From=MainMenu"
    else:  # the current month on Schedule Lookup itself (its page carries the totals and the month list)
        W.S["sched_shape"] = "lookup"
    return W, Flica(W, mobile=mobile, **kw)


def _tick(W, F, full=False, step=6 * MIN):
    """One check's schedule part as check() runs it (Check now's marks, a stale mark's forced read), then the next
    check's time. The schedule loads it made: [(time, bd or 'mobile')]."""
    n = len(F.fl.loads)
    if full:
        W.check_now_marks()
    stale = W.sched_stale_force()
    W.schedule_check(F.fl, force=full or stale or not W.S.get("schedule"))
    W.CLOCK.t += step
    return F.sched(n)


def _items(W, mon):
    return [(i["trip"], i["start"]) for i in (W.S.get("schedule") or {}).get(mon, {}).get("items") or []]


def _lines(caplog, start):
    return [r.getMessage() for r in caplog.records if r.getMessage().startswith(start)]


# ---------------------------------------------------------------- S1: cadence
def test_december_every_30_min_october_once_a_day_and_two_loads_a_read(mk):
    """The current month on Schedule Lookup (one load, its totals and month list on it): the spare load of every read
    goes to December, so December is read again at the first read after it turns 30 min old; the closed October is
    read once a day (it takes one read's spare load then, December waiting that one read)."""
    W, F = _w(mk)
    t0, per, every = W.CLOCK.t, [], []
    while W.CLOCK.t < t0 + 26 * 3600:
        got = _tick(W, F)
        if got:
            per.append(got)
        every += got
    assert per and max(len(r) for r in per) <= W.SCHED_TRIES_PER_READ, per
    dec = [t for t, bd in every if bd == "1226"]
    octo = [t for t, bd in every if bd == "1026"]
    gaps = [b - a for a, b in zip(dec, dec[1:])]
    assert max(gaps) <= 60 * MIN + 6 * MIN + 30, gaps  # at most one read waits (October's, once a day)
    assert sorted(gaps)[len(gaps) // 2] <= 36 * MIN + 30, gaps  # December within 30 min of going stale
    assert sum(1 for g in gaps if g > 40 * MIN) <= 2, gaps
    assert len(octo) == 2 and octo[1] - octo[0] >= 24 * 3600, octo  # once a day, never on every read
    # loads an hour: 2 a read every 30 min (the current month and December), October once a day
    day = [t for t, _ in every if t0 + 3600 <= t < t0 + 25 * 3600]
    assert len(day) <= 4 * 24 + 1, len(day)
    for h in range(1, 25):
        assert len([t for t in day if t0 + h * 3600 <= t < t0 + (h + 1) * 3600]) <= 6, h


def test_the_6_h_gate_no_longer_holds_a_due_future_month(mk):
    """A pass that got every month set sched_prev_at (the 6 h gate of 1.8.1): December is still read 30 min later;
    other_months_pending agrees with other_months_check (the 1.6.2 review's 'the spare load goes to a month')."""
    W, F = _w(mk, mobile=True)
    got = [bd for _ in range(4) for _, bd in _tick(W, F, step=30 * MIN)]
    # the totals (never loaded), December, October (never read: it takes the totals' turn), December (it waited a read)
    assert got == ["mobile", "1126", "mobile", "1226", "mobile", "1026", "mobile", "1226"], got
    W.S["sched_prev_at"], W.S["sched_prev_v"] = W.CLOCK.t, 6  # as after a pass that got every month
    assert W.other_months_pending("2026-11") is True  # December is due again (30 min) despite the gate
    W.S["sched_totals"]["at"] = W.CLOCK.t  # the totals are fresh: December takes the spare load
    got = _tick(W, F)
    assert [bd for _, bd in got] == ["mobile", "1226"], got
    assert W.other_months_pending("2026-11") is False  # nothing due now: the totals would take a spare load
    assert W.other_month_due("2026-10", "2026-11") == "fresh" and W.other_month_due("2026-12", "2026-11") == "fresh"


def test_the_read_order_future_first_then_past_and_a_failing_month_last(mk):
    W, F = _w(mk)
    bds = ("1026", "1126", "1226", "0127")
    W.S["schedule"] = {"2026-11": {"items": [], "days": [], "src": "lookup", "read_ts": W.CLOCK.t}}
    # the schedule keeps three months: with January listed the closed October is no longer read at all
    assert W.other_months_order(bds, "2026-11") == ["2026-12", "2027-01"]
    assert W.other_months_order(LISTED, "2026-11") == ["2026-12", "2026-10"]
    W.S["sched_other_fail"] = {"2026-12": {"n": 1, "next": 0}}
    assert W.other_months_order(LISTED, "2026-11") == ["2026-10", "2026-12"]  # a failing month never holds one back
    W.S["sched_stale"] = {"2026-12": {"why": "test", "at": W.CLOCK.t, "forced": False}}
    assert W.other_months_order(LISTED, "2026-11") == ["2026-12", "2026-10"]  # a month marked stale goes first


# ---------------------------------------------------------------- S2: the totals on the mobile path
def test_mobile_path_totals_an_hour_old_at_most_but_once_a_day_and_december_waits_one_read(mk):
    """53 h, so the closed October's daily read is in it twice after its first (1.8.2 review: it took December's turn
    and December went about 2 h 15 min unread once a day). Now October takes the totals' turn: December waits one read
    at most, always; the totals are an hour old at most except once a day (about 2 h, the read October took)."""
    W, F = _w(mk, mobile=True)
    t0, every, per = W.CLOCK.t, [], []
    while W.CLOCK.t < t0 + 53 * 3600:
        got = _tick(W, F)
        if got:
            per.append(got)
        every += got
    assert max(len(r) for r in per) <= 2 and all(r[0][1] == "mobile" for r in per), per
    tot = [t for t, bd in every if bd == "1126"]
    dec = [t for t, bd in every if bd == "1226"]
    octo = [t for t, bd in every if bd == "1026"]
    assert len(octo) == 3 and all(b - a >= 24 * 3600 for a, b in zip(octo, octo[1:])), octo
    dgaps = [b - a for a, b in zip(dec, dec[1:])]
    assert max(dgaps) <= 60 * MIN + 6 * MIN + 30, [round(g / 60) for g in dgaps]  # one read at most, every day
    tgaps = [b - a for a, b in zip(tot, tot[1:])]
    long = [g for g in tgaps if g > 60 * MIN + 6 * MIN + 30]
    assert len(long) == len(octo) and max(long) <= 2 * 3600 + 6 * MIN + 30, [round(g / 60) for g in tgaps]
    assert len(dec) >= 45 and len(tot) >= 45, (len(dec), len(tot))
    nov = W.S["schedule"]["2026-11"]
    assert nov["totals"]["credit"] == "85:00" and nov["totals"]["block"] == "70:00"  # always FLICA's figures
    # a read whose totals are an hour old loads them first, December (due, it has not waited a read) waiting one read
    W.S["sched_totals"]["at"] = W.CLOCK.t - 61 * MIN
    W.S["schedule"]["2026-12"]["read_ts"] = W.CLOCK.t - 40 * MIN
    W.S["sched_checked_at"] = 0
    assert [bd for _, bd in _tick(W, F)] == ["mobile", "1126"]
    # December that already waited a read goes before totals under 2 h old; totals 2 h old go before it
    W.S["sched_totals"]["at"] = W.CLOCK.t - 61 * MIN
    W.S["schedule"]["2026-12"]["read_ts"] = W.CLOCK.t - 61 * MIN
    W.S["sched_checked_at"] = 0
    assert [bd for _, bd in _tick(W, F)] == ["mobile", "1226"]
    W.S["sched_totals"]["at"] = W.CLOCK.t - 121 * MIN
    W.S["schedule"]["2026-12"]["read_ts"] = W.CLOCK.t - 61 * MIN
    W.S["sched_checked_at"] = 0
    assert [bd for _, bd in _tick(W, F)] == ["mobile", "1126"]


def test_mobile_page_with_its_own_totals_needs_no_totals_load(mk):
    W, F = _w(mk, mobile=True)
    F.mobile = True
    global NOV_MOBILE
    keep = NOV_MOBILE
    try:
        NOV_MOBILE = _mobile(2026, 11, 30, 0, {5: ("H3901", "LAX", 1)})  # Block 80.00, Credit 90.00 on the page
        got = [bd for _ in range(4) for _, bd in _tick(W, F, step=30 * MIN)]
    finally:
        NOV_MOBILE = keep
    # the month list page once (kept 6 h), then December on every read but October's first
    assert got == ["mobile", "1126", "mobile", "1226", "mobile", "1026", "mobile", "1226"], got


# ---------------------------------------------------------------- S3: early re-reads
def test_trigger_a_seat_gone_reads_december_at_once_and_never_loops(mk, caplog, monkeypatch):
    W, F = _w(mk)
    _tick(W, F, step=6 * MIN)  # November and December read
    W.OPTS["my_name"] = "Doe"
    crew = {"now": [["FO", "DOE, JANE"]]}
    monkeypatch.setattr(W, "parse_detail", lambda html: {"report": "08:00", "last_arr": "18:00", "blk": "10:00",
                                                         "credit": "12:00", "crew": crew["now"], "duties": []})
    W.own_trip_times(F.fl, full=True)
    assert W.S["own_trips"]["H3913|2026-12-04"]["seat"] == "FO" and not W.S.get("sched_stale")
    _tick(W, F)  # a check later, nothing is due
    crew["now"] = [["FO", "ROE, PAT"]]  # the swap: he is no longer on his Dec 4 trip
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        W.own_trip_times(F.fl, full=True)
    assert W.S["own_trips"]["H3913|2026-12-04"]["seat"] == ""
    assert _lines(caplog, "schedule 2026-12: read early") == [
        "schedule 2026-12: read early (own trip H3913 2026-12-04 no longer lists you (seat FO is empty))"]
    F.pg["1226"] = list(DEC6)  # FLICA's December page has the swap
    got = _tick(W, F)  # the next check: forced, at once, still two loads
    assert [bd for _, bd in got] == ["1126", "1226"] and _items(W, "2026-12") == [("H3913", "2026-12-06")]
    # the same evidence never fires again: the next re-read finds the seat empty again (no change)
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        W.own_trip_times(F.fl, full=True)
        assert _tick(W, F) == []  # no forced read: December was read 6 min ago and is fresh
    assert not _lines(caplog, "schedule 2026-12: read early")


def test_trigger_b_his_trip_in_the_pot_once_per_trip_while_the_row_stays(mk, caplog):
    W, F = _w(mk)
    _tick(W, F)
    row = {"pairing": "H3913", "start": "04Dec", "dates": "04Dec"}
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        W.pot_own_trigger({"2026-12": {"H3913|04Dec": row}}, {"2026-12"})
        W.pot_own_trigger({"2026-12": {"H3913|04Dec": row}}, {"2026-12"})  # the next check: the same row, no fire
    assert _lines(caplog, "schedule 2026-12: read early") == [
        "schedule 2026-12: read early (his H3913 2026-12-04 is in the open time pot)"]
    assert W.sched_stale_force() is True and W.sched_stale_force() is False  # one forced read for one mark
    # 1.8.2 review: the row leaves the pot read this check and comes back an hour later (pot rows are by pairing and
    # date, not seat): the trip is still on his schedule, so the evidence stays and nothing fires again
    W.pot_own_trigger({"2026-12": {}}, {"2026-12"})
    assert W.S["sched_trig"]["b"]["H3913|2026-12-04"]["fired"] is True
    W.CLOCK.t += 3600
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        W.pot_own_trigger({"2026-12": {"H3913|04Dec": row}}, {"2026-12"})
    assert W.S["sched_trig"]["b"]["H3913|2026-12-04"]["fired"] is True and not _lines(caplog, "schedule 2026-12")
    # a row of a pot not read this check keeps its evidence (no re-fire when it is read again)
    W.pot_own_trigger({}, set())
    assert "H3913|2026-12-04" in W.S["sched_trig"]["b"]
    # gone from its pot for 6 h: the row coming back is new evidence and fires again
    W.pot_own_trigger({"2026-12": {}}, {"2026-12"})
    W.CLOCK.t += 6 * 3600
    W.pot_own_trigger({"2026-12": {}}, {"2026-12"})
    assert "H3913|2026-12-04" not in W.S["sched_trig"]["b"]
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        W.pot_own_trigger({"2026-12": {"H3913|04Dec": row}}, {"2026-12"})
    assert _lines(caplog, "schedule 2026-12: read early") == [
        "schedule 2026-12: read early (his H3913 2026-12-04 is in the open time pot)"]
    # the current month's trip in the pot (his own drop request, say) is never a trigger: it is read every 30 min
    W.pot_own_trigger({"2026-11": {"H3901|05Nov": {"pairing": "H3901", "start": "05Nov"}}}, {"2026-11"})
    assert all(not k.startswith("H3901") for k in W.S["sched_trig"]["b"])


def test_trigger_c_crewtrac_mismatch_once_per_snapshot(mk, caplog, monkeypatch):
    W, F = _w(mk)
    _tick(W, F)
    snap = {"pulled_at": "2026-11-23T10:00:00Z", "trips": [], "months": {}}
    res = {"status": "ok", "age_h": 1.0, "rows": [{"trip": "H3913", "start": "2026-12-04", "ok": False, "line": "x"},
                                                  {"trip": "H3901", "start": "2026-11-05", "ok": False, "line": "y"}],
           "mismatches": 2}
    monkeypatch.setattr(W, "crewtrac_snapshot", lambda: snap)
    monkeypatch.setattr(W, "crewtrac_fw_trips", lambda: {})
    monkeypatch.setattr(W.CTR, "compare_trips", lambda s, fw, now: json.loads(json.dumps(res)))
    monkeypatch.setattr(W.CTR, "card_view", lambda s: {})
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        W.crewtrac_check()
        W.CLOCK.t += 10 * MIN
        W.crewtrac_check()  # the same snapshot: never again
    assert _lines(caplog, "schedule 2026-") == [
        "schedule 2026-12: read early (the CrewTrac check differs in December 2026)"]  # never the current month
    got = _tick(W, F)
    assert [bd for _, bd in got] == ["1126", "1226"]  # the next check reads it at once
    snap["pulled_at"] = "2026-11-24T10:00:00Z"  # Hark's next snapshot
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        W.crewtrac_check()
    assert len(_lines(caplog, "schedule 2026-12: read early")) == 1


def test_trigger_d_check_now_reads_the_future_month_too(mk, caplog):
    W, F = _w(mk, mobile=True)
    got = [bd for _ in range(4) for _, bd in _tick(W, F, step=30 * MIN)]
    assert got == ["mobile", "1126", "mobile", "1226", "mobile", "1026", "mobile", "1226"], got
    W.S["sched_totals"]["at"] = W.CLOCK.t - 90 * MIN  # even with the totals due (under 2 h)
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        got = _tick(W, F, full=True, step=4 * MIN)
    assert [bd for _, bd in got] == ["mobile", "1226"], got  # a marked month takes the spare load first
    assert _lines(caplog, "schedule 2026-12: read early") == ["schedule 2026-12: read early (Check now)"]
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        got = _tick(W, F, full=True)  # Check now again 4 min later: no second mark (5 min rule), the totals load
    assert len(_lines(caplog, "schedule 2026-12: read early")) == 1 and [bd for _, bd in got] == ["mobile", "1126"]
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        got = _tick(W, F, full=True)  # 6 min after that one: December again
    assert len(_lines(caplog, "schedule 2026-12: read early")) == 2 and [bd for _, bd in got] == ["mobile", "1226"]


def test_a_trigger_waits_5_min_for_the_same_month_and_marks_only_listed_months(mk):
    W, F = _w(mk)
    _tick(W, F)
    assert W.mark_stale("2026-12", "test") is True
    assert W.mark_stale("2026-12", "again") is False  # inside 5 min
    W.CLOCK.t += 5 * MIN
    assert W.mark_stale("2026-12", "later") is True
    assert W.mark_stale("2026-11", "current") is False  # the current month: read every 30 min anyway
    assert W.mark_stale("2027-03", "not listed") is False and W.mark_stale("bad", "x") is False


def test_a_mark_the_read_cannot_serve_forces_one_read_only(mk):
    """The current month needs both loads (its first page fails): the stale December waits for the next due read
    instead of forcing a read at every check."""
    W, F = _w(mk)
    _tick(W, F)
    W.S["sched_shape"] = "/full/mobileschedule.cgi?BCID=001.{n}&From=MainMenu"  # tried first, refused
    W.S["sched_shape_mobile"] = ""
    W.mark_stale("2026-12", "test")
    loads = [_tick(W, F) for _ in range(4)]
    assert [[bd for _, bd in r] for r in loads] == [["mobile", "1126"], [], [], []], loads
    assert "2026-12" in W.S["sched_stale"]  # still first at the next due read
    assert W.check_tokens() == W.GATE_CHECK_TOKENS  # a mark already forced asks for no schedule loads
    W.CLOCK.t += 30 * MIN
    got = _tick(W, F)
    assert [bd for _, bd in got] == ["1126", "1226"], got  # the learned Schedule Lookup page, then December
    assert "2026-12" not in W.S["sched_stale"]


# ---------------------------------------------------------------- the Nov 23 timeline, replayed
def test_nov23_a_page_that_changes_10_min_after_a_read_shows_within_30_min(mk, caplog):
    """00:56 December read before the swap posted; FLICA's page changes at 01:06; the 01:26 read shows it (it was
    about 8 h). 1.8.2 (S1, P6, T2): another month's change runs the current month's change path: one log line and
    event/schedule_changed (the trade push waits for a quiet read: test_fw182_bid_month_sched)."""
    W, F = _w(mk, t=at(2026, 11, 22, 23, 56))

    def at_(d, h, m):  # a check at that HST time
        W.CLOCK.t = max(W.CLOCK.t, at(2026, 11, d, h, m))
        return [bd for _, bd in _tick(W, F, step=0)]
    assert at_(22, 23, 56) == ["1126", "1226"]
    assert at_(23, 0, 26) == ["1126", "1026"]  # October's first read (once a day from now)
    assert at_(23, 0, 56) == ["1126", "1226"] and _items(W, "2026-12") == [("H3913", "2026-12-04")]
    for m in (2, 8):
        assert at_(23, 1, m) == []
    F.pg["1226"] = list(DEC6)  # 01:06: the swap posts on FLICA's December page
    for m in (14, 20):
        assert at_(23, 1, m) == []
    W.MQ.msgs.clear()
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        got = at_(23, 1, 26)  # 20 min after the change (it was about 8 h)
    assert got == ["1126", "1226"]
    assert _items(W, "2026-12") == [("H3913", "2026-12-06")]
    (line,) = _lines(caplog, "SCHEDULE changed")
    assert "'month': '2026-12'" in line and "'added': ['H3913 2026-12-06'], 'removed': ['H3913 2026-12-04']" in line
    assert [t for t, _ in W.MQ.msgs if "/event/" in t] == ["flight_watcher/event/schedule_changed"]
    months = W.MQ.last("flight_watcher/schedule")["months"]
    assert months["2026-12"]["items"][0]["start"] == "2026-12-06" and months["2026-12"]["read_at"]


def test_nov23_at_once_on_trigger_b_in_a_real_check(mk, caplog):
    """The full check: his Dec 4 seat enters December's open time pot (Pot month Both) at 01:03 with the swap; the
    01:08 check sees it and the 01:14 check reads December (forced, two loads)."""
    pots = {"003.152": page([("H3902", "28Nov")]), "003.153": page([("H3911", "12Dec")])}
    W, F = _w(mk, t=at(2026, 11, 23, 0, 56), pots=pots)
    for f in ("own_trip_times", "publish_working_flight", "versions_check", "uploads_check", "capture",
              "detail_probe", "pot_details", "email_check", "pickup_check", "tradeboard_check", "requests_check",
              "grid_check", "publish_finds", "publish_tickets", "enrich", "swap_scan", "drop_scan",
              "publish_near_misses"):
        setattr(W, f, lambda *a, **k: None)
    W.close_in_check = lambda *a, **k: ({}, "ok")
    W.crew_index_check = lambda *a, **k: "ok"
    W.S["pot_month"], W.S["pot_urls"] = "Both", {}

    def chk():
        n = len(F.fl.loads)
        W.RUN.update(check=True, aborted="", skipped=set())
        try:
            res = W.check(F.fl)
        finally:
            W.RUN["check"] = False
        W.CLOCK.t += 6 * MIN
        return res, F.sched(n)
    res, got = chk()  # 00:56: November and December read
    assert res == "ok" and [bd for _, bd in got] == ["1126", "1226"], (res, got)
    W.CLOCK.t += 1 * MIN  # 01:03: the swap posts; his Dec 4 seat is in December's pot
    F.pg["1226"] = list(DEC6)
    pots["003.153"] = page([("H3911", "12Dec"), ("H3913", "04Dec")])
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        res, got = chk()  # 01:03 check: no read due; the pot row marks December
        assert got == [] and _lines(caplog, "schedule 2026-12: read early") == [
            "schedule 2026-12: read early (his H3913 2026-12-04 is in the open time pot)"]
        res, got = chk()  # 01:09: December read at once
    assert [bd for _, bd in got] == ["1126", "1226"] and _items(W, "2026-12") == [("H3913", "2026-12-06")]
    for _ in range(3):  # the row stays in the pot (FLICA's page is slow to drop it): no read loop
        res, got = chk()
        assert got == [], got
    assert len(_lines(caplog, "schedule 2026-12: read early")) == 1


# ---------------------------------------------------------------- S4: the refresh command
def _cmd(W, payload, topic=None):
    W.WAKE.clear()
    W.on_message(W.MQ, None, types.SimpleNamespace(topic=topic or f"{W.T}/schedule/refresh",
                                                   payload=payload.encode()))
    return W.WAKE.is_set()


def test_refresh_marks_the_month_wakes_the_loop_and_is_rate_limited(mk, caplog):
    W, F = _w(mk)
    _tick(W, F)
    W.S["machine"], W.S["last_check_ts"] = "idle", W.CLOCK.t - 120
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        assert _cmd(W, json.dumps({"month": "2026-12"})) is True
    assert W.S["sched_stale"]["2026-12"]["why"] == "refresh button"
    rf = W.MQ.last("flight_watcher/schedule")["refresh"]
    assert rf["month"] == "2026-12" and rf["state"] == "queued"
    assert _lines(caplog, "schedule 2026-12: read early") == ["schedule 2026-12: read early (refresh button)"]
    W.CLOCK.t += 30
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        assert _cmd(W, json.dumps({"month": "2026-12"})) is False  # inside 60 s: nothing more
    assert _lines(caplog, "schedule refresh 2026-12 refused") == ["schedule refresh 2026-12 refused: just refreshed"]
    assert W.MQ.last("flight_watcher/schedule")["refresh"]["state"] == "queued"  # the press in hand stays
    got = _tick(W, F)
    assert [bd for _, bd in got] == ["1126", "1226"] and "2026-12" not in W.S["sched_stale"]
    assert W.MQ.last("flight_watcher/schedule")["refresh"]["state"] == "read"
    W.CLOCK.t += 61
    assert _cmd(W, "2026-12") is True  # the month alone works too, a minute later


def test_refresh_of_the_current_month_is_a_forced_read(mk):
    W, F = _w(mk)
    _tick(W, F)
    W.S["machine"] = "idle"
    assert _cmd(W, json.dumps({"month": "2026-11"})) is True
    got = _tick(W, F)
    assert [bd for _, bd in got][0] == "1126" and W.MQ.last("flight_watcher/schedule")["refresh"]["state"] == "read"


def test_refresh_refuses_a_month_flica_does_not_list_bad_payloads_and_a_paused_watcher(mk):
    W, F = _w(mk)
    _tick(W, F)
    W.S["machine"] = "idle"
    assert _cmd(W, json.dumps({"month": "2027-03"})) is False
    rf = W.MQ.last("flight_watcher/schedule")["refresh"]
    assert rf["state"] == "refused" and rf["why"] == "FLICA does not list March 2027"
    assert "2027-03" not in W.S.get("sched_stale", {})
    for bad in ("", "x", "2026-13", json.dumps({"month": 5}), "[1]"):
        assert _cmd(W, bad) is False
    assert not W.S.get("sched_stale")
    W.FLAGS["pause"] = True
    assert _cmd(W, json.dumps({"month": "2026-12"})) is False
    assert W.MQ.last("flight_watcher/schedule")["refresh"]["why"] == "the Watcher is paused (turn Pause off first)"
    W.FLAGS["pause"] = False
    W.S["sched_other_fail"] = {"2026-12": {"n": 1, "next": W.CLOCK.t + 3600}}
    assert _cmd(W, json.dumps({"month": "2026-12"})) is False
    assert "did not read last time; next try" in W.MQ.last("flight_watcher/schedule")["refresh"]["why"]


def test_a_second_pilots_watcher_answers_its_own_refresh_only(mk):
    W, F = _w(mk, "pilot2")
    _tick(W, F)
    W.S["machine"], W.S["last_check_ts"] = "idle", W.CLOCK.t - 120
    _cmd(W, json.dumps({"month": "2026-12"}), topic="flight_watcher/schedule/refresh")  # the admin's prefix
    assert not W.S.get("sched_stale")
    assert _cmd(W, json.dumps({"month": "2026-12"}), topic="flight_watcher_pilot2/schedule/refresh") is True
    assert "2026-12" in W.S["sched_stale"]
    assert W.MQ.last("flight_watcher_pilot2/schedule")["refresh"]["state"] == "queued"
    assert ("schedule/refresh", 0) in roles.subscriptions("pilot2")
    assert ("schedule/refresh", 0) in roles.subscriptions("")
    # never a portal command: the spool refuses it as anything else (no contract change)
    assert roles.SUBS["schedule/refresh"] == "core" and "schedule/refresh" in roles.NOT_ON_PORTAL
    assert roles.portal_sub("schedule/refresh") is None and "schedule/refresh" not in roles.PORTAL_CMDS
    assert "schedule/refresh" not in roles.PORTAL_REFUSED


def test_the_schedule_sensor_says_which_months_flica_lists_and_when_each_was_read(mk):
    W, F = _w(mk)
    _tick(W, F)
    sch = W.MQ.last("flight_watcher/schedule")
    assert sch["listed"] == ["2026-10", "2026-11", "2026-12"] and sch["refresh"] == {}
    assert sch["months"]["2026-11"]["read_at"] and sch["months"]["2026-12"]["read_at"]
    assert "read_ts" not in json.dumps(sch) and "10001" not in json.dumps(sch)  # no employee number, no internals


# ---------------------------------------------------------------- S4: the card's button in Chromium
CARD_PAGE = ("<!doctype html><html><head><meta name='viewport' content='width=device-width'><style>"
             ":root{%s}body{margin:0;background:var(--primary-background-color);color:var(--primary-text-color)}"
             "</style></head><body><script>customElements.define('ha-card', class extends HTMLElement {});"
             "window.calls = [];</script><script>%s</script></body></html>")
LIGHT = ("--primary-background-color:#fafafa;--card-background-color:#fff;--primary-text-color:#212121;"
         "--secondary-text-color:#555;--divider-color:#ccc;--primary-color:#03a9f4")
DARK = ("--primary-background-color:#111;--card-background-color:#1c1c1c;--primary-text-color:#e1e1e1;"
        "--secondary-text-color:#9b9b9b;--divider-color:#444;--primary-color:#03a9f4")
NOW = "2026-11-23T21:30:00Z"  # Nov 23 11:30 HST


def _dec():
    days = [[f"2026-12-{d:02d}", "", ""] for d in range(1, 32)]
    days[3] = ["2026-12-04", "H3913", "SYD"]
    return {"items": [{"trip": "H3913", "start": "2026-12-04", "end": "2026-12-04", "lay": "SYD"}], "days": days,
            "totals": {"credit": "85:00", "block": "70:00"}, "updated": "Nov 22, 2026 13:52:55",
            "read_at": "2026-11-23T21:00:00+00:00"}


def _states(offset=1, listed=("2026-10", "2026-11", "2026-12"), dec=None, refresh=None):
    st = lambda s, a=None: {"state": s, "attributes": a or {}, "last_updated": "2026-11-23T21:20:00+00:00",  # noqa
                            "last_changed": "2026-11-23T21:20:00+00:00"}
    return {"sensor.flight_watcher_schedule": st("", {"updated": "", "months": {"2026-12": dec or _dec()},
                                                      "listed": list(listed), "refresh": refresh or {},
                                                      "read_status": {"ok": True}}),
            "input_number.flight_watcher_month_offset": st(str(offset)),
            "sensor.flight_watcher_state": st("idle", {"role": "admin", "note": ""}),
            "sensor.flight_watcher_last_check": st("2026-11-23T21:29:00+00:00"),
            "number.flight_watcher_normal_check_every": st("6"), "number.flight_watcher_hunt_check_every": st("40"),
            "switch.flight_watcher_hunt_mode": st("off"), "switch.flight_watcher_pause": st("off")}


MOUNT = """([h, dark, tag]) => { window.calls = []; document.body.innerHTML = '';
  const c = document.createElement(tag || 'flight-watcher-schedule-card');
  c.setConfig({}); document.body.appendChild(c);
  window.card = c;
  c.hass = {states: h, themes: {darkMode: dark}, user: {is_owner: true},
            callService: (d, s, data) => { window.calls.push([d, s, data]); return Promise.resolve(); }};
  const r = c.shadowRoot, b = r.querySelector('.rfb'), hd = r.querySelector('.hd2');
  if (!b) return {none: true, rfs: !!r.querySelector('.rfs'), wide: document.documentElement.scrollWidth,
                  vw: window.innerWidth};
  const bb = b.getBoundingClientRect(), hb = hd.getBoundingClientRect();
  const ag = r.querySelector('.hd2 .ag').getBoundingClientRect();
  return {none: false, w: bb.width, h: bb.height, right: bb.right, hdRight: hb.right, top: bb.top, hdTop: hb.top,
          agTop: ag.top, agRight: ag.right, label: b.getAttribute('aria-label'), text: b.textContent.trim(),
          tag: b.tagName, wide: document.documentElement.scrollWidth, vw: window.innerWidth,
          rfs: r.querySelector('.rfs').textContent}; }"""
STATUS = "() => window.card.shadowRoot.querySelector('.rfs').textContent"


def _browser():
    sync_api = pytest.importorskip("playwright.sync_api")
    from test_cards import _chromium
    return sync_api, _chromium


def _rgb(s):
    import re
    return tuple(int(x) for x in re.findall(r"\d+", s)[:3])


def _contrast(a, b):
    def lum(c):
        v = [x / 255 for x in c]
        v = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in v]
        return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2]
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _src():
    return open(os.path.join(WWW, "flight-watcher-schedule-card.js"), encoding="utf-8").read()


def test_the_refresh_button_in_chromium_light_390_and_dark_320():
    sync_api, chromium = _browser()
    src = _src()
    out = {}
    with sync_api.sync_playwright() as p:
        b = chromium(p)
        if not b:
            pytest.skip("no Chromium for Playwright")
        try:
            for name, width, dark in (("light", 390, False), ("dark", 320, True)):
                ctx = b.new_context(viewport={"width": width, "height": 900}, timezone_id="Pacific/Honolulu",
                                    color_scheme="dark" if dark else "light")
                pg = ctx.new_page()
                pg.clock.set_fixed_time(NOW)
                pg.set_content(CARD_PAGE % (DARK if dark else LIGHT, src))
                o = pg.evaluate(f"({MOUNT})", [_states(), dark])
                # the keyboard reaches it (Tab from the Data age stamp) and Enter presses it; the focus ring shows
                pg.evaluate("window.card.shadowRoot.querySelector('.hd2 .ag[data-age]').focus()")
                pg.keyboard.press("Tab")
                ring = pg.evaluate("""() => { const b = window.card.shadowRoot.querySelector('.rfb'),
                    s = getComputedStyle(b); return [s.outlineStyle, s.outlineWidth, s.outlineColor,
                    getComputedStyle(document.body).backgroundColor,
                    window.card.shadowRoot.activeElement === b]; }""")
                pg.keyboard.press("Enter")
                o["calls"] = pg.evaluate("window.calls")
                o["after"] = pg.evaluate(STATUS)
                o["busy"] = pg.evaluate("window.card.shadowRoot.querySelector('.rfb').getAttribute('aria-busy')")
                pg.keyboard.press("Space")  # inside 60 s: Just refreshed, nothing sent
                o["again"], o["calls2"] = pg.evaluate(STATUS), pg.evaluate("window.calls.length")
                o["ring"] = ring
                pg.clock.set_fixed_time("2026-11-23T21:30:06Z")  # "Just refreshed" shows a few seconds
                pg.evaluate("window.card._rfShow()")
                o["back"] = pg.evaluate(STATUS)
                # the Watcher read December: its read time moved
                dec = _dec()
                dec["read_at"] = "2026-11-23T21:31:10+00:00"
                pg.evaluate("(h) => { window.card.hass = Object.assign({}, window.card._h, {states: h}); }",
                            _states(dec=dec))
                o["done"] = pg.evaluate(STATUS)
                o["focusKept"] = pg.evaluate(
                    "window.card.shadowRoot.activeElement === window.card.shadowRoot.querySelector('.rfb')")
                out[name] = o
                ctx.close()
        finally:
            b.close()
    for k, o in out.items():
        assert not o["none"] and o["tag"] == "BUTTON" and o["text"] == "↻", (k, o)
        assert o["label"] == "Refresh December 2026 from FLICA", (k, o)
        assert o["w"] >= 44 and o["h"] >= 44, (k, o)  # a 44 px target on a phone
        assert o["wide"] <= o["vw"] and o["right"] <= o["vw"], (k, o)  # no horizontal scroll
        assert abs(o["right"] - o["hdRight"]) <= 1 and abs(o["top"] - o["hdTop"]) <= 1, (k, o)  # upper right
        assert o["agRight"] <= o["right"] - o["w"] + 1, (k, o)  # next to Data age, at its right
        style, width, color, bg, focused = o["ring"]
        assert focused and style == "solid" and width == "3px", (k, o["ring"])
        assert _contrast(_rgb(color), _rgb(bg)) >= 3, (k, o["ring"])
        assert o["calls"] == [["mqtt", "publish", {"topic": "flight_watcher/schedule/refresh",
                                                   "payload": json.dumps({"month": "2026-12"}).replace(" ", "")}]]
        assert o["after"] == "Refreshing…" and o["busy"] == "true", (k, o)
        assert o["again"] == "Just refreshed" and o["calls2"] == 1 and o["back"] == "Refreshing\u2026", (k, o)
        assert o["done"].startswith("Refreshed: ") and "FLICA updated Nov 22, 2026 13:52:55" in o["done"], (k, o)
        assert "read 11:31:10 HST" in o["done"] and o["focusKept"], (k, o)
    assert _rgb(out["light"]["ring"][2]) == (21, 101, 192) and _rgb(out["dark"]["ring"][2]) == (144, 202, 249)


def test_the_card_refuses_an_unlisted_month_and_says_why_it_was_not_refreshed():
    sync_api, chromium = _browser()
    src = _src()
    with sync_api.sync_playwright() as p:
        b = chromium(p)
        if not b:
            pytest.skip("no Chromium for Playwright")
        try:
            pg = b.new_page(viewport={"width": 390, "height": 900})
            pg.clock.set_fixed_time(NOW)
            pg.set_content(CARD_PAGE % (LIGHT, src))
            pg.evaluate(f"({MOUNT})", [_states(offset=2), False])  # January 2027: FLICA does not list it yet
            pg.evaluate("window.card.shadowRoot.querySelector('.rfb').click()")
            jan = [pg.evaluate(STATUS), pg.evaluate("window.calls.length"),
                   pg.evaluate("window.card.shadowRoot.querySelector('.rfb').getAttribute('aria-label')")]
            # December: the Watcher refuses (paused)
            pg.evaluate(f"({MOUNT})", [_states(), False])
            pg.evaluate("window.card.shadowRoot.querySelector('.rfb').click()")
            pg.evaluate("(h) => { window.card.hass = Object.assign({}, window.card._h, {states: h}); }",
                        _states(refresh={"month": "2026-12", "state": "refused", "at": "2026-11-23T21:30:01+00:00",
                                         "why": "the Watcher is paused (turn Pause off first)"}))
            paused = pg.evaluate(STATUS)
            # no read in 3 min: the read status's reason, or that no read came
            pg.evaluate(f"({MOUNT})", [_states(), False])
            pg.evaluate("window.card.shadowRoot.querySelector('.rfb').click()")
            first = pg.evaluate(STATUS)
            pg.clock.set_fixed_time("2026-11-23T21:33:01Z")
            pg.evaluate("window.card._rfShow()")
            late = [pg.evaluate(STATUS), pg.evaluate(
                "window.card.shadowRoot.querySelector('.rfs').classList.contains('bad')")]
        finally:
            b.close()
    assert jan == ["Not refreshed: FLICA does not list January 2027", 0, "Refresh January 2027 from FLICA"]
    assert paused == "Not refreshed: the Watcher is paused (turn Pause off first)"
    assert first == "Refreshing…" and late == ["Not refreshed: no new read from FLICA in 3 min", True]


def test_the_button_is_not_on_the_portal_and_a_pilots_copy_uses_his_prefix():
    sync_api, chromium = _browser()
    built = cards.build("9.9.9", ["pilot2"])
    pilot = built["flight-watcher-schedule-card-pilot2.js"]
    portal = PT.portal_card(pilot)
    assert "const FW_PORTAL = true;" in portal
    assert "const FW_PORTAL = false;" in built["flight-watcher-schedule-card.js"]
    assert '"flight_watcher_pilot2/schedule/refresh"' in pilot
    pst = json.loads(json.dumps(_states()).replace("flight_watcher_", "flight_watcher_pilot2_"))
    with sync_api.sync_playwright() as p:
        b = chromium(p)
        if not b:
            pytest.skip("no Chromium for Playwright")
        try:
            pg = b.new_page(viewport={"width": 390, "height": 900})
            pg.clock.set_fixed_time(NOW)
            pg.set_content(CARD_PAGE % (LIGHT, portal))
            tag = "flight-watcher-schedule-card-pilot2"
            on_portal = pg.evaluate(f"({MOUNT})", [pst, False, tag])
            pg = b.new_page(viewport={"width": 390, "height": 900})  # a new window: its own element registry
            pg.clock.set_fixed_time(NOW)
            pg.set_content(CARD_PAGE % (LIGHT, pilot))
            ha = pg.evaluate(f"({MOUNT})", [pst, False, tag])
            pg.evaluate("window.card.shadowRoot.querySelector('.rfb').click()")
            calls = pg.evaluate("window.calls")
        finally:
            b.close()
    assert on_portal["none"] and not on_portal["rfs"] and on_portal["wide"] <= on_portal["vw"]
    assert not ha["none"] and ha["label"] == "Refresh December 2026 from FLICA"
    assert calls == [["mqtt", "publish", {"topic": "flight_watcher_pilot2/schedule/refresh",
                                          "payload": '{"month":"2026-12"}'}]]


# ---------------------------------------------------------------- the release
def test_version_changelog_readme_and_no_em_dash():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg = open(os.path.join(here, "config.yaml"), encoding="utf-8").read()
    assert 'version: "1.8.2"' in cfg
    assert 'VERSION = "1.8.2"' in open(os.path.join(here, "watcher.py"), encoding="utf-8").read()
    log = open(os.path.join(here, "CHANGELOG.md"), encoding="utf-8").read()
    assert log.startswith("# Changelog\n\n## 1.8.2\n") and "\n## 1.8.1\n" in log
    top = log.split("\n## 1.8.1\n")[0]
    for word in ("00:56", "01:03", "01:15", "30 min", "24 h", "Check now", "CrewTrac", "refresh", "loads",
                 "Maybe we need to add a little refresh button"):
        assert word in top, word
    readme = open(os.path.join(here, "README.md"), encoding="utf-8").read()
    assert "## Schedule months kept fresh (1.8.2)" in readme
    for name in ("watcher.py", "roles.py", "CHANGELOG.md", "README.md", "www/flight-watcher-schedule-card.js",
                 "tests/test_fw182_sched_fresh.py"):
        text = open(os.path.join(here, name), encoding="utf-8").read()
        assert chr(0x2014) not in text, name


# ---------------------------------------------------------------- 1.8.2 review: loads, triggers, the refresh command
def _checker(mk, pots=None, t=None, instance=""):
    """A Watcher whose check() runs for real (the pot pages, the schedule read and the triggers) with the slow reads
    around them stubbed; chk() runs one check and moves the clock 6 min (step), returning the schedule loads."""
    pots = pots if pots is not None else {"003.152": page([("H3902", "28Nov")]), "003.153": page([("H3911", "12Dec")])}
    W, F = _w(mk, instance, t=t or at(2026, 11, 23, 0, 56), pots=pots)
    for f in ("own_trip_times", "publish_working_flight", "versions_check", "uploads_check", "capture",
              "detail_probe", "pot_details", "email_check", "pickup_check", "tradeboard_check", "requests_check",
              "grid_check", "publish_finds", "publish_tickets", "enrich", "swap_scan", "drop_scan",
              "publish_near_misses"):
        setattr(W, f, lambda *a, **k: None)
    W.close_in_check = lambda *a, **k: ({}, "ok")
    W.crew_index_check = lambda *a, **k: "ok"
    W.S["pot_month"], W.S["pot_urls"] = "Both", {}

    def chk(step=6 * MIN):
        n = len(F.fl.loads)
        W.RUN.update(check=True, aborted="", skipped=set())
        try:
            assert W.check(F.fl) == "ok"
        finally:
            W.RUN["check"] = False
        W.CLOCK.t += step
        return [bd for _, bd in F.sched(n)]
    return W, F, chk


def test_review_check_now_in_a_real_check_reads_december_too(mk, caplog):
    """S3 (d) through check() itself (the review: nothing tested the call in check()). Without the Check now mark the
    read's spare load would go to October (never read yet)."""
    W, F, chk = _checker(mk)
    assert chk() == ["1126", "1226"]  # 00:56
    W.FLAGS["full"] = True  # Check now at 01:02: December was read 6 min ago
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        got = chk()
    assert got == ["1126", "1226"], got
    assert _lines(caplog, "schedule 2026-12: read early") == ["schedule 2026-12: read early (Check now)"]
    assert not W.FLAGS.get("full") and not W.S.get("sched_stale")


def test_review_a_failing_totals_page_takes_its_turn_and_december_is_still_read(mk):
    """The review: a totals page that failed never stamped sched_totals, so on the mobile path every read loaded it
    again and December was never read. Now a failed load counts as the totals' turn (once an hour)."""
    W, F = _w(mk, mobile=True)
    for _ in range(6):
        _tick(W, F, step=30 * MIN)  # the totals, December and October in hand
    F.bad.add("1126")  # Schedule Lookup no longer gives November's page; December's still reads
    t0, every = W.CLOCK.t, []
    while W.CLOCK.t < t0 + 5 * 3600:
        every += _tick(W, F)
    dec = [t for t, bd in every if bd == "1226"]
    tot = [t for t, bd in every if bd == "1126"]
    assert len(dec) >= 4 and max(b - a for a, b in zip(dec, dec[1:])) <= 60 * MIN + 6 * MIN + 30, len(dec)
    assert 4 <= len(tot) <= 6 and min(b - a for a, b in zip(tot, tot[1:])) >= 60 * MIN, len(tot)  # once an hour
    assert W.S["sched_totals"]["ok"] is False
    assert W.S["schedule"]["2026-11"]["totals"]["credit"] == "85:00"  # the figures last stored stay


def test_review_marks_that_keep_coming_never_hold_the_totals_for_ever(mk):
    """The review: any mark beat stale totals, so marks that kept coming (Check now, the refresh button, a recurring
    trigger) kept the mobile path's Block / Credit unloaded for hours. Now a mark goes first while the totals are
    under 2 h old (or when the read before did not load that month); else the totals load and the mark forces the
    next check's read."""
    W, F = _w(mk, mobile=True)
    for _ in range(4):
        _tick(W, F, step=30 * MIN)
    t0, per = W.CLOCK.t, []
    while W.CLOCK.t < t0 + 5 * 3600:
        W.mark_stale("2026-12", "test")  # a mark at every check (6 min apart)
        per.append([bd for _, bd in _tick(W, F)])
    assert all(len(r) <= 2 for r in per), per
    tot = [i for i, r in enumerate(per) if r == ["mobile", "1126"]]
    assert len(tot) >= 2, per
    assert all(b - a <= 21 for a, b in zip(tot, tot[1:])), tot  # every 2 h at most (20 checks of 6 min, and one)
    assert all(per[i + 1] == ["mobile", "1226"] for i in tot if i + 1 < len(per)), per  # the mark at the next check
    assert sum(1 for r in per if r == ["mobile", "1226"]) >= len(per) - len(tot) - 1


def test_review_a_mark_beats_totals_under_2_h_or_when_the_month_was_not_read_the_read_before(mk):
    W, F = _w(mk, mobile=True)
    for _ in range(4):
        _tick(W, F, step=30 * MIN)  # the read before this one loaded December
    W.S["sched_totals"]["at"] = W.CLOCK.t - 121 * MIN
    W.mark_stale("2026-12", "test")
    assert [bd for _, bd in _tick(W, F)] == ["mobile", "1126"]  # the totals first: December was just read
    assert W.S["sched_stale"]["2026-12"]["forced"] is False  # ... and the mark forces the next check's read
    assert [bd for _, bd in _tick(W, F)] == ["mobile", "1226"] and not W.S["sched_stale"]
    assert _tick(W, F) == []  # one more read, never a loop
    # December not read by the read before (its last read was an earlier one): the mark goes first even with the
    # totals over 2 h old
    W.CLOCK.t += 30 * MIN
    _tick(W, F)
    W.S["schedule"]["2026-12"]["read_ts"] = W.S["sched_checked_at"] - 10 * MIN
    W.S["sched_totals"]["at"] = W.CLOCK.t - 121 * MIN
    W.mark_stale("2026-12", "test")
    assert [bd for _, bd in _tick(W, F)] == ["mobile", "1226"]


def test_review_trigger_b_a_row_that_comes_and_goes_fires_once(mk, caplog):
    """The review: pot rows are by pairing and date, not seat, so a row that left the pot read and came back fired a
    forced read each time (30 in 6 h). The evidence now stays while the trip is on his schedule."""
    W, F = _w(mk)
    _tick(W, F)
    row = {"pairing": "H3913", "start": "04Dec", "dates": "04Dec"}
    per = []
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        for i in range(60):  # 6 h of checks, the row in December's pot on every other one
            W.pot_own_trigger({"2026-12": {"H3913|04Dec": row} if i % 2 == 0 else {}}, {"2026-12"})
            per.append(len(_tick(W, F)))
    assert len(_lines(caplog, "schedule 2026-12: read early")) == 1
    assert sum(per) <= 2 * 13, per  # the read every 30 min (two loads) and the one forced read, no more


def test_review_trigger_b_ends_when_the_trip_leaves_his_schedule(mk, caplog):
    W, F = _w(mk)
    _tick(W, F)
    row = {"pairing": "H3913", "start": "04Dec", "dates": "04Dec"}
    W.pot_own_trigger({"2026-12": {"H3913|04Dec": row}}, {"2026-12"})
    assert W.S["sched_trig"]["b"]["H3913|2026-12-04"]["fired"] is True
    F.pg["1226"] = list(DEC6)
    _tick(W, F)  # the forced read: the Dec 4 trip is gone from his December (he is on Dec 6 now)
    assert _items(W, "2026-12") == [("H3913", "2026-12-06")]
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        W.pot_own_trigger({"2026-12": {"H3913|04Dec": row}}, {"2026-12"})  # someone else's Dec 4 seat, not his
    assert "H3913|2026-12-04" not in W.S["sched_trig"]["b"] and not _lines(caplog, "schedule 2026-12: read early")


def test_review_two_own_trips_in_the_pot_one_forced_read(mk, caplog):
    """The review: two pieces of evidence for one month in one check forced two reads 6 min apart."""
    W, F = _w(mk, pg={"1226": [("04", "H3913", "SYD"), ("10", "H3920", "LAX")]})
    _tick(W, F)
    rows = {"H3913|04Dec": {"pairing": "H3913", "start": "04Dec"},
            "H3920|10Dec": {"pairing": "H3920", "start": "10Dec"}}
    per = []
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        for _ in range(6):  # a check every 3 min, the rows stay in the pot
            W.pot_own_trigger({"2026-12": rows}, {"2026-12"})
            per.append([bd for _, bd in _tick(W, F, step=3 * MIN)])
    assert per == [["1126", "1226"], [], [], [], [], []], per
    assert len(_lines(caplog, "schedule 2026-12: read early")) == 1
    assert all(v["fired"] for v in W.S["sched_trig"]["b"].values())


def _ct(W, monkeypatch, snap, rows, months=None):
    monkeypatch.setattr(W, "crewtrac_snapshot", lambda: snap)
    monkeypatch.setattr(W, "crewtrac_fw_trips", lambda: {})
    res = {"status": "ok", "age_h": 1.0, "rows": rows, "mismatches": sum(1 for r in rows if not r["ok"])}
    monkeypatch.setattr(W.CTR, "compare_trips", lambda s, fw, now: json.loads(json.dumps(res)))
    monkeypatch.setattr(W.CTR, "card_view", lambda s: {})
    if months is not None:  # each month's line ({month: ok}): ends with a tick when it agrees
        monkeypatch.setattr(W.CTR, "m_of", lambda v: 0 if v else None)
        monkeypatch.setattr(W.CTR, "month_line", lambda s, mk, fw: f"{mk} line " + ("✓" if months[mk] else "x"))


def test_review_a_crewtrac_mismatch_inside_the_5_min_gap_fires_later(mk, caplog, monkeypatch):
    """The review: a snapshot whose mismatch came inside the 5 min gap of the month was used up and never read the
    month (the Nov 23 failure in small). Now its evidence waits and fires once the gap is over."""
    W, F = _w(mk)
    _tick(W, F)
    W.S["machine"] = "idle"
    assert _cmd(W, json.dumps({"month": "2026-12"})) is True
    assert [bd for _, bd in _tick(W, F, step=2 * MIN)] == ["1126", "1226"]
    snap = {"pulled_at": "2026-11-23T10:00:00Z", "trips": [], "months": {}}
    _ct(W, monkeypatch, snap, [{"trip": "H3913", "start": "2026-12-04", "ok": False, "line": "x"}])
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        W.crewtrac_check()  # 2 min after the press: inside December's 5 min gap
        assert not _lines(caplog, "schedule 2026-12: read early") and not W.S["sched_stale"]
        assert W.S["sched_trig"]["c"]["2026-12"]["fired"] is False
        got = []
        for _ in range(3):  # the checks after it (each one's pot step fires pending evidence)
            W.sched_triggers_fire()
            got.append([bd for _, bd in _tick(W, F, step=2 * MIN)])
    assert _lines(caplog, "schedule 2026-12: read early") == [
        "schedule 2026-12: read early (the CrewTrac check differs in December 2026)"]
    assert ["1126", "1226"] in got and W.S["sched_trig"]["c"]["2026-12"]["fired"] is True
    # the CrewTrac poll alone (the same snapshot 10 min later) fires evidence the gap refused, too
    W.S["sched_trig"]["c"]["2026-12"]["fired"] = False
    W.S["sched_trig_at"]["2026-12"] = W.CLOCK.t - 6 * MIN
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        W.crewtrac_check()
    assert len(_lines(caplog, "schedule 2026-12: read early")) == 1
    W.sched_stale().clear()
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        W.CLOCK.t += 10 * MIN
        W.crewtrac_check()  # the same snapshot: never again
        W.sched_triggers_fire()
    assert len(_lines(caplog, "schedule 2026-12: read early")) == 1


def test_review_a_crewtrac_month_line_mismatch_reads_that_month(mk, caplog, monkeypatch):
    W, F = _w(mk)
    _tick(W, F)
    snap = {"pulled_at": "2026-11-23T11:00:00Z", "trips": [], "months": {"2026-11": {}, "2026-12": {}}}
    _ct(W, monkeypatch, snap, [{"trip": "H3913", "start": "2026-12-04", "ok": True}],
        months={"2026-11": False, "2026-12": False})
    W.CLOCK.t += 6 * MIN
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        W.crewtrac_check()
    assert _lines(caplog, "schedule 2026-") == [
        "schedule 2026-12: read early (the CrewTrac check differs in December 2026)"]  # never the current month
    assert W.MQ.last("flight_watcher/crewtrac_check")["status"] == "mismatch"


def test_review_check_tokens_counts_only_a_mark_that_forces_a_read(mk):
    """The review: check_tokens added the read's two loads for any mark, also one already forced or for a month
    backing off (up to 6 h), so a pilot's check waited for two tokens it never used."""
    W, F = _w(mk)
    F.pg.pop("1226")  # December's page is not a schedule: it backs off 1 h
    _tick(W, F)
    assert W.other_month_due("2026-12", "2026-11") == "wait"
    base = W.check_tokens()
    W.mark_stale("2026-12", "test")
    before = json.dumps(W.S["sched_stale"], sort_keys=True)
    assert W.sched_stale_force(dry=True) is False and W.check_tokens() == base == W.GATE_CHECK_TOKENS
    assert json.dumps(W.S["sched_stale"], sort_keys=True) == before  # a dry ask changes nothing
    assert W.sched_stale_force() is False and _tick(W, F) == []  # a month backing off forces no read
    W.CLOCK.t += 61 * MIN
    F.pg["1226"] = list(DEC4)
    assert W.sched_stale_force(dry=True) is True  # the back-off is over: the mark forces the read now


def test_review_check_now_with_two_future_months_reads_the_second_at_the_next_check(mk, caplog):
    W, F = _w(mk, pg={"0127": [("05", "H3920", "LAX")]})
    F.months = ["1126", "1226", "0127"]
    _tick(W, F, step=30 * MIN)
    _tick(W, F, step=30 * MIN)
    got = [[bd for _, bd in _tick(W, F, full=True, step=1 * MIN)]]  # Check now
    got += [[bd for _, bd in _tick(W, F, step=1 * MIN)] for _ in range(2)]
    assert got == [["1126", "1226"], ["1126", "0127"], []], got
    assert not W.S["sched_stale"]


def test_review_refresh_of_a_month_flica_lists_but_the_schedule_does_not_keep(mk):
    """The review: with October to January listed the schedule keeps the latest three months, so a refresh of October
    was accepted, woke the loop and was dropped without a note ('Refreshing...' then the generic 3 min note)."""
    W, F = _w(mk, pg={"0127": [("05", "H3920", "LAX")]})
    F.months = ["1026", "1126", "1226", "0127"]
    _tick(W, F)
    W.S["machine"] = "idle"
    assert _cmd(W, json.dumps({"month": "2026-10"})) is False
    rf = W.MQ.last("flight_watcher/schedule")["refresh"]
    assert rf["state"] == "refused"
    assert rf["why"] == "Flight Watcher keeps only the latest three months (October 2026 is older)"
    assert not W.S["sched_stale"] and W.mark_stale("2026-10", "a trigger") is False


def test_review_a_queued_refresh_whose_month_is_no_longer_kept_says_why(mk):
    W, F = _w(mk)
    _tick(W, F)
    W.S["machine"] = "idle"
    W.CLOCK.t += 25 * 3600  # October is due again (once a day)
    assert _cmd(W, json.dumps({"month": "2026-10"})) is True
    F.months, F.pg["0127"] = ["1026", "1126", "1226", "0127"], [("05", "H3920", "LAX")]  # January is published
    assert "1026" not in [bd for _, bd in _tick(W, F)]
    rf = W.MQ.last("flight_watcher/schedule")["refresh"]
    assert rf["state"] == "failed" and "keeps only the latest three months" in rf["why"], rf


def test_review_a_refresh_whose_read_fails_says_why(mk):
    W, F = _w(mk)
    _tick(W, F)
    W.S["machine"] = "idle"
    F.bad.add("1226")  # December's page is not a schedule
    assert _cmd(W, json.dumps({"month": "2026-12"})) is True
    _tick(W, F)
    rf = W.MQ.last("flight_watcher/schedule")["refresh"]
    assert rf["state"] == "failed" and rf["why"].startswith("FLICA's December 2026 page was "), rf
    # the current month: every schedule page fails (schedule_failed)
    W.CLOCK.t += 61
    F.bad.add("1126")
    assert _cmd(W, json.dumps({"month": "2026-11"})) is True
    _tick(W, F)
    rf = W.MQ.last("flight_watcher/schedule")["refresh"]
    assert rf["month"] == "2026-11" and rf["state"] == "failed" and rf["why"], rf


def test_review_the_current_months_mark_is_served_by_its_read(mk):
    W, F = _w(mk)
    _tick(W, F)
    W.S["machine"] = "idle"
    assert _cmd(W, json.dumps({"month": "2026-11"})) is True
    assert W.sched_stale_force(dry=True) is True and W.check_tokens() > W.GATE_CHECK_TOKENS
    assert [bd for _, bd in _tick(W, F)][0] == "1126"  # forced, 6 min after the last read
    assert "2026-11" not in W.S["sched_stale"] and W.sched_stale_force(dry=True) is False
    assert _tick(W, F) == []


def test_review_a_trigger_waits_5_min_after_a_refresh_press(mk, caplog):
    W, F = _w(mk)
    _tick(W, F)
    W.S["machine"] = "idle"
    assert _cmd(W, json.dumps({"month": "2026-12"})) is True
    _tick(W, F, step=2 * MIN)  # the press's read
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        assert W.mark_stale("2026-12", "a trigger") is False  # 2 min after the press
        W.CLOCK.t += 3 * MIN
        assert W.mark_stale("2026-12", "a trigger") is True  # 5 min after it
    assert _lines(caplog, "schedule 2026-12: read early") == ["schedule 2026-12: read early (a trigger)"]


# ---------------------------------------------------------------- 1.8.2 review: the card's header in Chromium
# Home Assistant's ha-card is a block (its own :host rule); the card sits in a column narrower than the window
BLOCK_PAGE = CARD_PAGE.replace(
    "customElements.define('ha-card', class extends HTMLElement {});",
    "customElements.define('ha-card', class extends HTMLElement { constructor() { super(); "
    "this.attachShadow({mode: 'open'}).innerHTML = '<style>:host{display:block}</style><slot></slot>'; } });")
IN_COLUMN = """([h, dark, px]) => { document.body.innerHTML = '';
  const w = document.createElement('div'); w.style.width = px + 'px'; document.body.appendChild(w);
  const c = document.createElement('flight-watcher-schedule-card'); c.setConfig({}); w.appendChild(c);
  window.card = c;
  c.hass = {states: h, themes: {darkMode: dark}, user: {is_owner: true},
            callService: (d, s, data) => { window.calls.push([d, s, data]); return Promise.resolve(); }};
  const r = c.shadowRoot, B = (e) => { const b = e.getBoundingClientRect();
    return {l: b.left, t: b.top, r: b.right, b: b.bottom, h: b.height}; };
  return {hd: B(r.querySelector('.hd2')), rf: B(r.querySelector('.rfb')), ag: B(r.querySelector('.hd2 .ag')),
          lock: B(r.querySelector('.hd2 .lock')), h3: B(r.querySelector('.hd2 h3')),
          page: document.documentElement.scrollWidth}; }"""


def test_review_the_button_stays_in_the_upper_right_of_a_card_narrower_than_the_window():
    """The review: the header's layout was keyed to the window, so in a card 615 to 650 px wide in a wide window the
    button wrapped alone to the left of a second row (and sat on the second row from 480 to 610 px). Now Data age and
    the button are one box, and a card 700 px wide or less has the phone's two lines whatever the window."""
    sync_api, chromium = _browser()
    src, out = _src(), []
    with sync_api.sync_playwright() as p:
        b = chromium(p)
        if not b:
            pytest.skip("no Chromium for Playwright")
        try:
            for dark in (False, True):
                pg = b.new_page(viewport={"width": 1280, "height": 900})
                pg.clock.set_fixed_time(NOW)
                pg.set_content(BLOCK_PAGE % (DARK if dark else LIGHT, src))
                for px in (420, 480, 560, 600, 615, 630, 640, 650, 660, 700, 720, 760, 900):
                    out.append((dark, px, pg.evaluate(f"({IN_COLUMN})", [_states(), dark, px])))
                pg.close()
        finally:
            b.close()
    for dark, px, g in out:
        hd, rf, ag, lk = g["hd"], g["rf"], g["ag"], g["lock"]
        where = (dark, px, g)
        assert abs(rf["r"] - hd["r"]) <= 1, where  # at the header's right
        assert rf["t"] >= lk["t"] - 0.5 and rf["b"] <= lk["b"] + 0.5, where  # on the first line, the Lock switch's
        assert 0 <= rf["l"] - ag["r"] <= 12 and ag["t"] < rf["b"] and ag["b"] > rf["t"], where  # beside Data age
        assert g["page"] <= 1280, where
        if px <= 700:  # the phone's two lines: the month's line under the switch's
            assert g["h3"]["t"] >= lk["b"], where
        else:
            assert round(hd["h"]) == 44, where


def test_review_the_refresh_line_ends_under_the_button_on_a_wide_card():
    sync_api, chromium = _browser()
    src = _src()
    with sync_api.sync_playwright() as p:
        b = chromium(p)
        if not b:
            pytest.skip("no Chromium for Playwright")
        try:
            got = []
            for width in (1024, 1280):
                pg = b.new_page(viewport={"width": width, "height": 900})
                pg.clock.set_fixed_time(NOW)
                pg.set_content(BLOCK_PAGE % (LIGHT, src))
                pg.evaluate(f"({MOUNT})", [_states(), False])
                pg.evaluate("window.card.shadowRoot.querySelector('.rfb').click()")
                got.append(pg.evaluate("""() => { const r = window.card.shadowRoot, s = r.querySelector('.rfs'),
                    b = r.querySelector('.rfb').getBoundingClientRect(), g = document.createRange();
                    g.selectNodeContents(s); const t = g.getBoundingClientRect();
                    return [s.textContent, t.right, b.right, t.top, b.bottom]; }"""))
                pg.close()
        finally:
            b.close()
    for text, right, brt, top, bbot in got:
        assert text == "Refreshing…" and abs(right - brt) <= 2 and top >= bbot, got  # under the button
