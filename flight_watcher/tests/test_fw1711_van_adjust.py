"""1.7.11 (FW-0075, Ryan, Nov 17): "I need to have a plus and a - kind of below the numbers for the van time because in
some cases the company adjust the van time a little tiny bit ... I would want to be able to switch the van time in five
minute increments so I could set it for 510 for example".

layover.adjusted moves a van by a whole multiple of 5 minutes (ADJUST_RANGE, -120 to +120) on the instant and reads
its clock again on the station's zone (daylight time and midnight right); layover.van_id is the van before any move.
The admin's Watcher keeps S["van_adjust"] {van_id: minutes} (at most 8, the van in hand's always), takes
flight_watcher/van/adjust/set {"van", "minutes"} (the absolute move, so a repeat or a retry never moves it twice;
refused with one log line and nothing changed otherwise, never on a pilot's instance), applies the move in van_tick
right after van_source (keys, alerts and the sensor use the moved van: a new van time, the 1.7.1 and 1.7.2 rules) and
drops it when the van itself changes. The layover card (Chromium, 390 px) shows -5 min and +5 min under the van time
only when the sensor says adjustable, waits for the Watcher ("Saving...", "Not saved, try again" after 10 s), says
the move and offers "Back to". Synthetic data only: made-up pairings, hotels and places."""
import copy
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone

import pytest

import layover as LO
import portal as PT
import roles
from test_layover import FakeClient, _last, _load, _unload, _vans, hark  # noqa: F401 (_unload: the autouse fixture)
from test_layover_card import DARK, HA_DARK, HA_LIGHT, LIGHT, NOW, SRC, _hark_full, _page, _states, browser  # noqa: F401

UTC = timezone.utc
LAS_VAN = datetime(2026, 11, 18, 13, 25, tzinfo=UTC)  # 05:25 PST, Wed 2026-11-18
LAS_TEXT = "5:25 AM (05:25) Wed 2026-11-18, Example Desert Hotel lobby"
LAS_STATE = "Layover LAS, van 2026-11-18 05:25"
VID = "H3681|2026-11-18T13:25Z"
TOPIC = "flight_watcher/van/adjust/set"
SHOTS = os.environ.get("FW_171_SHOTS", "")


class Msg:
    def __init__(self, topic, payload):
        self.topic, self.payload = topic, payload.encode() if isinstance(payload, str) else payload


def las(van=LAS_TEXT, **kw):
    return hark(van=van, origin="LAS", **kw)


def las_info(van=LAS_TEXT, **kw):
    info, why = LO.van_info(las(van=van, **kw), "x")
    assert why == "", why
    return info


# ---------------------------------------------------------------- layover.py
def test_adjusted_moves_the_instant_and_reads_the_clock_again():
    info = las_info()
    keep = copy.deepcopy(info)
    m = LO.adjusted(info, -15)
    assert info == keep  # pure: the van as read is not changed
    assert (m["local"], m["date"], m["weekday"], m["abbr"]) == ("05:10", "2026-11-18", "Wed", "PST")
    assert m["at"] == LAS_VAN - timedelta(minutes=15) and m["at"].tzinfo == UTC
    assert (m["hst"], m["hst_date"], m["hst_weekday"]) == ("03:10", "2026-11-18", "Wed")
    assert (m["adjust_min"], m["orig_local"], m["orig_date"]) == (-15, "05:25", "2026-11-18")
    for k in ("pairing", "city", "zone", "place", "hotel", "text", "source"):
        assert m[k] == info[k], k
    assert m["source"] == "hark" and m["place"] == "Example Desert Hotel lobby"
    # 0 is the van unchanged; a move of a moved van is from the van as read (absolute), and 0 puts it back
    assert LO.adjusted(info, 0) is info
    assert LO.adjusted(m, 10) == LO.adjusted(info, 10)
    assert LO.adjusted(m, 0) == info and "adjust_min" not in LO.adjusted(m, 0)
    assert LO.adjusted(m, -15) == m
    p = LO.adjusted(info, 120)
    assert (p["local"], p["adjust_min"], p["orig_local"]) == ("07:25", 120, "05:25")


def test_adjusted_across_midnight_both_ways():
    info = las_info("12:05 AM (00:05) Thu 2026-11-19, Example lobby")
    m = LO.adjusted(info, -10)
    assert (m["local"], m["date"], m["weekday"]) == ("23:55", "2026-11-18", "Wed")
    assert (m["orig_local"], m["orig_date"]) == ("00:05", "2026-11-19")
    assert (m["hst"], m["hst_date"], m["hst_weekday"]) == ("21:55", "2026-11-18", "Wed")
    info = las_info("11:55 PM (23:55) Wed 2026-11-18, Example lobby")
    m = LO.adjusted(info, 10)
    assert (m["local"], m["date"], m["weekday"]) == ("00:05", "2026-11-19", "Thu")
    # a month and a year edge at SYD
    info, _ = LO.van_info(hark(van="12:10 AM (00:10) Fri 2027-01-01, lobby"))
    m = LO.adjusted(info, -15)
    assert (m["local"], m["date"], m["weekday"], m["abbr"]) == ("23:55", "2026-12-31", "Thu", "AEDT")


def test_adjusted_is_daylight_time_right():
    # SYD springs forward Sun 2026-10-04 at 02:00 AEST to 03:00 AEDT: 03:10 AEDT less 15 min is 01:55 AEST
    info, _ = LO.van_info(hark(van="(03:10) Sun 2026-10-04"))
    assert info["abbr"] == "AEDT" and info["at"] == datetime(2026, 10, 3, 16, 10, tzinfo=UTC)
    m = LO.adjusted(info, -15)
    assert (m["local"], m["date"], m["abbr"]) == ("01:55", "2026-10-04", "AEST")
    assert m["at"] == datetime(2026, 10, 3, 15, 55, tzinfo=UTC)
    # LAX falls back Sun 2026-11-01 at 02:00 PDT to 01:00 PST: 00:55 PDT plus 30 is 01:25 PDT, plus 70 is 01:05 PST
    info, _ = LO.van_info(hark(van="(00:55) Sun 2026-11-01", origin="LAX"))
    assert info["abbr"] == "PDT"
    assert (LO.adjusted(info, 30)["local"], LO.adjusted(info, 30)["abbr"]) == ("01:25", "PDT")
    m = LO.adjusted(info, 70)
    assert (m["local"], m["abbr"], m["at"]) == ("01:05", "PST", datetime(2026, 11, 1, 9, 5, tzinfo=UTC))
    # a station without daylight time (PPT, UTC-10) keeps its letters
    info, _ = LO.van_info(hark(van="(06:00) 2026-11-18", origin="PPT"))
    assert LO.adjusted(info, -5)["abbr"] == "UTC-10" and LO.adjusted(info, -5)["local"] == "05:55"


def test_only_a_whole_multiple_of_5_in_the_range():
    assert LO.ADJUST_RANGE == (-120, 120) and LO.ADJUST_STEP == 5
    info = las_info()
    for m in (-120, -5, 0, 5, 115, 120):
        assert LO.adjust_ok(m), m
    for bad in (-125, 125, 7, 1, -1, True, False, 5.0, -15.0, "5", "-15", None, float("nan"), float("inf"),
                10 ** 30, [5], {"m": 5}):
        assert not LO.adjust_ok(bad), bad
        with pytest.raises(ValueError):
            LO.adjusted(info, bad)


def test_van_id_is_the_van_before_any_move():
    info = las_info()
    assert LO.van_id(info) == VID == LO.key(info, 0).rsplit("|", 1)[0]
    m = LO.adjusted(info, -15)
    assert LO.van_id(m) == VID and LO.van_id(LO.adjusted(info, 120)) == VID
    # a moved van is a new van time: a new key for every alert
    assert LO.key(m, 30) == "H3681|2026-11-18T13:10Z|30" and LO.key(m, 30) != LO.key(info, 30)
    # FLICA's rebuilt H3681B is the same trip
    assert LO.van_id(las_info(pairing="H3681B")) == VID
    assert LO.van_id(None) == ""


def test_the_sensor_says_adjustable_the_van_id_and_the_move():
    info = las_info()
    now = LAS_VAN - timedelta(hours=2)
    d = LO.sensor(info, "", {}, now, adjustable=True)
    assert (d["adjustable"], d["van_id"], d["adjust_min"]) == (True, VID, 0)
    assert "orig_local" not in d and "orig_date" not in d and d["local"] == "05:25"
    d = LO.sensor(LO.adjusted(info, -15), "", {}, now, adjustable=True)
    assert (d["adjustable"], d["van_id"], d["adjust_min"]) == (True, VID, -15)
    assert (d["local"], d["orig_local"], d["orig_date"]) == ("05:10", "05:25", "2026-11-18")
    assert d["at"] == "2026-11-18T13:10:00+00:00" and d["alerts"][0]["at_hst"] == "02:40"
    # not adjustable (the default, a pilot never has a van sensor): none of it; no van: nothing new
    d = LO.sensor(info, "", {}, now)
    assert not {"adjustable", "van_id", "adjust_min", "orig_local", "orig_date"} & set(d)
    assert LO.sensor(None, "no van time", {}, now, adjustable=True) == {"at": None, "why": "no van time",
                                                                       "alerts_on": True, "offsets": [30, 10]}


def test_no_em_dash_anywhere_this_release_wrote():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for fn in ("layover.py", "watcher.py", "roles.py", "CHANGELOG.md", "README.md",
               os.path.join("www", "flight-watcher-layover-card.js"), os.path.join("tests", "test_fw1711_van_adjust.py"),
               os.path.join("..", "HANDOFF.md")):
        assert chr(0x2014) not in open(os.path.join(here, fn), encoding="utf-8").read(), fn


# ---------------------------------------------------------------- the Watcher
def _w(tmp_path, monkeypatch, instance="", text=LAS_TEXT, state=LAS_STATE):
    states = {"sensor.hark_working_flight": (state, las(van=text))}
    tmp_path.mkdir(parents=True, exist_ok=True)
    return _load(tmp_path, monkeypatch, instance, states=states)


def _move(W, fake, minutes, van=VID, prefix="flight_watcher"):
    W.on_message(fake, None, Msg(f"{prefix}/van/adjust/set", json.dumps({"van": van, "minutes": minutes})))


def _at(before, van=LAS_VAN):
    return van - timedelta(minutes=before)


def _lines(caplog, start="van"):
    return [r.getMessage() for r in caplog.records if r.getMessage().startswith(start)]


def test_the_command_moves_the_van_absolutely_and_once(tmp_path, monkeypatch, caplog):
    W, fake, st, _ = _w(tmp_path, monkeypatch)
    assert ("van/adjust/set", 0) in roles.subscriptions("")
    assert W.van_tick(_at(180), mono=0) == []
    s = _last(fake, "layover_van")
    assert (s["adjustable"], s["van_id"], s["adjust_min"], s["local"]) == (True, VID, 0, "05:25")
    with caplog.at_level(logging.INFO, logger=W.log.name):
        caplog.clear()
        _move(W, fake, -15)
        assert W.S["van_adjust"] == {VID: -15}
        s = _last(fake, "layover_van")
        assert (s["local"], s["abbr"], s["hst"], s["adjust_min"], s["van_id"]) == ("05:10", "PST", "03:10", -15, VID)
        assert (s["orig_local"], s["orig_date"], s["at"]) == ("05:25", "2026-11-18", "2026-11-18T13:10:00+00:00")
        # the same press again (a retry, a double tap): never moved twice, no second line
        _move(W, fake, -15)
        assert W.S["van_adjust"] == {VID: -15} and _last(fake, "layover_van")["local"] == "05:10"
        # the next sweep keeps it and says nothing more about it
        W.van_tick(_at(170), mono=100)
        assert _last(fake, "layover_van")["local"] == "05:10"
        _move(W, fake, -10)
        assert _last(fake, "layover_van")["local"] == "05:15" and W.S["van_adjust"] == {VID: -10}
        _move(W, fake, 0)  # back to Hark's time: the entry goes
        assert W.S["van_adjust"] == {}
        s = _last(fake, "layover_van")
        assert (s["local"], s["adjust_min"]) == ("05:25", 0) and "orig_local" not in s
    assert _lines(caplog) == [
        "van: moved -15 min by Ryan: H3681 LAS 2026-11-18 05:10 PST (Hark says 05:25)",
        "van: moved -10 min by Ryan: H3681 LAS 2026-11-18 05:15 PST (Hark says 05:25)",
        "van: moved back by Ryan: H3681 LAS 2026-11-18 05:25 PST (Hark's time)"]
    assert "Example" not in caplog.text and "Doe" not in caplog.text


def test_a_package_van_says_the_package(tmp_path, monkeypatch, caplog):
    from test_van_package import _own, _put, package
    W, fake, st, _ = _load(tmp_path, monkeypatch, states={"sensor.hark_working_flight": ("x", hark())})
    _own(W)
    _put(W, package())
    pk = datetime(2026, 11, 12, 8, 25, tzinfo=UTC)  # 19:25 AEDT from the package
    W.van_tick(pk - timedelta(hours=3), mono=0)
    s = _last(fake, "layover_van")
    assert (s["source"], s["local"], s["adjustable"]) == ("package", "19:25", True)
    with caplog.at_level(logging.INFO, logger=W.log.name):
        caplog.clear()
        _move(W, fake, 10, van=s["van_id"])
        W.van_tick(pk - timedelta(hours=2), mono=100)
    s = _last(fake, "layover_van")
    assert (s["source"], s["local"], s["orig_local"], s["adjust_min"]) == ("package", "19:35", "19:25", 10)
    assert _lines(caplog) == ["van: moved +10 min by Ryan: H3681 SYD 2026-11-12 19:35 AEDT (the package says 19:25)"]
    with caplog.at_level(logging.INFO, logger=W.log.name):
        _move(W, fake, 0, van=s["van_id"])
    assert _lines(caplog)[-1] == "van: moved back by Ryan: H3681 SYD 2026-11-12 19:25 AEDT (the package's time)"


@pytest.mark.parametrize("payload,why", [
    ("not json", "not a JSON object"), ("[1, 2]", "not a JSON object"), ("5", "not a JSON object"),
    ("null", "not a JSON object"), ("", "not a JSON object"), ("[" * 100000, "not a JSON object"),
    ("[" * 500, "not a JSON object"),
    (json.dumps({"van": VID, "minutes": "x" * 600}), "not a JSON object"),  # over the size cap
    (json.dumps({"van": VID}), "the minutes"), (json.dumps({"van": VID, "minutes": 7}), "the minutes"),
    (json.dumps({"van": VID, "minutes": 125}), "the minutes"), (json.dumps({"van": VID, "minutes": -125}), "the minutes"),
    (json.dumps({"van": VID, "minutes": True}), "the minutes"), (json.dumps({"van": VID, "minutes": -5.0}), "the minutes"),
    (json.dumps({"van": VID, "minutes": "-5"}), "the minutes"), (json.dumps({"van": VID, "minutes": None}), "the minutes"),
    ('{"van": "%s", "minutes": NaN}' % VID, "the minutes"), ('{"van": "%s", "minutes": 1e999}' % VID, "the minutes"),
    ('{"van": "%s", "minutes": %d}' % (VID, 10 ** 40), "the minutes"),
    (json.dumps({"van": "H3681|2026-11-18T13:20Z", "minutes": -5}), "not the van in hand"),
    (json.dumps({"van": 5, "minutes": -5}), "not the van in hand"), (json.dumps({"minutes": -5}), "not the van in hand"),
])
def test_a_bad_command_is_refused_with_one_line_and_nothing_changed(tmp_path, monkeypatch, caplog, payload, why):
    W, fake, st, _ = _w(tmp_path, monkeypatch)
    W.van_tick(_at(180), mono=0)
    _move(W, fake, -5)
    before, n = json.dumps(W.S, sort_keys=True), len(fake.msgs)
    with caplog.at_level(logging.INFO, logger=W.log.name):
        caplog.clear()
        W.on_message_safe(fake, None, Msg(TOPIC, payload))  # never ends paho's thread
        assert W.van_adjust_cmd(fake, payload) is False
    assert json.dumps(W.S, sort_keys=True) == before
    lines = _lines(caplog)
    assert len(lines) == 2 and all(ln.startswith("van move refused: ") and why in ln for ln in lines), lines
    assert "nothing changed" in lines[0] and "skipped" not in caplog.text
    for word in ("not json", "xxxxxxxx", "NaN", "1e999", "[[[[", "13:20Z"):
        assert word not in caplog.text, word  # a payload is never logged
    # the sensor goes again (the card stops waiting), still the -5 move
    pubs = [json.loads(p) for t, p, _ in fake.msgs[n:] if t == "flight_watcher/layover_van"]
    assert len(pubs) == 2 and all(p["adjust_min"] == -5 and p["local"] == "05:20" for p in pubs)


def test_no_van_in_hand_is_refused(tmp_path, monkeypatch, caplog):
    W, fake, st, _ = _w(tmp_path, monkeypatch)
    with caplog.at_level(logging.INFO, logger=W.log.name):
        caplog.clear()
        assert W.van_adjust_cmd(fake, json.dumps({"van": VID, "minutes": -5})) is False  # before the first sweep
    assert "van_adjust" not in W.S and _lines(caplog) == ["van move refused: no van in hand; nothing changed"]


def test_a_pilot_instance_refuses_it_and_keeps_nothing(tmp_path, monkeypatch, caplog):
    W, fake, st, reads = _w(tmp_path, monkeypatch, "pilot2")
    assert W.van_tick(_at(180), mono=0) == [] and reads == [] and fake.msgs == []
    before = json.dumps(W.S, sort_keys=True)
    with caplog.at_level(logging.INFO, logger=W.log.name):
        _move(W, fake, -5, prefix="flight_watcher_pilot2")  # refused by roles before the handler
        assert W.van_adjust_cmd(fake, json.dumps({"van": VID, "minutes": -5})) is False
    assert json.dumps(W.S, sort_keys=True) == before and fake.msgs == [] and "van_adjust" not in W.S
    assert "MQTT van/adjust/set refused: not for a pilot instance (admin_pushes)" in caplog.text
    assert "van move refused: not for a pilot instance" in caplog.text
    # roles: the admin's only, never a portal's (the contract is unchanged)
    assert roles.SUBS["van/adjust/set"] == "admin_pushes" and "van/adjust/set" in roles.NOT_ON_PORTAL
    assert "van/adjust/set" not in roles.PORTAL_CMDS + roles.PORTAL_REFUSED
    for portal in (False, True):
        assert ("van/adjust/set", 0) not in roles.subscriptions("pilot2", portal)
        assert not roles.sub_allowed("van/adjust/set", "pilot2", portal)
    assert roles.portal_sub("van/adjust/set") is None
    assert b"van/adjust" not in PT.contract_text().encode("utf-8")


def test_the_portal_spool_refuses_it(tmp_path):
    in_dir = tmp_path / "in"
    in_dir.mkdir()
    sp = PT.Spool("demo", now=lambda: 1763600000.5)
    cmd = {"fwp": 1, "id": "00000000c0de0f75", "pilot": "demo", "ts": 1763600000001, "sub": "van/adjust/set",
           "payload": json.dumps({"van": VID, "minutes": -5}), "session": "5e55105e55105e55"}
    name = f"{cmd['ts']}-{cmd['id']}.json"
    (in_dir / name).write_text(json.dumps(cmd))
    with pytest.raises(PT.PortalError):
        sp.take(str(in_dir / name))


def test_a_restart_keeps_the_move(tmp_path, monkeypatch, caplog):
    W, fake, st, _ = _w(tmp_path, monkeypatch)
    W.van_tick(_at(180), mono=0)
    _move(W, fake, -15)
    W, fake, st, _ = _w(tmp_path, monkeypatch)  # the module again, the same /data
    assert W.S["van_adjust"] == {VID: -15}
    with caplog.at_level(logging.INFO, logger=W.log.name):
        caplog.clear()
        W.van_tick(_at(170), mono=0)
    s = _last(fake, "layover_van")
    assert (s["local"], s["adjust_min"], s["orig_local"]) == ("05:10", -15, "05:25")
    line, = [ln for ln in _lines(caplog) if ln.startswith("van: H3681")]
    assert line.startswith("van: H3681 LAS 2026-11-18 at 05:10 PST (03:10 HST 2026-11-18)")
    assert line.endswith("(from Hark; moved -15 min by Ryan; Hark says 05:25)")


def test_van_tick_sends_the_moved_vans_alerts(tmp_path, monkeypatch):
    W, fake, st, _ = _w(tmp_path, monkeypatch)
    W.van_tick(_at(180), mono=0)
    _move(W, fake, -15)  # 05:10 PST, 13:10 UTC
    moved = LAS_VAN - timedelta(minutes=15)
    assert W.van_tick(_at(31, moved), mono=10) == []
    assert W.van_tick(_at(30, moved), mono=20) == [30]
    assert W.van_tick(_at(30), mono=30) == []  # the van as read had its 30 min mark here: nothing for it
    assert W.van_tick(_at(10, moved), mono=40) == [10]
    evs = [e for e, _ in _vans(fake)]
    assert [(e["minutes"], e["van_local"], e["key"]) for e in evs] == [
        (30, "05:10", "H3681|2026-11-18T13:10Z|30"), (10, "05:10", "H3681|2026-11-18T13:10Z|10")]
    assert evs[0]["message"] == "Van in 30 min: 05:10 PST (03:10 HST), Example Desert Hotel lobby"
    assert evs[0]["title"] == "Van LAS 05:10 PST" and evs[0]["van_utc"] == "2026-11-18T13:10:00+00:00"
    assert [a["status"] for a in _last(fake, "layover_van")["alerts"]] == ["sent", "sent"]
    assert W.van_tick(moved + timedelta(minutes=1), mono=50) == []


def test_a_move_after_an_alert_is_a_new_van_time(tmp_path, monkeypatch):
    """The 1.7.1 rules for a van moved after its 30 min alert went: the moved van's alerts are new keys; a late start
    sends only the latest one still due, worded with the minutes really left; nothing after the van."""
    W, fake, st, _ = _w(tmp_path, monkeypatch)
    assert W.van_tick(_at(30), mono=0) == [30]  # 04:55 PST for 05:25
    assert W.van_tick(_at(27), mono=10) == []
    _move(W, fake, -15)  # 05:10 at 04:58: its 30 min mark has passed, its 10 min mark is ahead
    assert W.van_tick(_at(27) + timedelta(seconds=10), mono=20) == []  # the taps settle first (VAN_ADJUST_SETTLE_S)
    assert W.van_tick(_at(27) + timedelta(seconds=40), mono=25) == [30]
    ev = _vans(fake)[-1][0]
    assert (ev["minutes"], ev["minutes_left"], ev["van_local"]) == (30, 12, "05:10")
    assert ev["message"].startswith("Van in 12 min: 05:10 PST")
    moved = LAS_VAN - timedelta(minutes=15)
    assert W.van_tick(_at(10, moved), mono=30) == [10]
    # moved back to 05:25: its own 30 min alert went already and is never sent again; its 10 min one goes at its mark
    _move(W, fake, 0)
    assert W.van_tick(_at(12), mono=40) == [] and W.van_tick(_at(10), mono=50) == [10]
    assert [e["minutes"] for e, _ in _vans(fake)] == [30, 30, 10, 10]
    # a move into the past: nothing is sent, the sensor says missed
    W2, fake2, st2, _ = _w(tmp_path / "b", monkeypatch)
    W2.van_tick(_at(20), mono=0)
    n = len(_vans(fake2))
    _move(W2, fake2, -30)  # 04:55, now 05:05
    assert W2.van_tick(_at(20) + timedelta(seconds=20), mono=10) == [] and len(_vans(fake2)) == n
    assert [a["status"] for a in _last(fake2, "layover_van")["alerts"]] == ["missed", "missed"]


def test_a_changed_van_drops_the_move_with_one_line(tmp_path, monkeypatch, caplog):
    W, fake, st, _ = _w(tmp_path, monkeypatch)
    W.van_tick(_at(180), mono=0)
    _move(W, fake, -15)
    with caplog.at_level(logging.INFO, logger=W.log.name):
        caplog.clear()
        # Hark's sensor gone for a while: the van is not known, the move is not dropped
        st.clear()
        W.van_tick(_at(170), mono=100)
        assert _last(fake, "layover_van")["at"] is None
        st["sensor.hark_working_flight"] = (LAS_STATE, las())
        W.van_tick(_at(169), mono=200)
        assert _last(fake, "layover_van")["local"] == "05:10"
        # the company changed the van to 05:40: the old move no longer applies
        st["sensor.hark_working_flight"] = ("x", las(van="5:40 AM (05:40) Wed 2026-11-18, Example lobby"))
        for i in range(3):
            W.van_tick(_at(160 - i), mono=300 + i * 100)
    s = _last(fake, "layover_van")
    assert (s["local"], s["adjust_min"], s["van_id"]) == ("05:40", 0, "H3681|2026-11-18T13:40Z") and "orig_local" not in s
    assert _lines(caplog, "van: the").count("van: the -15 min move no longer applies: the van time changed") == 1
    assert len(_lines(caplog, "van: the")) == 1
    assert W.S["van_adjust"] == {VID: -15}  # kept within the bound; it is not the van in hand's
    with caplog.at_level(logging.INFO, logger=W.log.name):
        assert W.van_adjust_cmd(fake, json.dumps({"van": VID, "minutes": -20})) is False  # a stale card
    assert "van move refused: not the van in hand (the van time changed); nothing changed" in caplog.text
    # another pairing: the same
    _move(W, fake, 5, van="H3681|2026-11-18T13:40Z")
    st["sensor.hark_working_flight"] = ("x", las(pairing="H3700"))
    with caplog.at_level(logging.INFO, logger=W.log.name):
        W.van_tick(_at(100), mono=900)
    assert _last(fake, "layover_van")["pairing"] == "H3700" and _last(fake, "layover_van")["adjust_min"] == 0
    assert "van: the +5 min move no longer applies: the van time changed" in caplog.text


def test_at_most_8_moves_kept_and_the_van_in_hands_always(tmp_path, monkeypatch):
    W, fake, st, _ = _w(tmp_path, monkeypatch)
    ids = []
    for i in range(10):  # ten vans in a row, each moved once
        st["sensor.hark_working_flight"] = ("x", las(van=f"5:{10 + i:02d} AM (05:{10 + i:02d}) Wed 2026-11-18, X"))
        W.van_tick(_at(300), mono=i * 100)
        vid = _last(fake, "layover_van")["van_id"]
        ids.append(vid)
        _move(W, fake, -5, van=vid)
    assert list(W.S["van_adjust"]) == ids[2:] and set(W.S["van_adjust"].values()) == {-5}
    # the van in hand's is kept even when it is the oldest entry
    adj = {ids[0]: 10, **{f"H3700|2026-11-{d:02d}T10:00Z": 5 for d in range(1, 10)}}
    kept = W.van_adjust_keep(adj, ids[0])
    assert len(kept) == 8 and kept[ids[0]] == 10 and "H3700|2026-11-01T10:00Z" not in kept
    assert "H3700|2026-11-09T10:00Z" in kept
    # a hand-edited state cannot put a bad move in
    W.S["van_adjust"] = {"a": 7, "b": "5", "c": True, "d": 200, "e": 0, "f": -5.0, VID: -10, "g" * 200: 5}
    assert W.van_adjusts() == {VID: -10}
    W.S["van_adjust"] = ["not", "a", "dict"]
    assert W.van_adjusts() == {}


def test_van_keep_keeps_the_original_vans_keys_while_it_is_moved(tmp_path, monkeypatch):
    W, fake, st, _ = _w(tmp_path, monkeypatch)
    info = las_info()
    moved = LO.adjusted(info, -15)
    old = {f"H9{i:03d}|2026-10-01T00:00Z|30": {"how": "sent", "at": f"2026-11-{1 + i % 9:02d}T00:00:00"}
           for i in range(60)}
    mine = {LO.key(info, 30): {"how": "sent", "at": "2026-10-01T00:00:00"},
            LO.key(moved, 30): {"how": "sent", "at": "2026-10-01T00:00:01"}}
    kept = W.van_keep({**old, **mine}, moved)
    assert LO.key(info, 30) in kept and LO.key(moved, 30) in kept and len(kept) == W.VAN_KEEP


def test_a_van_setting_works_on_the_moved_van(tmp_path, monkeypatch):
    W, fake, st, _ = _w(tmp_path, monkeypatch)
    W.van_tick(_at(180), mono=0)
    _move(W, fake, -15)
    moved = LAS_VAN - timedelta(minutes=15)
    W.van_tick(_at(60, moved), mono=5)  # the sweep that sees the move (its alerts wait VAN_ADJUST_SETTLE_S from it)
    assert W.van_setting_cmd(fake, "van/first_min/set", "45", now=_at(50, moved))
    assert W.van_tick(_at(45, moved), mono=10) == [45]
    assert _vans(fake)[-1][0]["van_local"] == "05:10"


# ---------------------------------------------------------------- the layover card (Chromium)
def _adj_states(tmp_path, minutes=0, source="hark", adjustable=True, **kw):
    """The layover card's states with the Watcher's van sensor as van_tick makes it on the admin's instance, the van
    moved by minutes (SYD, Hark's 19:40 AEDT; or the pairings package's 19:25 with source package)."""
    st = _states(tmp_path, **kw)
    if source == "package":
        from test_van_package import package
        leg = {"pairing": "H3681", "start": "2026-11-10", "city": "SYD", "flt": "852", "dep": "21:40",
               "date": "2026-11-12"}
        info, why = LO.package_van([LO.package_vans(package())], leg)
    else:
        info, why = LO.van_info(st["sensor.hark_working_flight"]["attributes"], st["sensor.hark_working_flight"]["state"])
    st["sensor.flight_watcher_layover_van"]["attributes"] = LO.sensor(LO.adjusted(info, minutes), why, {}, NOW,
                                                                      adjustable=adjustable)
    return st


def _sensor_js(st, **over):
    a = dict(st["sensor.flight_watcher_layover_van"]["attributes"], **over)
    return f"window.setStates({{'sensor.flight_watcher_layover_van': {{state: 'x', last_updated: '{id(a)}', attributes: {json.dumps(a)}}}}})"


def _moved_sensor(st, minutes, source="hark"):
    """The sensor after the Watcher moved the van to minutes (what the card waits for)."""
    if source == "package":
        from test_van_package import package
        leg = {"pairing": "H3681", "start": "2026-11-10", "city": "SYD", "flt": "852", "dep": "21:40",
               "date": "2026-11-12"}
        info, why = LO.package_van([LO.package_vans(package())], leg)
    else:
        info, why = LO.van_info(st["sensor.hark_working_flight"]["attributes"], st["sensor.hark_working_flight"]["state"])
    return LO.sensor(LO.adjusted(info, minutes), why, {}, NOW, adjustable=True)


def _set_sensor(pg, attrs, tag):
    pg.evaluate("([a, t]) => window.setStates({'sensor.flight_watcher_layover_van': {state: 'x', last_updated: t, attributes: a}})",
                [attrs, tag])


def _adj(pg):
    return pg.evaluate("""() => { const r = window.root(), q = (s) => r.querySelector(s);
        const b = (s) => { const e = q(s); return e ? {text: e.textContent.trim(), label: e.getAttribute('aria-label'),
          disabled: e.disabled, ariaDisabled: e.getAttribute('aria-disabled')} : null; };
        return {minus: b('[data-vadj="-5"]'), plus: b('[data-vadj="5"]'), back: b('[data-vadj="0"]'),
                pend: (q('[data-vadjpend]') || {}).textContent || '', msg: (q('[data-vadjmsg]') || {}).textContent || '',
                moved: (q('[data-vmoved]') || {}).textContent || '', time: (q('[data-van] .vt') || {}).textContent || '',
                hst: (q('[data-van] .vh') || {}).textContent || '', src: (q('[data-vansrc]') || {}).textContent || '',
                harkvan: (q('[data-harkvan]') || {}).textContent || '', cd: (q('[data-cd]') || {}).textContent || '',
                vp: (q('.vp') || {}).textContent || ''}; }""")


def _calls(pg):
    return [(c[2]["topic"], json.loads(c[2]["payload"])) for c in pg.evaluate("window.calls")]


def test_the_buttons_show_only_when_the_watcher_says_adjustable(browser, tmp_path):  # noqa: F811
    pg = browser.new_page(viewport={"width": 390, "height": 844})
    pg.set_content(_page(_adj_states(tmp_path / "a")))
    got = _adj(pg)
    assert got["minus"] == {"text": "−5 min", "label": "Van 5 minutes earlier", "disabled": False, "ariaDisabled": None}
    assert got["plus"] == {"text": "+5 min", "label": "Van 5 minutes later", "disabled": False, "ariaDisabled": None}
    assert got["back"] is None and got["moved"] == "" and got["pend"] == "" and got["time"] == "19:40"
    pg.close()
    # a sensor that does not say adjustable (a 1.7.10 Watcher, a pilot's copy), Hark's van the Watcher did not place,
    # no van, or the portal's copy of the card: no buttons
    st_hark_other = _adj_states(tmp_path / "c")
    st_hark_other["sensor.hark_working_flight"]["attributes"]["van"] = "8:10 PM (20:10) Thu 2026-11-12, Example lobby"
    st_novan = _adj_states(tmp_path / "d")
    st_novan["sensor.hark_working_flight"]["attributes"]["van"] = ""
    st_novan["sensor.hark_working_flight"]["state"] = "Layover SYD"
    st_novan["sensor.flight_watcher_layover_van"]["attributes"] = LO.sensor(None, "no van time", {}, NOW, adjustable=True)
    portal = PT.portal_card(SRC)
    assert portal != SRC and "const FW_PORTAL = true;" in portal
    for name, html in (("not adjustable", _page(_adj_states(tmp_path / "b", adjustable=False))),
                       ("another van", _page(st_hark_other)), ("no van", _page(st_novan)),
                       ("portal", _page(_adj_states(tmp_path / "e")).replace(SRC, portal))):
        pg = browser.new_page(viewport={"width": 390, "height": 844})
        pg.set_content(html)
        got = _adj(pg)
        assert (got["minus"], got["plus"], got["back"]) == (None, None, None), name
        assert pg.evaluate("!!window.root().querySelector('[data-vadjrow]')") is False, name
        pg.close()


def test_a_press_publishes_the_absolute_move_and_waits_for_the_watcher(browser, tmp_path):  # noqa: F811
    st = _adj_states(tmp_path)
    pg = browser.new_page(viewport={"width": 390, "height": 844})
    pg.set_content(_page(st))
    card = pg.locator("flight-watcher-layover-card")
    card.locator('[data-vadj="-5"]').click()
    pg.wait_for_function("window.calls.length === 1")
    assert pg.evaluate("window.calls[0][0] + '/' + window.calls[0][1]") == "mqtt/publish"
    assert _calls(pg) == [(TOPIC, {"van": "H3681|2026-11-12T08:40Z", "minutes": -5})]
    got = _adj(pg)
    assert got["pend"] == "Saving..." and got["time"] == "19:40"  # the Watcher's time until it says the new one
    # one move at a time (review F1): a second press while saving does nothing; an unrelated update keeps it waiting
    card.locator('[data-vadj="-5"]').click(force=True)
    pg.wait_for_timeout(100)
    assert len(_calls(pg)) == 1
    pg.evaluate("window.setStates({'sensor.flight_watcher_layover_notes': {...window.H.states['sensor.flight_watcher_layover_notes'], last_updated: 'n9'}})")
    assert _adj(pg)["pend"] == "Saving..."
    # the Watcher's answer (-5) ends the wait; the next press goes on from it (absolute: -10), never from 0 twice
    _set_sensor(pg, _moved_sensor(st, -5), "v2")
    got = _adj(pg)
    assert got["pend"] == "" and got["time"] == "19:35"
    card.locator('[data-vadj="-5"]').click()
    pg.wait_for_function("window.calls.length === 2")
    assert _calls(pg)[1] == (TOPIC, {"van": "H3681|2026-11-12T08:40Z", "minutes": -10})
    _set_sensor(pg, _moved_sensor(st, -10), "v3")
    got = _adj(pg)
    assert (got["pend"], got["msg"], got["time"]) == ("", "", "19:30")
    assert got["moved"] == "You moved it -10 min (Hark says 19:40)"
    assert got["hst"].strip() == "22:30 HST Wed" and got["cd"] == "in 2 h"  # HST and the countdown follow the move
    assert "30 min at 22:00 HST" in got["vp"]  # and the alerts' times
    assert got["back"]["text"] == "Back to 19:40" and got["src"] == "from Hark" and got["harkvan"] == ""
    # +5 from -10 is -5; Back is 0
    card.locator('[data-vadj="5"]').click()
    pg.wait_for_function("window.calls.length === 3")
    assert _calls(pg)[2] == (TOPIC, {"van": "H3681|2026-11-12T08:40Z", "minutes": -5})
    _set_sensor(pg, _moved_sensor(st, -5), "v4")
    card.locator('[data-vadj="0"]').click()
    pg.wait_for_function("window.calls.length === 4")
    assert _calls(pg)[3] == (TOPIC, {"van": "H3681|2026-11-12T08:40Z", "minutes": 0})
    assert _adj(pg)["pend"] == "Saving..."
    _set_sensor(pg, _moved_sensor(st, 0), "v5")
    got = _adj(pg)
    assert (got["pend"], got["moved"], got["back"], got["time"]) == ("", "", None, "19:40")
    pg.close()


def test_no_answer_in_10_s_says_not_saved_and_a_publish_error_says_so(browser, tmp_path):  # noqa: F811
    st = _adj_states(tmp_path)
    pg = browser.new_page(viewport={"width": 390, "height": 844})
    pg.set_content(_page(st))
    pg.evaluate("() => { window.tmo = []; window.setTimeout = (f, ms) => { window.tmo.push([f, ms]); return window.tmo.length; };"
                "window.clearTimeout = () => {}; }")
    card = pg.locator("flight-watcher-layover-card")
    card.locator('[data-vadj="5"]').click()
    pg.wait_for_function("window.calls.length === 1")
    assert pg.evaluate("window.tmo.map((t) => t[1])") == [10000] and _adj(pg)["pend"] == "Saving..."
    pg.evaluate("window.tmo[0][0]()")
    got = _adj(pg)
    assert (got["pend"], got["msg"], got["time"]) == ("", "Not saved, try again", "19:40")
    # a late answer clears the message
    _set_sensor(pg, _moved_sensor(st, 5), "v2")
    got = _adj(pg)
    assert (got["msg"], got["time"], got["moved"]) == ("", "19:45", "You moved it +5 min (Hark says 19:40)")
    # a publish that fails
    pg.evaluate("() => { window.H.callService = async () => { throw new Error('offline'); }; }")
    card.locator('[data-vadj="5"]').click()
    pg.wait_for_function("!!window.root().querySelector('[data-vadjmsg]')")
    got = _adj(pg)
    assert (got["pend"], got["msg"]) == ("", "Not saved, try again (offline)")
    # the van itself changed while waiting: not saved
    pg.evaluate("() => { window.H.callService = async (d, s, data) => { window.calls.push([d, s, data]); }; }")
    card.locator('[data-vadj="5"]').click()
    pg.wait_for_function("window.calls.length === 2")
    other = dict(_moved_sensor(st, 0), van_id="H3681|2026-11-12T08:50Z")
    _set_sensor(pg, other, "v3")
    assert (_adj(pg)["pend"], _adj(pg)["msg"]) == ("", "Not saved, try again")
    pg.close()


def test_the_ends_of_the_range_disable_their_button(browser, tmp_path):  # noqa: F811
    for minutes, off in ((120, "plus"), (-120, "minus"), (115, None)):
        st = _adj_states(tmp_path / str(minutes), minutes=minutes)
        pg = browser.new_page(viewport={"width": 390, "height": 844})
        pg.set_content(_page(st, theme=HA_LIGHT))
        got = _adj(pg)
        for k in ("minus", "plus"):  # aria-disabled, never disabled: it keeps the focus (review F2)
            want = k == off
            assert (got[k]["disabled"], got[k]["ariaDisabled"] == "true") == (False, want), (minutes, k)
        if off:
            pg.locator(f'flight-watcher-layover-card [data-vadj="{"5" if off == "plus" else "-5"}"]').click(force=True)
            pg.wait_for_timeout(100)
            assert pg.evaluate("window.calls.length") == 0, minutes
        con = pg.evaluate("window.fwContrast(window.root().host)")
        assert not con["fails"], json.dumps(con["fails"], indent=1)
        pg.close()
    # 115 + 5 = 120 is sent; both wait while saving, then the plus stays off at 120
    st = _adj_states(tmp_path / "x", minutes=115)
    pg = browser.new_page(viewport={"width": 390, "height": 844})
    pg.set_content(_page(st))
    pg.locator('flight-watcher-layover-card [data-vadj="5"]').click()
    pg.wait_for_function("window.calls.length === 1")
    got = _adj(pg)
    assert _calls(pg)[0][1]["minutes"] == 120 and got["plus"]["ariaDisabled"] == got["minus"]["ariaDisabled"] == "true"
    _set_sensor(pg, _moved_sensor(st, 120), "v2")
    got = _adj(pg)
    assert (got["plus"]["ariaDisabled"], got["minus"]["ariaDisabled"], got["plus"]["disabled"]) == ("true", None, False)
    pg.close()


def test_a_moved_package_van_says_the_package_and_hark_still_shows(browser, tmp_path):  # noqa: F811
    st = _adj_states(tmp_path, minutes=-15, source="package")
    pg = browser.new_page(viewport={"width": 390, "height": 844})
    pg.set_content(_page(st))
    got = _adj(pg)
    assert (got["time"], got["src"], got["harkvan"]) == ("19:10", "from the pairings package", "Hark says 19:40")
    assert got["moved"] == "You moved it -15 min (the package says 19:25)" and got["back"]["text"] == "Back to 19:25"
    pg.locator('flight-watcher-layover-card [data-vadj="0"]').click()
    pg.wait_for_function("window.calls.length === 1")
    assert _calls(pg) == [(TOPIC, {"van": "H3681|2026-11-12T08:25Z", "minutes": 0})]
    pg.close()
    # a package van moved onto Hark's own time: Hark's line goes only when it says the package's time
    st = _adj_states(tmp_path / "b", minutes=15, source="package")
    pg = browser.new_page(viewport={"width": 390, "height": 844})
    pg.set_content(_page(st))
    got = _adj(pg)
    assert (got["time"], got["harkvan"]) == ("19:40", "Hark says 19:40")
    pg.close()


def test_a_move_across_midnight_names_the_day(browser, tmp_path):  # noqa: F811
    a = _hark_full(van="12:05 AM (00:05) Thu 2026-11-12, Example Harbour Hotel lobby")
    st = _adj_states(tmp_path / "m", minutes=-10, hark_attrs=a, hark_state="Layover SYD, van 2026-11-12 00:05")
    pg = browser.new_page(viewport={"width": 390, "height": 844})
    pg.set_content(_page(st))
    got = _adj(pg)
    assert got["time"] == "23:55" and got["moved"] == "You moved it -10 min (Hark says 00:05 Thu)"
    assert got["back"]["text"] == "Back to 00:05 Thu"
    pg.close()


def test_every_value_is_escaped(browser, tmp_path):  # noqa: F811
    st = _adj_states(tmp_path, minutes=-15, source="package")
    va = st["sensor.flight_watcher_layover_van"]["attributes"]
    bad = '"><img src=x onerror="window.pwned=1">'
    va.update(orig_local=bad, orig_date=bad, van_id=bad)
    pg = browser.new_page(viewport={"width": 390, "height": 844})
    pg.set_content(_page(st))
    got = _adj(pg)
    assert bad in got["moved"] and bad in got["back"]["text"]
    assert pg.evaluate("window.root().querySelectorAll('img').length") == 1  # Hark's one https photo only
    assert pg.evaluate("window.pwned") is None
    pg.locator('flight-watcher-layover-card [data-vadj="-5"]').click()
    pg.wait_for_function("window.calls.length === 1")
    assert _calls(pg) == [(TOPIC, {"van": bad, "minutes": -20})]  # data, sent back as it came (the Watcher checks it)
    pg.close()


def test_the_focus_stays_on_the_button_through_its_answer(browser, tmp_path):  # noqa: F811
    st = _adj_states(tmp_path)
    pg = browser.new_page(viewport={"width": 390, "height": 844})
    pg.set_content(_page(st))
    focused = "() => { const a = window.root().activeElement; return a ? a.getAttribute('data-vadj') : null; }"
    pg.evaluate("window.root().querySelector('[data-vadj=\"5\"]').focus()")
    pg.keyboard.press("Enter")
    pg.wait_for_function("window.calls.length === 1")
    assert pg.evaluate(focused) == "5"
    _set_sensor(pg, _moved_sensor(st, 5), "v2")
    assert pg.evaluate(focused) == "5" and _adj(pg)["time"] == "19:45"
    pg.keyboard.press("Enter")
    pg.wait_for_function("window.calls.length === 2")
    assert _calls(pg)[1][1]["minutes"] == 10
    pg.close()


@pytest.mark.parametrize("theme", ["light", "dark", "ha-light", "ha-dark"])
def test_the_buttons_are_44_px_fit_390_and_read_in_light_and_dark(browser, tmp_path, theme):  # noqa: F811
    colors = {"light": LIGHT, "dark": DARK, "ha-light": HA_LIGHT, "ha-dark": HA_DARK}[theme]
    for state in ("still", "moved", "saving", "not saved"):
        st = _adj_states(tmp_path / state.replace(" ", "_"), minutes=-15 if state != "still" else 0)
        pg = browser.new_page(viewport={"width": 390, "height": 844})
        pg.set_content(_page(st, theme=colors))
        if state == "saving":
            pg.evaluate("() => { window.H.callService = () => new Promise(() => {}); }")
            pg.locator('flight-watcher-layover-card [data-vadj="-5"]').click()
            assert _adj(pg)["pend"] == "Saving..."
        elif state == "not saved":
            pg.evaluate("() => { window.H.callService = async () => { throw new Error('no connection'); }; }")
            pg.locator('flight-watcher-layover-card [data-vadj="-5"]').click()
            pg.wait_for_function("!!window.root().querySelector('[data-vadjmsg]')")
        sizes = pg.evaluate("""() => [...window.root().querySelectorAll('[data-vadj]')].map((e) => {
            const r = e.getBoundingClientRect(); return [e.getAttribute('data-vadj'), Math.round(r.width), Math.round(r.height)]; })""")
        assert len(sizes) == (3 if state != "still" else 2), sizes
        for sel, w, h in sizes:
            assert w >= 44 and h >= 44, (state, sel, w, h)
        # under the van time block, inside the card, no sideways scroll at 390 px
        row = pg.locator("flight-watcher-layover-card [data-vadjrow]").bounding_box()
        van = pg.locator("flight-watcher-layover-card [data-van]").bounding_box()
        card = pg.locator("flight-watcher-layover-card ha-card").bounding_box()
        assert row["y"] >= van["y"] + van["height"] - 1 and row["x"] + row["width"] <= card["x"] + card["width"] + 1
        assert pg.evaluate("document.documentElement.scrollWidth") <= 390
        va = pg.locator("flight-watcher-layover-card [data-va]").bounding_box()
        assert va["y"] >= row["y"] + row["height"] - 1  # the van alerts tick box stays under it
        con = pg.evaluate("window.fwContrast(window.root().host)")
        assert not con["fails"], (state, json.dumps(con["fails"], indent=1))
        for d in (tmp_path, SHOTS):
            if d:
                pg.screenshot(path=os.path.join(str(d), f"fw0075_van_adjust_390_{theme}_{state.replace(' ', '_')}.png"),
                              clip={"x": 0, "y": 0, "width": 390, "height": 420})
        pg.close()


def test_the_cards_range_is_the_watchers():
    m = re.search(r"const FW_VAN_ADJUST = \{ lo: (-?\d+), hi: (-?\d+), step: (\d+) \};", SRC)
    assert m and (int(m.group(1)), int(m.group(2))) == LO.ADJUST_RANGE and int(m.group(3)) == LO.ADJUST_STEP
    assert "const FW_PORTAL = false;" in SRC and chr(0x2014) not in SRC
    assert PT.card_subs(SRC, "flight_watcher") >= {"van/adjust/set", "layover/note"}


# ---------------------------------------------------------------- review fixes (the Watcher)
def test_taps_between_sweeps_send_one_alert_for_the_van_chosen(tmp_path, monkeypatch):
    """Review F1 (alerts): Ryan's own case inside the alert window. The 05:25 van's 30 min alert went at 04:55; at 04:56
    he taps -5 three times to reach 05:10 with a sweep (10 s) between taps. The times passed through on the way
    (05:20, 05:15) send nothing and leave no key; the van he chose gets its one late alert once his taps settle
    (VAN_ADJUST_SETTLE_S from the first sweep that saw his last move)."""
    W, fake, st, _ = _w(tmp_path, monkeypatch)
    assert W.VAN_ADJUST_SETTLE_S == 30
    assert W.van_tick(_at(30), mono=0) == [30]  # 04:55 for 05:25
    t = _at(29)  # 04:56
    for i, m in enumerate((-5, -10, -15)):
        _move(W, fake, m)
        assert W.van_tick(t + timedelta(seconds=10 * i + 10), mono=10 + 10 * i) == [], m
    assert W.van_tick(t + timedelta(seconds=40), mono=40) == []
    assert W.van_tick(t + timedelta(seconds=50), mono=50) == []
    assert W.van_tick(t + timedelta(seconds=60), mono=60) == [30]  # 30 s after the sweep that saw the last tap
    for k in range(1, 6):
        assert W.van_tick(t + timedelta(seconds=60 + 10 * k), mono=60 + 10 * k) == []
    evs = [e for e, _ in _vans(fake)]
    assert [e["message"].split(",")[0] for e in evs] == ["Van in 30 min: 05:25 PST (03:25 HST)",
                                                         "Van in 13 min: 05:10 PST (03:10 HST)"]
    done = W.DB.get(W.VAN_DONE)
    assert not [k for k in done if "13:20Z" in k or "13:15Z" in k], done
    # its 10 min alert goes at its mark, no settle on it (no move since)
    moved = LAS_VAN - timedelta(minutes=15)
    assert W.van_tick(_at(10, moved), mono=200) == [10]
    # an unmoved van is never held
    W2, fake2, _, _ = _w(tmp_path / "b", monkeypatch)
    assert W2.van_tick(_at(30), mono=0) == [30]


def test_a_settle_never_outlasts_its_length_when_the_clock_goes_back(tmp_path, monkeypatch):
    W, fake, st, _ = _w(tmp_path, monkeypatch)
    W.van_tick(_at(180), mono=0)
    _move(W, fake, -15)
    t = _at(29, LAS_VAN - timedelta(minutes=15))  # past the moved van's 30 min mark
    assert W.van_tick(t + timedelta(hours=1), mono=10) == []  # the sweep that sees the move, its clock an hour fast
    assert W.van_tick(t, mono=20) == [30]  # the clock set right: the wait is over, never an hour and 30 s


def test_a_move_while_hark_is_gone_logs_the_reason_once(tmp_path, monkeypatch, caplog):
    """Review F2 (security lens): a move taken for the van in hand while a sweep has no van (a card drawn before Hark's
    sensor went, a retry) does not make the next sweep log the same reason again."""
    W, fake, st, _ = _w(tmp_path, monkeypatch)
    W.van_tick(_at(180), mono=0)
    with caplog.at_level(logging.INFO, logger=W.log.name):
        caplog.clear()
        st.clear()
        W.van_tick(_at(170), mono=100)
        assert _last(fake, "layover_van")["at"] is None
        assert W.van_adjust_cmd(fake, json.dumps({"van": VID, "minutes": -15})) is True  # the van as a setting takes it
        assert W.S["van_adjust"] == {VID: -15}
        W.van_tick(_at(169), mono=200)
        W.van_tick(_at(168), mono=300)
        st["sensor.hark_working_flight"] = (LAS_STATE, las())  # Hark is back with the same van
        W.van_tick(_at(160), mono=400)
        W.van_tick(_at(159), mono=500)
    assert _lines(caplog) == [
        "van alerts: none (Hark's working flight is not in Home Assistant)",
        "van: moved -15 min by Ryan: H3681 LAS 2026-11-18 05:10 PST (Hark says 05:25)",
        "van: H3681 LAS 2026-11-18 at 05:10 PST (03:10 HST 2026-11-18), alerts 30 and 10 min before (from Hark; "
        "moved -15 min by Ryan; Hark says 05:25)"]
    assert _last(fake, "layover_van")["local"] == "05:10"


def test_a_van_changed_while_the_app_was_down_drops_the_move_with_one_line(tmp_path, monkeypatch, caplog):
    """Review F5 and F3: the move applied is kept with the state (S["van_moved"]), so a van that changed while the app
    was down (an update, a restart) still says once that the move no longer applies; a later restart says nothing
    (the move in S["van_adjust"] of a van no longer in hand is never taken for the applied one)."""
    W, fake, st, _ = _w(tmp_path, monkeypatch)
    W.van_tick(_at(180), mono=0)
    _move(W, fake, -15)
    W.van_tick(_at(179), mono=10)
    assert W.S["van_moved"] == [VID, -15]
    later = "5:40 AM (05:40) Wed 2026-11-18, Example lobby"
    for n in range(2):  # the restart, then another one
        W, fake, st, _ = _w(tmp_path, monkeypatch, text=later, state="x")
        with caplog.at_level(logging.INFO, logger=W.log.name):
            caplog.clear()
            W.van_tick(_at(170), mono=0)
            W.van_tick(_at(169), mono=100)
        s = _last(fake, "layover_van")
        assert (s["local"], s["adjust_min"], s["van_id"]) == ("05:40", 0, "H3681|2026-11-18T13:40Z")
        assert _lines(caplog, "van: the") == (["van: the -15 min move no longer applies: the van time changed"]
                                              if n == 0 else []), n
        assert W.S["van_adjust"] == {VID: -15} and "van_moved" not in W.S
    # a restart with the same van moved says nothing about it either
    W, fake, st, _ = _w(tmp_path / "same", monkeypatch)
    W.van_tick(_at(180), mono=0)
    _move(W, fake, -15)
    W, fake, st, _ = _w(tmp_path / "same", monkeypatch)
    with caplog.at_level(logging.INFO, logger=W.log.name):
        caplog.clear()
        W.van_tick(_at(170), mono=0)
    assert _lines(caplog, "van: the") == [] and _last(fake, "layover_van")["local"] == "05:10"
    # a hand-edited applied move cannot be a bad one
    for bad in ("x", [VID], [VID, 7], [VID, True], [VID, 0], [5, -15], ["g" * 200, -15], {"v": VID}):
        W.S["van_moved"] = bad
        assert W.van_moved() is None, bad


# ---------------------------------------------------------------- review fixes (the layover card)
_FOCUSED = "() => { const a = window.root().activeElement; return a ? a.getAttribute('data-vadj') : 'none'; }"
_FAKE_TIMERS = ("() => { window.tmo = []; window.setTimeout = (f, ms) => { window.tmo.push([f, ms]); return window.tmo.length; };"
                "window.clearTimeout = () => {}; }")
VAN_ID = "H3681|2026-11-12T08:40Z"


def _tap(pg, d):
    """A tap that does not wait for the button to look enabled (a quick second tap while saving)."""
    pg.locator(f'flight-watcher-layover-card [data-vadj="{d}"]').click(force=True)


def test_one_move_at_a_time_so_an_older_answer_never_settles_a_newer_tap(browser, tmp_path):  # noqa: F811
    """Review F1 (card): taps while a move is saving are ignored (the buttons aria-disabled, never disabled, like the
    1.7.2 tick box), each move is from the Watcher's adjust_min, and only the answer to the one command in flight ends
    "Saving...": so a lost last command still says "Not saved, try again" after 10 s."""
    st = _adj_states(tmp_path)
    pg = browser.new_page(viewport={"width": 390, "height": 844})
    pg.set_content(_page(st))
    pg.evaluate(_FAKE_TIMERS)
    for d in ("-5", "-5", "5"):  # -5, -5, +5 quickly
        _tap(pg, d)
    pg.wait_for_timeout(100)
    assert _calls(pg) == [(TOPIC, {"van": VAN_ID, "minutes": -5})]
    got = _adj(pg)
    assert got["pend"] == "Saving..." and got["time"] == "19:40"
    for k in ("minus", "plus"):
        assert (got[k]["disabled"], got[k]["ariaDisabled"]) == (False, "true"), k
    # that one command is lost: "Not saved, try again" after 10 s, the taps while waiting never sent
    pg.evaluate("window.tmo[window.tmo.length - 1][0]()")
    got = _adj(pg)
    assert (got["pend"], got["msg"], got["time"]) == ("", "Not saved, try again", "19:40")
    assert got["minus"]["ariaDisabled"] is None and len(_calls(pg)) == 1
    # +5 then -5: only the +5 goes, still saving (never a 0 that looks settled at once)
    _tap(pg, "5")
    _tap(pg, "-5")
    pg.wait_for_timeout(100)
    assert _calls(pg)[1:] == [(TOPIC, {"van": VAN_ID, "minutes": 5})] and _adj(pg)["pend"] == "Saving..."
    _set_sensor(pg, _moved_sensor(st, 5), "v2")  # its answer ends the wait
    got = _adj(pg)
    assert (got["pend"], got["time"], got["moved"]) == ("", "19:45", "You moved it +5 min (Hark says 19:40)")
    _tap(pg, "-5")  # from the Watcher's +5
    pg.wait_for_timeout(100)
    assert _calls(pg)[-1] == (TOPIC, {"van": VAN_ID, "minutes": 0}) and _adj(pg)["pend"] == "Saving..."
    pg.close()


def test_the_focus_stays_at_the_ends_of_the_range_and_when_back_goes(browser, tmp_path):  # noqa: F811
    """Review F2 (card): a button at an end of the range is aria-disabled and keeps its focus (a tap on it does
    nothing); when Back goes after its answer, the focus moves to -5 instead of falling to the page."""
    st = _adj_states(tmp_path / "end", minutes=115)
    pg = browser.new_page(viewport={"width": 390, "height": 844})
    pg.set_content(_page(st))
    pg.evaluate("window.root().querySelector('[data-vadj=\"5\"]').focus()")
    pg.keyboard.press("Enter")
    pg.wait_for_function("window.calls.length === 1")
    assert _calls(pg)[0][1]["minutes"] == 120 and pg.evaluate(_FOCUSED) == "5"
    _set_sensor(pg, _moved_sensor(st, 120), "v2")
    got = _adj(pg)
    assert (got["plus"]["disabled"], got["plus"]["ariaDisabled"], got["minus"]["ariaDisabled"]) == (False, "true", None)
    assert pg.evaluate(_FOCUSED) == "5" and pg.evaluate("document.activeElement.tagName") != "BODY"
    pg.keyboard.press("Enter")  # at the end: nothing sent
    pg.wait_for_timeout(100)
    assert len(_calls(pg)) == 1 and pg.evaluate(_FOCUSED) == "5"
    pg.close()
    st = _adj_states(tmp_path / "back", minutes=-15)
    pg = browser.new_page(viewport={"width": 390, "height": 844})
    pg.set_content(_page(st))
    pg.evaluate("window.root().querySelector('[data-vadj=\"0\"]').focus()")
    pg.keyboard.press("Enter")
    pg.wait_for_function("window.calls.length === 1")
    assert _calls(pg)[0][1]["minutes"] == 0 and pg.evaluate(_FOCUSED) == "0"
    _set_sensor(pg, _moved_sensor(st, 0), "v2")
    assert _adj(pg)["back"] is None and pg.evaluate(_FOCUSED) == "-5"
    pg.keyboard.press("Enter")  # and it works from there
    pg.wait_for_function("window.calls.length === 2")
    assert _calls(pg)[1][1]["minutes"] == -5
    pg.close()


def test_a_screen_reader_hears_saving_moved_and_not_saved(browser, tmp_path):  # noqa: F811
    """Review F4 (card): one visually hidden role=status (aria-live polite) element that every render keeps (outside
    the part drawn again), its text set when the move's state changes."""
    st = _adj_states(tmp_path)
    pg = browser.new_page(viewport={"width": 390, "height": 844})
    pg.set_content(_page(st))
    pg.evaluate(_FAKE_TIMERS)
    lives = pg.evaluate("""() => [...window.root().querySelectorAll('[role="status"]')].map((e) =>
        [e.getAttribute('aria-live'), e.getAttribute('aria-atomic'), e.hasAttribute('data-vadjlive'), !!e.closest('ha-card'),
         Math.round(e.getBoundingClientRect().width), getComputedStyle(e).display])""")
    assert lives == [["polite", "true", True, False, 1, "block"]]
    pg.evaluate("window.live0 = window.root().querySelector('[data-vadjlive]')")
    said = "() => { const l = window.root().querySelector('[data-vadjlive]'); return [l === window.live0, l.textContent]; }"
    assert pg.evaluate(said) == [True, ""]
    _tap(pg, "-5")
    pg.wait_for_timeout(50)
    assert pg.evaluate(said) == [True, "Saving"]
    _set_sensor(pg, _moved_sensor(st, -5), "v2")
    assert pg.evaluate(said) == [True, "Van moved to 19:35"]
    _set_sensor(pg, dict(_moved_sensor(st, -5), local="19:35"), "v3")  # an update with nothing new: said once
    assert pg.evaluate(said) == [True, "Van moved to 19:35"]
    _tap(pg, "0")
    pg.wait_for_timeout(50)
    assert pg.evaluate(said) == [True, "Saving"]
    _set_sensor(pg, _moved_sensor(st, 0), "v4")
    assert pg.evaluate(said) == [True, "Van back to 19:40"]
    _tap(pg, "5")
    pg.evaluate("window.tmo[window.tmo.length - 1][0]()")  # no answer in 10 s
    assert pg.evaluate(said) == [True, "Not saved, try again"]
    pg.evaluate("() => { window.H.callService = async () => { throw new Error('offline'); }; }")
    _tap(pg, "5")
    pg.wait_for_function("!!window.root().querySelector('[data-vadjmsg]')")
    assert pg.evaluate(said) == [True, "Not saved, try again (offline)"]
    pg.close()
