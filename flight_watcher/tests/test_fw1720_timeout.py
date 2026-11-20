"""1.7.20 (Ryan, Nov 20, 2026: "I need this page to calculate per FAR 117 and PWA when I timeout, both for if I extend or
if I do not. Add that number in bold with a dark orange square around it right of the report time", and "the number I
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
    """By hand: report 1:15 before 09:15 EST = 08:00 EST, 03:00 HST (PWA 2.A.19.b.1). Free since the BOS release (02:10 +
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
    # the BOS rest (PWA, below) is met by 2:25 from release to report, under VAN_RIDES 2:30: '?', its chip only
    assert t["legal"] is True and t["sure"] is True and t["unsure"] == [] and t["flags"] == ["rest_q"]
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
    for w in ("Report 08:00 EST (03:00 HST Fri Feb 19): 1:15 before scheduled departure out of domicile (PWA 2.A.19.b.1)",
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
              "longest free period 75:00: met", "Duty ends 15 min after block-in (PWA 2.A.19.b): release 17:45 HST at the "
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
    assert p["txt"] == ("scheduled duty 13:00 (Scheduled limit 16:00), Maximum 18:00 (10.D.1.b.1): last out 14:15 EST (not "
                        "binding: FAR 117 is earlier) \u00b7 rest 24:35, 22:10 needed (10.E.1.a.1): ? \u00b7 landings 1 "
                        "(10 may be scheduled, 11 if required)")
    for w in ("PWA duty limit (10.D.1.b.1): IRO Crew (2.A.40): Scheduled 16:00, Maximum 18:00 of Duty Period (Local "
              "Times, 2.A.43; from the later of the scheduled and actual report, 10.D.5, to 15 min after the last "
              "block-in, 2.A.19.b)", "From the report 08:00 EST it ends by 21:00 HST Fri Feb 19, the last "
              "block-in by 20:45 HST, so the last out is 14:15 EST (09:15 HST Fri Feb 19): not binding (FAR 117 is earlier).",
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
    # SIN arrival 19:15 HST Mar 2, release 19:45 (clearing customs at SIN, PWA 2.A.19.b); report 1:15 before 13:30 SGT
    # = 12:15 SGT Mar 5 (18:15 HST Mar 4): 46:30 free: acclimated to SIN
    assert f["acclimated"] is True and f["row"] == "0700-1259 (SIN time 12:15)"
    assert f["pilots"] == 4 and f["rest_class"] == 2 and f["limit"] == "18:00"  # 4 pilots on the A330: Class 2, '?'
    assert f["rest_class_sure"] is False and t["unsure"] == ["rest class"] and f["alt"] == {"1": "13:15 HST", "3": "09:45 HST"}
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
    assert t["no_ext"]["txt"] == "11:45 HST" and t["fdp"]["in_txt"] == "11:45 HST" and t["fdp"]["end_txt"] == "12:15 HST"
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
    # the last out of the working leg (leg 1): 17:20 less 9:15 scheduled to the last block-in (15:35) = 08:05 HST; with
    # the extension FAR alone gives 10:05, but HNL-OGG-HNL-LAX is Mixed Flying (2.A.45: HNL-LAX is 3:00 or more, the
    # OGG turn is interisland and no Repositioning Flight, 2.A.62), so 14:00 for a standard crew (10.D.3): 05:20 +
    # 14:00 = 19:20, less the 0:15 debrief = 19:05 last block-in, less 9:15 = 09:50 HST
    assert (t["last_out"]["txt"], t["last_out_ext"]["txt"], t["last_out"]["leg"]) == ("08:05 HST", "09:50 HST", "HNL-OGG")
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
    # last out 14:55 HST less 5:30 = 09:25 HST = 12:25 PDT; on the LAX clock 18:55 less 5:30 = 13:25 HST = 16:25 PDT;
    # with the extension that reading's 20:55 is past the PWA 16:00 duty Maximum (10.D.1.a): 04:55 + 16:00 = 20:55 less
    # the 0:15 debrief = 20:40, less 5:30 = 15:10 HST = 18:10 PDT
    assert t["last_out"]["txt"] == "12:25 PDT"
    assert t["fdp"]["other"] == {"clock": "LAX time 07:55", "row": "0700-1159", "limit": "14:00",
                                 "last_out_txt": "16:25 PDT", "last_out_ext_txt": "18:10 PDT"}
    assert any(s.startswith("Other reading: LAX time 07:55 gives row 0700-1159, FDP 14:00 and 9:00 flight time, last out "
                            "16:25 PDT (18:10 PDT with the extension). FOM 4.3.2.4") for s in t["lines"])
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
    ends = lambda t: next(s for s in t["lines"] if s.startswith("Duty ends"))  # noqa: E731
    assert "clearing customs" in ends(t)  # LNK is not on the Watcher's US list: not known, conservative
    # review PWA-5: watcher.release_customs (a last leg from outside the US) gives 15 min here: the basis says so
    assert any(s.startswith("Customs (2.A.19.b): HNL-LNK crosses a border (or a country not on file), so the debrief is "
                            "30 min here") for s in t["lines"])
    t = run([(key, trip(key, "07:00", legs, CREW2))], at(2027, 3, 10, "06:00"), {key: {"eq": "332"}},
            domestic={"LNK"})["attributes"]["timeout"]
    assert "clearing customs" not in ends(t) and not any(s.startswith("Customs") for s in t["lines"])


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
    16:00, so the duty ends by 00:00 HST, the last block-in by 23:45 (0:15 debrief, 2.A.19.b), the last out 23:45 - 5:15 =
    18:30 HST: it caps the extension (18:45 -> 18:30), not the 16:45. Scheduled 08:00 to 14:30 = 6:30 of 14:00."""
    t = _pwa_d()["attributes"]["timeout"]
    lo, lx, p, f = t["last_out"], t["last_out_ext"], t["pwa"], t["fdp"]
    assert (lo["txt"], lo["by"], lo["pwa"]) == ("16:45 HST", "FDP 14:00 (FAR 117.13, Table B)", False)
    assert (lx["txt"], lx["by"], lx["short"], lx["pwa"]) == ("18:30 HST", "PWA 10.D.1.a max duty 16 h", "PWA max duty 16 h",
                                                             True)
    assert t["legal"] is True and t["sure"] is True and t["flags"] == []
    assert (p["cite"], p["crew"], p["scheduled"], p["maximum"], p["duty"], p["binds"]) == (
        "10.D.1.a", "2 pilots", "14:00", "16:00", "6:30", ["ext"])
    assert (p["end_txt"], p["in_txt"], p["last_out_txt"]) == ("00:00 HST", "23:45 HST", "18:30 HST")
    # the block-in limits: the FDP's own ends stay FAR's; the block-in with the extension is the PWA's, its release 00:00
    assert (f["end_txt"], f["ext_end_txt"], f["in_txt"], f["ext_in_txt"]) == ("22:00 HST", "00:00 HST", "22:00 HST",
                                                                             "23:45 HST")
    assert (f["release_txt"], f["ext_release_txt"]) == ("22:15 HST", "00:00 HST")
    # out on time the block-in is due by 09:00 + Table A 9:00 = 18:00 either way (flight time binds before the PWA)
    assert t["no_ext"]["txt"] == t["ext"]["txt"] == "18:00 HST" and t["ft"]["txt"] == "5:15 of 9:00 (3:45 spare)"
    lines = "\n".join(t["lines"])
    for w in ("Last out (block-out): the FDP end, or the PWA duty limit's last block-in when earlier, less the scheduled "
              "5:15", "16:45 HST (16:45 HST Wed Feb 10) without an extension, 18:30 HST (18:30 HST Wed Feb 10) with it "
              "(FDP 14:00; PWA max duty 16 h)", "PWA duty limit (10.D.1.a): 2 pilots: Scheduled 14:00, Maximum 16:00",
              "it ends by 00:00 HST Thu Feb 11, the last block-in by 23:45 HST, so the last out is 18:30 HST (18:30 HST "
              "Wed Feb 10): binding with the extension (FAR 117 alone: 16:45 HST, 18:45 HST with the extension).",
              "PWA duty scheduled 6:30 of 14:00 (10.D.1.a).", "No 5.A.6 transfer time is added (none serves HNL), ",
              "Landings (PWA 10.H.1): 1 flown segment; no more than 10 may be scheduled (11 if required to perform).",
              "PWA 10.E.1.b (18:00 rest when a segment departs 1400-0359 local and the scheduled Duty Period is "
              "12:00+): not "
              "triggered (HNL-LAX departs 09:00 HST)."):
        assert w in lines, w
    assert "PWA rest before this duty (10.E.1.a): the duty before it is not on file" in t["not_checked"]
    assert TO.PWA_NC in t["not_checked"] and TO.PWA_NC_IRO not in t["not_checked"]  # 10.D.1.b.4 is an IRO Crew's
    assert p["txt"] == ("scheduled duty 6:30 (Scheduled limit 14:00), Maximum 16:00 (10.D.1.a): last out 18:30 HST (binds "
                        "with the extension) · rest not on file · landings 1 (10 may be scheduled, 11 if required)")


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
    t = _sin4(["CA Doe, Jane (10001)", "CA Roe, Rick (10002)", "FO Poe, Pat (10003)", "FO Moe, Max (10004)"], "CA02FO02")
    assert t["fdp"]["pilots"] == 4 and t["fdp"]["limit"] == "18:00" and t["fdp"]["rest_class"] == 2
    assert (t["last_out"]["txt"], t["last_out_ext"]["txt"]) == ("14:55 HST", "16:55 HST")
    assert t["last_out"]["short"] == "FDP 18:00" and t["last_out_ext"]["short"] == "FDP + 2:00 ext"
    p = t["pwa"]
    assert (p["cite"], p["maximum"], p["scheduled"], p["binds"], p["last_out_txt"]) == ("10.D.1.d", "", "", [], "")
    assert p["duty"] == "14:35"  # 10:00 to 00:05 + 0:30 customs at SIN
    assert any(s.startswith("PWA duty limit (10.D.1.d): an Extended Range Crew of 2 Captains and 2 First Officers has no "
                            "PWA duty hours of its own: Part 117 Table C governs") for s in t["lines"])
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
    assert TO.pwa_duty(2, 1, True)[:3] == (h(12), h(14), "10.D.3") and TO.pwa_duty(3, 1, True)[:3] == (h(14), h(16), "10.D.3")
    assert TO.pwa_duty(4, 2, True)[:3] == (h(14), h(16), "10.D.3")
    assert (TO.package_captains("CA02FO02"), TO.package_captains("CA01FO01RO01"), TO.package_captains("FO02")) == (2, 1, None)
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
    assert TO.mixed_flying([L("HNL", "LIH", 0, 35), L("LIH", "HNL", 0, 35), L("HNL", "OGG", 0, 40), L("OGG", "LAX", 5, 0)])
    assert not TO.mixed_flying([L("HNL", "LAX", 5, 15)]) and not TO.mixed_flying([L("HNL", "OGG", 0, 40)])
    assert not TO.mixed_flying([_leg("HNL", "KOA", t0, t0 + timedelta(minutes=45), dh=True), L("KOA", "LAX", 5, 0)])
    # a duty that repositions: International limits, and the basis says why
    d = _duty(at(2027, 2, 12, "07:00"), L("HNL", "OGG", 0, 40),
              _leg("OGG", "LAX", at(2027, 2, 12, "09:40"), at(2027, 2, 12, "14:40")))
    t = TO.duty_timeout([d], 0, 2, "roster", "332")
    assert t["pwa"]["cite"] == "10.D.1.a" and t["pwa"]["mixed"] is False
    assert ("Not Mixed Flying (2.A.45): HNL-OGG is a Repositioning Flight (2.A.62; a sit of 2:00 or less at the neighbor "
            "island is read as its minimal delay).") in t["lines"]


def test_pwa_mixed_flying_14_hours_binds_a_two_pilot_crew():
    """(g) KOA-HNL (0:45) then HNL-LAX (5:15), 2 pilots, report 07:00 HST: Mixed Flying (2.A.45; KOA-HNL goes to
    Honolulu before the international segment, so it is no Repositioning Flight). FAR: Table B 0700-1159, 2 segments,
    14:00: FDP end 21:00; from KOA-HNL's 08:00 out to the last block-in 15:15 is 7:15: last outs 13:45 and 15:45 HST.
    PWA 10.D.3 standard crew: Maximum 14:00: 07:00 + 14:00 = 21:00, last block-in 20:45, less 7:15 = 13:30 HST: it
    binds both. Scheduled 8:30 of 12:00. Mixed Flying landings: 2 of 4 (10.H.3)."""
    key = "H3903|2027-02-12"
    legs = [(0, "9104", "KOA", "HNL", "08:00", "08:45", "0:45"), (0, "9105", "HNL", "LAX", "10:00", "17:15", "5:15")]
    t = run([(key, trip(key, "07:00", legs, CREW2))], at(2027, 2, 12, "06:00"), {key: {"eq": "332"}})["attributes"]["timeout"]
    lo, lx, p = t["last_out"], t["last_out_ext"], t["pwa"]
    assert t["fdp"]["limit"] == "14:00" and t["fdp"]["segments"] == 2 and lo["leg"] == "KOA-HNL"
    assert (lo["txt"], lx["txt"], lo["short"], lx["short"]) == ("13:30 HST", "13:30 HST", "PWA max duty 14 h",
                                                                "PWA max duty 14 h")
    assert lo["by"] == "PWA 10.D.3 max duty 14 h" and p["binds"] == ["no_ext", "ext"]
    assert (p["mixed"], p["cite"], p["crew"], p["scheduled"], p["maximum"], p["duty"]) == (
        True, "10.D.3", "Mixed Flying duty (2.A.45), standard crew", "12:00", "14:00", "8:30")
    assert p["landings"] == {"n": 2, "max": 4, "ok": True}
    assert "Landings (PWA 10.H.3, Mixed Flying): 2 flown segments; no more than 4 in a Mixed Flying Duty Period." in t["lines"]
    assert any("binding with and without an extension (FAR 117 alone: 13:45 HST, 15:45 HST with the extension)" in s
               for s in t["lines"])
    # augmented, the same duty: 14:00 Scheduled, 16:00 Maximum (10.D.3)
    t3 = run([(key, trip(key, "07:00", legs, CREW3))], at(2027, 2, 12, "06:00"), {key: {"eq": "332"}})["attributes"]["timeout"]
    assert (t3["pwa"]["scheduled"], t3["pwa"]["maximum"], t3["pwa"]["crew"]) == (
        "14:00", "16:00", "Mixed Flying duty (2.A.45), augmented crew")
    assert t3["pwa"]["last_out_txt"] == "15:30 HST"  # 07:00 + 16:00 - 0:15 - 7:15


def _rest_line():
    """HNL-SFO (report 06:00 HST, out 07:00, in 12:30, release 12:45: a 6:45 Duty Period), SFO-HNL reporting 12:00 later
    (00:45 HST, out 02:00, in 07:30, release 07:45), then HNL-LAX reporting 10:30 after that (18:15 HST, out 19:15)."""
    return [_duty(at(2027, 3, 10, "06:00"), _leg("HNL", "SFO", at(2027, 3, 10, "07:00"), at(2027, 3, 10, "12:30"), "1")),
            _duty(at(2027, 3, 11, "00:45"), _leg("SFO", "HNL", at(2027, 3, 11, "02:00"), at(2027, 3, 11, "07:30"), "2")),
            _duty(at(2027, 3, 11, "18:15"), _leg("HNL", "LAX", at(2027, 3, 11, "19:15"), at(2027, 3, 12, "00:30"), "3"))]


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
    assert any(s.startswith("PWA rest before this duty (10.E.1.a.1): out of domicile, 2 x the preceding Duty Period 6:45 "
                            "(06:00 HST Wed Mar 10 to release 12:45 HST Wed Mar 10) = 13:30 needed; release to report "
                            "12:00: SHORT; hotel time") for s in t["lines"])
    assert "rest 12:00, 13:30 needed (10.E.1.a.1): SHORT" in t["pwa"]["txt"]
    t2 = TO.duty_timeout(ds, 1, 2, "roster", "332")
    r2 = t2["pwa"]["rest"]
    assert (r2["need"], r2["have"], r2["ok"], r2["cite"]) == ("13:30", "12:00", None, "10.E.1.a.1")
    assert "pwa_rest" not in t2["flags"] and not any(s.startswith("Flag: short of PWA rest") for s in t2["lines"])
    assert any(s.startswith("PWA rest before this duty (10.E.1.a.1): out of domicile, 2 x the preceding Duty Period 6:45")
               and s.endswith("release to report 12:00: ? short of it, but 9:00 or more: met if the Company limits a "
                              "regular crew's hotel rest to 9:00 (10.E.1.a.2; a regular crew is read as 2 pilots); hotel "
                              "time (door to door, 10.E.1.a.3) is shorter by the van rides.") for s in t2["lines"])
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
    late = lambda hm: TO._late(_leg("HNL", "LAX", at(2027, 3, 10, hm), at(2027, 3, 10, hm) + timedelta(hours=5)))  # noqa: E731
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
    assert "Flag: landings (PWA 10.H.1): 8 flown segments, over 7 (the duty starts 23:00 local, 2200-0459)." in t["lines"]
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
    assert t["not_legal"].startswith("the scheduled Duty Period 16:30 (the report to 15 min after the last block-in, PWA "
                                     "2.A.19.b) is over the PWA 10.D.1.a Maximum 16:00 (2 pilots)")
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


# ---------------------------------------------------------------- review round 1 (PWA text over the spec where they differ)
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
    alone gave 16:30 HST). Rest at LAX: 2 landings performed in the grouping before it (3 in all): 9:00 (10.E.3.a), which
    15:00 meets; but until Ryan confirms that the table replaces 2 x the Duty Period (review PWA-R2-2), 2 x 8:30 = 17:00
    (10.E.1.a.1) is judged too: short of it, so the rest is a '?' (and no flag). Landings of day 2: 1 of 10 (10.H.3 is
    per Mixed Flying duty)."""
    key = "H3998|2027-02-10"
    legs = [(0, "9201", "KOA", "HNL", "08:00", "08:45", "0:45"), (0, "9202", "HNL", "LAX", "10:00", "17:15", "5:15"),
            (1, "9203", "LAX", "HNL", "09:45", "13:30", "5:45")]
    t = run([(key, trip(key, "07:00", legs, CREW2))], at(2027, 2, 11, "05:00"), {key: {"eq": "332"}})["attributes"]["timeout"]
    lo, lx, p = t["last_out"], t["last_out_ext"], t["pwa"]
    assert t["report_txt"] == "06:30 HST" and lo["leg"] == "LAX-HNL"
    assert (lo["txt"], lo["hst"], lo["pwa"]) == ("15:45 PST", "13:45 HST", False)
    assert (lx["txt"], lx["hst"], lx["by"], lx["short"]) == ("16:30 PST", "14:30 HST", "PWA 10.D.3 max duty 14 h",
                                                             "PWA max duty 14 h")
    assert (p["cite"], p["mixed"], p["mixed_grouping"], p["scheduled"], p["maximum"], p["binds"]) == (
        "10.D.3", False, True, "12:00", "14:00", ["ext"])
    assert p["crew"].startswith("a duty of a grouping that holds a Mixed Flying Duty Period (2.A.45; 10.D.3.a covers")
    assert any(s.startswith("PWA 10.D.3.a: this grouping holds a Mixed Flying Duty Period (2.A.45)") for s in t["lines"])
    assert p["rest"] == {"need": "9:00", "have": "15:00", "ok": None, "cite": "10.E.3.a", "late": False,
                         "other": "17:00 (10.E.1.a.1)"}
    assert "rest 15:00, 9:00 (10.E.3.a) or 17:00 (10.E.1.a.1) needed: ?" in p["txt"]
    assert any(s.startswith("? PWA rest, the other reading (10.E.1.a.1): if 10.E.3.a's table adds to 10.E.1.a.1 rather "
                            "than replacing it (to confirm): 2 x the preceding Duty Period 8:30") for s in t["lines"])
    assert "pwa_rest" not in t["flags"] and p["landings"] == {"n": 1, "max": 10, "ok": True}
    assert any(s.startswith("PWA rest before this duty (10.E.3.a): out of domicile in a grouping that holds a Mixed "
                            "Flying Duty Period, 2 landings performed in it before this rest: 9:00") for s in t["lines"])
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
    assert (r["need"], r["have"], r["ok"], r["cite"]) == ("10:00", "9:30", False, "10.E.3.a") and "pwa_rest" in t3["flags"]
    assert "Flag: short of PWA rest (10.E.3.a): 9:30 of 10:00." in t3["lines"]
    assert t3["pwa"]["cite"] == "10.D.3" and t3["pwa"]["mixed"] is False and t3["pwa"]["mixed_grouping"] is True
    t2 = TO.duty_timeout([d1, d2, d3], 1, 2, "roster", "332")
    r = t2["pwa"]["rest"]
    assert (r["need"], r["have"], r["ok"], r["cite"]) == ("9:00", "9:30", None, "10.E.3.a") and "pwa_rest" not in t2["flags"]
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
    assert D("23:00", "23:59")[:3] == (h(10), h(12), "10.D.2.a") and D("04:30", "10:00")[:3] == (h(10), h(12), "10.D.2.a")
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
    r = run([(key, trip(key, "07:10", legs, crew))], at(2027, 7, 12, "05:00"), {key: pk}, months_for("2027-06", "2027-07"))
    t = r["attributes"]["timeout"]
    # review PWA-deadhead: the trailing HNL-OGG deadhead may be the interisland Segment of a Mixed Flying duty (10.D.3)
    assert {"pilots", "rest class", "clock", "Mixed Flying"} <= set(t["unsure"]) and t["fdp"]["other"]
    assert set(t["cum"]) == {"ft_672", "fdp_168", "fdp_672"} and t["pwa"]["rest"]["cite"] == "10.E.3.a"
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
    return [_kd(k, at(2027, 2, 10, "06:00"), _leg("HNL", "LAX", at(2027, 2, 10, "07:00"), at(2027, 2, 10, "12:15"), "1")),
            _kd(k, at(2027, 2, 10, "23:00"), _leg("LAX", "KOA", at(2027, 2, 11, "00:15"), at(2027, 2, 11, "05:45"), "2"),
                _leg("KOA", "HNL", o, o + timedelta(minutes=40), "3"))]


def test_a_long_sit_judges_the_rest_both_ways_and_the_box_says_not_sure():
    """Review PWA-R2-1 / PWA-mixed-long-sit-rest: the long sit's Mixed Flying reading is the lower duty limit, but out of
    domicile it needs less rest (10.E.3.a's table in place of 10.E.1.a.1). By hand, 3 pilots, equipment not on file
    (Class 3, so FAR 117 sets both last outs): a 1:00 sit at KOA makes KOA-HNL a Repositioning Flight (2.A.62), no
    Mixed Flying: 2 x 6:30 = 13:00 needed, 10:30 from release to report: SHORT, flagged. A 2:30 sit: Mixed Flying
    (counted, conservative for the duty limit), 1 landing performed in the grouping before the rest: 9:00 (10.E.3.a),
    met by 1:30 (a '?' anyway: under the 2:30 of van rides); the other reading needs 13:00: SHORT. The readings disagree:
    a '?', no flag, the "Rest ?" chip; the box's last outs stay sure, as the PWA limit binds neither (review
    PWA-rest-unsure-box-inconsistent; FAR: Table C Class 3, 13:00 from 23:00 HST = 12:00 HST, less the 8:40 from the
    LAX out to the last block-in: 03:20 HST; 10.D.3's 16:00 gives 06:05 HST)."""
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
    assert any(s.startswith("? PWA rest, the other reading (10.E.1.a.1): if KOA-HNL is a Repositioning Flight (2.A.62), so "
                            "no Mixed Flying, or if 10.E.3.a's table adds to 10.E.1.a.1 rather than replacing it (to "
                            "confirm): out of domicile, 2 x the preceding Duty Period 6:30") and
               s.endswith("= 13:00 needed: SHORT. The readings disagree, so the rest is not sure.") for s in t["lines"])
    # the long sit line says the Mixed Flying reading is conservative only for the duty limit and the landings
    assert any(s.startswith("? Mixed Flying (2.A.45): KOA-HNL (sit 2:30)") and "counted as Mixed Flying for the duty "
               "limit and the landings (the lower limits, conservative); the rest before this duty is judged both ways"
               in s for s in t["lines"])
    # the two readings agree with a longer rest: met, no '?' (13:00 + the 2:30 of van rides = 15:30 from release to report)
    ds = _sit_pair(150)
    t = TO.duty_timeout([ds[0], _shift(ds[1], timedelta(hours=5))], 1, 3, "roster", "")
    assert t["pwa"]["rest"]["ok"] is True and "Mixed Flying" not in t["unsure"] and t["flags"] == []


def test_the_mixed_flying_rest_table_is_not_sure_where_2_x_the_duty_period_needs_more():
    """Review PWA-R2-2: until Ryan confirms that 10.E.3.a's table replaces 10.E.1.a.1, a rest the table meets but 2 x the
    preceding Duty Period does not is a '?'. By hand, 3 pilots: HNL-LAX report 08:00 HST, in 14:20, release 14:35 (6:35,
    2 x = 13:10), then LAX-HNL-KOA (Mixed Flying: LAX-HNL 5:40 and HNL-KOA). 10:00 from release to report: 9:00 met (1:00
    spare), 13:10 short: '?'. 15:40 (13:10 and the 2:30 of van rides): both met. 8:30: both short, flagged."""
    k = "H3992|2027-06-10"

    def pair(rest_m):
        rep = at(2027, 6, 10, "14:35") + timedelta(minutes=rest_m)
        o = rep + timedelta(minutes=75)
        return [_kd(k, at(2027, 6, 10, "08:00"), _leg("HNL", "LAX", at(2027, 6, 10, "09:00"), at(2027, 6, 10, "14:20"), "1")),
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
    - in domicile 11:30 from release to report before HNL-OGG-HNL, after LAX-HNL: 12:00 needed (10.E.2.a): SHORT, but as
      an International Pilot (the duty before it International flying) 10.E.1.a's 11:00 is met: the readings disagree,
      '?' (review PWA-interisland-second-reading-asymmetric); after an interisland duty: SHORT, flagged;
    - at OGG 11:30 after a 6:15 interisland duty: 9:00 (10.E.2.b): met by 2:30, the van rides (2 x 6:15 = 12:30 would be
      short);
    - at OGG 10:30 after LAX-OGG (International flying, 7:00, 3 pilots): 9:00 met, but as an International Pilot 2 x 7:00
      = 14:00: the readings disagree, '?';
    - nine HNL-OGG shuttles reporting 18:00 HST, the last in 02:50, the duty to 03:05: more than 8 (10.H.2): OVER; the
      same reporting 17:30 and ending 02:35 (before 0300): 10 (10.H.1);
    - a 12:00 interisland duty out 14:00 HST: 10.E.1.b would need 18:00 (12:30 from release to report): '?', no flag, as
      it names an International Pilot's Segment."""
    d0 = _duty(at(2027, 3, 1, "14:00"), _leg("LAX", "HNL", at(2027, 3, 1, "15:00"), at(2027, 3, 1, "20:30"), "1"))
    d1 = _duty(at(2027, 3, 2, "08:15"), _leg("HNL", "OGG", at(2027, 3, 2, "09:15"), at(2027, 3, 2, "09:55"), "2"),
               _leg("OGG", "HNL", at(2027, 3, 2, "10:30"), at(2027, 3, 2, "11:10"), "3"))
    t = TO.duty_timeout([d0, d1], 1, 2, "roster", "332")
    r = t["pwa"]["rest"]
    assert (r["need"], r["have"], r["ok"], r["cite"], r["other"]) == ("12:00", "11:30", None, "10.E.2.a",
                                                                      "11:00 (10.E.1.a)")
    assert "pwa_rest" not in t["flags"] and "rest_q" in t["flags"]
    assert any(s.startswith("? PWA rest, the other reading (10.E.1.a): as an International Pilot, the duty before it "
                            "being International flying: in domicile, 11:00 needed: met") for s in t["lines"])
    d0 = _duty(at(2027, 3, 1, "17:00"), _leg("HNL", "OGG", at(2027, 3, 1, "18:00"), at(2027, 3, 1, "18:40"), "1"),
               _leg("OGG", "HNL", at(2027, 3, 1, "19:30"), at(2027, 3, 1, "20:30"), "0"))
    t = TO.duty_timeout([d0, d1], 1, 2, "roster", "332")
    r = t["pwa"]["rest"]
    assert (r["need"], r["have"], r["ok"], r["cite"]) == ("12:00", "11:30", False, "10.E.2.a") and "pwa_rest" in t["flags"]
    assert "Flag: short of PWA rest (10.E.2.a): 11:30 of 12:00." in t["lines"] and "other" not in r
    a = _duty(at(2027, 3, 1, "06:00"), _leg("HNL", "OGG", at(2027, 3, 1, "07:00"), at(2027, 3, 1, "07:40"), "1"),
              _leg("OGG", "HNL", at(2027, 3, 1, "08:30"), at(2027, 3, 1, "09:10"), "2"),
              _leg("HNL", "OGG", at(2027, 3, 1, "11:20"), at(2027, 3, 1, "12:00"), "3"))
    b = _duty(at(2027, 3, 1, "23:45"), _leg("OGG", "HNL", at(2027, 3, 2, "01:00"), at(2027, 3, 2, "01:40"), "4"))
    t = TO.duty_timeout([a, b], 1, 2, "roster", "332")
    r = t["pwa"]["rest"]
    assert (r["need"], r["have"], r["ok"], r["cite"]) == ("9:00", "11:30", True, "10.E.2.b") and t["flags"] == []
    assert "rest 11:30, 9:00 needed (10.E.2.b): met" in t["pwa"]["txt"]
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
    assert ("Flag: landings (PWA 10.H.2): 9 flown segments, over 8 (an Interisland Pilot's duty starting before 2200 HST "
            "and continuing after 0300 HST).") in t["lines"]
    assert "landings 9 (8 at most, past 0300): OVER" in t["pwa"]["txt"]
    t = TO.duty_timeout([shuttles(at(2027, 3, 10, "17:30"), at(2027, 3, 10, "18:30"))], 0, 2, "roster", "332")
    assert t["pwa"]["landings"] == {"n": 9, "max": 10, "ok": True} and "landings" not in t["flags"]
    d0 = _duty(at(2027, 3, 9, "18:00"), _leg("HNL", "OGG", at(2027, 3, 9, "19:00"), at(2027, 3, 9, "19:40"), "1"),
               _leg("OGG", "HNL", at(2027, 3, 9, "23:35"), at(2027, 3, 10, "00:15"), "2"))
    legs = [_leg(x, y, at(2027, 3, 10, hm), at(2027, 3, 10, hm) + timedelta(hours=1), str(j)) for j, (x, y, hm) in
            enumerate((("HNL", "OGG", "14:00"), ("OGG", "HNL", "17:00"), ("HNL", "LIH", "20:00"), ("LIH", "HNL", "23:45")))]
    t = TO.duty_timeout([d0, _duty(at(2027, 3, 10, "13:00"), *legs)], 1, 2, "roster", "332")
    r = t["pwa"]["rest"]
    assert t["pwa"]["duty"] == "12:00" and (r["need"], r["ok"], r["cite"], r["late"]) == ("18:00", None, "10.E.1.b", True)
    assert "pwa_rest" not in t["flags"]
    assert any(s.startswith("PWA 10.E.1.b (18:00 rest") and "applies (?) (HNL-OGG departs 14:00 HST; this duty is all "
               "interisland flying, an Interisland Pilot's (2.A.36.b), and 10.E.1.b names an International Pilot's "
               "Segment" in s and s.endswith("? SHORT if it applies to an Interisland Pilot's duty.") for s in t["lines"])
    assert any("(10.D.2.c)" in s for s in t["not_checked"])


def test_a_rest_met_by_less_than_the_van_rides_out_of_domicile_is_not_sure():
    """Review PWA-R2-4: out of domicile the Rest Period is hotel time door to door (2.A.68.b, 10.E.1.a.3), shorter than
    release to report by the two van rides, which the schedule does not give: a rest met by under 2:30 (review
    PWA-VAN_RIDES: two rides at a far-out hotel take 1:30 to 2:30) is a '?'. By hand (_rest_line, 3 pilots, at SFO): 13:30
    needed; 14:00 from release to report (0:30 spare): '?'; 15:59 (2:29): '?'; 16:00 (2:30): met. In domicile no van:
    11:10 against 11:00 is met."""
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
    """Review PWA-over-hidden-by-FAR-not-legal: 2 pilots (firm), HNL-JFK 9:30 and JFK-BOS 1:15: 10:45 of flight time over
    Table A's 9:00 (not legal to dispatch), and the Duty Period 06:00 to 22:15 + 0:15 = 16:30 over the 16:00 Maximum
    (10.D.1.a): said too, and the PWA row says over the Maximum, not only "no last out"."""
    d = _duty(at(2027, 3, 2, "06:00"), _leg("HNL", "JFK", at(2027, 3, 2, "07:00"), at(2027, 3, 2, "16:30"), "1"),
              _leg("JFK", "BOS", at(2027, 3, 2, "21:00"), at(2027, 3, 2, "22:15"), "2"))
    t = TO.duty_timeout([d], 0, 2, "roster", "332", pilots_firm=True)
    assert t["legal"] is False and t["not_legal_short"] == "FT 10:45 of 9:00" and t["pwa"]["binds"] == []
    assert ("Flag: the PWA 10.D.1.a Maximum is over as scheduled too: the scheduled Duty Period 16:30 of 16:00 (2 pilots; "
            "to 15 min after the last block-in, 2.A.19.b): Crew Scheduling must change it.") in t["lines"]
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
    t = run(trips, at(2027, 3, 6, "06:30"), {key: {"eq": "332"}}, months_for("2027-02", "2027-03"))["attributes"]["timeout"]
    assert t["last_out"]["txt"] == "11:00 HST" and t["last_out"]["short"] == "60 h FDP in 168 h"
    assert t["fdp"]["alt"] == {"2": "23:30 HST", "3": "22:00 HST"}
    assert any("Class 2 23:30 HST (last out 11:00 HST), Class 3 22:00 HST (last out 11:00 HST)" in s for s in t["lines"])


def test_the_basis_names_a_rule_that_binds_both_once_and_the_block_in_has_its_day():
    """Review UI-R1-4 and UI-R1-3: the PWA Maximum binding both last outs is named once ("for both"); the block-in
    limits carry their day (HNL-SIN in after midnight HST)."""
    t = _sin4(["CA Doe, Jane (10001)", "FO Roe, Rick (10002)", "RO Poe, Pat (10003)", "RO Moe, Max (10004)"],
              "CA01FO01RO02")
    assert any(s.startswith("Last out (block-out):") and s.endswith("with it (PWA max duty 18 h for both).")
               for s in t["lines"])
    t = _sin4(["CA Doe, Jane (10001)", "CA Roe, Rick (10002)", "FO Poe, Pat (10003)", "FO Moe, Max (10004)"], "CA02FO02")
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
    assert said[-1] == ("working flight: pairings package not read (bid period ZeroDivisionError); the duty timeout goes "
                        "on without it")
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
    # the BOS rest is met by less than the van rides (2:25): its chip, the last outs sure (no '?')
    assert box.locator(".toq").count() == 0 and box.locator("[data-towarn]").all_inner_texts() == ["Rest ?"]
    say = box.get_attribute("aria-label")
    assert say == ("Last out 11:00 EST, 06:00 HST without an extension (FDP 14:30), 13:00 EST, 08:00 HST with one; flight "
                   "time 11:30 of 13:00 (1:30 spare); Rest ?. Details")
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
    (_unsure, "11:00? EST", "Ext 13:00 EST", "; not sure, the earlier reading is shown. Details"),
    (_same, "11:00 EST", "Ext same (60 h FDP in 168 h)", "the same with one (60 h FDP in 168 h)"),
    (_not_legal, "NOT LEGAL", "FT 13:05 of 13:00", "Not legal to dispatch: FT 13:05 of 13:00. Details"),
    (_early, "11:00 EST", "Over as scheduled", "; Over as scheduled, Rest ?. Details"),
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


def _watcher_pwa(tmp_path, r):
    """The admin's states with no Hark sensor and the working flight r (its timeout and leg)."""
    st = _states(tmp_path, hark_attrs={}, notes=False)
    a = st["sensor.flight_watcher_working_flight"]["attributes"]
    keep = ("pairing", "flight", "origin", "dest", "leg", "date", "dep_sched", "arr_sched", "report", "status", "timeout")
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
    assert bb["x"] >= rb["x"] + rb["width"] - 1 and bb["y"] < rb["y"] + rb["height"]  # right of the report, side by side
    cb = card.bounding_box()
    assert bb["x"] + bb["width"] <= cb["x"] + cb["width"] + 0.5
    assert pg.evaluate("document.documentElement.scrollWidth") <= 390
    box.click()
    det = card.locator("[data-todet]").inner_text()
    for w in ("With extension: block out by 18:30 HST Wed Feb 10, block in by 23:45 HST, release 00:00 HST",
              "PWA 10.D.1.a max duty 16 h; before takeoff only",
              "PWA: scheduled duty 6:30 (Scheduled limit 14:00), Maximum 16:00 (10.D.1.a): last out 18:30 HST (binds with "
              "the extension) · rest not on file · landings 1 (10 may be scheduled, 11 if required)"):
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
    assert box.locator("[data-tono]").inner_text() == "13:30 HST" and box.locator("[data-toext]").inner_text() == "Ext same"
    assert box.locator("[data-tobind]").inner_text() == "PWA max duty 14 h"
    assert "Landings" not in box.inner_text() and box.locator("[data-towarn]").count() == 0
    assert pg.evaluate("document.documentElement.scrollWidth") <= 390
    pg.close()


def test_card_box_says_not_legal_over_the_pwa_maximum_and_flags_a_short_pwa_rest(browser, tmp_path):
    def over(t):
        t.update(legal=False, last_out=None, last_out_ext=None, not_legal_short="PWA duty 16:30 of 16:00",
                 not_legal="the scheduled Duty Period 16:30 is over the PWA 10.D.1.a Maximum 16:00 (2 pilots): not legal "
                           "as scheduled")
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
    assert box.get_attribute("aria-label") == ("Not legal as scheduled (PWA): PWA duty 16:30 of 16:00; not sure, see the "
                                               "details. Details")
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
    assert "without an extension (FDP 14:00), 18:30 HST with one; Ext: PWA max duty 16 h;" in box.get_attribute("aria-label")
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
    two_ca = _graft(_sin4(["CA Doe, Jane (10001)", "CA Roe, Rick (10002)", "FO Poe, Pat (10003)", "FO Moe, Max (10004)"],
                          "CA02FO02"))
    txt = det(two_ca)
    assert "No extension: block out by 14:55 HST Tue Mar 2, block in by 04:00 HST Wed Mar 3, release 04:30 HST" in txt
    assert "With extension: block out by 16:55 HST Tue Mar 2, block in by 06:00 HST Wed Mar 3, release 06:30 HST" in txt
    assert "17:00 flight time: an extension adds no flight time." in txt
    one_ca = _graft(_sin4(["CA Doe, Jane (10001)", "FO Roe, Rick (10002)", "RO Poe, Pat (10003)", "RO Moe, Max (10004)"],
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
    assert "? Not sure: the rest facility class: the earlier reading is shown" in txt and "Repositioning" not in txt.split(
        "How it is worked out")[0]
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
    Apr 11: 56:00, met. Back Apr 7 (153:00 away): not triggered, no line. A line that starts with the SIN-HNL duty (the
    trip's start not on file, 11:00 away at least): '?' when short."""
    ds = _sin_trip() + [_lax(at(2027, 4, 10, "08:00"))]
    t = TO.duty_timeout(ds, 2, 2, "roster", "332")
    assert t["rest"]["ok"] is False and t["rest"]["need"] == "56:00" and "rest" in t["flags"]
    assert ("Rest on return to home base (FAR 117.25(d), FOM 4.3.2.11): 177:00 away from HNL (08:00 HST Thu Apr 1 to "
            "release 17:00 HST Thu Apr 8, more than 168 h) and SIN is 98 deg from HNL (more than 60): 56 consecutive "
            "hours, holding three physiological nights; 39:00 free: SHORT, check with Crew Scheduling.") in t["lines"]
    assert "Flag: short of FAR rest (FAR 117.25(d)): 39:00 of 56:00." in t["lines"]
    assert any(s.startswith("The three physiological nights of the 56 h rest") for s in t["not_checked"])
    assert any(s.startswith("Rest before this FDP (FAR 117.25(e), FOM 4.3.2.7): 39:00") and s.endswith("met.")
               for s in t["lines"])
    t = TO.duty_timeout(_sin_trip() + [_lax(at(2027, 4, 11, "01:00"))], 2, 2, "roster", "332")
    assert t["rest"]["ok"] is True and t["rest"]["need"] == "56:00" and "rest" not in t["flags"]
    assert any(s.endswith("; 56:00 free: met.") and "FAR 117.25(d)" in s for s in t["lines"])
    t = TO.duty_timeout(_sin_trip("04-07") + [_lax(at(2027, 4, 9, "08:00"))], 2, 2, "roster", "332")
    assert t["rest"] == {"free": "39:00", "ok": True} and not any("117.25(d)" in s for s in t["lines"])
    t = TO.duty_timeout(_sin_trip()[1:] + [_lax(at(2027, 4, 10, "08:00"))], 1, 2, "roster", "332")
    assert t["rest"]["ok"] is None and "need" not in t["rest"] and "rest" not in t["flags"] and "rest_q" in t["flags"]
    assert any(s.startswith("Rest on return to home base (FAR 117.25(d), FOM 4.3.2.11): 11:00 away from HNL") and
               "at least: it may be more than 168 h" in s and "(? the trip's start is not on file (away at least 11:00))"
               in s and s.endswith("39:00 free: ? SHORT of 56:00 if it applies.") for s in t["lines"])


def test_far_117_25g_rest_after_deadhead_transportation_past_table_b():
    """Review FAR-117.25d / FOM 4.3.2.10 (14 CFR 117.25(g)): deadhead transportation that runs past the Table B FDP
    needs a rest as long as the deadhead, no less than 10 h. By hand: a SIN-HNL deadhead only, report 06:00 HST Apr 8, out
    07:00, in 21:00 (14:00), release 21:30 (customs). Table B, 1 segment: 13:00 on HNL time (06:00, row 0600-0659), 9:00
    on SIN time (00:00 Apr 9, row 0000-0359); report to block-in 15:00 is over both: 15:00 needed. HNL-LAX reporting
    10:30 HST Apr 9 (13:00 free): SHORT; 12:30 (15:00): met. Flown SFO-HNL then a HNL-SIN deadhead (out 14:00, in 01:00,
    11:00): over Table B (19:00 from the report 06:00 to 01:00 HST; 13:00 for 2 segments on HNL time, 14:00 on SFO's
    09:00 PDT), but whether deadheads after the FDP count is not sure: 10:30 free of 11:00 is a '?'."""
    out = _duty(at(2027, 4, 6, "08:00"), _leg("HNL", "SIN", at(2027, 4, 6, "09:00"), at(2027, 4, 6, "19:30"), "0"))
    dh = _duty(at(2027, 4, 8, "06:00"), _leg("SIN", "HNL", at(2027, 4, 8, "07:00"), at(2027, 4, 8, "21:00"), "1", dh=True))
    t = TO.duty_timeout([out, dh, _lax(at(2027, 4, 9, "10:30"))], 2, 2, "roster", "332")
    assert (t["rest"]["ok"], t["rest"]["need"], t["rest"]["free"]) == (False, "15:00", "13:00") and "rest" in t["flags"]
    assert ("Rest after deadhead transportation (FAR 117.25(g), FOM 4.3.2.10): the duty before it was deadhead "
            "transportation only, 15:00 from its report to its last block-in, over its Table B FDP 9:00: a rest as long "
            "as the deadhead transportation (15:00, from the report), no less than 10 h; 13:00 free: SHORT, check with "
            "Crew Scheduling.") in t["lines"]
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
    assert any(s.startswith("Rest after deadhead transportation (FAR 117.25(g), FOM 4.3.2.10): the duty before it ended "
                            "with deadhead transportation after its last flown leg, 19:00 from its report") and
               s.endswith("10:30 free: ? SHORT of 11:00 if it applies.") for s in t["lines"])


def test_molokai_and_lanai_are_hawaii_stations():
    """Review PWA-MKK-LNY-customs-longitude: MKK and LNY are interisland (HAWAII), so no customs, a longitude and HST."""
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
    assert (t["last_out"]["hst"], t["last_out_ext"]["hst"], t["last_out_ext"]["pwa"]) == ("13:45 HST", "14:30 HST", True)
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
    assert any(s.startswith("? PWA rest: 2 x the preceding Duty Period (10.E.1.a.1) is not known") for s in t["lines"])


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
    assert ("? PWA rest, the other reading (10.E.2.a): as an Interisland Pilot, the duty before it being all interisland "
            "flying (2.A.36.b): in domicile after a duty that was all interisland flying, 12:00 needed: SHORT. The "
            "readings disagree, so the rest is not sure.") in t["lines"]
    t = TO.duty_timeout([d0, _lax(at(2027, 3, 2, "08:45"))], 1, 2, "roster", "332")
    assert t["pwa"]["rest"]["ok"] is True and "other" not in t["pwa"]["rest"] and t["flags"] == []


@pytest.mark.parametrize("rep_l,lim,ok", [("04:30", 7, False), ("05:00", 10, True)])
def test_pwa_landings_night_start_boundary_at_0459_local(rep_l, lim, ok):
    """Review TEST-boundary-gaps: 10.H.1's 7 landings for a duty starting 2200-0459 local; LAX in April is PDT (HST + 3):
    a report 04:30 PDT (01:30 HST) is a night start, 8 legs are over 7; 05:00 PDT (02:00 HST) is not, 8 of 10."""
    h, m = map(int, rep_l.split(":"))
    rep = at(2027, 4, 20, "00:00") + timedelta(hours=h - 3, minutes=m)
    t = TO.duty_timeout([_hops(rep, rep + timedelta(hours=1), 8, blk=30, every=50)], 0, 2, "roster", "332")
    assert (t["pwa"]["landings"]["n"], t["pwa"]["landings"]["max"], t["pwa"]["landings"]["ok"]) == (8, lim, ok)
    assert ("landings" in t["flags"]) is (not ok)


def test_a_sit_of_exactly_two_hours_is_a_repositioning_flight():
    """Review TEST-boundary-gaps: 2.A.62's minimal delay is read as a sit of 2:00 or less: 2:00 at KOA is a Repositioning
    Flight (no Mixed Flying), 2:01 is not."""
    assert not TO.mixed_flying(_sit_pair(120)[1]["legs"]) and TO.mixed_flying(_sit_pair(121)[1]["legs"])
    assert TO._repo([x for x in _sit_pair(120)[1]["legs"]], 1) == (True, timedelta(hours=2))


def test_card_box_has_a_chip_for_every_flag_timeout_sets(browser, tmp_path):
    """Review CARD-flags-segments-pilots-hidden: every key timeout.py appends to the flags maps to a chip and the label."""
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
