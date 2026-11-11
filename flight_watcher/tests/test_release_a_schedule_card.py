"""1.6.2 (Release A, item 5): the Schedule card shows the awarded line from the award file, labeled, while FLICA's
schedule for the month is not read, and the last read's status ("FLICA schedule not read: <reason> at HH:MM HST; next
try HH:MM HST"). Synthetic month and made-up trips; rendered in Chromium at the portal's 390 px."""
import os

import pytest

from test_cards import _chromium

WWW = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "www")
LABEL = "Awarded line from the award file. FLICA schedule not read yet."


def _src():
    return open(os.path.join(WWW, "flight-watcher-schedule-card.js"), encoding="utf-8").read()


def _award():
    days = [[f"2026-11-{d:02d}", "", ""] for d in range(1, 31)]
    days[2], days[3] = ["2026-11-03", "H9101", "SFO"], ["2026-11-04", "", "HNL"]
    return {"ver": "11.001", "n": 1, "award": True, "at": "2026-11-10T11:04:25+00:00", "updated": "Award",
            "items": [{"trip": "H9101", "start": "2026-11-03", "end": "2026-11-04", "lay": "SFO"}], "days": days,
            "totals": {"credit": "86:32"}, "trips": {}, "changes": ["awarded line (PBS bid run)"]}


def _states(months, versions, status, updated=""):
    sched = {"updated": updated, "source": "", "months": months}
    if status is not None:
        sched["read_status"] = status
    return {
        "sensor.flight_watcher_schedule": {"state": "", "last_updated": "a", "attributes": sched},
        "sensor.flight_watcher_schedule_versions": {"state": "1", "last_updated": "a", "attributes": {
            "months": versions}},
        "input_number.flight_watcher_month_offset": {"state": "0", "last_updated": "a"},
        "sensor.flight_watcher_state": {"state": "idle", "last_updated": "a", "attributes": {"role": "pilot"}}}


FAILED = {"ok": False, "why": "Schedule Lookup: not a schedule page; mobile schedule: FLICA answered 'invalid or "
                              "unspecified bid period'", "at_hst": "01:04", "next_hst": "01:14", "tries": 2}


def test_schedule_card_draws_the_awarded_line_labeled_and_the_read_status():
    sync_api = pytest.importorskip("playwright.sync_api")
    page = ("<!doctype html><html><body><script>customElements.define('ha-card', class extends HTMLElement {});"
            "window.calls = [];</script><script>" + _src() + "</script></body></html>")
    cases = [
        ("award", _states({}, {"2026-11": {"count": 1, "current": "11.001", "awarded": "11.001",
                                           "versions": [_award()]}}, FAILED)),
        ("nothing", _states({}, {}, FAILED)),
        ("read", _states({"2026-11": {"items": _award()["items"], "days": _award()["days"], "totals": {},
                                      "updated": "Nov 9, 2026"}}, {}, {"ok": True, "why": "", "at_hst": "01:05"}, "Nov 9, 2026")),
    ]
    with sync_api.sync_playwright() as p:
        b = _chromium(p)
        if not b:
            pytest.skip("no Chromium for Playwright")
        try:
            pg = b.new_page(viewport={"width": 390, "height": 844})
            pg.clock.set_fixed_time("2026-11-10T11:30:00Z")
            pg.set_content(page)
            got = {}
            for name, st in cases:
                got[name] = pg.evaluate("""(h) => { const c = document.createElement('flight-watcher-schedule-card');
                    c.setConfig({}); document.body.appendChild(c);
                    c.hass = {states: h, callService: async (d, s, data) => window.calls.push([d, s, data])};
                    const r = c.shadowRoot; const q = (s) => r.querySelector(s);
                    return {awl: q('.awl') && q('.awl').textContent, rsl: q('.rsl') && q('.rsl').textContent,
                            none: q('.none') && q('.none').textContent, rows: r.querySelectorAll('.cal tr').length,
                            trip: (r.querySelector('.cal') || {textContent: ''}).textContent.includes('H9101'),
                            upd: !!q('.u'), wide: document.documentElement.scrollWidth}; }""", st)
            calls = pg.evaluate("window.calls.map((c) => c[2].topic || '')")
        finally:
            b.close()
    a = got["award"]
    assert a["awl"] == LABEL and a["trip"] and a["rows"] >= 31 and a["none"] is None
    assert a["rsl"] == ("FLICA schedule not read: Schedule Lookup: not a schedule page; mobile schedule: FLICA answered"
                        " 'invalid or unspecified bid period' at 01:04 HST; next try 01:14 HST")
    assert not a["upd"]  # no 'updated' with nothing after it
    n = got["nothing"]
    assert n["awl"] is None and n["none"] == "No schedule for November yet." and n["rsl"].startswith("FLICA schedule not read")
    r = got["read"]
    assert r["awl"] is None and r["rsl"] is None and r["trip"] and r["upd"]  # a read schedule: as before
    assert "flight_watcher/improved/set" not in calls  # the award alone never reports an Improved-Pay-Gross


# ---------------------------------------------------------------- 1.6.2 review
def _render(cases, src=None):
    sync_api = pytest.importorskip("playwright.sync_api")
    page = ("<!doctype html><html><body><script>customElements.define('ha-card', class extends HTMLElement {});"
            "window.calls = [];</script><script>" + (src or _src()) + "</script></body></html>")
    with sync_api.sync_playwright() as p:
        b = _chromium(p)
        if not b:
            pytest.skip("no Chromium for Playwright")
        try:
            pg = b.new_page(viewport={"width": 390, "height": 844})
            pg.clock.set_fixed_time("2026-11-10T11:30:00Z")
            pg.set_content(page)
            return {name: pg.evaluate(js, st) for name, js, st in cases}
        finally:
            b.close()


READ_JS = """async (h) => { window.calls = []; const c = document.createElement('flight-watcher-schedule-card');
  c.setConfig({}); document.body.appendChild(c);
  c.hass = {states: h, callService: async (d, s, data) => window.calls.push([d, s, data])};
  await new Promise((ok) => setTimeout(ok, 50));  // 1.7.1 (F#32): the pairings package settles (none here) first
  const r = c.shadowRoot, q = (s) => r.querySelector(s);
  const out = {text: r.textContent, ubn: q('.ubn') && q('.ubn').textContent, tot: (q('.tot') || {}).textContent || '',
               improved: window.calls.some((x) => (x[2].topic || '').endsWith('improved/set'))};
  const pay = [...r.querySelectorAll('.pay')].find((x) => x.dataset.btn);
  if (pay) { pay.click(); const er = q('.info .er'); out.box = q('.info').style.display; out.er = !!er;
    if (er) er.click(); out.after = q('.info') ? q('.info').style.display : 'gone';
    out.erCalls = window.calls.filter((x) => x[2].entity_id === 'input_text.flight_watcher_er_trips').map((x) => x[2].value); }
  c.remove(); return out; }"""


def _read(prefs=True, doh=""):
    st = _states({"2026-11": {"items": _award()["items"], "days": _award()["days"], "totals": {"credit": "86:32"},
                              "updated": "Nov 9, 2026"}}, {"2026-11": {"count": 2, "versions": [
                                  _award(), dict(_award(), ver="11.002", award=False)]}},
                 {"ok": True, "why": ""}, "Nov 9, 2026")
    st["sensor.flight_watcher_state"]["attributes"]["doh"] = doh
    st["sensor.flight_watcher_own_trip_times"] = {"state": "1", "last_updated": "a", "attributes": {"trips": {
        "H9101|2026-11-03": {"blk": "10:00", "credit": "12:00", "report": "08:00", "last_arr": "18:00"}}}}
    if prefs:
        for k, v in (("federal_tax_pct", "22.0"), ("state_tax_pct", "7.0"), ("longevity_year", "3.0")):
            st[f"input_number.flight_watcher_{k}"] = {"state": v, "last_updated": "a", "attributes": {}}
    return st


def test_no_pay_settings_and_no_doh_give_the_banner_and_no_rate():
    got = _render([("unset", READ_JS, _read(prefs=False)), ("set", READ_JS, _read(prefs=True))])
    u = got["unset"]
    assert u["ubn"] and u["ubn"].startswith("Set your tax and longevity in Pay settings")
    assert "longevity year" in u["ubn"] and "federal tax" in u["ubn"] and "no pay is figured" in u["ubn"]
    assert "$307.78" not in u["text"] and "year 12" not in u["text"] and not u["improved"]
    assert "set your longevity year" in u["tot"] and "Pay-Gross" not in u["tot"]
    s = got["set"]
    assert s["ubn"] is None and "$" in s["tot"] and s["improved"]  # with a year: pay and Improved-Pay-Gross as before


def test_the_ro15_toggle_inside_the_pay_box_can_be_tapped():
    r = _render([("pay", READ_JS, _read())])["pay"]
    assert r["box"] == "block" and r["er"] and r["erCalls"] == ["+H9101|2026-11-03"]


def test_the_award_only_view_labels_its_totals_award_not_flica():
    award = _states({}, {"2026-11": {"count": 1, "current": "11.001", "awarded": "11.001", "versions": [_award()]}},
                    FAILED)
    got = _render([("award", READ_JS, award), ("read", READ_JS, _read())])
    assert "award 86:32" in got["award"]["tot"] and "FLICA 86:32" not in got["award"]["tot"]
    assert "FLICA 86:32" in got["read"]["tot"]  # a FLICA read: still FLICA's figure
