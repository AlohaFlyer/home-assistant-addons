// Flight Watcher: near misses in the open time pot (1.7.14). Ryan, Nov 17: "In the open time pot, for each trip hidden
// by a VAC or blocked day, show what I'd have to drop or swap to fly it, plus the pay difference."
// Reads sensor.flight_watcher_near_misses (the Watcher's near_misses(): attributes count, misses, kinds, rate, year,
// pay_note, trimmed). Each miss is a pot trip hidden today because it touches a VAC day, a blocked day or one of your own
// trips: what stands in the way, what to change to fly it (give up those VAC days, unblock the day, drop or swap your
// trip), the pay difference (the trip's Pay-Gross less what you give up: a VAC day 4:00 at your rate, PWA 6.J.1.c; a
// dropped trip its own pay; a blocked day nothing; every trip priced as the schedule card prices it: credit x the PWA
// 3.D.6 rate for your longevity year, the PWA 4.O.1 overrides and the Extended Range +15%) and FAR 117 legality with the
// conflict removed (117.25(e) 10 h rest, 117.25(b) 30 h free in 168 h, 117.23(b)(1) 100 h in 672 h, 117.23(c) FDP
// limits, and the PWA 10.E.1.a 11 h home rest: legal only when all of them pass). The list is folded by default with
// its count; it stays open across updates once opened. Information only: nothing here talks to FLICA or sends anything.
// All times HST. Usage: type: custom:flight-watcher-near-card
const NM_ENTITY = "sensor.flight_watcher_near_misses";

class FlightWatcherNearCard extends HTMLElement {
  setConfig(c) { this.c = c || {}; }
  set hass(h) {
    if (typeof this.toggleAttribute === "function") this.toggleAttribute("dark", !!(h && h.themes && typeof h.themes.darkMode === "boolean" ? h.themes.darkMode : typeof matchMedia === "function" && matchMedia("(prefers-color-scheme: dark)").matches));
    this._h = h;
    const s = h && h.states ? h.states[NM_ENTITY] : null;
    const sig = s ? `${s.last_updated}/${s.state}` : "-";
    if (sig === this._sig) return;
    this._sig = sig;
    this._render();
  }
  _e(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }
  _usd(v) { return "-$" + Math.round(Math.abs(v)).toLocaleString("en-US"); }
  _miss(m) {
    const bl = Array.isArray(m.blockers) ? m.blockers : [];
    const lost = (b) => {
      if (b.kind === "blocked") return "nothing lost";
      const p = [b.credit ? `-${b.credit}` : "", typeof b.pay === "number" ? this._usd(b.pay) : ""].filter(Boolean);
      return p.length ? p.join(", ") : "pay not known";
    };
    const pos = typeof m.diff === "number" ? (m.diff >= 0 ? "pos" : "neg") : "";
    const pay = m.diff_text ? `<span class="pay ${pos}">${this._e(m.diff_text)}${m.hours ? ` <span class="h">${this._e(m.hours)} cr</span>` : ""}</span>`
      : `<span class="pay">${m.hours ? `${this._e(m.hours)} credit, ` : ""}pay not known</span>`;
    const legal = m.legal === true ? "ok" : m.legal === false ? "bad" : "mute";
    const facts = [m.dates || m.start, m.lay, m.days ? `${m.days} d` : "", m.credit ? `Cr ${m.credit}` : "",
      m.src === "C" ? "close-in" : "", m.seat === "RO" ? "RO seat" : ""].filter(Boolean).map((x) => `<span>${this._e(x)}</span>`).join("");
    return `<div class="m"><div class="l1"><b class="trip">${this._e(m.pairing)}</b>${facts}${pay}</div>`
      + `<div class="l2"><span class="lb">In the way:</span> ${bl.map((b) => this._e(b.what)).join(" &middot; ")}</div>`
      + `<div class="l2"><span class="lb">To fly it:</span> ${bl.map((b) => `${this._e(b.fix)} <span class="k">(${this._e(lost(b))})</span>`).join(" &middot; ")}</div>`
      + `<div class="l3"><span class="k">FAR 117</span><span class="c ${legal}" title="${this._e(m.far_why || "")}">${this._e(m.legal_text || "not known yet")}</span></div></div>`;
  }
  _render() {
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    const s = this._h && this._h.states ? this._h.states[NM_ENTITY] : null;
    const a = (s && s.attributes) || {};
    const misses = Array.isArray(a.misses) ? a.misses : [];
    const n = s ? Number(a.count != null ? a.count : misses.length) || 0 : 0;
    let body;
    if (!s) body = `<div class="k">Near misses come with Flight Watcher 1.7.14: the Watcher has not published them yet.</div>`;
    else if (!misses.length) body = `<div class="k">No pot trip is hidden by a VAC day, a blocked day or one of your trips right now.</div>`;
    else {
      const more = n > misses.length ? `<div class="k">The ${misses.length} best of ${n} shown.</div>` : "";
      const note = a.pay_note ? `<div class="warn">${this._e(a.pay_note)}</div>` : "";
      body = note + misses.map((m) => this._miss(m)).join("") + more;
    }
    const rate = typeof a.rate === "number" ? `$${a.rate.toFixed(2)}/h (PWA 3.D.6, longevity year ${this._e(a.year)})` : "your hourly rate (PWA 3.D.6), once Pay settings has your longevity year";
    const open = !!this._open;
    this.shadowRoot.innerHTML = `<style>
      :host{--fw-ok:#2e7d32;--fw-err:#c62828}:host([dark]){--fw-ok:#81c784;--fw-err:#ef9a9a}
      ha-card{padding:4px 12px 8px;font-size:13px;line-height:1.35}
      summary{cursor:pointer;list-style-position:outside;min-height:44px;display:flex;align-items:center;gap:8px;flex-wrap:wrap}
      summary::-webkit-details-marker{display:none}summary:before{content:"\\25B8";color:var(--secondary-text-color)}
      details[open]>summary:before{content:"\\25BE"}
      .t{font-size:15px;font-weight:600}.n{font-weight:700;padding:0 8px;border-radius:10px;border:1px solid var(--divider-color)}
      .k{color:var(--secondary-text-color);font-size:12px}
      .warn{margin:4px 0 6px;padding:6px 8px;border-radius:6px;border-left:4px solid var(--warning-color,#b26a00)}
      .m{padding:6px 0;border-top:1px solid var(--divider-color)}
      .l1{display:flex;flex-wrap:wrap;gap:2px 10px;align-items:baseline}.trip{font-size:14px}
      .l2{margin-top:2px;overflow-wrap:anywhere}.lb{color:var(--secondary-text-color);font-size:12px}
      .l3{display:flex;flex-wrap:wrap;gap:4px 6px;align-items:center;margin-top:3px}
      .pay{margin-left:auto;font-weight:600;font-variant-numeric:tabular-nums}.pay.pos{color:var(--fw-ok)}.pay.neg{color:var(--fw-err)}
      .pay .h{font-weight:400}
      .c{font-size:12px;padding:1px 7px;border-radius:10px;border:1px solid var(--divider-color);overflow-wrap:anywhere}
      .c.ok{color:var(--fw-ok);border-color:currentColor}.c.bad{color:var(--fw-err);border-color:currentColor}.c.mute{color:var(--secondary-text-color)}
      .key summary{min-height:44px;font-size:12px;color:var(--secondary-text-color)}ul{margin:2px 0 4px;padding-left:18px}
    </style><ha-card><details class="nm"${open ? " open" : ""}><summary><span class="t">Near misses</span><span class="n">${n}</span>`
      + `<span class="k">pot trips hidden by VAC, a blocked day or your trips</span></summary>${body}`
      + `<details class="key"><summary>How this is figured</summary><ul class="k">
        <li><b>Pay difference</b> = the trip's Pay-Gross less what you give up, at ${rate}: a VAC day is 4:00 of pay and credit (PWA 6.J.1.c), a dropped trip its own pay, a blocked day nothing. Each trip as the Schedule card prices it: credit (with the PWA 4.C.3 minimums in it) x the rate, the PWA 4.O.1 overrides (RO $4.00 per block hour, FO $3.00 on a 3-pilot crew) and the Extended Range +15%. The hours are the credit difference.</li>
        <li><b>Legal</b> = with what is in the way removed, FAR 117.25(e) 10 h rest, 117.25(b) 30 h free in 168 h, 117.23(b)(1) 100 h flying in 672 h and the 117.23(c) FDP limits pass, and the 11 h home rest (PWA 10.E.1.a). <b>Not known yet</b> = a time is not on file, so it is never called legal.</li>
        <li>Legal ones first, the best pay difference first.</li>
        <li>Information only: nothing is sent to FLICA. Drop, swap, give up VAC or pick up in FLICA yourself; unblock a day on the Schedule card. All times HST.</li></ul></details></details></ha-card>`;
    const d = this.shadowRoot.querySelector("details.nm");
    if (d) d.addEventListener("toggle", () => { this._open = d.open; });
  }
  getCardSize() { return this._open ? 6 : 1; }
}
customElements.define("flight-watcher-near-card", FlightWatcherNearCard);
window.customCards = window.customCards || [];
window.customCards.push({ type: "flight-watcher-near-card", name: "Flight Watcher near misses", description: "Pot trips hidden by VAC, a blocked day or your own trips: what to change, the pay difference and FAR 117" });
