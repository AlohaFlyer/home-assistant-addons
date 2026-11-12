"""1.7.2 (Ryan, Nov 12: "I like the layover card. Can you add a tick box to turn on the van time alerts and also add van
time alert settings in the form of sliders in the settings tab?"). The admin's Watcher keeps S["van"] (on, first,
second), takes flight_watcher/van/alerts/set, van/first_min/set and van/second_min/set (clamped, kept across a restart),
announces a switch and two sliders (never on a pilot), and its van alerts follow the settings: off sends nothing; a
setting changes only the van in hand (layover.settle): a lead time set or switched on after its mark is skipped while
another alert for that van is ahead or one has gone, else the latest one goes at once, and a slider moved after its own
alert went sends no other; a van learned or moved after a setting follows the 1.7.1 rules; toggling or moving a slider
back and forth never sends an alert twice or after the van; a restart's late start is as in 1.7.1. The layover card's
"Van alerts" tick box (Chromium, 390 px) and the Settings tab snapshot's tiles. Synthetic data and made-up hotels."""
import hashlib
import importlib.util
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

import layover as LO
import portal as PT
import roles
from test_layover import FakeClient, VAN_UTC, _last, _load, _vans, hark
from test_layover_card import HA_DARK, HA_LIGHT, LIGHT, NOW, _page, _states, browser  # noqa: F401 (browser is a fixture)

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(HERE)
UTC = timezone.utc
VAN = VAN_UTC  # 19:40 AEDT, 2026-11-12 08:40 UTC
SUBS = ("van/alerts/set", "van/first_min/set", "van/second_min/set")
SHOTS = os.environ.get("FW_171_SHOTS", "")  # a folder: the renders are saved there too


@pytest.fixture(autouse=True)
def _unload():
    yield
    sys.modules.pop("watcher", None)


class Msg:
    def __init__(self, topic, payload):
        self.topic, self.payload = topic, payload.encode()


def _w(tmp_path, monkeypatch, instance="", **kw):
    states = {"sensor.hark_working_flight": ("Layover SYD, van 2026-11-12 19:40", hark())}
    tmp_path.mkdir(parents=True, exist_ok=True)
    return _load(tmp_path, monkeypatch, instance, states=states, **kw)


def _set(W, sub, payload, before):
    """A van setting at <before> minutes before the van (the arming time)."""
    return W.van_setting_cmd(W.MQ, sub, payload, now=VAN - timedelta(minutes=before))


def _at(before):
    return VAN - timedelta(minutes=before)


def _sent(fake):
    return [e["minutes"] for e, _ in _vans(fake)]


def _states_pub(fake, prefix="flight_watcher"):
    """The last retained van setting states published: {sub: payload}."""
    out = {}
    for t, p, r in fake.msgs:
        if t.startswith(f"{prefix}/van/") and t.endswith("/state"):
            assert r is True, t
            out[t[len(prefix) + 1:]] = p
    return out


# ---------------------------------------------------------------- the commands, clamps and persistence
def test_defaults_are_1_7_1s_alerts():
    assert LO.offsets_of(30, 10) == LO.OFFSETS == (30, 10)
    assert LO.offsets_of(10, 30) == (30, 10) and LO.offsets_of(20, 20) == (20,) and LO.offsets_of(45, 0) == (45,)
    assert LO.offsets_of(True, None) == ()  # never a bool or a missing value


def test_topics_clamp_and_ignore_like_the_frequency_sliders(tmp_path, monkeypatch, caplog):
    W, fake, st, _ = _w(tmp_path, monkeypatch)
    assert W.van_settings() == {"on": True, "first": 30, "second": 10}
    with caplog.at_level(logging.INFO, logger=W.log.name):
        for payload, want in (("45", 45), ("200", 120), ("1", 5), ("17.6", 18), ("-3", 5), ("120", 120)):
            W.on_message(fake, None, Msg("flight_watcher/van/first_min/set", payload))
            assert W.van_settings()["first"] == want, payload
        for payload, want in (("0", 0), ("99", 60), ("-5", 0), ("25", 25)):
            W.on_message(fake, None, Msg("flight_watcher/van/second_min/set", payload))
            assert W.van_settings()["second"] == want, payload
        for bad in ("abc", "inf", "-inf", "nan", "1e999", "", "ON"):
            W.on_message(fake, None, Msg("flight_watcher/van/first_min/set", bad))  # never ends paho's thread
            W.on_message(fake, None, Msg("flight_watcher/van/second_min/set", bad))
        assert (W.van_settings()["first"], W.van_settings()["second"]) == (120, 25)
        for payload, want in (("OFF", False), ("on", True), ("false", False), ("TRUE", True), ("Off", False),
                              ("maybe", False), ("1", False), ("", False), ("ON", True)):
            W.on_message(fake, None, Msg("flight_watcher/van/alerts/set", payload))
            assert W.van_settings()["on"] is want, payload
    assert _states_pub(fake) == {"van/alerts/state": "ON", "van/first_min/state": "120", "van/second_min/state": "25"}
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("van alerts: ")]
    # one line a change (6 first, 4 second, 6 switch), none for a value that did not change; an unread switch says so
    changes = [ln for ln in lines if "ignored" not in ln]
    assert len(changes) == 16, changes
    assert "van alerts: first alert 45 min before (alerts 45 and 10 min before)" in lines
    assert "van alerts: second alert off (alerts 120 min before)" in lines
    assert "van alerts: switched off (alerts off)" in lines
    assert lines.count("van alerts: a switch command that is not ON or OFF ignored") == 3
    assert not [ln for ln in lines if "maybe" in ln]  # a payload is never logged


def test_settings_survive_a_restart(tmp_path, monkeypatch):
    W, fake, st, _ = _w(tmp_path, monkeypatch)
    assert _set(W, "van/first_min/set", "40", 300) and _set(W, "van/second_min/set", "15", 300)
    assert _set(W, "van/alerts/set", "OFF", 290)
    W, fake, st, _ = _w(tmp_path, monkeypatch)  # the module again, the same /data
    assert W.van_settings() == {"on": False, "first": 40, "second": 15}
    c = FakeClient()
    W.publish_van_settings(c)
    assert _states_pub(c) == {"van/alerts/state": "OFF", "van/first_min/state": "40", "van/second_min/state": "15"}
    assert _set(W, "van/alerts/set", "ON", 280)
    W, fake, st, _ = _w(tmp_path, monkeypatch)
    assert W.van_settings() == {"on": True, "first": 40, "second": 15} and W.S["van"] == W.van_settings()
    # a hand-edited state cannot widen the ranges; anything else in it is not read
    W.S["van"] = {"on": "yes", "first": 999, "second": -4, "armed": {"40": "2026-11-12T00:00:00"}}
    assert W.van_settings() == {"on": True, "first": 120, "second": 0}


def test_discovery_and_subscriptions_on_the_admin_only(tmp_path, monkeypatch):
    W, fake, st, _ = _w(tmp_path, monkeypatch)
    c = FakeClient()
    W.discovery(c)
    cfg = {t: json.loads(p) for t, p, _ in c.msgs if p}
    sw = cfg["homeassistant/switch/flight_watcher/van_alerts/config"]
    first = cfg["homeassistant/number/flight_watcher/van_alert_first/config"]
    second = cfg["homeassistant/number/flight_watcher/van_alert_second/config"]
    assert (sw["default_entity_id"], sw["name"], sw["icon"]) == ("switch.flight_watcher_van_alerts", "Van time alerts",
                                                                "mdi:van-passenger")
    assert (sw["command_topic"], sw["state_topic"]) == ("flight_watcher/van/alerts/set", "flight_watcher/van/alerts/state")
    assert first["default_entity_id"] == "number.flight_watcher_van_alert_first" and first["name"] == "First van alert"
    assert {k: first[k] for k in ("min", "max", "step", "mode", "unit_of_measurement")} == \
        {"min": 5, "max": 120, "step": 5, "mode": "slider", "unit_of_measurement": "min"}
    assert second["default_entity_id"] == "number.flight_watcher_van_alert_second" and "0 is off" in second["name"]
    assert {k: second[k] for k in ("min", "max", "step", "mode", "unit_of_measurement")} == \
        {"min": 0, "max": 60, "step": 5, "mode": "slider", "unit_of_measurement": "min"}
    for x, oid in ((sw, "van_alerts"), (first, "van_alert_first"), (second, "van_alert_second")):
        # built like every other entity: availability, device, ids
        assert x["availability_topic"] == "flight_watcher/status" and x["device"] == W.DEV
        assert x["unique_id"] == f"flight_watcher_{oid}" and x["object_id"] == f"flight_watcher_{oid}"
    assert (first["command_topic"], first["state_topic"]) == ("flight_watcher/van/first_min/set",
                                                              "flight_watcher/van/first_min/state")
    assert (second["command_topic"], second["state_topic"]) == ("flight_watcher/van/second_min/set",
                                                                "flight_watcher/van/second_min/state")
    subs = [s for s, q in roles.subscriptions("")]
    assert all(s in subs for s in SUBS)
    # a pilot: the three configs emptied (HA removes them), not subscribed, refused, nothing published or kept
    W, fake, st, _ = _w(tmp_path, monkeypatch, "pilot2")
    c = FakeClient()
    W.discovery(c)
    emptied = [t for t, p, _ in c.msgs if not p]
    for comp, oid in (("switch", "van_alerts"), ("number", "van_alert_first"), ("number", "van_alert_second")):
        assert f"homeassistant/{comp}/flight_watcher_pilot2/{oid}/config" in emptied
    assert not [s for s, q in roles.subscriptions("pilot2") if s.startswith("van/")]
    assert not [s for s, q in roles.subscriptions("pilot2", portal=True) if s.startswith("van/")]
    before = json.dumps(W.S, sort_keys=True)
    for sub in SUBS:
        W.on_message(fake, None, Msg(f"flight_watcher_pilot2/{sub}", "OFF" if "alerts" in sub else "60"))
        assert W.van_setting_cmd(fake, sub, "OFF" if "alerts" in sub else "60") is False
    assert json.dumps(W.S, sort_keys=True) == before and fake.msgs == []
    assert W.publish_van_settings(fake) is False and fake.msgs == []


@pytest.mark.parametrize("instance", ["", "pilot2"])
def test_connect_publishes_the_states_on_the_admin_only(tmp_path, monkeypatch, instance):
    W, fake, st, _ = _w(tmp_path, monkeypatch, instance)
    pubs = []

    class Client:
        def __init__(self, *a, **k):
            pass

        def username_pw_set(self, *a):
            pass

        def will_set(self, *a, **k):
            pass

        def connect(self, *a):
            pass

        def loop_start(self):
            pass

        def publish(self, t, p="", retain=False, **k):
            pubs.append((t, p, retain))

        def subscribe(self, t, *a, **k):
            pass

    class Timer:
        def __init__(self, *a, **k):
            self.daemon = True

        def start(self):
            pass
    monkeypatch.setattr(W.mqtt, "Client", Client)
    monkeypatch.setattr(W, "mqtt_creds", lambda: {"username": "u", "password": "p", "host": "h", "port": 1883})
    monkeypatch.setattr(W.threading, "Timer", Timer)
    c = W.mqtt_start()
    c.on_connect(c, None, None, 0)
    got = {t: (p, r) for t, p, r in pubs if "/van/" in t}
    if instance:
        assert got == {}
    else:
        assert got == {"flight_watcher/van/alerts/state": ("ON", True), "flight_watcher/van/first_min/state": ("30", True),
                       "flight_watcher/van/second_min/state": ("10", True)}


# ---------------------------------------------------------------- layover.py: custom offsets and a setting's effect
def test_due_with_custom_offsets():
    info, _ = LO.van_info(hark())
    assert LO.due(info, {}, _at(46), (45, 20)) == ([], [])
    assert LO.due(info, {}, _at(45), (45, 20)) == ([45], [])
    assert LO.due(info, {LO.key(info, 45): {"how": "sent"}}, _at(20), (45, 20)) == ([20], [])
    assert LO.due(info, {}, _at(19), (45, 20)) == ([20], [45])  # the late-start rule, the same for any offsets
    assert LO.due(info, {}, _at(30), ()) == ([], [])  # off: nothing is due
    assert LO.due(info, {LO.key(info, 45): {"how": "skipped"}}, _at(39), (45, 20)) == ([], [])  # a setting's skip
    ev = LO.event(info, 45, _at(45), (45, 20))
    assert ev["minutes"] == 45 and ev["offsets"] == [45, 20] and ev["message"].startswith("Van in 45 min: 19:40 AEDT")
    assert LO.event(info, 30, _at(30))["offsets"] == [30, 10]


def test_settle_skips_a_late_lead_time_only_when_the_van_still_gets_an_alert():
    info, _ = LO.van_info(hark())
    k = lambda m: LO.key(info, m)  # noqa: E731
    assert LO.settle(None, {}, _at(25), (), (30, 10), 30) == {}  # no van in hand: nothing (a later van is a new key)
    # switched on at 25 min before: 30's mark passed, 10 still ahead: 30 skipped, 10 goes at its mark
    assert LO.settle(info, {}, _at(25), (), (30, 10), 30) == {30: "set_after_mark"}
    # switched on at 5 min before, none gone: the latest (10) goes now, the 30 never
    assert LO.settle(info, {}, _at(5), (), (30, 10), 30) == {30: "set_after_mark"}
    assert LO.due(info, {k(30): {"how": "skipped"}}, _at(5), (30, 10)) == ([10], [])
    # one has gone already: a late one is skipped
    assert LO.settle(info, {k(30): {"how": "sent", "slot": "first"}}, _at(5), (), (30, 10), 30) == {10: "set_after_mark"}
    # after the van: skipped (so the sensor never says missed for an alert that was off)
    assert LO.settle(info, {}, VAN + timedelta(minutes=2), (), (30, 10), 30) == {30: "set_after_mark",
                                                                                 10: "set_after_mark"}
    # both raised past their marks at 35 min before (60 and 40): 60 skipped while 10 is ahead, then 40 goes now
    got = LO.settle(info, {}, _at(35), (30, 10), (60, 10), 60)
    assert got == {60: "set_after_mark"}
    done = {k(60): {"how": "skipped", "why": "set_after_mark"}}
    assert LO.settle(info, done, _at(35), (60, 10), (60, 40), 60) == {}
    assert LO.due(info, done, _at(34), (60, 40)) == ([40], [])
    # the only alert raised past its mark (30 to 45 at 35 min before): it goes now, never no alert
    assert LO.settle(info, {}, _at(35), (30,), (45,), 45) == {}
    assert LO.due(info, {}, _at(34), (45,)) == ([45], [])
    # a mark still ahead: never skipped for being late
    assert LO.settle(info, {}, _at(35), (30, 10), (20, 10), 20) == {}


def test_settle_sends_one_alert_a_slider_a_van():
    info, _ = LO.van_info(hark())
    k = lambda m: LO.key(info, m)  # noqa: E731
    sent30 = {k(30): {"how": "sent", "slot": "first"}}
    # the first alert went at 30; the first slider to 25 and then 20 (both ahead): neither goes
    assert LO.settle(info, sent30, _at(28), (30, 10), (25, 10), 25) == {25: "slot_sent"}
    chain = {**sent30, k(25): {"how": "skipped", "why": "slot_sent", "slot": "first"}}
    assert LO.settle(info, chain, _at(24), (25, 10), (20, 10), 20) == {20: "slot_sent"}
    # switched off, the first slider moved, on again: the same
    assert LO.settle(info, sent30, _at(24), (), (20, 10), 20) == {20: "slot_sent"}
    # the second slider is its own: 10 to 15 after the 30 went: 15 goes at its mark
    assert LO.settle(info, sent30, _at(28), (30, 10), (30, 15), 30) == {}
    # first and second both 30 is one alert, the first's: the second split off to 10 still goes
    assert LO.settle(info, sent30, _at(25), (30,), (30, 10), 30) == {}
    # the first moved onto the second's value: nothing new, the 10 still goes
    assert LO.settle(info, sent30, _at(25), (30, 10), (10,), 10) == {}
    # a 1.7.1 key names no slider: it counts for none
    assert LO.settle(info, {k(30): {"how": "sent"}}, _at(28), (30, 10), (25, 10), 25) == {}
    assert LO.slot_of(30, 30) == "first" and LO.slot_of(10, 30) == "second"


def test_the_sensor_says_the_settings_and_the_current_alerts():
    info, _ = LO.van_info(hark())
    d = LO.sensor(info, "", {LO.key(info, 30): {"how": "sent", "at": "x"}}, _at(20), (30, 10))
    assert (d["alerts_on"], d["offsets"]) == (True, [30, 10])
    assert [(a["minutes"], a["status"]) for a in d["alerts"]] == [(30, "sent"), (10, "pending")]
    d = LO.sensor(info, "", {}, _at(20), (45, 10), on=False)
    assert (d["alerts_on"], d["offsets"]) == (False, [45, 10]) and d["at"] == "2026-11-12T08:40:00+00:00"
    assert [(a["minutes"], a["status"]) for a in d["alerts"]] == [(45, "off"), (10, "off")]
    d = LO.sensor(info, "", {LO.key(info, 45): {"how": "skipped", "why": "set_after_mark"}}, _at(20), (45,))
    assert d["alerts"] == [{"minutes": 45, "status": "skipped", "at_hst": "21:55", "why": "set_after_mark"}]
    assert LO.sensor(info, "", {}, VAN, (30,))["alerts"][0]["status"] == "missed"  # on, never sent, van gone
    assert LO.sensor(None, "no van time", {}, _at(20), (20,), on=False) == {
        "at": None, "why": "no van time", "alerts_on": False, "offsets": [20]}


# ---------------------------------------------------------------- the Watcher's alerts follow the settings
def test_off_sends_nothing_and_the_sensor_still_shows_the_van(tmp_path, monkeypatch, caplog):
    W, fake, st, _ = _w(tmp_path, monkeypatch)
    assert _set(W, "van/alerts/set", "OFF", 120)
    with caplog.at_level(logging.INFO, logger=W.log.name):
        for i, m in enumerate((60, 30, 29, 10, 9, 1)):
            assert W.van_tick(_at(m), mono=i) == []
    assert _vans(fake) == [] and W.DB.get(W.VAN_DONE) in (None, {})
    s = _last(fake, "layover_van")
    assert s["at"] == "2026-11-12T08:40:00+00:00" and s["local"] == "19:40" and s["alerts_on"] is False
    assert s["offsets"] == [30, 10] and [a["status"] for a in s["alerts"]] == ["off", "off"]
    assert "alerts off (from Hark)" in caplog.text  # the van's log line says alerts are off


def test_switched_on_after_a_mark_skips_it_and_never_sends_it_late(tmp_path, monkeypatch, caplog):
    W, fake, st, _ = _w(tmp_path, monkeypatch)
    assert _set(W, "van/alerts/set", "OFF", 40)
    assert W.van_tick(_at(35), mono=0) == [] and W.van_tick(_at(30), mono=1) == []
    with caplog.at_level(logging.INFO, logger=W.log.name):
        assert _set(W, "van/alerts/set", "ON", 25)  # the 30 min mark passed while off
        assert W.van_tick(_at(25) + timedelta(seconds=10), mono=2) == []
        assert W.van_tick(_at(11), mono=3) == []
        assert W.van_tick(_at(10), mono=4) == [10]
    assert _sent(fake) == [10]
    done = W.DB.get(W.VAN_DONE)
    info = LO.van_info(hark())[0]
    assert done[LO.key(info, 30)]["how"] == "skipped" and done[LO.key(info, 30)]["why"] == "set_after_mark"
    assert caplog.text.count("set or alerts switched on after its mark, so it is never sent late") == 1
    s = _last(fake, "layover_van")
    assert [(a["minutes"], a["status"], a.get("why")) for a in s["alerts"]] == [(30, "skipped", "set_after_mark"),
                                                                                (10, "sent", None)]
    # a restart after it: still never sent
    W, fake, st, _ = _w(tmp_path, monkeypatch)
    assert W.van_tick(_at(5), mono=0) == [] and _vans(fake) == []


def test_a_lead_time_moved_past_its_mark_is_skipped_and_one_ahead_simply_moves(tmp_path, monkeypatch):
    """At 40 min before the van: the first alert to 45 (its mark passed 5 min ago: skipped, never sent) and the second
    to 20 (still ahead: it simply goes at its own mark); nothing at the old 30 and 10 min marks."""
    W, fake, st, _ = _w(tmp_path, monkeypatch)
    assert W.van_tick(_at(60), mono=0) == []
    assert _set(W, "van/first_min/set", "45", 40) and _set(W, "van/second_min/set", "20", 40)
    got = [W.van_tick(_at(m), mono=i + 1) for i, m in enumerate((39, 30, 21, 20, 10, 1, -1))]
    assert got == [[], [], [], [20], [], [], []]
    assert [(e["minutes"], e["minutes_left"], e["offsets"]) for e, _ in _vans(fake)] == [(20, 20, [45, 20])]
    info = LO.van_info(hark())[0]
    done = W.DB.get(W.VAN_DONE)
    assert done[LO.key(info, 45)]["how"] == "skipped" and done[LO.key(info, 45)]["why"] == "set_after_mark"
    assert LO.key(info, 30) not in done and LO.key(info, 10) not in done
    # set well ahead of both marks: both simply go at their marks
    W, fake, st, _ = _w(tmp_path / "b", monkeypatch)
    assert _set(W, "van/first_min/set", "20", 40)
    assert [W.van_tick(_at(m), mono=i) for i, m in enumerate((30, 20, 10))] == [[], [20], [10]]
    assert [(e["minutes"], e["minutes_left"], e["offsets"]) for e, _ in _vans(fake)] == [(20, 20, [20, 10]),
                                                                                        (10, 10, [20, 10])]


def test_toggling_never_sends_an_alert_twice_or_after_the_van(tmp_path, monkeypatch):
    W, fake, st, _ = _w(tmp_path, monkeypatch)
    assert W.van_tick(_at(30), mono=0) == [30]
    for before, payload in ((28, "OFF"), (27, "ON"), (26, "OFF"), (25, "ON")):
        assert _set(W, "van/alerts/set", payload, before)
        assert W.van_tick(_at(before) + timedelta(seconds=5), mono=30 - before) == []
    assert W.van_tick(_at(10), mono=20) == [10]
    for before, payload in ((5, "OFF"), (4, "ON")):
        assert _set(W, "van/alerts/set", payload, before)
        assert W.van_tick(_at(before) + timedelta(seconds=5), mono=30 - before) == []
    assert _set(W, "van/alerts/set", "OFF", -1) and _set(W, "van/alerts/set", "ON", -2)  # after the van
    assert W.van_tick(_at(-2), mono=40) == [] and W.van_tick(_at(-30), mono=41) == []
    assert _sent(fake) == [30, 10]


def test_a_slider_back_and_forth_never_sends_an_alert_twice(tmp_path, monkeypatch):
    W, fake, st, _ = _w(tmp_path, monkeypatch)
    assert W.van_tick(_at(30), mono=0) == [30]
    assert _set(W, "van/first_min/set", "20", 26)  # ahead: it would go at 20
    assert _set(W, "van/first_min/set", "30", 25)  # back: 30 went already
    for i, m in enumerate((24, 20, 15, 11)):
        assert W.van_tick(_at(m), mono=i + 1) == []
    assert _set(W, "van/second_min/set", "40", 10.5)  # past its mark: skipped
    assert _set(W, "van/second_min/set", "10", 10.4)  # back to 10 after 10.5 min before: 10's mark is ahead
    assert W.van_tick(_at(10), mono=10) == [10]
    assert _set(W, "van/second_min/set", "5", 9) and _set(W, "van/second_min/set", "10", 8)  # 10 went already
    assert W.van_tick(_at(5), mono=11) == [] and W.van_tick(_at(1), mono=12) == []
    assert _sent(fake) == [30, 10]


def _move_van(st, hhmm, label):
    """Hark writes another van time for the same layover (a made-up hotel)."""
    st["sensor.hark_working_flight"] = ("Layover SYD", hark(van=f"{label} ({hhmm}) Thu 2026-11-12, Example Harbour "
                                                             "Hotel lobby"))


def _sent3(fake):
    return [(e["minutes"], e["minutes_left"], e["van_local"]) for e, _ in _vans(fake)]


def test_a_van_moved_or_learned_after_a_setting_follows_the_1_7_1_rules(tmp_path, monkeypatch):
    """Review (1.7.2): a setting changes only the van in hand. A van Hark moves or writes after it is a new van: the
    late-start rule sends its latest alert still due, never nothing."""
    # one alert, moved from 25 to 30 at 41 min before the 19:40 van (its mark ahead); Hark then moves the van to 19:20
    W, fake, st, _ = _w(tmp_path / "a1", monkeypatch)
    assert _set(W, "van/second_min/set", "0", 300) and _set(W, "van/first_min/set", "25", 300)
    assert W.van_tick(_at(45), mono=0) == []
    assert _set(W, "van/first_min/set", "30", 41)
    _move_van(st, "19:20", "7:20 PM")
    assert [W.van_tick(_at(m), mono=100 * (i + 1)) for i, m in enumerate((40, 35, 30, 25, 21))] == [[30], [], [], [],
                                                                                                    []]
    assert _sent3(fake) == [(30, 20, "19:20")]
    # alerts off and on again after the 30 went for 19:40; Hark then moves the van to 19:23 (7 min away)
    W, fake, st, _ = _w(tmp_path / "a2", monkeypatch)
    assert W.van_tick(_at(30), mono=0) == [30]
    assert _set(W, "van/alerts/set", "OFF", 26) and _set(W, "van/alerts/set", "ON", 25)
    _move_van(st, "19:23", "7:23 PM")
    for i, m in enumerate((24, 22, 20, 18, 17.5)):
        W.van_tick(_at(m), mono=100 * (i + 1))
    assert _sent3(fake) == [(30, 30, "19:40"), (10, 7, "19:23")]
    # no van known when the first alert is set to 45 (second 0); Hark writes the 19:40 van 2 min later
    W, fake, st, _ = _w(tmp_path / "a3", monkeypatch)
    _move_van(st, "", "")
    st["sensor.hark_working_flight"][1]["van"] = "TBD"
    assert _set(W, "van/second_min/set", "0", 300)
    assert W.van_tick(_at(40), mono=0) == [] and _last(fake, "layover_van")["at"] is None
    assert _set(W, "van/first_min/set", "45", 40)
    _move_van(st, "19:40", "7:40 PM")
    assert [W.van_tick(_at(m), mono=100 * (i + 1)) for i, m in enumerate((38, 30, 10, 1))] == [[45], [], [], []]
    assert _sent3(fake) == [(45, 38, "19:40")]


def test_raising_the_lead_times_never_leaves_the_van_in_hand_with_no_alert(tmp_path, monkeypatch, caplog):
    """Review (1.7.2): at 35 min before the van, both alerts raised past their marks (60 and 40), or the only one (30 to
    45): one alert goes at once, worded with the minutes left, and nothing after it."""
    W, fake, st, _ = _w(tmp_path / "b1", monkeypatch)
    assert W.van_tick(_at(36), mono=0) == []
    with caplog.at_level(logging.INFO, logger=W.log.name):
        assert _set(W, "van/first_min/set", "60", 35) and _set(W, "van/second_min/set", "40", 35)
    assert caplog.text.count("not sent: that lead time was set or alerts switched on after its mark") == 1
    assert [W.van_tick(_at(m), mono=i + 1) for i, m in enumerate((34.9, 30, 10, 1))] == [[40], [], [], []]
    assert _sent3(fake) == [(40, 35, "19:40")]
    W, fake, st, _ = _w(tmp_path / "b2", monkeypatch)
    assert _set(W, "van/second_min/set", "0", 300)
    assert W.van_tick(_at(36), mono=0) == []
    assert _set(W, "van/first_min/set", "45", 35)
    assert _last(fake, "layover_van")["alerts"][0]["status"] == "pending"
    assert [W.van_tick(_at(m), mono=i + 1) for i, m in enumerate((34.9, 30, 10, 1))] == [[45], [], [], []]
    assert _sent3(fake) == [(45, 35, "19:40")]


def test_a_slider_moved_after_its_alert_went_sends_no_other_for_that_van(tmp_path, monkeypatch):
    """Review (1.7.2): one alert a slider a van. The first went at 30; the first slider to 25, then to 20 (both ahead):
    no push for either, the second's 10 still goes. The same through off, a move and on. The second slider is its
    own, and first and second on one value is one alert (the first's), so splitting them still sends the second."""
    W, fake, st, _ = _w(tmp_path / "f", monkeypatch)
    assert W.van_tick(_at(30), mono=0) == [30]
    assert _set(W, "van/first_min/set", "25", 28)
    assert W.van_tick(_at(25), mono=1) == []
    assert _set(W, "van/first_min/set", "20", 24)
    assert [W.van_tick(_at(m), mono=2 + i) for i, m in enumerate((20, 10))] == [[], [10]]
    assert _sent(fake) == [30, 10]
    done = W.DB.get(W.VAN_DONE)
    info = LO.van_info(hark())[0]
    assert [(done[LO.key(info, m)]["how"], done[LO.key(info, m)].get("why"), done[LO.key(info, m)]["slot"])
            for m in (30, 25, 20, 10)] == [("sent", None, "first"), ("skipped", "slot_sent", "first"),
                                           ("skipped", "slot_sent", "first"), ("sent", None, "second")]
    s = _last(fake, "layover_van")
    assert [(a["minutes"], a["status"], a.get("why")) for a in s["alerts"]] == [(20, "skipped", "slot_sent"),
                                                                                (10, "sent", None)]
    W, fake, st, _ = _w(tmp_path / "f2", monkeypatch)
    assert W.van_tick(_at(30), mono=0) == [30]
    assert _set(W, "van/alerts/set", "OFF", 28) and _set(W, "van/first_min/set", "20", 27)
    assert _set(W, "van/alerts/set", "ON", 26)
    assert [W.van_tick(_at(m), mono=1 + i) for i, m in enumerate((20, 10))] == [[], [10]]
    assert _sent(fake) == [30, 10]
    # the second slider after the first went: 10 to 15, still ahead: it goes at 15
    W, fake, st, _ = _w(tmp_path / "f3", monkeypatch)
    assert W.van_tick(_at(30), mono=0) == [30]
    assert _set(W, "van/second_min/set", "15", 28)
    assert [W.van_tick(_at(m), mono=1 + i) for i, m in enumerate((15, 10))] == [[15], []]
    # first and second both 30, the 30 went; the second split off to 10: it still goes
    W, fake, st, _ = _w(tmp_path / "i", monkeypatch)
    assert _set(W, "van/second_min/set", "30", 50)
    assert W.van_tick(_at(30), mono=0) == [30]
    assert _set(W, "van/second_min/set", "10", 25)
    assert W.van_tick(_at(10), mono=1) == [10] and _sent(fake) == [30, 10]


def test_a_setting_applies_to_the_last_van_seen_through_a_sweep_that_could_not_read_hark(tmp_path, monkeypatch):
    """The sweep before the setting got no answer for Hark's sensor: the setting still applies to the van last placed
    (switched on at 25 min before: the 30 skipped, the 10 at its mark), never a late 30 on the next good read."""
    W, fake, st, _ = _w(tmp_path, monkeypatch)
    assert _set(W, "van/alerts/set", "OFF", 40)
    assert W.van_tick(_at(35), mono=0) == []
    saved = st.pop("sensor.hark_working_flight")
    assert W.van_tick(_at(27), mono=100) == [] and _last(fake, "layover_van")["at"] is None
    assert _set(W, "van/alerts/set", "ON", 25)
    st["sensor.hark_working_flight"] = saved
    assert [W.van_tick(_at(m), mono=200 + 100 * i) for i, m in enumerate((24, 10))] == [[], [10]]
    assert _sent(fake) == [10]


def test_switched_on_after_the_van_reads_skipped_never_missed(tmp_path, monkeypatch):
    """Review (1.7.2): alerts off over both marks and switched on after the van: the sensor says skipped (with why),
    not missed (which reads as a Watcher that failed); nothing is sent."""
    W, fake, st, _ = _w(tmp_path, monkeypatch)
    assert _set(W, "van/alerts/set", "OFF", 60)
    for i, m in enumerate((30, 10, -1)):
        assert W.van_tick(_at(m), mono=i) == []
    assert _set(W, "van/alerts/set", "ON", -2)
    s = _last(fake, "layover_van")
    assert [(a["status"], a.get("why")) for a in s["alerts"]] == [("skipped", "set_after_mark")] * 2
    assert W.van_tick(_at(-3), mono=5) == [] and _vans(fake) == []


def test_mqtt_down_over_both_marks_sends_the_latest_once_it_is_back(tmp_path, monkeypatch, caplog):
    """MQTT down from before the 30 min mark to after the 10 min one: the 10 goes once MQTT is back, the 30 never; the
    log says why without claiming the app was not running."""
    W, fake, st, _ = _w(tmp_path, monkeypatch)
    fake.up = False
    with caplog.at_level(logging.INFO, logger=W.log.name):
        assert W.van_tick(_at(30), mono=0) == [] and W.van_tick(_at(10), mono=1) == []
        fake.up = True
        assert W.van_tick(_at(9), mono=2) == [10]
    assert [(e["minutes"], e["minutes_left"]) for e, _ in _vans(fake)] == [(10, 9)]
    assert "the app or MQTT was down" in caplog.text and "the app was not running then" not in caplog.text


def test_a_restarts_late_start_is_as_in_1_7_1(tmp_path, monkeypatch, caplog):
    """The app off over the 30 min mark: at 4 min 20 s before, the 10 min alert alone, worded with the real minutes,
    the 30 min one skipped (late_start), with the default settings and with a lead time set long before."""
    W, fake, st, _ = _w(tmp_path, monkeypatch)
    with caplog.at_level(logging.INFO, logger=W.log.name):
        assert W.van_tick(_at(4) - timedelta(seconds=20), mono=0) == [10]
    (ev, _), = _vans(fake)
    assert ev["minutes_left"] == 5 and ev["message"].startswith("Van in 5 min")
    info = LO.van_info(hark())[0]
    assert W.DB.get(W.VAN_DONE)[LO.key(info, 30)] == {"how": "skipped", "at": (_at(4) - timedelta(seconds=20)).isoformat(),
                                                       "why": "late_start"}
    assert "not sent: its mark passed with no alert (the app or MQTT was down, or the van time came later)" in caplog.text
    # a lead time set an hour before the van, then the app is down over its mark: the late start sends it
    W, fake, st, _ = _w(tmp_path / "b", monkeypatch)
    assert _set(W, "van/first_min/set", "20", 60)
    W, fake, st, _ = _w(tmp_path / "b", monkeypatch)  # restarted, the same /data
    assert W.van_tick(_at(15), mono=0) == [20]
    assert [(e["minutes"], e["minutes_left"]) for e, _ in _vans(fake)] == [(20, 15)]
    W, fake, st, _ = _w(tmp_path / "c", monkeypatch)
    assert _set(W, "van/first_min/set", "20", 60)
    W, fake, st, _ = _w(tmp_path / "c", monkeypatch)
    assert W.van_tick(_at(5), mono=0) == [10]  # past both marks: the latest alone
    assert W.DB.get(W.VAN_DONE)[LO.key(info, 20)]["why"] == "late_start"


def test_the_sensor_follows_a_setting_at_once(tmp_path, monkeypatch):
    W, fake, st, _ = _w(tmp_path, monkeypatch)
    assert W.van_tick(_at(60), mono=0) == []
    assert _last(fake, "layover_van")["alerts_on"] is True
    assert _set(W, "van/alerts/set", "OFF", 59)  # no van_tick between: the command republishes the sensor
    s = _last(fake, "layover_van")
    assert s["alerts_on"] is False and [a["status"] for a in s["alerts"]] == ["off", "off"]
    assert _set(W, "van/alerts/set", "ON", 58) and _set(W, "van/second_min/set", "0", 57)
    s = _last(fake, "layover_van")
    assert (s["alerts_on"], s["offsets"], [a["minutes"] for a in s["alerts"]]) == (True, [30], [30])
    assert _set(W, "van/first_min/set", "45", 56)
    s = _last(fake, "layover_van")
    assert s["offsets"] == [45] and s["alerts"][0]["status"] == "pending"  # its mark is 11 min ahead
    assert _set(W, "van/second_min/set", "20", 55.5) and _set(W, "van/first_min/set", "60", 55)
    s = _last(fake, "layover_van")  # 60's mark passed 5 min ago and the 20 is still ahead: skipped
    assert s["offsets"] == [60, 20] and [(a["status"], a.get("why")) for a in s["alerts"]] == [
        ("skipped", "set_after_mark"), ("pending", None)]
    assert W.van_tick(_at(45), mono=1) == [] and _vans(fake) == []


def test_the_done_keys_stay_bounded_and_keep_the_van_in_hand(tmp_path, monkeypatch):
    W, fake, st, _ = _w(tmp_path, monkeypatch)
    info = LO.van_info(hark())[0]
    old = {f"H9{n:03d}|2026-10-{1 + n % 28:02d}T08:00Z|30": {"how": "sent", "at": f"2026-10-01T00:{n % 60:02d}:00"}
           for n in range(45)}
    mine = {LO.key(info, m): {"how": "skipped", "at": f"2026-11-12T08:{m % 60:02d}:00"} for m in range(31, 72)}
    mine[LO.key(info, 30)] = {"how": "sent", "at": "2026-11-12T00:00:00"}  # the oldest of all by its time
    kept = W.van_keep({**old, **mine}, info)
    assert set(mine) <= set(kept) and len(kept) == len(mine) == 42  # none of the others fit in VAN_KEEP
    kept = W.van_keep({**old, LO.key(info, 30): mine[LO.key(info, 30)]}, info)
    assert len(kept) == W.VAN_KEEP and LO.key(info, 30) in kept
    assert len(W.van_keep(old, None)) == W.VAN_KEEP
    # live: the second slider through every value whose mark passed, a skipped key each; 30 never goes again
    W.DB.put(W.VAN_DONE, old)
    assert W.van_tick(_at(30), mono=0) == [30]
    for i, v in enumerate(range(31, 61)):
        assert _set(W, "van/second_min/set", str(v), 29)
        assert W.van_tick(_at(29), mono=i + 1) == []
    assert _set(W, "van/second_min/set", "10", 28)
    assert W.van_tick(_at(10), mono=50) == [10] and _sent(fake) == [30, 10]
    done = W.DB.get(W.VAN_DONE)
    assert done[LO.key(info, 30)]["how"] == "sent" and len(done) <= max(W.VAN_KEEP, 120)


# ---------------------------------------------------------------- roles, the portal and the push guard
def test_roles_classify_the_new_subs_and_the_contract_is_unchanged(tmp_path):
    allowed, refused, later = set(roles.PORTAL_CMDS), set(roles.PORTAL_REFUSED), set(roles.NOT_ON_PORTAL)
    assert set(roles.SUBS) == allowed | refused | later
    for sub in SUBS:
        assert roles.SUBS[sub] == "admin_pushes" and sub in later and sub not in allowed | refused
        assert roles.portal_sub(sub) is None and not roles.sub_allowed(sub, "pilot2", portal=True)
        assert roles.sub_allowed(sub, "") and roles.FEATURES[roles.SUBS[sub]][1] is False
    for oid in ("van_alerts", "van_alert_first", "van_alert_second"):
        assert roles.ENTITY_FEATURE[oid] == "admin_pushes" and not roles.entity_allowed(oid, "pilot2")
        assert not roles.entity_on_portal(oid, "pilot2")
    # the portal's spool refuses each, like any sub not in PORTAL_CMDS
    in_dir = tmp_path / "in"
    in_dir.mkdir()
    for i, sub in enumerate(SUBS):
        sp = PT.Spool("demo", now=lambda: 1763600000.5)
        cmd = {"fwp": 1, "id": f"00000000c0de0f0{i}", "pilot": "demo", "ts": 1763600000001 + i, "sub": sub,
               "payload": "OFF", "session": "5e55105e55105e55"}
        name = f"{cmd['ts']}-{cmd['id']}.json"
        (in_dir / name).write_text(json.dumps(cmd))
        with pytest.raises(PT.PortalError):
            sp.take(str(in_dir / name))
    # contract 1 revision 3 byte for byte (HOM 1.8.2 holds the same), and its doc unchanged
    raw = open(os.path.join(HERE, "tests", "fixtures", "portal_contract_v1.json"), "rb").read()
    assert hashlib.sha256(raw).hexdigest() == "e8e437fe9f9ccd7822158c080351d31d98a7825ff3669bf2ba4cb9cb2f8bb9fa"
    assert PT.contract_text().encode("utf-8") == raw and b"van/alerts" not in raw
    doc = open(os.path.join(HERE, "PORTAL_CONTRACT.md"), "rb").read()
    assert hashlib.sha256(doc).hexdigest() == "621f5d71d7abe71d4eccf464da658e27ec5b973558cbecd4277381bc13ad63b7"


def test_van_is_reserved_and_the_guard_reads_the_ids_as_ryans():
    assert "van" in roles.RESERVED
    assert roles.name_refusal("van") != "" and roles.name_refusal("van_driver") != ""
    spec = importlib.util.spec_from_file_location("check_push_isolation_van", os.path.join(ROOT, "ha",
                                                                                          "check_push_isolation.py"))
    G = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(G)
    for rest in ("van_alerts", "van_alert_first", "van_alert_second"):
        assert G._entity_pilot(rest) == G.RYAN, rest


# ---------------------------------------------------------------- the Settings tab snapshot
def test_the_settings_tab_snapshot_has_the_van_alert_tiles():
    text = open(os.path.join(ROOT, "ha", "dashboard_flight_watcher.json"), encoding="utf-8").read()
    d = json.loads(text)
    v = next(v for v in d["data"]["config"]["views"] if v.get("path") == "settings")
    cs = [c for s in v["sections"] for c in s["cards"]]
    i = next(i for i, c in enumerate(cs) if c.get("type") == "heading" and c.get("heading") == "Van time alerts")
    head, sw, first, second = cs[i:i + 4]
    assert head["icon"] == "mdi:van-passenger" and cs[i - 1]["type"] == "custom:flight-watcher-uploads-card"
    assert (sw["type"], sw["entity"]) == ("tile", "switch.flight_watcher_van_alerts")
    slider = [{"type": "numeric-input", "style": "slider"}]
    assert (first["type"], first["entity"], first["features"]) == ("tile", "number.flight_watcher_van_alert_first", slider)
    assert (second["type"], second["entity"], second["features"]) == ("tile", "number.flight_watcher_van_alert_second",
                                                                      slider)
    assert "0 is off" in second["name"]
    for c in (sw, first, second):
        assert c["grid_options"] == {"columns": "full"} and "visibility" not in c
    readme = open(os.path.join(ROOT, "ha", "README.md"), encoding="utf-8").read()
    pend = readme[readme.index("## Pending on Pako (1.7.2): van alert settings"):]
    pend = pend[:pend.index("\n## ", 5)]
    assert "after 1.7.2 is live" in pend and "undo: remove those four cards" in pend and "ahead of Pako" in pend
    assert hashlib.sha256(text.encode("utf-8")).hexdigest() in readme
    assert chr(0x2014) not in readme and chr(0x2014) not in text


# ---------------------------------------------------------------- the layover card's tick box (Chromium, 390 px)
def _va_states(tmp_path, on=True, offsets=(30, 10), sensor_has=True, switch=None):
    """The layover card's states with the Watcher's van sensor as van_tick makes it for these settings."""
    st = _states(tmp_path)
    a = st["sensor.hark_working_flight"]["attributes"]
    info, why = LO.van_info(a, st["sensor.hark_working_flight"]["state"])
    va = LO.sensor(info, why, {}, NOW, tuple(offsets), on)
    if not sensor_has:  # a 1.7.1 Watcher's sensor: no alerts_on or offsets
        va.pop("alerts_on")
        va.pop("offsets")
    st["sensor.flight_watcher_layover_van"]["attributes"] = va
    if switch is not None:
        st["switch.flight_watcher_van_alerts"] = {"state": switch, "last_updated": "sw1", "attributes": {}}
    return st


def _va(pg):
    return pg.evaluate("""() => { const r = window.root(), i = r.querySelector('[data-vaon]'), p = r.querySelector('[data-vapend]');
        const m = r.querySelector('[data-vamsg]'), l = r.querySelector('[data-vaset]');
        return {checked: i && i.checked, disabled: !!i && (i.disabled || i.getAttribute('aria-disabled') === 'true'),
                pend: p ? p.textContent : '', msg: m ? m.textContent : '',
                words: (r.querySelector('[data-vawords]') || {}).textContent, link: l && l.getAttribute('href'),
                label: r.querySelector('.vck') && r.querySelector('.vck').textContent.trim(),
                vp: (r.querySelector('.vp') || {}).textContent || ''}; }""")


def test_the_tick_box_shows_the_watchers_setting(browser, tmp_path):  # noqa: F811
    unk = "Not known yet: Flight Watcher has not said"
    cases = (({}, True, "30 and 10 min before", "30 min at 22:10 HST, 10 min at 22:30 HST"),
             ({"on": False}, False, "Off", ""),
             ({"offsets": (45,)}, True, "45 min before", "45 min at 21:55 HST"),
             ({"sensor_has": False, "switch": "off"}, False, "Off", ""),
             ({"sensor_has": False, "switch": "on"}, True, "30 and 10 min before", "30 min at 22:10 HST"),
             # neither the sensor nor the switch says: not known, never shown as on (review, 1.7.2)
             ({"sensor_has": False}, False, unk, ""),
             ({"sensor_has": False, "switch": "unavailable"}, False, unk, ""))
    for i, (kw, checked, words, vp) in enumerate(cases):
        pg = browser.new_page(viewport={"width": 390, "height": 844})
        pg.set_content(_page(_va_states(tmp_path / f"c{i}", **kw)))
        got = _va(pg)
        assert (got["checked"], got["words"], got["disabled"], got["pend"]) == (checked, words, words == unk, ""), kw
        assert got["label"] == "Van alerts" and got["link"] == "/flight-watcher/settings", kw
        assert "Van at Example Harbour Hotel lobby" in got["vp"], kw
        if vp:
            assert vp in got["vp"], (kw, got["vp"])
        else:  # off: the line keeps the place and leaves out the alerts (the tick box says Off)
            assert "alerts" not in got["vp"] and "HST" not in got["vp"], (kw, got["vp"])
        assert pg.evaluate("document.documentElement.scrollWidth") <= 390
        pg.close()
    # no van on the card (the report shows instead): no tick box
    st = _va_states(tmp_path / "none")
    st["sensor.hark_working_flight"]["attributes"]["van"] = ""
    st["sensor.hark_working_flight"]["state"] = "Layover SYD"
    st["sensor.flight_watcher_layover_van"]["attributes"] = LO.sensor(None, "no van time", {}, NOW)
    pg = browser.new_page(viewport={"width": 390, "height": 844})
    pg.set_content(_page(st))
    assert pg.evaluate("!!window.root().querySelector('[data-va]')") is False
    pg.close()


def test_a_tap_publishes_waits_for_the_watcher_and_reverts_on_an_error(browser, tmp_path):  # noqa: F811
    st = _va_states(tmp_path)
    pg = browser.new_page(viewport={"width": 390, "height": 844})
    pg.set_content(_page(st))
    card = pg.locator("flight-watcher-layover-card")
    card.locator("[data-vaon]").click()
    pg.wait_for_function("window.calls.length === 1")
    assert pg.evaluate("window.calls[0]") == ["mqtt", "publish", {"topic": "flight_watcher/van/alerts/set", "payload": "OFF"}]
    got = _va(pg)
    assert (got["checked"], got["disabled"], got["pend"], got["words"]) == (False, True, "Saving...", "Off")
    assert "HST" not in got["vp"] and "alerts" not in got["vp"]  # while saving off, the line says no alert times either
    # an unrelated update keeps it waiting; the Watcher's sensor saying off ends it
    pg.evaluate("window.setStates({'sensor.flight_watcher_layover_notes': {...window.H.states['sensor.flight_watcher_layover_notes'], last_updated: 'n9'}})")
    assert _va(pg)["pend"] == "Saving..."
    va = dict(st["sensor.flight_watcher_layover_van"]["attributes"], alerts_on=False)
    pg.evaluate(f"window.setStates({{'sensor.flight_watcher_layover_van': {{state: 'x', last_updated: 'v2', attributes: {json.dumps(va)}}}}})")
    got = _va(pg)
    assert (got["checked"], got["disabled"], got["pend"], got["words"]) == (False, False, "", "Off")
    assert "22:10 HST" not in got["vp"]
    # on again
    card.locator(".vck").click()
    pg.wait_for_function("window.calls.length === 2")
    assert pg.evaluate("window.calls[1][2]") == {"topic": "flight_watcher/van/alerts/set", "payload": "ON"}
    va["alerts_on"] = True
    pg.evaluate(f"window.setStates({{'sensor.flight_watcher_layover_van': {{state: 'x', last_updated: 'v3', attributes: {json.dumps(va)}}}}})")
    assert _va(pg)["checked"] is True and _va(pg)["pend"] == ""
    # a publish that fails: a short message and the box back as it was
    pg.evaluate("() => { window.H.callService = async () => { throw new Error('offline'); }; }")
    card.locator("[data-vaon]").click()
    pg.wait_for_function("!!window.root().querySelector('[data-vamsg]')")
    got = _va(pg)
    assert got["checked"] is True and got["pend"] == "" and got["msg"] == "Didn't send: offline. Try again."
    # no answer from the Watcher in 30 s: the box goes back and says so
    pg.evaluate("() => { window.H.callService = async (d, s, data) => { window.calls.push([d, s, data]); };"
                "window.setTimeout = (f, ms) => { window.tmo = [f, ms]; return 7; }; }")
    card.locator("[data-vaon]").click()
    pg.wait_for_function("window.tmo && window.tmo[1] === 30000")
    assert _va(pg)["pend"] == "Saving..."
    pg.evaluate("window.tmo[0]()")
    got = _va(pg)
    assert got["checked"] is True and got["pend"] == "" and "did not confirm" in got["msg"]
    pg.close()


def test_the_box_says_not_known_while_the_watcher_is_unavailable(browser, tmp_path):  # noqa: F811
    """Review (1.7.2): HA marks the Watcher's entities unavailable (their attributes gone) while Hark's van still
    shows: the box is not ticked, not tappable and says it is not known; a tap sends nothing."""
    st = _va_states(tmp_path, on=False, switch="off")
    st["sensor.flight_watcher_layover_van"] = {"state": "unavailable", "last_updated": "u1",
                                               "attributes": {"friendly_name": "Layover van"}}
    st["switch.flight_watcher_van_alerts"] = {"state": "unavailable", "last_updated": "u1", "attributes": {}}
    for name, theme in (("light", LIGHT), ("ha-light", HA_LIGHT), ("ha-dark", HA_DARK)):  # AA, no sideways scroll
        pg = browser.new_page(viewport={"width": 390, "height": 844})
        pg.set_content(_page(st, theme=theme))
        con = pg.evaluate("window.fwContrast(window.root().host)")
        assert not con["fails"], (name, json.dumps(con["fails"], indent=1))
        assert pg.evaluate("document.documentElement.scrollWidth") <= 390
        if SHOTS:
            pg.screenshot(path=os.path.join(SHOTS, f"van_alerts_390_{name}_not_known.png"), clip={"x": 0, "y": 0,
                                                                                                 "width": 390,
                                                                                                 "height": 360})
        pg.close()
    pg = browser.new_page(viewport={"width": 390, "height": 844})
    pg.set_content(_page(st))
    got = _va(pg)
    assert (got["checked"], got["disabled"], got["words"]) == (False, True, "Not known yet: Flight Watcher has not said")
    assert "HST" not in got["vp"]
    pg.locator("flight-watcher-layover-card .vck").click(force=True)  # aria-disabled: Playwright would wait
    pg.wait_for_timeout(100)
    assert pg.evaluate("window.calls.length") == 0 and _va(pg)["checked"] is False
    # the Watcher back: the box follows it and taps again
    va = LO.sensor(*LO.van_info(st["sensor.hark_working_flight"]["attributes"],
                                st["sensor.hark_working_flight"]["state"]), {}, NOW, (30, 10), False)
    pg.evaluate(f"window.setStates({{'sensor.flight_watcher_layover_van': {{state: 'x', last_updated: 'v2', attributes: {json.dumps(va)}}}}})")
    assert (_va(pg)["checked"], _va(pg)["disabled"], _va(pg)["words"]) == (False, False, "Off")
    pg.close()


def test_saving_ends_even_after_the_card_was_away_and_a_late_confirm_clears_the_message(browser, tmp_path):  # noqa: F811
    """Review (1.7.2): a tap, then the card off the page (another view) and back while still waiting: the 30 s wait
    starts again and ends with its message, never "Saving..." for good. A confirm that comes after the message clears
    it."""
    st = _va_states(tmp_path)
    pg = browser.new_page(viewport={"width": 390, "height": 844})
    pg.set_content(_page(st))
    pg.evaluate("() => { window.H.callService = async (d, s, data) => { window.calls.push([d, s, data]); };"
                "window.tmo = []; window.setTimeout = (f, ms) => { window.tmo.push([f, ms]); return window.tmo.length; };"
                "window.clearTimeout = () => {}; }")
    pg.locator("flight-watcher-layover-card [data-vaon]").click()
    pg.wait_for_function("window.calls.length === 1")
    assert _va(pg)["pend"] == "Saving..."
    pg.evaluate("() => { const c = window.root().host; c.remove(); document.body.appendChild(c); }")
    assert pg.evaluate("window.tmo.length") == 2 and pg.evaluate("window.tmo[1][1]") == 30000
    assert _va(pg)["pend"] == "Saving..."
    pg.evaluate("window.tmo[1][0]()")
    got = _va(pg)
    assert (got["checked"], got["disabled"], got["pend"]) == (True, False, "") and "did not confirm" in got["msg"]
    # the Watcher confirms off after all: the box says off and the message goes
    va = dict(st["sensor.flight_watcher_layover_van"]["attributes"], alerts_on=False)
    pg.evaluate(f"window.setStates({{'sensor.flight_watcher_layover_van': {{state: 'x', last_updated: 'v2', attributes: {json.dumps(va)}}}}})")
    got = _va(pg)
    assert (got["checked"], got["msg"], got["words"]) == (False, "", "Off")
    pg.close()


def test_the_box_keeps_the_keyboard_focus_through_a_tap_and_its_answer(browser, tmp_path):  # noqa: F811
    st = _va_states(tmp_path)
    pg = browser.new_page(viewport={"width": 390, "height": 844})
    pg.set_content(_page(st))
    focused = "() => { const a = window.root().activeElement; return !!a && a.matches('[data-vaon]'); }"
    pg.evaluate("window.root().querySelector('[data-vaon]').focus()")
    assert pg.evaluate(focused) is True
    pg.keyboard.press("Space")
    pg.wait_for_function("window.calls.length === 1")
    assert pg.evaluate(focused) is True and _va(pg)["pend"] == "Saving..."
    pg.keyboard.press("Space")  # while saving: nothing more is sent and the box stays as asked
    pg.wait_for_timeout(100)
    assert pg.evaluate("window.calls.length") == 1 and _va(pg)["checked"] is False
    va = dict(st["sensor.flight_watcher_layover_van"]["attributes"], alerts_on=False)
    pg.evaluate(f"window.setStates({{'sensor.flight_watcher_layover_van': {{state: 'x', last_updated: 'v2', attributes: {json.dumps(va)}}}}})")
    assert _va(pg)["pend"] == "" and pg.evaluate(focused) is True
    pg.keyboard.press("Space")
    pg.wait_for_function("window.calls.length === 2")
    assert pg.evaluate("window.calls[1][2]") == {"topic": "flight_watcher/van/alerts/set", "payload": "ON"}
    assert pg.evaluate(focused) is True
    pg.close()


def test_change_in_settings_opens_the_settings_tab_in_the_app(browser, tmp_path):  # noqa: F811
    pg = browser.new_page(viewport={"width": 390, "height": 844})
    pg.set_content(_page(_va_states(tmp_path)))
    pg.evaluate("window.went = []; history.pushState = (s, t, u) => window.went.push(u);"
                "window.addEventListener('location-changed', () => window.went.push('location-changed'))")
    pg.locator("flight-watcher-layover-card [data-vaset]").click()
    assert pg.evaluate("window.went") == ["/flight-watcher/settings", "location-changed"]
    pg.close()


@pytest.mark.parametrize("theme", ["light", "ha-light", "ha-dark"])
def test_the_tick_box_is_a_44_px_tap_and_reads_in_light_and_dark(browser, tmp_path, theme):  # noqa: F811
    pg = browser.new_page(viewport={"width": 390, "height": 844})
    pg.set_content(_page(_va_states(tmp_path), theme={"light": LIGHT, "ha-light": HA_LIGHT, "ha-dark": HA_DARK}[theme]))
    sizes = pg.evaluate("""() => ['[data-vaon]', '.vck', '[data-vaset]'].map((s) => {
        const r = window.root().querySelector(s).getBoundingClientRect(); return [s, Math.round(r.width), Math.round(r.height)]; })""")
    for sel, w, h in sizes:
        assert h >= 44 and w >= 44, (sel, w, h)
    # the box sits under the van time block, inside the card at 390 px
    va, van = pg.locator("flight-watcher-layover-card [data-va]").bounding_box(), \
        pg.locator("flight-watcher-layover-card [data-van]").bounding_box()
    assert va["y"] >= van["y"] + van["height"] - 1 and va["x"] + va["width"] <= 390
    for state in ("on", "pending", "off", "error"):
        if state == "pending":
            pg.evaluate("() => { window.H.callService = () => new Promise(() => {}); }")
            pg.locator("flight-watcher-layover-card [data-vaon]").click()
            assert _va(pg)["pend"] == "Saving..."
        elif state == "off":
            pg.evaluate("window.root().host._vaWant = null; window.root().host._render()")
            va_ = pg.evaluate("window.H.states['sensor.flight_watcher_layover_van']")
            va_["attributes"]["alerts_on"] = False
            va_["last_updated"] = "v9"
            pg.evaluate(f"window.setStates({{'sensor.flight_watcher_layover_van': {json.dumps(va_)}}})")
            assert _va(pg)["words"] == "Off"
        elif state == "error":
            pg.evaluate("() => { window.H.callService = async () => { throw new Error('no connection'); }; }")
            pg.locator("flight-watcher-layover-card [data-vaon]").click()
            pg.wait_for_function("!!window.root().querySelector('[data-vamsg]')")
        con = pg.evaluate("window.fwContrast(window.root().host)")
        assert not con["fails"], (state, json.dumps(con["fails"], indent=1))
        assert pg.evaluate("document.documentElement.scrollWidth") <= 390
        if SHOTS:
            pg.screenshot(path=os.path.join(SHOTS, f"van_alerts_390_{theme}_{state}.png"), clip={"x": 0, "y": 0,
                                                                                               "width": 390, "height": 360})
    pg.close()
