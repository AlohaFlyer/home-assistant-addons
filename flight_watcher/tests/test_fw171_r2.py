"""1.7.1, Ryan's decisions of Nov 11: the recall history replayed once from the admin to each pilot (judged and shown,
no alert or push), F#22 shared charters (a pilot's Watcher makes no CrewTrac login and shows the admin's scan, the flight
list only), FW-0042 the new-pairing push shows the commute and the value, F#10 the health line on the settings card
(version, FLICA pages in the last hour against the budget), and Ryan's weather view gone from the dashboard snapshot.
Synthetic data and made-up names only ("Doe, Jane"); FLICA and CrewTrac are never reached."""
import hashlib
import json
import logging
import os
import re
import types
from datetime import datetime

import pytest

from test_fw171_cards import P, _browser, _card, _page, _pilot, _s
from test_fw171_core import _gate_full, _press
from test_portal_spool import demo  # noqa: F401
from test_release_a_flica import mk  # noqa: F401

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(HERE)


# ------------------------------------------------------------------ the recall history replay
def _row(date, pairing, v="MISSED"):
    return {"date": date, "kind": "recall", "seat": "FO", "pilot": "Doe, Jane", "sen": 900, "pairing": pairing, "v": v}


def _judge(monkeypatch, W):
    """Each synthetic row judged as its own 'v' says (the real check needs a whole schedule history)."""
    def check_day(rows, me, *a, **k):
        return [{"date": r["date"], "kind": r["kind"], "pairing": r["pairing"], "seat": r["seat"], "sen": r["sen"],
                 "verdict": r.get("v", "NO"), "why": ["synthetic"]} for r in rows or []]
    monkeypatch.setattr(W.RC, "check_day", check_day)


def _history(A):
    """The admin's lists from Oct 30 to Nov 2 (before the pilot started) and Nov 10."""
    for d, pid in (("2026-10-30", "H9030"), ("2026-10-31", "H9031"), ("2026-11-01", "H9001"), ("2026-11-02", "H9002"),
                   ("2026-11-10", "H9110")):
        A.recall_cmd(json.dumps({"date": d, "file": "ok", "rows": [_row(d, pid)]}))
    A.MQ.msgs.clear()


def _status(A, prefix, text):
    """The pilot Watcher's availability as the broker hands it to the admin (retained <prefix>/status)."""
    A.on_message(A.MQ, None, types.SimpleNamespace(topic=f"{prefix}/status", payload=text.encode()))


def _online(A, *prefixes):
    """Each pilot's Watcher online long enough for his replay (RECALL_REPLAY_SETTLE_S)."""
    for p in prefixes:
        _status(A, p, "online")
    A.CLOCK.t += A.RECALL_REPLAY_SETTLE_S


def _confirm(A):
    """The pilots stay online RECALL_REPLAY_CONFIRM_S after the send, a tick a minute: the replay is marked done."""
    for _ in range(A.RECALL_REPLAY_CONFIRM_S // 60):
        A.CLOCK.t += 60
        assert A.recall_replay_tick() == []


def test_the_admin_replays_its_recall_history_once_to_each_pilot(mk, monkeypatch, caplog):
    A = mk("")
    _judge(monkeypatch, A)
    A.OPTS["pilots"] = [{"name": "pilot2"}]
    _history(A)
    _online(A, "flight_watcher_pilot2")
    A._REPLAY["since"] = A.CLOCK.t - 60
    assert A.recall_replay_tick() == [] and not A.MQ.msgs  # not before RECALL_REPLAY_DELAY_S after the start
    A._REPLAY["since"] = A.CLOCK.t - A.RECALL_REPLAY_DELAY_S
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        assert A.recall_replay_tick() == ["flight_watcher_pilot2"]
        (topic, body), = [(t, json.loads(p)) for t, p in A.MQ.msgs]
        assert topic == "flight_watcher_pilot2/recall/set"
        assert [d["date"] for d in body] == ["2026-10-30", "2026-10-31", "2026-11-01", "2026-11-02", "2026-11-10"]
        stored = A.DB.get("recall_days")
        for d in body:  # the list as it came in, its first time, the mark; never 'me', the verdicts or the CCR drafts
            assert set(d) == {"date", "file", "rows", "at", "replay"} and d["replay"] is True
            assert d["rows"] == stored[d["date"]]["rows"] and d["at"] == stored[d["date"]]["at"] and d["file"] == "ok"
        assert not A.DB.get(A.RECALL_REPLAY)  # done only once his Watcher stayed online after it
        A.MQ.msgs.clear()
        _confirm(A)
    assert not A.MQ.msgs  # sent once while he stayed online
    assert A.DB.get(A.RECALL_REPLAY)["flight_watcher_pilot2"]["days"] == 5
    assert caplog.text.count("recall history replayed once to flight_watcher_pilot2: 5 stored days "
                             "(2026-10-30 to 2026-11-10)") == 1
    A.MQ.msgs.clear()
    A.CLOCK.t += 3600
    assert A.recall_replay_tick() == [] and not A.MQ.msgs  # once: the DB flag holds across ticks (and restarts)
    # a long history goes in parts (no one message grows with the 120 days kept), all of it, in date order
    A.DB.put(A.RECALL_REPLAY, {})
    A.DB.put("recall_days", {f"2026-09-{d:02d}": {"date": f"2026-09-{d:02d}", "file": "blank", "rows": [], "at": ""}
                             for d in range(1, 31)})
    assert A.recall_replay_tick() == ["flight_watcher_pilot2"]
    parts = [json.loads(p) for _, p in A.MQ.msgs]
    assert [len(x) for x in parts] == [20, 10] and [d["date"] for x in parts for d in x] == sorted(
        A.DB.get("recall_days"))
    _confirm(A)
    A.MQ.msgs.clear()
    A.OPTS["pilots"] = [{"name": "pilot2"}, {"name": "demo"}]  # a pilot added later gets his own replay, once
    _online(A, "flight_watcher_demo")
    assert A.recall_replay_tick() == ["flight_watcher_demo"]
    assert {t for t, _ in A.MQ.msgs} == {"flight_watcher_demo/recall/set"}
    # a pilot replays nothing
    Pi = mk("pilot2")
    Pi._REPLAY["since"] = Pi.CLOCK.t - 999
    assert Pi.recall_replay_tick() == [] and not Pi.MQ.msgs


def test_a_replay_waits_for_the_pilots_watcher_and_goes_again_if_he_restarts(mk, monkeypatch, caplog):
    """1.7.1 review: a replay published while the pilot's Watcher is down is dropped by the broker (clean sessions,
    not retained) without an error, so the admin sends it only while his availability reads online and marks it done
    only once he stayed online after it. A restart in that time (a Settings save, a crash) sends it again."""
    A = mk("")
    _judge(monkeypatch, A)
    A.OPTS["pilots"] = [{"name": "pilot2"}]
    _history(A)
    A._REPLAY["since"] = A.CLOCK.t - A.RECALL_REPLAY_DELAY_S
    sends = lambda: [t for t, _ in A.MQ.msgs if t == "flight_watcher_pilot2/recall/set"]  # noqa: E731
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        assert A.recall_replay_tick() == [] and sends() == []  # never seen online: nothing sent, nothing done
        _status(A, "flight_watcher_pilot2", "offline")  # his will (the restart a Settings save makes)
        A.CLOCK.t += 60
        assert A.recall_replay_tick() == [] and sends() == [] and not A.DB.get(A.RECALL_REPLAY)
        assert caplog.text.count("recall history replay to flight_watcher_pilot2 waits until its Watcher is online") == 1
        _status(A, "flight_watcher_pilot2", "online")  # back, but his subscriptions follow his "online"
        assert A.recall_replay_tick() == [] and sends() == []
        A.CLOCK.t += A.RECALL_REPLAY_SETTLE_S
        assert A.recall_replay_tick() == ["flight_watcher_pilot2"] and len(sends()) == 1
        A.CLOCK.t += 60
        assert A.recall_replay_tick() == [] and not A.DB.get(A.RECALL_REPLAY)  # not done yet: he may still go down
        _status(A, "flight_watcher_pilot2", "offline")  # he restarts before the confirm time: the replay may be lost
        A.CLOCK.t += 60
        assert A.recall_replay_tick() == [] and len(sends()) == 1 and not A.DB.get(A.RECALL_REPLAY)
        _online(A, "flight_watcher_pilot2")
        assert A.recall_replay_tick() == ["flight_watcher_pilot2"] and len(sends()) == 2  # sent again
        assert "its Watcher restarted after the send; sending it again" in caplog.text
        _confirm(A)
    assert len(sends()) == 2 and A.DB.get(A.RECALL_REPLAY)["flight_watcher_pilot2"]["days"] == 5
    # the admin's own reconnect starts the counts again (a restart it missed counts as one): nothing more once done
    subs = []
    A.subscribe_all(types.SimpleNamespace(subscribe=lambda t, *a: subs.append(t)))
    assert subs[-1] == ("flight_watcher_pilot2/status", 1) and A.PILOT_UP == {}
    assert subs[:-1] == [(f"flight_watcher/{t}", q) if q else f"flight_watcher/{t}"
                         for t, q in A.ROLES.subscriptions("")]  # the role list itself is unchanged
    _online(A, "flight_watcher_pilot2")
    A.CLOCK.t += 600
    assert A.recall_replay_tick() == [] and len(sends()) == 2


def test_a_pilots_status_is_only_data_and_a_pilot_reads_none(mk):
    A = mk("")
    A.OPTS["pilots"] = [{"name": "pilot2"}]
    for text in ("ONLINE", "on", '{"cmd": "online"}', ""):
        _status(A, "flight_watcher_pilot2", text)
        assert A.PILOT_UP["flight_watcher_pilot2"] is None, text  # only the exact word starts the count
    assert A.pilot_status_in("flight_watcher_other/status", b"online") is False  # not a pilot of this add-on
    assert A.pilot_status_in("flight_watcher/status", b"online") is False  # the admin's own
    assert A.pilot_status_in("flight_watcher_pilot2/recall", b"online") is False
    assert set(A.PILOT_UP) == {"flight_watcher_pilot2"}
    _status(A, "flight_watcher_pilot2", "online")
    t0 = A.PILOT_UP["flight_watcher_pilot2"]
    A.CLOCK.t += 300
    _status(A, "flight_watcher_pilot2", "online")  # the retained copy again: his count goes on
    assert A.PILOT_UP["flight_watcher_pilot2"] == t0
    Pi = mk("pilot2")
    Pi.OPTS["pilots"] = [{"name": "pilot2"}]
    assert Pi.pilot_status_subs() == [] and Pi.pilot_status_in("flight_watcher_pilot2/status", b"online") is False
    subs = []
    Pi.subscribe_all(types.SimpleNamespace(subscribe=lambda t, *a: subs.append(t)))
    assert not [s for s in subs if (s[0] if isinstance(s, tuple) else s).endswith("/status")]


def test_a_replay_is_judged_and_shown_but_never_alerts_or_pushes(mk, monkeypatch, caplog):
    """The admin's real replay body into a pilot that started Nov 10: the four older days are taken (judged, a CCR draft
    each, shown on his Recall/O75 tab with the admin's received time), the day he holds stays as it is, nothing goes on
    event/recall_miss and the RECALL ALERT count stays at his own day's miss. A replay twice changes nothing; a later
    live list still alerts for its own miss only."""
    A = mk("")
    _judge(monkeypatch, A)
    A.OPTS["pilots"] = [{"name": "pilot2"}]
    _history(A)
    A._REPLAY["since"] = A.CLOCK.t - A.RECALL_REPLAY_DELAY_S
    _online(A, "flight_watcher_pilot2")
    A.recall_replay_tick()
    (_, replay), = A.MQ.msgs
    admin_at = {d: v["at"] for d, v in A.DB.get("recall_days").items()}

    Pi = mk("pilot2")
    _judge(monkeypatch, Pi)
    Pi.recall_cmd(json.dumps({"date": "2026-11-10", "file": "ok", "rows": [_row("2026-11-10", "H9110")]}))  # live
    misses = lambda: [json.loads(p) for t, p in Pi.MQ.msgs if t == f"{Pi.T}/event/recall_miss"]  # noqa: E731
    assert [m["pairing"] for m in misses()] == ["H9110"]  # his own day alerts, as before
    held = json.loads(json.dumps(Pi.DB.get("recall_days")["2026-11-10"]))
    Pi.MQ.msgs.clear()
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        Pi.on_message(Pi.MQ, None, types.SimpleNamespace(topic=f"{Pi.T}/recall/set", payload=replay.encode()))
    assert misses() == []  # no push for replayed days
    days = Pi.DB.get("recall_days")
    assert sorted(days) == ["2026-10-30", "2026-10-31", "2026-11-01", "2026-11-02", "2026-11-10"]
    assert days["2026-11-10"] == held  # the day he holds is untouched
    for d in ("2026-10-30", "2026-10-31", "2026-11-01", "2026-11-02"):
        assert days[d]["replay"] is True and days[d]["at"] == admin_at[d]
        assert [v["verdict"] for v in days[d]["verdicts"]] == ["MISSED"]  # judged against his own line
    acts = Pi.DB.get("recall_acts")
    assert {k[:10] for k in acts} == set(days) and all(a["status"] == "new" for a in acts.values())  # drafts shown
    rec = json.loads([p for t, p in Pi.MQ.msgs if t == f"{Pi.T}/recall"][-1])
    assert rec["open"] == 5 and rec["alert"] == 1  # the RECALL ALERT bar counts his own day's miss only
    assert rec["received"] == days["2026-11-10"]["at"]  # 'came in' stays the newest live list
    assert {d["date"]: d.get("replay", False) for d in rec["days"]}["2026-10-30"] is True
    assert "recall history from the admin: 4 days taken (2026-10-30 to 2026-11-02), 1 already held" in caplog.text
    # twice: nothing changes (the days, the drafts, no push)
    before = json.dumps([Pi.DB.get("recall_days"), Pi.DB.get("recall_acts")], sort_keys=True)
    Pi.MQ.msgs.clear()
    Pi.recall_cmd(replay)
    assert json.dumps([Pi.DB.get("recall_days"), Pi.DB.get("recall_acts")], sort_keys=True) == before
    assert misses() == []
    # a new live list later: only its own miss pushes, never a replayed day's (each eval re-judges every day)
    Pi.recall_cmd(json.dumps({"date": "2026-11-11", "file": "ok", "rows": [_row("2026-11-11", "H9111")]}))
    assert [m["pairing"] for m in misses()] == ["H9111"]


def test_the_admin_ignores_a_replay_mark_and_never_forwards_one(mk, monkeypatch):
    A = mk("")
    _judge(monkeypatch, A)
    A.OPTS["pilots"] = [{"name": "pilot2"}]
    A.recall_cmd(json.dumps([{"date": "2026-11-09", "rows": [_row("2026-11-09", "H9109")], "replay": True,
                              "at": "2026-01-01T00:00:00+00:00"}]))
    day = A.DB.get("recall_days")["2026-11-09"]
    assert "replay" not in day and day["at"] != "2026-01-01T00:00:00+00:00"  # a list from Hark, as any other
    assert [t for t, _ in A.MQ.msgs if t == "flight_watcher/event/recall_miss"]  # judged and pushed as any list
    (fwd,), = [json.loads(p) for t, p in A.MQ.msgs if t == "flight_watcher_pilot2/recall/set"]
    assert set(fwd) == {"date", "rows"}  # the live forward carries no mark and no time


def test_the_recall_card_shows_a_replayed_day_without_an_alert():
    def verdict(d, pid):
        return {"id": f"{d}|{pid}|recall", "date": d, "kind": "recall", "pairing": pid, "seat": "FO", "sen": 900,
                "pilot": "Doe, Jane", "verdict": "MISSED", "why": ["synthetic"], "act": {"status": "new", "narrative": "x"}}
    a = {"open": 2, "alert": 1, "me": {"sen": 500, "seat": "FO"}, "last": "2026-11-10", "checked": "2026-11-10T11:00:00Z",
         "received": "2026-11-10T10:00:00Z", "sen_source": "typed",
         "days": [{"date": "2026-11-10", "file": "ok", "verdicts": [verdict("2026-11-10", "H9110")]},
                  {"date": "2026-11-02", "file": "ok", "replay": True, "verdicts": [verdict("2026-11-02", "H9002")]}]}
    st = _pilot({"sensor.flight_watcher_recall_o75": _s("2", a), "sensor.flight_watcher_state": _s("idle", {"role": "pilot"})})
    with _browser() as b:
        pg = _page(b, [_card("recall-card")])
        got = pg.evaluate("""(st) => { const al = mount('flight-watcher-recall-card-pilot2', {mode: 'alert'}, st);
          const tab = mount('flight-watcher-recall-card-pilot2', {}, st); tab._m = '2026-11'; tab._sig = null; tab.hass = tab._h;
          const day = tab.shadowRoot.querySelector('details[data-day="2026-11-02"]');
          return {bar: [...al.shadowRoot.querySelectorAll('.bar li')].map((l) => l.textContent.trim()),
                  tabBar: [...tab.shadowRoot.querySelectorAll('.bar li')].length,
                  sum: day.querySelector('summary').textContent, note: day.querySelector('.row.k').textContent}; }""", st)
    assert len(got["bar"]) == 1 and "H9110" in got["bar"][0] and got["tabBar"] == 1
    assert "list ok, history" in got["sum"] and "1 should have been you" in got["sum"]
    assert got["note"].startswith("From the admin's recall history") and "no alert or push" in got["note"]


# ------------------------------------------------------------------ F#22: shared charters
FLIGHTS = {
    "2026-11-20|9980|HNL-SIN": {"key": "2026-11-20|9980|HNL-SIN", "date": "2026-11-20", "flight": "9980",
                                "route": "HNL-SIN", "scheduled": "11/20 09:00-11/21 15:00", "eqpt": "332/3",
                                "tail": "N300XX", "why": "99xx flight", "cancelled": "", "estimated": "09:05",
                                "actual": "", "orig": "11/20", "first_seen": "2026-11-11", "gone": False},
    "2026-11-21|0071|HNL-ANC": {"key": "2026-11-21|0071|HNL-ANC", "date": "2026-11-21", "flight": "71",
                                "route": "HNL-ANC", "scheduled": "11/21 22:00-11/22 05:30", "eqpt": "333",
                                "tail": "N301XX", "why": "ANC not a regular A330 station", "cancelled": "",
                                "estimated": "", "actual": "", "orig": "11/21", "first_seen": "2026-11-10", "gone": True},
}
CARD_FIELDS = {"key", "date", "flight", "route", "scheduled", "eqpt", "tail", "why", "first_seen", "gone"}


def _admin_scanned(A, flights=FLIGHTS, at="2026-11-11T00:05:00+00:00"):
    A.DB.put("charters", json.loads(json.dumps(flights)))
    A.DB.put("charter_scan_at", at)


def test_the_admin_shares_only_the_flight_list_retained_under_its_own_prefix(mk):
    A = mk("")
    assert A.charters_share() is False  # no scan yet: nothing
    _admin_scanned(A)
    A.OPTS["pilots"] = []
    assert A.charters_share() is False  # no pilot on this add-on: nothing to share
    A.OPTS["pilots"] = [{"name": "pilot2"}]
    A.DB.put("crewtrac", {"creds": "c" * 64, "state": "ok"})  # his own login's record: never in the share
    A.DB.put("charter_status", "ok: 412 rows, 2 unusual A330, 0 new")
    A.MQ.msgs.clear()
    assert A.charters_share() is True
    (topic, body), = A.MQ.msgs
    assert topic == A.CHARTERS_SHARED == "flight_watcher/charters/shared"
    d = json.loads(body)
    assert set(d) == {"v", "at", "items"} and d["at"] == "2026-11-11T00:05:00+00:00"
    assert [set(r) for r in d["items"]] == [CARD_FIELDS, CARD_FIELDS]  # the card's columns, nothing else
    assert [r["flight"] for r in d["items"]] == ["9980", "71"] and d["items"][1]["gone"] is True
    A.DB.put("own_trips", {"H9101|2026-11-20": {"report": "08:00"}})  # the admin's own line: never in the share
    A.MQ.msgs.clear()
    assert A.charters_share() is True
    body = A.MQ.msgs[-1][1]
    for word in ("estimated", "actual", "cancelled", "orig", "crewtrac", "status", "creds", '"fit"', "ok: 412", "H9101",
                 "own", "report"):
        assert word not in body, word  # nothing of the admin's login, status, line or fit, no extra CrewTrac column


def test_the_admin_shares_after_each_scan_and_at_start(mk, monkeypatch):
    A = mk("")
    A.OPTS["pilots"] = [{"name": "pilot2"}]
    _admin_scanned(A)
    monkeypatch.setattr(A, "charter_thread", lambda: None)
    A.MQ.msgs.clear()
    assert A.start_charter_watch() is True
    assert [t for t, _ in A.MQ.msgs if t == A.CHARTERS_SHARED] == [A.CHARTERS_SHARED]  # at start, the last scan again

    class Sc:  # a scan that read CrewTrac (no network: the Scanner's answers)
        def __init__(self, *a, **k):
            self.unconfirmed = False

        def login(self):
            return A.CH.OK

        def scan(self, today):
            return [dict(FLIGHTS["2026-11-20|9980|HNL-SIN"])]
    monkeypatch.setattr(A.CH, "Scanner", Sc)
    monkeypatch.setattr(A.CH, "unusual", lambda rows, reg: [{k: v for k, v in r.items() if k not in ("first_seen", "gone")}
                                                            for r in rows])
    A.OPTS.update(ctweb_username="10001", ctweb_password="pw")
    A.MQ.msgs.clear()
    assert A.charter_scan() is True
    shared = [json.loads(p) for t, p in A.MQ.msgs if t == A.CHARTERS_SHARED]
    assert len(shared) == 1 and shared[0]["at"] == A.DB.get("charter_scan_at")
    assert [r["flight"] for r in shared[0]["items"] if not r["gone"]] == ["9980"]


def _shared(at="2026-11-11T00:05:00+00:00", flights=FLIGHTS):
    return json.dumps({"v": 1, "at": at, "items": [{k: r[k] for k in CARD_FIELDS} for r in flights.values()]}).encode()


def test_a_pilot_shows_the_admins_list_with_its_source_and_time(mk, caplog):
    Pi = mk("pilot2")
    Pi.MQ.msgs.clear()
    Pi.publish_charters()
    s0 = Pi.MQ.last(f"{Pi.T}/charters")
    assert s0["status"] == "waiting for the admin's CrewTrac scan" and s0["items"] == [] and s0["source"] == "admin"
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        Pi.on_message(Pi.MQ, None, types.SimpleNamespace(topic="flight_watcher/charters/shared", payload=_shared()))
    s = Pi.MQ.last(f"{Pi.T}/charters")
    assert s["source"] == "admin" and s["last_scan"] == "2026-11-11T00:05:00+00:00"
    assert s["status"] == "from the admin's scan at Nov 10 14:05 HST"  # the date too: not today (Nov 6 here)
    assert s["count"] == 1 and [r["flight"] for r in s["items"]] == ["9980", "71"]
    assert s["crewtrac"] == {"state": "not_used", "at": "", "next_try": ""}
    assert all(set(r) == CARD_FIELDS for r in s["items"])
    # the first list on an instance that never had one is taken quietly: no burst of alerts
    assert not [t for t, _ in Pi.MQ.msgs if t.endswith("/event/charter")]
    assert "first shared list taken quietly" in caplog.text
    # a later scan with a new flight: his event/charter once (his portal's charter alert), the flight fields only
    more = dict(FLIGHTS, **{"2026-11-25|9982|HNL-NRT": {**FLIGHTS["2026-11-20|9980|HNL-SIN"], "key": "2026-11-25|9982|HNL-NRT",
                                                      "date": "2026-11-25", "flight": "9982", "route": "HNL-NRT"}})
    Pi.MQ.msgs.clear()
    Pi.on_message(Pi.MQ, None, types.SimpleNamespace(topic="flight_watcher/charters/shared",
                                                     payload=_shared("2026-11-11T06:05:00+00:00", more)))
    ev = [json.loads(p) for t, p in Pi.MQ.msgs if t == f"{Pi.T}/event/charter"]
    assert [e["flight"] for e in ev] == ["9982"]
    assert set(ev[0]) == {"key", "date", "flight", "route", "scheduled", "eqpt", "tail", "why"}
    Pi.MQ.msgs.clear()
    Pi.charters_shared_in(_shared("2026-11-11T06:05:00+00:00", more))  # the same list again: no alert
    assert not [t for t, _ in Pi.MQ.msgs if t.endswith("/event/charter")]
    # data, not instructions: a malformed list changes nothing; extra fields are dropped, long text cut
    Pi.MQ.msgs.clear()
    assert Pi.charters_shared_in(b"not json") == [] and not Pi.MQ.msgs
    assert Pi.charters_shared_in(json.dumps({"at": "x", "items": "all"})) == []
    odd = {"key": "k1", "flight": "1" * 300, "route": "HNL-SIN", "contact": "Doe, Jane 808", "gone": "yes"}
    Pi.charters_shared_in(json.dumps({"at": "2026-11-11T07:00:00+00:00", "items": [odd, 5, {"key": "no flight"}]}))
    (it,) = Pi.MQ.last(f"{Pi.T}/charters")["items"]
    assert set(it) == CARD_FIELDS and len(it["flight"]) == 80 and it["gone"] is False


def test_a_pilot_flights_seen_by_his_own_old_scans_do_not_alert_again(mk):
    Pi = mk("pilot2")
    Pi.DB.put("charters", {"2026-11-20|9980|HNL-SIN": FLIGHTS["2026-11-20|9980|HNL-SIN"]})  # from his 1.7.0 scans
    Pi.MQ.msgs.clear()
    one = {"2026-11-20|9980|HNL-SIN": FLIGHTS["2026-11-20|9980|HNL-SIN"],
           "2026-11-26|9984|HNL-PPT": {**FLIGHTS["2026-11-20|9980|HNL-SIN"], "key": "2026-11-26|9984|HNL-PPT",
                                       "flight": "9984", "route": "HNL-PPT", "date": "2026-11-26"}}
    assert Pi.charters_shared_in(_shared(flights=one)) == ["2026-11-26|9984|HNL-PPT"]


def test_a_pilot_makes_no_crewtrac_login_at_all(mk, monkeypatch, caplog):
    Pi = mk("pilot2")
    Pi.OPTS.update(ctweb_username="doej", ctweb_password="pw")  # an old saved login: harmless, never used
    logins = []
    monkeypatch.setattr(Pi.CH, "Scanner", lambda *a, **k: logins.append(1))
    monkeypatch.setattr(Pi, "charter_thread", lambda: logins.append("thread"))
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        assert Pi.start_charter_watch() is True  # the status only
    assert logins == []  # no charter thread, no Scanner
    assert "makes no CrewTrac login" in caplog.text
    assert Pi.charter_scan() is False and Pi._charter_scan({}) is False and logins == []
    Pi.CHARTER_WAKE.clear()
    assert Pi.charter_press() is False and not Pi.CHARTER_WAKE.is_set()
    assert Pi.crewtrac_lift() is False  # saving the same login again lifts nothing (there is no login to retry)
    assert Pi.MQ.last(f"{Pi.T}/charters")["crewtrac"]["state"] == "not_used"
    # the pilot's subscriptions: his own, plus the admin's shared list (never a command)
    subs = []
    Pi.subscribe_all(types.SimpleNamespace(subscribe=lambda t, *a: subs.append(t)))
    assert subs[-1] == ("flight_watcher/charters/shared", 1)
    assert all((s[0] if isinstance(s, tuple) else s).startswith(f"{Pi.T}/") for s in subs[:-1])
    A = mk("")
    asubs = []
    A.subscribe_all(types.SimpleNamespace(subscribe=lambda t, *a: asubs.append(t)))
    assert ("flight_watcher/charters/shared", 1) not in asubs  # the admin never reads it back


def test_a_portal_scan_press_answers_ok_false_with_the_reason(demo):
    W = demo
    _gate_full(W, 0)
    res, sent = _press(W, "charter_scan/press", 40)
    assert res["ok"] is False and sent == []
    assert res["why"] == "ignored: charters come from the admin's CrewTrac scan; this Watcher does not log in to CrewTrac"


def test_the_charters_card_says_where_the_list_comes_from_and_has_no_scan_button():
    a = {"count": 1, "items": [{k: r[k] for k in CARD_FIELDS} for r in FLIGHTS.values()],
         "last_scan": "2026-11-11T00:05:00+00:00", "status": "from the admin's scan at 14:05 HST", "source": "admin",
         "crewtrac": {"state": "not_used", "at": "", "next_try": ""}}
    with _browser() as b:
        for width, scheme in ((390, "light"), (390, "dark")):
            pg = _page(b, [_card("charters-card")], width=width, scheme=scheme)
            got = pg.evaluate("""(st) => { const c = mount('flight-watcher-charters-card-pilot2', {}, st);
              return {st: c.shadowRoot.getElementById('st').textContent, scan: !!c.shadowRoot.getElementById('scan'),
                      why: c.shadowRoot.getElementById('why').textContent, rows: c.shadowRoot.querySelectorAll('.r').length,
                      con: fwContrast(c), fit: fwFits(c)}; }""", _pilot({"sensor.flight_watcher_charters": _s("1", a)}))
            assert got["st"] == "From the admin's CrewTrac scan at Nov 10 14:05 HST." and got["scan"] is False
            assert "you need no CrewTrac login" in got["why"] and got["rows"] == 2
            assert not got["con"]["fails"], got["con"]["fails"]
            assert got["fit"]["page"] <= 390
            pg.context.close()
        # the admin's own card (no source): the Scan button as before
        pg = _page(b, [_card("charters-card", pilot=False)])
        own = dict(a, source=None, crewtrac={"state": "ok"}, status="ok: 400 rows")
        assert pg.evaluate("(st) => !!mount('flight-watcher-charters-card', {}, st).shadowRoot.getElementById('scan')",
                           {"sensor.flight_watcher_charters": _s("1", own)}) is True


def test_the_charters_card_warns_when_the_admins_scans_stop():
    """1.7.1 review: the admin shares only after a scan that read CrewTrac, so when its scans stop (its CrewTrac login
    refused or removed) the pilot's list stays as it was. Over 13 h after the admin's scan (two 6 h scans and their
    jitter missed) his card says so as a warning, in light and dark, and the same sensor turns it on as time passes."""
    def st(last):
        return _pilot({"sensor.flight_watcher_charters": _s("1", {
            "count": 1, "items": [{k: r[k] for k in CARD_FIELDS} for r in FLIGHTS.values()], "last_scan": last,
            "status": "", "source": "admin", "crewtrac": {"state": "not_used", "at": "", "next_try": ""}})})
    js = """(st) => { window.C = mount('flight-watcher-charters-card-pilot2', {}, st); const r = C.shadowRoot;
      return {cls: r.getElementById('st').className, st: r.getElementById('st').textContent,
              rows: r.querySelectorAll('.r').length, con: fwContrast(C), fit: fwFits(C)}; }"""
    with _browser() as b:
        for scheme in ("light", "dark"):
            pg = _page(b, [_card("charters-card")], scheme=scheme)  # the time fixed at Nov 10 11:30 UTC
            got = pg.evaluate(js, st("2026-11-09T22:00:00+00:00"))  # 13.5 h before
            assert got["cls"] == "st warn" and got["rows"] == 2
            assert got["st"] == ("The admin's last CrewTrac scan was Nov 9 12:00 HST, over 13 h ago. Charters added or "
                                 "cancelled since then are not shown until it scans again.")
            assert not got["con"]["fails"], got["con"]["fails"]
            assert got["fit"]["page"] <= 390
            got = pg.evaluate(js, st("2026-11-09T23:00:00+00:00"))  # 12.5 h before: the scan is still current
            assert got["cls"] == "st info" and got["st"] == "From the admin's CrewTrac scan at Nov 9 13:00 HST."
            pg.context.close()
        # the same sensor (no new list) turns to the warning once 13 h pass: the card re-renders on the next update
        pg = _page(b, [_card("charters-card")], clock=True)
        assert pg.evaluate(js, st("2026-11-09T23:00:00+00:00"))["cls"] == "st info"
        pg.clock.run_for(31 * 60 * 1000)
        pg.evaluate("(st) => { C.hass = mkHass(st); }", st("2026-11-09T23:00:00+00:00"))
        assert pg.evaluate("C.shadowRoot.getElementById('st').className") == "st warn"
        # the admin's own card is never marked from its scan time (its CrewTrac state says what is wrong)
        pg = _page(b, [_card("charters-card", pilot=False)])
        own = {"sensor.flight_watcher_charters": _s("1", {"items": [], "last_scan": "2026-11-01T00:00:00+00:00",
                                                           "crewtrac": {"state": "ok"}, "status": "ok: 400 rows"})}
        assert pg.evaluate("(st) => mount('flight-watcher-charters-card', {}, st).shadowRoot.getElementById('st')"
                           ".className", own) == "st ok"


def _settings(ct_state="not_used", saved=True, version="1.7.1", hour=37, at="2026-11-10T11:29:00+00:00", budget=100):
    a = {"instance": "pilot2", "username": "doej", "my_name": "Doe", "ctweb_username": "doej" if saved else "",
         "has_password": True, "has_ctweb_password": saved, "at": "2026-11-10T11:00:00+00:00", "result": "",
         "doh": "2016-03-02", "ntfy": False, "pubkey": "", "kid": ""}
    return _pilot({"sensor.flight_watcher_settings": _s("ok", a),
                   "sensor.flight_watcher_state": _s("hunting", {"role": "pilot", "version": version}),
                   "sensor.flight_watcher_flica_fetches": _s("5321", {"total": 5321, "at": at, "hour": hour, "budget": budget}),
                   "sensor.flight_watcher_charters": _s("0", {"crewtrac": {"state": ct_state}, "source": "admin"})})


SETTINGS_JS = """(st) => { const c = mount('flight-watcher-settings-card-pilot2', {}, st); const r = c.shadowRoot;
  return {keys: [...r.querySelectorAll('input[data-k]')].map((i) => i.dataset.k), ctno: (r.getElementById('ctno') || {}).textContent || '',
          rm: !!r.getElementById('ctoff'), who: r.getElementById('who').textContent, ct: r.getElementById('ct').textContent,
          con: fwContrast(c), fit: fwFits(c)}; }"""


def test_the_settings_card_says_crewtrac_is_not_needed_and_keeps_remove():
    with _browser() as b:
        pg = _page(b, [_card("settings-card")])
        got = pg.evaluate(SETTINGS_JS, _settings())
        assert "ctweb_username" not in got["keys"] and "ctweb_password" not in got["keys"] and "password" in got["keys"]
        assert got["ctno"].startswith("CrewTrac") and "Not needed: your charters come from the admin's CrewTrac scan" in got["ctno"]
        assert got["rm"] is True and "still saved" in got["ctno"] and got["ct"] == ""  # the old login can still go
        pg.context.close()
        pg = _page(b, [_card("settings-card")])
        got = pg.evaluate(SETTINGS_JS, _settings(saved=False))
        assert got["rm"] is False and "still saved" not in got["ctno"]
        pg.context.close()
        # a Watcher that still reads CrewTrac (the admin, or an older pilot Watcher): the fields as before
        pg = _page(b, [_card("settings-card")])
        got = pg.evaluate(SETTINGS_JS, _settings(ct_state="refused"))
        assert {"ctweb_username", "ctweb_password"} <= set(got["keys"]) and got["ctno"] == ""


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_the_health_line_at_390_px(scheme):
    """F#10: version, state and FLICA pages in the last hour against the budget, from the sensors his export carries;
    rendered on the portal's light and dark cards at 390 px with WCAG AA contrast."""
    shots = os.environ.get("FW_171_SHOTS", "")
    with _browser() as b:
        pg = _page(b, [_card("settings-card")], scheme=scheme)
        got = pg.evaluate(SETTINGS_JS, _settings())
        if shots:
            pg.screenshot(path=os.path.join(shots, f"health_390_{scheme}.png"), full_page=True)
        assert got["who"] == "Watcher 1.7.1: hunting. FLICA pages in the last hour: 37 of 100."
        assert not got["con"]["fails"], got["con"]["fails"]
        assert got["fit"]["page"] <= 390 and got["fit"]["right"] <= 390
        pg.context.close()
        # counted 20 min ago: its time shows; over an hour ago: no load since, so 0
        pg = _page(b, [_card("settings-card")], scheme=scheme)
        assert pg.evaluate(SETTINGS_JS, _settings(at="2026-11-10T11:10:00+00:00"))["who"] == (
            "Watcher 1.7.1: hunting. FLICA pages in the last hour: 37 of 100 (counted 01:10 HST).")
        pg.context.close()
        pg = _page(b, [_card("settings-card")], scheme=scheme)
        assert pg.evaluate(SETTINGS_JS, _settings(at="2026-11-10T10:00:00+00:00"))["who"] == (
            "Watcher 1.7.1: hunting. FLICA pages in the last hour: 0 of 100.")
        pg.context.close()


def test_the_fetches_sensor_carries_this_hours_loads_and_the_budget(mk):
    Pi = mk("pilot2")
    _gate_full(Pi, 37)
    Pi.MQ.msgs.clear()
    Pi.FETCHES["pub_at"] = 0
    Pi.count_fetch()
    f = Pi.MQ.last(f"{Pi.T}/fetches")
    assert f["hour"] == 37 and f["budget"] == 100 and f["total"] >= 1 and f["at"]
    # loads age out while nothing loads: the janitor's minute sends the new count, and nothing when it is the same
    Pi.MQ.msgs.clear()
    assert Pi.fetches_tick() is False and not Pi.MQ.msgs
    _gate_full(Pi, 12)
    assert Pi.fetches_tick() is True and Pi.MQ.last(f"{Pi.T}/fetches")["hour"] == 12
    A = mk("")
    A.FETCHES["pub_at"] = 0
    A.count_fetch()
    fa = A.MQ.last("flight_watcher/fetches")
    assert fa["budget"] is None and "hour" in fa and A.fetches_tick() is False  # the admin: no budget, no tick


def test_the_portal_exports_both_sensors_the_health_line_reads(portal_pilot):
    W, _ = portal_pilot("pilot2")
    ids = set(W.portal_ids())
    assert {f"sensor.{W.T}_state", f"sensor.{W.T}_flica_fetches", f"sensor.{W.T}_charters"} <= ids


# ------------------------------------------------------------------ FW-0042: the new-pairing push text (show only)
def _ha_env():
    jinja2 = pytest.importorskip("jinja2")
    env = jinja2.Environment()

    def strptime(s, fmt, default=None):
        try:
            return datetime.strptime(s, fmt)
        except (TypeError, ValueError):
            return default
    env.globals.update(now=lambda: datetime(2026, 11, 11, 9, 0), strptime=strptime)
    return env


def _new_pairing():
    import yaml
    autos = yaml.safe_load(open(os.path.join(ROOT, "ha", "automations_flight_watcher.yaml"), encoding="utf-8"))
    return next(a for a in autos if a["alias"] == "Flight Watcher new pairing")


EV = {"pairing": "H9101", "start": "14NOV", "end": "16NOV", "dates": "14NOV-16NOV", "captain": "Doe, Jane",
      "depart": "08:00", "arrive": "18:30", "credit": "15:00", "soft": "1:30", "fit": "Fits", "days": 3,
      "layover": "LAX", "source": "pot"}


def _msg(ev):
    a = _new_pairing()
    return _ha_env().from_string(a["actions"][1]["variables"]["msg"]).render(p=ev)


def test_the_push_shows_the_commute_and_the_value_when_known():
    base = "Sa Nov 14 - Mo Nov 16 | Doe\nDep 8:00am - Ret 6:30pm\nCr 15:00 | ST 1:30 | Fits"
    assert _msg(EV) == base  # nothing new without the fields (no smart.json): the text as before
    assert _msg({**EV, "comm": "", "comm_why": "", "value": ""}) == base
    assert _msg({**EV, "comm": "KOA/ITO", "comm_why": "rpt 11-14 08:00, rel 11-16 18:30: KOA in 3 home 19:45; ITO "
                                                       "in 2 home 20:10", "value": 4617}) == (
        base + "\nCommute: KOA/ITO\nValue: 4617")  # a long why stays off the push
    assert _msg({**EV, "comm": "No", "comm_why": "no nonstop home", "value": None}) == base + "\nCommute: No (no nonstop home)"
    assert _msg({**EV, "value": 0}) == base + "\nValue: 0"


def test_the_push_change_silences_nothing_and_pushes_no_one_new():
    a = _new_pairing()
    assert [c["alias"][:24] for c in a["conditions"]] == ["Skip trips touching VAC ", "Skip trips Ryan cannot l"]
    assert "comm" not in json.dumps(a["conditions"]) and "value" not in json.dumps(a["conditions"]).replace("value_template", "")
    assert [s["action"] for s in a["actions"][2]["parallel"]] == ["notify.mobile_app_ryans_iphone",
                                                                  "notify.mobile_app_ryans_iphone_16"]
    assert a["triggers"] == [{"topic": "flight_watcher/event/new_pairing", "trigger": "mqtt"}]
    assert all(s["data"]["message"] == "{{ msg }}" for s in a["actions"][2]["parallel"])
    assert chr(0x2014) not in json.dumps(a)


# ------------------------------------------------------------------ the weather view gone from Ryan's dashboard
def test_the_dashboard_snapshot_has_no_weather_view_and_matches_its_sha():
    path = os.path.join(ROOT, "ha", "dashboard_flight_watcher.json")
    text = open(path, encoding="utf-8").read()
    views = [v.get("path") for v in json.loads(text)["data"]["config"]["views"]]
    assert views == ["watcher", "flight", "details", "recall", "settings"]
    readme = open(os.path.join(ROOT, "ha", "README.md"), encoding="utf-8").read()
    assert hashlib.sha256(text.encode("utf-8")).hexdigest() in readme  # the sha the refresh checked on Pako
    assert "lat=" not in text and "windy" not in text.lower()
    assert os.path.exists(os.path.join(ROOT, "ha", "packages", "flight_watcher_wx.yaml"))  # the wx package stays
    claude = open(os.path.join(ROOT, "CLAUDE.md"), encoding="utf-8").read()
    assert re.search(r"views: watcher, flight \(Working Flight", claude) and "views: watcher, wx" not in claude
