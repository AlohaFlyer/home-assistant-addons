// 1.7.11 (FW-0079, FW-0080): the pilot card in Chromium (node Playwright) with the Watcher's own reply for a made-up
// December (tests/test_fw1711_totals.py builds it with pilot_price: synthetic pilots and pairings only). At 390 px and
// 1024 px, light and dark: the grid fits its box, the Crew column gives way to the crew list on a phone (and is back on
// a wide card), names stay text, the trip across the bid period's edge shows its December part, purple, with its title,
// and the totals match FLICA's (no red). Usage: node <this> <pilot card.js> <attributes.json> [screenshot dir or ""]
// [widths, default "390,1024"] [shot name tag]. 1.7.11 review: also 360, 375 and 820 px (a tablet in portrait), and each
// row's height by day (rowHd) for a one-day turn's row.
const [, , cardPath, attrsPath, shotDir, widthsArg, tag] = process.argv;
const fs = require("fs");

(async () => {
  let chromium;
  try { ({ chromium } = require("playwright")); } catch (e) { console.log(JSON.stringify({ skip: "playwright missing" })); return; }
  const attrs = JSON.parse(fs.readFileSync(attrsPath, "utf-8"));
  const ENT = "sensor.flight_watcher_pilot_schedule";
  const b = await chromium.launch();
  const out = {};
  const widths = String(widthsArg || "390,1024").split(",").map(Number).filter((x) => x > 0);
  for (const [w, h] of widths.map((x) => [x, x >= 700 ? 900 : 844])) {
    for (const dark of [false, true]) {
      const p = await b.newPage({ viewport: { width: w, height: h }, deviceScaleFactor: 2 });
      await p.route("**/*", (r) => r.fulfill({ status: 404, body: "" }));
      const bg = dark ? "#111111" : "#fafafa", card = dark ? "#1c1c1c" : "#ffffff", fg = dark ? "#e1e1e1" : "#212121";
      await p.setContent(`<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><style>
        html,body{margin:0;background:${bg};color:${fg};font-family:Roboto,Arial,sans-serif}
        body{padding:8px;--card-background-color:${card};--primary-text-color:${fg};--secondary-text-color:${dark ? "#9e9e9e" : "#727272"};--divider-color:${dark ? "#333333" : "#e0e0e0"};--primary-color:#03a9f4}
      </style></head><body><script>
customElements.define("ha-card", class extends HTMLElement { constructor() { super(); this.attachShadow({ mode: "open" }).innerHTML = "<style>:host{display:block;background:var(--card-background-color);border-radius:12px;color:var(--primary-text-color)}</style><slot></slot>"; } });
</script><script>${fs.readFileSync(cardPath, "utf-8")}</script></body></html>`);
      const r = await p.evaluate(({ ENT, attrs, dark }) => {
        const c = document.createElement("flight-watcher-pilot-card");
        c.setConfig({ entity: ENT });
        document.body.appendChild(c);
        c.scrollIntoView = () => {};
        c.hass = { themes: { darkMode: dark }, states: { [ENT]: { state: "10999", last_updated: "2026-11-17T16:00:00+00:00", attributes: attrs } }, callService: () => {} };
        const R = c.shadowRoot;
        const box = (el) => { if (!el) return null; const q = el.getBoundingClientRect(); return { l: q.left, r: q.right, w: q.width, h: q.height }; };
        const wrap = R.querySelector(".body .wrap"), tab = wrap.querySelector("table.cal"), crl = R.querySelector(".crl");
        const shown = (el) => !!el && getComputedStyle(el).display !== "none" && el.getBoundingClientRect().width > 0;
        const row = (d) => [...R.querySelectorAll(`.body tr[data-d="${d}"] td.t`)].map((td) => ({ t: td.textContent, cls: td.className, title: td.title }));
        const tot = R.querySelector(".body .frame > .tot");
        return {
          doc: document.documentElement.scrollWidth, win: innerWidth, wrap: box(wrap), table: box(tab),
          wrapScroll: wrap.scrollWidth, wrapClient: wrap.clientWidth,
          crewTh: shown(R.querySelector("table.cal th.crw")), crewTd: [...R.querySelectorAll("table.cal td.crew")].some(shown),
          crl: shown(crl), crlLines: crl ? [...crl.querySelectorAll(":scope > div")].map((x) => x.textContent) : [],
          crlTags: crl ? [...crl.querySelectorAll("*")].map((x) => x.tagName.toLowerCase()).filter((t, i, a) => a.indexOf(t) === i).sort() : [],
          crlNowrap: crl ? [...crl.querySelectorAll(".cp")].every((x) => getComputedStyle(x).whiteSpace === "nowrap") : null,
          crlRight: crl ? Math.max(...[...crl.querySelectorAll(".cp")].map((x) => x.getBoundingClientRect().right)) : 0,
          crewCell: [...R.querySelectorAll("table.cal td.crew")].map((x) => x.textContent).filter(Boolean),
          crewTags: [...R.querySelectorAll("table.cal td.crew *")].map((x) => x.tagName.toLowerCase()).filter((t, i, a) => a.indexOf(t) === i).sort(),
          dec1: row("2026-12-01"), dec5: row("2026-12-05"),
          splitColor: (() => { const td = R.querySelector(".body tr[data-d='2026-12-01'] td.t.split"); return td ? getComputedStyle(td).color : ""; })(),
          tot: tot ? tot.textContent.replace(/\s+/g, " ").trim() : "", totTitle: tot ? tot.title : "", totBad: tot ? tot.querySelectorAll(".bad").length : -1,
          rowH: [...R.querySelectorAll(".body tr[data-d]")].map((x) => Math.round(x.getBoundingClientRect().height * 100) / 100),
          rowHd: Object.fromEntries([...R.querySelectorAll(".body tr[data-d]")].map((x) => [x.dataset.d, Math.round(x.getBoundingClientRect().height * 100) / 100])),
          payR: Math.max(0, ...[...R.querySelectorAll(".body tr[data-d] td.tot1 .pay")].map((x) => x.getBoundingClientRect().right)),
          crlon: !!R.querySelector(".body .wrap.crlon"),
        };
      }, { ENT, attrs, dark });
      if (shotDir) await p.screenshot({ path: `${shotDir}/totals_pilot_${tag ? `${tag}_` : ""}${w}_${dark ? "dark" : "light"}.png`, fullPage: true });
      out[`${w}_${dark ? "dark" : "light"}`] = r;
      await p.close();
    }
  }
  await b.close();
  console.log(JSON.stringify(out));
})().catch((e) => { console.error(e); process.exit(1); });
