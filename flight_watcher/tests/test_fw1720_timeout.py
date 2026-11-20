"""1.7.20 (Ryan, Nov 20, 2026: "I need this page to calculate per FAR 117 and PWA when I timeout, both for if I extend or
if I do not. Add that number in bold with a dark orange square around it right of the report time"): the duty timeout
(timeout.py, FOM 125.4 4.3.2 = 14 CFR 117 Tables A, B and C; FOM 5.1.23.7 and 5.1.23.8 crew rest; PWA 2.19.b), as
working.py puts it on sensor.<prefix>_working_flight, and the layover card's box in a real Chromium.

Synthetic data only: made-up pairings (H39xx), flight numbers (9xxx) and crew ("Doe, Jane"). The first case keeps the
times of Ryan's Nov 20 duty (JFK-HNL, report 07:25 EST) and the duty periods before it, with other ids, so its numbers
are the ones checked against FOM 4.3.2 by hand (TIMEOUT_SPEC acceptance case)."""
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
        out.append(f"{dow} {flt} {a.lower()}-{b.lower()} {dep.replace(':', '')} {arr.replace(':', '')} {blk.replace(':', '')}")
    return " ".join(out)


def trip(key, report, legs, crew=CREW2, legs_read=True):
    """(item, record) of a trip: the record as own_trip_times keeps it (legs only when read)."""
    pid, start = key.split("|")
    d0 = date.fromisoformat(start)
    t = text(d0, legs)
    rec = {"report": report, "duties": parse_duties(t), "crew": list(crew)}
    if legs_read:
        rec["legs"] = parse_legs(t)
    end = d0 + timedelta(days=max(x[0] for x in legs) + 1)
    return {"trip": pid, "start": start, "end": end.isoformat(), "lay": ""}, rec


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


def run(trips, now, pkg=None, months=None, extra_items=()):
    items, own = [], {}
    for key, it in trips:
        items.append(it[0])
        own[key] = it[1]
    items += list(extra_items)
    return WK.working_flight(items, own, now, 2, pkg=pkg, months=months)


# ---------------------------------------------------------------- the acceptance case (Ryan's Nov 20 duty, other ids)
# The duty periods before it, from his own trips on Nov 20 (times only; ids, flights and names made up): duties-only
# records, as a trip read before 1.4.9 keeps them (no legs)
HIST = {
    "H3901|2026-10-08": ("11:05", [{"d": 0, "dep": 774, "arr": 1144, "stn": "SMF", "blk": 310, "dep_l": "12:54", "arr_l": "21:04"},
                                   {"d": 1, "dep": 1863, "arr": 2121, "stn": "HNL", "blk": 318, "dep_l": "09:03", "arr_l": "11:21"}]),
    "H3902|2026-10-12": ("14:05", [{"d": 0, "dep": 921, "arr": 1545, "stn": "JFK", "blk": 564, "dep_l": "15:21", "arr_l": "06:45"},
                                   {"d": 2, "dep": 3120, "arr": 3727, "stn": "HNL", "blk": 667, "dep_l": "09:00", "arr_l": "14:07"}]),
    "H3903|2026-10-17": ("22:15", [{"d": 0, "dep": 1394, "arr": 1784, "stn": "LAS", "blk": 330, "dep_l": "23:14", "arr_l": "07:44"},
                                   {"d": 2, "dep": 4148, "arr": 4450, "stn": "HNL", "blk": 387, "dep_l": "23:08", "arr_l": "02:10"}]),
    "H3904|2026-11-01": ("4:00", [{"d": 0, "dep": 320, "arr": 1121, "stn": "SIN", "blk": 801, "dep_l": "05:20", "arr_l": "12:41"},
                                  {"d": 2, "dep": 3978, "arr": 4808, "stn": "HNL", "blk": 830, "dep_l": "12:18", "arr_l": "08:08"}]),
    "H3905|2026-11-06": ("22:45", [{"d": 0, "dep": 1422, "arr": 1775, "stn": "LAS", "blk": 353, "dep_l": "23:42", "arr_l": "07:35"},
                                   {"d": 2, "dep": 3184, "arr": 3575, "stn": "HNL", "blk": 391, "dep_l": "07:04", "arr_l": "11:35"}]),
    "H3906|2026-11-09": ("10:55", [{"d": 0, "dep": 730, "arr": 1427, "stn": "SYD", "blk": 637, "dep_l": "12:10", "arr_l": "19:47"},
                                   {"d": 3, "dep": 4427, "arr": 4959, "stn": "HNL", "blk": 592, "dep_l": "21:47", "arr_l": "10:39"}]),
    "H3907|2026-11-15": ("22:45", [{"d": 0, "dep": 1417, "arr": 1761, "stn": "LAS", "blk": 344, "dep_l": "23:37", "arr_l": "07:21"},
                                   {"d": 2, "dep": 3192, "arr": 3582, "stn": "HNL", "blk": 390, "dep_l": "07:12", "arr_l": "11:42"}]),
}
JFK_TRIP = ("H3908|2026-11-18", "14:45", [(0, "9028", "HNL", "JFK", "15:47", "06:31", "9:44"),
                                          (2, "9029", "JFK", "HNL", "08:40", "14:55", "11:15")])


def acceptance(pkg=None, months="default", hist=True):
    trips = []
    if hist:
        for key, (rep, du) in HIST.items():
            pid, start = key.split("|")
            end = date.fromisoformat(start) + timedelta(days=max(x["arr"] for x in du) // 1440)
            trips.append((key, ({"trip": pid, "start": start, "end": end.isoformat(), "lay": ""},
                                {"report": rep, "duties": du, "crew": ["CA", "FO"]})))
    key, rep, legs = JFK_TRIP
    trips.append((key, trip(key, rep, legs, CREW3)))
    pkg = {key: {"eq": "332", "crew": "CA01FO01RO01"}} if pkg is None else pkg
    return run(trips, at(2026, 11, 20, "04:25"), pkg, months_for("2026-10", "2026-11") if months == "default" else months)


def test_acceptance_jfk_hnl_unacclimated_three_pilots_flight_time_binds():
    r = acceptance()
    a = r["attributes"]
    assert r["state"] == "HA9029 JFK-HNL" and a["leg"] == "2 of 2" and a["report"] == "07:25 local, 02:25 HST"
    t = a["timeout"]
    n, x, f = t["no_ext"], t["ext"], t["fdp"]
    assert (n["txt"], n["day"], n["local"], n["z"]) == ("16:40 HST", "Fri Nov 20", "16:40 HST", "02:40Z")
    assert n["by"] == "13:00 flight time (FAR 117.11)" and n["short"] == "13:00 flight time"
    assert n["at"] == "2026-11-20T16:40:00-10:00" and n["release_txt"] == "16:55 HST"
    assert x["txt"] == "16:40 HST" and x["by"] == "13:00 flight time; FDP with 2:00 extension 18:55 HST"
    assert x["release_txt"] == "16:55 HST"
    assert (f["limit"], f["end_txt"], f["ext_end_txt"], f["table"]) == ("14:30", "16:55 HST", "18:55 HST", "C")
    assert f["row"] == "0000-0559 (HNL time 02:25)" and f["acclimated"] is False
    assert (f["pilots"], f["rest_class"], f["rest_class_sure"], f["segments"]) == (3, 1, True, 1)
    assert f["alt"] == {"2": "15:55 HST", "3": "14:55 HST"}
    assert t["ft"] == {"limit": "13:00", "end_at": "2026-11-20T16:40:00-10:00", "end_txt": "16:40 HST",
                       "from": "scheduled out 08:40 EST"}
    c = t["cum"]
    assert (c["ft_672"]["used"], c["ft_672"]["room"], c["ft_672"]["cap_txt"]) == ("93:17", "6:43", "21:38 HST")
    assert (c["fdp_168"]["used"], c["fdp_168"]["room"]) == ("37:37", "22:23")
    assert c["fdp_672"]["used"] == "104:58"
    lines = "\n".join(t["lines"])
    for w in ("Report 07:25 EST (02:25 HST Fri Nov 20): 1:15 before scheduled departure out of domicile (PWA 2.19.b.1)",
              "not acclimated: JFK is 84 deg from HNL, 24:39 free from duty (36 h needed), 24:54 in that theater (72 h "
              "needed)", "FAR 117.13(b), 117.17(b), FOM 4.3.2.4", "3 pilots (the trip's crew list): augmented, Table C",
              "A330 LDMCR bunks 1 and 4 (FOM 5.1.23.8): Class 1", "Class 2 ends 15:55 HST, Class 3 14:55 HST",
              "Table C row 0000-0559 (HNL time 02:25), Class 1, 3 pilots: 15:00, less 0:30 = FDP 14:30, ends 16:55 HST",
              "from scheduled out 08:40 EST (03:40 HST), block-in by 16:40 HST; moves with the actual out",
              "FAR 117.19(a), FOM 4.3.2.5", "FAR 117.19(b)", "6:43 left", "FAR 117.23(b)(1)", "FAR 117.23(c)(1)",
              "Duty ends 15 min after block-in (PWA 2.19.b.2): release 16:55 HST without an extension, 16:55 HST with one"):
        assert w in lines, w
    assert TO.PWA10 in t["not_checked"]
    assert any("FAR 117.19(a)(2)" in s for s in t["not_checked"])
    blob = json.dumps(t)
    assert chr(0x2014) not in blob and "Doe" not in blob and "Roe" not in blob and "1000" not in blob.replace("1000 h", "")
    assert len(blob) < 6000  # the sensor stays far under ATTR_MAX


def test_acceptance_with_every_trip_read_gives_the_same_times():
    """Legs read for every trip (not just duty periods) give the same numbers."""
    trips = []
    for key, (rep, du) in HIST.items():
        it, rec = (lambda pid, start: ({"trip": pid, "start": start, "end": start, "lay": ""}, {"report": rep}))(*key.split("|"))
        rec["duties"] = du
        prev, legs = "HNL", []
        for i, d in enumerate(du):
            legs.append({"dep": d["dep"], "arr": d["arr"], "to": d["stn"], "frm": prev, "blk": d["blk"],
                         "dep_l": d["dep_l"], "arr_l": d["arr_l"], "flt": str(9100 + i)})
            prev = d["stn"]
        rec["legs"], rec["crew"] = legs, CREW2
        it["end"] = (date.fromisoformat(it["start"]) + timedelta(days=max(d["arr"] for d in du) // 1440)).isoformat()
        trips.append((key, (it, rec)))
    key, rep, legs = JFK_TRIP
    trips.append((key, trip(key, rep, legs, CREW3)))
    t = run(trips, at(2026, 11, 20, "04:25"), {key: {"eq": "332", "crew": "CA01FO01RO01"}},
            months_for("2026-10", "2026-11"))["attributes"]["timeout"]
    a = acceptance()["attributes"]["timeout"]
    assert t["no_ext"] == a["no_ext"] and t["ext"] == a["ext"] and t["fdp"] == a["fdp"] and t["cum"] == a["cum"]


def test_cumulative_needs_the_whole_window_on_file():
    """No schedule months: the cumulative limits are listed as not checked, and the timeout stands without them. A
    window that reaches before the first month on file is not checked either."""
    t = acceptance(months=None)["attributes"]["timeout"]
    assert t["cum"] == {} and t["no_ext"]["txt"] == "16:40 HST"
    assert sum("not all on file, not checked" in s for s in t["not_checked"]) == 3
    t = acceptance(months=months_for("2026-11"))["attributes"]["timeout"]
    assert set(t["cum"]) == {"fdp_168"}  # 168 h back from Nov 20 is in November; 672 h is not
    assert any(s.startswith("100 h flight time in 672 h (FAR 117.23(b)(1)): your line before") for s in t["not_checked"])


def test_the_package_crew_line_counts_when_there_is_no_roster_and_a_mismatch_is_said():
    key, rep, legs = JFK_TRIP
    it, rec = trip(key, rep, legs, [])
    t = run([(key, (it, rec))], at(2026, 11, 20, "04:25"), {key: {"eq": "332", "crew": "CA01FO01RO01"}})["attributes"]["timeout"]
    assert t["fdp"]["pilots"] == 3 and t["fdp"]["pilots_from"] == "package crew line CA01FO01RO01"
    it, rec = trip(key, rep, legs, CREW3)
    t = run([(key, (it, rec))], at(2026, 11, 20, "04:25"), {key: {"eq": "332", "crew": "CA01FO02RO01"}})["attributes"]["timeout"]
    assert t["fdp"]["pilots"] == 3
    assert any("crew list shows 3 pilot seats, the package crew line CA01FO02RO01 4" in s for s in t["lines"])
    # neither: no timeout attribute (never a guess)
    it, rec = trip(key, rep, legs, ["CA Doe, Jane (10001)"])
    a = run([(key, (it, rec))], at(2026, 11, 20, "04:25"), {})["attributes"]
    assert "timeout" not in a and a["report"] == "07:25 local, 02:25 HST"


def test_pilots_of_counts_pilot_seats_only():
    assert TO.pilots_of(["CA Doe, Jane (1)", "FO OPEN", "RO Roe, Rick (2)", "FA Poe, Pat (3)"]) == (3, "roster")
    assert TO.pilots_of([["CA", "Doe, Jane"], {"pos": "FO"}]) == (2, "roster")
    assert TO.pilots_of([], "CA02FO02") == (4, "package")
    assert TO.pilots_of(None, "") == (None, "")


# ---------------------------------------------------------------- acclimated at home, Table C by HNL time
def test_acclimated_hnl_report_table_c_by_hnl_time_with_no_reduction():
    key = "H3910|2026-11-09"
    it = trip(key, "10:55", [(0, "9011", "HNL", "SYD", "12:10", "19:47", "10:37")], CREW3)
    t = run([(key, it)], at(2026, 11, 9, "09:00"), {key: {"eq": "332"}})["attributes"]["timeout"]
    f = t["fdp"]
    assert f["acclimated"] is True and f["row"] == "0700-1259 (HNL time 10:55)" and f["limit"] == "17:00"
    assert f["end_txt"] == "03:55 HST" and f["ext_end_txt"] == "05:55 HST" and f["alt"] == {"2": "03:25 HST", "3": "01:55 HST"}
    # flight time 13:00 from out 12:10 HST: block-in by 01:10 HST, the next day
    assert t["no_ext"]["txt"] == "01:10 HST" and t["no_ext"]["day"] == "Tue Nov 10" and t["report_day"] == "Mon Nov 9"
    assert t["no_ext"]["local"] == "22:10 AEDT"  # SYD keeps daylight time in November
    assert "less 0:30" not in " ".join(t["lines"]) and "FLICA check-in 10:55 HST" in t["lines"][0]


# ---------------------------------------------------------------- SIN: acclimated there, then home unacclimated
SIN = ("H3920|2026-11-01", "4:00", [(0, "9021", "HNL", "SIN", "05:20", "12:41", "13:21"),
                                    (2, "9022", "SIN", "HNL", "12:18", "08:08", "13:50")])


def _sin_line():
    key, rep, legs = SIN
    out = [(key, trip(key, rep, legs, CREW4))]
    k2 = "H3921|2026-11-05"  # HNL-LAX the next morning: 25:52 free since the SIN release (08:08 + 0:30 customs)
    out.append((k2, trip(k2, "10:00", [(0, "9023", "HNL", "LAX", "11:00", "18:00", "5:00")], CREW2)))
    return out, {key: {"eq": "332", "crew": "CA01FO02RO01"}, k2: {"eq": "332", "crew": "CA01FO01"}}


def test_sin_layover_of_46_h_free_acclimates_there():
    trips, pkg = _sin_line()
    t = run(trips, at(2026, 11, 3, "16:00"), pkg)["attributes"]["timeout"]
    f = t["fdp"]
    # report 1:15 before 12:18 SIN = 11:03 SIN (17:03 HST Nov 3); 46:07 free since the 18:41 HST block-in + 0:15
    assert f["acclimated"] is True and f["row"] == "0700-1259 (SIN time 11:03)"
    assert f["pilots"] == 4 and f["rest_class"] == 2 and f["limit"] == "18:00"  # 4 pilots on the A330: Class 2
    assert any("acclimated to the SIN theater (46:07 free from duty" in s for s in t["lines"])
    assert any("hard-blocks cabin seat 3C or 3G" in s for s in t["lines"])
    assert t["no_ext"]["release_txt"] == t["no_ext"]["txt"].replace(t["no_ext"]["txt"][:5], (
        datetime.fromisoformat(t["no_ext"]["at"]) + timedelta(minutes=30)).astimezone(HST).strftime("%H:%M"))  # customs


def test_home_report_within_36_h_after_sin_is_unacclimated_on_the_sin_clock():
    trips, pkg = _sin_line()
    t = run(trips, at(2026, 11, 5, "09:00"), pkg)["attributes"]["timeout"]
    f = t["fdp"]
    # HNL is 98 deg from SIN: not acclimated; 10:00 HST is 04:00 SIN on Nov 6: Table B 0400-0459, 1 segment, 10:00 - 0:30
    assert f["acclimated"] is False and f["table"] == "B" and f["row"] == "0400-0459 (SIN time 04:00)"
    assert f["limit"] == "9:30" and f["end_txt"] == "19:30 HST"
    # Table A on SIN time 04:00 (0000-0459): 8:00 from out 11:00 HST
    assert t["ft"]["limit"] == "8:00" and t["ft"]["end_txt"] == "19:00 HST"
    assert t["no_ext"]["txt"] == "19:00 HST" and t["no_ext"]["short"] == "8:00 flight time"
    assert t["ext"]["txt"] == "19:00 HST" and "FDP with 2:00 extension 21:30 HST" in t["ext"]["by"]
    assert any("HNL is 98 deg from SIN, 25:52 free from duty (36 h needed)" in s for s in t["lines"])


# ---------------------------------------------------------------- 2 pilots: Table B, 3 segments, Table A
def test_two_pilots_three_segments_table_b_and_table_a():
    key = "H3930|2026-11-12"
    legs = [(0, "9031", "HNL", "OGG", "06:30", "07:10", "0:40"), (0, "9032", "OGG", "HNL", "08:00", "08:40", "0:40"),
            (0, "9033", "HNL", "LAX", "10:00", "17:10", "5:10")]
    t = run([(key, trip(key, "05:30", legs, CREW2))], at(2026, 11, 12, "05:00"), {key: {"eq": "332"}})["attributes"]["timeout"]
    f = t["fdp"]
    assert f["table"] == "B" and f["segments"] == 3 and f["row"] == "0500-0559 (HNL time 05:30)"
    assert f["limit"] == "12:00" and f["end_txt"] == "17:30 HST" and f["rest_class"] is None and f["alt"] == {}
    # Table A 0500-1959: 9:00, 1:20 flown before the last leg's 10:00 HST out: 17:40 HST
    assert t["ft"]["limit"] == "9:00" and t["ft"]["end_txt"] == "17:40 HST"
    assert t["no_ext"]["txt"] == "17:30 HST" and t["no_ext"]["by"] == "FDP 12:00 (FAR 117.13, Table B)"
    assert t["ext"]["txt"] == "17:40 HST" and t["ext"]["by"] == "9:00 flight time; FDP with 2:00 extension 19:30 HST"
    assert any("Segments: 3 in this FDP (every leg counted, a deadhead too: conservative)" in s for s in t["lines"])
    assert t["no_ext"]["local"] == "19:30 PST"  # the arrival station's own clock
    # the working leg can be any leg of the duty: the same duty, the same timeout
    t2 = run([(key, trip(key, "05:30", legs, CREW2))], at(2026, 11, 12, "09:30"), {key: {"eq": "332"}})
    assert t2["attributes"]["leg"] == "3 of 3" and t2["attributes"]["timeout"]["no_ext"] == t["no_ext"]


def test_a_deadhead_after_the_last_flown_leg_is_not_fdp():
    duties = [{"report": at(2026, 11, 12, "06:00"), "legs": [
        {"dep": at(2026, 11, 12, "07:00"), "arr": at(2026, 11, 12, "12:00"), "blk": 300, "frm": "HNL", "to": "LAX", "flt": "1"},
        {"dep": at(2026, 11, 12, "13:00"), "arr": at(2026, 11, 12, "14:30"), "blk": 90, "frm": "LAX", "to": "SFO", "flt": "2", "dh": True}]}]
    t = TO.duty_timeout(duties, 0, 2, "roster", "332")
    assert t["fdp"]["segments"] == 1 and t["sched_in_txt"] == "12:00 HST"
    assert t["ft"]["end_txt"] == "16:00 HST"  # 9:00 from 07:00 out; the deadhead is no flight time
    assert TO.duty_timeout([{"report": duties[0]["report"], "legs": duties[0]["legs"][1:]}], 0, 2, "roster", "332") is None


# ---------------------------------------------------------------- 4 pilots on the A330, unknown equipment
def test_four_pilots_on_the_a330_use_class_2():
    key = "H3940|2026-11-01"
    t = run([(key, trip(key, "4:00", [(0, "9041", "HNL", "SIN", "05:20", "12:41", "13:21")], CREW4))],
            at(2026, 11, 1, "03:00"), {key: {"eq": "332"}})["attributes"]["timeout"]
    f = t["fdp"]
    assert (f["pilots"], f["rest_class"], f["row"], f["limit"]) == (4, 2, "0000-0559 (HNL time 04:00)", "15:30")
    assert t["no_ext"]["txt"] == "19:30 HST" and t["no_ext"]["short"] == "FDP 15:30"
    assert t["ext"]["txt"] == "21:30 HST" and t["ext"]["by"] == "FDP 15:30 with the 2:00 extension (FAR 117.19(a))"
    assert t["ft"]["limit"] == "17:00" and t["ft"]["end_txt"] == "22:20 HST"
    assert f["alt"] == {"2": "19:30 HST", "3": "17:30 HST"}


def test_unknown_equipment_uses_class_3_and_says_so():
    key = "H3941|2026-11-09"
    t = run([(key, trip(key, "10:55", [(0, "9042", "HNL", "SYD", "12:10", "19:47", "10:37")], CREW3))],
            at(2026, 11, 9, "09:00"), None)["attributes"]["timeout"]
    f = t["fdp"]
    assert f["rest_class"] == 3 and f["rest_class_sure"] is False and f["limit"] == "15:00"
    assert t["no_ext"]["txt"] == "01:10 HST" and t["no_ext"]["short"] == "13:00 flight time"  # FT 01:10 < FDP 01:55
    line = next(s for s in t["lines"] if s.startswith("Rest facility"))
    assert "equipment not on file" in line and "Class 3 used" in line and "(?)" in line
    assert any("Class 3 ?, 3 pilots" in s for s in t["lines"])
    t787 = run([(key, trip(key, "10:55", [(0, "9042", "HNL", "SYD", "12:10", "19:47", "10:37")], CREW3))],
               at(2026, 11, 9, "09:00"), {key: {"eq": "789"}})["attributes"]["timeout"]
    assert t787["fdp"]["rest_class"] == 1 and any("787 OFCR (FOM 5.1.23.7)" in s for s in t787["lines"])


# ---------------------------------------------------------------- the 60 h FDP in 168 h cap binds
def test_sixty_hours_fdp_in_168_binds():
    trips = []
    for k, d in enumerate((2, 3, 4, 5)):  # four turns of 12:45 FDP (06:00 to 18:45 HST)
        key = f"H395{k}|2026-11-0{d}"
        trips.append((key, trip(key, "06:00", [(0, f"905{k}", "HNL", "SFO", "07:00", "14:00", "5:00"),
                                               (0, f"906{k}", "SFO", "HNL", "15:30", "18:45", "5:15")], CREW2)))
    key = "H3960|2026-11-06"
    trips.append((key, trip(key, "07:00", [(0, "9070", "HNL", "LAX", "08:00", "15:00", "5:00")], CREW2)))
    t = run(trips, at(2026, 11, 6, "06:30"), {}, months_for("2026-10", "2026-11"))["attributes"]["timeout"]
    c = t["cum"]["fdp_168"]
    assert (c["used"], c["room"], c["cap_txt"]) == ("57:00", "3:00", "16:00 HST")
    assert t["fdp"]["end_txt"] == "21:00 HST" and t["ft"]["end_txt"] == "17:00 HST"
    assert t["no_ext"]["txt"] == "16:00 HST" and t["no_ext"]["by"] == "60 h FDP in 168 h (FAR 117.23(c)(1))"
    assert t["ext"]["txt"] == "16:00 HST" and t["ext"]["by"].startswith("60 h FDP in 168 h; FDP with 2:00 extension 23:00 HST")
    assert any("cap an extension before takeoff" in s for s in t["lines"])


# ---------------------------------------------------------------- a duty across midnight
def test_a_red_eye_across_midnight():
    key = "H3970|2026-11-06"
    t = run([(key, trip(key, "22:45", [(0, "9071", "HNL", "LAS", "23:42", "07:35", "5:53")], CREW2))],
            at(2026, 11, 6, "20:00"), {key: {"eq": "332"}})["attributes"]["timeout"]
    f = t["fdp"]
    assert f["row"] == "2200-2259 (HNL time 22:45)" and f["limit"] == "11:00" and f["end_txt"] == "09:45 HST"
    assert t["ft"]["limit"] == "8:00" and t["ft"]["end_txt"] == "07:42 HST"  # Table A 2000-2359
    assert (t["no_ext"]["txt"], t["no_ext"]["day"], t["report_day"]) == ("07:42 HST", "Sat Nov 7", "Fri Nov 6")
    assert t["no_ext"]["local"] == "09:42 PST" and t["sched_in_txt"] == "05:35 HST"


def test_a_report_later_than_the_first_departure_is_the_day_before():
    key = "H3971|2026-11-07"  # FLICA's trip day is the departure's (00:30); its check-in 23:30 is the night before
    t = run([(key, trip(key, "23:30", [(0, "9072", "HNL", "LAX", "00:30", "07:30", "5:00")], CREW2))],
            at(2026, 11, 6, "22:00"), {key: {"eq": "332"}})["attributes"]["timeout"]
    assert t["report_txt"] == "23:30 HST" and t["report_day"] == "Fri Nov 6"
    assert t["fdp"]["row"] == "2300-2359 (HNL time 23:30)" and t["fdp"]["limit"] == "10:00"


# ---------------------------------------------------------------- daylight time: LAX in July
def test_lax_in_july_reads_pdt_and_takes_the_lower_clock():
    key = "H3980|2026-07-10"
    legs = [(0, "9081", "HNL", "LAX", "08:00", "16:00", "5:00"), (2, "9082", "LAX", "HNL", "09:00", "11:30", "5:30")]
    t = run([(key, trip(key, "07:00", legs, CREW2))], at(2026, 7, 12, "05:00"), {key: {"eq": "332"}})["attributes"]["timeout"]
    # 09:00 PDT is 06:00 HST: report 1:15 before, 04:45 HST = 07:45 PDT. Acclimated to the HNL theater (LAX within 60
    # deg); HNL time gives Table B 0400-0459 (10:00), LAX time 0700-1159 (14:00): the lower is used
    assert t["report_txt"] == "04:45 HST" and t["fdp"]["acclimated"] is True
    assert t["fdp"]["row"] == "0400-0459 (HNL time 04:45)" and t["fdp"]["limit"] == "10:00"
    assert any("LAX time 07:45 gives row 0700-1159, 14:00: the lower is used" in s for s in t["lines"])
    assert t["lines"][0].startswith("Report 07:45 PDT (04:45 HST")
    assert t["ft"]["limit"] == "8:00" and t["ft"]["from"] == "scheduled out 09:00 PDT"  # Table A on HNL time 04:45


# ---------------------------------------------------------------- the theater table
def test_every_station_has_a_longitude_and_the_theater_checks_hold():
    assert set(TO.LON) == set(WK.ZONES)
    near = ("SYD", "MEL", "BNE", "AKL", "PPT", "LAX", "SFO", "SEA", "SAN", "PDX", "LAS", "PHX", "ANC", "OGG")
    far = ("JFK", "BOS", "ORD", "DFW", "AUS", "NRT", "HND", "KIX", "ICN", "SIN", "MNL")
    assert all(TO.same_theater("HNL", s) for s in near), [s for s in near if not TO.same_theater("HNL", s)]
    assert not any(TO.same_theater("HNL", s) for s in far), [s for s in far if TO.same_theater("HNL", s)]
    assert round(TO.ang(TO.LON["SYD"], TO.LON["HNL"])) == 51 and round(TO.ang(TO.LON["AUS"], TO.LON["HNL"]), 1) == 60.2
    assert round(TO.ang(TO.LON["NRT"], TO.LON["HNL"]), 1) == 61.7
    assert TO.same_theater("HNL", "XYZ") is None


def test_the_watcher_uses_the_one_us_station_list():
    src = open(os.path.join(HERE, "watcher.py"), encoding="utf-8").read()
    assert "US_STATIONS = TO.US_STATIONS" in src
    assert "timeout.py" in open(os.path.join(HERE, "Dockerfile"), encoding="utf-8").read()


def test_a_schedule_item_that_may_be_duty_makes_acclimation_unknown_and_the_lower_is_used():
    """36 h free at home after SIN would acclimate him to HNL, but a training day inside it may be duty: the lower of
    acclimated (HNL time) and not (SIN time, less 0:30) is used."""
    key, rep, legs = SIN
    trips = [(key, trip(key, rep, legs, CREW4))]
    k2 = "H3922|2026-11-07"  # 2 days after the SIN release (Nov 4 08:38 HST): 49:52 free
    trips.append((k2, trip(k2, "10:30", [(0, "9024", "HNL", "LAX", "11:30", "18:30", "5:00")], CREW2)))
    pkg = {key: {"eq": "332"}, k2: {"eq": "332"}}
    clean = run(trips, at(2026, 11, 6, "09:00"), pkg)["attributes"]["timeout"]
    assert clean["fdp"]["acclimated"] is True and clean["fdp"]["row"] == "0700-1159 (HNL time 10:30)"
    busy = run(trips, at(2026, 11, 6, "09:00"), pkg,
               extra_items=[{"trip": "TRNG", "start": "2026-11-05", "end": "2026-11-05", "lay": ""}])["attributes"]["timeout"]
    assert busy["fdp"]["acclimated"] is None
    # SIN time 04:30 (Nov 8): Table B 0400-0459, 10:00 less 0:30 is lower than HNL 0700-1159's 14:00
    assert busy["fdp"]["row"] == "0400-0459 (SIN time 04:30)" and busy["fdp"]["limit"] == "9:30"
    assert any(s.startswith("Acclimation (FAR 117.3, FOM 4.3.2.4.6): ? acclimated to HNL only if") for s in busy["lines"])
    vac = run(trips, at(2026, 11, 6, "09:00"), pkg,
              extra_items=[{"trip": "VAC", "start": "2026-11-05", "end": "2026-11-05", "lay": ""}])["attributes"]["timeout"]
    assert vac["fdp"] == clean["fdp"]


def test_news_and_the_sensor_payload_keep_working():
    r = acceptance()
    assert WK.news(r)["attributes"]["timeout"] == r["attributes"]["timeout"]
    later = WK.working_flight([], {}, at(2026, 11, 20, "05:00"))  # no trip: no timeout
    assert "timeout" not in later["attributes"]


# ---------------------------------------------------------------- the Watcher passes the package detail (both instances)
from test_working import W  # noqa: E402,F401  (the Watcher fixture: Ryan's instance and a second pilot's)


def test_publish_working_flight_passes_the_package_detail(W, monkeypatch):
    key, rep, legs = JFK_TRIP
    it, rec = trip(key, rep, legs, CREW3)
    W.S["schedule"] = {"2026-11": {"items": [it], "days": months_for("2026-11")["2026-11"]["days"]}}
    W.S["own_trips"] = {key: rec}
    calls = []
    monkeypatch.setattr(W, "pkg_detail_for", lambda period, pid, st=None: calls.append((period, pid, st)) or
                        {"eq": "332", "crew": "CA01FO01RO01"})
    monkeypatch.setattr(W, "bid_period_key", lambda iso: "2026-11")
    assert W.publish_working_flight(now=at(2026, 11, 20, "04:25"), force=True)
    sent = [json.loads(p) for t, p, r in W.FAKE.msgs if t == f"{W.T}/working_flight" and r][-1]
    t = sent["attributes"]["timeout"]
    assert t["no_ext"]["txt"] == "16:40 HST" and t["fdp"]["rest_class"] == 1
    assert calls and calls[-1] == ("2026-11", "H3908", "2026-11-18")
    # a package that cannot be read: still published, eq unknown (Class 3, '?')
    monkeypatch.setattr(W, "pkg_detail_for", lambda *a, **k: (_ for _ in ()).throw(OSError("gone")))
    assert W.publish_working_flight(now=at(2026, 11, 20, "04:26"), force=True)
    sent = [json.loads(p) for t, p, r in W.FAKE.msgs if t == f"{W.T}/working_flight" and r][-1]
    assert sent["attributes"]["timeout"]["fdp"]["rest_class"] == 3


# ---------------------------------------------------------------- the card, in a real Chromium
from test_layover_card import DARK, HA_DARK, HA_LIGHT, LIGHT, _page, _states, browser  # noqa: E402,F401

ORANGE = "rgb(194, 65, 12)"  # #c2410c


def _watcher_only(tmp_path, timeout=True):
    """The admin's states with no Hark sensor: the Watcher's working flight (report block in the header), with the
    acceptance case's timeout."""
    st = _states(tmp_path, hark_attrs={}, notes=False)
    a = st["sensor.flight_watcher_working_flight"]["attributes"]
    a.update({"pairing": "H3908", "flight": "HA9029", "origin": "JFK", "dest": "HNL", "leg": "2 of 2", "date": "2026-11-20",
              "dep_sched": "08:40 local, 03:40 HST", "arr_sched": "14:55 local, 14:55 HST", "report": "07:25 local, 02:25 HST",
              "status": "Enroute per schedule"})
    if timeout:
        a["timeout"] = acceptance()["attributes"]["timeout"]
    return st


def test_card_box_right_of_the_report_bold_and_opens_its_basis(browser, tmp_path):
    pg = browser.new_page(viewport={"width": 390, "height": 844})
    pg.set_content(_page(_watcher_only(tmp_path)))
    card = pg.locator("flight-watcher-layover-card")
    box, rep = card.locator("[data-to]"), card.locator("[data-van]")
    assert box.is_visible() and rep.locator(".vl").inner_text().lower() == "report"
    assert box.locator(".tol").inner_text().lower() == "timeout"
    assert box.locator("[data-tono]").inner_text() == "16:40 HST"
    assert box.locator("[data-toext]").inner_text() == "Ext 16:40 HST"
    assert box.locator("[data-toby]").inner_text() == "13:00 flight time"
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
    assert "No extension: 16:40 HST Fri Nov 20, release 16:55 HST" in txt and "With extension: 16:40 HST" in txt
    assert "Table C row 0000-0559 (HNL time 02:25)" in txt and "PWA Section 10 (Hours of Service)" in txt
    assert card.locator("[data-tolines] li").count() == len(acceptance()["attributes"]["timeout"]["lines"])
    assert det.bounding_box()["y"] >= card.locator(".hd").bounding_box()["y"] + card.locator(".hd").bounding_box()["height"] - 1
    assert pg.evaluate("window.root().activeElement && window.root().activeElement.matches('[data-to]')")
    pg.keyboard.press("Enter")
    assert not card.locator("[data-todet]").is_visible()
    pg.keyboard.press("Space")
    assert card.locator("[data-todet]").is_visible()
    assert pg.evaluate("document.documentElement.scrollWidth") <= 390
    pg.close()


def test_card_without_the_attribute_shows_no_box_and_nothing_else_changes(browser, tmp_path):
    pg = browser.new_page(viewport={"width": 390, "height": 844})
    pg.set_content(_page(_watcher_only(tmp_path, timeout=False)))
    card = pg.locator("flight-watcher-layover-card")
    assert card.locator("[data-to]").count() == 0 and card.locator("[data-todet]").count() == 0
    assert card.locator(".rt").count() == 0 and card.locator(".hd.wt").count() == 0 and card.locator(".tmw").count() == 0
    assert card.locator("[data-van] .vt").inner_text() == "07:25"
    pg.close()


def test_card_with_hark_and_a_van_puts_the_box_right_of_the_report_line(browser, tmp_path):
    """Hark's sensor (the admin's layover data) carries no timeout: the Watcher's for the same pairing and origin shows,
    right of the Report line (the van holds the header). Another pairing's timeout never shows."""
    st = _states(tmp_path, notes=False)
    st["sensor.flight_watcher_working_flight"]["attributes"]["timeout"] = acceptance()["attributes"]["timeout"]
    pg = browser.new_page(viewport={"width": 390, "height": 844})
    pg.set_content(_page(st))
    card = pg.locator("flight-watcher-layover-card")
    assert card.locator("[data-van] .vl").inner_text().lower() == "van"
    box, line = card.locator(".tmw [data-to]"), card.locator(".tm div", has_text="Report")
    assert box.is_visible() and box.locator("[data-tono]").inner_text() == "16:40 HST"
    bb, lb = box.bounding_box(), line.bounding_box()
    assert bb["y"] < lb["y"] + lb["height"] + 1 and bb["x"] >= lb["x"]  # level with the Report line, to its right
    assert pg.evaluate("document.documentElement.scrollWidth") <= 390
    pg.close()
    st["sensor.flight_watcher_working_flight"]["attributes"]["origin"] = "HNL"  # another leg than Hark's
    pg = browser.new_page(viewport={"width": 390, "height": 844})
    pg.set_content(_page(st))
    assert pg.locator("flight-watcher-layover-card [data-to]").count() == 0
    pg.close()


SHOTS = os.environ.get("FW_171_SHOTS", "")


@pytest.mark.parametrize("width", [390, 1100])
@pytest.mark.parametrize("theme", ["light", "dark", "ha-light", "ha-dark"])
def test_card_timeout_box_reads_on_every_theme(browser, tmp_path, width, theme):
    """WCAG AA for every text node (the box's text is the theme's own colors), the dark orange border at least 3:1
    against the card on light and dark, no sideways scroll; the basis open too."""
    pg = browser.new_page(viewport={"width": width, "height": 844})
    pg.set_content(_page(_watcher_only(tmp_path), theme={"light": LIGHT, "dark": DARK, "ha-light": HA_LIGHT, "ha-dark": HA_DARK}[theme]))
    card = pg.locator("flight-watcher-layover-card")
    card.locator("[data-to]").click()
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
