"""1.6.0 (FW-0061): a portal pilot's state export (PORTAL_CONTRACT.md 4.2): exactly portal_ids(), read from a fake HA
one GET per id, masked, signed, written atomically, also while the Watcher waits for its first logins; and the admin,
even handed the portal env by mistake, behaves exactly as in 1.5.0. Synthetic data, made-up names."""
import json
import logging
import os
import stat
import sys

import pytest

import portal as PT
import roles
from conftest import ha_state

PILOT2_IDS = sorted([
    "binary_sensor.flight_watcher_pilot2_session_ok", "button.flight_watcher_pilot2_check_now",
    "sensor.flight_watcher_pilot2_bid_calendar",  # 1.7.1 (FW-0070): a core entity (contract 4.2: no HOM release)
    "button.flight_watcher_pilot2_re_arm", "button.flight_watcher_pilot2_scan_crewtrac_charters_now",
    "input_number.flight_watcher_pilot2_federal_tax_pct", "input_number.flight_watcher_pilot2_longevity_year",
    "input_number.flight_watcher_pilot2_state_tax_pct", "input_text.flight_watcher_pilot2_er_trips",
    "number.flight_watcher_pilot2_hunt_check_every", "number.flight_watcher_pilot2_normal_check_every",
    "sensor.flight_watcher_pilot2_blocked_days", "sensor.flight_watcher_pilot2_charters",
    "sensor.flight_watcher_pilot2_finds", "sensor.flight_watcher_pilot2_flica_fetches",
    "sensor.flight_watcher_pilot2_improved_pay_gross", "sensor.flight_watcher_pilot2_last_check",
    "sensor.flight_watcher_pilot2_last_match", "sensor.flight_watcher_pilot2_last_new_pairing",
    "sensor.flight_watcher_pilot2_next_check", "sensor.flight_watcher_pilot2_ot_requests",
    "sensor.flight_watcher_pilot2_own_trip_times", "sensor.flight_watcher_pilot2_pickers",
    "sensor.flight_watcher_pilot2_pilot_schedule", "sensor.flight_watcher_pilot2_pot_count",
    "sensor.flight_watcher_pilot2_pilot_uploads",  # 1.7.2 (revision 3): synthesized from his uploads, never from HA
    "sensor.flight_watcher_pilot2_recall_o75", "sensor.flight_watcher_pilot2_reserve_grid",
    "sensor.flight_watcher_pilot2_rules_active", "sensor.flight_watcher_pilot2_schedule",
    "sensor.flight_watcher_pilot2_schedule_versions", "sensor.flight_watcher_pilot2_settings",
    "sensor.flight_watcher_pilot2_state", "sensor.flight_watcher_pilot2_swap_ideas",
    "sensor.flight_watcher_pilot2_swap_mode", "sensor.flight_watcher_pilot2_swap_test_requests",
    "sensor.flight_watcher_pilot2_tickets",  # 1.7.0 (contract 1 revision 2): his own tickets
    "sensor.flight_watcher_pilot2_tradeboard_pickups", "sensor.flight_watcher_pilot2_working_flight",
    "sensor.flight_watcher_pilot2_would_trade", "switch.flight_watcher_pilot2_hunt_mode",
    "switch.flight_watcher_pilot2_pause"])
PREF_IDS = {roles.pref_entity(k, "flight_watcher_pilot2") for k in roles.PREF_KEYS} | {
    "sensor.flight_watcher_pilot2_pilot_uploads"}  # the ids state.json synthesizes (never a GET to HA)
# what HA also holds and the pilot's export must never ask for: the house, the admin's, another pilot's
OTHERS = ["lock.front_door", "sensor.flight_watcher_state", "sensor.flight_watcher_finds",
          "sensor.flight_watcher_james_state", "input_number.flight_watcher_federal_tax_pct"]
CONTACT = {"name": "Doe, Jane", "phones": ["808-555-0100"], "emails": ["jane.doe@example.invalid"]}


def _states():
    st = {e: ha_state(e, "on") for e in PILOT2_IDS if e not in PREF_IDS}
    st["sensor.flight_watcher_pilot2_finds"] = ha_state("sensor.flight_watcher_pilot2_finds", "2", {
        "count": 2, "file_key": "ab" * 16, "rev": "0123456789ab", "finds": [{"pairing": "H9001"}]})
    st["sensor.flight_watcher_pilot2_pilot_schedule"] = ha_state("sensor.flight_watcher_pilot2_pilot_schedule", "10001", {
        "emp": "10001", "name": "Doe, Jane", "versions_file_key": "cd" * 16, "contact": CONTACT,
        "reconstructed": [{"pairing": "H9001", "contact": CONTACT}]})
    for e in OTHERS:
        st[e] = ha_state(e, "secret-other")
    return st


def _read(W, name):
    with open(os.path.join(W.PORTAL_DIR, "out", name), encoding="utf-8") as f:
        return json.load(f)


def _payload(W, name, kind):
    key = PT.load_key(W.PORTAL_KEY_FILE, create=False)
    return json.loads(PT.verify(PT.public_id(key), _read(W, name), kind, W.INSTANCE))


def _asked(ha):
    assert all(u.startswith("http://supervisor/core/api/states/") for u in ha.urls)
    return [u.rsplit("/", 1)[-1] for u in ha.urls]


def test_portal_ids_exact_for_a_pilot(portal_pilot):
    W, _ = portal_pilot("pilot2")
    assert sorted(W.portal_ids()) == PILOT2_IDS
    for e in W.portal_ids():
        assert ".flight_watcher_pilot2_" in e  # no admin id, no house id, no other pilot's
    for gone in ("uploads_on_file", "upload_status", "would_drop", "auto_swap_dry_run", "crew_index",
                 "update_schedules", "map_swap_pages_read_only"):
        assert not [e for e in W.portal_ids() if e.endswith("_" + gone)], gone
    W.RULES["list"] = [{"id": "sin_alert", "name": "SIN", "enabled": True, "mode": "alert",
                        "created_at": "2026-11-01T00:00:00+00:00"}]
    assert sorted(W.portal_ids()) == sorted(PILOT2_IDS + ["switch.flight_watcher_pilot2_rule_sin_alert_live"])
    topics = W.portal_topics()
    assert topics["flight_watcher_pilot2/finds"] == {"sensor.flight_watcher_pilot2_finds"}
    assert all(t.startswith("flight_watcher_pilot2/") for t in topics)


def test_export_reads_only_portal_ids_and_masks(portal_pilot):
    W, ha = portal_pilot("pilot2", states=_states())
    assert W.portal_start(threads=False)
    assert _asked(ha) == []  # 1.6.2: the pref helpers are never read (no seed from HA any more)
    ha.urls.clear()
    W.portal_export_once(full=True)
    asked = _asked(ha)
    assert sorted(asked) == sorted(set(PILOT2_IDS) - PREF_IDS) and len(asked) == len(set(asked))  # one GET per id
    assert not set(asked) & set(OTHERS)
    body = _payload(W, "state.json", "state")
    assert sorted(body["states"]) == PILOT2_IDS and body["ha_ok"] is True
    text = json.dumps(body)
    for leak in ("secret-other", "808-555-0100", "jane.doe@example.invalid", "u-secret-context", "context",
                 "ab" * 16, "cd" * 16):
        assert leak not in text, leak
    finds = body["states"]["sensor.flight_watcher_pilot2_finds"]
    assert finds["attributes"]["file_key"] == "0" * 32 and set(finds) == {"state", "attributes", "last_changed",
                                                                           "last_updated"}
    ps = body["states"]["sensor.flight_watcher_pilot2_pilot_schedule"]["attributes"]
    assert ps["versions_file_key"] == "0" * 32 and "contact" not in ps and "contact" not in ps["reconstructed"][0]
    # the pref helpers are synthesized from prefs.json, never read from HA
    fed = body["states"]["input_number.flight_watcher_pilot2_federal_tax_pct"]
    assert fed["state"] == "unknown" and fed["attributes"]["max"] == 45


def test_a_publish_marks_only_its_ids(portal_pilot):
    W, ha = portal_pilot("pilot2", states=_states())
    W.portal_start(threads=False)
    W.portal_export_once(full=True)
    ha.urls.clear()
    W.pub("finds", {"count": 3, "finds": [], "file_key": "ab" * 16, "rev": "x"})
    W.portal_export_once()
    assert _asked(ha) == ["sensor.flight_watcher_pilot2_finds"]
    ha.urls.clear()
    W.RULES["list"] = [{"id": "sin_alert", "name": "SIN", "enabled": True, "mode": "alert",
                        "created_at": "2026-11-01T00:00:00+00:00"}]
    W.MQ.publish("flight_watcher_pilot2/rule/sin_alert/live/state", "ON", retain=True)
    W.portal_export_once()
    assert _asked(ha) == ["switch.flight_watcher_pilot2_rule_sin_alert_live"]
    ha.urls.clear()
    W.MQ.publish("flight_watcher_pilot2/status", "online", retain=True)  # availability: every id again
    W.portal_export_once()
    assert sorted(_asked(ha)) == sorted(set(W.portal_ids()) - PREF_IDS)


def test_unchanged_state_is_not_rewritten_and_ha_down_keeps_the_last(portal_pilot):
    W, ha = portal_pilot("pilot2", states=_states())
    W.portal_start(threads=False)
    W.portal_export_once(full=True)
    first = _read(W, "state.json")
    W.MQ.publish(f"{W.T}/pot/state", "{}")  # a publish that changes nothing HA answers
    W.portal_export_once(full=False)
    assert _read(W, "state.json") == first  # same payload: no new write, no new seq
    # 1.7.1 (F#7, F#110): the full sweep is the heartbeat: the same payload in a new envelope, a later seq
    W.portal_export_once(full=True)
    beat = _read(W, "state.json")
    assert beat["seq"] > first["seq"] and beat["payload"] == first["payload"]
    first = beat
    ha.down = True
    W.portal_export_once(full=True)
    body = _payload(W, "state.json", "state")
    assert body["ha_ok"] is False and sorted(body["states"]) == PILOT2_IDS  # last good states kept
    assert _read(W, "state.json")["seq"] > first["seq"]


SETTINGS = "sensor.flight_watcher_pilot2_settings"


@pytest.mark.parametrize("miss", ["404", "502"])
def test_a_state_ha_had_no_answer_for_is_back_within_seconds(portal_pilot, miss):
    """Right after a start or during an HA restart HA answers 404 (no entity yet) or not at all for the settings
    sensor, and its topic is published only on connect and on a settings command: the next pass must not wait for
    the 5-minute sweep, or the Settings card has no pubkey (and must not save) that long."""
    st = _states()
    st[SETTINGS] = ha_state(SETTINGS, "ok", {"pubkey": "MIIB" + "A" * 40, "kid": "k1", "has_password": False})
    held = st.pop(SETTINGS)
    W, ha = portal_pilot("pilot2", states=st)
    W.portal_start(threads=False)
    t0 = 1800000000.0
    ha.down = miss == "502"
    W.portal_export_once(full=True, now=t0)
    assert SETTINGS not in _payload(W, "state.json", "state")["states"]
    assert W.portal_wait_s(now=t0) == W.EXPORT_RETRY_S  # the thread wakes for it, not in 300 s
    ha.down = False
    ha.states[SETTINGS] = held
    ha.urls.clear()
    W.portal_export_once(now=t0 + 5)  # not due yet: nothing read
    assert _asked(ha) == []
    W.portal_export_once(now=t0 + W.EXPORT_RETRY_S + W.EXPORT_DEBOUNCE_S)
    want = [SETTINGS] if miss == "404" else sorted(set(PILOT2_IDS) - PREF_IDS)  # 502 with nothing cached: all
    assert sorted(_asked(ha)) == want  # only the missing ones, one GET each
    got = _payload(W, "state.json", "state")["states"][SETTINGS]
    assert got["attributes"]["pubkey"] == held["attributes"]["pubkey"]
    assert W.EXPORT["retry"] == {} and W.portal_wait_s(now=t0 + 20) > 200


def test_an_entity_ha_never_has_costs_a_few_gets_not_one_per_pass(portal_pilot):
    st = _states()
    st.pop("sensor.flight_watcher_pilot2_charters")
    W, ha = portal_pilot("pilot2", states=st)
    W.portal_start(threads=False)
    t0 = 1800000000.0
    W.portal_export_once(full=True, now=t0)
    ha.urls.clear()
    for i in range(1, 600):  # 50 minutes of 5-second passes, no sweep
        W.portal_export_once(full=False, now=t0 + 5 * i)
    asked = _asked(ha)
    assert set(asked) == {"sensor.flight_watcher_pilot2_charters"} and len(asked) == 5  # 15, 30, 60, 120, 240 s
    assert W.EXPORT["retry"]["sensor.flight_watcher_pilot2_charters"][1] is None  # the sweep covers it from here
    assert W.portal_wait_s(now=t0 + 3000) == 0.0  # the sweep is due


def test_a_cached_state_ha_does_not_answer_for_is_kept_and_not_retried(portal_pilot):
    W, ha = portal_pilot("pilot2", states=_states())
    W.portal_start(threads=False)
    t0 = 1800000000.0
    W.portal_export_once(full=True, now=t0)
    ha.down = True
    W.portal_export_once(full=True, now=t0 + 300)
    assert W.EXPORT["retry"] == {}  # every state still shown from the cache; the next sweep reads them again
    assert W.portal_wait_s(now=t0 + 300) == W.EXPORT_SWEEP_S


def test_two_megabyte_cap(portal_pilot, caplog):
    st = _states()
    st["sensor.flight_watcher_pilot2_schedule"] = ha_state("sensor.flight_watcher_pilot2_schedule", "x",
                                                           {"big": "y" * (2 * 1024 * 1024)})
    W, ha = portal_pilot("pilot2", states=st)
    W.portal_start(threads=False)
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        W.portal_export_once(full=True)
        W.portal_export_once(full=True)
    assert not os.path.exists(os.path.join(W.PORTAL_DIR, "out", "state.json"))
    assert [r.getMessage() for r in caplog.records if "over" in r.getMessage()] == [
        "portal state over 2048 KB: not written"]


def test_atomic_write_and_modes(portal_pilot):
    W, _ = portal_pilot("pilot2", states=_states())
    W.portal_start(threads=False)
    W.portal_export_once(full=True)
    out = os.path.join(W.PORTAL_DIR, "out")
    for dp, _, fs in os.walk(out):
        for f in fs:
            assert not f.startswith("."), f  # no tmp left behind
            assert stat.S_IMODE(os.stat(os.path.join(dp, f)).st_mode) == 0o640, f
    assert sorted(n for n in os.listdir(out) if n.endswith(".json")) == ["events.json", "manifest.json",
                                                                          "results.json", "state.json"]


def test_export_runs_while_waiting_for_settings(portal_pilot, monkeypatch):
    """main() starts the portal before the needs_settings wait: James enters his first logins through it."""
    W, ha = portal_pilot("pilot2", states=_states())
    order = []
    monkeypatch.setattr(W, "mqtt_start", lambda: W.MQ)
    monkeypatch.setattr(W, "start_upload_janitor", lambda: None)
    real_start, real_sm = W.portal_start, W.set_machine
    monkeypatch.setattr(W, "portal_start", lambda: order.append("portal") or real_start(threads=False))
    monkeypatch.setattr(W, "set_machine", lambda st, note="": order.append(st) or real_sm(st, note))

    class Waiting(Exception):
        pass

    def sleep(s):
        if s == 3600:
            raise Waiting
    monkeypatch.setattr(W.time, "sleep", sleep)
    with pytest.raises(Waiting):
        W.main()
    assert order[:2] == ["portal", "needs_settings"] and W.EXPORT["on"]
    W.portal_export_once(full=True)
    assert "sensor.flight_watcher_pilot2_state" in _payload(W, "state.json", "state")["states"]
    evs = _payload(W, "events.json", "events")["events"]
    assert [e["kind"] for e in evs] == ["needs_settings"] and evs[0]["view"] == "settings"


# ---------------------------------------------------------------- the admin stays exactly 1.5.0
ADMIN_SETTINGS_KEYS = {"instance", "username", "my_name", "ctweb_username", "has_password", "has_ctweb_password", "at",
                       "result", "pubkey", "kid",
                       "doh"}  # 1.6.4: the Settings card's Date of hire field, on the admin's card too (Ryan, Nov 11)


def test_admin_never_has_a_portal_even_with_the_env(portal_pilot, monkeypatch, caplog, tmp_path):
    W, ha = portal_pilot("", portal=True)  # the env says portal; the admin still never has one
    assert not W.portal_on() and W.INSTANCE == ""
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        assert W.portal_start() is False
        W.set_machine("needs_settings", "x")
        W.pub("event/new_pairing", {"pairing": "H9001", "captain": "Doe, Jane"}, retain=False)
        assert W.portal_event("new_pairing", {"pairing": "H9001"}) is None
        assert W.pref_cmd('{"key": "federal_tax_pct", "value": 30}') is False
    lines = [r.getMessage() for r in caplog.records]
    assert [ln for ln in lines if "portal" in ln.lower() and "pref/set ignored" not in ln] == []
    assert not W.EXPORT["on"] and W.EXPORT["events_list"] == [] and ha.urls == []
    assert not (tmp_path / "share" / "fw_portal").exists()
    assert not [f for f in os.listdir(W.DATA) if f.startswith(("portal_", "prefs"))]
    assert "publish" not in vars(W.MQ)  # not wrapped
    assert [s for s, q in roles.subscriptions(W.INSTANCE, W.portal_on())] == [s for s, q in roles.subscriptions("")]
    assert "pref/set" not in [s for s, q in roles.subscriptions(W.INSTANCE, W.portal_on())]
    assert set(W.settings_state()) == ADMIN_SETTINGS_KEYS  # no ntfy keys on Ryan's settings sensor
    assert W.pref_get("federal_tax_pct") is None


def test_admin_mqtt_client_not_wrapped(portal_pilot, monkeypatch):
    W, _ = portal_pilot("", portal=True)

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

        def publish(self, *a, **k):
            pass
    monkeypatch.setattr(W.mqtt, "Client", Client)
    monkeypatch.setattr(W, "mqtt_creds", lambda: {"username": "u", "password": "p", "host": "h", "port": 1883})
    assert "publish" not in vars(W.mqtt_start())
    W2, _ = portal_pilot("pilot2")
    monkeypatch.setattr(W2.mqtt, "Client", Client)
    monkeypatch.setattr(W2, "mqtt_creds", lambda: {"username": "u", "password": "p", "host": "h", "port": 1883})
    assert "publish" in vars(W2.mqtt_start())  # a portal pilot's client notes what it publishes


def test_a_pilot_without_portal_is_1_5_0(portal_pilot, caplog):
    W, ha = portal_pilot("pilot2", portal=False)
    assert not W.portal_on() and W.portal_start() is False and ha.urls == []
    assert "pref/set" not in [s for s, q in roles.subscriptions(W.INSTANCE, W.portal_on())]
    assert set(W.settings_state()) == ADMIN_SETTINGS_KEYS
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        W.on_message(W.MQ, None, type("M", (), {"topic": "flight_watcher_pilot2/pref/set",
                                                "payload": b'{"key": "federal_tax_pct", "value": 30}'})())
    assert [r.getMessage() for r in caplog.records] == [
        "MQTT pref/set refused: the portal is off on this instance (prefs)"]
    assert not os.path.exists(W.PREFS_FILE)
    sys.modules.pop("watcher", None)
