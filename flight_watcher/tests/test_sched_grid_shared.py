"""1.7.7 (Ryan, Nov 14: "my schedule and other pilots schedule and reconstructed schedules should be exactly the same
style including this latest detail panel"): the month grid's look and the pairing detail panel live in one block of
code that every card drawing a month carries byte for byte (the cards load one file each, as ES modules, on Home
Assistant and on the portal, so a shared file would change the portal's card bundle). This keeps the copies equal,
in the cards and in every pilot's copy, and keeps the block free of anything a pilot copy or the portal rewrites."""
import re

import cards
import portal as PT

START = "// ---- shared schedule grid: keep identical in every card that holds it (tests/test_sched_grid_shared.py) ----\n"
END = "// ---- end shared schedule grid ----\n"


def block(text):
    """The shared block of a card's text (from its start marker to its end marker, both kept), or None."""
    if START not in text:
        return None
    i = text.index(START)
    j = text.index(END, i)
    return text[i:j + len(END)]


def test_the_schedule_card_holds_the_block_once():
    src = cards.sources()["flight-watcher-schedule-card"]
    assert src.count(START) == 1 and src.count(END) == 1 and block(src)
    assert src.index(END) < src.index("class FlightWatcherScheduleCard")  # defined before the card uses it


def test_every_copy_of_the_block_is_identical():
    """Every card in www/ that holds the block (the schedule card, and the pilot card once it draws its grid with it)
    holds the same text, and so does each pilot's copy and the portal's (FW_PORTAL on)."""
    ref = block(cards.sources()["flight-watcher-schedule-card"])
    holders = [n for n, t in cards.sources().items() if START in t]
    assert "flight-watcher-schedule-card" in holders
    built = cards.build("9.9.9", ["pilot2", "jane_doe"])
    for name in holders:
        assert block(cards.sources()[name]) == ref, name
        for who in ("pilot2", "jane_doe"):
            cp = built[f"{name}-{who}.js"]
            assert block(cp) == ref and block(PT.portal_card(cp)) == ref, (name, who)


def test_the_block_names_nothing_a_copy_rewrites():
    b = block(cards.sources()["flight-watcher-schedule-card"])
    assert "flight_watcher" not in b and "flight-watcher" not in b and "customElements" not in b
    assert not re.search(r"\bryan\b|\bpako\b", b, re.I) and not cards.DOH_RE.search(b)
    assert not re.search(r"\b(?:sensor|input_number|input_text|switch)\.", b)  # no entity ids: each card passes its own
    assert "FW_PORTAL" not in b and "\u2014" not in b
    # the panel's text goes through fwgEsc: no raw interpolation of a field in the HTML builders
    for fn in ("fwgPanelHtml", "fwgSheetHtml"):
        body = b[b.index(f"function {fn}("):]
        body = body[:body.index("\n}\n")]
        assert not re.search(r"\$\{(?:l|du|nx|t|m)\.(?!legs|duties|length|sum|dh|crew\.length)[a-z]+\}", body), fn
