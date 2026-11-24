"""1.8.2 (LIVE-10, council loop 2; S1, P6, T2): the schedule's current month is the bid month of today, and every
month the schedule reads again runs the current month's change path.

Hawaiian's bid periods are not calendar months: November 2026 runs Nov 1 to Dec 1, December Dec 2 to 31. So on Dec 1
November is still the current month (read every 30 min, Schedule Lookup bd=1126, the mobile page of bid period 152)
and December a future one; December becomes current on Dec 2. And a trade or swap in another month (December, seen on
Schedule Lookup before Dec 2) is diffed like the current month's: event/schedule_changed, the FW-0064 moves and their
one request_decided push, with the same text and pricing; a month's first read is no change. A trip on two pages (Nov 30
to Dec 2: November's, carried onto December's) is one change, and a group of another month's moves waits for that
month's own quiet read (G1A-1, G1A-2). FLICA is never reached: a fake browser answers with synthetic pages (made-up
pairings H39xx, "Doe, Jane" 10001, "Doe, John")."""
import json
import logging
from datetime import date

import pytest

import pot as P
from test_fw181_pot_month import _periods, at
from test_fw182_sched_fresh import DEC6, MIN, _items, _lk, _tick, _w
from test_release_a_flica import INVALID, mk, real_fl  # noqa: F401

DOW = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")  # date.weekday() order


def _mob(name, year, rows, trips=None, updated=None, days_off=True):
    """A mobile schedule page (pot.parse_schedule's layout) headed '<name> <year> Schedule' whose rows are the days in
    rows (ISO dates, in page order). trips: {ISO day: (pairing, layover, days)}; updated: its 'Schedule Updated' (HST);
    days_off False: no Days Off total on it (the OT drop view's page)."""
    cell = {}
    for d0, (pid, lay, n) in (trips or {}).items():
        k = rows.index(d0)
        cell[d0] = (f"<a>{pid}</a>", lay)
        for j in range(1, n):
            if k + j < len(rows):
                cell.setdefault(rows[k + j], ("-", "HNL" if j == n - 1 else "-"))
    body = "".join(f"<tr><td>{DOW[date.fromisoformat(d).weekday()]}</td><td>{d[8:]}</td>"
                   f"<td>{cell.get(d, ('-', '-'))[0]}</td><td>{cell.get(d, ('-', '-'))[1]}</td></tr>" for d in rows)
    return (f"<html><body><div>{name} {year} Schedule</div><table><tr><td>Schedule Updated:<br>"
            f"{updated or f'Nov 22, {year} 09:00:00'} HA</td></tr></table><table border=1><tr><th>Day</th>"
            "<th>Pairing</th><th>Layover</th></tr>" + body + "</table>" + ("<p>Days Off 16</p>" if days_off else "") +
            "</body></html>")


def _days(a, b):
    return [date.fromordinal(n).isoformat() for n in range(date.fromisoformat(a).toordinal(),
                                                             date.fromisoformat(b).toordinal() + 1)]


# November's bid period (Nov 1 to Dec 1, H3905 Nov 29 to Dec 1) and December's page with its carry-in rows first
# (H3907 Nov 30 to Dec 2 runs into December's period; FLICA's December Schedule Lookup page starts that way too)
NOV_PAGE = _mob("Nov", 2026, _days("2026-11-01", "2026-12-01"), {"2026-11-05": ("H3901", "LAX", 2),
                                                                  "2026-11-29": ("H3905", "KIX", 3)})
DEC_PAGE = _mob("Dec", 2026, _days("2026-11-30", "2026-12-31"), {"2026-11-30": ("H3907", "KIX", 3),
                                                                  "2026-12-12": ("H3913", "SYD", 4)})


def _ev(W, kind):
    return [json.loads(p) for t, p in W.MQ.msgs if t == f"{W.T}/event/{kind}"]


def _rec(credit, blk):
    return {"report": "07:00", "last_arr": "11:37", "credit": credit, "blk": blk, "seat": "FO",
            "crew": ["CA Doe, John (10002)", "FO Doe, Jane (10001)"], "duties": [], "soft": "0:00"}


# ---------------------------------------------------------------- LIVE-10: the current month is the bid month
def test_parse_schedule_anchors_a_carry_in_row_to_the_month_before_the_header():
    """A mobile page headed December whose first rows are Nov 30 and Dec 1 (a trip carried into December's period) is
    December's page with those two days in November, never Dec 30 and January (P5)."""
    sp = P.parse_schedule(DEC_PAGE)
    assert sp["month"] == "2026-12"
    assert (sp["days"][0][0], sp["days"][1][0], sp["days"][-1][0]) == ("2026-11-30", "2026-12-01", "2026-12-31")
    assert [(i["trip"], i["start"]) for i in sp["items"]] == [("H3907", "2026-11-30"), ("H3913", "2026-12-12")]
    nov = P.parse_schedule(NOV_PAGE)
    assert nov["month"] == "2026-11" and nov["days"][-1][0] == "2026-12-01"
    assert ("H3905", "2026-11-29") in [(i["trip"], i["start"]) for i in nov["items"]]


def test_dec_1_reads_november_every_30_min_and_december_as_a_future_month(mk):
    """Schedule Lookup path (a pilot, and the admin before he learned a mobile page): on Dec 1 every read's first load
    is November's page (bd=1126), December is read on the spare load every 30 min; on Dec 2 December is current."""
    W, F = _w(mk, t=at(2026, 11, 30, 23, 0))
    _periods(W)
    F.pg["1126"] = [("05", "H3901", "LAX"), ("29", "H3905", "KIX")]
    _tick(W, F)
    W.CLOCK.t = at(2026, 12, 1, 0, 10)
    assert W.this_month_key() == "2026-11"
    reads = []
    while W.CLOCK.t < at(2026, 12, 1, 20, 0):
        got = _tick(W, F)
        if got:
            reads.append(got)
    assert reads and all(r[0][1] == "1126" for r in reads), reads[:3]
    nov = [r[0][0] for r in reads]
    assert max(b - a for a, b in zip(nov, nov[1:])) <= 30 * MIN + 6 * MIN + 30
    dec = [t for r in reads for t, bd in r if bd == "1226"]
    assert len(dec) >= len(reads) - 2 and max(b - a for a, b in zip(dec, dec[1:])) <= 60 * MIN + 6 * MIN + 30
    assert W.S["sched_status"]["ok"] and W.S["schedule"]["2026-11"]["read_ts"] >= at(2026, 12, 1, 19, 0)
    assert ("H3905", "2026-11-29") in [(i["trip"], i["start"]) for i in
                                       W.MQ.last(f"{W.T}/schedule")["months"]["2026-11"]["items"]]
    W.CLOCK.t = at(2026, 12, 2, 0, 5)
    assert W.this_month_key() == "2026-12" and _tick(W, F)[0][1] == "1226"


def test_a_november_change_on_dec_1_is_diffed_as_the_current_month(mk):
    """P6: on Dec 1 a change to November (still the current bid month) is seen at the next 30 min read, with its event
    and moves."""
    W, F = _w(mk, t=at(2026, 11, 30, 23, 0))
    _periods(W)
    F.pg["1126"] = [("05", "H3901", "LAX"), ("29", "H3905", "KIX")]
    _tick(W, F)
    W.CLOCK.t = at(2026, 12, 1, 9, 0)
    F.pg["1126"] = [("05", "H3901", "LAX"), ("30", "H3906", "KIX")]
    got = _tick(W, F)
    assert got and got[0][1] == "1126"
    (ch,) = [e for e in _ev(W, "schedule_changed") if e["month"] == "2026-11"]
    assert (ch["added"], ch["removed"]) == (["H3906 2026-11-30"], ["H3905 2026-11-29"])
    assert sorted((m["side"], m["trip"]) for m in W.S["sched_moves"]) == [("add", "H3906"), ("drop", "H3905")]


def test_a_past_months_day_long_freshness_waits_for_its_bid_period_to_end(mk):
    W, F = _w(mk, t=at(2026, 12, 1, 12, 0))
    _periods(W)
    assert W.other_month_fresh_s("2026-11", "2026-12") == W.SCHED_FUTURE_FRESH_S  # November's period runs to Dec 1
    assert W.other_month_fresh_s("2026-10", "2026-11") == W.SCHED_PAST_FRESH_S
    assert W.other_month_fresh_s("2026-12", "2026-11") == W.SCHED_FUTURE_FRESH_S
    W.CLOCK.t = at(2026, 12, 2, 0, 5)
    assert W.other_month_fresh_s("2026-11", "2026-12") == W.SCHED_PAST_FRESH_S


def _mobile_fl(W, F, pages):
    """The admin's mobile path: the mobile schedule page by bid period number (pages {'152': html}) or INVALID."""
    def answer(u):
        if "mobileschedule" in u:
            n = u.split("BCID=001.")[1][:3] if "BCID=001." in u else ""
            return pages.get(n, pages.get("", INVALID))
        return F.answer(u)
    F.fl = real_fl(W, answer)


def test_dec_1_on_the_mobile_path_reads_bid_period_152_as_november(mk):
    """Ryan's learned mobile page (BCID 001.{n}): on Dec 1 the current month's page is bid period 152 (November's),
    stored as 2026-11 with its Dec 1 day; December's own page (153) is read from Dec 2."""
    W, F = _w(mk, t=at(2026, 12, 1, 0, 10), mobile=True)
    _periods(W)
    _mobile_fl(W, F, {"152": NOV_PAGE, "153": DEC_PAGE})
    _tick(W, F)
    mob = [u for _, u in F.fl.loads if "mobileschedule" in u]
    assert mob and "BCID=001.152" in mob[0], mob
    nov = W.S["schedule"]["2026-11"]
    assert W.S["sched_status"]["ok"] and nov["days"][-1][0] == "2026-12-01" and "src" not in nov
    assert not [d for m in W.S["schedule"].values() for d, *_ in m.get("days") or [] if d >= "2027"]
    W.CLOCK.t = at(2026, 12, 2, 0, 5)
    n = len(F.fl.loads)
    _tick(W, F)
    assert "BCID=001.153" in [u for _, u in F.fl.loads[n:] if "mobileschedule" in u][0]
    dec = W.S["schedule"]["2026-12"]
    assert dec["days"][0][0] == "2026-11-30" and "src" not in dec and W.S["sched_status"]["ok"]


def test_a_mobile_page_of_another_month_is_never_stored_as_the_current_month(mk):
    """A mobile page whose URL names no month (FLICA's own default) that shows December on Dec 1 is refused for the
    current month (November): the read goes on to Schedule Lookup bd=1126, and no day of January is stored."""
    W, F = _w(mk, t=at(2026, 12, 1, 0, 10), mobile=True)
    W.S["sched_shape"] = W.S["sched_shape_mobile"] = "/full/mobileschedule.cgi?From=MainMenu"
    _periods(W)
    _mobile_fl(W, F, {"": DEC_PAGE})
    got = _tick(W, F)
    assert [bd for _, bd in got] == ["mobile", "1126"]
    assert W.S["schedule"]["2026-11"]["src"] == "lookup"
    assert not [d for m in W.S["schedule"].values() for d, *_ in m.get("days") or [] if d >= "2027"]
    assert "2026-12" not in W.S["schedule"]


# the picker's pairing page (synthetic): H3905 Nov 29, home on LAX-HNL 07:00 to 10:30 HST Dec 1
PICKER_PAIRING = ("<html><body>pairing details h3905:29nov check in: 08:00 dy flt dps-ars dep arr blk su 9001 hnl-lax"
                  " 0900 1600 0500 tu 9002 lax-hnl 0700 1030 0530 crew: ca 10009 doe, john fo 10008 doe, jane"
                  "</body></html>")


def test_a_dec_1_pickup_looks_up_the_pickers_november_page(mk):
    """The in-flight lookup (inflt.run) asks the pickup day's bid month: a pickup on Dec 1 reads the picker's
    November page (bd=1126), whose trip runs Nov 29 to Dec 1 (December's page would not list it). G1-TEST-2: the
    picker is airborne on that trip's last leg at the pickup (10:00 HST), so the finds card says IN FLIGHT on it."""
    W, F = _w(mk, t=at(2026, 12, 1, 12, 0))
    _periods(W)
    gone = "2026-12-01T20:00:00+00:00"  # 10:00 HST Dec 1
    W.DB.add_find("H3931|01Dec", "2026-11", {"pairing": "H3931"}, gone, gone=gone)
    W.DB.set_pickup("H3931|01Dec", {"status": "filled", "by": "FO Doe, Jane (10008)", "ca": "", "known": True})
    seen = []

    def answer(u):
        seen.append(u)
        if "cmschedules" in u:
            bd = u.split("bd=")[1][:4] if "bd=" in u else "default"
            return _lk(bd if bd != "default" else "1226", [("29", "H3905", "LAX")] if bd == "1126" else [])
        if "mobilepairing" in u:
            return PICKER_PAIRING
        return "<html><body>x</body></html>"
    fl = real_fl(W, answer)
    W.inflt_check(fl)
    (f,) = [x for x in W.DB.recent_finds() if x.get("pairing") == "H3931"]
    assert (f["inflt"], f["inflt_trip"]) == (True, "H3905 2026-11-29")
    assert {k: f["inflt_leg"][k] for k in ("flt", "frm", "to", "date")} == {"flt": "9002", "frm": "LAX", "to": "HNL",
                                                                          "date": "2026-12-01"}
    looks = [u for u in seen if "cmschedules" in u]
    assert looks and "bd=1126" in looks[0] and not [u for u in looks if "bd=1226" in u or "bd=" not in u], looks


# ---------------------------------------------------------------- S1, P6, T2: another month's change path
def _swap(mk, monkeypatch, instance="", mobile=False):
    W, F = _w(mk, instance, t=at(2026, 11, 23, 0, 0), mobile=mobile)
    monkeypatch.setattr(W, "ha_state", lambda e: {f"input_number.{W.T}_longevity_year": "12.0"}.get(e))
    W.S["own_trips"] = {"H3913|2026-12-04": _rec("17:35", "15:00"), "H3913|2026-12-06": _rec("21:00", "18:00")}
    return W, F


def _until_dec(W, F, n=1, limit=6 * 3600):
    """Checks until December was read n more times; the loads."""
    out, t0 = [], W.CLOCK.t
    while sum(1 for _, bd in out if bd == "1226") < n and W.CLOCK.t < t0 + limit:
        out += _tick(W, F)
    return out


@pytest.mark.parametrize("instance,mobile", [("", False), ("", True), ("james", False)])
def test_a_december_swap_seen_on_schedule_lookup_is_pushed_once(mk, monkeypatch, instance, mobile):
    """Nov 23 (Ryan on his mobile page, Both; a pilot on Schedule Lookup, This month): December's H3913 Dec 4 becomes
    H3913 Dec 6 on FLICA's December page. The next December read publishes event/schedule_changed and records the
    FW-0064 moves; one quiet read later the trade goes out once as event/request_decided, priced like the current
    month's; later reads and the first December read as the current month (Dec 2) push nothing more."""
    W, F = _swap(mk, monkeypatch, instance, mobile)
    assert "1226" in [bd for _, bd in _until_dec(W, F)]
    assert _items(W, "2026-12") == [("H3913", "2026-12-04")] and not _ev(W, "schedule_changed")  # first read
    F.pg["1226"] = list(DEC6)
    _until_dec(W, F)
    assert _items(W, "2026-12") == [("H3913", "2026-12-06")]
    (ch,) = _ev(W, "schedule_changed")
    assert (ch["month"], ch["added"], ch["removed"]) == ("2026-12", ["H3913 2026-12-06"], ["H3913 2026-12-04"])
    assert sorted((m["side"], m["trip"], m["start"]) for m in W.S["sched_moves"]) == [
        ("add", "H3913", "2026-12-06"), ("drop", "H3913", "2026-12-04")]
    assert not _ev(W, "request_decided")  # decided one quiet read later, as the current month's
    t0 = W.CLOCK.t
    while W.CLOCK.t < t0 + 4 * 3600:
        _tick(W, F)
    (ev,) = _ev(W, "request_decided")
    assert (ev["type"], ev["status"], ev["source"]) == ("Trade", "Approved", "schedule")
    assert ev["detail"] == "gave H3913 04DEC; took H3913 06DEC (seen on the FLICA schedule; no request on file)"
    assert [(x["trip"], x["day"], x["side"]) for x in ev["legs"]] == [("H3913", "04DEC", "drop"),
                                                                     ("H3913", "06DEC", "add")]
    rate = W.pay_settings()[0]
    if rate:
        want = (21.0 - (17 + 35 / 60)) * rate
        assert ev["pay"]["delta"] == pytest.approx(round(want, 2), abs=0.02) and ev["pay"]["credit_delta"] == "+3:25"
    _periods(W)
    W.CLOCK.t = at(2026, 12, 2, 0, 5)
    W.MQ.msgs.clear()
    for _ in range(12):
        _tick(W, F)
    assert not _ev(W, "request_decided") and not [e for e in _ev(W, "schedule_changed") if e["month"] == "2026-12"]


def test_a_december_change_logs_one_schedule_changed_line(mk, monkeypatch, caplog):
    W, F = _swap(mk, monkeypatch)
    _until_dec(W, F)
    F.pg["1226"] = list(DEC6)
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        _until_dec(W, F)
        _until_dec(W, F)
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("SCHEDULE changed")]
    assert len(lines) == 1 and "'month': '2026-12'" in lines[0] and "H3913 2026-12-06" in lines[0]
    assert [r.getMessage() for r in caplog.records if r.getMessage().startswith("schedule moves 2026-12")]


def test_a_month_read_on_another_page_than_its_copy_is_an_event_with_no_moves(mk, monkeypatch):
    """As the current month's: a copy from the mobile page and a read on Schedule Lookup are not the same page, so a
    difference is published but never taken for a trade (the 'same src' guard)."""
    W, F = _swap(mk, monkeypatch)
    W.S.setdefault("schedule", {})["2026-12"] = {"month": "2026-12", "updated": "", "items": [
        {"trip": "H3913", "start": "2026-12-04", "end": "2026-12-07", "lay": "SYD"}], "days": [], "totals": {}}
    F.pg["1226"] = list(DEC6)
    _until_dec(W, F)
    assert [e["month"] for e in _ev(W, "schedule_changed")] == ["2026-12"]
    assert not W.S.get("sched_moves")


def test_the_previous_months_mobile_fallback_runs_the_change_path(mk, monkeypatch):
    """prev_month_check's mobile BlockDate page (no own employee number: no Schedule Lookup) is diffed against the
    copy on file too."""
    W, F = _w(mk, t=at(2026, 11, 23, 0, 0), mobile=True)
    W.S.pop("own_emp", None)
    oct_rows = _days("2026-10-01", "2026-10-31")
    W.S["schedule"] = {"2026-10": P.parse_schedule(_mob("Oct", 2026, oct_rows, {"2026-10-03": ("H3905", "LAX", 2)}))}
    _mobile_fl(W, F, {"": _mob("Oct", 2026, oct_rows, {"2026-10-05": ("H3905", "LAX", 2)})})
    W.S["sched_prev_at"] = 0
    W.prev_month_check(F.fl, "https://ha2.flica.net/full/mobileschedule.cgi?BCID=001.152&From=MainMenu", "2026-11")
    assert _items(W, "2026-10") == [("H3905", "2026-10-05")]
    (ch,) = _ev(W, "schedule_changed")
    assert (ch["month"], ch["added"], ch["removed"]) == ("2026-10", ["H3905 2026-10-05"], ["H3905 2026-10-03"])
    assert sorted(m["side"] for m in W.S["sched_moves"]) == ["add", "drop"]


# ---------------------------------------------------------------- G1A-1: a trip on two pages is one change
def _lkr(bd, rows, trips, updated="Nov 22, 2026 13:52:55"):
    """A Schedule Lookup page (inflt.parse_cm_month's layout) whose rows are the ISO days in rows, carry-in rows too
    (FLICA's December page starts Nov 30 when a trip runs across the edge). trips: {ISO day: (pairing, layover,
    days)}; updated: its 'Schedule Last Updated' (HST)."""
    cell = {}
    for d0, (pid, lay, n) in trips.items():
        k = rows.index(d0)
        cell[d0] = (pid, lay)
        for j in range(1, n):
            if k + j < len(rows):
                cell.setdefault(rows[k + j], ("", "HNL" if j == n - 1 else "-"))
    tasks = "".join(f'TAry[TAry.length]=new Task(1, "{DOW[date.fromisoformat(d).weekday()]}", "{d[8:]}", '
                    f'"{cell.get(d, ("", ""))[0]}", "{cell.get(d, ("", ""))[1]}", "{d.replace("-", "")}");'
                    for d in rows)
    opts = "".join(f'<option value="{b}"{" selected" if b == bd else ""}> M' for b in ("1026", "1126", "1226"))
    return (f'<html><script>function pair(pr){{}} {tasks}</script><select name="BlockDates">{opts}</select>'
            f" DOE, JANE (Emp# 10001) Schedule Last Updated: {updated} HA<TABLE><TR><TD Colspan=2"
            " Class='left'>Block &nbsp;&nbsp;</TD>\n<TD Colspan=2 Class='right'>70.00 &nbsp;&nbsp;</TD></TR><TR><TD"
            " Colspan=2 Class='left'>Credit &nbsp;&nbsp;</TD>\n<TD Colspan=2 Class='right'>85.00 &nbsp;&nbsp;</TD>"
            "</TR></TABLE></html>")


NOV_ROWS, DEC_ROWS = _days("2026-11-01", "2026-12-01"), _days("2026-11-30", "2026-12-31")
EDGE = ("H3907", "KIX", 3)  # Nov 30 to Dec 2: November's trip, carried onto December's page (as Ryan's H3607)


def _edge_fl(W, F, st):
    """The fake FLICA for a trip across the edge: November's page (rows Nov 1 to Dec 1, on Schedule Lookup and on the
    mobile page, Ryan's path) and December's (rows Nov 30 to Dec 31) from st {'nov', 'dec', 'up'}."""
    def answer(u):
        if "cmschedules" in u:
            bd = u.split("bd=")[1][:4]
            if bd == "1026":
                return _lkr(bd, _days("2026-10-01", "2026-10-31"), {"2026-10-03": ("H3905", "LAX", 2)}, st["up"])
            return {"1126": lambda: _lkr(bd, NOV_ROWS, st["nov"], st["up"]),
                    "1226": lambda: _lkr(bd, DEC_ROWS, st["dec"], st["up"])}.get(bd, lambda: INVALID)()
        if "mobileschedule" in u:
            return _mob("Nov", 2026, NOV_ROWS, st["nov"], updated=st["up"])
        return F.answer(u)
    F.fl = real_fl(W, answer)


def _run(W, F, hours):
    t0 = W.CLOCK.t
    while W.CLOCK.t < t0 + hours * 3600:
        _tick(W, F)


def _edge_setup(mk, monkeypatch, instance, mobile, own):
    W, F = _w(mk, instance, t=at(2026, 11, 23, 0, 0), mobile=mobile)
    _periods(W)
    monkeypatch.setattr(W, "ha_state", lambda e: {f"input_number.{W.T}_longevity_year": "12.0"}.get(e))
    W.S["own_trips"] = dict(own)
    st = {"nov": {"2026-11-05": ("H3901", "LAX", 2), "2026-11-30": EDGE},
          "dec": {"2026-11-30": EDGE, "2026-12-12": ("H3913", "SYD", 4)}, "up": "Nov 22, 2026 13:52:55"}
    _edge_fl(W, F, st)
    _run(W, F, 2)
    assert ("H3907", "2026-11-30") in _items(W, "2026-11") and ("H3907", "2026-11-30") in _items(W, "2026-12")
    assert not _ev(W, "schedule_changed") and not W.S.get("sched_moves")
    return W, F, st


def _changed(W):
    return [(e["month"], e["removed"], e["added"]) for e in _ev(W, "schedule_changed")]


@pytest.mark.parametrize("instance,mobile", [("", False), ("james", False), ("", True)])
def test_a_trip_on_two_pages_traded_away_is_one_move_and_one_push(mk, monkeypatch, instance, mobile):
    """G1A-1: Nov 23 a crew-to-crew trade (no request on file) gives H3907 Nov 30 (on November's page and, carried
    in, on December's) for H3909 Nov 25. One push, each leg once, priced 17:35 -> 21:00 (+3:25); one
    schedule_changed (November's: December's page changed only in its carried-in row, which November's page
    reported); no move left open, so a December assignment later that HST day is no second 'Trade'."""
    W, F, st = _edge_setup(mk, monkeypatch, instance, mobile, {"H3907|2026-11-30": _rec("17:35", "15:00"),
                                                               "H3909|2026-11-25": _rec("21:00", "18:00")})
    st.update(nov={"2026-11-05": ("H3901", "LAX", 2), "2026-11-25": ("H3909", "SYD", 3)},
              dec={"2026-12-12": ("H3913", "SYD", 4)}, up="Nov 23, 2026 02:10:00")
    _run(W, F, 4)
    (ev,) = _ev(W, "request_decided")
    assert ev["detail"] == "gave H3907 30NOV; took H3909 25NOV (seen on the FLICA schedule; no request on file)"
    assert [(x["trip"], x["day"], x["side"]) for x in ev["legs"]] == [("H3907", "30NOV", "drop"),
                                                                     ("H3909", "25NOV", "add")]
    if W.pay_settings()[0]:
        assert ev["pay"]["credit_delta"] == "+3:25" and ev["pay"]["delta"] > 0
    assert sorted((m["side"], m["trip"], m["start"], m["state"]) for m in W.S["sched_moves"]) == [
        ("add", "H3909", "2026-11-25", "pushed"), ("drop", "H3907", "2026-11-30", "pushed")]
    assert _changed(W) == [("2026-11", ["H3907 2026-11-30"], ["H3909 2026-11-25"])]
    assert ("H3907", "2026-11-30") not in _items(W, "2026-12")  # December's copy is up to date all the same
    # later the same HST day: a December trip assigned with nothing given (no trade)
    W.S["own_trips"]["H3930|2026-12-20"] = _rec("10:00", "9:00")
    st.update(dec={"2026-12-12": ("H3913", "SYD", 4), "2026-12-20": ("H3930", "SYD", 3)}, up="Nov 23, 2026 06:00:00")
    _run(W, F, 4)
    assert len(_ev(W, "request_decided")) == 1, [e["detail"] for e in _ev(W, "request_decided")]
    assert _changed(W)[1:] == [("2026-12", [], ["H3930 2026-12-20"])]


@pytest.mark.parametrize("mobile", [False, True])
def test_a_trip_on_two_pages_traded_for_a_december_trip(mk, monkeypatch, mobile):
    """G1A-1: the carried-in H3907 Nov 30 given for H3915 Dec 15. November's page reports the drop, December's the
    add only: one push 'gave H3907 30NOV; took H3915 15DEC', +3:25, the drop once."""
    W, F, st = _edge_setup(mk, monkeypatch, "", mobile, {"H3907|2026-11-30": _rec("17:35", "15:00"),
                                                         "H3915|2026-12-15": _rec("21:00", "18:00")})
    st.update(nov={"2026-11-05": ("H3901", "LAX", 2)}, up="Nov 23, 2026 02:10:00",
              dec={"2026-12-12": ("H3913", "SYD", 3), "2026-12-15": ("H3915", "SYD", 3)})
    _run(W, F, 4)
    (ev,) = _ev(W, "request_decided")
    assert ev["detail"] == "gave H3907 30NOV; took H3915 15DEC (seen on the FLICA schedule; no request on file)"
    if W.pay_settings()[0]:
        assert ev["pay"]["credit_delta"] == "+3:25"
    assert sorted(_changed(W)) == [("2026-11", ["H3907 2026-11-30"], []), ("2026-12", [], ["H3915 2026-12-15"])]
    assert [m["state"] for m in W.S["sched_moves"]] == ["pushed", "pushed"]


def _it(trip, start, end, lay="KIX"):
    return {"trip": trip, "start": start, "end": end, "lay": lay}


def _copy(month, items, updated, src="lookup"):
    return {"month": month, "updated": updated, "items": items, "days": [], "totals": {}, "src": src}


def test_the_dec_2_roll_over_sees_a_carried_in_change_once(mk, monkeypatch):
    """G1A-1 at the roll-over: November's last read (Dec 1 23:55, still the current month) saw H3907 Nov 30 traded
    for H3909 Nov 25; December's copy on file was read before the trade, so the first current read of December
    (Dec 2 00:05) sees the same drop again. It is the same change: no second schedule_changed and no second move, and
    the trade goes out once (November's bid period is over: the current month's read decides it)."""
    W, _ = _w(mk, t=at(2026, 12, 1, 23, 55))
    _periods(W)
    monkeypatch.setattr(W, "ha_state", lambda e: {f"input_number.{W.T}_longevity_year": "12.0"}.get(e))
    W.S["own_trips"] = {"H3907|2026-11-30": _rec("17:35", "15:00"), "H3909|2026-11-25": _rec("21:00", "18:00")}
    h3901, h3913 = _it("H3901", "2026-11-05", "2026-11-06", "LAX"), _it("H3913", "2026-12-12", "2026-12-15", "SYD")
    up0, up1 = "Dec 1, 2026 20:00:00", "Dec 1, 2026 23:50:00"
    t1 = W.now_iso()
    assert W.sched_change(_copy("2026-11", [h3901, _it("H3907", "2026-11-30", "2026-12-01")], up0),
                          _copy("2026-11", [h3901, _it("H3909", "2026-11-25", "2026-11-27", "SYD")], up1), t1)
    W.S["sched_read_at"] = t1
    W.CLOCK.t = at(2026, 12, 2, 0, 5)
    t2 = W.now_iso()
    assert not W.sched_change(_copy("2026-12", [_it("H3907", "2026-11-30", "2026-12-02"), h3913], up0),
                              _copy("2026-12", [h3913], up1), t2)
    W.S["sched_read_at"] = t2
    assert _changed(W) == [("2026-11", ["H3907 2026-11-30"], ["H3909 2026-11-25"])]
    assert sorted((m["month"], m["side"], m["trip"]) for m in W.S["sched_moves"]) == [
        ("2026-11", "add", "H3909"), ("2026-11", "drop", "H3907")]
    W.trade_check()
    (ev,) = _ev(W, "request_decided")
    assert ev["detail"] == "gave H3907 30NOV; took H3909 25NOV (seen on the FLICA schedule; no request on file)"


def test_a_trip_that_moves_again_on_its_own_page_is_a_move_each_time(mk):
    """G1A-1: only another month's page reporting the same change is left out: a December trip dropped, taken back
    and dropped again on December's own page is three moves and three schedule_changed events."""
    W, _ = _w(mk)
    h3913, h3950 = _it("H3913", "2026-12-12", "2026-12-15", "SYD"), _it("H3950", "2026-12-20", "2026-12-22")
    pages = [[h3913, h3950], [h3913], [h3913, h3950], [h3913]]
    for k, (a, b) in enumerate(zip(pages, pages[1:])):
        assert W.sched_change(_copy("2026-12", a, f"Nov 23, 2026 0{k}:00:00"),
                              _copy("2026-12", b, f"Nov 23, 2026 0{k + 1}:00:00"), W.now_iso())
    assert [(m["side"], m["trip"]) for m in W.S["sched_moves"]] == [("drop", "H3950"), ("add", "H3950"),
                                                                    ("drop", "H3950")]
    assert [e["month"] for e in _ev(W, "schedule_changed")] == ["2026-12"] * 3


def test_a_carried_in_move_recorded_by_1_8_1_is_not_recorded_again(mk):
    """G1A-1, a state from 1.8.1 (no sched_seen): November's move of H3907 Nov 30 is on file; December's first diff
    after the update sees the same drop: neither a second move nor a second event."""
    W, _ = _w(mk)
    W.S["sched_moves"] = [{"id": "drop|H3907|2026-11-30|x", "side": "drop", "trip": "H3907", "start": "2026-11-30",
                           "end": "2026-12-01", "lay": "KIX", "month": "2026-11", "at": W.now_iso(),
                           "upd": "Nov 23, 2026 02:10:00", "t": W.now_iso(), "day": "2026-11-23", "rec": {},
                           "state": "open"}]
    h3913 = _it("H3913", "2026-12-12", "2026-12-15", "SYD")
    assert not W.sched_change(_copy("2026-12", [_it("H3907", "2026-11-30", "2026-12-02"), h3913], "x"),
                              _copy("2026-12", [h3913], "Nov 23, 2026 02:10:00"), W.now_iso())
    assert len(W.S["sched_moves"]) == 1 and not _ev(W, "schedule_changed")


def test_a_carried_in_change_whose_first_page_recorded_no_moves_is_recorded_by_the_other(mk):
    """G1A-1: November's read that saw H3907 Nov 30 go was on another page than its copy (mobile, then Schedule
    Lookup: an event, no moves); December's read on Schedule Lookup both times records the move (once), with no
    second event."""
    W, _ = _w(mk)
    h3901, h3913 = _it("H3901", "2026-11-05", "2026-11-06", "LAX"), _it("H3913", "2026-12-12", "2026-12-15", "SYD")
    up = "Nov 23, 2026 02:10:00"
    assert W.sched_change(_copy("2026-11", [h3901, _it("H3907", "2026-11-30", "2026-12-01")], "x", src=None),
                          _copy("2026-11", [h3901], up), W.now_iso())
    assert not W.S.get("sched_moves")
    assert not W.sched_change(_copy("2026-12", [_it("H3907", "2026-11-30", "2026-12-02"), h3913], "x"),
                              _copy("2026-12", [h3913], up), W.now_iso())
    assert [(m["month"], m["side"], m["trip"]) for m in W.S["sched_moves"]] == [("2026-12", "drop", "H3907")]
    assert [e["month"] for e in _ev(W, "schedule_changed")] == ["2026-11"]


# ---------------------------------------------------------------- G1A-2: each month's own quiet read
@pytest.mark.parametrize("mobile", [True, False])
def test_a_december_trade_posted_in_two_steps_is_one_push(mk, monkeypatch, mobile):
    """G1A-2: FLICA posts a December trade in two steps (H3913 Dec 4 for H3914 Dec 6, then H3921 Dec 21 for H3922
    Dec 24, the second right after the December read that saw the first). A group of December moves is decided once
    December itself was read again after its newest move (S sched_read_at_by_month): on Ryan's mobile path, where
    December is read every other read, it is one push with four legs, as on the Lookup path."""
    W, F = _w(mk, t=at(2026, 11, 23, 0, 0), mobile=mobile)
    monkeypatch.setattr(W, "ha_state", lambda e: {f"input_number.{W.T}_longevity_year": "12.0"}.get(e))
    W.S["own_trips"] = {k: _rec("17:35", "15:00") for k in ("H3913|2026-12-04", "H3914|2026-12-06",
                                                           "H3921|2026-12-21", "H3922|2026-12-24")}
    F.pg["1226"] = [("04", "H3913", "SYD"), ("21", "H3921", "SYD")]
    _run(W, F, 2)
    step, t0 = 0, W.CLOCK.t
    while W.CLOCK.t < t0 + 6 * 3600:
        dec = any(bd == "1226" for _, bd in _tick(W, F))
        if step == 0 and dec:
            F.pg["1226"], step = [("06", "H3914", "SYD"), ("21", "H3921", "SYD")], 1
        elif step == 1 and dec and _items(W, "2026-12")[0][0] == "H3914":
            F.pg["1226"], step = [("06", "H3914", "SYD"), ("24", "H3922", "SYD")], 2
    assert step == 2
    (ev,) = _ev(W, "request_decided")
    assert [(x["trip"], x["side"]) for x in ev["legs"]] == [("H3913", "drop"), ("H3921", "drop"), ("H3914", "add"),
                                                           ("H3922", "add")]


def test_a_december_trade_whose_month_is_not_read_again_goes_out_two_hours_later(mk, monkeypatch):
    """G1A-2: December's page stops answering after the read that saw the swap. The push waits for December's own
    quiet read, but no longer than SCHED_QUIET_WAIT_S (2 h): then the current month's read decides it, as before."""
    W, F = _swap(mk, monkeypatch)
    _until_dec(W, F)
    F.pg["1226"] = list(DEC6)
    _until_dec(W, F)
    assert len(W.S["sched_moves"]) == 2 and not _ev(W, "request_decided")
    F.bad.add("1226")
    t0, quiet = W.CLOCK.t, 2 * 3600  # SCHED_QUIET_WAIT_S
    while W.CLOCK.t < t0 + quiet - 10 * MIN:
        _tick(W, F)
    assert not _ev(W, "request_decided")
    while W.CLOCK.t < t0 + quiet + 40 * MIN:
        _tick(W, F)
    (ev,) = _ev(W, "request_decided")
    assert ev["detail"] == "gave H3913 04DEC; took H3913 06DEC (seen on the FLICA schedule; no request on file)"
    assert W.SCHED_QUIET_WAIT_S == quiet


# ---------------------------------------------------------------- G1-TEST-1: what Ryan sees on Dec 1
def test_dec_1_refresh_button_for_november_reads_the_current_month(mk):
    """(a) On Dec 1, before FLICA's month list is read, a press for November (still current) is queued and served by
    the next read's first load (bd=1126); a press for December is refused until the list is in. A later press for
    November forces the read at once (sched_stale_force)."""
    W, F = _w(mk, t=at(2026, 12, 1, 12, 0))
    _periods(W)
    assert W.schedule_refresh_cmd('{"month": "2026-12"}') is False
    rf = W.S["sched_refresh"]
    assert (rf["month"], rf["state"]) == ("2026-12", "refused") and "only November 2026 can be refreshed" in rf["why"]
    W.schedule_refresh_cmd('{"month": "2026-11"}')
    assert (W.S["sched_refresh"]["month"], W.S["sched_refresh"]["state"]) == ("2026-11", "queued")
    got = _tick(W, F)
    assert got and got[0][1] == "1126" and W.S["sched_refresh"]["state"] == "read"
    W.CLOCK.t += 10 * MIN
    assert not W.schedule_due(False)
    W.schedule_refresh_cmd('{"month": "2026-11"}')
    assert W.S["sched_refresh"]["state"] == "queued" and W.sched_stale_force(dry=True)
    got = _tick(W, F)
    assert got and got[0][1] == "1126" and W.S["sched_refresh"]["state"] == "read"


def test_dec_1_sensor_failed_note_and_check_now_follow_the_bid_month(mk):
    """(b) the schedule sensor's 'updated' on Dec 1 is November's; (c) a failed read's note goes on November's
    refresh press; (d) Check now marks December (a future month on Dec 1) and never November."""
    W, F = _w(mk, t=at(2026, 12, 1, 12, 0))
    _periods(W)
    W.S["schedule"] = {"2026-11": _copy("2026-11", [], "Nov 30, 2026 10:00:00"),
                       "2026-12": _copy("2026-12", [], "Dec 1, 2026 09:00:00")}
    W.publish_schedule()
    assert W.MQ.last(f"{W.T}/schedule")["updated"] == "Nov 30, 2026 10:00:00"
    W.S["sched_refresh"] = {"month": "2026-11", "state": "queued", "why": "", "at": W.now_iso()}
    W.schedule_failed(["mobile: down"], ["the mobile page: no answer"])
    assert W.S["sched_refresh"]["state"] == "failed"
    W.S["lookup_months"] = {"bds": ["1026", "1126", "1226"], "at": W.CLOCK.t}
    W.check_now_marks()
    assert set(W.sched_stale()) == {"2026-12"}


def test_dec_1_a_forced_read_serves_one_other_month(mk):
    """sched_stale_force on Dec 1: December (a future month) and October both marked; the read's spare load serves
    one other month, so only December's mark is used by it and October's forces the next read."""
    W, F = _w(mk, t=at(2026, 12, 1, 12, 0))
    _periods(W)
    W.S["lookup_months"] = {"bds": ["1026", "1126", "1226"], "at": W.CLOCK.t}
    W.S["schedule"] = {m: {**_copy(m, [], ""), "read_ts": W.CLOCK.t} for m in ("2026-10", "2026-11", "2026-12")}
    for m in ("2026-12", "2026-10"):
        W.sched_stale()[m] = {"why": "test", "at": W.CLOCK.t, "forced": False}
    assert W.sched_stale_force() is True
    assert [m for m, v in sorted(W.sched_stale().items()) if v["forced"]] == ["2026-12"]
    W.sched_stale().pop("2026-12")  # the read served December
    assert W.sched_stale_force() is True and W.sched_stale()["2026-10"]["forced"]


def test_dec_1_triggers_mark_december_not_november(mk):
    """Dec 1: his seat gone from a December trip, his December trip in the pot and a CrewTrac mismatch on Dec 12
    each mark December (a future month); a CrewTrac mismatch on Dec 1 (November's bid period, the current month,
    read every 30 min anyway) marks nothing."""
    W, F = _w(mk, t=at(2026, 12, 1, 12, 0))
    _periods(W)
    W.S["lookup_months"] = {"bds": ["1026", "1126", "1226"], "at": W.CLOCK.t}
    W.S["schedule"] = {"2026-11": _copy("2026-11", [_it("H3905", "2026-11-29", "2026-12-01")], ""),
                       "2026-12": _copy("2026-12", [_it("H3913", "2026-12-12", "2026-12-15", "SYD")], "")}
    W.crewtrac_trigger({"pulled_at": "s1"}, [{"ok": False, "trip": "H3999", "start": "2026-12-01"}], [])
    assert not W.sched_stale()
    W.seat_trigger("H3913|2026-12-12", "FO", "")
    assert set(W.sched_stale()) == {"2026-12"}
    for kind, fire in (("b", lambda: W.pot_own_trigger({"2026-12": {"H3913|12Dec": {"pairing": "H3913",
                                                                                    "start": "12Dec"}}}, {"2026-12"})),
                       ("c", lambda: W.crewtrac_trigger({"pulled_at": "s2"}, [{"ok": False, "trip": "H3998",
                                                                                "start": "2026-12-12"}], []))):
        W.S["sched_stale"], W.S["sched_trig_at"] = {}, {}
        fire()
        assert set(W.sched_stale()) == {"2026-12"}, kind


def test_dec_1_month_list_is_the_current_bid_months_page(mk):
    """other_months_check on Dec 1 takes FLICA's month list from November's page (the current month's, just loaded:
    LOOKUP_PAGE bd=1126), so December is loaded once, never a second time as the month list page."""
    W, F = _w(mk, t=at(2026, 12, 1, 12, 0))
    _periods(W)
    W.S.pop("lookup_months", None)
    W.LOOKUP_PAGE.update(bd="1126", html=_lk("1126", [("05", "H3901", "LAX")]), at=W.CLOCK.t)
    W.other_months_check(F.fl, "2026-11")
    assert [bd for _, bd in F.sched()].count("1226") == 1, F.sched()


def test_a_december_page_with_no_days_off_total_counts_decembers_days():
    """pot.parse_schedule's fallback count (no Days Off total on the page) counts the header month's days, not the
    carried-in first rows' month: December's page Nov 30 to Dec 31 with H3907 (Nov 30 to Dec 2) and H3913 (Dec 12 to
    15) has 25 December days off."""
    sp = P.parse_schedule(_mob("Dec", 2026, DEC_ROWS, {"2026-11-30": EDGE, "2026-12-12": ("H3913", "SYD", 4)},
                               days_off=False))
    assert sp["month"] == "2026-12" and sp["totals"]["days_off"] == 25
