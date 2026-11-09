"""1.6.0 (FW-0061): a portal pilot's events, results and list files (PORTAL_CONTRACT.md 4.3 to 4.5). A made-up name,
"Doe, Jane", is planted in every field of an event that may carry one (captain, detail_url, url, contact, picked_by,
detail) and must never reach events.json, results.json, the manifest or an ntfy push; nor may pay (value, pay) or the
commute reason (comm_why). state.json and files/ are the pilot's own dashboard data and keep crew names, employee
numbers, detail URLs, value and comm_why (contract 4.2, 4.5; test_state_and_files_are_the_pilots_own_dashboard_data):
only contact and the file keys are masked there. List files are read only when they are plain files. Synthetic data
only."""
import json
import os
import re
import sys

import pytest

import portal as PT
import roles

NAME = "Doe, Jane"
EMP = "10001"


def _env(W, name):
    with open(os.path.join(W.PORTAL_DIR, "out", name), encoding="utf-8") as f:
        return json.load(f)


def _payload(W, name, kind):
    key = PT.load_key(W.PORTAL_KEY_FILE, create=False)
    return json.loads(PT.verify(PT.public_id(key), _env(W, name), kind, W.INSTANCE))


def _all_out(W):
    """The payload of every data file under out/ (the card blobs are the cards' own JS from git, not data; the
    manifest's card hashes are hex)."""
    key = PT.public_id(PT.load_key(W.PORTAL_KEY_FILE, create=False))
    text = ""
    for dp, _, fs in os.walk(os.path.join(W.PORTAL_DIR, "out")):
        if os.path.basename(dp) == "blobs":
            continue
        for f in fs:
            name = os.path.relpath(os.path.join(dp, f), os.path.join(W.PORTAL_DIR, "out"))
            body = json.loads(PT.verify(key, json.load(open(os.path.join(dp, f), encoding="utf-8")), PT.kind_of(name)))
            if name == "manifest.json":
                body.pop("cards")
            text += json.dumps(body) + "\n"
    return text


def _leaks(text):
    """The planted values found in text (numbers as whole words only)."""
    found = [x for x in ("Doe", "Jane", "ha2.flica.net", "808-555", "4321.5", "$999", "delta", "home flight",
                         "token=abc", "N999ZZ", "was called first") if x in text]
    return found + [x for x in (EMP, "412") if re.search(r"\b%s\b" % x, text)]


PLANTED = {"captain": f"{NAME} ({EMP})", "detail_url": f"https://ha2.flica.net/x?name={NAME}",
           "url": "https://ha2.flica.net/full/otframe.cgi?token=abc", "contact": {"name": NAME, "phones": ["808-555-0100"]},
           "picked_by": f"FO {NAME} ({EMP})", "detail": f"Swap with {NAME} {EMP}", "value": 4321.5,
           "comm_why": "home flight HA 123 at 1800", "pay": {"delta": 999, "delta_text": "+$999"}}
EVENTS = [
    ("new_pairing", {"pairing": "H9001", "dates": "20NOV-22NOV", "start": "2026-11-20", "days": 3, "layover": "SYD",
                     "report": "0800", "credit": "15:20", "blk": "12:00", "fit": "Fits", "far": "OK", "comm": "Yes",
                     "month_rule": "line under 85 h", "month": "2026-11", **PLANTED}),
    ("rule_match", {"rule_id": "sin_alert", "rule": "SIN alert", "would_submit": False,
                    "row": {"pairing": "H9002", "dates": "24NOV", **PLANTED}}),
    ("recall_miss", {"id": "2026-11-03|H9003|recall", "verdict": "MISSED", "date": "2026-11-03", "pairing": "H9003",
                     "kind": "recall", "sen": 412, "why": f"{NAME} was called first"}),
    ("request_decided", {"type": "Swap", "status": "Approved", "bcid": "003.152", "at": "x", **PLANTED}),
    ("schedule_changed", {"month": "2026-11", "added": ["H9004 2026-11-12"], "removed": ["H9005 2026-11-14"],
                          "totals": {"credit": "80:00"}}),
    ("charter", {"key": "2026-11-30|HA9999", "date": "2026-11-30", "flight": "HA9999", "route": "HNL-PPT-HNL",
                 "eqpt": "A330", "tail": "N999ZZ", "why": "unusual"}),
    ("hidden", {"key": "2026-11|H9006", "pairing": "H9006", "dates": "26NOV-28NOV", "start": "2026-11-26",
                "credit": "14:00", "layover": "NRT", "vac": False, "blocked": False, "gone": "x", **PLANTED}),
]


def test_names_urls_contacts_pay_never_reach_out(portal_pilot):
    W, _ = portal_pilot("pilot2")
    W.portal_start(threads=False)
    for kind, p in EVENTS:
        W.pub(f"event/{kind}", p, retain=False)
    W.portal_export_once(full=True)
    assert _leaks(_all_out(W)) == [] and _leaks(json.dumps(W.EXPORT["events_list"])) == []
    assert _leaks(json.dumps(EVENTS)) != []  # the check itself finds them where they are
    evs = _payload(W, "events.json", "events")["events"]
    assert [e["kind"] for e in evs] == [k for k, _ in EVENTS]  # hidden included
    for e in evs:
        assert set(e) == {"seq", "ts", "kind", "id", "view", "priority", "title", "body", "data", "tags"}
        assert set(e["data"]) <= set(roles.EVENT_FIELDS) and e["view"] in roles.PORTAL_TABS
    np = evs[0]
    assert np["title"] == "New pairing H9001 20NOV-22NOV" and np["priority"] == 5
    assert np["data"]["block"] == "12:00" and np["data"]["comm"] == "Yes" and "value" not in np["data"]
    assert "comm_why" not in np["data"] and "captain" not in np["data"]
    assert evs[1]["data"]["pairing"] == "H9002" and evs[1]["data"]["rule_id"] == "sin_alert"
    assert evs[2]["view"] == "recall" and "PWA 22.G.2" in evs[2]["body"] and "sen" not in evs[2]["data"]
    assert evs[3]["title"] == "Request Approved Swap" and evs[3]["view"] == "schedule"
    assert "H9004 2026-11-12" in evs[4]["body"]
    assert evs[6]["title"].startswith("Hidden trip? H9006")


def test_admin_events_never_recorded(portal_pilot):
    W, _ = portal_pilot("", portal=True)
    W.pub("event/new_pairing", EVENTS[0][1], retain=False)
    assert W.EXPORT["events_list"] == [] and not os.path.exists(os.path.join(W.DATA, "portal_events.json"))


def test_priority_rule(portal_pilot):
    rec = PT.event_record
    assert rec("new_pairing", {"pairing": "H1", "fit": "Fits", "far": "OK (CBA rest 10:30)"}, 1, "t")["priority"] == 5
    for fit, far in (("Conflict H3659", "OK"), ("Fits", "Rest 8:00 before"), ("Fits", "?"), ("No sched", "OK"),
                     ("", "")):
        assert rec("new_pairing", {"pairing": "H1", "fit": fit, "far": far}, 1, "t")["priority"] == 3, (fit, far)
    assert rec("recall_miss", {"id": "x"}, 1, "t")["priority"] == 4
    assert rec("stopped_*", {"state": "stopped_unexpected"}, 1, "t")["priority"] == 4
    assert rec("needs_settings", {"state": "needs_settings"}, 1, "t")["priority"] == 3


@pytest.mark.parametrize("kind,base,field", [
    ("new_pairing", {"pairing": "H9001", "dates": "20NOV-22NOV", "fit": "Fits", "far": "OK", "month": "2026-11"},
     "seen"),
    ("rule_match", {"rule_id": "sin_alert", "rule": "SIN alert", "would_submit": False,
                    "row": {"pairing": "H9002", "dates": "24NOV"}}, "at"),
    ("schedule_changed", {"month": "2026-11", "added": ["H9004 2026-11-12"], "removed": []}, "updated"),
])
def test_event_id_is_one_occurrence_not_one_pairing(kind, base, field):
    """A pot pairing that is picked up and dropped back (a new 'seen'), a rule matching again later (a new 'at') or a
    second schedule change with the same lines (a new 'updated') is a new event with a new id, so it is pushed and
    listed again; a replay of the same publish keeps its id (dedupe). The time itself is never in data."""
    rec = PT.event_record
    first = rec(kind, {**base, field: "2026-11-09T10:00:00+00:00"}, 1, "t")
    again = rec(kind, {**base, field: "2026-11-09T10:00:00+00:00"}, 2, "t")
    later = rec(kind, {**base, field: "2026-11-09T13:00:00+00:00"}, 3, "t")
    assert first["id"] == again["id"] and first["id"] != later["id"]
    assert first["data"] == later["data"] and field not in first["data"]
    assert rec(kind, base, 4, "t")["id"] == rec(kind, dict(base), 5, "t")["id"]  # no time: data alone, as before


def test_machine_events_once_per_state(portal_pilot):
    W, _ = portal_pilot("pilot2")
    W.portal_start(threads=False)
    W.set_machine("needs_settings", "send username and password")
    W.set_machine("needs_settings", "still")  # the same state again: no second event
    W.set_machine("idle", "starting")
    W.set_machine("stopped_login_failed", "one login attempt failed (re-arm)")
    W.set_machine("stopped_login_failed", "one login attempt failed (re-arm) (still stopped after restart)")
    W.set_machine("stopped_unexpected", f"3 check errors in a row: {NAME}")
    kinds = [(e["kind"], e["data"].get("state")) for e in W.EXPORT["events_list"]]
    assert kinds == [("needs_settings", "needs_settings"), ("stopped_*", "stopped_login_failed"),
                     ("stopped_*", "stopped_unexpected")]
    assert NAME not in json.dumps(W.EXPORT["events_list"])  # the note is never copied
    assert "password on the Settings tab" in W.EXPORT["events_list"][1]["body"]


def test_seq_and_events_survive_a_restart(portal_pilot):
    W, _ = portal_pilot("pilot2")
    W.portal_start(threads=False)
    W.pub("event/charter", EVENTS[5][1], retain=False)
    first = W.EXPORT["events_list"][-1]["seq"]
    sys.modules.pop("watcher", None)
    W, _ = portal_pilot("pilot2")  # a restart: same /data
    W.portal_start(threads=False)
    assert [e["seq"] for e in W.EXPORT["events_list"]] == [first]
    W.pub("event/hidden", EVENTS[6][1], retain=False)
    assert W.EXPORT["events_list"][-1]["seq"] > first
    W.portal_export_once(full=True)
    assert [e["kind"] for e in _payload(W, "events.json", "events")["events"]] == ["charter", "hidden"]


def test_last_100_events_and_50_results(portal_pilot):
    W, _ = portal_pilot("pilot2")
    W.portal_start(threads=False)
    for i in range(105):
        W.portal_event("charter", {"key": f"k{i}", "flight": f"HA{i}"})
    for i in range(55):
        W.portal_result("%016x" % i, i % 2 == 0, "" if i % 2 == 0 else "sub not allowed: drop/set")
    W.portal_export_once(full=True)
    evs = _payload(W, "events.json", "events")["events"]
    assert len(evs) == 100 and evs[0]["data"]["flight"] == "HA5"
    seqs = [e["seq"] for e in evs]
    assert seqs == sorted(seqs) and len(set(seqs)) == 100
    res = _payload(W, "results.json", "results")["results"]
    assert len(res) == 50 and res[-1] == {"id": "%016x" % 54, "ok": True, "why": ""}
    assert set(res[0]) == {"id", "ok", "why"}


# ---------------------------------------------------------------- list files (4.5)
def test_list_files_copied_exactly_and_without_keys(portal_pilot, monkeypatch):
    W, _ = portal_pilot("pilot2")
    W.portal_start(threads=False)
    key = W.www_key()
    fdir = W.finds_dir()
    os.makedirs(fdir, exist_ok=True)
    month = W.local_now().strftime("%Y-%m")
    W.DB.finds_between = lambda a, b: [{"pairing": "H9001", "captain": "Doe, Jane (10001)"}] if a.startswith(month) else []
    W.write_finds_months()
    W.write_list_file("pickers", {"count": 1, "pickers": [{"emp": "10001", "name": NAME}]})
    W.write_list_file("versions", {"months": {}})
    W.write_list_file("tickets", {"tickets": [{"id": "FW-0001"}]})  # not in contract 1
    open(os.path.join(fdir, "school_2026-27.json"), "w").write('{"days": []}')
    open(os.path.join(W.CARD_PAIRINGS, f"pairings_{month}.json"), "w").write('{"cols": [], "rows": []}')
    open(os.path.join(W.CARD_PAIRINGS, "pairings_2001-01.json"), "w").write('{"cols": [], "rows": []}')  # too old
    assert W.EXPORT["files"]  # the writes marked the files
    W.portal_export_once(full=True)
    out = os.path.join(W.PORTAL_DIR, "out", "files")
    names = sorted(os.listdir(out))
    assert names == sorted([f"finds_{month}.json", "pickers.json", "versions.json", "school_2026-27.json",
                            f"pairings_{month}.json"])
    assert not [n for n in names if key in n]
    src = open(os.path.join(fdir, W.WF.list_name("pickers", key)), encoding="utf-8").read()
    assert PT.verify(PT.public_id(PT.load_key(W.PORTAL_KEY_FILE)), _env(W, "files/pickers.json"),
                     "file:pickers", "pilot2") == src  # the file exactly as the card fetches it
    man = _payload(W, "manifest.json", "manifest")
    assert man["files"] == sorted([f"finds:{month}", "pickers", "versions", "school:2026-27", f"pairings:{month}"])
    # a file that goes away leaves out/files and the manifest
    os.remove(os.path.join(fdir, "school_2026-27.json"))
    W.portal_export_once(full=True)
    assert "school_2026-27.json" not in os.listdir(out) and "school:2026-27" not in _payload(
        W, "manifest.json", "manifest")["files"]
    # nothing changed: nothing rewritten
    before = _env(W, "files/pickers.json")["seq"]
    W.portal_export_once(full=True)
    assert _env(W, "files/pickers.json")["seq"] == before


def test_admin_list_writes_touch_no_portal(portal_pilot):
    W, _ = portal_pilot("", portal=True)
    W.write_list_file("pickers", {"count": 0, "pickers": []})
    assert W.EXPORT["files"] is True and W.EXPORT["writer"] is None  # untouched defaults: no export exists
    assert not os.path.exists(os.path.join(os.path.dirname(W.DATA), "share", "fw_portal"))


def test_a_portal_failure_never_stops_the_watcher(portal_pilot, monkeypatch):
    W, _ = portal_pilot("pilot2")
    W.portal_start(threads=False)

    def boom(kind):
        raise OSError("disk full")
    monkeypatch.setattr(W.EXPORT["seq"], "next", boom)
    W.set_machine("stopped_unexpected", "x")  # no exception reaches the caller
    W.pub("event/new_pairing", {"pairing": "H9001"}, retain=False)
    assert W.S["machine"] == "stopped_unexpected" and W.EXPORT["events_list"] == []
    monkeypatch.setattr(W, "_prefs_save", lambda d: boom(None))
    assert W.pref_cmd('{"key": "federal_tax_pct", "value": 20}') is False


# ---------------------------------------------------------------- list files: only plain files are read (4.5)
def _files_setup(W):
    W.portal_start(threads=False)
    fdir = W.finds_dir()
    os.makedirs(fdir, exist_ok=True)
    month = W.local_now().strftime("%Y-%m")
    W.write_list_file("versions", {"months": {}})  # a good file in the same pass
    return fdir, month


def _out_files(W):
    return sorted(os.listdir(os.path.join(W.PORTAL_DIR, "out", "files")))


def test_a_symlinked_list_file_never_exports_a_container_file(portal_pilot, caplog):
    """Another app that can write HA's config folder plants school_ / pairings_ names that point at this container's
    /data (options.json with the FLICA password, the signing key): the export reads only plain files."""
    import logging
    W, _ = portal_pilot("pilot2")
    fdir, month = _files_setup(W)
    os.symlink(os.path.join(W.DATA, "options.json"), os.path.join(fdir, "school_2026-27.json"))
    os.symlink(W.PORTAL_KEY_FILE, os.path.join(W.CARD_PAIRINGS, f"pairings_{month}.json"))
    os.symlink("/dev/zero", os.path.join(fdir, "school_2027-28.json"))
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        W.portal_export_once(full=True)
        W.portal_export_once(full=True)
    assert _out_files(W) == ["versions.json"]  # the good file still goes
    assert _payload(W, "manifest.json", "manifest")["files"] == ["versions"]
    text = _all_out(W)
    assert "BEGIN PRIVATE KEY" not in text and "category_check" not in text  # neither the key nor options.json
    for kind in ("school:2026-27", f"pairings:{month}", "school:2027-28"):
        assert caplog.text.count(f"portal file file:{kind} skipped") == 1, kind  # once, not every pass


def test_a_fifo_never_blocks_the_export(portal_pilot):
    import threading
    W, _ = portal_pilot("pilot2")
    fdir, month = _files_setup(W)
    os.mkfifo(os.path.join(fdir, "school_2026-27.json"))
    os.mkfifo(os.path.join(W.CARD_PAIRINGS, f"pairings_{month}.json"))
    t = threading.Thread(target=W.portal_export_once, kwargs={"full": True}, daemon=True)
    t.start()
    t.join(5)
    assert not t.is_alive()  # an open() of a FIFO would wait for a writer for good
    assert _out_files(W) == ["versions.json"]


def test_a_symlinked_list_folder_is_skipped(portal_pilot, tmp_path):
    W, _ = portal_pilot("pilot2")
    W.portal_start(threads=False)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "school_2026-27.json").write_text('{"days": []}')
    os.makedirs(W.CARD_PAIRINGS, exist_ok=True)
    os.symlink(str(elsewhere), W.finds_dir())  # www/flight-watcher/pilot2 -> somewhere else
    month = W.local_now().strftime("%Y-%m")
    open(os.path.join(W.CARD_PAIRINGS, f"pairings_{month}.json"), "w").write('{"cols": [], "rows": []}')
    W.portal_export_once(full=True)
    assert _out_files(W) == [f"pairings_{month}.json"]  # the shared folder is real: its package still goes


def test_state_and_files_are_the_pilots_own_dashboard_data(portal_pilot):
    """Contract 4.2 / 4.5 (a decision, like plan Q6): state.json and files/ are the pilot's own dashboard data, so the
    finds card's captain and picked_by, the pickers card's names and employee numbers, the finds files' detail_url
    and the FW-0042 value and comm_why stay in them (masking them would empty those cards); only contact and the file
    keys are masked. events.json, results.json and the manifest never carry any of it (4.3, plan risk K1)."""
    from conftest import ha_state
    find = {"pairing": "H9001", "captain": f"{NAME} ({EMP})", "picked_by": f"FO {NAME} ({EMP})", "value": 4321.5,
            "comm_why": "home flight HA 123 at 1800", "contact": {"name": NAME, "phones": ["808-555-0100"]}}
    W, _ = portal_pilot("pilot2", states={"sensor.flight_watcher_pilot2_finds": ha_state(
        "sensor.flight_watcher_pilot2_finds", "1", {"count": 1, "finds": [find], "file_key": "ab" * 16})})
    W.portal_start(threads=False)
    os.makedirs(W.finds_dir(), exist_ok=True)
    W.write_list_file("pickers", {"count": 1, "pickers": [{"emp": EMP, "name": NAME}]})
    for kind, p in EVENTS:
        W.pub(f"event/{kind}", p, retain=False)
    W.portal_result("0123456789abcdef", True, "")
    W.portal_export_once(full=True)
    for name, kind in (("events.json", "events"), ("results.json", "results")):
        assert _leaks(json.dumps(_payload(W, name, kind))) == [], name
    man = _payload(W, "manifest.json", "manifest")
    man.pop("cards")
    assert _leaks(json.dumps(man)) == []
    st = _payload(W, "state.json", "state")["states"]["sensor.flight_watcher_pilot2_finds"]["attributes"]
    assert st["finds"][0]["captain"] == f"{NAME} ({EMP})" and st["finds"][0]["value"] == 4321.5
    assert "contact" not in st["finds"][0] and st["file_key"] == "0" * 32 and "808-555" not in json.dumps(st)
    assert NAME in _payload(W, "files/pickers.json", "file:pickers")["pickers"][0]["name"]
