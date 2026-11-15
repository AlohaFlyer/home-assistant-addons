"""1.7.8: the pilot database's upload merges (spec sections 7 and 8, with Ryan's Nov 14 answers: the seed from the kept
contact CSV and seniority.json, the seniority PDF winning on Sen#, DOH and status). A list makes records, a number two
pilots share ('also') makes two; a hand edit survives every upload; an older list is not applied; gone and back and
the 90% guard; renumbered, other_pilot and ambiguous rows are held, never moved, and each answer works; the contact
list matched by its Notes' HAL Emp# (the Employee ID column kept as union_id when it is another number), by Employee ID
and last name, or held; the award's dates of hire; the status codes and the DOR. Synthetic pilots only."""
from datetime import datetime, timedelta, timezone

import pytest

import pilotdb as P
import seniority as SEN

T0 = datetime(2026, 11, 15, 20, 0, tzinfo=timezone.utc)


def _p(sen, name, doh, **k):
    return dict({"sen": sen, "name": name, "last": name.split(",")[0], "doh": doh, "seat": "", "equip": ""}, **k)


JANE = _p(812, "Doe, Jane A.", "2001-05-01", status="SLOA")
RICK = _p(13, "Roe, Rick", "1985-09-17", status="A", seat="CA", equip="330", retire="2032-04")
PAT = _p(14, "Poe, Pat", "1986-01-01", status="A")


def lst(date, **pilots):
    return {"list_date": date, "pilots": {k[1:]: v for k, v in pilots.items()}}


@pytest.fixture
def db(tmp_path):
    clock = {"t": T0}
    d = P.PilotDB(str(tmp_path / "p.sqlite"), (), lambda: clock["t"])
    d.clock_box = clock
    return d


def vals(db, pid, field):
    return db.record(pid)["fields"][field]


def test_a_list_makes_records_and_also_makes_two_on_one_number(db):
    r = db.merge_list(lst("2026-07-01", e10001=JANE, e10002=dict(RICK, also=[PAT])))
    assert (r["applied"], r["rows"], r["added"], r.get("conflicts", 0)) == (True, 3, 3, 0)
    rick, pat = db.find("10002", "Roe, Rick"), db.find("10002", "Poe, Pat")
    assert rick and pat and rick != pat and db.find("10002") is None  # the number alone does not decide
    assert db.record(rick)["emp_shared"] and db.record(pat)["emp_shared"]
    assert not db.record(db.find("10001"))["emp_shared"]
    # the next list with both again: matched by last name, nobody added
    r = db.merge_list(lst("2026-08-01", e10001=JANE, e10002=dict(PAT, also=[RICK])))
    assert r.get("added", 0) == 0 and r.get("conflicts", 0) == 0
    assert vals(db, rick, "seat")["value"] == "CA" and vals(db, rick, "retire")["value"] == "2032-04"


def test_a_hand_edit_survives_three_uploads_and_an_older_list_is_not_applied(db):
    db.merge_list(lst("2026-07-01", e10001=JANE, e10002=RICK))
    pid = db.find("10001")
    db.set_field(pid, "status", "A", db.record(pid)["rev"], "back from leave")
    for i, d in enumerate(("2026-08-01", "2026-09-01", "2026-10-01")):
        r = db.merge_list(lst(d, e10001=dict(JANE, sen=812 - i), e10002=RICK))
        assert r["applied"]
        assert vals(db, pid, "status")["value"] == "A" and vals(db, pid, "status")["source"] == "hand"
    assert vals(db, pid, "sen")["value"] == "810"
    r = db.merge_list(lst("2026-01-01", e10001=dict(JANE, sen=1), e10002=RICK))
    assert r == {"rows": 2, "applied": False, "why": "older"} and vals(db, pid, "sen")["value"] == "810"
    m = db.db.execute("SELECT ref,changed FROM merges ORDER BY id DESC LIMIT 1").fetchone()
    assert m == ("list 2026-01-01", 0)


def test_gone_and_back_and_the_partial_list_guard(db):
    pilots = {f"e{10010 + i}": _p(100 + i, f"Moe{chr(65 + i)}, Max", "2010-01-01") for i in range(20)}
    db.merge_list(lst("2026-07-01", e10001=JANE, **pilots))
    pid = db.find("10001")
    r = db.merge_list(lst("2026-08-01", **pilots))  # Jane left the list
    assert r["gone"] == 1
    rec = db.record(pid)
    assert rec["gone"] and rec["gone_from"] == "list 2026-08-01"
    assert all(c["stale"] for c in rec["fields"]["sen"]["cands"] if c["source"] == "list")
    assert rec["fields"]["sen"]["stale"] is True and rec["fields"]["sen"]["value"] == "812"  # last on the list
    r = db.merge_list(lst("2026-09-01", e10001=JANE, **pilots))  # back (a recall from furlough)
    assert r["back"] == 1 and not db.record(pid)["gone"]
    assert [x["how"] for x in db.record(pid)["field_log"] if x["field"] == "_gone"][:2] == ["back", "gone"]
    # a list with fewer than 90% of the last one's pilots marks nobody gone: a list_partial conflict
    few = dict(list(pilots.items())[:10])
    r = db.merge_list(lst("2026-10-01", **few))
    assert r.get("gone", 0) == 0 and r["conflicts"] == 1
    c, = [c for c in db.conflicts() if c["kind"] == "list_partial"]
    assert len(c["row"]["missing"]) == 11 and not db.record(pid)["gone"]
    db.resolve(c["id"], "gone")  # Mark them gone anyway
    assert db.record(pid)["gone"]


def test_renumbered_is_held_never_moved_then_same_pilot(db):
    db.merge_list(lst("2026-07-01", e10001=JANE, e10002=RICK))
    pid = db.find("10001")
    db.add_entry(pid, "notes stay with the pilot")
    r = db.merge_list(lst("2026-08-01", e10051=JANE, e10002=RICK))  # same name and DOH, a new number
    assert r["conflicts"] == 1 and r.get("added", 0) == 0
    c, = db.conflicts()
    assert (c["kind"], c["pid"], c["emp"]) == ("renumbered", pid, "10051")
    assert db.find("10051") is None and db.record(pid)["emp"] == "10001"  # nothing moved
    assert not db.record(pid)["gone"]  # held, so not marked gone either
    db.resolve(c["id"], "same")
    rec = db.record(pid)
    assert rec["emp"] == "10051" and db.find("10051") == pid and len(rec["entries"]) == 1
    assert any(x["field"] == "_emp" and x["how"] == "move" for x in rec["field_log"])
    assert db.conflicts() == []
    # the same row again is not asked twice
    db.merge_list(lst("2026-08-01", e10051=JANE, e10002=RICK))
    assert db.conflicts() == []


def test_renumbered_different_pilot_and_ignore(db):
    db.merge_list(lst("2026-07-01", e10001=JANE, e10002=RICK))
    db.merge_list(lst("2026-08-01", e10051=JANE, e10002=RICK))
    c, = db.conflicts()
    new = db.resolve(c["id"], "different")
    assert new != db.find("10001") and db.find("10051") == new
    db.merge_list(lst("2026-09-01", e10061=RICK, e10051=JANE))
    c, = db.conflicts()
    assert c["kind"] == "renumbered"
    db.resolve(c["id"], "ignore")
    assert db.conflicts() == [] and db.find("10061") is None


def test_other_pilot_and_ambiguous_are_held(db):
    db.merge_list(lst("2026-07-01", e10001=JANE, e10002=RICK))
    jane = db.find("10001")
    # another pilot on Jane's number (another last name and DOH), listed once: other_pilot, nothing written
    r = db.merge_list(lst("2026-08-01", e10001=_p(812, "Zed, Zoe", "2015-02-02"), e10002=RICK))
    assert r["conflicts"] == 1
    c, = db.conflicts()
    assert c["kind"] == "other_pilot" and c["row"]["values"]["name"] == "Zed, Zoe"
    assert vals(db, jane, "name")["value"] == "Doe, Jane A."
    db.resolve(c["id"], "new")
    zoe = db.find("10001", "Zed, Zoe")
    assert zoe and zoe != jane and db.record(zoe)["emp_shared"] and db.record(jane)["emp_shared"]
    # two live records on 10001 and a row that fits neither: ambiguous
    db.merge_list(lst("2026-09-01", e10001=_p(812, "Qux, Quin", "2016-03-03"), e10002=RICK))
    c, = db.conflicts()
    assert c["kind"] == "ambiguous"
    with pytest.raises(P.Bad):
        db.resolve(c["id"], "same")  # not an answer to an ambiguous row
    db.resolve(c["id"], "attach", pid=zoe)
    assert vals(db, zoe, "name")["value"] == "Qux, Quin"  # Ryan said it is her (a name change)
    with pytest.raises(P.Missing):
        db.resolve(c["id"], "attach", pid=zoe)  # answered already
    with pytest.raises(P.Missing):
        db.resolve(999, "ignore")


def test_a_name_change_with_the_same_doh_is_a_match(db):
    db.merge_list(lst("2026-07-01", e10001=JANE))
    pid = db.find("10001")
    r = db.merge_list(lst("2026-08-01", e10001=_p(812, "Smith, Jane A.", "2001-05-01")))
    assert r.get("conflicts", 0) == 0 and r.get("added", 0) == 0
    rec = db.record(pid)
    assert rec["fields"]["name"]["value"] == "Smith, Jane A." and db.find("10001", "Smith, Jane") == pid
    assert db.search("doe")["total"] == 1  # the old spelling still finds her


FILLER = [{"emp": str(10070 + i), "name": f"Moe{chr(65 + i)}, Max", "phones": [], "emails": [f"m{i}@example.com"],
           "hal": {"emp": str(10070 + i), "sen": str(200 + i), "sen_month": "2026-07", "doh": "2012-01-01"}}
          for i in range(30)]


def test_contacts_by_hal_emp_with_union_id_and_unmatched(db):
    db.merge_list(lst("2026-07-01", e10001=JANE, e10002=RICK))
    cj = {"uploaded_at": "2026-11-14T09:30:00-10:00", "pilots": FILLER + [
        {"emp": "77001", "name": "Doe, Jane", "phones": [{"label": "cell", "number": "808-555-0101", "tel": "+18085550101"}],
         "emails": [], "hal": {"emp": "10001", "sen": "812", "sen_month": "2026-07", "doh": "2001-05-01",
                               "status": "SLOA", "retire": "2041-03"}},
        {"emp": "10002", "name": "Roe, Rick", "phones": [], "emails": ["rick.roe@example.com"]},  # no Notes: by Employee ID
        {"emp": "10003", "name": "Roe, Rick", "phones": [], "emails": ["x@example.com"]},  # 10003: no such record ...
        {"emp": "", "name": "Nobody, Ned", "phones": [{"label": "home", "number": "808-555-0109"}], "emails": []}]}
    r = db.merge_contacts(cj)
    jane, rick = db.find("10001"), db.find("10002")
    rec = db.record(jane)
    assert rec["fields"]["union_id"]["value"] == "77001"  # the Employee ID column was not the HAL number
    assert rec["fields"]["retire"]["value"] == "2041-03" and rec["fields"]["retire"]["source"] == "contacts"
    assert rec["fields"]["phones"]["value"][0]["tel"] == "+18085550101"
    assert vals(db, rick, "emails")["value"] == ["rick.roe@example.com"]
    # ... but last name and first name fit Rick: 10003's row lands on him? No: he is already matched in this file
    kinds = sorted(c["kind"] for c in db.conflicts())
    assert kinds == ["contact_unmatched", "contact_unmatched"] and r["conflicts"] == 2 and r["added"] == 30
    ned = next(c for c in db.conflicts() if c["row"]["values"]["name"] == "Nobody, Ned")
    db.resolve(ned["id"], "attach", pid=jane)
    assert len(vals(db, jane, "phones")["value"]) == 1  # attach applied Ned's row as Jane's contacts values
    # a newer contact list without Rick's row: only his contacts values go (logged)
    cj2 = {"uploaded_at": "2026-11-20T09:00:00-10:00",
           "pilots": [e for e in cj["pilots"] if e["name"] != "Roe, Rick"]}
    r = db.merge_contacts(cj2)
    assert r["removed"] == 1 and vals(db, rick, "emails")["value"] == [] and vals(db, rick, "sen")["value"] == "13"
    assert any(x["field"] == "emails" and x["new"] is None for x in db.record(rick)["field_log"])
    # a contact list with fewer than 90% of the last one's rows removes nobody's values (list_partial)
    r = db.merge_contacts({"uploaded_at": "2026-11-21T09:00:00-10:00", "pilots": cj["pilots"][-4:]})
    assert r.get("removed", 0) == 0 and any(c["kind"] == "list_partial" for c in db.conflicts())
    assert vals(db, db.find("10070"), "emails")["value"] == ["m0@example.com"]
    # an older contact list is not applied
    assert db.merge_contacts(cj)["applied"] is False
    assert db.find("10070")  # the HAL rows made records (the seed rule)


def test_the_seed_from_the_contact_csv_alone_then_the_list_wins(db):
    """Ryan, Nov 14: seed on the first start from the kept contact CSV (its Notes) and seniority.json; on Pako there
    is no seniority.json yet, so the HAL rows make the records; the seniority PDF later wins on Sen#, DOH and status."""
    cj = {"uploaded_at": "2026-11-14T09:30:00-10:00", "pilots": [
        {"emp": "010001", "name": "Doe, Jane", "name_full": "Doe, Jane A", "phones": [], "emails": ["j@example.com"],
         "hal": {"emp": "10001", "sen": "811", "sen_month": "2026-07", "doh": "2001-05-02", "status": "A",
                 "retire": "2041-03"}}],
        "hal_only": [{"emp": "10003", "name": "Poe, Pat", "hal": {"emp": "10003", "sen": "900", "sen_month": "2026-07",
                                                                   "doh": "2019-03-03", "status": "MLOA"}}]}
    r = db.merge_contacts(cj)
    assert r["added"] == 2 and db.find("10003") and db.find("10001")
    pid = db.find("10001")
    assert (vals(db, pid, "sen")["value"], vals(db, pid, "sen")["as_of"]) == ("811", "2026-07-01")
    assert vals(db, pid, "name")["value"] == "Doe, Jane A"
    db.merge_list(lst("2026-07-01", e10001=JANE))
    rec = db.record(pid)
    assert (rec["fields"]["sen"]["value"], rec["fields"]["sen"]["source"]) == ("812", "list")
    assert (rec["fields"]["doh"]["value"], rec["fields"]["doh"]["source"]) == ("2001-05-01", "list")
    assert (rec["fields"]["status"]["value"], rec["fields"]["status"]["source"]) == ("SLOA", "list")
    assert rec["fields"]["sen"]["disagree"] and rec["fields"]["doh"]["disagree"]  # flagged for Ryan
    assert rec["fields"]["retire"]["value"] == "2041-03"  # the contacts' age 65 month comes first for retire
    # a contacts-only record is never marked gone by a list (it never had a list value)
    db.merge_list(lst("2026-08-01", e10001=JANE))
    assert not db.record(db.find("10003"))["gone"]


def test_award_rows_and_the_status_codes_and_dor(db, fx):
    view = SEN.to_json(SEN.parse(fx("seniority_synthetic.txt"), 2026), "s.pdf", "2026-11-06T09:00:00-10:00",
                       "2026-03-01")
    r = db.merge_list(view)
    assert r["added"] == view["count"]
    jane = db.find("901")
    assert vals(db, jane, "retire")["value"] == "2028-05" and vals(db, jane, "seat")["value"] == "CA"
    aw = {"award_month": "2026-12", "pilots": {"901": {"sen": 1, "name": "Doe, Jane", "doh": "1988-05-01",
                                                       "seat": "FO", "equip": ""}}}
    r = db.merge_award(aw)
    assert r["applied"] and r.get("added", 0) == 0
    seat = vals(db, jane, "seat")
    assert (seat["value"], seat["source"]) == ("FO", "award")  # RECENCY: the award month is newer than the list
    assert db.merge_award(dict(aw, award_month="2026-11"))["applied"] is False  # an older award
    from test_seniority_hal import hal_text
    hal = SEN.to_json(SEN.parse(hal_text()), "u.pdf", "2026-11-14T09:00:00-10:00")
    db.merge_list(hal)
    codes = {db.record(p["pid"])["fields"]["status"]["value"] for p in db.search("", "all", 0)["rows"]
             if p["status"]}
    assert codes <= SEN.HAL_STATUS and len(codes) > 3


def test_merge_counts_and_no_value_or_name_in_the_merges_table(db):
    db.merge_list(lst("2026-07-01", e10001=JANE, e10002=RICK), by="ryan", sha="ab" * 32, parser=4)
    row = db.db.execute("SELECT source,ref,by,rows,added,changed,parser FROM merges").fetchone()
    assert row == ("list", "list 2026-07-01", "ryan", 2, 2, 2, 4)


def test_a_row_whose_name_cannot_be_read_marks_nobody_gone(db):
    pilots = {f"e{10010 + i}": _p(100 + i, f"Moe{chr(65 + i)}, Max", "2010-01-01") for i in range(20)}
    db.merge_list(lst("2026-07-01", e10001=JANE, **pilots))
    r = db.merge_list(lst("2026-08-01", e10001=dict(JANE, name="Doe Jane ‮"), **pilots))
    assert r["bad"] >= 1 and r.get("gone", 0) == 0 and not db.record(db.find("10001"))["gone"]
    assert vals(db, db.find("10001"), "name")["value"] == "Doe, Jane A."  # nothing written from the bad row
