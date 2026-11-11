"""FW-0042 (1.4.13): smart push fields. The commute check (two scheduled nonstops arriving HNL before report, PWA
26.QQ.2; one home 60+ min after release), the bid month's line / reserve rules, the pairing value, on every pot,
Tradeboard, close-in and finds row and on event/new_pairing. Synthetic only: made-up airports (AAA, BBB, CCC),
made-up times and rates, made-up pairings and names. Nothing personal ships in git: without smart.json every field
is '' and the sensors carry what they did before."""
import json
import os
import sys
from datetime import date, datetime, timedelta

import pytest

import pot as P
import smart as SM

RAW = {"v": 1, "updated": "2030-01-01", "source": "synthetic",
       "airports": ["AAA", "BBB"],
       # arrivals: AAA 05:50, 06:20, 09:50; BBB 06:00, 08:00
       "in": {"AAA": {"dep": ["05:00", "05:30", "09:00"], "block_max": 50},
              "BBB": {"dep": ["05:10", "07:10"], "block_max": 50}},
       "home": {"AAA": ["12:00", "18:00"], "BBB": ["12:00", "16:00"]},
       "home_gap_min": 60,
       "month_types": {"2030-03": "line", "2030-04": "reserve", "2026-11": "reserve"},
       "vac": [["2030-03-20", "2030-03-22"]],
       "rate": 100.0, "breakeven": "50:00", "min_days_off": 10, "cap_credit": "40:00"}
CFG = SM.normalize(RAW)


def at(d, hm):
    return datetime(2030, 3, d, int(hm[:2]), int(hm[3:]))


# ---------------------------------------------------------------- commute
def test_two_arrivals_before_report_and_a_home_flight_count():
    r, why = SM.comm(at(12, "07:00"), at(12, "13:00"), CFG)
    assert r == "AAA"  # AAA: 05:50 and 06:20 in; BBB: 06:00 only
    assert "AAA in 2 by 06:20" in why and "BBB in 1 by 06:00 (needs 2)" in why and "PWA 26.QQ.2" in why
    assert SM.comm(at(12, "08:30"), at(12, "13:00"), CFG)[0] == "AAA/BBB"  # both, in the config's order


def test_one_arrival_only_is_not_enough():
    assert SM.comm(at(12, "06:10"), at(12, "13:00"), CFG)[0] == "No"  # AAA 05:50 only, BBB 06:00 only
    # an arrival at the report time is not before it
    assert SM.comm(at(12, "06:20"), at(12, "13:00"), CFG)[0] == "No"
    # two flights at the same time are two flights
    two = SM.normalize(dict(RAW, airports=["CCC"], **{"in": {"CCC": {"dep": ["06:00", "06:00"], "block_max": 50}},
                                                     "home": {"CCC": ["20:00"]}}))
    assert SM.comm(at(12, "07:00"), at(12, "13:00"), two)[0] == "CCC"


def test_overnight_report_before_the_first_arrival_is_no():
    r, why = SM.comm(at(12, "01:00"), at(12, "13:00"), CFG)
    assert r == "No" and "AAA in 0 (needs 2)" in why and "BBB in 0 (needs 2)" in why
    # an arrival that would land after midnight is not the report day's
    late = SM.normalize(dict(RAW, airports=["CCC"], **{"in": {"CCC": {"dep": ["23:30", "23:40"], "block_max": 50}},
                                                      "home": {"CCC": ["20:00"]}}))
    assert SM.comm(at(12, "23:59"), at(13, "13:00"), late)[0] == "No"


def test_home_needs_a_nonstop_60_min_after_release():
    assert SM.comm(at(12, "08:30"), at(12, "15:00"), CFG)[0] == "AAA/BBB"  # BBB 16:00 is exactly 60 min after
    r, why = SM.comm(at(12, "08:30"), at(12, "15:01"), CFG)
    assert r == "AAA" and "BBB in 2 by 08:00, no home" in why  # 59 min: too soon
    gap90 = SM.normalize(dict(RAW, home_gap_min=90))
    assert SM.comm(at(12, "08:30"), at(12, "15:00"), gap90)[0] == "AAA"


def test_release_after_the_last_flight_home_is_no():
    assert SM.comm(at(12, "08:30"), at(12, "17:30"), CFG)[0] == "No"  # AAA 18:00 is 30 min after
    assert SM.comm(at(12, "08:30"), at(12, "23:30"), CFG)[0] == "No"  # 60 min later is tomorrow


# a first flight home at 06:00, as early as a release after midnight could reach
NIGHT_RAW = dict(RAW, airports=["AAA"], **{"in": {"AAA": {"dep": ["05:00", "05:30"], "block_max": 50}},
                                          "home": {"AAA": ["06:00", "12:00", "20:30"]}})
NIGHT = SM.normalize(NIGHT_RAW)


def test_an_overnight_release_has_no_same_day_home():
    """The mirror of the IN rule (an overnight report is No): a release after midnight leaves the pilot in HNL
    overnight like a 22:00 one, so the next morning's first flight home does not make it a same-day home."""
    rep = at(11, "08:30")
    for rel in (at(11, "23:55"), at(12, "00:05"), at(12, "01:30"), at(12, "04:00"), at(12, "04:59")):
        r, why = SM.comm(rep, rel, NIGHT)
        assert r == "No" and "AAA in 2 by 06:20, no home (overnight release)" in why, rel
    r, why = SM.comm(rep, at(11, "22:00"), NIGHT)
    assert r == "No" and why.count("no home") == 1 and "overnight" not in why  # after the last flight, same day
    assert SM.comm(rep, at(11, "13:00"), NIGHT)[0] == "AAA"  # home 20:30
    assert SM.comm(rep, at(12, "05:00"), NIGHT)[0] == "AAA"  # the day's first flight, exactly 60 min later
    # later releases never read better: once No, No to the end of the night
    seen, t = [], at(11, "19:00")
    while t < at(12, "05:00"):
        seen.append(SM.comm(rep, t, NIGHT)[0])
        t += timedelta(minutes=5)
    assert "No" in seen and "AAA" not in seen[seen.index("No"):]
    # where the night ends is the pilot's call (smart.json home_day_start, 05:00 without it)
    early = SM.normalize(dict(NIGHT_RAW, home_day_start="04:00"))
    assert early["home_day_start"] == 240 and NIGHT["home_day_start"] == 300
    assert SM.comm(rep, at(12, "04:00"), early)[0] == "AAA" and SM.comm(rep, at(12, "03:59"), early)[0] == "No"
    assert SM.normalize(dict(NIGHT_RAW, home_day_start="x"))["home_day_start"] == 300


def test_home_takes_the_customs_release_when_asked():
    """PWA 2.19.b: a release 30 min after block-in, not 15, when clearing customs. comm() gets block-in + 15 and,
    with customs, judges HOME from 15 min later, saying so."""
    cust = SM.normalize(dict(NIGHT_RAW, home={"AAA": ["12:00", "21:00"]}))
    assert SM.comm(at(14, "08:30"), at(14, "19:55"), cust)[0] == "AAA"  # 21:00 is exactly 65 min after
    r, why = SM.comm(at(14, "08:30"), at(14, "19:55"), cust, customs=True)
    assert r == "No" and "rel 03-14 20:10 (customs, PWA 2.19.b): AAA in 2 by 06:20, no home" in why


def test_an_unknown_origin_is_judged_both_ways_never_a_no_from_missing_data():
    """far.py's rule: a No needs the sure case to fail, a pass needs the worst case to pass. With the last leg's origin
    not on file (customs=None) HOME is judged at block-in + 15 and + 30 (PWA 2.19.b): passing only at + 15 is
    unknown, '' with the why saying so (the push keeps it critical), never 'No'."""
    cust = SM.normalize(dict(NIGHT_RAW, home={"AAA": ["12:00", "21:00"]}))
    r, why = SM.comm(at(14, "08:30"), at(14, "19:55"), cust, customs=None)
    assert r == "" and why.startswith("rpt 03-14 08:30, rel 03-14 19:55 (20:10 if customs, origin not on file, PWA "
                                      "2.19.b): AAA in 2 by 06:20, home 21:00 only if no customs")
    assert "PWA 26.QQ.2" in why and len(why) <= SM.WHY_MAX
    # the sure release fails too: a real No, data or not
    r, why = SM.comm(at(14, "08:30"), at(14, "20:05"), cust, customs=None)
    assert r == "No" and "AAA in 2 by 06:20, no home" in why and "only if" not in why
    # the worst release passes: it counts, and the why names the flight that works with customs
    assert SM.comm(at(14, "08:30"), at(14, "13:00"), cust, customs=None)[0] == "AAA"
    assert SM.comm(at(14, "08:30"), at(14, "19:40"), cust, customs=None)[0] == "AAA"  # 20:00 worst, 21:00 is 60 after
    # two airports: one counts at the worst release, the other only without customs; only the sure one is named
    two = SM.normalize(dict(RAW, home={"AAA": ["12:00", "18:00"], "BBB": ["12:00", "18:15"]}))
    r, why = SM.comm(at(12, "08:30"), at(12, "17:00"), two, customs=None)
    assert r == "BBB" and "AAA in 2 by 06:20, home 18:00 only if no customs" in why
    assert "BBB in 2 by 08:00, home 18:15" in why
    r, why = SM.comm(at(12, "08:30"), at(12, "17:05"), two, customs=None)
    assert r == "" and "AAA in 2 by 06:20, no home" in why and "BBB in 2 by 08:00, home 18:15 only if no customs" in why
    # a known foreign origin (True) and a known domestic one (False) are as before
    assert SM.comm(at(12, "08:30"), at(12, "17:00"), two, customs=True)[0] == "BBB"
    assert SM.comm(at(12, "08:30"), at(12, "17:05"), two, customs=True)[0] == "No"
    assert SM.comm(at(12, "08:30"), at(12, "17:00"), two)[0] == "AAA/BBB"


def test_multi_day_trip_report_day_in_release_day_home():
    assert SM.comm(at(12, "08:30"), at(14, "13:00"), CFG)[0] == "AAA/BBB"
    assert SM.comm("2030-03-12T08:30", "2030-03-14T13:00", CFG)[0] == "AAA/BBB"  # ISO text too


def test_one_airport_configured():
    one = SM.normalize(dict(RAW, airports=["BBB"]))
    assert SM.comm(at(12, "08:30"), at(12, "13:00"), one)[0] == "BBB"
    assert SM.comm(at(12, "07:00"), at(12, "13:00"), one)[0] == "No"
    # an airport with no table never counts
    half = SM.normalize(dict(RAW, home={"AAA": ["18:00"]}))
    r, why = SM.comm(at(12, "08:30"), at(12, "13:00"), half)
    assert r == "AAA" and "BBB no table" in why


def test_no_config_or_no_times_is_blank():
    assert SM.comm(at(12, "08:30"), at(12, "13:00"), {}) == ("", "")
    assert SM.comm(at(12, "08:30"), at(12, "13:00"), SM.normalize(dict(RAW, airports=[]))) == ("", "")
    assert SM.comm(None, at(12, "13:00"), CFG) == ("", "")
    assert SM.comm(at(12, "08:30"), None, CFG) == ("", "")
    assert SM.comm("bad", "worse", CFG) == ("", "")
    assert SM.comm(at(12, "13:00"), at(12, "08:30"), CFG) == ("", "")  # release before report


# ---------------------------------------------------------------- month rules
def _days(y, m, n, extra=3):
    return [[(date(y, m, 1) + timedelta(days=k)).isoformat(), "", ""] for k in range(n + extra)]


def months():
    """March 2030 (line): trips Mar 1-4, 6-9, 11-14, 16-19 (16 busy days), VAC Mar 20-22 in the config, credit 30:00.
    April 2030 (reserve): SCR Apr 1-4 and 7-12, VAC Apr 5-6 on the schedule, a trip Apr 14-16."""
    mar = {"month": "2030-03", "days": _days(2030, 3, 31), "totals": {"credit": "30:00"},
           "items": [{"trip": f"H900{i}", "start": f"2030-03-{a:02d}", "end": f"2030-03-{a + 3:02d}", "lay": ""}
                     for i, a in enumerate((1, 6, 11, 16), 1)]}
    apr = {"month": "2030-04", "days": _days(2030, 4, 30), "totals": {"credit": "70:00"},
           "items": [{"trip": "SCR", "start": "2030-04-01", "end": "2030-04-04"},
                     {"trip": "VAC", "start": "2030-04-05", "end": "2030-04-06"},
                     {"trip": "SCR", "start": "2030-04-07", "end": "2030-04-12"},
                     {"trip": "H9010", "start": "2030-04-14", "end": "2030-04-16"}]}
    return {"2030-03": mar, "2030-04": apr}


def D(mo, d):
    return date(2030, mo, d)


def test_line_days_off_count_vac_as_off():
    m = months()
    assert SM.days_off("2030-03", m, CFG) == 15  # 31 days, 16 on trips; the 3 VAC days count as off
    # a 4-day add leaves 11 (>= 10); counting VAC as work it would leave 8
    assert SM.month_rule(D(3, 24), D(3, 27), "10:00", "Fits", "OK", m, CFG) == "OK"
    assert SM.month_rule(D(3, 24), D(3, 29), "10:00", "Fits", "OK", m, CFG) == "Days off 9"
    assert SM.month_rule(D(3, 24), D(3, 29), "10:00", "Fits", "OK", m, SM.normalize(dict(RAW, min_days_off=None))) == "OK"


def test_line_conflict_and_rest_and_no_credit_cap():
    m = months()
    assert SM.month_rule(D(3, 24), D(3, 24), "10:00", "Fits", "OK", m, CFG) == "OK"
    # 1.7.1: no monthly credit cap (RAW's old cap_credit 40:00 is ignored): 30 + 10:01 is no fail
    assert SM.month_rule(D(3, 24), D(3, 24), "10:01", "Fits", "OK", m, CFG) == "OK"
    assert SM.month_rule(D(3, 4), D(3, 5), "5:00", "Conflict H9001", "Conflict", m, CFG) == "Conflict H9001"
    assert SM.month_rule(D(3, 24), D(3, 24), "5:00", "Fits", "OK (CBA rest 10:30)", m, CFG) == "Rest 10:30"
    # short only if the neighbour clears customs (PWA 2.19.b): possible, not certain, and it says so
    assert SM.month_rule(D(3, 24), D(3, 24), "5:00", "Fits", "OK (CBA rest 10:50?)", m, CFG) == "Rest 10:50?"
    near = SM.month_rule(D(3, 24), D(3, 24), "5:00", "Check rest H9004", "OK (CBA rest 10:50?)", m, CFG)
    assert near == "Rest 10:50?"
    assert SM.month_rule(D(3, 24), D(3, 24), "5:00", "Fits", "Rest 9:00 before", m, CFG) == "Rest 9:00 before"
    assert SM.month_rule(D(3, 24), D(3, 24), "5:00", "Check rest H9004", "?", m, CFG) == "Rest ?"  # times not on file
    assert SM.month_rule(D(3, 24), D(3, 24), "5:00", "Check rest H9004", "OK", m, CFG) == "OK"
    assert SM.month_rule(D(3, 24), D(3, 29), "12:00", "Fits", "OK", m, CFG) == "Days off 9"


def test_an_old_cap_credit_is_ignored_never_over_cap_or_cap_unknown():
    """1.7.1 (Ryan via Hark, Nov 9): the 90 h monthly credit cap was Hark's error; the PWA does not cap voluntary adds.
    A smart.json that still has cap_credit (RAW's 40:00, Pako's 90:00) is read and the key ignored: the month's credit
    on file or not, the row's credit readable or not, no 'Over cap' and no 'Cap ?' ever."""
    assert "cap_credit" not in CFG and CFG["ignored"] == ("cap_credit",)
    assert SM.normalize(dict(RAW, cap_credit=None))["ignored"] == ("cap_credit",)
    assert SM.normalize({k: v for k, v in RAW.items() if k != "cap_credit"})["ignored"] == ()
    for tot in ({"credit": "30:00"}, {"credit": "89:00"}, {"days_off": 25}, {}, {"credit": ""}):
        m = months()
        m["2030-03"]["totals"] = tot
        for credit in ("10:00", "45:00", "99:00", "x", ""):
            for cfg in (CFG, SM.normalize(dict(RAW, cap_credit="90:00")), SM.normalize(dict(RAW, cap_credit=None))):
                got = SM.month_rule(D(3, 24), D(3, 24), credit, "Fits", "OK", m, cfg)
                assert got == "OK", (tot, credit, got)
    # across a month end, where the old split by days decided the cap: nothing either
    m = _xm([], apr_credit="89:59")
    cfg = SM.normalize(dict(RAW, month_types=XCFG["month_types"], vac=[], min_days_off=None, cap_credit="90:00"))
    for credit in ("9:00", "12:00", "16:30", "40:00"):
        assert SM.month_rule(D(3, 31), D(4, 2), credit, "No sched", "OK", m, cfg) == "OK"


def test_reserve_pickups_over_scr_days_only():
    m = months()
    assert SM.month_rule(D(4, 2), D(4, 3), "10:00", "Conflict SCR", "OK", m, CFG) == "OK"  # SCR days: the point
    assert SM.month_rule(D(4, 12), D(4, 13), "10:00", "", "OK", m, CFG) == "Not SCR"  # Apr 13 is a day off
    assert SM.month_rule(D(4, 14), D(4, 14), "10:00", "", "OK", m, CFG) == "Not SCR"  # a trip day
    assert SM.month_rule(D(4, 8), D(4, 9), "99:00", "", "OK", m, CFG) == "OK"  # no cap on reserve here


def test_vac_is_never_a_pickup_day():
    m = months()
    assert SM.month_rule(D(3, 21), D(3, 21), "5:00", "Fits", "OK", m, CFG) == "VAC"  # the config's VAC, line
    assert SM.month_rule(D(4, 4), D(4, 5), "5:00", "", "OK", m, CFG).startswith("VAC")  # the schedule's VAC, reserve
    # VAC on the schedule only (not in the config) still counts
    assert SM.month_rule(D(4, 6), D(4, 6), "5:00", "", "OK", m, SM.normalize(dict(RAW, vac=[]))).startswith("VAC")


def _xm(apr_items, apr_credit="60:00"):
    """Synthetic March, April and May 2030 with no next-month rows (a month that ends clean): March trip H9001 Mar 2-5
    (credit 30:00), April as given, May SCR May 5-10 only."""
    def mo(mk, n, items, credit):
        return {"month": mk, "days": _days(int(mk[:4]), int(mk[5:]), n, extra=0), "totals": {"credit": credit},
                "items": items}
    return {"2030-03": mo("2030-03", 31, [{"trip": "H9001", "start": "2030-03-02", "end": "2030-03-05"}], "30:00"),
            "2030-04": mo("2030-04", 30, apr_items, apr_credit),
            "2030-05": mo("2030-05", 31, [{"trip": "SCR", "start": "2030-05-05", "end": "2030-05-10"}], "0:00")}


XCFG = SM.normalize(dict(RAW, month_types={"2030-03": "line", "2030-04": "line", "2030-05": "reserve"}, vac=[],
                         min_days_off=12, cap_credit="90:00"))
# April with exactly 12 days off: trips Apr 3-8, 10-15 and 17-22
APR12 = [{"trip": t, "start": f"2030-04-{a:02d}", "end": f"2030-04-{a + 5:02d}"}
         for t, a in (("H9003", 3), ("H9004", 10), ("H9005", 17))]


def test_a_trip_across_a_month_end_is_judged_in_both_months():
    """The fit tag cannot cover a trip across a month end (each schedule month covers its own days), so the Watcher
    tags it 'No sched'; month_rule reads both months from the schedule, each by its own type."""
    m = _xm([{"trip": "H9002", "start": "2030-04-01", "end": "2030-04-05"}])
    assert P.fit_tag(D(3, 31), D(4, 2), m["2030-03"]) == P.fit_tag(D(3, 31), D(4, 2), m["2030-04"]) == ""
    assert SM.month_rule(D(3, 31), D(4, 2), "15:00", "No sched", "Conflict", m, XCFG) == "Conflict H9002"
    assert SM.month_rule(D(4, 2), D(4, 3), "15:00", "Conflict H9002", "Conflict", m, XCFG) == "Conflict H9002"
    # the second month's days off, at the minimum before the add
    m = _xm(APR12)
    assert SM.days_off("2030-04", m, XCFG) == 12
    assert SM.days_off("2030-04", m, XCFG, add={D(4, 1), D(4, 2)}) == 10
    assert SM.month_rule(D(3, 31), D(4, 2), "15:00", "No sched", "OK", m, XCFG) == "Days off 10"
    # a line April into a reserve May: May's days must be SCR days
    assert SM.month_rule(D(4, 30), D(5, 2), "15:00", "No sched", "OK", m, XCFG) == "Days off 11, Not SCR"
    assert SM.month_rule(D(5, 1), D(5, 2), "15:00", "", "OK", m, XCFG) == "Not SCR"
    # 1.7.1: no credit cap per month any more (the old split by days, 'Cap ?' and 'Over cap', are gone)
    m = _xm([], apr_credit="80:00")
    nomin = SM.normalize(dict(RAW, month_types=XCFG["month_types"], vac=[], min_days_off=None, cap_credit="90:00"))
    for credit in ("9:00", "12:00", "16:30"):
        assert SM.month_rule(D(3, 31), D(4, 2), credit, "No sched", "OK", m, nomin) == "OK"
    # a month with no type next to a typed one: a trip there is still a conflict
    m = _xm([{"trip": "H9002", "start": "2030-04-01", "end": "2030-04-05"}])
    marl = SM.normalize(dict(RAW, month_types={"2030-03": "line"}, vac=[], min_days_off=None, cap_credit=None))
    assert SM.month_rule(D(3, 31), D(4, 2), "15:00", "No sched", "OK", m, marl) == "Conflict H9002"
    # next month not on file: its days cannot be checked, never OK; the checks that can run still do
    only = {"2030-03": m["2030-03"]}
    assert SM.month_rule(D(3, 30), D(4, 1), "15:00", "No sched", "OK", only, marl) == "No sched"
    assert SM.month_rule(D(3, 30), D(4, 1), "15:00", "No sched", "OK", only, XCFG) == "No sched"
    assert SM.month_rule(D(3, 4), D(4, 1), "15:00", "No sched", "OK", only, marl) == "Conflict H9001, No sched"
    # the rest next to a trip across the month end, its times not on file yet
    m = _xm([{"trip": "H9002", "start": "2030-04-03", "end": "2030-04-05"}])
    assert SM.month_rule(D(3, 31), D(4, 2), "5:00", "No sched", "?", m, marl) == "Rest ?"
    assert SM.month_rule(D(3, 30), D(3, 31), "5:00", "No sched", "?", m, marl) == "OK"


def test_the_rule_is_cut_between_parts():
    # 1.7.1: RULE_MAX 80 keeps the rest with the longest 672 tag in place of 'Over cap'
    assert SM._join(["VAC", "Conflict H9002", "Days off 10", "Over 98/672 (101:30)", "Rest 10:50?", "No sched"]) == \
        "VAC, Conflict H9002, Days off 10, Over 98/672 (101:30), Rest 10:50?, No sched"
    assert SM._join(["VAC", "Conflict H9002", "Days off 10", "Over 98/672 (101:30)", "Rest 10:50?", "No sched",
                     "Not SCR"]) == "VAC, Conflict H9002, Days off 10, Over 98/672 (101:30), Rest 10:50?, No sched"
    assert len(SM._join(["x" * 90])) == SM.RULE_MAX and SM._join([]) == ""


def test_month_type_and_unknowns():
    m = months()
    assert SM.month_type("2030-03", CFG) == "line" and SM.month_type(D(4, 9), CFG) == "reserve"
    assert SM.month_type("2030-05", CFG) == "" and SM.month_type("2030-03", {}) == ""
    assert SM.month_rule(D(5, 10), D(5, 11), "5:00", "", "OK", m, CFG) == ""  # no month type
    # April's page lists May 2 and 3 with nothing on them: days of April's bid period, judged as April (reserve)
    assert SM.month_rule(D(5, 2), D(5, 3), "5:00", "", "OK", m, CFG) == "Not SCR"
    assert SM.month_rule(D(3, 24), D(3, 24), "5:00", "", "OK", {}, CFG) == "No sched"
    assert SM.month_rule(None, None, "5:00", "", "OK", m, CFG) == ""
    assert SM.month_rule(D(3, 24), D(3, 24), "5:00", "", "OK", m, {}) == ""


def test_vac_in_a_month_with_no_type_is_still_vac():
    """VAC days are never pickup days, whatever the month's type: a VAC range in smart.json for a month with no type
    yet (the seed lists a December VAC with no December type) reads 'VAC', not blank."""
    m = months()
    cfg = SM.normalize(dict(RAW, vac=[["2030-05-20", "2030-05-22"]]))
    assert SM.month_type("2030-05", cfg) == ""
    assert SM.month_rule(D(5, 21), D(5, 21), "5:00", "", "OK", m, cfg) == "VAC"
    assert SM.month_rule(D(5, 19), D(5, 20), "5:00", "", "OK", m, cfg) == "VAC"
    assert SM.month_rule(D(5, 25), D(5, 25), "5:00", "", "OK", m, cfg) == ""  # no VAC, no type: unknown as before
    # a typed month is unchanged: VAC plus the month's own checks
    assert SM.month_rule(D(3, 21), D(3, 21), "5:00", "Fits", "OK", m, cfg) == "OK"  # the config's VAC moved to May
    assert SM.month_rule(D(5, 21), D(5, 21), "5:00", "", "OK", {}, cfg) == "VAC"  # no schedule on file at all


def _page(month_label, rows, days_off):
    """A synthetic mobile schedule page (pot.parse_schedule's input): rows of (day number, activity, layover)."""
    dow = ("SU", "MO", "TU", "WE", "TH", "FR", "SA")
    body = "".join(f"<tr><td>{dow[i % 7]}</td><td>{dd:02d}</td><td>{a}</td><td>{lay}</td></tr>"
                   for i, (dd, a, lay) in enumerate(rows))
    return (f"<html><body><div>{month_label} Schedule</div><table>{body}</table>"
            f"<p>Block 60.00</p><p>Credit 60:00</p><p>Days Off {days_off}</p></body></html>")


def _three_day_trips(first, last, trip):
    """Rows for days first..last with 3-day trips back to back (a trip starts on every third day, home on the third)."""
    return [(dd, trip if (dd - first) % 3 == 0 else "-", "AAA" if (dd - first) % 3 == 0 else
             ("HNL" if (dd - first) % 3 == 2 else "-")) for dd in range(first, last + 1)]


def bid_periods():
    """November 2030's bid period runs Nov 1 to Dec 1 (pdfs.py: 'November 1 - December 1 (31 Days)'), December's
    Dec 2 to 31. November: trips Nov 1 to 18, off Nov 19 to Dec 1 (13, FLICA's Days Off). December: trips Dec 2 to 19,
    off Dec 20 to 31 (12). Both through the real page parser, which keeps November's Dec 1 row."""
    nov = P.parse_schedule(_page("Nov 2030", _three_day_trips(1, 18, "H9001") + [(dd, "-", "-") for dd in range(19, 31)]
                                 + [(1, "-", "-")], 13))
    dec = P.parse_schedule(_page("Dec 2030", _three_day_trips(2, 19, "H9002")
                                 + [(dd, "-", "-") for dd in range(20, 32)], 12))
    assert (nov["days"][0][0], nov["days"][-1][0], dec["days"][0][0]) == ("2030-11-01", "2030-12-01", "2030-12-02")
    return {nov["month"]: nov, dec["month"]: dec}


BP = SM.normalize({"v": 1, "month_types": {"2030-11": "line", "2030-12": "line"}, "min_days_off": 12})


def test_month_rules_follow_the_bid_period_not_the_calendar_month():
    """FLICA's Days Off counts the bid period, and so does the rule: a Nov 25 pickup leaves November 12 (OK, as the fit
    tag says), a Dec 25 pickup leaves December 11 (a real fail the calendar month missed)."""
    m = bid_periods()
    assert SM.days_off("2030-11", m, BP) == 13 and SM.days_off("2030-12", m, BP) == 12
    for d, mk, want in ((D(11, 25), "2030-11", "OK"), (D(12, 25), "2030-12", "Days off 11")):
        fit = P.fit_tag(d, d, m[mk])
        assert fit == ("Fits" if want == "OK" else want)
        assert SM.month_rule(d, d, "6:00", fit, "OK", m, BP) == want, d
    # without FLICA's total the page's own bid period days are recounted, Dec 1 in November's
    for s in m.values():
        s["totals"].pop("days_off")
    assert SM.days_off("2030-11", m, BP) == 13 and SM.days_off("2030-12", m, BP) == 12
    assert SM.days_off("2030-11", m, BP, add={D(12, 1)}) == 12 and SM.days_off("2030-12", m, BP, add={D(12, 1)}) == 12
    assert SM.month_rule(D(12, 25), D(12, 25), "6:00", "Fits", "OK", m, BP) == "Days off 11"


def test_a_bid_period_boundary_day_is_judged_by_its_own_bid_month():
    """Dec 1, 2030 is a November day (its page lists it, off): November's type, schedule and days off judge it, not
    December's, and not '' because December has no type yet."""
    m = bid_periods()
    seed = SM.normalize({"v": 1, "month_types": {"2030-10": "reserve", "2030-11": "line"}, "min_days_off": 13})
    d = D(12, 1)
    assert SM.bid_month(m)(d) == "2030-11" and SM.bid_month(m)(D(12, 2)) == "2030-12"
    assert SM.month_rule(d, d, "6:00", "Fits", "OK", {"2030-11": m["2030-11"]}, seed) == "Days off 12"
    dec_res = SM.normalize({"v": 1, "month_types": {"2030-11": "line", "2030-12": "reserve"}, "min_days_off": 12})
    assert SM.month_rule(d, d, "6:00", "Fits", "OK", {"2030-11": m["2030-11"]}, dec_res) == "OK"  # not 'No sched'
    assert SM.month_rule(d, d, "6:00", "Fits", "OK", m, dec_res) == "OK"  # not 'Not SCR'
    assert SM.month_rule(D(12, 2), D(12, 2), "6:00", "", "OK", m, dec_res) == "Not SCR"  # December's own day
    # the pairing files' bounds (period=) decide when the caller has them; None leaves it to the pages
    files = {"2030-11": (D(11, 1), D(12, 1)), "2030-12": (D(12, 2), D(12, 31))}
    per = lambda day: next((k for k, (a, b) in files.items() if a <= day <= b), None)  # noqa: E731
    assert SM.month_rule(d, d, "6:00", "Fits", "OK", {}, dec_res, period=per) == "No sched"  # November, not on file
    assert SM.month_rule(d, d, "6:00", "Fits", "OK", m, dec_res, period=per) == "OK"
    assert SM.month_rule(d, d, "6:00", "Fits", "OK", m, dec_res, period=lambda day: None) == "OK"
    assert SM.month_rule(d, d, "6:00", "Fits", "OK", m, dec_res, period=lambda day: "2030-12") == "No sched"
    assert SM.month_rule(d, d, "6:00", "Fits", "OK", m, dec_res, period=lambda day: 1 / 0) == "OK"  # never raises


def test_a_carried_trip_day_goes_to_the_next_bid_month_once_its_page_is_on_file():
    """November's page lists Dec 2 only for a trip carried past its end (H9003 Nov 30 to Dec 2): December's page owns
    Dec 2; with December's page not on file it is still a day holding a trip, a Conflict either way."""
    m = bid_periods()
    nov = m["2030-11"]
    nov["days"] = [d for d in nov["days"] if d[0] < "2030-11-30"] + [["2030-11-30", "H9003", "AAA"],
                                                                     ["2030-12-01", "", "-"], ["2030-12-02", "", "HNL"]]
    nov["items"] = P.schedule_items(nov["days"])
    assert nov["items"][-1] == {"trip": "H9003", "start": "2030-11-30", "end": "2030-12-02", "lay": "AAA"}
    bid = SM.bid_month(m)
    assert (bid(D(12, 1)), bid(D(12, 2))) == ("2030-11", "2030-12")  # a trip day of November's page, December's own
    assert SM.bid_month({"2030-11": nov})(D(12, 2)) == "2030-11"  # the only page that lists it
    assert SM.month_rule(D(12, 2), D(12, 2), "6:00", "", "OK", {"2030-11": nov}, BP) == "Conflict H9003"


def _line_april(codes):
    days = [[f"2030-04-{d:02d}", codes.get(d, ""), ""] for d in range(1, 31)]
    return {"2030-04": {"month": "2030-04", "days": days, "totals": {"credit": "30:00"},
                        "items": P.schedule_items(days)}}


def test_an_off_code_in_the_fit_tag_is_not_a_conflict_on_a_line():
    """The fit tag names any item, a day off code too ('Conflict GDO'); a line is free to add on a day off (OFF, GDO
    or smart.json off_codes), as duty() and days_off() already read them. A trip on another day of the pickup, which
    the fit tag's first hit hides, is still a Conflict."""
    m = _line_april({10: "GDO", 11: "H9001", 20: "OFF", 25: "XYZ"})
    cfg = SM.normalize(dict(RAW, month_types={"2030-04": "line"}, vac=[], min_days_off=10, cap_credit="90:00"))
    for d, code in ((10, "GDO"), (20, "OFF")):
        fit = P.fit_tag(D(4, d), D(4, d), m["2030-04"])
        assert fit == f"Conflict {code}"
        assert SM.month_rule(D(4, d), D(4, d), "10:00", fit, "OK", m, cfg) == "OK", code
    assert SM.days_off("2030-04", m, cfg) == 28  # GDO and OFF count as off; the trip day and XYZ do not
    fit = P.fit_tag(D(4, 10), D(4, 11), m["2030-04"])
    assert fit == "Conflict GDO" and SM.month_rule(D(4, 10), D(4, 11), "10:00", fit, "OK", m, cfg) == "Conflict H9001"
    # a code the pilot lists as off, and one he does not
    assert SM.month_rule(D(4, 25), D(4, 25), "10:00", "Conflict XYZ", "OK", m, cfg) == "Conflict XYZ"
    own = SM.normalize(dict(RAW, month_types={"2030-04": "line"}, vac=[], min_days_off=10, cap_credit="90:00",
                            off_codes=["OFF", "GDO", "XYZ"]))
    assert SM.month_rule(D(4, 25), D(4, 25), "10:00", "Conflict XYZ", "OK", m, own) == "OK"
    assert SM.days_off("2030-04", m, own) == 29
    # a real trip in the fit tag is a Conflict as before
    assert SM.month_rule(D(4, 11), D(4, 11), "10:00", "Conflict H9001", "OK", m, cfg) == "Conflict H9001"


# ---------------------------------------------------------------- value
def test_value_is_credit_times_rate():
    assert SM.value("15:00", CFG) == 1500 and SM.value("15:30", CFG) == 1550 and SM.value("7.45", CFG) == 775
    assert SM.value("6:10", CFG) == 617
    assert SM.value("", CFG) == "" and SM.value("x", CFG) == "" and SM.value("15:00", {}) == ""
    assert SM.value("15:00", SM.normalize(dict(RAW, rate=None))) == ""
    assert SM.normalize(dict(RAW, rate="$1,234.50"))["rate"] == 1234.5


# ---------------------------------------------------------------- the file
def test_loader_never_raises_and_reloads_on_change(tmp_path):
    p = str(tmp_path / "smart.json")
    warned = []
    assert SM.load(p, warned.append) == {} and warned == []  # no file: nothing to say
    open(p, "w").write("{not json")
    assert SM.load(p, warned.append) == {} and len(warned) == 1 and "not json" not in warned[0]
    assert SM.load(p, warned.append) == {} and len(warned) == 1  # cached: said once
    open(p, "w").write(json.dumps(dict(RAW, v=2)) + " ")  # a different size from RAW's (the loader needs none)
    assert SM.load(p, warned.append) == {} and len(warned) == 2  # another format version
    open(p, "w").write(json.dumps(RAW))
    cfg = SM.load(p, warned.append)
    assert cfg["airports"] == ["AAA", "BBB"] and cfg["rate"] == 100.0 and len(warned) == 3
    assert warned[2].startswith("smart.json cap_credit ignored: no monthly credit cap")  # 1.7.1: RAW's old cap
    assert SM.load(p, warned.append) == cfg and len(warned) == 3  # cached: said once
    open(p, "w").write(json.dumps(dict(RAW, rate=200.0, source="synthetic two")))
    assert SM.load(p)["rate"] == 200.0
    for bad in ("[]", "null", '{"v": 1, "airports": 7, "in": [], "home": "x", "vac": 3, "month_types": []}'):
        open(p, "w").write(bad + " " * len(bad))  # a different size, so the cache sees the change
        cfg = SM.load(p)
        assert SM.comm(at(12, "08:30"), at(12, "13:00"), cfg) == ("", "")
        assert SM.month_rule(D(3, 24), D(3, 24), "5:00", "", "OK", months(), cfg) == ""


def test_loader_sees_a_same_size_rewrite_in_one_clock_tick(tmp_path):
    """A kernel with a coarse file clock (before Linux 6.13: 1 to 4 ms) gives a rewrite inside one tick the same
    mtime; with the same size a time and size key would keep the old config. The loader compares the contents."""
    p = tmp_path / "smart.json"
    a, b = json.dumps(dict(RAW, rate=100.0)), json.dumps(dict(RAW, rate=200.0))
    assert len(a) == len(b)
    p.write_text(a)
    st = os.stat(p)
    assert SM.load(str(p))["rate"] == 100.0
    p.write_text(b)
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns))  # the same file time, as one coarse tick gives it
    assert (os.stat(p).st_mtime_ns, os.stat(p).st_size) == (st.st_mtime_ns, st.st_size)
    assert SM.load(str(p))["rate"] == 200.0
    warned = []
    p.write_text(json.dumps(dict(RAW, source="x" * (SM.MAX_BYTES + 1))))
    assert SM.load(str(p), warned.append) == {} and "too large" in warned[0]
    assert SM.load(str(tmp_path)) == {}  # a folder, not a file


def test_normalize_drops_what_does_not_parse():
    cfg = SM.normalize(dict(RAW, airports=["aaa", "AAA", "bbbb", 7, "BBB"],
                            **{"in": {"AAA": {"dep": ["25:00", "x", "05:00", "05:30"], "block_max": 50},
                                      "BBB": {"dep": ["05:10"], "block_max": "long"}}},
                            month_types={"2030-03": "Line", "2030-4": "reserve", "2030-05": "other"},
                            vac=[["2030-03-22", "2030-03-20"], "2030-03-25", ["x", "y"]]))
    assert cfg["airports"] == ["AAA", "BBB"] and cfg["in"]["AAA"]["dep"] == [300, 330] and "BBB" not in cfg["in"]
    assert cfg["month_types"] == {"2030-03": "line"} and cfg["vac"] == [(D(3, 25), D(3, 25))]
    assert SM.normalize([]) == {} and SM.normalize({"v": "1"}) == {}


def test_nothing_personal_ships_in_the_module_or_the_card():
    """The home airports, the nonstop tables, the month types, VAC dates, the rate and the break-even live only in
    smart.json: the module has no defaults for them, and neither it nor the card names an airport but HNL and the
    made-up ones, a calendar date outside the made-up 2030, or a dollar rate."""
    import re
    cfg = SM.normalize({"v": 1})
    assert (cfg["airports"], cfg["in"], cfg["home"], cfg["month_types"], cfg["vac"]) == ([], {}, {}, {}, [])
    assert cfg["rate"] is cfg["breakeven"] is cfg["min_days_off"] is None and "cap_credit" not in cfg
    words = {"HNL", "AAA", "BBB", "HST", "DST", "UTC", "ISO", "PWA", "FAR", "CBA", "SCR", "VAC", "OFF", "GDO", "MON"}
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for f in ("smart.py", "www/flight-watcher-finds-card.js"):
        src = open(os.path.join(here, f), encoding="utf-8").read()
        assert set(re.findall(r"\b[A-Z]{3}\b", src)) <= words, f
        assert all(d.startswith("2030") for d in re.findall(r"\b20\d\d-\d\d-\d\d", src)), f
        assert not re.findall(r"\b\d{3}\.\d{2}\b", src), f
        assert chr(0x2014) not in src


# ---------------------------------------------------------------- the Watcher
def _w(tmp_path, monkeypatch, smart=RAW):
    monkeypatch.setenv("FLIGHT_WATCHER_DATA", str(tmp_path))
    monkeypatch.delenv("FLIGHT_WATCHER_INSTANCE", raising=False)
    monkeypatch.delenv("FLIGHT_WATCHER_PREFIX", raising=False)
    (tmp_path / "options.json").write_text(json.dumps({"username": "u", "password": "p"}))
    sys.modules.pop("watcher", None)
    import watcher as W
    from store import Store
    W.S.clear()
    monkeypatch.setattr(W, "DB", Store(str(tmp_path / "t.db")))
    monkeypatch.setattr(W, "local_now", lambda: datetime(2030, 3, 2, 9, 0))
    monkeypatch.setattr(W, "row_date", lambda s, today=None: P.row_date(s, date(2030, 3, 2)))
    monkeypatch.setattr(W, "SMART_FILE", str(tmp_path / "smart.json"))
    monkeypatch.setattr(W, "CARD_PAIRINGS", str(tmp_path / "www"))  # no pairing files unless a test writes them
    if smart is not None:
        (tmp_path / "smart.json").write_text(smart if isinstance(smart, str) else json.dumps(smart))
    W.S["schedule"] = months()
    sent = []
    monkeypatch.setattr(W, "pub", lambda t, p, retain=True: sent.append((t, p)))
    return W, sent


ROW = {"pairing": "H9101", "start": "24Mar", "end": "24Mar", "days": "1", "credit": "6:00", "depart": "09:30",
       "arrive": "13:00", "dates": "24Mar"}


def test_report_and_release_from_the_best_on_file(tmp_path, monkeypatch):
    W, _ = _w(tmp_path, monkeypatch)
    rr = W.report_release
    # the pairing page's check-in and the pot row's final arrival, + 15 min (PWA 2.19.b)
    assert rr(dict(ROW, report="08:30")) == (at(24, "08:30"), at(24, "13:15"))
    # no check-in: 1:00 before the pot row's first departure
    assert rr(dict(ROW)) == (at(24, "08:30"), at(24, "13:15"))
    # duty periods (details cache) when the row has neither time: first departure - 1:00, last block-in + 0:15
    W.S["details"] = {"H9101|24Mar": {"duties": [{"d": 0, "dep": 600, "arr": 900, "stn": "HNL", "blk": 300}]}}
    assert rr(dict(ROW, depart="", arrive="")) == (at(24, "09:00"), at(24, "15:15"))
    # a 3-day trip home on the last day; a block-in after midnight rolls to the next day
    assert rr(dict(ROW, start="12Mar", end="14Mar", report="08:30", arrive="13:00")) == (at(12, "08:30"), at(14, "13:15"))
    assert rr(dict(ROW, report="22:00", arrive="01:00")) == (at(24, "22:00"), at(25, "01:15"))
    W.S["details"] = {}
    assert rr(dict(ROW, depart="", arrive="")) == (None, None)
    # the bid period's pairings package: its report (BASE REPT) and its duty periods
    W.DB.put("pkg_details:2030-03", {"H9101": {"report": "07:45", "rel_days": 0,
                                               "duties": [{"d": 0, "dep": 525, "arr": 840, "stn": "HNL", "blk": 315}]}})
    assert rr(dict(ROW, depart="", arrive="")) == (at(24, "07:45"), at(24, "14:15"))
    assert rr(dict(ROW, report="08:30", arrive="13:00")) == (at(24, "08:30"), at(24, "13:15"))  # the row's own first
    assert rr(dict(ROW, start="", dates="")) == (None, None)


def _cache(W, k, report="08:30"):
    W.S.setdefault("details", {})[k] = {"crew": [], "duties": [], "report": report, "captain": "Doe, Jane (10001)"}


def test_pot_rows_carry_the_fields_the_sensor_does_not(tmp_path, monkeypatch):
    """The pot row (the finds DB and files read it) carries the fields; sensor.flight_watcher_pot_count does not (no
    card reads them there yet, and they would cost rows under the 12 KB cap)."""
    W, sent = _w(tmp_path, monkeypatch)
    _cache(W, "H9101|24Mar")
    pot = {"H9101|24Mar": dict(ROW)}
    W.pot_details(None, pot)  # cached: no page load
    row = pot["H9101|24Mar"]
    assert row["comm"] == "AAA/BBB" and "PWA 26.QQ.2" in row["comm_why"]
    # 1.7.1: months()'s own trips have no times or blocks on file, so the 672 h block check says so (never guessed)
    assert row["value"] == 600 and row["month_rule"] == "672 ? (block not read)" and row["fit"] and row["far"]
    assert (row["b672"], row["b672_ok"]) == ("", "")
    W.publish_pot([dict(row, month="2030-03")])
    s = [p for t, p in sent if t == "pot/state"][-1]["pairings"][0]
    assert not set(W.SMART_FIELDS) & set(s) and "far_why" not in s and s["far"] == row["far"]
    # a trip over VAC, a late release, too few days off: the rule and the commute say so
    late = {"H9102|21Mar": dict(ROW, pairing="H9102", start="21Mar", end="21Mar", arrive="17:30")}
    _cache(W, "H9102|21Mar")
    W.pot_details(None, late)
    assert late["H9102|21Mar"]["comm"] == "No" and late["H9102|21Mar"]["month_rule"] == "VAC, 672 ? (block not read)"


def test_the_tradeboard_sensor_rows_stay_as_they_were(tmp_path, monkeypatch):
    """A Tradeboard post's enriched row (event/new_pairing, the details cache) carries the fields; the
    tradeboard/state sensor rows do not, as on pot/state."""
    W, sent = _w(tmp_path, monkeypatch)
    post = dict(ROW, pairing="H9103", report="08:30", source="tradeboard", poster="Doe, Jane")
    W.smart_fields(post)  # as enrich() leaves it in tb_details
    assert (post["comm"], post["value"], post["month_rule"]) == ("AAA/BBB", 600, "672 ? (block not read)")
    W.publish_tradeboard({"000000001|H9103": post})
    r = [p for t, p in sent if t == "tradeboard/state"][-1]["pairings"][0]
    assert not set(W.SMART_FIELDS) & set(r) and "far_why" not in r and r["fit"] and r["far"]


def test_a_release_after_midnight_reads_no_end_to_end(tmp_path, monkeypatch):
    """A 2-day trip whose last block-in is late on the end day: the release report_release rolls past midnight
    gives no same-day home, the same as one just before midnight."""
    W, _ = _w(tmp_path, monkeypatch, smart=NIGHT_RAW)
    row = dict(ROW, pairing="H9104", start="12Mar", end="13Mar", days="2", report="08:30", route="HNL-LAX-HNL")
    got = {}
    for arr in ("13:00", "21:30", "23:40", "23:50", "00:30"):
        r = dict(row, arrive=arr)
        W.smart_fields(r)
        got[arr] = (r["comm"], r["comm_why"])
    assert W.report_release(dict(row, arrive="23:50"))[1] == at(14, "00:05")
    assert got["13:00"][0] == "AAA" and "rel 03-13 13:15:" in got["13:00"][1]
    assert [got[a][0] for a in ("21:30", "23:40", "23:50", "00:30")] == ["No"] * 4
    assert all("overnight release" in got[a][1] for a in ("23:40", "23:50", "00:30"))


def test_home_takes_the_customs_release_unless_the_last_leg_is_domestic(tmp_path, monkeypatch):
    """Block-in 19:40, the last flight home 21:00, 60 min: a US last leg releases 19:55 and makes it; a foreign one
    releases 20:10 (PWA 2.19.b, customs) and does not. One not on file is judged both ways (far.py's sure / worst
    rule): making it only without customs is unknown, a blank comm (critical push), never a No from missing data."""
    raw = dict(NIGHT_RAW, home={"AAA": ["12:00", "21:00"]})
    W, _ = _w(tmp_path, monkeypatch, smart=raw)
    row = dict(ROW, pairing="H9105", start="12Mar", end="14Mar", days="3", report="08:30", arrive="19:40")
    dom = dict(row, route="HNL-LAX-HNL")
    W.smart_fields(dom)
    assert dom["comm"] == "AAA" and "rel 03-14 19:55: AAA in 2 by 06:20, home 21:00" in dom["comm_why"]
    assert "customs" not in dom["comm_why"]
    foreign = dict(row, route="HNL-ZZZ-HNL")
    W.smart_fields(foreign)
    assert foreign["comm"] == "No"
    assert "rel 03-14 20:10 (customs, PWA 2.19.b): AAA in 2 by 06:20, no home" in foreign["comm_why"]
    assert (W.release_customs(dom), W.release_customs(foreign), W.release_customs(dict(row))) == (False, True, None)
    unknown = dict(row)  # no route on the row and no package for the period
    W.smart_fields(unknown)
    assert unknown["comm"] == ""
    assert ("rel 03-14 19:55 (20:10 if customs, origin not on file, PWA 2.19.b): AAA in 2 by 06:20, home 21:00 only "
            "if no customs") in unknown["comm_why"]
    late = dict(row, arrive="19:50")  # the sure release (20:05) misses 21:00 too: a No, route or not
    W.smart_fields(late)
    assert late["comm"] == "No" and "AAA in 2 by 06:20, no home" in late["comm_why"]
    via = dict(row, route="HNL-ZZZ-LAX-HNL")  # customs cleared on the mainland: the last leg is domestic
    assert W.last_origin(via) == "LAX" and not W.release_customs(via)
    # the bid period's pairings package gives the route when the row has none
    W.DB.put("pkg_details:2030-03", {"H9105": {"report": "08:30", "rel_days": 2, "route": "HNL-SEA-HNL", "duties": []}})
    assert W.last_origin(dict(row)) == "SEA"
    pkg = dict(row)
    W.smart_fields(pkg)
    assert pkg["comm"] == "AAA"
    # the pilot's smart.json can add a US station the Watcher does not list
    (tmp_path / "smart.json").write_text(json.dumps(dict(raw, domestic=["zzz", "nope"])))
    r = dict(row, route="HNL-ZZZ-HNL")
    W.smart_fields(r)
    assert r["comm"] == "AAA" and SM.normalize(dict(raw, domestic=["zzz", "nope"]))["domestic"] == ("ZZZ",)


def test_the_watcher_reads_the_bid_period_off_the_pairing_files(tmp_path, monkeypatch):
    """smart_fields passes month_rule the pairing files' period bounds (crewidx.period_for, as the crew index and the
    cards use them): Dec 1 is November's when November's file says its period runs to Dec 1, whatever the pages
    show; with no pairing file for a month the bounds say nothing (None) and the pages decide."""
    raw = dict(RAW, month_types={"2030-11": "line", "2030-12": "reserve"}, vac=[], min_days_off=12, cap_credit=None)
    W, _ = _w(tmp_path, monkeypatch, smart=raw)
    www = tmp_path / "www"
    www.mkdir()
    for mk, a, b in (("2030-11", "2030-11-01", "2030-12-01"), ("2030-12", "2030-12-02", "2030-12-31")):
        (www / f"pairings_{mk}.json").write_text(json.dumps({"month": mk, "start": a, "end": b, "cols": ["id", "days"],
                                                             "rows": []}))
    assert [W.bid_period_of(D(*md)) for md in ((11, 30), (12, 1), (12, 2), (12, 31))] == \
        ["2030-11", "2030-11", "2030-12", "2030-12"]
    assert W.bid_period_of(D(3, 5)) is None  # no pairing file for March 2030: the pages and the calendar decide
    W.S["schedule"] = bid_periods()
    monkeypatch.setattr(W, "row_date", lambda s, today=None: P.row_date(s, date(2030, 11, 2)))
    row = dict(ROW, pairing="H9106", start="01Dec", end="01Dec", dates="01Dec", report="08:30")
    row["fit"] = W.schedule_fit(row)
    W.smart_fields(row)
    # November's line day off, not December's 'Not SCR' (the 672 tag: the trips' blocks are not on file)
    assert row["fit"] == "Fits" and row["month_rule"] == "672 ? (block not read)"
    # December's own day, by the same bounds
    row = dict(ROW, pairing="H9107", start="25Dec", end="25Dec", dates="25Dec", report="08:30", fit="Fits")
    W.smart_fields(row)
    assert row["month_rule"] == "Not SCR, 672 ? (block not read)"
    # the files win over the pages: a December file that starts Dec 1 makes Dec 1 December's (its page lacks it)
    (www / "pairings_2030-12.json").write_text(json.dumps({"month": "2030-12", "start": "2030-12-01",
                                                          "end": "2030-12-31", "cols": ["id", "days"], "rows": []}))
    W.BID_PERIODS["at"] = 0  # the 10 min cache, as a later pass sees the new file
    assert W.bid_period_of(D(12, 1)) == "2030-12"
    row = dict(ROW, pairing="H9106", start="01Dec", end="01Dec", dates="01Dec", report="08:30", fit="Fits")
    W.smart_fields(row)
    assert row["month_rule"] == "672 ? (block not read), No sched"


def test_a_find_on_a_vac_day_of_a_month_with_no_type_reads_vac(tmp_path, monkeypatch):
    W, _ = _w(tmp_path, monkeypatch, smart=dict(RAW, vac=[["2030-05-20", "2030-05-22"]]))
    row = dict(ROW, pairing="H9108", start="21May", end="21May", dates="21May", report="08:30")
    W.smart_fields(row)
    assert row["month_rule"] == "VAC"


def test_the_finds_sensor_carries_none_of_the_smart_fields(tmp_path, monkeypatch):
    """The DB, the finds month files, last_new and event/new_pairing carry the four fields; the finds sensor (like
    the pot and Tradeboard sensors) carries FINDS_ATTR_KEYS only. The docs say so; this keeps them in step."""
    W, _ = _w(tmp_path, monkeypatch)
    row = {"pairing": "H9001", "comm": "AAA", "comm_why": "x", "value": 123, "month_rule": "OK", "far": "OK"}
    f = W.finds_payload([row], "k")["finds"][0]
    assert f["pairing"] == "H9001" and not set(W.SMART_FIELDS) & set(f) and set(f) <= set(W.FINDS_ATTR_KEYS)
    assert not set(W.SMART_FIELDS) & set(W.sensor_row(row))


def test_enrich_sets_the_fields_for_the_push(tmp_path, monkeypatch):
    """event/new_pairing is the enriched row: it carries comm, comm_why, value and month_rule (the push can use them)."""
    W, _ = _w(tmp_path, monkeypatch)
    page = "<html><body>Check In: 08:30 Blk : 0400 Pay : 0600 Crew: CA 10001 DOE, JANE FO OPEN</body></html>"

    class Fl:
        def fetch(self, url):
            return page
    ev = dict(ROW)
    W.enrich(Fl(), ev)
    assert ev["report"] == "8:30" and ev["comm"] == "AAA/BBB" and ev["value"] == 600 and ev["month_rule"] == "672 ? (block not read)"
    assert "PWA 26.QQ.2" in ev["comm_why"]


def test_without_smart_json_nothing_changes(tmp_path, monkeypatch):
    W, sent = _w(tmp_path, monkeypatch, smart=None)
    _cache(W, "H9101|24Mar")
    pot = {"H9101|24Mar": dict(ROW)}
    W.pot_details(None, pot)
    row = pot["H9101|24Mar"]
    assert all(row[k] == "" for k in W.SMART_FIELDS)
    before = {k: v for k, v in row.items() if k not in W.SMART_FIELDS and k != "far_why"}
    W.publish_pot([row])
    W.publish_tradeboard({"000000001|H9103": dict(ROW, pairing="H9103", report="08:30")})
    pot_s = [p for t, p in sent if t == "pot/state"][-1]["pairings"][0]
    tb_s = [p for t, p in sent if t == "tradeboard/state"][-1]["pairings"][0]
    assert pot_s == before  # the sensor row is what it was before 1.4.13
    assert not set(W.SMART_FIELDS) & set(tb_s)


@pytest.mark.parametrize("bad", ["{not json", "[1, 2]", '{"v": 1, "airports": ["AAA"], "in": {"AAA": 5}}', ""])
def test_a_malformed_smart_json_never_raises(tmp_path, monkeypatch, bad):
    W, sent = _w(tmp_path, monkeypatch, smart=bad)
    _cache(W, "H9101|24Mar")
    pot = {"H9101|24Mar": dict(ROW)}
    W.pot_details(None, pot)
    assert pot["H9101|24Mar"]["comm"] == "" and pot["H9101|24Mar"]["far"]


def test_smart_file_is_per_pilot(tmp_path, monkeypatch):
    monkeypatch.setenv("FLIGHT_WATCHER_DATA", str(tmp_path))
    (tmp_path / "options.json").write_text(json.dumps({"username": "u", "password": "p"}))
    monkeypatch.setenv("FLIGHT_WATCHER_INSTANCE", "pilot2")
    monkeypatch.setenv("FLIGHT_WATCHER_PREFIX", "flight_watcher_pilot2")
    sys.modules.pop("watcher", None)
    import watcher as W
    assert W.SMART_FILE == "/share/flight_watcher/pilot2/smart.json" == f"{W.SHARE}/smart.json"
    monkeypatch.delenv("FLIGHT_WATCHER_INSTANCE")
    monkeypatch.delenv("FLIGHT_WATCHER_PREFIX")
    sys.modules.pop("watcher", None)
    import watcher as W2
    assert W2.SMART_FILE == "/share/flight_watcher/smart.json"


# ---------------------------------------------------------------- check(): the push, the finds, the sensor
def _check_env(tmp_path, monkeypatch, smart):
    from test_close_in import _checks, _pot_page, _w as ci_w
    W, fl, pages, fetched, framed, waits, events = ci_w(tmp_path, monkeypatch)
    _checks(W, monkeypatch)
    monkeypatch.setattr(W, "local_now", lambda: datetime(2026, 11, 2, 9, 0))
    monkeypatch.setattr(W, "row_date", lambda s, today=None: P.row_date(s, date(2026, 11, 2)))
    monkeypatch.setattr(W, "SMART_FILE", str(tmp_path / "smart.json"))
    if smart is not None:
        (tmp_path / "smart.json").write_text(smart if isinstance(smart, str) else json.dumps(smart))
    pages["003.152"] = _pot_page([("H9201", "07Nov")])
    assert W.check(fl) == "ok"  # baseline
    pages["003.152"] = _pot_page([("H9201", "07Nov"), ("H9202", "07Nov")])
    assert W.check(fl) == "ok"
    pot = [json.loads(p) for tp, p, _ in W.MQ.msgs if tp == "flight_watcher/pot/state"][-1]["pairings"]
    return W, events("new_pairing"), pot


def test_check_pushes_and_records_the_fields(tmp_path, monkeypatch):
    """A new pot trip Nov 7, check-in 08:00 (its pairing page), final block-in 15:00: AAA has 05:50 and 06:20 in
    before report and 18:00 home 60+ min after the release (15:15, or 15:30 with customs: no route on file, so both
    are judged, PWA 2.19.b, and 18:00 works with either); BBB only 06:00 in (08:00 is not before 08:00)."""
    W, ev, pot = _check_env(tmp_path, monkeypatch, RAW)
    assert [e["pairing"] for e in ev] == ["H9202"]
    e = ev[0]
    assert (e["comm"], e["value"], e["month_rule"]) == ("AAA", 617, "672 ? (block not read), No sched")
    assert e["fit"] and e["far"] and (e["b672"], e["b672_ok"]) == ("", "")
    assert "PWA 26.QQ.2" in e["comm_why"]
    assert ("rel 11-07 15:15 (15:30 if customs, origin not on file, PWA 2.19.b): AAA in 2 by 06:20, home 18:00"
            in e["comm_why"])
    row = next(r for r in pot if r["pairing"] == "H9202")
    assert not set(W.SMART_FIELDS) & set(row) and row["fit"]  # off the pot sensor
    find = next(f for f in W.DB.recent_finds() if f["pairing"] == "H9202")
    assert (find["comm"], find["value"], find["month_rule"]) == ("AAA", 617, "672 ? (block not read), No sched")
    assert find["comm_why"] and (find["b672"], find["b672_ok"]) == ("", "")


def test_check_without_smart_json_pushes_blank_fields(tmp_path, monkeypatch):
    W, ev, pot = _check_env(tmp_path, monkeypatch, None)
    assert all(ev[0][k] == "" for k in W.SMART_FIELDS)
    assert all(not set(W.SMART_FIELDS) & set(r) for r in pot)
    find = next(f for f in W.DB.recent_finds() if f["pairing"] == "H9202")
    assert all(find[k] == "" for k in W.SMART_FIELDS)


def test_check_with_a_malformed_smart_json_runs(tmp_path, monkeypatch):
    W, ev, pot = _check_env(tmp_path, monkeypatch, '{"v": 1, "airports": ["AAA"], "in": {"AAA": {"dep": 7}}, "rate": []')
    assert [e["pairing"] for e in ev] == ["H9202"] and ev[0]["comm"] == ""


# ---------------------------------------------------------------- sensor sizes
def test_the_pot_and_tradeboard_sensors_keep_their_rows(tmp_path, monkeypatch):
    """With smart.json the pot and Tradeboard sensors publish exactly what they do without it: a busy month keeps
    as many rows under cap_attrs' 12 KB (the fields are on the rows, the finds files and event/new_pairing)."""
    from test_sensor_size import HA_OWN, LIMIT, _attr_topics, _fill, _load, _pot_row
    W, fake = _load(tmp_path, monkeypatch)
    monkeypatch.setattr(W, "SMART_FILE", str(tmp_path / "smart.json"))
    mk = f"{W.row_date('12Nov'):%Y-%m}"  # the bid month of the busy month's rows, a line month here
    (tmp_path / "smart.json").write_text(json.dumps(dict(RAW, month_types={mk: "line"})))
    got = _fill(W, fake, tmp_path, monkeypatch)
    for t in _attr_topics(W):
        assert len(json.dumps(got[t], separators=(",", ":"))) + HA_OWN <= LIMIT, t

    def publish(smart):
        if smart:
            (tmp_path / "smart.json").write_text(json.dumps(dict(RAW, month_types={mk: "line"})))
        elif os.path.exists(tmp_path / "smart.json"):
            os.remove(tmp_path / "smart.json")
        rows = [_pot_row(i) for i in range(60)]
        tb = {f"{i:09d}|H3{i:03d}": _pot_row(i, src=True) for i in range(40)}
        for r in rows + list(tb.values()):
            W.smart_fields(r)  # as pot_details() and enrich() leave them
        W.publish_pot(rows)
        W.publish_tradeboard(tb)
        last = {t: p for t, p, _ in fake.msgs}
        return rows, {t: last[f"flight_watcher/{t}"] for t in ("pot/state", "tradeboard/state")}

    rows, plain = publish(False)
    assert all(r[k] == "" for r in rows for k in W.SMART_FIELDS)
    rows, smart = publish(True)
    assert rows[0]["comm"] == "AAA/BBB" and rows[0]["value"] == 1500
    assert rows[0]["month_rule"].startswith("Conflict H3681") and len(rows[0]["month_rule"]) <= SM.RULE_MAX
    assert len(rows[0]["comm_why"]) <= SM.WHY_MAX
    assert smart == plain  # byte for byte
    for t, p in smart.items():
        d = json.loads(p)
        assert d["trimmed"] > 0 and len(d["pairings"]) < d["count"], t  # busy: the cap is what decides the rows
        assert not set(W.SMART_FIELDS) & set(d["pairings"][0]), t
        assert len(json.dumps(d, separators=(",", ":"))) + HA_OWN <= LIMIT, t


# ---------------------------------------------------------------- the finds card
def test_finds_card_shows_comm_and_value(tmp_path):
    from test_cards import _finds_card_node
    rows = [{"pairing": "H9301", "seen": "2026-11-07T09:00:00Z", "dates": "08Nov", "credit": "15:00", "value": 1500,
             "comm": "AAA/BBB", "comm_why": "rpt 11-08 08:30 <x>", "month_rule": "OK"},
            {"pairing": "H9302", "seen": "2026-11-07T08:00:00Z", "dates": "08Nov", "credit": "6:10", "value": 617,
             "comm": "No", "comm_why": "AAA in 1 by 05:50 (needs 2)", "month_rule": "Days off 9"},
            {"pairing": "H9303", "seen": "2026-11-07T07:00:00Z", "dates": "08Nov", "credit": "6:10", "value": "",
             "comm": "", "comm_why": "", "month_rule": ""},
            {"pairing": "H9304", "seen": "2026-11-07T06:00:00Z", "dates": "08Nov", "credit": "6:10"},
            {"pairing": "H9305", "seen": "2026-11-07T05:00:00Z", "dates": "08Nov", "credit": "6:10", "value": 617,
             "comm": "", "comm_why": "AAA in 2 by 06:20, home 21:00 only if no customs", "month_rule": "OK"}]
    js = (f"const rows = {json.dumps(rows)};\n"
          "const c = new FlightWatcherFindsCard(); c.setConfig({}); c._m = '2026-11';\n"
          "const cells = (h) => [...h.matchAll(/<td[^>]*>(.*?)<\\/td>/g)].map((m) => m[1]);\n"
          "const out = rows.map((f) => { const t = cells(c._row(f)); return [t[7], t[8]]; });\n"
          "const html = c._list(rows, Date.parse('2026-11-07T09:30:00Z'), false);\n"
          "const head = (html.match(/<tr><th>.*?<\\/tr>/) || [''])[0];\n"
          "console.log(JSON.stringify({out, ths: (head.match(/<th/g) || []).length, head,\n"
          "  colspan: (html.match(/colspan=\"(\\d+)\"/) || [])[1] || null}));")
    r = _finds_card_node(tmp_path, js)
    (v1, c1), (v2, c2), (v3, c3), (v4, c4), (v5, c5) = r["out"]
    assert v1 == "$1,500" and 'class="cm ok"' in c1 and ">AAA/BBB<" in c1
    assert "rpt 11-08 08:30 &lt;x&gt; | Month: OK" in c1  # the why on hover, escaped
    assert v2 == "$617" and 'class="cm no"' in c2 and "Month: Days off 9" in c2
    assert (v3, c3, v4, c4) == ("", "", "", "")  # blank without smart.json (or a find from before 1.4.13)
    # unknown (only a customs release, origin not on file, decides it): '?', neither green nor red, the why on hover
    assert v5 == "$617" and '<span class="cm" title=' in c5 and ">?<" in c5 and "only if no customs" in c5
    assert r["ths"] == 14 and ">Value</th>" in r["head"] and ">Comm</th>" in r["head"]
    assert r["head"].index(">Credit<") < r["head"].index(">Value<") < r["head"].index(">Comm<") < r["head"].index(">CA<")
