"""1.5.0 (FW-0063, plan risk K8): the dashboards on Pako (redacted snapshots in ha/) read only entities the Watcher's
discovery creates for that dashboard's instance, so a role gate that retires an entity fails here before it blanks a
card on Pako. HA helpers (input_*), automations, the add-on's update entity and the utility meters HA builds from
sensor.<prefix>_flica_fetches are not the Watcher's and are left out."""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HA = os.path.join(os.path.dirname(HERE), "ha")
DISCOVERY_DOMAINS = ("sensor", "switch", "button", "number", "select", "binary_sensor")
NOT_THE_WATCHERS = re.compile(r"^sensor\.flight_watcher_(?:[a-z0-9]+_)?flica_refreshes_")  # HA utility meters


def _made(tmp_path, monkeypatch, instance):
    data = tmp_path / (instance or "ryan")
    data.mkdir()
    (data / "options.json").write_text(json.dumps({"username": "u", "password": "p", "log_level": "info"}))
    monkeypatch.setenv("FLIGHT_WATCHER_DATA", str(data))
    if instance:
        monkeypatch.setenv("FLIGHT_WATCHER_PREFIX", f"flight_watcher_{instance}")
        monkeypatch.setenv("FLIGHT_WATCHER_INSTANCE", instance)
    else:
        monkeypatch.delenv("FLIGHT_WATCHER_PREFIX", raising=False)
        monkeypatch.delenv("FLIGHT_WATCHER_INSTANCE", raising=False)
    monkeypatch.delenv("FLIGHT_WATCHER_OPTIONS", raising=False)
    sys.modules.pop("watcher", None)
    import watcher as W

    class C:
        msgs = []

        def publish(self, topic, payload="", retain=False):
            self.msgs.append((topic, payload))
    c = C()
    W.discovery(c)
    sys.modules.pop("watcher", None)
    return {json.loads(p)["default_entity_id"] for t, p in c.msgs if p}


def _used(name, prefix, others=()):
    text = open(os.path.join(HA, name), encoding="utf-8").read()
    ids = set(re.findall(r"\b(?:%s)\.%s_[a-z0-9_]+" % ("|".join(DISCOVERY_DOMAINS), prefix), text))
    return {e for e in ids if not NOT_THE_WATCHERS.match(e) and not any(f"{prefix}_{o}_" in e for o in others)}


def test_a_pilot_instance_skips_the_admin_only_entities(tmp_path, monkeypatch):
    """James's HA dashboard was retired on 2026-11-10 (he uses the pilot portal, FW-0061), so there is no pilot
    dashboard snapshot left; the role gate on a pilot instance's discovery still holds."""
    made = _made(tmp_path, monkeypatch, "james")
    # the three entities 1.5.0 retires on a pilot (swap ideas and the charter button are core)
    for gone in ("switch.flight_watcher_james_auto_swap_dry_run", "button.flight_watcher_james_map_swap_pages_read_only",
                 "sensor.flight_watcher_james_would_drop"):
        assert gone not in made
    assert {"sensor.flight_watcher_james_swap_ideas", "button.flight_watcher_james_scan_crewtrac_charters_now"} <= made


def test_ryans_dashboard_reads_only_what_the_admin_creates(tmp_path, monkeypatch):
    made = _made(tmp_path, monkeypatch, "")
    pilots = json.load(open(os.path.join(HA, "pilots.json"), encoding="utf-8"))["pilots"]
    used = _used("dashboard_flight_watcher.json", "flight_watcher", pilots)
    assert used and used - made == set(), sorted(used - made)

