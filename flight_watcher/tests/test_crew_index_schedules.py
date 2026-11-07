"""FW-0056..FW-0059 crew index: trips no package lists, the previous bid period, seat codes inside names, a pilot on
two overlapping trips (synthetic data only: made-up names, made-up pairings)."""
import logging
from datetime import datetime, timedelta

import pot
import crewidx as CI
from store import Store
from test_crew_index import W, _file, _row  # noqa: F401  (W is the watcher fixture)


class CrewFl:
    """Fake FLICA pairing pages: crew[(pid, 'YYYYMMDD')] or crew[pid] is the crew line (default: CA Open FO Open),
    legs[pid] the leg text before it; a pid in fail gets a page with no crew line."""

    def __init__(self, crew=None, legs=None, fail=()):
        self.crew, self.legs, self.fail, self.urls = dict(crew or {}), dict(legs or {}), set(fail), []

    def fetch(self, url):
        self.urls.append(url)
        pid = url.split("PID=")[1].split("&")[0]
        d = url.split("DATE=")[1][:8]
        if pid in self.fail:
            return "<html><p>pairing not found</p></html>"
        line = self.crew.get((pid, d)) or self.crew.get(pid) or "ca open fo open"
        return f"<html><p>pairing details {pid.lower()} {self.legs.get(pid, '')} crew: {line}</p></html>"


def _read(fl):
    return [(u.split("PID=")[1].split("&")[0], u.split("DATE=")[1][:8]) for u in fl.urls]


def _last(W, topic):
    return [p for t, p in W.SENT if t == topic][-1]


# ---------------------------------------------------------------- FW-0058: seat codes inside a name
LINE = ("crew: ca 10001 lee, so young ca 10002 doe, fa ann fo 10003 moe, ca jun ro 10004 roe, ro bert "
        "so 10005 so, jane fo open")


def test_seat_codes_inside_names_stay_whole():
    """A seat code counts only where FLICA puts the seat: standing alone, followed by the employee number or Open.
    The same two letters inside a given name (or as a last name) stay part of the name."""
    assert CI.crew_line(LINE) == [
        {"pos": "CA", "name": "Lee, So Young", "emp": "10001"}, {"pos": "CA", "name": "Doe, Fa Ann", "emp": "10002"},
        {"pos": "FO", "name": "Moe, Ca Jun", "emp": "10003"}, {"pos": "RO", "name": "Roe, Ro Bert", "emp": "10004"},
        {"pos": "SO", "name": "So, Jane", "emp": "10005"}, {"pos": "FO", "name": "OPEN", "emp": ""}]
    assert pot.parse_crew(LINE)[:2] == [("CA", "Lee, So Young"), ("CA", "Doe, Fa Ann")]
    assert pot.crew_ids(LINE) == {"Lee, So Young": "10001", "Doe, Fa Ann": "10002", "Moe, Ca Jun": "10003",
                                  "Roe, Ro Bert": "10004", "So, Jane": "10005"}
    assert pot.parse_detail(f"<p>pairing details h9001 {LINE}</p>")["captain"] == "Lee, So Young (10001)"
    # a seat code with neither a number nor Open after it is never a seat
    assert CI.crew_line("crew: fo 10003 doe, fo jane ro open") == [
        {"pos": "FO", "name": "Doe, Fo Jane", "emp": "10003"}, {"pos": "RO", "name": "OPEN", "emp": ""}]
    # the lines that parsed before still parse the same
    assert pot.parse_crew("Crew: CA 10001 SMITH JR, JOHN CA 10002 DOE, JANE FO Open") == [
        ("CA", "Smith Jr, John"), ("CA", "Doe, Jane"), ("FO", "OPEN")]
    assert pot.parse_crew("crew: ca open fo open") == [("CA", "OPEN"), ("FO", "OPEN")]


def test_crew_directory_keeps_whole_names(tmp_path):
    db = Store(str(tmp_path / "d.db"))
    assert db.remember_crew(LINE) == 5
    assert [(r["emp"], r["name"], r["pos"]) for r in db.find_crew("so young")] == [("10001", "Lee, So Young", "CA")]
    assert db.find_crew("10005")[0]["name"] == "So, Jane"


def test_split_suspect():
    cut = [{"pos": "CA", "name": "Lee", "emp": "10001"}, {"pos": "SO", "name": "Young", "emp": ""}]
    assert CI.split_suspect(cut) and CI.split_suspect(cut[1:]) and CI.split_suspect(cut[:1])
    assert not CI.split_suspect(CI.crew_line(LINE))
    assert not CI.split_suspect([{"pos": "CA", "name": "OPEN", "emp": ""}]) and not CI.split_suspect([])


def test_split_repair_rereads_cut_lines_once(W, tmp_path):
    """Lines stored before the fix and cut at a seat code are read again first, once, even a departed trip read after
    it departed (never read again otherwise); a failed re-read keeps the stored line."""
    _file(tmp_path / "www", "2026-11", [_row("H9001", "2", rel=0), _row("H9002", "3", rel=0), _row("H9003", "4", rel=0)])
    cut = [{"pos": "CA", "name": "Lee", "emp": "10001"}, {"pos": "SO", "name": "Young", "emp": ""}]
    whole = [{"pos": "CA", "name": "Doe, Jane", "emp": "10002"}]
    W.DB.crew_put("H9001|2026-11-02", "H9001", "2026-11-02", "2026-11-02", "", cut, "2026-11-03T00:00:00", "ok")
    W.DB.crew_put("H9002|2026-11-03", "H9002", "2026-11-03", "2026-11-03", "", whole, "2026-11-04T00:00:00", "ok")
    W.DB.crew_put("H9003|2026-11-04", "H9003", "2026-11-04", "2026-11-04", "", cut, "2026-11-05T00:00:00", "ok")
    assert W.crew_split_repair() == 2 and W.crew_split_repair() is None
    assert sorted(W.DB.get(W.CREW_REREAD_KEY)) == ["H9001|2026-11-02", "H9003|2026-11-04"]
    W.S["crew_slot"] = W.crew_slot()[0]  # this slot's run is done: only the re-reads are read
    fl = CrewFl({"H9001": "ca 10001 lee, so young fo open"}, fail=("H9003",))
    assert W.crew_index_check(fl) == "ok"
    assert _read(fl) == [("H9001", "20261102"), ("H9003", "20261104")] and "crew_run" not in W.S
    rows = W.DB.crew_rows()
    assert rows["H9001|2026-11-02"]["crew"][0] == {"pos": "CA", "name": "Lee, So Young", "emp": "10001"}
    assert rows["H9003|2026-11-04"]["status"] == "ok" and rows["H9003|2026-11-04"]["crew"] == cut  # last good read kept
    assert W.DB.find_crew("10001")[0]["name"] == "Lee, So Young"
    assert W.DB.get(W.CREW_REREAD_KEY) == {}
    W.crew_index_check(fl)
    assert len(fl.urls) == 2  # one re-read each


# ---------------------------------------------------------------- FW-0056: trips no package lists
def test_own_schedule_trips_not_in_the_package_are_indexed(W, tmp_path):
    """Ryan's own month lists a trade's H3815B (Nov 1) and a later built H3842 (Nov 14): neither is in the package, both
    are read (paced, read only) and found in the pilot lookup; VAC and the package's own trip are not doubled."""
    _file(tmp_path / "www", "2026-11", [_row("H9001", "9", rel=2)])
    W.S["schedule"] = {"2026-11": {"items": [
        {"trip": "H3815B", "start": "2026-11-01", "end": "2026-11-03", "lay": "LAX"},
        {"trip": "H9001", "start": "2026-11-09", "end": "2026-11-11", "lay": ""},
        {"trip": "VAC", "start": "2026-11-20", "end": "2026-11-25", "lay": ""},
        {"trip": "H3842", "start": "2026-11-14", "end": "2026-11-16", "lay": "SFO"}]}}
    fl = CrewFl({"H3815B": "ca 10001 doe, jane fo 10777 poe, pat", "H3842": "ca 10003 moe, mo fo 10777 poe, pat",
                 "H9001": "ca 10004 lee, lou fo 10777 poe, pat"})
    W.crew_index_check(fl)
    assert sorted(_read(fl)) == [("H3815B", "20261101"), ("H3842", "20261114"), ("H9001", "20261109")]
    insts = W.crew_instances()
    it = insts["H3815B|2026-11-01"]
    assert (it["src"], it["period"], it["end_date"], it["days"], it["end_known"]) == ("schedule", "2026-11", "2026-11-03", 3, True)
    assert insts["H9001|2026-11-09"]["src"] == "package" and not any(k.startswith("VAC") for k in insts)
    assert _last(W, "crew_index")["from_schedules"] == 2
    W.pub_pilot({"emp": "10777", "name": "Poe, Pat", "status": "not readable", "month": "", "days": [], "items": []})
    r = _last(W, "pilot_schedule")["reconstructed"]
    assert [(x["pairing"], x["start"], x["end"], x["seat"], x["overlap"]) for x in r] == [
        ("H3815B", "2026-11-01", "2026-11-03", "FO", ""), ("H9001", "2026-11-09", "2026-11-11", "FO", ""),
        ("H3842", "2026-11-14", "2026-11-16", "FO", "")]
    assert "| 2026-11-01 | H3815B | FO |" in (tmp_path / "crew_index" / "2026-11.md").read_text()


CM_PAGE = ('<select><option value="1126" selected>Nov 2026</option></select><script>'
           'TAry[0]=new Task(1, "SU", "01", "H3842", "LAX", "20261101", 1, 0, \'H3842\');'
           'TAry[1]=new Task(1, "MO", "02", "", "-", "20261101", 1, 0, \'\');'
           'TAry[2]=new Task(1, "TU", "03", "", "HNL", "20261101", 1, 0, \'\');'
           'TAry[3]=new Task(1, "WE", "04", "VAC", "", "", 1, 0, \'\');</script>'
           '<p>DOE, JANE (Emp# 10001) Schedule Last Updated: Nov 4, 2026 10:00</p>')


def test_pilot_lookup_and_picker_trips_are_indexed(W, tmp_path, monkeypatch):
    """A pilot lookup's month (H3842 Nov 1-3, not in the package) and a picker's month read for an in-flight check
    (starts only: H3850 Nov 12) are noted; the next run reads them, and the picker trip's end, route and report come
    from its pairing page."""
    _file(tmp_path / "www", "2026-11", [_row("H9001", "20", rel=0)])
    W.S["cm_prompt_captured"] = True
    W.S["pilot_req"] = {"emp": "10001", "name": "", "at": ""}

    class Fl(CrewFl):
        def fetch(self, url):
            return CM_PAGE if "cmschedules.cgi" in url else super().fetch(url)

    fl = Fl({"H3842": "ca 10001 doe, jane fo open", "H3850": "ca 10005 roe, rick fo 10006 poe, pat"},
            legs={"H3850": "check in: 07:30 th 804 hnl-lax 0900 1700 0500 sa 933 lax-hnl 1000 1300 0530"})
    assert W.pilot_check(fl)
    reg = W.DB.get(W.CREW_SCHED_KEY)
    assert reg["H3842|2026-11-01"]["end"] == "2026-11-03" and reg["H3842|2026-11-01"]["src"] == "lookup"
    assert not any(k.startswith("VAC") for k in reg)
    assert W.note_sched_trips([{"trip": "H3850", "start": "2026-11-12"}, {"trip": "x", "start": "2026-11-12"},
                               {"trip": "H3851", "start": "2026-08-01"}], "picker") == 2
    assert "H3851|2026-08-01" not in W.DB.get(W.CREW_SCHED_KEY)  # ended more than CREW_SCHED_KEEP_D days ago
    n0 = len(fl.urls)
    W.crew_index_check(fl)
    assert sorted(_read(fl)[n0:]) == [("H3842", "20261101"), ("H3850", "20261112"), ("H9001", "20261120")]
    it = W.crew_instances()["H3850|2026-11-12"]
    assert (it["end_date"], it["days"], it["route"], it["report"], it["end_known"]) == ("2026-11-14", 3, "HNL-LAX-HNL", "07:30", True)
    row = W.DB.crew_rows()["H3850|2026-11-12"]
    assert (row["status"], row["end_date"], row["route"]) == ("ok", "2026-11-14", "HNL-LAX-HNL")


def test_inflt_passes_picker_months_on(tmp_path, monkeypatch):
    import inflt
    from test_inflt import HST, PAIR, SCHED, FakeFl as IFl, _db
    monkeypatch.setattr(inflt.time, "sleep", lambda s: None)
    db = _db(tmp_path, "2026-11-04T17:00:00+00:00")
    got = []
    assert inflt.run(IFl({"cmschedules.cgi": SCHED, "mobilepairing.cgi": PAIR}), db, 3, logging.getLogger("t"),
                     lambda: datetime(2026, 11, 4, 8, 0), "https://x", HST, on_sched=got.extend)
    assert got == [{"trip": "H3647", "start": "2026-11-01"}, {"trip": "H3648", "start": "2026-11-03"}]


# ---------------------------------------------------------------- FW-0057: the previous bid period
def test_instances_keep_trips_running_into_the_index(tmp_path):
    _file(tmp_path, "2026-10", [_row("H9701", "29", rel=2), _row("H9702", "28", rel=2), _row("H9703", "20", rel=1)])
    ins = CI.instances(str(tmp_path))
    assert set(ins) == {"H9701|2026-10-29"}  # Oct 29-31 runs into Oct 31; Oct 28-30 and Oct 20-21 do not
    assert ins["H9701|2026-10-29"]["period"] == "2026-10" and ins["H9701|2026-10-29"]["release"] == "14:00"


def test_period_for(tmp_path):
    d = str(tmp_path)
    _file(tmp_path, "2026-11", [_row("H9001", "1 2 D1")])
    assert CI.period_for(d, "2026-10-31") == "2026-10" and CI.period_for(d, "2026-11-01") == "2026-11"
    assert CI.period_for(d, "2026-12-01") == "2026-11" and CI.period_for(d, "2026-12-02") == "2026-12"
    _file(tmp_path, "2027-01", [_row("H9002", "31 3")])  # January's period starts Dec 31
    assert CI.period_for(d, "2026-12-31") == "2027-01" and CI.period_for(d, "bad") == "bad"


def test_previous_period_trip_from_the_schedule(W, tmp_path):
    """No October package on file: Ryan's October month (Schedule Lookup) lists H3790 Oct 30 - Nov 1. It runs into
    November's grid (Oct 31 to Dec 1), so it is read and shows in a lookup of November and of October; one that ends
    before the grid is not read."""
    _file(tmp_path / "www", "2026-11", [_row("H9001", "9", rel=2)])
    W.S["schedule"] = {"2026-10": {"items": [
        {"trip": "H3790", "start": "2026-10-30", "end": "2026-11-01", "lay": "SYD"},
        {"trip": "H3780", "start": "2026-10-20", "end": "2026-10-23", "lay": "NRT"}]}}
    fl = CrewFl({"H3790": "ca 10001 doe, jane fo 10777 poe, pat", "H9001": "ca 10002 roe, rick fo 10777 poe, pat"})
    W.crew_index_check(fl)
    assert sorted(_read(fl)) == [("H3790", "20261030"), ("H9001", "20261109")]
    it = W.crew_instances()["H3790|2026-10-30"]
    assert (it["period"], it["month"], it["end_date"]) == ("2026-10", "2026-10", "2026-11-01")
    W.pub_pilot({"emp": "10777", "name": "Poe, Pat", "status": "not readable", "month": "", "days": [], "items": []})
    p = _last(W, "pilot_schedule")
    assert [(x["pairing"], x["start"], x["end"], x["period"]) for x in p["reconstructed"]] == [
        ("H3790", "2026-10-30", "2026-11-01", "2026-10"), ("H9001", "2026-11-09", "2026-11-11", "2026-11")]
    assert p["reconstructed_coverage_pct"] == 100.0  # the October trip counts: it is on the grid's days
    W.pub_pilot({"emp": "10777", "name": "Poe, Pat", "status": "not readable", "month": "2026-10", "days": [], "items": []})
    assert [x["pairing"] for x in _last(W, "pilot_schedule")["reconstructed"]] == ["H3790"]
    assert "| 2026-10-30 | H3790 | FO |" in (tmp_path / "crew_index" / "2026-10.md").read_text()


# ---------------------------------------------------------------- FW-0059: one pilot on two overlapping trips
def test_overlap_rule():
    o = CI.overlap
    assert o(("2026-11-05", "2026-11-07", "", ""), ("2026-11-06", "2026-11-08", "", ""))  # two shared days
    assert o(("2026-11-05", "2026-11-05", "", ""), ("2026-11-05", "2026-11-07", "", ""))  # same start
    assert o(("2026-11-03", "2026-11-07", "", ""), ("2026-11-05", "2026-11-07", "", ""))  # same end
    assert not o(("2026-11-05", "2026-11-07", "", ""), ("2026-11-08", "2026-11-09", "", ""))
    # ends the day the other starts: only when the times say the report is before the release
    assert not o(("2026-11-05", "2026-11-07", "07:00", ""), ("2026-11-07", "2026-11-09", "20:00", ""))
    assert not o(("2026-11-05", "2026-11-07", "07:00", "09:30"), ("2026-11-07", "2026-11-09", "20:00", ""))
    assert o(("2026-11-07", "2026-11-09", "06:00", ""), ("2026-11-05", "2026-11-07", "07:00", "09:30"))


def test_overlap_state():
    ins = {"H9001|2026-11-05": {"date": "2026-11-05", "end_date": "2026-11-07"},
           "H9002|2026-11-06": {"date": "2026-11-06", "end_date": "2026-11-07"},
           "H9003|2026-11-20": {"date": "2026-11-20", "end_date": "2026-11-20"}}
    poe = {"pos": "FO", "name": "Poe, Pat", "emp": "10777"}
    rows = {"H9001|2026-11-05": {"status": "ok", "checked_at": "2026-11-10T00:00:00", "crew": [poe]},
            "H9002|2026-11-06": {"status": "ok", "checked_at": "2026-11-10T01:00:00", "crew": [poe]},
            "H9003|2026-11-20": {"status": "ok", "checked_at": "2026-11-10T02:00:00", "crew": [poe]}}
    found = CI.overlaps(ins, rows)
    fid = "10777|H9001|2026-11-05|H9002|2026-11-06"
    assert found == [{"id": fid, "emp": "10777", "name": "Poe, Pat", "keys": ["H9001|2026-11-05", "H9002|2026-11-06"]}]
    assert CI.overlaps(ins, {**rows, "H9002|2026-11-06": {**rows["H9002|2026-11-06"], "status": "fail"}}) == []
    flags, rr, new, kept, cleared = CI.overlap_update(found, {}, {}, "2026-11-10T03:00:00")
    assert new == [fid] and flags[fid]["state"] == "reread" and sorted(rr) == ["H9001|2026-11-05", "H9002|2026-11-06"]
    m = CI.overlap_marks(flags, rows)["10777"]
    assert m["H9001|2026-11-05"] == {"with": ["H9002 2026-11-06"], "state": "reread"}
    flags2, rr2, new2, kept2, _ = CI.overlap_update(found, flags, {"H9002|2026-11-06": {}}, "x")
    assert (new2, kept2, flags2[fid]["state"]) == ([], [], "reread")  # one still waiting
    flags3, _, _, kept3, _ = CI.overlap_update(found, flags2, {}, "x")
    assert kept3 == [fid] and flags3[fid]["state"] == "kept" and flags3[fid]["found_at"] == "2026-11-10T03:00:00"
    m = CI.overlap_marks(flags3, rows)["10777"]
    assert (m["H9001|2026-11-05"]["state"], m["H9002|2026-11-06"]["state"]) == ("older", "newer")
    assert CI.overlap_update([], flags3, {}, "x")[4] == [fid]  # gone: cleared
    md = CI.render_month("2026-11", {k: {**v, "pairing": k[:5], "month": "2026-11"} for k, v in ins.items()}, rows,
                         "2026-11-10 12:00", flags=flags3)
    assert "| 2026-11-05 | H9001 (overlaps H9002 2026-11-06: older read) | FO |" in md
    assert "| 2026-11-06 | H9002 (overlaps H9001 2026-11-05: newer read kept) | FO |" in md
    assert "| 2026-11-20 | H9003 | FO |" in md and "Overlaps: 1 (a pilot on two trips" in md


def test_queue_puts_rereads_first():
    now = datetime(2026, 11, 10, 12, 0)
    ins = {k: {"key": k, "pairing": k[:5], "date": d, "end_date": d, "report": "08:00", "month": d[:7]}
           for k, d in (("A|2026-11-02", "2026-11-02"), ("B|2026-11-20", "2026-11-20"), ("C|2026-11-25", "2026-11-25"))}
    rows = {"A|2026-11-02": {"status": "ok", "checked_at": "2026-11-03T00:00:00"},  # departed, read after: never again
            "B|2026-11-20": {"status": "ok", "checked_at": "2026-11-10T11:00:00"}}  # read in this run
    assert CI.queue(ins, rows, now, "2026-11-10T10:00:00") == ["C|2026-11-25"]
    assert CI.queue(ins, rows, now, "2026-11-10T10:00:00", {"B|2026-11-20", "A|2026-11-02", "Z|2026-11-01"}) == [
        "A|2026-11-02", "B|2026-11-20", "C|2026-11-25"]


def _overlap_setup(W, tmp_path, monkeypatch):
    clock = [datetime(2026, 11, 2, 12, 5)]

    def tick():  # every read a second later than the one before, as the paced reads are
        clock[0] += timedelta(seconds=1)
        return clock[0]

    monkeypatch.setattr(W, "local_now", tick)
    _file(tmp_path / "www", "2026-11", [_row("H9001", "5", rel=2), _row("H9002", "6", rel=1), _row("H9003", "20", rel=0)])
    fl = CrewFl({"H9001": "ca 10001 doe, jane fo 10777 poe, pat", "H9002": "ca 10002 lee, lou fo 10777 poe, pat",
                 "H9003": "ca 10003 moe, mo fo 10777 poe, pat"})
    W.crew_index_check(fl)  # the slot's run: all three read, Poe on H9001 (Nov 5-7) and H9002 (Nov 6-7)
    assert sorted(_read(fl)) == [("H9001", "20261105"), ("H9002", "20261106"), ("H9003", "20261120")]
    flags = W.DB.get(W.CREW_OVERLAP_KEY)
    assert [(f["emp"], f["state"]) for f in flags.values()] == [("10777", "reread")]
    assert sorted(W.DB.get(W.CREW_REREAD_KEY)) == ["H9001|2026-11-05", "H9002|2026-11-06"]
    assert _last(W, "crew_index")["overlaps"] == 1
    md = (tmp_path / "crew_index" / "2026-11.md").read_text()
    assert "H9001 (overlaps H9002 2026-11-06: re-read queued)" in md and "H9002 (overlaps H9001 2026-11-05: re-read queued)" in md
    W.pub_pilot({"emp": "10777", "name": "Poe, Pat", "status": "not readable", "month": "", "days": [], "items": []})
    r = _last(W, "pilot_schedule")["reconstructed"]
    assert [(x["pairing"], x["overlap"], x["overlap_with"]) for x in r] == [
        ("H9001", "reread", "H9002 2026-11-06"), ("H9002", "reread", "H9001 2026-11-05"), ("H9003", "", "")]
    clock[0] = datetime(2026, 11, 2, 12, 20)
    return clock, fl


def test_overlap_reread_clears_the_flag(W, tmp_path, monkeypatch):
    """The trade is done by the re-read: H9001 names another FO now. Both trips are read again first, in the next
    check (no run going: just those two), the flag clears, and nothing is read again after."""
    clock, fl = _overlap_setup(W, tmp_path, monkeypatch)
    fl.crew["H9001"] = "ca 10001 doe, jane fo 10778 roe, rick"
    n0 = len(fl.urls)
    W.crew_index_check(fl)
    assert _read(fl)[n0:] == [("H9001", "20261105"), ("H9002", "20261106")] and "crew_run" not in W.S
    assert W.DB.get(W.CREW_OVERLAP_KEY) == {} and W.DB.get(W.CREW_REREAD_KEY) == {}
    md = (tmp_path / "crew_index" / "2026-11.md").read_text()
    assert "overlaps" not in md and "Overlaps:" not in md
    W.pub_pilot({"emp": "10777", "name": "Poe, Pat", "status": "not readable", "month": "", "days": [], "items": []})
    assert [(x["pairing"], x["overlap"]) for x in _last(W, "pilot_schedule")["reconstructed"]] == [("H9002", ""), ("H9003", "")]
    clock[0] = datetime(2026, 11, 2, 12, 30)
    W.crew_index_check(fl)
    assert len(fl.urls) == n0 + 2


def test_overlap_still_there_after_the_reread_keeps_the_newer_read(W, tmp_path, monkeypatch):
    """FLICA still lists the pilot on both after the re-read: the flag stays ('kept'), the newer read is the one kept
    (the grid's choice) and the older one says so, and the two are not read again and again."""
    clock, fl = _overlap_setup(W, tmp_path, monkeypatch)
    n0 = len(fl.urls)
    W.crew_index_check(fl)
    assert _read(fl)[n0:] == [("H9001", "20261105"), ("H9002", "20261106")]
    flags = W.DB.get(W.CREW_OVERLAP_KEY)
    assert [f["state"] for f in flags.values()] == ["kept"] and W.DB.get(W.CREW_REREAD_KEY) == {}
    md = (tmp_path / "crew_index" / "2026-11.md").read_text()
    assert "H9001 (overlaps H9002 2026-11-06: older read)" in md and "H9002 (overlaps H9001 2026-11-05: newer read kept)" in md
    W.pub_pilot({"emp": "10777", "name": "Poe, Pat", "status": "not readable", "month": "", "days": [], "items": []})
    r = _last(W, "pilot_schedule")["reconstructed"]
    assert [(x["pairing"], x["overlap"]) for x in r] == [("H9001", "older"), ("H9002", "newer"), ("H9003", "")]
    grid, also = CI.grid_pick(r)
    assert [x["pairing"] for x in grid] == ["H9002", "H9003"] and [x["pairing"] for x in also] == ["H9001"]
    for minute in (30, 40):
        clock[0] = datetime(2026, 11, 2, 12, minute)
        W.crew_index_check(fl)
    assert len(fl.urls) == n0 + 2
    assert _last(W, "crew_index")["overlaps"] == 1 and _last(W, "crew_index")["overlaps_rereading"] == 0


def test_a_trip_gone_from_the_index_is_never_flagged_or_kept(W):
    """FW-0059 review: a stored read of a trip no longer in the index (it ended, or its file left) is never re-read,
    so it must not raise or keep an overlap flag."""
    insts = {"H9001|2026-11-05": {"key": "H9001|2026-11-05", "pairing": "H9001", "date": "2026-11-05",
                                  "end_date": "2026-11-07"}}
    crew = [{"pos": "FO", "name": "Poe, Pat", "emp": "10777"}]
    rows = {"H9001|2026-11-05": {"status": "ok", "crew": crew, "date": "2026-11-05", "end_date": "2026-11-07"},
            "H9002|2026-11-06": {"status": "ok", "crew": crew, "date": "2026-11-06", "end_date": "2026-11-07"}}
    assert W.crew_overlaps(insts, rows) == {} and not W.DB.get(W.CREW_REREAD_KEY)
    insts["H9002|2026-11-06"] = {"key": "H9002|2026-11-06", "pairing": "H9002", "date": "2026-11-06",
                                 "end_date": "2026-11-07"}
    assert [f["state"] for f in W.crew_overlaps(insts, rows).values()] == ["reread"]
    del insts["H9002|2026-11-06"]  # the trip left the index before its re-read: the flag clears, it is not 'kept'
    assert W.crew_overlaps(insts, rows) == {}


def test_a_failed_reread_stays_queued(W, tmp_path, monkeypatch):
    """FW-0059 review: a forced re-read whose fetch fails is not counted as done; it stays queued and the flag does not
    turn 'kept' without a re-read."""
    clock, fl = _overlap_setup(W, tmp_path, monkeypatch)
    real = fl.fetch

    def flaky(url):
        if "PID=H9001" in url:
            fl.urls.append(url)
            raise OSError("timed out")
        return real(url)
    fl.fetch = flaky
    W.crew_index_check(fl)
    assert sorted(W.DB.get(W.CREW_REREAD_KEY)) == ["H9001|2026-11-05"]
    assert [f["state"] for f in W.DB.get(W.CREW_OVERLAP_KEY).values()] == ["reread"]
    fl.fetch = real
    clock[0] = datetime(2026, 11, 2, 12, 30)
    W.crew_index_check(fl)
    assert W.DB.get(W.CREW_REREAD_KEY) == {}
    assert [f["state"] for f in W.DB.get(W.CREW_OVERLAP_KEY).values()] == ["kept"]


def test_a_schedule_end_grows_and_never_shrinks(W):
    """FW-0056 / FW-0065: a trip noted with its end cut short (Nov 9 to Nov 9, the old item builder) takes the later
    end a schedule gives (Nov 12); a later, shorter end does not shrink it. A pilot lookup shows the later end even
    when the stored crew read still has the short one."""
    assert W.note_sched_trips([{"trip": "H9100", "start": "2026-11-09", "end": "2026-11-09"}], "own") == 1
    assert W.note_sched_trips([{"trip": "H9100", "start": "2026-11-09", "end": "2026-11-12"}], "own") == 0
    assert W.DB.get(W.CREW_SCHED_KEY)["H9100|2026-11-09"]["end"] == "2026-11-12"
    W.note_sched_trips([{"trip": "H9100", "start": "2026-11-09", "end": "2026-11-10"}], "lookup")
    assert W.DB.get(W.CREW_SCHED_KEY)["H9100|2026-11-09"]["end"] == "2026-11-12"
    insts = CI.instances(str(W.CARD_PAIRINGS), extra=W.DB.get(W.CREW_SCHED_KEY))
    assert insts["H9100|2026-11-09"]["end_date"] == "2026-11-12"
    r = {"key": "H9100|2026-11-09", "pairing": "H9100", "date": "2026-11-09", "end_date": "2026-11-09", "pos": "FO"}
    got = CI.pilot_trips(insts, [r], start_from="2026-10-31", end_to="2026-11-30")
    assert [(x["start"], x["end"]) for x in got] == [("2026-11-09", "2026-11-12")]


OCT_PAGE = ('<select><option value="1026" selected>Oct 2026</option></select><script>'
            'TAry[0]=new Task(1, "SA", "10", "H3780", "NRT", "20261001", 1, 0, \'H3780\');'
            'TAry[1]=new Task(1, "SU", "11", "", "HNL", "20261001", 1, 0, \'\');'
            'TAry[2]=new Task(1, "TH", "29", "H3790", "SYD", "20261001", 1, 0, \'H3790\');'
            'TAry[3]=new Task(1, "FR", "30", "", "-", "20261001", 1, 0, \'\');'
            'TAry[4]=new Task(1, "SA", "31", "", "-", "20261001", 1, 0, \'\');'
            'TAry[5]=new Task(1, "SU", "01", "", "HNL", "20261101", 1, 0, \'\');</script>'
            '<p>DOE, JANE (Emp# 10001) Schedule Last Updated: Oct 28, 2026 10:00</p>')


def test_pilot_lookup_reads_the_previous_month_when_no_package_lists_it(W, tmp_path):
    """FW-0057 review: no October package on file. A pilot lookup also reads that pilot's October (once, GET only,
    both guards, paced), and the trip that runs into November (H3790 Oct 29 to Nov 1) is noted for the crew index;
    one that ended in October (H3780) is not. With October's package on file, nothing more is read."""
    import submit as SUB
    import swapmap as SM
    _file(tmp_path / "www", "2026-11", [_row("H9001", "20", rel=0)])
    W.S["cm_prompt_captured"] = True

    class Fl(CrewFl):
        def fetch(self, url):
            self.urls.append(url)
            if "cmschedules.cgi" in url:
                return OCT_PAGE if "bd=1026" in url else CM_PAGE
            return super().fetch(url)

    fl = Fl()
    W.S["pilot_req"] = {"emp": "10001", "name": "", "at": ""}
    assert W.pilot_check(fl)
    reg = W.DB.get(W.CREW_SCHED_KEY)
    assert reg["H3790|2026-10-29"]["end"] == "2026-11-01" and "H3780|2026-10-10" not in reg
    prev = [u for u in fl.urls if "bd=1026" in u]
    assert len(prev) == 1 and SUB.safe_get(prev[0]) and SM.safe_get(prev[0])
    assert W.crew_instances()["H3790|2026-10-29"]["period"] == "2026-10"
    assert W.lookup_prev_month(fl, "10001", W.local_now()) == 0 and len([u for u in fl.urls if "bd=1026" in u]) == 1
    _file(tmp_path / "www", "2026-10", [_row("H9701", "29", rel=2)])
    assert W.lookup_prev_month(fl, "10002", W.local_now()) == 0
    assert not any("EmployeeID=10002" in u for u in fl.urls)
