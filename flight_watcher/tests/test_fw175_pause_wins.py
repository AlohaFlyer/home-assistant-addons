"""1.7.5 (Ryan, Nov 14: "Pause wins"): Pause on cancels a FLICA login still waiting to run, Re-arm's (a pilot's 10 min
login floor, a back-off) and the one more try a save of the same FLICA details gave (flica_again_at), whether Pause
is turned on during the wait, in the last instant before the login, before the save's restart or found on at a
start. A Re-arm pressed while paused answers ok false and queues nothing; after Pause is off a new Re-arm logs in
(still at the floor). A stopped Watcher stays stopped; a hunting pilot's un-pause checks with the session it has, as
before. The admin (no floor) follows the same Pause rule. FLICA is never reached: a fake login answers, on a fake
clock. Synthetic details only (u / p, "Doe, Jane")."""
import logging

from test_release_a_flica import mk  # noqa: F401
from test_release_a_review import _cmd, _run_main
from test_fw174_flica_hmac import _refuse, _restart
from test_fw174_review2 import _pilot_up, _save

PAUSED_STOPPED_WHY = "nothing to re-arm while paused: turn Pause off, then press Re-arm"


def _stopped_pilot(mk, since_login=60):  # noqa: F811
    W = mk("pilot2")
    W.OPTS.update(username="u", password="p")
    W.S["machine"], W.S["note"] = "stopped_unexpected", "x"
    W.S["login_ts"] = W.CLOCK.t - since_login  # 60 s: the next login waits 9 min for the floor
    W.save_state(W.S)
    return W


def _cancel_lines(caplog):
    return [r.getMessage() for r in caplog.records if "cancelled" in r.getMessage()]


# ---------------------------------------------------------------- Re-arm, then Pause during the floor wait
def test_rearm_then_pause_during_the_floor_wait_makes_no_login_until_a_new_rearm(mk, monkeypatch, caplog):  # noqa: F811
    W = _stopped_pilot(mk)
    t0 = W.S["login_ts"]
    seen = {}

    def script(i):
        if i == 1:
            _cmd(W, "rearm/press")
        elif i == 2:
            seen["wait"] = W.S["note"]
            _cmd(W, "pause/set", b"ON")  # during the floor wait
            seen["note"], seen["rearm"] = W.S["note"], W.FLAGS["rearm"]
        elif i == 4:
            seen["paused_press"] = W.press_answer("rearm/press")
        elif i == 6:
            _cmd(W, "pause/set", b"OFF")
            seen["off"] = W.CLOCK.t
        elif i == 8:
            seen["state_after_off"] = W.S["machine"]
            seen["press"] = W.CLOCK.t
            _cmd(W, "rearm/press")  # a new Re-arm of his own after un-pausing
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        logins, _ = _run_main(W, monkeypatch, script, login="ok", max_sleeps=11)
    assert len(logins) == 1 and logins[0] > seen["press"], logins  # none until the new Re-arm
    assert seen["off"] - t0 > W.LOGIN_MIN_GAP_S  # the floor wait ended long before: still no login then
    assert seen["wait"].startswith("Re-arm pressed; the FLICA login waits until "), seen["wait"]
    assert seen["note"] == W.pause_cancel_note(W.PAUSE_CANCEL_REARM) and seen["rearm"] is False
    assert seen["paused_press"] == (False, PAUSED_STOPPED_WHY)
    assert seen["state_after_off"] == "stopped_unexpected"  # a stopped pilot stays stopped after the un-pause
    assert len(_cancel_lines(caplog)) == 1


def test_a_pilot_in_a_backoff_rearm_then_pause_makes_no_login_and_his_unpause_is_as_before(mk, monkeypatch):  # noqa: F811
    W = mk("pilot2")
    W.OPTS.update(username="u", password="p")
    W.S.update(machine="backoff", note="x", relogin_at=W.CLOCK.t + 1200, relogin_streak=1,
               login_ts=W.CLOCK.t - 60)
    W.save_state(W.S)
    seen = {}

    def script(i):
        if i == 1:
            seen["answer"] = W.rearm_answer()[:2]
            _cmd(W, "rearm/press")  # waits for the back-off and the floor
            _cmd(W, "pause/set", b"ON")
            seen["rearm"] = W.FLAGS["rearm"]
        elif i == 3:
            seen["paused"] = W.S["machine"]
            _cmd(W, "pause/set", b"OFF")
            seen["off"] = W.CLOCK.t
    logins, checks = _run_main(W, monkeypatch, script, login="ok", check="ok", max_sleeps=6)
    assert logins == [] and any(t >= seen["off"] for t in checks)  # un-paused: checks with the session it has
    assert seen["answer"] == ("login", True) and seen["rearm"] is False and seen["paused"] == "paused"


# ---------------------------------------------------------------- the save's one more try, then Pause
def test_the_saves_try_after_the_restart_then_pause_makes_no_login(mk, monkeypatch):  # noqa: F811
    W = _pilot_up(mk)
    _refuse(W)  # the floor: the try after the restart waits up to 10 min
    assert _save(W, monkeypatch, {"password": "p", "my_name": "Doe, Jane"}) is True
    W2 = _restart(mk, W, "u", "p")
    seen = {}

    def script(i):
        if i == 1:
            seen["wait"] = W2.S["note"]
            _cmd(W2, "pause/set", b"ON")
            seen["note"] = W2.S["note"]
            seen["again"] = ("flica_again_at" in W2.S, "flica_again_at" in W2.load_state())
        elif i == 5:
            _cmd(W2, "pause/set", b"OFF")
        elif i == 7:
            seen["press"] = W2.CLOCK.t
            _cmd(W2, "rearm/press")
    logins, _ = _run_main(W2, monkeypatch, script, login="failed", max_sleeps=10)
    assert len(logins) == 1 and logins[0] > seen["press"], logins  # only the Re-arm after the un-pause logs in
    assert seen["again"] == (False, False)  # the try is dropped, on disk too
    assert seen["wait"].startswith(W2.FLICA_AGAIN_NOTE + "; the FLICA login waits until "), seen["wait"]
    assert seen["note"] == W2.pause_cancel_note(W2.PAUSE_CANCEL_SAVE)
    assert W2.flica_refused_at() is not None  # refused again: blocked again, as before


def test_the_same_details_saved_alone_then_pause_make_no_login(mk, monkeypatch):  # noqa: F811
    W = _pilot_up(mk)
    _refuse(W)

    def script(i):
        if i == 1:
            assert _save(W, monkeypatch, {"username": "u", "password": "p"}) is False  # nothing new: no restart
        elif i == 2:
            _cmd(W, "pause/set", b"ON")
    logins, _ = _run_main(W, monkeypatch, script, login="failed", max_sleeps=10)
    assert logins == [] and not W.FLAGS["rearm"] and W.FLAGS["rearm_note"] is None
    assert W.S["note"] == W.pause_cancel_note(W.PAUSE_CANCEL_SAVE)
    assert W.flica_refused_at() is None  # the save's lift stands: a Re-arm after the un-pause may log in


def test_pause_before_the_saves_restart_drops_the_try_and_keeps_its_lift(mk, monkeypatch):  # noqa: F811
    W = _pilot_up(mk)
    _refuse(W)
    assert _save(W, monkeypatch, {"password": "p", "my_name": "Doe, Jane"}) is True
    _cmd(W, "pause/set", b"ON")  # in the 2 s before the restart
    assert "flica_again_at" not in W.S and W.flica_refused_at() is None
    assert W.S["note"] == W.pause_cancel_note(W.PAUSE_CANCEL_SAVE)
    assert W.rearm_answer() == ("", False, PAUSED_STOPPED_WHY)
    W2 = _restart(mk, W, "u", "p")
    seen = {}

    def script(i):
        if i == 3:
            _cmd(W2, "pause/set", b"OFF")
        elif i == 5:
            seen["press"] = W2.CLOCK.t
            _cmd(W2, "rearm/press")
    logins, _ = _run_main(W2, monkeypatch, script, login="failed", max_sleeps=8)
    assert len(logins) == 1 and logins[0] > seen["press"], logins
    assert logins[0] - W.S["login_ts"] >= W.LOGIN_MIN_GAP_S  # still at the floor


def test_pause_found_on_at_start_cancels_the_saves_try(mk, monkeypatch, caplog):  # noqa: F811
    W = _pilot_up(mk)
    _refuse(W)
    _cmd(W, "pause/set", b"ON")  # Pause first: nothing is waiting yet
    assert _save(W, monkeypatch, {"password": "p", "my_name": "Doe, Jane"}) is True
    assert W.S.get("flica_again_at")
    W2 = _restart(mk, W, "u", "p")
    assert W2.FLAGS["pause"]
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        logins, _ = _run_main(W2, monkeypatch, lambda i: None, login="failed", max_sleeps=10)
    assert logins == [] and not W2.FLAGS["rearm"]
    assert "flica_again_at" not in W2.S and "flica_again_at" not in W2.load_state()
    assert W2.S["note"] == W2.pause_cancel_note(W2.PAUSE_CANCEL_SAVE)
    assert W2.flica_refused_at() is None and W2.S["machine"] == "stopped_login_failed"
    assert len(_cancel_lines(caplog)) == 1


# ---------------------------------------------------------------- the last instant, a press while paused
def test_pause_in_the_last_instant_before_the_login_makes_none(mk, monkeypatch):  # noqa: F811
    W = _stopped_pilot(mk, since_login=3600)  # no floor wait: the login would start at once
    real = W.login_deferred
    hit = {"n": 0}

    def deferred(st, base_note=None):
        r = real(st, base_note)
        if not r and W.FLAGS["rearm"]:
            hit["n"] += 1
            W.remember_switch("pause", True)  # paho's thread: the switch is set, its handler has not cancelled yet
        return r
    monkeypatch.setattr(W, "login_deferred", deferred)
    logins, _ = _run_main(W, monkeypatch, lambda i: _cmd(W, "rearm/press") if i == 1 else None, login="ok",
                          max_sleeps=6)
    assert hit["n"] == 1 and logins == [] and not W.FLAGS["rearm"]
    assert W.S["machine"] == "stopped_unexpected" and W.S["note"] == W.pause_cancel_note(W.PAUSE_CANCEL_REARM)


def test_a_rearm_while_paused_answers_ok_false_and_queues_no_login(mk, monkeypatch):  # noqa: F811
    W = _stopped_pilot(mk, since_login=3600)
    _cmd(W, "pause/set", b"ON")
    assert W.rearm_answer() == ("", False, PAUSED_STOPPED_WHY)
    assert W.press_answer("rearm/press") == (False, PAUSED_STOPPED_WHY)  # a portal press is not republished
    _cmd(W, "rearm/press")  # one from Home Assistant
    assert not W.FLAGS["rearm"]
    for st in ("backoff", "yielded"):
        W.S["machine"] = st
        assert W.rearm_answer() == ("", False, "nothing to re-arm while paused: turn Pause off")
    W.S["machine"] = "stopped_unexpected"
    W.save_state(W.S)
    logins, _ = _run_main(W, monkeypatch, lambda i: _cmd(W, "rearm/press"), login="ok", max_sleeps=8)
    assert logins == [] and W.S["machine"] == "stopped_unexpected"


def test_a_rearm_on_refused_details_while_paused_still_says_refused(mk, monkeypatch):  # noqa: F811
    W = _pilot_up(mk)
    _refuse(W)
    _cmd(W, "pause/set", b"ON")
    ok, why = W.rearm_answer()[1:]
    assert ok is False and why == "nothing to re-arm: FLICA refused these login details; save new ones on Settings"


# ---------------------------------------------------------------- what stays as it was
def test_the_unpause_of_a_hunting_pilot_is_unchanged(mk, monkeypatch, caplog):  # noqa: F811
    W = mk("pilot2")
    W.OPTS.update(username="u", password="p")
    W.remember_switch("hunt", True)
    W.S.update(machine="hunting", note="x", login_ts=W.CLOCK.t - 3600, last_check_ts=W.CLOCK.t - 30)
    W.save_state(W.S)
    seen = {}

    def script(i):
        if i == 2:
            _cmd(W, "pause/set", b"ON")
        elif i == 4:
            seen["paused"] = W.S["machine"]
            _cmd(W, "pause/set", b"OFF")
            seen["off"] = W.CLOCK.t
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        logins, checks = _run_main(W, monkeypatch, script, login="ok", check="ok", max_sleeps=7)
    assert seen["paused"] == "paused" and logins == [] and any(t >= seen["off"] for t in checks)
    assert _cancel_lines(caplog) == []  # nothing was waiting: nothing cancelled


def test_the_admins_rearm_then_pause_makes_no_login(mk, monkeypatch, caplog):  # noqa: F811
    W = mk("")
    W.S["machine"], W.S["note"] = "stopped_unexpected", "x"
    W.save_state(W.S)
    seen = {}

    def script(i):
        if i == 1:
            _cmd(W, "rearm/press")
            _cmd(W, "pause/set", b"ON")  # before the loop reaches its login (the admin has no floor)
            seen["note"] = W.S["note"]
        elif i == 3:
            seen["answer"] = W.rearm_answer()
            _cmd(W, "rearm/press")
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        logins, _ = _run_main(W, monkeypatch, script, login="ok", max_sleeps=6)
    assert logins == [] and W.S["machine"] == "stopped_unexpected" and not W.FLAGS["rearm"]
    assert seen["note"] == W.pause_cancel_note(W.PAUSE_CANCEL_REARM)
    assert seen["answer"] == ("", False, PAUSED_STOPPED_WHY)
    assert len(_cancel_lines(caplog)) == 1


def test_the_admins_rearm_in_the_last_instant_makes_none(mk, monkeypatch):  # noqa: F811
    W = mk("")
    W.S["machine"], W.S["note"] = "stopped_unexpected", "x"
    W.save_state(W.S)
    real = W.login_deferred

    def deferred(st, base_note=None):
        r = real(st, base_note)  # the admin never waits
        if not r and W.FLAGS["rearm"]:
            W.remember_switch("pause", True)
        return r
    monkeypatch.setattr(W, "login_deferred", deferred)
    logins, _ = _run_main(W, monkeypatch, lambda i: _cmd(W, "rearm/press") if i == 1 else None, login="ok",
                          max_sleeps=5)
    assert logins == [] and W.S["note"] == W.pause_cancel_note(W.PAUSE_CANCEL_REARM)
