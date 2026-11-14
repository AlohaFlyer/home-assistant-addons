"""1.7.7 (Ryan, Nov 14): "when it says picked up in flight. I want to know what flight he was flying to be certain. Add
the flight number... i.e AS808/06NOV and date". The in-flight check keeps the leg the picker was airborne on
(inflt_leg: flight, origin, destination, printed local departure, the local departure date at its origin, deadhead);
an in-flight pickup from before 1.7.7 gets its leg from the pairings package with no FLICA load, only when the package
lists the picker's pairing on that start date, else "flight not on file". Synthetic pairings, flights and pilots only
(H3648 and H9101 made up; "Doe, Pat" 10008)."""
import inspect
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import inflt  # noqa: E402
import pdfs  # noqa: E402
import pot  # noqa: E402
from store import Store  # noqa: E402
from test_crew_index import W  # noqa: E402,F401  (the Watcher fixture)
from test_pairing_detail import package  # noqa: E402

HST = timezone(timedelta(hours=-10))
# H3648 from Tue Nov 3 (HST day 0): HNL-LAX Tue, a deadhead LAX-SFO Thu morning, SFO-HNL Thu, HNL-LAS Fri 23:00 (past
# midnight), LAS-HNL Sun 00:30 Pacific (22:30 HST on Saturday: a West Coast origin whose local date is the next day's)
PAGE = ("pairing details h3648:03nov check in: 08:00 dy flt dps-ars dep arr blk "
        "tu 9001 hnl-lax 0900 1600 0500 th dh 1127* lax-sfo 0700 0830 0130 th 9002 sfo-hnl 1100 1430 0530 "
        "fr 808 hnl-las 2300 0650 0550 su 809 las-hnl 0030 0400 0530 crew: ca 10009 doe, john fo 10008 doe, pat")
SCHED = ('<script>function pair(pr){} TAry[TAry.length]=new Task(1, "TU", "03", "H3648", "LAX", "20261103", 1, 0, \'H3648\');'
         '</script> DOE, P (Emp# 10008) Schedule Last Updated: Nov 4')


def _utc(y, mo, d, h, mi):
    """An HST wall time as the UTC ISO text a find's gone_at holds."""
    return datetime(y, mo, d, h, mi, tzinfo=HST).astimezone(timezone.utc).isoformat()


# ---------------------------------------------------------------- the leg from FLICA's pairing page
def test_a_leg_past_midnight_keeps_its_departure_date():
    legs = pot.parse_legs(PAGE, dh=True)
    lg = pot.inflight_leg(legs, "2026-11-03", _utc(2026, 11, 7, 1, 30))  # 01:30 HST Sat, HNL-LAS left 23:00 Fri
    assert (lg["flt"], lg["frm"], lg["to"], lg["dep_l"], lg["dh"]) == ("808", "HNL", "LAS", "23:00", False)
    assert inflt.page_leg(lg, "2026-11-03") == {"flt": "808", "frm": "HNL", "to": "LAS", "dep_l": "23:00",
                                                "date": "2026-11-06", "dh": False, "src": "page"}


def test_a_west_coast_origin_takes_its_own_local_date():
    lg = pot.inflight_leg(pot.parse_legs(PAGE, dh=True), "2026-11-03", _utc(2026, 11, 7, 23, 0))  # 23:00 HST Sat Nov 7
    assert (lg["flt"], lg["frm"], lg["dep_l"]) == ("809", "LAS", "00:30")
    assert pot.leg_local_date("2026-11-03", lg) == "2026-11-08"  # Sunday in Las Vegas, still Saturday in Honolulu
    assert inflt.page_leg(lg, "2026-11-03")["date"] == "2026-11-08"


def test_a_deadhead_is_airborne_and_says_so():
    lg = pot.inflight_leg(pot.parse_legs(PAGE, dh=True), "2026-11-03", _utc(2026, 11, 5, 6, 0))  # 08:00 Pacific
    assert (lg["flt"], lg["frm"], lg["to"], lg["dh"]) == ("1127", "LAX", "SFO", True)
    assert inflt.page_leg(lg, "2026-11-03")["date"] == "2026-11-05"
    # every other reader of the page keeps its legs as before (no deadhead leg, no dh key)
    assert [x["flt"] for x in pot.parse_legs(PAGE)] == ["9001", "9002", "808", "809"]
    assert "dh" not in pot.parse_legs(PAGE)[0]
    # on the ground (Thu 18:00 HST, home between legs) and bad inputs: no leg
    assert pot.inflight_leg(pot.parse_legs(PAGE, dh=True), "2026-11-03", _utc(2026, 11, 5, 18, 0)) is None
    assert pot.inflight_leg([], "bad", "2026-11-05T16:00:00+00:00") is None
    assert pot.inflight_at(pot.parse_legs(PAGE), "bad", "2026-11-05T16:00:00+00:00") is None


class _Fl:
    def __init__(self):
        self.urls = []

    def fetch(self, url):
        self.urls.append(url)
        return SCHED if "cmschedules.cgi" in url else PAGE if "mobilepairing.cgi" in url else "<html>nothing</html>"


def test_the_check_stores_the_leg_with_the_verdict(tmp_path, monkeypatch):
    monkeypatch.setattr(inflt.time, "sleep", lambda s: None)
    db = Store(str(tmp_path / "f.db"))
    db.put("score_email_v", 1)
    gone = _utc(2026, 11, 7, 1, 30)
    db.add_find("H9001|20Nov", "2026-11", {"pairing": "H9001", "open_seats": "FO"}, gone, gone=gone)
    db.set_pickup("H9001|20Nov", {"status": "filled", "by": "FO Doe, Pat (10008)", "ca": "", "known": True, "pickers": ["10008"]})
    fl = _Fl()
    assert inflt.run(fl, db, 3, logging.getLogger("t"), lambda: datetime(2026, 11, 7, 8, 0), "https://x", HST)
    f = db.recent_finds()[0]
    assert f["inflt"] is True and f["inflt_trip"] == "H3648 2026-11-03" and f["inflt_emp"] == "10008"
    assert f["inflt_leg"] == {"flt": "808", "frm": "HNL", "to": "LAS", "dep_l": "23:00", "date": "2026-11-06", "dh": False,
                              "src": "page"}
    assert len(fl.urls) == 2  # the schedule and the one pairing page, as before: no extra load for the leg


# ---------------------------------------------------------------- the backfill from the pairings package
def _verdict(db, key, trip, gone):
    db.add_find(key, "2026-11", {"pairing": key.split("|")[0], "open_seats": "FO"}, gone, gone=gone)
    db.set_pickup(key, {"status": "filled", "by": "FO Doe, Pat (10008)", "ca": "", "known": True, "pickers": ["10008"]})
    db.set_inflt(key, True, trip, tries=1)  # a verdict from before 1.7.7: the pairing, no leg


def test_the_backfill_finds_the_leg_in_the_package_or_says_not_on_file(W, tmp_path, monkeypatch):  # noqa: F811
    www = tmp_path / "www"
    www.mkdir()
    (www / "pairings_2026-11.json").write_text(json.dumps(pdfs.package_json(package(), "synthetic")))
    monkeypatch.setattr(W, "UPLOADS_SHARED", str(tmp_path / "uploads"))
    # H9101 operates Thursdays (Nov 5, 12, 19, 26): HNL-SEA 23:00 Thu, SEA-LAX and DH 1127 LAX-SFO Fri, SFO-HNL Sat
    _verdict(W.DB, "H9201|10Nov", "H9101 2026-11-05", _utc(2026, 11, 6, 0, 30))   # over the Pacific past midnight
    _verdict(W.DB, "H9202|11Nov", "H9101 2026-11-05", _utc(2026, 11, 6, 20, 0))   # on the deadhead LAX-SFO
    _verdict(W.DB, "H9203|12Nov", "H9101 2026-11-06", _utc(2026, 11, 7, 0, 30))   # no H9101 on a Friday: not his trip
    _verdict(W.DB, "H9204|13Nov", "H9101 2026-11-05", _utc(2026, 11, 6, 10, 0))   # the SEA layover: no leg holds it
    _verdict(W.DB, "H9205|14Nov", "H3648 2026-11-03", _utc(2026, 11, 7, 1, 30))   # not in the package at all
    assert not inspect.signature(W.inflt_leg_backfill).parameters  # no FLICA session to load a page with
    assert W.inflt_leg_backfill() == 2
    f = {x["pairing"]: x for x in W.DB.recent_finds()}
    assert f["H9201"]["inflt_leg"] == {"flt": "9001", "frm": "HNL", "to": "SEA", "dep_l": "23:00", "date": "2026-11-05",
                                       "dh": False, "src": "package"}
    assert f["H9202"]["inflt_leg"] == {"flt": "1127", "frm": "LAX", "to": "SFO", "dep_l": "21:50", "date": "2026-11-06",
                                       "dh": True, "src": "package"}
    for p in ("H9203", "H9204", "H9205"):
        assert f[p]["inflt"] is True and f[p]["inflt_leg"] is None, p  # the airplane alone: flight not on file
    assert W.inflt_leg_backfill() == 0  # the misses stay misses; the hits are not looked at again
    assert sorted(k for k, *_ in W.DB.inflt_without_leg()) == ["H9203|12Nov", "H9204|13Nov", "H9205|14Nov"]


def test_the_backfill_reads_the_text_copy_when_the_file_has_no_detail(W, tmp_path, monkeypatch):  # noqa: F811
    www = tmp_path / "www"
    www.mkdir()
    pj = pdfs.package_json(package(), "synthetic")
    pj.pop("detail")  # a pairing file from before the detail (or past its budget)
    (www / "pairings_2026-11.json").write_text(json.dumps(pj))
    up = tmp_path / "uploads"
    up.mkdir()
    (up / "2026-11_pairings.txt").write_text(package())
    monkeypatch.setattr(W, "UPLOADS_SHARED", str(up))
    _verdict(W.DB, "H9201|10Nov", "H9101 2026-11-05", _utc(2026, 11, 6, 0, 30))
    assert W.inflt_leg_backfill() == 1
    assert W.DB.recent_finds()[0]["inflt_leg"]["flt"] == "9001"


def test_package_leg_needs_a_known_station_and_a_trip_day():
    det = {"duties": [{"legs": [["1", "", "9001", "XXX", "SEA", "23:00", "06:42", "5h42"],
                                ["x", "", "9002", "HNL", "SEA", "23:00", "06:42", "5h42"]]}]}
    assert inflt.package_leg(det, "2026-11-05", _utc(2026, 11, 6, 0, 30)) is None
    assert inflt.package_leg(None, "2026-11-05", _utc(2026, 11, 6, 0, 30)) is None
    assert inflt.package_leg({"duties": "x"}, "bad", "x") is None
