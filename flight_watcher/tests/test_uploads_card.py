"""1.4.5: the dashboard uploads card (www/flight-watcher-uploads-card.js). In node with a stub hass: the ingress
address and session the way HA's own app panels get them, the cookie, re-validation, escaping. 1.4.8 (FW-0066): the
card picks its path from the user: an admin uses ingress, anyone else sensor.flight_watcher_uploads and chunks over
mqtt.publish (never a Supervisor call). In a real browser (node Playwright, tests/uploads_card_render.js): an upload
end to end each way against stubbed answers, at 390 px and 1100 px with no sideways scroll. Made-up data only."""
import json
import os
import shutil
import subprocess
import tempfile

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
    # a file, not node -e: -e puts node's own modules (crypto among them) in scope, which a page never has
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, "t.js")
        open(f, "w", encoding="utf-8").write(js)
        out = subprocess.run(["node", f], capture_output=True, text=True, timeout=30)
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


USER_STATES = """{"sensor.flight_watcher_uploads": {state: "2", last_updated: "t1", attributes: {
  files: [{name: "2026-12_award.pdf", kind: "award", month: "2026-12", size: 2500000, uploaded_at: "2026-11-20T09:30:00-10:00", has_text: true},
          {name: "contacts_2026-11-07.csv", kind: "contacts", day: "2026-11-07", size: 3000, uploaded_at: "2026-11-07T09:30:00-10:00", has_text: true}],
  seniority: null, contacts: {count: 312, with_phone: 300, with_email: 250, rejects: 0, file: "contacts_2026-11-07.csv", uploaded_at: "2026-11-07T09:30:00-10:00"},
  version: "1.4.8", max_bytes: 16711680, mqtt_max_bytes: 25000000, wanted: [{kind: "pairings", month: "2026-11", why: "current"}]}}}"""


def test_not_an_admin_makes_no_supervisor_call_and_reads_the_sensor():
    """FW-0066: a user who is not an admin gets the form and what is on file from sensor.flight_watcher_uploads,
    with no Supervisor call, cookie or ingress request; the ingress path stays an admin's."""
    r = _node("""
      const states = """ + USER_STATES + """;
      const c = new FlightWatcherUploadsCard(); c.setConfig({}); c.hass = {...hass(false), states};
      for (let i = 0; i < 5; i++) await tick();
      const html = c.shadowRoot.innerHTML, list = c._q("[data-list]").innerHTML, sen = c._q("[data-sen]").innerHTML;
      const none = new FlightWatcherUploadsCard(); none.setConfig({}); none.hass = {...hass(false), states: {}};  // a Watcher before 1.4.8
      const off = new FlightWatcherUploadsCard(); off.setConfig({}); off.hass = {...hass(false), states: {"sensor.flight_watcher_uploads": {state: "unavailable", attributes: {}}}};
      const u = new FlightWatcherUploadsCard(); u.setConfig({}); u.hass = {callWS: hass(true).callWS, states};  // no user yet
      for (let i = 0; i < 5; i++) await tick();
      let err = ""; try { await c._ingress(); } catch (e) { err = e.message; }
      await c._load();
      console.log(JSON.stringify({html, list, sen, none: none._err, off: off._err, nouser: u._data && u._data.version, calls, cookies, fetched, err}));
    """)
    assert "<input" in r["html"] and "Sent to the Watcher in parts" in r["html"] and "admin" not in r["html"]
    assert r["calls"] == [] and r["cookies"] == [] and r["fetched"] == []
    assert "Contact list" in r["list"] and "Award</b> Dec 2026" in r["list"] and "Wanted:</b> the Nov 2026 pairings package" in r["list"]
    assert "<b>312 pilots</b> · 300 with a phone · 250 with an email" in r["sen"] and "Flight Watcher 1.4.8" in r["sen"]
    assert r["none"].startswith("The Watcher has not listed its files yet") and "1.4.8" in r["none"]
    assert r["off"] == "The Flight Watcher app is not running (its sensors are unavailable)."
    assert r["nouser"] == "1.4.8"
    assert r["err"] == "The app's Web UI is for the Home Assistant admin."


def test_the_card_picks_the_path_from_the_user():
    """FW-0066: the same upload goes through ingress for an admin (no mqtt.publish) and in chunks over mqtt.publish
    for anyone else (no Supervisor call); a refusal the Watcher sends part way stops the sending; a contact list on a
    plain http page is refused before anything is sent; the Watcher's progress shows once all parts are out."""
    r = _node("""
      const xhrs = [];
      globalThis.FormData = class { constructor() { this.names = []; } append(n) { this.names.push(n); } };
      globalThis.XMLHttpRequest = class { constructor() { xhrs.push(this); this.upload = {}; }
        open(m, u) { this.url = u; } send(fd) { this.fd = fd.names; this.status = 200;
          this.responseText = JSON.stringify({ok: true, message: "Saved 2026-12_award.pdf (400 KB)."}); setTimeout(() => this.onload(), 0); } };
      const raw = new Uint8Array(500000); raw.set([37, 80, 68, 70]);  // %PDF, three parts
      const file = (name, type, n) => ({name, type, size: (n || raw).length, arrayBuffer: async () => (n || raw).buffer});
      const kp = await crypto.subtle.generateKey({name: "RSA-OAEP", modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: "SHA-256"}, true, ["encrypt", "decrypt"]);
      const states = {...""" + USER_STATES + """, "sensor.flight_watcher_settings": {state: "True", attributes: {
        pubkey: Buffer.from(await crypto.subtle.exportKey("spki", kp.publicKey)).toString("base64"), kid: "k1"}}};
      const run = async (admin, reply, kind, f) => {
        const pubs = [], seen = [];
        const c = new FlightWatcherUploadsCard(); c.setConfig({});
        const h = {...hass(admin), states, callService: async (d, s, data) => { const p = JSON.parse(data.payload); pubs.push(p);
          const st = reply(p); if (st) c.hass = {...h, states: {...states, "sensor.flight_watcher_upload_status": {state: st.state, attributes: st}}};
          seen.push(c._q("[data-prog]").textContent); }};
        c.hass = h;
        for (let i = 0; i < 20 && admin && !c._data; i++) await tick();
        c._q("[data-kind]").value = kind || "award"; c._q("[data-month]").value = "2026-12";
        c._q("[data-pdf]").files = [f || file("a.pdf", "application/pdf")];
        const n0 = calls.length, x0 = xhrs.length;
        await c._upload();
        return {pubs: pubs.map((p) => ({i: p.i, n: p.n, kind: p.kind, month: p.month, sealed: !!p.enc})), msg: c._msg, ws: calls.length - n0, xhr: xhrs.length - x0, seen};
      };
      const done = (p) => p.i === p.n - 1 ? {id: p.id, state: "done", ok: true, message: "Saved 2026-12_award.pdf (488 KB)."} :
        {id: p.id, state: "receiving", got: p.i + 1, total: p.n, message: `Received ${p.i + 1} of ${p.n} parts.`};
      const admin = await run(true, () => null);
      const user = await run(false, done);
      const refused = await run(false, (p) => p.i === 0 ? {id: p.id, state: "error", ok: false, message: "Too large: 30.0 MB (the Watcher takes up to 25 MB)."} : null);
      Object.defineProperty(globalThis, "crypto", {value: {getRandomValues: (a) => require("crypto").getRandomValues(a)}, configurable: true});
      const plainCsv = await run(false, done, "contacts", file("list.csv", "text/csv", new TextEncoder().encode(["Name,Emp", "Doe Jane,10001"].join(String.fromCharCode(10)))));
      const plainPdf = await run(false, done);
      console.log(JSON.stringify({admin, user, refused, plainCsv, plainPdf}));
    """)
    a, u = r["admin"], r["user"]
    assert a["pubs"] == [] and a["xhr"] == 1 and a["msg"]["text"] == "Saved 2026-12_award.pdf (400 KB)."  # ingress: no mqtt.publish
    assert u["ws"] == 0 and u["xhr"] == 0 and u["msg"] == {"ok": True, "text": "Saved 2026-12_award.pdf (488 KB)."}
    assert [p["i"] for p in u["pubs"]] == [0, 1, 2] and all(p["n"] == 3 and p["sealed"] and p["kind"] == "award" and p["month"] == "2026-12" for p in u["pubs"])
    assert u["seen"] == ["Uploading the Dec 2026 award (488 KB)...", "Sending the Dec 2026 award (488 KB)... 30%",
                         "Sending the Dec 2026 award (488 KB)... 60%"]  # the line at each publish: 10 % steps
    rf = r["refused"]
    assert len(rf["pubs"]) == 1 and rf["msg"] == {"ok": False, "text": "Too large: 30.0 MB (the Watcher takes up to 25 MB)."}
    pc = r["plainCsv"]
    assert pc["pubs"] == [] and pc["msg"]["ok"] is False and "https address" in pc["msg"]["text"]
    pp = r["plainPdf"]
    assert pp["msg"]["ok"] is True and len(pp["pubs"]) == 3 and not any(p["sealed"] for p in pp["pubs"])


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


def test_wanted_packages_are_asked_for_above_the_files():
    """FW-0057 (1.4.7 verify): api/uploads 'wanted' shows above the files (and with none on file), oldest first; a month
    that is not YYYY-MM is left out, so nothing from the answer reaches the page unchecked; no 'wanted' shows nothing."""
    r = _node("""
      const c = new FlightWatcherUploadsCard(); c.setConfig({});
      const bad = "<img src=x onerror=alert(1)>";
      const wanted = [{kind: "pairings", month: "2026-12", why: "previous"}, {kind: "pairings", month: "2027-01", why: "current"},
        {kind: "pairings", month: bad, why: bad}];
      const none = c._listHtml({files: [], wanted});
      const some = c._listHtml({files: [{name: "2026-11_pairings.pdf", kind: "pairings", month: "2026-11", size: 900000,
        uploaded_at: "2026-11-20T09:30:00-10:00", has_text: true}], wanted: wanted.slice(1)});
      const old = c._listHtml({files: []});
      console.log(JSON.stringify({none, some, old, add: [fwUpAdd("2026-12", 1), fwUpAdd("2026-10", 1), fwUpAdd("2027-01", -1)]}));
    """)
    assert r["none"].index("Dec 2026") < r["none"].index("Jan 2027") < r["none"].index("Nothing uploaded yet.")
    assert ("<b>Wanted:</b> the Dec 2026 pairings package<div class=\"u\">Trips other pilots started in Dec 2026 that run into "
            "Jan 2027 reach the crew index only from pilot lookups until it is on file.</div>") in r["none"]
    assert "The trip details and the crew index for Jan 2027 need it." in r["none"]
    assert "<img" not in r["none"] and "img src" not in r["none"] and r["none"].count("Wanted:") == 2
    assert r["some"].index("Wanted:") < r["some"].index('<div class="f">') and r["some"].count("Wanted:") == 1
    assert "Wanted" not in r["old"] and r["old"] == '<div class="u">Nothing uploaded yet.</div>'
    assert r["add"] == ["2027-01", "2026-11", "2026-12"]


def test_second_pilot_copy_keeps_the_apps_slug_and_uses_its_own_topic():
    """The James dashboard's copy: an admin reaches the one app's ingress (its slug is not renamed); a user who is not
    an admin (James) reads sensor.flight_watcher_james_uploads and publishes to flight_watcher_james/upload/chunk,
    sealed with his Watcher's key (sensor.flight_watcher_james_settings); the files land in the shared folder."""
    src = cards.build("1.4.8", ["james"])["flight-watcher-uploads-card-james.js"]
    assert 'customElements.define("flight-watcher-uploads-card-james"' in src and "Ryan" not in src
    r = _node("""
      const c = new FlightWatcherUploadsCard(); c.setConfig({}); c.hass = hass(true);
      for (let i = 0; i < 20 && !c._data; i++) await tick();
      const pubs = [], states = {"sensor.flight_watcher_james_uploads": {state: "0", last_updated: "1", attributes: {files: [], version: "1.4.8"}},
        "sensor.flight_watcher_james_settings": {state: "True", attributes: {pubkey: "", kid: ""}}};
      const u = new FlightWatcherUploadsCard(); u.setConfig({}); const n = calls.length;
      const h = {...hass(false), states, callService: async (d, s, data) => { const p = JSON.parse(data.payload); pubs.push(data.topic);
        if (p.i === p.n - 1) u.hass = {...h, states: {...states, "sensor.flight_watcher_james_upload_status": {state: "done", attributes: {id: p.id, state: "done", ok: true, message: "Saved."}}}}; }};
      u.hass = h;
      u._q("[data-kind]").value = "seniority";
      u._q("[data-pdf]").files = [{name: "s.pdf", type: "application/pdf", size: 9, arrayBuffer: async () => new TextEncoder().encode("%PDF-1.4 ").buffer}];
      await u._upload();
      console.log(JSON.stringify({calls, fetched, data: u._data, after: calls.length - n, pubs, msg: u._msg}));
    """, src=src)
    assert r["calls"][0]["endpoint"] == "/addons/43b22650_flight_watcher/info"  # the one app, not a per-pilot slug
    assert r["fetched"] == ["/api/hassio_ingress/tok123/api/uploads"]
    assert r["after"] == 0 and r["data"]["version"] == "1.4.8"
    assert r["pubs"] == ["flight_watcher_james/upload/chunk"] and r["msg"] == {"ok": True, "text": "Saved."}


def test_renders_and_uploads_in_a_browser(tmp_path):
    """Node Playwright (require('playwright'); chromium.launch()) against stubbed callWS and ingress answers: the
    upload sends the form with the session cookie, every value is escaped, a non-admin makes no request, and the card
    fits 390 px and 1100 px with no sideways scroll. FW_UPLOADS_SHOTS=<dir> keeps the screenshots."""
    if not shutil.which("node"):
        pytest.skip("node not installed")
    if subprocess.run(["node", "-e", "require('playwright')"], capture_output=True).returncode:
        pytest.skip("node Playwright not installed")
    import sealed as SEAL
    import chunks as UP
    key = SEAL.load_key(str(tmp_path / "k.pem"))
    shots = os.environ.get("FW_UPLOADS_SHOTS") or str(tmp_path)
    out = subprocess.run(["node", os.path.join(HERE, "uploads_card_render.js"), CARD, shots, SEAL.public_info(key)["pubkey"]],
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    r = json.loads(out.stdout.strip().splitlines()[-1])
    if r.get("skip"):
        pytest.skip(r["skip"])
    for w in ("390", "1100"):
        m = r["fit"][w]
        assert m["doc"] <= m["win"] and m["card"] <= int(w) + 0.5 and m["inner"] <= 0, (w, m)
    assert r["month"] == r["expect_month"] and r["kinds"] == ["award", "pairings", "seniority", "contacts"]
    assert r["sen_toggle"] == {"month_hidden": True, "date_hidden": False} and r["award_toggle"] == {"month_hidden": False, "date_hidden": True}
    assert r["rows_before"] == 4 and r["rows_after"] == 5 and r["pwned"] is None and r["imgs"] == 0
    assert r["wanted"] == ["Wanted: the Oct 2026 pairings packageTrips other pilots started in Oct 2026 that run into Nov 2026 "
                           "reach the crew index only from pilot lookups until it is on file."]  # FW-0057
    assert r["msg"].startswith("Saved 2026-12_award.pdf (1 KB). Dates of hire: 30 pilots") and r["msg_class"] == "ok"
    assert r["status"] == r["msg"] and r["live"] == {"msg": ["status", "polite"], "prog": "polite"}  # announced
    assert '- status: "Saved 2026-12_award.pdf (1 KB).' in r["aria"], r["aria"]
    p = r["post"]
    assert "ingress_session=" + "f" * 128 in p["cookie"] and len(r["gets"]) == 2 and all("ingress_session=" in g for g in r["gets"])
    for part in ('name="kind"\r\n\r\naward\r\n', 'name="month"\r\n\r\n2026-12\r\n', 'filename="award.pdf"', "%PDF-1.4 synthetic"):
        assert part in p["body"], part
    assert r["ws"] == ["/addons/43b22650_flight_watcher/info", "/ingress/session"]
    u = r["user"]  # FW-0066: a user who is not an admin, in Chromium (an https page: WebCrypto seals the file)
    assert (u["ws"], u["ingress"], u["secure"]) == (0, 0, True)
    assert u["toggle"] == {"month_hidden": True, "date_hidden": True, "label": "File (PDF, CSV or XLSX)",
                           "accept": "application/pdf,.pdf,text/csv,.csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,.xlsx"}
    assert u["msg"].startswith("Saved contacts_2026-11-20.csv") and u["msg_class"] == "ok"
    assert (u["rows_before"], u["rows_after"]) == (4, 5) and "1 pilot · 1 with a phone · 1 with an email" in u["sen"]
    m = u["fit"]
    assert m["doc"] <= m["win"] and m["card"] <= 390.5 and m["inner"] <= 0, m
    pubs = u["pubs"]
    assert [(p["d"], p["s"], p["data"]["topic"], p["data"]["qos"], p["data"]["retain"]) for p in pubs] == [
        ("mqtt", "publish", "flight_watcher/upload/chunk", 1, False)]
    msg = json.loads(pubs[0]["data"]["payload"])
    assert msg["kind"] == "contacts" and msg["enc"]["v"] == 1 and "Doe" not in pubs[0]["data"]["payload"]  # only ciphertext
    a = UP.Assembler(str(tmp_path / "staging"), 25_000_000, key=key)
    _, ready = a.add(msg)
    fields, data = a.finish(ready)
    assert fields == {"kind": "contacts", "month": "", "list_date": ""} and data.startswith(b"Name,Emp #,Cell,Email\nDoe, Jane")
    assert r["refused"]["msg"] == "That file is not a PDF." and r["refused"]["class"] == "err" and r["refused"]["posts"] == 1
    for name in r["shots"]:
        assert os.path.getsize(os.path.join(shots, name)) > 1000


def test_a_pdf_over_the_ingress_limit_is_refused_before_it_is_sent():
    """Review fix: the Supervisor's ingress proxy refuses a body over 16 MiB (HTTP 413) only after it has all arrived,
    so the card refuses a larger PDF before any request, even when the app advertises its own 25 MB cap (the lower of
    the two wins); a PDF under the limit is sent (stub XMLHttpRequest)."""
    r = _node("""
      const xhrs = [];
      globalThis.FormData = class { constructor() { this.names = []; } append(n) { this.names.push(n); } };
      globalThis.XMLHttpRequest = class { constructor() { xhrs.push(this); this.upload = {}; }
        open(m, u) { this.url = u; } send(fd) { this.fd = fd.names; this.status = 200;
          this.responseText = JSON.stringify({ok: true, message: "Saved 2026-12_pairings.pdf (15625 KB)."}); setTimeout(() => this.onload(), 0); } };
      DATA = {files: [], seniority: null, version: "1.4.5", max_bytes: 25000000};  // an app that advertises more
      const c = new FlightWatcherUploadsCard(); c.setConfig({}); c.hass = hass(true);
      for (let i = 0; i < 20 && !c._data; i++) await tick();
      c._q("[data-kind]").value = "pairings"; c._q("[data-month]").value = "2026-12";
      const try_ = async (size) => { c._q("[data-pdf]").files = [{name: "p.pdf", type: "application/pdf", size}]; const n = xhrs.length;
        await c._upload(); return {msg: c._msg, sent: xhrs.length - n}; };
      const big = await try_(20000000), edge = await try_(FW_UP_MAX + 1), ok = await try_(16000000);
      DATA = {files: [], seniority: null, version: "1.4.5", max_bytes: 1000000}; await c._load();  // a lower app figure wins
      const low = await try_(2000000);
      console.log(JSON.stringify({big, edge, ok, low, max: FW_UP_MAX, url: xhrs[0] && xhrs[0].url, fd: xhrs[0] && xhrs[0].fd}));
    """)
    assert r["max"] == 16 * 1024 * 1024 - 64 * 1024
    assert r["big"] == {"msg": {"ok": False, "text": "Too large: 19.1 MB. Home Assistant's app proxy takes a PDF of up to 15.9 MB."}, "sent": 0}
    assert r["edge"]["sent"] == 0 and r["edge"]["msg"]["text"].startswith("Too large: 15.9 MB.")
    assert r["ok"] == {"msg": {"ok": True, "text": "Saved 2026-12_pairings.pdf (15625 KB)."}, "sent": 1}
    assert r["url"] == "/api/hassio_ingress/tok123/api/upload" and r["fd"] == ["kind", "month", "pdf"]
    assert r["low"]["sent"] == 0 and r["low"]["msg"]["text"].endswith("up to 977 KB.")


def test_progress_and_result_lines_are_live_regions():
    """Review fix (WCAG 4.1.3 status messages): the result line is a polite status region and the progress line is
    live too, so a screen reader announces the upload's progress and its outcome; the progress moves in 10 % steps."""
    r = _node("""
      const c = new FlightWatcherUploadsCard(); c.setConfig({}); c.hass = hass(true);
      for (let i = 0; i < 20 && !c._data; i++) await tick();
      console.log(JSON.stringify({html: c.shadowRoot.innerHTML}));
    """)
    h = " ".join(r["html"].split())
    assert '<div class="msg" data-msg role="status" aria-live="polite" aria-atomic="true"></div>' in h
    assert '<span class="u" data-prog aria-live="polite"></span>' in h
    src = open(CARD, encoding="utf-8").read()
    assert "Math.floor(p / 10) * 10}%" in src
