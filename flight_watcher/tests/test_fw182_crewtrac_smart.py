"""1.8.2 (LIVE-8, S6): the CrewTrac check knows which copy is newer, and a bid month with no month type in smart.json
is said out loud.

LIVE-8: the check compared FW's line with Hark's once-a-day CrewTrac snapshot and never asked which one was newer.
After each December trade it read 'CrewTrac controls' for about 12.6 h, although FW was right and the snapshot was
older than the trade. Now a trip or a month whose FW copy (the schedule version that holds it as it is now) is newer
than the snapshot's pulled_at reads 'CrewTrac not updated yet (pulled HH:MM HST)': no cross, no 'CrewTrac controls',
no mismatch and no early read (1.8.2 trigger c). A snapshot newer than FW's copy keeps the mismatch (FW is stale, so
that month is read early).

S6: smart.json typed 2026-10 and 2026-11 only, so every December pickup's month rule was blank and nothing said so.
The Watcher never guesses a type: while a bid month it reads has none, its state note says so and the log says it
once a day.

Synthetic data only: made-up pairings H39xx (H3907 held twice, Nov 30 as November's carry-in and Dec 12 from a
trade), made-up crew, no real CrewTrac or FLICA pages."""
import json
import logging
import os
import shutil
import subprocess
from datetime import date, datetime, timezone

import pytest

import captures as CAPS
import crewtrac as CT
import smart as SM
import versions as VER
from test_fw181_pot_month import DEC, NOV, _check, _periods, at, page
from test_fw181_pot_month import _w as _pot_w
from test_fw182_sched_fresh import _lines, _tick
from test_fw182_sched_fresh import _w as _sched_w
from test_release_a_flica import mk, real_fl  # noqa: F401

HERE = os.path.dirname(os.path.abspath(__file__))
CARD = os.path.join(HERE, "..", "www", "flight-watcher-schedule-card.js")
PULLED = "2026-11-22T05:20:00-10:00"  # Hark's daily pull
OLD = "2026-11-13T19:00:00+00:00"  # the December award, long before the pull
BEFORE = "2026-11-22T15:00:00+00:00"  # 05:00 HST Nov 22, 20 min before the pull
TRADE = "2026-11-23T02:37:00+00:00"  # 16:37 HST Nov 22: the trade, after the pull
NOW = datetime(2026, 11, 23, 2, 46, tzinfo=timezone.utc)  # 16:46 HST, the first check after the trade


def _snap(pulled=PULLED, dec12=False, dec_credit="65:35"):
    """A compact snapshot as Hark hands it (card_view's shape): the Nov 30 carry-in and the Dec 6 trip; the Dec 12
    trip only once CrewTrac has the trade."""
    trips = [{"pairing": "H3907", "key": "H3907", "start": "2026-11-30", "end": "2026-12-02", "credit": "17:35",
              "block": "15:10"},
             {"pairing": "H3913", "key": "H3913", "start": "2026-12-06", "end": "2026-12-08", "credit": "21:00",
              "block": "18:30"}]
    if dec12:
        trips.append({"pairing": "H3907", "key": "H3907", "start": "2026-12-12", "end": "2026-12-14", "credit": "21:00",
                      "block": "18:40"})
    return {"version": 1, "pulled_at": pulled, "source": {}, "trips": trips,
            "months": {"2026-11": {"pay_report": {"as_of": "11/21", "totals": {"credit": "80:00"}}},
                       "2026-12": {"pay_report": {"as_of": "11/21", "totals": {"credit": dec_credit}}}}}


FW = {"H3907|2026-11-30": {"credit": "17:35", "blk": "15:10", "at": OLD},
      "H3913|2026-12-06": {"credit": "21:00", "blk": "18:30", "at": OLD},
      "H3907|2026-12-12": {"credit": "21:00", "blk": "18:40", "at": TRADE}}
WAIT = "CrewTrac not updated yet (pulled 05:20 HST)"


# ---------------------------------------------------------------- LIVE-8: crewtrac.py
def test_live8_a_trade_after_the_pull_reads_not_updated_yet_not_crewtrac_controls():
    r = CT.compare_trips(_snap(), FW, NOW)
    rows = {x["trip"] + "|" + x["start"]: x for x in r["rows"]}
    assert rows["H3907|2026-12-12"]["line"] == f"{WAIT}: no H3907 on 2026-12-12 in CrewTrac"
    assert rows["H3907|2026-12-12"]["ok"] is None and (r["mismatches"], r.get("waiting")) == (0, 1)
    assert rows["H3907|2026-11-30"]["ok"] is True  # the carry-in still matches
    assert rows["H3913|2026-12-06"]["ok"] is True
    line = CT.month_line(_snap(), "2026-12", "84:10", fw_at=TRADE)
    assert line == f"{WAIT}: Pay Report 65:35 credit (as of 11/21), FW 84:10"
    assert "✗" not in line and "CrewTrac controls" not in line
    # a trip FW's copy changed after the pull (its credit moved): the figures stay in the line, no cross
    one = CT.compare_trips(_snap(), {"H3913|2026-12-06": {"credit": "21:30", "blk": "18:30", "at": TRADE}}, NOW)
    assert one["rows"][0]["line"] == f"{WAIT}: CrewTrac 21:00, FW 21:30" and one["rows"][0]["ok"] is None
    # a match stays a tick whatever the times
    assert CT.month_line(_snap(dec_credit="84:10"), "2026-12", "84:10", fw_at=TRADE).endswith("✓")


def test_live8_a_snapshot_newer_than_fws_copy_keeps_the_mismatch():
    """FW's copy is older than the pull (or has no time): today's line, the cross and 'CrewTrac controls'."""
    fw = dict(FW, **{"H3907|2026-12-12": dict(FW["H3907|2026-12-12"], at=BEFORE)})
    r = CT.compare_trips(_snap(), fw, NOW)
    row = next(x for x in r["rows"] if x["start"] == "2026-12-12")
    assert row["line"] == "CrewTrac has no H3907 on 2026-12-12 ✗ (CrewTrac controls)" and row["ok"] is False
    assert (r["mismatches"], r.get("waiting")) == (1, 0)
    for at_ in (BEFORE, PULLED, None, "", "not a time"):
        assert CT.month_line(_snap(), "2026-12", "84:10", fw_at=at_).endswith("off by +18:35 (CrewTrac controls)")
    assert CT.month_line(_snap(), "2026-12", "84:10") == CT.month_line(_snap(), "2026-12", "84:10", fw_at=BEFORE)
    nofw = {k: {f: v for f, v in t.items() if f != "at"} for k, t in FW.items()}  # 1.7.22's input: no times
    assert CT.compare_trips(_snap(), nofw, NOW)["mismatches"] == 1
    assert not CT.newer(PULLED, _snap()) and CT.newer(TRADE, _snap()) and not CT.newer(TRADE, None)


def _node(js, tmp_path):
    src = open(CARD, encoding="utf-8").read()
    f = tmp_path / "t.mjs"
    f.write_text(src[:src.index("class FlightWatcherScheduleCard")].replace("customElements", "//") + "\n" + js)
    res = subprocess.run(["node", str(f)], capture_output=True, text=True, timeout=30)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_live8_card_and_crewtrac_py_agree(tmp_path):
    """The schedule card draws its own compare (fwCtTrip, fwCtMonth) from the check sensor's snapshot, whose fw_at
    carries FW's copy times; it says what crewtrac.py says."""
    now_ms = int(NOW.timestamp() * 1000)
    cases = [(k, t) for k, t in FW.items()] + [("H3913|2026-12-06", {"credit": "21:30", "blk": "18:30", "at": TRADE}),
                                               ("H3907|2026-12-12", {"credit": "21:00", "blk": "18:40", "at": BEFORE})]
    js = "const out = [];\n"
    for k, t in cases:
        s = dict(_snap(), fw_at={k: t["at"]})
        pid, _, st = k.partition("|")
        js += (f"out.push(fwCtTrip({json.dumps(s)}, {json.dumps(pid)}, {json.dumps(st)}, {json.dumps(t['credit'])}, "
               f"{json.dumps(t['blk'])}, {now_ms}));\n")
    mon = [(TRADE, "84:10", "65:35"), (BEFORE, "84:10", "65:35"), (TRADE, "84:10", "84:10"), (None, "84:10", "65:35")]
    for a, fc, cc in mon:
        s = dict(_snap(dec_credit=cc), fw_at={"2026-12": a} if a else {})
        js += f"out.push(fwCtMonth({json.dumps(s)}, '2026-12', {json.dumps(fc)}, {now_ms}));\n"
    js += "console.log(JSON.stringify(out.map((o) => [o.ok, o.line])));"
    got = _node(js, tmp_path)
    for (k, t), (ok, line) in zip(cases, got[:len(cases)]):
        r = CT.compare_trips(_snap(), {k: t}, NOW)["rows"][0]
        assert (ok, line) == (r["ok"], r["line"]), k
    for (a, fc, cc), (ok, line) in zip(mon, got[len(cases):]):
        want = CT.month_line(_snap(dec_credit=cc), "2026-12", fc, fw_at=a)
        assert line == want and ok == (None if want.startswith(WAIT) else want.endswith("✓"))
    assert got[2] == [None, f"{WAIT}: no H3907 on 2026-12-12 in CrewTrac"]


# ---------------------------------------------------------------- LIVE-8: the Watcher's check and trigger (c)
def _days(mon, n):
    return [[f"{mon}-{d:02d}", "", ""] for d in range(1, n + 1)]


def _trade_watcher(mk, monkeypatch):
    """Ryan's Nov 22 in small: the December award stored Nov 13 (11.001, 12.001), Hark's pull at 05:20 HST, a trade
    at 16:37 HST that adds H3907 Dec 12 (12.002). The Watcher has read FLICA's month list (1026, 1126, 1226)."""
    W, F = _sched_w(mk, t=at(2026, 11, 22, 4, 0))
    _tick(W, F)
    monkeypatch.setattr(W, "pkg_detail_for", lambda *a, **k: None)
    snap = {"v": _snap()}
    monkeypatch.setattr(W, "crewtrac_snapshot", lambda: snap["v"])
    W.S["own_trips"] = {"H3907|2026-11-30": {"credit": "17:35", "blk": "15:10", "seat": "FO"},
                        "H3913|2026-12-06": {"credit": "21:00", "blk": "18:30", "seat": "FO"}}
    nov = {"month": "2026-11", "updated": "Nov 13, 2026 09:00:00", "days": _days("2026-11", 30),
           "items": [{"trip": "H3907", "start": "2026-11-30", "end": "2026-12-02", "lay": "KIX"}],
           "totals": {"credit": "80:00"}}
    dec = {"month": "2026-12", "updated": "Nov 13, 2026 09:00:00", "days": _days("2026-12", 31),
           "items": [{"trip": "H3907", "start": "2026-11-30", "end": "2026-12-02", "lay": "KIX"},
                     {"trip": "H3913", "start": "2026-12-06", "end": "2026-12-08", "lay": "JFK"}],
           "totals": {"credit": "65:35"}}
    W.S["schedule"] = {"2026-11": nov, "2026-12": dec}
    assert VER.update(W.DB, W.S["schedule"], W.S["own_trips"], OLD) == [("2026-11", "11.001"), ("2026-12", "12.001")]
    W.S["own_trips"]["H3907|2026-12-12"] = {"credit": "21:00", "blk": "18:40", "seat": "FO"}
    dec["items"].append({"trip": "H3907", "start": "2026-12-12", "end": "2026-12-14", "lay": "JFK"})
    dec["totals"]["credit"] = "84:10"
    assert VER.update(W.DB, W.S["schedule"], W.S["own_trips"], TRADE) == [("2026-12", "12.002")]
    return W, F, snap


def test_live8_watcher_says_not_updated_yet_after_a_trade_and_never_reads_early(mk, caplog, monkeypatch):
    W, F, snap = _trade_watcher(mk, monkeypatch)
    W.CLOCK.t = at(2026, 11, 22, 16, 46)
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        W.crewtrac_check(NOW)
    p = W.MQ.last("flight_watcher/crewtrac_check")
    assert (p["status"], p["mismatches"], p.get("waiting")) == ("ok", 0, 2), p
    assert {(r["trip"], r["start"]): r["ok"] for r in p["rows"]} == {
        ("H3907", "2026-11-30"): True, ("H3913", "2026-12-06"): True, ("H3907", "2026-12-12"): None}
    assert [r["line"] for r in p["rows"] if r["ok"] is None] == [f"{WAIT}: no H3907 on 2026-12-12 in CrewTrac"]
    assert p["months"] == [{"month": "2026-11", "line": "CrewTrac Pay Report 80:00 credit (as of 11/21), FW 80:00 ✓",
                            "ok": True},
                           {"month": "2026-12", "line": f"{WAIT}: Pay Report 65:35 credit (as of 11/21), FW 84:10",
                            "ok": None}]
    assert "CrewTrac controls" not in json.dumps(p) and "\\u2717" not in json.dumps(p)
    assert p["snapshot"]["fw_at"] == {"H3907|2026-12-12": TRADE, "2026-12": TRADE}  # the card's own compare reads it
    assert not _lines(caplog, "schedule 2026-12: read early")
    assert "2026-12" not in (W.S.get("sched_trig") or {}).get("c", {})
    # Hark's next pull (05:20 HST Nov 23) still has no Dec 12 trip: now the snapshot is newer than FW's copy, so it is
    # a real mismatch, CrewTrac controls, and trigger (c) reads December early (FW may be the stale one)
    snap["v"] = _snap(pulled="2026-11-23T05:20:00-10:00")
    W.CLOCK.t = at(2026, 11, 23, 5, 30)
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        W.crewtrac_check(datetime.fromtimestamp(W.CLOCK.t, timezone.utc))
    p = W.MQ.last("flight_watcher/crewtrac_check")
    assert (p["status"], p["mismatches"], p.get("waiting")) == ("mismatch", 2, 0)
    assert [r["line"] for r in p["rows"] if r["ok"] is False] == [
        "CrewTrac has no H3907 on 2026-12-12 ✗ (CrewTrac controls)"]
    assert p["months"][1]["line"].endswith("off by +18:35 (CrewTrac controls)") and "fw_at" not in p["snapshot"]
    assert _lines(caplog, "schedule 2026-12: read early") == [
        "schedule 2026-12: read early (the CrewTrac check differs in December 2026)"]
    # CrewTrac caught up: all ticks, nothing waiting
    snap["v"] = _snap(pulled="2026-11-23T05:40:00-10:00", dec12=True, dec_credit="84:10")
    W.crewtrac_check(datetime.fromtimestamp(W.CLOCK.t + 1800, timezone.utc))
    p = W.MQ.last("flight_watcher/crewtrac_check")
    assert (p["status"], p["mismatches"], p.get("waiting")) == ("ok", 0, 0) and all(r["ok"] for r in p["rows"])


def test_live8_a_waiting_month_never_feeds_trigger_c_even_beside_a_real_mismatch(mk, caplog, monkeypatch):
    """A real mismatch in November (the current month, never read early) makes the status a mismatch, so trigger (c)
    runs: December's 'not updated yet' trip and month are no evidence for it."""
    W, F, snap = _trade_watcher(mk, monkeypatch)
    W.S["own_trips"]["H3907|2026-11-30"]["credit"] = "17:50"  # FW and CrewTrac differ on the carry-in, FW's copy older
    W.CLOCK.t = at(2026, 11, 22, 16, 46)
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        W.crewtrac_check(NOW)
    p = W.MQ.last("flight_watcher/crewtrac_check")
    assert (p["status"], p["mismatches"], p.get("waiting")) == ("mismatch", 1, 2)
    assert W.S["sched_trig"]["ct"] == PULLED and W.S["sched_trig"]["c"] == {}
    assert not _lines(caplog, "schedule 2026-")


def test_live8_versions_held_since():
    """When FW's copy took its current form: the oldest version of the newest unbroken run that holds the trip (listed,
    same block / credit / seat / times) or the month credit unchanged."""
    def v(at_, items, credit, trips):
        return {"at": at_, "items": [{"trip": t, "start": s} for t, s in items], "totals": {"credit": credit},
                "trips": trips}
    a = {"credit": "21:00", "blk": "18:30"}
    vers = [v("t1", [("H3913", "2026-12-06")], "65:35", {"H3913|2026-12-06": a}),
            v("t2", [("H3913", "2026-12-06")], "65:35", {"H3913|2026-12-06": a}),
            v("t3", [("H3913", "2026-12-06"), ("H3907", "2026-12-12")], "84:10",
              {"H3913|2026-12-06": a, "H3907|2026-12-12": {"credit": "21:00"}}),
            v("t4", [("H3913", "2026-12-06"), ("H3907", "2026-12-12")], "84:10",
              {"H3913|2026-12-06": dict(a, credit="21:30"), "H3907|2026-12-12": {"credit": "21:00"}})]
    assert VER.held_since(vers, "H3907|2026-12-12") == "t3" and VER.held_since(vers, "H3913|2026-12-06") == "t4"
    assert VER.held_since(vers) == "t3" and VER.held_since(vers[:2]) == "t1"
    assert VER.held_since(vers, "H3999|2026-12-20") == "" and VER.held_since([], "H3913|2026-12-06") == ""
    assert VER.held_since(None) == "" and VER.held_since([{"items": [], "totals": {}}]) == ""


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_live8_admin_card_says_not_updated_yet_in_the_tooltip_and_the_totals():
    """The schedule card on the admin's login: a trip and a month credit FW holds since after the pull read 'not updated
    yet' in the Pay-Gross tooltip and the totals line, with no cross; FW's copy older than the pull keeps the cross."""
    sync_api = pytest.importorskip("playwright.sync_api")
    from test_cards import _chromium
    from test_fw1720_pay_engine import DET, OT
    days = [[f"2026-11-{d:02d}", "", ""] for d in range(1, 31)]
    days[17] = ["2026-11-18", "H3906A", "JFK"]
    package = {"month": "2026-11", "source": "synthetic", "start": "2026-11-01", "end": "2026-11-30",
               "cols": ["id", "report", "dep", "release", "rel_days", "first_duty_min", "route", "credit", "tafb",
                        "days"],
               "rows": [["H3906", "14:45", "15:45", "15:10", 2, 960, "HNL-JFK-HNL", "21h00", "48h25", "18"]],
               "detail": {"H3906": DET}}
    sn = {"version": 1, "pulled_at": "2026-11-20T05:20:00-10:00", "trips": [],
          "months": {"2026-11": {"pay_report": {"as_of": "11/19", "totals": {"credit": "11:00"}}}}}

    def states(fw_at):
        s = dict(sn, fw_at={"H3906A|2026-11-18": fw_at, "2026-11": fw_at})
        return {"sensor.flight_watcher_schedule": {"state": "", "last_updated": "a", "attributes": {
                    "updated": "Nov 20, 2026", "months": {"2026-11": {
                        "items": [{"trip": "H3906A", "start": "2026-11-18", "end": "2026-11-21", "lay": "JFK"}],
                        "days": days, "totals": {"credit": "32:19", "block": "21:08"}, "updated": "Nov 20, 2026"}}}},
                "sensor.flight_watcher_own_trip_times": {"state": "1", "last_updated": "a",
                                                         "attributes": {"trips": {"H3906A|2026-11-18": dict(OT)}}},
                "input_number.flight_watcher_month_offset": {"state": "0", "last_updated": "a"},
                "input_number.flight_watcher_longevity_year": {"state": "12.0", "last_updated": "a", "attributes": {}},
                "input_text.flight_watcher_er_trips": {"state": "", "last_updated": "a", "attributes": {}},
                "sensor.flight_watcher_crewtrac_check": {"state": "ok", "last_updated": "a",
                                                         "attributes": {"snapshot": s}},
                "sensor.flight_watcher_state": {"state": "idle", "last_updated": "a", "attributes": {"role": "admin"}}}
    stub = ("window.fetch = async (u) => ({ok: String(u).includes('pairings_2026-11'), json: async () => ("
            + json.dumps(package) + ")});")
    pg_html = ("<!doctype html><html><body><script>customElements.define('ha-card', class extends HTMLElement {});"
               + stub + "</script><script>" + open(CARD, encoding="utf-8").read() + "</script></body></html>")
    js = """(h) => { const c = document.createElement('flight-watcher-schedule-card'); c.setConfig({});
      const hs = {states: h, user: {is_owner: true}, callService: async () => {}};
      document.body.appendChild(c); c.hass = hs;
      return new Promise((res) => setTimeout(() => { c.hass = {...hs};
        const r = c.shadowRoot, tr = [...r.querySelectorAll('tr[data-d]')].find((x) => x.dataset.d === '2026-11-18');
        const p = tr.querySelector('.pay');
        res({tot: (r.querySelector('.tot') || {}).textContent || '', info: p.dataset.info, cls: p.className});
      }, 400)); }"""
    got = {}
    with sync_api.sync_playwright() as p:
        b = _chromium(p)
        if not b:
            pytest.skip("no Chromium for Playwright")
        try:
            for name, fw_at in (("after", "2026-11-21T02:37:00+00:00"), ("before", "2026-11-20T15:00:00+00:00")):
                pg = b.new_page(viewport={"width": 1200, "height": 900})
                pg.clock.set_fixed_time("Fri 2026-11-20 6:30 PM EST (UTC-05:00)")
                pg.set_content(pg_html)
                got[name] = pg.evaluate(js, states(fw_at))
        finally:
            b.close()
    a, z = got["after"], got["before"]
    assert f"{WAIT}: no H3906A on 2026-11-18 in CrewTrac" in a["info"], a["info"]
    assert "CrewTrac controls" not in a["info"] and "ctbad" not in a["cls"]
    tot = " ".join(a["tot"].split())
    assert "not updated yet (pulled 05:20 HST)" in tot and "✗" not in tot and "Pay Report" not in tot, tot
    assert "CrewTrac has no H3906A on 2026-11-18 ✗ (CrewTrac controls)" in z["info"] and "ctbad" in z["cls"]
    assert "✗" in " ".join(z["tot"].split())


# ---------------------------------------------------------------- S6: a bid month with no month type
def _smart(path, types):
    path.write_text(json.dumps({"v": 1, "updated": "2026-10-18", "source": "synthetic", "month_types": types,
                                "min_days_off": 12}))


S6_LINE = ('smart.json has no month type for December 2026: its finds and pushes carry no month rule (the days off, '
           'conflict, rest and 672 checks) until "2026-12": "line" or "reserve" is added to smart.json (the Watcher '
           'never guesses a type)')


def test_s6_december_with_no_month_type_is_said_in_the_note_and_logged_once_a_day(mk, tmp_path, caplog, monkeypatch):
    """Ryan's Both: November and December pots are read; smart.json types November only (and October), so December
    finds carry no month rule. The state note says so while it lasts and the log once a day; the type is never
    guessed. Typed, the note goes."""
    f = tmp_path / "smart.json"
    _smart(f, {"2026-10": "reserve", "2026-11": "line"})
    W, fl, pages = _pot_w(mk, at(2026, 11, 24, 9, 0), mode="Both", pages={"003.152": page(NOV), "003.153": page(DEC)})
    _periods(W)
    monkeypatch.setattr(W, "SMART_FILE", str(f))
    cfg = SM.load(str(f))  # the gap itself: a December pickup has no month rule, a November one has
    assert SM.month_rule(date(2026, 12, 20), date(2026, 12, 21), "10:00", "Fits", "", {}, cfg) == ""
    assert SM.month_rule(date(2026, 11, 20), date(2026, 11, 21), "10:00", "Fits", "", {}, cfg) != ""
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        assert _check(W, fl)[1] == ["003.152", "003.153"]
        _check(W, fl)
    note = "smart.json has no month type for December 2026"
    assert note in W.health_note() and note in W.S.get("note", ""), W.S.get("note")
    assert note in W.MQ.last("flight_watcher/state_attr")["note"]
    assert len(_lines(caplog, note)) == 1  # once a day, not every check
    # 1.8.2 review (S6-logmask): the whole line as the add-on log shows it (caplog sees it after the admin's mask),
    # and the pilot's mask leaves it as it is too: no fixed word reads as a crew name or number
    assert _lines(caplog, note)[0] == S6_LINE, _lines(caplog, note)[0]
    assert CAPS.mask_crew(S6_LINE) == S6_LINE and CAPS.mask(S6_LINE, ()) == S6_LINE
    assert json.loads(f.read_text())["month_types"] == {"2026-10": "reserve", "2026-11": "line"}  # never written
    W.CLOCK.t = at(2026, 11, 25, 9, 0)  # the next day: said once more
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        _check(W, fl)
        _check(W, fl)
    assert len(_lines(caplog, note)) == 1
    _smart(f, {"2026-10": "reserve", "2026-11": "line", "2026-12": "line"})  # Hark adds it
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        _check(W, fl)
    assert "month type" not in W.health_note() and "month type" not in W.S.get("note", "")
    assert not _lines(caplog, "smart.json has")


def test_s6_this_month_pilot_across_dec_1_and_dec_2_and_no_note_without_types(mk, tmp_path, monkeypatch):
    """This month (a pilot's default): December is read from Dec 2 (Dec 1 is still November's bid period), so the note
    comes on Dec 2. A smart.json with no month types at all (none used) or no smart.json says nothing."""
    f = tmp_path / "smart.json"
    _smart(f, {"2026-10": "reserve", "2026-11": "line"})
    W, fl, pages = _pot_w(mk, at(2026, 11, 30, 23, 0), pages={"003.152": page(NOV), "003.153": page(DEC)})
    _periods(W)
    monkeypatch.setattr(W, "SMART_FILE", str(f))
    assert _check(W, fl)[1] == ["003.152"] and "month type" not in W.health_note()
    W.CLOCK.t = at(2026, 12, 1, 12, 0)
    assert _check(W, fl)[1] == ["003.152"] and "month type" not in W.health_note()
    W.CLOCK.t = at(2026, 12, 2, 0, 5)
    assert _check(W, fl)[1] == ["003.153"]
    assert "smart.json has no month type for December 2026" in W.health_note()
    _smart(f, {})
    _check(W, fl)
    assert "month type" not in W.health_note()
    monkeypatch.setattr(W, "SMART_FILE", str(tmp_path / "none.json"))
    _check(W, fl)
    assert "month type" not in W.health_note()


def test_live8_a_copy_ahead_of_its_versions_is_dated_by_the_read(mk, caplog, monkeypatch):
    """A version waits up to 2 h for a new trip's times (versions_check), so FW can show the trade before any version
    holds it: its copy then dates from the read that brought it (S ver_wait, else the month's read_at), not from the
    older version, and still reads 'not updated yet'. A wait that began before the pull keeps the mismatch."""
    W, F, snap = _trade_watcher(mk, monkeypatch)
    W.DB.put("sched_versions:2026-12", W.DB.get("sched_versions:2026-12")[:1])  # 12.002 not stored yet
    W.S["ver_wait"] = {"2026-12": at(2026, 11, 22, 16, 37)}
    W.CLOCK.t = at(2026, 11, 22, 16, 46)
    with caplog.at_level(logging.INFO, logger="flight_watcher"):
        W.crewtrac_check(NOW)
    p = W.MQ.last("flight_watcher/crewtrac_check")
    assert (p["status"], p["mismatches"], p.get("waiting")) == ("ok", 0, 2), p
    assert not _lines(caplog, "schedule 2026-12: read early")
    W.S["ver_wait"] = {}
    W.S["schedule"]["2026-12"]["read_at"] = TRADE  # no wait yet: the read that brought it
    W.crewtrac_check(NOW)
    assert W.MQ.last("flight_watcher/crewtrac_check")["waiting"] == 2
    W.S["ver_wait"] = {"2026-12": at(2026, 11, 22, 5, 0)}  # the wait began before the pull: FW may be the stale one
    W.crewtrac_check(NOW)
    p = W.MQ.last("flight_watcher/crewtrac_check")
    assert (p["status"], p["mismatches"], p.get("waiting")) == ("mismatch", 2, 0)
    # the Dec 6 trip is held unchanged since 12.001: its copy is old, so CrewTrac booking it differently stays a
    # mismatch however new December's read is; a change FW holds on it after the pull waits
    W.S["ver_wait"] = {"2026-12": at(2026, 11, 22, 16, 37)}
    s2 = _snap()
    s2["trips"][1]["credit"] = "21:30"
    snap["v"] = s2
    W.crewtrac_check(NOW)
    p = W.MQ.last("flight_watcher/crewtrac_check")
    assert [(r["trip"], r["start"], r["ok"]) for r in p["rows"] if not r["ok"]] == [
        ("H3913", "2026-12-06", False), ("H3907", "2026-12-12", None)]
    snap["v"] = _snap()
    W.S["own_trips"]["H3913|2026-12-06"]["credit"] = "21:30"
    W.crewtrac_check(NOW)
    p = W.MQ.last("flight_watcher/crewtrac_check")
    assert [(r["trip"], r["start"], r["ok"]) for r in p["rows"] if not r["ok"]] == [
        ("H3913", "2026-12-06", None), ("H3907", "2026-12-12", None)]


def test_live8_versions_held_since_with_the_form_fw_holds_now():
    vers = [{"at": "t1", "items": [{"trip": "H3913", "start": "2026-12-06"}], "totals": {"credit": "65:35"},
             "trips": {"H3913|2026-12-06": {"credit": "21:00", "blk": "18:30"}}}]
    rec = {"credit": "21:00", "blk": "18:30", "seat": "", "report": None}  # empty fields as own_trips keeps them
    assert VER.held_since(vers, "H3913|2026-12-06", cur=rec) == "t1"
    assert VER.held_since(vers, "H3913|2026-12-06", cur=dict(rec, credit="21:30")) is None  # ahead of the versions
    assert VER.held_since(vers, "H3907|2026-12-12", cur={"credit": "21:00"}) is None  # a trip no version lists yet
    assert VER.held_since(vers, cur="65:35") == "t1" and VER.held_since(vers, cur="84:10") is None
    assert VER.held_since([], "H3913|2026-12-06", cur=rec) == ""  # no version at all: no time


# ---------------------------------------------------------------- 1.8.2 review: the copy time keeps the read time
def test_live8_a_version_that_waited_keeps_the_read_time_so_a_mismatch_never_flips_to_waiting(mk, caplog,
                                                                                             monkeypatch):
    """1.8.2 review (LIVE8-wait-flip): FW reads the trade at 04:05 HST and its version waits for the new trip's times
    (ver_wait 04:05); Hark pulls at 05:20, after FW's read, without the trade: a real mismatch (CrewTrac controls,
    trigger c reads December early). The wait ends at 06:05 and 12.002 is stored then: nothing changed at FLICA or
    CrewTrac, so the verdict stays a mismatch (the version keeps the read time, seen_at) and never reads 'not updated
    yet' until the next pull."""
    W, F, snap = _trade_watcher(mk, monkeypatch)
    monkeypatch.setattr(W, "now_iso", lambda: datetime.fromtimestamp(W.CLOCK.t, timezone.utc).isoformat())
    W.DB.put("sched_versions:2026-12", W.DB.get("sched_versions:2026-12")[:1])  # 12.002 not stored yet
    W.S["ver_wait"] = {"2026-12": at(2026, 11, 22, 4, 5)}
    snap["v"] = _snap(pulled="2026-11-22T05:20:00-10:00")
    W.CLOCK.t = at(2026, 11, 22, 5, 30)
    W.crewtrac_check(datetime.fromtimestamp(W.CLOCK.t, timezone.utc))
    p = W.MQ.last("flight_watcher/crewtrac_check")
    assert (p["status"], p["mismatches"], p.get("waiting")) == ("mismatch", 2, 0), p
    W.CLOCK.t = at(2026, 11, 22, 6, 5)  # the wait ends (the trip's times are in): 12.002 is stored now
    W.versions_check()
    vers = W.DB.get("sched_versions:2026-12")
    assert [v["ver"] for v in vers] == ["12.001", "12.002"] and "2026-12" not in (W.S.get("ver_wait") or {})
    assert vers[1]["seen_at"] == "2026-11-22T14:05:00+00:00" and vers[1]["at"] == "2026-11-22T16:05:00+00:00"
    W.CLOCK.t = at(2026, 11, 22, 6, 10)
    W.crewtrac_check(datetime.fromtimestamp(W.CLOCK.t, timezone.utc))
    p = W.MQ.last("flight_watcher/crewtrac_check")
    assert (p["status"], p["mismatches"], p.get("waiting")) == ("mismatch", 2, 0), p
    assert [r["line"] for r in p["rows"] if r["ok"] is False] == [
        "CrewTrac has no H3907 on 2026-12-12 ✗ (CrewTrac controls)"]
    assert "fw_at" not in p["snapshot"]
    # a version made with no wait keeps its one time (no seen_at); a pull before FW's 04:05 read still reads 'not
    # updated yet' (FW's copy is the newer one)
    assert "seen_at" not in vers[0]
    snap["v"] = _snap(pulled="2026-11-22T04:00:00-10:00")
    W.crewtrac_check(datetime.fromtimestamp(W.CLOCK.t, timezone.utc))
    p = W.MQ.last("flight_watcher/crewtrac_check")
    assert (p["status"], p["mismatches"], p.get("waiting")) == ("ok", 0, 2), p


def test_live8_an_award_put_first_later_never_dates_fws_copy_by_the_upload(mk, caplog, monkeypatch):
    """1.8.2 review (LIVE8-award-order): the PBS award becomes version .001 when its upload is processed, which can be
    after FLICA versions on file. FW's copy of a month credit (or a trip) unchanged since the award dates from FW's
    first read of it, not from the upload, so a pull between the read and the upload keeps a real mismatch."""
    flica = {"at": OLD, "items": [{"trip": "H3913", "start": "2026-12-06"}], "totals": {"credit": "65:35"},
             "trips": {"H3913|2026-12-06": {"credit": "21:00", "blk": "18:30"}}}
    award = dict(flica, at="2026-11-24T20:00:00+00:00", award=True)
    vers = [award, flica]
    assert VER.held_since(vers, cur="65:35") == OLD
    assert VER.held_since(vers, "H3913|2026-12-06", cur={"credit": "21:00", "blk": "18:30"}) == OLD
    assert not CT.newer(VER.held_since(vers, cur="65:35"), _snap(pulled="2026-11-24T05:20:00-10:00"))
    # an older award (uploaded before FW's first read) dates it, as before; a later run start still wins
    assert VER.held_since([dict(award, at="2026-11-10T20:00:00+00:00"), flica], cur="65:35") == \
        "2026-11-10T20:00:00+00:00"
    later = dict(flica, at="2026-11-25T01:00:00+00:00", totals={"credit": "70:00"})
    assert VER.held_since([award, flica, later], cur="70:00") == "2026-11-25T01:00:00+00:00"
    # the Watcher: the award processed now (Nov 24 10:00 HST) after Hark's 05:20 pull; FLICA's 12.001 is Nov 13
    W, F, snap = _trade_watcher(mk, monkeypatch)
    W.DB.put("sched_versions:2026-12", W.DB.get("sched_versions:2026-12")[:1])
    dec = W.S["schedule"]["2026-12"]
    dec["items"].pop()
    dec["totals"]["credit"] = "65:35"
    W.S["own_trips"].pop("H3907|2026-12-12")
    VER.set_award(W.DB, "2026-12", {"items": dec["items"], "days": dec["days"], "totals": {"credit": "65:35"},
                                    "trips": VER.trips_of(dec["items"], W.S["own_trips"])}, "2026-11-24T20:00:00+00:00")
    assert [v.get("award", False) for v in W.DB.get("sched_versions:2026-12")] == [True, False]
    snap["v"] = _snap(pulled="2026-11-24T05:20:00-10:00", dec_credit="60:00")
    W.CLOCK.t = at(2026, 11, 24, 10, 30)
    W.crewtrac_check(datetime.fromtimestamp(W.CLOCK.t, timezone.utc))
    p = W.MQ.last("flight_watcher/crewtrac_check")
    assert p["months"][1]["ok"] is False and p["months"][1]["line"].endswith("(CrewTrac controls)"), p["months"]
    assert (p["status"], p.get("waiting")) == ("mismatch", 0) and "fw_at" not in p["snapshot"]
