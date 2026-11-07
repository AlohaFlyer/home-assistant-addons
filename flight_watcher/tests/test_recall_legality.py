"""1.4.6 (Ryan, Nov 6): the Recall / Over 75 miss check is judged on the line Ryan held on the list day (schedule
versions), with full FAR 117 and PWA legality, and anything not on file gives POSSIBLE, never MISSED.
FAR 117.25(b)(e), 117.23(b)(1), 117.23(c)(1)(2); PWA 10.E.1.a, 2.19.b, 22.G.2.d-g. Synthetic data only."""
from datetime import date, datetime, timedelta

import far as F
import recall as RC

ME = {"sen": 500, "seat": "FO", "o75": True}
# H9001: report 08:00 Nov 10, LAX layover, back 16:00 Nov 11 (two duty periods, 10:00 block)
DET = {"H9001": {"report": "08:00", "block": "10:00", "rel_days": 2,
                 "duties": [{"d": 0, "dep": 540, "arr": 840, "stn": "LAX", "blk": 300},
                            {"d": 1, "dep": 2100, "arr": 2400, "stn": "HNL", "blk": 300}]}}
ROW = {"date": "2026-11-10", "kind": "recall", "seat": "FO", "pilot": "Doe, Jane", "sen": 900, "pairing": "H9001"}
DAY = date(2026, 11, 10)


def D(d, h=0, m=0, mo=11):
    return datetime(2026, mo, 1, h, m) + timedelta(days=d - 1)


def T(label, rep, blockin, blk=None, flying=True):
    """One exact one-duty trip as far.legality() reads it."""
    return {"label": label, "report": rep, "release": blockin + F.DEBRIEF, "duties": [(rep, blockin, blk)],
            "exact": True, "approx": False, "flying": flying}


def V(at, items=(), trips=None, months=("2026-10", "2026-11", "2026-12"), ver=1):
    """{month: [one version seen at `at`]} holding the items that start in that month."""
    return {mk: [{"ver": f"{int(mk[5:])}.{ver:03d}", "n": ver, "at": at, "days": [], "totals": {},
                  "items": [i for i in items if i["start"][:7] == mk],
                  "trips": {k: v for k, v in (trips or {}).items() if k.split("|")[1][:7] == mk}}] for mk in months}


def merge(*vs):
    out = {}
    for v in vs:
        for mk, lst in v.items():
            out[mk] = sorted(out.get(mk, []) + lst, key=lambda x: x["at"])
    return out


def judge(versions, current=None, own=None, day=DAY, row=ROW):
    return RC.judge(row, ME, RC.helds_on(versions, day, current or {}, own or {}), [], DET)


EARLY = "2026-10-20T00:00:00+00:00"


# ---------------------------------------------------------------- as of the list day
def test_a_trip_picked_up_after_the_list_day_does_not_clear_the_miss():
    """On Nov 10 Ryan's line was open and legal: MISSED. On Nov 11 he picked up H1234 reporting 01:00 Nov 12, 8:45
    after the recall pairing's release. Today's line says NO (rest, FAR 117.25(e)); the line he held says MISSED."""
    pick = {"trip": "H1234", "start": "2026-11-12", "end": "2026-11-12"}
    t = {"H1234|2026-11-12": {"report": "01:00", "last_arr": "09:00", "blk": "6:00"}}
    later = V("2026-11-11T20:00:00+00:00", [pick], t, months=("2026-11",), ver=2)
    versions = merge(V(EARLY), later)
    assert RC.evaluate(ROW, ME, [pick], t, [], DET)["verdict"] == "NO"  # today's line (what 1.4.5 did)
    v = judge(versions, {"2026-11": {"items": [pick]}}, t)
    assert v["verdict"] == "MISSED", v["why"]
    assert "Nov 10 00:00 HST" in v["why"][-1] and "version 11.001" in v["why"][-1]


def test_a_trip_dropped_after_the_list_day_does_not_make_a_miss():
    """On Nov 10 Ryan held H1234 Nov 11-13 (in the way: removal is 22.G.2.f, after clean junior volunteers). He traded
    it away on Nov 11 05:00 HST. Today's line is open (MISSED for 1.4.5); the line he held says NO."""
    held = {"trip": "H1234", "start": "2026-11-11", "end": "2026-11-13"}
    versions = merge(V(EARLY, [held]), V("2026-11-11T15:00:00+00:00", [], months=("2026-11",), ver=2))
    assert RC.evaluate(ROW, ME, [], {}, [], DET)["verdict"] == "MISSED"  # today's line
    v = judge(versions)
    assert v["verdict"] == "NO" and "H1234" in v["why"][-1] and "22.G.2.f" in v["why"][-1]


def test_a_line_that_changed_during_the_list_day_is_possible():
    """A version seen at 12:00 HST on the list day puts H1234 in the way; the award time is not on the list, so the
    row is POSSIBLE and says what each line gave."""
    held = {"trip": "H1234", "start": "2026-11-11", "end": "2026-11-13"}
    versions = merge(V(EARLY), V("2026-11-10T22:00:00+00:00", [held], months=("2026-11",), ver=2))
    v = judge(versions)
    assert v["verdict"] == "POSSIBLE"
    assert any("changed during the day" in w and "MISSED" in w for w in v["why"])
    assert any("12:00 HST: NO" in w for w in v["why"])


def test_no_version_on_file_for_the_list_day_is_possible_never_missed():
    """The Watcher's first version came after the list day: the days from the list day on are not on file then."""
    v = judge(V("2026-11-15T00:00:00+00:00"))
    assert v["verdict"] == "POSSIBLE" and "not on file" in v["why"][-1]
    v = judge({})  # nothing at all
    assert v["verdict"] == "POSSIBLE"


def test_a_month_of_the_672_h_window_not_on_file_is_possible():
    """October is not on file at all: FAR 117.23(b)(1) and (c)(2) cannot be proven, so POSSIBLE (not MISSED)."""
    v = judge(V(EARLY, months=("2026-11", "2026-12")))
    assert v["verdict"] == "POSSIBLE"
    assert "FAR 117.23(b)(1)" in v["why"][-1] and "your line 2026-10-05 to 2026-11-07 not on file" in v["why"][-1]


def test_a_later_month_not_awarded_yet_is_empty_but_its_first_days_stay_unknown():
    """List day Nov 20: December's first version came Nov 28, so December was not awarded yet: no trips, MISSED.
    List day Nov 26: December 1-4 fall within NEAR days, so they stay unknown in case the Watcher missed it, and in
    the worst case they could hold 60 h of FDP in 168 h with the pairing (FAR 117.23(c)(1)): POSSIBLE."""
    row = dict(ROW, date="2026-11-20", pairing="H9001")
    versions = merge(V(EARLY, months=("2026-10", "2026-11")), V("2026-11-28T00:00:00+00:00", months=("2026-12",)))
    v = judge(versions, day=date(2026, 11, 20), row=row)
    assert v["verdict"] == "MISSED", v["why"]
    row = dict(ROW, date="2026-11-26")
    v = judge(versions, day=date(2026, 11, 26), row=row)
    assert v["verdict"] == "POSSIBLE" and "your line 2026-12-01 to 2026-12-04 not on file" in v["why"][-1], v["why"]
    assert "FAR 117.23(c)(1)" in v["why"][-1]


def test_a_neighbouring_trip_without_times_is_possible():
    trip = {"trip": "H1234", "start": "2026-11-09", "end": "2026-11-09"}
    v = judge(V(EARLY, [trip]))  # no report / arrival on file for H1234
    assert v["verdict"] == "POSSIBLE" and "H1234 Nov 9 times not on file" in v["why"][-1]


def test_unknown_pairing_times_are_possible():
    v = judge(V(EARLY), row=dict(ROW, pairing="H9999"))
    assert v["verdict"] == "POSSIBLE" and "pairing times unknown" in v["why"][-1]


def test_every_rule_is_cited():
    v = judge(V(EARLY))
    assert v["verdict"] == "MISSED"
    for ref in ("PWA 22.G.2.e, 22.E, 4.M (200%)", "FAR 117.25(e)", "PWA 10.E.1.a", "FAR 117.25(b)", "FAR 117.23(b)(1)",
                "FAR 117.23(c)(1)", "FAR 117.23(c)(2)", "PWA 2.19.b"):
        assert ref in v["refs"], ref
    for ref in ("FAR 117.25(b)", "FAR 117.23(b)(1)", "FAR 117.23(c)(1)", "FAR 117.23(c)(2)"):
        assert ref in v["why"][-1], ref
    n = RC.narrative(v, ME)
    assert "117.23(c)" in n and "version 11.001" in n


# ---------------------------------------------------------------- FAR 117 / PWA gaps closed in far.legality()
NEW = T("H9001", D(10, 8), D(10, 14), 5)


def test_30_hours_free_in_168_before_the_pairing():
    """Duty six days in a row (Nov 4-9), then the pairing on the 7th: no 30 h free in the 168 h before it."""
    mine = [T(f"H10{d:02d}", D(d, 8), D(d, 14), 5) for d in range(4, 10)]
    r = F.legality(NEW, mine)
    assert r["result"] == "NO" and len(r["issues"]) == 1 and "FAR 117.25(b)" in r["issues"][0], r


def test_fdp_60_in_168():
    """13 h duties Nov 6, 7, 8 and 12 with the pairing (13 h) on Nov 10: 65 h of FDP in 168 h."""
    new = T("H9001", D(10, 8), D(10, 21), 6)
    mine = [T(f"H10{d:02d}", D(d, 6), D(d, 19), 6) for d in (6, 7, 8, 12)]
    r = F.legality(new, mine)
    assert r["result"] == "NO" and len(r["issues"]) == 1 and "FAR 117.23(c)(1)" in r["issues"][0], r


def test_fdp_190_in_672():
    """14:12 duties every other day for four weeks around the pairing: 190:36 of FDP in 672 h, while every 168 h
    stays under 60 and 30 h free holds."""
    x = D(20)
    mine = [T(f"P{k}", x + timedelta(days=k, hours=6.5), x + timedelta(days=k, hours=6.5 + 14.2), 3)
            for k in range(-14, 15, 2) if k]
    r = F.legality(T("H9001", x + timedelta(hours=8), x + timedelta(hours=14), 5), mine)
    assert r["result"] == "NO" and len(r["issues"]) == 1 and "FAR 117.23(c)(2)" in r["issues"][0], r


def test_flight_time_100_in_672():
    x = D(20)
    mine = [T(f"P{k}", x + timedelta(days=k, hours=8), x + timedelta(days=k, hours=16), 7.5)
            for k in range(-14, 15, 2) if k]
    r = F.legality(T("H9001", x + timedelta(hours=8), x + timedelta(hours=14), 5), mine)
    assert r["result"] == "NO" and len(r["issues"]) == 1 and "FAR 117.23(b)(1)" in r["issues"][0], r


def test_rest_far_10_h_pwa_11_h_and_the_customs_margin():
    def before(h, m):  # a trip whose release (block-in + 15 min) is h:m before the pairing's 08:00 report
        rel = D(10, 8) - timedelta(hours=h, minutes=m)
        return [T("H1234", rel - timedelta(hours=8), rel - F.DEBRIEF, 6)]
    r = F.legality(NEW, before(9, 0))
    assert r["result"] == "NO" and "FAR 117.25(e)" in r["issues"][0]
    r = F.legality(NEW, before(10, 30))
    assert r["result"] == "NO" and "PWA 10.E.1.a" in r["issues"][0] and "117.25(e)" not in r["issues"][0]
    r = F.legality(NEW, before(11, 5))  # 30 min after block-in when clearing customs (PWA 2.19.b) makes it 10:50
    assert r["result"] == "?" and "PWA 2.19.b" in r["unknown"][0]
    r = F.legality(NEW, before(11, 20))
    assert r["result"] == "OK" and "rest 11:20 before" in r["summary"]


def test_a_guess_never_passes_and_never_fails():
    """A neighbour with only its dates, or days not on file, make a check unknown: never OK, never NO."""
    approx = RC._trip("H1234 Nov 9", D(9).date(), D(9).date(), None, None, None, None)
    assert F.legality(NEW, [approx])["result"] == "?"
    gap = RC._gaps_as_trips([("2026-10-12", "2026-10-31")])
    r = F.legality(NEW, gap)
    assert r["result"] == "?" and any("117.23(b)(1)" in u for u in r["unknown"])
    assert F.legality(NEW, [])["result"] == "OK"


def test_held_line_parts():
    """held_at(): the newest version at or before 00:00 HST of the day; trips that started before the day come from
    a later version when nothing earlier is on file; the rest of that month is unknown."""
    a = {"trip": "H1111", "start": "2026-11-02", "end": "2026-11-03"}
    b = {"trip": "H2222", "start": "2026-11-15", "end": "2026-11-16"}
    h = RC.held_at(V("2026-11-12T00:00:00+00:00", [a, b], months=("2026-11",)), DAY)
    assert [i["trip"] for i in h["items"]] == ["H1111"] and ("2026-11-10", "2026-12-07") in h["unknown"]
    h = RC.held_at(merge(V(EARLY, [a]), V("2026-11-12T00:00:00+00:00", [a, b], months=("2026-11",), ver=2)), DAY)
    assert [i["trip"] for i in h["items"]] == ["H1111"] and h["line"] == "11.001" and not h["unknown"]


def test_an_award_alone_counts_only_for_a_month_the_watcher_watched():
    """A month with only the PBS award on file: its line is the award when the Watcher kept versions from that month's
    first day (a change would have made a version); October began before the Watcher kept versions, so an October
    award alone is not on file (a pickup there would be unseen)."""
    oct_award = {"2026-10": [{"ver": "10.001", "award": True, "at": "2026-11-05T00:00:00+00:00",
                              "items": [{"trip": "H1111", "start": "2026-10-20", "end": "2026-10-21"}], "trips": {}}]}
    dec_award = {"2026-12": [{"ver": "12.001", "award": True, "at": "2026-11-05T00:00:00+00:00",
                              "items": [{"trip": "H2222", "start": "2026-12-05", "end": "2026-12-06"}], "trips": {}}]}
    keeping = V("2026-11-02T00:00:00+00:00", months=("2026-11",))
    h = RC.held_at(merge(keeping, oct_award, dec_award), DAY)
    assert ("2026-10-05", "2026-11-07") in h["unknown"] and h["lines"]["2026-10"] == "not on file"
    assert [i["trip"] for i in h["items"]] == ["H2222"] and h["lines"]["2026-12"] == "12.001"


# ---------------------------------------------------------------- 1.4.6 review (Nov 7)
def test_a_row_awarded_to_ryan_himself_is_not_a_miss():
    """Ryan (#500) is awarded H9001 for Nov 10 at 21:00 HST; the version holding it is stored at 00:40 HST Nov 11 (the
    block / credit wait). His own award is never a miss, whatever line was on file at 00:00."""
    mine = {"trip": "H9001", "start": "2026-11-10", "end": "2026-11-11"}
    late = V("2026-11-11T10:40:00+00:00", [mine], months=("2026-11",), ver=2)
    late["2026-11"][0]["updated"] = "Nov 10, 2026 21:00:00"
    versions = merge(V(EARLY), late)
    row = dict(ROW, sen=500)
    v = judge(versions, row=row)
    assert v["verdict"] == "NO" and v["why"][0].startswith("awarded to you (#500)"), v["why"]
    v = judge(merge(V(EARLY)), row=row)  # the version never came: still his own
    assert v["verdict"] == "NO" and "awarded to you" in v["why"][0]


def test_a_pairing_of_unknown_length_is_possible_not_one_day():
    """No days on the row and no package: H9002's report and last arrival are known but not its length. It must not
    shrink to one day (Ryan's H1111 on Nov 12-13 would be ignored and the row MISSED)."""
    trip = {"trip": "H1111", "start": "2026-11-12", "end": "2026-11-13"}
    t = {"H1111|2026-11-12": {"report": "08:00", "last_arr": "16:00", "blk": "8:00"}}
    row = dict(ROW, pairing="H9002", report="08:00", last_arr="06:00", blk="18:00")
    v = judge(V(EARLY, [trip], t), row=row)
    assert v["verdict"] == "POSSIBLE" and "pairing length unknown" in v["why"][-1], v["why"]
    v = judge(V(EARLY, [trip], t), row=dict(row, days=4))  # with its length: H1111 is in the way
    assert v["verdict"] == "NO" and "H1111" in v["why"][-1]
    assert RC.pairing_window(row, {})[5] is False and RC.pairing_window(dict(row, days=2), {})[5] is True
    assert RC.pairing_window(ROW, DET)[5] is True  # the package's duty periods give it


def test_details_come_from_the_row_s_own_bid_period():
    """Pairing ids repeat across bid periods: October's H3601 is 4 days, November's is 1 day. An October row is judged
    with October's package (H1200 Oct 30-31 is in the way), never November's, whichever is looked up first."""
    pkgs = {"2026-10": {"H3601": {"report": "08:00", "block": "20:00", "rel_days": 4}},
            "2026-11": {"H3601": {"report": "08:00", "block": "5:00", "rel_days": 1,
                                  "duties": [{"d": 0, "dep": 540, "arr": 840, "stn": "HNL", "blk": 300}]}}}
    h = {"trip": "H1200", "start": "2026-10-30", "end": "2026-10-31"}
    row = dict(ROW, date="2026-10-28", pairing="H3601", last_arr="16:00")
    helds = RC.helds_on(V(EARLY, [h]), date(2026, 10, 28))
    v = RC.check_day([row], ME, None, None, [], lambda p: pkgs.get(p), helds)[0]
    assert v["verdict"] == "NO" and "H1200" in v["why"][-1] and v["end"] == "2026-10-31", v["why"]
    assert RC.check_day([row], ME, None, None, [], lambda p: {}, helds)[0]["verdict"] == "POSSIBLE"  # no package


def test_a_version_read_late_counts_from_flica_s_updated_stamp():
    """Ryan picked up H2222 (Nov 10-11) on Nov 8 10:00 HST ('Schedule Updated: Nov 8, 2026 10:00:00'); the Watcher was
    stuck on a CAPTCHA and stored version 11.002 only on Nov 12. The Nov 10 line is 11.002, so H2222 is in the way."""
    pick = {"trip": "H2222", "start": "2026-11-10", "end": "2026-11-11"}
    late = V("2026-11-12T00:00:00+00:00", [pick], months=("2026-11",), ver=2)
    late["2026-11"][0]["updated"] = "Nov 8, 2026 10:00:00"
    v = judge(merge(V(EARLY), late))
    assert v["verdict"] == "NO" and "H2222" in v["why"][-1] and "version 11.002" in v["why"][-1], v["why"]
    late["2026-11"][0]["updated"] = "Nov 11, 2026 10:00:00"  # changed after the list day: the old line held
    assert judge(merge(V(EARLY), late))["verdict"] == "MISSED"
    late["2026-11"][0]["updated"] = ""  # no stamp: only 'at' is trusted
    assert judge(merge(V(EARLY), late))["verdict"] == "MISSED"
    late["2026-11"][0]["updated"] = "Nov 30, 2026 10:00:00"  # later than the read: not trusted
    assert RC._upd(late["2026-11"][0]) is None


def test_a_month_awarded_during_an_outage_is_not_counted_as_not_awarded_yet():
    """List day Nov 20; December's first version is stored Nov 28 but FLICA shows it updated Nov 15: December was
    awarded by then, so its trips count (the 672 h windows), not 'not awarded yet'."""
    dec = {"trip": "H3000", "start": "2026-12-05", "end": "2026-12-06"}
    late = V("2026-11-28T00:00:00+00:00", [dec], months=("2026-12",))
    late["2026-12"][0]["updated"] = "Nov 15, 2026 12:00:00"
    versions = merge(V(EARLY, months=("2026-10", "2026-11")), late)
    h = RC.held_at(versions, date(2026, 11, 20))
    assert h["lines"]["2026-12"] == "12.001" and [i["trip"] for i in h["items"]] == ["H3000"]
    late["2026-12"][0]["updated"] = "Nov 27, 2026 12:00:00"
    h = RC.held_at(merge(V(EARLY, months=("2026-10", "2026-11")), late), date(2026, 11, 20))
    assert h["lines"]["2026-12"] == "not awarded yet" and not h["items"]


def test_a_trip_from_the_month_before_counts_in_the_672_h_window():
    """List day Oct 30 (LOOK reaches Oct 1). H1000 runs Sep 29 to Oct 3 with 10 h block on Oct 3, plus 81 h of October
    trips and the 10 h recall pairing: 101 h in the 672 h from Oct 3 (FAR 117.23(b)(1)). The September trip counts."""
    sep = {"trip": "H1000", "start": "2026-09-29", "end": "2026-10-03"}
    sep_t = {"H1000|2026-09-29": {"report": "08:00", "last_arr": "16:00", "blk": "15:00",
                                  "duties": [{"d": 0, "dep": 540, "arr": 840, "stn": "LAX", "blk": 300},
                                             {"d": 4, "dep": 4 * 1440 + 360, "arr": 4 * 1440 + 960, "stn": "HNL", "blk": 600}]}}
    octs = [{"trip": f"H10{d:02d}", "start": f"2026-10-{d:02d}", "end": f"2026-10-{d:02d}"} for d in range(5, 22, 2)]
    oct_t = {f"H10{d:02d}|2026-10-{d:02d}": {"report": "08:00", "last_arr": "18:00", "blk": "9:00"} for d in range(5, 22, 2)}
    row = dict(ROW, date="2026-10-30", pairing="H9005", report="08:00", last_arr="18:00", blk="10:00", days=1)
    months = ("2026-09", "2026-10", "2026-11", "2026-12")
    v = judge(V(EARLY, [sep] + octs, {**sep_t, **oct_t}, months=months), day=date(2026, 10, 30), row=row)
    assert v["verdict"] == "NO" and "flight time 101:00 h in 672 h" in v["why"][-1], v["why"]
    # September not on file: its last days are unknown, so POSSIBLE, never MISSED
    v = judge(V(EARLY, octs, oct_t, months=months[1:]), day=date(2026, 10, 30), row=row)
    assert v["verdict"] == "POSSIBLE" and "your line 2026-09-24 to 2026-10-07 not on file" in v["why"][-1], v["why"]
    # and a pairing on Oct 2-3: a September trip could still be running (it is in September's items only)
    v = judge(V(EARLY, octs, oct_t, months=months[1:]), day=date(2026, 10, 2), row=dict(row, date="2026-10-02", days=2))
    assert v["verdict"] == "POSSIBLE" and "not on file for 2026-09-01 to 2026-10-07" in v["why"][-1], v["why"]


def test_over_75_needs_the_month_s_reserve_answer():
    """PWA 22.G.2.d: Over 75 goes to Reserve Run pilots. Without Ryan's answer for the month the row is POSSIBLE, not
    MISSED; 'on reserve' that month gives MISSED; 'not on reserve' gives NO."""
    row = dict(ROW, kind="o75")
    me = {"sen": 500, "seat": "FO", "o75": True}  # the old flag no longer counts
    v = RC.judge(row, me, RC.helds_on(V(EARLY), DAY, {}, {}), [], DET)
    assert v["verdict"] == "POSSIBLE" and "reserve status for Nov 2026 unknown" in v["why"][-1], v["why"]
    v = RC.judge(row, {**me, "o75_months": {"2026-11": True}}, RC.helds_on(V(EARLY), DAY, {}, {}), [], DET)
    assert v["verdict"] == "MISSED"
    v = RC.judge(row, {**me, "o75_months": {"2026-11": False, "2026-12": True}}, RC.helds_on(V(EARLY), DAY, {}, {}), [], DET)
    assert v["verdict"] == "NO" and "not on reserve in Nov 2026" in v["why"][-1]
