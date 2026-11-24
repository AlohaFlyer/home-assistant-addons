"""1.8.2 (C3): the pot sensor's row cap with two pots. With the Pot month select on Both (Ryan: November's pot 003.152
and December's 003.153 on Nov 23), the check lists this month's rows first and the next month's after. The sensor
(sensor.<prefix>_pot_count, pot/state) carries at most 60 rows and at most ATTR_MAX bytes; it used to keep flat[:60]
and cap_attrs cut 'pairings' from the end, so December's rows (the month Ryan trades) were the ones cut, and the pot
card counted the rows it got, never the sensor's count. Now each bid month read keeps a fair share (rows taken in turn,
soonest first, close-in trips before all), the rows go out by bid month then start date, "trimmed" says how many are
left out, and the pot card shows the sensor's count and "N not shown". No FLICA page load is added. Synthetic only:
made-up pairings H39xx, "Doe, Jane"."""
import json
import os

import pytest

from test_fw171_cards import P as PILOT2, _browser, _card, _page as _portal_page, _pilot, _s, _sched_states
import test_fw181_pot_month as PM
from test_fw181_pot_month import _check, _w, at, page
from test_layover_card import HA_DARK, HA_LIGHT
from test_release_a_cards import POT as POT_ROWS
from test_release_a_flica import mk, real_fl  # noqa: F401

import cards

SHOTS = os.environ.get("FW_C3_SHOTS", "")  # a folder: the pot card renders are saved there as c3_*.png
MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def row(p, s, e, m, **kw):
    """A pot row the size of a live one (crew, detail URL, captain): about 500 bytes on the sensor."""
    r = {"pairing": p, "start": s, "end": e, "credit": "11:56", "layover": "LAX", "depart": "12:08", "arrive": "14:17",
         "days": "2", "prem": "", "dates": f"{s}-{e}", "blk": "11:12", "report": "11:08",
         "captain": "Doe, Jane (10001)", "tafb": "27:24", "soft": "0:44", "turn": "OGG/LAX", "route": "HNL-OGG-LAX-HNL",
         "open_seats": "FO", "crew": [["CA", "Doe, Jane"], ["FO", "OPEN"]],
         "detail_url": f"https://example.invalid/full/mobilepairing.cgi?PID={p}&DATE=2026{s}&FROM=MobileOpentimePot",
         "fit": "Fits", "far": "OK", "month": m}
    r.update(kw)
    return r


def nov(n):
    return [row(f"H39{i:02d}", f"{15 + i % 15:02d}Nov", f"{16 + i % 15:02d}Nov", "2026-11") for i in range(n)]


def dec(n):
    return [row(f"H39{50 + i:02d}", f"{2 + i % 29:02d}Dec", f"{3 + i % 29:02d}Dec", "2026-12") for i in range(n)]


def _iso(r):
    """'16Nov' in its bid month's year (a January row of '31Dec' is the December before)."""
    d, mo = int(r["start"][:2]), MON.index(r["start"][2:5]) + 1
    y, mm = (int(x) for x in r["month"].split("-")) if r.get("month", "")[:2] == "20" else (2026, mo)
    y += -1 if mo - mm > 6 else 1 if mm - mo > 6 else 0
    return f"{y:04d}-{mo:02d}-{d:02d}"


def _months(out):
    got = {}
    for r in out["pairings"]:
        got[r["month"]] = got.get(r["month"], 0) + 1
    return got


def _fair(out, totals):
    """No month cut out while another keeps more of its rows: a month that lost rows keeps at least as many as any
    other month, less one (the rows are taken in turn)."""
    kept = _months(out)
    for m, n in totals.items():
        if kept.get(m, 0) < n:
            assert all(kept.get(m, 0) >= kept.get(o, 0) - 1 for o in totals if o != m), (kept, totals)


def _order(out):
    """Close-in trips first, then by bid month, then start date (and pairing)."""
    keys = [(r.get("src") != "C", r["month"], _iso(r), r["pairing"]) for r in out["pairings"]]
    assert keys == sorted(keys), keys


# ---------------------------------------------------------------- the Watcher: publish_pot
@pytest.mark.parametrize("nn,nd", [(15, 30), (30, 15), (8, 20), (2, 20)])
def test_both_months_keep_a_fair_share_of_the_pot_sensor(mk, nn, nd):
    """The audit's probe sizes: 15 November rows and 30 December rows (23 fit) kept 15 and 8 (December cut by 22);
    each month now keeps its share, both ways round. 2 + 20 all fit, as before."""
    W = mk("", t=at(2026, 11, 23))
    flat = list(reversed(nov(nn))) + dec(nd)  # the check's order: this month's rows, then next month's (page order)
    W.publish_pot(flat)
    out = W.MQ.last(f"{W.T}/pot/state")
    assert W.attr_size(out) <= W.ATTR_MAX and out["count"] == nn + nd
    kept = len(out["pairings"])
    assert out.get("trimmed", 0) == nn + nd - kept
    _fair(out, {"2026-11": nn, "2026-12": nd})
    _order(out)
    if nn + nd <= 22:
        assert kept == nn + nd and "trimmed" not in out


def test_the_row_cap_is_shared_too_and_counted(mk):
    """Small rows: 50 + 50 fit the bytes but not the 60 row cap. 1.8.0 kept November's 50 and December's first 10, with
    no "trimmed"; now 30 and 30, and "trimmed" counts the 40 left out (count stays the whole pot)."""
    W = mk("", t=at(2026, 11, 23))
    small = lambda r: {k: r[k] for k in ("pairing", "start", "end", "month")}  # noqa: E731
    flat = [small(r) for r in nov(15) * 3 + nov(5)] + [small(r) for r in dec(25) * 2]
    for i, r in enumerate(flat):
        r["pairing"] = f"H39{i % 100:02d}"
    W.publish_pot(flat)
    out = W.MQ.last(f"{W.T}/pot/state")
    assert out["count"] == 100 and len(out["pairings"]) == 60 and out["trimmed"] == 40
    assert _months(out) == {"2026-11": 30, "2026-12": 30}
    _order(out)


def test_close_in_trips_stay_first_and_the_edge_days_sort_in_their_bid_month(mk):
    """A close-in trip (under 16 h to report, FW-0034) is always kept and first; November's Dec 1 trip sorts after its
    30Nov (its bid month runs Nov 1 to Dec 1) and January's 31Dec before its 04Jan."""
    W = mk("", t=at(2026, 11, 30, 20))
    ci = row("H3999", "01Dec", "01Dec", W.CLOSE_IN_KEY, src="C", folder="close-in")
    edge = [row("H3998", "01Dec", "02Dec", "2026-11"), row("H3997", "30Nov", "01Dec", "2026-11")]
    jan = [row("H3996", "04Jan", "05Jan", "2027-01"), row("H3995", "31Dec", "01Jan", "2027-01")]
    flat = [ci] + jan + edge + dec(40)
    W.publish_pot(flat)
    out = W.MQ.last(f"{W.T}/pot/state")
    got = [(r["month"], r["pairing"]) for r in out["pairings"]]
    assert got[0] == (W.CLOSE_IN_KEY, "H3999")
    assert got[1:3] == [("2026-11", "H3997"), ("2026-11", "H3998")]
    assert got[-2:] == [("2027-01", "H3995"), ("2027-01", "H3996")]
    assert out["trimmed"] == len(flat) - len(got) and W.attr_size(out) <= W.ATTR_MAX


def test_a_check_on_both_publishes_both_months(mk):
    """Through the check (Ryan, Both, Nov 23): November's page and December's page of 40 trips each; the sensor keeps
    as many of each, with "trimmed" and the whole count."""
    nv = [(f"H39{i:02d}", f"{16 + i % 15:02d}Nov") for i in range(40)]
    dc = [(f"H39{40 + i:02d}", f"{3 + i % 28:02d}Dec") for i in range(40)]
    W, fl, pages = _w(mk, at(2026, 11, 23), "Both", {"003.152": page(nv), "003.153": page(dc)})
    assert _check(W, fl) == ("ok", ["003.152", "003.153"])
    out = W.MQ.last(f"{W.T}/pot/state")
    assert out["count"] == 80 and out["trimmed"] == 80 - len(out["pairings"]) > 0
    n = _months(out)
    assert abs(n["2026-11"] - n["2026-12"]) <= 1 and W.attr_size(out) <= W.ATTR_MAX, n
    _order(out)


def test_a_pilot_on_this_month_keeps_the_soonest_trips_in_date_order(mk):
    """James (a pilot instance, This month): one month, its 70 trips listed by start date; the 60 row cap keeps the
    soonest, and "trimmed" says 10 are left out. His sensor is his own (his prefix)."""
    nv = [(f"H39{i:02d}", f"{30 - i % 15:02d}Nov") for i in range(70)]
    W = mk("james", t=at(2026, 11, 23))
    for f in PM.STUBS:
        setattr(W, f, lambda *a, **k: None)
    W.close_in_check = lambda *a, **k: ({}, "ok")
    W.crew_index_check = lambda *a, **k: "ok"
    W.S["pot_urls"] = {}
    pages = {"003.152": page(nv)}
    other = "<html><body>x</body></html>"
    fl = real_fl(W, lambda u: pages.get(W.bcid(u), PM.NOT_OPEN) if "opentimepot" in u else other)
    assert W.T == "flight_watcher_james" and W.pot_mode() == "This month"
    assert _check(W, fl) == ("ok", ["003.152"])
    out = W.MQ.last(f"{W.T}/pot/state")
    assert out["count"] == 70 and len(out["pairings"]) + out["trimmed"] == 70 and out["trimmed"] >= 10
    _order(out)
    starts = [_iso(r) for r in out["pairings"]]
    assert starts[0] == "2026-11-16" and starts == sorted(starts)


def test_the_size_stays_under_the_cap_and_nothing_is_cut_after(mk):
    """The payload publish_pot builds is already at or under ATTR_MAX, so cap_attrs passes it as it is (the fair
    share is never undone by a cut from the end). 1.8.2 (C3 review T1): the payload is caught as publish_pot hands it
    to pub(), before cap_attrs (the one MQ.last holds has been through cap_attrs already, so it could never fail)."""
    W = mk("", t=at(2026, 11, 23))
    seen, cap = [], W.cap_attrs
    W.cap_attrs = lambda topic, payload: (seen.append((topic, json.loads(json.dumps(payload)))), cap(topic, payload))[1]
    flat = nov(30) + dec(30)
    W.publish_pot(flat)
    (sent,) = [p for t, p in seen if t == "pot/state"]
    assert W.attr_size(sent) <= W.ATTR_MAX, (W.attr_size(sent), len(sent["pairings"]))
    assert cap("pot/state", sent) == sent  # nothing cut from the end, no "trimmed" added or changed
    assert W.MQ.last(f"{W.T}/pot/state") == sent and sent["trimmed"] == 60 - len(sent["pairings"])


# ---------------------------------------------------------------- the pot card: the sensor's count and "N not shown"
def _states(n_pot, rows, trimmed=True, tb=()):
    a = {"count": n_pot, "pairings": rows}
    if trimmed and n_pot > len(rows):
        a["trimmed"] = n_pot - len(rows)
    return _pilot({"sensor.flight_watcher_pot_count": _s(str(n_pot), a),
                   "sensor.flight_watcher_tradeboard_pickups": _s(str(len(tb)), {"count": len(tb),
                                                                                  "pairings": list(tb)}),
                   "sensor.flight_watcher_last_check": _s("2026-11-10T11:29:00+00:00"),
                   "sensor.flight_watcher_state": _s("hunting", {"role": "pilot", "doh": "2016-03-02"}),
                   "input_number.flight_watcher_longevity_year": _s("5")})


def _rows():
    """12 November and 12 December rows as the sensor carries them (a fair share of 15 + 30)."""
    W_rows = [r for r in sorted(nov(15), key=_iso)[:12]] + [r for r in sorted(dec(30), key=_iso)[:12]]
    return [{k: v for k, v in r.items() if k not in ("crew", "detail_url")} for r in W_rows]


TB = [{"pairing": "H3990", "start": "05Dec", "end": "06Dec", "dates": "05Dec-06Dec", "days": "2", "layover": "SFO",
       "credit": "12:00", "soft": "2:00", "fit": "Fits", "far": "OK", "vac": False, "blocked": False, "src": "T"}]

READ_JS = """(st) => { const c = mount('%s', {}, st); const r = c.shadowRoot;
  const t = (q) => { const e = r.querySelector(q); return e ? e.textContent.replace(/\\s+/g, ' ').trim() : null; };
  return {head: t('.hd .k'), more: t('.more'), rows: r.querySelectorAll('.r').length, fit: fwFits(c),
          contrast: fwContrast(c), text: r.textContent.replace(/\\s+/g, ' ')}; }"""


def _shot(pg, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        pg.screenshot(path=os.path.join(SHOTS, f"c3_{name}.png"), full_page=True)


@pytest.mark.parametrize("width,scheme", [(390, "light"), (320, "dark")])
def test_the_portal_pot_card_shows_the_count_and_how_many_are_not_shown(width, scheme):
    """James's portal: 45 pot trips, 24 on the sensor (12 of November's 15, 12 of December's 30), one Tradeboard
    pickup. The header gives the sensor's count (45), the line under the list "21 not shown" and why; it fits the
    phone width with no sideways scroll and keeps WCAG AA contrast, light and dark."""
    rows = _rows()
    with _browser() as b:
        pg = _portal_page(b, [_card("pot-card")], width=width, scheme=scheme)
        got = pg.evaluate(READ_JS % "flight-watcher-pot-card-pilot2", _states(45, rows, tb=TB))
        _shot(pg, f"portal_{width}_{scheme}")
        old = _portal_page(b, [_card("pot-card")], width=width, scheme=scheme).evaluate(
            READ_JS % "flight-watcher-pot-card-pilot2", _states(45, rows, trimmed=False, tb=TB))
        whole = _portal_page(b, [_card("pot-card")], width=width, scheme=scheme).evaluate(
            READ_JS % "flight-watcher-pot-card-pilot2", _states(len(rows), rows, tb=TB))
    assert got["head"].startswith("45 in the pot") and "21 not shown" in got["head"], got["head"]
    assert got["more"].startswith("21 not shown:") and "24 of the 45" in got["more"], got["more"]
    assert "\u2014" not in got["text"] and "\u2013" not in got["text"]
    assert got["rows"] == 25  # the 24 pot rows and the Tradeboard post
    assert got["fit"]["page"] <= width and got["fit"]["inner"] <= 0 and got["fit"]["right"] <= width, got["fit"]
    assert got["contrast"]["fails"] == [], got["contrast"]["fails"]
    # an older Watcher (no "trimmed", only count over the rows it sent): the same words from the count
    assert "21 not shown" in old["head"] and old["more"].startswith("21 not shown:")
    # nothing left out: no "not shown" at all
    assert whole["head"].startswith("24 in the pot") and whole["more"] is None and "not shown" not in whole["text"]


def test_the_pot_card_with_no_row_on_the_sensor_never_says_the_pot_is_empty():
    """1.8.2 (C3 review T2): the pot has 45 trips but none is on the sensor (count 45, pairings []) and no Tradeboard
    pickup: the card gives the count and "45 not shown", never "The open time pot is empty"."""
    with _browser() as b:
        got = _portal_page(b, [_card("pot-card")]).evaluate(READ_JS % "flight-watcher-pot-card-pilot2",
                                                            _states(45, [], tb=()))
    assert got["head"].startswith("45 in the pot, 45 not shown"), got["head"]
    assert got["more"].startswith("45 not shown:"), got["more"]
    assert "pot is empty" not in got["text"] and got["rows"] == 0, got["text"]


@pytest.mark.parametrize("theme,name,width", [(HA_LIGHT, "light", 390), (HA_DARK, "dark", 320)])
def test_the_admins_pot_card_shows_the_count_and_not_shown_on_home_assistants_theme(theme, name, width):
    """Ryan's own copy (Home Assistant), HA's light theme at 390 px and dark at 320 px."""
    src = cards.build("9.9.9")["flight-watcher-pot-card.js"]
    st = {k.replace("flight_watcher_pilot2_", "flight_watcher_", 1): v for k, v in _states(45, _rows(), tb=TB).items()}
    html = ("<!doctype html><html><head><meta charset='utf-8'><style>body{margin:0;padding:8px 16px;"
            f"font-family:Roboto,sans-serif;{theme}}}</style></head><body><script>"
            "customElements.define('ha-card', class extends HTMLElement { constructor() { super(); "
            "this.attachShadow({mode: 'open'}).innerHTML = '<style>:host{display:block;"
            "background:var(--card-background-color);border-radius:12px}</style><slot></slot>'; } });</script><script>"
            + src + "</script><script>"
            "const c = document.createElement('flight-watcher-pot-card'); c.setConfig({});"
            " document.body.appendChild(c);"
            f"c.hass = {{states: {json.dumps(st)}, themes: {{darkMode: {'true' if name == 'dark' else 'false'}}},"
            " callService: () => {}};</script></body></html>")
    with _browser() as b:
        pg = b.new_page(viewport={"width": width, "height": 900})
        pg.set_content(html)
        got = pg.evaluate("""() => { const c = document.querySelector('flight-watcher-pot-card'), r = c.shadowRoot;
          const t = (q) => { const e = r.querySelector(q);
            return e ? e.textContent.replace(/\\s+/g, ' ').trim() : null; };
          const m = r.querySelector('.more');
          return {head: t('.hd .k'), more: t('.more'), color: m && getComputedStyle(m).color,
                  wide: document.documentElement.scrollWidth}; }""")
        _shot(pg, f"ha_{width}_{name}")
    assert got["head"].startswith("45 in the pot") and "21 not shown" in got["head"]
    assert got["more"].startswith("21 not shown:") and got["wide"] <= width
    assert got["color"] == ("rgb(155, 155, 155)" if name == "dark" else "rgb(114, 114, 114)")  # secondary text


# ---------------------------------------------------------------- the schedule card: its Open column says the cut
SCHED_JS = """([tag, st]) => { const c = mount(tag, {}, st);
  return new Promise((ok) => setTimeout(() => { const r = c.shadowRoot, e = r.querySelector('.pcut');
    ok({cut: e ? e.textContent.replace(/\\s+/g, ' ').trim() : null, fit: fwFits(c), contrast: fwContrast(c),
        open: [...r.querySelectorAll('tr[data-d]')].map((tr) => tr.cells[14] && tr.cells[14].textContent.trim())
          .filter((x) => x), text: r.textContent}); }, 80)); }"""


def _sched(a, admin=False):
    """The schedule card's states (the portal's pilot2, or the admin's own ids) with the pot sensor's attributes a."""
    st = _sched_states()
    st[f"sensor.{PILOT2}_pot_count"] = _s(str(a.get("count", len(a["pairings"]))), a)
    return {k.replace(PILOT2 + "_", "flight_watcher_", 1): v for k, v in st.items()} if admin else st


@pytest.mark.parametrize("width,scheme", [(390, "light"), (390, "dark"), (1100, "light")])
def test_the_schedule_cards_open_column_says_how_many_pot_trips_are_not_shown(width, scheme):
    """1.8.2 (C3-R1): the schedule card (on the admin's Home Assistant Watcher view and on a pilot's portal) draws the
    Open column and the Ideas' O marks from the pot sensor's rows. With two pots it carries a fair share of each
    month, so a line under the totals says how many pot trips are not shown there and that the Watcher still watches
    all of them; an older Watcher's payload (count, no "trimmed") gives the same line; none when nothing is cut."""
    cut = {"count": 45, "pairings": POT_ROWS, "trimmed": 43}
    with _browser() as b:
        got = {}
        for name, tag, st in (
                ("portal", "flight-watcher-schedule-card-pilot2", _sched(cut)),
                ("admin", "flight-watcher-schedule-card", _sched(cut, admin=True)),
                ("old", "flight-watcher-schedule-card-pilot2", _sched({"count": 45, "pairings": POT_ROWS})),
                ("whole", "flight-watcher-schedule-card-pilot2", _sched({"count": 2, "pairings": POT_ROWS})),
                ("180", "flight-watcher-schedule-card", _sched({"pairings": POT_ROWS}, admin=True))):
            pg = _portal_page(b, [_card("schedule-card", pilot=name not in ("admin", "180"))], width=width,
                              scheme=scheme)
            got[name] = pg.evaluate(SCHED_JS, [tag, st])
            if name == "portal":
                _shot(pg, f"sched_{width}_{scheme}")
            pg.context.close()
    want = ("43 of the 45 pot trips are not in the Open column or the Ideas' O marks: the sensor carries 2 (all Home "
            "Assistant keeps; each bid month gets a fair share, soonest first). The Watcher still reads and watches "
            "all 45.")
    for name in ("portal", "admin", "old"):
        g = got[name]
        assert g["cut"] == want, (name, g["cut"])
        assert chr(0x2014) not in g["cut"] and chr(0x2013) not in g["cut"]
        assert g["fit"]["page"] <= width and g["fit"]["right"] <= width, (name, g["fit"])
        assert g["contrast"]["fails"] == [], (name, g["contrast"]["fails"])
    assert got["portal"]["open"] == got["whole"]["open"] != []  # the rows it has are drawn as before
    assert got["whole"]["cut"] is None and got["180"]["cut"] is None  # nothing cut, or 1.8.0's payload: no line


def test_no_em_dash_and_short_lines_in_the_change():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for f in ("tests/test_fw181_pot_cap.py",):
        text = open(os.path.join(here, f), encoding="utf-8").read()
        assert "\u2014" not in text and all(len(x) <= 120 for x in text.splitlines()), f
    # 1.8.2 (C3-R1): the schedule card's new lines (the card's older lines are longer; these are not)
    sched = open(os.path.join(here, "www", "flight-watcher-schedule-card.js"), encoding="utf-8").read().splitlines()
    new = [x for x in sched if "potCut" in x or "potOff" in x or "potN" in x or "(C3-R1)" in x
           or "Ideas' O marks" in x]
    assert len(new) >= 8 and all(len(x) <= 120 and chr(0x2014) not in x for x in new), new
