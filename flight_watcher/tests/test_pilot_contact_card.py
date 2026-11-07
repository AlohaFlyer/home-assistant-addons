"""FW-0066 (1.4.8): the pilot card's call / text / mail links for the looked-up pilot (attribute contact of
sensor.flight_watcher_pilot_schedule, filled from the pilot contact list). Rendered in node with a small stub DOM:
the links in the header and beside the pilot's own name in the crew lists, never beside another crew member, only
digits in a tel: or sms: link, only a plain address in a mailto: link, nothing shown for a lookup still on its way,
and the second pilot's copy. Made-up pilots, 555-01xx numbers and example.com addresses."""
import json
import os
import shutil
import subprocess

import pytest

import cards
from test_pilot_pay_card import _payload

CARD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "www", "flight-watcher-pilot-card.js")
STUB = """
globalThis.HTMLElement = class { constructor() { this.style = {}; }
  attachShadow() { const body = {innerHTML: "", insertAdjacentHTML(p, h) { this.innerHTML += h; }};
    this.shadowRoot = {innerHTML: "", body, addEventListener() {}, querySelector: (s) => (s === ".body" ? body : null)}; return this.shadowRoot; }
  scrollIntoView() {} };
globalThis.customElements = {define() {}, get() {}};
globalThis.window = {addEventListener() {}, removeEventListener() {}, dispatchEvent() {}};
globalThis.location = {hash: "", pathname: "/", search: ""}; globalThis.history = {replaceState() {}};
globalThis.CustomEvent = class { constructor(t, o) { this.type = t; this.detail = (o || {}).detail; } };
"""
ROE = {"name": "Roe, Rick", "phones": [{"label": "cell", "number": "808-555-0112", "tel": "+18085550112"},
                                       {"label": "home", "number": "808-555-0113", "tel": "+18085550113"}],
       "emails": ["rick.roe@example.com"]}


def _node(tmp_path, body, src=None):
    if not shutil.which("node"):
        pytest.skip("node not installed")
    f = tmp_path / "t.js"
    f.write_text(STUB + (src if src is not None else open(CARD, encoding="utf-8").read()) + "\n(async () => {\n" + body + "\n})();")
    out = subprocess.run(["node", str(f)], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def _paint(entity="sensor.flight_watcher_pilot_schedule"):
    return f"""
      const paint = (a, sig) => {{ const c = new FlightWatcherPilotCard(); c.setConfig({{}});
        c.hass = {{states: {{"{entity}": {{last_updated: sig || "1", attributes: a}}}}, callService() {{}}}}; return c; }};
      const html = (c) => c.shadowRoot.body.innerHTML;
    """


def test_contact_links_in_the_header_and_the_crew_lists(tmp_path):
    a = dict(_payload(), contact=ROE)
    hostile = dict(_payload(), contact={"name": "Roe, Rick", "phones": [{"label": "<img src=x>", "number": "<b>1</b>", "tel": "+18085550114"},
                                                                       {"label": "cell", "number": "x", "tel": "javascript:alert(1)"}],
                                        "emails": ['x" onmouseover="alert(1)@example.com', "ok.roe@example.com"]})
    r = _node(tmp_path, _paint() + f"""
      const a = {json.dumps(a)}, none = {json.dumps(_payload())}, bad = {json.dumps(hostile)};
      const loading = {json.dumps(dict(_payload(), status="loading", contact=ROE))};
      const c = paint(a), n = paint(none), b = paint(bad), l = paint(loading);
      const local = paint(a); local._lookup({{detail: {{emp: "20001"}}}});  // another pilot asked: the reply is still to come
      console.log(JSON.stringify({{a: html(c), none: html(n), bad: html(b), loading: html(l), local: html(local)}}));
    """)
    h = r["a"]
    head = h.split("</div>")[0]
    assert '<a class="ct" href="tel:+18085550112" title="Call 808-555-0112">Call cell</a>' in head
    assert '<a class="ct" href="sms:+18085550112" title="Text 808-555-0112">Text cell</a>' in head
    assert 'href="tel:+18085550113"' in head and "Call home" in head and "sms:+18085550113" not in head  # a landline: no text
    assert '<a class="ct" href="mailto:rick.roe@example.com" title="Mail rick.roe@example.com">Mail</a>' in head
    # the crew lists: the looked-up pilot's own name gets the small links (first number only); nobody else does
    rows = [x for x in h.split('<td class="crew">')[1:]]
    roe = [x for x in rows if "Roe, Rick" in x.split("</td>")[0]]
    assert roe and all('<span class="cts mini"><a class="ct" href="tel:+18085550112"' in x.split("</td>")[0] for x in roe)
    assert all("tel:+18085550113" not in x.split("</td>")[0] for x in roe)
    assert all(x.split("</td>")[0].count("href=") == 3 for x in roe)  # call, text, mail
    doe_only = [x.split("</td>")[0] for x in rows if "Roe, Rick" not in x.split("</td>")[0] and "Doe, Jane" in x]
    assert doe_only == [] or all("href" not in x for x in doe_only)
    assert "href=" not in r["none"] and 'class="cts' not in r["none"]  # no list entry: no link, the card as before
    b = r["bad"]
    assert "javascript:" not in b and "onmouseover" not in b and "<img" not in b and "<b>1" not in b
    assert 'href="tel:+18085550114"' in b and "&lt;img src=x&gt;" in b and 'href="mailto:ok.roe@example.com"' in b
    assert 'href="tel:+18085550112"' in r["loading"]  # the Watcher's own loading reply carries this pilot's entry
    assert "href=" not in r["local"]  # a new lookup on its way: the last pilot's links are not shown under its number


def test_the_second_pilots_copy_reads_its_own_sensor(tmp_path):
    src = cards.build("1.4.8", ["james"])["flight-watcher-pilot-card-james.js"]
    r = _node(tmp_path, _paint("sensor.flight_watcher_james_pilot_schedule") + f"""
      const c = paint({json.dumps(dict(_payload(), contact=ROE))});
      console.log(JSON.stringify({{h: html(c)}}));
    """, src=src)
    assert 'href="sms:+18085550112"' in r["h"]


def test_contact_links_fit_a_phone(tmp_path):
    """In a real browser at 390 px and 1100 px: the header with its links has no sideways scroll and every link is
    a tap target of at least 20 px; FW_PILOT_SHOTS=<dir> keeps the screenshots."""
    sync_api = pytest.importorskip("playwright.sync_api")
    from test_cards import _chromium
    states = {"sensor.flight_watcher_pilot_schedule": {"last_updated": "a", "attributes": dict(_payload(), contact=ROE)}}
    page = ("<!doctype html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<style>body{margin:0;font-family:sans-serif;--primary-color:#03a9f4}</style></head><body><script>"
            "customElements.define('ha-card', class extends HTMLElement {});</script><script>"
            + open(CARD, encoding="utf-8").read() + "</script><script>"
            "const c = document.createElement('flight-watcher-pilot-card'); c.setConfig({}); document.body.appendChild(c);"
            f"c.hass = {{states: {json.dumps(states)}, callService() {{}}}};</script></body></html>")
    shots = os.environ.get("FW_PILOT_SHOTS") or str(tmp_path)
    with sync_api.sync_playwright() as p:
        b = _chromium(p)
        if not b:
            pytest.skip("no Chromium for Playwright")
        try:
            for w in (390, 1100):
                pg = b.new_page(viewport={"width": w, "height": 900})
                pg.set_content(page)
                m = pg.evaluate("""() => {
                  const r = document.querySelector('flight-watcher-pilot-card').shadowRoot, card = r.querySelector('ha-card');
                  const hd = r.querySelector('.hd'), links = [...hd.querySelectorAll('a.ct')].map((a) => a.getBoundingClientRect());
                  const mini = [...r.querySelectorAll('.cts.mini a.ct')].map((a) => a.getBoundingClientRect());
                  return {doc: document.documentElement.scrollWidth, win: window.innerWidth, card: card.getBoundingClientRect().right,
                          n: links.length, right: Math.max(...links.map((x) => x.right)), h: Math.min(...links.map((x) => x.height)),
                          mn: mini.length, mh: Math.min(...mini.map((x) => x.height)), mw: Math.min(...mini.map((x) => x.width))};
                }""")
                assert m["doc"] <= m["win"] and m["card"] <= w + 0.5 and m["right"] <= w + 0.5, (w, m)
                assert m["n"] == 4 and m["h"] >= 20, (w, m)  # call and text the cell, call home, mail
                # FW-0066 review: the crew-list links are tap targets too (Call dials at once): 24 px high at least
                # (they sit in the calendar grid, which scrolls sideways in its own box on a phone: the page does not)
                assert m["mn"] >= 3 and m["mh"] >= 24 and m["mw"] >= 24, (w, m)
                pg.screenshot(path=os.path.join(shots, f"pilot_contact_{w}.png"))
                pg.close()
        finally:
            b.close()


def test_crew_links_match_flicas_spelling_of_the_pilot(tmp_path):
    """FW-0066 review: the crew lists carry FLICA's spelling of a name; a contact list may spell it otherwise (a suffix,
    a second last name), so the pilot's own crew-list entries are found by the sensor's name as well as the contact's."""
    a = dict(_payload(), contact=dict(ROE, name="Roe Jr, Rick"))
    r = _node(tmp_path, _paint() + f"""
      const c = paint({json.dumps(a)});
      console.log(JSON.stringify({{h: html(c)}}));
    """)
    rows = [x.split("</td>")[0] for x in r["h"].split('<td class="crew">')[1:]]
    roe = [x for x in rows if "Roe, Rick" in x]
    assert roe and all('<span class="cts mini"><a class="ct" href="tel:+18085550112"' in x for x in roe)
    assert all("cts mini" not in x for x in rows if "Roe, Rick" not in x)
