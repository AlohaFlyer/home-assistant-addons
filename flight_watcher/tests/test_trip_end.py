"""Trip end fix (Nov 7, no ticket filed): from version 11.009 the schedule item of a 4-day SYD trip (Nov 9 to 12)
read Nov 9 to Nov 9, because another trip started on Nov 12, the day it came home: FLICA's mobile schedule then shows only the new trip's row on that
day, so there was no 'HNL' layover cell to end the first trip on. Made-up trips (H39xx)."""
import json

import pot
import versions as VER
from test_trades import BASE, W, _html  # noqa: F401  (W: the watcher fixture)


def _ends(s):
    return {(i["trip"], i["start"]): i["end"] for i in s["items"]}


def test_trip_home_the_day_the_next_starts_keeps_its_last_day():
    before = pot.parse_schedule(_html(BASE, "Nov 6, 2026 12:04:46"))
    assert _ends(before)[("H3981", "2026-11-09")] == "2026-11-12"  # 'HNL' on Nov 12: always fine
    after = pot.parse_schedule(_html({**BASE, 12: ("H3920", "LAS", 3)}, "Nov 6, 2026 14:01:09"))
    e = _ends(after)
    assert after["days"][11] == ["2026-11-12", "H3920", "LAS"]  # no HNL cell for H3981 any more
    assert e[("H3981", "2026-11-09")] == "2026-11-12"  # was 2026-11-09 before the fix
    assert e[("H3920", "2026-11-12")] == "2026-11-14" and e[("H3920", "2026-11-06")] == "2026-11-08"
    assert e[("H3915", "2026-11-01")] == "2026-11-04" and e[("H3907", "2026-11-30")] == "2026-12-02"
    assert e[("VAC", "2026-11-22")] == "2026-11-28"


def test_rows_that_never_mean_away_do_not_stretch_a_trip():
    """'-' is written on days off too: only a trip whose first layover is a station (not domicile, not '-' or empty)
    is away; an empty layover cell (a day off) ends that; two rows on one date still work."""
    days = [["2026-11-01", "H3901", ""], ["2026-11-02", "", "-"], ["2026-11-03", "SCR", ""],     # a turn: no layover
            ["2026-11-05", "H3902", "LAX"], ["2026-11-06", "", ""], ["2026-11-07", "GDO", ""],    # an empty cell: home
            ["2026-11-10", "SCR", ""], ["2026-11-10", "H3903", "JFK"], ["2026-11-11", "", "-"],   # SCR then a trip
            ["2026-11-12", "", "HNL"], ["2026-11-12", "H3904", "SEA"], ["2026-11-13", "", "HNL"]]  # home, out again
    e = {(i["trip"], i["start"]): i["end"] for i in pot.schedule_items(days)}
    assert e[("H3901", "2026-11-01")] == "2026-11-01" and e[("H3902", "2026-11-05")] == "2026-11-05"
    assert e[("H3903", "2026-11-10")] == "2026-11-12" and e[("H3904", "2026-11-12")] == "2026-11-13"
    assert e[("SCR", "2026-11-10")] == "2026-11-10"


def test_stored_versions_repaired_once_and_no_new_version_for_it(W):  # noqa: F811
    """Versions stored with the cut-short end get the end their own days give (the PBS award is left alone); the
    repaired fingerprint is the one a fresh read makes, so the fixed parser makes no new version; a later real change
    says which trip's end moved."""
    good = pot.parse_schedule(_html({**BASE, 12: ("H3920", "LAS", 3)}, "Nov 6, 2026 14:01:09"))
    bad = json.loads(json.dumps(good))
    next(i for i in bad["items"] if i["trip"] == "H3981")["end"] = "2026-11-09"  # as 11.009 stored it
    award = {"ver": "11.001", "award": True, "items": [{"trip": "H3981", "start": "2026-11-09", "end": "2026-11-09"}],
             "days": [], "trips": {}, "at": "2026-10-12T12:00:00+00:00"}
    VER.update(W.DB, {"2026-11": {**bad, "days": bad["days"]}}, {}, "2026-11-07T00:13:43+00:00")
    vers = W.DB.get("sched_versions:2026-11")
    W.DB.put("sched_versions:2026-11", [award] + vers)
    W.S["schedule"] = {"2026-11": json.loads(json.dumps(bad))}
    W.S.pop("ends_fix_v", None)
    assert W.repair_trip_ends() == 2  # the stored FLICA version and the schedule on file
    vers = W.DB.get("sched_versions:2026-11")
    assert vers[0]["items"][0]["end"] == "2026-11-09" and "repaired" not in vers[0]  # the award: untouched
    assert _ends(vers[1])[("H3981", "2026-11-09")] == "2026-11-12" and vers[1]["repaired"] == "trip-end-1.4.7"
    assert _ends(W.S["schedule"]["2026-11"])[("H3981", "2026-11-09")] == "2026-11-12"
    assert "repaired" not in W.S["schedule"]["2026-11"]
    assert W.repair_trip_ends() == 0  # once
    assert VER.update(W.DB, {"2026-11": good}, {}, "2026-11-07T01:00:00+00:00") == []  # the fixed read is no new version
    old = {"items": [{"trip": "H3981", "start": "2026-11-09", "end": "2026-11-09"}]}
    assert VER.diff(old, {"items": [{"trip": "H3981", "start": "2026-11-09", "end": "2026-11-12"}]}) == [
        "H3981 2026-11-09 ends 2026-11-12 (was 2026-11-09)"]
