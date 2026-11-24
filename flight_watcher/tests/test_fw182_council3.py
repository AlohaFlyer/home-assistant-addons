"""1.8.2, council loop 3 (Nov 24, 2026): the bid month edge, Nov 30 to Dec 2 HST. Hawaiian's November 2026 bid period
runs Nov 1 to Dec 1 and December's Dec 2 to 31 (the pairing files' bounds, _periods), so the Watcher's current month
and its pot months roll over at Dec 2 00:00 HST, not at Dec 1.

- R1: the Pot month select on Dec 1 (This month November 003.152, Next month December 003.153 and never January's
  003.154, Both November and December) and from Dec 2 00:00 (December, January once its pot is open, both).
- R2: a schedule read that runs across Dec 2 00:00 keeps the current month it started with; the first read after it
  takes December as current and November as a past month (fresh 24 h only now); the pot's month flips at 00:00 too.
- R3: November's daily re-read after Dec 2, with the carry-in trip (Nov 30 to Dec 2) on both pages: no event, move or
  push when nothing changed, exactly one when it did.
- R4: FLICA's whole-schedule stamp moving with nothing changed: December is read early (the stamp mark), and no
  event, move or push goes out.
- R5: a carry-in trip on both months' pages counts once: its identity, the change path, the pricing key (pairing,
  start day), the Working Flight and the FAR column, to its last day also when November's page cuts it short.

Each test drives the real code (check(), _schedule_read, the pot plan) on a fake clock with synthetic pages: made-up
pairings H39xx, "Doe, Jane" 10001, "Doe, John" 10002. FLICA is never reached."""
import json
import logging

import pytest

from test_fw181_pot_month import DEC, JAN, NOV, _check, _new, _periods, at, page
from test_fw181_pot_month import _w as _pot_w
from test_fw182_bid_month_sched import DEC_ROWS, EDGE, _changed, _days, _ev, _lkr, _mob, _rec
from test_fw182_sched_fresh import MIN, _items, _tick, _w
from test_release_a_flica import INVALID, mk, real_fl  # noqa: F401

NOV_D1 = NOV + [("H3905", "01Dec")]  # a Dec 1 trip: November's bid period, in November's pot


# ---------------------------------------------------------------- R1: the Pot month select across the edge
DEC1 = {"This month": ["003.152"], "Next month": ["003.153"], "Both": ["003.152", "003.153"]}
ONDEC1 = {"This month": ["2026-11"], "Next month": ["2026-12"], "Both": ["2026-11", "2026-12"]}


@pytest.mark.parametrize("mode", ["This month", "Next month", "Both"])
def test_r1_the_pot_select_on_dec_1_and_from_dec_2_00_00_hst(mk, mode):
    """Dec 1 (November's bid month): every check of the day reads the pages of DEC1[mode], January's 003.154 never.
    Dec 2 00:00: This month reads December (its first read a baseline), Next month tries January in place of
    December's page and reads December while January is not open, then January alone once it is; Both reads December
    and tries January. A December trip posted on Dec 2 alerts once in each mode."""
    W, fl, pages = _pot_w(mk, at(2026, 12, 1, 0, 5), mode, {"003.152": page(NOV_D1), "003.153": page(DEC)})
    _periods(W)
    got = []
    while W.CLOCK.t < at(2026, 12, 1, 23, 50):
        assert W.this_month_key() == "2026-11" and W.pot_months_of() == ONDEC1[mode], W.local_now()
        res, loads = _check(W, fl, step=1800)
        assert res == "ok", res
        got.append(loads)
    assert len(got) == 48 and all(g == DEC1[mode] for g in got), got
    # the roll-over is at Dec 2 00:00 HST to the second
    W.CLOCK.t = at(2026, 12, 2, 0, 0) - 1
    assert W.this_month_key() == "2026-11"
    W.CLOCK.t = at(2026, 12, 2, 0, 0)
    assert W.this_month_key() == "2026-12"
    assert W.pot_months_of() == (["2026-12"] if mode == "This month" else ["2026-12", "2027-01"])  # January not open
    W.CLOCK.t += 5 * 60
    after = [_check(W, fl, step=1800)[1] for _ in range(2)]
    assert _new(W) == []  # This month: December's first read (Dec 2 00:05) is its baseline, no alert
    pages["003.153"] = page(DEC + [("H3914", "24Dec")])
    after += [_check(W, fl, step=1800)[1] for _ in range(10)]
    assert _new(W) == ["H3914"]  # once (Next month, Both: December's baseline from Dec 1 carried across 00:00)
    if mode == "This month":
        assert all(g == ["003.153"] for g in after) and W.pot_months_of() == ["2026-12"], after
        return
    assert after[0] == (["003.154"] if mode == "Next month" else ["003.153", "003.154"]), after
    assert W.pot_status("2027-01") == "not open yet"
    assert all(g == ["003.153"] for g in after[1:]), after  # January waits for its try (a day)
    W.CLOCK.t += 86400  # a day later January's pot is open: read and learned, then read every check
    pages["003.154"] = page(JAN)
    later = [_check(W, fl)[1] for _ in range(3)]
    if mode == "Next month":
        assert later == [["003.154"]] * 3 and list(W.S["pot_urls"]) == ["2027-01"]
        assert W.pot_months_of() == ["2027-01"]
    else:
        assert later == [["003.153", "003.154"]] * 3 and list(W.S["pot_urls"]) == ["2026-12", "2027-01"]
        assert W.pot_months_of() == ["2026-12", "2027-01"]
    assert W.pot_learned()["2027-01"]["bcid"] == "003.154" and _new(W) == ["H3914"]  # January's first read: a baseline


# ---------------------------------------------------------------- the fake FLICA of the edge (R2 to R5)
OCT_ROWS = _days("2026-10-01", "2026-10-31")
NOV_TO_DEC2 = _days("2026-11-01", "2026-12-02")  # FLICA's November page runs to Dec 2 (its carry-out rows)
OCT_TRIPS = {"2026-10-03": ("H3904", "LAX", 2)}
MIDNIGHT = at(2026, 12, 2, 0, 0)  # Dec 2 00:00 HST: December's bid period starts


def _fl(W, F, st):
    """FLICA for the bid month edge, from st: Schedule Lookup bd=1026 / 1126 / 1226 (rows Oct; st['nov_rows'];
    st['dec_rows'], else Nov 30 to Dec 31, as FLICA's December page with a carry-in) and the mobile schedule by bid
    period number (152 November, 153 December), trips st['nov'] / st['dec'] ({ISO day: (pairing, layover, days)}),
    stamp st['up'] on every page."""
    def answer(u):
        if "cmschedules" in u:
            bd = u.split("bd=")[1][:4]
            rows, trips = {"1026": (OCT_ROWS, OCT_TRIPS), "1126": (st["nov_rows"], st["nov"]),
                           "1226": (st.get("dec_rows") or DEC_ROWS, st["dec"])}.get(bd, (None, None))
            return _lkr(bd, rows, trips, st["up"]) if rows else INVALID
        if "mobileschedule" in u:
            n = u.split("BCID=001.")[1][:3] if "BCID=001." in u else ""
            if n == "152":
                return _mob("Nov", 2026, st["nov_rows"], st["nov"], updated=st["up"])
            if n == "153":
                return _mob("Dec", 2026, st.get("dec_rows") or DEC_ROWS, st["dec"], updated=st["up"])
            return INVALID
        return F.answer(u)
    F.fl = real_fl(W, answer)


def _edge(mk, monkeypatch, t, mobile=False, own=None, nov_rows=NOV_TO_DEC2, instance=""):
    """A Watcher at t (HST) with the bid periods on file, his line H3901 Nov 5, H3907 Nov 30 to Dec 2 (on both
    months' pages) and H3913 Dec 12, and the edge's fake FLICA; (W, F, st)."""
    W, F = _w(mk, instance, t=t, mobile=mobile)
    _periods(W)
    monkeypatch.setattr(W, "ha_state", lambda e: {f"input_number.{W.T}_longevity_year": "12.0"}.get(e))
    W.S["own_trips"] = dict(own or {})
    st = {"nov_rows": nov_rows, "nov": {"2026-11-05": ("H3901", "LAX", 2), "2026-11-30": EDGE},
          "dec": {"2026-11-30": EDGE, "2026-12-12": ("H3913", "SYD", 4)}, "up": "Nov 22, 2026 13:52:55"}
    _fl(W, F, st)
    return W, F, st


def _bds(loads):
    return [bd for _, bd in loads]


def _quiet(W):
    """No schedule_changed event, no FW-0064 move and no request_decided push."""
    return not _ev(W, "schedule_changed") and not W.S.get("sched_moves") and not _ev(W, "request_decided")


# ---------------------------------------------------------------- R2: a schedule read across Dec 2 00:00 HST
@pytest.mark.parametrize("mobile", [False, True])
def test_r2_a_read_across_dec_2_00_00_keeps_its_month_and_the_next_one_rolls_over(mk, monkeypatch, mobile):
    """The read due at Dec 1 23:59:59 loads November's page (the current month) before 00:00 and its spare load after
    it: November is stored and diffed as the current month (its change is an event with its moves), the spare load is
    another month's (never December's page taken for the current one), the read status is ok. The pot's month flips
    at 00:00. The next read takes December as the current month (its first load), and November, read at 23:59:59, is a
    past month now: fresh 24 h (no load of it until then), then read once."""
    W, F, st = _edge(mk, monkeypatch, at(2026, 12, 1, 23, 0), mobile)
    for _ in range(2):  # 23:00 and 23:30: November current, December and October read as other months
        assert _tick(W, F, step=30 * MIN)
    W.CLOCK.t = MIDNIGHT - 1
    W.S["sched_checked_at"] = W.CLOCK.t - 30 * MIN  # due now, by the 30 min gap
    st["nov"] = {"2026-11-05": ("H3901", "LAX", 2), "2026-11-25": ("H3909", "SYD", 3), "2026-11-30": EDGE}
    assert W.this_month_key() == "2026-11"
    got = _tick(W, F, step=0)
    assert len(got) == 2 and got[0][0] < MIDNIGHT <= got[1][0], got  # the read ran across 00:00
    # the spare load: December read as another month (Lookup path), or November's own Block / Credit after 00:00
    # (mobile: its trips moved, so its totals load at once); never a page of December taken for the current month
    assert _bds(got) == (["mobile", "1126"] if mobile else ["1126", "1226"]), got
    if mobile:
        assert W.S["sched_totals"]["month"] == "2026-11" and W.S["sched_totals"]["ok"]
    else:
        dec = W.S["schedule"]["2026-12"]
        assert (dec["month"], dec["src"], dec["read_ts"]) == ("2026-12", "lookup", W.S["sched_checked_at"])
    assert W.S["sched_status"]["ok"] and not W.S.get("sched_other_fail"), W.S.get("sched_other_fail")
    assert ("H3909", "2026-11-25") in _items(W, "2026-11") and W.S["schedule"]["2026-11"]["month"] == "2026-11"
    assert _changed(W) == [("2026-11", [], ["H3909 2026-11-25"])]  # diffed as the current month
    if not mobile:
        assert [(m["month"], m["side"], m["trip"]) for m in W.S["sched_moves"]] == [("2026-11", "add", "H3909")]
    assert W.this_month_key() == W.sched_month() == "2026-12"  # the pot's month and the schedule's flip at 00:00
    nov_read = got[0][0]
    # the next read: December is the current month, November a past one
    W.CLOCK.t = nov_read + 30 * MIN
    first = _tick(W, F)
    assert first[0][1] == ("mobile" if mobile else "1226"), first
    if mobile:
        assert "BCID=001.153" in [u for _, u in F.fl.loads if "mobileschedule" in u][-1]
    assert W.S["schedule"]["2026-12"]["month"] == "2026-12" and W.S["sched_status"]["ok"]
    assert W.other_month_fresh_s("2026-11", "2026-12") == W.SCHED_PAST_FRESH_S
    every = list(first)
    while W.CLOCK.t < at(2026, 12, 3, 1, 30):
        r = _tick(W, F)
        assert not r or r[0][1] == ("mobile" if mobile else "1226"), r  # December first on every read
        every += r
    nov = [t for t, bd in every if bd == "1126"]  # from 00:00 November's own read (the totals are December's)
    assert len(nov) == 1 and nov_read + 24 * 3600 <= nov[0] <= nov_read + 24 * 3600 + 40 * MIN, (
        [round((t - nov_read) / 60) for t in nov])
    assert len(_changed(W)) == 1  # nothing else changed: November's daily read is no change


def test_r2_a_refresh_press_whose_read_fails_after_00_00_is_answered_for_its_month(mk, monkeypatch):
    """Dec 1 23:59:59 Ryan presses refresh on November (still the current month). The forced read's first page fails
    before 00:00 and its second try fails after it: the press is answered for November (failed, with why), never left
    'queued' because the month changed while the read ran."""
    W, F, st = _edge(mk, monkeypatch, at(2026, 12, 1, 23, 0))
    _tick(W, F, step=30 * MIN)
    W.CLOCK.t, W.S["machine"] = MIDNIGHT - 1, "idle"
    W.schedule_refresh_cmd(json.dumps({"month": "2026-11"}))
    assert (W.S["sched_refresh"]["month"], W.S["sched_refresh"]["state"]) == ("2026-11", "queued")
    st["nov_rows"] = []  # FLICA gives no November schedule (every page of the read fails)
    got = _tick(W, F, step=0)
    assert _bds(got) == ["1126", "mobile"] and got[0][0] < MIDNIGHT <= got[1][0], got
    assert not W.S["sched_status"]["ok"] and W.sched_month() == "2026-12"
    rf = W.S["sched_refresh"]
    assert (rf["month"], rf["state"]) == ("2026-11", "failed") and rf["why"], rf
    assert W.MQ.last(f"{W.T}/schedule")["refresh"]["state"] == "failed"


# ---------------------------------------------------------------- R3: November's daily re-read after Dec 2
def _until(W, F, t):
    """Checks until the clock passes t (HST epoch); the schedule loads [(time, bd or 'mobile')]."""
    out = []
    while W.CLOCK.t < t:
        out += _tick(W, F)
    return out


OWN = {"H3901|2026-11-05": _rec("12:00", "10:00"), "H3907|2026-11-30": _rec("17:35", "15:00"),
       "H3913|2026-12-12": _rec("20:00", "17:00")}


@pytest.mark.parametrize("mobile", [False, True])
def test_r3_novembers_daily_reread_after_dec_2_is_quiet_or_one_change(mk, monkeypatch, mobile):
    """Dec 1 20:00 to Dec 3 03:00 with H3907 (Nov 30 to Dec 2) on November's and December's pages and nothing
    changed: November's daily read after Dec 2 runs and sends no schedule_changed, no move and no push. Then (a) H3907
    is traded for H3920 Dec 20 (both pages change): one event (December's, read first) and one push; November's next
    daily read, which sees H3907 gone too, adds neither. (b) A change on November's page alone (H3901 Nov 5 moved to
    Nov 6), seen at its daily read: one event and one push."""
    W, F, st = _edge(mk, monkeypatch, at(2026, 12, 1, 20, 0), mobile, OWN)
    before = _until(W, F, MIDNIGHT)
    assert "1126" in _bds(before) and "1226" in _bds(before)
    after = _until(W, F, at(2026, 12, 3, 3, 0))
    nov = [t for t, bd in after if bd == "1126"]
    assert len(nov) == 1 and nov[0] >= at(2026, 12, 2, 23, 0), [W.local_now()] + nov  # its daily read, once
    assert ("H3907", "2026-11-30") in _items(W, "2026-11") and ("H3907", "2026-11-30") in _items(W, "2026-12")
    assert _quiet(W), (_changed(W), W.S.get("sched_moves"), _ev(W, "request_decided"))
    # (a) the carry-in trip traded for a December one: both pages change
    W.S["own_trips"]["H3920|2026-12-20"] = _rec("21:00", "18:00")
    st.update(nov={"2026-11-05": ("H3901", "LAX", 2)}, dec={"2026-12-12": ("H3913", "SYD", 4),
                                                             "2026-12-20": ("H3920", "SYD", 3)},
              up="Dec 3, 2026 02:50:00")
    t_a = W.CLOCK.t
    after = _until(W, F, at(2026, 12, 4, 3, 0))
    assert [t for t, bd in after if bd == "1126" and t > t_a]  # November read again after the change
    assert _changed(W) == [("2026-12", ["H3907 2026-11-30"], ["H3920 2026-12-20"])]
    (ev,) = _ev(W, "request_decided")
    assert ev["detail"] == "gave H3907 30NOV; took H3920 20DEC (seen on the FLICA schedule; no request on file)"
    assert sorted((m["side"], m["trip"], m["state"]) for m in W.S["sched_moves"]) == [
        ("add", "H3920", "pushed"), ("drop", "H3907", "pushed")]
    assert ("H3907", "2026-11-30") not in _items(W, "2026-11")
    # (b) November's page alone changes (its bid period is over): seen at its daily read
    W.S["own_trips"]["H3902|2026-11-06"] = _rec("13:00", "11:00")
    st.update(nov={"2026-11-06": ("H3902", "LAX", 2)}, up="Dec 4, 2026 02:50:00")
    t_b = W.CLOCK.t
    after = _until(W, F, at(2026, 12, 5, 3, 0))
    nov = [t for t, bd in after if bd == "1126"]
    assert len(nov) == 1 and nov[0] > t_b, nov
    assert _changed(W)[1:] == [("2026-11", ["H3901 2026-11-05"], ["H3902 2026-11-06"])]
    assert [e["detail"] for e in _ev(W, "request_decided")][1:] == [
        "gave H3901 05NOV; took H3902 06NOV (seen on the FLICA schedule; no request on file)"]


# ---------------------------------------------------------------- R4: the stamp moves, nothing changed
def _next_read(W, F, limit=3600):
    """Checks until one reads the schedule; its loads."""
    t0 = W.CLOCK.t
    while W.CLOCK.t < t0 + limit:
        got = _tick(W, F)
        if got:
            return got
    return []


@pytest.mark.parametrize("mobile", [False, True])
def test_r4_the_stamp_moving_with_nothing_changed_reads_december_early_and_sends_nothing(mk, monkeypatch, caplog,
                                                                                         mobile):
    """Dec 1 (November current, December a later month): FLICA's whole-schedule stamp moves and no month changed.
    December was read at the read before and October is late, so that read's spare load was October's: the stamp's
    mark gives it to December (read early), October is read at the next read, and no schedule_changed event, move or
    push goes out (then or in the 4 h after); one stamp change is one early read."""
    W, F, st = _edge(mk, monkeypatch, at(2026, 12, 1, 8, 0), mobile, OWN)
    _until(W, F, at(2026, 12, 1, 12, 0))
    assert {"2026-10", "2026-11", "2026-12"} <= set(W.S["schedule"]) and _quiet(W)
    W.S["schedule"]["2026-12"]["read_ts"] = W.S["sched_checked_at"]  # read at the read before
    W.S["schedule"]["2026-10"]["read_ts"] -= 25 * 3600  # late: the next read's spare load would be October's
    W.S["sched_totals"] = {"month": "2026-11", "at": W.S["sched_checked_at"], "ok": True}  # mobile: totals fresh
    assert W.next_other_month("2026-11") == ("2026-10", "late")
    st["up"] = "Dec 1, 2026 12:20:00"  # FLICA's stamp moves; every month's trips stay as they were
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        got = _next_read(W, F)
        assert _bds(got) == ["mobile" if mobile else "1126", "1226"], got
        assert W.S["schedule"]["2026-12"]["cur_stamp"] == st["up"] and "2026-12" not in W.sched_stale()
        assert _bds(_next_read(W, F)) == ["mobile" if mobile else "1126", "1026"]  # October on its own clock
        _until(W, F, W.CLOCK.t + 4 * 3600)
    assert [r.getMessage() for r in caplog.records if "read early" in r.getMessage()] == [
        "schedule 2026-12: read early (FLICA's schedule stamp moved)"]  # once for one stamp change
    assert _quiet(W), (_changed(W), W.S.get("sched_moves"), _ev(W, "request_decided"))


# ---------------------------------------------------------------- R5: a carry-in trip on both pages counts once
# H3907 Nov 30 to Dec 2: November's page (to Dec 2) and December's (from Nov 30) both show all of it. H3908 Nov 29 to
# Dec 3: November's page ends before it comes home (its copy there is cut short), December's starts Nov 29.
CARRY = {"H3907": ("2026-11-30", 3, "2026-12-02"), "H3908": ("2026-11-29", 5, "2026-12-03")}


def _carry(mk, monkeypatch, trip, mobile=False, own=None):
    start, n, end = CARRY[trip]
    W, F, st = _edge(mk, monkeypatch, at(2026, 11, 23, 0, 0), mobile, own)
    st.update(nov={"2026-11-05": ("H3901", "LAX", 2), start: (trip, "KIX", n)},
              dec={start: (trip, "KIX", n), "2026-12-12": ("H3913", "SYD", 4)}, dec_rows=_days(start, "2026-12-31"))
    _until(W, F, at(2026, 11, 23, 2, 0))
    assert (trip, start) in _items(W, "2026-11") and (trip, start) in _items(W, "2026-12") and _quiet(W)
    return W, F, st, start, end


def _ddmon(iso):
    return f"{iso[8:]}{('Nov', 'Dec')[iso[5:7] == '12']}"


@pytest.mark.parametrize("trip", ["H3907", "H3908"])
def test_r5_a_carry_in_trip_counts_once_in_the_far_column_and_the_working_flight(mk, monkeypatch, trip):
    """The FAR column of a pickup on the carry-in's last day sees the trip once, to its last day (a Conflict), and
    the Working Flight has it once: on Dec 1 (no legs read yet) it is the trip he is on, its legs read the one leg
    list ('2 of 2')."""
    start, n = CARRY[trip][:2]
    W, F, st, start, end = _carry(mk, monkeypatch, trip, own={f"{trip}|{start}": _rec("17:35", "15:00")})
    assert W.S["schedule"]["2026-12"]["days"][0][0] == start and W.S["schedule"]["2026-11"]["days"][-1][0] == \
        "2026-12-02"
    ev = {"pairing": "H3990", "start": _ddmon(end), "end": _ddmon(end), "report": "09:00", "arrive": "15:00",
          "blk": "5:00"}
    (new, mine), why = W.far_trips(ev)
    assert not why
    got = [t for t in mine if t["label"].startswith(f"{trip} ")]
    assert len(got) == 1 and got[0]["release"].date().isoformat() == end, [(t["label"], t["release"]) for t in got]
    assert W.far_screen(ev)["far"].startswith("Conflict"), W.far_screen(ev)
    now = W.datetime(2026, 12, 1, 12, 0, tzinfo=W.HST)
    W.publish_working_flight(now=now, force=True)
    wf = W.MQ.last(f"{W.T}/working_flight")
    assert wf["attributes"]["next"] == f"{trip} KIX {start}", wf  # the trip he is on, not H3913
    W.S["own_trips"][f"{trip}|{start}"]["legs"] = [
        {"flt": "9001", "frm": "HNL", "to": "KIX", "dep": 600, "arr": 1140},
        {"flt": "9002", "frm": "KIX", "to": "HNL", "dep": (n - 1) * 1440 + 600, "arr": (n - 1) * 1440 + 1080}]
    W.publish_working_flight(now=now, force=True)
    wf = W.MQ.last(f"{W.T}/working_flight")
    assert (wf["attributes"]["pairing"], wf["attributes"]["leg"], wf["attributes"]["date"]) == (trip, "2 of 2", end)


@pytest.mark.parametrize("mobile", [False, True])
@pytest.mark.parametrize("trip", ["H3907", "H3908"])
def test_r5_a_carry_in_trip_traded_is_one_change_one_move_a_leg_and_priced_once(mk, monkeypatch, trip, mobile):
    """The carry-in given for H3909 Nov 25: one schedule_changed (November's; December's page lost only its carried
    rows, which November's page reported), one move a leg, one push whose pay has the given trip once, keyed by its
    pairing and start day (its own trip record: 17:35 -> 21:00, +3:25)."""
    start = CARRY[trip][0]
    own = {f"{trip}|{start}": _rec("17:35", "15:00"), "H3909|2026-11-25": _rec("21:00", "18:00")}
    W, F, st, start, end = _carry(mk, monkeypatch, trip, mobile, own)
    st.update(nov={"2026-11-05": ("H3901", "LAX", 2), "2026-11-25": ("H3909", "SYD", 3)},
              dec={"2026-12-12": ("H3913", "SYD", 4)}, up="Nov 23, 2026 02:10:00")
    _until(W, F, W.CLOCK.t + 4 * 3600)
    (ev,) = _ev(W, "request_decided")
    assert ev["detail"] == (f"gave {trip} {_ddmon(start).upper()}; took H3909 25NOV (seen on the FLICA schedule; no "
                            "request on file)")
    assert [(x["trip"], x["side"]) for x in ev["legs"]] == [(trip, "drop"), ("H3909", "add")]
    assert _changed(W) == [("2026-11", [f"{trip} {start}"], ["H3909 2026-11-25"])]
    assert sorted((m["side"], m["trip"], m["start"], m["state"]) for m in W.S["sched_moves"]) == [
        ("add", "H3909", "2026-11-25", "pushed"), ("drop", trip, start, "pushed")]
    assert W.pay_settings()[0] and ev["pay"]["credit_delta"] == "+3:25", ev["pay"]
    assert [(p["trip"], p["start"], p["side"]) for p in ev["pay"]["parts"]] == [(trip, start, "drop"),
                                                                              ("H3909", "2026-11-25", "add")]
    assert (trip, start) not in _items(W, "2026-11") + _items(W, "2026-12")
