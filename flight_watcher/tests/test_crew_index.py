"""0.10.1 crew index: day mapping, run order and budget, crew lines, Markdown, pilot lookup (synthetic data only)."""
import json
import sys
from datetime import date, datetime, timedelta

import pytest

import crewidx as CI

COLS = ["id", "report", "dep", "release", "rel_days", "first_duty_min", "route", "credit", "tafb", "days", "block", "crew"]


def _file(d, month, rows):
    d.mkdir(parents=True, exist_ok=True)
    (d / f"pairings_{month}.json").write_text(json.dumps({"month": month, "cols": COLS, "rows": rows}))


def _row(pid, days, rel=1, report="07:30", route="HNL-LAX-HNL"):
    return [pid, report, "08:30", "14:00", rel, 300, route, "12:00", "30:30", days, "10:00", ""]


def test_month_dates_plain_and_next_month():
    assert CI.month_dates("2026-11", "2 5 30") == [date(2026, 11, 2), date(2026, 11, 5), date(2026, 11, 30)]
    assert CI.month_dates("2026-11", "29 D1") == [date(2026, 11, 29), date(2026, 12, 1)]
    assert CI.month_dates("2026-11", "28 30 D1 D2") == [date(2026, 11, 28), date(2026, 11, 30), date(2026, 12, 1), date(2026, 12, 2)]


def test_month_dates_previous_month():
    # 31 is larger than November: Oct 31
    assert CI.month_dates("2026-11", "31") == [date(2026, 10, 31)]
    # ahead of a smaller number in bid period order: last month's (also as a D token)
    assert CI.month_dates("2026-11", "31 2 9") == [date(2026, 10, 31), date(2026, 11, 2), date(2026, 11, 9)]
    assert CI.month_dates("2026-11", "D31 4") == [date(2026, 10, 31), date(2026, 11, 4)]
    # a 31 day month whose period starts Dec 31: file level start makes a lone 31 Dec 31, 30 stays January
    lists = [["31", "3"], ["31"], ["30"]]
    pf = CI.file_prev_from("2027-01", lists)
    assert pf == 31
    assert CI.month_dates("2027-01", "31", pf) == [date(2026, 12, 31)]
    assert CI.month_dates("2027-01", "30", pf) == [date(2027, 1, 30)]
    assert CI.file_prev_from("2026-12", [["2", "5"], ["31"]]) is None


def test_instances_from_files(tmp_path):
    _file(tmp_path, "2026-11", [_row("H9001", "31 2 30", rel=2), _row("H9002", "1", rel=0)])
    _file(tmp_path, "2026-10", [_row("H9003", "20 31", rel=1)])
    ins = CI.instances(str(tmp_path))
    # H9003 Oct 20 is before CREW_FROM; Oct 31 appears from both files once
    assert set(ins) == {"H9001|2026-10-31", "H9001|2026-11-02", "H9001|2026-11-30", "H9002|2026-11-01", "H9003|2026-10-31"}
    it = ins["H9001|2026-11-30"]
    assert it["end_date"] == "2026-12-02" and it["days"] == 3 and it["month"] == "2026-11" and it["route"] == "HNL-LAX-HNL"
    assert ins["H9001|2026-10-31"]["month"] == "2026-10"
    assert ins["H9002|2026-11-01"]["end_date"] == "2026-11-01"


def _ins(**kw):
    return {k: {"key": k, "pairing": k.split("|")[0], "date": d, "end_date": d, "report": "08:00", "route": "", "days": 1,
                "month": d[:7]} for k, d in kw.items()}


def test_queue_order():
    now = datetime(2026, 11, 10, 12, 0)
    ins = _ins(**{"A|2026-11-20": "2026-11-20", "B|2026-11-11": "2026-11-11", "C|2026-11-01": "2026-11-01",
                  "D|2026-11-12": "2026-11-12", "E|2026-11-25": "2026-11-25", "F|2026-11-05": "2026-11-05",
                  "G|2026-11-04": "2026-11-04", "H|2026-11-28": "2026-11-28", "I|2026-11-11": "2026-11-11",
                  "J|2026-11-30": "2026-11-30"})
    ok = lambda at: {"status": "ok", "checked_at": at, "tries": 0}
    rows = {
        "D|2026-11-12": ok("2026-11-10T02:00:00"),     # within 72 h, stale (> 6 h)
        "I|2026-11-11": ok("2026-11-10T09:00:00"),     # within 72 h, fresh: skipped
        "E|2026-11-25": ok("2026-11-09T00:00:00"),     # future, older read
        "H|2026-11-28": ok("2026-11-10T00:00:00"),     # future, newer read
        "F|2026-11-05": ok("2026-11-06T00:00:00"),     # departed, read after departure: never again
        "G|2026-11-04": ok("2026-11-03T00:00:00"),     # departed, read before departure: once more
        "J|2026-11-30": {"status": "fail", "checked_at": "2026-11-10T08:00:00", "tries": 1},  # failed today: not again
    }
    q = CI.queue(ins, rows, now)
    assert q == ["C|2026-11-01", "B|2026-11-11", "A|2026-11-20", "D|2026-11-12", "G|2026-11-04", "E|2026-11-25", "H|2026-11-28"]
    rows["J|2026-11-30"]["checked_at"] = "2026-11-09T08:00:00"  # failed over a day ago: retried after the never-checked
    assert CI.queue(ins, rows, now)[3] == "J|2026-11-30"
    # read in this run: not read again
    assert "E|2026-11-25" not in CI.queue(ins, {**rows, "E|2026-11-25": ok("2026-11-10T11:00:00")}, now, "2026-11-10T10:00:00")


CREW_TXT = ("flica.net - mobile pairing pairing details h9001 check in: 07:30 blk : 1000 tafb : 3030 pay : 1200 "
            "crew: ca 10001 doe, jane fo 10002 roe jr, rick ro open")


def test_crew_line():
    assert CI.crew_line(CREW_TXT) == [{"pos": "CA", "name": "Doe, Jane", "emp": "10001"},
                                      {"pos": "FO", "name": "Roe Jr, Rick", "emp": "10002"},
                                      {"pos": "RO", "name": "OPEN", "emp": ""}]
    assert CI.crew_line("nothing here") is None
    # trailing page text after the last name is cut off
    assert CI.crew_line("crew: fo 10003 poe, pat a back to top")[0]["name"] == "Poe, Pat A"


def test_render_month():
    ins = _ins(**{"H9001|2026-11-02": "2026-11-02", "H9002|2026-11-09": "2026-11-09", "H9003|2026-11-12": "2026-11-12"})
    rows = {"H9001|2026-11-02": {"status": "ok", "crew": [{"pos": "CA", "name": "Doe, Jane", "emp": "10001"},
                                                          {"pos": "FO", "name": "Roe, Rick", "emp": "10002"},
                                                          {"pos": "FA", "name": "Moe, Mo", "emp": "20001"}]},
            "H9002|2026-11-09": {"status": "ok", "crew": [{"pos": "FO", "name": "Doe, Jane", "emp": "10001"},
                                                          {"pos": "RO", "name": "OPEN", "emp": ""}]},
            "H9003|2026-11-12": {"status": "fail"}}
    md = CI.render_month("2026-11", ins, rows, "2026-11-10 12:00")
    assert md.startswith("# Crew index 2026-11")
    assert "Coverage 66.7% (2 of 3 trip instances read, 1 failed, 0 with no crew names yet)" in md
    assert md.index("### Doe, Jane (10001)") < md.index("### Roe, Rick (10002)")
    assert "Moe" not in md and "OPEN" not in md
    sec = md.split("### Doe, Jane (10001)")[1].split("###")[0]
    assert "| 2026-11-02 | H9001 | CA |  | 1 |" in sec and "| 2026-11-09 | H9002 | FO |  | 1 |" in sec


# ---------------------------------------------------------------- watcher flow
@pytest.fixture
def W(tmp_path, monkeypatch):
    monkeypatch.setenv("FLIGHT_WATCHER_DATA", str(tmp_path))
    monkeypatch.delenv("FLIGHT_WATCHER_INSTANCE", raising=False)
    (tmp_path / "options.json").write_text(json.dumps({"username": "u", "password": "p"}))
    sys.modules.pop("watcher", None)
    import watcher as W
    from store import Store
    monkeypatch.setattr(W.time, "sleep", lambda s: None)
    monkeypatch.setattr(W, "DB", Store(str(tmp_path / "t.db")))
    monkeypatch.setattr(W, "CARD_PAIRINGS", str(tmp_path / "www"))
    monkeypatch.setattr(W, "CREW_DIR", str(tmp_path / "crew_index"))
    monkeypatch.setattr(W, "local_now", lambda: datetime(2026, 11, 10, 12, 5))
    sent = []
    monkeypatch.setattr(W, "pub", lambda t, p, retain=True: sent.append((t, p)))
    W.S.clear()
    W.S.update(json.loads(json.dumps(W.DEFAULT_STATE)))
    W.SENT = sent
    return W


class FakeFl:
    def __init__(self, fail=(), kind_at=None):
        self.urls, self.fail, self.kind_at = [], fail, kind_at

    def fetch(self, url):
        self.urls.append(url)
        if self.kind_at and len(self.urls) == self.kind_at[0]:
            return self.kind_at[1]
        pid = url.split("PID=")[1].split("&")[0]
        if pid in self.fail:
            return "<html><p>pairing not found</p></html>"
        emp = 10000 + int(pid[1:]) % 1000
        return f"<html><p>pairing {pid} crew: ca {emp} doe, jane fo 10999 roe, rick ro open</p></html>"


def test_run_budget_chunks_and_outputs(W, tmp_path):
    _file(tmp_path / "www", "2026-11", [_row(f"H{9000 + i}", " ".join(str(d) for d in range(1, 31)), rel=0) for i in range(12)])
    # 12 pairings x 30 days = 360 instances; budget 300 per run, 50 per check
    fl = FakeFl(fail=("H9011",))
    assert W.crew_index_check(fl) == "ok"
    assert len(fl.urls) == 50 and W.S["crew_run"]["pages"] == 50 and W.S["crew_slot"] == "2026-11-10T12"
    assert "DATE=20261101" in fl.urls[0]  # soonest first, past dates back to CREW_FROM included
    for _ in range(5):
        W.crew_index_check(fl)
    assert len(fl.urls) == 300 and "crew_run" not in W.S and W.S["crew_last"]["pages"] == 300
    # same slot: no new run until the button
    assert W.crew_index_check(fl) == "ok" and len(fl.urls) == 300
    ci = [p for t, p in W.SENT if t == "crew_index"][-1]
    assert ci["instances"] == 360 and ci["checked"] + ci["failures"] == 300 and ci["pages_last_run"] == 300
    assert ci["next_slot"] == "2026-11-10T18:00:00-10:00"
    md = (tmp_path / "crew_index" / "2026-11.md").read_text()
    assert "### Roe, Rick (10999)" in md and "| 2026-11-01 | H9000 | FO |" in md
    W.FLAGS["crew_scan"] = True
    W.crew_index_check(fl)
    assert len(fl.urls) == 350
    # the 60 never-read instances went first in the second run
    assert all(int(u.split("DATE=")[1][:8]) >= 20261126 for u in fl.urls[300:310])
    # failed instances are not re-read the same day
    assert not [u for u in fl.urls[300:] if "PID=H9011" in u and int(u.split("DATE=")[1][:8]) <= 20261125]
    rows = W.DB.crew_rows()
    assert rows["H9011|2026-11-01"]["status"] == "fail" and "no crew line" in rows["H9011|2026-11-01"]["reason"]


def test_run_ends_on_killed_page(W, tmp_path):
    _file(tmp_path / "www", "2026-11", [_row("H9001", "1 2 3 4 5", rel=0)])
    fl = FakeFl(kind_at=(3, "<html>A new session under this account was detected</html>"))
    assert W.crew_index_check(fl) == "killed"
    assert len(fl.urls) == 3 and "crew_run" not in W.S and W.S["crew_last"]["ended"] == "killed"


def test_pilot_lookup_reconstructed(W, tmp_path):
    _file(tmp_path / "www", "2026-11", [_row("H9001", "2 9", rel=2), _row("H9002", "20", rel=0)])
    W.crew_index_check(FakeFl())
    W.pub_pilot({"emp": "10999", "name": "Roe, Rick", "status": "error: hidden", "month": "", "days": [], "items": []})
    p = [p for t, p in W.SENT if t == "pilot_schedule"][-1]
    assert p["reconstructed_coverage_pct"] == 100.0 and p["reconstructed_month"] == "2026-11"
    assert [(r["pairing"], r["start"], r["end"], r["seat"]) for r in p["reconstructed"]] == [
        ("H9001", "2026-11-02", "2026-11-04", "FO"), ("H9001", "2026-11-09", "2026-11-11", "FO"), ("H9002", "2026-11-20", "2026-11-20", "FO")]
    W.pub_pilot({"emp": "", "name": "x", "status": "no pilot"})
    assert [p for t, p in W.SENT if t == "pilot_schedule"][-1]["reconstructed"] == []


def test_pilot_lookup_rebuilt_grid_fields(W, tmp_path):
    """FW-0002: the rebuilt trips carry what the schedule grid shows (layover, block, credit, soft, crew) and
    span FLICA's grid for the month: the day before the bid period (Oct 31, a trip from October's file) to its
    last day (Dec 1, a 'D1' trip in November's file, as on the live package). Coverage spans the same days."""
    _file(tmp_path / "www", "2026-10", [_row("H9007", "31", rel=2)])
    _file(tmp_path / "www", "2026-11", [_row("H9001", "9 D1", rel=2), _row("H9002", "20", rel=0, route="HNL-OGG-HNL"),
                                        _row("H9003", "15", rel=0)])
    W.crew_index_check(FakeFl(fail=("H9003",)))
    W.DB.put("pkg_details:2026-11", {"H9001": {"block": "9:58", "credit": "12:34", "lay": "LAX"}})
    W.pub_pilot({"emp": "10999", "name": "Roe, Rick", "status": "not readable", "month": "", "days": [], "items": []})
    p = [p for t, p in W.SENT if t == "pilot_schedule"][-1]
    assert (p["reconstructed_from"], p["reconstructed_to"], p["reconstructed_month"]) == ("2026-11-01", "2026-12-01", "2026-11")
    r = p["reconstructed"]
    assert [(x["pairing"], x["start"], x["end"]) for x in r] == [
        ("H9007", "2026-10-31", "2026-11-02"), ("H9001", "2026-11-09", "2026-11-11"), ("H9002", "2026-11-20", "2026-11-20"),
        ("H9001", "2026-12-01", "2026-12-03")]
    assert (r[1]["lay"], r[1]["blk"], r[1]["credit"], r[1]["soft"]) == ("LAX", "9:58", "12:34", "2:36")
    assert r[1]["crew"] == [["CA", "Doe, Jane"], ["FO", "Roe, Rick"], ["RO", "OPEN"]]
    # no package details: credit from the pairing file, no block, layover or soft
    assert (r[2]["lay"], r[2]["blk"], r[2]["credit"], r[2]["soft"]) == ("", "", "12:00", "")
    # Oct 31 to Dec 1: 4 of 5 instances read (H9003 failed); the calendar month alone would say 2 of 3
    assert p["reconstructed_coverage_pct"] == 80.0
    # November's D1 ends its period on Dec 1, so December's starts on Dec 2 (its grid's first row is Dec 1)
    www = str(tmp_path / "www")
    assert CI.period_start(www, "2026-12") == "2026-12-02" and CI.period_end(www, "2026-12") == "2026-12-31"
    assert CI.grid_range(www, "2026-12") == ("2026-12-01", "2026-12-02", "2026-12-31")
    assert CI.period_start(www, "2027-02") == "2027-02-01"  # no files: the 1st


def test_period_bounds(tmp_path):
    """FW-0002: bid period ends from the pairing files: a D day in this month's file, else the day before the
    next month's period start (a last-month day in its file), else the month's last day."""
    d = tmp_path / "www"
    _file(d, "2026-11", [_row("H9001", "1 2 30 D1"), _row("H9002", "D31 4")])  # D31 ahead of 4 is Oct 31, not Dec 31
    _file(d, "2027-01", [_row("H9003", "31 3")])  # January's period starts Dec 31
    assert CI.period_end(str(d), "2026-11") == "2026-12-01"
    assert CI.period_start(str(d), "2026-11") == "2026-10-31"
    assert CI.period_end(str(d), "2026-12") == "2026-12-30" and CI.period_start(str(d), "2026-12") == "2026-12-02"
    assert CI.period_start(str(d), "2027-01") == "2026-12-31" and CI.period_end(str(d), "2027-01") == "2027-01-31"
    assert CI.file_next_to("2026-11", [["D31", "4"]]) is None
    ins = CI.instances(str(d))
    rows = {k: {"status": "ok"} for k in ins if k.startswith("H9001|")}
    # 1 2 30 D1 and Oct 31 / Nov 4: the range counts by date, whatever file or month the instance has
    assert CI.coverage(ins, rows, None, "2026-10-31", "2026-12-01")[:2] == (6, 4)
    assert CI.coverage(ins, rows, "2026-11")[:2] == (4, 3)


def test_pilot_instance_skips_crew_index(W, tmp_path, monkeypatch):
    monkeypatch.setattr(W, "INSTANCE", "james")
    _file(tmp_path / "www", "2026-11", [_row("H9001", "2", rel=0)])
    fl = FakeFl()
    assert W.crew_index_check(fl) == "ok" and fl.urls == []


def test_rebuilt_keeps_a_trip_running_into_the_grid():
    """1.3.0 review: a trip that starts before the grid (Nov 30) and runs into December's period is kept, as on
    FLICA's own grid; one that ends before the grid is not."""
    insts = {"a": {"date": "2026-11-30", "end_date": "2026-12-03", "pairing": "H9120"},
             "b": {"date": "2026-11-27", "end_date": "2026-11-29", "pairing": "H9121"},
             "c": {"date": "2026-12-10", "end_date": "2026-12-12", "pairing": "H9201"}}
    rows = [{"key": k, "pos": "FO"} for k in insts]
    got = CI.pilot_trips(insts, rows, start_from="2026-12-01", end_to="2026-12-31")
    assert [(x["pairing"], x["start"], x["end"]) for x in got] == [
        ("H9120", "2026-11-30", "2026-12-03"), ("H9201", "2026-12-10", "2026-12-12")]


# ---------------------------------------------------------------- FW-0017: FLICA's CKP check pilot tag
CKP_TXT = "pairing h9001 crew: ca 10001 doe jr, ckp jane ca 10002 roe, rick fo open"


def test_ckp_tag_out_of_names():
    import pot
    assert CI.crew_line(CKP_TXT) == [{"pos": "CA", "name": "Doe Jr, Jane", "emp": "10001", "ckp": True},
                                     {"pos": "CA", "name": "Roe, Rick", "emp": "10002"},
                                     {"pos": "FO", "name": "OPEN", "emp": ""}]
    assert CI.crew_line("crew: fo 10003 poe, ckp pat a back to top")[0] == {"pos": "FO", "name": "Poe, Pat A", "emp": "10003", "ckp": True}
    assert pot.parse_crew(CKP_TXT) == [("CA", "Doe Jr, Jane"), ("CA", "Roe, Rick"), ("FO", "OPEN")]
    assert pot.crew_ids(CKP_TXT) == {"Doe Jr, Jane": "10001", "Roe, Rick": "10002"}
    assert pot.parse_detail(f"<html><p>{CKP_TXT}</p></html>")["captain"] == "Doe Jr, Jane (10001)"
    assert pot.clean_name("DOE, CKP JANE") == ("DOE, JANE", True) and pot.clean_name("Ckpson, Jane") == ("Ckpson, Jane", False)
    assert pot.clean_name("Ckp Doe, Jane") == ("Doe, Jane", True) and pot.clean_name("Doe,Ckp Jane") == ("Doe, Jane", True)
    # a pot roster stored with the tag is the same crew as the page read without it
    assert pot.pickup_diff([("CA", "Doe, Ckp Jane"), ("FO", "OPEN")], [("CA", "Doe, Jane"), ("FO", "OPEN")])[0] == "open"
    assert pot.pickup_diff([("FO", "Doe, Ckp Jane")], [("FO", "Doe, Jane")])[0] == "unchanged"


def test_crew_dir_merges_ckp_forms(tmp_path):
    """FW-0017: 'Doe, Ckp Jane' and 'Doe, Jane' are one person in the directory, the index and the pickers; the
    one-shot repair (Store.crew_fix) cleans what was stored before. FW-0016: it also sets a stored 'ok' read
    whose crew names no pilot to 'empty'."""
    from store import Store
    db = Store(str(tmp_path / "t.db"))
    assert db.remember_crew(CKP_TXT) == 2
    db.remember_crew("crew: ca 10001 doe jr, jane")
    assert db.find_crew("doe jane") == [{"emp": "10001", "name": "Doe Jr, Jane", "pos": "CA"}]
    db.remember_person("10004", "Moe, Ckp Max", "FO")
    assert db.find_crew("10004")[0]["name"] == "Moe, Max"
    # rows as an earlier version stored them
    with db.lock:
        db.db.execute("UPDATE crew_dir SET name='Doe Jr, Ckp Jane' WHERE emp='10001'")
        db.db.execute("INSERT INTO pickers(emp,name,pos,n,total_s,last_at) VALUES('10002','Roe, Ckp Rick','FO',1,60,'x')")
    db.crew_put("H9001|2026-11-02", "H9001", "2026-11-02", "2026-11-02", "", [
        {"pos": "CA", "name": "Doe Jr, Ckp Jane", "emp": "10001"}, {"pos": "FO", "name": "OPEN", "emp": ""}],
        "2026-11-01T10:00:00", "ok")
    db.crew_put("H9101|2026-12-03", "H9101", "2026-12-03", "2026-12-03", "", [], "2026-11-01T10:00:05", "ok")
    db.crew_put("H9102|2026-12-04", "H9102", "2026-12-04", "2026-12-04", "", [{"pos": "FO", "name": "OPEN", "emp": ""}],
                "2026-11-01T10:00:09", "ok")
    # the finds history: a captain, the pot roster and a pickup stored with the tag (the finds card shows them)
    db.add_find("H3601|20Nov", "2026-11", {"pairing": "H3601", "captain": "Doe Jr, Ckp Jane (10001)",
                                           "crew": [["CA", "Doe Jr, Ckp Jane"], ["FO", "OPEN"]]}, "2026-11-02T01:00:00+00:00")
    db.set_pickup("H3601|20Nov", {"status": "filled", "ca": "Doe Jr, Ckp Jane (10001)",
                                  "by": "FO Roe, Ckp Rick (10002); RO Moe, Max (10004)", "known": False})
    db.add_find("H3602|21Nov", "2026-11", {"pairing": "H3602", "captain": "Poe, Pat (10005)"}, "2026-11-02T02:00:00+00:00")
    # crew_dir, crew_emp, pickers, the crew line; the find's captain, roster, ca and by; two pre-award reads
    assert db.crew_fix(CI.has_crew) == (8, 2)
    assert db.find_crew("doe")[0]["name"] == "Doe Jr, Jane" and db.picker_stats()["10002"]["name"] == "Roe, Rick"
    assert db.crew_by_emp("10001")[0]["name"] == "Doe Jr, Jane"
    rows = db.crew_rows()
    assert rows["H9001|2026-11-02"]["crew"][0] == {"pos": "CA", "name": "Doe Jr, Jane", "emp": "10001", "ckp": True}
    assert rows["H9001|2026-11-02"]["status"] == "ok"
    assert rows["H9101|2026-12-03"]["status"] == "empty" and rows["H9102|2026-12-04"]["status"] == "empty"
    assert rows["H9101|2026-12-03"]["checked_at"] == "2026-11-01T10:00:05"
    f = {x["pairing"]: x for x in db.recent_finds()}
    assert f["H3601"]["captain"] == "Doe Jr, Jane (10001)" and f["H3601"]["picked_by"] == "FO Roe, Rick (10002); RO Moe, Max (10004)"
    assert db.find_row("H3601|20Nov")["crew"] == [["CA", "Doe Jr, Jane"], ["FO", "OPEN"]]
    assert f["H3602"]["captain"] == "Poe, Pat (10005)"
    assert db.crew_fix(CI.has_crew) == (0, 0)  # nothing left to repair


def test_crew_fix_by_bid_period(tmp_path):
    """FW-0016 review: the one-shot repair sets an 'ok' read naming no pilot to 'empty' only in a bid period no
    read of which names a pilot (December before its award), and only for a trip not yet started. November is
    awarded: its open-time trips ('CA Open FO Open', past and future) stay read. A Dec 1 trip is November's."""
    from store import Store
    db = Store(str(tmp_path / "t.db"))
    named = [{"pos": "CA", "name": "Doe, Jane", "emp": "10001"}, {"pos": "FO", "name": "Roe, Rick", "emp": "10002"}]
    open_ = [{"pos": "CA", "name": "OPEN", "emp": ""}, {"pos": "FO", "name": "OPEN", "emp": ""}]
    put = lambda k, crew: db.crew_put(k, k[:5], k[6:], k[6:], "", crew, "2026-11-01T10:00:00", "ok")
    put("H9001|2026-11-02", named)
    put("H9002|2026-11-03", open_)    # November, departed, open time
    put("H9003|2026-11-20", open_)    # November, future, open time
    put("H9004|2026-12-01", named)    # November's period (D1)
    put("H9101|2026-12-03", open_)    # December before the award
    put("H9102|2026-11-05", open_)    # a departed trip of a period with no names (made up): left alone
    periods = {"H9001|2026-11-02": "2026-11", "H9002|2026-11-03": "2026-11", "H9003|2026-11-20": "2026-11",
               "H9004|2026-12-01": "2026-11", "H9101|2026-12-03": "2026-12", "H9102|2026-11-05": "2026-12"}
    assert db.crew_fix(CI.has_crew, periods, "2026-11-06") == (0, 1)
    st = {k: r["status"] for k, r in db.crew_rows().items()}
    assert st == {"H9001|2026-11-02": "ok", "H9002|2026-11-03": "ok", "H9003|2026-11-20": "ok", "H9004|2026-12-01": "ok",
                  "H9101|2026-12-03": "empty", "H9102|2026-11-05": "ok"}
    # without the periods, Dec 1's names would count for December (its calendar month): nothing to repair there
    db2 = Store(str(tmp_path / "t2.db"))
    db2.crew_put("H9004|2026-12-01", "H9004", "2026-12-01", "2026-12-01", "", named, "2026-11-01T10:00:00", "ok")
    db2.crew_put("H9101|2026-12-03", "H9101", "2026-12-03", "2026-12-03", "", open_, "2026-11-01T10:00:00", "ok")
    assert db2.crew_fix(CI.has_crew, {}, "2026-11-06") == (0, 0)


# ---------------------------------------------------------------- FW-0016: pages read before the award
def test_has_crew():
    assert not CI.has_crew([]) and not CI.has_crew(None)
    assert not CI.has_crew([{"pos": "CA", "name": "OPEN", "emp": ""}, {"pos": "FA", "name": "Moe, Mo", "emp": "20001"}])
    assert CI.has_crew([{"pos": "FO", "name": "Doe, Jane", "emp": "10001"}])


def _per(**kw):
    """Instances like _ins, with the bid period they came from: key=(date, period)."""
    return {k: {"key": k, "pairing": k.split("|")[0], "date": d, "end_date": d, "report": "08:00", "route": "",
                "days": 1, "month": d[:7], "period": p} for k, (d, p) in kw.items()}


NAMED = [{"pos": "CA", "name": "Doe, Jane", "emp": "10001"}, {"pos": "FO", "name": "Roe, Rick", "emp": "10002"}]
OPEN2 = [{"pos": "CA", "name": "OPEN", "emp": ""}, {"pos": "FO", "name": "OPEN", "emp": ""}]
_empty = lambda at, tries=1: {"status": "empty", "checked_at": at, "tries": tries, "crew": []}
_ok = lambda at, crew=NAMED: {"status": "ok", "checked_at": at, "tries": 0, "crew": crew}


def test_held_period_gets_one_probe_a_run():
    now = datetime(2026, 11, 10, 12, 0)
    ins = _per(**{"A|2026-12-03": ("2026-12-03", "2026-12"), "B|2026-12-04": ("2026-12-04", "2026-12"),
                  "C|2026-12-05": ("2026-12-05", "2026-12"), "D|2026-12-06": ("2026-12-06", "2026-12"),
                  "E|2026-12-07": ("2026-12-07", "2026-12"), "N|2026-11-20": ("2026-11-20", "2026-11"),
                  "M|2026-12-01": ("2026-12-01", "2026-11")})
    rows = {"B|2026-12-04": _empty("2026-11-10T06:00:01"), "C|2026-12-05": _empty("2026-11-10T06:00:04"),
            "D|2026-12-06": _empty("2026-11-10T06:00:07"), "M|2026-12-01": _ok("2026-11-10T06:00:10")}
    # December: 3 reads, none naming a pilot: held. M (Dec 1) names crew: November's period is awarded.
    assert CI.awarded_periods(ins, rows) == {"2026-11"} and CI.held_periods(ins, rows) == {"2026-12"}
    q = CI.queue(ins, rows, now, "2026-11-10T12:00:00")
    assert q == ["A|2026-12-03", "N|2026-11-20", "M|2026-12-01"]  # one probe (never read, soonest), then the rest
    # December had its read in this run: no second probe
    rows2 = {**rows, "A|2026-12-03": _empty("2026-11-10T12:00:30")}
    assert CI.queue(ins, rows2, now, "2026-11-10T12:00:00") == ["N|2026-11-20", "M|2026-12-01"]
    # fewer than HOLD_AFTER empty reads do not hold a period; empties are read again after FAIL_RETRY_H
    few = {k: v for k, v in rows.items() if k != "D|2026-12-06"}
    assert CI.held_periods(ins, few) == set()
    assert CI.queue(ins, few, now, "2026-11-10T12:00:00")[:4] == ["N|2026-11-20", "A|2026-12-03", "D|2026-12-06", "E|2026-12-07"]
    assert "B|2026-12-04" not in CI.queue(ins, few, now) and "B|2026-12-04" in CI.queue(ins, few, datetime(2026, 11, 11, 7, 0))
    # the probe names crew: December is awarded, never held again, and its pages read before go first
    rows3 = {**rows, "A|2026-12-03": _ok("2026-11-10T12:00:30")}
    assert CI.held_periods(ins, rows3) == set() and CI.awarded_periods(ins, rows3) == {"2026-11", "2026-12"}
    assert CI.queue(ins, rows3, now, "2026-11-10T12:00:00") == [
        "N|2026-11-20", "B|2026-12-04", "C|2026-12-05", "D|2026-12-06", "E|2026-12-07", "M|2026-12-01"]
    # coverage counts only reads with crew; the Markdown says the period waits for the award
    assert CI.coverage(ins, rows, "2026-12")[:2] == (6, 1)
    md = CI.render_month("2026-12", ins, rows, "2026-11-10 12:00")
    assert "(1 of 6 trip instances read, 0 failed, 3 with no crew names yet)" in md
    assert "Waiting for the award: the 2026-12 bid period" in md
    assert "Waiting for the award" not in CI.render_month("2026-12", ins, rows3, "2026-11-10 12:00")


def test_held_probe_moves_through_the_period():
    """FW-0016 review: the probe is not always the soonest trip (an open one would pin it): never read first,
    soonest, then the one checked longest ago; a departed trip is never the probe."""
    ins = _per(**{f"{c}|2026-12-0{d}": (f"2026-12-0{d}", "2026-12") for c, d in zip("ABCDE", range(3, 8))})
    ins.update(_per(**{"P|2026-11-08": ("2026-11-08", "2026-12")}))  # made up: departed, never read
    rows = {"B|2026-12-04": _empty("2026-11-10T06:00:01"), "C|2026-12-05": _empty("2026-11-10T06:00:04"),
            "D|2026-12-06": _empty("2026-11-10T06:00:07")}
    probes, now = [], datetime(2026, 11, 10, 12, 0)
    for run in range(7):
        q = CI.queue(ins, rows, now, now.isoformat())
        assert len(q) == 1  # one page of the held period per run, nothing else
        probes.append(q[0].split("|")[0])
        rows[q[0]] = _empty((now + timedelta(seconds=30)).isoformat())
        now += timedelta(hours=6)
    assert probes == ["A", "E", "B", "C", "D", "A", "E"]


def test_awarded_period_with_open_trips_is_never_held():
    """FW-0016 review: after the award, open-time trips ('CA Open FO Open') name no pilot either. A period with
    a read naming a pilot is never held, however many such reads it has (past and future, 'ok' as the repair
    leaves them or 'empty' as a read before the award was seen stores them), and its assigned trips still get
    their 72 h (2), after-departure (2b) and oldest-checked (3) reads. An 'empty' read of a trip after it
    departed is final (no 24 h retries)."""
    now = datetime(2026, 11, 10, 12, 0)
    ins = _per(**{f"H9001|2026-11-{d:02d}": (f"2026-11-{d:02d}", "2026-11") for d in range(5, 31)})  # 26 assigned
    ins.update(_per(**{"O1|2026-11-02": ("2026-11-02", "2026-11"), "O2|2026-11-03": ("2026-11-03", "2026-11"),
                       "O3|2026-11-12": ("2026-11-12", "2026-11"), "O4|2026-11-25": ("2026-11-25", "2026-11")}))
    rows = {k: _ok("2026-11-09T00:00:00") for k in ins if k.startswith("H9001")}
    for opened in ({k: _ok("2026-11-09T00:00:00", OPEN2) for k in ("O1|2026-11-02", "O2|2026-11-03", "O3|2026-11-12",
                                                                     "O4|2026-11-25")},
                   {k: _empty("2026-11-09T00:00:00", 0) for k in ("O1|2026-11-02", "O2|2026-11-03", "O3|2026-11-12",
                                                                   "O4|2026-11-25")}):
        r = {**rows, **opened}
        assert CI.held_periods(ins, r) == set()
        q = CI.queue(ins, r, now, "2026-11-10T12:00:00")
        assigned = [k.split("|")[1][-2:] for k in q if k.startswith("H9001")]
        assert assigned[:5] == ["11", "12", "13", "09", "10"] and assigned[5:] == [f"{d}" for d in range(14, 31)]
        assert "O1|2026-11-02" not in q and "O2|2026-11-03" not in q  # read after departure: final
        if opened["O3|2026-11-12"]["status"] == "ok":  # an open trip read after the award: refreshed like the rest
            assert q.index("O3|2026-11-12") == 2 and q.index("O4|2026-11-25") > q.index("H9001|2026-11-24")
        else:  # read before the award was seen: read again first
            assert q[:2] == ["O3|2026-11-12", "O4|2026-11-25"]
        # days later, still no retry of the departed ones
        later = CI.queue(ins, r, datetime(2026, 11, 14, 12, 0))
        assert "O1|2026-11-02" not in later and "O2|2026-11-03" not in later
    # an 'empty' read taken before departure gets one more read after it (the final crew), then none
    pre = {**rows, "O3|2026-11-12": _empty("2026-11-11T00:00:00")}
    assert "O3|2026-11-12" in CI.queue(ins, pre, datetime(2026, 11, 12, 12, 0))
    pre["O3|2026-11-12"] = _empty("2026-11-12T12:00:00", 2)
    assert "O3|2026-11-12" not in CI.queue(ins, pre, datetime(2026, 11, 14, 12, 0))


class AwardFl(FakeFl):
    """FakeFl whose December-period pairings (H91xx) list nobody until award is set; pairings in open (open
    time, after the award too) always read 'CA Open FO Open'."""
    award = False

    def __init__(self, open_=(), **kw):
        super().__init__(**kw)
        self.open = open_

    def fetch(self, url):
        pid = url.split("PID=")[1].split("&")[0]
        if pid in self.open or (pid.startswith("H91") and not self.award):
            self.urls.append(url)
            return f"<html><p>pairing {pid} crew: ca open fo open</p></html>"
        return super().fetch(url)


def test_crawl_holds_a_period_until_the_award(W, tmp_path, monkeypatch):
    """FW-0016 on Pako: December's pages were read before the award and counted done (247 of 681, only Dec 1
    with crew). Now three pages naming nobody, in a period no page of which has named anyone, hold the period;
    one page is read per run (a different one each run) until names appear, and then the pages read empty are
    read first again, in the same run. Open time (H9150, 'CA Open FO Open' after the award too) neither holds
    the period nor pins the probe."""
    clock = [datetime(2026, 11, 10, 12, 5)]
    monkeypatch.setattr(W, "local_now", lambda: clock[0])
    _file(tmp_path / "www", "2026-11", [_row("H9001", "2 3 D1", rel=0)])
    _file(tmp_path / "www", "2026-12", [_row("H9150", "2 3 4", rel=0), _row("H9101", "5 6 7 8 9 10", rel=0),
                                        _row("H9102", "12 13", rel=0)])
    fl = AwardFl(open_=("H9150",))
    W.crew_index_check(fl)
    dec = lambda urls: [u.split("DATE=")[1][:8] for u in urls if "PID=H91" in u]
    assert dec(fl.urls) == ["20261202", "20261203", "20261204"]  # held after 3: the other 8 are not loaded
    assert len(fl.urls) == 6 and "crew_run" not in W.S  # Nov 2, Nov 3, Dec 1 (November's period) and the 3
    ci = [p for t, p in W.SENT if t == "crew_index"][-1]
    assert (ci["instances"], ci["checked"], ci["no_crew_yet"], ci["waiting_for_award"]) == (14, 3, 3, ["2026-12"])
    assert ci["coverage_pct"] == 21.4
    assert "Waiting for the award: the 2026-12 bid period" in (tmp_path / "crew_index" / "2026-12.md").read_text()
    # next slots, award still not out: one probe a run, never read first (not the open trip of Dec 2 again)
    for hour, want in ((18, "20261205"), (24, "20261206")):
        clock[0] = datetime(2026, 11, 10, 0, 5) + timedelta(hours=hour)
        n0 = len(fl.urls)
        W.crew_index_check(fl)
        assert dec(fl.urls[n0:]) == [want]
    # award out: the probe names crew and the run goes on to read the rest of December in the next check
    fl.award = True
    clock[0] = datetime(2026, 11, 11, 6, 5)
    n0 = len(fl.urls)
    W.crew_index_check(fl)
    assert dec(fl.urls[n0:]) == ["20261207"] and "crew_run" in W.S
    clock[0] = datetime(2026, 11, 11, 6, 10)
    W.crew_index_check(fl)
    assert sorted(dec(fl.urls[n0:])) == ["20261202", "20261203", "20261204", "20261205", "20261206", "20261207",
                                         "20261208", "20261209", "20261210", "20261212", "20261213"]
    ci = [p for t, p in W.SENT if t == "crew_index"][-1]
    assert (ci["checked"], ci["coverage_pct"], ci["no_crew_yet"], ci["waiting_for_award"]) == (14, 100.0, 0, [])
    rows = W.DB.crew_rows()  # the open trip is read (open time), as any page of an awarded period
    assert rows["H9150|2026-12-02"]["status"] == "ok" and rows["H9150|2026-12-02"]["crew"] == OPEN2


def test_crawl_awarded_period_with_open_trips(W, tmp_path, monkeypatch):
    """FW-0016 review, as on Pako: November is awarded (26 instances name crew) and has fully open trips, two
    departed (Nov 2, 3) and one ahead (Nov 12), stored 'ok' by the version before. The one-shot repair leaves
    them read, and the next run reads the usual refresh: no hold, the departed open trips are not read again,
    and a never-read open trip (Nov 20) is stored as read."""
    monkeypatch.setattr(W, "local_now", lambda: datetime(2026, 11, 10, 12, 5))
    _file(tmp_path / "www", "2026-11", [_row("H9001", " ".join(str(d) for d in range(5, 31)), rel=0),
                                        _row("H9501", "2 3 12", rel=0), _row("H9502", "20", rel=0)])
    insts = CI.instances(str(tmp_path / "www"))
    for k, it in insts.items():
        if k != "H9502|2026-11-20":
            W.DB.crew_put(k, it["pairing"], it["date"], it["end_date"], it["route"],
                          OPEN2 if it["pairing"] == "H9501" else NAMED, "2026-11-09T00:00:00", "ok")
    periods = {k: CI.period_of(it) for k, it in insts.items()}
    assert W.DB.crew_fix(CI.has_crew, periods, "2026-11-10") == (0, 0)
    fl = AwardFl(open_=("H9501", "H9502"))
    W.crew_index_check(fl)
    got = [(u.split("PID=")[1][:5], u.split("DATE=")[1][6:8]) for u in fl.urls]
    # never read (H9502), within 72 h and stale (11, 12, 12 open, 13), read before departure (9, 10), the rest
    assert got == ([("H9502", "20"), ("H9001", "11"), ("H9001", "12"), ("H9501", "12"), ("H9001", "13"),
                    ("H9001", "09"), ("H9001", "10")] + [("H9001", f"{d}") for d in range(14, 31)])
    ci = [p for t, p in W.SENT if t == "crew_index"][-1]
    assert (ci["instances"], ci["checked"], ci["coverage_pct"], ci["no_crew_yet"], ci["waiting_for_award"]) == (
        30, 30, 100.0, 0, [])
    rows = W.DB.crew_rows()
    assert rows["H9502|2026-11-20"]["status"] == "ok" and rows["H9501|2026-11-12"]["status"] == "ok"
