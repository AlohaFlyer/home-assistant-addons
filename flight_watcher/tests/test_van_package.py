"""1.7.1 (FW-0072, Ryan, Nov 11: "remember van times are published in the pairings pack monthly and can be updated
from time to time"): the van alerts and the layover card take the van time, in order, from (a) the pairings package's
VAN for that pairing's layover when it is not 00:00 (the text copy each upload makes; a revised package replaces it),
(b) Hark's sensor for the same pairing, (c) nothing: no alert, and the card says the van time is not known. A synthetic
package only: a made-up hotel and a made-up phone number, never a real one; made-up pairings and crew."""
import json
import logging
import os
from datetime import datetime, timedelta, timezone

import pytest

import layover as LO
import working as WK
from pot import parse_duties, parse_legs
from test_layover import FakeClient, _last, _load, _vans, hark  # noqa: F401
from test_layover import _unload  # noqa: F401  (the autouse fixture)

UTC = timezone.utc
HST = LO.HST
HDR = ("DAY    DH FLTN       DPS - ARS DEPL/GMT         ARRL/GMT       BLKT    SGCRD GRNT EQP            TBLK    TCRD   "
       "DUTY  LAYO      Mo Tu We Th Fr Sa Su")
RULE = "=" * 120


def package(van="19:25", rept="20:25", month="November", period="November 1 - December 1 (31 Days)", pairing="H3681",
            hotel="EXAMPLE HARBOUR HOTEL"):
    """A pairings package's text copy (pdftotext -layout) with one SYD layover: the hotel line prints a made-up phone
    and the VAN, calendar cells after it; the next duty reports at rept and leaves at 21:40 (HA852 SYD-HNL)."""
    return "\n".join([
        f"{month} 2026 Pairing Package", period, "", HDR,
        f"{pairing}                               BASE REPT:     12:00L/22:00GMT" + " " * 68 + "-- -- -- -- --",
        "BASE : HNL          CA01FO01RO01" + " " * 64 + "-- 10 -- -- -- -- --",
        "1          851       HNL - SYD 13:00/23:00 20:45/09:45 10h45           10:45          33L        10h45 10h45 "
        "12h15 23h40",
        "D-END: 21:00L/10:00GMT",
        f"{hotel:<63}(555)555-0100   VAN {van}" + " " * 30 + "-- 17 -- -- -- -- --",
        f"                                         REPT: {rept}L/09:25GMT",
        "3          852       SYD - HNL 21:40/10:40 08:45/18:45 10h05           10:05          33L        10h05 10h05 "
        "11h35",
        "D-END: 09:00L/19:00GMT" + " " * 72 + "-------------------------------",
        "      TOTALS BLOCK 20h50     FDP 23h50    DHD 0h00     LDGS: 2    CREDIT 22h00    T.A.F.B. 69h00",
        RULE, ""])


# Ryan's own line: H3681 from Tue Nov 10, HNL-SYD, then HA852 SYD-HNL Thu Nov 12 21:40 AEDT (10:40 UTC)
TRIP = "tu 851 hnl-syd 1300 2045 1045 th 852 syd-hnl 2140 0845 1005"
PKG_VAN = datetime(2026, 11, 12, 8, 25, tzinfo=UTC)  # 19:25 AEDT
HARK_VAN = datetime(2026, 11, 12, 8, 40, tzinfo=UTC)  # 19:40 AEDT, Hark's text in test_layover.hark()


def _own(W, pairing="H3681"):
    W.S["schedule"] = {"2026-11": {"items": [{"trip": pairing, "start": "2026-11-10", "end": "2026-11-12",
                                              "lay": "SYD"}]}}
    W.S["own_trips"] = {f"{pairing}|2026-11-10": {"report": "12:00", "legs": parse_legs(TRIP),
                                                  "duties": parse_duties(TRIP), "crew": ["CA Doe, Jane (10001)"]}}


def _put(W, text, bump=0):
    """The upload's text copy on the shared folder (a revised package replaces the file; bump moves its time on)."""
    os.makedirs(W.UPLOADS_SHARED, exist_ok=True)
    path = os.path.join(W.UPLOADS_SHARED, "2026-11_pairings.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    if bump:
        st = os.stat(path)
        os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + bump * 10**9))
    return path


# ---------------------------------------------------------------- the package's text
def test_package_vans_reads_each_layover_and_never_a_phone_number():
    got = LO.package_vans(package())
    assert (got["month"], got["start"], got["end"]) == ("2026-11", "2026-11-01", "2026-12-01")
    assert got["layovers"] == 1 and got["with_van"] == 1
    assert got["pairings"] == {"H3681": [{"stn": "SYD", "hotel": "EXAMPLE HARBOUR HOTEL", "van": "19:25",
                                          "rept": "20:25", "flt": "852", "dep": "21:40", "day": "3", "n": 1}]}
    assert "555" not in json.dumps(got)
    zero = LO.package_vans(package(van="00:00"))
    assert zero["with_van"] == 0 and zero["pairings"]["H3681"][0]["van"] == ""  # 00:00: no van time given
    ride = LO.package_vans(package(van="00:30", rept="21:10"))  # a ride time, kept as printed, not counted
    assert ride["with_van"] == 0 and ride["pairings"]["H3681"][0]["van"] == "00:30"


def test_package_van_puts_the_van_on_the_stations_clock_before_the_report():
    leg = {"pairing": "H3681", "start": "2026-11-10", "city": "SYD", "flt": "852", "dep": "21:40", "date": "2026-11-12"}
    info, why = LO.package_van([LO.package_vans(package())], leg)
    assert why == "" and info["at"] == PKG_VAN and info["source"] == "package"
    assert (info["local"], info["abbr"], info["hst"], info["date"], info["place"]) == (
        "19:25", "AEDT", "22:25", "2026-11-12", "EXAMPLE HARBOUR HOTEL")
    # a report before midnight for a departure after it, and a van before midnight for a report after it
    late = package(van="23:50", rept="00:20").replace("SYD - HNL 21:40/10:40", "SYD - HNL 01:35/14:35")
    info, _ = LO.package_van([LO.package_vans(late)], dict(leg, dep="01:35", date="2026-11-13"))
    assert (info["date"], info["local"]) == ("2026-11-12", "23:50")
    # the leg is found by station and flight or departure; another flight, station or month's period is not it
    pk = [LO.package_vans(package())]
    assert LO.package_van(pk, dict(leg, flt="11")) == (None, "")
    assert LO.package_van(pk, dict(leg, city="MEL")) == (None, "")
    assert LO.package_van(pk, dict(leg, start="2026-12-05")) == (None, "")
    assert LO.package_van(pk, dict(leg, dep="", flt=""))[0] is None  # nothing to tell this layover by
    assert LO.package_van(pk, dict(leg, pairing="H3681B"))[0]["at"] == PKG_VAN  # a rebuilt copy, same layover
    assert LO.package_van([], leg) == (None, "")


def test_00_00_and_a_van_that_is_no_pickup_before_the_report_give_no_van_time():
    leg = {"pairing": "H3681", "start": "2026-11-10", "city": "SYD", "flt": "852", "dep": "21:40", "date": "2026-11-12"}
    assert LO.package_van([LO.package_vans(package(van="00:00"))], leg) == (
        None, "gives no van time for H3681 SYD (VAN 00:00)")
    # as four "HOTEL TBA" charter lines on Pako read (VAN 00:30 with a 21:10 report): a ride time, not a clock time
    assert LO.package_van([LO.package_vans(package(van="00:30", rept="21:10"))], leg) == (
        None, "VAN 00:30 for H3681 SYD is no pickup before the 21:10 report")
    assert LO.package_van([LO.package_vans(package(van="20:40"))], leg)[0] is None  # after the 20:25 report
    assert LO.package_van([LO.package_vans(package(van="17:25"))], leg)[0]["local"] == "17:25"  # 3 h before: kept


def test_the_layover_leg_from_ryans_own_schedule():
    items = [{"trip": "H3681", "start": "2026-11-10", "end": "2026-11-12", "lay": "SYD"}]
    own = {"H3681|2026-11-10": {"report": "12:00", "legs": parse_legs(TRIP), "duties": parse_duties(TRIP)}}
    want = {"pairing": "H3681", "start": "2026-11-10", "city": "SYD", "flt": "852", "dep": "21:40", "date": "2026-11-12"}
    assert WK.layover_leg(items, own, datetime(2026, 11, 10, 20, 0, tzinfo=HST)) is None  # flying to SYD
    assert WK.layover_leg(items, own, datetime(2026, 11, 11, 0, 0, tzinfo=HST)) == want  # blocked in at SYD
    assert WK.layover_leg(items, own, PKG_VAN) == want
    assert WK.layover_leg(items, own, datetime(2026, 11, 12, 10, 41, tzinfo=UTC)) is None  # left SYD
    assert WK.layover_leg(items, {}, PKG_VAN) is None  # legs not read


# ---------------------------------------------------------------- the Watcher: package, then Hark, then none
def test_a_package_van_wins_over_harks_and_says_so(tmp_path, monkeypatch, caplog):
    states = {"sensor.hark_working_flight": ("Layover SYD, van 2026-11-12 19:40", hark())}
    W, fake, st, _ = _load(tmp_path, monkeypatch, states=states)
    _own(W)
    _put(W, package())
    with caplog.at_level(logging.INFO, logger=W.log.name):
        assert W.van_tick(PKG_VAN - timedelta(minutes=31), mono=0) == []
        assert W.van_tick(PKG_VAN - timedelta(minutes=30), mono=10) == [30]
        assert W.van_tick(HARK_VAN - timedelta(minutes=30), mono=20) == []  # Hark's 19:40 sends nothing
        assert W.van_tick(PKG_VAN - timedelta(minutes=10), mono=30) == [10]
    assert [(e["minutes"], e["van_local"], e["van_hst"]) for e, _ in _vans(fake)] == [(30, "19:25", "22:25"),
                                                                                     (10, "19:25", "22:25")]
    ev = _vans(fake)[0][0]
    assert ev["message"] == "Van in 30 min: 19:25 AEDT (22:25 HST), Example Harbour Hotel lobby"  # Hark's place words
    s = _last(fake, "layover_van")
    assert (s["source"], s["local"], s["at"]) == ("package", "19:25", "2026-11-12T08:25:00+00:00")
    assert "van times: the 2026-11 pairings package read: 1 layovers, 1 with a van time" in caplog.text
    assert "(from the pairings package)" in caplog.text


def test_a_revised_package_with_another_van_re_arms_the_alerts(tmp_path, monkeypatch, caplog):
    states = {"sensor.hark_working_flight": ("x", hark())}
    W, fake, st, _ = _load(tmp_path, monkeypatch, states=states)
    _own(W)
    _put(W, package(van="19:25"))
    assert W.van_tick(PKG_VAN - timedelta(minutes=30), mono=0) == [30]
    assert W.van_tick(PKG_VAN - timedelta(minutes=29), mono=10) == []  # once
    # the company revises the package (the uploads card replaces the text copy): van 19:45 AEDT
    _put(W, package(van="19:45"), bump=5)
    new = PKG_VAN + timedelta(minutes=20)
    with caplog.at_level(logging.INFO, logger=W.log.name):
        assert W.van_tick(PKG_VAN - timedelta(minutes=28), mono=20) == []  # its 30 min mark is not here yet
        assert W.van_tick(new - timedelta(minutes=30), mono=30) == [30]  # re-armed: the new van's 30 min alert
        assert W.van_tick(new - timedelta(minutes=10), mono=40) == [10]
    assert [(e["minutes"], e["van_local"]) for e, _ in _vans(fake)] == [(30, "19:25"), (30, "19:45"), (10, "19:45")]
    assert caplog.text.count("van times: the 2026-11 pairings package read") == 1  # the revision read once
    # the same package again (an upload of the same revision) re-arms nothing
    _put(W, package(van="19:45"), bump=10)
    assert W.van_tick(new - timedelta(minutes=5), mono=50) == []
    assert [a["status"] for a in _last(fake, "layover_van")["alerts"]] == ["sent", "sent"]


def test_00_00_or_no_pickup_time_falls_through_to_hark(tmp_path, monkeypatch):
    for van, rept in (("00:00", "20:25"), ("00:30", "21:10")):
        states = {"sensor.hark_working_flight": ("x", hark())}
        root = tmp_path / van.replace(":", "")
        root.mkdir()
        W, fake, st, _ = _load(root, monkeypatch, states=states)
        _own(W)
        _put(W, package(van=van, rept=rept))
        assert W.van_tick(HARK_VAN - timedelta(minutes=30), mono=0) == [30], van
        (ev, _), = _vans(fake)
        assert ev["van_local"] == "19:40" and _last(fake, "layover_van")["source"] == "hark"


def test_no_package_van_and_no_hark_is_no_alert_and_says_why(tmp_path, monkeypatch):
    W, fake, st, _ = _load(tmp_path, monkeypatch, states={})
    _own(W)
    _put(W, package(van="00:00"))
    assert W.van_tick(HARK_VAN - timedelta(minutes=30), mono=0) == [] and _vans(fake) == []
    assert _last(fake, "layover_van") == {
        "at": None, "why": "Hark's working flight is not in Home Assistant; the pairings package gives no van time for "
                           "H3681 SYD (VAN 00:00)", "alerts_on": True, "offsets": [30, 10]}  # 1.7.2: the settings
    assert W._VAN["city"] == "SYD"  # the notes still follow the layover station


def test_harks_van_for_another_pairing_is_not_used(tmp_path, monkeypatch):
    states = {"sensor.hark_working_flight": ("x", hark(pairing="H3999"))}  # Hark still on another trip
    W, fake, st, _ = _load(tmp_path, monkeypatch, states=states)
    _own(W)
    assert W.van_tick(HARK_VAN - timedelta(minutes=30), mono=0) == [] and _vans(fake) == []
    assert _last(fake, "layover_van")["why"] == "Hark's working flight is for another pairing than H3681"
    _put(W, package())  # the package still gives this layover's van
    assert W.van_tick(PKG_VAN - timedelta(minutes=10), mono=100) == [10]


def test_without_ryans_legs_harks_layover_finds_the_package_van(tmp_path, monkeypatch):
    """No own legs read (a trip FLICA has not shown yet): Hark's layover (pairing, origin, flight, departure) finds the
    same layover in the package, and its VAN still comes first."""
    states = {"sensor.hark_working_flight": ("x", hark())}
    W, fake, st, _ = _load(tmp_path, monkeypatch, states=states)
    _put(W, package())
    assert W.van_tick(PKG_VAN - timedelta(minutes=30), mono=0) == [30]
    assert _vans(fake)[0][0]["van_local"] == "19:25" and _last(fake, "layover_van")["source"] == "package"


def test_a_package_for_another_month_is_not_used(tmp_path, monkeypatch, caplog):
    states = {"sensor.hark_working_flight": ("x", hark())}
    W, fake, st, _ = _load(tmp_path, monkeypatch, states=states)
    _own(W)
    _put(W, package(month="December", period="December 2 - December 31 (30 Days)"))  # misnamed file
    with caplog.at_level(logging.INFO, logger=W.log.name):
        assert W.van_tick(HARK_VAN - timedelta(minutes=30), mono=0) == [30]
    assert _vans(fake)[0][0]["van_local"] == "19:40"
    assert "2026-11_pairings.txt is the 2026-12 package: not used" in caplog.text


def test_no_em_dash_in_the_new_code():
    for f in ("layover.py", "working.py", "tests/test_van_package.py"):
        assert chr(0x2014) not in open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), f),
                                       encoding="utf-8").read(), f
