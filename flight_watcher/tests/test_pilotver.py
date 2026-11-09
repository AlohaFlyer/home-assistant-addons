"""FW-0069 (1.4.11): other pilots' schedule versions, M.NNN per bid month (pilotver.py). Pure logic and the DB side on a
real Store: numbering, the award as .001 (seeded or late, renumbered), what makes a version (pairings only), the
rebuild merge against a lookup (no flip-flop; a later crew read that drops the pilot does), the caps, the registry and
the list file's content. Made-up pilots ("Doe, Jane", 10001) and made-up pairings only."""
import json
import os
import shutil
import subprocess

import pytest

import pdfs
import pilotver as PV
import versions as VER
from store import Store
from test_pdfs import AWARD, PKG

WIN = ("2026-10-31", "2026-12-01")  # November's grid: the day before the bid period to its last day
T0, T1, T2, T3 = ("2026-11-05T20:00:00+00:00", "2026-11-06T20:00:00+00:00", "2026-11-07T20:00:00+00:00",
                  "2026-11-08T20:00:00+00:00")


@pytest.fixture
def db(tmp_path):
    return Store(str(tmp_path / "t.db"))


def _it(trip, start, end=None, lay="LAX", **kw):
    return {"trip": trip, "start": start, "end": end or start, "lay": lay, **kw}


def _days(items, first="2026-10-31", last="2026-12-01", extra=None):
    """FLICA's rows for the items: the code and layover on the first day, '-' away, HNL home; extra {iso: code}."""
    at = {}
    for i in items:
        at[i["start"]] = [i["trip"], i.get("lay") or ""]
    for iso, code in (extra or {}).items():
        at[iso] = [code, ""]
    out, d = [], first
    while d <= last:
        out.append([d, *(at.get(d) or ["", ""])])
        d = PV._add(d, 1)
    return out


def _sched(items, month="2026-11", updated="Nov 5, 2026 10:00", totals=None, extra=None):
    return {"month": month, "updated": updated, "items": items, "days": _days(items, extra=extra),
            "totals": totals or {"block": "40:00", "credit": "60:00", "days_off": 15}}


def _trip(pairing, start, end, checked_at="2026-11-07T08:00:00", seat="FO", route="HNL-LAX-HNL", lay="LAX"):
    """One crewidx.pilot_trips entry (checked_at: the crew index's HST wall clock)."""
    return {"pairing": pairing, "start": start, "end": end, "seat": seat, "route": route, "checked_at": checked_at,
            "lay": lay, "blk": "10:00", "credit": "12:00", "soft": "2:00", "crew": [["FO", "Doe, Jane"]], "period": start[:7],
            "n": 3, "overlap": "", "overlap_with": ""}


def _row(pairing, date_, emps, checked_at, status="ok"):
    """One store.crew_rows entry."""
    return {"key": f"{pairing}|{date_}", "pairing": pairing, "date": date_, "end_date": date_, "route": "HNL-LAX-HNL",
            "crew": [{"pos": "CA", "name": "Roe, Rick", "emp": "10002"}] + [{"pos": "FO", "name": "Doe, Jane", "emp": e} for e in emps],
            "checked_at": checked_at, "status": status, "reason": "", "tries": 0}


A = _it("H3101", "2026-11-03", "2026-11-05", "LAX")
B = _it("H3205", "2026-11-12", "2026-11-14", "SFO")
C = _it("H3300", "2026-11-20", "2026-11-22", "NRT")


def _vers(db, month="2026-11", emp="10001"):
    return PV.versions_of(db, emp, month)


# ---------------------------------------------------------------- numbering and what makes a version
def test_numbering_like_ryans_versions(db):
    assert PV.ver_label("2026-11", 3) == "11.003" and PV.ver_label("2027-01", 1) == "1.001"
    assert PV.capture_lookup(db, "10001", "Doe, Jane", _sched([A, B]), T0, WIN) == ["11.001"]
    assert PV.capture_lookup(db, "10001", "Doe, Jane", _sched([A, B, C]), T1, WIN) == ["11.002"]
    assert PV.capture_lookup(db, "10001", "Doe, Jane", _sched([A, C]), T2, WIN) == ["11.003"]
    v = _vers(db)
    assert [(x["ver"], x["n"], x["source"], x["at"]) for x in v] == [
        ("11.001", 1, "lookup", T0), ("11.002", 2, "lookup", T1), ("11.003", 3, "lookup", T2)]
    assert v[0]["changes"] == ["first version on file (FLICA schedule)"]
    assert v[1]["changes"] == ["added H3300 Nov 20-22 NRT"] and v[2]["changes"] == ["removed H3205 Nov 12-14 SFO"]
    assert v[0]["updated"] == "Nov 5, 2026 10:00" and v[0]["totals"] == {"block": "40:00", "credit": "60:00", "days_off": 15}
    assert v[0]["days"] == _sched([A, B])["days"] and [i["trip"] for i in v[0]["items"]] == ["H3101", "H3205"]
    assert json.loads(v[0]["fp"]) == [["H3101", "2026-11-03"], ["H3205", "2026-11-12"]]


def test_only_pairings_make_a_version(db):
    """Seat, crew, read times, block / credit, FLICA's totals and Last Updated, the end date, a reserve or VAC day, the
    source: none of these is a new version."""
    PV.capture_lookup(db, "10001", "Doe, Jane", _sched([A, B]), T0, WIN)
    changed = [
        _sched([dict(A, seat="CA", crew=[["CA", "Doe, Jane"]], blk="9:00", credit="11:00", read=T1), B]),
        _sched([A, B], updated="Nov 6, 2026 09:00", totals={"block": "41:00", "credit": "61:00", "days_off": 12}),
        _sched([dict(A, end="2026-11-06"), dict(B, end="2026-11-12")]),  # sources compute the end differently
        _sched([A, B, _it("VAC", "2026-11-24", "2026-11-28", ""), _it("SCR", "2026-11-17", "2026-11-17", "")],
               extra={"2026-11-17": "SCR", "2026-11-24": "VAC"}),
        _sched([dict(A, trip="h3101"), B]),  # the id's case
    ]
    for k, s in enumerate(changed):
        assert PV.capture_lookup(db, "10001", "Doe, Jane", s, f"2026-11-0{6 + k % 3}T0{k}:00:00+00:00", WIN) == [], k
    assert PV.capture_rebuild(db, "10001", "Doe, Jane", "2026-11",
                              [_trip("H3101", "2026-11-03", "2026-11-05", seat="RO"), _trip("H3205", "2026-11-12", "2026-11-14")],
                              {}, T3, WIN, "2026-11-01", "2026-12-01") == []
    assert [v["ver"] for v in _vers(db)] == ["11.001"]


def test_a_pairing_added_removed_or_swapped_is_a_version(db):
    PV.capture_lookup(db, "10001", "Doe, Jane", _sched([A, B]), T0, WIN)
    assert PV.capture_lookup(db, "10001", "", _sched([A, B, C]), T1, WIN) == ["11.002"]
    # FW-0068: the package's H3205 rebuilt as H3205B the same day is a swap
    assert PV.capture_lookup(db, "10001", "", _sched([A, dict(B, trip="H3205B"), C]), T2, WIN) == ["11.003"]
    assert PV.capture_lookup(db, "10001", "", _sched([A, dict(B, trip="H3205B", start="2026-11-13", end="2026-11-15"), C]), T3, WIN) == ["11.004"]
    v = _vers(db)
    assert v[2]["changes"] == ["removed H3205 Nov 12-14 SFO", "added H3205B Nov 12-14 SFO"]
    assert v[3]["changes"] == ["removed H3205B Nov 12-14 SFO", "added H3205B Nov 13-15 SFO"]


def test_pairings_off_the_grid_do_not_count(db):
    """Only pairings that start on the card's grid for the month count (the edges of FLICA's page and of the crew index
    differ); they are still kept in the version for the days drawn."""
    PV.capture_lookup(db, "10001", "", _sched([A]), T0, WIN)
    edge = _it("H3900", "2026-12-02", "2026-12-04", "SYD")
    assert PV.capture_lookup(db, "10001", "", _sched([A, edge]), T1, WIN) == []
    assert PV.capture_lookup(db, "10001", "", _sched([A, dict(edge, start="2026-12-01")]), T2, WIN) == ["11.002"]


def test_diff_lines_and_spans():
    assert PV.span("2026-11-06", "2026-11-06") == "Nov 6" and PV.span("2026-11-06", "2026-11-08") == "Nov 6-8"
    assert PV.span("2026-11-30", "2026-12-02") == "Nov 30-Dec 2"
    old = {"items": [_it("H3631", "2026-11-06", "2026-11-06", "")]}
    new = {"items": [_it("H3631B", "2026-11-06", "2026-11-08", "LAX"), _it("H3700", "2026-11-20", "2026-11-20", "HNL")]}
    assert PV.diff(old, new) == ["removed H3631 Nov 6", "added H3631B Nov 6-8 LAX", "added H3700 Nov 20"]
    assert PV.diff(None, {"source": "rebuild"}) == ["first version on file (rebuilt from crew lists)"]
    assert PV.diff(None, {"source": "award"}) == ["first version on file (awarded line)"]
    assert PV.diff(old, old) == ["no pairing change"]
    assert not any("\u2014" in x for x in PV.FIRST_SAYS.values())


# ---------------------------------------------------------------- lookups and rebuilds
def test_lookup_and_rebuild_with_the_same_pairings_never_flip_flop(db):
    PV.capture_lookup(db, "10001", "Doe, Jane", _sched([A, B]), T0, WIN)
    rb = [_trip("H3101", "2026-11-03", "2026-11-05"), _trip("H3205", "2026-11-12", "2026-11-14")]
    for t in (T1, T2):
        assert PV.capture_rebuild(db, "10001", "", "2026-11", rb, {}, t, WIN, "2026-11-01", "2026-12-01") == []
        assert PV.capture_lookup(db, "10001", "", _sched([A, B]), t, WIN) == []
    assert [v["ver"] for v in _vers(db)] == ["11.001"]
    # the other way round: a rebuild first, then a lookup of the same pairings
    assert PV.capture_rebuild(db, "10002", "Roe, Rick", "2026-11", rb, {}, T0, WIN, "2026-11-01", "2026-12-01") == ["11.001"]
    assert PV.capture_lookup(db, "10002", "", _sched([A, B]), T1, WIN) == []
    v = _vers(db, emp="10002")
    assert v[0]["source"] == "rebuild" and v[0]["changes"] == ["first version on file (rebuilt from crew lists)"]
    assert v[0]["totals"] == {} and v[0]["updated"] == ""
    assert [(i["trip"], i["lay"], i.get("seat")) for i in v[0]["items"]] == [("H3101", "LAX", "FO"), ("H3205", "LAX", "FO")]
    assert "read" not in v[0]["items"][0]


def test_partial_rebuild_keeps_the_lookups_trips(db):
    """R3: the crew index read only some of the pilot's trips; the lookup's others are carried (items from the lookup),
    so nothing changes. A trip the index adds is a version that keeps the rest."""
    PV.capture_lookup(db, "10001", "Doe, Jane", _sched([A, B, C]), T0, WIN)
    assert PV.capture_rebuild(db, "10001", "", "2026-11", [_trip("H3101", "2026-11-03", "2026-11-05")], {}, T1, WIN,
                              "2026-11-01", "2026-12-01") == []
    new = _trip("H3400", "2026-11-26", "2026-11-27", checked_at="2026-11-06T12:00:00", route="HNL-SEA-HNL", lay="")
    rows = {"H3205|2026-11-12": _row("H3205", "2026-11-12", ["10001"], "2026-11-06T12:00:00")}  # still on it
    assert PV.capture_rebuild(db, "10001", "", "2026-11", [_trip("H3101", "2026-11-03", "2026-11-05"), new], rows, T2,
                              WIN, "2026-11-01", "2026-12-01") == ["11.002"]
    v = _vers(db)[-1]
    assert v["source"] == "rebuild" and [i["trip"] for i in v["items"]] == ["H3101", "H3205", "H3300", "H3400"]
    assert v["items"][0] == {"trip": "H3101", "start": "2026-11-03", "end": "2026-11-05", "lay": "LAX"}  # the lookup's
    assert v["items"][3]["lay"] == "SEA" and v["changes"] == ["added H3400 Nov 26-27 SEA"]
    assert ["2026-11-26", "H3400", "SEA"] in v["days"] and ["2026-11-27", "", "HNL"] in v["days"]
    assert ["2026-11-12", "H3205", "SFO"] in v["days"] and v["days"][0][0] == "2026-10-31" and v["days"][-1][0] == "2026-12-01"


def test_a_later_crew_read_without_the_pilot_drops_the_trip(db):
    """R3: a lookup's trip goes only when the crew index read that same trip and date after the lookup and the pilot
    is not on its crew line. A read from before the lookup, or one that still names him, keeps it."""
    PV.capture_lookup(db, "10001", "Doe, Jane", _sched([A, B, C]), T0, WIN)  # T0 = Nov 5 20:00 UTC = 10:00 HST
    rb = [_trip("H3101", "2026-11-03", "2026-11-05")]
    before = {"H3205|2026-11-12": _row("H3205", "2026-11-12", ["10009"], "2026-11-05T09:00:00")}  # 09:00 HST, before
    assert PV.capture_rebuild(db, "10001", "", "2026-11", rb, before, T1, WIN, "2026-11-01", "2026-12-01") == []
    other_day = {"H3205|2026-11-13": _row("H3205", "2026-11-13", ["10009"], "2026-11-06T09:00:00")}
    assert PV.capture_rebuild(db, "10001", "", "2026-11", rb, other_day, T1, WIN, "2026-11-01", "2026-12-01") == []
    failed = {"H3205|2026-11-12": _row("H3205", "2026-11-12", [], "2026-11-06T09:00:00", status="fail")}
    assert PV.capture_rebuild(db, "10001", "", "2026-11", rb, failed, T1, WIN, "2026-11-01", "2026-12-01") == []
    after = {"H3205|2026-11-12": _row("H3205", "2026-11-12", ["10009"], "2026-11-06T09:00:00")}
    assert PV.capture_rebuild(db, "10001", "", "2026-11", rb, after, T2, WIN, "2026-11-01", "2026-12-01") == ["11.002"]
    v = _vers(db)[-1]
    assert [i["trip"] for i in v["items"]] == ["H3101", "H3300"] and v["changes"] == ["removed H3205 Nov 12-14 SFO"]
    # the next lookup is the authority again: the same pairings, no version; the trip back, a version
    assert PV.capture_lookup(db, "10001", "", _sched([A, C]), T3, WIN) == []
    assert PV.capture_lookup(db, "10001", "", _sched([A, B, C]), "2026-11-09T20:00:00+00:00", WIN) == ["11.003"]


def test_a_rebuilt_trip_read_before_the_lookup_is_not_added(db):
    """A crew read older than the latest version that version does not have is stale (the trip was traded away after
    the read), so a rebuild does not put it back; a read after the version does."""
    PV.capture_lookup(db, "10001", "Doe, Jane", _sched([A]), T0, WIN)  # Nov 5 10:00 HST
    old = _trip("H3500", "2026-11-15", "2026-11-16", checked_at="2026-11-04T08:00:00")
    assert PV.capture_rebuild(db, "10001", "", "2026-11", [old], {}, T1, WIN, "2026-11-01", "2026-12-01") == []
    new = dict(old, checked_at="2026-11-05T11:00:00")
    assert PV.capture_rebuild(db, "10001", "", "2026-11", [new], {}, T1, WIN, "2026-11-01", "2026-12-01") == ["11.002"]


def test_rebuild_with_nothing_read_makes_no_first_version(db):
    assert PV.capture_rebuild(db, "10001", "", "2026-11", [], {}, T0, WIN, "2026-11-01", "2026-12-01") == []
    edge = [_trip("H3001", "2026-10-29", "2026-11-01", route="HNL-SYD-HNL", lay="SYD")]  # off the grid: counts for nothing
    assert PV.capture_rebuild(db, "10001", "", "2026-11", edge, {}, T0, WIN, "2026-11-01", "2026-12-01") == []
    assert _vers(db) == [] and PV.registered(db) == []


# ---------------------------------------------------------------- the award
def _aw(emp="10001"):
    return pdfs.parse_award(AWARD.replace("00999 / 1234", f"00999 / {emp}"), emp, pdfs.package_details(PKG), "2026-11")


def test_award_is_001_and_a_capture_with_its_pairings_adds_nothing(db):
    aw = _aw()
    assert [(i["trip"], i["start"]) for i in aw["items"]] == [("H9001", "2026-11-02"), ("VAC", "2026-11-05")]
    award = lambda e, m: _aw(e) if (e, m) == ("10001", "2026-11") else None  # noqa: E731
    h9001 = _it("H9001", "2026-11-02", "2026-11-04", "LAX")
    assert PV.capture_lookup(db, "10001", "Doe, Jane", _sched([h9001]), T0, WIN, award) == ["11.001"]
    v = _vers(db)
    assert len(v) == 1 and v[0]["source"] == "award" and v[0]["changes"] == ["first version on file (awarded line)"]
    assert v[0]["at"] == "2026-10-12T10:00:00+00:00"  # posted Oct 12 (00:00 HST), so a later crew read can contradict it
    assert v[0]["updated"] == "Award posted October 12, 2026" and v[0]["totals"] == {"credit": "22:00", "days_off": 25}
    assert v[0]["items"][0] == {"trip": "H9001", "start": "2026-11-02", "end": "2026-11-04", "lay": "LAX", "seat": "RO"}
    assert v[0]["days"][0] == ["2026-10-31", "", ""] and v[0]["days"][2] == ["2026-11-02", "H9001", "LAX"]
    assert ["2026-11-05", "VAC", ""] in v[0]["days"]
    # a capture whose pairings differ is .002
    assert PV.capture_lookup(db, "10001", "", _sched([h9001, B]), T1, WIN, award) == ["11.002"]
    assert _vers(db)[1]["changes"] == ["added H3205 Nov 12-14 SFO"]
    # no award for this pilot: his first capture is .001; a rebuild seeds the award the same way
    assert PV.capture_lookup(db, "10002", "", _sched([A]), T0, WIN, award) == ["11.001"]
    assert _vers(db, emp="10002")[0]["source"] == "lookup"
    award3 = lambda e, m: _aw(e)  # noqa: E731
    assert PV.capture_rebuild(db, "10003", "", "2026-11", [_trip("H3101", "2026-11-03", "2026-11-05")], {}, T1, WIN,
                              "2026-11-01", "2026-12-01", award3) == ["11.001", "11.002"]
    v = _vers(db, emp="10003")
    assert [x["source"] for x in v] == ["award", "rebuild"] and [i["trip"] for i in v[1]["items"]] == ["H9001", "H3101"]
    # an award callable that fails is no award
    boom = lambda e, m: 1 / 0  # noqa: E731
    assert PV.capture_lookup(db, "10004", "", _sched([A]), T0, WIN, boom) == ["11.001"]


def test_late_award_becomes_001_and_the_rest_renumber(db):
    PV.capture_lookup(db, "10001", "Doe, Jane", _sched([A]), T0, WIN)
    PV.capture_lookup(db, "10001", "", _sched([A, B]), T1, WIN)
    assert PV.set_award(db, "10001", "2026-11", _aw(), T2, WIN, WIN[0])
    v = _vers(db)
    assert [(x["ver"], x["n"], x["source"]) for x in v] == [("11.001", 1, "award"), ("11.002", 2, "lookup"), ("11.003", 3, "lookup")]
    assert v[0]["changes"] == ["first version on file (awarded line)"]
    assert v[1]["changes"] == ["removed H9001 Nov 2-4 LAX", "added H3101 Nov 3-5 LAX"]
    assert v[2]["changes"] == ["added H3205 Nov 12-14 SFO"]
    assert not PV.set_award(db, "10001", "2026-11", _aw(), T3, WIN, WIN[0])  # the same award again: nothing changes
    assert [x["ver"] for x in _vers(db)] == ["11.001", "11.002", "11.003"]
    # the next capture numbers on
    assert PV.capture_lookup(db, "10001", "", _sched([A]), T3, WIN) == ["11.004"]
    # a first version with the award's pairings goes: the award stands for it
    PV.capture_lookup(db, "10002", "", _sched([_it("H9001", "2026-11-02", "2026-11-03")]), T0, WIN)
    PV.capture_lookup(db, "10002", "", _sched([_it("H9001", "2026-11-02", "2026-11-03"), C]), T1, WIN)
    assert PV.set_award(db, "10002", "2026-11", _aw("10002"), T2, WIN, WIN[0])
    assert [(x["ver"], x["source"], x["changes"]) for x in _vers(db, emp="10002")] == [
        ("11.001", "award", ["first version on file (awarded line)"]), ("11.002", "lookup", ["added H3300 Nov 20-22 NRT"])]
    # no versions yet: nothing to put the award ahead of (the first capture seeds it)
    assert not PV.set_award(db, "10003", "2026-11", _aw("10003"), T2, WIN, WIN[0])


def test_ryans_own_versions_are_untouched(db):
    """R6: pilotver keeps its own keys; versions.py's sched_versions:<month> and its award behave as before."""
    VER.update(db, {"2026-11": {"items": [{"trip": "H9002", "start": "2026-11-04"}], "days": [["2026-11-04", "H9002", "LAX"]],
                                "totals": {}}}, {}, "t1")
    PV.capture_lookup(db, "10001", "", _sched([A]), T0, WIN)
    PV.set_award(db, "10001", "2026-11", _aw(), T1, WIN, WIN[0])
    assert [v["ver"] for v in db.get("sched_versions:2026-11")] == ["11.001"] and "source" not in db.get("sched_versions:2026-11")[0]
    assert VER.MAX_PUBLISHED == PV.MAX_PER_MONTH == 25


# ---------------------------------------------------------------- caps and the registry
def test_month_keeps_the_award_and_the_latest_24(db):
    award = lambda e, m: _aw(e)  # noqa: E731
    trips = [_it(f"H3{k:03d}", "2026-11-15", "2026-11-16") for k in range(31)]
    for k, t in enumerate(trips):
        PV.capture_lookup(db, "10001", "", _sched([t]), f"2026-11-08T{k % 24:02d}:{k:02d}:00+00:00", WIN, award)
    v = _vers(db)
    assert len(v) == 25 and v[0]["ver"] == "11.001" and v[0]["source"] == "award"
    assert v[1]["ver"] == "11.009" and v[-1]["ver"] == "11.032"
    assert PV.summary(db, "10001") == {"2026-11": {"count": 25, "current": "11.032", "awarded": "11.001"}}


def test_at_most_4_bid_months_a_pilot(db):
    for k, m in enumerate(("2026-09", "2026-10", "2026-11", "2026-12", "2027-01")):
        win = (f"{m}-01", f"{m}-28")
        assert PV.capture_lookup(db, "10001", "", _sched([_it("H3101", f"{m}-03", f"{m}-05")], month=m), T0, win)
    assert PV.history(db, "10001")["10001"]["months"].keys() == {"2026-10", "2026-11", "2026-12", "2027-01"}
    assert db.get("pilot_versions:10001:2026-09") is None
    assert db.db.execute("SELECT COUNT(*) FROM kv WHERE k='pilot_versions:10001:2026-09'").fetchone()[0] == 0  # gone
    # a capture for a month older than the four kept is not stored
    assert PV.capture_lookup(db, "10001", "", _sched([_it("H3101", "2026-08-03")], month="2026-08"), T1,
                             ("2026-08-01", "2026-08-31")) == ["8.001"]
    assert db.get("pilot_versions:10001:2026-08") is None and "2026-08" not in PV.registered(db) and \
        PV.history(db, "10001")["10001"]["months"].keys() == {"2026-10", "2026-11", "2026-12", "2027-01"}


def test_at_most_60_pilots_least_recently_looked_up_go(db):
    for k in range(61):
        emp = str(10001 + k)
        PV.register(db, emp, f"Doe, Jane{k}", f"2026-11-08T10:{k:02d}:00+00:00")
        PV.capture_lookup(db, emp, "", _sched([A]), T0, WIN)
    idx = db.get(PV.INDEX_KEY)
    assert len(idx) == 60 and "10001" not in idx and "10061" in idx
    assert db.get("pilot_versions:10001:2026-11") is None and db.get("pilot_versions:10002:2026-11")
    PV.register(db, "10002", "", "2026-11-09T10:00:00+00:00")  # looked up again: newest now
    PV.register(db, "10099", "Roe, Rick", "2026-11-09T11:00:00+00:00")
    idx = db.get(PV.INDEX_KEY)
    assert "10002" in idx and "10003" not in idx and idx["10002"]["name"] == "Doe, Jane1"


def test_registry_history_and_summary(db):
    assert PV.register(db, "x10001y", "Doe, Jane", T0) == {"name": "Doe, Jane", "months": [], "last_seen": T0}
    assert PV.register(db, "", "Nobody", T0) is None
    assert PV.history(db, "10001") == {"10001": {"name": "Doe, Jane", "months": {}}} and PV.summary(db, "10001") == {}
    assert PV.history(db, "10002") == {} and PV.history(db, "") == {}
    PV.capture_lookup(db, "10001", "", _sched([A]), T1, WIN)
    PV.capture_lookup(db, "10001", "", _sched([A, B]), T2, WIN)
    PV.register(db, "10002", "Roe, Rick", T3)
    assert PV.registered(db) == ["10002", "10001"] and PV.registered(db, "2026-11") == ["10001"]
    h = PV.history(db, "10001")
    assert list(h) == ["10001"] and h["10001"]["name"] == "Doe, Jane"
    recs = h["10001"]["months"]["2026-11"]
    assert [r["ver"] for r in recs] == ["11.001", "11.002"]  # oldest first
    assert set(recs[0]) == {"ver", "n", "at", "source", "updated", "items", "days", "totals", "changes"}  # no fp, no win
    assert db.get(PV.INDEX_KEY)["10001"]["months"] == ["2026-11"] and db.get(PV.INDEX_KEY)["10001"]["last_seen"] == T0
    assert PV.summary(db, "10001") == {"2026-11": {"count": 2, "current": "11.002", "awarded": ""}}
    PV.register(db, "10001", "Doe, Jane A", T3)  # a name from FLICA replaces the typed one
    assert PV.history(db, "10001")["10001"]["name"] == "Doe, Jane A"


# ---------------------------------------------------------------- the days drawn for a rebuild: the card's own _rebuild
CARD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "www", "flight-watcher-pilot-card.js")


def test_rebuilt_days_match_the_pilot_cards_grid(tmp_path):
    """build_days(rebuild_items(trips)) gives the same rows the pilot card's _rebuild draws from the same trips: a trip
    running in from before the grid, a turn, two trips on the same days (the newer read goes in the grid), a trip past
    the bid period's end."""
    trips = [_trip("H3001", "2026-10-29", "2026-11-01", route="HNL-SYD-HNL", lay="SYD"),
             _trip("H3101", "2026-11-03", "2026-11-05", route="HNL-LAX-HNL", lay=""),
             _trip("H3150", "2026-11-04", "2026-11-06", checked_at="2026-11-01T08:00:00", route="HNL-SEA-HNL"),
             _trip("H3205", "2026-11-12", "2026-11-12", route="HNL-OGG-HNL", lay=""),
             _trip("H3300", "2026-11-20", "2026-11-23", route="HNL-NRT-HNL-SFO-HNL", lay=""),
             _trip("H3999", "2026-12-01", "2026-12-03", route="HNL-SYD-HNL", lay="SYD")]
    items = PV.rebuild_items(trips)
    assert [i["trip"] for i in items] == ["H3001", "H3101", "H3205", "H3300", "H3999"]  # H3150 is the older read
    assert [i["lay"] for i in items] == ["SYD", "LAX", "HNL", "", "SYD"]
    py = PV.build_days(items, "2026-11", "2026-11-01", "2026-12-01")
    assert py[0] == ["2026-10-29", "H3001", "SYD"] and py[-1] == ["2026-12-01", "H3999", "SYD"]  # starts on the last day: open at the bottom, as on the card
    if not shutil.which("node"):
        pytest.skip("node not installed")
    a = {"reconstructed": trips, "reconstructed_month": "2026-11", "reconstructed_from": "2026-11-01",
         "reconstructed_to": "2026-12-01", "month": "", "days": []}
    js = ("globalThis.HTMLElement = class { constructor() { this.style = {}; } };\n"
          "globalThis.customElements = {define() {}, get() {}};\n"
          "globalThis.window = {addEventListener() {}, removeEventListener() {}, dispatchEvent() {}, customCards: []};\n"
          "globalThis.location = {hash: '', pathname: '/', search: ''}; globalThis.history = {replaceState() {}};\n"
          + open(CARD, encoding="utf-8").read() +
          f"\nconsole.log(JSON.stringify(new FlightWatcherPilotCard()._rebuild({json.dumps(a)}).days));\n")
    f = tmp_path / "rb.js"
    f.write_text(js)
    out = subprocess.run(["node", str(f)], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout) == py


def test_an_award_without_a_posting_day_is_dated_before_the_period(db):
    """No 'Posted' line: the award's capture time is ten days before the grid's first day (00:00 HST), so a crew read
    made since then still adds a trip to a rebuild; now when that is earlier."""
    assert PV.award_fallback_at("2026-11-09T01:00:00+00:00", "2026-10-31") == "2026-10-21T10:00:00+00:00"
    assert PV.award_fallback_at("2026-10-01T00:00:00+00:00", "2026-10-31") == "2026-10-01T00:00:00+00:00"
    assert PV.award_fallback_at("2026-11-09T01:00:00+00:00", "") == "2026-11-09T01:00:00+00:00"
    aw = _aw()
    aw["updated"] = "Award"
    award = lambda e, m: aw  # noqa: E731
    trip = _trip("H3500", "2026-11-15", "2026-11-16", checked_at="2026-11-04T08:00:00")  # read after Oct 21, before now
    assert PV.capture_rebuild(db, "10001", "", "2026-11", [trip], {}, T1, WIN, "2026-11-01", "2026-12-01", award) == \
        ["11.001", "11.002"]
    v = _vers(db)
    assert v[0]["at"] == "2026-10-21T10:00:00+00:00" and [i["trip"] for i in v[1]["items"]] == ["H9001", "H3500"]
