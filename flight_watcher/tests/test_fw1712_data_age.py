"""1.7.12 (Ryan, Nov 17, yes: "Replace the two clocks ("updated" and "Last check") with one "data age" stamp. Turn it
amber past 1x the normal interval and red past 2x."): the clock card's "Last" and the schedule card's "updated" give
way to one "Data age 12 min" stamp, the time since the Watcher's last good read (sensor.<prefix>_last_check, which a
check sets only when it succeeds). Amber past 1x the check interval (the normal one in minutes, the hunt one in seconds
while hunting), red past 2x, plain otherwise, with the word "stale" or "very stale" so the colour is never the only cue.
An unknown or missing read time is "Data age unknown", no colour. The Details view's "Last check" tile is the same stamp
(the clock card in age mode), FLICA's own schedule time stays in the schedule card's hover text ("FLICA updated ..."),
the stamp ticks by itself, and a pilot's portal copies show it from entities the portal already has. Synthetic states
only, rendered in Chromium at 390 px, light and dark."""
import hashlib
import json
import os
import re

import cards
import portal as PT
import roles
from test_fw171_cards import P, _browser, _card, _page as _portal_page, _pilot, _s
from test_fw171_r4_cards import HA_VARS_JS
from test_layover_card import HA_DARK, HA_LIGHT
from test_release_a_cards import _run, _src
from test_release_a_schedule_card import _read

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(HERE)
START = "// ---- shared data age: keep identical in every card that holds it (tests/test_fw1712_data_age.py) ----\n"
END = "// ---- end shared data age ----\n"
HOLDERS = ("flight-watcher-clock-card", "flight-watcher-schedule-card")
NOW = "2026-11-10T11:30:00Z"  # Nov 10 01:30 HST, the harnesses' clock
AMBER = {"light": "rgb(138, 83, 0)", "dark": "rgb(255, 183, 77)"}  # #8a5300 / #ffb74d
RED = {"light": "rgb(198, 40, 40)", "dark": "rgb(239, 154, 154)"}  # #c62828 / #ef9a9a
NORMAL_RULE = "Stale past 6 min, very stale past 12 min: 1x and 2x the normal check interval."


def block(text):
    if START not in text:
        return None
    i = text.index(START)
    return text[i:text.index(END, i) + len(END)]


# ---------------------------------------------------------------- the shared block
def test_the_age_code_is_one_block_in_both_cards_and_every_copy():
    srcs = cards.sources()
    ref = block(srcs[HOLDERS[0]])
    assert ref and "function fwDataAge(" in ref and "function fwAgeDur(" in ref
    built = cards.build("9.9.9", ["pilot2", "jane_doe"])
    for name in HOLDERS:
        src = srcs[name]
        assert src.count(START) == 1 and src.count(END) == 1 and block(src) == ref, name
        assert src.index(END) < src.index("\nclass FlightWatcher"), name  # defined before the card uses it
        for who in ("pilot2", "jane_doe"):
            cp = built[f"{name}-{who}.js"]
            assert block(cp) == ref and block(PT.portal_card(cp)) == ref, (name, who)
    # nothing in it a copy rewrites: no entity ids (each card passes its own), no names, no em dash
    assert "flight_watcher" not in ref and "flight-watcher" not in ref and "FW_PORTAL" not in ref
    assert not re.search(r"\b(?:sensor|number|switch)\.", ref) and not re.search(r"\bryan\b|\bpako\b", ref, re.I)
    assert chr(0x2014) not in ref


# ---------------------------------------------------------------- the age math (normal and hunt, both thresholds)
AGE_JS = """(cases) => cases.map(([last, hunting, nm, hs]) => { const a = fwDataAge(last, hunting, nm, hs, Date.now());
  return [a.text, a.level, a.word, a.rule]; })"""


def test_the_age_and_both_thresholds_in_normal_and_hunt_mode():
    cases = [  # [last check, hunting, normal min, hunt s]; the clock is 11:30:00Z
        ["2026-11-10T11:25:00+00:00", False, "6", "40"],  # 5 min of 6
        ["2026-11-10T11:24:00+00:00", False, "6", "40"],  # exactly 1x: not past it
        ["2026-11-10T11:23:59+00:00", False, "6", "40"],  # 1 s past 1x
        ["2026-11-10T11:18:00+00:00", False, "6", "40"],  # exactly 2x: still amber
        ["2026-11-10T11:17:59+00:00", False, "6", "40"],  # 1 s past 2x
        ["2026-11-10T11:29:21+00:00", True, "6", "40"],  # hunting: 39 s of 40
        ["2026-11-10T11:29:20+00:00", True, "6", "40"],  # exactly 1x
        ["2026-11-10T11:29:19+00:00", True, "6", "40"],  # 41 s
        ["2026-11-10T11:28:40+00:00", True, "6", "40"],  # exactly 2x (80 s)
        ["2026-11-10T11:28:39+00:00", True, "6", "40"],  # 81 s
        ["2026-11-10T11:29:49+00:00", True, "90", "5"],  # hunting takes the hunt interval, not the long normal one
        ["2026-11-10T11:29:49+00:00", False, "6", "5"],  # not hunting: the hunt interval does not count
        ["2026-11-10T09:25:00+00:00", False, "6", "40"],  # hours
        ["2026-11-10T09:30:00+00:00", False, "6", "40"],
        ["2026-11-07T09:00:00+00:00", False, "6", "40"],  # days
        ["2026-11-10T11:31:00+00:00", False, "6", "40"],  # a read time ahead of the phone's clock: 0 s, never negative
    ]
    got = _run([("a", f"({AGE_JS})({json.dumps(cases)})")], _src("clock-card"))["a"]
    hunt = "Stale past 40 s, very stale past 80 s: 1x and 2x the hunt check interval."
    assert [g[:3] for g in got] == [
        ["Data age 5 min", "", ""], ["Data age 6 min", "", ""], ["Data age 6 min, stale", "amber", "stale"],
        ["Data age 12 min, stale", "amber", "stale"], ["Data age 12 min, very stale", "red", "very stale"],
        ["Data age 39 s", "", ""], ["Data age 40 s", "", ""], ["Data age 41 s, stale", "amber", "stale"],
        ["Data age 1 min, stale", "amber", "stale"], ["Data age 1 min, very stale", "red", "very stale"],
        ["Data age 11 s, very stale", "red", "very stale"], ["Data age 11 s", "", ""],
        ["Data age 2 h 5 min, very stale", "red", "very stale"], ["Data age 2 h, very stale", "red", "very stale"],
        ["Data age 3 d 2 h, very stale", "red", "very stale"], ["Data age 0 s", "", ""]]
    assert got[0][3] == NORMAL_RULE and got[5][3] == hunt
    assert got[10][3] == "Stale past 5 s, very stale past 10 s: 1x and 2x the hunt check interval."


def test_an_unknown_or_missing_value_gives_no_colour():
    cases = [["unknown", False, "6", "40"], ["unavailable", True, "6", "40"], ["", False, "6", "40"],
             [None, False, "6", "40"], ["not a time", False, "6", "40"],
             ["2026-11-10T11:00:00+00:00", False, "unavailable", "40"],  # 30 min, no normal interval to judge by
             ["2026-11-10T11:00:00+00:00", False, "0", "40"],
             ["2026-11-10T11:29:00+00:00", True, "6", "unknown"], ["2026-11-10T11:29:00+00:00", True, "6", None]]
    got = _run([("a", f"({AGE_JS})({json.dumps(cases)})")], _src("clock-card"))["a"]
    assert [g[:3] for g in got[:5]] == [["Data age unknown", "", ""]] * 5
    assert [g[:3] for g in got[5:7]] == [["Data age 30 min", "", ""]] * 2
    assert [g[:3] for g in got[7:]] == [["Data age 1 min", "", ""]] * 2
    assert got[5][3] == "No normal check interval is known, so the age is not judged."
    assert got[7][3] == "No hunt check interval is known, so the age is not judged."
    # a missing entity reaches the card as no state at all: the same
    js = """(() => { const c = document.createElement('flight-watcher-clock-card'); c.setConfig({});
      document.body.appendChild(c); c.hass = {states: {}, callService: () => {}};
      const el = c.shadowRoot.getElementById('age'); return [el.textContent, el.dataset.age]; })()"""
    assert _run([("none", js)], _src("clock-card"))["none"] == ["Data age unknown", ""]


# ---------------------------------------------------------------- the clock card: one stamp in place of "Last"
def _clock(last="2026-11-10T11:27:00+00:00", nm="6", hs="30", hunt="off", st="idle", pilot=True):
    h = {"sensor.flight_watcher_state": _s(st, {"note": "", "role": "pilot" if pilot else "admin"}),
         "sensor.flight_watcher_last_check": _s(last),
         "sensor.flight_watcher_next_check": _s("2026-11-10T11:33:00+00:00"),
         "switch.flight_watcher_hunt_mode": _s(hunt), "switch.flight_watcher_pause": _s("off"),
         "number.flight_watcher_hunt_check_every": _s(hs, {"min": 5, "max": 90}),
         "number.flight_watcher_normal_check_every": _s(nm, {"min": 1, "max": 90})}
    return _pilot(h) if pilot else h


CLOCK_CASES = {  # name: (states kwargs, text, level)
    "fresh": ({}, "Data age 3 min", ""),
    "stale": ({"last": "2026-11-10T11:22:00+00:00"}, "Data age 8 min, stale", "amber"),
    "very stale": ({"last": "2026-11-10T11:10:00+00:00"}, "Data age 20 min, very stale", "red"),
    "unknown": ({"last": "unknown"}, "Data age unknown", ""),
    "hunt stale": ({"last": "2026-11-10T11:29:00+00:00", "hunt": "on", "st": "hunting"},
                   "Data age 1 min, stale", "amber"),
    "hunt very stale": ({"last": "2026-11-10T11:28:59+00:00", "hunt": "on", "st": "hunting"},
                        "Data age 1 min, very stale", "red"),
    "hunting state": ({"last": "2026-11-10T11:28:59+00:00", "st": "hunting"}, "Data age 1 min, very stale", "red"),
    "stuck": ({"last": "2026-11-10T09:30:00+00:00", "hunt": "on", "st": "hunting"}, "Data age 2 h, very stale", "red"),
}

STAMP_JS = """([tag, cfg, st]) => { const c = mount(tag, cfg, st); const r = c.shadowRoot;
  const el = r.querySelector('.ag[data-age]');
  return new Promise((ok) => setTimeout(() => ok({text: el ? el.textContent : null, level: el ? el.dataset.age : null,
    title: el ? el.title : '', color: el ? getComputedStyle(el).color : '',
    all: (r.querySelector('ha-card') || r).textContent,
    card: (r.querySelector('ha-card') || {}).className, lt: !!r.getElementById('lt'), la: !!r.getElementById('la'),
    nt: (r.getElementById('nt') || {}).textContent, buttons: r.querySelectorAll('button').length,
    con: fwContrast(c), fit: fwFits(c)}), 80)); }"""


def _clock_renders(pilot, scheme):
    out = {}
    with _browser() as b:
        for name, (kw, _, _) in CLOCK_CASES.items():
            pg = _portal_page(b, [_card("clock-card", pilot=pilot)], width=390, scheme=scheme)
            if not pilot:  # the admin's copy on Home Assistant's own theme
                pg.evaluate(HA_VARS_JS, (HA_DARK if scheme == "dark" else HA_LIGHT).split(";background")[0])
            tag = "flight-watcher-clock-card" + ("-pilot2" if pilot else "")
            out[name] = pg.evaluate(STAMP_JS, [tag, {}, _clock(pilot=pilot, **kw)])
            pg.context.close()
    return out


def _check_clock(got, scheme):
    for name, (_, text, level) in CLOCK_CASES.items():
        g = got[name]
        assert (g["text"], g["level"]) == (text, level), name
        assert not g["lt"] and not g["la"] and not re.search(r"\bLast\b", g["all"]), name  # "Last" gave way
        assert g["nt"], name  # Next stays
        assert not g["con"]["fails"], (name, json.dumps(g["con"]["fails"], indent=1))
        assert g["fit"]["page"] <= 390 and g["fit"]["right"] <= 390, (name, g["fit"])
        if level == "amber":
            assert g["color"] == AMBER[scheme], name
        if level == "red":
            assert g["color"] == RED[scheme], name
    assert got["fresh"]["color"] not in (AMBER[scheme], RED[scheme])
    assert got["fresh"]["title"] == "Last good read 01:27:00 HST. " + NORMAL_RULE
    assert got["unknown"]["title"].startswith("No good read on file.")
    assert got["stuck"]["card"] == "err" and got["very stale"]["card"] == "ok"  # the state line keeps its own colour


def test_the_clock_card_stamp_on_a_pilots_portal_light_and_dark():
    for scheme in ("light", "dark"):
        _check_clock(_clock_renders(True, scheme), scheme)


def test_the_clock_card_stamp_on_home_assistant_light_and_dark():
    for scheme in ("light", "dark"):
        _check_clock(_clock_renders(False, scheme), scheme)


TICK_JS = ("(() => { const el = C.shadowRoot.querySelector('.ag[data-age]'); "
           "return [el.textContent, el.dataset.age]; })()")


def test_the_clock_card_stamp_ticks_without_a_reload():
    with _browser() as b:
        pg = _portal_page(b, [_card("clock-card")], clock=True)
        pg.clock.pause_at("2026-11-10T11:30:02Z")  # from here the page's time moves only when the test says
        pg.evaluate("(st) => { window.C = mount('flight-watcher-clock-card-pilot2', {}, st); }",
                    _clock(last="2026-11-10T11:25:30+00:00"))  # 4 min 32 s of 6
        assert pg.evaluate(TICK_JS) == ["Data age 4 min", ""]
        pg.clock.run_for(91_000)
        assert pg.evaluate(TICK_JS) == ["Data age 6 min, stale", "amber"]
        pg.clock.run_for(6 * 60_000)
        assert pg.evaluate(TICK_JS) == ["Data age 12 min, very stale", "red"]
        pg.evaluate("(st) => { C.hass = mkHass(st); }", _clock(last="2026-11-10T11:37:30+00:00"))  # a good read
        assert pg.evaluate(TICK_JS) == ["Data age 3 s", ""]


def test_the_details_view_stamp_is_the_clock_card_in_age_mode():
    with _browser() as b:
        for scheme in ("light", "dark"):
            pg = _portal_page(b, [_card("clock-card", pilot=False)], width=390, scheme=scheme)
            pg.evaluate(HA_VARS_JS, (HA_DARK if scheme == "dark" else HA_LIGHT).split(";background")[0])
            for name, (kw, text, level) in CLOCK_CASES.items():
                g = pg.evaluate(STAMP_JS, ["flight-watcher-clock-card", {"mode": "age"}, _clock(pilot=False, **kw)])
                assert (g["text"], g["level"]) == (text, level), name
                assert g["buttons"] == 0 and g["all"].strip() == text and g["nt"] is None, name  # the stamp alone
                assert not g["con"]["fails"], (name, g["con"]["fails"])
                assert g["fit"]["page"] <= 390, name
                if level:
                    assert g["color"] == (AMBER if level == "amber" else RED)[scheme], name
            pg.context.close()
        pg = _portal_page(b, [_card("clock-card", pilot=False)], clock=True)
        pg.evaluate("(st) => { window.C = mount('flight-watcher-clock-card', {mode: 'age'}, st); }",
                    _clock(last="2026-11-10T11:25:30+00:00", pilot=False))
        assert pg.evaluate(TICK_JS) == ["Data age 4 min", ""]
        pg.clock.run_for(91_000)
        assert pg.evaluate(TICK_JS) == ["Data age 6 min, stale", "amber"]
        assert pg.evaluate("window.calls") == []  # it only reads


# ---------------------------------------------------------------- the schedule card's header
def _sched(last="2026-11-10T11:27:00+00:00", nm="6", hs="30", hunt="off", pilot=True, updated="Nov 9, 2026 09:54:34"):
    st = _read()
    st["sensor.flight_watcher_schedule"]["attributes"]["updated"] = updated
    st.update({"sensor.flight_watcher_last_check": _s(last), "switch.flight_watcher_hunt_mode": _s(hunt),
               "number.flight_watcher_hunt_check_every": _s(hs, {"min": 5, "max": 90}),
               "number.flight_watcher_normal_check_every": _s(nm, {"min": 1, "max": 90})})
    return _pilot(st) if pilot else st


HEAD_JS = """([tag, st]) => { const c = mount(tag, {}, st); const r = c.shadowRoot;
  return new Promise((ok) => setTimeout(() => {
    const el = r.querySelector('.hd2 .ag[data-age]'), hd = r.querySelector('.hd2');
    ok({text: el ? el.textContent : null, level: el ? el.dataset.age : null, title: el ? el.title : '',
        color: el ? getComputedStyle(el).color : '', head: hd.textContent, u: !!r.querySelector('.hd2 .u'),
        con: fwContrast(c), fit: fwFits(c)}); }, 80)); }"""


def test_the_schedule_header_has_the_stamp_and_flica_time_only_on_hover():
    cases = {"fresh": ({}, "Data age 3 min", ""),
             "stale": ({"last": "2026-11-10T11:22:00+00:00"}, "Data age 8 min, stale", "amber"),
             "very stale": ({"last": "2026-11-10T11:10:00+00:00"}, "Data age 20 min, very stale", "red"),
             "unknown": ({"last": "unavailable"}, "Data age unknown", ""),
             "hunt": ({"last": "2026-11-10T11:28:59+00:00", "hunt": "on"}, "Data age 1 min, very stale", "red"),
             "no flica time": ({"updated": ""}, "Data age 3 min", "")}
    with _browser() as b:
        for pilot in (True, False):
            for scheme in ("light", "dark"):
                pg = _portal_page(b, [_card("schedule-card", pilot=pilot)], width=390, scheme=scheme)
                if not pilot:
                    pg.evaluate(HA_VARS_JS, (HA_DARK if scheme == "dark" else HA_LIGHT).split(";background")[0])
                tag = "flight-watcher-schedule-card" + ("-pilot2" if pilot else "")
                for name, (kw, text, level) in cases.items():
                    g = pg.evaluate(HEAD_JS, [tag, _sched(pilot=pilot, **kw)])
                    where = (name, pilot, scheme)
                    assert (g["text"], g["level"]) == (text, level), where
                    assert "updated" not in g["head"] and not g["u"], where  # FLICA's time is not shown, only hovered
                    # the stamp's own contrast (the rest of the card has its own render tests, on the portal's theme)
                    mine = [f for f in g["con"]["fails"] if f["cls"].startswith("span.ag")]
                    assert not mine, (where, json.dumps(mine, indent=1))
                    if pilot:  # the portal's copy, as F#119 checks it: nothing fails
                        assert not g["con"]["fails"], (where, json.dumps(g["con"]["fails"], indent=1))
                    assert g["fit"]["page"] <= 390 and g["fit"]["right"] <= 390, (where, g["fit"])
                    if level:
                        assert g["color"] == (AMBER if level == "amber" else RED)[scheme], where
                    if name == "no flica time":
                        assert "FLICA updated" not in g["title"], where
                    else:
                        assert g["title"].startswith("FLICA updated Nov 9, 2026 09:54:34. "), where
                    pg.evaluate("() => { document.querySelector('.view').innerHTML = ''; }")
                pg.context.close()


def test_the_award_line_keeps_the_stamp_without_a_flica_time():
    from test_release_a_schedule_card import FAILED, _award, _states
    vers = {"2026-11": {"count": 1, "current": "11.001", "awarded": "11.001", "versions": [_award()]}}
    st = _states({}, vers, FAILED, "Nov 9, 2026")
    st["sensor.flight_watcher_last_check"] = _s("2026-11-10T11:27:00+00:00")
    st["number.flight_watcher_normal_check_every"] = _s("6")
    with _browser() as b:
        pg = _portal_page(b, [_card("schedule-card", pilot=False)])
        g = pg.evaluate(HEAD_JS, ["flight-watcher-schedule-card", st])
    assert g["text"] == "Data age 3 min" and "FLICA updated" not in g["title"]  # the award line has no FLICA time


SCHED_TICK_JS = ("(() => { const el = C.shadowRoot.querySelector('.hd2 .ag[data-age]'); return [el.textContent, "
                 "el.dataset.age, el.title, C.shadowRoot.querySelector('h3').dataset.mark || '']; })()")


def test_the_schedule_stamp_ticks_without_redrawing_the_card():
    ns = f"number.{P}_hunt_check_every"
    with _browser() as b:
        pg = _portal_page(b, [_card("schedule-card")], clock=True)
        pg.evaluate("(st) => { window.C = mount('flight-watcher-schedule-card-pilot2', {}, st); }",
                    _sched(last="2026-11-10T11:25:30+00:00"))
        pg.wait_for_timeout(300)  # the pairings package and versions files answer 404 and the card redraws once
        pg.clock.pause_at("2026-11-10T11:30:05Z")  # from here the page's time moves only when the test says
        pg.evaluate("(() => { C.shadowRoot.querySelector('h3').dataset.mark = 'kept'; window.N = 0; "
                    "const r = C._render; "
                    "C._render = function () { window.N++; return r.apply(this, arguments); }; })()")
        assert pg.evaluate(SCHED_TICK_JS)[:2] == ["Data age 4 min", ""]
        pg.clock.run_for(91_000)
        got = pg.evaluate(SCHED_TICK_JS)
        assert got[:2] == ["Data age 6 min, stale", "amber"] and got[3] == "kept"  # ticked, the grid not redrawn
        assert pg.evaluate("window.N") == 0
        # hunting with 5 s (no schedule entity changed, so the card does not redraw): the hunt rule, at once
        st = _sched(last="2026-11-10T11:31:25+00:00", hunt="on", hs="5")
        pg.evaluate("(st) => { C.hass = mkHass(st); }", st)
        got = pg.evaluate(SCHED_TICK_JS)
        assert got[:2] == ["Data age 11 s, very stale", "red"] and got[3] == "kept" and pg.evaluate("window.N") == 0
        assert got[2].endswith("Stale past 5 s, very stale past 10 s: 1x and 2x the hunt check interval.")
        assert st[ns]["state"] == "5"
        pg.evaluate("() => { window.T = C._ageT; C.remove(); }")  # off the page: the tick stops
        assert pg.evaluate("C._ageT") is None


# ---------------------------------------------------------------- the portal: nothing new is exported
def test_a_pilots_portal_shows_the_stamp_from_what_it_already_has():
    for oid in ("state", "last_check", "next_check", "normal_check_every", "hunt_check_every", "hunt_mode"):
        assert roles.entity_on_portal(oid, "james"), oid
    names = sorted(cards.sources())
    assert names == sorted(f"flight-watcher-{n}" for n in (
        "charters-card", "clock-card", "finds-card", "improved-card", "layover-card", "pickers-card", "pilot-card",
        "pilot-search-card", "pilot-uploads-card", "pilotdb-card", "pot-card", "recall-card", "requests-card",
        "row-colors", "schedule-card", "settings-card", "tickets-card", "uploads-card", "working-card"))  # no new card
    layout = open(os.path.join(HERE, "portal_layout.json"), encoding="utf-8").read()
    assert '"mode": "age"' not in layout  # the portal's tabs are as they were: the clock card already carries the stamp
    for name in HOLDERS:  # the stamp publishes nothing: the cards' MQTT subs are what they were
        cp = PT.portal_card(cards.build("9.9.9", ["james"])[f"{name}-james.js"])
        assert "sensor.flight_watcher_james_last_check" in cp, name
    assert PT.card_subs(PT.portal_card(cards.build("9.9.9", ["james"])["flight-watcher-clock-card-james.js"]),
                        "flight_watcher_james") == set()


# ---------------------------------------------------------------- the Details view snapshot and the docs
def test_the_details_view_tile_is_the_stamp_in_the_snapshot():
    path = os.path.join(ROOT, "ha", "dashboard_flight_watcher.json")
    text = open(path, encoding="utf-8").read()
    assert text == json.dumps(json.loads(text), indent=2, ensure_ascii=False) + "\n"  # as ha/README.md's Refresh
    v = next(v for v in json.loads(text)["data"]["config"]["views"] if v.get("path") == "details")
    cs = v["sections"][0]["cards"]
    names = [c.get("name") or c.get("heading") or c.get("type") for c in cs[:5]]
    assert names == ["Health", "State", "FLICA session", "custom:flight-watcher-clock-card", "App version"]
    assert cs[3] == {"grid_options": {"columns": 6}, "mode": "age", "type": "custom:flight-watcher-clock-card"}
    assert '"name": "Last check"' not in text
    readme = open(os.path.join(ROOT, "ha", "README.md"), encoding="utf-8").read()
    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert sha in readme
    sec = readme[readme.index("## Pending on Pako (1.7.12): the Details view's data age stamp"):]
    sec = sec[:sec.index("\n## ", 5)]
    pako = "be03a0a48b9df66962e49a86c285921858768f5f97d27fda88288c26a0595435"  # Pako's dashboard, until then
    assert sha in sec and pako in sec
    assert "Undo" in sec and "yes" in sec and '"mode": "age"' in sec
    assert chr(0x2014) not in readme and chr(0x2014) not in text


def test_version_changelog_and_readme_say_data_age():
    cfg = open(os.path.join(HERE, "config.yaml"), encoding="utf-8").read()
    assert re.search(r'^version: "1\.7\.12"$', cfg, re.M)
    assert re.search(r'^VERSION = "1\.7\.12"$', open(os.path.join(HERE, "watcher.py"), encoding="utf-8").read(), re.M)
    log = open(os.path.join(HERE, "CHANGELOG.md"), encoding="utf-8").read()
    assert log.startswith("# Changelog\n\n## 1.7.12\n") and "\n## 1.7.11\n" in log
    top = log.split("\n## 1.7.11\n", 1)[0]
    for word in ("Data age", "stale", "very stale", "FLICA updated", "Details", "hunt", "portal"):
        assert word in top, word
    readme = open(os.path.join(HERE, "README.md"), encoding="utf-8").read()
    assert "**Data age** (1.7.12" in readme and "FLICA updated" in readme
    for f in ("CHANGELOG.md", "README.md", "www/flight-watcher-clock-card.js", "www/flight-watcher-schedule-card.js",
              "tests/test_fw1712_data_age.py"):
        assert chr(0x2014) not in open(os.path.join(HERE, f), encoding="utf-8").read(), f
