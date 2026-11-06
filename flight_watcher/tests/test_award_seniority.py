"""1.4.5 (Ryan, Nov 6: "the monthly award packet lists every pilot's date of hire"): an uploaded award is also read
for dates of hire and merged into seniority.json. Made-up text only: tests/fixtures/award_packet_synthetic.txt (a
bid-line award followed by a seniority section) and pilot blocks with a labeled DOH built here. The real packet was
not available to build on; its first upload is checked live (counts in the upload result and the app log)."""
import datetime as dt
import json
import logging

import pytest

import seniority as SEN
import web
from test_crew_index import W  # noqa: F401  (the Watcher fixture)
from test_web_upload import _fake_pdftotext, _mp

HST = dt.timezone(dt.timedelta(hours=-10))
LOG = logging.getLogger("t")


def _blocks(n=30, label="DOH", first_line=True):
    """Pilot blocks of a bid-line award with the date of hire labeled on the name line (made-up pilots)."""
    out = ["                                      A332FO PBS BIDLINE AWARD", "                                         Posted November 18, 2026"]
    for i in range(n):
        sen, emp, y = i + 1, f"8{i + 1:04d}", 1990 + i % 30
        doh = f"{label} {(i % 12) + 1:02d}/{(i % 27) + 1:02d}/{y % 100:02d}"
        if first_line:
            out += [f"{sen:05d} / {emp}   DOE{chr(65 + i % 26)}, JANE    {doh}      10:00", "                  01:00",
                    "Cr:080:00         H9001", "Days Off: 18      H9001", "                  FO"]
        else:  # the name on the next line, the DOH under it
            out += [f"{sen:05d} / {emp}                     10:00", f"ROE{chr(65 + i % 26)}, JOHN                 01:00",
                    f"Cr:080:00   {doh}   H9001", "Days Off: 18      H9001", "                  FO"]
    return "\n".join(out) + "\n"


def test_award_packet_seniority_section(fx):
    p = SEN.award_parse(fx("award_packet_synthetic.txt"), 2026)
    assert (p["reader"], len(p["rows"]), p["rejects"]) == ("seniority section", 30, [])
    by = {r["sen"]: r for r in p["rows"]}
    assert (by[1]["emp"], by[1]["name"], by[1]["doh"], by[1]["seat"]) == ("70001", "Doe, Jane", "1988-01-01", "CA")
    assert by[23]["name"] == "O'Poe, Alex" and by[24]["name"] == "Moe Jr, Pat" and by[22]["name"] == "Van Roe, John"
    assert p["list_date"] == ""  # the cover gives a posting date, not a list date
    # the bid lines ('00001 / 90001') carry no date of hire: never read as one
    assert len(SEN._award_blocks(fx("award_packet_synthetic.txt"), 2026)["rows"]) == 0


def test_award_pilot_lines_with_a_labeled_doh():
    p = SEN.award_parse(_blocks(), 2026)
    assert (p["reader"], len(p["rows"]), p["rejects"]) == ("pilot lines", 30, [])
    r = p["rows"][0]
    assert (r["sen"], r["emp"], r["name"], r["doh"]) == (1, "80001", "Doea, Jane", "1990-01-01")
    for label in ("HIRE DATE", "Date of Hire:", "D.O.H."):
        assert len(SEN.award_parse(_blocks(label=label), 2026)["rows"]) == 30, label
    q = SEN.award_parse(_blocks(first_line=False), 2026)  # name on the next line, DOH lower in the block
    assert len(q["rows"]) == 30 and q["rows"][1]["name"] == "Roeb, John"
    # an unlabeled date is never taken for a date of hire
    bare = SEN.award_parse(_blocks(label=""), 2026)
    assert bare["rows"] == [] and bare["reader"] == "seniority section"  # nothing read by either reader
    # a DOH after the award's year is a misread, and a repeat that disagrees is reported
    t = _blocks(3) + "00001 / 80001   DOEA, JANE    DOH 02/02/91\n00004 / 80004   DOEZ, JANE    DOH 01/01/2031\n"
    p = SEN.award_parse(t, 2026)
    assert [r["sen"] for r in p["rows"]] == [1, 2, 3] and [x for x, _ in p["rejects"]] == ["conflict-doh", "future-doh"]


def test_an_award_without_dates_of_hire_reads_none(fx):
    from test_pdfs import AWARD
    p = SEN.award_parse(AWARD, 2026)
    assert len(p["rows"]) < SEN.AWARD_MIN
    assert len(SEN.award_parse(_blocks(SEN.AWARD_MIN - 1), 2026)["rows"]) == SEN.AWARD_MIN - 1


def _up(tmp_path, monkeypatch, text, kind="award", month="2026-12", list_date="", day=(2026, 11, 20)):
    monkeypatch.setattr(web, "UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(web, "_hst_now", lambda: dt.datetime(*day, 9, 30, tzinfo=HST))
    monkeypatch.setattr(web.subprocess, "run", _fake_pdftotext(text))
    fields = {"month": month if kind != "seniority" else "", "kind": kind}
    if list_date:
        fields["list_date"] = list_date
    return web.upload_result(*_mp(fields, b"%PDF-1.4 fake"), LOG)


def _view(tmp_path):
    return json.loads((tmp_path / "seniority.json").read_text())


def test_award_alone_writes_the_dates_of_hire(tmp_path, monkeypatch, fx, caplog):
    with caplog.at_level(logging.INFO):
        r = _up(tmp_path, monkeypatch, fx("award_packet_synthetic.txt"))
    assert r["ok"] and r["file"] == "2026-12_award.pdf"
    assert r["message"] == ("Saved 2026-12_award.pdf (0 KB). Dates of hire: 30 pilots read from its seniority section; "
                            "30 pilots on file now.")
    assert r["seniority"]["decision"] == "on-top" and r["seniority"]["view"]["source"] == "award 2026-12"
    v = _view(tmp_path)
    assert (v["source"], v["award_month"], v["as_of"], v["count"], v["file"], v["parser"]) == (
        "award 2026-12", "2026-12", "2026-12-01", 30, "2026-12_award.pdf", SEN.PARSER)
    assert SEN.find(v, "70001")["doh"] == "1988-01-01"
    assert (tmp_path / "seniority_award.json").exists() and not (tmp_path / "seniority_list.json").exists()
    assert "dates of hire: 30 pilot rows (seniority section" in caplog.text and "Doe" not in caplog.text
    assert "1988" not in caplog.text
    # the Web UI page says where the dates of hire came from
    assert ("Dates of hire on file from the 2026-12 award: 30 pilots read, as of 2026-12-01 (the award&#x27;s bid "
            "period)") in web._seniority_status()


def test_an_award_with_no_dates_of_hire_never_replaces_a_good_list(tmp_path, monkeypatch, fx):
    _up(tmp_path, monkeypatch, fx("seniority_synthetic.txt"), kind="seniority", list_date="2026-03-01")
    before = (tmp_path / "seniority.json").read_bytes()
    from test_pdfs import AWARD
    r = _up(tmp_path, monkeypatch, AWARD, month="2027-01")
    assert r["ok"] and r["seniority"]["decision"] == "too-few"
    assert "No dates of hire read from it (0 pilot rows; 25 needed), so the seniority data on file is unchanged." in r["message"]
    assert (tmp_path / "seniority.json").read_bytes() == before and not (tmp_path / "seniority_award.json").exists()
    r = _up(tmp_path, monkeypatch, _blocks(SEN.AWARD_MIN - 1), month="2027-01")  # 24 rows: still not a section
    assert r["seniority"]["decision"] == "too-few" and (tmp_path / "seniority.json").read_bytes() == before


def test_a_later_award_goes_on_top_and_keeps_the_lists_other_pilots(tmp_path, monkeypatch, fx):
    _up(tmp_path, monkeypatch, fx("seniority_synthetic.txt"), kind="seniority", list_date="2026-03-01")
    r = _up(tmp_path, monkeypatch, fx("award_packet_synthetic.txt"))
    assert r["seniority"]["decision"] == "on-top"
    assert r["message"].endswith("30 pilots read from its seniority section; 42 pilots on file now (12 more kept from "
                                 "the seniority list of 2026-03-01).")
    v = _view(tmp_path)
    assert (v["source"], v["count"], v["carried"], v["base"]["as_of"], v["base"]["file"]) == (
        "award 2026-12", 42, 12, "2026-03-01", "seniority_2026-11-20.pdf")
    assert SEN.find(v, "901")["doh"] == "1988-05-01" and SEN.find(v, "70030")["doh"]  # list pilot and award pilot
    assert SEN.find(v, "90011", "Noe, Nina")["sen"] == 12  # the list's shared employee number still decided by name
    assert json.loads((tmp_path / "seniority_list.json").read_text())["count"] == 12
    s = web.uploads_json("1.4.5")["seniority"]
    assert (s["pilots"], s["source"], s["as_of"], s["carried"], s["base"]["as_of"]) == (42, "award 2026-12", "2026-12-01", 12, "2026-03-01")
    # an older list uploaded under the newer award: the award stays on top, the new list under it
    r = _up(tmp_path, monkeypatch, fx("seniority_synthetic.txt"), kind="seniority", list_date="2026-06-01", day=(2026, 11, 21))
    assert r["ok"] and "The award 2026-12 on file is later (2026-12-01), so its dates of hire stay on top of this list (42 pilots in all)." in r["message"]
    v = _view(tmp_path)
    assert (v["source"], v["base"]["list_date"], v["base"]["file"]) == ("award 2026-12", "2026-06-01", "seniority_2026-11-21.pdf")


def test_a_newer_dedicated_list_wins(tmp_path, monkeypatch, fx):
    _up(tmp_path, monkeypatch, fx("award_packet_synthetic.txt"))
    r = _up(tmp_path, monkeypatch, fx("seniority_synthetic.txt"), kind="seniority", list_date="2026-12-15", day=(2026, 12, 16))
    assert r["ok"] and "12 pilots read, list date 2026-12-15" in r["message"] and "on top" not in r["message"]
    v = _view(tmp_path)
    assert (v["source"], v["count"], v["as_of"], v["award_older"]["source"]) == ("list", 12, "2026-12-15", "award 2026-12")
    assert SEN.find(v, "70002") is None and not (tmp_path / "seniority_list.json").exists()
    # an award re-read while the newer list is on file: kept aside, the list stays in use
    r = _up(tmp_path, monkeypatch, fx("award_packet_synthetic.txt"), day=(2026, 12, 17))
    assert r["seniority"]["decision"] == "list-newer" and "the seniority list on file (2026-12-15) is newer and stays in use" in r["message"]
    assert _view(tmp_path)["source"] == "list"
    # no list date typed or printed: the list's upload day is its date, and a tie goes to the list
    r = _up(tmp_path, monkeypatch, fx("seniority_synthetic.txt"), kind="seniority", day=(2026, 12, 1))
    assert (_view(tmp_path)["source"], _view(tmp_path)["as_of"]) == ("list", "2026-12-01")


def test_award_months(tmp_path, monkeypatch, fx):
    _up(tmp_path, monkeypatch, fx("award_packet_synthetic.txt"), month="2027-01")
    r = _up(tmp_path, monkeypatch, _blocks(), month="2026-12")  # an older award: the newer one stays
    assert r["seniority"]["decision"] == "older-award"
    assert "Dates of hire: 30 pilots read, but the 2027-01 award on file is newer and stays in use." in r["message"]
    assert _view(tmp_path)["source"] == "award 2027-01" and SEN.find(_view(tmp_path), "80001") is None
    r = _up(tmp_path, monkeypatch, _blocks(), month="2027-01")  # the same month again: the re-upload replaces it
    assert r["seniority"]["decision"] == "on-top" and _view(tmp_path)["reader"] == "pilot lines"
    assert SEN.find(_view(tmp_path), "80001") and SEN.find(_view(tmp_path), "70001") is None


def test_a_1_4_4_seniority_json_is_the_list(tmp_path, monkeypatch, fx):
    """A seniority.json written before 1.4.5 has no 'source': it is the dedicated list, kept under a later award."""
    parsed = SEN.parse(fx("seniority_synthetic.txt"), 2026)
    old = SEN.to_json(parsed, "seniority_2026-11-06.pdf", "2026-11-06T09:30:00-10:00", "2026-03-01")
    (tmp_path / "seniority.json").write_text(json.dumps(old))
    _up(tmp_path, monkeypatch, fx("award_packet_synthetic.txt"))
    v = _view(tmp_path)
    assert (v["source"], v["count"], v["base"]["file"]) == ("award 2026-12", 42, "seniority_2026-11-06.pdf")
    lst = json.loads((tmp_path / "seniority_list.json").read_text())
    assert (lst["source"], lst["list_date"], lst["pilots"]) == ("list", "2026-03-01", old["pilots"])


def test_combine_rules():
    lst = {"source": "list", "list_date": "2026-03-01", "count": 1, "pilots": {"1": {"sen": 1, "doh": "1990-01-01"}}}
    aw = {"source": "award 2026-12", "award_month": "2026-12", "count": 1, "pilots": {"2": {"sen": 2, "doh": "2000-01-01"}}}
    assert SEN.combine(None, None) is None
    assert SEN.combine(lst, None)["source"] == "list" and SEN.combine(None, aw)["source"] == "award 2026-12"
    v = SEN.combine(lst, aw)
    assert (v["source"], sorted(v["pilots"]), v["carried"], v["newest_doh"]) == ("award 2026-12", ["1", "2"], 1, "2000-01-01")
    assert SEN.combine(dict(lst, list_date="2026-12-01"), aw)["source"] == "list"  # a tie goes to the list
    assert SEN.combine(dict(lst, list_date="", uploaded_at="2026-12-05T08:00:00-10:00"), aw)["source"] == "list"
    assert SEN.as_of(dict(aw, list_date="2026-11-18")) == "2026-11-18"  # a list date printed in the award wins
    # a pilot on both: the later source's record (seniority number, seat) wins, the date of hire is the same
    both = SEN.combine(lst, dict(aw, pilots={"1": {"sen": 7, "doh": "1990-01-01", "seat": "CA"}}))
    assert both["pilots"] == {"1": {"sen": 7, "doh": "1990-01-01", "seat": "CA"}} and both["carried"] == 0


def test_the_watcher_reads_an_award_on_file_at_start(W, tmp_path, monkeypatch, fx):
    """An award uploaded before 1.4.5 (no seniority.json yet) is read for dates of hire at the first start; its
    signature is stored under 'sen:<file>' (uploads_check keeps the plain name for the award's line), so it is not
    read again until the parser changes; then the list and the award are both read again (made-up text)."""
    import os
    up = tmp_path / "uploads"
    up.mkdir()
    (up / "2026-12_award.txt").write_text(fx("award_packet_synthetic.txt"), encoding="utf-8")
    monkeypatch.setattr(W, "UPLOADS_SHARED", str(up))
    W.S.setdefault("uploads_done", {})["2026-12_award.txt"] = "123"  # uploads_check's own mark is left alone
    W.seniority_refresh()
    v = json.loads((up / "seniority.json").read_text())
    assert (v["source"], v["count"], v["file"], v["parser"]) == ("award 2026-12", 30, "2026-12_award.pdf", SEN.PARSER)
    done = W.DB.load_state()["uploads_done"]
    assert done["2026-12_award.txt"] == "123" and done["sen:2026-12_award.txt"].endswith(f"|{SEN.PARSER}")
    mt = (up / "seniority.json").stat().st_mtime_ns
    W._SEN_CACHE.clear()
    W.seniority_refresh()  # current: not read again
    assert (up / "seniority.json").stat().st_mtime_ns == mt
    # a list arrives, then a release changes the parser: both sources are read again, the award still on top
    (up / "seniority_2026-11-06.txt").write_text(fx("seniority_synthetic.txt"), encoding="utf-8")
    calls, real_w, real_a = [], W.web.seniority_write, W.web.award_seniority
    monkeypatch.setattr(W.web, "seniority_write", lambda path, *a: calls.append(os.path.basename(path)) or real_w(path, *a))
    monkeypatch.setattr(W.web, "award_seniority", lambda path, *a: calls.append(os.path.basename(path)) or real_a(path, *a))
    monkeypatch.setattr(W.SEN, "PARSER", SEN.PARSER + 1)
    W._SEN_CACHE.clear()
    W.seniority_refresh()
    v = json.loads((up / "seniority.json").read_text())
    assert calls == ["seniority_2026-11-06.txt", "2026-12_award.txt"]
    assert (v["source"], v["count"], v["carried"], v["parser"]) == ("award 2026-12", 42, 12, W.SEN.PARSER)
    W._SEN_CACHE.clear()
    W.seniority_refresh()
    assert calls == ["seniority_2026-11-06.txt", "2026-12_award.txt"]  # read once per parser


def test_the_second_pilots_watcher_never_writes_it(W, tmp_path, monkeypatch, fx):
    up = tmp_path / "uploads"
    up.mkdir()
    (up / "2026-12_award.txt").write_text(fx("award_packet_synthetic.txt"), encoding="utf-8")
    monkeypatch.setattr(W, "UPLOADS_SHARED", str(up))
    monkeypatch.setattr(W, "INSTANCE", "pilot2")
    W.seniority_refresh()
    assert not (up / "seniority.json").exists()


def test_a_shared_employee_number_keeps_both_pilots_under_an_award():
    """Review fix: the list holds two pilots on one employee number (the record and 'also'); a later award that lists
    only one of them keeps the other from the list, so each is still found by last name with their own date of hire
    (PWA 3.B.1 longevity) instead of the one left getting the other's (made-up pilots)."""
    ann = {"sen": 11, "name": "Moe, Ann", "last": "Moe", "doh": "1995-01-01", "seat": "CA", "equip": "330"}
    nina = {"sen": 12, "name": "Noe, Nina", "last": "Noe", "doh": "2010-06-01", "seat": "FO", "equip": "330"}
    jane = {"sen": 1, "name": "Doe, Jane", "last": "Doe", "doh": "1988-05-01", "seat": "CA", "equip": "330"}
    lst = {"source": "list", "list_date": "2026-03-01", "count": 3,
           "pilots": {"90011": dict(ann, also=[nina]), "901": jane}}
    assert SEN.find(lst, "90011", "Noe, Nina")["doh"] == "2010-06-01"
    award = {"source": "award 2026-12", "award_month": "2026-12", "count": 1,
             "pilots": {"90011": dict(ann, sen=10, seat="FO")}}  # only Ann, with her award record
    v = SEN.combine(lst, award)
    assert SEN.find(v, "90011", "Noe, Nina") == nina and SEN.find(v, "90011", "Moe, Ann")["sen"] == 10
    assert (v["count"], v["carried"], v["newest_doh"]) == (3, 2, "2010-06-01")  # Jane and Nina kept from the list
    assert lst["pilots"]["90011"]["also"] == [nina] and "also" not in award["pilots"]["90011"]  # inputs untouched
    # the award holds the other one: Ann stays, from the list, without a nested 'also'
    v = SEN.combine(lst, dict(award, pilots={"90011": dict(nina, sen=13)}))
    assert SEN.find(v, "90011", "Moe, Ann") == ann and SEN.find(v, "90011", "Noe, Nina")["sen"] == 13
    assert v["pilots"]["90011"]["also"] == [ann] and v["carried"] == 2
    # the award holds both (its own 'also'): nothing is carried under that number, the award's records win
    v = SEN.combine(lst, dict(award, count=2, pilots={"90011": dict(ann, sen=10, also=[dict(nina, sen=14)])}))
    assert v["pilots"]["90011"]["also"] == [dict(nina, sen=14)] and (v["count"], v["carried"]) == (3, 1)
    assert SEN.find(v, "90011", "Noe, Nina")["sen"] == 14


def test_the_watcher_reads_an_award_on_file_beside_a_1_4_4_list(W, tmp_path, monkeypatch, fx, caplog):
    """Review fix: a seniority.json written by 1.4.4 (the current parser, no 'source') no longer stops the first 1.4.5
    start from reading an award already on file: its dates of hire are read once and go on top of the older list,
    then not again; an award with too few rows is tried once, not at every check (made-up text)."""
    import os
    up = tmp_path / "uploads"
    up.mkdir()
    old = SEN.to_json(SEN.parse(fx("seniority_synthetic.txt"), 2026), "seniority_2026-11-01.pdf",
                      "2026-11-01T09:30:00-10:00", "")
    assert old["parser"] == SEN.PARSER and "source" not in old
    (up / "seniority.json").write_text(json.dumps(old))
    (up / "seniority_2026-11-01.txt").write_text(fx("seniority_synthetic.txt"), encoding="utf-8")
    (up / "2026-12_award.txt").write_text(fx("award_packet_synthetic.txt"), encoding="utf-8")
    monkeypatch.setattr(W, "UPLOADS_SHARED", str(up))
    calls, real_w, real_a = [], W.web.seniority_write, W.web.award_seniority
    monkeypatch.setattr(W.web, "seniority_write", lambda path, *a: calls.append(os.path.basename(path)) or real_w(path, *a))
    monkeypatch.setattr(W.web, "award_seniority", lambda path, *a: calls.append(os.path.basename(path)) or real_a(path, *a))
    W._SEN_CACHE.clear()
    with caplog.at_level(logging.INFO):
        W.seniority_refresh()
    v = json.loads((up / "seniority.json").read_text())
    assert calls == ["2026-12_award.txt"]  # the list is current: only the award is read
    assert (v["source"], v["count"], v["carried"], v["base"]["file"]) == ("award 2026-12", 42, 12, "seniority_2026-11-01.pdf")
    assert (up / "seniority_award.json").exists() and json.loads((up / "seniority_list.json").read_text())["pilots"] == old["pilots"]
    assert "award 2026-12_award.txt dates of hire: 30 pilot rows (seniority section), on-top" in caplog.text
    for _ in range(2):  # later checks: nothing is read again
        W._SEN_CACHE.clear()
        W.seniority_refresh()
    assert calls == ["2026-12_award.txt"]
    # an award with too few dates of hire beside a 1.4.4 list: tried once, the list stays as it was
    for f in ("seniority.json", "seniority_award.json", "seniority_list.json", "2026-12_award.txt"):
        (up / f).unlink()
    (up / "seniority.json").write_text(json.dumps(old))
    from test_pdfs import AWARD
    (up / "2027-01_award.txt").write_text(AWARD, encoding="utf-8")
    calls.clear()
    for _ in range(3):
        W._SEN_CACHE.clear()
        W.seniority_refresh()
    assert calls == ["2027-01_award.txt"] and json.loads((up / "seniority.json").read_text()) == old
    assert not (up / "seniority_award.json").exists()
