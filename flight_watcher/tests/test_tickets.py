"""0.10.1 tickets: numbering, image validation, actions, per-instance listing (synthetic data only)."""
import base64
import json
import sys

import pytest

import tickets as TK

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 20
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20


def _url(raw, mime="image/jpeg"):
    return f"data:{mime};base64," + base64.b64encode(raw).decode()


def test_numbering_shared_and_folder_safe(tmp_path):
    b = str(tmp_path)
    t1, _ = TK.create(b, {"kind": "bug", "title": "Card blank", "narrative": "The card shows nothing."}, "ryan", "t1")
    t2, _ = TK.create(b, {"kind": "feature", "title": "Dark mode", "narrative": "Please."}, "james", "t2")
    assert (t1["id"], t2["id"]) == ("FW-0001", "FW-0002")
    assert (tmp_path / "counter").read_text() == "2"
    (tmp_path / "counter").write_text("0")  # a lost counter never reuses a number
    t3, _ = TK.create(b, {"kind": "bug", "title": "x", "narrative": "y"}, "ryan", "t3")
    assert t3["id"] == "FW-0003"
    j = json.loads((tmp_path / "FW-0001" / "ticket.json").read_text())
    assert j["status"] == "new" and j["created_at"] == "t1" and j["history"] == [] and j["reporter"] == "ryan"


def test_validation_and_images(tmp_path):
    b = str(tmp_path)
    assert TK.create(b, {"kind": "idea", "title": "x", "narrative": "y"}, "ryan", "t")[1] == "kind must be bug or feature"
    assert TK.create(b, {"kind": "bug", "title": "", "narrative": "y"}, "ryan", "t")[1] == "title is required"
    assert TK.create(b, {"kind": "bug", "title": "x", "narrative": "y", "image": _url(b"GIF89a....")}, "ryan", "t")[1] == "image is not a JPEG or PNG"
    big = b"\xff\xd8\xff" + b"\x00" * (2 * 1024 * 1024)
    assert TK.create(b, {"kind": "bug", "title": "x", "narrative": "y", "image": _url(big)}, "ryan", "t")[1] == "image over 2 MB"
    assert not list(tmp_path.glob("FW-*"))  # refused tickets use no number
    t, _ = TK.create(b, {"kind": "bug", "title": "x", "narrative": "y", "image": _url(JPEG)}, "ryan", "t")
    assert t["image"] == "screenshot.jpg" and (tmp_path / t["id"] / "screenshot.jpg").read_bytes() == JPEG
    t, _ = TK.create(b, {"kind": "bug", "title": "x", "narrative": "y", "image": _url(PNG, "image/png")}, "ryan", "t")
    assert t["image"] == "screenshot.png"
    assert TK.listing(b)["tickets"][0]["has_image"] is True


def test_actions(tmp_path):
    b = str(tmp_path)
    t, _ = TK.create(b, {"kind": "bug", "title": "x", "narrative": "y"}, "james", "t0")
    tid = t["id"]
    assert TK.act(b, {"id": tid, "action": "verify"}, "ryan", "t1")[1] == f"{tid} is new, not fixed"
    for action, st in (("triage", "triaged"), ("progress", "in_progress"), ("note", "in_progress")):
        assert TK.act(b, {"id": tid, "action": action, "text": "looking"}, "ryan", "t1")[0]["status"] == st
    t, _ = TK.act(b, {"id": tid, "action": "fixed", "version": "0.10.2"}, "ryan", "t2")
    assert t["status"] == "fixed" and t["version_fixed"] == "0.10.2"
    t, _ = TK.act(b, {"id": tid, "action": "verify"}, "james", "t3")
    assert t["status"] == "closed" and t["updated_at"] == "t3"
    assert TK.act(b, {"id": tid, "action": "triage"}, "ryan", "t4")[1] == f"{tid} is closed"
    t, _ = TK.act(b, {"id": tid, "action": "reopen", "text": "back again"}, "james", "t5")
    assert t["status"] == "reopened"
    h = t["history"]
    assert [x["action"] for x in h] == ["triage", "progress", "note", "fixed", "verify", "reopen"]
    assert h[3]["version"] == "0.10.2" and h[4]["actor"] == "james" and h[5]["text"] == "back again" and h[0]["to"] == "triaged"
    assert TK.act(b, {"id": tid, "action": "close"}, "ryan", "t6", allowed_reporter="maria")[1] == f"{tid} is not maria's ticket"
    assert TK.act(b, {"id": "FW-9999", "action": "close"}, "ryan", "t6")[1] == "FW-9999 not found"
    assert TK.act(b, {"id": tid, "action": "explode"}, "ryan", "t6")[1] == "unknown action explode"


def _files(d):
    return sorted(p.name for p in d.iterdir() if p.name != "ticket.json")


def test_photos_one_message_each(tmp_path):
    """FW-0003: the ticket first (cid + count), then each photo on its own; stored in photo order."""
    b = str(tmp_path)
    t, err = TK.create(b, {"kind": "bug", "title": "x", "narrative": "y", "cid": "c0ffee01", "images": 3}, "ryan", "t0")
    assert err == "" and t["images"] == [] and t["image"] == "" and t["images_expected"] == 3
    d = tmp_path / t["id"]
    t, _ = TK.add_image(b, {"cid": "c0ffee01", "i": 2, "image": _url(PNG, "image/png")}, "ryan", "t1")
    assert t["images"] == ["screenshot_2.png"] and t["image"] == "screenshot_2.png"  # arrived out of order
    t, _ = TK.add_image(b, {"cid": "c0ffee01", "i": 1, "image": _url(JPEG)}, "ryan", "t2")
    t, _ = TK.add_image(b, {"cid": "c0ffee01", "i": 3, "image": _url(JPEG)}, "ryan", "t3")
    assert t["images"] == ["screenshot.jpg", "screenshot_2.png", "screenshot_3.jpg"]
    assert t["image"] == "screenshot.jpg" and t["updated_at"] == "t3"  # "image" stays photo 1 for older readers
    assert _files(d) == ["screenshot.jpg", "screenshot_2.png", "screenshot_3.jpg"]
    assert (d / "screenshot_2.png").read_bytes() == PNG
    j = json.loads((d / "ticket.json").read_text())
    assert j["images"] == t["images"] and j["image"] == "screenshot.jpg"
    s = TK.listing(b)["tickets"][0]
    assert s["image_count"] == 3 and s["has_image"] is True
    # refused, nothing written: a 4th past the count, a repeat, a bad number
    assert TK.add_image(b, {"cid": "c0ffee01", "i": 4, "image": _url(JPEG)}, "ryan", "t4")[1] == f"{t['id']} takes 3 photos, not photo 4"
    assert TK.add_image(b, {"cid": "c0ffee01", "i": 2, "image": _url(JPEG)}, "ryan", "t4")[1] == f"{t['id']} already has photo 2"
    assert TK.add_image(b, {"cid": "c0ffee01", "i": "two", "image": _url(JPEG)}, "ryan", "t4")[1] == "bad photo number"
    assert _files(d) == ["screenshot.jpg", "screenshot_2.png", "screenshot_3.jpg"]
    assert json.loads((d / "ticket.json").read_text())["updated_at"] == "t3"


def test_photos_unknown_cid_and_checks(tmp_path):
    b = str(tmp_path)
    t, _ = TK.create(b, {"kind": "feature", "title": "x", "narrative": "y", "cid": "abc123XY", "images": 2}, "ryan", "t0")
    d = tmp_path / t["id"]
    before = (d / "ticket.json").read_text()
    # unknown cid, someone else's ticket, a malformed cid, not a dict: ignored, nothing written anywhere
    assert TK.add_image(b, {"cid": "nobody99", "i": 1, "image": _url(JPEG)}, "ryan", "t1")[1] == "no ticket for that photo"
    assert TK.add_image(b, {"cid": "abc123XY", "i": 1, "image": _url(JPEG)}, "james", "t1")[1] == "no ticket for that photo"
    assert TK.add_image(b, {"cid": "../../etc", "i": 1, "image": _url(JPEG)}, "ryan", "t1")[1] == "bad cid"
    assert TK.add_image(b, "not a dict", "ryan", "t1")[1] == "not an object"
    assert TK.add_image(str(tmp_path / "none"), {"cid": "abc123XY", "i": 1, "image": _url(JPEG)}, "ryan", "t1")[1] == "no ticket for that photo"
    # the per-image size and magic-byte checks still apply to every photo
    assert TK.add_image(b, {"cid": "abc123XY", "i": 1, "image": _url(b"GIF89a....")}, "ryan", "t1")[1] == "image is not a JPEG or PNG"
    big = b"\xff\xd8\xff" + b"\x00" * (2 * 1024 * 1024)
    assert TK.add_image(b, {"cid": "abc123XY", "i": 1, "image": _url(big)}, "ryan", "t1")[1] == "image over 2 MB"
    assert TK.add_image(b, {"cid": "abc123XY", "i": 1}, "ryan", "t1")[1] == "image is not a JPEG or PNG"
    assert _files(d) == [] and (d / "ticket.json").read_text() == before
    assert [p.name for p in tmp_path.iterdir() if p.name.startswith("FW-")] == [t["id"]]
    # a ticket filed without a cid takes no later photos; an unusable cid is dropped, the ticket still files
    t2, _ = TK.create(b, {"kind": "bug", "title": "x", "narrative": "y", "images": 5}, "ryan", "t2")
    t3, _ = TK.create(b, {"kind": "bug", "title": "x", "narrative": "y", "cid": "a b", "images": 5}, "ryan", "t3")
    assert (t2["cid"], t2["images_expected"], t3["cid"], t3["images_expected"]) == ("", 0, "", 0)


def test_photos_cap_ten(tmp_path):
    b = str(tmp_path)
    t, _ = TK.create(b, {"kind": "bug", "title": "x", "narrative": "y", "cid": "tenphotos", "images": 25}, "ryan", "t0")
    assert t["images_expected"] == 10
    t0, _ = TK.create(b, {"kind": "bug", "title": "x", "narrative": "y", "cid": "nocount1"}, "ryan", "t0")
    assert t0["images_expected"] == 10  # a cid with no count may send up to the cap
    for i in range(1, 11):
        t, err = TK.add_image(b, {"cid": "tenphotos", "i": i, "image": _url(JPEG)}, "ryan", f"t{i}")
        assert err == ""
    assert t["images"] == ["screenshot.jpg"] + [f"screenshot_{i}.jpg" for i in range(2, 11)]
    assert TK.add_image(b, {"cid": "tenphotos", "i": 11, "image": _url(JPEG)}, "ryan", "t11")[1] == "photo number must be 1 to 10"
    assert TK.add_image(b, {"cid": "tenphotos", "i": 0, "image": _url(JPEG)}, "ryan", "t11")[1] == "photo number must be 1 to 10"
    assert len(list((tmp_path / t["id"]).glob("screenshot*"))) == 10
    assert TK.listing(b)["tickets"][1]["image_count"] == 10


def test_photos_old_readers_and_inline_first(tmp_path):
    b = str(tmp_path)
    # a card from before FW-0003: one image inline on ticket/new, no cid
    t, _ = TK.create(b, {"kind": "bug", "title": "x", "narrative": "y", "image": _url(JPEG)}, "ryan", "t0")
    assert (t["image"], t["images"], t["images_expected"]) == ("screenshot.jpg", ["screenshot.jpg"], 1)
    # inline photo 1 plus a cid: later photos start at 2
    t, _ = TK.create(b, {"kind": "bug", "title": "x", "narrative": "y", "image": _url(JPEG), "cid": "mixed001", "images": 3}, "ryan", "t1")
    assert TK.add_image(b, {"cid": "mixed001", "i": 1, "image": _url(JPEG)}, "ryan", "t2")[1] == f"{t['id']} already has photo 1"
    t, _ = TK.add_image(b, {"cid": "mixed001", "i": 3, "image": _url(PNG)}, "ryan", "t2")
    assert t["images"] == ["screenshot.jpg", "screenshot_3.png"]
    # a ticket.json written before FW-0003 has only "image"
    old = {"id": "FW-0099", "kind": "bug", "title": "old", "status": "new", "reporter": "ryan", "image": "screenshot.png"}
    assert TK.images(old) == ["screenshot.png"] and TK.summary(old)["image_count"] == 1 and TK.summary(old)["has_image"]
    assert TK.summary({**old, "image": ""})["image_count"] == 0


@pytest.mark.parametrize("bad", [float("inf"), float("-inf"), float("nan"), "Infinity", None, [3], {"n": 3}])
def test_photos_counts_that_are_not_numbers(tmp_path, bad):
    """json.loads takes Infinity and 1e999 (float inf); int() of those raises OverflowError, not ValueError."""
    b = str(tmp_path)
    t, err = TK.create(b, {"kind": "bug", "title": "x", "narrative": "y", "cid": "abcdef12", "images": bad}, "ryan", "t0")
    assert err == "" and t["images_expected"] == 10  # an unusable count: the cap
    assert TK.add_image(b, {"cid": "abcdef12", "i": bad, "image": _url(JPEG)}, "ryan", "t1")[1] == "bad photo number"
    assert _files(tmp_path / t["id"]) == []


def test_photos_infinity_from_json(tmp_path):
    b = str(tmp_path)
    d = json.loads('{"kind": "bug", "title": "x", "narrative": "y", "cid": "abcdef12", "images": Infinity}')
    t, err = TK.create(b, d, "ryan", "t0")
    assert err == "" and t["images_expected"] == 10
    for raw in ('{"cid": "abcdef12", "i": Infinity, "image": "x"}', '{"cid": "abcdef12", "i": 1e999, "image": "x"}',
                '{"cid": "abcdef12", "i": -Infinity, "image": "x"}', '{"cid": "abcdef12", "i": NaN, "image": "x"}'):
        assert TK.add_image(b, json.loads(raw), "ryan", "t1")[1] == "bad photo number"
    t, err = TK.add_image(b, {"cid": "abcdef12", "i": 1.0, "image": _url(JPEG)}, "ryan", "t2")
    assert err == "" and t["images"] == ["screenshot.jpg"]


def test_listing_filter(tmp_path):
    b = str(tmp_path)
    TK.create(b, {"kind": "bug", "title": "a", "narrative": "n" * 900}, "ryan", "t1")
    TK.create(b, {"kind": "feature", "title": "b", "narrative": "n"}, "james", "t2")
    TK.act(b, {"id": "FW-0002", "action": "close"}, "ryan", "t3")
    allx = TK.listing(b)
    assert [r["id"] for r in allx["tickets"]] == ["FW-0002", "FW-0001"] and allx["total"] == 2 and allx["open"] == 1
    assert len(allx["tickets"][1]["narrative"]) == 500 and allx["tickets"][0]["history_count"] == 1
    mine = TK.listing(b, "james")
    assert [r["id"] for r in mine["tickets"]] == ["FW-0002"] and mine["open"] == 0


@pytest.fixture
def W(tmp_path, monkeypatch):
    monkeypatch.setenv("FLIGHT_WATCHER_DATA", str(tmp_path))
    (tmp_path / "options.json").write_text(json.dumps({"username": "u", "password": "p"}))
    sys.modules.pop("watcher", None)
    import watcher as W
    monkeypatch.setattr(W, "TICKETS_DIR", str(tmp_path / "tickets"))
    sent = []
    monkeypatch.setattr(W, "pub", lambda t, p, retain=True: sent.append((t, p, retain)))
    W.SENT = sent
    return W


def test_watcher_ticket_flow(W, monkeypatch):
    W.ticket_new(json.dumps({"kind": "bug", "title": "Finds empty", "narrative": "No rows.", "image": _url(JPEG)}))
    ev = [(p, r) for t, p, r in W.SENT if t == "event/ticket_new"]
    assert ev == [({"id": "FW-0001", "kind": "bug", "title": "Finds empty", "reporter": "ryan"}, False)]
    lst = [(p, r) for t, p, r in W.SENT if t == "tickets"][-1]
    assert lst[1] is True and lst[0]["open"] == 1 and lst[0]["tickets"][0]["has_image"]
    W.ticket_new("not json")
    assert [p for t, p, _ in W.SENT if t == "event/ticket_error"][-1]["error"] == "not an object"
    seen = TK.signature(W.TICKETS_DIR)  # what Ryan's process last published
    # the second pilot's instance files one and sees only its own; Ryan's re-scan picks it up
    monkeypatch.setattr(W, "INSTANCE", "james")
    W.ticket_new(json.dumps({"kind": "feature", "title": "Push on pickup", "narrative": "Please."}))
    assert [p for t, p, _ in W.SENT if t == "tickets"][-1]["tickets"][0]["reporter"] == "james"
    assert [p for t, p, _ in W.SENT if t == "tickets"][-1]["total"] == 1
    assert W.ticket_act(json.dumps({"id": "FW-0001", "action": "close"})) is None  # not James's
    monkeypatch.setattr(W, "INSTANCE", "")
    W.TICKETS_SIG["sig"] = seen  # back in Ryan's process, which has not seen James's file yet
    n = len(W.SENT)
    W.publish_tickets()
    assert [p for t, p, _ in W.SENT[n:] if t == "tickets"][-1]["total"] == 2
    n = len(W.SENT)
    W.publish_tickets()  # nothing changed: no publish
    assert len(W.SENT) == n
    t = W.ticket_act(json.dumps({"id": "FW-0002", "action": "triage", "text": "next release"}))
    assert t["status"] == "triaged" and t["history"][0]["actor"] == "ryan"


def test_watcher_ticket_photos(W, monkeypatch):
    """FW-0003: ticket/new with a cid, then one ticket/image message per photo; an unknown cid is ignored."""
    W.ticket_new(json.dumps({"kind": "bug", "title": "Grid blank", "narrative": "Nothing.", "cid": "card0001", "images": 2}))
    assert [p for t, p, _ in W.SENT if t == "tickets"][-1]["tickets"][0]["image_count"] == 0
    for i, (raw, mime) in ((1, (JPEG, "image/jpeg")), (2, (PNG, "image/png"))):
        t = W.ticket_image(json.dumps({"cid": "card0001", "i": i, "n": 2, "image": _url(raw, mime)}))
        assert t and t["id"] == "FW-0001"
    lst = [p for t, p, _ in W.SENT if t == "tickets"][-1]
    assert lst["tickets"][0]["image_count"] == 2 and lst["tickets"][0]["has_image"]
    n = len(W.SENT)
    assert W.ticket_image(json.dumps({"cid": "stranger", "i": 1, "image": _url(JPEG)})) is None
    assert W.ticket_image("not json") is None
    errs = [p["error"] for t, p, _ in W.SENT[n:] if t == "event/ticket_error"]
    assert errs == ["no ticket for that photo", "not an object"]
    assert not [1 for t, p, _ in W.SENT[n:] if t == "tickets"]  # nothing changed, nothing re-listed
    # the second pilot's instance cannot add photos to Ryan's ticket even with its cid
    monkeypatch.setattr(W, "INSTANCE", "james")
    assert W.ticket_image(json.dumps({"cid": "card0001", "i": 2, "image": _url(JPEG)})) is None
    assert TK.load(W.TICKETS_DIR, "FW-0001")["images"] == ["screenshot.jpg", "screenshot_2.png"]


def test_on_message_routes_ticket_image(W, monkeypatch):
    got = []
    monkeypatch.setattr(W, "ticket_image", got.append)
    msg = type("M", (), {"topic": f"{W.T}/ticket/image", "payload": b'{"cid": "card0001"}'})()
    W.on_message(None, None, msg)
    assert got == ['{"cid": "card0001"}']


def test_watcher_ticket_infinity_files_and_is_ignored(W):
    """A hand-made ticket/new or ticket/image with Infinity must not raise out of on_message (paho would end the
    MQTT loop thread): the ticket files with the cap, the photo is refused."""
    def msg(topic, raw):
        return type("M", (), {"topic": f"{W.T}/{topic}", "payload": raw.encode()})()
    W.on_message(None, None, msg("ticket/new", '{"kind": "bug", "title": "x", "narrative": "y", "cid": "abcdef12", "images": Infinity}'))
    assert TK.load(W.TICKETS_DIR, "FW-0001")["images_expected"] == 10
    n = len(W.SENT)
    W.on_message(None, None, msg("ticket/image", '{"cid": "abcdef12", "i": 1e999, "image": "x"}'))
    W.on_message(None, None, msg("ticket/image", '{"cid": "abcdef12", "i": Infinity, "image": "x"}'))
    assert [p["error"] for t, p, _ in W.SENT[n:] if t == "event/ticket_error"] == ["bad photo number", "bad photo number"]


@pytest.mark.parametrize("topic,name", [("ticket/new", "create"), ("ticket/image", "add_image"), ("ticket/act", "act")])
def test_on_message_ticket_errors_never_escape(W, monkeypatch, topic, name):
    """Any exception inside a ticket handler is logged and sent as event/ticket_error, never raised to paho."""
    def boom(*a, **k):
        raise OverflowError("cannot convert float infinity to integer")
    monkeypatch.setattr(W.TK, name, boom)
    msg = type("M", (), {"topic": f"{W.T}/{topic}", "payload": b'{"cid": "abcdef12", "id": "FW-0001"}'})()
    W.on_message(None, None, msg)  # must not raise
    errs = [p for t, p, r in W.SENT if t == "event/ticket_error"]
    assert errs and errs[-1]["error"] == "ticket message failed: OverflowError"
