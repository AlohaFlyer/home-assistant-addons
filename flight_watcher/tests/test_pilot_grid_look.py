"""1.7.7 (Ryan, Nov 14: "my schedule and other pilots schedule and reconstructed schedules should be exactly the same
style including this latest detail panel"). In Chromium at 390 x 844 (iPhone), 820 x 1180 (iPad) and 1280 x 800
(MacBook), light and dark: Ryan's own month (the schedule card), another pilot's month as FLICA showed it and the month
reconstructed from pairing crew lists (the pilot card), with the same synthetic trips, have the same look: the same
row height, the same day, date, trip and layover cell styles (getComputedStyle), the same layover box markup and R /
Rel times, the same totals line style, and the same pairing detail (a panel below the grid on a wide card, a bottom
sheet on a phone). The other pilot's Pay-Gross column comes from the Watcher's price (his DOH, the seat flown).
Made-up pilots, pairings and hotels only ("Doe, John" 10001, H9101). FW_176_SHOTS=<dir> keeps the screenshots
(deviceScaleFactor 2) as B_<view>_<width>_<scheme>.png."""
import contextlib
import json
import os

import pytest

import cards
import pay as PAY
import pdfs
from test_cards import _chromium
from test_fw171_cards import HARNESS_JS, PORTAL_CSS, _card
from test_pairing_detail import package
from test_pairing_panel_card import OWN, _days, states

ORIGIN = "https://ha.test"
NOW = "2026-11-28T20:00:00Z"  # Nov 28 10:00 HST: the month's trips are flown, so Ryan's rows carry no trade marks
SHOTS = os.environ.get("FW_176_SHOTS", "")
PKG = pdfs.package_json(package(), "synthetic")
CREW = [["CA", "Doe, John"], ["FO", "Roe, Jane"]]
H9101_LEGS = [{"dow": "TH", "flt": "9001", "route": "HNL-SEA", "dep": "2300", "arr": "0642", "blk": "0542"},
              {"dow": "FR", "flt": "9002", "route": "SEA-LAX", "dep": "1815", "arr": "2050", "blk": "0235"},
              {"dow": "SA", "flt": "9003", "route": "SFO-HNL", "dep": "2100", "arr": "0050", "blk": "0550"}]
H3604B_LEGS = [{"dow": "MO", "flt": "9011", "route": "HNL-LAX", "dep": "0800", "arr": "1530", "blk": "0530"},
               {"dow": "TU", "flt": "9012", "route": "LAX-HNL", "dep": "1900", "arr": "2245", "blk": "0545"}]
TRIPS = [  # the same three trips as Ryan's own month (test_pairing_panel_card.states)
    {"pairing": "H9101", "start": "2026-11-05", "end": "2026-11-08", "lay": "SEA", "route": "HNL-SEA-LAX-SFO-HNL",
     "blk": "14:07", "credit": "16:00", "soft": "1:53", "seat": "FO", "n": 3, "legs": H9101_LEGS},
    {"pairing": "H9102", "start": "2026-11-16", "end": "2026-11-17", "lay": "LAX", "route": "HNL-LAX-HNL",
     "blk": "11:15", "credit": "13:15", "soft": "2:00", "seat": "CA", "n": 3, "legs": []},
    {"pairing": "H3604B", "start": "2026-11-23", "end": "2026-11-24", "lay": "LAX", "route": "HNL-LAX-HNL",
     "blk": "10:30", "credit": "12:00", "soft": "1:30", "seat": "FO", "n": 2, "legs": H3604B_LEGS}]
DOH = "2018-10-03"
PRICED, PER = PAY.pay_line([dict(t, crew=CREW) for t in TRIPS], DOH, "2026-11-01", "2026-12-01", 22.0)
LIST = {"list_status": "ok", "list_date": "2026-03-01", "list_newest_doh": "2026-01-05", "seat_list": "FO", "list_source": "list"}
READ = "sensor.flight_watcher_pilot_schedule"
RB = "sensor.flight_watcher_pilot_rebuilt"  # a second card of the same kind, on another entity (the rebuilt month)


def _readable():
    """Another pilot's month as FLICA's Schedule Lookup showed it, priced by the Watcher (pilot_price)."""
    items = [{"trip": t["pairing"], "start": t["start"], "end": t["end"], "lay": t["lay"], "blk": t["blk"], "credit": t["credit"],
              "soft": t["soft"], "seat": t["seat"], "seat_src": "pairing page", "n": t["n"], "crew": CREW, "legs": t["legs"],
              "gross": PER[f"{t['pairing']}|{t['start']}"]} for t in TRIPS]
    pl = dict(PRICED, **LIST, seat_src={"pairing page": 3}, days_off=22)
    return {"emp": "10999", "name": "Roe, Rick", "status": "ok", "month": "2026-11", "updated": "Nov 4, 2026 10:00",
            "fetched": "2026-11-28T19:00:00Z", "days": _days(), "items": items, "items_pay": pl,
            "totals": {"block": "35:52", "credit": "41:15", "days_off": 22}}


def _rebuilt():
    """The same trips as the crew index rebuilt them (FLICA would not show this pilot's month)."""
    rec = [dict({k: v for k, v in t.items() if k != "legs"}, checked_at="2026-11-04T09:00:00", crew=CREW,
                gross=PER[f"{t['pairing']}|{t['start']}"]) for t in TRIPS]
    return {"emp": "10998", "name": "Poe, Pat", "status": "not readable: error", "month": "", "reconstructed_month": "2026-11",
            "reconstructed_from": "2026-11-01", "reconstructed_to": "2026-12-01", "reconstructed_coverage_pct": 90.0,
            "reconstructed": rec, "pay_line": dict(PRICED, **LIST)}


def _states():
    st = states(role="admin")
    lu = "2026-11-28T19:00:00+00:00"
    st[READ] = {"state": "ok", "attributes": _readable(), "last_updated": lu, "last_changed": lu}
    st[RB] = {"state": "x", "attributes": _rebuilt(), "last_updated": lu, "last_changed": lu}
    return st


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


def _page(b, scripts, width, height, scheme):
    ctx = b.new_context(viewport={"width": width, "height": height}, device_scale_factor=2, color_scheme=scheme,
                        timezone_id="Pacific/Honolulu")
    html = ("<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<style>" + PORTAL_CSS + "</style></head><body><main><section class='view'></section></main><script>" + HARNESS_JS
            + "</script>" + "".join(f"<script type='module'>{s}</script>" for s in scripts) + "</body></html>")  # modules, as on HA

    def serve(route):
        url = route.request.url
        if url == ORIGIN + "/":
            return route.fulfill(status=200, content_type="text/html", body=html)
        if "/local/flight-watcher/pairings_2026-11.json" in url:
            return route.fulfill(status=200, content_type="application/json", body=json.dumps(PKG))
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
TAGS = {"own": "flight-watcher-schedule-card", "pilot": "flight-watcher-pilot-card", "recon": "flight-watcher-pilot-card"}


def _mount_all(pg, st):
    pg.evaluate("(st) => { window.OWN = mount('flight-watcher-schedule-card', {}, st, " + OWNER + ");"
                " window.PIL = mount('flight-watcher-pilot-card', {entity: '" + READ + "'}, st, " + OWNER + ");"
                " window.REC = mount('flight-watcher-pilot-card', {entity: '" + RB + "'}, st, " + OWNER + "); }", st)
    # every card has the package in (R / Rel times and the detail come from it)
    pg.wait_for_function("[OWN, PIL, REC].every((c) => c._pk && c._pk['2026-11'] && Object.values(c._pk).every((v) => v !== null))")
    pg.wait_for_timeout(100)


# what makes a cell look as it does; the day cell's teal edge (FAR 30 h break) and its tap cursor are Ryan's
# planning marks (blocked days, FAR 117.25(b)), never on another pilot's grid
CELL = ["fontSize", "fontWeight", "fontFamily", "lineHeight", "color", "backgroundColor", "backgroundImage", "textAlign",
        "verticalAlign", "whiteSpace", "paddingTop", "paddingRight", "paddingBottom", "paddingLeft", "borderTopWidth",
        "borderRightWidth", "borderBottomWidth", "borderLeftWidth", "borderBottomColor", "borderLeftColor", "position", "left", "zIndex"]
SPAN = ["fontSize", "fontWeight", "fontFamily", "color", "cursor", "textDecorationLine", "display", "minWidth", "lineHeight"]
MEASURE = """([cell, span]) => {
  const pick = (el, ks) => { if (!el) return null; const cs = getComputedStyle(el); return Object.fromEntries(ks.map((k) => [k, cs[k]])); };
  const one = (c) => { const r = c.shadowRoot, out = {};
    for (const tr of r.querySelectorAll('.cal tr[data-d]')) {
      if (tr.closest('.rb') && c !== REC) continue;
      const td = tr.children, lay = td[3];
      out[tr.dataset.d] = { h: Math.round(tr.getBoundingClientRect().height * 100) / 100, plan: !!tr.querySelector('.idb, .trb, .drb, .sw'), cls: tr.className.split(' ').filter((x) => /^(wk|hol2|oth|bx|bxs|bxe)$/.test(x)).sort().join(' '),
        day: pick(td[0], cell), date: pick(td[1], cell), tripTd: pick(td[2], cell), layTd: { ...pick(lay, cell), box: getComputedStyle(lay).boxShadow },
        num: pick(td[4], cell), trip: pick(td[2].querySelector('.trip'), span), tag: pick(lay.querySelector('.tag.lay'), span),
        tm: [...lay.querySelectorAll('.tm')].map((x) => x.textContent), tmStyle: pick(lay.querySelector('.tm'), span),
        lay: lay.querySelector('.tag.lay') ? lay.querySelector('.tag.lay').innerHTML : '', dayText: td[0].textContent, dateText: td[1].textContent,
        st: [...lay.querySelectorAll('.st')].map((x) => x.className + ' ' + x.textContent), stStyle: pick(lay.querySelector('.st'), span) };
    }
    const tot = r.querySelector('.rb .tot') && c === REC ? r.querySelector('.rb .tot') : r.querySelector('.tot');
    return { rows: out, tot: pick(tot, ['fontSize', 'fontWeight', 'textAlign', 'display', 'justifyContent', 'color', 'marginTop']),
      totK: pick(tot && tot.querySelector('.k'), ['fontSize', 'fontWeight', 'color', 'marginRight']),
      th: pick(r.querySelector('.cal th:nth-child(5)'), ['fontSize', 'fontWeight', 'textAlign', 'color', 'paddingTop', 'paddingLeft']),
      heads: [...((c === REC ? r.querySelector('.rb .cal') : r.querySelector('.cal')).querySelectorAll('tr.hd th'))].map((x) => x.textContent),
      labels: tot ? [...tot.querySelectorAll('.ti > .k:first-child')].map((x) => x.textContent) : [] };
  };
  return { own: one(OWN), pilot: one(PIL), recon: one(REC), page: document.documentElement.scrollWidth, inner: innerWidth };
}"""


def _shot(pg, name, sel=None):
    if not SHOTS:
        return
    os.makedirs(SHOTS, exist_ok=True)
    path = os.path.join(SHOTS, f"B_{name}.png")
    if sel:
        pg.locator(sel).first.screenshot(path=path)
    else:
        pg.screenshot(path=path)


def _same(a, b, what):
    diff = {k: (a.get(k), b.get(k)) for k in a if a.get(k) != b.get(k)} if a and b else {"missing": (a, b)}
    assert not diff, (what, diff)


def _no_hotels(lines):
    """1.7.7 review: Ryan's detail lines without the hotel and van (another pilot's panel has none: they are not in the
    public pairing file, only on Ryan's own trip times)."""
    import re
    return [re.sub(r"(?: ·)? (?:EXAMPLE(?: (?!VAN\b)[A-Z]+)+|VAN \d{2}:\d{2}L)", "", x) for x in lines]


def _tap(pg, card, k):
    pg.evaluate("([c, k]) => [...window[c].shadowRoot.querySelectorAll('.trip[data-k]')].find((x) => x.dataset.k === k).click()", [card, k])


def _texts(pg, card, sel):
    return pg.evaluate("([c, s]) => [...window[c].shadowRoot.querySelectorAll(s)].map((x) => x.innerText.replace(/\\s+/g, ' ').trim())", [card, sel])


@pytest.mark.parametrize("width,height", [(390, 844), (820, 1180), (1280, 800)])
@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_one_look_for_every_month_grid(width, height, scheme):
    with _browser() as b:
        pg = _page(b, [cards.build("9.9.9", [])[f"{t}.js"] for t in ("flight-watcher-schedule-card", "flight-watcher-pilot-card")],
                   width, height, scheme)
        _mount_all(pg, _states())
        r = pg.evaluate(MEASURE, [CELL, SPAN])
        assert r["page"] <= r["inner"], r["page"]  # no sideways page scroll (the grid scrolls in its own box)
        own, pil, rec = r["own"]["rows"], r["pilot"]["rows"], r["recon"]["rows"]
        assert sorted(own) == [f"2026-11-{d:02d}" for d in range(1, 31)] and set(own) <= set(pil) and set(own) <= set(rec)
        for d in sorted(own):
            o, p, q = own[d], pil[d], rec[d]
            # the same row height; a row where Ryan's card shows a planning mark (the Ideas airplane, the trade and drop
            # arrows: his own schedule only) may be up to that glyph's line taller on a phone, never the other way
            assert p["h"] == q["h"] == pil["2026-11-01"]["h"], (d, p["h"], q["h"])
            assert o["h"] == p["h"] or (o["plan"] and 0 < o["h"] - p["h"] < 0.5), (d, o["h"], p["h"])
            assert o["dayText"] == p["dayText"] == q["dayText"] and o["dateText"] == p["dateText"] == q["dateText"]
            for key in ("day", "date", "tripTd", "layTd", "num"):
                _same(o[key], p[key], (d, key, "readable"))
                _same(o[key], q[key], (d, key, "rebuilt"))
            if o["trip"]:
                _same(o["trip"], p["trip"], (d, "trip", "readable"))
                _same(o["trip"], q["trip"], (d, "trip", "rebuilt"))
            if o["tag"]:
                _same(o["tag"], p["tag"], (d, "layover", "readable"))
                _same(o["tag"], q["tag"], (d, "layover", "rebuilt"))
            # FLICA's month: the very same layover box, layover text and R / Rel times as Ryan's own month
            assert (o["cls"], o["lay"], o["tm"]) == (p["cls"], p["lay"], p["tm"]), (d, o, p)
            # the trip status mark (a check once flown) on the same day, in the same style (1.7.7 review)
            assert o["st"] == p["st"] == q["st"], (d, o["st"], p["st"], q["st"])
            if o["st"]:
                _same(o["stStyle"], p["stStyle"], (d, "status mark"))
            # the rebuilt month: the same boxes; R / Rel where the package times the trip (the crew index has no times of
            # its own, so H3604B, not in the package, has none)
            assert o["cls"] == q["cls"], (d, o["cls"], q["cls"])
            # and the same layover text on every day (1.7.7 review: a rebuilt trip's nights from the package's duties)
            assert p["lay"] == q["lay"], (d, p["lay"], q["lay"])
            assert o["tm"] == q["tm"] or (d in ("2026-11-23", "2026-11-24") and q["tm"] == []), (d, o["tm"], q["tm"])
            if o["tm"]:
                _same(o["tmStyle"], p["tmStyle"], (d, "R / Rel"))
        # the trips' boxes, R and Rel as Ryan's month draws them (the package's report and release, a turn in bold)
        assert [own[d]["tm"] for d in ("2026-11-05", "2026-11-08", "2026-11-16", "2026-11-17", "2026-11-23", "2026-11-24")] == [
            ["R 22:00"], ["Rel 01:05"], ["R 07:00"], ["Rel 23:00"], ["R 07:00"], ["Rel 23:00"]]
        assert own["2026-11-05"]["cls"] == "bx bxs" and own["2026-11-08"]["cls"] == "bx bxe wk"
        assert own["2026-11-11"]["cls"] == "hol2" and pil["2026-11-26"]["cls"] == "hol2"  # Veterans Day, Thanksgiving: hatched
        assert rec["2026-10-31"]["cls"] == "oth wk"  # the rebuilt grid starts on FLICA's day before the bid period
        # the same totals line, header cell and labels; the other pilot's columns and pay
        for v in ("pilot", "recon"):
            _same(r["own"]["tot"], r[v]["tot"], (v, "totals"))
            _same(r["own"]["totK"], r[v]["totK"], (v, "totals label"))
            _same(r["own"]["th"], r[v]["th"], (v, "header"))
            assert r[v]["heads"] == ["", "", "Trip", "Layover", "Block", "Credit", "Soft", "Pay-Gross", "Crew"], r[v]["heads"]
        assert r["own"]["heads"][:8] == ["", "", "Trip", "Layover", "Block", "Credit", "Soft", "Pay-Gross"]
        assert r["pilot"]["labels"] == ["Credit", "Block", "Soft", "Pay-Gross", "Pay-Net", "Days Off"]
        assert r["recon"]["labels"] == ["Trips", "Credit", "Block", "Soft", "Pay-Gross", "Pay-Net", "Days Off"]
        assert r["own"]["labels"][:2] == ["Credit", "Block"]
        rows = _texts(pg, "PIL", ".cal tr[data-d='2026-11-16']")
        assert rows == [f"MO 16 H9102 LAX ✔ R 07:00 11:15 13:15 2:00 ${round(PER['H9102|2026-11-16']):,} CA Doe, John · FO Roe, Jane"], rows
        tot = _texts(pg, "PIL", ".frame > .tot")[0]
        assert tot.startswith("Credit 41:15 ✓ Block 35:52 ✓ Soft 5:23 Pay-Gross") and "Days Off 22" in tot, tot
        assert "Year 9 (DOH 2018-10-03)" in _texts(pg, "PIL", ".prate")[0]
        # WCAG AA for every text in the other pilot's grids (fwContrast: computed colours over their backgrounds)
        assert pg.evaluate("() => [PIL, REC].flatMap((c) => fwContrast(c).fails.map((f) => f.text))") == []
        tag = f"{width}_{scheme}"
        _shot(pg, f"own_{tag}", "flight-watcher-schedule-card")
        _shot(pg, f"pilot_{tag}", "flight-watcher-pilot-card >> nth=0")
        pg.evaluate("() => { const d = REC.shadowRoot.querySelector('details.rb'); if (d) d.open = true; }")
        _shot(pg, f"recon_{tag}", "flight-watcher-pilot-card >> nth=1")
        # the pairing detail: the same one Ryan's card opens, for the same pairing
        narrow = width <= 700
        _tap(pg, "OWN", "H9101|2026-11-05")
        sel = ".fwss .fwgsl" if narrow else ".fwgpt tbody tr"
        pg.wait_for_function("OWN.shadowRoot.querySelector('" + (".fwss .fwgsl" if narrow else ".fwgp") + "')")
        want = _texts(pg, "OWN", sel)
        pg.keyboard.press("Escape")
        for card, k in (("PIL", "H9101|2026-11-05"), ("REC", "H9101|2026-11-05")):
            pg.evaluate("(c) => window[c].scrollIntoView()", card)  # the card on screen under its sheet (the shots)
            _tap(pg, card, k)
            if narrow:
                pg.wait_for_function(f"!{card}.shadowRoot.querySelector('.fwsh').hidden")
                pg.wait_for_timeout(350)
                s = pg.evaluate("(c) => { const r = window[c].shadowRoot, d = r.querySelector('.fwss'), t = r.getElementById(d.getAttribute('aria-labelledby'));"
                                " const rc = d.getBoundingClientRect(); return {role: d.getAttribute('role'), modal: d.getAttribute('aria-modal'),"
                                " title: t && t.textContent, focus: r.activeElement && r.activeElement.className, h: Math.round(rc.height), bottom: Math.round(rc.bottom),"
                                " panel: r.querySelectorAll('.body .fwgp').length, pdh: [...r.querySelectorAll('tr.pdh')].map((x) => x.dataset.d)}; }", card)
                assert s == {"role": "dialog", "modal": "true", "title": "H9101 : 05NOV", "focus": "pdx", "h": round(0.6 * height),
                             "bottom": height, "panel": 0, "pdh": ["2026-11-05", "2026-11-06", "2026-11-07", "2026-11-08"]}, s
                assert _texts(pg, card, sel) == _no_hotels(want)
                if card == "PIL":
                    _shot(pg, f"pilot_sheet_{tag}")
                pg.locator(f"{TAGS['pilot']} >> nth={0 if card == 'PIL' else 1}").locator(".fwss .pdx").click()
                assert pg.evaluate("(c) => window[c].shadowRoot.querySelector('.fwsh').hidden", card) is True
            else:
                pg.wait_for_function(f"{card}.shadowRoot.querySelector('.fwgp')")
                pg.wait_for_timeout(500)
                s = pg.evaluate("(c) => { const r = window[c].shadowRoot, p = r.querySelector('.fwgp'), w = p.previousElementSibling;"
                                " return {below: !!w && w.classList.contains('wrap') && !!w.querySelector('.trip[aria-expanded=\"true\"]'),"
                                " next: p.nextElementSibling && p.nextElementSibling.className, title: r.querySelector('#fwgpt').textContent,"
                                " pdh: [...r.querySelectorAll('tr.pdh')].map((x) => x.dataset.d), sheet: r.querySelector('.fwsh').hidden,"
                                " crew: [...p.querySelectorAll('.fwgpl')].map((x) => x.innerText.replace(/\\s+/g, ' ').trim()).pop()}; }", card)
                assert s == {"below": True, "next": "tot", "title": "H9101 : 05NOV", "sheet": True,
                             "pdh": ["2026-11-05", "2026-11-06", "2026-11-07", "2026-11-08"], "crew": "Crew: CA Doe, John FO Roe, Jane Seat: FO"}, s
                assert _texts(pg, card, sel) == _no_hotels(want)
                if card == "PIL":
                    _shot(pg, f"pilot_panel_{tag}", "flight-watcher-pilot-card >> nth=0")
                pg.keyboard.press("Escape")
                assert pg.evaluate("(c) => window[c].shadowRoot.querySelectorAll('.fwgp').length", card) == 0
        assert pg.errors == []


def test_a_pairing_the_package_lacks_shows_the_legs_read_and_why():
    """H3604B (a pairing FLICA rebuilt) is not in the package: the detail draws the legs the pairing page gave, says why,
    and the report and release come from those legs (first departure - 1:00, last arrival + 0:15)."""
    with _browser() as b:
        pg = _page(b, [cards.build("9.9.9", [])[f"{t}.js"] for t in ("flight-watcher-schedule-card", "flight-watcher-pilot-card")],
                   1280, 800, "light")
        _mount_all(pg, _states())
        _tap(pg, "PIL", "H3604B|2026-11-23")
        pg.wait_for_function("PIL.shadowRoot.querySelector('.fwgp')")
        legs = _texts(pg, "PIL", ".fwgpt tr.lg")
        assert legs == ["MO 23 9011 HNL-LAX 08:00 15:30 5:30 5:30", "TU 24 9012 LAX-HNL 19:00 22:45 5:45 5:45"], legs
        notes = _texts(pg, "PIL", ".fwgpn")
        assert notes[0] == "H3604B is not in the November 2026 pairings package: the package detail is not on file."
        assert notes[1] == "Seat FO from the pairing page's crew line."
        assert notes[2].startswith("Pay-Gross $") and notes[-1].startswith("From FLICA's pairing page: each leg's departure")
        lines = _texts(pg, "PIL", ".fwgpl")
        assert lines[0] == "Block 10:30 Credit 12:00 Soft 1:30 Report 07:00 Mon Nov 23 HST Release 23:00 Tue Nov 24 HST", lines
        # a trip with no pairing page read and no package: what is known, and why
        st = _states()
        st[READ]["attributes"]["items"][2]["legs"] = []
        st[READ]["attributes"]["items"][2].update(blk="", credit="", soft="")
        st[READ]["last_updated"] = "2026-11-28T19:30:00+00:00"
        pg.evaluate("(st) => { PIL.hass = mkHass(st, " + OWNER + "); }", st)
        notes = _texts(pg, "PIL", ".fwgpn")
        assert notes[0].endswith("The Watcher read no pairing page for this trip either."), notes
        assert pg.errors == []


def test_the_pilot_card_keeps_working_with_its_detail_open():
    """The versions arrows, the close button and a Watcher update leave the card drawn; a new pilot closes the detail."""
    with _browser() as b:
        pg = _page(b, [cards.build("9.9.9", [])["flight-watcher-pilot-card.js"]], 390, 844, "light")
        st = _states()
        pg.evaluate("(st) => { window.PIL = mount('flight-watcher-pilot-card', {entity: '" + READ + "'}, st); }", st)
        pg.wait_for_function("PIL._pk && PIL._pk['2026-11']")
        _tap(pg, "PIL", "H9102|2026-11-16")
        pg.wait_for_function("!PIL.shadowRoot.querySelector('.fwsh').hidden")
        lines = _texts(pg, "PIL", ".fwss .fwgsl")
        assert lines == ["9011 HNL-LAX 08:00-15:30 blk 5:30", "9012 LAX-HNL 19:00-22:45 blk 5:45"], lines
        pg.evaluate("() => { PIL.shadowRoot.querySelector('.fwss').mark = 3; }")
        st[READ]["last_updated"] = "2026-11-28T19:40:00+00:00"
        pg.evaluate("(st) => { PIL.hass = mkHass(st); }", st)
        assert pg.evaluate("() => [PIL.shadowRoot.querySelector('.fwss').mark, PIL.shadowRoot.querySelector('.fwsh').hidden]") == [3, False]
        # another pilot looked up: the detail closes
        st[READ] = {"state": "ok", "attributes": dict(_readable(), emp="10997", name="Moe, Kai"), "last_updated": "2026-11-28T19:50:00+00:00"}
        pg.evaluate("(st) => { PIL.hass = mkHass(st); }", st)
        assert pg.evaluate("() => [PIL.shadowRoot.querySelector('.fwsh').hidden, PIL._pd]") == [True, None]
        assert pg.evaluate("() => document.documentElement.scrollWidth <= innerWidth")
        assert pg.errors == []


def test_the_portal_pilot_copy_draws_the_same_grid_and_detail():
    """The second pilot's copy as the portal serves it (FW_PORTAL on, his entities): the same grid and detail."""
    from test_fw171_cards import _pilot
    with _browser() as b:
        pg = _page(b, [_card("pilot-card")], 390, 844, "dark")
        st = _pilot({READ: _states()[READ]})
        pg.evaluate("(st) => { window.PIL = mount('flight-watcher-pilot-card-pilot2', {}, st); }", st)
        pg.wait_for_function("PIL._pk && PIL._pk['2026-11']")
        assert pg.evaluate("() => PIL.hasAttribute('dark')") is True
        assert pg.evaluate("() => PIL.shadowRoot.querySelectorAll('.cal tr[data-d]').length") == 30
        _tap(pg, "PIL", "H9101|2026-11-05")
        pg.wait_for_function("!PIL.shadowRoot.querySelector('.fwsh').hidden")
        assert _texts(pg, "PIL", ".fwss .fwgsl")[0] == "9001 HNL-SEA 23:00-06:42 blk 5:42"
        pg.wait_for_timeout(300)
        _shot(pg, "pilot_sheet_390_dark_portal_pilot2")
        pg.keyboard.press("Escape")
        assert pg.evaluate("() => PIL.shadowRoot.querySelector('.fwsh').hidden") is True
        assert pg.evaluate("() => window.calls.length") == 0  # a detail only reads
        assert pg.errors == []


def test_own_trip_times_match_the_test_data():
    """The fixture's own trips are the ones the other pilot's month repeats (a guard on this file's data)."""
    assert sorted(OWN) == sorted(f"{t['pairing']}|{t['start']}" for t in TRIPS)
    assert all(PER.get(f"{t['pairing']}|{t['start']}") for t in TRIPS) and PRICED["doh_known"]
