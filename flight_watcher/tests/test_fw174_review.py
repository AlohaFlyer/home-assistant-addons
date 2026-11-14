"""1.7.4 review: the FLICA refusal record (S flica_refused, an HMAC with <data>/flica_hmac.key) must never lift on a
doubt. A key file replaced or remade under a record (bit rot, a state copy put back, a stop between the new key and
the saved verdict) keeps the pilot blocked until FLICA details are saved again in Settings; a read error on the key
file holds the block and keeps the key; the bare sha256 the migration replaced is gone from the database files too.
Also: a stale key-lost flag after a rollback, the restart note of a refused pilot, and the same FLICA details saved
together with another change. FLICA is never reached: a fake login answers. Synthetic details only."""
import errno
import glob
import json
import logging
import os
import random
from datetime import datetime, timezone

import pytest

from test_release_a_flica import mk  # noqa: F401
from test_release_a_review import _cmd, _run_main
from test_fw174_flica_hmac import FakeFl, _key_path, _legacy, _mac, _refuse, _restart, _saved

LOST_WHY = ("nothing to re-arm: FLICA's refusal on record can no longer be checked; save your FLICA details on "
            "Settings again")
SAVE_AGAIN = "save your FLICA details on the Settings tab again"


def _pilot_up(mk):  # noqa: F811
    """_run_main's details (u / p) on a pilot instance."""
    W = mk("pilot2")
    W.OPTS.update(username="u", password="p")
    return W


def _presses(W):
    return lambda i: _cmd(W, "rearm/press")


class LoadErr(FakeFl):
    login_error = "TimeoutError"  # FLICA did not answer: no refusal


# ---------------------------------------------------------------- a key that is not the record's
def test_a_replaced_key_file_keeps_the_block_and_rearm_logs_in_no_more(mk, monkeypatch, caplog):  # noqa: F811
    W = _pilot_up(mk)
    rec = _refuse(W)
    with open(_key_path(W), "wb") as f:  # 32 other bytes: bit rot, or a folder whose key was remade since
        f.write(os.urandom(32))
    W2 = _restart(mk, W, "u", "p")
    W2.CLOCK.t += 700  # past the 10 min login floor: only the block can stop the login
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        logins, _ = _run_main(W2, monkeypatch, _presses(W2), login="failed", max_sleeps=10)
    assert logins == []  # never one more login with details FLICA refused
    assert W2.S["flica_key_lost"] == rec["at"] and "flica_refused" not in W2.S
    assert "does not match this instance's block key" in caplog.text
    assert SAVE_AGAIN in W2.S["note"] and W2.rearm_answer()[1:] == (False, LOST_WHY)
    assert _saved(W2, monkeypatch, "u", "p", ("u", "p")) is False and W2.FLAGS["rearm"]  # a save: one more try


def test_a_state_copy_put_back_onto_a_remade_key_keeps_the_block(mk, monkeypatch):  # noqa: F811
    W = _pilot_up(mk)
    _refuse(W)
    W.save_state(W.S)
    old = json.loads(json.dumps(W.load_state()))  # a copy of the state: the record keyed with the first key
    os.unlink(_key_path(W))  # the key lost
    W2 = _restart(mk, W, "u", "p")
    W2.flica_key_start()  # a second key, the key-lost rule
    assert W2.S.get("flica_key_lost")
    assert W2.try_login(FakeFl("ok"), "test") is True and "flica_key_lost" not in W2.S
    W2.S.clear()
    W2.S.update(old)  # the old state put back by hand; the key file holds the second key
    W3 = _restart(mk, W2, "u", "p")
    W3.CLOCK.t += 700
    logins, _ = _run_main(W3, monkeypatch, _presses(W3), login="failed", max_sleeps=10)
    assert logins == [] and W3.S.get("flica_key_lost") == old["flica_refused"]["at"]


class Killed(BaseException):
    """The container stopped (a kill, a power cut) at that very point."""


def test_a_stop_between_the_new_key_and_the_saved_verdict_keeps_the_block(mk, monkeypatch):  # noqa: F811
    W = _pilot_up(mk)
    rec = _refuse(W)
    W.save_state(W.S)
    os.unlink(_key_path(W))  # the key lost with a refusal on record
    W2 = _restart(mk, W, "u", "p")
    real = W2._key_file_make

    def made_then_killed(*a, **k):
        real(*a, **k)  # the new key reached the disk...
        raise Killed()  # ...and nothing after it ran
    monkeypatch.setattr(W2, "_key_file_make", made_then_killed)
    with pytest.raises(Killed):
        W2.flica_key_start()
    assert os.path.exists(_key_path(W2))
    saved = W2.load_state()  # the verdict reached the disk before the new key did
    assert saved["flica_key_lost"] == rec["at"] and "flica_refused" not in saved
    W3 = mk("pilot2")  # the next start, on the state as it was saved
    W3.S.update(W3.load_state())
    W3.OPTS.update(username="u", password="p")
    W3.CLOCK.t += 700
    logins, _ = _run_main(W3, monkeypatch, _presses(W3), login="failed", max_sleeps=10)
    assert logins == [] and W3.S["flica_key_lost"] == rec["at"]


# ---------------------------------------------------------------- a read error is not a lost key
def test_a_read_error_on_the_key_file_keeps_the_key_and_the_block(mk, monkeypatch, caplog):  # noqa: F811
    W = _pilot_up(mk)
    rec = _refuse(W)
    key = open(_key_path(W), "rb").read()
    W2 = _restart(mk, W, "u", "p")
    real_open = os.open
    bad = {"n": 2}

    def flaky(path, flags, *a, **k):
        if path == W2.FL_KEY_FILE and bad["n"]:
            bad["n"] -= 1
            raise OSError(errno.EMFILE, "Too many open files")  # synthetic, transient
        return real_open(path, flags, *a, **k)
    monkeypatch.setattr(os, "open", flaky)
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        W2.flica_key_start()  # the first read fails: the block holds, the key is kept
        assert W2.flica_refused_at() == rec["at"] and W2.rearm_answer()[1] is False  # the second fails too
    assert open(_key_path(W2), "rb").read() == key and W2.S["flica_refused"] == rec
    assert "flica_key_lost" not in W2.S and "could not be read" in caplog.text
    assert W2.flica_refused_at() == rec["at"] and W2.S["flica_refused"] == rec  # the error passed: the same key
    assert W2._FLK["key"] == key and "flica_key_lost" not in W2.S


def test_a_crewtrac_key_read_error_keeps_the_crewtrac_key(portal_pilot, monkeypatch):
    A, _ = portal_pilot("", portal=False)
    A.OPTS["ctweb_username"], A.OPTS["ctweb_password"] = "10001", "pw-synthetic-wrong"
    A.crewtrac_state()
    key = open(A.CT_KEY_FILE, "rb").read()
    A._CTK["key"] = None  # the next start
    real_open = os.open

    def flaky(path, flags, *a, **k):
        if path == A.CT_KEY_FILE:
            raise OSError(errno.EIO, "Input/output error")  # synthetic
        return real_open(path, flags, *a, **k)
    monkeypatch.setattr(os, "open", flaky)
    with pytest.raises(OSError):
        A.crewtrac_key()
    assert set(A.crewtrac_info()) == {"state", "at", "next_try"}  # the charters sensor still goes out
    monkeypatch.setattr(os, "open", real_open)
    assert open(A.CT_KEY_FILE, "rb").read() == key and A.crewtrac_key() == key


def test_a_crewtrac_key_lost_verdict_is_saved_before_the_new_key(portal_pilot, monkeypatch):
    def admin():
        A, _ = portal_pilot("", portal=False)
        A.OPTS["ctweb_username"], A.OPTS["ctweb_password"] = "10001", "pw-synthetic-wrong"
        return A
    import charter as CH
    A = admin()
    A.crewtrac_failed(dict(A.crewtrac_state()), CH.REFUSED)
    os.unlink(A.CT_KEY_FILE)
    A2 = admin()
    real = A2._key_file_make

    def made_then_killed(*a, **k):
        real(*a, **k)
        raise Killed()
    monkeypatch.setattr(A2, "_key_file_make", made_then_killed)
    with pytest.raises(Killed):
        A2.crewtrac_key()
    A3 = admin()
    assert A3.DB.get(A3.CT_KEY_LOST) and A3.crewtrac_stopped(A3.crewtrac_state())


# ---------------------------------------------------------------- the bare sha256 gone from the files
@pytest.mark.parametrize("kind", ["kept", "dropped"])
def test_the_bare_sha256_is_gone_from_the_database_files_after_the_migration(mk, kind):  # noqa: F811
    W = _pilot_up(mk)
    pw = "p" if kind == "kept" else "an older made-up pw"
    leg = _legacy("u", pw)
    W.S["machine"], W.S["note"] = "stopped_login_failed", "x"
    W.S["flica_refused"] = {"hash": leg, "at": W.CLOCK.t - 900}  # as 1.7.3 kept it, for weeks
    W.S["pad"] = "z" * 6000  # a state of a realistic size
    rnd = random.Random(7)
    for i in range(600):  # 1.7.3's life: the state saved often, its size changing, checkpoints running
        W.S["note"] = "n" * rnd.randint(0, 3000) + str(i)
        W.save_state(W.S)
        if i % 7 == 0:
            W.DB.put(f"other{i % 13}", {"v": "q" * rnd.randint(0, 5000)})
    W.DB.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    W.S["note"] = "x"
    W.save_state(W.S)
    W.DB.db.close()  # the 1.7.3 process ended
    W2 = mk("pilot2")  # the first 1.7.4 start
    W2.S.update(W2.load_state())
    W2.OPTS.update(username="u", password="p")
    W2.flica_key_start()
    for i in range(20):  # and it runs on
        W2.S["note"] = f"after {i}"
        W2.save_state(W2.S)
    if kind == "kept":
        assert W2.S["flica_refused"]["hash"] == _mac(open(_key_path(W2), "rb").read(), "u", "p")
    else:
        assert "flica_refused" not in W2.S
    hits = [os.path.basename(p) for p in glob.glob(os.path.join(W2.DATA, "watcher.db*"))
            if leg.encode() in open(p, "rb").read()]
    assert hits == []  # no file in the data folder holds it any more
    assert W2.load_state()["pad"] == "z" * 6000 and W2.DB.get("other0") is not None  # nothing else lost


# ---------------------------------------------------------------- the safety paths, each pinned
def test_a_restart_with_a_lost_key_and_no_press_says_save_again(mk, monkeypatch):  # noqa: F811
    W = _pilot_up(mk)
    _refuse(W)
    os.unlink(_key_path(W))
    W2 = _restart(mk, W, "u", "p")
    logins, _ = _run_main(W2, monkeypatch, lambda i: None, login="failed", max_sleeps=3)
    assert logins == []
    assert SAVE_AGAIN in W2.S["note"] and "press Re-arm" not in W2.S["note"]


@pytest.mark.parametrize("first", [True, False])
def test_no_key_can_be_had_with_a_record_on_file_the_block_holds(mk, monkeypatch, first):  # noqa: F811
    W = _pilot_up(mk)
    if first:  # the first 1.7.4 start on a read-only data folder: 1.7.3's record
        at = W.CLOCK.t - 900
        W.S["machine"], W.S["note"] = "stopped_login_failed", "x"
        W.S["flica_refused"] = {"hash": _legacy("u", "p"), "at": at}
        W.save_state(W.S)
        W2 = W
    else:  # a later start, the key lost
        at = _refuse(W)["at"]
        os.unlink(_key_path(W))
        W2 = _restart(mk, W, "u", "p")

    def boom(*a, **k):
        raise PermissionError("synthetic: the data folder is read-only")
    monkeypatch.setattr(W2, "_key_file_make", boom)
    W2.CLOCK.t += 700
    assert W2.flica_refused_at() == at and W2.flica_refused_at() == at  # asked twice: it holds each time
    logins, _ = _run_main(W2, monkeypatch, _presses(W2), login="failed", max_sleeps=10)
    assert logins == [] and W2.rearm_answer()[1] is False


def test_a_login_clears_the_key_lost_block(mk):  # noqa: F811
    W = _pilot_up(mk)
    _refuse(W)
    os.unlink(_key_path(W))
    W2 = _restart(mk, W, "u", "p")
    W2.flica_key_start()
    assert W2.S.get("flica_key_lost") and W2.rearm_answer()[1:] == (False, LOST_WHY)
    W2.FLAGS["rearm"] = False
    assert W2.try_login(FakeFl("ok"), "re-arm") is True  # the try a save gave: FLICA let it through
    assert "flica_key_lost" not in W2.S
    assert W2.try_login(LoadErr(), "backoff") is False and W2.S["machine"] == "stopped_login_failed"
    assert W2.flica_refused_at() is None and W2.rearm_answer()[1] is True  # a load error is no refusal


def test_a_refusal_replaces_a_key_lost_flag_with_its_own_record(mk):  # noqa: F811
    W = _pilot_up(mk)
    W.S["flica_hmac_v"], W.S["flica_key_lost"] = 1, W.CLOCK.t - 3600
    W.CLOCK.t += 5
    rec = _refuse(W)
    assert "flica_key_lost" not in W.S and W.flica_refused_at() == rec["at"] == W.CLOCK.t
    assert W.S["note"].startswith("FLICA refused these login details at ")


# ---------------------------------------------------------------- after a rollback to 1.7.3 and back
def _iso(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat()


@pytest.mark.parametrize("how", ["logged_in_since", "not_stopped"])
def test_a_stale_key_lost_flag_from_before_a_rollback_is_dropped(mk, caplog, how):  # noqa: F811
    W = _pilot_up(mk)
    W.S["flica_hmac_v"], W.S["flica_key_lost"] = 1, W.CLOCK.t - 86400  # 1.7.4's, which 1.7.3 does not know
    if how == "logged_in_since":  # 1.7.3 logged in, then a login failed on a load error
        W.S["last_login_ok"] = _iso(W.CLOCK.t - 3600)
        W.S["machine"], W.S["note"] = "stopped_login_failed", "one login attempt failed (backoff step 1)"
    else:  # 1.7.3 logged in and runs: no refusal on record, not stopped by one
        W.S["machine"] = "idle"
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        W.flica_key_start()
    assert "flica_key_lost" not in W.S and "flica_key_lost" not in W.load_state()
    assert "key-lost block from before" in caplog.text
    if how == "not_stopped":
        assert W.try_login(LoadErr(), "backoff") is False
    assert W.S["machine"] == "stopped_login_failed" and W.rearm_answer()[1] is True


def test_the_start_drops_a_stale_key_lost_flag_before_the_watch_runs(mk, monkeypatch):  # noqa: F811
    W = _pilot_up(mk)
    W.S["flica_hmac_v"], W.S["flica_key_lost"] = 1, W.CLOCK.t - 86400  # back from 1.7.3, which logged in and ran
    W.S["machine"] = "hunting"
    W.save_state(W.S)
    logins, checks = _run_main(W, monkeypatch, lambda i: None, max_sleeps=2)
    assert logins == [] and checks and "flica_key_lost" not in W.S and "flica_key_lost" not in W.load_state()


def test_a_key_lost_flag_still_in_force_is_kept_at_the_start(mk):  # noqa: F811
    W = _pilot_up(mk)
    W.S["flica_hmac_v"], W.S["flica_key_lost"] = 1, W.CLOCK.t - 60
    W.S["last_login_ok"] = _iso(W.CLOCK.t - 86400)  # the last good login came before that refusal
    W.S["machine"] = "stopped_login_failed"
    W.flica_key_start()
    assert W.S["flica_key_lost"] == W.CLOCK.t - 60 and W.rearm_answer()[1:] == (False, LOST_WHY)


def test_a_1_7_3_refusal_after_a_rollback_stands_for_an_older_key_lost_flag(mk):  # noqa: F811
    W = _pilot_up(mk)
    _refuse(W)
    key = open(_key_path(W), "rb").read()
    lost = W.CLOCK.t - 7200
    W.S["flica_key_lost"] = lost  # left from before the rollback
    W.S["flica_refused"] = {"hash": _legacy("u", "p"), "at": W.CLOCK.t}  # 1.7.3's Re-arm, refused again
    W2 = _restart(mk, W, "u", "p")
    W2.flica_key_start()
    assert W2.S["flica_refused"]["hash"] == _mac(key, "u", "p") and "flica_key_lost" not in W2.S
    assert W2.flica_refused_at() == W.CLOCK.t and W2.rearm_answer()[1] is False
    assert W2.flica_refused_note(W.CLOCK.t).startswith("FLICA refused these login details at ")


# ---------------------------------------------------------------- the restart note of a stopped pilot
def test_a_restart_of_a_refused_pilot_never_says_press_rearm(mk, monkeypatch):  # noqa: F811
    W = _pilot_up(mk)
    _refuse(W)
    for _ in range(2):
        W = _restart(mk, W, "u", "p")
        _run_main(W, monkeypatch, lambda i: None, login="failed", max_sleeps=2)
    assert W.rearm_answer()[1] is False
    assert "press Re-arm" not in W.S["note"] and W.S["note"].startswith("FLICA refused these login details at ")


def test_the_restart_suffix_is_said_once(mk, monkeypatch):  # noqa: F811
    W = _pilot_up(mk)
    W.S["machine"], W.S["note"] = "stopped_unexpected", "FLICA asked for captcha/MFA/password change during login"
    for _ in range(3):
        W = _restart(mk, W, "u", "p")
        _run_main(W, monkeypatch, lambda i: None, login="failed", max_sleeps=2)
    assert W.S["note"] == ("FLICA asked for captcha/MFA/password change during login (still stopped after restart, "
                           "press Re-arm)")


# ---------------------------------------------------------------- the same details saved with another change
@pytest.mark.parametrize("lost", [False, True])
def test_the_same_flica_details_saved_with_another_change_give_one_more_try(mk, monkeypatch, lost):  # noqa: F811
    W = _pilot_up(mk)
    _refuse(W)
    if lost:  # the key-lost note asks for exactly this save ("the same ones or new ones")
        os.unlink(_key_path(W))
        W = _restart(mk, W, "u", "p")
        W.flica_key_start()
        assert W.S.get("flica_key_lost")
    monkeypatch.setattr(W, "restart_later", lambda: None)
    json.dump({"username": "u", "password": "p"}, open(W.CREDS_FILE, "w"))
    W.FLAGS["rearm"] = False
    W.WAKE.clear()
    assert W.settings_cmd(json.dumps({"username": "u", "password": "p", "my_name": "Doe, Jane"})) is True
    assert W.flica_refused_at() is None and "flica_key_lost" not in W.S
    res = W.S["settings_last"]["result"]
    assert res.startswith("saved: my_name") and "FLICA gets one more login try with these details" in res
    assert not W.FLAGS["rearm"] and not W.WAKE.is_set()  # nothing logs in before the restart cuts it short
    W2 = _restart(mk, W, "u", "p")  # the restart the save asked for, 2 s later
    logins, _ = _run_main(W2, monkeypatch, lambda i: None, login="failed", max_sleeps=10)
    assert logins == [W.S["login_ts"] + W.LOGIN_MIN_GAP_S]  # one more try after it, Re-arm's path and its floor
    assert W2.flica_refused_at() is not None and W2.S["note"].startswith("FLICA refused these login details at ")
