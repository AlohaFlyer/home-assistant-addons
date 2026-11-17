"""1.7.11: the pilot schedule card (www/flight-watcher-pilot-card.js) for FW-0078 (the pick list: "Last, First" then
seat, base and employee number, escaped, wrapping at 390 px, 44 px targets; a pilot's entry still sends only its pick
id) and FW-0076 (the month buttons: this HST month and the next under the heading of a pilot's month, the shown one
pressed and not tappable, the other sends pilot/set with the same pilot and the month; "Loading Nov 2026..." while it
waits; the 2 s guard; light and dark; a portal that refuses the key says the month choice needs a portal update).
Rendered in Chromium with node Playwright on made-up replies ("Doe, Jane", 10001).

1.7.11 review: the page's clock is pinned to Nov 17, 2026, 10:00 HST (P2: the labels hold on any day); the refusal is
also run the way the portal's shell does it, a fresh card swapped in before the rejection, and the note is read on the
card on the page (P1); a refused tap goes again at once (P3); an employee number the shape refuses draws no buttons
(P4); a waiting reply to a month tap names and presses the month (P5); a month that did not read is named (F5); the
pressed month reads at 4.5:1 or more on any theme (P6)."""
import json
import os
import re
import shutil
import subprocess

import pytest

import cards
import portal as PT

HERE = os.path.dirname(os.path.abspath(__file__))
CARD = os.path.join(HERE, "..", "www", "flight-watcher-pilot-card.js")
SRC = open(CARD, encoding="utf-8").read()


def test_the_card_source_cleans_the_month_and_sends_no_number_as_a_pick():
    # the month goes through _clean with the shape's own pattern; data-emp is set only where no pick is
    assert "MONTH_RE" in SRC and "^[0-9]{4}-(0[1-9]|1[0-2])$" in SRC
    assert 'data-emp="${this._esc(m.pick ? "" : m.emp || "")}"' in SRC
    assert "month is not allowed" in SRC and "needs a portal update" in SRC
    assert chr(0x2014) not in SRC


@pytest.fixture(scope="module")
def rendered(tmp_path_factory):
    if not shutil.which("node"):
        pytest.skip("node not installed")
    if subprocess.run(["node", "-e", "require('playwright')"], capture_output=True).returncode:
        pytest.skip("node Playwright not installed")
    d = tmp_path_factory.mktemp("fw1711card")
    copy = d / "pc_james.js"
    copy.write_text(cards.pilot_copy(SRC, "james"))
    shots = os.environ.get("FW_SHOTS") or ""
    out = subprocess.run(["node", os.path.join(HERE, "fw1711_pilot_render.js"), CARD, str(copy), "james"] +
                         ([shots] if shots else []), capture_output=True, text=True, timeout=180)
    assert out.returncode == 0, out.stderr
    r = json.loads(out.stdout.strip().splitlines()[-1])
    if r.get("skip"):
        pytest.skip(r["skip"])
    return r


@pytest.mark.parametrize("who", ["admin", "pilot", "pilotDark"])
def test_the_pick_list_shows_name_seat_base_and_number(rendered, who):
    r = rendered[who]
    assert r["pkCount"] == 10
    assert r["pkLabels"][0] == "Doe, Ann · CA · #10001"  # no base: left out
    assert r["pkLabels"][1] == "Doe, Bea · FO · HNL · #10002"
    assert r["pkLabels"][9] == "Doe, <b>Jo</b> · FO · HNL · #10010" and r["markup"] == 0  # escaped
    assert r["pkMinH"] >= 44 and r["pkMinW"] >= 44 and r["pkMaxRight"] <= 390 and r["wide1"] <= 390


def test_a_pick_sends_the_pick_id_on_a_pilot_and_the_number_on_the_admin(rendered):
    assert [json.loads(x) for x in rendered["pilot"]["pickSent"]] == [{"pick": "a1b2c3d4e5f1", "name": "Doe, Bea"}]
    assert [json.loads(x) for x in rendered["admin"]["pickSent"]] == [{"emp": "10002", "name": "Doe, Bea"}]
    for who in ("admin", "pilot"):
        for x in rendered[who]["pickSent"]:
            PT.check_shape("pilot/set", x)


@pytest.mark.parametrize("who", ["admin", "pilot", "pilotDark"])
def test_the_month_buttons_under_the_heading(rendered, who):
    r = rendered[who]
    assert r["heading"] == "Doe, Bea (10002)" and r["underHeading"]
    assert r["mos"] == [{"t": "Nov 2026", "pressed": "false", "disabled": False},
                        {"t": "Dec 2026", "pressed": "true", "disabled": True}]
    assert r["moMinH"] >= 44 and r["moMinW"] >= 44 and r["wide2"] <= 390
    on, off = r["moColors"]["on"], r["moColors"]["off"]
    assert on[0] != on[1] and off[0] != off[1] and on != off  # readable, and the shown month looks pressed


def test_a_month_tap_sends_the_same_pilot_and_the_month_once(rendered):
    topic = {"admin": "flight_watcher/pilot/set", "pilot": "flight_watcher_james/pilot/set"}
    want = {"admin": {"emp": "10002", "name": "Doe, Bea", "month": "2026-11"},
            "pilot": {"pick": "a1b2c3d4e5f1", "name": "Doe, Bea", "month": "2026-11"}}
    for who in ("admin", "pilot"):
        r = rendered[who]
        assert r["sentShown"] == 0  # the shown month is not tappable
        assert [(t, json.loads(p)) for t, p in r["monthSent"]] == [(topic[who], want[who])]  # once: the 2 s guard
        PT.check_shape("pilot/set", r["monthSent"][0][1])
        assert re.search(r"Loading Nov 2026\.\.\.", r["loading"]), r["loading"]
        assert "Dec 2026" not in r["loading"].split("Loading")[0]


@pytest.mark.parametrize("who", ["admin", "pilot"])
def test_a_portal_that_refuses_the_month_says_it_needs_an_update(rendered, who):
    ref = rendered[who]["refused"]
    assert ref["sent"] == 1
    assert "The month choice needs a portal update" in ref["text"] and "Loading" not in ref["text"]
    assert "Doe, Bea (10002)" in ref["text"]  # the month shown stays


@pytest.mark.parametrize("who", ["admin", "pilot", "pilotDark"])
def test_the_note_shows_on_the_card_the_portals_shell_swaps_in(rendered, who):
    """P1 / R1: HOM's shell draws a fresh pilot card before the refusal reaches the one that sent the tap."""
    ref = rendered[who]["refused"]
    assert ref["swapped"] and ref["shellSent"] == 1
    assert "The month choice needs a portal update (Nov 2026 was not read)." in ref["shellText"], ref["shellText"]
    assert "December 2026" in ref["shellText"] and "Loading" not in ref["shellText"]
    assert "needs a portal update" not in ref["otherText"]  # another pilot shown: not his note


@pytest.mark.parametrize("who", ["admin", "pilot"])
def test_a_refused_tap_can_be_sent_again_at_once(rendered, who):
    """P3: the 2 s guard forgets a refused publish: the same tap again goes out, and the card never waits for nothing."""
    ref = rendered[who]["refused"]
    assert ref["retapSent"] == 2
    assert "needs a portal update" in ref["retapText"] and "Loading" not in ref["retapText"]
    assert ref["retapMos"] == [{"t": "Nov 2026", "disabled": False}, {"t": "Dec 2026", "disabled": True}]


@pytest.mark.parametrize("who", ["admin", "pilot"])
def test_the_clock_is_pinned_in_the_page(rendered, who):
    assert rendered[who]["clock"] == "2026-11-17T20"  # P2: the card reads the pinned day, not the real one


@pytest.mark.parametrize("who", ["admin", "pilot", "pilotDark"])
def test_a_waiting_month_tap_says_loading_that_month(rendered, who):
    r = rendered[who]
    assert "Loading Nov 2026... waiting: your Watcher is yielded" in r["waiting"], r["waiting"]
    assert r["waitMos"] == [{"t": "Nov 2026", "pressed": "true", "disabled": True},
                            {"t": "Dec 2026", "pressed": "false", "disabled": True}]


@pytest.mark.parametrize("who", ["admin", "pilot"])
def test_an_overdue_month_lookup_frees_the_buttons(rendered, who):
    """P3: once the wait is overdue the 'try again' it suggests can be done from the card."""
    r = rendered[who]
    assert "Still waiting after 60 min for Nov 2026:" in r["late"], r["late"]
    assert r["lateMos"] == [{"t": "Nov 2026", "pressed": "false", "disabled": False},
                            {"t": "Dec 2026", "pressed": "false", "disabled": False}]


@pytest.mark.parametrize("who", ["admin", "pilot"])
def test_a_month_that_did_not_read_is_named(rendered, who):
    r = rendered[who]
    assert "Dec 2026: not readable: ok no schedule" in r["unread"] and "Loading" not in r["unread"]
    assert [m["disabled"] for m in r["unreadMos"]] == [False, False]  # either month again


@pytest.mark.parametrize("who", ["admin", "pilot"])
def test_an_employee_number_the_shape_refuses_draws_no_month_buttons(rendered, who):
    r = rendered[who]
    assert r["eightMos"] == 0 and r["eightMonthMos"] == 0
    assert r["eightSent"] == 0 and "Loading" not in r["eightText"]


def _lum(rgb):
    def f(v):
        v /= 255
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (float(x) for x in re.findall(r"[\d.]+", rgb)[:3])
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


@pytest.mark.parametrize("who", ["admin", "pilot", "pilotDark"])
def test_the_pressed_month_reads_at_aa(rendered, who):
    """P6: white on #01579b, not the theme's primary pair (white on Home Assistant's #03a9f4 is 2.6:1, #009ac7 3.3:1)."""
    fg, bg = rendered[who]["moColors"]["on"]
    assert bg == "rgb(1, 87, 155)" and fg == "rgb(255, 255, 255)"
    a, b = sorted((_lum(fg), _lum(bg)))
    assert (b + 0.05) / (a + 0.05) >= 4.5
    assert "--primary-color" not in SRC.split('.mo[aria-pressed="true"]{')[1].split("}")[0]
