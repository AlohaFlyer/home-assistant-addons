// FLICA Watcher finds card (0.9.4, Ryan): "Recently added to the pot" with a month picker. The last 2 days show,
// the rest of the month opens under "Older". Live rows: sensor.flica_watcher_finds; month history (24 months):
// /local/flica/finds_<YYYY-MM>.json written by the Watcher. Times HST.
class FlicaFindsCard extends HTMLElement {
  setConfig(c) { this._c = { entity: "sensor.flica_watcher_finds", ...c }; this._files = {}; this._older = false; this._m = this._hstMonth(Date.now()); }
  getCardSize() { return 8; }
  _hstMonth(ms) { return new Date(ms - 10 * 3600e3).toISOString().slice(0, 7); }
  _e(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]); }
  set hass(h) {
    this._h = h;
    const st = h.states[this._c.entity];
    const sig = st ? st.last_updated : "none";
    if (sig === this._sig) return;
    this._sig = sig;
    if (this._m === this._hstMonth(Date.now())) this._load(this._m, true);
    this._render();
  }
  async _load(m, force) {
    if (this._files[m] && !force) return;
    if (this._files[m] && force && Date.now() - (this._files[m].at || 0) < 60e3) return;
    try {
      const r = await fetch(`/local/flica/finds_${m}.json?t=${Date.now()}`, { cache: "no-store" });
      this._files[m] = r.ok ? { ...(await r.json()), at: Date.now() } : { finds: [], at: Date.now(), missing: true };
    } catch (e) { this._files[m] = { finds: [], at: Date.now(), missing: true }; }
    this._render();
  }
  _t(iso) {
    if (!iso) return "";
    return new Date(iso).toLocaleString("en-US", { timeZone: "Pacific/Honolulu", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false }).replace(",", "");
  }
  _dates(f) {
    const m = String(f.dates || "").match(/^(\d{2})([A-Za-z]{3})(?:-(\d{2})([A-Za-z]{3}))?/);
    if (!m) return this._e(f.dates);
    const a = `${m[2]} ${+m[1]}`;
    if (!m[3]) return a;
    return m[4].toLowerCase() === m[2].toLowerCase() ? `${a}-${+m[3]}` : `${a}-${m[4]} ${+m[3]}`;
  }
  _who(f) {
    return String(f.picked_by || "").split("; ").map((part) => {
      const sp = part.indexOf(" ");
      const seat = sp > 0 ? part.slice(0, sp) : "", nm = sp > 0 ? part.slice(sp + 1) : part;
      const em = nm.match(/\((\d{3,7})\)\s*$/);
      const lnk = em ? `<a href="#pilot=${em[1]},${encodeURIComponent(nm.replace(/\s*\(\d+\)\s*$/, ""))}">${this._e(nm)}</a>` : this._e(nm);
      return `${this._e(seat)} ${f.pickup_known ? `<b>${lnk}</b>` : lnk}`;
    }).join("; ");
  }
  _speed(f) {
    if (f.dwell_s == null || !f.gone) return "";
    const a = +f.dwell_s, pm = +(f.dwell_pm_s || 0);
    const txt = a >= 3600 ? `${Math.floor(a / 3600)}h ${String(Math.floor(a % 3600 / 60)).padStart(2, "0")}m` : a >= 60 ? `${Math.floor(a / 60)}m ${String(a % 60).padStart(2, "0")}s` : `${a}s`;
    const pmt = pm < 5 ? "" : ` ±${pm >= 60 ? Math.floor(pm / 60) + "m" : pm + "s"}`;
    const av = f.picker_avg_s;
    const tip = av != null ? `picker avg ${av >= 60 ? Math.floor(av / 60) + "m " + String(av % 60).padStart(2, "0") + "s" : av + "s"} over ${f.picker_n} pickup${f.picker_n !== 1 ? "s" : ""}` : "";
    return `<span title="${this._e(tip)}">${f.picker_approx ? "~" : ""}${a < 60 ? `<b>${txt}</b>` : txt}<sub>${pmt}</sub></span>`;
  }
  _row(f) {
    const st = f.pickup_status || "";
    let by;
    if (!f.gone) by = "still open";
    else if (st === "open") by = `<ha-icon icon="mdi:eye-off"></ha-icon> <b>Open, not in pot (hidden?)</b>${f.picked_by ? ` (${this._e(f.picked_by)})` : ""}`;
    else if (st === "unchanged") by = "left pot, same crew";
    else if (f.picked_by) by = this._who(f);
    else by = "checking";
    const inflt = f.inflt === true ? `<ha-icon icon="mdi:airplane"></ha-icon>` : f.inflt === false ? "no" : (st === "filled" && f.picked_by ? "-" : "");
    const prem = f.prem && f.gone && st === "filled" ? `<ha-icon icon="mdi:alpha-x"></ha-icon>` : f.prem ? "X" : "";
    const lay = f.layover && !["-none-", "none"].includes(f.layover) ? this._e(f.layover) : (f.turn ? `<b>${this._e(f.turn)}</b>` : "none");
    const cls = st === "open" && f.gone ? "hid" : (f.prem && f.gone && st === "filled" ? "prem" : "");
    return `<tr class="${cls}"><td>${this._t(f.seen)}</td><td>${this._t(f.gone)}</td><td><b>${this._e(f.pairing)}</b>${f.source === "email" ? ` <ha-icon icon="mdi:email-outline"></ha-icon>` : ""}</td><td>${this._dates(f)}</td><td>${lay}</td><td class="n">${this._e(f.days)}</td><td class="n">${this._e(f.credit)}</td><td>${this._e(f.captain)}</td><td>${by}</td><td class="c">${inflt}</td><td class="n">${this._speed(f)}</td><td class="c">${prem}</td></tr>`;
  }
  _rows() {
    const cur = this._m === this._hstMonth(Date.now());
    const file = (this._files[this._m] || {}).finds || [];
    const live = cur ? ((this._h && this._h.states[this._c.entity] || {}).attributes || {}).finds || [] : [];
    const byKey = new Map();
    for (const f of file) byKey.set(`${f.pairing}|${f.seen}`, f);
    for (const f of live) if (this._hstMonth(Date.parse(f.seen)) === this._m) byKey.set(`${f.pairing}|${f.seen}`, f);
    return [...byKey.values()].sort((a, b) => Date.parse(b.seen) - Date.parse(a.seen));
  }
  _render() {
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    if (!this._files[this._m]) this._load(this._m);
    const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    const [y, m] = this._m.split("-").map(Number);
    const all = this._rows();
    const cut = Date.now() - 48 * 3600e3;
    const recent = all.filter((f) => Date.parse(f.seen) >= cut), older = all.filter((f) => Date.parse(f.seen) < cut);
    const head = `<tr><th>Seen</th><th>Picked up</th><th>Trip</th><th>Dates</th><th>Layover</th><th>Days</th><th>Credit</th><th>CA</th><th>Picked up by</th><th>InFlt</th><th>Pickup Speed</th><th>Prem</th></tr>`;
    const loading = !this._files[this._m];
    const openTop = this._top !== false;
    this.shadowRoot.innerHTML = `<style>
      ha-card{padding:10px 14px;font-size:12.5px}
      .hd{display:flex;align-items:flex-start;gap:8px}.hd summary{cursor:pointer;font-weight:700;font-size:14px}
      .mp{margin-left:auto;display:flex;align-items:center;gap:8px;font-weight:700}.mp .nv{cursor:pointer;font-size:20px;color:var(--primary-color);padding:0 6px;user-select:none}
      .wrap{overflow-x:auto}table{border-collapse:collapse;width:100%;margin-top:6px}
      th,td{border:1px solid var(--divider-color);padding:4px 6px;text-align:left;white-space:nowrap}th{font-weight:700}
      td.n{text-align:right}td.c{text-align:center}
      tr.hid td{background:rgba(244,67,54,.14)}tr.prem td{background:rgba(76,175,80,.16)}
      a{color:var(--primary-color);text-decoration:underline}
      .old{margin-top:6px}.old summary,.key summary{cursor:pointer;font-size:12px;color:var(--secondary-text-color)}
      .k{color:var(--secondary-text-color);font-size:12px;margin-top:6px}
      ha-icon{--mdc-icon-size:16px}
    </style><ha-card>
      <div class="hd"><details class="top"${openTop ? " open" : ""} style="flex:1;min-width:0"><summary><ha-icon icon="mdi:new-box"></ha-icon> Recently added to the pot <span class="k">${all.length} in ${MON[m - 1]}</span></summary>
        ${loading ? `<div class="k">Loading ${MON[m - 1]} ${y}...</div>` : ""}
        ${recent.length ? `<div class="wrap"><table>${head}${recent.map((f) => this._row(f)).join("")}</table></div>` : (!loading ? `<div class="k">Nothing new in the last 2 days${older.length ? "" : ` in ${MON[m - 1]} ${y}`}.</div>` : "")}
        ${older.length ? `<details class="old"${this._older ? " open" : ""}><summary>${older.length} older in ${MON[m - 1]} ${y}</summary><div class="wrap"><table>${head}${older.map((f) => this._row(f)).join("")}</table></div></details>` : ""}
        <details class="key"><summary>Key</summary><div class="k">
          <div><ha-icon icon="mdi:email-outline"></ha-icon> caught from your FLICA alert email (gone before a pot check)</div>
          <div>InFlt <ha-icon icon="mdi:airplane"></ha-icon> = picked up while airborne (from the picker's own trip); no = on the ground; - = not checked yet</div>
          <div>Pickup Speed = how long the trip sat in open time, ± half the check window; ~ = timed from your alert email; bold under 1 min. Hover for the picker's average.</div>
          <div>Red row: seat still open but not in the pot (hidden?). Green row: Premium trip picked up.</div>
          <div>Last 2 days show; the rest of the month opens under "older". History kept 24 months.</div></div></details>
      </details>
      <span class="mp"><span class="nv" data-m="-1">&#8249;</span>${MON[m - 1]} ${y}<span class="nv" data-m="1">&#8250;</span></span></div>
    </ha-card>`;
    const r = this.shadowRoot;
    r.querySelector("details.top").ontoggle = (e) => { this._top = e.target.open; };
    const od = r.querySelector("details.old");
    if (od) od.ontoggle = () => { this._older = od.open; };
    r.querySelectorAll("[data-m]").forEach((el) => el.onclick = () => {
      const d = new Date(Date.UTC(y, m - 1 + Number(el.dataset.m), 1));
      const nm = d.toISOString().slice(0, 7);
      if (nm > this._hstMonth(Date.now())) return;
      this._m = nm;
      this._older = false;
      this._render();
    });
  }
}
customElements.define("flica-finds-card", FlicaFindsCard);
