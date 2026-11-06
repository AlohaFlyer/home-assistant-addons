"""FW-0049 (Ryan): edit a ticket while it is new or reopened, delete it in any status (moved, never destroyed).
Synthetic data only."""
import base64
import json
import os
import shutil
import subprocess
import sys

import pytest

import cards
import tickets as TK

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 20


def _url(raw, mime="image/jpeg"):
    return f"data:{mime};base64," + base64.b64encode(raw).decode()


def _new(b, who="ryan", **kw):
    p = {"kind": "bug", "title": "Grid blank", "narrative": "Nothing shows.", "steps": "Open Schedule",
         "expected": "The grid", "page": "Schedule"}
    p.update(kw)
    return TK.create(b, p, who, "t0")[0]


def test_edit_only_while_new_or_reopened(tmp_path):
    """Edits only before the ticket is worked (new) or after it was reopened; only the fields sent change; the
    history line keeps the replaced text."""
    b = str(tmp_path)
    tid = _new(b)["id"]
    t, err = TK.edit(b, {"id": tid, "title": "  Grid blank on v11.003 ", "narrative": "Nothing shows at all."}, "ryan", "t1")
    assert err == "" and t["title"] == "Grid blank on v11.003" and t["narrative"] == "Nothing shows at all."
    assert (t["steps"], t["expected"], t["page"], t["kind"], t["status"]) == ("Open Schedule", "The grid", "Schedule", "bug", "new")
    assert t["history"][-1] == {"at": "t1", "actor": "ryan", "action": "edit", "from": "new", "to": "new",
                                "fields": ["title", "narrative"],
                                "before": {"title": "Grid blank", "narrative": "Nothing shows."}}
    j = json.loads((tmp_path / tid / "ticket.json").read_text())
    assert j["title"] == "Grid blank on v11.003" and j["updated_at"] == "t1"
    t, _ = TK.edit(b, {"id": tid.lower(), "steps": "", "expected": "", "page": "Details"}, "ryan", "t2")  # blanks allowed here
    assert (t["steps"], t["expected"], t["page"]) == ("", "", "Details")
    t, _ = TK.edit(b, {"id": tid, "title": "x" * 300}, "ryan", "t2")
    assert len(t["title"]) == 200  # cut like create
    # refused, nothing written
    before = (tmp_path / tid / "ticket.json").read_text()
    assert TK.edit(b, {"id": tid, "title": "  "}, "ryan", "t3")[1] == "title is required"
    assert TK.edit(b, {"id": tid, "narrative": None}, "ryan", "t3")[1] == "narrative is required"
    assert TK.edit(b, {"id": tid, "page": "Details"}, "ryan", "t3")[1] == "nothing changed"
    assert TK.edit(b, {"id": tid, "kind": "feature", "status": "closed"}, "ryan", "t3")[1] == "nothing to edit"
    assert TK.edit(b, "not a dict", "ryan", "t3")[1] == "not an object"
    assert TK.edit(b, {"id": "../FW-0001", "title": "y"}, "ryan", "t3")[1] == "bad id"
    assert TK.edit(b, {"id": "FW-9999", "title": "y"}, "ryan", "t3")[1] == "FW-9999 not found"
    assert TK.edit(b, {"id": tid, "title": "y"}, "pilot2", "t3", allowed_reporter="pilot2")[1] == f"{tid} is not pilot2's ticket"
    assert (tmp_path / tid / "ticket.json").read_text() == before
    # once worked: no edits in triaged, in_progress, fixed or closed; reopened takes them again
    for action, st in (("triage", "triaged"), ("progress", "in progress"), ("fixed", "fixed"), ("verify", "closed")):
        TK.act(b, {"id": tid, "action": action}, "ryan", "t4")
        assert TK.edit(b, {"id": tid, "title": "late"}, "ryan", "t5")[1] == f"{tid} is {st}: edits only while new or reopened"
    TK.act(b, {"id": tid, "action": "reopen", "text": "back"}, "ryan", "t6")
    t, err = TK.edit(b, {"id": tid, "narrative": "Back again, worse."}, "ryan", "t7")
    assert err == "" and t["status"] == "reopened" and t["history"][-1]["from"] == "reopened"


def test_edit_pilot_own_ryan_any(tmp_path):
    """A pilot instance edits only its own tickets; Ryan's instance (no allowed_reporter) any."""
    b = str(tmp_path)
    mine, his = _new(b, "ryan")["id"], _new(b, "pilot2")["id"]
    assert TK.edit(b, {"id": mine, "title": "z"}, "pilot2", "t1", allowed_reporter="pilot2")[1] == f"{mine} is not pilot2's ticket"
    assert TK.edit(b, {"id": his, "title": "his fix"}, "pilot2", "t1", allowed_reporter="pilot2")[0]["title"] == "his fix"
    t, _ = TK.edit(b, {"id": his, "title": "typo fixed"}, "ryan", "t2")
    assert t["title"] == "typo fixed" and t["reporter"] == "pilot2" and t["history"][-1]["actor"] == "ryan"


def test_delete_moves_the_folder_any_status(tmp_path):
    """Delete in any status moves the whole folder (photos too) to .deleted/<id>-<stamp>; it leaves every listing and
    the change signature; a photo still on its way is refused; nothing is destroyed."""
    b = str(tmp_path)
    t1 = TK.create(b, {"kind": "bug", "title": "a", "narrative": "n", "image": _url(JPEG)}, "ryan", "t0")[0]
    t2 = _new(b, "pilot2", cid="abcdef12", images=2)
    t3 = _new(b)
    TK.act(b, {"id": t1["id"], "action": "fixed"}, "ryan", "t1")
    TK.act(b, {"id": t1["id"], "action": "verify"}, "ryan", "t1")  # closed (the completed fold): still deletable
    sig = TK.signature(b)
    t, err = TK.delete(b, {"id": t1["id"]}, "ryan", "2026-11-06T20:15:00.123456+00:00")
    assert err == "" and t["status"] == "closed" and t["deleted_by"] == "ryan"
    assert not (tmp_path / t1["id"]).exists()
    gone = tmp_path / ".deleted" / f"{t1['id']}-20261106T201500"
    assert (gone / "screenshot.jpg").read_bytes() == JPEG
    j = json.loads((gone / "ticket.json").read_text())
    assert j["deleted_at"] == "2026-11-06T20:15:00.123456+00:00" and j["history"][-1]["action"] == "delete"
    assert j["history"][-1]["from"] == "closed"
    assert [r["id"] for r in TK.listing(b)["tickets"]] == [t3["id"], t2["id"]] and TK.listing(b)["total"] == 2
    assert TK.signature(b) != sig and TK.load(b, t1["id"]) is None
    # a pilot instance deletes only its own; a photo for a deleted ticket finds no ticket
    assert TK.delete(b, {"id": t3["id"]}, "pilot2", "t2", allowed_reporter="pilot2")[1] == f"{t3['id']} is not pilot2's ticket"
    assert TK.delete(b, {"id": t2["id"]}, "pilot2", "t2", allowed_reporter="pilot2")[0]["id"] == t2["id"]
    assert TK.add_image(b, {"cid": "abcdef12", "i": 1, "image": _url(JPEG)}, "pilot2", "t3")[1] == "no ticket for that photo"
    # refused: twice, bad id, not an object
    assert TK.delete(b, {"id": t1["id"]}, "ryan", "t4")[1] == f"{t1['id']} not found"
    assert TK.delete(b, {"id": ".deleted"}, "ryan", "t4")[1] == "bad id"
    assert TK.delete(b, ["FW-0003"], "ryan", "t4")[1] == "not an object"
    assert (tmp_path / t3["id"]).is_dir()


def test_deleted_numbers_never_come_back(tmp_path):
    """The newest ticket deleted and the counter file lost: the next ticket still takes a new number."""
    b = str(tmp_path)
    _new(b), _new(b)
    TK.delete(b, {"id": "FW-0002"}, "ryan", "t1")
    (tmp_path / "counter").unlink()
    assert _new(b)["id"] == "FW-0003"
    (tmp_path / ".deleted" / "keep me").mkdir()  # anything else in the folder is ignored
    TK.delete(b, {"id": "FW-0003"}, "ryan", "t2")
    (tmp_path / "counter").write_text("1")
    assert TK._next_id(b) == "FW-0004"


def test_deleted_stamp_collision(tmp_path):
    """The same ticket deleted twice with one stamp (a folder put back by hand) gets a folder of its own."""
    b = str(tmp_path)
    _new(b)
    os.makedirs(tmp_path / ".deleted" / "FW-0001-same")  # an earlier deletion with the same stamp
    TK.delete(b, {"id": "FW-0001"}, "ryan", "same")
    assert sorted(p.name for p in (tmp_path / ".deleted").iterdir()) == ["FW-0001-same", "FW-0001-same_2"]
    assert TK._stamp("2026-11-06T20:15:00+00:00") == "20261106T201500" and TK._stamp("") == "x" and TK._stamp("../..") == "x"


def test_listing_editable_rows_carry_the_whole_text(tmp_path):
    """The card's Edit form starts from the listing, so an editable row (new, reopened) carries its whole narrative
    plus steps, expected and page; a worked ticket keeps the short row (page only)."""
    b = str(tmp_path)
    tid = _new(b, narrative="n" * 900)["id"]
    r = TK.listing(b)["tickets"][0]
    assert r["editable"] is True and len(r["narrative"]) == 900
    assert (r["steps"], r["expected"], r["page"]) == ("Open Schedule", "The grid", "Schedule")
    TK.act(b, {"id": tid, "action": "progress"}, "ryan", "t1")
    r = TK.listing(b)["tickets"][0]
    assert r["editable"] is False and len(r["narrative"]) == 500 and r["page"] == "Schedule"
    assert "steps" not in r and "expected" not in r
    TK.act(b, {"id": tid, "action": "fixed"}, "ryan", "t2")
    TK.act(b, {"id": tid, "action": "reopen"}, "ryan", "t3")
    assert TK.listing(b)["tickets"][0]["editable"] is True


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


def test_watcher_ticket_edit_and_delete(W, monkeypatch):
    """Through the Watcher: {T}/ticket/edit and {T}/ticket/delete; the answer rides on the listing as "last" with the
    card's rid; a refusal is also event/ticket_error. A pilot instance touches its own tickets only, Ryan's any."""
    W.ticket_new(json.dumps({"kind": "bug", "title": "Grid blank", "narrative": "Nothing."}))
    assert [p for t, p, _ in W.SENT if t == "tickets"][-1]["last"] == {}  # nothing edited or deleted yet
    monkeypatch.setattr(W, "INSTANCE", "pilot2")
    W.ticket_new(json.dumps({"kind": "feature", "title": "Push on pickup", "narrative": "Please."}))

    def lst(n=0):
        return [p for t, p, _ in W.SENT[n:] if t == "tickets"][-1]
    n = len(W.SENT)
    assert W.ticket_edit(json.dumps({"id": "FW-0001", "rid": "card0001", "title": "mine now"})) is None
    last = lst(n)["last"]
    assert last == {"rid": "card0001", "id": "FW-0001", "action": "edit", "ok": False,
                    "error": "FW-0001 is not pilot2's ticket", "at": last["at"]}
    assert [p["error"] for t, p, _ in W.SENT[n:] if t == "event/ticket_error"] == ["FW-0001 is not pilot2's ticket"]
    assert W.ticket_delete(json.dumps({"id": "FW-0001", "rid": "card0002"})) is None
    assert TK.load(W.TICKETS_DIR, "FW-0001")["title"] == "Grid blank"
    t = W.ticket_edit(json.dumps({"id": "FW-0002", "rid": "card0003", "narrative": "Please, quietly."}))
    assert t["narrative"] == "Please, quietly." and t["history"][-1]["actor"] == "pilot2"
    last = lst()["last"]
    assert (last["rid"], last["ok"], last["error"], last["action"]) == ("card0003", True, "", "edit")
    assert [r["id"] for r in lst()["tickets"]] == ["FW-0002"]  # his listing: his own only
    # Ryan's instance: any ticket
    monkeypatch.setattr(W, "INSTANCE", "")
    t = W.ticket_edit(json.dumps({"id": "FW-0002", "rid": "card0004", "title": "Push on pickup (quiet)"}))
    assert t and t["reporter"] == "pilot2" and t["history"][-1]["actor"] == "ryan"
    W.ticket_act(json.dumps({"id": "FW-0001", "action": "progress"}))
    n = len(W.SENT)
    assert W.ticket_edit(json.dumps({"id": "FW-0001", "rid": "card0005", "title": "late"})) is None
    assert lst(n)["last"]["error"] == "FW-0001 is in progress: edits only while new or reopened"
    t = W.ticket_delete(json.dumps({"id": "FW-0001", "rid": "card0006"}))
    assert t and t["status"] == "in_progress"
    after = lst()
    assert [r["id"] for r in after["tickets"]] == ["FW-0002"] and after["total"] == 1
    assert after["last"]["rid"] == "card0006" and after["last"]["ok"] is True and after["last"]["action"] == "delete"
    # a bad rid is dropped, not echoed; junk never raises
    W.ticket_delete(json.dumps({"id": "FW-0002", "rid": "<script>"}))
    assert lst()["last"]["rid"] == "" and lst()["last"]["ok"] is True
    for junk in ("not json", "[]", "null", '{"id": 5}'):
        assert W.ticket_delete(junk) is None and W.ticket_edit(junk) is None
    assert lst()["last"]["ok"] is False


def test_on_message_routes_ticket_edit_and_delete(W):
    def msg(topic, obj):
        return type("M", (), {"topic": f"{W.T}/{topic}", "payload": json.dumps(obj).encode()})()
    W.on_message(None, None, msg("ticket/new", {"kind": "bug", "title": "x", "narrative": "y"}))
    W.on_message(None, None, msg("ticket/edit", {"id": "FW-0001", "rid": "abcdef12", "title": "x2"}))
    assert TK.load(W.TICKETS_DIR, "FW-0001")["title"] == "x2"
    W.on_message(None, None, msg("ticket/delete", {"id": "FW-0001", "rid": "abcdef13"}))
    assert TK.load(W.TICKETS_DIR, "FW-0001") is None
    assert [p for t, p, _ in W.SENT if t == "tickets"][-1]["tickets"] == []


@pytest.mark.parametrize("topic,name", [("ticket/edit", "edit"), ("ticket/delete", "delete")])
def test_on_message_ticket_edit_errors_never_escape(W, monkeypatch, topic, name):
    def boom(*a, **k):
        raise OSError("disk gone")
    monkeypatch.setattr(W.TK, name, boom)
    msg = type("M", (), {"topic": f"{W.T}/{topic}", "payload": b'{"id": "FW-0001"}'})()
    W.on_message(None, None, msg)  # must not raise
    assert [p for t, p, r in W.SENT if t == "event/ticket_error"][-1]["error"] == "ticket message failed: OSError"


@pytest.mark.parametrize("inst", ["", "pilot2"])
def test_both_instances_subscribe_ticket_edit_and_delete(W, monkeypatch, inst):
    monkeypatch.setattr(W, "INSTANCE", inst)
    monkeypatch.setattr(W, "T", f"flight_watcher_{inst}" if inst else "flight_watcher")
    subs = []

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

        def publish(self, *a, **k):
            pass

        def subscribe(self, t):
            subs.append(t)
    monkeypatch.setattr(W.mqtt, "Client", C)
    monkeypatch.setattr(W, "mqtt_creds", lambda: {"username": "u", "password": "p", "host": "h", "port": 1883})
    for f in ("discovery", "publish_settings", "publish_rules", "publish_swap_tests"):
        monkeypatch.setattr(W, f, lambda *a, **k: None)
    monkeypatch.setattr(W, "freq", lambda: {"normal_min": 6, "hunt_s": 40})
    c = W.mqtt_start()
    c.on_connect(c, None, None, 0)
    assert {f"{W.T}/ticket/edit", f"{W.T}/ticket/delete", f"{W.T}/ticket/act"} <= set(subs)


# ---------------------------------------------------------------- the card (node, stub DOM)
CARD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "www", "flight-watcher-tickets-card.js")


def _card_node(tmp_path, body, src=None):
    if not shutil.which("node"):
        pytest.skip("node not installed")
    src = src if src is not None else open(CARD, encoding="utf-8").read()
    js = ("globalThis.HTMLElement = class {}; globalThis.customElements = {define() {}}; globalThis.window = {};\n"
          + src + "\n" + body)
    f = tmp_path / "t.js"
    f.write_text(js)
    out = subprocess.run(["node", str(f)], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_card_edit_message_sends_only_what_changed(tmp_path):
    t = {"id": "FW-0007", "kind": "bug", "title": "Grid blank", "narrative": "Nothing shows.", "steps": "",
         "expected": "The grid", "page": "Schedule", "editable": True}
    js = (f"const t = {json.dumps(t)}; const c = new FlightWatcherTicketsCard(); c.setConfig({{}});\n"
          "console.log(JSON.stringify([\n"
          "  c._editMsg(t, {title: ' Grid blank ', narrative: 'Nothing shows.', steps: '', expected: 'The grid', page: 'Schedule'}),\n"
          "  c._editMsg(t, {title: 'Grid blank v2', narrative: 'Nothing shows.', steps: 'Open it', expected: 'The grid', page: 'Details'}),\n"
          "  c._editMsg(t, {title: '', narrative: 'x'}),\n"
          "  c._editMsg(t, {title: 'x', narrative: '   '}),\n"
          "  c._editMsg(t, {title: 'y'.repeat(300), narrative: 'Nothing shows.'}).title.length,\n"
          "]));")
    r = _card_node(tmp_path, js)
    assert r[0] == "Nothing changed."
    assert r[1] == {"id": "FW-0007", "title": "Grid blank v2", "steps": "Open it", "page": "Details"}
    assert r[2] == r[3] == "Add a title and a description."
    assert r[4] == 200


def test_card_request_line(tmp_path):
    """The line under the buttons: waiting, the Watcher's answer for this card's rid only, a send failure."""
    js = ("const c = new FlightWatcherTicketsCard(); c.setConfig({}); const out = [];\n"
          "out.push(c._reqText({}));\n"
          "c._req = {rid: 'r1', id: 'FW-0007', action: 'edit'};\n"
          "out.push(c._reqText({}), c._reqText({rid: 'other', ok: true}), c._reqBad({rid: 'other', ok: false}));\n"
          "out.push(c._reqText({rid: 'r1', ok: true}), c._reqBad({rid: 'r1', ok: true}));\n"
          "out.push(c._reqText({rid: 'r1', ok: false, error: 'FW-0007 is in progress: edits only while new or reopened'}),\n"
          "         c._reqBad({rid: 'r1', ok: false}));\n"
          "c._req = {rid: 'r2', id: 'FW-0008', action: 'delete'};\n"
          "out.push(c._reqText({}), c._reqText({rid: 'r2', ok: true}), c._reqText({rid: 'r2', ok: false, error: 'FW-0008 not found'}));\n"
          "c._req.slow = true; out.push(c._reqText({}));\n"
          "out.push(c._reqText({rid: 'r2', ok: false, error: 'nothing changed'}));\n"
          "c._req.err = 'no connection'; out.push(c._reqText({}), c._reqBad({}));\n"
          "console.log(JSON.stringify(out));")
    assert _card_node(tmp_path, js) == [
        "", "Saving FW-0007...", "Saving FW-0007...", False, "FW-0007 saved.", False,
        "Not saved: FW-0007 is in progress: edits only while new or reopened.", True,
        "Deleting FW-0008...", "FW-0008 deleted.", "Not deleted: FW-0008 not found.",
        "FW-0008: sent, no answer from the Watcher yet.", "FW-0008 not deleted: nothing changed.",
        "FW-0008 not deleted: didn't send (no connection). Try again.", True]


def test_card_edit_form_prefills_and_escapes(tmp_path):
    bug = {"id": "FW-0007", "kind": "bug", "title": 'Say "hi" <b>', "narrative": "a </textarea><script>x</script>",
           "steps": "s & t", "expected": "", "page": "Old page"}
    feat = {"id": "FW-0008", "kind": "feature", "title": "Dark mode", "narrative": "Please.", "steps": "",
            "expected": "", "page": ""}
    js = (f"const c = new FlightWatcherTicketsCard(); c.setConfig({{}});\n"
          f"console.log(JSON.stringify([c._editForm({json.dumps(bug)}), c._editForm({json.dumps(feat)})]));")
    b, f = _card_node(tmp_path, js)
    assert 'value="Say &quot;hi&quot; &lt;b&gt;"' in b and "</textarea><script>" not in b
    assert "a &lt;/textarea&gt;&lt;script&gt;x&lt;/script&gt;</textarea>" in b and "s &amp; t</textarea>" in b
    assert "<option selected>Old page</option>" in b and "What happened?" in b and 'data-f="steps"' in b
    assert 'data-f="steps"' not in f and 'data-f="expected"' not in f and "What do you want, and why?" in f
    assert '<option value="" selected>(not set)</option>' in f and "<option>Watcher</option>" in f


def test_card_pilot_copy_sends_to_his_own_topics():
    p = cards.build("1", ["pilot2"])["flight-watcher-tickets-card-pilot2.js"]
    assert 'prefix: "flight_watcher_pilot2"' in p and '"ticket/edit"' in p and '"ticket/delete"' in p


def test_fixed_chip_says_v_only_for_app_versions():
    """A ticket fixed in an app release reads 'fixed v1.3.0'; one fixed in Pako config reads 'fixed in Pako config ...'."""
    import os
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "www", "flight-watcher-tickets-card.js"),
               encoding="utf-8").read()
    assert '(/^\\d+(\\.\\d+)+$/.test(String(t.version_fixed)) ? " v" : " in ")' in src


def test_card_paste_takes_screenshots_only_while_new_form_open(tmp_path):
    """FW-0053: Cmd+V on a Mac adds a copied screenshot as a photo; text pastes, an edit form or a closed form are left alone."""
    js = ("const listeners = {}; globalThis.document = {addEventListener(t, f) { listeners[t] = f; },\n"
          "  removeEventListener(t, f) { if (listeners[t] === f) delete listeners[t]; }};\n"
          "const c = new FlightWatcherTicketsCard(); c.setConfig({}); const got = []; c._addFiles = (fl) => got.push(fl.map((x) => x.name));\n"
          "const png = {name: 'image.png', type: 'image/png'};\n"
          "const ev = (items, files) => ({prevented: false, preventDefault() { this.prevented = true; },\n"
          "  clipboardData: {items: items.map(([kind, type, f]) => ({kind, type, getAsFile: () => f})), files: files || []}});\n"
          "c.connectedCallback(); const on = typeof listeners.paste === 'function';\n"
          "const e0 = ev([['file', 'image/png', png]]); listeners.paste(e0);\n"
          "c._form = {mode: 'new', kind: 'bug'};\n"
          "const e1 = ev([['file', 'image/png', png]]); listeners.paste(e1);\n"
          "const e2 = ev([['string', 'text/plain', null]]); listeners.paste(e2);\n"
          "const e3 = ev([['string', 'text/plain', null], ['file', 'image/png', png]]); listeners.paste(e3);\n"
          "const e4 = ev([], [{name: 'shot.jpg', type: 'image/jpeg'}, {name: 'a.pdf', type: 'application/pdf'}]); listeners.paste(e4);\n"
          "c._form = {mode: 'edit', id: 'FW-0001'}; const e5 = ev([['file', 'image/png', png]]); listeners.paste(e5);\n"
          "c.disconnectedCallback();\n"
          "console.log(JSON.stringify([on, got, e0.prevented, e1.prevented, e2.prevented, e3.prevented, e4.prevented, e5.prevented, 'paste' in listeners]));")
    on, got, p0, p1, p2, p3, p4, p5, still = _card_node(tmp_path, js)
    assert on and not still
    assert got == [["image.png"], ["image.png"], ["shot.jpg"]]
    assert (p0, p1, p2, p3, p4, p5) == (False, True, False, False, True, False)


def test_card_claude_code_button_link(tmp_path):
    """Ryan (Nov 6): Process Tickets in Claude Code opens claude.ai/code/new with the prompt and this repo filled in."""
    js = ("const c = new FlightWatcherTicketsCard(); c.setConfig({}); const d = new FlightWatcherTicketsCard();\n"
          "d.setConfig({claude_code_url: 'https://claude.ai/code/new?q=x'});\n"
          "console.log(JSON.stringify([c._ccUrl(), d._ccUrl(), FW_TICKET_CC_PROMPT]));")
    url, override, prompt = _card_node(tmp_path, js)
    from urllib.parse import urlsplit, parse_qs
    u = urlsplit(url)
    assert (u.scheme, u.netloc, u.path) == ("https", "claude.ai", "/code/new")
    assert parse_qs(u.query) == {"q": [prompt], "repo": ["AlohaFlyer/home-assistant-addons"]}
    assert "Flight Watcher tickets" in prompt and override == "https://claude.ai/code/new?q=x"
    src = open(CARD, encoding="utf-8").read()
    assert 'data-cc href="${this._e(this._ccUrl())}" target="_blank" rel="noopener noreferrer">Process Tickets in Claude Code</a>' in src
    p = cards.build("1", ["pilot2"])["flight-watcher-tickets-card-pilot2.js"]
    assert "Process Tickets in Claude Code" in p and 'FW_TICKET_CC_REPO = "AlohaFlyer/home-assistant-addons"' in p
