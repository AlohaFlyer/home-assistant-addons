// 1.6.2 (Release A item 11): a pilot's copy of the pilot schedule card in Chromium (node Playwright) at 390 px with
// made-up replies: the loading header names the pilot asked for (never the sensor's previous one), a no-match reply
// shows its status line with its HST time, a pick list shows name and seat only and sends the opaque pick id, and the
// loading line gives up 2 minutes after the Watcher's next check with a reason. Usage: node <this> <pilot card.js>.
const [, , cardPath] = process.argv;
const fs = require("fs");

(async () => {
  let chromium;
  try { ({ chromium } = require("playwright")); } catch (e) { console.log(JSON.stringify({ skip: "playwright missing" })); return; }
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 390, height: 844 } });
  await p.setContent(`<!doctype html><html><body><script>
customElements.define("ha-card", class extends HTMLElement { constructor() { super(); this.attachShadow({ mode: "open" }).innerHTML = "<slot></slot>"; } });
window.sent = [];
</script><script>${fs.readFileSync(cardPath, "utf-8")}</script></body></html>`);
  const out = await p.evaluate(() => {
    const ENT = "sensor.flight_watcher_james_pilot_schedule";
    const c = document.createElement("flight-watcher-pilot-card-james");
    c.setConfig({ entity: ENT });
    document.body.appendChild(c);
    c.scrollIntoView = () => {};
    let n = 0;
    const hass = (attrs, extra) => {
      n += 1;
      c.hass = { states: { [ENT]: { state: "x", last_updated: `2026-11-10T20:00:0${n}+00:00`, attributes: attrs }, ...(extra || {}) },
                 callService: (d, s, data) => window.sent.push(data) };
    };
    const text = () => c.shadowRoot.querySelector(".body").innerText;
    const r = {};
    hass({ emp: "10001", name: "Doe, Jane", status: "not readable: error", month: "" });
    r.a = text();
    window.dispatchEvent(new CustomEvent("flight-watcher-pilot-james", { detail: { q: "Roe" } }));
    r.loading = text();
    hass({ emp: "", name: "Roe", status: "No pilot named 'Roe' on the award or seniority list on file. Type the employee number.",
           matches: [], at: "2026-11-10T20:00:00+00:00", month: "" });
    r.nomatch = text();
    hass({ emp: "", name: "Moe", status: "2 pilots match 'Moe', pick one", at: "2026-11-10T20:01:00+00:00", month: "",
           matches: [{ pick: "a1b2c3d4e5f6", name: "Moe, Kai", pos: "FO" }, { pick: "0f9e8d7c6b5a", name: "Moe, Lee", pos: "CA" }] });
    r.picks = text();
    window.sent = [];
    c.shadowRoot.querySelector(".pk").click();
    r.pickSent = window.sent.map((x) => x.payload);
    r.pickLoading = text();
    // overdue: the Watcher's next check was 3 minutes ago and it is paused
    const past = new Date(Date.now() - 180000).toISOString();
    c._ask.at = Date.now() - 300000;
    c._h.states["sensor.flight_watcher_james_next_check"] = { state: past };
    c._h.states["sensor.flight_watcher_james_state"] = { state: "paused" };
    c._paint(true);
    r.overdue = text();
    r.wide = document.documentElement.scrollWidth;
    return r;
  });
  await b.close();
  console.log(JSON.stringify(out));
})().catch((e) => { console.error(e); process.exit(1); });
