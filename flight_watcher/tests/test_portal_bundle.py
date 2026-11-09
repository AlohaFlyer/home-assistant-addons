"""1.6.0 (FW-0061): a portal pilot's card bundle and manifest (PORTAL_CONTRACT.md 4.1): the manifest verifies; every
layout card is a bundled card or a plain type; every entity the layout or a bundled card reads is exported (or local,
or an admin-only entity a pilot never has); every callService in the bundled cards maps to the manifest's services or
mqtt_subs; blobs are content-addressed and swept. Synthetic data only."""
import hashlib
import json
import os
import re

import pytest

import portal as PT
import roles

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = "flight_watcher_pilot2"
PLAIN = {"heading", "tile", "entity", "toggle", "markdown"}


@pytest.fixture
def pilot(portal_pilot):
    W, _ = portal_pilot("pilot2")
    W.portal_start(threads=False)
    W.portal_export_once(full=True)
    return W


def _manifest(W):
    key = PT.public_id(PT.load_key(W.PORTAL_KEY_FILE, create=False))
    env = json.load(open(os.path.join(W.PORTAL_DIR, "out", "manifest.json"), encoding="utf-8"))
    return json.loads(PT.verify(key, env, "manifest", "pilot2")), env


def _cards(layout):
    return [c for t in layout["tabs"] for c in t["cards"]]


def test_manifest_verifies_and_names_the_pilot(pilot):
    W = pilot
    m, env = _manifest(W)
    assert env["kind"] == "manifest" and env["pilot"] == "pilot2"
    assert {k: m[k] for k in ("contract", "app_version", "pilot", "prefix", "role", "ntfy")} == {
        "contract": 1, "app_version": W.VERSION, "pilot": "pilot2", "prefix": P, "role": "pilot", "ntfy": False}
    assert set(m) == {"contract", "app_version", "pilot", "prefix", "role", "cards", "layout", "services", "mqtt_subs",
                      "files", "ntfy"}
    assert [t["id"] for t in m["layout"]["tabs"]] == list(roles.PORTAL_TABS)
    assert m["mqtt_subs"] == ["blocked/set", "improved/set", "pilot/set", "recall/act", "recall/set", "settings/set",
                              "trade/set"]
    assert set(m["mqtt_subs"]) <= set(roles.PORTAL_CMDS)


def built_settings(W, m):
    sha = m["cards"]["flight-watcher-settings-card-pilot2.js"]
    return open(os.path.join(W.PORTAL_DIR, "out", "blobs", f"{sha}.js"), encoding="utf-8").read()


def test_blobs_are_the_pilot_card_copies_by_hash(pilot):
    W = pilot
    m, _ = _manifest(W)
    import cards
    built = cards.build(W.VERSION, ["pilot2"])
    assert sorted(m["cards"]) == sorted(f"flight-watcher-{b}-pilot2.js" for b in (
        "clock-card", "finds-card", "improved-card", "pickers-card", "pilot-card", "pilot-search-card", "recall-card",
        "schedule-card", "settings-card"))  # no tickets, uploads or row colors card
    for fn, sha in m["cards"].items():
        raw = open(os.path.join(W.PORTAL_DIR, "out", "blobs", f"{sha}.js"), "rb").read()
        assert hashlib.sha256(raw).hexdigest() == sha and raw.decode() == PT.portal_card(built[fn])
        assert "const FW_PORTAL = false;" not in raw.decode()  # the settings card: sealed or nothing in a portal
        assert '"flight_watcher/' not in raw.decode() and ".flight_watcher_" + "state" not in raw.decode()
    assert PT.PORTAL_CARD_FLAG[1] in built_settings(W, m)
    assert PT.PORTAL_CARD_FLAG[0] in built["flight-watcher-settings-card-pilot2.js"]  # as deployed: unchanged
    assert all(PT.PORTAL_CARD_FLAG[1] not in t for t in built.values())


def test_every_layout_card_is_bundled_or_plain(pilot):
    W = pilot
    m, _ = _manifest(W)
    ids, local = set(W.portal_ids()), {s["entity"].format(prefix=P) for s in roles.LOCAL_HELPERS.values()}
    for c in _cards(m["layout"]):
        t = c["type"]
        if t.startswith("custom:"):
            assert f"{t[7:]}.js" in m["cards"], t
        else:
            assert t in PLAIN, t
        if t == "markdown":
            assert "{{" not in c["content"] and "{%" not in c["content"]  # static text only
        if "entity" in c:
            assert c["entity"] in ids | local, c["entity"]
    text = open(os.path.join(HERE, "portal_layout.json"), encoding="utf-8").read()
    assert chr(0x2014) not in text and "flight_watcher_{name}_" in text
    assert "tickets-card" not in text and "uploads-card" not in text


def _admin_only(W):
    """The discovery ids a pilot never has (its role lacks their feature)."""
    return {cfg["default_entity_id"] for _, _, cfg, f in W.entity_defs() if not W.has(f)}


def test_every_entity_a_bundled_card_reads_is_exported(pilot):
    W = pilot
    ok = set(W.portal_ids()) | {s["entity"].format(prefix=P) for s in roles.LOCAL_HELPERS.values()}
    missing = set()
    for fn, text in W.portal_cards().items():
        for eid in re.findall(r"\b[a-z_]+\.%s_[a-z0-9_]+" % P, text):
            if eid not in ok:
                missing.add(eid)
    assert missing <= _admin_only(W), sorted(missing - _admin_only(W))
    assert missing == {f"sensor.{P}_would_drop"}  # the schedule card's admin-only drop marks, never drawn for a pilot


def test_every_call_service_maps_to_the_manifest(pilot):
    W = pilot
    m, _ = _manifest(W)
    sv, subs = m["services"], set(m["mqtt_subs"])
    seen = 0
    for fn, text in W.portal_cards().items():
        calls = list(re.finditer(r'callService\("([a-z_]+)", ("[a-z_]+"|[^,]+), (\{[^}]*\}|[a-z_]+)', text))
        assert len(calls) == text.count("callService("), fn  # every call site is classified below
        for call in calls:
            dom, svc, data = call.group(1), call.group(2).strip('"'), call.group(3)
            seen += 1
            if dom == "mqtt":
                lit = re.search(r'topic: "%s/([a-z_/]+)"' % P, data)
                if lit:
                    assert lit.group(1) in subs or lit.group(1) == "drop/set", (fn, lit.group(1))
                    if lit.group(1) == "drop/set":
                        assert "schedule-card" in fn  # drawn only for the admin's role (_isAdmin), refused anyway
                elif "this._c.topic" in data:
                    assert "settings-card" in fn and "settings/set" in subs
                elif "`%s/${topic" % P in data:  # the recall card's _send(topic, ...)
                    sends = set(re.findall(r'_send\("([a-z_/]+)"', text))
                    assert sends and sends <= subs, sends
                else:
                    pytest.fail(f"unmapped mqtt publish in {fn}: {data}")
                continue
            if "inp.dataset.e" in data:
                ids = re.findall(r'data-e="([a-z_.0-9]+)"', text)
            elif data == "ent" or "...ent" in data:
                ids = re.findall(r'ent = \{ entity_id: "([a-z_.0-9]+)" \}', text)
            else:
                ids = re.findall(r'entity_id: "([a-z_.0-9]+)"', data)
            assert ids, (fn, call.group(0))
            want = {"increment", "decrement"} if svc.startswith("d > 0") else {svc}
            for eid in ids:
                assert want <= set(sv.get(eid, {})), (fn, eid, want)
    assert seen >= 15


def test_services_only_use_allowed_subs(pilot):
    W = pilot
    m, _ = _manifest(W)
    for eid, how in m["services"].items():
        assert eid.split(".", 1)[1].startswith(P + "_"), eid
        for svc, spec in how.items():
            if spec.get("local"):
                assert eid in {s["entity"].format(prefix=P) for s in roles.LOCAL_HELPERS.values()}
                continue
            assert roles.portal_sub(spec["sub"]), (eid, spec)
            if spec["sub"] == "pref/set":
                assert spec["key"] in roles.PREF_KEYS and roles.pref_entity(spec["key"], P) == eid
    assert m["services"][f"switch.{P}_pause"]["toggle"] == {"sub": "pause/set", "on": "ON", "off": "OFF"}
    assert m["services"][f"button.{P}_re_arm"] == {"press": {"sub": "rearm/press", "payload": "PRESS"}}
    assert m["services"][f"number.{P}_hunt_check_every"] == {"set_value": {"sub": "freq/hunt_s/set"}}
    assert m["services"][f"input_text.{P}_er_trips"] == {"set_value": {"sub": "pref/set", "key": "er_trips"}}


def test_a_new_rule_rewrites_the_manifest(pilot):
    W = pilot
    before = _manifest(W)[1]["seq"]
    W.RULES["list"] = [{"id": "sin_alert", "name": "SIN", "enabled": True, "mode": "alert",
                        "created_at": "2026-11-01T00:00:00+00:00"}]
    W.publish_rules(W.MQ)
    W.portal_export_once()
    m, env = _manifest(W)
    assert env["seq"] > before
    assert m["services"][f"switch.{P}_rule_sin_alert_live"]["turn_on"] == {"sub": "rule/sin_alert/live/set",
                                                                            "payload": "ON"}
    W.portal_export_once(full=True)
    assert _manifest(W)[1]["seq"] == env["seq"]  # unchanged: not rewritten


def test_stale_blobs_swept_an_hour_after_they_leave_the_manifest(pilot):
    W = pilot
    d = os.path.join(W.PORTAL_DIR, "out", "blobs")
    old = os.path.join(d, "0" * 64 + ".js")
    open(old, "w").write("// a card from an older version")
    os.utime(old, (0, 0))  # its file time says nothing: the hour runs from the sweep that first finds it unlisted
    now = W.time.time()
    W.portal_export_once(full=True, now=now)
    assert os.path.exists(old)
    W.portal_export_once(full=True, now=now + PT.BLOB_KEEP_S - 1)
    assert os.path.exists(old)
    W.portal_export_once(full=True, now=now + PT.BLOB_KEEP_S)
    m, _ = _manifest(W)
    assert not os.path.exists(old) and sorted(os.listdir(d)) == sorted(f"{s}.js" for s in m["cards"].values())


def test_a_release_that_changes_a_card_keeps_the_old_blob_an_hour(portal_pilot):
    """A portal that read the previous manifest just before the restart's first full pass can still fetch the old
    card by its hash for an hour, though the blob file was written days ago."""
    W, _ = portal_pilot("pilot2")
    W.portal_start(threads=False)
    W.portal_export_once(full=True)
    before, _ = _manifest(W)
    d = os.path.join(W.PORTAL_DIR, "out", "blobs")
    days_ago = W.time.time() - 2 * 86400
    for n in os.listdir(d):
        os.utime(os.path.join(d, n), (days_ago, days_ago))
    import sys
    sys.modules.pop("watcher", None)
    W, _ = portal_pilot("pilot2")  # the restart after an update that changed one card
    W.portal_start(threads=False)
    fn = sorted(W.portal_cards())[0]
    W.EXPORT["cards"][fn] += "\n// changed in a release\n"
    now = W.time.time()
    W.portal_export_once(now=now)  # the first pass after a start is a full one (blob sweep included)
    after, _ = _manifest(W)
    old_sha, new_sha = before["cards"][fn], after["cards"][fn]
    assert old_sha != new_sha and os.path.exists(os.path.join(d, new_sha + ".js"))
    assert os.path.exists(os.path.join(d, old_sha + ".js"))  # still served to a reader of the previous manifest
    W.portal_export_once(full=True, now=now + PT.BLOB_KEEP_S)
    assert not os.path.exists(os.path.join(d, old_sha + ".js")) and os.path.exists(os.path.join(d, new_sha + ".js"))
    assert sorted(os.listdir(d)) == sorted(f"{s}.js" for s in after["cards"].values())


def test_dockerfile_ships_the_portal():
    lines = open(os.path.join(HERE, "Dockerfile"), encoding="utf-8").read().splitlines()
    copy = next(ln for ln in lines if ln.startswith("COPY run.py"))
    assert "portal.py" in copy.split() and "ntfy.py" in copy.split()
    assert "COPY portal_layout.json /app/" in lines
