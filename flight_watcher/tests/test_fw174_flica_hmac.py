"""1.7.4: a pilot's FLICA refusal record (S flica_refused) is keyed with an HMAC-SHA256 of the instance's own random
key (<data>/flica_hmac.key, 32 bytes, 0600, read with O_NOFOLLOW), never a bare sha256 of the details any more (anyone
who could read the state could test password guesses against that offline), as CrewTrac's since 1.7.2
(test_fw172_rev3.py). The first 1.7.4 start re-keys the 1.7.3 record of the details in use and drops any other; a key
lost later with a refusal on record keeps the pilot blocked until FLICA details are saved again in Settings; the admin
has no block and makes no key. FLICA is never reached: a fake login answers. Synthetic details only."""
import hashlib
import hmac
import json
import logging
import os
import stat

import pytest

from test_release_a_flica import mk  # noqa: F401
from test_release_a_review import _cmd, _run_main

USER, PW = "doej2", "made-up pw 1"  # synthetic
KEYNAME = "flica_hmac.key"


def _legacy(u, p):
    """What 1.6.2 to 1.7.3 stored: a bare sha256 anyone can test a guess against."""
    return hashlib.sha256(json.dumps(["flica", u, p]).encode()).hexdigest()


def _mac(key, u, p):
    return hmac.new(key, json.dumps(["flica", u, p]).encode(), hashlib.sha256).hexdigest()


def _key_path(W):
    return os.path.join(W.DATA, KEYNAME)


class FakeFl:
    """Flica.login's answers: 'failed' with no load error is FLICA's form coming back (a refusal)."""
    login_error = None

    def __init__(self, res="failed"):
        self.res = res

    def login(self):
        return self.res


def _pilot(mk, user=USER, pw=PW):  # noqa: F811
    W = mk("pilot2")
    W.OPTS.update(username=user, password=pw)
    return W


def _refuse(W):
    W.S["machine"] = "idle"
    assert W.try_login(FakeFl(), "test") is False
    assert W.S["machine"] == "stopped_login_failed"
    return dict(W.S["flica_refused"])


def _restart(mk, W, user=USER, pw=PW):  # noqa: F811
    """The Watcher started again on the same data folder (its state as saved)."""
    W.save_state(W.S)
    W2 = mk("pilot2")
    W2.S.update(W2.load_state())
    W2.OPTS.update(username=user, password=pw)
    return W2


def _saved(W, monkeypatch, user, pw, on_file=(USER, PW)):
    """A Settings save of these FLICA details (creds.json held on_file before)."""
    monkeypatch.setattr(W, "restart_later", lambda: None)
    json.dump({"username": on_file[0], "password": on_file[1]}, open(W.CREDS_FILE, "w"))
    W.FLAGS["rearm"] = False
    W.WAKE.clear()
    return W.settings_cmd(json.dumps({"username": user, "password": pw}))


# ---------------------------------------------------------------- the record and its key
def test_the_record_is_an_hmac_with_a_private_key_never_a_bare_sha256(mk, caplog):  # noqa: F811
    W = _pilot(mk)
    assert not os.path.exists(_key_path(W))  # made when first needed, not at import
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        rec = _refuse(W)
    st = os.lstat(_key_path(W))
    key = open(_key_path(W), "rb").read()
    assert stat.S_ISREG(st.st_mode) and stat.S_IMODE(st.st_mode) == 0o600 and len(key) == 32
    assert rec["hash"] != _legacy(USER, PW) and rec["hash"] == _mac(key, USER, PW)
    assert set(rec) == {"hash", "at"} and W.S["flica_hmac_v"] == 1
    # without the key file a guess cannot be tested: neither the 1.7.3 way nor with any other key
    for guess in (PW, "password", "made-up pw 2", ""):
        tries = (_legacy(USER, guess), _mac(b"\0" * 32, USER, guess), _mac(os.urandom(32), USER, guess))
        assert rec["hash"] not in tries
    # the key and the password never reach the log or an MQTT message
    assert key.hex() not in caplog.text and PW not in caplog.text
    assert all(key.hex() not in str(p) and PW not in str(p) for _, p in W.MQ.msgs)
    # the block holds; a restart reads the same key and the same record still blocks
    assert W.flica_refused_at() == rec["at"] and W.rearm_answer()[1] is False
    W2 = _restart(mk, W)
    assert open(_key_path(W2), "rb").read() == key and W2.flica_refused_at() == rec["at"]
    assert W2.S["flica_refused"] == rec


def test_the_admin_makes_no_key_and_has_no_block(mk):  # noqa: F811
    W = mk("")
    W.OPTS.update(username=USER, password=PW)
    W.S["machine"] = "idle"
    assert W.try_login(FakeFl(), "test") is False
    assert W.S["machine"] == "stopped_login_failed" and "flica_refused" not in W.S
    assert W.flica_refused_at() is None and W.flica_creds_hash() is None
    assert W.rearm_answer()[1] is True
    assert not os.path.exists(_key_path(W)) and "flica_hmac_v" not in W.S


def test_the_key_is_never_read_through_a_link_and_its_mode_is_put_back(mk, tmp_path):  # noqa: F811
    W = _pilot(mk)
    planted = tmp_path / "planted.key"
    planted.write_bytes(b"k" * 32)
    os.symlink(planted, _key_path(W))
    rec = _refuse(W)
    assert not os.path.islink(_key_path(W)) and planted.read_bytes() == b"k" * 32  # replaced, never written through
    key = open(_key_path(W), "rb").read()
    assert key != b"k" * 32 and rec["hash"] == _mac(key, USER, PW)
    os.chmod(_key_path(W), 0o644)
    W2 = _restart(mk, W)
    assert W2.flica_refused_at() == rec["at"] and stat.S_IMODE(os.stat(_key_path(W2)).st_mode) == 0o600


def test_the_key_is_never_exported_or_published(portal_pilot):
    W, _ = portal_pilot("pilot2")
    assert W.portal_start(threads=False)
    W.OPTS.update(username=USER, password=PW)
    _refuse(W)
    W.portal_export_once(full=True)
    key = open(_key_path(W), "rb").read()
    assert all(key.hex() not in str(p) and PW not in str(p) for _, p, *_ in W.MQ.raw.msgs)
    root = os.path.dirname(W.PORTAL_DIR)
    seen = 0
    for d, _, files in os.walk(root):
        for f in files:
            raw = open(os.path.join(d, f), "rb").read()
            seen += 1
            assert key not in raw and key.hex().encode() not in raw and PW.encode() not in raw
    assert seen  # the export wrote files, and none carries the key


# ---------------------------------------------------------------- the 1.7.4 migration
def test_the_first_start_rekeys_the_1_7_3_record_and_rearm_still_logs_in_no_more(mk, monkeypatch, caplog):  # noqa
    W = mk("pilot2")
    at = W.CLOCK.t - 900
    W.S["machine"], W.S["note"] = "stopped_login_failed", "x"
    W.S["flica_refused"] = {"hash": _legacy("u", "p"), "at": at}  # as 1.7.3 left it (_run_main's details)
    W.save_state(W.S)
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        logins, _ = _run_main(W, monkeypatch, lambda i: _cmd(W, "rearm/press"), login="failed", max_sleeps=10)
    assert logins == []  # the block held through the migration
    key = open(_key_path(W), "rb").read()
    assert W.S["flica_refused"] == {"hash": _mac(key, "u", "p"), "at": at}  # the same refusal, keyed
    assert W.S["flica_hmac_v"] == 1
    assert "FLICA refusal record keyed with this instance's own key (1 kept, 0 dropped)" in caplog.text
    assert caplog.text.count("FLICA refusal record keyed") == 1
    assert _legacy("u", "p") not in json.dumps(W.load_state())  # gone from the stored state too
    assert W.S["note"].startswith("FLICA refused these login details at ") and "Settings tab" in W.S["note"]


def test_the_migration_drops_a_record_it_cannot_rekey(mk, caplog):  # noqa: F811
    W = _pilot(mk)
    W.S["machine"], W.S["note"] = "stopped_login_failed", "x"
    W.S["flica_refused"] = {"hash": _legacy(USER, "an older made-up pw"), "at": W.CLOCK.t - 60}
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        assert W.flica_refused_at() is None  # other details than those in use: no block, as before
    assert "flica_refused" not in W.S and W.S["flica_hmac_v"] == 1
    assert "(0 kept, 1 dropped)" in caplog.text and W.rearm_answer()[1] is True
    assert "flica_refused" not in W.load_state()


def test_a_1_7_3_refusal_after_a_rollback_is_rekeyed_on_the_way_forward(mk):  # noqa: F811
    W = _pilot(mk)
    _refuse(W)
    key = open(_key_path(W), "rb").read()
    W.S["flica_refused"] = {"hash": _legacy(USER, PW), "at": W.CLOCK.t + 5}  # what 1.7.3 writes after a rollback
    W2 = _restart(mk, W)
    assert W2.flica_refused_at() == W.CLOCK.t + 5 and W2.S["flica_refused"]["hash"] == _mac(key, USER, PW)
    assert _legacy(USER, PW) not in json.dumps(W2.load_state())


# ---------------------------------------------------------------- the key lost later
@pytest.mark.parametrize("same", [True, False])
def test_a_lost_key_with_a_refusal_on_record_blocks_until_a_save(mk, monkeypatch, caplog, same):  # noqa: F811
    W = mk("pilot2")
    W.OPTS.update(username="u", password="p")  # _run_main's details
    rec = _refuse(W)
    os.unlink(_key_path(W))  # a restored or wiped data folder
    W2 = _restart(mk, W, "u", "p")
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        logins, _ = _run_main(W2, monkeypatch, lambda i: _cmd(W2, "rearm/press"), login="failed", max_sleeps=10)
    assert logins == []  # never one more login with details FLICA refused
    assert W2.S["flica_key_lost"] == rec["at"] and "flica_refused" not in W2.S
    assert "the FLICA block key was lost with a refusal on record" in caplog.text
    assert "save your FLICA details on the Settings tab again" in W2.S["note"] and "press Re-arm" not in W2.S["note"]
    ok, why = W2.rearm_answer()[1:]
    assert ok is False and "Settings" in why
    W2.OPTS["password"] = "p2"  # whatever details are in use: the old record can no longer be told apart
    assert W2.flica_refused_at() == rec["at"]
    W2.OPTS["password"] = "p"
    if same:  # the same details saved again: one more try (Re-arm's path, the login floor kept)
        assert _saved(W2, monkeypatch, "u", "p", ("u", "p")) is False
        assert W2.FLAGS["rearm"] and W2.WAKE.is_set()
        assert W2.S["note"] == "FLICA details saved again: one more login try"
    else:  # new details: no block, no login floor
        assert _saved(W2, monkeypatch, "u", "p2", ("u", "p")) is True
        assert "login_ts" not in W2.S and W2.S["machine"] == "idle"
    assert "flica_key_lost" not in W2.S and W2.flica_refused_at() is None
    # refused again: a new record keyed with the new key blocks again
    W2.OPTS["password"] = "p" if same else "p2"
    rec2 = _refuse(W2)
    key2 = open(_key_path(W2), "rb").read()
    assert rec2["hash"] == _mac(key2, "u", W2.OPTS["password"]) and W2.flica_refused_at() == rec2["at"]
    assert "flica_key_lost" not in W2.S


def test_a_lost_key_with_no_refusal_on_record_blocks_nothing(mk):  # noqa: F811
    W = _pilot(mk)
    _refuse(W)
    assert W.try_login(FakeFl("ok"), "test") is True and "flica_refused" not in W.S  # a login cleared it
    os.unlink(_key_path(W))
    W2 = _restart(mk, W)
    W2.S["machine"] = "stopped_login_failed"  # a login that failed on a load error (no refusal)
    assert W2.flica_refused_at() is None and "flica_key_lost" not in W2.S and W2.rearm_answer()[1] is True
    rec = _refuse(W2)  # the next refusal makes a new key, silently, and blocks
    assert rec["hash"] == _mac(open(_key_path(W2), "rb").read(), USER, PW) and W2.flica_refused_at() == rec["at"]
    assert "flica_key_lost" not in W2.S


def test_no_key_can_be_made_the_refusal_still_blocks_until_a_save(mk, monkeypatch):  # noqa: F811
    W = _pilot(mk)

    def boom(*a, **k):
        raise PermissionError("synthetic: the data folder is read-only")
    monkeypatch.setattr(W, "_key_file_make", boom)
    rec_at = W.CLOCK.t
    W.S["machine"] = "idle"
    assert W.try_login(FakeFl(), "test") is False
    assert "flica_refused" not in W.S and W.S["flica_key_lost"] == rec_at and W.flica_refused_at() == rec_at
    assert W.rearm_answer()[1] is False and "Settings tab again" in W.S["note"]
    assert _saved(W, monkeypatch, USER, PW) is False and W.FLAGS["rearm"] and "flica_key_lost" not in W.S


# ---------------------------------------------------------------- what stays as it was
def test_same_details_give_one_more_try_and_new_ones_lift_the_block_and_the_floor(mk, monkeypatch):  # noqa: F811
    W = _pilot(mk)
    _refuse(W)
    assert _saved(W, monkeypatch, USER, PW) is False  # the same again: flica_lift
    assert "flica_refused" not in W.S and W.FLAGS["rearm"] and W.WAKE.is_set() and W.S["login_ts"] == W.CLOCK.t
    _refuse(W)
    assert _saved(W, monkeypatch, USER, "made-up pw 2") is True  # new details
    assert "flica_refused" not in W.S and "login_ts" not in W.S and W.S["machine"] == "idle"


def test_rearm_after_a_refusal_makes_no_second_login_and_keeps_an_hmac(mk, monkeypatch):  # noqa: F811
    W = mk("pilot2")
    W.S["machine"], W.S["note"] = "stopped_login_failed", "one login attempt failed (re-arm)"
    logins, _ = _run_main(W, monkeypatch, lambda i: _cmd(W, "rearm/press"), login="failed", max_sleeps=20)
    assert len(logins) == 1  # the first press tries once; FLICA's refusal blocks the rest
    key = open(_key_path(W), "rb").read()
    assert W.S["flica_refused"]["hash"] == _mac(key, "u", "p") != _legacy("u", "p")
    assert W.S["note"].startswith("FLICA refused these login details at ")
