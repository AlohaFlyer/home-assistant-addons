"""1.8.1: a later month follows FLICA's schedule stamp (Hark for Ryan, Nov 23, 2026: "FW is not updating his December
schedule completely"). FLICA's "Last Updated" stamp covers the whole schedule, so when the current month's page (read
every 30 min) carries a newer stamp than a later month's copy, that month is read again on the same read, once per
stamp change, inside the read's two loads. Synthetic pages and names only."""
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
    # nothing moved: December is not loaded again (the 6 h copy holds)
    assert len(_read(W, fl)) == 1
    # FLICA moves December; November's page carries the new stamp, its own trips unchanged
    fl.pages.update(_pages(S1, DEC_06, S1))
    got = _read(W, fl)
    assert len(got) == 2 and "bd=1226" in got[1]
    assert ("H3613", "2026-12-06") in _starts(W, "2026-12") and ("H3613", "2026-12-04") not in _starts(W, "2026-12")
    assert W.S["schedule"]["2026-12"]["cur_stamp"] == S1 and W.S["schedule"]["2026-12"]["updated"] == S1
    assert "(read again: FLICA's schedule stamp moved)" in caplog.text
    assert "schedule 2026-12 changed: added ['H3613 2026-12-06'], removed ['H3613 2026-12-04']" in caplog.text
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


def test_mobile_path_gives_the_last_load_to_the_moved_month_only_when_this_month_did_not_move(W):
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
    # the stamp moves and November's own trips moved: its Block / Credit are read; December waits for a load
    fl.pages["mobileschedule"] = mob.replace(m_stamp, "Nov 23, 2026 05:37:39")
    W.S["schedule"]["2026-11"]["items"] = W.S["schedule"]["2026-11"]["items"][1:]
    W.LOOKUP_PAGE.update(bd="", html="", at=0)
    got = _read(W, fl)
    assert len(got) == 2 and "bd=1126" in got[1]
    assert W.S["schedule"]["2026-12"]["cur_stamp"] != "Nov 23, 2026 05:37:39"
    assert W.later_months_stale("2026-11") == ["2026-12"]  # still owed: the next read with a load left takes it


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


def test_a_stale_only_pass_loads_only_the_stale_month_and_keeps_the_6h_clock(W):
    fl = _three_on_file(W)
    W.S["schedule"]["2026-10"]["read_ts"] -= 6 * 3600 + 60  # October is past its own 6 h
    W.S["sched_prev_at"] = W.time.time() - 3600  # the pass clock is not due
    before = W.S["sched_prev_at"]
    fl.pages.update(_pages(S1, DEC_06, S1, months=("1026", "1126", "1226")))
    got = _read(W, fl)
    assert len(got) == 2 and "bd=1226" in got[1] and not [u for u in got if "bd=1026" in u]
    assert ("H3613", "2026-12-06") in _starts(W, "2026-12")
    assert W.S["sched_prev_at"] == before  # the 6 h clock of the other months is left as it was
    # the review's case: October still fresh, so the pass would have counted as complete and restarted the clock
    W.S["schedule"]["2026-10"]["read_ts"] = W.time.time() - 5 * 3600
    fl.pages.update(_pages(S2, DEC_04, S2, months=("1026", "1126", "1226")))
    got = _read(W, fl)
    assert len(got) == 2 and "bd=1226" in got[1] and ("H3613", "2026-12-04") in _starts(W, "2026-12")
    assert W.S["sched_prev_at"] == before


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


def test_mobile_path_this_months_own_change_reads_its_totals_whatever_the_other_months_say(W):
    """The review's case: the pass clock is closed, October is past its own 6 h, December is stale and November's own
    trips moved: November's Block / Credit are read (as in 1.8.0), never the stored ones."""
    fl = _three_on_file(W, mobile=True)
    W.S["schedule"]["2026-10"]["read_ts"] -= 6 * 3600 + 60
    W.S["sched_prev_at"] = W.time.time() - 3600
    fl.pages["mobileschedule"] = fl.pages["mobileschedule"].replace(S0, S1)
    fl.pages["bd=1126"] = _lookup("1126", ("1026", "1126", "1226"), NOV, S1, block="99.59", credit="111.11")
    W.S["schedule"]["2026-11"]["items"] = W.S["schedule"]["2026-11"]["items"][1:]  # November's own trips moved
    W.LOOKUP_PAGE.update(bd="", html="", at=0)
    got = _read(W, fl)
    assert "bd=1126" in got[1] and W.S["schedule"]["2026-11"]["totals"]["credit"] == "111:11"


def test_mobile_path_a_trip_that_ends_later_is_this_months_change(W):
    """Same trips and starts but a trip now ends a day later: November changed, so its totals are read."""
    fl = _three_on_file(W, mobile=True)
    fl.pages["mobileschedule"] = fl.pages["mobileschedule"].replace(S0, S1)
    fl.pages["bd=1126"] = _lookup("1126", ("1026", "1126", "1226"), NOV, S1, block="99.59", credit="111.11")
    it = W.S["schedule"]["2026-11"]["items"][0]
    it["end"] = "2026-12-31"  # the stored copy differs from the page in one trip's end only
    W.LOOKUP_PAGE.update(bd="", html="", at=0)
    got = _read(W, fl)
    assert "bd=1126" in got[1] and W.S["schedule"]["2026-11"]["totals"]["credit"] == "111:11"
    assert W.later_months_stale("2026-11") == ["2026-12"]  # December waits for a read with a load left


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
