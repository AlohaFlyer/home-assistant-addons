"""1.7.6 (Ryan, Nov 14: "you should be able to calculate their pay by looking at their date of hire and seniority. I
can upload the pilot list that has that data. Then you can keep that in an MD card for reference"): every time
seniority.json is written the Watcher writes seniority.md from it, a heading (list date, source, count) and one row per
pilot sorted by seniority, with the pay year today (PWA 3.B.1, capped at 12). It is personal data: mode 600, beside the
uploads folder (/share/flight_watcher/seniority.md), never listed by the Web UI, never exported to a pilot's portal,
never in a list file kind. Made-up pilots only (the synthetic list fixture, "Doe, Jane")."""
import datetime as dt
import json
import logging
import os
import stat

import roles
import seniority as SEN
import web
from test_crew_index import W  # noqa: F401  (the Watcher fixture)
from test_web_upload import _fake_pdftotext, _mp

HST = dt.timezone(dt.timedelta(hours=-10))
LOG = logging.getLogger("t")
VIEW = {"source": "list", "file": "seniority_2026-03-01.pdf", "list_date": "2026-03-01", "count": 3, "pilots": {
    "10002": {"sen": 12, "name": "Roe, Rick", "doh": "2018-10-03", "seat": "FO", "equip": "330",
              "also": [{"sen": 3, "name": "Poe | Pat\nX", "doh": "bad", "seat": "FO", "equip": "321"}]},
    "10001": {"sen": 2, "name": "Doe, Jane", "doh": "1998-04-01", "seat": "CA", "equip": "330"}}}


def _rows(md):
    return [ln for ln in md.splitlines() if ln.startswith("| ") and not ln.startswith("| Seniority")]


def test_render_md_heading_rows_sorted_and_escaped():
    md = SEN.render_md(VIEW, "2026-11-14", "2026-11-14 10:00 HST")
    head = md.splitlines()
    assert head[0] == "# Pilot seniority list"
    assert head[2] == ("List date 2026-03-01 · Source: seniority list (seniority_2026-03-01.pdf) · 3 pilots · "
                       "Written 2026-11-14 10:00 HST")
    assert "| Seniority # | Name | Emp | DOH | Seat | Equip | Pay year today |" in head
    # sorted by seniority number; the record sharing an employee number ('also') is a row of its own; a pipe or a line
    # break inside a value never splits the table; an unreadable DOH has no pay year
    assert _rows(md) == ["| 2 | Doe, Jane | 10001 | 1998-04-01 | CA | 330 | 12 |",
                         "| 3 | Poe \\| Pat X | 10002 | bad | FO | 321 |  |",
                         "| 12 | Roe, Rick | 10002 | 2018-10-03 | FO | 330 | 9 |"]
    # the pay year turns over on the DOH's anniversary (PWA 3.B.1), the same count as pay.doh_year
    assert "| 12 | Roe, Rick | 10002 | 2018-10-03 | FO | 330 | 8 |" in SEN.render_md(VIEW, "2026-10-02")
    assert "PWA 3.B.1" in md and chr(0x2014) not in md
    # an award on top names its month and the pilots carried from the list under it
    aw = dict(VIEW, source="award 2026-12", carried=4, base={"as_of": "2026-03-01"}, list_date="")
    assert "Source: award 2026-12, 4 more carried from the seniority list of 2026-03-01 · 3 pilots" in SEN.render_md(aw, "2026-11-14")
    assert SEN.render_md(None, "2026-11-14") == "" and _rows(SEN.render_md({"pilots": {}}, "2026-11-14")) == []


def _mode(p):
    return stat.S_IMODE(os.stat(p).st_mode)


def test_a_list_upload_writes_the_md_at_mode_600(tmp_path, monkeypatch, fx, caplog):
    up = tmp_path / "uploads"
    up.mkdir()
    monkeypatch.setattr(web, "UPLOAD_DIR", str(up))
    monkeypatch.setattr(web, "_hst_now", lambda: dt.datetime(2026, 11, 14, 9, 30, tzinfo=HST))
    monkeypatch.setattr(web.subprocess, "run", _fake_pdftotext(fx("seniority_synthetic.txt")))
    with caplog.at_level(logging.INFO):
        r = web.upload_result(*_mp({"kind": "seniority", "list_date": "2026-03-01"}, b"%PDF-1.4 fake"), LOG)
    assert r["ok"], r
    md = tmp_path / "seniority.md"  # the folder above the uploads folder: /share/flight_watcher/seniority.md on Pako
    assert md.exists() and not (up / "seniority.md").exists() and _mode(md) == 0o600
    text = md.read_text()
    view = json.loads((up / "seniority.json").read_text())
    assert text.startswith("# Pilot seniority list\n") and f"· {view['count']} pilots ·" in text
    assert "List date 2026-03-01 · Source: seniority list (seniority_2026-11-14.pdf)" in text
    assert _rows(text)[0].startswith("| 1 | Doe, Jane | 901 | 1988-05-01 | CA | 330 | 12 |")
    assert "Written 2026-11-14 09:30 HST" in text
    assert not [f for f in os.listdir(tmp_path) if f.endswith(".tmp")]  # written whole, nothing left behind
    # never in the Web UI's uploads list, never in the log
    assert all("seniority.md" not in f["name"] for f in web.uploads_list())
    assert "Doe" not in caplog.text and "seniority.md" not in caplog.text


def test_an_award_rebuild_rewrites_the_md(tmp_path, monkeypatch, fx):
    """Any source of seniority.json goes through seniority_rebuild, so the md follows an award's dates of hire too;
    a test folder that is not named uploads gets the md beside the json (never outside the test's folder)."""
    monkeypatch.setattr(web, "UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(web, "_hst_now", lambda: dt.datetime(2026, 11, 20, 9, 30, tzinfo=HST))
    txt = tmp_path / "2026-12_award.txt"
    txt.write_text(fx("award_packet_synthetic.txt"), encoding="utf-8")
    info = web.award_seniority(str(txt), "2026-12", "2026-12_award.pdf", "2026-11-20T09:30:00-10:00")
    assert info["decision"] == "on-top"
    md = (tmp_path / "seniority.md").read_text()
    assert "Source: award 2026-12 · 30 pilots" in md and len(_rows(md)) == 30 and _mode(tmp_path / "seniority.md") == 0o600
    assert web.seniority_md_path(str(tmp_path / "uploads" / "seniority.json")) == str(tmp_path / "seniority.md")
    assert web.seniority_md_path(str(tmp_path / "x" / "seniority.json")) == str(tmp_path / "x" / "seniority.md")


def test_the_md_never_fails_an_upload(tmp_path, monkeypatch, fx):
    monkeypatch.setattr(web, "UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(SEN, "render_md", lambda *a: 1 / 0)
    d = web.seniority_store(SEN.parse(fx("seniority_synthetic.txt"), 2026), "seniority_2026-11-14.pdf", "2026-11-14T09:30:00")
    assert d["count"] == 12 and (tmp_path / "seniority.json").exists() and not (tmp_path / "seniority.md").exists()


def test_the_watcher_backfills_the_md_at_start(W, tmp_path, monkeypatch, fx):  # noqa: F811
    """A seniority.json written by an older Watcher (no md) gets its md at the first start, and again only when the
    json is newer than the md; the default instance only (the files' one writer)."""
    up = tmp_path / "uploads"
    up.mkdir()
    monkeypatch.setattr(W, "UPLOADS_SHARED", str(up))
    view = SEN.combine(dict(SEN.to_json(SEN.parse(fx("seniority_synthetic.txt"), 2026), "seniority_2026-11-06.pdf",
                                        "2026-11-06T09:00:00"), source="list"), None)
    view["parser"] = SEN.PARSER
    (up / "seniority.json").write_text(json.dumps(view))
    monkeypatch.setattr(W, "INSTANCE", "pilot2")
    W.seniority_refresh()
    assert not (tmp_path / "seniority.md").exists()  # a pilot's instance never writes it
    monkeypatch.setattr(W, "INSTANCE", "")
    W.seniority_refresh()
    md = tmp_path / "seniority.md"
    assert md.exists() and _mode(md) == 0o600 and len(_rows(md.read_text())) == 12
    t0 = md.stat().st_mtime_ns
    W.seniority_refresh()
    assert md.stat().st_mtime_ns == t0  # current: not written again
    os.utime(up / "seniority.json", ns=(t0 + 10 ** 9, t0 + 10 ** 9))
    W.seniority_refresh()
    assert md.stat().st_mtime_ns > t0


def test_the_md_is_never_exported_or_a_file_kind(W, tmp_path, monkeypatch):  # noqa: F811
    """seniority.md is no list file kind and the portal's file sources never name it, wherever it sits."""
    assert not any("seniority" in k for k in roles.FILE_KINDS)
    www = tmp_path / "www"
    www.mkdir(exist_ok=True)
    for d in (www, tmp_path):
        (d / "seniority.md").write_text("# Pilot seniority list\n")
        os.chmod(d / "seniority.md", 0o600)
    monkeypatch.setattr(W, "portal_on", lambda: True)
    assert not any("seniority" in k or "seniority" in p for k, p in W.portal_file_sources())
