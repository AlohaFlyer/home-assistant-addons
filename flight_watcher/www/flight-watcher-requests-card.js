// Flight Watcher: my FLICA requests (1.6.2, Release A item 13), from sensor.flight_watcher_ot_requests: the open time
// requests and Tradeboard trades the Watcher read on FLICA's own request lists (type, trips, the date and time FLICA
// shows for the request, HST, and its status), newest first. The "Request decided" alert opens the Schedule tab, where
// this card sits. Read only: a request is made, changed or withdrawn in FLICA only, never from here.
// Usage: type: custom:flight-watcher-requests-card
const RQ_MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const rqHst = (iso) => { const t = Date.parse(iso || ""); if (isNaN(t)) return ""; const d = new Date(t - 10 * 3600e3), p = (n) => String(n).padStart(2, "0"); return `${RQ_MON[d.getUTCMonth()]} ${d.getUTCDate()} ${p(d.getUTCHours())}:${p(d.getUTCMinutes())} HST`; };
const RQ_OPEN = ["Pending", "Processing"];  // submit.OPEN: not decided yet
class FlightWatcherRequestsCard extends HTMLElement {
  setConfig(c) { this.c = c || {}; }
  set hass(h) {
    this._h = h;
    const s = h.states["sensor.flight_watcher_ot_requests"];
    const sig = s ? `${s.last_updated}/${s.state}/${(s.attributes || {}).checked_at}` : "-";
    if (sig === this._sig) return;
    this._sig = sig;
    this._render();
  }
  _e(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }
  // FLICA's '10/25' as 'Oct 25'
  _md(s) { const m = /^(\d{1,2})\/(\d{1,2})$/.exec(String(s || "").trim()); return m && +m[1] >= 1 && +m[1] <= 12 ? `${RQ_MON[+m[1] - 1]} ${+m[2]}` : String(s || ""); }
  // a sort key for FLICA's 'MM/DD' and 'HH:MM' (no year: a month more than 6 ahead of this one is last year's)
  _when(r) {
    const m = /^(\d{1,2})\/(\d{1,2})$/.exec(String(r.date || "").trim()); if (!m) return "";
    const now = new Date(Date.now() - 10 * 3600e3); let y = now.getUTCFullYear();
    if (+m[1] - (now.getUTCMonth() + 1) > 6) y -= 1;
    return `${y}-${m[1].padStart(2, "0")}-${m[2].padStart(2, "0")} ${String(r.time || "").padStart(5, "0")}`;
  }
  _cls(st) { return st === "Approved" ? "ok" : st === "Denied" ? "bad" : RQ_OPEN.includes(st) ? "warn" : "mute"; }
  _render() {
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    const s = this._h.states["sensor.flight_watcher_ot_requests"];
    const a = (s && s.attributes) || {};
    const reqs = (a.requests || []).slice().sort((x, y) => this._when(y).localeCompare(this._when(x)));  // newest first
    const head = s ? `${a.count || 0} request${a.count === 1 ? "" : "s"}, ${a.pending || 0} pending${a.checked_at ? ` &middot; read ${this._e(rqHst(a.checked_at))}` : ""}` : "";
    const rows = reqs.map((r) => {
      const trips = (r.trips || []).filter(Boolean).join(", ");
      const when = [this._md(r.date), r.time].filter(Boolean).join(" ");
      return `<div class="r"><span class="c ${this._cls(r.status)}">${this._e(r.status || "?")}</span> <b>${this._e(r.type || "Request")}</b>`
        + `${trips ? ` ${this._e(trips)}` : ""} <span class="k">${when ? `${this._e(when)} HST` : ""}${r.folder === "close-in" ? " &middot; close-in" : ""}</span></div>`;
    }).join("");
    const body = !s ? `<div class="k">Waiting for your Watcher.</div>` : rows || `<div class="k">No requests on FLICA's lists.</div>`;
    this.shadowRoot.innerHTML = `<style>
      ha-card{padding:10px 12px;font-size:13px;line-height:1.4}h3{margin:0;font-size:15px}.hd{display:flex;gap:8px;flex-wrap:wrap;align-items:baseline;margin-bottom:4px}
      .k{color:var(--secondary-text-color);font-size:12px}.r{padding:5px 0;border-top:1px solid var(--divider-color)}
      .c{font-size:12px;padding:1px 7px;border-radius:10px;border:1px solid currentColor}
      .c.ok{color:var(--success-color,#2e7d32)}.c.bad{color:var(--error-color,#c62828)}.c.warn{color:var(--warning-color,#b26a00)}.c.mute{color:var(--secondary-text-color)}
    </style><ha-card><div class="hd"><h3>My FLICA requests</h3><span class="k">${head}</span></div>${body}
      <div class="k">Read only: make, change or withdraw a request in FLICA.</div></ha-card>`;
  }
  getCardSize() { return 3; }
}
customElements.define("flight-watcher-requests-card", FlightWatcherRequestsCard);
window.customCards = window.customCards || [];
window.customCards.push({ type: "flight-watcher-requests-card", name: "Flight Watcher requests", description: "Your open time requests and Tradeboard trades as FLICA lists them" });
