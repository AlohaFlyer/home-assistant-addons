import logging

import web


def _mp(fields, pdf):
    b = "XyZb"
    parts = [f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode() for k, v in fields.items()]
    parts.append(f'--{b}\r\nContent-Disposition: form-data; name="pdf"; filename="a.pdf"\r\nContent-Type: application/pdf\r\n\r\n'.encode() + pdf + b"\r\n")
    return f"multipart/form-data; boundary={b}", b"".join(parts) + f"--{b}--\r\n".encode()


def test_upload_saves_pdf(tmp_path, monkeypatch):
    monkeypatch.setattr(web, "UPLOAD_DIR", str(tmp_path))
    ct, body = _mp({"month": "2026-12", "kind": "pairings"}, b"%PDF-1.4 fake")
    msg = web._save_upload(ct, body, logging.getLogger("t"))
    assert "Saved 2026-12_pairings.pdf" in msg
    assert (tmp_path / "2026-12_pairings.pdf").read_bytes() == b"%PDF-1.4 fake"
    assert "2026-12_pairings.pdf" in web._uploads_table()


def test_upload_rejects(tmp_path, monkeypatch):
    monkeypatch.setattr(web, "UPLOAD_DIR", str(tmp_path))
    ct, body = _mp({"month": "2026-12", "kind": "award"}, b"not a pdf")
    assert "not a PDF" in web._save_upload(ct, body, logging.getLogger("t"))
    ct, body = _mp({"month": "12/2026", "kind": "award"}, b"%PDF")
    assert "Pick a month" in web._save_upload(ct, body, logging.getLogger("t"))
    ct, body = _mp({"month": "", "kind": "pairings"}, b"%PDF")  # the month box is optional now, not for a package
    assert "Pick a month" in web._save_upload(ct, body, logging.getLogger("t"))
    ct, body = _mp({"month": "2026-12", "kind": "roster"}, b"%PDF")
    assert "Pick a month" in web._save_upload(ct, body, logging.getLogger("t"))


def _fake_pdftotext(text):
    def run(cmd, check=True, timeout=None):
        assert cmd[:2] == ["pdftotext", "-layout"]
        open(cmd[3], "w", encoding="utf-8").write(text)
    return run


def test_upload_seniority_list(tmp_path, monkeypatch, fx, caplog):
    """FW-0062: kind 'seniority' needs no month; saved as seniority_<HST day>.pdf with its text copy and parsed at once
    into seniority.json, shared by every pilot instance. The page says how many pilots were read and the list date;
    the log has counts only (made-up list)."""
    import datetime as dt
    import json
    monkeypatch.setattr(web, "UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(web, "_hst_now", lambda: dt.datetime(2026, 11, 6, 9, 30, tzinfo=dt.timezone(dt.timedelta(hours=-10))))
    monkeypatch.setattr(web.subprocess, "run", _fake_pdftotext(fx("seniority_synthetic.txt")))
    assert "No pilot seniority list on file" in web._seniority_status()
    ct, body = _mp({"month": "", "kind": "seniority", "list_date": "2026-03-01"}, b"%PDF-1.4 fake")
    with caplog.at_level(logging.INFO):
        msg = web._save_upload(ct, body, logging.getLogger("t"))
    assert "Saved seniority_2026-11-06.pdf" in msg and "12 pilots read, list date 2026-03-01" in msg and "class='ok'" in msg
    assert (tmp_path / "seniority_2026-11-06.pdf").exists() and (tmp_path / "seniority_2026-11-06.txt").exists()
    d = json.loads((tmp_path / "seniority.json").read_text())
    assert (d["count"], d["list_date"], d["file"], d["uploaded_at"]) == (12, "2026-03-01", "seniority_2026-11-06.pdf", "2026-11-06T09:30:00-10:00")
    assert d["pilots"]["901"]["doh"] == "1988-05-01"
    assert "seniority list read, 12 pilots" in caplog.text and "Doe" not in caplog.text and "1988" not in caplog.text
    st = web._seniority_status()
    assert "Seniority list on file: 12 pilots read, list date 2026-03-01" in st and "2026-11-06 09:30 HST" in st
    assert "seniority_2026-11-06.pdf" in web._uploads_table()
    # no list date typed and none in the file: said so; a month typed in the Month box is not used
    ct, body = _mp({"month": "2026-12", "kind": "seniority"}, b"%PDF-1.4 fake")
    assert "no list date in the file" in web._save_upload(ct, body, logging.getLogger("t"))
    assert json.loads((tmp_path / "seniority.json").read_text())["list_date"] == ""
    # a PDF that is not the list: refused, the list on file kept
    monkeypatch.setattr(web.subprocess, "run", _fake_pdftotext("Minutes of the March meeting\n"))
    msg = web._save_upload(ct, body, logging.getLogger("t"))
    assert "No pilot rows were found" in msg and "class='err'" in msg
    assert json.loads((tmp_path / "seniority.json").read_text())["count"] == 12


def test_upload_page_offers_the_seniority_list():
    assert '<option value="seniority">Pilot seniority list</option>' in web.PAGE and 'name="list_date"' in web.PAGE
    assert '<input type="month" name="month" value="{month}">' in web.PAGE  # not required: the list has no month
