"""1.7.11 review: the schedule card's other joins of two months' items, for a trip across a month end (made-up X9607
Nov 30 to Dec 2) and for trips of the month before in the next month's view. Chromium, synthetic data only (made-up
pairings X9607, X9612, X9615, X9620, X9631, X9650, X9660; no crew names).

- Swap ideas: the trip a swap replaces is skipped by its trip and start. December's page (Schedule Lookup rows start
  in late November) lists X9607 at Nov 30 too, and that copy made every day of X9607 busy: no Ideas button at all.
- Release: a trip not in the viewed month's package ends on a day of its own (its start to its end). A November
  trip in the December view took the first HNL day on December's page (a later trip's return), which moved its
  release, the FAR-30/7 mid-trip test, the trip box, Legal next and the Ideas rest checks.
- Open clashes, the layover cell: from Dec 1 December is read on the mobile page, which starts at Dec 1 and gives
  the trip in progress no code day, so December's items do not hold X9607. The Open column's clash test and the
  layover cell read every month's items (each trip and start once), as the Watcher's schedule_fit does."""
from datetime import date, timedelta

import pytest

from test_fw171_cards import _card
from test_pairing_panel_card import TAG, _browser, _page

NOW = "2026-11-20T20:00:00Z"  # Nov 20 10:00 HST
COLS = ["id", "report", "dep", "release", "rel_days", "first_duty_min", "route", "credit", "tafb", "days", "block", "crew"]
OWNER = "{user: {id: 'o', name: 'O', is_admin: true, is_owner: true}}"


def _span(a, b):
    d, out = date.fromisoformat(a), []
    while d <= date.fromisoformat(b):
        out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _days(lay, a, b, off="-"):
    """A page's days [iso, trip, layover] from a to b; FLICA writes '-' on a day off."""
    return [[d, *lay.get(d, ("", off))] for d in _span(a, b)]


def _two(dep, arr, blk, dep2, arr2, blk2, stn):
    return [{"d": 0, "dep": dep, "arr": arr, "stn": stn, "blk": blk},
            {"d": 2, "dep": dep2, "arr": arr2, "stn": "HNL", "blk": blk2}]


def _s(st, a=None):
    return {"state": st, "attributes": a or {}, "last_updated": NOW, "last_changed": NOW}


def _states(months, own, offset, pot=None):
    st = {"sensor.flight_watcher_schedule": _s("ok", {"updated": "Nov 20, 2026", "months": months}),
          "sensor.flight_watcher_own_trip_times": _s(str(len(own)), {"count": len(own), "trips": own}),
          "input_number.flight_watcher_month_offset": _s(str(offset)),
          "sensor.flight_watcher_state": _s("watching", {"role": "admin", "doh": "2012-03-04"})}
    if pot is not None:
        st["sensor.flight_watcher_pot_count"] = _s(str(len(pot)), {"pairings": pot})
    return st


def _render(b, st, month, pkg=None, files=None, idea=None):
    """The admin's schedule card on st; month is the viewed month (its package loaded, or 404, first). idea: the day
    whose Ideas button is tapped. Returns {rows: {day: {cls, cells (text), html (inner HTML)}}, panel, errors}."""
    pg = _page(b, _card("schedule-card", pilot=False), 1600, 900, pkg=pkg, files=files)
    pg.clock.set_fixed_time(NOW)
    pg.evaluate("([tag, st]) => { window.C = mount(tag, {}, st, " + OWNER + "); }", [TAG, st])
    pg.wait_for_function(f"C._pk && C._pk['{month}'] !== null && C._pk['{month}'] !== undefined "
                         "&& C.shadowRoot && C.shadowRoot.querySelector('tr[data-d]')")
    pg.wait_for_timeout(300)
    if idea:
        pg.evaluate("([d]) => { const e = C.shadowRoot.querySelector(`.idb[data-d=\"${d}\"]`); if (e) e.click(); }", [idea])
        pg.wait_for_timeout(250)
    out = pg.evaluate("""() => { const r = C.shadowRoot, o = {rows: {}};
      for (const tr of r.querySelectorAll('tr[data-d]')) o.rows[tr.dataset.d] = {cls: tr.className,
        cells: [...tr.cells].map((c) => c.textContent.replace(/\\s+/g, ' ').trim()), html: [...tr.cells].map((c) => c.innerHTML),
        titles: [...tr.cells].map((c) => c.title || '')};
      const p = r.querySelector('.ipanel'); o.panel = p ? p.textContent.replace(/\\s+/g, ' ').trim() : ''; return o; }""")
    out["errors"] = pg.errors
    pg.context.close()
    return out


LAYOVER, FAR30, LEGAL, OPEN, IDEAS = 3, 10, 13, 14, 15  # the schedule table's columns

# ---------------------------------------------------------------- swap ideas for a trip on both months' pages
X9607 = {"trip": "X9607", "start": "2026-11-30", "end": "2026-12-02", "lay": "KIX"}
OWN_07 = {"X9607|2026-11-30": {"report": "12:45", "last_arr": "09:20", "blk": "17:35", "credit": "17:35", "seat": "FO",
                               "crew": [], "duties": _two(825, 1425, 600, 2985, 3440, 455, "KIX")}}
PKG_11 = {"cols": COLS, "start": "2026-11-01", "end": "2026-11-30", "rows": [
    ["X9631", "12:00", "1300", "09:00", 2, 600, "HNL-KIX-HNL", "19h00", "68h00", "26 27 28 29 30", "18h00", "CA01FO01"],
    ["X9607", "12:45", "1345", "09:35", 2, 600, "HNL-KIX-HNL", "17h35", "68h00", "30", "17h35", "CA01FO01"]]}
LAY_07 = {"2026-11-30": ("X9607", "KIX"), "2026-12-01": ("", "-"), "2026-12-02": ("", "HNL")}


@pytest.mark.parametrize("dec", ["copy", "none", "no December"])
def test_swap_ideas_for_a_trip_across_a_month_end_with_its_copy_on_the_next_page(dec):
    """Nov view: December's page also lists X9607 at Nov 30 (copy), does not (none), or no December is on file. The
    swap ideas are the same in all three: X9631 on Nov 28, 29 and 30 in the window, never all dropped as clashes."""
    months = {"2026-11": {"items": [dict(X9607)], "days": _days(LAY_07, "2026-11-01", "2026-11-30", ""),
                          "totals": {"block": "10:00", "credit": "10:00"}}}
    if dec != "no December":
        months["2026-12"] = {"items": [dict(X9607)] if dec == "copy" else [],
                             "days": _days(LAY_07, "2026-12-01", "2026-12-31", ""), "totals": {"block": "7:35", "credit": "7:35"}}
    with _browser() as b:
        r = _render(b, _states(months, OWN_07, 0), "2026-11", pkg=PKG_11, idea="2026-11-30")
    assert not r["errors"]
    cell = r["rows"]["2026-11-30"]["html"][IDEAS]
    assert 'class="idb' in cell and "3 in the package" in cell, f"no swap ideas for X9607 ({dec}): {cell!r}"
    assert r["panel"].startswith("Swap ideas for X9607 Nov 30"), r["panel"][:200]
    assert "X9631" in r["panel"], r["panel"][:400]
    for dates in ("Nov 28 - Nov 30", "Nov 29 - Dec 1", "Nov 30 - Dec 2"):
        assert dates in r["panel"], (dates, r["panel"][:400])


# ---------------------------------------------------------------- a November trip in the December view
LAY_N = {"2026-11-15": ("X9615", "SEA"), "2026-11-16": ("", "-"), "2026-11-17": ("", "HNL"),
         "2026-11-20": ("X9620", "SFO"), "2026-11-21": ("", "-"), "2026-11-22": ("", "HNL"),
         "2026-12-08": ("X9612", "SFO"), "2026-12-09": ("", "-"), "2026-12-10": ("", "HNL"), **LAY_07}
IT = {"X9615": {"trip": "X9615", "start": "2026-11-15", "end": "2026-11-17", "lay": "SEA"},
      "X9620": {"trip": "X9620", "start": "2026-11-20", "end": "2026-11-22", "lay": "SFO"},
      "X9607": X9607,
      "X9612": {"trip": "X9612", "start": "2026-12-08", "end": "2026-12-10", "lay": "SFO"}}
OWN_N = {"X9615|2026-11-15": {"report": "09:00", "last_arr": "19:00", "blk": "20:00", "credit": "20:00", "seat": "FO",
                              "crew": [], "duties": _two(600, 1200, 600, 3420, 4020, 600, "SEA")},
         "X9620|2026-11-20": {"report": "09:00", "last_arr": "19:00", "blk": "20:00", "credit": "20:00", "seat": "FO",
                              "crew": [], "duties": _two(600, 1200, 600, 3420, 4020, 600, "SFO")},
         "X9612|2026-12-08": {"report": "09:00", "last_arr": "18:00", "blk": "18:00", "credit": "18:00", "seat": "FO",
                              "crew": [], "duties": _two(600, 1140, 540, 3420, 3960, 540, "SFO")},
         **OWN_07}
PKG_12 = {"cols": COLS, "start": "2026-12-01", "end": "2026-12-31", "rows": [
    ["X9660", "08:00", "0900", "18:00", 0, 600, "HNL-LAX-HNL", "10h00", "10h00", "3", "9h00", "CA01FO01"]]}


def _months(nov, dec, dec_from="2026-12-01"):
    """November's mobile page runs to Dec 2 (as FLICA's does); December's starts at dec_from."""
    return {"2026-11": {"items": [dict(IT[t]) for t in nov], "days": _days(LAY_N, "2026-11-01", "2026-12-02"),
                        "totals": {"block": "40:00", "credit": "40:00"}},
            "2026-12": {"items": [dict(IT[t]) for t in dec], "days": _days(LAY_N, dec_from, "2026-12-31"),
                        "totals": {"block": "18:00", "credit": "18:00"}}}


@pytest.mark.parametrize("read", ["X9612 read", "X9612 not read"])
def test_a_november_trip_keeps_its_own_release_in_the_december_view(read):
    """X9620 Nov 20 to 22 (home 19:00) and X9612 Dec 8 to 10. In the Dec view X9620 is released on Nov 22, not on
    X9612's Dec 10: the open days Dec 1 to 7 are no mid-trip days, get no trip box, and Dec 10 gets no release or
    Legal next of the November trip."""
    own = {k: v for k, v in OWN_N.items() if k.startswith(("X9620", "X9612"))}
    if read == "X9612 not read":
        own.pop("X9612|2026-12-08")
    with _browser() as b:
        r = _render(b, _states(_months(["X9620"], ["X9612"]), own, 1), "2026-12", files={"2026-12": {"cols": COLS, "rows": []}})
    assert not r["errors"]
    rows = r["rows"]
    for d in ("2026-12-01", "2026-12-03", "2026-12-05", "2026-12-07"):
        assert not rows[d]["titles"][FAR30].startswith("Mid-trip"), (d, rows[d]["titles"][FAR30])
        assert " bx" not in f" {rows[d]['cls']}", (d, rows[d]["cls"])
    assert "bxs" in rows["2026-12-08"]["cls"].split()
    if read == "X9612 not read":
        assert "Rel 19:15" not in rows["2026-12-10"]["cells"][LAYOVER], rows["2026-12-10"]["cells"][LAYOVER]
        assert rows["2026-12-10"]["cells"][LEGAL] == "", rows["2026-12-10"]["cells"][LEGAL]
    else:
        assert "Rel 18:15" in rows["2026-12-10"]["cells"][LAYOVER]


@pytest.mark.parametrize("home", ["19:00", "22:45"])
def test_a_december_pick_up_measures_rest_from_the_last_release(home):
    """X9615 Nov 15 to 17, X9607 Nov 30 to Dec 2 (released 09:35 Dec 2), X9612 Dec 8 to 10; a December package
    pick-up X9660 on Dec 3 reporting 08:00. Its rest before is 22:25 from X9607 (PWA 10.E.1.a needs 11 h), whatever
    time X9615 came home on Nov 17: a November trip is never released on Dec 2."""
    own = {k: (dict(v, last_arr=home) if k.startswith("X9615") else v) for k, v in OWN_N.items() if not k.startswith("X9620")}
    with _browser() as b:
        r = _render(b, _states(_months(["X9615", "X9607"], ["X9612"]), own, 1), "2026-12", files={"2026-12": PKG_12},
                    idea="2026-12-03")
    assert not r["errors"]
    assert 'class="idb' in r["rows"]["2026-12-03"]["html"][IDEAS], "the legal pick-up on Dec 3 is not offered"
    assert "X9660" in r["panel"] and "22:25 rest before" in r["panel"], r["panel"][:400]
    assert r["rows"]["2026-12-02"]["cells"][LEGAL].startswith("20:35"), r["rows"]["2026-12-02"]["cells"][LEGAL]


# ---------------------------------------------------------------- Open clashes on the December mobile page
@pytest.mark.parametrize("dec_from", ["2026-12-01", "2026-11-29"])
def test_the_trip_in_progress_from_november_clashes_in_the_december_open_column(dec_from):
    """Dec view, an open-time pairing X9650 Dec 1 to 2 against X9607 Nov 30 to Dec 2. December's page starts at Dec 1
    (the mobile page: no X9607 there) or at Nov 29 (Schedule Lookup: X9607 listed at Nov 30). Both say it clashes,
    as the Watcher's schedule_fit does, and the Dec 1 and Dec 2 layover cells carry the trip."""
    pot = [{"pairing": "X9650", "start": "01Dec", "end": "02Dec", "layover": "LAX"}]
    dec = ["X9607"] if dec_from < "2026-11-30" else []
    with _browser() as b:
        r = _render(b, _states(_months(["X9607"], dec, dec_from), OWN_07, 1, pot=pot), "2026-12",
                    files={"2026-12": {"cols": COLS, "rows": []}})
    assert not r["errors"]
    rows = r["rows"]
    assert '<span class="clash" title="clashes with X9607">LAX(X9650)</span>' in rows["2026-12-01"]["html"][OPEN], \
        rows["2026-12-01"]["html"][OPEN]
    assert rows["2026-12-01"]["cells"][LAYOVER] == "-", rows["2026-12-01"]["cells"][LAYOVER]
    assert 'class="tag lay"' in rows["2026-12-01"]["html"][LAYOVER] and 'class="tag lay"' in rows["2026-12-02"]["html"][LAYOVER]
