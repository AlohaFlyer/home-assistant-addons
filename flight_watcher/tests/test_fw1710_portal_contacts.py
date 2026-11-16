"""1.7.10, contract 1 revision 5 (Ryan, Nov 16: "His uploads should update the shared database too", and the
contacts list upload on a pilot's portal "Now, in 1.7.10"): a portal pilot uploads the airline contacts list (the CSV
export, header "First Name, Middle Name, Last Name, Suffix, Company, Job Title, Mobile Phone, Email, Employee ID,
Notes") through upload/pdf with kind contacts. His Watcher puts the parts together and checks the whole file (size,
sha256, text, the header row, the 1.4.8 parser), then hands it to the admin's Watcher through his inbox folder under
/share (0600, the author from the folder's name). The admin's Watcher runs the same checks again and merges it into
the ONE database with that pilot as the author. A pilot's list only adds and updates: nobody is marked gone, nothing
is deleted, no phone or email is removed, and Ryan's hand edits stay on top.
Synthetic rows only ("Doe, Jane", 10001, 808-555-01xx, example.com)."""
import base64
import hashlib
import json
import logging
import math
import os
import stat
from datetime import datetime, timedelta, timezone

import pytest

import contacts as CT
import pdbshare as PS
import pilotdb as P
import pilotpdf as PP
import portal as PT
import roles
from test_pilotdb_store import CONTACTS, LIST

T0 = datetime(2026, 11, 16, 20, 0, tzinfo=timezone.utc)
NOW = datetime(2026, 11, 16, 10, 0)  # HST, as local_now() gives it
LIM = roles.PILOT_UPLOAD_LIMITS
HEAD = "First Name,Middle Name,Last Name,Suffix,Company,Job Title,Mobile Phone,Email,Employee ID,Notes\r\n"
UID = "uDemoContacts0000001"
SECRETS = ("Doe", "Jane", "Roe", "Poe", "Moe", "10001", "10002", "10003", "10004", "555-01", "example.com")
# Jane: a second phone and no email (her email on file must stay); Rick: an email and no phone; Pat and Max: new
ROWS = [
    ["Jane", "A", "Doe", "", "Example Air", "First Officer", "808-555-0111", "", "010001",
     "HAL Emp# 10001 | Sen# 812 (Jul 2026) | DOH 1-May-01 | Status SLOA | Age-65 retirement Mar 2041"],
    ["Rick", "", "Roe", "", "Example Air", "Captain", "", "rick.roe@example.com", "10002",
     "HAL Emp# 10002 | Sen# 13 (Jul 2026) | DOH 17-Sep-85 | Status A"],
    ["Pat", "", "Poe", "", "Example Air", "First Officer", "", "", "10003",
     "HAL Emp# 10003 | Sen# 900 (Jul 2026) | DOH 3-Mar-19 | Status MLOA | Age 65 retirement Jan 2050"],
    ["Max", "", "Moe", "", "Example Air", "First Officer", "808-555-0104", "max.moe@example.com", "77001",
     "HAL Emp# 10004 | Sen# 950 (Jul 2026) | DOH 9-Dec-20 | Status A"],
]


def _csv(rows=ROWS, head=HEAD):
    return (head + "".join(",".join(f'"{c}"' if ("," in c or "|" in c) else c for c in r) + "\r\n"
                           for r in rows)).encode()


def _cj(rows=ROWS, day="2026-11-16"):
    d = CT.build(CT.parse(_csv(rows), "csv", today=T0.date()), "contacts.csv", f"{day}T10:00:00-10:00")
    return d


def _db(tmp_path, name="p.sqlite"):
    clock = {"t": T0}
    db = P.PilotDB(str(tmp_path / name), clock=lambda: clock["t"])
    db.clock_box = clock
    db.merge_list(LIST)
    db.merge_contacts(CONTACTS)  # Ryan's list of Nov 14: Jane, 808-555-0101, jane.doe@example.com
    return db


def _f(db, emp, field):
    return db.record(db.find(emp))["fields"][field]


# ---------------------------------------------------------------- the contract: revision 5
def test_revision_5_takes_kind_contacts_on_upload_pdf():
    assert roles.CONTRACT_REVISION == 5
    cl = roles.PILOT_CONTACTS_LIMITS
    assert cl["kind"] == "contacts" and cl["file_bytes"] == 1024 * 1024
    assert cl["header"] == ["First Name", "Middle Name", "Last Name", "Suffix", "Company", "Job Title",
                            "Mobile Phone", "Email", "Employee ID", "Notes"]
    assert cl["chunk_parts"] == math.ceil(math.ceil(cl["file_bytes"] / 3) * 4 / LIM["chunk_chars"])
    # the PDF kinds are as they were; contacts is a third value of the command's kind, from revision 5 on
    assert LIM["kinds"] == ["pairings", "award"] and PP.KINDS == ("pairings", "award")
    assert roles.SHAPE_CMDS["upload/pdf"]["fields"]["kind"]["values"] == ["pairings", "award", "contacts"]
    assert roles.COMMAND_SINCE["upload/pdf"] == 3 and roles.VALUE_SINCE == {"upload/pdf": {"kind": {"contacts": 5}}}
    raw = _csv()
    up = {"uid": UID, "kind": "contacts", "month": "2026-11", "size": len(raw), "sha": hashlib.sha256(raw).hexdigest(),
          "part": 1, "parts": 1, "data": base64.b64encode(raw).decode()}
    assert PT.check_shape("upload/pdf", json.dumps(up))["kind"] == "contacts"
    for bad in ("seniority", "contact", "CONTACTS"):
        with pytest.raises(PT.PortalError):
            PT.check_shape("upload/pdf", json.dumps({**up, "kind": bad}))
    # no upload ever names its author or a pilot
    with pytest.raises(PT.PortalError):
        PT.check_shape("upload/pdf", json.dumps({**up, "by": "ryan"}))


def test_the_fixture_says_revision_5_and_what_hom_checks():
    fx = PT.contract()
    cm = fx["commands"]
    assert fx["revision"] == 5
    assert cm["value_since_revision"] == {"upload/pdf": {"kind": {"contacts": 5}}}
    assert cm["pilot_contacts_limits"] == roles.PILOT_CONTACTS_LIMITS
    assert cm["pilot_contacts_checks"] == list(PT.CONTACTS_CHECKS) and len(cm["pilot_contacts_checks"]) >= 8
    assert cm["since_revision"]["upload/pdf"] == 3  # the command itself is revision 3's
    assert fx["revisions"]["5"].startswith("Flight Watcher 1.7.10, HOM 1.9.1")
    assert "HOM 1.9.0" in fx["revisions"]["5"]  # what an older portal does with it is said
    acc = [json.loads(c["cmd"]["payload"]) for c in fx["samples"]["commands"]["accepted"]
           if c["cmd"]["sub"] == "upload/pdf"]
    one = next(p for p in acc if p["kind"] == "contacts")
    assert PS.contacts_check(base64.b64decode(one["data"]))["entries"]  # the sample is a list both Watchers take
    assert any(p["kind"] == "contacts" for p in acc)
    ref = [c["why"] for c in fx["samples"]["commands"]["refused"]]
    assert "upload kind contacts" not in ref and "upload kind seniority" in ref
    man = json.loads(next(e["envelope"] for e in fx["samples"]["envelopes"]
                          if e["file"] == "manifest.json")["payload"])
    assert man["revision"] == 5
    # the inbox hand-off of the list is described, with its own size
    ib = fx["pilotdb"]["inbox"]
    assert ib["contacts_max_bytes"] == roles.PILOT_CONTACTS_LIMITS["inbox_bytes"] > ib["max_bytes"]
    assert ib["contacts_body"] == ["v", "by", "at", "cmd", "rid", "size", "sha", "data"]
    for a in ("Contacts merged: <n> rows read, <n> pilots added, <n> updated, <n> held for Ryan",
              "Not merged: that file is not the contacts list (CSV) export",
              "Not merged: no pilot was read from that contacts list",
              "Not merged: over <n> contacts lists in 24 h"):
        assert a in cm["pilotdb_answers"]


# ---------------------------------------------------------------- the checks both Watchers run
def test_contacts_check_takes_the_export_and_nothing_else():
    got = PS.contacts_check(_csv())
    assert len(got["entries"]) == 3 and len(got["hal_only"]) == 1  # Pat has neither a phone nor an email
    assert PS.contacts_check(b"\xef\xbb\xbf" + _csv())["entries"]  # a UTF-8 BOM is fine
    lower = HEAD.lower().replace(",", " , ")
    assert PS.contacts_check(_csv(head=lower))["entries"]  # the header's case and spaces do not matter
    bad = {
        "a pdf": b"%PDF-1.4\n" + _csv(),
        "a zip": b"PK\x03\x04" + _csv(),
        "a NUL": _csv() + b"\x00",
        "an escape": _csv().replace(b"Example Air", b"Example\x1bAir", 1),
        "not utf-8": _csv().replace(b"Jane", b"J\xe4ne", 1),
        "another header": _csv(head="Name,Phone,Email\r\n"),
        "one column short": _csv(head=HEAD.replace(",Notes", "")),
        "a column more": _csv(head=HEAD.replace("\r\n", ",Home Phone\r\n")),
        "no header": _csv(head=""),
        "empty": b"",
    }
    for name, raw in bad.items():
        with pytest.raises(PS.ContactsRefused) as e:
            PS.contacts_check(raw)
        assert str(e.value) == PS.CONTACTS_BAD, name
    with pytest.raises(PS.ContactsRefused) as e:
        PS.contacts_check(_csv(rows=[]))
    assert str(e.value) == PS.CONTACTS_EMPTY
    big = _csv() + b"x" * (roles.PILOT_CONTACTS_LIMITS["file_bytes"] + 1 - len(_csv()))
    with pytest.raises(PS.ContactsRefused) as e:
        PS.contacts_check(big)
    assert str(e.value) == "Not merged: a contacts list is at most 1024 KB"
    # a refusal never repeats a byte of the file
    for s in SECRETS:
        assert s not in PS.CONTACTS_BAD + PS.CONTACTS_EMPTY


def test_the_assembler_caps_a_contacts_list_at_1_mib():
    cl = roles.PILOT_CONTACTS_LIMITS
    assert PP.parts_for(cl["file_bytes"]) == cl["chunk_parts"]
    a = PP.Assembler()
    size = cl["file_bytes"] + 1
    d = {"uid": UID, "kind": "contacts", "month": "2026-11", "size": size, "sha": "a" * 64, "part": 1,
         "parts": PP.parts_for(size), "data": "A" * 60000}
    with pytest.raises(PP.Refused) as e:
        a.add(d)
    assert "1024 KB" in str(e.value)
    raw = _csv()
    b = base64.b64encode(raw).decode()
    meta, got = PP.Assembler().add({"uid": UID, "kind": "contacts", "month": "2026-11", "size": len(raw),
                                    "sha": hashlib.sha256(raw).hexdigest(), "part": 1, "parts": 1, "data": b})
    assert got == raw and meta["kind"] == "contacts"


# ---------------------------------------------------------------- the merge: adds and updates only
def test_a_pilots_list_adds_and_updates_with_him_as_the_author(tmp_path):
    db = _db(tmp_path)
    jane, rick = db.find("10001"), db.find("10002")
    before = db.summary()
    r = db.merge_contacts(_cj(), by="james", sha="ab" * 32, parser=CT.PARSER)
    assert r["applied"] and r["added"] == 2 and r.get("gone", 0) == 0 and r.get("removed", 0) == 0
    # two new records, made by james
    for emp, name in (("10003", "Poe, Pat"), ("10004", "Moe, Max")):
        pid = db.find(emp)
        assert pid and db.record(pid)["fields"]["name"]["value"] == name
        assert db.db.execute("SELECT created_by FROM pilots WHERE pid=?", (pid,)).fetchone()[0].startswith("pilot contacts")
        assert {b for (b,) in db.db.execute("SELECT by FROM vals WHERE pid=?", (pid,))} == {"james"}
    assert _f(db, "10004", "union_id")["value"] == "77001"
    assert [p["number"] for p in _f(db, "10004", "phones")["value"]] == ["808-555-0104"]
    # Jane: her phone from Ryan's list stays FIRST and the pilot's is added; her email stays though his row has none
    ph = _f(db, "10001", "phones")
    assert [p["number"] for p in ph["value"]] == ["808-555-0101", "808-555-0111"] and ph["by"] == "james"
    em = _f(db, "10001", "emails")
    assert em["value"] == ["jane.doe@example.com"] and em["by"] == "ryan"
    # Rick had no contact values: his email is added, by james; his list values are untouched
    assert _f(db, "10002", "emails")["value"] == ["rick.roe@example.com"]
    assert (_f(db, "10002", "sen")["value"], _f(db, "10002", "sen")["source"]) == ("13", "list")
    # every change is in the field log with the value before it and its author, so Ryan can put it back
    log = db.db.execute("SELECT old,new,by,source FROM field_log WHERE pid=? AND field='phones' ORDER BY id DESC",
                        (jane,)).fetchone()
    assert "0101" in log[0] and "0111" in log[1] and log[2:] == ("james", "contacts")
    # nobody gone, no record less, and Ryan's list stays the one the dates and the partial guard are measured by
    after = db.summary()
    assert after["gone"] == before["gone"] == 0 and after["records"] == before["records"] + 2
    assert db.meta("contacts_as_of") == "2026-11-14" and db.meta("contacts_count") == "1"
    m = db.db.execute("SELECT source,ref,by,sha256,added FROM merges ORDER BY id DESC").fetchone()
    assert m == ("contacts", "pilot contacts 2026-11-16", "james", "ab" * 32, 2)
    assert rick and db.conflicts() == []
    db.close()


def test_a_pilots_list_never_removes_and_never_marks_gone(tmp_path):
    db = _db(tmp_path)
    jane = db.find("10001")
    # a list of his that holds only Rick, with nothing but a name: Jane is not in it at all
    only_rick = [["Rick", "", "Roe", "", "", "", "808-555-0102", "", "10002", "HAL Emp# 10002"]]
    r = db.merge_contacts(_cj(only_rick), by="james")
    assert r["applied"] and r.get("removed", 0) == 0 and r.get("gone", 0) == 0 and r.get("conflicts", 0) == 0
    assert [p["number"] for p in _f(db, "10001", "phones")["value"]] == ["808-555-0101"]
    assert _f(db, "10001", "emails")["value"] == ["jane.doe@example.com"]
    assert _f(db, "10001", "retire")["value"] == "2041-03"  # the contacts value of Ryan's list
    assert db.record(jane)["gone"] is False and db.conflicts() == []
    # a row of his with empty cells drops nothing either
    bare = [["Jane", "", "Doe", "", "", "", "808-555-0101", "", "10001", "HAL Emp# 10001"]]
    db.clock_box["t"] = T0 + timedelta(days=1)
    db.merge_contacts(_cj(bare, "2026-11-17"), by="james")
    assert _f(db, "10001", "emails")["value"] == ["jane.doe@example.com"]
    assert _f(db, "10001", "retire")["value"] == "2041-03" and _f(db, "10001", "sen")["value"] == "812"
    assert not db.db.execute("SELECT 1 FROM field_log WHERE new IS NULL AND by='james'").fetchone()
    db.close()


def test_phones_and_emails_are_capped_and_a_full_list_is_left_alone(tmp_path):
    db = _db(tmp_path)
    jane = db.find("10001")
    for i, day in ((2, "2026-11-16"), (3, "2026-11-17"), (4, "2026-11-18"), (5, "2026-11-19")):
        db.clock_box["t"] = datetime.fromisoformat(day + "T20:00:00+00:00")
        row = [["Jane", "A", "Doe", "", "", "", f"808-555-011{i}", f"jane{i}@example.com", "10001", "HAL Emp# 10001"]]
        db.merge_contacts(_cj(row, day), by="james")
    ph = [p["number"] for p in _f(db, "10001", "phones")["value"]]
    em = _f(db, "10001", "emails")["value"]
    assert ph == ["808-555-0101", "808-555-0112", "808-555-0113", "808-555-0114"]  # 4 at most, Ryan's first
    assert em == ["jane.doe@example.com", "jane2@example.com", "jane3@example.com"]  # 3 at most
    assert db.record(jane)["gone"] is False
    db.close()


def test_ryans_hand_edit_stays_on_top_and_he_can_put_a_value_back(tmp_path):
    db = _db(tmp_path)
    jane = db.find("10001")
    rev = db.record(jane)["rev"]
    db.set_field(jane, "phones", json.dumps([{"label": "mobile", "number": "808-555-0199"}]), rev, "her new number")
    r = db.merge_contacts(_cj(), by="james")
    assert r["kept_hand"] >= 1
    ph = _f(db, "10001", "phones")
    assert ph["hand"] and [p["number"] for p in ph["value"]] == ["808-555-0199"] and ph["by"] == "ryan"
    # the upload value under it grew (Ryan's first, the pilot's after it); Ryan unsets his edit and sees it
    db.unset_field(jane, "phones", db.record(jane)["rev"])
    assert [p["number"] for p in _f(db, "10001", "phones")["value"]] == ["808-555-0101", "808-555-0111"]
    # and he puts the value before the pilot's list back by hand: the log holds it
    old = db.db.execute("SELECT old FROM field_log WHERE pid=? AND field='phones' AND by='james'", (jane,)).fetchone()[0]
    db.set_field(jane, "phones", json.dumps([{"label": p["label"], "number": p["number"]} for p in json.loads(old)]),
                 db.record(jane)["rev"], "back")
    assert [p["number"] for p in _f(db, "10001", "phones")["value"]] == ["808-555-0101"]
    db.close()


def test_ryans_next_list_wins_on_what_it_lists_and_leaves_a_pilots_own_records(tmp_path):
    db = _db(tmp_path)
    db.merge_contacts(_cj(), by="james")
    db.clock_box["t"] = T0 + timedelta(days=3)
    newer = dict(CONTACTS, uploaded_at="2026-11-19T09:30:00-10:00")
    r = db.merge_contacts(newer)  # Ryan's own list again: Jane only
    assert r["applied"] and r.get("removed", 0) == 0 and r.get("conflicts", 0) == 0
    assert [p["number"] for p in _f(db, "10001", "phones")["value"]] == ["808-555-0101"]  # his list says her phones
    # the records and values only the pilot's list gave are not removed by Ryan's list not holding them
    assert _f(db, "10004", "name")["value"] == "Moe, Max" and _f(db, "10004", "union_id")["value"] == "77001"
    assert _f(db, "10002", "emails")["value"] == ["rick.roe@example.com"]
    assert db.meta("contacts_as_of") == "2026-11-19"
    db.close()


# ---------------------------------------------------------------- the inbox hand-off and the admin's drain
def _put(root, raw, rid=UID, pilot="james", now=None):
    PS.ensure_dirs(root, [pilot])
    return PS.contacts_put(pilot, rid, raw, root, now=now)


def test_the_list_waits_in_the_pilots_inbox_private_and_the_folder_names_its_author(tmp_path, caplog):
    db = _db(tmp_path)
    root = str(tmp_path / "pilotdb")
    raw = _csv()
    name = _put(root, raw, now=T0.timestamp())
    path = os.path.join(PS.inbox_dir("james", root), name)
    assert PT.INBOX_NAME_RE.fullmatch(name) and stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(PS.inbox_dir("james", root)).st_mode) == 0o700
    body = json.load(open(path))
    assert sorted(body) == sorted(["v", "by", "at", "cmd", "rid", "size", "sha", "data"])
    assert (body["by"], body["cmd"], body["size"], body["sha"]) == ("james", "contacts", len(raw),
                                                                     hashlib.sha256(raw).hexdigest())
    assert PS.waiting(PS.inbox_dir("james", root), UID)
    lines = []
    with caplog.at_level(logging.INFO):
        out = PS.drain(db, ["james"], root, now=T0.timestamp() + 5, log=lines.append)
    assert out["applied"] == 1 and out["refused"] == 0 and not os.listdir(PS.inbox_dir("james", root))
    assert db.find("10004") and _f(db, "10004", "name")["by"] == "james"
    a = db.answer_of("james", UID)
    assert a["ok"] and a["why"] == "Contacts merged: 4 rows read, 2 pilots added, 2 updated, 0 held for Ryan"
    assert lines == ["pilot db: contacts list from james: merged (4 rows, 2 added, 2 changed, 0 kept hand edits, "
                     "0 held for Ryan)"]
    for s in SECRETS:
        assert s not in " ".join(lines) + caplog.text, s
    # the sha of the file is on the merge row, the author is james, and the same rid again changes nothing
    assert db.db.execute("SELECT by,sha256 FROM merges ORDER BY id DESC").fetchone() == ("james", hashlib.sha256(raw).hexdigest())
    rev = db.rev
    _put(root, raw, now=T0.timestamp() + 6)
    assert PS.drain(db, ["james"], root, now=T0.timestamp() + 7)["applied"] == 1 and db.rev == rev
    db.close()


def test_the_drain_refuses_what_is_not_this_pilots_contacts_list(tmp_path):
    db = _db(tmp_path)
    root = str(tmp_path / "pilotdb")
    PS.ensure_dirs(root, ["james"])
    folder = PS.inbox_dir("james", root)
    raw = _csv()
    t = T0.timestamp()

    def plant(rid, **over):
        body = {"v": 1, "by": "james", "at": "2026-11-16T20:00:00+00:00", "cmd": "contacts", "rid": rid,
                "size": len(raw), "sha": hashlib.sha256(raw).hexdigest(), "data": base64.b64encode(raw).decode()}
        body.update(over)
        body = {k: v for k, v in body.items() if v is not None}
        with open(os.path.join(folder, f"{int(t * 1000):013d}-{rid}.json"), "w") as f:
            json.dump(body, f)

    total = db.summary()["records"]
    plant("rid-author-1", by="ryan")                                    # names another author than its folder
    plant("rid-sha-0001", sha="0" * 64)                                 # not the bytes it says
    plant("rid-size-001", size=len(raw) + 1)
    plant("rid-b64-0001", data="not base64 !!")
    plant("rid-extra-01", pid="p0123456789")                            # a key that is not a contacts list's
    plant("rid-pdf-0001", data=base64.b64encode(b"%PDF-1.4 x").decode(), size=10,
          sha=hashlib.sha256(b"%PDF-1.4 x").hexdigest())
    out = PS.drain(db, ["james"], root, now=t + 1)
    assert out == {"applied": 0, "refused": 6, "scrub": False} and not os.listdir(folder)
    assert db.summary()["records"] == total and db.find("10004") is None
    assert db.answer_of("james", "rid-author-1")["why"] == PS.UNREADABLE
    assert db.answer_of("james", "rid-pdf-0001")["why"] == PS.CONTACTS_BAD
    for rid in ("rid-sha-0001", "rid-size-001", "rid-b64-0001", "rid-extra-01"):
        assert db.answer_of("james", rid) == {**db.answer_of("james", rid), "ok": False, "why": PS.UNREADABLE}
    # with his share off: refused in Ryan's words, nothing merged
    db.set_share("james", False)
    plant("rid-off-0001")
    assert PS.drain(db, ["james"], root, now=t + 2)["refused"] == 1
    assert db.answer_of("james", "rid-off-0001")["why"] == PS.NOT_SHARED and db.find("10004") is None
    db.set_share("james", True)
    # a note file may not grow to a contacts list's size
    with open(os.path.join(folder, f"{int(t * 1000):013d}-rid-bignote1.json"), "w") as f:
        json.dump({"v": 1, "by": "james", "at": "x", "cmd": "note", "op": "add", "pid": db.find("10001"),
                   "text": "x", "rid": "rid-bignote1", "pad": "y" * (PT.INBOX_MAX_BYTES + 10)}, f)
    assert PS.drain(db, ["james"], root, now=t + 3)["refused"] == 1
    assert db.answer_of("james", "rid-bignote1")["why"] == PS.UNREADABLE
    db.close()


def test_at_most_four_lists_in_24_h_are_merged_for_a_pilot(tmp_path):
    db = _db(tmp_path)
    root = str(tmp_path / "pilotdb")
    t = T0.timestamp()
    n = roles.PILOT_CONTACTS_LIMITS["per_day"]
    assert n == 4
    for i in range(n + 1):
        row = [["Jane", "A", "Doe", "", "", "", "808-555-0101", f"j{i}@example.com", "10001", "HAL Emp# 10001"]]
        _put(root, _csv(row), rid=f"uDemoContactsDay{i:04d}", now=t + i)
        PS.drain(db, ["james"], root, now=t + i + 0.5)
    assert [db.answer_of("james", f"uDemoContactsDay{i:04d}")["ok"] for i in range(n + 1)] == [True] * n + [False]
    assert db.answer_of("james", f"uDemoContactsDay{n:04d}")["why"] == "Not merged: over 4 contacts lists in 24 h"
    db.close()


# ---------------------------------------------------------------- end to end: his Watcher, the inbox, Ryan's database
class Msg:
    def __init__(self, topic, payload):
        self.topic, self.payload = topic, payload.encode() if isinstance(payload, str) else payload


def _chunks(raw, uid=UID, month="2026-11", kind="contacts"):
    b = base64.b64encode(raw).decode("ascii")
    n = math.ceil(len(b) / LIM["chunk_chars"])
    sha = hashlib.sha256(raw).hexdigest()
    return [json.dumps({"uid": uid, "kind": kind, "month": month, "size": len(raw), "sha": sha, "part": p, "parts": n,
                        "data": b[(p - 1) * LIM["chunk_chars"]:p * LIM["chunk_chars"]]}) for p in range(1, n + 1)]


def _send(W, payloads):
    for p in payloads:
        W.on_message(None, None, Msg(f"{W.T}/upload/pdf", p))


def _answer(W, uid=UID):
    return next((x for x in W._pup_read().get("answers") or [] if x["uid"] == uid), None)


@pytest.fixture
def james(portal_pilot, tmp_path, monkeypatch):
    W, _ha = portal_pilot("james")
    root = str(tmp_path / "share" / "flight_watcher" / "pilotdb")
    up = tmp_path / "share" / "flight_watcher" / "uploads"
    up.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(W, "PILOTDB_SHARE", root)
    monkeypatch.setattr(W, "UPLOADS_SHARED", str(up))
    monkeypatch.setattr(W, "UPLOADS", str(up))
    monkeypatch.setattr(W, "local_now", lambda: NOW)
    monkeypatch.setattr(W, "_bg", lambda fn, *a: fn(*a))
    monkeypatch.setattr(W, "PDBV", {"view": None, "lock": W.threading.RLock(), "sig": None, "shown": None, "local": None})
    db = _db(tmp_path, "pilotdb.sqlite")
    assert W.portal_start(threads=False)
    PS.write_files(db, ["james"], root)
    W.pilotdb_watch()
    yield W, db, root
    db.close()


def _ups(W):
    return W.pilot_uploads_state()[f"sensor.{W.T}_pilot_uploads"]["attributes"]


def test_a_portal_pilots_contacts_list_lands_in_the_shared_database_with_his_name(james, caplog, monkeypatch):
    W, db, root = james
    c = _ups(W)["contacts"]
    assert c == {"offered": True, "file_bytes": 1048576, "waiting": False}
    for name in ("pilot_cmd", "gate_wait"):  # no lookup, no gate, no FLICA page is behind an upload
        if hasattr(W, name):
            monkeypatch.setattr(W, name, lambda *a, **k: (_ for _ in ()).throw(AssertionError(name)))
    raw = _csv()
    with caplog.at_level(logging.INFO):
        _send(W, _chunks(raw))
    a = _answer(W)
    assert a["ok"] and a["state"] == "sent" and "the admin's Watcher" in a["message"]
    assert _ups(W)["contacts"]["waiting"] is True
    names = os.listdir(PS.inbox_dir("james", root))
    assert len(names) == 1 and names[0].endswith(f"-{UID}.json")
    body = json.load(open(os.path.join(PS.inbox_dir("james", root), names[0])))
    assert body["by"] == "james" and body["cmd"] == "contacts" and base64.b64decode(body["data"]) == raw
    # nothing of it is kept on his side: no file in the uploads folder, no provenance record, no quarantine
    assert os.listdir(W.UPLOADS_SHARED) == [] and W.review().records() == []
    # the admin's pass: merged with james as the author; the answer comes back through his file
    assert PS.drain(db, ["james"], root, log=logging.getLogger("flight_watcher").info)["applied"] == 1
    PS.write_files(db, ["james"], root)
    assert W.pilotdb_watch()
    a = _answer(W)
    assert (a["ok"], a["state"]) == (True, "merged")
    assert a["message"] == "Contacts merged: 4 rows read, 2 pilots added, 2 updated, 0 held for Ryan."
    assert _ups(W)["contacts"]["waiting"] is False
    max_ = db.find("10004")
    assert db.record(max_)["fields"]["name"]["by"] == "james"
    assert db.db.execute("SELECT by FROM merges ORDER BY id DESC").fetchone()[0] == "james"
    # his own file now holds the pilot his list added
    W.pilotdb_watch()
    assert any(r["emp"] == "10004" for r in json.loads(W.pilotdb_view().text)["records"])
    for s in SECRETS:
        assert s not in caplog.text, s
    assert "contacts" in caplog.text


def test_his_watcher_refuses_a_file_that_is_not_the_export_and_sends_nothing(james):
    W, db, root = james
    cases = {"uDemoContactsBad0001": (_csv(head="Name,Phone\r\n"), "not the contacts list (CSV) export"),
             "uDemoContactsBad0002": (b"%PDF-1.4\n%%EOF\n", "not the contacts list (CSV) export"),
             "uDemoContactsBad0003": (_csv(rows=[]), "no pilot was read")}
    for uid, (raw, words) in cases.items():
        _send(W, _chunks(raw, uid=uid))
        a = _answer(W, uid)
        assert a and not a["ok"] and a["state"] == "error" and words in a["message"], uid
    assert os.listdir(PS.inbox_dir("james", root)) == []
    # over 1 MiB: refused at the first part
    big = HEAD.encode() + b"x" * (1024 * 1024)
    _send(W, _chunks(big, uid="uDemoContactsBig0001")[:1])
    a = _answer(W, "uDemoContactsBig0001")
    assert not a["ok"] and "1024 KB" in a["message"]
    assert os.listdir(PS.inbox_dir("james", root)) == []


def test_with_his_share_off_the_choice_is_gone_and_an_upload_is_refused(james):
    W, db, root = james
    db.set_share("james", False)
    PS.write_files(db, ["james"], root)
    W.pilotdb_watch()
    assert _ups(W)["contacts"]["offered"] is False
    _send(W, _chunks(_csv()))
    a = _answer(W)
    assert not a["ok"] and "Ryan has not shared the pilot database with you" in a["message"]
    assert os.listdir(PS.inbox_dir("james", root)) == [] if os.path.isdir(PS.inbox_dir("james", root)) else True


def test_one_list_waits_at_a_time_and_a_lost_one_is_answered(james, monkeypatch):
    W, db, root = james
    _send(W, _chunks(_csv()))
    assert _answer(W)["state"] == "sent"
    _send(W, _chunks(_csv(), uid="uDemoContacts0000002"))
    a = _answer(W, "uDemoContacts0000002")
    assert not a["ok"] and "still waiting" in a["message"]
    assert len(os.listdir(PS.inbox_dir("james", root))) == 1
    # its inbox file vanishes and no answer comes: after PILOTDB_LOST_S his card stops waiting
    for n in os.listdir(PS.inbox_dir("james", root)):
        os.unlink(os.path.join(PS.inbox_dir("james", root), n))
    W.pilotdb_watch(now=W.time.time() + W.PILOTDB_LOST_S + 5)
    a = _answer(W)
    assert not a["ok"] and a["state"] == "error" and "again" in a["message"]
    assert _ups(W)["contacts"]["waiting"] is False


def test_the_admin_never_takes_an_upload_command(portal_pilot):
    W, _ = portal_pilot("", portal=False)
    assert "upload/pdf" not in roles.subs_for(W.INSTANCE) if hasattr(roles, "subs_for") else True
    W.on_message(None, None, Msg(f"{W.T}/upload/pdf", _chunks(_csv())[0]))
    assert not (W._pup_read().get("answers") or [])


# ---------------------------------------------------------------- the portal card, in Chromium
from test_fw171_cards import P as CP, _browser, _card, _page, _s  # noqa: E402

SHOTS = os.environ.get("FW_1710D_SHOTS", "")


def _shot(pg, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        pg.screenshot(path=os.path.join(SHOTS, f"{name}.png"), full_page=True)


def _view(offered=True, last=None):
    c = {"offered": offered, "file_bytes": 1048576, "waiting": False}
    if last:
        c["last"] = last
    return {f"sensor.{CP}_pilot_uploads": _s("0", {
        "friendly_name": "Pilot uploads", "busy": False, "receiving": None, "contacts": c,
        "months": [{"month": m, "name": n, "pairings": {"on_file": True, "by": "the admin", "pending": False},
                    "award": {"on_file": False, "by": "", "pending": False}}
                   for m, n in (("2026-11", "November 2026"), ("2026-12", "December 2026"), ("2027-01", "January 2027"))],
        "mine": [], "answers": [],
        "limits": {"file_bytes": 4194304, "per_day": 4, "used_today": 0, "left_today": 4, "chunk_chars": 60000,
                   "chunk_parts": 94, "stale_s": 120, "kinds": ["pairings", "award"]}})}


def _pick_csv(pg, raw, name="contacts.csv"):
    pg.evaluate("() => { const k = c.shadowRoot.querySelector('[data-kind]'); k.value = 'contacts'; "
                "k.dispatchEvent(new Event('change')); }")
    inp = pg.evaluate_handle("() => c.shadowRoot.querySelector('[data-pdf]')")
    inp.as_element().set_input_files(files=[{"name": name, "mimeType": "text/csv", "buffer": raw}])


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_the_card_offers_contacts_list_csv_beside_the_pdfs(scheme):
    last = {"ok": True, "state": "merged", "at": "2026-11-16T20:02:00+00:00",
            "message": "Contacts merged: 4 rows read, 2 pilots added, 2 updated, 0 held for Ryan."}
    with _browser() as b:
        pg = _page(b, [_card("pilot-uploads-card")], width=390, scheme=scheme)
        pg.evaluate("""(st) => { window.c = mount('flight-watcher-pilot-uploads-card-pilot2', {}, st); }""",
                    _view(last=last))
        pg.evaluate("() => { const k = c.shadowRoot.querySelector('[data-kind]'); k.value = 'contacts'; "
                    "k.dispatchEvent(new Event('change')); }")
        got = pg.evaluate("""() => { const r = c.shadowRoot; return {
            kinds: [...r.querySelectorAll('[data-kind] option')].map((o) => [o.value, o.textContent]),
            month: getComputedStyle(r.querySelector('[data-monthl]')).display === 'none', lbl: r.querySelector('[data-filel]').textContent,
            accept: r.querySelector('[data-pdf]').getAttribute('accept'), text: r.textContent.replace(/\\s+/g, ' '),
            fit: fwFits(c), con: fwContrast(c), btn: r.querySelector('[data-up]').getBoundingClientRect().height,
            font: getComputedStyle(r.querySelector('[data-kind]')).fontSize}; }""")
        _shot(pg, f"portal_contacts_choice_390_{scheme}")
    assert got["kinds"] == [["pairings", "Pairings package"], ["award", "Award"], ["contacts", "Contacts list (CSV)"]]
    assert got["month"] is True and got["lbl"] == "CSV" and got["accept"] == "text/csv,.csv"
    assert "only adds and updates" in got["text"] and "A contacts list: up to 1024 KB" in got["text"]
    assert "Your contacts list" in got["text"] and "Contacts merged: 4 rows read, 2 pilots added" in got["text"]
    assert got["fit"]["right"] <= 390 and got["fit"]["page"] <= 390 and got["fit"]["inner"] <= 0
    assert got["con"]["fails"] == [], got["con"]["fails"]
    assert got["btn"] >= 44 and got["font"] == "16px"


def test_the_choice_is_not_there_while_the_watcher_does_not_offer_it():
    with _browser() as b:
        pg = _page(b, [_card("pilot-uploads-card")], width=390)
        kinds = {}
        for name, st in (("off", _view(offered=False)), ("older", {k: _s("0", {**v["attributes"], "contacts": None})
                                                                  for k, v in _view().items()})):
            kinds[name] = pg.evaluate("""(st) => { document.querySelector('.view').innerHTML = '';
              const c = mount('flight-watcher-pilot-uploads-card-pilot2', {}, st);
              return [[...c.shadowRoot.querySelectorAll('[data-kind] option')].map((o) => o.value),
                      c.shadowRoot.textContent.includes('never the seniority list or the contact list')]; }""", st)
    assert kinds == {"off": [["pairings", "award"], True], "older": [["pairings", "award"], True]}


def test_the_card_sends_a_contacts_list_in_parts_the_contract_takes():
    rows = [[f"Pat{i}", "", "Poe", "", "Example Air", "First Officer", f"808-555-{i:04d}", f"p{i}@example.com",
             str(20000 + i), f"HAL Emp# {20000 + i} | Sen# {i} (Jul 2026)"] for i in range(1, 700)]
    raw = _csv(rows)
    assert 60000 * 3 // 4 < len(raw) < 1024 * 1024  # more than one part
    with _browser() as b:
        pg = _page(b, [_card("pilot-uploads-card")], width=390)
        pg.evaluate("""(st) => { window.c = mount('flight-watcher-pilot-uploads-card-pilot2', {}, st); }""", _view())
        _pick_csv(pg, raw)
        pg.evaluate("() => c.shadowRoot.querySelector('[data-up]').click()")
        pg.wait_for_function("() => window.calls.length >= 2", timeout=15000)
        calls = pg.evaluate("() => window.calls")
        text = pg.evaluate("() => c.shadowRoot.textContent")
    parts = []
    for c in calls:
        assert c[:2] == ["mqtt", "publish"] and c[2]["topic"] == f"{CP}/upload/pdf"
        parts.append(PT.check_shape("upload/pdf", c[2]["payload"]))  # the spool's and HOM 1.9.1's own check
        assert len(json.dumps({"sub": "upload/pdf", "payload": c[2]["payload"]}).encode()) < PT.CAPS["cmd"]
    assert {(d["kind"], d["month"], d["size"], d["sha"]) for d in parts} == {
        ("contacts", "2026-11", len(raw), hashlib.sha256(raw).hexdigest())}  # this HST month, never a picked one
    assert [d["part"] for d in parts] == [1, 2] and parts[0]["parts"] == PP.parts_for(len(raw))
    assert base64.b64decode("".join(d["data"] for d in parts)) == raw[:len(base64.b64decode("".join(d["data"] for d in parts)))]
    assert "Sending the contacts list" in text


def test_the_card_refuses_what_is_not_the_export_before_sending():
    with _browser() as b:
        pg = _page(b, [_card("pilot-uploads-card")], width=390)
        out = {}
        files = {"pdf": b"%PDF-1.4\n%%EOF\n", "other": _csv(head="Name,Phone,Email\r\n"),
                 "big": _csv() + b"x" * (1024 * 1024)}
        for name, raw in files.items():
            pg.evaluate("""(st) => { document.querySelector('.view').innerHTML = '';
              window.c = mount('flight-watcher-pilot-uploads-card-pilot2', {}, st); window.calls = []; }""", _view())
            _pick_csv(pg, raw)
            pg.evaluate("() => c.shadowRoot.querySelector('[data-up]').click()")
            pg.wait_for_function("() => c.shadowRoot.querySelector('[data-msg]').textContent.length > 0")
            out[name] = pg.evaluate("() => [c.shadowRoot.querySelector('[data-msg]').textContent, window.calls.length]")
    for name in ("pdf", "other"):
        assert out[name][0].startswith("That file is not the contacts list (CSV) export") and out[name][1] == 0
    assert "a contacts list is up to 1024 KB" in out["big"][0] and out["big"][1] == 0


def test_a_portal_that_does_not_take_the_kind_yet_is_said_plainly_at_the_first_part():
    """HOM 1.9.0 (pinned to revision 4's shape) answers a chunk of kind contacts with 400 'Not available in the
    portal': the card stops at once, says so and sends nothing more; the PDF choices work as before."""
    with _browser() as b:
        pg = _page(b, [_card("pilot-uploads-card")], width=390)
        pg.evaluate("""(st) => { window.tries = 0; window.c = mount('flight-watcher-pilot-uploads-card-pilot2', {}, st,
          { callService: async () => { window.tries += 1;
              throw new Error('Not available in the portal: upload/pdf: kind is not one of its values.'); } }); }""",
                    _view())
        _pick_csv(pg, _csv())
        pg.evaluate("() => c.shadowRoot.querySelector('[data-up]').click()")
        pg.wait_for_function("() => /does not take a contacts list yet/.test(c.shadowRoot.querySelector('[data-msg]').textContent)",
                             timeout=5000)
        got = pg.evaluate("() => [window.tries, c.shadowRoot.querySelector('[data-up]').disabled, "
                          "c.shadowRoot.querySelector('[data-msg]').textContent]")
        _shot(pg, "portal_contacts_refused_by_hom_190_390")
    assert got[0] == 1 and got[1] is False
    assert got[2] == ("Not sent: the portal does not take a contacts list yet (it needs its next update). "
                      "Nothing was sent.")
