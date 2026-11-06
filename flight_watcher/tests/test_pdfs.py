"""Synthetic pairing-package and award text in the pdftotext -layout shape (no real crew data)."""
import json
from datetime import date, timedelta

import pytest

import crewidx as CI
import pdfs
import versions as VER
from store import Store
from test_crew_index import W  # noqa: F401  (the Watcher fixture)

R = " " * 100  # the operating calendar sits at column 100+
PKG = (
    "                                                 November 2026 Pairing Package\n"
    "                                                 November 1 —December 1 (31 Days)\n"
    "========================================================================================================================\n"
    "DAY   DH   FLTN        DPS -   ARS   DEPL/GMT       ARRL/GMT      BLKT   SGCRD   GRNT    EQP    TBLK       TCRD   DUTY  LAYO\n"
    "H9001                                  BASE REPT:     10:00L/20:00GMT" + " " * 40 + "Mo Tu We Th Fr Sa Su\n"
    "BASE : HNL         CA01FO01" + R + "01\n"
    "1      DH 1126*      HNL - OGG 11:00/21:00 11:45/21:45 0h45            0:00    1:25 717\n"
    "1          900       OGG - LAX 12:30/22:30 20:30/04:30 5h00            5:00           332        5h00   5h00   8h00   24h00" + " " * 6 + "02 -- -- -- -- -- --\n"
    "D-END: 20:45L/04:45GMT" + R + "-- -- -- -- -- -- --\n"
    "                                         REPT: 20:45L/04:45GMT" + " " * 60 + "-- -- -- -- -- -- --\n"
    "2          901       LAX - HNL 21:45/05:45 00:45/10:45 6h00            6:00           332        6h00   6h00   7h00" + " " * 14 + "-- -- -- -- -- -- --\n"
    "D-END: 01:00L/11:00GMT" + R + "30 01\n"
    "      TOTALS BLOCK 11h00     FDP 15h00    DHD 0h45     LDGS: 2    CREDIT 12h00    T.A.F.B. 39h00\n"
    "========================================================================================================================\n"
    "H9002                                  BASE REPT:     10:00L/20:00GMT\n"
    "BASE : SEA         CA01FO01\n"
    "1          902       SEA - HNL 11:00/21:00 16:00/02:00 5h00            5:00           789        5h00   5h00   6h00\n"
    "D-END: 16:15L/02:15GMT\n"
    "      TOTALS BLOCK 5h00     FDP 6h00    DHD 0h00     LDGS: 1    CREDIT 5h00    T.A.F.B. 6h15\n"
    "========================================================================================================================\n")


def test_package_rows_and_details():
    j = pdfs.package_json(PKG, "test")
    assert j["month"] == "2026-11" and len(j["rows"]) == 1  # the SEA 789 pairing is not ours
    r = j["rows"][0]
    assert r[:4] == ["H9001", "10:00", "11:00", "01:00"] and r[4] == 2 and r[6] == "HNL-OGG-LAX-HNL"
    assert r[7] == "12h00" and r[8] == "39h00" and r[9] == "1 2 30 D1"
    d = pdfs.package_details(PKG)["H9001"]
    assert d["block"] == "11:00" and d["lay"] == "LAX"
    assert [(x["dep"], x["arr"], x["blk"], x["d"]) for x in d["duties"]] == [(660, 1050, 300, 0), (2625, 2985, 360, 1)]  # HST from the GMT columns; 2nd duty = release + 24h00 layover


AWARD = (
    "                                      A332FO PBS BIDLINE AWARD\n"
    "                                         Posted October 12, 2026\n"
    "                 C/IN   Sun      Mon      Tue\n"
    "                        1        2        3        4        5        6        7        8        9        10\n"
    "\n"
    "                                 LAX\n"
    "00999 / 1234                     10:00\n"
    "DOE                                       01:00\n"
    "Cr:022:00                        012:00                     010:00\n"
    "Days Off: 25                     H9001                      VA\n"
    "                                 RO\n")


def test_award_line_and_version_001(tmp_path):
    det = pdfs.package_details(PKG)
    aw = pdfs.parse_award(AWARD, "1234", det, "2026-11")
    assert [(i["trip"], i["start"], i["end"]) for i in aw["items"]] == [("H9001", "2026-11-02", "2026-11-04"), ("VAC", "2026-11-05", "2026-11-06")]
    assert aw["trips"]["H9001|2026-11-02"]["seat"] == "RO" and aw["totals"] == {"credit": "22:00", "days_off": 25}
    assert aw["days"][1] == ["2026-11-02", "H9001", "LAX"] and aw["days"][3] == ["2026-11-04", "", "HNL"]
    assert pdfs.parse_award(AWARD, "5678", det, "2026-11") is None
    db = Store(str(tmp_path / "v.db"))
    VER.update(db, {"2026-11": {"items": [{"trip": "H9002", "start": "2026-11-04"}], "days": [["2026-11-04", "H9002", "LAX"]], "totals": {}}}, {}, "t1")
    vers = VER.set_award(db, "2026-11", aw, "t2")
    assert [v["ver"] for v in vers] == ["11.001", "11.002"] and vers[0]["award"] and "added H9002 2026-11-04" in vers[1]["changes"]
    assert [v["ver"] for v in VER.set_award(db, "2026-11", aw, "t3")] == ["11.001", "11.002"]  # a re-upload replaces the award


# ---------------------------------------------------------------- FW-0014: a bid period that starts last month
LEGS = (
    "1          900       HNL - LAX 12:30/22:30 20:30/04:30 5h00            5:00           332        5h00   5h00   8h00   24h00\n"
    "D-END: 20:45L/04:45GMT\n"
    "2          901       LAX - HNL 21:45/05:45 00:45/10:45 6h00            6:00           332        6h00   6h00   7h00\n"
    "D-END: 01:00L/11:00GMT\n"
    "      TOTALS BLOCK 11h00     FDP 15h00    DHD 0h00     LDGS: 2    CREDIT 12h00    T.A.F.B. 39h00\n")


def _pkg(title, period, first, ndays, ops):
    """A synthetic package: one A332 HNL pairing per entry of ops {pairing: set of operating dates}, each with
    a calendar of ndays cells from `first` (7 a row at column 100+, '--' = not operating)."""
    out = (f"                                                 {title} Pairing Package\n"
           f"                                                 {period}\n" + "=" * 120 + "\n")
    for pid, dates in ops.items():
        cells = [f"{(first + timedelta(days=i)).day:02d}" if first + timedelta(days=i) in dates else "--" for i in range(ndays)]
        cal = "".join(R + " ".join(cells[i:i + 7]) + "\n" for i in range(0, ndays, 7))
        out += (f"{pid}                                  BASE REPT:     10:00L/20:00GMT\n"
                "BASE : HNL         CA01FO01\n" + cal + LEGS + "=" * 120 + "\n")
    return out


def test_period_starting_last_month_is_not_a_month_late(tmp_path):
    """FW-0014: January 2027 runs Dec 31 to Jan 30 and February Jan 31 to Mar 1. Before the fix the January
    file read '31 D1 D15 D30' (Jan 31, Feb 1, ...) and February's 'D31 D1 D28 D1' (all a month late)."""
    jan = _pkg("January 2027", "December 31 —January 30 (31 Days)", date(2026, 12, 31), 31,
               {"H9001": {date(2026, 12, 31), date(2027, 1, 1), date(2027, 1, 15), date(2027, 1, 30)},
                "H9002": {date(2026, 12, 31)}})
    feb = _pkg("February 2027", "January 31 —March 1 (30 Days)", date(2027, 1, 31), 30,
               {"H9003": {date(2027, 1, 31), date(2027, 2, 1), date(2027, 2, 28), date(2027, 3, 1)}})
    assert pdfs.period_start(jan) == date(2026, 12, 31) and pdfs.period_start(feb) == date(2027, 1, 31)
    jj, fj = pdfs.package_json(jan, "t"), pdfs.package_json(feb, "t")
    assert (jj["month"], jj["start"], jj["end"]) == ("2027-01", "2026-12-31", "2027-01-30")
    assert (fj["start"], fj["end"]) == ("2027-01-31", "2027-03-01")
    assert [r[9] for r in jj["rows"]] == ["31 1 15 30", "31"]
    assert [r[9] for r in fj["rows"]] == ["31 1 28 D1"]
    www = tmp_path / "www"
    www.mkdir()
    for j in (jj, fj):
        (www / f"pairings_{j['month']}.json").write_text(json.dumps(j))
    ins = CI.instances(str(www))
    assert sorted(ins) == ["H9001|2026-12-31", "H9001|2027-01-01", "H9001|2027-01-15", "H9001|2027-01-30",
                           "H9002|2026-12-31",  # a lone '31': the file's start says Dec 31, not Jan 31
                           "H9003|2027-01-31", "H9003|2027-02-01", "H9003|2027-02-28", "H9003|2027-03-01"]
    assert ins["H9002|2026-12-31"]["period"] == "2027-01" and ins["H9002|2026-12-31"]["month"] == "2026-12"
    assert CI.period_start(str(www), "2027-01") == "2026-12-31" and CI.period_end(str(www), "2027-01") == "2027-01-30"
    assert CI.grid_range(str(www), "2027-02") == ("2027-01-30", "2027-01-31", "2027-03-01")


def test_period_inside_the_month_and_november_unchanged():
    dec = _pkg("December 2026", "December 2 —December 31 (30 Days)", date(2026, 12, 2), 30,
               {"H9001": {date(2026, 12, 2), date(2026, 12, 31)}})
    j = pdfs.package_json(dec, "t")
    assert (j["start"], j["end"], j["rows"][0][9]) == ("2026-12-02", "2026-12-31", "2 31")
    p = pdfs.package_json(PKG, "t")
    assert (p["start"], p["end"], p["rows"][0][9]) == ("2026-11-01", "2026-12-01", "1 2 30 D1")
    assert pdfs.period_start("no period line", "2026-12") == date(2026, 12, 1) and pdfs.period_bounds("nothing") == ("", "")


# ---------------------------------------------------------------- FW-0015: an award whose period starts on the 2nd
def _hdr(days):
    """An award date header: one column per day, 9 wide from column 24 (as AWARD prints 1 to 10)."""
    return (" " * 24 + "".join(f"{d:<9}" for d in days)).rstrip()


def _award(days):
    """AWARD with its date header replaced (H9001 sits in the 2nd column, VA in the 5th)."""
    lines = AWARD.splitlines()
    lines[3] = _hdr(days)
    return "\n".join(lines) + "\n"


def test_award_december_starts_on_the_2nd(tmp_path):
    """FW-0015: December runs Dec 2 to 31, so its header reads '2 3 ... 31'. Before the fix that raised
    StopIteration (the header had to start '1 2 3') and the award never became 12.001."""
    det = pdfs.package_details(PKG)
    text = _award(range(2, 32))
    for pstart in (None, "2026-12-02"):
        aw = pdfs.parse_award(text, "1234", det, "2026-12", pstart)
        assert [(i["trip"], i["start"], i["end"]) for i in aw["items"]] == [
            ("H9001", "2026-12-03", "2026-12-05"), ("VAC", "2026-12-06", "2026-12-07")]
        assert aw["days"][0] == ["2026-12-02", "", ""] and aw["days"][1] == ["2026-12-03", "H9001", "LAX"]
        assert aw["days"][-1][0] == "2026-12-31" and len(aw["days"]) == 30
        assert "H9001|2026-12-03" in aw["trips"]
    db = Store(str(tmp_path / "v.db"))
    assert [v["ver"] for v in VER.set_award(db, "2026-12", aw, "t1")] == ["12.001"]


def test_award_full_width_november_header():
    """FW-0015 review: the real November award (11.001 on Pako) was read by the old '^\\s+1\\s+2\\s+3\\s' matcher, which
    let anything follow the days. A full-width header ('1 2 ... 30 1', the period Nov 1 to Dec 1) reads as before,
    and so does one with text after the run of days (a label, a stray mark); text before the days is no header."""
    det = pdfs.package_details(PKG)
    want = [("H9001", "2026-11-02", "2026-11-04"), ("VAC", "2026-11-05", "2026-11-06")]
    full = list(range(1, 31)) + [1]
    for tail in ("", "   C/OUT", " |", "  Total  31"):
        lines = AWARD.splitlines()
        lines[3] = _hdr(full) + tail
        text = "\n".join(lines) + "\n"
        cols = pdfs._day_header(lines[3])
        assert [d for _, d in cols] == full and cols[1][0] == 33  # the days only, the 2nd column where H9001 sits
        aw = pdfs.parse_award(text, "1234", det, "2026-11")
        assert [(i["trip"], i["start"], i["end"]) for i in aw["items"]] == want
        assert aw["trips"]["H9001|2026-11-02"]["seat"] == "RO" and aw["totals"] == {"credit": "22:00", "days_off": 25}
        assert aw["days"][0][0] == "2026-11-01" and aw["days"][-1][0] == "2026-12-01"  # the period's 31 days
        assert aw["days"][1] == ["2026-11-02", "H9001", "LAX"]
    # the 10 column fixture with text after it, and a run that breaks: the days up to the break
    assert pdfs._day_header(AWARD.splitlines()[3] + "   (HST)") == pdfs._day_header(AWARD.splitlines()[3])
    assert [d for _, d in pdfs._day_header(_hdr([1, 2, 3, 4, 5, 6, 7, 9, 10]))] == [1, 2, 3, 4, 5, 6, 7]
    assert pdfs._day_header("Days " + _hdr(full)) is None and pdfs._day_header(_hdr([0, 1, 2, 3, 4, 5, 6, 7])) is None


def test_award_header_first_day():
    """FW-0015: the header's first column, from the header itself or the package's period start."""
    hdr = lambda days: pdfs._day_header(_hdr(days))
    assert pdfs.award_start(hdr(list(range(1, 31)) + [1]), "2026-11") == date(2026, 11, 1)
    assert pdfs.award_start(hdr(range(2, 32)), "2026-12") == date(2026, 12, 2)
    assert pdfs.award_start(hdr([31] + list(range(1, 31))), "2027-01") == date(2026, 12, 31)
    assert pdfs.award_start(hdr([31] + list(range(1, 29)) + [1]), "2027-02") == date(2027, 1, 31)
    assert pdfs.award_start(hdr(range(2, 32)), "2026-12", "2026-12-02") == date(2026, 12, 2)
    assert pdfs.award_start(hdr(range(2, 32)), "2026-12", "junk") == date(2026, 12, 2)
    assert hdr([1, 2, 3]) is None and hdr([1, 2, 4, 5, 6, 7, 8, 9]) is None
    assert pdfs._day_header("00999 / 1234   10:00") is None
    no_hdr = AWARD.replace(AWARD.splitlines()[3], "")
    with pytest.raises(ValueError):
        pdfs.parse_award(no_hdr, "1234", {}, "2026-11")
    # a January award running Dec 31 to Jan 30: H9001 in the 2nd column is Jan 1
    aw = pdfs.parse_award(_award([31] + list(range(1, 31))), "1234", pdfs.package_details(PKG), "2027-01")
    assert aw["items"][0]["start"] == "2027-01-01" and aw["days"][0][0] == "2026-12-31" and aw["days"][-1][0] == "2027-01-30"


def test_uploads_december_package_and_award(W, tmp_path, monkeypatch):
    """FW-0014 / FW-0015 through the Watcher's Web UI uploads: the December package writes start / end into the
    pairing file, the December award (header from the 2nd) becomes 12.001; an award with no date header is
    logged once and not retried every check."""
    up = tmp_path / "uploads"
    up.mkdir()
    monkeypatch.setattr(W, "UPLOADS", str(up))
    W.S["own_emp"] = "1234"
    dec = _pkg("December 2026", "December 2 —December 31 (30 Days)", date(2026, 12, 2), 30,
               {"H9001": {date(2026, 12, 3), date(2026, 12, 20)}})
    (up / "2026-12_pairings.txt").write_text(dec)
    (up / "2026-12_award.txt").write_text(_award(range(2, 32)))
    (up / "2026-11_award.txt").write_text(AWARD.replace(AWARD.splitlines()[3], ""))
    W.DB.put("pkg_details:2026-11", pdfs.package_details(PKG))
    W.uploads_check()
    pj = json.loads((tmp_path / "www" / "pairings_2026-12.json").read_text())
    assert (pj["start"], pj["end"], pj["rows"][0][9]) == ("2026-12-02", "2026-12-31", "3 20")
    vers = W.DB.get("sched_versions:2026-12")
    assert [v["ver"] for v in vers] == ["12.001"] and vers[0]["items"][0] == {
        "trip": "H9001", "start": "2026-12-03", "end": "2026-12-05", "lay": "LAX"}
    assert W.DB.get("sched_versions:2026-11") is None and "2026-11_award.txt" in W.S["uploads_done"]
