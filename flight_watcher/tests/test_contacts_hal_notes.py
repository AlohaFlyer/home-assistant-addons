"""1.7.8 (pilot database, spec section 8.4; Ryan, Nov 14: "import the kept contact CSV ... its Notes: HAL Emp#, Sen#,
DOH, Status, Age 65 retirement"): the contact list's Notes column is read for the HAL employee number, the seniority
number and its month, the date of hire, the status code and the age 65 retirement month (14 CFR 121.383(d)). Only the
parsed values are kept, in the entry's `hal` object; the raw Notes text never is. contacts.PARSER 2; contacts.json
stays mode 600 and every log line carries counts only. Synthetic data only: made-up names ("Doe, Jane"), employee
numbers 10001 to 10099, 808-555-01xx numbers and example.com addresses."""
import json
import logging
import os
import stat
from datetime import date, datetime, timedelta, timezone

import contacts as CT
import web

TODAY = date(2026, 11, 15)
HST = timezone(timedelta(hours=-10))
NOTE = "HAL Emp# 10001 | Sen# 812 (Jul 2026) | DOH 1-May-01 | Status SLOA | Age 65 retirement Mar 2041"
HEAD = "First Name,Middle Name,Last Name,Suffix,Company,Job Title,Mobile Phone,Email,Employee ID,Notes\r\n"


def _csv(rows):
    return (HEAD + "".join(",".join(f'"{c}"' if ("," in c or "|" in c) else c for c in r) + "\r\n"
                           for r in rows)).encode()


ROWS = [
    ["Jane", "A", "Doe", "", "Example Air", "First Officer", "808-555-0101", "jane.doe@example.com", "010001",
     "HAL Emp# 10001 | Sen# 812 (Jul 2026) | DOH 1-May-01 | Status SLOA | Age-65 retirement Mar 2041"],
    ["Rick", "", "Roe", "Jr", "Example Air", "Captain", "808-555-0102", "rick.roe@example.com", "10002",
     "HAL Emp# 10002 | Sen# 13 (Jul 2026) | DOH 17-Sep-85 | Status A"],
    # no phone and no email: not a contact, but his Notes still carry the HAL data (hal_only)
    ["Pat", "", "Poe", "", "Example Air", "First Officer", "", "", "10003",
     "HAL Emp# 10003 | Sen# 900 (Jul 2026) | DOH 3-Mar-19 | Status MLOA | Age 65 retirement Jan 2050"],
    # the union's own number in the Employee ID column: kept as union_id, the HAL number from the Notes is the emp
    ["Max", "", "Moe", "", "Example Air", "First Officer", "808-555-0104", "", "77001",
     "HAL Emp# 10004 | Sen# 950 (Jul 2026) | DOH 9-Dec-20 | Status A | Favorite color blue"],
    # no Notes at all: a plain contact
    ["Kim", "", "Lee", "", "", "", "808-555-0105", "", "10005", ""],
]


def test_hal_notes_reads_every_segment():
    hal, rej = CT.hal_notes(NOTE, TODAY)
    assert hal == {"emp": "10001", "sen": "812", "sen_month": "2026-07", "doh": "2001-05-01", "status": "SLOA",
                   "retire": "2041-03"}
    assert rej == {}
    # the hyphen form seen on the real list ("Age-65 retirement") reads the same
    assert CT.hal_notes("HAL Emp# 10001 | Age-65 retirement Mar 2041", TODAY)[0]["retire"] == "2041-03"
    # leading zeros go; a list with no retirement segment (4 segments) is fine
    hal, rej = CT.hal_notes("HAL Emp# 0010009 | Sen# 1 (Jul 2026) | DOH 17-Sep-85 | Status A", TODAY)
    assert (hal["emp"], hal["doh"], "retire" in hal, rej) == ("10009", "1985-09-17", False, {})


def test_two_digit_years_take_the_century_from_today():
    # yy at most the current yy is 20yy, else 19yy (spec 8.4.2)
    assert CT.hal_notes("DOH 1-Jan-26", TODAY)[0]["doh"] == "2026-01-01"
    assert CT.hal_notes("DOH 1-Jan-27", TODAY)[0]["doh"] == "1927-01-01"
    assert CT.hal_notes("DOH 31-Dec-99", TODAY)[0]["doh"] == "1999-12-31"


def test_a_future_doh_an_unknown_status_and_unknown_segments_are_dropped_and_counted():
    hal, rej = CT.hal_notes("HAL Emp# 10001 | DOH 20-Dec-26 | Status ZZZ | Favorite color blue | Sen# 5 (Foo 2026)",
                            TODAY)
    assert hal == {"emp": "10001"}
    assert rej == {"notes-doh-future": 1, "notes-status-unknown": 1, "notes-unknown": 2}
    hal, rej = CT.hal_notes("DOH 31-Feb-01 | HAL Emp# 12345678 | " + "x" * 300, TODAY)
    assert hal == {} and rej == {"notes-bad-date": 1, "notes-unknown": 2}
    assert CT.hal_notes("", TODAY) == ({}, {}) and CT.hal_notes(None, TODAY) == ({}, {})
    # a second segment of the same kind is counted, the first kept
    hal, rej = CT.hal_notes("HAL Emp# 10001 | HAL Emp# 10002", TODAY)
    assert hal == {"emp": "10001"} and rej == {"notes-dup": 1}


def test_header_roles_notes_middle_and_suffix():
    assert CT._role("Notes") == ("notes", "") and CT._role("Middle Name") == ("middle", "")
    assert CT._role("Suffix") == ("suffix", "")
    # unchanged
    assert CT._role("Last Name") == ("last", "") and CT._role("First Name") == ("first", "")
    assert CT._role("Employee ID") == ("emp", "") and CT._role("Mobile Phone") == ("phone", "cell")


def test_a_csv_with_notes_gives_hal_objects_and_hal_only_entries():
    r = CT.parse(_csv(ROWS), "csv", today=TODAY)
    by = {e["emp"]: e for e in r["entries"]}
    assert sorted(by) == ["010001", "10002", "10005", "77001"]
    assert by["010001"]["hal"] == {"emp": "10001", "sen": "812", "sen_month": "2026-07", "doh": "2001-05-01",
                                   "status": "SLOA", "retire": "2041-03"}
    assert by["010001"]["name"] == "Doe, Jane" and by["010001"]["name_full"] == "Doe, Jane A"
    assert by["10002"]["name"] == "Roe, Rick" and by["10002"]["name_full"] == "Roe, Rick Jr"
    assert by["77001"]["hal"]["emp"] == "10004" and "hal" not in by["10005"] and "name_full" not in by["10005"]
    assert [(e["emp"], e["name"], e["hal"]["emp"]) for e in r["hal_only"]] == [("10003", "Poe, Pat", "10003")]
    assert r["skipped"] == 1 and r["hal_rejects"] == {"notes-unknown": 1}
    for e in r["entries"] + r["hal_only"]:
        assert "notes" not in e and not any("|" in str(v) for v in e.values()), e  # the raw Notes never kept


def test_contacts_json_parser_2_mode_600_counts_only(tmp_path, monkeypatch, caplog):
    up = tmp_path / "uploads"
    up.mkdir()
    monkeypatch.setattr(web, "UPLOAD_DIR", str(up))
    monkeypatch.setattr(web, "CONTACTS_FILE", str(tmp_path / "contacts.json"))
    monkeypatch.setattr(web, "LOCK_PATH", str(tmp_path / "lock"))
    monkeypatch.setattr(web, "_hst_now", lambda: datetime(2026, 11, 14, 9, 30, tzinfo=HST))
    with caplog.at_level(logging.INFO):
        r = web.save_upload({"kind": "contacts", "month": ""}, _csv(ROWS), logging.getLogger("t"))
    assert r["ok"], r
    cf = tmp_path / "contacts.json"
    assert stat.S_IMODE(os.stat(cf).st_mode) == 0o600
    d = json.loads(cf.read_text())
    assert (d["parser"], CT.PARSER, d["count"], d["skipped"], d["with_hal"]) == (2, 2, 4, 1, 4)
    assert d["hal_rejects"] == {"notes-unknown": 1} and len(d["hal_only"]) == 1
    raw = cf.read_text()
    assert "HAL Emp#" not in raw and "Favorite" not in raw and "retirement" not in raw
    # the pilot card's lookup still answers only name, phones and emails
    assert CT.find(d, "10001") is None or set(CT.find(d, "10001")) == {"name", "phones", "emails"}
    assert set(CT.find(d, "010001")) == {"name", "phones", "emails"}
    for s in ("Doe", "Jane", "10001", "555-01", "example.com", "SLOA", "2041"):
        assert s not in caplog.text, s


def test_reparse_of_the_kept_source_once(tmp_path, monkeypatch, caplog):
    """Spec 8.4.4: a contacts.json written by parser 1 (no hal) is read again from the kept 0600 source once; with no
    source kept the answer says to upload the list again."""
    up = tmp_path / "uploads"
    up.mkdir()
    monkeypatch.setattr(web, "UPLOAD_DIR", str(up))
    cf = tmp_path / "contacts.json"
    monkeypatch.setattr(web, "CONTACTS_FILE", str(cf))
    monkeypatch.setattr(web, "LOCK_PATH", str(tmp_path / "lock"))
    log = logging.getLogger("t")
    assert web.contacts_reparse(log, TODAY) == "no-list"
    CT.store(str(cf), {"v": 1, "parser": 1, "file": "contacts_2026-11-14.csv", "uploaded_at": "2026-11-14T09:30:00-10:00",
                       "count": 0, "pilots": []})
    assert web.contacts_reparse(log, TODAY) == "no-source"
    src = up / "contacts_2026-11-14.csv"
    src.write_bytes(_csv(ROWS))
    os.chmod(src, 0o600)
    with caplog.at_level(logging.INFO):
        assert web.contacts_reparse(log, TODAY) == "reparsed"
    d = json.loads(cf.read_text())
    assert (d["parser"], d["count"], d["with_hal"], d["file"], d["uploaded_at"]) == (
        2, 4, 4, "contacts_2026-11-14.csv", "2026-11-14T09:30:00-10:00")
    assert stat.S_IMODE(os.stat(cf).st_mode) == 0o600
    assert web.contacts_reparse(log, TODAY) == "current"  # once
    assert "Doe" not in caplog.text and "10001" not in caplog.text
