"""1.7.6 review fixes, the cards (Chromium; synthetic pilots, pairings and crew only: "Doe, John" 10001, H9101).
Another pilot's month, its versions and the rebuilt month keep the schedule card's look in the cases the first pass
missed: VAC and PAYP days, the trip status mark, a trip carried in from the month before, the rebuilt trip's nights,
row heights while the trips are still ahead, the totals line of an older version, and the trip box in Home Assistant's
dark mode. The pilot card's own status lines keep their look, a plain render fetches only the package it needs, the
phone sheet's focus ring is whole, and Ryan's card closes a detail its version does not draw."""
import copy
import json
import re

import cards
import pay as PAY
from test_pilot_grid_look import (OWNER, RB, READ, _browser, _mount_all, _page, _states, _tap, _texts)

SCRIPTS = None


def _scripts():
    global SCRIPTS
    if SCRIPTS is None:
        b = cards.build("9.9.9", [])
        SCRIPTS = [b["flight-watcher-schedule-card.js"], b["flight-watcher-pilot-card.js"]]
    return SCRIPTS


ROW = """([c, d, rb]) => { const r = window[c].shadowRoot;
  const tr = [...r.querySelectorAll('.cal tr[data-d="' + d + '"]')].find((x) => !!x.closest('.rb') === !!rb); if (!tr) return null;
  const td = tr.children, sp = td[2].querySelector('span');
  return {cls: tr.className.split(' ').filter((x) => /^(wk|vac|bx|bxs|bxe)$/.test(x)).sort().join(' '), h: Math.round(tr.getBoundingClientRect().height * 100) / 100,
    dateWeight: getComputedStyle(td[1]).fontWeight, dateAfter: getComputedStyle(td[1], '::after').content, layWeight: getComputedStyle(td[3]).fontWeight,
    code: sp ? [sp.className, getComputedStyle(sp).color, getComputedStyle(sp).fontWeight, sp.textContent] : ['plain', td[2].textContent],
    lay: (td[3].querySelector('.tag.lay') || td[3]).textContent, st: [...td[3].querySelectorAll('.st')].map((x) => x.className + ' ' + x.textContent),
    box: getComputedStyle(td[3]).boxShadow }; }"""


def _row(pg, card, d, rb=False):
    return pg.evaluate(ROW, [card, d, rb])


def _set_day(days, d, code, lay=""):
    for x in days:
        if x[0] == d:
            x[1], x[2] = code, lay


def test_the_pilot_cards_status_lines_keep_their_look():
    """Its status span (an error page note, the loading line, the pick list's) is the secondary text, never the
    shared grid's green trip-complete mark (.st)."""
    with _browser() as b:
        pg = _page(b, _scripts()[1:], 1280, 800, "light")
        st = _states()
        st[READ]["attributes"] = {"emp": "10999", "name": "Roe, Rick", "status": "not readable: Application Error, call customer care",
                                  "month": "", "days": [], "items": [], "totals": {}, "at": "2026-11-28T19:00:00Z"}
        pg.evaluate("(st) => { window.PIL = mount('flight-watcher-pilot-card', {entity: '" + READ + "'}, st, " + OWNER + "); }", st)
        look = ("() => { const r = PIL.shadowRoot, s = r.querySelector('.hd .pst'); const ref = document.createElement('span'); ref.className = 'u';"
                " r.querySelector('.hd').appendChild(ref); const cs = getComputedStyle(s), cr = getComputedStyle(ref);"
                " const out = {text: s.textContent, color: cs.color, ref: cr.color, weight: cs.fontWeight, cursor: cs.cursor, st: r.querySelectorAll('.hd .st').length}; ref.remove(); return out; }")
        err = pg.evaluate(look)
        assert err["text"].startswith("FLICA showed its error page") and err["color"] == err["ref"]
        assert (err["weight"], err["cursor"], err["st"]) == ("400", "auto", 0)
        pg.evaluate("() => PIL._lookup({detail: {emp: '10997', name: 'Moe, Kai'}})")
        load = pg.evaluate(look)
        assert load["text"].startswith("reading this pilot's month from FLICA") and load["color"] == load["ref"] and load["weight"] == "400"
        st[READ]["attributes"] = {"emp": "", "name": "Doe", "status": "2 pilots named 'Doe'", "month": "",
                                  "matches": [{"emp": "10001", "name": "Doe, John", "pos": "CA"}, {"emp": "10002", "name": "Doe, Jane", "pos": "FO"}]}
        st[READ]["last_updated"] = "2026-11-28T19:30:00+00:00"
        pg.evaluate("(st) => { PIL._ask = null; PIL.hass = mkHass(st, " + OWNER + "); }", st)
        pick = pg.evaluate(look)
        assert pick["color"] == pick["ref"] and pick["weight"] == "400"
        assert pg.errors == []


def _vac_payp(st):
    """Nov 13 and 14 vacation, Nov 19 a PAYP, on Ryan's month and on the other pilot's FLICA month alike."""
    mon = st["sensor.flight_watcher_schedule"]["attributes"]["months"]["2026-11"]
    for days, items in ((mon["days"], mon["items"]), (st[READ]["attributes"]["days"], st[READ]["attributes"]["items"])):
        _set_day(days, "2026-11-13", "VAC")
        _set_day(days, "2026-11-14", "VAC")
        _set_day(days, "2026-11-19", "PAYP")
        items += [{"trip": "VAC", "start": "2026-11-13", "end": "2026-11-14", "lay": ""}, {"trip": "PAYP", "start": "2026-11-19", "end": "2026-11-19", "lay": ""}]
    return st


def test_vac_and_payp_days_look_as_on_ryans_card():
    for scheme in ("light", "dark"):
        with _browser() as b:
            pg = _page(b, _scripts(), 1280, 800, scheme)
            _mount_all(pg, _vac_payp(_states()))
            for d in ("2026-11-13", "2026-11-14", "2026-11-19"):
                o, p = _row(pg, "OWN", d), _row(pg, "PIL", d)
                keep = ("cls", "dateWeight", "dateAfter", "layWeight", "code", "h")
                assert {k: o[k] for k in keep} == {k: p[k] for k in keep}, (scheme, d, o, p)
            o = _row(pg, "OWN", "2026-11-13")
            assert "vac" in o["cls"] and o["dateWeight"] == "600" and "⊘" in o["dateAfter"]
            assert _row(pg, "PIL", "2026-11-19")["code"][:1] == ["payp tag"] and _row(pg, "PIL", "2026-11-19")["code"][2] == "600"
            assert pg.errors == []


def test_the_trip_status_mark_is_on_every_grid():
    """Nov 6 10:00 HST: H9101 (Nov 5 to 8) is flying: the airplane on its first day, on Ryan's grid and both others."""
    with _browser() as b:
        pg = _page(b, _scripts(), 1280, 800, "light")
        pg.clock.set_fixed_time("2026-11-06T20:00:00Z")
        _mount_all(pg, _states())
        marks = [_row(pg, c, "2026-11-05", c == "REC")["st"] for c in ("OWN", "PIL", "REC")]
        assert marks == [["st fly ✈"]] * 3, marks
        assert [_row(pg, c, "2026-11-16", c == "REC")["st"] for c in ("OWN", "PIL", "REC")] == [[]] * 3  # ahead: none
        assert pg.errors == []


def test_rows_are_the_same_height_while_the_trips_are_ahead():
    """Nov 2: Ryan's trip-start rows carry the trade and drop marks; they no longer make his rows taller."""
    for width, height in ((390, 844), (1280, 800)):
        with _browser() as b:
            pg = _page(b, _scripts(), width, height, "light")
            pg.clock.set_fixed_time("2026-11-02T20:00:00Z")
            _mount_all(pg, _states())
            assert pg.evaluate("() => OWN.shadowRoot.querySelectorAll('.trb').length") == 3
            for d in [f"2026-11-{n:02d}" for n in range(1, 31)]:
                o, p, q = _row(pg, "OWN", d), _row(pg, "PIL", d), _row(pg, "REC", d, True)
                assert p["h"] == q["h"] and abs(o["h"] - p["h"]) < 0.5, (width, d, o["h"], p["h"], q["h"])
            # the marks keep their size and place: still a 19 px glyph, tappable
            assert pg.evaluate("() => getComputedStyle(OWN.shadowRoot.querySelector('.trb')).fontSize") == "19px"
            assert pg.errors == []


def test_a_trip_carried_in_from_last_month_is_boxed():
    """H9099 Oct 29 to Nov 1: FLICA's November grid has no code day for it. Ryan's card boxes Nov 1 from the month
    before; the other pilot's grid boxes it from the crew index's trip (it runs into the grid)."""
    with _browser() as b:
        pg = _page(b, _scripts(), 1280, 800, "light")
        st = copy.deepcopy(_states())  # the fixture's own trip times are shared with other tests
        sm = st["sensor.flight_watcher_schedule"]["attributes"]["months"]
        _set_day(sm["2026-11"]["days"], "2026-11-01", "", "HNL")
        sm["2026-10"] = {"items": [{"trip": "H9099", "start": "2026-10-29", "end": "2026-11-01", "lay": "SEA"}], "days": [], "totals": {}}
        st["sensor.flight_watcher_own_trip_times"]["attributes"]["trips"]["H9099|2026-10-29"] = {"report": "22:00", "last_arr": "05:30"}
        a = st[READ]["attributes"]
        a["days"] = [["2026-10-31", "", "SEA"]] + copy.deepcopy(sm["2026-11"]["days"])
        a.update(reconstructed_month="2026-11", reconstructed_from="2026-11-01", reconstructed_to="2026-12-01",
                 reconstructed=[{"pairing": "H9099", "start": "2026-10-29", "end": "2026-11-01", "route": "HNL-SEA-HNL", "seat": "FO",
                                 "checked_at": "2026-10-29T08:00:00", "crew": [["CA", "Doe, John"]]}])
        _mount_all(pg, st)
        o, p = _row(pg, "OWN", "2026-11-01"), _row(pg, "PIL", "2026-11-01")
        assert o["cls"] == p["cls"] == "bx bxe wk" and o["box"] == p["box"] != "none", (o, p)  # a Sunday
        assert p["lay"] == "HNL" and _row(pg, "PIL", "2026-10-31")["cls"] == "bx wk"
        assert "H9099" not in json.dumps(_texts(pg, "PIL", ".frame > .tot"))  # drawn, never totaled
        assert pg.errors == []


def test_the_rebuilt_trip_shows_each_nights_station():
    with _browser() as b:
        pg = _page(b, _scripts()[1:], 1280, 800, "light")
        st = _states()
        pg.evaluate("(st) => { window.PIL = mount('flight-watcher-pilot-card', {entity: '" + READ + "'}, st, " + OWNER + ");"
                    " window.REC = mount('flight-watcher-pilot-card', {entity: '" + RB + "'}, st, " + OWNER + "); }", st)
        pg.wait_for_function("[PIL, REC].every((c) => c._pk && c._pk['2026-11'])")
        pg.wait_for_timeout(100)
        days = ["2026-11-05", "2026-11-06", "2026-11-07", "2026-11-08", "2026-11-16", "2026-11-17"]
        rec = [_row(pg, "REC", d, True)["lay"].split(" ")[0] for d in days]
        assert rec == [_row(pg, "PIL", d)["lay"].split(" ")[0] for d in days] == ["SEA", "SFO", "-", "HNL", "LAX", "HNL"], rec
        assert pg.errors == []


def test_an_older_version_has_the_live_months_totals_line():
    with _browser() as b:
        pg = _page(b, _scripts()[1:], 1280, 800, "light")
        st = _states()
        a = st[READ]["attributes"]
        key = "ab" * 16
        recs = [{"ver": "11.001", "at": "2026-11-01T19:00:00Z", "source": "lookup", "items": [{"trip": "H9101", "start": "2026-11-05", "end": "2026-11-08", "lay": "SEA", "gross": 5000}],
                 "days": a["days"], "totals": {"block": "14:07", "credit": "16:00", "days_off": 26}, "changes": [],
                 "pay": {"gross": 5000, "trips": 1, "trips_priced": 1, "credit": "16:00", "credit_n": 1, "block": "14:07", "block_n": 1, "soft": "1:53", "soft_n": 1}},
                {"ver": "11.002", "at": "2026-11-28T19:00:00Z", "source": "lookup", "items": [], "days": a["days"], "totals": {}, "changes": []}]
        a.update(versions={"2026-11": {"count": 2, "current": "11.002"}}, versions_file_key=key, versions_rev=1)
        pg.route("**/local/flight-watcher/pilotver_*", lambda r: r.fulfill(status=200, content_type="application/json",
                                                                         body=json.dumps({"10999": {"name": "Roe, Rick", "months": {"2026-11": recs}}})))
        pg.evaluate("(st) => { window.PIL = mount('flight-watcher-pilot-card', {entity: '" + READ + "'}, st, " + OWNER + "); }", st)
        pg.wait_for_function("PIL.shadowRoot.querySelector('.vbar .vb[data-v=prev]')")
        live = pg.evaluate("() => [...PIL.shadowRoot.querySelectorAll('.frame > .tot .ti > .k:first-child')].map((x) => x.textContent)")
        pg.evaluate("() => PIL.shadowRoot.querySelector('.vb[data-v=prev]').click()")
        pg.wait_for_function("PIL.shadowRoot.querySelector('.vbar b').textContent === 'v11.001'")
        old = pg.evaluate("() => [...PIL.shadowRoot.querySelectorAll('.frame > .tot .ti > .k:first-child')].map((x) => x.textContent)")
        assert old == ["Credit", "Block", "Soft", "Pay-Gross", "Pay-Net", "Days Off"] == live, (old, live)
        tot = _texts(pg, "PIL", ".frame > .tot")[0]
        assert tot.startswith("Credit 16:00 ✓ Block 14:07 ✓ Soft 1:53 Pay-Gross $5,000"), tot
        assert pg.errors == []


def test_the_phone_sheets_focus_ring_is_whole():
    with _browser() as b:
        pg = _page(b, _scripts(), 390, 844, "light")
        _mount_all(pg, _states())
        for card in ("OWN", "PIL"):
            pg.evaluate("(c) => window[c].scrollIntoView()", card)
            _tap(pg, card, "H9101|2026-11-05")
            pg.wait_for_function(f"!{card}.shadowRoot.querySelector('.fwsh').hidden")
            pg.wait_for_timeout(300)
            pg.keyboard.press("Shift+Tab")
            pg.keyboard.press("Tab")  # keyboard focus: :focus-visible
            r = pg.evaluate("(c) => { const s = window[c].shadowRoot, x = s.querySelector('.fwss .pdx'), box = s.querySelector('.fwss .fwsc');"
                            " const cs = getComputedStyle(x), a = x.getBoundingClientRect(), o = box.getBoundingClientRect();"
                            " const ring = parseFloat(cs.outlineOffset) + parseFloat(cs.outlineWidth);"
                            " return {focus: s.activeElement === x, style: cs.outlineStyle, top: a.top - ring - o.top, right: o.right - (a.right + ring)}; }", card)
            assert r["focus"] and r["style"] == "solid" and r["top"] >= 0 and r["right"] >= 0, (card, r)
            pg.keyboard.press("Escape")
        assert pg.errors == []


def test_ryans_card_closes_a_detail_its_version_does_not_draw():
    with _browser() as b:
        pg = _page(b, _scripts()[:1], 1280, 800, "light")
        st = _states()
        mon = st["sensor.flight_watcher_schedule"]["attributes"]["months"]["2026-11"]
        old_items = [i for i in mon["items"] if i["trip"] != "H9102"]
        old_days = [[d, "" if t == "H9102" else t, "" if d in ("2026-11-16", "2026-11-17") else lay] for d, t, lay in mon["days"]]
        lu = "2026-11-28T19:00:00+00:00"
        st["sensor.flight_watcher_schedule_versions"] = {"state": "2", "last_updated": lu, "last_changed": lu, "attributes": {"months": {"2026-11": {"versions": [
            {"ver": "11.001", "at": "2026-11-01T19:00:00Z", "items": old_items, "days": old_days, "totals": {}, "changes": []},
            {"ver": "11.002", "at": "2026-11-02T19:00:00Z", "items": copy.deepcopy(mon["items"]), "days": copy.deepcopy(mon["days"]), "totals": {}, "changes": []}]}}}}
        pg.evaluate("(st) => { window.OWN = mount('flight-watcher-schedule-card', {}, st, " + OWNER + "); }", st)
        pg.wait_for_function("OWN._pk && OWN._pk['2026-11']")
        _tap(pg, "OWN", "H9102|2026-11-16")
        pg.wait_for_function("OWN.shadowRoot.querySelector('.fwgp')")
        pg.evaluate("() => OWN.shadowRoot.querySelector('.vb[data-v=prev]').click()")
        pg.wait_for_timeout(200)
        r = pg.evaluate("() => { const s = OWN.shadowRoot; return {ver: (s.querySelector('.vbar b') || {}).textContent, panel: s.querySelectorAll('.fwgp').length,"
                        " pdh: s.querySelectorAll('tr.pdh').length, pd: OWN._pd, drawn: !!s.querySelector('.trip[data-k=\"H9102|2026-11-16\"]')}; }")
        assert r == {"ver": "v11.001", "panel": 0, "pdh": 0, "pd": None, "drawn": False}, r
        assert pg.errors == []


def test_a_plain_render_fetches_only_the_package_it_needs():
    """H3604B (FLICA rebuilt it; the package has H3604) used to send the pilot card to the neighbouring months' files on
    every render; now only the trip's own bid period's file is read, until a tap asks for the detail."""
    with _browser() as b:
        pg = _page(b, _scripts()[1:], 1280, 800, "light")
        urls, fails = [], []
        pg.on("request", lambda r: urls.append(r.url.split("/local/flight-watcher/")[1]) if "/pairings_" in r.url else None)
        pg.on("console", lambda m: fails.append(m.text) if "Failed to load resource" in m.text and "404" in m.text else None)
        pg.on("response", lambda r: fails.append(r.url) if r.status == 404 and "/pairings_" in r.url else None)
        st = _states()
        pg.evaluate("(st) => { window.PIL = mount('flight-watcher-pilot-card', {entity: '" + READ + "'}, st, " + OWNER + ");"
                    " window.REC = mount('flight-watcher-pilot-card', {entity: '" + RB + "'}, st, " + OWNER + "); }", st)
        pg.wait_for_timeout(1200)
        assert sorted({re.sub(r"\?.*", "", u) for u in urls}) == ["pairings_2026-11.json"], urls
        assert fails == [] and pg.errors == []


def test_the_trip_box_follows_home_assistants_dark_mode():
    """The device is light and Home Assistant's theme dark (or the other way round): the trip box takes HA's colours,
    like every other dark colour (hass.themes.darkMode, :host([dark]))."""
    for scheme, dark, want in (("light", True, "rgb(187, 187, 187)"), ("dark", False, "rgb(68, 68, 68)")):
        with _browser() as b:
            pg = _page(b, _scripts(), 1280, 800, scheme)
            st = _states()
            ex = "{user: {id: 'owner', name: 'Owner', is_admin: true, is_owner: true}, themes: {darkMode: " + ("true" if dark else "false") + "}}"
            pg.evaluate("(st) => { window.OWN = mount('flight-watcher-schedule-card', {}, st, " + ex + ");"
                        " window.PIL = mount('flight-watcher-pilot-card', {entity: '" + READ + "'}, st, " + ex + "); }", st)
            pg.wait_for_function("[OWN, PIL].every((c) => c._pk && c._pk['2026-11'])")
            for c in ("OWN", "PIL"):
                box = _row(pg, c, "2026-11-05")["box"]
                assert want in box, (scheme, c, box)
            assert pg.errors == []


def test_the_pay_groups_split_and_rate_notes():
    """The other pilot's totals line counts vacation and a PAYP as Ryan's does (Vacation 4:00 (1 d x 4:00); a PAYP of
    unknown credit is said so, and FLICA's credit is shown, not flagged red); a trip into next month shows this month's
    PWA 4.A share; the rate note names a fleet with no rates on file and a mid-month step."""
    with _browser() as b:
        pg = _page(b, _scripts()[1:], 1280, 800, "light")
        st = _states()
        a = st[READ]["attributes"]
        ip = a["items_pay"]
        ip.update(vac="4:00", vac_days=1, payp_unk=True, credit="45:15",
                  rate_steps=[{"from": "2026-11-15", "year": 10, "CA": PAY.rate_for(10, "2026-11-15", "CA"), "FO": PAY.rate_for(10, "2026-11-15", "FO")}])
        a["totals"] = dict(a["totals"], credit="48:00")
        it = a["items"][0]
        it["split"] = {"credit": "11:41", "blk": "10:47", "soft": "0:54", "all_credit": "16:00", "all_blk": "14:07", "out_blk": "5:50", "next": "2026-12"}
        pg.evaluate("(st) => { window.PIL = mount('flight-watcher-pilot-card', {entity: '" + READ + "'}, st, " + OWNER + "); }", st)
        pg.wait_for_function("PIL._pk && PIL._pk['2026-11']")
        tot = _texts(pg, "PIL", ".frame > .tot")[0]
        assert "Vacation 4:00 (1 d x 4:00)" in tot and "PAYP credit unknown" in tot and "FLICA 48:00" in tot, tot
        assert pg.evaluate("() => [...PIL.shadowRoot.querySelectorAll('.frame > .tot .bad')].map((x) => x.textContent)") == ["credit unknown"]
        row = pg.evaluate("() => { const td = PIL.shadowRoot.querySelector('.cal tr[data-d=\"2026-11-05\"]').children;"
                          " return [td[4].textContent, td[5].textContent, td[6].textContent, td[5].className, td[5].title]; }")
        assert row[:4] == ["10:47", "11:41", "0:54", "t split"] and "5:50 block flown from 2026-12 pays next month (PWA 4.A)" in row[4], row
        rate = _texts(pg, "PIL", ".prate")[0]
        assert "from Nov 15 year 10: $" in rate, rate
        # another fleet: no rates on file, so no Pay-Gross and the note says why
        ip.update(equip="717", seat_rates={}, gross=None, trips_priced=0)
        for x in a["items"]:
            x.pop("gross", None)
        st[READ]["last_updated"] = "2026-11-28T19:30:00+00:00"
        pg.evaluate("(st) => { PIL.hass = mkHass(st, " + OWNER + "); }", st)
        rate = _texts(pg, "PIL", ".prate")[0]
        assert "rates for the 717 CA/FO seats are not on file" in rate and "no Pay-Gross" in rate, rate
        assert "Pay-Gross" not in _texts(pg, "PIL", ".frame > .tot")[0]
        assert pg.errors == []
