"""1.7.20 (Hark, Ryan Nov 20, 2026): the PWA pay engine of an own trip. Credit = the greater of GOP, Trip Rig 1:3.5 and
MDG 5:00 x calendar days (PWA 4.C.3.a); a delayed leg is ONE segment (2.A.15.a.1, 4.B.1), so FLICA's credit that
counted it twice is replaced; LODO 4:00 pay, no credit, per lost day off (4.D.2.e); recall 200% pay, 100% credit
(4.M.1.a); PWA 4.O.1 overrides by crew size (the type-rated FO's 15% only when marked). pay.py mirrors the card
(fwPwaTrip, fwOverride, fwCrewOwn), and the card draws it on a synthetic month. Made-up trips and crew only."""
import json
import os
import re
import shutil
import subprocess

import pytest

import pay as PAY

CARD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "www", "flight-watcher-schedule-card.js")

# a JFK-style trip: out day 1, back day 3 scheduled 08:40 local (03:40 HST), delayed 14:05 to 17:45 HST, block-in
# 05:09 HST on day 4 (a day off). FLICA's credit 32:19 counts the delayed leg twice (21:08 + 11:11)
DET = {"crew": "CA01FO01RO01", "duties": [
    {"legs": [["1", "", "830", "HNL", "JFK", "15:45", "06:30", "9h45", "9:45", "", "332"]], "stn": "JFK", "tblk": "9h45", "tcrd": "9h45"},
    {"legs": [["3", "", "829", "JFK", "HNL", "08:40", "14:55", "11h15", "11:15", "", "332"]], "stn": "HNL", "tblk": "11h15", "tcrd": "11h15"}]}
OT = {"report": "14:45", "blk": "21:08", "credit": "32:19", "soft": "11:11", "seat": "FO",
      "crew": ["CA Doe, John (1001)", "FO Roe, Jane (1002)", "RO Poe, Jim (1003)"],
      "duties": [{"d": 0, "dep": 947, "arr": 1531, "stn": "JFK", "blk": 584}, {"d": 2, "dep": 3945, "arr": 4629, "stn": "HNL", "blk": 684}]}


def _head():
    src = open(CARD, encoding="utf-8").read()
    return src[:src.index("class FlightWatcherScheduleCard")].replace("customElements", "//")


def _node(js, tmp_path):
    f = tmp_path / "t.mjs"
    f.write_text(_head() + "\n" + js)
    res = subprocess.run(["node", str(f)], capture_output=True, text=True, timeout=30)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


def test_delayed_leg_counts_once_with_lodo():
    pa = PAY.pwa_trip("2026-11-18", OT, DET, 2, lambda iso: True)
    assert pa["fix"] and pa["match"] and pa["delayed"] == 1 and not pa["passed"]
    assert pa["gop"] == 9 * 60 + 45 + 11 * 60 + 24  # 9:45 sched > 9:44 actual; 11:24 actual > 11:15 sched
    assert pa["rig"] == round((4629 + 15 - 885) / 3.5) and pa["mdg"] == 20 * 60 and pa["won"] == "gop"
    assert pa["use"] == pa["gop"] and pa["cut"] == 32 * 60 + 19 - pa["gop"]
    assert pa["lodo_days"] == ["2026-11-21"] and pa["lodo"] == 240
    # the release day not a day off: no LODO
    assert PAY.pwa_trip("2026-11-18", OT, DET, 2, lambda iso: False)["lodo"] == 0


def test_reassignment_or_unknown_keeps_flicas_credit():
    late = json.loads(json.dumps(OT))
    late["duties"][1]["dep"] += 1440  # left a day later: may pass the next day's operation (2.A.15)
    late["duties"][1]["arr"] += 1440
    pa = PAY.pwa_trip("2026-11-18", late, DET, 2, lambda iso: True)
    assert pa["passed"] == 1 and not pa["fix"] and pa["use"] == 32 * 60 + 19
    assert PAY.pwa_trip("2026-11-18", OT, None)["use"] == 32 * 60 + 19  # no package: nothing to compare, FLICA kept
    two = json.loads(json.dumps(DET))
    two["duties"][1]["legs"].append(["3", "", "9", "HNL", "OGG", "16:00", "16:40", "0h40", "0:40", "", "332"])
    assert not PAY.pwa_trip("2026-11-18", OT, two, 2)["fix"]  # a duty of two legs: per-leg block not on file


def test_on_time_trip_matches_and_mdg_wins():
    ot = {"report": "22:45", "credit": "15:00", "duties": [{"dep": 1422, "arr": 1775, "stn": "LAS", "blk": 353},
                                                          {"dep": 3184, "arr": 3575, "stn": "HNL", "blk": 391}]}
    pa = PAY.pwa_trip("2026-11-06", ot)
    assert pa["mdg"] == 15 * 60 and pa["won"] == "mdg" and pa["use"] == 15 * 60 and not pa["fix"] and pa["lodo"] == 0


def test_recall_pay_only():
    assert PAY.pwa_trip("2026-11-18", OT, DET, 2, rcl=[0])["rcl"] == 9 * 60 + 45
    assert PAY.pwa_trip("2026-11-18", OT, DET, 2, rcl=True)["rcl"] == PAY.pwa_trip("2026-11-18", OT, DET, 2)["use"]


def test_overrides_by_crew_size():
    r = 307.78
    assert PAY.override("RO", 4, 26.6, 27.0, r) == (pytest.approx(26.6 * 3.0), "erfo")  # 4 pilots, RO seat: $3.00
    assert PAY.override("FO", 4, 26.6, 27.0, r) == (pytest.approx(26.6 * 3.0), "erfo")
    assert PAY.override("FO", 4, 26.6, 27.0, r, True) == (pytest.approx(27.0 * r * 0.15), "er")  # marked type-rated FO
    assert PAY.override("RO", 3, 10.0, 11.0, r) == (pytest.approx(40.0), "iro")
    assert PAY.override("FO", 3, 10.0, 11.0, r) == (pytest.approx(30.0), "fo3")
    assert PAY.override("CA", 3, 10.0, 11.0, r) == (pytest.approx(50.0), "ca")
    assert PAY.override("CA", 4, 10.0, 11.0, r, True) == (pytest.approx(50.0), "ca")  # a Captain never the 15%
    assert PAY.override("FO", 2, 10.0, 11.0, r) == (0.0, "")
    assert not PAY.er_on("H9815|2026-11-01", "SIN", 4, ()) and PAY.er_on("H9815|2026-11-01", "SIN", 4, ("+H9815|2026-11-01",))
    assert PAY.crew_own(["FO Doe, J (1)", "FO Roe, J (2)", "RO Poe, J (3)"]) == 4  # no Captain listed: one more
    assert PAY.crew_own(["CA Doe, J (1)", "FO Roe, J (2)", "RO Poe, J (3)"]) == 3 and PAY.crew_own([]) == 0


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_card_and_pay_py_agree(tmp_path):
    late = json.loads(json.dumps(OT))
    late["duties"][1]["dep"] += 1440
    late["duties"][1]["arr"] += 1440
    cases = [("2026-11-18", OT, DET, 2, "all", None), ("2026-11-18", OT, DET, 2, "none", None),
             ("2026-11-18", late, DET, 2, "all", None), ("2026-11-18", OT, None, None, "all", None),
             ("2026-11-18", OT, DET, 2, "all", [1]), ("2026-11-18", OT, DET, 2, "all", True)]
    js = "const out = [];\n"
    for st, ot, det, rd, off, rcl in cases:
        pr = "null" if det is None else json.dumps({"det": det, "relDays": rd})
        js += (f"{{ const p = fwPwaTrip({{start: {json.dumps(st)}, ot: {json.dumps(ot)}, pr: {pr}, "
               f"isOff: () => {'true' if off == 'all' else 'false'}, rcl: {json.dumps(rcl)}}}); "
               "out.push([p.gop, p.rig, p.mdg, p.pwa, p.won, p.use, p.fix, p.cut, p.lodoDays, p.rcl, p.delayed, p.passed]); }\n")
    ov = [("RO", 4, 26.6, 27.0, False), ("FO", 3, 10.0, 11.0, False), ("RO", 3, 10.0, 11.0, False), ("CA", 3, 10.0, 11.0, False),
          ("FO", 4, 26.6, 27.0, True), ("RO", 2, 10.0, 11.0, False), ("", 0, 0.0, 15.0, False), ("FO", 3, None, 11.0, False)]
    js += "const ovs = [];\n"
    for s, n, b, c, e in ov:
        js += f"{{ const o = fwOverride({json.dumps(s)}, {n}, {json.dumps(b)}, {c}, 307.78, {json.dumps(e)}); ovs.push([o.v, o.kind]); }}\n"
    js += ("const cr = [fwCrewOwn(['FO A, B (1)', 'FO C, D (2)', 'RO E, F (3)']), fwCrewOwn(['CA A, B (1)', 'FO C, D (2)'])];\n"
           "console.log(JSON.stringify({out, ovs, cr, rcl: [fwRclOf(['+X|1', 'R+H9606A|2026-11-18@0.1'], 'H9606A|2026-11-18'), "
           "fwRclOf(['R+H9606A|2026-11-18'], 'H9606A|2026-11-18'), fwRclOf(['+H9606A|2026-11-18'], 'H9606A|2026-11-18')]}));")
    got = _node(js, tmp_path)
    for (st, ot, det, rd, off, rcl), j in zip(cases, got["out"]):
        p = PAY.pwa_trip(st, ot, det, rd, (lambda iso: True) if off == "all" else (lambda iso: False), rcl)
        assert j == [p["gop"], p["rig"], p["mdg"], p["pwa"], p["won"], p["use"], p["fix"], p["cut"], p["lodo_days"],
                     p["rcl"], p["delayed"], p["passed"]]
    for (s, n, b, c, e), (v, k) in zip(ov, got["ovs"]):
        pv, pk = PAY.override(s, n, b, c, 307.78, e)
        assert (pv, pk) == (pytest.approx(v), k)
    assert got["cr"] == [4, 2] and got["rcl"] == [[0, 1], True, None]


def test_card_and_pay_py_share_the_tz_table():
    src = open(CARD, encoding="utf-8").read()
    body = re.search(r"const FW_TZ = \{(.*?)\};", src, re.S).group(1)
    card = {k: int(v) for k, v in re.findall(r"([A-Z]{3}): (-?\d+)", body)}
    assert card == PAY.FW_TZ


def test_schedule_card_draws_the_pwa_breakdown_and_lodo():
    sync_api = pytest.importorskip("playwright.sync_api")
    from test_cards import _chromium
    days = [[f"2026-11-{d:02d}", "", ""] for d in range(1, 31)]
    days[17] = ["2026-11-18", "H9606A", "JFK"]
    package = {"month": "2026-11", "source": "synthetic", "start": "2026-11-01", "end": "2026-11-30",
               "cols": ["id", "report", "dep", "release", "rel_days", "first_duty_min", "route", "credit", "tafb", "days"],
               "rows": [["H9606", "14:45", "15:45", "15:10", 2, 960, "HNL-JFK-HNL", "21h00", "48h25", "18"]],
               "detail": {"H9606": DET}}
    ot = dict(OT)
    st = {"sensor.flight_watcher_schedule": {"state": "", "last_updated": "a", "attributes": {"updated": "Nov 20, 2026", "months": {
              "2026-11": {"items": [{"trip": "H9606A", "start": "2026-11-18", "end": "2026-11-21", "lay": "JFK"}],
                          "days": days, "totals": {"credit": "32:19", "block": "21:08"}, "updated": "Nov 20, 2026"}}}},
          "sensor.flight_watcher_own_trip_times": {"state": "1", "last_updated": "a", "attributes": {"trips": {"H9606A|2026-11-18": ot}}},
          "input_number.flight_watcher_month_offset": {"state": "0", "last_updated": "a"},
          "input_number.flight_watcher_longevity_year": {"state": "12.0", "last_updated": "a", "attributes": {}},
          "input_text.flight_watcher_er_trips": {"state": "", "last_updated": "a", "attributes": {}},
          "sensor.flight_watcher_state": {"state": "idle", "last_updated": "a", "attributes": {"role": "pilot"}}}
    stub = ("window.fetch = async (u) => ({ok: String(u).includes('pairings_2026-11'), json: async () => ("
            + json.dumps(package) + ")});")
    page = ("<!doctype html><html><body><script>customElements.define('ha-card', class extends HTMLElement {});"
            + stub + "</script><script>" + open(CARD, encoding="utf-8").read() + "</script></body></html>")
    js = """(h) => { const c = document.createElement('flight-watcher-schedule-card'); c.setConfig({});
      document.body.appendChild(c); c.hass = {states: h, callService: async () => {}};
      return new Promise((res) => setTimeout(() => { c.hass = {states: h, callService: async () => {}};
        const r = c.shadowRoot, tr = [...r.querySelectorAll('tr[data-d]')].find((x) => x.dataset.d === '2026-11-18');
        const p = tr.querySelector('.pay');
        res({tot: (r.querySelector('.tot') || {}).textContent || '', cells: [...tr.querySelectorAll('td.t')].map((td) => td.textContent),
             info: p.dataset.info, btn: p.dataset.btn}); }, 400)); }"""
    with sync_api.sync_playwright() as p:
        b = _chromium(p)
        if not b:
            pytest.skip("no Chromium for Playwright")
        try:
            pg = b.new_page(viewport={"width": 1200, "height": 900})
            pg.clock.set_fixed_time("Fri 2026-11-20 6:30 PM EST (UTC-05:00)")
            pg.set_content(page)
            got = pg.evaluate(js, st)
        finally:
            b.close()
    tot = " ".join(got["tot"].split())
    assert "Credit 21:09" in tot and "PWA -11:10" in tot and "LODO 4:00" in tot, tot
    assert got["cells"][1] == "21:09" and got["cells"][2] == "0:01", got["cells"]
    for want in ("PWA 4.C.3.a", "GOP 21:09", "Trip Rig 17:54", "MDG 20:00", "GOP wins", "FLICA shows 32:19", "2.A.15.a.1",
                 "LODO $1,231", "4.D.2.e", "IRO crew FO override $63", "4.O.1.a", "pay hours 25:09", "CrewTrac"):
        assert want in got["info"], (want, got["info"])
    assert 'class="er tag"' in got["btn"] and 'class="rcl tag"' in got["btn"]
