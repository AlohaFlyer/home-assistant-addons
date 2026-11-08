"""FW-0067: the working flight from the pilot's own FLICA schedule (working.py) and its sensor (watcher.py), for any
instance. Synthetic data only: made-up pairings (H39xx), made-up crew ("Doe, Jane"), stations HNL/LAX/SEA/PPG/SYD."""
import json
import sys
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest

import working as WK
from pot import parse_duties, parse_legs

HST = timezone(timedelta(hours=-10))

# PPG turn on Fri Nov 20 (PPG is UTC-11): out 16:30 HST, in PPG 21:15 local (22:15 HST); back 23:20 PPG local
# (00:20 HST Nov 21), in HNL 05:55
TURN = "dy flt dps-ars dep arr blk fr 865 hnl-ppg 1630 2115 0545 fr 866 ppg-hnl 2320 0555 0535 blk : 11:20"
# Four days from Mon Nov 23: LAX layover, a layover in domicile, a SEA layover (LAX and SEA are UTC-8 standard)
FOUR = ("mo 10 hnl-lax 0800 1500 0500 tu 11 lax-hnl 0900 1230 0530 "
        "we 20 hnl-sea 0700 1430 0530 th 21 sea-hnl 0900 1300 0600")
# SYD (UTC+10): out Mon Nov 9 11:55 HST, back Thu Nov 12 08:00 SYD local = Wed Nov 11 12:00 HST
SYD = "mo 451 hnl-syd 1155 1845 1050 th 452 syd-hnl 0800 2215 1015"


def at(day, hm):
    """An aware HST time on a November 2026 day."""
    h, m = map(int, hm.split(":"))
    return datetime(2026, 11, day, h, m, tzinfo=HST)


def rec(text, report):
    return {"report": report, "legs": parse_legs(text), "duties": parse_duties(text), "crew": ["CA Doe, Jane (10001)"]}


def line():
    items = [{"trip": "H3999", "start": "2026-11-20", "end": "2026-11-21", "lay": "PPG"},
             {"trip": "VAC", "start": "2026-11-22", "end": "2026-11-22", "lay": ""},
             {"trip": "H3998", "start": "2026-11-23", "end": "2026-11-26", "lay": "LAX"},
             {"trip": "H3997", "start": "2026-11-28", "end": "2026-11-30", "lay": "SYD"}]  # legs not read yet
    own = {"H3999|2026-11-20": rec(TURN, "15:30"), "H3998|2026-11-23": rec(FOUR, "07:00"), "H3997|2026-11-28": {}}
    return items, own


def wf(now, items=None, own=None):
    i, o = line()
    return WK.working_flight(i if items is None else items, o if own is None else own, now)


def test_attributes_of_a_working_leg():
    r = wf(at(20, "12:00"))
    a = r["attributes"]
    assert r["state"] == "HA865 HNL-PPG"
    assert a == {"pairing": "H3999", "leg": "1 of 2", "flight": "HA865", "date": "2026-11-20", "origin": "HNL",
                 "dest": "PPG", "dep_sched": "16:30 local, 16:30 HST", "arr_sched": "21:15 local, 22:15 HST",
                 "block": "5:45", "report": "15:30 HST", "status": "Scheduled", "status_as_of": "2026-11-20 12:00 HST",
                 "next": "HA866 PPG-HNL 2026-11-20 23:20 local",
                 "flightaware_url": "https://www.flightaware.com/live/flight/HAL865",
                 "sigwx_url": "https://aviationweather.gov/gfa/", "source": "schedule", "release_updated": False,
                 "updated": "2026-11-20 12:00 HST", "updated_by": "Flight Watcher"}
    assert len(r["state"]) < 255
    # any aware time works: 22:00 UTC is 12:00 HST
    assert wf(datetime(2026, 11, 20, 22, 0, tzinfo=timezone.utc))["attributes"]["status_as_of"] == "2026-11-20 12:00 HST"


def test_status_phases():
    assert wf(at(20, "16:29"))["attributes"]["status"] == "Scheduled"
    assert wf(at(20, "16:30"))["attributes"]["status"] == "Enroute per schedule"
    assert wf(at(20, "22:14"))["attributes"]["status"] == "Enroute per schedule"
    assert wf(at(20, "22:15"))["attributes"]["status"] == "Arrived per schedule"


def test_rolls_exactly_two_hours_after_block_in():
    # leg 1 blocks in 22:15 HST: still the working leg at 00:14, the next leg from 00:15
    r = wf(at(21, "00:14"))
    assert r["state"] == "HA865 HNL-PPG" and r["attributes"]["status"] == "Arrived per schedule"
    r = wf(at(21, "00:15"))
    assert r["state"] == "HA866 PPG-HNL" and r["attributes"]["leg"] == "2 of 2"
    assert r["attributes"]["status"] == "Scheduled"
    # another roll_h
    assert WK.working_flight(*line(), at(20, "23:15"), roll_h=1)["state"] == "HA866 PPG-HNL"


def test_date_at_origin_across_midnight():
    # PPG 23:20 local on Nov 20 is 00:20 HST on Nov 21: the date is the day at PPG
    a = wf(at(21, "00:15"))["attributes"]
    assert a["date"] == "2026-11-20" and a["dep_sched"] == "23:20 local, 00:20 HST"
    assert a["arr_sched"] == "05:55 local, 05:55 HST" and a["block"] == "5:35" and a["report"] == "15:30 HST"
    # SYD is ahead: 08:00 SYD on Thu Nov 12 is 12:00 HST on Wed Nov 11
    items = [{"trip": "H3994", "start": "2026-11-09", "end": "2026-11-12", "lay": "SYD"}]
    own = {"H3994|2026-11-09": rec(SYD, "10:55")}
    a = WK.working_flight(items, own, at(11, "06:00"))["attributes"]
    assert a["flight"] == "HA452" and a["date"] == "2026-11-12" and a["dep_sched"] == "08:00 local, 12:00 HST"
    assert a["arr_sched"] == "22:15 local, 22:15 HST" and a["leg"] == "2 of 2"
    assert a["report"] == "06:45 local, 10:45 HST"  # a later duty out of domicile: 1:15 before departure
    assert a["next"] == ""  # no pairing after it


def test_layover_report_rule_domicile_and_away():
    # PWA 2.19.b: a later duty reports 1:15 before departure out of domicile, 1:00 in domicile
    seen = {}
    for day, hm in (("23", "06:00"), ("24", "04:00"), ("25", "04:00"), ("26", "04:00")):
        a = wf(at(int(day), hm))["attributes"]
        seen[a["flight"]] = (a["leg"], a["origin"], a["report"], a["dep_sched"], a["date"])
    assert seen == {
        "HA10": ("1 of 4", "HNL", "07:00 HST", "08:00 local, 08:00 HST", "2026-11-23"),            # FLICA check in
        "HA11": ("2 of 4", "LAX", "07:45 local, 05:45 HST", "09:00 local, 07:00 HST", "2026-11-24"),  # away: 1:15
        "HA20": ("3 of 4", "HNL", "06:00 local, 06:00 HST", "07:00 local, 07:00 HST", "2026-11-25"),  # domicile: 1:00
        "HA21": ("4 of 4", "SEA", "07:45 local, 05:45 HST", "09:00 local, 07:00 HST", "2026-11-26"),
    }


def test_a_later_leg_in_the_same_duty_keeps_the_duty_report():
    # HNL-OGG-LAX in one duty (40 min on the ground in OGG), then a LAX layover
    text = "mo 100 hnl-ogg 0800 0840 0040 mo 102 ogg-lax 0920 1720 0600 tu 103 lax-hnl 1000 1330 0530"
    items = [{"trip": "H3993", "start": "2026-11-16", "end": "2026-11-17", "lay": "LAX"}]
    own = {"H3993|2026-11-16": rec(text, "07:00")}
    a = WK.working_flight(items, own, at(16, "09:19"))["attributes"]
    assert a["flight"] == "HA100" and a["status"] == "Arrived per schedule"
    # a turn shorter than 2 h: the next leg is the working one once it blocks out, not 2 h after HA100's block-in
    a = WK.working_flight(items, own, at(16, "09:20"))["attributes"]
    assert a["flight"] == "HA102" and a["leg"] == "2 of 3" and a["report"] == "07:00 HST"
    assert a["status"] == "Enroute per schedule" and a["dep_sched"] == "09:20 local, 09:20 HST"
    a = WK.working_flight(items, own, at(17, "06:00"))["attributes"]
    assert a["flight"] == "HA103" and a["report"] == "08:45 local, 06:45 HST"


def test_next_leg_then_next_pairing():
    assert wf(at(20, "12:00"))["attributes"]["next"] == "HA866 PPG-HNL 2026-11-20 23:20 local"
    # the turn's last leg: the next pairing, by its first layover (VAC is no pairing)
    assert wf(at(21, "01:00"))["attributes"]["next"] == "H3998 LAX 2026-11-23"
    # H3998's last leg: H3997 is next though its legs are not read yet (station from the schedule's layover cell)
    a = wf(at(26, "04:00"))["attributes"]
    assert a["leg"] == "4 of 4" and a["next"] == "H3997 SYD 2026-11-28"


def test_first_layover_beats_a_first_stop():
    # H3992 stops in OGG on its way to its LAX layover: the next pairing reads LAX, not OGG
    text = "mo 100 hnl-ogg 0800 0840 0040 mo 102 ogg-lax 0920 1720 0600 tu 103 lax-hnl 1000 1330 0530"
    items = [{"trip": "H3999", "start": "2026-11-20", "end": "2026-11-21", "lay": "PPG"},
             {"trip": "H3992", "start": "2026-12-01", "end": "2026-12-02", "lay": ""}]
    own = {"H3999|2026-11-20": rec(TURN, "15:30"), "H3992|2026-12-01": rec(text, "07:00")}
    assert WK.working_flight(items, own, at(21, "01:00"))["attributes"]["next"] == "H3992 LAX 2026-12-01"
    # a turn has no layover: its first arrival that is not HNL
    own["H3992|2026-12-01"] = rec(TURN, "15:30")
    assert WK.working_flight(items, own, at(21, "01:00"))["attributes"]["next"] == "H3992 PPG 2026-12-01"
    # nothing known about where it goes: pairing and date only
    own["H3992|2026-12-01"] = {}
    assert WK.working_flight(items, own, at(21, "01:00"))["attributes"]["next"] == "H3992 2026-12-01"


def test_a_trip_with_legs_not_read_is_skipped_for_the_working_leg():
    items, own = line()
    items.insert(0, {"trip": "H3996", "start": "2026-11-19", "end": "2026-11-19", "lay": ""})
    own["H3996|2026-11-19"] = {"report": "06:00"}  # an entry cached before 1.4.9: no legs
    r = WK.working_flight(items, own, at(19, "08:00"))
    assert r["state"] == "HA865 HNL-PPG" and r["attributes"]["pairing"] == "H3999"


def test_no_trip():
    items, own = line()
    r = WK.working_flight(items, own, at(28, "09:00"))
    assert r == {"state": "No trip", "attributes": {"source": "schedule", "next": "H3997 SYD 2026-11-28",
                                                    "updated": "2026-11-28 09:00 HST", "updated_by": "Flight Watcher"}}
    # H3997 stays next until the day it ends, then nothing is ahead
    assert WK.working_flight(items, own, at(30, "23:59"))["attributes"]["next"] == "H3997 SYD 2026-11-28"
    assert WK.working_flight(items, own, datetime(2026, 12, 1, 9, 0, tzinfo=HST))["attributes"]["next"] == ""
    # an empty line, junk entries
    r = WK.working_flight([], {}, at(8, "09:00"))
    assert r["state"] == "No trip" and r["attributes"]["next"] == ""
    junk = [None, {"trip": "SCR", "start": "2026-11-10"}, {"trip": "H3991", "start": "bad"}]
    assert WK.working_flight(junk, {"H3991|bad": {"legs": [{"dep": "x"}]}}, at(8, "09:00"))["state"] == "No trip"


def test_unknown_station_shows_printed_local_and_hst():
    text = "mo 700 hnl-xyz 1000 1500 0500 tu 701 xyz-hnl 2330 0430 0500"
    items = [{"trip": "H3990", "start": "2026-11-16", "end": "2026-11-18", "lay": "XYZ"}]
    own = {"H3990|2026-11-16": rec(text, "09:00")}
    a = WK.working_flight(items, own, at(16, "09:30"))["attributes"]
    assert a["dest"] == "XYZ" and a["dep_sched"] == "10:00 local, 10:00 HST"
    assert a["arr_sched"] == "15:00 local, 15:00 HST" and a["next"] == "HA701 XYZ-HNL 2026-11-17 23:30 local"
    a = WK.working_flight(items, own, at(17, "12:00"))["attributes"]
    assert a["origin"] == "XYZ" and a["date"] == "2026-11-17"  # falls back to the HST date
    assert a["dep_sched"] == "23:30 local, 23:30 HST" and a["report"] == "22:15 local, 22:15 HST"


def test_news_ignores_only_the_time_stamps():
    a, b = wf(at(20, "12:00")), wf(at(20, "12:05"))
    assert a != b and WK.news(a) == WK.news(b)
    assert WK.news(a) != WK.news(wf(at(20, "16:30")))  # status changed
    assert "updated" not in WK.news(a)["attributes"] and "status_as_of" not in WK.news(a)["attributes"]


# ---------------------------------------------------------------- the sensor (watcher.py)
class FakeClient:
    def __init__(self):
        self.msgs = []

    def publish(self, topic, payload="", retain=False):
        self.msgs.append((topic, payload, retain))

    def subscribe(self, topic):
        pass


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
    monkeypatch.setattr(watcher.time, "sleep", lambda s: None)
    watcher.FAKE = FakeClient()
    monkeypatch.setattr(watcher, "MQ", watcher.FAKE)
    watcher.S.clear()
    items, own = line()
    watcher.S["schedule"] = {"2026-11": {"items": items}}
    watcher.S["own_trips"] = own
    return watcher


def _sent(W):
    return [json.loads(p) for t, p, r in W.FAKE.msgs if t == f"{W.T}/working_flight" and r]


def test_discovery_announces_the_working_flight_for_every_instance(W):
    c = FakeClient()
    W.discovery(c)
    cfg = {t: json.loads(p) for t, p, _ in c.msgs if p}[f"homeassistant/sensor/{W.T}/working_flight/config"]
    assert cfg["name"] == "Working flight" and cfg["icon"] == "mdi:airplane-takeoff"
    assert cfg["state_topic"] == cfg["json_attributes_topic"] == f"{W.T}/working_flight"
    assert cfg["value_template"] == "{{ value_json.state }}"
    assert cfg["json_attributes_template"] == "{{ value_json.attributes | tojson }}"
    assert cfg["unique_id"] == f"{W.T}_working_flight"
    assert cfg["default_entity_id"] == f"sensor.{W.T}_working_flight" and cfg["availability_topic"] == W.AVAIL


def test_publish_skips_an_unchanged_payload(W):
    assert W.publish_working_flight(now=at(20, "12:00")) is True
    first = _sent(W)
    assert len(first) == 1 and first[0]["state"] == "HA865 HNL-PPG"
    assert W.publish_working_flight(now=at(20, "12:01")) is False  # only the time stamps moved
    assert W.publish_working_flight(now=at(20, "12:29")) is False
    assert len(_sent(W)) == 1
    assert W.publish_working_flight(now=at(20, "12:30")) is True  # at least every 30 min
    assert W.publish_working_flight(now=at(20, "12:31")) is False
    assert W.publish_working_flight(now=at(20, "16:30")) is True  # the status changed
    assert _sent(W)[-1]["attributes"]["status"] == "Enroute per schedule"
    assert W.publish_working_flight(now=at(20, "16:31"), force=True) is True
    assert len(_sent(W)) == 4


def test_publish_never_raises(W, caplog):
    W.S["schedule"] = {"2026-11": "not a month"}
    assert W.publish_working_flight(now=at(20, "12:00")) is False
    assert "working flight not published" in caplog.text


def test_own_trip_legs_are_read_kept_in_state_and_off_the_own_trips_sensor(W, monkeypatch):
    """An entry cached before 1.4.9 (no legs) is read again, at most OWN_PER_CHECK a check, paced; one with legs is not."""
    page = ("<html><body><div>Pairing H3999 : 20NOV Check In: 15:30</div><div>Dy Flt Dps-Ars Dep Arr Blk</div>"
            "<div>Fr 865 HNL-PPG 1630 2115 0545</div><div>Fr 866 PPG-HNL 2320 0555 0535</div>"
            "<div>Blk : 11:20 Pay : 11:20 TAFB : 13:25</div><div>Crew: CA 10001 DOE, JANE FO 10003 ROE, RICK</div>"
            "</body></html>")
    waits, urls = [], []
    monkeypatch.setattr(W.time, "sleep", waits.append)
    monkeypatch.setattr(W, "local_now", lambda: datetime(2026, 11, 8, 12, 0))
    old = {"report": "15:30", "last_arr": "05:55", "blk": "11:20", "credit": "11:20", "soft": "", "crew": ["CA Doe, Jane"],
           "duties": [{"d": 0, "dep": 990, "arr": 1795, "stn": "HNL", "blk": 680, "dep_l": "16:30", "arr_l": "05:55"}]}
    items = [{"trip": f"H39{n}", "start": f"2026-11-{n}", "end": f"2026-11-{n}", "lay": "PPG"} for n in range(10, 15)]
    W.S["schedule"] = {"2026-11": {"items": items}}
    W.S["own_trips"] = {f"{it['trip']}|{it['start']}": dict(old) for it in items}
    W.S["own_trips"]["H3910|2026-11-10"]["legs"] = parse_legs(TURN)  # read since 1.4.9: kept

    class FL:
        def fetch(self, url):
            urls.append(url)
            return page

    W.own_trip_times(FL())
    assert len(urls) == W.OWN_PER_CHECK == 3 and all("H3910" not in u for u in urls)
    assert len(waits) == 2 and all(1.5 <= s <= 3.5 for s in waits)
    got = W.S["own_trips"]["H3911|2026-11-11"]["legs"]
    assert [(lg["flt"], lg["frm"], lg["to"], lg["dep_l"]) for lg in got] == [("865", "HNL", "PPG", "16:30"),
                                                                             ("866", "PPG", "HNL", "23:20")]
    assert "legs" not in W.S["own_trips"]["H3914|2026-11-14"]  # waits for the next check
    sensor = [json.loads(p) for t, p, _ in W.FAKE.msgs if t == f"{W.T}/own_trips"][-1]
    assert sensor["count"] == 5 and all("legs" not in t for t in sensor["trips"].values())
    assert sensor["trips"]["H3911|2026-11-11"]["report"] == "15:30"
    # the next check reads the last one
    urls.clear()
    W.own_trip_times(FL())
    assert len(urls) == 1 and "H3914" in urls[0]


def test_a_long_wait_looks_at_the_working_flight(W, monkeypatch):
    """While the Watcher waits (between checks, yielded, paused or parked) it looks every WORKING_TICK_S, so a departure
    or the 2 h roll shows without a check; Check now (WAKE) still ends the wait at once."""
    calls = []
    monkeypatch.setattr(W, "publish_working_flight", lambda: calls.append(1))
    monkeypatch.setattr(W, "WORKING_TICK_S", 0.01)
    W.sleep(0.2)
    assert len(calls) >= 3
    calls.clear()
    W.sleep(0)
    assert calls == []
    monkeypatch.setattr(W, "WORKING_TICK_S", 60)
    threading.Timer(0.05, W.WAKE.set).start()
    t0 = time.monotonic()
    W.sleep(30)
    assert time.monotonic() - t0 < 5 and calls == []
