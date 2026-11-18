"""1.7.11 (Ryan, Nov 17): an own trip's times are never blanked by a pairing page with no times.

Before 1.7.11, own_trip_times wrote an empty record ({}) over the times already read whenever FLICA's pairing page came
back with no report or arrival time, and an empty record was never read again (save on a full Check now). Now a page
with no times keeps the times read before, and a trip whose last page had none is read again at most once an hour
(S["own_empty_at"], OWN_EMPTY_RETRY_S), inside the per-check limit. Synthetic schedule, made-up pairings (H9001,
H9002), no crew names, no FLICA (a fake client hands out the pages)."""
import json
import sys
from datetime import datetime, timedelta

import pytest

from pot import schedule_items


def _days(marks):
    days = [[f"2026-11-{d:02d}", "", ""] for d in range(1, 31)]
    for iso, act, lay in marks:
        days[int(iso[8:]) - 1] = [iso, act, lay]
    return days


MARKS = [("2026-11-20", "H9001", "SFO"), ("2026-11-21", "", "HNL"),
         ("2026-11-24", "H9002", "LAX"), ("2026-11-25", "", "HNL")]
TIMES = {"report": "08:00", "last_arr": "18:00", "blk": "10:00", "credit": "12:00", "crew": [], "duties": []}
K1, K2 = "H9001|2026-11-20", "H9002|2026-11-24"


def _sched(marks=MARKS):
    days = _days(marks)
    return {"items": schedule_items(days), "days": days,
            "totals": {"days_off": 20, "block": "20:00", "credit": "24:00"}, "updated": "Nov 17, 2026"}


class FakeClient:
    def __init__(self):
        self.msgs = []

    def publish(self, topic, payload="", retain=False):
        self.msgs.append((topic, payload, retain))

    def subscribe(self, topic):
        pass


class Pages:
    """A fake FLICA client: each pairing page load returns the next answer queued for that pairing ("times" or
    "none"), and counts the loads."""

    def __init__(self, **answers):
        self.answers = {k: list(v) for k, v in answers.items()}
        self.loads = []

    def fetch(self, url):
        pid = url.split("PID=")[1].split("&")[0]
        self.loads.append(pid)
        q = self.answers.get(pid) or ["none"]
        return f"{q.pop(0) if len(q) > 1 else q[0]}:{pid}"


@pytest.fixture(params=["", "pilot2"])
def W(request, tmp_path, monkeypatch):
    instance = request.param
    (tmp_path / "options.json").write_text(json.dumps({"username": "u", "password": "p", "my_name": "Doe"}))
    monkeypatch.setenv("FLIGHT_WATCHER_DATA", str(tmp_path))
    if instance:
        monkeypatch.setenv("FLIGHT_WATCHER_PREFIX", f"flight_watcher_{instance}")
        monkeypatch.setenv("FLIGHT_WATCHER_INSTANCE", instance)
    else:
        monkeypatch.delenv("FLIGHT_WATCHER_PREFIX", raising=False)
        monkeypatch.delenv("FLIGHT_WATCHER_INSTANCE", raising=False)
    monkeypatch.delenv("FLIGHT_WATCHER_OPTIONS", raising=False)
    sys.modules.pop("watcher", None)
    import watcher
    clock = {"now": datetime(2026, 11, 17, 12, 0)}  # before both trips: no in-progress re-reads
    monkeypatch.setattr(watcher.time, "sleep", lambda s: None)
    monkeypatch.setattr(watcher, "local_now", lambda: clock["now"])
    monkeypatch.setattr(watcher, "classify", lambda page: "ok")
    monkeypatch.setattr(watcher, "parse_detail",
                        lambda page: dict(TIMES) if str(page).startswith("times:") else {"crew": [], "duties": []})
    watcher.FAKE = FakeClient()
    monkeypatch.setattr(watcher, "MQ", watcher.FAKE)
    monkeypatch.setattr(watcher, "CARD_PAIRINGS", str(tmp_path / "www" / "flight-watcher"))
    watcher.S.clear()
    watcher.S["schedule"] = {"2026-11": _sched()}
    watcher.CLOCK = clock
    return watcher


def _later(W, **kw):
    W.CLOCK["now"] = W.CLOCK["now"] + timedelta(**kw)


def _have_times(rec):
    return rec.get("report") == "08:00" and rec.get("last_arr") == "18:00" and rec.get("blk") == "10:00"


def test_a_page_with_no_times_never_blanks_the_times_read_before(W, caplog):
    fl = Pages(H9001=["times", "none"], H9002=["times"])
    W.own_trip_times(fl)  # first read: both trips get their times
    assert _have_times(W.S["own_trips"][K1]) and _have_times(W.S["own_trips"][K2])
    # the times are kept and the trip is read again (a full Check now reads every trip)
    caplog.set_level("INFO")
    W.own_trip_times(fl, full=True)
    assert fl.loads.count("H9001") == 2
    assert _have_times(W.S["own_trips"][K1]), "a page with no times blanked the times read before"
    assert W.S["own_empty_at"][K1] == W.CLOCK["now"].isoformat()
    assert "no times on the pairing page; the times read before are kept" in caplog.text
    # the sensor the cards read still has them
    sensor = [json.loads(p) for t, p, _ in W.FAKE.msgs if t == f"{W.T}/own_trips"][-1]["trips"]
    assert sensor[K1]["report"] == "08:00" and sensor[K1]["blk"] == "10:00"


def test_an_empty_record_is_read_again_once_an_hour_then_filled(W):
    fl = Pages(H9001=["none", "none", "times"], H9002=["times"])
    W.own_trip_times(fl)
    assert W.S["own_trips"][K1] == {} and K1 in W.S["own_empty_at"]  # an empty record stays {}
    assert fl.loads.count("H9001") == 1
    # within the hour: not read again, however many checks run
    for _ in range(5):
        _later(W, minutes=10)
        W.own_trip_times(fl)
    assert fl.loads.count("H9001") == 1
    # an hour after the empty read: read once more (still no times), then not again for another hour
    _later(W, minutes=11)
    W.own_trip_times(fl)
    W.own_trip_times(fl)
    assert fl.loads.count("H9001") == 2 and W.S["own_trips"][K1] == {}
    _later(W, minutes=61)
    W.own_trip_times(fl)  # this time FLICA has the times: the record fills and empty_at goes
    assert fl.loads.count("H9001") == 3
    assert _have_times(W.S["own_trips"][K1]) and K1 not in W.S["own_empty_at"]
    # filled and before the trip: no more reads
    _later(W, hours=3)
    W.own_trip_times(fl)
    assert fl.loads.count("H9001") == 3


def test_a_record_from_before_1_7_11_with_no_empty_at_is_read_on_the_next_check(W):
    W.S["own_trips"] = {K1: {}, K2: dict(TIMES, read_at="2026-11-17T11:00:00", final=False, legs=[], soft="2:00")}
    fl = Pages(H9001=["none"])
    W.own_trip_times(fl)
    assert fl.loads == ["H9001"]  # the old empty record once; the trip with times is not read
    _later(W, minutes=30)
    W.own_trip_times(fl)
    assert fl.loads == ["H9001"]  # then hourly at most


def test_a_trip_in_progress_with_kept_times_is_read_at_most_hourly(W):
    # the 6 h in-progress re-read is due, but its last page had no times: not every check, once an hour
    W.CLOCK["now"] = datetime(2026, 11, 20, 23, 0)
    W.S["own_trips"] = {K1: dict(TIMES, read_at="2026-11-20T10:00:00", final=False, legs=[], soft="2:00"),
                        K2: dict(TIMES, read_at="2026-11-20T22:00:00", final=False, legs=[], soft="2:00")}
    fl = Pages(H9001=["none"])
    W.own_trip_times(fl)
    assert fl.loads == ["H9001"] and _have_times(W.S["own_trips"][K1])
    for _ in range(3):
        _later(W, minutes=15)
        W.own_trip_times(fl)
    assert fl.loads == ["H9001"]
    _later(W, minutes=20)
    W.own_trip_times(fl)
    assert fl.loads == ["H9001", "H9001"] and _have_times(W.S["own_trips"][K1])


class Stopping(Pages):
    """1.7.11: FLICA hands out a page with no times, and the Flica client's own check of that very page (page_verdict:
    not a pairing page, as while the FLICA session is going) stops every pairing read before own_trip_times sees it."""

    def __init__(self, W, **answers):
        super().__init__(**answers)
        self.W = W

    def fetch(self, url):
        page = super().fetch(url)
        self.W.BRK.fail("pairing", "not a pairing page (a page the parser does not know)", "unknown")
        return page


def test_a_page_that_stops_pairing_reads_is_no_read(W, caplog):
    """Ryan, Nov 17 (H3620 Nov 15 lost its times at 16:48 HST while the FLICA session was going): a page the breaker
    stopped pairing reads on is no read at all. The times on file and own_empty_at stay exactly as they were, a later
    trip in the same check is not pruned, and nothing more loads from FLICA in that check."""
    W.CLOCK["now"] = datetime(2026, 11, 20, 23, 0)  # on H9001: its 6 h in-progress re-read is due
    W.S["own_trips"] = {K1: dict(TIMES, read_at="2026-11-20T10:00:00", final=False, legs=[], soft="2:00"),
                        K2: dict(TIMES, read_at="2026-11-17T11:00:00", final=False, soft="2:00")}  # no legs: due too
    W.S["own_empty_at"] = {K1: "2026-11-20T19:00:00"}  # an earlier page had no times, over an hour ago
    before = json.loads(json.dumps({"own": W.S["own_trips"], "empty_at": W.S["own_empty_at"]}))
    fl = Stopping(W, H9001=["none"], H9002=["times"])
    caplog.set_level("INFO")
    W.own_trip_times(fl)
    assert not W.BRK.allow("pairing")  # the page stopped pairing reads
    assert fl.loads == ["H9001"], "a FLICA load after the page that stopped pairing reads"
    assert W.S["own_trips"] == before["own"], "a page that stopped pairing reads changed the times on file"
    assert W.S["own_empty_at"] == before["empty_at"], "a page that stopped pairing reads counted as a page with no times"
    assert _have_times(W.S["own_trips"][K1]) and K2 in W.S["own_trips"]  # the later trip is kept, not pruned
    assert "page stopped pairing reads" in caplog.text
    sensor = [json.loads(p) for t, p, _ in W.FAKE.msgs if t == f"{W.T}/own_trips"][-1]["trips"]
    assert sensor[K1]["blk"] == "10:00" and sensor[K2]["blk"] == "10:00"


def test_a_page_that_stops_pairing_reads_leaves_no_empty_record(W):
    """A trip never read whose first page stopped pairing reads gets no empty record and no empty_at: it is read as
    soon as pairing reads go again, not an hour later."""
    fl = Stopping(W, H9001=["none"])
    W.own_trip_times(fl)
    assert fl.loads == ["H9001"]
    assert K1 not in W.S.get("own_trips", {}) and K1 not in W.S.get("own_empty_at", {})


def test_the_per_check_limit_still_holds_and_empty_at_is_pruned_with_the_trip(W):
    marks = [(f"2026-11-{d:02d}", f"H90{d:02d}", "SFO") for d in range(2, 12, 2)]  # five one-day trips
    W.S["schedule"] = {"2026-11": _sched(marks)}
    fl = Pages()
    W.own_trip_times(fl)
    assert len(fl.loads) == W.OWN_PER_CHECK  # the limit per check is unchanged
    W.own_trip_times(fl)
    assert len(fl.loads) == 5  # the other two on the next check
    assert len(W.S["own_empty_at"]) == 5
    W.S["schedule"] = {"2026-11": _sched(marks[:1])}  # four trips leave the schedule
    W.own_trip_times(fl)
    assert set(W.S["own_empty_at"]) == {"H9002|2026-11-02"} and set(W.S["own_trips"]) == {"H9002|2026-11-02"}


def test_no_flica_load_without_an_empty_page(W):
    """A trip with times, before it starts, is never read again: 1.7.11 adds no load to it."""
    W.S["own_trips"] = {k: dict(TIMES, read_at="2026-11-17T11:00:00", final=False, legs=[], soft="2:00")
                        for k in (K1, K2)}

    class NoFLICA:
        def fetch(self, url):
            raise AssertionError(f"no FLICA load expected: {url}")

    for _ in range(3):
        _later(W, hours=2)
        W.own_trip_times(NoFLICA())
