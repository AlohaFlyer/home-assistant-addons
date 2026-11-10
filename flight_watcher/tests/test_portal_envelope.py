"""1.6.0 (FW-0061): the portal's signed envelopes and its signing key (portal.py, PORTAL_CONTRACT.md sections 2 and 3).
Synthetic data only."""
import json
import os
import stat

import pytest

import portal as PT


@pytest.fixture
def key(tmp_path):
    return PT.load_key(str(tmp_path / "data" / "portal_ed25519.pem"))


def test_round_trip(key):
    env = PT.envelope(key, "state", "demo", 7, '{"states":{},"ha_ok":true}')
    assert set(env) == {"fwp", "kind", "pilot", "seq", "payload", "sig"} and env["fwp"] == 1
    assert len(PT.b64u_dec(env["sig"])) == 64 and "=" not in env["sig"]
    pub = PT.public_id(key)
    assert PT.PUB_RE.fullmatch(pub) and len(pub) == len("ed25519:") + 43
    assert PT.verify(pub, env, "state", "demo") == env["payload"]
    assert PT.verify(PT.public_from_id(pub), json.loads(json.dumps(env)), "state", "demo", after=6) == env["payload"]
    # the signed bytes are exactly the documented ones
    raw = PT.b64u_dec(pub.split(":", 1)[1])
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    Ed25519PublicKey.from_public_bytes(raw).verify(
        PT.b64u_dec(env["sig"]), b'fwp1\nstate\ndemo\n7\n{"states":{},"ha_ok":true}')


@pytest.mark.parametrize("change,why", [
    ({"payload": '{"states":{},"ha_ok":false}'}, "bad signature"),
    ({"pilot": "james"}, "wrong pilot"),
    ({"kind": "events"}, "wrong kind"),
    ({"seq": 8}, "bad signature"),
    ({"fwp": 2}, "unknown fwp"),
    ({"sig": "A" * 86}, "bad signature"),
    ({"sig": "short"}, "bad signature length"),
    ({"extra": 1}, "not an envelope"),
])
def test_tamper_and_mismatch_refused(key, change, why):
    env = {**PT.envelope(key, "state", "demo", 7, '{"states":{},"ha_ok":true}'), **change}
    with pytest.raises(PT.PortalError, match=why):
        PT.verify(PT.public_id(key), env, "state", "demo")


def test_wrong_key_rollback_and_caps(key, tmp_path):
    env = PT.envelope(key, "results", "demo", 10, '{"results":[]}')
    other = PT.load_key(str(tmp_path / "other.pem"))
    with pytest.raises(PT.PortalError, match="bad signature"):
        PT.verify(PT.public_id(other), env, "results", "demo")
    with pytest.raises(PT.PortalError, match="seq not above"):
        PT.verify(PT.public_id(key), env, "results", "demo", after=10)
    with pytest.raises(PT.PortalError, match="over 64 KB"):
        PT.envelope(key, "results", "demo", 11, "x" * (64 * 1024 + 1))
    PT.envelope(key, "results", "demo", 11, "x" * (64 * 1024))  # at the cap is fine
    PT.envelope(key, "file:tickets", "demo", 1, "{}")  # 1.7.0 (contract 1 revision 2): a list file kind now
    for bad_kind in ("file:uploads", "file:finds", "file:finds:2026", "file:versions:2026-11", "file:tickets:x", "blob",
                     "../state"):
        with pytest.raises(PT.PortalError, match="unknown kind"):
            PT.envelope(key, bad_kind, "demo", 1, "{}")
    with pytest.raises(PT.PortalError, match="bad pilot"):
        PT.envelope(key, "state", "../x", 1, "{}")
    with pytest.raises(PT.PortalError, match="not an ed25519"):
        PT.verify("ed25519:short", env)


def test_file_names_and_kinds():
    for kind, name in (("manifest", "manifest.json"), ("state", "state.json"), ("events", "events.json"),
                       ("results", "results.json"), ("file:finds:2026-11", "files/finds_2026-11.json"),
                       ("file:pairings:2026-12", "files/pairings_2026-12.json"),
                       ("file:school:2026-27", "files/school_2026-27.json"), ("file:pickers", "files/pickers.json"),
                       ("file:versions", "files/versions.json"), ("file:recall", "files/recall.json"),
                       ("file:pilotver", "files/pilotver.json"), ("file:tickets", "files/tickets.json")):
        assert PT.out_name(kind) == name and PT.kind_of(name) == kind
    for bad in ("files/uploads.json", "files/tickets_2026-11.json", "files/finds.json", "files/pickers_2026-11.json", "blobs/x.js", "../state.json",
                "files/finds_2026-11_" + "0" * 32 + ".json"):
        assert PT.kind_of(bad) is None, bad


def test_seq_strictly_increasing_and_persisted(tmp_path):
    p = str(tmp_path / "portal_seq.json")
    clock = {"t": 1763600000.0}
    s = PT.SeqStore(p, now=lambda: clock["t"])
    a = s.next("state")
    b = s.next("state")
    assert b == a + 1 and s.next("events") == 1763600000000
    clock["t"] -= 3600  # a clock step back an hour
    s2 = PT.SeqStore(p, now=lambda: clock["t"])  # a restart
    assert s2.next("state") == b + 1  # never goes back
    assert stat.S_IMODE(os.stat(p).st_mode) == 0o600


def test_key_file_private_reused_and_never_under_share(tmp_path):
    p = tmp_path / "data" / "portal_ed25519.pem"
    k1 = PT.load_key(str(p))
    assert stat.S_IMODE(os.stat(p).st_mode) == 0o600 and b"PRIVATE KEY" in p.read_bytes()
    assert PT.public_id(PT.load_key(str(p), create=False)) == PT.public_id(k1)
    os.chmod(p, 0o644)
    PT.load_key(str(p))
    assert stat.S_IMODE(os.stat(p).st_mode) == 0o600  # re-applied
    for bad in ("/share/portal_ed25519.pem", "/share/fw_portal/portal_ed25519.pem", "/share/flight_watcher/k.pem"):
        with pytest.raises(PT.PortalError, match="never goes under /share"):
            PT.load_key(bad)
    with pytest.raises(PT.PortalError, match="no portal signing key"):
        PT.load_key(str(tmp_path / "none.pem"), create=False)
    assert PT.KEY_FILE == "/data/portal_ed25519.pem"


def test_corrupt_key_moves_aside_only_when_creating(tmp_path):
    p = tmp_path / "portal_ed25519.pem"
    p.write_bytes(b"-----BEGIN PRIVATE KEY-----\nnot a key\n-----END PRIVATE KEY-----\n")
    with pytest.raises(PT.PortalError, match="does not parse"):
        PT.load_key(str(p), create=False)  # a pilot's watcher.py never moves or makes the key
    assert p.exists() and not (tmp_path / "portal_ed25519.pem.bad").exists()
    said = []
    k = PT.load_key(str(p), log=said.append)
    assert (tmp_path / "portal_ed25519.pem.bad").exists() and PT.public_id(PT.load_key(str(p))) == PT.public_id(k)
    assert len(said) == 1 and "fw_signing_key" in said[0] and "PRIVATE" not in said[0]


def test_writer_atomic_mode_and_blobs(tmp_path, key):
    out = tmp_path / "out"
    for d in ("", "blobs", "files"):
        (out / d).mkdir(parents=True, exist_ok=True)
    w = PT.Writer(str(out), "demo", key, PT.SeqStore(str(tmp_path / "seq.json")))
    env = w.write("state", {"states": {}, "ha_ok": True})
    on_disk = json.loads((out / "state.json").read_text())
    assert on_disk == env and PT.verify(PT.public_id(key), on_disk, "state", "demo")
    assert stat.S_IMODE(os.stat(out / "state.json").st_mode) == 0o640
    assert [n for n in os.listdir(out) if n.startswith(".")] == []  # no tmp left behind
    w.write("file:finds:2026-11", '{"month":"2026-11","count":0,"finds":[]}')
    assert PT.verify(PT.public_id(key), json.loads((out / "files" / "finds_2026-11.json").read_text()),
                     "file:finds:2026-11", "demo") == '{"month":"2026-11","count":0,"finds":[]}'
    sha = w.blob("// card\n")
    assert (out / "blobs" / f"{sha}.js").read_text() == "// card\n" and len(sha) == 64
    old = w.blob("// old card\n")
    oldp = out / "blobs" / f"{old}.js"
    os.utime(oldp, (0, 0))  # the file time does not count: the hour runs from the sweep that first finds it unlisted
    t = 1.9e9
    assert w.sweep_blobs({sha}, now=t) == 0 and oldp.exists()
    assert w.sweep_blobs({sha}, now=t + PT.BLOB_KEEP_S - 1) == 0 and oldp.exists()
    assert w.sweep_blobs({sha, old}, now=t + PT.BLOB_KEEP_S) == 0 and old not in w.unlisted  # named again: clock off
    assert w.sweep_blobs({sha}, now=t + 2 * PT.BLOB_KEEP_S) == 0 and oldp.exists()  # unlisted again: a new hour
    assert w.sweep_blobs({sha}, now=t + 3 * PT.BLOB_KEEP_S) == 1 and not oldp.exists() and w.unlisted == {}
    young = w.blob("// unlisted but new\n")
    assert w.sweep_blobs({sha}) == 0 and (out / "blobs" / f"{young}.js").exists()  # kept for an hour
    with pytest.raises(PT.PortalError, match="blob over"):
        w.blob("x" * (1024 * 1024 + 1))
