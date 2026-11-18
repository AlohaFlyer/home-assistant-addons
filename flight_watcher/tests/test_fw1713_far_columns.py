"""1.7.13 (item 4, Ryan, Nov 17: "Give FAR-30/7, FAR-100/672 and Room real headers with units, and show headroom
against each limit (e.g. "100h/672h: 10:57 left"). Explain the Room column in the Key."). The Schedule card only: its
three FAR column headers carry units ("30h in 7d", "100h in 672h", "Room to 100h", the rule in each title), the two
flight time cells say what is left of the FAR 117.23(b)(1) limit (100 flight hours in any 672 consecutive hours):
"10:57 left", red "0:00 left" at the limit, red "1:20 over" past it, "~" in front when a window reaches past the
schedule on file; the 30h in 7d cell (FAR 117.25(b): 30 consecutive hours free from all duty in the 168 h before a
report) words today's states with units ("✓ 36h off 11/05", red "need 30h off", "?", "–"). far.py and the FAR math
are unchanged. Synthetic months and made-up trips only (H91xx, H93xx), rendered in Chromium at 390 px, light and dark.
Set FW_1713_SHOTS to a folder to save the screenshots."""
import os

import pytest

from pot import schedule_items
from test_release_a_schedule_card import _src, _states

SHOTS = os.environ.get("FW_1713_SHOTS", "")
TURN = {"report": "06:00", "last_arr": "20:00"}  # duty 06:00 to 20:15 (release = block-in + 15 min, PWA 2.19.b)
# 100h cases: one-day turns, their blocks summing to 89:03 by Nov 19, 100:00 on Nov 22, 101:20 on Nov 25
BLOCKS = [("01", "13:00"), ("04", "13:00"), ("07", "13:00"), ("10", "13:00"), ("13", "13:00"), ("16", "13:00"),
          ("19", "11:03"), ("22", "10:57"), ("25", "1:20")]


def _month(mk, marks, ndays):
    days = [[f"{mk}-{d:02d}", "", ""] for d in range(1, ndays + 1)]
    for iso, act, lay in marks:
        days[int(iso[8:]) - 1] = [iso, act, lay]
    return {"items": schedule_items(days), "days": days, "totals": {}, "updated": "Nov 12, 2026"}


def _st(months, own):
    st = _states(months, {}, {"ok": True, "why": ""}, "Nov 12, 2026")
    st["sensor.flight_watcher_state"]["attributes"]["doh"] = "2022-01-15"
    for k, v in (("federal_tax_pct", "22.0"), ("state_tax_pct", "7.0"), ("longevity_year", "5.0")):
        st[f"input_number.flight_watcher_{k}"] = {"state": v, "last_updated": "a", "attributes": {}}
    st["sensor.flight_watcher_own_trip_times"] = {"state": str(len(own)), "last_updated": "a",
                                                  "attributes": {"count": len(own), "trips": own}}
    return st


def _blocks(load=("2026-10", "2026-11", "2026-12"), drop=()):
    """Turns on the Nov days of BLOCKS (less `drop`), with the months in `load` on file: Oct to Dec makes every
    November window exact; without October a window ending before Nov 28 starts before the schedule on file, without
    December a window from a November day reaches past it."""
    blk = [(d, b) for d, b in BLOCKS if d not in drop]
    nov = _month("2026-11", [(f"2026-11-{d}", f"H91{d}", "") for d, _ in blk], 30)
    months = {"2026-11": nov}
    if "2026-10" in load:
        months["2026-10"] = _month("2026-10", [], 31)
    if "2026-12" in load:
        months["2026-12"] = _month("2026-12", [], 31)
    own = {f"H91{d}|2026-11-{d}": {"blk": b, "credit": b, **TURN} for d, b in blk}
    return _st(months, own)


def _rest():
    """30h in 7d states: H9301 Nov 1 to 3 (LAX), then daily turns Nov 5 to 13 (07:00 to 19:15, 11:45 between), only
    November on file. Nov 1 and 4: no 30 h free and the 168 h reach before Nov 1 ('?'); Nov 2 and 3 mid-trip;
    Nov 5 to 10: the 36:45 break from Nov 3 18:15 to Nov 5 07:00; Nov 11 to 15: no 30 h free; Nov 16: 52:46 off."""
    marks = [("2026-11-01", "H9301", "LAX"), ("2026-11-02", "", "-"), ("2026-11-03", "", "HNL")]
    marks += [(f"2026-11-{d:02d}", f"H93{d:02d}", "") for d in range(5, 14)]
    own = {"H9301|2026-11-01": {"blk": "18:00", "credit": "20:00", "report": "08:00", "last_arr": "18:00"}}
    own.update({f"H93{d:02d}|2026-11-{d:02d}": {"blk": "9:00", "credit": "9:30", "report": "07:00", "last_arr": "19:00"}
                for d in range(5, 14)})
    return _st({"2026-11": _month("2026-11", marks, 30)}, own)


JS = """async ({h, dark, shot}) => { const c = document.createElement('flight-watcher-schedule-card');
  c.setConfig({}); document.body.appendChild(c);
  c.hass = {states: h, themes: {darkMode: dark}, callService: async () => {}};
  await new Promise((ok) => setTimeout(ok, 300));
  const r = c.shadowRoot;
  const box = (el) => { const q = el.getBoundingClientRect(); return {w: q.width, h: q.height, l: q.left, r: q.right}; };
  const heads = [...r.querySelectorAll('.cal tr.hd th')].map((th) => ({t: th.textContent.trim(), title: th.title, ...box(th)}));
  const rows = Object.fromEntries([...r.querySelectorAll('.cal tr[data-d]')].map((tr) => [tr.dataset.d,
    [...tr.querySelectorAll('td.far')].map((td) => ({t: td.textContent.trim(), cls: td.className, title: td.title,
      color: getComputedStyle(td).color, ws: getComputedStyle(td).whiteSpace, h: td.getBoundingClientRect().height}))]));
  const key = [...r.querySelectorAll('.leg .lt tr')].map((tr) => [...tr.children].map((td) => td.textContent.trim()));
  const probe = document.createElement('span'); probe.style.color = dark ? '#ef9a9a' : '#c62828'; document.body.appendChild(probe);
  const red = getComputedStyle(probe).color; probe.remove();
  const helper = typeof farLeft === 'function' ? [farLeft(10.95, false), farLeft(0, false), farLeft(-4 / 3, false),
    farLeft(10.95, true), farLeft(-4 / 3, true), farLeft(-0.001, false), farLeft(100, false)] : null;
  const wrap = r.querySelector('.wrap');
  const out = {heads, rows, key, red, helper, text: r.textContent, wide: document.documentElement.scrollWidth,
    rowH: [...r.querySelectorAll('.cal tr[data-d]')].map((tr) => tr.getBoundingClientRect().height)};
  if (shot) {  // the grid scrolled so the 30h in 7d column sits right after the day column, the Key open
    const th = r.querySelectorAll('.cal tr.hd th')[10], day = r.querySelector('.cal tr[data-d] td.n');
    wrap.scrollLeft += th.getBoundingClientRect().left - day.getBoundingClientRect().right;
    r.querySelector('.leg').open = true; return out; }
  c.remove(); return out; }"""


CASES = {
    "over": _blocks(),  # every November window on file
    "zero": _blocks(drop=("25",)),  # the busiest window holds 100:00 exactly
    "back": _blocks(load=("2026-11", "2026-12")),  # windows before Nov 28 start before the schedule on file
    "fwd": _blocks(load=("2026-10", "2026-11")),  # every window from a November day reaches past it
    "rest": _rest(),
}


def _theme(dark):
    """The page around the card, as tests/fw1711_totals_render.js draws it: Home Assistant's theme variables, light or
    dark."""
    bg, card, fg = ("#111111", "#1c1c1c", "#e1e1e1") if dark else ("#fafafa", "#ffffff", "#212121")
    return (f"body{{margin:0;padding:8px;background:{bg};color:{fg};font-family:Roboto,Arial,sans-serif;"
            f"--card-background-color:{card};--primary-text-color:{fg};--secondary-text-color:"
            f"{'#9e9e9e' if dark else '#727272'};--divider-color:{'#333333' if dark else '#e0e0e0'};"
            f"--secondary-background-color:{'#282828' if dark else '#f5f5f5'};--primary-color:#03a9f4}}"
            f"ha-card{{display:block;background:var(--card-background-color);border-radius:12px}}")


@pytest.fixture(scope="module")
def got():
    sync_api = pytest.importorskip("playwright.sync_api")
    from test_cards import _chromium
    page = ("<!doctype html><html><body><script>customElements.define('ha-card', class extends HTMLElement {});"
            "window.fetch = async () => ({ok: false, json: async () => null});</script><script>" + _src()
            + "</script></body></html>")
    out = {}
    with sync_api.sync_playwright() as p:
        b = _chromium(p)
        if not b:
            pytest.skip("no Chromium for Playwright")
        try:
            for dark in (False, True):
                pg = b.new_page(viewport={"width": 390, "height": 844})
                pg.clock.set_fixed_time("2026-11-13T02:00:00Z")  # Nov 12 16:00 HST
                pg.set_content(page)
                pg.add_style_tag(content=_theme(dark))
                for name, st in CASES.items():
                    out[(name, dark)] = pg.evaluate(JS, {"h": st, "dark": dark, "shot": False})
                if SHOTS:
                    os.makedirs(SHOTS, exist_ok=True)
                    for name in ("over", "rest"):
                        pg2 = b.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=2)
                        pg2.clock.set_fixed_time("2026-11-13T02:00:00Z")
                        pg2.set_content(page)
                        pg2.add_style_tag(content=_theme(dark))
                        pg2.evaluate(JS, {"h": CASES[name], "dark": dark, "shot": True})
                        pg2.wait_for_timeout(100)
                        pg2.screenshot(path=os.path.join(SHOTS, f"item4_{name}_390_{'dark' if dark else 'light'}.png"),
                                       full_page=True)
                        pg2.close()
                pg.close()
        finally:
            b.close()
    return out


def _far(got, name, d, dark=False):
    """The three FAR cells of a day: (30h in 7d, 100h in 672h, Room to 100h)."""
    return got[(name, dark)]["rows"][f"2026-11-{d:02d}"]


def _txt(got, name, d, dark=False):
    return [c["t"] for c in _far(got, name, d, dark)]


def test_headers_carry_units_and_cite_the_rule(got):
    for dark in (False, True):
        heads = got[("over", dark)]["heads"]
        far = heads[10:13]
        assert [h["t"] for h in far] == ["30h in 7d", "100h in 672h", "Room to 100h"]
        assert far[0]["title"].startswith("FAR 117.25(b): 30 consecutive hours free from all duty in the 168 h "
                                          "(7 days) before a report")
        assert far[1]["title"].startswith("FAR 117.23(b)(1): at most 100 flight hours in any 672 consecutive hours "
                                          "(28 days)")
        assert far[2]["title"].startswith("FAR 117.23(b)(1): 100:00 minus the busiest 672 h window")
        # short enough for a 390 px phone: a dozen characters on one line, like the one-word Trip header, and the
        # three columns side by side within one screen when the grid is scrolled to them
        line = heads[2]["h"]
        assert all(len(h["t"]) <= 12 and h["h"] <= line + 0.5 for h in far), far
        assert far[2]["r"] - far[0]["l"] <= 300, far
        text = got[("over", dark)]["text"]
        assert "FAR-30/7" not in text and "FAR-100/672" not in text
        assert all(x["wide"] <= 390 for k, x in got.items() if k[1] == dark)  # the grid scrolls in its box


def test_100h_cell_is_what_is_left_positive_zero_and_over(got):
    for dark in (False, True):
        assert _txt(got, "over", 1, dark)[1] == "87:00 left"
        assert _txt(got, "over", 19, dark)[1] == "10:57 left"  # Ryan's example: 89:03 flown
        assert _txt(got, "over", 21, dark)[1] == "10:57 left"
        assert _txt(got, "over", 22, dark)[1] == "0:00 left"  # 100:00 flown: at the limit
        assert _txt(got, "over", 25, dark)[1] == "1:20 over"  # 101:20 flown
        assert _txt(got, "over", 28, dark)[1] == "1:20 over"
        assert _txt(got, "over", 29, dark)[1] == "11:40 left"  # Nov 1's 13:00 left the window
        c19 = _far(got, "over", 19, dark)[1]
        assert c19["title"].startswith("100h/672h: 10:57 left. 89:03 block flown in the 672 h (28 days) ending "
                                       "24:00 2026-11-19, leg by leg. FAR 117.23(b)(1): at most 100 flight hours in "
                                       "any 672 consecutive hours."), c19["title"]
        assert "~" not in c19["title"]
        assert _far(got, "over", 25, dark)[1]["title"].startswith("100h/672h: 1:20 over. 101:20 block flown")


def test_room_cell_positive_zero_over_and_approximate(got):
    for dark in (False, True):
        # negative: every November day up to Nov 28 falls in the Nov 1 to 28 window (101:20)
        assert {_txt(got, "over", d, dark)[2] for d in range(1, 29)} == {"1:20 over"}
        assert _txt(got, "over", 29, dark)[2] == "11:40 left"  # positive
        assert _txt(got, "over", 30, dark)[2] == "11:40 left"
        r = _far(got, "over", 19, dark)[2]
        assert r["title"].startswith("Room to 100h: 1:20 over. 100:00 minus the busiest 672 h window this day falls "
                                     "in (101:20 in the 28 days ending 24:00 2026-11-25), looking back and forward: "
                                     "the most block you could add on this day (FAR 117.23(b)(1))."), r["title"]
        # zero: the busiest window holds exactly 100:00
        assert {_txt(got, "zero", d, dark)[2] for d in range(1, 29)} == {"0:00 left"}
        assert _txt(got, "zero", 22, dark)[1] == "0:00 left" and _txt(got, "zero", 29, dark)[2] == "13:00 left"
        # approximate: '~' in front, the word kept
        assert _txt(got, "fwd", 19, dark)[1:] == ["10:57 left", "~1:20 over"]  # the 672 h back are on file
        assert _txt(got, "fwd", 29, dark)[1:] == ["11:40 left", "~11:40 left"]
        assert _txt(got, "back", 19, dark)[1:] == ["~10:57 left", "~1:20 over"]
        assert _txt(got, "back", 22, dark)[1:] == ["~0:00 left", "~1:20 over"]
        assert _txt(got, "back", 28, dark)[1:] == ["1:20 over", "1:20 over"]  # Nov 1 to 28: all on file
        assert _txt(got, "back", 29, dark)[1:] == ["11:40 left", "11:40 left"]
        assert "~ = a window reaches past the schedule on file" in _far(got, "fwd", 29, dark)[2]["title"]
        assert "~ = part of the window is before the schedule on file" in _far(got, "back", 19, dark)[1]["title"]


def test_red_only_with_a_word_that_says_so(got):
    """Colour is never the only cue: a red FAR cell says 'over', '0:00 left' or 'need 30h off'; every other is not
    red."""
    for (name, dark), x in got.items():
        for d, cells in x["rows"].items():
            for c in cells:
                bad = " bad" in f" {c['cls']} "
                cue = c["t"].endswith(" over") or c["t"] in ("0:00 left", "~0:00 left", "need 30h off")
                assert bad == cue, (name, dark, d, c)
                assert (c["color"] == x["red"]) == bad, (name, dark, d, c)
                assert c["ws"] == "nowrap", (name, d, c)  # one line: no taller rows
        assert len(set(round(h) for h in x["rowH"])) <= 2, (name, dark, sorted(set(x["rowH"])))


def test_30h_cell_states_worded_with_units(got):
    for dark in (False, True):
        t = {d: _txt(got, "rest", d, dark)[0] for d in range(1, 31)}
        assert t[1] == "?" and t[4] == "?"  # no 30 h free and the 168 h reach before Nov 1
        assert t[2] == t[3] == "–"  # mid-trip (H9301 LAX)
        assert all(t[d] == "✓ 36h off 11/05" for d in range(5, 11)), t  # 36:45 from Nov 3 18:15 to Nov 5 07:00
        assert all(t[d] == "need 30h off" for d in range(11, 16)), t
        assert t[16] == "✓ 52h off 11/16"  # 52:46 off since Nov 13 19:15, still on
        c = _far(got, "rest", 5, dark)[0]
        assert "ok30" in c["cls"] and "bad" not in c["cls"]
        assert c["title"] == ("Duty starts 07:00: longest free block in the 168 h before was 36:45 from 18:15 "
                              "2026-11-03. 30 h free in 7 days met (FAR 117.25(b)): this break covers reports until "
                              "01:00 2026-11-11.")
        n = _far(got, "rest", 11, dark)[0]
        assert "bad" in n["cls"] and n["title"].endswith("Under 30:00: 30 h free in 7 days NOT met (FAR 117.25(b)).")
        assert "mid" in _far(got, "rest", 2, dark)[0]["cls"]
        assert _far(got, "rest", 1, dark)[0]["title"].endswith("The window reaches before the schedule on file.")
        # an exact month: November 1 has every hour of October off before it
        assert _txt(got, "over", 1, dark)[0] == "✓ 168h off 11/01"


def test_key_explains_the_columns_with_units_and_the_rules(got):
    key = dict((r[0], r[1]) for r in got[("over", False)]["key"] if len(r) == 2)
    assert "FAR-30/7, FAR-100/672, Room" not in key
    t30, t100, room = key["30h in 7d"], key["100h in 672h"], key["Room to 100h"]
    assert t30.startswith("FAR 117.25(b): 30 consecutive hours free from all duty within the past 168 consecutive "
                          "hours (7 days) before a report.")
    assert "✓ 36h off MM/DD" in t30 and "red 'need 30h off'" in t30 and "? = the window reaches before" in t30
    assert "– = mid-trip, no report that day" in t30 and "Need 30 h off by (totals)" in t30
    assert t100.startswith("FAR 117.23(b)(1): at most 100 flight hours in any 672 consecutive hours (28 days).")
    assert "hours and minutes" in t100 and "10:57 left = 89:03 flown" in t100 and "1:20 over" in t100
    assert room.startswith("The most block you could still add that day, in hours and minutes (h:mm), under FAR "
                           "117.23(b)(1): 100 flight hours in any 672 consecutive hours.")
    assert "busiest 672 h (28-day) window the day falls in, looking back and forward" in room
    assert "red '0:00 left'" in room and "red '1:20 over'" in room and "~ = a window reaches past" in room
    assert "Block Avail (totals): 98:00 bid-month cap minus FLICA's bid-period Block" in room
    assert "The 30h in 7d column gives the date that counts" in key["Teal edge"]
    # only rules far.py and the card check: 117.25(b) for 30 h free, 117.23(b)(1) for 100 h in 672 h
    for k in ("30h in 7d", "100h in 672h", "Room to 100h"):
        assert "117.23(c)" not in key[k]


def test_helper_rounds_to_the_minute_and_names_the_side(got):
    h = got[("over", False)]["helper"]
    assert h == [{"txt": "10:57 left", "bad": False}, {"txt": "0:00 left", "bad": True},
                 {"txt": "1:20 over", "bad": True}, {"txt": "~10:57 left", "bad": False},
                 {"txt": "~1:20 over", "bad": True}, {"txt": "0:00 left", "bad": True},
                 {"txt": "100:00 left", "bad": False}]


def test_far_math_is_untouched():
    """Item 4 is wording and display only: far.py keeps its limits and rule references."""
    import far
    assert (far.FT_672, far.FDP_168, far.FDP_672) == (100, 60, 190)
    assert [c[3] for c in far.CUM] == ["FAR 117.23(b)(1)", "FAR 117.23(c)(1)", "FAR 117.23(c)(2)"]
    assert far.H168.total_seconds() == 168 * 3600 and far.H672.total_seconds() == 672 * 3600
