"""1.6.0 (FW-0061): the portal's command spool (PORTAL_CONTRACT.md section 5), driven by the shared fixture
tests/fixtures/portal_contract_v1.json (the same samples the HOM portal's tests use). Every refused class is proven
here; every allowed sub republishes exactly <prefix>/<sub>; the admin never reads a spool. Synthetic data only."""
import json
import os

import pytest

import portal as PT
import roles

HERE = os.path.dirname(os.path.abspath(__file__))
FIX = json.load(open(os.path.join(HERE, "fixtures", "portal_contract_v1.json"), encoding="utf-8"))
SAMPLES = FIX["samples"]["commands"]
T0 = 1763600000.0  # the fixture's seq0, in seconds


def _put(W, name, body, owner=True, mode=0o600):
    d = os.path.join(W.PORTAL_DIR, "in")
    p = os.path.join(d, name)
    raw = body if isinstance(body, bytes) else json.dumps(body).encode()
    with open(p, "wb") as f:
        f.write(raw)
    os.chmod(p, mode)
    if owner and os.geteuid() == 0:
        os.chown(p, PT.PORTAL_UID, PT.PORTAL_GID)
    return p


@pytest.fixture
def demo(portal_pilot):
    W, _ = portal_pilot("demo")
    assert W.portal_start(threads=False)
    W.EXPORT["spool"].now = lambda: T0 + 1
    W.MQ.msgs.clear()
    return W


def _published(W):
    return [(t, p, q, r) for t, p, q, r in W.MQ.msgs if not t.startswith("flight_watcher_demo/event")]


def _batches(samples, n=20):
    """1.7.0: the samples in polls of n (30 commands a minute and 50 results are the spool's caps, not under test)."""
    samples = sorted(samples, key=lambda s: s["name"])
    return [samples[i:i + n] for i in range(0, len(samples), n)]


def test_every_accepted_sample_republishes_exactly_its_sub(demo):
    W = demo
    # 1.7.1 review: a Scan CrewTrac now that starts no scan is answered ok false (press_answer). With F#22 a pilot's
    # Watcher never scans, so even with an old CrewTrac login saved (made up) his press is answered ok false (below)
    W.OPTS.update(ctweb_username="doej", ctweb_password="ct pw")
    for batch in _batches(SAMPLES["accepted"]):
        W.MQ.msgs.clear()
        W.EXPORT["spool"].accepted.clear()
        W.EXPORT["results_list"] = []
        for s in batch:
            _put(W, s["name"], s["cmd"])
        # 1.7.1 (F#22): Scan CrewTrac now passes the spool's checks, but a pilot's Watcher answers it ok false with
        # the reason (his charters are the admin's scan) and does not republish it, like an ignored Check now (F#12)
        taken = [s for s in batch if s["cmd"]["sub"] != "charter_scan/press"]
        assert W.portal_spool_once() == len(taken)
        got = [(t, p, q, r) for t, p, q, r in W.MQ.msgs if t.startswith("flight_watcher_demo/") and q == 1]
        assert got == [(f"flight_watcher_demo/{s['cmd']['sub']}", s["cmd"]["payload"], 1, False) for s in taken]
        assert os.listdir(os.path.join(W.PORTAL_DIR, "in")) == []
        res = {r["id"]: r for r in W.EXPORT["results_list"]}
        assert [res[s["cmd"]["id"]]["ok"] for s in batch] == [s["cmd"]["sub"] != "charter_scan/press" for s in batch]
        assert all(res[s["cmd"]["id"]]["why"] == "ignored: charters come from the admin's CrewTrac scan; this Watcher "
                   "does not log in to CrewTrac" for s in batch if s["cmd"]["sub"] == "charter_scan/press")
    assert {roles.portal_sub(s["cmd"]["sub"]) for s in SAMPLES["accepted"]} == set(roles.PORTAL_CMDS)


def test_every_refused_sample_publishes_nothing(demo):
    W = demo
    for batch in _batches(SAMPLES["refused"]):
        W.EXPORT["results_list"] = []
        for s in batch:
            _put(W, s["name"], s["cmd"])
        assert W.portal_spool_once() == 0
        assert _published(W) == [] and os.listdir(os.path.join(W.PORTAL_DIR, "in")) == []
        res = {r["id"]: r for r in W.EXPORT["results_list"]}
        for s in batch:
            r = res[s["cmd"]["id"]]
            assert r["ok"] is False and r["why"], s
    named = {s["cmd"]["sub"] for s in SAMPLES["refused"] if s["why"] == "sub not allowed"}
    assert set(roles.PORTAL_REFUSED) <= named  # each refused sub is in the fixture and proven here


@pytest.mark.parametrize("sub", roles.PORTAL_REFUSED + roles.NOT_ON_PORTAL + ("anything/else", "rule/x/y/live/set",
                                                                              "rule/A/live/set", "../hunt/set",
                                                                              "hunt/set/"))
def test_each_refused_sub(demo, sub):
    W = demo
    cmd = {"fwp": 1, "id": "00000000000000aa", "pilot": "demo", "ts": int(T0 * 1000), "sub": sub, "payload": "ON",
           "session": "5e55105e55105e55"}
    _put(W, f"{int(T0 * 1000):013d}-00000000000000aa.json", cmd)
    W.portal_spool_once()
    assert _published(W) == [] and W.EXPORT["results_list"][-1]["ok"] is False
    assert "sub not allowed" in W.EXPORT["results_list"][-1]["why"]


def _cmd(n, sub="hunt/set", payload="ON", **over):
    cid = "%016x" % n
    c = {"fwp": 1, "id": cid, "pilot": "demo", "ts": int(T0 * 1000), "sub": sub, "payload": payload,
         "session": "5e55105e55105e55", **over}
    return f"{c['ts'] if isinstance(c['ts'], int) else 0:013d}-{cid}.json", c


def _refused_with(W, why):
    assert _published(W) == []
    return [r["why"] for r in W.EXPORT["results_list"] if not r["ok"] and why in r["why"]]


def test_symlink_fifo_oversize_bad_name_and_dotfile(demo, tmp_path):
    W = demo
    d = os.path.join(W.PORTAL_DIR, "in")
    target = tmp_path / "target.json"
    name, cmd = _cmd(1)
    target.write_text(json.dumps(cmd))
    os.symlink(target, os.path.join(d, name))
    fname, _ = _cmd(2)
    os.mkfifo(os.path.join(d, fname))
    big_name, big = _cmd(3, payload="x" * (64 * 1024))
    _put(W, big_name, big)
    _put(W, "1763600000000-short.json", _cmd(4)[1])
    _put(W, "hunt.json", _cmd(5)[1])
    dot = _put(W, ".1763600000000-0000000000000006.json.tmp", _cmd(6)[1])
    assert W.portal_spool_once() == 0
    assert _published(W) == []
    assert os.listdir(d) == [os.path.basename(dot)]  # the portal's write in progress is left alone
    assert target.exists() and json.loads(target.read_text()) == cmd  # the link went, its target is untouched
    assert W.EXPORT["results_list"] == []  # none of these named an id it could be held to


def test_leftover_dotfiles_never_hold_up_a_command(demo):
    """The portal writes .<file>.tmp, then renames it; each write it abandons (a crash, a full disk) leaves one
    behind, and '.' sorts before every command name. However many there are, the next command is still read on the
    first poll: dotfiles are never in the per-poll cap."""
    W = demo
    W.EXPORT["spool"].now = lambda: T0 + 1  # the dotfiles are dated now (after T0): fresh, so all are kept
    for i in range(W.SPOOL_MAX_PER_POLL + 5):
        _put(W, ".%013d-%016x.json.tmp" % (int(T0 * 1000), i), b"{}")
    name, cmd = _cmd(7, sub="check_now/press", payload="PRESS")
    _put(W, name, cmd)
    assert W.portal_spool_once() == 1
    assert _published(W) == [("flight_watcher_demo/check_now/press", "PRESS", 1, False)]
    left = os.listdir(os.path.join(W.PORTAL_DIR, "in"))
    assert name not in left and len(left) == W.SPOOL_MAX_PER_POLL + 5 and all(n.startswith(".") for n in left)


def test_an_abandoned_dotfile_is_removed_a_fresh_one_kept(demo, tmp_path, caplog):
    import logging
    W = demo
    now = 1800000000.0
    W.EXPORT["spool"].now = lambda: now
    d = os.path.join(W.PORTAL_DIR, "in")
    old = _put(W, ".1763600000000-0000000000000001.json.tmp", b"{}")
    fresh = _put(W, ".1763600000000-0000000000000002.json.tmp", b"{}")
    target = tmp_path / "outside.txt"
    target.write_text("keep")
    link = os.path.join(d, ".link.tmp")
    os.symlink(target, link)
    os.mkdir(os.path.join(d, ".dotdir"))
    os.utime(old, (now - PT.DOT_STALE_S - 1, now - PT.DOT_STALE_S - 1))
    os.utime(fresh, (now - 5, now - 5))
    os.utime(link, (now - 3600, now - 3600), follow_symlinks=False)
    os.utime(os.path.join(d, ".dotdir"), (now - 3600, now - 3600))
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        assert W.portal_spool_once() == 0
        W.portal_spool_once()
    assert sorted(os.listdir(d)) == [".1763600000000-0000000000000002.json.tmp", ".dotdir"]
    assert target.read_text() == "keep"  # the link went, never its target
    assert W.EXPORT["spool"].reaped == 2 and caplog.text.count("temp files the portal left behind") == 1
    assert _published(W) == [] and W.EXPORT["results_list"] == []


def test_wrong_owner(demo):
    W = demo
    name, cmd = _cmd(7)
    _put(W, name, cmd, owner=False)
    W.EXPORT["spool"].expect_uid = os.stat(os.path.join(W.PORTAL_DIR, "in", name)).st_uid + 1
    assert W.portal_spool_once() == 0 and _published(W) == []


def test_wrong_owner_when_root(demo):
    if os.geteuid() != 0:
        pytest.skip("owner check runs as root")
    W = demo
    name, cmd = _cmd(8)
    _put(W, name, cmd, owner=False)  # root-owned, not the portal's
    assert W.EXPORT["spool"].expect_uid == PT.PORTAL_UID
    assert W.portal_spool_once() == 0 and _published(W) == []


@pytest.mark.parametrize("over,why", [
    ({"ts": int((T0 - 301) * 1000)}, "too old"),
    ({"ts": int((T0 + 120) * 1000)}, "too old or clock off"),
    ({"pilot": "james"}, "wrong pilot"),
    ({"fwp": 2}, "unknown fwp"),
    ({"session": "nope"}, "bad session"),
    ({"payload": {"not": "text"}}, "payload is not text"),
    ({"ts": "1763600000000"}, "bad ts"),
])
def test_field_checks(demo, over, why):
    W = demo
    name, cmd = _cmd(9, **over)
    _put(W, f"{int(T0 * 1000):013d}-{cmd['id']}.json", cmd)
    assert W.portal_spool_once() == 0
    assert _refused_with(W, why)


def test_id_must_match_the_name(demo):
    W = demo
    _, cmd = _cmd(10)
    _put(W, f"{int(T0 * 1000):013d}-{'f' * 16}.json", cmd)
    assert W.portal_spool_once() == 0 and _published(W) == [] and W.EXPORT["results_list"] == []


def test_duplicate_id_refused_even_after_a_restart(demo, portal_pilot):
    W = demo
    name, cmd = _cmd(11)
    _put(W, name, cmd)
    assert W.portal_spool_once() == 1
    _put(W, name, cmd)
    assert W.portal_spool_once() == 0 and W.EXPORT["results_list"][-1]["why"] == "duplicate id"
    W2, _ = portal_pilot("demo")  # a restart: the seen ids are kept in /data
    W2.portal_start(threads=False)
    W2.EXPORT["spool"].now = lambda: T0 + 2
    _put(W2, name, cmd)
    assert W2.portal_spool_once() == 0 and W2.EXPORT["results_list"][-1]["why"] == "duplicate id"


def test_thirty_a_minute(demo):
    W = demo
    for n in range(31):
        _put(W, *_cmd(100 + n, sub="check_now/press", payload="PRESS"))
    assert W.portal_spool_once() == 30
    assert W.EXPORT["results_list"][-1] == {"id": "%016x" % 130, "ok": False, "why": "over 30 commands a minute"}
    W.EXPORT["spool"].now = lambda: T0 + 62  # a minute later
    _put(W, *_cmd(200, sub="check_now/press", payload="PRESS", ts=int((T0 + 61) * 1000)))
    assert W.portal_spool_once() == 1


def test_plain_settings_refused_sealed_accepted(demo):
    W = demo
    _put(W, *_cmd(300, sub="settings/set", payload=json.dumps({"username": "doej", "password": "pw-x"})))
    _put(W, *_cmd(301, sub="settings/set", payload=json.dumps({"enc": {"v": 1}, "password": "pw-x"})))
    _put(W, *_cmd(302, sub="settings/set", payload="not json"))
    assert W.portal_spool_once() == 0 and len(_refused_with(W, "settings must be sealed")) == 3
    _put(W, *_cmd(303, sub="settings/set", payload=json.dumps({"enc": {"v": 1, "kid": "x"}})))
    assert W.portal_spool_once() == 1
    assert _published(W)[-1][0] == "flight_watcher_demo/settings/set"


def test_pref_set_bounds_checked_at_the_spool(demo):
    W = demo
    for n, (k, v) in enumerate([("federal_tax_pct", 46), ("state_tax_pct", 1.1), ("longevity_year", 0),
                                ("er_trips", "H9001|2026-11-20"), ("month_offset", 1), ("federal_tax_pct", True)]):
        _put(W, *_cmd(400 + n, sub="pref/set", payload=json.dumps({"key": k, "value": v})))
    assert W.portal_spool_once() == 0 and _published(W) == []
    _put(W, *_cmd(410, sub="pref/set", payload=json.dumps({"key": "federal_tax_pct", "value": 24.5})))
    assert W.portal_spool_once() == 1


def test_the_admin_never_reads_a_spool(portal_pilot, monkeypatch, tmp_path):
    W, _ = portal_pilot("", portal=True)
    started = []
    monkeypatch.setattr(W.threading, "Thread", lambda *a, **k: started.append(k.get("name")) or type(
        "T", (), {"start": lambda self: None})())
    in_dir = tmp_path / "share" / "fw_portal" / "admin" / "in"
    in_dir.mkdir(parents=True)
    name, cmd = _cmd(500)
    (in_dir / name).write_text(json.dumps(cmd))
    assert W.portal_start() is False and started == [] and W.EXPORT["spool"] is None
    assert os.listdir(in_dir) == [name]  # never read, never deleted


def _fds():
    import gc
    gc.collect()  # 1.6.1: an earlier test's watcher module (its SQLite files) closed by the collector is no leak here
    return len(os.listdir("/proc/self/fd"))


def _folder(W, name, files=()):
    p = os.path.join(W.PORTAL_DIR, "in", name)
    os.mkdir(p)
    for f in files:
        open(os.path.join(p, f), "w").write("{}")
    if os.geteuid() == 0:
        os.chown(p, PT.PORTAL_UID, PT.PORTAL_GID)
    return p


def test_a_folder_never_stalls_the_spool_or_leaks_a_descriptor(demo, caplog):
    """Contract 5.2: a folder in in/ is refused. One named like a command (sorted before every later command) once
    raised out of the poll with its fd left open, so no later command was ever read and one fd leaked every second."""
    import logging
    W = demo
    d = os.path.join(W.PORTAL_DIR, "in")
    empty = _folder(W, f"{int(T0 * 1000) - 2:013d}-00000000000000aa.json")
    full = _folder(W, f"{int(T0 * 1000) - 1:013d}-00000000000000ab.json", files=("x.json",))
    junk = _folder(W, "junk", files=("y.json",))
    _put(W, *_cmd(600, sub="check_now/press", payload="PRESS"))
    fds = _fds()
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        assert W.portal_spool_once() == 1  # the command after the folders is read
        for _ in range(20):
            assert W.portal_spool_once() == 0
    assert _fds() == fds  # no descriptor left open
    assert _published(W) == [("flight_watcher_demo/check_now/press", "PRESS", 1, False)]
    assert W.EXPORT["results_list"] == [{"id": "%016x" % 600, "ok": True, "why": ""}]
    assert not os.path.exists(empty)  # an empty folder is removed
    assert os.path.isdir(full) and os.path.isdir(junk)  # one that is not empty stays, skipped from then on
    assert W.EXPORT["spool"].stuck == {os.path.basename(full), "junk"}
    refused = [r.getMessage() for r in caplog.records if r.getMessage().startswith("portal command refused")]
    assert sorted(refused) == sorted(["portal command refused: not a plain file"] * 2
                                     + ["portal command refused: bad file name"])  # once each, not every poll
    assert caplog.text.count("left in place") == 2
    for f in os.listdir(full):
        os.unlink(os.path.join(full, f))
    W.portal_spool_once()
    assert not os.path.exists(full) and os.listdir(d) == ["junk"]  # emptied later: removed quietly


def test_one_bad_entry_never_ends_the_poll(demo, monkeypatch):
    W = demo
    _put(W, *_cmd(610, sub="check_now/press", payload="PRESS"))
    _put(W, *_cmd(611, sub="hunt/set", payload="ON"))
    real = W.EXPORT["spool"]._take

    def boom(path, name):
        if name.endswith("%016x.json" % 610):
            raise RuntimeError("unexpected")
        return real(path, name)
    monkeypatch.setattr(W.EXPORT["spool"], "_take", boom)
    assert W.portal_spool_once() == 1
    assert _published(W) == [("flight_watcher_demo/hunt/set", "ON", 1, False)]
    assert os.listdir(os.path.join(W.PORTAL_DIR, "in")) == []


@pytest.mark.parametrize("sub,payload", [
    ("freq/hunt_s/set", "inf"), ("freq/hunt_s/set", "1e999"), ("freq/hunt_s/set", "nan"), ("freq/hunt_s/set", "-inf"),
    ("freq/hunt_s/set", "Infinity"), ("freq/hunt_s/set", "4"), ("freq/hunt_s/set", "91"), ("freq/hunt_s/set", "fast"),
    ("freq/normal_min/set", "inf"), ("freq/normal_min/set", "0"), ("freq/normal_min/set", "91"),
    ("freq/normal_min/set", ""),
])
def test_freq_must_be_a_finite_number_in_range(demo, sub, payload):
    W = demo
    _put(W, *_cmd(700, sub=sub, payload=payload))
    assert W.portal_spool_once() == 0 and _published(W) == []
    r = W.EXPORT["results_list"][-1]
    assert r["ok"] is False and r["why"].startswith("freq ")


def test_freq_in_range_republished(demo):
    W = demo
    for n, (sub, payload) in enumerate([("freq/hunt_s/set", "5"), ("freq/hunt_s/set", "90.0"),
                                        ("freq/normal_min/set", " 7 "), ("freq/normal_min/set", "1")]):
        _put(W, *_cmd(710 + n, sub=sub, payload=payload))
    assert W.portal_spool_once() == 4


class _Msg:
    def __init__(self, topic, payload):
        self.topic, self.payload = topic, payload if isinstance(payload, bytes) else payload.encode()


@pytest.mark.parametrize("payload", [b"inf", b"1e999", b"-Infinity", b"nan", b"\xff\xfe"])
def test_a_bad_freq_message_never_raises_out_of_paho(demo, payload):
    """An inf freq value was OverflowError inside on_message; paho 2.1 re-raises it and its network thread ends."""
    W = demo
    W.S["freq"] = {"hunt_s": 40}
    msg = _Msg("flight_watcher_demo/freq/hunt_s/set", payload)
    if payload != b"\xff\xfe":
        W.on_message(W.MQ, None, msg)  # the handler itself refuses it
    W.on_message_safe(W.MQ, None, msg)  # and paho's callback never raises, whatever a handler does
    assert W.S["freq"] == {"hunt_s": 40}


def test_paho_callback_logs_a_handler_error_without_the_payload(demo, monkeypatch, caplog):
    import logging
    W = demo

    def boom(p):
        raise KeyError("Doe, Jane")
    monkeypatch.setattr(W, "pref_cmd", boom)
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        W.on_message_safe(W.MQ, None, _Msg("flight_watcher_demo/pref/set", '{"key": "x", "value": "Doe, Jane"}'))
    assert "MQTT pref/set skipped: KeyError" in caplog.text and "Doe" not in caplog.text
    import inspect
    assert "c.on_message = on_message_safe" in inspect.getsource(W.mqtt_start)  # what paho calls


def test_a_huge_pref_number_is_refused_and_the_next_file_still_read(demo):
    W = demo
    huge = '{"key": "federal_tax_pct", "value": %s}' % ("9" * 400)
    _put(W, *_cmd(800, sub="pref/set", payload=huge))
    _put(W, *_cmd(801, sub="pref/set", payload=json.dumps({"key": "federal_tax_pct", "value": 24.5})))
    assert W.portal_spool_once() == 1
    res = {r["id"]: r for r in W.EXPORT["results_list"]}
    assert res["%016x" % 800]["ok"] is False and "not a number" in res["%016x" % 800]["why"]
    assert res["%016x" % 801]["ok"] is True
    assert os.listdir(os.path.join(W.PORTAL_DIR, "in")) == []


def test_deeply_nested_json_is_refused_not_raised(demo):
    W = demo
    deep = "[" * 30000 + "]" * 30000
    name, cmd = _cmd(810, sub="settings/set", payload=deep)
    _put(W, name, cmd)
    _put(W, *_cmd(811, sub="pref/set", payload=deep))
    raw_name = f"{int(T0 * 1000):013d}-{'%016x' % 812}.json"
    _put(W, raw_name, ("[" * 60000).encode())
    assert W.portal_spool_once() == 0 and _published(W) == []
    assert [r["ok"] for r in W.EXPORT["results_list"]] == [False, False]
    assert os.listdir(os.path.join(W.PORTAL_DIR, "in")) == []


def test_freq_limits_are_the_sliders_ranges(demo):
    """1.6.2 (Ryan 2026-11-10): a portal pilot's sliders are what contract 1 sends (hunt 5 to 90 s; normal 1 to 90 min
    since revision 2, 1.7.0, 1 to 20 before); the Watcher's own clamp is WATCHER_FREQ_LIMITS, the same ranges, so every
    value the spool passes is applied as sent. The contract's FREQ_LIMITS stay what the spool checks."""
    W = demo
    got = {}
    for comp, _, cfg, _ in W.entity_defs():
        ct = cfg.get("command_topic") or ""
        if comp == "number" and "/freq/" in ct:
            got[ct.split("/")[-2]] = (cfg["min"], cfg["max"])
    assert got == roles.FREQ_LIMITS == {"normal_min": (1, 90), "hunt_s": (5, 90)}
    assert W.FREQ_LIMITS is roles.WATCHER_FREQ_LIMITS == {"normal_min": (1, 90), "hunt_s": (5, 90)}
    assert not hasattr(roles, "PILOT_FREQ_LIMITS")
