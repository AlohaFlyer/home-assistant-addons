// 1.6.2 (Release A item 10): the pilot's copy of the Recall / Over 75 card in Chromium (node Playwright) at 390 px with
// made-up data: no Hark hint on a pilot, the missing-data notes (seniority, line), day rows for a list not posted and
// an empty one, "came in ... HST", the seniority source, and the seniority box sending only a whole number 1..99999.
// Usage: node tests/release_a_recall_render.js <pilot card.js>. Prints one JSON line. Made-up names only.
const [, , cardPath] = process.argv;
const fs = require("fs");

function attrs(sen, src) {
  const v = (date, pairing, verdict, extra) => ({ id: `${date}|${pairing}|recall`, date, kind: "recall", pairing, seat: "FO",
    sen: 900, pilot: "Doe, Jane", verdict, why: ["went to #900"], refs: [], act: {}, ...(extra || {}) });
  return {
    open: 1, alert: 0, me: { sen, seat: "FO", o75_months: {} }, last: "2026-11-09", checked: "2026-11-10T20:00:00+00:00",
    received: "2026-11-09T03:30:00+00:00", hark_files: false, sen_source: src, missing_sen: 0, missing_line: 1,
    missing_line_old: 2, versions_from: "2026-11-10",
    days: [
      { date: "2026-11-09", file: "ok", verdicts: [
        v("2026-11-09", "H3601", "POSSIBLE", { missing: "line", why: ["went to #900, junior to you (#500)", "your line is not on file"] }),
        v("2026-11-09", "H3602", "POSSIBLE", { act: { status: "confirmed", narrative: "Made-up narrative." } })] },
      { date: "2026-11-08", file: "not posted", verdicts: [] },
      { date: "2026-11-07", file: "blank", verdicts: [] },
    ],
  };
}

(async () => {
  let chromium;
  try { ({ chromium } = require("playwright")); } catch (e) { console.log(JSON.stringify({ skip: "playwright missing" })); return; }
  const src = fs.readFileSync(cardPath, "utf-8");
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 390, height: 844 } });
  await p.setContent(`<!doctype html><html><body><script>
customElements.define("ha-card", class extends HTMLElement { constructor() { super(); this.attachShadow({ mode: "open" }).innerHTML = "<slot></slot>"; } });
window.sent = [];
</script><script>${src}</script></body></html>`);
  const run = async (sen, src) => p.evaluate(([a]) => {
    document.body.querySelectorAll("flight-watcher-recall-card-james").forEach((x) => x.remove());
    const c = document.createElement("flight-watcher-recall-card-james");
    c.setConfig({ entity: "sensor.flight_watcher_james_recall_o75" });
    c._m = "2026-11";
    document.body.appendChild(c);
    c.hass = { states: { "sensor.flight_watcher_james_recall_o75": { state: "1", last_updated: "2026-11-10T20:00:01+00:00", attributes: a },
                         "sensor.flight_watcher_james_state": { state: "idle", attributes: { role: "pilot" } } },
               callService: (d, s, data) => window.sent.push(data) };
    c.shadowRoot.querySelectorAll("details.day").forEach((d) => { d.open = true; });
    const text = c.shadowRoot.querySelector("ha-card").innerText;
    const box = c.shadowRoot.querySelector('[data-me="sen"]');
    const tries = {};
    for (const val of ["-5", "123456", "12.7", "abc", "", "1234"]) {
      window.sent = [];
      box.value = val;
      box.onchange();
      tries[val] = window.sent.map((x) => x.payload);
    }
    const nav = [...c.shadowRoot.querySelectorAll("[data-m]")].map((x) => [x.tagName, Math.round(x.getBoundingClientRect().height), Math.round(x.getBoundingClientRect().width)]);
    return { text, tries, attrs: { min: box.min, max: box.max, mode: box.inputMode }, wide: document.documentElement.scrollWidth,
             nav, paste: !!c.shadowRoot.querySelector("[data-paste]") };
  }, [attrs(sen, src)]);
  const out = { nosen: await run(null, ""), award: await run(512, "award 2026-11") };
  await b.close();
  console.log(JSON.stringify(out));
})().catch((e) => { console.error(e); process.exit(1); });
