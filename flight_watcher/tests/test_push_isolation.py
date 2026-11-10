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


# Crossing 3 (review fix): a wildcard first level matches both pilots' Watchers, so it may not push Ryan.
WILDCARD_TO_RYAN = """\
- id: '3'
  alias: Flight Watcher any new pairing
  triggers:
  - topic: +/event/new_pairing
    trigger: mqtt
  actions:
  - action: notify.mobile_app_ryans_iphone
    data:
      message: '{{ trigger.payload_json.pairing }}'
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
    (WILDCARD_TO_RYAN, "triggered by ['james'] but pushes Ryan"),
    (WILDCARD_TO_RYAN.replace("+/event/new_pairing", "'#'"), "triggered by ['james'] but pushes Ryan"),
], ids=["james-event-to-ryan", "ryan-event-to-other", "wildcard-to-ryan", "hash-to-ryan"])
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
                                                       "OFFENDER Flight Watcher new ticket",
                                                       "OFFENDER Flight Watcher new ticket"]  # 1.5.0: + unlisted target
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


# ---------------------------------------------------------------- 1.5.0 (FW-0063): pilots from ha/pilots.json
PILOTS_JSON = os.path.join(ROOT, "ha", "pilots.json")

# A third pilot's Watcher event pushed to James's (made-up) phone.
PILOT3_TO_JAMES = """\
- id: '31'
  alias: Flight Watcher Pilot3 new pairing
  triggers:
  - topic: flight_watcher_pilot3/event/new_pairing
    trigger: mqtt
  actions:
  - action: notify.mobile_app_jane_doe_phone
    data:
      message: '{{ trigger.payload_json.pairing }}'
  mode: queued
"""

# A pilot whose name has an underscore: its topic and its entity both count as that pilot's, not Ryan's.
UNDERSCORE_NAME = """\
- id: '32'
  alias: Flight Watcher Jane Doe new pairing
  triggers:
  - topic: flight_watcher_jane_doe/event/new_pairing
    trigger: mqtt
  actions:
  - action: notify.mobile_app_ryans_iphone
    data:
      message: '{{ trigger.payload_json.pairing }}'
  mode: queued
- id: '33'
  alias: Flight Watcher Jane Doe down
  triggers:
  - trigger: state
    entity_id: sensor.flight_watcher_jane_doe_state
  actions:
  - action: notify.mobile_app_ryans_iphone_16
    data:
      message: down
  mode: single
"""

# An id of a pilot ha/pilots.json does not know: it used to read as Ryan's.
UNKNOWN_PREFIX = """\
- id: '34'
  alias: Flight Watcher Bob down
  triggers:
  - trigger: state
    entity_id: sensor.flight_watcher_bob_state
  actions:
  - action: notify.mobile_app_ryans_iphone
    data:
      message: down
  mode: single
"""


@pytest.fixture
def pilots():
    """Configure the guard with extra pilots for one test; ha/pilots.json is loaded back afterwards."""
    import json

    def use(extra, targets=None, prefixes=None):
        cfg = json.load(open(PILOTS_JSON, encoding="utf-8"))
        cfg["pilots"] += extra
        cfg["targets"].update(targets or {})
        cfg["action_prefixes"].update(prefixes or {})
        G.configure(cfg)
        return cfg
    yield use
    G.load_pilots()


def test_pilots_json_is_what_the_guard_used_to_hard_code():
    """The move to ha/pilots.json changes nothing for Ryan and James."""
    import json
    cfg = json.load(open(PILOTS_JSON, encoding="utf-8"))
    assert cfg["admin"] == "ryan" and cfg["pilots"] == ["james"]
    G.ensure_loaded()  # 1.5.0 review fix: the guard reads its files on first use, not at import
    assert G.RYAN == "ryan" and G.SECOND_PILOTS == ("james",)
    assert G.RYAN_TARGETS == {"notify.mobile_app_ryans_iphone_16", "notify.mobile_app_ryans_iphone",
                              "notify.mobile_app_ryan_macbook"}
    assert G.ACTION_PREFIXES == {"ryan": ("RECALL_", "FLIGHT_WATCHER_"), "james": ("JRECALL_", "FLIGHT_WATCHER_JAMES_")}
    import roles
    assert G.RESERVED == roles.RESERVED and G.NAME_RE.pattern == roles.NAME_RE.pattern


@LOADERS
def test_pilot3_pushing_james_fails(tmp_path, use_yaml, pilots):
    pilots(["pilot3"], targets={"james": ["notify.mobile_app_jane_doe_phone"]})
    offenders, summary = G.check(G.load(_write(tmp_path, PILOT3_TO_JAMES), use_yaml=use_yaml))
    assert summary.startswith("push isolation FAILED:")
    assert any("triggered by ['pilot3'] but pushes james: ['notify.mobile_app_jane_doe_phone']" in r for _, r in offenders), offenders
    # James's own event to his own phone is fine; a push to his phone carrying an action that is not his is not
    own = PILOT3_TO_JAMES.replace("flight_watcher_pilot3/", "flight_watcher_james/")
    assert G.check(G.load(_write(tmp_path, own), use_yaml=use_yaml))[0] == []
    act = own.replace("      message: '{{ trigger.payload_json.pairing }}'",
                      "      message: x\n      data:\n        actions:\n        - action: RECALL_CONFIRM\n          title: OK")
    assert [r for _, r in G.check(G.load(_write(tmp_path, act), use_yaml=use_yaml))[0]] == [
        "push to notify.mobile_app_jane_doe_phone carries action 'RECALL_CONFIRM', not one of james's prefixes"]
    assert G.check(G.load(_write(tmp_path, act.replace("RECALL_CONFIRM", "JRECALL_CONFIRM")), use_yaml=use_yaml))[0] == []


@LOADERS
def test_underscore_name(tmp_path, use_yaml, pilots):
    text = _write(tmp_path, UNDERSCORE_NAME)
    # unknown to ha/pilots.json: both automations name an unknown pilot (1.4.12 read the topic as neutral and the
    # entity as Ryan's, so both passed)
    offenders, _ = G.check(G.load(text, use_yaml=use_yaml))
    assert {a for a, _ in offenders} == {"Flight Watcher Jane Doe new pairing", "Flight Watcher Jane Doe down"}
    assert all("unknown pilot" in r or "but pushes Ryan" in r for _, r in offenders), offenders
    # known (with a shorter name that is a prefix of it): the longest name wins, and both push Ryan from her Watcher
    pilots(["jane", "jane_doe"])
    offenders, _ = G.check(G.load(text, use_yaml=use_yaml))
    assert sorted(offenders) == [
        ("Flight Watcher Jane Doe down", "triggered by ['jane_doe'] but pushes Ryan: ['notify.mobile_app_ryans_iphone_16']"),
        ("Flight Watcher Jane Doe new pairing", "triggered by ['jane_doe'] but pushes Ryan: ['notify.mobile_app_ryans_iphone']")]


@LOADERS
def test_unknown_prefix_is_an_offender(tmp_path, use_yaml):
    offenders, summary = G.check(G.load(_write(tmp_path, UNKNOWN_PREFIX), use_yaml=use_yaml))
    assert summary.startswith("push isolation FAILED:")
    assert ("Flight Watcher Bob down", "names an unknown pilot ['bob']: add it to ha/pilots.json") in offenders
    # Ryan's own ids (first word reserved) and James's stay known
    assert G._entity_pilot("state") == G._entity_pilot("last_new_pairing") == G._entity_pilot("month_offset") == "ryan"
    assert G._entity_pilot("james_state") == "james" and G._entity_pilot("bob_state") == "?bob"


def test_every_id_in_the_ha_snapshot_belongs_to_a_known_pilot():
    """Every Flight Watcher topic and entity in the automations, dashboards and package snapshots maps to Ryan or a
    pilot in ha/pilots.json (none to an unknown pilot), so the snapshot still reports 0 offenders."""
    found = set()
    for name in ("automations_flight_watcher.yaml", "dashboard_flight_watcher.json",
                 os.path.join("packages", "flight_watcher_wx.yaml")):
        found |= G._pilots_in(open(os.path.join(ROOT, "ha", name), encoding="utf-8").read())
    assert found == {"ryan", "james"}, found


def test_cli_takes_another_pilots_file(tmp_path):
    import json
    cfg = json.load(open(PILOTS_JSON, encoding="utf-8"))
    cfg["pilots"].append("pilot3")
    cfg["targets"]["james"] = ["notify.mobile_app_jane_doe_phone"]
    pj = tmp_path / "pilots.json"
    pj.write_text(json.dumps(cfg))
    bad = subprocess.run([sys.executable, GUARD, _write(tmp_path, PILOT3_TO_JAMES), f"--pilots={pj}"],
                         capture_output=True, text=True)
    assert bad.returncode == 1 and "but pushes james" in bad.stdout
    pj.write_text('{"admin": "ryan"}')
    assert subprocess.run([sys.executable, GUARD, f"--pilots={pj}"], capture_output=True, text=True).returncode == 2


# Review fix (1.5.0): with two or more pilots a notify target ha/pilots.json gives to nobody cannot be told apart, so
# it is an offender (fail closed). James's targets stay [] here, as in the shipped ha/pilots.json.
PILOT3_TO_UNLISTED_ACTION = PILOT3_TO_JAMES.replace(
    "      message: '{{ trigger.payload_json.pairing }}'",
    "      message: x\n      data:\n        actions:\n        - action: JRECALL_CONFIRM|{{ trigger.payload_json.id }}\n"
    "          title: OK")

NEUTRAL_READS_TWO_PILOTS = """\
- id: '35'
  alias: Flight Watcher morning digest
  triggers:
  - trigger: time
    at: '06:00:00'
  actions:
  - action: notify.mobile_app_jane_doe_phone
    data:
      message: '{{ states(''sensor.flight_watcher_pilot3_state'') }} {{ states(''sensor.flight_watcher_james_state'') }}'
  mode: single
"""


@LOADERS
@pytest.mark.parametrize("text, why", [
    (PILOT3_TO_JAMES, "notify target(s) ['notify.mobile_app_jane_doe_phone'] not in ha/pilots.json"),
    (PILOT3_TO_UNLISTED_ACTION, "carries james's action 'JRECALL_CONFIRM'"),
    (NEUTRAL_READS_TWO_PILOTS, "neutral trigger reads several pilots ['james', 'pilot3'] and pushes"),
], ids=["pilot3-to-unlisted", "pilot3-james-action-to-unlisted", "neutral-reads-two-pilots"])
def test_unlisted_targets_fail_closed(tmp_path, use_yaml, pilots, text, why):
    cfg = pilots(["pilot3"], targets={"pilot3": ["notify.mobile_app_pilot3_phone"]},
                 prefixes={"pilot3": ["P3RECALL_", "FLIGHT_WATCHER_PILOT3_"]})
    assert cfg["targets"]["james"] == []
    offenders, summary = G.check(G.load(_write(tmp_path, text), use_yaml=use_yaml))
    assert summary.startswith("push isolation FAILED:")
    reasons = [r for _, r in offenders]
    assert any("not in ha/pilots.json" in r for r in reasons), offenders
    assert any(why in r for r in reasons), offenders


@LOADERS
def test_listed_targets_stay_clean(tmp_path, use_yaml, pilots):
    """The same automations pushing the right pilot's listed target, reading one pilot, pass."""
    pilots(["pilot3"], targets={"pilot3": ["notify.mobile_app_pilot3_phone"]},
           prefixes={"pilot3": ["P3RECALL_", "FLIGHT_WATCHER_PILOT3_"]})
    own = PILOT3_TO_UNLISTED_ACTION.replace("notify.mobile_app_jane_doe_phone", "notify.mobile_app_pilot3_phone")
    assert G.check(G.load(_write(tmp_path, own.replace("JRECALL_", "P3RECALL_")), use_yaml=use_yaml))[0] == []
    one = NEUTRAL_READS_TWO_PILOTS.replace("notify.mobile_app_jane_doe_phone", "notify.mobile_app_pilot3_phone")
    one = one.replace(" {{ states(''sensor.flight_watcher_james_state'') }}", "")
    assert G.check(G.load(_write(tmp_path, one), use_yaml=use_yaml))[0] == []


def test_cli_fails_closed_with_the_shipped_james_targets(tmp_path):
    """The CLI with pilots.json plus a third pilot, James's targets left [] as shipped: pilot3 to an unlisted phone
    fails (it passed before this fix)."""
    import json
    cfg = json.load(open(PILOTS_JSON, encoding="utf-8"))
    cfg["pilots"].append("pilot3")
    assert cfg["targets"]["james"] == []
    pj = tmp_path / "pilots.json"
    pj.write_text(json.dumps(cfg))
    bad = subprocess.run([sys.executable, GUARD, _write(tmp_path, PILOT3_TO_JAMES), f"--pilots={pj}"],
                         capture_output=True, text=True)
    assert bad.returncode == 1 and "not in ha/pilots.json" in bad.stdout


# ---------------------------------------------------------------- 1.5.0 review fixes
def _tree(tmp_path, pilots_text=None, roles_text=None):
    """A copy of the guard in tmp_path/ha with its own pilots.json and ../flight_watcher/roles.py (None: the real
    file; False: left out) and the real snapshot, so a broken default never touches the repo."""
    import shutil
    ha, fw = tmp_path / "ha", tmp_path / "flight_watcher"
    ha.mkdir(parents=True)
    fw.mkdir()
    shutil.copy(GUARD, ha / "check_push_isolation.py")
    shutil.copy(SNAPSHOT, ha / "automations_flight_watcher.yaml")
    for dst, src, text in ((ha / "pilots.json", PILOTS_JSON, pilots_text),
                           (fw / "roles.py", os.path.join(ROOT, "flight_watcher", "roles.py"), roles_text)):
        if text is None:
            shutil.copy(src, dst)
        elif text is not False:
            dst.write_text(text, encoding="utf-8")
    return str(ha / "check_push_isolation.py")


def _run(*args):
    return subprocess.run([sys.executable, *args], capture_output=True, text=True)


@pytest.mark.parametrize("pilots_text, roles_text, names", [
    ('{"admin": "ryan", "pilots": "james"}', None, "pilots.json"),  # pilots is a string
    (False, None, "pilots.json"),  # missing
    ('{"admin": "ryan", "pilots": [', None, "pilots.json"),  # not JSON
    ('{"admin": "ryan", "pilots": ["jane_"]}', None, "pilots.json"),  # a name HA cannot keep in an id
    ('{"admin": "ryan", "pilots": ["james"], "targets": ["x"]}', None, "pilots.json"),  # targets not an object
    (None, False, "roles.py"),  # roles.py missing
    (None, "RESERVED = frozenset({\n", "roles.py"),  # roles.py broken
    (None, "import re\nNAME_RE = re.compile('x')\n", "roles.py"),  # no RESERVED
], ids=["pilots-a-string", "pilots-missing", "pilots-not-json", "pilots-bad-name", "targets-a-list",
        "roles-missing", "roles-syntax", "roles-no-reserved"])
def test_cli_exit_2_when_the_default_setup_cannot_be_read(tmp_path, pilots_text, roles_text, names):
    """Review fix (1.5.0): a broken ha/pilots.json or roles.py is exit 2 with one line naming that file, not a
    traceback with exit 1 (the offenders code), and importing the guard never reads either file."""
    guard = _tree(tmp_path, pilots_text, roles_text)
    r = _run(guard)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "Traceback" not in r.stdout + r.stderr and r.stdout.startswith("push isolation: cannot read ")
    assert names in r.stdout.splitlines()[0] and len(r.stdout.strip().splitlines()) == 1, r.stdout
    spec = importlib.util.spec_from_file_location("guard_copy", guard)
    spec.loader.exec_module(importlib.util.module_from_spec(spec))  # importing reads nothing, so it cannot fail


def test_cli_another_pilots_file_skips_a_broken_default(tmp_path):
    """--pilots=<a good file> runs with a broken default ha/pilots.json (it is never read); a bad --pilots file is
    exit 2 naming that file; a broken roles.py is exit 2 even with a good --pilots file."""
    guard = _tree(tmp_path, '{"admin": "ryan", "pilots": "james"}')
    good = tmp_path / "good.json"
    good.write_text(open(PILOTS_JSON, encoding="utf-8").read(), encoding="utf-8")
    r = _run(guard, f"--pilots={good}")
    assert r.returncode == 0 and r.stdout.startswith("push isolation OK:"), r.stdout + r.stderr
    assert _run(guard, f"--pilots={good}", _write(tmp_path, JAMES_TO_RYAN)).returncode == 1
    bad = tmp_path / "bad.json"
    bad.write_text('{"admin": "ryan"}', encoding="utf-8")
    r = _run(guard, f"--pilots={bad}")
    assert r.returncode == 2 and f"cannot read {bad}" in r.stdout and "Traceback" not in r.stderr, r.stdout
    r = _run(guard, f"--pilots={good}", str(tmp_path / "none.yaml"))  # a missing automations file: named as before
    assert r.returncode == 2 and f"cannot read {tmp_path / 'none.yaml'}" in r.stdout, r.stdout
    guard = _tree(tmp_path / "t2", None, "RESERVED = (\n")
    r = _run(guard, f"--pilots={good}")
    assert r.returncode == 2 and "roles.py" in r.stdout and "Traceback" not in r.stdout + r.stderr, r.stdout


@pytest.mark.parametrize("name", ["jane_", "a__b", "x_", "_x", "Jane", "a" * 33])
def test_guard_refuses_a_name_the_app_refuses(pilots, name):
    """Review fix (1.5.0): ha/pilots.json follows roles.NAME_RE (single underscores between words)."""
    with pytest.raises(ValueError, match="single underscores"):
        pilots([name])
    assert G.SECOND_PILOTS == ("james",)  # a refused file changes nothing


# Review fix (1.5.0): a pilot-triggered push may read only that pilot's data; a Ryan-triggered one no pilot's.
TRIGGERED_READS = """\
- id: '41'
  alias: Flight Watcher read test
  triggers:
  - topic: flight_watcher_james/event/new_pairing
    trigger: mqtt
  actions:
  - action: notify.mobile_app_james_phone
    data:
      message: '{{ states(''sensor.flight_watcher_jane_schedule'') }}'
  mode: queued
"""

TRIGGERED_CONDITION = """\
- id: '42'
  alias: Flight Watcher read test
  triggers:
  - trigger: state
    entity_id: sensor.flight_watcher_james_state
  conditions:
  - condition: state
    entity_id: sensor.flight_watcher_jane_state
    state: ok
  actions:
  - action: notify.mobile_app_james_phone
    data:
      message: down
  mode: single
"""

NEUTRAL_READS_JAMES_PUSHES_JANE = """\
- id: '43'
  alias: Flight Watcher read test
  triggers:
  - trigger: time
    at: '06:00:00'
  actions:
  - action: notify.mobile_app_jane_doe_phone
    data:
      message: '{{ states(''sensor.flight_watcher_james_schedule'') }}'
  mode: single
"""


@pytest.fixture
def james_and_jane(pilots):
    return pilots(["jane"], targets={"james": ["notify.mobile_app_james_phone"],
                                     "jane": ["notify.mobile_app_jane_doe_phone"]},
                  prefixes={"jane": ["JANERECALL_", "FLIGHT_WATCHER_JANE_"]})


@LOADERS
@pytest.mark.parametrize("text, why", [
    (TRIGGERED_READS, "triggered by james but reads ['jane']'s topics or entities and pushes"),
    (TRIGGERED_CONDITION, "triggered by james but reads ['jane']'s topics or entities and pushes"),
    (TRIGGERED_READS.replace("sensor.flight_watcher_jane_schedule", "sensor.flight_watcher_schedule"),
     "triggered by james but reads ['ryan']'s topics or entities and pushes"),
    (TRIGGERED_READS.replace("flight_watcher_james/event", "flight_watcher/event").replace(
        "notify.mobile_app_james_phone", "notify.mobile_app_ryans_iphone").replace(
        "sensor.flight_watcher_jane_schedule", "sensor.flight_watcher_james_schedule"),
     "triggered by Ryan but reads ['james']'s topics or entities and pushes"),
    (NEUTRAL_READS_JAMES_PUSHES_JANE, "pushes jane but reads ['james']'s topics or entities"),
], ids=["james-reads-jane-message", "james-condition-on-jane", "james-reads-ryan", "ryan-reads-james",
        "neutral-reads-james-pushes-jane"])
def test_a_push_reading_another_pilots_data_fails(tmp_path, use_yaml, james_and_jane, text, why):
    offenders, summary = G.check(G.load(_write(tmp_path, text), use_yaml=use_yaml))
    assert summary.startswith("push isolation FAILED:")
    assert [r for _, r in offenders] == [why], offenders


@LOADERS
def test_a_push_reading_only_its_own_pilot_passes(tmp_path, use_yaml, james_and_jane):
    own = TRIGGERED_READS.replace("sensor.flight_watcher_jane_schedule", "sensor.flight_watcher_james_schedule")
    assert G.check(G.load(_write(tmp_path, own), use_yaml=use_yaml))[0] == []
    cond = TRIGGERED_CONDITION.replace("sensor.flight_watcher_jane_state", "sensor.flight_watcher_james_last_check")
    assert G.check(G.load(_write(tmp_path, cond), use_yaml=use_yaml))[0] == []
    ryan = (TRIGGERED_READS.replace("flight_watcher_james/event", "flight_watcher/event")
            .replace("notify.mobile_app_james_phone", "notify.mobile_app_ryans_iphone")
            .replace("sensor.flight_watcher_jane_schedule", "sensor.flight_watcher_schedule"))
    assert G.check(G.load(_write(tmp_path, ryan), use_yaml=use_yaml))[0] == []
    # reading another pilot without pushing anyone is not a crossing
    quiet = TRIGGERED_CONDITION.replace(
        "  - action: notify.mobile_app_james_phone\n    data:\n      message: down\n",
        "  - action: input_boolean.turn_on\n    target:\n      entity_id: input_boolean.jane_doe_flag\n")
    assert quiet != TRIGGERED_CONDITION and G.check(G.load(_write(tmp_path, quiet), use_yaml=use_yaml))[0] == []
