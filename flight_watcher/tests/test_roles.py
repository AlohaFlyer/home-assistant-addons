"""1.5.0 (FW-0063): pilots and roles. The default instance is the admin and keeps the 1.4.12 subscriptions, entities
and pushes exactly; a pilot instance loses only the admin's features (roles.FEATURES). Synthetic data only."""
import inspect
import json
import logging
import os
import re
import sys

import pytest

import roles

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(HERE)

# on_connect in 1.4.12 (watcher.py L936-941), call for call: the admin's subscriptions may never change
ADMIN_SUBS_1412 = [
    "flight_watcher/hunt/set", "flight_watcher/pause/set", "flight_watcher/rearm/press", "flight_watcher/hunt/state",
    "flight_watcher/pause/state", "flight_watcher/rule/+/live/set", "flight_watcher/check_now/press",
    "flight_watcher/freq/normal_min/set", "flight_watcher/freq/hunt_s/set", "flight_watcher/email/alert",
    "flight_watcher/blocked/set", "flight_watcher/trade/set", "flight_watcher/auto_swap/set",
    "flight_watcher/swap_map/press", "flight_watcher/drop/set", "flight_watcher/charter_scan/press",
    "flight_watcher/pilot/set", "flight_watcher/improved/set", "flight_watcher/recall/set", "flight_watcher/recall/act",
    "flight_watcher/settings/set", "flight_watcher/ticket/new", "flight_watcher/ticket/image",
    "flight_watcher/ticket/act", "flight_watcher/ticket/edit", "flight_watcher/ticket/delete",
    "flight_watcher/crew_scan/press", ("flight_watcher/upload/chunk", 1),
]
PILOT_LOSES = ("email/alert", "auto_swap/set", "swap_map/press", "drop/set", "crew_scan/press")


class FakeClient:
    def __init__(self):
        self.msgs, self.subs = [], []

    def publish(self, topic, payload="", retain=False):
        self.msgs.append((topic, payload, retain))

    def subscribe(self, topic):
        self.subs.append(topic)


class Msg:
    def __init__(self, topic, payload):
        self.topic, self.payload = topic, payload.encode()


def _load(tmp_path, monkeypatch, instance):
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
    monkeypatch.delenv("FLIGHT_WATCHER_PORTAL", raising=False)
    sys.modules.pop("watcher", None)
    import watcher as W
    monkeypatch.setattr(W.time, "sleep", lambda s: None)
    monkeypatch.setattr(W, "MQ", FakeClient())
    monkeypatch.setattr(W, "CARD_PAIRINGS", str(tmp_path / "www" / "flight-watcher"))
    W.S.clear()
    return W


@pytest.fixture
def load(tmp_path, monkeypatch):
    yield lambda instance: _load(tmp_path, monkeypatch, instance)
    sys.modules.pop("watcher", None)


# ---------------------------------------------------------------- the table
def test_readme_table_equals_features():
    text = open(os.path.join(HERE, "README.md"), encoding="utf-8").read()
    sec = text.split("## Pilots and roles (1.5.0, FW-0063)", 1)[1].split("\n## ", 1)[0]
    rows = [ln for ln in sec.splitlines() if ln.startswith("| `")]
    got = {}
    for ln in rows:
        name, who, portal, gates = [c.strip() for c in ln.strip("|").split("|")]
        got[name.strip("`")] = (who, portal == "yes", gates)
    assert got == roles.FEATURES
    assert list(got) == list(roles.FEATURES)  # same order


def test_roles_basics():
    assert roles.role("") == "admin" and roles.role("james") == roles.role("pilot3") == "pilot"
    assert roles.features("") == list(roles.FEATURES)
    assert roles.features("pilot2") == ["core", "prefs", "tickets", "uploads"]
    assert roles.allowed("core", "pilot2") and not roles.allowed("drop_mark", "pilot2") and roles.allowed("drop_mark", "")
    assert not roles.allowed("no_such_feature", "") and not roles.allowed("no_such_feature", "pilot2")  # fail closed
    for f, (who, portal, gates) in roles.FEATURES.items():
        assert who in ("admin", "all") and isinstance(portal, bool) and gates and chr(0x2014) not in gates
        assert not (who == "admin" and portal), f  # a portal is a pilot's: an admin-only feature is never on it
    assert set(roles.SUBS.values()) - {roles.INTERNAL} <= set(roles.FEATURES)
    assert set(roles.EVENTS.values()) <= set(roles.FEATURES) and set(roles.ENTITY_FEATURE.values()) <= set(roles.FEATURES)
    assert roles.sub_key("rule/sin_alert/live/set") == "rule/+/live/set" and roles.sub_key("rule/a/b/live/set") is None
    assert roles.sub_allowed("hunt/state", "pilot2") and roles.sub_allowed("unknown/topic", "pilot2")
    assert not roles.sub_allowed("drop/set", "pilot2") and roles.sub_allowed("drop/set", "")
    assert roles.event_allowed("new_pairing", "pilot2") and not roles.event_allowed("drop_ready", "pilot2")
    assert roles.event_allowed("some_new_event", "pilot2")  # an event the table does not name yet is core


def test_admin_subscriptions_are_the_1412_list_verbatim():
    got = [(f"flight_watcher/{s}", q) if q else f"flight_watcher/{s}" for s, q in roles.subscriptions("")]
    assert got == ADMIN_SUBS_1412
    assert roles.subscriptions("", portal=True) == roles.subscriptions("")
    pilot = [s for s, q in roles.subscriptions("pilot2")]
    assert pilot == [s for s, q in roles.subscriptions("") if s not in PILOT_LOSES]
    assert roles.subscriptions("pilot2", portal=True) == roles.subscriptions("pilot2")  # nothing portal-only in 1.5.0


@pytest.mark.parametrize("instance", ["", "pilot2"])
def test_subscribe_all_on_a_fake_client(load, instance):
    W = load(instance)
    c = FakeClient()
    W.subscribe_all(c)
    if not instance:
        assert c.subs == ADMIN_SUBS_1412
    else:
        want = [(t[0].replace("flight_watcher/", "flight_watcher_pilot2/", 1), 1) if isinstance(t, tuple)
                else t.replace("flight_watcher/", "flight_watcher_pilot2/", 1) for t in ADMIN_SUBS_1412
                if (t[0] if isinstance(t, tuple) else t).split("/", 1)[1] not in PILOT_LOSES]
        assert c.subs == want and len(want) == len(ADMIN_SUBS_1412) - len(PILOT_LOSES)


class _Timer:
    def __init__(self, *a, **k):
        self.daemon = False

    def start(self):
        pass


@pytest.mark.parametrize("instance", ["", "pilot2"])
def test_on_connect_subscribes_exactly_the_role_list(load, monkeypatch, instance):
    """Review fix (1.5.0): what on_connect itself subscribes on the broker, call for call. The admin's is the 1.4.12
    list verbatim (order and the qos 1 chunk topic included); a pilot's is that list under its prefix minus
    PILOT_LOSES. Exact equality also catches a merge that puts the old 1.4.12 subscribe loop back beside
    subscribe_all() (every topic twice) or adds a subscribe anywhere in on_connect."""
    W = load(instance)
    subs, pubs = [], []

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
            pubs.append(t)

        def subscribe(self, t, *a, **k):
            subs.append(t)
    monkeypatch.setattr(W.mqtt, "Client", Client)
    monkeypatch.setattr(W, "mqtt_creds", lambda: {"username": "u", "password": "p", "host": "h", "port": 1883})
    monkeypatch.setattr(W, "freq", lambda: {"normal_min": 6, "hunt_s": 40})
    monkeypatch.setattr(W.threading, "Timer", _Timer)
    c = W.mqtt_start()
    c.on_connect(c, None, None, 0)
    if not instance:
        assert subs == ADMIN_SUBS_1412
        assert "flight_watcher/auto_swap/state" in pubs
    else:
        want = [(t[0].replace("flight_watcher/", "flight_watcher_pilot2/", 1), 1) if isinstance(t, tuple)
                else t.replace("flight_watcher/", "flight_watcher_pilot2/", 1) for t in ADMIN_SUBS_1412
                if (t[0] if isinstance(t, tuple) else t).split("/", 1)[1] not in PILOT_LOSES]
        assert subs == want
        assert not [t for t in pubs if t.endswith("/auto_swap/state")]  # the admin-only switch is not published
    assert pubs and all(t.startswith(W.T + "/") or t.startswith("homeassistant/") for t in pubs)


def test_every_on_message_topic_is_in_subs(load):
    """Every f"{T}/..." topic on_message handles has a feature, and every feature'd topic is handled."""
    W = load("")
    src = inspect.getsource(W.on_message)
    seen = {t for ln in src.splitlines() if "msg.topic" in ln for t in re.findall(r'f"\{T\}/([a-z_/]+)"', ln)}
    seen.discard("rule/")  # the startswith("rule/") ... endswith("/live/set") branch
    assert 'startswith(f"{T}/rule/")' in src and 'endswith("/live/set")' in src
    assert {s for s in seen if roles.sub_key(s) is None} == set()
    assert set(roles.SUBS) - {"rule/+/live/set"} == seen


def test_every_event_the_watcher_sends_is_in_events():
    src = open(os.path.join(HERE, "watcher.py"), encoding="utf-8").read()
    sent = set(re.findall(r'"event/([a-z_]+)"', src)) | set(re.findall(r'f"\{T\}/event/([a-z_]+)"', src))
    assert sent and sent - set(roles.EVENTS) == set()


def test_reserved_covers_every_admin_id_topic_and_folder(load):
    """A pilot name may not start with a word that begins one of the admin's entity ids, topics, helpers, share
    folders or /data files (its ids or folders would collide), and the push guard reads such an id as Ryan's."""
    W = load("")
    words = set()
    for comp, oid, cfg, feat in W.entity_defs():
        words.add(cfg["default_entity_id"].split(".", 1)[1][len("flight_watcher_"):].split("_")[0])
        words.add(oid.split("_")[0])
    words.add("rule")  # switch.flight_watcher_rule_<id>_live
    src = "".join(open(os.path.join(HERE, f), encoding="utf-8").read() for f in ("watcher.py", "web.py", "inflt.py"))
    for top in re.findall(r'\bpub\("([a-z_]+)', src) + re.findall(r'f"\{T\}/([a-z_]+)', src):
        words.add(top.split("_")[0])
    for name in (re.findall(r'/share/flight_watcher/([a-z0-9_.]+)', src) + re.findall(r'\{SHARE\}/([a-z0-9_.]+)', src)
                 + re.findall(r'f"\{DATA\}/([a-z0-9_.]+)"', src)):
        if "." not in name:  # a file <name>.json cannot collide with a pilot's folder /data/<pilot> or /share/.../<pilot>
            words.add(name.split("_")[0])
    pilots = json.load(open(os.path.join(ROOT, "ha", "pilots.json"), encoding="utf-8"))["pilots"]
    text = ""
    for d in (os.path.join(ROOT, "ha"), os.path.join(HERE, "www")):
        for dp, _, fs in os.walk(d):
            text += "".join(open(os.path.join(dp, f), encoding="utf-8", errors="replace").read()
                            for f in fs if f.endswith((".json", ".yaml", ".js", ".py")))
    for rest in re.findall(r"\b[a-z_]+\.flight_watcher_([a-z0-9_]+)", text):
        if not any(rest == p or rest.startswith(p + "_") for p in pilots):
            words.add(rest.split("_")[0])
    words.discard("")
    assert words - roles.RESERVED == set()
    assert words >= {"state", "settings", "ticket", "hunt", "last", "month", "www", "captures", "ccr"}
    for ok in ("james", "pilot2", "pilot3", "demo"):
        assert roles.name_refusal(ok) == "", ok


# homeassistant/core.py VALID_ENTITY_ID: no "__" anywhere, no leading or trailing "_" in either part
HA_VALID_ENTITY_ID = re.compile(r"^(?!.+__)(?!_)[\da-z_]+(?<!_)\.(?!_)[\da-z_]+(?<!_)$")


def test_name_refusal():
    assert roles.name_refusal("james") == "" and roles.name_refusal("pilot_2") != ""  # pilot_schedule is the admin's
    for bad in ("", "James", "a-b", "../x", "a" * 33, "_x", None, 7, "jane_", "a__b", "x_", "jane\n", "jane doe"):
        assert roles.name_refusal(bad) != "", bad
    for bad in ("jane_", "a__b", "x_"):  # review fix (1.5.0): ids HA cannot keep as written
        assert "single underscores" in roles.name_refusal(bad) and not roles.NAME_RE.match(bad), bad
        assert not HA_VALID_ENTITY_ID.match(f"sensor.flight_watcher_{bad}_state"), bad
    for ok in ("james", "jane_doe", "demo", "pilot3", "a" * 32, "x1_y2_z3"):
        assert roles.name_refusal(ok) == "" and HA_VALID_ENTITY_ID.match(f"sensor.flight_watcher_{ok}_state"), ok
    for res in ("state", "settings", "ticket", "hunt", "last_x", "ryan", "www"):
        assert "first word" in roles.name_refusal(res), res
    assert roles.name_refusal("james", ["james"]) == "named twice"
    assert "mix" in roles.name_refusal("jane_x", ["jane"]) and "mix" in roles.name_refusal("jane", ["jane_x"])


# ---------------------------------------------------------------- the watcher
def test_has_reads_instance_at_call_time(load, monkeypatch):
    W = load("")
    assert W.has("crew_index") and W.has("drop_mark")
    monkeypatch.setattr(W, "INSTANCE", "pilot2")
    assert not W.has("crew_index") and not W.has("hark_ccr") and W.has("core") and W.has("tickets")


@pytest.mark.parametrize("sub", ["drop/set", "auto_swap/set", "swap_map/press", "email/alert", "crew_scan/press"])
def test_a_refused_sub_changes_nothing_on_a_pilot(load, caplog, sub):
    W = load("pilot2")
    W.S.update({"drop_away": ["H9002|2099-11-12"], "auto_swap": False, "email_queue": []})
    before = json.dumps(W.S, sort_keys=True)
    W.WAKE.clear()
    called = []
    for fn in ("drop_cmd", "email_alert", "set_switch"):
        setattr(W, fn, lambda *a, _fn=fn, **k: called.append(_fn))
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        W.on_message(W.MQ, None, Msg(f"flight_watcher_pilot2/{sub}", '{"key": "H9001|2099-11-20", "text": "x"}' if sub != "auto_swap/set" else "ON"))
    assert json.dumps(W.S, sort_keys=True) == before and called == [] and W.MQ.msgs == []
    assert not W.FLAGS.get("swap_map") and not W.FLAGS.get("crew_scan") and not W.WAKE.is_set()
    lines = [r.getMessage() for r in caplog.records if "refused" in r.getMessage()]
    assert lines == [f"MQTT {sub} refused: not for a pilot instance ({roles.SUBS[sub]})"]


def test_drop_set_still_works_for_the_admin(load):
    W = load("")
    W.S.update({"drop_away": []})
    marks = []
    W.drop_cmd = lambda p: marks.append(p)
    W.on_message(W.MQ, None, Msg("flight_watcher/drop/set", '{"key": "H9001|2099-11-20"}'))
    assert marks == ['{"key": "H9001|2099-11-20"}']


def test_email_check_never_runs_on_a_pilot(load):
    W = load("pilot2")
    q = [{"key": "H9001|2026-11-20", "pairing": "H9001", "start": "2026-11-20"}]
    W.S["email_queue"] = list(q)

    class Fl:
        urls = []

        def fetch(self, url):
            self.urls.append(url)
            return "<html></html>"
    fl = Fl()
    assert W.email_check(fl, {}) is False and W.S["email_queue"] == q and fl.urls == []
    W.email_alert(json.dumps({"subject": "Open Time: H9002 20NOV", "text": "H9002 20NOV"}))
    assert W.S["email_queue"] == q


def test_drop_scan_and_would_drop_only_on_the_admin(load, monkeypatch):
    W = load("pilot2")
    W.S.update({"drop_away": ["H9002|2099-11-12"], "grid": {}})
    W.drop_scan()
    W.publish_drop()
    assert W.MQ.msgs == [] and "drop_ready" not in W.S
    W.pub("event/drop_ready", {"key": "x"}, retain=False)  # the backstop in pub()
    assert W.MQ.msgs == []
    monkeypatch.setattr(W, "INSTANCE", "")
    W.publish_drop()
    assert [t for t, _, _ in W.MQ.msgs] == ["flight_watcher_pilot2/drop/state"]


def test_ccr_thread_idle_on_a_pilot(load, monkeypatch):
    for inst, polls in (("pilot2", 0), ("", 2)):
        W = load(inst)
        n = {"sleep": 0, "poll": 0}

        def sleep(s):
            n["sleep"] += 1
            if n["sleep"] > 2:
                raise StopIteration
        monkeypatch.setattr(W.time, "sleep", sleep)
        monkeypatch.setattr(W, "ccr_poll", lambda: n.__setitem__("poll", n["poll"] + 1))
        with pytest.raises(StopIteration):
            W.ccr_thread()
        assert n["poll"] == polls, inst
        sys.modules.pop("watcher", None)


def test_auto_swap_forced_off_on_a_pilot(load):
    W = load("pilot2")
    W.S["auto_swap"] = True
    W.enforce_role()
    assert W.S["auto_swap"] is False
    W = load("")
    W.S["auto_swap"] = True
    W.enforce_role()
    assert W.S["auto_swap"] is True


def test_hark_ccr_and_one_writer_gates(load, monkeypatch):
    W = load("pilot2")
    assert W.recall_file_refusal("2026-11-03|H9001|recall", {"status": "approved"}, {}) == \
        "only Ryan's Watcher asks Hark to file CCRs in this release"
    seen = []
    monkeypatch.setattr(W.os, "listdir", lambda p: seen.append(p) or [])
    W.seniority_refresh()
    assert seen == []  # a pilot instance never reads the shared uploads for the seniority list
