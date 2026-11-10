"""1.7.0 (Release C): the tickets card in Chromium (node Playwright, tests/tickets_card_render.js). The portal's copy
(FW_PORTAL on) under the HOM portal's exact CSP files a ticket with three made-up 1080 x 2400 screenshots: FileReader
data: URLs (no blob:), three thumbnails, no CSP error, chunks of at most 60,000 base64 characters in order after
ticket/new, each command under the caps, the short side at least 400 px, a chunk turned away once and sent again; the
Watcher's answers on the card; verify with a rid and its answer on the row; a refused send says "Didn't send"; an
over-size text is not sent; edit and delete carry a rid; the Where list names the portal's tabs; no Claude Code
button. Then the same commands go through the pilot's spool and Watcher handlers: one ticket with three re-encoded
photos. The HA copy (Ryan's) keeps its 1.6.x path. Made-up data only."""
import base64
import io
import json
import os
import random
import shutil
import subprocess
import time

import pytest
from PIL import Image, ImageDraw

import cards
import portal as PT
import roles
import tickets as TK

HERE = os.path.dirname(os.path.abspath(__file__))
LIM = roles.PILOT_TICKET_LIMITS


def _shot(path, seed, w=1080, h=2400):
    """A made-up phone screenshot: rows of glyph-like marks on a light page (text-like detail for the JPEG)."""
    rnd = random.Random(seed)
    im = Image.new("RGB", (w, h), (250, 250, 250))
    d = ImageDraw.Draw(im)
    y = 40
    while y < h - 40:
        x = 32
        while x < w - 60:
            gw = rnd.randint(8, 22)
            d.rectangle([x, y, x + gw, y + rnd.randint(14, 24)], fill=(rnd.randint(0, 60),) * 3)
            x += gw + rnd.randint(3, 14)
        y += rnd.randint(34, 52)
    im.save(path, "PNG")


@pytest.fixture(scope="module")
def rendered(tmp_path_factory):
    if not shutil.which("node"):
        pytest.skip("node not installed")
    if subprocess.run(["node", "-e", "require('playwright')"], capture_output=True).returncode:
        pytest.skip("node Playwright not installed")
    d = tmp_path_factory.mktemp("tickets_card")
    for i in range(3):
        _shot(str(d / f"shot{i + 1}.png"), i)
    built = cards.build("1.7.0", ["demo"])
    portal_copy = PT.portal_card(built["flight-watcher-tickets-card-demo.js"])
    ha_copy = built["flight-watcher-tickets-card.js"]
    assert "const FW_PORTAL = true;" in portal_copy and "const FW_PORTAL = false;" in ha_copy
    (d / "portal.js").write_text(portal_copy, encoding="utf-8")
    (d / "ha.js").write_text(ha_copy, encoding="utf-8")
    shots = os.environ.get("FW_TICKETS_SHOTS") or str(d / "out")
    out = subprocess.run(["node", os.path.join(HERE, "tickets_card_render.js"), str(d / "portal.js"), str(d / "ha.js"),
                          str(d), shots], capture_output=True, text=True, timeout=180)
    assert out.returncode == 0, out.stderr
    r = json.loads(out.stdout.strip().splitlines()[-1])
    if r.get("skip"):
        pytest.skip(r["skip"])
    return r


def _portal_pubs(r):
    return [(p["topic"].split("/", 1)[1], p["payload"]) for p in r["portal"]["pubs"]]


def _filed(r):
    """The card's ticket/new and the ticket/image chunks right after it."""
    pubs = _portal_pubs(r)
    n = 1
    while n < len(pubs) and pubs[n][0] == "ticket/image":
        n += 1
    return pubs[:n]


def test_portal_copy_under_the_portal_csp(rendered):
    P = rendered["portal"]
    assert P["cc"] == 0 and P["csp"] == [] and P["errors"] == [] and P["blobs"] == 0
    assert P["thumbs"] == 3 and P["thumb_src"] == ["data:image/jpeg;base64,"] * 3
    assert P["photo_label"] == "Photos (optional, up to 3)"
    assert P["pages"] == ["Watcher", "Schedule", "Pilot", "Recall/O75", "Settings", "Tickets", "Phone alert (ntfy)",
                          "Other"]
    assert all(n <= 360000 for n in P["url_lengths"])
    assert P["fit"]["doc"] <= P["fit"]["win"]


def test_portal_chunks_in_order_and_under_the_caps(rendered):
    pubs = _filed(rendered)
    assert pubs[0][0] == "ticket/new" and len(pubs) - 1 <= 3 * 6  # 360,000 characters a photo: 6 chunks at most
    new = json.loads(pubs[0][1])
    assert new["images"] == 3 and set(new) <= set(roles.TICKET_CMDS["ticket/new"]["keys"])
    PT.check_ticket("ticket/new", pubs[0][1])
    by_photo = {}
    for sub, payload in pubs[1:]:
        d = PT.check_ticket(sub, payload)
        assert d["cid"] == new["cid"] and len(d["data"]) <= LIM["chunk_chars"]
        assert len(json.dumps({"sub": sub, "payload": payload}).encode()) <= 63000  # the card's own cap
        by_photo.setdefault(d["i"], []).append(d)
    assert sorted(by_photo) == [1, 2, 3]
    for i, parts in by_photo.items():
        assert [p["part"] for p in parts] == list(range(1, parts[0]["parts"] + 1))  # in order, no gap, no repeat
        raw = base64.b64decode("".join(p["data"] for p in parts))
        im = Image.open(io.BytesIO(raw))
        assert im.format == "JPEG" and min(im.size) >= 400 and max(im.size) <= 2048


def test_portal_answers_acts_and_refusals(rendered):
    P = rendered["portal"]
    assert P["status_sent"] == "Ticket sent with 3 photos."
    assert P["status_answers"] == ["Ticket sent with 3 photos. FW-0101 filed. Photo 2 not saved: photo is not a JPEG "
                                   "or PNG.", "warn"]
    v = json.loads(P["verify"]["payload"])
    assert P["verify"]["topic"] == "flight_watcher_demo/ticket/act" and v["id"] == "FW-0100" and v["action"] == "verify"
    assert set(v) == {"id", "action", "rid"} and PT.check_ticket("ticket/act", P["verify"]["payload"])
    assert P["verify_row"] == "Sent. Waiting for the Watcher..." and P["verify_done"] == "Verified and closed."
    assert P["reject"] == ["Didn't send: Not available here: test refusal.", "Still broken"]  # one period (review)
    assert P["del_fixed"] == 0  # 1.7.0 review: a pilot deletes a new ticket only
    assert P["too_big"] == "Too long for the portal: shorten the description." and P["too_big_sent"] == 0
    e, dl = json.loads(P["edit"]), json.loads(P["del"])
    assert e == {"id": "FW-0099", "narrative": "The arrows do nothing on the portal.", "rid": e["rid"]}
    assert dl == {"id": "FW-0099", "rid": dl["rid"]}
    PT.check_ticket("ticket/edit", P["edit"])
    PT.check_ticket("ticket/delete", P["del"])
    assert rendered["tiny"] == {"note": "Photo 1 is too detailed for the portal: crop it and add it again.", "imgs": 0}


def test_ha_copy_keeps_its_path(rendered):
    A = rendered["ha"]
    assert A["cc"] == 1 and A["photo_label"] == "Photos (optional, up to 10)" and A["blobs"] == 2
    assert A["del_fixed"] == 1  # Ryan's card deletes in any status, as before
    assert A["pages"] == ["Watcher", "Schedule", "Recall/O75", "Details", "Settings", "Aviation Wx", "Phone alert",
                          "Other"]
    assert [p["topic"] for p in A["pubs"]] == ["flight_watcher/ticket/new"] + ["flight_watcher/ticket/image"] * 2
    assert all(p["keys"] == ["cid", "i", "image", "n"] and p["image"] == "data:image/jpeg;base64," for p in A["pubs"][1:])
    assert A["status"] == "Ticket sent with 2 photos."
    assert json.loads(A["verify"]) == {"id": "FW-0100", "action": "verify"} and A["verify_button"] == "Sent"
    assert A["rowmsg"] == 0


def test_the_portal_commands_through_the_spool_and_the_watcher(rendered, portal_pilot, tmp_path, monkeypatch):
    """End to end without the live Watcher: the card's ticket/new and its chunks as portal command files in the
    pilot's in/, the spool, then the republished payloads through the Watcher's own handlers: one ticket, three photos,
    each re-encoded, his answers on his sensor."""
    W, _ = portal_pilot("demo")
    monkeypatch.setattr(W, "TICKETS_DIR", str(tmp_path / "tickets"))
    assert W.portal_start(threads=False)
    pubs = _filed(rendered)
    now = time.time()
    d = os.path.join(W.PORTAL_DIR, "in")
    for n, (sub, payload) in enumerate(pubs):
        cid = "%016x" % (0xfeed0000 + n)
        ts = int(now * 1000) + n
        body = json.dumps({"fwp": 1, "id": cid, "pilot": "demo", "ts": ts, "sub": sub, "payload": payload,
                           "session": "5e55105e55105e55"})
        assert len(body.encode()) < PT.CAPS["cmd"]
        p = os.path.join(d, f"{ts:013d}-{cid}.json")
        open(p, "w").write(body)
        if os.geteuid() == 0:
            os.chown(p, PT.PORTAL_UID, PT.PORTAL_GID)
    W.EXPORT["spool"].now = lambda: now + 1
    W.MQ.raw.msgs.clear()
    assert W.portal_spool_once() == len(pubs)
    handlers = {"ticket/new": W.ticket_new, "ticket/image": W.ticket_image}
    for t, payload, q, _ in list(W.MQ.raw.msgs):
        sub = t[len(W.T) + 1:]
        if sub in handlers:
            handlers[sub](payload)
    tk = TK.load(W.TICKETS_DIR, "FW-0001")
    assert tk["reporter"] == "demo" and tk["images"] == ["screenshot.jpg", "screenshot_2.jpg", "screenshot_3.jpg"]
    total = 0
    for name in tk["images"]:
        raw = open(os.path.join(W.TICKETS_DIR, "FW-0001", name), "rb").read()
        total += len(raw)
        im = Image.open(io.BytesIO(raw))
        assert im.format == "JPEG" and min(im.size) >= 400 and not im.getexif()
    assert total <= LIM["ticket_bytes"]
    s = json.loads([m for m in W.MQ.raw.msgs if m[0] == f"{W.T}/tickets"][-1][1])
    assert [(a["action"], a["ok"]) for a in s["answers"]][:4] == [("image", True)] * 3 + [("new", True)]
