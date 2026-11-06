// Flight Watcher: Improved-Pay-Gross by month (Ryan, 2026-11-05). Bars = current version's Pay-Gross minus the awarded
// line (version .001) for each month, both priced with today's pay settings by the schedule card; dashed line = least
// squares trend. Reads sensor.flight_watcher_improved_pay_gross (app 0.9.0+). Read only.
// FW-0047 (Ryan, Nov 6): a Net tick box switches the bars, the title and the total to Improved-Pay-Net, priced exactly
// as the schedule card's Pay-Net: gross x (1 - (federal + state) / 100) from input_number.flight_watcher_federal_tax_pct
// and _state_tax_pct (22 and 0 while a helper has no number). Gross by default; the choice is kept per browser.
const IMP_FED = "input_number.flight_watcher_federal_tax_pct", IMP_STT = "input_number.flight_watcher_state_tax_pct";
const IMP_NET_KEY = "flight_watcher_improved_net";  // localStorage: "1" = Net, "0" = Gross

class FlightWatcherImprovedCard extends HTMLElement {
  setConfig(c) { this.c = c || {}; }
  set hass(h) {
    this._h = h;
    const ent = (this.c && this.c.entity) || "sensor.flight_watcher_improved_pay_gross";
    const sig = [ent, IMP_FED, IMP_STT].map((e) => (h.states[e] ? h.states[e].last_updated : "none")).join("|");  // a tax change redraws Net
    if (sig === this._sig) return;
    this._sig = sig;
    this._render();
  }
  _tax() {  // the schedule card's num(): the helper's number, else its default
    const S = (this._h && this._h.states) || {};
    const num = (e, d) => { const v = parseFloat((S[e] || {}).state); return isNaN(v) ? d : v; };
    return { fed: num(IMP_FED, 22), stt: num(IMP_STT, 0) };
  }
  _isNet() {
    if (this._net === undefined) {
      let v = null;
      try { v = localStorage.getItem(IMP_NET_KEY); } catch (e) { v = null; }  // private mode / blocked storage: Gross
      this._net = v === "1";
    }
    return this._net;
  }
  _setNet(on) {
    this._net = !!on;
    try { localStorage.setItem(IMP_NET_KEY, this._net ? "1" : "0"); } catch (e) { /* kept for this page only */ }
    this._render();
  }
  _rows() {
    const st = this._h && this._h.states[(this.c && this.c.entity) || "sensor.flight_watcher_improved_pay_gross"];
    return ((st && st.attributes && st.attributes.months) || []).filter((r) => r && r.month);
  }
  _html() {
    const rows = this._rows();
    const net = this._isNet();
    const { fed, stt } = this._tax();
    const k = net ? 1 - (fed + stt) / 100 : 1;  // Pay-Net = gross x (1 - (fed + stt) / 100), as on the schedule card
    const lbl = net ? "Net" : "Gross";
    const usd = (v) => (v < 0 ? "-$" : "$") + Math.round(Math.abs(v)).toLocaleString("en-US");
    const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    let svg = "";
    if (!rows.length) {
      svg = `<div class="none">No months priced yet. Open the schedule card on each month once app 0.9.0 is running; it reports Awarded and current Pay-Gross here.</div>`;
    } else {
      const W = 640, Ht = 220, pl = 56, pr = 12, pt = 14, pb = 34;
      const vals = rows.map((r) => (Number(r.improved) || 0) * k);
      const lo = Math.min(0, ...vals), hi = Math.max(0, ...vals, 1);
      const y = (v) => pt + (hi - v) * (Ht - pt - pb) / (hi - lo || 1);
      const n = rows.length, bw = Math.max(8, Math.min(48, (W - pl - pr) / n * 0.6)), step = (W - pl - pr) / n;
      const x = (i) => pl + step * i + step / 2;
      const grid = [lo, (lo + hi) / 2, hi].map((v) => `<line x1="${pl}" x2="${W - pr}" y1="${y(v)}" y2="${y(v)}" class="g"/><text x="${pl - 6}" y="${y(v) + 4}" class="ax" text-anchor="end">${usd(v)}</text>`).join("");
      const bars = rows.map((r, i) => { const v = vals[i], top = Math.min(y(v), y(0)), h = Math.max(1, Math.abs(y(v) - y(0)));
        return `<rect x="${x(i) - bw / 2}" y="${top}" width="${bw}" height="${h}" class="${v >= 0 ? "b" : "bn"}"><title>${MON[+r.month.slice(5, 7) - 1]} ${r.month.slice(0, 4)}: Improved-Pay-${lbl} ${usd(v)} (awarded ${usd((r.awarded || 0) * k)} v${r.awarded_ver || "?"}, now ${usd((r.current || 0) * k)} v${r.ver || "?"})</title></rect>` +
          `<text x="${x(i)}" y="${Ht - pb + 14}" class="ax" text-anchor="middle">${MON[+r.month.slice(5, 7) - 1]}</text><text x="${x(i)}" y="${top - 4}" class="lb" text-anchor="middle">${usd(v)}</text>`; }).join("");
      let trend = "";
      if (n >= 2) {
        const mx = (n - 1) / 2, my = vals.reduce((a, b) => a + b, 0) / n;
        let sxy = 0, sxx = 0; vals.forEach((v, i) => { sxy += (i - mx) * (v - my); sxx += (i - mx) ** 2; });
        const b = sxx ? sxy / sxx : 0, a = my - b * mx;
        trend = `<line x1="${x(0)}" y1="${y(a)}" x2="${x(n - 1)}" y2="${y(a + b * (n - 1))}" class="t"><title>Trend ${b >= 0 ? "+" : ""}${usd(b)} per month</title></line>`;
      }
      const ytd = vals.reduce((a, b) => a + b, 0);
      svg = `<svg viewBox="0 0 ${W} ${Ht}" preserveAspectRatio="xMidYMid meet">${grid}<line x1="${pl}" x2="${W - pr}" y1="${y(0)}" y2="${y(0)}" class="z"/>${bars}${trend}</svg>` +
        `<div class="k">Total improved${net ? " (net)" : ""}: <b>${usd(ytd)}</b> over ${n} month${n === 1 ? "" : "s"}. Bars: current version minus the awarded line (v.001), both at today's pay settings${net ? `, less ${fed}% federal and ${stt}% state tax (the schedule card's Pay-Net; estimate)` : ""}. Dashed: trend.</div>`;
    }
    return `<style>
      ha-card{padding:12px 14px}.hd{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin:0 0 8px}
      h3{margin:0;font-size:16px;font-weight:600;flex:1;min-width:0}svg{width:100%;height:auto}
      .nt{display:inline-flex;align-items:center;gap:4px;font-size:13px;color:var(--primary-text-color);cursor:pointer;white-space:nowrap;user-select:none}
      .nt input{margin:0;width:16px;height:16px;accent-color:var(--primary-color,#03a9f4);cursor:pointer}
      .g{stroke:var(--divider-color,#ddd);stroke-width:1}.z{stroke:var(--secondary-text-color,#888);stroke-width:1}
      .b{fill:#2e7d32}.bn{fill:#c62828}.t{stroke:var(--primary-color,#03a9f4);stroke-width:2;stroke-dasharray:6 4}
      .ax{font-size:11px;fill:var(--secondary-text-color,#666)}.lb{font-size:11px;fill:var(--primary-text-color,#222)}
      .k{font-size:12px;opacity:.8;margin-top:4px}.none{font-size:13px;opacity:.75}
    </style><ha-card><div class="hd"><h3>Improved-Pay-${lbl} by month</h3><label class="nt" title="Tick for Pay-Net: Pay-Gross less the federal and state tax settings (schedule card > Pay settings)"><input type="checkbox" data-net${net ? " checked" : ""}> Net</label></div>${svg}</ha-card>`;
  }
  _render() {
    if (!this.shadowRoot) {
      this.attachShadow({ mode: "open" });
      this.shadowRoot.addEventListener("change", (e) => { if (e.target && e.target.matches && e.target.matches("input[data-net]")) this._setNet(e.target.checked); });
    }
    this.shadowRoot.innerHTML = this._html();
  }
  getCardSize() { return 5; }
}
customElements.define("flight-watcher-improved-card", FlightWatcherImprovedCard);
window.customCards = window.customCards || [];
window.customCards.push({ type: "flight-watcher-improved-card", name: "Flight Watcher improved pay", description: "Improved-Pay-Gross (or Net) by month with a trend line" });
