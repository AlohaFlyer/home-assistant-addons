"""1.4.5: the Web UI's JSON endpoints for the dashboard uploads card, on a real server: GET api/uploads and POST
api/upload (the page's multipart form, its checks and limits), ingress-only like the page. Made-up PDFs and text."""
import datetime as dt
import http.client
import json
import logging
import socket

import pytest

import web
from test_web_upload import _fake_pdftotext, _mp

HST = dt.timezone(dt.timedelta(hours=-10))


class _Store:
    def recent_finds(self, n):
        return []

    def recent_matches(self, n):
        return []


@pytest.fixture
def srv(tmp_path, monkeypatch, fx):
    monkeypatch.setattr(web, "UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(web, "_hst_now", lambda: dt.datetime(2026, 11, 20, 9, 30, tzinfo=HST))
    monkeypatch.setattr(web.subprocess, "run", _fake_pdftotext(fx("award_packet_synthetic.txt")))
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = web.serve(port, "9.9.9", lambda: [], lambda d: [], _Store(), logging.getLogger("t"))
    yield port
    server.shutdown()
    server.server_close()


def _req(port, method, path, body=None, headers=None, source="127.0.0.1"):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10, source_address=(source, 0))
    c.request(method, path, body=body, headers=headers or {})
    r = c.getresponse()
    data = r.read()
    c.close()
    return r.status, r.getheader("Content-Type") or "", data


def _post(port, fields, pdf=b"%PDF-1.4 fake", path="/api/upload", **kw):
    ct, body = _mp(fields, pdf)
    return _req(port, "POST", path, body, {"Content-Type": ct, "Content-Length": str(len(body))}, **kw)


def test_uploads_list_and_upload(srv, tmp_path):
    st, ct, data = _req(srv, "GET", "/api/uploads")
    assert st == 200 and ct.startswith("application/json")
    assert json.loads(data) == {"files": [], "seniority": None, "version": "9.9.9", "max_bytes": web.UPLOAD_MAX}
    st, ct, data = _post(srv, {"kind": "pairings", "month": "2026-12"})
    r = json.loads(data)
    assert (st, r["ok"], r["file"], r["message"]) == (200, True, "2026-12_pairings.pdf", "Saved 2026-12_pairings.pdf (0 KB).")
    st, _, data = _post(srv, {"kind": "award", "month": "2026-12"})  # read for dates of hire too
    r = json.loads(data)
    assert st == 200 and r["ok"] and "Dates of hire: 30 pilots read from its seniority section" in r["message"]
    assert r["seniority"]["decision"] == "on-top" and r["seniority"]["view"]["pilots"] == 30
    d = json.loads(_req(srv, "GET", "/api/uploads/")[2])  # a trailing slash is the same
    assert [(f["name"], f["kind"], f["month"], f["size"], f["has_text"]) for f in sorted(d["files"], key=lambda f: f["name"])] == [
        ("2026-12_award.pdf", "award", "2026-12", 13, True), ("2026-12_pairings.pdf", "pairings", "2026-12", 13, True)]
    assert all(f["uploaded_at"].endswith("-10:00") for f in d["files"])
    s = d["seniority"]
    assert (s["pilots"], s["source"], s["as_of"], s["file"], s["list_date"], s["carried"]) == (
        30, "award 2026-12", "2026-12-01", "2026-12_award.pdf", "", 0)
    assert "pilots" not in json.dumps(s["base"] or {}) and "Doe" not in json.dumps(d)  # counts and dates, no pilot
    # a seniority list (no month) through the same endpoint
    st, _, data = _post(srv, {"kind": "seniority", "month": "", "list_date": "2027-01-15"})
    r = json.loads(data)  # the award text has a seniority section in the list's layout: it reads as a list too
    assert st == 200 and r["ok"] and r["file"] == "seniority_2026-11-20.pdf" and "30 pilots read, list date 2027-01-15" in r["message"]
    d = json.loads(_req(srv, "GET", "/api/uploads")[2])
    assert d["seniority"]["source"] == "list" and {f["kind"] for f in d["files"]} == {"award", "pairings", "seniority"}
    assert [f["day"] for f in d["files"] if f["kind"] == "seniority"] == ["2026-11-20"]


def test_refused_uploads(srv, tmp_path, monkeypatch):
    for fields, pdf, msg in (({"kind": "award", "month": "2026-12"}, b"not a pdf", "That file is not a PDF."),
                             ({"kind": "award", "month": "12/2026"}, b"%PDF", "Pick a month and a kind."),
                             ({"kind": "roster", "month": "2026-12"}, b"%PDF", "Pick a month and a kind.")):
        st, ct, data = _post(srv, fields, pdf)
        assert (st, json.loads(data)) == (400, {"ok": False, "message": msg}) and ct.startswith("application/json")
    st, _, data = _req(srv, "POST", "/api/upload", b"kind=award", {"Content-Type": "application/x-www-form-urlencoded"})
    assert (st, json.loads(data)["message"]) == (400, "Send the PDF as a multipart form.")
    monkeypatch.setattr(web, "UPLOAD_MAX", 100)
    st, _, data = _post(srv, {"kind": "award", "month": "2026-12"}, b"%PDF" + b"x" * 200)
    assert (st, json.loads(data)) == (413, {"ok": False, "message": "File too large (0 MB max)."})
    st, _, data = _req(srv, "POST", "/api/uploads", b"", {"Content-Type": "multipart/form-data; boundary=x"})
    assert st == 404 and not json.loads(data)["ok"]  # an unknown api path is never taken for the rules form
    assert _req(srv, "GET", "/api/other")[0] == 404
    assert not [f for f in tmp_path.iterdir() if f.suffix == ".pdf"]


def test_only_the_ingress_proxy_may_connect(srv, tmp_path):
    """Any client other than the Supervisor's ingress proxy (172.30.32.2) or the app itself is refused, the JSON
    endpoints like the page (here a second loopback address stands in for another host)."""
    try:
        with socket.socket() as s:
            s.bind(("127.0.0.2", 0))
    except OSError:
        pytest.skip("no second loopback address on this host")
    for method, path in (("GET", "/api/uploads"), ("GET", "/")):
        assert _req(srv, method, path, source="127.0.0.2")[0] == 403
    assert _post(srv, {"kind": "pairings", "month": "2026-12"}, source="127.0.0.2")[0] == 403
    assert not list(tmp_path.iterdir())


def test_the_page_still_uploads(srv, tmp_path):
    st, ct, data = _post(srv, {"kind": "pairings", "month": "2026-12"}, path="/upload")
    assert st == 200 and ct.startswith("text/html") and b"<p class='ok'>Saved 2026-12_pairings.pdf (0 KB).</p>" in data
    st, _, data = _req(srv, "GET", "/")
    assert st == 200 and b"2026-12_pairings.pdf" in data and b"Monthly PDFs" in data
