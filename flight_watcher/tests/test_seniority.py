"""FW-0062: the pilot seniority list parser, on a made-up list in the pdftotext -layout shape (every name and number
in tests/fixtures/seniority_synthetic.txt is invented)."""
import seniority as SEN


def _parsed(fx, ref=2026):
    return SEN.parse(fx("seniority_synthetic.txt"), ref)


def test_reads_every_pilot_once(fx):
    p = _parsed(fx)
    assert [r["sen"] for r in p["rows"]] == list(range(1, 13)) and p["rejects"] == []
    assert p["sections"] == {"SENIORITY": 12, "ALPHABETICAL": 5, "A330 CAPTAINS": 2, "MANDATORY AGE 65 RETIREMENT AGE": 2}
    by = {r["sen"]: r for r in p["rows"]}
    assert (by[1]["name"], by[1]["emp"], by[1]["doh"], by[1]["seat"], by[1]["equip"], by[1]["listed"]) == (
        "Doe, Jane", "901", "1988-05-01", "CA", "330", 4)
    assert by[5]["name"] == "O'Doe, Mary Ann" and by[3]["name"] == "Van Doe, Karen"
    assert (by[6]["name"], by[6]["doh"], by[6]["equip"]) == ("Poe, Edgar", "2002-01-07", "767")  # no ALPA number
    # the cover letter, 'YYYY = n PILOTS' lines, 'Page N' footers and the summary page are not rows
    assert not any(r["name"].startswith(("The ", "Page", "Total")) for r in p["rows"])
    assert p["list_date"] == ""  # the cover text names a month, not a date


def test_crowded_columns(fx):
    by = {r["sen"]: r for r in _parsed(fx)["rows"]}
    # the short name runs into the employee number; a long last name is cut short on a crowded page and read whole
    # from the alphabetical listing
    assert (by[8]["emp"], by[8]["name"], by[8]["listed"]) == ("90008", "Doe-Smitherson, John", 2)
    assert (by[9]["emp"], by[9]["name"]) == ("9009", "Roe Jr, Robert")
    # LAST and FIRST glued ('MOEKAI') or the first name touching the date ('ZACHARIAH04/22/19'): the cleaner listing wins
    assert (by[10]["name"], by[10]["doh"]) == ("Moe, Kai", "2018-10-03")
    assert (by[11]["name"], by[11]["doh"]) == ("Zoe, Zachariah", "2019-04-22")


def test_two_digit_years_and_conflicts():
    hdr = "SEN   NAME, Initial   EMP #   ALPA #   LAST NAME   FIRST NAME   DOH   DOR   EQUIP   SEAT\n"
    t = ("SENIORITY\n" + hdr + "  1   DOE, J.   901   990001   DOE   JANE   05/01/88   May-28 330 CA\n"
         "  2   ROE, R.   902   990002   ROE   RICK   03/19/25   Jun-60 330 FO\n"
         "ALPHABETICAL\n" + hdr + "  1   DOE, J.   901   990001   DOE   JANE   05/02/88   May-28 330 CA\n")
    p = SEN.parse(t, 2026)
    assert [r["doh"] for r in p["rows"]] == ["1988-05-01", "2025-03-19"]  # 88 is 1988, 25 (not after the list) 2025
    assert SEN.parse(t, 2024)["rows"][1]["doh"] == "1925-03-19"  # a list from 2024 cannot hold a 2025 hire
    assert p["rejects"] == [("conflict-doh", 7)]  # a repeat that disagrees is reported, the first listing is kept
    assert SEN.parse("1   DOE, J.   901   990001   DOE   JANE   05/01/88   May-28 330 CA\n")["rows"] == []  # no header
    assert SEN.parse("")["rows"] == [] and SEN.parse("Minutes of the meeting, 3/1/2026")["rows"] == []


def test_list_date_from_the_cover_text():
    assert SEN.list_date("Pilot Seniority List effective March 1, 2026\nSEN NAME EMP # DOH") == "2026-03-01"
    assert SEN.list_date("SENIORITY LIST as of 01 MAR 2026\n") == "2026-03-01"
    assert SEN.list_date("Seniority list dated 3/1/2026\n") == "2026-03-01"
    assert SEN.list_date("Protests are due by April 15, 2026.\n") == ""  # a date with no list wording is not the list's
    hdr = "SEN   NAME, Initial   EMP #   ALPA #   LAST NAME   FIRST NAME   DOH   DOR   EQUIP   SEAT\n"
    assert SEN.list_date(hdr + "  1   DOE, J.   901   990001   DOE   JANE   effective 5/1/1988\n") == ""  # rows: never


def test_json_and_lookup(fx):
    d = SEN.to_json(_parsed(fx), "seniority_2026-11-06.pdf", "2026-11-06T09:00:00-10:00", "2026-03-01")
    assert (d["count"], d["list_date"], d["newest_doh"], d["parser"], d["rejects"]) == (12, "2026-03-01", "2019-08-05", SEN.PARSER, 0)
    assert d["pilots"]["901"] == {"sen": 1, "name": "Doe, Jane", "last": "Doe", "doh": "1988-05-01", "seat": "CA", "equip": "330"}
    # two pilots share 90011 in the source list: the crew line's last name decides; the number alone does not
    assert [x["sen"] for x in [d["pilots"]["90011"]] + d["pilots"]["90011"]["also"]] == [11, 12]
    assert SEN.find(d, "90011", "Noe, Nina")["sen"] == 12 and SEN.find(d, "90011", "ZOE, ZACHARIAH")["sen"] == 11
    assert SEN.find(d, "90011") is None and SEN.find(d, "90011", "Poe, Pat") is None
    assert SEN.find(d, "00901")["sen"] == 1  # leading zeros
    assert SEN.find(d, "99999", "Van Doe, Karen")["sen"] == 3  # not on the list by number: last and first name
    assert SEN.find(d, "", "Roe Jr, Robert")["sen"] == 9 and SEN.find(d, "", "Doe, Jack") is None
    assert SEN.find(d, "", "Roe, Robert")["sen"] == 9  # a Jr / Sr the crew line leaves out does not matter
    assert SEN.find(d, "", "Roe, R") is None  # first given name, whole: no guessing from an initial
    assert SEN.find({}, "901") is None and SEN.find(None, "901", "Doe, Jane") is None
