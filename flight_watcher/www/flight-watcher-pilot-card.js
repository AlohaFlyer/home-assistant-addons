/* Flight Watcher: pilot schedule card (v3, Ryan 2026-11-04). v3: free-text lookup with a pick list.
   Tap a pilot's name on the pickers list or in Recently added (link #pilot=EMP) and the Watcher reads that
   pilot's current month from Tools > Schedule Lookup (read only) and publishes sensor.flight_watcher_pilot_schedule;
   this card draws it in the same calendar shape as the schedule card: Day, Date, Trip, Layover (boxed per
   trip), Block, Credit, Soft, Crew. Nothing is written to FLICA. */
const DOW = ["SU", "MO", "TU", "WE", "TH", "FR", "SA"];
const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

class FlightWatcherPilotCard extends HTMLElement {
  setConfig(config) {
    this._config = { entity: "sensor.flight_watcher_pilot_schedule", ...config };
    this._hidden = false;
    if (!FlightWatcherPilotCard._hooked) {
      FlightWatcherPilotCard._hooked = true;
      const fire = () => {
        const m = /#pilot=(\d+)(?:,([^#&]*))?/.exec(location.hash || "");
        if (!m) return;
        history.replaceState(null, "", location.pathname + location.search);
        window.dispatchEvent(new CustomEvent("flight-watcher-pilot", { detail: { emp: m[1], name: decodeURIComponent(m[2] || "") } }));
      };
      for (const ev of ["hashchange", "popstate", "location-changed"]) window.addEventListener(ev, fire);  // HA routes markdown links via pushState: location-changed
      fire();
    }
    window.addEventListener("flight-watcher-pilot", (e) => {
      this._hidden = false;
      this._want = e.detail.emp || e.detail.q;
      if (this._h) {
        this._h.callService("mqtt", "publish", { topic: "flight_watcher/pilot/set", payload: JSON.stringify(e.detail) });
        this._paint(true);
        this.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    });
  }
  set hass(h) {
    this._h = h;
    const st = h.states[this._config.entity];
    const sig = st ? st.last_updated : "";
    if (sig === this._sig && this._root) return;
    this._sig = sig;
    this._paint();
  }
  getCardSize() { return 8; }
  _recon(a, readable) {  // FW-0002: the crew index's rebuilt month, drawn in the same grid as a readable schedule
    const r = a.reconstructed || [];
    const cov = a.reconstructed_coverage_pct;
    if (!r.length) return cov != null ? `<div class="u" style="margin-top:6px">Crew index: no trips found for this pilot in ${this._esc(a.reconstructed_month || "")} yet (${this._esc(cov)}% of trips read).</div>` : "";
    const g = this._rebuild(a);
    const [y, m] = String(a.reconstructed_month || "").split("-").map(Number);
    const mon = m >= 1 && m <= 12 ? `${MONTHS[m - 1]} ${y}` : (a.reconstructed_month || "");
    const head = `<b>Reconstructed from pairing crew lists</b> <span class="u">${this._esc(mon)} · ${this._esc(cov)}% of trips read · updated 00/06/12/18 HST</span>`;
    const tot = g.items.filter((it) => it.start >= g.from);  // totals: trips in the bid period, as drawn (not the day-before row, not the overlaps below)
    const sum = (k) => { let t = 0; for (const it of tot) { const x = /^(\d+):(\d{2})$/.exec(it[k] || ""); if (!x) return "?"; t += +x[1] * 60 + +x[2]; } return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, "0")}`; };
    const md = (d) => `${MONTHS[+d.slice(5, 7) - 1].slice(0, 3)} ${+d.slice(8)}`;
    const days = (x) => (x.start === x.end ? md(x.start) : x.start.slice(0, 7) === x.end.slice(0, 7) ? `${md(x.start)}-${+x.end.slice(8)}` : `${md(x.start)}-${md(x.end)}`);
    const also = g.also.length ? `<div class="u also">Also on crew lists, on days of a trip above (one of them was likely traded after it was read): ${g.also.map((x) => `<b>${this._esc(x.pairing)}</b> ${days(x)}${x.seat ? " " + this._esc(x.seat) : ""}${x.checked_at ? ", read " + this._esc(String(x.checked_at).slice(5, 16).replace("T", " ")) : ""}`).join(" · ")}</div>` : "";
    const left = [g.also.length ? `+${g.also.length} overlapping` : "", g.items.length > tot.length ? `+${g.items.length - tot.length} before ${md(g.from)}` : ""].filter(Boolean);
    const body = g.items.length ? `${this._grid(g.days, g.items, g.month)}${also}
      <div class="tot"><span>Trips<b>${tot.length}</b>${left.length ? ` <small class="u">(${left.join(", ")}: not totaled)</small>` : ""}</span><span>Block<b>${sum("blk")}</b></span><span>Credit<b>${sum("credit")}</b></span><span class="u">Source: crew lines on FLICA pairing pages (crew index, read only); Block / Credit / layover from the pairing package, blank where it has none. A trip picked up or dropped after it was read shows as it was then.</span></div>` : "";
    return readable ? `<details class="rb"><summary>${head}</summary>${body}</details>` : `<div class="rb"><div class="rbh">${head}</div>${body}</div>`;
  }
  _rebuild(a) {  // FW-0002: reconstructed trips -> the readable schedule's {days: [[iso, code, lay]], items} shape, plus also (overlaps)
    const ok = (d) => /^\d{4}-\d{2}-\d{2}$/.test(d || "");
    const cmp = (u, v) => (u < v ? -1 : u > v ? 1 : 0);
    const month = /^\d{4}-\d{2}$/.test(a.reconstructed_month || "") ? a.reconstructed_month : "";
    const add = (d, n) => { const t = new Date(d + "T00:00:00Z"); t.setUTCDate(t.getUTCDate() + n); return t.toISOString().slice(0, 10); };
    if (!month) return { month, from: "", days: [], items: [], also: [] };
    const [y, m] = month.split("-").map(Number);
    const from = ok(a.reconstructed_from) ? a.reconstructed_from : `${month}-01`;  // the bid period's first day
    const fd = a.month === month && Array.isArray(a.days) && a.days.length && ok((a.days[0] || [])[0]) && ok((a.days[a.days.length - 1] || [])[0]);
    let first = fd ? a.days[0][0] : add(from, -1);  // FLICA's grid starts on the day before the bid period: line up with it
    let last = fd ? a.days[a.days.length - 1][0] : ok(a.reconstructed_to) ? a.reconstructed_to : "";  // and ends on its last day (Dec 1 for November)
    // The crew index can hold two trips on the same days (a trade between reads): newest read goes in the grid, the rest in `also`
    const used = {}, trips = [], also = [];
    const all = (a.reconstructed || []).filter((x) => x && x.pairing && ok(x.start)).map((x) => ({ ...x, end: ok(x.end) && x.end >= x.start ? x.end : x.start }));
    all.sort((p, q) => cmp(q.checked_at || "", p.checked_at || "") || cmp(p.start, q.start) || cmp(p.pairing, q.pairing));
    for (const x of all) {
      const ds = []; for (let d = x.start, k = 0; d <= x.end && k < 15; d = add(d, 1), k++) ds.push(d);
      if (ds.some((d) => used[d])) { also.push(x); continue; }
      for (const d of ds) used[d] = 1;
      trips.push(x);
    }
    trips.sort((p, q) => cmp(p.start, q.start)); also.sort((p, q) => cmp(p.start, q.start) || cmp(p.pairing, q.pairing));
    if (!last) { last = new Date(Date.UTC(y, m, 0)).toISOString().slice(0, 10); for (const x of trips) if (x.end > last) last = x.end; }  // a publish without reconstructed_to
    for (const x of trips) { if (x.start < first) first = x.start; if (x.start > last) last = x.end; }  // never drop a trip; one running past the end stays open at the bottom, like FLICA's
    const at = {}, items = [];
    for (const x of trips) {
      const st = String(x.route || "").split("-").filter(Boolean);
      const base = st[0] || "HNL";
      const outs = [...new Set(st.filter((s) => s !== base))];
      const lay = x.start === x.end ? base : (x.lay || (outs.length === 1 ? outs[0] : ""));  // out and back: the one outstation
      for (let d = add(x.start, 1), k = 0; d <= x.end && k < 14; d = add(d, 1), k++) if (!(at[d] && at[d][0])) at[d] = ["", d === x.end ? base : "-"];
      at[x.start] = [x.pairing, lay];
      items.push({ trip: x.pairing, start: x.start, end: x.end, blk: x.blk || "", credit: x.credit || "", soft: x.soft || "", crew: x.crew || [],
        legs: st.slice(1).map((s, i) => ({ route: `${st[i]}-${s}` })), seat: x.seat || "", read: x.checked_at || "" });
    }
    const days = [];
    for (let d = first, k = 0; d <= last && k < 45; d = add(d, 1), k++) days.push([d, ...(at[d] || ["", ""])]);
    return { month, from, days, items, also };
  }
  _esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }
  _hol(iso) {
    const [y, m, d] = iso.split("-").map(Number);
    const nth = (mo, dow, n) => { const f = new Date(Date.UTC(y, mo - 1, 1)).getUTCDay(); return 1 + ((dow - f + 7) % 7) + (n - 1) * 7; };
    const last = (mo, dow) => { const l = new Date(Date.UTC(y, mo, 0)); return l.getUTCDate() - ((l.getUTCDay() - dow + 7) % 7); };
    const list = [[1, 1], [1, nth(1, 1, 3)], [2, nth(2, 1, 3)], [5, last(5, 1)], [6, 19], [7, 4], [9, nth(9, 1, 1)], [10, nth(10, 1, 2)], [11, 11], [11, nth(11, 4, 4)], [12, 25]];
    return list.some(([mo, dd]) => mo === m && dd === d);
  }
  _paint(loading) {
    if (!this._root) {
      this._root = this.attachShadow({ mode: "open" });
      this._root.innerHTML = `<style>
        ha-card{padding:10px 8px 12px;font-size:12.5px;line-height:1.25;box-sizing:border-box}
        .hd{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:0 0 6px}
        h3{margin:0;font-size:16px}.u{font-size:11px;color:var(--secondary-text-color)}
        .x{margin-left:auto;cursor:pointer;font-size:18px;line-height:1;padding:2px 8px;border-radius:6px;color:var(--secondary-text-color)}.x:hover{background:rgba(0,0,0,.06)}
        .wrap{overflow-x:auto;-webkit-overflow-scrolling:touch}
        table{border-collapse:collapse;margin:0 auto}
        .cal{border:1px solid var(--divider-color)}
        .cal td{padding:1px 6px;white-space:nowrap;vertical-align:top;border-left:1px solid var(--divider-color,#e0e0e0);border-bottom:1px solid var(--divider-color,#e0e0e0)}
        .cal th{padding:2px 6px;font-size:10.5px;font-weight:600;text-align:left;color:var(--secondary-text-color);border-bottom:1px solid var(--divider-color);border-left:1px solid var(--divider-color,#e0e0e0);white-space:nowrap}
        .cal td:first-child,.cal th:first-child,.cal td:nth-child(2){border-left:none}
        .cal td.n{text-align:right;padding-right:10px}
        .cal tr.wk td:nth-child(1),.cal tr.wk td:nth-child(2){background:#dde6f3;color:#1f2a44}
        .cal tr.hol td:nth-child(1),.cal tr.hol td:nth-child(2){background:#fff0a8;color:#4e3b00}
        .cal tr.oth td:nth-child(1),.cal tr.oth td:nth-child(2){opacity:.6}
        .cal tr.bx td:nth-child(4){box-shadow:inset 2px 0 0 #444,inset -2px 0 0 #444}
        .cal tr.bxs td:nth-child(4){box-shadow:inset 2px 0 0 #444,inset -2px 0 0 #444,inset 0 2px 0 #444}
        .cal tr.bxe td:nth-child(4){box-shadow:inset 2px 0 0 #444,inset -2px 0 0 #444,inset 0 -2px 0 #444}
        .cal tr.bxs.bxe td:nth-child(4){box-shadow:inset 2px 0 0 #444,inset -2px 0 0 #444,inset 0 2px 0 #444,inset 0 -2px 0 #444}
        .trip{font-weight:700;color:var(--primary-color)}
        .crew{font-size:11px;color:var(--secondary-text-color)}
        .legs{font-size:10.5px;color:var(--secondary-text-color)}
        .tot{margin:6px 0 0;font-size:12px}.tot b{margin-left:4px}.tot span{margin-right:14px}
        .none{padding:8px;color:var(--secondary-text-color)}
        .rb{margin-top:10px}.rbh{margin:0 0 4px}details.rb summary{cursor:pointer;margin:0 0 4px}.also{margin:6px 0 0}.also b{color:var(--primary-text-color)}
        .picks{display:flex;flex-wrap:wrap;gap:6px;margin:4px 0}
        .pk{padding:6px 10px;border:1px solid var(--divider-color,#ccc);border-radius:6px;background:var(--card-background-color,#fff);color:var(--primary-text-color);cursor:pointer;font-size:13px}
        @media (prefers-color-scheme: dark){
          .cal tr.bx td:nth-child(4){box-shadow:inset 2px 0 0 #bbb,inset -2px 0 0 #bbb}
          .cal tr.bxs td:nth-child(4){box-shadow:inset 2px 0 0 #bbb,inset -2px 0 0 #bbb,inset 0 2px 0 #bbb}
          .cal tr.bxe td:nth-child(4){box-shadow:inset 2px 0 0 #bbb,inset -2px 0 0 #bbb,inset 0 -2px 0 #bbb}
          .cal tr.bxs.bxe td:nth-child(4){box-shadow:inset 2px 0 0 #bbb,inset -2px 0 0 #bbb,inset 0 2px 0 #bbb,inset 0 -2px 0 #bbb}}
        @media (max-width:700px){ha-card{font-size:10.5px;padding:6px 3px 8px}.cal td{padding:1px 3px}}
      </style><ha-card><div class="body"></div></ha-card>`;
      this._root.addEventListener("click", (e) => {
        if (e.target.closest(".x")) { this._hidden = true; this._paint(); return; }
        const pk = e.target.closest(".pk");
        if (pk) window.dispatchEvent(new CustomEvent("flight-watcher-pilot", { detail: { emp: pk.dataset.emp, name: pk.dataset.name } }));
      });
    }
    const body = this._root.querySelector(".body");
    const st = this._h && this._h.states[this._config.entity];
    const a = (st && st.attributes) || {};
    if (this._hidden || (!a.emp && !a.status && !loading)) { body.innerHTML = ""; this.style.display = "none"; return; }  // v4: a "no match" or pick-list reply shows too
    this.style.display = "";
    const name = a.name || "";
    const emp = a.emp || this._want || "";
    if (loading || a.status === "loading") {
      body.innerHTML = `<div class="hd"><h3>${this._esc(name || "Pilot")} (${this._esc(emp)})</h3><span class="u">reading this pilot's month from FLICA (Schedule Lookup, read only), 20 to 40 s</span><span class="x" title="close">&times;</span></div>`;
      return;
    }
    if (!a.month) {
      const picks = (a.matches || []).map((m) => `<button class="pk" data-emp="${this._esc(m.emp)}" data-name="${this._esc(m.name)}">${this._esc(m.name)} <span class="u">${this._esc(m.pos)} ${this._esc(m.emp)}</span></button>`).join("");
      body.innerHTML = `<div class="hd"><h3>${this._esc(name || "Pilot")}${emp ? " (" + this._esc(emp) + ")" : ""}</h3><span class="u">${this._esc(/application error|customer care/i.test(a.status || "") ? "FLICA showed its error page for this schedule (often a pilot who has hidden it, or a FLICA hiccup). Nothing to read; try again later." : (a.status || "no data"))}</span><span class="x" title="close">&times;</span></div>${picks ? `<div class="picks">${picks}</div>` : ""}`;
      body.insertAdjacentHTML("beforeend", this._recon(a, false));  // 0.10.1 crew index; FW-0002: in the schedule grid
      return;
    }
    const [y, m] = a.month.split("-").map(Number);
    const t = a.totals || {};
    body.innerHTML = `<div class="hd"><h3>${this._esc(name)} (${this._esc(emp)})</h3><span class="u">${MONTHS[m - 1]} ${y} · FLICA updated ${this._esc(a.updated || "?")} · read ${a.fetched ? new Date(a.fetched).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : ""}${a.status === "cached" ? " (cached)" : ""}</span><span class="x" title="close">&times;</span></div>
      ${this._grid(a.days, a.items || [], a.month)}
      <div class="tot"><span>Block<b>${this._esc(t.block || "?")}</b></span><span>Credit<b>${this._esc(t.credit || "?")}</b></span><span>Days Off<b>${t.days_off != null ? t.days_off : "?"}</b></span><span class="u">Source: FLICA Tools > Schedule Lookup, read only. Block / Credit per trip from the pairing pages.</span></div>`;
    body.insertAdjacentHTML("beforeend", this._recon(a, true));  // 0.10.1: crew index (reconstructed from pairing crew lists), folded under a readable month
  }
  _grid(days, items, month) {  // the calendar: one row per day, trips boxed in the Layover column (readable and rebuilt months)
    const byStart = {}; for (const it of items) byStart[it.start] = it;
    const span = (d) => items.find((it) => /^[A-Z]\d{4}/.test(it.trip) && it.start <= d && d <= it.end);
    let rows = "";
    for (const [d, code, lay] of days || []) {
      const dt = new Date(d + "T00:00:00");
      const wk = dt.getDay() === 0 || dt.getDay() === 6;
      const oth = d.slice(0, 7) !== month;
      const tr = span(d);
      const bx = tr ? " bx" + (tr.start === d ? " bxs" : "") + (tr.end === d ? " bxe" : "") : "";
      const it = byStart[d];
      let tripCell = "", layCell = "", blk = "", cr = "", soft = "", crew = "";
      if (code) {
        const read = it && it.read ? ` title="crew read ${this._esc(String(it.read).slice(5, 16).replace("T", " "))} HST"` : "";
        tripCell = /^[A-Z]\d{4}/.test(code) ? `<span class="trip"${read}>${this._esc(code)}</span>` : this._esc(code);
        if (it && it.legs && it.legs.length) {
          tripCell += ` <span class="legs" title="${this._esc(it.legs.map((l) => [l.dow, l.route, l.dep && l.arr ? `${l.dep}-${l.arr}` : "", l.blk].filter(Boolean).join(" ")).join("\n"))}">${it.legs.length} legs</span>`;
        }
        if (it && it.seat) tripCell += ` <span class="legs" title="seat on the crew list">${this._esc(it.seat)}</span>`;
      }
      if (lay && lay !== "-") layCell = lay === "HNL" ? `<span class="u">HNL</span>` : `<b>${this._esc(lay)}</b>`;
      if (it && /^[A-Z]\d{4}/.test(it.trip)) {
        blk = this._esc(it.blk || ""); cr = this._esc(it.credit || ""); soft = this._esc(it.soft || "");
        crew = (it.crew || []).map(([p, n]) => `${this._esc(p)} ${this._esc(n)}`).join(" · ");
      }
      rows += `<tr class="${wk ? "wk" : ""}${this._hol(d) ? " hol" : ""}${oth ? " oth" : ""}${bx}"><td>${DOW[dt.getDay()]}</td><td class="n">${d.slice(8)}</td><td>${tripCell}</td><td>${layCell}</td><td class="n">${blk}</td><td class="n">${cr}</td><td class="n">${soft}</td><td class="crew">${crew}</td></tr>`;
    }
    return `<div class="wrap"><table class="cal"><thead><tr><th></th><th></th><th>Trip</th><th>Layover</th><th>Block</th><th>Credit</th><th>Soft</th><th>Crew</th></tr></thead><tbody>${rows}</tbody></table></div>`;
  }
}
customElements.define("flight-watcher-pilot-card", FlightWatcherPilotCard);
window.customCards = window.customCards || [];
window.customCards.push({ type: "flight-watcher-pilot-card", name: "Flight Watcher pilot schedule", description: "A tapped pilot's month" });
