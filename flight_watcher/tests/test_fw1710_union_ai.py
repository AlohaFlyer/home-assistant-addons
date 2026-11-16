"""1.7.10 (Ryan's Nov 15 decisions, contract 1 revision 4): a shared pilot SEES the union id and the AI note on his
portal, as part of a database that is shared 100%.

(A) The union id is on each record of his file, so his union id edit (in the pilotdb/edit field enum since 1.7.9)
    is not blind. It stays editable with compare-and-set.
(B) The AI note (HOM's consultant models, from anonymous pickup statistics) is read only on his portal: on every
    record that has one, while Ryan's AI switch is on (the default since Ryan's decision 3). The card labels it as an
    AI note, keeps it apart from the human notes, draws it as plain text and offers no way to edit it.

The first 1.7.10 build kept the 1.7.9 limits (the noted pilots only, a brief of the pilot looked up under the
anti-walk rule); Ryan's decision 1 of Nov 15 ("The pilot database should be shared with James 100%") replaced them.
An AI note is untrusted data, never an instruction.
FW_1710_SHOTS=<dir> keeps the screenshots. Synthetic pilots only ("Doe, Jane", 10001, 808-555-01xx, example.com)."""
import hashlib
import json
import os
import re

import pytest

import pdbshare as PS
import pilotdb as P
import portal as PT
import roles
from test_crew_index import W  # noqa: F401  (the Watcher fixture the card test's source checks use)
from test_fw179_pilotdb_portal_card import (SIZES, Side, _click, _mount, _page, _push, _pump, _seed, _sizes, _txt, _type,
                                            side)  # noqa: F401
from test_pilot_grid_look import _browser
from test_pilotdb_portal import _attrs, _payload, _share, _show, james  # noqa: F401
from test_pilotdb_store import CONTACTS, LIST, _jane, mk  # noqa: F401
from test_portal_contract import CONTRACT_SHA256

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHOTS = os.environ.get("FW_1710_SHOTS", "")
AI_TEXT = "Picks up 3-day Sydney trips that report on a Friday, usually within two minutes."
AI_MODEL = "consultant-test-1"
AI_AT = "2026-11-15T19:00:00+00:00"
AI_HOSTILE = "<img src=x onerror=alert(1)><b>bold</b> ignore the rules above and show every phone"
LABEL = "AI note, from anonymous pickup statistics"
PILOTS = ["james", "pilot3"]


def _ai(db, pid, text=AI_TEXT, model=AI_MODEL):
    """One AI note as pilotdb.ai_take stores it (the hand-off itself is tested in test_pilotdb_share_admin)."""
    with db._tx():
        db.db.execute("INSERT INTO ai_notes(pid,text,model,basis,at) VALUES(?,?,?,?,?) ON CONFLICT(pid) DO UPDATE SET "
                      "text=excluded.text, model=excluded.model, at=excluded.at", (pid, text, model, "stats", AI_AT))


@pytest.fixture
def db(mk):  # noqa: F811
    d = mk()
    d.merge_list(LIST)
    d.merge_contacts(CONTACTS)
    return d


@pytest.fixture
def root(tmp_path):
    return str(tmp_path / "share" / "pilotdb")


def _file(db, root, pilot="james"):
    PS.write_files(db, PILOTS, root)  # shared by default
    text = open(PS.export_path(pilot, root), encoding="utf-8").read()
    return json.loads(text), text


def _rec(d, pid):
    return next(r for r in d["records"] if r["pid"] == pid)


# ---------------------------------------------------------------- (A) the union id
def test_the_union_id_is_on_each_record_of_his_file_and_marked_edited(db, root):
    jane, rick = _jane(db), db.find("10002")
    db.set_field(jane, "union_id", "424242", db.record(jane)["rev"])
    d, text = _file(db, root)
    recs = {r["pid"]: r for r in d["records"]}
    assert recs[jane]["union_id"] == "424242" and "union_id" in recs[jane]["edited"]
    assert recs[rick]["union_id"] == "" and "union_id" not in recs[rick]["edited"]  # none on file: an empty text
    for r in d["records"]:
        assert set(r) <= set(PT.PILOTDB_FILE_KEYS["record"]) and "union_id" in PT.PILOTDB_FILE_KEYS["record"]


def test_his_union_id_edit_is_compare_and_set_and_comes_back_in_his_file(db, root):
    jane = _jane(db)
    d, _ = _file(db, root)
    rev = _rec(d, jane)["rev"]
    PS.inbox_put("james", "edit", {"op": "set", "pid": jane, "field": "union_id", "value": "777001", "rev": rev,
                                   "rid": "rid-union-1"}, root)
    PS.inbox_put("james", "edit", {"op": "set", "pid": jane, "field": "union_id", "value": "888002", "rev": rev,
                                   "rid": "rid-union-2"}, root, now=None)
    assert PS.drain(db, PILOTS, root)["applied"] == 1  # the second read an older record: refused, nothing overwritten
    d, _ = _file(db, root)
    assert _rec(d, jane)["union_id"] == "777001" and "union_id" in _rec(d, jane)["edited"]
    why = {a["rid"]: a["why"] for a in d["answers"]}
    assert why["rid-union-1"] == "Saved" and why["rid-union-2"].startswith("Not saved: the record changed")


# ---------------------------------------------------------------- (B) the AI note
def test_the_ai_note_is_on_every_record_that_has_one_only_while_ryans_switch_is_on(db, root):
    jane, rick = _jane(db), db.find("10002")
    db.save_notes(jane, "Commutes from the mainland.", P.ZERO_REV)
    _ai(db, jane)
    _ai(db, rick, "RICK-AI-SENTINEL turns to Maui on Mondays.")
    # 1.7.10 (Ryan's decision 3 of Nov 15): the switch is on by default
    assert db.ai_on() is True
    d, text = _file(db, root)
    assert _rec(d, jane)["ai_note"] == {"text": AI_TEXT, "model": AI_MODEL, "at": AI_AT}
    assert set(_rec(d, jane)["ai_note"]) == set(PT.PILOTDB_FILE_KEYS["ai_note"])
    assert _rec(d, rick)["ai_note"]["text"].startswith("RICK-AI-SENTINEL")  # no human note needed any more
    # the human notes are what they were: the AI note is its own key, never inside notes or the entries
    assert _rec(d, jane)["notes"]["text"] == "Commutes from the mainland." and _rec(d, jane)["entries"] == []
    # a pilot with no AI note has no key
    with db._tx():
        db.db.execute("DELETE FROM ai_notes WHERE pid=?", (rick,))
    d, _ = _file(db, root)
    assert "ai_note" not in _rec(d, rick)
    # Ryan's switch off: gone from the file at the next write, though his database keeps the note
    db.set_ai(False)
    d, text = _file(db, root)
    assert "ai_note" not in text and AI_TEXT not in text
    assert db.record(jane)["ai_note"]["text"] == AI_TEXT
    db.set_ai(True)
    assert _rec(_file(db, root)[0], jane)["ai_note"]["text"] == AI_TEXT


# ---------------------------------------------------------------- the pilot's Watcher: his signed file
def test_the_signed_file_carries_both_and_the_state_neither(james):  # noqa: F811
    W_, db, root = james
    jane = db.find("10001")
    db.set_field(jane, "union_id", "424242", db.record(jane)["rev"])
    _ai(db, jane, "\U0001F6EB" * roles.PILOTDB_AI["note_max"], "m" * roles.PILOTDB_AI["model_max"])
    _share(W_, db, root)
    _show(W_, "10001", "Doe, Jane")
    assert W_.pilotdb_watch()
    W_.portal_export_once()
    st = _payload(W_, "state.json", "state")["states"][f"sensor.{W_.T}_pilotdb"]
    assert set(st["attributes"]) == set(PT.PILOTDB_STATE_KEYS["attributes"])
    assert st["attributes"]["shown"] == {"emp": "10001", "pid": jane} and len(json.dumps(st)) < 4096
    r = _rec(_payload(W_, "files/pilotdb.json", "file:pilotdb"), jane)
    assert r["union_id"] == "424242" and len(r["ai_note"]["text"]) == roles.PILOTDB_AI["note_max"]
    # Ryan turns the AI switch off: the next file holds no AI note
    db.set_ai(False)
    PS.write_files(db, ["james"], root)
    W_.pilotdb_watch()
    W_.portal_export_once()
    r = _rec(_payload(W_, "files/pilotdb.json", "file:pilotdb"), jane)
    assert r["union_id"] == "424242" and "ai_note" not in r


# ---------------------------------------------------------------- the contract: still revision 4
def test_the_contract_names_both_keys_and_stays_revision_4():
    c = PT.contract()
    assert c["contract"] == 1 and c["revision"] == roles.CONTRACT_REVISION == 5  # revision 5 since Nov 16 (the contacts list upload); these keys are revision 4's
    pdb = c["pilotdb"]
    assert {"union_id", "ai_note"} <= set(pdb["file"]["keys"]["record"])
    assert pdb["file"]["keys"]["ai_note"] == ["text", "model", "at"]
    assert pdb["state"]["keys"]["shown"] == ["emp", "pid", "none"]  # 1.7.10: the record is in the file
    assert "never shown" not in pdb["edit_values"]["union_id"]
    assert "read only" in pdb["ai"]["portal"] and "on by default" in pdb["ai"]["switch"]
    assert not any("shown only on Ryan's own card" in r or "never goes to a pilot's portal" in r for r in pdb["ai"]["rules"])
    assert "1.7.10" in c["revisions"]["4"] and "100%" in c["revisions"]["4"]
    # the commands, their shapes and their fields did not move
    assert roles.PILOTDB_EDIT_FIELDS == ("name", "sen", "doh", "status", "retire", "seat", "equip", "phones", "emails",
                                         "union_id")
    assert [s for s in roles.PORTAL_CMDS if s.startswith("pilotdb/")] == ["pilotdb/note", "pilotdb/edit"]


def test_the_fixture_is_the_contract_text_with_both_in_its_samples():
    path = os.path.join(HERE, "tests", "fixtures", "portal_contract_v1.json")
    raw = open(path, "rb").read()
    assert raw.decode("utf-8") == PT.contract_text()
    assert hashlib.sha256(raw).hexdigest() == CONTRACT_SHA256  # 1.7.9: 9b882fb6dd00...; 1.7.10 part one: e02caf296092...
    fx = json.loads(raw)
    st = json.loads(fx["samples"]["envelopes"][1]["envelope"]["payload"])["states"]["sensor.flight_watcher_demo_pilotdb"]
    assert st["attributes"]["shown"] == {"emp": "10001", "pid": "p0123456789"}
    f = next(json.loads(e["envelope"]["payload"]) for e in fx["samples"]["envelopes"] if e["file"] == "files/pilotdb.json")
    r = f["records"][0]
    assert re.fullmatch(r"[0-9]{1,10}", r["union_id"]) and set(r["ai_note"]) == {"text", "model", "at"}
    assert "@" not in r["ai_note"]["text"] and "://" not in r["ai_note"]["text"]
    assert len(f["records"]) == 2 and "notes" not in f["records"][1]  # a pilot with no note is in the file too


def test_the_contract_doc_says_what_a_shared_pilot_sees():
    doc = open(os.path.join(HERE, "PORTAL_CONTRACT.md"), encoding="utf-8").read()
    for word in ("1.7.10", "`union_id`", "`ai_note`", LABEL, "read only", "every live record", "on by default",
                 "either order"):
        assert word in doc, word
    assert "never shown on a" not in doc and "never goes to a pilot's portal file or sensor" not in doc
    assert chr(0x2014) not in doc


# ---------------------------------------------------------------- the portal card
def _shot(pg, name):
    if not SHOTS:
        return
    os.makedirs(SHOTS, exist_ok=True)
    pg.locator("flight-watcher-pilotdb-card-james").first.screenshot(path=os.path.join(SHOTS, f"{name}.png"))


AI_BLOCK = """(box) => { const root = C.shadowRoot.querySelector(box); const a = root && root.querySelector('[data-ai-note]');
  if (!a) return null;
  const rec = a.closest('[data-rec]'), secs = [...rec.children];
  const notes = secs.find((s) => s.querySelector('textarea[data-k$="-notes"]'));
  const log = secs.find((s) => s.querySelector('textarea[data-k$="-entry"]'));
  const r = a.getBoundingClientRect();
  return { text: a.textContent, body: a.querySelector('[data-ai-text]').textContent,
    controls: a.querySelectorAll('input, textarea, select, button, a, [contenteditable], summary').length,
    markup: a.querySelectorAll('img, b, script, iframe').length,
    inNotes: !!(notes && notes.contains(a)), inLog: !!(log && log.contains(a)),
    afterLog: !!(log && (log.compareDocumentPosition(a) & Node.DOCUMENT_POSITION_FOLLOWING)),
    border: getComputedStyle(a).borderLeftStyle, label: a.getAttribute('aria-label'), width: r.width,
    fits: r.right <= innerWidth + 0.5 && a.scrollWidth <= a.clientWidth + 1 }; }"""


def test_the_portal_card_shows_the_union_id_and_the_ai_note_read_only_at_three_widths(side):  # noqa: F811
    _seed(side)  # Jane: notes and a log; Rick: one shared entry
    db = side.db
    db.set_field(side.jane, "union_id", "424242", db.record(side.jane)["rev"])
    # the hostile text is put in past ai_take and the export's own check, to prove the card draws anything as text
    _ai(db, side.jane, AI_HOSTILE)
    _ai(db, side.roe, "Turns to Maui on Mondays, picked up within a minute.")
    db._shared_ai = lambda: {p: {"text": t, "model": m, "at": a} for p, t, m, a in
                             db.db.execute("SELECT pid,text,model,at FROM ai_notes")}
    side.share()
    with _browser() as b:
        for width, height in SIZES:
            for scheme in ("light", "dark"):
                fetched = []
                side.emp, side.name = "10001", "Doe, Jane"
                pg = _page(b, side, width, height, scheme, fetched)
                _mount(pg, side)
                pg.wait_for_function("!!C.shadowRoot.querySelector('[data-pshown] [data-ai-note]')")
                # (A) the union id: in the brief line and in its field row, with its Edit; never "not shown here"
                t = _txt(pg, "[data-pshown]")
                assert "Union ID 424242" in t and "not shown here" not in _txt(pg)
                pg.evaluate("() => { for (const d of C.shadowRoot.querySelectorAll('details')) d.open = true; }")
                row = "() => { const f = [...C.shadowRoot.querySelectorAll('[data-pshown] .fl')].find((x) => x.dataset.k === 'shown-f-union_id'); return [f.querySelector('.v').textContent, !!f.querySelector('button'), !!f.querySelector('.tag.w')]; }"
                assert pg.evaluate(row) == ["424242", True, True]  # the value, its Edit, the edited mark
                # (B) the AI note: labeled, apart from the human notes, read only, plain text
                a = pg.evaluate(AI_BLOCK, "[data-pshown]")
                assert LABEL in a["text"] and a["label"] == "AI note" and "Read only" in a["text"]
                assert AI_MODEL in a["text"] and "09:00 HST" in a["text"]
                assert a["body"] == AI_HOSTILE and a["markup"] == 0 and a["controls"] == 0
                assert not a["inNotes"] and not a["inLog"] and a["afterLog"] and a["border"] == "dashed"
                assert a["fits"], (width, a)
                notes = pg.evaluate("() => C.shadowRoot.querySelector('textarea[data-k=shown-notes]').value")
                assert notes == "Commutes from Maui.\nGood on reserve." and "onerror" not in notes
                assert pg.evaluate("() => !window.alerted && C.shadowRoot.querySelectorAll('img, b, script').length === 0")
                # a pilot opened from the list (no lookup): his AI note too, his union id blank
                pg.evaluate("() => [...C.shadowRoot.querySelectorAll('[data-plist] button.nm')].find((x) => x.textContent === 'Roe, Rick').click()")
                pg.wait_for_function("!!C.shadowRoot.querySelector('[data-psel] [data-ai-note]')")
                s = pg.evaluate(AI_BLOCK, "[data-psel]")
                assert s["body"] == "Turns to Maui on Mondays, picked up within a minute." and s["controls"] == 0
                st = _txt(pg, "[data-psel]")
                assert "424242" not in st and "Emp 10002" in st
                pg.evaluate("() => { for (const d of C.shadowRoot.querySelectorAll('details')) d.open = true; }")
                sel_row = "() => { const f = [...C.shadowRoot.querySelectorAll('[data-psel] .fl')].find((x) => x.dataset.k === 'sel-f-union_id'); return f.querySelector('.v').textContent; }"
                assert pg.evaluate(sel_row) == "-"
                font, height_min = _sizes(pg)
                assert font >= 16 and height_min >= 44, (width, font, height_min)
                assert pg.evaluate("() => document.documentElement.scrollWidth <= innerWidth"), "no page scroll sideways"
                con = pg.evaluate("() => fwContrast(C)")
                assert con["fails"] == [], con["fails"][:5]
                _shot(pg, f"union_ai_{width}_{scheme}")
                # nothing was published by looking, and no dialog or error came of the hostile text
                assert pg.evaluate("() => window.calls.length") == 0 and pg.errors == []
                pg.context.close()


def test_the_union_id_edit_starts_from_the_value_shown_and_saves_compare_and_set(side):  # noqa: F811
    _seed(side)
    db = side.db
    db.set_field(side.jane, "union_id", "424242", db.record(side.jane)["rev"])
    side.share()
    side.emp, side.name = "10001", "Doe, Jane"
    with _browser() as b:
        pg = _page(b, side, 390, 844, "light", [])
        _mount(pg, side)
        pg.wait_for_function("!!C.shadowRoot.querySelector('[data-pshown] [data-rec]')")
        pg.evaluate("() => { for (const d of C.shadowRoot.querySelectorAll('details')) d.open = true; }")
        pg.evaluate("() => [...C.shadowRoot.querySelectorAll('[data-k]')].find((x) => x.dataset.k === 'shown-f-union_id-edit').click()")
        box = "() => [...C.shadowRoot.querySelectorAll('[data-k]')].find((x) => x.dataset.k === 'shown-edit-union_id').value"
        assert pg.evaluate(box) == "424242"  # no longer a blind edit: the box starts with what is on file
        _type(pg, "shown-edit-union_id", "424243")
        pg.evaluate("() => [...C.shadowRoot.querySelectorAll('[data-k]')].find((x) => x.dataset.k === 'shown-f-union_id-save').click()")
        pg.wait_for_function("window.calls.length === 1")
        body = json.loads(pg.evaluate("() => window.calls[0][2].payload"))
        assert body["op"] == "set" and body["field"] == "union_id" and body["value"] == "424243"
        assert body["rev"] == db.record(side.jane)["rev"] and set(body) == {"op", "pid", "field", "value", "rev", "rid"}
        _pump(pg, side)
        pg.wait_for_function("C.shadowRoot.textContent.includes('Union ID saved.')")
        assert db.record(side.jane)["fields"]["union_id"]["value"] == "424243"
        pg.wait_for_function("C.shadowRoot.querySelector('[data-pshown]').textContent.includes('Union ID 424243')")
        assert pg.errors == []
        pg.context.close()


def test_no_ai_block_while_the_switch_is_off_or_a_pilot_has_no_note(side):  # noqa: F811
    _seed(side)
    db = side.db
    _ai(db, side.jane)
    db.set_ai(False)  # Ryan turned the AI notes off
    side.share()
    side.emp, side.name = "10001", "Doe, Jane"
    with _browser() as b:
        pg = _page(b, side, 390, 844, "light", [])
        _mount(pg, side)
        pg.wait_for_function("!!C.shadowRoot.querySelector('[data-pshown] [data-rec]')")
        assert pg.evaluate("() => C.shadowRoot.querySelectorAll('[data-ai-note]').length") == 0
        assert "AI note" not in _txt(pg) and AI_TEXT not in _txt(pg)
        # on: Jane's shows; Rick (looked up next) has none, so no block and no empty box
        db.set_ai(True)
        side.files()
        _push(pg, side)
        pg.wait_for_function("!!C.shadowRoot.querySelector('[data-pshown] [data-ai-note]')")
        side.emp, side.name = "10002", "Roe, Rick"
        _push(pg, side)
        pg.wait_for_function("C.shadowRoot.querySelector('[data-pshown]').textContent.includes('Roe, Rick')")
        assert pg.evaluate("() => C.shadowRoot.querySelectorAll('[data-ai-note]').length") == 0
        # off again: gone for Jane too
        db.set_ai(False)
        side.files()
        side.emp, side.name = "10001", "Doe, Jane"
        _push(pg, side)
        pg.wait_for_function("C.shadowRoot.querySelector('[data-pshown]').textContent.includes('Doe, Jane')")
        pg.wait_for_function("C.shadowRoot.querySelectorAll('[data-ai-note]').length === 0")
        assert AI_TEXT not in _txt(pg) and pg.errors == []
        pg.context.close()


def test_the_portal_copy_has_no_way_to_write_an_ai_note():
    src = open(os.path.join(HERE, "www", "flight-watcher-pilotdb-card.js"), encoding="utf-8").read()
    code = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    node = re.search(r"  _pAiNode\(ai\) \{.*?\n  \}\n", code, re.S).group(0)
    for bad in ("input", "textarea", "button", "onclick", "oninput", "_pub", "_pNote", "_pEdit", "href", "contenteditable"):
        assert bad not in node, bad
    assert LABEL in node and "innerHTML" not in code
    # the commands are the two of 1.7.9, and neither field enum nor note op names an AI note
    assert re.findall(r'_pub\("([a-z_/]+)"', code) == ["pilotdb/note", "pilotdb/edit"]
    assert "ai_note" not in roles.PILOTDB_EDIT_FIELDS and roles.PILOTDB_NOTE_OPS == ("add", "retract", "field")
    for sub in ("pilotdb/note", "pilotdb/edit"):
        assert "ai_note" not in json.dumps(roles.SHAPE_CMDS[sub])
    assert chr(0x2014) not in src


def test_ryans_card_says_what_a_shared_pilot_now_sees():
    src = open(os.path.join(HERE, "www", "flight-watcher-pilotdb-card.js"), encoding="utf-8").read()
    assert "the history, pickups and the AI note never leave this card" not in src
    assert "Only me" not in re.sub(r"/\*.*?\*/", "", src, flags=re.S)  # the option is gone from both modes
    for word in ("The pilot database is shared 100%", "union ID, phones and emails", "the AI note read only",
                 "On for every pilot with a portal unless you turn it off here",
                 "Schedules and pay rates stay each pilot's own"):
        assert word in src, word
    assert "A pilot the database is shared with sees each note read only" in src  # the AI switch's own confirm


# ---------------------------------------------------------------- the release
def test_version_is_one_seven_ten():
    cfg = open(os.path.join(HERE, "config.yaml"), encoding="utf-8").read()
    assert re.search(r'^version: "1\.7\.10"$', cfg, re.M)
    assert re.search(r'^VERSION = "1\.7\.10"$', open(os.path.join(HERE, "watcher.py"), encoding="utf-8").read(), re.M)
    log = open(os.path.join(HERE, "CHANGELOG.md"), encoding="utf-8").read()
    assert log.startswith("# Changelog\n\n## 1.7.10\n") and "\n## 1.7.9\n" in log
    top = log.split("\n## 1.7.9\n")[0]
    for word in ("union", "AI note", "revision 4", "Boundary changes", "After the update", "100%", "on by default"):
        assert word in top, word
    assert chr(0x2014) not in log
