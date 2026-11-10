"""1.6.2 (Release A, group 3, items 13 to 15): the portal layout shows the open time pot and Tradeboard pickups (fit,
FAR 117, value), the working flight and the CrewTrac status on the Watcher tab and the FLICA requests on the Schedule
tab (where the Request decided alert opens); a portal copy speaks no Home Assistant steps; times are HST and labeled;
the clock card's controls are 44 px tall on a phone and offer only the intervals the Watcher and the portal take; this
and last month always have a finds file; the schedule card follows the month helper's state. Synthetic data only
("Doe, Jane", 10001, made-up pairings), rendered in Chromium at the portal's 390 px."""
import json
import os
import re

import pytest

import cards
import portal as PT
import roles
from test_cards import _chromium

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WWW = os.path.join(HERE, "www")
NEW = ("pot-card", "working-card", "charters-card", "requests-card")


def _src(name):
    return open(os.path.join(WWW, f"flight-watcher-{name}.js"), encoding="utf-8").read()


def _layout():
    return json.load(open(os.path.join(HERE, "portal_layout.json"), encoding="utf-8"))


def _tab(tid):
    return [c for t in _layout()["tabs"] if t["id"] == tid for c in t["cards"]]


# ---------------------------------------------------------------- item 13: the layout
def test_watcher_tab_has_the_pot_the_working_flight_and_the_charters_card():
    types = [c["type"] for c in _tab("watcher")]
    for n in ("working-card", "pot-card", "charters-card"):
        assert f"custom:flight-watcher-{n}-{{name}}" in types, n
    assert types.index("custom:flight-watcher-clock-card-{name}") < types.index("custom:flight-watcher-working-card-{name}") \
        < types.index("custom:flight-watcher-pot-card-{name}") < types.index("custom:flight-watcher-finds-card-{name}")
    # the charters status is the card's, with its own Scan button: no bare count row or tile left
    assert not [c for c in _tab("watcher") if "charters" in c.get("entity", "") or "scan_crewtrac" in c.get("entity", "")]
    assert [t["id"] for t in _layout()["tabs"]] == list(roles.PORTAL_TABS)  # the same 5 tabs


def test_requests_card_sits_where_the_request_decided_alert_opens():
    view = roles.EVENT_VIEWS["request_decided"]
    assert "custom:flight-watcher-requests-card-{name}" in [c["type"] for c in _tab(view)]
    assert PT.event_text("request_decided", {"status": "Approved", "type": "Add"})[1] == "See the Schedule tab."


def test_new_cards_ship_like_the_others():
    built = cards.build("9", ["pilot2"])
    for n in NEW:
        assert f"flight-watcher-{n}.js" in built and f"flight-watcher-{n}-pilot2.js" in built
        p = built[f"flight-watcher-{n}-pilot2.js"]
        assert f'customElements.define("flight-watcher-{n}-pilot2"' in p and "Ryan" not in p
        assert chr(0x2014) not in _src(n)
    assert "COPY www /app/www" in open(os.path.join(HERE, "Dockerfile"), encoding="utf-8").read()
    # the pot card's PWA 3.D.6 table is the schedule card's
    grab = lambda s, n: re.search(n + r" = (\[.*?\]\]?);", s, re.S).group(1)  # noqa: E731
    sch, pot = _src("schedule-card"), _src("pot-card")
    assert grab(sch, "RATE_TABLE") == grab(pot, "PC_RATE_TABLE") and grab(sch, "RATE_DATES") == grab(pot, "PC_RATE_DATES")


def test_help_markdown_says_what_the_controls_really_do():
    md = next(c["content"] for c in _tab("watcher") if c["type"] == "markdown")
    assert "longer if you log in again within 6 h (up to 4 h)" in md  # the yield doubles (watcher.py, kills in 6 h)
    assert "**Scan CrewTrac now** logs in to CrewTrac once" in md and "save new CrewTrac details on the Settings tab" in md
    assert "reads the pot right away" not in md and "the Tradeboard right away" in md  # check_now is a full check
    assert chr(0x2014) not in json.dumps(_layout())


# ---------------------------------------------------------------- item 14: alert texts and notes
def test_alert_texts_match_the_pages_they_open():
    t, b = PT.event_text("recall_miss", {"verdict": "POSSIBLE", "date": "2026-11-12", "pairing": "H9001"})
    assert t == "Recall/O75 CHECK 2026-11-12 H9001" and "POSSIBLE" not in t and "Recall/O75 tab" in b
    assert PT.event_text("recall_miss", {"verdict": "MISSED"})[0] == "Recall/O75 SHOULD HAVE BEEN YOU"
    t, b = PT.event_text("rule_match", {"rule_id": "sin_hunt", "pairing": "H9002", "dates": "24Nov-27Nov",
                                        "layover": "SIN"})
    assert t == "Your alert rule matched H9002 24Nov-27Nov" and "sin_hunt" not in t and b == "Layover SIN"
    b = PT.event_text("stopped_*", {"state": "stopped_login_failed"})[1]
    assert "save the new one on the Settings tab" in b and "logs in by itself" in b
    # the new pairing text is pinned by the contract sample (portal_contract_v1.json): unchanged
    assert PT.event_text("new_pairing", {"pairing": "H9001", "fit": "Fits"}) == ("New pairing H9001", "Fit Fits")


def test_a_pilots_machine_notes_name_nobody_and_no_ha_step(portal_pilot):
    W, _ = portal_pilot("pilot2")
    assert W.yield_note(1800) == "back in 30 min"
    for note in (W.yield_note(1800), W.NEEDS_SETTINGS_NOTE, W.PAUSED_NOTE):
        assert "Ryan" not in note and "HA" not in note and "/settings/set" not in note
    assert "Settings tab" in W.NEEDS_SETTINGS_NOTE
    src = open(os.path.join(HERE, "watcher.py"), encoding="utf-8").read()
    assert 'set_machine("yielded", yield_note(cool))' in src and 'set_machine("paused", PAUSED_NOTE)' in src
    assert 'set_machine("needs_settings", NEEDS_SETTINGS_NOTE)' in src
    import sys
    sys.modules.pop("watcher", None)
    A, _ = portal_pilot("", portal=False)
    assert A.yield_note(1800) == "Ryan logged in elsewhere, back in 30 min"  # the admin's note as before


def test_the_needs_settings_wait_tells_the_pilot_where(portal_pilot, monkeypatch):
    W, _ = portal_pilot("pilot2")
    notes = []
    monkeypatch.setattr(W, "mqtt_start", lambda: W.MQ)
    monkeypatch.setattr(W, "start_upload_janitor", lambda: None)
    monkeypatch.setattr(W, "portal_start", lambda: None)
    real = W.set_machine
    monkeypatch.setattr(W, "set_machine", lambda st, note="": notes.append((st, note)) or real(st, note))

    class Waiting(Exception):
        pass

    def sleep(s):
        if s == 3600:
            raise Waiting
    monkeypatch.setattr(W.time, "sleep", sleep)
    with pytest.raises(Waiting):
        W.main()
    assert ("needs_settings", "enter your FLICA username and password on the Settings tab") in notes


def test_sealed_refusal_says_reload_this_page():
    import sealed
    assert "reload this page" in open(sealed.__file__, encoding="utf-8").read()
    assert "reload the dashboard" not in open(sealed.__file__, encoding="utf-8").read()


# ---------------------------------------------------------------- item 15: finds files
def test_this_and_last_month_always_have_a_finds_file(portal_pilot):
    W, _ = portal_pilot("pilot2")
    W.portal_start(threads=False)
    W.DB.finds_between = lambda a, b: []  # no finds at all yet (a new pilot)
    W.write_finds_months()
    first = W.local_now().date().replace(day=1)
    prev = f"{first.year - (first.month == 1):04d}-{(first.month - 2) % 12 + 1:02d}"
    key = W.www_key()
    for mon in (f"{first:%Y-%m}", prev):
        p = os.path.join(W.finds_dir(), W.WF.finds_name(mon, key))
        assert json.load(open(p)) == {"month": mon, "count": 0, "finds": []}
    older = f"{first.year - 1:04d}-{first.month:02d}"
    assert not os.path.exists(os.path.join(W.finds_dir(), W.WF.finds_name(older, key)))  # no empty history beyond
    W.portal_export_once(full=True)
    env = json.load(open(os.path.join(W.PORTAL_DIR, "out", "manifest.json"), encoding="utf-8"))
    files = json.loads(env["payload"])["files"]
    assert f"finds:{first:%Y-%m}" in files and f"finds:{prev}" in files


# ---------------------------------------------------------------- renders (Chromium, 390 px)
PAGE = ("<!doctype html><html><head><style>:root{--secondary-text-color:#555;--divider-color:#ccc}</style></head><body>"
        "<script>customElements.define('ha-card', class extends HTMLElement {});window.calls = [];"
        "window.fetches = []; const rf = window.fetch; window.fetch = (u, o) => { window.fetches.push(String(u));"
        " return Promise.resolve(new Response('{}', {status: 404})); };</script>%s</body></html>")


def _page(*texts):
    return PAGE % "".join(f"<script>{t}</script>" for t in texts)


def _run(js_cases, *texts, tz="Pacific/Honolulu", now="2026-11-10T11:30:00Z"):
    """Each case: (name, js returning a value); a fresh page per case. None when there is no Chromium."""
    sync_api = pytest.importorskip("playwright.sync_api")
    out = {}
    with sync_api.sync_playwright() as p:
        b = _chromium(p)
        if not b:
            pytest.skip("no Chromium for Playwright")
        try:
            ctx = b.new_context(viewport={"width": 390, "height": 844}, timezone_id=tz)
            for name, js in js_cases:
                pg = ctx.new_page()
                pg.clock.set_fixed_time(now)
                pg.set_content(_page(*texts))
                out[name] = pg.evaluate(js)
                pg.close()
        finally:
            b.close()
    return out


def _st(state, attrs=None, lu="2026-11-10T11:20:00+00:00"):
    return {"state": state, "attributes": attrs or {}, "last_updated": lu}


POT = [{"pairing": "H9001", "start": "26Nov", "end": "27Nov", "dates": "26Nov-27Nov", "days": "2", "layover": "-none-",
        "turn": "PPG", "credit": "11:20", "soft": "0:00", "report": "15:30", "captain": "Doe, Jane", "fit": "No sched",
        "far": "?", "vac": False, "blocked": False},
       {"pairing": "H9002", "start": "20Nov", "end": "22Nov", "dates": "20Nov-22Nov", "days": "3", "layover": "LAX",
        "credit": "15:00", "soft": "1:10", "captain": "Roe, Max", "fit": "Fits", "far": "OK (CBA rest 10:30)",
        "vac": True, "blocked": False}]
TB = [{"pairing": "H9003", "start": "25Nov", "end": "27Nov", "dates": "25Nov-27Nov", "days": "3", "layover": "SFO",
       "credit": "15:00", "soft": "3:45", "fit": "Conflict H9100", "far": "Rest 8:00 before", "vac": False,
       "blocked": False, "src": "T"}]

POT_JS = """(h) => { const c = document.createElement('flight-watcher-pot-card'); c.setConfig({});
  document.body.appendChild(c); c.hass = {states: h, callService: () => {}};
  const r = c.shadowRoot, rows = () => [...r.querySelectorAll('.r')].map((x) => x.innerText.replace(/\\s+/g, ' ').trim());
  const out = {rows: rows(), warn: (r.querySelector('.warn') || {}).textContent || '', head: r.querySelector('.hd').innerText,
               key: r.querySelector('details').textContent, wide: document.documentElement.scrollWidth};
  const sv = r.getElementById('sv'); out.sv = sv ? sv.parentElement.textContent.trim() : '';
  if (sv) { sv.click(); out.after = rows(); out.svh = r.getElementById('sv').parentElement.getBoundingClientRect().height; }
  return out; }"""


def _pot_states(lc="2026-11-10T11:29:00+00:00", st="hunting", lyr="5", unconf=False):
    return {"sensor.flight_watcher_pot_count": _st("2", {"pairings": POT}),
            "sensor.flight_watcher_tradeboard_pickups": _st("1", {"pairings": TB}),
            "sensor.flight_watcher_last_check": _st(lc), "sensor.flight_watcher_state": _st(st, {"role": "pilot"}),
            "input_number.flight_watcher_longevity_year": _st(lyr, {"unconfirmed": True} if unconf else {})}


def test_pot_card_shows_pot_and_pickups_with_fit_far_and_value():
    src = _src("pot-card")
    cases = [(n, f"({POT_JS})({json.dumps(s)})") for n, s in (
        ("fresh", _pot_states()), ("stale", _pot_states(lc="2026-11-10T10:00:00+00:00")),
        ("unset", _pot_states(lyr="1", unconf=True)))]
    got = _run(cases, src)
    f = got["fresh"]
    assert f["head"].startswith("Open time pot and Tradeboard pickups") and "2 in the pot" in f["head"] \
        and "1 Tradeboard pickup" in f["head"]
    assert len(f["rows"]) == 2 and f["rows"][0].startswith("H9003 T 25Nov-27Nov SFO 3 d $3,886")  # date order; H9002 on VAC
    assert "Conflict H9100" in f["rows"][0] and "FAR: Rest 8:00 before" in f["rows"][0]
    h1 = f["rows"][1]
    assert h1.startswith("H9001 26Nov-27Nov PPG turn 2 d $2,936")  # 11:20 x $259.04 (year 5, 2026-03-02 rate)
    assert "needs your schedule" in h1 and "FAR ?" in h1 and "CA Doe, Jane" in h1
    assert f["sv"] == "Show VAC/blocked (1 hidden)" and len(f["after"]) == 3 and f["svh"] >= 44
    assert "FAR OK (CBA rest 10:30)" in " ".join(f["after"]) and "VAC" in " ".join(f["after"])
    assert f["warn"] == "" and f["wide"] <= 390
    assert "PWA 3.D.6" in f["key"] and "117.25(e)" in f["key"] and "PWA 10.E.1.a" in f["key"]
    assert got["stale"]["warn"] == "Pot last read Nov 10 00:00 HST. May be out of date until the Watcher is running again."
    assert "$90.00/h" in got["unset"]["key"] and "not confirmed yet" in got["unset"]["key"]


WORK_JS = """(h) => { const c = document.createElement('flight-watcher-working-card'); c.setConfig({});
  document.body.appendChild(c); c.hass = {states: h, callService: () => {}};
  const r = c.shadowRoot; return {text: r.querySelector('ha-card').innerText.replace(/\\s+/g, ' ').trim(),
    links: [...r.querySelectorAll('a')].map((a) => a.href), wide: document.documentElement.scrollWidth}; }"""
LEG = {"pairing": "H9001", "leg": "1 of 2", "flight": "HA9001", "date": "2026-11-26", "origin": "HNL", "dest": "PPG",
       "dep_sched": "16:30 local, 16:30 HST", "arr_sched": "21:55 local, 22:55 HST", "block": "5:25", "report": "15:30",
       "status": "Scheduled", "status_as_of": "2026-11-10 01:30 HST", "next": "HA9002 PPG-HNL 2026-11-27",
       "flightaware_url": "https://www.flightaware.com/live/flight/HAL9001", "sigwx_url": "javascript:alert(1)",
       "updated": "2026-11-10 01:30 HST"}


def test_working_card_says_why_there_is_no_flight_and_shows_a_leg():
    src = _src("working-card")
    months = {"2026-11": {"items": []}}
    cases = [
        ("unread", f"({WORK_JS})({json.dumps({'sensor.flight_watcher_working_flight': _st('No trip', {'next': '', 'updated': '2026-11-10 01:30 HST'}), 'sensor.flight_watcher_schedule': _st('unknown')})})"),
        ("notrip", f"({WORK_JS})({json.dumps({'sensor.flight_watcher_working_flight': _st('No trip', {'next': 'H9005 2026-12-02'}), 'sensor.flight_watcher_schedule': _st('Nov 9', {'months': months})})})"),
        ("leg", f"({WORK_JS})({json.dumps({'sensor.flight_watcher_working_flight': _st('HA9001 HNL-PPG', LEG), 'sensor.flight_watcher_schedule': _st('Nov 9', {'months': months})})})"),
    ]
    got = _run(cases, src)
    assert "your FLICA schedule has not been read" in got["unread"]["text"]
    assert "No trip on your schedule right now." in got["notrip"]["text"] and "Next: H9005" in got["notrip"]["text"]
    leg = got["leg"]
    assert leg["text"].startswith("Working flight HA9001 HNL → PPG H9001 leg 1 of 2") and "Report: 15:30" in leg["text"]
    assert "16:30 local, 16:30 HST" in leg["text"] and "Next: HA9002" in leg["text"]
    assert leg["links"] == ["https://www.flightaware.com/live/flight/HAL9001"]  # a non-https link is never drawn
    assert leg["wide"] <= 390


CH_JS = """async (h) => { const c = document.createElement('flight-watcher-charters-card'); c.setConfig({});
  document.body.appendChild(c); c.hass = {states: h, callService: async (d, s, data) => window.calls.push([d, s, data])};
  const r = c.shadowRoot, b = r.getElementById('scan');
  const out = {st: r.getElementById('st').textContent, cls: r.getElementById('st').className, dis: b.disabled,
               bh: b.getBoundingClientRect().height, text: r.querySelector('ha-card').innerText};
  if (!b.disabled) { b.click(); await new Promise((ok) => setTimeout(ok, 20)); }
  out.calls = window.calls; out.msg = (r.getElementById('msg') || {}).textContent || ''; return out; }"""
REFUSED = ("CrewTrac refused your user ID or password at 01:29 HST. No more tries until you save new CrewTrac details "
           "in Settings.")


def test_charters_card_tells_crewtrac_refusal_and_turns_scan_off():
    src = _src("charters-card")
    item = {"date": "2026-11-20", "flight": "HA9901", "route": "HNL-PPT", "scheduled": "08:00", "eqpt": "332",
            "tail": "N900XX", "why": "99xx", "first_seen": "Nov 9"}
    cases = [
        ("refused", f"({CH_JS})({json.dumps({'sensor.flight_watcher_charters': _st('0', {'items': [], 'status': REFUSED, 'last_scan': '', 'crewtrac': {'state': 'refused', 'at': '2026-11-10T01:29:00-10:00', 'next_try': ''}})})})"),
        ("none", f"({CH_JS})({json.dumps({'sensor.flight_watcher_charters': _st('0', {'items': [], 'status': 'Enter your CrewTrac user ID and password in Settings.', 'crewtrac': {'state': 'not_configured'}})})})"),
        ("ok", f"({CH_JS})({json.dumps({'sensor.flight_watcher_charters': _st('1', {'items': [item], 'status': 'ok: 40 rows, 1 unusual A330, 0 new', 'last_scan': '2026-11-10T11:00:00+00:00', 'crewtrac': {'state': 'ok'}})})})"),
    ]
    got = _run(cases, src)
    r = got["refused"]
    assert r["st"] == REFUSED and "bad" in r["cls"] and r["dis"] and r["calls"] == []
    assert "Off until CrewTrac details that work are saved on the Settings tab." in r["text"]
    assert got["none"]["dis"] and "Settings tab" in got["none"]["st"]
    ok = got["ok"]
    assert ok["st"] == "CrewTrac OK." and not ok["dis"] and ok["bh"] >= 44
    assert "HA9901 HNL-PPT" in ok["text"] and "Last scan Nov 10 01:00 HST." in ok["text"]
    assert ok["calls"] == [["button", "press", {"entity_id": "button.flight_watcher_scan_crewtrac_charters_now"}]]
    assert ok["msg"].startswith("Asked for a scan.")


def test_requests_card_lists_requests_newest_first_in_hst():
    src = _src("requests-card")
    reqs = [{"date": "10/25", "time": "19:54", "type": "Add", "status": "Approved", "trips": ["H9001"]},
            {"date": "11/02", "time": "08:05", "type": "Trade", "status": "Pending", "trips": []},
            {"date": "11/01", "time": "23:10", "type": "Drop", "status": "Denied", "trips": ["H9002"],
             "folder": "close-in"}]
    js = f"""(() => {{ const c = document.createElement('flight-watcher-requests-card'); c.setConfig({{}});
      document.body.appendChild(c); c.hass = {{states: {json.dumps({'sensor.flight_watcher_ot_requests': _st('3', {'count': 3, 'pending': 1, 'requests': reqs, 'checked_at': '2026-11-10T11:19:12+00:00'})})}}};
      const r = c.shadowRoot; return {{rows: [...r.querySelectorAll('.r')].map((x) => x.innerText.replace(/\\s+/g, ' ').trim()),
        head: r.querySelector('.hd').innerText, wide: document.documentElement.scrollWidth}}; }})()"""
    got = _run([("r", js)], src)["r"]
    assert got["rows"] == ["Pending Trade Nov 2 08:05 HST", "Denied Drop H9002 Nov 1 23:10 HST · close-in",
                           "Approved Add H9001 Oct 25 19:54 HST"]
    assert "3 requests, 1 pending" in got["head"] and "read Nov 10 01:19 HST" in got["head"] and got["wide"] <= 390


CLOCK_JS = """(h) => { const c = document.createElement('flight-watcher-clock-card'); c.setConfig({});
  document.body.appendChild(c); c.hass = {states: h, callService: (d, s, data) => window.calls.push([d, s, data])};
  const r = c.shadowRoot, q = (i) => r.getElementById(i);
  const hs = q('hs'), vis = (e) => e.style.display !== 'none';
  return {lt: q('lt').textContent, nt: q('nt').textContent, st: q('st').textContent, msg: q('msg').textContent,
          opts: [...hs.options].map((o) => o.value), hsShown: vis(hs), hst: q('hst').textContent, val: hs.value,
          nopts: [...q('ns').options].map((o) => o.value), rearm: vis(q('rearm')),
          heights: [...r.querySelectorAll('button, select')].filter(vis).map((e) => Math.round(e.getBoundingClientRect().height)),
          wide: document.documentElement.scrollWidth}; }"""


def _clock_states(st="hunting", hs="40", hmin=5, hmax=90, nmin=1, nmax=90):
    return {"sensor.flight_watcher_state": _st(st, {"note": "", "role": "pilot"}),
            "sensor.flight_watcher_last_check": _st("2026-11-10T11:29:30+00:00"),
            "sensor.flight_watcher_next_check": _st("2026-11-10T11:30:40+00:00"),
            "switch.flight_watcher_hunt_mode": _st("on"), "switch.flight_watcher_pause": _st("off"),
            "number.flight_watcher_hunt_check_every": _st(hs, {"min": hmin, "max": hmax, "step": 5}),
            "number.flight_watcher_normal_check_every": _st("6", {"min": nmin, "max": nmax, "step": 1})}


HUNT_OPTS = ["5", "10", "15", "20", "30", "45", "60", "90"]
NORM_OPTS = ["1", "2", "3", "5", "6", "10", "15", "20", "30", "45", "60", "90"]


def test_clock_card_hst_touch_targets_and_the_intervals_a_pilot_has():
    """Ryan 2026-11-10: hunt 5 to 90 s and normal 1 to 90 min on every instance; a portal pilot's normal stops at 20 min
    (his number entity says 20, and the portal copy caps it at contract 1's 20 even if an entity said more)."""
    src = _src("clock-card")
    portal = PT.portal_card(src)
    assert portal != src  # the clock card has the FW_PORTAL flag
    admin = [("admin", f"({CLOCK_JS})({json.dumps(_clock_states())})")]
    pilot = [("pilot", f"({CLOCK_JS})({json.dumps(_clock_states(hs='10', nmax=20))})"),
             ("down", f"({CLOCK_JS})({json.dumps(_clock_states(st='unavailable'))})"),
             ("needs", f"({CLOCK_JS})({json.dumps(_clock_states(st='needs_settings'))})"),
             ("wide", f"({CLOCK_JS})({json.dumps(_clock_states(hs='5'))})")]
    ha = _run(admin + [("pilot", f"({CLOCK_JS})({json.dumps(_clock_states(hs='10'))})")], src, tz="Asia/Tokyo")
    po = _run(pilot, portal, tz="America/Los_Angeles")  # the phone on a Tokyo layover / in LA: still HST
    a = ha["admin"]
    assert a["lt"] == "01:29:30 HST" and a["nt"] == "01:30:40 HST"
    assert a["opts"] == ["5", "10", "15", "20", "30", "40", "45", "60", "90"] and a["val"] == "40"  # 40 in its place
    assert a["nopts"] == NORM_OPTS  # 1 to 90 min on the admin's HA dashboard
    assert min(a["heights"]) >= 44 and a["wide"] <= 390
    assert ha["pilot"]["opts"] == HUNT_OPTS and ha["pilot"]["nopts"] == NORM_OPTS  # a pilot on HA: the same ranges
    p = po["pilot"]
    assert p["lt"] == "01:29:30 HST" and p["hsShown"] and p["opts"] == HUNT_OPTS and p["val"] == "10"
    assert p["nopts"] == NORM_OPTS[:8] and p["nopts"][-1] == "20"  # the portal sends normal up to 20 min (contract 1)
    assert po["wide"]["nopts"] == NORM_OPTS[:8] and po["wide"]["val"] == "5"  # capped at 20 even if the entity says 90
    assert min(p["heights"]) >= 44
    d = po["down"]
    assert "Settings > Apps" not in d["msg"] and "admin" in d["msg"] and d["st"] == "Watcher not answering."
    n = po["needs"]
    assert n["st"] == "Needs your FLICA login." and "Settings tab" in n["msg"] and "Re-arm" not in n["msg"] and not n["rearm"]


def test_schedule_card_follows_the_month_helper_and_keeps_hpa_to_the_admin():
    src = _src("schedule-card")
    js = """(role) => { const c = document.createElement('flight-watcher-schedule-card'); c.setConfig({});
      document.body.appendChild(c);
      const st = (m) => ({'sensor.flight_watcher_schedule': {state: 'Nov 9', last_updated: 'a', attributes: {months: {
          '2026-11': {items: [], days: [['2026-11-26', '', '']], totals: {}, updated: 'Nov 9'}}}},
        'input_number.flight_watcher_month_offset': {state: String(m), last_updated: null, attributes: {}},
        'sensor.flight_watcher_state': {state: 'idle', last_updated: 'a', attributes: {role: role}}});
      c.hass = {states: st(0), user: {is_owner: role === 'admin'}, callService: () => {}};
      const h3 = () => c.shadowRoot.querySelector('h3').textContent;
      const a = h3(); c.hass = {states: st(1), user: {is_owner: role === 'admin'}, callService: () => {}};
      return {a, b: h3(), html: c.shadowRoot.innerHTML, fetches: window.fetches}; }"""
    got = _run([("pilot", f"({js})('pilot')"), ("admin", f"({js})('admin')")], src)
    p = got["pilot"]
    assert p["a"] == "November 2026" and p["b"] == "December 2026"  # same last_updated (null), new state
    assert "HPA" not in p["html"] and not [u for u in p["fetches"] if "school_" in u]
    assert "hatched yellow = US or Hawaii holiday" in p["html"]
    ad = got["admin"]
    assert "yellow = no school at HPA" in ad["html"] and [u for u in ad["fetches"] if "school_" in u]


def test_portal_settings_card_speaks_of_the_portal_and_shows_crewtrac():
    src = PT.portal_card(_src("settings-card"))
    js = f"""(() => {{ const c = document.createElement('flight-watcher-settings-card'); c.setConfig({{}});
      document.body.appendChild(c);
      c.hass = {{states: {json.dumps({'sensor.flight_watcher_settings': _st('True', {'username': 'doej', 'has_password': True}), 'sensor.flight_watcher_state': _st('hunting'), 'sensor.flight_watcher_charters': _st('0', {'status': REFUSED, 'crewtrac': {'state': 'refused'}})})}, callService: () => {{}}}};
      const r = c.shadowRoot; return {{note: r.querySelector('.note').textContent.replace(/\\s+/g, ' '),
        ct: r.getElementById('ct').textContent, cls: r.getElementById('ct').className}}; }})()"""
    got = _run([("s", js)], src)["s"]
    assert got["note"].startswith("Encrypted in your browser; only your Watcher can read it")
    assert "Home Assistant" not in got["note"] and "restarts your Watcher" in got["note"]
    assert got["ct"] == REFUSED and "err" in got["cls"]
    assert "Saved on this Home Assistant only" in _src("settings-card")  # the HA card keeps its own words


def test_portal_copies_drop_ha_era_wording():
    imp = _src("improved-card")
    assert "0.9.0" not in imp and "A month shows here once" in imp
    finds = _src("finds-card")
    js = """(() => { const c = document.createElement('flight-watcher-finds-card'); c.setConfig({});
      document.body.appendChild(c);
      c.hass = {states: {'sensor.flight_watcher_finds': {state: '0', last_updated: 'a', attributes: {count: 0,
        finds: [], file_key: '0'.repeat(32), rev: 'r'}}}, callService: () => {}};
      return c.shadowRoot.querySelector('details.key').textContent; })()"""
    ha = _run([("k", js)], finds)["k"]
    po = _run([("k", js)], PT.portal_card(finds))["k"]
    assert "alert email" in ha and "smart.json" in ha
    assert "alert email" not in po and "smart.json" not in po and "Pickup Speed" in po


def test_pilot_card_read_time_is_hst_on_any_phone():
    src = _src("pilot-card")
    js = """(() => { const E = 'sensor.flight_watcher_pilot_schedule'; const c = document.createElement('flight-watcher-pilot-card');
      c.setConfig({entity: E}); document.body.appendChild(c);
      c.hass = {states: {[E]: {state: 'x', last_updated: 'a', attributes: {emp: '10001', name: 'Doe, Jane', month: '2026-11',
        days: [], items: [], totals: {}, updated: 'Nov 10', status: 'ok', fetched: '2026-11-10T11:40:00+00:00'}}},
        callService: () => {}};
      return c.shadowRoot.querySelector('.hd .u').textContent; })()"""
    got = _run([("p", js)], src, tz="UTC")["p"]
    assert "read Nov 10 01:40 HST" in got


# ---------------------------------------------------------------- 1.6.2 review
def test_clock_card_shows_the_budget_note_and_no_stuck_during_a_budget_wait():
    src = PT.portal_card(_src("clock-card"))
    note = ("FLICA budget: 100 page loads in the last hour; the next one waits until 01:44 HST; FLICA tradeboard read "
            "paused until 02:00 HST: tradeboard: unknown page")
    wait = _clock_states(hs="90", nmax=20)
    wait["sensor.flight_watcher_state"] = _st("hunting", {"note": note, "role": "pilot"})
    wait["sensor.flight_watcher_last_check"] = _st("2026-11-10T11:18:51+00:00")  # 11 min 9 s old
    wait["sensor.flight_watcher_next_check"] = _st("2026-11-10T11:44:00+00:00")  # the gate's wait, ahead
    brk = _clock_states(hs="90", nmax=20)
    brk["sensor.flight_watcher_state"] = _st("hunting", {"note": "FLICA grid read paused until 02:00 HST: x",
                                                         "role": "pilot"})
    login = _clock_states()
    login["sensor.flight_watcher_state"] = _st("hunting", {"note": "logged in (re-arm)", "role": "pilot"})
    got = _run([("wait", f"({CLOCK_JS})({json.dumps(wait)})"), ("brk", f"({CLOCK_JS})({json.dumps(brk)})"),
                ("login", f"({CLOCK_JS})({json.dumps(login)})")], src)
    w = got["wait"]
    assert w["st"] == "Waiting." and w["msg"].startswith("Waiting for the FLICA budget until 01:44 HST.")
    assert "tradeboard read paused until 02:00 HST" in w["msg"] and "Stuck" not in w["msg"] and not w["rearm"]
    assert got["brk"]["st"] == "Hunting." and "FLICA grid read paused until 02:00 HST" in got["brk"]["msg"]
    assert got["login"]["msg"] == "Checking about every 40 s."  # a login note is no news


def test_clock_card_says_a_held_hunt_plainly():
    """Ryan 2026-11-10: a pilot's hunt his 100 FLICA loads an hour holds says so in the clock card, in the Watcher's
    words (held_note), with the next check's time; never "Stuck" or Re-arm while it waits."""
    src = PT.portal_card(_src("clock-card"))
    held = "Hunting every 10 s is held to 100 FLICA loads an hour: checks wait for the budget"
    pace = _clock_states(hs="10", nmax=20)
    pace["sensor.flight_watcher_state"] = _st("hunting", {"note": held + ", at least 89 s apart", "role": "pilot"})
    pace["sensor.flight_watcher_next_check"] = _st("2026-11-10T11:31:10+00:00")
    wait = _clock_states(hs="10", nmax=20)
    wait["sensor.flight_watcher_state"] = _st("hunting", {
        "note": held + " (next at 01:44 HST); FLICA grid read paused until 02:00 HST: x", "role": "pilot"})
    wait["sensor.flight_watcher_last_check"] = _st("2026-11-10T11:18:51+00:00")  # 11 min old: no "Stuck"
    wait["sensor.flight_watcher_next_check"] = _st("2026-11-10T11:44:00+00:00")
    run = _clock_states(hs="10", nmax=20)  # the check it held is running: next_check is behind
    run["sensor.flight_watcher_state"] = _st("hunting", {"note": held + ", at least 89 s apart", "role": "pilot"})
    run["sensor.flight_watcher_next_check"] = _st("2026-11-10T11:29:59+00:00")
    norm = _clock_states(hs="10", nmax=20)
    norm["switch.flight_watcher_hunt_mode"] = _st("off")
    norm["sensor.flight_watcher_state"] = _st("idle", {"note": "Checking every 1 min is held to 100 FLICA loads an hour: "
                                                       "checks wait for the budget, at least 89 s apart", "role": "pilot"})
    hung = _clock_states(hs="10", nmax=20)  # a held note on a Watcher that stopped checking is still "Stuck"
    hung["sensor.flight_watcher_state"] = _st("hunting", {"note": held + ", at least 89 s apart", "role": "pilot"})
    hung["sensor.flight_watcher_last_check"] = _st("2026-11-10T11:18:51+00:00")
    hung["sensor.flight_watcher_next_check"] = _st("2026-11-10T11:20:30+00:00")
    got = _run([(k, f"({CLOCK_JS})({json.dumps(v)})") for k, v in
                (("pace", pace), ("wait", wait), ("run", run), ("norm", norm), ("hung", hung))], src)
    p, w, r, n = got["pace"], got["wait"], got["run"], got["norm"]
    assert got["hung"]["st"] == "Stuck." and got["hung"]["rearm"]
    assert p["st"] == "Slowed." and p["msg"] == held + ", at least 89 s apart. Next check 01:31 HST."
    assert w["st"] == "Slowed." and w["msg"] == held + ". Next check 01:44 HST. FLICA grid read paused until 02:00 HST: x."
    assert not w["rearm"] and "Stuck" not in w["msg"]
    assert r["st"] == "Slowed." and r["msg"] == held + ", at least 89 s apart."
    assert n["st"] == "Slowed." and n["msg"].startswith("Checking every 1 min is held to 100 FLICA loads an hour")


def test_the_settings_tab_has_both_intervals_and_says_the_budget_slows_short_hunts():
    """Ryan 2026-11-10: the Hunt tile is back (5 to 90 s, all of which contract 1 sends); no markdown line speaks of a
    120 s or 2 min floor; the Watcher keeps a pilot within 100 FLICA loads an hour, so very short hunts are slowed."""
    settings = _tab("settings")
    names = {c.get("entity", ""): c.get("name") for c in settings if c["type"] == "tile"}
    assert names["number.flight_watcher_{name}_hunt_check_every"] == "Hunt: check every"
    assert names["number.flight_watcher_{name}_normal_check_every"] == "Normal: check every"
    md = [c["content"] for t in _layout()["tabs"] for c in t["cards"] if c["type"] == "markdown"]
    assert not [m for m in md if re.search(r"\b120 s\b|\b2 min\b|fastest for a pilot", m)], md
    line = next(c["content"] for c in settings if c["type"] == "markdown")
    assert "5 to 90 s" in line and "1 to 20 min" in line
    assert "within 100 FLICA page loads an hour, so very short hunts are slowed automatically" in line
    help_md = next(c["content"] for c in _tab("watcher") if c["type"] == "markdown")
    assert "within 100 FLICA page loads an hour, so very short hunts are slowed automatically" in help_md
    assert "a press within 10 s of the last check is ignored" in help_md
    # every value the sliders offer passes the contract as sent: hunt is the same range, normal stops at 20 on a portal
    assert roles.WATCHER_FREQ_LIMITS["hunt_s"] == roles.FREQ_LIMITS["hunt_s"]
    assert roles.entity_freq_limits("pilot2", portal=True) == roles.FREQ_LIMITS
    watcher = [c.get("entity", "") for c in _tab("watcher")]
    for gone in ("_state", "_last_check", "_next_check"):  # the clock card shows them
        assert not [e for e in watcher if e.startswith("sensor.") and e.endswith(gone)], gone
    md = next(c["content"] for c in _tab("watcher") if c["type"] == "markdown")
    assert "and your schedule too unless a schedule read is backing off" in md


def test_a_clamped_frequency_says_so_in_the_result(monkeypatch, tmp_path):
    import sys
    monkeypatch.setenv("FLIGHT_WATCHER_DATA", str(tmp_path))
    monkeypatch.setenv("FLIGHT_WATCHER_INSTANCE", "pilot2")
    monkeypatch.setenv("FLIGHT_WATCHER_PREFIX", "flight_watcher_pilot2")
    (tmp_path / "options.json").write_text(json.dumps({"username": "u", "password": "p"}))
    sys.modules.pop("watcher", None)
    import watcher as W
    try:  # Ryan 2026-11-10: every value contract 1 passes is inside the Watcher's ranges, so nothing it sends is moved
        assert W.freq_clamp_note("freq/hunt_s/set", "60") == "" and W.freq_clamp_note("freq/hunt_s/set", "5") == ""
        assert W.freq_clamp_note("freq/normal_min/set", "1") == "" and W.freq_clamp_note("freq/normal_min/set", "20") == ""
        assert W.freq_clamp_note("freq/hunt_s/set", "3") == "set to 5 s, the fastest this Watcher allows"
        assert W.freq_clamp_note("freq/normal_min/set", "95") == "set to 90 min, the slowest this Watcher allows"
        assert W.freq_clamp_note("freq/normal_min/set", "6") == "" and W.freq_clamp_note("hunt/set", "ON") == ""
    finally:
        sys.modules.pop("watcher", None)


def test_working_card_on_a_trip_with_unread_legs_and_no_updated_line_without_a_schedule():
    src = _src("working-card")
    months = {"2026-11": {"items": []}}
    cases = [  # today Nov 10 HST: H9681 started Nov 9
        ("on", f"({WORK_JS})({json.dumps({'sensor.flight_watcher_working_flight': _st('No trip', {'next': 'H9681 SYD 2026-11-09', 'updated': '2026-11-10 01:30 HST'}), 'sensor.flight_watcher_schedule': _st('Nov 9', {'months': months})})})"),
        ("unread", f"({WORK_JS})({json.dumps({'sensor.flight_watcher_working_flight': _st('No trip', {'next': '', 'updated': '2026-11-10 01:30 HST'}), 'sensor.flight_watcher_schedule': _st('unknown')})})"),
    ]
    got = _run(cases, src)
    assert "On H9681: its legs are not read yet." in got["on"]["text"] and "right now" not in got["on"]["text"]
    assert "From your FLICA schedule, updated" in got["on"]["text"]
    assert "has not been read" in got["unread"]["text"] and "From your FLICA schedule" not in got["unread"]["text"]


def test_charters_card_says_not_scanned_yet_instead_of_a_clean_result():
    src = _src("charters-card")
    cases = [
        ("refused", f"({CH_JS})({json.dumps({'sensor.flight_watcher_charters': _st('0', {'items': [], 'status': REFUSED, 'last_scan': '', 'crewtrac': {'state': 'refused'}})})})"),
        ("fresh", f"({CH_JS})({json.dumps({'sensor.flight_watcher_charters': _st('0', {'items': [], 'status': '', 'last_scan': '', 'crewtrac': {'state': ''}})})})"),
        ("clean", f"({CH_JS})({json.dumps({'sensor.flight_watcher_charters': _st('0', {'items': [], 'status': 'ok: 40 rows', 'last_scan': '2026-11-10T11:00:00+00:00', 'crewtrac': {'state': 'ok'}})})})"),
    ]
    got = _run(cases, src)
    assert "No unusual A330 flying found" not in got["refused"]["text"] + got["fresh"]["text"]
    assert "Not scanned yet." in got["fresh"]["text"]
    assert "No unusual A330 flying found (scanned Nov 10 01:00 HST)." in got["clean"]["text"]


def test_pilot_search_placeholder_says_what_a_pilots_lookup_takes():
    src = _src("pilot-search-card")
    js = """(role) => { const c = document.createElement('flight-watcher-pilot-search-card'); c.setConfig({});
      document.body.appendChild(c); c.hass = {states: {'sensor.flight_watcher_state': {state: 'idle', attributes: {role}}}};
      const p = c.shadowRoot.querySelector('input').placeholder; c.remove(); return p; }"""
    got = _run([("pilot", f"({js})('pilot')"), ("admin", f"({js})('admin')")], src)
    assert got["pilot"] == "Last name (3+ letters), Last, First, or employee #" and "first name" not in got["pilot"]
    assert got["admin"] == "Anybody's schedule: last name, first name or employee #"  # the admin's crew directory
