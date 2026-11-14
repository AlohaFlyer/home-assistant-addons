"""1.7.4 second review: the same FLICA details saved together with another change keep the block until the restart
(a Re-arm in the 2 s before it logs in no more), a login cut short still counts for the 10 min floor, the one more try
survives a second restart while it waits and is never called a Re-arm press; CrewTrac (the admin's charter scan): a
key that cannot be read says the scans are held, a save made meanwhile still lifts the key-lost block, two threads
make one key; a failed database scrub is tried again at the next start. FLICA and CrewTrac are never reached: fake
logins answer. Synthetic details only (u / p, "Doe, Jane", 10001)."""
import errno
import glob
import json
import os
import random
import sqlite3
import threading
from datetime import timedelta

import pytest

from test_release_a_flica import mk  # noqa: F401
from test_release_a_review import _cmd, _run_main
from test_fw174_flica_hmac import _legacy, _refuse, _restart

CT_PW = "pw-synthetic-ct"  # synthetic


class Killed(BaseException):
    """os._exit(3) RESTART_DELAY_S after a save: the process ends wherever it is."""


def _pilot_up(mk):  # noqa: F811
    W = mk("pilot2")
    W.OPTS.update(username="u", password="p")
    return W


def _save(W, monkeypatch, payload):
    """A Settings save (creds.json held u / p before); the restart it asks for is left to the test."""
    monkeypatch.setattr(W, "restart_later", lambda: None)
    json.dump({"username": "u", "password": "p"}, open(W.CREDS_FILE, "w"))
    return W.settings_cmd(json.dumps(payload))


def _from_disk(mk, t):  # noqa: F811
    """The next process after a kill: only what was saved (nothing is saved for it at the kill)."""
    W2 = mk("pilot2")
    W2.S.update(W2.load_state())
    W2.OPTS.update(username="u", password="p")
    W2.CLOCK.t = t
    return W2


# ---------------------------------------------------------------- the block holds until the restart
def test_the_block_holds_until_the_restart_the_save_asked_for(mk, monkeypatch):  # noqa: F811
    W = _pilot_up(mk)
    rec = _refuse(W)
    W.CLOCK.t += 900  # the pilot fixes things 15 min after the refusal: past the login floor
    assert _save(W, monkeypatch, {"password": "p", "my_name": "Doe, Jane"}) is True
    assert "FLICA gets one more login try" in W.S["settings_last"]["result"]
    assert W.flica_refused_at() == rec["at"]  # until the restart
    assert W.rearm_answer()[1:] == (False, "nothing to re-arm: the one more FLICA login try runs after the restart")
    assert not W.FLAGS["rearm"] and not W.WAKE.is_set()
    assert W.S["note"] == W.FLICA_AGAIN_NOTE + " after the restart"
    assert W.flica_refused_note(rec["at"]) == W.S["note"]  # a press meanwhile keeps that note


def test_a_rearm_in_the_restart_window_makes_no_second_login(mk, monkeypatch):  # noqa: F811
    W = _pilot_up(mk)
    _refuse(W)
    W.CLOCK.t += 900
    W.save_state(W.S)
    old = []

    def script(i):
        if i == 1:
            assert _save(W, monkeypatch, {"password": "p", "my_name": "Doe, Jane"}) is True
            _cmd(W, "rearm/press")  # within the 2 s before os._exit(3)
        if i >= 2:
            raise Killed()

    def cut_short():
        old.append(W.CLOCK.t)
        raise Killed()  # a FLICA login takes longer than 2 s: the restart ends it
    with pytest.raises(Killed):
        _run_main(W, monkeypatch, script, login=cut_short, max_sleeps=5)
    assert W.S["note"] == W.FLICA_AGAIN_NOTE + " after the restart"
    W2 = _from_disk(mk, W.CLOCK.t + 10)  # run.py starts the child again 10 s later
    new, _ = _run_main(W2, monkeypatch, lambda i: None, login="failed", max_sleeps=10)
    assert old == [] and len(new) == 1  # one save, one FLICA login, after the restart
    assert W2.flica_refused_at() is not None and "flica_again_at" not in W2.S


def test_a_login_cut_short_still_counts_for_the_floor(mk, monkeypatch):  # noqa: F811
    W = _pilot_up(mk)
    W.S["machine"] = "idle"
    W.save_state(W.S)

    class Cut:
        login_error = None

        def login(self):
            raise Killed()
    with pytest.raises(Killed):
        W.try_login(Cut(), "test")
    W2 = _from_disk(mk, W.CLOCK.t + 12)
    assert W2.S["login_ts"] == W.CLOCK.t and W2.login_wait() == W2.LOGIN_MIN_GAP_S - 12


# ---------------------------------------------------------------- the one more try: a second restart, its note
def test_a_second_restart_during_the_wait_keeps_the_one_more_try(mk, monkeypatch):  # noqa: F811
    W = _pilot_up(mk)
    _refuse(W)
    assert _save(W, monkeypatch, {"password": "p", "my_name": "Doe, Jane"}) is True
    W2 = _restart(mk, W, "u", "p")
    _run_main(W2, monkeypatch, lambda i: None, login="failed", max_sleeps=0)  # started, waiting for the floor
    assert "waits until" in W2.S["note"]
    W2.CLOCK.t += 60
    assert _save(W2, monkeypatch, {"my_name": "Doe, Janet"}) is True  # another Settings save (no FLICA details)
    W3 = _restart(mk, W2, "u", "p")
    W3.CLOCK.t = W2.CLOCK.t + 10
    logins, _ = _run_main(W3, monkeypatch, lambda i: None, login="failed", max_sleeps=10)
    assert logins == [W.S["login_ts"] + W.LOGIN_MIN_GAP_S]  # the try runs at the floor
    assert W3.flica_refused_at() is not None and "flica_again_at" not in W3.S  # refused again: blocked again


def test_a_restart_after_the_try_ran_gives_no_other_try(mk, monkeypatch):  # noqa: F811
    W = _pilot_up(mk)
    _refuse(W)
    assert _save(W, monkeypatch, {"password": "p", "my_name": "Doe, Jane"}) is True
    W2 = _restart(mk, W, "u", "p")
    logins, _ = _run_main(W2, monkeypatch, lambda i: None, login="failed", max_sleeps=10)
    assert len(logins) == 1
    W3 = _restart(mk, W2, "u", "p")
    W3.CLOCK.t = W2.CLOCK.t + 30
    logins, _ = _run_main(W3, monkeypatch, lambda i: _cmd(W3, "rearm/press"), login="failed", max_sleeps=10)
    assert logins == [] and W3.S["note"].startswith("FLICA refused these login details at ")


def test_the_one_more_try_after_the_restart_is_not_called_a_rearm_press(mk, monkeypatch):  # noqa: F811
    W = _pilot_up(mk)
    _refuse(W)  # the floor: the try after the restart waits up to 10 min
    assert _save(W, monkeypatch, {"password": "p", "my_name": "Doe, Jane"}) is True
    W2 = _restart(mk, W, "u", "p")
    notes = []
    logins, _ = _run_main(W2, monkeypatch, lambda i: notes.append(W2.S["note"]), login="failed", max_sleeps=10)
    assert len(logins) == 1
    assert notes[0].startswith(W2.FLICA_AGAIN_NOTE + "; the FLICA login waits until "), notes[0]
    assert not any(n.startswith("Re-arm pressed") for n in notes)


def test_the_same_details_saved_alone_wait_with_their_own_note(mk, monkeypatch):  # noqa: F811
    W = _pilot_up(mk)
    _refuse(W)
    notes = []

    def script(i):
        if i == 1:
            assert _save(W, monkeypatch, {"username": "u", "password": "p"}) is False  # nothing new: no restart
        notes.append(W.S["note"])
    logins, _ = _run_main(W, monkeypatch, script, login="failed", max_sleeps=10)
    assert len(logins) == 1
    assert any(n.startswith(W.FLICA_AGAIN_NOTE + "; the FLICA login waits until ") for n in notes), notes
    assert not any(n.startswith("Re-arm pressed") for n in notes)


def test_a_real_rearm_press_is_still_called_one(mk, monkeypatch):  # noqa: F811
    W = _pilot_up(mk)
    W.S["machine"], W.S["note"], W.S["login_ts"] = "stopped_unexpected", "x", W.CLOCK.t - 60
    W.FLAGS["rearm_note"] = "FLICA details saved again: one more login try"  # left from an earlier try
    W.save_state(W.S)
    notes = []

    def script(i):
        if i == 1:
            _cmd(W, "rearm/press")
        notes.append(W.S["note"])
    _run_main(W, monkeypatch, script, login="failed", max_sleeps=4)
    assert any(n.startswith("Re-arm pressed; the FLICA login waits until ") for n in notes), notes


# ---------------------------------------------------------------- CrewTrac: the admin's charter scan
def _admin(portal_pilot):
    A, _ = portal_pilot("", portal=False)
    A.OPTS["ctweb_username"], A.OPTS["ctweb_password"] = "10001", CT_PW
    o = json.load(open(A.OPTIONS_FILE))
    o.update(ctweb_username="10001", ctweb_password=CT_PW)  # the app Configuration tab (synthetic)
    with open(A.OPTIONS_FILE, "w") as f:
        json.dump(o, f)
    return A


def _flaky(monkeypatch, path, n=None):
    """os.open raises EIO for path (n times, or always until st off is set)."""
    real = os.open
    st = {"n": n, "off": False}

    def f(p, flags, *a, **k):
        if p == path and not st["off"] and (st["n"] is None or st["n"] > 0):
            if st["n"] is not None:
                st["n"] -= 1
            raise OSError(errno.EIO, "Input/output error", p)  # synthetic
        return real(p, flags, *a, **k)
    monkeypatch.setattr(os, "open", f)
    return st


def _charters(A):
    m = [x for x in A.MQ.msgs if x[0].endswith("/charters")]
    return json.loads(m[-1][1]) if m else None


def test_a_crewtrac_key_that_cannot_be_read_says_the_scans_are_held(portal_pilot, monkeypatch):
    import charter as CH
    A = _admin(portal_pilot)
    ct = dict(A.crewtrac_state())
    past = A.local_now() - timedelta(hours=9)
    ct.update(state=CH.OK, at=A._hst_iso(past), next_try=A._hst_iso(past + timedelta(seconds=CH.SCAN_EVERY_S)))
    A.DB.put("crewtrac", ct)
    A.DB.put("charter_scan_at", "2026-11-06T00:00:00+00:00")
    A.DB.put("charter_status", "ok: 40 rows, 0 unusual A330, 0 new")
    A._CTK["key"] = None  # the next start
    err = _flaky(monkeypatch, A.CT_KEY_FILE)  # EIO for good (a bad block)
    waits = []
    monkeypatch.setattr(A.CHARTER_WAKE, "wait", lambda t=None: waits.append(t))
    with pytest.raises(OSError):
        A.charter_turn()  # charter_thread logs it and tries again a minute later
    pay = _charters(A)
    assert pay["status"] == A.CT_KEY_HELD_TEXT and pay["status"].startswith("CrewTrac scans held: ")
    assert pay["crewtrac"]["state"] == CH.OUTAGE and pay["crewtrac"]["next_try"] > A._hst_iso(A.local_now())
    assert A.DB.get("charter_status") == "ok: 40 rows, 0 unusual A330, 0 new"  # the record itself is kept
    err["off"] = True
    monkeypatch.setattr(A, "_charter_scan", lambda c: True)
    A.charter_turn()  # the key reads again: the status as kept goes out at once
    assert _charters(A)["status"] == "ok: 40 rows, 0 unusual A330, 0 new"
    assert _charters(A)["crewtrac"]["state"] == CH.OK


def test_a_held_status_from_the_start_is_put_right_by_the_next_charter_turn(portal_pilot, monkeypatch):
    A = _admin(portal_pilot)
    A.crewtrac_state()
    A.DB.put("charter_scan_at", "2026-11-06T00:00:00+00:00")
    A.DB.put("charter_status", "ok: 40 rows, 0 unusual A330, 0 new")
    A._CTK["key"] = None  # the next start
    err = _flaky(monkeypatch, A.CT_KEY_FILE)
    A.publish_charters()  # main, while the key cannot be read
    assert _charters(A)["status"] == A.CT_KEY_HELD_TEXT
    err["off"] = True
    monkeypatch.setattr(A.CHARTER_WAKE, "wait", lambda t=None: None)
    monkeypatch.setattr(A, "_charter_scan", lambda c: True)
    A.charter_turn()  # the charter thread's first turn reads the key
    assert _charters(A)["status"] == "ok: 40 rows, 0 unusual A330, 0 new"


def test_a_crewtrac_save_during_a_read_error_lifts_the_key_lost_block(portal_pilot, monkeypatch):
    import charter as CH
    A = _admin(portal_pilot)
    A.crewtrac_failed(dict(A.crewtrac_state()), CH.REFUSED)
    os.unlink(A.CT_KEY_FILE)
    A._CTK["key"] = None
    A.crewtrac_key()  # the key-lost rule
    assert A.DB.get(A.CT_KEY_LOST)
    A._CTK["key"] = None  # the next start
    err = _flaky(monkeypatch, A.CT_KEY_FILE)  # a read error while the save is made
    assert A.crewtrac_lift() is True  # the save the block waited for needs no key
    err["off"] = True  # the error passed
    assert not A.DB.get(A.CT_KEY_LOST) and not A.crewtrac_stopped(A.crewtrac_state())


def test_two_threads_make_one_crewtrac_key(portal_pilot, monkeypatch):
    A = _admin(portal_pilot)
    A.crewtrac_state()
    os.unlink(A.CT_KEY_FILE)  # the key lost (no refusal on record)
    A._CTK["key"] = None
    real_read, real_make = A._ct_key_read, A._key_file_make
    first_in, go = threading.Event(), threading.Event()
    makes = []

    def read():
        k = real_read()
        if not first_in.is_set():
            first_in.set()
            go.wait(5)  # the first caller holds here, after its read found no key
        return k

    def make(path, prefix):
        makes.append(threading.current_thread().name)
        return real_make(path, prefix)
    monkeypatch.setattr(A, "_ct_key_read", read)
    monkeypatch.setattr(A, "_key_file_make", make)
    got = {}
    t1 = threading.Thread(target=lambda: got.update(t1=A.crewtrac_key()), name="t1")
    t2 = threading.Thread(target=lambda: got.update(t2=A.crewtrac_key()), name="t2")
    t1.start()
    assert first_in.wait(5)
    t2.start()  # paho's thread (a press, a save) while main or the charter thread is in the key-lost path
    t2.join(0.5)
    go.set()
    t1.join(5)
    t2.join(5)
    assert len(makes) == 1 and got["t1"] == got["t2"] == A._CTK["key"] == open(A.CT_KEY_FILE, "rb").read()


# ---------------------------------------------------------------- a failed scrub is tried again
def test_a_scrub_that_failed_is_tried_again_at_the_next_start(mk, monkeypatch):  # noqa: F811
    W = _pilot_up(mk)
    leg = _legacy("u", "p")
    W.S["machine"], W.S["note"] = "stopped_login_failed", "x"
    W.S["flica_refused"] = {"hash": leg, "at": W.CLOCK.t - 900}
    W.S["pad"] = "z" * 6000
    rnd = random.Random(7)
    for i in range(300):
        W.S["note"] = "n" * rnd.randint(0, 3000) + str(i)
        W.save_state(W.S)
    W.DB.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    W.DB.db.close()
    W2 = _from_disk(mk, W.CLOCK.t)  # the first 1.7.4 start: its scrub fails

    def boom():
        raise sqlite3.OperationalError("database or disk is full")
    monkeypatch.setattr(W2.DB, "scrub", boom)
    W2.flica_key_start()
    assert W2.S["flica_refused"]["hash"] != leg and W2.S.get("flica_scrub_due") == 1
    W2.DB.db.close()
    W3 = _from_disk(mk, W.CLOCK.t + 60)  # the next start: the scrub again
    calls = []
    real = W3.DB.scrub
    monkeypatch.setattr(W3.DB, "scrub", lambda: calls.append(1) or real())
    W3.flica_key_start()
    assert calls == [1] and "flica_scrub_due" not in W3.S
    W3.DB.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    hits = [os.path.basename(p) for p in glob.glob(os.path.join(W3.DATA, "watcher.db*"))
            if leg.encode() in open(p, "rb").read()]
    assert hits == []
    W4 = _from_disk(mk, W.CLOCK.t + 120)  # done: no scrub after that
    monkeypatch.setattr(W4.DB, "scrub", lambda: calls.append(2) or True)
    W4.flica_key_start()
    assert calls == [1]


def test_a_scrub_that_could_not_empty_the_wal_is_tried_again(mk, monkeypatch):  # noqa: F811
    W = _pilot_up(mk)
    W.S["machine"], W.S["note"] = "stopped_login_failed", "x"
    W.S["flica_refused"] = {"hash": _legacy("u", "p"), "at": W.CLOCK.t - 900}
    monkeypatch.setattr(W.DB, "scrub", lambda: False)  # the last checkpoint was busy
    W.flica_key_start()
    assert W.S.get("flica_scrub_due") == 1 and W._FLK["key"]
    W2 = _restart(mk, W, "u", "p")
    monkeypatch.setattr(W2.DB, "scrub", lambda: True)
    W2.flica_key_start()
    assert "flica_scrub_due" not in W2.S and "flica_scrub_due" not in W2.load_state()
