"""1.8.1: a later month follows FLICA's schedule stamp (Hark for Ryan, Nov 23, 2026: "FW is not updating his December
schedule completely"). FLICA's "Last Updated" stamp covers the whole schedule, so when the current month's page (read
every 30 min) carries a newer stamp than a later month's copy, that month is read again on the same read, once per
stamp change, inside the read's two loads. 1.8.2 (merge): the rule is one more early re-read signal: stamp_marks marks
the month (S sched_stale), it takes the read's spare load first and never forces a read of its own; 1.8.2's own cadence
(a future month fresh 30 min, a closed one a day) and totals_first decide the rest. Synthetic pages and names only."""
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

import pytest

FX = Path(__file__).parent / "fixtures"
S0 = "Nov 23, 2026 00:53:18"
S1 = "Nov 23, 2026 05:08:15"
S2 = "Nov 23, 2026 05:37:39"
NOV = [("01", "H3647", "PHX", "20261101")]
DEC_04 = [("30", "H3607", "KIX", "20261130"), ("04", "H3613", "LAS", "20261204"), ("09", "H3665", "SEA", "20261209")]
DEC_06 = [("30", "H3607", "KIX", "20261130"), ("06", "H3613", "LAS", "20261206"), ("09", "H3665", "SEA", "20261209")]


class FakeClient:
    def __init__(self):
        self.msgs = []

    def publish(self, topic, payload="", retain=False):
        self.msgs.append((topic, payload, retain))

    def subscribe(self, topic):
        pass

    def last(self, topic):
        return next((p for t, p, _ in reversed(self.msgs) if t == topic), None)


class FakeFl:
    def __init__(self, pages):
        self.pages, self.urls = pages, []

    def fetch(self, url):
        self.urls.append(url)
        for k, v in self.pages.items():
            if k in url:
                return v
        return "<html>nothing</html>"


@pytest.fixture
def W(tmp_path, monkeypatch):
    monkeypatch.setenv("FLIGHT_WATCHER_DATA", str(tmp_path))
    for k in ("FLIGHT_WATCHER_PREFIX", "FLIGHT_WATCHER_INSTANCE", "FLIGHT_WATCHER_OPTIONS"):
        monkeypatch.delenv(k, raising=False)
    (tmp_path / "options.json").write_text(json.dumps({"username": "u", "password": "p"}))
    sys.modules.pop("watcher", None)
    import watcher as W
    W.SLEEPS = []
    monkeypatch.setattr(W.time, "sleep", lambda s: W.SLEEPS.append(s))
    monkeypatch.setattr(W, "local_now", lambda: datetime(2026, 11, 23, 5, 45))
    W.S.clear()
    W.LOOKUP_PAGE.update(bd="", html="", at=0)
    W.MQ = FakeClient()
    W.S["own_emp"] = "10008"
    yield W
    sys.modules.pop("watcher", None)


def _lookup(bd, months, rows, stamp, block="52.57", credit="86.35"):
    """Schedule Lookup (cmschedules.cgi) for the pilot's own number, laid out like FLICA's (synthetic values)."""
    opts = "".join(f'<option value="{b}" {"selected" if b == bd else ""}> M' for b in months)
    tasks = "".join(f'TAry[TAry.length]=new Task(1, "SU", "{dd}", "{c}", "{lay}", "{ymd}", 1, 0, \'{c}\');'
                    for dd, c, lay, ymd in rows)
    tot = "".join(f"<TR><TD Colspan=2 Class='left'>{k} &nbsp;&nbsp;</TD>\n<TD Colspan=2 Class='right'>{v} &nbsp;&nbsp;</TD></TR>"
                  for k, v in (("Block", block), ("Credit", credit), ("Days Off", 20)))
    return (f'<html><script>function pair(pr){{}} {tasks}</script><select name="BlockDates">{opts}</select>'
            f' DOE, JANE Schedule Last Updated: {stamp} HA<TABLE>{tot}</TABLE></html>')


def _pages(nov_stamp, dec_rows, dec_stamp, months=("1126", "1226")):
    return {"bd=1126": _lookup("1126", months, NOV, nov_stamp, block="103.08", credit="163.34"),
            "bd=1226": _lookup("1226", months, dec_rows, dec_stamp)}


def _read(W, fl):
    n = len(fl.urls)
    W.schedule_check(fl, force=True)
    return [u for u in fl.urls[n:]]


def _starts(W, mon):
    return [(i["trip"], i["start"]) for i in W.S["schedule"][mon]["items"]]


def test_stamp_helpers(W):
    assert W.flica_stamp(S2) == datetime(2026, 11, 23, 5, 37, 39)
    assert W.flica_stamp("Nov  1, 2026 09:54") == datetime(2026, 11, 1, 9, 54)
    assert W.flica_stamp("") is None and W.flica_stamp("Unknown") is None and W.flica_stamp(None) is None


def test_december_follows_a_trade_on_the_next_read(W, caplog):
    """The Nov 23 case: Schedule Lookup is the current month's page (Ryan's path); H3613 moves 04DEC to 06DEC."""
    caplog.set_level(logging.INFO)
    W.S["sched_shape"] = "lookup"
    fl = FakeFl(_pages(S0, DEC_04, S0))
    got = _read(W, fl)
    assert [u for u in got if "bd=1126" in u] and [u for u in got if "bd=1226" in u] and len(got) == 2
    assert ("H3613", "2026-12-04") in _starts(W, "2026-12")
    assert W.S["sched_stamp"] == S0 and W.S["schedule"]["2026-12"]["cur_stamp"] == S0
    assert all(1.5 <= s <= 3.5 for s in W.SLEEPS)  # every load paced
    # nothing moved: December is not loaded again (its read is fresh, 1.8.2: 30 min)
    assert len(_read(W, fl)) == 1
    # FLICA moves December; November's page carries the new stamp, its own trips unchanged
    fl.pages.update(_pages(S1, DEC_06, S1))
    got = _read(W, fl)
    assert len(got) == 2 and "bd=1226" in got[1]
    assert ("H3613", "2026-12-06") in _starts(W, "2026-12") and ("H3613", "2026-12-04") not in _starts(W, "2026-12")
    assert W.S["schedule"]["2026-12"]["cur_stamp"] == S1 and W.S["schedule"]["2026-12"]["updated"] == S1
    # 1.8.2 (merge): the mark's why is logged when it is made and on the month's line; sched_change logs the change
    assert "schedule 2026-12: read early (FLICA's schedule stamp moved)" in caplog.text
    assert "via Schedule Lookup (bd=1226) (FLICA's schedule stamp moved)" in caplog.text
    assert "SCHEDULE changed {'month': '2026-12'" in caplog.text
    assert "'added': ['H3613 2026-12-06'], 'removed': ['H3613 2026-12-04']" in caplog.text
    assert "2026-12" not in W.S["sched_stale"]  # the mark is served by the read
    sched = json.loads(W.MQ.last("flight_watcher/schedule"))
    assert ["H3613", "2026-12-06"] in [[i["trip"], i["start"]] for i in sched["months"]["2026-12"]["items"]]
    assert "cur_stamp" not in sched["months"]["2026-12"]  # the sensor's month keys are unchanged
    # and quiet again
    assert len(_read(W, fl)) == 1


def test_one_load_per_stamp_change_even_if_stamps_were_per_month(W):
    """Should FLICA ever stamp each month on its own, December (older stamp) is read once per change of the current
    month's stamp, never on every read."""
    W.S["sched_shape"] = "lookup"
    fl = FakeFl(_pages(S0, DEC_04, S0))
    _read(W, fl)
    fl.pages.update(_pages(S1, DEC_04, S0))  # November moved, December's page keeps its old stamp
    assert len(_read(W, fl)) == 2
    assert len(_read(W, fl)) == 1 and len(_read(W, fl)) == 1
    fl.pages.update(_pages(S2, DEC_04, S0))
    assert len(_read(W, fl)) == 2 and len(_read(W, fl)) == 1


def test_past_months_back_off_and_unlisted_months_are_not_stamp_reads(W):
    W.S["sched_shape"] = "lookup"
    fl = FakeFl(_pages(S0, DEC_04, S0, months=("1026", "1126", "1226")))
    fl.pages["bd=1026"] = _lookup("1026", ("1026", "1126", "1226"), [("03", "H3610", "LAX", "20261003")], S0)
    _read(W, fl)
    _read(W, fl)  # two loads a read: October and December are both on file after the second
    assert {"2026-10", "2026-12"} <= set(W.S["schedule"])
    W.S["sched_stamp"] = S1
    assert W.other_month_stale("2026-12", "2026-11") and not W.other_month_stale("2026-10", "2026-11")
    assert not W.other_month_stale("2026-11", "2026-11")
    assert W.later_months_stale("2026-11") == ["2026-12"]
    W.S["sched_other_fail"] = {"2026-12": {"n": 1, "next": W.time.time() + 3600}}  # back-off holds the month
    assert not W.other_month_stale("2026-12", "2026-11")
    W.S["sched_other_fail"] = {}
    W.S["lookup_months"]["bds"] = ["1026", "1126"]  # FLICA no longer lists December
    assert not W.other_month_stale("2026-12", "2026-11")
    W.S["lookup_months"]["bds"] = ["1026", "1126", "1226"]
    W.S["schedule"]["2026-12"]["cur_stamp"] = S1  # already read under this stamp
    assert not W.other_month_stale("2026-12", "2026-11")
    W.S["schedule"]["2026-12"].pop("cur_stamp")  # a copy from 1.8.0 (no cur_stamp): its own older stamp decides
    assert W.other_month_stale("2026-12", "2026-11")
    W.S["schedule"]["2026-12"]["updated"] = S1
    assert not W.other_month_stale("2026-12", "2026-11")
    W.S["sched_stamp"] = "Unknown"
    W.S["schedule"]["2026-12"]["updated"] = S0
    assert not W.other_month_stale("2026-12", "2026-11")


def test_mobile_path_gives_the_last_load_to_the_stamp_moved_month(W):
    mob = (FX / "mobile_schedule_nov.html").read_text().replace("<p>Block 92.33</p><p>Credit 121.48</p><p>YTD 592.22</p>", "")
    m_stamp = "Nov 1, 2026 09:54:34"
    assert m_stamp in mob
    W.S["sched_url_ok"] = f"{W.BASE}/full/mobileschedule.cgi?BCID=001.152&From=MainMenu"
    fl = FakeFl({"mobileschedule": mob, **_pages(S0, DEC_04, S0)})
    _read(W, fl)  # the mobile page and November's totals
    got = _read(W, fl)  # December's first read takes the last load; November keeps its stored totals
    assert len(got) == 2 and "bd=1226" in got[1]
    nov_tot = dict(W.S["schedule"]["2026-11"]["totals"])
    assert W.S["sched_stamp"] == m_stamp
    got = _read(W, fl)  # nothing moved: the mobile page and November's totals, as before 1.8.1
    assert len(got) == 2 and "bd=1126" in got[1]
    # the stamp moves, November's trips do not: December gets the read's last load, November keeps its figures
    fl.pages["mobileschedule"] = mob.replace(m_stamp, "Nov 23, 2026 05:08:15")
    fl.pages.update(_pages(S1, DEC_06, S1))
    got = _read(W, fl)
    assert len(got) == 2 and "bd=1226" in got[1]
    assert ("H3613", "2026-12-06") in _starts(W, "2026-12") and W.S["schedule"]["2026-11"]["totals"] == nov_tot
    # the stamp moves and November's own trips moved: its Block / Credit are read on this read (main's rule, kept in
    # the merge); December's stamp mark waits, unforced, and takes the next read's spare load
    fl.pages["mobileschedule"] = mob.replace(m_stamp, S2)
    fl.pages["bd=1126"] = _lookup("1126", ("1126", "1226"), NOV, S2, block="99.59", credit="111.11")
    W.S["schedule"]["2026-11"]["items"] = W.S["schedule"]["2026-11"]["items"][1:]
    W.LOOKUP_PAGE.update(bd="", html="", at=0)
    got = _read(W, fl)
    assert len(got) == 2 and "bd=1126" in got[1] and W.S["schedule"]["2026-11"]["totals"]["credit"] == "111:11"
    assert W.S["schedule"]["2026-12"]["cur_stamp"] != S2
    assert W.later_months_stale("2026-11") == ["2026-12"]  # still owed: the next read with a load left takes it
    got = _read(W, fl)
    assert len(got) == 2 and "bd=1226" in got[1]
    assert W.S["schedule"]["2026-12"]["cur_stamp"] == S2 and W.later_months_stale("2026-11") == []


# ------------------------------------------------------------------ 1.8.1 review fixes
def _three_on_file(W, mobile=False):
    """October, November and December on file, the last pass complete; returns the FakeFl."""
    months = ("1026", "1126", "1226")
    fl = FakeFl(_pages(S0, DEC_04, S0, months=months))
    fl.pages["bd=1026"] = _lookup("1026", months, [("03", "H3610", "LAX", "20261003")], S0)
    if mobile:
        mob = (FX / "mobile_schedule_nov.html").read_text().replace("<p>Block 92.33</p><p>Credit 121.48</p><p>YTD 592.22</p>", "")
        fl.pages["mobileschedule"] = mob.replace("Nov 1, 2026 09:54:34", S0)
        W.S["sched_url_ok"] = f"{W.BASE}/full/mobileschedule.cgi?BCID=001.152&From=MainMenu"
    else:
        W.S["sched_shape"] = "lookup"
    for _ in range(3):
        _read(W, fl)
    assert {"2026-10", "2026-11", "2026-12"} <= set(W.S["schedule"]) and W.S.get("sched_prev_v") == 6
    return fl


def test_a_stamp_read_loads_only_the_moved_month_and_keeps_the_past_months_clock(W):
    """1.8.2 (merge): the stamp marks only the later month. October (a closed month, read once a day) is due and
    already waited a read (late), yet the stamp read loads December alone and leaves October's clock (read_ts) as it
    was; October keeps its own clock and is read at the next read, so it is never starved."""
    fl = _three_on_file(W)
    late = 24 * 3600 + 31 * 60  # past SCHED_PAST_FRESH_S by over SCHED_FUTURE_FRESH_S: due and late
    W.S["schedule"]["2026-10"]["read_ts"] -= late
    oct_ts = W.S["schedule"]["2026-10"]["read_ts"]
    assert W.other_month_due("2026-10", "2026-11") == "due" and W.other_month_late("2026-10", "2026-11")
    fl.pages.update(_pages(S1, DEC_06, S1, months=("1026", "1126", "1226")))
    got = _read(W, fl)
    assert len(got) == 2 and "bd=1126" in got[0] and "bd=1226" in got[1]
    assert ("H3613", "2026-12-06") in _starts(W, "2026-12")
    assert W.S["schedule"]["2026-10"]["read_ts"] == oct_ts  # October's clock is left as it was
    got = _read(W, fl)  # the next read: October, on its own clock
    assert len(got) == 2 and "bd=1026" in got[1] and W.S["schedule"]["2026-10"]["read_ts"] != oct_ts
    # the stamp moves again (December back to the 4th) with October late again: December alone, then October
    W.S["schedule"]["2026-10"]["read_ts"] -= late
    oct_ts = W.S["schedule"]["2026-10"]["read_ts"]
    fl.pages.update(_pages(S2, DEC_04, S2, months=("1026", "1126", "1226")))
    got = _read(W, fl)
    assert len(got) == 2 and "bd=1226" in got[1] and ("H3613", "2026-12-04") in _starts(W, "2026-12")
    assert W.S["schedule"]["2026-10"]["read_ts"] == oct_ts and "2026-12" not in W.S["sched_stale"]
    got = _read(W, fl)
    assert len(got) == 2 and "bd=1026" in got[1] and W.S["schedule"]["2026-10"]["read_ts"] != oct_ts


def test_a_stale_month_whose_load_fails_waits_its_back_off(W):
    fl = _three_on_file(W)
    fl.pages.update(_pages(S1, DEC_06, S1, months=("1026", "1126", "1226")))
    real = fl.fetch

    def boom(url):
        if "bd=1226" in url:
            fl.urls.append(url)
            raise TimeoutError("Timeout 45000ms exceeded")
        return real(url)
    fl.fetch = boom
    got = _read(W, fl)
    assert len(got) == 2 and "bd=1226" in got[1]
    assert W.S["sched_other_fail"]["2026-12"]["n"] == 1 and not W.other_month_stale("2026-12", "2026-11")
    assert len(_read(W, fl)) == 1 and len(_read(W, fl)) == 1  # no load again while it backs off
    W.S["sched_other_fail"]["2026-12"]["next"] = 0  # the back-off is over: one more try
    fl.fetch = real
    got = _read(W, fl)
    assert len(got) == 2 and "bd=1226" in got[1] and ("H3613", "2026-12-06") in _starts(W, "2026-12")
    assert "2026-12" not in W.S["sched_other_fail"]


@pytest.mark.parametrize("oct_late", [False, True])
def test_mobile_path_this_months_own_change_reads_its_totals_at_once_then_the_stamp_month(W, oct_late):
    """The 1.8.1 review's case (main's rule kept in the merge): December is stale by the stamp and November's own
    trips moved. FLICA's stamp is the whole schedule's, so his own change marks December too, but the change that
    explains the stamp is November's own: November's Block / Credit are loaded on this read (his credit line is right
    at once), and December's stamp mark waits, unforced, for the next read's spare load, before a late October."""
    fl = _three_on_file(W, mobile=True)
    if oct_late:
        W.S["schedule"]["2026-10"]["read_ts"] -= 24 * 3600 + 31 * 60
    fl.pages["mobileschedule"] = fl.pages["mobileschedule"].replace(S0, S1)
    fl.pages["bd=1126"] = _lookup("1126", ("1026", "1126", "1226"), NOV, S1, block="99.59", credit="111.11")
    W.S["schedule"]["2026-11"]["items"] = W.S["schedule"]["2026-11"]["items"][1:]  # November's own trips moved
    W.LOOKUP_PAGE.update(bd="", html="", at=0)
    got = _read(W, fl)
    assert len(got) == 2 and "bd=1126" in got[1] and W.S["schedule"]["2026-11"]["totals"]["credit"] == "111:11"
    assert W.sched_stale()["2026-12"]["why"] == W.SCHED_STAMP_WHY and W.sched_stale()["2026-12"]["forced"] is True
    got = _read(W, fl)
    assert len(got) == 2 and "bd=1226" in got[1] and "2026-12" not in W.sched_stale()
    assert W.later_months_stale("2026-11") == []
    if oct_late:
        got = _read(W, fl)
        assert len(got) == 2 and "bd=1026" in got[1]


def test_a_stale_only_pass_that_raises_leaves_the_clock_and_the_fallback_alone(W):
    """Second review: a pause, a stopped path or a load error inside the pass for a changed later month never drops
    into the previous month's mobile fallback nor moves the pass clock."""
    fl = _three_on_file(W, mobile=True)
    W.S["sched_prev_at"] = W.time.time() - 3600
    before = (W.S["sched_prev_at"], W.S["sched_prev_v"])
    real = fl.fetch
    for exc in (W.GT.BreakerOpen("lookup", "07:00"), W.GT.GateAbort("paused"), TimeoutError("Timeout 45000ms")):
        W.S.pop("sched_other_fail", None)
        W.S["schedule"]["2026-12"]["cur_stamp"] = ""  # December owes a read under the current stamp

        def boom(url, exc=exc):
            if "bd=1226" in url:
                fl.urls.append(url)
                raise exc
            return real(url)
        fl.fetch = boom
        fl.pages["mobileschedule"] = fl.pages["mobileschedule"].replace(S0, S1)
        got = _read(W, fl)
        assert len(got) == 2 and "bd=1226" in got[1], (exc, got)  # no fallback load of the previous month
        assert (W.S["sched_prev_at"], W.S["sched_prev_v"]) == before, exc
    fl.fetch = real


def test_a_month_list_load_error_backs_off_and_counts_once(W):
    W.S["sched_shape"] = "lookup"
    W.S["own_emp"] = "10008"
    calls = []

    class Fl:
        urls = []

        def fetch(self, url):
            calls.append(url)
            raise TimeoutError("Timeout 45000ms")
    W.LOOKUP_PAGE.update(bd="", html="", at=0)
    assert W.other_months_check(Fl(), "2026-11") is False and len(calls) == 1
    assert W.S["breakers"]["lookup"]["fails"] == 1  # counted once, as a month list page that is not a schedule


def test_a_good_schedule_lookup_page_ends_a_run_of_failed_ones(W):
    """Second review: on the mobile path the lookup path's failure count is reset by any Schedule Lookup page that
    parses (the totals read, the month list, a month), so failures counted on different reads never add up to a stop
    while the path works."""
    fl = _three_on_file(W, mobile=True)
    W.BRK.fail("lookup", "test: an earlier failure")
    W.BRK.fail("lookup", "test: another")
    assert W.S["breakers"]["lookup"]["fails"] == 2
    _read(W, fl)  # the mobile page and November's totals on Schedule Lookup
    assert int((W.S["breakers"].get("lookup") or {}).get("fails") or 0) == 0


# ------------------------------------------------------------------ 1.8.2 (merge): the stamp rule as a mark
def test_a_stamp_mark_never_forces_a_read_and_leaves_triggers_their_own(W, caplog):
    """The stamp's mark takes a read's spare load first but never forces a read of its own (sched_stale_force,
    defer_mark), is made once while a mark is in hand, and a trigger's evidence for the month still forces its read."""
    caplog.set_level(logging.INFO)
    fl = _three_on_file(W)
    W.S["sched_stamp"] = S1  # a current month read moved the stamp; December was read under S0
    assert W.stamp_marks("2026-11") == ["2026-12"]
    mark = W.S["sched_stale"]["2026-12"]
    assert mark["why"] == W.SCHED_STAMP_WHY and mark["forced"] is True
    assert "schedule 2026-12: read early (FLICA's schedule stamp moved)" in caplog.text
    assert W.stamp_marks("2026-11") == []  # the mark in hand stands: no second one
    assert not W.sched_stale_force(dry=True) and not W.sched_stale_force()  # no read of its own
    assert W.defer_mark("2026-12") is False and W.S["sched_stale"]["2026-12"]["forced"] is True
    assert W.next_other_month("2026-11") == ("2026-12", "marked")  # the read's spare load goes to it first
    # his own Dec 4 seat goes empty: the trigger marks December itself and forces the read the stamp's mark did not
    W.seat_trigger("H3613|2026-12-04", "FO 2", "")
    assert W.S["sched_stale"]["2026-12"]["why"].startswith("own trip H3613 2026-12-04")
    assert W.sched_stale_force(dry=True)
    # a month backing off after a failed read is not marked by the stamp
    W.S["sched_stale"].clear()
    W.S["sched_other_fail"] = {"2026-12": {"n": 1, "next": W.time.time() + 3600}}
    assert W.stamp_marks("2026-11") == [] and "2026-12" not in W.S["sched_stale"]
    W.S["sched_other_fail"] = {}
    # the read serves the mark: December read under the new stamp, then nothing to mark
    fl.pages.update(_pages(S1, DEC_06, S1, months=("1026", "1126", "1226")))
    got = _read(W, fl)
    assert len(got) == 2 and "bd=1226" in got[1] and W.S["schedule"]["2026-12"]["cur_stamp"] == S1
    assert "2026-12" not in W.S["sched_stale"] and W.stamp_marks("2026-11") == []


@pytest.mark.parametrize("mobile", [False, True])
@pytest.mark.parametrize("how", ["press", "trigger"])
def test_a_press_or_a_trigger_right_after_a_stamp_move_is_read_in_its_own_forced_read(W, mobile, how):
    """Merge review M1: Ryan presses refresh on October (or a CrewTrac mismatch marks it) because his schedule
    changed, so FLICA's stamp moved too. The forced read's current month marks December by the stamp; the forced read's
    spare load still goes to October (a stamp mark goes after a press's or a trigger's), so the press is answered in
    that read (the card waits 3 min). December's stamp mark takes the next read's spare load."""
    fl = _three_on_file(W, mobile=mobile)
    months = ("1026", "1126", "1226")
    fl.pages.update(_pages(S1, DEC_06, S1, months=months))
    fl.pages["bd=1026"] = _lookup("1026", months, [("05", "H3611", "LAX", "20261005")], S1)
    if mobile:
        fl.pages["mobileschedule"] = fl.pages["mobileschedule"].replace(S0, S1)
    if how == "press":
        W.schedule_refresh_cmd('{"month": "2026-10"}')
        assert W.S["sched_stale"]["2026-10"]["why"] == W.SCHED_REFRESH_WHY
    else:
        W.crewtrac_trigger({"pulled_at": "snap-1"}, [], [{"month": "2026-10", "ok": False}])
        assert W.S["sched_stale"]["2026-10"]["why"].startswith("the CrewTrac check differs")
    assert W.sched_stale_force()  # the check runs the forced read
    got = _read(W, fl)
    assert len(got) == 2 and "bd=1026" in got[1], got
    assert ("H3611", "2026-10-05") in _starts(W, "2026-10") and "2026-10" not in W.S["sched_stale"]
    if how == "press":
        assert W.S["sched_refresh"]["state"] == "read"
    mark = W.S["sched_stale"]["2026-12"]  # the stamp's mark waits for a read with a load left
    assert mark["why"] == W.SCHED_STAMP_WHY and mark["forced"] is True and not W.sched_stale_force(dry=True)
    got = _read(W, fl)
    assert len(got) == 2 and "bd=1226" in got[1] and ("H3613", "2026-12-06") in _starts(W, "2026-12")
    assert "2026-12" not in W.S["sched_stale"] and W.S["schedule"]["2026-12"]["cur_stamp"] == S1


def test_mobile_path_totals_take_the_spare_load_and_the_stamp_mark_waits_unforced(W):
    """Merge review T3: on the mobile path with November's Block / Credit 3 h old and December read at the read
    before, totals_first gives the spare load to the totals although the stamp marked December; defer_mark leaves the
    stamp's mark as it is (forced True: no read of its own, no wake), and the next read serves it."""
    fl = _three_on_file(W, mobile=True)
    W.S["schedule"]["2026-12"]["read_ts"] = W.S["sched_checked_at"]  # December came in the read before this one
    W.S["sched_totals"]["at"] = W.time.time() - 3 * 3600  # November's Block / Credit 3 h old
    wake = W.WAKE_DUE["at"]
    fl.pages["mobileschedule"] = fl.pages["mobileschedule"].replace(S0, S1)
    fl.pages.update(_pages(S1, DEC_06, S1, months=("1026", "1126", "1226")))
    fl.pages["bd=1126"] = _lookup("1126", ("1026", "1126", "1226"), NOV, S1, block="99.59", credit="111.11")
    W.LOOKUP_PAGE.update(bd="", html="", at=0)
    got = _read(W, fl)
    assert len(got) == 2 and "bd=1126" in got[1], got  # the totals
    assert W.S["schedule"]["2026-11"]["totals"]["credit"] == "111:11"
    mark = W.S["sched_stale"]["2026-12"]
    assert mark["why"] == W.SCHED_STAMP_WHY and mark["forced"] is True
    assert W.WAKE_DUE["at"] == wake and not W.sched_stale_force(dry=True)
    assert W.S["schedule"]["2026-12"]["cur_stamp"] == S0
    got = _read(W, fl)
    assert len(got) == 2 and "bd=1226" in got[1] and ("H3613", "2026-12-06") in _starts(W, "2026-12")
    assert "2026-12" not in W.S["sched_stale"] and W.S["schedule"]["2026-12"]["cur_stamp"] == S1
