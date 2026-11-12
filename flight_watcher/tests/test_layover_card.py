"""1.7.1 (FW-0072, Ryan: "Make this page more intuitive and easy to use at a glance"): the layover card in a real
Chromium against synthetic states (a made-up hotel and notes; layover.py builds the Watcher's van and notes sensors
the way the Watcher does). At 390 px the van time sits at the top right in headline size with AEDT, the HST time and a
countdown, readable without scrolling; Update with Hark is a small chip; the layover lists, the hotel's map and phone
links and lazy photo thumbnails show; Release / MEL / NOTAM fold away; it falls back to the Watcher's sensor when
Hark's is absent or for another pairing, and shows Hark's data only on the admin's instance. The notes: the guide is
escaped markdown, a note is sent on flight_watcher/layover/note, Tidy with AI files a feature ticket, delete asks
first. Screenshots at 390 px and 1100 px, light and dark, go to the pytest tmp folder."""
import json
import os
from datetime import datetime, timedelta, timezone

import pytest

import layover as LO
from test_cards import _chromium
from test_fw171_cards import HARNESS_JS
from test_layover import hark

# the contrast check of test_fw171_cards (WCAG AA from the rendered colors), without its harness's ha-card
FW_CONTRAST = HARNESS_JS[HARNESS_JS.index("window.fwContrast"):HARNESS_JS.index("window.fwFits")]

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = open(os.path.join(HERE, "www", "flight-watcher-layover-card.js"), encoding="utf-8").read()
UTC = timezone.utc
VAN = datetime(2026, 11, 12, 8, 40, tzinfo=UTC)
NOW = VAN - timedelta(hours=2, minutes=10)
URL = "https://example.invalid/project/demo"
DARK = ("--primary-color:#03a9f4;--text-primary-color:#ffffff;--secondary-text-color:#9b9b9b;--divider-color:rgba(255,255,255,.12);"
        "--card-background-color:#1c1c1c;--primary-text-color:#e1e1e1;--error-color:#ef5350;--warning-color:#ffa726;"
        "background:#111;color:#e1e1e1")
LIGHT = ("--primary-color:#03a9f4;--text-primary-color:#ffffff;--secondary-text-color:#727272;--divider-color:rgba(0,0,0,.12);"
         "--card-background-color:#fff;--primary-text-color:#212121;--error-color:#c62828;--warning-color:#ef6c00;"
         "background:#f4f4f4;color:#212121")
# Home Assistant 2026.11's own default theme (Pako runs it; read from its frontend bundle): primary #009ac7, warning
# #ffa600, error #db4437, white text on primary. The countdown's urgent colors and the release warning failed AA here.
HA_LIGHT = ("--primary-color:#009ac7;--text-primary-color:#ffffff;--secondary-text-color:#727272;"
            "--divider-color:rgba(0,0,0,.12);--card-background-color:#ffffff;--primary-text-color:#212121;"
            "--error-color:#db4437;--warning-color:#ffa600;background:#fafafa;color:#212121")
HA_DARK = ("--primary-color:#009ac7;--text-primary-color:#ffffff;--secondary-text-color:#9b9b9b;"
           "--divider-color:rgba(225,225,225,.12);--card-background-color:#1c1c1c;--primary-text-color:#e1e1e1;"
           "--error-color:#db4437;--warning-color:#ffa600;background:#111111;color:#e1e1e1")
GUIDE = ("# SYD layover\n\n## Coffee\n- The corner cart on George St, **6 AM**\n- [Map](https://example.invalid/map?a=1&b=2)\n\n"
         "Run: the harbour loop, *about 5 km*.\n\n<img src=x onerror=\"window.pwned=1\"> [bad](javascript:alert(1))\n")


def _hark_full(**kw):
    a = hark(**kw)
    a.update({"tail": "", "status": "Off. On layover at Example Harbour Hotel. Van 7:40 PM (19:40) Thu 2026-11-12.",
              "status_as_of": "2026-11-12 06:35 AEDT", "mel": ["Not updated (HA852 release not out yet)"],
              "notam": ["Not updated"], "release_updated": False, "release_url": "",
              "flightaware_url": "https://www.flightaware.com/live/flight/HAL852", "sigwx_url": "https://aviationweather.gov/gfa/",
              "hotel_map": "https://www.google.com/maps/search/?api=1&query=Example+Harbour+Hotel",
              "hotel_notes": "Breakfast 6:30-10 AM. Gym in hotel.", "weather": "Thu 16-23C, dry.",
              "open_now": ["Hotel cafe until 10 AM"], "eat": ["Example Oyster Bar, 1 Example St"],
              "todo": ["Walk to the harbour", "Ferry ride, 30 min each way"],
              "todo_photos": [{"name": "Harbour", "img": "https://example.invalid/harbour.jpg"},
                              {"name": "Ferry", "img": "http://example.invalid/ferry.jpg"}],
              "transport": "Example Ground Transport", "van_rule": "Roll time 2:00 prior to STD",
              "updated": "2026-11-12 06:35 AEDT", "updated_by": "Hark", "next": "", "mode": "layover"})
    return a


def _states(tmp_path, role="admin", hark_attrs=None, watcher_pairing="H3681", notes=True, van_sensor=True,
            hark_state="Layover SYD, van 2026-11-12 19:40"):
    st = {"sensor.flight_watcher_state": {"state": "idle", "last_updated": "s1", "attributes": {"role": role, "version": "1.7.1"}},
          "sensor.flight_watcher_working_flight": {"state": "HA852 SYD-HNL", "last_updated": "w1", "attributes": {
              "pairing": watcher_pairing, "flight": "HA852" if watcher_pairing == "H3681" else "HA11", "origin": "SYD", "dest": "HNL",
              "leg": "2 of 2", "date": "2026-11-12", "dep_sched": "21:40 local, 00:40 HST", "arr_sched": "10:45 local, 10:45 HST",
              "report": "20:25 local, 23:25 HST", "status": "Scheduled", "updated": "2026-11-11 10:36 HST",
              "updated_by": "Flight Watcher", "flightaware_url": "https://www.flightaware.com/live/flight/HAL852"}}}
    if role is None:  # no state sensor (missing, or HA restarting): no role
        del st["sensor.flight_watcher_state"]
    a = _hark_full() if hark_attrs is None else hark_attrs
    if a:
        st["sensor.hark_working_flight"] = {"state": hark_state, "last_updated": "h1", "attributes": a}
        if van_sensor:
            info, why = LO.van_info(a, hark_state)  # the Watcher's reading, as van_tick makes it
            st["sensor.flight_watcher_layover_van"] = {"state": "x", "last_updated": "v1",
                                                       "attributes": LO.sensor(info, why, {}, NOW)}
    if notes:
        root = str(tmp_path / "layovers")
        LO.add(root, "SYD", "Coffee at the corner cart on George St, 6 AM.", "2026-11-10T20:00:00+00:00")
        LO.add(root, "SYD", "Harbour loop run, about 5 km.\nStart at the hotel.", "2026-11-11T20:00:00+00:00")
        LO.add(root, "LAX", "Beach path run.", "2026-10-01T20:00:00+00:00")
        with open(os.path.join(root, "SYD.guide.md"), "w", encoding="utf-8") as f:
            f.write(GUIDE)
        st["sensor.flight_watcher_layover_notes"] = {"state": "3", "last_updated": "n1",
                                                     "attributes": LO.sensor_payload(root, "SYD")}
    return st


def _page(states, theme=LIGHT, url=URL):
    cfg = {"update_url": url} if url else {}
    return ("<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<style>body{{margin:0;padding:8px 16px;font-family:Roboto,sans-serif;{theme}}}</style></head><body><script>"
            + FW_CONTRAST +
            f"const FIXED = {int(NOW.timestamp() * 1000)}; Date.now = () => FIXED;"
            "customElements.define('ha-card', class extends HTMLElement { constructor() { super(); this.attachShadow({mode: 'open'}).innerHTML ="
            " '<style>:host{display:block;background:var(--card-background-color);border-radius:12px}</style><slot></slot>'; } });"
            "window.calls = [];</script><script>" + SRC + "</script><script>"
            f"const c = document.createElement('flight-watcher-layover-card'); c.setConfig({json.dumps(cfg)}); document.body.appendChild(c);"
            f"window.H = {{states: {json.dumps(states)}, callService: async (d, s, data) => {{ window.calls.push([d, s, data]); }}}};"
            "c.hass = window.H; window.root = () => c.shadowRoot;"
            "window.setStates = (patch) => { window.H = {...window.H, states: {...window.H.states, ...patch}}; c.hass = window.H; };"
            "</script></body></html>")


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


def test_van_time_top_right_headline_at_a_glance_on_a_phone(browser, tmp_path):
    pg = browser.new_page(viewport={"width": 390, "height": 844})
    pg.set_content(_page(_states(tmp_path)))
    card = pg.locator("flight-watcher-layover-card")
    van = card.locator("[data-van]")
    assert van.locator(".vt").inner_text() == "19:40"
    assert "AEDT" in van.locator(".vz").inner_text() and "Thu" in van.locator(".vz").inner_text()
    assert van.locator(".vh").inner_text().strip() == "22:40 HST Wed"
    assert van.locator("[data-cd]").inner_text() == "in 2 h 10 min"
    bb, cb = van.bounding_box(), card.bounding_box()
    assert bb["y"] + bb["height"] < 844 / 2  # readable without scrolling, in the top half
    assert bb["x"] + bb["width"] >= cb["x"] + cb["width"] - 20  # at the card's right edge
    assert bb["y"] - cb["y"] < 30  # at its top
    assert pg.evaluate("parseFloat(getComputedStyle(window.root().querySelector('.vt')).fontSize)") >= 40
    fl = card.locator(".fl").inner_text()
    assert "HA852 SYD" in fl and "HNL" in fl and "H3681" in card.locator(".lt .u").inner_text()
    assert "leg 2 of 2" in card.locator(".lt .u").inner_text()
    assert "Van at Example Harbour Hotel lobby" in card.locator(".vp").inner_text()
    assert "30 min at 22:10 HST" in card.locator(".vp").inner_text()  # the alerts and when they go
    tm = card.locator(".tm").inner_text()
    assert "Report" in tm and "20:25 AEDT" in tm and "Departs" in tm and "21:40 AEDT" in tm
    # a small Update with Hark chip, no big tile
    chip = card.locator("a.chip", has_text="Update with Hark")
    assert chip.get_attribute("href") == URL and chip.get_attribute("target") == "_blank"
    cbb = chip.bounding_box()
    assert cbb["height"] <= 40 and cbb["width"] < 200
    assert pg.evaluate("document.documentElement.scrollWidth") <= 390
    pg.close()


def test_the_countdown_turns_urgent_and_moves_on_its_own(browser, tmp_path):
    pg = browser.new_page(viewport={"width": 390, "height": 844})
    pg.set_content(_page(_states(tmp_path)))
    cd = pg.locator("flight-watcher-layover-card [data-cd]")
    for mins, text, cls in ((25, "in 25 min", "soon"), (8, "in 8 min", "now"), (-3, "3 min ago", "past")):
        pg.evaluate(f"Date.now = () => {int((VAN - timedelta(minutes=mins)).timestamp() * 1000)};"
                    "window.root().host._countdown()")
        assert cd.inner_text() == text and cls in cd.get_attribute("class")
    pg.close()


def test_layover_lists_links_photos_and_folded_release(browser, tmp_path):
    pg = browser.new_page(viewport={"width": 1100, "height": 900})
    pg.set_content(_page(_states(tmp_path)))
    card = pg.locator("flight-watcher-layover-card")
    sec = card.locator(".sec").first
    assert "Example Harbour Hotel" in sec.locator("h3").inner_text()
    assert sec.locator("a", has_text="488").count() == 0  # made-up address only
    addr = sec.locator("a", has_text="1 Example St")
    assert addr.get_attribute("href").startswith("https://www.google.com/maps/") and addr.get_attribute("rel") == "noopener noreferrer"
    assert sec.locator("a[href^='tel:']").get_attribute("href") == "tel:+61200000000"
    for t in ("Weather", "Open now", "Eat", "Things to do", "Transport", "Walk to the harbour", "Example Oyster Bar"):
        assert t in sec.inner_text(), t
    imgs = sec.locator(".ph img")
    assert imgs.count() == 1  # the http photo is left out
    assert imgs.get_attribute("loading") == "lazy" and imgs.get_attribute("alt") == "Harbour"
    rel = card.locator("details.rel")
    assert rel.get_attribute("open") is None and "not updated for this leg yet" in rel.locator("summary").inner_text()
    assert not rel.locator("li", has_text="Not updated (HA852").is_visible()
    rel.locator("summary").click()
    assert rel.locator("li", has_text="Not updated (HA852").is_visible()
    pg.close()


def test_falls_back_to_the_watcher_and_hides_hark_from_a_pilot(browser, tmp_path):
    """Hark's data only while the state sensor says admin: a pilot's copy keeps sensor.hark_working_flight's id, so a
    missing state sensor (or one with no role, as while HA restarts) shows the Watcher's own (review r3, B2). With only
    the Watcher's data the release line is a plain line, not a fold-out with nothing in it (UX review r3, #4)."""
    for kw, why in (({"hark_attrs": {}}, "no Hark sensor"), ({"watcher_pairing": "H3700"}, "Hark on another pairing"),
                    ({"role": "pilot"}, "a pilot's instance"), ({"role": None}, "no state sensor"),
                    ({"role": ""}, "a state sensor with no role")):
        pg = browser.new_page(viewport={"width": 390, "height": 844})
        pg.set_content(_page(_states(tmp_path / why.replace(" ", "_"), **kw)))
        card = pg.locator("flight-watcher-layover-card")
        van = card.locator("[data-van]")
        assert van.locator(".vl").inner_text().lower() == "report", why
        assert van.locator(".vt").inner_text() == "20:25" and "23:25 HST" in van.locator(".vz").inner_text(), why
        assert "From your FLICA schedule" in card.locator("[data-rel]").inner_text(), why
        assert card.locator("details.rel").count() == 0 and card.locator("details summary", has_text="FLICA").count() == 0, why
        assert card.locator(".sec h3", has_text="Example Harbour Hotel").count() == 0, why
        assert "Example" not in card.locator("ha-card").inner_text().split("My notes")[0], why
        pg.close()
    # no trip at all
    st = _states(tmp_path / "none", hark_attrs={}, notes=False)
    st["sensor.flight_watcher_working_flight"]["attributes"] = {"pairing": "", "next": "H3620 LAS 2026-11-20"}
    pg = browser.new_page(viewport={"width": 390, "height": 844})
    pg.set_content(_page(st))
    assert "No trip on your schedule. Next: H3620 LAS 2026-11-20" in pg.locator("flight-watcher-layover-card ha-card").inner_text()
    pg.close()


def test_notes_guide_is_escaped_markdown_and_other_cities_fold(browser, tmp_path):
    pg = browser.new_page(viewport={"width": 390, "height": 844})
    pg.set_content(_page(_states(tmp_path)))
    card = pg.locator("flight-watcher-layover-card")
    notes = card.locator(".notes")
    assert notes.locator("h3").inner_text().endswith("My notes for SYD")
    g = notes.locator(".guide").first
    assert g.locator("h4", has_text="SYD layover").count() == 1 and g.locator("b", has_text="6 AM").count() == 1
    assert g.locator("a").count() == 1 and g.locator("a").get_attribute("href") == "https://example.invalid/map?a=1&b=2"
    assert g.locator("img").count() == 0 and pg.evaluate("window.pwned") is None
    assert "<img src=x" in g.inner_text() and "[bad](javascript:alert(1))" in g.inner_text()
    assert [t.inner_text() for t in notes.locator(".nl .nt").all()][:2] == [
        "Harbour loop run, about 5 km.\nStart at the hotel.", "Coffee at the corner cart on George St, 6 AM."]
    other = notes.locator("details[data-k=others]")
    assert other.get_attribute("open") is None and "Notes for other cities (1)" in other.locator("summary").first.inner_text()
    pg.close()


def test_add_tidy_and_delete_notes(browser, tmp_path):
    pg = browser.new_page(viewport={"width": 390, "height": 844})
    st = _states(tmp_path)
    pg.set_content(_page(st))
    card = pg.locator("flight-watcher-layover-card")
    card.locator("[data-draft]").fill("Ferry at 9: sit upstairs on the left.")
    # a state update redraws the card: what is typed stays
    pg.evaluate("window.setStates({'sensor.flight_watcher_layover_van': {...window.H.states['sensor.flight_watcher_layover_van'], last_updated: 'v2'}})")
    assert card.locator("[data-draft]").input_value() == "Ferry at 9: sit upstairs on the left."
    card.locator("[data-addnote]").click()
    pg.wait_for_function("window.calls.length === 1")
    d, s, data = pg.evaluate("window.calls[0]")
    assert (d, s, data["topic"]) == ("mqtt", "publish", "flight_watcher/layover/note")
    p = json.loads(data["payload"])
    assert (p["city"], p["text"]) == ("SYD", "Ferry at 9: sit upstairs on the left.") and p["rid"].startswith("r")
    assert card.locator("[data-nmsg]").inner_text() == "Saving..." and card.locator("[data-draft]").input_value() == ""
    # the Watcher's answer on the sensor
    na = dict(st["sensor.flight_watcher_layover_notes"]["attributes"])
    na["last"] = {"rid": p["rid"], "ok": True, "error": "", "city": "SYD", "action": "add", "at": "t"}
    pg.evaluate(f"window.setStates({{'sensor.flight_watcher_layover_notes': {{state: '4', last_updated: 'n2', attributes: {json.dumps(na)}}}}})")
    assert card.locator("[data-nmsg]").inner_text() == "Saved."
    # Tidy with AI: a feature ticket on the existing path, once
    card.locator("[data-tidy]").click()
    pg.wait_for_function("window.calls.length === 2")
    d, s, data = pg.evaluate("window.calls[1]")
    assert data["topic"] == "flight_watcher/ticket/new"
    t = json.loads(data["payload"])
    assert (t["kind"], t["title"], t["images"]) == ("feature", "Tidy the SYD layover notes", 0)
    assert "/share/flight_watcher/layovers/SYD.json" in t["narrative"] and "keep every fact" in t["narrative"]
    assert "reporter" not in t  # the Watcher sets it (ryan on the admin's instance)
    assert card.locator("[data-tidy]").is_disabled() and "Ticket filed" in card.locator("[data-nmsg]").inner_text()
    # delete asks first
    first = card.locator(".notes > .nl [data-del]").first
    nid = first.get_attribute("data-del")
    first.click()
    assert card.locator(f"[data-del='{nid}']").inner_text() == "Delete?" and pg.evaluate("window.calls.length") == 2
    card.locator(f"[data-del='{nid}']").click()
    pg.wait_for_function("window.calls.length === 3")
    p = json.loads(pg.evaluate("window.calls[2][2].payload"))
    assert p["city"] == "SYD" and p["delete"] == nid and "text" not in p
    # a city of 2 letters is not sent
    card.locator("[data-city]").fill("SY")
    card.locator("[data-draft]").fill("x")
    card.locator("[data-addnote]").click()
    assert "3-letter code" in card.locator("[data-nmsg]").inner_text() and pg.evaluate("window.calls.length") == 3
    pg.close()


SHOTS = os.environ.get("FW_171_SHOTS", "")  # a folder: the renders are saved there too


def _contrast(pg):
    return pg.evaluate("window.fwContrast(window.root().host)")


@pytest.mark.parametrize("width", [390, 1100])
@pytest.mark.parametrize("theme", ["light", "dark", "ha-light", "ha-dark"])
def test_render_layover_card(browser, tmp_path, width, theme):
    """At 390 and 1100 px, light and dark (the tests' colors and Home Assistant 2026.11's own): no sideways scroll, the
    van in the top 300 px, and every visible text node at WCAG AA (4.5:1, 3:1 large) from its rendered colors, the
    release warning, chips, links and countdown included (UX review r3, #1)."""
    pg = browser.new_page(viewport={"width": width, "height": 844})
    pg.set_content(_page(_states(tmp_path), theme={"light": LIGHT, "dark": DARK, "ha-light": HA_LIGHT, "ha-dark": HA_DARK}[theme]))
    card = pg.locator("flight-watcher-layover-card")
    assert pg.evaluate("document.documentElement.scrollWidth") <= width
    bb = card.locator("[data-van]").bounding_box()
    assert bb and bb["y"] + bb["height"] < 300
    con = _contrast(pg)
    assert con["n"] > 20 and not con["fails"], json.dumps(con["fails"], indent=1)
    for d in (tmp_path, SHOTS):
        if d:
            pg.screenshot(path=os.path.join(str(d), f"fw0072_layover_{width}_{theme}.png"), full_page=True)
    pg.close()


@pytest.mark.parametrize("theme", ["ha-light", "ha-dark"])
def test_urgent_countdown_armed_delete_and_errors_read_on_home_assistants_theme(browser, tmp_path, theme):
    """UX review r3 #1 on Pako's real colors: "in 25 min" (orange) was 1.96:1, "in 8 min" (red) 4.29:1 and 3.97:1, the
    armed Delete? 4.29:1. Now white on a fixed dark orange or red, AA in light and dark at 130, 25 and 8 min, and so is
    a refusal message."""
    pg = browser.new_page(viewport={"width": 390, "height": 844})
    st = _states(tmp_path)
    pg.set_content(_page(st, theme=HA_LIGHT if theme == "ha-light" else HA_DARK))
    cd = pg.locator("flight-watcher-layover-card [data-cd]")
    for mins, cls in ((130, ""), (25, "soon"), (8, "now")):
        pg.evaluate(f"Date.now = () => {int((VAN - timedelta(minutes=mins)).timestamp() * 1000)};"
                    "window.root().host._countdown()")
        assert cls in cd.get_attribute("class")
        con = _contrast(pg)
        assert not con["fails"], (mins, json.dumps(con["fails"], indent=1))
    card = pg.locator("flight-watcher-layover-card")
    card.locator(".notes > .nl [data-del]").first.click()  # armed: "Delete?"
    assert card.locator("button.x.arm").inner_text() == "Delete?"
    card.locator("[data-city]").fill("SY")
    card.locator("[data-draft]").fill("x")
    card.locator("[data-addnote]").click()  # refused in the card: a warning line
    assert "3-letter code" in card.locator("[data-nmsg].warn").inner_text()
    con = _contrast(pg)
    assert not con["fails"], json.dumps(con["fails"], indent=1)
    if SHOTS:
        pg.screenshot(path=os.path.join(SHOTS, f"fw0072_layover_urgent_{theme}.png"), full_page=True)
    pg.close()


def test_every_tap_target_is_44_px_at_390(browser, tmp_path):
    """UX review r3 #2: chips were 34 px, the address and phone links 16 px, the delete x 27 by 28, the city box 26,
    Add note and Tidy 32, the fold-outs 32. Now every button, input, fold-out and block link is at least 44 px tall
    (the delete x 44 wide too), and a chip stays small to the eye but takes a tap 4 px above and below it. Inline links
    in the guide's text are text, not targets."""
    pg = browser.new_page(viewport={"width": 390, "height": 844})
    pg.set_content(_page(_states(tmp_path), theme=HA_LIGHT))
    pg.evaluate("window.root().querySelectorAll('details').forEach((d) => { d.open = true; })")
    small = pg.evaluate("""() => [...window.root().querySelectorAll('a, button, summary, input, textarea')]
        .filter((e) => e.getClientRects().length && !e.closest('.guide, .nt') && !e.matches('a.chip'))
        .map((e) => { const r = e.getBoundingClientRect(); return {t: (e.textContent || e.getAttribute('aria-label') || e.tagName).trim().slice(0, 30),
          h: Math.round(r.height), w: Math.round(r.width), x: e.matches('button.x')}; })
        .filter((b) => b.h < 44 || (b.x && b.w < 44))""")
    assert small == [], small
    n = pg.evaluate("window.root().querySelectorAll('a, button, summary, input').length")
    assert n >= 12
    chips = pg.evaluate("""() => [...window.root().querySelectorAll('a.chip')].map((c) => { const r = c.getBoundingClientRect(), x = r.left + r.width / 2;
        return {h: r.height, up: window.root().elementFromPoint(x, r.top - 4) === c, down: window.root().elementFromPoint(x, r.bottom + 4) === c}; })""")
    assert len(chips) == 3 and all(c["h"] <= 40 and c["up"] and c["down"] for c in chips), chips
    pg.close()


def test_note_dates_are_hst_and_the_guide_time_says_hst(browser, tmp_path):
    """UX review r3 #3: a note's "at" is UTC, so a note written 2026-11-10 20:00 HST showed 2026-11-11. Its date is
    now the HST one, and the guide's tidied time is labeled HST."""
    st = _states(tmp_path)
    na = st["sensor.flight_watcher_layover_notes"]["attributes"]
    na["cities"]["SYD"]["notes"][0]["at"] = "2026-11-11T06:00:00+00:00"  # 2026-11-10 20:00 HST
    pg = browser.new_page(viewport={"width": 390, "height": 844})
    pg.set_content(_page(st))
    card = pg.locator("flight-watcher-layover-card")
    assert card.locator(".notes > .nl .nm .u").first.inner_text() == "2026-11-10"
    assert card.locator(".notes > .guide > .u").first.inner_text().endswith(" HST")
    pg.close()


def test_a_12_hour_van_and_one_only_the_watcher_read_show_on_the_card(browser, tmp_path):
    """Review r3 #6: a van Hark wrote as "7:40 PM Thu 2026-11-12, ..." got its alerts but the card showed Report and
    no van. The card reads the same three forms as the Watcher, and when it still cannot, it shows the Watcher's own
    reading (here Hark's text says "see crew desk" and its state has the time)."""
    for van, state, place in (("7:40 PM Thu 2026-11-12, Example Harbour Hotel lobby", "x", "Example Harbour Hotel lobby"),
                              ("see crew desk", "Layover SYD, van 2026-11-12 19:40", "")):
        pg = browser.new_page(viewport={"width": 390, "height": 844})
        pg.set_content(_page(_states(tmp_path / place.replace(" ", "_"), hark_attrs=_hark_full(van=van), hark_state=state)))
        card = pg.locator("flight-watcher-layover-card")
        v = card.locator("[data-van]")
        assert v.locator(".vl").inner_text().lower() == "van", van
        assert v.locator(".vt").inner_text() == "19:40" and "AEDT" in v.locator(".vz").inner_text(), van
        assert v.locator("[data-cd]").inner_text() == "in 2 h 10 min", van
        assert card.locator("[data-vanunread]").count() == 0
        if place:
            assert f"Van at {place}" in card.locator(".vp").first.inner_text()
            assert "30 min at 22:10 HST" in card.locator(".vp").first.inner_text()
        pg.close()


def test_a_van_the_watcher_cannot_place_shows_its_text_and_no_alert(browser, tmp_path):
    """Review r3 #1 and #2 on the card: a date-first van with PM after it, or a weekday that is not the date's, is no
    alert in the Watcher; the card shows Hark's text and says no van alert comes, never a time of its own."""
    for van, state in (("2026-11-12 7:40 PM, Example lobby", "Layover SYD, van 2026-11-12 07:40"),
                       ("12:05 AM (00:05) Fri 2026-11-12, Example lobby", "Layover SYD, van 2026-11-12 00:05")):
        pg = browser.new_page(viewport={"width": 390, "height": 844})
        pg.set_content(_page(_states(tmp_path / str(len(van)), hark_attrs=_hark_full(van=van), hark_state=state)))
        card = pg.locator("flight-watcher-layover-card")
        assert card.locator("[data-van] .vl").inner_text().lower() == "report", van
        line = card.locator("[data-vanunread]").inner_text()
        assert van in line and "no van alert" in line, van
        pg.close()


def test_the_cards_van_reading_matches_the_watchers(browser):
    """The card's _parseVan and layover.parse_van read the same texts the same way (date, time, and none)."""
    texts = ["7:40 PM (19:40) Thu 2026-11-12, Example Harbour Hotel lobby", "2026-11-12 19:40", "7:05 am Fri 2026-11-13, front door",
             "12:30 AM Sat 2026-11-14", " 2026-11-12 19:40", "Thu, 2026-11-12 19:40, lobby", "2026-11-12 19:40 AEDT, lobby",
             "2026-11-12 7:40 PM, X", "2026-11-12T08:40:00Z", "2026-11-12 08:40 UTC", "2026-11-12T19:40+11:00",
             "12:05 AM (00:05) Fri 2026-11-12, lobby", "7:40 PM Thu/Fri 2026-11-12", "(19:40) Thurs. 2026-11-12",
             "7:40 PM at the Saturn Hotel desk 2026-11-12", "(25:10) 2026-11-12", "(19:40) 2026-02-30", "TBD", ""]
    pg = browser.new_page()
    pg.set_content(_page({}))
    got = pg.evaluate("(ts) => ts.map((t) => { const v = window.root().host._parseVan(t); return v ? [v.date, v.local, v.place] : null; })", texts)
    for t, g in zip(texts, got):
        want = LO.parse_van(t)
        assert (list(want) if want else None) == g, t
    pg.close()


def test_a_damaged_notes_file_is_said_not_shown_as_no_notes(browser, tmp_path):
    """Review r3 #3 on the card: the sensor's "unreadable" cities are named, and the current one is not "No notes
    yet"."""
    st = _states(tmp_path)
    na = st["sensor.flight_watcher_layover_notes"]["attributes"]
    na["cities"].pop("SYD")
    na["order"].remove("SYD")
    na["unreadable"] = ["SYD"]
    pg = browser.new_page(viewport={"width": 390, "height": 844})
    pg.set_content(_page(st))
    card = pg.locator("flight-watcher-layover-card")
    assert "notes file for SYD could not be read" in card.locator("[data-unread]").inner_text()
    assert "No notes for SYD yet" not in card.locator(".notes").inner_text()
    pg.close()


def test_the_dashboard_snapshot_puts_the_card_on_the_working_flight_view():
    root = os.path.dirname(HERE)
    text = open(os.path.join(root, "ha", "dashboard_flight_watcher.json"), encoding="utf-8").read()
    d = json.loads(text)
    v = next(v for v in d["data"]["config"]["views"] if v.get("path") == "flight")
    assert v["title"] == "Working Flight" and v["icon"] == "mdi:airplane-takeoff"
    cs = [c for s in v["sections"] for c in s["cards"]]
    # Nov 12 (Ryan, in Sydney: the page said "Configuration error" on his phone): the built-in markdown card and the
    # Ready to update? button are back above the layover card, so the page reads with no custom card at all
    assert [c["type"] for c in cs] == ["markdown", "grid", "custom:flight-watcher-layover-card"]
    assert "sensor.flight_watcher_working_flight" in cs[0]["content"] and "sensor.hark_working_flight" in cs[0]["content"]
    # Nov 12 (Ryan: "When I click ready to update I want you to trigger hark without my help"): the button runs the
    # ask-Hark automation instead of opening Hark's project page
    assert cs[1]["cards"][0]["name"] == "Ready to update"
    assert cs[1]["cards"][0]["tap_action"] == {"action": "perform-action", "perform_action": "automation.trigger",
                                              "target": {"entity_id": "automation.flight_watcher_ready_to_update_ask_hark"}}
    assert "flight_watcher_ready_to_update_ask_hark" in cs[0]["content"]  # the card shows "Asked Hark at ..." 
    assert cs[2] == {"grid_options": {"columns": "full"}, "type": "custom:flight-watcher-layover-card",
                     "update_url": "<redacted-hark-url>"}
    assert "hark.com/project" not in text  # Hark's project link stays out of git
    # the card ships with the app
    import cards
    assert "flight-watcher-layover-card.js" in json.loads(cards.build("1")[cards.MANIFEST])["cards"]


# ---------------------------------------------------------------- 1.7.1: the van time's source (Ryan, Nov 11)
def test_the_card_shows_where_the_van_time_comes_from(browser, tmp_path):
    """The pairings package's VAN (19:25 here) comes before Hark's (19:40) and the card says "from the pairings
    package"; Hark's alone says "from Hark"."""
    from test_van_package import package
    leg = {"pairing": "H3681", "start": "2026-11-10", "city": "SYD", "flt": "852", "dep": "21:40", "date": "2026-11-12"}
    info, _ = LO.package_van([LO.package_vans(package())], leg)
    st = _states(tmp_path)
    st["sensor.flight_watcher_layover_van"]["attributes"] = LO.sensor(info, "", {}, NOW)
    pg = browser.new_page(viewport={"width": 390, "height": 844})
    pg.set_content(_page(st))
    card = pg.locator("flight-watcher-layover-card")
    v = card.locator("[data-van]")
    assert v.locator(".vt").inner_text() == "19:25" and "AEDT" in v.locator(".vz").inner_text()
    assert v.locator(".vh").inner_text().strip() == "22:25 HST Wed"
    assert v.locator("[data-vansrc]").inner_text() == "from the pairings package"
    assert v.locator("[data-cd]").inner_text() == "in 1 h 55 min"
    assert "30 min at 21:55 HST" in card.locator(".vp").first.inner_text()
    assert pg.evaluate("document.documentElement.scrollWidth") <= 390
    pg.close()
    pg = browser.new_page(viewport={"width": 390, "height": 844})
    pg.set_content(_page(_states(tmp_path / "h")))
    assert pg.locator("flight-watcher-layover-card [data-vansrc]").inner_text() == "from Hark"
    pg.close()


def test_with_no_van_time_the_card_says_it_is_not_known(browser, tmp_path):
    """(c): no package van and nothing from Hark: no van time and no alert, and the card says so with the Watcher's
    reason, the report time in the van's place."""
    why = "Hark's working flight is not in Home Assistant; the pairings package gives no van time for H3681 SYD (VAN 00:00)"
    st = _states(tmp_path, hark_attrs={})
    st["sensor.flight_watcher_layover_van"] = {"state": "unknown", "last_updated": "v2", "attributes": {"at": None, "why": why}}
    pg = browser.new_page(viewport={"width": 390, "height": 844})
    pg.set_content(_page(st))
    card = pg.locator("flight-watcher-layover-card")
    assert card.locator("[data-van] .vl").inner_text().lower() == "report"
    line = card.locator("[data-vanunknown]").inner_text()
    assert "Van time not known" in line and "no van alert comes" in line and "VAN 00:00" in line
    assert card.locator("[data-vansrc]").count() == 0
    # at home (the next leg leaves HNL) the card says nothing about a van
    st["sensor.flight_watcher_working_flight"]["attributes"]["origin"] = "HNL"
    st["sensor.flight_watcher_working_flight"]["last_updated"] = "w2"
    pg.evaluate("(p) => window.setStates(p)", {"sensor.flight_watcher_working_flight": st["sensor.flight_watcher_working_flight"]})
    assert card.locator("[data-vanunknown]").count() == 0
    pg.close()


# ---------------------------------------------------------------- Nov 12: the GIN code on its own line (Ryan)
def test_the_gin_code_has_a_line_of_its_own_at_390(browser, tmp_path):
    """Ryan, Nov 12: "Gin code should be on its own line so it doesn't get cut off." The place stays after the label,
    the code goes under it on one unbroken line; a code with no place shows alone under its label."""
    a = _hark_full()
    a.update({"gin_arr": "HNL gate C5 (Non-Mauka): *-2-1-1-7-3-1-4-5-2-#", "gin_dep": "4-4-2-#", "release_updated": True,
              "mel": ["Example MEL item"], "notam": ["Example NOTAM"]})
    pg = browser.new_page(viewport={"width": 390, "height": 844})
    pg.set_content(_page(_states(tmp_path, hark_attrs=a)))
    card = pg.locator("flight-watcher-layover-card")
    card.locator("details.rel summary").click()
    arr = card.locator(".gin", has_text="GIN arr:")
    assert arr.locator("b").inner_text() == "GIN arr:"
    assert "HNL gate C5 (Non-Mauka)" in arr.inner_text() and ": *" not in arr.inner_text()
    code = arr.locator("code")
    assert code.inner_text() == "*-2-1-1-7-3-1-4-5-2-#"
    lb, cb = arr.locator("b").bounding_box(), code.bounding_box()
    assert cb["y"] >= lb["y"] + lb["height"] - 1  # under the label, on its own line
    line_h = pg.evaluate("(e) => parseFloat(getComputedStyle(e).lineHeight) || parseFloat(getComputedStyle(e).fontSize) * 1.4",
                         code.element_handle())
    assert cb["height"] <= line_h * 1.6  # one line, never broken inside the code
    assert cb["x"] + cb["width"] <= card.bounding_box()["x"] + card.bounding_box()["width"] + 1  # inside the card
    dep = card.locator(".gin", has_text="GIN dep:")
    assert dep.locator("code").inner_text() == "4-4-2-#"
    pg.close()
