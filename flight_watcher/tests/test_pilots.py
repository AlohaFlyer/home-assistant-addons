"""1.5.0 (FW-0063): option `pilots` [{name}] in run.py, with `second_pilot` read when it is empty. Made-up names."""
import json
import os
import sys

import pytest

import roles
import run

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _env(name, data="/data"):
    return {"FLIGHT_WATCHER_DATA": f"{data}/{name}", "FLIGHT_WATCHER_PREFIX": f"flight_watcher_{name}",
            "FLIGHT_WATCHER_INSTANCE": name, "FLIGHT_WATCHER_OPTIONS": f"{data}/options.json", "FLIGHT_WATCHER_WEB": "0"}


def _names(opts):
    return [s["name"] for s in run.child_specs(opts)]


def test_fallback_to_second_pilot():
    assert run.child_specs({}) == [{"name": "", "env": {}}]
    assert run.child_specs({"pilots": [], "second_pilot": "james"}, data="/d") == [
        {"name": "", "env": {}}, {"name": "james", "env": _env("james", "/d")}]
    assert _names({"pilots": None, "second_pilot": "james"}) == ["", "james"]  # a missing option reads as empty
    assert _names({"second_pilot": ""}) == [""]


def test_pilots_override_second_pilot(capsys):
    assert _names({"pilots": [{"name": "james"}, {"name": "demo"}], "second_pilot": "james"}) == ["", "james", "demo"]
    assert "ignored" not in capsys.readouterr().out  # second_pilot names a listed pilot: nothing to say
    assert _names({"pilots": [{"name": "demo"}], "second_pilot": "james"}) == ["", "demo"]
    assert "second_pilot 'james' ignored: the pilots option is set" in capsys.readouterr().out


def test_invalid_reserved_duplicate_names_left_out(capsys):
    opts = {"pilots": [{"name": "james"}, {"name": "two words"}, {"name": "a-b"}, {"name": "../x"}, {"name": "a" * 33},
                       {"name": None}, {}, {"name": "state"}, {"name": "settings_x"}, {"name": "ticket"}, {"name": "hunt"},
                       {"name": "ryan"}, {"name": "james"}, {"name": "james_b"}, {"name": "demo"}]}
    assert _names(opts) == ["", "james", "demo"]
    out = capsys.readouterr().out
    assert out.count("left out") == 13
    for bad in ("'state'", "'settings_x'", "'ticket'", "'hunt'", "'ryan'"):
        assert f"pilot {bad} left out: its first word" in out, bad
    assert "pilot 'james' left out: named twice" in out and "pilot 'james_b' left out: its ids would mix" in out


def test_names_home_assistant_cannot_keep_are_left_out(capsys):
    """Review fix (1.5.0): a trailing or doubled underscore would give ids such as sensor.flight_watcher_jane__state,
    which Home Assistant does not keep as written, so the pilot's dashboard would read missing entities."""
    opts = {"pilots": [{"name": n} for n in ("jane_", "a__b", "x_", "demo")]}
    assert _names(opts) == ["", "demo"]
    out = capsys.readouterr().out
    for bad in ("jane_", "a__b", "x_"):
        assert f"pilot {bad!r} left out: use 1 to 32 lowercase letters, digits and single underscores" in out, bad
    assert _names({"second_pilot": "jane_"}) == [""]
    assert "second_pilot 'jane_' ignored" in capsys.readouterr().out
    assert _names({"pilots": [{"name": "jane_doe"}]}) == ["", "jane_doe"]  # single underscores stay fine


def test_cap_of_three_pilots(capsys):
    opts = {"pilots": [{"name": n} for n in ("james", "demo", "pilot3", "pilot4")]}
    assert _names(opts) == ["", "james", "demo", "pilot3"] and roles.MAX_PILOTS == 3
    assert "pilot 'pilot4' left out: at most 3 pilots besides the admin" in capsys.readouterr().out
    # a refused name does not count toward the cap
    assert _names({"pilots": [{"name": "state"}] + opts["pilots"][:3]}) == ["", "james", "demo", "pilot3"]


def test_a_third_pilot_needs_no_code_change(tmp_path, monkeypatch):
    """pilot3 gets its prefix, data folder and env from run.py alone, and its watcher.py runs as a pilot under them."""
    specs = run.child_specs({"pilots": [{"name": "james"}, {"name": "pilot3"}]}, data=str(tmp_path))
    assert [s["name"] for s in specs] == ["", "james", "pilot3"]
    assert specs[2]["env"] == _env("pilot3", str(tmp_path))
    (tmp_path / "options.json").write_text(json.dumps({"username": "u", "password": "p", "log_level": "info",
                                                       "pilots": [{"name": "james"}, {"name": "pilot3"}]}))
    (tmp_path / "pilot3").mkdir()
    for k, v in specs[2]["env"].items():
        monkeypatch.setenv(k, v)
    sys.modules.pop("watcher", None)
    try:
        import watcher as W
        assert W.T == "flight_watcher_pilot3" and W.INSTANCE == "pilot3" and W.DATA == str(tmp_path / "pilot3")
        assert W.DB_FILE == str(tmp_path / "pilot3" / "watcher.db") and "username" not in W.OPTS  # not the admin's logins
        assert W.ROLES.role(W.INSTANCE) == "pilot" and not W.has("crew_index") and W.has("core")
        assert W.finds_dir().endswith("/flight-watcher/pilot3")
    finally:
        sys.modules.pop("watcher", None)


def test_cards_deploy_gets_the_same_names(monkeypatch, tmp_path):
    """main() hands cards.deploy the pilot names child_specs ran, so every pilot gets its card copies."""
    import cards
    import migrate
    seen = {}
    monkeypatch.setattr(run, "read_options", lambda path=None: {"pilots": [{"name": "james"}, {"name": "state"},
                                                                           {"name": "pilot3"}]})
    monkeypatch.setattr(migrate, "run", lambda: None)
    monkeypatch.setattr(cards, "deploy", lambda version, pilots: seen.setdefault("pilots", list(pilots)))
    monkeypatch.setattr(run, "start", lambda spec: (_ for _ in ()).throw(SystemExit(0)))
    monkeypatch.setattr(run.signal, "signal", lambda *a: None)  # keep pytest's own SIGINT / SIGTERM handlers
    with pytest.raises(SystemExit):
        run.main()
    assert seen["pilots"] == ["james", "pilot3"]


def test_config_yaml_option_and_schema():
    yaml = pytest.importorskip("yaml")
    cfg = yaml.safe_load(open(os.path.join(HERE, "config.yaml"), encoding="utf-8"))
    assert cfg["options"]["pilots"] == [] and cfg["options"]["second_pilot"] == ""
    assert cfg["schema"]["pilots"] == [{"name": "match(^(?=.{1,32}$)[a-z0-9]+(?:_[a-z0-9]+)*$)"}]
    assert cfg["schema"]["second_pilot"] == "str?"
    assert cfg["schema"]["pilots"][0]["name"] == f"match({roles.NAME_RE.pattern})"
