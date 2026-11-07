// 1.4.5: renders www/flight-watcher-uploads-card.js in Chromium (node Playwright) against a stubbed hass.callWS and
// stubbed ingress answers (page.route), uploads a made-up PDF and measures the card at 390 px and 1100 px.
// Usage: node tests/uploads_card_render.js <card.js> <screenshot dir>. Prints one JSON line; test_uploads_card.py
// checks it. Made-up data only.
const fs = require("fs");
const path = require("path");

const [, , cardPath, outDir] = process.argv;
const SESSION = "f".repeat(128);
const BAD = "<img src=x onerror=window.pwned=1>";

function initialData() {
  return {
    version: "1.4.5", max_bytes: 25000000,
    files: [
      { name: "2026-11_award.pdf", kind: "award", month: "2026-11", day: "", size: 812345, uploaded_at: "2026-10-18T08:12:00-10:00", has_text: true },
      { name: "2026-11_pairings.pdf", kind: "pairings", month: "2026-11", day: "", size: 3456789, uploaded_at: "2026-10-18T08:15:00-10:00", has_text: true },
      { name: "seniority_2026-11-06.pdf", kind: "seniority", month: "", day: "2026-11-06", size: 456789, uploaded_at: "2026-11-06T09:30:00-10:00", has_text: true },
      { name: `${BAD}.pdf`, kind: "other", month: "", day: "", size: 2048, uploaded_at: "2026-11-01T07:00:00-10:00", has_text: false },
    ],
    // FW-0057: a pairings package the crew index still needs, and a month that is not one (left out)
    wanted: [{ kind: "pairings", month: "2026-10", why: "previous" }, { kind: "pairings", month: BAD, why: BAD }],
    seniority: { pilots: 12, list_date: "2026-03-01", uploaded_at: "2026-11-06T09:30:00-10:00", source: "list", file: "seniority_2026-11-06.pdf",
      as_of: "2026-03-01", newest_doh: "2019-08-05", rejects: 0, carried: 0, base: null },
  };
}

function page(src, admin) {
  return `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{margin:0;padding:8px 16px;font-family:Roboto,sans-serif;background:#f4f4f4;color:#212121;
--primary-color:#03a9f4;--secondary-text-color:#727272;--divider-color:rgba(0,0,0,.12);--card-background-color:#fff;--primary-text-color:#212121}
</style></head><body>
<script>
// ha-card as Home Assistant draws it: a block with the card background, rounded corners and a shadow
customElements.define("ha-card", class extends HTMLElement { constructor() { super(); this.attachShadow({ mode: "open" }).innerHTML =
  "<style>:host{display:block;background:var(--card-background-color,#fff);border-radius:12px;box-shadow:0 1px 3px rgba(0,0,0,.2)}</style><slot></slot>"; } });
window.ws = [];</script>
<script>${src}</script>
<script>
const c = document.createElement("flight-watcher-uploads-card"); c.setConfig({}); document.body.appendChild(c);
c.hass = { user: { is_admin: ${admin ? "true" : "false"} }, callWS: async (m) => {
  window.ws.push(m.endpoint);
  if (m.endpoint.endsWith("/info")) return { ingress_url: "/api/hassio_ingress/tok123/", state: "started", ingress: true };
  if (m.endpoint === "/ingress/session") return { session: "${SESSION}" };
  return {};
} };
</script></body></html>`;
}

(async () => {
  let chromium;
  try { ({ chromium } = require("playwright")); } catch (e) { console.log(JSON.stringify({ skip: "node Playwright not installed" })); return; }
  let browser;
  try { browser = await chromium.launch(); } catch (e) { console.log(JSON.stringify({ skip: `no Chromium: ${String(e.message).slice(0, 120)}` })); return; }
  const src = fs.readFileSync(cardPath, "utf8");
  fs.mkdirSync(outDir, { recursive: true });
  const res = { fit: {}, shots: [], gets: [] };
  let data = initialData(), posts = [], ingressHits = 0;
  try {
    const ctx = await browser.newContext({ viewport: { width: 390, height: 900 } });
    await ctx.route("https://fw.test/**", async (route) => {
      const req = route.request(), u = new URL(req.url());
      if (u.pathname === "/" || u.pathname === "/user") return route.fulfill({ contentType: "text/html", body: page(src, u.pathname === "/") });
      if (u.pathname.startsWith("/api/hassio_ingress/")) ingressHits += 1;
      const h = await req.allHeaders();
      if (u.pathname === "/api/hassio_ingress/tok123/api/uploads" && req.method() === "GET") {
        res.gets.push(h.cookie || "");
        return route.fulfill({ contentType: "application/json", body: JSON.stringify(data) });
      }
      if (u.pathname === "/api/hassio_ingress/tok123/api/upload" && req.method() === "POST") {
        posts.push({ cookie: h.cookie || "", body: (req.postDataBuffer() || Buffer.alloc(0)).toString("latin1") });
        data.files.unshift({ name: "2026-12_award.pdf", kind: "award", month: "2026-12", day: "", size: 1024, uploaded_at: "2026-11-20T09:31:00-10:00", has_text: true });
        data.seniority = { pilots: 42, list_date: "", uploaded_at: "2026-11-20T09:31:00-10:00", source: "award 2026-12", file: "2026-12_award.pdf",
          as_of: "2026-12-01", newest_doh: "2019-08-05", rejects: 0, carried: 12, base: { source: "list", as_of: "2026-03-01", file: "seniority_2026-11-06.pdf" } };
        return route.fulfill({ contentType: "application/json", body: JSON.stringify({ ok: true, file: "2026-12_award.pdf",
          message: "Saved 2026-12_award.pdf (1 KB). Dates of hire: 30 pilots read from its seniority section; 42 pilots on file now (12 more kept from the seniority list of 2026-03-01)." }) });
      }
      return route.fulfill({ status: 404, body: "" });
    });
    const pg = await ctx.newPage();
    await pg.goto("https://fw.test/");
    const card = pg.locator("flight-watcher-uploads-card");
    const rows = () => pg.evaluate(() => document.querySelector("flight-watcher-uploads-card").shadowRoot.querySelectorAll(".f").length);
    await pg.waitForFunction(() => document.querySelector("flight-watcher-uploads-card").shadowRoot.querySelectorAll(".f").length > 0);
    res.rows_before = await rows();
    res.wanted = await pg.evaluate(() => Array.from(document.querySelector("flight-watcher-uploads-card").shadowRoot.querySelectorAll(".w"), (x) => x.textContent));
    res.month = await card.locator("[data-month]").inputValue();
    const h = new Date(Date.now() - 10 * 3600e3), m = h.getUTCMonth() + 1;
    res.expect_month = m === 12 ? `${h.getUTCFullYear() + 1}-01` : `${h.getUTCFullYear()}-${String(m + 1).padStart(2, "0")}`;
    res.kinds = await card.locator("[data-kind] option").evaluateAll((os) => os.map((o) => o.value));
    const hid = () => pg.evaluate(() => { const r = document.querySelector("flight-watcher-uploads-card").shadowRoot;
      return { month_hidden: r.querySelector("[data-ml]").hidden, date_hidden: r.querySelector("[data-dl]").hidden }; });
    await card.locator("[data-kind]").selectOption("seniority");
    res.sen_toggle = await hid();
    await card.locator("[data-kind]").selectOption("award");
    res.award_toggle = await hid();
    // a file that is not a PDF is refused in the card, before any request
    await card.locator("[data-pdf]").setInputFiles({ name: "notes.txt", mimeType: "text/plain", buffer: Buffer.from("hello") });
    await card.locator("[data-up]").click();
    const msg = () => pg.evaluate(() => { const s = document.querySelector("flight-watcher-uploads-card").shadowRoot.querySelector("[data-msg] span");
      return s ? { text: s.textContent, cls: s.className } : { text: "", cls: "" }; });
    const r0 = await msg();
    await card.locator("[data-month]").fill("2026-12");
    await card.locator("[data-pdf]").setInputFiles({ name: "award.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4 synthetic\n" + "x".repeat(1000)) });
    await card.locator("[data-up]").click();
    await pg.waitForFunction(() => { const s = document.querySelector("flight-watcher-uploads-card").shadowRoot.querySelector("[data-msg] span");
      return s && s.textContent.startsWith("Saved"); });
    await pg.waitForFunction(() => document.querySelector("flight-watcher-uploads-card").shadowRoot.querySelectorAll(".f").length === 5);
    const r1 = await msg();
    res.msg = r1.text; res.msg_class = r1.cls;
    // review fix (WCAG 4.1.3): the outcome is in a status region a screen reader announces, the progress line is live
    res.status = (await card.getByRole("status").textContent()).trim();
    res.live = await pg.evaluate(() => { const r = document.querySelector("flight-watcher-uploads-card").shadowRoot;
      const m = r.querySelector("[data-msg]"), p = r.querySelector("[data-prog]");
      return { msg: [m.getAttribute("role"), m.getAttribute("aria-live")], prog: p.getAttribute("aria-live") }; });
    res.aria = await card.ariaSnapshot();
    res.refused = { msg: r0.text, class: r0.cls, posts: posts.length };
    res.post = posts[0] || {};
    res.rows_after = await rows();
    res.ws = await pg.evaluate(() => window.ws);
    res.pwned = await pg.evaluate(() => (window.pwned === undefined ? null : window.pwned));
    res.imgs = await pg.evaluate(() => document.querySelector("flight-watcher-uploads-card").shadowRoot.querySelectorAll("img").length);
    const fit = (w) => pg.evaluate((w) => {
      const r = document.querySelector("flight-watcher-uploads-card").shadowRoot, c = r.querySelector("ha-card");
      return { doc: document.documentElement.scrollWidth, win: window.innerWidth, card: c.getBoundingClientRect().right,
        inner: c.scrollWidth - c.clientWidth, w };
    }, w);
    res.fit["390"] = await fit(390);
    await pg.screenshot({ path: path.join(outDir, "uploads_390.png"), fullPage: true });
    res.shots.push("uploads_390.png");
    await pg.setViewportSize({ width: 1100, height: 900 });
    res.fit["1100"] = await fit(1100);
    await pg.screenshot({ path: path.join(outDir, "uploads_1100.png"), fullPage: true });
    res.shots.push("uploads_1100.png");
    // a user who is not an admin: a note, no supervisor call, no ingress request
    const before = ingressHits;
    const up = await ctx.newPage();
    await up.setViewportSize({ width: 390, height: 400 });
    await up.goto("https://fw.test/user");
    await up.waitForTimeout(300);
    res.user = { ws: (await up.evaluate(() => window.ws)).length, ingress: ingressHits - before,
      text: (await up.evaluate(() => document.querySelector("flight-watcher-uploads-card").shadowRoot.querySelector("ha-card").textContent)).trim() };
    await up.screenshot({ path: path.join(outDir, "uploads_user_390.png") });
    res.shots.push("uploads_user_390.png");
  } finally {
    await browser.close();
  }
  console.log(JSON.stringify(res));
})().catch((e) => { console.error(e && e.stack ? e.stack : e); process.exit(1); });
