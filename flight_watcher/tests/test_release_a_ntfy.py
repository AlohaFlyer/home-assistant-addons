"""1.6.2 (Release A item 9, Ryan's decision): ntfy with a topic only, with the guardrails. The token is optional; a
topic must be at least 24 characters with letters and digits (refused with the reason, nothing saved); a topic-only
push carries only the pairing number, the date and the fit (no crew names, employee numbers, URLs, report times, rule
ids, ticket text) and no Click URL; the topic is never logged, never in settings/state or state.json (has_ntfy_topic
and ntfy_topic_ok only); the manifest says ntfy true with a usable topic alone; Turn off forgets it. The Settings card
explains the risk before the first topic, asks for a tick, generates a 32-character random topic shown once, refuses a
weak typed one and offers Rotate. Made-up names, fake topics and tokens only."""
import json
import logging
import os

import pytest

import ntfy as NT
import portal as PT
import sealed as SEAL
from test_ntfy import Post, _node, _portal_copy

TOPIC = "Ab3dEf6hIj9kLm2nOp5qRs8tUv1wXy4z"  # 32, letters and digits (as the card generates)
TOKEN = "tk_faketokenfaketokenfaketoken0"
NAME = "Doe, Jane"


def _rec(kind="new_pairing", **p):
    base = {"pairing": "H9001", "dates": "20NOV-22NOV", "fit": "Fits", "far": "OK", "report": "0715",
            "credit": "12:30", "captain": f"{NAME} (10001)", "rule_id": "sin_layover",
            "detail_url": f"https://ha2.flica.net/x?n={NAME}", "contact": {"name": NAME}, "value": 1234.5}
    return PT.event_record(kind, {**base, **p}, 1, "2026-11-09T20:00:00+00:00")


@pytest.mark.parametrize("topic,ok", [
    (TOPIC, True), ("a" * 23 + "1", True), ("fw-test-topic-0001-synthetic00", True),
    ("a" * 22 + "1", False),  # 23 characters
    ("abcdefghijklmnopqrstuvwxyzab", False), ("123456789012345678901234", False),  # letters only, digits only
    ("Ab3dEf6hIj9kLm2nOp5qRs8t/x", False), ("../" + TOPIC, False), (TOPIC + "x" * 40, False), ("", False), (None, False),
])
def test_topic_rule(topic, ok):
    assert (NT.topic_refusal(topic) == "") is ok
    assert NT.valid(topic) is ok and NT.valid(topic, "") is ok


def test_topic_only_push_says_pairing_date_and_fit_only():
    post = Post()
    n = NT.Ntfy(TOPIC, "", "https://hom.tail0000.ts.net", log=lambda m: None, post=post, sleep=lambda s: None)
    assert n.send(_rec()) == "sent"
    c = post.calls[0]
    h = c["headers"]
    assert c["url"] == f"https://ntfy.sh/{TOPIC}"
    assert "Authorization" not in h and "Click" not in h  # no token, and no URL in a topic-only push
    assert h["Title"] == "New pairing H9001 20NOV-22NOV" and c["data"].decode() == "Fit: Fits"
    blob = json.dumps(h) + c["data"].decode()
    for leak in ("Doe", "Jane", "10001", "flica", "http", "0715", "12:30", "sin_layover", "1234", "Report", "Credit"):
        assert leak not in blob, leak
    post = Post()
    NT.Ntfy(TOPIC, "", log=lambda m: None, post=post).send(_rec("rule_match", pairing="H9002"))
    assert post.calls[0]["headers"]["Title"] == "Rule match H9002 20NOV-22NOV"  # no rule id
    post = Post()
    NT.Ntfy(TOPIC, "", log=lambda m: None, post=post).send(PT.event_record(
        "recall_miss", {"id": "2026-11-03|H3601|recall", "verdict": "MISSED", "date": "2026-11-03", "pairing": "H3601",
                        "why": f"went to #900 ({NAME})"}, 2, "t"))
    c = post.calls[0]
    assert c["headers"]["Title"] == "Recall/O75 to check H3601 2026-11-03" and NAME not in json.dumps(c["headers"])
    assert "900" not in c["data"].decode() and NAME not in c["data"].decode()


def test_with_a_token_the_1_6_0_push_is_unchanged():
    post = Post()
    n = NT.Ntfy(TOPIC, TOKEN, "https://hom.tail0000.ts.net", log=lambda m: None, post=post)
    n.send(_rec())
    h = post.calls[0]["headers"]
    assert h["Authorization"] == f"Bearer {TOKEN}" and h["Click"] == "https://hom.tail0000.ts.net/fw/#watcher"
    assert "Report 0715" in post.calls[0]["data"].decode()


# ---------------------------------------------------------------- the Watcher's side
def _sealed(W, fields):
    return json.dumps(SEAL.seal(SEAL.public_info(W.settings_key())["pubkey"], fields))


def _manifest(W):
    key = PT.public_id(PT.load_key(W.PORTAL_KEY_FILE))
    return json.loads(PT.verify(key, json.load(open(os.path.join(W.PORTAL_DIR, "out", "manifest.json"))), "manifest"))


def test_topic_only_is_saved_and_turns_ntfy_on(portal_pilot, monkeypatch, caplog):
    W, _ = portal_pilot("pilot2")
    monkeypatch.setattr(W, "restart_later", lambda: None)
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        assert W.settings_cmd(_sealed(W, {"ntfy_topic": TOPIC}))
        W.portal_start(threads=False)
        W.portal_export_once(full=True)
    c = W.load_creds()
    assert c["ntfy_topic"] == TOPIC and "ntfy_token" not in c
    st = W.settings_state()
    assert st["has_ntfy_topic"] is True and st["ntfy_topic_ok"] is True and st["has_ntfy_token"] is False
    assert isinstance(W.EXPORT["ntfy"], NT.Ntfy) and _manifest(W)["ntfy"] is True
    assert "topic only" in caplog.text
    outs = [open(os.path.join(dp, f), encoding="utf-8").read() for dp, _, fs in os.walk(W.PORTAL_DIR) for f in fs]
    pubs = json.dumps([m for m in W.MQ.raw.msgs])
    for text in [caplog.text, json.dumps(st), pubs] + outs:
        assert TOPIC not in text  # never logged, never in settings/state, MQTT or the export


@pytest.mark.parametrize("bad", ["short-topic-1", "abcdefghijklmnopqrstuvwxyzab", "x/" + TOPIC])
def test_a_weak_topic_is_refused_with_the_reason(portal_pilot, monkeypatch, caplog, bad):
    W, _ = portal_pilot("pilot2")
    monkeypatch.setattr(W, "restart_later", lambda: None)
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        assert W.settings_cmd(_sealed(W, {"ntfy_topic": bad, "username": "doej2"})) is False
    assert W.load_creds() == {}  # nothing saved, not even the username
    res = json.loads([p for t, p, *_ in W.MQ.raw.msgs if t.endswith("/settings/state")][-1])["result"]
    assert res.startswith("refused: ntfy topic: ") and res.endswith("nothing was saved")
    assert bad not in caplog.text and bad not in res


def test_a_weak_topic_saved_before_1_6_2_keeps_ntfy_off(portal_pilot, caplog):
    W, _ = portal_pilot("pilot2")
    json.dump({"ntfy_topic": "fw-old-topic"}, open(W.CREDS_FILE, "w"))
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        W.portal_start(threads=False)
    assert W.EXPORT["ntfy"] is None and "generate a new one on Settings" in caplog.text
    st = W.settings_state()
    assert st["has_ntfy_topic"] is True and st["ntfy_topic_ok"] is False and "fw-old-topic" not in caplog.text


def test_turn_off_forgets_topic_and_token(portal_pilot, monkeypatch):
    W, _ = portal_pilot("pilot2")
    monkeypatch.setattr(W, "restart_later", lambda: None)
    json.dump({"ntfy_topic": TOPIC, "ntfy_token": TOKEN, "username": "doej2"}, open(W.CREDS_FILE, "w"))
    assert W.settings_cmd(_sealed(W, {"ntfy_off": True}))
    assert W.load_creds() == {"username": "doej2"}
    W.settings_cmd(json.dumps({"ntfy_off": True, "username": "x"}))  # plain: ntfy keys never move unsealed
    assert "ntfy_topic" not in W.load_creds()


# ---------------------------------------------------------------- the Settings card
CARD_CASES = """
const calls = [];
const ENT = "sensor.flight_watcher_pilot2_settings";
const kp = await globalThis.crypto.subtle.generateKey({ name: "RSA-OAEP", modulusLength: 2048,
  publicExponent: new Uint8Array([1, 0, 1]), hash: "SHA-256" }, true, ["encrypt", "decrypt"]);
const spki = Buffer.from(await globalThis.crypto.subtle.exportKey("spki", kp.publicKey)).toString("base64");
window.crypto = globalThis.crypto;
const mk = (attrs) => {
  const c = new FlightWatcherSettingsCard();
  c.setConfig({ entity: ENT, topic: "flight_watcher_pilot2/settings/set" });
  c.hass = { states: { [ENT]: { attributes: { has_password: true, ntfy: true, pubkey: spki, kid: "k1", ...attrs } } },
             callService: async (d, s, data) => calls.push(data) };
  return c;
};
const inp = (c, k) => c.shadowRoot._inputs.find((i) => i.dataset.k === k);
const out = {};
let c = mk({ has_ntfy_topic: false });
out.html = c.shadowRoot.innerHTML;
c._gen();
out.gen = inp(c, "ntfy_topic").value;
out.shown = c.shadowRoot.getElementById("newtopic").innerHTML;
const g2 = (c._gen(), inp(c, "ntfy_topic").value);
out.distinct = g2 !== out.gen;
let n = calls.length;
await c._save();
out.noack = { sent: calls.length - n, msg: c.shadowRoot.getElementById("msg").innerHTML };
c.shadowRoot.getElementById("ack").checked = true;
inp(c, "ntfy_topic").value = "my-topic-1";
n = calls.length;
await c._save();
out.weak = { sent: calls.length - n, msg: c.shadowRoot.getElementById("msg").innerHTML };
c._gen();
n = calls.length;
await c._save();
out.ok = { sent: calls.length - n, payload: calls[calls.length - 1].payload, after: inp(c, "ntfy_topic").value,
           box: c.shadowRoot.getElementById("newtopic").innerHTML };
c = mk({ has_ntfy_topic: true, ntfy_topic_ok: false });
out.rotate = c.shadowRoot.innerHTML;
console.log(JSON.stringify(out));
"""


def test_card_warns_generates_once_and_refuses_a_weak_topic():
    r = _node(CARD_CASES, _portal_copy())
    assert "Anyone who learns your topic can read your alerts there for about 12 hours" in r["html"]
    assert 'id="ack"' in r["html"] and "Generate topic" in r["html"] and "Rotate topic" not in r["html"]
    t = r["gen"]
    assert len(t) == 32 and NT.topic_refusal(t) == "" and r["distinct"]
    assert t in r["shown"] and "Subscribe to it in the ntfy app now" in r["shown"]
    assert r["noack"]["sent"] == 0 and "tick" in r["noack"]["msg"] and "Nothing was sent" in r["noack"]["msg"]
    assert r["weak"]["sent"] == 0 and "at least 24 characters" in r["weak"]["msg"]
    assert r["ok"]["sent"] == 1 and list(json.loads(r["ok"]["payload"])) == ["enc"]  # sealed, never the topic in clear
    assert t not in r["ok"]["payload"] and r["ok"]["after"] == "" and r["ok"]["box"] == ""  # shown once
    assert "Rotate topic" in r["rotate"] and "too easy to guess" in r["rotate"] and "Turn off phone alerts" in r["rotate"]
    assert 'id="ack"' not in r["rotate"]
