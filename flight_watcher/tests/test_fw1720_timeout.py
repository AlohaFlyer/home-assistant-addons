"""1.7.20 (Ryan, Nov 20, 2026: "I need this page to calculate per FAR 117 and PWA when I timeout, both for if I extend
or if I do not. Add that number in bold with a dark orange square around it right of the report time", and "the number I
need to know is when is the last moment I can block out and be legal"): the last legal block-out and the duty limits
(timeout.py, FOM 125.4 4.3.2 = 14 CFR 117 Tables A, B and C; FOM 5.1.23.7 and 5.1.23.8 crew rest; PWA 2.A.19.b and the
PWA 2023 Section 10 duty, rest and landing limits), as working.py puts them on sensor.<prefix>_working_flight, and the
layover card's box in a real Chromium.

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
    """By hand: report 1:15 before 09:15 EST = 08:00 EST, 03:00 HST (PWA 2.A.19.b.1). Free since the BOS release (02:10
    + 0:15 HST Feb 18) 24:35 < 36 h, in the BOS theater 24:50 < 72 h, BOS 87 deg from HNL: not acclimated, HNL time
    03:00. Table C 0000-0559, Class 1 (A330 LDMCR), 3 pilots: 15:00 less 0:30 = 14:30, FDP end 17:30 HST, 19:30 with the
    extension. Last out = 17:30 less 11:30 = 06:00 HST = 11:00 EST; with the extension 08:00 HST = 13:00 EST. Flight
    time 11:30 of 13:00, 1:30 spare; out on time the block-in is due by 04:15 + 13:00 = 17:15 HST, with or without the
    extension (it adds no flight time). Class 2: 13:30, ends 16:30 (last out 10:00 EST); Class 3 12:30, 15:30 (09:00
    EST). 100 h in 672 h from Jan 22 15:45: 5:50 + 8:40 + 6:50 + 5:55 + 6:00 + 10:40 + 9:50 + 5:20 + 5:35 + 9:50 + 11:30
    = 86:00. 60 h in 168 h from Feb 12 15:45: 6:20 + 6:50 + 10:50 + 12:45 = 36:45."""
    r = acceptance()
    a = r["attributes"]
    assert r["state"] == "HA9062 BOS-HNL" and a["leg"] == "2 of 2" and a["report"] == "08:00 local, 03:00 HST"
    t = a["timeout"]
    # the BOS rest (PWA, below) is met by 2:25 from release to report, under VAN_RIDES 2:30: '?', its chip only
    assert t["legal"] is True and t["sure"] is True and t["unsure"] == [] and t["flags"] == ["rest_q"]
    lo, lx = t["last_out"], t["last_out_ext"]
    assert (lo["txt"], lo["hst"], lo["day"], lo["wd"], lo["z"]) == ("11:00 EST", "06:00 HST", "Fri Feb 19", "",
                                                                    "16:00Z")
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
    assert (c["ft_672"]["used"], c["ft_672"]["room"], c["ft_672"]["txt"]) == ("86:00", "14:00",
                                                                              "100 h in 672 h: 14:00 spare")
    assert (c["fdp_168"]["used"], c["fdp_168"]["room"]) == ("36:45", "23:15")
    assert t["rest"] == {"free": "24:35", "ok": True, "week": "75:00", "week_ok": True, "cite": "FAR 117.25(e)",
                         "txt": "24:35 free, 10:00 needed (FAR 117.25(e)): met; 30 h free in 168 h (FAR 117.25(b)): "
                                "longest 75:00, met"}
    lines = "\n".join(t["lines"])
    for w in ("Report 08:00 EST (03:00 HST Fri Feb 19): 1:15 before scheduled departure out of domicile (PWA "
              "2.A.19.b.1)",
              "not acclimated: BOS is 87 deg from HNL, 24:35 free from duty (36 h needed), 24:50 in that theater (72 h "
              "needed)", "FAR 117.13(b), 117.17(b), FOM 4.3.2.4", "3 pilots (the trip's crew list): augmented, Table C",
              "A330 LDMCR bunks 1 and 4 (FOM 5.1.23.8), all LDMCR available",
              "Class 1 ends 17:30 HST; Class 2 16:30 HST "
              "(last out 10:00 EST), Class 3 15:30 HST (last out 09:00 EST) (Class 1 assumes the bunks are usable",
              "Table C row 0000-0559 (HNL time 03:00), Class 1, 3 pilots: 15:00, less 0:30 = FDP 14:30, ends 17:30 HST",
              "the FDP end less the scheduled 11:30 from this leg's out (09:15 EST) to the duty's last block-in (15:45 "
              "HST): 11:00 EST (06:00 HST Fri Feb 19) without an extension, 13:00 EST (08:00 HST Fri Feb 19) with it",
              "Flight time 11:30 of 13:00 (FAR 117.11, FOM 4.3.2.2): 1:30 spare, a duration",
              "Out on time (09:15 EST, 04:15 HST) the block-in is due by 17:15 HST; it moves with the actual out",
              "FAR 117.19(a), FOM 4.3.2.5", "FAR 117.19(b)", "86:00 at the scheduled block-in 15:45 HST, 14:00 spare",
              "FAR 117.23(c)(1)", "24:35 free from duty since the last release, 10 h needed: met",
              "longest free period 75:00: met",
              "Duty ends 15 min after block-in (PWA 2.A.19.b): release 17:45 HST at the "
              "FDP end without an extension, 19:45 HST with one"):
        assert w in lines, w
    # PWA Section 10 (ADDENDUM 2), by hand: an IRO Crew (3 pilots, 2.A.40), Maximum 18:00 (10.D.1.b.1): from 03:00 HST
    # the duty ends by 21:00 HST; BOS-HNL is domestic, debrief 0:15, so the last block-in is 20:45 HST, less the 11:30
    # block: 09:15 HST = 14:15 EST, later than both FAR last outs: not binding. Scheduled 03:00 to 16:00 HST = 13:00 of
    # 16:00. The duty before it (HNL-BOS, report 15:20 HST Feb 17, in 02:10 HST Feb 18, release 02:25) is 11:05, so the
    # BOS rest is 2 x 11:05 = 22:10 (10.E.1.a.1); release to report 24:35, 2:25 spare, under the 2:30 the two van rides
    # may take (hotel time door to door, 10.E.1.a.3): '?'. BOS-HNL departs 09:15 EST: no 10.E.1.b. 1 landing of 10.
    p = t["pwa"]
    assert (p["cite"], p["scheduled"], p["maximum"], p["duty"], p["debrief"], p["binds"]) == (
        "10.D.1.b.1", "16:00", "18:00", "13:00", "0:15", [])
    assert (p["end_txt"], p["in_txt"], p["last_out_txt"], p["last_out_hst"]) == ("21:00 HST", "20:45 HST", "14:15 EST",
                                                                                 "09:15 HST")
    assert p["rest"] == {"need": "22:10", "have": "24:35", "ok": None, "cite": "10.E.1.a.1", "late": False}
    assert p["landings"] == {"n": 1, "max": 10, "ok": True}
    assert p["txt"] == ("scheduled duty 13:00 (Scheduled limit 16:00), Maximum 18:00 (10.D.1.b.1): last out 14:15 EST "
                        "(not binding: FAR 117 is earlier) \u00b7 rest 24:35, 22:10 needed (10.E.1.a.1): ? \u00b7 "
                        "landings 1 (10 may be scheduled, 11 if required)")
    for w in ("PWA duty limit (10.D.1.b.1): IRO Crew (2.A.40): Scheduled 16:00, Maximum 18:00 of Duty Period (Local "
              "Times, 2.A.43; from the later of the scheduled and actual report, 10.D.5, to 15 min after the last "
              "block-in, 2.A.19.b)", "From the report 08:00 EST it ends by 21:00 HST Fri Feb 19, the last "
              "block-in by 20:45 HST, so the last out is 14:15 EST (09:15 HST Fri Feb 19): not binding (FAR 117 is "
              "earlier).",
              "PWA duty scheduled 13:00 of 16:00 (10.D.1.b.1).", "No 5.A.6 transfer time is added (none serves HNL; "
              "10.D.1.b.2 bars them for an IRO Crew)", "10.D.4 is Interisland", "the PWA Maximum caps both last outs",
              "PWA rest before this duty (10.E.1.a.1): out of domicile, 2 x the preceding Duty Period 11:05 (15:20 HST "
              "Wed Feb 17 to release 02:25 HST Thu Feb 18) = 22:10 needed; release to report 24:35: ? met by 2:25 from "
              "release to report, but the hotel time (door to door, 2.A.68.b, 10.E.1.a.3) is shorter by the two van "
              "rides, which are not on the schedule (under 2:30 spare is not sure).",
              "PWA 10.E.1.b (18:00 rest when a segment departs 1400-0359 local and the scheduled Duty Period is "
              "12:00+): not "
              "triggered (BOS-HNL departs 09:15 EST).",
              "Landings (PWA 10.H.1): 1 flown segment; no more than 10 may be scheduled (11 if required to perform)."):
        assert w in lines, w
    assert "the PWA duty limit" not in lines  # it binds neither: the last out line is the FAR one
    for w in ("FAR 117.19(a)(2)", "In-flight rest of an augmented FDP (FOM 4.3.2.4.2)", "8 h sleep opportunity",
              "1000 h flight time in 365 days", TO.PWA_NC_IRO, TO.PWA_NC):
        assert any(w in s for s in t["not_checked"]), w
    assert not any("Section 10" in s for s in t["not_checked"])
    blob = json.dumps(t)
    assert chr(0x2014) not in blob and not any(w in blob for w in ("Doe", "Roe", "Poe", "10001", "10002", "10003"))
    assert len(json.dumps(r)) < 10000  # review TEST-1: a heavier case is guarded below (HA keeps 16 KB at most)


def test_acceptance_with_every_trip_read_gives_the_same_times():
    """Legs read for every trip (not just duty periods) give the same numbers."""
    a, b = acceptance()["attributes"]["timeout"], acceptance(legs_read=True)["attributes"]["timeout"]
    for k in ("last_out", "last_out_ext", "no_ext", "ext", "fdp", "ft", "cum", "rest"):
        assert a[k] == b[k], k


def test_cumulative_needs_the_whole_window_on_file():
    """No schedule months: the cumulative limits and the 30 h in 168 h are listed as not checked, and the last out
    stands without them. A window that reaches before the first month on file is not checked either."""
    t = acceptance(months=None)["attributes"]["timeout"]
    assert t["cum"] == {} and t["last_out"]["txt"] == "11:00 EST" and t["no_ext"]["txt"] == "17:15 HST"
    assert sum("not all on file, not checked" in s for s in t["not_checked"]) == 3
    assert any(s.startswith("30 h free from duty in the 168 h before this FDP (FAR 117.25(b)")
               for s in t["not_checked"])
    t = acceptance(months=months_for("2027-02"))["attributes"]["timeout"]
    assert set(t["cum"]) == {"fdp_168"}  # 168 h back from Feb 19 is in February; 672 h is not
    assert any(s.startswith("100 h flight time in 672 h (FAR 117.23(b)(1)): your line before")
               for s in t["not_checked"])


def test_the_package_crew_line_counts_when_there_is_no_roster_and_a_mismatch_is_said():
    key, rep, legs = BOS_TRIP
    it, rec = trip(key, rep, legs, [])
    t = run([(key, (it, rec))], at(2027, 2, 19, "01:00"), {key: BOS_PKG})["attributes"]["timeout"]
    assert t["fdp"]["pilots"] == 3 and t["fdp"]["pilots_from"] == "package crew line CA01FO01RO01"
    it, rec = trip(key, rep, legs, CREW3)
    t = run([(key, (it, rec))], at(2027, 2, 19, "01:00"), {key: {"eq": "332",
                                                                 "crew": "CA01FO02RO01"}})["attributes"]["timeout"]
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
    t = run([(key, trip(key, "05:10", SIN_LONG, crew))], at(2027, 3, 2, "04:00"),
            {key: {"eq": "332"}})["attributes"]["timeout"]
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
    t = run([(key, trip(key, "05:10", SIN_LONG, CREW3))], at(2027, 3, 2, "04:00"),
            {key: {"eq": "332"}})["attributes"]["timeout"]
    assert t["fdp"]["pilots"] == 4 and t["legal"] is True and "pilots" in t["unsure"] and "pilots" in t["flags"]
    assert any(s.startswith("Flag: 3 pilots (the trip's crew list) may not fly 13:05 of planned flight time")
               for s in t["lines"])
    # the package line says 3 as well: the count is firm and the duty is not legal to dispatch at any time
    t = run([(key, trip(key, "05:10", SIN_LONG, CREW3))], at(2027, 3, 2, "04:00"),
            {key: {"eq": "332", "crew": "CA01FO01RO01"}})["attributes"]["timeout"]
    assert t["legal"] is False and t["last_out"] is None and t["last_out_ext"] is None
    assert t["not_legal_short"] == "FT 13:05 of 13:00" and "not legal to dispatch at any time" in t["not_legal"]
    assert t["no_ext"]["legal"] is False and any(s.startswith("Not legal: 13:05 of planned flight time")
                                                 for s in t["lines"])


# ---------------------------------------------------------------- acclimated at home, Table C by HNL time
SYD_OUT = [(0, "9011", "HNL", "SYD", "11:20", "19:05", "10:45")]  # 22:05 HST in (AEDT, 21 h ahead)


def test_acclimated_hnl_report_table_c_by_hnl_time_with_no_reduction():
    key = "H3910|2027-02-08"
    t = run([(key, trip(key, "10:20", SYD_OUT, CREW3))], at(2027, 2, 8, "09:00"),
            {key: {"eq": "332"}})["attributes"]["timeout"]
    f = t["fdp"]
    assert f["acclimated"] is True and f["row"] == "0700-1259 (HNL time 10:20)" and f["limit"] == "17:00"
    assert f["end_txt"] == "03:20 HST" and f["ext_end_txt"] == "05:20 HST" and f["alt"] == {"2": "02:50 HST",
                                                                                            "3": "01:20 HST"}
    # last out 03:20 less 10:45 = 16:35 HST (same day); out on time, 13:00 flight time: block-in by 00:20 HST the next
    # day
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
    # SIN arrival 19:15 HST Mar 2, release 19:45 (clearing customs at SIN, PWA 2.A.19.b); report 1:15 before 13:30 SGT
    # = 12:15 SGT Mar 5 (18:15 HST Mar 4): 46:30 free: acclimated to SIN
    assert f["acclimated"] is True and f["row"] == "0700-1259 (SIN time 12:15)"
    assert f["pilots"] == 4 and f["rest_class"] == 2 and f["limit"] == "18:00"  # 4 pilots on the A330: Class 2, '?'
    assert f["rest_class_sure"] is False and t["unsure"] == ["rest class"] and f["alt"] == {"1": "13:15 HST",
                                                                                            "3": "09:45 HST"}
    assert any("acclimated to the SIN theater (46:30 free from duty" in s for s in t["lines"])
    assert any("requires pilot crew rest seat 3C or 3G" in s for s in t["lines"])
    # FAR alone: FDP end 12:15 HST Mar 5 less 13:40 = 22:35 HST Mar 4 = 16:35 SGT Mar 5 (SGT has no letters on file, so
    # the box names the station: "SIN", review I7, never "UTC+08"). The PWA
    # binds: an Extended Range Crew of 1 Captain (CA01FO02RO01, 2.A.25) may not be required past 18:00 of Duty Period
    # (10.D.1.c), which ends 30 min after block-in clearing customs at HNL (2.A.19.b): 18:15 HST + 18:00 = 12:15 HST,
    # last block-in 11:45, less 13:40 = 22:05 HST = 16:05 SGT, with and without an extension
    assert (t["last_out"]["txt"], t["last_out"]["hst"]) == ("16:05 SIN", "22:05 HST")
    assert t["last_out"]["short"] == t["last_out_ext"]["short"] == "PWA max duty 18 h" and t["last_out"]["pwa"] is True
    assert t["last_out"]["by"] == "PWA 10.D.1.c max duty 18 h" and t["pwa"]["binds"] == ["no_ext", "ext"]
    assert "UTC+" not in json.dumps(t)
    assert (t["no_ext"]["txt"] == "11:45 HST" and t["fdp"]["in_txt"] == "11:45 HST"
            and t["fdp"]["end_txt"] == "12:15 HST")
    rel = datetime.fromisoformat(t["no_ext"]["at"]) + timedelta(minutes=30)  # into HNL from SIN: customs
    assert t["no_ext"]["release_txt"] == f"{rel.astimezone(HST):%H:%M} HST"
    assert any("Duty ends 30 min after block-in, clearing customs (PWA 2.A.19.b)" in s for s in t["lines"])


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
    assert any("HNL is 98 deg from SIN, 24:20 free from duty (36 h needed), 24:50 in that theater" in s
               for s in t["lines"])


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
    assert any("? acclimation not known: a span of your line before this report is not on file" in s
               for s in t["lines"])
    # the rest before it is at least the 10:00 since the end of the unread trip's last day: met
    assert t["rest"] == {"free": "10:00", "ok": True, "cite": "FAR 117.25(e)",
                         "txt": "at least 10:00 free, 10:00 needed (FAR 117.25(e)): met"}
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
    t = run([(key, trip(key, "05:20", TURNS, CREW2))], at(2027, 3, 12, "05:00"),
            {key: {"eq": "332"}})["attributes"]["timeout"]
    f = t["fdp"]
    assert f["table"] == "B" and f["segments"] == 3 and f["row"] == "0500-0559 (HNL time 05:20)"
    assert f["limit"] == "12:00" and f["end_txt"] == "17:20 HST" and f["rest_class"] is None and f["alt"] == {}
    # the last out of the working leg (leg 1): 17:20 less 9:15 scheduled to the last block-in (15:35) = 08:05 HST; with
    # the extension FAR alone gives 10:05, but HNL-OGG-HNL-LAX is Mixed Flying (2.A.45: HNL-LAX is 3:00 or more, the
    # OGG turn is interisland and no Repositioning Flight, 2.A.62), so 14:00 for a standard crew (10.D.3): 05:20 +
    # 14:00 = 19:20, less the 0:15 debrief = 19:05 last block-in, less 9:15 = 09:50 HST
    assert (t["last_out"]["txt"], t["last_out_ext"]["txt"], t["last_out"]["leg"]) == ("08:05 HST", "09:50 HST",
                                                                                      "HNL-OGG")
    assert t["last_out_ext"]["by"] == "PWA 10.D.3 max duty 14 h" and t["pwa"]["mixed"] is True
    assert t["pwa"]["landings"] == {"n": 3, "max": 4, "ok": True}  # Mixed Flying: 4 landings (10.H.3)
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
        {"dep": at(2027, 3, 12, "07:00"), "arr": at(2027, 3, 12, "12:00"), "blk": 300, "frm": "HNL", "to": "LAX",
         "flt": "1"},
        {"dep": at(2027, 3, 12, "13:00"), "arr": at(2027, 3, 12, "14:30"), "blk": 90, "frm": "LAX", "to": "SFO",
         "flt": "2", "dh": True}]}]
    t = TO.duty_timeout(duties, 0, 2, "roster", "332")
    assert t["fdp"]["segments"] == 1 and t["sched_in_txt"] == "12:00 HST"
    assert t["ft"]["end_txt"] == "16:00 HST"  # 9:00 from 07:00 out; the deadhead is no flight time
    assert TO.duty_timeout([{"report": duties[0]["report"], "legs": duties[0]["legs"][1:]}], 0, 2, "roster",
                           "332") is None


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
    t = run([(key, trip(key, rep, legs, CREW3))], at(2027, 3, 12, "04:00"),
            {key: {"eq": "332"}})["attributes"]["timeout"]
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
    t = run([(key, trip(key, "05:10", SIN_LONG, CREW4))], at(2027, 3, 2, "04:00"),
            {key: {"eq": "332"}})["attributes"]["timeout"]
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
    assert ("equipment not on file" in line and "Class 3 used" in line and "(?)" in line
            and "assumes the bunks" not in line)
    assert any("Class 3 ?, 3 pilots" in s for s in t["lines"])
    t787 = run([(key, trip(key, "10:20", SYD_OUT, CREW3))], at(2027, 2, 8, "09:00"),
               {key: {"eq": "789"}})["attributes"]["timeout"]
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
    assert (t["fdp"]["end_txt"] == "21:00 HST" and t["fdp"]["in_txt"] == "16:00 HST"
            and t["fdp"]["ext_in_txt"] == "16:00 HST")
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
            (0, f"908{k}", "HNL", "SFO", "07:00", "14:00", "5:00"), (0, f"909{k}", "SFO", "HNL", "15:30", "18:45",
                                                                     "5:15")],
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
    t = run([(key, trip(key, "07:10", legs, CREW2))], at(2027, 7, 12, "05:00"),
            {key: {"eq": "332"}})["attributes"]["timeout"]
    # 09:10 PDT is 06:10 HST: report 1:15 before, 04:55 HST = 07:55 PDT. Acclimated to the HNL theater (LAX within 60
    # deg); HNL time gives Table B 0400-0459 (10:00), LAX time 0700-1159 (14:00): the lower is used and marked '?'
    assert t["report_txt"] == "04:55 HST" and t["fdp"]["acclimated"] is True
    assert t["fdp"]["row"] == "0400-0459 (HNL time 04:55)" and t["fdp"]["limit"] == "10:00"
    assert t["sure"] is False and t["unsure"] == ["clock"] and t["last_out"]["sure"] is False
    # last out 14:55 HST less 5:30 = 09:25 HST = 12:25 PDT; on the LAX clock 18:55 less 5:30 = 13:25 HST = 16:25 PDT;
    # with the extension that reading's 20:55 is past the PWA 16:00 duty Maximum (10.D.1.a): 04:55 + 16:00 = 20:55 less
    # the 0:15 debrief = 20:40, less 5:30 = 15:10 HST = 18:10 PDT
    assert t["last_out"]["txt"] == "12:25 PDT"
    assert t["fdp"]["other"] == {"clock": "LAX time 07:55", "row": "0700-1159", "limit": "14:00",
                                 "last_out_txt": "16:25 PDT", "last_out_ext_txt": "18:10 PDT"}
    assert any(s.startswith("Other reading: LAX time 07:55 gives row 0700-1159, FDP 14:00 and 9:00 flight time, last "
                            "out 16:25 PDT (18:10 PDT with the extension). FOM 4.3.2.4") for s in t["lines"])
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
    t = run([(key, trip(key, "07:00", legs, CREW2))], at(2027, 3, 10, "06:00"),
            {key: {"eq": "332"}})["attributes"]["timeout"]
    ends = lambda t: next(s for s in t["lines"] if s.startswith("Duty ends"))  # noqa: E731
    assert "clearing customs" in ends(t)  # LNK is not on the Watcher's US list: not known, conservative
    # review PWA-5: watcher.release_customs (a last leg from outside the US) gives 15 min here: the basis says so
    assert any(s.startswith("Customs (2.A.19.b): HNL-LNK crosses a border (or a country not on file), so the debrief "
                            "is 30 min here") for s in t["lines"])
    t = run([(key, trip(key, "07:00", legs, CREW2))], at(2027, 3, 10, "06:00"), {key: {"eq": "332"}},
            domestic={"LNK"})["attributes"]["timeout"]
    assert "clearing customs" not in ends(t) and not any(s.startswith("Customs") for s in t["lines"])


def test_a_station_with_no_clock_is_never_read_as_its_own_time():
    duties = [{"report": at(2027, 3, 10, "06:00"), "legs": [
        {"dep": at(2027, 3, 10, "07:00"), "arr": at(2027, 3, 10, "12:00"), "blk": 300, "frm": "HNL", "to": "XYZ",
         "flt": "1"}]},
              {"report": at(2027, 3, 11, "06:00"), "legs": [
                  {"dep": at(2027, 3, 11, "07:00"), "arr": at(2027, 3, 11, "12:00"), "blk": 300, "frm": "XYZ",
                   "to": "HNL",
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
               extra_items=[{"trip": "TRNG", "start": "2027-03-06", "end": "2027-03-06",
                             "lay": ""}])["attributes"]["timeout"]
    assert busy["fdp"]["acclimated"] is None and busy["unsure"] == ["acclimation"]
    # SIN time 04:30 (Mar 8): Table B 0400-0459, 10:00 less 0:30 is lower than HNL 0700-1159's 14:00
    assert busy["fdp"]["row"] == "0400-0459 (SIN time 04:30)" and busy["fdp"]["limit"] == "9:30"
    assert any(s.startswith("Acclimation (FAR 117.3, FOM 4.3.2.4.6): ? acclimated to HNL only if")
               for s in busy["lines"])
    # review round 5 (RV5-3): the training day (Mar 6, ending 00:00 HST Mar 7) ends 10:30 before the report, outside
    # FAR 117.25(e)'s 10 h, so even as duty it leaves 10 h; it ends inside 10.E.1.a's 11:00: '?'. Review round 5, fix 2
    # (RF1-ITEM-DEADHEAD): the item runs 24:00, over 8:30, so a deadhead in it may need 24:00 (FAR 117.25(g)); 10:30
    # since it: '?' (round 4's '?' kept, round 5: met)
    assert (busy["rest"]["ok"], busy["rest"]["cite"], busy["pwa"]["rest"]["ok"]) == (None, "FAR 117.25(g)", None)
    assert any(s.startswith("Rest before this FDP (FAR 117.25(e)") and "met even if the schedule item ending 00:00 HST "
               "Sun Mar 7 (10:30 before the report) is duty" in s for s in busy["lines"])
    vac = run(trips, at(2027, 3, 7, "09:00"), pkg,
              extra_items=[{"trip": "VAC", "start": "2027-03-06", "end": "2027-03-06",
                            "lay": ""}])["attributes"]["timeout"]
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


# ------------------------------------------------------------ the Watcher passes the package detail (both instances)
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
    assert [s for s in said
            if "duty timeout" in s] == ["working flight: duty timeout not worked out (ZeroDivisionError)"]


# ---------------------------------------------------------------- PWA Section 10 (ADDENDUM 2): duty, rest, landings
# Every case below is worked by hand from PWA 10.D, 10.E.1, 10.H.1 and 2.A.19.b / 2.A.25 / 2.A.40 / 2.A.45 / 2.A.62
# (Local Times, 2.A.43) and FOM 125.4 4.3.2 (FAR 117 Tables A, B and C), before the code.
def _leg(frm, to, dep, arr, flt="9", dh=False):
    return {"dep": dep, "arr": arr, "blk": int((arr - dep).total_seconds() // 60), "frm": frm, "to": to, "flt": flt,
            "dh": dh}


def _duty(report, *legs):
    return {"report": report, "legs": list(legs)}


PWA_D = ("H3901|2027-02-10", "08:00", [(0, "9101", "HNL", "LAX", "09:00", "16:15", "5:15")])  # 09:00 + 5:15 = 14:15 HST


def _pwa_d():
    key, rep, legs = PWA_D
    return run([(key, trip(key, rep, legs, CREW2))], at(2027, 2, 10, "07:00"), {key: {"eq": "332", "crew": "CA01FO01"}})


def test_pwa_two_pilot_maximum_caps_the_extension():
    """(d) 2 pilots HNL-LAX, report 08:00 HST, block 5:15, domestic. FAR: Table B 0700-1159, 1 segment, 14:00: FDP end
    22:00, last out 22:00 - 5:15 = 16:45 HST; with the 2:00 extension 18:45. PWA 10.D.1.a (the LOA's table): Maximum
    16:00, so the duty ends by 00:00 HST, the last block-in by 23:45 (0:15 debrief, 2.A.19.b), the last out 23:45 - 5:15
    = 18:30 HST: it caps the extension (18:45 -> 18:30), not the 16:45. Scheduled 08:00 to 14:30 = 6:30 of 14:00."""
    t = _pwa_d()["attributes"]["timeout"]
    lo, lx, p, f = t["last_out"], t["last_out_ext"], t["pwa"], t["fdp"]
    assert (lo["txt"], lo["by"], lo["pwa"]) == ("16:45 HST", "FDP 14:00 (FAR 117.13, Table B)", False)
    assert (lx["txt"], lx["by"], lx["short"], lx["pwa"]) == ("18:30 HST", "PWA 10.D.1.a max duty 16 h",
                                                             "PWA max duty 16 h",
                                                             True)
    assert t["legal"] is True and t["sure"] is True and t["flags"] == []
    assert (p["cite"], p["crew"], p["scheduled"], p["maximum"], p["duty"], p["binds"]) == (
        "10.D.1.a", "2 pilots", "14:00", "16:00", "6:30", ["ext"])
    assert (p["end_txt"], p["in_txt"], p["last_out_txt"]) == ("00:00 HST", "23:45 HST", "18:30 HST")
    # the block-in limits: the FDP's own ends stay FAR's; the block-in with the extension is the PWA's, its release
    # 00:00
    assert (f["end_txt"], f["ext_end_txt"], f["in_txt"], f["ext_in_txt"]) == ("22:00 HST", "00:00 HST", "22:00 HST",
                                                                             "23:45 HST")
    assert (f["release_txt"], f["ext_release_txt"]) == ("22:15 HST", "00:00 HST")
    # out on time the block-in is due by 09:00 + Table A 9:00 = 18:00 either way (flight time binds before the PWA)
    assert t["no_ext"]["txt"] == t["ext"]["txt"] == "18:00 HST" and t["ft"]["txt"] == "5:15 of 9:00 (3:45 spare)"
    lines = "\n".join(t["lines"])
    for w in ("Last out (block-out): the FDP end, or the PWA duty limit's last block-in when earlier, less the "
              "scheduled 5:15",
              "16:45 HST (16:45 HST Wed Feb 10) without an extension, 18:30 HST (18:30 HST Wed Feb 10) with it "
              "(FDP 14:00; PWA max duty 16 h)", "PWA duty limit (10.D.1.a): 2 pilots: Scheduled 14:00, Maximum 16:00",
              "it ends by 00:00 HST Thu Feb 11, the last block-in by 23:45 HST, so the last out is 18:30 HST (18:30 "
              "HST Wed Feb 10): binding with the extension (FAR 117 alone: 16:45 HST, 18:45 HST with the extension).",
              "PWA duty scheduled 6:30 of 14:00 (10.D.1.a).", "No 5.A.6 transfer time is added (none serves HNL), ",
              "Landings (PWA 10.H.1): 1 flown segment; no more than 10 may be scheduled (11 if required to perform).",
              "PWA 10.E.1.b (18:00 rest when a segment departs 1400-0359 local and the scheduled Duty Period is "
              "12:00+): not "
              "triggered (HNL-LAX departs 09:00 HST)."):
        assert w in lines, w
    assert "PWA rest before this duty (10.E.1.a): the duty before it is not on file" in t["not_checked"]
    assert TO.PWA_NC in t["not_checked"] and TO.PWA_NC_IRO not in t["not_checked"]  # 10.D.1.b.4 is an IRO Crew's
    assert p["txt"] == ("scheduled duty 6:30 (Scheduled limit 14:00), Maximum 16:00 (10.D.1.a): last out 18:30 HST "
                        "(binds with the extension) · rest not on file · landings 1 (10 may be scheduled, 11 if "
                        "required)")


def test_pwa_maximum_less_the_customs_debrief_binds_the_extension():
    """2 pilots HNL-PPT (Tahiti), report 08:00, out 09:00, block 5:45: FAR FDP 14:00 ends 22:00, last outs 16:15 and
    18:15 HST. Clearing customs at PPT the Duty Period ends 30 min after block-in (2.A.19.b): 08:00 + 16:00 = 00:00,
    last block-in 23:30, less 5:45 = 17:45 HST, which caps the extension; 15 min later than without customs."""
    key = "H3904|2027-02-10"
    t = run([(key, trip(key, "08:00", [(0, "9106", "HNL", "PPT", "09:00", "14:45", "5:45")], CREW2))],
            at(2027, 2, 10, "07:00"), {key: {"eq": "332"}})["attributes"]["timeout"]
    assert (t["last_out"]["txt"], t["last_out_ext"]["txt"]) == ("16:15 HST", "17:45 HST")
    assert t["last_out_ext"]["short"] == "PWA max duty 16 h" and t["pwa"]["debrief"] == "0:30"
    assert t["pwa"]["in_txt"] == "23:30 HST" and t["pwa"]["duty"] == "7:15"  # 08:00 to 14:45 + 0:30
    assert any("to 30 min after the last block-in, clearing customs, 2.A.19.b)" in s for s in t["lines"])


SIN4 = ("H3902|2027-03-02", "10:00", [(0, "9103", "HNL", "SIN", "11:00", "18:05", "13:05")])  # in 00:05 HST Mar 3


def _sin4(crew, code=None):
    key, rep, legs = SIN4
    pk = {"eq": "332"} | ({"crew": code} if code else {})
    return run([(key, trip(key, rep, legs, crew))], at(2027, 3, 2, "09:00"), {key: pk})["attributes"]["timeout"]


def test_pwa_four_pilots_two_captains_have_no_pwa_hours_table_c_only():
    """(e) CA02FO02: an Extended Range Crew of 2 Captains and 2 First Officers is limited by Part 117 Table C only
    (10.D.1.d). Table C 0700-1259 (HNL time 10:00), Class 2 (A330, 4 pilots), 4 pilots: 18:00: FDP end 04:00 HST, last
    out 04:00 - 13:05 = 14:55 HST, 16:55 with the extension; the PWA adds nothing."""
    t = _sin4(["CA Doe, Jane (10001)", "CA Roe, Rick (10002)", "FO Poe, Pat (10003)", "FO Moe, Max (10004)"],
              "CA02FO02")
    assert t["fdp"]["pilots"] == 4 and t["fdp"]["limit"] == "18:00" and t["fdp"]["rest_class"] == 2
    assert (t["last_out"]["txt"], t["last_out_ext"]["txt"]) == ("14:55 HST", "16:55 HST")
    assert t["last_out"]["short"] == "FDP 18:00" and t["last_out_ext"]["short"] == "FDP + 2:00 ext"
    p = t["pwa"]
    assert (p["cite"], p["maximum"], p["scheduled"], p["binds"], p["last_out_txt"]) == ("10.D.1.d", "", "", [], "")
    assert p["duty"] == "14:35"  # 10:00 to 00:05 + 0:30 customs at SIN
    assert any(s.startswith("PWA duty limit (10.D.1.d): an Extended Range Crew of 2 Captains and 2 First Officers has "
                            "no PWA duty hours of its own: Part 117 Table C governs") for s in t["lines"])
    assert "PWA crew" not in t["unsure"]


def test_pwa_four_pilots_one_captain_extended_range_crew_18_hours():
    """(f) CA01FO01RO02: an Extended Range Crew of 1 Captain (2.A.25), Scheduled 16:00, Maximum 18:00 (10.D.1.c). The
    same duty: 10:00 + 18:00 = 04:00 HST, customs at SIN (0:30): last block-in 03:30, less 13:05 = 14:25 HST, earlier
    than FAR's 14:55 and 16:55: it binds both. Scheduled 14:35 of 16:00."""
    t = _sin4(["CA Doe, Jane (10001)", "FO Roe, Rick (10002)", "RO Poe, Pat (10003)", "RO Moe, Max (10004)"],
              "CA01FO01RO02")
    lo, lx, p = t["last_out"], t["last_out_ext"], t["pwa"]
    assert (lo["txt"], lx["txt"], lo["by"], lx["by"]) == ("14:25 HST", "14:25 HST", "PWA 10.D.1.c max duty 18 h",
                                                          "PWA 10.D.1.c max duty 18 h")
    assert (p["cite"], p["scheduled"], p["maximum"], p["duty"], p["binds"], p["sure"]) == (
        "10.D.1.c", "16:00", "18:00", "14:35", ["no_ext", "ext"], True)
    assert any("Extended Range Crew of 1 Captain and 3 First Officers (2.A.25)" in s for s in t["lines"])
    assert any("binding with and without an extension (FAR 117 alone: 14:55 HST, 16:55 HST with the extension)" in s
               for s in t["lines"])
    assert t["no_ext"]["txt"] == "03:30 HST" and t["no_ext"]["by"] == "PWA 10.D.1.c max duty 18 h"
    assert "PWA crew" not in t["unsure"]
    # the Captains not known (a crew list with no CA and no package line): the 1-Captain values, marked '?'
    t = _sin4(["FO Doe, Jane (10001)", "FO Roe, Rick (10002)", "RO Poe, Pat (10003)"])
    assert t["fdp"]["pilots"] == 4 and t["last_out"]["txt"] == "14:25 HST" and t["pwa"]["sure"] is False
    assert "PWA crew" in t["unsure"] and t["sure"] is False and "(10.D.1.c?)" in t["pwa"]["txt"]


def test_pwa_duty_values_by_crew():
    h = lambda x: timedelta(hours=x)  # noqa: E731
    assert TO.pwa_duty(2)[:3] == (h(14), h(16), "10.D.1.a")
    assert TO.pwa_duty(3, 2)[:3] == (h(16), h(18), "10.D.1.b.1")  # an IRO Crew whatever its Captains (2.A.40)
    assert TO.pwa_duty(4, 1)[:3] == (h(16), h(18), "10.D.1.c")
    assert TO.pwa_duty(4, 2)[:3] == (None, None, "10.D.1.d")
    assert TO.pwa_duty(4, None)[2:] == ("10.D.1.c", TO.pwa_duty(4, None)[3], False)
    assert TO.pwa_duty(None)[:3] == (h(14), h(16), "10.D.1.a") and TO.pwa_duty(None)[4] is False
    assert TO.pwa_duty(2, 1, True)[:3] == (h(12), h(14), "10.D.3") and TO.pwa_duty(3, 1, True)[:3] == (h(14), h(16),
                                                                                                       "10.D.3")
    assert TO.pwa_duty(4, 2, True)[:3] == (h(14), h(16), "10.D.3")
    assert (TO.package_captains("CA02FO02"), TO.package_captains("CA01FO01RO01"), TO.package_captains("FO02")) == (2, 1,
                                                                                                                   None)
    assert TO.roster_captains(["CA Doe, Jane (1)", "CA OPEN", "FO Roe, Rick (2)"]) == 2


def test_mixed_flying_and_the_repositioning_flight():
    """2.A.45: a segment of 3:00 or more and an interisland one, besides a single Repositioning Flight (2.A.62: to a
    neighbor island station to leave the islands from there, or to Honolulu from one after arriving from outside)."""
    t0 = at(2027, 2, 12, "08:00")
    L = lambda a, b, h, m: _leg(a, b, t0, t0 + timedelta(hours=h, minutes=m))  # noqa: E731
    assert TO.mixed_flying([L("KOA", "HNL", 0, 45), L("HNL", "LAX", 5, 15)])
    assert TO.mixed_flying([L("HNL", "OGG", 0, 40), L("OGG", "HNL", 0, 40), L("HNL", "LAX", 5, 30)])
    assert not TO.mixed_flying([L("HNL", "OGG", 0, 40), L("OGG", "LAX", 5, 0)])  # HNL-OGG repositions (2.A.62.a)
    assert not TO.mixed_flying([L("LAX", "OGG", 5, 0), L("OGG", "HNL", 0, 40)])  # OGG-HNL repositions (2.A.62.b)
    assert TO.mixed_flying([L("HNL", "LIH", 0, 35), L("LIH", "HNL", 0, 35), L("HNL", "OGG", 0, 40), L("OGG", "LAX", 5,
                                                                                                      0)])
    assert not TO.mixed_flying([L("HNL", "LAX", 5, 15)]) and not TO.mixed_flying([L("HNL", "OGG", 0, 40)])
    assert not TO.mixed_flying([_leg("HNL", "KOA", t0, t0 + timedelta(minutes=45), dh=True), L("KOA", "LAX", 5, 0)])
    # a duty that repositions: International limits, and the basis says why
    d = _duty(at(2027, 2, 12, "07:00"), L("HNL", "OGG", 0, 40),
              _leg("OGG", "LAX", at(2027, 2, 12, "09:40"), at(2027, 2, 12, "14:40")))
    t = TO.duty_timeout([d], 0, 2, "roster", "332")
    assert t["pwa"]["cite"] == "10.D.1.a" and t["pwa"]["mixed"] is False
    assert ("Not Mixed Flying (2.A.45): HNL-OGG is a Repositioning Flight (2.A.62; a sit of 2:00 or less at the "
            "neighbor island is read as its minimal delay).") in t["lines"]


def test_pwa_mixed_flying_14_hours_binds_a_two_pilot_crew():
    """(g) KOA-HNL (0:45) then HNL-LAX (5:15), 2 pilots, report 07:00 HST: Mixed Flying (2.A.45; KOA-HNL goes to
    Honolulu before the international segment, so it is no Repositioning Flight). FAR: Table B 0700-1159, 2 segments,
    14:00: FDP end 21:00; from KOA-HNL's 08:00 out to the last block-in 15:15 is 7:15: last outs 13:45 and 15:45 HST.
    PWA 10.D.3 standard crew: Maximum 14:00: 07:00 + 14:00 = 21:00, last block-in 20:45, less 7:15 = 13:30 HST: it
    binds both. Scheduled 8:30 of 12:00. Mixed Flying landings: 2 of 4 (10.H.3)."""
    key = "H3903|2027-02-12"
    legs = [(0, "9104", "KOA", "HNL", "08:00", "08:45", "0:45"), (0, "9105", "HNL", "LAX", "10:00", "17:15", "5:15")]
    t = run([(key, trip(key, "07:00", legs, CREW2))], at(2027, 2, 12, "06:00"),
            {key: {"eq": "332"}})["attributes"]["timeout"]
    lo, lx, p = t["last_out"], t["last_out_ext"], t["pwa"]
    assert t["fdp"]["limit"] == "14:00" and t["fdp"]["segments"] == 2 and lo["leg"] == "KOA-HNL"
    assert (lo["txt"], lx["txt"], lo["short"], lx["short"]) == ("13:30 HST", "13:30 HST", "PWA max duty 14 h",
                                                                "PWA max duty 14 h")
    assert lo["by"] == "PWA 10.D.3 max duty 14 h" and p["binds"] == ["no_ext", "ext"]
    assert (p["mixed"], p["cite"], p["crew"], p["scheduled"], p["maximum"], p["duty"]) == (
        True, "10.D.3", "Mixed Flying duty (2.A.45), standard crew", "12:00", "14:00", "8:30")
    assert p["landings"] == {"n": 2, "max": 4, "ok": True}
    assert ("Landings (PWA 10.H.3, Mixed Flying): 2 flown segments; no more than 4 in a Mixed Flying Duty Period."
            in t["lines"])
    assert any("binding with and without an extension (FAR 117 alone: 13:45 HST, 15:45 HST with the extension)" in s
               for s in t["lines"])
    # augmented, the same duty: 14:00 Scheduled, 16:00 Maximum (10.D.3)
    t3 = run([(key, trip(key, "07:00", legs, CREW3))], at(2027, 2, 12, "06:00"),
             {key: {"eq": "332"}})["attributes"]["timeout"]
    assert (t3["pwa"]["scheduled"], t3["pwa"]["maximum"], t3["pwa"]["crew"]) == (
        "14:00", "16:00", "Mixed Flying duty (2.A.45), augmented crew")
    assert t3["pwa"]["last_out_txt"] == "15:30 HST"  # 07:00 + 16:00 - 0:15 - 7:15


def _rest_line():
    """HNL-SFO (report 06:00 HST, out 07:00, in 12:30, release 12:45: a 6:45 Duty Period), SFO-HNL reporting 12:00 later
    (00:45 HST, out 02:00, in 07:30, release 07:45), then HNL-LAX reporting 10:30 after that (18:15 HST, out 19:15)."""
    return [_duty(at(2027, 3, 10, "06:00"), _leg("HNL", "SFO", at(2027, 3, 10, "07:00"), at(2027, 3, 10, "12:30"),
                                                 "1")),
            _duty(at(2027, 3, 11, "00:45"), _leg("SFO", "HNL", at(2027, 3, 11, "02:00"), at(2027, 3, 11, "07:30"),
                                                 "2")),
            _duty(at(2027, 3, 11, "18:15"), _leg("HNL", "LAX", at(2027, 3, 11, "19:15"), at(2027, 3, 12, "00:30"),
                                                 "3"))]


def test_pwa_rest_short_out_of_domicile_and_in_domicile():
    """(h) Out of domicile (SFO) the rest is 2 x the preceding Duty Period (10.E.1.a.1): 2 x 6:45 = 13:30; release to
    report 12:00: short (FAR's 10 h is met). With 2 pilots the Company may limit a regular crew's hotel rest to 9:00
    (10.E.1.a.2), so 12:00 may meet the contract: a '?', not a red flag (review PWA-7; a regular crew is read as 2
    pilots). At home (10.E.1.a) 11:00: release 07:45 to report 18:15 = 10:30: short. Flags only: the last outs do not
    move."""
    ds = _rest_line()
    t = TO.duty_timeout(ds, 1, 3, "roster", "332")
    r = t["pwa"]["rest"]
    assert (r["need"], r["have"], r["ok"], r["cite"]) == ("13:30", "12:00", False, "10.E.1.a.1")
    assert "pwa_rest" in t["flags"] and t["rest"]["ok"] is True and t["legal"] is True
    assert "Flag: short of PWA rest (10.E.1.a.1): 12:00 of 13:30." in t["lines"]
    assert any(s.startswith("PWA rest before this duty (10.E.1.a.1): out of domicile, 2 x the preceding Duty Period "
                            "6:45 (06:00 HST Wed Mar 10 to release 12:45 HST Wed Mar 10) = 13:30 needed; release to "
                            "report 12:00: SHORT; hotel time") for s in t["lines"])
    assert "rest 12:00, 13:30 needed (10.E.1.a.1): SHORT" in t["pwa"]["txt"]
    t2 = TO.duty_timeout(ds, 1, 2, "roster", "332")
    r2 = t2["pwa"]["rest"]
    assert (r2["need"], r2["have"], r2["ok"], r2["cite"]) == ("13:30", "12:00", None, "10.E.1.a.1")
    assert "pwa_rest" not in t2["flags"] and not any(s.startswith("Flag: short of PWA rest") for s in t2["lines"])
    assert any(s.startswith("PWA rest before this duty (10.E.1.a.1): out of domicile, 2 x the preceding Duty Period "
                            "6:45")
               and s.endswith("release to report 12:00: ? short of it, but 9:00 or more: met if the Company limits a "
                              "regular crew's hotel rest to 9:00 (10.E.1.a.2; a regular crew is read as 2 pilots); "
                              "hotel time (door to door, 10.E.1.a.3) is shorter by the van rides.")
               for s in t2["lines"])
    assert "rest 12:00, 13:30 needed (10.E.1.a.1): ?" in t2["pwa"]["txt"]
    # under 9:00 it is short for any crew: report 8:30 after the SFO release
    ds2 = copy.deepcopy(ds)
    for x in [ds2[1]] + ds2[1]["legs"]:
        for k in ("report", "dep", "arr"):
            if k in x:
                x[k] -= timedelta(hours=3, minutes=30)
    t5 = TO.duty_timeout(ds2, 1, 2, "roster", "332")
    assert t5["pwa"]["rest"]["ok"] is False and "pwa_rest" in t5["flags"]
    assert "Flag: short of PWA rest (10.E.1.a.1): 8:30 of 13:30." in t5["lines"]
    # the duty starts 02:45 PST: no more than 7 landings (10.H.1)
    assert ("Landings (PWA 10.H.1): 1 flown segment; no more than 7 when the duty starts 2200-0459 local (it starts "
            "02:45).") in t["lines"]
    t3 = TO.duty_timeout(ds, 2, 2, "roster", "332")
    r = t3["pwa"]["rest"]
    assert (r["need"], r["have"], r["ok"], r["cite"]) == ("11:00", "10:30", False, "10.E.1.a")
    assert "Flag: short of PWA rest (10.E.1.a): 10:30 of 11:00." in t3["lines"] and t3["rest"]["ok"] is True
    assert any(s.startswith("PWA rest before this duty (10.E.1.a): in domicile, 11:00 needed; release to report 10:30: "
                            "SHORT.") for s in t3["lines"])
    # out at 19:15 HST but a 6:30 Duty Period: no 10.E.1.b
    assert any(s.endswith("not triggered (scheduled Duty Period 6:30, under 12:00).") for s in t3["lines"])
    # a longer rest meets it, and the box keeps its last out either way
    ds[2] = _duty(at(2027, 3, 11, "19:00"), _leg("HNL", "LAX", at(2027, 3, 11, "20:00"), at(2027, 3, 12, "01:15"), "3"))
    t4 = TO.duty_timeout(ds, 2, 2, "roster", "332")
    assert t4["pwa"]["rest"]["ok"] is True and "pwa_rest" not in t4["flags"]
    assert "rest 11:15, 11:00 needed (10.E.1.a): met" in t4["pwa"]["txt"]


def _late_line(arr="01:45"):
    """LAX-HNL in 20:45 HST, release 21:00; then HNL-JFK reporting 17:00 later (14:00 HST), out 15:00 HST, 3 pilots."""
    h, m = map(int, arr.split(":"))
    return [_duty(at(2027, 3, 9, "14:00"), _leg("LAX", "HNL", at(2027, 3, 9, "15:15"), at(2027, 3, 9, "20:45"), "1")),
            _duty(at(2027, 3, 10, "14:00"), _leg("HNL", "JFK", at(2027, 3, 10, "15:00"),
                                                 datetime(2027, 3, 11, h, m, tzinfo=HST), "2"))]


def test_pwa_late_departure_with_a_12_hour_duty_needs_18_hours_rest():
    """(i) 10.E.1.b: HNL-JFK departs 15:00 local (1400-0359) and the scheduled Duty Period, 14:00 to 01:45 + 0:15, is
    12:00: 18:00 rest before it. Release to report 17:00: 11:00 at home (10.E.1.a) is met, 18:00 is not: flagged."""
    t = TO.duty_timeout(_late_line(), 1, 3, "roster", "332")
    r = t["pwa"]["rest"]
    assert (r["need"], r["have"], r["ok"], r["cite"], r["late"]) == ("18:00", "17:00", False, "10.E.1.b", True)
    assert "pwa_rest" in t["flags"] and "Flag: short of PWA rest (10.E.1.b): 17:00 of 18:00." in t["lines"]
    assert any(s.startswith("PWA rest before this duty (10.E.1.a): in domicile, 11:00 needed; release to report 17:00: "
                            "met, 6:00 spare") for s in t["lines"])
    assert ("PWA 10.E.1.b (18:00 rest when a segment departs 1400-0359 local and the scheduled Duty Period is 12:00+): "
            "applies "
            "(HNL-JFK departs 15:00 HST, scheduled Duty Period 12:00); release to report 17:00: SHORT.") in t["lines"]
    assert t["pwa"]["duty"] == "12:00" and "rest 17:00, 18:00 needed (10.E.1.b): SHORT" in t["pwa"]["txt"]
    # one minute under 12:00 of Duty Period: not triggered
    t = TO.duty_timeout(_late_line("01:44"), 1, 3, "roster", "332")
    assert t["pwa"]["rest"]["late"] is False and "pwa_rest" not in t["flags"]
    assert any(s.endswith("not triggered (scheduled Duty Period 11:59, under 12:00).") for s in t["lines"])
    # the window is 1400-0359 at the station's Local Time
    late = lambda hm: TO._late(_leg("HNL", "LAX", at(2027, 3, 10, hm), at(2027, 3, 10, hm)
                                    + timedelta(hours=5)))  # noqa: E731
    assert late("14:00") and late("03:59") and late("23:30") and not late("04:00") and not late("13:59")
    assert TO._late(_leg("LAX", "HNL", at(2027, 3, 10, "12:00"), at(2027, 3, 10, "17:00")))  # 14:00 PST


def _hops(report, first_out, n, blk=40, every=60, dh_last=False):
    """n LAX-SFO / SFO-LAX hops of `blk` minutes leaving every `every` minutes from first_out (HST)."""
    legs = []
    for k in range(n):
        dep = first_out + timedelta(minutes=every * k)
        a, b = ("LAX", "SFO") if k % 2 == 0 else ("SFO", "LAX")
        legs.append(_leg(a, b, dep, dep + timedelta(minutes=blk), str(9200 + k), dh=dh_last and k == n - 1))
    return _duty(report, *legs)


def test_pwa_landings_seven_for_a_night_start_and_ten_scheduled():
    """(j) 10.H.1: 8 flown legs in a duty reporting 23:00 PST (21:00 HST) at LAX: more than 7 for a duty starting
    2200-0459 local: flagged. 11 scheduled legs (07:00 PST report): more than 10: flagged. 10, or 10 flown and a
    deadhead, are not."""
    t = TO.duty_timeout([_hops(at(2027, 3, 3, "21:00"), at(2027, 3, 3, "22:00"), 8)], 0, 2, "roster", "332")
    assert t["pwa"]["landings"] == {"n": 8, "max": 7, "ok": False} and "landings" in t["flags"]
    assert ("Flag: landings (PWA 10.H.1): 8 flown segments, over 7 (the duty starts 23:00 local, 2200-0459)."
            in t["lines"])
    t = TO.duty_timeout([_hops(at(2027, 3, 3, "21:00"), at(2027, 3, 3, "22:00"), 7)], 0, 2, "roster", "332")
    assert t["pwa"]["landings"]["ok"] is True and "landings" not in t["flags"]
    day = (at(2027, 3, 3, "05:00"), at(2027, 3, 3, "06:00"))
    t = TO.duty_timeout([_hops(*day, 11, 30, 45)], 0, 2, "roster", "332")
    assert t["pwa"]["landings"] == {"n": 11, "max": 10, "ok": False} and "landings" in t["flags"]
    assert ("Flag: landings (PWA 10.H.1): 11 flown segments, over the 10 that may be scheduled (11 if required to "
            "perform).") in t["lines"]
    assert "landings 11 (10 may be scheduled, 11 if required): OVER" in t["pwa"]["txt"]
    t = TO.duty_timeout([_hops(*day, 11, 30, 45, dh_last=True)], 0, 2, "roster", "332")
    assert t["pwa"]["landings"] == {"n": 10, "max": 10, "ok": True}
    assert ("Landings (PWA 10.H.1): 10 flown segments; no more than 10 may be scheduled (11 if required to perform)."
            in t["lines"])


def _long_day(in2):
    """2 pilots: report 06:00 HST, HNL-SFO 07:00-12:15 (5:15), SFO-LAX out 1:30 before in2 (HST)."""
    h, m = map(int, in2.split(":"))
    arr = at(2027, 3, 10, "00:00") + timedelta(hours=h, minutes=m)
    return [_duty(at(2027, 3, 10, "06:00"), _leg("HNL", "SFO", at(2027, 3, 10, "07:00"), at(2027, 3, 10, "12:15"), "1"),
                  _leg("SFO", "LAX", arr - timedelta(minutes=90), arr, "2"))]


def test_pwa_maximum_over_at_the_scheduled_times_is_not_legal_and_over_the_scheduled_limit_is_flagged():
    """(k) 2 pilots, last block-in 22:15 HST: Duty Period 06:00 to 22:30 = 16:30, over the 16:00 Maximum (10.D.1.a):
    not legal, no last out. Block-in 20:15: 14:30, within the Maximum but past the 14:00 Scheduled limit: flagged (the
    company may not schedule it), the last outs stand: the PWA's 06:00 + 16:00 - 0:15 - (20:15 - 07:00) = 08:30 HST is
    later than FAR's (Table B 0600-0659, 2 segments, 13:00: 19:00 - 13:15 = 05:45, over as scheduled; 07:45 with the
    extension), so it binds neither."""
    t = TO.duty_timeout(_long_day("22:15"), 0, 2, "roster", "332")
    assert t["legal"] is False and t["last_out"] is None and t["last_out_ext"] is None
    assert t["not_legal_short"] == "PWA duty 16:30 of 16:00" and "not legal as scheduled" in t["not_legal"]
    assert t["not_legal"].startswith("the scheduled Duty Period 16:30 (the report to 15 min after the last block-in, "
                                     "PWA 2.A.19.b) is over the PWA 10.D.1.a Maximum 16:00 (2 pilots)")
    assert any(s.startswith("Not legal: the scheduled Duty Period 16:30") for s in t["lines"])
    assert any(s.endswith("the scheduled Duty Period is over it: not legal.") for s in t["lines"])
    assert t["no_ext"]["legal"] is False and t["pwa"]["txt"].startswith(
        "scheduled duty 16:30, over the 14:00 Scheduled limit (PAST), Maximum 16:00 (10.D.1.a): over the Maximum: not "
        "legal")
    assert t["pwa"]["binds"] == []  # no last out: the PWA sets no time (review)
    # FAR 117 is over as scheduled too (Table B 0600-0659, 2 segments, 13:00; 06:00 to 22:15 is 16:15): said (review I9)
    assert ("Flag: FAR 117 is over as scheduled too: the FDP from the report to the last flown block-in (22:15 HST) is "
            "16:15, over the 13:00 limit (15:00 with the 2:00 extension, FAR 117.19(a); FAR 117.13).") in t["lines"]
    assert t["ft"]["txt"] == "6:45 of 9:00 (2:15 spare)"  # flight time is not what makes it illegal
    # SFO-LAX leaves 22:45 PST on a 16:30 duty: 10.E.1.b applies; no duty before it on file: not known
    assert t["pwa"]["rest"] == {"need": "18:00", "have": "", "ok": None, "cite": "10.E.1.b", "late": True}
    assert "rest not on file (10.E.1.b)" in t["pwa"]["txt"] and "pwa_rest" not in t["flags"]
    t = TO.duty_timeout(_long_day("20:15"), 0, 2, "roster", "332")
    assert t["legal"] is True and "pwa_sched" in t["flags"]
    assert t["pwa"]["txt"].startswith("scheduled duty 14:30, over the 14:00 Scheduled limit (PAST), Maximum 16:00 "
                                      "(10.D.1.a): last out 08:30 HST (not binding: FAR 117 is earlier)")
    assert not any(s.startswith("Flag: FAR 117 is over as scheduled too") for s in t["lines"])  # the early flag says it
    assert ("Flag: PWA duty scheduled 14:30 of 14:00 (10.D.1.a): scheduled past the PWA limit (the company may not "
            "schedule it; not a timeout).") in t["lines"]
    assert t["pwa"]["last_out_txt"] == "08:30 HST" and t["pwa"]["binds"] == []
    assert (t["last_out"]["txt"], t["last_out_ext"]["txt"], t["last_out"]["early"]) == ("05:45 HST", "07:45 HST", True)
    # 3 pilots: an IRO Crew's 18:00 (10.D.1.b.1): 18:30 is over it too
    t = TO.duty_timeout([_duty(at(2027, 3, 10, "06:00"), _leg("HNL", "SFO", at(2027, 3, 10, "07:00"),
                                                              at(2027, 3, 10, "12:15"), "1"),
                               _leg("SFO", "LAX", at(2027, 3, 11, "00:45") - timedelta(minutes=90),
                                    at(2027, 3, 11, "00:15"), "2"))], 0, 3, "roster", "332")
    assert t["legal"] is False and t["not_legal_short"] == "PWA duty 18:30 of 18:00" and t["pwa"]["binds"] == []


# ------------------------------------------------------------ review round 1 (PWA text over the spec where they differ)
def _kd(key, report, *legs):
    return {"key": key, "report": report, "legs": [dict(x, key=key) for x in legs]}


def test_pwa_mixed_flying_limits_and_rest_cover_the_whole_grouping():
    """PWA 10.D.3.a ("A pilot assigned to a grouping containing a Mixed Flying Duty Period shall be subject to the
    following limitations") and 10.E.3.a ("For pilots assigned to a grouping containing at least one Mixed Flying Duty
    Period, out of Domicile rest ... shall be determined by the following table"). By hand: day 1 KOA-HNL (0:45) and
    HNL-LAX (5:15), report 07:00 HST, in 15:15, release 15:30 (Duty Period 8:30); day 2 LAX-HNL out 07:45 HST (09:45
    PST), block 5:45, report 1:15 before = 06:30 HST (08:30 PST), 15:00 after the release. 2 pilots, acclimated to HNL:
    HNL time 06:30 is Table B 0600-0659, 13:00 (LAX time 08:30 would give 14:00: the lower is used, '?'): FDP end 19:30,
    last out 19:30 - 5:45 = 13:45 HST (15:45 PST), 15:45 HST (17:45 PST) with the extension. Day 2 is no Mixed Flying
    duty itself, but its grouping holds one: Maximum 14:00 (10.D.3, standard crew), so the duty ends by 20:30, the last
    block-in by 20:15 (0:15 debrief), the last out 20:15 - 5:45 = 14:30 HST (16:30 PST): it caps the extension (10.D.1.a
    alone gave 16:30 HST). Rest at LAX: 2 landings performed in the grouping before it (3 in all): 9:00 (10.E.3.a),
    which 15:00 meets; but until Ryan confirms that the table replaces 2 x the Duty Period (review PWA-R2-2), 2 x 8:30 =
    17:00 (10.E.1.a.1) is judged too: short of it, so the rest is a '?' (and no flag). Landings of day 2: 1 of 10
    (10.H.3 is per Mixed Flying duty)."""
    key = "H3998|2027-02-10"
    legs = [(0, "9201", "KOA", "HNL", "08:00", "08:45", "0:45"), (0, "9202", "HNL", "LAX", "10:00", "17:15", "5:15"),
            (1, "9203", "LAX", "HNL", "09:45", "13:30", "5:45")]
    t = run([(key, trip(key, "07:00", legs, CREW2))], at(2027, 2, 11, "05:00"),
            {key: {"eq": "332"}})["attributes"]["timeout"]
    lo, lx, p = t["last_out"], t["last_out_ext"], t["pwa"]
    assert t["report_txt"] == "06:30 HST" and lo["leg"] == "LAX-HNL"
    assert (lo["txt"], lo["hst"], lo["pwa"]) == ("15:45 PST", "13:45 HST", False)
    assert (lx["txt"], lx["hst"], lx["by"], lx["short"]) == ("16:30 PST", "14:30 HST", "PWA 10.D.3 max duty 14 h",
                                                             "PWA max duty 14 h")
    assert (p["cite"], p["mixed"], p["mixed_grouping"], p["scheduled"], p["maximum"], p["binds"]) == (
        "10.D.3", False, True, "12:00", "14:00", ["ext"])
    assert p["crew"].startswith("a duty of a grouping that holds a Mixed Flying Duty Period (2.A.45; 10.D.3.a covers")
    assert any(s.startswith("PWA 10.D.3.a: this grouping holds a Mixed Flying Duty Period (2.A.45)")
               for s in t["lines"])
    assert p["rest"] == {"need": "9:00", "have": "15:00", "ok": None, "cite": "10.E.3.a", "late": False,
                         "other": "17:00 (10.E.1.a.1)"}
    assert "rest 15:00, 9:00 (10.E.3.a) or 17:00 (10.E.1.a.1) needed: ?" in p["txt"]
    assert any(s.startswith("? PWA rest, the other reading (10.E.1.a.1): if 10.E.3.a's table adds to 10.E.1.a.1 rather "
                            "than replacing it (to confirm): 2 x the preceding Duty Period 8:30") for s in t["lines"])
    assert "pwa_rest" not in t["flags"] and p["landings"] == {"n": 1, "max": 10, "ok": True}
    assert any(s.startswith("PWA rest before this duty (10.E.3.a): out of domicile in a grouping that holds a Mixed "
                            "Flying Duty Period, 2 landings performed in it before this rest: 9:00")
               for s in t["lines"])
    # the other clock (LAX 08:30, Table B 14:00) is capped by the PWA too: 20:15 - 5:45 = 14:30 HST
    assert t["fdp"]["other"]["last_out_txt"] == "16:30 PST" and "clock" in t["unsure"]


def test_pwa_mixed_flying_rest_counts_the_grouping_landings():
    """10.E.3.a's table by the landings performed in the grouping: day 1 KOA-HNL-LAX (Mixed, 2), day 2 four LAX-SFO
    hops (6 by then), day 3 LAX-HNL. Before day 3: 6 landings, 10:00 needed; 9:30 from release to report: short. Before
    day 2: 2 landings performed (9:00, met by 9:30), but the whole grouping on file has 7 (10:00): a '?'."""
    k = "H3999|2027-03-10"
    d1 = _kd(k, at(2027, 3, 10, "07:00"), _leg("KOA", "HNL", at(2027, 3, 10, "08:00"), at(2027, 3, 10, "08:45"), "1"),
             _leg("HNL", "LAX", at(2027, 3, 10, "10:00"), at(2027, 3, 10, "15:15"), "2"))
    # release 15:30; day 2 reports 9:30 later (01:00 HST Mar 11), four 1:00 hops from 02:15
    hops = [_leg(*(("LAX", "SFO") if j % 2 == 0 else ("SFO", "LAX")), at(2027, 3, 11, "02:15") + timedelta(hours=2 * j),
                 at(2027, 3, 11, "03:15") + timedelta(hours=2 * j), str(3 + j)) for j in range(4)]
    d2 = _kd(k, at(2027, 3, 11, "01:00"), *hops)  # last in 09:15, release 09:30
    d3 = _kd(k, at(2027, 3, 11, "19:00"), _leg("LAX", "HNL", at(2027, 3, 11, "20:15"), at(2027, 3, 12, "01:45"), "7"))
    t3 = TO.duty_timeout([d1, d2, d3], 2, 2, "roster", "332")
    r = t3["pwa"]["rest"]
    assert (r["need"], r["have"], r["ok"], r["cite"]) == ("10:00", "9:30", False,
                                                          "10.E.3.a") and "pwa_rest" in t3["flags"]
    assert "Flag: short of PWA rest (10.E.3.a): 9:30 of 10:00." in t3["lines"]
    assert t3["pwa"]["cite"] == "10.D.3" and t3["pwa"]["mixed"] is False and t3["pwa"]["mixed_grouping"] is True
    t2 = TO.duty_timeout([d1, d2, d3], 1, 2, "roster", "332")
    r = t2["pwa"]["rest"]
    assert (r["need"], r["have"], r["ok"], r["cite"]) == ("9:00", "9:30", None,
                                                          "10.E.3.a") and "pwa_rest" not in t2["flags"]
    assert any("? met for those landings; the 7 landings of the whole grouping on file would need 10:00" in s
               for s in t2["lines"])
    assert (TO.mixed_rest(5), TO.mixed_rest(6), TO.mixed_rest(7), TO.mixed_rest(8)) == (
        timedelta(hours=9), timedelta(hours=10), timedelta(hours=10), timedelta(hours=11))
    # another grouping (another key) is not covered: day 3 alone is 10.D.1.a and 2 x its preceding Duty Period
    d3b = dict(d3, key="H3997|2027-03-11", legs=[dict(x, key="H3997|2027-03-11") for x in d3["legs"]])
    t = TO.duty_timeout([d1, d2, d3b], 2, 2, "roster", "332")
    assert t["pwa"]["cite"] == "10.D.1.a" and t["pwa"]["rest"]["cite"] == "10.E.1.a.1"


def test_an_all_interisland_duty_takes_the_interisland_duty_limits():
    """2.A.36.b: a pilot performing Interisland flying (other than a Repositioning Flight) is an Interisland Pilot, so
    10.D.2 applies. By hand, 2 pilots: report 14:00 HST, four 1:00 legs HNL-OGG-HNL-LIH-HNL from 15:00 to 20:45 in.
    FAR: Table B 1300-1659, 4 segments, 12:00: FDP end 02:00, 04:00 with the extension; the last out of the first leg
    02:00 - 5:45 = 20:15 HST, 22:15 with the extension. 10.D.2.b (starting before 2200 and continuing after 0300: 12 h),
    so the Maximum runs to the later of 0300 and 14:00 + 12:00 = 02:00: 03:00 (13 h), the last block-in 02:45, last out
    02:45 - 5:45 = 21:00 HST: it caps the extension (10.D.1.a's 16:00 gave 00:00). Scheduled 14:00 to 21:00: 7:00 of
    12:00. The pilot may exceed the Maximum at his option (10.D.4) only departing a station other than his domicile."""
    rep = at(2027, 3, 10, "14:00")
    legs = []
    for j, (a, b) in enumerate((("HNL", "OGG"), ("OGG", "HNL"), ("HNL", "LIH"), ("LIH", "HNL"))):
        dep = at(2027, 3, 10, "15:00") + timedelta(minutes=95 * j)
        legs.append(_leg(a, b, dep, dep + timedelta(minutes=60), str(j + 1)))
    t = TO.duty_timeout([_duty(rep, *legs)], 0, 2, "roster", "332")
    lo, lx, p = t["last_out"], t["last_out_ext"], t["pwa"]
    assert t["sched_in_txt"] == "20:45 HST" and lo["by"] == "FDP 12:00 (FAR 117.13, Table B)"
    assert (lo["txt"], lx["txt"], lx["by"], lx["short"]) == ("20:15 HST", "21:00 HST", "PWA 10.D.2.b max duty 13 h",
                                                             "PWA max duty 13 h")
    assert p["duty"] == "7:00" and p["binds"] == ["ext"]
    assert (p["cite"], p["scheduled"], p["maximum"], p["end_txt"], p["in_txt"]) == ("10.D.2.b", "12:00", "13:00",
                                                                                  "03:00 HST", "02:45 HST")
    assert p["crew"].startswith("Interisland duty (all its flown segments interisland: an Interisland Pilot, 2.A.36.b)")
    assert "Pilot option (10.D.4): none for a departure from HNL, your domicile." in t["lines"]
    assert any(s.startswith("This duty is all interisland flying (an Interisland Pilot's, PWA 2.A.36.b): one who "
                            "completes a Duty Period after 0200 may not start another that calendar day (10.D.2.c)")
               for s in t["not_checked"])
    assert not any("are not checked" in s for s in t["not_checked"])  # 10.E.2 and 10.H.2 are checked (round 2)
    # from OGG (the second leg working): the option is said with its time, the box keeps the limit without it
    t = TO.duty_timeout([_duty(rep, *legs)], 0, 2, "roster", "332", work=1)
    assert any(s.startswith("Pilot option (10.D.4): departing OGG, not your domicile, you may at your option stay past "
                            "the Interisland Maximum if it has not passed at block-out, so block out before 03:00 HST")
               for s in t["lines"])
    h = lambda x: timedelta(hours=x)  # noqa: E731
    D = lambda hm, end: TO.interisland_duty(at(2027, 3, 10, hm), at(2027, 3, 10, end))  # noqa: E731
    assert D("06:00", "16:00")[:3] == (h(12), h(14), "10.D.2.a")  # 0500-2159
    assert D("23:00", "23:59")[:3] == (h(10), h(12), "10.D.2.a") and D("04:30", "10:00")[:3] == (h(10), h(12),
                                                                                                 "10.D.2.a")
    assert D("13:00", "20:00")[:3] == (h(12), h(14), "10.D.2.a")  # 14 h ends exactly 0300: not after it
    assert D("16:00", "22:00")[:3] == (h(12), h(12), "10.D.2.b")  # past 0300 the next morning: 12 h
    assert TO.interisland_duty(at(2027, 3, 10, "17:00"), at(2027, 3, 11, "03:30"))[0] == h(10)  # scheduled past 0300


def test_a_long_sit_at_the_neighbor_island_is_no_repositioning_flight():
    """2.A.62 needs "minimal delay at the neighbor island station"; the PWA gives no figure, the Watcher reads 2:00. By
    hand, 2 pilots, report 07:00 HST: HNL-OGG 08:00-08:40, then OGG-LAX 3:00 later (11:40-16:40, 5:00 block). With the
    3:00 sit HNL-OGG is no Repositioning Flight: Mixed Flying (2.A.45), 14:00 (10.D.3): the last block-in 20:45, last
    out 20:45 - 8:40 = 12:05 HST, under FAR's 12:20 (Table B 0700-1159, 2 segments, 14:00: 21:00 - 8:40): it binds both,
    marked '?'. With a 1:40 sit (OGG-LAX 10:20-15:20) it repositions: 10.D.1.a."""
    t0 = at(2027, 3, 10, "08:00")
    d = _duty(at(2027, 3, 10, "07:00"), _leg("HNL", "OGG", t0, t0 + timedelta(minutes=40)),
              _leg("OGG", "LAX", at(2027, 3, 10, "11:40"), at(2027, 3, 10, "16:40")))
    t = TO.duty_timeout([d], 0, 2, "roster", "332")
    assert t["pwa"]["mixed"] is True and t["pwa"]["cite"] == "10.D.3" and t["last_out"]["txt"] == "12:05 HST"
    assert "Mixed Flying" in t["unsure"] and t["sure"] is False
    assert any(s.startswith("? Mixed Flying (2.A.45): HNL-OGG (sit 3:00) would be a Repositioning Flight (2.A.62)")
               for s in t["lines"])
    d = _duty(at(2027, 3, 10, "07:00"), _leg("HNL", "OGG", t0, t0 + timedelta(minutes=40)),
              _leg("OGG", "LAX", at(2027, 3, 10, "10:20"), at(2027, 3, 10, "15:20")))
    t = TO.duty_timeout([d], 0, 2, "roster", "332")
    assert t["pwa"]["mixed"] is False and t["pwa"]["cite"] == "10.D.1.a" and "Mixed Flying" not in t["unsure"]
    assert not TO.mixed_flying(d["legs"]) and not TO.mixed_flying(d["legs"], True)


def test_a_trailing_deadhead_moves_every_release_to_its_block_in():
    """By hand, 2 pilots: report 07:00 HST, HNL-LAX 08:00-13:00 HST (5:00), then a deadhead LAX-SFO 14:00-15:30 HST
    (2:30 after the flown block-in). The duty ends 15 min after the deadhead's block-in. FAR: Table B 0700-1159,
    1 segment, 14:00: FDP end 21:00. PWA 10.D.1.a: 07:00 + 16:00 = 23:00, less 0:15 and the 2:30 tail = 20:15 for the
    flown block-in: it binds both (last out 20:15 - 5:00 = 15:15 HST). Every release is that block-in + 2:30 + 0:15:
    23:00 with and without the extension; out on time the flight time (Table A 9:00) gives a block-in by 17:00, release
    19:45."""
    d = _duty(at(2027, 3, 10, "07:00"), _leg("HNL", "LAX", at(2027, 3, 10, "08:00"), at(2027, 3, 10, "13:00"), "1"),
              _leg("LAX", "SFO", at(2027, 3, 10, "14:00"), at(2027, 3, 10, "15:30"), "2", dh=True))
    t = TO.duty_timeout([d], 0, 2, "roster", "332")
    f = t["fdp"]
    assert t["last_out"]["txt"] == t["last_out_ext"]["txt"] == "15:15 HST" and t["pwa"]["binds"] == ["no_ext", "ext"]
    assert (f["in_txt"], f["ext_in_txt"], f["release_txt"], f["ext_release_txt"]) == ("20:15 HST", "20:15 HST",
                                                                                      "23:00 HST", "23:00 HST")
    assert (t["no_ext"]["txt"], t["no_ext"]["release_txt"]) == ("17:00 HST", "19:45 HST")
    assert t["pwa"]["end_txt"] == "23:00 HST"  # the same end as the releases
    assert ("Duty ends 15 min after the trailing deadhead's block-in (LAX-SFO, due 2:30 after the last flown one) (PWA "
            "2.A.19.b): release 23:00 HST at the FDP end without an extension, 23:00 HST with one.") in t["lines"]


def test_a_station_whose_local_time_is_not_on_file_is_a_question_for_the_pwa():
    """PWA Local Times (2.A.43): a station with no clock on file is never read as HST. 10.E.1.b: XYZ-HNL (11:00 block,
    3 pilots) departs 05:00 HST, 12:45 of Duty Period (report 1:15 before, 0:30 customs: XYZ's country is not known),
    17:00 after the last release: 18:00 may apply, so a '?' and no flag. 10.H.1: 8 hops from XYZ: 7 may apply: '?'."""
    ds = [_duty(at(2027, 3, 9, "06:00"), _leg("HNL", "XYZ", at(2027, 3, 9, "07:00"), at(2027, 3, 9, "11:00"), "1")),
          _duty(at(2027, 3, 10, "03:45"), _leg("XYZ", "HNL", at(2027, 3, 10, "05:00"), at(2027, 3, 10, "16:00"), "2"))]
    assert TO._late(ds[1]["legs"][0]) is None and TO._late(_leg("MKK", "HNL", at(2027, 3, 10, "15:00"),
                                                                at(2027, 3, 10, "15:30"))) is True
    t = TO.duty_timeout(ds, 1, 3, "roster", "332")
    r = t["pwa"]["rest"]
    assert (r["need"], r["ok"], r["late"]) == ("18:00", None, True) and "pwa_rest" not in t["flags"]
    assert any(s.startswith("PWA 10.E.1.b (18:00 rest") and "applies (?) (XYZ-HNL departs 05:00 HST; XYZ local time is "
               "not on file, so it may depart 1400-0359 there" in s for s in t["lines"])
    hops = [_leg(*(("XYZ", "QQQ") if j % 2 == 0 else ("QQQ", "XYZ")), at(2027, 3, 10, "08:00") + timedelta(hours=j),
                 at(2027, 3, 10, "08:30") + timedelta(hours=j), str(j)) for j in range(8)]
    t = TO.duty_timeout([_duty(at(2027, 3, 10, "07:00"), *hops)], 0, 2, "roster", "332")
    assert t["pwa"]["landings"] == {"n": 8, "max": 10, "ok": None} and "landings" not in t["flags"]
    assert "landings 8 (10 may be scheduled, 11 if required)?" in t["pwa"]["txt"]
    assert any(s.startswith("Landings (PWA 10.H.1): 8 flown segments;") and "XYZ's local time is not on file: ?" in s
               for s in t["lines"])


def test_pwa_local_time_windows_follow_daylight_time():
    """10.E.1.b and 10.H.1 read the station's Local Time with daylight time: 11:30 HST is 14:30 PDT in July (1400-0359:
    late) and 13:30 PST in January (not late); a 19:30 HST report at LAX is 22:30 PDT in July (a night start: 7
    landings) and 21:30 PST in January (10)."""
    late = lambda m: TO._late(_leg("LAX", "HNL", at(2027, m, 10, "11:30"), at(2027, m, 10, "16:30")))  # noqa: E731
    assert late(7) is True and late(1) is False
    jul = TO.duty_timeout([_hops(at(2027, 7, 3, "19:30"), at(2027, 7, 3, "20:30"), 8)], 0, 2, "roster", "332")
    jan = TO.duty_timeout([_hops(at(2027, 1, 3, "19:30"), at(2027, 1, 3, "20:30"), 8)], 0, 2, "roster", "332")
    assert jul["pwa"]["landings"] == {"n": 8, "max": 7, "ok": False} and "landings" in jul["flags"]
    assert "(the duty starts 22:30 local, 2200-0459)" in "\n".join(jul["lines"])
    assert jan["pwa"]["landings"] == {"n": 8, "max": 10, "ok": True} and "landings" not in jan["flags"]


def test_a_return_before_duty_timeout_never_logs_the_last_error(monkeypatch):
    """Review ERR-1: TO.ERR keeps the last duty_timeout error; a working flight whose timeout returns before
    duty_timeout runs (the working leg not found, legs not on HST) must not log it again."""
    TO.ERR["last"] = "ZeroDivisionError"
    monkeypatch.setattr(WK, "_timeout_of", lambda *a, **k: None)
    assert WK._timeout([], [], {}, {}, at(2027, 2, 19, "01:00"), None, None) is None
    assert WK.TIMEOUT_ERR["msg"] == "" and TO.ERR["last"] == ""


def test_the_payload_of_a_heavy_case_stays_far_under_the_ha_limit():
    """Review TEST-1: 4 pilots whose Captains are not known (crew list FO FO RO), the other clock (LAX in July), a
    trailing deadhead from the package, the cumulative limits on, the PWA rest lines: under 12000 bytes (HA's recorder
    keeps attributes up to 16384)."""
    key = "H3986|2027-07-10"
    legs = [(0, "9086", "HNL", "LAX", "08:10", "16:10", "5:00"), (2, "9087", "LAX", "HNL", "09:10", "11:40", "5:30")]
    pk = {"eq": "332", "duties": [
        {"legs": [["1", "", "9086", "HNL", "LAX", "08:10", "16:10", "5h00", "5:00", "", "332"]], "rept": "07:10"},
        {"legs": [["3", "", "9087", "LAX", "HNL", "09:10", "11:40", "5h30", "5:30", "", "332"],
                  ["3", "DH", "1200", "HNL", "OGG", "13:00", "13:40", "0h40", "0:20", "", "717"]], "rept": "08:00"}]}
    crew = ["FO Doe, Jane (10001)", "FO Roe, Rick (10002)", "RO Poe, Pat (10003)"]
    r = run([(key, trip(key, "07:10", legs, crew))], at(2027, 7, 12, "05:00"), {key: pk}, months_for("2027-06",
                                                                                                     "2027-07"))
    t = r["attributes"]["timeout"]
    # review PWA-deadhead: the trailing HNL-OGG deadhead may be the interisland Segment of a Mixed Flying duty (10.D.3)
    assert {"pilots", "rest class", "clock", "Mixed Flying"} <= set(t["unsure"]) and t["fdp"]["other"]
    # review round 3 (R3-2): the rest reads the grouping without the deadhead reading (Mixed Flying needs less rest out
    # of domicile), so 10.E.1.a.1 again (round 3 had 10.E.3.a): 2 x 6:15 = 12:30, met by the 39:30 release to
    # report (27:00 spare); 10.E.3.a's 9:00 for 1 landing is less, so the deadhead reading adds no '?'
    assert set(t["cum"]) == {"ft_672", "fdp_168", "fdp_672"} and t["pwa"]["rest"]["cite"] == "10.E.1.a.1"
    assert t["pwa"]["rest"]["ok"] is True and "rest_q" not in t["flags"]
    assert any(s.startswith("Duty ends 15 min after the trailing deadhead's block-in (HNL-OGG") for s in t["lines"])
    assert len(json.dumps(r)) < 12000


def test_no_text_says_pwa_section_10_is_not_on_file():
    src = open(os.path.join(HERE, "timeout.py"), encoding="utf-8").read()
    card = open(os.path.join(HERE, "www", "flight-watcher-layover-card.js"), encoding="utf-8").read()
    docs = [open(os.path.join(HERE, n), encoding="utf-8").read() for n in ("CHANGELOG.md", "README.md")]
    for blob in [src, card] + docs:
        lines = blob.splitlines()
        assert not [ln for ln in lines if "Section 10" in ln and ("not on file" in ln or "not checked" in ln)]
        assert not [ln for ln in lines if "PWA10" in ln] and chr(0x2014) not in blob
    t = acceptance()["attributes"]["timeout"]
    assert not any("Section 10" in s for s in t["not_checked"] + t["lines"])


# ---------------------------------------------------------------- review round 2: PWA rest and landings readings
def _shift(d, td):
    """A copy of duty d moved by td (its report and legs)."""
    d = copy.deepcopy(d)
    d["report"] += td
    for x in d["legs"]:
        x["dep"] += td
        x["arr"] += td
    return d


def _sit_pair(sit):
    """One grouping: HNL-LAX (report 06:00 HST Feb 10, in 12:15, release 12:30: a 6:30 Duty Period), then LAX-KOA-HNL
    reporting 10:30 after that release (23:00 HST, 01:00 PST), LAX-KOA 00:15-05:45 HST, KOA-HNL `sit` minutes later."""
    k = "H3991|2027-02-10"
    o = at(2027, 2, 11, "05:45") + timedelta(minutes=sit)
    return [_kd(k, at(2027, 2, 10, "06:00"), _leg("HNL", "LAX", at(2027, 2, 10, "07:00"), at(2027, 2, 10, "12:15"),
                                                  "1")),
            _kd(k, at(2027, 2, 10, "23:00"), _leg("LAX", "KOA", at(2027, 2, 11, "00:15"), at(2027, 2, 11, "05:45"),
                                                  "2"),
                _leg("KOA", "HNL", o, o + timedelta(minutes=40), "3"))]


def test_a_long_sit_judges_the_rest_both_ways_and_the_box_says_not_sure():
    """Review PWA-R2-1 / PWA-mixed-long-sit-rest: the long sit's Mixed Flying reading is the lower duty limit, but out
    of domicile it needs less rest (10.E.3.a's table in place of 10.E.1.a.1). By hand, 3 pilots, equipment not on file
    (Class 3, so FAR 117 sets both last outs): a 1:00 sit at KOA makes KOA-HNL a Repositioning Flight (2.A.62), no Mixed
    Flying: 2 x 6:30 = 13:00 needed, 10:30 from release to report: SHORT, flagged. A 2:30 sit: Mixed Flying (counted,
    conservative for the duty limit), 1 landing performed in the grouping before the rest: 9:00 (10.E.3.a), met by 1:30
    (a '?' anyway: under the 2:30 of van rides); the other reading needs 13:00: SHORT. The readings disagree: a '?', no
    flag, the "Rest ?" chip; the box's last outs stay sure, as the PWA limit binds neither (review
    PWA-rest-unsure-box-inconsistent; FAR: Table C Class 3, 13:00 from 23:00 HST = 12:00 HST, less the 8:40 from the LAX
    out to the last block-in: 03:20 HST; 10.D.3's 16:00 gives 06:05 HST)."""
    t = TO.duty_timeout(_sit_pair(60), 1, 3, "roster", "")
    r = t["pwa"]["rest"]
    assert (t["pwa"]["cite"], r["need"], r["have"], r["ok"], r["cite"]) == ("10.D.1.b.1", "13:00", "10:30", False,
                                                                            "10.E.1.a.1")
    assert "pwa_rest" in t["flags"] and "Mixed Flying" not in t["unsure"]
    t = TO.duty_timeout(_sit_pair(150), 1, 3, "roster", "")
    p, r = t["pwa"], t["pwa"]["rest"]
    assert (p["cite"], p["mixed"], p["binds"], t["last_out"]["hst"], t["last_out"]["pwa"]) == (
        "10.D.3", True, [], "03:20 HST", False)
    assert r == {"need": "9:00", "have": "10:30", "ok": None, "cite": "10.E.3.a", "late": False,
                 "other": "13:00 (10.E.1.a.1)"}
    assert t["flags"] == ["rest_q"] and "Mixed Flying" not in t["unsure"] and t["unsure"] == ["rest class"]
    assert "rest 10:30, 9:00 (10.E.3.a) or 13:00 (10.E.1.a.1) needed: ?" in p["txt"]
    assert any(s.startswith("PWA rest before this duty (10.E.3.a): out of domicile in a grouping that holds a Mixed "
                            "Flying Duty Period, 1 landing performed in it before this rest: 9:00") and
               "release to report 10:30: ? met by 1:30 from release to report" in s for s in t["lines"])
    assert any(s.startswith("? PWA rest, the other reading (10.E.1.a.1): if KOA-HNL is a Repositioning Flight "
                            "(2.A.62), so no Mixed Flying, or if 10.E.3.a's table adds to 10.E.1.a.1 rather than "
                            "replacing it (to confirm): out of domicile, 2 x the preceding Duty Period 6:30") and
               s.endswith("= 13:00 needed: SHORT. The readings disagree, so the rest is not sure.") for s in t["lines"])
    # the long sit line says the Mixed Flying reading is conservative only for the duty limit and the landings
    assert any(s.startswith("? Mixed Flying (2.A.45): KOA-HNL (sit 2:30)") and "counted as Mixed Flying for the duty "
               "limit and the landings (the lower limits, conservative); the rest before this duty is judged both ways"
               in s for s in t["lines"])
    # the two readings agree with a longer rest: met, no '?' (13:00 + the 2:30 of van rides = 15:30 from release to
    # report)
    ds = _sit_pair(150)
    t = TO.duty_timeout([ds[0], _shift(ds[1], timedelta(hours=5))], 1, 3, "roster", "")
    assert t["pwa"]["rest"]["ok"] is True and "Mixed Flying" not in t["unsure"] and t["flags"] == []


def test_the_mixed_flying_rest_table_is_not_sure_where_2_x_the_duty_period_needs_more():
    """Review PWA-R2-2: until Ryan confirms that 10.E.3.a's table replaces 10.E.1.a.1, a rest the table meets but 2 x
    the preceding Duty Period does not is a '?'. By hand, 3 pilots: HNL-LAX report 08:00 HST, in 14:20, release 14:35
    (6:35, 2 x = 13:10), then LAX-HNL-KOA (Mixed Flying: LAX-HNL 5:40 and HNL-KOA). 10:00 from release to report: 9:00
    met (1:00 spare), 13:10 short: '?'. 15:40 (13:10 and the 2:30 of van rides): both met. 8:30: both short, flagged."""
    k = "H3992|2027-06-10"

    def pair(rest_m):
        rep = at(2027, 6, 10, "14:35") + timedelta(minutes=rest_m)
        o = rep + timedelta(minutes=75)
        return [_kd(k, at(2027, 6, 10, "08:00"), _leg("HNL", "LAX", at(2027, 6, 10, "09:00"), at(2027, 6, 10, "14:20"),
                                                      "1")),
                _kd(k, rep, _leg("LAX", "HNL", o, o + timedelta(minutes=340), "2"),
                    _leg("HNL", "KOA", o + timedelta(minutes=400), o + timedelta(minutes=440), "3"))]
    t = TO.duty_timeout(pair(600), 1, 3, "roster", "332")
    r = t["pwa"]["rest"]
    assert t["pwa"]["mixed"] is True and (r["need"], r["ok"], r["cite"], r["other"]) == ("9:00", None, "10.E.3.a",
                                                                                        "13:10 (10.E.1.a.1)")
    assert "pwa_rest" not in t["flags"] and "Mixed Flying" not in t["unsure"]  # no long sit: only the rest is a '?'
    assert any(s.startswith("? PWA rest, the other reading (10.E.1.a.1): if 10.E.3.a's table adds to 10.E.1.a.1 rather "
                            "than replacing it (to confirm): 2 x the preceding Duty Period 6:35") for s in t["lines"])
    t = TO.duty_timeout(pair(940), 1, 3, "roster", "332")
    assert t["pwa"]["rest"]["ok"] is True and "other" not in t["pwa"]["rest"]
    assert not any(s.startswith("? PWA rest") for s in t["lines"])
    t = TO.duty_timeout(pair(510), 1, 3, "roster", "332")
    assert t["pwa"]["rest"]["ok"] is False and "Flag: short of PWA rest (10.E.3.a): 8:30 of 9:00." in t["lines"]


def test_an_interisland_duty_takes_the_interisland_rest_landings_and_10e1b():
    """Review PWA-R2-3 / PWA-10E2-interisland-rest: a duty that is all interisland flying is an Interisland Pilot's
    (2.A.36.b), so its rest is 10.E.2 and its landings 10.H.2. By hand, 2 pilots:
    - in domicile 11:30 from release to report before HNL-OGG-HNL, after LAX-HNL: 12:00 needed (10.E.2.a): SHORT,
      flagged. Review round 3 (R3-1): the pilot always holds the International category (2.A.38) and 10.E.2.a's 12:00
      applies on top of it before an interisland duty (2.A.36.b), so 10.E.1.a's 11:00 met (0:30 spare) is no other
      reading (round 3 made it a '?'); after an interisland duty: SHORT, flagged, the same;
    - at OGG 11:30 after a 6:15 interisland duty: 9:00 (10.E.2.b): met by 2:30, the van rides; review round 4, fix 1
      (R4-5): as 10.E.2.a's 12:00 is on top of 10.E.1.a at home, 10.E.1.a.1 may be on top of 10.E.2.b away (the
      pilot holds the International category, 2.A.38): 2 x 6:15 = 12:30 is not met (9:00 or more: 10.E.1.a.2 may meet
      it for 2 pilots), the readings disagree, '?' ("Rest ?" chip, no flag) until Ryan confirms it;
    - at OGG 10:30 after LAX-OGG (International flying, 7:00, 3 pilots): 9:00 met, but as an International Pilot 2 x
      7:00 = 14:00: the readings disagree, '?';
    - nine HNL-OGG shuttles reporting 18:00 HST, the last in 02:50, the duty to 03:05: more than 8 (10.H.2): OVER; the
      same reporting 17:30 and ending 02:35 (before 0300): 10 (10.H.1);
    - a 12:00 interisland duty out 14:00 HST: 10.E.1.b would need 18:00 (12:30 from release to report): '?', no flag, as
      it names an International Pilot's Segment."""
    d0 = _duty(at(2027, 3, 1, "14:00"), _leg("LAX", "HNL", at(2027, 3, 1, "15:00"), at(2027, 3, 1, "20:30"), "1"))
    d1 = _duty(at(2027, 3, 2, "08:15"), _leg("HNL", "OGG", at(2027, 3, 2, "09:15"), at(2027, 3, 2, "09:55"), "2"),
               _leg("OGG", "HNL", at(2027, 3, 2, "10:30"), at(2027, 3, 2, "11:10"), "3"))
    t = TO.duty_timeout([d0, d1], 1, 2, "roster", "332")
    r = t["pwa"]["rest"]
    # review round 3 (R3-1): SHORT again (round 3 read 10.E.1.a's 11:00 as another reading and gave a '?')
    assert (r["need"], r["have"], r["ok"], r["cite"]) == ("12:00", "11:30", False, "10.E.2.a") and "other" not in r
    assert "pwa_rest" in t["flags"] and "rest_q" not in t["flags"]
    assert "Flag: short of PWA rest (10.E.2.a): 11:30 of 12:00." in t["lines"]
    assert not any(s.startswith("? PWA rest") for s in t["lines"])
    d0 = _duty(at(2027, 3, 1, "17:00"), _leg("HNL", "OGG", at(2027, 3, 1, "18:00"), at(2027, 3, 1, "18:40"), "1"),
               _leg("OGG", "HNL", at(2027, 3, 1, "19:30"), at(2027, 3, 1, "20:30"), "0"))
    t = TO.duty_timeout([d0, d1], 1, 2, "roster", "332")
    r = t["pwa"]["rest"]
    assert (r["need"], r["have"], r["ok"], r["cite"]) == ("12:00", "11:30", False,
                                                          "10.E.2.a") and "pwa_rest" in t["flags"]
    assert "Flag: short of PWA rest (10.E.2.a): 11:30 of 12:00." in t["lines"] and "other" not in r
    a = _duty(at(2027, 3, 1, "06:00"), _leg("HNL", "OGG", at(2027, 3, 1, "07:00"), at(2027, 3, 1, "07:40"), "1"),
              _leg("OGG", "HNL", at(2027, 3, 1, "08:30"), at(2027, 3, 1, "09:10"), "2"),
              _leg("HNL", "OGG", at(2027, 3, 1, "11:20"), at(2027, 3, 1, "12:00"), "3"))
    b = _duty(at(2027, 3, 1, "23:45"), _leg("OGG", "HNL", at(2027, 3, 2, "01:00"), at(2027, 3, 2, "01:40"), "4"))
    t = TO.duty_timeout([a, b], 1, 2, "roster", "332")
    r = t["pwa"]["rest"]
    assert (r["need"], r["have"], r["ok"], r["cite"], r["other"]) == ("9:00", "11:30", None, "10.E.2.b",
                                                                      "12:30 (10.E.1.a.1)")
    assert t["flags"] == ["rest_q"] and "rest 11:30, 9:00 (10.E.2.b) or 12:30 (10.E.1.a.1) needed: ?" in t["pwa"]["txt"]
    assert ("PWA rest before this duty (10.E.2.b): out of domicile before a duty that is all interisland flying (an "
            "Interisland Pilot's, 2.A.36.b), 9:00 needed; release to report 11:30: met, 2:30 spare; hotel time (door "
            "to door, 10.E.1.a.3) is shorter by the van rides.") in t["lines"]
    assert any(s.startswith("? PWA rest, the other reading (10.E.1.a.1): as an International Pilot too (2.A.38: "
                            "10.E.1.a.1 on top of 10.E.2.b, as 10.E.2.a is on top of 10.E.1.a at home; to confirm): 2 "
                            "x the preceding Duty Period 6:15 (06:00 HST Mon Mar 1 to release 12:15 HST Mon Mar 1) = "
                            "12:30 needed: ? short of it, but 9:00 or more") for s in t["lines"])
    a = _duty(at(2027, 3, 1, "06:00"), _leg("LAX", "OGG", at(2027, 3, 1, "07:15"), at(2027, 3, 1, "12:45"), "1"))
    b = _duty(at(2027, 3, 1, "23:30"), _leg("OGG", "HNL", at(2027, 3, 2, "00:45"), at(2027, 3, 2, "01:25"), "2"))
    t = TO.duty_timeout([a, b], 1, 3, "roster", "332")
    r = t["pwa"]["rest"]
    assert (r["need"], r["ok"], r["cite"], r["other"]) == ("9:00", None, "10.E.2.b", "14:00 (10.E.1.a.1)")
    assert any(s.startswith("? PWA rest, the other reading (10.E.1.a.1): as an International Pilot, the duty before it "
                            "being International flying: 2 x the preceding Duty Period 7:00") for s in t["lines"])

    def shuttles(rep, out0):
        legs = []
        for j in range(9):
            o = out0 + timedelta(minutes=55 * j)
            legs.append(_leg(*(("HNL", "OGG") if j % 2 == 0 else ("OGG", "HNL")), o, o + timedelta(minutes=30), str(j)))
        return _duty(rep, *legs)
    t = TO.duty_timeout([shuttles(at(2027, 3, 10, "18:00"), at(2027, 3, 10, "19:00"))], 0, 2, "roster", "332")
    assert t["sched_in_txt"] == "02:50 HST" and t["pwa"]["duty"] == "9:05" and t["legal"] is True
    assert t["pwa"]["landings"] == {"n": 9, "max": 8, "ok": False} and "landings" in t["flags"]
    assert ("Flag: landings (PWA 10.H.2): 9 flown segments, over 8 (an Interisland Pilot's duty starting before 2200 "
            "HST and continuing after 0300 HST).") in t["lines"]
    assert "landings 9 (8 at most, past 0300): OVER" in t["pwa"]["txt"]
    t = TO.duty_timeout([shuttles(at(2027, 3, 10, "17:30"), at(2027, 3, 10, "18:30"))], 0, 2, "roster", "332")
    assert t["pwa"]["landings"] == {"n": 9, "max": 10, "ok": True} and "landings" not in t["flags"]
    d0 = _duty(at(2027, 3, 9, "18:00"), _leg("HNL", "OGG", at(2027, 3, 9, "19:00"), at(2027, 3, 9, "19:40"), "1"),
               _leg("OGG", "HNL", at(2027, 3, 9, "23:35"), at(2027, 3, 10, "00:15"), "2"))
    legs = [_leg(x, y, at(2027, 3, 10, hm), at(2027, 3, 10, hm) + timedelta(hours=1), str(j)) for j, (x, y, hm) in
            enumerate((("HNL", "OGG", "14:00"), ("OGG", "HNL", "17:00"), ("HNL", "LIH", "20:00"), ("LIH", "HNL",
                                                                                                   "23:45")))]
    t = TO.duty_timeout([d0, _duty(at(2027, 3, 10, "13:00"), *legs)], 1, 2, "roster", "332")
    r = t["pwa"]["rest"]
    assert t["pwa"]["duty"] == "12:00" and (r["need"], r["ok"], r["cite"], r["late"]) == ("18:00", None, "10.E.1.b",
                                                                                          True)
    assert "pwa_rest" not in t["flags"]
    assert any(s.startswith("PWA 10.E.1.b (18:00 rest") and "applies (?) (HNL-OGG departs 14:00 HST; this duty is all "
               "interisland flying, an Interisland Pilot's (2.A.36.b), and 10.E.1.b names an International Pilot's "
               "Segment" in s and s.endswith("? SHORT if it applies to an Interisland Pilot's duty.")
               for s in t["lines"])
    assert any("(10.D.2.c)" in s for s in t["not_checked"])


def test_a_rest_met_by_less_than_the_van_rides_out_of_domicile_is_not_sure():
    """Review PWA-R2-4: out of domicile the Rest Period is hotel time door to door (2.A.68.b, 10.E.1.a.3), shorter than
    release to report by the two van rides, which the schedule does not give: a rest met by under 2:30 (review
    PWA-VAN_RIDES: two rides at a far-out hotel take 1:30 to 2:30) is a '?'. By hand (_rest_line, 3 pilots, at SFO):
    13:30 needed; 14:00 from release to report (0:30 spare): '?'; 15:59 (2:29): '?'; 16:00 (2:30): met. In domicile no
    van: 11:10 against 11:00 is met."""
    ds = _rest_line()
    t = TO.duty_timeout([ds[0], _shift(ds[1], timedelta(hours=2))], 1, 3, "roster", "332")
    r = t["pwa"]["rest"]
    assert (r["need"], r["have"], r["ok"]) == ("13:30", "14:00", None) and "pwa_rest" not in t["flags"]
    assert any(s.endswith("release to report 14:00: ? met by 0:30 from release to report, but the hotel time (door to "
                          "door, 2.A.68.b, 10.E.1.a.3) is shorter by the two van rides, which are not on the schedule "
                          "(under 2:30 spare is not sure).") for s in t["lines"])
    assert t["flags"] == ["rest_q"]
    t = TO.duty_timeout([ds[0], _shift(ds[1], timedelta(hours=3, minutes=59))], 1, 3, "roster", "332")
    assert (t["pwa"]["rest"]["have"], t["pwa"]["rest"]["ok"]) == ("15:59", None)
    t = TO.duty_timeout([ds[0], _shift(ds[1], timedelta(hours=4))], 1, 3, "roster", "332")
    assert t["pwa"]["rest"]["ok"] is True and "rest 16:00, 13:30 needed (10.E.1.a.1): met" in t["pwa"]["txt"]
    t = TO.duty_timeout([ds[0], ds[1], _shift(ds[2], timedelta(minutes=40))], 2, 3, "roster", "332")
    assert (t["pwa"]["rest"]["have"], t["pwa"]["rest"]["ok"]) == ("11:10", True)
    assert TO.VAN_RIDES == timedelta(hours=2, minutes=30)


def test_a_far_not_legal_duty_says_the_pwa_maximum_is_over_too():
    """Review PWA-over-hidden-by-FAR-not-legal: 2 pilots (firm), HNL-JFK 9:30 and JFK-BOS 1:15: 10:45 of flight time
    over Table A's 9:00 (not legal to dispatch), and the Duty Period 06:00 to 22:15 + 0:15 = 16:30 over the 16:00
    Maximum (10.D.1.a): said too, and the PWA row says over the Maximum, not only "no last out"."""
    d = _duty(at(2027, 3, 2, "06:00"), _leg("HNL", "JFK", at(2027, 3, 2, "07:00"), at(2027, 3, 2, "16:30"), "1"),
              _leg("JFK", "BOS", at(2027, 3, 2, "21:00"), at(2027, 3, 2, "22:15"), "2"))
    t = TO.duty_timeout([d], 0, 2, "roster", "332", pilots_firm=True)
    assert t["legal"] is False and t["not_legal_short"] == "FT 10:45 of 9:00" and t["pwa"]["binds"] == []
    assert ("Flag: the PWA 10.D.1.a Maximum is over as scheduled too: the scheduled Duty Period 16:30 of 16:00 (2 "
            "pilots; to 15 min after the last block-in, 2.A.19.b): Crew Scheduling must change it.") in t["lines"]
    assert any(s.startswith("PWA duty limit (10.D.1.a)") and s.endswith(
        ": the scheduled Duty Period is over it too: not legal (above).") for s in t["lines"])
    assert t["pwa"]["txt"].startswith("scheduled duty 16:30, over the 14:00 Scheduled limit (PAST), Maximum 16:00 "
                                      "(10.D.1.a): over the Maximum too (not legal)")
    # within the Maximum: still "no last out (not legal)"
    t = TO.duty_timeout([dict(d, legs=d["legs"][:1])], 0, 2, "roster", "332", pilots_firm=True)
    assert t["legal"] is False and ": no last out (not legal)" in t["pwa"]["txt"]
    assert not any(s.startswith("Flag: the PWA") for s in t["lines"])


def test_the_other_rest_classes_last_outs_take_the_cumulative_caps():
    """Review FAR-class-alternatives: with 60 h FDP in 168 h binding at 16:00 HST (the 60 h test, 3 pilots on the A330),
    the Class 2 and Class 3 last outs are no later than it: 16:00 - 5:00 = 11:00 HST, as the main one (they read 18:30
    and 17:00 before). The FDP ends by class stay the table's (Class 2 23:30, Class 3 22:00)."""
    trips = _turns((2, 3, 4, 5))
    key = "H3960|2027-03-06"
    trips.append((key, trip(key, "07:00", [(0, "9070", "HNL", "LAX", "08:00", "15:00", "5:00")], CREW3)))
    t = run(trips, at(2027, 3, 6, "06:30"), {key: {"eq": "332"}}, months_for("2027-02",
                                                                             "2027-03"))["attributes"]["timeout"]
    assert t["last_out"]["txt"] == "11:00 HST" and t["last_out"]["short"] == "60 h FDP in 168 h"
    assert t["fdp"]["alt"] == {"2": "23:30 HST", "3": "22:00 HST"}
    assert any("Class 2 23:30 HST (last out 11:00 HST), Class 3 22:00 HST (last out 11:00 HST)" in s
               for s in t["lines"])


def test_the_basis_names_a_rule_that_binds_both_once_and_the_block_in_has_its_day():
    """Review UI-R1-4 and UI-R1-3: the PWA Maximum binding both last outs is named once ("for both"); the block-in
    limits carry their day (HNL-SIN in after midnight HST)."""
    t = _sin4(["CA Doe, Jane (10001)", "FO Roe, Rick (10002)", "RO Poe, Pat (10003)", "RO Moe, Max (10004)"],
              "CA01FO01RO02")
    assert any(s.startswith("Last out (block-out):") and s.endswith("with it (PWA max duty 18 h for both).")
               for s in t["lines"])
    t = _sin4(["CA Doe, Jane (10001)", "CA Roe, Rick (10002)", "FO Poe, Pat (10003)", "FO Moe, Max (10004)"],
              "CA02FO02")
    f = t["fdp"]
    assert (f["in_txt"], f["in_day"], f["ext_in_txt"], f["ext_in_day"]) == ("04:00 HST", "Wed Mar 3", "06:00 HST",
                                                                          "Wed Mar 3")
    assert t["last_out"]["day"] == "Tue Mar 2"
    assert any(s.endswith("with it (FDP 18:00; FDP + 2:00 ext).") for s in t["lines"])


def test_a_package_lookup_error_is_logged_once_and_a_missing_file_never(W, monkeypatch):
    """Review ERR-pkg-lookup-silent: an error other than OSError in the package lookup still falls back (no equipment:
    Class 3) and its type is logged once a change; a file that cannot be read stays silent."""
    key, rep, legs = BOS_TRIP
    it, rec = trip(key, rep, legs, CREW3)
    W.S["schedule"] = {"2027-02": {"items": [it], "days": months_for("2027-02")["2027-02"]["days"]}}
    W.S["own_trips"] = {key: rec}
    said = []
    monkeypatch.setattr(W, "bid_period_fn", lambda: (lambda iso: "2027-02"))
    monkeypatch.setattr(W.SMART, "load", lambda *a, **k: {})
    monkeypatch.setattr(W.log, "info", lambda msg, *a: said.append(msg % a))
    monkeypatch.setattr(W, "pkg_detail_for", lambda *a, **k: (_ for _ in ()).throw(OSError("gone")))
    assert W.publish_working_flight(now=at(2027, 2, 19, "01:00"), force=True)
    assert not [s for s in said if "package" in s]
    monkeypatch.setattr(W, "pkg_detail_for", lambda *a, **k: {}["eq"])
    for m in ("01:01", "01:02"):
        assert W.publish_working_flight(now=at(2027, 2, 19, m), force=True)
    sent = [json.loads(p) for t, p, r in W.FAKE.msgs if t == f"{W.T}/working_flight" and r][-1]
    assert sent["attributes"]["timeout"]["fdp"]["rest_class"] == 3
    assert [s for s in said if "package" in s] == [
        "working flight: pairings package not read (package detail KeyError); the duty timeout goes on without it"]
    monkeypatch.setattr(W, "pkg_detail_for", lambda period, pid, st=None: BOS_PKG)
    monkeypatch.setattr(W, "bid_period_fn", lambda: 1 / 0)
    assert W.publish_working_flight(now=at(2027, 2, 19, "01:03"), force=True)
    assert said[-1] == ("working flight: pairings package not read (bid period ZeroDivisionError); the duty timeout "
                        "goes on without it")
    # working.py alone, with a lookup that fails: kept the same way, and cleared by the next working flight
    WK.working_flight([it], {key: rec}, at(2027, 2, 19, "01:00"), 2, pkg=lambda trip_, start: [][0])
    assert WK.PKG_ERR["msg"] == "package detail IndexError"
    WK.working_flight([it], {key: rec}, at(2027, 2, 19, "01:00"), 2, pkg={key: BOS_PKG})
    assert WK.PKG_ERR["msg"] == ""


# ---------------------------------------------------------------- the card, in a real Chromium
from test_layover_card import DARK, HA_DARK, HA_LIGHT, LIGHT, _page, _states, browser  # noqa: E402,F401

ORANGE = "rgb(194, 65, 12)"  # #c2410c


def _watcher_only(tmp_path, timeout=True, tweak=None):
    """The admin's states with no Hark sensor: the Watcher's working flight (report block in the header), with the
    acceptance case's timeout (tweak(t) changes a copy)."""
    st = _states(tmp_path, hark_attrs={}, notes=False)
    a = st["sensor.flight_watcher_working_flight"]["attributes"]
    a.update({"pairing": "H3958", "flight": "HA9062", "origin": "BOS", "dest": "HNL", "leg": "2 of 2",
              "date": "2027-02-19",
              "dep_sched": "09:15 local, 04:15 HST", "arr_sched": "15:45 local, 15:45 HST",
              "report": "08:00 local, 03:00 HST",
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
    # the BOS rest is met by less than the van rides (2:25): its chip, the last outs sure (no '?')
    assert box.locator(".toq").count() == 0 and box.locator("[data-towarn]").all_inner_texts() == ["Rest ?"]
    say = box.get_attribute("aria-label")
    assert say == ("Last out 11:00 EST, 06:00 HST without an extension (FDP 14:30), 13:00 EST, 08:00 HST with one; "
                   "flight time 11:30 of 13:00 (1:30 spare); Rest ?. Details")
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
              "with the 2:00 extension (FAR 117.19(a)); before takeoff only",
              "13:00 flight time: an extension adds no flight time.",
              "Flight time: 11:30 of 13:00 (1:30 spare) · 100 h in 672 h: 14:00 spare", "How it is worked out",
              "Not checked (7)"):
        assert w in txt, w
    # how it is worked out and what is not checked fold under the summary (a phone sees the answer first)
    assert not card.locator("[data-tolines]").is_visible() and not card.locator("[data-tonc]").is_visible()
    assert card.locator("[data-tolines] li").count() == len(acceptance()["attributes"]["timeout"]["lines"])
    assert det.bounding_box()["height"] < 600
    card.locator("[data-k=tobasis] summary").click()
    assert "Table C row 0000-0559 (HNL time 03:00)" in card.locator("[data-tolines]").inner_text()
    card.locator("[data-k=tonc] summary").click()
    assert "IRO at the controls 8 h in 24 h (PWA 10.D.1.b.4)" in card.locator("[data-tonc]").inner_text()
    assert det.bounding_box()["y"] >= (card.locator(".hd").bounding_box()["y"]
                                       + card.locator(".hd").bounding_box()["height"] - 1)
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
    t["last_out_ext"].update({k: t["last_out"][k] for k in ("at", "txt", "hst", "day", "wd")},
                             short="60 h FDP in 168 h")


def _not_legal(t):
    t.update(legal=False, last_out=None, last_out_ext=None, not_legal_short="FT 13:05 of 13:00",
             not_legal="13:05 of planned flight time is over the 13:00 limit (FAR 117.11, FOM 4.3.2.2): not legal to "
                       "dispatch at any time")


def _early(t):
    t["last_out"]["early"] = True


def _old(t):
    for k in ("last_out", "last_out_ext", "legal", "sure", "ft"):
        t.pop(k)


def _ext_next_day(t):
    """Review round 5, fix 2 (UI6-3): only the last out with the extension falls on the next day (its weekday)."""
    t["last_out_ext"]["wd"] = "Sat"


@pytest.mark.parametrize("tweak,tono,rest,say", [
    (_unsure, "11:00? EST", "Ext 13:00 EST", "; not sure, the earlier reading is shown. Details"),
    (_same, "11:00 EST", "Ext same (60 h FDP in 168 h)", "the same with one (60 h FDP in 168 h)"),
    # review round 4, fix 1 (UI-R4-1): the case's "Rest ?" chip shows in a NOT LEGAL box too
    (_not_legal, "NOT LEGAL", "FT 13:05 of 13:00\nRest ?", "Not legal to dispatch: FT 13:05 of 13:00; Rest ?. Details"),
    (_early, "11:00 EST", "Over as scheduled", "; Over as scheduled, Rest ?. Details"),
    (_old, "17:15 HST", "Ext 17:15 HST",
     "Timeout 17:15 HST without an extension, 17:15 HST with one, 13:00 flight time"),
    # review round 5, fix 2 (UI6-3): the label names the extension's weekday as the box does
    (_ext_next_day, "11:00 EST", "Ext 13:00 EST Sat",
     "Last out 11:00 EST, 06:00 HST without an extension (FDP 14:30), 13:00 EST Sat, 08:00 HST with one; "),
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
    assert (card.locator(".rt").count() == 0 and card.locator(".hd.wt").count() == 0
            and card.locator(".tmw").count() == 0)
    assert card.locator("[data-van] .vt").inner_text() == "08:00"
    pg.close()


def _watcher_pwa(tmp_path, r):
    """The admin's states with no Hark sensor and the working flight r (its timeout and leg)."""
    st = _states(tmp_path, hark_attrs={}, notes=False)
    a = st["sensor.flight_watcher_working_flight"]["attributes"]
    keep = ("pairing", "flight", "origin", "dest", "leg", "date", "dep_sched", "arr_sched", "report", "status",
            "timeout")
    a.update({k: copy.deepcopy(r["attributes"][k]) for k in keep})
    return st


def test_card_box_names_the_pwa_limit_when_it_binds_at_390(browser, tmp_path):
    """(d) 2 pilots HNL-LAX: the PWA 16:00 Maximum caps the extension (18:30 HST, FAR alone 18:45): the box keeps the
    FAR last out in bold, "Ext 18:30 HST", and a binding-rule line that says PWA; the details carry the PWA row and the
    binding rule of the extension. (g) Mixed Flying binds both: "Ext same" and "PWA 14:00 duty". No sideways scroll."""
    pg = browser.new_page(viewport={"width": 390, "height": 844})
    pg.set_content(_page(_watcher_pwa(tmp_path, _pwa_d())))
    card = pg.locator("flight-watcher-layover-card")
    box = card.locator("[data-to]")
    assert box.is_visible() and box.locator("[data-tono]").inner_text() == "16:45 HST"
    assert box.locator("[data-toext]").inner_text() == "Ext 18:30 HST"
    bind = box.locator("[data-tobind]")
    assert bind.is_visible() and bind.inner_text() == "Ext: PWA max duty 16 h" and "PWA" in bind.inner_text()
    assert box.locator("[data-toby]").inner_text() == "FT 5:15 of 9:00"
    assert "; Ext: PWA max duty 16 h;" in box.get_attribute("aria-label")
    bb, rb = box.bounding_box(), card.locator("[data-van]").bounding_box()
    # right of the report, side by side
    assert bb["x"] >= rb["x"] + rb["width"] - 1 and bb["y"] < rb["y"] + rb["height"]
    cb = card.bounding_box()
    assert bb["x"] + bb["width"] <= cb["x"] + cb["width"] + 0.5
    assert pg.evaluate("document.documentElement.scrollWidth") <= 390
    box.click()
    det = card.locator("[data-todet]").inner_text()
    for w in ("With extension: block out by 18:30 HST Wed Feb 10, block in by 23:45 HST, release 00:00 HST",
              "PWA 10.D.1.a max duty 16 h; before takeoff only",
              "PWA: scheduled duty 6:30 (Scheduled limit 14:00), Maximum 16:00 (10.D.1.a): last out 18:30 HST (binds "
              "with the extension) · rest not on file · landings 1 (10 may be scheduled, 11 if required)"):
        assert w in det, w
    assert card.locator("[data-topwa]").is_visible()
    assert pg.evaluate("document.documentElement.scrollWidth") <= 390
    pg.close()
    key = "H3903|2027-02-12"
    legs = [(0, "9104", "KOA", "HNL", "08:00", "08:45", "0:45"), (0, "9105", "HNL", "LAX", "10:00", "17:15", "5:15")]
    r = run([(key, trip(key, "07:00", legs, CREW2))], at(2027, 2, 12, "06:00"), {key: {"eq": "332"}})
    pg = browser.new_page(viewport={"width": 390, "height": 844})
    pg.set_content(_page(_watcher_pwa(tmp_path, r)))
    box = pg.locator("flight-watcher-layover-card [data-to]")
    assert (box.locator("[data-tono]").inner_text() == "13:30 HST"
            and box.locator("[data-toext]").inner_text() == "Ext same")
    assert box.locator("[data-tobind]").inner_text() == "PWA max duty 14 h"
    assert "Landings" not in box.inner_text() and box.locator("[data-towarn]").count() == 0
    assert pg.evaluate("document.documentElement.scrollWidth") <= 390
    pg.close()


def test_card_box_says_not_legal_over_the_pwa_maximum_and_flags_a_short_pwa_rest(browser, tmp_path):
    def over(t):
        t.update(legal=False, last_out=None, last_out_ext=None, not_legal_short="PWA duty 16:30 of 16:00",
                 not_legal="the scheduled Duty Period 16:30 is over the PWA 10.D.1.a Maximum 16:00 (2 pilots): not "
                           "legal as scheduled")
    pg = browser.new_page(viewport={"width": 390, "height": 844})
    pg.set_content(_page(_watcher_only(tmp_path, tweak=over)))
    box = pg.locator("flight-watcher-layover-card [data-to]")
    assert box.locator("[data-tono]").inner_text() == "NOT LEGAL" and "PWA duty 16:30 of 16:00" in box.inner_text()
    pg.close()

    def short(t):
        t["flags"] = ["pwa_rest"]
    pg = browser.new_page(viewport={"width": 390, "height": 844})
    pg.set_content(_page(_watcher_only(tmp_path, tweak=short)))
    box = pg.locator("flight-watcher-layover-card [data-to]")
    assert box.locator("[data-towarn]").inner_text() == "PWA rest short"
    assert box.locator("[data-tobind]").count() == 0  # the PWA binds neither result here
    assert pg.evaluate("document.documentElement.scrollWidth") <= 390
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
    assert (bb["y"] < lb["y"] + lb["height"] and lb["y"] < bb["y"] + bb["height"]
            and bb["x"] >= lb["x"] + lb["width"] - 1)
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


# ---------------------------------------------------------------- review round 1: the card
def _graft(t):
    """The (d) working flight with another timeout t (a case worked out by duty_timeout)."""
    r = copy.deepcopy(_pwa_d())
    r["attributes"]["timeout"] = copy.deepcopy(t)
    return r


@pytest.mark.parametrize("theme", ["ha-light", "ha-dark"])
def test_card_not_legal_is_white_on_red_says_why_and_keeps_its_question_mark(browser, tmp_path, theme):
    """Review CARD-1, I2, I4, I10: NOT LEGAL is the most serious state: white on red (#b71c1c, AA on both themes), its
    '?' kept when not sure (the Captains of a 4-pilot crew decide it), "Not legal as scheduled (PWA)" for a PWA Maximum
    (a contract limit) and "Not legal to dispatch" for FAR 117; the button's class is its own (to-nl)."""
    t = TO.duty_timeout(_long_day("22:15"), 0, 2, "roster", "332")
    t.update(sure=False, unsure=["PWA crew"])
    pg = browser.new_page(viewport={"width": 390, "height": 844})
    pg.set_content(_page(_watcher_pwa(tmp_path, _graft(t)), theme={"ha-light": HA_LIGHT, "ha-dark": HA_DARK}[theme]))
    card = pg.locator("flight-watcher-layover-card")
    box = card.locator("[data-to]")
    assert box.locator("[data-tono]").inner_text() == "NOT LEGAL?" and box.locator(".toq").count() == 1
    assert box.get_attribute("aria-label") == ("Not legal as scheduled (PWA): PWA duty 16:30 of 16:00; not sure, see "
                                               "the details. Details")
    cls = box.get_attribute("class").split()
    assert "to-nl" in cls and "nl" not in cls
    st = pg.evaluate("""() => { const c = getComputedStyle(window.root().querySelector('[data-to] .tonl'));
        return [c.color, c.backgroundColor]; }""")
    assert st == ["rgb(255, 255, 255)", "rgb(183, 28, 28)"]
    box.click()
    det = card.locator("[data-todet]")
    assert det.locator(".tnlb").inner_text() == "Not legal as scheduled (PWA):"
    assert pg.evaluate("getComputedStyle(window.root().querySelector('.tnlb')).backgroundColor") == "rgb(183, 28, 28)"
    assert "? Not sure: the Captains of the crew (PWA 10.D.1.c or 10.D.1.d)" in det.inner_text()
    card.locator("[data-k=tobasis] summary").click()
    assert "Flag: FAR 117 is over as scheduled too" in card.locator("[data-tolines]").inner_text()
    con = pg.evaluate("window.fwContrast(window.root().host)")
    assert not con["fails"], json.dumps(con["fails"], indent=1)
    pg.close()
    # FAR 117 (flight time over): not legal to dispatch
    pg = browser.new_page(viewport={"width": 390, "height": 844})
    pg.set_content(_page(_watcher_only(tmp_path, tweak=_not_legal)))
    box = pg.locator("flight-watcher-layover-card [data-to]")
    assert box.get_attribute("aria-label").startswith("Not legal to dispatch: FT 13:05 of 13:00")
    box.click()
    assert pg.locator("flight-watcher-layover-card .tnlb").inner_text() == "Not legal to dispatch:"
    pg.close()


def test_card_not_legal_box_shows_its_flag_chips_and_names_them(browser, tmp_path):
    """Review round 4, fix 1 (UI-R4-1): a NOT LEGAL box keeps the flag chips (Crew Scheduling re-timing the duty to fit
    the Maximum leaves a rest short): a duty over the PWA Maximum and short of rest shows "Rest short" and "PWA rest
    short" under the reason, its label names both, and at 320 px it stays beside the Report block. By hand: LAX-HNL
    report 08:00 HST Mar 9, out 09:00, in 21:00, release 21:15 (domestic, 2.A.19.b); _long_day("22:15") reporting
    06:00 HST Mar 10: a 16:30 Duty Period, over 16:00 (10.D.1.a): NOT LEGAL; 8:45 free, short of FAR 117.25(e)'s 10 h
    ("rest") and of 10.E.1.a's 11:00 in domicile ("pwa_rest")."""
    d0 = _duty(at(2027, 3, 9, "08:00"), _leg("LAX", "HNL", at(2027, 3, 9, "09:00"), at(2027, 3, 9, "21:00"), "0"))
    t = TO.duty_timeout([d0] + _long_day("22:15"), 1, 2, "roster", "332")
    assert t["legal"] is False and t["flags"] == ["rest", "pwa_rest"] and t["rest"]["free"] == "8:45"
    for width in (390, 320):
        pg = browser.new_page(viewport={"width": width, "height": 844})
        pg.set_content(_page(_watcher_pwa(tmp_path, _graft(t))))
        card = pg.locator("flight-watcher-layover-card")
        box, rep = card.locator("[data-to]"), card.locator("[data-van]")
        assert box.locator("[data-tono]").inner_text() == "NOT LEGAL"
        assert box.locator("[data-towarn]").all_inner_texts() == ["Rest short", "PWA rest short"]
        assert box.get_attribute("aria-label") == ("Not legal as scheduled (PWA): PWA duty 16:30 of 16:00; Rest short, "
                                                   "PWA rest short. Details")
        bb, rb = box.bounding_box(), rep.bounding_box()
        assert bb["x"] >= rb["x"] + rb["width"] - 1 and bb["y"] < rb["y"] + rb["height"], (width, bb, rb)
        assert pg.evaluate("document.documentElement.scrollWidth") <= width
        pg.close()
    t["flags"] = ["rest", "pwa_rest", "landings"]
    pg = browser.new_page(viewport={"width": 390, "height": 844})
    pg.set_content(_page(_watcher_pwa(tmp_path, _graft(t))))
    box = pg.locator("flight-watcher-layover-card [data-to]")
    assert box.locator("[data-towarn]").all_inner_texts() == ["Rest short", "+2 more flags"]
    assert "; Rest short, PWA rest short, Landings over. Details" in box.get_attribute("aria-label")
    pg.close()


def _sin_r():
    trips, pkg = _sin_line()
    return run(trips, at(2027, 3, 4, "17:00"), pkg)


@pytest.mark.parametrize("case", ["sin", "not_legal", "four_pilots"])
def test_card_box_stays_beside_the_report_block_at_320(browser, tmp_path, case):
    """Review I1, I7: at 320 px the box sits right of the Report block, not under it: the time keeps 24 px with its '?'
    right after it and its clock smaller after it (a zone with no letters named by its station: "16:05? SIN"), the
    binding rule wraps, the Report block is a little smaller under 360 px. The SIN case (4 pilots, not sure), a NOT
    LEGAL one and a 4-pilot FAR one (CA02FO02 HNL-SIN)."""
    r = {"sin": _sin_r, "not_legal": lambda: _graft(TO.duty_timeout(_long_day("22:15"), 0, 2, "roster", "332")),
         "four_pilots": lambda: _graft(_sin4(["CA Doe, Jane (10001)", "CA Roe, Rick (10002)", "FO Poe, Pat (10003)",
                                              "FO Moe, Max (10004)"], "CA02FO02"))}[case]()
    pg = browser.new_page(viewport={"width": 320, "height": 700})
    pg.set_content(_page(_watcher_pwa(tmp_path, r)))
    card = pg.locator("flight-watcher-layover-card")
    box, rep = card.locator("[data-to]"), card.locator("[data-van]")
    if case == "sin":
        assert box.locator("[data-tono]").inner_text() == "16:05? SIN" and "UTC" not in box.inner_text()
    bb, rb, cb = box.bounding_box(), rep.bounding_box(), card.bounding_box()
    assert bb["x"] >= rb["x"] + rb["width"] - 1, (case, bb, rb)  # right of the Report block
    assert bb["y"] < rb["y"] + rb["height"] and rb["y"] < bb["y"] + bb["height"], (case, bb, rb)  # side by side
    assert bb["x"] + bb["width"] <= cb["x"] + cb["width"] + 0.5
    size = pg.evaluate("parseFloat(getComputedStyle(window.root().querySelector('[data-tono]')).fontSize)")
    assert size >= 20 and pg.evaluate("document.documentElement.scrollWidth") <= 320
    pg.close()


def test_card_box_shows_two_flag_chips_and_names_every_flag(browser, tmp_path):
    """Review I5: more than one flag: the box shows two chips (a third and more as "+N more flags") and the label names
    every one; the PWA row marks a duty past the Scheduled limit (PAST)."""
    def three(t):
        t["last_out"]["early"] = True
        t["flags"] = ["early", "pwa_rest", "landings"]

    def two(t):
        t["flags"] = ["pwa_rest", "pwa_sched"]
    pg = browser.new_page(viewport={"width": 390, "height": 844})
    pg.set_content(_page(_watcher_only(tmp_path, tweak=three)))
    box = pg.locator("flight-watcher-layover-card [data-to]")
    assert box.locator("[data-towarn]").all_inner_texts() == ["Over as scheduled", "+2 more flags"]
    assert "; Over as scheduled, PWA rest short, Landings over. Details" in box.get_attribute("aria-label")
    pg.close()
    pg = browser.new_page(viewport={"width": 390, "height": 844})
    pg.set_content(_page(_watcher_only(tmp_path, tweak=two)))
    box = pg.locator("flight-watcher-layover-card [data-to]")
    assert box.locator("[data-towarn]").all_inner_texts() == ["PWA rest short", "Past PWA schedule"]
    assert pg.evaluate("document.documentElement.scrollWidth") <= 390
    pg.close()
    r = _graft(TO.duty_timeout(_long_day("20:15"), 0, 2, "roster", "332"))
    pg = browser.new_page(viewport={"width": 390, "height": 844})
    pg.set_content(_page(_watcher_pwa(tmp_path, r)))
    box = pg.locator("flight-watcher-layover-card [data-to]")
    assert box.locator("[data-towarn]").all_inner_texts() == ["Over as scheduled", "Past PWA schedule"]
    box.click()
    assert ("scheduled duty 14:30, over the 14:00 Scheduled limit (PAST)"
            in pg.locator("flight-watcher-layover-card [data-topwa]").inner_text())
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
        const lum = (c) => { const f = (v) => { v /= 255;
            return v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
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


# ---------------------------------------------------------------- review round 2: the card
def test_card_without_the_attribute_keeps_the_report_size_at_320(browser, tmp_path):
    """Review CARD-360-media-unscoped: the phone rule that makes room for the box applies only to a header that holds
    it: with no timeout attribute the Report time keeps 36 px at 320."""
    pg = browser.new_page(viewport={"width": 320, "height": 700})
    pg.set_content(_page(_watcher_only(tmp_path, timeout=False)))
    assert pg.evaluate("parseFloat(getComputedStyle(window.root().querySelector('[data-van] .vt')).fontSize)") == 36
    assert pg.evaluate("document.documentElement.scrollWidth") <= 320
    pg.close()
    pg = browser.new_page(viewport={"width": 320, "height": 700})
    pg.set_content(_page(_watcher_only(tmp_path)))
    assert pg.evaluate("parseFloat(getComputedStyle(window.root().querySelector('[data-van] .vt')).fontSize)") == 30
    pg.close()


def _one_line(pg, sel):
    """True when the element's text sits on one line (its height under 1.5 of its line height)."""
    return pg.evaluate("""(sel) => { const el = window.root().querySelector(sel), s = getComputedStyle(el);
        const lh = parseFloat(s.lineHeight) || parseFloat(s.fontSize) * 1.15;
        return el.getBoundingClientRect().height < lh * 1.5; }""", sel)


@pytest.mark.parametrize("width", [320, 390])
def test_card_box_keeps_a_number_with_its_unit_and_names_the_rule_of_each_last_out(browser, tmp_path, width):
    """Review UI-R1-1 and UI-R1-2: the binding-rule lines keep "16 h" and "16:30 of 16:00" whole and fit on one line
    (no "h" alone under it), and when the PWA binds only the extension the no-extension rule ("FDP 14:00", FAR 117) is
    named above it, so neither reads as the reason for both; the label names it too. The box stays beside the Report
    block at 320."""
    pg = browser.new_page(viewport={"width": width, "height": 844})
    pg.set_content(_page(_watcher_pwa(tmp_path, _pwa_d())))
    card = pg.locator("flight-watcher-layover-card")
    box = card.locator("[data-to]")
    assert box.locator("[data-torule]").inner_text() == "FDP 14:00"
    assert box.locator("[data-tobind]").inner_text() == "Ext: PWA max duty 16 h"
    assert box.locator("[data-tobind] .nw").inner_text() == "16 h"
    assert _one_line(pg, "[data-tobind]") and _one_line(pg, "[data-torule]") and _one_line(pg, "[data-toby]")
    assert ("without an extension (FDP 14:00), 18:30 HST with one; Ext: PWA max duty 16 h;"
            in box.get_attribute("aria-label"))
    bb, rb = box.bounding_box(), card.locator("[data-van]").bounding_box()
    assert bb["x"] >= rb["x"] + rb["width"] - 1 and bb["y"] < rb["y"] + rb["height"]
    assert pg.evaluate("document.documentElement.scrollWidth") <= width
    pg.close()
    pg = browser.new_page(viewport={"width": width, "height": 844})
    pg.set_content(_page(_watcher_pwa(tmp_path, _graft(TO.duty_timeout(_long_day("22:15"), 0, 2, "roster", "332")))))
    box = pg.locator("flight-watcher-layover-card [data-to]")
    assert box.locator("[data-toby]").inner_text() == "PWA duty 16:30 of 16:00" and _one_line(pg, "[data-toby]")
    assert box.locator("[data-torule]").count() == 0
    assert pg.evaluate("document.documentElement.scrollWidth") <= width
    pg.close()
    pg = browser.new_page(viewport={"width": width, "height": 844})
    pg.set_content(_page(_watcher_only(tmp_path)))  # FAR 117 sets both: no rule line, the label names it
    box = pg.locator("flight-watcher-layover-card [data-to]")
    assert box.locator("[data-torule]").count() == 0 and box.locator("[data-tobind]").count() == 0
    assert "without an extension (FDP 14:30)," in box.get_attribute("aria-label")
    pg.close()


def test_card_details_give_the_block_in_day_and_why_the_on_time_block_ins_are_one(browser, tmp_path):
    """Review UI-R1-3, UI-R1-4, CARD-ontime-flight-time-wording: a block-in after midnight carries its day; the two
    on-time block-ins being one is said by the rule that makes them one: flight time ("an extension adds no flight
    time"), the PWA Maximum ("the PWA Maximum caps it"), or another limit ("the same limit binds both"). A long sit's
    Mixed Flying doubt is named with what it decides."""
    def det(r, tweak=None):
        r = copy.deepcopy(r)
        if tweak:
            tweak(r["attributes"]["timeout"])
        pg = browser.new_page(viewport={"width": 390, "height": 844})
        pg.set_content(_page(_watcher_pwa(tmp_path, r)))
        pg.locator("flight-watcher-layover-card [data-to]").click()
        txt = pg.locator("flight-watcher-layover-card [data-todet]").inner_text()
        pg.close()
        return txt
    two_ca = _graft(_sin4(["CA Doe, Jane (10001)", "CA Roe, Rick (10002)", "FO Poe, Pat (10003)",
                           "FO Moe, Max (10004)"],
                          "CA02FO02"))
    txt = det(two_ca)
    assert "No extension: block out by 14:55 HST Tue Mar 2, block in by 04:00 HST Wed Mar 3, release 04:30 HST" in txt
    assert "With extension: block out by 16:55 HST Tue Mar 2, block in by 06:00 HST Wed Mar 3, release 06:30 HST" in txt
    assert "17:00 flight time: an extension adds no flight time." in txt
    one_ca = _graft(_sin4(["CA Doe, Jane (10001)", "FO Roe, Rick (10002)", "RO Poe, Pat (10003)",
                           "RO Moe, Max (10004)"],
                          "CA01FO01RO02"))
    txt = det(one_ca)
    assert "PWA max duty 18 h: the PWA Maximum caps it, an extension adds nothing." in txt
    assert "an extension adds no flight time" not in txt

    def cap(t):
        t["no_ext"].update(short="60 h FDP in 168 h")
        t["ext"].update(at=t["no_ext"]["at"], short="60 h FDP in 168 h")
    txt = det(_graft(acceptance()["attributes"]["timeout"]), cap)
    assert "60 h FDP in 168 h: the same limit binds both, an extension adds nothing." in txt
    txt = det(_graft(TO.duty_timeout(_sit_pair(150), 1, 3, "roster", "")))
    assert ("? Not sure: the rest facility class: the earlier reading is shown" in txt
            and "Repositioning" not in txt.split("How it is worked out")[0])
    assert "rest 10:30, 9:00 (10.E.3.a) or 13:00 (10.E.1.a.1) needed: ?" in txt


# ---------------------------------------------------------------- review round 3 (the open items after round 2)
def _sin_trip(back="04-08"):
    """HNL-SIN (report 08:00 HST Apr 1, out 09:00, in 19:30, customs: release 20:00), SIN-HNL (report 06:00 HST on
    `back`, out 07:00, in 16:30, release 17:00)."""
    m, d = map(int, back.split("-"))
    return [_duty(at(2027, 4, 1, "08:00"), _leg("HNL", "SIN", at(2027, 4, 1, "09:00"), at(2027, 4, 1, "19:30"), "1")),
            _duty(at(2027, m, d, "06:00"), _leg("SIN", "HNL", at(2027, m, d, "07:00"), at(2027, m, d, "16:30"), "2"))]


def _lax(rep):
    o = rep + timedelta(hours=1)
    return _duty(rep, _leg("HNL", "LAX", o, o + timedelta(minutes=315), "3"))


def test_far_117_25d_56_hours_on_return_home_after_a_long_trip_past_60_degrees():
    """Review FAR-117.25d-theater-change-rest (FOM 4.3.2.11): away from HNL more than 168 h and more than 60 deg of
    longitude (SIN: |104.0 - (-157.9)| = 261.9, 98.1 deg the short way), then 56 consecutive hours of rest at home. By
    hand: away from the HNL report 08:00 HST Thu Apr 1 to the release 17:00 HST Thu Apr 8 = 177:00. The next report
    08:00 HST Sat Apr 10: 39:00 free, SHORT of 56:00 (the 10 h of 117.25(e) and the PWA 11:00 are met); 01:00 HST Sun
    Apr 11: 56:00, but only the 0100-0700 HNL nights of Apr 9 and 10 are inside it, so review round 4, fix 1 (R4-4: the
    rest "must encompass three physiological nights' rest", FAR 117.3 reading one as 10 h holding 0100-0700 at home
    base, not in the FOM) makes it a '?' ("Rest ?" chip), not short, until Ryan confirms it; 07:00 HST Apr 11: 62:00
    holding the nights of Apr 9, 10 and 11: met; 06:59: 61:59, two nights: '?'. Back Apr 7 (153:00 away): not
    triggered, no line. A line that starts with the SIN-HNL duty (the trip's start not on file, 11:00 away at least):
    '?' when short."""
    ds = _sin_trip() + [_lax(at(2027, 4, 10, "08:00"))]
    t = TO.duty_timeout(ds, 2, 2, "roster", "332")
    assert t["rest"]["ok"] is False and t["rest"]["need"] == "56:00" and "rest" in t["flags"]
    # review round 4, fix 2 (UI-R4V-1): the card's FAR rest row names the rule that decides
    assert (t["rest"]["cite"], t["rest"]["txt"]) == ("FAR 117.25(d)", "39:00 free, 56:00 needed (FAR 117.25(d)): SHORT")
    assert ("Rest on return to home base (FAR 117.25(d), FOM 4.3.2.11): 177:00 away from HNL (08:00 HST Thu Apr 1 to "
            "release 17:00 HST Thu Apr 8, more than 168 h) and SIN is 98 deg from HNL (more than 60): 56 consecutive "
            "hours, holding three physiological nights; 39:00 free: SHORT, check with Crew Scheduling.") in t["lines"]
    assert "Flag: short of FAR rest (FAR 117.25(d)): 39:00 of 56:00." in t["lines"]
    assert not any("physiological nights" in s for s in t["not_checked"])  # counted now (review round 4, fix 1)
    assert any(s.startswith("Rest before this FDP (FAR 117.25(e), FOM 4.3.2.7): 39:00") and s.endswith("met.")
               for s in t["lines"])
    t = TO.duty_timeout(_sin_trip() + [_lax(at(2027, 4, 11, "01:00"))], 2, 2, "roster", "332")
    assert (t["rest"]["ok"], t["rest"]["need"]) == (None, "56:00") and t["flags"] == ["rest_q"]
    assert any("FAR 117.25(d)" in s
               and s.endswith("; 56:00 free: ? 2 of the three physiological nights (0100-0700 HNL) "
                                                   "are inside it (FAR 117.3 reads one as 10 h of rest holding "
                                                   "0100-0700 at home base; not in the FOM, Ryan to confirm).")
               for s in t["lines"])
    t = TO.duty_timeout(_sin_trip() + [_lax(at(2027, 4, 11, "07:00"))], 2, 2, "roster", "332")
    assert (t["rest"]["ok"], t["rest"]["need"]) == (True, "56:00") and t["flags"] == []
    assert any("FAR 117.25(d)" in s and s.endswith("; 62:00 free: met (3 physiological nights, 0100-0700 HNL).")
               for s in t["lines"])
    t = TO.duty_timeout(_sin_trip() + [_lax(at(2027, 4, 11, "06:59"))], 2, 2, "roster", "332")
    assert t["rest"]["ok"] is None and t["flags"] == ["rest_q"]
    t = TO.duty_timeout(_sin_trip("04-07") + [_lax(at(2027, 4, 9, "08:00"))], 2, 2, "roster", "332")
    assert t["rest"] == {"free": "39:00", "ok": True, "cite": "FAR 117.25(e)",
                         "txt": "39:00 free, 10:00 needed (FAR 117.25(e)): met"}
    assert not any("117.25(d)" in s for s in t["lines"])
    t = TO.duty_timeout(_sin_trip()[1:] + [_lax(at(2027, 4, 10, "08:00"))], 1, 2, "roster", "332")
    assert t["rest"]["ok"] is None and "need" not in t["rest"] and "rest" not in t["flags"] and "rest_q" in t["flags"]
    assert any(s.startswith("Rest on return to home base (FAR 117.25(d), FOM 4.3.2.11): 11:00 away from HNL") and
               "at least: it may be more than 168 h" in s
               and "(? the trip's start is not on file (away at least 11:00))"
               in s and s.endswith("39:00 free: ? SHORT of 56:00 if it applies.") for s in t["lines"])


def test_far_117_25g_rest_after_deadhead_transportation_past_table_b():
    """Review FAR-117.25d / FOM 4.3.2.10 (14 CFR 117.25(g)): deadhead transportation that runs past the Table B FDP
    needs a rest as long as the deadhead, no less than 10 h. By hand: a SIN-HNL deadhead only, report 06:00 HST Apr 8,
    out 07:00, in 21:00 (14:00), release 21:30 (customs). 34:00 free at SIN since the HNL-SIN release (20:00 HST Apr 6),
    under 36 h: not acclimated, so Table B on HNL time less 0:30 (review round 3, R3-4: FAR 117.13(b); round 3 took the
    lower of HNL's 13:00 and SIN's 9:00 with no reduction): 1 segment, row 0600-0659, 13:00 - 0:30 = 12:30; report to
    block-in 15:00 is over it: 15:00 needed. HNL-LAX reporting 10:30 HST Apr 9 (13:00 free): SHORT; 12:30 (15:00):
    met. Flown SFO-HNL (07:00-12:30) then a HNL-SIN deadhead (out 14:00, in 01:00): over Table B (19:00 from the report
    06:00 to 01:00 HST; acclimated to HNL, 13:00 for 2 segments on HNL time, 14:00 on SFO's 09:00 PDT: the lower), but
    whether deadheads after the FDP count is not sure. Its length runs from the last flown block-in (review round 3,
    R3-5: the 1:30 sit counts, conservative): 12:30 to 01:00 = 12:30 (round 3: 11:00 from the deadhead's out); 10:30
    free of 12:30 is a '?'."""
    out = _duty(at(2027, 4, 6, "08:00"), _leg("HNL", "SIN", at(2027, 4, 6, "09:00"), at(2027, 4, 6, "19:30"), "0"))
    dh = _duty(at(2027, 4, 8, "06:00"), _leg("SIN", "HNL", at(2027, 4, 8, "07:00"), at(2027, 4, 8, "21:00"), "1",
                                             dh=True))
    t = TO.duty_timeout([out, dh, _lax(at(2027, 4, 9, "10:30"))], 2, 2, "roster", "332")
    assert (t["rest"]["ok"], t["rest"]["need"], t["rest"]["free"]) == (False, "15:00", "13:00") and "rest" in t["flags"]
    # review round 3 (R3-4): its Table B FDP is 12:30 (HNL time less 0:30, not acclimated), not SIN's 9:00
    assert ("Rest after deadhead transportation (FAR 117.25(g), FOM 4.3.2.10): the duty before it was deadhead "
            "transportation only, 15:00 from its report to its last block-in, over its Table B FDP 12:30 (HNL time, "
            "less 0:30: not acclimated, FAR 117.13(b)): a rest as long as the deadhead transportation (15:00, from the "
            "report), no less than 10 h; 13:00 free: SHORT, check with Crew Scheduling.") in t["lines"]
    assert "Flag: short of FAR rest (FAR 117.25(g)): 13:00 of 15:00." in t["lines"]
    t = TO.duty_timeout([out, dh, _lax(at(2027, 4, 9, "12:30"))], 2, 2, "roster", "332")
    assert (t["rest"]["ok"], t["rest"]["need"]) == (True, "15:00") and "rest" not in t["flags"]
    assert not any("117.25(d)" in s for s in t["lines"])  # 61:30 away: no 56 h rest
    tr = _duty(at(2027, 4, 8, "06:00"), _leg("SFO", "HNL", at(2027, 4, 8, "07:00"), at(2027, 4, 8, "12:30"), "1"),
               _leg("HNL", "SIN", at(2027, 4, 8, "14:00"), at(2027, 4, 9, "01:00"), "2", dh=True))
    o = at(2027, 4, 9, "13:00")
    nxt = _duty(at(2027, 4, 9, "12:00"), _leg("SIN", "NRT", o, o + timedelta(hours=7), "3"))
    t = TO.duty_timeout([tr, nxt], 1, 3, "roster", "332")
    assert (t["rest"]["ok"], t["rest"]["free"]) == (None, "10:30") and "need" not in t["rest"]  # may apply: its line
    # review round 3 (R3-5): 12:30 from the last flown block-in (round 3: 11:00 from the deadhead's out)
    assert ("Rest after deadhead transportation (FAR 117.25(g), FOM 4.3.2.10): the duty before it ended with deadhead "
            "transportation after its last flown leg, 19:00 from its report to its last block-in, over its Table B FDP "
            "13:00 (HNL time): a rest as long as the deadhead transportation (12:30, from the last flown block-in: the "
            "sit before the deadhead counts, conservative), no less than 10 h (? whether deadheads after the FDP count "
            "is not sure); 10:30 free: ? SHORT of 12:30 if it applies.") in t["lines"]


def test_molokai_and_lanai_are_hawaii_stations():
    """Review PWA-MKK-LNY-customs-longitude: MKK and LNY are interisland (HAWAII), so no customs, a longitude and
    HST."""
    for s in ("MKK", "LNY"):
        assert s in TO.US_STATIONS and s in TO.LON and WK.ZONES[s] == "Pacific/Honolulu"
        assert TO.customs({"frm": "HNL", "to": s}) is False and TO.same_theater(s, "HNL") is True


def test_an_interisland_deadhead_is_judged_as_a_mixed_flying_segment_too():
    """Review PWA-deadhead-not-counted-for-mixed-flying: 2.A.62 positions "such aircraft, or operating crew" and 2.A.45
    counts Segments, so a deadhead may be the interisland Segment. By hand, 2 pilots: DH LIH-HNL 07:00-07:35, HNL-LAX
    09:00-14:15 (5:15), report 06:00 HST. Table B, 2 segments, row 0600-0659: 13:00, FDP end 19:00, 21:00 with the
    extension; the out to the last block-in 5:15: FAR last outs 13:45 and 15:45 HST. Mixed Flying (the deadhead read as
    its interisland Segment, conservative): 10.D.3 standard crew 14:00, duty end 20:00, last block-in 19:45, last out
    14:30 HST: it caps the extension (10.D.1.a's 16:00 would give 16:30). Not sure: Mixed Flying. A DH HNL-KOA before
    KOA-LAX is the single Repositioning Flight either way (2.A.62)."""
    dh = [_leg("LIH", "HNL", at(2027, 4, 5, "07:00"), at(2027, 4, 5, "07:35"), "1", dh=True),
          _leg("HNL", "LAX", at(2027, 4, 5, "09:00"), at(2027, 4, 5, "14:15"), "2")]
    assert not TO.mixed_flying(dh) and TO.mixed_flying(dh, dh=True)
    rp = [_leg("HNL", "KOA", at(2027, 4, 5, "07:00"), at(2027, 4, 5, "07:45"), "1", dh=True),
          _leg("KOA", "LAX", at(2027, 4, 5, "09:00"), at(2027, 4, 5, "14:00"), "2")]
    assert not TO.mixed_flying(rp) and not TO.mixed_flying(rp, dh=True)
    t = TO.duty_timeout([_duty(at(2027, 4, 5, "06:00"), *dh)], 0, 2, "roster", "332")
    p = t["pwa"]
    assert (p["cite"], p["maximum"], p["mixed"], p["binds"]) == ("10.D.3", "14:00", True, ["ext"])
    assert (t["last_out"]["hst"], t["last_out_ext"]["hst"], t["last_out_ext"]["pwa"]) == ("13:45 HST", "14:30 HST",
                                                                                          True)
    assert "Mixed Flying" in t["unsure"] and t["sure"] is False
    assert any(s.startswith("? Mixed Flying (2.A.45): the interisland deadhead LIH-HNL may be its interisland Segment")
               for s in t["lines"])
    # BASIS-flight-time-duplicate-clock: an HNL departure's clock once
    assert any("Out on time (09:00 HST) the block-in is due by" in s for s in t["lines"])


def test_a_mixed_flying_rest_is_not_sure_when_2_x_the_duty_period_is_not_known():
    """Review PWA-mixed-rest-table-sure-when-2xDP-unknown: a span of the line not on file between the two duties of a
    Mixed Flying grouping: 10.E.1.a.1 cannot be judged, so 10.E.3.a's 9:00 met alone is a '?'. By hand: HNL-LAX release
    14:35 HST Jun 10, a span not on file to 17:35, LAX-HNL-KOA reporting 05:35 HST Jun 11: at least 12:00 free, 9:00 met
    by 3:00."""
    k = "H3993|2027-06-10"
    rep = at(2027, 6, 11, "05:35")
    o = rep + timedelta(minutes=75)
    ds = [_kd(k, at(2027, 6, 10, "08:00"), _leg("HNL", "LAX", at(2027, 6, 10, "09:00"), at(2027, 6, 10, "14:20"), "1")),
          _kd(k, rep, _leg("LAX", "HNL", o, o + timedelta(minutes=340), "2"),
              _leg("HNL", "KOA", o + timedelta(minutes=400), o + timedelta(minutes=440), "3"))]
    t = TO.duty_timeout(ds, 1, 3, "roster", "332", unknown=[(at(2027, 6, 10, "15:00"), at(2027, 6, 10, "17:35"))])
    r = t["pwa"]["rest"]
    assert (r["need"], r["have"], r["ok"], r["cite"]) == ("9:00", "12:00", None, "10.E.3.a") and "rest_q" in t["flags"]
    # review round 5 (F2V-1): the duty before it is on file, so 10.E.1.a.1 is judged across the span (round 4: "not
    # known (the duty before it is not on file)"): Duty Period 08:00 to 14:35 = 6:35, the span to 17:35 3:00, 2 x the
    # longer 13:10; at least 12:00, at most 15:00 since that release: still a '?', other 13:10 (10.E.1.a.1)
    assert r["other"] == "13:10 (10.E.1.a.1)" and any(
        s.startswith("? PWA rest, the other reading (10.E.1.a.1): 10.E.3.a's table alone is not sure until Ryan "
                     "confirms it replaces 10.E.1.a.1: 2 x the preceding Duty Period across a span of your line not "
                     "on file") and s.endswith("? not known: met only if no duty in the span needs more (15:00 since "
                                               "that release).") for s in t["lines"])


def test_in_domicile_after_an_interisland_duty_the_interisland_rest_is_judged_too():
    """Review PWA-interisland-second-reading-asymmetric (a): at home before an International duty that follows an all
    interisland duty (an Interisland Pilot's, 2.A.36.b), 10.E.2.a's 12:00 is judged beside 10.E.1.a's 11:00. By hand:
    HNL-OGG-HNL release 20:45 HST, HNL-LAX reporting 08:15 (11:30): 11:00 met, 12:00 short: '?'; 08:45 (12:00): met."""
    d0 = _duty(at(2027, 3, 1, "17:00"), _leg("HNL", "OGG", at(2027, 3, 1, "18:00"), at(2027, 3, 1, "18:40"), "1"),
               _leg("OGG", "HNL", at(2027, 3, 1, "19:30"), at(2027, 3, 1, "20:30"), "2"))
    t = TO.duty_timeout([d0, _lax(at(2027, 3, 2, "08:15"))], 1, 2, "roster", "332")
    r = t["pwa"]["rest"]
    assert (r["need"], r["have"], r["ok"], r["cite"], r["other"]) == ("11:00", "11:30", None, "10.E.1.a",
                                                                      "12:00 (10.E.2.a)")
    assert ("? PWA rest, the other reading (10.E.2.a): as an Interisland Pilot, the duty before it being all "
            "interisland flying (2.A.36.b): in domicile after a duty that was all interisland flying, 12:00 needed: "
            "SHORT. The readings disagree, so the rest is not sure.") in t["lines"]
    t = TO.duty_timeout([d0, _lax(at(2027, 3, 2, "08:45"))], 1, 2, "roster", "332")
    assert t["pwa"]["rest"]["ok"] is True and "other" not in t["pwa"]["rest"] and t["flags"] == []


@pytest.mark.parametrize("rep_l,lim,ok", [("04:30", 7, False), ("05:00", 10, True)])
def test_pwa_landings_night_start_boundary_at_0459_local(rep_l, lim, ok):
    """Review TEST-boundary-gaps: 10.H.1's 7 landings for a duty starting 2200-0459 local; LAX in April is PDT (HST +
    3): a report 04:30 PDT (01:30 HST) is a night start, 8 legs are over 7; 05:00 PDT (02:00 HST) is not, 8 of 10."""
    h, m = map(int, rep_l.split(":"))
    rep = at(2027, 4, 20, "00:00") + timedelta(hours=h - 3, minutes=m)
    t = TO.duty_timeout([_hops(rep, rep + timedelta(hours=1), 8, blk=30, every=50)], 0, 2, "roster", "332")
    assert (t["pwa"]["landings"]["n"], t["pwa"]["landings"]["max"], t["pwa"]["landings"]["ok"]) == (8, lim, ok)
    assert ("landings" in t["flags"]) is (not ok)


def test_a_sit_of_exactly_two_hours_is_a_repositioning_flight():
    """Review TEST-boundary-gaps: 2.A.62's minimal delay is read as a sit of 2:00 or less: 2:00 at KOA is a
    Repositioning Flight (no Mixed Flying), 2:01 is not."""
    assert not TO.mixed_flying(_sit_pair(120)[1]["legs"]) and TO.mixed_flying(_sit_pair(121)[1]["legs"])
    assert TO._repo([x for x in _sit_pair(120)[1]["legs"]], 1) == (True, timedelta(hours=2))


def test_card_box_has_a_chip_for_every_flag_timeout_sets(browser, tmp_path):
    """Review CARD-flags-segments-pilots-hidden: every key timeout.py appends to the flags maps to a chip and the
    label."""
    import re
    src = open(os.path.join(HERE, "timeout.py")).read()
    js = open(os.path.join(HERE, "www", "flight-watcher-layover-card.js")).read()
    keys = set(re.findall(r'\b(?:flags|r_flags|l_flags)\.append\("(\w+)"\)', src))
    assert {"rest", "week", "pilots", "segments", "early", "pwa_rest", "pwa_sched", "landings", "rest_q",
            "landings_q"} <= keys
    for k in keys - {"rest", "week", "early"}:  # rest and week share "Rest short"; early is last_out.early
        assert f'fl.includes("{k}")' in js, k

    def seg(t):
        t["flags"] = ["segments"]

    def crew(t):
        t["flags"] = ["pilots", "landings_q"]
    for tweak, chips, said in ((seg, ["Over 3 segments (FOM)"], "; Over 3 segments (FOM). Details"),
                               (crew, ["Check crew", "Landings ?"], "; Check crew, Landings ?. Details")):
        pg = browser.new_page(viewport={"width": 390, "height": 844})
        pg.set_content(_page(_watcher_only(tmp_path, tweak=tweak)))
        box = pg.locator("flight-watcher-layover-card [data-to]")
        assert box.locator("[data-towarn]").all_inner_texts() == chips
        assert said in box.get_attribute("aria-label")
        pg.close()


# ---------------------------------------------------------------- review round 4 (the round-3 review's findings)
def test_the_deadhead_mixed_flying_reading_never_relaxes_a_short_pwa_rest():
    """Review round 3, R3-2: Mixed Flying needs less rest out of domicile (10.E.3.a's table in place of 10.E.1.a.1), so
    the deadhead reading (an interisland deadhead read as the interisland Segment, 2.A.45, 2.A.62) applies to the duty
    limit (10.D.3) and the landings (10.H.3) only; the rest reads the grouping without it. By hand, 3 pilots, one
    grouping: DH LIH-HNL 07:00-07:35, HNL-LAX 09:00-14:15 (5:15), report 06:00 HST Apr 5, release 14:30 (domestic,
    2.A.19.b): a Duty Period of 8:30, 2 x = 17:00 (10.E.1.a.1). LAX-HNL reporting 15:00 after that release: 15:00 of
    17:00, SHORT, flagged (round 3 read 10.E.3.a's 9:00 for the 1 landing as the other reading and gave a '?'). The duty
    limit keeps the deadhead reading: 10.D.3, augmented 16:00."""
    k = "H3994|2027-04-05"
    d1 = _kd(k, at(2027, 4, 5, "06:00"),
             _leg("LIH", "HNL", at(2027, 4, 5, "07:00"), at(2027, 4, 5, "07:35"), "1", dh=True),
             _leg("HNL", "LAX", at(2027, 4, 5, "09:00"), at(2027, 4, 5, "14:15"), "2"))
    rep = at(2027, 4, 6, "05:30")
    o = rep + timedelta(minutes=75)
    d2 = _kd(k, rep, _leg("LAX", "HNL", o, o + timedelta(minutes=345), "3"))
    t = TO.duty_timeout([d1, d2], 1, 3, "roster", "332")
    r, p = t["pwa"]["rest"], t["pwa"]
    assert (p["cite"], p["maximum"], p["mixed_grouping"]) == ("10.D.3", "16:00", True)
    assert (r["need"], r["have"], r["ok"], r["cite"]) == ("17:00", "15:00", False, "10.E.1.a.1") and "other" not in r
    assert "pwa_rest" in t["flags"] and "rest_q" not in t["flags"]
    assert "Flag: short of PWA rest (10.E.1.a.1): 15:00 of 17:00." in t["lines"]
    assert not any(s.startswith("? PWA rest") for s in t["lines"])
    assert any(s.startswith("? Mixed Flying (2.A.45): the interisland deadhead LIH-HNL may be its interisland Segment")
               and "The rest before this duty is judged without it" in s for s in t["lines"])


def test_the_deadhead_mixed_flying_reading_may_only_add_a_question_to_a_met_rest():
    """Review round 3, R3-2: the deadhead reading may only make a rest otherwise met a '?', where 10.E.3.a's table needs
    more than 2 x the Duty Period and is not met, or is met by less than VAN_RIDES (2:30). By hand, 3 pilots, one
    grouping: day 1 as above (DH LIH-HNL, HNL-LAX, release 14:30 HST Apr 5, 8:30); LAX-SFO reporting 20:00 later (10:30
    HST Apr 6), out 11:45, in 13:15 (1:30), release 13:30: a 3:00 Duty Period, 2 x = 6:00; SFO-HNL reporting 11:00
    after it (00:30 HST Apr 7): 6:00 met by 5:00. 2 landings performed in the grouping before this rest (HNL-LAX,
    LAX-SFO): 10.E.3.a's table 9:00, more than 6:00, met by 2:00 only, under 2:30: '?', the "Rest ?" chip, no flag.
    11:30 after it (01:00 HST): 9:00 met by 2:30: met. 8:45 after it (22:15 HST Apr 6): 6:00 met by 2:45, the table's
    9:00 not met: '?', never short (FAR 117.25(e)'s 10 h is short there: its own flag)."""
    k = "H3995|2027-04-05"
    d1 = _kd(k, at(2027, 4, 5, "06:00"),
             _leg("LIH", "HNL", at(2027, 4, 5, "07:00"), at(2027, 4, 5, "07:35"), "1", dh=True),
             _leg("HNL", "LAX", at(2027, 4, 5, "09:00"), at(2027, 4, 5, "14:15"), "2"))
    d2 = _kd(k, at(2027, 4, 6, "10:30"), _leg("LAX", "SFO", at(2027, 4, 6, "11:45"), at(2027, 4, 6, "13:15"), "3"))

    def d3(rest_m):
        rep = at(2027, 4, 6, "13:30") + timedelta(minutes=rest_m)
        o = rep + timedelta(minutes=75)
        return _kd(k, rep, _leg("SFO", "HNL", o, o + timedelta(minutes=330), "4"))
    t = TO.duty_timeout([d1, d2, d3(660)], 2, 3, "roster", "332")
    r = t["pwa"]["rest"]
    assert (r["need"], r["have"], r["ok"], r["cite"], r["other"]) == ("6:00", "11:00", None, "10.E.1.a.1",
                                                                      "9:00 (10.E.3.a)")
    assert t["flags"] == ["rest_q"] and "rest 11:00, 6:00 (10.E.1.a.1) or 9:00 (10.E.3.a) needed: ?" in t["pwa"]["txt"]
    assert ("? PWA rest, the deadhead reading (10.E.3.a): if the interisland deadhead LIH-HNL is its interisland "
            "Segment (2.A.45, 2.A.62), this grouping holds a Mixed Flying Duty Period and 10.E.3.a's table needs 9:00 "
            "for the 2 landings performed in it before this rest, more than 6:00 (10.E.1.a.1): ? met by 2:00 from "
            "release to report, but the hotel time (door to door, 2.A.68.b, 10.E.1.a.3) is shorter by the two van "
            "rides, which are not on the schedule (under 2:30 spare is not sure). Read without it the rest is met; "
            "this reading only adds the '?'.") in t["lines"]
    t = TO.duty_timeout([d1, d2, d3(690)], 2, 3, "roster", "332")
    assert t["pwa"]["rest"]["ok"] is True and "other" not in t["pwa"]["rest"] and t["flags"] == []
    t = TO.duty_timeout([d1, d2, d3(525)], 2, 3, "roster", "332")
    r = t["pwa"]["rest"]
    assert (r["need"], r["have"], r["ok"]) == ("6:00", "8:45", None) and "pwa_rest" not in t["flags"]
    assert "rest" in t["flags"] and any(s.startswith("? PWA rest, the deadhead reading (10.E.3.a)") and
                                        s.endswith("(10.E.1.a.1): SHORT. Read without it the rest is met; this reading "
                                                   "only adds the '?'.") for s in t["lines"])


def test_the_56_h_and_deadhead_rests_are_judged_across_a_span_not_on_file():
    """Review round 3, R3-3: with a span of the line not on file between the duty before and the report, FAR 117.25(d)
    and (g) are still judged on the duty before it: the rest is at least the time since the span ended and at most the
    time since that duty's release; met only when the first meets it, else a '?' (never short: a duty in the span would
    move the rule to it). By hand: the 177:00 SIN trip (_sin_trip, release 17:00 HST Apr 8; SIN 98 deg from HNL), a span
    not on file Apr 9 00:00-Apr 10 00:00 HST, HNL-LAX reporting 12:00 HST Apr 10: at least 12:00, at most 43:00, of
    56:00: '?' (round 3: no 56 h line, the FAR rest 'met'); reporting 06:00 HST Apr 11: at least 30:00, at most 61:00:
    '?' (review round 4, fix 2, RV-4: and 61:00 holds only the 0100-0700 HNL nights of Apr 9 and 10, so its words say a
    '?' even then); a span Apr 8 18:00-20:00 and the report 07:00 HST Apr 11: at least 59:00, holding the 0100-0700 HNL
    nights of Apr 9, 10 and 11: met (review round 4, fix 1, R4-4: reporting 05:00, 57:00 holds two of them: '?'). The
    deadhead-only SIN-HNL (release 21:30 HST Apr 8, 15:00 needed, as in the 117.25(g) test), a span Apr 9 00:00-02:00,
    HNL-LAX reporting 12:30 HST Apr 9: at least 10:30, at most 15:00: '?'."""
    t = TO.duty_timeout(_sin_trip() + [_lax(at(2027, 4, 10, "12:00"))], 2, 2, "roster", "332",
                        unknown=[(at(2027, 4, 9, "00:00"), at(2027, 4, 10, "00:00"))])
    assert (t["rest"]["ok"], t["rest"]["need"], t["rest"]["free"]) == (None, "56:00", "12:00")
    assert "rest" not in t["flags"] and "rest_q" in t["flags"]
    assert any(s.startswith("Rest on return to home base (FAR 117.25(d), FOM 4.3.2.11): 177:00 away from HNL") and
               s.endswith("; at least 12:00 free (since the end of a span of your line not on file; 43:00 since the "
                          "release of the duty before it): ? not known: SHORT of 56:00 if no duty was in the span not "
                          "on file.") for s in t["lines"])
    assert not any(s.startswith("Flag: short of FAR rest") for s in t["lines"])
    t = TO.duty_timeout(_sin_trip() + [_lax(at(2027, 4, 11, "06:00"))], 2, 2, "roster", "332",
                        unknown=[(at(2027, 4, 9, "00:00"), at(2027, 4, 10, "00:00"))])
    # review round 4, fix 2 (RV-4): 61:00 from the release 17:00 HST Apr 8 holds only the nights of Apr 9 and 10
    assert t["rest"]["ok"] is None and any(s.endswith(": ? not known: met only if the span not on file was free "
                                                      "from duty (61:00 then, but it holds only 2 of the three "
                                                      "physiological nights, 0100-0700 HNL: a '?' even then).")
                                           for s in t["lines"])
    t = TO.duty_timeout(_sin_trip() + [_lax(at(2027, 4, 11, "07:00"))], 2, 2, "roster", "332",
                        unknown=[(at(2027, 4, 8, "18:00"), at(2027, 4, 8, "20:00"))])
    assert (t["rest"]["ok"], t["rest"]["free"]) == (True, "59:00") and any(
        "FAR 117.25(d)" in s and s.endswith("since the release of the duty before it): met (3 physiological nights, "
                                            "0100-0700 HNL).") for s in t["lines"])
    t = TO.duty_timeout(_sin_trip() + [_lax(at(2027, 4, 11, "05:00"))], 2, 2, "roster", "332",
                        unknown=[(at(2027, 4, 8, "18:00"), at(2027, 4, 8, "20:00"))])
    assert (t["rest"]["ok"], t["rest"]["free"]) == (None, "57:00") and "rest_q" in t["flags"] and any(
        "FAR 117.25(d)" in s and s.endswith("since the release of the duty before it): ? 2 of the three physiological "
                                            "nights (0100-0700 HNL) are inside it (FAR 117.3 reads one as 10 h of rest "
                                            "holding 0100-0700 at home base; not in the FOM, Ryan to confirm).")
        for s in t["lines"])
    out = _duty(at(2027, 4, 6, "08:00"), _leg("HNL", "SIN", at(2027, 4, 6, "09:00"), at(2027, 4, 6, "19:30"), "0"))
    dh = _duty(at(2027, 4, 8, "06:00"),
               _leg("SIN", "HNL", at(2027, 4, 8, "07:00"), at(2027, 4, 8, "21:00"), "1", dh=True))
    t = TO.duty_timeout([out, dh, _lax(at(2027, 4, 9, "12:30"))], 2, 2, "roster", "332",
                        unknown=[(at(2027, 4, 9, "00:00"), at(2027, 4, 9, "02:00"))])
    assert (t["rest"]["ok"], t["rest"]["need"], t["rest"]["free"]) == (None, "15:00", "10:30")
    assert "rest_q" in t["flags"]
    assert any(s.startswith("Rest after deadhead transportation (FAR 117.25(g), FOM 4.3.2.10)") and
               s.endswith("at least 10:30 free (since the end of a span of your line not on file; 15:00 since the "
                          "release of the duty before it): ? not known: met only if the span not on file was free from "
                          "duty (15:00 then).") for s in t["lines"])


def test_an_unacclimated_deadhead_takes_its_last_acclimated_clock_less_30_minutes():
    """Review round 3, R3-4: the deadhead's Table B FDP is read on its own acclimation (FAR 117.13(b), FOM 4.3.2.4: not
    acclimated, the last acclimated theater's clock and 0:30 less). By hand: HNL-JFK report 03:00 HST Apr 2, in 13:00,
    release 13:15 (domestic); a JFK-HNL deadhead only reporting 13:00 HST Apr 3: 23:45 free at JFK (84 deg from HNL),
    under 36 h: not acclimated. Table B on HNL time, row 1300-1659, 1 segment: 12:00 - 0:30 = 11:30. Out 14:00, in 00:45
    HST Apr 4: 11:45 from the report, over 11:30: 11:45 needed, sure (deadheads alone, acclimation known). Release
    01:00 HST; HNL-LAX reporting 12:00 HST Apr 4: 11:00 free, SHORT (round 3 read 12:00 on the HNL and JFK clocks, 18:00
    EDT, and did not apply it); 12:45: met. With a span of the line not on file before the deadhead (Apr 2 20:00 to Apr
    3 00:00 HST) round 4 read its acclimation as not known: the lowest row on any clock, 9:00 - 0:30 = 8:30, a '?'.
    Review round 5 (RV5-1): the 23:45 from the release to the deadhead's report, the span inside it, is under 36 h and
    he arrived at JFK 24:00 before it (under 72 h), so the span holds no acclimation: read as free time or as duty he is
    not acclimated, HNL time less 0:30 = 11:30 both ways; 11:45 is over it: SHORT as with no span. With the span from
    Apr 2 00:00 HST (inside the HNL-JFK duty, 37:00 to the report, 36 h or more) the lowest row stays: a '?'."""
    out = _duty(at(2027, 4, 2, "03:00"), _leg("HNL", "JFK", at(2027, 4, 2, "04:00"), at(2027, 4, 2, "13:00"), "0"))
    dh = _duty(at(2027, 4, 3, "13:00"),
               _leg("JFK", "HNL", at(2027, 4, 3, "14:00"), at(2027, 4, 4, "00:45"), "1", dh=True))
    t = TO.duty_timeout([out, dh, _lax(at(2027, 4, 4, "12:00"))], 2, 2, "roster", "332")
    assert (t["rest"]["ok"], t["rest"]["need"], t["rest"]["free"]) == (False, "11:45", "11:00") and "rest" in t["flags"]
    assert ("Rest after deadhead transportation (FAR 117.25(g), FOM 4.3.2.10): the duty before it was deadhead "
            "transportation only, 11:45 from its report to its last block-in, over its Table B FDP 11:30 (HNL time, "
            "less 0:30: not acclimated, FAR 117.13(b)): a rest as long as the deadhead transportation (11:45, from the "
            "report), no less than 10 h; 11:00 free: SHORT, check with Crew Scheduling.") in t["lines"]
    assert "Flag: short of FAR rest (FAR 117.25(g)): 11:00 of 11:45." in t["lines"]
    t = TO.duty_timeout([out, dh, _lax(at(2027, 4, 4, "12:45"))], 2, 2, "roster", "332")
    assert (t["rest"]["ok"], t["rest"]["need"]) == (True, "11:45") and t["flags"] == []
    t = TO.duty_timeout([out, dh, _lax(at(2027, 4, 4, "12:00"))], 2, 2, "roster", "332",
                        unknown=[(at(2027, 4, 2, "20:00"), at(2027, 4, 3, "00:00"))])
    # review round 5 (RV5-1): bounded across the span, so sure (round 4: '?', "need" not set)
    assert (t["rest"]["ok"], t["rest"]["need"], t["rest"]["free"]) == (False, "11:45", "11:00") and "rest" in t["flags"]
    assert ("Rest after deadhead transportation (FAR 117.25(g), FOM 4.3.2.10): the duty before it was deadhead "
            "transportation only, 11:45 from its report to its last block-in, over its Table B FDP on every reading of "
            "its acclimation across a span of your line not on file (11:30 at most, HNL time, less 0:30: not "
            "acclimated, FAR 117.13(b)): a rest as long as the deadhead transportation (11:45, from the report), no "
            "less than 10 h; 11:00 free: SHORT, check with Crew Scheduling.") in t["lines"]
    t = TO.duty_timeout([out, dh, _lax(at(2027, 4, 4, "12:00"))], 2, 2, "roster", "332",
                        unknown=[(at(2027, 4, 2, "00:00"), at(2027, 4, 3, "00:00"))])
    assert (t["rest"]["ok"], t["rest"]["free"]) == (None, "11:00") and "need" not in t["rest"]
    assert "rest" not in t["flags"]
    assert any(s.startswith("Rest after deadhead transportation (FAR 117.25(g), FOM 4.3.2.10)") and "over its Table B "
               "FDP 8:30 (the lowest row on any clock, less 0:30: acclimation not known)" in s and
               "(? its acclimation is not known)" in s and s.endswith("11:00 free: ? SHORT of 11:45 if it applies.")
               for s in t["lines"])


def test_a_trailing_deadhead_is_measured_from_the_last_flown_block_in():
    """Review round 3, R3-5: a deadhead after the last flown leg is measured from that leg's block-in (the sit before it
    counts, conservative). By hand, 3 pilots: SFO-HNL 07:00-12:30 HST Apr 8 (report 06:00), a HNL-SIN deadhead out
    15:30, in 02:30 HST Apr 9 (a 3:00 sit at HNL), release 03:00 (customs). Over its Table B FDP (20:30 from the report;
    acclimated to HNL, 2 segments, 13:00 on HNL time, 14:00 on SFO's 09:00 PDT: the lower). Length 12:30 to 02:30 =
    14:00 (round 3: 11:00 from the deadhead's out). SIN-NRT reporting 12:00 after the release: '?' short of 14:00 if
    it applies (round 3: met by 1:00); 14:00 after it: met."""
    tr = _duty(at(2027, 4, 8, "06:00"), _leg("SFO", "HNL", at(2027, 4, 8, "07:00"), at(2027, 4, 8, "12:30"), "1"),
               _leg("HNL", "SIN", at(2027, 4, 8, "15:30"), at(2027, 4, 9, "02:30"), "2", dh=True))

    def nxt(rest_h):
        rep = at(2027, 4, 9, "03:00") + timedelta(hours=rest_h)
        o = rep + timedelta(minutes=75)
        return _duty(rep, _leg("SIN", "NRT", o, o + timedelta(hours=7), "3"))
    t = TO.duty_timeout([tr, nxt(12)], 1, 3, "roster", "332")
    assert (t["rest"]["ok"], t["rest"]["free"]) == (None, "12:00") and "rest" not in t["flags"]
    assert any(s.startswith("Rest after deadhead transportation (FAR 117.25(g), FOM 4.3.2.10): the duty before it "
                            "ended with deadhead transportation after its last flown leg, 20:30 from its report to its "
                            "last block-in, over its Table B FDP 13:00 (HNL time): a rest as long as the deadhead "
                            "transportation (14:00, from the last flown block-in: the sit before the deadhead counts, "
                            "conservative)") and s.endswith("12:00 free: ? SHORT of 14:00 if it applies.")
               for s in t["lines"])
    t = TO.duty_timeout([tr, nxt(14)], 1, 3, "roster", "332")
    assert t["rest"]["ok"] is True and any("FAR 117.25(g)" in s and s.endswith("14:00 free: met.") for s in t["lines"])


def test_the_56_h_rest_takes_the_widest_spread_of_the_trip_not_only_the_distance_from_hnl():
    """Review round 3, R3-6: "travels more than 60 degrees longitude" (FAR 117.25(d), FOM 4.3.2.11) is read as the
    largest spread between two of HNL and the trip's stations (conservative). By hand: HNL-LAX (report 08:00 HST May 1),
    LAX-SYD, SYD-HNL in 11:00 HST May 8, release 11:30 (customs): 171:30 away, more than 168 h. LAX is 39.5 deg from HNL
    (-118.4 and -157.9), SYD 50.9 (151.2: 309.1 the long way), but LAX and SYD are 90.4 apart (269.6 the long way): more
    than 60, so 56 h; HNL-LAX reporting 12:00 HST May 9: 24:30 free, SHORT (round 3 took SYD's 51 deg from HNL: no 56 h
    rule). Where the widest pair holds HNL the line names it from HNL, as for SIN (98 deg)."""
    ds = [_duty(at(2027, 5, 1, "08:00"), _leg("HNL", "LAX", at(2027, 5, 1, "09:00"), at(2027, 5, 1, "14:15"), "1")),
          _duty(at(2027, 5, 3, "08:00"), _leg("LAX", "SYD", at(2027, 5, 3, "09:00"), at(2027, 5, 3, "23:30"), "2")),
          _duty(at(2027, 5, 8, "00:00"), _leg("SYD", "HNL", at(2027, 5, 8, "01:00"), at(2027, 5, 8, "11:00"), "3")),
          _lax(at(2027, 5, 9, "12:00"))]
    assert round(TO.ang(TO.LON["LAX"], TO.LON["SYD"]), 1) == 90.4 and TO.same_theater("SYD", "HNL") is True
    t = TO.duty_timeout(ds, 3, 2, "roster", "332")
    assert (t["rest"]["ok"], t["rest"]["need"], t["rest"]["free"]) == (False, "56:00", "24:30") and "rest" in t["flags"]
    assert ("Rest on return to home base (FAR 117.25(d), FOM 4.3.2.11): 171:30 away from HNL (08:00 HST Sat May 1 to "
            "release 11:30 HST Sat May 8, more than 168 h) and LAX and SYD are 90 deg apart (more than 60): 56 "
            "consecutive hours, holding three physiological nights; 24:30 free: SHORT, check with Crew "
            "Scheduling.") in t["lines"]
    t = TO.duty_timeout(_sin_trip() + [_lax(at(2027, 4, 10, "08:00"))], 2, 2, "roster", "332")
    assert any("and SIN is 98 deg from HNL (more than 60)" in s for s in t["lines"])


# ------------------------------------------------------------ review round 4, fix 1 (the round-4 verifiers' findings)
def _dh_sin(arr="21:00"):
    """HNL-SIN (report 08:00 HST Apr 6, in 19:30, release 20:00, customs), a SIN-HNL deadhead only (report 06:00 HST
    Apr 8, out 07:00, in `arr` HST, release 30 min after it)."""
    h, m = map(int, arr.split(":"))
    return [_duty(at(2027, 4, 6, "08:00"), _leg("HNL", "SIN", at(2027, 4, 6, "09:00"), at(2027, 4, 6, "19:30"), "0")),
            _duty(at(2027, 4, 8, "06:00"), _leg("SIN", "HNL", at(2027, 4, 8, "07:00"),
                                                at(2027, 4, 8, "00:00") + timedelta(hours=h, minutes=m), "1", dh=True))]


def test_a_deadhead_past_every_table_b_row_needs_its_rest_whatever_the_acclimation():
    """Review round 4, fix 1 (R4-1): FAR 117.25(g) is sure for deadheads alone whose report to block-in is over every
    Table B row for their segments, on any clock and whatever the acclimation. By hand: the SIN-HNL deadhead, report
    06:00 HST Apr 8, in 21:00: 15:00 from the report; a span of the line not on file at SIN (Apr 7 00:00-02:00 HST)
    makes its acclimation not known, but Table B for 1 segment is 14:00 at most (row 0700-1159), so 15:00 is over the
    applicable FDP on every reading: 15:00 needed. Release 21:30 (customs); HNL-LAX reporting 10:30 HST Apr 9: 13:00
    free, SHORT, flagged (round 4 read a '?'). In 20:00 instead: 14:00 is not over the 14:00 row; round 4, fix 1 read
    that it may apply only (the lowest row on any clock, 9:00 less 0:30 = 8:30): release 20:30, the report 09:30 HST
    Apr 9, 13:00 free of 14:00: '?'. Review round 5 (RV5-1): the 34:00 from the HNL-SIN release (20:00 Apr 6) to the
    deadhead's report, the span inside it, is under 36 h, and he reached SIN 34:30 before it: the span holds no
    acclimation, and read as free time or as duty he is not acclimated: HNL time 06:00, row 0600-0659, 13:00 less 0:30 =
    12:30; 14:00 is over it: SHORT. Reported 2:00 later (08:00 HST Apr 8, in 22:00, 36:00 after the release): round 5
    kept the lowest row (the span with the time around it is 36 h); review round 5, fix 2 (RF1-36H-ANYWHERE): a report
    inside the span follows at most 6:00 free (20:00 Apr 6 to 02:00 Apr 7), so it holds no acclimation to a theater not
    on file, and the span is bounded: free time, 36:00 free at SIN, acclimated there: SIN 02:00, row 0000-0359, 9:00;
    duty, 30:00 free and 30:30 in that theater, not acclimated: HNL 08:00 less 0:30, 13:30. 14:00 is over both:
    release 22:30, the report 11:30 HST Apr 9, 13:00 free of 14:00: SHORT (round 5 and fix 1: '?')."""
    unk = [(at(2027, 4, 7, "00:00"), at(2027, 4, 7, "02:00"))]
    t = TO.duty_timeout(_dh_sin() + [_lax(at(2027, 4, 9, "10:30"))], 2, 2, "roster", "332", unknown=unk)
    assert (t["rest"]["ok"], t["rest"]["need"], t["rest"]["free"]) == (False, "15:00", "13:00") and "rest" in t["flags"]
    assert ("Rest after deadhead transportation (FAR 117.25(g), FOM 4.3.2.10): the duty before it was deadhead "
            "transportation only, 15:00 from its report to its last block-in, over every Table B row (14:00 at most "
            "for 1 segment, on any clock): a rest as long as the deadhead transportation (15:00, from the report), no "
            "less than 10 h; 13:00 free: SHORT, check with Crew Scheduling.") in t["lines"]
    assert "Flag: short of FAR rest (FAR 117.25(g)): 13:00 of 15:00." in t["lines"]
    t = TO.duty_timeout(_dh_sin("20:00") + [_lax(at(2027, 4, 9, "09:30"))], 2, 2, "roster", "332", unknown=unk)
    # review round 5 (RV5-1): bounded across the span: sure, SHORT (round 4, fix 1: '?')
    assert (t["rest"]["ok"], t["rest"]["need"], t["rest"]["free"]) == (False, "14:00", "13:00") and "rest" in t["flags"]
    assert any(s.startswith("Rest after deadhead transportation (FAR 117.25(g), FOM 4.3.2.10)") and "over its Table B "
               "FDP on every reading of its acclimation across a span of your line not on file (12:30 at most, HNL "
               "time, less 0:30: not acclimated, FAR 117.13(b))" in s and s.endswith("13:00 free: SHORT, check with "
                                                                                    "Crew Scheduling.")
               for s in t["lines"])
    ds = _dh_sin()[:1] + [_duty(at(2027, 4, 8, "08:00"), _leg("SIN", "HNL", at(2027, 4, 8, "09:00"),
                                                              at(2027, 4, 8, "22:00"), "1", dh=True))]
    t = TO.duty_timeout(ds + [_lax(at(2027, 4, 9, "11:30"))], 2, 2, "roster", "332", unknown=unk)
    # review round 5, fix 2 (RF1-36H-ANYWHERE): bounded, past both readings: SHORT (round 5 and fix 1: '?')
    assert (t["rest"]["ok"], t["rest"]["need"], t["rest"]["free"]) == (False, "14:00", "13:00") and "rest" in t["flags"]
    assert any(s.startswith("Rest after deadhead transportation (FAR 117.25(g), FOM 4.3.2.10)") and "over its Table B "
               "FDP on every reading of its acclimation across a span of your line not on file (13:30 at most, HNL "
               "time, less 0:30: not acclimated on a reading of a span of your line not on file)" in s and
               s.endswith("13:00 free: SHORT, check with Crew Scheduling.") for s in t["lines"])
    pr = [TO._prep(d) for d in ds + [_lax(at(2027, 4, 9, "11:30"))]]
    assert TO._acc_bound(pr, 1, (), unk) == ([("SIN", False), ("HNL", True)], None)


def test_a_deadhead_also_takes_the_domicile_clock_and_a_station_clock_not_on_file_as_readings():
    """Review round 4, fix 1 (R4-2, R4-3 of the code review): two more Table B readings for 117.25(g) that may only make
    it a '?' (they never make it sure). By hand:
    - HNL-NRT report 08:00 HST Apr 1 (in 17:30, release 18:00), NRT-LAX report 10:00 HST Apr 3 (40:00 free at NRT: 36 h
      acclimates there), in 20:30, release 21:00 (customs); a LAX-HNL deadhead only reporting 14:00 HST Apr 4 (17:00
      free at LAX, 101 deg from NRT: not acclimated), out 21:00, in 02:30 HST Apr 5: 12:30 from the report. On its
      acclimation (FAR 117.13(b): NRT time, 09:00 JST, row 0700-1159, 14:00 less 0:30 = 13:30) it is not over; on
      the domicile's clock (FOM 4.3.2.4 "the report time at local domicile": HNL 14:00, row 1300-1659, 12:00 less
      0:30 = 11:30) it is: '?' (round 3 read HNL's and LAX's 12:00 with no reduction and gave SHORT; round 4 no line).
      Release 02:45; HNL-LAX reporting 11:00 later: '? SHORT of 12:30 if it applies', the "Rest ?" chip; 13:00: met.
      The same deadhead in at 04:00 HST Apr 5: 14:00 from the report, over NRT's 13:30, so sure on its acclimation
      (the line names that reading, not the lower domicile one): release 04:15, HNL-LAX reporting 15:15: 11:00 of
      14:00, SHORT, flagged. A higher domicile reading never makes a sure one a '?': HNL-SIN (report 08:00 HST Apr 1,
      release 20:00), a SIN-HNL deadhead only reporting 08:00 HST Apr 3 (36:00 free: acclimated to SIN), SIN 02:00,
      row 0000-0359, 9:00 (HNL 08:00 would give 14:00); out 09:00, in 20:00: 12:00, over 9:00: sure; release 20:30,
      HNL-LAX reporting 07:30 HST Apr 4: 11:00 of 12:00, SHORT.
    - HNL-XYZ (report 11:00 HST Apr 1, in 17:30, release 18:00: XYZ's country is not on file, customs), an XYZ-HNL
      deadhead only reporting 08:00 HST Apr 2, out 14:30, in 20:00: 12:00. XYZ has no longitude: acclimation not
      known, HNL time 08:00 less 0:30 = 13:30; XYZ's own clock is not on file, so the lowest row, 9:00: over it: '?'
      (round 4: no line). Release 20:30; HNL-LAX reporting 06:45 HST Apr 3: 10:15 free, '? SHORT of 12:00'."""
    a = _duty(at(2027, 4, 1, "08:00"), _leg("HNL", "NRT", at(2027, 4, 1, "09:00"), at(2027, 4, 1, "17:30"), "1"))
    b = _duty(at(2027, 4, 3, "10:00"), _leg("NRT", "LAX", at(2027, 4, 3, "11:00"), at(2027, 4, 3, "20:30"), "2"))
    dh = _duty(at(2027, 4, 4, "14:00"),
               _leg("LAX", "HNL", at(2027, 4, 4, "21:00"), at(2027, 4, 5, "02:30"), "3", dh=True))
    t = TO.duty_timeout([a, b, dh, _lax(at(2027, 4, 5, "13:45"))], 3, 2, "roster", "332")
    assert (t["rest"]["ok"], t["rest"]["free"]) == (None, "11:00") and "need" not in t["rest"]
    assert t["flags"] == ["rest_q"]
    assert ("Rest after deadhead transportation (FAR 117.25(g), FOM 4.3.2.10): the duty before it was deadhead "
            "transportation only, 12:30 from its report to its last block-in, over its Table B FDP 11:30 (HNL time, "
            "the domicile's clock, less 0:30: not acclimated, FAR 117.13(b); a reading to confirm, FOM 4.3.2.4): a "
            "rest as long as the deadhead transportation (12:30, from the report), no less than 10 h (? its "
            "acclimation readings give 13:30); 11:00 free: ? SHORT of 12:30 if it applies.") in t["lines"]
    t = TO.duty_timeout([a, b, dh, _lax(at(2027, 4, 5, "15:45"))], 3, 2, "roster", "332")
    assert t["rest"]["ok"] is True and any("FAR 117.25(g)" in s and s.endswith("13:00 free: met.") for s in t["lines"])
    dh4 = _duty(at(2027, 4, 4, "14:00"),
                _leg("LAX", "HNL", at(2027, 4, 4, "22:30"), at(2027, 4, 5, "04:00"), "3", dh=True))
    t = TO.duty_timeout([a, b, dh4, _lax(at(2027, 4, 5, "15:15"))], 3, 2, "roster", "332")
    assert (t["rest"]["ok"], t["rest"]["need"], t["rest"]["free"]) == (False, "14:00", "11:00") and "rest" in t["flags"]
    assert any(s.startswith("Rest after deadhead transportation (FAR 117.25(g), FOM 4.3.2.10)") and "over its Table B "
               "FDP 13:30 (NRT time, less 0:30: not acclimated, FAR 117.13(b)): a rest" in s and
               s.endswith("11:00 free: SHORT, check with Crew Scheduling.") for s in t["lines"])
    a2 = _duty(at(2027, 4, 1, "08:00"), _leg("HNL", "SIN", at(2027, 4, 1, "09:00"), at(2027, 4, 1, "19:30"), "1"))
    d2 = _duty(at(2027, 4, 3, "08:00"),
               _leg("SIN", "HNL", at(2027, 4, 3, "09:00"), at(2027, 4, 3, "20:00"), "2", dh=True))
    t = TO.duty_timeout([a2, d2, _lax(at(2027, 4, 4, "07:30"))], 2, 2, "roster", "332")
    assert (t["rest"]["ok"], t["rest"]["need"], t["rest"]["free"]) == (False, "12:00", "11:00") and "rest" in t["flags"]
    assert any("over its Table B FDP 9:00 (SIN time): a rest" in s and s.endswith("11:00 free: SHORT, check with Crew "
                                                                                   "Scheduling.") for s in t["lines"])
    o = _duty(at(2027, 4, 1, "11:00"), _leg("HNL", "XYZ", at(2027, 4, 1, "12:00"), at(2027, 4, 1, "17:30"), "1"))
    dx = _duty(at(2027, 4, 2, "08:00"), _leg("XYZ", "HNL", at(2027, 4, 2, "14:30"), at(2027, 4, 2, "20:00"), "2",
                                             dh=True))
    t = TO.duty_timeout([o, dx, _lax(at(2027, 4, 3, "06:45"))], 2, 2, "roster", "332")
    assert (t["rest"]["ok"], t["rest"]["free"]) == (None, "10:15") and "rest" not in t["flags"]
    assert any(s.startswith("Rest after deadhead transportation (FAR 117.25(g), FOM 4.3.2.10)") and "over its Table B "
               "FDP 9:00 (the lowest row on any clock, XYZ's own clock not on file)" in s
               and "(? its acclimation is not "
               "known; its acclimation readings give 13:30)" in s and s.endswith("10:15 free: ? SHORT of 12:00 if it "
                                                                              "applies.") for s in t["lines"])


def test_a_deadhead_between_two_readings_of_its_acclimation_may_need_its_rest():
    """Review round 4, fix 1 (R4-5 of the code review, mutants M1 and M15): a deadhead over the lower reading's Table B
    FDP and not over the higher one's is a '?', neither sure nor dropped. By hand: HNL-LAX report 08:00 HST Apr 1, in
    14:15, release 14:30; a LAX-HNL deadhead only reporting 05:00 HST Apr 2 (14:30 free; LAX 39.5 deg from HNL:
    acclimated to the HNL theater), its readings HNL 05:00 (row 0500-0559, 12:00) and LAX 08:00 PDT (row 0700-1159,
    14:00); out 11:30, in 18:00: 13:00 from the report, over 12:00 only. Release 18:15; HNL-LAX reporting 12:00 later:
    '? SHORT of 13:00 if it applies'; 13:00 later: met."""
    o = _duty(at(2027, 4, 1, "08:00"), _leg("HNL", "LAX", at(2027, 4, 1, "09:00"), at(2027, 4, 1, "14:15"), "1"))
    dh = _duty(at(2027, 4, 2, "05:00"),
               _leg("LAX", "HNL", at(2027, 4, 2, "11:30"), at(2027, 4, 2, "18:00"), "2", dh=True))
    t = TO.duty_timeout([o, dh, _lax(at(2027, 4, 3, "06:15"))], 2, 2, "roster", "332")
    assert (t["rest"]["ok"], t["rest"]["free"]) == (None, "12:00") and t["flags"] == ["rest_q"]
    assert ("Rest after deadhead transportation (FAR 117.25(g), FOM 4.3.2.10): the duty before it was deadhead "
            "transportation only, 13:00 from its report to its last block-in, over its Table B FDP 12:00 (HNL time): a "
            "rest as long as the deadhead transportation (13:00, from the report), no less than 10 h (? another "
            "reading of its acclimation gives 14:00); 12:00 free: ? SHORT of 13:00 if it applies.") in t["lines"]
    t = TO.duty_timeout([o, dh, _lax(at(2027, 4, 3, "07:15"))], 2, 2, "roster", "332")
    assert t["rest"]["ok"] is True and t["flags"] == []


def test_the_longer_far_rests_are_not_sure_with_a_schedule_item_or_a_station_with_no_longitude():
    """Review round 4, fix 1 (R4-5 of the code review, mutants M18 and M32). By hand:
    - the 177:00 SIN trip (_sin_trip, release 17:00 HST Apr 8), HNL-LAX reporting 07:00 HST Apr 11: 62:00 free, three
      nights, met; a schedule item that may be duty Apr 9 10:00-12:00 HST inside it: '? a schedule item inside it may
      be duty' (the 10 h of 117.25(e) too);
    - the SIN-HNL deadhead (_dh_sin, release 21:30 HST Apr 8, 15:00 needed), HNL-LAX reporting 12:30 HST Apr 9: 15:00
      free, met; an item Apr 9 02:00-03:00: '?';
    - HNL-LAX (report 08:00 HST May 1), LAX-XYZ, XYZ-HNL in 11:00 HST May 8, release 11:30 (customs): 171:30 away. LAX
      is 39.5 deg from HNL, XYZ has no longitude: it may be more than 60 deg away, so 56 h may apply; HNL-LAX
      reporting 12:00 HST May 9: 24:30 free: '? SHORT of 56:00 if it applies' (the "Rest ?" chip, no flag)."""
    t = TO.duty_timeout(_sin_trip() + [_lax(at(2027, 4, 11, "07:00"))], 2, 2, "roster", "332",
                        busy=[(at(2027, 4, 9, "10:00"), at(2027, 4, 9, "12:00"))])
    assert t["rest"]["ok"] is None and "rest_q" in t["flags"]
    assert any(s.startswith("Rest on return to home base (FAR 117.25(d)") and s.endswith("; 62:00 free: ? a schedule "
                                                                                         "item inside it may be duty.")
               for s in t["lines"])
    t = TO.duty_timeout(_dh_sin() + [_lax(at(2027, 4, 9, "12:30"))], 2, 2, "roster", "332",
                        busy=[(at(2027, 4, 9, "02:00"), at(2027, 4, 9, "03:00"))])
    assert (t["rest"]["ok"], t["rest"]["need"]) == (None, "15:00") and "rest_q" in t["flags"]
    assert any(s.startswith("Rest after deadhead transportation (FAR 117.25(g)") and s.endswith("; 15:00 free: ? a "
                                                                                                "schedule item inside "
                                                                                                "it may be duty.")
               for s in t["lines"])
    ds = [_duty(at(2027, 5, 1, "08:00"), _leg("HNL", "LAX", at(2027, 5, 1, "09:00"), at(2027, 5, 1, "14:15"), "1")),
          _duty(at(2027, 5, 3, "08:00"), _leg("LAX", "XYZ", at(2027, 5, 3, "09:00"), at(2027, 5, 3, "14:00"), "2")),
          _duty(at(2027, 5, 8, "00:00"), _leg("XYZ", "HNL", at(2027, 5, 8, "01:00"), at(2027, 5, 8, "11:00"), "3")),
          _lax(at(2027, 5, 9, "12:00"))]
    t = TO.duty_timeout(ds, 3, 2, "roster", "332")
    assert (t["rest"]["ok"], t["rest"]["free"]) == (None, "24:30") and "need" not in t["rest"]
    assert "rest" not in t["flags"] and "rest_q" in t["flags"]
    assert ("Rest on return to home base (FAR 117.25(d), FOM 4.3.2.11): 171:30 away from HNL (08:00 HST Sat May 1 to "
            "release 11:30 HST Sat May 8, more than 168 h) and a station with no longitude on file may be more than 60 "
            "deg away: 56 consecutive hours, holding three physiological nights (? XYZ has no longitude on file); "
            "24:30 free: ? SHORT of 56:00 if it applies.") in t["lines"]


def test_a_return_home_inside_a_span_not_on_file_keeps_the_56_h_rest():
    """Review round 4, fix 1 (R4-3 of the rules review, R4-4 of the code review): the duty before the report ended away
    from HNL and the return home falls inside a span of the line not on file. By hand: HNL-SIN report 08:00 HST Apr 1,
    SIN-NRT Apr 4, NRT-SIN Apr 6 (in 16:00 HST, release 16:30, customs); a span not on file Apr 7 12:00 HST to Apr 9
    00:00; HNL-LAX reporting 12:00 HST Apr 10. Away from 08:00 Apr 1 to at least 12:00 Apr 7 (148:00: no duty on file
    took him home before the span) and at most 00:00 Apr 9 (184:00): it may be more than 168 h, and SIN is 98 deg from
    HNL. The rest at home is at least 36:00 (since the span ended) and at most 72:00 (since it began): '?', never short
    (round 4: no 56 h line, the FAR rest 'met'). Reporting 08:00 HST Apr 11: at least 56:00, holding the 0100-0700 HNL
    nights of Apr 9, 10 and 11: met. A span Apr 6 20:00 to Apr 7 08:00 instead (away at most 144:00): no 56 h line."""
    ds = [_duty(at(2027, 4, 1, "08:00"), _leg("HNL", "SIN", at(2027, 4, 1, "09:00"), at(2027, 4, 1, "19:30"), "1")),
          _duty(at(2027, 4, 4, "08:00"), _leg("SIN", "NRT", at(2027, 4, 4, "09:00"), at(2027, 4, 4, "16:00"), "2")),
          _duty(at(2027, 4, 6, "08:00"), _leg("NRT", "SIN", at(2027, 4, 6, "09:00"), at(2027, 4, 6, "16:00"), "3"))]
    unk = [(at(2027, 4, 7, "12:00"), at(2027, 4, 9, "00:00"))]
    t = TO.duty_timeout(ds + [_lax(at(2027, 4, 10, "12:00"))], 3, 2, "roster", "332", unknown=unk)
    assert (t["rest"]["ok"], t["rest"]["free"]) == (None, "36:00") and "need" not in t["rest"]
    assert "rest" not in t["flags"] and "rest_q" in t["flags"]
    assert ("Rest on return to home base (FAR 117.25(d), FOM 4.3.2.11): 148:00 to 184:00 away from HNL (08:00 HST Thu "
            "Apr 1 to a return home inside a span of your line not on file, 12:00 HST Wed Apr 7 to 00:00 HST Fri Apr "
            "9; it may be more than 168 h) and SIN is 98 deg from HNL (more than 60): 56 consecutive hours, holding "
            "three physiological nights (? its return home is not on file); at least 36:00 free (since the end of a "
            "span of your line not on file; at most 72:00, since that span began): ? not known: met only if its return "
            "home came early in the span not on file (at most 72:00) and if it applies.") in t["lines"]
    t = TO.duty_timeout(ds + [_lax(at(2027, 4, 11, "08:00"))], 3, 2, "roster", "332", unknown=unk)
    assert t["rest"]["ok"] is True and any("FAR 117.25(d)" in s and s.endswith("at most 92:00, since that span began): "
                                                                               "met (3 physiological nights, 0100-0700 "
                                                                               "HNL).") for s in t["lines"])
    t = TO.duty_timeout(ds + [_lax(at(2027, 4, 7, "20:00"))], 3, 2, "roster", "332",
                        unknown=[(at(2027, 4, 6, "20:00"), at(2027, 4, 7, "08:00"))])
    assert not any("117.25(d)" in s for s in t["lines"])


def test_the_deadhead_reading_keeps_its_question_when_2_x_the_duty_period_is_not_known():
    """Review round 4, fix 1 (R4-2 of the rules review): as for any grouping that holds a Mixed Flying Duty Period, the
    deadhead reading's 10.E.3.a table is no sure 'met' while 2 x the preceding Duty Period (10.E.1.a.1) is not known
    (round 3's '?' kept; it never makes a rest short). By hand:
    - one grouping, 3 pilots: DH LIH-HNL 07:00-07:35, HNL-LAX 09:00-14:15 (report 06:00 HST Apr 5, release 14:30); a
      span not on file Apr 5 15:00-17:00 HST; LAX-HNL reporting 05:30 HST Apr 6: at least 12:30 free. 10.E.1.a.1 is
      judged across the span (review round 4, fix 2, RV-5): 2 x 8:30 = 17:00, and 15:00 since that release: '? SHORT
      of 17:00 if the span was free from duty'; if LIH-HNL is the grouping's interisland Segment, 10.E.3.a's table
      needs 9:00 for the 1 landing (HNL-LAX): met by 3:30, but the table alone is not sure: '?', the "Rest ?" chip
      (round 4 gave no PWA rest verdict and no chip). With no span: 15:00 of 2 x 8:30 = 17:00, SHORT. Review round 5
      (F2V-2): 10.E.1.a.1 is judged across the span, so the deadhead reading's table, met by 3:30 (over the 2:30 van
      rides), adds no '?' of its own and no line; the rest stays a '?' on 10.E.1.a.1. Review round 5, fix 1 (R5V-3,
      R5V-4): the span starts 0:30 after the release, inside a 10.E rest, so a call-back in it makes one Duty Period
      from 06:00 to the span's end 17:00 (10.F.1): 11:00, 2 x = 22:00 is named; "(from that release)" says how the
      2:30 is measured;
    - one grouping, 2 pilots: HNL-LAX 07:00-12:15, LAX-OGG 13:30-18:45, DH OGG-LIH 19:30-20:10 (report 06:00 HST Apr
      5, release 20:25); a span Apr 5 21:00-22:00; LIH-HNL (all interisland) reporting 12:00 HST Apr 6: at least 14:00
      free, 10.E.2.b's 9:00 met by 5:00; with OGG-LIH as its interisland Segment the grouping is Mixed Flying and 2 x
      the Duty Period is not known: '?'. Review round 5 (F2V-1): the duty before it is on file, so 2 x its Duty Period
      is judged across the span: 06:00 to 20:25 = 14:25, 2 x = 28:50; 15:35 since that release: '? not known: SHORT of
      28:50 if the span was free from duty', other 28:50 (10.E.1.a.1) (round 4: "not known (the duty before it is not on
      file)"). Review round 5, fix 1 (R5V-3): the span starts 0:35 after the release, so a call-back in it makes one
      Duty Period from 06:00 to its end 22:00 (10.F.1): 16:00, 2 x = 32:00, named too."""
    k = "H3997|2027-04-05"
    d0 = _kd(k, at(2027, 4, 5, "06:00"),
             _leg("LIH", "HNL", at(2027, 4, 5, "07:00"), at(2027, 4, 5, "07:35"), "1", dh=True),
             _leg("HNL", "LAX", at(2027, 4, 5, "09:00"), at(2027, 4, 5, "14:15"), "2"))
    rep = at(2027, 4, 6, "05:30")
    o = rep + timedelta(minutes=75)
    d1 = _kd(k, rep, _leg("LAX", "HNL", o, o + timedelta(minutes=345), "3"))
    t = TO.duty_timeout([d0, d1], 1, 3, "roster", "332", unknown=[(at(2027, 4, 5, "15:00"), at(2027, 4, 5, "17:00"))])
    r = t["pwa"]["rest"]
    assert (r["need"], r["have"], r["ok"], r["cite"]) == ("17:00", "12:30", None, "10.E.1.a.1")
    # review round 5, fix 2 (UI6-4): across a span not on file the PWA row says "at least", as the FAR row does
    assert "rest_q" in t["flags"] and "rest at least 12:30, 17:00 needed (10.E.1.a.1): ?" in t["pwa"]["txt"]
    assert not any(s.startswith("PWA rest before this duty") for s in t["not_checked"])
    assert ("PWA rest before this duty (10.E.1.a.1): out of domicile, 2 x the preceding Duty Period across a span of "
            "your line not on file: the duty before it on file 8:30 (06:00 HST Mon Apr 5 to release 14:30 HST Mon "
            "Apr 5), 2 x = 17:00; a duty inside the span (from that release) at most 2:30, 2 x = 5:00; called back "
            "inside the span with less time off than a 10.E rest, one Duty Period from its report to the span's end "
            "(10.F.1) at most 11:00, 2 x = 22:00; at least 12:30 free (a span of your line before it is not on file): "
            "? not known: SHORT of 17:00 if the span was free from duty (15:00 since that release).") in t["lines"]
    # review round 5 (F2V-2): the table is met with the van rides spare, so the reading adds no '?' line (round 4 did)
    assert not any(s.startswith("? PWA rest, the deadhead reading") for s in t["lines"])
    t = TO.duty_timeout([d0, d1], 1, 3, "roster", "332")
    r = t["pwa"]["rest"]
    assert (r["need"], r["have"], r["ok"], r["cite"]) == ("17:00", "15:00", False, "10.E.1.a.1")
    k = "H3998|2027-04-05"
    d0 = _kd(k, at(2027, 4, 5, "06:00"), _leg("HNL", "LAX", at(2027, 4, 5, "07:00"), at(2027, 4, 5, "12:15"), "1"),
             _leg("LAX", "OGG", at(2027, 4, 5, "13:30"), at(2027, 4, 5, "18:45"), "2"),
             _leg("OGG", "LIH", at(2027, 4, 5, "19:30"), at(2027, 4, 5, "20:10"), "3", dh=True))
    rep = at(2027, 4, 6, "12:00")
    o = rep + timedelta(minutes=75)
    d1 = _kd(k, rep, _leg("LIH", "HNL", o, o + timedelta(minutes=35), "4"))
    t = TO.duty_timeout([d0, d1], 1, 2, "roster", "332", unknown=[(at(2027, 4, 5, "21:00"), at(2027, 4, 5, "22:00"))])
    r = t["pwa"]["rest"]
    assert (r["need"], r["have"], r["ok"], r["cite"]) == ("9:00", "14:00", None, "10.E.2.b") and "rest_q" in t["flags"]
    # review round 5 (F2V-1): judged across the span (round 4: "is not known (the duty before it is not on file)")
    assert r["other"] == "28:50 (10.E.1.a.1)"
    assert ("? PWA rest, the deadhead reading (10.E.3.a): if the interisland deadhead OGG-LIH is its interisland "
            "Segment (2.A.45, 2.A.62), this grouping holds a Mixed Flying Duty Period, and 10.E.3.a's table alone is "
            "not sure until Ryan confirms it replaces 10.E.1.a.1: 2 x the preceding Duty Period across a span of your "
            "line not on file: the duty before it on file 14:25 (06:00 HST Mon Apr 5 to release 20:25 HST Mon Apr 5), "
            "2 x = 28:50; a duty inside the span (from that release) at most 1:35, 2 x = 3:10; called back inside the "
            "span with less time off than a 10.E rest, one Duty Period from its report to the span's end (10.F.1) at "
            "most 16:00, 2 x = 32:00; at least 14:00 free (a span of your line before it is not on file): ? not known: "
            "SHORT of 28:50 if the span was free from duty (15:35 since that release).") in t["lines"]


def test_the_van_rides_are_judged_against_the_whole_groupings_landings_need():
    """Review round 4, fix 1 (LOGIC-R4-2; mutant M10): 10.E.3.a's need for the whole grouping's landings on file, when
    it is the larger, is the one the two van rides (VAN_RIDES, 2:30) are judged against. By hand, 3 pilots, one
    grouping: DH LIH-HNL and HNL-LAX (report 06:00 HST Apr 5, release 14:30), LAX-SFO (report 10:30 HST Apr 6, out
    11:45, in 13:15, release 13:30: a 3:00 Duty Period, 2 x = 6:00), then six SFO-LAX-SFO legs of 1:00. Landings before
    this rest 2 (9:00), in the whole grouping 8 (11:00). The deadhead reading's '?': 12:30 after the release meets
    11:00 by 1:30 only, under 2:30: '?' (round 4: met, judged on 9:00); 13:30: 2:30 spare, met; 10:30: '? met for those
    landings; the 8 landings of the whole grouping on file would need 11:00'."""
    k = "H3996|2027-04-05"
    d1 = _kd(k, at(2027, 4, 5, "06:00"),
             _leg("LIH", "HNL", at(2027, 4, 5, "07:00"), at(2027, 4, 5, "07:35"), "1", dh=True),
             _leg("HNL", "LAX", at(2027, 4, 5, "09:00"), at(2027, 4, 5, "14:15"), "2"))
    d2 = _kd(k, at(2027, 4, 6, "10:30"), _leg("LAX", "SFO", at(2027, 4, 6, "11:45"), at(2027, 4, 6, "13:15"), "3"))

    def d3(rest_m):
        rep = at(2027, 4, 6, "13:30") + timedelta(minutes=rest_m)
        legs, o = [], rep + timedelta(minutes=75)
        for j, (a, b) in enumerate([("SFO", "LAX"), ("LAX", "SFO")] * 3):
            legs.append(_leg(a, b, o, o + timedelta(minutes=60), str(10 + j)))
            o += timedelta(minutes=100)
        return _kd(k, rep, *legs)
    t = TO.duty_timeout([d1, d2, d3(750)], 2, 3, "roster", "332")
    r = t["pwa"]["rest"]
    assert (r["need"], r["have"], r["ok"], r["other"]) == ("6:00", "12:30", None, "11:00 (10.E.3.a)")
    assert "rest_q" in t["flags"] and "pwa_rest" not in t["flags"]
    assert any(s.startswith("? PWA rest, the deadhead reading (10.E.3.a)") and ": ? met by 1:30 from release to report "
               "for the 8 landings of the whole grouping on file (11:00), but the hotel time" in s for s in t["lines"])
    t = TO.duty_timeout([d1, d2, d3(810)], 2, 3, "roster", "332")
    assert t["pwa"]["rest"]["ok"] is True and "rest_q" not in t["flags"]
    t = TO.duty_timeout([d1, d2, d3(630)], 2, 3, "roster", "332")
    assert t["pwa"]["rest"]["ok"] is None and any(
        s.startswith("? PWA rest, the deadhead reading (10.E.3.a)") and ": ? met for those landings; the 8 landings of "
        "the whole grouping on file would need 11:00." in s for s in t["lines"])


# ------------------------------------------------------------ review round 4, fix 2 (the round-4 verifiers' findings)
def _sin_nrt():
    """HNL-SIN report 08:00 HST Apr 1, SIN-NRT Apr 4, NRT-SIN Apr 6 (in 16:00 HST, release 16:30, customs)."""
    return [_duty(at(2027, 4, 1, "08:00"), _leg("HNL", "SIN", at(2027, 4, 1, "09:00"), at(2027, 4, 1, "19:30"), "1")),
            _duty(at(2027, 4, 4, "08:00"), _leg("SIN", "NRT", at(2027, 4, 4, "09:00"), at(2027, 4, 4, "16:00"), "2")),
            _duty(at(2027, 4, 6, "08:00"), _leg("NRT", "SIN", at(2027, 4, 6, "09:00"), at(2027, 4, 6, "16:00"), "3"))]


def test_the_longer_far_rests_keep_the_rest_class_alternatives_and_the_payload_is_json():
    """Review round 4, fix 2 (RV-1, C1): round 4's FAR rest loop unpacked into `alt`, the name of the rest-class
    alternatives published as fdp.alt, so a 117.25(g) or (d) line turned fdp.alt into [] and the not-home 117.25(d)
    line into [timedelta, str], which json.dumps (watcher.pub) refused: the Working Flight sensor kept a stale last out.
    By hand, 3 pilots, A330 (Class 1):
    - the SIN-HNL deadhead (_dh_sin, release 21:30 HST Apr 8, 15:00 needed), HNL-LAX reporting 10:30 HST Apr 9:
      acclimated to HNL (back in its theater), Table C row 0700-1259 (HNL time 10:30): Class 2 16:30, Class 3 15:00, so
      the alternatives end 03:00 and 01:30 HST; the 13:00 free is SHORT of 15:00 (117.25(g));
    - the HNL-SIN-NRT-SIN trip (_sin_nrt), a span not on file Apr 7 12:00 HST to Apr 9 00:00, HNL-LAX reporting 12:00
      HST Apr 10: 36:00 free since the span acclimates to HNL, row 0700-1259 (HNL 12:00): Class 2 04:30, Class 3 03:00
      HST; the 56 h rest across the span is a '?'."""
    t = TO.duty_timeout(_dh_sin() + [_lax(at(2027, 4, 9, "10:30"))], 2, 3, "roster", "332")
    assert t["fdp"]["alt"] == {"2": "03:00 HST", "3": "01:30 HST"} and "rest" in t["flags"]
    assert any(s.startswith("Rest after deadhead transportation (FAR 117.25(g)") for s in t["lines"])
    assert json.loads(json.dumps(t))["fdp"]["alt"] == {"2": "03:00 HST", "3": "01:30 HST"}
    t = TO.duty_timeout(_sin_nrt() + [_lax(at(2027, 4, 10, "12:00"))], 3, 3, "roster", "332",
                        unknown=[(at(2027, 4, 7, "12:00"), at(2027, 4, 9, "00:00"))])
    assert t["fdp"]["alt"] == {"2": "04:30 HST", "3": "03:00 HST"} and t["rest"]["ok"] is None
    assert any(s.startswith("Rest on return to home base (FAR 117.25(d)") and "a return home inside a span" in s
               for s in t["lines"])
    assert json.loads(json.dumps(t))["fdp"]["alt"] == {"2": "04:30 HST", "3": "03:00 HST"}


def test_a_span_not_on_file_inside_the_trip_may_hide_more_than_60_degrees():
    """Review round 4, fix 2 (RV-3): the spread of 60 degrees or less on file says nothing of the stations of a span of
    the line not on file inside the trip (or holding its return home, or before its start): 117.25(d) is then a '?',
    never short. By hand: HNL-LAX report 08:00 HST Apr 1 (LAX 39.5 deg from HNL), a span not on file Apr 2 12:00 to
    Apr 6 12:00 HST, LAX-HNL in 12:00 HST Apr 8, release 12:15: 172:15 away, more than 168 h; HNL-LAX reporting 12:15
    HST Apr 9: 24:00 free: '? SHORT of 56:00 if it applies' (round 4: no 56 h line, the rest met); with no span, no
    line. The SIN trip (_sin_trip, 177:00 away, 98 deg) with a span Apr 3 00:00-12:00 inside it: he may have been home,
    so '?' too (mutant V19: a sure SHORT)."""
    d0 = _duty(at(2027, 4, 1, "08:00"), _leg("HNL", "LAX", at(2027, 4, 1, "09:00"), at(2027, 4, 1, "14:15"), "1"))
    d1 = _duty(at(2027, 4, 8, "06:00"), _leg("LAX", "HNL", at(2027, 4, 8, "07:00"), at(2027, 4, 8, "12:00"), "2"))
    t = TO.duty_timeout([d0, d1, _lax(at(2027, 4, 9, "12:15"))], 2, 2, "roster", "332",
                        unknown=[(at(2027, 4, 2, "12:00"), at(2027, 4, 6, "12:00"))])
    assert (t["rest"]["ok"], t["rest"]["free"], t["rest"]["cite"]) == (None, "24:00", "FAR 117.25(d)")
    assert "rest" not in t["flags"] and "rest_q" in t["flags"] and "need" not in t["rest"]
    assert ("Rest on return to home base (FAR 117.25(d), FOM 4.3.2.11): 172:15 away from HNL (08:00 HST Thu Apr 1 to "
            "release 12:15 HST Thu Apr 8, more than 168 h) and a station in a span of your line not on file may be "
            "more than 60 deg away: 56 consecutive hours, holding three physiological nights (? a span of your line "
            "inside the trip is not on file (you may have been home); the stations of a span of your line not on file "
            "are not known (those on file: LAX is 39.5 deg from HNL)); 24:00 free: ? SHORT of 56:00 if it "
            "applies.") in t["lines"]
    t = TO.duty_timeout([d0, d1, _lax(at(2027, 4, 9, "12:15"))], 2, 2, "roster", "332")
    assert t["rest"]["ok"] is True and not any("117.25(d)" in s for s in t["lines"])
    t = TO.duty_timeout(_sin_trip() + [_lax(at(2027, 4, 10, "08:00"))], 2, 2, "roster", "332",
                        unknown=[(at(2027, 4, 3, "00:00"), at(2027, 4, 3, "12:00"))])
    assert (t["rest"]["ok"], t["rest"]["free"]) == (None, "39:00") and "rest" not in t["flags"]
    assert any(s.startswith("Rest on return to home base (FAR 117.25(d)") and "SIN is 98 deg from HNL" in s
               and "(? a span of your line inside the trip is not on file (you may have been home))" in s
               and s.endswith("39:00 free: ? SHORT of 56:00 if it applies.") for s in t["lines"])


def test_the_56_h_rest_counts_the_nights_of_the_most_it_may_be_across_a_span_not_on_file():
    """Review round 4, fix 2 (RV-4): the words of a '?' across a span not on file count the physiological nights of
    the rest at most too. By hand: _sin_nrt (release 16:30 HST Apr 6), a span not on file Apr 7 07:30 to Apr 8 12:00
    HST holding the return home: away from 08:00 HST Apr 1 to at least 07:30 Apr 7 (143:30) and at most 12:00 Apr 8
    (172:00), SIN 98 deg; HNL-LAX reporting 15:30 HST Apr 9: at least 27:30 at home (since the span ended), at most
    56:00 (since it began), which holds only the 0100-0700 HNL nights of Apr 8 and 9: a '?' even then."""
    t = TO.duty_timeout(_sin_nrt() + [_lax(at(2027, 4, 9, "15:30"))], 3, 2, "roster", "332",
                        unknown=[(at(2027, 4, 7, "07:30"), at(2027, 4, 8, "12:00"))])
    assert (t["rest"]["ok"], t["rest"]["free"]) == (None, "27:30") and "rest" not in t["flags"]
    assert any(s.startswith("Rest on return to home base (FAR 117.25(d), FOM 4.3.2.11): 143:30 to 172:00 away") and
               s.endswith("at least 27:30 free (since the end of a span of your line not on file; at most 56:00, since "
                          "that span began): ? not known: met only if its return home came early in the span not on "
                          "file (at most 56:00, but it holds only 2 of the three physiological nights, 0100-0700 HNL: "
                          "a '?' even then) and if it applies.") for s in t["lines"])


def _lh(rep):
    """LAX-HNL reporting rep, out 1:15 later, block 5:45."""
    o = rep + timedelta(minutes=75)
    return _duty(rep, _leg("LAX", "HNL", o, o + timedelta(minutes=345), "2"))


def test_2_x_the_duty_period_is_judged_across_a_span_not_on_file_and_never_short():
    """Review round 4, fix 2 (RV-5): with a span of the line not on file after the duty before it, 10.E.1.a.1 was only
    listed as not checked (no verdict, no chip), though the rest is at most release to report. Now 2 x the duty
    before's Duty Period is judged: met only when the rest since the span ended meets 2 x the longer of that Duty
    Period and the span (a duty inside it is no longer), else a '?'. By hand, 3 pilots: HNL-LAX report 06:00 HST Apr 5,
    in 14:15, release 14:30 (Duty Period 8:30, 2 x = 17:00); a span Apr 5 15:00-17:00 (a duty inside it at most 2:30,
    2 x = 5:00); LAX-HNL reporting 05:30 HST Apr 6: at least 12:30, at most 15:00: '? SHORT of 17:00 if the span was
    free from duty', the "Rest ?" chip (with no span: 15:00 of 17:00, SHORT); 12:30 HST Apr 6: 19:30 meets 17:00 by
    2:30: met; 12:29: 2:29 spare, under the 2:30 van rides: '?'. A span Apr 5 10:00-15:00 after a 3:00 duty (06:00 to
    release 09:00, 2 x = 6:00; a duty in the span at most 6:00, 2 x = 12:00), LAX-HNL reporting 23:00 HST Apr 5: at
    least 8:00, 14:00 since that release: '? met only if no duty in the span needs more'. Review round 5, fix 1
    (R5V-3, PWA 10.F.1): the span starts 0:30 after the 14:30 release, inside a 10.E rest (2 x 8:30 = 17:00), so a
    call-back in it makes one Duty Period from 06:00 to the span's end 17:00: 11:00, 2 x = 22:00 is the sure need:
    12:30 HST Apr 6 (19:30 since the span) is now '? met only if no duty in the span needs more (22:00 since that
    release)'; 17:30 HST Apr 6: 24:30 meets 22:00 by 2:30: met; 17:29: '?' (the van rides)."""
    d0 = _duty(at(2027, 4, 5, "06:00"), _leg("HNL", "LAX", at(2027, 4, 5, "07:00"), at(2027, 4, 5, "14:15"), "1"))
    u = [(at(2027, 4, 5, "15:00"), at(2027, 4, 5, "17:00"))]
    t = TO.duty_timeout([d0, _lh(at(2027, 4, 6, "05:30"))], 1, 3, "roster", "332", unknown=u)
    r = t["pwa"]["rest"]
    assert (r["need"], r["have"], r["ok"], r["cite"]) == ("17:00", "12:30", None, "10.E.1.a.1")
    assert "rest_q" in t["flags"] and "pwa_rest" not in t["flags"]
    assert not any(s.startswith("PWA rest before this duty") for s in t["not_checked"])
    assert ("PWA rest before this duty (10.E.1.a.1): out of domicile, 2 x the preceding Duty Period across a span of "
            "your line not on file: the duty before it on file 8:30 (06:00 HST Mon Apr 5 to release 14:30 HST Mon "
            "Apr 5), 2 x = 17:00; a duty inside the span (from that release) at most 2:30, 2 x = 5:00; called back "
            "inside the span with less time off than a 10.E rest, one Duty Period from its report to the span's end "
            "(10.F.1) at most 11:00, 2 x = 22:00; at least 12:30 free (a span of your line before it is not on file): "
            "? not known: SHORT of 17:00 if the span was free from duty (15:00 since that release).") in t["lines"]
    t = TO.duty_timeout([d0, _lh(at(2027, 4, 6, "05:30"))], 1, 3, "roster", "332")
    assert t["pwa"]["rest"]["ok"] is False and "pwa_rest" in t["flags"]
    # review round 5, fix 1 (R5V-3): a call-back inside the span (10.F.1) may make 06:00-17:00 one Duty Period
    t = TO.duty_timeout([d0, _lh(at(2027, 4, 6, "12:30"))], 1, 3, "roster", "332", unknown=u)
    assert t["pwa"]["rest"]["ok"] is None and t["flags"] == ["rest_q"] and any(
        s.startswith("PWA rest before this duty (10.E.1.a.1)") and s.endswith(
            "? not known: met only if no duty in the span needs more (22:00 since that release).") for s in t["lines"])
    t = TO.duty_timeout([d0, _lh(at(2027, 4, 6, "17:30"))], 1, 3, "roster", "332", unknown=u)
    assert t["pwa"]["rest"]["ok"] is True and t["flags"] == [] and any(
        s.startswith("PWA rest before this duty (10.E.1.a.1)") and s.endswith(": met, 2:30 spare.") for s in t["lines"])
    t = TO.duty_timeout([d0, _lh(at(2027, 4, 6, "17:29"))], 1, 3, "roster", "332", unknown=u)
    assert t["pwa"]["rest"]["ok"] is None and t["flags"] == ["rest_q"]
    d0 = _duty(at(2027, 4, 5, "06:00"), _leg("HNL", "LAX", at(2027, 4, 5, "06:30"), at(2027, 4, 5, "08:45"), "1"))
    t = TO.duty_timeout([d0, _lh(at(2027, 4, 5, "23:00"))], 1, 3, "roster", "332",
                        unknown=[(at(2027, 4, 5, "10:00"), at(2027, 4, 5, "15:00"))])
    r = t["pwa"]["rest"]
    assert (r["need"], r["have"], r["ok"]) == ("6:00", "8:00", None) and any(
        s.startswith("PWA rest before this duty (10.E.1.a.1)") and "a duty inside the span (from that release) at most "
        "6:00, 2 x = 12:00" in s and "(10.F.1) at most 9:00, 2 x = 18:00"
        in s and s.endswith("? not known: met only if no duty in the span needs more (14:00 since that release).")
        for s in t["lines"])


def _oh(rep):
    """OGG-HNL reporting rep, out 1:00 later, block 0:40 (all interisland flying)."""
    return _duty(rep, _leg("OGG", "HNL", rep + timedelta(hours=1), rep + timedelta(hours=1, minutes=40), "4"))


def test_10e1a1_on_top_of_10e2b_is_judged_when_2_x_the_duty_period_is_not_known():
    """Review round 4, fix 2 (C2): R4-5's reading (2 x the preceding Duty Period, 10.E.1.a.1, on top of 10.E.2.b's
    9:00 before an all-interisland duty away) vanished when 2 x the Duty Period was not known: a '?' became a sure
    'met'. By hand, 2 pilots: HNL-LIH, LIH-HNL, HNL-OGG (report 06:00 HST Apr 5, in 12:45, release 13:00: Duty Period
    7:00, 2 x = 14:00), OGG-HNL reporting 02:00 HST Apr 6: on file, 9:00 met by 4:00, 13:00 of 14:00 a '?' (10.E.1.a.2,
    2 pilots); a 10 min span not on file after the release (13:00-13:10): at least 12:50, at most 13:00 since the
    release: '? not known: SHORT of 14:00 if the span was free from duty', other 14:00 (round 4: met, no chip);
    reporting 05:40: 16:30 meets 2 x the longer of 7:00 and the span (14:00) by 2:30: met. With no duty before it on
    file (the line known since Mar 1): '?', 2 x the preceding Duty Period not known. Review round 5, fix 1 (R5V-3, PWA
    10.F.1): a call-back in the span (it starts at the release) makes one Duty Period 06:00-13:10, 7:10, 2 x = 14:20:
    05:40 meets it by 2:10, under the van rides: '?'; 06:00 (16:50) by 2:30: met."""
    d0 = _duty(at(2027, 4, 5, "06:00"), _leg("HNL", "LIH", at(2027, 4, 5, "07:00"), at(2027, 4, 5, "07:40"), "1"),
               _leg("LIH", "HNL", at(2027, 4, 5, "08:30"), at(2027, 4, 5, "09:10"), "2"),
               _leg("HNL", "OGG", at(2027, 4, 5, "12:00"), at(2027, 4, 5, "12:45"), "3"))
    u = [(at(2027, 4, 5, "13:00"), at(2027, 4, 5, "13:10"))]
    t = TO.duty_timeout([d0, _oh(at(2027, 4, 6, "02:00"))], 1, 2, "roster", "332")
    r = t["pwa"]["rest"]
    assert (r["need"], r["ok"], r["cite"], r["other"]) == ("9:00", None, "10.E.2.b", "14:00 (10.E.1.a.1)")
    t = TO.duty_timeout([d0, _oh(at(2027, 4, 6, "02:00"))], 1, 2, "roster", "332", unknown=u)
    r = t["pwa"]["rest"]
    assert (r["need"], r["have"], r["ok"], r["cite"], r["other"]) == ("9:00", "12:50", None, "10.E.2.b",
                                                                      "14:00 (10.E.1.a.1)")
    assert t["flags"] == ["rest_q"]
    assert ("? PWA rest, the other reading (10.E.1.a.1): as an International Pilot too (2.A.38: 10.E.1.a.1 on top of "
            "10.E.2.b, as 10.E.2.a is on top of 10.E.1.a at home; to confirm): 2 x the preceding Duty Period across a "
            "span of your line not on file: the duty before it on file 7:00 (06:00 HST Mon Apr 5 to release 13:00 HST "
            "Mon Apr 5), 2 x = 14:00; a duty inside the span (from that release) at most 0:10, 2 x = 0:20; called "
            "back inside the span with less time off than a 10.E rest, one Duty Period from its report to the span's "
            "end (10.F.1) at most 7:10, 2 x = 14:20; at least 12:50 free (a span of your line before it is not on "
            "file): ? not known: SHORT of 14:00 if the span was free from duty (13:00 since that release). The "
            "readings disagree, so the rest is not sure.") in t["lines"]
    # review round 5, fix 1 (R5V-3): 2 x 7:10 (10.F.1) = 14:20 with the 2:30 van rides: 05:40 is short of them by 0:20
    t = TO.duty_timeout([d0, _oh(at(2027, 4, 6, "05:40"))], 1, 2, "roster", "332", unknown=u)
    assert t["pwa"]["rest"]["ok"] is None and t["flags"] == ["rest_q"]
    t = TO.duty_timeout([d0, _oh(at(2027, 4, 6, "06:00"))], 1, 2, "roster", "332", unknown=u)
    assert t["pwa"]["rest"]["ok"] is True and "other" not in t["pwa"]["rest"] and t["flags"] == []
    t = TO.duty_timeout([_oh(at(2027, 4, 6, "02:00"))], 0, 2, "roster", "332", known_from=at(2027, 3, 1, "00:00"))
    assert t["pwa"]["rest"]["ok"] is None and ("? PWA rest, the other reading (10.E.1.a.1): as an International Pilot "
                                               "too (2.A.38: 10.E.1.a.1 on top of 10.E.2.b; to confirm): 2 x the "
                                               "preceding Duty Period is not known (the duty before it is not on "
                                               "file). The readings disagree, so the rest is not sure.") in t["lines"]


def test_a_three_segment_deadhead_takes_its_own_table_b_column_and_is_no_international_flying():
    """Review round 4, fix 2 (C3 mutant V8; C4 (b)). By hand, 2 pilots: deadheads HNL-OGG 09:00-09:40, OGG-HNL
    15:00-15:40, HNL-LIH 20:50-21:30 HST Apr 5 (report 08:00, acclimated to HNL), 3 segments: Table B row 0700-1159,
    13:00 for 3 segments (14:00 for 1, the most for 3 on any row 13:00); report to block-in 13:30 is over every row for
    3 segments: sure, 13:30 needed. Release 21:45 (domestic); LIH-HNL reporting 10:00 HST Apr 6: 12:15 free, SHORT,
    flagged (mutant V8, one segment: 14:00, no line). PWA: 10.E.2.b's 9:00 met by 3:15; 2 x 13:45 = 27:30 on top of it
    is a '?' (10.E.1.a.2) labelled "as an International Pilot too": a deadhead is no flying, and the duty before it
    holds no flown leg outside the islands (round 4: "the duty before it being International flying")."""
    dh = _duty(at(2027, 4, 5, "08:00"),
               _leg("HNL", "OGG", at(2027, 4, 5, "09:00"), at(2027, 4, 5, "09:40"), "1", dh=True),
               _leg("OGG", "HNL", at(2027, 4, 5, "15:00"), at(2027, 4, 5, "15:40"), "2", dh=True),
               _leg("HNL", "LIH", at(2027, 4, 5, "20:50"), at(2027, 4, 5, "21:30"), "3", dh=True))
    rep = at(2027, 4, 6, "10:00")
    nx = _duty(rep, _leg("LIH", "HNL", rep + timedelta(hours=1), rep + timedelta(hours=1, minutes=40), "4"))
    t = TO.duty_timeout([dh, nx], 1, 2, "roster", "332")
    assert (t["rest"]["ok"], t["rest"]["need"], t["rest"]["free"]) == (False, "13:30", "12:15") and "rest" in t["flags"]
    assert t["rest"]["txt"] == "12:15 free, 13:30 needed (FAR 117.25(g)): SHORT"
    assert ("Rest after deadhead transportation (FAR 117.25(g), FOM 4.3.2.10): the duty before it was deadhead "
            "transportation only, 13:30 from its report to its last block-in, over its Table B FDP 13:00 (HNL time): a "
            "rest as long as the deadhead transportation (13:30, from the report), no less than 10 h; 12:15 free: "
            "SHORT, check with Crew Scheduling.") in t["lines"]
    assert t["pwa"]["rest"]["other"] == "27:30 (10.E.1.a.1)" and any(
        s.startswith("? PWA rest, the other reading (10.E.1.a.1): as an International Pilot too (2.A.38") for s in
        t["lines"])
    assert not any("being International flying" in s for s in t["lines"])


def test_the_deadhead_reading_names_the_whole_groupings_need_when_only_it_is_more():
    """Review round 4, fix 2 (C3 mutant V11; C4 (a)): the deadhead reading adds its '?' when the whole grouping's
    10.E.3.a need is more than 2 x the Duty Period although the need for the landings before the rest is not, and its
    words name that need. By hand, 3 pilots, one grouping: DH LIH-HNL and HNL-LAX (report 06:00 HST Apr 5), LAX-SFO-LAX
    (report 07:00 HST Apr 6, in 12:00, release 12:15: Duty Period 5:15, 2 x = 10:30), LAX-HNL reporting 01:15 HST Apr 7
    (13:00 free), then six interisland legs Apr 8. 3 landings before this rest: 9:00, not more than 10:30; the whole
    grouping's 10: 11:00, more; 13:00 meets it by 2:00 only, under the 2:30 van rides: '?', other 11:00 (mutant V11:
    met). 10.E.1.a.1 itself is met by 2:30. Reporting 01:45: 2:30 spare for 11:00: met."""
    k = "H3981|2027-04-05"
    d0 = _kd(k, at(2027, 4, 5, "06:00"),
             _leg("LIH", "HNL", at(2027, 4, 5, "07:00"), at(2027, 4, 5, "07:35"), "1", dh=True),
             _leg("HNL", "LAX", at(2027, 4, 5, "09:00"), at(2027, 4, 5, "14:15"), "2"))
    d1 = _kd(k, at(2027, 4, 6, "07:00"), _leg("LAX", "SFO", at(2027, 4, 6, "08:00"), at(2027, 4, 6, "09:30"), "3"),
             _leg("SFO", "LAX", at(2027, 4, 6, "10:30"), at(2027, 4, 6, "12:00"), "4"))
    r3, hops = at(2027, 4, 8, "06:00"), []
    for j, (a, b) in enumerate([("HNL", "OGG"), ("OGG", "HNL"), ("HNL", "KOA"), ("KOA", "HNL"), ("HNL", "LIH"),
                                ("LIH", "HNL")]):
        o = r3 + timedelta(hours=1, minutes=80 * j)
        hops.append(_leg(a, b, o, o + timedelta(minutes=40), str(10 + j)))
    d3 = _kd(k, r3, *hops)

    def d2(rep):
        return _kd(k, rep, _leg("LAX", "HNL", rep + timedelta(minutes=75), rep + timedelta(minutes=405), "5"))
    t = TO.duty_timeout([d0, d1, d2(at(2027, 4, 7, "01:15")), d3], 2, 3, "roster", "332")
    r = t["pwa"]["rest"]
    assert (r["need"], r["have"], r["ok"], r["cite"], r["other"]) == ("10:30", "13:00", None, "10.E.1.a.1",
                                                                      "11:00 (10.E.3.a)")
    assert t["flags"] == ["rest_q"]
    assert any(s.startswith("? PWA rest, the deadhead reading (10.E.3.a): if the interisland deadhead LIH-HNL is its "
                            "interisland Segment (2.A.45, 2.A.62), this grouping holds a Mixed Flying Duty Period and "
                            "10.E.3.a's table needs 9:00 for the 3 landings performed in it before this rest and 11:00 "
                            "for the 10 landings of the whole grouping on file, more than 10:30 (10.E.1.a.1): ? met by "
                            "2:00 from release to report for the 10 landings of the whole grouping on file (11:00)")
               for s in t["lines"])
    t = TO.duty_timeout([d0, d1, d2(at(2027, 4, 7, "01:45")), d3], 2, 3, "roster", "332")
    assert t["pwa"]["rest"]["ok"] is True and t["flags"] == []


def test_the_deadhead_reading_across_a_span_needs_the_whole_groupings_landings_and_never_at_home():
    """Review round 4, fix 2 (C3 mutants W15 and W6). By hand, 3 pilots, one grouping:
    - DH LIH-HNL and HNL-LAX (report 06:00 HST Apr 5), LAX-SFO (report 10:30 HST Apr 6, in 13:15, release 13:30: Duty
      Period 3:00, 2 x = 6:00), a span not on file Apr 6 14:00-15:00 (a duty in it at most 1:30, 2 x = 3:00), SFO-HNL
      reporting 01:00 HST Apr 7 (at least 10:00 free), five interisland legs Apr 8. 10.E.1.a.1 across the span: 6:00
      met by 4:00 (review round 5, fix 1, R5V-3: the span starts 0:30 after the release, so a call-back in it makes one
      Duty Period 10:30-15:00, 4:30, 2 x = 9:00, PWA 10.F.1: met by 1:00, under the van rides, a '?'). The deadhead
      reading: 2 landings before this rest, 9:00; the whole grouping's 8, 11:00: 10:00 meets 9:00 but not 11:00: '?',
      pwa.rest.need 11:00 (10.E.3.a) (mutant W15: 9:00);
    - at home: DH LIH-HNL and HNL-LAX, LAX-HNL (report 06:00 HST Apr 6, in 12:45, release 13:00), a span Apr 6
      13:30-18:00, HNL-SFO reporting 06:00 HST Apr 7: at least 12:00 free, 10.E.1.a's 11:00 met by 1:00, and the
      deadhead reading's '?' is for out of domicile only (mutant W6: '?')."""
    k = "H3982|2027-04-05"
    e0 = _kd(k, at(2027, 4, 5, "06:00"),
             _leg("LIH", "HNL", at(2027, 4, 5, "07:00"), at(2027, 4, 5, "07:35"), "1", dh=True),
             _leg("HNL", "LAX", at(2027, 4, 5, "09:00"), at(2027, 4, 5, "14:15"), "2"))
    e1 = _kd(k, at(2027, 4, 6, "10:30"), _leg("LAX", "SFO", at(2027, 4, 6, "11:45"), at(2027, 4, 6, "13:15"), "3"))
    rep = at(2027, 4, 7, "01:00")
    e2 = _kd(k, rep, _leg("SFO", "HNL", rep + timedelta(minutes=75), rep + timedelta(minutes=405), "4"))
    r4, hops = at(2027, 4, 8, "06:00"), []
    for j, (a, b) in enumerate([("HNL", "OGG"), ("OGG", "HNL"), ("HNL", "KOA"), ("KOA", "HNL"), ("HNL", "LIH")]):
        o = r4 + timedelta(hours=1, minutes=80 * j)
        hops.append(_leg(a, b, o, o + timedelta(minutes=40), str(10 + j)))
    t = TO.duty_timeout([e0, e1, e2, _kd(k, r4, *hops)], 2, 3, "roster", "332",
                        unknown=[(at(2027, 4, 6, "14:00"), at(2027, 4, 6, "15:00"))])
    r = t["pwa"]["rest"]
    assert (r["need"], r["have"], r["ok"], r["cite"]) == ("11:00", "10:00", None, "10.E.3.a") and "rest_q" in t["flags"]
    # review round 5, fix 1 (R5V-3): 2 x 4:30 (10.F.1) = 9:00, met by 1:00 since the span ended, under the van rides
    assert any(s.startswith("PWA rest before this duty (10.E.1.a.1)") and s.endswith(
        ": ? met by 1:00 since the span of your line not on file ended, but the hotel time (door to door, 2.A.68.b, "
        "10.E.1.a.3) is shorter by the two van rides, which are not on the schedule (under 2:30 spare is not sure).")
        for s in t["lines"])
    assert any(s.startswith("? PWA rest, the deadhead reading (10.E.3.a)") and "? met for those landings; the 8 "
               "landings of the whole grouping on file would need 11:00." in s for s in t["lines"])
    k = "H3983|2027-04-05"
    f0 = _kd(k, at(2027, 4, 5, "06:00"),
             _leg("LIH", "HNL", at(2027, 4, 5, "07:00"), at(2027, 4, 5, "07:35"), "1", dh=True),
             _leg("HNL", "LAX", at(2027, 4, 5, "09:00"), at(2027, 4, 5, "14:15"), "2"))
    f1 = _kd(k, at(2027, 4, 6, "06:00"), _leg("LAX", "HNL", at(2027, 4, 6, "07:00"), at(2027, 4, 6, "12:45"), "3"))
    o = at(2027, 4, 7, "07:00")
    f2 = _kd(k, at(2027, 4, 7, "06:00"), _leg("HNL", "SFO", o, o + timedelta(minutes=315), "4"))
    t = TO.duty_timeout([f0, f1, f2], 2, 3, "roster", "332",
                        unknown=[(at(2027, 4, 6, "13:30"), at(2027, 4, 6, "18:00"))])
    r = t["pwa"]["rest"]
    assert (r["need"], r["have"], r["ok"], r["cite"]) == ("11:00", "12:00", True, "10.E.1.a") and "other" not in r
    assert t["pwa"]["mixed_grouping"] is True and not any(s.startswith("? PWA rest") for s in t["lines"])


def test_the_56_h_rest_boundaries_are_more_than_168_h_and_more_than_60_degrees(monkeypatch):
    """Review round 4, fix 2 (C3 mutants V10, W13): FAR 117.25(d) needs "more than 168 consecutive hours" away and
    travel of "more than 60 degrees longitude". By hand:
    - HNL-SIN report 08:00 HST Apr 1; SIN-HNL in 07:30 HST Apr 8, release 08:00 (customs): exactly 168:00 away, no 56 h
      rest; in 07:31, release 08:01: 168:01, and HNL-LAX reporting 08:00 HST Apr 9 has 23:59 of 56:00: SHORT;
    - a made-up station XQA at -97.9 (exactly 60.0 deg from HNL's -157.9): HNL-XQA report 08:00 HST Apr 1, XQA-HNL in
      16:30 Apr 8, release 17:00 (XQA's country not on file: customs), 177:00 away, HNL-LAX 08:00 HST Apr 10 (39:00):
      no 56 h rest; XQB at -97.8 (60.1 deg): SHORT."""
    for arr, ok in (("07:30", True), ("07:31", False)):
        h, m = map(int, arr.split(":"))
        ds = [_duty(at(2027, 4, 1, "08:00"), _leg("HNL", "SIN", at(2027, 4, 1, "09:00"), at(2027, 4, 1, "19:30"), "1")),
              _duty(at(2027, 4, 7, "21:00"), _leg("SIN", "HNL", at(2027, 4, 7, "22:00"),
                                                  at(2027, 4, 8, "00:00") + timedelta(hours=h, minutes=m), "2")),
              _lax(at(2027, 4, 9, "08:00"))]
        t = TO.duty_timeout(ds, 2, 2, "roster", "332")
        assert t["rest"]["ok"] is ok and any("117.25(d)" in s for s in t["lines"]) is (not ok), arr
    assert any(s.startswith("Rest on return to home base (FAR 117.25(d), FOM 4.3.2.11): 168:01 away from HNL") and
               s.endswith("23:59 free: SHORT, check with Crew Scheduling.") for s in t["lines"])
    for stn, lon, ok in (("XQA", -97.9, True), ("XQB", -97.8, False)):
        monkeypatch.setitem(TO.LON, stn, lon)
        ds = [_duty(at(2027, 4, 1, "08:00"), _leg("HNL", stn, at(2027, 4, 1, "09:00"), at(2027, 4, 1, "17:00"), "1")),
              _duty(at(2027, 4, 8, "06:00"), _leg(stn, "HNL", at(2027, 4, 8, "07:00"), at(2027, 4, 8, "16:30"), "2")),
              _lax(at(2027, 4, 10, "08:00"))]
        t = TO.duty_timeout(ds, 2, 2, "roster", "332")
        assert t["rest"]["ok"] is ok and any("117.25(d)" in s for s in t["lines"]) is (not ok), stn
    assert "Flag: short of FAR rest (FAR 117.25(d)): 39:00 of 56:00." in t["lines"] and any(
        "and XQB is 60.1 deg from HNL (more than 60)" in s for s in t["lines"])


def test_a_schedule_item_inside_the_pwa_rest_is_a_question_after_a_span_or_with_no_duty_before_it():
    """Review round 4, fix 2 (C5): judge() took a schedule item that may be duty (busy) only after a release on file.
    By hand, 2 pilots: HNL-LAX-HNL (report 06:00 HST Apr 5, in 18:45, release 19:00), a span not on file Apr 5
    20:00-Apr 6 00:00, a training day Apr 6 08:00-16:00 (busy), HNL-LAX reporting 07:00 HST Apr 7: at least 31:00 free,
    10.E.1.a's 11:00 '? a schedule item inside it may be duty' (round 4: met, 20:00 spare), as FAR 117.25(e). Review
    round 5 (RV5-3): for a fixed need only an item ending inside the need before the report counts: the training ends
    15:00 before it, so even as duty it leaves 15:00, more than FAR 117.25(e)'s 10 h, 10.E.1.a's 11:00 and the 12:00
    reading after the span (F2V-3: a duty inside it may be all interisland): FAR and PWA met, no chip (review round 5,
    fix 1, UI5-2: "met even if the schedule item ending 16:00 ... is duty", 4:00 spare from it for the 11:00, 5:00
    for the 10 h, and rest.txt and the PWA row say 15:00 after it). The same item
    Apr 6 16:00-21:00 (ending 10:00 before the report): FAR's 10 h met (it ends at the 10 h's start), 10.E.1.a's 11:00
    a '?' and the chip; ending 21:01: FAR a '?' too. With no duty on file before it (the line known since Mar 1) and an
    item Apr 6 20:00-20:45 HST, 10:15 to 11:00 before the report: FAR 117.25(e)'s 10 h is met, the PWA 11:00 is a '?'
    and the "Rest ?" chip shows."""
    g0 = _duty(at(2027, 4, 5, "06:00"), _leg("HNL", "LAX", at(2027, 4, 5, "07:00"), at(2027, 4, 5, "12:15"), "1"),
               _leg("LAX", "HNL", at(2027, 4, 5, "13:30"), at(2027, 4, 5, "18:45"), "2"))
    g1 = _lax(at(2027, 4, 7, "07:00"))
    u = [(at(2027, 4, 5, "20:00"), at(2027, 4, 6, "00:00"))]
    t = TO.duty_timeout([g0, g1], 1, 2, "roster", "332", unknown=u,
                        busy=[(at(2027, 4, 6, "08:00"), at(2027, 4, 6, "16:00"))])
    # review round 5 (RV5-3): the item ends 15:00 before the report, outside every fixed need here (round 4: '?');
    # review round 5, fix 1 (UI5-2): the sure margin is from the item's end (15:00 - 11:00 = 4:00, 15:00 - 10 h = 5:00)
    assert (t["pwa"]["rest"]["ok"], t["rest"]["ok"]) == (True, True) and t["flags"] == []
    assert ("PWA rest before this duty (10.E.1.a): in domicile, 11:00 needed; at least 31:00 free (a span of your line "
            "before it is not on file): met even if the schedule item ending 16:00 HST Tue Apr 6 (15:00 before the "
            "report) is duty, 4:00 spare from it.") in t["lines"]
    assert ("Rest before this FDP (FAR 117.25(e), FOM 4.3.2.7): 31:00 free from duty since the end of a span of your "
            "line not on file (at least), 10 h needed: met even if the schedule item ending 16:00 HST Tue Apr 6 (15:00 "
            "before the report) is duty, 5:00 spare from it.") in t["lines"]
    assert t["rest"]["txt"] == ("at least 31:00 free (15:00 after a schedule item that may be duty), 10:00 needed "
                                "(FAR 117.25(e)): met")
    # review round 5, fix 2 (UI6-4): "at least" across the span, as rest.txt; pwa.rest.have stays the figure
    assert ("rest at least 31:00 (15:00 after a schedule item that may be duty), 11:00 needed (10.E.1.a): "
            "met") in t["pwa"]["txt"] and t["pwa"]["rest"]["have"] == "31:00"
    t = TO.duty_timeout([g0, g1], 1, 2, "roster", "332", unknown=u,
                        busy=[(at(2027, 4, 6, "16:00"), at(2027, 4, 6, "21:00"))])
    assert (t["pwa"]["rest"]["ok"], t["rest"]["ok"]) == (None, True) and t["flags"] == ["rest_q"]
    assert ("PWA rest before this duty (10.E.1.a): in domicile, 11:00 needed; at least 31:00 free (a span of your line "
            "before it is not on file): ? a schedule item inside it may be duty.") in t["lines"]
    t = TO.duty_timeout([g0, g1], 1, 2, "roster", "332", unknown=u,
                        busy=[(at(2027, 4, 6, "16:00"), at(2027, 4, 6, "21:01"))])
    assert (t["pwa"]["rest"]["ok"], t["rest"]["ok"]) == (None, None) and t["flags"] == ["rest_q"]
    t = TO.duty_timeout([g1], 0, 2, "roster", "332", known_from=at(2027, 3, 1, "00:00"),
                        busy=[(at(2027, 4, 6, "20:00"), at(2027, 4, 6, "20:45"))])
    assert (t["pwa"]["rest"]["ok"], t["rest"]["ok"]) == (None, True) and t["flags"] == ["rest_q"]
    assert ("PWA rest before this duty (10.E.1.a): in domicile, 11:00 needed; no duty on file before it: ? a schedule "
            "item inside it may be duty.") in t["lines"]
    t = TO.duty_timeout([g1], 0, 2, "roster", "332", known_from=at(2027, 3, 1, "00:00"),
                        busy=[(at(2027, 4, 6, "21:30"), at(2027, 4, 6, "22:00"))])
    assert t["rest"]["ok"] is None and ("Rest before this FDP (FAR 117.25(e), FOM 4.3.2.7): no duty on file in the "
                                        "10 h before it: ? a schedule item inside it may be duty.") in t["lines"]


def test_card_details_show_the_far_rest_row_before_the_fold(browser, tmp_path):
    """Review round 4, fix 2 (UI-R4V-1): a "Rest short" or "Rest ?" chip may be FAR's, but the details showed only the
    PWA rest ("met"), the FAR verdict folded under "How it is worked out". The details now carry a FAR rest row (the
    rule that decides, its need and verdict) before the PWA row, visible without opening the fold. By hand: the 177:00
    SIN trip (_sin_trip), HNL-LAX reporting 08:00 HST Apr 10: 39:00 free, SHORT of 56:00 (117.25(d)), the PWA 11:00
    met; reporting 01:00 HST Apr 11: 56:00 holding two of the three physiological nights: '?'. At 390 and 320 px, no
    sideways scroll."""
    t = TO.duty_timeout(_sin_trip() + [_lax(at(2027, 4, 10, "08:00"))], 2, 2, "roster", "332")
    q = TO.duty_timeout(_sin_trip() + [_lax(at(2027, 4, 11, "01:00"))], 2, 2, "roster", "332")
    for tt, chip, row in ((t, "Rest short", "FAR rest: 39:00 free, 56:00 needed (FAR 117.25(d)): SHORT"),
                          (q, "Rest ?", "FAR rest: 56:00 free, 56:00 needed (FAR 117.25(d)): ? (2 of the three "
                                        "physiological nights, 0100-0700 HNL)")):
        for width in (390, 320):
            pg = browser.new_page(viewport={"width": width, "height": 844})
            pg.set_content(_page(_watcher_pwa(tmp_path, _graft(tt))))
            card = pg.locator("flight-watcher-layover-card")
            box = card.locator("[data-to]")
            assert box.locator("[data-towarn]").all_inner_texts() == [chip]
            box.click()
            far, pwa = card.locator("[data-tofar]"), card.locator("[data-topwa]")
            assert far.is_visible() and far.inner_text() == row, (width, far.inner_text())
            assert "rest 39:00, 11:00 needed (10.E.1.a): met" in pwa.inner_text() or "rest 56:00" in pwa.inner_text()
            assert far.bounding_box()["y"] < pwa.bounding_box()["y"]  # before the PWA row
            assert not card.locator("[data-tolines]").is_visible()  # the fold stays shut
            assert pg.evaluate("document.documentElement.scrollWidth") <= width
            pg.close()


# ------------------------------------------------------------ review round 5 (the round-4 final recheck's findings)
def _g0():
    """HNL-LAX-HNL: report 06:00 HST Apr 5, HNL-LAX 07:00-12:15, LAX-HNL 13:30-18:45, release 19:00 (domestic)."""
    return _duty(at(2027, 4, 5, "06:00"), _leg("HNL", "LAX", at(2027, 4, 5, "07:00"), at(2027, 4, 5, "12:15"), "1"),
                 _leg("LAX", "HNL", at(2027, 4, 5, "13:30"), at(2027, 4, 5, "18:45"), "2"))


def _m0(k):
    """A Mixed Flying duty (2.A.45: HNL-LIH and LIH-HNL interisland, HNL-LAX 5:15): report 06:00 HST Apr 5, in 15:45,
    release 16:00 (a 10:00 Duty Period), 3 landings."""
    return _kd(k, at(2027, 4, 5, "06:00"), _leg("HNL", "LIH", at(2027, 4, 5, "07:00"), at(2027, 4, 5, "07:40"), "1"),
               _leg("LIH", "HNL", at(2027, 4, 5, "08:30"), at(2027, 4, 5, "09:10"), "2"),
               _leg("HNL", "LAX", at(2027, 4, 5, "10:30"), at(2027, 4, 5, "15:45"), "3"))


def _m1(k, rep):
    """LAX-HNL of the same grouping reporting rep, out 1:15 later, block 5:45."""
    return _kd(k, rep, _leg("LAX", "HNL", rep + timedelta(minutes=75), rep + timedelta(minutes=420), "4"))


def test_a_need_that_holds_whatever_the_duty_before_is_short_across_a_span_when_the_most_is_under_it():
    """Review round 5 (RV5-2): across a span of the line not on file a rule whose need holds whatever the preceding
    duty was read '?' though the most the rest can be (the report less the on-file release of the duty before it) was
    under the need: a duty in the span only shortens the rest, so it is a sure SHORT, flagged as with no span. By hand,
    2 pilots unless said:
    - _g0 (release 19:00 HST Apr 5), a span not on file 20:00-21:00, HNL-LAX reporting 04:00 HST Apr 6: at least 7:00,
      at most 9:00: FAR 117.25(e)'s 10 h and 10.E.1.a's 11:00 in domicile SHORT, flags rest and pwa_rest (round 4: '?'
      both, rest_q; with no span 9:00 free, the same flags);
    - _g0 and the span, HNL-LIH (all interisland) reporting 06:30 HST Apr 6: at least 9:30, at most 11:30: 10.E.2.a's
      12:00 SHORT; the FAR 10 h stays a '?' (a duty in the span may cut 11:30 under 10 h);
    - HNL-OGG (report 06:00 HST Apr 5, in 07:40, release 07:55), a span 08:30-09:30, OGG-HNL reporting 16:00: at least
      6:30, at most 8:05: 10.E.2.b's 9:00 away and the FAR 10 h SHORT;
    - a Mixed Flying grouping, 3 pilots (_m0, release 16:00 HST Apr 5), a span 17:00-18:00, LAX-HNL reporting 00:30 HST
      Apr 6: at most 8:30, under 10.E.3.a's 9:00 for the 3 landings: SHORT (more landings only raise it);
    - never short where a duty in the span could lower the need: _sit_pair(150) (a 2:30 sit at KOA, so Mixed Flying
      only if KOA-HNL is no Repositioning Flight; the other reading needs 2 x the preceding Duty Period, which a duty in
      the span may set) with its LAX-KOA-HNL duty 2:00 earlier (21:00 HST Feb 10, release 12:30, at most 8:30) and a
      span 13:00-14:00: the FAR 10 h SHORT, 10.E.3.a's 9:00 a '?'."""
    u = [(at(2027, 4, 5, "20:00"), at(2027, 4, 5, "21:00"))]
    t = TO.duty_timeout([_g0(), _lax(at(2027, 4, 6, "04:00"))], 1, 2, "roster", "332", unknown=u)
    assert t["flags"] == ["rest", "pwa_rest"]
    assert (t["rest"]["ok"], t["rest"]["free"], t["rest"]["cite"]) == (False, "7:00", "FAR 117.25(e)")
    assert t["rest"]["txt"] == "at most 9:00 free, 10:00 needed (FAR 117.25(e)): SHORT"
    r = t["pwa"]["rest"]
    assert (r["need"], r["have"], r["ok"], r["cite"]) == ("11:00", "7:00", False, "10.E.1.a")
    assert "rest at most 9:00, 11:00 needed (10.E.1.a): SHORT" in t["pwa"]["txt"]
    assert ("Rest before this FDP (FAR 117.25(e), FOM 4.3.2.7): 7:00 free from duty since the end of a span of your "
            "line not on file (at least), 10 h needed: SHORT: at most 9:00 since the release of the duty before it; a "
            "duty in the span not on file would only shorten it, check with Crew Scheduling.") in t["lines"]
    assert ("PWA rest before this duty (10.E.1.a): in domicile, 11:00 needed; at least 7:00 free (a span of your line "
            "before it is not on file): SHORT: at most 9:00 since the release of the duty before it; a duty in the "
            "span not on file would only shorten it.") in t["lines"]
    assert "Flag: short of PWA rest (10.E.1.a): at most 9:00 of 11:00." in t["lines"]
    t = TO.duty_timeout([_g0(), _lax(at(2027, 4, 6, "04:00"))], 1, 2, "roster", "332")
    assert t["flags"] == ["rest", "pwa_rest"]
    rep = at(2027, 4, 6, "06:30")
    lih = _duty(rep, _leg("HNL", "LIH", rep + timedelta(hours=1), rep + timedelta(minutes=100), "3"))
    t = TO.duty_timeout([_g0(), lih], 1, 2, "roster", "332", unknown=u)
    r = t["pwa"]["rest"]
    assert (r["need"], r["ok"], r["cite"], t["rest"]["ok"], t["flags"]) == ("12:00", False, "10.E.2.a", None,
                                                                            ["pwa_rest"])
    assert "Flag: short of PWA rest (10.E.2.a): at most 11:30 of 12:00." in t["lines"]
    og = _duty(at(2027, 4, 5, "06:00"), _leg("HNL", "OGG", at(2027, 4, 5, "07:00"), at(2027, 4, 5, "07:40"), "1"))
    t = TO.duty_timeout([og, _oh(at(2027, 4, 5, "16:00"))], 1, 2, "roster", "332",
                        unknown=[(at(2027, 4, 5, "08:30"), at(2027, 4, 5, "09:30"))])
    r = t["pwa"]["rest"]
    assert (r["need"], r["have"], r["ok"], r["cite"], t["flags"]) == ("9:00", "6:30", False, "10.E.2.b",
                                                                      ["rest", "pwa_rest"])
    assert "Flag: short of PWA rest (10.E.2.b): at most 8:05 of 9:00." in t["lines"]
    k = "H3971|2027-04-05"
    t = TO.duty_timeout([_m0(k), _m1(k, at(2027, 4, 6, "00:30"))], 1, 3, "roster", "332",
                        unknown=[(at(2027, 4, 5, "17:00"), at(2027, 4, 5, "18:00"))])
    r = t["pwa"]["rest"]
    assert (r["need"], r["ok"], r["cite"], t["flags"]) == ("9:00", False, "10.E.3.a", ["rest", "pwa_rest"])
    assert "Flag: short of PWA rest (10.E.3.a): at most 8:30 of 9:00." in t["lines"]
    ds = _sit_pair(150)
    t = TO.duty_timeout([ds[0], _shift(ds[1], timedelta(hours=-2))], 1, 3, "roster", "",
                        unknown=[(at(2027, 2, 10, "13:00"), at(2027, 2, 10, "14:00"))])
    r = t["pwa"]["rest"]
    assert (r["need"], r["ok"], r["cite"], t["rest"]["ok"], t["flags"]) == ("9:00", None, "10.E.3.a", False, ["rest"])


def test_a_deadhead_across_a_span_of_the_line_is_judged_on_the_bounded_readings_of_its_acclimation():
    """Review round 5 (RV5-1): a span of the line not on file before a deadhead made its acclimation 'not known' (the
    lowest row on any clock, 8:30), so a 117.25(g) SHORT became '?' even for a 1 h span in the same theater. Now the
    readings are bounded: the span read as free time and as duty (not acclimated, the last acclimated clock less 0:30),
    plus HNL's clock. By hand, 2 pilots: HNL-LAX (report 08:00 HST Apr 1, in 14:15, release 14:30), a span at LAX Apr 2
    02:00-03:00 HST, a LAX-HNL deadhead only reporting 14:00 HST Apr 2 (17:00 PDT), in 03:00 HST Apr 3: 13:00 from the
    report. 23:30 from the release to that report, under 36 h, holds no acclimation to a theater not on file, and LAX is
    39.5 deg from HNL: read as free time acclimated to HNL (HNL 14:00 and LAX 17:00 PDT, row 1300-1659 and 1700-2159,
    12:00 for 1 segment both); read as duty, also HNL time less 0:30 = 11:30. 13:00 is over 12:00, the most: sure, 13:00
    needed. Release 03:15; HNL-LAX reporting 15:15 HST Apr 3: 12:00 free, SHORT, flagged, as with no span and as round
    3 (round 4: '?', rest_q). Not bounded (ANY stays) where a stay in another theater may reach 72 h inside the span:
    HNL-SIN (in 19:30 HST Apr 1, release 20:00), SIN-NRT (report 06:00 HST Apr 3, 34:00 later, release 13:30), a span at
    NRT Apr 4 12:00-20:00 HST, a NRT-HNL deadhead reporting 22:00 HST Apr 4 (32:30 after the release), in 11:30 Apr 5:
    13:30. In the SIN-NRT theater since 19:30 Apr 1, 72 h at 19:30 Apr 4, inside the span: he may have been acclimated
    there and left it, a reading neither walk gives, so the lowest row stays: release 12:00, HNL-LAX reporting 01:00
    HST Apr 6, 13:00 free: '?'. The span ending 19:00 (before the 72 h): bounded, NRT time 22:00 HST = 17:00 JST Apr 5,
    row 1700-2159, 12:00, and HNL time less 0:30 (row 2200-2259, 10:30): 13:30 is over both: SHORT."""
    d0 = _duty(at(2027, 4, 1, "08:00"), _leg("HNL", "LAX", at(2027, 4, 1, "09:00"), at(2027, 4, 1, "14:15"), "1"))
    dh = _duty(at(2027, 4, 2, "14:00"),
               _leg("LAX", "HNL", at(2027, 4, 2, "15:00"), at(2027, 4, 3, "03:00"), "2", dh=True))
    for u in ([], [(at(2027, 4, 2, "02:00"), at(2027, 4, 2, "03:00"))]):
        t = TO.duty_timeout([d0, dh, _lax(at(2027, 4, 3, "15:15"))], 2, 2, "roster", "332", unknown=u)
        assert (t["rest"]["ok"], t["rest"]["need"], t["rest"]["free"]) == (False, "13:00", "12:00"), u
        assert t["flags"] == ["rest"] and "Flag: short of FAR rest (FAR 117.25(g)): 12:00 of 13:00." in t["lines"]
        assert t["last_out"]["hst"] == ("22:00 HST" if not u else "18:30 HST")  # the duty's own walk is unchanged
    assert ("Rest after deadhead transportation (FAR 117.25(g), FOM 4.3.2.10): the duty before it was deadhead "
            "transportation only, 13:00 from its report to its last block-in, over its Table B FDP on every reading of "
            "its acclimation across a span of your line not on file (12:00 at most, HNL time): a rest as long as the "
            "deadhead transportation (13:00, from the report), no less than 10 h; 12:00 free: SHORT, check with Crew "
            "Scheduling.") in t["lines"]
    json.dumps(t)
    s0 = _duty(at(2027, 4, 1, "08:00"), _leg("HNL", "SIN", at(2027, 4, 1, "09:00"), at(2027, 4, 1, "19:30"), "1"))
    s1 = _duty(at(2027, 4, 3, "06:00"), _leg("SIN", "NRT", at(2027, 4, 3, "07:00"), at(2027, 4, 3, "13:00"), "2"))
    s2 = _duty(at(2027, 4, 4, "22:00"),
               _leg("NRT", "HNL", at(2027, 4, 4, "23:00"), at(2027, 4, 5, "11:30"), "3", dh=True))
    ds = [s0, s1, s2, _lax(at(2027, 4, 6, "01:00"))]
    t = TO.duty_timeout(ds, 3, 2, "roster", "332", unknown=[(at(2027, 4, 4, "12:00"), at(2027, 4, 4, "20:00"))])
    assert (t["rest"]["ok"], t["rest"]["free"], t["flags"]) == (None, "13:00", ["rest_q"])
    assert any(s.startswith("Rest after deadhead transportation (FAR 117.25(g)") and "over its Table B FDP 8:30 (the "
               "lowest row on any clock, less 0:30: acclimation not known)" in s for s in t["lines"])
    t = TO.duty_timeout(ds, 3, 2, "roster", "332", unknown=[(at(2027, 4, 4, "12:00"), at(2027, 4, 4, "19:00"))])
    assert (t["rest"]["ok"], t["rest"]["need"], t["flags"]) == (False, "13:30", ["rest"])
    assert any(s.startswith("Rest after deadhead transportation (FAR 117.25(g)") and "(12:00 at most, NRT time)" in s
               for s in t["lines"])


def test_a_mixed_flying_grouping_judges_2_x_the_duty_period_across_a_span_not_on_file():
    """Review round 5 (F2V-1): the block that makes a Mixed Flying grouping's rest a '?' when 2 x the preceding Duty
    Period is not known fired across a span not on file too, saying the duty before it was not on file, so the '?'
    could never resolve. Now, with the duty before it on file, 10.E.1.a.1 is judged across the span (met only when the
    rest since the span ended meets 2 x the longer of that Duty Period and the span, with the 2:30 van rides spare). By
    hand, 3 pilots: _m0 (Duty Period 10:00, release 16:00 HST Apr 5), a span 17:00-18:00 (a duty in it at most 2:00),
    LAX-HNL of the same grouping: 2 x the longer = 20:00, 22:30 with the van rides. Reporting 16:30 HST Apr 6: at least
    22:30 since the span: met, flags [] (round 4: '?', rest_q); 16:29: 2:29 spare, '?', other 20:00 (10.E.1.a.1); 12:00
    HST Apr 6: at least 18:00, 20:00 since that release: '? met only if no duty in the span needs more'. 10.E.3.a's 9:00
    for the 3 landings is met each time. Review round 5, fix 1 (R5V-3, PWA 10.F.1): the span starts 1:00 after the
    release, inside a 10.E rest, so a call-back in it may make 06:00 to the span's end 18:00 one Duty Period: 12:00,
    2 x = 24:00, 26:30 with the van rides: 16:30 (22:30 since the span) is '? met only if no duty in the span needs more
    (24:30 since that release)'; met from 20:30 (26:30); 20:29: '? met by 2:29 since the span ... ended' (R5V-4: the
    spare is from the span's end, not from the release)."""
    k = "H3971|2027-04-05"
    u = [(at(2027, 4, 5, "17:00"), at(2027, 4, 5, "18:00"))]
    # review round 5, fix 1 (R5V-3, PWA 10.F.1): a call-back in the span may make 06:00-18:00 one Duty Period: 2 x 12:00
    # = 24:00, 26:30 with the van rides: met from 20:30 HST Apr 6 (round 5: 16:30)
    t = TO.duty_timeout([_m0(k), _m1(k, at(2027, 4, 6, "20:30"))], 1, 3, "roster", "332", unknown=u)
    r = t["pwa"]["rest"]
    assert (r["need"], r["have"], r["ok"], r["cite"], t["flags"]) == ("9:00", "26:30", True, "10.E.3.a", [])
    assert "other" not in r and not any(s.startswith("? PWA rest") for s in t["lines"])
    t = TO.duty_timeout([_m0(k), _m1(k, at(2027, 4, 6, "20:29"))], 1, 3, "roster", "332", unknown=u)
    r = t["pwa"]["rest"]
    assert (r["ok"], r["other"], t["flags"]) == (None, "20:00 (10.E.1.a.1)", ["rest_q"])
    # review round 5, fix 1 (R5V-4): the spare is from the span's end, and the 2:00 from the release
    assert any(s.startswith("? PWA rest, the other reading (10.E.1.a.1): 10.E.3.a's table alone is not sure until "
                            "Ryan confirms it replaces 10.E.1.a.1: 2 x the preceding Duty Period across a span of your "
                            "line not on file: the duty before it on file 10:00 (06:00 HST Mon Apr 5 to release 16:00 "
                            "HST Mon Apr 5), 2 x = 20:00; a duty inside the span (from that release) at most 2:00, 2 x "
                            "= 4:00; called back inside the span with less time off than a 10.E rest, one Duty Period "
                            "from its report to the span's end (10.F.1) at most 12:00, 2 x = 24:00")
               and "? met by 2:29 since the span of your line not on file ended" in s for s in t["lines"])
    t = TO.duty_timeout([_m0(k), _m1(k, at(2027, 4, 6, "16:30"))], 1, 3, "roster", "332", unknown=u)
    assert t["pwa"]["rest"]["ok"] is None and any(
        s.startswith("? PWA rest, the other reading (10.E.1.a.1)") and s.endswith(
            "? not known: met only if no duty in the span needs more (24:30 since that release).") for s in t["lines"])
    assert not any("the duty before it is not on file" in s for s in t["lines"])
    t = TO.duty_timeout([_m0(k), _m1(k, at(2027, 4, 6, "12:00"))], 1, 3, "roster", "332", unknown=u)
    assert t["pwa"]["rest"]["ok"] is None and any(
        s.startswith("? PWA rest, the other reading (10.E.1.a.1)") and s.endswith(
            "? not known: met only if no duty in the span needs more (20:00 since that release).") for s in t["lines"])


def test_the_deadhead_reading_across_a_span_counts_its_own_verdict_once_2_x_the_duty_period_is_judged():
    """Review round 5 (F2V-2): across a span, the deadhead Mixed Flying reading always added a '?' check, though
    10.E.1.a.1 is judged across the span (round 4, fix 2) and the table, the whole grouping's need included, may be met
    with the van rides spare. Now it adds its own verdict: a '?' only when its table is not sure. By hand, the shape of
    the W15 test (3 pilots, one grouping): LAX-SFO release 13:30 HST Apr 6 (Duty Period 3:00), a span 14:00-15:00 (a
    duty in it at most 1:30), SFO-HNL reporting 09:00 HST Apr 7: at least 18:00; 10.E.1.a.1 2 x 3:00 = 6:00 met by
    12:00 (review round 5, fix 1, R5V-3: a call-back in the span, 0:30 after the release, makes one Duty Period
    10:30-15:00, 4:30, PWA 10.F.1: 2 x = 9:00, met by 9:00); the table: 9:00 for the 2 landings before this rest,
    11:00 for the grouping's 8, met by 7:00: met, flags [] and no deadhead '?' line (round 4: '?', rest_q; with no span
    met too); review round 5, fix 1 (R5V-5): pwa.rest names the 10.E.1.a.1 reading, 6:00, not the deadhead reading's
    11:00 that no line shows. Reporting 01:00 HST Apr 7: at least 10:00, 11:00 not met: '?', pwa.rest.need 11:00
    (10.E.3.a), as round 4."""
    k = "H3982|2027-04-05"
    e0 = _kd(k, at(2027, 4, 5, "06:00"),
             _leg("LIH", "HNL", at(2027, 4, 5, "07:00"), at(2027, 4, 5, "07:35"), "1", dh=True),
             _leg("HNL", "LAX", at(2027, 4, 5, "09:00"), at(2027, 4, 5, "14:15"), "2"))
    e1 = _kd(k, at(2027, 4, 6, "10:30"), _leg("LAX", "SFO", at(2027, 4, 6, "11:45"), at(2027, 4, 6, "13:15"), "3"))
    r4, hops = at(2027, 4, 8, "06:00"), []
    for j, (a, b) in enumerate([("HNL", "OGG"), ("OGG", "HNL"), ("HNL", "KOA"), ("KOA", "HNL"), ("HNL", "LIH")]):
        o = r4 + timedelta(hours=1, minutes=80 * j)
        hops.append(_leg(a, b, o, o + timedelta(minutes=40), str(10 + j)))
    u = [(at(2027, 4, 6, "14:00"), at(2027, 4, 6, "15:00"))]

    def e2(rep):
        return _kd(k, rep, _leg("SFO", "HNL", rep + timedelta(minutes=75), rep + timedelta(minutes=405), "4"))
    t = TO.duty_timeout([e0, e1, e2(at(2027, 4, 7, "09:00")), _kd(k, r4, *hops)], 2, 3, "roster", "332", unknown=u)
    r = t["pwa"]["rest"]
    assert (r["have"], r["ok"], t["flags"]) == ("18:00", True, []) and "other" not in r
    # review round 5, fix 1 (R5V-5): the met deadhead reading is no check, so its 11:00 (10.E.3.a) is not the cite
    assert (r["need"], r["cite"]) == ("6:00", "10.E.1.a.1") and "10.E.3.a" not in t["pwa"]["txt"]
    assert not any(s.startswith("? PWA rest") for s in t["lines"])
    # review round 5, fix 1 (R5V-3): a call-back in the span may make 10:30-15:00 one Duty Period (10.F.1), 2 x 4:30
    # = 9:00: met by 9:00 (round 5: 2 x 3:00 = 6:00, 12:00 spare)
    assert any(s.startswith("PWA rest before this duty (10.E.1.a.1)") and s.endswith(": met, 9:00 spare.")
               for s in t["lines"])
    t = TO.duty_timeout([e0, e1, e2(at(2027, 4, 7, "01:00")), _kd(k, r4, *hops)], 2, 3, "roster", "332", unknown=u)
    r = t["pwa"]["rest"]
    assert (r["need"], r["have"], r["ok"], r["cite"]) == ("11:00", "10:00", None, "10.E.3.a") and "rest_q" in t["flags"]
    assert any(s.startswith("? PWA rest, the deadhead reading (10.E.3.a)") and s.endswith(
        "10.E.1.a.1 is judged across the span not on file above; this reading only adds the '?'.") for s in t["lines"])


def test_at_home_after_a_span_not_on_file_the_interisland_rest_is_a_reading_whatever_the_duty_before():
    """Review round 5 (F2V-3): at home after a span not on file, 10.E.2.a's 12:00 (after an all-interisland duty) was a
    reading only when the on-file duty before the span was all interisland; a duty inside the span may be the preceding
    one and all interisland. Now it is a reading whatever that duty was; it only adds a '?' (never short). By hand, 2
    pilots: _g0 (International, release 19:00 HST Apr 5), a span Apr 6 12:00-19:30 (7:30, at HNL: no FAR 117.25(g)
    reading), HNL-LAX reporting 07:00 HST Apr 7: at least 11:30: 10.E.1.a's 11:00 met by 0:30, the 12:00 reading '?':
    '?', other 12:00 (10.E.2.a), rest_q (round 4: met, flags []); 07:30: at least 12:00, both met; 05:00: at least 9:30,
    at most 34:00: 10.E.1.a a '?', never short; with no span (36:00 free) met, no reading."""
    u = [(at(2027, 4, 6, "12:00"), at(2027, 4, 6, "19:30"))]
    t = TO.duty_timeout([_g0(), _lax(at(2027, 4, 7, "07:00"))], 1, 2, "roster", "332", unknown=u)
    r = t["pwa"]["rest"]
    assert (r["need"], r["have"], r["ok"], r["cite"], r["other"]) == ("11:00", "11:30", None, "10.E.1.a",
                                                                      "12:00 (10.E.2.a)")
    assert t["flags"] == ["rest_q"] and t["rest"]["ok"] is True
    assert ("? PWA rest, the other reading (10.E.2.a): a duty inside the span of your line not on file may be all "
            "interisland flying (2.A.36.b): in domicile after a duty that was all interisland flying, 12:00 needed: ? "
            "not known. The readings disagree, so the rest is not sure.") in t["lines"]
    t = TO.duty_timeout([_g0(), _lax(at(2027, 4, 7, "07:30"))], 1, 2, "roster", "332", unknown=u)
    assert (t["pwa"]["rest"]["ok"], t["flags"]) == (True, [])
    t = TO.duty_timeout([_g0(), _lax(at(2027, 4, 7, "05:00"))], 1, 2, "roster", "332", unknown=u)
    assert t["pwa"]["rest"]["ok"] is None and "pwa_rest" not in t["flags"]
    t = TO.duty_timeout([_g0(), _lax(at(2027, 4, 7, "07:00"))], 1, 2, "roster", "332")
    assert (t["pwa"]["rest"]["ok"], t["flags"]) == (True, []) and not any("10.E.2.a" in s for s in t["lines"])


def test_a_span_not_on_file_that_may_hold_a_deadhead_adds_a_far_117_25g_question():
    """Review round 5 (F2V-4, the FAR twin of RV-5): after a span not on file, FAR 117.25(g) was judged on the on-file
    duty before it only. A span that moves him, or that runs over 8:30 (the lowest Table B row, 9:00, less 0:30), may
    hold deadhead transportation past its Table B FDP: a reading that needs the longer of 10 h and the span, met only
    when the rest since the span ended meets it, else a '?', never short. By hand, 2 pilots, _g0 (release 19:00 HST Apr
    5, at HNL):
    - a span Apr 6 04:00-20:00 (16:00), SIN-NRT reporting at SIN 08:00 HST Apr 7 (he went to SIN inside the span): at
      least 12:00, 10 h met; the reading needs 16:00: '?', rest.txt names it, rest_q (round 4: met);
    - at HNL, a span Apr 6 04:00-16:00 (12:00, over 8:30), HNL-LAX reporting 03:00 HST Apr 7: at least 11:00, 12:00
      needed: '?'; 04:00: 12:00 met; a span 04:00-12:30 (8:30, not over it), reporting 01:00: no reading.
    Review round 5, fix 2 (RF1-F2V4-SHORT-SPAN, V6-MUT-EF): a span of 8:30 or less holds no deadhead past any Table B
    row even when it moves him, so only the length counts (round 5 also read a station change), and a schedule item
    outside the 10 h no longer makes the reading a '?' once the time since the last of them meets its need:
    - a span 04:00-12:45 (8:45, over 8:30), reporting 01:00 Apr 7: a line, 10 h needed, at least 12:15: met;
    - a span 04:00-05:00 Apr 6 that moves him (SFO-HNL reporting 20:00 HST Apr 6, 15:00 after it) and a 1 h item ending
      12:00 before the report: no 117.25(g) line, the 10 h met even if the item is duty, 2:00 spare from it (round 5,
      fix 1: a line and a '?' for the item)."""
    rep = at(2027, 4, 7, "08:00")
    sn = _duty(rep, _leg("SIN", "NRT", rep + timedelta(minutes=75), rep + timedelta(hours=8, minutes=15), "3"))
    t = TO.duty_timeout([_g0(), sn], 1, 2, "roster", "332",
                        unknown=[(at(2027, 4, 6, "04:00"), at(2027, 4, 6, "20:00"))])
    assert (t["rest"]["ok"], t["rest"]["free"], t["rest"]["cite"]) == (None, "12:00", "FAR 117.25(g)")
    assert t["rest"]["txt"] == ("at least 12:00 free, 16:00 needed (FAR 117.25(g)): ? (a span of your line not on "
                                "file; if it applies)")
    assert "rest_q" in t["flags"] and "rest" not in t["flags"] and "need" not in t["rest"]
    assert ("Rest after deadhead transportation (FAR 117.25(g), FOM 4.3.2.10): a deadhead inside the span of your line "
            "not on file may need more (FAR 117.25(g), FOM 4.3.2.10): the span runs 16:00 (04:00 HST Tue Apr 6 to "
            "20:00 HST Tue Apr 6), over 8:30 (the lowest Table B row less 0:30); the duty before it ended at HNL and "
            "you report at SIN, so a deadhead in it may have run past its Table B FDP and need a rest as long (at most "
            "16:00), no less than 10 h; at least 12:00 free (since the end of that span): ? not known: short if a "
            "deadhead in the span ran past its Table B FDP.") in t["lines"]
    u = [(at(2027, 4, 6, "04:00"), at(2027, 4, 6, "16:00"))]
    t = TO.duty_timeout([_g0(), _lax(at(2027, 4, 7, "03:00"))], 1, 2, "roster", "332", unknown=u)
    assert (t["rest"]["ok"], t["rest"]["cite"]) == (None, "FAR 117.25(g)") and "12:00 needed" in t["rest"]["txt"]
    t = TO.duty_timeout([_g0(), _lax(at(2027, 4, 7, "04:00"))], 1, 2, "roster", "332", unknown=u)
    assert t["rest"]["ok"] is True and t["flags"] == []
    t = TO.duty_timeout([_g0(), _lax(at(2027, 4, 7, "01:00"))], 1, 2, "roster", "332",
                        unknown=[(at(2027, 4, 6, "04:00"), at(2027, 4, 6, "12:30"))])
    assert t["rest"]["ok"] is True and not any("117.25(g)" in s for s in t["lines"])
    t = TO.duty_timeout([_g0(), _lax(at(2027, 4, 7, "01:00"))], 1, 2, "roster", "332",
                        unknown=[(at(2027, 4, 6, "04:00"), at(2027, 4, 6, "12:45"))])
    assert t["rest"]["ok"] is True and any(s.startswith("Rest after deadhead") and "the span runs 8:45 (04:00 HST Tue "
                                           "Apr 6 to 12:45 HST Tue Apr 6), over 8:30" in s and s.endswith(
                                               "at least 12:15 free (since the end of that span): met.")
                                           for s in t["lines"])
    rep = at(2027, 4, 6, "20:00")
    sf = _duty(rep, _leg("SFO", "HNL", rep + timedelta(hours=1), rep + timedelta(hours=6), "4"))
    t = TO.duty_timeout([_g0(), sf], 1, 2, "roster", "332",
                        unknown=[(at(2027, 4, 6, "04:00"), at(2027, 4, 6, "05:00"))],
                        busy=[(at(2027, 4, 6, "07:00"), at(2027, 4, 6, "08:00"))])
    assert t["rest"]["ok"] is True and not any(s.startswith("Rest after deadhead") for s in t["lines"])
    assert ("Rest before this FDP (FAR 117.25(e), FOM 4.3.2.7): 15:00 free from duty since the end of a span of your "
            "line not on file (at least), 10 h needed: met even if the schedule item ending 08:00 HST Tue Apr 6 (12:00 "
            "before the report) is duty, 2:00 spare from it.") in t["lines"]


def test_a_schedule_item_counts_against_a_fixed_rest_need_only_inside_that_need():
    """Review round 5 (RV5-3): a schedule item that may be duty anywhere in the rest made it a '?'. For a need that
    holds whatever the duty before it was (FAR 117.25(e)'s 10 h, 10.E.1.a's 11:00, 10.E.2.a's 12:00, 10.E.2.b's 9:00)
    only an item ending inside the need before the report counts: even as duty it leaves the need. 2 x the preceding
    Duty Period keeps any item (one may be the preceding duty and set the need). By hand, 2 pilots: _g0 (release 19:00
    HST Apr 5), a training day Apr 6 08:00-16:00 HST, HNL-LAX reporting 07:00 HST Apr 7 (36:00 free): FAR and PWA met
    (round 4: '?' both, rest_q); training 16:00-21:00 (10:00 before the report): FAR met, 10.E.1.a a '?'. Away: HNL-LAX
    (report 06:00 HST Apr 5, in 14:15, release 14:30: 2 x 8:30 = 17:00), training Apr 5 16:00-17:00, LAX-HNL reporting
    12:00 HST Apr 6: 21:30 meets 17:00 by 4:30, but the item may be the preceding duty: '?'; the FAR 10 h met."""
    for b, pwa, far in (("16:00", True, True), ("21:00", None, True)):
        a = "08:00" if b == "16:00" else "16:00"
        t = TO.duty_timeout([_g0(), _lax(at(2027, 4, 7, "07:00"))], 1, 2, "roster", "332",
                            busy=[(at(2027, 4, 6, a), at(2027, 4, 6, b))])
        assert (t["pwa"]["rest"]["ok"], t["rest"]["ok"]) == (pwa, far), b
        assert t["flags"] == ([] if pwa else ["rest_q"]), b
    d0 = _duty(at(2027, 4, 5, "06:00"), _leg("HNL", "LAX", at(2027, 4, 5, "07:00"), at(2027, 4, 5, "14:15"), "1"))
    t = TO.duty_timeout([d0, _lh(at(2027, 4, 6, "12:00"))], 1, 2, "roster", "332",
                        busy=[(at(2027, 4, 5, "16:00"), at(2027, 4, 5, "17:00"))])
    r = t["pwa"]["rest"]
    assert (r["need"], r["ok"], r["cite"], t["rest"]["ok"]) == ("17:00", None, "10.E.1.a.1", True)
    assert any(s.startswith("PWA rest before this duty (10.E.1.a.1)") and "? a schedule item inside it may be duty" in s
               for s in t["lines"])


# ------------------------------------------------------------ review round 5, fix 1 (the round-5 verifiers' findings)
def _jfk_line(dh_rep, dh_arr, nrt=False):
    """HNL-JFK (in 16:00 HST Apr 1), JFK-BOS-JFK (report 22:00 HST Apr 2, release 06:00 Apr 3), JFK-HNL (report 17:00
    HST Apr 4, 35:00 after it, in 04:00 Apr 5), HNL-LAX-HNL (report 15:00 HST Apr 6, release 04:00 Apr 7), a HNL-JFK
    deadhead only (dh_rep to dh_arr), JFK-BOS 10:30 after its release (the duty judged); nrt: an on-file HNL-NRT-HNL
    trip Apr 7 06:00-22:30 (the second span's reality)."""
    ds = [_duty(at(2027, 4, 1, "06:00"), _leg("HNL", "JFK", at(2027, 4, 1, "07:00"), at(2027, 4, 1, "16:00"), "1")),
          _duty(at(2027, 4, 2, "22:00"), _leg("JFK", "BOS", at(2027, 4, 2, "23:00"), at(2027, 4, 3, "00:15"), "2"),
                _leg("BOS", "JFK", at(2027, 4, 3, "04:00"), at(2027, 4, 3, "05:45"), "3")),
          _duty(at(2027, 4, 4, "17:00"), _leg("JFK", "HNL", at(2027, 4, 4, "18:00"), at(2027, 4, 5, "04:00"), "4")),
          _duty(at(2027, 4, 6, "15:00"), _leg("HNL", "LAX", at(2027, 4, 6, "16:00"), at(2027, 4, 6, "21:15"), "5"),
                _leg("LAX", "HNL", at(2027, 4, 6, "22:30"), at(2027, 4, 7, "03:45"), "6"))]
    if nrt:
        ds.append(_duty(at(2027, 4, 7, "06:00"),
                        _leg("HNL", "NRT", at(2027, 4, 7, "07:00"), at(2027, 4, 7, "15:00"), "7"),
                        _leg("NRT", "HNL", at(2027, 4, 7, "16:00"), at(2027, 4, 7, "22:30"), "8")))
    ds.append(_duty(dh_rep, _leg("HNL", "JFK", dh_rep + timedelta(hours=1), dh_arr, "9", dh=True)))
    rep = dh_arr + timedelta(minutes=15, hours=10, seconds=1800)  # the deadhead's release (0:15) + 10:30
    ds.append(_duty(rep, _leg("JFK", "BOS", rep + timedelta(hours=1), rep + timedelta(hours=2, minutes=15), "10")))
    return ds


def test_a_deadhead_after_two_spans_is_judged_on_every_mix_of_their_readings():
    """Review round 5, fix 1 (R5V-1): the bound of a deadhead's acclimation (RV5-1) read every span as free time, or
    every span as duty, but not a mix, so with spans in two gaps a reading was missed. By hand, 2 pilots (_jfk_line): a
    span Apr 3 08:00-12:00 (35:00 from the 06:00 release to the 17:00 Apr 4 report, under 36 h), a span Apr 7
    06:00-23:00 (32:00 to the deadhead's 12:00 HST Apr 8 report), a HNL-JFK deadhead 12:00 HST Apr 8 to 00:00 Apr 9
    (12:00), JFK-BOS 10:30 after its release. Both spans free: 73:00 in the JFK theater by Apr 4 17:00 (acclimated
    there), then 80:00 back in HNL's by Apr 8 12:00: HNL time 12:00, row 1200-1259, 13:00. Both duty: never acclimated
    to JFK, HNL time 13:00 and HNL less 0:30, 12:30. The first free, the second a trip out of HNL's theater (the reality
    HNL-NRT-HNL Apr 7): acclimated to JFK and not to HNL: JFK time 18:00 EDT, row 1700-2159, 12:00 less 0:30 = 11:30,
    a reading neither pure walk gives. 12:00 is over 11:30 and not over 13:00: '? SHORT of 12:00 if it applies', rest_q
    (round 5: no 117.25(g) line, met); the reality with the trip on file: SHORT, 12:00 needed. With the deadhead
    reporting 04:30 HST Apr 8 (in 15:30, 11:00): HNL 04:30, row 0400-0459, 10:00, less 0:30 9:30, and JFK 10:30 EDT,
    row 0700-1159, 14:00 less 0:30 = 13:30: '?' (round 5: a sure SHORT on 10:00, though the trip on file reads '?').
    Review round 5, fix 2: the same; the mixed walk itself (the first span free, the second duty, his stay at HNL not
    begun in it) reads JFK less 0:30, the walk with both free HNL 12:00."""
    spans = [(at(2027, 4, 3, "08:00"), at(2027, 4, 3, "12:00")), (at(2027, 4, 7, "06:00"), at(2027, 4, 7, "23:00"))]
    ds = _jfk_line(at(2027, 4, 8, "12:00"), at(2027, 4, 9, "00:00"))
    t = TO.duty_timeout(ds, 5, 2, "roster", "332", unknown=spans)
    assert (t["rest"]["ok"], t["rest"]["free"], t["rest"]["cite"]) == (None, "10:30", "FAR 117.25(g)")
    assert "rest_q" in t["flags"] and "rest" not in t["flags"]
    assert any(s.startswith("Rest after deadhead transportation (FAR 117.25(g)") and "over its Table B FDP 11:30 (JFK "
               "time, less 0:30: not acclimated on a reading of a span of your line not on file)" in s and
               "another reading of its acclimation gives 13:00" in s and s.endswith(
                   "10:30 free: ? SHORT of 12:00 if it applies.") for s in t["lines"])
    pr = [TO._prep(d) for d in ds]
    assert TO._acclimation(pr, 4, (), spans, read=[0, 0], info={})[0] == [("HNL", False)]
    assert TO._acclimation(pr, 4, (), spans, read=[0, 1, 1], info={})[0] == [("JFK", True)]
    t = TO.duty_timeout(_jfk_line(at(2027, 4, 8, "12:00"), at(2027, 4, 9, "00:00"), nrt=True), 6, 2, "roster", "332")
    assert (t["rest"]["ok"], t["rest"]["need"], t["flags"]) == (False, "12:00", ["rest"])
    ds = _jfk_line(at(2027, 4, 8, "04:30"), at(2027, 4, 8, "15:30"))
    t = TO.duty_timeout(ds, 5, 2, "roster", "332", unknown=spans)
    assert (t["rest"]["ok"], t["rest"]["cite"]) == (None, "FAR 117.25(g)") and "rest" not in t["flags"]
    assert any(s.startswith("Rest after deadhead transportation (FAR 117.25(g)") and "over its Table B FDP 9:30 (HNL "
               "time, less 0:30" in s and "gives 13:30" in s for s in t["lines"])
    json.dumps(t)


def test_a_span_that_moves_him_may_start_his_stay_in_the_new_theater_early():
    """Review round 5, fix 1 (RV5-1-STAY): read as free time, a span that moved him to another theater started his
    stay there only at the next block-in on file, so 72 h there (FAR 117.3) was missed and a 117.25(g) '?' became met.
    By hand, 2 pilots: HNL-LAX (release 14:30 HST Apr 1), a span Apr 1 14:45-Apr 2 23:00, NRT-SIN reporting 02:00 HST
    Apr 3 (35:30 after the release: bounded), SIN-HKG-SIN Apr 4, a SIN-HNL deadhead only reporting 07:00 HST Apr 5
    (01:00 SGT Apr 6), in 18:30 (11:30), release 19:00 (customs); HNL-LAX reporting 06:15 HST Apr 6 (11:15 free). He
    may have been in the NRT-SIN theater from the span's start: 88:30 by the deadhead's report, acclimated there: SIN
    01:00, row 0000-0359, 9:00; or not: HNL 07:00 less 0:30, row 0700-1159, 13:30. 11:30 is over 9:00, not over
    13:30: '? SHORT of 11:30 if it applies', rest_q (round 5: [HNL less 0:30] only, no line, met; rounds 3 and 4: '?').
    With no span: in that theater from 10:00 Apr 3 (45:00), not acclimated: 13:30, no line."""
    a = _duty(at(2027, 4, 1, "08:00"), _leg("HNL", "LAX", at(2027, 4, 1, "09:00"), at(2027, 4, 1, "14:15"), "1"))
    b = _duty(at(2027, 4, 3, "02:00"), _leg("NRT", "SIN", at(2027, 4, 3, "03:00"), at(2027, 4, 3, "10:00"), "2"))
    b2 = _duty(at(2027, 4, 4, "04:00"), _leg("SIN", "HKG", at(2027, 4, 4, "05:00"), at(2027, 4, 4, "09:00"), "3"),
               _leg("HKG", "SIN", at(2027, 4, 4, "10:00"), at(2027, 4, 4, "14:00"), "4"))
    c = _duty(at(2027, 4, 5, "07:00"),
              _leg("SIN", "HNL", at(2027, 4, 5, "08:00"), at(2027, 4, 5, "18:30"), "5", dh=True))
    ds = [a, b, b2, c, _lax(at(2027, 4, 6, "06:15"))]
    u = [(at(2027, 4, 1, "14:45"), at(2027, 4, 2, "23:00"))]
    t = TO.duty_timeout(ds, 4, 2, "roster", "332", unknown=u)
    assert (t["rest"]["ok"], t["rest"]["free"], t["rest"]["cite"]) == (None, "11:15", "FAR 117.25(g)")
    assert "rest_q" in t["flags"] and "rest" not in t["flags"]
    assert any(s.startswith("Rest after deadhead transportation (FAR 117.25(g)") and "over its Table B FDP 9:00 (SIN "
               "time)" in s and "another reading of its acclimation gives 13:30" in s and s.endswith(
                   "11:15 free: ? SHORT of 11:30 if it applies.") for s in t["lines"])
    pr = [TO._prep(d) for d in ds]
    assert TO._acc_bound(pr, 3, (), u) == ([("SIN", False), ("HNL", True)], None)
    t = TO.duty_timeout(ds, 4, 2, "roster", "332")
    assert t["rest"]["ok"] is True and not any("117.25(g)" in s for s in t["lines"])


def test_the_bound_keeps_the_duty_reading_and_the_lowest_row_where_it_cannot_bound():
    """Review round 5, fix 1 (R5V-6, TEST-RV51-DUTYWALK): RV5-1's bound pinned by hand, 2 pilots:
    - the duty reading's last acclimated clock less 0:30: HNL-SIN (in 19:30 HST Apr 1), SIN-NRT (report 06:00 HST Apr
      3, in 13:00), a span at NRT Apr 4 12:00-19:00, a NRT-HNL deadhead reporting 22:00 HST Apr 4 (17:00 JST Apr 5),
      in 08:45 Apr 5 (10:45), release 09:15; HNL-LAX reporting 19:15 HST Apr 5 (10:00 free). Free time: 74:30 in that
      theater, acclimated to NRT: row 1700-2159, 12:00. Duty: his stay there may be broken, not acclimated: HNL 22:00,
      row 2200-2259, 11:00 less 0:30 = 10:30. 10:45 is over 10:30 only: '? SHORT of 10:45 if it applies' (a free walk
      alone: met);
    - acclimated to a theater other than HNL across a short span: HNL-NRT (in 15:00 HST Apr 1), NRT-KIX-NRT (report
      18:00 HST Apr 4, 75:00 there: acclimated to NRT, release 23:15), a span Apr 5 01:00-02:00, a NRT-HNL deadhead
      reporting 05:00 HST Apr 5 (00:00 JST Apr 6), in 13:45 (8:45): NRT 00:00, row 0000-0359, 9:00, and read as duty
      (he may have left the theater) NRT less 0:30, 8:30, status not known: 'over its Table B FDP 8:30 (NRT time, less
      0:30 ...)', 'its acclimation is not known (...)', another reading 9:00; with no span 9:00 only, no line;
    - the lowest row on any clock stays where a walk ends on no bounded reading. A station with no longitude: HNL-XYZ
      (release 15:30 HST Apr 1), a span Apr 1 20:00-21:00, a XYZ-HNL deadhead reporting 08:00 HST Apr 2, in 16:45
      (8:45): 8:30 (the lowest row less 0:30), a line (HNL 08:00 less 0:30 would be 13:30, no line). A schedule item
      that decides the reading: HNL-NRT (release 15:30 HST Apr 1), a span Apr 2 00:00-02:00, NRT-KIX-NRT (report 20:00
      HST Apr 2, release 01:15 Apr 3), an item Apr 3 12:00-14:00, a NRT-HNL deadhead reporting 14:00 HST Apr 4 (36:45
      free, the item inside), in 00:00 Apr 5 (10:00): 8:30, a line (NRT 09:00 JST and HNL less 0:30 would be 14:00 and
      11:30, no line)."""
    s0 = _duty(at(2027, 4, 1, "08:00"), _leg("HNL", "SIN", at(2027, 4, 1, "09:00"), at(2027, 4, 1, "19:30"), "1"))
    s1 = _duty(at(2027, 4, 3, "06:00"), _leg("SIN", "NRT", at(2027, 4, 3, "07:00"), at(2027, 4, 3, "13:00"), "2"))
    s2 = _duty(at(2027, 4, 4, "22:00"),
               _leg("NRT", "HNL", at(2027, 4, 4, "23:00"), at(2027, 4, 5, "08:45"), "3", dh=True))
    t = TO.duty_timeout([s0, s1, s2, _lax(at(2027, 4, 5, "19:15"))], 3, 2, "roster", "332",
                        unknown=[(at(2027, 4, 4, "12:00"), at(2027, 4, 4, "19:00"))])
    assert (t["rest"]["ok"], t["rest"]["free"], t["rest"]["cite"]) == (None, "10:00", "FAR 117.25(g)")
    assert any(s.startswith("Rest after deadhead transportation (FAR 117.25(g)") and "over its Table B FDP 10:30 (HNL "
               "time, less 0:30: not acclimated on a reading of a span of your line not on file)" in s and s.endswith(
                   "10:00 free: ? SHORT of 10:45 if it applies.") for s in t["lines"])
    n0 = _duty(at(2027, 4, 1, "06:00"), _leg("HNL", "NRT", at(2027, 4, 1, "07:00"), at(2027, 4, 1, "15:00"), "1"))
    n1 = _duty(at(2027, 4, 4, "18:00"), _leg("NRT", "KIX", at(2027, 4, 4, "19:00"), at(2027, 4, 4, "20:30"), "2"),
               _leg("KIX", "NRT", at(2027, 4, 4, "21:30"), at(2027, 4, 4, "23:00"), "3"))
    n2 = _duty(at(2027, 4, 5, "05:00"),
               _leg("NRT", "HNL", at(2027, 4, 5, "06:00"), at(2027, 4, 5, "13:45"), "4", dh=True))
    ds = [n0, n1, n2, _lax(at(2027, 4, 6, "02:15"))]
    t = TO.duty_timeout(ds, 3, 2, "roster", "332", unknown=[(at(2027, 4, 5, "01:00"), at(2027, 4, 5, "02:00"))])
    assert any(s.startswith("Rest after deadhead transportation (FAR 117.25(g)") and "over its Table B FDP 8:30 (NRT "
               "time, less 0:30: not acclimated on a reading of a span of your line not on file)" in s and
               "its acclimation is not known (a span of your line not on file, each read as free time and as duty)"
               in s and "another reading of its acclimation gives 9:00" in s for s in t["lines"])
    t = TO.duty_timeout(ds, 3, 2, "roster", "332")
    assert not any("117.25(g)" in s for s in t["lines"])
    x0 = _duty(at(2027, 4, 1, "06:00"), _leg("HNL", "XYZ", at(2027, 4, 1, "07:00"), at(2027, 4, 1, "15:00"), "1"))
    x1 = _duty(at(2027, 4, 2, "08:00"),
               _leg("XYZ", "HNL", at(2027, 4, 2, "09:00"), at(2027, 4, 2, "16:45"), "2", dh=True))
    t = TO.duty_timeout([x0, x1, _lax(at(2027, 4, 3, "05:15"))], 2, 2, "roster", "332",
                        unknown=[(at(2027, 4, 1, "20:00"), at(2027, 4, 1, "21:00"))])
    assert any(s.startswith("Rest after deadhead transportation (FAR 117.25(g)") and "over its Table B FDP 8:30 (the "
               "lowest row on any clock, less 0:30: acclimation not known)" in s for s in t["lines"])
    b0 = _duty(at(2027, 4, 1, "06:00"), _leg("HNL", "NRT", at(2027, 4, 1, "07:00"), at(2027, 4, 1, "15:00"), "1"))
    b1 = _duty(at(2027, 4, 2, "20:00"), _leg("NRT", "KIX", at(2027, 4, 2, "21:00"), at(2027, 4, 2, "22:30"), "2"),
               _leg("KIX", "NRT", at(2027, 4, 2, "23:30"), at(2027, 4, 3, "01:00"), "3"))
    b2 = _duty(at(2027, 4, 4, "14:00"),
               _leg("NRT", "HNL", at(2027, 4, 4, "15:00"), at(2027, 4, 5, "00:00"), "4", dh=True))
    item = [(at(2027, 4, 3, "12:00"), at(2027, 4, 3, "14:00"))]
    t = TO.duty_timeout([b0, b1, b2, _lax(at(2027, 4, 5, "12:30"))], 3, 2, "roster", "332", busy=item,
                        unknown=[(at(2027, 4, 2, "00:00"), at(2027, 4, 2, "02:00"))])
    assert any(s.startswith("Rest after deadhead transportation (FAR 117.25(g)") and "over its Table B FDP 8:30 (the "
               "lowest row on any clock, less 0:30: acclimation not known)" in s for s in t["lines"])
    t = TO.duty_timeout([b0, b1, b2, _lax(at(2027, 4, 5, "12:30"))], 3, 2, "roster", "332", busy=item)
    assert not any("117.25(g)" in s for s in t["lines"])


def test_a_rest_whose_most_equals_its_need_across_a_span_stays_a_question():
    """Review round 5, fix 1 (R5V-6): RV5-2's sure SHORT is for a most under the need; a most equal to it may be met.
    By hand, 2 pilots: _g0 (release 19:00 HST Apr 5), a span 20:00-21:00, HNL-LAX reporting 05:00 HST Apr 6: at least
    8:00, at most 10:00: FAR 117.25(e)'s 10 h a '?' (10:00 is not under it), 10.E.1.a's 11:00 SHORT (at most 10:00);
    06:00: at most 11:00: 10.E.1.a a '?', rest_q, no pwa_rest."""
    u = [(at(2027, 4, 5, "20:00"), at(2027, 4, 5, "21:00"))]
    t = TO.duty_timeout([_g0(), _lax(at(2027, 4, 6, "05:00"))], 1, 2, "roster", "332", unknown=u)
    assert (t["rest"]["ok"], t["pwa"]["rest"]["ok"], t["flags"]) == (None, False, ["pwa_rest"])
    assert ("Rest before this FDP (FAR 117.25(e), FOM 4.3.2.7): 8:00 free from duty since the end of a span of your "
            "line not on file (at least), 10 h needed: ? not known.") in t["lines"]
    t = TO.duty_timeout([_g0(), _lax(at(2027, 4, 6, "06:00"))], 1, 2, "roster", "332", unknown=u)
    assert (t["rest"]["ok"], t["pwa"]["rest"]["ok"], t["flags"]) == (None, None, ["rest_q"])
    assert ("PWA rest before this duty (10.E.1.a): in domicile, 11:00 needed; at least 9:00 free (a span of your line "
            "before it is not on file): ? not known.") in t["lines"]


def test_a_schedule_item_anywhere_in_the_rest_away_keeps_the_interisland_9_hours_a_question():
    """Review round 5, fix 1 (UI5-1, R5V-2): RV5-3 counted, for 10.E.2.b's 9:00 out of domicile, only a schedule item
    ending inside the 9:00; read as duty, an item outside it may still leave a rest met by less than the 2:30 van rides,
    or be the preceding Duty Period of 10.E.1.a.1 on top of 10.E.2.b. Away any item in the rest counts again (round 4's
    '?'). By hand, 2 pilots: HNL-OGG (report 06:00 HST Apr 5, in 07:40, release 07:55, a 1:55 Duty Period), an item
    12:00-20:00 Apr 5, OGG-HNL reporting 06:00 HST Apr 6: 22:05 free; as duty the item leaves 10:00, 9:00 met by 1:00
    (under the van rides) and 2 x 8:00 = 16:00 not met: '? a schedule item inside it may be duty', rest_q (round 5: met,
    13:05 spare). The FAR 10 h: the item ends 10:00 before the report: met even as duty, 0:00 spare from it. An item
    09:00-12:00 Apr 5, OGG-HNL reporting 22:00 Apr 5: 14:05 free, the item ends 10:00 before: '?' (round 5: met, 5:05
    spare); as an on-file OGG-ITO-OGG duty (release 12:00) it reads '? met by 1:00 from release to report' (the van
    rides); with no item: met."""
    og = _duty(at(2027, 4, 5, "06:00"), _leg("HNL", "OGG", at(2027, 4, 5, "07:00"), at(2027, 4, 5, "07:40"), "1"))
    t = TO.duty_timeout([og, _oh(at(2027, 4, 6, "06:00"))], 1, 2, "roster", "332",
                        busy=[(at(2027, 4, 5, "12:00"), at(2027, 4, 5, "20:00"))])
    r = t["pwa"]["rest"]
    assert (r["need"], r["have"], r["ok"], r["cite"], t["flags"]) == ("9:00", "22:05", None, "10.E.2.b", ["rest_q"])
    assert any(s.startswith("PWA rest before this duty (10.E.2.b)") and "? a schedule item inside it may be duty" in s
               for s in t["lines"])
    assert ("Rest before this FDP (FAR 117.25(e), FOM 4.3.2.7): 22:05 free from duty since the last release, 10 h "
            "needed: met even if the schedule item ending 20:00 HST Mon Apr 5 (10:00 before the report) is duty, 0:00 "
            "spare from it.") in t["lines"]
    t = TO.duty_timeout([og, _oh(at(2027, 4, 5, "22:00"))], 1, 2, "roster", "332",
                        busy=[(at(2027, 4, 5, "09:00"), at(2027, 4, 5, "12:00"))])
    assert (t["pwa"]["rest"]["ok"], t["rest"]["ok"], t["flags"]) == (None, True, ["rest_q"])
    x = _duty(at(2027, 4, 5, "09:00"), _leg("OGG", "ITO", at(2027, 4, 5, "09:30"), at(2027, 4, 5, "10:10"), "2"),
              _leg("ITO", "OGG", at(2027, 4, 5, "11:00"), at(2027, 4, 5, "11:45"), "3"))
    t = TO.duty_timeout([og, x, _oh(at(2027, 4, 5, "22:00"))], 2, 2, "roster", "332")
    assert t["pwa"]["rest"]["ok"] is None and any(s.startswith("PWA rest before this duty (10.E.2.b)") and
                                                  "? met by 1:00 from release to report" in s for s in t["lines"])
    t = TO.duty_timeout([og, _oh(at(2027, 4, 5, "22:00"))], 1, 2, "roster", "332")
    assert (t["pwa"]["rest"]["ok"], t["flags"]) == (True, [])


def test_a_met_rest_with_a_schedule_item_in_it_says_the_margin_from_the_item():
    """Review round 5, fix 1 (UI5-2): a fixed need met with a schedule item that may be duty in the rest (outside the
    need) said 'met, 13:00 spare', the margin from the release, though the item may be duty. By hand, 2 pilots: _g0
    (release 19:00 HST Apr 5), training Apr 6 06:00-07:30 HST, HNL-LAX reporting 19:00 HST Apr 6: 24:00 free; the item
    ends 11:30 before the report: FAR 117.25(e) met even as duty, 1:30 spare from it; 10.E.1.a's 11:00 met, 0:30 spare
    from it; rest.txt and the PWA row say 11:30 after it."""
    g1 = _duty(at(2027, 4, 6, "19:00"), _leg("HNL", "LAX", at(2027, 4, 6, "20:00"), at(2027, 4, 7, "01:15"), "3"))
    t = TO.duty_timeout([_g0(), g1], 1, 2, "roster", "332", busy=[(at(2027, 4, 6, "06:00"), at(2027, 4, 6, "07:30"))])
    assert (t["rest"]["ok"], t["pwa"]["rest"]["ok"], t["flags"]) == (True, True, [])
    assert t["pwa"]["rest"]["have"] == "24:00"
    assert t["rest"]["txt"] == ("24:00 free (11:30 after a schedule item that may be duty), 10:00 needed (FAR "
                                "117.25(e)): met")
    assert ("Rest before this FDP (FAR 117.25(e), FOM 4.3.2.7): 24:00 free from duty since the last release, 10 h "
            "needed: met even if the schedule item ending 07:30 HST Tue Apr 6 (11:30 before the report) is duty, 1:30 "
            "spare from it.") in t["lines"]
    assert ("PWA rest before this duty (10.E.1.a): in domicile, 11:00 needed; release to report 24:00: met even if the "
            "schedule item ending 07:30 HST Tue Apr 6 (11:30 before the report) is duty, 0:30 spare from "
            "it.") in t["lines"]
    assert "rest 24:00 (11:30 after a schedule item that may be duty), 11:00 needed (10.E.1.a): met" in t["pwa"]["txt"]
    json.dumps(t)


def test_a_call_back_inside_a_span_may_make_one_duty_period_pwa_10f1():
    """Review round 5, fix 1 (R5V-3, PWA 10.F.1: "If a pilot reports for duty, and is released and is later called back
    for duty, with less time off than the Rest Periods prescribed in Subsection 10.E ... the total time from their first
    reporting for duty to their release ... shall be considered a Duty Period"): across a span that starts inside a
    10.E rest after the duty before it (2 x its Duty Period or 18:00, the longest), a call-back in it may make one Duty
    Period from that duty's report to the span's end, and 2 x that is the need a sure 'met' takes. By hand, 3 pilots:
    HNL-LAX (report 06:00 HST Apr 5, release 14:30: 8:30, 2 x = 17:00, so the 10.E rest is at most 18:00); LAX-HNL
    reporting 01:00 HST Apr 8. A span Apr 6 08:29-08:59 (17:59 after the release): one Duty Period 06:00 Apr 5 to
    08:59 Apr 6 at most, 26:59, 2 x = 53:58; 40:01 since the span: '? met only if no duty in the span needs more (58:30
    since that release)'. A span Apr 6 08:30-09:00 (18:00 after it): no call-back reading; 2 x the longer of 8:30 and
    18:30 (a duty in the span, from that release) = 37:00, 40:00 since the span: met, 3:00 spare."""
    d0 = _duty(at(2027, 4, 5, "06:00"), _leg("HNL", "LAX", at(2027, 4, 5, "07:00"), at(2027, 4, 5, "14:15"), "1"))
    t = TO.duty_timeout([d0, _lh(at(2027, 4, 8, "01:00"))], 1, 3, "roster", "332",
                        unknown=[(at(2027, 4, 6, "08:29"), at(2027, 4, 6, "08:59"))])
    assert (t["pwa"]["rest"]["ok"], t["flags"]) == (None, ["rest_q"])
    assert any(s.startswith("PWA rest before this duty (10.E.1.a.1)") and "called back inside the span with less time "
               "off than a 10.E rest, one Duty Period from its report to the span's end (10.F.1) at most 26:59, 2 x = "
               "53:58" in s and s.endswith("? not known: met only if no duty in the span needs more (58:30 since that "
                                           "release).") for s in t["lines"])
    t = TO.duty_timeout([d0, _lh(at(2027, 4, 8, "01:00"))], 1, 3, "roster", "332",
                        unknown=[(at(2027, 4, 6, "08:30"), at(2027, 4, 6, "09:00"))])
    assert (t["pwa"]["rest"]["ok"], t["flags"]) == (True, [])
    assert any(s.startswith("PWA rest before this duty (10.E.1.a.1)") and "10.F.1" not in s and s.endswith(
        ": met, 3:00 spare.") for s in t["lines"])


def test_a_long_sit_grouping_away_before_an_interisland_duty_is_short_on_both_readings():
    """Review round 5, fix 1 (RV52-LONGSIT-II): 10.E.3.a's table took RV5-2's sure SHORT only where no long sit's
    reading changes Mixed Flying; before an all-interisland duty away the other reading is 10.E.2.b's 9:00, which holds
    whatever the duty before it was and is no less than the table's lowest, so both may be SHORT. By hand, 2 pilots, one
    grouping: HNL-KOA (07:00-07:40 HST Apr 1), a 2:30 sit, KOA-LAX (10:10-15:40): Mixed Flying unless HNL-KOA is a
    Repositioning Flight; LAX-OGG (report 06:00 HST Apr 2, in 12:30, release 12:45); a span at OGG 13:30-14:30; OGG-HNL
    reporting 20:00 HST Apr 2: at least 5:30, at most 7:15. The table for the 3 landings: 9:00; 10.E.2.b: 9:00; both
    SHORT on 7:15: 'Flag: short of PWA rest (10.E.3.a): at most 7:15 of 9:00', pwa_rest (round 5: '?', with the
    other reading's line SHORT), as with no span (7:15 release to report: SHORT); the FAR 10 h SHORT both ways."""
    k = "H3990|2027-04-01"
    d1 = _kd(k, at(2027, 4, 1, "06:00"), _leg("HNL", "KOA", at(2027, 4, 1, "07:00"), at(2027, 4, 1, "07:40"), "1"),
             _leg("KOA", "LAX", at(2027, 4, 1, "10:10"), at(2027, 4, 1, "15:40"), "2"))
    d2 = _kd(k, at(2027, 4, 2, "06:00"), _leg("LAX", "OGG", at(2027, 4, 2, "07:00"), at(2027, 4, 2, "12:30"), "3"))
    rep = at(2027, 4, 2, "20:00")
    d3 = _kd(k, rep, _leg("OGG", "HNL", rep + timedelta(hours=1), rep + timedelta(hours=1, minutes=40), "4"))
    for u in ([(at(2027, 4, 2, "13:30"), at(2027, 4, 2, "14:30"))], []):
        t = TO.duty_timeout([d1, d2, d3], 2, 2, "roster", "332", unknown=u)
        r = t["pwa"]["rest"]
        assert (r["need"], r["ok"], r["cite"], t["flags"]) == ("9:00", False, "10.E.3.a", ["rest", "pwa_rest"]), u
        assert "other" not in r
    t = TO.duty_timeout([d1, d2, d3], 2, 2, "roster", "332",
                        unknown=[(at(2027, 4, 2, "13:30"), at(2027, 4, 2, "14:30"))])
    assert "Flag: short of PWA rest (10.E.3.a): at most 7:15 of 9:00." in t["lines"]


def _las_line(first=None):
    """HNL-LAX (report 06:00 HST May 1 or `first`, 5:15 later in, release 0:15 after), a LAS-HNL-AKL deadhead duty
    (report 20:00 HST May 3, in 11:00 May 4, release 11:30), an AKL-HNL deadhead only reporting 18:00 HST May 4, in
    05:45 May 5 (11:45), release 06:15; HNL-LAX 11:00 later (the duty judged). May 2027: no daylight change."""
    rep = first or at(2027, 5, 1, "06:00")
    a = _duty(rep, _leg("HNL", "LAX", rep + timedelta(hours=1), rep + timedelta(hours=6, minutes=15), "1"))
    b = _duty(at(2027, 5, 3, "20:00"),
              _leg("LAS", "HNL", at(2027, 5, 3, "21:00"), at(2027, 5, 4, "02:00"), "2", dh=True),
              _leg("HNL", "AKL", at(2027, 5, 4, "03:00"), at(2027, 5, 4, "11:00"), "3", dh=True))
    c = _duty(at(2027, 5, 4, "18:00"),
              _leg("AKL", "HNL", at(2027, 5, 4, "19:00"), at(2027, 5, 5, "05:45"), "4", dh=True))
    return [a, b, c, _lax(at(2027, 5, 5, "17:15"))]


def test_a_span_of_36_h_or_more_anywhere_before_the_deadhead_keeps_the_lowest_row():
    """Review round 5, fix 1 (found checking the bound against fillings of its spans): RV5-1 bounded the deadhead's
    acclimation when only the span just before it was short, though an earlier span had reset the walk: after it the
    walk re-acclimates at the next station with 36 h free (LAS here) and takes that station's theater, while he may
    never have left HNL's (LAS is 42.7 deg from HNL). Review round 5, fix 2 (RF1-36H-ANYWHERE): only a span that with
    the free time on file before it is 36 h or more may hold an acclimation to a theater not on file; and after any
    span the deadhead's acclimation is read by the bound, never by the walk's own re-acclimation. By hand, 2 pilots
    (_las_line):
    - HNL-LAX release 12:30 HST May 1, a span May 2 00:00-06:00 (17:30 from that release): bounded: free time or duty,
      38:00 or more free at LAS, 42.7 deg from HNL, acclimated to HNL's theater; at AKL (27.3 deg from HNL) HNL 18:00,
      row 1700-2159, 12:00, AKL 16:00 NZST, row 1300-1659, 12:00: 11:45 is under both, no 117.25(g) line, met (round 5
      and fix 1: the walk's own reading, acclimated to LAS, AKL 70 deg from it, LAS 21:00 PDT less 0:30 = 11:30, a
      sure SHORT the line with the span free does not give);
    - with a span at AKL May 4 12:00-13:00 too, and that span alone: HNL and AKL 12:00, and read as duty HNL less 0:30,
      11:30: 11:45 is over 11:30 only: '? SHORT of 11:45 if it applies', rest_q;
    - HNL-LAX release 12:30 HST Apr 30, a span Apr 30 13:00-May 2 06:00 (41:30 from that release): a report inside it
      may follow 36 h free: the lowest row, '? SHORT of 11:45 if it applies' (round 5: the sure SHORT on LAS), with the
      AKL span and without it (the walk's own reading, LAS less 0:30, would be a sure SHORT)."""
    short = [(at(2027, 5, 4, "12:00"), at(2027, 5, 4, "13:00"))]
    may2 = [(at(2027, 5, 2, "00:00"), at(2027, 5, 2, "06:00"))]
    ds = _las_line()
    assert TO._acc_bound([TO._prep(d) for d in ds], 2, (), may2) == ([("HNL", False), ("AKL", False)], True)
    for u in (may2, []):
        t = TO.duty_timeout(ds, 3, 2, "roster", "332", unknown=u)
        assert t["rest"]["ok"] is True and not any("117.25(g)" in s for s in t["lines"]), u
    for u in (may2 + short, short):
        t = TO.duty_timeout(ds, 3, 2, "roster", "332", unknown=u)
        assert (t["rest"]["ok"], t["rest"]["free"], t["flags"]) == (None, "11:00", ["rest_q"]), u
        assert any(s.startswith("Rest after deadhead transportation (FAR 117.25(g)") and "11:30 (HNL time, less 0:30"
                   in s and "gives 12:00" in s and s.endswith("11:00 free: ? SHORT of 11:45 if it applies.")
                   for s in t["lines"]), u
        assert TO._acc_bound([TO._prep(d) for d in ds], 2, (), u) == ([("HNL", False), ("AKL", False), ("HNL", True)],
                                                                       None), u
    ds = _las_line(at(2027, 4, 30, "06:00"))
    for u in ([(at(2027, 4, 30, "13:00"), at(2027, 5, 2, "06:00"))] + short,
              [(at(2027, 4, 30, "13:00"), at(2027, 5, 2, "06:00"))]):
        t = TO.duty_timeout(ds, 3, 2, "roster", "332", unknown=u)
        assert (t["rest"]["ok"], t["rest"]["free"], t["flags"]) == (None, "11:00", ["rest_q"]), u
        assert any(s.startswith("Rest after deadhead transportation (FAR 117.25(g)") and "over its Table B FDP 8:30 "
                   "(the lowest row on any clock, less 0:30: acclimation not known)" in s and s.endswith(
                       "11:00 free: ? SHORT of 11:45 if it applies.") for s in t["lines"]), u
        assert TO._acc_bound([TO._prep(d) for d in ds], 2, (), u) is None
    assert TO._acclimation([TO._prep(d) for d in ds], 2, (), u)[0] == [("LAS", True)]  # the walk's own reading


# ------------------------------------------------------------ review round 5, fix 2 (the fix-1 verifiers' findings)
def _kix_jfk(span_end="01:00"):
    """HNL-KIX (in 15:00 HST Apr 1, release 15:30, customs), KIX-JFK (report 04:00 HST Apr 4, in 17:00, release 17:30),
    a JFK-HNL deadhead only (report 03:00 HST Apr 6, 22:00 JST, in 15:30: 12:30), HNL-LAX 10:30 after its release
    (15:45 + 10:30 = 02:15 HST Apr 7); the spans: one at KIX from 20:00 Apr 1 to `span_end` Apr 2 (or a datetime) and
    one at JFK Apr 4 22:00-Apr 5 01:00."""
    a = _duty(at(2027, 4, 1, "06:00"), _leg("HNL", "KIX", at(2027, 4, 1, "07:00"), at(2027, 4, 1, "15:00"), "1"))
    b = _duty(at(2027, 4, 4, "04:00"), _leg("KIX", "JFK", at(2027, 4, 4, "05:00"), at(2027, 4, 4, "17:00"), "2"))
    c = _duty(at(2027, 4, 6, "03:00"),
              _leg("JFK", "HNL", at(2027, 4, 6, "04:00"), at(2027, 4, 6, "15:30"), "3", dh=True))
    end = span_end if isinstance(span_end, datetime) else at(2027, 4, 2, span_end)
    return [a, b, c, _lax(at(2027, 4, 7, "02:15"))], [(at(2027, 4, 1, "20:00"), end),
                                                       (at(2027, 4, 4, "22:00"), at(2027, 4, 5, "01:00"))]


def test_a_short_span_early_in_a_long_gap_is_bounded_and_a_deadhead_past_every_reading_is_short():
    """Review round 5, fix 2 (RF1-36H-ANYWHERE): fix 1 kept the lowest row for any span with 36 h or more around it,
    anywhere in the walk, though a report inside a span follows at most the time from the release before it to the
    span's end free from duty: under 36 h it acclimates him to no theater not on file, and the free time after it is
    read by the two readings. By hand, 2 pilots (_kix_jfk): the KIX span 20:00 Apr 1-01:00 Apr 2 (9:30 after the 15:30
    release; 60:30 to the KIX-JFK report) and the JFK span (7:30 after the 17:30 release). Free time: 60:30 free at
    KIX, acclimated there; duty: 51:00 free after the span, acclimated there too. At JFK: 33:30 free, 34:00 in that
    theater, not acclimated (both readings): KIX 22:00 JST less 0:30, row 2200-2259, 11:00 less 0:30 = 10:30; HNL
    03:00 less 0:30 (the domicile's reading) 8:30. 12:30 is over both: SHORT, 12:30 needed, 10:30 free, flagged (fix 1:
    '? SHORT of 12:30 if it applies', the lowest row), as with either span alone and with none (round 5: SHORT in all
    four). The
    KIX span to 03:29 Apr 3 (35:59 after the release): bounded, free time acclimated to KIX (10:30), duty not (24:31
    free after it): HNL less 0:30 at JFK, 8:30: SHORT. To 03:30 (36:00): a report inside it may follow 36 h free, so the
    lowest row stays: '?'."""
    ds, (kix, jfk) = _kix_jfk()
    for u in ([kix, jfk], [kix], [jfk], []):
        t = TO.duty_timeout(ds, 3, 2, "roster", "332", unknown=u)
        assert (t["rest"]["ok"], t["rest"]["need"], t["rest"]["free"]) == (False, "12:30", "10:30"), u
        assert "rest" in t["flags"] and "Flag: short of FAR rest (FAR 117.25(g)): 10:30 of 12:30." in t["lines"], u
    t = TO.duty_timeout(ds, 3, 2, "roster", "332", unknown=[kix, jfk])
    assert any(s.startswith("Rest after deadhead transportation (FAR 117.25(g)") and "over its Table B FDP on every "
               "reading of its acclimation across a span of your line not on file (10:30 at most, KIX time, less 0:30: "
               "not acclimated, FAR 117.13(b))" in s and s.endswith("10:30 free: SHORT, check with Crew Scheduling.")
               for s in t["lines"])
    assert TO._acc_bound([TO._prep(d) for d in ds], 2, (), [kix, jfk]) == ([("KIX", True)], False)
    ds, u = _kix_jfk(at(2027, 4, 3, "03:29"))
    t = TO.duty_timeout(ds, 3, 2, "roster", "332", unknown=u)
    assert (t["rest"]["ok"], t["rest"]["need"]) == (False, "12:30") and "rest" in t["flags"]
    assert TO._acc_bound([TO._prep(d) for d in ds], 2, (), u) == ([("KIX", True), ("HNL", True)], False)
    ds, u = _kix_jfk(at(2027, 4, 3, "03:30"))
    t = TO.duty_timeout(ds, 3, 2, "roster", "332", unknown=u)
    assert t["rest"]["ok"] is None and "rest" not in t["flags"] and TO._acc_bound([TO._prep(d) for d in ds], 2, (),
                                                                                  u) is None
    assert any(s.startswith("Rest after deadhead transportation (FAR 117.25(g)") and "over its Table B FDP 8:30 (the "
               "lowest row on any clock, less 0:30: acclimation not known)" in s and s.endswith(
                   "10:30 free: ? SHORT of 12:30 if it applies.") for s in t["lines"])


def _nrt_stay(s2):
    """HNL-LAX (release 13:15 HST Apr 1), a span Apr 1 14:00-15:00, NRT-KIX (report 08:00 HST Apr 2, in 11:00),
    KIX-NRT (report 20:00 HST Apr 3, release 23:15), a second span s2, an NRT-HNL deadhead only (report 10:30 HST Apr 5,
    05:30 JST Apr 6, in 22:15: 11:45, release 22:45, customs), HNL-LAX 10:15 after it (09:00 HST Apr 6)."""
    ds = [_duty(at(2027, 4, 1, "07:00"), _leg("HNL", "LAX", at(2027, 4, 1, "08:00"), at(2027, 4, 1, "13:00"), "1")),
          _duty(at(2027, 4, 2, "08:00"), _leg("NRT", "KIX", at(2027, 4, 2, "09:00"), at(2027, 4, 2, "11:00"), "2")),
          _duty(at(2027, 4, 3, "20:00"), _leg("KIX", "NRT", at(2027, 4, 3, "21:00"), at(2027, 4, 3, "23:00"), "3")),
          _duty(at(2027, 4, 5, "10:30"),
                _leg("NRT", "HNL", at(2027, 4, 5, "11:00"), at(2027, 4, 5, "22:15"), "4", dh=True)),
          _duty(at(2027, 4, 6, "09:00"), _leg("HNL", "LAX", at(2027, 4, 6, "10:00"), at(2027, 4, 6, "15:30"), "5"))]
    return ds, [(at(2027, 4, 1, "14:00"), at(2027, 4, 1, "15:00")), s2]


def test_a_stay_begun_in_a_span_that_may_reach_72_h_inside_a_later_span_keeps_the_lowest_row():
    """Review round 5, fix 2 (V6-MUT-P): a later span is bounded only where no stay in another theater may reach 72 h
    before it ends, counted from the stay's earliest start (a span may have begun it), not its latest. By hand, 2
    pilots (_nrt_stay): the first span moved him (the LAX release to an NRT report), so his NRT-theater stay may have
    begun at 13:15 HST Apr 1 (else at the KIX block-in 11:00 Apr 2): 72 h from the earliest is 13:15 Apr 4, before the
    end of a span Apr 4 14:00-16:00, so a report inside it may follow 72 h there, at a station whose clock is not on
    file: the lowest row, 8:30; 11:45 is over it: '? SHORT of 11:45 if it applies', no rest flag (pwa_rest is 10.E.1.a's
    11:00 at home, 10:15 free; on the latest start it would be bounded on NRT 12:00 acclimated and HNL 10:30 less 0:30,
    13:30, with no line and met). The second span Apr 4 11:00-13:00 ends before 13:15: bounded, no line, met. With
    KIX-NRT reported at JFK instead (a duty that does not start where the last one ended), the stay a duty in the first
    span may have begun is cut away (no station is within 60 deg of NRT, KIX and JFK), and the earliest start of his
    KIX stay alone keeps the later span from being bounded: the lowest row, '?' (on its latest start: met)."""
    ds, u = _nrt_stay((at(2027, 4, 4, "14:00"), at(2027, 4, 4, "16:00")))
    assert TO._acc_bound([TO._prep(d) for d in ds], 3, (), u) is None
    t = TO.duty_timeout(ds, 4, 2, "roster", "332", unknown=u)
    assert (t["rest"]["ok"], t["rest"]["free"], t["rest"]["cite"]) == (None, "10:15", "FAR 117.25(g)")
    assert t["flags"] == ["pwa_rest"]
    assert any(s.startswith("Rest after deadhead transportation (FAR 117.25(g)") and "over its Table B FDP 8:30 (the "
               "lowest row on any clock, less 0:30: acclimation not known)" in s and s.endswith(
                   "10:15 free: ? SHORT of 11:45 if it applies.") for s in t["lines"])
    ds, u = _nrt_stay((at(2027, 4, 4, "11:00"), at(2027, 4, 4, "13:00")))
    assert TO._acc_bound([TO._prep(d) for d in ds], 3, (), u) is not None
    t = TO.duty_timeout(ds, 4, 2, "roster", "332", unknown=u)
    assert t["rest"]["ok"] is True and not any(s.startswith("Rest after deadhead") for s in t["lines"])
    ds, u = _nrt_stay((at(2027, 4, 4, "14:00"), at(2027, 4, 4, "16:00")))
    ds[2] = _duty(at(2027, 4, 3, "20:00"), _leg("JFK", "NRT", at(2027, 4, 3, "21:00"), at(2027, 4, 3, "23:00"), "3"))
    assert TO._acc_bound([TO._prep(d) for d in ds], 3, (), u) is None
    t = TO.duty_timeout(ds, 4, 2, "roster", "332", unknown=u)
    assert t["rest"]["ok"] is None and any(s.startswith("Rest after deadhead") and "8:30 (the lowest row" in s
                                           for s in t["lines"])


def test_the_early_stay_fork_holds_at_exactly_72_h_and_only_from_the_first_leg_after_the_span():
    """Review round 5, fix 2 (RF1-MUT M6 and M13, V6-MUT-N): RV5-1-STAY's fork pinned at its edges. By hand, 2 pilots:
    - HNL-LAX (release 11:30 HST Apr 1), a span Apr 1 12:00-Apr 2 20:00 (32:30 from the release: bounded), NRT-SIN
      (report 22:00 HST Apr 2, in 06:00 Apr 3), a SIN-HNL deadhead only reporting 11:30 HST Apr 4 (05:30 SGT Apr 5),
      in 00:15 Apr 5 (12:45). The span may have moved him to the NRT-SIN theater at the 11:30 release: exactly 72:00
      there by the report (FAR 117.3: 72 h acclimates), so acclimated: SIN 05:30, row 0500-0559, 12:00; or not: HNL
      11:30 less 0:30, 13:30. 12:45 is over 12:00 only: '? SHORT of 12:45 if it applies'. Reported 11:29 (71:59): only
      HNL 13:30 (HNL 11:29 is in the same row), no line, met;
    - HNL-LAX (release 12:30 HST Apr 1), a span Apr 1 13:00-Apr 2 22:00, NRT-SFO-SIN (report 23:00 HST Apr 2;
      NRT-SFO leaves the NRT theater on the first leg, SFO-SIN in 02:00 Apr 4), a SIN-HNL deadhead only reporting 14:00
      HST Apr 4 (08:00 SGT Apr 5), in 02:30 Apr 5 (12:30), HNL-LAX 10:00 after its release. His stay in SIN's theater
      begins at 02:00 Apr 4 (the first leg took him out), not at the span: not acclimated, HNL 14:00 less 0:30, row
      1300-1659, 11:30: SHORT, 12:30 needed (read from the span's start, SIN 08:00, row 0700-1159, 14:00, would make it
      a '?')."""
    a = _duty(at(2027, 4, 1, "06:00"), _leg("HNL", "LAX", at(2027, 4, 1, "07:00"), at(2027, 4, 1, "11:15"), "1"))
    b = _duty(at(2027, 4, 2, "22:00"), _leg("NRT", "SIN", at(2027, 4, 2, "23:00"), at(2027, 4, 3, "06:00"), "2"))
    u = [(at(2027, 4, 1, "12:00"), at(2027, 4, 2, "20:00"))]
    for rep, bnd, ok in ((at(2027, 4, 4, "11:30"), [("SIN", False), ("HNL", True)], None),
                         (at(2027, 4, 4, "11:29"), [("HNL", True)], True)):
        c = _duty(rep, _leg("SIN", "HNL", rep + timedelta(hours=1), rep + timedelta(hours=12, minutes=45), "3",
                            dh=True))
        ds = [a, b, c, _lax(rep + timedelta(hours=23, minutes=45))]  # release 0:30 after the in, then 10:30
        assert TO._acc_bound([TO._prep(d) for d in ds], 2, (), u)[0] == bnd, rep
        t = TO.duty_timeout(ds, 3, 2, "roster", "332", unknown=u)
        assert (t["rest"]["ok"], t["rest"]["free"]) == (ok, "10:30"), rep
        assert any(s.startswith("Rest after deadhead") and "over its Table B FDP 12:00 (SIN time)" in s and s.endswith(
            "10:30 free: ? SHORT of 12:45 if it applies.") for s in t["lines"]) == (ok is None), rep
    a = _duty(at(2027, 4, 1, "06:00"), _leg("HNL", "LAX", at(2027, 4, 1, "07:00"), at(2027, 4, 1, "12:15"), "1"))
    b = _duty(at(2027, 4, 2, "23:00"), _leg("NRT", "SFO", at(2027, 4, 3, "00:00"), at(2027, 4, 3, "09:00"), "2"),
              _leg("SFO", "SIN", at(2027, 4, 3, "10:00"), at(2027, 4, 4, "02:00"), "3"))
    c = _duty(at(2027, 4, 4, "14:00"),
              _leg("SIN", "HNL", at(2027, 4, 4, "15:00"), at(2027, 4, 5, "02:30"), "4", dh=True))
    ds, u = [a, b, c, _lax(at(2027, 4, 5, "13:00"))], [(at(2027, 4, 1, "13:00"), at(2027, 4, 2, "22:00"))]
    assert TO._acc_bound([TO._prep(d) for d in ds], 2, (), u) == ([("HNL", True)], False)
    t = TO.duty_timeout(ds, 3, 2, "roster", "332", unknown=u)
    assert (t["rest"]["ok"], t["rest"]["need"], t["rest"]["free"]) == (False, "12:30", "10:00") and "rest" in t["flags"]


def test_more_bounded_walks_than_the_cap_keep_the_lowest_row(monkeypatch):
    """Review round 5, fix 2 (V6-MUT-T): past timeout.ACC_WALKS bounded walks the bound gives up (the lowest row
    stays), never a part of the readings. By hand: _kix_jfk's two spans (four walks): with the cap at 64, KIX less 0:30
    (10:30) and a sure SHORT of 12:30; with the cap at 1 the bound is None and the deadhead's line takes the lowest row
    on any clock, 8:30: '? SHORT of 12:30 if it applies'."""
    ds, u = _kix_jfk()
    assert TO._acc_bound([TO._prep(d) for d in ds], 2, (), u) == ([("KIX", True)], False)
    monkeypatch.setattr(TO, "ACC_WALKS", 1)
    assert TO._acc_bound([TO._prep(d) for d in ds], 2, (), u) is None
    t = TO.duty_timeout(ds, 3, 2, "roster", "332", unknown=u)
    assert t["rest"]["ok"] is None and any(s.startswith("Rest after deadhead") and "over its Table B FDP 8:30 (the "
                                           "lowest row on any clock" in s for s in t["lines"])


def test_a_call_back_window_takes_2_x_the_duty_period_when_that_is_over_18_h():
    """Review round 5, fix 2 (RF1-MUT M1): R5V-3's call-back window is the longest 10.E rest that may apply, 2 x the
    Duty Period or 18:00. By hand, 3 pilots: HNL-LAX (report 06:00 HST Apr 5, in 15:45, release 16:00: a 10:00 Duty
    Period, 2 x = 20:00), a span Apr 6 11:00-12:00 (19:00 after the release: inside the 20:00 rest, past 18:00), LAX-HNL
    reporting 06:30 HST Apr 8: at least 42:30, at most 62:30. A call-back in the span makes 06:00 Apr 5 to 12:00 Apr 6
    one Duty Period, 30:00, 2 x = 60:00: '? not known: met only if no duty in the span needs more (62:30 since that
    release)', rest_q (on 18:00 alone: 2 x the longer of 10:00 and 20:00 = 40:00, met by 2:30)."""
    d0 = _duty(at(2027, 4, 5, "06:00"), _leg("HNL", "LAX", at(2027, 4, 5, "07:00"), at(2027, 4, 5, "15:45"), "1"))
    t = TO.duty_timeout([d0, _lh(at(2027, 4, 8, "06:30"))], 1, 3, "roster", "332",
                        unknown=[(at(2027, 4, 6, "11:00"), at(2027, 4, 6, "12:00"))])
    assert (t["pwa"]["rest"]["ok"], t["pwa"]["rest"]["have"], t["flags"]) == (None, "42:30", ["rest_q"])
    assert any(s.startswith("PWA rest before this duty (10.E.1.a.1)") and "(10.F.1) at most 30:00, 2 x = 60:00" in s
               and s.endswith("? not known: met only if no duty in the span needs more (62:30 since that release).")
               for s in t["lines"])


def test_10e1b_is_never_short_across_a_span_not_on_file():
    """Review round 5, fix 2 (V6-MUT-AM): 10.E.1.b's 18:00 is set by the duty before it as well as the one reported for,
    so across a span not on file it stays a '?' even when the most the rest can be is under 18:00 (RV5-2 makes only the
    needs that hold whatever the duty before was sure). By hand, 2 pilots: HNL-LAX (release 14:30 HST Apr 1), a span
    Apr 2 01:00-02:00, LAX-SFO-HNL reporting 07:00 HST Apr 2 (LAX-SFO departs 15:30 PDT, a 13:00 Duty Period): at
    least 5:00, at most 16:30: '? not known', no pwa_rest flag (a sure SHORT would read 'at most 16:30 of 18:00')."""
    d0 = _duty(at(2027, 4, 1, "08:00"), _leg("HNL", "LAX", at(2027, 4, 1, "09:00"), at(2027, 4, 1, "14:15"), "1"))
    d1 = _duty(at(2027, 4, 2, "07:00"), _leg("LAX", "SFO", at(2027, 4, 2, "12:30"), at(2027, 4, 2, "13:45"), "2"),
               _leg("SFO", "HNL", at(2027, 4, 2, "14:30"), at(2027, 4, 2, "19:45"), "3"))
    t = TO.duty_timeout([d0, d1], 1, 2, "roster", "332", unknown=[(at(2027, 4, 2, "01:00"), at(2027, 4, 2, "02:00"))])
    r = t["pwa"]["rest"]
    assert (r["need"], r["ok"], r["cite"], r["late"]) == ("18:00", None, "10.E.1.b", True)
    assert "pwa_rest" not in t["flags"] and "rest_q" in t["flags"]
    assert ("PWA 10.E.1.b (18:00 rest when a segment departs 1400-0359 local and the scheduled Duty Period is 12:00+): "
            "applies (LAX-SFO departs 15:30 PDT, scheduled Duty Period 13:00); at least 5:00 free (a span of your line "
            "before it is not on file): ? not known.") in t["lines"]


def test_a_schedule_item_that_may_hold_a_deadhead_past_table_b_adds_a_far_117_25g_question():
    """Review round 5, fix 2 (RF1-ITEM-DEADHEAD): RV5-3 counts a schedule item that may be duty for FAR 117.25(e)'s 10 h
    only inside the 10 h, but an item may hold deadhead transportation past its Table B FDP, which needs a rest as long
    as it (117.25(g)); d7227a0 read any item as a '?'. Now an item, joined to a span not on file or another item it
    touches, that runs over 8:30 (the lowest Table B row, 9:00, less 0:30) is a 117.25(g) reading that only adds a '?':
    the longer of 10 h and its length, met only when the time since it ended meets that. By hand, 2 pilots, _g0
    (release 19:00 HST Apr 5):
    - a whole-day item Apr 6 00:00-Apr 7 00:00 (working.py's HST day), HNL-LAX reporting 12:00 HST Apr 7: 41:00 free,
      the 10 h met (the item ends 12:00 before it, 2:00 spare from it); the item runs 24:00, so 24:00 needed, 12:00
      since it: '?', rest_q, cite FAR 117.25(g) (round 5 and fix 1: met; with that day a JFK-HNL deadhead of 13:30 on
      file: SHORT, 14:30 needed). Reporting 00:00 Apr 8: 24:00 since it, met. With a 1 h item 06:00-07:00 Apr 7 too and
      the report 06:00 Apr 8: 30:00 since the day, but the rest before the FDP is counted from the last item that may
      be duty, 23:00: '?' (the 10 h met);
    - a span Apr 6 00:00-06:00 and an item 06:00-12:00: one stretch of 12:00, HNL-LAX reporting 23:00 HST Apr 6: the
      10 h met (the item ends 11:00 before), 12:00 needed, 11:00 since: '?'; reporting 00:00 Apr 7: met. Each alone
      (6:00) holds no deadhead past any Table B row: no line.
    Review round 6 (V7-ITEM-TXT, UI7-1, V7-STRETCH-SPAN-WORDS): the FAR rest row gives the figure the '?' is judged on,
    the time since the stretch's last piece: '41:00 free (12:00 since a schedule item that may be duty)' (round 5, fix
    2: '41:00 free', as if 41:00 were judged against 24:00) and, with the 1 h item, '59:00 free (23:00 since ...)'; its
    '?' names both kinds when the stretch holds a span and an item (at least 17:00 free since the span's end 06:00,
    11:00 since the item's end 12:00); and the 1 h item of Apr 7, not part of the 24:00 stretch the line describes, is
    'a schedule item', not 'the'."""
    item = [(at(2027, 4, 6, "00:00"), at(2027, 4, 7, "00:00"))]
    t = TO.duty_timeout([_g0(), _lax(at(2027, 4, 7, "12:00"))], 1, 2, "roster", "332", busy=item)
    assert (t["rest"]["ok"], t["rest"]["cite"], t["flags"]) == (None, "FAR 117.25(g)", ["rest_q"])
    assert t["rest"]["txt"] == ("41:00 free (12:00 since a schedule item that may be duty), 24:00 needed (FAR "
                                "117.25(g)): ? (a schedule item that may be duty; if it applies)")
    assert ("Rest after deadhead transportation (FAR 117.25(g), FOM 4.3.2.10): a deadhead inside the schedule item "
            "that may be duty may need more (FAR 117.25(g), FOM 4.3.2.10): it runs 24:00 (00:00 HST Tue Apr 6 to "
            "00:00 HST Wed Apr 7), over 8:30 (the lowest Table B row less 0:30), so a deadhead in it may have run past "
            "its Table B FDP and need a rest as long (at most 24:00), no less than 10 h; 12:00 free since the schedule "
            "item that may be duty ending 00:00 HST Wed Apr 7: ? not known: short if a deadhead in it ran past its "
            "Table B FDP.") in t["lines"]
    assert any(s.startswith("Rest before this FDP (FAR 117.25(e)") and s.endswith("2:00 spare from it.")
               for s in t["lines"])
    t = TO.duty_timeout([_g0(), _lax(at(2027, 4, 8, "06:00"))], 1, 2, "roster", "332",
                        busy=item + [(at(2027, 4, 7, "06:00"), at(2027, 4, 7, "07:00"))])
    assert (t["rest"]["ok"], t["rest"]["cite"]) == (None, "FAR 117.25(g)") and any(
        s.startswith("Rest after deadhead") and "it runs 24:00 (00:00 HST Tue Apr 6 to 00:00 HST Wed Apr 7)" in s and
        "23:00 free since a schedule item that may be duty ending 07:00 HST Wed Apr 7" in s for s in t["lines"])
    assert t["rest"]["txt"].startswith("59:00 free (23:00 since a schedule item that may be duty), 24:00 needed")
    t = TO.duty_timeout([_g0(), _lax(at(2027, 4, 8, "00:00"))], 1, 2, "roster", "332", busy=item)
    assert (t["rest"]["ok"], t["flags"]) == (True, []) and any(
        s.startswith("Rest after deadhead") and s.endswith("24:00 free since the schedule item that may be duty ending "
                                                            "00:00 HST Wed Apr 7: met.") for s in t["lines"])
    u, b = [(at(2027, 4, 6, "00:00"), at(2027, 4, 6, "06:00"))], [(at(2027, 4, 6, "06:00"), at(2027, 4, 6, "12:00"))]
    t = TO.duty_timeout([_g0(), _lax(at(2027, 4, 6, "23:00"))], 1, 2, "roster", "332", busy=b, unknown=u)
    assert (t["rest"]["ok"], t["rest"]["cite"]) == (None, "FAR 117.25(g)")
    assert t["rest"]["txt"] == ("at least 17:00 free (11:00 since a schedule item that may be duty), 12:00 needed (FAR "
                                "117.25(g)): ? (a span of your line not on file and a schedule item that may be duty; "
                                "if it applies)")
    assert any(s.startswith("Rest after deadhead transportation (FAR 117.25(g), FOM 4.3.2.10): a deadhead inside the "
                            "span of your line not on file and the schedule item that may be duty in or next to it may "
                            "need more") and "it runs 12:00 (00:00 HST Tue Apr 6 to 12:00 HST Tue Apr 6)" in s
               and s.endswith("11:00 free since the schedule item that may be duty ending 12:00 HST Tue Apr 6: ? not "
                              "known: short if a deadhead in it ran past its Table B FDP.") for s in t["lines"])
    t = TO.duty_timeout([_g0(), _lax(at(2027, 4, 7, "00:00"))], 1, 2, "roster", "332", busy=b, unknown=u)
    assert t["rest"]["ok"] is True
    for kw in ({"busy": b}, {"unknown": u}):
        t = TO.duty_timeout([_g0(), _lax(at(2027, 4, 6, "23:00"))], 1, 2, "roster", "332", **kw)
        assert t["rest"]["ok"] is True and not any(s.startswith("Rest after deadhead") for s in t["lines"]), kw


def test_a_report_at_a_station_with_no_longitude_counts_as_one_since_the_last_acclimation():
    """Review round 5, fix 2 (found checking the bound against fillings of the spans): an arrival at a station with no
    longitude made the theater of the walk not sure, but a report at one did not, so a duty reported there whose arrival
    is not on file (a span, or a gap in the line) left the walk sure of HNL's theater. By hand, 2 pilots: HNL-AKL-HNL
    (in 13:15 HST Apr 12), XYZ-KIX-NRT (report 07:25 HST Apr 14, in 23:25), an NRT-HNL deadhead only reporting 09:15 HST
    Apr 16 (33:20 free), in 23:00 (13:45), HNL-LAX 11:30 after its release (23:30). Round 5, fix 1, with no span: not
    acclimated, HNL 09:15 less 0:30, row 0700-1159, 13:30: a sure SHORT. Now the lower of HNL less 0:30 and NRT's own
    clock (04:15 JST, row 0400-0459, 10:00) with acclimation not known: '? SHORT of 13:45 if it applies', as the line
    with an HNL-XYZ leg on file reads; with a span Apr 12 13:45-18:45 the bound keeps the lowest row (8:30)."""
    a = _duty(at(2027, 4, 11, "16:00"), _leg("HNL", "AKL", at(2027, 4, 11, "17:15"), at(2027, 4, 12, "02:15"), "1"),
              _leg("AKL", "HNL", at(2027, 4, 12, "03:15"), at(2027, 4, 12, "13:15"), "2"))
    b = _duty(at(2027, 4, 14, "07:25"), _leg("XYZ", "KIX", at(2027, 4, 14, "08:25"), at(2027, 4, 14, "15:25"), "3"),
              _leg("KIX", "NRT", at(2027, 4, 14, "16:25"), at(2027, 4, 14, "23:25"), "4"))
    c = _duty(at(2027, 4, 16, "09:15"),
              _leg("NRT", "HNL", at(2027, 4, 16, "10:30"), at(2027, 4, 16, "23:00"), "5", dh=True))
    ds = [a, b, c, _lax(at(2027, 4, 17, "11:00"))]
    t = TO.duty_timeout(ds, 3, 2, "roster", "332")
    assert t["rest"]["ok"] is None and "rest" not in t["flags"]
    assert any(s.startswith("Rest after deadhead") and "over its Table B FDP 10:00 (NRT time)" in s and s.endswith(
        "11:30 free: ? SHORT of 13:45 if it applies.") for s in t["lines"])
    x = _duty(at(2027, 4, 12, "15:00"), _leg("HNL", "XYZ", at(2027, 4, 12, "16:00"), at(2027, 4, 12, "18:00"), "6"))
    t2 = TO.duty_timeout([a, x, b, c, ds[3]], 4, 2, "roster", "332")
    assert t2["rest"]["ok"] is None and [s for s in t2["lines"] if s.startswith("Rest after deadhead")] == [
        s for s in t["lines"] if s.startswith("Rest after deadhead")]
    u = [(at(2027, 4, 12, "13:45"), at(2027, 4, 12, "18:45"))]
    assert TO._acc_bound([TO._prep(d) for d in ds], 2, (), u) is None
    t = TO.duty_timeout(ds, 3, 2, "roster", "332", unknown=u)
    assert t["rest"]["ok"] is None and any(s.startswith("Rest after deadhead") and "over its Table B FDP 8:30 (the "
                                           "lowest row on any clock" in s for s in t["lines"])


def test_a_duty_inside_a_span_may_begin_a_stay_at_a_station_not_on_file():
    """Review round 5, fix 2 (found checking the bound against fillings of the spans): a span read as duty may hold a
    block-in at any station, and a stay begun there (FAR 117.3's theater: 60 degrees around the station it began at,
    the walk's own model) holds while every station he is at since is within 60 degrees of it. By hand, 2 pilots:
    LIH-LAX (release 02:10 HST Feb 17), a span Feb 17 02:55-Feb 18 08:55 (30:45 from the release: bounded),
    LAX-JFK (report 14:55 HST Feb 19, in 01:55 Feb 20), a JFK-HNL deadhead only reporting 17:25 HST Feb 20 (22:25 EST),
    in 04:40 Feb 21 (11:15), HNL-OGG 10:30 after its release. The walks of fix 1's bound: never acclimated to JFK's
    theater, HNL 17:25 less 0:30, row 1700-2159, 11:30: no line, met. A LAX-ORD-LAX duty in the span (in LAX 14:30 Feb
    17) begins a stay at ORD, whose 60 degrees hold LAX and JFK: 86:30 there by the deadhead's report from the span's
    start (review round 6, CV7-1: the span's start; round 5, fix 2 counted 87:15 from the release before it), so
    acclimated: JFK 22:25, row 2200-2259, 11:00: '? SHORT of 11:15 if it applies' (with that duty on file: SHORT,
    11:15 needed)."""
    a = _duty(at(2027, 2, 16, "19:55"), _leg("LIH", "LAX", at(2027, 2, 16, "20:55"), at(2027, 2, 17, "01:55"), "1"))
    b = _duty(at(2027, 2, 19, "14:55"), _leg("LAX", "JFK", at(2027, 2, 19, "15:55"), at(2027, 2, 20, "01:55"), "2"))
    c = _duty(at(2027, 2, 20, "17:25"),
              _leg("JFK", "HNL", at(2027, 2, 20, "18:40"), at(2027, 2, 21, "04:40"), "3", dh=True))
    rep = at(2027, 2, 21, "15:25")
    d = _duty(rep, _leg("HNL", "OGG", rep + timedelta(hours=1), rep + timedelta(hours=1, minutes=40), "4"))
    u = [(at(2027, 2, 17, "02:55"), at(2027, 2, 18, "08:55"))]
    ds = [a, b, c, d]
    assert TO._acc_bound([TO._prep(x) for x in ds], 2, (), u) == ([("HNL", True), ("JFK", False)], None)
    t = TO.duty_timeout(ds, 3, 2, "roster", "332", unknown=u)
    assert t["rest"]["ok"] is None and "rest" not in t["flags"]
    assert any(s.startswith("Rest after deadhead") and "over its Table B FDP 11:00 (JFK time)" in s and
               "another reading of its acclimation gives 11:30" in s and s.endswith(
                   "10:30 free: ? SHORT of 11:15 if it applies.") for s in t["lines"])
    x = _duty(at(2027, 2, 17, "04:00"), _leg("LAX", "ORD", at(2027, 2, 17, "05:00"), at(2027, 2, 17, "09:00"), "5"),
              _leg("ORD", "LAX", at(2027, 2, 17, "10:00"), at(2027, 2, 17, "14:30"), "6"))
    t = TO.duty_timeout([a, x, b, c, d], 4, 2, "roster", "332")
    assert (t["rest"]["ok"], t["rest"]["need"], t["rest"]["cite"]) == (False, "11:15", "FAR 117.25(g)")


def test_after_a_span_read_as_duty_a_block_in_on_file_may_have_ended_his_stay():
    """Review round 5, fix 2 (found checking the bound against fillings of the spans): after a span read as duty his
    stay's station may be one the span left him at, not the first block-in after it, so a later block-in on file may
    have ended a stay the walk counts. By hand, 2 pilots: HNL-HKG (in 12:00 HST Apr 1), a span at HKG Apr 1 18:00-20:00,
    SIN-AKL (report 06:00 HST Apr 2, in 16:00), SIN-ICN-HNL (report 06:00 HST Apr 4, 37:30 free: acclimated to SIN; in
    HNL 21:00), an HNL-JFK deadhead only reporting 08:00 HST Apr 6 (02:00 SGT Apr 7), in 19:00 (11:00), JFK-BOS 10:30
    after its release. Read from the AKL block-in (16:00 Apr 2) his stay holds ICN and HNL: 88:00 by the report,
    acclimated to HNL's theater, HNL 08:00, row 0700-1159, 14:00: no line, met (round 5 and fix 1). Had the span left
    him in a stay begun at ICN (HKG-BOS-ICN-SIN), AKL is inside its 60 degrees and HNL is not: the stay ends at the HNL
    block-in, 11:00 by the report, not acclimated: SIN 02:00 less 0:30, row 0000-0359, 8:30: '? SHORT of 11:00 if it
    applies' (with that duty on file: SHORT, 11:00 needed)."""
    d0 = _duty(at(2027, 4, 1, "00:00"), _leg("HNL", "HKG", at(2027, 4, 1, "01:00"), at(2027, 4, 1, "12:00"), "1"))
    d1 = _duty(at(2027, 4, 2, "06:00"), _leg("SIN", "AKL", at(2027, 4, 2, "07:00"), at(2027, 4, 2, "16:00"), "2"))
    d2 = _duty(at(2027, 4, 4, "06:00"), _leg("SIN", "ICN", at(2027, 4, 4, "07:00"), at(2027, 4, 4, "12:00"), "3"),
               _leg("ICN", "HNL", at(2027, 4, 4, "13:00"), at(2027, 4, 4, "21:00"), "4"))
    d3 = _duty(at(2027, 4, 6, "08:00"),
               _leg("HNL", "JFK", at(2027, 4, 6, "09:00"), at(2027, 4, 6, "19:00"), "5", dh=True))
    rep = at(2027, 4, 7, "05:45")
    d4 = _duty(rep, _leg("JFK", "BOS", rep + timedelta(hours=1), rep + timedelta(hours=2), "6"))
    u = [(at(2027, 4, 1, "18:00"), at(2027, 4, 1, "20:00"))]
    ds = [d0, d1, d2, d3, d4]
    assert TO._acc_bound([TO._prep(x) for x in ds], 3, (), u) == ([("HNL", False), ("SIN", True)], None)
    t = TO.duty_timeout(ds, 4, 2, "roster", "332", unknown=u)
    assert (t["rest"]["ok"], t["rest"]["free"]) == (None, "10:30") and "rest" not in t["flags"]
    assert any(s.startswith("Rest after deadhead") and "over its Table B FDP 8:30 (SIN time, less 0:30" in s and
               "another reading of its acclimation gives 14:00" in s and s.endswith(
                   "10:30 free: ? SHORT of 11:00 if it applies.") for s in t["lines"])
    t = TO.duty_timeout(ds, 4, 2, "roster", "332")
    assert t["rest"]["ok"] is True and not any(s.startswith("Rest after deadhead") for s in t["lines"])
    x = _duty(at(2027, 4, 1, "18:00"), _leg("HKG", "BOS", at(2027, 4, 1, "18:10"), at(2027, 4, 1, "18:40"), "7"),
              _leg("BOS", "ICN", at(2027, 4, 1, "18:45"), at(2027, 4, 1, "19:10"), "8"),
              _leg("ICN", "SIN", at(2027, 4, 1, "19:15"), at(2027, 4, 1, "19:30"), "9"))
    t = TO.duty_timeout([d0, x, d1, d2, d3, d4], 5, 2, "roster", "332")
    assert (t["rest"]["ok"], t["rest"]["need"], t["rest"]["cite"]) == (False, "11:00", "FAR 117.25(g)")


def test_a_stay_a_duty_inside_a_span_may_begin_and_that_reaches_72_h_inside_a_later_span_is_not_bounded():
    """Review round 5, fix 2 (found checking the bound against fillings of the spans): a stay a duty inside a span may
    have begun at a station not on file may reach 72 h inside a later span, and a report there at a station outside
    the theater he is acclimated to may acclimate him to it. By hand, 2 pilots: HNL-SYD (release 23:30 HST Jan 10), a
    span Jan 11 04:30-21:10, SYD-SIN (report 01:50 HST Jan 14, in 10:00), a span at SIN Jan 14 18:50-23:50, an SFO-HNL
    deadhead only reporting 06:40 HST Jan 16 (08:40 PST), in 17:40 (11:00), HNL-AKL 10:30 after its release. A stay
    begun in the first span at a station whose 60 degrees hold SYD and SIN (SYD, SIN, HKG ...; not all in HNL's theater)
    is 72 h old by 04:30 Jan 14 (from the span's start, review round 6; round 5, fix 2: from the release, 23:30 Jan
    13), before the second span ends: the lowest row, 8:30, '? SHORT of 11:00 if it applies'
    (round 5 and fix 1: HNL 06:40, row 0600-0659, 13:00, SFO 08:40, 14:00, HNL less 0:30 12:30: no line, met). With
    SYD-BOS-SYD in the first span (in SYD 17:50 Jan 11) and SIN-SFO reported at SIN 20:38 Jan 14 (74:47 in that
    theater: acclimated to SIN) on file: SFO not acclimated, SIN 00:40 less 0:30, row 0000-0359, 8:30: SHORT. The second
    span alone: bounded (HNL 13:00, SFO 14:00, HNL less 0:30 12:30), met."""
    d0 = _duty(at(2027, 1, 10, "13:00"), _leg("HNL", "SYD", at(2027, 1, 10, "14:00"), at(2027, 1, 10, "23:00"), "1"))
    d1 = _duty(at(2027, 1, 14, "01:50"), _leg("SYD", "SIN", at(2027, 1, 14, "02:50"), at(2027, 1, 14, "10:00"), "2"))
    d2 = _duty(at(2027, 1, 16, "06:40"),
               _leg("SFO", "HNL", at(2027, 1, 16, "07:40"), at(2027, 1, 16, "17:40"), "3", dh=True))
    rep = at(2027, 1, 17, "04:25")
    d3 = _duty(rep, _leg("HNL", "AKL", rep + timedelta(hours=1), rep + timedelta(hours=8), "4"))
    u = [(at(2027, 1, 11, "04:30"), at(2027, 1, 11, "21:10")), (at(2027, 1, 14, "18:50"), at(2027, 1, 14, "23:50"))]
    ds = [d0, d1, d2, d3]
    assert TO._acc_bound([TO._prep(d) for d in ds], 2, (), u) is None
    t = TO.duty_timeout(ds, 3, 2, "roster", "332", unknown=u)
    assert (t["rest"]["ok"], t["rest"]["free"]) == (None, "10:30") and "rest" not in t["flags"]
    assert any(s.startswith("Rest after deadhead") and "over its Table B FDP 8:30 (the lowest row on any clock" in s and
               s.endswith("10:30 free: ? SHORT of 11:00 if it applies.") for s in t["lines"])
    assert TO._acc_bound([TO._prep(d) for d in ds], 2, (), u[1:]) == ([("HNL", False), ("SFO", False), ("HNL", True)],
                                                                       None)
    t = TO.duty_timeout(ds, 3, 2, "roster", "332", unknown=u[1:])
    assert t["rest"]["ok"] is True and not any(s.startswith("Rest after deadhead") for s in t["lines"])
    x1 = _duty(at(2027, 1, 11, "12:00"), _leg("SYD", "BOS", at(2027, 1, 11, "13:00"), at(2027, 1, 11, "15:00"), "5"),
               _leg("BOS", "SYD", at(2027, 1, 11, "16:00"), at(2027, 1, 11, "17:50"), "6"))
    x2 = _duty(at(2027, 1, 14, "20:38"), _leg("SIN", "SFO", at(2027, 1, 14, "21:38"), at(2027, 1, 14, "22:39"), "7"))
    t = TO.duty_timeout([d0, x1, d1, x2, d2, d3], 5, 2, "roster", "332")
    assert (t["rest"]["ok"], t["rest"]["need"], t["rest"]["cite"]) == (False, "11:00", "FAR 117.25(g)")


def test_card_shows_the_margin_from_a_schedule_item_without_sideways_scroll(browser, tmp_path):
    """Review round 5, fix 1 (UI5-2): the FAR rest row and the PWA row carry the margin from a schedule item that may be
    duty ("(11:30 after a schedule item that may be duty)"); the longer rows wrap at 390 and 320 px with no sideways
    scroll and no chip (the rest is met). By hand: _g0 (release 19:00 HST Apr 5), training Apr 6 06:00-07:30, HNL-LAX
    reporting 19:00 HST Apr 6: 24:00 free, 11:30 after the item."""
    g1 = _duty(at(2027, 4, 6, "19:00"), _leg("HNL", "LAX", at(2027, 4, 6, "20:00"), at(2027, 4, 7, "01:15"), "3"))
    t = TO.duty_timeout([_g0(), g1], 1, 2, "roster", "332", busy=[(at(2027, 4, 6, "06:00"), at(2027, 4, 6, "07:30"))])
    for width in (390, 320):
        pg = browser.new_page(viewport={"width": width, "height": 844})
        pg.set_content(_page(_watcher_pwa(tmp_path, _graft(t))))
        card = pg.locator("flight-watcher-layover-card")
        box = card.locator("[data-to]")
        assert box.locator("[data-towarn]").all_inner_texts() == []
        box.click()
        far, pwa = card.locator("[data-tofar]"), card.locator("[data-topwa]")
        assert far.inner_text() == ("FAR rest: 24:00 free (11:30 after a schedule item that may be duty), 10:00 needed "
                                    "(FAR 117.25(e)): met"), (width, far.inner_text())
        row = "rest 24:00 (11:30 after a schedule item that may be duty), 11:00 needed (10.E.1.a): met"
        assert row in pwa.inner_text(), (width, pwa.inner_text())
        assert pg.evaluate("document.documentElement.scrollWidth") <= width
        pg.close()


# ------------------------------------------------------------ review round 6 (the round-5 final recheck's findings)
def _syd_line(c_or_dh):
    """HNL-LAX (report 06:00 HST Apr 30, in 12:15, release 12:30), LAX-SYD (report 18:00 HST May 2, in 10:00 May 3,
    release 10:30, customs), then the duties given; the span Apr 30 13:00-May 2 06:00 (41:30 after the release)."""
    a = _duty(at(2027, 4, 30, "06:00"), _leg("HNL", "LAX", at(2027, 4, 30, "07:00"), at(2027, 4, 30, "12:15"), "1"))
    b = _duty(at(2027, 5, 2, "18:00"), _leg("LAX", "SYD", at(2027, 5, 2, "19:00"), at(2027, 5, 3, "10:00"), "2"))
    return [a, b] + list(c_or_dh), [(at(2027, 4, 30, "13:00"), at(2027, 5, 2, "06:00"))]


def test_after_36_h_free_on_file_past_the_last_span_a_deadhead_reads_every_clock_of_that_theater():
    """Review round 6 (CV7-1): where the bound fails (here a span with 41:30 of free time on file before its end: a
    report inside it may follow 36 h free) round 5, fix 2 kept the lowest row on any clock, 8:30, though 36 h free on
    file after the last span acclimates him (FAR 117.3) to a theater that holds that station; only its reference is not
    known (any station within 60 deg of it). By hand, 2 pilots (_syd_line):
    - a SYD-HNL deadhead only reporting 18:30 HST May 5 (04:30 UTC May 6; 56:00 free since the 10:30 May 3 release, no
      span after it): every reference within 60 deg of SYD reads 12:00 at that time (HNL 18:30, row 1700-2159; SYD
      14:30 AEST and NRT 13:30, row 1300-1659; AKL 16:30 NZST; PPG 17:30; ANC 20:30 AKDT) but the clocks 8 h ahead of
      UTC, 13:00 (SIN and HKG 12:30, row 1200-1259). In 07:45 May 6 (13:15), over 13:00: SHORT, 13:15 needed, 10:30
      free, flagged (round 5, fix 2: '? SHORT of 13:15 if it applies' on 8:30). In 07:15 (12:45): over 12:00 only, '?
      SHORT of 12:45 if it applies' (the walk's own reading, SYD 12:00 alone, would make it a sure SHORT);
    - SYD-NRT reporting 18:30 HST May 5 (in 05:00 May 6, release 05:30), an NRT-HNL deadhead only reporting 23:00 HST
      May 6 (09:00 UTC, 17:30 free), in 11:30 May 7 (12:30): from SYD each reference walked on: within 60 deg of NRT,
      its clock or NRT's (12:00 for the clocks 8 to 12 h ahead of UTC, PPG 22:00 11:00, RAR 23:00 10:00); farther,
      NRT's own (his stay in SYD's theater may be 72 h old: a fork) or not acclimated, that clock less 0:30 (HNL 23:00,
      row 2300-2359, 10:00 less 0:30 = 9:30; ANC 01:00 AKDT, row 0000-0359, 9:00 less 0:30 = 8:30). 12:30 is over the
      highest, 12:00: SHORT, 12:30 needed (round 5, fix 2: the lowest row, '?')."""
    for dh, ok, flag in ((timedelta(hours=13, minutes=15), False, "rest"), (timedelta(hours=12, minutes=45), None, "")):
        rep = at(2027, 5, 5, "18:30")
        c = _duty(rep, _leg("SYD", "HNL", rep + timedelta(hours=1), rep + dh, "3", dh=True))
        ds, u = _syd_line([c, _lax(rep + dh + timedelta(hours=11))])
        pr = [TO._prep(d) for d in ds]
        assert TO._acc_bound(pr, 2, (), u) is None
        a_opts, a_st, a_stn = TO._acc_anchor(pr, 2, (), u)
        assert (a_stn, a_st, len(a_opts)) == ("SYD", True, 29) and ("SIN", False) in a_opts and ("HNL", False) in a_opts
        t = TO.duty_timeout(ds, 3, 2, "roster", "332", unknown=u)
        assert (t["rest"]["ok"], t["rest"]["free"], t["rest"]["cite"]) == (ok, "10:30", "FAR 117.25(g)"), dh
        assert ("rest" in t["flags"]) == bool(flag), dh
    assert any(s.startswith("Rest after deadhead") and "over its Table B FDP 12:00 (AKL time)" in s and
               "another reading of its acclimation gives 13:00" in s and s.endswith(
                   "10:30 free: ? SHORT of 12:45 if it applies.") for s in t["lines"])
    c = _duty(at(2027, 5, 5, "18:30"), _leg("SYD", "NRT", at(2027, 5, 5, "19:30"), at(2027, 5, 6, "05:00"), "3"))
    rep = at(2027, 5, 6, "23:00")
    dh = _duty(rep, _leg("NRT", "HNL", rep + timedelta(hours=1), rep + timedelta(hours=12, minutes=30), "4", dh=True))
    ds, u = _syd_line([c, dh, _lax(rep + timedelta(hours=23, minutes=30))])
    pr = [TO._prep(d) for d in ds]
    a_opts, a_st, a_stn = TO._acc_anchor(pr, 3, (), u)
    assert (a_stn, a_st) == ("SYD", None) and {("ANC", True), ("HNL", True), ("NRT", False)} <= set(a_opts)
    t = TO.duty_timeout(ds, 4, 2, "roster", "332", unknown=u)
    assert (t["rest"]["ok"], t["rest"]["need"], t["rest"]["cite"]) == (False, "12:30", "FAR 117.25(g)")
    assert any(s.startswith("Rest after deadhead") and "over its Table B FDP on every reading of its acclimation, 36 h "
               "free at SYD after a span of your line not on file: any theater that holds SYD, every clock within 60 "
               "deg of it (12:00 at most" in s for s in t["lines"])
    json.dumps(t)


def test_the_117_25g_stretch_is_one_piece_per_span_joined_only_where_pieces_touch():
    """Review round 6 (CV7-3): round 5, fix 2 made one piece of every span in the gap, from the earliest start to the
    latest end, the free line on file between them included, so two short spans far apart read as one long one that
    may hold a deadhead. Now each span is a piece of its own, clipped to the release and the report, and pieces join
    only where they touch. By hand, 2 pilots, _g0 (release 19:00 HST Apr 5):
    - spans Apr 5 20:00-21:00 and Apr 6 08:00-09:30, HNL-LAX reporting 22:00 HST Apr 6: 1:00 and 1:30, neither over
      8:30: no 117.25(g) line, at least 12:30 free, FAR and PWA met (11:00, and 12:00 at home after a span), no flag
      (round 5, fix 2: a 13:30 stretch, 13:30 needed, 12:30 since it: '?');
    - spans Apr 6 00:00-06:00 and 06:00-12:00 (touching), reporting 23:00 HST Apr 6: one stretch of 12:00, over 8:30:
      12:00 needed, at least 11:00 since its end: '?'; the second span from 06:30 (6:00 and 5:30): no line, met."""
    t = TO.duty_timeout([_g0(), _lax(at(2027, 4, 6, "22:00"))], 1, 2, "roster", "332",
                        unknown=[(at(2027, 4, 5, "20:00"), at(2027, 4, 5, "21:00")),
                                 (at(2027, 4, 6, "08:00"), at(2027, 4, 6, "09:30"))])
    assert (t["rest"]["ok"], t["rest"]["free"], t["pwa"]["rest"]["ok"], t["flags"]) == (True, "12:30", True, [])
    assert not any("117.25(g)" in s for s in t["lines"])
    u = [(at(2027, 4, 6, "00:00"), at(2027, 4, 6, "06:00")), (at(2027, 4, 6, "06:00"), at(2027, 4, 6, "12:00"))]
    t = TO.duty_timeout([_g0(), _lax(at(2027, 4, 6, "23:00"))], 1, 2, "roster", "332", unknown=u)
    assert t["rest"]["txt"] == ("at least 11:00 free, 12:00 needed (FAR 117.25(g)): ? (spans of your line not on file; "
                                "if it applies)")
    assert ("Rest after deadhead transportation (FAR 117.25(g), FOM 4.3.2.10): a deadhead inside the spans of your "
            "line not on file may need more (FAR 117.25(g), FOM 4.3.2.10): the spans run 12:00 (00:00 HST Tue Apr 6 to "
            "12:00 HST Tue Apr 6), over 8:30 (the lowest Table B row less 0:30), so a deadhead in them may have run "
            "past its Table B FDP and need a rest as long (at most 12:00), no less than 10 h; at least 11:00 free "
            "(since the end of the last of those spans): ? not known: short if a deadhead in the spans ran past its "
            "Table B FDP.") in t["lines"]
    u[1] = (at(2027, 4, 6, "06:30"), at(2027, 4, 6, "12:00"))
    t = TO.duty_timeout([_g0(), _lax(at(2027, 4, 6, "23:00"))], 1, 2, "roster", "332", unknown=u)
    assert t["rest"]["ok"] is True and not any("117.25(g)" in s for s in t["lines"])


def test_two_long_stretches_need_the_longest_even_when_it_comes_first():
    """Review round 6 (CV7-4: mutants Vmaxkey, BHneed_slen_tie): the stretch reading needs the longest stretch over
    8:30, not the last or the shortest. By hand, 2 pilots, _g0 (release 19:00 HST Apr 5): a whole-day item Apr 6
    (24:00) and a span Apr 7 06:00-16:00 (10:00, not touching it), HNL-LAX reporting 06:00 HST Apr 8: at least 14:00
    free since the span's end; the longest stretch, 24:00, comes first: 24:00 needed, '?', rest_q (on the 10:00 span:
    10:00 needed, met). The time is counted from the span, which is not part of the stretch the line describes, so the
    line names it with its end ('since the end of a span of your line not on file at 16:00 HST Wed Apr 7')."""
    t = TO.duty_timeout([_g0(), _lax(at(2027, 4, 8, "06:00"))], 1, 2, "roster", "332",
                        busy=[(at(2027, 4, 6, "00:00"), at(2027, 4, 7, "00:00"))],
                        unknown=[(at(2027, 4, 7, "06:00"), at(2027, 4, 7, "16:00"))])
    assert (t["rest"]["ok"], t["rest"]["free"], t["rest"]["cite"], t["flags"]) == (None, "14:00", "FAR 117.25(g)",
                                                                                   ["rest_q"])
    assert t["rest"]["txt"] == ("at least 14:00 free, 24:00 needed (FAR 117.25(g)): ? (a schedule item that may be "
                                "duty; if it applies)")
    assert any(s.startswith("Rest after deadhead") and "it runs 24:00 (00:00 HST Tue Apr 6 to 00:00 HST Wed Apr 7)" in s
               and s.endswith("at least 14:00 free (since the end of a span of your line not on file at 16:00 HST Wed "
                              "Apr 7): ? not known: short if a deadhead in it ran past its Table B FDP.")
               for s in t["lines"])


def test_a_report_outside_every_theater_a_stay_begun_in_a_span_may_hold_is_no_fork():
    """Review round 6 (CV7-4: mutant Gcut_rep): a stay a duty inside a span may have begun at a station not on file
    forks the reading only at a report within 60 deg of a station it may have begun at. By hand, 2 pilots: HNL-LAX
    (report 08:00 HST Apr 1, release 14:30), a span Apr 2 00:00-01:00, LAX-JFK (report 20:00 HST Apr 2, release 02:15
    Apr 3), JFK-BOS-JFK (report 06:00 HST Apr 4, 27:45 free, release 10:30), an NRT-HNL deadhead only reporting 13:00
    HST Apr 5 (08:00 JST Apr 6, 26:30 free), in 01:00 Apr 6 (12:00), release 01:30; HNL-LAX 11:00 later. Never
    acclimated to the JFK or NRT theater: at NRT (61.7 deg from HNL) HNL 13:00 less 0:30, row 1300-1659, 11:30. A stay
    begun in the span (85:00 by the report) holds LAX, JFK and BOS only at a station between -131 and -58.4 deg (SEA,
    ORD, ...); NRT is 97 deg or more from every one: no fork. 12:00 is over 11:30: SHORT, 12:00 needed, flagged (with
    the fork: NRT 08:00 acclimated, row 0700-1159, 14:00, a '?')."""
    d0 = _duty(at(2027, 4, 1, "08:00"), _leg("HNL", "LAX", at(2027, 4, 1, "09:00"), at(2027, 4, 1, "14:15"), "1"))
    d1 = _duty(at(2027, 4, 2, "20:00"), _leg("LAX", "JFK", at(2027, 4, 2, "21:00"), at(2027, 4, 3, "02:00"), "2"))
    d2 = _duty(at(2027, 4, 4, "06:00"), _leg("JFK", "BOS", at(2027, 4, 4, "07:00"), at(2027, 4, 4, "08:15"), "3"),
               _leg("BOS", "JFK", at(2027, 4, 4, "09:00"), at(2027, 4, 4, "10:15"), "4"))
    d3 = _duty(at(2027, 4, 5, "13:00"),
               _leg("NRT", "HNL", at(2027, 4, 5, "14:00"), at(2027, 4, 6, "01:00"), "5", dh=True))
    ds, u = [d0, d1, d2, d3, _lax(at(2027, 4, 6, "12:30"))], [(at(2027, 4, 2, "00:00"), at(2027, 4, 2, "01:00"))]
    assert TO._acc_bound([TO._prep(d) for d in ds], 3, (), u) == ([("HNL", True)], False)
    t = TO.duty_timeout(ds, 4, 2, "roster", "332", unknown=u)
    assert (t["rest"]["ok"], t["rest"]["need"], t["rest"]["free"], t["flags"]) == (False, "12:00", "11:00", ["rest"])


def test_a_span_read_as_duty_that_moved_him_starts_his_new_stay_at_the_release_before_it():
    """Review round 6 (CV7-4: mutant Zpend_nomove): a span read as duty that moved him into another theater may have
    started his stay there as early as the release before the span, not as early as the stay he had in the theater he
    left. By hand, 2 pilots: HNL-JFK (in 16:00 HST Apr 1: in JFK's theater from then), JFK-BOS-JFK (report 22:00 HST
    Apr 2, release 06:00 Apr 3), a span Apr 3 08:00-12:00, NRT-KIX (report 20:00 HST Apr 3, at NRT: the span moved him,
    in 22:00, release 22:15), a KIX-HNL deadhead only reporting 20:00 HST Apr 4 (15:00 JST Apr 5, 21:45 free), in 08:00
    Apr 5 (12:00), release 08:30; HNL-LAX 11:00 later. At KIX (66.9 deg from HNL) not acclimated: HNL 20:00 less 0:30,
    row 1700-2159, 11:30. His stay in the NRT-KIX theater from the 06:00 Apr 3 release is 38:00 old at the KIX
    report: no fork. 12:00 is over 11:30: SHORT, 12:00 needed (from his JFK stay's start, 76:00 there: KIX 15:00
    acclimated, row 1300-1659, 12:00, a '?')."""
    c0 = _duty(at(2027, 4, 1, "06:00"), _leg("HNL", "JFK", at(2027, 4, 1, "07:00"), at(2027, 4, 1, "16:00"), "1"))
    c1 = _duty(at(2027, 4, 2, "22:00"), _leg("JFK", "BOS", at(2027, 4, 2, "23:00"), at(2027, 4, 3, "00:15"), "2"),
               _leg("BOS", "JFK", at(2027, 4, 3, "04:00"), at(2027, 4, 3, "05:45"), "3"))
    c2 = _duty(at(2027, 4, 3, "20:00"), _leg("NRT", "KIX", at(2027, 4, 3, "21:00"), at(2027, 4, 3, "22:00"), "4"))
    c3 = _duty(at(2027, 4, 4, "20:00"),
               _leg("KIX", "HNL", at(2027, 4, 4, "21:00"), at(2027, 4, 5, "08:00"), "5", dh=True))
    ds, u = [c0, c1, c2, c3, _lax(at(2027, 4, 5, "19:30"))], [(at(2027, 4, 3, "08:00"), at(2027, 4, 3, "12:00"))]
    assert TO._acc_bound([TO._prep(d) for d in ds], 3, (), u) == ([("HNL", True)], False)
    t = TO.duty_timeout(ds, 4, 2, "roster", "332", unknown=u)
    assert (t["rest"]["ok"], t["rest"]["need"], t["rest"]["free"], t["flags"]) == (False, "12:00", "11:00", ["rest"])


def test_a_station_exactly_60_degrees_from_one_he_is_at_since_keeps_a_stay_begun_in_a_span(monkeypatch):
    """Review round 6 (CV7-4: mutant Uanchor_lt): FAR 117.3's theater is 60 degrees of longitude, so a station a stay
    may have begun at is kept while every station he is at since is 60 degrees or less from it, exactly 60 included.
    By hand (two made-up stations at 10.0 and 70.0 deg E, exactly 60.0 apart; one at 70.5, 60.5 away): kept at 70.0,
    cut at 70.5; a None (no longitude) cuts nothing."""
    monkeypatch.setitem(TO.LON, "QQA", 10.0)
    monkeypatch.setitem(TO.LON, "QQB", 15.0)
    assert TO.ang(10.0, 70.0) == 60.0
    assert TO._anchors_cut(frozenset({"QQA", "QQB"}), [70.0]) == frozenset({"QQA", "QQB"})
    assert TO._anchors_cut(frozenset({"QQA", "QQB"}), [70.5]) == frozenset({"QQB"})
    assert TO._anchors_cut(frozenset({"QQA"}), [None, 70.0]) == frozenset({"QQA"})


def test_with_his_theater_not_sure_a_stay_begun_in_a_span_that_may_reach_72_h_in_a_later_one_is_not_bounded():
    """Review round 6 (CV7-4: mutant Xref_sure_alts): a later span is bounded only where no stay a duty in an earlier
    span may have begun can reach 72 h inside it outside the theater he is sure of; with his theater not sure (a leg
    to a station with no longitude) that holds even when every station that stay may have begun at is within 60 deg
    of his last reference. By hand, 2 pilots: HNL-LAX (release 14:30 HST Apr 1), a span Apr 1 15:00-16:00, LAX-PPG-XYZ
    (report 20:00 HST Apr 3, in XYZ 06:00 Apr 4, release 06:30), a span Apr 5 08:00-10:00, a LAX-HNL deadhead only
    reporting 22:00 HST Apr 6 (36:00 after that span: acclimated to LAX on every reading), in 08:30 Apr 7 (10:30),
    release 08:45; HNL-LAX 10:15 later. A stay begun in the first span at a station within 60 deg of LAX and PPG (all
    within 60 deg of HNL) is 72 h old at 15:00 Apr 4, before the second span ends, and his theater is not sure (XYZ):
    the lowest row, 8:30, '? SHORT of 10:30 if it applies'. Bounded it would read LAX 01:00 PDT, row 0000-0359, 9:00:
    a sure SHORT."""
    e0 = _duty(at(2027, 4, 1, "08:00"), _leg("HNL", "LAX", at(2027, 4, 1, "09:00"), at(2027, 4, 1, "14:15"), "1"))
    e1 = _duty(at(2027, 4, 3, "20:00"), _leg("LAX", "PPG", at(2027, 4, 3, "21:00"), at(2027, 4, 4, "03:00"), "2"),
               _leg("PPG", "XYZ", at(2027, 4, 4, "04:00"), at(2027, 4, 4, "06:00"), "3"))
    e2 = _duty(at(2027, 4, 6, "22:00"),
               _leg("LAX", "HNL", at(2027, 4, 6, "23:00"), at(2027, 4, 7, "08:30"), "4", dh=True))
    ds = [e0, e1, e2, _lax(at(2027, 4, 7, "19:00"))]
    u = [(at(2027, 4, 1, "15:00"), at(2027, 4, 1, "16:00")), (at(2027, 4, 5, "08:00"), at(2027, 4, 5, "10:00"))]
    assert TO._acc_bound([TO._prep(d) for d in ds], 2, (), u) is None
    t = TO.duty_timeout(ds, 3, 2, "roster", "332", unknown=u)
    assert (t["rest"]["ok"], t["rest"]["free"]) == (None, "10:15") and "rest" not in t["flags"]
    assert any(s.startswith("Rest after deadhead") and "over its Table B FDP 8:30 (the lowest row on any clock" in s
               and s.endswith("10:15 free: ? SHORT of 10:30 if it applies.") for s in t["lines"])


def test_after_a_span_read_as_duty_36_h_free_with_a_schedule_item_in_it_keeps_the_block_in_fork():
    """Review round 6 (CV7-4: mutant Yfree_ok_fork): after a span read as duty a block-in on file may have ended the
    stay the walk counts; 36 h free acclimates him whatever the stay, but not when a schedule item that may be duty
    lies inside the 36 h. By hand, 2 pilots, the line of test_after_a_span_read_as_duty_a_block_in_on_file_may_have_
    ended_his_stay with the HNL-JFK deadhead reporting 10:00 HST Apr 6 (36:30 after the 21:30 Apr 4 release, in 21:00:
    11:00) and an item Apr 5 12:00-13:00: on the stay from the AKL block-in (90:00), acclimated to HNL, row 0700-1159,
    14:00: no line; had the span left him in a stay the HNL block-in ends, only 36 h free acclimates him, and the item
    may be duty: no reading of its own, so the lowest row stays, 8:30: '? SHORT of 11:00 if it applies' (without the
    fork: no line, met)."""
    d0 = _duty(at(2027, 4, 1, "00:00"), _leg("HNL", "HKG", at(2027, 4, 1, "01:00"), at(2027, 4, 1, "12:00"), "1"))
    d1 = _duty(at(2027, 4, 2, "06:00"), _leg("SIN", "AKL", at(2027, 4, 2, "07:00"), at(2027, 4, 2, "16:00"), "2"))
    d2 = _duty(at(2027, 4, 4, "06:00"), _leg("SIN", "ICN", at(2027, 4, 4, "07:00"), at(2027, 4, 4, "12:00"), "3"),
               _leg("ICN", "HNL", at(2027, 4, 4, "13:00"), at(2027, 4, 4, "21:00"), "4"))
    d3 = _duty(at(2027, 4, 6, "10:00"),
               _leg("HNL", "JFK", at(2027, 4, 6, "11:00"), at(2027, 4, 6, "21:00"), "5", dh=True))
    rep = at(2027, 4, 7, "07:45")
    d4 = _duty(rep, _leg("JFK", "BOS", rep + timedelta(hours=1), rep + timedelta(hours=2), "6"))
    ds, u = [d0, d1, d2, d3, d4], [(at(2027, 4, 1, "18:00"), at(2027, 4, 1, "20:00"))]
    item = [(at(2027, 4, 5, "12:00"), at(2027, 4, 5, "13:00"))]
    assert TO._acc_bound([TO._prep(d) for d in ds], 3, item, u) is None
    t = TO.duty_timeout(ds, 4, 2, "roster", "332", unknown=u, busy=item)
    assert (t["rest"]["ok"], t["rest"]["free"], t["flags"]) == (None, "10:30", ["rest_q"])
    assert any(s.startswith("Rest after deadhead") and "over its Table B FDP 8:30 (the lowest row on any clock" in s
               and s.endswith("10:30 free: ? SHORT of 11:00 if it applies.") for s in t["lines"])
    t = TO.duty_timeout(ds, 4, 2, "roster", "332", unknown=u)
    assert t["rest"]["ok"] is True and not any(s.startswith("Rest after deadhead") for s in t["lines"])


def test_two_spans_in_one_gap_are_bounded_on_the_end_of_the_later():
    """Review round 6 (CV7-4: mutant ACuend_lo): the free time on file before the spans of one gap runs from the release
    to the end of the last of them. By hand, 2 pilots: HNL-LAX (release 14:30 HST Apr 1), spans Apr 1 16:00-17:00 and
    Apr 3 03:00-04:00 (37:30 after the release: a report inside it may follow 36 h free), a LAX-HNL deadhead only
    reporting 12:00 HST Apr 3, in 00:00 Apr 4 (12:00), release 00:15; HNL-LAX 10:30 later: the lowest row, 8:30, '?
    SHORT of 12:00 if it applies', rest_q kept (on the first span's end, 2:30 after the release, it would be bounded:
    HNL 12:00, row 1200-1259, 13:00, LAX 15:00 PDT, row 1300-1659, 12:00, HNL less 0:30 12:30: no line, met)."""
    g0 = _duty(at(2027, 4, 1, "08:00"), _leg("HNL", "LAX", at(2027, 4, 1, "09:00"), at(2027, 4, 1, "14:15"), "1"))
    g1 = _duty(at(2027, 4, 3, "12:00"),
               _leg("LAX", "HNL", at(2027, 4, 3, "13:00"), at(2027, 4, 4, "00:00"), "2", dh=True))
    ds = [g0, g1, _lax(at(2027, 4, 4, "10:45"))]
    u = [(at(2027, 4, 1, "16:00"), at(2027, 4, 1, "17:00")), (at(2027, 4, 3, "03:00"), at(2027, 4, 3, "04:00"))]
    assert TO._acc_bound([TO._prep(d) for d in ds], 1, (), u) is None
    t = TO.duty_timeout(ds, 2, 2, "roster", "332", unknown=u)
    assert (t["rest"]["ok"], t["rest"]["free"]) == (None, "10:30") and "rest" not in t["flags"]
    assert any(s.startswith("Rest after deadhead") and "over its Table B FDP 8:30 (the lowest row on any clock" in s
               and s.endswith("10:30 free: ? SHORT of 12:00 if it applies.") for s in t["lines"])


def test_a_stay_begun_in_a_span_bounds_a_later_span_ending_at_its_72_h_and_not_one_ending_after():
    """Review round 6 (CV7-4: mutants Calts_le, BAalts_tight; CV7-1: the stay starts at the span's start, where its
    block-in may be, no earlier): FAR 117.3's 72 h are not reached by a report inside a later span that ends exactly at
    them. By hand, 2 pilots: HNL-SYD (release 23:30 HST Jan 10), a span Jan 11 04:00-06:00, SYD-SIN (report 06:00 HST
    Jan 13, in 14:00, release 14:30), a span Jan 14 02:00-04:00, a SIN-HNL deadhead only reporting 20:00 HST Jan 14
    (14:00 SGT Jan 15), in 07:00 Jan 15 (11:00), release 07:30; HNL-LAX 10:30 later. A stay a duty in the first span
    may have begun at a station within 60 deg of SYD and SIN (HKG, MNL ...) from 04:00 Jan 11: 72 h at 04:00 Jan 14,
    exactly the second span's end: bounded, HNL 20:00 less 0:30 (row 1700-2159) 11:30 and, that stay acclimating him at
    SIN (88:00), SIN 14:00, row 1300-1659, 12:00: 11:00 is under both, no line, met (from the release, 23:30 Jan 10, as
    round 5, fix 2 counted, 72 h fall inside the span: '?'). The second span to 04:30: a report inside it may follow 72
    h there: the lowest row, 8:30, '? SHORT of 11:00 if it applies'."""
    h0 = _duty(at(2027, 1, 10, "13:00"), _leg("HNL", "SYD", at(2027, 1, 10, "14:00"), at(2027, 1, 10, "23:00"), "1"))
    h1 = _duty(at(2027, 1, 13, "06:00"), _leg("SYD", "SIN", at(2027, 1, 13, "07:00"), at(2027, 1, 13, "14:00"), "2"))
    h2 = _duty(at(2027, 1, 14, "20:00"),
               _leg("SIN", "HNL", at(2027, 1, 14, "21:00"), at(2027, 1, 15, "07:00"), "3", dh=True))
    ds = [h0, h1, h2, _lax(at(2027, 1, 15, "18:00"))]
    for end, ok in (("04:00", True), ("04:30", None)):
        u = [(at(2027, 1, 11, "04:00"), at(2027, 1, 11, "06:00")), (at(2027, 1, 14, "02:00"), at(2027, 1, 14, end))]
        bnd = TO._acc_bound([TO._prep(d) for d in ds], 2, (), u)
        assert bnd == (([("HNL", True), ("SIN", False)], None) if ok else None), end
        t = TO.duty_timeout(ds, 3, 2, "roster", "332", unknown=u)
        assert (t["rest"]["ok"], t["rest"]["free"]) == (ok, "10:30"), end
        assert any(s.startswith("Rest after deadhead") and s.endswith("10:30 free: ? SHORT of 11:00 if it applies.")
                   for s in t["lines"]) == (ok is None), end


def test_the_stretch_reading_edges_8_30_against_8_31_and_since_equal_to_the_need():
    """Review round 6 (CV7-4: mutants BClowb_1m, BDsince_1m): a stretch of exactly 8:30 (the lowest Table B row less
    0:30) holds no deadhead past any row, 8:31 may; the reading is met when the time since the stretch equals its need,
    a '?' one minute short of it. By hand, 2 pilots, _g0 (release 19:00 HST Apr 5), HNL-LAX reporting 01:00 HST Apr 7:
    a span Apr 6 04:00-12:30 (8:30): no line, met; 04:00-12:31 (8:31): a line, 10 h needed, at least 12:29 since: met.
    A span Apr 6 04:00-16:00 (12:00): reporting 04:00 Apr 7, 12:00 since: met; 03:59, 11:59: '?', rest_q."""
    for end, line in (("12:30", False), ("12:31", True)):
        t = TO.duty_timeout([_g0(), _lax(at(2027, 4, 7, "01:00"))], 1, 2, "roster", "332",
                            unknown=[(at(2027, 4, 6, "04:00"), at(2027, 4, 6, end))])
        g = [s for s in t["lines"] if s.startswith("Rest after deadhead")]
        assert t["rest"]["ok"] is True and bool(g) == line, end
    assert "the span runs 8:31 (04:00 HST Tue Apr 6 to 12:31 HST Tue Apr 6), over 8:30" in g[0]
    assert g[0].endswith("at least 12:29 free (since the end of that span): met.")
    u = [(at(2027, 4, 6, "04:00"), at(2027, 4, 6, "16:00"))]
    for rep, ok, flags in (("04:00", True, []), ("03:59", None, ["rest_q"])):
        t = TO.duty_timeout([_g0(), _lax(at(2027, 4, 7, rep))], 1, 2, "roster", "332", unknown=u)
        assert (t["rest"]["ok"], t["flags"]) == (ok, flags), rep


def test_after_36_h_free_past_the_last_span_his_stay_in_that_theater_may_be_long_enough_to_acclimate_him():
    """Review round 6 (CV7-1; mutant R6anchor_early): after 36 h free on file past the last span his stay in that
    station's theater began no later than the block-in that brought him there and may be older (the spans), so later
    reports in that theater may follow 72 h there even where every reference's walk has left it. By hand, 2 pilots:
    HNL-LAX (release 12:30 HST Apr 30), a span Apr 30 13:00-May 2 06:00 (41:30: the bound fails), LAX-NRT (in 00:00
    May 3), NRT-KIX (report 13:00 HST May 4, 36:30 free: the anchor), his own way to LAX, LAX-SIN (report 04:00 HST
    May 6, 36:15 free: every reference's walk on LAX's theater, or PPG's or RAR's, which hold LAX; none holds SIN; in
    SIN 22:00), a SIN-HNL deadhead only reporting 10:00 HST May 7 (20:00 UTC), in 21:00 (11:00); HNL-LAX 11:00 later.
    Not acclimated: LAX 13:00 PDT less 0:30 (row 1300-1659) 11:30, PPG 09:00 and RAR 10:00 less 0:30 (row 0700-1159)
    13:30. In NRT's theater since 00:00 May 3 (KIX and SIN are within 60 deg of NRT; his own trip to LAX is no block-in,
    the walk's stay model): 106 h, acclimated at SIN, 04:00 May 8, row 0400-0459, 10:00. 11:00 is over 10:00 only: '?
    SHORT of 11:00 if it applies' (counted from the anchor's report, 69 h, no line). The FAR rest is a '?' on
    117.25(d)'s 56 h anyway (a trip of 183 h past 60 degrees with a span inside it)."""
    a = _duty(at(2027, 4, 30, "06:00"), _leg("HNL", "LAX", at(2027, 4, 30, "07:00"), at(2027, 4, 30, "12:15"), "1"))
    b = _duty(at(2027, 5, 2, "12:00"), _leg("LAX", "NRT", at(2027, 5, 2, "13:00"), at(2027, 5, 3, "00:00"), "2"))
    c = _duty(at(2027, 5, 4, "13:00"), _leg("NRT", "KIX", at(2027, 5, 4, "14:00"), at(2027, 5, 4, "15:30"), "3"))
    d = _duty(at(2027, 5, 6, "04:00"), _leg("LAX", "SIN", at(2027, 5, 6, "05:00"), at(2027, 5, 6, "22:00"), "4"))
    rep = at(2027, 5, 7, "10:00")
    e = _duty(rep, _leg("SIN", "HNL", rep + timedelta(hours=1), rep + timedelta(hours=11), "5", dh=True))
    ds, u = [a, b, c, d, e, _lax(rep + timedelta(hours=22))], [(at(2027, 4, 30, "13:00"), at(2027, 5, 2, "06:00"))]
    pr = [TO._prep(x) for x in ds]
    assert TO._acc_anchor(pr, 4, (), u) == ([("SIN", False), ("LAX", True), ("PPG", True), ("RAR", True)], None, "NRT")
    t = TO.duty_timeout(ds, 5, 2, "roster", "332", unknown=u)
    assert (t["rest"]["ok"], t["rest"]["cite"]) == (None, "FAR 117.25(d)")
    assert any(s.startswith("Rest after deadhead") and "over its Table B FDP 10:00 (SIN time)" in s and
               "another reading of its acclimation gives 13:30" in s and s.endswith(
                   "10:30 free: ? SHORT of 11:00 if it applies.") for s in t["lines"])


def _ja(d, hm):
    return at(2027, 1, d, hm)


def _fb(d, hm):
    return at(2027, 2, d, hm)


def _ap(d, hm):
    return at(2027, 4, d, hm)


def _my(d, hm):
    return at(2027, 5, d, hm)


def _nv(d, hm):
    return at(2027, 11, d, hm)


def _kix_anchor_line():
    """The ANCHOR-DSPAN line (review round 6, fix 1), 3 pilots: HNL-ICN, NRT-BNE (in 22:50 HST Nov 13), a span Nov 12
    07:35-08:35 and one Nov 14 01:20 to Nov 15 17:20, BNE-KIX (in 09:35 Nov 16, release 10:05), KIX-OGG-SEA reporting
    10:05 Nov 18 (48:00 free, no span after it: the anchor, KIX), SEA-OGG reporting 08:05 Nov 21 (48:15 free), OGG-AKL
    (in 05:50 Nov 22, release 06:20), an AKL-SEA deadhead only reporting 15:40 HST Nov 23 (33:20 free), in 03:40 Nov 24
    (12:00), release 04:10; SEA-SFO 10:30 later."""
    ds = [_duty(_nv(11, "08:05"), _leg("HNL", "ICN", _nv(11, "09:05"), _nv(11, "21:05"), "1")),
          _duty(_nv(13, "09:35"), _leg("NRT", "BNE", _nv(13, "10:50"), _nv(13, "22:50"), "2")),
          _duty(_nv(15, "22:20"), _leg("BNE", "KIX", _nv(15, "23:35"), _nv(16, "09:35"), "3")),
          _duty(_nv(18, "10:05"), _leg("KIX", "OGG", _nv(18, "11:05"), _nv(18, "18:05"), "4"),
                _leg("OGG", "SEA", _nv(18, "19:35"), _nv(19, "07:35"), "5")),
          _duty(_nv(21, "08:05"), _leg("SEA", "OGG", _nv(21, "09:20"), _nv(21, "12:20"), "6")),
          _duty(_nv(22, "03:50"), _leg("OGG", "AKL", _nv(22, "04:50"), _nv(22, "05:50"), "7")),
          _duty(_nv(23, "15:40"),
                _leg("AKL", "SEA", _nv(23, "16:40"), _nv(24, "03:40"), "8", dh=True)),
          _duty(_nv(24, "14:40"), _leg("SEA", "SFO", _nv(24, "15:40"), _nv(24, "16:40"), "9"))]
    return ds, [(_nv(12, "07:35"), _nv(12, "08:35")), (_nv(14, "01:20"), _nv(15, "17:20"))]


def test_after_36_h_free_past_the_last_span_a_block_in_on_file_may_have_ended_the_stay_the_walk_counts(monkeypatch):
    """Review round 6, fix 1 (ANCHOR-DSPAN; mutants F1anc_dspan, V9anc_st_true): the walk from the anchor keeps round
    5, fix 2's block-in fork: the spans before it may have held duty, so a stay the walk counts from a block-in on file
    may be one that block-in did not start. By hand (_kix_anchor_line): KIX is 68.4 deg from OGG, so the KIX-OGG
    block-in (18:05 Nov 18) starts a stay that holds SEA (34.1 deg from OGG) and AKL (28.8): 117:35 at the deadhead's
    AKL report, acclimated, AKL 14:40 NZDT (01:40 UTC Nov 24), row 1300-1659, 12:00 (PPG's reference, 14:40 SST, 12:00
    too). Had the span left him in BNE's theater (OGG is 50.5 deg from BNE, SEA 84.6), the SEA block-in starts his stay
    and AKL is 62.9 deg from SEA: 33:50 there, not acclimated, SEA 17:40 PST less 0:30 (row 1700-2159) 11:30. 12:00 is
    over 11:30 only: '? SHORT of 12:00 if it applies', its acclimation not known (round 6: no line, met). Filling the
    span with BNE-LAX and LAX-BNE (in BNE 07:30 Nov 15) on file: SHORT, 12:00 needed. With the walk cap at 1 the
    anchor's forks are too many: the lowest row on any clock, 8:30."""
    ds, u = _kix_anchor_line()
    pr = [TO._prep(d) for d in ds]
    assert TO._acc_bound(pr, 6, (), u) is None
    assert TO._acc_anchor(pr, 6, (), u) == ([("AKL", False), ("SEA", True), ("PPG", False)], None, "KIX")
    t = TO.duty_timeout(ds, 7, 3, "roster", "332", unknown=u)
    assert (t["rest"]["ok"], t["rest"]["free"], t["rest"]["cite"], "rest" in t["flags"]) == (None, "10:30",
                                                                                             "FAR 117.25(g)", False)
    assert t["rest"]["txt"] == "10:30 free, 12:00 needed (FAR 117.25(g)): ? (if it applies)"
    assert any(s.startswith("Rest after deadhead") and "over its Table B FDP 11:30 (SEA time, less 0:30: not "
               "acclimated on a reading of a theater that holds KIX)" in s and "(? its acclimation is not known (36 h "
               "free at KIX after a span of your line not on file" in s
               and s.endswith("10:30 free: ? SHORT of 12:00 if it applies.") for s in t["lines"])
    f1 = _duty(_nv(14, "01:30"), _leg("BNE", "LAX", _nv(14, "02:30"), _nv(14, "15:30"), "10"))
    f2 = _duty(_nv(14, "16:30"), _leg("LAX", "BNE", _nv(14, "17:30"), _nv(15, "07:30"), "11"))
    t = TO.duty_timeout(ds[:2] + [f1, f2] + ds[2:], 9, 3, "roster", "332")
    assert (t["rest"]["ok"], t["rest"]["need"], t["rest"]["cite"]) == (False, "12:00", "FAR 117.25(g)")
    monkeypatch.setattr(TO, "ACC_WALKS", 1)
    assert TO._acc_anchor(pr, 6, (), u) is None
    t = TO.duty_timeout(ds, 7, 3, "roster", "332", unknown=u)
    assert any(s.startswith("Rest after deadhead") and "over its Table B FDP 8:30 (the lowest row on any clock" in s
               for s in t["lines"])


def _xyz_line(rep4, *legs4):
    """HNL-NRT (in 17:00 HST Apr 1, release 17:30), NRT-LAX (report 06:00 HST Apr 3, 36:30 free: acclimated to NRT; in
    LAX 16:00, release 16:30), LAX-SFO (report 06:00 HST Apr 5, 37:30 free: acclimated to LAX; release 08:30), an
    XYZ-HNL deadhead (report 08:00 HST Apr 6 at XYZ, a station with no longitude he went to his own way, in HNL 15:00,
    release 15:30: a country not on file), then the duty given."""
    return [_duty(_ap(1, "08:00"), _leg("HNL", "NRT", _ap(1, "09:00"), _ap(1, "17:00"), "1")),
            _duty(_ap(3, "06:00"), _leg("NRT", "LAX", _ap(3, "07:00"), _ap(3, "16:00"), "2")),
            _duty(_ap(5, "06:00"), _leg("LAX", "SFO", _ap(5, "07:00"), _ap(5, "08:15"), "3")),
            _duty(_ap(6, "08:00"),
                  _leg("XYZ", "HNL", _ap(6, "09:00"), _ap(6, "15:00"), "4", dh=True)),
            _duty(rep4, *legs4)]


def test_72_h_counted_across_a_report_at_a_station_with_no_longitude_is_never_the_only_reading():
    """Review round 6, fix 1 (LASTOUT-NOLON-72H; mutants F1walk_off, F1cut_off, F1mode_cut, F1st_none, F1words): round
    5, fix 2 made a report at a station with no longitude clear the theater last acclimated to, but kept his stay across
    it, so 72 h counted across that report acclimated him to a new theater on one clock, a later last out than round 4,
    fix 2's. By hand, 2 pilots (_xyz_line): his stay from the LAX block-in (16:00 Apr 3) holds SFO and HNL (39.5 deg).
    - HNL-LAS reporting 10:00 HST Apr 7 (18:30 free), 11:00-16:30 (5:30): the walk alone, 90:00 in that stay:
      acclimated to HNL's theater, HNL 10:00, row 0700-1159, 14:00, last out 24:00 less 5:30 = 18:30 HST (round 5, fix
      2). Round 4, fix 2 kept LAX's theater: LAX 13:00 PDT, row 1300-1659, 12:00, and HNL's 14:00: 16:30. His stay may
      have ended at XYZ (the HNL block-in starts one, 19:00 old) with the theater not sure: LAX less 0:30, 11:30: the
      last out is 21:30 less 5:30 = 16:00 HST (18:00 with the extension), its acclimation '?'.
    - HNL-LAS reporting 10:00 HST Apr 8 (42:30 free): acclimated whatever XYZ was, but on LAX's theater (round 4, fix 2)
      or HNL's: the lower, LAX 12:00, 16:30 (round 5, fix 2: HNL alone, 18:30); every reading acclimated: no
      'acclimation' in unsure, 'clock' (the other reading differs).
    - NRT-KIX reporting at NRT 08:00 HST Apr 8 (40:30 free, his own way): 36 h free acclimates him to NRT's theater,
      outside LAX's, on every reading: the walk alone, its own words (mutant F1same_ret).
    - An HNL-SIN deadhead only reporting 10:00 HST Apr 7, in 00:00 Apr 8 (14:00), SIN-HKG 10:15 after its release: on
      HNL alone (14:00) no line; on LAX less 0:30, 11:30: '? SHORT of 14:00 if it applies'."""
    rep = _ap(7, "10:00")
    ds = _xyz_line(rep, _leg("HNL", "LAS", rep + timedelta(hours=1), rep + timedelta(hours=6, minutes=30), "5"))
    pr = [TO._prep(d) for d in ds]
    assert TO._acclimation(pr, 4, (), ())[0] == [("HNL", False)]
    w_opts, w_words, w_st, _f, _h = TO._acc_walk(pr, 4, (), ())
    assert (w_opts, w_st) == ([("HNL", False), ("LAX", False), ("LAX", True)], None)
    assert w_words.startswith("? acclimation not sure: you reported at XYZ since, with no longitude on file")
    assert w_words.endswith("the lower of HNL time, LAX time and LAX time less 0:30 is used (conservative)")
    t = TO.duty_timeout(ds, 4, 2, "roster", "332")
    assert (t["last_out"]["txt"], t["last_out"]["by"], t["last_out_ext"]["txt"]) == ("16:00 HST", "FDP 11:30 (FAR "
                                                                                      "117.13, Table B)", "18:00 HST")
    assert "acclimation" in t["unsure"] and t["fdp"]["acclimated"] is None
    json.dumps(t)
    rep = _ap(8, "10:00")
    ds = _xyz_line(rep, _leg("HNL", "LAS", rep + timedelta(hours=1), rep + timedelta(hours=6, minutes=30), "5"))
    t = TO.duty_timeout(ds, 4, 2, "roster", "332")
    assert (t["last_out"]["txt"], t["fdp"]["acclimated"], t["unsure"]) == ("16:30 HST", True, ["clock"])
    assert any(s.startswith("Acclimation (FAR 117.3, FOM 4.3.2.4.6): ? acclimated, but to which theater is not sure: "
                            "you reported at XYZ since") for s in t["lines"])
    rep = _ap(8, "08:00")
    ds = _xyz_line(rep, _leg("NRT", "KIX", rep + timedelta(hours=1), rep + timedelta(hours=2, minutes=15), "5"))
    t = TO.duty_timeout(ds, 4, 2, "roster", "332")
    assert ("Acclimation (FAR 117.3, FOM 4.3.2.4.6): acclimated to the NRT theater (40:30 free from duty; 36 h free "
            "from duty or 72 h there acclimates).") in t["lines"] and t["unsure"] == []
    rep = _ap(7, "10:00")
    ds = _xyz_line(rep, _leg("HNL", "SIN", rep + timedelta(hours=1), _ap(8, "00:00"), "5", dh=True))
    ds.append(_duty(_ap(8, "10:45"), _leg("SIN", "HKG", _ap(8, "11:45"), _ap(8, "15:45"), "6")))
    t = TO.duty_timeout(ds, 5, 2, "roster", "332")
    assert (t["rest"]["ok"], t["rest"]["free"], t["rest"]["cite"]) == (None, "10:15", "FAR 117.25(g)")
    assert any(s.startswith("Rest after deadhead") and "over its Table B FDP 11:30 (LAX time, less 0:30" in s and
               s.endswith("10:15 free: ? SHORT of 14:00 if it applies.") for s in t["lines"])


def test_the_anchor_needs_36_h_free_exactly():
    """Review round 6, fix 1 (TEST-ANCHOR-PATHS, TEST-R6-EDGE-SURVIVORS; mutants V3anc_36le, V5anc_36m1): the anchor is
    a report after 36 h free from the release on file before it (FAR 117.3's 36 consecutive hours). By hand, 2 pilots:
    HNL-LAX (release 12:30 HST Apr 30), a span Apr 30 13:00 to May 3 02:00 (61:30 from the release: the bound fails),
    LAX-SYD (in SYD 06:00 May 4, release 06:30), a SYD-HNL deadhead only reporting 18:30 HST May 5 (36:00 free), in
    06:15 May 6 (11:45), HNL-LAX 11:00 after its release (10:30 free). Every reference within 60 deg of SYD reads 12:00
    or more at 04:30 UTC May 6 (test_after_36_h_free_on_file_past_the_last_span_a_deadhead_reads_every_clock_of_that_
    theater): no line, met. LAX-SYD a minute later (35:59 free): no anchor, the lowest row, 8:30: '? SHORT of 11:45 if
    it applies'."""
    rep = _my(5, "18:30")
    u = [(_ap(30, "13:00"), _my(3, "02:00"))]
    for late, ok in ((0, True), (1, None)):
        arr = _my(4, "06:00") + timedelta(minutes=late)
        ds = [_duty(_ap(30, "06:00"), _leg("HNL", "LAX", _ap(30, "07:00"), _ap(30, "12:15"), "1")),
              _duty(arr - timedelta(hours=16), _leg("LAX", "SYD", arr - timedelta(hours=15), arr, "2")),
              _duty(rep, _leg("SYD", "HNL", rep + timedelta(hours=1), rep + timedelta(hours=11, minutes=45), "3",
                              dh=True)),
              _lax(rep + timedelta(hours=22, minutes=45))]
        a = TO._acc_anchor([TO._prep(d) for d in ds], 2, (), u)
        assert (a is None) == (ok is None) and (a is None or (a[1], a[2]) == (True, "SYD")), late
        t = TO.duty_timeout(ds, 3, 2, "roster", "332", unknown=u)
        assert (t["rest"]["ok"], t["rest"]["free"]) == (ok, "10:30"), late
        assert any(s.startswith("Rest after deadhead") and "over its Table B FDP 8:30 (the lowest row on any clock" in s
                   and s.endswith("10:30 free: ? SHORT of 11:45 if it applies.") for s in t["lines"]) == (ok is None)


def test_a_stay_begun_before_the_anchor_may_reach_72_h_at_a_later_report_outside_its_theater():
    """Review round 6, fix 1 (TEST-ANCHOR-PATHS; mutant V1anc_noalts): after 36 h free past the last span his stay in
    that theater may have begun at any station within 60 deg of it (the spans), so at a later report within 60 deg of
    such a station and of every one he is at since it may be 72 h old: acclimated (0) or not (1), a fork. By hand, 2
    pilots: HNL-AKL (release 18:00 HST May 5), a span May 6 04:00 to May 7 20:00 (50:00 from the release: the bound
    fails), MNL-PPG (release 08:45 May 8), PPG-HKG reporting 08:45 May 10 (48:00 free: the anchor, PPG; in HKG 19:45,
    75.4 deg from PPG), HKG-HNL reporting 20:15 May 12 (48:00 free: acclimated to HKG; in HNL 04:15 May 13, 88.2 deg
    from HKG), HNL-SIN reporting 00:45 May 14 (20:00 free; in SIN 06:45, 98.1 deg from HNL), a SIN-LAX deadhead only
    reporting 17:15 HST May 14 (03:15 UTC May 15, 10:00 free), in 05:00 May 15 (11:45); LAX-MNL 10:15 after its
    release. SYD, BNE and MEL are within 60 deg of PPG, HKG, HNL and SIN: a stay begun there 72 h before the anchor
    may acclimate him at the HNL report, and then at SIN he is not acclimated: HNL 17:15 less 0:30 (row 1700-2159)
    11:30; on HKG's acclimation SIN and HKG 11:15, row 0700-1159, 14:00. 11:45 is over 11:30 only: '? SHORT of 11:45 if
    it applies' (without that stay: HKG's 14:00 alone, no line, met)."""
    ds = [_duty(_my(5, "05:15"), _leg("HNL", "AKL", _my(5, "06:30"), _my(5, "17:30"), "1")),
          _duty(_my(8, "06:00"), _leg("MNL", "PPG", _my(8, "07:15"), _my(8, "08:15"), "2")),
          _duty(_my(10, "08:45"), _leg("PPG", "HKG", _my(10, "09:45"), _my(10, "19:45"), "3")),
          _duty(_my(12, "20:15"), _leg("HKG", "HNL", _my(12, "21:15"), _my(13, "04:15"), "4")),
          _duty(_my(14, "00:45"), _leg("HNL", "SIN", _my(14, "01:45"), _my(14, "06:45"), "5")),
          _duty(_my(14, "17:15"),
                _leg("SIN", "LAX", _my(14, "18:30"), _my(15, "05:00"), "6", dh=True)),
          _duty(_my(15, "15:45"), _leg("LAX", "MNL", _my(15, "16:45"), _my(15, "17:45"), "7"))]
    u = [(_my(6, "04:00"), _my(7, "20:00"))]
    a_opts, a_st, a_stn = TO._acc_anchor([TO._prep(d) for d in ds], 5, (), u)
    assert (a_stn, a_st) == ("PPG", None) and {("HNL", True), ("HKG", False), ("SIN", False)} <= set(a_opts)
    t = TO.duty_timeout(ds, 6, 2, "roster", "332", unknown=u)
    assert (t["rest"]["ok"], t["rest"]["free"], t["rest"]["cite"]) == (None, "10:15", "FAR 117.25(g)")
    assert any(s.startswith("Rest after deadhead") and "over its Table B FDP 11:30 (HNL time, less 0:30: not "
               "acclimated on a reading of a theater that holds PPG)" in s and "another reading of its acclimation "
               "gives 14:00" in s and s.endswith("10:15 free: ? SHORT of 11:45 if it applies.") for s in t["lines"])


def test_past_the_walk_cap_from_the_earliest_anchor_a_later_one_is_read(monkeypatch):
    """Review round 6, fix 1 (TEST-ANCHOR-PATHS, TEST-R6-EDGE-SURVIVORS; mutants V4anc_cap_keep, V6anc_first): where the
    walk from the earliest report after 36 h free past the last span gives no reading (here more walks than the cap, set
    to 1), a later such report is read; the walks cut short by the cap are never kept. By hand, 2 pilots: HNL-ANC
    (release 04:50 HST May 4), a span May 4 15:05-16:05, HNL-PPT (release 20:35 May 5), PPT-SYD-SIN reporting 20:35 May
    7 (48:00 free: the earliest anchor, PPT; in SIN 09:20 May 8, release 09:50), SIN-LAX-HKG reporting 21:55 May 9
    (36:05 free: an anchor too, SIN; in HKG 15:40 May 10, release 16:10), an HKG-ORD deadhead only reporting 02:10 HST
    May 11 (12:10 UTC, 10:00 free), in 16:10 (14:00); ORD-BNE 10:00 after its release. From PPT: a stay begun at SYD or
    BNE (within 60 deg of PPT, SYD and SIN) may be 72 h old at the SIN report, a fork: two walks for a reference. From
    SIN: one walk per reference, every clock within 60 deg of SIN 12:00 at most (SIN and HKG 20:10, row 1700-2159; SYD
    and BNE 22:10 AEST, row 2200-2259, 11:00): 14:00 is over all, SHORT, 14:00 needed. With the cap at 64 the bound
    reads it (the 1:00 span, 10:15 after the release: SIN 12:00, sure) and the walk from PPT gives readings: SHORT
    too."""
    ds = [_duty(_my(3, "18:20"), _leg("HNL", "ANC", _my(3, "19:35"), _my(4, "04:35"), "1")),
          _duty(_my(5, "07:05"), _leg("HNL", "PPT", _my(5, "08:05"), _my(5, "20:05"), "2")),
          _duty(_my(7, "20:35"), _leg("PPT", "SYD", _my(7, "21:50"), _my(8, "00:50"), "3"),
                _leg("SYD", "SIN", _my(8, "02:20"), _my(8, "09:20"), "4")),
          _duty(_my(9, "21:55"), _leg("SIN", "LAX", _my(9, "23:10"), _my(10, "02:10"), "5"),
                _leg("LAX", "HKG", _my(10, "03:40"), _my(10, "15:40"), "6")),
          _duty(_my(11, "02:10"),
                _leg("HKG", "ORD", _my(11, "03:10"), _my(11, "16:10"), "7", dh=True)),
          _duty(_my(12, "02:40"), _leg("ORD", "BNE", _my(12, "03:55"), _my(12, "08:55"), "8"))]
    u = [(_my(4, "15:05"), _my(4, "16:05"))]
    pr = [TO._prep(d) for d in ds]
    for cap, bnd, stn in ((64, ([("SIN", False)], True), "PPT"), (1, None, "SIN")):
        monkeypatch.setattr(TO, "ACC_WALKS", cap)
        assert TO._acc_bound(pr, 4, (), u) == bnd, cap
        assert TO._acc_anchor(pr, 4, (), u)[1:] == (True, stn), cap
        t = TO.duty_timeout(ds, 5, 2, "roster", "332", unknown=u)
        assert (t["rest"]["ok"], t["rest"]["need"], "rest" in t["flags"]) == (False, "14:00", True), cap
    assert any(s.startswith("Rest after deadhead") and "36 h free at SIN after a span of your line not on file" in s
               for s in t["lines"])


def test_a_schedule_item_inside_a_span_leaves_the_stretch_its_full_length():
    """Review round 6, fix 1 (TEST-R6-RELAX-SURVIVORS: mutant V11join_end; TXT-ITEM-INSIDE-SPAN): a piece inside an
    earlier one never shortens the stretch. By hand, 2 pilots, _g0 (release 19:00 HST Apr 5): a span Apr 6 00:00-12:00
    with a schedule item 02:00-03:00 inside it, HNL-LAX reporting 23:00 HST Apr 6: one stretch of 12:00 (the item
    inside it), over 8:30: 12:00 needed, at least 11:00 since its end: '?', rest_q (a stretch cut at the item's end,
    3:00, would read met on 10 h). The line names both kinds, the item in or next to the span."""
    t = TO.duty_timeout([_g0(), _lax(_ap(6, "23:00"))], 1, 2, "roster", "332",
                        unknown=[(_ap(6, "00:00"), _ap(6, "12:00"))],
                        busy=[(_ap(6, "02:00"), _ap(6, "03:00"))])
    assert (t["rest"]["ok"], t["rest"]["free"], t["rest"]["cite"], t["flags"]) == (None, "11:00", "FAR 117.25(g)",
                                                                                   ["rest_q"])
    assert t["rest"]["txt"] == ("at least 11:00 free, 12:00 needed (FAR 117.25(g)): ? (a span of your line not on file "
                                "and a schedule item that may be duty; if it applies)")
    assert any(s.startswith("Rest after deadhead transportation (FAR 117.25(g), FOM 4.3.2.10): a deadhead inside the "
                            "span of your line not on file and the schedule item that may be duty in or next to it may "
                            "need more") and "it runs 12:00 (00:00 HST Tue Apr 6 to 12:00 HST Tue Apr 6)" in s
               for s in t["lines"])


def test_a_stay_a_duty_in_a_span_may_begin_starts_at_the_first_span_of_the_gap():
    """Review round 6, fix 1 (TEST-R6-RELAX-SURVIVORS: mutant V10alt_lastspan): with two spans in one gap, a stay a
    duty in a span may have begun starts at the first span's start, not the last's. By hand, 2 pilots, the line of
    test_a_duty_inside_a_span_may_begin_a_stay_at_a_station_not_on_file with its span split in two, Feb 17 02:55-08:00
    and Feb 17 18:00 to Feb 18 08:55 (30:45 from the 02:10 release to the last end: bounded): a stay begun in the first
    (at ORD, whose 60 degrees hold LAX and JFK) is 86:30 old at the JFK deadhead's report (17:25 HST Feb 20):
    acclimated, JFK 22:25 EST, row 2200-2259, 11:00; on HNL 17:25 less 0:30, 11:30: '? SHORT of 11:15 if it applies'
    (from the second span's start, 18:00 Feb 17, 71:25: no fork, no line, met). A filling on file, LAX-ORD in the first
    span (in 07:30 Feb 17) and ORD-LAX in the second (in 08:30 Feb 18): 81:55 in ORD's theater, acclimated, SHORT, 11:15
    needed."""
    a = _duty(_fb(16, "19:55"), _leg("LIH", "LAX", _fb(16, "20:55"), _fb(17, "01:55"), "1"))
    b = _duty(_fb(19, "14:55"), _leg("LAX", "JFK", _fb(19, "15:55"), _fb(20, "01:55"), "2"))
    c = _duty(_fb(20, "17:25"),
              _leg("JFK", "HNL", _fb(20, "18:40"), _fb(21, "04:40"), "3", dh=True))
    rep = _fb(21, "15:25")
    d = _duty(rep, _leg("HNL", "OGG", rep + timedelta(hours=1), rep + timedelta(hours=1, minutes=40), "4"))
    u = [(_fb(17, "02:55"), _fb(17, "08:00")), (_fb(17, "18:00"), _fb(18, "08:55"))]
    assert TO._acc_bound([TO._prep(x) for x in (a, b, c, d)], 2, (), u) == ([("HNL", True), ("JFK", False)], None)
    t = TO.duty_timeout([a, b, c, d], 3, 2, "roster", "332", unknown=u)
    assert any(s.startswith("Rest after deadhead") and "over its Table B FDP 11:00 (JFK time)" in s and
               "another reading of its acclimation gives 11:30" in s and s.endswith(
                   "10:30 free: ? SHORT of 11:15 if it applies.") for s in t["lines"])
    x1 = _duty(_fb(17, "03:00"), _leg("LAX", "ORD", _fb(17, "03:30"), _fb(17, "07:30"), "5"))
    x2 = _duty(_fb(18, "03:30"), _leg("ORD", "LAX", _fb(18, "04:00"), _fb(18, "08:30"), "6"))
    t = TO.duty_timeout([a, x1, x2, b, c, d], 5, 2, "roster", "332")
    assert (t["rest"]["ok"], t["rest"]["need"], t["rest"]["cite"]) == (False, "11:15", "FAR 117.25(g)")


def test_a_span_that_begins_at_or_before_the_release_is_read_from_the_release():
    """Review round 6, fix 1 (TEST-R6-EDGE-SURVIVORS: mutants V13clip_late, V10b_alt_noclip): the line on file runs to
    the release, so a span that begins at or before it is read from the release, as a stretch piece and as the start of
    a stay a duty in it may begin. By hand, 2 pilots:
    - _g0 (release 19:00 HST Apr 5), a span 19:00 Apr 5 (or 18:00) to 07:00 Apr 6, HNL-LAX reporting 18:59 HST Apr 6:
      the stretch runs 12:00 from the release, 12:00 needed, at least 11:59 since: '?' (from a minute later: 11:59,
      met);
    - the line of test_a_stay_begun_in_a_span_bounds_a_later_span_ending_at_its_72_h_and_not_one_ending_after with its
      first span from 23:00 Jan 10, before the 23:30 release, and the second Jan 13 20:00-23:30: a stay a duty in the
      first may begin from 23:30 Jan 10, 72 h at 23:30 Jan 13, exactly the second span's end: bounded, no line, met
      (from 23:00 Jan 10 it would reach 72 h inside the second span: the lowest row, '?')."""
    for st in ("19:00", "18:00"):
        t = TO.duty_timeout([_g0(), _lax(_ap(6, "18:59"))], 1, 2, "roster", "332",
                            unknown=[(_ap(5, st), _ap(6, "07:00"))])
        assert t["rest"]["txt"] == ("at least 11:59 free, 12:00 needed (FAR 117.25(g)): ? (a span of your line not on "
                                    "file; if it applies)"), st
        assert any(s.startswith("Rest after deadhead") and "the span runs 12:00 (19:00 HST Mon Apr 5 to 07:00 HST Tue "
                   "Apr 6)" in s for s in t["lines"]), st
    h0 = _duty(_ja(10, "13:00"), _leg("HNL", "SYD", _ja(10, "14:00"), _ja(10, "23:00"), "1"))
    h1 = _duty(_ja(13, "06:00"), _leg("SYD", "SIN", _ja(13, "07:00"), _ja(13, "14:00"), "2"))
    h2 = _duty(_ja(14, "20:00"),
               _leg("SIN", "HNL", _ja(14, "21:00"), _ja(15, "07:00"), "3", dh=True))
    ds = [h0, h1, h2, _lax(_ja(15, "18:00"))]
    u = [(_ja(10, "23:00"), _ja(11, "06:00")), (_ja(13, "20:00"), _ja(13, "23:30"))]
    assert TO._acc_bound([TO._prep(d) for d in ds], 2, (), u) == ([("HNL", True), ("SIN", False)], None)
    t = TO.duty_timeout(ds, 3, 2, "roster", "332", unknown=u)
    assert (t["rest"]["ok"], t["rest"]["free"]) == (True, "10:30")
    assert not any(s.startswith("Rest after deadhead") for s in t["lines"])


def test_from_the_anchor_a_block_in_forks_only_where_a_stay_he_may_be_in_is_under_72_h():
    """Review round 6, fix 1 (ANCHOR-DSPAN; mutants F1chains_off, F1chains_norep, F1chains_noleg): the walk from the
    anchor forks on a block-in on file (fix 2's fork) only where a stay he may be in, begun before the anchor at a
    station within 60 deg of his and held or ended at each station since, is under 72 h old at that report. By hand,
    2 pilots: HNL-ICN (release 07:15 HST May 15), a span May 15 07:15-09:15, OGG-ANC (release 21:30 May 15), SFO-LAX-KIX
    reporting 09:50 May 17 (36:20 free: the anchor, SFO), in KIX 19:50 (102.4 deg from SFO: a stay there), KIX-PPG
    reporting 08:20 May 19 (36:00 free with a schedule item May 18 07:20-08:20 in it), in PPG 21:35 (54.1 deg from
    KIX), a PPG-BOS deadhead only reporting 21:25 HST May 20 (07:25 UTC May 21), in 11:25 May 21 (14:00); BOS-BNE
    10:00 after its release. The only station within 60 deg of SFO, LAX and KIX is PPG, which holds PPG too, so any
    stay he may be in at the PPG report is 72 h old or more (the KIX one 73:35): no fork, acclimated there on every
    reading, KIX 16:25 (row 1300-1659) and PPG 20:25 SST (row 1700-2159), 12:00 at most: 14:00 is over it, SHORT, 14:00
    needed (forking anyway, the walk where the item may be duty reads no reading: the lowest row, '?'). Reporting at
    19:50 HST May 20 the KIX stay is exactly 72:00 old: no fork, SHORT (KIX 14:50 and PPG 18:50, 12:00); at 19:49,
    71:59: a fork, the lowest row, '?' (mutant F1chains_le)."""
    u, item = [(_my(15, "07:15"), _my(15, "09:15"))], [(_my(18, "07:20"), _my(18, "08:20"))]
    for rp, ok in (("21:25", False), ("19:50", False), ("19:49", None)):
        r = _my(20, rp)
        ds = [_duty(_my(14, "20:45"), _leg("HNL", "ICN", _my(14, "21:45"), _my(15, "06:45"), "1")),
              _duty(_my(15, "19:15"), _leg("OGG", "ANC", _my(15, "20:15"), _my(15, "21:15"), "2")),
              _duty(_my(17, "09:50"), _leg("SFO", "LAX", _my(17, "11:05"), _my(17, "12:05"), "3"),
                    _leg("LAX", "KIX", _my(17, "12:50"), _my(17, "19:50"), "4")),
              _duty(_my(19, "08:20"), _leg("KIX", "PPG", _my(19, "09:35"), _my(19, "21:35"), "5")),
              _duty(r, _leg("PPG", "BOS", r + timedelta(hours=1), r + timedelta(hours=14), "6", dh=True)),
              _duty(r + timedelta(hours=24, minutes=30),
                    _leg("BOS", "BNE", r + timedelta(hours=25, minutes=45), r + timedelta(hours=30, minutes=45), "7"))]
        pr = [TO._prep(d) for d in ds]
        assert TO._acc_bound(pr, 4, item, u) is None
        a = TO._acc_anchor(pr, 4, item, u)
        assert a == (([("KIX", False), ("PPG", False)], True, "SFO") if ok is False else None), rp
        t = TO.duty_timeout(ds, 5, 2, "roster", "332", unknown=u, busy=item)
        assert (t["rest"]["ok"], t["rest"]["free"], "rest" in t["flags"]) == (ok, "10:00", ok is False), rp
        assert t["rest"]["txt"].startswith("10:00 free, 14:00 needed (FAR 117.25(g)): " + ("SHORT" if ok is False else
                                                                                        "? (if it applies)")), rp


def test_from_the_anchor_a_report_his_own_way_ends_the_stays_it_does_not_hold():
    """Review round 6, fix 1 (ANCHOR-DSPAN; mutant F1chains_norep): a stay he may be in ends where he reports at a
    station outside its 60 degrees (he went there his own way), as at a block-in. By hand, 3 pilots, _kix_anchor_line
    with KIX-OGG alone (in OGG 18:05 Nov 18, release 18:35) and SEA-OGG reporting at SEA 08:05 HST Nov 21 (61:30 free):
    a stay begun before the anchor at BNE (50.5 deg from OGG) ends at that report (84.6 deg from BNE), the one begun
    there at the AKL block-in (62.9 deg from SEA): 33:50 at the deadhead's AKL report, under 72 h: the fork, not
    acclimated, SEA 17:40 PST less 0:30 (row 1700-2159) 11:30: '? SHORT of 12:00 if it applies' (not ending at the
    report, every stay he may be in is 72 h old or more there: the OGG block-in's 117:35 alone, AKL 12:00, no line,
    met)."""
    ds, u = _kix_anchor_line()
    ds[3] = _duty(_nv(18, "10:05"), _leg("KIX", "OGG", _nv(18, "11:05"), _nv(18, "18:05"), "4"))
    pr = [TO._prep(d) for d in ds]
    assert TO._acc_anchor(pr, 6, (), u) == ([("AKL", False), ("SEA", True), ("PPG", False)], None, "KIX")
    t = TO.duty_timeout(ds, 7, 3, "roster", "332", unknown=u)
    assert (t["rest"]["ok"], t["rest"]["free"], t["rest"]["cite"]) == (None, "10:30", "FAR 117.25(g)")
    assert any(s.startswith("Rest after deadhead") and s.endswith("10:30 free: ? SHORT of 12:00 if it applies.")
               for s in t["lines"])
