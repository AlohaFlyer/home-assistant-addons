"""1.6.1 stage 0 (schedule read back-off): no schedule stored no longer forces a read every loop. A failed read (no page
accepted) makes the next one due 10 min later, then 30, then every SCHED_GAP_S; a read that works resets it; inside the
gap nothing is fetched from FLICA; only the start's first forced read skips the gap; one log line per failed read.
Synthetic pages only."""
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

import pytest

FX = Path(__file__).parent / "fixtures"
POT = "https://flica.example/pot"
KILLED = "<html>a new session under this account was detected</html>"


class FakeMQ:
    def publish(self, topic, payload=None, qos=0, retain=False):
        pass


class FakeFl:
    """FLICA: every schedule URL gives a page that does not parse until `good`; the pot page ends a check()."""

    def __init__(self):
        self.urls, self.good = [], False

    def fetch(self, url):
        self.urls.append(url)
        if url == POT:
            return KILLED
        if self.good and "mobileschedule" in url:
            return (FX / "mobile_schedule_nov.html").read_text()
        return "<html><body>Please wait</body></html>"

    def sched(self):
        return [u for u in self.urls if "schedule" in u]


@pytest.fixture
def W(tmp_path, monkeypatch):
    monkeypatch.setenv("FLIGHT_WATCHER_DATA", str(tmp_path))
    for k in ("FLIGHT_WATCHER_PREFIX", "FLIGHT_WATCHER_INSTANCE", "FLIGHT_WATCHER_OPTIONS", "FLIGHT_WATCHER_PORTAL"):
        monkeypatch.delenv(k, raising=False)
    (tmp_path / "options.json").write_text(json.dumps({"username": "u", "password": "p"}))
    sys.modules.pop("watcher", None)
    import watcher as W
    clock = {"t": 1_800_000_000.0}
    monkeypatch.setattr("time.time", lambda: clock["t"])
    monkeypatch.setattr("time.sleep", lambda s: None)
    monkeypatch.setattr(W, "local_now", lambda: datetime(2026, 11, 6, 8, 0))
    monkeypatch.setattr(W, "CAPTURE_DIR", str(tmp_path / "captures"))
    W.MQ = FakeMQ()
    W.S.clear()
    for k, v in json.loads(json.dumps(W.DEFAULT_STATE)).items():
        W.S.setdefault(k, v)
    W.S["sched_alt_at"] = clock["t"]  # no daily probe of the other URL shapes
    W.S["sched_probe_logged"] = W.S["sched_detail_saved"] = True  # the once-ever captures are done
    W.CLOCK = clock
    yield W
    sys.modules.pop("watcher", None)


def _at(W, s):
    W.CLOCK["t"] = 1_800_000_000.0 + s


def test_failed_reads_back_off_10_then_30_min_and_a_success_resets(W, caplog):
    fl = FakeFl()
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        W.schedule_check(fl, force=True)  # the start's first pass
    n = len(fl.sched())
    assert n >= 1 and W.S["sched_fail"] == 1 and W.S["sched_next_at"] == W.CLOCK["t"] + 600
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("schedule")]
    assert len(lines) == 1 and lines[0].startswith(f"schedule read failed (1 in a row, {n} tries: ")
    assert lines[0].endswith("next read in 10 min")
    for s, force in ((40, True), (80, False), (599, True)):  # inside the gap: no FLICA fetch, forced or not
        _at(W, s)
        W.schedule_check(fl, force=force)
        assert len(fl.sched()) == n, s
    # 1.6.2: the 3rd failed read in a row also stops the read path for 30 min (the same due time), and the 4th, with
    # no good read between, for 60 min (the breaker doubles up to 6 h), so the next read is due 60 min later
    plan = [(600, 2, 1800), (2399, None, None), (2400, 3, 1800), (4199, None, None), (4200, 4, 3600),
            (7799, None, None)]
    for s, fails, gap in plan:
        _at(W, s)
        before = len(fl.sched())
        W.schedule_check(fl)
        if fails is None:
            assert len(fl.sched()) == before, s
        else:
            assert len(fl.sched()) > before and W.S["sched_fail"] == fails
            assert W.S["sched_next_at"] == W.CLOCK["t"] + gap
    fl.good = True
    _at(W, 7800)
    W.schedule_check(fl)
    assert W.S["sched_fail"] == 0 and W.S["sched_next_at"] == 0 and "2026-11" in W.S["schedule"]
    assert W.BRK.allow("schedule") and not W.S["breakers"]["schedule"]["trips"]  # a good read closes the breaker
    before = len(fl.sched())
    _at(W, 7860)
    W.schedule_check(fl)
    assert len(fl.sched()) == before  # back to the normal 30 min gap
    W.schedule_check(fl, force=True)  # Check now after a good read re-reads, as before
    assert len(fl.sched()) > before
    fl.good = False
    _at(W, 11000)
    W.schedule_check(fl)
    assert W.S["sched_fail"] == 1 and W.S["sched_next_at"] == W.CLOCK["t"] + 600  # the sequence starts over


def test_no_schedule_stored_forces_only_the_starts_first_pass(W):
    """check(): with nothing stored the first pass reads the schedule; the next loops (40 s apart) do not, and neither
    does a Check now inside the gap; the back-off's due time does."""
    W.S["pot_urls"] = {"mobile": POT}
    for f in ("own_trip_times", "publish_working_flight", "versions_check", "uploads_check"):
        setattr(W, f, lambda *a, **k: None)
    fl = FakeFl()
    assert W.check(fl) == "killed"
    n = len(fl.sched())
    assert n >= 1 and W.S["sched_fail"] == 1
    for s in (40, 80, 120, 560):
        _at(W, s)
        assert W.check(fl) == "killed"
    W.FLAGS["full"] = True  # Check now
    _at(W, 580)
    W.check(fl)
    assert len(fl.sched()) == n
    _at(W, 600)
    W.check(fl)
    assert len(fl.sched()) > n and W.S["sched_fail"] == 2


def test_a_restart_reads_once_then_keeps_the_back_off(W):
    W.S.update(sched_fail=3, sched_next_at=W.CLOCK["t"] + 1500)
    fl = FakeFl()
    W.schedule_check(fl, force=True)  # this start's first pass (no schedule stored)
    n = len(fl.sched())
    assert n >= 1 and W.S["sched_fail"] == 4 and W.S["sched_next_at"] == W.CLOCK["t"] + 1800
    _at(W, 60)
    W.schedule_check(fl, force=True)
    assert len(fl.sched()) == n


def test_a_failed_read_is_saved_for_the_next_start(W):
    W.schedule_check(FakeFl(), force=True)
    st = W.DB.get("state")
    assert st["sched_fail"] == 1 and st["sched_next_at"] == W.CLOCK["t"] + 600


def test_tries_that_failed_before_a_good_page_are_logged_in_one_line(W, caplog):
    """A read that works after a failed try still says which URL failed (one line), so a preferred URL that starts
    failing shows in the log."""

    class Fl(FakeFl):
        def fetch(self, url):
            self.urls.append(url)
            if len(self.urls) == 1:
                raise RuntimeError("synthetic: net::ERR_TIMED_OUT")
            return (FX / "mobile_schedule_nov.html").read_text()

    fl = Fl()
    W.S["sched_url_ok"] = "https://ha2.flica.net/full/mobileschedule.cgi?BCID=001.152&From=MainMenu"  # learned before
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        W.schedule_check(fl, force=True)
    assert W.S["sched_fail"] == 0 and "2026-11" in W.S["schedule"]
    first, second = fl.urls[0].split("?")[-1], fl.urls[1].split("?")[-1]
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("schedule read")]
    assert lines == [f"schedule read: {second} worked after 1 failed: {first}: error synthetic: net::ERR_TIMED_OUT"]
    caplog.clear()
    _at(W, 4000)
    W.schedule_check(fl)  # a read that works first time: no such line
    assert not [r for r in caplog.records if r.getMessage().startswith("schedule read")]
