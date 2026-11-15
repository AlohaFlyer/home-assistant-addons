"""1.7.8 (Ryan, Nov 14: "should we have an editable pilot database that has these data points. and even a notes field
we can edit and append to"): pilotdb.py, the database itself (spec sections 5, 6, 9 and 18). The schema and its
user_version (a newer file is never opened); pid stability; a hand edit beats every upload, unset, keep and drift; the
ORDER and RECENCY rules, stale values and disagree; the field log; the notes field's compare-and-set and its kept
versions; the notes log (add, retract own only, hide, restore, purge, forget, the (by, rid) idempotency, the 500 cap);
the scrub leaves a purged text in no byte of the file, its WAL or a backup. Synthetic pilots only ("Doe, Jane", 10001)."""
import os
import sqlite3
import stat
from datetime import datetime, timedelta, timezone

import pytest

import pilotdb as P

T0 = datetime(2026, 11, 15, 20, 0, tzinfo=timezone.utc)  # 10:00 HST
LIST = {"list_date": "2026-07-01", "pilots": {
    "10001": {"sen": 812, "name": "Doe, Jane A.", "last": "Doe", "doh": "2001-05-01", "seat": "", "equip": "",
              "status": "SLOA"},
    "10002": {"sen": 13, "name": "Roe, Rick", "last": "Roe", "doh": "1985-09-17", "status": "A", "seat": "CA",
              "equip": "330", "retire": "2032-04"}}}
HAL_JANE = {"emp": "10001", "sen": "812", "sen_month": "2026-07", "doh": "2001-05-01", "status": "SLOA",
            "retire": "2041-03"}
CONTACTS = {"uploaded_at": "2026-11-14T09:30:00-10:00", "pilots": [
    {"emp": "010001", "name": "Doe, Jane", "name_full": "Doe, Jane A",
     "phones": [{"label": "cell", "number": "808-555-0101", "tel": "+18085550101"}],
     "emails": ["jane.doe@example.com"], "hal": HAL_JANE}]}


@pytest.fixture
def mk(tmp_path):
    clock = {"t": T0}

    def make(name="p.sqlite"):
        db = P.PilotDB(str(tmp_path / name), (str(tmp_path / "bk_data"), str(tmp_path / "bk_share")), lambda: clock["t"])
        db.clock_box = clock
        return db
    return make


def _jane(db):
    return db.find("10001")


def test_schema_user_version_and_private_file(mk, tmp_path):
    db = mk()
    assert db.db.execute("PRAGMA user_version").fetchone()[0] == P.USER_VERSION == 1
    tables = {n for (n,) in db.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert tables >= {"meta", "pilots", "vals", "field_log", "notes", "notes_hist", "entries", "act_log", "merges",
                      "conflicts", "answers", "share", "pickups", "ai_notes"}
    assert db.db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert db.db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert db.db.execute("PRAGMA secure_delete").fetchone()[0] == 1
    db.merge_list(LIST)
    for f in os.listdir(tmp_path):
        if f.startswith("p.sqlite"):
            assert stat.S_IMODE(os.stat(tmp_path / f).st_mode) == 0o600, f
    # the share tables and the AI note are there, unused in 1.7.8
    for t in ("share", "answers", "act_log", "ai_notes"):
        assert db.db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] == 0, t


def test_a_newer_database_is_never_opened(mk, tmp_path):
    db = mk()
    db.db.execute("PRAGMA user_version=2")
    db.close()
    with pytest.raises(P.NewerDB):
        mk()
    pdb, st = P.open_checked(str(tmp_path / "p.sqlite"), ())
    assert pdb is None and st["db"] == "newer_db"
    con = sqlite3.connect(str(tmp_path / "p.sqlite"))
    assert con.execute("PRAGMA user_version").fetchone()[0] == 2  # left as it was
    con.close()


def test_pid_is_stable_and_never_the_employee_number(mk):
    db = mk()
    db.merge_list(LIST)
    pid = _jane(db)
    assert pid.startswith("p") and len(pid) == 11 and "10001" not in pid
    db.merge_list(dict(LIST, list_date="2026-08-01"))
    db.merge_contacts(CONTACTS)
    assert _jane(db) == pid
    db.move(pid, "10011")
    assert db.find("10011") == pid and db.find("10001") is None


def test_hand_beats_uploads_unset_keep_and_drift(mk):
    db = mk()
    db.merge_list(LIST)
    pid = _jane(db)
    rec = db.record(pid)
    rec = db.set_field(pid, "doh", "2001-05-02", rec["rev"], "the list has a typo")
    f = rec["fields"]["doh"]
    assert (f["value"], f["source"], f["hand"], f["why"], f["drift"]) == ("2001-05-02", "hand", True,
                                                                        "the list has a typo", True)
    with pytest.raises(P.Stale) as e:  # a stale rev answers the fresh record
        db.set_field(pid, "doh", "2001-05-03", rec["rev"] - 1)
    assert e.value.current["fields"]["doh"]["value"] == "2001-05-02"
    # Keep my edit: drift dismissed until an upload brings another value
    rec = db.keep(pid, "doh")
    assert rec["fields"]["doh"]["drift"] is False
    db.merge_list(dict(LIST, list_date="2026-08-01"))  # the same list value again: still dismissed
    assert db.record(pid)["fields"]["doh"]["drift"] is False
    lst = {"list_date": "2026-09-01", "pilots": {"10001": dict(LIST["pilots"]["10001"], doh="2001-06-01"),
                                                "10002": LIST["pilots"]["10002"]}}
    db.merge_list(lst)
    rec = db.record(pid)
    assert rec["fields"]["doh"]["value"] == "2001-05-02" and rec["fields"]["doh"]["drift"] is True  # hand still shown
    rec = db.unset_field(pid, "doh", rec["rev"])
    assert (rec["fields"]["doh"]["value"], rec["fields"]["doh"]["source"]) == ("2001-06-01", "list")
    hows = [r["how"] for r in rec["field_log"] if r["field"] == "doh"]
    assert hows[:4] == ["unset", "upload", "keep", "hand"]
    with pytest.raises(P.Bad) as e:
        db.set_field(pid, "doh", "2099-01-01", rec["rev"])
    assert e.value.field == "doh" and "2099" not in str(e.value)  # errors name the field, never echo a value


def test_field_checks():
    today = T0.date()
    assert P.check("sen", "0812", today) == "812"
    assert P.check("status", "sloa", today) == "SLOA"
    assert P.check("seat", "fo", today) == "FO" and P.check("equip", "a330", today) == "A330"
    assert P.check("name", "  Doe,   Jane A Jr ", today) == "Doe, Jane A Jr"
    assert P.check("retire", "2041-03", today) == "2041-03" and P.check("union_id", "77001", today) == "77001"
    assert P.check("phones", [{"label": "cell", "number": "(808) 555-0101"}], today) == \
        '[{"label":"mobile","number":"808-555-0101","tel":"+18085550101"}]'
    assert P.check("emails", ["jane.doe@example.com", "JANE.DOE@example.com"], today) == '["jane.doe@example.com"]'
    for f, v in (("sen", "0"), ("sen", "123456"), ("doh", "1949-12-31"), ("doh", "2026-11-16"), ("status", "ZZZ"),
                 ("retire", "2041-13"), ("seat", "XX"), ("equip", "A-330"), ("name", "Doe"), ("name", "Doe,\nJane"),
                 ("name", "Doe, Jane‮"), ("name", "x" * 81 + ", J"), ("union_id", "12a"),
                 ("phones", [{"label": "fax", "number": "808-555-0101"}]), ("phones", [{"label": "home", "number": "12"}]),
                 ("emails", ["not an email"]), ("emails", ["a@example.com", "b@example.com", "c@example.com",
                                                          "d@example.com"]), ("nope", "1")):
        with pytest.raises(P.Bad):
            P.check(f, v, today)


def test_order_recency_stale_and_disagree():
    def row(src, v, as_of, stale=0):
        return {"source": src, "value": v, "as_of": as_of, "ref": f"{src} {as_of}", "at": "", "by": "ryan",
                "why": None, "stale": stale, "kept": None}
    # ORDER: the list first for doh even when the contacts are newer (Ryan: "the seniority PDF wins")
    rows = [row("contacts", "2001-05-02", "2026-11-14"), row("list", "2001-05-01", "2026-07-01")]
    v = P.field_view("doh", rows)
    assert (v["value"], v["source"], v["disagree"]) == ("2001-05-01", "list", True)
    # a stale list value comes after a fresh contacts one
    rows = [row("contacts", "812", "2026-07-01"), row("list", "811", "2026-01-01", stale=1)]
    assert P.field_view("sen", rows)["value"] == "812" and P.field_view("sen", rows)["disagree"] is False
    # sen differs in the same month: disagree; another month: not
    assert P.field_view("sen", [row("list", "811", "2026-07-01"), row("contacts", "812", "2026-07-01")])["disagree"]
    assert not P.field_view("sen", [row("list", "811", "2026-01-01"), row("contacts", "812", "2026-07-01")])["disagree"]
    # RECENCY (seat): the newest as_of; a tie goes list, contacts, award
    rows = [row("list", "FO", "2026-07-01"), row("award", "CA", "2026-12-01")]
    assert P.field_view("seat", rows)["value"] == "CA"
    assert P.field_view("seat", [row("award", "CA", "2026-07-01"), row("list", "FO", "2026-07-01")])["value"] == "FO"
    # the name key (last name, first initial) decides a name disagreement, not the spelling
    assert not P.field_view("name", [row("list", "Doe, Jane A.", "2026-07-01"),
                                     row("contacts", "Doe, Jane A", "2026-11-14")])["disagree"]
    assert P.field_view("name", [row("list", "Doe, Jane", "2026-07-01"),
                                 row("contacts", "Dow, Jane", "2026-11-14")])["disagree"]
    assert P.field_view("name", [row("list", "Doe, Jane", "2026-07-01"),
                                 row("contacts", "Doe, Mary", "2026-11-14")])["disagree"]


def test_field_log_rows_for_uploads(mk):
    db = mk()
    db.merge_list(LIST)
    pid = _jane(db)
    db.merge_contacts(CONTACTS)
    log = db.record(pid)["field_log"]
    assert {(r["field"], r["source"], r["how"]) for r in log} >= {
        ("_record", "list", "created"), ("doh", "list", "upload"), ("phones", "contacts", "upload"),
        ("retire", "contacts", "upload")}
    assert all(r["by"] == "ryan" and r["at"] for r in log)
    n = len(log)
    db.merge_contacts(dict(CONTACTS, uploaded_at="2026-11-20T09:00:00-10:00"))  # nothing changed: nothing logged
    assert len(db.record(pid)["field_log"]) == n


def test_notes_field_cas_versions_and_restore(mk):
    db = mk()
    db.merge_list(LIST)
    pid = _jane(db)
    a = db.save_notes(pid, "Good to fly with.\r\n\r\n\r\n\r\nLikes SYD.", P.ZERO_REV)
    assert a["text"] == "Good to fly with.\n\nLikes SYD." and len(a["rev"]) == 12 and a["by"] == "ryan"
    with pytest.raises(P.Stale) as e:  # a stale base: nothing is overwritten blind
        db.save_notes(pid, "blind write", P.ZERO_REV)
    assert e.value.current == a
    db.clock_box["t"] = T0 + timedelta(minutes=5)
    b = db.save_notes(pid, "Second version", a["rev"])
    assert db.record(pid)["notes"] == b
    hist = db.record(pid)["notes_hist"]
    assert [(h["text"], h["rev"]) for h in hist] == [(a["text"], a["rev"])]
    db.clock_box["t"] = T0 + timedelta(minutes=10)
    c = db.restore_notes(pid, hist[0]["id"], b["rev"])
    assert c["text"] == a["text"] and c["rev"] not in (a["rev"], b["rev"])
    d = db.save_notes(pid, "", c["rev"])  # an empty text clears the field, with a new rev
    assert d["text"] == "" and d["rev"] != c["rev"]
    for bad in ("x" * 4001, "bidi ‮", "nul \x00"):
        with pytest.raises(P.Bad):
            db.save_notes(pid, bad, d["rev"])
    for i in range(60):  # the newest 50 versions are kept
        db.clock_box["t"] = T0 + timedelta(hours=1, minutes=i)
        d = db.save_notes(pid, f"v{i}", d["rev"])
    assert len(db.record(pid)["notes_hist"]) == P.HIST_KEEP


def test_entries_add_retract_hide_restore_purge_and_idempotency(mk):
    db = mk()
    db.merge_list(LIST)
    pid = _jane(db)
    e1 = db.add_entry(pid, "Picked up SYD again", shared=True, rid="rid_0001")
    assert db.add_entry(pid, "Picked up SYD again", shared=True, rid="rid_0001") == e1  # same rid: nothing added
    e2 = db.add_entry(pid, "only for me", shared=False, rid="rid_0002")
    e3 = db.add_entry(pid, "by james", shared=True, rid="rid_0001", by="james")  # another author's rid is his own
    rec = db.record(pid)
    assert sorted(e["eid"] for e in rec["entries"]) == sorted([e1, e2, e3])
    assert sorted(e["by"] for e in rec["entries"]) == ["james", "ryan", "ryan"]
    with pytest.raises(P.Bad) as e:
        db.retract(e3, by="ryan")  # only the author takes back his own
    assert "own" in e.value.why
    db.retract(e3, by="james")
    got = {e["eid"]: e for e in db.record(pid)["entries"]}
    assert got[e3]["text"] == "" and got[e3]["gone"] == "retracted"
    db.hide(e1)
    got = {e["eid"]: e for e in db.record(pid)["entries"]}
    assert got[e1]["gone"] == "hidden" and got[e1]["text"] == "Picked up SYD again"  # Ryan still has it
    db.unhide(e1)
    assert "gone" not in {e["eid"]: e for e in db.record(pid)["entries"]}[e1]
    with pytest.raises(P.Bad):
        db.purge(eid=e1)  # hide it first
    db.hide(e1)
    db.purge(eid=e1)
    got = {e["eid"]: e for e in db.record(pid)["entries"]}
    assert got[e1]["text"] == "" and got[e1]["gone"] == "purged"
    assert got[e2]["shared"] is False
    # a pilot's write is counted (1.7.9 quotas), Ryan's are not; no text in act_log
    acts = db.db.execute("SELECT by,kind FROM act_log ORDER BY id").fetchall()
    assert acts == [("james", "add"), ("james", "retract")]


def test_the_500_entry_cap(mk):
    db = mk()
    db.merge_list(LIST)
    pid = _jane(db)
    with db._tx():
        for i in range(P.ENTRIES_PER_RECORD):
            db.db.execute("INSERT INTO entries(eid,pid,by,at,text) VALUES(?,?,?,?,?)",
                          (f"n{i:010x}", pid, "ryan", "2026-11-15T00:00:00+00:00", "x"))
    with pytest.raises(P.Bad) as e:
        db.add_entry(pid, "one more")
    assert e.value.why == "the log for that pilot is full"


def test_scrub_leaves_purged_text_in_no_byte(mk, tmp_path):
    db = mk()
    db.merge_list(LIST)
    pid = _jane(db)
    sentinel = "SENTINEL-NOTE-QXZ"
    db.backup()  # a copy before the note: holds no sentinel
    eid = db.add_entry(pid, f"{sentinel} entry")
    n = db.save_notes(pid, f"{sentinel} field", P.ZERO_REV)
    db.save_notes(pid, "plain now", n["rev"])
    db.clock_box["t"] = T0 + timedelta(days=1)
    db.backup()  # tomorrow's copy holds it
    assert any(sentinel.encode() in open(os.path.join(d, f), "rb").read()
               for d in db.backup_dirs for f in os.listdir(d))
    db.hide(eid)
    db.purge(eid=eid)
    hid = db.record(pid)["notes_hist"][0]["id"]
    db.purge(hist_id=hid)
    db.replace_backups()
    files = [str(tmp_path / f) for f in os.listdir(tmp_path) if f.startswith("p.sqlite")]
    files += [os.path.join(d, f) for d in db.backup_dirs for f in os.listdir(d)]
    for f in files:
        assert sentinel.encode() not in open(f, "rb").read(), f
    for d in db.backup_dirs:  # one fresh copy left in each folder, 0600 in a 0700 folder
        assert len(os.listdir(d)) == 1
        assert stat.S_IMODE(os.stat(d).st_mode) == 0o700
        assert all(stat.S_IMODE(os.stat(os.path.join(d, f)).st_mode) == 0o600 for f in os.listdir(d))


def test_forget_removes_the_whole_record(mk, tmp_path):
    db = mk()
    db.merge_list(LIST)
    db.merge_contacts(CONTACTS)
    pid = _jane(db)
    db.add_entry(pid, "FORGET-ME-QXZ")
    with pytest.raises(P.Bad):
        db.forget(pid, "delete")
    db.forget(pid, "DELETE")
    db.replace_backups()
    assert db.find("10001") is None
    for t in ("vals", "field_log", "notes", "entries"):
        assert db.db.execute(f"SELECT COUNT(*) FROM {t} WHERE pid=?", (pid,)).fetchone()[0] == 0
    for f in os.listdir(tmp_path):
        if f.startswith("p.sqlite"):
            raw = open(tmp_path / f, "rb").read()
            assert b"FORGET-ME-QXZ" not in raw and b"jane.doe@example.com" not in raw, f


def test_backups_keep_seven_and_the_start_checks(mk, tmp_path):
    db = mk()
    db.merge_list(LIST)
    for i in range(9):
        db.clock_box["t"] = T0 + timedelta(days=i)
        db.add_entry(_jane(db), f"day {i}")  # a change a day (a copy of an unchanged file has the same rev)
        db.backup()
    for d in db.backup_dirs:
        names = sorted(os.listdir(d))
        assert len(names) == P.BACKUP_KEEP and names[-1] == "pilotdb-2026-11-23.sqlite"
    live_rev = db.rev
    db.close()
    pdb, st = P.open_checked(str(tmp_path / "p.sqlite"), db.backup_dirs)
    assert st == {"db": "ok", "offer": None} and pdb.rev == live_rev
    # an older /data copy restored (the live rev is lower than the newest /share copy): offered, never overwritten
    pdb.close()
    old = os.path.join(db.backup_dirs[0], "pilotdb-2026-11-17.sqlite")
    os.replace(old, str(tmp_path / "p.sqlite"))
    for sfx in ("-wal", "-shm"):
        if os.path.exists(str(tmp_path / "p.sqlite") + sfx):
            os.remove(str(tmp_path / "p.sqlite") + sfx)
    pdb, st = P.open_checked(str(tmp_path / "p.sqlite"), db.backup_dirs)
    assert st["db"] == "restore_offered" and st["offer"]["file"] == "1/pilotdb-2026-11-23.sqlite"
    pdb.close()
    aside = P.restore(str(tmp_path / "p.sqlite"), db.backup_dirs, st["offer"]["file"])
    assert os.path.exists(aside) and stat.S_IMODE(os.stat(aside).st_mode) == 0o600
    pdb, st = P.open_checked(str(tmp_path / "p.sqlite"), db.backup_dirs)
    assert st["db"] == "ok" and pdb.find("10001")
    pdb.close()
    with pytest.raises(P.Bad):
        P.restore(str(tmp_path / "p.sqlite"), db.backup_dirs, "../../etc/passwd")
    # a file that fails integrity_check is set aside (0600) and the newest good copy offered; nothing is opened
    open(tmp_path / "p.sqlite", "wb").write(b"SQLite format 3\x00" + b"\xff" * 4000)
    for sfx in ("-wal", "-shm"):
        if os.path.exists(str(tmp_path / "p.sqlite") + sfx):
            os.remove(str(tmp_path / "p.sqlite") + sfx)
    pdb, st = P.open_checked(str(tmp_path / "p.sqlite"), db.backup_dirs)
    assert pdb is None and st["db"] == "error" and st["offer"]["day"] == "2026-11-23"
    bad = [f for f in os.listdir(tmp_path) if ".bad-" in f]
    assert bad and all(stat.S_IMODE(os.stat(tmp_path / f).st_mode) == 0o600 for f in bad)
    assert not os.path.exists(tmp_path / "p.sqlite")


def test_search_rows_hold_no_phones_or_emails(mk):
    db = mk()
    db.merge_list(LIST)
    db.merge_contacts(CONTACTS)
    pid = _jane(db)
    db.add_entry(pid, "Great on the SYD trip")
    res = db.search("doe")
    assert res["total"] == 1 and res["rows"][0]["pid"] == pid
    assert "555-01" not in str(res) and "example.com" not in str(res)
    assert db.search("1000")["total"] == 2 and db.search("s13")["rows"][0]["name"] == "Roe, Rick"
    assert db.search('"syd trip"')["rows"][0]["pid"] == pid and db.search('"nothing here"')["total"] == 0
    assert db.search("", "notes")["total"] == 1 and db.search("", "status:SLOA")["total"] == 1
    assert db.search("ja do")["total"] == 1  # every word prefix-matches a token
    with pytest.raises(P.Bad):
        db.search("x" * 61)
    with pytest.raises(P.Bad):
        db.search("", "everything")
    s = db.summary()
    assert (s["records"], s["live"], s["noted"], s["entries"]) == (2, 2, 1, 1)
    assert "Doe" not in str(s) and "10001" not in str(s) and len(str(s)) < 2048


def test_new_record_and_merging_a_duplicate(mk):
    db = mk()
    db.merge_list(LIST)
    jane = _jane(db)
    dup = db.new_record("10091", "Doe, Jane", "2001-05-01")
    assert dup != jane and db.record(dup)["fields"]["name"]["source"] == "hand"
    with pytest.raises(P.Bad):
        db.new_record("10091", "Doe, Janet")  # the same number and last name: another record has it
    n1 = db.save_notes(dup, "on the duplicate", P.ZERO_REV)
    db.add_entry(dup, "entry on the duplicate")
    db.save_notes(jane, "on jane", P.ZERO_REV)
    assert db.merge_records(dup, jane) == jane
    rec = db.record(jane)
    assert rec["notes"]["text"] == "on jane" and any(h["text"] == n1["text"] for h in rec["notes_hist"])
    assert [e["text"] for e in rec["entries"]] == ["entry on the duplicate"]
    assert db.find("10091") is None and db.search("", "all")["total"] == 2  # the duplicate is hidden
    assert db.record(dup)["merged_into"] == jane
    with pytest.raises(P.Missing):  # a merged record takes no edit
        db.set_field(dup, "sen", "1", db.record(dup)["rev"])
    with pytest.raises(P.Bad):
        db.merge_records(jane, jane)


def test_move_refuses_a_number_and_last_name_already_held(mk):
    db = mk()
    db.merge_list(LIST)
    jane = _jane(db)
    db.new_record("10095", "Doe, Jo")
    with pytest.raises(P.Bad):
        db.move(jane, "10095")
    with pytest.raises(P.Bad):
        db.move(jane, "abc")
    assert db.record(jane)["emp"] == "10001"
