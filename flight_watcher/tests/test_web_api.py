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
    monkeypatch.setattr(web, "PAIRINGS_DIR", str(tmp_path / "www"))  # no pairing file on file
    monkeypatch.setattr(web, "CONTACTS_FILE", str(tmp_path / "contacts.json"))
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
    assert json.loads(data) == {"files": [], "seniority": None, "contacts": None, "version": "9.9.9",
                                "max_bytes": web.INGRESS_MAX, "mqtt_max_bytes": web.UPLOAD_MAX,
                                "wanted": [{"kind": "pairings", "month": "2026-10", "why": "previous"},
                                           {"kind": "pairings", "month": "2026-11", "why": "current"}]}
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


def test_the_advertised_limit_is_what_ingress_lets_through(srv):
    """1.4.5 review fix: the Supervisor's ingress proxy refuses a body over 16 MiB (MAX_CLIENT_SIZE = 1024**2 * 16,
    read whole without ingress_stream) with HTTP 413 after it has all arrived. api/uploads advertises that less 64 KiB
    for the form, and the card refuses a larger PDF before sending it; the app's own 25 MB check stays the hard cap."""
    import os
    import re
    assert web.INGRESS_MAX == 16 * 1024 * 1024 - 64 * 1024 < web.UPLOAD_MAX
    assert json.loads(_req(srv, "GET", "/api/uploads")[2])["max_bytes"] == web.INGRESS_MAX
    card = open(os.path.join(os.path.dirname(web.__file__), "www", "flight-watcher-uploads-card.js"), encoding="utf-8").read()
    m = re.search(r"^const FW_UP_MAX = (16 \* 1024 \* 1024 - 64 \* 1024);", card, re.M)
    assert m and eval(m.group(1)) == web.INGRESS_MAX  # the card's fallback is the same figure
    st, _, page = _req(srv, "GET", "/")  # the Web UI page says so too
    assert st == 200 and "Home Assistant's app proxy takes a PDF of up to 15.9 MB." in " ".join(page.decode().split())
    # not ingress_stream: the Supervisor would then send the body chunked, and this server reads Content-Length
    assert "ingress_stream" not in open(os.path.join(os.path.dirname(web.__file__), "config.yaml")).read()


def test_an_unreadable_pdf_is_refused_over_the_api(srv, tmp_path, monkeypatch):
    """1.4.5 review fix, through api/upload: a PDF with no text copy answers 400 ok:false and the month's good PDF and
    text copy stay, so api/uploads still says read only for the file that was read (made-up files)."""
    import subprocess
    assert json.loads(_post(srv, {"kind": "award", "month": "2026-12"}, b"%PDF-1.4 good")[2])["ok"]

    def exit1(cmd, check=True, timeout=None):
        raise subprocess.CalledProcessError(1, cmd)
    monkeypatch.setattr(web.subprocess, "run", exit1)
    st, _, data = _post(srv, {"kind": "award", "month": "2026-12"}, b"%PDF-1.4 truncated")
    r = json.loads(data)
    assert st == 400 and not r["ok"] and r["message"].endswith("the 2026-12 award on file is kept.") and "file" not in r
    assert (tmp_path / "2026-12_award.pdf").read_bytes() == b"%PDF-1.4 good"
    d = json.loads(_req(srv, "GET", "/api/uploads")[2])
    assert [(f["name"], f["size"], f["has_text"]) for f in d["files"]] == [("2026-12_award.pdf", 13, True)]
    assert not [f for f in tmp_path.iterdir() if ".new." in f.name]


def test_wanted_pairings_packages(srv, tmp_path):
    """FW-0057 (1.4.7 verify): api/uploads names the pairings packages the crew index still needs, this bid month's and
    the previous one's (trips other pilots started in October that run into November), while neither the pairing file
    nor an upload of it is on file, never before the crew index's first bid month (crewidx.CREW_FROM)."""
    www = tmp_path / "www"
    www.mkdir()
    (www / "pairings_2026-11.json").write_text("{}")  # November's package was read
    d = json.loads(_req(srv, "GET", "/api/uploads")[2])
    assert d["wanted"] == [{"kind": "pairings", "month": "2026-10", "why": "previous"}]
    assert _post(srv, {"kind": "pairings", "month": "2026-10"})[0] == 200  # uploaded: no longer asked for
    assert json.loads(_req(srv, "GET", "/api/uploads")[2])["wanted"] == []
    (tmp_path / "2026-10_pairings.pdf").unlink()
    (www / "pairings_2026-10.json").write_text("{}")  # the Watcher wrote its pairing file
    assert web.uploads_wanted(dt.date(2026, 11, 20), str(www)) == []
    assert web.uploads_wanted(dt.date(2026, 12, 2), str(www)) == [{"kind": "pairings", "month": "2026-12", "why": "current"}]
    assert web.uploads_wanted(dt.date(2027, 1, 5), str(www)) == [
        {"kind": "pairings", "month": "2026-12", "why": "previous"}, {"kind": "pairings", "month": "2027-01", "why": "current"}]
    # before the crew index starts (CREW_FROM, Oct 31 2026): September is never asked for
    assert web.uploads_wanted(dt.date(2026, 10, 20), str(tmp_path / "none")) == [
        {"kind": "pairings", "month": "2026-10", "why": "current"}]
