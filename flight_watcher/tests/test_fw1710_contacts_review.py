"""1.7.10, review fixes of the pilot contacts upload (Nov 16). Each test failed before its fix:

- one pilot's lists cannot flood the shared database: rows_max rows a list, and at most new_max live records that only
  pilots' lists made (a list over it is refused whole and changes nothing);
- no cell can hold the parser: cell_chars and notes_chars, nothing beyond the header's columns, and the email pattern
  reads a long run of letters once; the admin's Watcher checks a waiting list before it takes the database's lock;
- a held row of a pilot's list that Ryan answers is applied the way the list is: it never drops or replaces a value;
- a number a pilot's list adds to Ryan's value leaves that value Ryan's (author, ref), so his next list treats the
  phones as it treats the email; the partial list answer 'gone' keeps what only a pilot's list gave;
- a Windows-1252 export is read as Ryan's own upload reads it;
- the card shows the portal's own refusal, and says "needs its next update" only for an older portal; its fields are
  16 px and 44 px at every width; its title, its limit line and its answer.

Synthetic rows only ("Doe, Jane", 10001, 808-555-01xx, example.com).
"""
import json
import os
import threading
import time
from datetime import timedelta

import pytest

import contacts as CT
import pdbshare as PS
import pilotdb as P
import portal as PT
import roles
from test_fw1710_portal_contacts import (CP, HEAD, ROWS, T0, UID, _browser, _card, _cj, _csv, _db, _f, _page, _pick_csv,
                                         _put, _shot, _view)
from test_pilotdb_store import CONTACTS

LIM = roles.PILOT_CONTACTS_LIMITS


def _new_rows(n, start=30000):
    return [[f"Pat{i}", "", "Poe", "", "Example Air", "First Officer", "", "", str(start + i),
             f"HAL Emp# {start + i} | Sen# {i + 1} (Jul 2026)"] for i in range(n)]


# ---------------------------------------------------------------- the flood bounds
def test_the_limits_are_in_the_contract_and_its_answers():
    assert (LIM["rows_max"], LIM["new_max"], LIM["cell_chars"], LIM["notes_chars"]) == (2500, 250, 200, 2000)
    assert LIM["encodings"] == ["utf-8", "cp1252"]
    cm = PT.contract()["commands"]
    assert cm["pilot_contacts_limits"] == LIM
    assert "Not merged: a contacts list is at most <n> rows" in cm["pilotdb_answers"]
    assert ("Not merged: over <n> pilots that no list of Ryan's holds; ask Ryan to upload his own list first"
            in cm["pilotdb_answers"])
    text = " ".join(cm["pilot_contacts_checks"])
    for word in ("rows_max", "cell_chars", "notes_chars", "new_max", "Windows-1252", "refused whole"):
        assert word in text, word


def test_a_list_of_more_than_rows_max_rows_is_refused_by_both_watchers():
    assert len(PS.contacts_check(_csv(_new_rows(LIM["rows_max"])))["hal_only"]) == LIM["rows_max"]
    with pytest.raises(PS.ContactsRefused) as e:
        PS.contacts_check(_csv(_new_rows(LIM["rows_max"] + 1)))
    assert str(e.value) == "Not merged: a contacts list is at most 2500 rows"


def test_a_list_that_would_add_over_new_max_records_is_refused_whole_and_changes_nothing(tmp_path):
    db = _db(tmp_path)
    root = str(tmp_path / "pilotdb")
    before, rev = db.summary()["records"], db.rev
    # 251 made-up pilots and one row that would add a number to Jane: nothing of it lands
    rows = _new_rows(LIM["new_max"] + 1) + [ROWS[0]]
    _put(root, _csv(rows), now=T0.timestamp())
    lines = []
    out = PS.drain(db, ["james"], root, now=T0.timestamp() + 1, log=lines.append)
    assert out["refused"] == 1 and out["applied"] == 0 and not os.listdir(PS.inbox_dir("james", root))
    a = db.answer_of("james", UID)
    assert not a["ok"] and a["why"] == ("Not merged: over 250 pilots that no list of Ryan's holds; ask Ryan to upload "
                                        "his own list first")
    assert db.summary()["records"] == before and db.find("30000") is None and db.pilot_made() == 0
    assert [p["number"] for p in _f(db, "10001", "phones")["value"]] == ["808-555-0101"]
    assert not db.db.execute("SELECT 1 FROM merges WHERE by='james'").fetchone()
    assert not db.db.execute("SELECT 1 FROM field_log WHERE by='james'").fetchone()
    assert lines == ["pilot db: contacts list from james: refused"]
    assert db.record(db.find("10001"))["fields"]["phones"]["by"] == "ryan" and db.rev >= rev
    db.close()


def test_new_max_is_a_standing_total_over_every_pilots_lists_and_ryans_own_list_frees_it(tmp_path):
    db = _db(tmp_path)
    r = db.pilot_contacts("james", "uDemoContactsFlood01", _cj(_new_rows(200)), "aa" * 32, CT.PARSER)
    assert r[0] and r[2]["added"] == 200 and db.pilot_made() == 200
    db.clock_box["t"] = T0 + timedelta(days=2)
    # 60 more would make 260: refused, from another pilot too (one database, one bound)
    more = _cj(_new_rows(60, start=40000), "2026-11-18")
    ok, why, st = db.pilot_contacts("kate", "uDemoContactsFlood02", more, "bb" * 32, CT.PARSER)
    assert (ok, st) == (False, None) and why.startswith("Not merged: over 250 pilots") and db.pilot_made() == 200
    assert db.find("40000") is None
    # 50 more fit exactly; a list that adds nobody is always taken
    ok, why, st = db.pilot_contacts("kate", "uDemoContactsFlood03", _cj(_new_rows(50, start=40000), "2026-11-18"),
                                    "cc" * 32, CT.PARSER)
    assert ok and st["added"] == 50 and db.pilot_made() == 250
    ok, _why, st = db.pilot_contacts("kate", "uDemoContactsFlood04", _cj([ROWS[0]], "2026-11-18"), "dd" * 32, CT.PARSER)
    assert ok and st.get("added", 0) == 0
    # a pilot's own hand edit does not make a record 'Ryan's'; Ryan's own contacts list holding the pilot does
    pid = db.find("30000")
    db.pilot_op("james", "edit", {"op": "set", "pid": pid, "field": "status", "value": "A",
                                  "rev": db.record(pid)["rev"], "rid": "uDemoEditFlood00001"},
                roles.PILOTDB_NOTE_LIMITS)
    assert db.pilot_made() == 250
    db.clock_box["t"] = T0 + timedelta(days=3)
    mine = dict(_cj([ROWS[0]] + _new_rows(10), "2026-11-19"), uploaded_by="ryan")
    db.merge_contacts(mine)
    assert db.pilot_made() == 240
    db.close()


# ---------------------------------------------------------------- no cell holds the parser or the database
def test_a_long_cell_a_long_note_and_a_cell_beyond_the_header_are_refused():
    def row(**over):
        r = ["Jane", "A", "Doe", "", "Example Air", "First Officer", "808-555-0111", "jane.doe@example.com", "10001",
             "HAL Emp# 10001"]
        for i, v in over.items():
            r[int(i[1:])] = v
        return r
    ok = [row(c7="j" * (LIM["cell_chars"] - 12) + "@example.com"), row(c9="HAL Emp# 10001 " + "x" * (LIM["notes_chars"] - 15))]
    assert PS.contacts_check(_csv(ok))
    assert PS.contacts_check(_csv([row() + ["", " "]]))  # empty cells after the last column (a trailing comma)
    bad = {"an email cell over cell_chars": [row(c7="j" * (LIM["cell_chars"] + 1))],
           "a name cell over cell_chars": [row(c2="D" * (LIM["cell_chars"] + 1))],
           "a note over notes_chars": [row(c9="x" * (LIM["notes_chars"] + 1))],
           "text beyond the header's columns": [row() + ["more"]]}
    for name, rows in bad.items():
        with pytest.raises(PS.ContactsRefused) as e:
            PS.contacts_check(_csv(rows))
        assert str(e.value) == PS.CONTACTS_BAD, name
    # a quoted cell that swallows the rest of the file (one cell over the csv module's own limit)
    with pytest.raises(PS.ContactsRefused):
        PS.contacts_check(_csv([row()]) + b'"' + b"x" * 200000)


def test_a_crafted_list_of_the_largest_size_is_answered_in_seconds():
    """The 130000 letter email cell of the review took 14 s a cell (100 s a list, inside the database's lock)."""
    t = time.monotonic()
    assert CT.emails_in("j" * 130000) == [] and CT.emails_in("x" * 70 + " jane.doe@example.com") == ["jane.doe@example.com"]
    assert CT.emails_in("jane.doe@example.com, j.d+x@mail.example.com") == ["jane.doe@example.com", "j.d+x@mail.example.com"]
    assert time.monotonic() - t < 2
    cell = "a" * LIM["cell_chars"]
    worst = {"letters": [cell] * 9 + ["n" * LIM["notes_chars"]],
             "hyphens": ["a-" * (LIM["cell_chars"] // 2)] * 9 + ["a-" * (LIM["notes_chars"] // 2)],
             "ats": ["a@" * (LIM["cell_chars"] // 2)] * 9 + ["a@a." * (LIM["notes_chars"] // 4)],
             "digits": ["1" * LIM["cell_chars"]] * 9 + ["1 " * (LIM["notes_chars"] // 2)]}
    for name, r in worst.items():
        n = min(LIM["rows_max"], (LIM["file_bytes"] - len(HEAD) - 200) // (sum(len(c) for c in r) + 12))
        raw = _csv([ROWS[0]] + [r] * n)
        assert len(raw) <= LIM["file_bytes"]
        t = time.monotonic()
        try:
            PS.contacts_check(raw)
        except PS.ContactsRefused:
            pass
        assert time.monotonic() - t < 5, name


def test_the_admin_checks_a_waiting_list_before_it_takes_the_databases_lock(tmp_path, monkeypatch):
    db = _db(tmp_path)
    root = str(tmp_path / "pilotdb")
    name = _put(root, _csv(), now=T0.timestamp())
    lock = threading.RLock()  # stands for watcher.PDB_LOCK
    seen = []
    real = PS.contacts_check

    def check(raw, limits=None, today=None):
        got = lock.acquire(blocking=False)  # from another thread it would wait while the lock is held
        if got:
            lock.release()
        seen.append(threading.current_thread() is threading.main_thread() and getattr(check, "held", False))
        return real(raw, limits, today)
    monkeypatch.setattr(PS, "contacts_check", check)
    pre = PS.contacts_precheck(["james"], root, today=db.today())
    assert list(pre) == [("james", name)] and pre[("james", name)][1]["entries"]
    with lock:
        check.held = True
        out = PS.drain(db, ["james"], root, now=T0.timestamp() + 1, checked=pre)
        check.held = False
    assert out["applied"] == 1 and seen == [False]  # the one check ran before the lock, none inside it
    assert db.find("10004") and db.answer_of("james", UID)["ok"]
    # a refusal found outside the lock is answered by the drain, and other bytes under that name are checked again
    _put(root, b"%PDF-1.4 x", rid="uDemoContactsPdf0001", now=T0.timestamp() + 2)
    pre = PS.contacts_precheck(["james"], root, today=db.today())
    assert isinstance(next(iter(pre.values()))[1], PS.ContactsRefused)
    assert PS.drain(db, ["james"], root, now=T0.timestamp() + 3, checked=pre)["refused"] == 1
    assert db.answer_of("james", "uDemoContactsPdf0001")["why"] == PS.CONTACTS_BAD
    name = _put(root, _csv([ROWS[1]]), rid="uDemoContactsSwap001", now=T0.timestamp() + 4)
    stale = {("james", name): ("0" * 64, PS.ContactsRefused(PS.CONTACTS_BAD))}
    assert PS.drain(db, ["james"], root, now=T0.timestamp() + 5, checked=stale)["applied"] == 1
    db.close()


def test_the_watchers_share_pass_checks_outside_pdb_lock():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(here, "watcher.py"), encoding="utf-8").read()
    src = src[src.index("def pilotdb_share_pass("):]
    src = src[:src.index("\ndef ", 10)]
    assert src.index("PS.contacts_precheck(") < src.index("with PDB_LOCK:") < src.index("PS.drain(")
    assert "checked=checked" in src


# ---------------------------------------------------------------- Ryan answers a held row of a pilot's list
def _held(db, row, day="2026-11-16"):
    r = db.merge_contacts(_cj([row], day), by="james")
    assert r["conflicts"] == 1
    c = db.conflicts()
    assert len(c) == 1
    return c[0]


def test_a_held_row_ryan_attaches_adds_and_never_drops_or_replaces(tmp_path):
    db = _db(tmp_path)
    jane = db.find("10001")
    # another name on Jane's number, another phone, no email, no retirement month: held (other_pilot)
    c = _held(db, ["Jan", "", "Dough", "", "", "", "808-555-0199", "", "10001", "HAL Emp# 10001"])
    assert c["kind"] == "other_pilot"
    db.resolve(c["id"], "attach", jane)
    ph = _f(db, "10001", "phones")
    assert [p["number"] for p in ph["value"]] == ["808-555-0101", "808-555-0199"] and ph["by"] == "ryan"
    assert _f(db, "10001", "emails")["value"] == ["jane.doe@example.com"]
    assert _f(db, "10001", "retire")["value"] == "2041-03" and _f(db, "10001", "sen")["value"] == "812"
    assert not db.db.execute("SELECT 1 FROM field_log WHERE pid=? AND new IS NULL", (jane,)).fetchone()
    # the addition is in the history under the pilot's name
    log = db.db.execute("SELECT old,new,by,ref FROM field_log WHERE pid=? AND field='phones' ORDER BY id DESC",
                        (jane,)).fetchone()
    assert "0199" not in log[0] and "0199" in log[1] and log[2:] == ("james", "pilot contacts 2026-11-16")
    db.close()


def test_a_held_row_with_no_hal_number_attached_keeps_ryans_values_too(tmp_path):
    db = _db(tmp_path)
    jane = db.find("10001")
    c = _held(db, ["Janet", "", "Dove", "", "", "", "808-555-0198", "", "", ""])
    assert c["kind"] == "contact_unmatched"
    db.resolve(c["id"], "attach", jane)
    assert [p["number"] for p in _f(db, "10001", "phones")["value"]] == ["808-555-0101", "808-555-0198"]
    assert _f(db, "10001", "emails")["value"] == ["jane.doe@example.com"]
    assert _f(db, "10001", "retire")["value"] == "2041-03"
    db.close()


def test_a_held_row_of_ryans_own_list_is_applied_as_before(tmp_path):
    db = _db(tmp_path)
    jane = db.find("10001")
    db.clock_box["t"] = T0 + timedelta(days=1)
    mine = dict(_cj([["Jan", "", "Dough", "", "", "", "808-555-0199", "", "10001", "HAL Emp# 10001"]], "2026-11-17"),
                uploaded_by="ryan")
    assert db.merge_contacts(mine)["conflicts"] >= 1
    c = next(x for x in db.conflicts() if x["kind"] == "other_pilot")
    db.resolve(c["id"], "attach", jane)
    assert [p["number"] for p in _f(db, "10001", "phones")["value"]] == ["808-555-0199"]  # his list says her phones
    db.close()


# ---------------------------------------------------------------- whose value it is, and Ryan's next list
def test_ryans_number_stays_ryans_when_a_pilot_adds_one_and_his_next_list_removes_both_alike(tmp_path):
    db = _db(tmp_path)
    jane = db.find("10001")
    db.merge_contacts(_cj([ROWS[0], ROWS[1]]), by="james")  # adds 808-555-0111 to Jane; Rick's email is his alone
    row = db.db.execute("SELECT by,ref FROM vals WHERE pid=? AND field='phones' AND source='contacts'", (jane,)).fetchone()
    assert row == ("ryan", "contacts 2026-11-14")
    rick = db.db.execute("SELECT by,ref FROM vals WHERE pid=? AND field='emails' AND source='contacts'",
                         (db.find("10002"),)).fetchone()
    assert rick == ("james", "pilot contacts 2026-11-16")
    # Ryan's next whole list no longer holds Jane (it holds 20 others, so it is not partial)
    db.clock_box["t"] = T0 + timedelta(days=3)
    nxt = dict(_cj(_new_rows(20, start=50000), "2026-11-19"), uploaded_by="ryan")
    r = db.merge_contacts(nxt)
    assert r["applied"] and r.get("removed", 0) == 1 and r.get("conflicts", 0) == 0
    assert _f(db, "10001", "phones")["value"] == [] and _f(db, "10001", "emails")["value"] == []
    # what only a pilot's list gave stays, and the removed value is in the history with the pilot's number in it
    assert _f(db, "10002", "emails")["value"] == ["rick.roe@example.com"]
    old = db.db.execute("SELECT old FROM field_log WHERE pid=? AND field='phones' AND new IS NULL", (jane,)).fetchone()[0]
    assert "0101" in old and "0111" in old
    db.close()


def test_the_partial_list_answer_gone_keeps_what_only_a_pilots_list_gave(tmp_path):
    db = _db(tmp_path)
    jane = db.find("10001")
    db.clock_box["t"] = T0 + timedelta(days=1)
    whole = dict(_cj([ROWS[0], ROWS[1]] + _new_rows(20, start=50000), "2026-11-17"), uploaded_by="ryan")
    db.merge_contacts(whole)  # Ryan's whole list: Jane, Rick and 20 others
    db.clock_box["t"] = T0 + timedelta(days=2)
    db.merge_contacts(_cj([["Rick", "", "Roe", "", "", "", "808-555-0177", "", "10002", "HAL Emp# 10002"]], "2026-11-18"),
                      by="james")
    db.clock_box["t"] = T0 + timedelta(days=3)
    part = dict(_cj(_new_rows(3, start=50000), "2026-11-19"), uploaded_by="ryan")
    assert db.merge_contacts(part).get("conflicts") == 1
    c = next(x for x in db.conflicts() if x["kind"] == "list_partial")
    db.resolve(c["id"], "gone")
    # Jane's and Rick's values from Ryan's list go; the phone only james's list gave Rick stays
    assert _f(db, "10001", "emails")["value"] == [] and _f(db, "10001", "phones")["value"] == []
    assert _f(db, "10002", "emails")["value"] == []
    assert [p["number"] for p in _f(db, "10002", "phones")["value"]] == ["808-555-0177"]
    assert jane
    db.close()


# ---------------------------------------------------------------- the same file Ryan's own upload reads
def test_a_windows_1252_export_is_read_as_ryans_own_upload_reads_it():
    raw = _csv().replace(b"Jane", b"Ren\xe9e", 1)
    with pytest.raises(UnicodeDecodeError):
        raw.decode("utf-8")
    assert CT.sniff(raw) == "csv"
    mine = CT.parse(raw, "csv", today=T0.date())
    got = PS.contacts_check(raw, today=T0.date())
    assert got["entries"] == mine["entries"] and len(got["entries"]) == 3
    assert PS.contacts_text(raw).count("Renée") == 1
    # a byte Windows-1252 does not have, and a control character in such a file, are still refused
    for bad in (raw.replace(b"\xe9", b"\x8d", 1), raw.replace(b"Example Air", b"Example\x07Air", 1)):
        with pytest.raises(PS.ContactsRefused) as e:
            PS.contacts_check(bad)
        assert str(e.value) == PS.CONTACTS_BAD


# ---------------------------------------------------------------- the card
def _refused_by_portal(message):
    with _browser() as b:
        pg = _page(b, [_card("pilot-uploads-card")], width=390)
        pg.evaluate("""([st, msg]) => { window.tries = 0; window.c = mount('flight-watcher-pilot-uploads-card-pilot2', {}, st,
          { callService: async () => { window.tries += 1; throw new Error(msg); } }); }""", [_view(), message])
        _pick_csv(pg, _csv())
        pg.evaluate("() => c.shadowRoot.querySelector('[data-up]').click()")
        pg.wait_for_function("() => /^Not sent/.test(c.shadowRoot.querySelector('[data-msg]').textContent)", timeout=5000)
        got = pg.evaluate("() => [window.tries, c.shadowRoot.querySelector('[data-up]').disabled, "
                          "c.shadowRoot.querySelector('[data-msg]').textContent]")
        _shot(pg, "review_portal_refusal_390")
    return got


@pytest.mark.parametrize("message,shown", [
    ("Not available in the portal: upload/pdf: that file is not the contacts list (CSV) export.",
     "Not sent: that file is not the contacts list (CSV) export. Nothing was merged."),
    ("Not available in the portal: your Flight Watcher is too old for this. Ask Ryan to update it.",
     "Not sent: your Flight Watcher is too old for this. Ask Ryan to update it. Nothing was merged."),
    ("Not available in the portal: this page is from before a portal update. Reload the page, then send it again.",
     "Not sent: this page is from before a portal update. Reload the page, then send it again. Nothing was merged."),
    ("Not available in the portal: upload/pdf: <img src=x onerror=alert(1)> parts do not fit",
     "Not sent: img src x onerror alert(1) parts do not fit. Nothing was merged."),
])
def test_a_refusal_of_the_live_portal_is_shown_in_its_own_words_not_as_a_missing_update(message, shown):
    tries, disabled, text = _refused_by_portal(message)
    assert tries == 1 and disabled is False and text == shown
    assert "next update" not in text


def test_only_an_older_portals_own_words_mean_it_needs_its_update():
    got = _refused_by_portal("Not available in the portal: upload/pdf: kind is not one of pairings, award.")
    assert got == [1, False, "Not sent: the portal does not take a contacts list yet (it needs its next update). "
                             "Nothing was sent."]


@pytest.mark.parametrize("width", [390, 820, 1280])
def test_the_fields_are_16_px_and_44_px_high_at_every_width(width):
    with _browser() as b:
        pg = _page(b, [_card("pilot-uploads-card")], width=width)
        pg.evaluate("""(st) => { window.c = mount('flight-watcher-pilot-uploads-card-pilot2', {}, st); }""", _view())
        got = pg.evaluate("""() => { const r = c.shadowRoot, m = (q) => { const e = r.querySelector(q);
            return [getComputedStyle(e).fontSize, Math.round(e.getBoundingClientRect().height)]; };
          return { kind: m('[data-kind]'), month: m('[data-month]'), file: m('[data-pdf]'), up: m('[data-up]'),
                   page: document.documentElement.scrollWidth, inner: window.innerWidth }; }""")
        _shot(pg, f"review_fields_{width}")
    for k in ("kind", "month", "file", "up"):
        assert got[k][0] == "16px" and got[k][1] >= 44, (k, got[k])
    assert got["page"] <= got["inner"]


def test_the_title_the_limit_line_and_one_answer():
    last = {"ok": True, "state": "merged", "at": "2026-11-16T20:02:00+00:00",
            "message": "Contacts merged: 4 rows read, 2 pilots added, 2 updated, 0 held for Ryan."}
    with _browser() as b:
        pg = _page(b, [_card("pilot-uploads-card")], width=390)
        pg.evaluate("""(st) => { window.c = mount('flight-watcher-pilot-uploads-card-pilot2', {}, st); }""",
                    _view(offered=False))
        off = pg.evaluate("() => c.shadowRoot.querySelector('.ttl').textContent")
        pg.evaluate("""(st) => { document.querySelector('.view').innerHTML = '';
          window.c = mount('flight-watcher-pilot-uploads-card-pilot2', {}, st); }""", _view())
        on = pg.evaluate("() => [c.shadowRoot.querySelector('.ttl').textContent, c.shadowRoot.querySelector('[data-lim]').textContent]")
        # the upload's answer arrives: it is shown once, under "Your contacts list"
        _pick_csv(pg, _csv())
        pg.evaluate("() => c.shadowRoot.querySelector('[data-up]').click()")
        pg.wait_for_function("() => window.calls.length >= 1", timeout=15000)
        uid = pg.evaluate("() => JSON.parse(window.calls[0][2].payload).uid")
        st = _view(last=last)
        key = next(iter(st))
        st[key]["attributes"]["answers"] = [{"uid": uid, "ok": True, "state": "merged", "message": last["message"],
                                             "at": last["at"]}]
        st[key]["last_updated"] = "2026-11-16T20:02:01+00:00"
        pg.evaluate("(st) => { c.hass = { ...c._h, states: st }; }", st)
        text = pg.evaluate("() => c.shadowRoot.textContent")
        msg = pg.evaluate("() => c.shadowRoot.querySelector('[data-msg]').textContent")
        _shot(pg, "review_one_answer_390")
    assert off == "Pairings package and award" and on[0] == "Uploads"
    assert "A contacts list: up to 1 MB." in on[1] and "1024 KB" not in on[1]
    assert text.count("Contacts merged: 4 rows read") == 1 and msg == ""


def test_handoff_no_longer_tells_the_old_order():
    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    text = open(os.path.join(here, "HANDOFF.md"), encoding="utf-8").read()
    for old in ("either order is safe", "Contract 1 stays revision 4", "read this\nparagraph and the release order instead"):
        assert old not in text, old
    assert chr(0x2014) not in text
    flat = " ".join(text.split())
    assert "HOM 1.9.1 goes live FIRST" in flat or "needs HOM 1.9.1 live FIRST" in flat
