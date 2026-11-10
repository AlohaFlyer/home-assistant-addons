// 1.7.0 (Release C): renders the tickets card in Chromium (node Playwright) twice against a stubbed hass:
// - the pilot portal's copy (FW_PORTAL on, pilot "demo"), served with the HOM portal's exact Content-Security-Policy
//   header (no inline script: the page's own scripts come from the same origin), files three made-up 1080 x 2400
//   screenshots, then acts on the made-up tickets of the list file (verify, a refused Still broken, edit, delete), an
//   over-size text and the Watcher's answers on the sensor;
// - the Home Assistant copy (Ryan's, FW_PORTAL off) without a CSP: the 1.6.x path (blob: URL, whole photos, 10 photos,
//   the Claude Code button, "Sent" on act).
// Usage: node tests/tickets_card_render.js <portal copy.js> <HA copy.js> <dir with shot1.png..shot3.png> <out dir>.
// Prints one JSON line; test_release_c_card.py checks it. Made-up data only.
const fs = require("fs");
const path = require("path");

const [, , portalPath, haPath, shotDir, outDir] = process.argv;
const CSP = "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; " +
  "base-uri 'none'; form-action 'self'; frame-ancestors 'none'";
const ZEROS = "0".repeat(32);

function listing(prefixTickets) {
  return {
    open: 2, total: 3, tickets: [
      { id: "FW-0100", kind: "bug", title: "Pot card blank", status: "fixed", reporter: "demo", created_at: "2026-11-09", updated_at: "2026-11-10",
        version_fixed: "1.7.0", has_image: false, image_count: 0, narrative: "The pot card showed no rows.", history_count: 2, page: "Watcher", editable: false },
      { id: "FW-0099", kind: "bug", title: "Schedule month arrows", status: "new", reporter: "demo", created_at: "2026-11-08", updated_at: "2026-11-08",
        version_fixed: "", has_image: false, image_count: 0, narrative: "The arrows do nothing.", steps: "Schedule tab", expected: "Next month",
        history_count: 0, page: "Schedule", editable: true },
      { id: "FW-0098", kind: "feature", title: "Reserve days", status: "closed", reporter: "demo", created_at: "2026-11-01", updated_at: "2026-11-02",
        version_fixed: "1.6.2", has_image: false, image_count: 0, narrative: "Show reserve days.", history_count: 3, page: "Schedule", editable: false },
    ].filter((t) => prefixTickets || t),
  };
}

function sensor(prefix, extra) {
  const L = listing(true);
  return {
    state: "2", last_updated: "t1",
    attributes: { open: 2, total: 3, rows: "open", file_key: ZEROS, rev: "abc123abc123", last: {},
      tickets: L.tickets.filter((t) => t.status !== "closed").map((t) => ({ id: t.id, kind: t.kind, title: t.title, status: t.status,
        reporter: t.reporter, created_at: t.created_at, version_fixed: t.version_fixed, image_count: 0, editable: t.editable })), ...extra },
  };
}

// the page's own script (same origin, so the CSP's script-src 'self' lets it run): ha-card, the stub hass
function harness(tag, prefix, extra) {
  return `
customElements.define("ha-card", class extends HTMLElement { constructor() { super(); this.attachShadow({ mode: "open" }).innerHTML =
  "<style>:host{display:block;background:#fff;border-radius:12px}</style><slot></slot>"; } });
window.pubs = []; window.REJECT = ""; window.blobs = 0; window.csp = [];
document.addEventListener("securitypolicyviolation", (e) => window.csp.push(e.violatedDirective + " " + String(e.blockedURI).slice(0, 20)));
const ou = URL.createObjectURL.bind(URL);
URL.createObjectURL = (b) => { window.blobs += 1; return ou(b); };
window.H = { user: { is_admin: false }, states: {
  "sensor.${prefix}_tickets": ${JSON.stringify(sensor(prefix, extra))},
  "sensor.${prefix}_state": { state: "idle", attributes: { version: "1.7.0" } } },
  callService: async (d, s, data) => {
    if (window.REJECT) throw new Error(window.REJECT);
    window.pubs.push({ d, s, topic: data.topic, payload: data.payload });
  } };
window.setHass = (attrs) => {
  const st = window.H.states["sensor.${prefix}_tickets"];
  window.H = { ...window.H, states: { ...window.H.states, "sensor.${prefix}_tickets": { ...st, last_updated: String(Date.now()), attributes: { ...st.attributes, ...attrs } } } };
  document.querySelector("${tag}").hass = window.H;
};
window.addEventListener("load", () => {
  const c = document.createElement("${tag}"); c.setConfig({}); document.body.appendChild(c); c.hass = window.H; window.card = c;
});`;
}

function page(withCsp) {
  return `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{margin:0;padding:8px 16px;font-family:sans-serif;background:#f4f4f4;--primary-color:#03a9f4;--divider-color:#ddd}</style>
<script src="/harness.js"></script><script src="/card.js"></script></head><body></body></html>`;
}

(async () => {
  let chromium;
  try { ({ chromium } = require("playwright")); } catch (e) { console.log(JSON.stringify({ skip: "node Playwright not installed" })); return; }
  let browser;
  try { browser = await chromium.launch(); } catch (e) { console.log(JSON.stringify({ skip: `no Chromium: ${String(e.message).slice(0, 120)}` })); return; }
  // test only: the retry wait of a chunk turned away for too many commands a minute is 50 ms here, not 10 s
  const portalSrc = fs.readFileSync(portalPath, "utf8").replace("const FW_TICKET_RETRY_MS = 10000;", "const FW_TICKET_RETRY_MS = 50;");
  const haSrc = fs.readFileSync(haPath, "utf8");
  const shots = ["shot1.png", "shot2.png", "shot3.png"].map((n) => path.join(shotDir, n));
  fs.mkdirSync(outDir, { recursive: true });
  const res = { portal: {}, ha: {}, tiny: {} };
  try {
    const serve = async (ctx, tag, prefix, src, withCsp, extra, folder) => {
      await ctx.route("https://fw.test/**", async (route) => {
        const u = new URL(route.request().url());
        const headers = withCsp ? { "Content-Security-Policy": CSP } : {};
        if (u.pathname === "/") return route.fulfill({ contentType: "text/html", headers, body: page(withCsp) });
        if (u.pathname === "/harness.js") return route.fulfill({ contentType: "text/javascript", headers, body: harness(tag, prefix, extra) });
        if (u.pathname === "/card.js") return route.fulfill({ contentType: "text/javascript", headers, body: src });
        if (u.pathname === `/local/flight-watcher/${folder}tickets_${ZEROS}.json`) {
          return route.fulfill({ contentType: "application/json", headers, body: JSON.stringify(listing(true)) });
        }
        return route.fulfill({ status: 404, headers, body: "" });
      });
    };
    const sr = (pg, tag, js) => pg.evaluate(`(() => { const r = document.querySelector("${tag}").shadowRoot; ${js} })()`);

    // ------------------------------------------------------------------ the portal copy, under the portal's CSP
    {
      const tag = "flight-watcher-tickets-card-demo", prefix = "flight_watcher_demo";
      const ctx = await browser.newContext({ viewport: { width: 390, height: 844 } });
      const errors = [];
      await serve(ctx, tag, prefix, portalSrc, true, { answers: [], limits: { photos: 3, new_per_day: 10, open: 25, ticket_bytes: 1572864 } }, "demo/");
      const pg = await ctx.newPage();
      pg.on("console", (m) => { if (m.type() === "error") errors.push(m.text().slice(0, 160)); });
      pg.on("pageerror", (e) => errors.push(String(e.message).slice(0, 160)));
      await pg.goto("https://fw.test/");
      await pg.waitForFunction(() => window.card && window.card.shadowRoot && window.card.shadowRoot.querySelectorAll(".t").length >= 2);
      const P = res.portal;
      P.cc = await sr(pg, tag, "return r.querySelectorAll('[data-cc]').length;");
      P.rows = await sr(pg, tag, "return Array.from(r.querySelectorAll('.th b'), (b) => b.textContent);");
      await pg.locator(`${tag} [data-new]`).first().click();
      P.pages = await sr(pg, tag, "return Array.from(r.querySelectorAll('[data-f=page] option'), (o) => o.textContent);");
      P.photo_label = await sr(pg, tag, "return r.querySelector('[data-photos] .lbl').textContent;");
      await pg.locator(`${tag} [data-f=title]`).fill("Card blank after scan");
      await pg.locator(`${tag} [data-f=narrative]`).fill("The pot card shows nothing after Scan FLICA now.");
      await pg.locator(`${tag} [data-img]`).setInputFiles(shots);
      await pg.waitForFunction(() => window.card._prep === null && window.card._imgs.length === 3, null, { timeout: 30000 });
      P.thumbs = await sr(pg, tag, "return r.querySelectorAll('.thumbs img').length;");
      P.thumb_src = await sr(pg, tag, "return Array.from(r.querySelectorAll('.thumbs img'), (i) => i.src.slice(0, 23));");
      P.url_lengths = await pg.evaluate(() => window.card._imgs.map((x) => x.url.length));
      await pg.screenshot({ path: path.join(outDir, "tickets_portal_form_390.png"), fullPage: true });
      // the first chunk of photo 2 is turned away once for too many commands a minute: it waits and goes again
      await pg.evaluate(() => {
        const orig = window.H.callService; let n = 0;
        window.H.callService = async (d, s, data) => { const p = JSON.parse(data.payload);
          if (p.i === 2 && p.part === 1 && !n++) throw new Error("Too many commands just now. Wait a minute."); return orig(d, s, data); };
        window.card.hass = { ...window.H };
      });
      await pg.locator(`${tag} [data-send]`).click();
      await pg.waitForFunction(() => window.card._send && window.card._send.done, null, { timeout: 30000 });
      P.pubs = await pg.evaluate(() => window.pubs.map((p) => ({ topic: p.topic, payload: p.payload })));
      P.status_sent = await sr(pg, tag, "return r.querySelector('[data-status]').textContent;");
      const cid = await pg.evaluate(() => window.card._send.cid);
      // the Watcher's answers on the sensor
      await pg.evaluate((cid) => window.setHass({ answers: [
        { ref: cid, id: "", action: "image", i: 2, ok: false, error: "photo is not a JPEG or PNG", at: "t" },
        { ref: cid, id: "FW-0101", action: "new", ok: true, error: "", at: "t" }] }), cid);
      P.status_answers = await sr(pg, tag, "return [r.querySelector('[data-status]').textContent, r.querySelector('[data-status]').className];");
      // act: Verified, close on the fixed ticket, with a rid; the Watcher's answer on its row
      await sr(pg, tag, "r.querySelector('details.done').open = true; return 1;");  // FW-0100 is fixed: in the completed fold
      await pg.waitForFunction(() => window.card._doneOpen === true);
      await sr(pg, tag, "r.querySelector('[data-t=\"FW-0100\"]').click(); return 1;");
      const before = (await pg.evaluate(() => window.pubs.length));
      await pg.locator(`${tag} button[data-a=verify]`).click();
      await pg.waitForFunction((n) => window.pubs.length > n, before);
      P.verify = await pg.evaluate(() => window.pubs[window.pubs.length - 1]);
      P.verify_row = await sr(pg, tag, "return r.querySelector('[data-rowmsg=\"FW-0100\"]').textContent;");
      const rid = JSON.parse(P.verify.payload).rid;
      await pg.evaluate((rid) => window.setHass({ answers: [{ ref: rid, id: "FW-0100", action: "act", ok: true, error: "", at: "t" }] }), rid);
      P.verify_done = await sr(pg, tag, "return r.querySelector('[data-rowmsg=\"FW-0100\"]').textContent;");
      // a refused send: the row says so, the button never says Sent
      await pg.evaluate(() => { window.REJECT = "Not available here: test refusal"; });
      await pg.locator(`${tag} button[data-a=reopen]`).first().click();
      await pg.waitForFunction(() => { const e = window.card.shadowRoot.querySelector('[data-rowmsg="FW-0100"]'); return e && e.textContent.startsWith("Didn't send"); });
      P.reject = await sr(pg, tag, "const b = r.querySelector('button[data-a=reopen]'); return [r.querySelector('[data-rowmsg=\"FW-0100\"]').textContent, b.textContent];");
      await pg.evaluate(() => { window.REJECT = ""; });
      // an over-size text is not sent
      const n1 = await pg.evaluate(() => window.pubs.length);
      await sr(pg, tag, "r.querySelector('[data-t=\"FW-0100\"]').click(); return 1;");  // close the row
      await pg.locator(`${tag} [data-new]`).first().click();
      await pg.locator(`${tag} [data-f=title]`).fill("Quotes");
      await pg.locator(`${tag} [data-f=narrative]`).fill('"'.repeat(10000));
      await pg.locator(`${tag} [data-f=steps]`).fill('"'.repeat(5000));
      await pg.locator(`${tag} [data-f=expected]`).fill('"'.repeat(5000));
      await pg.locator(`${tag} [data-send]`).click();
      P.too_big = await sr(pg, tag, "return r.querySelector('[data-msg]').textContent;");
      P.too_big_sent = (await pg.evaluate(() => window.pubs.length)) - n1;
      await pg.locator(`${tag} [data-cancel]`).click();
      // edit and delete the editable ticket, each with a rid
      await sr(pg, tag, "r.querySelector('[data-t=\"FW-0099\"]').click(); return 1;");
      await pg.locator(`${tag} [data-edit="FW-0099"]`).click();
      await pg.locator(`${tag} [data-editform] [data-f=narrative]`).fill("The arrows do nothing on the portal.");
      await pg.locator(`${tag} [data-editform] [data-save]`).click();
      await pg.waitForFunction(() => window.pubs.some((p) => p.topic.endsWith("/ticket/edit")));
      await pg.locator(`${tag} [data-del="FW-0099"]`).click();
      await pg.locator(`${tag} dialog button[value=delete]`).click();
      await pg.waitForFunction(() => window.pubs.some((p) => p.topic.endsWith("/ticket/delete")));
      P.edit = await pg.evaluate(() => window.pubs.find((p) => p.topic.endsWith("/ticket/edit")).payload);
      P.del = await pg.evaluate(() => window.pubs.find((p) => p.topic.endsWith("/ticket/delete")).payload);
      P.blobs = await pg.evaluate(() => window.blobs);
      P.csp = await pg.evaluate(() => window.csp);
      P.errors = errors;
      P.fit = await pg.evaluate(() => ({ doc: document.documentElement.scrollWidth, win: window.innerWidth }));
      await pg.screenshot({ path: path.join(outDir, "tickets_portal_390.png"), fullPage: true });
      await ctx.close();
    }

    // ------------------------------------------------------------------ a photo too detailed for a tiny budget
    {
      const tag = "flight-watcher-tickets-card-demo", prefix = "flight_watcher_demo";
      const ctx = await browser.newContext({ viewport: { width: 390, height: 844 } });
      const tiny = portalSrc.replace("const FW_TICKET_PORTAL_URL = 360000;", "const FW_TICKET_PORTAL_URL = 3000;");
      await serve(ctx, tag, prefix, tiny, true, { answers: [] }, "demo/");
      const pg = await ctx.newPage();
      await pg.goto("https://fw.test/");
      await pg.waitForFunction(() => window.card && window.card.shadowRoot && window.card.shadowRoot.querySelector("[data-new]"));
      await pg.locator(`${tag} [data-new]`).first().click();
      await pg.locator(`${tag} [data-img]`).setInputFiles([shots[0]]);
      await pg.waitForFunction(() => window.card._prep === null && window.card._note, null, { timeout: 30000 });
      res.tiny = { note: await pg.evaluate(() => window.card._note), imgs: await pg.evaluate(() => window.card._imgs.length) };
      await ctx.close();
    }

    // ------------------------------------------------------------------ the Home Assistant copy (Ryan's), no CSP
    {
      const tag = "flight-watcher-tickets-card", prefix = "flight_watcher";
      const ctx = await browser.newContext({ viewport: { width: 390, height: 844 } });
      await serve(ctx, tag, prefix, haSrc, false, {}, "");
      const pg = await ctx.newPage();
      await pg.goto("https://fw.test/");
      await pg.waitForFunction(() => window.card && window.card.shadowRoot && window.card.shadowRoot.querySelectorAll(".t").length >= 2);
      const A = res.ha;
      A.cc = await sr(pg, tag, "return r.querySelectorAll('[data-cc]').length;");
      await pg.locator(`${tag} [data-new]`).first().click();
      A.pages = await sr(pg, tag, "return Array.from(r.querySelectorAll('[data-f=page] option'), (o) => o.textContent);");
      A.photo_label = await sr(pg, tag, "return r.querySelector('[data-photos] .lbl').textContent;");
      await pg.locator(`${tag} [data-f=title]`).fill("Card blank");
      await pg.locator(`${tag} [data-f=narrative]`).fill("Nothing after a scan.");
      await pg.locator(`${tag} [data-img]`).setInputFiles(shots.slice(0, 2));
      await pg.waitForFunction(() => window.card._prep === null && window.card._imgs.length === 2, null, { timeout: 30000 });
      await pg.locator(`${tag} [data-send]`).click();
      await pg.waitForFunction(() => window.card._send && window.card._send.done, null, { timeout: 30000 });
      A.pubs = await pg.evaluate(() => window.pubs.map((p) => ({ topic: p.topic, keys: Object.keys(JSON.parse(p.payload)).sort(),
        image: (JSON.parse(p.payload).image || "").slice(0, 23), len: p.payload.length })));
      A.status = await sr(pg, tag, "return r.querySelector('[data-status]').textContent;");
      await sr(pg, tag, "r.querySelector('details.done').open = true; return 1;");
      await pg.waitForFunction(() => window.card._doneOpen === true);
      await sr(pg, tag, "r.querySelector('[data-t=\"FW-0100\"]').click(); return 1;");
      await pg.locator(`${tag} button[data-a=verify]`).click();
      A.verify = await pg.evaluate(() => window.pubs[window.pubs.length - 1].payload);
      A.verify_button = await sr(pg, tag, "return r.querySelector('button[data-a=verify]').textContent;");
      A.rowmsg = await sr(pg, tag, "return r.querySelectorAll('[data-rowmsg]').length;");
      A.blobs = await pg.evaluate(() => window.blobs);
      await ctx.close();
    }
  } finally {
    await browser.close();
  }
  console.log(JSON.stringify(res));
})().catch((e) => { console.error(e && e.stack ? e.stack : e); process.exit(1); });
