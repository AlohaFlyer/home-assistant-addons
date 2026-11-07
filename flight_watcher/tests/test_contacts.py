"""FW-0066 (1.4.8): the pilot contact list (contacts.py and web._save_contacts). Synthetic lists only: made-up names
("Doe, Jane"), 555-01xx numbers and example.com addresses. PDF text as pdftotext -layout gives it, CSV and XLSX as a
crew office export might lay them out; the file type is read from the bytes; contacts.json and the kept file are
mode 600; the result and the log carry counts only."""
import io
import json
import logging
import os
import stat
import zipfile
from datetime import datetime, timedelta, timezone

import pytest

import contacts as CT
import web
from test_web_upload import _fake_pdftotext

PDF_TEXT = """                     HNL A330 PILOT CONTACT LIST                      Updated 11/01/2026
SEN   EMP #   NAME                     CELL            HOME            EMAIL
  1   10001   DOE, JANE A              808-555-0101    (808) 555-0102  jane.doe@example.com
  2   10002   ROE, RICK                C: 808.555.0103                 rick.roe@example.com
  3   10003   POE, PAT                 Fax 808-555-0199
  4   10004   SMITH-JONES, ALEX        +1 808 555 0104
                                       alex.sj@example.com
  5   10005   VAN DYKE, SAM            H 8085550105    DOH 03/15/2001
  6   10006   O'NEIL, KIM              kim.oneil@example.com
              808-555-0106
  7   10008   LEE, ANN M 808-555-0108
Page 1 of 1     orphan line 808-555-0107
"""


def test_pdf_text_layout():
    r = CT.parse(b"%PDF", "pdf", PDF_TEXT)
    by = {e["emp"]: e for e in r["entries"]}
    assert sorted(by) == ["10001", "10002", "10004", "10005", "10006", "10008"]  # Poe has only a fax: skipped
    assert by["10008"]["name"] == "Lee, Ann" and by["10008"]["phones"][0]["label"] == "phone"  # M: an initial, no label
    assert r["skipped"] == 1 and r["rejects"] == 1  # the orphan number on the page footer is not anyone's
    j = by["10001"]
    assert j["name"] == "Doe, Jane"
    assert j["phones"] == [{"label": "phone", "number": "808-555-0101", "tel": "+18085550101"},
                           {"label": "phone", "number": "808-555-0102", "tel": "+18085550102"}]
    assert j["emails"] == ["jane.doe@example.com"]
    assert by["10002"]["phones"] == [{"label": "cell", "number": "808-555-0103", "tel": "+18085550103"}]
    assert by["10004"]["name"] == "Smith-Jones, Alex" and by["10004"]["emails"] == ["alex.sj@example.com"]  # wrapped
    assert by["10004"]["phones"][0]["tel"] == "+18085550104"
    assert by["10005"]["name"] == "Van Dyke, Sam" and by["10005"]["phones"][0]["label"] == "home"  # the DOH is no emp
    assert by["10006"]["name"] == "O'Neil, Kim" and by["10006"]["phones"][0]["tel"] == "+18085550106"


CSV = ("﻿Last Name,First Name,Emp #,Cell Phone,Home Phone,Fax,E-mail\r\n"
       "Doe,Jane,10001,808-555-0111,,808-555-0198,jane.doe@example.com\r\n"
       "Roe,Rick,10002,(808) 555-0112,808 555 0113,,\r\n"
       "Poe,Pat,10003,,,808-555-0197,\r\n"
       ",,,808-555-0114,,,\r\n"
       "Zoe,Ann,010007,8085550115,,,ann.zoe@example.com; ann2@example.com\r\n")


def test_csv_with_a_header():
    r = CT.parse(CSV.encode("utf-8"), "csv")
    by = {e["emp"]: e for e in r["entries"]}
    assert sorted(by) == ["010007", "10001", "10002"] and r["skipped"] == 1 and r["rejects"] == 1
    assert by["10001"] == {"emp": "10001", "name": "Doe, Jane", "emails": ["jane.doe@example.com"],
                           "phones": [{"label": "cell", "number": "808-555-0111", "tel": "+18085550111"}]}  # no fax
    assert [p["label"] for p in by["10002"]["phones"]] == ["cell", "home"]
    assert by["010007"]["emails"] == ["ann.zoe@example.com", "ann2@example.com"]


def test_csv_semicolons_full_names_and_no_header():
    semi = "Pilot;Employee Number;Mobile;Email\nJane Doe;10001;808-555-0121;jane.doe@example.com\nRoe, Rick;10002;808-555-0122;\n"
    r = CT.parse(semi.encode("cp1252"), "csv")
    assert [(e["emp"], e["name"], e["phones"][0]["tel"]) for e in r["entries"]] == [
        ("10001", "Doe, Jane", "+18085550121"), ("10002", "Roe, Rick", "+18085550122")]
    bare = "10001,Doe, Jane,808-555-0131\n10002,Roe, Rick,808-555-0132,rick.roe@example.com\n"  # no header: read as lines
    r = CT.parse(bare.encode(), "csv")
    assert [(e["emp"], e["name"]) for e in r["entries"]] == [("10001", "Doe, Jane"), ("10002", "Roe, Rick")]


class Num(str):
    """A cell Excel stores as a number, written as it is (a phone typed as a number can come out in E notation)."""


def _xlsx(rows, inline=False):
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    shared, sx = [], []

    def cell(r, c, v):
        ref = f"{chr(65 + c)}{r + 1}"
        if isinstance(v, (int, float, Num)):
            return f'<c r="{ref}"><v>{v}</v></c>'
        if inline:
            return f'<c r="{ref}" t="inlineStr"><is><t>{v}</t></is></c>'
        shared.append(v)
        return f'<c r="{ref}" t="s"><v>{len(shared) - 1}</v></c>'
    body = "".join(f'<row r="{r + 1}">' + "".join(cell(r, c, v) for c, v in enumerate(row) if v != "") + "</row>"
                   for r, row in enumerate(rows))
    sx = "".join(f"<si><t>{v}</t></si>" for v in shared)
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("xl/workbook.xml", f'<workbook {ns} xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/'
                                      'relationships"><sheets><sheet name="Pilots" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
                                                 'relationships"><Relationship Id="rId1" Target="worksheets/sheet1.xml"/>'
                                                 '</Relationships>')
        z.writestr("xl/worksheets/sheet1.xml", f"<worksheet {ns}><sheetData>{body}</sheetData></worksheet>")
        z.writestr("xl/sharedStrings.xml", f"<sst {ns}>{sx}</sst>")
    return b.getvalue()


ROWS = [["HNL A330 pilots", "", "", ""], ["Name", "Emp", "Cell", "Email"],
        ["Doe, Jane", 10001, 8085550141, "jane.doe@example.com"], ["Roe, Rick", 10002, Num("8.085550142E9"), ""]]


@pytest.mark.parametrize("inline", [False, True])
def test_xlsx_first_sheet(inline):
    data = _xlsx(ROWS, inline)
    assert CT.sniff(data) == "xlsx"
    r = CT.parse(data, "xlsx")
    assert [(e["emp"], e["name"], [p["tel"] for p in e["phones"]], e["emails"]) for e in r["entries"]] == [
        ("10001", "Doe, Jane", ["+18085550141"], ["jane.doe@example.com"]), ("10002", "Roe, Rick", ["+18085550142"], [])]


def test_xlsx_refuses_a_dtd_and_a_zip_bomb(monkeypatch):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("xl/workbook.xml", "<workbook/>")
        z.writestr("xl/worksheets/sheet1.xml", '<!DOCTYPE x [<!ENTITY a "aaaa">]><worksheet>&a;</worksheet>')
    with pytest.raises(ValueError, match="DTD"):
        CT.parse(b.getvalue(), "xlsx")
    monkeypatch.setattr(CT, "XLSX_MAX", 100)
    with pytest.raises(ValueError, match="too large"):
        CT.parse(_xlsx(ROWS), "xlsx")


def test_sniff_reads_the_bytes_not_the_name():
    assert CT.sniff(b"%PDF-1.7 x") == "pdf"
    assert CT.sniff(CSV.encode()) == "csv"
    assert CT.sniff(b"just one line, no list") is None
    assert CT.sniff(b"a,b\x00\nc,d\n") is None  # binary
    assert CT.sniff(b"PK\x03\x04 not a zip") is None
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("word/document.xml", "<w/>")
    assert CT.sniff(b.getvalue()) is None  # a zip that is no workbook (a .docx)
    assert CT.sniff(b"") is None and CT.sniff(b"\xff\xfe\x00\x00") is None


def test_find_one_pilot():
    d = CT.build(CT.parse(b"%PDF", "pdf", PDF_TEXT), "contacts_2026-11-07.pdf", "2026-11-07T09:00:00-10:00")
    assert CT.find(d, "10001") == {"name": "Doe, Jane", "emails": ["jane.doe@example.com"],
                                   "phones": [{"label": "phone", "number": "808-555-0101", "tel": "+18085550101"},
                                              {"label": "phone", "number": "808-555-0102", "tel": "+18085550102"}]}
    assert CT.find(d, "99999", "DOE, JANE M")["name"] == "Doe, Jane"  # by name when the number is not on the list
    assert CT.find(d, "99999", "Nobody, Here") is None and CT.find(None, "10001") is None
    twice = dict(d, pilots=d["pilots"] + [{"emp": "20001", "name": "Doe, Jane", "phones": [], "emails": ["x@example.com"]}])
    assert CT.find(twice, "", "Doe, Jane") is None  # two pilots by that name: none is guessed
    assert CT.find_by_name(d, "doe, jane") == ("10001", "Doe, Jane") and CT.find_by_name(d, "Roe") == ("10002", "Roe, Rick")
    assert CT.find_by_name(twice, "Doe") is None and CT.find_by_name(d, "") is None
    s = CT.summary(d)
    assert s == {"count": 6, "with_phone": 6, "with_email": 4, "with_emp": 6, "rejects": 1,
                 "file": "contacts_2026-11-07.pdf", "uploaded_at": "2026-11-07T09:00:00-10:00"}
    assert "Doe" not in json.dumps(s) and "555" not in json.dumps(s)


HST = timezone(timedelta(hours=-10))


@pytest.fixture
def up(tmp_path, monkeypatch):
    d = tmp_path / "uploads"
    d.mkdir()
    monkeypatch.setattr(web, "UPLOAD_DIR", str(d))
    monkeypatch.setattr(web, "CONTACTS_FILE", str(tmp_path / "contacts.json"))
    monkeypatch.setattr(web, "LOCK_PATH", str(tmp_path / "lock"))
    monkeypatch.setattr(web, "_hst_now", lambda: datetime(2026, 11, 7, 9, 30, tzinfo=HST))
    return d


SECRETS = ("Doe", "Jane", "Roe", "555-01", "55501", "example.com", "jane.doe")


def test_save_contacts_csv_then_pdf_mode_600_counts_only(up, tmp_path, monkeypatch, caplog):
    log = logging.getLogger("t")
    with caplog.at_level(logging.INFO):
        r = web.save_upload({"kind": "contacts", "month": ""}, CSV.encode(), log)
    assert r["ok"] and r["file"] == "contacts_2026-11-07.csv"
    assert r["message"] == ("Saved contacts_2026-11-07.csv (0 KB). Pilot contacts: 3 pilots, 3 with a phone, 2 with an "
                            "email. 1 lines with a phone or email but no pilot were not read.")
    cf = tmp_path / "contacts.json"
    for p in (cf, up / "contacts_2026-11-07.csv"):
        assert stat.S_IMODE(os.stat(p).st_mode) == 0o600, p
    d = json.loads(cf.read_text())
    assert d["count"] == 3 and d["file"] == "contacts_2026-11-07.csv" and d["pilots"][0]["emp"] == "10001"
    files = web.uploads_list()
    assert [(f["name"], f["kind"], f["day"], f["has_text"]) for f in files] == [("contacts_2026-11-07.csv", "contacts", "2026-11-07", True)]
    assert web.uploads_json("1.4.8")["contacts"]["count"] == 3
    # a PDF list later the same day: the CSV goes, the PDF and its text copy stay (both 600)
    monkeypatch.setattr(web.subprocess, "run", _fake_pdftotext(PDF_TEXT))
    with caplog.at_level(logging.INFO):
        r = web.save_upload({"kind": "contacts"}, b"%PDF-1.4 synthetic", log)
    assert r["ok"] and r["file"] == "contacts_2026-11-07.pdf" and r["contacts"]["count"] == 6
    assert sorted(os.listdir(up)) == ["contacts_2026-11-07.pdf", "contacts_2026-11-07.txt"]
    for p in os.listdir(up):
        assert stat.S_IMODE(os.stat(up / p).st_mode) == 0o600, p
    # a file that is not a list: refused, the list on file kept
    monkeypatch.setattr(web.subprocess, "run", _fake_pdftotext("Minutes of the March meeting\n"))
    r = web.save_upload({"kind": "contacts"}, b"%PDF-1.4 other", log)
    assert not r["ok"] and "No pilot contacts were found" in r["message"] and "list on file is kept" in r["message"]
    assert sorted(os.listdir(up)) == ["contacts_2026-11-07.pdf", "contacts_2026-11-07.txt"]
    assert json.loads(cf.read_text())["count"] == 6
    r = web.save_upload({"kind": "contacts"}, b"\x89PNG\r\n\x1a\n", log)
    assert r == {"ok": False, "message": "That file is not a PDF, CSV or XLSX contact list."}
    for s in SECRETS:  # the log and the results: counts only
        assert s not in caplog.text, s
        assert s not in json.dumps(r)
    assert "pilot contact list read, 6 pilots" in caplog.text


def test_save_contacts_xlsx_through_the_web_ui_form(up, tmp_path):
    from test_web_upload import _mp
    ct, body = _mp({"kind": "contacts", "month": ""}, _xlsx(ROWS))
    r = web.upload_result(ct, body, logging.getLogger("t"))
    assert r["ok"] and r["file"] == "contacts_2026-11-07.xlsx" and r["contacts"]["count"] == 2
    assert "contacts_2026-11-07.xlsx" in web._uploads_table()
    assert 'value="contacts"' in web.PAGE
