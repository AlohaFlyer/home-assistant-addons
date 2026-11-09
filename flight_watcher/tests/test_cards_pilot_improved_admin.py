"""Cards: FW-0025 (one pilot lookup publishes once), FW-0047 (Improved-Pay Gross / Net tick box), FW-0048 (auto drop
mark for the HA owner on the admin Watcher only since FW-0063). Synthetic data and made-up names only."""
import json
import os
import shutil
import subprocess

import pytest

import cards
from test_cards import _chromium

WWW = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "www")


def _src(name):
    return open(os.path.join(WWW, name), encoding="utf-8").read()


def _node(tmp_path, js):
    if not shutil.which("node"):
        pytest.skip("node not installed")
    f = tmp_path / "t.js"
    f.write_text(js)
    out = subprocess.run(["node", str(f)], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


# a browser-ish window for node: a real EventTarget (add / remove / dispatch), a location with a hash, a fake clock
_DOM = ("globalThis.HTMLElement = class {}; globalThis.customElements = {define() {}};\n"
        "globalThis.window = new EventTarget();\n"
        "globalThis.location = {hash: '', pathname: '/flight-watcher/watcher', search: ''};\n"
        "globalThis.history = {replaceState(a, b, url) { location.hash = ''; }};\n"
        "let clock = 1790000000000; Date.now = () => clock;\n")


def test_pilot_card_one_lookup_publishes_once(tmp_path):
    """FW-0025: setConfig ran again and again (HA re-sends the config) and each call added a window listener that was
    never removed, so one tap published 2 to 4 times. Now: one listener per card while it is on the page, and one
    lookup publishes once however many cards hear it; a #pilot= link waits for a card to be on the page."""
    js = _DOM + _src("flight-watcher-pilot-card.js") + r"""
const sent = [];
const mk = (name) => { const c = new FlightWatcherPilotCard(); c.setConfig({}); c.setConfig({}); c.setConfig({ entity: "sensor.x" });
  c._paint = () => {}; c.scrollIntoView = () => {}; c.name = name;
  c._h = { callService: (d, s, data) => sent.push([name, d, s, data.topic, JSON.parse(data.payload)]) }; return c; };
const ask = (detail) => window.dispatchEvent(new CustomEvent("flight-watcher-pilot", { detail }));
const r = {};
const a = mk("a");
ask({ emp: "10001" }); r.offPage = sent.length;                 // not on the page yet: not listening
a.connectedCallback(); a.connectedCallback();                   // HA can connect twice: still one listener
ask({ emp: "10002", name: "Doe, Jane" }); r.one = sent.length;
const b = mk("b"); b.connectedCallback();                       // a second card (editor preview, stale copy)
ask({ q: "Doe" }); r.two = sent.length; r.bothWant = [a._want, b._want];
ask({ q: "Doe" }); r.doubleTap = sent.length;                   // the same lookup again at once: one tap heard twice
clock += 2500; ask({ q: "Doe" }); r.later = sent.length;        // 2.5 s later it is a new request
ask({ emp: "10003" }); r.other = sent.length;                   // a different pilot goes at once
a.disconnectedCallback(); a.disconnectedCallback(); b.disconnectedCallback();
clock += 5000; ask({ emp: "10004" }); r.gone = sent.length;     // both cards off the page: nobody listens
// a #pilot= link with no card on the page keeps its hash; the card picks it up when it connects
location.hash = "#pilot=10005,Doe%2C%20Jane"; window.dispatchEvent(new Event("hashchange")); r.waiting = [sent.length, location.hash];
a.connectedCallback(); r.deep = [sent.length, location.hash, sent[sent.length - 1][4]];
clock += 5000; location.hash = "#pilot=10006"; window.dispatchEvent(new Event("hashchange"));
window.dispatchEvent(new Event("popstate")); window.dispatchEvent(new Event("location-changed")); r.link = sent.length;
clock += 5000; location.hash = "#pilot=10007,%E0%A4%A"; window.dispatchEvent(new Event("hashchange")); r.bad = sent[sent.length - 1][4];
r.topics = [...new Set(sent.map((x) => x.slice(1, 4).join(" ")))];
r.payloads = sent.map((x) => x[4]);
r.live = FlightWatcherPilotCard._live;
console.log(JSON.stringify(r));
"""
    r = _node(tmp_path, js)
    assert r["offPage"] == 0
    assert r["one"] == 1 and r["two"] == 2 and r["bothWant"] == ["Doe", "Doe"]  # both cards redraw, one publishes
    assert r["doubleTap"] == 2 and r["later"] == 3 and r["other"] == 4
    assert r["gone"] == 4
    assert r["waiting"] == [4, "#pilot=10005,Doe%2C%20Jane"]
    assert r["deep"] == [5, "", {"emp": "10005", "name": "Doe, Jane"}]
    assert r["link"] == 6  # hashchange, popstate and location-changed for one link: one lookup
    assert r["bad"] == {"emp": "10007", "name": "%E0%A4%A"}  # a stray % does not throw
    assert r["topics"] == ["mqtt publish flight_watcher/pilot/set"]
    assert r["payloads"][:4] == [{"emp": "10002", "name": "Doe, Jane"}, {"q": "Doe"}, {"q": "Doe"}, {"emp": "10003"}]
    assert r["live"] == 1
    # a second pilot's copy listens to its own event and publishes on its own topic
    p2 = cards.build("1", ["pilot2"])["flight-watcher-pilot-card-pilot2.js"]
    assert 'PILOT_EV = "flight-watcher-pilot-pilot2"' in p2 and '"flight_watcher_pilot2/pilot/set"' in p2
    assert '"flight-watcher-pilot"' not in p2 and '"flight_watcher/pilot/set"' not in p2


def test_pilot_card_double_tap_after_a_quick_reply_draws_the_reply(tmp_path):
    """FW-0025: a lookup the Watcher already answered (a cache hit, a pick list, 'no pilot named') and asked again,
    as a double tap (dropped) or later (published), ends on that reply, not on the loading line: HA fires no state
    change for an identical reply, so the loading line would stay forever. A new pilot still shows loading."""
    js = _DOM + _src("flight-watcher-pilot-card.js") + r"""
const sent = [], paints = [];
const E = "sensor.flight_watcher_pilot_schedule";
let S = { [E]: { last_updated: "t0", attributes: {} } };
const c = new FlightWatcherPilotCard(); c.setConfig({}); c.scrollIntoView = () => {};
c._paint = (l) => paints.push(l ? "loading" : "reply"); c._root = {};  // as if drawn once
const hass = () => ({ states: S, callService: (d, s, data) => sent.push(JSON.parse(data.payload)) });
c.hass = hass(); c.connectedCallback();
const ask = (detail) => { window.dispatchEvent(new CustomEvent("flight-watcher-pilot", { detail })); return [sent.length, paints[paints.length - 1]]; };
const reply = (attrs) => { S = { [E]: { last_updated: "t" + clock, attributes: attrs } }; c.hass = hass(); clock += 1; return paints[paints.length - 1]; };
const r = {};
r.first = ask({ emp: "10002", name: "Doe, Jane" });
r.cached = reply({ emp: "10002", name: "Doe, Jane", status: "cached", month: "2026-11" });
clock += 300; r.dbl = ask({ emp: "10002", name: "Doe, Jane" });       // a double tap after the cached reply: dropped
const n = paints.length; c.hass = hass(); r.idle = paints.length - n;  // HA re-sends hass, nothing changed: no redraw
clock += 3000; r.again = ask({ emp: "10002", name: "Doe, Jane" });    // the same pilot later: asks, draws what it has
r.digits = ask({ q: "10002" });                                      // an all-digit lookup is that employee number
r.other = ask({ emp: "10003" });                                     // another pilot: loading till the reply
r.loading = reply({ emp: "10003", name: "", status: "loading", month: "" });
// a name with one match: loading, then the reply teaches the card which pilot the name found
clock += 3000; r.name = ask({ q: "Doe" });
r.nameReply = reply({ emp: "10008", name: "Doe, John", status: "cached", month: "2026-11" });
clock += 300; r.nameDbl = ask({ q: "Doe" });
clock += 3000; r.nameAgain = ask({ q: " doe " });
// a name with several matches (the pick list), and one nobody has
clock += 3000; r.many = ask({ q: "Roe" });
reply({ emp: "", name: "Roe", status: "2 pilots match 'Roe', pick one", matches: [{ emp: "10010", name: "Roe, Ann" }], month: "" });
clock += 300; r.manyDbl = ask({ q: "Roe" });
clock += 3000; r.none = ask({ q: "Poe" });
reply({ emp: "", name: "Poe", status: "no pilot named 'Poe' in the 9 crew the Watcher has seen; enter the employee number", month: "" });
clock += 300; r.noneDbl = ask({ q: "Poe" });
r.otherName = ask({ q: "Moe" });                                     // a different name: loading
r.qEmp = FlightWatcherPilotCard._qEmp;
r.sent = sent;
console.log(JSON.stringify(r));
"""
    r = _node(tmp_path, js)
    assert r["first"] == [1, "loading"] and r["cached"] == "reply"
    assert r["dbl"] == [1, "reply"]  # the old code stayed on "reading this pilot's month from FLICA, 20 to 40 s"
    assert r["idle"] == 0
    assert r["again"] == [2, "reply"] and r["digits"] == [3, "reply"]
    assert r["other"] == [4, "loading"] and r["loading"] == "reply"  # the card draws the Watcher's own loading status
    assert r["name"] == [5, "loading"] and r["nameReply"] == "reply"
    assert r["nameDbl"] == [5, "reply"] and r["nameAgain"] == [6, "reply"]
    assert r["qEmp"] == {"doe": "10008"}
    assert r["many"] == [7, "loading"] and r["manyDbl"] == [7, "reply"]
    assert r["none"] == [8, "loading"] and r["noneDbl"] == [8, "reply"]
    assert r["otherName"] == [9, "loading"]
    assert r["sent"][:3] == [{"emp": "10002", "name": "Doe, Jane"}] * 2 + [{"q": "10002"}]


def test_pilot_search_card_asks_once_per_press(tmp_path):
    """FW-0025: Go and Enter both ask; a double tap on Go, a held Enter (auto-repeat) or an IME confirm does not ask
    again. Another name, or the same one 2 s later, asks."""
    js = _DOM + _src("flight-watcher-pilot-search-card.js") + r"""
const asks = []; window.addEventListener("flight-watcher-pilot", (e) => asks.push(e.detail));
const el = () => { const l = {}; return { value: "", addEventListener: (t, f) => { l[t] = f; }, fire: (t, e) => l[t](e) }; };
const input = el(), button = el();
const root = { set innerHTML(v) {}, querySelector: (s) => (s === "input" ? input : button) };
const c = new FlightWatcherPilotSearchCard(); c.attachShadow = () => root; c.setConfig({}); c.hass = {}; c.hass = {};
const key = (k, more) => { let stopped = false; input.fire("keydown", { key: k, repeat: false, isComposing: false, stopPropagation: () => { stopped = true; }, ...more }); return stopped; };
const r = {};
input.value = "  "; button.fire("click"); r.blank = asks.length;
input.value = " Doe "; button.fire("click"); button.fire("click"); r.dbl = asks.length;
clock += 300; r.stop = key("Enter"); r.enterSoon = asks.length;   // Enter right after Go: the same press
clock += 2500; key("Enter"); key("Enter", { repeat: true }); key("Enter", { repeat: true }); r.held = asks.length;
clock += 2500; key("Enter", { isComposing: true }); r.ime = asks.length;
key("a"); r.letter = asks.length;
input.value = "Roe"; key("Enter"); r.other = asks.length;
console.log(JSON.stringify({ ...r, asks }));
"""
    r = _node(tmp_path, js)
    assert r["blank"] == 0 and r["dbl"] == 1 and r["enterSoon"] == 1 and r["stop"] is True
    assert r["held"] == 2 and r["ime"] == 2 and r["letter"] == 2 and r["other"] == 3
    assert r["asks"] == [{"q": "Doe"}, {"q": "Doe"}, {"q": "Roe"}]


def _improved_js(body):
    return ("globalThis.HTMLElement = class {}; globalThis.customElements = {define() {}}; globalThis.window = {};\n"
            "const store = new Map(); globalThis.localStorage = {getItem: (k) => store.has(k) ? store.get(k) : null,"
            " setItem: (k, v) => store.set(k, String(v))};\n" + _src("flight-watcher-improved-card.js") + "\n" + body)


_MONTHS = [{"month": "2026-10", "awarded": 20000, "current": 21000, "improved": 1000, "ver": "10.003", "awarded_ver": "10.001"},
           {"month": "2026-11", "awarded": 24000, "current": 26500, "improved": 2500, "ver": "11.004", "awarded_ver": "11.001"}]


def test_improved_card_net_tick_box(tmp_path):
    """FW-0047: Gross by default; ticking Net prices every bar, the title, the total and the tooltip as the schedule
    card's Pay-Net (gross x (1 - (federal + state) / 100), 22 / 0 while a helper has no number); the choice is kept
    per browser (localStorage, which may throw); a tax change redraws."""
    js = _improved_js(r"""
const months = %s;
const st = (fed, stt, lu) => ({ "sensor.flight_watcher_improved_pay_gross": { last_updated: "S1", attributes: { months } },
  ...(fed == null ? {} : { "input_number.flight_watcher_federal_tax_pct": { state: fed, last_updated: "F" + lu } }),
  ...(stt == null ? {} : { "input_number.flight_watcher_state_tax_pct": { state: stt, last_updated: "T" + lu } }) });
const mk = () => { const c = new FlightWatcherImprovedCard(); c.setConfig({}); c.draws = 0; c._render = () => { c.draws++; c.html = c._html(); }; return c; };
const pick = (h) => ({ title: (h.match(/<h3>([^<]*)<\/h3>/) || [])[1], total: (h.match(/<div class="k">([^]*?)<\/div>/) || [])[1],
  labels: [...h.matchAll(/class="lb"[^>]*>([^<]*)</g)].map((m) => m[1]), tip: (h.match(/<title>(Nov[^<]*)<\/title>/) || [])[1],
  box: (h.match(/<input type="checkbox" data-net[^>]*>/) || [])[0] });
const r = {};
const c = mk(); c.hass = { states: st("24.0", "6.0", 1) }; r.gross = pick(c.html); r.k = c._tax();
c._setNet(true); r.net = pick(c.html); r.saved = store.get("flight_watcher_improved_net");
c.hass = { states: st("24.0", "6.0", 1) }; r.sameDraws = c.draws;            // nothing changed: no redraw
c.hass = { states: st("10", "0", 2) }; r.taxed = pick(c.html); r.taxDraws = c.draws;
const d = mk(); d.hass = { states: st(null, null, 3) }; r.reload = pick(d.html); r.def = d._tax();   // a new page reads the choice
const bad = mk(); bad.hass = { states: st("unknown", "", 4) }; r.unknown = bad._tax();
d._setNet(false); r.back = [store.get("flight_watcher_improved_net"), pick(d.html).title];
const e = mk(); e.hass = { states: { "sensor.flight_watcher_improved_pay_gross": { last_updated: "x", attributes: {} } } };
e._setNet(true); r.empty = pick(e.html);
globalThis.localStorage = { getItem() { throw new Error("blocked"); }, setItem() { throw new Error("blocked"); } };
const p = mk(); p.hass = { states: st("24", "6", 5) }; r.blocked = pick(p.html).title; p._setNet(true); r.blockedNet = pick(p.html).title;
console.log(JSON.stringify(r));
""" % json.dumps(_MONTHS))
    r = _node(tmp_path, js)
    g, n = r["gross"], r["net"]
    assert g["title"] == "Improved-Pay-Gross by month" and "checked" not in g["box"]
    assert g["labels"] == ["$1,000", "$2,500"] and "<b>$3,500</b> over 2 months" in g["total"] and "tax" not in g["total"]
    assert g["tip"] == "Nov 2026: Improved-Pay-Gross $2,500 (awarded $24,000 v11.001, now $26,500 v11.004)"
    assert r["k"] == {"fed": 24, "stt": 6}
    # 24 %% + 6 %% = 30 %%: net = gross x 0.70
    assert n["title"] == "Improved-Pay-Net by month" and "checked" in n["box"] and r["saved"] == "1"
    assert n["labels"] == ["$700", "$1,750"] and "Total improved (net): <b>$2,450</b> over 2 months" in n["total"]
    assert "less 24% federal and 6% state tax" in n["total"]
    assert n["tip"] == "Nov 2026: Improved-Pay-Net $1,750 (awarded $16,800 v11.001, now $18,550 v11.004)"
    assert r["sameDraws"] == 2 and r["taxDraws"] == 3  # first draw + the tick; then only the tax change
    assert r["taxed"]["labels"] == ["$900", "$2,250"] and "<b>$3,150</b>" in r["taxed"]["total"]
    # a new card (page reload) opens on Net; helpers missing: the schedule card's defaults 22 / 0
    assert r["reload"]["title"] == "Improved-Pay-Net by month" and r["def"] == {"fed": 22, "stt": 0}
    assert r["reload"]["labels"] == ["$780", "$1,950"]
    assert r["unknown"] == {"fed": 22, "stt": 0}
    assert r["back"] == ["0", "Improved-Pay-Gross by month"]
    assert r["empty"]["title"] == "Improved-Pay-Net by month" and "checked" in r["empty"]["box"]
    # storage blocked (private mode): Gross, and the tick still works for this page
    assert r["blocked"] == "Improved-Pay-Gross by month" and r["blockedNet"] == "Improved-Pay-Net by month"
    p2 = cards.build("1", ["pilot2"])["flight-watcher-improved-card-pilot2.js"]
    assert '"flight_watcher_pilot2_improved_net"' in p2 and "input_number.flight_watcher_pilot2_federal_tax_pct" in p2
    assert "input_number.flight_watcher_pilot2_state_tax_pct" in p2 and "input_number.flight_watcher_federal" not in p2


def test_improved_card_net_matches_schedule_card_pay_net():
    """FW-0047: the improved card's Net is the schedule card's Pay-Net formula and defaults, word for word."""
    sch, imp = _src("flight-watcher-schedule-card.js"), _src("flight-watcher-improved-card.js")
    assert 'const num = (e, d) => { const v = parseFloat((S[e] || {}).state); return isNaN(v) ? d : v; };' in sch
    assert 'const num = (e, d) => { const v = parseFloat((S[e] || {}).state); return isNaN(v) ? d : v; };' in imp
    assert 'const fed = num("input_number.flight_watcher_federal_tax_pct", 22), stt = num("input_number.flight_watcher_state_tax_pct", 0);' in sch
    assert "return { fed: num(IMP_FED, 22), stt: num(IMP_STT, 0) };" in imp
    assert "total * (1 - (fed + stt) / 100)" in sch and "1 - (fed + stt) / 100" in imp


def _sched_states(who, role=None):
    """Synthetic November: a trip that starts after 'today' (Nov 6 HST), one in the past, a VAC day. role: the
    Watcher's role in sensor.flight_watcher_state (None: no state sensor yet)."""
    days = [[f"2026-11-{d:02d}", "", ""] for d in range(1, 31)]
    days[2] = ["2026-11-03", "H9001", "LAX"]
    days[3] = ["2026-11-04", "", "HNL"]
    days[11] = ["2026-11-12", "H9002", "SEA"]
    days[12] = ["2026-11-13", "", "HNL"]
    days[19] = ["2026-11-20", "VAC", ""]
    items = [{"trip": "H9001", "start": "2026-11-03", "end": "2026-11-04", "blk": "10:00", "credit": "12:00"},
             {"trip": "H9002", "start": "2026-11-12", "end": "2026-11-13", "blk": "11:00", "credit": "12:30"},
             {"trip": "VAC", "start": "2026-11-20", "end": "2026-11-20"}]
    st = {"sensor.flight_watcher_schedule": {"last_updated": "a", "attributes": {"months": {"2026-11": {
              "days": days, "items": items, "totals": {"block": "21:00", "credit": "24:30", "days_off": 25}, "updated": "Nov 6"}}}},
          "input_number.flight_watcher_month_offset": {"state": "0", "last_updated": "a"},
          "sensor.flight_watcher_would_drop": {"last_updated": "a", "attributes": {"keys": ["H9002|2026-11-12"], "ready": {}}},
          "sensor.flight_watcher_would_trade": {"last_updated": "a", "attributes": {"keys": []}},
          "input_number.flight_watcher_federal_tax_pct": {"state": "22", "last_updated": "a"},
          "input_number.flight_watcher_state_tax_pct": {"state": "0", "last_updated": "a"}}
    if role is not None:
        st["sensor.flight_watcher_state"] = {"state": "idle", "last_updated": "a", "attributes": {"role": role}}
    h = {"states": st}
    if who is not None:  # HA's hass.user: the owner is always an admin too; HA has exactly one owner
        h["user"] = {"name": "Doe, Jane", "is_owner": who == "owner", "is_admin": who in ("owner", "admin")}
    return h


def test_schedule_card_drop_mark_for_the_owner_on_the_admin_role_only():
    """FW-0048 (Ryan), FW-0063 (1.5.0): the auto drop mark (it composes a drop request) shows only for the HA owner
    (Ryan) AND only on the admin Watcher's card (sensor.flight_watcher_state role "admin"). Another admin login (Pako
    has one), a plain user or a hass without a user yet keeps the read-only parts and the trade mark on Ryan's card,
    as in 1.4.12; a pilot's Watcher (role "pilot") or a state sensor not there yet never shows it, even to the owner.
    The owner arriving later, or the role arriving later, redraws."""
    sync_api = pytest.importorskip("playwright.sync_api")
    page_html = ("<!doctype html><html><body><script>customElements.define('ha-card', class extends HTMLElement {});"
                 "window.calls = [];</script><script>" + _src("flight-watcher-schedule-card.js") + "</script></body></html>")
    with sync_api.sync_playwright() as p:
        b = _chromium(p)
        if not b:
            pytest.skip("no Chromium for Playwright")
        try:
            pg = b.new_page(viewport={"width": 1100, "height": 900})
            pg.clock.set_fixed_time("2026-11-06T20:00:00Z")  # Nov 6 10:00 HST
            pg.set_content(page_html)
            pg.evaluate("() => { window.mk = (h) => { const c = document.createElement('flight-watcher-schedule-card'); c.setConfig({});"
                        " document.body.appendChild(c); c.hass = {...h, callService: async (d, s, data) => window.calls.push([d, s, data])}; }; }")
            look = ("(i) => { const r = document.querySelectorAll('flight-watcher-schedule-card')[i].shadowRoot;"
                    " return {drb: r.querySelectorAll('.drb').length, drbOn: r.querySelectorAll('.drb.on').length,"
                    " trb: r.querySelectorAll('.trb').length, lock: r.querySelector('.lock').title,"
                    " key: [...r.querySelectorAll('.lt td')].map((t) => t.textContent).find((t) => t.includes('The lock')) || ''}; }")
            cases = (("owner", "admin"), ("admin", "admin"), ("user", "admin"), (None, "admin"), ("owner", "pilot"),
                     ("admin", "pilot"), ("owner", None))
            for who, role in cases:
                pg.evaluate("(h) => { window.mk(h); }", _sched_states(who, role))
            got = [pg.evaluate(look, i) for i in range(len(cases))]
            owner = got[0]  # the HA owner on the admin Watcher's card: the drop mark
            assert owner["drb"] == 1 and owner["drbOn"] == 1 and owner["trb"] == 1  # H9002 (Nov 12); H9001 has started
            assert "availability, trade and drop marks" in owner["lock"] and "availability, trade and drop taps" in owner["key"]
            for (who, role), x in zip(cases[1:], got[1:]):  # anyone else, or a pilot's card: no drop mark
                assert x["drb"] == 0 and x["drbOn"] == 0 and x["trb"] == 1, (who, role)
                assert "availability and trade marks" in x["lock"] and "drop" not in x["lock"], (who, role)
                assert "availability and trade taps" in x["key"], (who, role)
            # a non-owner admin on Ryan's card unlocks and taps: only the trade mark publishes; no drop mark to tap
            r = "document.querySelectorAll('flight-watcher-schedule-card')[1].shadowRoot"
            pg.evaluate(f"{r}.querySelector('.lock').click()")
            pg.evaluate(f"{r}.querySelector('.trb').click()")
            assert pg.evaluate("window.calls.map((c) => c[2].topic)") == ["flight_watcher/trade/set"]
            # the same on the pilot card the HA owner opened
            r = "document.querySelectorAll('flight-watcher-schedule-card')[4].shadowRoot"
            pg.evaluate(f"{r}.querySelector('.lock').click()")
            pg.evaluate(f"{r}.querySelector('.trb').click()")
            assert pg.evaluate("window.calls.map((c) => c[2].topic)") == ["flight_watcher/trade/set"] * 2
            # the user (the owner) arrives after the first states on the admin Watcher's card: it redraws with the mark
            pg.evaluate("() => { const c = document.querySelectorAll('flight-watcher-schedule-card')[3];"
                        " c.hass = {...c._h, user: {name: 'Doe, Jane', is_owner: true, is_admin: true}}; }")
            assert pg.evaluate(look, 3)["drb"] == 1
            # the state sensor (role admin) arrives after the first states for the owner: it redraws with the mark
            pg.evaluate("() => { const c = document.querySelectorAll('flight-watcher-schedule-card')[6];"
                        " c.hass = {...c._h, states: {...c._h.states, 'sensor.flight_watcher_state':"
                        " {state: 'idle', last_updated: 'b', attributes: {role: 'admin'}}}}; }")
            assert pg.evaluate(look, 6)["drb"] == 1
        finally:
            b.close()


def test_improved_card_tick_box_in_a_browser():
    """FW-0047 in a real browser: the tick box flips the title and stays ticked after a reload of the card."""
    sync_api = pytest.importorskip("playwright.sync_api")
    page_html = ("<!doctype html><html><body><script>customElements.define('ha-card', class extends HTMLElement {});</script>"
                 "<script>" + _src("flight-watcher-improved-card.js") + "</script></body></html>")
    hass = {"states": {"sensor.flight_watcher_improved_pay_gross": {"last_updated": "a", "attributes": {"months": _MONTHS}},
                       "input_number.flight_watcher_federal_tax_pct": {"state": "22", "last_updated": "a"},
                       "input_number.flight_watcher_state_tax_pct": {"state": "0", "last_updated": "a"}}}
    with sync_api.sync_playwright() as p:
        b = _chromium(p)
        if not b:
            pytest.skip("no Chromium for Playwright")
        try:
            pg = b.new_page(viewport={"width": 390, "height": 700})
            pg.route("http://fw.test/", lambda route: route.fulfill(status=200, content_type="text/html", body=page_html))
            pg.goto("http://fw.test/")  # a real origin, so localStorage works
            mk = ("(h) => { document.body.innerHTML = ''; const c = document.createElement('flight-watcher-improved-card');"
                  " c.setConfig({}); document.body.appendChild(c); c.hass = h; }")
            pg.evaluate(mk, hass)
            card = pg.locator("flight-watcher-improved-card")
            assert card.locator("h3").inner_text() == "Improved-Pay-Gross by month"
            box = card.locator("input[data-net]")
            assert not box.is_checked()
            card.locator("label.nt").click()
            assert card.locator("h3").inner_text() == "Improved-Pay-Net by month" and box.is_checked()
            assert "$2,730" in card.locator(".k").inner_text()  # 3,500 x 0.78
            pg.reload()
            pg.evaluate(mk, hass)
            assert card.locator("h3").inner_text() == "Improved-Pay-Net by month"
            assert card.locator("input[data-net]").is_checked()
        finally:
            b.close()
