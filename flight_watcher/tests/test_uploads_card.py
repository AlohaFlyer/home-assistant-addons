"""1.4.5: the dashboard uploads card (www/flight-watcher-uploads-card.js). In node with a stub hass: the ingress
address and session the way HA's own app panels get them, the cookie, re-validation, admin only, escaping. In a real
browser (node Playwright, tests/uploads_card_render.js): an upload end to end against stubbed callWS and ingress
answers, at 390 px and 1100 px with no sideways scroll. Made-up data only."""
import json
import os
import shutil
import subprocess

import pytest

import cards

HERE = os.path.dirname(os.path.abspath(__file__))
CARD = os.path.join(HERE, "..", "www", "flight-watcher-uploads-card.js")

HARNESS = r"""
const els = () => { const m = {}; return (sel) => m[sel] || (m[sel] = {addEventListener() {}, value: "", files: [], hidden: false, disabled: false, innerHTML: "", textContent: ""}); };
globalThis.HTMLElement = class { attachShadow() { const q = els(); this.shadowRoot = {innerHTML: "", querySelector: q}; return this.shadowRoot; } };
globalThis.customElements = {define() {}}; globalThis.window = {};
const cookies = []; globalThis.document = {set cookie(v) { cookies.push(v); }, get cookie() { return cookies.join("; "); }, visibilityState: "visible"};
globalThis.location = {protocol: "https:"};
const fetched = []; let DATA = {files: [], seniority: null, version: "9.9.9", max_bytes: 25000000};
globalThis.fetch = async (url, opts) => { fetched.push(url); return {ok: true, status: 200, json: async () => DATA}; };
const calls = [];
let INFO = {ingress_url: "/api/hassio_ingress/tok123/", state: "started", ingress: true}, BADVAL = false, SESS = "a".repeat(128);
const hass = (admin) => ({user: {is_admin: admin}, callWS: async (m) => {
  calls.push(JSON.parse(JSON.stringify(m)));
  if (m.endpoint.endsWith("/info")) return INFO;
  if (m.endpoint === "/ingress/session") return {session: SESS};
  if (m.endpoint === "/ingress/validate_session" && BADVAL) throw {code: "unknown_error", message: "Invalid session"};
  return {};
}});
const tick = () => new Promise((r) => setTimeout(r, 0));
"""


def _node(body, src=None):
    if not shutil.which("node"):
        pytest.skip("node not installed")
    js = HARNESS + (src if src is not None else open(CARD, encoding="utf-8").read()) + "\n(async () => {\n" + body + "\n})();"
    out = subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_card_syntax():
    if not shutil.which("node"):
        pytest.skip("node not installed")
    assert subprocess.run(["node", "--check", CARD], capture_output=True).returncode == 0


def test_ingress_session_cookie_and_list():
    r = _node("""
      const c = new FlightWatcherUploadsCard(); c.setConfig({}); c.hass = hass(true);
      for (let i = 0; i < 20 && !c._data; i++) await tick();
      const first = {calls: calls.slice(), cookies: cookies.slice(), fetched: fetched.slice(), data: !!c._data, err: c._err};
      c._sessAt = Date.now() - 6 * 60 * 1000;  // older than the refresh mark: validated before the next call
      await c._ingress();
      const validated = calls.slice(first.calls.length);
      BADVAL = true; SESS = "b".repeat(128); c._sessAt = 0;  // lapsed: a new session
      await c._ingress();
      const renewed = calls.slice(first.calls.length + validated.length);
      location.protocol = "http:"; await c._session(true);
      console.log(JSON.stringify({first, validated, renewed, plain: cookies[cookies.length - 1], base: c._base}));
    """)
    f = r["first"]
    assert f["calls"] == [{"type": "supervisor/api", "endpoint": "/addons/43b22650_flight_watcher/info", "method": "get"},
                          {"type": "supervisor/api", "endpoint": "/ingress/session", "method": "post"}]
    assert f["cookies"] == ["ingress_session=" + "a" * 128 + ";path=/api/hassio_ingress/;SameSite=Strict;Secure"]
    assert f["fetched"] == ["/api/hassio_ingress/tok123/api/uploads"] and f["data"] and f["err"] == ""
    assert r["validated"] == [{"type": "supervisor/api", "endpoint": "/ingress/validate_session", "method": "post",
                               "data": {"session": "a" * 128}}]
    assert [m["endpoint"] for m in r["renewed"]] == ["/ingress/validate_session", "/ingress/session"]
    assert r["plain"] == "ingress_session=" + "b" * 128 + ";path=/api/hassio_ingress/;SameSite=Strict"  # http: no Secure
    assert r["base"] == "/api/hassio_ingress/tok123/"


def test_ingress_address_checks():
    r = _node("""
      const out = {};
      for (const [k, info] of Object.entries({entry: {ingress_entry: "/api/hassio_ingress/tok9", state: "started"},
          evil: {ingress_url: "https://evil.example/x/", state: "started"}, stopped: {ingress_url: "/api/hassio_ingress/t/", state: "stopped"},
          none: {ingress: false}})) {
        INFO = info; const n = calls.length, nf = fetched.length;
        const c = new FlightWatcherUploadsCard(); c.setConfig({slug: "local_test"}); c.hass = hass(true);
        for (let i = 0; i < 20 && !c._data && !c._err; i++) await tick();
        out[k] = {base: c._base, err: c._err, fetched: fetched.slice(nf), endpoint: calls[n].endpoint};
      }
      let bad = ""; try { new FlightWatcherUploadsCard().setConfig({slug: "../x"}); } catch (e) { bad = e.message; }
      console.log(JSON.stringify({...out, bad}));
    """)
    assert r["entry"]["base"] == "/api/hassio_ingress/tok9/" and r["entry"]["fetched"] == ["/api/hassio_ingress/tok9/api/uploads"]
    assert r["entry"]["endpoint"] == "/addons/local_test/info"
    assert r["evil"]["fetched"] == [] and r["evil"]["err"] == "The app's Web UI address was not found."
    assert r["stopped"]["fetched"] == [] and r["stopped"]["err"] == "The Flight Watcher app is not running (stopped)."
    assert r["none"]["err"] == "The app has no Web UI to upload to."
    assert r["bad"].startswith("slug:")


def test_not_an_admin_no_call():
    r = _node("""
      const c = new FlightWatcherUploadsCard(); c.setConfig({}); c.hass = hass(false);
      for (let i = 0; i < 5; i++) await tick();
      const u = new FlightWatcherUploadsCard(); u.setConfig({}); u.hass = {callWS: hass(true).callWS};  // no user yet
      for (let i = 0; i < 5; i++) await tick();
      let err = ""; try { await c._ingress(); } catch (e) { err = e.message; }
      await c._upload(); await c._load();
      console.log(JSON.stringify({html: c.shadowRoot.innerHTML, nouser: u.shadowRoot.innerHTML, calls, cookies, fetched, err}));
    """)
    assert "Uploads are for the Home Assistant admin." in r["html"] and "Uploads are for the Home Assistant admin." in r["nouser"]
    assert "<input" not in r["html"] and r["calls"] == [] and r["cookies"] == [] and r["fetched"] == []
    assert r["err"] == "Uploads are for the Home Assistant admin."


def test_escaping_and_dates():
    r = _node("""
      const c = new FlightWatcherUploadsCard(); c.setConfig({title: "<b>Up</b>"});
      const bad = "<img src=x onerror=alert(1)>";
      const list = c._listHtml({files: [{name: bad + ".pdf", kind: "other", size: 2048, uploaded_at: bad, has_text: false},
        {name: "2026-12_award.pdf", kind: "award", month: "2026-12", size: 2500000, uploaded_at: "2026-11-20T09:30:00-10:00", has_text: true},
        {name: "2026-12_pairings.pdf", kind: "pairings", month: "2026-12", size: 900000, uploaded_at: "2026-11-20T19:31:00Z", has_text: true},
        {name: "2027-01_award.pdf", kind: "award", month: "2027-01", size: 1, uploaded_at: "", has_text: false},
        {name: "seniority_2026-11-06.pdf", kind: "seniority", day: "2026-11-06", size: 5000, uploaded_at: "2026-11-06T09:00:00-10:00", has_text: true}]});
      const sen = c._senHtml({pilots: bad, source: bad, list_date: bad, uploaded_at: "2026-11-20T09:30:00-10:00", carried: 3, base: {as_of: bad}, rejects: 2});
      const aw = c._senHtml({pilots: 42, source: "award 2026-12", as_of: "2026-12-01", carried: 12, base: {as_of: "2026-03-01"}});
      c.hass = hass(false);
      console.log(JSON.stringify({list, sen, aw, none: c._senHtml(null), title: c.shadowRoot.innerHTML,
        next: [fwUpNextMonth(Date.UTC(2027, 0, 1, 5)), fwUpNextMonth(Date.UTC(2026, 11, 1, 5)), fwUpNextMonth(Date.UTC(2026, 10, 6, 20))],
        hst: fwUpHst("2026-11-20T19:31:00Z"), size: [fwUpSize(2048), fwUpSize(2500000)]}));
    """)
    for k in ("list", "sen", "title"):
        assert "<img" not in r[k] and "<b>Up" not in r[k], k
    assert "&lt;img src=x onerror=alert(1)&gt;.pdf" in r["list"] and "&lt;b&gt;Up&lt;/b&gt;" in r["title"]
    rows = r["list"].split('<div class="f">')[1:]
    assert [x.split("</b>")[0].split("<b>")[1] + x.split("</b>")[1].split("</div>")[0] for x in rows] == [
        "Award Jan 2027", "Award Dec 2026", "Pairings package Dec 2026", "Seniority list",
        "Other file &lt;img src=x onerror=alert(1)&gt;.pdf"]
    assert "2.4 MB · uploaded Nov 20 09:30 HST · <span class=\"ok\">read</span>" in r["list"]
    assert "not read: no text copy" in r["list"] and "uploaded ? HST" in r["list"]
    assert "<b>42 pilots</b> from the Dec 2026 award · as of 2026-12-01" in r["aw"] and "12 more kept from the seniority list of 2026-03-01" in r["aw"]
    assert "None on file yet" in r["none"]
    assert r["next"] == ["2027-01", "2026-12", "2026-12"]  # Dec 31 19:00 HST is still December; Nov 30 HST: December
    assert r["hst"] == "Nov 20 09:31" and r["size"] == ["2 KB", "2.4 MB"]


def test_second_pilot_copy_keeps_the_apps_slug_and_admin_rule():
    src = cards.build("1.4.5", ["james"])["flight-watcher-uploads-card-james.js"]
    assert 'customElements.define("flight-watcher-uploads-card-james"' in src and "Ryan" not in src
    r = _node("""
      const c = new FlightWatcherUploadsCard(); c.setConfig({}); c.hass = hass(true);
      for (let i = 0; i < 20 && !c._data; i++) await tick();
      const u = new FlightWatcherUploadsCard(); u.setConfig({}); const n = calls.length; u.hass = hass(false);
      console.log(JSON.stringify({calls, fetched, user: u.shadowRoot.innerHTML, after: calls.length - n}));
    """, src=src)
    assert r["calls"][0]["endpoint"] == "/addons/43b22650_flight_watcher/info"  # the one app, not a per-pilot slug
    assert r["fetched"] == ["/api/hassio_ingress/tok123/api/uploads"]
    assert "Uploads are for the Home Assistant admin." in r["user"] and r["after"] == 0


def test_renders_and_uploads_in_a_browser(tmp_path):
    """Node Playwright (require('playwright'); chromium.launch()) against stubbed callWS and ingress answers: the
    upload sends the form with the session cookie, every value is escaped, a non-admin makes no request, and the card
    fits 390 px and 1100 px with no sideways scroll. FW_UPLOADS_SHOTS=<dir> keeps the screenshots."""
    if not shutil.which("node"):
        pytest.skip("node not installed")
    if subprocess.run(["node", "-e", "require('playwright')"], capture_output=True).returncode:
        pytest.skip("node Playwright not installed")
    shots = os.environ.get("FW_UPLOADS_SHOTS") or str(tmp_path)
    out = subprocess.run(["node", os.path.join(HERE, "uploads_card_render.js"), CARD, shots],
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    r = json.loads(out.stdout.strip().splitlines()[-1])
    if r.get("skip"):
        pytest.skip(r["skip"])
    for w in ("390", "1100"):
        m = r["fit"][w]
        assert m["doc"] <= m["win"] and m["card"] <= int(w) + 0.5 and m["inner"] <= 0, (w, m)
    assert r["month"] == r["expect_month"] and r["kinds"] == ["award", "pairings", "seniority"]
    assert r["sen_toggle"] == {"month_hidden": True, "date_hidden": False} and r["award_toggle"] == {"month_hidden": False, "date_hidden": True}
    assert r["rows_before"] == 4 and r["rows_after"] == 5 and r["pwned"] is None and r["imgs"] == 0
    assert r["msg"].startswith("Saved 2026-12_award.pdf (1 KB). Dates of hire: 30 pilots") and r["msg_class"] == "ok"
    p = r["post"]
    assert "ingress_session=" + "f" * 128 in p["cookie"] and len(r["gets"]) == 2 and all("ingress_session=" in g for g in r["gets"])
    for part in ('name="kind"\r\n\r\naward\r\n', 'name="month"\r\n\r\n2026-12\r\n', 'filename="award.pdf"', "%PDF-1.4 synthetic"):
        assert part in p["body"], part
    assert r["ws"] == ["/addons/43b22650_flight_watcher/info", "/ingress/session"]
    assert r["user"] == {"ws": 0, "ingress": 0, "text": "Uploads are for the Home Assistant admin."}
    assert r["refused"]["msg"] == "That file is not a PDF." and r["refused"]["class"] == "err" and r["refused"]["posts"] == 1
    for name in r["shots"]:
        assert os.path.getsize(os.path.join(shots, name)) > 1000
