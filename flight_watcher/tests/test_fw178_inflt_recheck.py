"""1.7.8 (Ryan, Nov 15: "Re-check them"): the in-flight verdicts 1.7.7 dropped as made for another pilot (inflt_skip)
are looked up again once for the right pilot (the pickup's first open-seat picker), and the second picker of a
both-seats pickup gets his own in-flight lookup (his verdict in inflt_no, by employee number), all within the existing
paced in-flight budget (INFLT_PER_CHECK lookups a check), FLICA read only (GET only: the Schedule Lookup and the
mobile pairing page). Synthetic pilots only ("Doe, Jane" 10001)."""
import json
import logging
from datetime import datetime, timedelta, timezone

import inflt
from store import INFLT_MAX_TRIES, Store
from test_fw177_pickers import JANE, MAX, PAT, RICK, _find, _old_style

HST = timezone(timedelta(hours=-10))


class _Fl:
    """FLICA stand-in: every Schedule Lookup gives a month with one trip on Nov 3 (H3648), every pairing page one leg
    airborne at the pickup time when the picker is in `air`."""

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


def _run(db, fl, monkeypatch, limit=3):
    monkeypatch.setattr(inflt.time, "sleep", lambda s: None)
    return inflt.run(fl, db, limit, logging.getLogger("t"), lambda: datetime(2026, 11, 14, 8, 0), "https://example.invalid",
                     HST)


def _done(db):
    for k, v in (("score_email_v", 1), ("inflt_reset_v", inflt.RESET_V), ("inflt_recheck_no_v", inflt.RECHECK_NO_V)):
        db.put(k, v)


def _pk(db, key):
    return json.loads(db.db.execute("SELECT pickup FROM finds WHERE key=?", (key,)).fetchone()[0])


def test_the_dropped_verdicts_are_looked_up_again_once_for_the_picker(tmp_path, monkeypatch):
    db = Store(str(tmp_path / "s.db"))
    _done(db)
    _find(db, "H9001|20Nov", f"FO {JANE}; RO {RICK}", "2026-11-03T20:30:00+00:00", "FO")  # Jane the picker
    _old_style(db, "H9001|20Nov", f"FO {JANE}; RO {RICK}", 120)
    db.set_inflt("H9001|20Nov", True, "H3648 2026-11-03", tries=1)  # 1.7.6.1 looked up Rick (the wrong pilot)
    db.rebuild_pickers()
    assert _pk(db, "H9001|20Nov")["inflt_skip"] is True and db.pickups_without_inflt() == []
    fl = _Fl()
    assert _run(db, fl, monkeypatch)
    sched = [u for u in fl.urls if "cmschedules.cgi" in u]
    assert sched and all("EmployeeID=10001" in u for u in sched)  # Jane, never Rick
    pk = _pk(db, "H9001|20Nov")
    assert (pk["inflt"], pk["inflt_emp"], "inflt_skip" in pk) == (False, "10001", False)
    assert db.get("inflt_skip_recheck_v") == inflt.RECHECK_SKIP_V
    # once: a later run loads nothing for it
    fl2 = _Fl()
    _run(db, fl2, monkeypatch)
    assert fl2.urls == []


def test_the_second_picker_of_a_both_seats_pickup_gets_his_own_lookup(tmp_path, monkeypatch):
    db = Store(str(tmp_path / "s.db"))
    _done(db)
    db.put("inflt_skip_recheck_v", inflt.RECHECK_SKIP_V)
    _find(db, "H9002|21Nov", f"FO {PAT}; RO {MAX}", "2026-11-03T20:30:00+00:00", "FO,RO",
          pickup={"pickers": ["10003", "10004"]})
    db.score_pickup("H9002|21Nov")
    todo = db.pickups_without_inflt()
    assert [(k, e) for k, e, _g, _t in todo] == [("H9002|21Nov", "10003"), ("H9002|21Nov", "10004")]
    fl = _Fl(air={"10004"})  # Max was airborne, Pat on the ground
    assert _run(db, fl, monkeypatch)
    pk = _pk(db, "H9002|21Nov")
    assert (pk["inflt"], pk["inflt_emp"]) == (False, "10003")  # the pickup's verdict stays the first picker's
    no = pk["inflt_no"]["10004"]
    assert no["inflt"] is True and no["trip"] == "H3648 2026-11-03" and no["leg"]["flt"] == "808"
    assert db.pickups_without_inflt() == []
    st = db.picker_stats()
    assert (st["10003"]["inflt_n"], st["10004"]["inflt_n"]) == (0, 1)
    f = db.recent_finds()[0]
    assert f["inflt_no"] == {"10004": True}
    # a re-check of the pickup keeps both verdicts; a reset drops them all
    db.set_pickup("H9002|21Nov", {"status": "filled", "by": f"FO {PAT}; RO {MAX}", "ca": "", "known": True,
                                  "pickers": ["10003", "10004"]})
    assert _pk(db, "H9002|21Nov")["inflt_no"]["10004"]["inflt"] is True
    db.reset_inflt()
    assert "inflt_no" not in _pk(db, "H9002|21Nov")


def test_within_the_paced_budget_and_failed_tries_count_per_picker(tmp_path, monkeypatch):
    db = Store(str(tmp_path / "s.db"))
    _done(db)
    db.put("inflt_skip_recheck_v", inflt.RECHECK_SKIP_V)
    for i in range(3):
        k = f"H900{i}|2{i}Nov"
        _find(db, k, f"FO {PAT}; RO {MAX}", f"2026-11-0{3 + i}T20:30:00+00:00", "FO,RO",
              pickup={"pickers": ["10003", "10004"]})
        db.score_pickup(k)
    assert len(db.pickups_without_inflt()) == 6

    class Down(_Fl):
        def fetch(self, url):
            self.urls.append(url)
            return "<html><body>application error</body></html>"
    fl = Down()
    _run(db, fl, monkeypatch, limit=3)
    assert len({u.split("EmployeeID=")[1].split("&")[0] + u[-30:] for u in fl.urls}) >= 1
    tries = [(k, e, t) for k, e, _g, t in db.pickups_without_inflt()]
    assert sum(1 for _k, _e, t in tries if t == 1) == 3  # 3 lookups a check (INFLT_PER_CHECK), each try counted once
    for _ in range(INFLT_MAX_TRIES * 2):
        _run(db, Down(), monkeypatch, limit=3)
    assert db.pickups_without_inflt() == []  # every picker gave up after INFLT_MAX_TRIES failed tries
    pk = _pk(db, "H9000|20Nov")
    assert pk["inflt_tries"] == INFLT_MAX_TRIES and pk["inflt_no"]["10004"]["tries"] == INFLT_MAX_TRIES


def test_the_recheck_never_writes_to_flica(tmp_path, monkeypatch):
    db = Store(str(tmp_path / "s.db"))
    _done(db)
    _find(db, "H9001|20Nov", f"FO {JANE}; RO {RICK}", "2026-11-03T20:30:00+00:00", "FO")
    _old_style(db, "H9001|20Nov", f"FO {JANE}; RO {RICK}", 120)
    db.set_inflt("H9001|20Nov", None, "", tries=3)
    db.rebuild_pickers()
    fl = _Fl()
    _run(db, fl, monkeypatch)
    assert fl.urls and all(("cmschedules.cgi" in u or "mobilepairing.cgi" in u) for u in fl.urls)
    assert not any(w in u.lower() for u in fl.urls for w in ("submit", "drop", "swap", "bid", "add"))
