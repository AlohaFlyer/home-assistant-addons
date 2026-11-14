"""1.7.5 second review ("Pause wins"), each on a fake clock with a fake FLICA (never reached). G1 Pause gives up a FLICA
login whose login page still waits in the gate (a pilot's budget, the host's cap, the pacing): Re-arm's, a back-off's.
G2 a pilot's login floor counts from when FLICA is reached, not from before that gate wait. P8 backed out (no yes from
Ryan): an un-pause during a step-aside goes on as in 1.7.4 (the admin logs in at once, a pilot checks with the session
he has). R3b a portal poll holding Pause off and a Re-arm, or a Pause change and a Check now, answers for the Pause it
set. C1 the clock card offers no Re-arm while Pause is on. Synthetic details only (u / p, "Doe, Jane")."""
import contextlib
import json
import sys
import time
import types

import pytest

from test_release_a_flica import mk  # noqa: F401
from test_release_a_review import Stop, _cmd
from test_portal_spool import _put, demo  # noqa: F401

CMD = {"fwp": 1, "pilot": "demo", "ts": 1763600000004, "payload": "PRESS", "session": "5e55105e55105e55"}


def _run_main_gated(W, monkeypatch, script, check=None, max_sleeps=60):
    """The real main() with a fake browser whose login goes through the real Flica._load (the gate and gate_abort), as
    Flica.login does. Returns (logins, checks): (clock time, Pause) when each login page passed the gate (FLICA
    reached), and the clock time of each check start."""
    monkeypatch.setenv("FLIGHT_WATCHER_WEB", "0")
    W.OPTS.update(username="u", password="p")
    logins, checks = [], []
    real_load = W.Flica._load

    class FakeFlica:
        def __init__(self, pw):
            self.login_error = None

        def login(self):
            real_load(self)  # the login page
            logins.append((W.CLOCK.t, W.FLAGS["pause"]))
            real_load(self)  # its submit
            return "ok"

    def fake_check(fl):
        checks.append(W.CLOCK.t)
        W.S["last_check_ts"] = W.CLOCK.t
        return check() if callable(check) else (check or "ok")
    for f in ("migrate_swap_mode", "enforce_role", "captures_cleanup", "start_upload_janitor", "portal_start",
              "finds_files_cleanup", "publish_finds", "publish_blocked", "publish_tradeboard", "publish_own_trips",
              "publish_working_flight", "publish_trade", "publish_charters", "publish_improved", "publish_tickets",
              "publish_crew_index", "versions_check", "uploads_check", "recall_eval", "crew_split_repair",
              "charter_thread", "ccr_thread", "publish_rules"):
        monkeypatch.setattr(W, f, lambda *a, **k: None)
    monkeypatch.setattr(W, "mqtt_start", lambda: W.MQ)
    monkeypatch.setattr(W, "load_rules", lambda: [])
    monkeypatch.setattr(W, "sync_playwright", lambda: contextlib.nullcontext(None))
    monkeypatch.setattr(W, "Flica", FakeFlica)
    monkeypatch.setattr(W, "check", fake_check)
    W.DB.put("crew_dir_v", 1)
    W.DB.put("crew_fix_v", 1)
    W.DB.put("score_v", 2)
    n = {"i": 0}

    def fake_sleep(sec):
        n["i"] += 1
        if n["i"] > max_sleeps:
            raise Stop("enough")
        W.WAKE.clear()
        script(n["i"])
        due = W.WAKE_DUE["at"]
        if W.WAKE.is_set():
            W.CLOCK.t += 1
        elif due and due - W.CLOCK.t < sec:
            W.CLOCK.t = max(W.CLOCK.t, due)
            W.WAKE_DUE["at"] = 0.0
        else:
            W.CLOCK.t += sec
    monkeypatch.setattr(W, "sleep", fake_sleep)
    try:
        W.main()
    except Stop:
        pass
    return logins, checks


def _budget_full(W):
    """100 of the pilot's own loads in the last hour (gate file): his next load waits about 50 min for his budget."""
    now = W.CLOCK.t
    with open(W.GATE.path, "w") as f:
        json.dump({"v": 1, "last": now - 600, "log": [[now - 700 + i, W.GATE.who] for i in range(100)]}, f)
    assert W.GATE.free_in(1)[0] > 2000


def _pause_in_the_gate(W, monkeypatch):
    """Pause on (its handler) at the first wait chunk of a load in the gate. Returns the clock time it was turned on."""
    real = time.sleep
    hit = {}

    def sl(sec):
        if sys._getframe(1).f_code.co_name == "gate_sleep" and not hit:
            hit["t"] = W.CLOCK.t
            _cmd(W, "pause/set", b"ON")
        return real(sec)
    monkeypatch.setattr(time, "sleep", sl)
    return hit


def _stopped_pilot(mk, since_login=3600):  # noqa: F811
    W = mk("pilot2")
    W.OPTS.update(username="u", password="p")
    W.S["machine"], W.S["note"] = "stopped_unexpected", "x"
    W.S["login_ts"] = W.CLOCK.t - since_login  # past the 10 min floor: Re-arm's login starts at once
    W.save_state(W.S)
    return W


# ---------------------------------------------------------------- G1: Pause gives up a login waiting in the gate
def test_pause_while_a_rearm_login_waits_in_the_gate_makes_no_login(mk, monkeypatch):  # noqa: F811
    W = _stopped_pilot(mk)
    before = W.S["login_ts"]
    _budget_full(W)
    hit = _pause_in_the_gate(W, monkeypatch)
    logins, _ = _run_main_gated(W, monkeypatch, lambda i: _cmd(W, "rearm/press") if i == 1 else None, max_sleeps=6)
    assert hit, "the login never waited in the gate"
    assert W.FLAGS["pause"] and logins == []  # FLICA never reached
    assert W.S["machine"] == "stopped_unexpected" and W.S["note"] == W.pause_cancel_note(W.PAUSE_CANCEL_REARM)
    assert W.S["login_ts"] == before and not W.FLAGS["rearm"]  # no login counts for the floor; nothing left queued


def test_a_rearm_after_the_gate_cancel_logs_in_once_pause_is_off(mk, monkeypatch):  # noqa: F811
    W = _stopped_pilot(mk)
    _budget_full(W)
    hit = _pause_in_the_gate(W, monkeypatch)

    def script(i):
        if i == 1:
            _cmd(W, "rearm/press")
        elif i == 3:
            _cmd(W, "pause/set", b"OFF")
            _cmd(W, "rearm/press")
    logins, _ = _run_main_gated(W, monkeypatch, script, max_sleeps=8)
    assert hit and logins and all(not p for _, p in logins)  # the new Re-arm's login, with Pause off


def test_pause_while_a_back_off_login_waits_in_the_gate_makes_no_login(mk, monkeypatch):  # noqa: F811
    W = mk("pilot2")
    W.OPTS.update(username="u", password="p")
    W.S.update(machine="backoff", note="session expired", relogin_at=W.CLOCK.t + 60, relogin_streak=1,
               login_ts=W.CLOCK.t - 3600)
    W.save_state(W.S)
    before = W.S["login_ts"]
    _budget_full(W)
    hit = _pause_in_the_gate(W, monkeypatch)
    logins, checks = _run_main_gated(W, monkeypatch, lambda i: None, max_sleeps=6)
    assert hit and logins == [] and checks == []
    assert W.S["machine"] == "paused" and W.S["login_ts"] == before  # the given-up login counts for no floor


def test_flica_login_lets_the_gates_abort_through(mk, monkeypatch):  # noqa: F811
    """The real Flica.login: a GateAbort from its login page's wait is no failed login (try_login handles it)."""
    W = mk("pilot2")
    fl = W.Flica.__new__(W.Flica)
    closed = []
    page = types.SimpleNamespace(close=lambda: closed.append(1))
    fl.ctx = None
    fl.browser = types.SimpleNamespace(new_context=lambda **k: types.SimpleNamespace(new_page=lambda: page,
                                                                                     close=lambda: None))

    def abort(self, url=None):
        raise W.GT.GateAbort("Pause is on")
    monkeypatch.setattr(W.Flica, "_load", abort)
    with pytest.raises(W.GT.GateAbort):
        fl.login()
    assert closed and fl.login_error is None


# ---------------------------------------------------------------- G2: the floor counts from FLICA reached
def test_a_login_delayed_by_the_gate_keeps_the_next_login_outside_the_floor(mk, monkeypatch):  # noqa: F811
    W = _stopped_pilot(mk)
    _budget_full(W)
    res = iter(["needs_login"] + ["ok"] * 50)  # the new session is gone at its first check: a back-off login
    logins, checks = _run_main_gated(W, monkeypatch, lambda i: _cmd(W, "rearm/press") if i == 1 else None,
                                     check=lambda: next(res), max_sleeps=12)
    assert len(logins) >= 2, (logins, checks)
    assert logins[1][0] - logins[0][0] >= W.LOGIN_MIN_GAP_S, logins  # two FLICA logins never closer than the floor


def test_the_floor_starts_when_the_login_page_passes_the_gate(mk, monkeypatch):  # noqa: F811
    W = _stopped_pilot(mk)
    _budget_full(W)
    logins, _ = _run_main_gated(W, monkeypatch, lambda i: _cmd(W, "rearm/press") if i == 1 else None, max_sleeps=3)
    # from FLICA reached on, not from before the gate's wait; third review: the login's end, its submit a pace later
    # (a login cut short after its page passed counts from that pass: test_fw175_review3)
    assert logins and logins[0][0] <= W.S["login_ts"] < logins[0][0] + 10


# ---------------------------------------------------------------- P8 backed out: an un-pause during a step-aside
def test_the_admins_unpause_inside_a_long_step_aside_logs_in_at_once(mk, monkeypatch):  # noqa: F811
    """Ryan signed out of FLICA and turned Pause off (the clock card: 'Turn Pause off when you have signed out of
    FLICA'): his login comes at once, as in 1.7.4, not at the step-aside's end (up to 4 h after repeated kills)."""
    from test_release_a_review import _run_main
    W = mk("")
    W.S.update(machine="yielded", note=W.yield_note(4 * 3600), yield_until=W.CLOCK.t + 4 * 3600)
    W.save_state(W.S)
    seen = {}

    def script(i):
        if i == 1:
            _cmd(W, "pause/set", b"ON")
        elif i == 3:
            _cmd(W, "pause/set", b"OFF")
            seen["off"] = W.CLOCK.t
    logins, _ = _run_main(W, monkeypatch, script, login="ok", check="ok", max_sleeps=20, step=60)
    assert logins and logins[0] - seen["off"] < 120, (seen, logins)


def test_a_pilots_unpause_inside_a_step_aside_checks_with_his_session(mk, monkeypatch):  # noqa: F811
    """1.7.4: a pilot's un-pause checks with the session he has (a login follows only if it is gone)."""
    from test_release_a_review import _run_main
    W = mk("pilot2")
    W.OPTS.update(username="u", password="p")
    W.S.update(machine="yielded", note=W.yield_note(7200), login_ts=W.CLOCK.t - 3600, yield_until=W.CLOCK.t + 7200)
    W.save_state(W.S)
    seen = {}

    def script(i):
        if i == 1:
            _cmd(W, "pause/set", b"ON")
        elif i == 3:
            _cmd(W, "pause/set", b"OFF")
            seen["off"] = W.CLOCK.t
    logins, checks = _run_main(W, monkeypatch, script, login="ok", check="ok", max_sleeps=20, step=60)
    assert logins == [] and checks and checks[0] - seen["off"] < 120, (seen, checks)


# ---------------------------------------------------------------- R3b: the poll's own Pause, for Re-arm and Check now
def _poll(W, cmds):
    """One spool poll of these portal commands; the broker then hands the republished ones back, in order."""
    ids = [f"00000000c0de{0x500 + n:04x}" for n in range(len(cmds))]
    for cid, (sub, payload) in zip(ids, cmds):
        _put(W, f"{CMD['ts']}-{cid}.json", {**CMD, "id": cid, "sub": sub, "payload": payload})
    W.MQ.raw.msgs.clear()
    W.portal_spool_once()
    res = {r["id"]: r for r in W.EXPORT["results_list"]}
    for t, p, *_ in list(W.MQ.raw.msgs):
        if t in (f"{W.T}/pause/set", f"{W.T}/rearm/press", f"{W.T}/check_now/press"):
            W.on_message(W.MQ, None, types.SimpleNamespace(topic=t, payload=p.encode() if isinstance(p, str) else p))
    return [res[cid] for cid in ids]


@pytest.mark.parametrize("yield_s", [0, 1800])  # parked from idle, or from a step-aside
def test_a_poll_with_pause_off_then_rearm_while_paused_is_not_told_to_turn_pause_off(demo, yield_s):  # noqa: F811
    W = demo
    W.S.update(machine="paused", note=W.PAUSED_NOTE, yield_until=time.time() + yield_s if yield_s else 0,
               last_check_ts=time.time() - 7200)
    W.remember_switch("pause", True)
    off, rearm = _poll(W, [("pause/set", "OFF"), ("rearm/press", "PRESS")])
    assert off["ok"] and not W.FLAGS["pause"]
    assert (rearm["ok"], rearm["why"]) == (False, W.REARM_UNPAUSED_WHY), rearm  # the un-pause itself starts it again
    assert W.rearm_answer() == ("", False, W.REARM_UNPAUSED_WHY)  # on HA too, before the loop moves


def test_a_poll_with_pause_on_then_check_now_refuses_it_as_paused(demo):  # noqa: F811
    W = demo
    W.S.update(machine="idle", note="", last_check_ts=time.time() - 600)
    W.remember_switch("pause", False)
    W.FLAGS["full"] = False
    on, chk = _poll(W, [("pause/set", "ON"), ("check_now/press", "PRESS")])
    assert on["ok"] and W.FLAGS["pause"]
    assert (chk["ok"], chk["why"]) == (False, "ignored: the Watcher is paused (turn Pause off first)")
    assert not W.FLAGS["full"]


def test_a_poll_with_pause_off_then_check_now_while_paused_takes_it(demo):  # noqa: F811
    W = demo
    W.S.update(machine="paused", note=W.PAUSED_NOTE, yield_until=0, last_check_ts=time.time() - 600)
    W.remember_switch("pause", True)
    W.FLAGS["full"] = False
    off, chk = _poll(W, [("pause/set", "OFF"), ("check_now/press", "PRESS")])
    assert off["ok"] and not W.FLAGS["pause"]
    assert chk["ok"] and W.FLAGS["full"], chk  # the loop's check after the un-pause is the full one asked for


# ---------------------------------------------------------------- C1: the clock card offers no Re-arm while paused
def test_the_clock_card_hides_rearm_while_pause_is_on():
    from test_release_a_cards import CLOCK_JS, _clock_states, _run, _src, _st
    note = "Re-arm's FLICA login was cancelled by Pause; press Re-arm after turning Pause off"
    cases = []
    for name, st, pause in (("stopped_paused", "stopped_unexpected", "on"), ("stopped", "stopped_unexpected", "off"),
                            ("yielded_paused", "yielded", "on"), ("yielded", "yielded", "off")):
        h = _clock_states(st=st)
        h["sensor.flight_watcher_state"] = _st(st, {"note": note, "role": "pilot"})
        h["switch.flight_watcher_pause"] = _st(pause)
        cases.append((name, f"({CLOCK_JS})({json.dumps(h)})"))
    got = _run(cases, _src("clock-card"))
    assert {k: v["rearm"] for k, v in got.items()} == {"stopped_paused": False, "stopped": True,
                                                         "yielded_paused": False, "yielded": True}
    assert got["stopped_paused"]["st"] == "Paused."
