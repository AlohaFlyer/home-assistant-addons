import logging

import web


def _mp(fields, pdf):
    b = "XyZb"
    parts = [f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode() for k, v in fields.items()]
    parts.append(f'--{b}\r\nContent-Disposition: form-data; name="pdf"; filename="a.pdf"\r\nContent-Type: application/pdf\r\n\r\n'.encode() + pdf + b"\r\n")
    return f"multipart/form-data; boundary={b}", b"".join(parts) + f"--{b}--\r\n".encode()


def test_upload_saves_pdf(tmp_path, monkeypatch):
    monkeypatch.setattr(web, "UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(web.subprocess, "run", _fake_pdftotext("PAIRINGS\n"))
    ct, body = _mp({"month": "2026-12", "kind": "pairings"}, b"%PDF-1.4 fake")
    msg = web._save_upload(ct, body, logging.getLogger("t"))
    assert "Saved 2026-12_pairings.pdf" in msg
    assert (tmp_path / "2026-12_pairings.pdf").read_bytes() == b"%PDF-1.4 fake"
    assert (tmp_path / "2026-12_pairings.txt").read_text() == "PAIRINGS\n"
    assert "2026-12_pairings.pdf" in web._uploads_table()
    assert sorted(f.name for f in tmp_path.iterdir()) == ["2026-12_pairings.pdf", "2026-12_pairings.txt"]  # no .new.*


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
    assert "No pilot rows were found" in msg and "class='err'" in msg and "Not kept" in msg
    assert json.loads((tmp_path / "seniority.json").read_text())["count"] == 12


def test_a_refused_seniority_upload_leaves_the_list_on_file(tmp_path, monkeypatch, fx):
    """Review fix: a refused upload (no pilot rows, a header in another column order, no text copy) is read under a
    temporary name and deleted, so the list on file keeps its PDF and text copy, on the same HST day or a later one;
    seniority.json and the page still name the real list (made-up list)."""
    import datetime as dt
    import json
    day = [dt.datetime(2026, 11, 6, 9, 30, tzinfo=dt.timezone(dt.timedelta(hours=-10)))]
    monkeypatch.setattr(web, "UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(web, "_hst_now", lambda: day[0])
    monkeypatch.setattr(web.subprocess, "run", _fake_pdftotext(fx("seniority_synthetic.txt")))
    ct, body = _mp({"month": "", "kind": "seniority", "list_date": "2026-03-01"}, b"%PDF-1.4 the real list")
    assert "12 pilots read" in web._save_upload(ct, body, logging.getLogger("t"))
    good_txt = (tmp_path / "seniority_2026-11-06.txt").read_text()
    wrong = _mp({"month": "", "kind": "seniority"}, b"%PDF-1.4 the wrong file")
    hdr = "SEN   NAME, Initial   ALPA #   EMP #   LAST NAME   FIRST NAME   DOH   DOR   EQUIP   SEAT\n"
    for when in (6, 7):  # the same HST day, then the next one
        day[0] = day[0].replace(day=when)
        for text, why in (("Minutes of the March meeting\n", "No pilot rows were found"),
                          ("SENIORITY\n" + hdr + "  1   DOE, J.   990001   901   DOE   JANE   5/1/1988   May-28 330 CA\n",
                           "order this version does not read")):
            monkeypatch.setattr(web.subprocess, "run", _fake_pdftotext(text))
            msg = web._save_upload(*wrong, logging.getLogger("t"))
            assert why in msg and "Not kept" in msg and "the list on file is kept" in msg and "class='err'" in msg
        def fail(cmd, check=True, timeout=None):
            raise OSError("pdftotext missing")
        monkeypatch.setattr(web.subprocess, "run", fail)
        assert "gave no text copy" in web._save_upload(*wrong, logging.getLogger("t"))
    assert sorted(f.name for f in tmp_path.iterdir()) == ["seniority.json", "seniority_2026-11-06.pdf", "seniority_2026-11-06.txt"]
    assert (tmp_path / "seniority_2026-11-06.pdf").read_bytes() == b"%PDF-1.4 the real list"
    assert (tmp_path / "seniority_2026-11-06.txt").read_text() == good_txt
    d = json.loads((tmp_path / "seniority.json").read_text())
    assert (d["count"], d["file"], d["list_date"]) == (12, "seniority_2026-11-06.pdf", "2026-03-01")
    assert "(seniority_2026-11-06.pdf)" in web._seniority_status()
    # a good list on a later day replaces it under its own day's name
    monkeypatch.setattr(web.subprocess, "run", _fake_pdftotext(fx("seniority_synthetic.txt")))
    assert "Saved seniority_2026-11-07.pdf" in web._save_upload(*wrong, logging.getLogger("t"))
    assert json.loads((tmp_path / "seniority.json").read_text())["file"] == "seniority_2026-11-07.pdf"
    assert not [f for f in tmp_path.iterdir() if ".new." in f.name]


def test_upload_page_offers_the_seniority_list():
    assert '<option value="seniority">Pilot seniority list</option>' in web.PAGE and 'name="list_date"' in web.PAGE
    assert '<input type="month" name="month" value="{month}">' in web.PAGE  # not required: the list has no month


def test_an_unreadable_award_or_package_keeps_the_file_on_file(tmp_path, monkeypatch, fx, caplog):
    """1.4.5 review fix: an award or pairings package that gives no text copy (truncated, password-protected: pdftotext
    exits 1) is staged under <month>_<kind>.new.pdf and refused, so the good PDF and its text copy on file stay, the
    list says read only for a file that was read, and the dates of hire from the good award stay. The real pdftotext
    reads the broken bytes when it is installed (made-up files)."""
    import json
    import shutil
    import subprocess
    real_run = subprocess.run
    monkeypatch.setattr(web, "UPLOAD_DIR", str(tmp_path))
    log = logging.getLogger("t")
    good = fx("award_packet_synthetic.txt")
    monkeypatch.setattr(web.subprocess, "run", _fake_pdftotext(good))
    for kind in ("award", "pairings"):
        assert web.upload_result(*_mp({"month": "2026-12", "kind": kind}, b"%PDF-1.4 good " + kind.encode()), log)["ok"]
    before = {f.name: f.read_bytes() for f in tmp_path.iterdir()}
    assert "seniority.json" in before and "2026-12_award.txt" in before

    def exit1(cmd, check=True, timeout=None):
        raise subprocess.CalledProcessError(1, cmd)
    fails = [exit1]
    if shutil.which("pdftotext"):
        fails.append(real_run)  # the real tool on a truncated PDF
    for run in fails:
        monkeypatch.setattr(web.subprocess, "run", run)
        for kind, what in (("award", "award"), ("pairings", "pairings package")):
            with caplog.at_level(logging.INFO):
                r = web.upload_result(*_mp({"month": "2026-12", "kind": kind}, b"%PDF-1.4 truncated"), log)
            assert r == {"ok": False, "message": f"Not kept: 2026-12_{kind}.pdf (0 KB) gave no text copy (pdftotext exit 1: "
                         f"damaged or password-protected PDF?), so the Watcher cannot read it; the 2026-12 {what} on file is kept."}
            assert "class='err'" in web._save_upload(*_mp({"month": "2026-12", "kind": kind}, b"%PDF-1.4 truncated"), log)
        assert {f.name: f.read_bytes() for f in tmp_path.iterdir()} == before  # PDFs, text copies, seniority.json
    assert [(f["name"], f["has_text"]) for f in sorted(web.uploads_list(), key=lambda f: f["name"])] == [
        ("2026-12_award.pdf", True), ("2026-12_pairings.pdf", True)]
    assert json.loads(before["seniority.json"])["count"] == 30 and "gave no text copy; not kept" in caplog.text
    # nothing on file for that month yet: nothing is saved, no PDF without its text copy is left
    monkeypatch.setattr(web.subprocess, "run", exit1)
    r = web.upload_result(*_mp({"month": "2027-01", "kind": "award"}, b"%PDF-1.4 truncated"), log)
    assert not r["ok"] and r["message"].endswith("so the Watcher cannot read it; nothing was saved.")
    assert {f.name for f in tmp_path.iterdir()} == set(before)
    # a timeout says so; still nothing kept
    def slow(cmd, check=True, timeout=None):
        raise subprocess.TimeoutExpired(cmd, timeout)
    monkeypatch.setattr(web.subprocess, "run", slow)
    assert "(pdftotext took over 2 minutes)" in web.upload_result(*_mp({"month": "2026-12", "kind": "award"}, b"%PDF"), log)["message"]
    assert {f.name: f.read_bytes() for f in tmp_path.iterdir()} == before
