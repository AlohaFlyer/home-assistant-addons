"""1.7.8 review fixes, the pilot database's Watcher side (each test failed on the builders' commit 65ac158): one pilot
listed twice (the contact list, a list's 'also'), one bad row and one failed merge no longer stop the pass; the 90%
guard keeps its baseline; a hand edit of the name or DOH never cuts a record off from its own rows; Ryan's Attach of a
contact row stays through later lists; a purge or a forget leaves no text in the files set aside beside the database
or in the conflicts table; a merged record keeps its pickups; a turn is no layover station; a notes rev never comes
back; the log's entries in one second stay newest first; an upload keeps its uploader; the in-flight re-check reaches
old pickups and logs no employee number. Synthetic data only ("Doe, Jane" 10001, 808-555-01xx, example.com)."""
import glob
import json
import logging
import os
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

import inflt
import pilotdb as P
import web
from store import Store
from test_contacts_hal_notes import ROWS, _csv
from test_crew_index import W  # noqa: F401  (the Watcher fixture)
from test_fw177_pickers import JANE, MAX, PAT, RICK, _find, _old_style
from test_fw178_inflt_recheck import _Fl, _done, _pk, _run
from test_pilotdb_watcher import P as PW  # noqa: F401  (the seeded pilot database fixture)

T0 = datetime(2026, 11, 15, 20, 0, tzinfo=timezone.utc)
SENT = "SENTINEL-PURGE-7f3a"


@pytest.fixture
def db(tmp_path):
    clock = {"t": T0}
    dirs = (str(tmp_path / "data" / "pilotdb_backup"), str(tmp_path / "share" / "pilotdb" / "backup"))
    (tmp_path / "data").mkdir()
    d = P.PilotDB(str(tmp_path / "data" / "pilotdb.sqlite"), dirs, lambda: clock["t"])
    d.clock_box, d.dirs = clock, dirs
    yield d
    d.close()


def _hal(emp, sen="812", doh="2001-05-01", status="A"):
    return {"emp": emp, "sen": sen, "sen_month": "2026-07", "doh": doh, "status": status}


# ---------------------------------------------------------------- one pilot listed twice
def test_one_pilot_twice_in_the_contact_list_is_one_record_with_both_phone_cards(db):
    cj = {"uploaded_at": "2026-11-14T09:30:00-10:00", "parser": 2, "pilots": [
        {"emp": "10001", "name": "Doe, Jane", "phones": [{"label": "cell", "number": "808-555-0101"}], "emails": [],
         "hal": _hal("10001")},
        {"emp": "10001", "name": "Doe, Jane", "phones": [{"label": "home", "number": "808-555-0111"}],
         "emails": ["jane.doe@example.com"], "hal": _hal("10001")},
        {"emp": "10002", "name": "Roe, Rich", "phones": [], "emails": ["rich@example.com"], "hal": _hal("10002", "813")}],
        "hal_only": [{"emp": "10001", "name": "Doe, Jane", "hal": _hal("10001")}]}
    r = db.merge_contacts(cj)
    assert r["applied"] and r["added"] == 2 and r["dup"] == 2 and r.get("conflicts", 0) == 0
    rec = db.record(db.find("10001"))
    assert [p["number"] for p in rec["fields"]["phones"]["value"]] == ["808-555-0101", "808-555-0111"]
    assert rec["fields"]["emails"]["value"] == ["jane.doe@example.com"]
    assert db.summary()["live"] == 2


def test_one_pilot_twice_through_the_real_csv_parser(db):
    import contacts as CT
    from datetime import date
    rows = ROWS + [ROWS[1][:6] + ["808-555-0199", "", "10002", ROWS[1][9]]]  # Rick's second card (another phone)
    d = CT.build(CT.parse(_csv(rows), "csv", today=date(2026, 11, 15)), "contacts_2026-11-14.csv",
                 "2026-11-14T09:30:00-10:00")
    assert sum(1 for e in d["pilots"] + d["hal_only"] if (e.get("hal") or {}).get("emp") == "10002") == 2
    r = db.merge_contacts(d)
    assert r["applied"] and r.get("dup") == 1
    assert len([x for x in db.search("roe")["rows"]]) == 1


def test_a_list_whose_also_repeats_the_same_pilot(db):
    lst = {"list_date": "2026-07-01", "pilots": {"10001": {
        "sen": 812, "name": "Doe, Jane", "doh": "2001-05-01", "status": "A",
        "also": [{"sen": 812, "name": "Doe, Jane", "doh": "2001-05-01", "status": "A"}]}}}
    r = db.merge_list(lst)
    assert r["applied"] and (r["added"], r["dup"]) == (1, 1) and db.summary()["live"] == 1
    # the same last name with another first initial on that number: held for Ryan, never a crash
    lst["pilots"]["10001"]["also"] = [{"sen": 900, "name": "Doe, Max", "doh": "2010-01-01", "status": "A"}]
    lst["list_date"] = "2026-08-01"
    r = db.merge_list(lst)
    assert r["applied"] and r["conflicts"] == 1 and [c["kind"] for c in db.conflicts()] == ["ambiguous"]


def test_one_row_the_database_refuses_rolls_back_alone(db, monkeypatch):
    real = db._apply

    def bad(pid, source, values, *a, **k):
        if values.get("name", "").startswith("Roe"):
            raise sqlite3.IntegrityError("synthetic")
        return real(pid, source, values, *a, **k)
    monkeypatch.setattr(db, "_apply", bad)
    r = db.merge_list({"list_date": "2026-07-01", "pilots": {
        "10001": {"sen": 812, "name": "Doe, Jane", "doh": "2001-05-01"},
        "10002": {"sen": 13, "name": "Roe, Rick", "doh": "1985-09-17"}}})
    assert r["applied"] and r["bad"] == 1 and db.find("10001") and db.find("10002") is None


def test_the_watcher_seeds_from_a_contact_list_with_a_pilot_twice(PW, caplog):  # noqa: F811
    rows = ROWS + [ROWS[0][:6] + ["", "", "010001", ROWS[0][9]]]  # Jane again: no phone, no email (hal_only)
    open(os.path.join(PW.UPLOADS_SHARED, "contacts_2026-11-14.csv"), "wb").write(_csv(rows))
    with caplog.at_level(logging.INFO):
        db = PW.pilotdb_start()
    msgs = [r.getMessage() for r in caplog.records if "pilot db" in r.getMessage()]
    assert db.summary()["live"] >= 4 and db.meta("seeded_at") and db.meta("sig:contacts")
    assert (PW.share_dir / "seniority.md").exists()
    assert not any("skipped" in m or "not merged" in m for m in msgs), msgs


def test_a_failed_merge_still_lets_the_rest_of_the_pass_run(PW, caplog, monkeypatch):  # noqa: F811
    db = PW.pilotdb_start()
    md = PW.share_dir / "seniority.md"
    md.unlink()
    os.utime(web.CONTACTS_FILE, (1, 1))  # the contact list's signature moves
    monkeypatch.setattr(db, "merge_contacts", lambda *a, **k: (_ for _ in ()).throw(sqlite3.OperationalError("disk")))
    synced = []
    real = db.sync_pickups
    monkeypatch.setattr(db, "sync_pickups", lambda rows: synced.append(1) or real(rows))
    with caplog.at_level(logging.INFO):
        PW.pilotdb_tick(force=True)
        PW.pilotdb_tick(force=True)  # the same file failing again: logged once
    msgs = [r.getMessage() for r in caplog.records if "pilot db" in r.getMessage()]
    assert msgs.count("pilot db: contacts not merged: OperationalError (tried again on the next pass)") == 1
    assert synced and md.exists()  # the pickups and seniority.md still ran
    sig = db.meta("sig:contacts")
    assert sig != PW._pilotdb_sig([web.CONTACTS_FILE])  # tried again on the next pass


# ---------------------------------------------------------------- the 90% guard
def _roster(n0, n1, date):
    import string

    def nm(i):
        return "Doe" + "".join(string.ascii_uppercase[int(x)] for x in f"{i:03d}").lower() + ", Jane"
    return {"list_date": date, "pilots": {str(10000 + i): {"sen": i, "name": nm(i), "doh": "2001-01-01", "status": "A"}
                                          for i in range(n0, n1)}}


def test_a_second_partial_list_is_measured_against_the_roster(db):
    db.merge_list(_roster(1, 101, "2026-07-01"))
    r = db.merge_list(_roster(1, 51, "2026-08-01"))  # captains only: the guard trips
    assert (r["gone"] if "gone" in r else 0, r["conflicts"]) == (0, 1)
    assert db.summary()["sources"]["list"]["count"] == 100  # a partial list leaves the whole list's count
    r = db.merge_list(_roster(51, 101, "2026-08-01"))  # first officers only: trips again, nobody gone
    assert r.get("gone", 0) == 0 and r["conflicts"] == 1
    assert db.summary()["gone"] == 0
    r = db.merge_list(_roster(1, 96, "2026-09-01"))  # a whole list again (5 retired): they go
    assert r["gone"] == 5 and db.summary()["sources"]["list"]["count"] == 95


def test_a_second_partial_contact_list_drops_nothing(db):
    def cl(n0, n1, day):
        return {"uploaded_at": f"{day}T09:00:00-10:00", "pilots": [
            {"emp": str(10000 + i), "name": f"Doe{chr(65 + i % 26)}{chr(65 + i // 26)}, Jane",
             "phones": [{"label": "mobile", "number": f"808-555-{i:04d}"}], "emails": [],
             "hal": _hal(str(10000 + i), str(i))} for i in range(n0, n1)]}
    db.merge_contacts(cl(1, 41, "2026-11-01"))
    assert db.merge_contacts(cl(1, 21, "2026-11-02")).get("removed", 0) == 0
    assert db.merge_contacts(cl(21, 41, "2026-11-03")).get("removed", 0) == 0
    assert all(db.record(db.find(str(10000 + i)))["fields"]["phones"]["value"] for i in range(1, 41))


# ---------------------------------------------------------------- a hand edit never cuts a record off
def test_a_hand_edit_of_the_name_and_doh_keeps_matching_the_pilots_own_rows(db):
    def L(d, js, rs):
        return {"list_date": d, "pilots": {"10001": {"sen": js, "name": "Doe, Jane", "doh": "2001-05-01", "status": "A"},
                                           "10002": {"sen": rs, "name": "Roe, Rick", "doh": "2001-05-02"}}}
    db.merge_list(L("2026-07-01", 812, 813))
    jane = db.find("10001")
    rec = db.set_field(jane, "name", "Dowe, Jane", db.record(jane)["rev"], "the list misspells it")
    db.set_field(jane, "doh", "2001-05-03", rec["rev"], "the list is a day off")
    for d, sen in (("2026-08-01", 800), ("2026-09-01", 790)):
        r = db.merge_list(L(d, sen, sen + 1))
        assert r.get("conflicts", 0) == 0 and db.conflicts() == []
        f = db.record(jane)["fields"]
        assert f["sen"]["value"] == str(sen) and f["name"]["value"] == "Dowe, Jane" and f["doh"]["value"] == "2001-05-03"
        assert f["name"]["drift"] and f["doh"]["drift"]  # the hand edits stay shown, the upload values keep updating
    # a married name on the next list (same DOH as the list's own): still her
    r = db.merge_list({"list_date": "2026-10-01", "pilots": {
        "10001": {"sen": 780, "name": "Smith, Jane", "doh": "2001-05-01"},
        "10002": {"sen": 781, "name": "Roe, Rick", "doh": "2001-05-02"}}})
    assert r.get("conflicts", 0) == 0 and r["renamed"] == 1 and db.record(jane)["fields"]["sen"]["value"] == "780"


# ---------------------------------------------------------------- Ryan's Attach stays
def test_an_attached_contact_row_goes_to_that_record_on_every_later_list(db):
    db.merge_list({"list_date": "2026-07-01", "pilots": {"10001": {"sen": 812, "name": "Doe, Jane", "doh": "2001-05-01"}}})
    jane = db.find("10001")
    row = {"emp": "77001", "name": "Smith, Jane", "phones": [{"label": "cell", "number": "808-555-0101"}], "emails": []}
    db.merge_contacts({"uploaded_at": "2026-11-14T09:30:00-10:00", "pilots": [row]})
    (c,) = db.conflicts()
    db.resolve(c["id"], "attach", jane)
    row2 = dict(row, phones=[{"label": "cell", "number": "808-555-0102"}])
    r = db.merge_contacts({"uploaded_at": "2026-11-20T09:30:00-10:00", "pilots": [row2]})
    assert (r.get("conflicts", 0), r.get("removed", 0), r["remembered"]) == (0, 0, 1)
    assert [p["number"] for p in db.record(jane)["fields"]["phones"]["value"]] == ["808-555-0102"]
    assert db.conflicts() == []
    # an ignored row stays ignored and removes nothing
    db.merge_contacts({"uploaded_at": "2026-11-21T09:30:00-10:00", "pilots": [
        row2, {"emp": "", "name": "Nobody, Ned", "phones": [{"label": "cell", "number": "808-555-0103"}], "emails": []}]})
    (c,) = db.conflicts()
    db.resolve(c["id"], "ignore")
    r = db.merge_contacts({"uploaded_at": "2026-11-22T09:30:00-10:00", "pilots": [
        row2, {"emp": "", "name": "Nobody, Ned", "phones": [{"label": "cell", "number": "808-555-0103"}], "emails": []}]})
    assert r.get("conflicts", 0) == 0 and r.get("removed", 0) == 0 and db.conflicts() == []
    assert db.record(jane)["fields"]["phones"]["value"]


# ---------------------------------------------------------------- a purge or a forget leaves no text behind
def _blob(paths):
    return b"".join(open(p, "rb").read() for p in paths if os.path.isfile(p))


def _everything(db, tmp_path):
    return [p for p in glob.glob(str(tmp_path / "**" / "*"), recursive=True) if os.path.isfile(p)]


def test_purge_after_a_restore_leaves_the_text_in_no_file(db, tmp_path):
    pid = db.new_record("10001", "Doe, Jane")
    eid = db.add_entry(pid, f"note {SENT}", rid="rid-000001")
    db.backup("2026-11-15")
    db.clock_box["t"] += timedelta(days=1)
    path, dirs, clock = db.path, db.dirs, db.clock
    db.close()
    aside = P.restore(path, dirs, "0/pilotdb-2026-11-15.sqlite", clock)
    assert os.path.exists(aside)
    # a file set aside by the start check too (a damaged one)
    open(path + ".bad-20261101T000000Z", "wb").write(f"damaged {SENT}".encode())
    d2, st = P.open_checked(path, dirs, clock)
    assert [a["kind"] for a in P.aside_files(path)] == ["before-restore", "bad"]
    d2.hide(eid)
    d2.purge(eid=eid)
    d2.replace_backups()
    d2.close()
    assert SENT.encode() not in _blob(_everything(db, tmp_path))
    assert P.aside_files(path) == []


def test_forget_after_a_restore_leaves_the_record_in_no_file(db, tmp_path):
    pid = db.new_record("10001", "Doe, Jane")
    db.save_notes(pid, f"field {SENT}", P.ZERO_REV)
    db.backup("2026-11-15")
    path, dirs, clock = db.path, db.dirs, db.clock
    db.close()
    P.restore(path, dirs, "0/pilotdb-2026-11-15.sqlite", clock)
    d2, _st = P.open_checked(path, dirs, clock)
    d2.forget(pid, "DELETE")
    d2.replace_backups()
    d2.close()
    blob = _blob(_everything(db, tmp_path))
    assert SENT.encode() not in blob and b"Doe, Jane" not in blob


def test_the_files_set_aside_roll_off_after_7_days(db):
    open(db.path + ".before-restore-20261101T000000Z", "wb").write(b"x")
    open(db.path + ".before-restore-20261114T000000Z", "wb").write(b"x")
    db.backup("2026-11-15")
    assert [a["name"] for a in P.aside_files(db.path)] == ["pilotdb.sqlite.before-restore-20261114T000000Z"]


def test_the_status_view_lists_the_files_set_aside(PW):  # noqa: F811
    PW.pilotdb_start()
    open(PW.PILOTDB_FILE + ".before-restore-20261114T000000Z", "wb").write(b"x")
    code, body = PW.pilotdb_get({"view": "status"})
    assert code == 200 and body["aside"] == [{"name": "pilotdb.sqlite.before-restore-20261114T000000Z",
                                              "kind": "before-restore", "at": "2026-11-14T00:00:00+00:00", "size": 1}]


def test_forget_leaves_no_contact_row_in_the_conflicts_table_or_the_copies(db, tmp_path):
    pid = db.new_record("10001", "Doe, Jane")
    db.merge_contacts({"uploaded_at": "2026-11-14T08:00:00-10:00", "pilots": [
        {"emp": "", "name": "Doe, Janet", "phones": [{"label": "mobile", "number": "808-555-0177"}],
         "emails": ["janet.doe@example.com"]}]})
    (c,) = db.conflicts()
    db.resolve(c["id"], "attach", pid)
    # and one still open about her (her number and last name), never answered
    db.merge_contacts({"uploaded_at": "2026-11-15T08:00:00-10:00", "pilots": [
        {"emp": "", "name": "Doe, Janet", "phones": [{"label": "mobile", "number": "808-555-0177"}],
         "emails": ["janet.doe@example.com"]},
        {"emp": "10001", "name": "Doe, Jen", "phones": [{"label": "mobile", "number": "808-555-0178"}],
         "emails": ["jen.doe@example.com"], "hal": {}}]}, "james")
    db.forget(pid, "DELETE")
    db.replace_backups()
    db.close()
    blob = _blob(_everything(db, tmp_path))
    for s in (b"janet.doe@example.com", b"808-555-0177", b"jen.doe@example.com", b"808-555-0178", b"Doe, Jan"):
        assert s not in blob, s


# ---------------------------------------------------------------- pickups
def test_a_merged_records_pickups_stay_on_the_record_it_went_into(db):
    db.merge_list({"list_date": "2026-07-01", "pilots": {"10010": {"sen": 812, "name": "Doe, Jane", "doh": "2001-05-01"}}})
    b = db.find("10010")
    a = db.new_record("10001", "Doe, Jane", "2001-05-01")
    rows = [{"key": "H3601|20Nov", "emp": "10010", "name": "Doe, Jane", "pos": "FO", "at": "2026-11-14T20:00:00+00:00",
             "lay": "LAX", "days": 3}]
    db.sync_pickups(rows)
    db.merge_records(b, a)
    assert db.pickups(a)["summary"]["n"] == 1
    db.sync_pickups(rows)  # the next minute's pass
    assert db.pickups(a)["summary"]["n"] == 1


def test_a_turn_is_no_layover_station(tmp_path):
    s = Store(str(tmp_path / "s.db"))
    for key, row, gone in (("H1001|01Nov", {"pairing": "H1001", "open_seats": "FO", "layover": "", "turn": "OGG",
                                             "days": 1}, "2026-11-01T20:00:00+00:00"),
                           ("H1002|05Nov", {"pairing": "H1002", "open_seats": "FO", "layover": "OGG", "days": 2},
                            "2026-11-05T20:00:00+00:00")):
        s.add_find(key, "2026-11", row, gone, gone=gone)
        s.db.execute("UPDATE finds SET last_seen=? WHERE key=?", (gone, key))
        s.set_pickup(key, {"status": "filled", "by": f"FO {PAT}", "ca": "", "known": True})
        s.score_pickup(key)
    h = P.pickup_history(sorted(s.pickup_history(), key=lambda r: r["at"]))
    sm = h["summary"]
    assert (sm["lays"], sm["turn_stations"], sm["layovers"], sm["turns"]) == ([["OGG", 1]], [["OGG", 1]], 1, 1)
    assert [(r["pairing"], r["lay"], r["n_lay"], r["station"]) for r in h["rows"]] == [
        ("H1002", "OGG", 1, "OGG"), ("H1001", "", 0, "OGG")]


# ---------------------------------------------------------------- the notes field and the log
def test_a_notes_rev_never_comes_back(db):
    pid = db.new_record("10001", "Doe, Jane")
    a = db.save_notes(pid, "X", P.ZERO_REV)
    b = db.save_notes(pid, "Y", a["rev"])
    c = db.save_notes(pid, "X", b["rev"])  # the same second, the same text and author as the first
    assert c["rev"] != a["rev"]
    with pytest.raises(P.Stale):
        db.save_notes(pid, "a stale tab's text", a["rev"])
    assert db.record(pid)["notes"]["text"] == "X"


def test_entries_in_the_same_second_stay_newest_first(db):
    pid = db.new_record("10001", "Doe, Jane")
    for i in range(20):
        db.add_entry(pid, f"entry {i}", rid=f"rid-{i:06d}")
        assert db.record(pid)["entries"][0]["text"] == f"entry {i}"
    assert [e["text"] for e in db.record(pid)["entries"]] == [f"entry {i}" for i in range(19, -1, -1)]
    md = db.render_md()
    assert md.index("entry 19") < md.index("entry 18") < md.index("entry 0")


def test_unset_of_a_name_no_upload_has_is_refused(db):
    pid = db.new_record("10001", "Doe, Jane")
    with pytest.raises(P.Bad) as e:
        db.unset_field(pid, "name", db.record(pid)["rev"])
    assert e.value.field == "name" and db.record(pid)["fields"]["name"]["value"] == "Doe, Jane"


# ---------------------------------------------------------------- the uploader
def test_a_pilots_uploaded_contact_list_is_his_and_merges_like_ryans(PW):  # noqa: F811
    """1.7.10 (Ryan's decision 4 of Nov 15): a contact list a pilot's instance saved merges into the one database like
    Ryan's own, with that pilot as the author (1.7.8 held a row that matched no record for Ryan)."""
    db = PW.pilotdb_start()
    row = ["Zoe", "", "Zed", "", "Example Air", "First Officer", "808-555-0109", "zoe.zed@example.com", "10099",
           "HAL Emp# 10099 | Sen# 990 (Jul 2026) | DOH 2-Feb-22 | Status A"]
    jane = ROWS[0][:6] + ["808-555-0121", "", "10001", ROWS[0][9]]
    r = web.save_upload({"kind": "contacts", "month": ""}, _csv([row, jane]), logging.getLogger("t"), who="james")
    assert r["ok"] and json.load(open(web.CONTACTS_FILE))["uploaded_by"] == "james"
    PW.pilotdb_tick()
    zoe = db.find("10099")  # a row with a HAL Emp# makes a record, as on Ryan's own list, and it is the pilot's
    assert zoe and [x["by"] for x in db.record(zoe)["field_log"] if x["how"] == "created"] == ["james"]
    assert {v["by"] for v in db._vals(zoe, "name")} == {"james"}
    assert not [c for c in db.conflicts() if c["kind"] == "contact_unmatched" and c["emp"] == "10099"]
    # Ryan's hand edit stays on top of a pilot's upload, and the upload's value is kept beside it
    db.set_field(zoe, "status", "LOA", db.record(zoe)["rev"], "He told me")
    web.save_upload({"kind": "contacts", "month": ""}, _csv([row, jane]), logging.getLogger("t"), who="james")
    PW.pilotdb_tick(force=True)
    f = db.record(zoe)["fields"]["status"]
    assert (f["value"], f["hand"], f["by"]) == ("LOA", True, "ryan")
    rec = db.record(db.find("10001"))  # a row that matches a record updates it, as the pilot's
    # 1.7.10 review: the value he added a number to keeps its author (Ryan's list); the history names james for it
    ph = [v for v in db._vals(rec["pid"], "phones") if v["source"] == "contacts"]
    assert {v["by"] for v in ph} == {"ryan"} and "808-555-0121" in ph[0]["value"]
    assert [x["by"] for x in rec["field_log"] if x["field"] == "phones" and "0121" in str(x["new"])] == ["james"]
    with db.lock:
        by = db.db.execute("SELECT by FROM merges WHERE source='contacts' ORDER BY id DESC LIMIT 1").fetchone()[0]
    assert by == "james" and "(uploaded by james," in db.render_md()
    # Ryan's own list (the ingress card's upload) is his
    r = web.save_upload({"kind": "contacts", "month": ""}, _csv([row]), logging.getLogger("t"))
    assert json.load(open(web.CONTACTS_FILE))["uploaded_by"] == "ryan"


def test_a_seniority_list_keeps_its_uploader(tmp_path, monkeypatch):
    monkeypatch.setattr(web, "SENIORITY_MD_HOOK", lambda: None)
    out = str(tmp_path / "seniority.json")
    d = web.seniority_store({"rows": [], "list_date": "2026-07-01", "rejects": []}, "seniority_2026-11-15.pdf",
                            "2026-11-15T09:00:00-10:00", "2026-07-01", out, who="james")
    assert d["uploaded_by"] == "james"
    lst, _aw = web.seniority_sources(out)
    assert lst["uploaded_by"] == "james"


# ---------------------------------------------------------------- the in-flight re-check
def test_the_recheck_reaches_a_dropped_verdict_older_than_the_newest_50(tmp_path, monkeypatch):
    db = Store(str(tmp_path / "s.db"))
    _done(db)
    _find(db, "H8001|01Oct", f"FO {JANE}; RO {RICK}", "2026-10-01T20:30:00+00:00", "FO")
    _old_style(db, "H8001|01Oct", f"FO {JANE}; RO {RICK}", 120)
    db.set_inflt("H8001|01Oct", True, "H3648 2026-10-01", tries=1)
    for i in range(50):
        k = f"H9{i:03d}|X"
        _find(db, k, f"FO {PAT}", f"2026-11-{1 + i % 28:02d}T{10 + i % 10}:00:00+00:00", "FO",
              first=f"2026-11-{1 + i % 28:02d}T0{i % 10}:{i % 60:02d}:00+00:00")
        db.set_inflt(k, False, "", tries=1, emp="10003")
    # a dropped verdict on a pickup with no known picker: it keeps its dropped state (nothing could look it up)
    _find(db, "H8002|02Oct", "FO Nobody, Ned", "2026-10-02T20:30:00+00:00", "FO")
    db.rebuild_pickers()
    with db.lock:
        pk = _pk(db, "H8002|02Oct")
        pk.update(inflt=True, inflt_skip=True)
        db.db.execute("UPDATE finds SET pickup=? WHERE key=?", (json.dumps(pk), "H8002|02Oct"))
    assert _pk(db, "H8001|01Oct")["inflt_skip"] is True
    fl = _Fl()
    _run(db, fl, monkeypatch)
    pk = _pk(db, "H8001|01Oct")
    assert (pk["inflt"], pk["inflt_emp"], "inflt_recheck" in pk) == (False, "10001", False)
    assert any("EmployeeID=10001" in u for u in fl.urls)
    assert _pk(db, "H8002|02Oct")["inflt_skip"] is True


def test_the_in_flight_log_names_the_picker_by_seat_never_his_number(tmp_path, monkeypatch, caplog):
    db = Store(str(tmp_path / "s.db"))
    _done(db)
    db.put("inflt_skip_recheck_v", inflt.RECHECK_SKIP_V)
    _find(db, "H9002|21Nov", f"FO {PAT}; RO {MAX}", "2026-11-03T20:30:00+00:00", "FO,RO",
          pickup={"pickers": ["10003", "10004"]})
    db.score_pickup("H9002|21Nov")
    with caplog.at_level(logging.INFO):
        _run(db, _Fl(air={"10004"}), monkeypatch)
    lines = [r.getMessage() for r in caplog.records if r.levelno >= logging.INFO]
    assert any("picker 2 IN FLIGHT" in m for m in lines) and any("picker 1 not in flight" in m for m in lines), lines
    assert not any("10003" in m or "10004" in m for m in lines), lines
