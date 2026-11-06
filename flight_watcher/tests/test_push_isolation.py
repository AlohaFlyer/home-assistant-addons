"""FW-0036 / FW-0038: ha/check_push_isolation.py passes the Pako automations snapshot and fails pilot crossings.

Synthetic automations only (made-up targets such as notify.mobile_app_jane_doe_iphone)."""
import copy
import importlib.util
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GUARD = os.path.join(ROOT, "ha", "check_push_isolation.py")
SNAPSHOT = os.path.join(ROOT, "ha", "automations_flight_watcher.yaml")

_spec = importlib.util.spec_from_file_location("check_push_isolation", GUARD)
G = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(G)

LOADERS = pytest.mark.parametrize("use_yaml", [True, False], ids=["pyyaml", "fallback"])

# Crossing 1: James's Watcher event pushed to Ryan's phone.
JAMES_TO_RYAN = """\
- id: '1'
  alias: Flight Watcher James new pairing
  triggers:
  - topic: flight_watcher_james/event/new_pairing
    trigger: mqtt
  actions:
  - action: notify.mobile_app_ryans_iphone_16
    data:
      message: '{{ trigger.payload_json.pairing }}'
      title: New pairing
  mode: queued
"""

# Crossing 2: Ryan's Watcher event pushed to someone else's phone.
RYAN_TO_OTHER = """\
- id: '2'
  alias: Flight Watcher new ticket
  triggers:
  - trigger: mqtt
    topic: flight_watcher/event/ticket_new
  actions:
  - parallel:
    - action: notify.mobile_app_ryans_iphone
      data:
        message: '{{ trigger.payload_json.title }}'
    - action: notify.mobile_app_jane_doe_iphone
      data:
        message: '{{ trigger.payload_json.title }}'
  mode: queued
"""


def _write(tmp_path, text):
    p = tmp_path / "automations.yaml"
    p.write_text(text, encoding="utf-8")
    return str(p)


def _snapshot(use_yaml=True):
    return G.load(SNAPSHOT, use_yaml=use_yaml)


@LOADERS
def test_snapshot_is_clean(use_yaml):
    autos = _snapshot(use_yaml)
    assert len(autos) >= 18 and all(a["alias"].startswith("Flight Watcher") for a in autos)
    offenders, summary = G.check(autos)
    assert offenders == [], offenders
    assert summary.startswith("push isolation OK:") and "0 offender(s)" in summary


def test_fallback_reader_matches_pyyaml():
    pytest.importorskip("yaml")
    assert G.load(SNAPSHOT, use_yaml=False) == G.load(SNAPSHOT, use_yaml=True)


def test_snapshot_is_redacted():
    text = open(SNAPSHOT, encoding="utf-8").read()
    for a in _snapshot():
        for t in a.get("triggers", []):
            if t.get("trigger") == "webhook":
                assert t["webhook_id"] == "<redacted>"
    assert "@gmail" not in text and "drive.google" not in text and "docs.google" not in text


@LOADERS
@pytest.mark.parametrize("text, why", [
    (JAMES_TO_RYAN, "triggered by ['james'] but pushes Ryan"),
    (RYAN_TO_OTHER, "triggered by Ryan's Watcher but pushes non-Ryan targets"),
], ids=["james-event-to-ryan", "ryan-event-to-other"])
def test_crossings_fail(tmp_path, use_yaml, text, why):
    offenders, summary = G.check(G.load(_write(tmp_path, text), use_yaml=use_yaml))
    assert summary.startswith("push isolation FAILED:")
    assert any(why in reason for _, reason in offenders), offenders


def test_cli_exit_codes(tmp_path):
    ok = subprocess.run([sys.executable, GUARD], capture_output=True, text=True)
    assert ok.returncode == 0, ok.stdout
    assert ok.stdout.strip().count("\n") == 0 and ok.stdout.startswith("push isolation OK:")
    bad = subprocess.run([sys.executable, GUARD, _write(tmp_path, JAMES_TO_RYAN + RYAN_TO_OTHER)],
                         capture_output=True, text=True)
    assert bad.returncode == 1
    lines = bad.stdout.strip().splitlines()
    assert [ln.split(":")[0] for ln in lines[:-1]] == ["OFFENDER Flight Watcher James new pairing",
                                                       "OFFENDER Flight Watcher new ticket"]
    missing = subprocess.run([sys.executable, GUARD, str(tmp_path / "none.yaml")], capture_output=True, text=True)
    assert missing.returncode == 2


def _by_alias(autos, alias):
    return next(a for a in autos if a["alias"] == alias)


def test_snapshot_edits_that_cross_are_caught():
    """Each rule, checked by breaking one real automation from the snapshot."""
    base = _snapshot()

    def fails(mutate, why):
        autos = copy.deepcopy(base)
        mutate(autos)
        offenders, _ = G.check(autos)
        assert any(why in reason for _, reason in offenders), offenders

    # ticket_fixed without the reporter == 'ryan' condition
    fails(lambda a: _by_alias(a, "Flight Watcher ticket fixed").__setitem__("conditions", []),
          "without a condition on reporter == 'ryan'")
    # Ryan's recall handler widened to James's prefix
    fails(lambda a: _by_alias(a, "Flight Watcher re-arm from push")["triggers"][0]["event_data"].__setitem__(
        "action", "JRECALL_CONFIRM"), "matches 'JRECALL_CONFIRM'")
    # a handler with no action filter at all
    fails(lambda a: _by_alias(a, "Flight Watcher recall miss alert").__setitem__("conditions", []),
          "matches every action")
    # James entity trigger pushing Ryan
    fails(lambda a: _by_alias(a, "Flight Watcher down")["triggers"][0].__setitem__(
        "entity_id", "sensor.flight_watcher_james_state"), "triggered by ['james'] but pushes Ryan")
    # a push to Ryan carrying James's action prefix
    def jprefix(a):
        auto = _by_alias(a, "Flight Watcher recall miss alert")
        auto["actions"][0]["choose"][0]["sequence"][1]["parallel"][0]["data"]["data"]["actions"][0]["action"] = \
            "JRECALL_CONFIRM|{{ ev.id }}"
    fails(jprefix, "carries action 'JRECALL_CONFIRM'")
