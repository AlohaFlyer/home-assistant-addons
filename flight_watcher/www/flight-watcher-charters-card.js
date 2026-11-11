// Flight Watcher: charters and unusual A330 flying from CrewTrac (1.6.2, Release A item 13), from
// sensor.flight_watcher_charters. A port of the HA dashboard's charters markdown for the pilot portal: the CrewTrac
// status in plain words (attribute crewtrac.state: ok, refused, outage, not_configured, or not tried yet, and the
// Watcher's own status text), the flights found (date, flight, route, scheduled, equipment, tail, why) and the last
// scan (HST), with the Scan CrewTrac now button (button.flight_watcher_scan_crewtrac_charters_now). The button is off
// while CrewTrac's refusal of the saved details stands or none are saved: the Watcher would not log in (1.6.1). Read
// only: CrewTrac Scheduled Service, nothing is ever changed there.
// 1.7.1 (F#22, shared charters): a pilot's Watcher runs no CrewTrac scan of its own; its sensor carries the admin's scan
// (attribute source "admin", last_scan the admin's scan time, crewtrac.state not_used). The card then says where the
// list comes from and when it was scanned, and has no Scan button (his Watcher would answer that it does not scan).
// A flight gone from the schedule is struck through at full color (it was faded to 60 %, under WCAG AA contrast).
// Usage: type: custom:flight-watcher-charters-card
const CC_MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const ccHst = (iso) => { const t = Date.parse(iso || ""); if (isNaN(t)) return ""; const d = new Date(t - 10 * 3600e3), p = (n) => String(n).padStart(2, "0"); return `${CC_MON[d.getUTCMonth()]} ${d.getUTCDate()} ${p(d.getUTCHours())}:${p(d.getUTCMinutes())} HST`; };
class FlightWatcherChartersCard extends HTMLElement {
  setConfig(c) { this.c = c || {}; }
  set hass(h) {
    this._h = h;
    const s = h.states["sensor.flight_watcher_charters"];
    const sig = s ? `${s.last_updated}/${s.state}/${JSON.stringify(s.attributes || {}).length}/${((s.attributes || {}).crewtrac || {}).state}/${(s.attributes || {}).status}` : "-";
    if (sig === this._sig) return;
    this._sig = sig;
    this._render();
  }
  _e(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }
  // [class, words, scan allowed]: the CrewTrac state the Watcher published (1.6.1), else the status text alone
  _status(a) {
    const ct = a.crewtrac || {}, st = String(a.status || "");
    if (ct.state === "refused") return ["bad", st || "CrewTrac refused your user ID or password. No more tries until you save new CrewTrac details on the Settings tab.", false];
    if (ct.state === "not_configured") return ["info", "CrewTrac is not set up: enter your CrewTrac user ID and password on the Settings tab.", false];
    if (ct.state === "outage") return ["warn", st || "CrewTrac could not be reached. The Watcher tries again later.", true];
    if (ct.state === "ok" || st.startsWith("ok")) return ["ok", "CrewTrac OK.", true];
    if (st) return ["info", st, true];
    return ["info", "Not scanned yet.", true];
  }
  _render() {
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    const s = this._h.states["sensor.flight_watcher_charters"];
    const a = (s && s.attributes) || {};
    const items = a.items || [];
    const shared = a.source === "admin";  // 1.7.1 (F#22): the admin's scan, shown on a pilot's card
    const ls = ccHst(a.last_scan);
    const [cls, words, can] = !s ? ["info", "Waiting for your Watcher.", false]
      : shared ? ["info", ls ? `From the admin's CrewTrac scan at ${ls}.` : "Waiting for the admin's CrewTrac scan.", false]
      : this._status(a);
    const rows = items.map((r) => `<div class="r${r.gone ? " gone" : ""}"><div><b>${this._e(r.flight)}</b> ${this._e(r.route)} <span class="k">${this._e(r.date)} ${this._e(r.scheduled || "")}</span></div>`
      + `<div class="k">${[r.eqpt, r.tail, r.why, r.first_seen ? `seen ${r.first_seen}` : ""].filter(Boolean).map((x) => this._e(x)).join(" &middot; ")}${r.gone ? " &middot; no longer on the schedule" : ""}</div></div>`).join("");
    // 1.6.2 review: 'nothing found' only after a scan; before one (or while CrewTrac is refused or not set up) it says so
    const ctSt = (a.crewtrac || {}).state || "";
    const none = !s || items.length ? "" : ls ? `<div class="k">No unusual A330 flying found (scanned ${ls}).</div>`
      : shared || ["refused", "not_configured"].includes(ctSt) ? "" : `<div class="k">Not scanned yet.</div>`;
    const btnWhy = can ? "Logs in to CrewTrac once and scans the next 30 days (at most one press every 30 min)."
      : "Off until CrewTrac details that work are saved on the Settings tab.";
    const foot = shared ? `<div class="k" id="why">The admin's Watcher scans CrewTrac every 6 h and shares the flights it finds. Yours never logs in to CrewTrac, so you need no CrewTrac login.</div>`
      : `<button id="scan"${can ? "" : " disabled"}>Scan CrewTrac now</button><div class="k" id="why">${this._e(btnWhy)}</div>`;
    this.shadowRoot.innerHTML = `<style>
      ha-card{padding:10px 12px;font-size:13px;line-height:1.4}h3{margin:0 0 6px;font-size:15px}
      .k{color:var(--secondary-text-color);font-size:12px}
      .st{margin:0 0 6px;padding:6px 8px;border-radius:6px;border-left:4px solid var(--divider-color)}
      .st.bad{border-left-color:var(--error-color,#c62828);background:rgba(198,40,40,.12)}.st.warn{border-left-color:var(--warning-color,#b26a00);background:rgba(178,106,0,.12)}
      .st.ok{border-left-color:var(--success-color,#2e7d32)}.st.info{border-left-color:var(--info-color,#0074c8)}
      .r{padding:5px 0;border-top:1px solid var(--divider-color)}.r.gone{text-decoration:line-through}
      button{font:inherit;min-height:44px;padding:8px 16px;margin-top:8px;border-radius:8px;border:1px solid var(--divider-color);background:var(--card-background-color);color:var(--primary-color);cursor:pointer}
      button:disabled{color:var(--secondary-text-color);cursor:not-allowed;opacity:.7}
    </style><ha-card><h3>Charters and unusual A330 flying <span class="k">(CrewTrac, next 30 days)</span></h3>
      <div class="st ${cls}" id="st">${this._e(words)}</div>${rows}${none}
      ${items.length && ls && !shared ? `<div class="k">Last scan ${ls}.</div>` : ""}
      ${foot}
      ${this._msg ? `<div class="k" id="msg">${this._e(this._msg)}</div>` : ""}</ha-card>`;
    const b = this.shadowRoot.getElementById("scan");
    if (b && can) b.addEventListener("click", () => {
      b.disabled = true;
      Promise.resolve(this._h.callService("button", "press", { entity_id: "button.flight_watcher_scan_crewtrac_charters_now" }))
        .then(() => { this._msg = "Asked for a scan. The status above changes when it is done."; }, (e) => { this._msg = `Not sent: ${(e && e.message) || e}`; })
        .finally(() => { this._sig = null; this._render(); });
    });
  }
  getCardSize() { return 3; }
}
customElements.define("flight-watcher-charters-card", FlightWatcherChartersCard);
window.customCards = window.customCards || [];
window.customCards.push({ type: "flight-watcher-charters-card", name: "Flight Watcher charters", description: "CrewTrac status, charters and unusual A330 flying, and Scan CrewTrac now" });
