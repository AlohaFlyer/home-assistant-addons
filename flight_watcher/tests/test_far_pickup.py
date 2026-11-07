"""FW-0039: the FAR column of pot, Tradeboard and finds rows uses far.legality()'s rules (FAR 117.25(e), 117.25(b),
117.23(b)(1) and the cumulative FDP limits of 117.23(c): 60 h in any 168 h, 190 h in any 672 h; PWA 10.E.1.a,
2.19.b), per duty period of Ryan's trips and of the pickup. Data not on file gives '?', never OK.
Synthetic trips and pairing numbers only."""
import json
import sys
from datetime import date, datetime, timedelta

import far as F
import pot as P
import recall as RC


def D(d, h=0, m=0, mo=11):
    return datetime(2026, mo, 1, h, m) + timedelta(days=d - 1)


def T(label, rep, blockin, blk=None, flying=True):
    return {"label": label, "report": rep, "release": blockin + F.DEBRIEF, "duties": [(rep, blockin, blk)],
            "exact": True, "approx": False, "flying": flying}


NEW = T("H9001", D(10, 8), D(10, 14), 5)


def before(h, m):
    """Ryan's trip released h:m before the pickup's 08:00 report on Nov 10."""
    rel = D(10, 8) - timedelta(hours=h, minutes=m)
    return [T("H1234", rel - timedelta(hours=8), rel - F.DEBRIEF, 6)]


def test_fdp_60_in_168_is_no_longer_ok():
    """13 h duties Nov 6, 7, 8 and 12 and a 13 h pickup on Nov 10: 65 h of FDP in 168 h (FAR 117.23(c)(1)). Rest,
    30 h free and flight time all pass, so the old screen (far_check) read OK; the column now names the limit."""
    new = T("H9001", D(10, 8), D(10, 21), 6)
    mine = [T(f"H10{d:02d}", D(d, 6), D(d, 19), 6) for d in (6, 7, 8, 12)]
    r = F.screen(new, mine)
    assert r["far"] == "FDP 65h/168h" and r["result"] == "NO", r
    assert "FAR 117.23(c)(1)" in r["why"]


def test_an_over_limit_total_never_reads_as_the_limit():
    """12 h duties Nov 6, 7, 8 and 12 and a 12:30 pickup on Nov 10: 60:30 h of FDP in 168 h. The column rounds up
    ('61h', never '60h/168h', which reads as at the limit) and the why line gives the minutes (FAR 117.23(c)(1))."""
    new = T("H9001", D(10, 8), D(10, 20, 30), 6)
    mine = [T(f"H10{d:02d}", D(d, 6), D(d, 18), 6) for d in (6, 7, 8, 12)]
    r = F.screen(new, mine)
    assert r["far"] == "FDP 61h/168h" and r["result"] == "NO", r
    assert "FDP 60:30 h in 168 h" in r["why"]


def test_the_worst_failing_window_is_shown_not_the_first():
    """A 14 h duty on Nov 13 makes the window Nov 6 20:00 to Nov 13 20:00 hold 62:30 h; an earlier window that also
    fails holds 60:30 h. The column shows the worst one."""
    new = T("H9001", D(10, 8), D(10, 20, 30), 6)
    mine = [T(f"H10{d:02d}", D(d, 6), D(d, 18), 6) for d in (6, 7, 8, 12)] + [T("H1013", D(13, 6), D(13, 20), 6)]
    r = F.screen(new, mine)
    assert r["far"] == "FDP 63h/168h", r
    assert "FDP 62:30 h in 168 h" in r["why"]


def test_fdp_190_in_672():
    x = D(20)
    mine = [T(f"P{k}", x + timedelta(days=k, hours=6.5), x + timedelta(days=k, hours=6.5 + 14.2), 3)
            for k in range(-14, 15, 2) if k]
    r = F.screen(T("H9001", x + timedelta(hours=8), x + timedelta(hours=14), 5), mine)
    assert r["far"] == "FDP 191h/672h", r
    assert "FAR 117.23(c)(2)" in r["why"]


def test_flight_time_30_in_168_rest_and_conflict_words_are_kept():
    x = D(20)
    ft = [T(f"P{k}", x + timedelta(days=k, hours=8), x + timedelta(days=k, hours=16), 7.5) for k in range(-14, 15, 2) if k]
    # 102:30 h of flight time: rounded up, so the column never shows less than the total
    assert F.screen(T("H9001", x + timedelta(hours=8), x + timedelta(hours=14), 5), ft)["far"] == "FT 103h/672h"
    six = [T(f"H10{d:02d}", D(d, 8), D(d, 14), 5) for d in range(4, 10)]
    assert F.screen(NEW, six)["far"] == "No 30h/168h"
    assert F.screen(NEW, before(9, 0))["far"] == "Rest 9:00 before"
    assert F.screen(NEW, [T("H1234", D(10, 23), D(11, 6), 5)])["far"] == "Rest 8:45 after"
    assert F.screen(NEW, [T("H1234", D(10, 6), D(10, 12), 5)])["far"] == "Conflict"
    assert F.screen(NEW, []) == {"far": "OK", "why": "", "result": "OK"}


def test_pwa_11_h_rest_stays_the_cba_note():
    """FAR 117.25(e) met, PWA 10.E.1.a 11 h domicile rest short: legal by FAR, flagged as before."""
    r = F.screen(NEW, before(10, 30))
    assert r["far"] == "OK (CBA rest 10:30)" and "PWA 10.E.1.a" in r["why"] and r["result"] == "NO"
    r = F.screen(NEW, before(11, 5))  # 30 min after block-in for customs (PWA 2.19.b) leaves 10:50
    assert r["far"] == "OK (CBA rest 10:50?)" and "PWA 2.19.b" in r["why"]
    assert F.screen(NEW, before(11, 20))["far"] == "OK"


def test_customs_can_make_far_rest_unknown():
    """Released 10:05 before report: under 10 h if that release was 30 min after block-in (FAR 117.25(e))."""
    r = F.screen(NEW, before(10, 5))
    assert r["far"] == "?" and "FAR 117.25(e)" in r["why"] and "PWA 2.19.b" in r["why"]


def test_unknown_data_is_never_ok():
    approx = RC._trip("H1234 Nov 9", D(9).date(), D(9).date(), None, None, None, None)
    r = F.screen(NEW, [approx])
    assert r["far"] == "?" and "not on file" in r["why"]
    gap = RC._gaps_as_trips([("2026-10-12", "2026-10-31")])
    r = F.screen(NEW, gap)
    assert r["far"] == "?" and "117.23(b)(1)" in r["why"]
    assert F.screen(NEW, [RC._trip("H1234 Nov 10", D(10).date(), D(10).date(), None, None, None, None)])["far"] == "?"


def test_pickup_duty_periods_split_the_layover():
    """A 3-day pickup: as one span its 50 h would count as FDP (unknown, '?'); with the duty times from its pairing
    page only the two duty periods count."""
    duties = [{"d": 0, "dep": 540, "arr": 840, "stn": "LAX", "blk": 300},
              {"d": 2, "dep": 3480, "arr": 3780, "stn": "HNL", "blk": 300}]
    mine = [T(f"H10{d:02d}", D(d, 6), D(d, 18), 6) for d in (5, 6)]
    span = RC.pickup_trip("H9001", D(10).date(), D(12).date(), "08:00", "15:00", 10.0, [])
    split = RC.pickup_trip("H9001", D(10).date(), D(12).date(), "08:00", "15:00", 10.0, duties)
    assert not span["exact"] and split["exact"] and len(split["duties"]) == 2
    assert F.screen(span, mine)["far"] == "?"
    assert F.screen(split, mine)["far"] == "OK"


def test_line_gaps():
    nov = {"2026-11": {"days": [[(date(2026, 11, 1) + timedelta(days=i)).isoformat(), "", ""] for i in range(30)]}}
    # October not on file: unknown; December after the last day on file and more than 8 days out: not awarded yet
    g = RC.line_gaps(nov, date(2026, 10, 28), date(2026, 12, 20), date(2026, 11, 2))
    assert g == [("2026-10-28", "2026-10-31")]
    # 8 days or less after today, December may be awarded and not read yet: unknown
    g = RC.line_gaps(nov, date(2026, 11, 20), date(2026, 12, 20), date(2026, 11, 28))
    assert g == [("2026-12-01", "2026-12-06")]
    assert RC.line_gaps({}, date(2026, 11, 1), date(2026, 11, 3), date(2026, 11, 1)) == [("2026-11-01", "2026-11-03")]


# ---------------------------------------------------------------- the Watcher's column
def _w(tmp_path, monkeypatch):
    monkeypatch.setenv("FLIGHT_WATCHER_DATA", str(tmp_path))
    monkeypatch.delenv("FLIGHT_WATCHER_INSTANCE", raising=False)
    (tmp_path / "options.json").write_text(json.dumps({"username": "u", "password": "p"}))
    sys.modules.pop("watcher", None)
    import watcher as W
    from store import Store
    W.S.clear()
    monkeypatch.setattr(W, "DB", Store(str(tmp_path / "t.db")))
    monkeypatch.setattr(W, "local_now", lambda: datetime(2026, 11, 2, 9, 0))
    monkeypatch.setattr(W, "row_date", lambda s, today=None: P.row_date(s, date(2026, 11, 2)))
    return W


def _month(mk, n, acts):
    y, m = int(mk[:4]), int(mk[5:])
    return {"month": mk, "days": [[(date(y, m, 1) + timedelta(days=i)).isoformat(), acts.get(i + 1, ""), ""]
                                  for i in range(n)], "items": [], "totals": {}}


def _line(W, months=("2026-10", "2026-11")):
    """13 h duties (06:00 to 19:00 block-in) on Nov 6, 7, 8 and 12."""
    W.S["schedule"] = {}
    for mk in months:
        W.S["schedule"][mk] = _month(mk, 31 if mk == "2026-10" else 30, {})
    if "2026-11" in W.S["schedule"]:
        W.S["schedule"]["2026-11"]["items"] = [{"trip": f"H10{d:02d}", "start": f"2026-11-{d:02d}",
                                               "end": f"2026-11-{d:02d}", "lay": ""} for d in (6, 7, 8, 12)]
    W.S["own_trips"] = {f"H10{d:02d}|2026-11-{d:02d}": {"report": "06:00", "last_arr": "19:00", "blk": "6:00"}
                        for d in (6, 7, 8, 12)}


ROW = {"pairing": "H9001", "start": "10Nov", "end": "10Nov", "days": "1", "report": "08:00", "arrive": "21:00",
       "blk": "6:00"}


def test_watcher_pot_row_reads_the_fdp_limit(tmp_path, monkeypatch):
    W = _w(tmp_path, monkeypatch)
    _line(W)
    row = dict(ROW)
    assert W.far_for(row) == "FDP 65h/168h"
    assert "FAR 117.23(c)(1)" in row["far_why"]
    # a swap that gives up the Nov 12 trip: 52 h of FDP, legal
    assert W.far_for(dict(ROW), exclude="H1012|2026-11-12") == "OK"


def test_watcher_unknowns_read_question_mark(tmp_path, monkeypatch):
    W = _w(tmp_path, monkeypatch)
    _line(W)
    row = dict(ROW, report="")
    assert W.far_for(row) == "?" and "not read yet" in row["far_why"]
    _line(W, months=("2026-11",))  # October not on file: the 672 h windows reach into it
    row = dict(ROW, start="02Nov", end="02Nov")
    assert W.far_for(row) == "?" and "not on file" in row["far_why"]
    _line(W)
    W.S["own_trips"].pop("H1008|2026-11-08")  # its times not read yet: whole days, a guess
    row = dict(ROW, start="09Nov", end="09Nov", report="10:00", arrive="14:00")
    assert W.far_for(row) == "?"


def test_watcher_uses_cached_or_package_duties(tmp_path, monkeypatch):
    """A 3-day pot row (Nov 14 08:00 to Nov 16 14:00, LAX layover) between 9 h and 13 h duties on Nov 12 and 18. As
    one 54 h span it may pass 60 h of FDP in 168 h ('?'); with its two duty periods, from the details cache (its
    pairing page) or else the bid period's package, it is 34 h: OK."""
    W = _w(tmp_path, monkeypatch)
    _line(W)
    W.S["schedule"]["2026-11"]["items"] = [{"trip": t, "start": f"2026-11-{d}", "end": f"2026-11-{d}", "lay": ""}
                                           for t, d in (("H1012", "12"), ("H1018", "18"))]
    W.S["own_trips"] = {"H1012|2026-11-12": {"report": "04:00", "last_arr": "13:00", "blk": "6:00"},
                        "H1018|2026-11-18": {"report": "06:00", "last_arr": "19:00", "blk": "6:00"}}
    duties = [{"d": 0, "dep": 540, "arr": 840, "stn": "LAX", "blk": 300},
              {"d": 2, "dep": 3420, "arr": 3720, "stn": "HNL", "blk": 300}]
    row = {"pairing": "H9002", "start": "14Nov", "end": "16Nov", "days": "3", "report": "08:00", "arrive": "14:00",
           "blk": "10:00"}
    r = dict(row)
    assert W.far_for(r) == "?" and "FAR 117.23(c)(1)" in r["far_why"]
    W.S["details"] = {"H9002|14Nov": {"duties": duties}}
    assert W.far_for(dict(row)) == "OK"
    W.S["details"] = {}
    W.DB.put("pkg_details:2026-11", {"H9002": {"report": "08:00", "block": "10:00", "rel_days": 3, "duties": duties}})
    assert W.far_for(dict(row)) == "OK"


def test_pot_details_keep_duties_off_the_published_row(tmp_path, monkeypatch):
    W = _w(tmp_path, monkeypatch)
    _line(W)
    page = ("<html><body>Check In: 08:00 Blk : 310 Pay : 600 Tafb : 1315 Crew: CA 10001 DOE, JANE FO OPEN "
            "Tu 101 HNL-OGG 0900 0945 0045 Tu 102 OGG-HNL 1100 1145 0045 Tu 103 HNL-LIH 1300 1340 0040 "
            "Tu 104 LIH-HNL 2000 2100 0100</body></html>")

    class Fl:
        def fetch(self, url):
            return page
    pot = {"H9001|10Nov": dict(ROW, report="", blk="")}
    W.pot_details(Fl(), pot)
    row = pot["H9001|10Nov"]
    assert "duties" not in row and W.S["details"]["H9001|10Nov"]["duties"]
    assert row["far"] == "FDP 65h/168h" and row["far_why"]


def test_far_why_stays_off_the_tradeboard_sensor(tmp_path, monkeypatch):
    """FW-0039 / FW-0060 review: the sensor rows carry the FAR column but not far_why (no card shows it yet, and it
    would cost rows under the 12 KB cap); far_for still sets it on the row it screens."""
    W = _w(tmp_path, monkeypatch)
    _line(W)
    sent = []
    monkeypatch.setattr(W, "pub", lambda t, p, retain=True: sent.append((t, p)))
    W.publish_tradeboard({"H9001|10Nov": dict(ROW)})
    rows = [p for t, p in sent if t == "tradeboard/state"][-1]["pairings"]
    assert rows[0]["far"] == "FDP 65h/168h" and "far_why" not in rows[0]
