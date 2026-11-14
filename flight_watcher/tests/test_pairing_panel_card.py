"""1.7.6 (Ryan, Nov 14): tap a pairing on the schedule and its detail opens, like FLICA's pairing printout. On a wide
card (MacBook 1280 px, iPad 820 px) a panel directly below the grid, the trip's rows tinted, scrolled into view;
another pairing swaps it; the same pairing again, the close button or Esc closes it. On a phone (390 px) a bottom
sheet over the schedule (about 60% high, a drag handle, a modal dialog): the backdrop, the close button, Esc or a
swipe down closes it, and a Watcher update leaves it (its node, its scroll) alone. The trade and drop marks and the
lock work as before, and a pairing the package does not have says so. Chromium, light and dark, synthetic data only:
made-up pairings, hotels and crew ("Doe, John", 10001)."""
import contextlib
import json
import os

import pytest

import cards
import pdfs
from test_cards import _chromium
from test_fw171_cards import HARNESS_JS, PORTAL_CSS, _card, _pilot
from test_pairing_detail import package

ORIGIN = "https://ha.test"
NOW = "2026-11-01T20:00:00Z"  # Nov 1 10:00 HST: every trip below is still ahead
SHOTS = os.environ.get("FW_176_SHOTS", "")  # a folder: the renders are saved there (deviceScaleFactor 2)
TAG = "flight-watcher-schedule-card"


def _days():
    lay = {"2026-11-05": ("H9101", "SEA"), "2026-11-06": ("", "SFO"), "2026-11-07": ("", "-"), "2026-11-08": ("", "HNL"),
           "2026-11-16": ("H9102", "LAX"), "2026-11-17": ("", "HNL"), "2026-11-23": ("H3604B", "LAX"), "2026-11-24": ("", "HNL")}
    return [[f"2026-11-{d:02d}", *lay.get(f"2026-11-{d:02d}", ("", ""))] for d in range(1, 31)]


CREW = ["CA Doe, John (10001)", "FO Roe, Jane (10002)"]
OWN = {
    "H9101|2026-11-05": {"report": "22:00", "last_arr": "00:50", "blk": "14:07", "credit": "16:00", "soft": "1:53", "seat": "FO",
                         "crew": CREW, "duties": [
                             {"d": 0, "dep": 1380, "arr": 1722, "stn": "SEA", "blk": 342, "dep_l": "23:00", "arr_l": "06:42"},
                             {"d": 1, "dep": 2415, "arr": 2720, "stn": "SFO", "blk": 155, "dep_l": "18:15", "arr_l": "23:20"},
                             {"d": 2, "dep": 4020, "arr": 4370, "stn": "HNL", "blk": 350, "dep_l": "21:00", "arr_l": "00:50"}]},
    "H9102|2026-11-16": {"report": "07:00", "blk": "11:15", "credit": "13:15", "seat": "FO", "crew": CREW},
    "H3604B|2026-11-23": {"report": "07:00", "last_arr": "22:45", "blk": "10:30", "credit": "12:00", "soft": "1:30", "seat": "FO",
                          "crew": ["CA Doe, Jim (10003)", "FO Roe, Jane (10002)"], "duties": [
                              {"d": 0, "dep": 480, "arr": 810, "stn": "LAX", "blk": 330, "dep_l": "08:00", "arr_l": "15:30"},
                              {"d": 1, "dep": 2340, "arr": 2685, "stn": "HNL", "blk": 345, "dep_l": "19:00", "arr_l": "22:45"}]},
}


def states(lu="2026-11-01T19:00:00+00:00", role="admin"):
    items = [{"trip": "H9101", "start": "2026-11-05", "end": "2026-11-08", "lay": "SEA"},
             {"trip": "H9102", "start": "2026-11-16", "end": "2026-11-17", "lay": "LAX"},
             {"trip": "H3604B", "start": "2026-11-23", "end": "2026-11-24", "lay": "LAX"}]
    s = lambda st, a=None: {"state": st, "attributes": a or {}, "last_updated": lu, "last_changed": lu}  # noqa: E731
    return {
        "sensor.flight_watcher_schedule": s("ok", {"updated": "Nov 1, 2026", "months": {"2026-11": {
            "items": items, "days": _days(), "totals": {"block": "35:52", "credit": "41:15", "days_off": 22}}}}),
        "sensor.flight_watcher_own_trip_times": s("3", {"count": 3, "trips": OWN}),
        "input_number.flight_watcher_month_offset": s("0"),
        "sensor.flight_watcher_state": s("watching", {"role": role, "doh": "2012-03-04"}),
    }


PKG = pdfs.package_json(package(), "synthetic")
OLD = {k: v for k, v in PKG.items() if k not in ("detail", "dv")}  # a file an older Watcher wrote


@contextlib.contextmanager
def _browser():
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as p:
        b = _chromium(p)
        if not b:
            pytest.skip("no Chromium for Playwright")
        try:
            yield b
        finally:
            b.close()


def _page(b, src, width, height, scheme="light", pkg=PKG, files=None):
    """A page at https://ha.test/ with the portal's theme variables, the harness (mount, mkHass) and the card; the
    November pairings file answers pkg (None: 404), files {month: json} the other months', everything else 404. Console errors and page errors are kept
    (a 404's own 'Failed to load resource' line aside)."""
    ctx = b.new_context(viewport={"width": width, "height": height}, device_scale_factor=2, color_scheme=scheme,
                        timezone_id="Pacific/Honolulu")
    html = ("<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<style>" + PORTAL_CSS + "</style></head><body><main><section class='view'></section></main><script>" + HARNESS_JS
            + "</script><script>" + src + "</script></body></html>")

    def serve(route):
        url = route.request.url
        if url == ORIGIN + "/":
            return route.fulfill(status=200, content_type="text/html", body=html)
        if "/local/flight-watcher/pairings_2026-11.json" in url and pkg is not None:
            return route.fulfill(status=200, content_type="application/json", body=json.dumps(pkg))
        for mk, j in (files or {}).items():
            if f"/local/flight-watcher/pairings_{mk}.json" in url:
                return route.fulfill(status=200, content_type="application/json", body=json.dumps(j))
        return route.fulfill(status=404, body="")
    ctx.route(ORIGIN + "/**", serve)
    pg = ctx.new_page()
    pg.errors = []
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    pg.on("console", lambda m: pg.errors.append(m.text) if m.type == "error" and "Failed to load resource" not in m.text else None)
    pg.clock.set_fixed_time(NOW)
    pg.goto(ORIGIN + "/")
    return pg


OWNER = "{user: {id: 'owner', name: 'Owner', is_admin: true, is_owner: true}}"


def _mount(pg, st, tag=TAG, month="2026-11"):
    pg.evaluate("([tag, st]) => { window.C = mount(tag, {}, st, " + OWNER + "); }", [tag, st])
    pg.wait_for_function(f"C._pk && C._pk['{month}'] !== null && C._pk['{month}'] !== undefined")


def _q(pg, js):
    return pg.evaluate("() => { const r = C.shadowRoot, q = (s) => r.querySelector(s), qa = (s) => [...r.querySelectorAll(s)]; "
                       + js + " }")


def _tap(pg, k):
    pg.locator(f'{TAG} .trip[data-k="{k}"], {TAG}-pilot2 .trip[data-k="{k}"]').first.click()


def _shot(pg, name, full=True):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        pg.screenshot(path=os.path.join(SHOTS, f"A_{name}.png"), full_page=full)


def _contrast_fails(pg):
    return pg.evaluate("() => fwContrast(C).fails.map((f) => f.text)")


@pytest.mark.parametrize("width,height", [(1280, 800), (820, 1180)])
@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_wide_panel_below_the_grid(width, height, scheme):
    with _browser() as b:
        pg = _page(b, cards.build("9.9.9", [])["flight-watcher-schedule-card.js"], width, height, scheme)
        _mount(pg, states())
        before = set(_contrast_fails(pg))
        _tap(pg, "H9101|2026-11-05")
        pg.wait_for_function("C.shadowRoot.querySelector('.fwgp')")
        pg.wait_for_timeout(700)  # the smooth scroll settles
        r = _q(pg, """const p = q('.fwgp'), wrap = q('.wrap'), rc = p.getBoundingClientRect();
          return {order: [wrap.nextElementSibling === p, p.nextElementSibling === q('.tot')], title: q('#fwgpt').textContent,
            role: p.getAttribute('role'), label: p.getAttribute('aria-labelledby'), head: q('.fwgph').textContent,
            legs: qa('.fwgpt tr.lg').map((t) => t.innerText.replace(/\\s+/g, ' ').trim()),
            ends: qa('.fwgpt tr.de').map((t) => t.innerText.replace(/\\s+/g, ' ').trim()),
            foot: q('.fwgpt tfoot').innerText.replace(/\\s+/g, ' ').trim(), lines: qa('.fwgpl').map((x) => x.innerText.replace(/\\s+/g, ' ').trim()),
            pdh: qa('tr.pdh').map((t) => t.dataset.d), exp: q('.trip[data-k="H9101|2026-11-05"]').getAttribute('aria-expanded'),
            seen: rc.top >= 0 && rc.top < innerHeight, sheet: q('.fwsh').hidden, wide: document.documentElement.scrollWidth <= innerWidth,
            dark: C.hasAttribute('dark'), tint: getComputedStyle(q('tr.pdh td:nth-child(3)')).backgroundImage};""")
        assert r["order"] == [True, True] and r["role"] == "region" and r["label"] == "fwgpt"
        assert r["title"] == "H9101 : 05NOV" and r["sheet"] is True and r["wide"] and r["dark"] == (scheme == "dark")
        for bit in ("THU ONLY", "BSE REPT: 22:00L", "Operates: Nov 5-Nov 26", "Base/Equip: HNL/332"):
            assert bit in r["head"], (bit, r["head"])
        assert r["legs"] == ["TH 05 9001 HNL-SEA 23:00 06:42 5:42 5:42 5:42 6:57/6:42 SEA 10:18",
                             "FR 06 9002 SEA-LAX 18:15 20:50 2:35",
                             "FR 06 DH 1127* LAX-SFO 21:50 23:20 1:30 1:00 2:35 1:30 3:20 6:20/3:35 SFO 20:25",
                             "SA 07 9003 SFO-HNL 21:00 00:50 5:50 5:50 5:50 7:05/6:50"]
        assert r["ends"] == ["D-END: 06:57L REPT: 17:15L EXAMPLE LAKE HOTEL VAN 16:15L", "D-END: 23:35L REPT: 20:00L EXAMPLE BAY INN"]
        assert r["foot"] == "Total 14:07 1:30 16:00 20:22/17:07"
        assert r["lines"][0] == ("D-END: 01:05L T.A.F.B.: 51:05 TRIP RIG: 1:08 (credit less the legs' credit) "
                                 "Report 22:00 Thu Nov 5 HST Release 01:05 Sun Nov 8 HST")
        assert r["lines"][1] == "Crew: CA 10001 Doe, John FO 10002 Roe, Jane Seat: FO"
        assert r["pdh"] == ["2026-11-05", "2026-11-06", "2026-11-07", "2026-11-08"] and r["exp"] == "true"
        assert r["seen"] and "linear-gradient" in r["tint"]
        assert not (set(_contrast_fails(pg)) - before), set(_contrast_fails(pg)) - before  # WCAG AA in the panel
        _shot(pg, f"wide_{width}_{scheme}")
        # another pairing swaps it
        _tap(pg, "H9102|2026-11-16")
        pg.wait_for_function("C.shadowRoot.querySelector('#fwgpt') && C.shadowRoot.querySelector('#fwgpt').textContent.startsWith('H9102')")
        r = _q(pg, "return {pdh: qa('tr.pdh').map((t) => t.dataset.d), n: qa('.fwgp').length, head: q('.fwgph').textContent,"
                   " old: q('.trip[data-k=\"H9101|2026-11-05\"]').getAttribute('aria-expanded')};")
        assert r["pdh"] == ["2026-11-16", "2026-11-17"] and r["n"] == 1 and r["old"] == "false"
        assert "MON TUE WED ONLY" in r["head"] and "Operates: Nov 2-Dec 1" in r["head"] and "Base/Equip: HNL/332" in r["head"]
        # the same pairing again closes it
        _tap(pg, "H9102|2026-11-16")
        assert _q(pg, "return [qa('.fwgp').length, qa('tr.pdh').length, q('.trip[data-k=\"H9102|2026-11-16\"]').getAttribute('aria-expanded')];") == [0, 0, "false"]
        # the close button, then Esc (the focus goes back to the pairing)
        _tap(pg, "H9101|2026-11-05")
        pg.locator(f"{TAG} .fwgp .pdx").click()
        assert _q(pg, "return qa('.fwgp').length;") == 0
        _tap(pg, "H9101|2026-11-05")
        pg.keyboard.press("Escape")
        assert _q(pg, "return [qa('.fwgp').length, r.activeElement && r.activeElement.dataset.k];") == [0, "H9101|2026-11-05"]
        # the keyboard: Enter on the focused pairing opens it
        pg.keyboard.press("Enter")
        assert _q(pg, "return q('#fwgpt') && q('#fwgpt').textContent;") == "H9101 : 05NOV"
        pg.keyboard.press("Escape")
        # a pairing the package does not have: what FLICA's pairing page gave, and why
        _tap(pg, "H3604B|2026-11-23")
        pg.wait_for_function("C.shadowRoot.querySelector('.fwgpn') && !C.shadowRoot.querySelector('.fwgpn').textContent.startsWith('Loading')")
        r = _q(pg, "return {legs: qa('.fwgpt tr.lg').map((t) => t.innerText.replace(/\\s+/g, ' ').trim()),"
                   " notes: qa('.fwgpn').map((x) => x.textContent), lines: qa('.fwgpl').map((x) => x.innerText.replace(/\\s+/g, ' ').trim()),"
                   " pdh: qa('tr.pdh').map((t) => t.dataset.d)};")
        assert r["legs"] == ["MO 23 Duty to LAX 08:00 15:30 5:30 5:30", "TU 24 Duty to HNL 19:00 22:45 5:45 5:45"]
        assert r["notes"][0] == "H3604B is not in the November 2026 pairings package: the package detail is not on file."
        assert r["notes"][1].startswith("From FLICA's pairing page")
        assert r["lines"][0].startswith("Block 10:30 Credit 12:00 Soft 1:30 Report 07:00 Mon Nov 23 HST")
        assert r["pdh"] == ["2026-11-23", "2026-11-24"]
        _shot(pg, f"wide_{width}_{scheme}_not_in_package")
        assert pg.errors == []


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_bottom_sheet_on_a_phone(scheme):
    with _browser() as b:
        pg = _page(b, cards.build("9.9.9", [])["flight-watcher-schedule-card.js"], 390, 844, scheme)
        _mount(pg, states())
        before = set(_contrast_fails(pg))
        _tap(pg, "H9101|2026-11-05")
        pg.wait_for_function("!C.shadowRoot.querySelector('.fwsh').hidden")
        pg.wait_for_timeout(400)  # the slide in
        r = _q(pg, """const d = q('.fwss'), rc = d.getBoundingClientRect(), t = r.getElementById(d.getAttribute('aria-labelledby'));
          return {role: d.getAttribute('role'), modal: d.getAttribute('aria-modal'), title: t && t.textContent, inSheet: !!(t && d.contains(t)),
            focus: r.activeElement && r.activeElement.className, h: Math.round(rc.height), bottom: Math.round(rc.bottom),
            lines: qa('.fwss .fwgsl').map((x) => x.textContent), lay: qa('.fwss .fwgso').map((x) => x.textContent),
            panel: qa('.fwm .fwgp').length, pdh: qa('tr.pdh').length, wide: document.documentElement.scrollWidth <= innerWidth,
            pad: getComputedStyle(d).paddingBottom, over: getComputedStyle(q('.fwsc')).overscrollBehaviorY};""")
        assert r["role"] == "dialog" and r["modal"] == "true" and r["title"] == "H9101 : 05NOV" and r["inSheet"]
        assert r["focus"] == "pdx" and r["panel"] == 0 and r["pdh"] == 4 and r["wide"] and r["over"] == "contain"
        assert abs(r["h"] - 0.6 * 844) <= 2 and r["bottom"] == 844 and r["pad"] == "12px"
        assert r["lines"] == ["9001 HNL-SEA 23:00-06:42 blk 5:42", "9002 SEA-LAX 18:15-20:50 blk 2:35",
                              "DH 1127* LAX-SFO 21:50-23:20 blk 1:30 · grnd 1:00", "9003 SFO-HNL 21:00-00:50 blk 5:50"]
        assert r["lay"] == ["SEA 10:18 · EXAMPLE LAKE HOTEL · VAN 16:15L · REPT 17:15L", "SFO 20:25 · EXAMPLE BAY INN · REPT 20:00L"]
        assert not (set(_contrast_fails(pg)) - before), set(_contrast_fails(pg)) - before
        _shot(pg, f"sheet_390_{scheme}", full=False)
        # a Watcher update: the same sheet node, its scroll kept, still open
        sc = _q(pg, "const c = q('.fwsc'); q('.fwss').mark = 7; c.scrollTop = 60; return [c.scrollTop, c.scrollHeight > c.clientHeight];")
        assert sc[1], "the sheet's content should scroll at 390 x 844"
        pg.evaluate("(st) => { C.hass = mkHass(st, " + OWNER + "); }", states(lu="2026-11-01T19:30:00+00:00"))
        assert _q(pg, "return [q('.fwss').mark, q('.fwsc').scrollTop, q('.fwsh').hidden, qa('tr.pdh').length];") == [7, sc[0], False, 4]
        # Tab stays inside the sheet
        pg.keyboard.press("Tab")
        assert _q(pg, "return q('.fwss').contains(r.activeElement);")
        # the backdrop closes it, the focus goes back to the pairing
        pg.locator(f"{TAG} .fwsb").click(position={"x": 195, "y": 120})
        assert _q(pg, "return [q('.fwsh').hidden, r.activeElement && r.activeElement.dataset.k, qa('tr.pdh').length];") == [True, "H9101|2026-11-05", 0]
        # the close button, Esc
        _tap(pg, "H9101|2026-11-05")
        pg.wait_for_timeout(300)
        pg.locator(f"{TAG} .fwss .pdx").click()
        assert _q(pg, "return q('.fwsh').hidden;") is True
        _tap(pg, "H9101|2026-11-05")
        pg.wait_for_timeout(300)
        pg.keyboard.press("Escape")
        assert _q(pg, "return q('.fwsh').hidden;") is True
        # a short drag on the handle springs back; a swipe down past 80 px closes it
        _tap(pg, "H9101|2026-11-05")
        pg.wait_for_timeout(300)
        box = pg.locator(f"{TAG} .fwsg").bounding_box()
        x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        pg.mouse.move(x, y)
        pg.mouse.down()
        pg.mouse.move(x, y + 40, steps=4)
        pg.mouse.up()
        assert _q(pg, "return [q('.fwsh').hidden, q('.fwss').style.transform];") == [False, ""]
        pg.wait_for_timeout(350)  # it springs back (the slide transition)
        pg.mouse.move(x, y)
        pg.mouse.down()
        pg.mouse.move(x, y + 90, steps=4)
        assert _q(pg, "return q('.fwss').style.transform;") == "translateY(90px)"
        pg.mouse.move(x, y + 150, steps=4)
        pg.mouse.up()
        assert _q(pg, "return q('.fwsh').hidden;") is True
        # a swipe on the sheet's header works too
        _tap(pg, "H9101|2026-11-05")
        pg.wait_for_timeout(300)
        hb = pg.locator(f"{TAG} .fwgsh h4").bounding_box()
        pg.mouse.move(hb["x"] + 10, hb["y"] + 5)
        pg.mouse.down()
        pg.mouse.move(hb["x"] + 10, hb["y"] + 200, steps=6)
        pg.mouse.up()
        assert _q(pg, "return q('.fwsh').hidden;") is True
        assert pg.errors == []


def test_lock_trade_and_drop_marks_still_work():
    """The pairing opens its detail with the lock on (it only reads); "would trade" is the arrow mark's alone and still
    needs the lock off, as do the drop mark and a blocked day."""
    with _browser() as b:
        pg = _page(b, cards.build("9.9.9", [])["flight-watcher-schedule-card.js"], 1280, 800)
        _mount(pg, states())
        assert _q(pg, "return q('.lock').classList.contains('shut');")
        pg.locator(f'{TAG} .trb[data-k="H9101|2026-11-05"]').click()
        r = _q(pg, "return [q('.info').textContent, window.calls.length];")
        assert r[0].startswith("Settings are locked") and r[1] == 0
        _tap(pg, "H9101|2026-11-05")
        assert _q(pg, "return [qa('.fwgp').length, window.calls.length, q('.trip[data-k=\"H9101|2026-11-05\"]').classList.contains('tr')];") == [1, 0, False]
        pg.locator(f"{TAG} .lock").click()
        pg.locator(f'{TAG} .trb[data-k="H9101|2026-11-05"]').click()
        pg.locator(f'{TAG} .drb[data-k="H9102|2026-11-16"]').click()
        pg.locator(f'{TAG} tr[data-d="2026-11-10"] td.n').click()
        calls = pg.evaluate("window.calls.map((c) => [c[2].topic, JSON.parse(c[2].payload)])")
        assert calls == [["flight_watcher/trade/set", {"key": "H9101|2026-11-05"}], ["flight_watcher/drop/set", {"key": "H9102|2026-11-16"}],
                         ["flight_watcher/blocked/set", {"date": "2026-11-10"}]]
        r = _q(pg, "return [q('.trip[data-k=\"H9101|2026-11-05\"]').classList.contains('tr'), q('.trb[data-k=\"H9101|2026-11-05\"]').classList.contains('on'),"
                   " qa('.fwgp').length];")
        assert r == [True, True, 1]  # the trade mark toggled, the detail still open
        assert pg.errors == []


@pytest.mark.parametrize("pkg,note", [
    (None, "No pairings package on file for the bid period of Nov 5: the package detail is not on file."),
    (OLD, "The November 2026 pairings file has no leg detail yet: an older Watcher wrote it, and the next update reads the package again.")])
def test_package_detail_not_on_file(pkg, note):
    with _browser() as b:
        pg = _page(b, cards.build("9.9.9", [])["flight-watcher-schedule-card.js"], 1280, 800, pkg=pkg)
        pg.evaluate("(st) => { window.C = mount('" + TAG + "', {}, st, " + OWNER + "); }", states())
        pg.wait_for_function("C._pk && C._pk['2026-11'] !== null && C._pk['2026-11'] !== undefined")
        _tap(pg, "H9101|2026-11-05")
        r = _q(pg, "return {notes: qa('.fwgpn').map((x) => x.textContent), legs: qa('.fwgpt tr.lg').length, head: q('.fwgph').textContent};")
        assert r["notes"][0] == note and r["legs"] == 3  # FLICA's three duties
        assert ("Operates: Nov 5-Nov 26" in r["head"]) == (pkg is not None)
        assert pg.errors == []


def test_portal_pilot_copy_opens_the_sheet():
    """The second pilot's copy as the portal serves it (FW_PORTAL on, his entities): the same detail and sheet."""
    with _browser() as b:
        pg = _page(b, _card("schedule-card"), 390, 844, "dark")
        pg.evaluate("(st) => { window.C = mount('" + TAG + "-pilot2', {}, st); }", _pilot(states(role="pilot")))
        pg.wait_for_function("C._pk && C._pk['2026-11'] !== null && C._pk['2026-11'] !== undefined")
        assert _q(pg, "return qa('.drb').length;") == 0  # no drop mark on a pilot's card
        _tap(pg, "H9101|2026-11-05")
        pg.wait_for_function("!C.shadowRoot.querySelector('.fwsh').hidden")
        r = _q(pg, "return [q('#fwgst').textContent, qa('.fwss .fwgsl').length, window.calls.length];")
        assert r == ["H9101 : 05NOV", 4, 0]
        pg.wait_for_timeout(300)
        _shot(pg, "sheet_390_dark_portal_pilot", full=False)
        pg.keyboard.press("Escape")
        assert _q(pg, "return q('.fwsh').hidden;") is True
        assert pg.errors == []


def test_a_trip_from_the_bid_period_before():
    """December's grid starts on Dec 1, a day of November's bid period (Nov 1 to Dec 1): a pairing that starts then is
    in November's package, which the panel reads (December's package does not hold Dec 1)."""
    from datetime import date
    from test_pdfs import _pkg
    dec = pdfs.package_json(_pkg("December 2026", "December 2 \u2014December 31 (30 Days)", date(2026, 12, 2), 30,
                                 {"H9201": {date(2026, 12, 9)}}), "synthetic")
    st = states()
    st["input_number.flight_watcher_month_offset"]["state"] = "1"
    days = [[f"2026-12-{d:02d}", "", ""] for d in range(1, 32)]
    days[0], days[1] = ["2026-12-01", "H9102", "LAX"], ["2026-12-02", "", "HNL"]
    st["sensor.flight_watcher_schedule"]["attributes"]["months"]["2026-12"] = {
        "items": [{"trip": "H9102", "start": "2026-12-01", "end": "2026-12-02", "lay": "LAX"}], "days": days, "totals": {}}
    with _browser() as b:
        pg = _page(b, cards.build("9.9.9", [])["flight-watcher-schedule-card.js"], 1280, 800, files={"2026-12": dec})
        _mount(pg, st, month="2026-12")
        _tap(pg, "H9102|2026-12-01")
        pg.wait_for_function("C.shadowRoot.querySelector('#fwgpt') && C.shadowRoot.querySelectorAll('.fwgpt tr.lg').length")
        r = _q(pg, "return {t: q('#fwgpt').textContent, legs: qa('.fwgpt tr.lg').map((x) => x.innerText.replace(/\\s+/g, ' ').trim()),"
                   " notes: qa('.fwgpn').map((x) => x.textContent), pdh: qa('tr.pdh').map((x) => x.dataset.d)};")
        assert r["t"] == "H9102 : 01DEC" and r["legs"][0].startswith("TU 01 9011 HNL-LAX 08:00 15:30")
        assert r["notes"][0].startswith("From the pairings package") and r["pdh"] == ["2026-12-01", "2026-12-02"]
        assert pg.errors == []
