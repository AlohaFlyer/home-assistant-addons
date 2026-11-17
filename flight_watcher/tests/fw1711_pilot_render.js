// 1.7.11: the pilot schedule card in Chromium (node Playwright) at 390 px with made-up replies, on the admin's card
// and on a pilot's copy. FW-0078: a pick list of 10 namesakes, each "Last, First · seat · base · #number" (escaped,
// wrapping, 44 px targets); a pilot's entry still sends its opaque pick id. FW-0076: "Nov 2026" and "Dec 2026" under
// the heading of a pilot's month (the shown one pressed and not tappable), a tap sends pilot/set with the same pilot
// and the month, "Loading Nov 2026..." while it waits, one publish for a double tap, light and dark, and a portal that
// refuses the month key (HOM 1.9.1) says the month choice needs a portal update.
// Usage: node <this> <admin card.js> <pilot copy.js> <james> [screenshot dir]
const [, , adminPath, pilotPath, pilot, shots] = process.argv;
const fs = require("fs");
const path = require("path");
const NOW = Date.parse("2026-11-17T20:00:00Z");  // 10:00 HST, Nov 17, 2026

async function run(b, cardPath, suffix, dark) {
  const p = await b.newPage({ viewport: { width: 390, height: 844 }, colorScheme: dark ? "dark" : "light" });
  await p.addInitScript((now) => { const real = Date.now; const off = now - real(); Date.now = () => real() + off; }, NOW);
  await p.setContent(`<!doctype html><html><head><style>body{margin:0;background:${dark ? "#111" : "#fafafa"};
    --primary-text-color:${dark ? "#e1e1e1" : "#212121"};--secondary-text-color:${dark ? "#9e9e9e" : "#727272"};
    --card-background-color:${dark ? "#1c1c1c" : "#fff"};--divider-color:${dark ? "#333" : "#e0e0e0"};
    --primary-color:#03a9f4;--text-primary-color:#fff}</style></head><body><script>
customElements.define("ha-card", class extends HTMLElement { constructor() { super(); this.attachShadow({ mode: "open" }).innerHTML = "<slot></slot>"; } });
window.sent = [];
window.refuse = null;
</script><script>${fs.readFileSync(cardPath, "utf-8")}</script></body></html>`);
  const out = await p.evaluate(({ suffix, dark }) => {
    const pre = suffix ? `flight_watcher_${suffix}` : "flight_watcher";
    const ENT = `sensor.${pre}_pilot_schedule`;
    const c = document.createElement(`flight-watcher-pilot-card${suffix ? "-" + suffix : ""}`);
    c.setConfig({ entity: ENT });
    document.body.appendChild(c);
    c.scrollIntoView = () => {};
    let n = 0;
    const hass = (attrs) => {
      n += 1;
      c.hass = { states: { [ENT]: { state: "x", last_updated: `2026-11-17T20:00:${String(n).padStart(2, "0")}+00:00`, attributes: attrs } },
                 themes: { darkMode: dark },
                 callService: (d, s, data) => { window.sent.push(data); return window.refuse ? Promise.reject(new Error(window.refuse)) : Promise.resolve(); } };
    };
    const R = () => c.shadowRoot;  // attached at the first hass
    const text = () => R().querySelector(".body").innerText;
    const r = {};
    // FW-0078: ten namesakes; one with no base; one name that is markup
    const firsts = ["Ann", "Bea", "Cal", "Dee", "Eve", "Fay", "Gus", "Hal", "Ida", "<b>Jo</b>"];
    const matches = firsts.map((f, i) => ({ ...(suffix ? { pick: (0xa1b2c3d4e5f0 + i).toString(16) } : {}), name: `Doe, ${f}`, pos: i % 2 ? "FO" : "CA",
                                            ...(i ? { base: "HNL" } : {}), emp: String(10001 + i) }));
    hass({ emp: "", name: "Doe", status: "10 pilots match 'Doe', pick one", at: "2026-11-17T20:00:00+00:00", month: "", matches });
    const pks = [...R().querySelectorAll(".pk")];
    r.pkCount = pks.length;
    r.pkLabels = pks.map((x) => x.innerText.replace(/\s+/g, " ").trim());
    r.pkMinH = Math.min(...pks.map((x) => x.getBoundingClientRect().height));
    r.pkMinW = Math.min(...pks.map((x) => x.getBoundingClientRect().width));
    r.pkMaxRight = Math.max(...pks.map((x) => x.getBoundingClientRect().right));
    r.markup = R().querySelectorAll(".pk b").length;
    r.wide1 = document.documentElement.scrollWidth;
    window.sent = [];
    pks[1].click();
    r.pickSent = window.sent.map((x) => x.payload);
    // FW-0076: the pilot's month (FLICA's default after the award: December), found by that pick on a pilot's copy
    window.sent = [];
    const shown = { emp: "10002", name: "Doe, Bea", status: "ok", month: "2026-12", updated: "Nov 4, 2026 10:00", fetched: "2026-11-17T19:59:00+00:00",
                    days: [["2026-12-01", "", ""], ["2026-12-02", "H9001", "LAX"], ["2026-12-03", "", "HNL"]],
                    items: [{ trip: "H9001", start: "2026-12-02", end: "2026-12-03", lay: "LAX" }], totals: {},
                    ...(suffix ? { ask: { pick: (0xa1b2c3d4e5f1).toString(16) } } : {}) };
    hass(shown);
    const mos = () => [...R().querySelectorAll(".mo")];
    r.heading = R().querySelector(".hd h3").innerText;
    r.mos = mos().map((x) => ({ t: x.innerText, pressed: x.getAttribute("aria-pressed"), disabled: x.disabled }));
    r.moMinH = Math.min(...mos().map((x) => x.getBoundingClientRect().height));
    r.moMinW = Math.min(...mos().map((x) => x.getBoundingClientRect().width));
    r.underHeading = (() => { const hd = R().querySelector(".hd"), g = R().querySelector(".mos"); return !!(hd && g && g.getBoundingClientRect().top >= hd.getBoundingClientRect().bottom - 1); })();
    const cs = getComputedStyle(mos()[1]), cp = getComputedStyle(mos()[0]);
    r.moColors = { on: [cs.color, cs.backgroundColor], off: [cp.color, cp.backgroundColor] };
    r.wide2 = document.documentElement.scrollWidth;
    mos()[1].click();  // the shown month: not tappable
    r.sentShown = window.sent.length;
    mos()[0].click();
    c._month("2026-11");  // the same tap heard again inside 2 s (another card, a double tap): one publish
    r.monthSent = window.sent.map((x) => [x.topic, x.payload]);
    r.loading = text();
    return r;
  }, { suffix, dark });
  if (shots) await p.screenshot({ path: path.join(shots, `fw1711_${suffix || "admin"}_${dark ? "dark" : "light"}.png`), fullPage: true });
  // a portal that refuses the month key (HOM 1.9.1's pinned shape)
  const ref = await p.evaluate(async ({ suffix }) => {
    const pre = suffix ? `flight_watcher_${suffix}` : "flight_watcher";
    const ENT = `sensor.${pre}_pilot_schedule`;
    const c = document.querySelector(`flight-watcher-pilot-card${suffix ? "-" + suffix : ""}`);
    window.refuse = "Not available in the portal: pilot/set: month is not allowed.";
    window.sent = [];
    const st = c._h.states[ENT];
    c.hass = { ...c._h, states: { [ENT]: { ...st, last_updated: "2026-11-17T20:01:00+00:00", attributes: { ...st.attributes, month: "2026-12", status: "cached" } } } };
    await new Promise((ok) => setTimeout(ok, 2100));  // past the 2 s guard
    c.shadowRoot.querySelector(".mo").click();
    await new Promise((ok) => setTimeout(ok, 50));
    return { sent: window.sent.length, text: c.shadowRoot.querySelector(".body").innerText };
  }, { suffix });
  await p.close();
  return { ...out, refused: ref };
}

(async () => {
  let chromium;
  try { ({ chromium } = require("playwright")); } catch (e) { console.log(JSON.stringify({ skip: "playwright missing" })); return; }
  const b = await chromium.launch();
  const res = {};
  res.admin = await run(b, adminPath, "", false);
  res.pilot = await run(b, pilotPath, pilot, false);
  res.pilotDark = await run(b, pilotPath, pilot, true);
  await b.close();
  console.log(JSON.stringify(res));
})().catch((e) => { console.error(e); process.exit(1); });
