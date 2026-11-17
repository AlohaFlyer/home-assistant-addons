"""1.7.10 review fixes, round 2 (Nov 15). Each test here failed before its fix. Synthetic pilots only ("Doe, Jane"
10001): no real name, number or page."""
import json
import logging
import os
import re

import pytest

import captures as CAPS
import pilotdb as PDBM
from test_crew_index import W  # noqa: F401  (the Watcher fixture: the admin's)
from test_fw177_pickers import JANE, RICK
from test_fw1710_speed_cap import FIRST, KEY, REQ, _db, _log, _pk  # noqa: F401

HERE = os.path.dirname(__file__)
SRC = open(os.path.join(HERE, "..", "watcher.py"), encoding="utf-8").read()
CARD = open(os.path.join(HERE, "..", "www", "flight-watcher-pilotdb-card.js"), encoding="utf-8").read()


# ---------------------------------------------------------------- the speed cap is each picker's own
def test_the_finds_row_shows_the_cap_only_for_its_own_picker(tmp_path):
    db = _db(tmp_path, by=f"FO {JANE}; RO {RICK}", seats="FO,RO", pickers=("10001", "10002"))
    db.score_pickup(KEY)
    assert db.set_req_cap(KEY, REQ, "10002") == "capped"  # the second picker's cap
    row = db.recent_finds()[0]
    assert (row["picker_emp"], row["dwell_s"], row["dwell_cap"]) == ("10001", 600, False)  # the shown picker's speed
    assert _pk(db)["scored"] == 600 and _log(db) == {f"{KEY}|10001": (600, 0), f"{KEY}|10002": (239, 1)}


def test_two_denials_naming_the_two_pickers_both_stay_and_a_second_pass_changes_nothing(tmp_path):
    db = _db(tmp_path, by=f"FO {JANE}; RO {RICK}", seats="FO,RO", pickers=("10001", "10002"))
    db.score_pickup(KEY)
    early = "2026-10-30T12:01-10:00"
    assert db.set_req_cap(KEY, REQ, "10001") == "capped" and db.set_req_cap(KEY, early, "10002") == "capped"
    assert _pk(db)["req_caps"] == {"10001": REQ, "10002": early}
    assert _log(db) == {f"{KEY}|10001": (239, 1), f"{KEY}|10002": (119, 1)}
    before = db.db.total_changes
    assert db.set_req_cap(KEY, REQ, "10001") == "same" and db.set_req_cap(KEY, early, "10002") == "same"
    assert db.db.total_changes == before  # idempotent: no write, no rescore
    row = db.recent_finds()[0]
    assert (row["picker_emp"], row["dwell_s"], row["dwell_cap"]) == ("10001", 239, True)


def test_a_recheck_that_names_another_picker_drops_the_old_pickers_cap(tmp_path):
    db = _db(tmp_path)
    db.score_pickup(KEY)
    assert db.set_req_cap(KEY, REQ, "10001") == "capped" and _pk(db)["scored"] == 239
    db.set_pickup(KEY, {"status": "filled", "by": f"FO {RICK}", "ca": "", "known": True, "pickers": ["10002"]})
    pk = _pk(db)
    assert "req_caps" not in pk and "capped" not in pk and pk["scored"] == 600
    row = db.recent_finds()[0]
    assert (row["picker_emp"], row["dwell_s"], row["dwell_cap"]) == ("10002", 600, False)


def test_a_cap_kept_by_the_first_build_is_still_read(tmp_path):
    db = _db(tmp_path)
    pk = dict(_pk(db), req_cap_at=REQ, req_cap_emp="10001")
    db.db.execute("UPDATE finds SET pickup=? WHERE key=?", (json.dumps(pk), KEY))
    assert db.score_pickup(KEY) == 239 and _log(db) == {f"{KEY}|10001": (239, 1)}


# ---------------------------------------------------------------- the pilot database
from datetime import datetime, timezone  # noqa: E402

import seniority as SEN  # noqa: E402
from test_fw1710_award_sen import ROWS, award  # noqa: E402

T0 = datetime(2026, 11, 15, 20, 0, tzinfo=timezone.utc)


@pytest.fixture
def pdb(tmp_path):
    d = PDBM.PilotDB(str(tmp_path / "p.sqlite"), (), lambda: T0)
    yield d
    d.close()


def _lst(date, pilots):
    return {"list_date": date, "pilots": {e: {"sen": s, "name": n, "last": n.split(",")[0], "doh": "2001-05-01",
                                              "seat": "", "equip": ""} for e, (s, n) in pilots.items()}}


def test_the_awards_dates_of_hire_do_not_erase_the_seat_of_its_seniority_lines(pdb):
    pdb.merge_award_sen("2026-12", SEN.award_sen_parse(award(ROWS))["rows"])
    jane = pdb.find("10001")
    assert pdb.record(jane)["fields"]["seat"]["value"] == "FO"
    r = pdb.merge_award({"award_month": "2026-12", "pilots": {"10001": {
        "sen": 72, "name": "Doe, Jane", "last": "Doe", "doh": "2001-05-01", "seat": ""}}})
    assert r["applied"]
    f = pdb.record(jane)["fields"]
    assert f["seat"]["value"] == "FO" and f["doh"]["value"] == "2001-05-01" and f["name"]["value"] == "Doe, Jane"


def test_a_pilot_an_old_list_dropped_who_is_on_a_later_award_is_back_and_both_lookups_agree(pdb):
    rest = {str(20000 + i): (900 + i, f"Poe{'abcdefghijklmnopqrst'[i]}, Pat") for i in range(20)}
    pdb.merge_list(_lst("2026-07-01", dict(rest, **{"10001": (812, "Doe, Jane")})))
    pdb.merge_list(_lst("2026-09-01", rest))
    jane = pdb.find("10001")
    assert pdb.record(jane)["gone"] is True
    # gone: neither lookup finds her (Ryan's found her before, a portal pilot's did not)
    assert pdb.name_hits("Doe") == [] and "10001" not in {r[0] for r in pdb.name_rows()}
    older = pdb.merge_award_sen("2026-08", SEN.award_sen_parse(award(ROWS[:1]))["rows"])
    assert not older.get("back") and pdb.record(jane)["gone"] is True  # an award before that list says nothing
    r = pdb.merge_award_sen("2026-12", SEN.award_sen_parse(award(ROWS[:1]))["rows"])
    assert r["back"] == 1 and pdb.record(jane)["gone"] is False
    assert [h["emp"] for h in pdb.name_hits("Doe")] == ["10001"] and "10001" in {r[0] for r in pdb.name_rows()}


# ---------------------------------------------------------------- Ryan's switches
def _sw(tmp_path, pilots=("james", "pilot3")):
    return str(tmp_path / "data" / "pilotdb_switches.json"), str(tmp_path / "share" / "switches_off.json"), lambda: pilots


def test_an_off_survives_a_lost_or_older_switches_file(tmp_path):
    path, mirror, pilots = _sw(tmp_path)
    os.makedirs(os.path.dirname(path))
    s = PDBM.Switches(path, mirror, pilots)
    s.set_share("james", False)
    s.set_ai(False)
    assert os.stat(mirror).st_mode & 0o777 == 0o600 and os.stat(os.path.dirname(mirror)).st_mode & 0o777 == 0o700
    assert json.load(open(mirror)) == {"v": 1, "share_off": ["james"], "ai_off": True}
    os.unlink(path)  # an older /data put back: the file is not there
    s2 = PDBM.Switches(path, mirror, pilots)
    assert (s2.shared("james"), s2.ai_on(), s2.shared("pilot3"), s2.broken) == (False, False, True, False)
    json.dump({"v": 1, "default": True, "share": {"james": True}, "ai": True}, open(path, "w"))  # or an older one
    s3 = PDBM.Switches(path, mirror, pilots)
    assert (s3.shared("james"), s3.ai_on()) == (False, False)  # off in either file is off
    s3.set_share("james", True)  # Ryan's own tap turns it on again, in both files
    s3.set_ai(True)
    assert json.load(open(mirror)) == {"v": 1, "share_off": [], "ai_off": False}
    assert (PDBM.Switches(path, mirror, pilots).shared("james"), PDBM.Switches(path, mirror, pilots).ai_on()) == (True, True)
    open(mirror, "w").write("{")  # a mirror that cannot be read fails closed
    assert PDBM.Switches(path, mirror, pilots).broken is True and not PDBM.Switches(path, mirror, pilots).shared("james")


def test_a_tap_on_a_broken_file_puts_the_defaults_back_and_turns_on_only_what_was_tapped(tmp_path):
    path, mirror, pilots = _sw(tmp_path)
    os.makedirs(os.path.dirname(path))
    open(path, "w").write("{")
    s = PDBM.Switches(path, mirror, pilots)
    assert s.broken and not s.shared("james") and not s.ai_on()
    s.set_share("james", True)
    assert json.load(open(path)) == {"v": 1, "default": True, "share": {"james": True, "pilot3": False}, "ai": False}
    s = PDBM.Switches(path, mirror, pilots)
    assert (s.shared("james"), s.shared("pilot3"), s.ai_on()) == (True, False, False)  # nothing came on untapped
    assert s.shared("pilot4") is True  # a pilot Ryan adds later is shared by default again (decision 2)
    s.set_ai(True)
    assert PDBM.Switches(path, mirror, pilots).ai_on() is True


def test_a_failed_write_leaves_the_running_watcher_as_it_was(tmp_path):
    path, mirror, pilots = _sw(tmp_path)
    s = PDBM.Switches(path, mirror, pilots)  # /data's folder does not exist: the write fails
    with pytest.raises(OSError):
        s.set_share("james", False)
    with pytest.raises(OSError):
        s.set_ai(False)
    assert s.shared("james") is True and s.ai_on() is True


def test_the_watcher_writes_no_file_for_a_pilot_switched_off_when_data_lost_its_switches(W, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setattr(W, "PILOTDB_SWITCHES", None)
    monkeypatch.setattr(W, "PILOTDB_FILE", str(tmp_path / "data" / "pilotdb.sqlite"))
    monkeypatch.setattr(W, "PILOTDB_SHARE", str(tmp_path / "share" / "pilotdb"))
    monkeypatch.setattr(W, "pilotdb_portal_pilots", lambda: ["james"])
    os.makedirs(tmp_path / "data")
    assert W.pilotdb_switches_mirror() == str(tmp_path / "share" / "pilotdb" / "switches_off.json")
    db = PDBM.PilotDB(W.PILOTDB_FILE, (), lambda: T0)
    try:
        W._pilotdb_switches(db).set_share("james", False)
        os.unlink(W.pilotdb_switches_path())
        assert W._pilotdb_switches(db).shared("james") is False and not db.is_shared("james")
        import pdbshare as PS
        assert PS.write_files(db, ["james"], W.PILOTDB_SHARE) == {"james": "off"}
        assert not os.path.exists(PS.export_path("james", W.PILOTDB_SHARE))
    finally:
        db.close()


# ---------------------------------------------------------------- Ryan's log: no crew name, number, e-mail or phone
LEAKS = ("Doe", "doe", "Jane", "jane", "John", "john", "Roe", "roe", "Rick", "rick", "Poe", "Pat", "Cruz", "cruz",
         "Mary", "Ann", "10001", "10002", "99999", "x@y.com", "555-0100", "5550100100", "(812)")


def _log_calls(src):
    """Every log call of a source, as one string each (to its closing bracket; brackets inside a string are text)."""
    out = []
    for m in re.finditer(r"\blog\.(?:info|warning|error|debug|exception)\(", src):
        depth, i, q = 1, m.end(), None
        while depth and i < len(src):
            ch = src[i]
            if q:
                if ch == "\\":
                    i += 1
                elif ch == q:
                    q = None
            elif ch in "\"'":
                q = ch
            else:
                depth += {"(": 1, ")": -1}.get(ch, 0)
            i += 1
        out.append(src[m.start():i])
    return out


def test_no_log_line_quotes_page_text_without_page_log():
    calls = _log_calls(SRC)
    assert len(calls) > 400
    quote = re.compile(r"(?<!len\()visible_text\(|\b(?:text|flat|html|raw|vis|txt)\[[^\]]*:[^\]]*\]|\[\"detail\"\]\[")
    bad = [c for c in calls if quote.search(c) and "page_log(" not in c]
    assert not bad, bad
    # the five lines the review named, and the trade decision's
    for call in ('near: %s", hits,\n                            page_log(text[', 'no month list: %s", page_log(visible_text(html)[:160])',
                 '(sp and sp["month"]) or page_log(visible_text(page)[:160])',
                 '(sp and sp["month"]) or page_log(visible_text(html)[:120])', "page_log(text[:300])",
                 'page_log(visible_text(html)[:200])', 'log.info("trade %s %s", r["status"], page_log(r["detail"][:120]))'):
        assert call in SRC, call


def test_the_tradeboard_lines_name_no_poster(W, caplog):  # noqa: F811
    for old in ('log.info("NEW tradeboard pickup %s", ev)', "pickups=%s text=%s", "A( calls; data: %s"):
        assert old not in SRC, old
    assert 'log.info("NEW tradeboard pickup %s %s", ev.get("pairing") or "?", ev.get("dates") or "")' in SRC
    assert 'log.info("tradeboard probe %s url=%s pickups=%d text=%d chars"' in SRC
    assert "no trip rows; %d A( calls; %d chars (the page is in the capture)" in SRC
    assert not [c for c in _log_calls(SRC) if "tradeboard" in c and re.search(r"\bev\)|list\(picks|poster", c)]
    from test_tradeboard import JS
    with caplog.at_level(logging.INFO, logger="flight_watcher"):  # and the net under them, should one come back
        W.log.info("NEW tradeboard pickup %s", {"pairing": "H3607", "poster": "Pat Poe", "row": "x@y.com 808-555-0100"})
        W.log.info("tradeboard 152: text=%s", "tradeboard h3606 04nov trade for x@y.com 808-555-0100 (808) 555-0100")
        W.log.info("tradeboard 152: data: %s", W.page_log(re.sub(r"\s+", " ", JS)))
    text = "\n".join(r.getMessage() for r in caplog.records)
    for leak in ("x@y.com", "555-0100", "5550100100"):
        assert leak not in text, (leak, text)
    assert "H3607" in text and "x@x.xxx ###-###-####" in text


@pytest.mark.parametrize("line, page, out", [
    ("De La Cruz, John", False, "xx xx xxxx, xxxx"),
    ("crew van der doe jr, jane m (10001) on h3601", True, "crew xxx xxx xxx xx, xxxx x (#####) on h3601"),
    ("Doe-Smith, Mary Ann", False, "xxx-xxxxx, xxxx xxx"),
    ("cs: h3607:17nov picked up by doe, jane (812)", False, "cs: h3607:17nov picked up by xxx, xxxx (###)"),
    ("Captain: DOE JOHN 99999 F/O: DOE JANE 10001", False, "Captain: xxx xxxx ##### F/O: xxx xxxx #####"),
    ("trade: DOE JANE 10001", False, "trade: xxx xxxx #####"),
    ("pilot db: sync skipped: KeyError('10001')", False, "pilot db: sync skipped: KeyError('#####')"),
    ("posted by x@y.com 808-555-0100 or (808) 555-0100", False, "posted by x@x.xxx ###-###-#### or (###) ###-####"),
    ("trade approved 11/04 08:57 trade h3606 04nov with doe, jane for h3607 25nov", True,
     "trade approved 11/04 08:57 trade h3606 04nov with xxx, xxxx for h3607 25nov"),
    ("sched 08:00 roe, rick 10002 doe, jane 10001", True, "sched 08:00 xxx, xxxx ##### xxx, xxxx #####"),
])
def test_the_admins_mask_takes_the_rounds_two_shapes(line, page, out):
    assert CAPS.mask_crew(line, page=page) == out
    assert CAPS.mask_crew(out, page=page) == out
    for leak in LEAKS:
        assert leak not in out, (leak, out)


@pytest.mark.parametrize("line", [
    "Doe, Jane Schedule read"[10:], "pot 2026-11: 14 pairings, 2 new, FLICA loads this hour 37 of 240",
    "NEW pairing H3601 17Nov 4 days LAX credit 21:30 at 2026-11-17 08:00", "pilot db: file 1763200000 bytes 3307104",
    "tradeboard probe 152 url=https://x/tb pickups=3 text=1500 chars", "NEW tradeboard pickup H3607 25Nov-27Nov",
    "schedule 2026-11: Friday, November 20 report 08:00",
])
def test_ordinary_lines_stay_as_they_are(line):
    assert CAPS.mask_crew(line) == line


def test_a_very_long_token_costs_the_mask_no_seconds():
    import time
    for tok in ("A" * 20000, "x-" * 10000, "a1" * 10000 + " x@y.com", "a_" * 10000 + "@"):
        t0 = time.time()
        CAPS.mask_crew(tok, page=True)
        assert time.time() - t0 < 1.0, tok[:4]


def test_two_namesakes_in_the_pick_list_are_told_apart_by_sen(W, monkeypatch):  # noqa: F811
    class View:
        sens = {"10001": "72", "10002": "100"}
    monkeypatch.setattr(W, "pilotdb_view", lambda: View)
    hits = [{"emp": "10001", "name": "Kai", "seat": "FO"}, {"emp": "10002", "name": "Kai", "seat": "FO"},
            {"emp": "10003", "name": "Doe, Jane", "seat": "FO"}, {"emp": "10004", "name": "Kai", "seat": "CA"}]
    assert W.pick_seats(hits) == ["FO Sen 72", "FO Sen 100", "FO", "CA"]
    assert W.pick_seats(hits[2:]) == ["FO", "CA"]


# ---------------------------------------------------------------- the file's size ladder has no cliff
def test_past_the_hard_size_the_newest_notes_and_entries_stay(pdb):
    from datetime import timedelta
    box = {"t": T0}
    pdb.clock = lambda: box["t"]
    pids = []
    for i in range(40):
        pid = pdb.new_record(str(20000 + i), f"Doe{'abcdefghij'[i // 10]}{'abcdefghij'[i % 10]}, Jane", None)
        box["t"] = T0 + timedelta(minutes=i)
        pdb.save_notes(pid, f"notes {i:02d} " + "n" * 600, PDBM.ZERO_REV)
        for j in range(6):
            pdb.add_entry(pid, f"entry {i:02d}-{j} " + "e" * 200, True, f"rid-{i:03d}{j:03d}")
        pids.append(pid)

    def size(d):
        return len(json.dumps(d, ensure_ascii=False, separators=(",", ":")).encode())
    whole = size(pdb.export_for("james", hard=10 ** 9))
    bare = size(dict(pdb.export_for("james", hard=10 ** 9), records=[
        {k: v for k, v in r.items() if k not in ("notes", "entries")} for r in pdb.export_for("james", hard=10 ** 9)["records"]]))
    hard = bare + (whole - bare) // 3  # room for about a third of the texts
    d = pdb.export_for("james", hard=hard)
    recs = {r["pid"]: r for r in d["records"]}
    assert size(d) <= hard and d["full"] is True and d["count"] == 40
    noted = [p for p in pids if "notes" in recs[p]]
    shown = sum(len(recs[p]["entries"]) for p in pids)
    assert noted and shown, "before: no notes field and no entry at all once the file was over"
    assert size(d) > hard * 0.9  # the room is used
    assert "notes" in recs[pids[-1]] and len(recs[pids[-1]]["entries"]) == 6  # the newest texts are there
    assert "notes" not in recs[pids[0]] and recs[pids[0]]["entries"] == [] and recs[pids[0]]["entries_total"] == 6
    for p in pids:  # a record's entries are a run from its newest on
        assert [e["eid"] for e in recs[p]["entries"]] == [e["eid"] for e in pdb.export_for("james", hard=10 ** 9)["records"][
            [r["pid"] for r in d["records"]].index(p)]["entries"]][:len(recs[p]["entries"])]


# ---------------------------------------------------------------- the portal card (Chromium)
from test_fw179_pilotdb_portal_card import (LIST_NAMES, SIZES, _mount, _page, _txt, _type,  # noqa: E402
                                            side as side)  # noqa: F401
from test_pilot_grid_look import _browser  # noqa: E402
import pdbshare as PS  # noqa: E402
import portal as PT  # noqa: E402

SHOTS2 = os.environ.get("FW_1710B_SHOTS", "")
NAMES = ["O'Brien, Pat", "De La Cruz, Ana", "McDonald-Smith, Lee", "St. John, Al", "Kaʻanaʻana, Kimo", "Zedb, Zoe",
         "Doe, Jane"]


def _file(side, recs, **top):  # noqa: F811
    doc = dict({"v": 1, "generated": "2026-11-15T20:00:00+00:00", "as_of": {"list": "2026-11-01", "contacts": "", "award": ""},
                "count": len(recs), "records": recs, "answers": [], "limits": PT.pilotdb_limits()}, **top)
    os.makedirs(os.path.join(side.root, "portal"), exist_ok=True)
    open(PS.export_path("james", side.root), "w", encoding="utf-8").write(json.dumps(doc, separators=(",", ":")))
    side.view.refresh()
    assert side.view.state == "on"


def _recs(names):
    return [{"pid": "p%010x" % i, "emp": str(20000 + i), "name": n, "sen": str(i + 1), "doh": "2001-05-01", "status": "A",
             "retire": "2041-03", "seat": "FO", "equip": "A330", "base": "HNL", "union_id": "",
             "phones": [{"label": "mobile", "number": "808-555-0101", "tel": "+18085550101"}],
             "emails": ["jane.doe@example.com"], "gone": False, "edited": [], "rev": 1, "entries": [], "entries_total": 0}
            for i, n in enumerate(names)]


def test_the_search_field_survives_a_composing_keyboard_and_the_count_is_one_lasting_live_region(side):  # noqa: F811
    _file(side, _recs(NAMES))
    with _browser() as b:
        pg = _page(b, side, 390, 844, "light", [])
        _mount(pg, side)
        pg.wait_for_function("C.shadowRoot.textContent.includes('All pilots (7)')")
        pg.evaluate("""() => { const r = C.shadowRoot; window.INP = r.querySelector('[data-k=pq]');
          window.CNT = r.querySelector('[data-pcount]'); INP.focus(); }""")
        cdp = pg.context.new_cdp_session(pg)
        for part in ("z", "ze", "zed", "zedb"):  # what Gboard or any IME sends while a word is composed
            cdp.send("Input.imeSetComposition", {"text": part, "selectionStart": len(part), "selectionEnd": len(part)})
        cdp.send("Input.insertText", {"text": "zedb"})
        pg.wait_for_function("C.shadowRoot.querySelector('[data-pcount]').textContent.includes('1 pilot matches')")
        assert pg.evaluate("() => C.shadowRoot.querySelector('[data-k=pq]').value") == "zedb"  # before: 'zzezedzedbzedb'
        assert pg.evaluate(LIST_NAMES) == ["Zedb, Zoe"]
        # the field and the count line are the same nodes as before the typing (built once, never replaced)
        assert pg.evaluate("""() => { const r = C.shadowRoot; return [r.querySelector('[data-k=pq]') === INP,
          r.querySelector('[data-pcount]') === CNT, r.activeElement === INP, CNT.getAttribute('role'), CNT.getAttribute('aria-live')]; }""") \
            == [True, True, True, "status", "polite"]
        pg.keyboard.press("Backspace")
        pg.keyboard.type("x")
        assert pg.evaluate("() => [INP.value, CNT.textContent, C.shadowRoot.querySelector('[data-k=pq]') === INP]") == [
            "zedx", "No pilot matches.", True]
        # a filter chip keeps the field and its text too
        pg.evaluate("() => [...C.shadowRoot.querySelectorAll('[data-plist] .chip')].find((x) => x.textContent === 'Gone').click()")
        assert pg.evaluate("""() => [INP.value, C.shadowRoot.querySelector('[data-k=pq]') === INP,
          [...C.shadowRoot.querySelectorAll('[data-plist] .chip')].filter((x) => x.getAttribute('aria-pressed') === 'true').map((x) => x.textContent)]""") \
            == ["zedx", True, ["Gone"]]
        assert not pg.errors, pg.errors
        pg.context.close()


def test_a_last_name_typed_without_its_apostrophe_hyphen_or_space_is_found(side):  # noqa: F811
    _file(side, _recs(NAMES))
    with _browser() as b:
        pg = _page(b, side, 390, 844, "light", [])
        _mount(pg, side)
        pg.wait_for_function("C.shadowRoot.textContent.includes('All pilots (7)')")
        for q, want in (("obrien", ["O'Brien, Pat"]), ("o'brien", ["O'Brien, Pat"]), ("o’brien", ["O'Brien, Pat"]),
                        ("brien", ["O'Brien, Pat"]), ("delacruz", ["De La Cruz, Ana"]), ("de la cruz", ["De La Cruz, Ana"]),
                        ("mcdonaldsmith", ["McDonald-Smith, Lee"]), ("stjohn", ["St. John, Al"]),
                        ("kaanaana", ["Kaʻanaʻana, Kimo"]), ("delacruz, a", ["De La Cruz, Ana"]),
                        ("delacruz, b", []), ("obrienx", []), ("doe ja", ["Doe, Jane"])):
            _type(pg, "pq", q)
            assert pg.evaluate(LIST_NAMES) == want, q
        for q in (",", '""', '"', " , ", "."):  # no letter, digit or quoted text: no query, and the line does not say 'match'
            _type(pg, "pq", q)
            assert _txt(pg, "[data-pcount]") == "7 pilots, by Sen #.", q
        assert not pg.errors, pg.errors
        pg.context.close()


def test_the_mail_link_is_a_44_px_target_and_a_full_file_says_what_it_left_out(side):  # noqa: F811
    recs = _recs(NAMES)
    recs[0].update(entries=[{"eid": "n1", "by": "ryan", "at": "2026-11-15T20:00:00+00:00", "text": "newest"}], entries_total=4)
    recs[1].update(entries=[], entries_total=3)
    _file(side, recs, full=True)
    with _browser() as b:
        for width, height in SIZES:
            pg = _page(b, side, width, height, "light", [])
            _mount(pg, side)
            pg.wait_for_function("C.shadowRoot.textContent.includes('All pilots (7)')")
            ban = _txt(pg, ".ban")
            assert "6 older log entries are not shown here" in ban
            assert "only the newest log entries and pickups are shown" not in ban
            assert "new notes are refused until it is trimmed" in ban and "Nothing is lost" in ban
            pg.evaluate("() => [...C.shadowRoot.querySelectorAll('[data-plist] button.nm')][0].click()")
            pg.wait_for_function("!!C.shadowRoot.querySelector('a.ct')")
            small = pg.evaluate("""() => [...C.shadowRoot.querySelectorAll('button, a.ct, summary, input:not([type=checkbox])')]
              .filter((e) => e.getClientRects().length).map((e) => { const r = e.getBoundingClientRect();
                return [e.textContent.trim().slice(0, 20), Math.round(r.width), Math.round(r.height)]; })
              .filter((x) => x[1] < 44 || x[2] < 44)""")
            assert small == [], small  # before: the Mail link was 28 px wide
            assert pg.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth")
            if SHOTS2:
                os.makedirs(SHOTS2, exist_ok=True)
                pg.screenshot(path=os.path.join(SHOTS2, f"full_record_{width}.png"), full_page=True)
            assert not pg.errors, pg.errors
            pg.context.close()
