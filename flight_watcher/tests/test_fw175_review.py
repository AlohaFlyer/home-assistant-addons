"""1.7.5 review ("Pause wins"): what an adversarial review found, each on a fake clock with a fake FLICA (never reached).
R1 a Pause turned on and off in the start's first seconds no longer brings back the save's try it cancelled. R2 a
save of the same FLICA details while Pause is on says Pause is on, lifts the block and queues no try. R3 a portal
poll holding a Pause change and a Re-arm answers the Re-arm for the Pause it set. R4 a Pause as the loop enters the
login floor wait leaves the cancel note and ends that wait at once. R5 a Pause landing while a Re-arm's login time is
saved makes no login. P8 Pause on and off during a step-aside for the pilot's own FLICA login keeps the step-aside
to its end (one FLICA session per login). Synthetic details only (u / p, "Doe, Jane")."""
import sys
import time
import types

from test_release_a_flica import mk  # noqa: F401
from test_release_a_review import _cmd, _run_main
from test_fw174_flica_hmac import _refuse, _restart
from test_fw174_review2 import _pilot_up, _save
from test_portal_spool import _put, demo  # noqa: F401

PAUSED_STOPPED_WHY = "nothing to re-arm while paused: turn Pause off, then press Re-arm"
CMD = {"fwp": 1, "pilot": "demo", "ts": 1763600000004, "payload": "PRESS", "session": "5e55105e55105e55"}


def _stopped_pilot(mk, since_login=60):  # noqa: F811
    W = mk("pilot2")
    W.OPTS.update(username="u", password="p")
    W.S["machine"], W.S["note"] = "stopped_unexpected", "x"
    W.S["login_ts"] = W.CLOCK.t - since_login  # 60 s: the next login waits 9 min for the floor
    W.save_state(W.S)
    return W


def _at_start_wait(W, monkeypatch, fire):
    """fire() runs once inside main's 2 s start wait (MQTT and the portal spool are up by then)."""
    real = time.sleep
    seen = {}

    def sl(sec):
        if sec == 2 and not seen and sys._getframe(1).f_code.co_name == "main":
            seen["n"] = 1
            fire()
        return real(sec)
    monkeypatch.setattr(time, "sleep", sl)
    return seen


# ---------------------------------------------------------------- R1: the start's `again` is read after its wait
def test_pause_on_and_off_in_the_starts_first_seconds_keeps_the_saves_try_cancelled(mk, monkeypatch):  # noqa: F811
    W = _pilot_up(mk)
    _refuse(W)
    t_refused = W.S["login_ts"]
    assert _save(W, monkeypatch, {"password": "p", "my_name": "Doe, Jane"}) is True
    W2 = _restart(mk, W, "u", "p")
    seen = {}

    def toggle():
        _cmd(W2, "pause/set", b"ON")
        seen["on"] = (W2.S["note"], "flica_again_at" in W2.S)
        _cmd(W2, "pause/set", b"OFF")
    hit = _at_start_wait(W2, monkeypatch, toggle)

    def script(i):
        if i == 2:
            seen["note"] = W2.S["note"]
        elif i == 4:
            seen["press"] = W2.CLOCK.t
            _cmd(W2, "rearm/press")  # a new Re-arm of his own: that one logs in
    logins, _ = _run_main(W2, monkeypatch, script, login="failed", max_sleeps=10)
    assert hit and seen["on"] == (W2.pause_cancel_note(W2.PAUSE_CANCEL_SAVE), False)
    assert seen["note"] == W2.pause_cancel_note(W2.PAUSE_CANCEL_SAVE)  # said once, no restart note after it
    assert len(logins) == 1 and logins[0] >= seen["press"], logins  # none until the new Re-arm
    assert logins[0] - t_refused >= W2.LOGIN_MIN_GAP_S


def test_pause_on_in_the_starts_first_seconds_still_cancels_the_try(mk, monkeypatch):  # noqa: F811
    W = _pilot_up(mk)
    _refuse(W)
    assert _save(W, monkeypatch, {"password": "p", "my_name": "Doe, Jane"}) is True
    W2 = _restart(mk, W, "u", "p")
    hit = _at_start_wait(W2, monkeypatch, lambda: _cmd(W2, "pause/set", b"ON"))
    logins, _ = _run_main(W2, monkeypatch, lambda i: None, login="failed", max_sleeps=10)
    assert hit and logins == [] and not W2.FLAGS["rearm"]
    assert W2.S["note"] == W2.pause_cancel_note(W2.PAUSE_CANCEL_SAVE) and W2.flica_refused_at() is None


# ---------------------------------------------------------------- R2: a save while Pause is on says so
def test_a_save_with_other_settings_while_paused_lifts_the_block_and_promises_no_try(mk, monkeypatch):  # noqa: F811
    W = _pilot_up(mk)
    _refuse(W)
    t_refused = W.S["login_ts"]
    _cmd(W, "pause/set", b"ON")
    assert _save(W, monkeypatch, {"password": "p", "my_name": "Doe, Jane"}) is True
    assert W.S["settings_last"]["result"] == "saved: my_name; " + W.FLICA_LIFT_PAUSED
    assert "flica_again_at" not in W.S and W.flica_refused_at() is None  # lifted at once, no try queued
    assert not W.FLAGS["rearm"] and W.S["note"] == W.pause_cancel_note(W.PAUSE_CANCEL_SAVE)
    assert W.rearm_answer() == ("", False, PAUSED_STOPPED_WHY)
    W2 = _restart(mk, W, "u", "p")
    seen = {}

    def script(i):
        if i == 1:
            seen["again"], seen["note"] = W2.settings_last_result(), W2.S["note"]
        elif i == 3:
            _cmd(W2, "pause/set", b"OFF")
        elif i == 5:
            seen["press"] = W2.CLOCK.t
            _cmd(W2, "rearm/press")
    logins, _ = _run_main(W2, monkeypatch, script, login="failed", max_sleeps=8)
    assert seen["again"] == "saved: my_name; " + W.FLICA_LIFT_PAUSED + " (Watcher restarted with them)"
    assert seen["note"] == W2.pause_cancel_note(W2.PAUSE_CANCEL_SAVE)
    assert len(logins) == 1 and logins[0] >= seen["press"] and logins[0] - t_refused >= W2.LOGIN_MIN_GAP_S


def test_the_same_details_alone_while_paused_lift_the_block_and_queue_no_try(mk, monkeypatch):  # noqa: F811
    W = _pilot_up(mk)
    _refuse(W)
    _cmd(W, "pause/set", b"ON")
    W.MQ.msgs.clear()
    W.WAKE.clear()
    assert _save(W, monkeypatch, {"username": "u", "password": "p"}) is False  # nothing new: no restart
    res = W.MQ.last(f"{W.T}/settings/state")["result"]
    assert res == "nothing new; " + W.FLICA_LIFT_PAUSED
    assert not W.FLAGS["rearm"] and W.FLAGS.get("rearm_note") is None and "flica_again_at" not in W.S
    assert W.flica_refused_at() is None and W.S["note"] == W.pause_cancel_note(W.PAUSE_CANCEL_SAVE)
    assert W.MQ.last(f"{W.T}/state_attr")["note"] == W.S["note"]  # the note goes out at once
    logins, _ = _run_main(W, monkeypatch, lambda i: None, login="failed", max_sleeps=4)
    assert logins == []


def test_a_save_while_not_paused_still_gives_the_one_more_try(mk, monkeypatch):  # noqa: F811
    W = _pilot_up(mk)
    _refuse(W)
    assert _save(W, monkeypatch, {"username": "u", "password": "p"}) is False
    assert W.MQ.last(f"{W.T}/settings/state")["result"] == "nothing new; FLICA gets one more login try with these details"
    assert W.FLAGS["rearm"] and W.FLAGS["rearm_note"] == W.FLICA_AGAIN_NOTE


# ---------------------------------------------------------------- R3: one portal poll, a Pause change and a Re-arm
def _poll(W, cmds):
    """One spool poll of these portal commands; the broker then hands the republished ones back, in order."""
    ids = [f"00000000c0de{0x300 + n:04x}" for n in range(len(cmds))]
    for cid, (sub, payload) in zip(ids, cmds):
        _put(W, f"{CMD['ts']}-{cid}.json", {**CMD, "id": cid, "sub": sub, "payload": payload})
    W.MQ.raw.msgs.clear()
    W.portal_spool_once()
    res = {r["id"]: r for r in W.EXPORT["results_list"]}
    for t, p, *_ in list(W.MQ.raw.msgs):
        if t in (f"{W.T}/pause/set", f"{W.T}/rearm/press"):
            W.on_message(W.MQ, None, types.SimpleNamespace(topic=t, payload=p.encode() if isinstance(p, str) else p))
    return [res[cid] for cid in ids]


def test_portal_pause_off_then_rearm_in_one_poll_queues_the_login(demo):  # noqa: F811
    W = demo
    W.S.update(machine="stopped_unexpected", note="x")
    W.remember_switch("pause", True)
    off, rearm = _poll(W, [("pause/set", "OFF"), ("rearm/press", "PRESS")])
    assert off["ok"] and not W.FLAGS["pause"]
    assert rearm["ok"] and W.FLAGS["rearm"], rearm


def test_portal_pause_on_then_rearm_in_one_poll_refuses_the_rearm(demo):  # noqa: F811
    W = demo
    W.S.update(machine="stopped_unexpected", note="x")
    W.remember_switch("pause", False)
    on, rearm = _poll(W, [("pause/set", "ON"), ("rearm/press", "PRESS")])
    assert on["ok"] and W.FLAGS["pause"]
    assert (rearm["ok"], rearm.get("why")) == (False, PAUSED_STOPPED_WHY) and not W.FLAGS["rearm"], rearm


# ---------------------------------------------------------------- R4: Pause as the loop enters the floor wait
def test_pause_as_the_loop_reads_the_floor_leaves_the_cancel_note(mk, monkeypatch):  # noqa: F811
    W = _stopped_pilot(mk)
    real = W.login_wait
    hit = {}

    def lw(now=None):
        if W.FLAGS["rearm"] and not hit:
            hit["n"] = 1
            _cmd(W, "pause/set", b"ON")  # paho's thread: after the loop's Pause check, before the wait's note
        return real(now)
    monkeypatch.setattr(W, "login_wait", lw)
    logins, _ = _run_main(W, monkeypatch, lambda i: _cmd(W, "rearm/press") if i == 1 else None, login="ok",
                          max_sleeps=6)
    assert hit and logins == [] and not W.FLAGS["rearm"]
    assert W.S["note"] == W.pause_cancel_note(W.PAUSE_CANCEL_REARM), W.S["note"]


def test_pause_right_after_the_floor_note_ends_the_wait_at_once(mk, monkeypatch):  # noqa: F811
    W = _stopped_pilot(mk)
    real = W.sleep_announced
    seen = {"sleeps": []}

    def announced(sec):
        if W.FLAGS["rearm"] and "cancel" not in seen and "the FLICA login waits until" in W.S["note"]:
            seen["cancel"] = W.CLOCK.t
            _cmd(W, "pause/set", b"ON")  # its wake comes before the wait's sleep starts (and clears it)
        return real(sec)
    monkeypatch.setattr(W, "sleep_announced", announced)

    def script(i):
        seen["sleeps"].append(W.CLOCK.t)
        if i == 1:
            _cmd(W, "rearm/press")
    logins, _ = _run_main(W, monkeypatch, script, login="ok", max_sleeps=5)
    assert "cancel" in seen and logins == []
    assert W.S["note"] == W.pause_cancel_note(W.PAUSE_CANCEL_REARM)
    after = [t for t in seen["sleeps"] if t >= seen["cancel"]]
    assert after[1] - seen["cancel"] <= 1, (after, seen["cancel"])  # not the floor's 9 min
    assert W.MQ.msgs[-1] == (f"{W.T}/next_check", "None") or (f"{W.T}/next_check", "None") in W.MQ.msgs[-4:]


# ---------------------------------------------------------------- R5: Pause while the Re-arm's login time is saved
def test_pause_while_the_rearm_logins_time_is_saved_makes_no_login(mk, monkeypatch):  # noqa: F811
    W = _stopped_pilot(mk, since_login=3600)  # no floor wait: the login would start at once
    t_before = W.S["login_ts"]
    real = W.save_state
    hit = {}

    def ss(s):
        if sys._getframe(1).f_code.co_name == "try_login" and not hit:
            hit["n"] = 1
            W.remember_switch("pause", True)  # paho's thread sets the switch while the login's time is saved
        return real(s)
    monkeypatch.setattr(W, "save_state", ss)
    logins, _ = _run_main(W, monkeypatch, lambda i: _cmd(W, "rearm/press") if i == 1 else None, login="ok",
                          max_sleeps=5)
    assert hit and logins == [], logins
    assert W.S["login_ts"] == t_before and W.load_state()["login_ts"] == t_before  # no login: the floor as it was
    assert not W.FLAGS["rearm"] and W.S["note"] == W.pause_cancel_note(W.PAUSE_CANCEL_REARM)
    assert W.S["machine"] == "stopped_unexpected"


def test_pause_while_the_saves_try_logins_time_is_saved_keeps_the_try_cancelled(mk, monkeypatch):  # noqa: F811
    W = _pilot_up(mk)
    _refuse(W)
    W.CLOCK.t += 900  # past the floor: the try starts at once after the restart
    assert _save(W, monkeypatch, {"password": "p", "my_name": "Doe, Jane"}) is True
    W2 = _restart(mk, W, "u", "p")
    W2.CLOCK.t = W.CLOCK.t
    real = W2.save_state
    hit = {}

    def ss(s):
        if sys._getframe(1).f_code.co_name == "try_login" and not hit:
            hit["n"] = 1
            W2.remember_switch("pause", True)
        return real(s)
    monkeypatch.setattr(W2, "save_state", ss)
    logins, _ = _run_main(W2, monkeypatch, lambda i: None, login="failed", max_sleeps=5)
    assert hit and logins == [] and "flica_again_at" not in W2.load_state()
    assert W2.S["note"] == W2.pause_cancel_note(W2.PAUSE_CANCEL_SAVE)


# ---------------------------------------------------------------- P8: Pause on and off during a step-aside
def test_pause_on_and_off_during_a_pilots_step_aside_keeps_it_to_its_end(mk, monkeypatch):  # noqa: F811
    W = mk("pilot2")
    W.OPTS.update(username="u", password="p")
    end = W.CLOCK.t + 1800
    W.S.update(machine="yielded", note="x", login_ts=W.CLOCK.t - 3600, yield_until=end)
    W.save_state(W.S)
    seen = {}

    def script(i):
        if i == 1:
            _cmd(W, "pause/set", b"ON")
        elif i == 2:
            seen["paused"] = W.S["machine"]
        elif i == 3:
            _cmd(W, "pause/set", b"OFF")
        elif i == 5:
            seen["back"] = W.S["machine"]
    logins, checks = _run_main(W, monkeypatch, script, login="ok", check="ok", max_sleeps=80, step=30)
    assert seen == {"paused": "paused", "back": "yielded"}
    assert [t for t in checks + logins if t < end] == []  # FLICA not reached inside the step-aside
    assert logins and logins[0] >= end  # its end's login, as without the Pause


def test_pause_on_and_off_during_the_admins_step_aside_keeps_it_to_its_end(mk, monkeypatch):  # noqa: F811
    W = mk("")
    end = W.CLOCK.t + 1800
    W.S.update(machine="yielded", note="x", yield_until=end)
    W.save_state(W.S)

    def script(i):
        if i == 1:
            _cmd(W, "pause/set", b"ON")
        elif i == 3:
            _cmd(W, "pause/set", b"OFF")
    logins, checks = _run_main(W, monkeypatch, script, login="ok", check="ok", max_sleeps=80, step=30)
    assert [t for t in checks + logins if t < end] == [] and logins and logins[0] >= end


def test_pause_on_and_off_after_a_step_aside_ended_is_as_before(mk, monkeypatch):  # noqa: F811
    W = mk("pilot2")
    W.OPTS.update(username="u", password="p")
    W.remember_switch("hunt", True)
    W.S.update(machine="hunting", note="x", login_ts=W.CLOCK.t - 3600, last_check_ts=W.CLOCK.t - 30,
               yield_until=W.CLOCK.t - 60)  # an old step-aside, over
    W.save_state(W.S)
    seen = {}

    def script(i):
        if i == 2:
            _cmd(W, "pause/set", b"ON")
        elif i == 4:
            _cmd(W, "pause/set", b"OFF")
            seen["off"] = W.CLOCK.t
    logins, checks = _run_main(W, monkeypatch, script, login="ok", check="ok", max_sleeps=7)
    assert logins == [] and any(t >= seen["off"] for t in checks)  # checks with the session it has
