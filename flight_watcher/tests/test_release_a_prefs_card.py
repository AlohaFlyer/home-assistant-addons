"""1.6.2 (Release A item 12): the Schedule card flags pay settings the Watcher copied from never-set HA helpers (pref
entity attribute unconfirmed: federal 0 %, state 0 %, longevity year 1) with "Set your tax and longevity in Pay
settings", opens Pay settings, and Keep these confirms them (one set_value each, the portal's pref/set); with nothing
flagged nothing changes. A pilot's copy, synthetic month, Chromium at 390 px."""
import os

import pytest

import cards
from test_cards import _chromium
from test_release_a_schedule_card import _award

WWW = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "www")
P = "flight_watcher_james"


def _states(flag):
    a = {"unconfirmed": True} if flag else {}
    return {
        f"sensor.{P}_schedule": {"state": "", "last_updated": "a", "attributes": {"updated": "Nov 9, 2026", "months": {
            "2026-11": {"items": _award()["items"], "days": _award()["days"], "totals": {}, "updated": "Nov 9, 2026"}}}},
        f"input_number.{P}_month_offset": {"state": "0", "last_updated": "a"},
        f"input_number.{P}_federal_tax_pct": {"state": "0.0", "last_updated": "a", "attributes": a},
        f"input_number.{P}_state_tax_pct": {"state": "0.0", "last_updated": "a", "attributes": a},
        f"input_number.{P}_longevity_year": {"state": "1.0", "last_updated": "a", "attributes": a},
        f"sensor.{P}_state": {"state": "idle", "last_updated": "a", "attributes": {"role": "pilot"}}}


def test_never_set_pay_settings_are_flagged_and_kept_on_request():
    sync_api = pytest.importorskip("playwright.sync_api")
    src = cards.pilot_copy(open(os.path.join(WWW, "flight-watcher-schedule-card.js"), encoding="utf-8").read(), "james")
    page = ("<!doctype html><html><body><script>customElements.define('ha-card', class extends HTMLElement {});"
            "window.calls = [];</script><script>" + src + "</script></body></html>")
    with sync_api.sync_playwright() as p:
        b = _chromium(p)
        if not b:
            pytest.skip("no Chromium for Playwright")
        try:
            pg = b.new_page(viewport={"width": 390, "height": 844})
            pg.clock.set_fixed_time("2026-11-10T11:30:00Z")
            pg.set_content(page)
            got = {}
            for name, flag in (("flagged", True), ("plain", False)):
                got[name] = pg.evaluate("""(h) => { window.calls = [];
                    const c = document.createElement('flight-watcher-schedule-card-james');
                    c.setConfig({}); document.body.appendChild(c);
                    c.hass = {states: h, callService: async (d, s, data) => window.calls.push([d, s, data])};
                    const r = c.shadowRoot; const q = (s) => r.querySelector(s);
                    const out = {ubn: q('.ubn') && q('.ubn').textContent, open: q('details.set').open,
                                 summary: q('details.set summary').textContent, keep: !!q('.set .keep'),
                                 wide: document.documentElement.scrollWidth};
                    if (q('.set .keep')) q('.set .keep').click();
                    out.calls = window.calls.map((c) => [c[0], c[1], c[2].entity_id, c[2].value]);
                    c.remove();
                    return out; }""", _states(flag))
        finally:
            b.close()
    f = got["flagged"]
    assert f["ubn"].startswith("Set your tax and longevity in Pay settings")
    assert "federal tax, state tax, longevity year are not set yet" in f["ubn"]
    assert f["open"] is True and f["summary"] == "Pay settings (not set yet)" and f["keep"] and f["wide"] <= 390
    assert f["calls"] == [["input_number", "set_value", f"input_number.{P}_federal_tax_pct", 0],
                          ["input_number", "set_value", f"input_number.{P}_state_tax_pct", 0],
                          ["input_number", "set_value", f"input_number.{P}_longevity_year", 1]]
    n = got["plain"]
    assert n["ubn"] is None and n["open"] is False and n["summary"] == "Pay settings" and not n["keep"] and n["calls"] == []
