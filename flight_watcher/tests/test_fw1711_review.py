"""1.7.11 review fixes for FW-0079 and FW-0080 (Ryan's yes of Nov 17, 2026; both from FW-0076, a pilot's report only).
Synthetic pilots and pairings only (Roe, Rick 10999; Doe, Jane; H96xx), no FLICA load.

Pay (PWA 4.A: a segment pays on the date it originates; PWA Definitions 57: a PAYP keeps the removed trip's pay):
- PAY-1 / R1: FLICA's December page starts on Dec 1, November's bid period's last day, so a PAYP listed again there
  starts on a November day: its continuation record carries December's share of the November record's split (the bid
  period of its days, not of its first day), and the card counts it (or, with no record, the November record's share).
- PAY-2 / R2: a PAYP record written by 1.7.10 (the calendar month's split, or none) is split again by bid period, on
  file and in the stored versions (once), from the removed trip's duties in own trips or the versions.
- PAY-5: another pilot's pairing page legs make duty periods (a gap of 8 h or more), as Ryan's own trips and the
  package's do, so a duty across HST midnight counts on its first leg's date whichever source prices the trip.
- R4 (a): the versions' change line names the bid period.
Cards (Chromium):
- F1 / F2: the pilot card's grid fits its box at 360, 375 and 390 px, a one-day turn (R and Rel on one row) too.
- F6: on a wider card whose grid does not fit (an 820 px tablet in portrait) the crew list replaces the Crew column.
- F3: a reserve code on a grid day outside the bid period stays a plain cell in Ryan's schedule card.
- F4: a trip whose own times are not read yet splits by the package detail's duties in Ryan's schedule card.
- F5: with no duty times on file the split title never says the trip was flown before the bid period's first day.
- R3: the month's Improved-Pay-Gross is reported once, priced with the bid period before's package (its TCRD)."""
import copy
import json
import os
import re
import shutil
import subprocess
from datetime import date, timedelta

import pytest

import cards
import pay as PAY
import pot
import versions as VER
from pot import PAIRING_RE, schedule_items
from test_crew_index import COLS, ROE, W, _sen  # noqa: F401
from test_fw1711_totals import (DETAIL, DUTIES, H9640, OWN_T, PKGS, _own_states, _pilot_attrs, _pkg, _row, _setup,
                                SHOTS, _src)

HERE = os.path.dirname(os.path.abspath(__file__))


def _bp(iso):
    """The bid period of a day (November 2026 runs Nov 1 to Dec 1, December Dec 2 to Dec 31), as bid_period_key gives it."""
    return "2026-11" if str(iso)[:10] == "2026-12-01" else str(iso)[:7]


def _page(first, last, marks, credit="0:00", block="0:00"):
    a, b = date.fromisoformat(first), date.fromisoformat(last)
    at = {d: (t, lay) for d, t, lay in marks}
    days = [[(a + timedelta(days=k)).isoformat(), *at.get((a + timedelta(days=k)).isoformat(), ("", ""))] for k in range((b - a).days + 1)]
    return {"items": schedule_items(days), "days": days, "totals": {"days_off": 12, "block": block, "credit": credit}, "updated": "Nov 17, 2026"}


H9640_OWN = {"blk": "14:00", "credit": "18:00", "soft": "4:00", "seat": "FO", "report": "20:40", "last_arr": "11:00",
             "duties": [dict(d) for d in H9640]}
PAYP_MARK = lambda *ds: [(d, "PAYP", "-") for d in ds]  # noqa: E731


# ---------------------------------------------------------------- PAY-1 / R1: the continuation by bid period
@pytest.mark.parametrize("nov_last", ["2026-12-01", "2026-12-02"])
def test_a_payp_listed_again_on_decembers_page_gets_decembers_share(W, tmp_path, monkeypatch, nov_last):  # noqa: F811
    """Removed trip H9640 Nov 30 to Dec 3 (duties Nov 30, Dec 2, Dec 3; TCRD 5:30 / 5:00 / 3:30; credit 18:00). November's
    page lists the PAYP to its last row, December's page (from Dec 1) lists it again. 1.7.11 compared the bid period of
    Dec 1 (November's) with the record's (November's) and wrote no December record; December estimated it."""
    _setup(W, tmp_path, monkeypatch)
    nov_days = ["2026-11-30", "2026-12-01"] + (["2026-12-02"] if nov_last == "2026-12-02" else [])
    W.S["schedule"] = {"2026-11": _page("2026-11-01", nov_last, PAYP_MARK(*nov_days), "9:30"),
                       "2026-12": _page("2026-12-01", "2026-12-31", PAYP_MARK("2026-12-01", "2026-12-02", "2026-12-03"), "8:30")}
    own = {"H9640|2026-11-30": copy.deepcopy(H9640_OWN)}
    keep = W.payp_refresh(own)
    assert keep == {"PAYP|2026-11-30", "PAYP|2026-12-01"}
    assert own["PAYP|2026-11-30"]["split"] == {"2026-11": "9:30", "2026-12": "8:30"}
    cont = own["PAYP|2026-12-01"]
    assert (cont["credit"], cont["of"], cont["protected"], cont["end"]) == ("8:30", "PAYP|2026-11-30", "H9640|2026-11-30", "2026-12-03")
    # the removed trip pruned (own trips keep only what payp_refresh keeps): both records stay as they are
    gone = {k: v for k, v in own.items() if k in keep}
    W.payp_refresh(gone)
    assert gone["PAYP|2026-12-01"] == cont and gone["PAYP|2026-11-30"] == own["PAYP|2026-11-30"]


def test_a_continuation_with_no_share_in_the_next_bid_period_is_not_written():
    """H9103 Nov 29 to Dec 1: all its duties depart on November days (Dec 1 is November's), so December's page listing
    the PAYP again on Dec 1 gets no record, and a 1.7.10 continuation record (the calendar share) goes."""
    du = [{"d": 0, "dep": 1380, "blk": 342}, {"d": 1, "dep": 2415, "blk": 305}, {"d": 2, "dep": 3900, "blk": 350}]
    own = {"H9103|2026-11-29": {"credit": "18:00", "blk": "16:37", "seat": "FO", "duties": du}}
    items = _page("2026-11-01", "2026-12-01", PAYP_MARK("2026-11-29", "2026-11-30", "2026-12-01"))["items"] + \
        _page("2026-12-01", "2026-12-31", PAYP_MARK("2026-12-01"))["items"]
    got = VER.payp_entries(items, own, lambda mk: [], PAIRING_RE.match, _bp)
    assert list(got) == ["PAYP|2026-11-29"] and "split" not in got["PAYP|2026-11-29"]
    old = {"credit": "6:19", "blk": "0:00", "soft": "0:00", "payp": True, "protected": "H9103|2026-11-29", "end": "2026-12-01",
           "src": "own trips", "of": "PAYP|2026-11-29"}
    got = VER.payp_entries(items, {**own, "PAYP|2026-12-01": old}, lambda mk: [], PAIRING_RE.match, _bp)
    assert list(got) == ["PAYP|2026-11-29"]


# ---------------------------------------------------------------- PAY-2 / R2: 1.7.10 records split again
H9103_DU = [{"d": 0, "dep": 1380, "arr": 1722, "stn": "SEA", "blk": 342}, {"d": 1, "dep": 2415, "arr": 2720, "stn": "SFO", "blk": 305},
            {"d": 2, "dep": 3900, "arr": 4250, "stn": "HNL", "blk": 350}]
OLD_H9103 = {"credit": "18:00", "blk": "0:00", "soft": "0:00", "payp": True, "protected": "H9103|2026-11-29", "end": "2026-12-01",
             "src": "own trips", "split": {"2026-11": "11:41", "2026-12": "6:19"}, "seat": "FO"}
H9103_REC = {"credit": "18:00", "blk": "16:37", "seat": "FO", "duties": H9103_DU}


def _ver(n, items, trips):
    return {"ver": f"11.{n:03d}", "n": n, "at": f"2026-11-1{n}T01:00:00+00:00", "items": items, "days": [], "totals": {}, "trips": trips}


def test_a_1_7_10_calendar_split_is_split_again_by_bid_period():
    """1.7.10 split H9103's 18:00 by calendar month (December 6:19 for the Dec 1 duty); every duty departs on a November
    day by bid period, so the record holds no split now: from own trips, or from the versions once it is pruned."""
    items = [{"trip": "PAYP", "start": "2026-11-29", "end": "2026-12-01"}]
    with_trip = VER.payp_entries(items, {"PAYP|2026-11-29": dict(OLD_H9103), "H9103|2026-11-29": H9103_REC}, lambda mk: [],
                                 PAIRING_RE.match, _bp)
    assert "split" not in with_trip["PAYP|2026-11-29"] and with_trip["PAYP|2026-11-29"]["credit"] == "18:00"
    vers = {"2026-11": [_ver(1, [{"trip": "H9103", "start": "2026-11-29", "end": "2026-12-01"}], {"H9103|2026-11-29": H9103_REC})]}
    pruned = VER.payp_entries(items, {"PAYP|2026-11-29": dict(OLD_H9103)}, lambda mk: vers.get(mk, []), PAIRING_RE.match, _bp)
    assert pruned == with_trip
    # the calendar month (no bid period given) keeps the 1.7.10 split, as before
    assert VER.payp_entries(items, {"PAYP|2026-11-29": dict(OLD_H9103), "H9103|2026-11-29": H9103_REC}, lambda mk: [],
                            PAIRING_RE.match)["PAYP|2026-11-29"]["split"] == OLD_H9103["split"]


def test_a_1_7_10_record_with_no_split_gets_the_bid_periods_split(W, tmp_path, monkeypatch):  # noqa: F811
    """H9635 Dec 1 to 3 (credit 15:00): 1.7.10 put it all in December (no split); by bid period its Dec 1 duty pays in
    November: 8:21 / 6:39 with the package's TCRD, as a fresh 1.7.11 record has it."""
    _setup(W, tmp_path, monkeypatch)
    old = {"credit": "15:00", "blk": "0:00", "soft": "0:00", "payp": True, "protected": "H9635|2026-12-01", "end": "2026-12-03",
           "src": "own trips", "seat": "FO"}
    W.S["schedule"] = {"2026-12": _page("2026-12-01", "2026-12-31", PAYP_MARK("2026-12-01", "2026-12-02", "2026-12-03"), "6:39")}
    W.DB.put("sched_versions:2026-12", [_ver(1, [{"trip": "H9635", "start": "2026-12-01", "end": "2026-12-03"}],
                                             {"H9635|2026-12-01": {"blk": "11:15", "credit": "15:00", "duties": DUTIES}})])
    own = {"PAYP|2026-12-01": dict(old)}
    W.payp_refresh(own)
    assert own["PAYP|2026-12-01"]["split"] == {"2026-11": "8:21", "2026-12": "6:39"}
    assert {k: v for k, v in own["PAYP|2026-12-01"].items() if k != "split"} == old


def test_the_stored_versions_payp_records_are_split_again_once(W, tmp_path, monkeypatch):  # noqa: F811
    """A viewed version prices its own PAYP record: 1.7.10's calendar split there is split again by bid period, once
    (payp_fix_v), the continuation record of December's version with it."""
    _setup(W, tmp_path, monkeypatch)
    W.TEST_CLOCK["t"] = W.TEST_CLOCK["t"].replace(month=11, day=17)
    nov = [_ver(1, [{"trip": "H9640", "start": "2026-11-30", "end": "2026-12-03"}], {"H9640|2026-11-30": copy.deepcopy(H9640_OWN)}),
           _ver(2, [{"trip": "PAYP", "start": "2026-11-30", "end": "2026-12-01"}],
                {"PAYP|2026-11-30": {"credit": "18:00", "blk": "0:00", "soft": "0:00", "payp": True, "protected": "H9640|2026-11-30",
                                     "end": "2026-12-01", "src": "own trips", "split": {"2026-11": "5:30", "2026-12": "12:30"}}})]
    dec = [_ver(1, [{"trip": "PAYP", "start": "2026-12-01", "end": "2026-12-03"}],
                {"PAYP|2026-12-01": {"credit": "12:30", "blk": "0:00", "soft": "0:00", "payp": True, "protected": "H9640|2026-11-30",
                                     "end": "2026-12-03", "src": "own trips", "of": "PAYP|2026-11-30"}})]
    W.DB.put("sched_versions:2026-11", nov)
    W.DB.put("sched_versions:2026-12", dec)
    assert W.repair_payp_splits() == 2
    n2 = W.DB.get("sched_versions:2026-11")[-1]["trips"]["PAYP|2026-11-30"]
    assert n2["split"] == {"2026-11": "9:30", "2026-12": "8:30"} and n2["credit"] == "18:00"
    assert W.DB.get("sched_versions:2026-12")[0]["trips"]["PAYP|2026-12-01"]["credit"] == "8:30"
    assert W.S["payp_fix_v"] == W.PAYP_FIX_V and W.repair_payp_splits() == 0  # once


# ---------------------------------------------------------------- PAY-5: the legs make duty periods
TURN_LEGS = [{"dow": "TU", "flt": "9001", "route": "HNL-OGG", "dep": "2300", "arr": "2335", "blk": "0035"},
             {"dow": "WE", "flt": "9002", "route": "OGG-LAX", "dep": "0010", "arr": "0810", "blk": "0500"},
             {"dow": "TH", "flt": "9003", "route": "LAX-HNL", "dep": "0840", "arr": "1132", "blk": "0552"}]


def test_pairing_page_legs_make_duty_periods_as_the_package_does(W, tmp_path, monkeypatch):  # noqa: F811
    """A 35-minute sit across HST midnight on Dec 1 is one duty (it counts on Dec 1, November's), as pot.parse_duties
    makes Ryan's own and the package lists it: the legs path and the package path price the trip alike."""
    assert W._legs_duties("2026-12-01", TURN_LEGS) == [{"dep": 1380, "blk": 335}, {"dep": 2 * 1440 + 520 - 120, "blk": 352}]
    _setup(W, tmp_path, monkeypatch)
    it = {"trip": "H9660", "start": "2026-12-01", "end": "2026-12-03", "lay": "LAX", "credit": "16:00", "blk": "11:27", "seat": "FO", "n": 2,
          "legs": TURN_LEGS}
    legs, _ = W.pilot_price([dict(it)], "10999", "Roe, Rick", "2026-12", "2026-12-02", "2026-12-31", None, 12)
    W.DB.put("pkg_details:2026-11", {**W.DB.get("pkg_details:2026-11"), "H9660": {
        "credit": "16:00", "block": "11:27", "lay": "LAX", "route": "HNL-OGG-LAX-HNL", "duties": [{"dep": 1380, "blk": 335}, {"dep": 3280, "blk": 352}]}})
    _pkg(tmp_path / "www", "2026-11", "2026-11-01", "2026-12-01", [_row("H9635", "D1", "15h00", "11:15"), _row("H9640", "30", "18h00", "14:00"),
                                                                    _row("H9660", "D1", "16h00", "11:27")], DETAIL)
    W._DETAIL_CACHE.clear()
    pkg, _ = W.pilot_price([dict(it)], "10999", "Roe, Rick", "2026-12", "2026-12-02", "2026-12-31", None, 12)
    assert (legs["credit"], legs["block"]) == (pkg["credit"], pkg["block"]) == ("8:12", "5:52")


# ---------------------------------------------------------------- R4 (a) and the card's time zones
def test_the_change_line_names_the_bid_period_and_the_cards_tz_is_the_watchers():
    old = {"trips": {}}
    new = {"trips": {"PAYP|2026-11-30": {"credit": "18:00", "payp": True, "protected": "H9640|2026-11-30",
                                         "split": {"2026-11": "9:30", "2026-12": "8:30"}}}}
    line = [c for c in VER.diff(old, new) if c.startswith("PAYP")][0]
    assert "by bid period (PWA 4.A) 2026-11 9:30, 2026-12 8:30" in line and "by month" not in line
    src = open(os.path.join(HERE, "..", "www", "flight-watcher-schedule-card.js"), encoding="utf-8").read()
    body = re.search(r"const FW_TZ = \{(.*?)\};", src, re.S).group(1)
    assert {k: int(v) for k, v in re.findall(r"([A-Z]{3}): (-?\d+)", body)} == pot.TZ


# ---------------------------------------------------------------- Ryan's schedule card (Chromium)
OWN_JS = """(h) => new Promise((res) => { const c = document.createElement('flight-watcher-schedule-card'); c.setConfig({});
  document.body.appendChild(c); const cs = (d, s, x) => (window.sent = window.sent || []).push(x);
  c.hass = {states: h, callService: cs};
  setTimeout(() => { c.hass = {states: h, callService: cs}; setTimeout(() => {
    const r = c.shadowRoot, tot = r.querySelector('.tot');
    const row = (d) => [...r.querySelectorAll(`.cal tr[data-d="${d}"] td.t`)].slice(0, 3).map((td) => ({t: td.textContent.trim(), cls: td.className, title: td.title}));
    res({tot: tot ? tot.textContent.replace(/\\s+/g, ' ').trim() : '', bad: tot ? tot.querySelectorAll('.bad').length : -1,
         dec1: row('2026-12-01'), dec2: row('2026-12-02'), cin: [...r.querySelectorAll('.cin')].map((x) => x.textContent),
         pps: Object.fromEntries([...r.querySelectorAll('tr[data-d] .payp')].map((x) => [x.closest('tr').dataset.d, x.title])),
         cursor: (() => { const td = r.querySelector('.cal tr[data-d="2026-12-01"] td.t'); return td ? getComputedStyle(td).cursor : ''; })(),
         imp: (window.sent || []).filter((x) => (x.topic || '').endsWith('improved/set')).map((x) => JSON.parse(x.payload))});
  }, 700); }, 400); })"""


def _render(cases, delays=None):
    sync_api = pytest.importorskip("playwright.sync_api")
    from test_cards import _chromium
    stub = ("window.fetch = async (u) => { const m = /pairings_(\\d{4}-\\d{2})\\.json/.exec(String(u)); const P = " + json.dumps(PKGS)
            + "; const D = " + json.dumps(delays or {}) + "; const k = m ? m[1] : ''; if (D[k]) await new Promise((ok) => setTimeout(ok, D[k]));"
            + " return m && P[k] ? {ok: true, json: async () => P[k]} : {ok: false, json: async () => null}; };")
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
                if SHOTS:
                    pg.screenshot(path=os.path.join(SHOTS, f"totals_review_own_{name}_390_light.png"), full_page=True)
                pg.close()
            return out
        finally:
            b.close()


def _no_own(st):
    st = copy.deepcopy(st)
    st["sensor.flight_watcher_own_trip_times"]["attributes"]["trips"] = {}
    return st


def _payp_states(offset, recs, dec_credit="8:30"):
    """Ryan's month with H9640 Nov 30 to Dec 3 removed for a PAYP; FLICA's November credit 9:30, December's 8:30."""
    st = _own_states(offset, dec_rows=PAYP_MARK("2026-12-01", "2026-12-02", "2026-12-03"), nov_rows=PAYP_MARK("2026-11-30", "2026-12-01"),
                     nov_tot={"block": "0:00", "credit": "9:30", "days_off": 29}, dec_tot={"block": "0:00", "credit": dec_credit, "days_off": 28})
    st["sensor.flight_watcher_own_trip_times"]["attributes"]["trips"] = recs
    return st


def test_ryans_card_a_reserve_code_outside_the_bid_period_is_plain():
    """F3: SCR on Dec 1 (the day before December's bid period, FLICA's first row) is a plain cell in the December view:
    no split mark, no made-up split title, no help cursor (1.7.10 drew it plain too)."""
    scr = _own_states(1, dec_rows=[("2026-12-01", "SCR", "")], nov_rows=[("2026-12-01", "SCR", "")],
                      dec_tot={"block": "0:00", "credit": "0:00", "days_off": 30})
    x = _render({"scr": scr})["scr"]
    assert all("split" not in c["cls"] and not c["title"] for c in x["dec1"]), x["dec1"]
    assert x["cursor"] != "help" and "Credit 0:00 ✓" in x["tot"]


def test_ryans_card_a_trip_with_no_own_times_splits_by_the_package():
    """F4: H9635's own times not read yet (or read with no duties): the package detail's duties (and their TCRD) split
    it, as FLICA's totals and the Watcher's pilot_price do: December 6:39 / 5:52, November 8:21 / 5:23, no red."""
    nodu = _own_states(1)
    nodu["sensor.flight_watcher_own_trip_times"]["attributes"]["trips"] = {"H9635|2026-12-01": {
        k: v for k, v in OWN_T["H9635|2026-12-01"].items() if k != "duties"}}
    got = _render({"dec": _no_own(_own_states(1)), "nov": _no_own(_own_states(0)), "nodu": nodu})
    dec, nov = got["dec"], got["nov"]
    assert "Credit 6:39 ✓" in dec["tot"] and "Block 5:52 ✓" in dec["tot"] and "FLICA" not in dec["tot"], dec["tot"]  # no red mismatch
    assert [c["t"] for c in dec["dec1"][:2]] == ["5:52", "6:39"] and "split" in dec["dec1"][0]["cls"]
    assert "5:23 block, 8:21 credit flown before Dec 2 pay in the November bid period (PWA 4.A)" in dec["dec1"][0]["title"]
    assert "Credit 8:21 ✓" in nov["tot"] and "Block 5:23 ✓" in nov["tot"] and "FLICA" not in nov["tot"], nov["tot"]
    assert "Credit 6:39 ✓" in got["nodu"]["tot"] and "FLICA" not in got["nodu"]["tot"], got["nodu"]["tot"]


def test_ryans_card_no_duty_times_anywhere_says_so():
    """F5: no duty times (own or package): the title says where the trip starts, never that it was all flown before."""
    pk = copy.deepcopy(PKGS)
    pk["2026-11"]["detail"] = {}
    sync_api = pytest.importorskip("playwright.sync_api")
    from test_cards import _chromium
    st = _no_own(_own_states(1))
    stub = ("window.fetch = async (u) => { const m = /pairings_(\\d{4}-\\d{2})\\.json/.exec(String(u)); const P = " + json.dumps(pk)
            + "; return m && P[m[1]] ? {ok: true, json: async () => P[m[1]]} : {ok: false, json: async () => null}; };")
    page = ("<!doctype html><html><body><script>customElements.define('ha-card', class extends HTMLElement {});" + stub
            + "</script><script>" + _src() + "</script></body></html>")
    with sync_api.sync_playwright() as p:
        b = _chromium(p)
        if not b:
            pytest.skip("no Chromium for Playwright")
        try:
            pg = b.new_page(viewport={"width": 390, "height": 844})
            pg.clock.set_fixed_time("2026-11-17T22:00:00Z")
            pg.set_content(page)
            r = pg.evaluate(OWN_JS, st)
        finally:
            b.close()
    t = r["dec1"][0]["title"]
    assert "starts Dec 1; no duty times on file, so the whole trip pays in the November bid period, the bid period of its first day (PWA 4.A)" in t, t
    assert "flown before" not in t


def test_ryans_card_counts_the_payp_listed_again_on_decembers_page():
    """PAY-1 on the card: December counts December's share (8:30) as FLICA does, from the continuation record, or from
    the November record's split when December's page has none yet; November its 9:30."""
    nov_rec = {"credit": "18:00", "blk": "0:00", "soft": "0:00", "payp": True, "protected": "H9640|2026-11-30", "end": "2026-12-01",
               "src": "own trips", "split": {"2026-11": "9:30", "2026-12": "8:30"}, "seat": "FO"}
    cont = {"credit": "8:30", "blk": "0:00", "soft": "0:00", "payp": True, "protected": "H9640|2026-11-30", "end": "2026-12-03",
            "src": "own trips", "of": "PAYP|2026-11-30", "seat": "FO"}
    got = _render({"dec": _payp_states(1, {"PAYP|2026-11-30": nov_rec, "PAYP|2026-12-01": cont}),
                   "dec_nocont": _payp_states(1, {"PAYP|2026-11-30": nov_rec}),
                   "dec_unknown": _payp_states(1, {"PAYP|2026-11-30": nov_rec}, dec_credit=None),
                   "nov": _payp_states(0, {"PAYP|2026-11-30": nov_rec, "PAYP|2026-12-01": cont})})
    for name in ("dec", "dec_nocont"):
        x = got[name]
        assert "Credit 8:30 ✓" in x["tot"] and "PAYP 8:30" in x["tot"] and "estimate" not in x["tot"] and "FLICA" not in x["tot"], (name, x["tot"])
        assert [c["t"] for c in x["dec2"]][1] == "8:30" and "share of the PAYP from Nov 30" in x["pps"]["2026-12-02"], (name, x["pps"])
    assert "PAYP 8:30" in got["dec_unknown"]["tot"] and "credit unknown" not in got["dec_unknown"]["tot"], got["dec_unknown"]["tot"]
    assert "Credit 9:30 ✓" in got["nov"]["tot"] and "PAYP 9:30" in got["nov"]["tot"], got["nov"]["tot"]


def test_ryans_card_reports_the_improved_pay_once_with_the_tcrd_split():
    """R3 (F#32): December's package in, November's still loading: the month's pay waits for it, then goes once,
    priced with H9635's December TCRD (6:39), never its block share (7:49) first."""
    st = _own_states(1, versions=True)
    st2 = copy.deepcopy(st)
    st2["sensor.flight_watcher_schedule"]["attributes"]["periods"] = {
        "2026-11": {"start": "2026-11-01", "end": "2026-12-01", "src": "package"}, "2026-12": {"start": "2026-12-02", "end": "2026-12-31", "src": "package"}}
    rate = PAY.rate_for(9, "2026-11-17")
    want = round((6 + 39 / 60) * rate, 2)
    got = _render({"nope": st, "periods": st2}, delays={"2026-11": 300})
    for name, x in got.items():
        assert [round(i["current"], 2) for i in x["imp"]] == [pytest.approx(want, abs=0.02)], (name, x["imp"])


# ---------------------------------------------------------------- the pilot card at phone, tablet and desktop widths
TIMES = {1: [("0600", "0640"), ("0730", "0810")], 3: [("0600", "0640"), ("0730", "0815"), ("0900", "1015"), ("1100", "1130")]}


def _turn(pid, st, dow, stns):
    route = ["HNL", *stns, "HNL"]
    legs = [{"dow": dow, "flt": f"92{i:02d}", "route": f"{route[i]}-{route[i + 1]}", "dep": d, "arr": a, "blk": "0040"}
            for i, (d, a) in enumerate(TIMES[len(stns)])]
    return {"trip": pid, "start": st, "end": st, "lay": "-", "credit": "5:00", "blk": "1:20", "soft": "3:40", "seat": "FO", "n": 2,
            "crew": [["CA", "Doe, Jane"], ["FO", "Roe, Rick"]], "legs": legs}


def _attrs_with(W, tmp_path, monkeypatch, extra):  # noqa: F811
    a = _pilot_attrs(W, tmp_path, monkeypatch)
    if not extra:
        return a
    W.SENT.clear()
    items = [{k: v for k, v in it.items() if k not in ("gross", "seat_src", "split", "figs")} for it in a["items"]]
    days = [list(d) for d in a["days"]]
    for it in extra:
        items.append(it)
        for d in days:
            if d[0] == it["start"]:
                d[1], d[2] = it["trip"], "-"
    W.pub_pilot({"emp": "10999", "name": "Roe, Rick", "status": "ok", "month": "2026-12", "updated": "Nov 17, 2026 03:16:30",
                 "fetched": "2026-11-17T16:00:00+00:00", "days": days, "items": items,
                 "totals": {"block": "52:12", "credit": "71:39", "days_off": 15}})
    return [p for t, p in W.SENT if t == "pilot_schedule"][-1]


def _pilot_render(tmp_path, attrs, widths, tag):
    if not shutil.which("node"):
        pytest.skip("node not installed")
    if subprocess.run(["node", "-e", "require('playwright')"], capture_output=True).returncode:
        pytest.skip("node Playwright not installed")
    f = tmp_path / f"attrs_{tag}.json"
    f.write_text(json.dumps(attrs))
    card = tmp_path / "pc.js"
    card.write_text(cards.build("9.9.9", [])["flight-watcher-pilot-card.js"])
    out = subprocess.run(["node", os.path.join(HERE, "fw1711_pilot_render.js"), str(card), str(f), SHOTS or "", widths, f"review_{tag}"],
                         capture_output=True, text=True, timeout=240)
    assert out.returncode == 0, out.stderr
    r = json.loads(out.stdout.strip().splitlines()[-1])
    if r.get("skip"):
        pytest.skip(r["skip"])
    return r


def _fits(v, m):
    assert m["doc"] <= m["win"], (v, m["doc"], m["win"])
    assert m["table"]["r"] <= m["wrap"]["r"] + 0.5 and m["wrapScroll"] <= m["wrapClient"] + 1, (v, m["table"], m["wrap"], m["wrapScroll"], m["wrapClient"])
    assert m["payR"] <= m["wrap"]["r"] + 0.5, (v, m["payR"], m["wrap"])  # every Pay-Gross figure whole on screen


@pytest.mark.parametrize("tag", ["plain", "turn1", "turn3"])
def test_the_pilot_cards_grid_fits_every_phone_width(W, tmp_path, monkeypatch, tag):  # noqa: F811
    """F1, F2: at 360, 375 and 390 px, light and dark, the grid fits its box with a one-day turn too (its Layover cell
    wraps, station, R and Rel each whole); every other row keeps one line."""
    extra = {"plain": [], "turn1": [_turn("H9611", "2026-12-25", "FR", ["OGG"])],
             "turn3": [_turn("H9612", "2026-12-25", "FR", ["OGG", "KOA", "LIH"])]}[tag]
    r = _pilot_render(tmp_path, _attrs_with(W, tmp_path, monkeypatch, extra), "360,375,390", tag)
    for v, m in r.items():
        _fits(v, m)
        assert not m["crewTh"] and m["crl"], (v, m["crewTh"], m["crl"])
        rows = {d: h for d, h in m["rowHd"].items() if d != "2026-12-25" or tag == "plain"}
        assert len(set(rows.values())) == 1, (v, sorted(set(rows.values())))


def test_a_wider_card_whose_grid_does_not_fit_lists_the_crew(W, tmp_path, monkeypatch):  # noqa: F811
    """F6: at 820 px (a tablet in portrait) a 4-pilot crew made the grid 870 px in a 788 px box: the crew list replaces
    the Crew column there; at 1024 px the grid fits and keeps it."""
    r = _pilot_render(tmp_path, _pilot_attrs(W, tmp_path, monkeypatch), "820,1024", "wide")
    for v in ("820_light", "820_dark"):
        m = r[v]
        _fits(v, m)
        assert m["crlon"] and m["crl"] and not m["crewTh"] and not m["crewTd"], (v, m["crlon"], m["crl"], m["crewTh"])
        assert len(m["crlLines"]) == 5 and "FO Poe, <i>Pat</i>" in m["crlLines"][3], m["crlLines"]
    for v in ("1024_light", "1024_dark"):
        m = r[v]
        assert not m["crlon"] and not m["crl"] and m["crewTh"] and m["crewTd"], (v, m)


def test_the_pilot_cards_split_title_with_no_duty_times(W, tmp_path, monkeypatch):  # noqa: F811
    """F5: another pilot's H9635 Dec 1 to 3 with no package detail and no legs: the whole trip pays in November (its
    first day's bid period); the title says it starts Dec 1 and no duty times are on file, never 'flown before Dec 2'."""
    _setup(W, tmp_path, monkeypatch, tcrd=False)
    W.DB.put("pkg_details:2026-11", {})
    a = _pilot_attrs(W, tmp_path, monkeypatch)
    W.DB.put("pkg_details:2026-11", {})
    W.SENT.clear()
    items = [{k: v for k, v in it.items() if k not in ("gross", "seat_src", "split", "figs")} for it in a["items"]]
    items[0]["legs"] = []
    W.pub_pilot({"emp": "10999", "name": "Roe, Rick", "status": "ok", "month": "2026-12", "updated": "Nov 17, 2026 03:16:30",
                 "fetched": "2026-11-17T16:00:00+00:00", "days": a["days"], "items": items, "totals": a["totals"]})
    attrs = [p for t, p in W.SENT if t == "pilot_schedule"][-1]
    sp = {it["trip"]: it for it in attrs["items"]}["H9635"]["split"]
    assert sp["none"] is True and sp["placed"] is False, sp
    m = _pilot_render(tmp_path, attrs, "390", "nodu")["390_light"]
    t = m["dec1"][0]["title"]
    assert "H9635: 11:15 block / 15:00 credit in all, starts Dec 1; no duty times on file, so the whole trip pays in the November bid period" in t, t
    assert "flown before" not in t
