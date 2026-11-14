"""1.7.5.1 (Ryan, Nov 14: "what format does it need? make the settings page work with this format. it is what the union
provides"): the company's Pilot's System Seniority List PDF, as the union posts it, read beside the older SEN / EMP /
DOH list. The layout (pdftotext -layout): every page repeats a title block (company, list name, 'Effective <date>
(Rev. n)') and the header '*  Sen #  Name  Employee #  DOH  Remarks'; a row is '*  <sen>  Last, First M.  <emp>
<D-Mon-YY>  <status>' (the '*' marks a changed seniority number); columns drift a few characters page to page; a
'Page n of m' footer; the last page lists the pilots removed from the list (employee number, then the name), a status
legend and a footnote. No seat or equipment column. Every name and number here is invented."""
import datetime as dt
import json
import logging
import time

import pytest

import seniority as SEN
import web
from test_crew_index import W  # noqa: F401  (the Watcher fixture)
from test_web_upload import _fake_pdftotext, _mp

HST = dt.timezone(dt.timedelta(hours=-10))
LOG = logging.getLogger("t")
CODES = ("A", "ALPA", "EXEC", "FUR", "LOA", "MLOA", "MRET", "PESL", "SLOA")  # the status legend's codes
# (sen, name, emp, DOH as printed, status, '*' mark); made-up pilots
PAGE1 = [(1, "Doe, Jane A.", "10001", "3-Mar-86", "A", True),
         (2, "Roe, John C.", "10002", "19-Feb-88", "SLOA", True),
         (3, "Poe, Anna Marie B.", "10003", "22-Apr-89", "MLOA", True),
         (4, "Moe, Kimo", "10004", "8-May-89", "EXEC", True),
         (5, "Doe Jr., Robert K.", "10005", "2-Jun-88", "LOA", True),
         (6, "Van Doe, Karen", "10006", "15-Aug-90", "ALPA", True),
         (7, "O'Doe, Sean P.", "10007", "1-Feb-99", "FUR", True)]
PAGE2 = [(8, "Doe-Smith, Ann", "10008", "30-Nov-05", "MRET", False),  # no '*': the mark is optional
         (9, "McDoe, Kai", "10009", "6-Jan-15", "PESL", True),
         (10, "Zoe, Zachariah Q.", "10010", "9-Oct-23", "A", True),
         (11, "Noe, Nina", "9011", "1-Jun-26", "A", True),           # a 4-digit employee number, hired this year
         (12, "Loe, Lee", "10012", "05-Jul-01", "A", True)]
REMOVED = [("10099", "DOE JR., JOHN C."), ("9098", "ROE, RICHARD"), ("10097", "VAN ROE, ANNA M.")]


def _title(lead, eff="Effective July 1, 2026 (Rev. 1)"):
    return [f"{' ' * lead}HAWAIIAN AIRLINES, INC.", f"{' ' * (lead - 1)}Pilot’s System Seniority List",
            f"{' ' * (lead - 1)}{eff}", ""]


def _header(sh):
    return f"*   Sen #{' ' * (20 + sh)}Name{' ' * (19 - sh)}Employee #      DOH      Remarks"


def _row(r, sh):
    sen, name, emp, doh, st, star = r
    return f"{'*' if star else ' '}{sen:>6}     {name:<{38 + sh}}{emp:>8}{doh:>{13 + sh % 3}}{st:>{8 - sh % 2}}"


def hal_text(pages=((PAGE1, 0), (PAGE2, 3)), removed=REMOVED, eff="Effective July 1, 2026 (Rev. 1)"):
    """A made-up list in the union's layout: a page per (rows, column shift), then the last page."""
    out, n = [], len(pages) + 1
    for i, (rows, sh) in enumerate(pages):
        page = _title(28 + sh, eff) + [_header(sh)] + [_row(r, sh) for r in rows] + ["", f"{' ' * (37 + sh)}Page {i + 1} of {n}"]
        page[0] = ("\f" if i else "") + page[0]
        out += page
    out += ["\f" + " " * 37 + "HAWAIIAN AIRLINES, INC.", " " * 31 + "Pilot’s System Seniority List Committee",
            " " * 44 + "July 1st, 2026", "", "", "The following pilots were removed from the list:", "",
            " " * 25 + "Employee #                Name"]
    out += [f"{emp:>32}{' ' * 11}{name}" for emp, name in removed]
    out += ["", "", " " * 41 + "STATUS LEGEND", ""]
    out += [f"{' ' * 25}{c:<16}Made-up meaning of {c}" for c in CODES]
    out += ["", "", "Each Pilot’s System Seniority List is posted under Section 18 of the",
            "1999 Pilots Agreement. A pilot whose number is posted in error may protest it",
            "in writing under Section 18 of the Agreement.", "", " " * 47 + "Jane Roe",
            " " * 35 + "Chair, Made-up Committee", "", "*Denotes pilots who have changed seniority numbers.", "\f"]
    return "\n".join(out)


def test_reads_the_union_list():
    p = SEN.parse(hal_text())
    assert [r["sen"] for r in p["rows"]] == list(range(1, 13)) and p["rejects"] == []
    assert p["list_date"] == "2026-07-01" and p["sections"] == {"SYSTEM SENIORITY LIST": 12}
    by = {r["sen"]: r for r in p["rows"]}
    assert {r["status"] for r in p["rows"]} == set(CODES)  # every legend code, kept as the row's status
    assert all(r["seat"] == "" and r["equip"] == "" and r["listed"] == 1 for r in p["rows"])
    assert (by[1]["name"], by[1]["last"], by[1]["first"], by[1]["emp"], by[1]["doh"], by[1]["status"]) == (
        "Doe, Jane A.", "Doe", "Jane A.", "10001", "1986-03-03", "A")
    assert (by[3]["name"], by[4]["doh"], by[11]["emp"], by[11]["doh"], by[12]["doh"]) == (
        "Poe, Anna Marie B.", "1989-05-08", "9011", "2026-06-01", "2001-07-05")
    assert (by[5]["name"], by[5]["last"], by[5]["first"]) == ("Doe Jr., Robert K.", "Doe Jr.", "Robert K.")
    assert (by[6]["last"], by[7]["name"], by[8]["name"], by[9]["name"]) == ("Van Doe", "O'Doe, Sean P.", "Doe-Smith, Ann", "McDoe, Kai")
    # the removed pilots (employee number, then the name), the legend, the footnote, footers: never rows
    emps = {r["emp"] for r in p["rows"]}
    assert not emps & {e for e, _ in REMOVED} and not any("Made-up" in r["name"] or "Page" in r["name"] for r in p["rows"])


@pytest.mark.parametrize("shifts", [(0, 3), (-4, 6), (5, -3)])
def test_drifting_columns_and_more_pages(shifts):
    """The columns move a few characters from page to page; every page has its title block, header and footer."""
    many = [(i, f"Doe{chr(65 + i % 26)}, Jane {chr(65 + i % 7)}.", f"{10000 + i}", f"{1 + i % 28}-{'JanFebMarAprMayJunJulAugSepOctNovDec'[3 * (i % 12):3 * (i % 12) + 3]}-{(85 + i % 40) % 100:02d}",
             CODES[i % len(CODES)], i % 3 != 0) for i in range(13, 13 + 60)]
    pages = ((PAGE1, shifts[0]), (PAGE2, shifts[1]), (many[:30], shifts[0] + 1), (many[30:], shifts[1] - 1))
    p = SEN.parse(hal_text(pages), 2026)
    assert [r["sen"] for r in p["rows"]] == list(range(1, 73)) and p["rejects"] == []
    assert p["sections"] == {"SYSTEM SENIORITY LIST": 72}


def test_dates_statuses_and_rejects():
    t = "\n".join(_title(28) + [_header(0)]) + "\n"
    row = lambda sen, doh, st="A", name="Doe, Jane A.", emp="10001": _row((sen, name, emp, doh, st, True), 0)  # noqa: E731
    lines = [row(1, "3-Mar-1986"),             # a 4-digit year
             row(2, "1-Aug-26"),               # after the list's 'Effective' date: a misread, never priced
             row(3, "31-Feb-90"),              # no such day
             row(4, "4-Xyz-87"),               # no such month
             row(5, "8-May-198"),              # a 3-digit year: not a date of hire
             row(6, "8-May-89", "ZZZ"),        # a status the legend does not have: kept, reported
             row(7, "8-May-89", ""),           # no status
             row(8, "8-May-89", "A  X1")]      # a column this version does not know: kept, reported
    p = SEN.parse(t + "\n".join(lines) + "\n", 2026)
    assert [(r["sen"], r["doh"], r["status"]) for r in p["rows"]] == [
        (1, "1986-03-03", "A"), (6, "1989-05-08", "ZZZ"), (7, "1989-05-08", ""), (8, "1989-05-08", "A")]
    assert p["rejects"] == [("future-doh", 7), ("bad-date", 8), ("bad-date", 9), ("no-date", 10),
                            ("status-unknown", 11)] + [("sen-gap", 11)] * 4 + [("tail-unknown-token", 13)]
    # review fix: the century comes from the printed Effective date (2026), not the year given; with no date in the
    # file, the year given sets it, and a 1926 DOH (100 years of longevity) is not read
    assert SEN.parse(t + row(1, "1-Jun-26") + "\n", 2024)["rows"][0]["doh"] == "2026-06-01"
    assert SEN.parse(_header(0) + "\n" + row(1, "1-Jun-26") + "\n", 2024)["rejects"] == [("bad-date", 2)]


def test_header_order_and_no_header():
    rows = "\n".join(_row(r, 0) for r in PAGE1)
    swapped = "*   Sen #     Employee #      Name                    DOH      Remarks"
    p = SEN.parse(swapped + "\n" + rows + "\n", 2026)
    assert p["rows"] == [] and {r for r, _ in p["rejects"]} == {"header-order-hal"} and len(p["rejects"]) == len(PAGE1)
    assert not SEN.hal_header_order_ok(swapped) and SEN.hal_header_order_ok(_header(0))
    assert SEN.hal_header_order_ok("Sen #   Name   Employee #   DOH")  # no Remarks column, no '*'
    assert SEN.parse(rows + "\n", 2026)["rows"] == []  # rows with no header above them are not read


def test_the_typed_list_date_wins_and_the_printed_one_is_used_otherwise():
    p = SEN.parse(hal_text())
    assert SEN.to_json(p, "s.pdf", "2026-11-14T09:00:00-10:00", "2026-07-15")["list_date"] == "2026-07-15"
    assert SEN.to_json(p, "s.pdf", "2026-11-14T09:00:00-10:00")["list_date"] == "2026-07-01"
    assert SEN.list_date(hal_text(eff="Effective January 15, 2027 (Rev. 2)")) == "2027-01-15"
    assert SEN.parse(hal_text(eff="Revision 2"))["list_date"] == ""  # the last page's 'July 1st, 2026' is not it


def test_json_and_find():
    d = SEN.to_json(SEN.parse(hal_text()), "seniority_2026-11-14.pdf", "2026-11-14T09:00:00-10:00")
    assert (d["count"], d["newest_doh"], d["rejects"], d["notes"], d["parser"]) == (12, "2026-06-01", 0, {}, SEN.PARSER)
    assert d["pilots"]["10005"] == {"sen": 5, "name": "Doe Jr., Robert K.", "last": "Doe Jr.", "doh": "1988-06-02",
                                    "seat": "", "equip": ""}  # review fix: no Remarks code per pilot
    assert d["pilots"]["9011"]["sen"] == 11
    assert SEN.find(d, "010005")["sen"] == 5
    assert SEN.find(d, "", "DOE JR, ROBERT")["sen"] == 5 and SEN.find(d, "", "Doe, Robert")["sen"] == 5  # Jr. or not
    assert SEN.find(d, "", "VAN DOE, KAREN")["sen"] == 6 and SEN.find(d, "", "Doe Smith, Ann")["sen"] == 8
    assert SEN.find(d, "", "ODOE, SEAN")["sen"] == 7 and SEN.find(d, "", "Poe, Anna")["sen"] == 3
    assert SEN.find(d, "10099", "Doe, John") is None  # a removed pilot is not on the list


def test_the_old_list_rows_carry_no_status(fx):
    p = SEN.parse(fx("seniority_synthetic.txt"), 2026)
    assert {r["status"] for r in p["rows"]} == {""}
    d = SEN.to_json(p, "s.pdf", "2026-11-06T09:00:00-10:00")
    assert all("status" not in rec for rec in d["pilots"].values()) and "statuses" not in d


def test_a_malformed_wide_line_fails_fast():
    """The name zone starts and ends on a non-space, so a numbered line that does not match fails in linear time."""
    rows = []
    for w in (40, 60, 70):
        sp = " " * w
        rows.append(f"*{sp}1{sp}Doe, Jane A.{sp}10001{sp}3-Mar-8")            # DOH cut short
        rows.append(f"*{sp}2{sp}Roe, John{sp}10002{sp}3-Mar-86A{sp}X Y Z")   # DOH glued to the status, then junk
    t = time.perf_counter()
    p = SEN.parse(_header(0) + "\n" + "\n".join(rows * 200) + "\n", 2026)
    assert time.perf_counter() - t < 2.0 and p["rows"] == []
    assert {r for r, _ in p["rejects"]} <= {"no-date", "no-match", "too-long"} and len(p["rejects"]) == 1200


def _up(tmp_path, monkeypatch, text, list_date="", day=(2026, 11, 14)):
    monkeypatch.setattr(web, "UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(web, "_hst_now", lambda: dt.datetime(*day, 9, 30, tzinfo=HST))
    monkeypatch.setattr(web.subprocess, "run", _fake_pdftotext(text))
    fields = {"month": "", "kind": "seniority"}
    if list_date:
        fields["list_date"] = list_date
    return web.upload_result(*_mp(fields, b"%PDF-1.4 fake"), LOG)


def test_the_settings_page_takes_the_union_list(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    r = _up(tmp_path, monkeypatch, hal_text())
    assert r["ok"] and r["file"] == "seniority_2026-11-14.pdf"
    assert "12 pilots read, list date 2026-07-01, newest date of hire on it 2026-06-01 (0 lines not read)" in r["message"]
    d = json.loads((tmp_path / "seniority.json").read_text())
    assert (d["source"], d["count"], d["list_date"], d["file"]) == ("list", 12, "2026-07-01", "seniority_2026-11-14.pdf")
    assert "status" not in d["pilots"]["10002"] and d["pilots"]["10002"]["seat"] == "" and d["statuses"]["SLOA"] == 1
    assert "Doe" not in caplog.text and "1986" not in caplog.text and "10001" not in caplog.text
    r = _up(tmp_path, monkeypatch, hal_text(), list_date="2026-07-15")  # a typed date wins over the printed one
    assert r["ok"] and json.loads((tmp_path / "seniority.json").read_text())["list_date"] == "2026-07-15"


def test_a_refused_list_says_which_lists_are_read(tmp_path, monkeypatch):
    r = _up(tmp_path, monkeypatch, "Minutes of the March meeting\n")
    assert not r["ok"] and "No pilot rows were found" in r["message"]
    assert "Pilot's System Seniority List" in r["message"] and "SEN / EMP / DOH" in r["message"]
    assert "Pilot's System Seniority List" in web.PAGE and "SEN / EMP / DOH" in web.PAGE


def test_the_uploads_card_says_which_lists_it_reads():
    import os
    js = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "www", "flight-watcher-uploads-card.js"),
              encoding="utf-8").read()
    assert "Pilot's System Seniority List" in js and "SEN / EMP / DOH" in js and "data-sh" in js


def _list_on_file(W, tmp_path, monkeypatch, award=""):
    up = tmp_path / "uploads"
    up.mkdir(exist_ok=True)
    d = SEN.to_json(SEN.parse(hal_text()), "seniority_2026-11-14.pdf", "2026-11-14T09:30:00-10:00")
    (up / "seniority.json").write_text(json.dumps(dict(d, source="list")))
    if award:
        (up / "2026-11_award.txt").write_text(award)
    monkeypatch.setattr(W, "UPLOADS_SHARED", str(up))
    monkeypatch.setattr(W, "UPLOADS", str(up))
    W._SEN_CACHE.clear()
    W._NAME_DIR.update(sig=None, rows=[])
    return d


def test_the_watchers_readers_take_records_with_no_seat(W, tmp_path, monkeypatch):
    """Pay for a looked-up pilot, the pilot card's pay note fields, the Recall seniority source and the name lookup
    all read the union list's records (no seat, no equipment)."""
    _list_on_file(W, tmp_path, monkeypatch)
    monkeypatch.setattr(W, "ha_state", lambda e: None)
    line = W.pilot_pay_line([], "10005", "DOE JR, ROBERT", "2026-11-01", "2026-11-30")
    assert (line["list_status"], line["list_date"], line["list_newest_doh"], line["seat_list"], line["list_source"]) == (
        "ok", "2026-07-01", "2026-06-01", "", "list")
    assert (line["doh_known"], line["doh"]) == (True, "1988-06-02")
    assert W.pilot_pay_line([], "55555", "Van Doe, Karen", "2026-11-01", "2026-11-30")["doh"] == "1990-08-15"  # by name
    assert W.pilot_pay_line([], "10099", "Doe, John", "2026-11-01", "2026-11-30")["list_status"] == "not_on_list"
    W.S["own_emp"] = "10006"
    assert W.own_seniority() == (6, "seniority list")
    me, src = W.recall_me(with_source=True)
    assert (me["sen"], src) == (6, "seniority list")
    rows = {r["emp"]: r for r in W.name_directory()}
    assert (rows["10009"]["name"], rows["10009"]["seat"]) == ("McDoe, Kai", "")  # mixed case kept as printed
    assert rows["10005"]["name"] == "Doe Jr., Robert K." and len(rows) == 12


def test_the_award_seat_fills_in_and_an_award_on_top_keeps_the_list(W, tmp_path, monkeypatch):
    award = "\n".join(["                                      A332FO PBS BIDLINE AWARD", "",
                       "00001 / 10001", "DOE, JANE", "Cr:080:00", ""])
    lst = _list_on_file(W, tmp_path, monkeypatch, award)
    rows = {r["emp"]: r for r in W.name_directory()}
    assert (rows["10001"]["name"], rows["10001"]["seat"]) == ("Doe, Jane A.", "FO")  # the list's name, the award's seat
    # an award with dates of hire later than the list goes on top; the list's other pilots (and their status) stay
    blocks = ["A332FO PBS BIDLINE AWARD"] + [f"{i:05d} / {20000 + i}   ROE{chr(65 + i % 26)}, JOHN    DOH 01/{i:02d}/95"
                                             for i in range(1, 27)]
    aw = SEN.to_json(SEN.award_parse("\n".join(blocks) + "\n", 2026), "2026-12_award.pdf", "2026-11-20T09:00:00-10:00")
    aw.update(source="award 2026-12", award_month="2026-12")
    out = SEN.combine(dict(lst, source="list"), aw)
    assert (out["source"], out["carried"], out["count"]) == ("award 2026-12", 12, 38)
    assert SEN.find(out, "10005", "Doe Jr., Robert")["doh"] == "1988-06-02" and SEN.find(out, "20003")["seat"] == ""


def test_the_watcher_reads_a_union_list_text_copy_at_start(W, tmp_path, monkeypatch):
    """The parser number went up (3): a text copy on file is read again with the union list's rules; its printed
    Effective date is the list date when none was typed."""
    assert SEN.PARSER >= 3
    up = tmp_path / "uploads"
    up.mkdir()
    (up / "seniority_2026-11-14.txt").write_text(hal_text(), encoding="utf-8")
    (up / "seniority.json").write_text(json.dumps({"file": "seniority_2026-11-14.pdf", "parser": SEN.PARSER - 1,
                                                   "uploaded_at": "2026-11-14T09:30:00-10:00", "list_date": "",
                                                   "count": 0, "pilots": {}}))
    monkeypatch.setattr(W, "UPLOADS_SHARED", str(up))
    W._SEN_CACHE.clear()
    W.seniority_refresh()
    d = json.loads((up / "seniority.json").read_text())
    assert (d["count"], d["list_date"], d["parser"], d["rejects"]) == (12, "2026-07-01", SEN.PARSER, 0)
    assert d["statuses"]["MLOA"] == 1 and "status" not in d["pilots"]["10003"]
    assert d["uploaded_at"] == "2026-11-14T09:30:00-10:00"


# ---------------------------------------------------------------- 1.7.5.1 review fixes (made-up rows only)
def _page(rows, eff="Effective July 1, 2026 (Rev. 1)"):
    return "\n".join(_title(28, eff) + [_header(0)] + rows) + "\n"


def _r(sen, name="Doe, Jane A.", doh="3-Mar-86", st="A"):
    return _row((sen, name, str(10000 + sen), doh, st, True), 0)


def test_the_century_comes_from_the_printed_list_date(tmp_path, monkeypatch):
    """Review fix: the union list prints every DOH as D-Mon-YY. The century comes from the list's own Effective date
    (else the typed date, else the upload year): the Jan 1, 2027 list uploaded on Dec 28, 2026 reads '1-Jan-27' as
    2027, and a typed date a year off does not turn this year's hires into 1926 (the page says the dates differ)."""
    text = _page([_r(1), _r(2, "Roe, John C.", "1-Jan-27")], "Effective January 1, 2027 (Rev. 1)")
    r = _up(tmp_path, monkeypatch, text, day=(2026, 12, 28))
    d = json.loads((tmp_path / "seniority.json").read_text())
    assert r["ok"] and (d["list_date"], d["pilots"]["10002"]["doh"], d["rejects"]) == ("2027-01-01", "2027-01-01", 0)
    assert "Check the list date" not in r["message"]
    r = _up(tmp_path, monkeypatch, _page([_r(1), _r(2, "Roe, John C.", "1-Jun-26")]), list_date="2025-07-01")
    d = json.loads((tmp_path / "seniority.json").read_text())
    assert r["ok"] and (d["list_date"], d["pilots"]["10002"]["doh"], d["rejects"]) == ("2025-07-01", "2026-06-01", 0)
    assert "Check the list date: the PDF prints 2026-07-01, the typed 2025-07-01 is kept." in r["message"]
    # the Watcher's re-read of a text copy at start takes the same path (web.seniority_read)
    (tmp_path / "x.txt").write_text(text, encoding="utf-8")
    p = web.seniority_read(str(tmp_path / "x.txt"), "2026-12-28T09:30:00-10:00")
    assert [r["doh"] for r in p["rows"]] == ["1986-03-03", "2027-01-01"] and p["rejects"] == []


def test_a_doh_the_list_cannot_hold_is_not_read():
    """Review fix: a pilot retires at 65, so a DOH 60 years or more before the list is a misread ('bad-date'), never
    decades of longevity. With no date in the file, the year given (typed, else the upload's) sets the century."""
    t = "\n".join([_header(0), _r(1, doh="1-Jun-26"), _r(2, doh="1-Jun-67"), _r(3, doh="1-Jun-66"),
                   _r(4, doh="3-Mar-1950")]) + "\n"
    p = SEN.parse(t, 2026)
    assert [(r["sen"], r["doh"]) for r in p["rows"]] == [(1, "2026-06-01"), (2, "1967-06-01")]
    assert p["rejects"] == [("bad-date", 4), ("bad-date", 5)]
    p = SEN.parse(t, 2025)  # 1-Jun-26 on a 2025 list would be 1926: not read (1966 is 59 years before it: read)
    assert [r["sen"] for r in p["rows"]] == [2, 3]
    assert p["rejects"] == [("bad-date", 2), ("sen-gap", 3), ("bad-date", 5)]  # sen 1 not read: a number missing
    old = ("SEN   NAME, Initial   EMP #   ALPA #   LAST NAME   FIRST NAME   DOH   DOR   EQUIP   SEAT\n"
           "  1  DOE, J.  10001  1000001  DOE  JANE  3/1/1950  Mar-55  330  FO\n"
           "  2  ROE, J.  10002  1000002  ROE  JOHN  3/1/1991  Mar-56  330  CA\n")
    p = SEN.parse(old, 2026)  # the older list too
    assert [r["sen"] for r in p["rows"]] == [2] and p["rejects"] == [("bad-date", 2)]


def test_other_marks_are_read_and_a_missing_number_is_reported():
    """Review fix: a changed-number mark other than one leading '*' ('**', a dagger, '4*') still reads the row; a dated
    line under the header that is not a row is counted as not read ('no-match'), never skipped; a seniority number
    missing between 1 and the last one read is reported ('sen-gap', a note: the union list has no gaps)."""
    rows = [_r(1), "**" + _r(2, "Roe, John C.")[1:], "\u2020" + _r(3, "Poe, Mary L.")[1:],
            _r(4, "Moe, Kimo").replace("     4 ", "    4* ", 1), _r(5, "Loe, Lee"), _r(7, "Noe, Nina"),
            "x" + _r(8, "Zoe, Zed")[1:], " " * 27 + "Effective 1-Jul-26 (Rev. 2)"]  # a dated title: not a row
    p = SEN.parse(_page(rows), 2026)
    assert [r["sen"] for r in p["rows"]] == [1, 2, 3, 4, 5, 7]
    assert p["rejects"] == [("sen-gap", 11), ("no-match", 12)]
    d = SEN.to_json(p, "s.pdf", "2026-11-14T09:00:00-10:00")
    assert (d["count"], d["rejects"], d["notes"]) == (6, 1, {"sen-gap": 1})
    assert SEN.parse(hal_text(), 2026)["rejects"] == []  # a list numbered 1..n has no gap


def test_the_union_lists_end_words_do_not_end_an_old_layout_list():
    """Review fix: 'removed from the list' and 'STATUS LEGEND' end the rows of a union list only; an older SEN / EMP /
    DOH list with such a line mid page reads every row as 1.7.5 did."""
    hdr = "SEN   NAME, Initial   EMP #   ALPA #   LAST NAME   FIRST NAME   DOH   DOR   EQUIP   SEAT\n"
    r1 = "  1  DOE, J.  10001  1000001  DOE  JANE  3/1/1990  Mar-55  330  FO\n"
    r2 = "  2  ROE, J.  10002  1000002  ROE  JOHN  3/1/1991  Mar-56  330  CA\n"
    for mid in ("STATUS LEGEND: CA captain, FO first officer\n", "Pilots removed from the list this month: none\n",
                "Employee #  Name\n"):
        p = SEN.parse(hdr + r1 + mid + r2, 2026)
        assert [r["sen"] for r in p["rows"]] == [1, 2] and p["rejects"] == [], mid


def test_a_union_list_in_another_column_order_is_refused_with_its_own_rule(tmp_path, monkeypatch):
    """Review fix: the refusal names the union list's column order, not the older list's EMP # / ALPA # rule."""
    swapped = "*   Sen #     Employee #      Name                    DOH      Remarks"
    text = "\n".join(_title(28) + [swapped] + [_row(r, 0) for r in PAGE1]) + "\n"
    assert {x for x, _ in SEN.parse(text, 2026)["rejects"]} == {"header-order-hal"}
    r = _up(tmp_path, monkeypatch, text)
    assert not r["ok"] and "Sen #, Name, Employee #, DOH, Remarks in that order" in r["message"]
    assert "ALPA" not in r["message"] and not (tmp_path / "seniority.json").exists()


@pytest.mark.parametrize("junk", ["removed from the " * 6000, "Sen # Employee " * 6000, "SEN EMP " * 6000,
                                  "*   Sen #   Name" + " " * 100000, "  12" + " " * 100000 + "x"])
def test_a_long_line_fails_fast(junk):
    """Review fix: a line longer than MAX_LINE is set aside before the section, header and end checks (a 100 KB line
    took seconds; a 1 MB one would take minutes in the upload lock); a numbered one is counted ('too-long')."""
    t = time.perf_counter()
    p = SEN.parse(_header(0) + "\n" + junk + "\n", 2026)
    SEN.list_date(junk + "\n")
    assert time.perf_counter() - t < 0.5 and p["rows"] == []
    assert [x for x, _ in p["rejects"]] == (["too-long"] if junk.startswith("  12") else [])


def test_blank_lines_fail_fast():
    """Review fix: the header search in the cover text no longer spans lines (2,000 blank lines took 12 s)."""
    t = time.perf_counter()
    SEN.list_date("\n" * 20000 + "x\n")
    SEN.parse(" \n" * 20000, 2026)
    assert time.perf_counter() - t < 0.5


def test_a_pilots_status_is_not_stored_and_the_files_are_private(tmp_path, monkeypatch):
    """Review fix: nothing reads a pilot's Remarks code (SLOA is sick leave, MLOA military leave), so seniority.json
    keeps only the count per code; the seniority files are readable by this app only, as the contact list is."""
    import os
    import stat
    mask = os.umask(0o022)
    try:
        assert _up(tmp_path, monkeypatch, hal_text())["ok"]
        d = json.loads((tmp_path / "seniority.json").read_text())
        assert all("status" not in v for v in d["pilots"].values())
        assert d["statuses"] == {"A": 4, "ALPA": 1, "EXEC": 1, "FUR": 1, "LOA": 1, "MLOA": 1, "MRET": 1, "PESL": 1,
                                 "SLOA": 1}
        blocks = ["A332FO PBS BIDLINE AWARD"] + [f"{i:05d} / {20000 + i}   ROE{chr(65 + i % 26)}, JOHN    DOH 01/{i:02d}/95"
                                                 for i in range(1, 27)]
        (tmp_path / "2026-12_award.txt").write_text("\n".join(blocks) + "\n")
        info = web.award_seniority(str(tmp_path / "2026-12_award.txt"), "2026-12", "2026-12_award.pdf",
                                   "2026-11-20T09:00:00-10:00")
        assert info["decision"] == "on-top"
        modes = {f.name: stat.S_IMODE(f.stat().st_mode) for f in tmp_path.iterdir() if "seniority" in f.name}
        # 1.7.7: seniority.md (the markdown reference) is written beside seniority.json, private like it
        assert sorted(modes) == ["seniority.json", "seniority.md", "seniority_2026-11-14.pdf", "seniority_2026-11-14.txt",
                                 "seniority_award.json", "seniority_list.json"]
        assert set(modes.values()) == {0o600}, modes
    finally:
        os.umask(mask)


def test_a_row_read_with_a_note_is_not_a_line_not_read(tmp_path, monkeypatch):
    """Review fix: 'lines not read' counts only lines that gave no pilot; a row read with a status code the legend does
    not list (or another note) is said apart, on the page and on the uploads card."""
    rows = [r if r[0] != 4 else (4, "Moe, Kimo", "10004", "8-May-89", "RET", True) for r in PAGE1]
    r = _up(tmp_path, monkeypatch, hal_text(pages=((rows, 0), (PAGE2, 3))))
    note = "1 row read with a status code the legend does not list"
    assert r["ok"] and ("12 pilots read, list date 2026-07-01, newest date of hire on it 2026-06-01 (0 lines not read; "
                        f"{note})") in r["message"]
    s = web.uploads_json("x")["seniority"]
    assert (s["rejects"], s["note"]) == (0, note)
    assert note in web._seniority_status()
    p = SEN.parse(hal_text(pages=((rows, 0), (PAGE2, 3))), 2026)
    assert [x for x, _ in p["rejects"]] == ["status-unknown"]  # parse still lists every reason


def test_the_name_lookup_takes_a_suffix_and_a_curly_apostrophe(W, tmp_path, monkeypatch):
    """Review fix: the union list prints 'Last Jr., First', so the lookup compares last names without Jr / Sr / II
    ('Doe, Robert' finds 'Doe Jr., Robert K.'), and takes the apostrophe a phone types (O\u2019Doe)."""
    _list_on_file(W, tmp_path, monkeypatch)
    assert [h["name"] for h in W.name_lookup("Doe, Robert")[0]] == ["Doe Jr., Robert K."]
    assert [h["name"] for h in W.name_lookup("Doe")[0]] == ["Doe Jr., Robert K.", "Doe, Jane A."]
    assert [h["name"] for h in W.name_lookup("Doe Jr., Rob")[0]] == ["Doe Jr., Robert K."]
    assert [h["name"] for h in W.name_lookup("O\u2019Doe")[0]] == ["O'Doe, Sean P."]
    assert [h["name"] for h in W.name_lookup("O'Doe, Sean")[0]] == ["O'Doe, Sean P."]
    assert W.name_lookup("Do*")[0] == []  # still letters only
