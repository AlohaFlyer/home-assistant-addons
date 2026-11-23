"""1.8.1 (Ryan, Nov 23, 2026: "Always look for the new pot each month. It's a different bcid"; "I'm working on Dec
now"): the open time pot follows the bid month. Each check reads the pot page of the bid month(s) the Pot month select
chooses (This month, Next month, Both), from that month's own BCID: learned (Ryan's two links, then each month whose
page read with its own trips), named by a menu or pot page link, or derived from the latest learned month. A page of
another month's trips is refused. FLICA is never reached: a fake browser answers with synthetic pages (made-up
pairings H39xx, no names)."""
import json
import os
import sys
import types
from datetime import datetime, timedelta, timezone

import pytest

import pot as P
import roles
from test_release_a_flica import mk, real_fl  # noqa: F401

HST = timezone(timedelta(hours=-10))
BASE = "https://ha2.flica.net"
NOT_OPEN = "<html><body>flica.net - Invalid or unspecified bid period</body></html>"
STUBS = ("schedule_check", "own_trip_times", "publish_working_flight", "versions_check", "uploads_check", "capture",
         "detail_probe", "pot_details", "email_check", "pickup_check", "tradeboard_check", "requests_check",
         "grid_check", "publish_finds", "publish_tickets", "enrich", "swap_scan", "drop_scan", "publish_near_misses")


def at(y, m, d, h=12, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=HST).timestamp()


def page(rows=(), links=()):
    """A synthetic mobile open time page: rows (pairing, start 'DDMon'), links (bcid, text)."""
    trs = "".join(f"<tr><td>{p}</td><td>{s}</td><td>{s}</td><td>6.10</td><td>-none-</td><td></td><td></td>"
                  f"<td>09:00</td><td>15:00</td><td>1</td><td></td></tr>" for p, s in rows)
    a = "".join(f'<a href="mobileopentimepot.cgi?BCID={b}&amp;From=MainMenu">{t}</a> ' for b, t in links)
    return f"<html><body><h3>Open Time Pot HNL 332 FO</h3>{a}<table>{trs}</table></body></html>"


NOV = [("H3901", "26Nov"), ("H3902", "28Nov")]
DEC = [("H3911", "03Dec"), ("H3912", "12Dec"), ("H3913", "20Dec")]
JAN = [("H3921", "04Jan"), ("H3922", "15Jan")]


def _w(mk, t, mode=None, pages=None):
    W = mk("", t=t)
    for f in STUBS:
        setattr(W, f, lambda *a, **k: None)
    W.close_in_check = lambda *a, **k: ({}, "ok")
    W.crew_index_check = lambda *a, **k: "ok"
    if mode:
        W.S["pot_month"] = mode
    W.S["pot_urls"] = {}
    pages = {} if pages is None else pages
    fl = real_fl(W, lambda u: pages.get(W.bcid(u), NOT_OPEN) if "opentimepot" in u else "<html><body>x</body></html>")
    return W, fl, pages


def _pot_loads(W, fl):
    return [W.bcid(u) for _, u in fl.loads if "mobileopentimepot" in u]


def _check(W, fl, step=600):
    """One check; the pot pages it fetched (BCIDs, in order)."""
    n = len(_pot_loads(W, fl))
    W.RUN.update(check=True, aborted="", skipped=set())
    try:
        res = W.check(fl)
    finally:
        W.RUN["check"] = False
    W.CLOCK.t += step
    return res, _pot_loads(W, fl)[n:]


def _new(W):
    return [json.loads(p)["pairing"] for t, p in W.MQ.msgs if t == f"{W.T}/event/new_pairing"]


# ---------------------------------------------------------------- D1: the BCID of a month
def test_pot_bcid_follows_the_bid_month_from_the_anchor(mk):
    W = mk("")
    assert W.POT_BCID_ANCHOR == ((2026, 11), "003", 152)
    assert [W.pot_bcid(*ym) for ym in ((2026, 11), (2026, 12), (2027, 1), (2027, 12))] == \
        ["003.152", "003.153", "003.154", "003.165"]
    assert W.pot_bcid(2027, 3, ((2027, 1), "003", 160)) == "003.162"  # from another anchor (a month learned)
    assert W.mobile_pot_url("003.153") == f"{BASE}/full/mobileopentimepot.cgi?BCID=003.153&From=MainMenu"
    assert "otframe" not in W.mobile_pot_url("003.153") and W.close_in_url("008.153") == W.mobile_pot_url("008.153")
    assert not hasattr(W, "MOBILE_POT")  # 1.8.0's hard-coded November page is gone
    src = open(os.path.join(os.path.dirname(W.__file__), "watcher.py"), encoding="utf-8").read()
    assert "BCID=003.152&From" not in src


def test_a_page_counts_for_a_month_only_with_its_own_trips():
    assert P.pot_month_check(page(DEC), "2026-12")["verdict"] == "ok"
    r = P.pot_month_check(page(NOV), "2026-12")
    assert r["verdict"] == "refused" and r["other"] == "2026-11" and r["dated"] == 2
    assert r["inside"] == 1  # 28Nov: inside the 3 day slack of a bid period's edge
    assert P.pot_month_check(page(), "2026-12")["verdict"] == "empty"  # an empty pot names no month
    assert P.pot_month_check(NOT_OPEN, "2026-12")["verdict"] == "not open"
    # a bid period's edge (November's runs Nov 1 to Dec 1) and one odd row are no refusal
    assert P.pot_month_check(page(NOV + [("H3903", "01Dec")]), "2026-11")["verdict"] == "ok"
    assert P.pot_month_check(page(DEC + [("H3904", "20Nov")]), "2026-12")["verdict"] == "ok"
    assert P.pot_month_check(page([("H3921", "04Jan")]), "2027-01")["verdict"] == "ok"  # the year from the month
    assert P.pot_month_check(page(DEC), "2027-01")["verdict"] == "refused"


# ---------------------------------------------------------------- D2 and D3: the three modes across Nov 30 to Dec 1
def test_this_month_reads_one_page_a_check_and_rolls_to_december_without_alerts(mk):
    W, fl, pages = _w(mk, at(2026, 11, 30, 23, 30), pages={"003.152": page(NOV), "003.153": page(DEC)})
    assert W.pot_mode() == "This month"
    assert _check(W, fl) == ("ok", ["003.152"]) and _new(W) == []  # first read: its baseline only
    pages["003.152"] = page(NOV + [("H3905", "29Nov")])
    assert _check(W, fl, step=1800) == ("ok", ["003.152"]) and _new(W) == ["H3905"]
    assert W.local_now().day == 1  # Dec 1, 00:10 HST
    assert _check(W, fl) == ("ok", ["003.153"]) and _new(W) == ["H3905"]  # December's first read: no alert
    assert list(W.S["baseline"]) == ["2026-12"]  # November's baseline dropped as before
    pages["003.153"] = page(DEC + [("H3914", "24Dec")])
    assert _check(W, fl) == ("ok", ["003.153"]) and _new(W) == ["H3905", "H3914"]


def test_next_month_reads_december_now_and_keeps_it_after_dec_1_with_one_page_a_check(mk):
    W, fl, pages = _w(mk, at(2026, 11, 30, 23, 30), "Next month", {"003.152": page(NOV), "003.153": page(DEC)})
    assert _check(W, fl) == ("ok", ["003.153"]) and _new(W) == []
    assert list(W.S["pot_urls"]) == ["2026-12"]
    pages["003.153"] = page(DEC + [("H3914", "24Dec")])
    assert _check(W, fl, step=1800) == ("ok", ["003.153"]) and _new(W) == ["H3914"]
    # Dec 1: January (derived 003.154) is tried once in place of December's page (its rows of the check before)
    res, got = _check(W, fl)
    assert (res, got) == ("ok", ["003.154"]) and W.pot_status("2027-01") == "not open yet"
    rows = W.MQ.last(f"{W.T}/pot/state")
    assert rows["count"] == 4 and {r["pairing"] for r in rows["pairings"]} >= {"H3911", "H3914"}
    pages["003.153"] = page(DEC + [("H3914", "24Dec"), ("H3915", "27Dec")])
    for _ in range(3):  # December again, one page a check; its baseline carried through the try
        assert _check(W, fl)[1] == ["003.153"]
    assert _new(W) == ["H3914", "H3915"]
    W.CLOCK.t += 86400  # a day later January is tried again, and it opened with its trips: learned, read from now on
    pages["003.154"] = page(JAN)
    assert _check(W, fl)[1] == ["003.154"] and W.pot_learned()["2027-01"]["bcid"] == "003.154"
    assert _new(W) == ["H3914", "H3915"]  # January's first read is its baseline
    assert _check(W, fl)[1] == ["003.154"] and list(W.S["pot_urls"]) == ["2027-01"]
    assert list(W.S["baseline"]) == ["2027-01"]


def test_next_month_falls_back_to_this_month_while_the_next_page_is_refused(mk):
    W, fl, pages = _w(mk, at(2026, 12, 20), "Next month", {"003.153": page(DEC), "003.154": page(DEC)})
    assert _check(W, fl)[1] == ["003.153", "003.154"]  # the first try: no rows of December's on hand yet
    assert W.pot_status("2027-01") == "refused" and "2027-01" not in W.pot_learned()
    assert "January 2027 open time pot: BCID 003.154 refused (its trips start in December 2026)" in W.S["note"]
    assert list(W.S["pot_urls"]) == ["2026-12"] and _new(W) == []
    for _ in range(3):
        assert _check(W, fl)[1] == ["003.153"]  # this month's page, one a check, until the next try
    a = W.pot_months_attr()
    assert [(x["month"], x["bcid"], x["how"], x["status"], x["read"]) for x in a] == [
        ("2026-12", "003.153", "learned", "ok", True), ("2027-01", "003.154", "not found yet", "refused", False)]


def test_both_reads_this_and_next_once_open(mk):
    W, fl, pages = _w(mk, at(2026, 11, 30, 23, 30), "Both", {"003.152": page(NOV), "003.153": page(DEC)})
    assert _check(W, fl, step=1800) == ("ok", ["003.152", "003.153"]) and _new(W) == []
    assert _check(W, fl) == ("ok", ["003.153", "003.154"])  # Dec 1: December, and January's first try
    for _ in range(2):
        assert _check(W, fl)[1] == ["003.153"]  # January not open: tried again tomorrow
    assert _new(W) == []


def test_a_learned_month_keeps_its_bcid_when_a_read_refuses_it(mk):
    W, fl, pages = _w(mk, at(2027, 1, 10), pages={"003.154": page(JAN)})
    assert _check(W, fl)[1] == ["003.154"] and W.pot_learned()["2027-01"]["bcid"] == "003.154"
    pages["003.154"] = page(DEC)  # a page of another month's trips
    assert _check(W, fl)[1] == ["003.154"] and W.pot_status("2027-01") == "refused"
    assert W.pot_learned()["2027-01"]["bcid"] == "003.154" and "refused" in W.S["note"]
    assert _check(W, fl)[1] == [] and list(W.S["pot_urls"]) == []  # nothing read until its try (6 h)
    W.CLOCK.t += 6 * 3600
    pages["003.154"] = page(JAN)
    assert _check(W, fl)[1] == ["003.154"] and W.pot_status("2027-01") == "ok" and "refused" not in W.S["note"]


def test_a_month_is_derived_from_the_latest_learned_one(mk):
    """One renumbering by FLICA is learned once: January found on 003.160 (a link), February derives 003.161."""
    W, fl, pages = _w(mk, at(2027, 1, 2), pages={"003.153": page(DEC, links=[("003.160", "Jan")])})
    W.S["pot_month"] = "This month"
    assert W.pot_pick("2027-01") == ("003.154", "derived")
    assert _check(W, fl)[1] == ["003.154"] and W.pot_status("2027-01") == "not open yet"
    # a page that names January's pot (December's, its link 'Jan'): a candidate, read and checked, then learned
    assert W.pot_link_scan(page(DEC, links=[("003.160", "Jan"), ("008.154", "Close in Opentime")]),
                           W.mobile_pot_url("003.153"), "2026-12") is None
    assert W.S["pot_cands"] == {"2027-01": {"bcid": "003.160", "how": "link", "at": W.S["pot_cands"]["2027-01"]["at"]}}
    pages["003.160"] = page(JAN)
    assert _check(W, fl)[1] == ["003.160"] and W.pot_learned()["2027-01"]["how"] == "menu"
    assert W.pot_derive("2027-02") == "003.161" and W.pot_pick("2027-03") == ("003.162", "derived")


def test_the_close_in_folder_is_never_a_months_pot(mk):
    W, fl, pages = _w(mk, at(2026, 12, 5))
    W.S["close_in"] = {"bcid": "008.153", "verified": True}
    html = page(DEC, links=[("008.153", "Open time"), ("008.154", "Jan"), ("001.154", "Jan"),
                            ("003.154", "Close in Opentime: &lt;16 Hrs to RPT")])
    W.pot_link_scan(html, W.mobile_pot_url("003.153"), "2026-12")
    assert not W.S.get("pot_cands")
    assert not W.pot_cand("2027-01", "008.153", "menu", "main menu")  # a close-in BCID is never a candidate


# ---------------------------------------------------------------- D1b: the main menu look
class _Frame:
    def __init__(self, links):
        self.url = f"{BASE}/online/leftmenu.cgi"
        self._links = links

    def evaluate(self, js, sec):
        assert "View Opentime Pot" in js and sec == "OPEN TIME"
        return self._links

    def content(self):
        return "<html><body>menu</body></html>"


class _Page:
    def __init__(self, frames, html="<html></html>"):
        self.frames, self._html, self.url = frames, html, f"{BASE}/online/mainmenu.cgi"

    def goto(self, *a, **k):
        pass

    def content(self):
        return self._html

    def close(self):
        pass


def test_a_month_not_found_is_looked_for_on_the_main_menu_at_most_every_6_h(mk):
    W, fl, pages = _w(mk, at(2027, 1, 2), pages={"003.161": page(JAN)})
    W.OPTS["pot_section"] = "OPEN TIME"  # the add-on option's default
    links = [{"i": 0, "section": "OPEN TIME- Add/Swap/Drop requests", "month": "January",
              "href": "javascript:openOT('/full/otframe.cgi?BCID=003.161&ViewOT=1');"},
             {"i": 1, "section": "Close in Opentime: <16 Hrs to RPT", "month": "January", "href": "BCID=008.161"}]
    opened = []
    fl.ctx.new_page = lambda: opened.append(1) or _Page([_Frame(links)])
    fl.save = lambda: None
    gated = []
    real = fl._load
    fl._load = lambda url=None: gated.append(url) or real(url)
    assert _check(W, fl)[1] == ["003.154"] and not opened  # the derivation first: not open
    assert W.pot_look_months() == ["2027-01"]
    assert _check(W, fl)[1] == ["003.161"] and opened == [1]  # the menu names 003.161 (no click): read and checked
    assert W.pot_learned()["2027-01"] == {"bcid": "003.161", "how": "menu", "at": W.pot_learned()["2027-01"]["at"]}
    assert None in gated  # the main menu load went through the gate
    a = W.pot_months_attr()
    assert [(x["month"], x["bcid"], x["how"], x["status"]) for x in a] == [("2027-01", "003.161", "learned", "ok")]
    # a month whose pick is still not open is looked for again only 6 h later
    W2, fl2, _ = _w(mk, at(2027, 1, 2))
    W2.OPTS["pot_section"] = "OPEN TIME"
    opened2 = []
    fl2.ctx.new_page = lambda: opened2.append(1) or _Page([], "<html><body>going to forward</body></html>")
    for _ in range(4):
        _check(W2, fl2, step=1800)
    assert opened2 == [1]
    W2.CLOCK.t += 6 * 3600
    _check(W2, fl2)
    assert opened2 == [1, 1] and W2.S["machine"] != "stopped_unexpected"  # a menu that does not load is no stop


# ---------------------------------------------------------------- 1.8.0 pages carry over, the select, the attribute
def test_the_update_from_1_8_0_carries_the_november_baseline_over(mk):
    W, fl, pages = _w(mk, at(2026, 11, 23), pages={"003.152": page(NOV + [("H3906", "30Nov")])})
    W.S["baseline"] = {"mobile": ["H3901|26Nov", "H3902|28Nov"]}
    W.S["fingerprints"] = {"mobile": W.header_fingerprint(page(NOV))}
    W.pot_start()
    assert W.S["pot_plan"] and W.pot_mode() == "This month"
    assert _check(W, fl)[1] == ["003.152"] and _new(W) == ["H3906"]  # the trip that came during the update alerts
    assert sorted(W.S["baseline"]) == ["2026-11"] and "mobile" not in W.S["fingerprints"]


def test_the_select_is_restored_at_start_and_a_change_replans_and_wakes(mk, monkeypatch):
    W, fl, pages = _w(mk, at(2026, 11, 23), pages={"003.152": page(NOV), "003.153": page(DEC)})
    ent = {oid: (comp, cfg) for comp, oid, cfg, f in W.entity_defs()}
    comp, cfg = ent["pot_month"]
    assert comp == "select" and cfg["name"] == "Pot month" and cfg["options"] == ["This month", "Next month", "Both"]
    assert cfg["command_topic"] == "flight_watcher/pot_month/set"
    assert cfg["state_topic"] == "flight_watcher/pot_month/state"
    assert cfg["default_entity_id"] == "select.flight_watcher_pot_month"
    assert "pot_month/set" in roles.SUBS and "pot_month/set" not in roles.PORTAL_CMDS
    assert "pot_month/set" in roles.NOT_ON_PORTAL and not roles.entity_on_portal("pot_month", "james")
    assert _check(W, fl)[1] == ["003.152"]
    woke = []
    monkeypatch.setattr(W, "WAKE", types.SimpleNamespace(set=lambda: woke.append(1)))
    W.on_message(W.MQ, None, types.SimpleNamespace(topic=f"{W.T}/pot_month/set", payload=b"Next month"))
    assert W.S["pot_month"] == "Next month" and W.S["pot_urls"] == {} and woke == [1]
    assert [p for t, p in W.MQ.msgs if t == f"{W.T}/pot_month/state"][-1] == "Next month"
    W.on_message(W.MQ, None, types.SimpleNamespace(topic=f"{W.T}/pot_month/set", payload=b"Last month"))
    assert W.S["pot_month"] == "Next month" and woke == [1]  # ignored, its state said again
    assert _check(W, fl)[1] == ["003.153"] and _new(W) == []  # December's first read: no alert
    W.save_state(W.S)
    sys.modules.pop("watcher", None)
    import watcher as W2  # the next start reads the same state
    W2.MQ = W.MQ
    W2.pot_start()
    assert W2.pot_mode() == "Next month"
    W2.connect_states(W2.MQ)
    assert [p for t, p in W2.MQ.msgs if t == f"{W2.T}/pot_month/state"][-1] == "Next month"
    sys.modules.pop("watcher", None)


def test_the_state_attribute_says_which_months_are_read(mk):
    W, fl, pages = _w(mk, at(2026, 11, 23), "Next month", {"003.153": page(DEC)})
    _check(W, fl)
    a = json.loads([p for t, p in W.MQ.msgs if t == f"{W.T}/state_attr"][-1])
    assert a["pot_mode"] == "Next month"
    assert a["pot_months"] == [{"month": "2026-12", "name": "December 2026", "bcid": "003.153", "how": "learned",
                                "status": "ok", "read": True}]
    assert W.mirror_links()[0] == ("Open time", W.mobile_pot_url("003.153"))  # the mirror follows the page read
    assert W.pot_bcid_now() == "003.153"  # the swap map's pot and its 001.153 / 003.153 pages


def test_the_old_rediscovery_and_hard_coded_page_are_gone():
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "watcher.py"),
               encoding="utf-8").read()
    assert "rediscovering pot pages to look for the next bid month" not in src
    assert "def discover_pot_urls" not in src and "MOBILE_POT" not in src


# ---------------------------------------------------------------- D4: the clock card in Chromium
WWW = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "www")
CARD_PAGE = ("<!doctype html><html><head><meta name='viewport' content='width=device-width'><style>"
             ":root{%s}body{margin:0;background:var(--primary-background-color)}</style></head><body>"
             "<script>customElements.define('ha-card', class extends HTMLElement {});window.calls = [];</script>"
             "<script>%s</script></body></html>")
LIGHT = ("--primary-background-color:#fafafa;--card-background-color:#fff;--primary-text-color:#212121;"
         "--secondary-text-color:#555;--divider-color:#ccc")
DARK = ("--primary-background-color:#111;--card-background-color:#1c1c1c;--primary-text-color:#e1e1e1;"
        "--secondary-text-color:#9b9b9b;--divider-color:#444")


def _clock_states(mode="Next month", months=None, dark=False):
    st = lambda s, a=None: {"state": s, "attributes": a or {}, "last_updated": "2026-11-23T21:20:00+00:00"}  # noqa
    months = months if months is not None else [
        {"month": "2026-12", "name": "December 2026", "bcid": "003.153", "how": "learned", "status": "ok",
         "read": True}]
    return {"sensor.flight_watcher_state": st("idle", {"note": "", "role": "admin", "pot_mode": mode,
                                                         "pot_months": months}),
            "sensor.flight_watcher_last_check": st("2026-11-23T21:29:30+00:00"),
            "sensor.flight_watcher_next_check": st("2026-11-23T21:33:40+00:00"),
            "switch.flight_watcher_hunt_mode": st("off"), "switch.flight_watcher_pause": st("off"),
            "number.flight_watcher_hunt_check_every": st("40", {"min": 5, "max": 90, "step": 5}),
            "number.flight_watcher_normal_check_every": st("6", {"min": 1, "max": 90, "step": 1}),
            "select.flight_watcher_pot_month": st(mode, {"options": ["This month", "Next month", "Both"]})}


CARD_JS = """([h, dark]) => { const c = document.createElement('flight-watcher-clock-card'); c.setConfig({});
  document.body.appendChild(c);
  c.hass = {states: h, themes: {darkMode: dark}, callService: (d, s, data) => window.calls.push([d, s, data])};
  const r = c.shadowRoot, sel = r.getElementById('pm'), b = sel.getBoundingClientRect();
  return {wide: document.documentElement.scrollWidth, vw: window.innerWidth, h: b.height, w: b.width,
    shown: sel.style.display !== 'none', value: sel.value, opts: [...sel.options].map((o) => o.value),
    label: sel.parentElement.firstChild.textContent.trim(), months: r.getElementById('pmm').textContent,
    mode: r.getElementById('pmt').textContent, aria: sel.getAttribute('aria-label'),
    right: Math.max(...[...r.querySelectorAll('*')].map((x) => x.getBoundingClientRect().right))}; }"""


def _render(src, cases):
    sync_api = pytest.importorskip("playwright.sync_api")
    from test_cards import _chromium
    out = {}
    with sync_api.sync_playwright() as p:
        b = _chromium(p)
        if not b:
            pytest.skip("no Chromium for Playwright")
        try:
            for name, (width, dark, h, keys) in cases.items():
                ctx = b.new_context(viewport={"width": width, "height": 800}, timezone_id="Pacific/Honolulu",
                                    color_scheme="dark" if dark else "light")
                pg = ctx.new_page()
                pg.clock.set_fixed_time("2026-11-23T21:30:00Z")
                pg.set_content(CARD_PAGE % (DARK if dark else LIGHT, src))
                out[name] = pg.evaluate(f"({CARD_JS})", [h, dark])
                if keys:
                    pg.locator("#pm").focus()
                    for k in keys:
                        pg.keyboard.press(k)
                    out[name]["calls"] = pg.evaluate("window.calls")
                    out[name]["focused"] = pg.evaluate(
                        "document.querySelector('flight-watcher-clock-card').shadowRoot.activeElement.id")
                ctx.close()
        finally:
            b.close()
    return out


def test_the_clock_card_pot_select_on_a_phone_light_and_dark():
    import portal as PT
    src = open(os.path.join(WWW, "flight-watcher-clock-card.js"), encoding="utf-8").read()
    two = [{"month": "2026-12", "name": "December 2026", "bcid": "003.153", "how": "learned", "status": "ok",
            "read": True},
           {"month": "2027-01", "name": "January 2027", "bcid": "003.154", "how": "derived", "status": "not open yet",
            "read": False}]
    got = _render(src, {"light": (390, False, _clock_states(), ["ArrowDown"]),
                        "dark": (320, True, _clock_states("This month", two), ["ArrowDown"])})
    for k, v in got.items():
        assert v["wide"] <= v["vw"] and v["right"] <= v["vw"] + 0.5, (k, v)  # no horizontal scroll
        assert v["h"] >= 44 and v["w"] >= 44 and v["shown"], (k, v)  # a 44 px phone target
        assert v["opts"] == ["This month", "Next month", "Both"] and v["aria"] == "Pot month" and v["label"] == "Pot"
        assert v["focused"] == "pm"  # reached and worked from the keyboard
    assert got["light"]["value"] == "Next month" and got["light"]["months"] == "December 2026 (003.153)"
    assert got["light"]["calls"] == [["select", "select_option",
                                      {"entity_id": "select.flight_watcher_pot_month", "option": "Both"}]]
    assert got["dark"]["months"] == "December 2026 (003.153) · January 2027 not open yet"
    assert got["dark"]["calls"] == [["select", "select_option",
                                     {"entity_id": "select.flight_watcher_pot_month", "option": "Next month"}]]
    # the portal's copy: no select (no such portal command), the mode and the months as text, read only
    h = _clock_states()
    portal = _render(PT.portal_card(src), {"p": (390, False, h, None)})["p"]
    assert not portal["shown"] and portal["mode"] == "Next month" and portal["months"] == "December 2026 (003.153)"
    assert portal["wide"] <= portal["vw"]
