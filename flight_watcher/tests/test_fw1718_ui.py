"""1.7.18 (Nov 17), two card changes, in Chromium on synthetic data ("Doe, Jane", made-up files):

A. The uploads card's "On file" rows fold under their heading, folded by default: the heading is a button (44 px,
   aria-expanded, aria-controls) that says "On file (6)" and, while folded, one line on what is there ("6 files,
   newest Award Dec 2026, uploaded Nov 14"). Open or folded is kept per browser (localStorage, a pilot's copy under
   its own key, nothing when storage is blocked); Refresh keeps it. The Wanted line, Pilot uploads (its Approve and
   Reject), Dates of hire and Pilot contacts stay in view: they are sections of their own, not rows of the list.
B. The schedule card's version lock is a switch: a lock icon drawn as an inline SVG (never the emoji a Samsung drew
   its own way), the word Lock, a track and knob and the word On (locked, the default) or Off. One button with
   role switch, aria-checked and the name "Lock schedule marks"; the same title, the same localStorage key
   ("flight_watcher_lock", a pilot's copy its own) and the same taps as before. The Key says how it works.
Both at 390 px light and dark, B also on an Android-like phone (360 x 780 at 3x): no sideways scroll, WCAG AA text
and 3:1 for the switch's track, knob and edge. FW_AB_SHOTS=<dir> keeps the renders as itemAB_*.png."""
import contextlib
import copy
import json
import os
import re

import pytest

import cards
import portal as PT
from test_cards import _chromium
from test_fw171_cards import HARNESS_JS, PORTAL_CSS, _pilot
from test_pairing_panel_card import OWNER, PKG, states as sched_states

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ORIGIN = "https://ha.test"
NOW = "2026-11-17T22:00:00Z"  # Nov 17 12:00 HST
SHOTS = os.environ.get("FW_AB_SHOTS", "")
UP = "flight-watcher-uploads-card"
SC = "flight-watcher-schedule-card"
LOCK_EMOJI = ("&#128274;", "&#128275;", "\U0001F512", "\U0001F513")


@contextlib.contextmanager
def _browser():
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as p:
        b = _chromium(p)
        if not b:
            pytest.skip("no Chromium for Playwright")
        try:
            yield b
        finally:
            b.close()


def _page(b, srcs, width=390, height=844, scheme="light", dsf=2, uploads=None, init=None):
    """https://ha.test/ with the portal's theme and harness and the cards (each a module, as the loader imports them,
    so a pilot's copy sits beside the admin's); the pairings package for November, the ingress api/uploads answer
    uploads["data"] (counted in uploads["gets"]), everything else 404."""
    ctx = b.new_context(viewport={"width": width, "height": height}, device_scale_factor=dsf, color_scheme=scheme,
                        timezone_id="Pacific/Honolulu", is_mobile=dsf >= 3, has_touch=dsf >= 3)
    if init:
        ctx.add_init_script(init)
    html = ("<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<style>" + PORTAL_CSS + "</style></head><body><main><section class='view'></section></main><script>" + HARNESS_JS
            + "</script>" + "".join(f"<script type='module'>{s}</script>" for s in ([srcs] if isinstance(srcs, str) else srcs))
            + "</body></html>")

    def serve(route):
        url = route.request.url
        if url == ORIGIN + "/":
            return route.fulfill(status=200, content_type="text/html", body=html)
        if "/local/flight-watcher/pairings_2026-11.json" in url:
            return route.fulfill(status=200, content_type="application/json", body=json.dumps(PKG))
        if uploads is not None and url.endswith("/api/hassio_ingress/tok123/api/uploads"):
            uploads["gets"] = uploads.get("gets", 0) + 1
            return route.fulfill(status=200, content_type="application/json", body=json.dumps(uploads["data"]))
        return route.fulfill(status=404, body="")
    ctx.route(ORIGIN + "/**", serve)
    pg = ctx.new_page()
    pg.errors = []
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    pg.on("console", lambda m: pg.errors.append(m.text) if m.type == "error" and "Failed to load resource" not in m.text else None)
    pg.clock.set_fixed_time(NOW)
    pg.goto(ORIGIN + "/")
    return pg


def _q(pg, js, arg=None):
    return pg.evaluate("(arg) => { const r = C.shadowRoot, q = (s) => r.querySelector(s), qa = (s) => [...r.querySelectorAll(s)];"
                       " const vis = (e) => !!e && e.checkVisibility({checkVisibilityCSS: true}) && e.getClientRects().length > 0; "
                       + js + " }", arg)


def _shot(pg, name):
    if SHOTS:
        pg.mouse.move(1, 1)  # the resting look, not the pointer's hover
        os.makedirs(SHOTS, exist_ok=True)
        pg.screenshot(path=os.path.join(SHOTS, f"itemAB_{name}.png"), full_page=True)


def _store(pg, key):
    return pg.evaluate("(k) => localStorage.getItem(k)", key)


# ---------------------------------------------------------------- A: the uploads card's On file list
def _files(extra=False):
    f = [{"name": "2026-12_award.pdf", "kind": "award", "month": "2026-12", "day": "", "size": 812345,
          "uploaded_at": "2026-11-14T08:12:00-10:00", "has_text": True},
         {"name": "2026-12_pairings.pdf", "kind": "pairings", "month": "2026-12", "day": "", "size": 3456789,
          "uploaded_at": "2026-11-13T08:15:00-10:00", "has_text": True},
         {"name": "2026-11_award.pdf", "kind": "award", "month": "2026-11", "day": "", "size": 801234,
          "uploaded_at": "2026-10-18T08:12:00-10:00", "has_text": True},
         {"name": "2026-11_pairings.pdf", "kind": "pairings", "month": "2026-11", "day": "", "size": 3401234,
          "uploaded_at": "2026-10-18T08:15:00-10:00", "has_text": True},
         {"name": "seniority_2026-11-06.pdf", "kind": "seniority", "month": "", "day": "2026-11-06", "size": 456789,
          "uploaded_at": "2026-11-06T09:30:00-10:00", "has_text": True},
         {"name": "contacts_2026-11-07.csv", "kind": "contacts", "month": "", "day": "2026-11-07", "size": 3000,
          "uploaded_at": "2026-11-07T09:30:00-10:00", "has_text": True}]
    if extra:  # Refresh: a 7th file, the newest, that has no text copy
        f.append({"name": "2027-01_pairings.pdf", "kind": "pairings", "month": "2027-01", "day": "", "size": 3300000,
                  "uploaded_at": "2026-11-15T07:05:00-10:00", "has_text": False})
    return f


def _udata(extra=False):
    return {"version": "9.9.9", "max_bytes": 16711680, "mqtt_max_bytes": 25000000, "files": _files(extra),
            "wanted": [{"kind": "pairings", "month": "2027-02", "why": "current"}],
            "seniority": {"pilots": 12, "list_date": "2026-03-01", "uploaded_at": "2026-11-06T09:30:00-10:00", "source": "list",
                          "as_of": "2026-03-01", "rejects": 0, "carried": 0, "base": None},
            "contacts": {"count": 30, "with_phone": 28, "with_email": 25, "rejects": 0, "uploaded_at": "2026-11-07T09:30:00-10:00"},
            "pilot_uploads": [{"id": "u1", "kind": "pairings", "month": "2027-01", "who": "pilot2", "state": "pending",
                               "size": 3300000, "at": "2026-11-15T07:05:00-10:00", "sha": "ab12cd34"}]}


def _ustates(prefix="flight_watcher", extra=False, lu="t1"):
    d = _udata(extra)
    return {f"sensor.{prefix}_uploads": {"state": str(len(d["files"])), "last_updated": lu, "attributes": d},
            f"sensor.{prefix}_settings": {"state": "True", "last_updated": lu, "attributes": {"pubkey": "", "kid": ""}}}


ADMIN = ("{user: {id: 'owner', name: 'Owner', is_admin: true, is_owner: true}, callWS: async (m) => {"
         " if (m.endpoint.endsWith('/info')) return {ingress_url: '/api/hassio_ingress/tok123/', state: 'started', ingress: true};"
         " if (m.endpoint === '/ingress/session') return {session: 'f'.repeat(128)}; return {}; }}")


def _umount(pg, tag=UP, st=None, extra="{}"):
    pg.evaluate("([tag, st]) => { window.C = mount(tag, {}, st, " + extra + "); }", [tag, st or {}])
    pg.wait_for_function("C._data || C._err")


LOOK_A = """const b = q('[data-oft]'), l = q('[data-ofl]'), s = q('[data-ofs]'), bb = b.getBoundingClientRect(),
    rb = q('[data-reload]').getBoundingClientRect();
  return {tag: b.tagName, type: b.type, exp: b.getAttribute('aria-expanded'), ctl: b.getAttribute('aria-controls'),
    ctlIsList: !!l && l.id === b.getAttribute('aria-controls'), count: q('[data-ofn]').textContent,
    head: b.textContent.replace(/\\s+/g, ' ').trim(), sum: s.textContent, sumVis: vis(s), listHidden: !l || l.hidden,
    rows: qa('[data-list] .f').filter(vis).map((x) => x.querySelector('div').textContent.trim()),
    rowsAll: qa('[data-list] .f').length, older: qa('[data-ofl] details').length,
    want: qa('.w').filter(vis).map((x) => x.textContent.slice(0, 40)), pilot: vis(q('[data-pilot] .sen')) && q('[data-pilot]').textContent,
    approve: vis(q('[data-pilot] button[data-act="approve"]')), sen: vis(q('[data-sen] .sen')) && q('[data-sen]').textContent,
    h: Math.round(bb.height), w: Math.round(bb.width), rh: Math.round(rb.height), focus: r.activeElement === b,
    chev: getComputedStyle(q('[data-oft] .chev')).transform};"""


def test_on_file_folds_by_default_with_its_count_and_a_summary():
    with _browser() as b:
        pg = _page(b, cards.build("9.9.9", [])[f"{UP}.js"])
        _umount(pg, st=_ustates())
        r = _q(pg, LOOK_A)
        assert r["tag"] == "BUTTON" and r["type"] == "button" and r["exp"] == "false" and r["ctlIsList"]
        assert r["count"] == " (6)" and r["head"] == "On file (6) 6 files, newest Award Dec 2026, uploaded Nov 14"
        assert r["sum"] == "6 files, newest Award Dec 2026, uploaded Nov 14" and r["sumVis"]
        assert r["listHidden"] and r["rows"] == [] and r["rowsAll"] == 6
        assert len(r["want"]) == 1 and r["want"][0].startswith("Wanted: the Feb 2027 pairings package")  # stays in view
        assert r["approve"] and "Pilot uploads" in r["pilot"]  # a section of its own: never folded away
        assert "Dates of hire" in r["sen"] and "Pilot contacts" in r["sen"] and "Flight Watcher 9.9.9" in r["sen"]
        assert r["h"] >= 44 and r["w"] >= 44 and r["rh"] >= 44
        assert _store(pg, "flight_watcher_onfile_open") is None  # nothing stored until it is tapped
        assert pg.errors == []


def test_on_file_opens_and_the_browser_remembers():
    with _browser() as b:
        pg = _page(b, cards.build("9.9.9", [])[f"{UP}.js"])
        _umount(pg, st=_ustates())
        pg.locator(f"{UP} [data-oft]").click()
        r = _q(pg, LOOK_A)
        assert r["exp"] == "true" and not r["listHidden"] and not r["sumVis"] and r["count"] == " (6)"
        assert [x.split(" ")[0] for x in r["rows"]] == ["Award", "Pairings", "Award", "Pairings", "Contact", "Seniority"]
        assert r["chev"] != "none"  # the arrow turns down
        assert _store(pg, "flight_watcher_onfile_open") == "1"
        # another copy on the page, and the page loaded again, open as left
        pg.evaluate("(st) => { window.D = mount('" + UP + "', {}, st); }", _ustates())
        assert pg.evaluate("D.shadowRoot.querySelector('[data-oft]').getAttribute('aria-expanded')") == "true"
        pg.reload()
        _umount(pg, st=_ustates())
        assert _q(pg, LOOK_A)["exp"] == "true"
        # the keyboard: Enter folds it, Space opens it; the focus stays on the heading
        pg.locator(f"{UP} [data-oft]").focus()
        pg.keyboard.press("Enter")
        r = _q(pg, LOOK_A)
        assert r["exp"] == "false" and r["listHidden"] and r["sumVis"] and r["focus"]
        assert _store(pg, "flight_watcher_onfile_open") == "0"
        pg.keyboard.press("Space")
        r = _q(pg, LOOK_A)
        assert r["exp"] == "true" and not r["listHidden"] and r["focus"]
        ring = _q(pg, "const s = getComputedStyle(q('[data-oft]')); return [s.outlineStyle, parseFloat(s.outlineWidth)];")
        assert ring[0] != "none" and ring[1] >= 2  # a visible focus ring
        assert pg.errors == []


def test_refresh_keeps_the_fold_admin_card():
    """The admin's card (ingress): collapsed by default, Refresh fetches api/uploads again and the count, the summary
    and the rows follow while the fold stays as it is, open or folded; the 7th row folds under "1 older" inside."""
    with _browser() as b:
        up = {"data": _udata()}
        pg = _page(b, cards.build("9.9.9", [])[f"{UP}.js"], uploads=up)
        _umount(pg, extra=ADMIN)
        r = _q(pg, LOOK_A)
        assert r["exp"] == "false" and r["count"] == " (6)" and r["sum"] == "6 files, newest Award Dec 2026, uploaded Nov 14"
        assert up["gets"] == 1 and r["approve"]
        up["data"] = _udata(extra=True)
        pg.locator(f"{UP} [data-reload]").click()
        pg.wait_for_function("C.shadowRoot.querySelector('[data-ofn]').textContent === ' (7)'")
        r = _q(pg, LOOK_A)
        assert up["gets"] == 2 and r["exp"] == "false" and r["listHidden"]
        assert r["sum"] == "7 files, newest Pairings package Jan 2027, uploaded Nov 15, 1 not read"
        pg.locator(f"{UP} [data-oft]").click()
        up["data"] = _udata()
        pg.locator(f"{UP} [data-reload]").click()
        pg.wait_for_function("C.shadowRoot.querySelector('[data-ofn]').textContent === ' (6)'")
        r = _q(pg, LOOK_A)
        assert up["gets"] == 3 and r["exp"] == "true" and not r["listHidden"] and len(r["rows"]) == 6 and not r["sumVis"]
        up["data"] = _udata(extra=True)
        pg.locator(f"{UP} [data-reload]").click()
        pg.wait_for_function("C.shadowRoot.querySelector('[data-ofn]').textContent === ' (7)'")
        r = _q(pg, LOOK_A)
        assert r["exp"] == "true" and r["older"] == 1 and len(r["rows"]) == 6 and r["rowsAll"] == 7  # 6 + 1 older (closed)
        assert pg.errors == []


def test_user_card_refresh_and_empty_and_error_states():
    """A user who is not an admin (the sensor): Refresh reads it again with the fold kept. Nothing on file, or the
    Watcher not running, says so in view under a plain heading (there is nothing to fold: review AB-1)."""
    with _browser() as b:
        pg = _page(b, cards.build("9.9.9", [])[f"{UP}.js"])
        _umount(pg, st=_ustates())
        pg.locator(f"{UP} [data-oft]").click()
        pg.evaluate("(st) => { C.hass = mkHass(st); }", _ustates(extra=True, lu="t2"))
        pg.locator(f"{UP} [data-reload]").click()
        r = _q(pg, LOOK_A)
        assert r["exp"] == "true" and r["count"] == " (7)" and r["older"] == 1
        empty = _ustates(lu="t3")
        empty["sensor.flight_watcher_uploads"]["attributes"]["files"] = []
        pg.evaluate("(st) => { C.hass = mkHass(st); }", empty)
        r = _q(pg, LOOK_H)
        assert r["count"] == "" and not r["sumVis"] and not r["btn"] and r["plain"]  # nothing to fold: plain text
        none = "return vis(q('[data-list] > .u')) && q('[data-list] > .u').textContent;"
        assert _q(pg, none) == "Nothing uploaded yet."
        pg.locator(f"{UP} [data-ofp]").click()  # a tap on the heading changes nothing: still in view
        assert _q(pg, none) == "Nothing uploaded yet." and _q(pg, LOOK_H)["exp"] == []
        pg.evaluate("() => { C.hass = mkHass({'sensor.flight_watcher_uploads': {state: 'unavailable', last_updated: 't4', attributes: {}}}); }")
        assert _q(pg, "return vis(q('[data-list] .err')) && q('[data-list] .err').textContent;") == \
            "The Flight Watcher app is not running (its sensors are unavailable)."
        assert pg.errors == []


# review AB-1: the heading as a disclosure button only while there are rows to fold, else plain text
LOOK_H = """const b = q('[data-oft]'), p = q('[data-ofp]'), h = b || p, l = q('[data-ofl]'), s = q('[data-ofs]');
  return {btn: !!b, plain: p ? p.tagName : null, exp: qa('.hd [aria-expanded]').map((x) => x.getAttribute('aria-expanded')),
    ctl: qa('.hd [aria-controls]').length, ctlOk: !!b && !!l && b.getAttribute('aria-controls') === l.id,
    dangling: qa('[aria-controls]').filter((x) => !r.getElementById(x.getAttribute('aria-controls'))).length,
    chev: qa('.hd .chev').filter(vis).length, head: h.textContent.replace(/\\s+/g, ' ').trim(),
    count: q('[data-ofn]').textContent, sumVis: vis(s), list: !!l, listVis: vis(l),
    text: q('[data-list]').textContent.replace(/\\s+/g, ' ').trim(), rows: qa('[data-list] .f').filter(vis).length,
    more: vis(q('[data-ofmore]')) && q('[data-ofmore]').textContent, open: C._open,
    h: Math.round(h.getBoundingClientRect().height), focus: r.activeElement === b};"""
HEAD_BTN = re.compile(r"^On file")


def _ax(node):
    """Every node of a Playwright accessibility snapshot."""
    if not node:
        return []
    return [node] + [x for c in node.get("children", []) for x in _ax(c)]


def _plain(r, text):
    """Nothing to fold: no button, no aria-expanded, no aria-controls (none pointing at nothing), no chevron."""
    assert not r["btn"] and r["plain"] == "DIV" and r["exp"] == [] and r["ctl"] == 0 and r["dangling"] == 0, r
    assert r["chev"] == 0 and not r["list"] and text in r["text"] and r["head"].startswith("On file"), r


def test_on_file_heading_is_plain_text_while_there_is_nothing_to_fold():
    """Review AB-1: while api/uploads has not answered ("Loading..."), on an error, and with nothing on file there are
    no rows to fold, so the heading is plain text: no disclosure button, no aria-expanded, no aria-controls pointing at
    an element that is not there, no chevron, and a tap on it changes nothing. The button comes back once there is a
    list, folded or open as this browser keeps it, and goes again when the list does."""
    src = cards.build("9.9.9", [])[f"{UP}.js"]
    with _browser() as b:
        # the admin's card: api/uploads held, then answered
        held = []
        pg = _page(b, src)
        pg.route("**/api/hassio_ingress/tok123/api/uploads", lambda route: held.append(route))
        pg.evaluate("() => { window.C = mount('" + UP + "', {}, {}, " + ADMIN + "); }")
        for _ in range(100):
            if held:
                break
            pg.wait_for_timeout(50)
        assert held, "the card never asked for api/uploads"
        r = _q(pg, LOOK_H)
        _plain(r, "Loading...")
        assert r["count"] == "" and not r["sumVis"] and r["h"] >= 44  # the heading keeps its height (no jump)
        assert pg.get_by_role("button", name=HEAD_BTN).count() == 0
        pg.locator(f"{UP} [data-ofp]").click()
        assert _q(pg, LOOK_H)["exp"] == [] and _store(pg, "flight_watcher_onfile_open") is None
        held[0].fulfill(status=200, content_type="application/json", body=json.dumps(_udata()))
        pg.wait_for_function("!!C.shadowRoot.querySelector('[data-oft]')")
        r = _q(pg, LOOK_H)
        assert r["btn"] and r["plain"] is None and r["exp"] == ["false"] and r["ctlOk"] and r["dangling"] == 0
        assert r["chev"] == 1 and r["head"] == "On file (6) 6 files, newest Award Dec 2026, uploaded Nov 14"
        assert pg.get_by_role("button", name=HEAD_BTN).count() == 1
        assert pg.errors == []
        # a user's card (the sensor): not listed yet, a list, nothing on file, not running, a list again
        pg = _page(b, src)
        _umount(pg, st={})
        _plain(_q(pg, LOOK_H), "The Watcher has not listed its files yet")
        pg.evaluate("(st) => { C.hass = mkHass(st); }", _ustates(lu="t2"))
        r = _q(pg, LOOK_H)
        assert r["btn"] and r["exp"] == ["false"] and r["ctlOk"] and r["chev"] == 1 and not r["listVis"]
        pg.locator(f"{UP} [data-oft]").click()
        r = _q(pg, LOOK_H)
        assert r["exp"] == ["true"] and r["listVis"] and r["rows"] == 6 and r["focus"]
        empty = _ustates(lu="t3")
        empty["sensor.flight_watcher_uploads"]["attributes"]["files"] = []
        pg.evaluate("(st) => { C.hass = mkHass(st); }", empty)
        r = _q(pg, LOOK_H)
        _plain(r, "Nothing uploaded yet.")
        assert r["open"] is True and _store(pg, "flight_watcher_onfile_open") == "1"  # kept for when a list is back
        assert pg.get_by_role("button", name=HEAD_BTN).count() == 0
        ax = [n for n in _ax(pg.accessibility.snapshot()) if str(n.get("name", "")).startswith("On file")]
        assert ax and all(n.get("role") != "button" and "expanded" not in n for n in ax), ax  # Chromium's tree
        _shot(pg, "A_390_light_empty_fixed")
        pg.evaluate("() => { C.hass = mkHass({'sensor.flight_watcher_uploads': {state: 'unavailable', last_updated: 't4', attributes: {}}}); }")
        _plain(_q(pg, LOOK_H), "The Flight Watcher app is not running")
        pg.evaluate("(st) => { C.hass = mkHass(st); }", _ustates(lu="t5"))
        r = _q(pg, LOOK_H)
        assert r["btn"] and r["exp"] == ["true"] and r["listVis"] and r["rows"] == 6 and r["ctlOk"] and not r["sumVis"]
        assert pg.errors == []


def _trimmed(count, trimmed=None):
    st = _ustates()
    a = st["sensor.flight_watcher_uploads"]["attributes"]
    a["count"] = count
    if trimmed is not None:
        a["trimmed"] = trimmed
    st["sensor.flight_watcher_uploads"]["state"] = str(count)
    return st


def test_on_file_counts_what_the_watcher_counts_when_the_sensor_list_is_cut(tmp_path, monkeypatch):
    """Review AB-2: watcher.cap_attrs cuts sensor.<prefix>_uploads files from the end (the oldest) at its byte cap and
    keeps the whole number in count (trimmed beside it). A card reading the sensor gives the Watcher's count in the
    heading and the folded line, and the open list says how many older ones it cannot show. A count it cannot use (none,
    not a whole number, fewer than listed) falls back to the rows listed; the admin's api/uploads is never cut."""
    from test_sensor_size import _load as wload

    src = cards.build("9.9.9", [])[f"{UP}.js"]
    with _browser() as b:
        pg = _page(b, src)
        _umount(pg, st=_trimmed(8, 2))
        r = _q(pg, LOOK_H)
        assert r["count"] == " (8)" and r["head"] == "On file (8) 8 files, newest Award Dec 2026, uploaded Nov 14", r
        assert r["more"] is False  # folded with the rows
        pg.locator(f"{UP} [data-oft]").click()
        r = _q(pg, LOOK_H)
        assert r["rows"] == 6 and r["more"] == "2 older files not listed here (more than the sensor can carry).", r
        _shot(pg, "A_390_light_trimmed_open")
        for bad in (None, "x", 3, 6.5, -1, True):
            pg.evaluate("(st) => { C.hass = mkHass(st); }", _trimmed(bad))
            pg.locator(f"{UP} [data-reload]").click()
            r = _q(pg, LOOK_H)
            assert r["count"] == " (6)" and r["more"] is False and r["rows"] == 6, (bad, r)
        assert pg.errors == []
        # the real cut: 120 synthetic files (60 months of award and pairings, newest first) through cap_attrs
        W = wload(tmp_path, monkeypatch)[0]
        files = []
        for k in range(60):
            y, m = 2026 - k // 12, 12 - k % 12
            for i, kind in enumerate(("award", "pairings")):
                files.append({"name": f"{y}-{m:02d}_{kind}.pdf", "kind": kind, "month": f"{y}-{m:02d}", "day": "",
                              "size": 800000 + k, "uploaded_at": f"{y - (m == 1)}-{(m - 2) % 12 + 1:02d}-14T08:{10 + i:02d}:00-10:00",
                              "has_text": True})
        d = {"version": "9.9.9", "max_bytes": 16711680, "mqtt_max_bytes": 25000000, "files": files, "wanted": [],
             "seniority": None, "contacts": None, "count": len(files), "chunk_bytes": 65536}
        p = W.cap_attrs("uploads", d)
        assert p["count"] == 120 and 0 < len(p["files"]) < 120 and p["trimmed"] == 120 - len(p["files"])
        st = {"sensor.flight_watcher_uploads": {"state": "120", "last_updated": "t9", "attributes": p}}
        pg.evaluate("(st) => { C.hass = mkHass(st); }", st)
        r = _q(pg, LOOK_H)
        assert r["count"] == " (120)" and r["more"] == f"{p['trimmed']} older files not listed here (more than the sensor can carry).", r
        pg.locator(f"{UP} [data-oft]").click()
        r = _q(pg, LOOK_H)
        assert r["head"] == "On file (120) 120 files, newest Pairings package Dec 2026, uploaded Nov 14", r
        assert pg.errors == []


def test_pilot_copy_folds_the_same_under_its_own_key():
    built = cards.build("9.9.9", ["pilot2"])
    src = built[f"{UP}-pilot2.js"]
    assert '"flight_watcher_pilot2_onfile_open"' in src and "Ryan" not in src
    with _browser() as b:
        pg = _page(b, [built[f"{UP}.js"], src])
        pg.evaluate("(st) => { window.A = mount('" + UP + "', {}, st); }", _ustates())
        _umount(pg, tag=f"{UP}-pilot2", st=_ustates("flight_watcher_pilot2"))
        r = _q(pg, LOOK_A)
        assert r["exp"] == "false" and r["count"] == " (6)" and r["sum"] == "6 files, newest Award Dec 2026, uploaded Nov 14"
        pg.locator(f"{UP}-pilot2 [data-oft]").click()
        assert _q(pg, LOOK_A)["exp"] == "true"
        assert _store(pg, "flight_watcher_pilot2_onfile_open") == "1" and _store(pg, "flight_watcher_onfile_open") is None
        assert pg.evaluate("A.shadowRoot.querySelector('[data-oft]').getAttribute('aria-expanded')") == "false"
        assert pg.errors == []


BLOCKED = ("Object.defineProperty(window, 'localStorage', {configurable: true, get() {"
           " throw new DOMException('The operation is insecure.', 'SecurityError'); }});")


def test_blocked_storage_folds_and_still_opens():
    with _browser() as b:
        pg = _page(b, cards.build("9.9.9", [])[f"{UP}.js"], init=BLOCKED)
        _umount(pg, st=_ustates())
        assert _q(pg, LOOK_A)["exp"] == "false"
        pg.locator(f"{UP} [data-oft]").click()
        r = _q(pg, LOOK_A)
        assert r["exp"] == "true" and len(r["rows"]) == 6
        assert pg.errors == []


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_on_file_renders_at_390(scheme):
    with _browser() as b:
        pg = _page(b, cards.build("9.9.9", [])[f"{UP}.js"], 390, 844, scheme)
        _umount(pg, st=_ustates())
        for state in ("folded", "open"):
            fit = pg.evaluate("fwFits(C)")
            assert fit["page"] <= 390 and fit["right"] <= 390 and fit["inner"] <= 0, (state, fit)
            mine = {"On file", "(6)", "6 files, newest Award Dec 2026, uploaded Nov 14", "Refresh"}
            fails = [f for f in pg.evaluate("fwContrast(C).fails") if f["text"] in mine]
            assert fails == [], (state, fails)
            assert _q(pg, "return C.hasAttribute('dark');") == (scheme == "dark")
            _shot(pg, f"A_390_{scheme}_{state}")
            if state == "folded":
                pg.locator(f"{UP} [data-oft]").click()
        pg.locator(f"{UP} [data-oft]").focus()
        pg.keyboard.press("Enter")
        _shot(pg, f"A_390_{scheme}_focus")
        assert pg.errors == []


# ---------------------------------------------------------------- B: the version lock as a switch
def _smount(pg, tag=SC, st=None):
    pg.evaluate("([tag, st]) => { window.C = mount(tag, {}, st, " + OWNER + "); }", [tag, st or sched_states()])
    pg.wait_for_function("C._pk && C._pk['2026-11'] !== null && C._pk['2026-11'] !== undefined")


LOOK_B = """const l = q('.lock'), t = q('.lock .lkt'), k = q('.lock .lkk'), lb = l.getBoundingClientRect(), tb = t.getBoundingClientRect(),
    kb = k.getBoundingClientRect(), key = qa('.lt td').map((x) => x.textContent).find((x) => x.includes('The lock')) || '';
  return {tag: l.tagName, type: l.type, role: l.getAttribute('role'), checked: l.getAttribute('aria-checked'),
    name: l.getAttribute('aria-label'), title: l.title, cls: [l.classList.contains('shut'), l.classList.contains('open')],
    text: l.textContent.replace(/\\s+/g, ' ').trim(), svg: l.querySelectorAll('svg').length,
    svgHidden: l.querySelector('svg').getAttribute('aria-hidden'), shackle: l.querySelector('svg').dataset.lock,
    knobRight: kb.left + kb.width / 2 > tb.left + tb.width / 2, h: Math.round(lb.height), w: Math.round(lb.width),
    focus: r.activeElement === l, key, html: r.innerHTML};"""


def test_lock_is_a_switch_that_reflects_and_toggles():
    with _browser() as b:
        pg = _page(b, cards.build("9.9.9", [])[f"{SC}.js"], 1100, 900)
        _smount(pg)
        r = _q(pg, LOOK_B)
        assert r["tag"] == "BUTTON" and r["type"] == "button" and r["role"] == "switch" and r["name"] == "Lock schedule marks"
        assert r["checked"] == "true" and r["cls"] == [True, False] and r["text"] == "Lock On" and r["knobRight"]
        assert r["svg"] == 1 and r["svgHidden"] == "true" and r["shackle"] == "shut"
        assert r["title"] == "Locked: availability, trade and drop marks cannot be changed by a tap. Tap to unlock."
        assert not any(x in r["html"] for x in LOCK_EMOJI)
        assert r["h"] >= 44 and r["w"] >= 44
        h = _q(pg, HEAD)  # a wide card: the switch on the month's line, at its left, as the lock was
        assert h["sameRow"] and h["navRow"] and h["left"] <= 4 and h["hdOver"] <= 0, h
        _shot(pg, "B_1100_light_on")
        # locked: a trade tap is refused with the switch named
        pg.locator(f'{SC} .trb[data-k="H3604B|2026-11-23"]').click()
        info = _q(pg, "return q('.info').textContent;")
        assert info == "Settings are locked: turn the Lock switch at the top left Off to change availability, trade or drop marks."
        assert pg.evaluate("window.calls.length") == 0
        pg.locator(f"{SC} .lock").click()
        r = _q(pg, LOOK_B)
        assert r["checked"] == "false" and r["cls"] == [False, True] and r["text"] == "Lock Off" and not r["knobRight"]
        assert r["shackle"] == "open" and r["title"] == "Unlocked: taps change availability, trade and drop marks. Tap to lock."
        assert _store(pg, "flight_watcher_lock") == "0"
        pg.locator(f'{SC} .trb[data-k="H3604B|2026-11-23"]').click()
        assert pg.evaluate("window.calls.map((c) => c[2].topic)") == ["flight_watcher/trade/set"]
        pg.locator(f"{SC} .lock").click()
        r = _q(pg, LOOK_B)
        assert r["checked"] == "true" and r["text"] == "Lock On" and _store(pg, "flight_watcher_lock") == "1"
        assert pg.errors == []


def test_lock_switch_keyboard_and_focus_ring():
    with _browser() as b:
        pg = _page(b, cards.build("9.9.9", [])[f"{SC}.js"], 1100, 900)
        _smount(pg)
        pg.locator(f"{SC} .lock").focus()
        pg.keyboard.press("Space")
        r = _q(pg, LOOK_B)
        assert r["checked"] == "false" and r["focus"]  # the redraw keeps the focus on the switch
        ring = _q(pg, "const s = getComputedStyle(q('.lock')); return [s.outlineStyle, parseFloat(s.outlineWidth)];")
        assert ring[0] != "none" and ring[1] >= 2
        pg.keyboard.press("Enter")
        r = _q(pg, LOOK_B)
        assert r["checked"] == "true" and r["focus"] and _store(pg, "flight_watcher_lock") == "1"
        assert pg.errors == []


def test_lock_storage_unchanged():
    """The stored value is the one 1.7.11 kept: "0" unlocked, anything else (or nothing, or blocked storage) locked."""
    with _browser() as b:
        pg = _page(b, cards.build("9.9.9", [])[f"{SC}.js"], 1100, 900, init="localStorage.setItem('flight_watcher_lock', '0');")
        _smount(pg)
        r = _q(pg, LOOK_B)
        assert r["checked"] == "false" and r["text"] == "Lock Off"
    with _browser() as b:
        pg = _page(b, cards.build("9.9.9", [])[f"{SC}.js"], 1100, 900, init=BLOCKED)
        _smount(pg)
        assert _q(pg, LOOK_B)["checked"] == "true"
        pg.locator(f"{SC} .lock").click()
        assert _q(pg, LOOK_B)["checked"] == "false"
        assert pg.errors == []


def test_key_describes_the_switch():
    with _browser() as b:
        pg = _page(b, cards.build("9.9.9", [])[f"{SC}.js"], 1100, 900)
        _smount(pg)
        key = _q(pg, LOOK_B)["key"]
        assert ("The lock switch at the top left (a lock, the word Lock, then On or Off) freezes availability, trade and "
                "drop taps while it is On (the default); switch it Off to change them and On again to lock them.") in key
        assert not any(x in key for x in LOCK_EMOJI)
    for name in os.listdir(os.path.join(HERE, "www")):  # no card draws the lock emoji any more
        s = open(os.path.join(HERE, "www", name), encoding="utf-8").read()
        assert not any(x in s for x in LOCK_EMOJI), name


def test_pilot_copy_has_the_same_switch_under_its_own_key():
    src = PT.portal_card(cards.build("9.9.9", ["pilot2"])[f"{SC}-pilot2.js"])
    assert '"flight_watcher_pilot2_lock"' in src and 'role="switch"' in src
    with _browser() as b:
        pg = _page(b, src, 390, 844)
        _smount(pg, f"{SC}-pilot2", _pilot(sched_states(role="pilot")))
        r = _q(pg, LOOK_B)
        assert r["role"] == "switch" and r["checked"] == "true" and r["text"] == "Lock On" and r["name"] == "Lock schedule marks"
        assert r["title"] == "Locked: availability and trade marks cannot be changed by a tap. Tap to unlock."
        assert "availability and trade taps" in r["key"] and "drop" not in r["key"]
        pg.locator(f"{SC}-pilot2 .lock").click()
        assert _q(pg, LOOK_B)["checked"] == "false"
        assert _store(pg, "flight_watcher_pilot2_lock") == "0" and _store(pg, "flight_watcher_lock") is None
        assert pg.errors == []


HEAD = """const l = q('.lock'), hd = q('.hd2'), c = q('ha-card').getBoundingClientRect(), lb = l.getBoundingClientRect(),
    h3 = q('.hd2 h3').getBoundingClientRect(), mid = (x) => (x.top + x.bottom) / 2;
  const nav = [...qa('.hd2 .nav'), q('.hd2 h3')].map((e) => mid(e.getBoundingClientRect()));
  return {inCard: lb.left >= c.left && lb.right <= c.right, hdOver: hd.scrollWidth - hd.clientWidth, h: lb.height,
    sameRow: Math.abs(mid(lb) - mid(h3)) < 12, above: lb.bottom <= h3.top + 1, left: Math.round(lb.left - hd.getBoundingClientRect().left),
    navRow: Math.max(...nav) - Math.min(...nav) < 12, page: document.documentElement.scrollWidth, dark: C.hasAttribute('dark')};"""


NONTEXT = """const P = (c) => { const m = /rgba?\\(([^)]+)\\)/.exec(c); const p = m[1].split(/[\\s,\\/]+/).filter(Boolean).map(parseFloat);
    return {r: p[0], g: p[1], b: p[2]}; };
  const L = (c) => { const f = (v) => { v /= 255; return v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b); };
  const R = (a, b) => { const x = L(P(a)), y = L(P(b)); return Math.round(((Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05)) * 100) / 100; };
  const card = getComputedStyle(q('ha-card')).backgroundColor, t = getComputedStyle(q('.lkt')), k = getComputedStyle(q('.lkk'));
  return C._locked ? {track: R(t.backgroundColor, card), knob: R(k.backgroundColor, t.backgroundColor), edge: R(t.borderTopColor, card)}
    : {track: R(t.borderTopColor, card), knob: R(k.backgroundColor, card), edge: R(t.borderTopColor, card)};"""


@pytest.mark.parametrize("scheme", ["light", "dark"])
@pytest.mark.parametrize("width,height,dsf,name", [(390, 844, 2, "390"), (360, 780, 3, "android_360")])
def test_lock_switch_renders_on_phones(scheme, width, height, dsf, name):
    with _browser() as b:
        pg = _page(b, cards.build("9.9.9", [])[f"{SC}.js"], width, height, scheme, dsf)
        _smount(pg)
        for state in ("on", "off"):
            r = _q(pg, HEAD)
            assert r["inCard"] and r["hdOver"] <= 0 and r["h"] >= 44 and r["page"] <= width and r["dark"] == (scheme == "dark"), (state, r)
            # a phone: the switch has the first line to itself, at the left; the arrows, the month and Now stay together
            assert r["navRow"] and r["above"] and not r["sameRow"] and r["left"] <= 4, (state, r)
            fails = [f for f in pg.evaluate("fwContrast(C).fails") if f["text"] in ("Lock", "On", "Off")]
            assert fails == [], (state, fails)
            nt = _q(pg, NONTEXT)
            assert min(nt.values()) >= 3, (state, nt)  # WCAG 1.4.11: the track, the knob and the edge
            _shot(pg, f"B_{name}_{scheme}_{state}")
            if state == "on":
                pg.locator(f"{SC} .lock").click()
        assert pg.errors == []
