"""1.6.0 (FW-0061): a portal pilot's pay and tax prefs (pref/set, prefs.json; PORTAL_CONTRACT.md 5.3): bounds, the
Watcher's own pay line reading them, and the admin never reading a prefs.json. 1.6.2 (Release A item 12): a portal
pilot's HA helpers are never read (they were deleted with his HA dashboard), and the values the 1.6.0 seed copied from
helpers that were never set (federal 0 %, state 0 %, longevity year 1) are flagged once for the card. Synthetic values
only."""
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


def _no_helper_asked(ha):
    return not [u for u in ha.urls if u.endswith(("_tax_pct", "_longevity_year", "_er_trips"))]


def test_prefs_are_read_and_the_helpers_never(portal_pilot):
    """1.6.2: the helpers exist here (and differ) but are never asked for: not at the start, not by the pay line; a
    pref that is not set is the code default (federal 22 %, state 0 %, the DOH's year, no ER trips)."""
    W, ha = portal_pilot("pilot2", states=_helpers(P))
    W.portal_start(threads=False)
    W.portal_export_once(full=True)
    assert _no_helper_asked(ha)
    W.pref_cmd(json.dumps({"key": "federal_tax_pct", "value": 20}))
    W.pref_cmd(json.dumps({"key": "longevity_year", "value": 9}))
    W.pref_cmd(json.dumps({"key": "er_trips", "value": "-H9002|2026-11-24"}))
    W.TAX["pct"] = None
    assert W.tax_pct() == 20.0  # 20 from prefs + the code's 0 for state (never the helper's 5)
    rate, yr, er = W.pay_settings()
    assert yr == 9 and er == ["-H9002|2026-11-24"] and rate
    d = json.load(open(W.PREFS_FILE))
    d["values"] = {}
    json.dump(d, open(W.PREFS_FILE, "w"))
    W.TAX["pct"] = None
    assert W.tax_pct() == 22.0
    assert W.pay_settings()[2] == []
    assert _no_helper_asked(ha)


def _planted(W, values, gap_s=0.00002, seeded="2026-11-09T20:14:01.051153+00:00"):
    """prefs.json as the 1.6.0 seed left it: each value stamped a few microseconds before 'seeded' (gap_s apart)."""
    from datetime import datetime, timedelta
    t = datetime.fromisoformat(seeded)
    upd = {k: (t - timedelta(seconds=gap_s)).isoformat() for k in values}
    json.dump({"values": values, "updated": upd, "seeded": seeded}, open(W.PREFS_FILE, "w"))


def test_values_from_never_set_helpers_are_flagged_once(portal_pilot):
    W, ha = portal_pilot("pilot2")
    _planted(W, {"federal_tax_pct": 0, "state_tax_pct": 0, "longevity_year": 1, "er_trips": ""})
    W.portal_start(threads=False)
    d = json.load(open(W.PREFS_FILE))
    assert d["unconfirmed"] == ["federal_tax_pct", "longevity_year", "state_tax_pct"] and d["checked"]
    assert d["values"]["federal_tax_pct"] == 0  # kept as they are, only flagged
    st = W.pref_states()
    assert st[f"input_number.{P}_federal_tax_pct"]["attributes"]["unconfirmed"] is True
    assert "unconfirmed" not in st[f"input_text.{P}_er_trips"]["attributes"]
    W.pref_cmd(json.dumps({"key": "federal_tax_pct", "value": 0}))  # the card's Keep these, or his own pick
    d = json.load(open(W.PREFS_FILE))
    assert d["unconfirmed"] == ["longevity_year", "state_tax_pct"]
    assert "unconfirmed" not in W.pref_states()[f"input_number.{P}_federal_tax_pct"]["attributes"]
    import sys
    sys.modules.pop("watcher", None)
    W, ha = portal_pilot("pilot2")  # a restart: checked once only, what he confirmed stays confirmed
    W.portal_start(threads=False)
    assert json.load(open(W.PREFS_FILE))["unconfirmed"] == ["longevity_year", "state_tax_pct"]
    assert _no_helper_asked(ha)


def test_values_the_pilot_set_are_not_flagged(portal_pilot):
    W, _ = portal_pilot("pilot2")
    _planted(W, {"federal_tax_pct": 0, "state_tax_pct": 4.25, "longevity_year": 7}, gap_s=60)  # a pref/set before
    W.portal_start(threads=False)
    assert json.load(open(W.PREFS_FILE))["unconfirmed"] == []
    W, _ = portal_pilot("pilot3")
    _planted(W, {"federal_tax_pct": 24, "state_tax_pct": 4.25, "longevity_year": 7})  # seeded, not at the minimum
    W.portal_start(threads=False)
    assert json.load(open(W.PREFS_FILE))["unconfirmed"] == []
