"""FW-0066 (1.4.8, Ryan Nov 7: "any user can see and upload"): an upload sent in chunks over MQTT by a Home Assistant
user who is not an admin (chunks.py, watcher.upload_chunk). The chunks: in order, out of order, a repeated chunk, a
missing chunk (timeout), a checksum that does not match, too large, the wrong file type, sealed (AES-GCM with the key
wrapped by the Watcher's RSA key; the upload's fields bound as additional data) and a contact list refused unsealed.
The Watcher: every chunk on <prefix>/upload/chunk, the status on <prefix>/upload/status (not retained), the save into
the shared uploads folder by the ingress path's own save_upload, sensor.<prefix>_uploads, both pilot instances, and no
contact data in any MQTT payload but the looked-up pilot's own entry, nor in any log line. Synthetic files only."""
import base64
import hashlib
import json
import logging
import math
import os
import stat
import sys
import time
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

import chunks as UP
import sealed as SEAL
import web
from test_contacts import CSV, PDF_TEXT, SECRETS
from test_web_upload import _fake_pdftotext

PDF = b"%PDF-1.4 synthetic\n" + bytes(range(256)) * 1600  # 409,619 bytes: 3 chunks
B64 = lambda b: base64.b64encode(b).decode()  # noqa: E731


def _meta(data, kind="pairings", month="2026-12", list_date="", uid="A" * 24, sha=None, size=None):
    return {"v": 1, "id": uid, "size": len(data) if size is None else size, "sha": sha or hashlib.sha256(data).hexdigest(),
            "kind": kind, "month": month, "list_date": list_date}


def plain(data, **kw):
    m = _meta(data, **kw)
    m["n"] = max(1, math.ceil(len(data) / UP.CHUNK_MAX))
    return [dict(m, i=i, data=B64(data[i * UP.CHUNK_MAX:(i + 1) * UP.CHUNK_MAX])) for i in range(m["n"])]


def sealed(pub_b64, data, ts=None, **kw):
    """What the card does with WebCrypto, in Python."""
    der = base64.b64decode(pub_b64)
    pub = serialization.load_der_public_key(der)
    m = _meta(data, **kw)
    m["n"] = max(1, math.ceil((len(data) + 16) / UP.CHUNK_MAX))
    aes, iv = AESGCM.generate_key(bit_length=256), os.urandom(12)
    m["enc"] = {"v": 1, "kid": hashlib.sha256(der).hexdigest()[:16], "key": "", "iv": B64(iv),
                "ts": int(time.time() if ts is None else ts)}
    ct = AESGCM(aes).encrypt(iv, data, UP.aad(m))
    m["enc"]["key"] = B64(pub.encrypt(aes, padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()),
                                                       algorithm=hashes.SHA256(), label=None)))
    return [dict(m, i=i, data=B64(ct[i * UP.CHUNK_MAX:(i + 1) * UP.CHUNK_MAX])) for i in range(m["n"])]


class Clock:
    def __init__(self):
        self.t = time.time()

    def __call__(self):
        return self.t


@pytest.fixture
def key(tmp_path):
    return SEAL.load_key(str(tmp_path / "settings_key.pem"))


@pytest.fixture
def asm(tmp_path, key):
    clock = Clock()
    a = UP.Assembler(str(tmp_path / "staging" / "flight_watcher"), 25_000_000, key=lambda: key, now=clock)
    a.clock = clock
    return a


def _feed(a, msgs):
    out = [a.add(m) for m in msgs]
    return [s for s, _ in out], [r for _, r in out if r]


def test_in_order_out_of_order_and_a_repeated_chunk(asm, tmp_path):
    for order in ([0, 1, 2], [2, 0, 1], [1, 1, 0, 2, 0]):
        msgs = plain(PDF, uid=f"order{''.join(map(str, order))}" + "x" * 16)
        sts, ready = _feed(asm, [msgs[i] for i in order])
        sts = [x for x in sts if x]  # a copy of a chunk after the upload ended gets no answer
        assert len(ready) == 1, order
        assert [s["state"] for s in sts][-1] == "checking" and sts[-1]["got"] == 3 == sts[-1]["total"]
        fields, data = asm.finish(ready[0])
        assert data == PDF and fields == {"kind": "pairings", "month": "2026-12", "list_date": ""}
        assert not os.path.exists(ready[0]["dir"])  # the staging folder goes
    # a repeated chunk does not count twice
    msgs = plain(PDF, uid="R" * 20)
    s1, _ = asm.add(msgs[0])
    s2, _ = asm.add(msgs[0])
    assert (s1["got"], s2["got"], s2["state"]) == (1, 1, "receiving")
    # the staging folder is private
    root = tmp_path / "staging" / "flight_watcher"
    assert stat.S_IMODE(os.stat(root).st_mode) == 0o700
    assert stat.S_IMODE(os.stat(root / ("R" * 20)).st_mode) == 0o700
    assert stat.S_IMODE(os.stat(root / ("R" * 20) / "00000.part").st_mode) == 0o600


def test_a_missing_chunk_times_out_and_late_chunks_are_ignored(asm):
    msgs = plain(PDF, uid="M" * 20)
    _feed(asm, [msgs[0], msgs[2]])
    asm.clock.t += UP.TIMEOUT_S - 1
    assert asm.sweep() == []
    asm.clock.t += 2
    (st,) = asm.sweep()
    assert st == {"id": "M" * 20, "kind": "pairings", "state": "error", "got": 2, "total": 3, "ok": False,
                  "message": "Timed out: 2 of 3 parts arrived; nothing was saved. Upload again."}
    assert not os.path.exists(os.path.join(asm.root, "M" * 20))
    assert asm.add(msgs[1]) == (None, None)  # the missing part, too late: ignored, no second answer
    # a folder left from before a restart goes once it is old
    asm.clock.t = time.time()
    os.makedirs(os.path.join(asm.root, "Z" * 20))
    assert asm.sweep() == [] and os.path.exists(os.path.join(asm.root, "Z" * 20))
    os.utime(os.path.join(asm.root, "Z" * 20), (asm.clock.t - UP.TIMEOUT_S - 5,) * 2)
    asm.sweep()
    assert not os.path.exists(os.path.join(asm.root, "Z" * 20))


def test_checksum_size_type_and_cap(asm):
    _, (r,) = _feed(asm, plain(PDF, uid="S" * 20, sha="0" * 64))
    with pytest.raises(UP.Bad, match="checksum does not match"):
        asm.finish(r)
    notpdf = b"GIF89a" + b"x" * 1000
    _, (r,) = _feed(asm, plain(notpdf, uid="T" * 20, kind="award"))
    with pytest.raises(UP.Bad, match="not a PDF"):
        asm.finish(r)
    big = UP.Assembler(asm.root, 1_000_000, key=None, now=asm.clock)
    st, ready = big.add(plain(PDF + b"x" * 700_000, uid="B" * 20)[0])
    assert st["state"] == "error" and st["message"].startswith("Too large: 1.1 MB") and ready is None
    assert not os.path.exists(os.path.join(asm.root, "B" * 20))
    assert big.add(plain(PDF, uid="B" * 20)[1]) == (None, None)  # the refused upload's other chunks: ignored
    # more data than the size says, a chunk count that cannot hold the file, mixed parts
    m = plain(PDF, uid="D" * 20)
    st, _ = asm.add(dict(m[0], size=1000, n=1))
    assert st["state"] == "error"
    m = plain(PDF, uid="E" * 20)
    asm.add(m[0])
    st, _ = asm.add(dict(m[1], month="2027-01"))
    assert st["message"] == "The upload's parts do not match; nothing was saved."


@pytest.mark.parametrize("bad, why", [
    ({"kind": "roster"}, "Pick what the file is."), ({"month": "2026-13"}, "Pick the bid period (month)."),
    ({"kind": "seniority", "month": "2026-12"}, "Only an award or a pairings package has a bid period."),
    ({"kind": "award", "list_date": "2026-11-06"}, "Bad list date."), ({"sha": "xyz"}, "Bad checksum."),
    ({"i": 3}, "Bad chunk index."), ({"i": True}, "Bad chunk index."), ({"data": "@@@"}, "Bad chunk data."),
    ({"data": "A" * (UP.CHUNK_MAX * 2)}, "Bad chunk data."), ({"n": 0}, "Bad chunk count."), ({"size": -1}, "Bad file size."),
    ({"enc": {"v": 2}}, "Bad seal on the upload."), ({"v": 2}, "Not an upload chunk this version reads.")])
def test_bad_chunks_are_refused(asm, bad, why):
    m = dict(plain(PDF, uid="F" * 20)[0], **bad)
    st, ready = asm.add(m)
    assert (st["state"], st["message"], ready) == ("error", why, None)


def test_no_id_no_answer_and_busy(asm):
    assert asm.add({"v": 1, "id": "short"}) == (None, None) and asm.add("not a dict") == (None, None)
    for k in range(UP.MAX_ACTIVE):
        assert asm.add(plain(PDF, uid=f"busy{k}" + "q" * 16)[0])[0]["state"] == "receiving"
    st, _ = asm.add(plain(PDF, uid="X" * 20)[0])
    assert st["message"] == "The Watcher is busy with other uploads; try again in a minute."


def test_sealed_round_trip_and_what_breaks_it(asm, key):
    pub = SEAL.public_info(key)["pubkey"]
    msgs = sealed(pub, PDF, uid="G" * 20, ts=asm.clock.t)
    assert msgs[0]["n"] == 3 and all("data" in m and "%PDF" not in base64.b64decode(m["data"]).decode("latin1") for m in msgs)
    _, (r,) = _feed(asm, msgs[::-1])
    assert asm.finish(r)[1] == PDF
    # the fields are bound to the ciphertext: a changed bid period does not open
    _, (r,) = _feed(asm, [dict(m, month="2027-01") for m in sealed(pub, PDF, uid="H" * 20, ts=asm.clock.t)])
    with pytest.raises(UP.Bad, match="does not open"):
        asm.finish(r)
    _, (r,) = _feed(asm, sealed(pub, PDF, uid="J" * 20, ts=asm.clock.t - SEAL.MAX_AGE_S - 5))
    with pytest.raises(UP.Bad, match="too old"):
        asm.finish(r)
    other = SEAL.public_info(SEAL.load_key(os.path.join(os.path.dirname(asm.root), "other.pem")))["pubkey"]
    _, (r,) = _feed(asm, sealed(other, PDF, uid="K" * 20, ts=asm.clock.t))
    with pytest.raises(UP.Bad, match="another key"):
        asm.finish(r)


def test_a_contact_list_only_sealed(asm, key):
    st, _ = asm.add(plain(CSV.encode(), uid="C" * 20, kind="contacts", month="")[0])
    assert st["state"] == "error" and "only taken encrypted" in st["message"] and "https" in st["message"]
    pub = SEAL.public_info(key)["pubkey"]
    _, (r,) = _feed(asm, sealed(pub, CSV.encode(), uid="L" * 20, kind="contacts", month="", ts=asm.clock.t))
    assert asm.finish(r) == ({"kind": "contacts", "month": "", "list_date": ""}, CSV.encode())
    _, (r,) = _feed(asm, sealed(pub, b"\x89PNG\r\n\x1a\n" + b"x" * 99, uid="N" * 20, kind="contacts", month="", ts=asm.clock.t))
    with pytest.raises(UP.Bad, match="not a PDF, CSV or XLSX"):
        asm.finish(r)


# ---------------------------------------------------------------- the Watcher
class FakeClient:
    def __init__(self):
        self.msgs = []

    def publish(self, topic, payload="", retain=False):
        self.msgs.append((topic, payload, retain))

    def subscribe(self, topic):
        pass


class Msg:
    def __init__(self, topic, payload):
        self.topic, self.payload = topic, json.dumps(payload).encode()


HST = timezone(timedelta(hours=-10))


def _watcher(tmp_path, monkeypatch, instance=""):
    from test_instance import _load
    d = tmp_path / ("d_" + (instance or "default"))
    d.mkdir(exist_ok=True)
    W = _load(d, monkeypatch, instance, {"username": "u", "password": "p"})
    up = tmp_path / "uploads"
    up.mkdir(exist_ok=True)
    monkeypatch.setattr(web, "UPLOAD_DIR", str(up))
    monkeypatch.setattr(web, "CONTACTS_FILE", str(tmp_path / "contacts.json"))
    monkeypatch.setattr(web, "LOCK_PATH", str(tmp_path / "lock"))
    monkeypatch.setattr(web, "PAIRINGS_DIR", str(tmp_path / "www"))
    monkeypatch.setattr(web, "_hst_now", lambda: datetime(2026, 11, 7, 9, 30, tzinfo=HST))
    monkeypatch.setattr(web.subprocess, "run", _fake_pdftotext("PAIRINGS\n"))
    monkeypatch.setattr(W, "UPLOAD_STAGING", str(up / ".staging" / W.T))
    monkeypatch.setattr(W, "_bg", lambda fn, *a: fn(*a))
    W._UP.update(asm=None, sig=None, recent=[], pub_at={})
    W.MQ = FakeClient()
    return W, up


def _status(W):
    return [(json.loads(p), r) for t, p, r in W.MQ.msgs if t == f"{W.T}/upload/status"]


@pytest.mark.parametrize("instance", ["", "james"])
def test_the_watcher_saves_a_sealed_upload_like_the_ingress_path(tmp_path, monkeypatch, instance, caplog):
    W, up = _watcher(tmp_path, monkeypatch, instance)
    pub = W.settings_state()["pubkey"]
    msgs = sealed(pub, PDF, uid="W" * 20)
    with caplog.at_level(logging.INFO):
        for m in msgs:
            W.on_message(W.MQ, None, Msg(f"{W.T}/upload/chunk", m))
    assert (up / "2026-12_pairings.pdf").read_bytes() == PDF and (up / "2026-12_pairings.txt").read_text() == "PAIRINGS\n"
    sts = _status(W)
    assert all(r is False for _, r in sts)  # never retained
    assert [s["state"] for s, _ in sts] == ["receiving", "checking", "reading", "done"]  # one receiving inside 1 s
    last = sts[-1][0]
    assert last["ok"] is True and last["message"] == "Saved 2026-12_pairings.pdf (400 KB)." and last["id"] == "W" * 20
    assert last["recent"][0]["id"] == "W" * 20 and last["recent"][0]["ok"] is True
    lst = [(json.loads(p), r) for t, p, r in W.MQ.msgs if t == f"{W.T}/uploads"]
    d, retained = lst[-1]
    assert retained is True and d["count"] == 1 and d["files"][0]["name"] == "2026-12_pairings.pdf"
    assert d["mqtt_max_bytes"] == web.UPLOAD_MAX and d["chunk_bytes"] == UP.CHUNK_MAX and d["version"] == W.VERSION
    assert f"upload WWWWWW (pairings, 400 KB, sealed): saved" in caplog.text
    assert not os.listdir(up / ".staging" / W.T)
    # discovery: the two new sensors on this instance's prefix
    c = FakeClient()
    W.discovery(c)
    cfg = {t: json.loads(p) for t, p, _ in c.msgs if p}
    u = cfg[f"homeassistant/sensor/{W.T}/uploads/config"]
    s = cfg[f"homeassistant/sensor/{W.T}/upload_status/config"]
    assert u["default_entity_id"] == f"sensor.{W.T}_uploads" and u["json_attributes_topic"] == f"{W.T}/uploads"
    assert s["default_entity_id"] == f"sensor.{W.T}_upload_status" and s["state_topic"] == f"{W.T}/upload/status"


def test_errors_answer_on_the_status_and_never_raise(tmp_path, monkeypatch):
    W, up = _watcher(tmp_path, monkeypatch)
    W.on_message(W.MQ, None, Msg(f"{W.T}/upload/chunk", plain(b"not a pdf at all", uid="Q" * 20, kind="award")[0]))
    (st, _), = [x for x in _status(W) if x[0]["state"] == "error"]
    assert st["message"] == "That file is not a PDF." and st["recent"][0]["ok"] is False
    W.MQ.msgs.clear()
    W.on_message(W.MQ, None, type("M", (), {"topic": f"{W.T}/upload/chunk", "payload": b"\xff{not json"})())
    W.on_message(W.MQ, None, Msg(f"{W.T}/upload/chunk", [1, 2]))
    assert W.MQ.msgs == []
    monkeypatch.setattr(W, "assembler", lambda: 1 / 0)  # anything unexpected: logged, never out of paho's thread
    W.upload_chunk(b"{}")
    assert sorted(os.listdir(up)) == [".staging"] or sorted(os.listdir(up)) == []


def test_both_instances_subscribe_the_chunk_topic_at_qos_1(tmp_path, monkeypatch):
    for inst in ("", "james"):
        W, _ = _watcher(tmp_path, monkeypatch, inst)
        subs, pubs = [], []

        class C:
            def __init__(self, *a, **k):
                pass

            def username_pw_set(self, *a):
                pass

            def will_set(self, *a, **k):
                pass

            def connect(self, *a):
                pass

            def loop_start(self):
                pass

            def publish(self, t, p="", retain=False):
                pubs.append((t, retain))

            def subscribe(self, t):
                subs.append(t)
        monkeypatch.setattr(W.mqtt, "Client", C)
        monkeypatch.setattr(W, "mqtt_creds", lambda: {"username": "u", "password": "p", "host": "h", "port": 1883})
        for f in ("discovery", "publish_settings", "publish_rules", "publish_swap_tests", "publish_swap_mode"):
            monkeypatch.setattr(W, f, lambda *a, **k: None)
        monkeypatch.setattr(W, "freq", lambda: {"normal_min": 6, "hunt_s": 40})
        c = W.mqtt_start()
        c.on_connect(c, None, None, 0)
        assert (f"{W.T}/upload/chunk", 1) in subs
        assert (f"{W.T}/uploads", True) in pubs  # what is on file, at every connect


def test_a_contact_list_end_to_end_reaches_only_the_looked_up_pilot(tmp_path, monkeypatch, caplog):
    """A sealed contact list through the chunks; then a pilot lookup: sensor.flight_watcher_pilot_schedule carries
    that one pilot's entry. No other MQTT payload (status, uploads list, pilot schedule of another pilot) and no log
    line carries a name, number or address from the list."""
    W, up = _watcher(tmp_path, monkeypatch)
    monkeypatch.setattr(web.subprocess, "run", _fake_pdftotext(PDF_TEXT))
    from store import Store
    monkeypatch.setattr(W, "DB", Store(str(tmp_path / "t.db")))
    monkeypatch.setattr(W, "CARD_PAIRINGS", str(tmp_path / "www"))
    monkeypatch.setattr(W, "local_now", lambda: datetime(2026, 11, 10, 12, 5))
    pub = W.settings_state()["pubkey"]
    W.MQ.msgs.clear()
    with caplog.at_level(logging.DEBUG):
        for m in sealed(pub, b"%PDF-1.4 contacts", uid="P" * 20, kind="contacts", month=""):
            W.on_message(W.MQ, None, Msg(f"{W.T}/upload/chunk", m))
        cf = tmp_path / "contacts.json"
        assert stat.S_IMODE(os.stat(cf).st_mode) == 0o600 and json.loads(cf.read_text())["count"] == 6
        assert _status(W)[-1][0]["message"].startswith("Saved contacts_2026-11-07.pdf")
        lst = json.loads([p for t, p, _ in W.MQ.msgs if t == f"{W.T}/uploads"][-1])
        assert lst["contacts"]["count"] == 6 and lst["files"][0]["kind"] == "contacts"
        W.pub_pilot({"emp": "10002", "name": "Roe, Rick", "status": "loading", "month": "", "days": [], "items": []})
        W.pub_pilot({"emp": "10999", "name": "Nobody, Else", "status": "ok", "month": "", "days": [], "items": []})
        W.pilot_cmd(json.dumps({"q": "o'neil, kim"}))  # a name only the contact list has: looked up by its number
    allps = [(json.loads(p), r) for t, p, r in W.MQ.msgs if t == f"{W.T}/pilot_schedule"]
    # review: the broker never keeps a contact: each lookup's retained copy has none, and the copy with it follows,
    # not retained (the sensor ends on it)
    assert [(x["emp"], r, "contact" in x) for x, r in allps] == [
        ("10002", True, False), ("10002", False, True), ("10999", True, False), ("10006", True, False), ("10006", False, True)]
    assert all({k: v for k, v in x.items() if k != "contact"} == allps[i - 1][0] for i, (x, r) in enumerate(allps) if not r)
    ps = [x for i, (x, r) in enumerate(allps) if not (r and i + 1 < len(allps) and not allps[i + 1][1])]
    assert ps[0]["contact"] == {"name": "Roe, Rick", "emails": ["rick.roe@example.com"],
                                "phones": [{"label": "cell", "number": "808-555-0103", "tel": "+18085550103"}]}
    assert "contact" not in ps[1]
    assert ps[2]["emp"] == "10006" and ps[2]["contact"]["phones"][0]["tel"] == "+18085550106"
    everything = "\n".join(p for t, p, _ in W.MQ.msgs if not t.endswith("/pilot_schedule"))
    for s in SECRETS + ("Smith", "O'Neil", "Lee, Ann", "0104", "0105", "0108"):
        assert s not in everything, s
        assert s not in caplog.text, s
    roe = json.dumps(ps[0])
    for s in ("Doe", "jane.doe", "0101", "Smith", "0106"):  # the looked-up pilot's entry only
        assert s not in roe, s
    assert "pilot contact list read, 6 pilots" in caplog.text


def test_the_card_and_the_watcher_agree_on_the_seal(tmp_path, key):
    """The uploads card's own sealing (node WebCrypto, the card's code) opens in the Watcher: the chunks it publishes
    for a non-admin are reassembled byte for byte; on a plain http page (no crypto.subtle) the card's own SHA-256
    matches Python's."""
    import shutil
    import subprocess
    if not shutil.which("node"):
        pytest.skip("node not installed")
    from test_uploads_card import CARD, HARNESS
    info = SEAL.public_info(key)
    data = PDF + b"tail"
    body = f"""
      const raw = Buffer.from({json.dumps(B64(data))}, "base64");
      const file = (name, type) => ({{name, type, size: raw.length, arrayBuffer: async () => raw.buffer.slice(raw.byteOffset, raw.byteOffset + raw.length)}});
      const out = {{}};
      for (const http of [false, true]) {{
        if (http) Object.defineProperty(globalThis, "crypto", {{value: {{getRandomValues: (a) => require("crypto").getRandomValues(a)}}, configurable: true}});
        const pubs = [];
        const states = {{"sensor.flight_watcher_uploads": {{state: "0", last_updated: "1", attributes: {{files: [], mqtt_max_bytes: 25000000}}}},
          "sensor.flight_watcher_settings": {{state: "True", attributes: {{pubkey: {json.dumps(info["pubkey"])}, kid: {json.dumps(info["kid"])}}}}}}};
        const c = new FlightWatcherUploadsCard(); c.setConfig({{}});
        const h = {{user: {{is_admin: false}}, states, callWS: async () => {{ throw new Error("no ws"); }},
          callService: async (d, s, data) => {{ pubs.push([d, s, data]); const p = JSON.parse(data.payload);
            if (p.i === p.n - 1) setTimeout(() => {{ c.hass = {{...h, states: {{...states, "sensor.flight_watcher_upload_status": {{state: "done",
              attributes: {{id: "other", phase: "done", recent: [{{id: p.id, ok: true, message: "Saved 2026-12_pairings.pdf (400 KB)."}}]}}}}}}}}; }}, 0); }} }};
        c.hass = h;
        c._q("[data-kind]").value = "pairings"; c._q("[data-month]").value = "2026-12";
        c._q("[data-pdf]").files = [file("p.pdf", "application/pdf")];
        await c._upload();
        out[http ? "http" : "https"] = {{pubs, msg: c._msg, calls: calls.length, fetched: fetched.length, cookies: cookies.length}};
      }}
      console.log(JSON.stringify(out));
    """
    js = HARNESS + open(CARD, encoding="utf-8").read() + "\n(async () => {\n" + body + "\n})();"
    f = tmp_path / "seal.js"
    f.write_text(js)
    out = subprocess.run(["node", str(f)], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    r = json.loads(out.stdout)
    for mode in ("https", "http"):
        x = r[mode]
        assert x["msg"] == {"ok": True, "text": "Saved 2026-12_pairings.pdf (400 KB)."}, mode
        assert (x["calls"], x["fetched"], x["cookies"]) == (0, 0, 0), mode  # no Supervisor call, no ingress request
        assert all(d == "mqtt" and s == "publish" and p["topic"] == "flight_watcher/upload/chunk" and p["qos"] == 1
                   and p["retain"] is False for d, s, p in x["pubs"]), mode
        msgs = [json.loads(p["payload"]) for _, _, p in x["pubs"]]
        assert all(len(p["payload"]) < 300 * 1024 for _, _, p in x["pubs"])  # about 256 KiB of base64 at most
        a = UP.Assembler(str(tmp_path / f"st_{mode}"), 25_000_000, key=key)
        ready = [r_ for _, r_ in (a.add(m) for m in msgs) if r_]
        fields, got = a.finish(ready[0])
        assert got == data and fields == {"kind": "pairings", "month": "2026-12", "list_date": ""}
        assert ("enc" in msgs[0]) == (mode == "https")
        assert msgs[0]["sha"] == hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------- FW-0066 review fixes
def test_an_ended_upload_is_not_saved_again_while_its_seal_opens(tmp_path, key):
    """A sealed upload's chunks sent again (a replay) are ignored for the seal's whole life (it used to be 20 min of
    the seal's 60), and after a restart too: the ids of completed sealed uploads are kept in done_path (mode 600)."""
    clock = Clock()
    done = tmp_path / "upload_done.json"
    a = UP.Assembler(str(tmp_path / "st"), 25_000_000, key=lambda: key, now=clock, done_path=str(done))
    msgs = sealed(SEAL.public_info(key)["pubkey"], PDF, uid="K" * 20)
    _, (r,) = _feed(a, msgs)
    assert a.finish(r)[1] == PDF
    assert stat.S_IMODE(os.stat(done).st_mode) == 0o600 and "K" * 20 in json.loads(done.read_text())
    clock.t += 10 * UP.TIMEOUT_S + 60  # past the old 20 min window, inside the seal's hour
    a.sweep()
    assert [a.add(m) for m in msgs] == [(None, None)] * len(msgs)
    b = UP.Assembler(str(tmp_path / "st"), 25_000_000, key=lambda: key, now=clock, done_path=str(done))  # a restart
    assert [b.add(m) for m in msgs] == [(None, None)] * len(msgs)
    clock.t += SEAL.MAX_AGE_S  # the seal no longer opens: the id may go
    b.sweep()
    assert "K" * 20 not in b.done and json.loads(done.read_text()) == {}
    # an unsealed upload or a refused one is never written to disk (anyone could send it anyway)
    _feed(b, plain(PDF, uid="U" * 20))
    b.add(dict(plain(PDF, uid="V" * 20)[0], kind="nope"))
    assert json.loads(done.read_text()) == {} and "U" * 20 in b.done and "V" * 20 in b.done
    # a damaged file is no reason to fail
    done.write_text("{not json")
    assert UP.Assembler(str(tmp_path / "st"), 25_000_000, key=None, done_path=str(done)).done == {}


def test_the_upload_status_carries_its_phase(tmp_path, monkeypatch):
    """HA's MQTT sensor drops an attribute named state (MQTT_ATTRIBUTES_BLOCKED): the status also says phase, which
    the card reads."""
    W, up = _watcher(tmp_path, monkeypatch)
    for m in plain(PDF, uid="H" * 20):
        W.on_message(W.MQ, None, Msg(f"{W.T}/upload/chunk", m))
    sts = [s for s, _ in _status(W)]
    assert [s["phase"] for s in sts] == [s["state"] for s in sts] == ["receiving", "checking", "reading", "done"]


def test_a_second_pilot_waiting_for_settings_still_sweeps_uploads(tmp_path, monkeypatch):
    """James's instance has no FLICA credentials yet (needs_settings) and waits in main(); its MQTT already takes
    upload chunks, so the janitor (stalled uploads, the busy slots, the files list) must run there too."""
    from test_instance import _load
    W = _load(tmp_path, monkeypatch, "james", {})
    fake = FakeClient()
    monkeypatch.setattr(W, "mqtt_start", lambda: fake)
    import threading
    stop = threading.Event()
    monkeypatch.setattr(W, "upload_janitor", lambda: stop.wait(30))
    W._UP["janitor"] = None

    class Waiting(Exception):
        pass

    def sleep(s):
        if s >= 3600:
            raise Waiting()
    monkeypatch.setattr(W.time, "sleep", sleep)
    try:
        with pytest.raises(Waiting):
            W.main()
        assert W.S["machine"] == "needs_settings"
        j = W._UP["janitor"]
        assert j is not None and j.name == "uploads" and j.is_alive()
        assert W.start_upload_janitor() is j  # once only
    finally:
        stop.set()
        W._UP["janitor"] = None
