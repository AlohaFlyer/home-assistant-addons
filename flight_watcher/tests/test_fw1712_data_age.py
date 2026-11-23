"""1.7.12 (Ryan, Nov 17, yes: "Replace the two clocks ("updated" and "Last check") with one "data age" stamp. Turn it
amber past 1x the normal interval and red past 2x."): the clock card's "Last" and the schedule card's "updated" give
way to one "Data age 12 min" stamp, the time since the Watcher's last good read (sensor.<prefix>_last_check, which a
check sets only when it succeeds). Amber past 1x the check interval (the normal one in minutes, the hunt one in seconds
while hunting), red past 2x, plain otherwise, with the word "stale" or "very stale" so the colour is never the only cue.
An unknown or missing read time is "Data age unknown", no colour. The Details view's "Last check" tile is the same stamp
(the clock card in age mode), FLICA's own schedule time stays in the schedule card's hover text ("FLICA updated ..."),
the stamp ticks by itself, and a pilot's portal copies show it from entities the portal already has. Synthetic states
only, rendered in Chromium at 390 px, light and dark.

1.7.12 review (the meaning of "1x" shipped under Ryan's "Ship it all", his to undo): 1x and 2x of the Watcher's own longest cycle between two good
reads (the interval, or a pilot's held budget pace, x 1.3 for the jitter, plus room for the check), counted from a mode
change or a gate wait when those come later; red "Watcher offline" when the app is down; the day in the hover text for
a read before today; a tap on the clock card's stamp shows its hover text; the clock card's height and the schedule
header's month controls never move as the age ticks; the Details tile is one 56 px row; a mode change rebuilds the
card."""
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
NORMAL_RULE = ("Stale past 10 min 48 s, very stale past 21 min 36 s: 1x and 2x the Watcher's longest normal cycle, the "
               "normal check interval (6 min) plus its 30 % jitter, and 3 min for the check.")
HUNT40_RULE = ("Stale past 1 min 37 s, very stale past 3 min 14 s: 1x and 2x the Watcher's longest hunt cycle, the hunt "
               "check interval (40 s) plus its 30 % jitter, and 45 s for the check.")
HUNT5_RULE = ("Stale past 52 s, very stale past 1 min 44 s: 1x and 2x the Watcher's longest hunt cycle, the hunt check "
              "interval (5 s) plus its 30 % jitter, and 45 s for the check.")


def block(text):
    if START not in text:
        return None
    i = text.index(START)
    return text[i:text.index(END, i) + len(END)]


# ---------------------------------------------------------------- the shared block
def test_the_age_code_is_one_block_in_both_cards_and_every_copy():
    srcs = cards.sources()
    ref = block(srcs[HOLDERS[0]])
    assert ref and "function fwDataAge(" in ref and "function fwAgeDur(" in ref and "function fwAgeFrom(" in ref
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
# 1.7.12 review: 1x and 2x of the Watcher's longest cycle (the interval x 1.3, plus room for the check): normal 6 min is
# 468 s + 180 s = 648 s (10 min 48 s) and 1296 s; hunt 40 s is 52 s + 45 s = 97 s and 194 s; hunt 5 s is 52 s and 104 s
AGE_JS = """(cases) => cases.map(([last, hunting, nm, hs, more]) => {
  const a = fwDataAge(last, hunting, nm, hs, Date.now(), more);
  return [a.text, a.level, a.word, a.rule, a.read]; })"""


def _age(cases, now=NOW):
    return _run([("a", f"({AGE_JS})({json.dumps(cases)})")], _src("clock-card"), now=now)["a"]


def test_the_age_and_both_thresholds_in_normal_and_hunt_mode():
    cases = [  # [last check, hunting, normal min, hunt s]; the clock is 11:30:00Z
        ["2026-11-10T11:25:00+00:00", False, "6", "40"],  # 5 min
        ["2026-11-10T11:19:12+00:00", False, "6", "40"],  # exactly 1x (648 s): not past it
        ["2026-11-10T11:19:11+00:00", False, "6", "40"],  # 1 s past 1x
        ["2026-11-10T11:08:24+00:00", False, "6", "40"],  # exactly 2x: still amber
        ["2026-11-10T11:08:23+00:00", False, "6", "40"],  # 1 s past 2x
        ["2026-11-10T11:28:24+00:00", True, "6", "40"],  # hunting: 96 s of 97
        ["2026-11-10T11:28:23+00:00", True, "6", "40"],  # exactly 1x
        ["2026-11-10T11:28:22+00:00", True, "6", "40"],  # 98 s
        ["2026-11-10T11:26:46+00:00", True, "6", "40"],  # exactly 2x (194 s)
        ["2026-11-10T11:26:45+00:00", True, "6", "40"],  # 195 s
        ["2026-11-10T11:28:15+00:00", True, "90", "5"],  # hunting takes the hunt interval, not the long normal one
        ["2026-11-10T11:28:15+00:00", False, "6", "5"],  # not hunting: the hunt interval does not count
        ["2026-11-10T09:25:00+00:00", False, "6", "40"],  # hours
        ["2026-11-10T09:30:00+00:00", False, "6", "40"],
        ["2026-11-07T09:00:00+00:00", False, "6", "40"],  # days
        ["2026-11-10T11:31:00+00:00", False, "6", "40"],  # a read time ahead of the phone's clock: 0 s, never negative
    ]
    got = _age(cases)
    assert [g[:3] for g in got] == [
        ["Data age 5 min", "", ""], ["Data age 10 min", "", ""], ["Data age 10 min, stale", "amber", "stale"],
        ["Data age 21 min, stale", "amber", "stale"], ["Data age 21 min, very stale", "red", "very stale"],
        ["Data age 1 min", "", ""], ["Data age 1 min", "", ""], ["Data age 1 min, stale", "amber", "stale"],
        ["Data age 3 min, stale", "amber", "stale"], ["Data age 3 min, very stale", "red", "very stale"],
        ["Data age 1 min, very stale", "red", "very stale"], ["Data age 1 min", "", ""],
        ["Data age 2 h 5 min, very stale", "red", "very stale"], ["Data age 2 h, very stale", "red", "very stale"],
        ["Data age 3 d 2 h, very stale", "red", "very stale"], ["Data age 0 s", "", ""]]
    assert got[0][3] == NORMAL_RULE and got[5][3] == HUNT40_RULE and got[10][3] == HUNT5_RULE
    assert got[0][4] == "Last good read 01:25:00 HST."


def test_an_unknown_or_missing_value_gives_no_colour():
    cases = [["unknown", False, "6", "40"], ["", False, "6", "40"], [None, False, "6", "40"],
             ["not a time", False, "6", "40"],
             ["2026-11-10T11:00:00+00:00", False, "unavailable", "40"],  # 30 min, no normal interval to judge by
             ["2026-11-10T11:00:00+00:00", False, "0", "40"],
             ["2026-11-10T11:29:00+00:00", True, "6", "unknown"], ["2026-11-10T11:29:00+00:00", True, "6", None]]
    got = _age(cases)
    assert [g[:3] for g in got[:4]] == [["Data age unknown", "", ""]] * 4
    assert got[0][4] == "No good read on file." and got[0][3] == NORMAL_RULE
    assert [g[:3] for g in got[4:6]] == [["Data age 30 min", "", ""]] * 2
    assert [g[:3] for g in got[6:]] == [["Data age 1 min", "", ""]] * 2
    assert got[4][3] == "No normal check interval is known, so the age is not judged."
    assert got[6][3] == "No hunt check interval is known, so the age is not judged."
    # a missing entity reaches the card as no state at all: the same
    js = """(() => { const c = document.createElement('flight-watcher-clock-card'); c.setConfig({});
      document.body.appendChild(c); c.hass = {states: {}, callService: () => {}};
      const el = c.shadowRoot.getElementById('age'); return [el.textContent, el.dataset.age]; })()"""
    assert _run([("none", js)], _src("clock-card"))["none"] == ["Data age unknown", ""]


# ---------------------------------------------------------------- review F1/F2 (logic): a healthy Watcher never reads stale
CYCLE_JS = """(cases) => cases.map(([hunting, nm, hs, note, iv, D]) => {
  const out = [];
  for (const f of [0.7, 0.85, 1, 1.15, 1.3]) {  // gap() is the interval x 0.7 to 1.3, after the read; then the check
    const age = iv * f + D, t = Date.now() - age * 1000;
    out.push(fwDataAge(new Date(t).toISOString(), hunting, nm, hs, Date.now(), {note}).level);
  }
  return out; })"""


def test_a_healthy_cycle_of_jitter_and_check_time_shows_no_colour():
    held_h = "Hunting every 10 s is held to 100 FLICA loads an hour: checks wait for the budget, at least 105 s apart"
    held_n = "Checking every 1 min is held to 100 FLICA loads an hour: checks wait for the budget, at least 134 s apart"
    cases = [  # [hunting, normal min, hunt s, state note, the wait's middle in s, the next check's time in s]
        [False, "6", "30", "", 360, 0], [False, "6", "30", "", 360, 30],
        [False, "6", "30", "", 360, 150],  # a crew index chunk (50 pages, about 2 min) in that check
        [False, "1", "30", "", 60, 150], [False, "10", "30", "", 600, 150],
        [True, "6", "5", "", 5, 2], [True, "6", "5", "", 5, 10],
        [True, "6", "5", "", 5, 38],  # two pot months and a hunting crew chunk (8 pages, about 20 s), 2 s of skew
        [True, "6", "40", "", 40, 30],
        [True, "6", "10", held_h, 105, 30],  # review F3: a pilot's hunt his FLICA budget holds to 105 s apart
        [False, "1", "30", held_n, 134, 60],
    ]
    got = _age_cycles(cases)
    assert got == [[""] * 5] * len(cases), got


def _age_cycles(cases):
    return _run([("a", f"({CYCLE_JS})({json.dumps(cases)})")], _src("clock-card"))["a"]


def test_the_held_pace_the_gate_and_a_mode_change_move_the_thresholds():
    held = "Hunting every 10 s is held to 100 FLICA loads an hour: checks wait for the budget, at least 105 s apart"
    gate = "FLICA budget: 100 page loads in the last hour; the next one waits until 01:50 HST"
    old = "2026-11-09T00:00:00+00:00"
    cases = [
        # review F3: held to 105 s apart: 137 s + 45 s = 182 s, 364 s
        ["2026-11-10T11:27:00+00:00", True, "6", "10", {"note": held}],  # 180 s: plain
        ["2026-11-10T11:26:57+00:00", True, "6", "10", {"note": held}],  # 183 s: stale
        ["2026-11-10T11:23:55+00:00", True, "6", "10", {"note": held}],  # 365 s: very stale
        ["2026-11-10T11:29:39+00:00", True, "6", "10", {"note": ""}],  # 21 s at 10 s, not held: plain too
        # the FLICA budget holds the next check until 11:50Z: the read is due 3 min (normal) after it
        ["2026-11-10T11:15:00+00:00", False, "6", "30", {"note": gate, "next": "2026-11-10T11:50:00+00:00"}],
        ["2026-11-10T11:15:00+00:00", False, "6", "30", {"note": gate, "next": "2026-11-10T11:26:00+00:00"}],
        ["2026-11-10T11:15:00+00:00", False, "6", "30", {"note": "", "next": "2026-11-10T11:50:00+00:00"}],
        # review F1 (cards, d): Hunt pressed 10 s ago with a 3 min old read; at 30 s: 39 + 45 = 84 s from the press
        ["2026-11-10T11:27:00+00:00", True, "6", "30", {"changed": ["2026-11-10T11:29:50+00:00", old]}],
        ["2026-11-10T11:27:00+00:00", True, "6", "30", {"changed": ["2026-11-10T11:28:00+00:00", old]}],
        ["2026-11-10T11:27:00+00:00", True, "6", "30", {"changed": [old, old]}],
        # a pilot's interval lowered after the read (no wake): the next check planned before still counts
        ["2026-11-10T11:10:00+00:00", False, "1", "30", {"changed": [old, "2026-11-10T11:20:00+00:00"],
                                                         "next": "2026-11-10T11:31:00+00:00"}],
        ["2026-11-10T11:10:00+00:00", False, "1", "30", {"changed": [old, old], "next": "2026-11-10T11:31:00+00:00"}],
    ]
    got = _age(cases)
    assert [g[:2] for g in got] == [
        ["Data age 3 min", ""], ["Data age 3 min, stale", "amber"], ["Data age 6 min, very stale", "red"],
        ["Data age 21 s", ""],
        ["Data age 15 min", ""], ["Data age 15 min, stale", "amber"], ["Data age 15 min, stale", "amber"],
        ["Data age 3 min", ""], ["Data age 3 min, stale", "amber"], ["Data age 3 min, very stale", "red"],
        ["Data age 20 min", ""], ["Data age 20 min, very stale", "red"]]
    assert got[0][3] == ("Stale past 3 min 2 s, very stale past 6 min 4 s: 1x and 2x the Watcher's longest hunt cycle,"
                         " the 105 s the FLICA budget holds the checks apart plus its 30 % jitter, and 45 s for the"
                         " check.")
    assert got[4][3].endswith("The FLICA budget or host limit holds the next check until 01:50:00 HST: counted from "
                              "then.") and got[4][3].startswith("Stale past 38 min, very stale past 48 min 48 s: ")
    assert got[7][3].endswith(" Counted from the hunt or interval change after that read.")


def test_the_watchers_stuck_limit_is_never_later_than_very_stale():
    # normal 10 min: 2x the cycle is 32 min, the Watcher's Stuck limit 30 min (stuck_after_s): red from 30 min, so the
    # clock card's "Stuck." never sits beside an amber stamp
    got = _age([["2026-11-10T11:00:59+00:00", False, "10", "30"], ["2026-11-10T10:59:59+00:00", False, "10", "30"]])
    assert [g[:2] for g in got] == [["Data age 29 min, stale", "amber"], ["Data age 30 min, very stale", "red"]]
    assert got[1][3] == ("Stale past 16 min, very stale past 30 min: 1x and 2x the Watcher's longest normal cycle, the "
                         "normal check interval (10 min) plus its 30 % jitter, and 3 min for the check, or its Stuck "
                         "limit when that comes first.")
    with _browser() as b:
        pg = _portal_page(b, [_card("clock-card", pilot=False)], width=390)
        g = pg.evaluate(STAMP_JS, ["flight-watcher-clock-card", {}, _clock(last="2026-11-10T10:59:00+00:00", nm="10",
                                                                         pilot=False)])
    assert (g["text"], g["level"], g["card"]) == ("Data age 31 min, very stale", "red", "err") and "Stuck." in g["all"]


def test_a_phone_clock_a_few_seconds_fast_does_not_colour_a_fresh_hunt():
    # review F7: a read 3 s ago on a phone 8 s fast reads 11 s; at hunt 5 s that was "very stale"
    got = _age([["2026-11-10T11:29:49+00:00", True, "6", "5"]])
    assert got[0][:2] == ["Data age 11 s", ""]


def test_an_offline_watcher_reads_red_not_unknown():
    # review F5: the app down makes every entity unavailable (its availability topic): no read is coming
    cases = [["unavailable", False, "6", "40", {"lastChanged": "2026-11-10T11:18:00+00:00"}],
             ["unavailable", True, "unavailable", "unavailable", {"lastChanged": "2026-11-10T11:29:30+00:00"}],
             ["unavailable", False, "6", "40"], ["unknown", False, "6", "40"]]
    got = _age(cases)
    assert [g[:3] for g in got] == [
        ["Data age over 12 min, Watcher offline", "red", "Watcher offline"],
        ["Data age unknown, Watcher offline", "red", "Watcher offline"],
        ["Data age unknown, Watcher offline", "red", "Watcher offline"], ["Data age unknown", "", ""]]
    assert got[0][4] == "The Watcher is offline since 01:18:00 HST." and got[2][4] == "The Watcher is offline."


def test_a_read_on_an_earlier_day_names_its_day():
    # review F6: a read before today (HST) carries its day; the year too when it differs
    got = _age([["2026-11-10T09:30:00+00:00", False, "6", "40"], ["2026-11-07T09:05:00+00:00", False, "6", "40"],
                ["2026-11-10T11:27:00+00:00", False, "6", "40"], ["2025-11-10T11:27:00+00:00", False, "6", "40"]])
    assert [g[4] for g in got] == ["Last good read Nov 9 23:30:00 HST.", "Last good read Nov 6 23:05:00 HST.",
                                   "Last good read 01:27:00 HST.", "Last good read Nov 10, 2025 01:27:00 HST."]


# ---------------------------------------------------------------- the clock card: one stamp in place of "Last"
OLD = "2026-11-09T00:00:00+00:00"  # the switch and the intervals last changed well before every read here


def _clock(last="2026-11-10T11:27:00+00:00", nm="6", hs="30", hunt="off", st="idle", pilot=True, note="",
           nxt="2026-11-10T11:33:00+00:00", lc="2026-11-10T11:20:00+00:00"):
    h = {"sensor.flight_watcher_state": _s(st, {"note": note, "role": "pilot" if pilot else "admin"}),
         "sensor.flight_watcher_last_check": _s(last, lu=lc),
         "sensor.flight_watcher_next_check": _s(nxt),
         "switch.flight_watcher_hunt_mode": _s(hunt, lu=OLD), "switch.flight_watcher_pause": _s("off"),
         "number.flight_watcher_hunt_check_every": _s(hs, {"min": 5, "max": 90}, lu=OLD),
         "number.flight_watcher_normal_check_every": _s(nm, {"min": 1, "max": 90}, lu=OLD)}
    return _pilot(h) if pilot else h


CLOCK_CASES = {  # name: (states kwargs, text, level)
    "fresh": ({}, "Data age 3 min", ""),
    "stale": ({"last": "2026-11-10T11:18:00+00:00"}, "Data age 12 min, stale", "amber"),
    "very stale": ({"last": "2026-11-10T11:05:00+00:00"}, "Data age 25 min, very stale", "red"),
    "unknown": ({"last": "unknown"}, "Data age unknown", ""),
    "offline": ({"last": "unavailable", "st": "unavailable"}, "Data age over 10 min, Watcher offline", "red"),
    "hunt stale": ({"last": "2026-11-10T11:28:30+00:00", "hunt": "on", "st": "hunting"},
                   "Data age 1 min, stale", "amber"),
    "hunt very stale": ({"last": "2026-11-10T11:27:00+00:00", "hunt": "on", "st": "hunting"},
                        "Data age 3 min, very stale", "red"),
    "hunting state": ({"last": "2026-11-10T11:27:00+00:00", "st": "hunting"}, "Data age 3 min, very stale", "red"),
    "stuck": ({"last": "2026-11-10T09:30:00+00:00", "hunt": "on", "st": "hunting"}, "Data age 2 h, very stale", "red"),
}

STAMP_JS = """([tag, cfg, st]) => { const c = mount(tag, cfg, st); const r = c.shadowRoot;
  const el = r.querySelector('.ag[data-age]');
  return new Promise((ok) => setTimeout(() => ok({text: el ? el.textContent : null, level: el ? el.dataset.age : null,
    title: el ? el.title : '', color: el ? getComputedStyle(el.querySelector('.v') || el).color : '',
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
    assert got["offline"]["title"].startswith("The Watcher is offline since 01:20:00 HST.")
    assert got["stuck"]["card"] == "err" and got["very stale"]["card"] == "ok"  # the state line keeps its own colour
    assert got["offline"]["card"] == "err"


def test_the_clock_card_stamp_on_a_pilots_portal_light_and_dark():
    for scheme in ("light", "dark"):
        _check_clock(_clock_renders(True, scheme), scheme)


def test_the_clock_card_stamp_on_home_assistant_light_and_dark():
    for scheme in ("light", "dark"):
        _check_clock(_clock_renders(False, scheme), scheme)


def test_a_held_pilot_hunt_reads_slowed_and_not_stale():
    # review F3: James hunts at 10 s, his FLICA budget holds the checks at least 105 s apart: 21 s after a read the
    # card says "Slowed." and the stamp is plain (it was red "very stale" past 20 s)
    note = "Hunting every 10 s is held to 100 FLICA loads an hour: checks wait for the budget, at least 105 s apart"
    with _browser() as b:
        pg = _portal_page(b, [_card("clock-card")], width=390)
        g = pg.evaluate(STAMP_JS, ["flight-watcher-clock-card-pilot2", {}, _clock(
            last="2026-11-10T11:29:39+00:00", hunt="on", hs="10", st="hunting", note=note,
            nxt="2026-11-10T11:31:30+00:00")])
    assert (g["text"], g["level"], g["card"]) == ("Data age 21 s", "", "info") and "Slowed." in g["all"]
    assert "the 105 s the FLICA budget holds the checks apart" in g["title"]


TICK_JS = ("(() => { const el = C.shadowRoot.querySelector('.ag[data-age]'); "
           "return [el.textContent, el.dataset.age]; })()")


def test_the_clock_card_stamp_ticks_without_a_reload():
    with _browser() as b:
        pg = _portal_page(b, [_card("clock-card")], clock=True)
        pg.clock.pause_at("2026-11-10T11:30:02Z")  # from here the page's time moves only when the test says
        pg.evaluate("(st) => { window.C = mount('flight-watcher-clock-card-pilot2', {}, st); }",
                    _clock(last="2026-11-10T11:25:30+00:00"))  # 4 min 32 s of 10 min 48 s
        assert pg.evaluate(TICK_JS) == ["Data age 4 min", ""]
        pg.clock.run_for(388_000)
        assert pg.evaluate(TICK_JS) == ["Data age 11 min, stale", "amber"]
        pg.clock.run_for(660_000)
        assert pg.evaluate(TICK_JS) == ["Data age 22 min, very stale", "red"]
        pg.evaluate("(st) => { C.hass = mkHass(st); }", _clock(last="2026-11-10T11:47:25+00:00"))  # a good read
        assert pg.evaluate(TICK_JS) == ["Data age 5 s", ""]


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
        pg.clock.run_for(391_000)
        assert pg.evaluate(TICK_JS) == ["Data age 11 min, stale", "amber"]
        assert pg.evaluate("window.calls") == []  # it only reads


# ---------------------------------------------------------------- review: the clock card's layout and its stamp box
LAYOUT_CASES = [  # (last check, next check): every stamp width and every "(in N)" width over a cycle and past it
    ("2026-11-10T11:29:51+00:00", "2026-11-10T11:36:00+00:00"), ("2026-11-10T11:25:00+00:00", "2026-11-10T11:30:09+00:00"),
    ("2026-11-10T11:18:00+00:00", "2026-11-10T11:32:59+00:00"), ("2026-11-10T11:05:00+00:00", "2026-11-10T11:33:00+00:00"),
    ("2026-11-10T11:01:00+00:00", "2026-11-10T11:32:00+00:00"), ("unknown", "2026-11-10T11:31:59+00:00")]

BOX_JS = """([tag, cfg, st]) => { const c = mount(tag, cfg, st); const r = c.shadowRoot;
  const hc = r.querySelector('ha-card'), chk = r.getElementById('chk'), el = r.getElementById('age');
  return {h: Math.round(hc.getBoundingClientRect().height * 10) / 10, text: el.textContent,
    chk: chk ? Math.round(chk.getBoundingClientRect().top - hc.getBoundingClientRect().top) : null}; }"""


def test_the_clock_card_keeps_its_height_and_buttons_as_the_age_ticks():
    # review F2 (cards): at 390 px the card went from 149 to 171 px and back as the stamp and "(in N)" changed width
    with _browser() as b:
        for pilot, scheme, width in ((True, "light", 390), (True, "dark", 390), (False, "light", 390),
                                     (False, "dark", 390), (True, "light", 360), (True, "light", 430),
                                     (False, "light", 701), (False, "light", 768), (False, "light", 1024)):
            pg = _portal_page(b, [_card("clock-card", pilot=pilot)], width=width, scheme=scheme)
            if not pilot:
                pg.evaluate(HA_VARS_JS, (HA_DARK if scheme == "dark" else HA_LIGHT).split(";background")[0])
            tag = "flight-watcher-clock-card" + ("-pilot2" if pilot else "")
            got = []
            for last, nxt in LAYOUT_CASES:
                got.append(pg.evaluate(BOX_JS, [tag, {}, _clock(last=last, nxt=nxt, pilot=pilot)]))
                pg.evaluate("() => { document.querySelector('.view').innerHTML = ''; }")
            pg.context.close()
            assert len({(g["h"], g["chk"]) for g in got}) == 1, (pilot, scheme, width, got)
            assert {g["text"] for g in got} >= {"Data age 9 s", "Data age 12 min, stale", "Data age 29 min, very stale",
                                                "Data age unknown"}


TAP_JS = """([tag, cfg, st]) => { const c = mount(tag, cfg, st); const r = c.shadowRoot;
  const el = r.getElementById('age'), box = r.getElementById('agi');
  const seen = () => ({shown: !!box && getComputedStyle(box).display !== 'none', text: box ? box.textContent : null,
    exp: el.getAttribute('aria-expanded')});
  const before = seen(); el.click(); const open = seen(); box.click(); const shut = seen();
  el.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true})); const key = seen();
  return {before, open, shut, key, role: el.getAttribute('role'), tab: el.tabIndex, calls: window.calls.length,
    con: fwContrast(c)}; }"""


def test_a_tap_on_the_clock_stamp_shows_the_last_read_time():
    # review F8: phones have no hover; the clock card and the Details tile showed the HST time nowhere on a phone
    with _browser() as b:
        for scheme in ("light", "dark"):
            for tag, cfg, pilot in (("flight-watcher-clock-card-pilot2", {}, True),
                                    ("flight-watcher-clock-card", {"mode": "age"}, False),
                                    ("flight-watcher-clock-card", {}, False)):
                pg = _portal_page(b, [_card("clock-card", pilot=pilot)], width=390, scheme=scheme)
                g = pg.evaluate(TAP_JS, [tag, cfg, _clock(last="2026-11-10T09:30:00+00:00", pilot=pilot)])
                where = (tag, cfg, scheme)
                assert not g["before"]["shown"] and g["before"]["exp"] == "false", where
                assert g["open"]["shown"] and g["open"]["exp"] == "true", where
                assert g["open"]["text"].startswith("Last good read Nov 9 23:30:00 HST. Stale past 10 min 48 s"), where
                assert not g["shut"]["shown"] and g["key"]["shown"], where  # the box closes; Enter opens it too
                assert g["role"] == "button" and g["tab"] == 0 and g["calls"] == 0, where
                assert not g["con"]["fails"], (where, g["con"]["fails"])
                pg.context.close()


TILE_JS = """([tag, w, st]) => { const v = document.querySelector('.view'); v.innerHTML = ''; v.style.width = w + 'px';
  const c = mount(tag, {mode: 'age'}, st), hc = c.shadowRoot.querySelector('ha-card');
  const lines = [...c.shadowRoot.querySelectorAll('.lb, .v')].map((e) => Math.round(e.getBoundingClientRect().height));
  return {h: Math.round(hc.getBoundingClientRect().height * 10) / 10, text: c.shadowRoot.getElementById('age').textContent,
    lines, grid: c.getGridOptions ? c.getGridOptions() : null, wide: hc.scrollWidth - hc.clientWidth}; }"""


def test_the_details_tile_is_one_56_px_row_whatever_the_age():
    # review F4: the 6-column tile wrapped "very stale" and grew from 50 to 65 px next to 56 px tiles
    lasts = ["2026-11-10T11:27:00+00:00", "2026-11-10T11:18:00+00:00", "2026-11-10T11:10:00+00:00",
             "2026-11-10T10:10:00+00:00", "2026-11-10T09:25:00+00:00", "unknown", "unavailable"]
    with _browser() as b:
        for scheme in ("light", "dark"):
            pg = _portal_page(b, [_card("clock-card", pilot=False)], width=1024, scheme=scheme)
            pg.evaluate(HA_VARS_JS, (HA_DARK if scheme == "dark" else HA_LIGHT).split(";background")[0])
            for w in (166, 183):  # half of a 340 px section (HA desktop) and of a 374 px phone section
                got = [pg.evaluate(TILE_JS, ["flight-watcher-clock-card", w, _clock(last=x, pilot=False)]) for x in lasts]
                assert {g["h"] for g in got} == {56}, (w, scheme, got)
                assert all(g["lines"] == [20, 16] for g in got), (w, got)  # one line each: never wrapped
                assert all(g["wide"] <= 0 for g in got), (w, got)
                assert got[0]["grid"] == {"columns": 6, "rows": 1, "min_rows": 1}
            assert got[2]["text"] == "Data age 20 min, stale" and got[4]["text"] == "Data age 2 h 5 min, very stale"
            pg.context.close()


MODE_JS = """async (st) => { const errs = []; window.addEventListener('error', (e) => errs.push(String(e.message)));
  const c = mount('flight-watcher-clock-card', {mode: 'age'}, st), r = c.shadowRoot, look = () => ({
    st: (r.getElementById('st') || {}).textContent || null, buttons: r.querySelectorAll('button').length,
    stamp: (r.getElementById('age') || {}).textContent, grid: c.getGridOptions()});
  const a = look();
  c.setConfig({}); c.hass = mkHass(st); await new Promise((ok) => setTimeout(ok, 1300)); const b = look();
  const paused = JSON.parse(JSON.stringify(st)); paused['sensor.flight_watcher_state'].state = 'paused';
  c.setConfig({mode: 'age'}); c.hass = mkHass(paused); await new Promise((ok) => setTimeout(ok, 1300)); const d = look();
  c.setConfig({}); c.hass = mkHass(paused); const e = look();
  return {a, b, d, e, errs}; }"""


def test_a_mode_change_on_the_same_card_builds_it_again():
    # review F5 (cards): age to full threw a TypeError every second; full to age kept a frozen full card
    with _browser() as b:
        pg = _portal_page(b, [_card("clock-card", pilot=False)])
        g = pg.evaluate(MODE_JS, _clock(pilot=False))
    assert g["errs"] == [], g["errs"]
    assert g["a"]["st"] is None and g["a"]["buttons"] == 0 and g["a"]["grid"]["rows"] == 1
    assert g["b"]["st"] == "Watching." and g["b"]["buttons"] == 4 and g["b"]["grid"] == {}
    assert g["d"]["st"] is None and g["d"]["buttons"] == 0 and g["d"]["stamp"] == "Data age 3 min"
    assert g["e"]["st"] == "Paused."


# ---------------------------------------------------------------- the schedule card's header
def _sched(last="2026-11-10T11:27:00+00:00", nm="6", hs="30", hunt="off", pilot=True, updated="Nov 9, 2026 09:54:34",
           lc="2026-11-10T11:20:00+00:00"):
    st = _read()
    st["sensor.flight_watcher_schedule"]["attributes"]["updated"] = updated
    st.update({"sensor.flight_watcher_last_check": _s(last, lu=lc), "switch.flight_watcher_hunt_mode": _s(hunt, lu=OLD),
               "number.flight_watcher_hunt_check_every": _s(hs, {"min": 5, "max": 90}, lu=OLD),
               "number.flight_watcher_normal_check_every": _s(nm, {"min": 1, "max": 90}, lu=OLD)})
    return _pilot(st) if pilot else st


HEAD_JS = """([tag, st]) => { const c = mount(tag, {}, st); const r = c.shadowRoot;
  return new Promise((ok) => setTimeout(() => {
    const el = r.querySelector('.hd2 .ag[data-age]'), hd = r.querySelector('.hd2');
    const x = (q) => Math.round(r.querySelector(q).getBoundingClientRect().left);
    ok({text: el ? el.textContent : null, level: el ? el.dataset.age : null, title: el ? el.title : '',
        color: el ? getComputedStyle(el).color : '', head: hd.textContent, u: !!r.querySelector('.hd2 .u'),
        prev: x('.hd2 .nav[data-nav="-1"]'), now: x('.hd2 .nav.now'), h3: x('.hd2 h3'),
        con: fwContrast(c), fit: fwFits(c)}); }, 80)); }"""


def test_the_schedule_header_has_the_stamp_and_flica_time_only_on_hover():
    cases = {"fresh": ({}, "Data age 3 min", ""),
             "stale": ({"last": "2026-11-10T11:18:00+00:00"}, "Data age 12 min, stale", "amber"),
             "very stale": ({"last": "2026-11-10T11:05:00+00:00"}, "Data age 25 min, very stale", "red"),
             "unknown": ({"last": "unknown"}, "Data age unknown", ""),
             "offline": ({"last": "unavailable"}, "Data age over 10 min, Watcher offline", "red"),
             "hunt": ({"last": "2026-11-10T11:27:00+00:00", "hunt": "on"}, "Data age 3 min, very stale", "red"),
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
                    if name == "fresh":  # review F8: a tap shows the title, which has the last good read in HST now
                        assert "Last good read 01:27:00 HST. " + NORMAL_RULE in g["title"], where
                    pg.evaluate("() => { document.querySelector('.view').innerHTML = ''; }")
                pg.context.close()


def test_the_schedule_header_month_controls_stay_put_as_the_age_ticks():
    # review F3 (cards): on a wide header the arrows and Now slid 42 to 70 px as the stamp's width changed (and on a
    # 430 or 600 px screen too, where a short stamp fits beside them and a long one does not)
    lasts = ["2026-11-10T11:29:51+00:00", "2026-11-10T11:21:00+00:00", "2026-11-10T11:18:00+00:00",
             "2026-11-10T11:05:00+00:00", "2026-11-10T10:31:00+00:00", "unknown"]
    with _browser() as b:
        for width in (390, 430, 600, 1024, 1280):
            for pilot in (True, False):
                pg = _portal_page(b, [_card("schedule-card", pilot=pilot)], width=width)
                tag = "flight-watcher-schedule-card" + ("-pilot2" if pilot else "")
                got = []
                for last in lasts:
                    got.append(pg.evaluate(HEAD_JS, [tag, _sched(last=last, pilot=pilot)]))
                    pg.evaluate("() => { document.querySelector('.view').innerHTML = ''; }")
                pg.context.close()
                assert len({(g["prev"], g["h3"], g["now"]) for g in got}) == 1, (width, pilot, got)
                assert [g["text"] for g in got][2:5] == ["Data age 12 min, stale", "Data age 25 min, very stale",
                                                        "Data age 59 min, very stale"]


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
        pg.clock.run_for(391_000)
        got = pg.evaluate(SCHED_TICK_JS)
        assert got[:2] == ["Data age 11 min, stale", "amber"] and got[3] == "kept"  # ticked, the grid not redrawn
        assert pg.evaluate("window.N") == 0
        # hunting with 5 s (no schedule entity changed, so the card does not redraw): the hunt rule, at once
        st = _sched(last="2026-11-10T11:34:46+00:00", hunt="on", hs="5")
        pg.evaluate("(st) => { C.hass = mkHass(st); }", st)
        got = pg.evaluate(SCHED_TICK_JS)
        assert got[:2] == ["Data age 1 min, very stale", "red"] and got[3] == "kept" and pg.evaluate("window.N") == 0
        assert got[2].endswith(HUNT5_RULE)
        assert st[ns]["state"] == "5"
        pg.evaluate("() => { window.T = C._ageT; C.remove(); }")  # off the page: the tick stops
        assert pg.evaluate("C._ageT") is None


# ---------------------------------------------------------------- the portal: nothing new is exported
def test_a_pilots_portal_shows_the_stamp_from_what_it_already_has():
    for oid in ("state", "last_check", "next_check", "normal_check_every", "hunt_check_every", "hunt_mode"):
        assert roles.entity_on_portal(oid, "james"), oid
    names = sorted(cards.sources())
    # no new card for the stamp (1.7.14's near misses card, off the portal, came later)
    assert names == sorted(f"flight-watcher-{n}" for n in (
        "charters-card", "clock-card", "finds-card", "improved-card", "layover-card", "near-card", "pickers-card",
        "pilot-card", "pilot-search-card", "pilot-uploads-card", "pilotdb-card", "pot-card", "recall-card",
        "requests-card", "row-colors", "schedule-card", "settings-card", "tickets-card", "uploads-card", "working-card"))
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
    sec = readme[readme.index("## Applied on Pako 2026-11-18 about 08:04 HST (1.7.12): the Details view's data age stamp"):]
    sec = sec[:sec.index("\n## ", 5)]
    pako = "be03a0a48b9df66962e49a86c285921858768f5f97d27fda88288c26a0595435"  # Pako's dashboard before the patch
    assert sha in sec and pako in sec  # applied 2026-11-18: Pako read be03a0a4... before, the snapshot's sha after
    assert "Undo" in sec and "yes" in sec and '"mode": "age"' in sec
    assert "Pending on Pako" not in readme
    assert chr(0x2014) not in readme and chr(0x2014) not in text


def test_version_changelog_and_readme_say_data_age():
    # 1.7.13 to 1.7.20 went on top: the version itself is pinned in test_release_c_tickets; the 1.7.12 section stays
    # below them
    log = open(os.path.join(HERE, "CHANGELOG.md"), encoding="utf-8").read()
    assert log.startswith("# Changelog\n\n## 1.8.1\n")  # 1.8.1 on top, the chain below it
    for v in ("1.8.0", "1.7.26", "1.7.25", "1.7.24", "1.7.23", "1.7.22", "1.7.21", "1.7.20", "1.7.19", "1.7.18",
              "1.7.17", "1.7.16", "1.7.15", "1.7.14", "1.7.13", "1.7.12", "1.7.11"):
        assert f"\n## {v}\n" in log, v
    top = log.split("\n## 1.7.12\n", 1)[1].split("\n## 1.7.11\n", 1)[0]
    for word in ("Data age", "stale", "very stale", "FLICA updated", "Details", "hunt", "portal"):
        assert word in top, word
    readme = open(os.path.join(HERE, "README.md"), encoding="utf-8").read()
    assert "**Data age** (1.7.12" in readme and "FLICA updated" in readme
    for f in ("CHANGELOG.md", "README.md", "www/flight-watcher-clock-card.js", "www/flight-watcher-schedule-card.js",
              "tests/test_fw1712_data_age.py"):
        assert chr(0x2014) not in open(os.path.join(HERE, f), encoding="utf-8").read(), f
