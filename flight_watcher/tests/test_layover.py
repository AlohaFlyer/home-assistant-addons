"""1.7.1 (FW-0072, Ryan): van alerts and layover notes. layover.py reads the van from a synthetic Hark working flight
sensor on the layover station's clock (a daylight time zone, AEDT, and ones without it), says which alert is due (30
and 10 min before, once each, a late start only before the van time, a new van time re-arms), and keeps the notes
per station. The Watcher (the admin only) sends each alert once on flight_watcher/event/van whatever its state, keeps
sensor flight_watcher_layover_van and flight_watcher_layover_notes, and stores notes 0600 in a 0700 folder. HA's
"Flight Watcher van time" push is Ryan's critical alert like the charter one. Made-up hotels and text only."""
import copy
import importlib.util
import json
import logging
import os
import re
import stat
import sys
import threading
from datetime import datetime, timedelta, timezone

import pytest

import layover as LO
import roles

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(HERE)
UTC = timezone.utc
HST = LO.HST


def hark(van="7:40 PM (19:40) Thu 2026-11-12, Example Harbour Hotel lobby", origin="SYD", pairing="H3681", **kw):
    """A synthetic sensor.hark_working_flight as Hark writes it (made-up hotel)."""
    a = {"mode": "layover", "pairing": pairing, "leg": "2 of 2", "flight": "HA852", "origin": origin, "dest": "HNL",
         "dep_sched": "21:40 AEDT (9:40 PM) Thu 2026-11-12", "arr_sched": "10:45 HST Thu 2026-11-12",
         "report": "20:25 AEDT (8:25 PM) Thu 2026-11-12", "van": van, "hotel": "Example Harbour Hotel",
         "hotel_address": "1 Example St", "hotel_phone": "+61 2 0000 0000"}
    a.update(kw)
    return a


# ---------------------------------------------------------------- parsing and the clock
def test_parse_van_reads_harks_text_iso_and_12_hour():
    assert LO.parse_van("7:40 PM (19:40) Thu 2026-11-12, Example Harbour Hotel lobby") == \
        ("2026-11-12", "19:40", "Example Harbour Hotel lobby")
    assert LO.parse_van("2026-11-12 19:40") == ("2026-11-12", "19:40", "")
    assert LO.parse_van("7:05 am Fri 2026-11-13, front door") == ("2026-11-13", "07:05", "front door")
    assert LO.parse_van("12:30 AM Sat 2026-11-14") == ("2026-11-14", "00:30", "")
    assert LO.parse_van("7:40 PM (19:40) Thu 2026-11-12") == ("2026-11-12", "19:40", "")
    for bad in ("", None, "7:40 PM", "(19:40) Thu", "(25:10) 2026-11-12", "(19:40) 2026-02-30", "TBD"):
        assert LO.parse_van(bad) is None, bad
    # control characters and bidi overrides never reach the push
    assert LO.parse_van("(19:40) 2026-11-12, lob\u202eby\nx") == ("2026-11-12", "19:40", "lob by x")


def test_a_date_first_van_with_am_pm_or_a_zone_after_it_is_never_read_as_station_time():
    """Review r3 #1: 'YYYY-MM-DD H:MM PM' read as 07:40 sent the 30 min push 12 h early; '...T08:40:00Z' is UTC, not the
    station's clock. Both are no alert and a reason; the plain 24 h forms still read."""
    for bad in ("2026-11-12 7:40 PM, Example lobby", "2026-11-12 7:40 p.m.", "2026-11-12 07:40am",
                "2026-11-12T08:40:00Z", "2026-11-12T08:40Z", "2026-11-12 08:40 UTC", "2026-11-12 08:40 GMT",
                "2026-11-12T19:40+11:00", "2026-11-12 19:40:00"):
        assert LO.parse_van(bad) is None, bad
    assert LO.parse_van("2026-11-12 19:40") == ("2026-11-12", "19:40", "")
    assert LO.parse_van("2026-11-12 19:40, Example lobby") == ("2026-11-12", "19:40", "Example lobby")
    assert LO.parse_van("Thu, 2026-11-12 19:40, lobby") == ("2026-11-12", "19:40", "lobby")
    assert LO.parse_van("2026-11-12 19:40 AEDT, lobby") == ("2026-11-12", "19:40", "")
    info, why = LO.van_info(hark(van="2026-11-12 7:40 PM, Example Harbour Hotel lobby"), "x")
    assert info is None and why.startswith("van time not read")
    # Hark's live forms (attribute and state) still read
    assert LO.van_info(hark(), "Layover SYD, van 2026-11-12 19:40")[0]["local"] == "19:40"


def test_a_weekday_that_is_not_the_dates_is_no_alert():
    """Review r3 #2: '12:05 AM (00:05) Fri 2026-11-12' (a Thursday) put both alerts about 24 h early. A weekday that
    contradicts the date is no alert, in each of the three forms; a matching one, a long one or none still reads, and a
    word that is no weekday ('van', 'Saturn') is not one."""
    for bad in ("12:05 AM (00:05) Fri 2026-11-12, lobby", "(19:40) Friday 2026-11-12", "7:40 PM Fri 2026-11-12, X",
                "7:40 PM Thu/Fri 2026-11-12", "Fri 2026-11-12 19:40", "Wed, 2026-11-12 19:40"):
        assert LO.parse_van(bad) is None, bad
    for good, want in (("12:05 AM (00:05) Thu 2026-11-12, lobby", ("2026-11-12", "00:05", "lobby")),
                       ("(19:40) Thursday 2026-11-12", ("2026-11-12", "19:40", "")),
                       ("(19:40) Thurs. 2026-11-12", ("2026-11-12", "19:40", "")),
                       ("7:40 PM Thu 2026-11-12, X", ("2026-11-12", "19:40", "X")),
                       ("7:40 PM at the Saturn Hotel desk 2026-11-12", ("2026-11-12", "19:40", "")),
                       ("Thu 2026-11-12 19:40", ("2026-11-12", "19:40", "")),
                       (" 2026-11-12 19:40", ("2026-11-12", "19:40", ""))):
        assert LO.parse_van(good) == want, good
    assert LO.weekdays("Saturn van Thurs Tue") == {"Thu", "Tue"}
    info, why = LO.van_info(hark(van="12:05 AM (00:05) Fri 2026-11-12, lobby"), "x")
    assert info is None and why.startswith("van time not read")
    # Hark's state names the same (likely wrong) date: it never stands in for a van text that has a date
    for van, state in (("12:05 AM (00:05) Fri 2026-11-12, lobby", "Layover SYD, van 2026-11-12 00:05"),
                       ("2026-11-12 7:40 PM, lobby", "Layover SYD, van 2026-11-12 07:40")):
        info, why = LO.van_info(hark(van=van), state)
        assert info is None and why.startswith("van time not read"), van


def test_a_dst_zone_aedt_and_hst():
    info, why = LO.van_info(hark())
    assert why == ""
    assert (info["city"], info["abbr"], info["local"], info["date"]) == ("SYD", "AEDT", "19:40", "2026-11-12")
    assert info["at"] == datetime(2026, 11, 12, 8, 40, tzinfo=UTC)  # UTC+11 in the southern summer
    assert (info["hst"], info["hst_date"], info["hst_weekday"]) == ("22:40", "2026-11-11", "Wed")
    assert info["place"] == "Example Harbour Hotel lobby" and info["hotel"] == "Example Harbour Hotel"
    # the same wall time in July is AEST, UTC+10
    info, _ = LO.van_info(hark(van="(19:40) Sun 2026-07-12"))
    assert info["abbr"] == "AEST" and info["at"] == datetime(2026, 7, 12, 9, 40, tzinfo=UTC)
    assert info["place"] == "Example Harbour Hotel"  # no place in the text: the hotel


@pytest.mark.parametrize("stn,abbr,off_h,hst", [("BNE", "AEST", 10, "23:40"), ("NRT", "JST", 9, "00:40"),
                                                ("PPT", "UTC-10", -10, "19:40"), ("PHX", "MST", -7, "16:40")])
def test_dst_free_zones(stn, abbr, off_h, hst):
    """Brisbane, Tokyo, Tahiti and Phoenix keep no daylight time: November and July read the same offset."""
    for d in ("2026-11-12", "2026-07-12"):
        info, why = LO.van_info(hark(van=f"(19:40) {d}", origin=stn))
        assert why == "" and info["abbr"] == abbr and info["hst"] == hst, (stn, d)
        want = datetime.strptime(f"{d} 19:40", "%Y-%m-%d %H:%M").replace(tzinfo=UTC) - timedelta(hours=off_h)
        assert info["at"] == want, (stn, d)


def test_month_and_year_edge():
    """A van just after midnight on New Year's Day at SYD is New Year's Eve in HST, and its 30 min alert is due in
    the old year at the station."""
    info, _ = LO.van_info(hark(van="12:20 AM (00:20) Fri 2027-01-01, lobby"))
    assert info["at"] == datetime(2026, 12, 31, 13, 20, tzinfo=UTC)
    assert (info["hst"], info["hst_date"]) == ("03:20", "2026-12-31")
    now = datetime(2026, 12, 31, 23, 50, tzinfo=LO.zone_of("SYD"))  # 23:50 on Dec 31 at SYD
    assert LO.due(info, {}, now) == ([30], [])
    # and a month edge: Nov 30 23:55 local for a van at 00:15 on Dec 1 (LAX, PST)
    info, _ = LO.van_info(hark(van="(00:15) 2026-12-01", origin="LAX"))
    assert info["abbr"] == "PST" and info["at"] == datetime(2026, 12, 1, 8, 15, tzinfo=UTC)
    assert LO.due(info, {}, datetime(2026, 11, 30, 23, 55, tzinfo=LO.zone_of("LAX"))) == ([30], [])


def test_no_alert_and_a_reason_never_a_guess():
    assert LO.van_info(hark(origin="XYZ")) == (None, "no time zone known for XYZ")
    assert LO.van_info(hark(van="")) == (None, "no van time")
    assert LO.van_info(hark(van="7:40 PM Thursday"))[1].startswith("van time not read")
    assert LO.van_info(hark(pairing=""))[0] is None and LO.van_info(hark(origin="sy"))[0] is None
    # the hour a daylight time change skips at SYD (Oct 4 2026, 02:00 -> 03:00): no such time there
    info, why = LO.van_info(hark(van="(02:30) Sun 2026-10-04"))
    assert info is None and "does not exist at SYD" in why
    # the hour it repeats (Apr 5 2026, 03:00 -> 02:00): the first of the two, AEDT, so the alert is early, not late
    info, _ = LO.van_info(hark(van="(02:30) Sun 2026-04-05"))
    assert info["abbr"] == "AEDT" and info["at"] == datetime(2026, 4, 4, 15, 30, tzinfo=UTC)
    # the state's "van YYYY-MM-DD HH:MM" stands in when the attribute has no time
    info, why = LO.van_info(hark(van="see crew desk"), "Layover SYD, van 2026-11-12 19:40")
    assert why == "" and info["at"] == datetime(2026, 11, 12, 8, 40, tzinfo=UTC)


def test_a_station_ryan_flies_has_a_zone():
    for stn in ("HNL", "OGG", "KOA", "LIH", "LAX", "SFO", "SEA", "SAN", "OAK", "SMF", "LAS", "PDX", "PHX", "JFK", "BOS",
                "AUS", "HND", "NRT", "KIX", "ICN", "SYD", "BNE", "MEL", "AKL", "PPT", "PPG", "BFI", "IND", "LAN", "LNK"):
        assert LO.zone_of(stn) is not None, stn


# ---------------------------------------------------------------- what is due
def _at(info, minutes_before):
    return info["at"] - timedelta(minutes=minutes_before)


def test_each_alert_due_once_from_its_mark_until_the_van():
    info, _ = LO.van_info(hark())
    done = {}
    assert LO.due(info, done, _at(info, 31)) == ([], [])
    assert LO.due(info, done, _at(info, 30)) == ([30], [])
    done[LO.key(info, 30)] = {"how": "sent"}
    assert LO.due(info, done, _at(info, 29)) == ([], [])
    assert LO.due(info, done, _at(info, 10)) == ([10], [])
    done[LO.key(info, 10)] = {"how": "sent"}
    assert LO.due(info, done, _at(info, 1)) == ([], [])
    assert LO.due(info, {}, info["at"]) == ([], [])  # at or after the van: nothing, even never sent
    assert LO.due(info, {}, _at(info, -5)) == ([], [])


def test_a_late_start_sends_only_the_latest_and_words_the_real_minutes():
    info, _ = LO.van_info(hark())
    now = _at(info, 4) - timedelta(seconds=20)  # the app came up 4 min 20 s before the van
    assert LO.due(info, {}, now) == ([10], [30])
    title, msg = LO.render(info, 10, now)
    assert msg == "Van in 5 min: 19:40 AEDT (22:40 HST), Example Harbour Hotel lobby"
    assert title == "Van SYD 19:40 AEDT"
    assert LO.render(info, 30, _at(info, 30))[1] == "Van in 30 min: 19:40 AEDT (22:40 HST), Example Harbour Hotel lobby"


def test_a_changed_van_time_re_arms():
    info, _ = LO.van_info(hark())
    done = {LO.key(info, 30): {"how": "sent"}, LO.key(info, 10): {"how": "sent"}}
    later, _ = LO.van_info(hark(van="8:10 PM (20:10) Thu 2026-11-12, lobby"))
    assert LO.key(later, 30) != LO.key(info, 30)
    assert LO.due(later, done, _at(later, 30)) == ([30], [])


def test_no_em_dash_in_the_module():
    assert chr(0x2014) not in open(os.path.join(HERE, "layover.py"), encoding="utf-8").read()


# ---------------------------------------------------------------- the Watcher
class FakeClient:
    def __init__(self, up=True):
        self.msgs, self.up = [], up

    def publish(self, topic, payload="", retain=False):
        self.msgs.append((topic, payload, retain))

    def subscribe(self, topic):
        pass

    def is_connected(self):
        return self.up


def _load(tmp_path, monkeypatch, instance="", fake=None, states=None):
    data = tmp_path / ("data_" + (instance or "default"))
    data.mkdir(exist_ok=True)
    (data / "options.json").write_text(json.dumps({"username": "u", "password": "p", "log_level": "info",
                                                   "category_check": "HNL 332 FO"}))
    monkeypatch.setenv("FLIGHT_WATCHER_DATA", str(data))
    if instance:
        monkeypatch.setenv("FLIGHT_WATCHER_PREFIX", f"flight_watcher_{instance}")
        monkeypatch.setenv("FLIGHT_WATCHER_INSTANCE", instance)
    else:
        monkeypatch.delenv("FLIGHT_WATCHER_PREFIX", raising=False)
        monkeypatch.delenv("FLIGHT_WATCHER_INSTANCE", raising=False)
    monkeypatch.delenv("FLIGHT_WATCHER_OPTIONS", raising=False)
    sys.modules.pop("watcher", None)
    import watcher as W
    fake = fake or FakeClient()
    monkeypatch.setattr(W, "MQ", fake)
    monkeypatch.setattr(W, "LAYOVERS_DIR", str(tmp_path / "share" / "layovers"))
    monkeypatch.setattr(W, "UPLOADS_SHARED", str(tmp_path / "share" / "uploads"))  # 1.7.1: no package unless a test puts one
    st = states if states is not None else {}
    reads = []

    def ha(eid):
        reads.append(eid)
        if eid not in st:
            return 404, None
        return 200, {"entity_id": eid, "state": st[eid][0], "attributes": st[eid][1]}
    monkeypatch.setattr(W, "ha_state_full", ha)
    return W, fake, st, reads


@pytest.fixture(autouse=True)
def _unload():
    yield
    sys.modules.pop("watcher", None)


def _vans(fake, prefix="flight_watcher"):
    return [(json.loads(p), r) for t, p, r in fake.msgs if t == f"{prefix}/event/van"]


def _last(fake, sub, prefix="flight_watcher"):
    got = [json.loads(p) for t, p, r in fake.msgs if t == f"{prefix}/{sub}"]
    return got[-1] if got else None


VAN_UTC = datetime(2026, 11, 12, 8, 40, tzinfo=UTC)


def test_the_watcher_sends_each_alert_once_and_never_again_after_a_restart(tmp_path, monkeypatch, caplog):
    states = {"sensor.hark_working_flight": ("Layover SYD, van 2026-11-12 19:40", hark())}
    W, fake, st, reads = _load(tmp_path, monkeypatch, states=states)
    with caplog.at_level(logging.INFO, logger=W.log.name):
        assert W.van_tick(VAN_UTC - timedelta(minutes=45), mono=0) == []
        assert W.van_tick(VAN_UTC - timedelta(minutes=30), mono=10) == [30]
        assert W.van_tick(VAN_UTC - timedelta(minutes=29), mono=20) == []
    (ev, retain), = _vans(fake)
    assert retain is False
    assert ev["message"] == "Van in 30 min: 19:40 AEDT (22:40 HST), Example Harbour Hotel lobby"
    assert {k: ev[k] for k in ("pairing", "city", "van_local", "van_hst", "minutes", "hotel", "abbr")} == \
        {"pairing": "H3681", "city": "SYD", "van_local": "19:40", "van_hst": "22:40", "minutes": 30,
         "hotel": "Example Harbour Hotel", "abbr": "AEDT"}
    assert "van: H3681 SYD 2026-11-12 at 19:40 AEDT (22:40 HST 2026-11-11)" in caplog.text
    assert reads == ["sensor.hark_working_flight"]  # read once a minute at most (mono 0 to 20 s)
    # a restart (the module again, the same /data): the 30 min alert never repeats, the 10 min one comes
    W, fake, st, reads = _load(tmp_path, monkeypatch, states=states)
    assert W.van_tick(VAN_UTC - timedelta(minutes=25), mono=0) == [] and _vans(fake) == []
    assert W.van_tick(VAN_UTC - timedelta(minutes=10), mono=1) == [10]
    assert [e["minutes"] for e, _ in _vans(fake)] == [10]
    s = _last(fake, "layover_van")
    assert s["at"] == "2026-11-12T08:40:00+00:00" and [a["status"] for a in s["alerts"]] == ["sent", "sent"]
    assert (s["local"], s["abbr"], s["hst"], s["city"]) == ("19:40", "AEDT", "22:40", "SYD")


def test_a_new_van_time_re_arms_and_a_late_start_skips_the_earlier(tmp_path, monkeypatch, caplog):
    states = {"sensor.hark_working_flight": ("x", hark())}
    W, fake, st, _ = _load(tmp_path, monkeypatch, states=states)
    assert W.van_tick(VAN_UTC - timedelta(minutes=30), mono=0) == [30]
    st["sensor.hark_working_flight"] = ("x", hark(van="8:10 PM (20:10) Thu 2026-11-12, lobby"))
    new = VAN_UTC + timedelta(minutes=30)
    with caplog.at_level(logging.INFO, logger=W.log.name):
        assert W.van_tick(new - timedelta(minutes=5), mono=100) == [10]  # a late start for the new van: 10 only
    assert [(e["minutes"], e["minutes_left"], e["van_local"]) for e, _ in _vans(fake)] == [(30, 30, "19:40"),
                                                                                         (10, 5, "20:10")]
    assert "not sent: the app was not running then" in caplog.text
    assert W.DB.get(W.VAN_DONE)[LO.key(LO.van_info(st["sensor.hark_working_flight"][1])[0], 30)]["how"] == "skipped"
    assert W.van_tick(new + timedelta(minutes=1), mono=200) == []


def test_runs_paused_or_stepped_aside_waits_for_mqtt_and_never_after_the_van(tmp_path, monkeypatch):
    states = {"sensor.hark_working_flight": ("x", hark())}
    W, fake, st, _ = _load(tmp_path, monkeypatch, fake=FakeClient(up=False), states=states)
    W.FLAGS["pause"] = True
    W.S["machine"] = "paused"
    assert W.van_tick(VAN_UTC - timedelta(minutes=30), mono=0) == []  # MQTT down: waits
    fake.up = True
    W.S["machine"] = "yielded"
    assert W.van_tick(VAN_UTC - timedelta(minutes=28), mono=10) == [30]
    assert W.van_tick(VAN_UTC + timedelta(seconds=1), mono=20) == []  # the 10 min one was never sent: too late now
    assert [a["status"] for a in _last(fake, "layover_van")["alerts"]] == ["sent", "missed"]


def test_unknown_zone_or_no_hark_is_no_alert_and_one_log_line(tmp_path, monkeypatch, caplog):
    states = {"sensor.hark_working_flight": ("x", hark(origin="XYZ"))}
    W, fake, st, _ = _load(tmp_path, monkeypatch, states=states)
    with caplog.at_level(logging.INFO, logger=W.log.name):
        for i in range(5):
            assert W.van_tick(VAN_UTC - timedelta(minutes=30 - i), mono=i * 100) == []
    assert caplog.text.count("van alerts: none (no time zone known for XYZ)") == 1
    # 1.7.2: the van alert settings ride along even without a van (Ryan's Nov 12 tick box and sliders)
    assert _vans(fake) == [] and _last(fake, "layover_van") == {"at": None, "why": "no time zone known for XYZ",
                                                                "alerts_on": True, "offsets": [30, 10]}
    st.clear()
    assert W.van_tick(VAN_UTC, mono=1000) == []
    assert _last(fake, "layover_van")["why"] == "Hark's working flight is not in Home Assistant"


def test_an_am_pm_van_after_the_date_sends_no_alert_12_h_early(tmp_path, monkeypatch, caplog):
    """Review r3 #1, the probe's failure: at 2026-11-11 20:11 UTC (07:11 AEDT) the 1.7.1 build read '2026-11-12 7:40
    PM' as 07:40 and sent "Van in 29 min". Now nothing goes, the reason is logged once and the sensor says it."""
    states = {"sensor.hark_working_flight": ("Layover SYD, van 2026-11-12 07:40",
                                             hark(van="2026-11-12 7:40 PM, Example Harbour Hotel lobby"))}
    W, fake, st, _ = _load(tmp_path, monkeypatch, states=states)
    with caplog.at_level(logging.INFO, logger=W.log.name):
        assert W.van_tick(datetime(2026, 11, 11, 20, 11, tzinfo=UTC), mono=0) == []
        assert W.van_tick(VAN_UTC - timedelta(minutes=30), mono=100) == []
    assert _vans(fake) == [] and caplog.text.count("van alerts: none (van time not read") == 1
    assert _last(fake, "layover_van")["at"] is None


def test_the_van_sensor_keeps_only_what_the_card_reads(tmp_path, monkeypatch):
    """Review r3 (B3): the retained layover_van topic and HA's recorder get the van's place, times and alerts, not
    Hark's van text, hotel or the zone name; the push event still names the hotel and place."""
    states = {"sensor.hark_working_flight": ("x", hark())}
    W, fake, st, _ = _load(tmp_path, monkeypatch, states=states)
    W.van_tick(VAN_UTC - timedelta(minutes=30), mono=0)
    s = _last(fake, "layover_van")
    assert set(s) == {"at", "why", "pairing", "city", "abbr", "date", "local", "weekday", "hst", "hst_weekday", "place",
                      "source", "alerts",  # 1.7.1: source, package or hark, for the card's "from ..." line
                      "alerts_on", "offsets"}  # 1.7.2: the van alert settings (Ryan, Nov 12)
    assert s["source"] == "hark"
    assert "7:40 PM" not in json.dumps(s) and s["place"] == "Example Harbour Hotel lobby"
    (ev, _), = _vans(fake)
    assert ev["hotel"] == "Example Harbour Hotel" and ev["place"] == "Example Harbour Hotel lobby"


def test_a_pilot_instance_never_reads_hark_or_sends_a_van(tmp_path, monkeypatch):
    states = {"sensor.hark_working_flight": ("x", hark())}
    W, fake, st, reads = _load(tmp_path, monkeypatch, "pilot2", states=states)
    assert W.van_tick(VAN_UTC - timedelta(minutes=30), mono=0) == []
    assert reads == [] and fake.msgs == []
    assert W.layover_note_cmd(json.dumps({"city": "SYD", "text": "x"})) is False
    assert not os.path.exists(W.LAYOVERS_DIR)
    assert not roles.event_allowed("van", "pilot2") and not roles.sub_allowed("layover/note", "pilot2")


def test_the_janitor_runs_van_alerts_every_sweep_whatever_else_fails(tmp_path, monkeypatch):
    W, fake, st, _ = _load(tmp_path, monkeypatch)
    ticks, sleeps = [], []

    class Stop(BaseException):
        pass

    def sleep(s):
        sleeps.append(s)
        if len(sleeps) > 6:
            raise Stop()
    monkeypatch.setattr(W.time, "sleep", sleep)
    monkeypatch.setattr(W, "assembler", lambda: (_ for _ in ()).throw(OSError("staging gone")))
    monkeypatch.setattr(W, "van_tick", lambda: ticks.append(1))
    with pytest.raises(Stop):
        W.upload_janitor()
    assert len(ticks) == 6  # every 10 s sweep, though the uploads part fails each time
    monkeypatch.setattr(W, "van_tick", lambda: (_ for _ in ()).throw(ValueError("x")))
    swept = []
    monkeypatch.setattr(W, "assembler", lambda: type("A", (), {"sweep": lambda self: swept.append(1) or []})())
    sleeps.clear()
    with pytest.raises(Stop):
        W.upload_janitor()
    assert len(swept) == 6  # and a van error never stops the uploads


# ---------------------------------------------------------------- layover notes
def test_notes_are_stored_private_and_published_by_city(tmp_path, monkeypatch, caplog):
    states = {"sensor.hark_working_flight": ("x", hark())}
    W, fake, st, _ = _load(tmp_path, monkeypatch, states=states)
    W.van_tick(VAN_UTC - timedelta(hours=5), mono=0)  # the current layover station: SYD
    with caplog.at_level(logging.INFO, logger=W.log.name):
        assert W.layover_note_cmd(json.dumps({"city": "syd", "text": "Coffee at the corner cart, 6 AM.\r\nGood.",
                                              "rid": "r12345678"}))
        assert W.layover_note_cmd(json.dumps({"city": "LAX", "text": "Run along the beach path."}))
    assert "Coffee" not in caplog.text and "layover note add SYD: saved" in caplog.text
    root = W.LAYOVERS_DIR
    assert stat.S_IMODE(os.stat(root).st_mode) == 0o700
    assert stat.S_IMODE(os.stat(os.path.join(root, "SYD.json")).st_mode) == 0o600
    doc = json.load(open(os.path.join(root, "SYD.json"), encoding="utf-8"))
    assert [n["text"] for n in doc["notes"]] == ["Coffee at the corner cart, 6 AM.\nGood."]
    s = _last(fake, "layover_notes")
    assert s["current"] == "SYD" and s["order"][0] == "SYD" and s["count"] == 2
    assert s["cities"]["SYD"]["notes"][0]["text"].startswith("Coffee") and s["cities"]["LAX"]["total"] == 1
    assert s["last"]["rid"] == "" and s["last"]["ok"] is True and s["last"]["city"] == "LAX"
    # a guide Claude wrote shows above the notes at the next look at the folder
    with open(os.path.join(root, "SYD.guide.md"), "w", encoding="utf-8") as f:
        f.write("# SYD\n\n- Coffee: the corner cart, 6 AM.\n")
    W.layover_notes_tick(mono=1000)
    assert _last(fake, "layover_notes")["cities"]["SYD"]["guide"].startswith("# SYD")
    # delete one note by its id
    nid = doc["notes"][0]["id"]
    assert W.layover_note_cmd(json.dumps({"city": "SYD", "delete": nid, "rid": "r87654321"}))
    s = _last(fake, "layover_notes")
    assert s["cities"]["SYD"]["notes"] == [] and s["last"] == {**s["last"], "rid": "r87654321", "ok": True,
                                                              "action": "delete"}


@pytest.mark.parametrize("cmd,why", [
    ({"city": "../etc", "text": "x"}, "3-letter station code"),
    ({"city": "SY", "text": "x"}, "3-letter station code"),
    ({"city": "SYD", "text": ""}, "empty"),
    ({"city": "SYD", "text": "\u202e\u0007 "}, "empty"),
    ({"city": "SYD", "text": "x" * 1001}, "over 1000"),
    ({"city": "SYD", "text": 7}, "must be text"),
    ({"city": "SYD", "delete": "abc"}, "no such note"),
    ("not json", "not a note"),
])
def test_bad_notes_are_refused_with_a_reason(tmp_path, monkeypatch, cmd, why):
    W, fake, st, _ = _load(tmp_path, monkeypatch)
    assert W.layover_note_cmd(cmd if isinstance(cmd, str) else json.dumps(cmd)) is False
    last = _last(fake, "layover_notes")["last"]
    assert last["ok"] is False and why in last["error"]
    assert not os.path.exists(os.path.join(W.LAYOVERS_DIR, "SYD.json"))
    assert W.layover_note_cmd("x" * 9000) is False  # over 8 KB: not even parsed


def test_a_notes_file_that_will_not_load_is_never_taken_as_empty(tmp_path, monkeypatch, caplog):
    """Review r3 #3: a SYD.json with a trailing comma (a hand edit) was read as empty, so the next note replaced every
    earlier one; a file holding [] raised in sensor_payload for every city, freezing the sensor. Now a file that is
    there but cannot be read refuses the note with nothing changed, and the sensor leaves only that city out."""
    W, fake, st, _ = _load(tmp_path, monkeypatch)
    root = W.LAYOVERS_DIR
    LO.add(root, "LAX", "Beach path run.", "t1")
    broken = '{"city": "SYD", "notes": [{"id": "0123456789ab", "at": "t0", "text": "first"},], "updated": "t0"}'
    with open(os.path.join(root, "SYD.json"), "w", encoding="utf-8") as f:
        f.write(broken)
    with pytest.raises(LO.Bad, match="SYD notes file could not be read"):
        LO.add(root, "SYD", "third", "t2")
    with caplog.at_level(logging.INFO, logger=W.log.name):
        assert W.layover_note_cmd(json.dumps({"city": "SYD", "text": "third", "rid": "r11112222"})) is False
    assert open(os.path.join(root, "SYD.json"), encoding="utf-8").read() == broken  # untouched
    s = _last(fake, "layover_notes")
    assert s["last"]["ok"] is False and "could not be read: nothing changed" in s["last"]["error"]
    assert s["unreadable"] == ["SYD"] and list(s["cities"]) == ["LAX"]
    assert "SYD left out, the notes file could not be read" in caplog.text
    for bad in ("[]", '{"notes": "x"}', "\xff\xfe", '"text"'):
        with open(os.path.join(root, "SYD.json"), "w", encoding="utf-8", errors="surrogateescape") as f:
            f.write(bad)
        p = LO.sensor_payload(root, "SYD")  # never raises for one bad file
        assert p["unreadable"] == ["SYD"] and p["cities"]["LAX"]["total"] == 1, bad
        with pytest.raises(LO.Bad):
            LO.delete(root, "SYD", "0123456789ab", "t3")
    os.unlink(os.path.join(root, "SYD.json"))  # a missing file is empty, as before
    assert LO.load(root, "SYD")["notes"] == [] and LO.add(root, "SYD", "new", "t4")["notes"][0]["text"] == "new"


def test_a_lone_surrogate_or_any_error_still_answers_the_card(tmp_path, monkeypatch):
    """Review r3 #4: {"text": "ok \\ud83d"} passed clean_note, then the UTF-8 write raised UnicodeEncodeError before the
    answer, so the card waited on "Saving..." for good. The surrogate goes like a control character, and any other
    error is an answer too."""
    W, fake, st, _ = _load(tmp_path, monkeypatch)
    assert W.layover_note_cmd('{"city": "SYD", "text": "ok \\ud83d \\ude00x", "rid": "r1234abcd"}')
    doc = json.load(open(os.path.join(W.LAYOVERS_DIR, "SYD.json"), encoding="utf-8"))
    assert doc["notes"][0]["text"] == "ok  x"  # both lone halves gone, the text kept
    assert LO.clean_note("caf\u00e9 \U0001f600") == "caf\u00e9 \U0001f600"  # a real emoji stays
    monkeypatch.setattr(W.LO, "add", lambda *a: (_ for _ in ()).throw(RuntimeError("boom")))
    assert W.layover_note_cmd(json.dumps({"city": "SYD", "text": "x", "rid": "r9999aaaa"})) is False
    last = _last(fake, "layover_notes")["last"]
    assert (last["rid"], last["ok"], last["error"]) == ("r9999aaaa", False, "not saved (RuntimeError)")


def test_the_notes_sensor_is_published_one_thread_at_a_time(tmp_path, monkeypatch):
    """Review r3 #5: the janitor built the payload, the MQTT thread then wrote a note and published, and the janitor's
    stale payload went last, dropping the note and its answer. Now each publish builds and sends under one lock."""
    W, fake, st, _ = _load(tmp_path, monkeypatch)
    real, built, go = LO.sensor_payload, threading.Event(), threading.Event()

    def slow(*a, **k):
        d = real(*a, **k)
        if threading.current_thread().name == "janitor":
            built.set()
            go.wait(1.0)  # the note command runs now (it would finish first without the lock)
        return d
    monkeypatch.setattr(W.LO, "sensor_payload", slow)
    j = threading.Thread(target=W.publish_layover_notes, kwargs={"force": True}, name="janitor")
    j.start()
    assert built.wait(5)
    m = threading.Thread(target=W.layover_note_cmd, args=(json.dumps({"city": "SYD", "text": "x", "rid": "r5555aaaa"}),))
    m.start()
    m.join(0.5)
    go.set()
    j.join(5)
    m.join(5)
    s = _last(fake, "layover_notes")
    assert s["last"]["rid"] == "r5555aaaa" and s["cities"]["SYD"]["total"] == 1


def _fifo_or_skip(path):
    if not hasattr(os, "mkfifo"):
        pytest.skip("no FIFOs here")
    os.mkfifo(path)


def test_links_and_fifos_in_the_notes_folder_are_never_followed(tmp_path):
    """Review r3 (B1): the HOM app maps /share, so it can plant files in the notes folder. A guide that is a symlink to
    a secret (as /data/options.json) never reaches the sensor; a FIFO guide never hangs it (the janitor and the MQTT
    thread call it); a symlinked notes file is refused, not followed; a symlinked folder is never chmod'ed, read or
    written through."""
    root = tmp_path / "layovers"
    LO.add(str(root), "SYD", "Coffee at the corner cart.", "t1")
    secret = tmp_path / "options.json"
    secret.write_text('{"password": "made-up-secret-123"}', encoding="utf-8")
    os.symlink(secret, root / "SYD.guide.md")
    os.symlink(secret, root / "AKL.json")
    _fifo_or_skip(str(root / "NRT.guide.md"))
    box = {}
    t = threading.Thread(target=lambda: box.update(p=LO.sensor_payload(str(root), "SYD")), daemon=True)
    t.start()
    t.join(5)
    assert not t.is_alive(), "sensor_payload hung on a FIFO"
    p = box["p"]
    assert "made-up-secret" not in json.dumps(p)
    assert p["cities"]["SYD"]["guide"] == "" and p["cities"]["SYD"]["total"] == 1
    assert p["unreadable"] == ["AKL"] and p["cities"]["NRT"]["guide"] == ""
    assert LO.guide(str(root), "SYD") == ("", "") and LO.guide(str(root), "NRT") == ("", "")
    with pytest.raises(LO.Bad):
        LO.add(str(root), "AKL", "x", "t2")
    assert secret.read_text(encoding="utf-8") == '{"password": "made-up-secret-123"}' and os.path.islink(root / "AKL.json")
    assert LO.signature(str(root))  # names and kinds, never through the links
    # the folder itself a symlink (to a folder served with no login, say): refused, never chmod'ed or written through
    www = tmp_path / "www"
    www.mkdir(mode=0o755)
    (www / "SYD.json").write_text(json.dumps({"notes": [{"id": "0123456789ab", "at": "t", "text": "planted"}]}))
    link = tmp_path / "linked_layovers"
    os.symlink(www, link)
    with pytest.raises(LO.Bad, match="link or not a folder"):
        LO.add(str(link), "SYD", "x", "t3")
    with pytest.raises(LO.Bad):
        LO.ensure_dir(str(link))
    assert stat.S_IMODE(os.stat(www).st_mode) == 0o755 and sorted(os.listdir(www)) == ["SYD.json"]
    assert LO.cities(str(link)) == [] and LO.sensor_payload(str(link))["cities"] == {} and LO.signature(str(link)) == []


def test_notes_text_is_plain_and_its_controls_go(tmp_path):
    d = LO.add(str(tmp_path / "l"), "SYD", "Line one\u202e\x00\r\n\n\n\nLine two <b>bold</b>", "t")
    assert d["notes"][-1]["text"] == "Line one\n\nLine two <b>bold</b>"  # kept as text: the card escapes it


def test_the_sensor_stays_under_its_cap_current_city_first(tmp_path):
    root = str(tmp_path / "l")
    for c in ("AKL", "LAX", "SYD"):
        for i in range(60):
            LO.add(root, c, f"{c} note {i} " + "y" * 150, f"2026-11-{10 + ('AKL', 'LAX', 'SYD').index(c):02d}T0{i % 10}")
    with open(os.path.join(root, "AKL.guide.md"), "w", encoding="utf-8") as f:
        f.write("g" * 10000)
    p = LO.sensor_payload(root, "AKL")
    assert len(json.dumps(p, separators=(",", ":"))) <= LO.SENSOR_BYTES
    assert p["order"][0] == "AKL" and p["cities"]["AKL"]["guide"].endswith("(cut here: the guide is longer)")
    a = p["cities"]["AKL"]
    assert a["total"] == 60 and a["left_out"] == 60 - len(a["notes"])
    assert a["notes"] and a["notes"][0]["text"].startswith("AKL note 59")  # newest first
    assert set(p["order"]) | set(p["left_out"]) == {"AKL", "LAX", "SYD"}
    assert p["count"] == 180


def test_the_layover_card_is_never_in_a_portal_and_notes_never_exported(portal_pilot):
    W, _ = portal_pilot()
    assert not any("layover" in fn for fn in W.portal_cards())
    assert not any("layover" in e for e in W.portal_ids())
    layout = json.load(open(os.path.join(HERE, "portal_layout.json"), encoding="utf-8"))
    assert "layover" not in json.dumps(layout)


# ---------------------------------------------------------------- the HA push (Ryan's phones only)
_spec = importlib.util.spec_from_file_location("check_push_isolation_van", os.path.join(ROOT, "ha",
                                                                                       "check_push_isolation.py"))
G = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(G)
SNAPSHOT = os.path.join(ROOT, "ha", "automations_flight_watcher.yaml")


def _targets(auto):
    return [s["action"] for s in auto["actions"][1]["parallel"]]


def test_the_van_push_is_ryans_critical_alert_like_the_charter_one():
    autos = G.load(SNAPSHOT)
    van = next(a for a in autos if a["alias"] == "Flight Watcher van time")
    charter = next(a for a in autos if a["alias"] == "Flight Watcher charter")
    assert van["triggers"] == [{"topic": "flight_watcher/event/van", "trigger": "mqtt"}]
    assert sorted(_targets(van)) == sorted(_targets(charter))
    for v, c in zip(van["actions"][1]["parallel"], charter["actions"][1]["parallel"]):
        assert v["data"]["data"]["push"] == c["data"]["data"]["push"]  # interruption-level critical, its sound
        assert v["data"]["title"] == "{{ p.title }}" and v["data"]["message"] == "{{ p.message }}"
        assert v["continue_on_error"] is True
    assert van["actions"][0] == {"variables": {"p": "{{ trigger.payload_json }}"}}
    text = open(SNAPSHOT, encoding="utf-8").read()
    assert re.findall(r"flight_watcher\w*/event/van\b", text) == ["flight_watcher/event/van"]
    assert G.check(autos)[0] == []


def test_the_guard_refuses_the_van_push_from_a_pilots_prefix():
    autos = G.load(SNAPSHOT)
    bad = copy.deepcopy(autos)
    next(a for a in bad if a["alias"] == "Flight Watcher van time")["triggers"][0]["topic"] = \
        "flight_watcher_james/event/van"
    offenders, _ = G.check(bad)
    assert any(name == "Flight Watcher van time" and "pushes Ryan" in why for name, why in offenders), offenders
