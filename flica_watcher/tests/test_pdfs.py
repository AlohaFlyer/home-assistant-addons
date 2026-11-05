"""Synthetic pairing-package and award text in the pdftotext -layout shape (no real crew data)."""
import pdfs
import versions as VER
from store import Store

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
