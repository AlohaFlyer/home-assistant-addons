"""1.7.1: the Watcher core fixes. F#15 a pilot gets no example rule (and an untouched seeded one leaves once), F#12 /
F#92 / F#149 a Check now or a Re-arm the Watcher would ignore answers the portal ok false with the reason, Re-arm while
'Stuck' runs a full check and never cuts a step-aside short, F#75 the admin forwards each recall list to every pilot
and a duplicate changes nothing, F#102 a pilot with only CrewTrac details gets the charter watch, F#155 the sealed
Remove CrewTrac login, F#77 the Watcher answers a Recall/O75 Refresh. Synthetic data only ("Doe, Jane" 10001); FLICA
and CrewTrac are never reached."""
import json
import logging
import os
import threading
import time
import types

import pytest

import rules as R
import sealed as SEAL
from test_portal_spool import _put, demo  # noqa: F401
from test_release_a_flica import mk  # noqa: F401
from test_release_a_review import Stop, _run_main

ROW = {"date": "2026-11-10", "kind": "recall", "seat": "FO", "pilot": "Doe, Jane", "sen": 900, "pairing": "H9001"}


# ------------------------------------------------------------------ F#15: no example rule on a pilot
def test_a_pilot_gets_no_example_rule_and_the_admin_keeps_his(mk, caplog):
    W = mk("pilot2")
    assert not os.path.exists(W.RULES_FILE)
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        assert W.load_rules() == []
    assert json.load(open(W.RULES_FILE)) == [] and "a pilot gets no example rule" in caplog.text
    A = mk("")
    assert [r["id"] for r in A.load_rules()] == ["sin_hunt"]  # the admin: as before
    assert [r["id"] for r in A.load_rules()] == ["sin_hunt"]  # and it stays (never removed on the admin)


def test_an_untouched_seeded_example_leaves_a_pilot_once(mk, caplog):
    W = mk("pilot2")
    seeded = R.validate(R.EXAMPLE)[0][0]  # as a 1.7.0 start wrote it, created_at stamped then
    seeded["created_at"] = "2026-11-10T11:01:00+00:00"
    mine = {**R.validate([{"id": "lax_turn", "name": "LAX", "match": {"layover": ["LAX"]}}])[0][0]}
    json.dump([seeded, mine], open(W.RULES_FILE, "w"))
    W.DB.set_live("sin_hunt", False)
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        W.RULES["list"] = W.load_rules()
    assert [r["id"] for r in W.RULES["list"]] == ["lax_turn"]
    assert [r["id"] for r in json.load(open(W.RULES_FILE))] == ["lax_turn"]
    assert "the example rule sin_hunt seeded before 1.7.1 removed" in caplog.text
    W.publish_rules(W.MQ)  # its live switch comes down from Home Assistant (and so from the portal)
    assert (f"homeassistant/switch/{W.T}/rule_sin_hunt_live/config", "") in W.MQ.msgs
    rules = json.loads([p for t, p in W.MQ.msgs if t == f"{W.T}/rules/state"][-1])
    assert rules["count"] == 1 and [r["id"] for r in rules["rules"]] == ["lax_turn"]
    json.dump([seeded], open(W.RULES_FILE, "w"))  # once only: the same rule written again later is his
    assert [r["id"] for r in W.load_rules()] == ["sin_hunt"]


@pytest.mark.parametrize("edit", [{"dry_run": False}, {"match": {"layover": ["SIN", "NRT"], "months": ["current"]}},
                                  {"enabled": False}, {"notify": "normal"}])
def test_an_edited_example_is_his_and_stays(mk, edit):
    W = mk("pilot2")
    rule = {**R.validate(R.EXAMPLE)[0][0], **edit}
    json.dump([rule], open(W.RULES_FILE, "w"))
    assert [r["id"] for r in W.load_rules()] == ["sin_hunt"]
    assert W.is_seeded_example(R.validate(R.EXAMPLE)[0][0]) and not W.is_seeded_example(rule)


# ------------------------------------------------------------------ F#12, F#92, F#149: presses the Watcher ignores
TEMPLATE = {"fwp": 1, "pilot": "demo", "ts": 1763600000004, "payload": "PRESS", "session": "5e55105e55105e55"}


def _press(W, sub, n, payload="PRESS"):
    cid = f"00000000c0de{0x100 + n:04x}"
    cmd = {**TEMPLATE, "id": cid, "sub": sub, "payload": payload}
    _put(W, f"{cmd['ts']}-{cid}.json", cmd)
    W.MQ.raw.msgs.clear()
    W.portal_spool_once()
    res = {r["id"]: r for r in W.EXPORT["results_list"]}[cid]
    sent = [t for t, *_ in W.MQ.raw.msgs if t == f"{W.T}/{sub}"]
    return res, sent


def _gate_full(W, n):
    """n loads of this pilot in the last hour on the host's gate file (none: an empty log)."""
    now = time.time()
    log = [[now - 3000 + i, W.INSTANCE] for i in range(n)]
    open(W.GATE_FILE, "w").write(json.dumps({"v": 1, "last": log[-1][0] if log else 0, "log": log}))


def test_an_ignored_check_now_answers_ok_false_with_the_reason(demo):
    W = demo
    W.S.update(machine="hunting", last_check_ts=time.time() - 60)
    W.FLAGS["hunt"] = True
    cases = [
        ({"pause": True}, {}, "ignored: the Watcher is paused (turn Pause off first)"),
        ({}, {"machine": "stopped_unexpected"}, "ignored: the Watcher is stopped (see why on the Watcher tab, then Re-arm)"),
        ({}, {"machine": "needs_settings"}, "ignored: the Watcher waits for your FLICA login on the Settings tab"),
        ({}, {"machine": "yielded", "yield_until": time.time() + 900},
         f"ignored: the Watcher stepped aside for your own FLICA login until {W.hst_hm(time.time() + 900)} HST"),
        ({}, {"machine": "backoff", "relogin_at": time.time() + 300},
         f"ignored: the Watcher logs in again at {W.hst_hm(time.time() + 300)} HST"),
        ({}, {"last_check_ts": time.time() - 4}, "ignored: last check under 10 s ago"),
    ]
    for i, (flags, state, why) in enumerate(cases):
        W.FLAGS["pause"] = False
        W.S.update(machine="hunting", last_check_ts=time.time() - 60, wake_ts=0, check_started_ts=0)
        W.FLAGS.update(flags)
        W.S.update(state)
        res, sent = _press(W, "check_now/press", i)
        assert res == {"id": res["id"], "ok": False, "why": why} and sent == [], (state, res)
    W.FLAGS["pause"] = False
    W.S.update(machine="hunting", last_check_ts=time.time() - 60, wake_ts=0, check_started_ts=0)
    _gate_full(W, 99)  # his budget: 99 of 100 loads in the last hour, the next check waits
    res, sent = _press(W, "check_now/press", 20)
    assert not res["ok"] and res["why"].startswith("ignored: the FLICA budget holds the next check until ") and not sent
    _gate_full(W, 0)
    res, sent = _press(W, "check_now/press", 21)
    assert res["ok"] and res["why"] == "" and sent == [f"{W.T}/check_now/press"]  # taken: republished as before


def test_rearm_says_what_it_does_by_state(demo):
    W = demo
    W.FLAGS["hunt"] = True
    W.S.update(machine="hunting", last_check_ts=time.time() - 60)
    res, sent = _press(W, "rearm/press", 1)  # checking normally: nothing to re-arm
    assert not res["ok"] and res["why"] == f"nothing to re-arm: the Watcher is checking (last check " \
        f"{W.hst_hm(W.S['last_check_ts'])} HST)" and not sent
    W.FLAGS["pause"] = True
    res, sent = _press(W, "rearm/press", 2)
    assert not res["ok"] and res["why"] == "nothing to re-arm while paused: turn Pause off" and not sent
    W.FLAGS["pause"] = False
    W.S["machine"] = "needs_settings"
    assert _press(W, "rearm/press", 3)[0]["why"] == "nothing to re-arm: enter your FLICA login on the Settings tab"
    W.S.update(machine="hunting", last_check_ts=time.time() - 11 * 60)  # 'Stuck. No check for 11 min. Press Re-arm.'
    res, sent = _press(W, "rearm/press", 4)
    assert res["ok"] and res["why"] == "a full check starts now" and sent == [f"{W.T}/rearm/press"]
    W.WAKE.clear()
    W.FLAGS["full"] = False
    W.on_message(W.MQ, None, types.SimpleNamespace(topic=f"{W.T}/rearm/press", payload=b"PRESS"))
    assert W.FLAGS["full"] and W.WAKE.is_set() and not W.FLAGS["rearm"]  # the full check, not a login
    W.RUN["check"], W.S["check_started_ts"] = True, time.time() - 30  # a check is running: it is not stuck
    res, _ = _press(W, "rearm/press", 5)
    assert not res["ok"] and res["why"].startswith("nothing to re-arm: a check is running (since ")
    W.RUN["check"] = False
    _gate_full(W, 99)
    res, _ = _press(W, "rearm/press", 6)
    assert not res["ok"] and res["why"].startswith("nothing to re-arm: the FLICA budget holds the next check until ")
    _gate_full(W, 0)
    W.S["machine"] = "stopped_unexpected"
    res, sent = _press(W, "rearm/press", 7)
    assert res["ok"] and res["why"] == "" and sent == [f"{W.T}/rearm/press"]
    W.S.update(machine="yielded", yield_until=time.time() + 1200)
    res, sent = _press(W, "rearm/press", 8)
    assert res["ok"] and sent and res["why"] == ("logs in when the step-aside for your own FLICA login ends, "
                                                 f"{W.hst_hm(W.S['yield_until'])} HST")


def test_rearm_while_hunting_and_checking_does_nothing_and_wakes_nothing(mk):
    W = mk("pilot2")
    W.FLAGS["hunt"] = True
    W.S.update(machine="hunting", last_check_ts=W.CLOCK.t - 130)
    W.WAKE.clear()
    W.on_message(W.MQ, None, types.SimpleNamespace(topic=f"{W.T}/rearm/press", payload=b"PRESS"))
    assert not W.WAKE.is_set() and not W.FLAGS["rearm"] and not W.FLAGS.get("full")


def test_rearm_in_a_step_aside_never_cuts_it_short(mk, monkeypatch):
    """A Re-arm while stepped aside for the pilot's own FLICA login, then commands that wake the loop every minute:
    no login before the step-aside ends (1.7.0 logged in at the first wake), one right after it."""
    W = mk("pilot2")
    until = W.CLOCK.t + 1800
    W.S.update(machine="yielded", yield_until=until, note="stepped aside")
    W.FLAGS["hunt"] = True

    def script(i):
        if i == 1:
            W.on_message(W.MQ, None, types.SimpleNamespace(topic=f"{W.T}/rearm/press", payload=b"PRESS"))
        W.WAKE.set()  # something else woke the loop
    logins, _ = _run_main(W, monkeypatch, script, max_sleeps=80, step=60)
    assert logins and min(logins) >= until, (logins, until)


# ------------------------------------------------------------------ F#75: the admin forwards each recall list
def test_the_admin_forwards_each_recall_list_to_every_pilot_never_its_me(mk, caplog):
    A = mk("")
    A.OPTS["pilots"] = [{"name": "pilot2"}, {"name": "demo", "portal": True}, {"name": "bad name"}]
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        A.recall_cmd(json.dumps({"date": "2026-11-10", "file": "ok", "rows": [ROW], "me": {"sen": 500}}))
    fwd = [(t, json.loads(p)) for t, p in A.MQ.msgs if t.endswith("/recall/set")]
    assert [t for t, _ in fwd] == ["flight_watcher_pilot2/recall/set", "flight_watcher_demo/recall/set"]
    assert all(p == [{"date": "2026-11-10", "file": "ok", "rows": [ROW]}] for _, p in fwd)  # never its 'me'
    assert "forwarded to 2 pilot Watchers" in caplog.text and "left out" not in caplog.text
    A.MQ.msgs.clear()
    A.recall_cmd(json.dumps({"date": "not a date", "rows": []}))
    assert not [t for t, _ in A.MQ.msgs if t.endswith("/recall/set")]  # nothing taken: nothing forwarded
    P = mk("pilot2")
    P.OPTS["pilots"] = [{"name": "pilot2"}]
    P.recall_cmd(json.dumps({"date": "2026-11-10", "rows": [ROW]}))
    assert not [t for t, _ in P.MQ.msgs if t.endswith("/recall/set")]  # a pilot forwards nothing


def test_the_same_list_twice_keeps_its_first_time(mk, monkeypatch):
    """The admin's forward and Ryan's HA action both send the list while the HA action is still there: the second copy
    changes nothing (its 'received' stays), and a changed list is news again."""
    P = mk("pilot2")
    sent = []
    monkeypatch.setattr(P, "pub", lambda t, p, retain=True: sent.append((t, p)))
    monkeypatch.setattr(P, "now_iso", lambda: P.datetime.fromtimestamp(P.CLOCK.t, P.timezone.utc).isoformat())
    day = {"date": "2026-11-10", "file": "ok", "rows": [ROW]}
    P.recall_cmd(json.dumps(day))
    at = P.DB.get("recall_days")["2026-11-10"]["at"]
    P.CLOCK.t += 37  # the second copy comes in a little later
    P.recall_cmd(json.dumps([day]))  # the other copy (a list of days)
    assert P.DB.get("recall_days")["2026-11-10"]["at"] == at
    rec = [p for t, p in sent if t == "recall"]
    assert len(rec) == 2 and rec[-1]["received"] == rec[0]["received"] == at
    P.CLOCK.t += 60
    P.recall_cmd(json.dumps({**day, "rows": [ROW, {**ROW, "pairing": "H9002"}]}))
    assert P.DB.get("recall_days")["2026-11-10"]["at"] == P.now_iso() != at  # a changed list is news


# ------------------------------------------------------------------ F#102: only CrewTrac details saved
def test_a_pilot_with_only_crewtrac_details_gets_the_charter_watch(mk, monkeypatch):
    W = mk("pilot2")
    assert not W.OPTS.get("username")  # a pilot's FLICA login comes from his Settings only: none saved
    W.OPTS.update(ctweb_username="doej", ctweb_password="pw")
    ran = threading.Event()
    monkeypatch.setattr(W, "charter_thread", lambda: ran.set())
    for f in ("migrate_swap_mode", "enforce_role", "captures_cleanup", "start_upload_janitor", "portal_start"):
        monkeypatch.setattr(W, f, lambda *a, **k: None)
    monkeypatch.setattr(W, "mqtt_start", lambda: W.MQ)

    def sleep(s):
        if s >= 3600:
            raise Stop("the wait for his FLICA login")
    monkeypatch.setattr("time.sleep", sleep)
    with pytest.raises(Stop):
        W.main()
    assert W.S["machine"] == "needs_settings" and ran.wait(5)
    assert any(t == f"{W.T}/charters" for t, _ in W.MQ.msgs)  # the charters status went out too
    assert W.start_charter_watch() is False  # once per process
    W.CHARTER_WAKE.clear()
    assert W.charter_press() is True and W.CHARTER_WAKE.is_set()  # Scan CrewTrac now: the thread reads the wake


# ------------------------------------------------------------------ F#155: Remove CrewTrac login (sealed)
def _sealed(W, fields):
    return json.dumps(SEAL.seal(SEAL.public_info(W.settings_key())["pubkey"], fields))


def test_remove_crewtrac_login_forgets_it_and_restarts(portal_pilot, monkeypatch, caplog):
    W, _ = portal_pilot("pilot2")
    restarts = []
    monkeypatch.setattr(W, "restart_later", lambda: restarts.append(1))
    json.dump({"username": "doej2", "password": "fl pw", "ctweb_username": "doej", "ctweb_password": "ct pw"},
              open(W.CREDS_FILE, "w"))
    W.DB.put("crewtrac", {"creds": "x" * 64, "state": "refused", "at": "2026-11-10T20:34:01+00:00"})
    assert W.settings_cmd(json.dumps({"ctweb_off": True})) is False  # plain: never (sealed only, like ntfy_off)
    assert W.load_creds()["ctweb_username"] == "doej" and not restarts
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        assert W.settings_cmd(_sealed(W, {"ctweb_off": True, "ctweb_username": "other"})) is True
    assert W.load_creds() == {"username": "doej2", "password": "fl pw"}  # FLICA's stay; CrewTrac's are gone
    assert W.DB.get("crewtrac") == {} and restarts == [1]
    st = json.loads([p for t, p, *_ in W.MQ.raw.msgs if t.endswith("/settings/state")][-1])
    assert st["result"] == "saved: CrewTrac login removed" and st["ctweb_username"] == "" and not st["has_ctweb_password"]
    assert "ct pw" not in caplog.text and "doej" not in caplog.text.replace("doej2", "")
    assert W.settings_cmd(_sealed(W, {"ctweb_off": True})) is False  # nothing saved: nothing to remove, no restart
    st = json.loads([p for t, p, *_ in W.MQ.raw.msgs if t.endswith("/settings/state")][-1])
    assert st["result"] == "nothing new: no CrewTrac login is saved" and restarts == [1]


# ------------------------------------------------------------------ F#77: the Watcher answers a Refresh
def test_a_recall_refresh_from_the_portal_is_answered_with_a_new_checked_time(demo):
    W = demo
    res, sent = _press(W, "recall/act", 30, payload=json.dumps({"refresh": True}))
    assert res["ok"] and sent == [f"{W.T}/recall/act"]
    before = [p for t, p, *_ in W.MQ.raw.msgs if t == f"{W.T}/recall"]
    W.on_message(W.MQ, None, types.SimpleNamespace(topic=f"{W.T}/recall/act", payload=b'{"refresh":true}'))
    after = [json.loads(p) for t, p, *_ in W.MQ.raw.msgs if t == f"{W.T}/recall"]
    assert not before and after and after[-1]["checked"]  # the card's Refresh gets its answer: a new checked time
