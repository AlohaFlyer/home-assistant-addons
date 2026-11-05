import logging
from datetime import date

import charter as C

TABLE = """<html><body>Sign Out<table><tr><th>Cancelled</th><th>Flight #</th><th>Org-Dest</th><th>Scheduled</th>
<th>Estimated</th><th>Actual</th><th>Eqpt/REG</th><th>Tail #</th><th>Orig. Date</th></tr>
<tr><td></td><td>9980</td><td>SIN-HNL</td><td>11/04/26 12:00-07:15</td><td>11/04/26 12:00-08:06</td><td></td><td>332/3</td><td>382</td><td></td></tr>
<tr><td></td><td>450</td><td>HNL-NRT</td><td>11/05/26 12:00-16:25</td><td></td><td></td><td>332/3</td><td>385</td><td></td></tr>
<tr><td></td><td>471</td><td>HNL-MNL</td><td>11/05/26 10:30-16:00</td><td></td><td></td><td>333</td><td>390</td><td></td></tr>
<tr><td></td><td>9916</td><td>HNL-CRK</td><td>11/06/26 09:00-14:00</td><td></td><td></td><td>321/3</td><td>220</td><td></td></tr>
<tr><td>Yes</td><td>12</td><td>HNL-LAX</td><td>11/05/26 13:00-21:00</td><td></td><td></td><td>332/3</td><td>381</td><td></td></tr>
</table>1 item</body></html>"""

LOGIN = """<html><body><form action="ctwc.aspx" method="post"><input type="hidden" name="__VIEWSTATE" value="abc">
<input type="text" name="ctl00$txtUsername"><input type="password" name="ctl00$txtPassword">
<input type="submit" name="ctl00$btnLogin" value="Login"></form></body></html>"""


def test_parse_rows_and_flags():
    rows = C.parse_rows(TABLE)
    assert [r["flight"] for r in rows] == ["9980", "450", "471", "9916", "12"]
    reg = C.regular_set()
    assert C.flag(rows[0], reg) == "99xx charter"
    assert C.flag(rows[1], reg) == ""
    assert C.flag(rows[2], reg) == "MNL not a regular A330 station"
    assert C.flag(rows[3], reg) == ""  # A321, not ours
    assert C.flag(rows[4], reg) == ""
    u = C.unusual(rows, reg)
    assert [r["key"] for r in u] == ["9980|SIN-HNL|2026-11-04", "471|HNL-MNL|2026-11-05"]


def test_regular_option_and_merge():
    reg = C.regular_set("hnl, lax nrt")
    assert "LAX" in reg and "MNL" not in reg
    rows = C.unusual(C.parse_rows(TABLE), reg)
    known, new = C.merge({}, rows, "2026-11-04")
    assert sorted(new) == ["471|HNL-MNL|2026-11-05", "9980|SIN-HNL|2026-11-04"]
    known, new = C.merge(known, rows[:1], "2026-11-05")
    assert new == [] and known["471|HNL-MNL|2026-11-05"]["gone"] is True
    known, new = C.merge(known, [], "2026-11-10")
    assert known == {}


def test_login_form_and_dates():
    action, f = C.login_form(LOGIN)
    assert action == "ctwc.aspx" and f["user"] == "ctl00$txtUsername" and f["pass"] == "ctl00$txtPassword"
    assert "__VIEWSTATE" in f["fields"]
    assert C.logged_in(TABLE) and not C.logged_in(LOGIN)
    assert C.logged_in("<html><body>CrewTrac Menu Home | Sign Out Options View Schedule Change Password</body></html>")
    ds = C.scan_dates(date(2026, 11, 4), 30)
    assert ds[0] == "2026-11-03" and ds[-1] == "2026-12-04" and len(ds) == 32
    assert C.report_url("2026-11-04", "HNL", "").endswith("DeptDate=20261104&DeptCity=HNL&ArrvCity=")


class FakeSession:
    def __init__(self):
        self.urls = []

    def get(self, url, timeout=0):
        self.urls.append(url)
        return type("R", (), {"text": TABLE if "ctw4190" in url else LOGIN, "url": url})()

    def post(self, url, data=None, timeout=0, allow_redirects=True):
        self.urls.append(url)
        assert data["ctl00$txtUsername"] == "12345" and data["__VIEWSTATE"] == "abc"
        return type("R", (), {"text": TABLE, "url": C.BASE + "/Pilot/ctwcmainmenu.aspx"})()


def test_scanner_logs_in_and_scans():
    s = FakeSession()
    sc = C.Scanner(s, "12345", "pw", logging.getLogger("t"))
    assert sc.login()
    rows = sc.scan(date(2026, 11, 4), ahead=1)
    assert len(rows) == 5 * 3 * 2 and len([u for u in s.urls if "ctw4190" in u]) == 6
