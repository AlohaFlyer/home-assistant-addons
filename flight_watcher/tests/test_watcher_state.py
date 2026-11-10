"""FW-0019 (current month Block / Credit via Schedule Lookup), FW-0024 (switch and Would drop states at connect) and
FW-0028 (Test is the only swap mode, drafts never sent). Synthetic pages and names only."""
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import pytest

import submit as SUB
import swapmap as SM
import versions as VER

FX = Path(__file__).parent / "fixtures"


class FakeClient:
    def __init__(self):
        self.msgs, self.subs = [], []

    def publish(self, topic, payload="", retain=False):
        self.msgs.append((topic, payload, retain))

    def subscribe(self, topic):
        self.subs.append(topic)

    def last(self, topic):
        return next((p for t, p, _ in reversed(self.msgs) if t == topic), None)


class Msg:
    def __init__(self, topic, payload):
        self.topic, self.payload = topic, payload.encode()


class FakeFl:
    def __init__(self, pages):
        self.pages, self.urls = pages, []

    def fetch(self, url):
        self.urls.append(url)
        for k, v in self.pages.items():
            if k in url:
                return v
        return "<html>nothing</html>"


def _import(tmp_path, monkeypatch):
    monkeypatch.setenv("FLIGHT_WATCHER_DATA", str(tmp_path))
    monkeypatch.delenv("FLIGHT_WATCHER_PREFIX", raising=False)
    monkeypatch.delenv("FLIGHT_WATCHER_INSTANCE", raising=False)
    monkeypatch.delenv("FLIGHT_WATCHER_OPTIONS", raising=False)
    (tmp_path / "options.json").write_text(json.dumps({"username": "u", "password": "p"}))
    sys.modules.pop("watcher", None)
    import watcher as W
    return W


@pytest.fixture
def W(tmp_path, monkeypatch):
    W = _import(tmp_path, monkeypatch)
    W.SLEEPS = []
    monkeypatch.setattr(W.time, "sleep", lambda s: W.SLEEPS.append(s))
    monkeypatch.setattr(W, "local_now", lambda: datetime(2026, 11, 6, 8, 0))
    W.S.clear()
    W.MQ = FakeClient()
    yield W
    sys.modules.pop("watcher", None)


# ------------------------------------------------------------------ FW-0019
def _mobile_without_totals():
    """The mobile schedule page as the Watcher reads it for the current month: no Block / Credit / YTD."""
    h = (FX / "mobile_schedule_nov.html").read_text()
    return h.replace("<p>Block 92.33</p><p>Credit 121.48</p><p>YTD 592.22</p>", "")


def _lookup(bd, months, block="96.16", credit="105.47", days_off=16):
    """Schedule Lookup (cmschedules.cgi) for the pilot's own number, laid out like FLICA's (synthetic values)."""
    opts = "".join(f'<option value="{b}" {"selected" if b == bd else ""}> M' for b in months)
    y, m = 2000 + int(bd[2:]), int(bd[:2])
    task = f'TAry[TAry.length]=new Task(1, "SU", "01", "H3647", "PHX", "{y}{m:02d}01", 1, 0, \'H3647\');'
    rows = "".join(f"<TR><TD Colspan=2 Class='left'>{k} &nbsp;&nbsp;</TD>\n<TD Colspan=2 Class='right'>{v} &nbsp;&nbsp;</TD></TR>"
                   for k, v in (("Block", block), ("Credit", credit), ("YTD", "760.37"), ("Days Off", days_off)) if v is not None)
    return (f'<html><script>function pair(pr){{}} {task}</script><select name="BlockDates">{opts}</select>'
            f' DOE, JANE Schedule Last Updated: Nov 4, 2026 13:52:55 HA<TABLE>{rows}</TABLE></html>')


def _pages(nov_credit="105.47"):
    months = ("1026", "1126")
    return {"mobileschedule": _mobile_without_totals(),
            "bd=1126": _lookup("1126", months, credit=nov_credit),
            "bd=1026": _lookup("1026", months, block="42.54", credit="78.17", days_off=8)}


def _read(W, fl):
    # 1.6.2: an instance whose mobile schedule page worked before (as the admin's does) tries that page's shape first;
    # Schedule Lookup then only fills its Block / Credit
    W.S.setdefault("sched_url_ok", f"{W.BASE}/full/mobileschedule.cgi?BCID=001.152&From=MainMenu")
    W.schedule_check(fl, force=True)
    return W.S["schedule"]["2026-11"]


def test_current_month_gets_block_and_credit_from_schedule_lookup(W):
    W.S["own_emp"] = "10008"
    fl = FakeFl(_pages())
    nov = _read(W, fl)
    assert nov["totals"] == {"block": "96:16", "credit": "105:47", "days_off": 15}  # days off stays the schedule page's
    look = [u for u in fl.urls if "bd=1126" in u]
    assert len(look) == 1, fl.urls  # other_months_check reuses the page the totals read loaded
    assert SUB.safe_get(look[0]) and SM.safe_get(look[0]) and "cmschedules.cgi" in look[0]
    assert all(1.5 <= s <= 3.5 for s in W.SLEEPS[-2:]) and len([s for s in W.SLEEPS if 1.5 <= s <= 3.5]) >= 2
    assert W.S["schedule"]["2026-10"]["totals"]["credit"] == "78:17"  # October still via the lookup
    sched = json.loads(W.MQ.last("flight_watcher/schedule"))
    assert sched["months"]["2026-11"]["totals"]["block"] == "96:16"


def test_schedule_versions_record_a_credit_change(W):
    W.S["own_emp"] = "10008"
    _read(W, FakeFl(_pages()))
    assert VER.update(W.DB, {"2026-11": W.S["schedule"]["2026-11"]}, {}, "2026-11-06T18:00:00+00:00")
    _read(W, FakeFl(_pages(nov_credit="106.00")))
    made = VER.update(W.DB, {"2026-11": W.S["schedule"]["2026-11"]}, {}, "2026-11-06T18:30:00+00:00")
    assert made and made[0][0] == "2026-11"
    last = W.DB.get("sched_versions:2026-11")[-1]
    assert "FLICA credit 105:47 -> 106:00" in last["changes"] and last["totals"]["credit"] == "106:00"


def test_missed_lookup_keeps_last_figures_so_no_false_version(W):
    W.S["own_emp"] = "10008"
    _read(W, FakeFl(_pages()))
    VER.update(W.DB, {"2026-11": W.S["schedule"]["2026-11"]}, {}, "2026-11-06T18:00:00+00:00")
    pages = _pages()
    pages["bd=1126"] = "<html>Application error</html>"
    W.LOOKUP_PAGE.update(bd="", html="", at=0)
    nov = _read(W, FakeFl(pages))
    assert nov["totals"]["block"] == "96:16" and nov["totals"]["credit"] == "105:47"
    assert VER.update(W.DB, {"2026-11": nov}, {}, "2026-11-06T18:30:00+00:00") == []


def test_no_lookup_without_own_number_or_when_the_page_has_totals(W):
    fl = FakeFl(_pages())
    nov = _read(W, fl)  # own number not noted yet
    assert "block" not in nov["totals"] and not any("cmschedules" in u for u in fl.urls)
    W.S["own_emp"] = "10008"
    s = {"month": "2026-11", "totals": {"block": "92.33", "credit": "121.48"}}
    fl = FakeFl(_pages())
    W.merge_lookup_totals(fl, s)
    assert fl.urls == [] and s["totals"] == {"block": "92.33", "credit": "121.48"}


def test_lookup_for_another_month_is_not_merged(W):
    W.S["own_emp"] = "10008"
    s = {"month": "2026-11", "totals": {}}
    W.merge_lookup_totals(FakeFl({"bd=1126": _lookup("1026", ("1026", "1126"))}), s)  # FLICA answered with October
    assert s["totals"] == {}


# ------------------------------------------------------------------ FW-0024
def test_connect_states_publish_switches_and_would_drop(W):
    c = W.MQ
    W.connect_states(c)
    assert c.last("flight_watcher/pause/state") == "OFF" and c.last("flight_watcher/hunt/state") == "OFF"
    assert all(r for t, _, r in c.msgs if t.endswith(("pause/state", "hunt/state")))
    drop = json.loads(c.last("flight_watcher/drop/state"))
    assert drop["count"] == 0 and drop["keys"] == []


def test_retained_switch_state_is_restored_and_kept(W):
    c = W.MQ
    W.on_message(c, None, Msg("flight_watcher/pause/state", "ON"))
    assert W.FLAGS["pause"] is True and W.S["switches"]["pause"] is True
    W.on_message(c, None, Msg("flight_watcher/pause/state", ""))  # a cleared retained topic is no state
    assert W.FLAGS["pause"] is True
    W.connect_states(c)
    assert c.last("flight_watcher/pause/state") == "ON"
    W.on_message(c, None, Msg("flight_watcher/hunt/set", "ON"))
    assert W.FLAGS["hunt"] is True and W.S["switches"]["hunt"] is True and c.last("flight_watcher/hunt/state") == "ON"


def test_switches_survive_a_restart_without_the_retained_topic(tmp_path, monkeypatch):
    W = _import(tmp_path, monkeypatch)
    W.S["switches"] = {"pause": True, "hunt": False}
    W.save_state(W.S)
    W = _import(tmp_path, monkeypatch)
    assert W.FLAGS["pause"] is True and W.FLAGS["hunt"] is False
    c = FakeClient()
    W.MQ = c
    W.connect_states(c)
    assert c.last("flight_watcher/pause/state") == "ON"
    sys.modules.pop("watcher", None)


def test_drop_scan_with_nothing_marked_publishes_zero_once(W):
    W.drop_scan()
    assert json.loads(W.MQ.last("flight_watcher/drop/state"))["count"] == 0
    n = len(W.MQ.msgs)
    W.drop_scan()
    assert len(W.MQ.msgs) == n  # not every check


def test_on_connect_schedules_the_states(W, monkeypatch):
    made = {}

    class Client(FakeClient):
        def __init__(self, *a, **k):
            super().__init__()
            made["c"] = self

        def username_pw_set(self, *a):
            pass

        def will_set(self, *a, **k):
            pass

        def connect(self, *a):
            pass

        def loop_start(self):
            pass

    class Timer:
        def __init__(self, delay, fn, args=()):
            made["delay"], self.fn, self.args = delay, fn, args

        def start(self):
            self.fn(*self.args)

    monkeypatch.setattr(W, "mqtt_creds", lambda: {"username": "x", "password": "y", "host": "h", "port": 1883})
    monkeypatch.setattr(W.mqtt, "Client", Client)
    monkeypatch.setattr(W.threading, "Timer", Timer)
    W.OPTS.update(idle_min_s=300, idle_max_s=420, hunt_min_s=30, hunt_max_s=50)
    cl = W.mqtt_start()
    W.MQ = cl
    cl.on_connect(cl, None, None, 0)
    assert made["delay"] >= 1
    assert cl.last("flight_watcher/pause/state") == "OFF" and cl.last("flight_watcher/hunt/state") == "OFF"
    assert json.loads(cl.last("flight_watcher/drop/state"))["count"] == 0
    assert "flight_watcher/swap_mode/set" not in cl.subs and "flight_watcher/pause/state" in cl.subs
    assert cl.last("flight_watcher/swap_mode/state") == "Test"


# ------------------------------------------------------------------ FW-0028
def test_swap_mode_is_a_read_only_sensor_and_the_select_is_removed(W):
    c = FakeClient()
    W.discovery(c)
    cfgs = {t: p for t, p, _ in c.msgs}
    assert cfgs["homeassistant/select/flight_watcher/swap_mode/config"] == ""  # removes the old select
    sensor = json.loads(cfgs["homeassistant/sensor/flight_watcher/swap_mode/config"])
    assert sensor["default_entity_id"] == "sensor.flight_watcher_swap_mode"
    assert "command_topic" not in sensor and "options" not in sensor
    assert not any(t.startswith("homeassistant/select/") and p for t, p in cfgs.items())
    W.publish_swap_mode(c)
    attr = json.loads(c.last("flight_watcher/swap_mode/attr"))
    assert attr["sends"] is False and "draft only, never sent" in attr["note"]


@pytest.mark.parametrize("stored", ["Live", "Confirm", "live", "confirm", None])
def test_stored_confirm_or_live_becomes_test(W, stored):
    if stored is not None:
        W.S["swap_mode"] = stored
    W.migrate_swap_mode()
    assert W.S["swap_mode"] == "Test"


def test_swap_mode_set_is_ignored(W):
    W.S["swap_mode"] = "Test"
    W.on_message(W.MQ, None, Msg("flight_watcher/swap_mode/set", "Live"))
    assert W.S["swap_mode"] == "Test" and W.MQ.last("flight_watcher/swap_mode/state") is None


def test_drop_draft_is_labelled(W):
    W.S["schedule"] = {"2026-11": {"month": "2026-11", "items": [{"trip": "H3629", "start": "2026-11-14", "end": "2026-11-15"}]}}
    W.S["drop_away"] = ["H3629|2026-11-14"]
    W.S["pot_urls"] = {"2026-11": "https://ha2.flica.net/full/mobileot.cgi?BCID=003.152"}
    W.S["grid"] = {"2026-11-14": {"net": 3, "color": "green"}, "2026-11-15": {"net": 2, "color": "green"}}
    W.drop_scan()
    rec = W.S["drop_tests"][-1]
    assert rec["draft"] == "draft only, never sent" and rec["why"].startswith("draft only, never sent")
    assert rec["sent"] is False and rec["mode"] == "Test"


# ------------------------------------------------------------------ FW-0063 (1.5.0)
def test_state_attr_carries_role_and_features(W, monkeypatch):
    """sensor.<prefix>_state says which role the Watcher has and its features; the schedule card draws the drop mark
    from role == "admin" (and the HA owner viewing)."""
    W.set_machine("idle", "ok")
    a = json.loads(W.MQ.last("flight_watcher/state_attr"))
    assert a["role"] == "admin" and a["features"] == list(W.ROLES.FEATURES) and a["instance"] == ""
    assert a["version"] == W.VERSION and set(a) == {"note", "version", "since", "instance", "doh", "role", "features"}
    monkeypatch.setattr(W, "INSTANCE", "pilot2")
    W.set_machine("needs_settings", "send username and password")
    a = json.loads(W.MQ.last("flight_watcher/state_attr"))
    assert a["role"] == "pilot" and a["features"] == ["core", "prefs", "tickets", "uploads"] and a["instance"] == "pilot2"
