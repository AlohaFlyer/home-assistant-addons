// Flight Watcher: Improved-Pay-Gross by month (Ryan, 2026-11-05). Bars = current version's Pay-Gross minus the awarded
// line (version .001) for each month, both priced with today's pay settings by the schedule card; dashed line = least
// squares trend. Reads sensor.flight_watcher_improved_pay_gross (app 0.9.0+). Read only.
class FlightWatcherImprovedCard extends HTMLElement {
  setConfig(c) { this.c = c || {}; }
  set hass(h) {
    const st = h.states[(this.c && this.c.entity) || "sensor.flight_watcher_improved_pay_gross"];
    const sig = st ? st.last_updated : "none";
    if (sig === this._sig) return;
    this._sig = sig;
    const rows = ((st && st.attributes.months) || []).filter((r) => r && r.month);
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    const usd = (v) => (v < 0 ? "-$" : "$") + Math.round(Math.abs(v)).toLocaleString("en-US");
    const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    let svg = "";
    if (!rows.length) {
      svg = `<div class="none">No months priced yet. Open the schedule card on each month once app 0.9.0 is running; it reports Awarded and current Pay-Gross here.</div>`;
    } else {
      const W = 640, Ht = 220, pl = 56, pr = 12, pt = 14, pb = 34;
      const vals = rows.map((r) => Number(r.improved) || 0);
      const lo = Math.min(0, ...vals), hi = Math.max(0, ...vals, 1);
      const y = (v) => pt + (hi - v) * (Ht - pt - pb) / (hi - lo || 1);
      const n = rows.length, bw = Math.max(8, Math.min(48, (W - pl - pr) / n * 0.6)), step = (W - pl - pr) / n;
      const x = (i) => pl + step * i + step / 2;
      const grid = [lo, (lo + hi) / 2, hi].map((v) => `<line x1="${pl}" x2="${W - pr}" y1="${y(v)}" y2="${y(v)}" class="g"/><text x="${pl - 6}" y="${y(v) + 4}" class="ax" text-anchor="end">${usd(v)}</text>`).join("");
      const bars = rows.map((r, i) => { const v = Number(r.improved) || 0, top = Math.min(y(v), y(0)), h = Math.max(1, Math.abs(y(v) - y(0)));
        return `<rect x="${x(i) - bw / 2}" y="${top}" width="${bw}" height="${h}" class="${v >= 0 ? "b" : "bn"}"><title>${MON[+r.month.slice(5, 7) - 1]} ${r.month.slice(0, 4)}: Improved ${usd(v)} (awarded ${usd(r.awarded || 0)} v${r.awarded_ver || "?"}, now ${usd(r.current || 0)} v${r.ver || "?"})</title></rect>` +
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
        `<div class="k">Total improved: <b>${usd(ytd)}</b> over ${n} month${n === 1 ? "" : "s"}. Bars: current version minus the awarded line (v.001), both at today's pay settings. Dashed: trend.</div>`;
    }
    this.shadowRoot.innerHTML = `<style>
      ha-card{padding:12px 14px}h3{margin:0 0 8px;font-size:16px;font-weight:600}svg{width:100%;height:auto}
      .g{stroke:var(--divider-color,#ddd);stroke-width:1}.z{stroke:var(--secondary-text-color,#888);stroke-width:1}
      .b{fill:#2e7d32}.bn{fill:#c62828}.t{stroke:var(--primary-color,#03a9f4);stroke-width:2;stroke-dasharray:6 4}
      .ax{font-size:11px;fill:var(--secondary-text-color,#666)}.lb{font-size:11px;fill:var(--primary-text-color,#222)}
      .k{font-size:12px;opacity:.8;margin-top:4px}.none{font-size:13px;opacity:.75}
    </style><ha-card><h3>Improved-Pay-Gross by month</h3>${svg}</ha-card>`;
  }
  getCardSize() { return 5; }
}
customElements.define("flight-watcher-improved-card", FlightWatcherImprovedCard);
window.customCards = window.customCards || [];
window.customCards.push({ type: "flight-watcher-improved-card", name: "Flight Watcher improved pay", description: "Improved-Pay-Gross by month with a trend line" });
