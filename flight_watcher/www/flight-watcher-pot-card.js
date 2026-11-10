// Flight Watcher: the open time pot and Tradeboard pickups (1.6.2, Release A item 13). A port of the HA dashboard's
// pot_table macro, so the pilot portal (which runs no templates) shows the pot too. Reads:
//  - sensor.flight_watcher_pot_count (attribute pairings: the open time pot) and
//    sensor.flight_watcher_tradeboard_pickups (attribute pairings: Tradeboard pickup posts, marked T);
//  - sensor.flight_watcher_last_check and sensor.flight_watcher_state: a pot not read for 15 min is flagged;
//  - input_number.flight_watcher_longevity_year (Pay settings) or the DOH (sensor.flight_watcher_state doh) for Value.
// Each row: trip, dates, layover or turn, days, credit, soft time, captain, Fits (no overlap with your trips, VAC or
// blocked days), FAR 117 (117.25(e) 10 h rest, 117.25(b) 30 h free in 168 h, 117.23(b)(1) 100 h in 672 h, 117.23(c)
// FDP limits; PWA 10.E.1.a 11 h domicile rest, as the Watcher's far.py screens them) and Value (credit x your hourly
// rate, PWA 3.D.6). Rows on VAC or blocked days stay hidden until Show VAC/blocked is ticked (this card's own state on
// this device; no helper). Read only: nothing here talks to FLICA. All times HST.
// Usage: type: custom:flight-watcher-pot-card
// PWA 3.D.6 A330 PAX / B787 First Officer hourly rate by longevity year (1-12) and effective date (as the schedule card)
const PC_RATE_DATES = ["2023-03-02", "2024-03-02", "2025-03-02", "2026-03-02", "2027-01-31"];
const PC_RATE_TABLE = [
  [81.00, 84.00, 87.00, 90.00, 93.00], [181.30, 188.55, 196.09, 203.93, 210.05], [208.37, 216.70, 225.37, 234.39, 241.42],
  [221.09, 229.94, 239.13, 248.70, 256.16], [230.29, 239.50, 249.08, 259.04, 266.81], [241.46, 251.12, 261.16, 271.61, 279.76],
  [251.28, 261.33, 271.79, 282.66, 291.13], [256.66, 266.93, 277.61, 288.71, 297.37], [262.48, 272.98, 283.90, 295.26, 304.12],
  [266.03, 276.67, 287.74, 299.24, 308.22], [270.00, 280.80, 292.03, 303.71, 312.82], [273.62, 284.56, 295.95, 307.78, 317.02]];
const PC_MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const PC_STALE_S = 900;  // the HA macro's 15 min
const pcRate = (year, iso) => { let i = 0; PC_RATE_DATES.forEach((d, k) => { if (iso >= d) i = k; }); return PC_RATE_TABLE[Math.min(12, Math.max(1, year)) - 1][i]; };
const pcDohYear = (iso, doh) => { const [a, b] = [doh, iso].map((s) => String(s).slice(0, 10).split("-").map(Number)); return b[0] - a[0] - (b[1] < a[1] || (b[1] === a[1] && b[2] < a[2]) ? 1 : 0) + 1; };
const pcHrs = (t) => { const m = /^(\d+):(\d{2})$/.exec(String(t || "").trim()); return m ? Number(m[1]) + Number(m[2]) / 60 : null; };
// a UTC ISO time as HST 'Nov 10 01:32' (HST is UTC-10 all year; built from parts, as the other cards do)
const pcHst = (iso) => { const t = Date.parse(iso || ""); if (isNaN(t)) return ""; const d = new Date(t - 10 * 3600e3), p = (n) => String(n).padStart(2, "0"); return `${PC_MON[d.getUTCMonth()]} ${d.getUTCDate()} ${p(d.getUTCHours())}:${p(d.getUTCMinutes())}`; };

class FlightWatcherPotCard extends HTMLElement {
  setConfig(c) { this.c = c || {}; }
  set hass(h) {
    this._h = h;
    const ids = ["sensor.flight_watcher_pot_count", "sensor.flight_watcher_tradeboard_pickups", "sensor.flight_watcher_last_check",
      "sensor.flight_watcher_state", "input_number.flight_watcher_longevity_year"];
    // the state too, not only last_updated: a portal's own state copy may keep last_updated unchanged
    const sig = ids.map((e) => { const s = h.states[e]; return s ? `${s.last_updated}/${e.endsWith("_state") ? (s.attributes || {}).doh : s.state}` : "-"; }).join("|")
      + "|" + Math.floor(Date.now() / 60e3);  // the 15 min freshness line moves on with the clock
    if (sig === this._sig) return;
    this._sig = sig;
    this._render();
  }
  _e(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }
  _a(id) { const s = this._h.states[id]; return (s && s.attributes) || {}; }
  _showVac() {
    if (this._vac === undefined) { let v = "0"; try { v = localStorage.getItem("flight_watcher_pot_show_vac") || "0"; } catch (e) { v = "0"; } this._vac = v === "1"; }
    return this._vac;
  }
  // '26Nov' -> 2026-11-26 in the year that puts it nearest today (the pot runs about two months ahead)
  _iso(s, today) {
    const m = /^(\d{1,2})([A-Za-z]{3})/.exec(String(s || "").trim()); if (!m) return "";
    const mo = PC_MON.findIndex((x) => x.toLowerCase() === m[2].toLowerCase()); if (mo < 0) return "";
    let y = Number(today.slice(0, 4)); const cur = Number(today.slice(5, 7)) - 1;
    if (mo - cur > 6) y -= 1; else if (cur - mo > 6) y += 1;
    return `${y}-${String(mo + 1).padStart(2, "0")}-${m[1].padStart(2, "0")}`;
  }
  _fit(f) {
    const s = String(f || "");
    if (s === "Fits") return ["ok", "Fits"];
    if (s === "No sched") return ["mute", "needs your schedule"];
    if (!s) return ["mute", "fit ?"];
    return ["bad", s];
  }
  _far(f) {
    const s = String(f || "");
    if (s === "OK") return ["ok", "FAR OK"];
    if (s.startsWith("OK")) return ["warn", `FAR ${s}`];
    if (!s || s === "?") return ["mute", "FAR ?"];
    return ["bad", `FAR: ${s}`];
  }
  _render() {
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    const h = this._h, today = new Date(Date.now() - 10 * 3600e3).toISOString().slice(0, 10);
    const pot = (this._a("sensor.flight_watcher_pot_count").pairings || []).map((p) => ({ ...p, _t: false }));
    const tb = (this._a("sensor.flight_watcher_tradeboard_pickups").pairings || []).map((p) => ({ ...p, _t: true }));
    const rows = pot.concat(tb).map((p) => ({ ...p, _s: this._iso(p.start || String(p.dates || "").split("-")[0], today) }))
      .sort((a, b) => (a._s || "9").localeCompare(b._s || "9") || String(a.pairing).localeCompare(String(b.pairing)));
    const showVac = this._showVac();
    const hidden = rows.filter((p) => p.vac || p.blocked);
    const shown = showVac ? rows : rows.filter((p) => !(p.vac || p.blocked));
    // Value: credit x the PWA 3.D.6 rate for the longevity year in Pay settings, else the one the DOH gives
    const lys = h.states["input_number.flight_watcher_longevity_year"];
    const doh = String(this._a("sensor.flight_watcher_state").doh || "");
    let lyr = parseFloat(lys && lys.state);
    if (isNaN(lyr)) lyr = /^\d{4}-\d{2}-\d{2}$/.test(doh) ? Math.min(12, pcDohYear(today, doh)) : NaN;
    const rate = isNaN(lyr) ? null : pcRate(lyr, today);
    const unconf = !!(lys && lys.attributes && lys.attributes.unconfirmed);
    const usd = (v) => "$" + Math.round(v).toLocaleString("en-US");
    // freshness, as the HA macro: a pot not read in 15 min, or a Watcher that is not idle or hunting
    const st = (h.states["sensor.flight_watcher_state"] || {}).state || "unavailable";
    const lc = Date.parse((h.states["sensor.flight_watcher_last_check"] || {}).state || "");
    const fresh = ["idle", "hunting"].includes(st) && !isNaN(lc) && (Date.now() - lc) / 1000 < PC_STALE_S;
    const warn = fresh ? "" : isNaN(lc) ? "The pot has not been read yet."
      : `Pot last read ${pcHst(new Date(lc).toISOString())} HST. May be out of date until the Watcher is running again.`;
    const row = (p) => {
      const [fc, ft] = this._fit(p.fit), [ac, at] = this._far(p.far);
      const cr = pcHrs(p.credit);
      const lay = p.layover && !/none/i.test(p.layover) ? p.layover : (p.turn ? `${p.turn} turn` : "turn");
      const facts = [p.credit ? `Cr ${p.credit}` : "", p.soft ? `Soft ${p.soft}` : "", p.report ? `Rpt ${p.report}` : "",
        p.captain ? `CA ${p.captain}` : ""].filter(Boolean).map((x) => this._e(x)).join(" &middot; ");
      const val = cr != null && rate != null ? `<span class="val" title="${this._e(`${p.credit} credit x $${rate.toFixed(2)}/h (PWA 3.D.6, longevity year ${lyr})`)}">${usd(cr * rate)}</span>` : "";
      return `<div class="r${p.vac || p.blocked ? " off" : ""}"><div class="l1"><b class="trip">${this._e(p.pairing)}</b>${p._t ? `<span class="t" title="Tradeboard pickup post">T</span>` : ""}`
        + `<span>${this._e(p.dates || p.start || "")}</span><span>${this._e(lay)}</span>${p.days ? `<span>${this._e(p.days)} d</span>` : ""}${val}</div>`
        + (facts ? `<div class="l2">${facts}</div>` : "")
        + `<div class="l3"><span class="c ${fc}">${this._e(ft)}</span><span class="c ${ac}">${this._e(at)}</span>${p.vac ? `<span class="c mute">VAC</span>` : ""}${p.blocked ? `<span class="c mute">blocked day</span>` : ""}</div></div>`;
    };
    const nP = pot.length, nT = tb.length;
    const head = `${nP} in the pot &middot; ${nT} Tradeboard pickup${nT === 1 ? "" : "s"}`;
    const list = shown.length ? shown.map(row).join("") : `<div class="k">${rows.length ? "Every trip is on a VAC or blocked day." : "The open time pot is empty and there are no Tradeboard pickups."}</div>`;
    const vacBox = hidden.length || showVac ? `<label class="sv"><input type="checkbox" id="sv"${showVac ? " checked" : ""}> Show VAC/blocked${hidden.length && !showVac ? ` (${hidden.length} hidden)` : ""}</label>` : "";
    const valNote = rate == null ? "Value: set your longevity year in Pay settings (Schedule tab)."
      : `Value = credit x $${rate.toFixed(2)}/h (PWA 3.D.6, longevity year ${lyr}${unconf ? ", not confirmed yet: check it in Pay settings on the Schedule tab" : ""}).`;
    this.shadowRoot.innerHTML = `<style>
      ha-card{padding:10px 12px;font-size:13px;line-height:1.35}
      h3{margin:0;font-size:15px}.hd{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap;margin-bottom:6px}
      .k{color:var(--secondary-text-color);font-size:12px}
      .warn{margin:4px 0 6px;padding:6px 8px;border-radius:6px;border-left:4px solid var(--warning-color,#b26a00);background:rgba(178,106,0,.12)}
      .r{padding:6px 0;border-top:1px solid var(--divider-color)}.r.off{opacity:.6}
      .l1{display:flex;flex-wrap:wrap;gap:4px 10px;align-items:baseline}.l2{color:var(--secondary-text-color);font-size:12px;margin-top:2px;overflow-wrap:anywhere}
      .l3{display:flex;flex-wrap:wrap;gap:4px;margin-top:3px}
      .trip{font-size:14px}.t{font-weight:700;color:var(--primary-color);margin-left:2px}.val{margin-left:auto;font-weight:600;font-variant-numeric:tabular-nums}
      .c{font-size:12px;padding:1px 7px;border-radius:10px;border:1px solid var(--divider-color)}
      .c.ok{color:var(--success-color,#2e7d32);border-color:currentColor}.c.warn{color:var(--warning-color,#b26a00);border-color:currentColor}
      .c.bad{color:var(--error-color,#c62828);border-color:currentColor}.c.mute{color:var(--secondary-text-color)}
      .sv{display:inline-flex;align-items:center;gap:6px;min-height:44px;cursor:pointer}.sv input{width:22px;height:22px;margin:0}
      details{margin-top:6px}summary{cursor:pointer;color:var(--secondary-text-color);font-size:12px;min-height:32px;line-height:32px}
      ul{margin:4px 0;padding-left:18px}
    </style><ha-card><div class="hd"><h3>Open time pot and Tradeboard pickups</h3><span class="k">${head}</span></div>
      ${warn ? `<div class="warn">${this._e(warn)}</div>` : ""}${list}${vacBox}
      <details><summary>Key</summary><ul class="k">
        <li><b>T</b> after a trip = Tradeboard pickup post; the rest are the open time pot.</li>
        <li><b>Fits</b> = no overlap with your trips, VAC or blocked days; <b>needs your schedule</b> = your FLICA schedule for those days is not read yet.</li>
        <li><b>FAR</b> = 10 h rest before and after (117.25(e)), 30 h off in 168 h (117.25(b)), 100 h flying in 672 h (117.23(b)(1)), FDP limits (117.23(c)); <b>CBA rest</b> = legal, but under the 11 h company minimum (PWA 10.E.1.a); <b>?</b> = not checked yet.</li>
        <li>${this._e(valNote)}</li>
        <li>Trips on VAC or blocked days are hidden: tick <b>Show VAC/blocked</b>. Block a day: tap it on the Schedule tab's calendar.</li>
        <li>Read only: pick a trip up in FLICA yourself. All times HST.</li></ul></details></ha-card>`;
    const sv = this.shadowRoot.getElementById("sv");
    if (sv) sv.addEventListener("change", (e) => { this._vac = e.target.checked; try { localStorage.setItem("flight_watcher_pot_show_vac", this._vac ? "1" : "0"); } catch (x) { /* view state only */ } this._sig = null; this._render(); });
  }
  getCardSize() { return 4; }
}
customElements.define("flight-watcher-pot-card", FlightWatcherPotCard);
window.customCards = window.customCards || [];
window.customCards.push({ type: "flight-watcher-pot-card", name: "Flight Watcher open time pot", description: "The open time pot and Tradeboard pickups with Fits, FAR 117 and value" });
