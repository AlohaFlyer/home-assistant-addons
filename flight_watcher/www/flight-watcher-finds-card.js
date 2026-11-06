// Flight Watcher finds card (0.9.4, Ryan; 1.1.1 FW-0001: month picker pinned top-right so the table gets the
// card's full width on a phone, times built from parts; FW-0005: only today's finds (HST) show, the rest of the
// month folds under "N earlier this month" in the same table, fold remembered per browser): "Recently added to the
// pot" with a month picker. A past month picked in the picker opens in full. Live rows: sensor.flight_watcher_finds;
// month history (24 months): /local/flight-watcher/finds_<YYYY-MM>_<key>.json written by the Watcher. Times HST.
// FW-0010: HA serves /local/ with no login and the files name crew, so their names carry a random key that only the
// sensor's file_key attribute (behind HA's login) tells. FW-0026: the sensor keeps a short list of short rows (HA's
// recorder limit), so the month file is the full source and a sensor row only adds to it (a new find, a fresher
// pickup); a sensor change inside the 60 s refetch guard schedules one refetch when it ends.
class FlightWatcherFindsCard extends HTMLElement {
  setConfig(c) { this._c = { entity: "sensor.flight_watcher_finds", ...c }; this._files = {}; this._m = this._hstMonth(Date.now()); }
  getCardSize() { return 8; }
  _hstMonth(ms) { return new Date(ms - 10 * 3600e3).toISOString().slice(0, 7); }
  _hstDay(ms) { return new Date(ms - 10 * 3600e3).toISOString().slice(0, 10); }  // HST is UTC-10 all year
  // FW-0005: the "earlier this month" fold, closed until opened; remembered per browser (try/catch: private mode,
  // blocked storage). The key starts flight_watcher_, so a second pilot's copy gets a key of its own.
  _earlierOpen() {
    if (this._earlier === undefined) { let v = null; try { v = localStorage.getItem("flight_watcher_finds_earlier"); } catch (e) { v = null; } this._earlier = v === "1"; }
    return this._earlier;
  }
  _setEarlier(open) {
    if (open === this._earlierOpen()) return;
    this._earlier = open;
    try { localStorage.setItem("flight_watcher_finds_earlier", open ? "1" : "0"); } catch (e) { /* not saved, still works */ }
  }
  _e(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]); }
  set hass(h) {
    this._h = h;
    const st = h.states[this._c.entity];
    // FW-0005: the HST day is in the signature, so the first hass push after midnight HST redraws: "today" moves on
    // (and on the 1st the month) even when the finds sensor itself has not changed overnight.
    const sig = `${st ? st.last_updated : "none"}|${this._hstDay(Date.now())}`;
    if (sig === this._sig) return;
    this._sig = sig;
    // FW-0010: the files' key; a new key (first push, or a reset /data) drops every file read under the old one
    const key = st && st.attributes ? st.attributes.file_key || "" : "";
    if (key !== (this._key || "")) { this._key = key; this._files = {}; clearTimeout(this._later); }
    // FW-0005: left on this month, the card moves on with the clock (a past month opens in full, so a page open
    // over the month's end would otherwise show all of last month); a month picked in the picker stays.
    if (!this._picked) this._m = this._hstMonth(Date.now());
    if (this._m === this._hstMonth(Date.now())) this._load(this._m, true);
    this._render();
  }
  disconnectedCallback() { clearTimeout(this._later); }
  async _load(m, force) {
    const files = this._files;
    if (files[m] && !force) return;
    // FW-0010: no key yet (sensor not published, Watcher down): no fetch; the sensor rows show, and the key's arrival
    // clears this entry (set hass), which loads the file
    if (!this._key) { files[m] = { finds: [], at: 0, missing: true }; return; }
    if (files[m] && force) {
      const wait = 60e3 - (Date.now() - (files[m].at || 0));
      if (wait > 0) {  // FW-0026: refetch once the guard ends, so the file catches up with a sensor change made inside it
        clearTimeout(this._later);
        this._later = setTimeout(() => { if (this._m === m) this._load(m, true); }, wait + 500);
        return;
      }
    }
    // one fetch per month at a time (set hass and the first draw both ask for this month's file)
    const busy = this._busy || (this._busy = new Set()), tag = `${this._key}|${m}`;
    if (busy.has(tag)) return;
    busy.add(tag);
    let f;
    try {
      const r = await fetch(`/local/flight-watcher/finds_${m}_${encodeURIComponent(this._key)}.json?t=${Date.now()}`, { cache: "no-store" });
      f = r.ok ? { ...(await r.json()), at: Date.now() } : { finds: [], at: Date.now(), missing: true };
    } catch (e) { f = { finds: [], at: Date.now(), missing: true }; }
    busy.delete(tag);
    if (files !== this._files) return;  // the key changed while this was in flight
    files[m] = f;
    this._render();
  }
  _t(iso) {
    // 1.1.1 (FW-0001): built from parts, so every browser shows "Nov 5 12:23" (iOS Safari's
    // toLocaleString says "Nov 5 at 12:23", which widened every row); h23 keeps midnight as 00:xx.
    if (!iso) return "";
    const d = new Date(iso);
    if (isNaN(d)) return this._e(iso);
    const p = {};
    for (const x of new Intl.DateTimeFormat("en-US", { timeZone: "Pacific/Honolulu", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).formatToParts(d)) p[x.type] = x.value;
    return `${p.month} ${p.day} ${p.hour}:${p.minute}`;
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
    // FW-0026: a sensor row is short (no Pickup Speed, InFlt, Prem fields), so it updates the file's row, never replaces it
    for (const f of live) if (this._hstMonth(Date.parse(f.seen)) === this._m) { const k = `${f.pairing}|${f.seen}`; byKey.set(k, { ...(byKey.get(k) || {}), ...f }); }
    return [...byKey.values()].sort((a, b) => Date.parse(b.seen) - Date.parse(a.seen));
  }
  _split(all, now) {
    // FW-0005: rows first seen today (HST calendar day) and the rest; a row without a readable time counts as earlier.
    const day = this._hstDay(now), today = [], earlier = [];
    for (const f of all) { const t = Date.parse(f.seen); (!isNaN(t) && this._hstDay(t) === day ? today : earlier).push(f); }
    return { today, earlier };
  }
  _list(all, now, loading) {
    // FW-0005 (Ryan): this month shows today's finds (HST) only; every earlier one folds under one line. A past month
    // picked in the picker has no today: picking it is the ask to see it, so its table opens in full (a fold there
    // would only repeat the header count and cost a second tap).
    const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    const [y, m] = this._m.split("-").map(Number);
    const head = `<tr><th>Seen</th><th>Picked up</th><th>Trip</th><th>Dates</th><th>Layover</th><th>Days</th><th>Credit</th><th>CA</th><th>Picked up by</th><th>InFlt</th><th>Pickup Speed</th><th>Prem</th></tr>`;
    const rows = (a) => a.map((f) => this._row(f)).join("");
    if (this._m !== this._hstMonth(now)) return all.length ? `<div class="wrap"><table><thead>${head}</thead><tbody>${rows(all)}</tbody></table></div>` : (loading ? "" : `<div class="k">Nothing added in ${MON[m - 1]} ${y}.</div>`);
    const { today, earlier } = this._split(all, now);
    const d = this._hstDay(now);
    const h = today.length || loading ? "" : `<div class="k">Nothing new today (${MON[+d.slice(5, 7) - 1]} ${+d.slice(8, 10)} HST).</div>`;
    if (!today.length && !earlier.length) return h;
    // One table: today's rows and the folded ones share column widths and one sideways scroll on a phone. The fold
    // line is a row of its own (a button: tap, keyboard); the earlier rows are a tbody shown or hidden in place. With
    // nothing today the header row moves into the fold, so a closed fold is one line.
    const open = this._earlierOpen();
    const top = today.length ? `<thead>${head}</thead><tbody>${rows(today)}</tbody>` : "";
    const fold = earlier.length ? `<tbody class="fold"><tr><td colspan="12"><button type="button" class="fb" aria-expanded="${open}">${earlier.length} earlier this month</button></td></tr></tbody><tbody class="old"${open ? "" : " hidden"}>${today.length ? "" : head}${rows(earlier)}</tbody>` : "";
    return `${h}<div class="wrap"><table>${top}${fold}</table></div>`;
  }
  _render() {
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    if (!this._files[this._m]) this._load(this._m);
    const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    const [y, m] = this._m.split("-").map(Number);
    const all = this._rows();
    const loading = !this._files[this._m];
    const openTop = this._top !== false;
    this.shadowRoot.innerHTML = `<style>
      ha-card{padding:10px 14px;font-size:12.5px}
      .hd{position:relative}.hd summary{cursor:pointer;font-weight:700;font-size:14px;padding-right:140px}
      .mp{position:absolute;top:-4px;right:0;display:flex;align-items:center;gap:4px;font-weight:700;white-space:nowrap}.mp .nv{cursor:pointer;font-size:20px;color:var(--primary-color);padding:0 6px;user-select:none}
      .wrap{overflow-x:auto}table{border-collapse:collapse;width:100%;margin-top:6px}
      th,td{border:1px solid var(--divider-color);padding:4px 6px;text-align:left;white-space:nowrap}th{font-weight:700}
      td.n{text-align:right}td.c{text-align:center}
      tr.hid td{background:rgba(244,67,54,.14)}tr.prem td{background:rgba(76,175,80,.16)}
      a{color:var(--primary-color);text-decoration:underline}
      tbody.fold td{border:0;padding:0}
      .fb{position:sticky;left:0;appearance:none;-webkit-appearance:none;background:none;border:0;margin:0;padding:8px 6px 6px 0;font:inherit;font-size:13px;font-weight:600;color:var(--secondary-text-color);cursor:pointer;-webkit-tap-highlight-color:transparent}
      .fb::before{content:"\\25B6";display:inline-block;width:1.5em;font-size:.72em}.fb[aria-expanded="true"]::before{content:"\\25BC"}
      .key{margin-top:4px}.key summary{cursor:pointer;font-size:12px;color:var(--secondary-text-color)}
      .k{color:var(--secondary-text-color);font-size:12px;margin-top:6px}
      ha-icon{--mdc-icon-size:16px}
    </style><ha-card>
      <div class="hd"><details class="top"${openTop ? " open" : ""}><summary><ha-icon icon="mdi:new-box"></ha-icon> Recently added to the pot <span class="k">${all.length} in ${MON[m - 1]}</span></summary>
        ${loading ? `<div class="k">Loading ${MON[m - 1]} ${y}...</div>` : ""}
        ${this._list(all, Date.now(), loading)}
        <details class="key"><summary>Key</summary><div class="k">
          <div><ha-icon icon="mdi:email-outline"></ha-icon> caught from your FLICA alert email (gone before a pot check)</div>
          <div>InFlt <ha-icon icon="mdi:airplane"></ha-icon> = picked up while airborne (from the picker's own trip); no = on the ground; - = not checked yet</div>
          <div>Pickup Speed = how long the trip sat in open time, ± half the check window; ~ = timed from your alert email; bold under 1 min. Hover for the picker's average.</div>
          <div>Red row: seat still open but not in the pot (hidden?). Green row: Premium trip picked up.</div>
          <div>Today's finds (HST) show; the rest of the month folds under "earlier this month" (this device remembers it open or closed). A past month opens in full. History kept 24 months.</div></div></details>
      </details>
      <span class="mp"><span class="nv" data-m="-1">&#8249;</span>${MON[m - 1]} ${y}<span class="nv" data-m="1">&#8250;</span></span></div>
    </ha-card>`;
    const r = this.shadowRoot;
    r.querySelector("details.top").ontoggle = (e) => { this._top = e.target.open; };
    const fb = r.querySelector("button.fb");
    if (fb) fb.onclick = () => {
      // in place, no redraw: the sideways scroll and the Key stay where they are
      const open = !this._earlierOpen();
      this._setEarlier(open);
      fb.setAttribute("aria-expanded", String(open));
      r.querySelector("tbody.old").hidden = !open;
    };
    r.querySelectorAll("[data-m]").forEach((el) => el.onclick = () => {
      const d = new Date(Date.UTC(y, m - 1 + Number(el.dataset.m), 1));
      const nm = d.toISOString().slice(0, 7);
      if (nm > this._hstMonth(Date.now())) return;
      this._m = nm;
      this._picked = nm !== this._hstMonth(Date.now());
      this._render();
    });
  }
}
customElements.define("flight-watcher-finds-card", FlightWatcherFindsCard);
