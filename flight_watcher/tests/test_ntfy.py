"""1.6.0 (FW-0061): ntfy pushes for a pilot's portal (ntfy.py, PORTAL_CONTRACT.md section 6): the constant host, no
names in the title, body or headers, the admin never posts, the token is never logged, dedupe, the hourly cap,
retries, the priority rule, one push per new machine state, and the settings card offering ntfy only on a portal
pilot and only sealed. Made-up names; fake tokens only."""
import json
import logging
import os
import shutil
import subprocess
import tempfile

import pytest
import requests

import ntfy as NT
import portal as PT
import sealed as SEAL

HERE = os.path.dirname(os.path.abspath(__file__))
TOPIC, TOKEN = "fw-test-topic-0001-synthetic00", "tk_faketokenfaketokenfaketoken0"
NAME = "Doe, Jane"


class Post:
    def __init__(self, codes=(200,)):
        self.codes, self.calls = list(codes), []

    def __call__(self, url, data=None, headers=None, timeout=None):
        self.calls.append({"url": url, "data": data, "headers": dict(headers or {}), "timeout": timeout})
        c = self.codes.pop(0) if self.codes else 200
        if isinstance(c, Exception):
            raise c
        return type("R", (), {"status_code": c})()


def _rec(kind="new_pairing", **p):
    base = {"pairing": "H9001", "dates": "20NOV-22NOV", "fit": "Fits", "far": "OK", "captain": f"{NAME} (10001)",
            "detail_url": f"https://ha2.flica.net/x?n={NAME}", "contact": {"name": NAME}, "value": 1234.5,
            "comm_why": f"{NAME} commutes"}
    return PT.event_record(kind, {**base, **p}, 1, "2026-11-09T20:00:00+00:00")


def _sender(post=None, origin="", **k):
    logs, sleeps = [], []
    n = NT.Ntfy(TOPIC, TOKEN, origin, log=logs.append, post=post or Post(), sleep=sleeps.append, **k)
    return n, logs, sleeps


def test_host_is_the_constant_and_headers_carry_no_names():
    assert NT.HOST == "https://ntfy.sh"
    post = Post()
    n, logs, _ = _sender(post, origin="https://hom.tail0000.ts.net")
    assert n.send(_rec()) == "sent"
    c = post.calls[0]
    assert c["url"] == f"https://ntfy.sh/{TOPIC}" and c["timeout"] == NT.TIMEOUT_S
    h = c["headers"]
    assert h["Title"] == "New pairing H9001 20NOV-22NOV" and h["Priority"] == "5" and h["Tags"] == "airplane"
    assert h["Click"] == "https://hom.tail0000.ts.net/fw/#watcher" and h["Authorization"] == f"Bearer {TOKEN}"
    blob = json.dumps({k: v for k, v in h.items() if k != "Authorization"}) + c["data"].decode()
    for leak in ("Doe", "Jane", "10001", "flica.net", "1234.5", "commutes"):
        assert leak not in blob, leak
    assert logs == ["ntfy: new_pairing sent (200)"]


@pytest.mark.parametrize("topic", ["../x", "a/b", "evil.example.com", "", "x" * 65, "t?x=1", "t#x"])
def test_a_topic_can_never_change_the_host(topic):
    assert not NT.valid(topic, TOKEN)
    with pytest.raises(ValueError):
        NT.Ntfy(topic, TOKEN)


def test_no_click_without_a_valid_origin():
    post = Post()
    n, _, _ = _sender(post)
    n.send(_rec())
    assert "Click" not in post.calls[0]["headers"]


def test_dedupe_and_hourly_cap():
    clock = {"t": 1000.0}
    post = Post([200] * 100)
    n, logs, _ = _sender(post, now=lambda: clock["t"])
    r = _rec()
    assert n.send(r) == "sent" and n.send(r) == "duplicate" and len(post.calls) == 1
    for i in range(NT.PER_HOUR - 1):
        assert n.send(_rec(pairing=f"H{i:04d}")) == "sent"
    assert n.send(_rec(pairing="H8888")) == "capped" and len(post.calls) == NT.PER_HOUR
    assert logs[-1] == "ntfy: new_pairing not sent: 30 pushes this hour already"
    clock["t"] += 3601
    assert n.send(_rec(pairing="H8888")) == "sent"


def test_a_pairing_back_in_the_pot_is_pushed_again():
    """The pot baseline is rebuilt on every check, so a pairing that is picked up and dropped back fires
    event/new_pairing again with a later 'seen': a new occurrence, pushed again within the 24 h dedupe window. The
    same publish replayed is still a duplicate."""
    clock = {"t": 1000.0}
    post = Post([200] * 5)
    n, _, _ = _sender(post, now=lambda: clock["t"])
    first = _rec(seen="2026-11-09T10:00:00+00:00", month="2026-11")
    assert n.send(first) == "sent" and n.send(dict(first)) == "duplicate"
    clock["t"] += 3 * 3600
    assert n.send(_rec(seen="2026-11-09T13:00:00+00:00", month="2026-11")) == "sent"
    assert len(post.calls) == 2


def test_retries_with_backoff_and_no_retry_on_a_refusal():
    post = Post([requests.ConnectionError("boom"), 503, 200])
    n, logs, sleeps = _sender(post)
    assert n.send(_rec()) == "sent" and len(post.calls) == 3 and sleeps == [2, 4]
    post = Post([500, 500, 500])
    n, logs, sleeps = _sender(post)
    assert n.send(_rec()) == "failed" and len(post.calls) == 3 and sleeps == [2, 4]
    assert logs == ["ntfy: new_pairing not sent (HTTP 500)"]
    post = Post([401])
    n, logs, sleeps = _sender(post)
    assert n.send(_rec()) == "failed" and len(post.calls) == 1 and sleeps == []


def test_token_and_topic_never_logged():
    err = requests.ConnectionError(f"HTTPSConnectionPool(host='ntfy.sh'): /{TOPIC} Bearer {TOKEN}")
    post = Post([err, err, err])
    n, logs, _ = _sender(post)
    n.send(_rec())
    assert logs == ["ntfy: new_pairing not sent (ConnectionError)"]
    assert n.scrub(f"x {TOKEN} {TOPIC}") == "x <hidden> <hidden>"
    for line in logs:
        assert TOKEN not in line and TOPIC not in line


@pytest.fixture
def local_ntfy(monkeypatch):
    """A stand-in for ntfy.sh on 127.0.0.1 (nothing leaves the machine): (port, the requests it got)."""
    import http.server
    import threading
    got = []

    class H(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            got.append((self.path, self.rfile.read(int(self.headers.get("Content-Length") or 0))))
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *a):
            pass
    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    for k in ("NO_PROXY", "no_proxy"):
        monkeypatch.setenv(k, "127.0.0.1,localhost")
    yield srv.server_address[1], got
    srv.shutdown()
    srv.server_close()


def test_urllib3_never_logs_the_topic_at_debug(local_ntfy, caplog):
    """log_level debug sets the root logger to DEBUG, and urllib3 then writes each request line, URL path (the topic)
    included: '"POST /<topic> HTTP/1.1" 200'. A real sender scrubs it."""
    port, got = local_ntfy
    n = NT.Ntfy(TOPIC, TOKEN)  # the real requests.post
    n.url = f"http://127.0.0.1:{port}/{TOPIC}"
    with caplog.at_level(logging.DEBUG):
        assert n.send(_rec()) == "sent"
    assert got and got[0][0] == f"/{TOPIC}"  # the push itself still goes to the topic
    assert '"POST /<hidden> HTTP/1.1" 200' in caplog.text  # the line is there, without the topic
    assert TOPIC not in caplog.text and TOKEN not in caplog.text


def test_only_a_real_sender_installs_the_scrub():
    for name in NT.URLLIB3_LOGGERS:
        logging.getLogger(name).removeFilter(NT.SCRUB)
    _sender(Post())  # a stub post: nothing to scrub
    assert not [n for n in NT.URLLIB3_LOGGERS if NT.SCRUB in logging.getLogger(n).filters]
    NT.Ntfy(TOPIC, TOKEN)
    assert all(NT.SCRUB in logging.getLogger(n).filters for n in NT.URLLIB3_LOGGERS)
    NT.Ntfy(TOPIC, TOKEN)
    assert logging.getLogger(NT.URLLIB3_LOGGERS[0]).filters.count(NT.SCRUB) == 1  # once, however many senders


def test_priority_rule_in_the_header():
    for p, want in (({"fit": "Fits", "far": "OK"}, "5"), ({"fit": "Conflict H1", "far": "OK"}, "3"),
                    ({"fit": "Fits", "far": "?"}, "3")):
        post = Post()
        _sender(post)[0].send(_rec(**p))
        assert post.calls[0]["headers"]["Priority"] == want
    post = Post()
    _sender(post)[0].send(PT.event_record("recall_miss", {"id": "2026-11-03|H1|recall", "verdict": "MISSED"}, 1, "t"))
    assert post.calls[0]["headers"]["Priority"] == "4"


# ---------------------------------------------------------------- the Watcher's side
def _sealed_settings(W, fields):
    return json.dumps(SEAL.seal(SEAL.public_info(W.settings_key())["pubkey"], fields))


def test_ntfy_settings_sealed_only_and_portal_only(portal_pilot, monkeypatch, caplog):
    W, _ = portal_pilot("pilot2")
    monkeypatch.setattr(W, "restart_later", lambda: None)
    W.settings_cmd(json.dumps({"ntfy_topic": TOPIC, "ntfy_token": TOKEN}))  # plain: never
    assert "ntfy_topic" not in W.load_creds()
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        assert W.settings_cmd(_sealed_settings(W, {"ntfy_topic": TOPIC, "ntfy_token": TOKEN}))
        W.settings_cmd(_sealed_settings(W, {"ntfy_topic": "bad/topic"}))
    c = W.load_creds()
    assert c["ntfy_topic"] == TOPIC and c["ntfy_token"] == TOKEN
    assert TOKEN not in caplog.text and TOPIC not in caplog.text
    st = W.settings_state()
    assert st["ntfy"] is True and st["has_ntfy_topic"] and st["has_ntfy_token"]
    assert TOKEN not in json.dumps(st) and TOPIC not in json.dumps(st)
    W.portal_start(threads=False)
    assert isinstance(W.EXPORT["ntfy"], NT.Ntfy)
    W.portal_export_once(full=True)
    key = PT.public_id(PT.load_key(W.PORTAL_KEY_FILE))
    man = json.loads(PT.verify(key, json.load(open(os.path.join(W.PORTAL_DIR, "out", "manifest.json"))), "manifest"))
    assert man["ntfy"] is True


def test_admin_never_posts(portal_pilot, monkeypatch):
    W, _ = portal_pilot("", portal=True)
    posts = []
    monkeypatch.setattr(NT.requests, "post", lambda *a, **k: posts.append(a))
    monkeypatch.setattr(W, "restart_later", lambda: None)
    W.settings_cmd(_sealed_settings(W, {"ntfy_topic": TOPIC, "ntfy_token": TOKEN}))
    assert "ntfy_topic" not in W.load_creds()  # the admin never even stores them
    json.dump({"ntfy_topic": TOPIC, "ntfy_token": TOKEN}, open(W.CREDS_FILE, "w"))  # planted all the same
    for name in NT.URLLIB3_LOGGERS:
        logging.getLogger(name).removeFilter(NT.SCRUB)
    assert W.portal_start() is False and W.EXPORT["ntfy"] is None
    assert not [n for n in NT.URLLIB3_LOGGERS if NT.SCRUB in logging.getLogger(n).filters]  # urllib3 as in 1.5.0
    W.set_machine("stopped_unexpected", "x")
    W.pub("event/new_pairing", {"pairing": "H9001", "fit": "Fits", "far": "OK"}, retain=False)
    assert posts == [] and "ntfy" not in W.settings_state()


def test_one_push_per_machine_state_and_per_event(portal_pilot):
    W, _ = portal_pilot("pilot2")
    W.portal_start(threads=False)
    sent = []
    W.EXPORT["ntfy"] = type("N", (), {"enqueue": lambda self, rec: sent.append(rec)})()
    W.set_machine("needs_settings", "a")
    W.set_machine("needs_settings", "b")
    W.set_machine("idle", "")
    W.set_machine("hunting", "")
    W.set_machine("stopped_unexpected", "c")
    W.set_machine("stopped_unexpected", "d")
    W.pub("event/new_pairing", {"pairing": "H9001", "fit": "Fits", "far": "OK"}, retain=False)
    W.pub("event/swap", {"pairing": "H9001"}, retain=False)  # not a portal event
    W.pub("last_new", {"pairing": "H9001"})  # a state, not an event
    assert [r["kind"] for r in sent] == ["needs_settings", "stopped_*", "new_pairing"]
    assert sent[-1]["priority"] == 5 and sent[0]["view"] == "settings"


def test_ntfy_off_with_a_bad_saved_token(portal_pilot, caplog):
    W, _ = portal_pilot("pilot2")
    json.dump({"ntfy_topic": TOPIC, "ntfy_token": "bad token with spaces"}, open(W.CREDS_FILE, "w"))
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        W.portal_start(threads=False)
    assert W.EXPORT["ntfy"] is None and "ntfy off: the saved topic or token is not usable" in caplog.text
    assert "bad token" not in caplog.text


# ---------------------------------------------------------------- the settings card
CARD = os.path.join(HERE, "..", "www", "flight-watcher-settings-card.js")
HARNESS = r"""
globalThis.HTMLElement = class {
  attachShadow() {
    const els = {};
    const root = {
      _html: "", _inputs: [],
      set innerHTML(v) { this._html = v; this._inputs = [...v.matchAll(/<input type="(\w+)" data-k="([a-z_]+)"/g)].map((m) => ({ type: m[1], dataset: { k: m[2] }, value: "" })); },
      get innerHTML() { return this._html; },
      getElementById(id) { return els[id] || (els[id] = { addEventListener() {}, innerHTML: "", textContent: "" }); },
      querySelector() { return null; },
      querySelectorAll(sel) { return sel === "input[data-k]" ? this._inputs : sel === "input[type=password]" ? this._inputs.filter((i) => i.type === "password") : []; },
    };
    this.shadowRoot = root;
    return root;
  }
};
globalThis.customElements = { define() {} };
globalThis.window = {};
"""


def _node(body, src=None):
    if not shutil.which("node"):
        pytest.skip("node not installed")
    js = HARNESS + (src or open(CARD, encoding="utf-8").read()) + "\n(async () => {\n" + body + "\n})();"
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, "t.js")
        open(f, "w", encoding="utf-8").write(js)
        out = subprocess.run(["node", f], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_card_hides_ntfy_on_ryans_card_and_never_sends_it_plain():
    r = _node("""
const calls = [];
const hass = (ent, attrs) => ({ states: { [ent]: { attributes: attrs } }, callService: async (d, s, data) => calls.push(data) });
const ryan = new FlightWatcherSettingsCard();
ryan.setConfig({});
ryan.hass = hass("sensor.flight_watcher_settings", { username: "doej", has_password: true, pubkey: "x" });
const jp = new FlightWatcherSettingsCard();
jp.setConfig({ entity: "sensor.flight_watcher_pilot2_settings", topic: "flight_watcher_pilot2/settings/set" });
jp.hass = hass("sensor.flight_watcher_pilot2_settings", { has_password: false });
const before = jp.shadowRoot.innerHTML.includes("ntfy");
jp.hass = hass("sensor.flight_watcher_pilot2_settings", { has_password: false, ntfy: true, has_ntfy_topic: false });
const after = jp.shadowRoot.innerHTML.includes('data-k="ntfy_token"') && jp.shadowRoot.innerHTML.includes('data-k="ntfy_topic"');
// plain http (no WebCrypto here): the ntfy fields are dropped, the rest goes
const set = (card, k, v) => card.shadowRoot._inputs.find((i) => i.dataset.k === k).value = v;
set(jp, "ntfy_topic", "fw-test-topic-0001-synthetic00"); set(jp, "ntfy_token", "tk_faketokenfaketokenfaketoken0"); set(jp, "password", "pw-x");
await jp._save();
const sent = calls.map((c) => c.payload);
// only ntfy fields: nothing goes, and the card says why
set(jp, "ntfy_topic", "fw-test-topic-0001-synthetic00"); set(jp, "ntfy_token", "tk_faketokenfaketokenfaketoken0");
await jp._save();
console.log(JSON.stringify({ ryan: ryan.shadowRoot.innerHTML.includes("ntfy"), before, after, sent, n: calls.length,
  msg: jp.shadowRoot.getElementById("msg").innerHTML }));
""")
    assert r["ryan"] is False and r["before"] is False and r["after"] is True
    assert r["n"] == 1 and json.loads(r["sent"][0]) == {"password": "pw-x"}
    assert "ntfy" not in r["sent"][0] and "tk_" not in r["sent"][0]
    assert "encrypted only" in r["msg"]


def _portal_copy():
    """The pilot's settings card exactly as its portal serves it (watcher.portal_cards)."""
    import cards
    return PT.portal_card(cards.pilot_copy(open(CARD, encoding="utf-8").read(), "pilot2"))


SAVE_CASES = """
const calls = [];
const ENT = "sensor.flight_watcher_pilot2_settings";
const hass = (attrs) => ({ states: attrs ? { [ENT]: { attributes: attrs } } : {},
                           callService: async (d, s, data) => calls.push(data) });
const set = (card, k, v) => card.shadowRoot._inputs.find((i) => i.dataset.k === k).value = v;
const run = async (attrs, crypto) => {
  window.crypto = crypto ? globalThis.crypto : undefined;
  const c = new FlightWatcherSettingsCard();
  c.setConfig({ entity: ENT, topic: "flight_watcher_pilot2/settings/set" });
  c.hass = hass(attrs);
  set(c, "username", "doej"); set(c, "password", "pw-synthetic-0001");
  const n = calls.length;
  await c._save();
  return { sent: calls.slice(n).map((x) => x.payload), msg: c.shadowRoot.getElementById("msg").innerHTML,
           disabled: c.shadowRoot.getElementById("save").disabled };
};
const kp = await globalThis.crypto.subtle.generateKey({ name: "RSA-OAEP", modulusLength: 2048,
  publicExponent: new Uint8Array([1, 0, 1]), hash: "SHA-256" }, true, ["encrypt", "decrypt"]);
const spki = Buffer.from(await globalThis.crypto.subtle.exportKey("spki", kp.publicKey)).toString("base64");
console.log(JSON.stringify({
  missing: await run(null, true),                                      // the sensor not in state.json yet
  nokey: await run({ has_password: false }, true),                     // present, no pubkey (restored / unknown)
  nocrypto: await run({ has_password: false }, false),                 // not a secure context
  sealed: await run({ has_password: false, pubkey: spki, kid: "k1" }, true),
}));
"""


def test_portal_settings_card_never_sends_a_login_unsealed():
    """In the portal the card sends a login sealed or not at all: before the Watcher's key is in state.json (the
    settings sensor not exported yet, or exported without its pubkey) or without WebCrypto, Save is disabled and sends
    nothing, so no password ever reaches the portal process in clear. With the key it seals as before."""
    r = _node(SAVE_CASES, _portal_copy())
    for case in ("missing", "nokey"):
        assert r[case]["sent"] == [] and r[case]["disabled"] is True, case
        assert "key has not loaded yet" in r[case]["msg"] and "Nothing was sent" in r[case]["msg"], case
    assert r["nocrypto"]["sent"] == [] and "encrypted only" in r["nocrypto"]["msg"]
    assert len(r["sealed"]["sent"]) == 1 and r["sealed"]["disabled"] is False
    body = json.loads(r["sealed"]["sent"][0])
    assert list(body) == ["enc"] and body["enc"]["kid"] == "k1" and "pw-synthetic" not in r["sealed"]["sent"][0]


def test_deployed_cards_keep_the_1_5_0_fallback():
    """The cards deployed under /local/ (Ryan's and a pilot's HA dashboard copy) are unchanged: on a page with
    WebCrypto but no key yet they still send plain, as Ryan accepted for his trusted users."""
    import cards
    src = open(CARD, encoding="utf-8").read()
    assert PT.PORTAL_CARD_FLAG[0] in src and PT.PORTAL_CARD_FLAG[1] not in src
    for text in (src, cards.pilot_copy(src, "pilot2")):
        r = _node(SAVE_CASES, text)
        assert json.loads(r["nokey"]["sent"][0]) == {"username": "doej", "password": "pw-synthetic-0001"}
        assert "not encrypted on this address" in r["nokey"]["msg"] and r["nokey"].get("disabled") is not True
        assert json.loads(r["sealed"]["sent"][0])["enc"]["kid"] == "k1"
