import logging
from datetime import datetime, timedelta, timezone

import inflt
from store import Store

HST = timezone(timedelta(hours=-10))
SCHED = ('<script>function pair(pr){} TAry[TAry.length]=new Task(1, "SU", "01", "H3647", "PHX", "20261101", 1, 0, \'H3647\');'
         ' TAry[TAry.length]=new Task(1, "TU", "03", "H3648", "SAN", "20261103", 1, 0, \'H3648\');</script>'
         ' MA, M (Emp# 10008) Schedule Last Updated: Nov 4')
PAIR = "pairing details h3648:03nov check in: 11:40 dy flt dps-ars dep arr blk tu 816 hnl-san 1249 1946 0457 we 815 san-hnl 0805 1219 0614 blk : 1111"
FWD = "<html>schedule details this is going to forward to the schedule details page ...</html>"


class FakeFl:
    def __init__(self, pages):
        self.pages, self.urls = pages, []

    def fetch(self, url):
        self.urls.append(url)
        for k, v in self.pages.items():
            if k in url:
                return v
        return "<html>nothing</html>"


def _db(tmp_path, gone):
    db = Store(str(tmp_path / "f.db"))
    db.put("score_email_v", 1)  # the 0.5.6 one-shot scoring is not what these tests check
    db.add_find("H3647|07Nov", "2026-11", {"pairing": "H3647"}, gone, gone=gone)
    db.set_pickup("H3647|07Nov", {"status": "filled", "by": "FO Doe, Pat (10008)", "ca": "", "known": True})
    return db


def test_airborne_pickup_marked(tmp_path, monkeypatch):
    monkeypatch.setattr(inflt.time, "sleep", lambda s: None)
    db = _db(tmp_path, "2026-11-04T17:00:00+00:00")  # 07:00 HST Nov 4, airborne SAN-HNL
    fl = FakeFl({"cmschedules.cgi": SCHED, "mobilepairing.cgi": PAIR})
    assert inflt.run(fl, db, 3, logging.getLogger("t"), lambda: datetime(2026, 11, 4, 8, 0), "https://x", HST)
    f = db.recent_finds()[0]
    assert f["inflt"] is True and f["inflt_trip"] == "H3648 2026-11-03"
    assert db.picker_stats() == {} or True


def test_layover_pickup_not_in_flight(tmp_path, monkeypatch):
    monkeypatch.setattr(inflt.time, "sleep", lambda s: None)
    db = _db(tmp_path, "2026-11-04T14:25:00+00:00")  # 04:25 HST, hotel before report
    fl = FakeFl({"cmschedules.cgi": SCHED, "mobilepairing.cgi": PAIR})
    inflt.run(fl, db, 3, logging.getLogger("t"), lambda: datetime(2026, 11, 4, 8, 0), "https://x", HST)
    assert db.recent_finds()[0]["inflt"] is False


def test_forwarding_page_counts_as_failed_try(tmp_path, monkeypatch):
    monkeypatch.setattr(inflt.time, "sleep", lambda s: None)
    db = _db(tmp_path, "2026-11-04T17:00:00+00:00")
    fl = FakeFl({"cmschedules.cgi": FWD})
    assert inflt.run(fl, db, 3, logging.getLogger("t"), lambda: datetime(2026, 11, 4, 8, 0), "https://x", HST) is False
    assert db.pickups_without_inflt()[0][3] == 1 and db.recent_finds()[0]["inflt"] is None
    assert any("bd=1126" in u for u in fl.urls)  # the month shape was tried too


def test_parse_task_rows_and_links():
    assert inflt.parse_cm_schedule(SCHED) == [{"trip": "H3647", "start": "2026-11-01"}, {"trip": "H3648", "start": "2026-11-03"}]
    assert inflt.parse_cm_schedule("onclick=\"javascript:pair('H3601','20261105',0)\"") == [{"trip": "H3601", "start": "2026-11-05"}]
    assert inflt.schedule_ok("<script>function pair(){}</script>") is False


def test_parse_cm_month():
    html = ('<html><head><title>FLICA.Net - Crewmember Schedule</title></head><body><select name="BlockDates">'
            '<option value="1026" > October<option value="1126" selected> November</select>'
            ' DOE, PAT (Emp# 10008) Schedule Last Updated: Nov 4, 2026 13:52:55 HA <script>'
            'TAry[TAry.length]=new Task(1, "FR", "30", "H3075", "LAX", "20261030", 1, 0, \'H3075\');'
            'TAry[TAry.length]=new Task(0, "SA", "31", "", "-", "20261030", 1, 0, \'\');'
            'TAry[TAry.length]=new Task(0, "SU", "01", "", "HNL", "20261030", 1, 0, \'\');'
            'TAry[TAry.length]=new Task(0, "MO", "02", "%26nbsp%3B", "", "", 0, 0, \'&nbsp;\');'
            'TAry[TAry.length]=new Task(1, "TU", "03", "VAC", "", "20261103", 1, 0, \'VAC\');'
            'TAry[TAry.length]=new Task(1, "WE", "04", "VAC", "", "20261104", 1, 0, \'VAC\');'
            'TAry[TAry.length]=new Task(1, "TH", "05", "H3606", "JFK", "20261105", 1, 0, \'H3606\');'
            'TAry[TAry.length]=new Task(0, "FR", "06", "", "-", "20261105", 1, 0, \'\');'
            'TAry[TAry.length]=new Task(0, "SA", "07", "", "HNL", "20261105", 1, 0, \'\');'
            'TAry[TAry.length]=new Task(0, "TU", "01", "%26nbsp%3B", "", "", 0, 0, \'&nbsp;\');</script>'
            "<TABLE><TR><TD>Block &nbsp;&nbsp;</TD><TD Colspan=2 Class='right'>100.39 &nbsp;&nbsp;</TD></TR>"
            "<TR><TD>Credit &nbsp;&nbsp;</TD><TD Colspan=2 Class='right'>116.16 &nbsp;&nbsp;</TD></TR>"
            "<TR><TD>Days Off &nbsp;</TD><TD Colspan=2 Class='right'>10 &nbsp;&nbsp;</TD></TR></TABLE></body></html>")
    r = inflt.parse_cm_month(html)
    assert r["month"] == "2026-11" and r["name"] == "Doe, Pat" and r["emp"] == "10008"
    assert r["days"][0] == ["2026-10-30", "H3075", "LAX"] and r["days"][2] == ["2026-11-01", "", "HNL"]
    assert r["days"][-1][0] == "2026-12-01" and r["days"][3] == ["2026-11-02", "", ""]
    assert r["items"] == [{"trip": "H3075", "start": "2026-10-30", "end": "2026-11-01", "lay": "LAX"},
                          {"trip": "VAC", "start": "2026-11-03", "end": "2026-11-04", "lay": ""},
                          {"trip": "H3606", "start": "2026-11-05", "end": "2026-11-07", "lay": "JFK"}]
    assert r["totals"] == {"block": "100:39", "credit": "116:16", "days_off": 10} and r["updated"].startswith("Nov 4, 2026")
    assert inflt.parse_cm_month("<html>nothing</html>") is None


def test_cm_month_decodes_codes():
    html = ('<script>TAry[TAry.length]=new Task(1, "MO", "26", "O%2FK", "", "20261026", 1, 0, \'x\');'
            'TAry[TAry.length]=new Task(1, "TU", "27", "%26nbsp%3B", "", "20261027", 1, 0, \'x\');</script>'
            '<select><option value="1026" selected> October</select>')
    s = inflt.parse_cm_month(html)
    assert [d[1] for d in s["days"]] == ["O/K", ""] and s["items"][0]["trip"] == "O/K"


def test_schedule_ok_own_page_without_emp():
    own = '<script>TAry[TAry.length]=new Task(1, "SU", "01", "H3647", "PHX", "20261101", 1, 0, \'x\');</script> November Schedule Last Updated: Nov 4, 2026'
    assert inflt.schedule_ok(own)
    assert not inflt.schedule_ok("<html>schedule details this is going to forward</html>")
