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

# 0.7.4: the real page: header table, then the rows in TABLE ID='REPORTINFO' with &nbsp; padding
REAL = """<html><body>Sign Out<TABLE><THEAD><TR><TD><A HREF='x?SortCol=0'>Cancelled</A></TD><TD><A>Flight #</A></TD><TD><A>Org-Dest</A></TD></TR></THEAD></TABLE>
<DIV ID='REPORTDIV'><TABLE ID='REPORTINFO' BORDER='0'>
<TR><TD><FONT>&nbsp;&nbsp;</FONT></TD><TD><FONT>&nbsp;9940&nbsp;</FONT></TD><TD><FONT>&nbsp;HNL-HNL&nbsp;</FONT></TD><TD><FONT>&nbsp;11/03/26  05:00-05:30&nbsp;</FONT></TD><TD><FONT>&nbsp;&nbsp;</FONT></TD><TD><FONT>&nbsp;11/03/26  05:22-05:50&nbsp;</FONT></TD><TD><FONT>&nbsp;332/3  &nbsp;</FONT></TD><TD><FONT>&nbsp;361&nbsp;</FONT></TD><TD><FONT>&nbsp;&nbsp;</FONT></TD></TR>
<TR><TD><FONT>&nbsp;&nbsp;</FONT></TD><TD><FONT>&nbsp;9950&nbsp;</FONT></TD><TD><FONT>&nbsp;HNL-KOA&nbsp;</FONT></TD><TD><FONT>&nbsp;11/03/26  07:00-07:45&nbsp;</FONT></TD><TD></TD><TD></TD><TD><FONT>&nbsp;332/3  &nbsp;</FONT></TD><TD><FONT>&nbsp;361&nbsp;</FONT></TD><TD></TD></TR>
<TR><TD><FONT>&nbsp;Yes&nbsp;</FONT></TD><TD><FONT>&nbsp;9982&nbsp;</FONT></TD><TD><FONT>&nbsp;HNL-MNL&nbsp;</FONT></TD><TD><FONT>&nbsp;11/03/26  17:00-21:30&nbsp;</FONT></TD><TD></TD><TD></TD><TD><FONT>&nbsp;332/3  &nbsp;</FONT></TD><TD><FONT>&nbsp;383&nbsp;</FONT></TD><TD></TD></TR>
<TR><TD><FONT>&nbsp;&nbsp;</FONT></TD><TD><FONT>&nbsp;9981&nbsp;</FONT></TD><TD><FONT>&nbsp;HNL-SIN&nbsp;</FONT></TD><TD><FONT>&nbsp;11/03/26  16:00-21:30&nbsp;</FONT></TD><TD><FONT>&nbsp;&nbsp;</FONT></TD><TD><FONT>&nbsp;&nbsp;</FONT></TD><TD><FONT>&nbsp;332/3  &nbsp;</FONT></TD><TD><FONT>&nbsp;382&nbsp;</FONT></TD><TD><FONT>&nbsp;&nbsp;</FONT></TD></TR>
</TABLE></DIV></body></html>"""


def test_real_layout_and_local_flight():
    rows = C.parse_rows(REAL)
    assert [(r["flight"], r["route"], r["eqpt"], r["scheduled"]) for r in rows] == [
        ("9940", "HNL-HNL", "332/3", "11/03/26 05:00-05:30"), ("9950", "HNL-KOA", "332/3", "11/03/26 07:00-07:45"),
        ("9982", "HNL-MNL", "332/3", "11/03/26 17:00-21:30"), ("9981", "HNL-SIN", "332/3", "11/03/26 16:00-21:30")]
    u = C.unusual(rows, C.regular_set())
    # HNL-HNL test flight and the 99xx interisland positioning leg are not charters; cancelled rows are skipped
    assert [r["key"] for r in u] == ["9981|HNL-SIN|2026-11-03"]

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
    reg = C.regular_set("gum, lax")
    assert "GUM" in reg and "PPT" in reg and "MNL" not in reg  # option adds, never shrinks
    rows = C.unusual(C.parse_rows(TABLE), reg)
    known, new = C.merge({}, rows, "2026-11-04")
    assert sorted(new) == ["471|HNL-MNL|2026-11-05", "9980|SIN-HNL|2026-11-04"]
    known, new = C.merge(known, rows[:1], "2026-11-05")
    assert new == [] and known["471|HNL-MNL|2026-11-05"]["gone"] is True
    known, new = C.merge(known, [], "2026-12-10")
    assert "471|HNL-MNL|2026-11-05" in known  # the month before stays listed
    known, new = C.merge(known, [], "2027-01-10")
    assert known == {}
    known, _ = C.merge({}, rows, "2026-11-04")
    assert sorted(C.prune(known, C.regular_set("MNL"))) == ["9980|SIN-HNL|2026-11-04"]


def test_login_form_and_dates():
    action, f = C.login_form(LOGIN)
    assert action == "ctwc.aspx" and f["user"] == "ctl00$txtUsername" and f["pass"] == "ctl00$txtPassword"
    assert "__VIEWSTATE" in f["fields"]
    assert C.logged_in(TABLE) and not C.logged_in(LOGIN)
    assert C.logged_in("<html><body>CrewTrac Menu Home | Sign Out Options View Schedule Change Password</body></html>")
    ds = C.scan_dates(date(2026, 11, 4), 30)
    assert ds[0] == "2026-10-31" and ds[-1] == "2026-12-04" and len(ds) == 35
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
    assert len(rows) == 5 * 6 * 2 and len([u for u in s.urls if "ctw4190" in u]) == 12
