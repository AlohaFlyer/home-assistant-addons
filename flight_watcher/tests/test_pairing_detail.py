"""1.7.6 (Ryan, Nov 14: "when looking at schedules I want to be able to click on a pairing and have the actual pairing
pop open below the schedule so I can see the schedule detail"): the pairings package parse keeps each pairing's legs,
duties, layovers (station, time, hotel name, VAN) and totals in the card's pairing file (pairings_<YYYY-MM>.json,
"detail", parser version "dv"), so the schedule card can draw it like FLICA's pairing printout. A synthetic package
only: made-up pairings, flights, hotels and phone numbers (555 numbers, never kept)."""
import json
import os
import time

import pdfs
from test_crew_index import W  # noqa: F401  (the Watcher fixture)

R = " " * 100  # the operating calendar sits at column 100+
HDR = ("DAY   DH   FLTN        DPS -   ARS   DEPL/GMT       ARRL/GMT      BLKT   SGCRD   GRNT    EQP    TBLK       TCRD"
       "   DUTY  LAYO")
RULE = "=" * 120


def _cal(days, first=1, ndays=31, month="11"):
    """The calendar cells of a pairing that operates on `days` (day numbers of the period Nov 1 to Dec 1)."""
    cells = []
    for i in range(ndays):
        d = first + i
        dn = d if d <= 30 else d - 30
        cells.append(f"{dn:02d}" if d in days else "--")
    return [" ".join(cells[i:i + 7]) for i in range(0, ndays, 7)]


def package(rig_line=""):
    """November 2026, the period Nov 1 to Dec 1 (31 days). H9101: a 3-day trip on Thursdays (Nov 5, 12, 19, 26) with two
    layovers (SEA, then SFO after a deadhead), legs past local midnight, hotel lines with made-up phones and VANs.
    H9102: a 2-day LAX trip with a printed TRIP RIG (rig_line). H9103: a 717 interisland turn (not an A330 pairing)."""
    c1 = _cal({5, 12, 19, 26})
    c2 = _cal({2, 3, 4, 9, 10, 11, 16, 17, 18, 23, 24, 25, 30, 31})  # Mon to Wed, Dec 1 (the period's 31st day) too
    lines = [
        " " * 49 + "November 2026 Pairing Package",
        " " * 49 + "November 1 \u2014December 1 (31 Days)",
        RULE, HDR,
        "H9101                                  BASE REPT:     22:00L/08:00GMT" + " " * 40 + "Mo Tu We Th Fr Sa Su",
        "BASE : HNL         CA01FO01" + R + c1[0],
        "1          9001      HNL - SEA 23:00/09:00 06:42/14:42 5h42            5:42           332        5h42   5h42   6h57"
        "   10h18" + "      " + c1[1],
        "D-END: 06:57L/14:57GMT" + R + c1[2],
        "EXAMPLE LAKE HOTEL                                             (555)555-0100   VAN 16:15" + " " * 20 + c1[3],
        "                                         REPT: 17:15L/01:15GMT" + " " * 60 + c1[4],
        "2          9002      SEA - LAX 18:15/02:15 20:50/04:50 2h35            2:35           332",
        "2      DH 1127*      LAX - SFO 21:50/05:50 23:20/07:20 1h30            0:45    1:00 321        2h35   3h20   6h20"
        "   20h25",
        "D-END: 23:35L/07:35GMT",
        "EXAMPLE BAY INN                                                +1 555 555 0101   VAN 00:00",
        "                                         REPT: 20:00L/04:00GMT",
        "3          9003      SFO - HNL 21:00/05:00 00:50/10:50 5h50            5:50           332        5h50   5h50   7h05",
        "D-END: 01:05L/11:05GMT",
        "      TOTALS BLOCK 14h07     FDP 17h07    DHD 1h30     LDGS: 3    CREDIT 16h00    T.A.F.B. 51h05",
        RULE,
        "H9102                                  BASE REPT:     07:00L/17:00GMT",
        "BASE : HNL         CA01FO01RO01" + R + c2[0],
        "1          9011      HNL - LAX 08:00/18:00 15:30/23:30 5h30            5:30           332        5h30   5h30   7h45"
        "   26h15" + "      " + c2[1],
        "D-END: 15:45L/23:45GMT" + R + c2[2],
        "EXAMPLE PIER HOTEL      (555) 555-0102      VAN 16:30" + R + c2[3],
        "                                         REPT: 18:00L/02:00GMT" + " " * 60 + c2[4],
        "2          9012      LAX - HNL 19:00/03:00 22:45/08:45 5h45            5:45           332        5h45   5h45   4h00",
        "D-END: 23:00L/09:00GMT",
        "      TOTALS BLOCK 11h15     FDP 12h30    DHD 0h00     LDGS: 2    CREDIT 13h15    T.A.F.B. 40h00" + rig_line,
        RULE,
        "H9103                                  BASE REPT:     06:00L/16:00GMT",
        "BASE : HNL         CA01FO01",
        "1          100       HNL - OGG 07:00/17:00 07:45/17:45 0h45            0:45           717        0h45   0h45   2h00",
        "D-END: 08:00L/18:00GMT",
        "      TOTALS BLOCK 0h45     FDP 1h45    DHD 0h00     LDGS: 1    CREDIT 1h00    T.A.F.B. 2h00",
        RULE, ""]
    return "\n".join(lines)


def test_package_detail_keeps_legs_duties_layovers_and_totals():
    j = pdfs.package_json(package(), "test")
    assert [r[0] for r in j["rows"]] == ["H9101", "H9102"] and j["dv"] == pdfs.PKG_PARSER >= 2
    assert sorted(j["detail"]) == ["H9101", "H9102"]  # exactly the rows' pairings (the 717 turn is not ours)
    row = dict(zip(j["cols"], j["rows"][0]))
    assert row["route"] == "HNL-SEA-LAX-SFO-HNL" and row["rel_days"] == 3 and row["days"] == "5 12 19 26"
    d = j["detail"]["H9101"]
    assert (d["eq"], d["crew"], d["rept"]) == ("332", "CA01FO01", "22:00")
    assert len(d["duties"]) == 3
    d1, d2, d3 = d["duties"]
    # DAY, DH, flight, from, to, departure L, arrival L, block, segment credit, ground, equipment
    assert d1["legs"] == [["1", "", "9001", "HNL", "SEA", "23:00", "06:42", "5h42", "5:42", "", "332"]]
    assert (d1["rept"], d1["dend"], d1["stn"], d1["layo"]) == ("22:00", "06:57", "SEA", "10h18")
    assert (d1["tblk"], d1["tcrd"], d1["duty"], d1["tdhd"]) == ("5h42", "5h42", "6h57", "")
    assert d1["fdp"] == "6h42"  # report 08:00 GMT to the block-in at 14:42 GMT (FAR 117.3), Ryan's example
    assert (d1["hotel"], d1["van"]) == ("EXAMPLE LAKE HOTEL", "16:15")
    assert d2["legs"] == [["2", "", "9002", "SEA", "LAX", "18:15", "20:50", "2h35", "2:35", "", "332"],
                          ["2", "DH", "1127*", "LAX", "SFO", "21:50", "23:20", "1h30", "0:45", "1:00", "321"]]
    assert (d2["rept"], d2["dend"], d2["stn"], d2["layo"]) == ("17:15", "23:35", "SFO", "20h25")
    assert (d2["tdhd"], d2["fdp"], d2["duty"]) == ("1h30", "3h35", "6h20")  # the deadhead after the last flight: duty, no FDP
    assert (d2["hotel"], d2["van"]) == ("EXAMPLE BAY INN", "")  # VAN 00:00: no van time given
    assert d3["legs"][0][5:8] == ["21:00", "00:50", "5h50"]  # past local midnight, printed as the package gives it
    assert (d3["rept"], d3["dend"], d3["stn"], d3["layo"], d3["hotel"]) == ("20:00", "01:05", "HNL", "", "")
    assert (d3["fdp"], d3["duty"]) == ("6h50", "7h05")
    assert d["tot"] == {"block": "14h07", "fdp": "17h07", "dhd": "1h30", "ldgs": 3, "credit": "16h00", "tafb": "51h05",
                        "rig": "1h08", "rig_c": True}  # 16:00 credit less 14:52 segment credit, computed
    text = json.dumps(j)
    assert "555" not in text and "(" not in "".join(x["hotel"] for x in d["duties"])  # phone numbers are never kept
    # the rows are what they were before the detail came (the card's other readers see no change)
    assert j["cols"] == ["id", "report", "dep", "release", "rel_days", "first_duty_min", "route", "credit", "tafb", "days"]
    assert j["rows"] == pdfs.parse_package(package())


def test_printed_trip_rig_wins_and_hotel_with_spaced_phone():
    j = pdfs.package_json(package("    TRIP RIG 2h00"), "test")
    d = j["detail"]["H9102"]
    assert d["tot"]["rig"] == "2h00" and "rig_c" not in d["tot"]
    assert d["crew"] == "CA01FO01RO01" and d["duties"][0]["hotel"] == "EXAMPLE PIER HOTEL"
    assert d["duties"][0]["van"] == "16:30" and d["duties"][1]["rept"] == "18:00"
    assert j["detail"]["H9101"]["tot"]["rig_c"] is True  # the other pairing prints none: computed
    assert pdfs.package_json(package("    TRIP RIG: 2:00"), "t")["detail"]["H9102"]["tot"]["rig"] == "2h00"


def test_existing_fixture_and_missing_rept_line():
    """The FW-0014 fixture of test_pdfs (no REPT line before a duty): the report is the release plus the layover."""
    from test_pdfs import LEGS, PKG, _pkg
    from datetime import date
    d = pdfs.package_json(PKG, "t")["detail"]["H9001"]
    assert [x["legs"][0][1] for x in d["duties"]] == ["DH", ""] and d["duties"][0]["legs"][0][9] == "1:25"
    assert d["duties"][0]["tdhd"] == "0h45" and d["tot"]["dhd"] == "0h45"
    p = _pkg("December 2026", "December 2 \u2014December 31 (30 Days)", date(2026, 12, 2), 30, {"H9001": {date(2026, 12, 3)}})
    dd = pdfs.package_json(p, "t")["detail"]["H9001"]["duties"]
    assert dd[1]["rept"] == "" and dd[1]["fdp"] == "6h00"  # no REPT line: none printed, FDP from release + layover
    assert "LAX - HNL" in LEGS


def test_caps_and_crafted_lines_stay_fast():
    """A pilot's approved upload is untrusted: legs and duties are capped, fields are short, a crafted long line is read
    in linear time."""
    leg = "1          9001      HNL - SEA 23:00/09:00 06:42/14:42 5h42            5:42           332"
    many = package().replace(
        "2          9002      SEA - LAX 18:15/02:15 20:50/04:50 2h35            2:35           332",
        "\n".join([leg] * 80))
    d = pdfs.package_json(many, "t")["detail"]["H9101"]
    assert sum(len(x["legs"]) for x in d["duties"]) <= pdfs.DETAIL_MAX_LEGS == 30
    dends = package().replace("D-END: 23:35L/07:35GMT", "\n".join(["D-END: 23:35L/07:35GMT", leg] * 40))
    assert len(pdfs.package_json(dends, "t")["detail"]["H9101"]["duties"]) <= pdfs.DETAIL_MAX_DUTIES == 12
    huge = "EXAMPLE " + "X" * 300 + "   VAN 16:15"
    d1 = pdfs.package_json(package().replace("EXAMPLE LAKE HOTEL", huge.split("   VAN")[0]), "t")["detail"]["H9101"]
    assert len(d1["duties"][0]["hotel"]) <= 80
    for bad in ("1 " + " 9" * 100000, "1          9001      HNL - SEA " + "1:00/" * 40000, "D-END: " + "1" * 200000,
                "      TOTALS BLOCK " + "1h00 " * 40000, "   REPT: " + "9" * 200000, "x VAN " * 40000):
        t0 = time.time()
        pdfs.package_json(package().replace("D-END: 06:57L/14:57GMT", "D-END: 06:57L/14:57GMT\n" + bad), "t")
        assert time.time() - t0 < 1.0, bad[:40]


def test_uploads_reparse_an_older_pairings_file_once(W, tmp_path, monkeypatch):  # noqa: F811
    """A package text copy marked done by an older Watcher (its mark is the file time only) is read again once, so the
    pairing files on Home Assistant gain the detail without a new upload; the file is written whole (a temp file moved
    into place, none left behind)."""
    up = tmp_path / "uploads"
    up.mkdir()
    monkeypatch.setattr(W, "UPLOADS", str(up))
    path = up / "2026-11_pairings.txt"
    path.write_text(package())
    out = os.path.join(W.CARD_PAIRINGS, "pairings_2026-11.json")
    os.makedirs(W.CARD_PAIRINGS, exist_ok=True)
    with open(out, "w") as f:  # what 1.7.5 wrote: no detail
        json.dump({k: v for k, v in pdfs.package_json(package(), "old").items() if k not in ("detail", "dv")}, f)
    W.S["uploads_done"] = {"2026-11_pairings.txt": f"{os.path.getmtime(path):.0f}"}
    W.uploads_check()
    j = json.load(open(out))
    assert j["dv"] == pdfs.PKG_PARSER and "H9101" in j["detail"]
    mark = W.S["uploads_done"]["2026-11_pairings.txt"]
    assert mark == f"{os.path.getmtime(path):.0f}|p{pdfs.PKG_PARSER}"
    os.utime(out, (1, 1))
    W.uploads_check()  # marked done for this parser: not read again
    assert os.path.getmtime(out) == 1
    assert not [n for n in os.listdir(W.CARD_PAIRINGS) if n.endswith(".tmp") or n.startswith(".pairings")]
    assert W.DB.get("pkg_details:2026-11")["H9101"]["route"] == "HNL-SEA-LAX-SFO-HNL"
