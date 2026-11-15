"""1.7.10 (Ryan, Nov 15: "look at the records... it has the seniority and also our pairings award packet had it
monthly"): each month's award text has one line per awarded pilot, 'Seniority 00072 Category HNL-332-FO DOE 10001'
(seniority number, BASE-EQUIPMENT-SEAT, last name, employee number). The pilot database merges them (Sen #, base,
equipment, seat; source award, dated by the bid month); a hand edit stays on top; a number whose record carries another
last name is not touched; a packet with no dates of hire section no longer says 'too-few'. Synthetic pilots only
("Doe, Jane" 10001)."""
import logging
from datetime import datetime, timezone

import pytest

import pilotdb as P
import seniority as SEN
import web
from test_crew_index import W  # noqa: F401  (the Watcher fixture)
from test_pilotdb_watcher import P as PW  # noqa: F401  (the Watcher with a pilot database)

T0 = datetime(2026, 11, 15, 20, 0, tzinfo=timezone.utc)
LINE = "Seniority            {sen:05d}       Category {cat}          {last}       {emp}"


def award(rows, head="                                      A332FO PBS BIDLINE AWARD\n"):
    out = [head]
    for sen, cat, last, emp in rows:
        out += [LINE.format(sen=sen, cat=cat, last=last, emp=emp), "Cr:082:00      012:00", "Days Off: 17", ""]
    return "\n".join(out) + "\n"


ROWS = [(72, "HNL-332-FO", "DOE", 10001), (100, "HNL-332-FO", "ROE", 10002), (101, "HNL-332-CA", "VAN DOE", 10003),
        (102, "HNL-332-FO", "O'DOE JR", 10004)]


@pytest.fixture
def db(tmp_path):
    d = P.PilotDB(str(tmp_path / "p.sqlite"), (), lambda: T0)
    yield d
    d.close()


def _f(db, pid, field):
    return db.record(pid)["fields"][field]


def test_the_award_seniority_lines_parse():
    text = award(ROWS) + "Seniority list follows\nSeniority 00x72 Category HNL-332-FO DOE 10009\n" + LINE.format(
        sen=72, cat="HNL-332-FO", last="DOE", emp=10001) + "\n"  # a title, a line that does not read, a repeat
    got = SEN.award_sen_parse(text)
    assert got["rejects"] == 1 and len(got["rows"]) == 4
    assert got["rows"][0] == {"sen": 72, "emp": "10001", "last": "Doe", "base": "HNL", "equip": "332", "seat": "FO"}
    assert [(r["last"], r["seat"]) for r in got["rows"][2:]] == [("Van Doe", "CA"), ("O'Doe Jr", "FO")]
    assert SEN.award_sen_parse("")["rows"] == [] and SEN.award_sen_parse("Seniority\n")["rejects"] == 0


def test_the_lines_merge_into_the_database_as_source_award(db):
    db.merge_list({"list_date": "2026-07-01", "pilots": {"10001": {
        "sen": 812, "name": "Doe, Jane A.", "last": "Doe", "doh": "2001-05-01", "seat": "", "equip": ""}}})
    jane = db.find("10001")
    r = db.merge_award_sen("2026-12", SEN.award_sen_parse(award(ROWS))["rows"])
    assert (r["applied"], r["rows"], r["added"], r["changed"], r.get("unmatched", 0)) == (True, 4, 3, 4, 0)
    for field, value in (("domicile", "HNL"), ("equip", "332"), ("seat", "FO")):
        v = _f(db, jane, field)
        assert (v["value"], v["source"], v["as_of"], v["ref"]) == (value, "award", "2026-12-01", "award 2026-12"), field
    sen = _f(db, jane, "sen")  # the seniority list wins on Sen # (Ryan, Nov 14); the award's number is kept beside it
    assert (sen["value"], sen["source"]) == ("812", "list")
    assert [(c["source"], c["value"]) for c in sen["cands"]] == [("list", "812"), ("award", "72")]
    assert _f(db, jane, "name")["value"] == "Doe, Jane A." and not _f(db, jane, "name")["disagree"]
    # a pilot the database did not have: a record under the last name, Sen # from the award
    roe = db.find("10002")
    assert roe and _f(db, roe, "name")["value"] == "Roe" and _f(db, roe, "sen")["value"] == "100"
    assert db.search("roe")["rows"][0]["pid"] == roe and db.search("s100")["total"] == 1
    assert _f(db, db.find("10003"), "seat")["value"] == "CA"
    # the same month again changes nothing
    again = db.merge_award_sen("2026-12", SEN.award_sen_parse(award(ROWS))["rows"])
    assert (again["added"] if "added" in again else 0, again.get("changed", 0)) == (0, 0)
    assert db.summary()["sources"]["award"] == {"month": "2026-12", "count": 4}


def test_a_full_name_from_a_later_upload_is_shown_instead_of_the_last_name_alone(db):
    db.merge_award_sen("2026-12", SEN.award_sen_parse(award(ROWS))["rows"])
    roe = db.find("10002")
    db.merge_list({"list_date": "2026-12-05", "pilots": {"10002": {
        "sen": 99, "name": "Roe, Rick", "last": "Roe", "doh": "1999-09-17", "seat": "", "equip": ""}}})
    assert db.find("10002") == roe and db.summary()["live"] == 4  # the same record, nobody added
    name = _f(db, roe, "name")
    assert name["value"] == "Roe, Rick" and not name["disagree"]
    assert db.find("", "Roe, Rick") == roe  # its first initial follows the full name
    assert _f(db, roe, "sen")["value"] == "99"  # the list wins


def test_a_hand_edit_stays_and_a_newer_month_stands(db):
    db.merge_award_sen("2026-12", SEN.award_sen_parse(award(ROWS))["rows"])
    doe = db.find("10001")
    db.set_field(doe, "seat", "CA", db.record(doe)["rev"], "moved up")
    r = db.merge_award_sen("2027-01", SEN.award_sen_parse(award([(70, "HNL-332-RO", "DOE", 10001)]))["rows"])
    assert r["kept_hand"] == 1 and _f(db, doe, "seat")["value"] == "CA" and _f(db, doe, "seat")["hand"]
    assert _f(db, doe, "seat")["up"]["value"] == "RO" and _f(db, doe, "seat")["drift"]  # the card offers the award's
    assert _f(db, doe, "sen")["value"] == "70" and _f(db, doe, "sen")["as_of"] == "2027-01-01"
    older = db.merge_award_sen("2026-11", SEN.award_sen_parse(award([(75, "HNL-321-FO", "DOE", 10001)]))["rows"])
    assert older["applied"] and _f(db, doe, "sen")["value"] == "70" and _f(db, doe, "equip")["value"] == "332"
    assert db.summary()["sources"]["award"]["month"] == "2027-01"


def test_another_last_name_on_the_number_is_not_touched(db):
    db.new_record("10001", "Poe, Pat")
    r = db.merge_award_sen("2026-12", SEN.award_sen_parse(award(ROWS[:1]))["rows"])
    assert (r.get("added", 0), r.get("changed", 0), r["unmatched"]) == (0, 0, 1)
    assert db.summary()["live"] == 1 and _f(db, db.find("10001"), "sen")["value"] == ""
    assert db.merge_award_sen("nope", [])["applied"] is False


def test_base_is_a_field_ryan_can_edit(db):
    pid = db.new_record("10001", "Doe, Jane")
    db.set_field(pid, "domicile", "hnl", db.record(pid)["rev"])
    assert _f(db, pid, "domicile")["value"] == "HNL"
    with pytest.raises(P.Bad):
        db.set_field(pid, "domicile", "Honolulu", db.record(pid)["rev"])


def test_a_packet_with_no_dates_of_hire_is_not_too_few(tmp_path, monkeypatch):
    txt = tmp_path / "2026-12_award.txt"
    txt.write_text(award(ROWS))
    info = web.award_seniority(str(txt), "2026-12", "2026-12_award.pdf", "2026-11-20T09:00:00-10:00",
                               str(tmp_path / "seniority.json"))
    assert info["decision"] == "no-doh" and info["rows"] == 0 and info["sen_lines"] == 4
    note = web.award_note(info)
    assert note == "Seniority: 4 pilots read from it (Sen #, base, equipment and seat) for the pilot database."
    assert "dates of hire" not in note.lower() and not (tmp_path / "seniority_award.json").exists()
    assert "No seniority lines and no dates of hire" in web.award_note({"rows": 0, "decision": "no-doh"})
    # a few stray rows are still said as too few (nothing on file changes)
    assert web.award_note({"rows": 3, "decision": "too-few"}).startswith("No dates of hire read from it (3 pilot rows")


def test_the_watcher_reads_an_award_without_dates_of_hire_quietly(W, tmp_path, monkeypatch, caplog):  # noqa: F811
    up = tmp_path / "uploads"
    up.mkdir()
    (up / "2026-12_award.txt").write_text(award(ROWS))
    monkeypatch.setattr(W, "UPLOADS_SHARED", str(up))
    monkeypatch.setattr(W, "UPLOADS", str(up))
    W._SEN_CACHE.clear()
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        W.seniority_refresh()
    assert "dates of hire" not in caplog.text and "too-few" not in caplog.text


def test_the_watcher_merges_each_months_award_text(PW, caplog):  # noqa: F811
    W = PW  # noqa: N806
    up = W.share_dir / "uploads"
    (up / "2026-11_award.txt").write_text(award([(80, "HNL-332-FO", "ZOE", 10777)]))
    (up / "2026-12_award.txt").write_text(award([(72, "HNL-332-FO", "ZOE", 10777), (100, "HNL-332-FO", "QOE", 10778)]))
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        db = W.pilotdb_start()
    zoe = db.find("10777")
    f = db.record(zoe)["fields"]
    assert (f["sen"]["value"], f["sen"]["ref"], f["domicile"]["value"], f["equip"]["value"], f["seat"]["value"]) == (
        "72", "award 2026-12", "HNL", "332", "FO")
    assert db.find("10778") and db.meta("sig:awardsen:2026-11") and db.meta("sig:awardsen:2026-12")
    lines = [r.getMessage() for r in caplog.records if "award" in r.getMessage() and "seniority merged" in r.getMessage()]
    assert lines == ["pilot db: award 2026-11 seniority merged: 1 lines (0 not read), 1 added, 1 changed, 0 kept hand "
                     "edits, 0 another last name on the number (not touched)",
                     "pilot db: award 2026-12 seniority merged: 2 lines (0 not read), 1 added, 2 changed, 0 kept hand "
                     "edits, 0 another last name on the number (not touched)"]
    for leak in ("Zoe", "ZOE", "Qoe", "10777", "10778"):  # counts only
        assert leak not in caplog.text, leak
    n = len(caplog.records)
    assert W.pilotdb_tick() is False  # nothing moved: not merged again
    assert not [r for r in caplog.records[n:] if "seniority merged" in r.getMessage()]
    (up / "2026-12_award.txt").write_text(award([(71, "HNL-332-FO", "ZOE", 10777)]))
    assert W.pilotdb_tick() is True
    assert db.record(zoe)["fields"]["sen"]["value"] == "71"
