"""1.6.0 (FW-0061): a portal pilot's pay and tax prefs (pref/set, prefs.json; PORTAL_CONTRACT.md 5.3): bounds,
precedence over the HA helpers in the Watcher's own pay line, a one-time seed from the helpers, and the admin never
reading a prefs.json. Synthetic values only."""
import json
import os
import stat

import pytest

import roles
from conftest import ha_state

P = "flight_watcher_pilot2"


class Msg:
    def __init__(self, topic, payload):
        self.topic, self.payload = topic, payload.encode()


def _helpers(prefix, fed="30.0", st="5.0", yr="4.0", er="+H9001|2026-11-20"):
    return {f"input_number.{prefix}_federal_tax_pct": ha_state(f"input_number.{prefix}_federal_tax_pct", fed),
            f"input_number.{prefix}_state_tax_pct": ha_state(f"input_number.{prefix}_state_tax_pct", st),
            f"input_number.{prefix}_longevity_year": ha_state(f"input_number.{prefix}_longevity_year", yr),
            f"input_text.{prefix}_er_trips": ha_state(f"input_text.{prefix}_er_trips", er)}


@pytest.mark.parametrize("key,value,want", [
    ("federal_tax_pct", 22, 22), ("federal_tax_pct", "22.5", 22.5), ("federal_tax_pct", 0, 0),
    ("federal_tax_pct", 45, 45), ("state_tax_pct", 7.25, 7.25), ("state_tax_pct", 15, 15),
    ("longevity_year", 12, 12), ("longevity_year", 1.0, 1), ("er_trips", "", ""),
    ("er_trips", "+H3631|2026-11-12,-H3628B|2026-11-20", "+H3631|2026-11-12,-H3628B|2026-11-20"),
])
def test_bounds_accept(key, value, want):
    got = roles.pref_value(key, value)
    assert got == want and type(got) is type(want)


@pytest.mark.parametrize("key,value", [
    ("federal_tax_pct", 45.5), ("federal_tax_pct", -0.5), ("federal_tax_pct", 22.3), ("federal_tax_pct", True),
    ("federal_tax_pct", None), ("federal_tax_pct", "nan"), ("federal_tax_pct", [22]), ("state_tax_pct", 15.25),
    ("state_tax_pct", 1.1), ("longevity_year", 0), ("longevity_year", 13), ("longevity_year", 2.5),
    ("er_trips", "H3631|2026-11-12"), ("er_trips", "+h3631|2026-11-12"), ("er_trips", "+H3631|2026-11-12,"),
    ("er_trips", "+H1|2026-11-12," * 20), ("er_trips", 5), ("month_offset", 1), ("vac", "x"), (None, 1),
    ("federal_tax_pct", int("9" * 400)), ("federal_tax_pct", "inf"), ("federal_tax_pct", float("inf")),
    ("state_tax_pct", "-Infinity"), ("longevity_year", float("nan")),
])
def test_bounds_refuse(key, value):
    with pytest.raises(ValueError):
        roles.pref_value(key, value)


def test_pref_set_saved_private_and_marked(portal_pilot, caplog):
    W, _ = portal_pilot("pilot2")
    W.portal_start(threads=False)
    W.TAX.update(at=1e12, pct=99.0)
    W.on_message(W.MQ, None, Msg(f"{P}/pref/set", '{"key": "federal_tax_pct", "value": 24.5}'))
    d = json.load(open(W.PREFS_FILE))
    assert d["values"]["federal_tax_pct"] == 24.5 and stat.S_IMODE(os.stat(W.PREFS_FILE).st_mode) == 0o600
    assert W.TAX["pct"] is None  # the pay line's tax % is read again
    assert f"input_number.{P}_federal_tax_pct" in W.EXPORT["dirty"]
    W.on_message(W.MQ, None, Msg(f"{P}/pref/set", '{"key": "federal_tax_pct", "value": 99}'))
    W.on_message(W.MQ, None, Msg(f"{P}/pref/set", '{"key": "federal_tax_pct"}'))
    W.on_message(W.MQ, None, Msg(f"{P}/pref/set", "not json"))
    assert json.load(open(W.PREFS_FILE))["values"]["federal_tax_pct"] == 24.5  # refusals change nothing
    assert "24.5" not in caplog.text  # the value is not logged


def test_prefs_first_then_helpers(portal_pilot):
    W, ha = portal_pilot("pilot2", states=_helpers(P))
    W.portal_start(threads=False)  # seeds 30 / 5 / 4 / the ER list from the helpers
    W.pref_cmd(json.dumps({"key": "federal_tax_pct", "value": 20}))
    W.pref_cmd(json.dumps({"key": "longevity_year", "value": 9}))
    W.pref_cmd(json.dumps({"key": "er_trips", "value": "-H9002|2026-11-24"}))
    ha.states = _helpers(P, fed="40.0", st="9.0", yr="2.0", er="+H7777|2026-11-01")  # the helpers moved on
    W.TAX["pct"] = None
    assert W.tax_pct() == 25.0  # 20 from prefs + 5 seeded from the state helper
    rate, yr, er = W.pay_settings()
    assert yr == 9 and er == ["-H9002|2026-11-24"] and rate
    # a pref that is not set falls back to its helper
    d = json.load(open(W.PREFS_FILE))
    d["values"].pop("state_tax_pct")
    json.dump(d, open(W.PREFS_FILE, "w"))
    W.TAX["pct"] = None
    assert W.tax_pct() == 29.0  # 20 + the helper's 9


def test_seed_once(portal_pilot):
    W, ha = portal_pilot("pilot2", states=_helpers(P, fed="22.3", yr="13.0"))  # two helper values out of bounds
    W.portal_start(threads=False)
    d = json.load(open(W.PREFS_FILE))
    assert d["values"] == {"state_tax_pct": 5, "er_trips": "+H9001|2026-11-20"} and d["seeded"]
    asked = list(ha.urls)
    import sys
    sys.modules.pop("watcher", None)
    W, ha = portal_pilot("pilot2", states=_helpers(P, fed="11.0"))  # a restart: the file exists
    W.portal_start(threads=False)
    assert ha.urls == [] and json.load(open(W.PREFS_FILE))["values"]["state_tax_pct"] == 5
    assert sorted(u.rsplit("/", 1)[1] for u in asked) == sorted(_helpers(P))


def test_state_json_shows_prefs(portal_pilot):
    W, _ = portal_pilot("pilot2")
    W.portal_start(threads=False)
    W.pref_cmd(json.dumps({"key": "state_tax_pct", "value": 4.25}))
    st = W.pref_states()
    assert st[f"input_number.{P}_state_tax_pct"]["state"] == "4.25"
    assert st[f"input_number.{P}_state_tax_pct"]["attributes"]["step"] == 0.25
    assert st[f"input_number.{P}_federal_tax_pct"]["state"] == "unknown"
    assert st[f"input_text.{P}_er_trips"]["state"] == ""


def test_the_admin_never_reads_prefs_json(portal_pilot, monkeypatch):
    W, ha = portal_pilot("", portal=True, states=_helpers("flight_watcher", fed="30.0", st="2.0", yr="6.0", er=""))
    json.dump({"values": {"federal_tax_pct": 10, "state_tax_pct": 0, "longevity_year": 12, "er_trips": "+H1|2026-11-01"}},
              open(W.PREFS_FILE, "w"))  # planted: must be ignored
    opened = []
    real_open = open

    def spy(path, *a, **k):
        opened.append(str(path))
        return real_open(path, *a, **k)
    monkeypatch.setattr("builtins.open", spy)
    W.TAX["pct"] = None
    assert W.tax_pct() == 32.0
    rate, yr, er = W.pay_settings()
    assert yr == 6 and er == []
    assert W.pref_get("federal_tax_pct") is None and W.prefs_read() == {} and W.prefs_seed() is None
    assert W.PREFS_FILE not in opened
    assert W.pref_cmd('{"key": "federal_tax_pct", "value": 20}') is False
    assert json.load(real_open(W.PREFS_FILE))["values"]["federal_tax_pct"] == 10


def test_a_huge_integer_is_a_refusal_not_an_overflow(portal_pilot):
    """float() of a 400-digit JSON integer is OverflowError: it got past check_pref and pref_cmd and, over MQTT, out
    of on_message (paho's network thread then ends)."""
    import portal as PT
    huge = '{"key": "federal_tax_pct", "value": %s}' % ("9" * 400)
    with pytest.raises(PT.PortalError, match="not a number"):
        PT.check_pref(huge, "0123456789abcdef")
    W, _ = portal_pilot("pilot2")
    W.portal_start(threads=False)
    W.pref_cmd(json.dumps({"key": "federal_tax_pct", "value": 24.5}))
    before = open(W.PREFS_FILE).read()
    W.on_message(W.MQ, None, Msg(f"{P}/pref/set", huge))  # refused, no exception
    assert open(W.PREFS_FILE).read() == before


def test_seed_waits_for_home_assistant(portal_pilot, caplog):
    """The first portal start meets an HA restart: nothing is seeded (no prefs.json, logged once) and the next export
    sweep seeds all four once HA answers, instead of the seed being used up empty."""
    import logging
    W, ha = portal_pilot("pilot2", states=_helpers(P))
    ha.down = True
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        W.portal_start(threads=False)
        W.portal_export_once(full=True)
        W.portal_export_once(full=True)
    assert not os.path.exists(W.PREFS_FILE)
    assert caplog.text.count("portal prefs not seeded yet") == 1
    assert W.pref_states()[f"input_number.{P}_federal_tax_pct"]["state"] == "unknown"
    ha.down = False
    W.portal_export_once(full=True)
    d = json.load(open(W.PREFS_FILE))
    assert d["values"] == {"federal_tax_pct": 30, "state_tax_pct": 5, "longevity_year": 4,
                           "er_trips": "+H9001|2026-11-20"} and d["seeded"]
    assert W.pref_states()[f"input_number.{P}_federal_tax_pct"]["state"] == "30.0"
    W.TAX["pct"] = None
    assert W.tax_pct() == 35.0
    ha.urls.clear()
    W.portal_export_once(full=True)
    assert not [u for u in ha.urls if u.endswith(("_tax_pct", "_longevity_year", "_er_trips"))]  # done: never again


@pytest.mark.parametrize("bad", ["unknown", "unavailable"])
def test_seed_waits_while_a_helper_is_not_loaded(portal_pilot, bad):
    W, ha = portal_pilot("pilot2", states=_helpers(P, st=bad))
    W.portal_start(threads=False)
    assert not os.path.exists(W.PREFS_FILE)
    ha.states = _helpers(P)
    W.portal_export_once(full=True)
    assert json.load(open(W.PREFS_FILE))["values"]["state_tax_pct"] == 5


def test_seed_takes_a_never_set_er_list_as_empty(portal_pilot):
    """HA keeps an input_text with no initial value that was never set at 'unknown' for good (restored as such after
    a restart): a pilot who never tapped an ER toggle. It seeds as the empty list instead of holding the seed (and the
    three number prefs) back on every sweep; the portal and the Watcher's own pay line then agree."""
    W, ha = portal_pilot("pilot2", states=_helpers(P, er="unknown"))
    W.portal_start(threads=False)
    d = json.load(open(W.PREFS_FILE))
    assert d["values"] == {"federal_tax_pct": 30, "state_tax_pct": 5, "longevity_year": 4, "er_trips": ""}
    assert d["seeded"]
    st = W.pref_states()
    assert st[f"input_number.{P}_federal_tax_pct"]["state"] == "30.0" and st[f"input_text.{P}_er_trips"]["state"] == ""
    W.TAX["pct"] = None
    assert W.tax_pct() == 35.0
    _, yr, er = W.pay_settings()
    assert yr == 4 and er == []
    ha.urls.clear()
    W.portal_export_once(full=True)
    assert not [u for u in ha.urls if u.endswith(("_tax_pct", "_longevity_year", "_er_trips"))]  # done: never again


def test_seed_with_a_missing_helper_completes(portal_pilot):
    helpers = _helpers(P)
    helpers.pop(f"input_number.{P}_longevity_year")  # 404: nothing to seed for it
    W, ha = portal_pilot("pilot2", states=helpers)
    W.portal_start(threads=False)
    d = json.load(open(W.PREFS_FILE))
    assert d["values"] == {"federal_tax_pct": 30, "state_tax_pct": 5, "er_trips": "+H9001|2026-11-20"}
    assert d["seeded"]


def test_a_pref_set_before_the_seed_is_kept(portal_pilot):
    W, ha = portal_pilot("pilot2", states=_helpers(P))
    ha.down = True
    W.portal_start(threads=False)
    W.on_message(W.MQ, None, Msg(f"{P}/pref/set", '{"key": "federal_tax_pct", "value": 24.5}'))
    assert "seeded" not in json.load(open(W.PREFS_FILE))
    ha.down = False
    W.portal_export_once(full=True)
    d = json.load(open(W.PREFS_FILE))
    assert d["values"] == {"federal_tax_pct": 24.5, "state_tax_pct": 5, "longevity_year": 4,
                           "er_trips": "+H9001|2026-11-20"} and d["seeded"]
