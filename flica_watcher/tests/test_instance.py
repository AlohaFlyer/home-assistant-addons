"""0.10.0: a second pilot as another watcher.py instance (prefix, creds.json, settings topic, run.py). Synthetic only."""
import json
import os
import stat
import sys

import pytest


def _load(tmp_path, monkeypatch, instance, opts):
    monkeypatch.setenv("FLICA_DATA", str(tmp_path))
    if instance:
        monkeypatch.setenv("FLICA_PREFIX", f"flica_watcher_{instance}")
        monkeypatch.setenv("FLICA_INSTANCE", instance)
    else:
        monkeypatch.delenv("FLICA_PREFIX", raising=False)
        monkeypatch.delenv("FLICA_INSTANCE", raising=False)
    monkeypatch.delenv("FLICA_OPTIONS", raising=False)
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
    assert W.T == "flica_watcher" and W.INSTANCE == "" and W.AVAIL == "flica_watcher/status"
    assert W.OPTS["username"] == "opt_user" and W.OPTS["my_name"] == "Optname"
    assert W.DEV["identifiers"] == ["flica_watcher"] and W.DEV["name"] == "Flight Watcher"
    assert W.RULE_UID == "flica_rule" and W.UPLOADS == "/share/flica_watcher/uploads"
    assert W.finds_dir() == W.CARD_PAIRINGS == "/homeassistant/www/flica"
    cfgs = _discovery(W)
    assert cfgs["homeassistant/sensor/flica_watcher/schedule/config"]["unique_id"] == "flica_watcher_schedule"
    assert cfgs["homeassistant/sensor/flica_watcher/schedule/config"]["object_id"] == "flica_watcher_schedule"
    assert cfgs["homeassistant/sensor/flica_watcher/schedule/config"]["state_topic"] == "flica_watcher/schedule"
    assert cfgs["homeassistant/switch/flica_watcher/hunt_mode/config"]["unique_id"] == "flica_watcher_hunt_mode"
    assert cfgs["homeassistant/sensor/flica_watcher/settings/config"]["state_topic"] == "flica_watcher/settings/state"
    # 0.10.3: HA ignores object_id; default_entity_id keeps the flica_watcher_* ids
    assert cfgs["homeassistant/sensor/flica_watcher/schedule/config"]["default_entity_id"] == "sensor.flica_watcher_schedule"
    assert cfgs["homeassistant/switch/flica_watcher/hunt_mode/config"]["default_entity_id"] == "switch.flica_watcher_hunt_mode"
    assert cfgs["homeassistant/binary_sensor/flica_watcher/session_ok/config"]["default_entity_id"] == "binary_sensor.flica_watcher_session_ok"
    for topic, cfg in cfgs.items():
        comp = topic.split("/")[1]
        assert cfg["default_entity_id"] == f"{comp}.{cfg['object_id']}" == f"{comp}.{cfg['unique_id']}"


def test_instance_prefix_and_ids(tmp_path, monkeypatch):
    W = _load(tmp_path, monkeypatch, "pilot2", OPTS)
    assert W.T == "flica_watcher_pilot2" and W.INSTANCE == "pilot2" and W.AVAIL == "flica_watcher_pilot2/status"
    assert W.DEV["identifiers"] == ["flica_watcher_pilot2"] and W.DEV["name"] == "Flight Watcher (Pilot2)"
    assert W.RULE_UID == "flica_watcher_pilot2_rule"
    assert W.UPLOADS == "/share/flica_watcher/pilot2/uploads" and W.CAPTURE_DIR == "/share/flica_watcher/pilot2/captures"
    assert W.finds_dir() == "/homeassistant/www/flica/pilot2" and W.CARD_PAIRINGS == "/homeassistant/www/flica"
    cfgs = _discovery(W)
    assert "homeassistant/sensor/flica_watcher/schedule/config" not in cfgs
    sch = cfgs["homeassistant/sensor/flica_watcher_pilot2/schedule/config"]
    assert sch["unique_id"] == "flica_watcher_pilot2_schedule" and sch["object_id"] == "flica_watcher_pilot2_schedule"
    assert sch["state_topic"] == "flica_watcher_pilot2/schedule" and sch["device"]["identifiers"] == ["flica_watcher_pilot2"]
    assert sch["availability_topic"] == "flica_watcher_pilot2/status"
    assert cfgs["homeassistant/switch/flica_watcher_pilot2/hunt_mode/config"]["command_topic"] == "flica_watcher_pilot2/hunt/set"
    assert all(cfg["unique_id"].startswith("flica_watcher_pilot2_") for cfg in cfgs.values())
    # rule switches
    W.RULES["list"] = [{"id": "r1", "name": "R", "enabled": True, "mode": "alert", "created_at": "2026-01-01T00:00:00+00:00"}]
    c = FakeClient()
    W.publish_rules(c)
    rule = json.loads(next(p for t, p, _ in c.msgs if t == "homeassistant/switch/flica_watcher_pilot2/rule_r1_live/config"))
    assert rule["unique_id"] == "flica_watcher_pilot2_rule_r1_live" and rule["command_topic"] == "flica_watcher_pilot2/rule/r1/live/set"
    assert rule["default_entity_id"] == "switch.flica_watcher_pilot2_rule_r1_live"
    assert sch["default_entity_id"] == "sensor.flica_watcher_pilot2_schedule"


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
    monkeypatch.setenv("FLICA_OPTIONS", str(other / "options.json"))
    monkeypatch.setenv("FLICA_DATA", str(tmp_path))
    monkeypatch.setenv("FLICA_PREFIX", "flica_watcher_pilot2")
    monkeypatch.setenv("FLICA_INSTANCE", "pilot2")
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
    assert topic == "flica_watcher_pilot2/settings/state" and retain is True
    st = json.loads(payload)
    assert st["username"] == "old" and st["ctweb_username"] == "ct" and st["has_password"] is True and st["has_ctweb_password"] is False
    assert "newpw" not in payload and "oldpw" not in payload and "password" not in st
    # same values again: state published, no restart
    assert W.settings_cmd(json.dumps({"password": "newpw"})) is False
    assert restarts == [1] and fake.msgs[-1][0] == "flica_watcher_pilot2/settings/state"
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
        topic = "flica_watcher_pilot2/settings/set"
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
    assert specs[1]["env"] == {"FLICA_DATA": "/d/pilot2", "FLICA_PREFIX": "flica_watcher_pilot2", "FLICA_INSTANCE": "pilot2",
                               "FLICA_OPTIONS": "/d/options.json", "FLICA_WEB": "0"}
    assert run.child_specs({"second_pilot": "bad name"}) == [{"name": "", "env": {}}]
