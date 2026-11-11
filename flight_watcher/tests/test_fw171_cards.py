"""1.7.1, the cards: F#4 the clock card keeps a picked interval and marks a command in flight; F#32 the schedule card
reports Improved-Pay-Gross once its pairings package has settled; F#43 / F#52 the pilot lookup is a form with a label,
the pickers filter says it is one and its speed columns show at 390 px; F#66 the RECALL ALERT bar opens the portal's
Watcher tab; F#77 a late Refresh answer clears the recall card's note; F#93 / F#155 the settings card's Show buttons,
autocomplete, neutral "nothing new" and Remove CrewTrac login; F#96 a pilot's card copy names nobody and keeps its
comments whole; F#107 swap ideas on the pot card; F#119 every changed card at 390 and 1100 px, light and dark, with WCAG
AA contrast (4.5:1, 3:1 for large text) computed from the rendered colors. The cards run as the portal serves them
(the pilot's copy, FW_PORTAL on) on a page with the portal's theme variables (HOM fwportal shell.css) and its ha-card.
Synthetic data and made-up names only ("Doe, Jane")."""
import contextlib
import json
import os
import re

import pytest

import cards
import portal as PT
import sealed as SEAL
from test_cards import _chromium
from test_release_a_cards import POT, TB
from test_release_a_schedule_card import FAILED, _award, _read

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = "flight_watcher_pilot2"
ORIGIN = "https://portal.test"
NOW = "2026-11-10T11:30:00Z"  # Nov 10 01:30 HST
NOW_TS = 1794310200  # NOW in Unix seconds (the time a sealed message carries)
SHOTS = os.environ.get("FW_171_SHOTS", "")  # a folder: every render of the read test is saved there as a PNG

# HOM fwportal 1.8 static/shell.css: the portal's theme variables, light and dark (dark follows the device)
PORTAL_CSS = """
:root{color-scheme:light dark;--primary-color:#0074c8;--accent-color:#00c7e6;--primary-background-color:#f2f5f8;
 --secondary-background-color:#e7edf2;--card-background-color:#ffffff;--ha-card-background:var(--card-background-color);
 --primary-text-color:#0a1929;--secondary-text-color:#4a5b6b;--text-primary-color:#ffffff;--divider-color:#d3dce4;
 --error-color:#c62828;--success-color:#2e7d32;--warning-color:#b26a00;--info-color:#0074c8;
 --table-row-background-color:#ffffff;--table-row-alternative-background-color:#f6f8fa}
@media (prefers-color-scheme: dark){:root{--primary-color:#3a9be0;--primary-background-color:#031526;
 --secondary-background-color:#0a1929;--card-background-color:#04253e;--primary-text-color:#e6eef5;
 --secondary-text-color:#9fb3c4;--text-primary-color:#ffffff;--divider-color:#1d3b55;--error-color:#ef5350;
 --success-color:#c0e585;--warning-color:#ffb74d;--info-color:#3a9be0;--table-row-background-color:#04253e;
 --table-row-alternative-background-color:#072f4d}}
*{box-sizing:border-box}html,body{margin:0}
body{background:var(--primary-background-color);color:var(--primary-text-color);
 font:15px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;-webkit-text-size-adjust:100%}
main{max-width:1100px;margin:0 auto;padding:12px 16px 48px}.view{display:grid;gap:12px}.view>*{min-width:0}
"""

HARNESS_JS = r"""
customElements.define("ha-card", class extends HTMLElement { constructor() { super();
  this.attachShadow({ mode: "open" }).innerHTML = "<style>:host{display:block;position:relative;"
    + "background:var(--ha-card-background,var(--card-background-color));color:var(--primary-text-color);"
    + "border:1px solid var(--divider-color);border-radius:var(--ha-card-border-radius,12px)}</style><slot></slot>"; } });
customElements.define("ha-icon", class extends HTMLElement {});
window.calls = [];
window.mkHass = (states, extra) => ({ states, language: "en", user: { id: "fw-portal", name: "Pilot", is_admin: false, is_owner: false },
  themes: { darkMode: matchMedia("(prefers-color-scheme: dark)").matches },
  callService: async (d, s, data) => { window.calls.push([d, s, data]); }, fwPending: {}, ...(extra || {}) });
window.mount = (tag, cfg, states, extra) => { const c = document.createElement(tag); c.setConfig(cfg || {});
  c.hass = window.mkHass(states, extra); document.querySelector(".view").appendChild(c); return c; };
// WCAG 2 contrast of every visible text node in a card, from its computed color and the backgrounds under it
// (translucent layers composited, opacity of the element and its ancestors applied to the text). Skipped: aria-hidden
// decoration, disabled-state marks (aria-disabled), emoji (drawn in their own colors), select menus. A button in the
// theme's own primary pair (background --primary-color, text --text-primary-color) is listed apart: that pair is the
// portal's palette, not the card's.
window.fwContrast = (host) => {
  const parse = (c) => { const m = /rgba?\(([^)]+)\)/.exec(c || ""); if (!m) return null;
    const p = m[1].split(/[\s,\/]+/).filter(Boolean).map(parseFloat); return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 }; };
  const up = (e) => e.parentElement || (e.getRootNode() instanceof ShadowRoot ? e.getRootNode().host : null);
  const over = (t, b) => ({ r: t.r * t.a + b.r * (1 - t.a), g: t.g * t.a + b.g * (1 - t.a), b: t.b * t.a + b.b * (1 - t.a), a: 1 });
  const bgOf = (el) => { const layers = []; let base = null;
    for (let e = el; e; e = up(e)) { const c = parse(getComputedStyle(e).backgroundColor); if (c && c.a > 0) { if (c.a >= 1) { base = { el: e, c }; break; } layers.push(c); } }
    let bg = base ? base.c : { r: 255, g: 255, b: 255, a: 1 };
    for (let i = layers.length - 1; i >= 0; i--) bg = over(layers[i], bg);
    return { bg, base: base && base.el }; };
  const opa = (el) => { let o = 1; for (let e = el; e; e = up(e)) o *= parseFloat(getComputedStyle(e).opacity); return o; };
  const lum = (c) => { const f = (v) => { v /= 255; return v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b); };
  const ratio = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
  const probe = (prop, val) => { const d = document.createElement("div"); d.style[prop] = val; document.body.appendChild(d);
    const c = getComputedStyle(d)[prop]; d.remove(); return c; };
  const prim = probe("backgroundColor", "var(--primary-color)"), onPrim = probe("color", "var(--text-primary-color)");
  const rgb = (c) => `rgb(${Math.round(c.r)}, ${Math.round(c.g)}, ${Math.round(c.b)})`;
  const fails = [], theme = [], seen = [];
  const walk = (root) => {
    const tw = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    for (let n = tw.nextNode(); n; n = tw.nextNode()) {
      const t = n.textContent.replace(/\s+/g, " ").trim(); if (!t) continue;
      const el = n.parentElement; if (!el) continue;
      if (el.closest("style,script,template,select,option,[aria-hidden='true'],[aria-disabled='true']")) continue;
      if (!el.checkVisibility({ checkOpacity: false, checkVisibilityCSS: true, visibilityProperty: true })) continue;
      const rg = document.createRange(); rg.selectNodeContents(n); if (!rg.getClientRects().length) continue;
      if (/^[\p{Extended_Pictographic}︎️‍\s]+$/u.test(t)) continue;
      const cs = getComputedStyle(el), fg = parse(cs.color), { bg, base } = bgOf(el);
      const eff = over({ ...fg, a: fg.a * opa(el) }, bg), r = ratio(eff, bg);
      const size = parseFloat(cs.fontSize), w = parseInt(cs.fontWeight, 10);
      const need = size >= 24 || (w >= 700 && size >= 18.66) ? 3 : 4.5;
      const row = { text: t.slice(0, 48), ratio: Math.round(r * 100) / 100, need, fg: cs.color, bg: rgb(bg), cls: `${el.tagName.toLowerCase()}.${el.className}` };
      seen.push(row);
      if (r >= need) continue;
      if (base && getComputedStyle(base).backgroundColor === prim && cs.color === onPrim) { theme.push(row); continue; }
      fails.push(row);
    }
    for (const e of root.querySelectorAll("*")) if (e.shadowRoot) walk(e.shadowRoot);
  };
  walk(host.shadowRoot);
  return { fails, theme, n: seen.length };
};
window.fwFits = (c) => { const hc = c.shadowRoot && c.shadowRoot.querySelector("ha-card");
  return { right: Math.round(c.getBoundingClientRect().right), page: document.documentElement.scrollWidth,
    inner: hc ? hc.scrollWidth - hc.clientWidth : 0 }; };
"""


def _card(name, pilot=True):
    """A card as the portal serves it to pilot2 (FW_PORTAL on), or the admin's own (Home Assistant)."""
    built = cards.build("9.9.9", ["pilot2"])
    return PT.portal_card(built[f"flight-watcher-{name}-pilot2.js"]) if pilot else built[f"flight-watcher-{name}.js"]


def _s(state, attrs=None, lu="2026-11-10T11:20:00+00:00"):
    return {"state": str(state), "attributes": attrs or {}, "last_updated": lu, "last_changed": lu}


def _pilot(states):
    """The admin's entity ids (flight_watcher_x) as pilot2's (flight_watcher_pilot2_x)."""
    return {k.replace("flight_watcher_", P + "_", 1): v for k, v in states.items()}


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


def _page(b, scripts, width=390, scheme="light", clock=False, routes=None):
    """A page at https://portal.test/fw/ (a secure context, so WebCrypto works) with the portal's theme and the
    scripts; every other URL there answers 404 unless routes ({url part: (status, json)}) says otherwise. clock:
    Playwright's clock installed at NOW (timers run only when the test says), else the time fixed at NOW."""
    ctx = b.new_context(viewport={"width": width, "height": 900}, color_scheme=scheme, timezone_id="Pacific/Honolulu")
    html = ("<!doctype html><html><head><meta charset='utf-8'><style>" + PORTAL_CSS + "</style></head><body><main>"
            "<section class='view'></section></main><script>" + HARNESS_JS + "</script>"
            + "".join(f"<script>{s}</script>" for s in scripts) + "</body></html>")

    def serve(route):
        url = route.request.url
        if url == ORIGIN + "/fw/":
            return route.fulfill(status=200, content_type="text/html", body=html)
        for part, (status, body) in (routes or {}).items():
            if part in url:
                return route.fulfill(status=status, content_type="application/json", body=json.dumps(body))
        return route.fulfill(status=404, body="")
    ctx.route(ORIGIN + "/**", serve)
    pg = ctx.new_page()
    if clock:
        pg.clock.install(time=NOW)
    else:
        pg.clock.set_fixed_time(NOW)
    pg.goto(ORIGIN + "/fw/")
    return pg


# ---------------------------------------------------------------- F#96: the name scrub
def test_pilot_copy_names_nobody_and_leaves_no_broken_comment():
    built = cards.build("1", ["pilot2"])
    for base, orig in cards.sources().items():
        cp = built[f"{base}-pilot2.js"]
        assert not re.search(r"\bryan\b", cp, re.I), base  # review r4: in any letter case
        a_lines, b_lines = orig.splitlines(), cp.splitlines()
        assert len(a_lines) == len(b_lines), base
        for a, b in zip(a_lines, b_lines):
            if "Ryan" not in a:
                continue
            assert "admin" in b, (base, b)
            # nothing dangles where the name was: no new doubled space, "'s" with nothing before it, "( ," or ", )"
            assert b.count("  ") == a.count("  "), (base, b)
            dangle = re.compile(r"(?:^|[\s(/*])'s\b|\(\s*[,;:)]|,\s*[,;:)]")
            assert dangle.findall(b) == dangle.findall(a.replace("Ryan", "X")), (base, b)
    st = built["flight-watcher-settings-card-pilot2.js"]
    assert "(1.4.5, the admin Nov 6: labeled Credentials on the Settings tab)" in st
    assert "The admin's card never shows them." in st
    assert cards.scrub_names("Ryan's card. Ryan, Nov 6 (Ryan)") == "The admin's card. The admin, Nov 6 (the admin)"


# ---------------------------------------------------------------- F#66: the RECALL ALERT bar on the Watcher tab
def _verdict(date, pairing, verdict, status=None):
    return {"id": f"{date}|{pairing}|recall", "date": date, "kind": "recall", "pairing": pairing, "seat": "FO", "sen": 900,
            "pilot": "Doe, Jane", "verdict": verdict,
            "why": ["went to #900, junior to you (#500)", "open and legal on your line (FAR 117.25(e), PWA 10.E.1.a)"],
            "refs": ["PWA 22.G.2.e"], "act": {"status": status, "narrative": "On 2026-11-10 ..."} if status else {}}


def _recall_states(miss=True, checked="2026-11-10T11:00:00+00:00", lu="2026-11-10T11:20:00+00:00"):
    vs = [_verdict("2026-11-10", "H3601", "MISSED", "new")] if miss else []
    vs += [_verdict("2026-11-10", "H3602", "POSSIBLE", "new"), _verdict("2026-11-10", "H3603", "NO")]
    a = {"open": 2, "alert": 1 if miss else 0, "me": {"sen": 500, "seat": "FO"}, "last": "2026-11-10", "checked": checked,
         "received": "2026-11-10T10:00:00+00:00", "sen_source": "typed",
         "days": [{"date": "2026-11-10", "file": "ok", "verdicts": vs}]}
    return _pilot({"sensor.flight_watcher_recall_o75": _s("1", a, lu), "sensor.flight_watcher_state": _s("idle", {"role": "pilot"})})


def test_watcher_tab_starts_with_the_recall_alert_bar():
    layout = json.load(open(os.path.join(HERE, "portal_layout.json"), encoding="utf-8"))
    first = layout["tabs"][0]["cards"][0]
    assert layout["tabs"][0]["id"] == "watcher" and first == {"type": "custom:flight-watcher-recall-card-{name}", "mode": "alert"}
    with _browser() as b:
        pg = _page(b, [_card("recall-card")])
        got = pg.evaluate("""(st) => { const quiet = mount('flight-watcher-recall-card-pilot2', {mode: 'alert'}, st[1]);
          const c = mount('flight-watcher-recall-card-pilot2', {mode: 'alert'}, st[0]);
          let moved = 0; window.addEventListener('location-changed', () => { moved++; });
          const bar = c.shadowRoot.querySelector('.bar'), btn = c.shadowRoot.querySelector('[data-go]');
          const out = {head: bar.querySelector('.bh').textContent, line: bar.querySelector('li').textContent.trim(),
                       btn: btn.textContent, quiet: quiet.getBoundingClientRect().height, quietShown: getComputedStyle(quiet).display,
                       h: btn.getBoundingClientRect().height, fit: fwFits(c)};
          btn.click(); out.path = location.pathname; out.moved = moved; return out; }""",
                          [_recall_states(), _recall_states(miss=False)])
    assert got["head"].startswith("RECALL ALERT") and got["line"].startswith("Tue Nov 10 Recall H3601 went to #900")
    assert got["btn"] == "Review and file CCR on Recall/O75"
    assert got["path"] == "/flight-watcher-pilot2/recall" and got["moved"] == 1
    # the portal (HOM shell.js fromLocation, on location-changed) opens the tab this path names: #recall
    assert re.match(r"^/flight-watcher(?:-[a-z0-9_]+)?/([a-z]+)", got["path"]).group(1) == "recall"
    assert got["quietShown"] == "none" and got["quiet"] == 0  # no alert: no gap in the tab's grid
    assert got["fit"]["page"] <= 390


# ---------------------------------------------------------------- F#77: a late Refresh answer
def test_recall_card_late_answer_clears_the_no_answer_note():
    with _browser() as b:
        pg = _page(b, [_card("recall-card")], clock=True)
        pg.evaluate("(st) => { window.C = mount('flight-watcher-recall-card-pilot2', {}, st); "
                    "C.shadowRoot.querySelector('[data-refresh]').click(); }", _recall_states())
        note = "(() => C.shadowRoot.querySelector('[data-checked]').textContent)()"
        assert pg.evaluate("window.calls.map((c) => [c[2].topic, c[2].payload])") == [
            [f"{P}/recall/act", '{"refresh":true}']]
        pg.clock.run_for(15500)
        assert pg.evaluate(note) == "No answer from the Watcher yet. Is it running?"
        # the same sensor again (another entity's update): the note stays
        pg.evaluate("(st) => { C._sig = null; C.hass = mkHass(st); }", _recall_states())
        assert pg.evaluate(note).startswith("No answer")
        # the answer, 20 s late: a new checked time clears the note
        pg.evaluate("(st) => { C.hass = mkHass(st); }",
                    _recall_states(checked="2026-11-10T11:30:20+00:00", lu="2026-11-10T11:30:20+00:00"))
        assert pg.evaluate(note) == "checked Nov 10 01:30 HST"
        assert pg.evaluate("C.shadowRoot.querySelector('[data-refresh]').disabled") is False


# ---------------------------------------------------------------- F#4: the clock card
def _clock_states(nm="5", hs="30", last="2026-11-10T11:29:00+00:00", hunt="off", st="idle"):
    return _pilot({
        "sensor.flight_watcher_state": _s(st, {"note": "", "role": "pilot"}),
        "sensor.flight_watcher_last_check": _s(last), "sensor.flight_watcher_next_check": _s("2026-11-10T11:34:00+00:00"),
        "switch.flight_watcher_hunt_mode": _s(hunt), "switch.flight_watcher_pause": _s("off"),
        "number.flight_watcher_hunt_check_every": _s(hs, {"min": 5, "max": 90}),
        "number.flight_watcher_normal_check_every": _s(nm, {"min": 1, "max": 90})})


def test_clock_card_keeps_a_picked_interval_until_the_state_shows_it():
    ns = f"number.{P}_normal_check_every"
    with _browser() as b:
        pg = _page(b, [_card("clock-card")], clock=True)
        pg.evaluate("(st) => { window.C = mount('flight-watcher-clock-card-pilot2', {}, st); }", _clock_states())
        sel = "C.shadowRoot.getElementById('ns')"
        val = f"(() => {sel}.value)()"
        assert pg.evaluate(val) == "5"
        # the focus guard: a value being chosen (the menu open, nothing sent yet) is not reset by the 1 s redraw
        pg.evaluate(f"(() => {{ {sel}.focus(); {sel}.value = '15'; }})()")
        pg.clock.run_for(1100)
        assert pg.evaluate(val) == "15"
        pg.evaluate(f"(() => {{ {sel}.value = '10'; {sel}.dispatchEvent(new Event('change')); {sel}.blur(); }})()")
        assert pg.evaluate("window.calls.at(-1)") == ["number", "set_value", {"entity_id": ns, "value": 10}]
        pg.clock.run_for(3000)  # the old state on every tick: the picked value stays
        assert pg.evaluate(val) == "10"
        # the portal's mark while it is in flight: the select waits, still showing it
        pg.evaluate("([st, id]) => { C.hass = mkHass(st, {fwPending: {[id]: {label: 'Normal: check every'}}}); }",
                    [_clock_states(), ns])
        assert pg.evaluate(f"[{sel}.value, {sel}.disabled]") == ["10", True]
        pg.evaluate("(st) => { C.hass = mkHass(st); }", _clock_states(nm="10"))  # the export shows it: settled
        pg.clock.run_for(1100)
        assert pg.evaluate(f"[{sel}.value, {sel}.disabled, Object.keys(C._want)]") == ["10", False, []]
        # refused: the mark comes and goes without the state moving, so the select shows the Watcher's value again
        pg.evaluate(f"(() => {{ {sel}.value = '20'; {sel}.dispatchEvent(new Event('change')); }})()")
        pg.evaluate("([st, id]) => { C.hass = mkHass(st, {fwPending: {[id]: {label: 'x'}}}); }", [_clock_states(nm="10"), ns])
        pg.evaluate("(st) => { C.hass = mkHass(st); }", _clock_states(nm="10"))
        assert pg.evaluate(val) == "10"
        # Home Assistant (no pending marks): no answer in 20 s and it goes back to the state
        pg.evaluate(f"(() => {{ {sel}.value = '30'; {sel}.dispatchEvent(new Event('change')); }})()")
        pg.clock.run_for(15000)
        assert pg.evaluate(val) == "30"
        pg.clock.run_for(6000)
        assert pg.evaluate(val) == "10"


def test_clock_card_buttons_say_sending_while_their_command_is_in_flight():
    with _browser() as b:
        pg = _page(b, [_card("clock-card")], clock=True)
        pg.evaluate("(st) => { window.C = mount('flight-watcher-clock-card-pilot2', {}, st); }", _clock_states(hunt="on"))
        btn = "(() => ['chk', 'hunt', 'pz'].map((i) => { const b = C.shadowRoot.getElementById(i); return [b.textContent.trim(), b.disabled]; }))()"
        before = pg.evaluate(btn)
        assert [x[1] for x in before] == [False, False, False] and before[0][0].endswith("Check now")
        pend = {f"button.{P}_check_now": {"label": "Scan FLICA now"}, f"switch.{P}_hunt_mode": {"label": "Hunt mode"}}
        pg.evaluate("([st, p]) => { C.hass = mkHass(st, {fwPending: p}); }", [_clock_states(hunt="on"), pend])
        assert pg.evaluate(btn) == [["Sending...", True], ["Sending...", True], [before[2][0], False]]
        pg.evaluate("(() => { C.shadowRoot.getElementById('chk').click(); })()")
        assert pg.evaluate("window.calls.length") == 0  # no second tap while the first is in flight
        pg.evaluate("(st) => { C.hass = mkHass(st); }", _clock_states(hunt="on"))
        assert pg.evaluate(btn) == before


# ---------------------------------------------------------------- F#32: Improved-Pay-Gross once the package settles
PACKAGE = {"month": "2026-11", "source": "synthetic", "start": "2026-11-01", "end": "2026-11-30",
           "cols": ["id", "report", "dep", "release", "rel_days", "first_duty_min", "route", "credit", "tafb", "days"],
           "rows": [["H9101", "08:00", "09:00", "18:00", 1, 600, "HNL-SFO-HNL", "15h00", "34h00", "3 4"]]}


def _improved(pg):
    return pg.evaluate(f"window.calls.filter((c) => c[2].topic === '{P}/improved/set').map((c) => JSON.parse(c[2].payload))")


def test_schedule_card_reports_improved_pay_once_the_package_settles():
    st = _pilot(_read())
    del st[f"sensor.{P}_own_trip_times"]  # the trip's credit can only come from the package
    with _browser() as b:
        # the package arrives late: nothing is reported before it, then one report with its credit
        pg = _page(b, ["window.release = null; const real = window.fetch; window.fetch = (u, o) => "
                       "String(u).includes('pairings_2026-11') ? new Promise((ok) => { window.release = () => ok(new Response("
                       + json.dumps(json.dumps(PACKAGE)) + ", {status: 200})); }) : real(u, o);", _card("schedule-card")])
        pg.evaluate("(st) => { window.C = mount('flight-watcher-schedule-card-pilot2', {}, st); }", st)
        pg.wait_for_timeout(100)
        assert _improved(pg) == []  # the package still loading: no low first figure
        pg.evaluate("window.release()")
        pg.wait_for_function(f"window.calls.some((c) => c[2].topic === '{P}/improved/set')")
        first = _improved(pg)
        assert len(first) == 1 and first[0]["month"] == "2026-11" and first[0]["current"] > 0, first
        pg.evaluate("(st) => { C.hass = mkHass(st); }", st)  # another update, the same figures: not sent again
        pg.wait_for_timeout(50)
        assert _improved(pg) == first
        # no package for the month (404): one report once that is known
        pg2 = _page(b, [_card("schedule-card")])
        pg2.evaluate("(st) => { window.C = mount('flight-watcher-schedule-card-pilot2', {}, st); }", st)
        pg2.wait_for_function(f"window.calls.some((c) => c[2].topic === '{P}/improved/set')")
        pg2.wait_for_timeout(100)
        assert len(_improved(pg2)) == 1


# ---------------------------------------------------------------- F#43 / F#52: the pilot lookup and the pickers filter
def test_pilot_search_card_asks_once_per_press_through_its_form():
    """FW-0025 and F#43: Go and Enter both submit the form, and its submit asks; a double tap on Go, an Enter right after
    Go or a held Enter (auto-repeat) inside 2 s does not ask again; another name, or the same one 2 s later, does. A
    phone keyboard's Go or Search key submits the form the same way (requestSubmit here)."""
    with _browser() as b:
        pg = _page(b, [_card("pilot-search-card")], clock=True)
        pg.evaluate("(st) => { window.asks = []; window.addEventListener('flight-watcher-pilot-pilot2', (e) => asks.push(e.detail));"
                    " window.C = mount('flight-watcher-pilot-search-card-pilot2', {}, st); }",
                    _pilot({"sensor.flight_watcher_state": _s("idle", {"role": "pilot"})}))
        card = pg.locator("flight-watcher-pilot-search-card-pilot2")
        inp, go = card.locator("input"), card.locator("button")
        attrs = pg.evaluate("""(() => { const i = C.shadowRoot.querySelector('input'), r = C.shadowRoot;
          return {form: !!i.closest('form'), hint: i.getAttribute('enterkeyhint'), ac: i.getAttribute('autocomplete'),
                  font: getComputedStyle(i).fontSize, type: r.querySelector('button').type, ph: i.placeholder,
                  label: r.querySelector('.lb').checkVisibility() ? r.querySelector('.lb').textContent : '',
                  help: r.querySelector('.hint').checkVisibility() ? r.querySelector('.hint').textContent : ''}; })()""")
        assert attrs == {"form": True, "hint": "search", "ac": "off", "font": "16px", "type": "submit",
                         "ph": "Last name or employee #", "label": "Look up a pilot's month (asks FLICA)",
                         "help": "An employee number finds any pilot; a whole last name (or Last, First) finds pilots on the award or "
                                 "seniority list on file."}
        asks = "window.asks.length"
        inp.fill("  ")
        go.click()
        assert pg.evaluate(asks) == 0
        inp.fill(" Doe ")
        go.click()
        go.click()
        assert pg.evaluate(asks) == 1
        pg.clock.run_for(300)
        inp.press("Enter")  # right after Go: the same press
        assert pg.evaluate(asks) == 1
        pg.clock.run_for(2500)
        inp.press("Enter")
        assert pg.evaluate(asks) == 2
        pg.keyboard.down("Enter")  # held: the key's auto-repeat submits again inside 2 s
        pg.keyboard.down("Enter")
        pg.keyboard.up("Enter")
        assert pg.evaluate(asks) == 2
        inp.fill("Roe")
        pg.evaluate("C.shadowRoot.querySelector('form').requestSubmit()")  # a phone keyboard's Search key
        assert pg.evaluate("window.asks") == [{"q": "Doe"}, {"q": "Doe"}, {"q": "Roe"}]
        # the admin's card (Home Assistant): no label or hint lines, the long placeholder
        pg.evaluate("(st) => { C.hass = mkHass(st); }", _pilot({"sensor.flight_watcher_state": _s("idle", {"role": "admin"})}))
        assert pg.evaluate("[C.shadowRoot.querySelector('.lb').checkVisibility(), C.shadowRoot.querySelector('.hint')"
                           ".checkVisibility(), C.shadowRoot.querySelector('input').placeholder]") == [
            False, False, "Anybody's schedule: last name, first name or employee #"]


PICKERS = [{"name": "Doe, Jane", "emp": "10001", "pos": "FO", "n": 12, "month_n": 3, "year_n": 9, "inflt_n": 1,
            "lays": [["NRT", 4], ["SIN", 2]], "last_lay": "NRT", "min_s": 41, "avg_s": 75},
           {"name": "Roe, Maximilian", "emp": "10002", "pos": "RO", "n": 5, "month_n": 1, "year_n": 5, "inflt_n": 0,
            "lays": [["SFO", 3]], "last_lay": "SFO", "min_s": 3700, "avg_s": 7300},
           {"name": "Poe, Sam", "emp": "10003", "pos": "FO", "n": 2, "month_n": 0, "year_n": 2, "inflt_n": 0, "lays": [],
            "last_lay": "", "min_s": 30, "avg_s": 40}]
PICKERS_JS = """(st) => { const c = mount(st[0], {entity: st[1], open: true}, st[2]); const r = c.shadowRoot;
  const vis = (e) => e.checkVisibility(), wrap = r.querySelector('.wrap'), vw = innerWidth;
  const ths = [...r.querySelectorAll('th')].filter(vis);
  return {heads: ths.map((t) => t.innerText), right: Math.max(...ths.map((t) => t.getBoundingClientRect().right)), vw,
          scroll: wrap.scrollWidth - wrap.clientWidth, label: r.querySelector('label').textContent,
          ph: r.querySelector('input').placeholder, small: [...r.querySelectorAll('.sm')].filter(vis).map((x) => x.innerText),
          first: [...r.querySelectorAll('tbody tr:first-child td')].filter(vis).map((x) => x.innerText.replace(/\\s+/g, ' ').trim())}; }"""


def test_pickers_card_filter_is_labeled_and_the_speeds_fit_at_390():
    st = {f"sensor.{P}_pickers": _s("3", {"pickers": PICKERS})}
    admin = {"sensor.flight_watcher_pickers": _s("3", {"pickers": PICKERS})}
    pilot = ["flight-watcher-pickers-card-pilot2", f"sensor.{P}_pickers", st]
    with _browser() as b:
        narrow = _page(b, [_card("pickers-card")]).evaluate(PICKERS_JS, pilot)
        wide = _page(b, [_card("pickers-card")], width=1100).evaluate(PICKERS_JS, pilot)
        ha = _page(b, [_card("pickers-card", pilot=False)], width=1100).evaluate(
            PICKERS_JS, ["flight-watcher-pickers-card", "sensor.flight_watcher_pickers", admin])  # the admin's (HA)
    assert narrow["label"] == "Filter this list (it does not ask FLICA)"
    assert narrow["ph"] == "Filter this list (name, emp or layover)"
    assert narrow["heads"] == ["Pilot", "Pos", "Best", "Avg"]
    assert narrow["scroll"] <= 0 and narrow["right"] <= narrow["vw"]  # the speeds on screen, no sideways scroll
    assert narrow["first"] == ["Poe, Sam Emp 10003 · 2 pickups: 0 this month, 2 this year, 0 in flight", "FO", "30s", "40s"]
    assert narrow["small"][1] == "Emp 10001 · 12 pickups: 3 this month, 9 this year, 1 in flight · NRT4SIN2"
    full = ["Pilot", "Emp", "Pos", "Ttl Pickups", "Month Pickups", "Year Pickups", "InFlt Pickups", "Common Layover",
            "Fastest Pickup Speed", "Avg Pickup Speed"]
    for w in (wide, ha):  # the desktop table as before
        assert w["heads"] == full and w["small"] == [] and w["scroll"] <= 0
        assert w["first"] == ["Poe, Sam", "10003", "FO", "2", "0", "2", "0", "-", "30s", "40s"]


# ---------------------------------------------------------------- F#107: swap ideas on the pot card
IDEAS = [{"for": "H9102|2026-11-20", "for_trip": "H9102", "pairing": "H9205", "start": "21Nov", "end": "23Nov",
          "dates": "21Nov-23Nov", "days": "3", "layover": "SFO", "turn": "", "credit": "16:30", "soft": "2:10", "src": "O",
          "soft_gain": "+1:05", "credit_gain": "+0:40", "why": "more soft time", "grid_ok": True, "grid": "grid OK"},
         {"for": "H9102|2026-11-20", "for_trip": "H9102", "pairing": "H9206", "start": "20Nov", "end": "20Nov",
          "dates": "20Nov", "days": "1", "layover": "-none-", "turn": "PPG", "credit": "9:00", "soft": "1:30", "src": "T",
          "soft_gain": "+0:35", "credit_gain": "-1:10", "why": "more soft time", "grid_ok": False, "grid": "grid red 11-21"}]


def _pot_states(marks=("H9102|2026-11-20",), ideas=IDEAS):
    return _pilot({"sensor.flight_watcher_pot_count": _s("2", {"pairings": POT}),
                   "sensor.flight_watcher_tradeboard_pickups": _s("1", {"pairings": TB}),
                   "sensor.flight_watcher_last_check": _s("2026-11-10T11:29:00+00:00"),
                   "sensor.flight_watcher_state": _s("hunting", {"role": "pilot", "doh": "2016-03-02"}),
                   "input_number.flight_watcher_longevity_year": _s("5"),
                   "sensor.flight_watcher_swap_ideas": _s(str(len(ideas)), {"count": len(ideas), "ideas": list(ideas),
                                                                            "marked": list(marks)}),
                   "sensor.flight_watcher_would_trade": _s(str(len(marks)), {"count": len(marks), "keys": list(marks)})})


SWAP_JS = """(st) => { const c = mount('flight-watcher-pot-card-pilot2', {}, st); const r = c.shadowRoot;
  const vis = (e) => e.checkVisibility();
  return {text: r.querySelector('.sw').innerText.replace(/\\s+/g, ' ').trim(), key: (r.querySelector('.sw details') || {}).textContent || '',
          heads: [...r.querySelectorAll('.swt th')].filter(vis).map((t) => t.textContent),
          rows: [...r.querySelectorAll('.swt tbody tr')].map((tr) => tr.innerText.replace(/\\s+/g, ' ').trim()),
          fit: fwFits(c)}; }"""


def test_pot_card_shows_the_swap_ideas_like_the_admins_table():
    with _browser() as b:
        none = _page(b, [_card("pot-card")]).evaluate(SWAP_JS, _pot_states(marks=(), ideas=()))
        watching = _page(b, [_card("pot-card")]).evaluate(SWAP_JS, _pot_states(ideas=()))
        narrow = _page(b, [_card("pot-card")]).evaluate(SWAP_JS, _pot_states())
        wide = _page(b, [_card("pot-card")], width=1100).evaluate(SWAP_JS, _pot_states())
    assert none["text"].startswith("Swap ideas No trips marked. On the Schedule tab, tap")
    assert watching["text"] == "Swap ideas Watching for better trips than H9102. Nothing better right now."
    assert wide["heads"] == ["Give up", "For", "Dates", "Layover", "Days", "Credit", "Soft", "Gain", "Src", "Grid"]
    assert wide["rows"] == ["H9102 H9205 21Nov-23Nov SFO 3 16:30 2:10 +1:05 soft, +0:40 cr Open time OK",
                            "H9102 H9206 20Nov PPG turn 1 9:00 1:30 +0:35 soft, -1:10 cr Tradeboard red 11-21"]  # review r4: not "Grid grid red"
    assert narrow["heads"] == [] and narrow["rows"] == wide["rows"]  # folded, the same cells
    assert narrow["fit"]["page"] <= 390 and narrow["fit"]["inner"] <= 0
    assert "Swap ideas 2" in wide["text"] and "nothing is filed from here" in wide["key"] and "PWA 10.E.1.a" in wide["key"]


# ---------------------------------------------------------------- F#93 / F#155: the settings card
def _settings_states(pub, **over):
    a = {"instance": "pilot2", "username": "doej", "my_name": "Doe", "ctweb_username": "doej", "has_password": True,
         "has_ctweb_password": True, "at": "2026-11-10T11:00:00+00:00", "result": "", "doh": "2016-03-02",
         "ntfy": True, "has_ntfy_topic": True, "has_ntfy_token": False, "ntfy_topic_ok": True, **pub, **over}
    return _pilot({"sensor.flight_watcher_settings": _s("ok", a), "sensor.flight_watcher_state": _s("idle", {"role": "pilot"}),
                   "sensor.flight_watcher_charters": _s("0", {"status": "CrewTrac refused your user ID or password at "
                                                                 "01:29 HST.", "crewtrac": {"state": "refused"}})})


def _sent(pg):
    return pg.evaluate(f"window.calls.filter((c) => c[2].topic === '{P}/settings/set').map((c) => JSON.parse(c[2].payload))")


def test_settings_card_secret_fields_show_and_send_exactly_as_typed(tmp_path):
    key = SEAL.load_key(str(tmp_path / "k.pem"))
    pub = SEAL.public_info(key)
    with _browser() as b:
        pg = _page(b, [_card("settings-card")])
        pg.evaluate("(st) => { window.C = mount('flight-watcher-settings-card-pilot2', {}, st); }", _settings_states(pub))
        r = "C.shadowRoot"
        info = pg.evaluate(f"""[...{r}.querySelectorAll('input[data-secret]')].map((i) => [i.dataset.k, i.type,
            i.getAttribute('autocomplete'), !!{r}.querySelector(`button[data-eye="${{i.dataset.k}}"]`)])""")
        assert info == [["password", "password", "off", True], ["ctweb_password", "password", "off", True],
                        ["ntfy_token", "password", "off", True]]
        assert pg.evaluate(f"{r}.innerHTML.includes('new-password')") is False
        card = pg.locator("flight-watcher-settings-card-pilot2")
        card.locator('input[data-k="password"]').fill(" pw 1 ")
        eye = card.locator('button[data-eye="password"]')
        eye.click()
        assert pg.evaluate(f"[{r}.querySelector('input[data-k=password]').type, {r}.querySelector('button[data-eye=password]')"
                           f".textContent, {r}.querySelector('button[data-eye=password]').getAttribute('aria-pressed')]") == [
            "text", "Hide", "true"]
        card.locator("#save").click()
        pg.wait_for_function("window.calls.length === 1")
        sent = _sent(pg)
        assert SEAL.open_sealed(key, sent[0]["enc"], now=NOW_TS) == {"password": " pw 1 "}  # shown as text, still not trimmed
        assert pg.evaluate(f"[...{r}.querySelectorAll('input[data-secret]')].map((i) => i.type + ':' + i.value)") == [
            "password:", "password:", "password:"]
        assert pg.evaluate(f"{r}.querySelector('button[data-eye=password]').textContent") == "Show"
        # the Watcher answers "nothing new": no change, in the text color, never the green of a save
        pg.evaluate("(st) => { C.hass = mkHass(st); }",
                    _settings_states(pub, at="2026-11-10T11:31:00+00:00", result="nothing new"))
        msg = pg.evaluate(f"(() => {{ const s = {r}.querySelector('#msg span'); return [s.className, s.textContent, "
                          f"getComputedStyle(s).color, getComputedStyle({r}.querySelector('ha-card')).color]; }})()")
        assert msg[:2] == ["nn", "No change: what you entered is already saved"] and msg[2] == msg[3]


def test_settings_card_removes_the_crewtrac_login_sealed_after_a_confirm(tmp_path):
    key = SEAL.load_key(str(tmp_path / "k.pem"))
    pub = SEAL.public_info(key)
    with _browser() as b:
        pg = _page(b, [_card("settings-card")])
        pg.evaluate("(st) => { window.C = mount('flight-watcher-settings-card-pilot2', {}, st); }", _settings_states(pub))
        card = pg.locator("flight-watcher-settings-card-pilot2")
        rm = card.locator("#ctoff")
        assert rm.inner_text() == "Remove CrewTrac login" and rm.bounding_box()["height"] >= 44
        dialogs = []
        pg.once("dialog", lambda d: (dialogs.append(d.message), d.dismiss()))
        rm.click()
        pg.wait_for_timeout(50)
        assert dialogs and "Remove the CrewTrac login saved on your Watcher?" in dialogs[0] and _sent(pg) == []
        pg.once("dialog", lambda d: d.accept())
        rm.click()
        pg.wait_for_function("window.calls.length === 1")
        sent = _sent(pg)
        assert list(sent[0]) == ["enc"] and SEAL.open_sealed(key, sent[0]["enc"], now=NOW_TS) == {"ctweb_off": True}
        assert pg.evaluate("C.shadowRoot.querySelector('#msg').textContent") == "Sent. Waiting for the Watcher to confirm..."
        # removed (the core's "saved: CrewTrac login removed"): green, and no button with nothing saved
        pg.evaluate("(st) => { C.hass = mkHass(st); }",
                    _settings_states(pub, ctweb_username="", has_ctweb_password=False, at="2026-11-10T11:32:00+00:00",
                                     result="saved: CrewTrac login removed"))
        assert pg.evaluate("C.shadowRoot.querySelector('#ctoff')") is None
        assert pg.evaluate("[C.shadowRoot.querySelector('#msg span').className, C.shadowRoot.querySelector('#msg')"
                           ".textContent]") == ["ok", "saved: CrewTrac login removed"]
        # the Watcher had none to remove: its own reason, in the neutral color
        pg.evaluate("(st) => { C.hass = mkHass(st); C._sentAt = '2026-11-10T11:32:00+00:00'; C.hass = mkHass(st); }",
                    _settings_states(pub, ctweb_username="", has_ctweb_password=False, at="2026-11-10T11:33:00+00:00",
                                     result="nothing new: no CrewTrac login is saved"))
        assert pg.evaluate("[C.shadowRoot.querySelector('#msg span').className, C.shadowRoot.querySelector('#msg')"
                           ".textContent]") == ["nn", "No change: no CrewTrac login is saved"]
    # the admin's own instance (instance ""): the card never offers it (his logins may be the add-on's options)
    with _browser() as b:
        pg = _page(b, [_card("settings-card", pilot=False)])
        admin = {"sensor.flight_watcher_settings": _settings_states(pub, instance="", ntfy=False)[f"sensor.{P}_settings"]}
        pg.evaluate("(st) => { window.C = mount('flight-watcher-settings-card', {}, st); }", admin)
        assert pg.evaluate("[!!C.shadowRoot.querySelector('#ctoff'), C.shadowRoot.querySelectorAll('button[data-eye]').length]") == [
            False, 2]


# ---------------------------------------------------------------- F#119 and the renders: every changed card
def _sched_states(prefs=True):
    st = _read(prefs=prefs, doh="2016-03-02" if prefs else "")
    mon = st["sensor.flight_watcher_schedule"]["attributes"]["months"]["2026-11"]
    days = [list(d) for d in _award()["days"]]
    days[19], days[20], days[21] = ["2026-11-20", "H9102", "LAX"], ["2026-11-21", "", "LAX"], ["2026-11-22", "", "HNL"]
    mon["days"] = days
    mon["items"] = _award()["items"] + [{"trip": "H9102", "start": "2026-11-20", "end": "2026-11-22", "lay": "LAX"}]
    if not prefs:
        st["sensor.flight_watcher_schedule"]["attributes"]["read_status"] = FAILED
    st["sensor.flight_watcher_reserve_grid"] = _s("3", {"days": {"2026-11-03": {"color": "green", "net": 4},
                                                                 "2026-11-20": {"color": "red", "net": -1},
                                                                 "2026-11-21": {"color": "green", "net": 2},
                                                                 "2026-11-12": {"color": "black", "net": 0}}})
    st["sensor.flight_watcher_would_trade"] = _s("1", {"keys": ["H9102|2026-11-20"]})
    st["sensor.flight_watcher_swap_ideas"] = _s("2", {"ideas": IDEAS})
    st["sensor.flight_watcher_pot_count"] = _s("2", {"pairings": POT})
    return _pilot(st)


def _clock_err():
    return _clock_states(last="2026-11-10T09:30:00+00:00", hunt="on")  # 2 h without a check: Stuck, hunt on


RENDERS = {  # name: (card, config, states, js run on the card after the mount)
    "clock": ("clock-card", {}, _clock_states, ""),
    "clock stuck": ("clock-card", {}, _clock_err, ""),
    "settings": ("settings-card", {}, lambda: _settings_states({"pubkey": "", "kid": ""}),
                 "c.shadowRoot.getElementById('msg').innerHTML = '<span class=\"err\">Not sent: x</span> "
                 "<span class=\"ok\">Sent.</span> <span class=\"nn\">No change</span>';"),
    "schedule": ("schedule-card", {}, _sched_states, ""),
    "schedule unset": ("schedule-card", {}, lambda: _sched_states(prefs=False), ""),
    "pot": ("pot-card", {}, _pot_states, ""),
    "pickers": ("pickers-card", {"open": True}, lambda: {f"sensor.{P}_pickers": _s("3", {"pickers": PICKERS})}, ""),
    "pilot search": ("pilot-search-card", {}, lambda: _pilot({"sensor.flight_watcher_state": _s("idle", {"role": "pilot"})}), ""),
    "recall": ("recall-card", {}, _recall_states,
               "c._note = 'No answer from the Watcher yet. Is it running?'; c._sig = null; c.hass = c._h;"),
    "recall alert": ("recall-card", {"mode": "alert"}, _recall_states, ""),
}


@pytest.mark.parametrize("width,scheme", [(390, "light"), (390, "dark"), (1100, "light"), (1100, "dark")])
def test_changed_cards_read_at_390_and_1100_px_in_light_and_dark(width, scheme):
    """F#119: text contrast computed from the rendered colors, WCAG AA (4.5:1, 3:1 for large text), on the portal's
    light and dark cards; at 390 px no card is wider than the screen. The portal's own primary button pair (white on its
    dark-mode primary blue, 3.02:1) is HOM's palette and listed apart."""
    bad, wide = {}, {}
    with _browser() as b:
        for name, (card, cfg, states, after) in RENDERS.items():
            pg = _page(b, [_card(card)], width=width, scheme=scheme)
            got = pg.evaluate("([tag, cfg, st, after]) => { const c = mount(tag, cfg, st); if (after) new Function('c', after)(c);"
                              " return new Promise((ok) => setTimeout(() => ok({con: fwContrast(c), fit: fwFits(c)}), 80)); }",
                              [f"flight-watcher-{card}-pilot2", cfg, states(), after])
            if SHOTS:
                pg.screenshot(path=os.path.join(SHOTS, f"{name.replace(' ', '_')}_{width}_{scheme}.png"), full_page=True)
            assert got["con"]["n"] > 0, name
            if got["con"]["fails"]:
                bad[name] = got["con"]["fails"]
            if width == 390 and (got["fit"]["page"] > 390 or got["fit"]["right"] > 390):
                wide[name] = got["fit"]
            pg.context.close()
    assert not bad, json.dumps(bad, indent=1)
    assert not wide, wide


# ---------------------------------------------------------------- 1.7.1 review: no iOS zoom on a tapped field
FIELDS_JS = """([tag, cfg, st, after]) => { const c = mount(tag, cfg, st); if (after) new Function('c', after)(c);
  return new Promise((ok) => setTimeout(() => { const out = [];
    const walk = (root) => { for (const e of root.querySelectorAll('input,select,textarea')) {
        if (e.matches('[type=checkbox],[type=radio],[type=hidden],[type=button],[type=submit]')) continue;
        if (!e.checkVisibility({ checkVisibilityCSS: true })) continue;
        const name = e.tagName.toLowerCase() + ':' + (e.dataset.k || e.id || e.type || '');
        out.push([name, getComputedStyle(e).fontSize]); }
      for (const e of root.querySelectorAll('*')) if (e.shadowRoot) walk(e.shadowRoot); };
    walk(c.shadowRoot); ok(out); }, 80)); }"""


def test_every_field_on_the_changed_cards_is_16_px_on_a_phone():
    """iOS Safari zooms into a field or select under 16 px when it is tapped, and the portal page (width=device-width,
    no maximum-scale) then stays wider than the screen: at 390 px every visible text field, select and text area of
    the changed cards is 16 px or more (F#43 did it for the pilot lookup)."""
    small, seen = {}, {}
    with _browser() as b:
        for name, (card, cfg, states, after) in RENDERS.items():
            pg = _page(b, [_card(card)], width=390)
            got = pg.evaluate(FIELDS_JS, [f"flight-watcher-{card}-pilot2", cfg, states(), after])
            pg.context.close()
            seen[name] = len(got)
            bad = [f for f in got if float(f[1][:-2]) < 16]
            if bad:
                small[name] = bad
    assert not small, small
    for name in ("clock", "settings", "schedule unset", "pickers", "pilot search", "recall"):
        assert seen[name] > 0, name  # each of these cards has fields to check
