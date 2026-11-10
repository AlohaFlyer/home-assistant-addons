// Flight Watcher: the working flight (1.6.2, Release A item 13), from sensor.flight_watcher_working_flight (FW-0067:
// the leg of the pilot's own FLICA schedule he is working, or works next). A port of the HA "Working Flight" view for
// the pilot portal, without Hark's parts (release, MEL, NOTAM, GIN), which are the admin's only. With no FLICA
// schedule read yet it says so, instead of "No trip". Times as the Watcher gives them: local and HST.
// Usage: type: custom:flight-watcher-working-card
class FlightWatcherWorkingCard extends HTMLElement {
  setConfig(c) { this.c = c || {}; }
  set hass(h) {
    this._h = h;
    const w = h.states["sensor.flight_watcher_working_flight"], s = h.states["sensor.flight_watcher_schedule"];
    const sig = `${w ? w.last_updated + "/" + w.state : "-"}|${s ? s.last_updated + "/" + s.state : "-"}`;
    if (sig === this._sig) return;
    this._sig = sig;
    this._render();
  }
  _e(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }
  // only a plain https link leaves the card (FlightAware, aviationweather.gov)
  _link(u, t) { return /^https:\/\/[A-Za-z0-9.-]+\//.test(String(u || "")) ? `<a href="${this._e(u)}" target="_blank" rel="noopener noreferrer">${t}</a>` : ""; }
  _render() {
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    const S = this._h.states, w = S["sensor.flight_watcher_working_flight"];
    const a = (w && w.attributes) || {};
    const sch = S["sensor.flight_watcher_schedule"];
    const months = (sch && sch.attributes && sch.attributes.months) || {};
    const read = Object.keys(months).length > 0;
    let body;
    if (!w || ["unknown", "unavailable"].includes(w.state)) {
      body = `<div class="k">Waiting for your Watcher.</div>`;
    } else if (!a.pairing) {
      const why = read ? "No trip on your schedule right now." : "No working flight yet: your FLICA schedule has not been read.";
      body = `<div>${this._e(why)}</div>${a.next ? `<div class="k">Next: ${this._e(a.next)}</div>` : ""}`;
    } else {
      const links = [this._link(a.flightaware_url, "FlightAware"), this._link(a.sigwx_url, "Sig Wx")].filter(Boolean).join(" &middot; ");
      body = `<div class="fl"><b>${this._e(a.flight || a.pairing)}</b> ${this._e(a.origin || "")} &rarr; ${this._e(a.dest || "")}</div>
        <div class="k">${this._e(a.pairing)} leg ${this._e(a.leg || "")} &middot; ${this._e(a.date || "")}${a.block ? ` &middot; block ${this._e(a.block)}` : ""}</div>
        <div><b>Status:</b> ${this._e(a.status || "")}${a.status_as_of ? ` <span class="k">(${this._e(a.status_as_of)})</span>` : ""}</div>
        <table><tr><th></th><th>Out</th><th>In</th></tr>
          <tr><td>Station</td><td>${this._e(a.origin || "")}</td><td>${this._e(a.dest || "")}</td></tr>
          <tr><td>Sched</td><td>${this._e(a.dep_sched || "")}</td><td>${this._e(a.arr_sched || "")}</td></tr></table>
        ${a.report ? `<div><b>Report:</b> ${this._e(a.report)}</div>` : ""}
        ${links ? `<div class="lk">${links}</div>` : ""}
        ${a.next ? `<div class="k">Next: ${this._e(a.next)}</div>` : ""}`;
    }
    const upd = a.updated ? `<div class="k u">From your FLICA schedule, updated ${this._e(a.updated)}.</div>` : "";
    this.shadowRoot.innerHTML = `<style>
      ha-card{padding:10px 12px;font-size:13px;line-height:1.4}h3{margin:0 0 4px;font-size:15px}
      .k{color:var(--secondary-text-color);font-size:12px}.fl{font-size:16px}.u{margin-top:4px}
      table{border-collapse:collapse;margin:4px 0;font-variant-numeric:tabular-nums}th,td{padding:2px 10px 2px 0;text-align:left;vertical-align:top}
      th{color:var(--secondary-text-color);font-weight:600;font-size:12px}
      a{color:var(--primary-color);display:inline-block;min-height:32px;line-height:32px}
    </style><ha-card><h3>Working flight</h3>${body}${upd}</ha-card>`;
  }
  getCardSize() { return 3; }
}
customElements.define("flight-watcher-working-card", FlightWatcherWorkingCard);
window.customCards = window.customCards || [];
window.customCards.push({ type: "flight-watcher-working-card", name: "Flight Watcher working flight", description: "The leg of your own schedule you are working or work next" });
