"""1.7.13 (item 4, Ryan, Nov 17: "Give FAR-30/7, FAR-100/672 and Room real headers with units, and show headroom
against each limit (e.g. "100h/672h: 10:57 left"). Explain the Room column in the Key."). The Schedule card only: its
three FAR column headers carry units ("30h in 7d", "100h in 672h", "Room to 100h", the rule in each title), the two
flight time cells say what is left of the FAR 117.23(b)(1) limit (100 flight hours in any 672 consecutive hours):
"10:57 left", red "0:00 left" at the limit, red "1:20 over" past it, "~" in front when a window reaches past the
schedule on file; the 30h in 7d cell (FAR 117.25(b): 30 consecutive hours free from all duty in the 168 h before a
report) words today's states with units ("✓ 36h 11/05", red "need 30h off", "?", "–"). far.py and the FAR math
are unchanged. Synthetic months and made-up trips only (H91xx, H93xx, H95xx, H98xx), rendered in Chromium at 390 px,
light and dark, and in a 936 px box. Set FW_1713_SHOTS to a folder to save the screenshots.

Review fixes (wording and display only): Room to 100h says it tries the 672 h windows ending 24:00 HST (F1), the tick
speaks for a report at the day's first duty start, 00:01 on a day off (F2), the Key says a trip with no times on file
counts no block and as time off (F3, the marking itself is Ryan's call), each block is rounded to the minute once so a
cell and its title add up to 100:00 (F4), the block is "flown or scheduled" (F6), and the grid is about as wide as in
1.7.11 (r1: no "off" in the tick, two-line 100h and Room headers above 700 px, 4 px cell padding)."""
import copy
import os
import re

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


def _midday():
    """F1 (review): a 672 h window ending mid-day holds more than any window ending 24:00. H9101 Nov 1 13:00 to 23:00
    (10:00), 10:00 turns on Nov 4 to 25 every third day, H9127 Nov 27 (1:00), H9129 Nov 29 01:00 to 10:45 (10:00), Oct
    to Dec on file. The busiest window ending 24:00 that holds Nov 29 has 91:00; the 672 h from Nov 1 12:00 to Nov 29
    12:00 hold 101:00."""
    own = {"H9101|2026-11-01": {"blk": "10:00", "credit": "10:00", "report": "13:00", "last_arr": "23:00"}}
    for d in (4, 7, 10, 13, 16, 19, 22, 25):
        own[f"H91{d:02d}|2026-11-{d:02d}"] = {"blk": "10:00", "credit": "10:00", **TURN}
    own["H9127|2026-11-27"] = {"blk": "1:00", "credit": "1:00", **TURN}
    own["H9129|2026-11-29"] = {"blk": "10:00", "credit": "10:00", "report": "01:00", "last_arr": "10:45"}
    nov = _month("2026-11", [(k[6:], k[:5], "") for k in own], 30)
    months = {"2026-10": _month("2026-10", [], 31), "2026-11": nov, "2026-12": _month("2026-12", [], 31)}
    return _st(months, own)


def _late():
    """F2 (review): the tick is for one report time. Turns Nov 2 and 5 to 9 and 11 (06:00 to 20:15), Nov 4 12:00 to
    20:15, Nov 10 off, Oct to Dec on file. A report at 00:01 Nov 10 has the 35:59 from 00:01 Nov 3 to 12:00 Nov 4; a
    report at 12:00 Nov 10 would not (its 168 h start at 12:00 Nov 3)."""
    days = {2: TURN, 4: {"report": "12:00", "last_arr": "20:00"}, 5: TURN, 6: TURN, 7: TURN, 8: TURN, 9: TURN, 11: TURN}
    nov = _month("2026-11", [(f"2026-11-{d:02d}", f"H95{d:02d}", "") for d in days], 30)
    months = {"2026-10": _month("2026-10", [], 31), "2026-11": nov, "2026-12": _month("2026-12", [], 31)}
    return _st(months, {f"H95{d:02d}|2026-11-{d:02d}": {"blk": "8:00", "credit": "8:00", **t} for d, t in days.items()})


def _half(turns=()):
    """F4 (review): half minutes. H9801 Nov 1 to 2: FLICA Block 1:01, duty block 61 + 61, so each leg counts 30.5 min
    (scaled to the trip's Block); `turns` adds one-day turns, Oct to Dec on file."""
    du = [{"d": 0, "dep": 600, "arr": 661, "stn": "LAX", "blk": 61},
          {"d": 1, "dep": 2040, "arr": 2101, "stn": "HNL", "blk": 61}]
    own = {"H9801|2026-11-01": {"blk": "1:01", "credit": "1:01", "report": "09:00", "last_arr": "11:01", "duties": du}}
    own.update({f"H91{d}|2026-11-{d}": {"blk": b, "credit": b, **TURN} for d, b in turns})
    nov = _month("2026-11", [("2026-11-01", "H9801", "LAX"), ("2026-11-02", "", "HNL")]
                 + [(f"2026-11-{d}", f"H91{d}", "") for d, _ in turns], 30)
    months = {"2026-10": _month("2026-10", [], 31), "2026-11": nov, "2026-12": _month("2026-12", [], 31)}
    return _st(months, own)


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
  const td = r.querySelector('.cal tr[data-d] td.far');
  const out = {heads, rows, key, red, helper, text: r.textContent, wide: document.documentElement.scrollWidth,
    pad: td ? getComputedStyle(td).paddingLeft : null,
    hb: [...r.querySelectorAll('.cal tr.hd th .hb')].map((x) => getComputedStyle(x).display),
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
    "midday": _midday(),
    "late": _late(),
    "half": _half(),  # Nov 1: one 30.5 min leg in the window
    "half100": _half([("04", "13:00"), ("07", "13:00"), ("10", "13:00"), ("13", "13:00"), ("16", "13:00"),
                      ("19", "13:00"), ("22", "13:00"), ("25", "8:30")]),  # Nov 2 to 29: 6000.5 min
}
WIDE = ("over", "rest")  # rendered in a 936 px box too, the pilot's copy and Ryan's (owner, role admin)


def _theme(dark):
    """The page around the card, as tests/fw1711_totals_render.js draws it: Home Assistant's theme variables, light or
    dark."""
    bg, card, fg = ("#111111", "#1c1c1c", "#e1e1e1") if dark else ("#fafafa", "#ffffff", "#212121")
    return (f"body{{margin:0;padding:8px;background:{bg};color:{fg};font-family:Roboto,Arial,sans-serif;"
            f"--card-background-color:{card};--primary-text-color:{fg};--secondary-text-color:"
            f"{'#9e9e9e' if dark else '#727272'};--divider-color:{'#333333' if dark else '#e0e0e0'};"
            f"--secondary-background-color:{'#282828' if dark else '#f5f5f5'};--primary-color:#03a9f4}}"
            f"ha-card{{display:block;background:var(--card-background-color);border-radius:12px}}")


# r1 (review): the grid in a box of a laptop-sized card (936 px, a 1280 px window): the three FAR columns' widths, the
# header row, and whether the grid scrolls in its box; `admin` = Ryan's own copy (owner, role admin), else the pilot's
WIDE_JS = """async ({h, dark, admin, W}) => { const box = document.createElement('div'); box.style.width = W + 'px';
  document.body.appendChild(box); const c = document.createElement('flight-watcher-schedule-card'); c.setConfig({});
  box.appendChild(c);
  c.hass = {states: h, themes: {darkMode: dark}, user: admin ? {is_owner: true, is_admin: true} : undefined,
    callService: async () => {}};
  await new Promise((ok) => setTimeout(ok, 300));
  const r = c.shadowRoot, w = r.querySelector('.wrap'), ths = [...r.querySelectorAll('.cal tr.hd th')];
  const out = {far: ths.slice(10, 13).map((th) => ({t: th.textContent.trim(), w: th.getBoundingClientRect().width})),
    table: r.querySelector('table.cal').getBoundingClientRect().width, sw: w.scrollWidth, cw: w.clientWidth,
    pad: getComputedStyle(r.querySelector('.cal tr[data-d] td.far')).paddingLeft,
    hb: [...r.querySelectorAll('.cal tr.hd th .hb')].map((x) => getComputedStyle(x).display),
    cells: [...r.querySelectorAll('.cal tr[data-d] td.far')].map((td) => td.textContent.trim())};
  box.remove(); return out; }"""


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
                pw = b.new_page(viewport={"width": 1280, "height": 900})
                pw.clock.set_fixed_time("2026-11-13T02:00:00Z")
                pw.set_content(page)
                pw.add_style_tag(content=_theme(dark))
                for name in WIDE:
                    for admin in (False, True):
                        st = copy.deepcopy(CASES[name])
                        if admin:
                            st["sensor.flight_watcher_state"]["attributes"]["role"] = "admin"
                        out[("wide", name, admin, dark)] = pw.evaluate(WIDE_JS, {"h": st, "dark": dark, "admin": admin,
                                                                                 "W": 936})
                pw.close()
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
                    pg3 = b.new_page(viewport={"width": 1024, "height": 900}, device_scale_factor=2)
                    pg3.clock.set_fixed_time("2026-11-13T02:00:00Z")
                    pg3.set_content(page)
                    pg3.add_style_tag(content=_theme(dark))
                    pg3.evaluate(JS, {"h": CASES["over"], "dark": dark, "shot": True})
                    pg3.wait_for_timeout(100)
                    pg3.screenshot(path=os.path.join(SHOTS, f"item4_over_1024_{'dark' if dark else 'light'}.png"),
                                   full_page=True)
                    pg3.close()
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
        assert far[2]["title"].startswith("FAR 117.23(b)(1) (100 flight hours in any 672 consecutive hours): 100:00 "
                                          "minus the busiest of the 672 h windows ending 24:00 HST that hold the day")
        # short enough for a 390 px phone: a dozen characters on one line, like the one-word Trip header, and the
        # three columns side by side within one screen when the grid is scrolled to them
        line = heads[2]["h"]
        assert all(len(h["t"]) <= 12 and h["h"] <= line + 0.5 for h in far), far
        assert far[2]["r"] - far[0]["l"] <= 300, far
        text = got[("over", dark)]["text"]
        assert "FAR-30/7" not in text and "FAR-100/672" not in text
        assert all(x["wide"] <= 390 for k, x in got.items() if len(k) == 2 and k[1] == dark)  # the grid scrolls


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
        assert c19["title"] == ("100h/672h: 10:57 left. 89:03 block flown or scheduled in the 672 h (28 days) "
                                "ending 24:00 2026-11-19, leg by leg. FAR 117.23(b)(1): at most 100 flight hours in "
                                "any 672 consecutive hours; this cell checks the 672 h ending 24:00 that day."), c19["title"]
        assert "~" not in c19["title"]
        assert _far(got, "over", 25, dark)[1]["title"].startswith("100h/672h: 1:20 over. 101:20 block flown or "
                                                                  "scheduled in the 672 h")


def test_room_cell_positive_zero_over_and_approximate(got):
    for dark in (False, True):
        # negative: every November day up to Nov 28 falls in the Nov 1 to 28 window (101:20)
        assert {_txt(got, "over", d, dark)[2] for d in range(1, 29)} == {"1:20 over"}
        assert _txt(got, "over", 29, dark)[2] == "11:40 left"  # positive
        assert _txt(got, "over", 30, dark)[2] == "11:40 left"
        r = _far(got, "over", 19, dark)[2]
        assert r["title"] == ("Room to 100h: 1:20 over. 100:00 minus the busiest of the 672 h windows ending 24:00 "
                              "HST that hold this day (101:20 flown or scheduled in the 28 days ending 24:00 "
                              "2026-11-25), looking back and forward (FAR 117.23(b)(1)). Only windows ending 24:00 are "
                              "tried: one ending mid-day can hold more, so the room can be less."), r["title"]
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
    for k, x in got.items():
        if len(k) != 2:
            continue
        name, dark = k
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
        assert all(t[d] == "✓ 36h 11/05" for d in range(5, 11)), t  # 36:45 from Nov 3 18:15 to Nov 5 07:00
        assert all(t[d] == "need 30h off" for d in range(11, 16)), t
        assert t[16] == "✓ 52h 11/16"  # 52:46 off since Nov 13 19:15, still on
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
        assert _txt(got, "over", 1, dark)[0] == "✓ 168h 11/01"


def test_key_explains_the_columns_with_units_and_the_rules(got):
    key = dict((r[0], r[1]) for r in got[("over", False)]["key"] if len(r) == 2)
    assert "FAR-30/7, FAR-100/672, Room" not in key
    t30, t100, room = key["30h in 7d"], key["100h in 672h"], key["Room to 100h"]
    assert t30.startswith("FAR 117.25(b): 30 consecutive hours free from all duty within the past 168 consecutive "
                          "hours (7 days) before a report.")
    assert "✓ 36h MM/DD" in t30 and "red 'need 30h off'" in t30 and "? = the window reaches before" in t30
    assert "– = mid-trip, no report that day" in t30 and "Need 30 h off by (totals)" in t30
    assert t100.startswith("FAR 117.23(b)(1): at most 100 flight hours in any 672 consecutive hours (28 days).")
    assert "hours and minutes" in t100 and "10:57 left = 89:03 flown or scheduled" in t100 and "1:20 over" in t100
    assert room.startswith("What is left, in hours and minutes (h:mm), under FAR 117.23(b)(1) (100 flight hours in any "
                           "672 consecutive hours):")
    assert ("busiest of the 672 h (28-day) windows that end at 24:00 HST and hold that day, looking back and forward"
            in room)
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


def _key(got, name="over", dark=False):
    return dict((r[0], r[1]) for r in got[(name, dark)]["key"] if len(r) == 2)


def _readme():
    with open(os.path.join(os.path.dirname(__file__), "..", "README.md"), encoding="utf-8") as f:
        text = " ".join(f.read().split())
    return text[text.index("**FAR 117 columns** (1.7.13"):][:2600]


def test_room_says_it_tries_only_the_windows_ending_midnight(got):
    """F1 (review): Room to 100h tries the 672 h windows ending 24:00 HST that hold the day (the math is unchanged;
    trying the windows that end mid-day, as far._cum does, is Ryan's call). A window ending mid-day can hold more, so
    the header, the cell's title, the Key and the README say what the cell tries and never call it the most block you
    could add."""
    import far
    from datetime import date, datetime
    for dark in (False, True):
        b, r = _far(got, "midday", 29, dark)[1:]
        assert (b["t"], r["t"]) == ("9:00 left", "9:00 left") and "bad" not in r["cls"]  # the card's hours, as before
        assert r["title"] == ("Room to 100h: 9:00 left. 100:00 minus the busiest of the 672 h windows ending 24:00 HST "
                              "that hold this day (91:00 flown or scheduled in the 28 days ending 24:00 2026-11-29), "
                              "looking back and forward (FAR 117.23(b)(1)). Only windows ending 24:00 are tried: one "
                              "ending mid-day can hold more, so the room can be less."), r["title"]
        head = got[("midday", dark)]["heads"][12]["title"]
        assert "Only those windows are tried: one ending mid-day can hold more, so the room can be less." in head
        assert "most block you could" not in head and "falls in" not in head
    room = _key(got, "midday")["Room to 100h"]
    assert ("Only windows ending 24:00 are tried: a window ending mid-day can hold more, so the room can be less than "
            "shown (a guide to the block you could add, not a legality check).") in room
    assert "The most block you could still add" not in room and "a window holding that day is over" not in room
    readme = _readme()
    assert "busiest of the 672 h windows ending 24:00 HST that hold the day" in readme
    assert "one ending mid-day can hold more, so the room can be less than shown" in readme
    assert "the most block you could add that day" not in readme

    # far.py on the same line: the 672 h from Nov 1 12:00 to Nov 29 12:00 hold 101:00, over the limit
    def trip(label, d, rep, arr, blk):
        r0, rel = far.window(date(2026, 11, d), date(2026, 11, d), rep, arr)
        s, e = (datetime.combine(date(2026, 11, d), far._t(x)) for x in (rep, arr))
        return {"label": label, "report": r0, "release": rel, "duties": [(s, e, blk)], "exact": True}
    mine = [trip("H9101", 1, "13:00", "23:00", 10.0), trip("H9127", 27, "06:00", "20:00", 1.0)]
    mine += [trip(f"H91{d:02d}", d, "06:00", "20:00", 10.0) for d in (4, 7, 10, 13, 16, 19, 22, 25)]
    res = far.legality(trip("H9129", 29, "01:00", "10:45", 10.0), mine)
    assert res["result"] == "NO" and "flight time 101:00 h in 672 h" in res["summary"], res


def test_30h_tick_speaks_for_the_first_duty_start_only(got):
    """F2 (review): the tick tests one report time, the day's first duty start (00:01 on a day off), and 00:01 is not
    the worst case: a later report that day can lose the break off the back of its 168 h. The check is today's; the
    header, the Key and the README say which report the tick covers, and the title gives 'covers reports until'."""
    for dark in (False, True):
        c = _far(got, "late", 10, dark)[0]
        assert c["t"] == "✓ 35h 11/04" and "ok30" in c["cls"]
        assert c["title"] == ("If you reported at 00:01: longest free block in the 168 h before was 35:59 from 00:01 "
                              "2026-11-03. 30 h free in 7 days met (FAR 117.25(b)): this break covers reports until "
                              "06:00 2026-11-10."), c["title"]
        head = got[("late", dark)]["heads"][10]["title"]
        assert ("✓ 36h MM/DD = a report at that day's first duty start (00:01 on a day off) is covered: the longest "
                "break off duty in the 168 h before it, in whole hours, and the day it ended. A later report that day "
                "may not be: hover a cell for the hours and 'covered until'.") in head, head
        assert "a report that day is covered" not in head
    t30 = _key(got, "late")["30h in 7d"]
    assert ("✓ 36h MM/DD = a report at that day's first duty start (00:01 on a day off) is covered: the longest break "
            "off duty in the 168 h before it, in whole hours, and the date that break ended; a later report that day "
            "may not be (hover for the hours and 'covered until'); red 'need 30h off' = that report is not covered;"
            ) in t30, t30
    assert "a report that day is covered" not in t30
    readme = _readme()
    assert "`✓ 36h 11/05` (a report at that day's first duty start, 00:01 on a day off, is covered" in readme
    assert "a later report that day may not be, so its title gives 'covers reports until'" in readme


def test_key_says_a_trip_with_no_times_counts_nothing(got):
    """F3 (review, wording only): a trip on the line whose times are not read yet adds no block, and with no report and
    release on file counts as time off. Marking such a cell '~' or '?' changes what the column decides: Ryan's call.
    Until then the Key and the README say it."""
    key = _key(got)
    assert ("a trip whose report and release are not on file yet (its times not read) counts as time off"
            in key["30h in 7d"])
    assert "A trip whose block times are not read yet adds 0:00 here and in Room to 100h." in key["100h in 672h"]
    assert ("A trip whose times are not read yet adds no block, and with no report and release on file counts as time "
            "off, so the cells can read better than the line is until its times are in.") in _readme()


def _hmin(m):
    return int(m.group(1)) * 60 + int(m.group(2))


def test_cell_and_title_add_up_to_100_hours(got):
    """F4 (review): the block is rounded to the minute once, so a cell (left or over) and its title (the block) always
    add up to 100:00, also when a leg counts a half minute (FLICA Block 1:01 over duty block 61 + 61)."""
    for dark in (False, True):
        assert _txt(got, "half", 1, dark)[1:] == ["99:29 left", "98:59 left"]  # Room: both legs, 1:01
        assert "0:31 block flown or scheduled" in _far(got, "half", 1, dark)[1]["title"]
        c = _far(got, "half100", 29, dark)
        assert [x["t"] for x in c[1:]] == ["0:01 over", "0:01 over"] and all("bad" in x["cls"] for x in c[1:])
        assert "100:01 block flown or scheduled" in c[1]["title"] and "(100:01 flown or scheduled" in c[2]["title"]
        n = 0
        for name in CASES:
            for d, cells in got[(name, dark)]["rows"].items():
                if len(cells) != 3:
                    continue
                for cell, pat in ((cells[1], r"\. (\d+):(\d\d) block flown"), (cells[2], r"\((\d+):(\d\d) (?:flown or "
                                                                                        r"scheduled )?in the 28 days")):
                    m, t = re.search(pat, cell["title"]), re.fullmatch(r"~?(\d+):(\d\d) (left|over)", cell["t"])
                    assert m and t, (name, d, cell)
                    left = _hmin(t) * (-1 if t.group(3) == "over" else 1)
                    assert left + _hmin(m) == 6000, (name, d, cell)
                    n += 1
        assert n > 200


def test_block_is_flown_or_scheduled(got):
    """F6 (review): a window after today holds block that is only scheduled: the titles, the header, the Key and the
    README say 'flown or scheduled', never 'block flown' alone."""
    for dark in (False, True):
        x = got[("over", dark)]
        titles = [c["title"] for cells in x["rows"].values() for c in cells[1:]]
        assert titles and all("flown or scheduled" in t for t in titles)
        assert not any(re.search(r"block flown(?! or scheduled)", t) for t in titles)
        assert "minus the block flown or scheduled in the 672 h ending 24:00 that day" in x["heads"][11]["title"]
    t100 = _key(got)["100h in 672h"]
    assert "(10:57 left = 89:03 flown or scheduled)" in t100 and not re.search(r"flown(?! or scheduled)", t100)
    assert "the block flown or scheduled in its title" in _readme()


def test_grid_about_as_wide_as_in_1711(got):
    """r1 (review): the hours in the tick and the longer headers made the grid 77 px wider, so a card 870 to 972 px wide
    scrolled where 1.7.11 fit. Now the tick has no 'off', the 100h in 672h and Room to 100h headers take two lines above
    700 px and the FAR cells pad 4 px a side: the three columns are within about 20 px of 1.7.11's (176 to 180 px here),
    and the pilot's and Ryan's grids fit a 936 px box again, light and dark."""
    for dark in (False, True):
        for name in WIDE:
            for admin in (False, True):
                x = got[("wide", name, admin, dark)]
                assert [h["t"] for h in x["far"]] == ["30h in 7d", "100h in 672h", "Room to 100h"]
                assert sum(h["w"] for h in x["far"]) <= 205, (name, admin, dark, x["far"])
                assert x["sw"] <= x["cw"] + 1, (name, admin, dark, x["table"], x["cw"])
                assert x["pad"] == "4px"
                assert x["hb"] == ["inline", "inline"]  # the two header breaks show
                assert not any(re.fullmatch(r"✓ \d+h off .*", t) for t in x["cells"])
                assert name != "rest" or "✓ 36h 11/05" in x["cells"]
        # a phone keeps the FAR headers on one line (the breaks hidden) and the grid's own 6 px padding
        assert got[("over", dark)]["hb"] == ["none", "none"] and got[("over", dark)]["pad"] == "6px"
