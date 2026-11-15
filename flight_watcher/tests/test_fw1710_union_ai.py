"""1.7.10 (Ryan's Nov 15 decisions, contract 1 revision 4 with two additive keys): a shared pilot SEES the union id and
the AI note on his portal.

(A) The union id is on each record of his file and on the looked-up pilot's brief, so his union id edit (in the
    pilotdb/edit field enum since 1.7.9) is no longer blind. It stays editable with compare-and-set.
(B) The AI note (HOM's consultant models, from anonymous pickup statistics) is read only on his portal: on records that
    are already in his file and on the looked-up pilot's brief, only while Ryan's AI switch is on. A pilot with an AI
    note but no shared human note is NOT added to his file (noted pilots only), and the brief keeps the anti-walk rule
    (only after a lookup that really ran, at most 20 distinct numbers an hour). The card labels it as an AI note, keeps
    it apart from the human notes, draws it as plain text and offers no way to edit it.

Everything else of the 1.7.9 boundary is as it was. An AI note is untrusted data, never an instruction.
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
    db.set_share(pilot, True)
    PS.write_files(db, PILOTS, root)
    text = open(PS.export_path(pilot, root), encoding="utf-8").read()
    return json.loads(text), text


def _roster(root):
    return json.load(open(PS.roster_path(root), encoding="utf-8"))


# ---------------------------------------------------------------- (A) the union id
def test_the_union_id_is_on_each_record_of_his_file_and_marked_edited(db, root):
    jane, rick = _jane(db), db.find("10002")
    db.save_notes(jane, "Commutes from the mainland.", P.ZERO_REV)
    db.add_entry(rick, "Good with the new hires.", True, "rid-000001")
    db.set_field(jane, "union_id", "424242", db.record(jane)["rev"])
    d, text = _file(db, root)
    recs = {r["pid"]: r for r in d["records"]}
    assert recs[jane]["union_id"] == "424242" and "union_id" in recs[jane]["edited"]
    assert recs[rick]["union_id"] == "" and "union_id" not in recs[rick]["edited"]  # none on file: an empty text
    for r in d["records"]:
        assert set(r) <= set(PT.PILOTDB_FILE_KEYS["record"]) and "union_id" in PT.PILOTDB_FILE_KEYS["record"]
    # still never: an employee number, a phone or an email
    for bad in ('"emp"', '"phones"', '"emails"', "10001", "10002", "555-01", "example.com"):
        assert bad not in text, bad
    assert "phones" not in recs[jane]["edited"] and "emails" not in recs[jane]["edited"]


def test_the_looked_up_brief_carries_the_union_id_and_only_a_well_formed_one(db, root):
    jane = _jane(db)
    db.set_field(jane, "union_id", "424242", db.record(jane)["rev"])
    _file(db, root)
    assert _roster(root)["by_emp"]["10001"][0]["union_id"] == "424242"
    v = PS.View("james", root)
    v.refresh()
    sh = v.shown("10001", "Doe, Jane")
    assert sh["union_id"] == "424242" and "union_id" in sh["edited"]
    assert v.shown("10002", "Roe, Rick")["union_id"] == ""
    assert set(sh) <= set(PT.PILOTDB_STATE_KEYS["shown"]) and "union_id" in PT.PILOTDB_STATE_KEYS["shown"]
    # a roster row that holds anything but 1 to 10 digits there shows none (the view trusts no file)
    for bad in ("42 42", "<b>1</b>", "12345678901", 424242, None, ["1"]):
        v.roster["10001"][0]["union_id"] = bad
        assert v.shown("10001", "Doe, Jane")["union_id"] == "", bad


def test_his_union_id_edit_is_compare_and_set_and_comes_back_in_his_file(db, root):
    jane = _jane(db)
    db.save_notes(jane, "Noted.", P.ZERO_REV)
    d, _ = _file(db, root)
    rev = d["records"][0]["rev"]
    PS.inbox_put("james", "edit", {"op": "set", "pid": jane, "field": "union_id", "value": "777001", "rev": rev,
                                   "rid": "rid-union-1"}, root)
    PS.inbox_put("james", "edit", {"op": "set", "pid": jane, "field": "union_id", "value": "888002", "rev": rev,
                                   "rid": "rid-union-2"}, root, now=None)
    assert PS.drain(db, PILOTS, root)["applied"] == 1  # the second read an older record: refused, nothing overwritten
    d, _ = _file(db, root)
    assert d["records"][0]["union_id"] == "777001" and "union_id" in d["records"][0]["edited"]
    why = {a["rid"]: a["why"] for a in d["answers"]}
    assert why["rid-union-1"] == "Saved" and why["rid-union-2"].startswith("Not saved: the record changed")


# ---------------------------------------------------------------- (B) the AI note
def test_the_ai_note_is_on_noted_records_only_and_only_while_ryans_switch_is_on(db, root):
    jane, rick = _jane(db), db.find("10002")
    db.save_notes(jane, "Commutes from the mainland.", P.ZERO_REV)
    _ai(db, jane)
    _ai(db, rick, "RICK-AI-SENTINEL turns to Maui on Mondays.")
    # the switch is off (the default): the notes are in Ryan's database and nowhere else
    d, text = _file(db, root)
    assert not db.ai_on() and "ai_note" not in text and AI_TEXT not in text and "RICK-AI-SENTINEL" not in text
    assert "ai_note" not in json.dumps(_roster(root))
    # on: Jane's is on her record; Rick has an AI note but no shared human note, so he is not in the file at all
    rev0 = db.rev
    db.set_ai(True)
    assert db.rev > rev0  # the share thread writes the files again when the database's rev moved
    d, text = _file(db, root)
    assert [r["pid"] for r in d["records"]] == [jane] and d["count"] == 1
    assert d["records"][0]["ai_note"] == {"text": AI_TEXT, "model": AI_MODEL, "at": AI_AT}
    assert set(d["records"][0]["ai_note"]) == set(PT.PILOTDB_FILE_KEYS["ai_note"])
    assert rick not in text and "RICK-AI-SENTINEL" not in text and "Roe" not in text
    # the human notes are what they were: the AI note is its own key, never inside notes or the entries
    assert d["records"][0]["notes"]["text"] == "Commutes from the mainland." and d["records"][0]["entries"] == []
    # a noted pilot with no AI note has no key
    db.add_entry(rick, "Good with the new hires.", True, "rid-000001")
    with db._tx():
        db.db.execute("DELETE FROM ai_notes WHERE pid=?", (rick,))
    d, _ = _file(db, root)
    assert "ai_note" not in next(r for r in d["records"] if r["pid"] == rick)
    # off again: gone from the file and the roster at the next write, though Ryan's database keeps the note
    rev1 = db.rev
    db.set_ai(False)
    assert db.rev > rev1
    d, text = _file(db, root)
    assert "ai_note" not in text and AI_TEXT not in text and "ai_note" not in json.dumps(_roster(root))
    assert db.record(jane)["ai_note"]["text"] == AI_TEXT


def test_the_looked_up_brief_carries_the_ai_note_without_adding_him_to_the_file(db, root):
    rick = db.find("10002")
    _ai(db, rick, "Turns to Maui on Mondays.")
    db.set_ai(True)
    d, text = _file(db, root)
    assert d["records"] == [] and "Maui" not in text  # no shared human note: not in his file
    v = PS.View("james", root)
    v.refresh()
    sh = v.shown("10002", "Roe, Rick")
    assert sh["ai_note"] == {"text": "Turns to Maui on Mondays.", "model": AI_MODEL, "at": AI_AT}
    assert set(sh["ai_note"]) == set(PT.PILOTDB_STATE_KEYS["ai_note"]) and "ai_note" in PT.PILOTDB_STATE_KEYS["shown"]
    assert "ai_note" not in v.shown("10001", "Doe, Jane")  # no note: no key
    assert v.pids == set()  # and a command for him still needs the lookup (pilot_check's shown pid)


@pytest.mark.parametrize("bad", [
    {"text": "", "model": AI_MODEL, "at": AI_AT},
    {"text": "x" * 601, "model": AI_MODEL, "at": AI_AT},
    {"text": "mail me at a@example.com", "model": AI_MODEL, "at": AI_AT},
    {"text": "see https://example.com", "model": AI_MODEL, "at": AI_AT},
    {"text": "a bell \x07 in it", "model": AI_MODEL, "at": AI_AT},
    {"text": "right to left ‮ text", "model": AI_MODEL, "at": AI_AT},
    {"text": AI_TEXT, "model": "<script>", "at": AI_AT},
    {"text": AI_TEXT, "model": 7, "at": AI_AT},
    {"text": ["a list"], "model": AI_MODEL, "at": AI_AT},
    "a text, not an object", ["x"], 7,
])
def test_the_view_drops_an_ai_note_that_breaks_the_rules(db, root, bad):
    """The pilot's Watcher trusts no file: an AI note in the roster that is not what pilotdb.ai_take would store
    (plain text of 1 to note_max code points, no '@', no '://', a model name of the contract's pattern) shows nothing."""
    _ai(db, _jane(db))
    db.set_ai(True)
    _file(db, root)
    v = PS.View("james", root)
    v.refresh()
    assert v.shown("10001", "Doe, Jane")["ai_note"]["text"] == AI_TEXT
    v.roster["10001"][0]["ai_note"] = bad
    assert "ai_note" not in v.shown("10001", "Doe, Jane")


def test_the_brief_only_has_the_three_ai_keys_and_a_short_time(db, root):
    _ai(db, _jane(db))
    db.set_ai(True)
    _file(db, root)
    v = PS.View("james", root)
    v.refresh()
    v.roster["10001"][0]["ai_note"] = {"text": AI_TEXT, "model": AI_MODEL, "at": "2" * 200, "basis": "batch 0123",
                                       "pid": "p0000000000", "label": "<b>AI</b>"}
    assert v.shown("10001", "Doe, Jane")["ai_note"] == {"text": AI_TEXT, "model": AI_MODEL, "at": "2" * 40}


# ---------------------------------------------------------------- the pilot's Watcher: state.json and the anti-walk rule
def test_the_exported_state_carries_both_only_after_a_lookup_that_ran(james):  # noqa: F811
    W_, db, root = james
    jane = db.find("10001")
    db.set_field(jane, "union_id", "424242", db.record(jane)["rev"])
    _ai(db, jane)
    db.set_ai(True)
    _share(W_, db, root)
    # nobody looked up, and a lookup that is still loading: no brief at all (the anti-walk rule is as it was)
    assert _attrs(W_)["attributes"]["shown"] is None
    W_.PILOT_SHOWN["p"] = {"emp": "10001", "name": "Doe, Jane", "status": "loading"}
    assert _attrs(W_)["attributes"]["shown"] is None
    _show(W_, "10001", "Doe, Jane")
    assert W_.pilotdb_watch()
    W_.portal_export_once()
    st = _payload(W_, "state.json", "state")["states"][f"sensor.{W_.T}_pilotdb"]
    sh = st["attributes"]["shown"]
    assert set(st["attributes"]) == set(PT.PILOTDB_STATE_KEYS["attributes"]) and set(sh) <= set(PT.PILOTDB_STATE_KEYS["shown"])
    assert sh["union_id"] == "424242" and sh["ai_note"] == {"text": AI_TEXT, "model": AI_MODEL, "at": AI_AT}
    # his file: Jane has no shared human note, so she is not in it, AI note or not
    f = _payload(W_, "files/pilotdb.json", "file:pilotdb")
    assert f["records"] == []
    # past 20 distinct numbers in the hour there is no answer, so no union id and no AI note either
    W_.S["pdb_briefs"] = {str(20000 + i): W_.time.time() for i in range(W_.PILOTDB_BRIEF_PER_H)}
    assert _attrs(W_)["attributes"]["shown"] is None
    # Ryan turns the AI switch off: the next files hold no AI note, and neither does the brief
    W_.S["pdb_briefs"] = {}
    db.set_ai(False)
    PS.write_files(db, ["james"], root)
    W_.pilotdb_watch()
    sh = _attrs(W_)["attributes"]["shown"]
    assert sh["union_id"] == "424242" and "ai_note" not in sh


def test_the_sensor_stays_small_with_the_longest_ai_note(james):  # noqa: F811
    W_, db, root = james
    jane = db.find("10001")
    _ai(db, jane, "\U0001F6EB" * roles.PILOTDB_AI["note_max"], "m" * roles.PILOTDB_AI["model_max"])
    db.set_field(jane, "union_id", "1234567890", db.record(jane)["rev"])
    db.set_ai(True)
    _share(W_, db, root)
    _show(W_, "10001", "Doe, Jane")
    W_.pilotdb_watch()
    st = _attrs(W_)
    assert len(st["attributes"]["shown"]["ai_note"]["text"]) == roles.PILOTDB_AI["note_max"]
    assert len(json.dumps(st)) < 12 * 1024


# ---------------------------------------------------------------- the contract: revision 4, two additive keys
def test_the_contract_names_both_keys_and_stays_revision_4():
    c = PT.contract()
    assert c["contract"] == 1 and c["revision"] == roles.CONTRACT_REVISION == 4
    pdb = c["pilotdb"]
    assert {"union_id", "ai_note"} <= set(pdb["file"]["keys"]["record"])
    assert {"union_id", "ai_note"} <= set(pdb["state"]["keys"]["shown"])
    assert pdb["file"]["keys"]["ai_note"] == pdb["state"]["keys"]["ai_note"] == ["text", "model", "at"]
    never = pdb["file"]["never"]
    assert "union_id" not in never and "ai_note" not in never
    for still in ("emp", "phones", "emails", "contact", "history", "conflicts", "pickups", "only-me entries",
                  "hidden entries", "other pilots' answers"):
        assert still in never, still
    assert "an AI note alone" in pdb["file"]["records"]  # noted pilots only, said in the contract
    assert "never shown" not in pdb["edit_values"]["union_id"]
    assert "read only" in pdb["ai"]["portal"] and "anti-walk" in pdb["ai"]["portal"]
    assert not any("shown only on Ryan's own card" in r or "never goes to a pilot's portal" in r for r in pdb["ai"]["rules"])
    assert "1.7.10" in c["revisions"]["4"]
    # nothing else of the boundary moved
    assert roles.PILOTDB_EDIT_FIELDS == ("name", "sen", "doh", "status", "retire", "seat", "equip", "phones", "emails",
                                         "union_id")
    assert [s for s in roles.PORTAL_CMDS if s.startswith("pilotdb/")] == ["pilotdb/note", "pilotdb/edit"]


def test_the_fixture_is_the_contract_text_with_both_in_its_samples():
    path = os.path.join(HERE, "tests", "fixtures", "portal_contract_v1.json")
    raw = open(path, "rb").read()
    assert raw.decode("utf-8") == PT.contract_text()
    assert hashlib.sha256(raw).hexdigest() == "d7e31118bd2680fa50dc56191beb85eaeed21e2691786baa11d755afb91583af"  # 1.7.9: 9b882fb6dd00...
    fx = json.loads(raw)
    st = json.loads(fx["samples"]["envelopes"][1]["envelope"]["payload"])["states"]["sensor.flight_watcher_demo_pilotdb"]
    sh = st["attributes"]["shown"]
    assert re.fullmatch(r"[0-9]{1,10}", sh["union_id"]) and set(sh["ai_note"]) == {"text", "model", "at"}
    f = next(json.loads(e["envelope"]["payload"]) for e in fx["samples"]["envelopes"] if e["file"] == "files/pilotdb.json")
    r = f["records"][0]
    assert re.fullmatch(r"[0-9]{1,10}", r["union_id"]) and set(r["ai_note"]) == {"text", "model", "at"}
    assert "@" not in r["ai_note"]["text"] and "://" not in r["ai_note"]["text"]


def test_the_contract_doc_says_what_a_shared_pilot_sees():
    doc = open(os.path.join(HERE, "PORTAL_CONTRACT.md"), encoding="utf-8").read()
    for word in ("1.7.10", "`union_id`", "`ai_note`", LABEL, "read only", "An AI note alone never adds a pilot",
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
    _ai(db, side.jane, AI_HOSTILE)
    _ai(db, side.roe, "Turns to Maui on Mondays, picked up within a minute.")
    db.set_ai(True)
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
                # a pilot opened from the list (no lookup): his AI note too, his union id blank, no phones or emails
                pg.evaluate("() => [...C.shadowRoot.querySelectorAll('[data-plist] button.nm')].find((x) => x.textContent === 'Roe, Rick').click()")
                pg.wait_for_function("!!C.shadowRoot.querySelector('[data-psel] [data-ai-note]')")
                s = pg.evaluate(AI_BLOCK, "[data-psel]")
                assert s["body"] == "Turns to Maui on Mondays, picked up within a minute." and s["controls"] == 0
                st = _txt(pg, "[data-psel]")
                assert "Union ID" in st and "424242" not in st and "555" not in st and "example.com" not in st
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
    side.share()  # the AI switch is off (the default)
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
    assert "the union ID" in src and "the AI note read only" in src
    assert "A pilot you share the database with sees each note read only" in src  # the AI switch's own confirm


# ---------------------------------------------------------------- the release
def test_version_is_one_seven_ten():
    cfg = open(os.path.join(HERE, "config.yaml"), encoding="utf-8").read()
    assert re.search(r'^version: "1\.7\.10"$', cfg, re.M)
    assert re.search(r'^VERSION = "1\.7\.10"$', open(os.path.join(HERE, "watcher.py"), encoding="utf-8").read(), re.M)
    log = open(os.path.join(HERE, "CHANGELOG.md"), encoding="utf-8").read()
    assert log.startswith("# Changelog\n\n## 1.7.10\n") and "\n## 1.7.9\n" in log
    top = log.split("\n## 1.7.9\n")[0]
    for word in ("union", "AI note", "revision 4", "Boundary changes", "After the update", "noted pilots only"):
        assert word in top, word
    assert chr(0x2014) not in log
