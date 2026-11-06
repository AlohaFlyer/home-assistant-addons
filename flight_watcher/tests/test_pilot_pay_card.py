"""FW-0062: the pay line under a rebuilt month on the pilot card (synthetic pilots and a made-up DOH): the schedule
card's totals style, the Watcher's numbers, Pay-Net at the viewer's tax settings, every value escaped, the same grid
choice in Python and in the card, a second pilot's copy, and a 390 px phone with no sideways scroll."""
import json
import os
import shutil
import subprocess

import pytest

import cards
import crewidx as CI
import pay as PAY

CARD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "www", "flight-watcher-pilot-card.js")


def _t(pid, s, e, seat, cr, blk, n, at, route="HNL-NRT-HNL", lay="", soft=""):
    return {"pairing": pid, "start": s, "end": e, "seat": seat, "route": route, "checked_at": at, "lay": lay, "blk": blk,
            "credit": cr, "soft": soft, "n": n, "crew": [["CA", "Doe, Jane"], ["FO", "Roe, Rick"]][:n]}


TRIPS = [_t("H9001", "2026-10-31", "2026-11-02", "FO", "12:34", "9:58", 2, "2026-11-05T13:56:42", "HNL-LAX-HNL", "LAX", "2:36"),
         _t("H9005", "2026-11-05", "2026-11-07", "FO", "10:00", "9:00", 2, "2026-11-01T13:10:00"),  # traded away: also
         _t("H9006", "2026-11-05", "2026-11-07", "CA", "20:00", "17:30", 3, "2026-11-04T09:00:00", lay="NRT", soft="2:30"),
         _t("H9003", "2026-11-12", "2026-11-14", "RO", "16:30", "14:00", 3, "2026-11-04T09:00:00", soft="2:30"),
         _t("H9004", "2026-11-20", "2026-11-23", "FO", "20:00", "17:30", 4, "2026-11-04T09:00:00", "HNL-SIN-HNL", "SIN", "2:30"),
         _t("<img src=x>", "2026-11-26", "2026-11-26", "FO", "", "", 2, "2026-11-04T09:00:00"),  # no credit, hostile id
         _t("H9007", "2026-12-01", "2026-12-03", "FO", "16:35", "16:35", 2, "2026-11-06T01:00:00", "HNL-SYD-HNL")]


def _payload(doh="2018-10-03", status=None):
    grid, _ = CI.grid_pick(TRIPS)
    pl, per = PAY.pay_line(grid, doh, "2026-11-01", "2026-12-01", 22.0)
    pl.update(list_status=status or ("ok" if doh else "none"), list_date="2026-03-01", list_newest_doh="2026-01-05", seat_list="FO")
    return {"emp": "10999", "name": "Roe, Rick", "status": "not readable: error", "month": "", "reconstructed_month": "2026-11",
            "reconstructed_from": "2026-11-01", "reconstructed_to": "2026-12-01", "reconstructed_coverage_pct": 92.5,
            "reconstructed": [dict(t, gross=per.get(f"{t['pairing']}|{t['start']}")) for t in TRIPS], "pay_line": pl}


def _node(js, tmp_path):
    if not shutil.which("node"):
        pytest.skip("node not installed")
    f = tmp_path / "t.js"
    f.write_text("globalThis.HTMLElement = class {}; globalThis.customElements = {define() {}}; globalThis.window = {};\n"
                 + open(CARD, encoding="utf-8").read() + "\n" + js)
    out = subprocess.run(["node", str(f)], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_pay_line_in_the_totals_style(tmp_path):
    a, none, off = _payload(), _payload(""), _payload("", "not_on_list")
    r = _node(f"const c = new FlightWatcherPilotCard(); const a = {json.dumps(a)};\n"
              f"const none = {json.dumps(none)}, off = {json.dumps(off)};\n"
              "const plain = c._recon(a, false), g = c._rebuild(a);\n"
              "c._h = {states: {'input_number.flight_watcher_federal_tax_pct': {state: '20.0'}, 'input_number.flight_watcher_state_tax_pct': {state: '5'}}};\n"
              "console.log(JSON.stringify({plain, taxed: c._recon(a, false), none: c._recon(none, false), off: c._recon(off, false),\n"
              "  items: g.items.map((x) => [x.trip, x.start]), also: g.also.map((x) => x.pairing), tot: g.items.filter((x) => x.start >= g.from).length}));",
              tmp_path)
    pl = a["pay_line"]
    # the card draws the trips the Watcher priced: the same grid (newest read wins), the same totaled trips
    grid, also = CI.grid_pick(TRIPS)
    assert r["items"] == [[t["pairing"], t["start"]] for t in grid] and r["also"] == [t["pairing"] for t in also]
    assert r["tot"] == pl["trips"] == 5
    h = r["plain"]
    bar = h[h.index('<div class="ptot"'):h.index("</div>", h.index('<div class="ptot"'))]
    labels = [x.split("</span>")[0] for x in bar.split('<span class="k">')[1:] if not x.startswith("(") and not x.startswith("est.")]
    assert labels == ["Trips", "Credit", "Block", "Soft", "Pay-Gross", "Pay-Net", "Days Off"]
    assert '<span class="tgrp thrs">' in bar and '<span class="tgrp tpay">' in bar and '<span class="tgrp tdays">' in bar
    gross = "$" + f"{round(pl['gross']):,}"
    assert f'<span class="k">Pay-Gross</span> {gross} <span class="k">(4 of 5 trips)</span>' in bar
    assert f'<span class="k">Pay-Net</span> ${round(pl["gross"] * 0.78):,} <span class="k">est. at your 22% tax</span>' in bar
    assert '<span class="k">Credit</span> 73:05 <span class="k">(4 of 5)</span>' in bar
    assert f'<span class="k">Days Off</span> {pl["days_off"]}</span>' in bar and pl["days_off"] == 31 - 14  # Nov 1-2, 5-7, 12-14, 20-23, 26, Dec 1
    assert "Year 9 (DOH 2018-10-03) · $431.04/cr h CA (PWA 3.C.4) · $295.26/cr h FO/RO (PWA 3.D.6)" in h
    assert "PWA 4.O.1" in bar and "PWA 3.B.1" in bar  # the rules, in the bar's title
    assert "+1 overlapping, +1 before Nov 1: not totaled" in h
    assert "No credit for &lt;img src=x&gt; Nov 26: not priced" in h and "<img" not in h
    assert "Source: crew lines on FLICA pairing pages" in h
    # Pay-Net follows the viewer's own tax settings (20 + 5 %) when the helpers are there
    assert f'${round(pl["gross"] * 0.75):,} <span class="k">est. at your 25% tax</span>' in r["taxed"]
    # no DOH: hours and days, no amounts, and what to do
    assert "Pay-Gross" not in r["none"] and "Days Off" in r["none"] and "Credit</span> 73:05" in r["none"]
    assert "Upload the seniority list on the Web UI for this pilot's pay" in r["none"]
    assert "Not on the seniority list on file (2026-03-01): upload a newer list on the Web UI for this pilot's pay" in r["off"]


def test_old_publish_keeps_the_old_line(tmp_path):
    a = _payload()
    a.pop("pay_line")
    r = _node(f"const c = new FlightWatcherPilotCard(); console.log(JSON.stringify(c._recon({json.dumps(a)}, false)));", tmp_path)
    assert '<div class="tot"><span>Trips<b>5</b>' in r and "ptot" not in r


def test_second_pilot_copy_reads_its_own_tax_helpers():
    f = cards.build("1.4.2", ["james"])
    p = f["flight-watcher-pilot-card-james.js"]
    assert "input_number.flight_watcher_james_federal_tax_pct" in p and "input_number.flight_watcher_james_state_tax_pct" in p
    assert "input_number.flight_watcher_federal_tax_pct" not in p and "Ryan" not in p
    assert "Upload the seniority list on the Web UI for this pilot's pay" in p


def test_pay_line_fits_a_phone():
    """In a real browser: the card at 390 px and 1100 px wide has no sideways scroll outside the grid's own scroller,
    and the pay bar's items stay whole (a label never wraps away from its value)."""
    sync_api = pytest.importorskip("playwright.sync_api")
    from test_cards import _chromium
    a = _payload()
    states = {"sensor.flight_watcher_pilot_schedule": {"last_updated": "a", "attributes": a},
              "input_number.flight_watcher_federal_tax_pct": {"state": "22", "last_updated": "b"},
              "input_number.flight_watcher_state_tax_pct": {"state": "0", "last_updated": "c"}}
    page = ("<!doctype html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<style>body{margin:0;font-family:sans-serif}</style></head><body><script>"
            "customElements.define('ha-card', class extends HTMLElement {});</script><script>"
            + open(CARD, encoding="utf-8").read() + "</script><script>"
            "const c = document.createElement('flight-watcher-pilot-card'); c.setConfig({}); document.body.appendChild(c);"
            f"c.hass = {{states: {json.dumps(states)}, callService() {{}}}};</script></body></html>")
    with sync_api.sync_playwright() as p:
        b = _chromium(p)
        if not b:
            pytest.skip("no Chromium for Playwright")
        try:
            for w in (390, 1100):
                pg = b.new_page(viewport={"width": w, "height": 900})
                pg.set_content(page)
                m = pg.evaluate("""() => {
                  const r = document.querySelector('flight-watcher-pilot-card').shadowRoot;
                  const bar = r.querySelector('.ptot'), card = r.querySelector('ha-card');
                  const items = [...bar.querySelectorAll('.ti')].map((x) => [x.getBoundingClientRect().height, x.getBoundingClientRect().right]);
                  return {doc: document.documentElement.scrollWidth, win: window.innerWidth, card: card.getBoundingClientRect().right,
                          bar: bar.scrollWidth - bar.clientWidth, items, line: r.querySelector('.ti .k').getBoundingClientRect().height};
                }""")
                assert m["doc"] <= m["win"] and m["card"] <= w + 0.5 and m["bar"] <= 0, (w, m)
                assert all(right <= w + 0.5 for _, right in m["items"]), (w, m)
                assert all(hgt < 2 * 22 for hgt, _ in m["items"]), (w, m)  # one line each
                pg.close()
        finally:
            b.close()
