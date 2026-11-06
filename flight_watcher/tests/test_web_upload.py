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
