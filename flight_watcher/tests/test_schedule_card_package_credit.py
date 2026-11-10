"""1.6.3: a trip whose own times are not read yet takes its credit from the pairings package, which writes it as
"15h00". The card read only "15:00", so such a trip counted 0:00 and $0 in its row and in the month's Credit and
Pay-Gross (live on a pilot's first day: Credit 0:00, Pay-Gross $0 beside FLICA's 150:28). Synthetic month, made-up
trip and crew, rendered in Chromium at 390 px."""
import json

import pytest

from test_cards import _chromium
from test_release_a_schedule_card import _award, _src, _states

PACKAGE = {"month": "2026-11", "source": "synthetic", "start": "2026-11-01", "end": "2026-11-30",
           "cols": ["id", "report", "dep", "release", "rel_days", "first_duty_min", "route", "credit", "tafb", "days"],
           "rows": [["H9101", "08:00", "09:00", "18:00", 1, 600, "HNL-SFO-HNL", "15h00", "34h00", "3"]]}

JS = """(h) => { const c = document.createElement('flight-watcher-schedule-card'); c.setConfig({});
  document.body.appendChild(c); c.hass = {states: h, callService: async () => {}};
  return new Promise((res) => setTimeout(() => { c.hass = {states: h, callService: async () => {}};
    const r = c.shadowRoot; res({tot: (r.querySelector('.tot') || {}).textContent || '',
      cells: [...r.querySelectorAll('.cal tr')].filter((tr) => tr.textContent.includes('H9101'))
        .map((tr) => [...tr.querySelectorAll('td.t')].map((td) => td.textContent))}); }, 300)); }"""


def _states_with_prefs():
    st = _states({"2026-11": {"items": _award()["items"], "days": _award()["days"], "totals": {"credit": "15:00"},
                              "updated": "Nov 10, 2026"}}, {}, {"ok": True, "why": ""}, "Nov 10, 2026")
    st["sensor.flight_watcher_state"]["attributes"]["doh"] = "2016-03-02"
    for k, v in (("federal_tax_pct", "22.0"), ("state_tax_pct", "7.0"), ("longevity_year", "5.0")):
        st[f"input_number.flight_watcher_{k}"] = {"state": v, "last_updated": "a", "attributes": {}}
    return st  # no sensor own_trip_times: the credit can only come from the package


def test_package_credit_in_h_form_counts_in_the_row_and_the_month_totals():
    sync_api = pytest.importorskip("playwright.sync_api")
    stub = ("window.fetch = async (u) => ({ok: String(u).includes('pairings_2026-11'), json: async () => ("
            + json.dumps(PACKAGE) + ")});")  # parenthesized: an arrow body in braces would be a block
    page = ("<!doctype html><html><body><script>customElements.define('ha-card', class extends HTMLElement {});"
            + stub + "</script><script>" + _src() + "</script></body></html>")
    with sync_api.sync_playwright() as p:
        b = _chromium(p)
        if not b:
            pytest.skip("no Chromium for Playwright")
        try:
            pg = b.new_page(viewport={"width": 390, "height": 844})
            pg.clock.set_fixed_time("2026-11-10T11:30:00Z")
            pg.set_content(page)
            got = pg.evaluate(JS, _states_with_prefs())
        finally:
            b.close()
    assert "Credit 15:00" in " ".join(got["tot"].split()), got["tot"]
    assert "Pay-Gross $0" not in got["tot"] and "Pay-Gross $" in got["tot"], got["tot"]
    assert any("15:00" in row for row in got["cells"]), got["cells"]  # the row's Credit cell, as H:MM
