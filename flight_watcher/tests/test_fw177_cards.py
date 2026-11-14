"""1.7.7, the finds card and the FO / RO pickers card in Chromium (390 x 844 and 1280 x 800), on rows the real Store
and Watcher make from synthetic finds (made-up pilots "Doe, Jane" 10001 and pairings H9101, H3648):
- "Picked up by": only the open-seat picker is the blue link (Ryan, Nov 14); a pilot already on the pairing is plain
  text in the text color; an old row with no stored pickers links the one its open seat names, an ambiguous one none.
- InFlt: the airplane then "AS808/06NOV" with the leg and the pairing on hover; a leg backfilled from the pairings
  package (a deadhead: DH in the hover); the airplane alone and "flight not on file" when there is no leg.
- The pickers card: no merged two-name rows after the rebuild.
FW_177_SHOTS=<dir> keeps the screenshots (device scale 2)."""
import json
import os
from datetime import datetime, timedelta, timezone

import cards
import pdfs
from test_crew_index import W  # noqa: F401  (the Watcher fixture)
from test_fw171_cards import HARNESS_JS, PORTAL_CSS
from test_fw177_pickers import _old_style
from test_pairing_detail import package
from test_pilot_grid_look import _browser

SHOTS = os.environ.get("FW_177_SHOTS", "")
ORIGIN = "https://ha.test"
NOW = "2026-11-14T22:00:00Z"  # Nov 14 12:00 HST: the rows below were seen this morning, so they show unfolded
HST = timezone(timedelta(hours=-10))
KEY = "0123456789abcdef0123456789abcdef"
JANE, RICK, PAT, MAX, KIM, LOU = ("Doe, Jane (10001)", "Roe, Rick (10002)", "Poe, Pat (10003)", "Moe, Max (10004)",
                                  "Lee, Kim (10005)", "Kay, Lou (10006)")


def _at(d, h, mi=0):
    return datetime(2026, 11, d, h, mi, tzinfo=HST).astimezone(timezone.utc).isoformat()


def _data(W, tmp_path):  # noqa: F811
    """The finds month file and the pickers rows as the Watcher writes them."""
    www = tmp_path / "www"
    www.mkdir(exist_ok=True)
    (www / "pairings_2026-11.json").write_text(json.dumps(pdfs.package_json(package(), "synthetic")))
    db = W.DB
    rows = [  # (key, by, open seats, pickup extras, seen hour)
        ("H9301|19Nov", f"FO {JANE}; RO {RICK}", "FO", {"pickers": ["10001"]}, 11),  # Rick was already on it
        ("H9302|20Nov", f"FO {PAT}; RO {MAX}", "FO,RO", {"pickers": ["10003", "10004"]}, 10),  # both seats open
        ("H9303|21Nov", f"FO {KIM}; RO {LOU}", "RO", {}, 9),  # from before 1.7.7: no pickers stored, RO was open
        ("H9304|22Nov", f"FO {KIM}; RO {LOU}", "", {}, 8),  # an email-caught find, no open seat on file: none
        ("H9305|23Nov", f"FO {JANE}", "FO", {"pickers": ["10001"]}, 7),  # in flight, leg from the pairing page
        ("H9306|24Nov", f"FO {PAT}", "FO", {"pickers": ["10003"]}, 6),  # in flight before 1.7.7: backfilled
        ("H9307|25Nov", f"FO {MAX}", "FO", {"pickers": ["10004"]}, 5),  # in flight, flight not on file
    ]
    for i, (k, by, seats, extra, h) in enumerate(rows):
        seen, gone = _at(14, h), _at(14, h, 2)
        db.add_find(k, "2026-11", {"pairing": k[:5], "dates": f"{k[6:8]}NOV-{int(k[6:8]) + 2}NOV", "days": "3",
                                   "layover": "SEA", "credit": "16:00", "captain": "Doe, John (10009)", "open_seats": seats,
                                   "source": "email" if k == "H9304|22Nov" else "pot"}, seen, gone=gone)
        db.db.execute("UPDATE finds SET last_seen=? WHERE key=?", (_at(14, h, 1), k))
        db.set_pickup(k, dict({"status": "filled", "by": by, "ca": "Doe, John (10009)", "known": k != "H9304|22Nov"}, **extra))
    _old_style(db, "H9303|21Nov", f"FO {KIM}; RO {LOU}", 75)  # before 1.7.7 it was scored to Lou under a merged name
    db.rebuild_pickers()
    for k in ("H9301|19Nov", "H9302|20Nov", "H9305|23Nov", "H9306|24Nov", "H9307|25Nov"):
        db.score_pickup(k)
    db.set_inflt("H9301|19Nov", False, "", tries=1, emp="10001")
    db.set_inflt("H9305|23Nov", True, "H3648 2026-11-03", tries=1, emp="10001",
                 leg={"flt": "808", "frm": "HNL", "to": "LAS", "dep_l": "23:00", "date": "2026-11-06", "dh": False, "src": "page"})
    db.set_inflt("H9306|24Nov", True, "H9101 2026-11-05", tries=1)  # on the DH LAX-SFO, Fri Nov 6 20:00 HST
    db.db.execute("UPDATE finds SET gone_at=? WHERE key='H9306|24Nov'", (_at(6, 20),))
    db.set_inflt("H9307|25Nov", True, "H3648 2026-11-03", tries=1)
    assert W.inflt_leg_backfill() == 1
    db.db.execute("UPDATE finds SET gone_at=? WHERE key='H9306|24Nov'", (_at(14, 6, 2),))
    finds = db.finds_between(_at(1, 0), _at(15, 0))
    W.publish_pickers()
    pickers = [p for t, p in W.SENT if t == "pickers"][-1]["pickers"]
    return finds, pickers


# the harness's ha-icon draws nothing; here it draws MDI's airplane (and a dot for any other icon) so the shots show it
AIRPLANE = ("M20.56 3.91C21.15 4.5 21.15 5.45 20.56 6.03L16.67 9.92L18.79 19.11L17.38 20.53L13.5 13.1L9.6 17L9.96 19.47"
            "L8.89 20.53L7.13 17.35L3.94 15.58L5 14.5L7.5 14.87L11.37 11L3.94 7.09L5.36 5.68L14.55 7.8L18.44 3.91C19 3.33 20 "
            "3.33 20.56 3.91Z")
ICON_JS = ("customElements.define('ha-icon', class extends HTMLElement { connectedCallback() { const air = this.getAttribute('icon') === "
           "'mdi:airplane'; this.innerHTML = `<svg viewBox='0 0 24 24' width='16' height='16' style='vertical-align:-3px;fill:currentColor'>"
           "${air ? `<path d='" + AIRPLANE + "'/>` : `<circle cx='12' cy='12' r='4'/>`}</svg>`; } });")


def _page(b, width, height, scheme, finds, pickers):
    built = cards.build("9.9.9", [])
    scripts = [built["flight-watcher-finds-card.js"], built["flight-watcher-pickers-card.js"]]
    ctx = b.new_context(viewport={"width": width, "height": height}, device_scale_factor=2, color_scheme=scheme,
                        timezone_id="Pacific/Honolulu")
    html = ("<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<style>" + PORTAL_CSS + "</style></head><body><main><section class='view'></section></main><script>"
            + HARNESS_JS.replace('customElements.define("ha-icon", class extends HTMLElement {});', ICON_JS)
            + "</script>" + "".join(f"<script type='module'>{s}</script>" for s in scripts) + "</body></html>")
    month = json.dumps({"month": "2026-11", "count": len(finds), "finds": finds})

    def serve(route):
        url = route.request.url
        if url == ORIGIN + "/":
            return route.fulfill(status=200, content_type="text/html", body=html)
        if f"/local/flight-watcher/finds_2026-11_{KEY}.json" in url:
            return route.fulfill(status=200, content_type="application/json", body=month)
        if f"/local/flight-watcher/finds_2026-10_{KEY}.json" in url:
            return route.fulfill(status=200, content_type="application/json", body=json.dumps({"finds": []}))
        return route.fulfill(status=404, body="")
    ctx.route(ORIGIN + "/**", serve)
    pg = ctx.new_page()
    pg.errors = []
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    pg.on("console", lambda m: pg.errors.append(m.text) if m.type == "error" and "Failed to load resource" not in m.text else None)
    pg.clock.set_fixed_time(NOW)
    pg.goto(ORIGIN + "/")
    lu = "2026-11-14T21:00:00+00:00"
    st = {"sensor.flight_watcher_finds": {"state": str(len(finds)), "last_updated": lu, "last_changed": lu,
                                          "attributes": {"count": 0, "finds": [], "file_key": KEY, "rev": "r1"}},
          "sensor.flight_watcher_pickers": {"state": str(len(pickers)), "last_updated": lu, "last_changed": lu,
                                            "attributes": {"count": len(pickers), "pickers": pickers}}}
    pg.wait_for_function("!!customElements.get('flight-watcher-finds-card') && !!customElements.get('flight-watcher-pickers-card')")
    pg.evaluate("(st) => { window.FC = mount('flight-watcher-finds-card', {}, st); window.PC = mount('flight-watcher-pickers-card', {open: true}, st); }", st)
    pg.wait_for_function("FC.shadowRoot && FC.shadowRoot.querySelectorAll('tbody tr').length >= 7")
    pg.wait_for_timeout(100)
    return pg


ROWS = """() => [...FC.shadowRoot.querySelectorAll('tbody tr')].filter((tr) => tr.children.length > 3).map((tr) => {
  const td = tr.children, by = td[10], inf = td[11], ifs = inf.querySelector('.if');
  return { trip: td[2].textContent.trim(), links: [...by.querySelectorAll('a')].map((a) => a.textContent),
    hrefs: [...by.querySelectorAll('a')].map((a) => a.getAttribute('href')),
    plain: [...by.querySelectorAll('.np')].map((x) => [x.textContent, getComputedStyle(x).color, getComputedStyle(x).cursor, getComputedStyle(x).textDecorationLine]),
    link: by.querySelector('a') ? [getComputedStyle(by.querySelector('a')).color, getComputedStyle(by.querySelector('a')).textDecorationLine] : null,
    text: by.textContent, inflt: inf.textContent.trim(), tip: ifs ? ifs.getAttribute('title') : '', icon: !!inf.querySelector('ha-icon') }; })"""


def _shot(pg, name, sel):
    if not SHOTS:
        return
    os.makedirs(SHOTS, exist_ok=True)
    pg.locator(sel).first.screenshot(path=os.path.join(SHOTS, f"{name}.png"))


def _check(pg):
    rows = {r["trip"]: r for r in pg.evaluate(ROWS)}
    text, primary = pg.evaluate("() => [getComputedStyle(document.body).color, getComputedStyle(FC.shadowRoot.querySelector('a')).color]")
    a = rows["H9301"]  # two names, one open seat: Jane is the picker, Rick was already on the pairing
    assert a["links"] == [JANE] and a["hrefs"] == ["#pilot=10001,Doe%2C%20Jane"]
    assert a["plain"] == [[RICK, text, "auto", "none"]] and a["link"][0] == primary != text
    assert a["text"] == f"FO {JANE}; RO {RICK}" and a["inflt"] == "no"
    assert rows["H9302"]["links"] == [PAT, MAX] and rows["H9302"]["plain"] == []  # both seats open: both
    assert rows["H9303"]["links"] == [LOU] and [p[0] for p in rows["H9303"]["plain"]] == [KIM]  # derived from open_seats
    assert rows["H9304"]["links"] == [] and [p[0] for p in rows["H9304"]["plain"]] == [KIM, LOU]  # ambiguous: none
    assert rows["H9304"]["inflt"] == "" and rows["H9302"]["inflt"] == "-"  # nobody to look up / not looked up yet
    d = rows["H9305"]
    assert d["icon"] and d["inflt"] == "AS808/06NOV"
    assert d["tip"] == "picked up while airborne on AS808 HNL-LAS, departed 06NOV 23:00 local (pairing H3648 Nov 3)"
    e = rows["H9306"]
    assert e["icon"] and e["inflt"] == "AS1127/06NOV"
    assert e["tip"] == ("picked up while airborne on AS1127 LAX-SFO (DH, deadhead), departed 06NOV 21:50 local (pairing H9101 "
                        "Nov 5); flight from the pairings package")
    f = rows["H9307"]
    assert f["icon"] and f["inflt"] == "" and f["tip"] == "picked up while airborne (pairing H3648 Nov 3); flight not on file"
    # the pickers card: each picker once, no merged two-name rows
    names = pg.evaluate("() => [...PC.shadowRoot.querySelectorAll('tbody tr td.pn .nm')].map((x) => x.textContent)")
    assert sorted(names) == ["Doe, Jane", "Kay, Lou", "Moe, Max", "Poe, Pat"], names
    assert not any(";" in n or "(" in n for n in names)
    assert pg.evaluate("() => document.documentElement.scrollWidth <= innerWidth")
    assert pg.errors == []


def test_the_finds_and_pickers_cards_on_a_phone_and_a_desktop(W, tmp_path):  # noqa: F811
    finds, pickers = _data(W, tmp_path)
    by = {f["pairing"]: f for f in finds}
    assert by["H9303"]["pickers"] == ["10006"] and by["H9304"]["pickers"] == [] and by["H9306"]["inflt_leg"]["src"] == "package"
    with _browser() as b:
        for width, height in ((390, 844), (1280, 800)):
            for scheme in ("light", "dark"):
                pg = _page(b, width, height, scheme, finds, pickers)
                _check(pg)
                # the Key says what the blue name and the flight mean
                pg.evaluate("() => { FC.shadowRoot.querySelector('details.key').open = true; }")
                key = pg.evaluate("() => FC.shadowRoot.querySelector('details.key').textContent")
                assert "the picker (blue) opens his month" in key and "AS808/06NOV" in key and "flight not on file" in key
                _shot(pg, f"finds_{width}_{scheme}", "flight-watcher-finds-card")
                # the table scrolls sideways inside the card: the Picked up by column, then InFlt, in view
                for col, nm in ((10, "by"), (11, "inflt")):
                    pg.evaluate("(i) => { const w = FC.shadowRoot.querySelector('.wrap'), th = FC.shadowRoot.querySelectorAll('thead th')[i];"
                                " w.scrollLeft = Math.max(0, th.offsetLeft - (i === 11 ? w.clientWidth - th.offsetWidth - 120 : 8)); }", col)
                    _shot(pg, f"finds_{width}_{scheme}_{nm}", "flight-watcher-finds-card")
                _shot(pg, f"pickers_{width}_{scheme}", "flight-watcher-pickers-card")
                pg.context.close()
