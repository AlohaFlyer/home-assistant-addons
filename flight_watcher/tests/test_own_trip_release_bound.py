"""A trip not in the viewed month's pairings package takes its release from its own return to HNL, bounded by its own
end, read from the month the trip came from. Before, the card searched the VIEWED month's days for the first HNL day
after the trip's start with no bound: a previous-month trip (the package is only the viewed month's) was released on
the viewed month's first HNL day, and a one-day turn on the next trip's return day. That made Nov 1 to 4 mid-trip
("-") in the 30 h in 7 d column, Nov 5 "need 30" (FAR 117.25(b)), spread the turn's block over 9 days in the 100 h in
672 h column (FAR 117.23(b)(1)), put the October turn's Legal next (PWA 10.E.1.a) on Nov 7 and stretched the trip box
in the Layover column. Synthetic months, made-up trips, no FLICA, rendered in Chromium at 390 px."""
import pytest

from test_cards import _chromium
from test_release_a_schedule_card import _src

JS = """(h) => { const c = document.createElement('flight-watcher-schedule-card'); c.setConfig({});
  document.body.appendChild(c); c.hass = {states: h, callService: async () => {}};
  return new Promise((res) => setTimeout(() => { c.hass = {states: h, callService: async () => {}};
    const r = c.shadowRoot; const out = {};
    for (const tr of r.querySelectorAll('tr[data-d]')) out[tr.dataset.d] = {cls: tr.className,
      far: [...tr.querySelectorAll('td.far')].map((td) => td.textContent.trim()),
      lg: ((tr.querySelector('td.lg') || {}).textContent || '').trim()};
    res(out); }, 300)); }"""


def _month(y, m, n, marks):
    days = [[f"{y}-{m:02d}-{d:02d}", "", ""] for d in range(1, n + 1)]
    for d, tr, ly in marks:
        days[d - 1] = [f"{y}-{m:02d}-{d:02d}", tr, ly]
    return days


def _st():
    octo = {"items": [{"trip": "H9030", "start": "2026-10-30", "end": "2026-10-30", "lay": ""}],
            "days": _month(2026, 10, 31, [(30, "H9030", "")]), "totals": {}, "updated": "Oct 29, 2026"}
    nov = {"items": [{"trip": "H9105", "start": "2026-11-05", "end": "2026-11-07", "lay": "LAX"},
                     {"trip": "H9110", "start": "2026-11-12", "end": "2026-11-12", "lay": ""},
                     {"trip": "H9115", "start": "2026-11-14", "end": "2026-11-16", "lay": "SEA"},
                     {"trip": "H9130", "start": "2026-11-30", "end": "2026-12-02", "lay": "SYD"}],
           "days": _month(2026, 11, 30, [(5, "H9105", "LAX"), (6, "", "-"), (7, "", "HNL"), (12, "H9110", ""),
                                         (14, "H9115", "SEA"), (15, "", "-"), (16, "", "HNL"),
                                         (30, "H9130", "SYD")]),
           "totals": {}, "updated": "Nov 10, 2026"}
    trips = {"H9030|2026-10-30": {"report": "06:00", "last_arr": "18:00", "blk": "10:00"},  # no duties
             "H9110|2026-11-12": {"report": "07:00", "last_arr": "15:00", "blk": "6:00",
                                  "duties": [{"dep": 480, "arr": 900, "stn": "HNL", "blk": 360}]},
             "H9115|2026-11-14": {"report": "09:00", "last_arr": "13:00", "blk": "12:00"},
             "H9130|2026-11-30": {"report": "10:00", "last_arr": "06:00", "blk": "18:00"}}
    a = lambda attrs: {"state": "1", "last_updated": "a", "attributes": attrs}  # noqa: E731
    return {"sensor.flight_watcher_schedule": a({"updated": "", "source": "", "months": {"2026-10": octo,
                                                                                         "2026-11": nov}}),
            "sensor.flight_watcher_schedule_versions": a({"months": {}}),
            "sensor.flight_watcher_own_trip_times": a({"trips": trips}),
            "input_number.flight_watcher_month_offset": {"state": "0", "last_updated": "a"},
            "sensor.flight_watcher_state": {"state": "idle", "last_updated": "a", "attributes": {"role": "pilot"}}}


@pytest.fixture(scope="module")
def rows():
    sync_api = pytest.importorskip("playwright.sync_api")
    page = ("<!doctype html><html><body><script>customElements.define('ha-card', class extends HTMLElement {});"
            "window.fetch = async () => ({ok: false, json: async () => ({})});</script><script>" + _src()
            + "</script></body></html>")  # no pairings package on file
    with sync_api.sync_playwright() as p:
        b = _chromium(p)
        if not b:
            pytest.skip("no Chromium for Playwright")
        try:
            pg = b.new_page(viewport={"width": 390, "height": 844})
            pg.clock.set_fixed_time("2026-11-10T11:30:00Z")
            pg.set_content(page)
            got = pg.evaluate(JS, _st())
        finally:
            b.close()
    return got


def test_previous_month_turn_is_released_on_its_own_day(rows):
    for d in ("2026-11-01", "2026-11-02", "2026-11-03", "2026-11-04"):
        assert rows[d]["far"][0] != "–", (d, rows[d])  # not mid-trip
        assert rows[d]["far"][0].startswith("✓"), (d, rows[d])  # 30 h free met (FAR 117.25(b))
    assert rows["2026-11-05"]["far"][0].startswith("✓"), rows["2026-11-05"]  # not "need 30"
    # the turn's 10:00 block sits on Oct 30 only (FAR 117.23(b)(1)), not spread up to Nov 7
    assert rows["2026-11-01"]["far"][1] == "10:00" and rows["2026-11-03"]["far"][1] == "10:00", rows["2026-11-03"]
    assert rows["2026-11-07"]["lg"] == "", rows["2026-11-07"]  # no Legal next from the October turn
    for d in ("2026-11-01", "2026-11-02", "2026-11-03", "2026-11-04"):
        assert " bx" not in rows[d]["cls"], (d, rows[d])  # no trip box carried from October
    assert " bxs" in rows["2026-11-05"]["cls"] and " bxe" in rows["2026-11-07"]["cls"]  # H9105's own box only


def test_turn_not_in_package_ends_on_its_own_day_not_the_next_trips_return(rows):
    assert rows["2026-11-12"]["lg"] == "02:15 +1", rows["2026-11-12"]  # 15:15 release + 11 h (PWA 10.E.1.a)
    assert rows["2026-11-16"]["lg"] == "00:15 +1", rows["2026-11-16"]  # H9115's own 13:15 release, not the turn's
    cls = rows["2026-11-12"]["cls"]
    assert " bx" in cls and " bxs" in cls and " bxe" in cls, cls  # the box opens and closes on Nov 12
    assert " bx" not in rows["2026-11-13"]["cls"], rows["2026-11-13"]
    assert rows["2026-11-13"]["far"][0].startswith("✓"), rows["2026-11-13"]  # not mid-trip
    assert rows["2026-11-12"]["far"][1] == "16:00", rows["2026-11-12"]  # 10:00 Oct 30 + 6:00 Nov 12


def test_trips_with_a_return_day_keep_it(rows):
    """Regression guards: a 3-day trip is still released on its own HNL day (Nov 16), and a trip running into the
    next month keeps the end its item carries (Dec 2: no box end and no Legal next in November)."""
    assert " bxs" in rows["2026-11-14"]["cls"] and " bxe" in rows["2026-11-16"]["cls"], rows["2026-11-16"]
    assert rows["2026-11-15"]["far"][0] == "\u2013", rows["2026-11-15"]  # a real layover day: mid-trip
    assert " bxs" in rows["2026-11-30"]["cls"] and " bxe" not in rows["2026-11-30"]["cls"], rows["2026-11-30"]
    assert rows["2026-11-30"]["lg"] == "", rows["2026-11-30"]
