"""1.7.9 (Ryan's two follow-ups, Nov 15), each test failed on cdbbd41 (1.7.8):
(1) A pickup whose open-seat picker is not known (no open seat on file and two pilots named, as the pickups 1.7.7
    dropped the verdict of: inflt_skip) gets an in-flight lookup for EACH pilot named in its 'by', his own verdict
    kept by employee number (inflt_named), read only (GET only), within the paced budget, queued once (the oldest
    too, listed first). The pickup's own verdict, its pickers and the pickers' in-flight counts do not change: nobody
    is made the picker. The finds export carries the verdicts (inflt_named), only while the picker is not known.
(2) No in-flight log line carries an employee number: the verdict line names the pilot by his place, and FLICA page
    text ("(emp# n) schedule last updated", EmployeeID=n) is masked by the helper every page quote goes through.
(3) The finds card (Chromium, 390 x 844 and 1280 x 800, light and dark): each named pilot's verdict on its own line
    by his seat, marked "picker not known", his name on hover, no link; the Key says so. FW_179_SHOTS=<dir> keeps the
    screenshots.
Synthetic pilots only ("Doe, Jane" 10001)."""
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone

import captures as CAPS
import inflt
from store import INFLT_MAX_TRIES, Store
from test_crew_index import W  # noqa: F401  (the Watcher fixture)
from test_fw177_pickers import JANE, MAX, PAT, RICK, _find

HST = timezone(timedelta(hours=-10))
GONE = "2026-11-03T20:30:00+00:00"


class _Fl:
    """FLICA stand-in (as test_fw178_inflt_recheck): a month with one trip on Nov 3 (H3648); its one leg holds the
    pickup time when the pilot looked up is in `air`."""

    def __init__(self, air=()):
        self.urls, self.air = [], set(air)

    def fetch(self, url):
        self.urls.append(url)
        if "cmschedules.cgi" in url:
            self.emp = url.split("EmployeeID=")[1].split("&")[0]
            return ('<script>function pair(pr){} TAry[TAry.length]=new Task(1, "TU", "03", "H3648", "LAS", "20261103", '
                    "1, 0, 'H3648');</script> DOE, P (Emp# " + self.emp + ") Schedule Last Updated: Nov 4")
        legs = "tu 808 hnl-las 1000 1900 0600 " if getattr(self, "emp", "") in self.air else "tu 808 hnl-las 1500 2300 0600 "
        return ("<html><body>pairing details h3648:03nov check in: 08:00 dy flt dps-ars dep arr blk " + legs +
                "crew: ca 10009 doe, john</body></html>")


def _run(db, fl, monkeypatch, limit=3, log=None):
    monkeypatch.setattr(inflt.time, "sleep", lambda s: None)
    return inflt.run(fl, db, limit, log or logging.getLogger("t"), lambda: datetime(2026, 11, 14, 8, 0),
                     "https://example.invalid", HST)


def _done(db):
    for k, v in (("score_email_v", 1), ("inflt_reset_v", inflt.RESET_V), ("inflt_recheck_no_v", inflt.RECHECK_NO_V),
                 ("inflt_skip_recheck_v", inflt.RECHECK_SKIP_V)):
        db.put(k, v)


def _pk(db, key):
    return json.loads(db.db.execute("SELECT pickup FROM finds WHERE key=?", (key,)).fetchone()[0])


def _dropped(db, key, by, gone=GONE, first=None):
    """A pickup as 1.7.7 left it when its verdict was for a pilot who is not known to be the picker: no open seat on
    file, two names, no picker, no verdict, tries used up."""
    _find(db, key, by, gone, "", first=first)
    pk = _pk(db, key)
    pk.update(pickers=[], inflt=None, inflt_trip="", inflt_emp="", inflt_skip=True, inflt_tries=INFLT_MAX_TRIES)
    db.db.execute("UPDATE finds SET pickup=? WHERE key=?", (json.dumps(pk), key))


def test_each_named_pilot_is_looked_up_once_when_the_picker_is_not_known(tmp_path, monkeypatch):
    db = Store(str(tmp_path / "s.db"))
    _done(db)
    _dropped(db, "H9001|20Nov", f"FO {JANE}; RO {RICK}")
    assert db.recent_finds()[0]["pickers"] == [] and db.get("inflt_named_v") is None
    fl = _Fl(air={"10002"})  # Rick was airborne, Jane on the ground
    assert _run(db, fl, monkeypatch)
    assert db.get("inflt_named_v") == inflt.NAMED_V
    sched = [u.split("EmployeeID=")[1].split("&")[0] for u in fl.urls if "cmschedules.cgi" in u]
    assert sched == ["10001", "10002"]  # each pilot named, in the 'by' order, one lookup each
    assert all(u.startswith("https://example.invalid/full/") and "cgi?" in u for u in fl.urls)  # GET reads only
    pk = _pk(db, "H9001|20Nov")
    named = pk["inflt_named"]
    assert named["10001"]["inflt"] is False and named["10002"]["inflt"] is True
    assert named["10002"]["trip"] == "H3648 2026-11-03" and named["10002"]["leg"]["flt"] == "808"
    # nobody is made the picker: the pickup's own verdict, its picker and the dropped state stay as 1.7.8 left them
    assert (pk["inflt"], pk["inflt_emp"], pk["inflt_skip"], pk["pickers"]) == (None, "", True, [])
    assert "inflt_no" not in pk and db.picker_stats() == {}
    f = db.recent_finds()[0]
    assert f["pickers"] == [] and f["inflt"] is None and f["inflt_skip"] is True
    assert f["inflt_named"] == {"10001": {"inflt": False, "trip": "", "leg": None},
                                "10002": {"inflt": True, "trip": "H3648 2026-11-03", "leg": named["10002"]["leg"]}}
    # once: a later run loads nothing for it
    fl2 = _Fl()
    _run(db, fl2, monkeypatch)
    assert fl2.urls == [] and db.pickups_without_inflt() == []
    # a re-check of the pickup keeps the verdicts; a reset drops them
    db.set_pickup("H9001|20Nov", {"status": "filled", "by": f"FO {JANE}; RO {RICK}", "ca": "", "known": True, "pickers": []})
    assert _pk(db, "H9001|20Nov")["inflt_named"]["10002"]["inflt"] is True
    db.reset_inflt()
    assert "inflt_named" not in _pk(db, "H9001|20Nov")


def test_a_known_picker_is_looked_up_as_before_and_has_no_named_verdicts(tmp_path, monkeypatch):
    db = Store(str(tmp_path / "s.db"))
    _done(db)
    _find(db, "H9002|21Nov", f"FO {JANE}; RO {RICK}", GONE, "FO", pickup={"pickers": ["10001"]})  # Jane the picker
    db.score_pickup("H9002|21Nov")
    fl = _Fl(air={"10002"})
    assert _run(db, fl, monkeypatch)
    assert {u.split("EmployeeID=")[1].split("&")[0] for u in fl.urls if "cmschedules.cgi" in u} == {"10001"}
    pk = _pk(db, "H9002|21Nov")
    assert (pk["inflt"], pk["inflt_emp"]) == (False, "10001") and "inflt_named" not in pk
    assert db.recent_finds()[0]["inflt_named"] == {}


def test_the_oldest_are_included_and_listed_first_within_the_budget(tmp_path, monkeypatch):
    db = Store(str(tmp_path / "s.db"))
    _done(db)
    _dropped(db, "H8000|01Sep", f"FO {JANE}; RO {RICK}", "2026-09-01T20:30:00+00:00")  # older than the newest 50 finds
    for i in range(55):
        _find(db, f"H7{i:03d}|20Nov", f"FO {PAT}", f"2026-11-{1 + i % 9:02d}T{10 + i % 9}:{i:02d}:00+00:00", "FO",
              pickup={"pickers": ["10003"], "inflt": False, "inflt_emp": "10003"})
    assert db.pickups_without_inflt() == []  # 1.7.8: it never came up again
    assert db.queue_inflt_named() == 1 and db.queue_inflt_named() == 0  # queued once
    todo = [(k, e, t) for k, e, _g, t in db.pickups_without_inflt()]
    assert todo == [("H8000|01Sep", "10001", 0), ("H8000|01Sep", "10002", 0)]
    # a newer pickup with no picker known is looked up too, after the queued one
    _find(db, "H9005|22Nov", f"FO {PAT}; RO {MAX}", "2026-11-12T20:30:00+00:00", "")
    assert [(k, e) for k, e, _g, _t in db.pickups_without_inflt()] == [
        ("H8000|01Sep", "10001"), ("H8000|01Sep", "10002"), ("H9005|22Nov", "10003"), ("H9005|22Nov", "10004")]
    fl = _Fl()
    _run(db, fl, monkeypatch, limit=3)  # INFLT_PER_CHECK lookups a check, no more
    assert len([u for u in fl.urls if "cmschedules.cgi" in u]) == 3
    assert [(k, e) for k, e, _g, _t in db.pickups_without_inflt()] == [("H9005|22Nov", "10004")]
    assert "inflt_named_q" not in _pk(db, "H8000|01Sep")  # both looked up: back in the normal order


def test_a_failed_lookup_counts_per_named_pilot_and_ends(tmp_path, monkeypatch):
    db = Store(str(tmp_path / "s.db"))
    _done(db)
    _dropped(db, "H9001|20Nov", f"FO {JANE}; RO {RICK}")

    class Down(_Fl):
        def fetch(self, url):
            self.urls.append(url)
            return "<html><body>application error</body></html>"
    _run(db, Down(), monkeypatch)
    assert [(e, t) for _k, e, _g, t in db.pickups_without_inflt()] == [("10001", 1), ("10002", 1)]
    for _ in range(INFLT_MAX_TRIES):
        _run(db, Down(), monkeypatch)
    assert db.pickups_without_inflt() == []
    named = _pk(db, "H9001|20Nov")["inflt_named"]
    assert {e: (v["inflt"], v["tries"]) for e, v in named.items()} == {"10001": (None, 3), "10002": (None, 3)}
    fl = Down()
    _run(db, fl, monkeypatch)
    assert fl.urls == []
    assert db.recent_finds()[0]["inflt_named"] == {"10001": {"inflt": None, "trip": "", "leg": None},
                                                   "10002": {"inflt": None, "trip": "", "leg": None}}


class _Lines(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


def _logger(name):
    lg = logging.getLogger(name)
    lg.setLevel(logging.INFO)
    h = _Lines()
    lg.handlers = [h]
    return lg, h.lines


def test_no_in_flight_log_line_carries_an_employee_number(tmp_path, monkeypatch):
    db = Store(str(tmp_path / "s.db"))
    _done(db)
    _dropped(db, "H9001|20Nov", f"FO {JANE}; RO {RICK}")
    _find(db, "H9002|21Nov", f"FO {PAT}; RO {MAX}", GONE, "FO,RO", pickup={"pickers": ["10003", "10004"]})
    db.score_pickup("H9002|21Nov")

    class Odd(_Fl):
        """Rick's lookup answers with FLICA's page that still names the employee number; Max's fails with the URL."""

        def fetch(self, url):
            if "EmployeeID=10002" in url:
                self.urls.append(url)
                return ("<html><body>FLICA.Net November (Emp# 10002) Schedule Last Updated: Unknown An error has "
                        "occurred EmployeeID=10002</body></html>")
            if "EmployeeID=10004" in url:
                raise RuntimeError(f"timeout loading {url}")
            return super().fetch(url)
    monkeypatch.setattr(inflt, "PROBE", {"logged": 0, "saved": 2})
    monkeypatch.setattr(inflt, "PAGE_LOG", None)
    lg, lines = _logger("fw179.inflt")
    _run(db, Odd(air={"10001"}), monkeypatch, limit=10, log=lg)
    text = "\n".join(lines)
    assert not re.search(r"1000\d", text), text
    assert "schedule lookup 1126 gave" in text and "(emp# #####) schedule last updated" in text
    assert "EmployeeID=#####" in text or "employeeid=#####" in text
    assert "inflt H9001|20Nov: named pilot 1 (picker not known) IN FLIGHT on H3648 2026-11-03 (808 HNL-LAS 2026-11-03)" in text
    assert "inflt H9002|21Nov: picker 1 not in flight at pickup" in text
    assert "inflt H9002|21Nov skipped: timeout loading" in text
    assert "1 pickups whose open-seat picker is not known" in text


def test_the_page_quote_helper_masks_the_number_for_the_admin_too(W):  # noqa: F811
    assert W.CAP.admin
    out = W.page_log("flica.net november (emp# 10001) schedule last updated: unknown ?Prompt=1&EmployeeID=10001&bd=1126 "
                     "Emp#10001 employee id: 10001 credit 16:00 H3648 2026-11-03 flight 808")
    assert "10001" not in out
    assert out == ("flica.net november (emp# #####) schedule last updated: unknown ?Prompt=1&EmployeeID=#####&bd=1126 "
                   "Emp###### employee id: ##### credit 16:00 H3648 2026-11-03 flight 808")
    assert W.IF.PAGE_LOG is W.page_log
    assert CAPS.mask_emp("Doe, Jane 10001, 808 HNL-LAS") == "Doe, Jane 10001, 808 HNL-LAS"  # only a labeled number
    assert W.page_log("Doe, Jane") == "Doe, Jane"


# ---------------------------------------------------------------- the finds card
def _card_finds(db):
    from test_fw177_cards import _at
    rows = [  # (key, by, open seats, pickup extras, seen hour)
        ("H9401|19Nov", f"FO {JANE}; RO {RICK}", "", {"pickers": []}, 11),  # picker not known: Jane no, Rick airborne
        ("H9402|20Nov", f"FO {PAT}; RO {MAX}", "", {"pickers": []}, 10),  # picker not known: Pat not readable, Max to come
        ("H9403|21Nov", f"FO {PAT}; RO {MAX}", "FO,RO", {"pickers": ["10003", "10004"]}, 9),  # both known pickers
        ("H9404|22Nov", f"FO {JANE}; RO {RICK}", "FO", {"pickers": ["10001"]}, 8),  # Jane the picker
        ("H9405|23Nov", f"FO {JANE}", "FO", {"pickers": ["10001"]}, 7),
        ("H9406|24Nov", f"FO {PAT}", "FO", {"pickers": ["10003"]}, 6),
        ("H9407|25Nov", f"FO {MAX}; RO {RICK}", "", {"pickers": []}, 5),  # picker not known: airborne, flight not on file
    ]
    for k, by, seats, extra, h in rows:
        db.add_find(k, "2026-11", {"pairing": k[:5], "dates": f"{k[6:8]}NOV-{int(k[6:8]) + 2}NOV", "days": "3",
                                   "layover": "SEA", "credit": "16:00", "captain": "Doe, John (10009)", "open_seats": seats},
                    _at(14, h), gone=_at(14, h, 2))
        db.db.execute("UPDATE finds SET last_seen=? WHERE key=?", (_at(14, h, 1), k))
        db.set_pickup(k, dict({"status": "filled", "by": by, "ca": "Doe, John (10009)", "known": bool(extra["pickers"])}, **extra))
    leg = {"flt": "808", "frm": "HNL", "to": "LAS", "dep_l": "23:00", "date": "2026-11-06", "dh": False, "src": "page"}
    db.set_inflt("H9401|19Nov", False, "", tries=1, emp="10001")
    db.set_inflt("H9401|19Nov", True, "H3648 2026-11-03", tries=1, emp="10002", leg=leg)
    db.set_inflt("H9402|20Nov", None, "", tries=INFLT_MAX_TRIES, emp="10003")
    db.set_inflt("H9403|21Nov", False, "", tries=1, emp="10003")
    db.set_inflt("H9403|21Nov", False, "", tries=1, emp="10004")
    db.set_inflt("H9404|22Nov", True, "H3648 2026-11-03", tries=1, emp="10001", leg=leg)
    db.set_inflt("H9405|23Nov", False, "", tries=1, emp="10001")
    db.set_inflt("H9407|25Nov", True, "H3648 2026-11-03", tries=1, emp="10004")
    db.set_inflt("H9407|25Nov", False, "", tries=1, emp="10002")
    return db.finds_between(_at(1, 0), _at(15, 0))


NAMED = """() => Object.fromEntries([...FC.shadowRoot.querySelectorAll('tbody tr')].filter((tr) => tr.children.length > 3).map((tr) => {
  const td = tr.children, by = td[10], inf = td[11];
  return [td[2].textContent.trim(), { links: [...by.querySelectorAll('a')].map((a) => a.textContent),
    plain: [...by.querySelectorAll('.np')].map((x) => x.textContent),
    lines: [...inf.querySelectorAll('.nk')].map((d) => d.textContent.trim().replace(/\\s+/g, ' ')),
    tips: [...inf.querySelectorAll('.nk .if')].map((x) => x.getAttribute('title')),
    icons: [...inf.querySelectorAll('.nk')].map((d) => !!d.querySelector('ha-icon')),
    text: inf.textContent.trim() }]; }))"""


def test_the_finds_card_shows_each_named_pilots_verdict_marked_picker_not_known(W, tmp_path):  # noqa: F811
    from test_fw177_cards import _browser, _page
    finds = _card_finds(W.DB)
    by = {f["pairing"]: f for f in finds}
    assert by["H9401"]["pickers"] == [] and sorted(by["H9401"]["inflt_named"]) == ["10001", "10002"]
    assert by["H9402"]["inflt_named"]["10004"] == {"inflt": None, "trip": "", "leg": None}
    assert by["H9403"]["inflt_named"] == {} and by["H9404"]["inflt_named"] == {}
    shots = os.environ.get("FW_179_SHOTS", "")
    with _browser() as b:
        for width, height in ((390, 844), (1280, 800)):
            for scheme in ("light", "dark"):
                pg = _page(b, width, height, scheme, finds, [])
                rows = pg.evaluate(NAMED)
                a = rows["H9401"]
                assert a["links"] == [] and a["plain"] == [JANE, RICK]  # no blue link: the picker is not known
                assert a["lines"] == ["FO no", "RO AS808/06NOV", "picker not known"] and a["icons"] == [False, True, False]
                assert a["tips"] == [
                    "FO Doe, Jane: on the ground at pickup; picker not known",
                    "RO Roe, Rick: picked up while airborne on AS808 HNL-LAS, departed 06NOV 23:00 local (pairing H3648 "
                    "Nov 3); picker not known"]
                c = rows["H9402"]
                assert c["links"] == [] and c["lines"] == ["FO -", "RO -", "picker not known"]
                assert c["tips"][0] == "FO Poe, Pat: not checked (yet, or his schedule could not be read); picker not known"
                g = rows["H9407"]
                assert g["lines"] == ["FO", "RO no", "picker not known"] and g["icons"] == [True, False, False]
                assert g["tips"][0] == ("FO Moe, Max: picked up while airborne (pairing H3648 Nov 3); flight not on file; "
                                        "picker not known")
                # a known picker is as 1.7.8: the link, one verdict, no "picker not known"
                assert rows["H9403"]["links"] == [PAT, MAX] and rows["H9403"]["lines"] == [] and rows["H9403"]["text"] == "no"
                assert rows["H9404"]["links"] == [JANE] and rows["H9404"]["text"] == "AS808/06NOV"
                assert rows["H9405"]["text"] == "no" and rows["H9406"]["text"] == "-"
                pg.evaluate("() => { FC.shadowRoot.querySelector('details.key').open = true; }")
                key = pg.evaluate("() => FC.shadowRoot.querySelector('details.key').textContent")
                assert "picker not known = the pot did not show which seat was open, so each pilot named was looked up" in key
                assert "only a known picker is" in key
                assert pg.evaluate("() => document.documentElement.scrollWidth <= innerWidth") and pg.errors == []
                if shots:
                    os.makedirs(shots, exist_ok=True)
                    pg.locator("flight-watcher-finds-card").first.screenshot(path=os.path.join(shots, f"finds_named_{width}_{scheme}.png"))
                    pg.evaluate("() => { const w = FC.shadowRoot.querySelector('.wrap'), th = FC.shadowRoot.querySelectorAll('thead th')[11];"
                                " w.scrollLeft = Math.max(0, th.offsetLeft - (w.clientWidth - th.offsetWidth - 120)); }")
                    pg.locator("flight-watcher-finds-card").first.screenshot(path=os.path.join(shots, f"finds_named_{width}_{scheme}_inflt.png"))
                pg.context.close()
