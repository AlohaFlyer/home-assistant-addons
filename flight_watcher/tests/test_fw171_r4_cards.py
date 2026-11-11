"""1.7.1, review r4 fixes in the cards, in a real Chromium on synthetic states (made-up hotel, "Doe, Jane"):
the layover card takes FLICA's rebuilt H3681B and Hark's H3681 as the same trip and never says "no van alert comes"
while the Watcher's van sensor has a van; a long link wraps at 390 px; the package's van and Hark's other time both
show; the note fields are 16 px on a phone; the package source line keeps the route on one line; the Layover pill
reads on Home Assistant's own blue; Report and Departs carry HST and the station's zone. The pot card's fold-outs are
44 px taps and its folded Grid cell says "red 11-21", not "grid red 11-21". The F#119 status colors follow Home
Assistant's dark mode (hass.themes.darkMode), not the phone's."""
import json
import os

import pytest

import cards
import layover as LO
from test_cards import _chromium
from test_fw171_cards import HARNESS_JS, SWAP_JS, _browser, _card, _page as _portal_page, _pot_states
from test_layover_card import HA_DARK, HA_LIGHT, NOW, _page, _states
from test_van_package import package

LEG = {"pairing": "H3681", "start": "2026-11-10", "city": "SYD", "flt": "852", "dep": "21:40", "date": "2026-11-12"}


@pytest.fixture()
def browser():
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as p:
        b = _chromium(p)
        if not b:
            pytest.skip("no Chromium for Playwright")
        try:
            yield b
        finally:
            b.close()


def _pkg_sensor(pairing="H3681", van="19:25"):
    info, _ = LO.package_van([LO.package_vans(package(van=van))], {**LEG, "pairing": pairing})
    assert info, pairing
    return {"state": "x", "last_updated": "v9", "attributes": LO.sensor(info, "", {}, NOW)}


def _open(browser, st, width=390, theme=HA_LIGHT):
    pg = browser.new_page(viewport={"width": width, "height": 844})
    pg.set_content(_page(st, theme=theme))
    return pg, pg.locator("flight-watcher-layover-card")


# ---------------------------------------------------------------- a rebuilt pairing is the same trip (UX #1, adv #2)
def test_a_rebuilt_pairing_shows_harks_van_and_its_countdown(browser, tmp_path):
    st = _states(tmp_path)
    st["sensor.flight_watcher_working_flight"]["attributes"]["pairing"] = "H3681B"  # FLICA rebuilt Ryan's trip
    pg, card = _open(browser, st)
    van = card.locator("[data-van]")
    assert van.locator(".vt").inner_text() == "19:40" and "AEDT" in van.locator(".vz").inner_text()
    assert van.locator("[data-cd]").inner_text() == "in 2 h 10 min"
    assert card.locator("[data-vanunknown]").count() == 0
    assert "Example Harbour Hotel" in card.locator(".sec h3").first.inner_text()  # Hark's hotel section shows
    pg.close()
    # the package's van read from Ryan's H3681B legs, Hark on H3681: the package's time, with its source
    st = _states(tmp_path / "p")
    st["sensor.flight_watcher_working_flight"]["attributes"]["pairing"] = "H3681B"
    st["sensor.flight_watcher_layover_van"] = _pkg_sensor("H3681B")
    pg, card = _open(browser, st)
    v = card.locator("[data-van]")
    assert v.locator(".vt").inner_text() == "19:25" and v.locator("[data-vansrc]").inner_text() == "from the pairings package"
    assert v.locator("[data-cd]").inner_text() == "in 1 h 55 min"
    pg.close()


def test_never_no_van_alert_while_the_watcher_has_a_van(browser, tmp_path):
    """Hark's sensor on another trip than the Watcher's working flight, the Watcher's van sensor holding Hark's van (no
    own layover legs): the card cannot place that van on this flight, but must not say no van alert comes."""
    from test_layover import hark
    st = _states(tmp_path, hark_attrs=hark(pairing="H3999"))
    pg, card = _open(browser, st)
    assert st["sensor.flight_watcher_layover_van"]["attributes"]["at"]  # the Watcher has a van, and sends its alerts
    assert card.locator("[data-vanunknown]").count() == 0
    pg.close()


# ---------------------------------------------------------------- a long link wraps (UX #2)
def test_a_bare_url_never_scrolls_the_phone_page_sideways(browser, tmp_path):
    url = "https://example.invalid/" + "averylongpathsegmentwithnobreak" * 12  # no hyphen or space to break at
    st = _states(tmp_path)
    a = st["sensor.hark_working_flight"]["attributes"]
    a["eat"] = [f"Example Oyster Bar {url}"]
    a["status"] = f"Off. On layover. See {url}"
    root = str(tmp_path / "layovers")
    with open(f"{root}/SYD.guide.md", "w", encoding="utf-8") as f:
        f.write(f"# SYD\n\nCoffee: {url}\n")
    st["sensor.flight_watcher_layover_notes"]["attributes"] = LO.sensor_payload(root, "SYD")
    pg, card = _open(browser, st)
    assert url in card.locator(".guide").inner_text().replace("\n", "")
    assert pg.evaluate("document.documentElement.scrollWidth") <= 390
    pg.close()


# ---------------------------------------------------------------- two van times say which wins (UX #3)
def test_the_package_van_and_harks_other_time_both_show(browser, tmp_path):
    st = _states(tmp_path)
    st["sensor.flight_watcher_layover_van"] = _pkg_sensor()
    pg, card = _open(browser, st)
    v = card.locator("[data-van]")
    assert v.locator(".vt").inner_text() == "19:25"
    assert v.locator("[data-harkvan]").inner_text() == "Hark says 19:40"
    pg.close()
    st = _states(tmp_path / "same")
    st["sensor.flight_watcher_layover_van"] = _pkg_sensor(van="19:40")  # the same time: nothing more to say
    pg, card = _open(browser, st)
    assert card.locator("[data-van] .vt").inner_text() == "19:40" and card.locator("[data-harkvan]").count() == 0
    pg.close()


# ---------------------------------------------------------------- 16 px fields, one-line route, the pill (UX #4-6)
@pytest.mark.parametrize("width,size", [(390, 16), (1100, 14)])
def test_the_note_fields_are_16_px_on_a_phone(browser, tmp_path, width, size):
    pg, card = _open(browser, _states(tmp_path), width=width)
    got = pg.evaluate("[...window.root().querySelectorAll('textarea[data-draft], input[data-city]')]"
                      ".map((e) => parseFloat(getComputedStyle(e).fontSize))")
    assert got == [size, size]
    pg.close()


def test_the_package_source_keeps_the_route_on_one_line(browser, tmp_path):
    st = _states(tmp_path)
    st["sensor.flight_watcher_layover_van"] = _pkg_sensor()
    pg, card = _open(browser, st)
    fl = card.locator(".fl")
    assert "HA852 SYD" in fl.inner_text() and "\n" not in fl.inner_text()
    lh = pg.evaluate("parseFloat(getComputedStyle(window.root().querySelector('.fl')).lineHeight)")
    assert fl.bounding_box()["height"] <= lh + 1  # one line
    assert card.locator("[data-van]").bounding_box()["width"] <= 110
    pg.close()


@pytest.mark.parametrize("theme", [HA_LIGHT, HA_DARK])
def test_the_layover_pill_reads_on_home_assistants_blue(browser, tmp_path, theme):
    pg, card = _open(browser, _states(tmp_path), theme=theme)
    assert card.locator(".mode").inner_text().lower() == "layover syd"
    con = pg.evaluate("window.fwContrast(window.root().host)")
    row = next(r for r in con["fails"] + con["theme"] + [None] if r is None or "Layover" in r["text"])
    assert row is None, row
    assert pg.evaluate("getComputedStyle(window.root().querySelector('.mode')).backgroundColor") == "rgb(1, 87, 155)"
    pg.close()


# ---------------------------------------------------------------- HST and the zone on Report and Departs (UX #7)
def _tm(card):
    return [x.replace("\n", " ") for x in card.locator(".tm > div").all_inner_texts()]


def test_report_and_departs_carry_hst_from_harks_data(browser, tmp_path):
    pg, card = _open(browser, _states(tmp_path))
    tm = _tm(card)
    assert "Report 20:25 AEDT (8:25 PM) Thu 2026-11-12, 23:25 HST" in tm
    assert "Departs 21:40 AEDT (9:40 PM) Thu 2026-11-12, 00:40 HST" in tm
    assert "Arrives 10:45 HST Thu 2026-11-12" in tm  # HST already: unchanged
    pg.close()
    # no van: the Report headline in the van's place carries the HST too
    from test_layover import hark
    st = _states(tmp_path / "nv", hark_attrs=hark(van=""), hark_state="Layover SYD")
    pg, card = _open(browser, st)
    assert card.locator("[data-van] .vl").inner_text().lower() == "report"
    assert "23:25 HST" in card.locator("[data-van] .vz").inner_text()
    pg.close()
    # another trip on the Watcher's sensor: its HST is not borrowed
    st = _states(tmp_path / "o")
    st["sensor.flight_watcher_working_flight"]["attributes"]["pairing"] = ""
    pg, card = _open(browser, st)
    assert "Report 20:25 AEDT (8:25 PM) Thu 2026-11-12" in _tm(card) and "HST" not in _tm(card)[0]
    pg.close()


def test_the_watchers_own_times_name_the_stations_zone(browser, tmp_path):
    st = _states(tmp_path, hark_attrs={})
    st["sensor.flight_watcher_layover_van"] = _pkg_sensor()
    pg, card = _open(browser, st)
    tm = _tm(card)
    assert "Report 20:25 AEDT, 23:25 HST" in tm and "Departs 21:40 AEDT, 00:40 HST" in tm
    assert "Arrives 10:45 local, 10:45 HST" in tm  # at HNL: the van's zone is not its zone
    pg.close()
    st = _states(tmp_path / "nv", hark_attrs={})  # no van sensor: no zone known, "local" stays
    pg, card = _open(browser, st)
    assert "Report 20:25 local, 23:25 HST" in _tm(card)
    pg.close()


# ---------------------------------------------------------------- the pot card (UX #8, #9)
def test_the_pot_cards_fold_outs_are_44_px_and_grid_says_red_once():
    js = SWAP_JS.replace("fit: fwFits(c)}", "fit: fwFits(c), sums: [...r.querySelectorAll('summary')].map((s) => "
                         "s.getBoundingClientRect().height), cells: [...r.querySelectorAll('td[data-l=Grid]')]"
                         ".map((t) => t.textContent)}")
    with _browser() as b:
        got = _portal_page(b, [_card("pot-card")]).evaluate(js, _pot_states())
    assert got["sums"] and min(got["sums"]) >= 44, got["sums"]
    assert got["cells"] == ["OK", "red 11-21"]


# ---------------------------------------------------------------- F#119 colors follow HA's dark mode (UX #10)
DARK_JS = """([tag, dark]) => { const c = document.createElement(tag); c.setConfig({});
  try { c.hass = mkHass({}, dark === null ? {themes: {}} : {themes: {darkMode: dark}}); } catch (e) { /* no states */ }
  document.querySelector('.view').appendChild(c);
  return [c.hasAttribute('dark'), getComputedStyle(c).getPropertyValue('--fw-err').trim()]; }"""


@pytest.mark.parametrize("name", ["settings", "recall", "clock", "pot", "schedule"])
def test_the_status_colors_follow_home_assistants_dark_mode_not_the_phones(name):
    src = cards.build("9.9.9")[f"flight-watcher-{name}-card.js"]
    tag = f"flight-watcher-{name}-card"
    with _browser() as b:
        # Home Assistant's profile forced to Light while the phone is dark: the light colors (no override)
        assert _portal_page(b, [src], scheme="dark").evaluate(DARK_JS, [tag, False]) == [False, ""]
        # forced Dark on a light phone: the lighter red
        assert _portal_page(b, [src], scheme="light").evaluate(DARK_JS, [tag, True]) == [True, "#ef9a9a"]
        # no darkMode given (an older frontend): the phone's, as before
        assert _portal_page(b, [src], scheme="dark").evaluate(DARK_JS, [tag, None]) == [True, "#ef9a9a"]
        assert _portal_page(b, [src], scheme="light").evaluate(DARK_JS, [tag, None]) == [False, ""]


def test_no_em_dash_in_the_fixes_and_the_portal_harness_gives_darkmode():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dash = chr(0x2014)
    for f in ("layover.py", "cards.py", "watcher.py", "tests/test_fw171_r4.py", "tests/test_fw171_r4_cards.py",
              *(f"www/flight-watcher-{n}-card.js" for n in ("layover", "pot", "settings", "recall", "clock", "schedule",
                                                             "tickets"))):
        assert dash not in open(os.path.join(here, f), encoding="utf-8").read(), f
    assert "themes: { darkMode:" in HARNESS_JS  # the portal (HOM) passes the device's mode the same way


# ---------------------------------------------------------------- pre-existing, on Home Assistant's own light theme
HA_VARS_JS = """(css) => { document.documentElement.style.cssText = css; }"""


def _recall_states():
    narr = "On 2026-11-10, Recall pairing H3601 was awarded to a FO with seniority #900, junior to me."
    why = ["went to #900, junior to you (#500)", "open and legal on your line (FAR 117.25(e) 10 h, PWA 10.E.1.a 11 h)"]
    v = {"id": "2026-11-10|H3601|recall", "date": "2026-11-10", "kind": "recall", "pairing": "H3601", "seat": "FO",
         "sen": 900, "pilot": "Doe, Jane", "verdict": "MISSED", "why": why, "refs": ["PWA 22.G.2.e"],
         "act": {"status": "new", "narrative": narr}}
    a = {"open": 1, "alert": 1, "me": {"sen": 500, "seat": "FO"}, "last": "2026-11-10",
         "checked": "2026-11-10T20:00:00+00:00", "received": "2026-11-10T19:00:00+00:00",
         "days": [{"date": "2026-11-10", "file": "ok", "verdicts": [v]}]}
    return {"sensor.flight_watcher_recall_o75": {"state": "1", "attributes": a, "last_updated": "r1", "last_changed": "r1"}}


def test_recall_and_clock_cards_read_on_home_assistants_light_theme_with_44_px_taps():
    """Review r4 (pre-existing, F#119 checked only the portal's palette): a SHOULD HAVE BEEN YOU row's reasons, the
    month arrows and the clock card's Stuck labels at WCAG AA on Home Assistant 2026.11's own light theme, and the
    recall card's buttons 44 px tall on a phone."""
    from test_fw171_cards import _clock_err
    ha = HA_LIGHT.replace("background:#fafafa;color:#212121", "")
    built = cards.build("9.9.9", ["pilot2"])
    with _browser() as b:
        pg = _portal_page(b, [built["flight-watcher-recall-card.js"]])
        pg.evaluate(HA_VARS_JS, ha)
        got = pg.evaluate("""(st) => { const c = mount('flight-watcher-recall-card', {}, st); const r = c.shadowRoot;
          return {con: fwContrast(c), why: r.querySelectorAll('.row.vMISSED .why').length,
                  nv: r.querySelectorAll('.mp .nv').length,
                  btn: [...r.querySelectorAll('button')].filter((e) => e.checkVisibility())
                    .map((e) => [e.textContent.trim(), e.getBoundingClientRect().height])}; }""", _recall_states())
        assert got["why"] and got["nv"] == 2 and got["btn"], got
        assert not got["con"]["fails"], json.dumps(got["con"]["fails"], indent=1)
        assert all(h >= 44 for _, h in got["btn"]), got["btn"]
        pg = _portal_page(b, [_card("clock-card")])
        pg.evaluate(HA_VARS_JS, ha)
        con = pg.evaluate("(st) => { const c = mount('flight-watcher-clock-card-pilot2', {}, st);"
                          " return [c.shadowRoot.querySelector('ha-card').className, fwContrast(c)]; }", _clock_err())
        assert con[0] == "err" and not con[1]["fails"], json.dumps(con[1]["fails"], indent=1)
