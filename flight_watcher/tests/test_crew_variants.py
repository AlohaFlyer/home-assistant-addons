"""FW-0068 crew index: a package trip FLICA rebuilt under a lettered id (H3999 flown as H3999B) is found by probing the
lettered ids of a departed package trip whose final read names no pilot (synthetic data only: made-up names, made-up
pairings, made-up employee numbers)."""
import logging
from datetime import datetime

import pytest

import crewidx as CI
from test_crew_index import W, _file, _row  # noqa: F401  (W is the watcher fixture)

OPEN2 = [{"pos": "CA", "name": "OPEN", "emp": ""}, {"pos": "FO", "name": "OPEN", "emp": ""}]
NAMED = [{"pos": "CA", "name": "Moe, Mo", "emp": "10005"}, {"pos": "FO", "name": "Poe, Pat", "emp": "10006"}]
# FLICA's application error page (synthetic, same shape as tests/test_inflt.py's ERR)
ERR = ("<html><head><title>FLICA.Net - Application Error</title></head><body>"
       "<h3>An error has occurred, please contact CAE Customer Care for assistance.</h3></body></html>")
KILLED = "<html>A new session under this account was detected</html>"
LEGS = ("check in: 07:30 dy flt dps-ars dep arr blk fr 2 hnl-lax 0830 1630 0500 su 1 lax-hnl 1000 1300 0600 "
        "blk : 1100 tafb : 5100 pay : 1500")


def page(pid, ddmon, line, legs=LEGS):
    """A mobile pairing page as the crew index reads it: 'pairing details h3999b:06nov ... crew: ...'."""
    return f"<html><p>flica.net - mobile pairing pairing details {pid.lower()}:{ddmon} {legs} crew: {line}</p></html>"


class VarFl:
    """Fake FLICA: pages[(pid, 'YYYYMMDD')] is the page (an Exception is raised); anything else is the application
    error page. Every fetch goes into `events` with the pacing sleeps, in order."""

    def __init__(self, pages, events=None):
        self.pages, self.urls = dict(pages), []
        self.events = events if events is not None else []

    def fetch(self, url):
        pid, d = url.split("PID=")[1].split("&")[0], url.split("DATE=")[1][:8]
        self.urls.append(url)
        self.events.append(("fetch", pid, d))
        v = self.pages.get((pid, d), ERR)
        if isinstance(v, Exception):
            raise v
        return v


def _read(fl):
    return [(u.split("PID=")[1].split("&")[0], u.split("DATE=")[1][:8]) for u in fl.urls]


def _last(W, topic):
    return [p for t, p in W.SENT if t == topic][-1]


def _sleeps(W, monkeypatch, events):
    monkeypatch.setattr(W.time, "sleep", lambda s: events.append(("sleep", s)))


# ---------------------------------------------------------------- crewidx helpers
def test_variant_ids():
    assert CI.variant_ids("H3631") == ["H3631A", "H3631B", "H3631C", "H3631D"]
    assert CI.variant_ids("h3631") == ["H3631A", "H3631B", "H3631C", "H3631D"]
    assert CI.VARIANT_LETTERS == "ABCD"
    for pid in ("H3631B", "h3631a", "", None, "VAC", "H363", "H36311", "X3631"):
        assert CI.variant_ids(pid) == []


def test_page_names():
    b = "flica.net - mobile pairing pairing details h3631b:06nov nov 6 - nov 8 check in: 07:30 crew: fo open"
    base = "flica.net - mobile pairing pairing details h3631:06nov nov 6 - nov 8 check in: 07:30 crew: fo open"
    assert CI.page_names(b, "H3631B", "2026-11-06") and CI.page_names(base, "H3631", "2026-11-06")
    assert not CI.page_names(b, "H3631", "2026-11-06")  # h3631b:06nov is not H3631
    assert not CI.page_names(base, "H3631B", "2026-11-06")  # h3631:06nov is not H3631B
    assert not CI.page_names(b, "H3631B", "2026-11-07") and not CI.page_names(b, "H3631B", "2026-12-06")
    assert not CI.page_names("pairing details xh3631b:06nov", "H3631B", "2026-11-06")
    assert not CI.page_names("pairing details h3631b:06nove", "H3631B", "2026-11-06")
    assert not CI.page_names(ERR.lower(), "H3631B", "2026-11-06")
    assert not CI.page_names(b, "H3631B", "") and not CI.page_names(b, "", "2026-11-06") and not CI.page_names(None, "H3631B", "2026-11-06")
    # the shapes the other tests use for real page text
    assert CI.page_names("flica.net - mobile pairing pairing details h3619:01nov nov 1 - nov 17 check in: 12:10",
                         "H3619", "2026-11-01")
    assert CI.page_names("pairing details h3648:03nov check in: 11:40", "h3648", "2026-11-03")
    assert CI.page_names("pairing details h3601:26jan check in: 11:40", "H3601", "2027-01-26")


def _inst(pid, d, report="07:30", src="package", period=None):
    return {"key": f"{pid}|{d}", "pairing": pid, "date": d, "end_date": d, "report": report, "route": "HNL-LAX-HNL",
            "days": 1, "month": d[:7], "period": period or d[:7], "src": src}


def test_variant_candidates():
    now = datetime(2026, 11, 10, 12, 5)
    ins = {k: _inst(*k.split("|")) for k in (
        "H9001|2026-11-06", "H9002|2026-11-08", "H9003|2026-11-04", "H9004|2026-11-07", "H9005|2026-11-05",
        "H9006B|2026-11-06", "H9007|2026-11-12", "H9008|2026-10-05", "H9009|2026-11-09", "H9010|2026-11-03",
        "H9015|2026-10-20")}
    ins["H9013|2026-11-02"] = _inst("H9013", "2026-11-02", src="schedule")
    ins["H9014|2026-11-10"] = _inst("H9014", "2026-11-10", report="12:00")  # departed 5 min ago
    ok = lambda at, crew=OPEN2: {"status": "ok", "checked_at": at, "crew": crew}  # noqa: E731
    rows = {
        "H9001|2026-11-06": ok("2026-11-07T00:00:00"),  # candidate
        "H9002|2026-11-08": ok("2026-11-08T07:30:00"),  # candidate: read right at departure
        "H9003|2026-11-04": ok("2026-11-03T00:00:00"),  # read before departure: crew not final
        "H9004|2026-11-07": ok("2026-11-08T00:00:00", NAMED),  # names crew (November is awarded)
        "H9005|2026-11-05": {"status": "fail", "checked_at": "2026-11-06T00:00:00", "crew": []},
        "H9006B|2026-11-06": ok("2026-11-07T00:00:00"),  # has a letter already
        "H9007|2026-11-12": ok("2026-11-10T00:00:00"),  # not departed
        "H9008|2026-10-05": ok("2026-10-06T00:00:00"),  # departed 36 days ago
        "H9009|2026-11-09": ok("2026-11-10T00:00:00"),  # probed already
        "H9010|2026-11-03": {"status": "empty", "checked_at": "2026-11-04T00:00:00", "crew": []},
        "H9013|2026-11-02": ok("2026-11-03T00:00:00"),  # a schedule trip, not the package's
        "H9014|2026-11-10": ok("2026-11-10T12:01:00"),  # candidate
        "H9015|2026-10-20": ok("2026-10-21T00:00:00", NAMED),  # October is awarded
    }
    got = CI.variant_candidates(ins, rows, now, {"H9009|2026-11-09"}, 35)
    assert got == ["H9014|2026-11-10", "H9002|2026-11-08", "H9001|2026-11-06"]
    # 35 days back is the limit
    assert "H9008|2026-10-05" in CI.variant_candidates(ins, rows, datetime(2026, 11, 9, 7, 30), (), 35)
    assert "H9008|2026-10-05" not in CI.variant_candidates(ins, rows, datetime(2026, 11, 9, 7, 31), (), 35)
    # a bid period no read of which names a pilot (the award is not out) is never probed
    dec = {"H9020|2026-12-02": _inst("H9020", "2026-12-02"), "H9021|2026-12-20": _inst("H9021", "2026-12-20")}
    drows = {"H9020|2026-12-02": ok("2026-12-03T00:00:00"), "H9021|2026-12-20": ok("2026-12-01T00:00:00")}
    assert CI.variant_candidates(dec, drows, datetime(2026, 12, 4), (), 35) == []
    drows["H9021|2026-12-20"] = ok("2026-12-01T00:00:00", NAMED)
    assert CI.variant_candidates(dec, drows, datetime(2026, 12, 4), (), 35) == ["H9020|2026-12-02"]


def test_instances_keep_a_variant_entry(tmp_path):
    _file(tmp_path, "2026-11", [_row("H9001", "6", rel=2)])
    extra = {"H9001B|2026-11-06": {"pairing": "H9001B", "date": "2026-11-06", "end": "2026-11-08", "route": "HNL-LAX-HNL",
                                   "report": "07:30", "src": "variant"},
             "H9002|2026-11-09": {"pairing": "H9002", "date": "2026-11-09", "end": "", "src": "own"}}
    ins = CI.instances(str(tmp_path), extra=extra)
    v = ins["H9001B|2026-11-06"]
    assert (v["src"], v["end_date"], v["days"], v["period"], v["end_known"], v["month"]) == (
        "variant", "2026-11-08", 3, "2026-11", True, "2026-11")
    assert ins["H9002|2026-11-09"]["src"] == "schedule" and ins["H9001|2026-11-06"]["src"] == "package"


# ---------------------------------------------------------------- watcher: the probe in a crew index run
def _setup(W, tmp_path, base_at="2026-11-07T00:00:00"):
    """November awarded (H9001 Nov 20 names crew); H3999 Nov 6-8 read after departure with every seat OPEN."""
    _file(tmp_path / "www", "2026-11", [_row("H3999", "6", rel=2), _row("H9001", "20", rel=0)])
    insts = CI.instances(str(tmp_path / "www"))
    W.DB.crew_put("H3999|2026-11-06", "H3999", "2026-11-06", "2026-11-08", "HNL-LAX-HNL", OPEN2, base_at, "ok")
    W.DB.crew_put("H9001|2026-11-20", "H9001", "2026-11-20", "2026-11-20", "HNL-LAX-HNL", NAMED,
                  "2026-11-09T00:00:00", "ok")
    return insts


B_LINE = "ca 10001 doe, jane fo 10003 roe, rick"


@pytest.mark.parametrize("a_page", [page("H3999A", "13nov", "ca 10007 lee, lou fo 10008 zoe, zed"), ERR])
def test_rebuilt_trip_found_and_indexed(W, tmp_path, monkeypatch, caplog, a_page):
    """The base page names nobody after departure; H3999A is another date's trip (or FLICA's error page); H3999B
    names this date with crew: it is indexed as a trip like any other (pilot card, month Markdown), its crew stored,
    C and D never read, the base left as it was and marked probed, and the next run does not probe it again."""
    _setup(W, tmp_path)
    events = []
    _sleeps(W, monkeypatch, events)
    fl = VarFl({("H3999A", "20261106"): a_page, ("H3999B", "20261106"): page("H3999B", "06nov", B_LINE),
                ("H3999C", "20261106"): page("H3999C", "06nov", "ca 10009 coe, cy fo 10010 foe, flo"),
                ("H3999", "20261106"): page("H3999", "06nov", "ca open fo open"),
                ("H9001", "20261120"): page("H9001", "20nov", "ca 10005 moe, mo fo 10006 poe, pat")}, events)
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        assert W.crew_index_check(fl) == "ok"
    assert _read(fl) == [("H3999A", "20261106"), ("H3999B", "20261106"), ("H9001", "20261120")]
    # paced: 1.5 to 3.5 s before every read, the probe's first one too
    for i, e in enumerate(events):
        if e[0] == "fetch":
            assert events[i - 1][0] == "sleep" and 1.5 <= events[i - 1][1] <= 3.5
    assert W.S["crew_last"]["pages"] == 3  # the probe's reads count in the run
    reg = W.DB.get(W.CREW_SCHED_KEY)["H3999B|2026-11-06"]
    assert {k: reg[k] for k in ("pairing", "date", "end", "route", "report", "src")} == {
        "pairing": "H3999B", "date": "2026-11-06", "end": "2026-11-08", "route": "HNL-LAX-HNL", "report": "07:30",
        "src": "variant"}
    rows = W.DB.crew_rows()
    r = rows["H3999B|2026-11-06"]
    assert (r["status"], r["date"], r["end_date"], r["route"]) == ("ok", "2026-11-06", "2026-11-08", "HNL-LAX-HNL")
    assert [(c["pos"], c["emp"]) for c in r["crew"]] == [("CA", "10001"), ("FO", "10003")]
    assert rows["H3999|2026-11-06"]["crew"] == OPEN2 and rows["H3999|2026-11-06"]["checked_at"] == "2026-11-07T00:00:00"
    assert W.DB.get(W.CREW_VARIANT_KEY)["H3999|2026-11-06"] == {"at": "2026-11-10T12:05:00", "found": "H3999B", "v": 2}
    assert W.DB.find_crew("10003")[0]["name"] == "Roe, Rick"
    assert "crew index: H3999 2026-11-06 flew as H3999B (read)" in caplog.text
    assert "Roe" not in caplog.text and "Doe" not in caplog.text and "Lee" not in caplog.text
    it = W.crew_instances()["H3999B|2026-11-06"]
    assert (it["src"], it["end_date"], it["days"], it["period"]) == ("variant", "2026-11-08", 3, "2026-11")
    ci = _last(W, "crew_index")
    assert ci["from_variants"] == 1 and ci["from_schedules"] == 0
    # the pilot card: the trip is on 10003's rebuilt month
    W.pub_pilot({"emp": "10003", "name": "Roe, Rick", "status": "error: application error", "month": "", "days": [],
                 "items": []})
    rec = _last(W, "pilot_schedule")["reconstructed"]
    assert [(x["pairing"], x["start"], x["end"], x["seat"], x["route"]) for x in rec] == [
        ("H3999B", "2026-11-06", "2026-11-08", "FO", "HNL-LAX-HNL")]
    insts = W.crew_instances()
    got = CI.pilot_trips(insts, W.DB.crew_by_emp("10003"), "2026-11", "2026-10-31", rows, end_to="2026-11-30")
    assert [(x["pairing"], x["start"]) for x in got] == [("H3999B", "2026-11-06")]
    md = (tmp_path / "crew_index" / "2026-11.md").read_text()
    assert "### Roe, Rick (10003)" in md and "| 2026-11-06 | H3999B | FO | HNL-LAX-HNL | 3 |" in md
    # the next run: the base is not probed again, the found copy (read after departure) is not read again
    W.FLAGS["crew_scan"] = True
    n0 = len(fl.urls)
    W.crew_index_check(fl)
    assert not [x for x in _read(fl)[n0:] if x[0].startswith("H3999")]


def test_already_indexed_copy_is_not_read(W, tmp_path, monkeypatch):
    """A rebuilt copy already in the index (from a schedule) whose read names a pilot is the one: nothing is read."""
    _setup(W, tmp_path)
    W.note_sched_trips([{"trip": "H3999B", "start": "2026-11-06", "end": "2026-11-08"}], "lookup")
    W.DB.crew_put("H3999B|2026-11-06", "H3999B", "2026-11-06", "2026-11-08", "", NAMED, "2026-11-07T00:00:00", "ok")
    insts, rows = W.crew_instances(), W.DB.crew_rows()
    fl = VarFl({})
    assert W.crew_variants(fl, insts, rows, 50) == (0, "ok", False)
    assert fl.urls == [] and W.DB.get(W.CREW_VARIANT_KEY)["H3999|2026-11-06"]["found"] == "H3999B"


def test_no_copy_found_is_recorded_once(W, tmp_path, monkeypatch, caplog):
    """Every letter tried (error pages, another date, a copy naming nobody): recorded with found '' and not again."""
    insts = _setup(W, tmp_path)
    rows = W.DB.crew_rows()
    events = []
    _sleeps(W, monkeypatch, events)
    fl = VarFl({("H3999A", "20261106"): page("H3999A", "06nov", "ca open fo open"),
                ("H3999C", "20261106"): page("H3999C", "07nov", B_LINE)}, events)
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        assert W.crew_variants(fl, insts, rows, 50) == (4, "ok", False)
    assert [p for p, _ in _read(fl)] == ["H3999A", "H3999B", "H3999C", "H3999D"]
    assert [e[0] for e in events] == ["sleep", "fetch"] * 4
    assert W.DB.get(W.CREW_VARIANT_KEY)["H3999|2026-11-06"]["found"] == ""
    assert "H3999C|2026-11-06" not in W.DB.crew_rows() and not W.DB.get(W.CREW_SCHED_KEY)
    assert "no rebuilt copy names a pilot" in caplog.text
    assert W.crew_variants(fl, insts, rows, 50) == (0, "ok", False) and len(fl.urls) == 4


def test_trips_not_probed(W, tmp_path, monkeypatch):
    """Read before departure, not departed, crew named, an id with a letter, an unawarded bid period: no probe."""
    _file(tmp_path / "www", "2026-11", [_row("H3991", "6", rel=0), _row("H3992", "12", rel=0), _row("H3993", "7", rel=0),
                                        _row("H3994A", "8", rel=0), _row("H9001", "20", rel=0)])
    _file(tmp_path / "www", "2026-12", [_row("H3995", "2", rel=0)])
    put = W.DB.crew_put
    put("H3991|2026-11-06", "H3991", "2026-11-06", "2026-11-06", "", OPEN2, "2026-11-05T00:00:00", "ok")  # before
    put("H3992|2026-11-12", "H3992", "2026-11-12", "2026-11-12", "", OPEN2, "2026-11-10T00:00:00", "ok")  # ahead
    put("H3993|2026-11-07", "H3993", "2026-11-07", "2026-11-07", "", NAMED, "2026-11-08T00:00:00", "ok")  # named
    put("H3994A|2026-11-08", "H3994A", "2026-11-08", "2026-11-08", "", OPEN2, "2026-11-09T00:00:00", "ok")  # letter
    put("H9001|2026-11-20", "H9001", "2026-11-20", "2026-11-20", "", NAMED, "2026-11-09T00:00:00", "ok")
    insts, rows = W.crew_instances(), W.DB.crew_rows()
    # December's period: departed (the clock moved on), read after, nobody named, and no award seen in December
    put("H3995|2026-12-02", "H3995", "2026-12-02", "2026-12-02", "", OPEN2, "2026-12-03T00:00:00", "ok")
    fl = VarFl({})
    assert W.crew_variants(fl, insts, W.DB.crew_rows(), 50) == (0, "ok", False) and fl.urls == []
    monkeypatch.setattr(W, "local_now", lambda: datetime(2026, 12, 4, 12, 0))
    assert CI.variant_candidates(insts, W.DB.crew_rows(), W.local_now(), (), W.VARIANT_MAX_AGE_D) == []
    assert W.crew_variants(fl, insts, W.DB.crew_rows(), 50) == (0, "ok", False) and fl.urls == []
    assert not W.DB.get(W.CREW_VARIANT_KEY)


def test_at_most_two_trips_a_check_most_recent_first(W, tmp_path, monkeypatch):
    _file(tmp_path / "www", "2026-11", [_row("H3991", "4", rel=0), _row("H3992", "6", rel=0), _row("H3993", "8", rel=0),
                                        _row("H9001", "20", rel=0)])
    for pid, d in (("H3991", "04"), ("H3992", "06"), ("H3993", "08")):
        W.DB.crew_put(f"{pid}|2026-11-{d}", pid, f"2026-11-{d}", f"2026-11-{d}", "", OPEN2, "2026-11-09T00:00:00", "ok")
    W.DB.crew_put("H9001|2026-11-20", "H9001", "2026-11-20", "2026-11-20", "", NAMED, "2026-11-09T00:00:00", "ok")
    insts, rows = W.crew_instances(), W.DB.crew_rows()
    fl = VarFl({})
    assert W.VARIANT_PER_CHECK == 2
    assert W.crew_variants(fl, insts, rows, 50) == (8, "ok", False)
    assert [p for p, _ in _read(fl)] == ["H3993A", "H3993B", "H3993C", "H3993D", "H3992A", "H3992B", "H3992C", "H3992D"]
    assert sorted(W.DB.get(W.CREW_VARIANT_KEY)) == ["H3992|2026-11-06", "H3993|2026-11-08"]
    assert W.crew_variants(fl, insts, rows, 50) == (4, "ok", False)
    assert {p[:5] for p, _ in _read(fl)[8:]} == {"H3991"} and len(W.DB.get(W.CREW_VARIANT_KEY)) == 3
    # the budget: a probe cut short is not recorded (1.7.3 review: its next try reads on from D)
    W.DB.put(W.CREW_VARIANT_KEY, {})
    fl2 = VarFl({})
    assert W.crew_variants(fl2, insts, rows, 3) == (3, "ok", False)
    assert [p for p, _ in _read(fl2)] == ["H3993A", "H3993B", "H3993C"] and W.DB.get(W.CREW_VARIANT_KEY) == {}


def test_fetch_error_leaves_the_trip_for_a_later_run(W, tmp_path, monkeypatch):
    """A fetch error ends that trip's probe without recording it: it is not tried again in this run, and the next run
    probes it again (1.7.3 review: the letters not read yet first, the one that failed last)."""
    _setup(W, tmp_path)
    fl = VarFl({("H3999A", "20261106"): OSError("timed out"), ("H9001", "20261120"): page("H9001", "20nov", B_LINE)})
    assert W.crew_index_check(fl) == "ok"
    assert _read(fl) == [("H3999A", "20261106"), ("H9001", "20261120")]
    assert "H3999|2026-11-06" not in (W.DB.get(W.CREW_VARIANT_KEY) or {})
    assert "crew_run" not in W.S  # the run ended (its queue ran dry)
    fl.pages[("H3999B", "20261106")] = page("H3999B", "06nov", B_LINE)
    W.FLAGS["crew_scan"] = True
    n0 = len(fl.urls)
    W.crew_index_check(fl)
    assert _read(fl)[n0:n0 + 1] == [("H3999B", "20261106")]  # B names every seat: A is not read again
    assert W.DB.get(W.CREW_VARIANT_KEY)["H3999|2026-11-06"]["found"] == "H3999B"


def test_fetch_error_not_retried_in_the_same_run(W, tmp_path, monkeypatch):
    _setup(W, tmp_path)
    fl = VarFl({("H3999A", "20261106"): OSError("timed out")})
    W.S["crew_run"] = {"started": "2026-11-10T12:00:00", "pages": 0, "why": "slot", "slot": "2026-11-10T12"}
    insts, rows = W.crew_instances(), W.DB.crew_rows()
    assert W.crew_variants(fl, insts, rows, 50) == (1, "ok", False)
    assert W.crew_variants(fl, insts, rows, 50) == (0, "ok", False) and len(fl.urls) == 1
    assert W.S["crew_run"]["variant_tried"] == ["H3999|2026-11-06"]


def test_a_killed_page_ends_the_run(W, tmp_path):
    """A page other than a pairing page (here: the session was taken) ends the probe and the run, like the queue's
    reads; nothing after it is read and the trip stays unprobed."""
    _setup(W, tmp_path)
    fl = VarFl({("H3999A", "20261106"): ERR, ("H3999B", "20261106"): KILLED})
    assert W.crew_index_check(fl) == "killed"
    assert _read(fl) == [("H3999A", "20261106"), ("H3999B", "20261106")]
    assert "crew_run" not in W.S and W.S["crew_last"]["ended"] == "killed" and W.S["crew_last"]["pages"] == 2
    assert not W.DB.get(W.CREW_VARIANT_KEY)


def test_blocked_page_stops(W, tmp_path, monkeypatch):
    _setup(W, tmp_path)
    machine = []
    monkeypatch.setattr(W, "set_machine", lambda m, note="": machine.append(m))
    fl = VarFl({("H3999A", "20261106"): "<html><p>please complete the captcha</p></html>"})
    assert W.crew_index_check(fl) == "stop"
    assert len(fl.urls) == 1 and machine == ["stopped_unexpected"]


def test_pause_halts_the_probe_and_the_run_goes_on(W, tmp_path):
    _setup(W, tmp_path)
    W.FLAGS["pause"] = True
    try:
        fl = VarFl({})
        assert W.crew_index_check(fl) == "ok"
        assert fl.urls == [] and W.S.get("crew_run") and not W.DB.get(W.CREW_VARIANT_KEY)
    finally:
        W.FLAGS["pause"] = False


def test_second_pilot_instance_never_probes(W, tmp_path, monkeypatch):
    _setup(W, tmp_path)
    monkeypatch.setattr(W, "INSTANCE", "james")
    fl = VarFl({})
    assert W.crew_variants(fl, W.crew_instances(), W.DB.crew_rows(), 50) == (0, "ok", False) and fl.urls == []


def test_old_probe_records_are_pruned(W, tmp_path):
    insts = _setup(W, tmp_path)
    W.DB.put(W.CREW_VARIANT_KEY, {"H3001|2026-08-01": {"at": "2026-08-02T00:00:00", "found": ""},
                                  "H3999|2026-11-06": {"at": "2026-11-09T00:00:00", "found": ""}})
    fl = VarFl({})
    assert W.crew_variants(fl, insts, W.DB.crew_rows(), 50) == (0, "ok", False)
    assert list(W.DB.get(W.CREW_VARIANT_KEY)) == ["H3999|2026-11-06"] and fl.urls == []


# ---------------------------------------------------------------- 1.4.12: a crew split over two rebuilt copies
OPEN3 = OPEN2 + [{"pos": "RO", "name": "OPEN", "emp": ""}]


def _setup3(W, tmp_path):
    """Like _setup, with a 3-pilot package trip (CA, FO, RO all OPEN after departure)."""
    insts = _setup(W, tmp_path)
    W.DB.crew_put("H3999|2026-11-06", "H3999", "2026-11-06", "2026-11-08", "HNL-LAX-HNL", OPEN3, "2026-11-07T00:00:00", "ok")
    return insts


def test_crew_split_over_two_copies_reads_on(W, tmp_path, monkeypatch, caplog):
    """FLICA rebuilt H3999 for the captain as H3999B and for the FO and RO as H3999C: B names 1 of the 3 pilot seats,
    so C is read too, and every pilot gets the trip on his rebuilt month; D is not read once all seats are named."""
    insts = _setup3(W, tmp_path)
    rows = W.DB.crew_rows()
    _sleeps(W, monkeypatch, [])
    fl = VarFl({("H3999B", "20261106"): page("H3999B", "06nov", "ca 10001 doe, jane"),
                ("H3999C", "20261106"): page("H3999C", "06nov", "fo 10003 roe, rick ro 10004 poe, pat")})
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        assert W.crew_variants(fl, insts, rows, 50) == (3, "ok", False)
    assert [p for p, _ in _read(fl)] == ["H3999A", "H3999B", "H3999C"]
    assert W.DB.get(W.CREW_VARIANT_KEY)["H3999|2026-11-06"] == {"at": "2026-11-10T12:05:00", "found": "H3999B,H3999C",
                                                                 "v": 2}
    for emp, pid in (("10001", "H3999B"), ("10003", "H3999C"), ("10004", "H3999C")):
        assert [r["pairing"] for r in W.DB.crew_by_emp(emp)] == [pid]
    assert "crew index: H3999B 2026-11-06 names 1 of 3 pilots, the next letters are read too (crew line: ca 10001 x, x)" \
        in caplog.text
    assert "Doe" not in caplog.text and "doe" not in caplog.text and "Roe" not in caplog.text


def test_a_copy_found_before_1_4_12_with_seats_unnamed_is_probed_again(W, tmp_path, monkeypatch):
    """A probe record from 1.4.10 / 1.4.11 (no v) whose copy named fewer pilots than the trip's seats is probed once
    more: the copy indexed already is not read again, the letters not indexed are; a complete one is left alone."""
    insts = _setup3(W, tmp_path)
    W.note_sched_trips([{"trip": "H3999B", "start": "2026-11-06", "end": "2026-11-08"}], "lookup")
    W.DB.crew_put("H3999B|2026-11-06", "H3999B", "2026-11-06", "2026-11-08", "", [NAMED[0]], "2026-11-09T00:00:00", "ok")
    W.DB.put(W.CREW_VARIANT_KEY, {"H3999|2026-11-06": {"at": "2026-11-09T00:00:00", "found": "H3999B"}})
    insts, rows = W.crew_instances(), W.DB.crew_rows()
    _sleeps(W, monkeypatch, [])
    fl = VarFl({("H3999C", "20261106"): page("H3999C", "06nov", "fo 10003 roe, rick ro 10004 poe, pat")})
    assert W.crew_variants(fl, insts, rows, 50) == (2, "ok", False)
    assert [p for p, _ in _read(fl)] == ["H3999A", "H3999C"]
    assert W.DB.get(W.CREW_VARIANT_KEY)["H3999|2026-11-06"]["found"] == "H3999B,H3999C"
    # recorded with v 2: never again
    assert W.crew_variants(fl, W.crew_instances(), W.DB.crew_rows(), 50) == (0, "ok", False) and len(fl.urls) == 2


def test_an_old_record_whose_copy_names_every_seat_stays(W, tmp_path, monkeypatch):
    insts = _setup(W, tmp_path)  # 2 pilot seats
    W.note_sched_trips([{"trip": "H3999B", "start": "2026-11-06", "end": "2026-11-08"}], "lookup")
    W.DB.crew_put("H3999B|2026-11-06", "H3999B", "2026-11-06", "2026-11-08", "", NAMED, "2026-11-09T00:00:00", "ok")
    old = {"H3999|2026-11-06": {"at": "2026-11-09T00:00:00", "found": "H3999B"}}
    W.DB.put(W.CREW_VARIANT_KEY, old)
    fl = VarFl({})
    assert W.crew_variants(fl, W.crew_instances(), W.DB.crew_rows(), 50) == (0, "ok", False)
    assert fl.urls == [] and W.DB.get(W.CREW_VARIANT_KEY) == old


def test_crew_mask_keeps_seats_and_numbers_only():
    assert CI.crew_mask("pairing details h3631b:06nov crew: ca 9606 doe, jane fb 19852 roe jr, rick ro open") == \
        "ca 9606 x, x fb 19852 x x, x ro open"
    assert CI.crew_mask("crew: ca 10001 ng, jo ckp f/o 10002 li, al") == "ca 10001 x, x ckp f/o 10002 x, x"
    assert CI.crew_mask("no crew line here") == "" and CI.crew_mask(None) == ""
    assert CI.pilot_seats(OPEN3) == 3 and CI.pilot_seats(OPEN3 + [{"pos": "FA", "name": "x", "emp": "1"}]) == 3
    assert CI.named_pilots(NAMED + OPEN2) == {"10005", "10006"}


# ---------------------------------------------------------------- 1.7.3: a lettered copy that does not exist is a miss
# a FLICA page no parser knows (synthetic): it still stops the pairing path at once, on a probe too
UNAVAIL = ("<html><head><title>503 Service Temporarily Unavailable</title></head><body><h1>Service Temporarily "
           "Unavailable</h1></body></html>")


def _miss(pid, ddmon):
    """FLICA's answer for a lettered copy that does not exist (synthetic): the page names the id and date, and holds no
    report, no crew and no credit (page_verdict 'error')."""
    return f"<html><p>flica.net - mobile pairing pairing details {pid.lower()}:{ddmon}</p></html>"


def _real_fl(W, monkeypatch, pages):
    """W.Flica (its real _load / _loaded, so the read-path breaker judges every page) with a fake browser context:
    pages[(pid, 'YYYYMMDD')] is the page (an Exception is raised); anything else is the miss page. .urls keeps every
    load that reached the context (FLICA). The gate's pacing is left out (the probe sleeps 1.5 to 3.5 s itself)."""
    import types
    monkeypatch.setattr(W.GATE, "acquire", lambda keep=0, abort=None: 0.0)
    fl = W.Flica.__new__(W.Flica)
    fl.urls = []

    def get(url, timeout=None):
        fl.urls.append(url)
        pid, d = url.split("PID=")[1].split("&")[0], url.split("DATE=")[1][:8]
        v = pages.get((pid, d), _miss(pid, datetime.strptime(d, "%Y%m%d").strftime("%d%b").lower()))
        if isinstance(v, Exception):
            raise v
        return types.SimpleNamespace(text=lambda: v)
    fl.ctx = types.SimpleNamespace(request=types.SimpleNamespace(get=get))
    return fl


def _setup9646(W, tmp_path):
    """November awarded (H9001 Nov 20 names crew); H9646 Nov 6-8 read after departure with every seat OPEN."""
    _file(tmp_path / "www", "2026-11", [_row("H9646", "6", rel=2), _row("H9001", "20", rel=0)])
    W.DB.crew_put("H9646|2026-11-06", "H9646", "2026-11-06", "2026-11-08", "HNL-LAX-HNL", OPEN2, "2026-11-07T00:00:00",
                  "ok")
    W.DB.crew_put("H9001|2026-11-20", "H9001", "2026-11-20", "2026-11-20", "HNL-LAX-HNL", NAMED, "2026-11-09T00:00:00",
                  "ok")
    return W.crew_instances()


def test_missing_lettered_copies_never_trip_the_pairing_breaker(W, tmp_path, monkeypatch, caplog):
    """Live Nov 12-13: H9646A..D do not exist; each answers a page naming the id with nothing on it. Before 1.7.3 the
    third such page stopped every pairing read for 30 min and D was refused. Now all four are read as misses, the
    breaker counts none of them, and the probe is recorded (found '')."""
    insts = _setup9646(W, tmp_path)
    fl = _real_fl(W, monkeypatch, {})
    url = f"{W.BASE}/full/mobilepairing.cgi?PID=H9646A&DATE=20261106&FROM=MobileOpentimePot&CurrentPage=1"
    assert W.page_verdict("pairing", url, _miss("H9646A", "06nov")) == "error"  # the shape seen live
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        assert W.crew_variants(fl, insts, W.DB.crew_rows(), 50) == (4, "ok", False)
    assert [p for p, _ in _read(fl)] == ["H9646A", "H9646B", "H9646C", "H9646D"]
    assert W.BRK.allow("pairing") and not (W.S.get("breakers") or {}).get("pairing", {}).get("fails")
    assert "read stopped" not in caplog.text and "probe of" not in caplog.text
    assert W.DB.get(W.CREW_VARIANT_KEY)["H9646|2026-11-06"]["found"] == ""
    assert "no rebuilt copy names a pilot" in caplog.text


def test_a_trip_probed_with_misses_is_not_probed_next_run(W, tmp_path, monkeypatch):
    """Two crew index runs (the live path: read_guard around crew_index_check). The first probes H9646's four letters
    (misses) and reads the queue; the second, 6 h later, loads no H9646 copy again (before 1.7.3 the breaker stopped
    the first run, the trip was never recorded, and every run probed it again)."""
    _setup9646(W, tmp_path)
    fl = _real_fl(W, monkeypatch, {("H9001", "20261120"): page("H9001", "20nov", B_LINE)})
    assert W.read_guard(W.crew_index_check, fl, default="ok", optional=True) == "ok"
    first = _read(fl)
    assert first[:4] == [("H9646A", "20261106"), ("H9646B", "20261106"), ("H9646C", "20261106"),
                         ("H9646D", "20261106")] and ("H9001", "20261120") in first
    assert "crew_run" not in W.S and W.BRK.allow("pairing")
    later = W.time.time() + 6 * 3600
    monkeypatch.setattr(W.BRK, "clock", lambda: later)  # a breaker stop (if any) is long over
    W.TEST_CLOCK["t"] = datetime(2026, 11, 10, 18, 5)  # the next slot's run
    assert W.read_guard(W.crew_index_check, fl, default="ok", optional=True) == "ok"
    assert W.S["crew_last"]["why"] == "slot"
    assert not [x for x in _read(fl)[len(first):] if x[0].startswith("H9646")]


def test_a_probe_cut_short_is_parked_after_bounded_tries(W, tmp_path, monkeypatch, caplog):
    """A probe a fetch error cuts short is left for a later run, but only VARIANT_MAX_TRIES times: then the trip is
    recorded with what it found and not probed again (before 1.7.3 it was probed every run until it aged out). 1.7.3
    review: the second try reads B, C and D before A again, so the trip is parked only once every letter had a try."""
    insts = _setup9646(W, tmp_path)
    rows = W.DB.crew_rows()
    fl = VarFl({("H9646A", "20261106"): OSError("timed out")})
    for i, want in enumerate((1, 4, 1)):
        W.S["crew_run"] = {"started": f"2026-11-10T{i:02d}:00:00", "pages": 0, "why": "slot", "slot": f"r{i}"}  # new run
        with caplog.at_level(logging.INFO, logger="flight_watcher"):
            assert W.crew_variants(fl, insts, rows, 50) == (want, "ok", False)
        if i == 1:
            assert W.DB.get(W.CREW_VARIANT_TRIES_KEY) == {"H9646|2026-11-06": {"n": 2, "at": "2026-11-10T12:05:00",
                                                                               "done": "BCD", "fail": "A"}}
    assert [p for p, _ in _read(fl)] == ["H9646A", "H9646B", "H9646C", "H9646D", "H9646A", "H9646A"]
    assert W.DB.get(W.CREW_VARIANT_KEY)["H9646|2026-11-06"] == {"at": "2026-11-10T12:05:00", "found": "", "v": 2,
                                                                "parked": 3, "fail": "A"}
    assert "H9646 2026-11-06 probe cut short 3 times, not probed again (H9646A never answered)" in caplog.text
    W.S["crew_run"] = {"started": "2026-11-10T12:00:00", "pages": 0, "why": "slot", "slot": "r9"}
    assert W.crew_variants(fl, insts, rows, 50) == (0, "ok", False) and len(fl.urls) == 6
    assert W.VARIANT_MAX_TRIES == 3 and not W.DB.get(W.CREW_VARIANT_TRIES_KEY)


def test_a_budget_cut_counts_a_try_only_for_the_trip_it_cut(W, tmp_path, monkeypatch):
    """The budget ends a probe after B: that trip has one try and its next try reads on from C (1.7.3 review); the
    next candidate, with no page read, has none."""
    _file(tmp_path / "www", "2026-11", [_row("H3992", "6", rel=0), _row("H3993", "8", rel=0), _row("H9001", "20", rel=0)])
    for pid, d in (("H3992", "06"), ("H3993", "08")):
        W.DB.crew_put(f"{pid}|2026-11-{d}", pid, f"2026-11-{d}", f"2026-11-{d}", "", OPEN2, "2026-11-09T00:00:00", "ok")
    W.DB.crew_put("H9001|2026-11-20", "H9001", "2026-11-20", "2026-11-20", "", NAMED, "2026-11-09T00:00:00", "ok")
    insts, rows = W.crew_instances(), W.DB.crew_rows()
    fl = VarFl({})
    assert W.crew_variants(fl, insts, rows, 2) == (2, "ok", False)
    assert [p for p, _ in _read(fl)] == ["H3993A", "H3993B"]
    assert W.DB.get(W.CREW_VARIANT_TRIES_KEY) == {"H3993|2026-11-08": {"n": 1, "at": "2026-11-10T12:05:00", "done": "AB",
                                                                       "fail": ""}}
    assert W.crew_variants(fl, insts, rows, 2) == (2, "ok", False)
    assert [p for p, _ in _read(fl)][2:] == ["H3993C", "H3993D"]
    assert sorted(W.DB.get(W.CREW_VARIANT_KEY) or {}) == ["H3993|2026-11-08"] and not W.DB.get(W.CREW_VARIANT_TRIES_KEY)
    assert W.crew_variants(fl, insts, rows, 2) == (2, "ok", False)
    assert [p for p, _ in _read(fl)][-2:] == ["H3992A", "H3992B"]


def test_a_stopped_pairing_path_ends_the_probe(W, tmp_path, monkeypatch, caplog):
    """A page no parser knows (FLICA's 'Service Temporarily Unavailable') still stops the pairing path, on a probe
    too, and is no answer for its letter: the trip it cut short has one try (A failed) and is not probed again in this
    run, the probe ends there (halted, the run goes on later), and the next trip is neither read nor charged a try."""
    _file(tmp_path / "www", "2026-11", [_row("H3992", "6", rel=0), _row("H3993", "8", rel=0), _row("H9001", "20", rel=0)])
    for pid, d in (("H3992", "06"), ("H3993", "08")):
        W.DB.crew_put(f"{pid}|2026-11-{d}", pid, f"2026-11-{d}", f"2026-11-{d}", "", OPEN2, "2026-11-09T00:00:00", "ok")
    W.DB.crew_put("H9001|2026-11-20", "H9001", "2026-11-20", "2026-11-20", "", NAMED, "2026-11-09T00:00:00", "ok")
    insts, rows = W.crew_instances(), W.DB.crew_rows()
    fl = _real_fl(W, monkeypatch, {("H3993A", "20261108"): UNAVAIL})
    W.S["crew_run"] = {"started": "2026-11-10T12:00:00", "pages": 0, "why": "slot", "slot": "2026-11-10T12"}
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        assert W.crew_variants(fl, insts, rows, 50) == (1, "ok", True)
    assert [p for p, _ in _read(fl)] == ["H3993A"] and not W.BRK.allow("pairing")
    one = {"H3993|2026-11-08": {"n": 1, "at": "2026-11-10T12:05:00", "done": "", "fail": "A"}}
    assert W.DB.get(W.CREW_VARIANT_TRIES_KEY) == one and W.S["crew_run"]["variant_tried"] == ["H3993|2026-11-08"]
    assert "crew index: variant probe stopped (FLICA pairing read stopped until" in caplog.text
    # still stopped at the next chunk: nothing reaches FLICA and no trip is charged
    assert W.crew_variants(fl, insts, rows, 50) == (0, "ok", True)
    assert len(fl.urls) == 1 and W.DB.get(W.CREW_VARIANT_TRIES_KEY) == one and not W.DB.get(W.CREW_VARIANT_KEY)


def test_a_real_error_page_on_a_detail_read_still_trips_the_breaker(W, tmp_path, monkeypatch, caplog):
    """Outside a probe (a detail read, the queue's read of a package trip) a pairing page that holds nothing is still a
    failed read: the third in a row stops the path for 30 min, also right after a probe's misses."""
    insts = _setup9646(W, tmp_path)
    fl = _real_fl(W, monkeypatch, {})
    assert W.crew_variants(fl, insts, W.DB.crew_rows(), 50) == (4, "ok", False)  # misses, not counted
    url = f"{W.BASE}/full/mobilepairing.cgi?PID=H9001&DATE=20261120&FROM=MobileOpentimePot&CurrentPage=1"
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        for _ in range(3):
            fl.fetch(url)
        with pytest.raises(W.GT.BreakerOpen):
            fl.fetch(url)
    assert not W.BRK.allow("pairing") and len(fl.urls) == 7
    assert "FLICA pairing read stopped for 30 min" in caplog.text and "not a pairing page" in caplog.text


# ---------------------------------------------------------------- 1.7.3 review: FLICA's error page, letters resumed


def test_an_application_error_page_on_a_probe_is_a_miss(W, tmp_path, monkeypatch, caplog):
    """FLICA may answer a lettered copy that does not exist with its application error page (FW-0068 counts it a miss).
    On a probe the breaker counts it as nothing too: B, the real copy, is read in the same run and indexed. Outside a
    probe the same page still stops the pairing path at once (a page the parser does not know)."""
    insts = _setup9646(W, tmp_path)
    fl = _real_fl(W, monkeypatch, {("H9646A", "20261106"): ERR, ("H9646B", "20261106"): page("H9646B", "06nov", B_LINE)})
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        assert W.crew_variants(fl, insts, W.DB.crew_rows(), 50) == (2, "ok", False)
    assert [p for p, _ in _read(fl)] == ["H9646A", "H9646B"]
    assert W.BRK.allow("pairing") and not (W.S.get("breakers") or {}).get("pairing", {}).get("fails")
    assert "read stopped" not in caplog.text
    assert W.DB.get(W.CREW_VARIANT_KEY)["H9646|2026-11-06"]["found"] == "H9646B"
    url = f"{W.BASE}/full/mobilepairing.cgi?PID=H9001&DATE=20261120&FROM=MobileOpentimePot&CurrentPage=1"
    fl.ctx.request.get = lambda u, timeout=None: (fl.urls.append(u), __import__("types").SimpleNamespace(
        text=lambda: ERR))[1]
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        fl.fetch(url)
    assert not W.BRK.allow("pairing") and "a page the parser does not know" in caplog.text


def test_a_letter_that_failed_is_tried_after_the_letters_not_read_yet(W, tmp_path, monkeypatch):
    """A times out on every read and B is the real copy: the next try reads B before A again, so B is found on the
    second run (before, every try started at A and the trip was parked with B never read)."""
    insts = _setup9646(W, tmp_path)
    rows = W.DB.crew_rows()
    fl = VarFl({("H9646A", "20261106"): OSError("timed out"), ("H9646B", "20261106"): page("H9646B", "06nov", B_LINE)})
    assert W.crew_variants(fl, insts, rows, 50) == (1, "ok", False)
    assert W.crew_variants(fl, insts, rows, 50) == (1, "ok", False)
    assert [p for p, _ in _read(fl)] == ["H9646A", "H9646B"]
    assert W.DB.get(W.CREW_VARIANT_KEY)["H9646|2026-11-06"] == {"at": "2026-11-10T12:05:00", "found": "H9646B", "v": 2}
    assert not W.DB.get(W.CREW_VARIANT_TRIES_KEY)
    assert W.crew_variants(fl, insts, rows, 50) == (0, "ok", False) and len(fl.urls) == 2


def test_a_probe_cut_by_the_budget_reads_on_from_the_next_letter(W, tmp_path, monkeypatch):
    """A budget of one read a run: each try reads the next letter, never one answered already, and the trip is recorded
    once every letter answered (not parked after VARIANT_MAX_TRIES with C and D never read)."""
    insts = _setup9646(W, tmp_path)
    rows = W.DB.crew_rows()
    fl = VarFl({})
    for _ in range(4):
        assert W.crew_variants(fl, insts, rows, 1) == (1, "ok", False)
    assert [p for p, _ in _read(fl)] == ["H9646A", "H9646B", "H9646C", "H9646D"]
    assert W.DB.get(W.CREW_VARIANT_KEY)["H9646|2026-11-06"] == {"at": "2026-11-10T12:05:00", "found": "", "v": 2}
    assert not W.DB.get(W.CREW_VARIANT_TRIES_KEY)
    assert W.crew_variants(fl, insts, rows, 1) == (0, "ok", False) and len(fl.urls) == 4


def test_a_page_nothing_knows_is_no_answer_for_its_letter(W, tmp_path, monkeypatch):
    """A page no parser knows stops the pairing path during a probe and is no answer: once the stop is over the next
    run reads B (the real copy) first, and A is never counted as read."""
    insts = _setup9646(W, tmp_path)
    rows = W.DB.crew_rows()
    fl = _real_fl(W, monkeypatch, {("H9646A", "20261106"): UNAVAIL, ("H9646B", "20261106"): page("H9646B", "06nov",
                                                                                                    B_LINE)})
    assert W.crew_variants(fl, insts, rows, 50) == (1, "ok", True)
    assert [p for p, _ in _read(fl)] == ["H9646A"] and not W.BRK.allow("pairing")
    later = W.time.time() + 3600
    monkeypatch.setattr(W.BRK, "clock", lambda: later)  # the 30 min stop is over
    assert W.crew_variants(fl, insts, rows, 50) == (1, "ok", False)
    assert [p for p, _ in _read(fl)] == ["H9646A", "H9646B"]
    assert W.DB.get(W.CREW_VARIANT_KEY)["H9646|2026-11-06"]["found"] == "H9646B"
