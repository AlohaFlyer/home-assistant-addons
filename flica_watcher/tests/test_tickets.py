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
    monkeypatch.setenv("FLICA_DATA", str(tmp_path))
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
