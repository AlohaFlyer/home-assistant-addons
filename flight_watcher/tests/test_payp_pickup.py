"""1.7.2 (Ryan, Nov 13: "make way for the fact that I can also pick up a trip over the top of PAYP for additional
pay"): open time over PAYP days. PWA 4.R.1: "Should a pilot elect to Add a Flight Grouping on a PAYP day(s), the pay
shall be: a. Pay and Credit of the PAYP Day, and b. Pay and Credit of the added Flight Grouping". On Pako (Nov 13)
H3607 Nov 13 to 15 and H3839 Nov 13 to 14 over PAYP Nov 12 to 14 were tagged "Conflict PAYP" and their FAR column
said "may overlap PAYP Nov 12: PAYP Nov 12 times not on file". Now a PAYP day is free for a pickup in the fit tag, the
month rules and the FAR line; FLICA counts PAYP days in Days Off (13 to 15 on Pako), so a pickup on them uses days off
as on any. The Recall / Over 75 miss check still counts a PAYP as possible duty (unchanged). Synthetic trips only."""
import json
import sys
from datetime import date, datetime, timedelta

import far as F
import pot as P
import recall as RC
import smart as SM

RAW = {"v": 1, "updated": "2030-01-01", "source": "synthetic", "airports": ["AAA"],
       "in": {"AAA": {"dep": ["05:00", "05:30"], "block_max": 50}}, "home": {"AAA": ["12:00", "18:00"]},
       "month_types": {"2030-11": "line"}, "vac": [], "rate": 100.0, "min_days_off": 10}
CFG = SM.normalize(RAW)


def _nov(days_off=15, extra=()):
    """November 2030 (30 days): H9681 Nov 8 to 11, PAYP Nov 12 to 14 (a removed trip), H9620 Nov 16 to 18."""
    codes = {d: "H9681" for d in range(8, 12)}
    codes.update({d: "PAYP" for d in (12, 13, 14)})
    codes.update({16: "H9620", 17: "", 18: ""})
    days = [[f"2030-11-{d:02d}", codes.get(d, ""), ""] for d in range(1, 31)]
    items = [{"trip": "H9681", "start": "2030-11-08", "end": "2030-11-11", "lay": "BBB"},
             {"trip": "PAYP", "start": "2030-11-12", "end": "2030-11-14", "lay": ""},
             {"trip": "H9620", "start": "2030-11-16", "end": "2030-11-18", "lay": "CCC"}] + list(extra)
    return {"month": "2030-11", "days": days, "items": items,
            "totals": {"days_off": days_off, "block": "60:00", "credit": "131:15"}}


def D(d):
    return date(2030, 11, d)


def test_fit_tag_a_pickup_on_payp_days_fits():
    s = _nov()
    assert P.fit_tag(D(13), D(14), s) == "Fits"  # was 'Conflict PAYP'
    assert P.fit_tag(D(12), D(14), s) == "Check rest H9681"  # the day after a trip: rest, as on any day
    assert P.fit_tag(D(15), D(15), s) == "Check rest H9620"  # a PAYP day is no rest neighbour, the trip after is
    assert P.fit_tag(D(13), D(16), s) == "Conflict H9620"  # into the next trip
    assert P.fit_tag(D(11), D(11), s) == "Conflict H9681"


def test_fit_tag_payp_days_are_days_off_as_flica_counts_them():
    """FLICA's Days Off holds the PAYP days (Pako: 13 before, 15 with PAYP Nov 12 to 14): a pickup on them uses them
    like any day off (10.G: 12 in a 30-day month)."""
    assert P.fit_tag(D(13), D(14), _nov(days_off=13)) == "Days off 11"
    assert P.fit_tag(D(13), D(14), _nov(days_off=14)) == "Fits"


def test_fit_tag_a_trip_added_on_a_payp_day_is_still_a_conflict():
    """PWA 4.R.1: a trip already added on PAYP Nov 14 holds that day."""
    s = _nov(extra=[{"trip": "H9700", "start": "2030-11-14", "end": "2030-11-14", "lay": ""}])
    assert P.fit_tag(D(13), D(13), s) == "Check rest H9700"  # the day before the added trip
    assert P.fit_tag(D(13), D(14), s) == "Conflict H9700"


def test_month_rule_payp_days_are_free_on_a_line():
    m = {"2030-11": _nov()}
    assert SM.month_rule(D(13), D(14), "10:00", "Fits", "OK", m, CFG) == "OK"
    # a row tagged before 1.7.2 ('Conflict PAYP') is no Conflict either
    assert SM.month_rule(D(13), D(14), "10:00", "Conflict PAYP", "OK", m, CFG) == "OK"
    assert SM.month_rule(D(13), D(16), "10:00", "Conflict H9620", "OK", m, CFG) == "Conflict H9620"
    # smart.json off_codes leaves PAYP out: still free (PWA 4.R.1 does not depend on the pilot's list)
    own = SM.normalize(dict(RAW, off_codes=["OFF"]))
    assert SM.month_rule(D(13), D(14), "10:00", "Fits", "OK", m, own) == "OK"


def test_month_rule_days_off_counts_payp_days_as_off():
    m = {"2030-11": _nov(days_off=15)}
    assert SM.days_off("2030-11", m, CFG) == 15
    assert SM.days_off("2030-11", m, CFG, add=[D(13), D(14)]) == 13  # the PAYP days are used
    tight = SM.normalize(dict(RAW, min_days_off=14))
    assert SM.month_rule(D(13), D(14), "10:00", "Fits", "OK", m, tight) == "Days off 13"
    # with no FLICA total, the recount counts PAYP days as off: 30 days less 4 + 3 trip days = 23
    nt = _nov()
    nt["totals"] = {}
    assert SM.days_off("2030-11", {"2030-11": nt}, CFG) == 23


def test_month_rule_a_trip_added_on_a_payp_day_is_a_conflict():
    m = {"2030-11": _nov(extra=[{"trip": "H9700", "start": "2030-11-14", "end": "2030-11-14", "lay": ""}])}
    assert SM.month_rule(D(14), D(14), "10:00", "Fits", "OK", m, CFG) == "Conflict H9700"


def _months():
    oct_ = {"month": "2030-10", "days": [[f"2030-10-{d:02d}", "", ""] for d in range(1, 32)], "items": [],
            "totals": {}}
    dec = {"month": "2030-12", "days": [[f"2030-12-{d:02d}", "", ""] for d in range(1, 32)], "items": [],
           "totals": {}}
    nov = _nov()
    nov["items"] = [it for it in nov["items"] if it["trip"] == "PAYP"]  # only the PAYP: nothing else to screen
    return {"2030-10": oct_, "2030-11": nov, "2030-12": dec}


def test_far_line_leaves_payp_out_the_miss_check_keeps_it():
    months = _months()
    mine = RC.line_records(months, {}, D(13), D(14), D(1))
    assert not any("PAYP" in t["label"] for t in mine)
    new = RC.pickup_trip("H9001", D(13), D(14), "08:00", "14:00", 5.0, [])
    assert F.screen(new, mine)["far"] == "OK"
    # the Recall / Over 75 miss check reads own_records: a PAYP is still whole days of possible duty there
    kept = RC.own_records(months["2030-11"]["items"], {})
    assert [t["label"] for t in kept] == ["PAYP Nov 12"]
    r = F.screen(new, kept)
    assert r["far"] != "OK" and "PAYP" in r["why"]


# ---------------------------------------------------------------- the Watcher's pot row
def _w(tmp_path, monkeypatch):
    monkeypatch.setenv("FLIGHT_WATCHER_DATA", str(tmp_path))
    monkeypatch.delenv("FLIGHT_WATCHER_INSTANCE", raising=False)
    (tmp_path / "options.json").write_text(json.dumps({"username": "u", "password": "p"}))
    sys.modules.pop("watcher", None)
    import watcher as W
    from store import Store
    W.S.clear()
    monkeypatch.setattr(W, "DB", Store(str(tmp_path / "t.db")))
    monkeypatch.setattr(W, "local_now", lambda: datetime(2030, 11, 2, 9, 0))
    monkeypatch.setattr(W, "row_date", lambda s, today=None: P.row_date(s, date(2030, 11, 2)))
    return W


def test_watcher_pot_row_over_payp_fits_and_screens(tmp_path, monkeypatch):
    W = _w(tmp_path, monkeypatch)
    W.S["schedule"] = _months()
    W.S["own_trips"] = {}
    row = {"pairing": "H9001", "start": "13Nov", "end": "14Nov", "days": "2", "report": "08:00", "arrive": "14:00",
           "blk": "5:00"}
    assert W.schedule_fit(row) == "Fits"
    assert W.far_for(row) == "OK" and "PAYP" not in row["far_why"]
