"""0.10.0: a second pilot as another watcher.py instance (prefix, creds.json, settings topic, run.py). Synthetic only."""
import json
import os
import stat
import sys

import pytest


def _load(tmp_path, monkeypatch, instance, opts):
    monkeypatch.setenv("FLIGHT_WATCHER_DATA", str(tmp_path))
    if instance:
        monkeypatch.setenv("FLIGHT_WATCHER_PREFIX", f"flight_watcher_{instance}")
        monkeypatch.setenv("FLIGHT_WATCHER_INSTANCE", instance)
    else:
        monkeypatch.delenv("FLIGHT_WATCHER_PREFIX", raising=False)
        monkeypatch.delenv("FLIGHT_WATCHER_INSTANCE", raising=False)
    monkeypatch.delenv("FLIGHT_WATCHER_OPTIONS", raising=False)
    (tmp_path / "options.json").write_text(json.dumps(opts))
    sys.modules.pop("watcher", None)
    import watcher as W
    monkeypatch.setattr(W.time, "sleep", lambda s: None)
    W.S.clear()
    return W


OPTS = {"username": "opt_user", "password": "opt_pw", "ctweb_username": "opt_ct", "ctweb_password": "opt_ctpw",
        "my_name": "Optname", "second_pilot": "pilot2", "log_level": "info", "category_check": "HNL 332 FO"}


class FakeClient:
    def __init__(self):
        self.msgs = []

    def publish(self, topic, payload="", retain=False):
        self.msgs.append((topic, payload, retain))

    def subscribe(self, topic):
        pass


def _discovery(W):
    c = FakeClient()
    W.discovery(c)
    cfgs = {t: json.loads(p) for t, p, _ in c.msgs if p}
    return cfgs


def test_default_instance_unchanged(tmp_path, monkeypatch):
    W = _load(tmp_path, monkeypatch, "", OPTS)
    assert W.T == "flight_watcher" and W.INSTANCE == "" and W.AVAIL == "flight_watcher/status"
    assert W.OPTS["username"] == "opt_user" and W.OPTS["my_name"] == "Optname"
    assert W.DEV["identifiers"] == ["flight_watcher"] and W.DEV["name"] == "Flight Watcher"
    assert W.RULE_UID == "flight_watcher_rule" and W.UPLOADS == "/share/flight_watcher/uploads"
    assert W.finds_dir() == W.CARD_PAIRINGS == "/homeassistant/www/flight-watcher"
    cfgs = _discovery(W)
    assert cfgs["homeassistant/sensor/flight_watcher/schedule/config"]["unique_id"] == "flight_watcher_schedule"
    assert cfgs["homeassistant/sensor/flight_watcher/schedule/config"]["object_id"] == "flight_watcher_schedule"
    assert cfgs["homeassistant/sensor/flight_watcher/schedule/config"]["state_topic"] == "flight_watcher/schedule"
    assert cfgs["homeassistant/switch/flight_watcher/hunt_mode/config"]["unique_id"] == "flight_watcher_hunt_mode"
    assert cfgs["homeassistant/sensor/flight_watcher/settings/config"]["state_topic"] == "flight_watcher/settings/state"
    # 0.10.3: HA ignores object_id; default_entity_id keeps the flight_watcher_* ids
    assert cfgs["homeassistant/sensor/flight_watcher/schedule/config"]["default_entity_id"] == "sensor.flight_watcher_schedule"
    assert cfgs["homeassistant/switch/flight_watcher/hunt_mode/config"]["default_entity_id"] == "switch.flight_watcher_hunt_mode"
    assert cfgs["homeassistant/binary_sensor/flight_watcher/session_ok/config"]["default_entity_id"] == "binary_sensor.flight_watcher_session_ok"
    for topic, cfg in cfgs.items():
        comp = topic.split("/")[1]
        assert cfg["default_entity_id"] == f"{comp}.{cfg['object_id']}"
        assert cfg["object_id"] == "flight_watcher_" + W.ENTITY_SUFFIX.get(topic.split("/")[3], topic.split("/")[3])
    assert cfgs["homeassistant/sensor/flight_watcher/recall/config"]["default_entity_id"] == "sensor.flight_watcher_recall_o75"
    assert cfgs["homeassistant/sensor/flight_watcher/recall/config"]["unique_id"] == "flight_watcher_recall"


def test_instance_prefix_and_ids(tmp_path, monkeypatch):
    W = _load(tmp_path, monkeypatch, "pilot2", OPTS)
    assert W.T == "flight_watcher_pilot2" and W.INSTANCE == "pilot2" and W.AVAIL == "flight_watcher_pilot2/status"
    assert W.DEV["identifiers"] == ["flight_watcher_pilot2"] and W.DEV["name"] == "Flight Watcher (Pilot2)"
    assert W.RULE_UID == "flight_watcher_pilot2_rule"
    # FW-0066 (1.4.8): the uploads are base-wide, so a second pilot reads the shared folder; its captures stay its own
    assert W.UPLOADS == "/share/flight_watcher/uploads" and W.CAPTURE_DIR == "/share/flight_watcher/pilot2/captures"
    assert W.UPLOAD_STAGING == "/share/flight_watcher/uploads/.staging/flight_watcher_pilot2"
    assert W.finds_dir() == "/homeassistant/www/flight-watcher/pilot2" and W.CARD_PAIRINGS == "/homeassistant/www/flight-watcher"
    cfgs = _discovery(W)
    assert "homeassistant/sensor/flight_watcher/schedule/config" not in cfgs
    sch = cfgs["homeassistant/sensor/flight_watcher_pilot2/schedule/config"]
    assert sch["unique_id"] == "flight_watcher_pilot2_schedule" and sch["object_id"] == "flight_watcher_pilot2_schedule"
    assert sch["state_topic"] == "flight_watcher_pilot2/schedule" and sch["device"]["identifiers"] == ["flight_watcher_pilot2"]
    assert sch["availability_topic"] == "flight_watcher_pilot2/status"
    assert cfgs["homeassistant/switch/flight_watcher_pilot2/hunt_mode/config"]["command_topic"] == "flight_watcher_pilot2/hunt/set"
    assert all(cfg["unique_id"].startswith("flight_watcher_pilot2_") for cfg in cfgs.values())
    # rule switches
    W.RULES["list"] = [{"id": "r1", "name": "R", "enabled": True, "mode": "alert", "created_at": "2026-01-01T00:00:00+00:00"}]
    c = FakeClient()
    W.publish_rules(c)
    rule = json.loads(next(p for t, p, _ in c.msgs if t == "homeassistant/switch/flight_watcher_pilot2/rule_r1_live/config"))
    assert rule["unique_id"] == "flight_watcher_pilot2_rule_r1_live" and rule["command_topic"] == "flight_watcher_pilot2/rule/r1/live/set"
    assert rule["default_entity_id"] == "switch.flight_watcher_pilot2_rule_r1_live"
    assert sch["default_entity_id"] == "sensor.flight_watcher_pilot2_schedule"


def test_instance_drops_option_creds_and_overlays_creds_json(tmp_path, monkeypatch):
    W = _load(tmp_path, monkeypatch, "pilot2", OPTS)
    for k in ("username", "password", "ctweb_username", "ctweb_password", "my_name", "second_pilot"):
        assert k not in W.OPTS
    assert W.OPTS["category_check"] == "HNL 332 FO"  # the rest of the options still apply
    (tmp_path / "creds.json").write_text(json.dumps({"username": "p2", "password": "pw2", "my_name": " Two ", "ctweb_username": ""}))
    W = _load(tmp_path, monkeypatch, "pilot2", OPTS)
    assert W.OPTS["username"] == "p2" and W.OPTS["password"] == "pw2" and W.OPTS["my_name"] == "Two"
    assert "ctweb_username" not in W.OPTS and "ctweb_password" not in W.OPTS
    st = W.settings_state()
    assert st["username"] == "p2" and st["has_password"] is True and st["has_ctweb_password"] is False
    assert st["instance"] == "pilot2" and "password" not in st and "pw2" not in json.dumps(st)


def test_creds_json_overlays_default_instance_too(tmp_path, monkeypatch):
    (tmp_path / "creds.json").write_text(json.dumps({"my_name": "Over"}))
    W = _load(tmp_path, monkeypatch, "", OPTS)
    assert W.OPTS["username"] == "opt_user" and W.OPTS["my_name"] == "Over"


def test_options_file_env(tmp_path, monkeypatch):
    other = tmp_path / "shared"
    other.mkdir()
    (other / "options.json").write_text(json.dumps({**OPTS, "category_check": "HNL 332 CA"}))
    monkeypatch.setenv("FLIGHT_WATCHER_OPTIONS", str(other / "options.json"))
    monkeypatch.setenv("FLIGHT_WATCHER_DATA", str(tmp_path))
    monkeypatch.setenv("FLIGHT_WATCHER_PREFIX", "flight_watcher_pilot2")
    monkeypatch.setenv("FLIGHT_WATCHER_INSTANCE", "pilot2")
    sys.modules.pop("watcher", None)
    import watcher as W
    assert W.OPTS["category_check"] == "HNL 332 CA" and "username" not in W.OPTS
    assert W.CREDS_FILE == str(tmp_path / "creds.json")


def test_settings_set_merges_and_restarts(tmp_path, monkeypatch):
    (tmp_path / "creds.json").write_text(json.dumps({"username": "old", "password": "oldpw"}))
    W = _load(tmp_path, monkeypatch, "pilot2", OPTS)
    fake = FakeClient()
    monkeypatch.setattr(W, "MQ", fake)
    restarts = []
    monkeypatch.setattr(W, "restart_later", lambda: restarts.append(1))
    # blanks and unknown keys are ignored; a changed value is merged and triggers a restart
    assert W.settings_cmd(json.dumps({"password": "newpw", "username": "", "my_name": "  ", "ctweb_username": "ct", "bogus": "x"})) is True
    saved = json.loads((tmp_path / "creds.json").read_text())
    assert saved == {"username": "old", "password": "newpw", "ctweb_username": "ct"}
    assert stat.S_IMODE(os.stat(tmp_path / "creds.json").st_mode) == 0o600
    assert restarts == [1]
    topic, payload, retain = fake.msgs[-1]
    assert topic == "flight_watcher_pilot2/settings/state" and retain is True
    st = json.loads(payload)
    assert st["username"] == "old" and st["ctweb_username"] == "ct" and st["has_password"] is True and st["has_ctweb_password"] is False
    assert "newpw" not in payload and "oldpw" not in payload and "password" not in st
    # same values again: state published, no restart
    assert W.settings_cmd(json.dumps({"password": "newpw"})) is False
    assert restarts == [1] and fake.msgs[-1][0] == "flight_watcher_pilot2/settings/state"
    # garbage: ignored
    assert W.settings_cmd("not json") is False and W.settings_cmd("[1]") is False
    assert json.loads((tmp_path / "creds.json").read_text()) == saved


def test_restart_calls_os_exit(tmp_path, monkeypatch):
    W = _load(tmp_path, monkeypatch, "pilot2", OPTS)
    codes = []
    monkeypatch.setattr(W.os, "_exit", lambda c: codes.append(c))
    W._restart()
    assert codes == [3]


def test_on_message_routes_settings(tmp_path, monkeypatch):
    W = _load(tmp_path, monkeypatch, "pilot2", OPTS)
    seen = []
    monkeypatch.setattr(W, "settings_cmd", lambda p: seen.append(p))

    class Msg:
        topic = "flight_watcher_pilot2/settings/set"
        payload = b'{"username": "x"}'

    W.on_message(None, None, Msg())
    assert seen == ['{"username": "x"}']


# ---------------------------------------------------------------- run.py
def test_run_child_specs():
    import run
    assert run.second_pilot_name({}) == "" and run.second_pilot_name({"second_pilot": "  "}) == ""
    assert run.second_pilot_name({"second_pilot": "Pilot_2"}) == "pilot_2"
    for bad in ("two words", "a-b", "../x", "x/y", "a" * 33, "nämé"):
        assert run.second_pilot_name({"second_pilot": bad}) == ""
    assert run.child_specs({"second_pilot": ""}) == [{"name": "", "env": {}}]
    specs = run.child_specs({"second_pilot": "pilot2"}, data="/d")
    assert [s["name"] for s in specs] == ["", "pilot2"]
    assert specs[1]["env"] == {"FLIGHT_WATCHER_DATA": "/d/pilot2", "FLIGHT_WATCHER_PREFIX": "flight_watcher_pilot2", "FLIGHT_WATCHER_INSTANCE": "pilot2",
                               "FLIGHT_WATCHER_OPTIONS": "/d/options.json", "FLIGHT_WATCHER_WEB": "0"}
    assert run.child_specs({"second_pilot": "bad name"}) == [{"name": "", "env": {}}]


def test_new_settings_clear_a_stop(tmp_path, monkeypatch):
    """1.0.1: new FLICA credentials clear only a no-credentials or rejected-login stop, never a CAPTCHA/MFA one."""
    W = _load(tmp_path, monkeypatch, "", {**OPTS, "username": "", "password": ""})
    monkeypatch.setattr(W, "MQ", FakeClient())
    monkeypatch.setattr(W, "restart_later", lambda: None)
    W.S.update({"machine": "stopped_unexpected", "kills": [1], "parse_fail": 2, "relogin_streak": 6,
                "note": "enter your FLICA username and password: Open Web UI > Settings (still stopped after restart, press Re-arm)"})
    assert W.settings_cmd(json.dumps({"username": "doej", "password": "pw1"})) is True
    assert W.S["machine"] == "idle" and W.S["parse_fail"] == 0 and W.S["relogin_streak"] == 0
    assert W.S["kills"] == [1]  # the yield back-off count is only cleared by Re-arm
    assert stat.S_IMODE(os.stat(tmp_path / "creds.json").st_mode) == 0o600
    W.S.update({"machine": "stopped_login_failed", "note": "one login attempt failed (bad password)"})
    assert W.settings_cmd(json.dumps({"password": "pw2"})) is True and W.S["machine"] == "idle"
    for i, note in enumerate(("FLICA asked for captcha/MFA/password change during login", "FLICA showed a captcha/MFA/password page")):
        W.S.update({"machine": "stopped_unexpected", "note": note})
        assert W.settings_cmd(json.dumps({"password": f"pw-captcha-{i}"})) is True
        assert W.S["machine"] == "stopped_unexpected"  # CAPTCHA/MFA: only Ryan's Re-arm
    W.S.update({"machine": "stopped_login_failed", "note": "x"})
    assert W.settings_cmd(json.dumps({"my_name": "Doe"})) is True and W.S["machine"] == "stopped_login_failed"
    W.S.update({"machine": "hunting", "note": ""})
    assert W.settings_cmd(json.dumps({"password": "pw3"})) is True and W.S["machine"] == "hunting"


def test_settings_clear_and_still_waiting(tmp_path, monkeypatch):
    W = _load(tmp_path, monkeypatch, "", OPTS)
    fake = FakeClient()
    monkeypatch.setattr(W, "MQ", fake)
    restarts = []
    monkeypatch.setattr(W, "restart_later", lambda: restarts.append(1))
    assert W.settings_clear() is False and restarts == []
    W.settings_cmd(json.dumps({"password": "pw9"}))
    assert (tmp_path / "creds.json").exists()
    assert W.settings_clear() is True and not (tmp_path / "creds.json").exists() and len(restarts) == 2
    assert "pw9" not in fake.msgs[-1][1]
    W.S.update({"machine": "yielded", "yield_until": 1000})
    assert W.still_waiting(now=999) is True and W.still_waiting(now=1001) is False
    W.S.update({"machine": "backoff", "relogin_at": 50})
    assert W.still_waiting(now=10) is True and W.still_waiting(now=60) is False
    W.S.update({"machine": "idle"})
    assert W.still_waiting(now=0) is False


def test_sealed_settings_from_the_card(tmp_path, monkeypatch):
    """1.1.0: settings/set {"enc": ...} sealed with this instance's key is saved; a bad seal is refused."""
    import sealed as SEAL
    W = _load(tmp_path, monkeypatch, "pilot2", OPTS)
    fake = FakeClient()
    monkeypatch.setattr(W, "MQ", fake)
    monkeypatch.setattr(W, "restart_later", lambda: None)
    st = W.settings_state()
    assert st["pubkey"] and st["kid"] and stat.S_IMODE(os.stat(tmp_path / "settings_key.pem").st_mode) == 0o600
    body = SEAL.seal(st["pubkey"], {"username": "doej", "password": "pw-sealed"})
    assert W.settings_cmd(json.dumps(body)) is True
    assert json.loads((tmp_path / "creds.json").read_text()) == {"username": "doej", "password": "pw-sealed"}
    last = json.loads(fake.msgs[-1][1])
    assert last["result"] == "saved: username, password" and "pw-sealed" not in fake.msgs[-1][1]
    old = SEAL.seal(st["pubkey"], {"password": "pw-old"}, ts=1)
    assert W.settings_cmd(json.dumps(old)) is False
    assert json.loads(fake.msgs[-1][1])["result"].startswith("refused")
    assert json.loads((tmp_path / "creds.json").read_text())["password"] == "pw-sealed"


def test_sealed_settings_without_a_key_never_raise(tmp_path, monkeypatch):
    W = _load(tmp_path, monkeypatch, "pilot2", OPTS)
    fake = FakeClient()
    monkeypatch.setattr(W, "MQ", fake)

    def boom():
        raise OSError("read-only")
    monkeypatch.setattr(W, "settings_key", boom)
    assert W.settings_cmd(json.dumps({"enc": {"v": 1}})) is False
    assert "key unavailable" in json.loads(fake.msgs[-1][1])["result"]


def test_ticket_fixed_event_on_the_instance_prefix(tmp_path, monkeypatch):
    """FW-0007: the admin's instance sends ticket_fixed on its own prefix, not retained, when it marks a ticket fixed
    (a pilot's ticket too: the tickets folder is shared, as on Pako). 1.7.0 (Release C): a pilot instance may no
    longer mark anything fixed (verify, reopen and note only), so it never sends ticket_fixed itself; his own alert is
    made from the folder (ticket_fixed_watch)."""
    W = _load(tmp_path, monkeypatch, "", OPTS)
    monkeypatch.setattr(W, "TICKETS_DIR", str(tmp_path / "tickets"))
    fake = FakeClient()
    monkeypatch.setattr(W, "MQ", fake)
    t = W.ticket_new(json.dumps({"kind": "bug", "title": "Card blank (ryan)", "narrative": "y"}))
    W.ticket_act(json.dumps({"id": t["id"], "action": "fixed", "version": "1.3.0"}))
    ev = [(tp, json.loads(p), r) for tp, p, r in fake.msgs if tp.endswith("/event/ticket_fixed")]
    assert ev == [("flight_watcher/event/ticket_fixed", {"id": t["id"], "kind": "bug", "title": t["title"],
                                                         "reporter": "ryan", "version": "1.3.0"}, False)]
    W = _load(tmp_path, monkeypatch, "pilot2", OPTS)
    monkeypatch.setattr(W, "TICKETS_DIR", str(tmp_path / "tickets"))
    fake = FakeClient()
    monkeypatch.setattr(W, "MQ", fake)
    mine = W.ticket_new(json.dumps({"kind": "bug", "title": "Card blank (pilot2)", "narrative": "y"}))
    assert mine["reporter"] == "pilot2"
    for tid in (mine["id"], t["id"]):  # his own and Ryan's: refused, nothing sent
        assert W.ticket_act(json.dumps({"id": tid, "action": "fixed", "version": "1.3.0"})) is None
    assert not [1 for tp, _, _ in fake.msgs if tp.endswith("/event/ticket_fixed")]
    errs = [json.loads(p)["error"] for tp, p, _ in fake.msgs if tp.endswith("/event/ticket_error")]
    assert errs == ["a pilot may only verify, reopen or add a note, not fixed"] * 2
    W2 = _load(tmp_path, monkeypatch, "", OPTS)  # the admin marks the pilot's ticket fixed: sent on his own prefix
    monkeypatch.setattr(W2, "TICKETS_DIR", str(tmp_path / "tickets"))
    fake2 = FakeClient()
    monkeypatch.setattr(W2, "MQ", fake2)
    W2.ticket_act(json.dumps({"id": mine["id"], "action": "fixed", "version": "1.7.0"}))
    ev = [(tp, json.loads(p)["reporter"]) for tp, p, _ in fake2.msgs if tp.endswith("/event/ticket_fixed")]
    assert ev == [("flight_watcher/event/ticket_fixed", "pilot2")]


# ---------------------------------------------------------------- 1.5.0 (FW-0063) roles
# every entity Ryan's instance announced in 1.4.12 (discovery's default_entity_ids): 1.5.0 may not change one
ADMIN_IDS_1412 = [
    "binary_sensor.flight_watcher_session_ok", "button.flight_watcher_check_now",
    "button.flight_watcher_map_swap_pages_read_only", "button.flight_watcher_re_arm",
    "button.flight_watcher_scan_crewtrac_charters_now", "button.flight_watcher_update_schedules",
    "number.flight_watcher_hunt_check_every", "number.flight_watcher_normal_check_every",
    "sensor.flight_watcher_blocked_days", "sensor.flight_watcher_charters", "sensor.flight_watcher_crew_index",
    "sensor.flight_watcher_finds", "sensor.flight_watcher_flica_fetches", "sensor.flight_watcher_improved_pay_gross",
    "sensor.flight_watcher_last_check", "sensor.flight_watcher_last_match", "sensor.flight_watcher_last_new_pairing",
    "sensor.flight_watcher_next_check", "sensor.flight_watcher_ot_requests", "sensor.flight_watcher_own_trip_times",
    "sensor.flight_watcher_pickers", "sensor.flight_watcher_pilot_schedule", "sensor.flight_watcher_pot_count",
    "sensor.flight_watcher_recall_o75", "sensor.flight_watcher_reserve_grid", "sensor.flight_watcher_rules_active",
    "sensor.flight_watcher_schedule", "sensor.flight_watcher_schedule_versions", "sensor.flight_watcher_settings",
    "sensor.flight_watcher_state", "sensor.flight_watcher_swap_ideas", "sensor.flight_watcher_swap_mode",
    "sensor.flight_watcher_swap_test_requests", "sensor.flight_watcher_tickets",
    "sensor.flight_watcher_tradeboard_pickups", "sensor.flight_watcher_upload_status",
    "sensor.flight_watcher_uploads", "sensor.flight_watcher_working_flight", "sensor.flight_watcher_would_drop",
    "sensor.flight_watcher_would_trade", "switch.flight_watcher_auto_swap_dry_run",
    "switch.flight_watcher_hunt_mode", "switch.flight_watcher_pause"
]
# added since: 1.7.1 (FW-0070) the bid calendar sensor, on every instance (core); 1.7.1 (FW-0072) the layover van
# and layover notes sensors, the admin's only (ADMIN_ONLY_171)
ADMIN_ONLY_171 = ("sensor.flight_watcher_layover_van", "sensor.flight_watcher_layover_notes")
ADMIN_IDS = sorted(ADMIN_IDS_1412 + ["sensor.flight_watcher_bid_calendar"] + list(ADMIN_ONLY_171))
PILOT_RETIRED_1500 = ("switch.flight_watcher_auto_swap_dry_run", "button.flight_watcher_map_swap_pages_read_only",
                      "sensor.flight_watcher_would_drop")
ADMIN_ONLY_1412 = ("sensor.flight_watcher_crew_index", "button.flight_watcher_update_schedules")  # never on a pilot


def test_discovery_ids_by_role(tmp_path, monkeypatch):
    """The admin announces exactly the 1.4.12 entities (plus the ones added since, ADMIN_IDS), one config each in
    entity_defs order; a pilot loses only Would drop, Auto swap (dry run) and Map swap pages, whose retained configs it
    empties so HA removes them (the crew index entities were never a pilot's)."""
    W = _load(tmp_path, monkeypatch, "", OPTS)
    c = FakeClient()
    W.discovery(c)
    made = [json.loads(p)["default_entity_id"] for t, p, _ in c.msgs if p]
    assert sorted(made) == ADMIN_IDS and len(made) == len(set(made))
    assert [t for t, p, _ in c.msgs if not p] == ["homeassistant/select/flight_watcher/swap_mode/config"]
    defs = W.entity_defs()
    assert [(t, json.loads(p)) for t, p, _ in c.msgs if p] == \
        [(f"homeassistant/{comp}/flight_watcher/{oid}/config", cfg) for comp, oid, cfg, _ in defs]
    assert {oid: f for _, oid, _, f in defs if f != "core"} == W.ROLES.ENTITY_FEATURE
    tmp2 = tmp_path / "p"
    tmp2.mkdir()
    W = _load(tmp2, monkeypatch, "pilot2", OPTS)
    c = FakeClient()
    W.discovery(c)
    made = {json.loads(p)["default_entity_id"].replace("flight_watcher_pilot2_", "flight_watcher_") for t, p, _ in c.msgs if p}
    assert set(ADMIN_IDS) - made == set(PILOT_RETIRED_1500) | set(ADMIN_ONLY_1412) | set(ADMIN_ONLY_171)
    assert made <= set(ADMIN_IDS)
    emptied = [t for t, p, _ in c.msgs if not p]
    assert emptied == [f"homeassistant/{t}/flight_watcher_pilot2/{o}/config" for t, o in (
        ("sensor", "drop_away"), ("switch", "auto_swap"), ("sensor", "layover_van"), ("sensor", "layover_notes"),
        ("button", "swap_map"), ("sensor", "crew_index"), ("button", "crew_scan"), ("select", "swap_mode"))]
