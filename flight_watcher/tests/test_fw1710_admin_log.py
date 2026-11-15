"""1.7.10 (Ryan, Nov 15): Ryan's own Watcher log carries no crew name and no employee number. Before, the admin's log
named the captain in the pairing detail probe ("detail probe H3601: captain='...(...)'"), quoted a pairing page's
crew list ("detail text H3601: ... crew: ca 99999 doe, ..."), started every Schedule Lookup line with the employee
number ("pilot <emp>: ...EmployeeID=<emp>..."), named the pickers of a pickup and quoted the request list's 'picked up
by'. Now each of those lines names the seat or the pairing (as the 1.7.9 in-flight lines do), and a filter on the
admin's logger (captures.mask_crew) is the net under every other line. Cards, the database and the exports are not
touched. Synthetic pilots only ("Doe, Jane" 10001)."""
import json
import logging
import os
import re

import pytest

import captures as CAPS
from test_crew_index import W  # noqa: F401  (the Watcher fixture: the admin's)
from test_fw173_log_mask import POT, load  # noqa: F401

LEAKS = ("Doe", "doe", "Jane", "jane", "John", "john", "Roe", "roe", "Rick", "10001", "10002", "99999", "6598")
SRC = open(os.path.join(os.path.dirname(__file__), "..", "watcher.py"), encoding="utf-8").read()


def _text(caplog):
    return "\n".join(r.getMessage() for r in caplog.records)


def _clean(text):
    for leak in LEAKS:
        assert leak not in text, (leak, text)


@pytest.mark.parametrize("line, out", [
    ("detail probe H3601: captain='Doe, Jane (99999)' blk=17:35 credit=17:35 soft=0:00",
     "detail probe H3601: captain='xxx, xxxx (#####)' blk=17:35 credit=17:35 soft=0:00"),
    ("detail text H3601: h3601 17nov report 08:00 blk 17:35 crew: ca 99999 doe, john fo 10001 doe, jane ro open",
     "detail text H3601: h3601 17nov report 08:00 blk 17:35 crew: ca ##### xxx, xxxx fo ##### xxx, xxxx ro open"),
    ("pilot 10001: Prompt=1&EmployeeID=10001&bd=1126 gave ok: flica.net (emp# 10001) schedule",
     "pilot #####: Prompt=1&EmployeeID=#####&bd=1126 gave ok: flica.net (emp# #####) schedule"),
    ("pilot 10001 (Doe, Jane): 2026-11 read, 12 items, 3 pairing pages",
     "pilot ##### (xxx, xxxx): 2026-11 read, 12 items, 3 pairing pages"),
    ("pickup H3607|13Nov: FO Doe, Jane (10001); RO Roe, Rick (10002) (CA Doe Jr, John (99999))",
     "pickup H3607|13Nov: FO xxx, xxxx (#####); RO xxx, xxxx (#####) (CA xxx xx, xxxx (#####))"),
    ("picker FO Doe, Jane (6598): 120 in open time", "picker FO xxx, xxxx (####): 120 in open time"),
    ("requests 003.152: text: 10/30 15:08 add denied 30 oct 15:10 cs: h3607:17nov picked up by doe, jane (10001)",
     "requests 003.152: text: 10/30 15:08 add denied 30 oct 15:10 cs: h3607:17nov picked up by xxx, xxxx (#####)"),
    ("crew index: H3601 17Nov names 1 of 2 pilots (crew line: ca 99999 x, x fo open)",
     "crew index: H3601 17Nov names 1 of 2 pilots (crew line: ca ##### x, x fo open)"),
    ("crew index: pilot 10001 on two overlapping trips (H3601|2026-11-17 and H3602|2026-11-18)",
     "crew index: pilot ##### on two overlapping trips (H3601|2026-11-17 and H3602|2026-11-18)"),
    ("a page line: Doe, Jane 10001", "a page line: xxx, xxxx #####"),
])
def test_the_admins_line_mask_takes_names_and_numbers(line, out):
    assert CAPS.mask_crew(line) == out
    assert CAPS.mask_crew(out) == out  # masking twice changes nothing
    _clean(out)


@pytest.mark.parametrize("line", [
    "pilot db: list 2026-07-01 merged: 3 added, 0 changed, 0 kept hand edits, 0 gone, 0 conflicts",
    "schedule 2026-11: 12 items, credit 82:00, block 71:35",
    "bid calendar: Monday, November 16 08:00 HST",
    "inflt H9001|20Nov: named pilot 1 (picker not known) IN FLIGHT on H3648 2026-11-03 (808 HNL-LAS 2026-11-03)",
    "inflt H9002|21Nov: picker 1 not in flight at pickup",
    "pickup H3607|13Nov: filled (FO, RO; CA named)", "picker of H3607|13Nov (FO): 120 in open time",
    "a pilot 100 loads an hour", "NEW pairing H3601 17Nov 4 days LAX credit 21:30",
    "speed: 2 pickups capped at Ryan's request time, 0 unmatched",
    "pot 2026-11: 14 pairings, 2 new, FLICA loads this hour 37 of 240",
])
def test_seats_pairings_times_and_counts_stay(line):
    assert CAPS.mask_crew(line) == line


def test_the_admins_detail_probe_names_no_captain(W, monkeypatch, caplog):  # noqa: F811
    monkeypatch.setattr(W, "DETAIL_PROBE", {"done": False})
    monkeypatch.setattr(W, "enrich", lambda fl, row: row.update(captain="Doe, Jane (99999)", blk="17:35",
                                                                credit="17:35", soft="0:00"))
    assert W.CAP.admin
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        W.detail_probe(None, POT)
    assert "detail probe H3607: captain=parsed blk=17:35 credit=17:35 soft=0:00" in _text(caplog)
    _clean(_text(caplog))


def test_the_admins_quoted_page_text_names_no_crew(W, caplog):  # noqa: F811
    page = ("<html><body>H3601 17NOV Report 08:00 Blk 17:35 Captain: DOE, JOHN Crew: CA 99999 DOE, JOHN "
            "FO 10001 DOE, JANE RO OPEN</body></html>")
    out = W.page_log(W.visible_text(page)[:2500])
    _clean(out)
    assert "crew: ca ##### xxx, xxxx fo ##### xxx, xxxx ro open" in out and "17:35" in out and "h3601" in out
    assert W.page_log("Doe, Jane") == "xxx, xxxx"
    # the lines that quote a page go through it
    for call in ('log.info("detail text %s: %s", ev.get("pairing"), page_log(',
                 'page captured; text: %s", b, len(rows), page_log(text[:600]))',
                 'log.info("request view %s captured; text: %s", ts, page_log(text[:600]))',
                 'log.info("request %s %s %s", r["type"], r["status"], page_log('):
        assert call in SRC, call


def test_ryans_own_schedule_lookup_lines_carry_no_number(W, monkeypatch, caplog):  # noqa: F811
    monkeypatch.setattr(W, "pub_pilot", lambda p: None)
    monkeypatch.setattr(W, "pilotver_register", lambda *a, **k: None)
    monkeypatch.setattr(W, "pilotver_capture_rebuild", lambda *a, **k: None)
    W.S["cm_prompt_captured"] = True

    class FL:
        def fetch(self, url):
            assert "EmployeeID=10001" in url or "10001" in url
            return "<html><body>flica.net (emp# 10001) Doe, Jane no schedule here</body></html>"

    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        W.pilot_cmd(json.dumps({"emp": "10001", "name": "Doe, Jane"}))
        assert W.S["pilot_req"]["emp"] == "10001"
        W.pilot_check(FL())
    text = _text(caplog)
    assert "pilot lookup: schedule requested" in text
    assert "EmployeeID=#####" in text and "gave ok" in text and "pilot lookup: schedule page not readable (ok)" in text
    _clean(text)
    assert not re.search(r'log\.\w+\(\s*"pilot %s', SRC)  # no line starts with the employee number any more


def test_the_pickup_lines_name_the_seat_not_the_pilot(W, caplog):  # noqa: F811
    for old in ('"pickup %s: %s (CA %s)"', '"picker %s: %s in open time"', 'flags[i]["emp"],'):
        assert old not in SRC, old
    assert 'log.info("pickup %s: filled (%s; CA %s)", k, seats, "named" if ca else "?")' in SRC
    assert 'log.info("picker of %s (%s): %s in open time", k, seats, secs)' in SRC
    with caplog.at_level(logging.INFO, logger="flight_watcher"):  # and the net under them, should one come back
        W.log.info("pickup %s: %s (CA %s)", "H3607|13Nov", "FO Doe, Jane (10001); RO Roe, Rick (10002)", "Doe, John (99999)")
        W.log.info("picker %s: %s in open time", "FO Doe, Jane (10001)", 12)
        W.log.info("crew index: pilot %s on two overlapping trips (%s)", "10001", "H3601|2026-11-17")
    text = _text(caplog)
    assert "pickup H3607|13Nov: FO xxx, xxxx (#####); RO xxx, xxxx (#####) (CA xxx, xxxx (#####))" in text
    assert "picker FO xxx, xxxx (#####): 12 in open time" in text and "crew index: pilot #####" in text
    _clean(text)


def test_each_instance_has_its_own_mask(load, W):  # noqa: F811
    assert [type(f).__name__ for f in W.log.filters] == ["AdminLogMask"]
    P = load("pilot2")  # noqa: N806
    assert [type(f).__name__ for f in P.log.filters] == ["PilotLogMask"]  # a pilot's log keeps its stricter mask
