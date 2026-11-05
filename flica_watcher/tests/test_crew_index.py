"""0.10.1 crew index: day mapping, run order and budget, crew lines, Markdown, pilot lookup (synthetic data only)."""
import json
import sys
from datetime import date, datetime

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
    assert "Coverage 66.7% (2 of 3 trip instances read, 1 failed)" in md
    assert md.index("### Doe, Jane (10001)") < md.index("### Roe, Rick (10002)")
    assert "Moe" not in md and "OPEN" not in md
    sec = md.split("### Doe, Jane (10001)")[1].split("###")[0]
    assert "| 2026-11-02 | H9001 | CA |  | 1 |" in sec and "| 2026-11-09 | H9002 | FO |  | 1 |" in sec


# ---------------------------------------------------------------- watcher flow
@pytest.fixture
def W(tmp_path, monkeypatch):
    monkeypatch.setenv("FLICA_DATA", str(tmp_path))
    monkeypatch.delenv("FLICA_INSTANCE", raising=False)
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


def test_pilot_instance_skips_crew_index(W, tmp_path, monkeypatch):
    monkeypatch.setattr(W, "INSTANCE", "james")
    _file(tmp_path / "www", "2026-11", [_row("H9001", "2", rel=0)])
    fl = FakeFl()
    assert W.crew_index_check(fl) == "ok" and fl.urls == []
