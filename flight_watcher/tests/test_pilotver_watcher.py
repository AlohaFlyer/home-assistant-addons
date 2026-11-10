"""FW-0069 (1.4.11): other pilots' schedule versions in the Watcher: the capture points (a readable Schedule Lookup,
a lookup FLICA hides with the crew index's rebuild, the end of a crew index run for the pilots Ryan looked up, an
award uploaded later), the pilotver list file and the pilot_schedule attributes, and that nothing raises out of the
check loop. No FLICA page is read for a version. Synthetic data only (made-up pilots and pairings)."""
import json
import os
import re
from datetime import timedelta

import pilotver as PV
import wwwfiles as WF
from test_crew_index import W, _file, _row  # noqa: F401  (W is the watcher fixture)
from test_crew_index_schedules import CM_PAGE, CrewFl
from test_pdfs import AWARD, PKG


class Fl(CrewFl):
    """Pairing pages from CrewFl; Schedule Lookup pages from `cm` (None: FLICA's application error)."""

    def __init__(self, crew=None, cm=CM_PAGE, **kw):
        super().__init__(crew, **kw)
        self.cm = cm

    def fetch(self, url):
        if "cmschedules.cgi" in url:
            self.urls.append(url)
            return self.cm or "<html><p>flica.net - application error initializesessiondata() failed</p></html>"
        return super().fetch(url)


def _last(W, topic="pilot_schedule"):
    return [p for t, p in W.SENT if t == topic][-1]


def _lookup(W, fl, emp="10001", name=""):
    W.S["cm_prompt_captured"] = True
    W.S["pilot_req"] = {"emp": emp, "name": name, "at": ""}
    assert W.pilot_check(fl)


def _run(W, fl):
    W.FLAGS["crew_scan"] = True
    for _ in range(10):
        W.crew_index_check(fl)
        if "crew_run" not in W.S:
            return


def _file_of(W, tmp_path, p):
    path = tmp_path / "www" / f"pilotver_{p['versions_file_key']}.json"
    return json.loads(path.read_text())


def test_a_readable_lookup_is_a_version_and_the_card_gets_its_file(W, tmp_path):
    _file(tmp_path / "www", "2026-11", [_row("H9001", "20", rel=0)])
    fl = Fl()
    _lookup(W, fl)
    v = PV.versions_of(W.DB, "10001", "2026-11")
    assert [(x["ver"], x["source"]) for x in v] == [("11.001", "lookup")]
    assert v[0]["updated"].endswith("Nov 4, 2026 10:00") and v[0]["changes"] == ["first version on file (FLICA schedule)"]
    assert [i["trip"] for i in v[0]["items"]] == ["H3842", "VAC"]
    p = _last(W)
    assert p["versions"] == {"2026-11": {"count": 1, "current": "11.001", "awarded": ""}}
    assert p["versions_file_key"] == W.www_key() and isinstance(p["versions_rev"], int)
    f = _file_of(W, tmp_path, p)
    assert list(f) == ["10001"] and list(f["10001"]["months"]) == ["2026-11"]
    rec = f["10001"]["months"]["2026-11"][0]
    assert "fp" not in rec and "win" not in rec and rec["ver"] == "11.001" and rec["days"][0][1] == "H3842"
    # the same page again: no new version, the same file and rev
    rev = p["versions_rev"]
    _lookup(W, fl)
    assert len(PV.versions_of(W.DB, "10001", "2026-11")) == 1 and _last(W)["versions_rev"] == rev
    assert PV.registered(W.DB) == ["10001"]


def test_a_lookup_flica_hides_takes_the_crew_indexs_rebuild(W, tmp_path):
    _file(tmp_path / "www", "2026-11", [_row("H9001", "20", rel=0)])
    _run(W, Fl({"H9001": "ca 10001 doe, jane fo 10002 roe, rick"}))
    _lookup(W, Fl(cm=None), "10001", "Doe, Jane")
    v = PV.versions_of(W.DB, "10001", "2026-11")
    assert [(x["ver"], x["source"]) for x in v] == [("11.001", "rebuild")]
    assert [(i["trip"], i["start"], i["seat"]) for i in v[0]["items"]] == [("H9001", "2026-11-20", "CA")]
    assert ["2026-11-20", "H9001", "HNL"] in v[0]["days"]  # a turn shows the base, as on the card
    p = _last(W)
    assert p["status"].startswith("not readable") and p["versions"]["2026-11"]["current"] == "11.001"
    assert _file_of(W, tmp_path, p)["10001"]["name"] == "Doe, Jane"


def test_a_crew_index_run_versions_the_looked_up_pilots_only(W, tmp_path):
    _file(tmp_path / "www", "2026-11", [_row("H9001", "20", rel=0), _row("H9002", "24", rel=0)])
    W.pilot_cmd(json.dumps({"emp": "10001", "name": "Doe, Jane"}))  # Ryan looked her up (read on the next check)
    assert PV.registered(W.DB) == ["10001"]
    fl = Fl({"H9001": "ca 10001 doe, jane fo 10002 roe, rick", "H9002": "ca 10003 poe, pat fo 10002 roe, rick"})
    _run(W, fl)
    v = PV.versions_of(W.DB, "10001", "2026-11")
    assert [(x["ver"], x["source"], [i["trip"] for i in x["items"]]) for x in v] == [("11.001", "rebuild", ["H9001"])]
    assert PV.versions_of(W.DB, "10002", "2026-11") == []  # on the crew lists, never looked up
    # the card shows her: a run that finds a new trip of hers republishes the sensor with the new version
    W.pub_pilot({"emp": "10001", "name": "Doe, Jane", "status": "not readable", "month": "", "days": [], "items": []})
    n = len(W.SENT)
    _file(tmp_path / "www", "2026-11", [_row("H9001", "20", rel=0), _row("H9002", "24", rel=0), _row("H9003", "26", rel=0)])
    fl.crew["H9003"] = "ca 10001 doe, jane fo 10002 roe, rick"  # a trip new to the package, read in the next run
    W.TEST_CLOCK["t"] += timedelta(minutes=5)  # 1.7.0 review: the next run is later than the version it builds on
    _run(W, fl)
    v = PV.versions_of(W.DB, "10001", "2026-11")
    assert [x["ver"] for x in v] == ["11.001", "11.002"] and v[1]["changes"] == ["added H9003 Nov 26"]
    assert _last(W)["versions"]["2026-11"] == {"count": 2, "current": "11.002", "awarded": ""}
    assert any(t == "pilot_schedule" for t, _ in W.SENT[n:])
    # a run with nothing new adds nothing
    _run(W, fl)
    assert len(PV.versions_of(W.DB, "10001", "2026-11")) == 2


def test_the_second_pilots_instance_runs_no_crew_index_versions(W, monkeypatch):
    PV.register(W.DB, "10001", "Doe, Jane", "2026-11-09T00:00:00+00:00")
    monkeypatch.setattr(W, "INSTANCE", "james")
    assert W.pilotver_run_end({}) == 0


def test_an_award_uploaded_later_becomes_001(W, tmp_path, monkeypatch):
    _file(tmp_path / "www", "2026-11", [_row("H9001", "20", rel=0)])
    up = tmp_path / "uploads"
    up.mkdir()
    monkeypatch.setattr(W, "UPLOADS", str(up))
    monkeypatch.setattr(W, "seniority_refresh", lambda: None)
    _lookup(W, Fl())  # 11.001: H3842 Nov 1-3, VAC
    W.DB.put("pkg_details:2026-11", __import__("pdfs").package_details(PKG))
    (up / "2026-11_award.txt").write_text(AWARD.replace("00999 / 1234", "00999 / 10001"))
    calls = []
    real = PV.set_award
    monkeypatch.setattr(PV, "set_award", lambda *a, **k: calls.append(a[1]) or real(*a, **k))
    W.uploads_check()  # no own employee number on this test instance: Ryan's own award waits, the pilots' does not
    v = PV.versions_of(W.DB, "10001", "2026-11")
    assert [(x["ver"], x["source"]) for x in v] == [("11.001", "award"), ("11.002", "lookup")]
    assert v[1]["changes"] == ["removed H9001 Nov 2-4 LAX", "added H3842 Nov 1-3 LAX"] or \
        v[1]["changes"] == ["added H3842 Nov 1-3 LAX", "removed H9001 Nov 2-4 LAX"]
    W.uploads_check()  # the same file again: not parsed again
    assert calls == ["10001"]


def test_pilot_versions_never_break_a_lookup_or_a_run(W, tmp_path, monkeypatch):
    _file(tmp_path / "www", "2026-11", [_row("H9001", "20", rel=0)])

    def boom(*a, **k):
        raise RuntimeError("versions broke")

    for f in ("register", "capture_lookup", "capture_rebuild", "history", "summary", "registered", "set_award"):
        monkeypatch.setattr(PV, f, boom)
    W.pilot_cmd(json.dumps({"emp": "10001", "name": "Doe, Jane"}))
    _lookup(W, Fl())
    p = _last(W)
    assert p["status"] == "ok" and [i["trip"] for i in p["items"]][:1] == ["H3842"] and "versions" not in p
    _lookup(W, Fl(cm=None))
    assert _last(W)["status"].startswith("not readable")
    _run(W, Fl({"H9001": "ca 10001 doe, jane fo open"}))
    assert W.S["crew_last"]["ended"] == "ok"
    assert W.pilotver_awards("2026-11", AWARD, {}) == 0


def test_the_pilotver_list_file_is_swept_and_moved_for_a_second_pilot():
    assert "pilotver" in WF.LIST_NAMES and WF.LIST_RE.fullmatch(f"pilotver_{'a' * 32}.json")
    import cards
    src = 'const PILOTVER_URL = "/local/flight-watcher/pilotver_";'
    assert cards.pilot_copy(src, "james") == 'const PILOTVER_URL = "/local/flight-watcher/james/pilotver_";'


def test_the_pilot_schedule_sensor_stays_small_with_a_long_history(W, tmp_path):
    """24 versions and the award in each of 4 months: the sensor carries the short form only (the records are in the
    list file), so it stays far under the 12000 byte cap."""
    _file(tmp_path / "www", "2026-11", [_row("H9001", "20", rel=0)])
    for mi, month in enumerate(("2026-08", "2026-09", "2026-10", "2026-11")):
        for k in range(30):
            items = [{"trip": f"H{3000 + j}", "start": f"{month}-{(j % 27) + 1:02d}", "end": f"{month}-{(j % 27) + 2:02d}",
                      "lay": "LAX"} for j in range(k + 1)]
            PV.capture_lookup(W.DB, "10001", "Doe, Jane", {"month": month, "items": items, "days": [], "updated": ""},
                              f"2026-11-0{mi + 1}T{k % 24:02d}:00:00+00:00")
    W.pub_pilot({"emp": "10001", "name": "Doe, Jane", "status": "ok", "month": "2026-11", "days": [], "items": []})
    p = _last(W)
    assert {m: x["count"] for m, x in p["versions"].items()} == {m: 25 for m in ("2026-08", "2026-09", "2026-10", "2026-11")}
    assert len(json.dumps(p["versions"])) < 400 and len(json.dumps(p)) < 12000
    assert re.fullmatch(r"[0-9a-f]{32}", p["versions_file_key"])
