"""1.7.20 (Ryan, Nov 20, 2026: "I need this page to calculate per FAR 117 and PWA when I timeout, both for if I extend or
if I do not. Add that number in bold with a dark orange square around it right of the report time", and "the number I
need to know is when is the last moment I can block out and be legal"): the last legal block-out and the duty limits
(timeout.py, FOM 125.4 4.3.2 = 14 CFR 117 Tables A, B and C; FOM 5.1.23.7 and 5.1.23.8 crew rest; PWA 2.19.b), as
working.py puts them on sensor.<prefix>_working_flight, and the layover card's box in a real Chromium.

Synthetic data only: made-up pairings (H39xx), flight numbers (9xxx), dates (2027), stations and times, and crew ("Doe,
Jane"). The first case has the shape the rules were checked on by hand: an unacclimated 3-pilot return after a 24 h
layover more than 60 degrees from HNL, with flight time binding the on-time block-in; its numbers are worked out by hand
in the comments."""
import copy
import json
import os
from datetime import date, datetime, timedelta, timezone

import pytest

import timeout as TO
import working as WK
from pot import LEG_DOW, parse_duties, parse_legs

HST = timezone(timedelta(hours=-10))
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CREW3 = ["CA Doe, Jane (10001)", "FO Roe, Rick (10002)", "RO Poe, Pat (10003)"]
CREW2 = ["CA Doe, Jane (10001)", "FO Roe, Rick (10002)"]
CREW4 = CREW3 + ["FO Moe, Max (10004)"]


def at(y, mo, d, hm):
    h, m = map(int, hm.split(":"))
    return datetime(y, mo, d, h, m, tzinfo=HST)


def text(day0, legs):
    """A pairing page's leg lines from (day offset, flight, from, to, out, in, block) as FLICA prints them (station
    local times, HHMM), the day code from the trip's first day."""
    out = []
    for k, flt, a, b, dep, arr, blk in legs:
        dow = LEG_DOW[((day0 + timedelta(days=k)).weekday() + 1) % 7].lower()
        hhmm = [x.replace(":", "").zfill(4) for x in (dep, arr, blk)]
        out.append(f"{dow} {flt} {a.lower()}-{b.lower()} {' '.join(hhmm)}")
    return " ".join(out)


def trip(key, report, legs, crew=CREW2, legs_read=True, end=None):
    """(item, record) of a trip: the record as own_trip_times keeps it (legs only when read)."""
    pid, start = key.split("|")
    d0 = date.fromisoformat(start)
    t = text(d0, legs)
    rec = {"report": report, "duties": parse_duties(t), "crew": list(crew)}
    if legs_read:
        rec["legs"] = parse_legs(t)
    end = end or (d0 + timedelta(days=max(x[0] for x in legs) + 1)).isoformat()
    return {"trip": pid, "start": start, "end": end, "lay": ""}, rec


def months_for(*mks):
    """Schedule months on file (S['schedule'] shape): every day of each month listed."""
    out = {}
    for mk in mks:
        y, m = map(int, mk.split("-"))
        d, days = date(y, m, 1), []
        while d.month == m:
            days.append([d.isoformat(), "", ""])
            d += timedelta(days=1)
        out[mk] = {"days": days, "items": []}
    return out


def run(trips, now, pkg=None, months=None, extra_items=(), domestic=()):
    items, own = [], {}
    for key, it in trips:
        items.append(it[0])
        own[key] = it[1]
    items += list(extra_items)
    return WK.working_flight(items, own, now, 2, pkg=pkg, months=months, domestic=domestic)


# ---------------------------------------------------------------- the acceptance case (synthetic)
# Duty periods before it (duties-only records, as a trip read before 1.4.9 keeps them): SEA, NRT, LAS, SYD and OAK trips
HIST = {
    "H3951|2027-01-21": ("06:00", [(0, "9051", "HNL", "SEA", "07:00", "14:25", "5:25"),
                                   (2, "9052", "SEA", "HNL", "10:05", "13:55", "5:50")]),
    "H3952|2027-01-26": ("12:30", [(0, "9053", "HNL", "NRT", "13:30", "17:10", "8:40"),
                                   (3, "9054", "NRT", "HNL", "21:00", "08:50", "6:50")]),
    "H3953|2027-02-02": ("22:30", [(0, "9055", "HNL", "LAS", "23:30", "07:25", "5:55"),
                                   (2, "9056", "LAS", "HNL", "07:40", "11:40", "6:00")]),
    "H3954|2027-02-08": ("09:40", [(0, "9057", "HNL", "SYD", "10:40", "18:20", "10:40"),
                                   (3, "9058", "SYD", "HNL", "20:15", "09:05", "9:50")]),
    "H3955|2027-02-13": ("05:45", [(0, "9059", "HNL", "OAK", "06:45", "14:05", "5:20"),
                                   (1, "9060", "OAK", "HNL", "08:30", "12:05", "5:35")]),
}
# HNL-BOS (in 02:10 HST Feb 18, release 02:25), then BOS-HNL out 09:15 EST (04:15 HST) Feb 19, block 11:30, in 15:45 HST
BOS_TRIP = ("H3958|2027-02-17", "15:20", [(0, "9061", "HNL", "BOS", "16:20", "07:10", "9:50"),
                                          (2, "9062", "BOS", "HNL", "09:15", "15:45", "11:30")])
BOS_PKG = {"eq": "332", "crew": "CA01FO01RO01"}


def acceptance(pkg=None, months="default", hist=True, now=None, legs_read=False):
    trips = [(k, trip(k, r, legs, ["CA", "FO"], legs_read=legs_read)) for k, (r, legs) in HIST.items()] if hist else []
    key, rep, legs = BOS_TRIP
    trips.append((key, trip(key, rep, legs, CREW3)))
    pkg = {key: BOS_PKG} if pkg is None else pkg
    return run(trips, now or at(2027, 2, 19, "01:00"), pkg,
               months_for("2027-01", "2027-02") if months == "default" else months)


def test_acceptance_bos_hnl_unacclimated_three_pilots_last_out_and_flight_time():
    """By hand: report 1:15 before 09:15 EST = 08:00 EST, 03:00 HST (PWA 2.19.b.1). Free since the BOS release (02:10 +
    0:15 HST Feb 18) 24:35 < 36 h, in the BOS theater 24:50 < 72 h, BOS 87 deg from HNL: not acclimated, HNL time 03:00.
    Table C 0000-0559, Class 1 (A330 LDMCR), 3 pilots: 15:00 less 0:30 = 14:30, FDP end 17:30 HST, 19:30 with the
    extension. Last out = 17:30 less 11:30 = 06:00 HST = 11:00 EST; with the extension 08:00 HST = 13:00 EST. Flight
    time 11:30 of 13:00, 1:30 spare; out on time the block-in is due by 04:15 + 13:00 = 17:15 HST, with or without the
    extension (it adds no flight time). Class 2: 13:30, ends 16:30 (last out 10:00 EST); Class 3 12:30, 15:30 (09:00 EST).
    100 h in 672 h from Jan 22 15:45: 5:50 + 8:40 + 6:50 + 5:55 + 6:00 + 10:40 + 9:50 + 5:20 + 5:35 + 9:50 + 11:30 =
    86:00. 60 h in 168 h from Feb 12 15:45: 6:20 + 6:50 + 10:50 + 12:45 = 36:45."""
    r = acceptance()
    a = r["attributes"]
    assert r["state"] == "HA9062 BOS-HNL" and a["leg"] == "2 of 2" and a["report"] == "08:00 local, 03:00 HST"
    t = a["timeout"]
    assert t["legal"] is True and t["sure"] is True and t["unsure"] == [] and t["flags"] == []
    lo, lx = t["last_out"], t["last_out_ext"]
    assert (lo["txt"], lo["hst"], lo["day"], lo["wd"], lo["z"]) == ("11:00 EST", "06:00 HST", "Fri Feb 19", "", "16:00Z")
    assert lo["short"] == "FDP 14:30" and lo["by"] == "FDP 14:30 (FAR 117.17, Table C)" and lo["early"] is False
    assert lo["leg"] == "BOS-HNL" and lo["sure"] is True
    assert (lx["txt"], lx["hst"], lx["short"]) == ("13:00 EST", "08:00 HST", "FDP + 2:00 ext")
    assert t["ft"]["txt"] == "11:30 of 13:00 (1:30 spare)" and t["ft"]["short"] == "FT 11:30 of 13:00"
    assert (t["ft"]["planned"], t["ft"]["spare"], t["ft"]["limit"]) == ("11:30", "1:30", "13:00")
    # the block-in limits with the leg out on time (no_ext / ext) and of the FDP itself
    n, x, f = t["no_ext"], t["ext"], t["fdp"]
    assert (n["txt"], n["day"], n["local"], n["z"]) == ("17:15 HST", "Fri Feb 19", "17:15 HST", "03:15Z")
    assert n["by"] == "13:00 flight time (FAR 117.11)" and n["short"] == "13:00 flight time"
    assert n["at"] == "2027-02-19T17:15:00-10:00" and n["release_txt"] == "17:30 HST"
    assert x["txt"] == "17:15 HST" and x["by"] == "13:00 flight time; FDP with 2:00 extension 19:30 HST"
    assert (f["limit"], f["end_txt"], f["ext_end_txt"], f["table"]) == ("14:30", "17:30 HST", "19:30 HST", "C")
    assert (f["in_txt"], f["ext_in_txt"], f["release_txt"], f["ext_release_txt"]) == (
        "17:30 HST", "19:30 HST", "17:45 HST", "19:45 HST")
    assert f["row"] == "0000-0559 (HNL time 03:00)" and f["acclimated"] is False and f["other"] is None
    assert (f["pilots"], f["rest_class"], f["rest_class_sure"], f["segments"]) == (3, 1, True, 1)
    assert f["alt"] == {"2": "16:30 HST", "3": "15:30 HST"}
    c = t["cum"]
    assert (c["ft_672"]["used"], c["ft_672"]["room"], c["ft_672"]["txt"]) == ("86:00", "14:00", "100 h in 672 h: 14:00 spare")
    assert (c["fdp_168"]["used"], c["fdp_168"]["room"]) == ("36:45", "23:15")
    assert t["rest"] == {"free": "24:35", "ok": True, "week": "75:00", "week_ok": True}
    lines = "\n".join(t["lines"])
    for w in ("Report 08:00 EST (03:00 HST Fri Feb 19): 1:15 before scheduled departure out of domicile (PWA 2.19.b.1)",
              "not acclimated: BOS is 87 deg from HNL, 24:35 free from duty (36 h needed), 24:50 in that theater (72 h "
              "needed)", "FAR 117.13(b), 117.17(b), FOM 4.3.2.4", "3 pilots (the trip's crew list): augmented, Table C",
              "A330 LDMCR bunks 1 and 4 (FOM 5.1.23.8), all LDMCR available", "Class 1 ends 17:30 HST; Class 2 16:30 HST "
              "(last out 10:00 EST), Class 3 15:30 HST (last out 09:00 EST) (Class 1 assumes the bunks are usable",
              "Table C row 0000-0559 (HNL time 03:00), Class 1, 3 pilots: 15:00, less 0:30 = FDP 14:30, ends 17:30 HST",
              "the FDP end less the scheduled 11:30 from this leg's out (09:15 EST) to the duty's last block-in (15:45 "
              "HST): 11:00 EST (06:00 HST Fri Feb 19) without an extension, 13:00 EST (08:00 HST Fri Feb 19) with it",
              "Flight time 11:30 of 13:00 (FAR 117.11, FOM 4.3.2.2): 1:30 spare, a duration",
              "Out on time (09:15 EST, 04:15 HST) the block-in is due by 17:15 HST; it moves with the actual out",
              "FAR 117.19(a), FOM 4.3.2.5", "FAR 117.19(b)", "86:00 at the scheduled block-in 15:45 HST, 14:00 spare",
              "FAR 117.23(c)(1)", "24:35 free from duty since the last release, 10 h needed: met",
              "longest free period 75:00: met", "Duty ends 15 min after block-in (PWA 2.19.b.2): release 17:45 HST at the "
              "FDP end without an extension, 19:45 HST with one"):
        assert w in lines, w
    assert TO.PWA10 in t["not_checked"]
    for w in ("FAR 117.19(a)(2)", "In-flight rest of an augmented FDP (FOM 4.3.2.4.2)", "8 h sleep opportunity",
              "1000 h flight time in 365 days"):
        assert any(w in s for s in t["not_checked"]), w
    blob = json.dumps(t)
    assert chr(0x2014) not in blob and not any(w in blob for w in ("Doe", "Roe", "Poe", "10001", "10002", "10003"))
    assert len(json.dumps(r)) < 9000  # the sensor stays far under HA's 16 KB attribute limit


def test_acceptance_with_every_trip_read_gives_the_same_times():
    """Legs read for every trip (not just duty periods) give the same numbers."""
    a, b = acceptance()["attributes"]["timeout"], acceptance(legs_read=True)["attributes"]["timeout"]
    for k in ("last_out", "last_out_ext", "no_ext", "ext", "fdp", "ft", "cum", "rest"):
        assert a[k] == b[k], k


def test_cumulative_needs_the_whole_window_on_file():
    """No schedule months: the cumulative limits and the 30 h in 168 h are listed as not checked, and the last out stands
    without them. A window that reaches before the first month on file is not checked either."""
    t = acceptance(months=None)["attributes"]["timeout"]
    assert t["cum"] == {} and t["last_out"]["txt"] == "11:00 EST" and t["no_ext"]["txt"] == "17:15 HST"
    assert sum("not all on file, not checked" in s for s in t["not_checked"]) == 3
    assert any(s.startswith("30 h free from duty in the 168 h before this FDP (FAR 117.25(b)") for s in t["not_checked"])
    t = acceptance(months=months_for("2027-02"))["attributes"]["timeout"]
    assert set(t["cum"]) == {"fdp_168"}  # 168 h back from Feb 19 is in February; 672 h is not
    assert any(s.startswith("100 h flight time in 672 h (FAR 117.23(b)(1)): your line before") for s in t["not_checked"])


def test_the_package_crew_line_counts_when_there_is_no_roster_and_a_mismatch_is_said():
    key, rep, legs = BOS_TRIP
    it, rec = trip(key, rep, legs, [])
    t = run([(key, (it, rec))], at(2027, 2, 19, "01:00"), {key: BOS_PKG})["attributes"]["timeout"]
    assert t["fdp"]["pilots"] == 3 and t["fdp"]["pilots_from"] == "package crew line CA01FO01RO01"
    it, rec = trip(key, rep, legs, CREW3)
    t = run([(key, (it, rec))], at(2027, 2, 19, "01:00"), {key: {"eq": "332", "crew": "CA01FO02RO01"}})["attributes"]["timeout"]
    assert t["fdp"]["pilots"] == 3
    assert any("crew list shows 3 pilot seats, the package crew line CA01FO02RO01 4" in s for s in t["lines"])
    # neither: no timeout attribute (never a guess)
    it, rec = trip(key, rep, legs, ["CA Doe, Jane (10001)"])
    a = run([(key, (it, rec))], at(2027, 2, 19, "01:00"), {})["attributes"]
    assert "timeout" not in a and a["report"] == "08:00 local, 03:00 HST"


def test_pilots_of_counts_pilot_seats_only():
    assert TO.pilots_of(["CA Doe, Jane (1)", "FO OPEN", "RO Roe, Rick (2)", "FA Poe, Pat (3)"]) == (3, "roster")
    assert TO.pilots_of([["CA", "Doe, Jane"], {"pos": "FO"}]) == (2, "roster")
    assert TO.pilots_of([], "CA02FO02") == (4, "package")
    assert TO.pilots_of(None, "") == (None, "")
    assert TO.roster_seats(["FO a", "FO b", "RO c"]) == (3, False) and TO.roster_seats(CREW2) == (2, True)


# ---------------------------------------------------------------- the crew list is not trusted blindly
SIN_LONG = [(0, "9071", "HNL", "SIN", "06:10", "13:15", "13:05")]  # 19:15 HST in: 13:05 of flight time


def test_a_crew_list_with_no_ca_misses_a_seat():
    key = "H3940|2027-03-02"
    crew = ["FO Doe, Jane (10001)", "FO Roe, Rick (10002)", "RO Poe, Pat (10003)"]
    t = run([(key, trip(key, "05:10", SIN_LONG, crew))], at(2027, 3, 2, "04:00"), {key: {"eq": "332"}})["attributes"]["timeout"]
    f = t["fdp"]
    assert (f["pilots"], f["pilots_sure"]) == (4, False) and "pilots" in t["unsure"] and t["sure"] is False
    assert f["pilots_from"] == "the crew list's 3 pilot seats and its missing CA"
    assert t["legal"] is True and t["ft"]["txt"] == "13:05 of 17:00 (3:55 spare)"
    # the package line says 4 too: sure (the rest class still is not: 4 pilots on the A330 use Class 2)
    t = run([(key, trip(key, "05:10", SIN_LONG, crew))], at(2027, 3, 2, "04:00"),
            {key: {"eq": "332", "crew": "CA01FO02RO01"}})["attributes"]["timeout"]
    assert t["fdp"]["pilots"] == 4 and t["fdp"]["pilots_sure"] is True and t["unsure"] == ["rest class"]


def test_a_count_whose_flight_time_is_over_its_limit_is_raised_unless_the_package_confirms_it():
    key = "H3941|2027-03-02"
    # a crew list of 3 with a CA, nothing to confirm it: 13:05 needs 4 (FAR 117.11): the 4-pilot limits, '?'
    t = run([(key, trip(key, "05:10", SIN_LONG, CREW3))], at(2027, 3, 2, "04:00"), {key: {"eq": "332"}})["attributes"]["timeout"]
    assert t["fdp"]["pilots"] == 4 and t["legal"] is True and "pilots" in t["unsure"] and "pilots" in t["flags"]
    assert any(s.startswith("Flag: 3 pilots (the trip's crew list) may not fly 13:05 of planned flight time") for s in t["lines"])
    # the package line says 3 as well: the count is firm and the duty is not legal to dispatch at any time
    t = run([(key, trip(key, "05:10", SIN_LONG, CREW3))], at(2027, 3, 2, "04:00"),
            {key: {"eq": "332", "crew": "CA01FO01RO01"}})["attributes"]["timeout"]
    assert t["legal"] is False and t["last_out"] is None and t["last_out_ext"] is None
    assert t["not_legal_short"] == "FT 13:05 of 13:00" and "not legal to dispatch at any time" in t["not_legal"]
    assert t["no_ext"]["legal"] is False and any(s.startswith("Not legal: 13:05 of planned flight time") for s in t["lines"])


# ---------------------------------------------------------------- acclimated at home, Table C by HNL time
SYD_OUT = [(0, "9011", "HNL", "SYD", "11:20", "19:05", "10:45")]  # 22:05 HST in (AEDT, 21 h ahead)


def test_acclimated_hnl_report_table_c_by_hnl_time_with_no_reduction():
    key = "H3910|2027-02-08"
    t = run([(key, trip(key, "10:20", SYD_OUT, CREW3))], at(2027, 2, 8, "09:00"), {key: {"eq": "332"}})["attributes"]["timeout"]
    f = t["fdp"]
    assert f["acclimated"] is True and f["row"] == "0700-1259 (HNL time 10:20)" and f["limit"] == "17:00"
    assert f["end_txt"] == "03:20 HST" and f["ext_end_txt"] == "05:20 HST" and f["alt"] == {"2": "02:50 HST", "3": "01:20 HST"}
    # last out 03:20 less 10:45 = 16:35 HST (same day); out on time, 13:00 flight time: block-in by 00:20 HST the next day
    assert (t["last_out"]["txt"], t["last_out"]["day"]) == ("16:35 HST", "Mon Feb 8")
    assert t["last_out"]["txt"] == t["last_out"]["hst"]  # out of HNL: one clock
    assert t["no_ext"]["txt"] == "00:20 HST" and t["no_ext"]["day"] == "Tue Feb 9" and t["report_day"] == "Mon Feb 8"
    assert t["no_ext"]["local"] == "21:20 AEDT"  # SYD keeps daylight time in February
    assert "less 0:30" not in " ".join(t["lines"]) and "FLICA check-in 10:20 HST" in t["lines"][0]


# ---------------------------------------------------------------- SIN: acclimated there, then home unacclimated
# HNL-SIN in 19:15 HST Mar 2 (13:15 SGT Mar 3); SIN-HNL out 13:30 SGT Mar 5 (19:30 HST Mar 4), block 13:40, in 09:10 HST
SIN = ("H3920|2027-03-02", "05:10", [(0, "9021", "HNL", "SIN", "06:10", "13:15", "13:05"),
                                     (3, "9022", "SIN", "HNL", "13:30", "09:10", "13:40")])


def _sin_line(sin_end=None, sin_read=True):
    key, rep, legs = SIN
    out = [(key, trip(key, rep, legs, CREW4, end=sin_end))]
    if not sin_read:
        out[0][1][1].clear()  # an empty page record: neither legs nor duty periods
    k2 = "H3921|2027-03-06"  # HNL-LAX the next morning: 24:20 free since the SIN release (09:10 + 0:30 customs)
    out.append((k2, trip(k2, "10:00", [(0, "9023", "HNL", "LAX", "11:00", "18:00", "5:00")], CREW2)))
    return out, {key: {"eq": "332", "crew": "CA01FO02RO01"}, k2: {"eq": "332", "crew": "CA01FO01"}}


def test_sin_layover_of_46_h_free_acclimates_there():
    trips, pkg = _sin_line()
    t = run(trips, at(2027, 3, 4, "17:00"), pkg)["attributes"]["timeout"]
    f = t["fdp"]
    # SIN arrival 19:15 HST Mar 2, release 19:45 (clearing customs at SIN, PWA 2.19.b.2); report 1:15 before 13:30 SGT
    # = 12:15 SGT Mar 5 (18:15 HST Mar 4): 46:30 free: acclimated to SIN
    assert f["acclimated"] is True and f["row"] == "0700-1259 (SIN time 12:15)"
    assert f["pilots"] == 4 and f["rest_class"] == 2 and f["limit"] == "18:00"  # 4 pilots on the A330: Class 2, '?'
    assert f["rest_class_sure"] is False and t["unsure"] == ["rest class"] and f["alt"] == {"1": "13:15 HST", "3": "09:45 HST"}
    assert any("acclimated to the SIN theater (46:30 free from duty" in s for s in t["lines"])
    assert any("requires pilot crew rest seat 3C or 3G" in s for s in t["lines"])
    # last out: FDP end 12:15 HST Mar 5 less 13:40 = 22:35 HST Mar 4 = 16:35 SGT Mar 5 (SGT prints as UTC+08)
    assert (t["last_out"]["txt"], t["last_out"]["hst"]) == ("16:35 UTC+08", "22:35 HST")
    rel = datetime.fromisoformat(t["no_ext"]["at"]) + timedelta(minutes=30)  # into HNL from SIN: customs
    assert t["no_ext"]["release_txt"] == f"{rel.astimezone(HST):%H:%M} HST"
    assert any("Duty ends 30 min after block-in, clearing customs (PWA 2.19.b.2)" in s for s in t["lines"])


def test_home_report_within_36_h_after_sin_is_unacclimated_on_the_sin_clock():
    trips, pkg = _sin_line()
    t = run(trips, at(2027, 3, 6, "09:00"), pkg)["attributes"]["timeout"]
    f = t["fdp"]
    # HNL is 98 deg from SIN: not acclimated; 10:00 HST is 04:00 SGT Mar 7: Table B 0400-0459, 1 segment, 10:00 - 0:30
    assert f["acclimated"] is False and f["table"] == "B" and f["row"] == "0400-0459 (SIN time 04:00)"
    assert f["limit"] == "9:30" and f["end_txt"] == "19:30 HST"
    # Table A on SIN time 04:00 (0000-0459): 8:00, a duration; out on time from 11:00 HST the block-in is due by 19:00
    assert t["ft"]["txt"] == "5:00 of 8:00 (3:00 spare)" and t["ft"]["end_txt"] == "19:00 HST"
    assert (t["last_out"]["txt"], t["last_out_ext"]["txt"]) == ("14:30 HST", "16:30 HST")
    assert t["no_ext"]["txt"] == "19:00 HST" and t["no_ext"]["short"] == "8:00 flight time"
    assert t["ext"]["txt"] == "19:00 HST" and "FDP with 2:00 extension 21:30 HST" in t["ext"]["by"]
    assert any("HNL is 98 deg from SIN, 24:20 free from duty (36 h needed), 24:50 in that theater" in s for s in t["lines"])


def test_a_trip_not_read_before_the_duty_makes_acclimation_unknown_and_the_lowest_value_is_used():
    """review (unread-trip-acclimation): the SIN trip's page record is empty (no legs, no duty periods). The walk must
    not measure free time across it: acclimation is not known, and the lowest Table B value on any clock less 0:30
    (8:30) is used, lower than the 9:30 the read trip gives."""
    trips, pkg = _sin_line(sin_end="2027-03-05", sin_read=False)
    r = run(trips, at(2027, 3, 6, "09:00"), pkg, months_for("2027-02", "2027-03"))
    t = r["attributes"]["timeout"]
    assert r["state"] == "HA9023 HNL-LAX" and t["fdp"]["acclimated"] is None and "acclimation" in t["unsure"]
    assert t["fdp"]["row"] == "lowest row (any clock)" and t["fdp"]["limit"] == "8:30" and t["ft"]["limit"] == "8:00"
    assert t["last_out"]["txt"] == "13:30 HST" and t["last_out"]["sure"] is False
    assert any("? acclimation not known: a span of your line before this report is not on file" in s for s in t["lines"])
    # the rest before it is at least the 10:00 since the end of the unread trip's last day: met
    assert t["rest"] == {"free": "10:00", "ok": True}
    # read, the same line gives 9:30 on the SIN clock
    trips, pkg = _sin_line(sin_end="2027-03-05")
    t = run(trips, at(2027, 3, 6, "09:00"), pkg, months_for("2027-02", "2027-03"))["attributes"]["timeout"]
    assert t["fdp"]["limit"] == "9:30" and t["fdp"]["acclimated"] is False


def test_days_no_schedule_month_covers_break_the_walk_too():
    """A trip that starts on the first day on file: the time before it is not known, so its acclimation is not either;
    one with two days on file and no duty before it is acclimated (at least 48 h free)."""
    key = "H3912|2027-03-01"
    legs = [(0, "9012", "HNL", "LAX", "08:00", "15:00", "5:00")]
    t = run([(key, trip(key, "07:00", legs, CREW2))], at(2027, 3, 1, "06:00"), {key: {"eq": "332"}},
            months_for("2027-03"))["attributes"]["timeout"]
    assert t["fdp"]["acclimated"] is None and t["fdp"]["limit"] == "8:30"
    key = "H3913|2027-03-04"
    t = run([(key, trip(key, "07:00", legs, CREW2))], at(2027, 3, 4, "06:00"), {key: {"eq": "332"}},
            months_for("2027-03"))["attributes"]["timeout"]
    assert t["fdp"]["acclimated"] is True and t["fdp"]["limit"] == "14:00"


# ---------------------------------------------------------------- 2 pilots: Table B, 3 segments, Table A
TURNS = [(0, "9031", "HNL", "OGG", "06:20", "07:05", "0:45"), (0, "9032", "OGG", "HNL", "08:05", "08:50", "0:45"),
         (0, "9033", "HNL", "LAX", "10:05", "17:35", "5:30")]


def test_two_pilots_three_segments_table_b_and_table_a():
    key = "H3930|2027-03-12"
    t = run([(key, trip(key, "05:20", TURNS, CREW2))], at(2027, 3, 12, "05:00"), {key: {"eq": "332"}})["attributes"]["timeout"]
    f = t["fdp"]
    assert f["table"] == "B" and f["segments"] == 3 and f["row"] == "0500-0559 (HNL time 05:20)"
    assert f["limit"] == "12:00" and f["end_txt"] == "17:20 HST" and f["rest_class"] is None and f["alt"] == {}
    # the last out of the working leg (leg 1): 17:20 less 9:15 scheduled to the last block-in (15:35) = 08:05 HST
    assert (t["last_out"]["txt"], t["last_out_ext"]["txt"], t["last_out"]["leg"]) == ("08:05 HST", "10:05 HST", "HNL-OGG")
    # Table A 0500-1959: 9:00; 7:00 planned; out on time 1:30 flown before the last leg's 10:05 out: block-in by 17:35
    assert t["ft"]["txt"] == "7:00 of 9:00 (2:00 spare)" and t["ft"]["end_txt"] == "17:35 HST"
    assert t["no_ext"]["txt"] == "17:20 HST" and t["no_ext"]["by"] == "FDP 12:00 (FAR 117.13, Table B)"
    assert t["ext"]["txt"] == "17:35 HST" and t["ext"]["by"] == "9:00 flight time; FDP with 2:00 extension 19:20 HST"
    assert any("This FDP: 3 segments, 7:00 of planned flight time." in s for s in t["lines"])
    assert t["no_ext"]["local"] == "19:20 PST"  # the arrival station's own clock
    # in OGG between the legs: the last out is the next leg's (OGG-HNL), the block-in limits are the duty's
    t2 = run([(key, trip(key, "05:20", TURNS, CREW2))], at(2027, 3, 12, "07:30"), {key: {"eq": "332"}})["attributes"]
    assert t2["leg"] == "1 of 3" and t2["timeout"]["no_ext"] == t["no_ext"]
    # 17:20 less 7:30 from OGG-HNL's 08:05 out to the last block-in
    assert (t2["timeout"]["last_out"]["txt"], t2["timeout"]["last_out"]["leg"]) == ("09:50 HST", "OGG-HNL")


def test_a_deadhead_after_the_last_flown_leg_is_not_fdp():
    duties = [{"report": at(2027, 3, 12, "06:00"), "legs": [
        {"dep": at(2027, 3, 12, "07:00"), "arr": at(2027, 3, 12, "12:00"), "blk": 300, "frm": "HNL", "to": "LAX", "flt": "1"},
        {"dep": at(2027, 3, 12, "13:00"), "arr": at(2027, 3, 12, "14:30"), "blk": 90, "frm": "LAX", "to": "SFO", "flt": "2", "dh": True}]}]
    t = TO.duty_timeout(duties, 0, 2, "roster", "332")
    assert t["fdp"]["segments"] == 1 and t["sched_in_txt"] == "12:00 HST"
    assert t["ft"]["end_txt"] == "16:00 HST"  # 9:00 from 07:00 out; the deadhead is no flight time
    assert TO.duty_timeout([{"report": duties[0]["report"], "legs": duties[0]["legs"][1:]}], 0, 2, "roster", "332") is None


# ---------------------------------------------------------------- deadheads from the pairings package
DH_TRIP = ("H3990|2027-03-10", "07:00", [(0, "9091", "HNL", "LAX", "08:00", "15:00", "5:00"),
                                         (2, "9092", "SFO", "HNL", "09:00", "12:30", "5:30")])
DH_PKG = {"eq": "332", "crew": "CA01FO01RO01", "duties": [
    {"legs": [["1", "", "9091", "HNL", "LAX", "08:00", "15:00", "5h00", "5:00", "", "332"]], "rept": "07:00"},
    {"legs": [["3", "DH", "1127*", "LAX", "SFO", "06:00", "07:30", "1h30", "0:45", "1:00", "321"],
              ["3", "", "9092", "SFO", "HNL", "09:00", "12:30", "5h30", "5:30", "", "332"]], "rept": "05:00"}]}


def test_a_duty_that_starts_with_a_deadhead_reports_before_it():
    """FLICA's pairing page legs on file carry no deadhead: the pairings package's LAX-SFO deadhead (06:00 PST) starts
    the second duty, so its report is 1:15 before it (04:45 PST, 02:45 HST; earlier than the package's REPT 05:00 and
    than 1:15 before the flown leg, 05:45 HST), and it counts as a segment."""
    key, rep, legs = DH_TRIP
    t = run([(key, trip(key, rep, legs, CREW3))], at(2027, 3, 12, "04:00"), {key: DH_PKG})["attributes"]["timeout"]
    assert t["report_txt"] == "02:45 HST" and t["fdp"]["segments"] == 2
    assert t["fdp"]["row"] == "0000-0559 (HNL time 02:45)" and t["fdp"]["end_txt"] == "17:45 HST"
    # last out of 9092: 17:45 less 5:30 = 12:15 HST = 14:15 PST; flight time only the flown 5:30
    assert (t["last_out"]["txt"], t["last_out"]["hst"]) == ("14:15 PST", "12:15 HST")
    assert t["ft"]["planned"] == "5:30"
    assert any("Deadheads: from the pairings package: LAX-SFO (FLICA's page lists none)." in s for s in t["lines"])
    assert any("This FDP: 2 segments (1 deadhead, counted: conservative)" in s for s in t["lines"])
    # without the package's detail: 1:15 before the flown leg, and the basis says a deadhead would not be counted
    t = run([(key, trip(key, rep, legs, CREW3))], at(2027, 3, 12, "04:00"), {key: {"eq": "332"}})["attributes"]["timeout"]
    assert t["report_txt"] == "05:45 HST" and t["fdp"]["segments"] == 1
    assert any("the pairings package has no detail for this pairing, so one there would not be counted" in s
               for s in t["lines"])


def test_a_trailing_deadhead_sets_the_release_and_never_the_fdp_end():
    key = "H3991|2027-03-10"
    legs = [(0, "9093", "HNL", "LAX", "08:00", "15:00", "5:00")]
    pk = {"eq": "332", "crew": "CA01FO01", "duties": [{"legs": [
        ["1", "", "9093", "HNL", "LAX", "08:00", "15:00", "5h00", "5:00", "", "332"],
        ["1", "DH", "1200", "LAX", "SFO", "16:00", "17:30", "1h30", "0:45", "1:00", "321"]], "rept": "07:00"}]}
    t = run([(key, trip(key, "07:00", legs, CREW2))], at(2027, 3, 10, "06:00"), {key: pk})["attributes"]["timeout"]
    assert t["sched_in_txt"] == "13:00 HST" and t["fdp"]["segments"] == 1 and t["fdp"]["limit"] == "14:00"
    it, rec = trip(key, "07:00", legs, CREW2)
    pairs = WK._pairings([it])
    pairs[0].update(rec=rec, legs=WK._legs(pairs[0], rec))
    ds = WK._duties(pairs, {key: pk})
    assert [x["dh"] for x in ds[0]["legs"]] == [False, True] and ds[0]["legs"][1]["arr"] == at(2027, 3, 10, "15:30")


# ---------------------------------------------------------------- rest classes, unknown equipment
def test_rest_class_is_class_2_wherever_the_fom_requires_a_cabin_rest_seat():
    assert TO.rest_class("332", 3)[:2] == (1, True)
    assert TO.rest_class("332", 4)[:2] == (2, False) and "3C or 3G" in TO.rest_class("332", 4)[2]
    assert TO.rest_class("789", 3)[:2] == (2, False) and "seat 9A " in TO.rest_class("789", 3)[2]
    assert TO.rest_class("789", 4)[:2] == (2, False) and "9A and 9J" in TO.rest_class("789", 4)[2]
    assert TO.rest_class("", 3)[:2] == (3, False)


def test_four_pilots_on_the_a330_use_class_2():
    key = "H3942|2027-03-02"
    t = run([(key, trip(key, "05:10", SIN_LONG, CREW4))], at(2027, 3, 2, "04:00"), {key: {"eq": "332"}})["attributes"]["timeout"]
    f = t["fdp"]
    assert (f["pilots"], f["rest_class"], f["row"], f["limit"]) == (4, 2, "0000-0559 (HNL time 05:10)", "15:30")
    assert f["end_txt"] == "20:40 HST" and f["alt"] == {"1": "22:10 HST", "3": "18:40 HST"}
    assert (t["last_out"]["txt"], t["last_out_ext"]["txt"]) == ("07:35 HST", "09:35 HST")  # 20:40 / 22:40 less 13:05
    assert t["ft"]["limit"] == "17:00" and t["last_out"]["sure"] is False


def test_unknown_equipment_uses_class_3_and_says_so():
    key = "H3943|2027-02-08"
    t = run([(key, trip(key, "10:20", SYD_OUT, CREW3))], at(2027, 2, 8, "09:00"), None)["attributes"]["timeout"]
    f = t["fdp"]
    assert f["rest_class"] == 3 and f["rest_class_sure"] is False and f["limit"] == "15:00" and t["sure"] is False
    assert f["alt"] == {"1": "03:20 HST", "2": "02:50 HST"}
    line = next(s for s in t["lines"] if s.startswith("Rest facility"))
    assert "equipment not on file" in line and "Class 3 used" in line and "(?)" in line and "assumes the bunks" not in line
    assert any("Class 3 ?, 3 pilots" in s for s in t["lines"])
    t787 = run([(key, trip(key, "10:20", SYD_OUT, CREW3))], at(2027, 2, 8, "09:00"), {key: {"eq": "789"}})["attributes"]["timeout"]
    assert t787["fdp"]["rest_class"] == 2 and any("787 OFCR (FOM 5.1.23.7)" in s for s in t787["lines"])


# ---------------------------------------------------------------- the cumulative limits
def _turns(days, start="2027-03-0", report="06:00"):
    out = []
    for k, d in enumerate(days):  # turns of 12:45 FDP (06:00 to 18:45 HST), 10:15 of flight time
        key = f"H395{k}|{start}{d}"
        out.append((key, trip(key, report, [(0, f"905{k}", "HNL", "SFO", "07:00", "14:00", "5:00"),
                                            (0, f"906{k}", "SFO", "HNL", "15:30", "18:45", "5:15")], CREW2)))
    return out


def test_sixty_hours_fdp_in_168_caps_the_last_out_and_the_extension():
    trips = _turns((2, 3, 4, 5))
    key = "H3960|2027-03-06"
    trips.append((key, trip(key, "07:00", [(0, "9070", "HNL", "LAX", "08:00", "15:00", "5:00")], CREW2)))
    t = run(trips, at(2027, 3, 6, "06:30"), {}, months_for("2027-02", "2027-03"))["attributes"]["timeout"]
    c = t["cum"]["fdp_168"]
    assert (c["used"], c["room"], c["cap_txt"]) == ("57:00", "3:00", "16:00 HST")
    assert t["fdp"]["end_txt"] == "21:00 HST" and t["fdp"]["in_txt"] == "16:00 HST" and t["fdp"]["ext_in_txt"] == "16:00 HST"
    # the cap binds both: last out 16:00 less 5:00 = 11:00 HST, the same with an extension
    lo, lx = t["last_out"], t["last_out_ext"]
    assert (lo["txt"], lx["txt"], lo["at"] == lx["at"]) == ("11:00 HST", "11:00 HST", True)
    assert lo["short"] == lx["short"] == "60 h FDP in 168 h"
    assert t["no_ext"]["txt"] == "16:00 HST" and t["no_ext"]["by"] == "60 h FDP in 168 h (FAR 117.23(c)(1))"
    assert any("cap an extension before takeoff" in s for s in t["lines"])


def test_a_cumulative_limit_over_at_the_scheduled_times_is_not_legal():
    """100 h in 672 h: 9 turns of 10:15 (92:15) and this duty's 9:00 = 101:15 at the scheduled block-in: not legal to
    dispatch (FOM 4.3.2.3), shown instead of a time."""
    trips = _turns((1, 3, 5, 7, 9), "2027-02-0", "06:00") + [
        (f"H397{k}|2027-02-1{d}", trip(f"H397{k}|2027-02-1{d}", "06:00", [
            (0, f"908{k}", "HNL", "SFO", "07:00", "14:00", "5:00"), (0, f"909{k}", "SFO", "HNL", "15:30", "18:45", "5:15")],
            CREW2)) for k, d in enumerate((1, 3, 5, 7))]
    key = "H3979|2027-02-19"  # February: no daylight time in the window, so every printed time matches its block
    trips.append((key, trip(key, "07:00", [(0, "9099", "HNL", "SFO", "08:00", "19:00", "9:00")], CREW3)))
    t = run(trips, at(2027, 2, 19, "06:00"), {key: {"eq": "332", "crew": "CA01FO01RO01"}},
            months_for("2027-01", "2027-02"))["attributes"]["timeout"]
    assert t["cum"]["ft_672"]["used"] == "101:15" and t["cum"]["ft_672"]["txt"] == "100 h in 672 h: 1:15 over"
    assert t["legal"] is False and t["last_out"] is None and t["not_legal_short"] == "100 h in 672 h: 1:15 over"
    assert "older flying leaves the 672 h window" in t["not_legal"]


# ---------------------------------------------------------------- rest before the FDP (FAR 117.25)
def test_short_rest_before_the_fdp_is_flagged():
    a = "H3981|2027-02-20"
    b = "H3982|2027-02-21"
    trips = [(a, trip(a, "13:00", [(0, "9081", "HNL", "LAX", "14:00", "21:00", "5:00")], CREW2, end="2027-02-20")),
             (b, trip(b, "02:00", [(0, "9083", "HNL", "SFO", "03:00", "10:00", "5:00")], CREW2))]
    # the first (a synthetic one-way) blocks in 19:00 HST, released 19:15; the next reports 02:00: 6:45 free
    t = run(trips, at(2027, 2, 21, "01:00"), {}, months_for("2027-01", "2027-02"))["attributes"]["timeout"]
    assert t["rest"]["free"] == "6:45" and t["rest"]["ok"] is False and "rest" in t["flags"]
    assert any("6:45 free from duty since the last release, 10 h needed: SHORT" in s for s in t["lines"])
    assert t["rest"]["week_ok"] is True


# ---------------------------------------------------------------- duties across midnight, the day before
def test_a_red_eye_across_midnight():
    key = "H3970|2027-02-02"
    t = run([(key, trip(key, "22:30", [(0, "9071", "HNL", "LAS", "23:30", "07:25", "5:55")], CREW2))],
            at(2027, 2, 2, "20:00"), {key: {"eq": "332"}})["attributes"]["timeout"]
    f = t["fdp"]
    assert f["row"] == "2200-2259 (HNL time 22:30)" and f["limit"] == "11:00" and f["end_txt"] == "09:30 HST"
    assert t["ft"]["limit"] == "8:00" and t["ft"]["end_txt"] == "07:30 HST"  # Table A 2000-2359
    assert (t["no_ext"]["txt"], t["no_ext"]["day"], t["report_day"]) == ("07:30 HST", "Wed Feb 3", "Tue Feb 2")
    assert t["no_ext"]["local"] == "09:30 PST" and t["sched_in_txt"] == "05:25 HST"
    assert (t["last_out"]["txt"], t["last_out"]["wd"]) == ("03:35 HST", "Wed")  # 09:30 less 5:55, the next day


def test_a_report_later_than_the_first_departure_is_the_day_before():
    key = "H3971|2027-02-04"  # FLICA's trip day is the departure's (00:20); its check-in 23:20 is the night before
    t = run([(key, trip(key, "23:20", [(0, "9072", "HNL", "LAX", "00:20", "07:20", "5:00")], CREW2))],
            at(2027, 2, 3, "22:00"), {key: {"eq": "332"}})["attributes"]["timeout"]
    assert t["report_txt"] == "23:20 HST" and t["report_day"] == "Wed Feb 3"
    assert t["fdp"]["row"] == "2300-2359 (HNL time 23:20)" and t["fdp"]["limit"] == "10:00"


# ---------------------------------------------------------------- daylight time: LAX in July, the other clock
def test_lax_in_july_reads_pdt_and_takes_the_lower_clock_marked_unsure():
    key = "H3980|2027-07-10"
    legs = [(0, "9081", "HNL", "LAX", "08:10", "16:10", "5:00"), (2, "9082", "LAX", "HNL", "09:10", "11:40", "5:30")]
    t = run([(key, trip(key, "07:10", legs, CREW2))], at(2027, 7, 12, "05:00"), {key: {"eq": "332"}})["attributes"]["timeout"]
    # 09:10 PDT is 06:10 HST: report 1:15 before, 04:55 HST = 07:55 PDT. Acclimated to the HNL theater (LAX within 60
    # deg); HNL time gives Table B 0400-0459 (10:00), LAX time 0700-1159 (14:00): the lower is used and marked '?'
    assert t["report_txt"] == "04:55 HST" and t["fdp"]["acclimated"] is True
    assert t["fdp"]["row"] == "0400-0459 (HNL time 04:55)" and t["fdp"]["limit"] == "10:00"
    assert t["sure"] is False and t["unsure"] == ["clock"] and t["last_out"]["sure"] is False
    # last out 14:55 HST less 5:30 = 09:25 HST = 12:25 PDT; on the LAX clock 18:55 less 5:30 = 13:25 HST = 16:25 PDT
    assert t["last_out"]["txt"] == "12:25 PDT"
    assert t["fdp"]["other"] == {"clock": "LAX time 07:55", "row": "0700-1159", "limit": "14:00",
                                 "last_out_txt": "16:25 PDT", "last_out_ext_txt": "18:25 PDT"}
    assert any(s.startswith("Other reading: LAX time 07:55 gives row 0700-1159, FDP 14:00 and 9:00 flight time, last out "
                            "16:25 PDT (18:25 PDT with the extension). FOM 4.3.2.4") for s in t["lines"])
    assert t["lines"][0].startswith("Report 07:55 PDT (04:55 HST")
    assert t["ft"]["limit"] == "8:00" and t["ft"]["from"] == "scheduled out 09:10 PDT"  # Table A on HNL time 04:55


# ---------------------------------------------------------------- the theater table, customs, a station with no clock
def test_every_station_has_a_longitude_and_the_theater_checks_hold():
    assert set(TO.LON) == set(WK.ZONES)
    near = ("SYD", "MEL", "BNE", "AKL", "PPT", "LAX", "SFO", "SEA", "SAN", "PDX", "LAS", "PHX", "ANC", "OGG")
    far = ("JFK", "BOS", "ORD", "DFW", "AUS", "NRT", "HND", "KIX", "ICN", "SIN", "MNL")
    assert all(TO.same_theater("HNL", s) for s in near), [s for s in near if not TO.same_theater("HNL", s)]
    assert not any(TO.same_theater("HNL", s) for s in far), [s for s in far if TO.same_theater("HNL", s)]
    assert round(TO.ang(TO.LON["SYD"], TO.LON["HNL"])) == 51 and round(TO.ang(TO.LON["AUS"], TO.LON["HNL"]), 1) == 60.2
    assert round(TO.ang(TO.LON["NRT"], TO.LON["HNL"]), 1) == 61.7
    assert TO.same_theater("HNL", "XYZ") is None


def test_customs_is_any_border_or_a_country_not_known():
    leg = lambda a, b: {"frm": a, "to": b}  # noqa: E731
    assert not TO.customs(leg("LAX", "HNL")) and not TO.customs(leg("NRT", "KIX"))
    assert TO.customs(leg("HNL", "NRT")) and TO.customs(leg("NRT", "HNL")) and TO.customs(leg("NRT", "ICN"))
    assert TO.customs(leg("HNL", "PPG")) and TO.customs(leg("BFI", "HNL"))  # American Samoa; a station not on file
    assert not TO.customs(leg("BFI", "HNL"), {"BFI"})  # the pilot's smart.json "domestic"
    assert set(TO.COUNTRY) | set(TO.US_STATIONS) <= set(WK.ZONES)


def test_the_domestic_list_reaches_the_release():
    key = "H3985|2027-03-10"
    legs = [(0, "9085", "HNL", "LNK", "08:00", "18:00", "6:00")]
    t = run([(key, trip(key, "07:00", legs, CREW2))], at(2027, 3, 10, "06:00"), {key: {"eq": "332"}})["attributes"]["timeout"]
    assert "clearing customs" in t["lines"][-1]  # LNK is not on the Watcher's US list: not known, conservative
    t = run([(key, trip(key, "07:00", legs, CREW2))], at(2027, 3, 10, "06:00"), {key: {"eq": "332"}},
            domestic={"LNK"})["attributes"]["timeout"]
    assert "clearing customs" not in t["lines"][-1]


def test_a_station_with_no_clock_is_never_read_as_its_own_time():
    duties = [{"report": at(2027, 3, 10, "06:00"), "legs": [
        {"dep": at(2027, 3, 10, "07:00"), "arr": at(2027, 3, 10, "12:00"), "blk": 300, "frm": "HNL", "to": "XYZ", "flt": "1"}]},
              {"report": at(2027, 3, 11, "06:00"), "legs": [
                  {"dep": at(2027, 3, 11, "07:00"), "arr": at(2027, 3, 11, "12:00"), "blk": 300, "frm": "XYZ", "to": "HNL",
                   "flt": "2"}]}]
    t = TO.duty_timeout(duties, 1, 2, "roster", "332")
    assert t["fdp"]["acclimated"] is None and "XYZ time" not in json.dumps(t)
    assert any("XYZ's own clock is not on file" in s for s in t["lines"])


def test_the_watcher_uses_the_one_us_station_list():
    src = open(os.path.join(HERE, "watcher.py"), encoding="utf-8").read()
    assert "US_STATIONS = TO.US_STATIONS" in src
    assert "timeout.py" in open(os.path.join(HERE, "Dockerfile"), encoding="utf-8").read()


def test_a_schedule_item_that_may_be_duty_makes_acclimation_unknown_and_the_lower_is_used():
    """36 h free at home after SIN would acclimate him to HNL, but a training day inside it may be duty: the lower of
    acclimated (HNL time) and not (SIN time, less 0:30) is used."""
    key, rep, legs = SIN
    trips = [(key, trip(key, rep, legs, CREW4))]
    k2 = "H3922|2027-03-07"  # 2 days after the SIN release (Mar 5 09:40 HST): 48:50 free, 49:20 at home (< 72 h)
    trips.append((k2, trip(k2, "10:30", [(0, "9024", "HNL", "LAX", "11:30", "18:30", "5:00")], CREW2)))
    pkg = {key: {"eq": "332"}, k2: {"eq": "332"}}
    clean = run(trips, at(2027, 3, 7, "09:00"), pkg)["attributes"]["timeout"]
    assert clean["fdp"]["acclimated"] is True and clean["fdp"]["row"] == "0700-1159 (HNL time 10:30)"
    busy = run(trips, at(2027, 3, 7, "09:00"), pkg,
               extra_items=[{"trip": "TRNG", "start": "2027-03-06", "end": "2027-03-06", "lay": ""}])["attributes"]["timeout"]
    assert busy["fdp"]["acclimated"] is None and busy["unsure"] == ["acclimation"]
    # SIN time 04:30 (Mar 8): Table B 0400-0459, 10:00 less 0:30 is lower than HNL 0700-1159's 14:00
    assert busy["fdp"]["row"] == "0400-0459 (SIN time 04:30)" and busy["fdp"]["limit"] == "9:30"
    assert any(s.startswith("Acclimation (FAR 117.3, FOM 4.3.2.4.6): ? acclimated to HNL only if") for s in busy["lines"])
    assert busy["rest"]["ok"] is None  # the training day sits inside the rest before it too
    vac = run(trips, at(2027, 3, 7, "09:00"), pkg,
              extra_items=[{"trip": "VAC", "start": "2027-03-06", "end": "2027-03-06", "lay": ""}])["attributes"]["timeout"]
    assert vac["fdp"] == clean["fdp"]


def test_a_timeout_input_that_cannot_be_read_never_stops_the_working_flight(monkeypatch):
    import recall
    monkeypatch.setattr(recall, "line_gaps", lambda *a, **k: 1 / 0)
    r = acceptance()
    assert r["state"] == "HA9062 BOS-HNL" and "timeout" not in r["attributes"]
    assert WK.TIMEOUT_ERR["msg"] == "ZeroDivisionError"
    acceptance(months=None)
    assert WK.TIMEOUT_ERR["msg"] == ""


def test_news_stays_the_same_from_minute_to_minute():
    """The sensor republishes only on news: the timeout does not move with the clock."""
    a, b = acceptance(now=at(2027, 2, 19, "01:00")), acceptance(now=at(2027, 2, 19, "01:01"))
    assert WK.news(a) == WK.news(b)
    later = acceptance(now=at(2027, 2, 19, "09:00"))  # in the air: the status moves, the timeout does not
    assert later["attributes"]["status"] == "Enroute per schedule"
    assert later["attributes"]["timeout"] == a["attributes"]["timeout"]
    assert "timeout" not in WK.working_flight([], {}, at(2027, 2, 19, "05:00"))["attributes"]


# ---------------------------------------------------------------- the Watcher passes the package detail (both instances)
from test_working import W  # noqa: E402,F401  (the Watcher fixture: Ryan's instance and a second pilot's)


def test_publish_working_flight_passes_the_package_detail_and_logs_an_error_once(W, monkeypatch):
    key, rep, legs = BOS_TRIP
    it, rec = trip(key, rep, legs, CREW3)
    W.S["schedule"] = {"2027-02": {"items": [it], "days": months_for("2027-02")["2027-02"]["days"]}}
    W.S["own_trips"] = {key: rec}
    calls, said = [], []
    monkeypatch.setattr(W, "pkg_detail_for", lambda period, pid, st=None: calls.append((period, pid, st)) or BOS_PKG)
    monkeypatch.setattr(W, "bid_period_fn", lambda: (lambda iso: "2027-02"))
    monkeypatch.setattr(W.SMART, "load", lambda *a, **k: {"domestic": ["LNK"]})
    assert W._domestic() == {"LNK"}
    assert W.publish_working_flight(now=at(2027, 2, 19, "01:00"), force=True)
    sent = [json.loads(p) for t, p, r in W.FAKE.msgs if t == f"{W.T}/working_flight" and r][-1]
    t = sent["attributes"]["timeout"]
    assert t["last_out"]["txt"] == "11:00 EST" and t["fdp"]["rest_class"] == 1
    assert calls and calls[-1] == ("2027-02", "H3958", "2027-02-17")
    # a package that cannot be read: still published, eq unknown (Class 3, '?')
    monkeypatch.setattr(W, "pkg_detail_for", lambda *a, **k: (_ for _ in ()).throw(OSError("gone")))
    assert W.publish_working_flight(now=at(2027, 2, 19, "01:01"), force=True)
    sent = [json.loads(p) for t, p, r in W.FAKE.msgs if t == f"{W.T}/working_flight" and r][-1]
    assert sent["attributes"]["timeout"]["fdp"]["rest_class"] == 3
    # an error inside the timeout: logged once (its type), the working flight still published
    import timeout
    monkeypatch.setattr(timeout, "_timeout", lambda *a, **k: 1 / 0)
    monkeypatch.setattr(W.log, "info", lambda msg, *a: said.append(msg % a))
    for m in ("01:02", "01:03"):
        assert W.publish_working_flight(now=at(2027, 2, 19, m), force=True)
    assert [s for s in said if "duty timeout" in s] == ["working flight: duty timeout not worked out (ZeroDivisionError)"]


# ---------------------------------------------------------------- the card, in a real Chromium
from test_layover_card import DARK, HA_DARK, HA_LIGHT, LIGHT, _page, _states, browser  # noqa: E402,F401

ORANGE = "rgb(194, 65, 12)"  # #c2410c


def _watcher_only(tmp_path, timeout=True, tweak=None):
    """The admin's states with no Hark sensor: the Watcher's working flight (report block in the header), with the
    acceptance case's timeout (tweak(t) changes a copy)."""
    st = _states(tmp_path, hark_attrs={}, notes=False)
    a = st["sensor.flight_watcher_working_flight"]["attributes"]
    a.update({"pairing": "H3958", "flight": "HA9062", "origin": "BOS", "dest": "HNL", "leg": "2 of 2", "date": "2027-02-19",
              "dep_sched": "09:15 local, 04:15 HST", "arr_sched": "15:45 local, 15:45 HST", "report": "08:00 local, 03:00 HST",
              "status": "Scheduled"})
    if timeout:
        t = copy.deepcopy(acceptance()["attributes"]["timeout"])
        if tweak:
            tweak(t)
        a["timeout"] = t
    return st


def test_card_box_shows_the_last_out_bold_right_of_the_report_and_opens_its_basis(browser, tmp_path):
    pg = browser.new_page(viewport={"width": 390, "height": 844})
    pg.set_content(_page(_watcher_only(tmp_path)))
    card = pg.locator("flight-watcher-layover-card")
    box, rep = card.locator("[data-to]"), card.locator("[data-van]")
    assert box.is_visible() and rep.locator(".vl").inner_text().lower() == "report"
    assert box.locator(".tol").inner_text().lower() == "last out"
    assert box.locator("[data-tono]").inner_text() == "11:00 EST"  # the big Report time's clock (08:00 local)
    assert box.locator("[data-toext]").inner_text() == "Ext 13:00 EST"
    assert box.locator("[data-tohst]").inner_text() == "(06:00 / 08:00 HST)"
    assert box.locator("[data-toby]").inner_text() == "FT 11:30 of 13:00"
    assert box.locator(".toq").count() == 0 and box.locator("[data-towarn]").count() == 0
    say = box.get_attribute("aria-label")
    assert say == ("Last out 11:00 EST, 06:00 HST without an extension, 13:00 EST, 08:00 HST with one; flight time 11:30 of "
                   "13:00 (1:30 spare). Details")
    style = pg.evaluate("""() => { const b = window.root().querySelector('[data-to]'), s = getComputedStyle(b);
        return {c: s.borderTopColor, w: s.borderTopWidth, st: s.borderTopStyle, tag: b.tagName,
                no: parseInt(getComputedStyle(b.querySelector('[data-tono]')).fontWeight, 10),
                ex: parseInt(getComputedStyle(b.querySelector('[data-toext]')).fontWeight, 10),
                size: parseFloat(getComputedStyle(b.querySelector('[data-tono]')).fontSize)}; }""")
    assert style["c"] == ORANGE and style["w"] == "2px" and style["st"] == "solid" and style["tag"] == "BUTTON"
    assert style["no"] >= 700 and style["ex"] >= 700 and style["size"] >= 20
    bb, rb = box.bounding_box(), rep.bounding_box()
    assert bb["x"] >= rb["x"] + rb["width"] - 1  # right of the report time
    assert bb["y"] < rb["y"] + rb["height"] and rb["y"] < bb["y"] + bb["height"]  # side by side
    assert bb["height"] >= 44
    assert pg.evaluate("document.documentElement.scrollWidth") <= 390
    fl = card.locator(".fl").bounding_box()
    assert bb["y"] >= fl["y"]  # under the title on a phone (or beside it), never over it
    # a tap opens the basis under the header; Enter closes it, Space opens it again
    det = card.locator("[data-todet]")
    assert not det.is_visible() and box.get_attribute("aria-expanded") == "false"
    box.click()
    assert det.is_visible() and card.locator("[data-to]").get_attribute("aria-expanded") == "true"
    txt = det.inner_text()
    for w in ("No extension: block out by 11:00 EST (06:00 HST Fri Feb 19), block in by 17:30 HST, release 17:45 HST",
              "Out on time (09:15 EST): block in by 17:15 HST Fri Feb 19, 13:00 flight time.",
              "With extension: block out by 13:00 EST (08:00 HST Fri Feb 19), block in by 19:30 HST, release 19:45 HST",
              "with the 2:00 extension (FAR 117.19(a)); before takeoff only", "13:00 flight time: an extension adds no flight time.",
              "Flight time: 11:30 of 13:00 (1:30 spare) · 100 h in 672 h: 14:00 spare", "How it is worked out",
              "Not checked (6)"):
        assert w in txt, w
    # how it is worked out and what is not checked fold under the summary (a phone sees the answer first)
    assert not card.locator("[data-tolines]").is_visible() and not card.locator("[data-tonc]").is_visible()
    assert card.locator("[data-tolines] li").count() == len(acceptance()["attributes"]["timeout"]["lines"])
    assert det.bounding_box()["height"] < 600
    card.locator("[data-k=tobasis] summary").click()
    assert "Table C row 0000-0559 (HNL time 03:00)" in card.locator("[data-tolines]").inner_text()
    card.locator("[data-k=tonc] summary").click()
    assert "PWA Section 10 (Hours of Service)" in card.locator("[data-tonc]").inner_text()
    assert det.bounding_box()["y"] >= card.locator(".hd").bounding_box()["y"] + card.locator(".hd").bounding_box()["height"] - 1
    card.locator("[data-to]").focus()
    pg.keyboard.press("Enter")
    assert not card.locator("[data-todet]").is_visible()
    pg.keyboard.press("Space")
    assert card.locator("[data-todet]").is_visible()
    assert card.locator("[data-tolines]").is_visible()  # the folds keep their state across a render
    assert pg.evaluate("document.documentElement.scrollWidth") <= 390
    pg.close()


def _unsure(t):
    t["sure"], t["unsure"] = False, ["clock"]
    t["last_out"]["sure"] = t["last_out_ext"]["sure"] = False


def _same(t):
    t["last_out_ext"].update({k: t["last_out"][k] for k in ("at", "txt", "hst", "day", "wd")}, short="60 h FDP in 168 h")


def _not_legal(t):
    t.update(legal=False, last_out=None, last_out_ext=None, not_legal_short="FT 13:05 of 13:00",
             not_legal="13:05 of planned flight time is over the 13:00 limit (FAR 117.11, FOM 4.3.2.2): not legal to "
                       "dispatch at any time")


def _early(t):
    t["last_out"]["early"] = True


def _old(t):
    for k in ("last_out", "last_out_ext", "legal", "sure", "ft"):
        t.pop(k)


@pytest.mark.parametrize("tweak,tono,rest,say", [
    (_unsure, "11:00 EST?", "Ext 13:00 EST", "; not sure, the earlier reading is shown. Details"),
    (_same, "11:00 EST", "Ext same (60 h FDP in 168 h)", "the same with one (60 h FDP in 168 h)"),
    (_not_legal, "NOT LEGAL", "FT 13:05 of 13:00", "Not legal to dispatch: FT 13:05 of 13:00. Details"),
    (_early, "11:00 EST", "Over as scheduled", "; Over as scheduled. Details"),
    (_old, "17:15 HST", "Ext 17:15 HST", "Timeout 17:15 HST without an extension, 17:15 HST with one, 13:00 flight time"),
])
def test_card_box_says_not_sure_not_legal_the_same_or_over(browser, tmp_path, tweak, tono, rest, say):
    pg = browser.new_page(viewport={"width": 390, "height": 844})
    pg.set_content(_page(_watcher_only(tmp_path, tweak=tweak)))
    box = pg.locator("flight-watcher-layover-card [data-to]")
    assert box.locator("[data-tono]").inner_text() == tono
    assert rest in box.inner_text() and say in box.get_attribute("aria-label")
    box.click()
    det = pg.locator("flight-watcher-layover-card [data-todet]").inner_text()
    if tweak is _unsure:
        assert "? Not sure: which clock enters the tables: the earlier reading is shown" in det
    if tweak is _not_legal:
        assert "Not legal to dispatch: 13:05 of planned flight time is over the 13:00 limit" in det
    if tweak is _old:
        assert "No extension: 17:15 HST Fri Feb 19, release 17:30 HST" in det
    assert pg.evaluate("document.documentElement.scrollWidth") <= 390
    pg.close()


def test_card_without_the_attribute_shows_no_box_and_nothing_else_changes(browser, tmp_path):
    pg = browser.new_page(viewport={"width": 390, "height": 844})
    pg.set_content(_page(_watcher_only(tmp_path, timeout=False)))
    card = pg.locator("flight-watcher-layover-card")
    assert card.locator("[data-to]").count() == 0 and card.locator("[data-todet]").count() == 0
    assert card.locator(".rt").count() == 0 and card.locator(".hd.wt").count() == 0 and card.locator(".tmw").count() == 0
    assert card.locator("[data-van] .vt").inner_text() == "08:00"
    pg.close()


def _rows(pg):
    return pg.evaluate("""() => Object.fromEntries([...window.root().querySelectorAll('.tm > div')].map(d =>
        [d.querySelector('.k').innerText, Math.round(d.getBoundingClientRect().height)]))""")


@pytest.mark.parametrize("width", [320, 390, 1280])
def test_card_with_hark_and_a_van_puts_the_box_right_of_the_report_line(browser, tmp_path, width):
    """Hark's sensor (the admin's layover data) carries no timeout: the Watcher's for the same pairing and origin shows,
    right of the Report line (the van holds the header); Departs and Arrives keep the card's full width, as without the
    box. On a wide card the box sits just after the report text. Another pairing's timeout never shows."""
    st = _states(tmp_path, notes=False)
    pg = browser.new_page(viewport={"width": width, "height": 844})
    pg.set_content(_page(st))
    before = _rows(pg)
    pg.close()
    t = copy.deepcopy(acceptance()["attributes"]["timeout"])
    t["last_out"]["leg"] = "SYD-HNL"
    st["sensor.flight_watcher_working_flight"]["attributes"]["timeout"] = t
    pg = browser.new_page(viewport={"width": width, "height": 844})
    pg.set_content(_page(st))
    card = pg.locator("flight-watcher-layover-card")
    assert card.locator("[data-van] .vl").inner_text().lower() == "van"
    box, line = card.locator(".tmw [data-to]"), card.locator(".tm div", has_text="Report")
    assert box.is_visible() and box.locator("[data-tono]").inner_text() == "11:00 EST"
    assert box.locator(".tol").inner_text().lower() == "last out"  # the card's own leg: no leg named
    bb, lb = box.bounding_box(), line.bounding_box()
    assert bb["y"] < lb["y"] + lb["height"] and lb["y"] < bb["y"] + bb["height"] and bb["x"] >= lb["x"] + lb["width"] - 1
    after = _rows(pg)
    assert after["Departs"] == before["Departs"] and after["Arrives"] == before["Arrives"], (before, after)
    if width >= 1000:
        assert bb["x"] - (lb["x"] + lb["width"]) <= 12  # just after the report text, not at the far edge
    cb = card.bounding_box()
    assert bb["x"] + bb["width"] <= cb["x"] + cb["width"] + 0.5
    assert pg.evaluate("document.documentElement.scrollWidth") <= width
    pg.close()
    st["sensor.flight_watcher_working_flight"]["attributes"]["origin"] = "HNL"  # another leg than Hark's
    pg = browser.new_page(viewport={"width": width, "height": 844})
    pg.set_content(_page(st))
    assert pg.locator("flight-watcher-layover-card [data-to]").count() == 0
    pg.close()


def test_card_box_stays_inside_the_card_at_320_with_a_long_next_day_time(browser, tmp_path):
    def long(t):
        t["last_out"].update(txt="23:55 UTC+08", wd="Sat")
        t["last_out_ext"].update(txt="01:55 UTC+08", wd="Sun")
    pg = browser.new_page(viewport={"width": 320, "height": 700})
    pg.set_content(_page(_watcher_only(tmp_path, tweak=long)))
    card = pg.locator("flight-watcher-layover-card")
    bb, cb = card.locator("[data-to]").bounding_box(), card.bounding_box()
    assert bb["x"] >= cb["x"] - 0.5 and bb["x"] + bb["width"] <= cb["x"] + cb["width"] + 0.5, (bb, cb)
    assert pg.evaluate("document.documentElement.scrollWidth") <= 320
    pg.close()


SHOTS = os.environ.get("FW_171_SHOTS", "")


@pytest.mark.parametrize("width", [390, 1100])
@pytest.mark.parametrize("theme", ["light", "dark", "ha-light", "ha-dark"])
def test_card_timeout_box_reads_on_every_theme(browser, tmp_path, width, theme):
    """WCAG AA for every text node (the box's text is the theme's own colors), the dark orange border at least 3:1
    against the card on light and dark, no sideways scroll; the basis open too."""
    pg = browser.new_page(viewport={"width": width, "height": 844})
    pg.set_content(_page(_watcher_only(tmp_path, tweak=_early),
                         theme={"light": LIGHT, "dark": DARK, "ha-light": HA_LIGHT, "ha-dark": HA_DARK}[theme]))
    card = pg.locator("flight-watcher-layover-card")
    card.locator("[data-to]").click()
    card.locator("[data-k=tobasis] summary").click()
    assert pg.evaluate("document.documentElement.scrollWidth") <= width
    con = pg.evaluate("window.fwContrast(window.root().host)")
    assert con["n"] > 20 and not con["fails"], json.dumps(con["fails"], indent=1)
    ratio = pg.evaluate("""() => { const b = window.root().querySelector('[data-to]');
        const rgb = (c) => c.match(/\\d+(\\.\\d+)?/g).slice(0, 3).map(Number);
        const lum = (c) => { const f = (v) => { v /= 255; return v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
          const [r, g, bl] = rgb(c); return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(bl); };
        const x = lum(getComputedStyle(b).borderTopColor), y = lum(getComputedStyle(b).backgroundColor);
        return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); }""")
    assert ratio >= 3, ratio
    if width == 1100:  # room for all: the box beside the report block, both beside the title
        bb, fl = card.locator("[data-to]").bounding_box(), card.locator(".fl").bounding_box()
        assert bb["y"] < fl["y"] + fl["height"]
    for d in (tmp_path, SHOTS):
        if d:
            pg.screenshot(path=os.path.join(str(d), f"fw1720_timeout_{width}_{theme}.png"), full_page=True)
    pg.close()
