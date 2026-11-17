"""1.7.11: FW-0080 and FW-0079 (Ryan, Nov 17, 2026: "Fix the crew column and totals too", scope "Everywhere"). Both
were seen in a pilot's screenshot (FW-0076, a report only); built as written in the spec. Synthetic pilots and pairings
only (Roe, Rick 10999; Doe, Jane; H96xx), no FLICA load.

FW-0080 (PWA 4.A: a segment pays on the date it originates): FLICA totals the bid period, never the calendar month.
December 2026 runs Dec 2 to Dec 31, November Nov 1 to Dec 1 (its package days read "D1"). A made-up trip Dec 1 to 3:
duty 1 on Dec 1 (HNL-LAX, block 5:23, TCRD 5:23), duty 2 on Dec 3 (block 5:52, TCRD 6:39), trip credit 15:00 (rig),
block 11:15. December counts duty 2, 6:39 / 5:52, as FLICA's December totals do; November the rest, 8:21 / 5:23
(15:00 - 6:39: the rig and minimums stay with the bid period of the trip's first day), so the two add up to the trip.
Another pilot's month (pilot_price), the month rebuilt from crew lists (pilot_pay_line), Ryan's own month (the
schedule card's figs and price) and the versions (pilotver file; versions._split for a PAYP) all count it this way.

FW-0079: at 390 px the pilot card's Crew column gives way to a crew list under the grid (one line a pairing, each pilot
a no-wrap span), so the grid fits its box; at 1024 px the column is back and the list hidden."""
import json
import os
import re
import shutil
import subprocess

import pytest

import cards
import pay as PAY
import versions as VER
from pot import PAIRING_RE
from test_crew_index import COLS, ROE, W, _sen  # noqa: F401
from test_release_a_schedule_card import _src, _states

HERE = os.path.dirname(os.path.abspath(__file__))
SHOTS = os.environ.get("FW_1711_SHOTS", "")
DUTIES = [{"d": 0, "dep": 1297, "arr": 1620, "stn": "LAX", "blk": 323}, {"d": 2, "dep": 3280, "arr": 3679, "stn": "HNL", "blk": 352}]
TCRD = [dict(d, tcrd=t) for d, t in zip(DUTIES, ("5h23", "6h39"))]


def _leg(day, flt, a, b, dep, arr, blk, sg):
    return [day, "", flt, a, b, dep, arr, blk, sg, "", "332"]


DETAIL = {"H9635": {"eq": "332", "crew": "CA01FO01", "rept": "20:37", "tot": {"block": "11h15", "credit": "15h00", "rig": "2h58"},
                    "duties": [{"legs": [_leg("1", "9001", "HNL", "LAX", "21:37", "05:00", "5h23", "5h23")], "rept": "20:37",
                                "dend": "05:15", "tblk": "5h23", "tcrd": "5h23", "duty": "8h38", "layo": "25h25", "stn": "LAX",
                                "tdhd": "", "fdp": "8h23"},
                               {"legs": [_leg("3", "9002", "LAX", "HNL", "08:40", "11:32", "5h52", "6h39")], "rept": "07:40",
                                "dend": "11:47", "tblk": "5h52", "tcrd": "6h39", "duty": "7h07", "layo": "", "stn": "HNL",
                                "tdhd": "", "fdp": "6h52"}]},
          # H9640 Nov 30 to Dec 3: duties Nov 30, Dec 2 and Dec 3 (a trip from before December's grid, carried into it)
          "H9640": {"eq": "332", "crew": "CA01FO01", "rept": "20:40", "tot": {"block": "14h00", "credit": "18h00"},
                    "duties": [{"legs": [], "tcrd": "5h30", "tblk": "5h30", "stn": "SEA"},
                               {"legs": [], "tcrd": "5h00", "tblk": "5h00", "stn": "LAX"},
                               {"legs": [], "tcrd": "3h30", "tblk": "3h30", "stn": "HNL"}]}}
H9640 = [{"d": 0, "dep": 1300, "arr": 1630, "stn": "SEA", "blk": 330}, {"d": 2, "dep": 3480, "arr": 3780, "stn": "LAX", "blk": 300},
         {"d": 3, "dep": 4800, "arr": 5010, "stn": "HNL", "blk": 210}]


def _row(pid, days, credit, block, route="HNL-LAX-HNL"):
    return [pid, "20:37", "21:37", "06:00", 2, 323, route, credit, "57h00", days, block, "CA01FO01"]


def _pkg(www, month, start, end, rows, detail):
    www.mkdir(parents=True, exist_ok=True)
    (www / f"pairings_{month}.json").write_text(json.dumps({"month": month, "source": "synthetic", "start": start, "end": end,
                                                             "cols": COLS, "rows": rows, "dv": 2, "detail": detail}))


def _setup(W, tmp_path, monkeypatch, tcrd=True):  # noqa: F811
    www = tmp_path / "www"
    _pkg(www, "2026-11", "2026-11-01", "2026-12-01", [_row("H9635", "D1", "15h00", "11:15"), _row("H9640", "30", "18h00", "14:00")],
         DETAIL if tcrd else {})
    _pkg(www, "2026-12", "2026-12-02", "2026-12-31", [_row("H9656", "5", "15h00", "11:15", "HNL-SEA-HNL")], {})
    monkeypatch.setattr(W, "UPLOADS_SHARED", _sen(tmp_path, {"10999": ROE}))
    monkeypatch.setattr(W, "ha_state", lambda e: None)
    W.DB.put("pkg_details:2026-11", {"H9635": {"credit": "15:00", "block": "11:15", "lay": "LAX", "route": "HNL-LAX-HNL", "duties": DUTIES},
                                     "H9640": {"credit": "18:00", "block": "14:00", "lay": "SEA", "route": "HNL-SEA-LAX-HNL", "duties": H9640}})


H9635_ITEM = {"trip": "H9635", "start": "2026-12-01", "end": "2026-12-03", "lay": "LAX", "credit": "15:00", "blk": "11:15", "seat": "FO", "n": 2}
DEC_ITEMS = [H9635_ITEM, {"trip": "SCR", "start": "2026-12-04", "end": "2026-12-19", "lay": ""},
             {"trip": "GDO", "start": "2026-12-20", "end": "2026-12-23", "lay": ""}]
FO9 = PAY.rate_for(9, "2026-12-01")  # Roe, Rick: DOH 2018-10-03, year 9, FO (PWA 3.D.6)


# ---------------------------------------------------------------- the rule (pay.py, the card's fwSplit)
def test_each_duty_counts_in_the_bid_period_of_its_hst_departure_date():
    dec = PAY.period_share("2026-12-01", "2026-12-02", "2026-12-31", TCRD, "15:00", "11:15")
    nov = PAY.period_share("2026-12-01", "2026-11-01", "2026-12-01", TCRD, "15:00", "11:15")
    assert (dec["credit"], dec["blk"], dec["out_credit"], dec["out_blk"], dec["side"], dec["est"]) == ("6:39", "5:52", "8:21", "5:23", "before", False)
    assert (nov["credit"], nov["blk"], nov["out_credit"], nov["out_blk"], nov["side"], nov["est"]) == ("8:21", "5:23", "6:39", "5:52", "after", False)
    assert PAY.mins(dec["credit"]) + PAY.mins(nov["credit"]) == 15 * 60 and PAY.mins(dec["blk"]) + PAY.mins(nov["blk"]) == 675
    assert dec["in"] and nov["in"] and not dec["whole"] and not nov["whole"]
    # no TCRD on file: the block share, an estimate (15:00 x 352 / 675 = 7:49 in December), still adding up
    est = PAY.period_share("2026-12-01", "2026-12-02", "2026-12-31", DUTIES, "15:00", "11:15")
    assert (est["credit"], est["blk"], est["out_credit"], est["est"]) == ("7:49", "5:52", "7:11", True)
    # no duty times: the whole trip pays in the bid period of its first day
    none = PAY.period_share("2026-12-01", "2026-12-02", "2026-12-31", [], "15:00", "11:15")
    assert (none["in"], none["placed"], none["credit"], none["out_credit"], none["side"]) == (False, False, "0:00", "15:00", "before")
    assert PAY.period_share("2026-12-01", "2026-11-01", "2026-12-01", [], "15:00", "11:15")["whole"] is True
    # a duty's date is its HST departure (dep minutes from 00:00 HST of the first day), never a weekday field
    late = [{"dep": 2 * 1440 - 1, "blk": 300, "tcrd": "5h00"}, {"dep": 2 * 1440, "blk": 300, "tcrd": "5h00"}]
    assert PAY.duty_dates("2026-12-01", late) == [("2026-12-02", 300, 300), ("2026-12-03", 300, 300)]


CASES = [("2026-12-01", "2026-12-02", "2026-12-31", TCRD, 15.0, 11.25), ("2026-12-01", "2026-11-01", "2026-12-01", TCRD, 15.0, 11.25),
         ("2026-12-01", "2026-12-02", "2026-12-31", DUTIES, 15.0, 11.25), ("2026-11-30", "2026-12-02", "2026-12-31",
         [dict(d, tcrd=t) for d, t in zip(H9640, ("5h30", "5h00", "3h30"))], 18.0, 14.0),
         ("2026-11-30", "2026-11-01", "2026-12-01", H9640, 18.0, None), ("2026-12-05", "2026-12-02", "2026-12-31", TCRD, 15.0, 11.25),
         ("2026-11-29", "2026-12-02", "2026-12-31", [{"dep": 30, "blk": 333}], 7.5, 5.55), ("2026-12-01", "2026-12-02", "2026-12-31", [], 15.0, 11.25)]


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_the_schedule_cards_split_is_the_watchers(tmp_path):
    """fwSplit (Ryan's schedule card) and pay.split_by_period / period_share (the Watcher, the pilot card's figures) give
    the same part for each case, minute for minute."""
    src = open(os.path.join(HERE, "..", "www", "flight-watcher-schedule-card.js"), encoding="utf-8").read()
    head = src[:src.index("class FlightWatcherScheduleCard")]
    js = head.replace("customElements", "//") + f"\nconsole.log(JSON.stringify({json.dumps(CASES)}.map((c) => fwSplit(c[0], c[3], c[1], c[2], c[4], c[5]))));"
    f = tmp_path / "split.js"
    f.write_text(js)
    out = subprocess.run(["node", str(f)], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout.strip().splitlines()[-1])
    for (st, a, b, du, cr, bl), js_sp in zip(CASES, got):
        py = PAY.period_share(st, a, b, du, cr, bl)
        if not py["placed"]:
            assert js_sp is None, (st, js_sp)
            continue
        assert (js_sp["in"], js_sp["whole"], js_sp["side"], js_sp["est"]) == (py["in"], py["whole"], py["side"], py["est"]), (st, js_sp, py)
        assert (PAY.hm(js_sp["cr"] / 60), PAY.hm(js_sp["bl"] / 60) if js_sp["bl"] is not None else "") == (py["credit"], py["blk"]), (st, js_sp, py)


# ---------------------------------------------------------------- another pilot's month (pilot_price)
def test_another_pilots_december_and_november_match_flica(W, tmp_path, monkeypatch):  # noqa: F811
    _setup(W, tmp_path, monkeypatch)
    dec, info = W.pilot_price(DEC_ITEMS, "10999", "Roe, Rick", "2026-12", "2026-12-02", "2026-12-31", None, 12,
                              {"block": "5:52", "credit": "6:39", "days_off": 12})
    assert (dec["trips"], dec["credit"], dec["block"], dec["soft"]) == (1, "6:39", "5:52", "0:47")  # FLICA's December
    sp = info["H9635|2026-12-01"]["split"]
    assert {k: sp[k] for k in ("credit", "blk", "out_credit", "out_blk", "side", "other", "edge", "est", "none")} == {
        "credit": "6:39", "blk": "5:52", "out_credit": "8:21", "out_blk": "5:23", "side": "before", "other": "2026-11",
        "edge": "2026-12-02", "est": False, "none": False}
    assert info["H9635|2026-12-01"]["gross"] == pytest.approx(round((6 + 39 / 60) * FO9, 2))
    assert dec["period"] == {"from": "2026-12-02", "to": "2026-12-31", "src": "package"}
    nov, ninfo = W.pilot_price(DEC_ITEMS, "10999", "Roe, Rick", "2026-11", "2026-11-01", "2026-12-01", None, 4)
    assert (nov["trips"], nov["credit"], nov["block"]) == (1, "8:21", "5:23")  # FLICA's November holds the rest
    nsp = ninfo["H9635|2026-12-01"]["split"]
    assert (nsp["out_credit"], nsp["out_blk"], nsp["side"], nsp["other"], nsp["edge"]) == ("6:39", "5:52", "after", "2026-12", "2026-12-01")
    assert dec["gross"] + nov["gross"] == pytest.approx(15 * FO9, abs=0.02)  # the trip's pay, once


def test_no_tcrd_falls_back_to_the_block_share_an_estimate(W, tmp_path, monkeypatch):  # noqa: F811
    _setup(W, tmp_path, monkeypatch, tcrd=False)
    dec, info = W.pilot_price(DEC_ITEMS, "10999", "Roe, Rick", "2026-12", "2026-12-02", "2026-12-31", None, 12)
    sp = info["H9635|2026-12-01"]["split"]
    assert (dec["credit"], dec["block"], sp["credit"], sp["out_credit"], sp["est"]) == ("7:49", "5:52", "7:49", "7:11", True)
    # the package detail with a different number of duties is never paired by index: the block share again
    bad = {"H9635": dict(DETAIL["H9635"], duties=DETAIL["H9635"]["duties"][:1])}
    _pkg(tmp_path / "www", "2026-11", "2026-11-01", "2026-12-01", [_row("H9635", "D1", "15h00", "11:15")], bad)
    W._DETAIL_CACHE.clear()
    _, info = W.pilot_price(DEC_ITEMS, "10999", "Roe, Rick", "2026-12", "2026-12-02", "2026-12-31", None, 12)
    assert info["H9635|2026-12-01"]["split"]["est"] is True


def test_a_vac_day_on_dec_1_counts_in_november(W, tmp_path, monkeypatch):  # noqa: F811
    _setup(W, tmp_path, monkeypatch)
    vac = [{"trip": "VAC", "start": "2026-11-30", "end": "2026-12-01", "lay": ""}, {"trip": "VAC", "start": "2026-12-02", "end": "2026-12-02", "lay": ""}]
    nov, _ = W.pilot_price(vac, "10999", "Roe, Rick", "2026-11", "2026-11-01", "2026-12-01", None, 4)
    dec, _ = W.pilot_price(vac, "10999", "Roe, Rick", "2026-12", "2026-12-02", "2026-12-31", None, 12)
    assert (nov["vac_days"], nov["vac"], nov["credit"]) == (2, "8:00", "8:00")  # Nov 30 and Dec 1 (PWA 6.J.1.c, 4:00 a day)
    assert (dec["vac_days"], dec["vac"]) == (1, "4:00")  # Dec 2 only
    # a PAYP over Dec 1 only is November's (its credit FLICA's November less the rest), not December's
    pp = [{"trip": "PAYP", "start": "2026-12-01", "end": "2026-12-01", "lay": ""}]
    assert W.pilot_price(pp, "10999", "Roe, Rick", "2026-11", "2026-11-01", "2026-12-01", None, 4, {"credit": "5:00"})[0]["payp"] == "5:00"
    assert "payp" not in W.pilot_price(pp, "10999", "Roe, Rick", "2026-12", "2026-12-02", "2026-12-31", None, 12, {"credit": "5:00"})[0]


def test_a_trip_from_before_the_grid_counts_its_part(W, tmp_path, monkeypatch):  # noqa: F811
    """H9640 Nov 30 to Dec 3 starts before December's grid (FLICA's first row is Dec 1), so FLICA's page has no item for
    it; its duties of Dec 2 and 3 pay in December (TCRD 5:00 + 3:30). From the crew index, only while FLICA's grid shows
    its days free with a layover cell (a trip in progress, not one dropped since)."""
    _setup(W, tmp_path, monkeypatch)
    recon = [{"pairing": "H9640", "start": "2026-11-30", "end": "2026-12-03", "credit": "18:00", "blk": "14:00", "seat": "FO", "n": 2}]
    days = [["2026-12-01", "", "SEA"], ["2026-12-02", "", "LAX"], ["2026-12-03", "", "HNL"]] + [[f"2026-12-{d:02d}", "", ""] for d in range(4, 32)]
    dec, info = W.pilot_price([], "10999", "Roe, Rick", "2026-12", "2026-12-02", "2026-12-31", recon, 12, None, days)
    assert (dec["trips"], dec["credit"], dec["block"]) == (1, "8:30", "8:30")
    assert dec["carry"] == [{"pairing": "H9640", "start": "2026-11-30", "credit": "8:30", "blk": "8:30", "all_credit": "18:00",
                             "all_blk": "14:00", "est": False, "gross": pytest.approx(round(8.5 * PAY.rate_for(9, "2026-11-30"), 2))}]
    assert info["H9640|2026-11-30"]["split"]["side"] == "before"
    for d, code, lay in ((1, "", ""), (2, "SCR", "")):  # a day off, or another code, on its days: never counted
        other = [list(x) for x in days]
        other[d - 1] = [f"2026-12-{d:02d}", code, lay]
        got, _ = W.pilot_price([], "10999", "Roe, Rick", "2026-12", "2026-12-02", "2026-12-31", recon, 12, None, other)
        assert got["trips"] == 0 and "carry" not in got
    assert "carry" not in W.pilot_price([], "10999", "Roe, Rick", "2026-12", "2026-12-02", "2026-12-31", recon, 12)[0]  # no grid


def test_the_versions_file_prices_it_the_same(W, tmp_path, monkeypatch):  # noqa: F811
    _setup(W, tmp_path, monkeypatch)
    days = [["2026-12-01", "H9635", "LAX"], ["2026-12-02", "", "-"], ["2026-12-03", "", "HNL"]] + [
        [f"2026-12-{d:02d}", "SCR" if d < 20 else "", ""] for d in range(4, 32)]
    sched = {"month": "2026-12", "updated": "Nov 17, 2026 03:16", "days": days, "items": DEC_ITEMS,
             "totals": {"block": "5:52", "credit": "6:39", "days_off": 12}}
    first, start, end = W.CI.grid_range(W.CARD_PAIRINGS, "2026-12")
    assert (first, start, end) == ("2026-12-01", "2026-12-02", "2026-12-31")
    assert W.PV.capture_lookup(W.DB, "10999", "Roe, Rick", sched, W.now_iso(), (first, end))
    W.pub_pilot({"emp": "10999", "name": "Roe, Rick", "status": "ok", **sched})
    p = [p for t, p in W.SENT if t == "pilot_schedule"][-1]
    assert (p["items_pay"]["credit"], p["items_pay"]["block"]) == ("6:39", "5:52")
    live = {it["trip"]: it for it in p["items"]}
    assert live["H9635"]["split"]["credit"] == "6:39"
    rec = json.loads((tmp_path / "www" / f"pilotver_{p['versions_file_key']}.json").read_text())["10999"]["months"]["2026-12"][-1]
    ver = {it["trip"]: it for it in rec["items"]}
    assert (rec["pay"]["credit"], rec["pay"]["block"], rec["pay"]["period"]["from"]) == ("6:39", "5:52", "2026-12-02")
    assert ver["H9635"]["split"]["credit"] == "6:39" and ver["H9635"]["gross"] == pytest.approx(live["H9635"]["gross"])


def test_the_rebuilt_month_splits_the_same(W, tmp_path, monkeypatch):  # noqa: F811
    """The month rebuilt from crew lists (pilot_pay_line): the same trip counts its December part there too."""
    _setup(W, tmp_path, monkeypatch)
    trips = [{"pairing": "H9635", "start": "2026-12-01", "end": "2026-12-03", "credit": "15:00", "blk": "11:15", "seat": "FO", "n": 2,
              "checked_at": "2026-11-17T09:00:00"}]
    line = W.pilot_pay_line(trips, "10999", "Roe, Rick", "2026-12-02", "2026-12-31", "2026-12")
    assert (line["trips"], line["credit"], line["block"]) == (1, "6:39", "5:52") and trips[0]["split"]["out_credit"] == "8:21"
    assert trips[0]["gross"] == pytest.approx(round((6 + 39 / 60) * FO9, 2)) and trips[0]["credit"] == "15:00"  # the record stays whole
    nov = W.pilot_pay_line(trips, "10999", "Roe, Rick", "2026-11-01", "2026-12-01", "2026-11")
    assert (nov["credit"], nov["block"]) == ("8:21", "5:23")


def test_bid_bounds_and_the_payp_split_by_bid_period(W, tmp_path, monkeypatch):  # noqa: F811
    _setup(W, tmp_path, monkeypatch)
    assert W.bid_bounds("2026-12") == ("2026-12-02", "2026-12-31", "package")
    assert W.bid_bounds("2026-11") == ("2026-11-01", "2026-12-01", "package")
    assert W.bid_bounds("2027-03") == ("2027-03-01", "2027-03-31", "calendar")  # nothing on file: the calendar month
    assert W.bid_period_key("2026-12-01") == "2026-11" and W.bid_period_key("2026-12-02") == "2026-12"
    # Ryan's own trip H9635 removed for a PAYP over its days: its kept credit splits by bid period with its TCRD
    own = {"H9635|2026-12-01": {"blk": "11:15", "credit": "15:00", "seat": "FO", "duties": DUTIES}}
    items = [{"trip": "PAYP", "start": "2026-12-01", "end": "2026-12-03", "lay": ""}]
    got = VER.payp_entries(items, own, lambda mk: [], PAIRING_RE.match, W.bid_period_key, W.payp_tcrd)
    assert got["PAYP|2026-12-01"]["split"] == {"2026-11": "8:21", "2026-12": "6:39"}
    # without the bid period (no pairing files and no schedule page): the calendar month, as before
    cal = VER.payp_entries(items, own, lambda mk: [], PAIRING_RE.match)
    assert cal["PAYP|2026-12-01"]["credit"] == "15:00" and "split" not in cal["PAYP|2026-12-01"]


def test_legs_place_each_duty_on_its_hst_departure_date(W):  # noqa: F811
    """A leg out of LAX at 00:30 local on a Wednesday departs 22:30 HST on Tuesday (pot.leg_shift)."""
    legs = [{"dow": "TU", "route": "HNL-LAX", "dep": "0800", "blk": "0530"}, {"dow": "WE", "route": "LAX-HNL", "dep": "0030", "blk": "0545"}]
    assert W._legs_duties("2026-12-01", legs) == [{"dep": 480, "blk": 330}, {"dep": 1440 + 30 - 120, "blk": 345}]
    assert PAY.duty_dates("2026-12-01", W._legs_duties("2026-12-01", legs))[1][0] == "2026-12-01"
    assert W._legs_duties("2026-12-01", [{"dow": "XX", "blk": "0530"}]) == []


# ---------------------------------------------------------------- Ryan's own month (the schedule card)
OWN_T = {"H9635|2026-12-01": {"blk": "11:15", "credit": "15:00", "soft": "3:45", "seat": "FO", "report": "20:37", "last_arr": "11:32",
                              "duties": [dict(d, dep_l="21:37", arr_l="05:00") for d in DUTIES]}}


def _month(month, first, last, rows, totals):
    from datetime import date, timedelta
    a, b = date.fromisoformat(first), date.fromisoformat(last)
    at = {d: (t, lay) for d, t, lay in rows}
    days = [[(a + timedelta(days=k)).isoformat(), *at.get((a + timedelta(days=k)).isoformat(), ("", ""))] for k in range((b - a).days + 1)]
    from pot import schedule_items
    return {"items": schedule_items(days), "days": days, "totals": totals, "updated": "Nov 17, 2026"}


H9635_DAYS = [("2026-12-01", "H9635", "LAX"), ("2026-12-02", "", "-"), ("2026-12-03", "", "HNL")]


def _own_states(offset, dec_rows=H9635_DAYS, nov_rows=H9635_DAYS, nov_tot=None, dec_tot=None, versions=False):
    nov = _month("2026-11", "2026-11-01", "2026-12-03", nov_rows, nov_tot or {"block": "5:23", "credit": "8:21", "days_off": 20})
    dec = _month("2026-12", "2026-12-01", "2026-12-31", dec_rows, dec_tot or {"block": "5:52", "credit": "6:39", "days_off": 12})
    vers = {}
    if versions:
        v = lambda n: {"ver": f"12.00{n}", "n": n, "at": "2026-11-1%dT01:00:00+00:00" % n, "updated": "x", "items": dec["items"],  # noqa: E731
                       "days": dec["days"], "totals": dec["totals"], "trips": OWN_T, "changes": []}
        vers = {"2026-12": {"count": 2, "current": "12.002", "awarded": "12.001", "versions": [v(1), v(2)]}}
    st = _states({"2026-11": nov, "2026-12": dec}, vers, {"ok": True, "why": ""}, "Nov 17, 2026")
    st["input_number.flight_watcher_month_offset"]["state"] = str(offset)
    st["sensor.flight_watcher_state"]["attributes"]["doh"] = "2018-10-03"
    for k, val in (("federal_tax_pct", "22.0"), ("state_tax_pct", "0.0"), ("longevity_year", "9.0")):
        st[f"input_number.flight_watcher_{k}"] = {"state": val, "last_updated": "a", "attributes": {}}
    st["sensor.flight_watcher_own_trip_times"] = {"state": "1", "last_updated": "a", "attributes": {"count": 1, "trips": OWN_T}}
    return st


def _pkg_json(month, start, end, rows, detail):
    return {"month": month, "source": "synthetic", "start": start, "end": end, "cols": COLS, "rows": rows, "dv": 2, "detail": detail}


PKGS = {"2026-11": _pkg_json("2026-11", "2026-11-01", "2026-12-01", [_row("H9635", "D1", "15h00", "11:15")], DETAIL),
        "2026-12": _pkg_json("2026-12", "2026-12-02", "2026-12-31", [_row("H9656", "5", "15h00", "11:15", "HNL-SEA-HNL")], {})}

OWN_JS = """(h) => new Promise((res) => { const c = document.createElement('flight-watcher-schedule-card'); c.setConfig({});
  document.body.appendChild(c); c.hass = {states: h, callService: (d, s, x) => (window.sent = window.sent || []).push(x)};
  setTimeout(() => { c.hass = {states: h, callService: (d, s, x) => (window.sent = window.sent || []).push(x)}; setTimeout(() => {
    const r = c.shadowRoot, tot = r.querySelector('.tot');
    const row = (d) => [...r.querySelectorAll(`.cal tr[data-d="${d}"] td.t`)].slice(0, 3).map((td) => ({t: td.textContent.trim(), cls: td.className, title: td.title}));
    res({tot: tot ? tot.textContent.replace(/\\s+/g, ' ').trim() : '', title: tot ? tot.title : '', bad: tot ? tot.querySelectorAll('.bad').length : -1,
         dec1: row('2026-12-01'), dec2: row('2026-12-02'), cin: [...r.querySelectorAll('.cin')].map((x) => x.textContent),
         vbar: (r.querySelector('.vbar') || {}).textContent || '', splitColor: (() => { const td = r.querySelector('.cal tr[data-d="2026-12-01"] td.t.split'); return td ? getComputedStyle(td).color : ''; })()});
  }, 400); }, 400); })"""


def _render_own(cases, shots=""):
    sync_api = pytest.importorskip("playwright.sync_api")
    from test_cards import _chromium
    stub = ("window.fetch = async (u) => { const m = /pairings_(\\d{4}-\\d{2})\\.json/.exec(String(u)); const P = " + json.dumps(PKGS)
            + "; return m && P[m[1]] ? {ok: true, json: async () => P[m[1]]} : {ok: false, json: async () => null}; };")
    page = ("<!doctype html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'></head><body>"
            "<script>customElements.define('ha-card', class extends HTMLElement {});" + stub + "</script><script>" + _src()
            + "</script></body></html>")
    with sync_api.sync_playwright() as p:
        b = _chromium(p)
        if not b:
            pytest.skip("no Chromium for Playwright")
        try:
            out = {}
            for name, st in cases.items():
                pg = b.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=2)
                pg.clock.set_fixed_time("2026-11-17T22:00:00Z")  # Nov 17 12:00 HST
                pg.set_content(page)
                out[name] = pg.evaluate(OWN_JS, st)
                if shots:
                    pg.screenshot(path=os.path.join(shots, f"totals_own_{name}_390_light.png"), full_page=True)
                pg.close()
            return out
        finally:
            b.close()


def test_ryans_schedule_card_totals_by_bid_period():
    got = _render_own({"dec": _own_states(1, versions=True), "nov": _own_states(0),
                       "vac_dec": _own_states(1, dec_rows=[("2026-12-01", "VAC", "")], nov_rows=[("2026-12-01", "VAC", "")],
                                              dec_tot={"block": "0:00", "credit": "0:00", "days_off": 30}),
                       "vac_nov": _own_states(0, nov_rows=[("2026-12-01", "VAC", "")], dec_rows=[("2026-12-01", "VAC", "")],
                                              nov_tot={"block": "0:00", "credit": "4:00", "days_off": 29}),
                       "carried": _own_states(1, dec_rows=[("2026-12-02", "", "-"), ("2026-12-03", "", "HNL")])}, SHOTS)
    dec, nov = got["dec"], got["nov"]
    # December: only duty 2 (6:39 / 5:52) as FLICA's December, checked, no red
    assert "Credit 6:39 ✓" in dec["tot"] and "Block 5:52 ✓" in dec["tot"] and dec["bad"] == 0, dec["tot"]
    assert [c["t"] for c in dec["dec1"]] == ["5:52", "6:39", "0:47"] and all("split" in c["cls"] for c in dec["dec1"][:2])
    assert "5:23 block, 8:21 credit flown before Dec 2 pay in the November bid period (PWA 4.A)" in dec["dec1"][0]["title"], dec["dec1"][0]["title"]
    assert "flown in the bid period, Dec 2 to Dec 31 (the pairings package)" in dec["title"], dec["title"]
    pay = re.search(r"Pay-Gross (\$[\d,]+)", dec["tot"]).group(1)
    assert pay == "$" + f"{round((6 + 39 / 60) * PAY.rate_for(9, '2026-11-17')):,}"
    assert f"Awarded-Pay-Gross {pay}" in dec["vbar"] and "Improved-Pay-Gross +$0" in dec["vbar"], dec["vbar"]  # the versions price it alike
    # November: the rest (8:21 / 5:23), as FLICA's November
    assert "Credit 8:21 ✓" in nov["tot"] and "Block 5:23 ✓" in nov["tot"] and nov["bad"] == 0, nov["tot"]
    assert [c["t"] for c in nov["dec1"]] == ["5:23", "8:21", "2:58"]
    assert "5:52 block, 6:39 credit flown after Dec 1 pay in the December bid period (PWA 4.A)" in nov["dec1"][0]["title"]
    # a VAC day on Dec 1 is November's
    assert "Vacation" not in got["vac_dec"]["tot"] and "Credit 0:00 ✓" in got["vac_dec"]["tot"], got["vac_dec"]["tot"]
    assert "Vacation 4:00" in got["vac_nov"]["tot"] and "Credit 4:00 ✓" in got["vac_nov"]["tot"], got["vac_nov"]["tot"]
    # a trip with no row on December's page (it starts on November's) still counts its December part, named under the totals
    car = got["carried"]
    assert "Credit 6:39 ✓" in car["tot"] and car["bad"] == 0, car["tot"]
    assert any("H9635 Dec 1: 5:52 block, 6:39 credit flown in this bid period" in x for x in car["cin"]), car["cin"]
    assert dec["splitColor"] in ("rgb(123, 31, 162)",)  # the split mark (purple, WCAG AA on a light card)


# ---------------------------------------------------------------- the pilot card at 390 and 1024 px (FW-0079, FW-0080)
LONG = [["CA", "Doe-Roeson, Janeanne Q"], ["FO", "Roe, Rick"], ["RO", "Moe-Poeson, Kalikoa T"], ["FO", "Poe, <i>Pat</i>"]]


def _pilot_attrs(W, tmp_path, monkeypatch):  # noqa: F811
    _setup(W, tmp_path, monkeypatch)
    add = lambda d, n: f"2026-12-{int(d[8:]) + n:02d}"  # noqa: E731
    starts = [("H9635", "2026-12-01", "LAX"), ("H9656", "2026-12-05", "SEA"), ("H9620", "2026-12-09", "LAS"), ("H9655", "2026-12-14", "SEA"),
              ("H9631", "2026-12-20", "LAX")]
    items, at = [], {}
    for i, (pid, st, lay) in enumerate(starts):
        crew = [["CA", "Doe-Roeson, Janeanne Q"], ["FO", "Roe, Rick"]] if i != 3 else LONG
        items.append({"trip": pid, "start": st, "end": add(st, 2), "lay": lay, "credit": "15:00", "blk": "11:15", "soft": "3:45", "seat": "FO",
                      "n": len(crew), "crew": crew,
                      "legs": [{"dow": "TU", "flt": "9001", "route": f"HNL-{lay}", "dep": "2137", "arr": "0500", "blk": "0523"},
                               {"dow": "TH", "flt": "9002", "route": f"{lay}-HNL", "dep": "0840", "arr": "1232", "blk": "0552"}]})
        at[st], at[add(st, 1)], at[add(st, 2)] = [pid, lay], ["", "-"], ["", "HNL"]
    days = [[f"2026-12-{d:02d}", *at.get(f"2026-12-{d:02d}", ["", ""])] for d in range(1, 32)]
    tot = {"block": "50:52", "credit": "66:39", "days_off": 16}  # FLICA's December: 6:39 of H9635, the four others whole
    W.pub_pilot({"emp": "10999", "name": "Roe, Rick", "status": "ok", "month": "2026-12", "updated": "Nov 17, 2026 03:16:30",
                 "fetched": "2026-11-17T16:00:00+00:00", "days": days, "items": items, "totals": tot})
    return [p for t, p in W.SENT if t == "pilot_schedule"][-1]


def test_the_pilot_card_on_a_phone_and_a_wide_card(W, tmp_path, monkeypatch):  # noqa: F811
    if not shutil.which("node"):
        pytest.skip("node not installed")
    if subprocess.run(["node", "-e", "require('playwright')"], capture_output=True).returncode:
        pytest.skip("node Playwright not installed")
    attrs = _pilot_attrs(W, tmp_path, monkeypatch)
    assert (attrs["items_pay"]["credit"], attrs["items_pay"]["block"]) == ("66:39", "50:52")
    f = tmp_path / "attrs.json"
    f.write_text(json.dumps(attrs))
    card = tmp_path / "pc.js"
    card.write_text(cards.build("9.9.9", [])["flight-watcher-pilot-card.js"])
    out = subprocess.run(["node", os.path.join(HERE, "fw1711_pilot_render.js"), str(card), str(f)] + ([SHOTS] if SHOTS else []),
                         capture_output=True, text=True, timeout=180)
    assert out.returncode == 0, out.stderr
    r = json.loads(out.stdout.strip().splitlines()[-1])
    if r.get("skip"):
        pytest.skip(r["skip"])
    for v in ("390_light", "390_dark"):
        m = r[v]
        assert m["doc"] <= m["win"], (v, m["doc"])
        assert m["table"]["r"] <= m["wrap"]["r"] + 0.5 and m["wrapScroll"] <= m["wrapClient"] + 1, (v, m["table"], m["wrap"], m["wrapScroll"])
        assert not m["crewTh"] and not m["crewTd"] and m["crl"], (v, m)
        assert m["crlLines"] == ["H9635 Dec 1: CA Doe-Roeson, Janeanne Q · FO Roe, Rick", "H9656 Dec 5: CA Doe-Roeson, Janeanne Q · FO Roe, Rick",
                                 "H9620 Dec 9: CA Doe-Roeson, Janeanne Q · FO Roe, Rick",
                                 "H9655 Dec 14: CA Doe-Roeson, Janeanne Q · FO Roe, Rick · RO Moe-Poeson, Kalikoa T · FO Poe, <i>Pat</i>",
                                 "H9631 Dec 20: CA Doe-Roeson, Janeanne Q · FO Roe, Rick"], (v, m["crlLines"])
        assert m["crlTags"] == ["b", "div", "span"] and m["crlNowrap"] is True, (v, m["crlTags"])  # names are text, never markup
        assert m["crlRight"] <= m["wrap"]["r"] + 0.5, (v, m["crlRight"], m["wrap"])
        assert len(set(m["rowH"])) == 1, (v, sorted(set(m["rowH"])))  # every row one line, as before
    for v in ("1024_light", "1024_dark"):
        m = r[v]
        assert m["crewTh"] and m["crewTd"] and not m["crl"], (v, m)  # the Crew column as before, no list
        assert "FO Poe, <i>Pat</i>" in m["crewCell"][3] and "i" not in m["crewTags"], m["crewCell"]
    for v, m in r.items():
        assert [c["t"] for c in m["dec1"][:3]] == ["5:52", "6:39", "0:47"] and "split" in m["dec1"][0]["cls"], (v, m["dec1"])
        assert m["dec1"][3]["t"] == "$" + f"{round((6 + 39 / 60) * FO9):,}"  # Pay-Gross of the December part only
        assert "5:23 block, 8:21 credit flown before Dec 2 pay in the November bid period (PWA 4.A)" in m["dec1"][0]["title"], m["dec1"][0]["title"]
        assert [c["t"] for c in m["dec5"][:3]] == ["11:15", "15:00", "3:45"] and "split" not in m["dec5"][0]["cls"]
        assert m["tot"].replace(" ", "").startswith("Credit66:39✓Block50:52✓Soft15:47") and m["totBad"] == 0, (v, m["tot"])
        assert "flown in the bid period (Dec 2 to Dec 31), as FLICA totals it" in m["totTitle"], m["totTitle"]
    assert r["390_light"]["splitColor"] == "rgb(123, 31, 162)" and r["390_dark"]["splitColor"] == "rgb(206, 147, 216)"
