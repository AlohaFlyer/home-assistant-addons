"""1.8.2: the cards' months follow HST and the bid period (C4, C10, P8, S11, C5, C7, C9 of the transition audit).

Hawaiian's bid periods are not calendar months: November runs Nov 1 to Dec 1, December Dec 2 to Dec 31 (the schedule
sensor's periods, the Watcher's bid_bounds). The schedule card took its month from the device's own clock and time
zone (new Date()) and the calendar month: a phone on Japan time changed month up to 19 h early, and on Dec 1 the card
opened December, where a trip carried across from November has no code day and no in-flight mark. Now the month the
offset (input_number.flight_watcher_month_offset) counts from is the bid month that holds today in HST: November on
Dec 1, December from Dec 2. The faded "other month" rows are the days outside the bid period the totals cover (Dec 1
plain on November's page, faded on December's), the calendar month only when no bid period is known. The recall card
moves on with the clock unless the month was picked with its arrows, and the pilot card offers the bid month of today
and the next (on Dec 1: November and December).

Rendered in Chromium (Python Playwright) with a fixed fake clock: Honolulu, and a phone on Japan time (UTC+9) at Nov 30
22:00 HST. Made-up pairings H39xx and names ("Doe, Jane"); FLICA is never reached. FW182_SHOTS=<dir> saves screenshots
(390 px light, 320 px dark, Nov 30, Dec 1 and Dec 2)."""
import json
import os
from datetime import datetime

import pytest

import cards
from test_release_a_lookup import load  # noqa: F401  (a pilot's or the admin's Watcher with files on hand)

WWW = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "www")
SHOTS = os.environ.get("FW182_SHOTS") or ""
PAGE = ("<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width'><style>"
        ":root{%s}body{margin:0;padding:8px;background:var(--primary-background-color);"
        "color:var(--primary-text-color);font-family:Roboto,sans-serif}</style></head><body><script>"
        "customElements.define('ha-card', class extends HTMLElement { constructor() { super();"
        " this.attachShadow({mode: 'open'}).innerHTML = '<style>:host{display:block;"
        "background:var(--card-background-color);border-radius:12px;padding:8px}</style><slot></slot>'; } });"
        "window.calls = []; window.sent = [];</script><script>%s</script></body></html>")
LIGHT = ("--primary-background-color:#fafafa;--card-background-color:#fff;--primary-text-color:#212121;"
         "--secondary-text-color:#555;--divider-color:#ccc;--primary-color:#03a9f4")
DARK = ("--primary-background-color:#111;--card-background-color:#1c1c1c;--primary-text-color:#e1e1e1;"
        "--secondary-text-color:#9b9b9b;--divider-color:#444;--primary-color:#03a9f4")
HNL, JST = "Pacific/Honolulu", "Asia/Tokyo"
# HST = UTC - 10 h
NOV30_22 = "2026-12-01T08:00:00Z"  # Nov 30 22:00 HST (Dec 1 17:00 on a phone set to Japan time)
NOV30_23 = "2026-12-01T09:00:00Z"
DEC1_0000 = "2026-12-01T10:00:30Z"  # Dec 1 00:00:30 HST
DEC1_10 = "2026-12-01T20:00:00Z"
DEC2_0000 = "2026-12-02T10:00:30Z"
DEC2_10 = "2026-12-02T20:00:00Z"
DEC2_09 = "2026-12-02T19:00:00+00:00"  # Dec 2 09:00 HST, as Home Assistant writes last_changed
DAYS = (("nov30", NOV30_22), ("dec1", DEC1_10), ("dec2", DEC2_10))
PERIODS = {"2026-11": {"start": "2026-11-01", "end": "2026-12-01", "src": "package"},
           "2026-12": {"start": "2026-12-02", "end": "2026-12-31", "src": "package"}}


def _days(first, last, trips):
    """[[iso, trip, lay]] from first to last (ISO days); trips {iso: (trip, lay)}."""
    from datetime import date, timedelta
    d, out = date.fromisoformat(first), []
    while d <= date.fromisoformat(last):
        t = trips.get(d.isoformat(), ("", ""))
        out.append([d.isoformat(), t[0], t[1]])
        d += timedelta(days=1)
    return out


def _sched(periods=PERIODS, offset=0, changed="2026-11-30T20:00:00+00:00", offset_at=None):
    """The schedule sensor with November's page (Oct 31 to Dec 1, FLICA's first row the day before the period) and
    December's (Nov 30 to Dec 31): a made-up trip H3907 Nov 30 to Dec 2 carried across, H3913 and H3965 in December.
    offset_at: when the month offset was last changed (its last_changed; changed when not given)."""
    carry = {"trip": "H3907", "start": "2026-11-30", "end": "2026-12-02", "lay": "KIX"}
    nov = {"items": [{"trip": "H3901", "start": "2026-11-10", "end": "2026-11-12", "lay": "LAX"}, carry],
           "days": _days("2026-10-31", "2026-12-01", {"2026-11-10": ("H3901", "LAX"), "2026-11-11": ("", "LAX"),
                                                      "2026-11-12": ("", "HNL"), "2026-11-30": ("H3907", "KIX"),
                                                      "2026-12-01": ("", "KIX")}),
           "totals": {"credit": "40:00", "block": "30:00"}, "updated": "Nov 29, 2026 10:00:00",
           "read_at": "2026-11-30T19:00:00+00:00"}
    dec = {"items": [carry, {"trip": "H3913", "start": "2026-12-06", "end": "2026-12-08", "lay": "SYD"},
                     {"trip": "H3965", "start": "2026-12-09", "end": "2026-12-11", "lay": "LAX"}],
           "days": _days("2026-11-30", "2026-12-31", {"2026-11-30": ("H3907", "KIX"), "2026-12-01": ("", "-"),
                                                      "2026-12-02": ("", "HNL"), "2026-12-06": ("H3913", "SYD"),
                                                      "2026-12-07": ("", "SYD"), "2026-12-08": ("", "HNL"),
                                                      "2026-12-09": ("H3965", "LAX"), "2026-12-10": ("", "LAX"),
                                                      "2026-12-11": ("", "HNL")}),
           "totals": {"credit": "60:00", "block": "45:00"}, "updated": "Nov 29, 2026 10:00:00",
           "read_at": "2026-11-30T19:00:00+00:00"}
    def st(s, a=None, ch=changed):
        return {"state": s, "attributes": a or {}, "last_updated": ch, "last_changed": ch}
    attrs = {"updated": "", "months": {"2026-11": nov, "2026-12": dec}, "listed": ["2026-10", "2026-11", "2026-12"],
             "refresh": {}, "read_status": {"ok": True}}
    if periods is not None:
        attrs["periods"] = periods
    return {"sensor.flight_watcher_schedule": st("", attrs),
            "input_number.flight_watcher_month_offset": st(str(offset), ch=offset_at or changed),
            "sensor.flight_watcher_state": st("idle", {"role": "admin", "note": ""}),
            "sensor.flight_watcher_last_check": st("2026-11-30T19:59:00+00:00"),
            "number.flight_watcher_normal_check_every": st("6"), "number.flight_watcher_hunt_check_every": st("40"),
            "switch.flight_watcher_hunt_mode": st("off"), "switch.flight_watcher_pause": st("off")}


SCHED_MOUNT = """([h, dark]) => {
  document.body.querySelectorAll('flight-watcher-schedule-card').forEach((x) => x.remove());
  window.calls = [];
  const c = document.createElement('flight-watcher-schedule-card'); c.setConfig({}); document.body.appendChild(c);
  window.card = c;
  c.hass = {states: h, themes: {darkMode: dark}, user: {is_owner: true},
            callService: (d, s, data) => { window.calls.push([d, s, data]); return Promise.resolve(); }};
  return window.readSched(); }"""
SCHED_READ = """() => { window.readSched = () => { const r = window.card.shadowRoot;
  const rows = {}, trips = {};
  r.querySelectorAll('tr[data-d]').forEach((t) => { if (!(t.dataset.d in rows)) rows[t.dataset.d] = t.className; });
  r.querySelectorAll('tr[data-d] .trip[data-k]').forEach((t) => { trips[t.closest('tr').dataset.d] = t.textContent; });
  return {title: r.querySelector('.hd2 h3').textContent, rows, trips,
          fly: [...r.querySelectorAll('tr[data-d] .st.fly')].map((x) => x.closest('tr').dataset.d),
          wide: document.documentElement.scrollWidth, vw: window.innerWidth}; }; }"""


def _browser():
    sync_api = pytest.importorskip("playwright.sync_api")
    from test_cards import _chromium
    return sync_api, _chromium


def _src(name):
    return open(os.path.join(WWW, name), encoding="utf-8").read()


def _open(b, src, clock, tz=HNL, width=390, dark=False):
    ctx = b.new_context(viewport={"width": width, "height": 900}, timezone_id=tz,
                        color_scheme="dark" if dark else "light")
    pg = ctx.new_page()
    pg.clock.set_fixed_time(clock)
    pg.set_content(PAGE % (DARK if dark else LIGHT, src))
    return ctx, pg


def _shot(pg, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        pg.screenshot(path=os.path.join(SHOTS, f"{name}.png"), full_page=True)


def _sched_case(b, src, clock, tz=HNL, **kw):
    ctx, pg = _open(b, src, clock, tz)
    try:
        pg.evaluate(SCHED_READ)
        return pg.evaluate(f"({SCHED_MOUNT})", [_sched(**kw), False])
    finally:
        ctx.close()


def _run(fn):
    sync_api, chromium = _browser()
    with sync_api.sync_playwright() as p:
        b = chromium(p)
        if not b:
            pytest.skip("no Chromium for Playwright")
        try:
            return fn(b)
        finally:
            b.close()


# ---------------------------------------------------------------- the schedule card's month (C4, C10, P8, S11)
def test_the_schedule_card_opens_the_bid_month_that_holds_today_in_hst():
    src = _src("flight-watcher-schedule-card.js")
    cases = [  # (name, clock, device time zone, offset, periods, the month shown)
        ("jst_nov30_22", NOV30_22, JST, 0, PERIODS, "November 2026"),  # was December (the phone's own month)
        ("jst_nov30_23_off1", NOV30_23, JST, 1, PERIODS, "December 2026"),  # was January
        ("hnl_dec1_0000_off1", DEC1_0000, HNL, 1, PERIODS, "December 2026"),  # was January until the 00:01 reset
        ("hnl_dec1", DEC1_10, HNL, 0, PERIODS, "November 2026"),  # Dec 1 is in November's period
        ("jst_dec1", DEC1_10, JST, 0, PERIODS, "November 2026"),
        ("hnl_dec1_off1", DEC1_10, HNL, 1, PERIODS, "December 2026"),  # the arrows step from November
        ("hnl_dec2_0000", DEC2_0000, HNL, 0, PERIODS, "December 2026"),  # December's period from Dec 2
        ("hnl_dec2_offm1", DEC2_10, HNL, -1, PERIODS, "November 2026", DEC2_09),  # set on Dec 2
        ("hnl_dec1_no_periods", DEC1_10, HNL, 0, None, "December 2026"),  # no bid period known: the calendar month
        ("hnl_dec1_only_dec", DEC1_10, HNL, 0, {"2026-12": PERIODS["2026-12"]}, "November 2026"),  # before Dec 2
        ("jst_nov30_no_periods", NOV30_22, JST, 0, None, "November 2026"),  # HST's calendar month, not the phone's
    ]
    got = _run(lambda b: {c[0]: _sched_case(b, src, c[1], c[2], offset=c[3], periods=c[4],
                                            offset_at=(c[6:] or [None])[0]) for c in cases})
    for name, _, _, _, _, want, *_ in cases:
        assert got[name]["title"] == want, (name, got[name]["title"])
        assert got[name]["wide"] <= got[name]["vw"], name


def test_on_dec_1_the_default_page_shows_the_trip_carried_across_in_progress():
    src = _src("flight-watcher-schedule-card.js")
    o = _run(lambda b: _sched_case(b, src, DEC1_10))
    assert o["title"] == "November 2026"
    assert o["trips"].get("2026-11-30") == "H3907" and o["fly"] == ["2026-11-30"], o
    assert "2026-12-01" in o["rows"]  # today is on the page


def test_the_month_arrows_still_step_the_offset():
    src = _src("flight-watcher-schedule-card.js")

    def fn(b):
        ctx, pg = _open(b, src, DEC1_10)
        try:
            pg.evaluate(SCHED_READ)
            out = {"first": pg.evaluate(f"({SCHED_MOUNT})", [_sched(), False])["title"]}
            for nav in ("1", "-1", "0"):
                pg.evaluate(f"window.card.shadowRoot.querySelector('.nav[data-nav=\"{nav}\"]').click()")
            out["calls"] = pg.evaluate("window.calls")
            st = _sched(offset=1)
            pg.evaluate("(h) => { window.card.hass = Object.assign({}, window.card._h, {states: h}); }", st)
            out["next"] = pg.evaluate("window.readSched()")["title"]
            st = _sched(offset=-1)
            pg.evaluate("(h) => { window.card.hass = Object.assign({}, window.card._h, {states: h}); }", st)
            out["prev"] = pg.evaluate("window.readSched()")["title"]
            return out
        finally:
            ctx.close()
    o = _run(fn)
    ent = {"entity_id": "input_number.flight_watcher_month_offset"}
    assert o["first"] == "November 2026" and o["next"] == "December 2026" and o["prev"] == "October 2026", o
    assert o["calls"] == [["input_number", "increment", ent], ["input_number", "decrement", ent],
                          ["input_number", "set_value", {**ent, "value": 0}]], o["calls"]


# ---------------------------------------------------------------- an offset left from an earlier bid month (G5A-1)
DEC1_10_LC = "2026-12-01T20:00:00.123456+00:00"  # Dec 1 10:00 HST: Ryan taps > on November's page to see December
JAN_EARLY = {"2026-12": {"start": "2026-12-02", "end": "2026-12-30", "src": "package"},
             "2027-01": {"start": "2026-12-31", "end": "2027-01-31", "src": "package"}}  # January from Dec 31


def test_an_offset_set_in_an_earlier_bid_month_counts_as_0_once_the_month_moves_on():
    """The reset automation runs at 00:01 on the calendar 1st, the card's month moves on at the bid period's first
    day: an offset set against an earlier bid month (its last_changed in HST) counts as 0, so the page shown is the
    bid month that holds today, not one month past it for the whole bid month."""
    src = _src("flight-watcher-schedule-card.js")
    cases = [  # (name, clock, offset, set at (last_changed), periods, the month shown)
        ("dec2_set_dec1", DEC2_10, 1, DEC1_10_LC, PERIODS, "December 2026"),  # was January 2027
        ("dec2_0000_set_dec1", DEC2_0000, 1, DEC1_10_LC, PERIODS, "December 2026"),  # was January 2027
        ("dec31_set_dec1", "2027-01-01T08:00:00Z", 1, DEC1_10_LC, PERIODS, "December 2026"),  # Dec 31 22:00 HST
        ("jan_from_dec31", "2026-12-31T20:00:00Z", 1, "2026-12-20T20:00:00+00:00", JAN_EARLY, "January 2027"),
        ("dec2_m1_set_dec1", DEC2_10, -1, DEC1_10_LC, PERIODS, "December 2026"),  # was November
        # kept: set in the bid month that holds today
        ("dec2_set_dec2", DEC2_10, 1, "2026-12-02T10:00:10+00:00", PERIODS, "January 2027"),
        ("dec1_0000_set_nov23", DEC1_0000, 1, "2026-11-23T16:12:59+00:00", PERIODS, "December 2026"),
        ("dec1_set_dec1", DEC1_10, 1, DEC1_10_LC, PERIODS, "December 2026"),
        ("dec2_no_stamp", DEC2_10, 1, "a", PERIODS, "January 2027"),  # no time to tell: as set
    ]
    got = _run(lambda b: {c[0]: _sched_case(b, src, c[1], offset=c[2], offset_at=c[3], periods=c[4])
                          for c in cases})
    for name, _, _, _, _, want in cases:
        assert got[name]["title"] == want, (name, got[name]["title"])


def test_the_arrows_step_from_the_month_shown_when_the_offset_is_left_from_an_earlier_bid_month():
    src = _src("flight-watcher-schedule-card.js")

    def fn(b):
        ctx, pg = _open(b, src, DEC2_10)
        try:
            pg.evaluate(SCHED_READ)
            out = {}
            for nav in ("1", "-1", "0"):
                out["first"] = pg.evaluate(f"({SCHED_MOUNT})", [_sched(offset=1, offset_at=DEC1_10_LC), False])
                pg.evaluate(f"window.card.shadowRoot.querySelector('.nav[data-nav=\"{nav}\"]').click()")
                out[nav] = pg.evaluate("new Promise((r) => setTimeout(() => r(window.calls), 0))")
            pg.evaluate(f"({SCHED_MOUNT})", [_sched(offset=1, offset_at="2026-12-02T10:00:10+00:00"), False])
            pg.evaluate("window.card.shadowRoot.querySelector('.nav[data-nav=\"1\"]').click()")
            out["kept"] = pg.evaluate("new Promise((r) => setTimeout(() => r(window.calls), 0))")
            return out
        finally:
            ctx.close()
    o = _run(fn)
    ent = {"entity_id": "input_number.flight_watcher_month_offset"}
    zero = ["input_number", "set_value", {**ent, "value": 0}]
    assert o["first"]["title"] == "December 2026", o["first"]
    assert o["1"] == [zero, ["input_number", "increment", ent]], o["1"]  # to January: was February
    assert o["-1"] == [zero, ["input_number", "decrement", ent]], o["-1"]  # to November: was December again
    assert o["0"] == [zero], o["0"]
    assert o["kept"] == [["input_number", "increment", ent]], o["kept"]  # an offset of this bid month: as before


# ---------------------------------------------------------------- the faded other-month rows (C7)
def test_the_faded_rows_are_the_days_outside_the_bid_period():
    src = _src("flight-watcher-schedule-card.js")

    def fn(b):
        return {"nov_dec1": _sched_case(b, src, DEC1_10), "dec_dec2": _sched_case(b, src, DEC2_10),
                "nov_hnl": _sched_case(b, src, NOV30_22), "nov_nov30": _sched_case(b, src, NOV30_22, JST),
                "cal_dec1": _sched_case(b, src, DEC1_10, periods=None)}
    o = _run(fn)
    oth = lambda r, d: " oth" in r["rows"][d] or r["rows"][d].startswith("oth")  # noqa: E731
    # Nov 30 in Honolulu: November's page, Dec 1 (in its period, in its totals) not faded (was faded)
    assert o["nov_hnl"]["title"] == "November 2026" and not oth(o["nov_hnl"], "2026-12-01"), o["nov_hnl"]["rows"]
    nov, dec = o["nov_dec1"], o["dec_dec2"]
    assert nov["title"] == "November 2026" and dec["title"] == "December 2026"
    assert not oth(nov, "2026-12-01") and not oth(nov, "2026-11-30") and oth(nov, "2026-10-31"), nov["rows"]
    assert oth(dec, "2026-12-01") and oth(dec, "2026-11-30") and not oth(dec, "2026-12-02"), dec["rows"]
    assert not oth(dec, "2026-12-31")
    assert not oth(o["nov_nov30"], "2026-12-01") and o["nov_nov30"]["title"] == "November 2026"
    cal = o["cal_dec1"]  # no bid period known: the calendar month, as before
    assert cal["title"] == "December 2026" and oth(cal, "2026-11-30") and not oth(cal, "2026-12-01"), cal["rows"]


# ---------------------------------------------------------------- the recall card's month (C5)
def _rv(date, pairing, verdict="POSSIBLE"):
    return {"id": f"{date}|{pairing}|recall", "date": date, "kind": "recall", "pairing": pairing, "seat": "FO",
            "sen": 900, "pilot": "Doe, Jane", "verdict": verdict, "why": ["went to #900, junior to you (#500)"],
            "refs": ["PWA 22.G.2.e"], "act": {}}


def _recall(days, updated="2026-12-01T08:00:00+00:00"):
    a = {"open": 1, "alert": 0, "me": {"sen": 500, "seat": "FO", "o75_months": {}}, "last": days[0]["date"],
         "checked": updated, "received": updated, "days": days}
    return {"sensor.flight_watcher_recall_o75": {"state": "1", "attributes": a, "last_updated": updated},
            "sensor.flight_watcher_state": {"state": "idle", "attributes": {"role": "admin"}, "last_updated": updated}}


NOV30_LIST = {"date": "2026-11-30", "file": "ok", "verdicts": [_rv("2026-11-30", "H3990", "NO")]}
DEC1_LIST = {"date": "2026-12-01", "file": "ok", "verdicts": [_rv("2026-12-01", "H3991")]}
RECALL_MOUNT = """([h, dark]) => {
  document.body.querySelectorAll('flight-watcher-recall-card').forEach((x) => x.remove());
  const c = document.createElement('flight-watcher-recall-card'); c.setConfig({mode: 'tab'});
  document.body.appendChild(c);
  window.card = c;
  c.hass = {states: h, themes: {darkMode: dark}, callService: (d, s, data) => { window.calls.push([d, s, data]); }};
  return window.readRecall(); }"""
RECALL_READ = """() => { window.readRecall = () => { const r = window.card.shadowRoot;
  return {month: r.querySelector('.mp b').textContent,
          days: [...r.querySelectorAll('details.day[data-day]')].map((x) => x.dataset.day),
          o75: r.querySelector('select[data-o75]').dataset.o75,
          wide: document.documentElement.scrollWidth, vw: window.innerWidth}; };
  window.pushRecall = (h) => { window.card.hass = Object.assign({}, window.card._h, {states: h});
                               return window.readRecall(); }; }"""


def test_the_recall_card_moves_on_with_the_clock_unless_a_month_was_picked():
    src = _src("flight-watcher-recall-card.js")
    both = _recall([DEC1_LIST, NOV30_LIST], "2026-12-01T19:00:00+00:00")

    def fn(b):
        out = {}
        ctx, pg = _open(b, src, NOV30_23)
        try:
            pg.evaluate(RECALL_READ)
            out["nov30"] = pg.evaluate(f"({RECALL_MOUNT})", [_recall([NOV30_LIST]), False])
            pg.clock.set_fixed_time(DEC1_10)  # left open overnight: the Dec 1 list comes in
            out["dec1"] = pg.evaluate("(h) => window.pushRecall(h)", both)
            # the arrows pick a month: it stays when the clock moves on
            pg.evaluate("window.card.shadowRoot.querySelector('[data-m=\"-1\"]').click()")
            out["picked"] = pg.evaluate("window.readRecall()")
            pg.clock.set_fixed_time(DEC2_10)
            out["picked_dec2"] = pg.evaluate("(h) => window.pushRecall(h)", both)
            pg.evaluate("window.card.shadowRoot.querySelector('[data-m=\"1\"]').click()")  # back to this month
            pg.clock.set_fixed_time("2027-01-01T10:00:30Z")  # Jan 1 00:00:30 HST: follows the clock again
            out["jan1"] = pg.evaluate("(h) => window.pushRecall(h)", both)
        finally:
            ctx.close()
        # the sensor itself unchanged overnight: the next hass push after midnight HST still moves the month on
        ctx, pg = _open(b, src, NOV30_23, JST)
        try:
            pg.evaluate(RECALL_READ)
            out["jst_nov30"] = pg.evaluate(f"({RECALL_MOUNT})", [both, False])
            pg.clock.set_fixed_time(DEC1_10)
            out["same_sensor"] = pg.evaluate("(h) => window.pushRecall(h)", both)
        finally:
            ctx.close()
        return out
    o = _run(fn)
    assert o["nov30"]["month"] == "Nov 2026" and o["nov30"]["days"] == ["2026-11-30"], o["nov30"]
    assert o["dec1"]["month"] == "Dec 2026" and o["dec1"]["days"] == ["2026-12-01"], o["dec1"]
    assert o["dec1"]["o75"] == "2026-12"
    assert o["picked"]["month"] == "Nov 2026" and o["picked_dec2"]["month"] == "Nov 2026", o
    assert o["jan1"]["month"] == "Jan 2027", o["jan1"]
    assert o["jst_nov30"]["month"] == "Nov 2026" and o["jst_nov30"]["days"] == ["2026-11-30"], o["jst_nov30"]
    assert o["same_sensor"]["month"] == "Dec 2026" and o["same_sensor"]["days"] == ["2026-12-01"], o["same_sensor"]


def test_a_month_set_before_the_first_draw_is_kept():
    """The render harnesses set the month before the first draw (c._m): it is kept as picked."""
    src = _src("flight-watcher-recall-card.js")

    def fn(b):
        ctx, pg = _open(b, src, DEC1_10)
        try:
            pg.evaluate(RECALL_READ)
            return pg.evaluate("""([h]) => { const c = document.createElement('flight-watcher-recall-card');
              c.setConfig({mode: 'tab'}); c._m = '2026-11'; document.body.appendChild(c); window.card = c;
              c.hass = {states: h, themes: {darkMode: false}, callService: () => {}}; return window.readRecall(); }""",
                               [_recall([DEC1_LIST, NOV30_LIST])])
        finally:
            ctx.close()
    o = _run(fn)
    assert o["month"] == "Nov 2026" and o["days"] == ["2026-11-30"], o


# ---------------------------------------------------------------- the pilot card's months (C9)
PILOT_ENT = "sensor.flight_watcher_pilot_schedule"


def _pilot(periods=PERIODS, pre="flight_watcher", month="2026-12"):
    shown = {"emp": "10002", "name": "Doe, Bea", "status": "ok", "month": month, "updated": "Nov 29, 2026 10:00",
             "fetched": "2026-11-30T19:59:00+00:00",
             "days": [[f"{month}-02", "H3961", "LAX"], [f"{month}-03", "", "HNL"]],
             "items": [{"trip": "H3961", "start": f"{month}-02", "end": f"{month}-03", "lay": "LAX"}], "totals": {}}
    at = "2026-11-30T20:00:00+00:00"
    st = {f"sensor.{pre}_pilot_schedule": {"state": "x", "last_updated": at, "attributes": shown}}
    if periods is not None:
        st[f"sensor.{pre}_schedule"] = {"state": "", "last_updated": at,
                                         "attributes": {"periods": periods}}
    return st


PILOT_MOUNT = """([h, dark, tag, ent]) => { document.body.querySelectorAll(tag).forEach((x) => x.remove());
  const c = document.createElement(tag); c.setConfig({entity: ent}); document.body.appendChild(c);
  c.scrollIntoView = () => {}; window.card = c;
  c.hass = {states: h, themes: {darkMode: dark},
            callService: (d, s, data) => { window.sent.push([d, s, data]); return Promise.resolve(); }};
  return window.readPilot(); }"""
PILOT_READ = """() => { window.readPilot = () => { const r = window.card.shadowRoot;
  return {mos: [...r.querySelectorAll('.mo')].map((x) => [x.textContent, x.dataset.month, x.disabled]),
          wide: document.documentElement.scrollWidth, vw: window.innerWidth}; }; }"""


def _pilot_case(b, src, clock, tz=HNL, tag="flight-watcher-pilot-card", ent=PILOT_ENT, **kw):
    ctx, pg = _open(b, src, clock, tz)
    try:
        pg.evaluate(PILOT_READ)
        return pg.evaluate(f"({PILOT_MOUNT})", [_pilot(**kw), False, tag, ent])
    finally:
        ctx.close()


def test_the_pilot_card_offers_the_bid_month_of_today_and_the_next():
    src = _src("flight-watcher-pilot-card.js")
    james = cards.pilot_copy(src, "james")

    def fn(b):
        out = {"dec1": _pilot_case(b, src, DEC1_10), "jst_nov30": _pilot_case(b, src, NOV30_22, JST, month="2026-11"),
               "dec2": _pilot_case(b, src, DEC2_10), "dec1_none": _pilot_case(b, src, DEC1_10, periods=None),
               "dec1_james": _pilot_case(b, james, DEC1_10, tag="flight-watcher-pilot-card-james",
                                         ent="sensor.flight_watcher_james_pilot_schedule",
                                         pre="flight_watcher_james")}
        # a tap on November on Dec 1 asks the Watcher for November's line of the pilot shown
        ctx, pg = _open(b, src, DEC1_10)
        try:
            pg.evaluate(PILOT_READ)
            pg.evaluate(f"({PILOT_MOUNT})", [_pilot(), False, "flight-watcher-pilot-card", PILOT_ENT])
            pg.evaluate("() => { const x = window.card.shadowRoot.querySelector('.mo[data-month=\"2026-11\"]');"
                        " if (x) x.click(); }")
            out["sent"] = pg.evaluate("window.sent")
        finally:
            ctx.close()
        # the buttons move on at Dec 2 00:00 HST on the next hass push, the pilot sensor unchanged
        ctx, pg = _open(b, src, "2026-12-02T09:59:00Z")  # Dec 1 23:59 HST
        try:
            pg.evaluate(PILOT_READ)
            out["dec1_2359"] = pg.evaluate(f"({PILOT_MOUNT})",
                                           [_pilot(), False, "flight-watcher-pilot-card", PILOT_ENT])
            pg.clock.set_fixed_time(DEC2_0000)
            out["dec2_push"] = pg.evaluate("""(h) => { window.card.hass = Object.assign({}, window.card._h,
                {states: h}); return window.readPilot(); }""", _pilot())
        finally:
            ctx.close()
        return out
    o = _run(fn)
    assert o["dec1"]["mos"] == [["Nov 2026", "2026-11", False], ["Dec 2026", "2026-12", True]], o["dec1"]
    assert o["jst_nov30"]["mos"] == [["Nov 2026", "2026-11", True], ["Dec 2026", "2026-12", False]], o["jst_nov30"]
    assert o["dec2"]["mos"] == [["Dec 2026", "2026-12", True], ["Jan 2027", "2027-01", False]], o["dec2"]
    assert o["dec1_none"]["mos"] == [["Dec 2026", "2026-12", True], ["Jan 2027", "2027-01", False]]  # as before
    assert o["dec1_james"]["mos"] == o["dec1"]["mos"]  # a pilot's copy reads his own schedule's periods
    pay = [json.loads(x[2]["payload"]) for x in o["sent"] if x[:2] == ["mqtt", "publish"]]
    assert [p.get("month") for p in pay] == ["2026-11"] and pay[0].get("emp") == "10002", o["sent"]
    assert [m[1] for m in o["dec1_2359"]["mos"]] == ["2026-11", "2026-12"], o["dec1_2359"]
    assert [m[1] for m in o["dec2_push"]["mos"]] == ["2026-12", "2027-01"], o["dec2_push"]


# ---------------------------------------------------------------- the pilot card's months are the Watcher's (G5A-2)
def _pairing_files(W, periods):  # noqa: N803
    """The pairing files' period bounds, as pdfs.py writes them (test_fw181_pot_month._periods)."""
    os.makedirs(W.CARD_PAIRINGS, exist_ok=True)
    for m, p in periods.items():
        with open(os.path.join(W.CARD_PAIRINGS, f"pairings_{m}.json"), "w") as f:
            json.dump({"start": p["start"], "end": p["end"], "cols": [], "rows": []}, f)


def _watcher_periods(W, sent):  # noqa: N803
    """The periods the Watcher publishes on its schedule sensor (publish_schedule), with November's and December's
    pages on file."""
    W.S["schedule"] = {m: {"items": [], "days": [], "totals": {}, "updated": "Nov 29, 2026 10:00:00"}
                       for m in ("2026-11", "2026-12")}
    W.publish_schedule()
    return [p for t, p in sent if t == "schedule"][-1]["periods"]


EDGES = (("nov30_22", NOV30_22, datetime(2026, 11, 30, 22, 0)), ("dec1_10", DEC1_10, datetime(2026, 12, 1, 10, 0)),
         ("dec2_0005", "2026-12-02T10:05:00Z", datetime(2026, 12, 2, 0, 5)))


@pytest.mark.parametrize("instance", ["pilot2", ""])
def test_the_pilot_cards_months_are_the_months_the_watcher_takes(load, monkeypatch, instance):  # noqa: F811
    """The pilot card's two buttons, drawn from the pilot's own schedule sensor (its periods), are the two months
    W.lookup_months() takes, on a pilot's instance and Ryan's, on Nov 30, Dec 1 and Dec 2: a tap on either is read
    (pilot_req), never refused with an empty pilot."""
    W, sent = load(instance)  # noqa: N806
    _pairing_files(W, PERIODS)
    pre = W.T  # the MQTT prefix: flight_watcher, flight_watcher_pilot2
    src = _src("flight-watcher-pilot-card.js")
    tag, ent = "flight-watcher-pilot-card", PILOT_ENT
    if instance:
        src, tag, ent = cards.pilot_copy(src, instance), f"{tag}-{instance}", f"sensor.{pre}_pilot_schedule"
    got = {}
    for name, clock, now in EDGES:
        monkeypatch.setattr(W, "local_now", lambda now=now: now)
        periods = _watcher_periods(W, sent)
        months = list(W.lookup_months())
        cardm = _run(lambda b: _pilot_case(b, src, clock, tag=tag, ent=ent, pre=pre, periods=periods))
        got[name] = ([m[1] for m in cardm["mos"]], months)
        for m in months:  # each button's month is taken: the lookup is queued for it
            W.S.pop("pilot_req", None)
            W.S["cm_prompt_captured"] = True
            monkeypatch.setattr(W.time, "sleep", lambda s: None)
            W.pilot_cmd(json.dumps({"emp": "10002", "name": "Doe, Bea", "month": m}))
            assert (W.S.get("pilot_req") or {}).get("month") == m, (name, m, W.S.get("pilot_req"))
    assert got == {"nov30_22": (["2026-11", "2026-12"], ["2026-11", "2026-12"]),
                   "dec1_10": (["2026-11", "2026-12"], ["2026-11", "2026-12"]),
                   "dec2_0005": (["2026-12", "2027-01"], ["2026-12", "2027-01"])}, got


# ---------------------------------------------------------------- one fwBidMonth, the Watcher's bid month (G5B-4)
def test_fw_bid_month_is_one_copy_in_the_shared_grid_block_of_each_card():
    from test_sched_grid_shared import block
    for name in ("schedule", "pilot"):
        text = _src(f"flight-watcher-{name}-card.js")
        assert text.count("function fwBidMonth(") == 1, name
        assert "function fwBidMonth(" in (block(text) or ""), name  # kept equal by test_sched_grid_shared


def test_the_cards_bid_month_is_the_watchers_on_the_same_periods(load, monkeypatch):  # noqa: F811
    """fwBidMonth on the schedule sensor's periods against the Watcher's bid_period_key on the same pairing files, for
    the days around a change of bid month (also a January that starts on Dec 31)."""
    days = ("2026-11-30", "2026-12-01", "2026-12-02", "2026-12-30", "2026-12-31", "2027-01-01", "2027-01-31")
    out = {}
    for name, periods in (("dec2", PERIODS), ("jan_dec31", {**PERIODS, **JAN_EARLY})):
        W, sent = load("pilot2")  # noqa: N806
        _pairing_files(W, periods)
        W.S["schedule"] = {m: {"items": [], "days": [], "totals": {}} for m in periods}
        W.publish_schedule()
        pub = [p for t, p in sent if t == "schedule"][-1]["periods"]
        watcher = [W.bid_period_key(d) for d in days]

        def fn(b, pub=pub):
            ctx, pg = _open(b, _src("flight-watcher-schedule-card.js"), DEC1_10)
            try:
                return pg.evaluate("([p, ds]) => ds.map((d) => fwBidMonth(p, d))", [pub, list(days)])
            finally:
                ctx.close()
        out[name] = (_run(fn), watcher)
    assert out["dec2"][0] == out["dec2"][1] == ["2026-11", "2026-11", "2026-12", "2026-12", "2026-12", "2027-01",
                                                "2027-01"], out
    assert out["jan_dec31"][0] == out["jan_dec31"][1] == ["2026-11", "2026-11", "2026-12", "2026-12", "2027-01",
                                                          "2027-01", "2027-01"], out


def test_the_lines_this_release_touched_stay_within_120_characters():
    for name, mark in (("schedule", "_bidToday("), ("pilot", "pcMonths(")):
        long = [len(x) for x in _src(f"flight-watcher-{name}-card.js").splitlines() if mark in x and len(x) > 120]
        assert not long, (name, long)


# ---------------------------------------------------------------- each changed card on Nov 30, Dec 1 and Dec 2
def test_each_changed_card_at_390_light_and_320_dark_on_nov_30_dec_1_and_dec_2():
    srcs = {k: _src(f"flight-watcher-{k}-card.js") for k in ("schedule", "recall", "pilot")}
    want = {"nov30": ("November 2026", "Nov 2026", ["2026-11", "2026-12"]),
            "dec1": ("November 2026", "Dec 2026", ["2026-11", "2026-12"]),
            "dec2": ("December 2026", "Dec 2026", ["2026-12", "2027-01"])}

    def fn(b):
        out = {}
        for day, clock in DAYS:
            for theme, width, dark in (("light", 390, False), ("dark", 320, True)):
                for card in ("schedule", "recall", "pilot"):
                    ctx, pg = _open(b, srcs[card], clock, width=width, dark=dark)
                    try:
                        if card == "schedule":
                            pg.evaluate(SCHED_READ)
                            o = pg.evaluate(f"({SCHED_MOUNT})", [_sched(), dark])
                        elif card == "recall":
                            pg.evaluate(RECALL_READ)
                            lists = [DEC1_LIST, NOV30_LIST] if day != "nov30" else [NOV30_LIST]
                            o = pg.evaluate(f"({RECALL_MOUNT})", [_recall(lists), dark])
                        else:
                            pg.evaluate(PILOT_READ)
                            mon = "2026-12" if day != "nov30" else "2026-11"
                            o = pg.evaluate(f"({PILOT_MOUNT})",
                                            [_pilot(month=mon), dark, "flight-watcher-pilot-card", PILOT_ENT])
                        _shot(pg, f"g5_{card}_{day}_{theme}{width}")
                        out[(card, day, theme)] = o
                    finally:
                        ctx.close()
        return out
    o = _run(fn)
    for (card, day, theme), r in o.items():
        assert r["wide"] <= r["vw"], (card, day, theme)  # no sideways scroll at 390 or 320 px
        s, rc, pc = want[day]
        if card == "schedule":
            assert r["title"] == s, (card, day, theme, r["title"])
        elif card == "recall":
            assert r["month"] == rc, (card, day, theme, r["month"])
        else:
            assert [m[1] for m in r["mos"]] == pc, (card, day, theme, r["mos"])


def test_the_card_sources_take_no_month_from_the_device_clock_and_have_no_em_dash():
    sch = _src("flight-watcher-schedule-card.js")
    key = sch.split("  _key() {", 1)[1].split("\n  }\n", 1)[0]
    assert "new Date()" not in key and "getMonth()" not in key and "getFullYear()" not in key, key
    for name in ("schedule", "recall", "pilot"):
        assert chr(0x2014) not in _src(f"flight-watcher-{name}-card.js"), name
