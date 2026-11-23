"""1.8.1 audit (group f4): drafts, marked swap ideas, rule months and the close-in folder at the bid period's edge.
Hawaiian's bid periods are not calendar months: November runs Nov 1 to Dec 1, December Dec 2 to 31 (the pairing files'
bounds, _periods). With the Pot month select on Both (Ryan) the Watcher holds November's pot 003.152 and December's
003.153 at once; a pilot instance on This month holds one.
POT-5 / LIVE-6 / T10: a swap or drop draft names the folder (BCID) of its trip's own bid month, never the earliest
watched one (FLICA files a request inside one BCID). Drafts only: nothing is ever sent.
POT-9: a marked ("would trade") trip's ideas stay inside its bid period, as the automatic ideas do.
POT-10: rule months 'current' and 'next' are the HST bid months, and a trip counts in the bid month of its first day.
POT-11: on Dec 1 (still November's bid month) the close-in folder stays November's.
Synthetic data only: made-up pairings H39xx, no names, no FLICA (a fake browser answers)."""
import json
from datetime import date, datetime, timedelta, timezone

import pytest

import pot as P
import rules as R
from test_fw181_pot_month import NOT_OPEN, NOV_D1, DEC, STUBS, _check, _periods, at, page
from test_release_a_flica import mk, real_fl  # noqa: F401

OWN_ITEMS = [("H3903", "2026-11-26", "2026-11-27"), ("H3907", "2026-11-30", "2026-12-02"),
             ("H3913", "2026-12-06", "2026-12-08")]  # his trips: November's, carried across the edge, December's


def _days(a, b):
    d0, d1 = date.fromisoformat(a), date.fromisoformat(b)
    return [(d0 + timedelta(days=i)).isoformat() for i in range((d1 - d0).days + 1)]


def _prow(pid, start, end, month, src="O"):
    """A pot row as the Watcher holds it after its detail read (FLICA's DDMon dates), from the pot of `month`."""
    s, e = date.fromisoformat(start), date.fromisoformat(end)
    st, en = f"{s.day:02d}{s:%b}", f"{e.day:02d}{e:%b}"
    return {"pairing": pid, "start": st, "end": en, "dates": f"{st}-{en}", "days": str((e - s).days + 1),
            "credit": "14:00", "blk": "9:00", "soft": "5:00", "layover": "LAX", "turn": "", "report": "08:00",
            "arrive": "18:00", "src": src, "month": month, "detail_url": ""}


def _sw(mk, inst="", mode="Both", pots=("2026-11", "2026-12"), trade=(), drop=(), t=None):  # noqa: F811
    """A Watcher on Nov 23 (HST) with the pairing files' bounds, the pot pages of `pots` watched (S pot_urls), a green
    reserve grid Nov 1 to Dec 31, his three trips, and FAR 117 reading OK; no pay rate (the ideas carry no pay)."""
    W = mk(inst, t=t or at(2026, 11, 23))
    _periods(W)
    W.row_date = lambda s, today=None: P.row_date(s, today or W.local_now().date())
    W.far_for = lambda ev, exclude=None: "OK"
    W.swap_pay_settings = lambda: (None, None, ())
    W.S["pot_month"] = mode
    W.S["pot_urls"] = {m: W.mobile_pot_url(W.POT_BCID_SEED[m]) for m in pots}
    W.S["grid"] = {d: {"color": "green", "net": 9} for d in _days("2026-11-01", "2026-12-31")}
    items = [{"trip": p, "start": s, "end": e, "lay": "LAX"} for p, s, e in OWN_ITEMS]
    W.S["schedule"] = {"2026-11": {"items": items[:2]}, "2026-12": {"items": items[1:]}}
    W.S["own_trips"] = {f"{p}|{s}": {"credit": "10:00", "soft": "1:00", "report": "08:00", "seat": "FO"}
                        for p, s, _ in OWN_ITEMS}
    W.S["trade_away"], W.S["drop_away"] = list(trade), list(drop)
    return W


def _ev(W, kind):
    return [json.loads(p) for t, p in W.MQ.msgs if t == f"{W.T}/event/{kind}"]


# ---------------------------------------------------------------- POT-5 / LIVE-6 / T10: the draft's folder
@pytest.mark.parametrize("inst", ["", "pilot2"])
def test_a_swap_draft_names_the_folder_of_its_trips_bid_month(mk, inst):  # noqa: F811
    """Both: a December idea's draft names December's 003.153 and a November idea's November's 003.152 (1.8.1 before:
    003.152, the earliest watched folder, for both)."""
    W = _sw(mk, inst, trade=["H3913|2026-12-06", "H3903|2026-11-26"])
    W.swap_scan([_prow("H3912", "2026-12-06", "2026-12-08", "2026-12"),
                 _prow("H3902", "2026-11-26", "2026-11-27", "2026-11")])
    drafts = _ev(W, "swap_test")
    assert {(d["give"], d["take"]): d["bcid"] for d in drafts} == {("H3913 2026-12-06", "H3912 06Dec"): "003.153",
                                                                   ("H3903 2026-11-26", "H3902 26Nov"): "003.152"}
    assert {d["bcid"]: (d.get("bid_month"), d["sendable"]) for d in drafts} == {"003.153": ("2026-12", False),
                                                                                "003.152": ("2026-11", False)}
    assert all(t["form"]["BCID"] == t["bcid"] for t in W.S["swap_tests"])  # the draft's form names the same folder


def test_a_drop_draft_names_the_folder_of_its_trips_bid_period(mk):  # noqa: F811
    """Both (the admin's drop scan): December's trip is dropped from 003.153; November's and the trip carried across
    the edge (Nov 30 to Dec 2, November's bid period) from 003.152."""
    W = _sw(mk, drop=["H3913|2026-12-06", "H3903|2026-11-26", "H3907|2026-11-30"])
    W.drop_scan()
    got = {d["give"]: (d["bcid"], d["form"]["BCID"], d["sendable"]) for d in _ev(W, "drop_ready")}
    assert got == {"H3913 2026-12-06": ("003.153", "003.153", False), "H3903 2026-11-26": ("003.152", "003.152", False),
                   "H3907 2026-11-30": ("003.152", "003.152", False)}
    assert {d["give"]: d.get("bid_month") for d in _ev(W, "drop_ready")} == {
        "H3913 2026-12-06": "2026-12", "H3903 2026-11-26": "2026-11", "H3907 2026-11-30": "2026-11"}


def test_a_draft_of_a_month_not_watched_names_that_months_pick_never_another_months(mk):  # noqa: F811
    """This month (November's pot only): a December trip's drop draft (its grid days green from an earlier read)
    names December's own folder (pot_pick: Ryan's link 003.153), not November's watched 003.152. A draft whose bid
    month is not known says so and names no folder."""
    W = _sw(mk, mode="This month", pots=("2026-11",), drop=["H3913|2026-12-06"])
    W.drop_scan()
    (d,) = _ev(W, "drop_ready")
    assert (d["bcid"], d["form"]["BCID"], d.get("bid_month")) == ("003.153", "003.153", "2026-12")
    W.swap_test({"for": "H3913|2026-12-06", "pairing": "H3912", "start": "06Dec", "report": "08:00",
                 "key": "H3912|06Dec>H3913|2026-12-06", "bid_month": "closein"})
    t = W.S["swap_tests"][-1]
    assert t["bcid"] is None and t["form"] is None and not t["sendable"]
    assert "not known" in t["why"] and "003.15" not in t["why"]


# ---------------------------------------------------------------- POT-9: a marked trip's ideas, one bid period
@pytest.mark.parametrize("inst", ["", "pilot2"])
def test_a_marked_trips_ideas_stay_inside_its_bid_period(mk, inst):  # noqa: F811
    """His marked H3907 (Nov 30 to Dec 2) is November's: a December pot trip that shares Dec 2 is no idea (no push, no
    draft, not on the sensor); November's trip over the same days is, and its draft names 003.152."""
    W = _sw(mk, inst, trade=["H3907|2026-11-30"])
    W.swap_scan([_prow("H3951", "2026-12-02", "2026-12-04", "2026-12"),
                 _prow("H3952", "2026-11-30", "2026-12-02", "2026-11")])
    assert [e["pairing"] for e in _ev(W, "swap")] == ["H3952"]
    assert [(d["take"], d["bcid"]) for d in _ev(W, "swap_test")] == [("H3952 30Nov", "003.152")]
    st = W.MQ.last(f"{W.T}/swap/state")
    assert [i["pairing"] for i in st["ideas"]] == ["H3952"]
    assert W.S["swap_seen"] == ["H3952|30Nov>H3907|2026-11-30"]


# ---------------------------------------------------------------- POT-10: rule months are the HST bid months
class _Clocked(datetime):
    """rules.py's datetime with now() on the test's clock (the Watcher's time.time)."""
    W = None

    @classmethod
    def now(cls, tz=None):
        return datetime.fromtimestamp(cls.W.CLOCK.t, tz or timezone.utc)


def _rule_hits(W, monkeypatch, months, rows):
    _Clocked.W = W
    monkeypatch.setattr(R, "datetime", _Clocked)
    old = (datetime.fromtimestamp(W.CLOCK.t, timezone.utc) - timedelta(days=8)).isoformat()
    clean, errs = R.validate([{"id": "sin_hunt", "name": "SIN layover", "mode": "alert", "created_at": old,
                               "match": {"layover": ["SIN"], "months": months}}])
    assert errs == []
    W.RULES["list"] = clean
    for i, (start, end) in enumerate(rows):
        row = _prow(f"H393{i}", start, end, "2026-11")
        row["layover"] = "SIN"
        W.run_rules("2026-11", f"{row['pairing']}|{row['start']}", row)
    return [e["row"]["start"] for e in _ev(W, "rule_match")]


@pytest.mark.parametrize("inst", ["", "pilot2"])
def test_current_and_next_are_the_hst_bid_months_at_14_hst_on_nov_30(mk, monkeypatch, inst):  # noqa: F811
    """14:00 HST Nov 30 is Dec 1 in UTC: 'this month or next' still means November and December (the HST date's bid
    month), so a Nov 30 trip matches and a January one does not (1.8.1 before: December and January from 14:00)."""
    W = mk(inst, t=at(2026, 11, 30, 15))
    _periods(W)
    got = _rule_hits(W, monkeypatch, ["current", "next"],
                     [("2026-11-30", "2026-12-02"), ("2027-01-05", "2027-01-07"), ("2026-12-12", "2026-12-14")])
    assert got == ["30Nov", "12Dec"]


@pytest.mark.parametrize("inst", ["", "pilot2"])
def test_a_trip_counts_in_the_bid_month_of_its_first_day(mk, monkeypatch, inst):  # noqa: F811
    """Dec 1 (HST) is November's bid month: 'current' takes a Dec 1 trip, not a Dec 2 one (December's, 'next'); a rule
    naming 2026-12 takes the Dec 2 trip, not the Dec 1 one."""
    W = mk(inst, t=at(2026, 12, 1, 10))
    _periods(W)
    rows = [("2026-12-01", "2026-12-03"), ("2026-12-02", "2026-12-04")]
    assert _rule_hits(W, monkeypatch, ["current"], rows) == ["01Dec"]
    W.MQ.msgs.clear()
    assert _rule_hits(W, monkeypatch, ["2026-12"], rows) == ["02Dec"]
    W.MQ.msgs.clear()
    assert _rule_hits(W, monkeypatch, ["next"], rows) == ["02Dec"]


def test_rules_stay_pure_and_default_to_the_calendar():
    """rules.py takes the bid month from its caller (month_of, this_month); without them the calendar month of today, as
    before."""
    r = {"id": "x", "name": "x", "enabled": True, "mode": "alert", "match": {"months": ["current"]}}
    row = {"pairing": "H3940", "start": "01Dec", "dates": "01Dec-03Dec"}
    dec1 = date(2026, 12, 1)
    assert R.matches(r, row, dec1) == (True, "")
    nov = lambda d: "2026-11" if d <= date(2026, 12, 1) else "2026-12"  # noqa: E731
    assert R.matches(r, row, dec1, month_of=nov, this_month="2026-11") == (True, "")
    assert R.matches(r, dict(row, start="02Dec"), dec1, month_of=nov, this_month="2026-11") == (False, "month")
    nxt = dict(r, match={"months": ["next"]})
    assert R.matches(nxt, dict(row, start="02Dec"), dec1, month_of=nov, this_month="2026-11") == (True, "")
    assert R.matches(nxt, dict(row, start="02Dec"), dec1) == (False, "month")  # the calendar: December is current


# ---------------------------------------------------------------- POT-11: the close-in folder at the edge
# a menu with one close-in heading per bid month (the shape where a re-pick would take December's folder)
MENU2 = """<html><body>
<b>OPEN TIME- Add/Swap/Drop requests</b><div>November</div>
<a href="/full/mobileopentimepot.cgi?BCID=003.152&amp;From=MainMenu">View Opentime Pot</a>
<div>December</div>
<a href="/full/mobileopentimepot.cgi?BCID=003.153&amp;From=MainMenu">View Opentime Pot</a>
<b>Close in Opentime: &lt;16 Hrs to RPT</b><div>November</div>
<a href="/full/mobileopentimepot.cgi?BCID=008.152&amp;From=MainMenu">View Opentime Pot</a>
<b>Close in Opentime: &lt;16 Hrs to RPT</b><div>December</div>
<a href="/full/mobileopentimepot.cgi?BCID=008.153&amp;From=MainMenu">View Opentime Pot</a>
</body></html>"""


@pytest.mark.parametrize("inst,mode", [("", "Both"), ("pilot2", "This month")])
def test_the_close_in_folder_stays_novembers_on_dec_1(mk, inst, mode):  # noqa: F811
    """Ryan (Both) and a pilot (This month): the close-in folder found on Nov 30 (November's 008.152) is kept all of
    Dec 1, November's last bid day, through the menu's daily re-read; at Dec 2 (December's bid period) December's
    008.153 takes over."""
    W = mk(inst, t=at(2026, 11, 30, 12))
    for f in STUBS:
        setattr(W, f, lambda *a, **k: None)
    W.crew_index_check = lambda *a, **k: "ok"
    W.S["pot_month"], W.S["pot_urls"] = mode, {}
    _periods(W)
    pages = {"003.152": page(NOV_D1), "003.153": page(DEC), "008.152": page(), "008.153": page()}
    menus = []

    def answer(u):
        if "leftmenu" in u:
            menus.append(W.local_now())
            return MENU2
        return pages.get(W.bcid(u), NOT_OPEN) if "opentimepot" in u else "<html><body>x</body></html>"
    fl = real_fl(W, answer)
    _check(W, fl)
    ci = W.S["close_in"]
    assert ci["bcid"] == "008.152" and ci["verified"] and W.S["close_in_bcid"] == "008.152"
    for h in (0, 7, 13, 19, 23):  # Dec 1, November's last bid day: the menu is read again once (its daily re-read)
        W.CLOCK.t = at(2026, 12, 1, h, 10)
        assert W.this_month_key() == "2026-11"
        _check(W, fl)
        assert (W.S["close_in"]["bcid"], W.S["close_in_bcid"]) == ("008.152", "008.152"), h
        assert W.S["close_in"].get("verified")
    assert [m.day for m in menus] == [30, 1]
    W.CLOCK.t = at(2026, 12, 2, 6, 30)  # December's bid period: its folder
    _check(W, fl)
    _check(W, fl)
    assert W.this_month_key() == "2026-12" and W.S["close_in"]["bcid"] == "008.153"
    assert W.S["close_in_bcid"] == "008.153"
