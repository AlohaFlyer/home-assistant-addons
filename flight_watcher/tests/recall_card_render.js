// 1.4.6: renders www/flight-watcher-recall-card.js in Chromium (node Playwright) against a stub hass with made-up
// recall data, at 390 px: the RECALL ALERT bar (tab and alert mode), day folds (default and remembered), the Hark
// states and button, escaping, and no sideways scroll. Usage: node tests/recall_card_render.js <card.js> <shot dir>.
// Prints one JSON line; test_recall_card.py checks it. Made-up names only.
const fs = require("fs");
const path = require("path");

const [, , cardPath, outDir] = process.argv;
const BAD = "<img src=x onerror=window.pwned=1>";

function v(date, pairing, verdict, act, extra) {
  return { id: `${date}|${pairing}|recall`, date, kind: "recall", pairing, seat: "FO", sen: 900, pilot: "Doe, Jane",
    verdict, why: ["went to #900, junior to you (#500)", verdict === "NO" ? "you were on H1111" : "open and legal on your line as held at Nov 10 00:00 HST (version 11.004): rest 30:00 before (FAR 117.25(e) 10 h, PWA 10.E.1.a 11 h in domicile)"],
    refs: ["PWA 22.G.2.e, 22.E, 4.M (200%)", "FAR 117.25(e)"], act: act || {}, ...(extra || {}) };
}

function data() {
  const narr = "On 2026-11-10, Recall pairing H3601 was awarded to a FO with seniority #900, junior to me.";
  return {
    open: 5, alert: 3, me: { sen: 500, seat: "FO", o75: true }, last: "2026-11-10", checked: "2026-11-10T20:00:00+00:00",
    received: "2026-11-10T19:00:00+00:00", hark_files: true,
    days: [
      { date: "2026-11-10", file: "ok", verdicts: [
        v("2026-11-10", "H3601", "MISSED", { status: "approved", narrative: narr, approved_at: "2026-11-10T21:00:00+00:00" }, { pilot: BAD }),
        v("2026-11-10", "H3602", "POSSIBLE", { status: "new", narrative: narr }),
        v("2026-11-10", "H3603", "NO") ] },
      { date: "2026-11-09", file: "ok", verdicts: [v("2026-11-09", "H3604", "NO"), v("2026-11-09", "H3605", "NO")] },
      { date: "2026-11-08", file: "blank", verdicts: [] },
      { date: "2026-11-07", file: "not posted", verdicts: [] },
      { date: "2026-11-06", file: "ok", verdicts: [v("2026-11-06", "H3606", "MISSED", { status: "filing", narrative: narr,
        approved_at: "2026-11-06T18:00:00+00:00", requested_at: "2026-11-06T19:52:00+00:00", rid: "2026-11-06_H3606_recall", task_id: "T-42" })] },
      { date: "2026-11-05", file: "ok", verdicts: [v("2026-11-05", "H3607", "MISSED", { status: "blocked", narrative: narr,
        approved_at: "2026-11-05T18:00:00+00:00", requested_at: "2026-11-05T19:00:00+00:00", rid: "2026-11-05_H3607_recall",
        hark_reason: `hal.alpa.org asked for a login ${BAD}`, hark_at: "2026-11-05T20:30:00+00:00" })] },
      { date: "2026-11-04", file: "ok", verdicts: [v("2026-11-04", "H3608", "MISSED", { status: "filed", narrative: narr,
        ccr: "12345", filed_by: "hark", filed_at: "2026-11-05T01:15:00+00:00", rid: "2026-11-04_H3608_recall" })] },
    ],
  };
}

function page(src, mode, opts) {
  return `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{margin:0;padding:8px 16px;font-family:Roboto,sans-serif;background:#f4f4f4;color:#212121;
--primary-color:#03a9f4;--secondary-text-color:#727272;--divider-color:rgba(0,0,0,.12);--card-background-color:#fff;--primary-text-color:#212121}
</style></head><body>
<script>
${opts.noStorage ? `Object.defineProperty(window, "localStorage", { get() { throw new Error("blocked"); } });` : ""}
customElements.define("ha-card", class extends HTMLElement { constructor() { super(); this.attachShadow({ mode: "open" }).innerHTML =
  "<style>:host{display:block;background:var(--card-background-color,#fff);border-radius:12px;box-shadow:0 1px 3px rgba(0,0,0,.2)}</style><slot></slot>"; } });
window.sent = []; window.opened = [];
window.open = (u) => { window.opened.push(u); return null; };
</script>
<script>${src}</script>
<script>
const c = document.createElement("flight-watcher-recall-card"); c.setConfig({ mode: "${mode}" }); c._m = "2026-11"; document.body.appendChild(c);
const attrs = ${JSON.stringify(opts.data)};
c.hass = { states: { "sensor.flight_watcher_recall_o75": { state: String(attrs.open), last_updated: "2026-11-10T20:00:01+00:00", attributes: attrs } },
  callService: (d, s, x) => { window.sent.push({ d, s, topic: x.topic, payload: JSON.parse(x.payload) }); } };
</script></body></html>`;
}

(async () => {
  let chromium;
  try { ({ chromium } = require("playwright")); } catch (e) { console.log(JSON.stringify({ skip: "node Playwright not installed" })); return; }
  let browser;
  try { browser = await chromium.launch(); } catch (e) { console.log(JSON.stringify({ skip: `no Chromium: ${String(e.message).slice(0, 120)}` })); return; }
  const src = fs.readFileSync(cardPath, "utf8");
  fs.mkdirSync(outDir, { recursive: true });
  const res = { shots: [] };
  const pages = {};
  try {
    const ctx = await browser.newContext({ viewport: { width: 390, height: 900 } });
    await ctx.route("https://fw.test/**", async (route) => {
      const u = new URL(route.request().url());
      const p = pages[u.pathname];
      return p ? route.fulfill({ contentType: "text/html", body: p }) : route.fulfill({ status: 404, body: "" });
    });
    pages["/tab"] = page(src, "tab", { data: data() });
    pages["/alert"] = page(src, "alert", { data: data() });
    const quiet = data();
    quiet.days = quiet.days.filter((d) => d.date === "2026-11-09");
    pages["/quiet"] = page(src, "alert", { data: quiet });
    pages["/nostore"] = page(src, "tab", { data: data(), noStorage: true });
    const R = (pg, fn, arg) => pg.evaluate(fn, arg);
    const root = "document.querySelector('flight-watcher-recall-card').shadowRoot";
    const state = (pg) => R(pg, (root) => {
      const r = eval(root);
      const bar = r.querySelector(".bar");
      return {
        bar: bar ? { head: bar.querySelector(".bh").textContent, lines: [...bar.querySelectorAll("li")].map((l) => l.textContent.replace(/\s+/g, " ").trim()),
          jump: !!bar.querySelector("[data-go]"), first: r.querySelector("ha-card").firstElementChild === bar } : null,
        open: Object.fromEntries([...r.querySelectorAll("details.day")].map((d) => [d.dataset.day, d.open])),
        hark: [...r.querySelectorAll("button[data-hark]")].map((b) => b.dataset.hark),
        manual: [...r.querySelectorAll("button[data-file]")].map((b) => b.dataset.file),
        hk: [...r.querySelectorAll(".hk")].map((h) => h.textContent.replace(/\s+/g, " ").trim()),
        imgs: r.querySelectorAll("img").length, pwned: window.pwned === undefined ? null : window.pwned,
        store: (() => { try { return localStorage.getItem("flight_watcher_recall_fold"); } catch (e) { return "blocked"; } })(),
        fit: { doc: document.documentElement.scrollWidth, win: window.innerWidth, card: r.querySelector("ha-card").getBoundingClientRect().right,
          inner: r.querySelector("ha-card").scrollWidth - r.querySelector("ha-card").clientWidth },
      };
    }, root);
    const pg = await ctx.newPage();
    await pg.goto("https://fw.test/tab");
    res.tab = await state(pg);
    await pg.screenshot({ path: path.join(outDir, "recall_tab_390.png"), fullPage: true });
    res.shots.push("recall_tab_390.png");
    // open a quiet day and fold a miss day: remembered across a reload; then back to default forgets the entry
    await R(pg, (root) => { const r = eval(root); r.querySelector('details.day[data-day="2026-11-09"] > summary').click(); r.querySelector('details.day[data-day="2026-11-10"] > summary').click(); }, root);
    await pg.waitForTimeout(100);
    res.after_toggle = (await state(pg)).store;
    await pg.reload();
    res.reloaded = (await state(pg)).open;
    // the Hark button sends file_request for that row only
    await R(pg, (root) => eval(root).querySelector('button[data-hark="2026-11-05|H3607|recall"]').click(), root);
    res.sent = await R(pg, () => window.sent);
    res.hark_btn = await R(pg, (root) => eval(root).querySelector('button[data-hark="2026-11-05|H3607|recall"]').textContent, root);
    // the manual fallback still opens hal.alpa.org
    await R(pg, (root) => eval(root).querySelector('button[data-file="2026-11-06|H3606|recall"]').click(), root);
    res.opened = await R(pg, () => window.opened);
    // a tap on a RECALL ALERT line opens that day
    await R(pg, (root) => { const r = eval(root); r.querySelector('details.day[data-day="2026-11-10"]').open = false; }, root);
    await R(pg, (root) => eval(root).querySelector('.bar li[data-goday="2026-11-10"]').click(), root);
    await pg.waitForTimeout(50);
    res.goday = (await state(pg)).open["2026-11-10"];
    const al = await ctx.newPage();
    await al.goto("https://fw.test/alert");
    res.alert = await state(al);
    await al.screenshot({ path: path.join(outDir, "recall_alert_390.png"), fullPage: true });
    res.shots.push("recall_alert_390.png");
    const qt = await ctx.newPage();
    await qt.goto("https://fw.test/quiet");
    res.quiet = await R(qt, (root) => eval(root).innerHTML, root);
    const ns = await ctx.newPage();
    await ns.goto("https://fw.test/nostore");
    const nsr = await state(ns);
    await R(ns, (root) => eval(root).querySelector('details.day[data-day="2026-11-09"] > summary').click(), root);
    await ns.waitForTimeout(50);
    res.nostore = { open: nsr.open, bar: nsr.bar && nsr.bar.lines.length, after: (await state(ns)).open["2026-11-09"] };
  } finally {
    await browser.close();
  }
  console.log(JSON.stringify(res));
})().catch((e) => { console.error(e && e.stack ? e.stack : e); process.exit(1); });
