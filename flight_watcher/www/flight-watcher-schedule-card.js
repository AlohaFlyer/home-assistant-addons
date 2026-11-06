// Flight Watcher: compact month schedule in FLICA's own layout (narrow, weekend rows shaded).
// Reads sensor.flight_watcher_schedule (months[YYYY-MM].days/items/totals), input_number.flight_watcher_month_offset,
// sensor.flight_watcher_pot_count (open trips starting each day: bold = fits, struck = clashes),
// sensor.flight_watcher_blocked_days (tap a day to block it) and, since v3 (Nov 2 2026):
//  - sensor.flight_watcher_own_trip_times (app 0.4.7+) and the monthly pairing package
//    /local/flight-watcher/pairings_YYYY-MM.json for report and release times of Ryan's own trips;
//  - tag-on suggestions: package pairings that operate on the release day or the day after and leave
//    the in-domicile rest Ryan needs (PWA 10.E.1.a: 11 h; 10.E.1.b: 18 h before a 12 h+ duty that
//    departs 1400-0359 local). Release = block-in + 15 min (PWA 2 Duty Period ends), report = 1 h
//    before departure in domicile. Also keeps 11 h before his next trip and skips VAC / blocked days.
// Pako HI, HOM t1218/t1225. Usage: type: custom:flight-watcher-schedule-card
const MONTHS = ["January","February","March","April","May","June","July","August","September","October","November","December"];
const DOW = ["SU","MO","TU","WE","TH","FR","SA"];
const MON3 = ["JAN","FEB","MAR","APR","MAY","JUN","JUL","AUG","SEP","OCT","NOV","DEC"];
const H = 3600e3;
// Pay (Ryan): hourly rate per credit hour; PWA 4.O.1.a IRO override $4.00 per block hour; 4.O.1.b Extended Range type-rated FO 15% hourly premium
const IRO_OVERRIDE = 4.00, ER_PCT = 0.15, DOH = "2000-01-01";  // FW_DOH: the add-on writes the pilot's date of hire here on deploy (cards.py)
const VAC_H = 4.0;  // PWA 6.J.1.c: vacation day Paid and Credited at 4:00 from 1 Jan 2026 (3.75 if the AA/DL/UA trigger had failed); FLICA's totals confirm 4:00
// PWA 3.D.6 A330 PAX / B787 First Officer hourly rate by longevity year (1-12) and effective date
const RATE_DATES = ["2023-03-02", "2024-03-02", "2025-03-02", "2026-03-02", "2027-01-31"];
const RATE_TABLE = [
  [81.00, 84.00, 87.00, 90.00, 93.00], [181.30, 188.55, 196.09, 203.93, 210.05], [208.37, 216.70, 225.37, 234.39, 241.42],
  [221.09, 229.94, 239.13, 248.70, 256.16], [230.29, 239.50, 249.08, 259.04, 266.81], [241.46, 251.12, 261.16, 271.61, 279.76],
  [251.28, 261.33, 271.79, 282.66, 291.13], [256.66, 266.93, 277.61, 288.71, 297.37], [262.48, 272.98, 283.90, 295.26, 304.12],
  [266.03, 276.67, 287.74, 299.24, 308.22], [270.00, 280.80, 292.03, 303.71, 312.82], [273.62, 284.56, 295.95, 307.78, 317.02]];
const rateFor = (year, iso) => { let i = 0; RATE_DATES.forEach((d, k) => { if (iso >= d) i = k; }); return RATE_TABLE[Math.min(12, Math.max(1, year)) - 1][i]; };
const dohYear = (iso) => Math.floor((Date.parse(iso) - Date.parse(DOH)) / (365.25 * 24 * H)) + 1;
const hrs = (t) => { const mm = /^(\d+):(\d{2})$/.exec(String(t || "").trim()); return mm ? Number(mm[1]) + Number(mm[2]) / 60 : null; };
const usd = (v) => (v == null ? "" : "$" + Math.round(v).toLocaleString("en-US"));

class FlightWatcherScheduleCard extends HTMLElement {
  setConfig(c) { this.c = c || {}; this._pk = {}; }
  set hass(h) {
    const sig = ["sensor.flight_watcher_schedule", "input_number.flight_watcher_month_offset", "sensor.flight_watcher_pot_count",
      "sensor.flight_watcher_blocked_days", "sensor.flight_watcher_own_trip_times", "sensor.flight_watcher_tradeboard_pickups",
      "sensor.flight_watcher_would_trade", "sensor.flight_watcher_swap_ideas", "sensor.flight_watcher_reserve_grid",
      "input_number.flight_watcher_federal_tax_pct", "input_number.flight_watcher_state_tax_pct", "input_number.flight_watcher_longevity_year", "input_text.flight_watcher_er_trips", "sensor.flight_watcher_schedule_versions"]
      .map((e) => h.states[e] && h.states[e].last_updated).join("|");
    this._h = h;
    if (sig === this._sig) return;
    this._sig = sig;
    this._render();
  }
  _key() {
    const off = parseInt((this._h.states["input_number.flight_watcher_month_offset"] || {}).state || "0", 10) || 0;
    const d = new Date(); const m = d.getMonth() + off; const y = d.getFullYear() + Math.floor(m / 12);
    return { y, m: ((m % 12) + 12) % 12, key: `${y}-${String(((m % 12) + 12) % 12 + 1).padStart(2, "0")}` };
  }
  _iso(s, y) { // '26Nov' -> '2026-11-26'
    const mm = MON3.indexOf((s || "").slice(2, 5).toUpperCase()); if (mm < 0) return "";
    return `${y}-${String(mm + 1).padStart(2, "0")}-${(s || "").slice(0, 2)}`;
  }
  // US federal holidays (observed on the actual date): yellow day/date cells
  _hol(iso) {
    const [y, m, d] = iso.split("-").map(Number);
    const nth = (mo, dow, n) => { const f = new Date(Date.UTC(y, mo - 1, 1)).getUTCDay(); return 1 + ((dow - f + 7) % 7) + (n - 1) * 7; };
    const last = (mo, dow) => { const l = new Date(Date.UTC(y, mo, 0)); return l.getUTCDate() - ((l.getUTCDay() - dow + 7) % 7); };
    if (m === 1 && (d === 1 || d === nth(1, 1, 3))) return true;
    if (m === 2 && d === nth(2, 1, 3)) return true;
    if (m === 5 && d === last(5, 1)) return true;
    if (m === 6 && d === 19) return true;
    if (m === 7 && d === 4) return true;
    if (m === 9 && d === nth(9, 1, 1)) return true;
    if (m === 10 && d === nth(10, 1, 2)) return true;
    if (m === 11 && (d === 11 || d === nth(11, 4, 4))) return true;
    if (m === 12 && d === 25) return true;
    // Hawaii state holidays (Ryan, Nov 3 2026): Prince Kuhio Mar 26, Good Friday, Kamehameha Jun 11, Statehood 3rd Fri Aug
    if (m === 3 && d === 26) return true;
    if (m === 6 && d === 11) return true;
    if (m === 8 && d === nth(8, 5, 3)) return true;
    const e = this._easter(y); const gf = new Date(Date.UTC(y, e[0] - 1, e[1] - 2));
    if (m === gf.getUTCMonth() + 1 && d === gf.getUTCDate()) return true;
    return false;
  }
  _easter(y) { // Anonymous Gregorian algorithm -> [month, day]
    const a = y % 19, b = Math.floor(y / 100), c = y % 100, dd = Math.floor(b / 4), e = b % 4, f = Math.floor((b + 8) / 25), g = Math.floor((b - f + 1) / 3);
    const h = (19 * a + b - dd - g + 15) % 30, i = Math.floor(c / 4), k = c % 4, l = (32 + 2 * e + 2 * i - h - k) % 7, mm = Math.floor((a + 11 * h + 22 * l) / 451);
    const month = Math.floor((h + l - 7 * mm + 114) / 31), day = ((h + l - 7 * mm + 114) % 31) + 1;
    return [month, day];
  }
  _esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }
  // wall-clock HST as a UTC-based ms value (no time zone maths: everything is HNL local)
  _t(iso, hhmm) { const [h, m] = String(hhmm || "0:0").split(":").map((x) => parseInt(x, 10) || 0); return Date.parse(iso + "T00:00:00Z") + (h * 60 + m) * 60e3; }
  _d(ms) { return new Date(ms).toISOString().slice(0, 10); }
  _hm(ms) { return new Date(ms).toISOString().slice(11, 16); }
  _dur(ms) { const m = Math.round(ms / 60e3); return `${Math.floor(m / 60)}:${String(m % 60).padStart(2, "0")}`; }
  _school(iso) {
    // school year starts in July: 2026-07-01 .. 2027-06-30 -> school_2026-27.json (swaps by itself each July)
    const y = parseInt(iso.slice(0, 4), 10), m = parseInt(iso.slice(5, 7), 10);
    const sy = m >= 7 ? y : y - 1; const key = `${sy}-${String((sy + 1) % 100).padStart(2, "0")}`;
    this._sc = this._sc || {};
    if (this._sc[key] !== undefined) return this._sc[key];
    this._sc[key] = null;
    fetch(`/local/flight-watcher/school_${key}.json?v=1`, { cache: "no-cache" }).then((r) => (r.ok ? r.json() : false)).then((j) => {
      if (!j) { this._sc[key] = false; return; }
      const days = new Set(j.closed || []);
      for (const [a, b] of (j.ranges || [])) { for (let t = Date.parse(a + "T00:00:00Z"); t <= Date.parse(b + "T00:00:00Z"); t += 864e5) days.add(new Date(t).toISOString().slice(0, 10)); }
      this._sc[key] = { name: j.name || key, days }; this._sig = null; this.hass = this._h;
    }).catch(() => { this._sc[key] = false; });
    return null;
  }
  _pack(key) {
    if (this._pk[key] !== undefined) return this._pk[key];
    this._pk[key] = null;
    fetch(`/local/flight-watcher/pairings_${key}.json?v=1`, { cache: "no-cache" }).then((r) => (r.ok ? r.json() : null)).then((j) => {
      if (!j) { this._pk[key] = false; return; }
      const [y, mo] = key.split("-").map(Number);
      const nxt = new Date(Date.UTC(y, mo, 1)).toISOString().slice(0, 7);
      const ix = Object.fromEntries(j.cols.map((c, i) => [c, i]));
      const map = {};
      for (const r of j.rows) {
        const days = String(r[ix.days]).split(" ").filter(Boolean)
          .map((d) => (d[0] === "D" ? `${nxt}-${d.slice(1).padStart(2, "0")}` : `${key}-${d.padStart(2, "0")}`));
        map[r[ix.id]] = { id: r[ix.id], report: r[ix.report], dep: r[ix.dep], release: r[ix.release], relDays: r[ix.rel_days],
          firstDuty: r[ix.first_duty_min], route: r[ix.route], credit: r[ix.credit], tafb: r[ix.tafb], days: new Set(days),
          block: ix.block != null ? r[ix.block] : "", crew: ix.crew != null ? r[ix.crew] : "" };
      }
      this._pk[key] = map; this._sig = null; this.hass = this._h;
    }).catch(() => { this._pk[key] = false; });
    return null;
  }
  _say(msg) { const box = this.shadowRoot.querySelector(".info"); if (box) { box.textContent = msg; box.style.whiteSpace = "pre-line"; box.style.display = "block"; } }
  _render() {
    if (this._locked === undefined) { let v = "1"; try { const g = localStorage.getItem("flight_watcher_lock"); v = g === null ? "1" : g; } catch (e) { v = "1"; } this._locked = v !== "0"; }  // v48: locked by default
    if (!this.shadowRoot) {
      this.attachShadow({ mode: "open" });
      this.shadowRoot.addEventListener("click", (e) => {
        const vb = e.target.closest(".vb");  // v51: schedule versions
        if (vb) { const k = this._key().key; const n = (((((this._h.states["sensor.flight_watcher_schedule_versions"] || {}).attributes || {}).months || {})[k] || {}).versions || []).length;
          let i = this._vsel && this._vsel[k] != null ? this._vsel[k] : n - 1; const a = vb.dataset.v;
          i = a === "home" ? n - 1 : a === "prev" ? Math.max(0, i - 1) : Math.min(n - 1, i + 1);
          this._vsel = this._vsel || {}; this._vsel[k] = i; this._sig = null; this._render(); return; }
        const ib2 = e.target.closest(".idb");  // v51: ideas panel below the schedule
        if (ib2) { const k = this._key().key; const cur = this._idea; this._idea = cur && cur.key === k && cur.d === ib2.dataset.d ? null : { key: k, d: ib2.dataset.d, trip: ib2.dataset.trip };
          this._render(); const pn = this.shadowRoot.querySelector(".ipanel"); if (pn) pn.scrollIntoView({ behavior: "smooth", block: "nearest" }); return; }
        if (e.target.closest(".ix")) { this._idea = null; this._render(); return; }
        const lk = e.target.closest(".lock");  // v48 (Ryan): lock / unlock the tap settings (blocked days, trade, drop)
        if (lk) { this._locked = !this._locked; try { localStorage.setItem("flight_watcher_lock", this._locked ? "1" : "0"); } catch (e2) { /* ignore */ } this._render(); return; }
        const locked = this._locked;
        const db = e.target.closest(".drb");
        if (db && locked) { this._say("Settings are locked: tap the lock at the top left to change availability, trade or drop marks."); return; }
        if (db && db.dataset.k) {
          db.classList.toggle("on");
          this._h.callService("mqtt", "publish", { topic: "flight_watcher/drop/set", payload: JSON.stringify({ key: db.dataset.k }) });
          return;
        }
        const tp = e.target.closest(".trip, .trb");
        if (tp && tp.dataset.k && tp.dataset.k.split("|")[1] <= new Date(Date.now() - 10 * H).toISOString().slice(0, 10)) return;  // v46: a started trip cannot be traded
        if (tp && tp.dataset.k && locked) { this._say("Settings are locked: tap the lock at the top left to change availability, trade or drop marks."); return; }
        if (tp && tp.dataset.k) {
          const row = tp.closest("td"); row.querySelector(".trip").classList.toggle("tr"); row.querySelector(".trb").classList.toggle("on");
          this._h.callService("mqtt", "publish", { topic: "flight_watcher/trade/set", payload: JSON.stringify({ key: tp.dataset.k }) });
          return;
        }
        const ib = e.target.closest(".info"); if (ib) { ib.style.display = "none"; return; }
        const er = e.target.closest(".er");
        if (er && er.dataset.k) {
          const cur = String((this._h.states["input_text.flight_watcher_er_trips"] || {}).state || "").split(",").filter(Boolean);
          const k = er.dataset.k, on = er.classList.contains("on");
          const next = cur.filter((x) => x.slice(1) !== k).concat(on ? ["-" + k] : ["+" + k]);
          this._h.callService("input_text", "set_value", { entity_id: "input_text.flight_watcher_er_trips", value: next.join(",") });
          return;
        }
        const nv = e.target.closest(".nav");
        if (nv) {
          const d = parseInt(nv.dataset.nav, 10), ent = { entity_id: "input_number.flight_watcher_month_offset" };
          if (d === 0) this._h.callService("input_number", "set_value", { ...ent, value: 0 });
          else this._h.callService("input_number", d > 0 ? "increment" : "decrement", ent);
          return;
        }
        const py = e.target.closest(".pay");
        if (py) { const box = this.shadowRoot.querySelector(".info"); if (box) { box.innerHTML = this._esc(py.dataset.info).replace(/\n/g, "<br>") + "<br>" + py.dataset.btn; box.style.display = "block"; } return; }
        const tg = e.target.closest(".tag");
        if (tg) { const box = this.shadowRoot.querySelector(".info"); if (box) { box.textContent = tg.title; box.style.whiteSpace = "pre-line"; box.style.display = "block"; } return; }
        if (e.target.closest(".set")) return;
        const tt = e.target.closest("span[title], th[title], b[title]");
        if (tt && tt.title) { const box = this.shadowRoot.querySelector(".info"); if (box) { box.textContent = tt.title; box.style.whiteSpace = "pre-line"; box.style.display = "block"; } return; }
        const dc = e.target.closest("td"); if (!dc || dc.cellIndex > 1) return;  // v43 (Ryan): only the day/date cells toggle a blocked day
        const tr = e.target.closest("tr[data-d]"); if (!tr || !this._h) return;
        if (tr.classList.contains("vac")) { this._say("Vacation day: always unavailable."); return; }  // v48 (Ryan): VAC days cannot be toggled
        if (locked) { this._say("Settings are locked: tap the lock at the top left to change availability, trade or drop marks."); return; }
        tr.classList.toggle("blk");
        this._h.callService("mqtt", "publish", { topic: "flight_watcher/blocked/set", payload: JSON.stringify({ date: tr.dataset.d }) });
      });
    }
    const S = this._h.states;
    const hm = (h) => { const mm = Math.round(h * 60); return `${Math.floor(mm / 60)}:${String(mm % 60).padStart(2, "0")}`; };
    const num = (e, d) => { const v = parseFloat((S[e] || {}).state); return isNaN(v) ? d : v; };
    const fed = num("input_number.flight_watcher_federal_tax_pct", 22), stt = num("input_number.flight_watcher_state_tax_pct", 0);
    const today = new Date(Date.now() - 10 * H).toISOString().slice(0, 10);
    const lyr = num("input_number.flight_watcher_longevity_year", Math.min(12, dohYear(today)));
    const RATE = rateFor(lyr, today);
    const erOv = String((S["input_text.flight_watcher_er_trips"] || {}).state || "").split(",").filter(Boolean);
    const erOn = (k, lay, n) => erOv.includes("-" + k) ? false : erOv.includes("+" + k) ? true : (n ? n >= 4 : /\bSIN\b/.test(lay || ""));
    // v51: pilots on the pairing from the package crew line (CA01FO01RO01 = 3 = IRO crew; CA02FO02 = 4 = Extended Range crew, PWA 2.A.25)
    const crewN = (c) => (String(c || "").match(/\d{2}/g) || []).reduce((a, x) => a + parseInt(x, 10), 0);
    const hx = (v) => hrs(String(v || "").replace("h", ":"));
    const blocked = new Set(((S["sensor.flight_watcher_blocked_days"] || {}).attributes || {}).days || []);
    const dropA = (S["sensor.flight_watcher_would_drop"] || {}).attributes || {};
    const dropM = new Set(dropA.keys || []), dropR = dropA.ready || {};
    const st = S["sensor.flight_watcher_schedule"];
    const { y, m, key } = this._key();
    let mon = st && st.attributes.months ? st.attributes.months[key] : null;
    // v51 (Ryan): schedule versions MM.NNN; arrows step through them, the house returns to the current one
    const VS = ((S["sensor.flight_watcher_schedule_versions"] || {}).attributes || {}).months || {};
    const vl = (VS[key] || {}).versions || [];
    this._vsel = this._vsel || {};
    let vi = this._vsel[key]; if (vi == null || vi < 0 || vi >= vl.length - 1) vi = null;
    const vsel = vi != null ? vl[vi] : null;
    const liveMon = mon;
    if (vsel && mon) mon = { ...mon, items: vsel.items || [], days: vsel.days || [], totals: vsel.totals || {}, updated: vsel.updated || "" };
    const pot = ((S["sensor.flight_watcher_pot_count"] || {}).attributes || {}).pairings || [];
    const tb = ((S["sensor.flight_watcher_tradeboard_pickups"] || {}).attributes || {}).pairings || [];
    const liveOwnT = ((S["sensor.flight_watcher_own_trip_times"] || {}).attributes || {}).trips || {};
    // v51c: a version keeps its own block / credit / times but inherits fields it never recorded (seat, crew) from the live
    // record of the same trip, so an early version of a trip still pays the seat override (PWA 4.O.1)
    const mergeT = (live, ver) => { const o = { ...live }; for (const [k, v] of Object.entries(ver || {})) o[k] = { ...(live[k] || {}), ...v }; return o; };
    const ownT = vsel ? mergeT(liveOwnT, vsel.trips) : liveOwnT;
    const pk = this._pack(key);
    const grid = ((S["sensor.flight_watcher_reserve_grid"] || {}).attributes || {}).days || {};
    const trade = new Set(((S["sensor.flight_watcher_would_trade"] || {}).attributes || {}).keys || []);
    const swaps = ((S["sensor.flight_watcher_swap_ideas"] || {}).attributes || {}).ideas || [];
    const swapFor = {};
    for (const i of swaps) (swapFor[i.for] = swapFor[i.for] || []).push(i);
    let body = "", note = "", chtml = "", vhtml = "", panel = "";
    if (!mon) {
      body = `<div class="none">No schedule for ${MONTHS[m]} yet.</div>`;
    } else {
      const items = mon.items || [];
      const busy = (a, b) => items.find((it) => a <= it.end && b >= it.start);
      const inTrip = (d) => items.some((it) => it.trip !== "VAC" && it.start <= d && d <= it.end);
      const opens = {};
      for (const p of pot) {
        const a = this._iso(p.start || (p.dates || "").split("-")[0], y);
        const b = this._iso(p.end || (p.dates || "").split("-")[1] || p.start, y) || a;
        if (!a) continue;
        const clash = busy(a, b) || ([...blocked].find((d) => a <= d && d <= b) ? { trip: "a blocked day" } : null);
        const city = (p.layover && !/none/i.test(p.layover)) ? p.layover : (p.turn || "");
        (opens[a] = opens[a] || []).push(`<span class="${clash ? "clash" : "fit"}" title="${clash ? "clashes with " + this._esc(clash.trip) : "fits"}">${city ? this._esc(city) : ""}(${this._esc(p.pairing)})</span>`);
      }
      // own trips: report / release (app times first, then the pairing package)
      const own = [];
      const prevKey = new Date(Date.UTC(y, m - 1, 1)).toISOString().slice(0, 7);
      const prevItems = (st.attributes.months[prevKey] || {}).items || [];
      const nextKey = new Date(Date.UTC(y, m + 1, 1)).toISOString().slice(0, 7);
      const nextItems = (st.attributes.months[nextKey] || {}).items || [];
      for (const it of [...prevItems, ...items, ...nextItems]) {
        if (it.trip === "VAC" || !/^[A-Z]\d{4}/.test(it.trip || "")) continue;
        const t = ownT[`${it.trip}|${it.start}`] || {};
        const p = pk ? pk[it.trip.slice(0, 5)] : null;
        let rep = null, rel = null;
        if (t.report) rep = this._t(it.start, t.report);
        else if (p && p.days.has(it.start)) rep = this._t(it.start, p.report);
        if (p && p.days.has(it.start)) rel = this._t(it.start, p.release) + p.relDays * 24 * H;
        else if (t.last_arr) {
          // trip not in the package: it ends on the first later day the schedule shows back in HNL
          const back = (mon.days || []).find(([d, tr, ly]) => d > it.start && !tr && ly === "HNL");
          const end = back ? back[0] : it.end;
          rel = this._t(end, t.last_arr) + 15 * 60e3; if (rep && rel <= rep) rel += 24 * H;
        }
        own.push({ it, rep, rel });
      }
      own.sort((a, b) => (a.it.start < b.it.start ? -1 : 1));
      const repOn = {}, relOn = {}, legalOn = {};
      for (const o of own) {
        if (o.rep) repOn[o.it.start] = this._hm(o.rep);
        if (o.rel) {
          relOn[this._d(o.rel)] = this._hm(o.rel);
          // legal to report for another trip: release + 11 h (PWA 10.E.1.a; covers FAR 117 10 h rest).
          // 18 h applies instead before a 12 h+ duty period departing 1400-0359 (PWA 10.E.1.b).
          const l11 = o.rel + 11 * H, l18 = o.rel + 18 * H;
          const dd = (ms) => (this._d(ms) === this._d(o.rel) ? "" : " +1");
          legalOn[this._d(o.rel)] = { t: this._hm(l11) + dd(l11), t18: this._hm(l18) + dd(l18), rel: this._hm(o.rel) };
        }
      }
      // Duty periods (app 0.4.15 `duties`: HST minutes from the trip's first day) or, without them, the whole trip.
      // Report = first departure - 1:00 (trip report when known), release = last arrival + 0:15 (PWA 2, 4.2.2).
      const duties = [];
      for (const o of own) {
        const t = ownT[`${o.it.trip}|${o.it.start}`] || {};
        const base = this._t(o.it.start, "0:0");
        if (t.duties && t.duties.length) {
          t.duties.forEach((du, k) => duties.push({
            start: k === 0 && o.rep ? o.rep : base + (du.dep - 60) * 60e3, end: base + (du.arr + 15) * 60e3, stn: du.stn, trip: o.it.trip }));
        } else if (o.rep && o.rel) duties.push({ start: o.rep, end: o.rel, stn: "", trip: o.it.trip });
      }
      // v49 (Ryan, Nov 5): training and reserve days are duty too (FAR 117.25(b) needs 30 h free from ALL duty): whole day HST.
      // VAC, SICK, GDO, O/K, RISK and other codes stay free.
      const DUTY_CODE = /^(SIM|OEB|OE\b|IOE|GS|GRD|TRN|TRG|TRAIN|CQ|RQ|PC|PT\b|LOE|LOFT|CBT|SCR|RSV|RES|SBY|ASB|AIR)/;
      for (const mk of Object.keys(st.attributes.months || {})) for (const it of (st.attributes.months[mk].items || [])) {
        if (!it.trip || /^[A-Z]\d{4}/.test(it.trip) || !DUTY_CODE.test(it.trip)) continue;
        duties.push({ start: this._t(it.start, "0:0"), end: this._t(it.end || it.start, "0:0") + 24 * H, stn: "", trip: it.trip });
      }
      duties.sort((a, b) => a.start - b.start);
      const nowHst = Date.now() - 10 * H;
      const mkeys = Object.keys(st.attributes.months || {}).sort();
      const dataStart = Date.parse((mkeys[0] || key) + "-01T00:00:00Z");
      const lastK = mkeys[mkeys.length - 1] || key;
      const dataEnd = Date.UTC(+lastK.slice(0, 4), +lastK.slice(5, 7), 1);
      // free windows between duties (and the open one after the last duty)
      const frees = [];
      for (let i = 0; i < duties.length; i++) {
        const a = duties[i].end, b = i + 1 < duties.length ? duties[i + 1].start : Infinity;
        if (b > a) frees.push({ a, b, at: duties[i].stn, after: duties[i].trip });
      }
      if (duties.length && duties[0].start > dataStart) frees.unshift({ a: dataStart, b: duties[0].start, at: "HNL", after: "" });
      // v50 (Ryan, Nov 5): mark EVERY 30 h+ break (FAR 117.25(b)), past and future; a long layover counts. Each break
      // covers any report up to 138 h after it ends (168 h look-back minus the 30 h it must fill).
      // FW-0004 (Ryan, Nov 6): no teal row background any more (FAR-30/7 carries the check and date); a thin teal edge
      // on the day cell is the only mark, and the date cell's hover still gives the break's window.
      const r30 = new Set(); const r30Notes = {};
      for (const f of frees) {
        const b = Math.min(f.b, dataEnd);
        if (b - f.a < 30 * H) continue;
        const txt = `30 h break: ${this._hm(f.a)} ${this._d(f.a)}${f.at && f.at !== "HNL" ? " at " + f.at : ""} to ${f.b >= dataEnd ? "end of schedule on file" : this._hm(f.b) + " " + this._d(f.b)}, ${f.b >= dataEnd ? "" : this._dur(f.b - f.a) + ", "}covers reports until ${f.b >= dataEnd ? "beyond the schedule on file" : this._hm(f.b + 138 * H) + " " + this._d(f.b + 138 * H)}`;
        for (let t = f.a; t < b; t += 24 * H) { const k = this._d(t); r30.add(k); r30Notes[k] = txt; }
        const ke = this._d(b - 60e3); r30.add(ke); r30Notes[ke] = txt;
      }
      // v49 (Ryan, Nov 5): FAR columns on EVERY day, looking back and forward.
      // 30/7 (117.25(b)): longest free block in the 168 h before a report that day: the real duty start on a duty day,
      // 00:01 on an open day (worst case); blank on a mid-trip day with no duty start.
      // 100/672 (117.23(b)(1)): leg block in the 672 h ending 24:00 that day; Room = 100:00 minus the busiest 672 h window
      // that contains the day, back and forward 28 days.
      const legs = [];
      for (const o of own) {
        const t = ownT[`${o.it.trip}|${o.it.start}`] || {}; const base = this._t(o.it.start, "0:0");
        // duty blk can carry credit on some trips, so each trip's legs are scaled to FLICA's trip Block
        const dsum = (t.duties || []).reduce((sm, du) => sm + (du.blk || 0), 0) / 60, tb = hrs(t.blk), sc = tb != null && dsum > 0 ? Math.min(1, tb / dsum) : 1;
        if (t.duties && t.duties.length) t.duties.forEach((du) => { if (du.blk) legs.push({ a: base + (du.arr - du.blk) * 60e3, b: base + du.arr * 60e3, h: du.blk / 60 * sc }); });
        else { const bh = hrs(t.blk); if (bh != null && o.rep && o.rel) legs.push({ a: o.rep, b: o.rel, h: bh }); }
      }
      const blkIn = (w0, w1) => legs.reduce((sm, l) => { const ov = Math.min(l.b, w1) - Math.max(l.a, w0); return ov > 0 ? sm + l.h * Math.min(1, ov / Math.max(1, l.b - l.a)) : sm; }, 0);
      const free30 = (R) => { const w0 = R - 168 * H; let big = null;
        for (const f of frees) { const a0 = Math.max(f.a, w0), a1 = Math.min(f.b, R); if (a1 > a0 && (!big || a1 - a0 > big.b - big.a)) big = { a: a0, b: a1, at: f.at }; }
        return big; };
      const inDuty = (ms) => duties.some((du) => du.start <= ms && ms < du.end);
      const hmS = (h) => (h < 0 ? "-" + hm(-h) : hm(h));
      const dutyStartOn = {};
      for (const du of duties) { const k = this._d(du.start); if (dutyStartOn[k] == null || du.start < dutyStartOn[k]) dutyStartOn[k] = du.start; }
      const farOn = {};
      for (const [d] of (mon.days || [])) {
        const R = dutyStartOn[d] != null ? dutyStartOn[d] : this._t(d, "0:01");
        const mid = dutyStartOn[d] == null && (inDuty(R) || own.some((o) => o.rep && o.rel && o.rep < R && R < o.rel));  // layover day inside a trip
        let t30 = "&#8211;", t30t = "Mid-trip (layover): no report this day. The layover itself gets the teal edge if it is 30 h or more.", bad30 = false;
        if (!mid) {
          const big = free30(R); const ok = !!big && big.b - big.a >= 30 * H; const unknown = !ok && R - 168 * H < dataStart;
          const gu = ok ? Math.min(big.b, R) + 138 * H : null;
          const endD = ok ? this._d(Math.min(big.b, R)) : "";
          t30 = ok ? `&#10003; <span class="k">${endD.slice(5).replace("-", "/")}</span>` : (unknown ? "?" : "need 30");
          bad30 = !ok && !unknown;
          t30t = `${dutyStartOn[d] != null ? "Duty starts " + this._hm(R) : "If you reported at 00:01"}: longest free block in the 168 h before was ${big ? this._dur(big.b - big.a) + " from " + this._hm(big.a) + " " + this._d(big.a) + (big.at && big.at !== "HNL" ? " at " + big.at : "") : "none"}. ` + (ok ? `30 in 7 met (FAR 117.25(b)); this break covers reports until ${this._hm(gu)} ${this._d(gu)}.` : unknown ? "The window reaches before the schedule on file." : "Under 30:00: 30 in 7 NOT met (FAR 117.25(b)).");
        }
        const E = this._t(d, "0:0") + 24 * H;
        const back = blkIn(E - 672 * H, E);
        let worst = back, wE = E;
        for (let k = 1; k < 28; k++) { const e2 = E + k * 24 * H; const v = blkIn(e2 - 672 * H, e2); if (v > worst) { worst = v; wE = e2; } }
        const approxB = E - 672 * H < dataStart, approxR = approxB || E + 27 * 24 * H > dataEnd;
        const room = 100 - worst;
        farOn[d] = { t30, t30t, bad30, ok30: t30.startsWith("&#10003;"), b: hm(back) + (approxB ? "~" : ""), over: back >= 100,
          bt: `Block flown in the 672 h (28 days) ending 24:00 ${d}, leg by leg${approxB ? "; ~ = part of the window is before the schedule on file" : ""}. FAR 117.23(b)(1) limit 100:00.`,
          room: hmS(room) + (approxR ? "~" : ""), rbad: room <= 0,
          rt: `Room = 100:00 minus the busiest 672 h window this day falls in (${hm(worst)} in the 28 days ending 24:00 ${this._d(wE - 1)}), looking back and forward. The most block you could add on this day.${approxR ? " ~ = a window reaches past the schedule on file." : ""}` };
      }
      // when the next 30 h off is needed: first report time after now with no 30 h free block in the 168 h before it
      let need30 = null;
      {
        const step = 15 * 60e3, t0 = Math.ceil(nowHst / step) * step, tEnd = Math.min(dataEnd, t0 + 40 * 24 * H);
        const cand = duties.filter((du) => du.start >= t0 && du.start < tEnd).map((du) => du.start);
        for (let T = t0; T < tEnd; T += step) if (!inDuty(T)) cand.push(T);
        cand.sort((a, b) => a - b);
        for (const T of cand) { const big = free30(T); if (!(big && big.b - big.a >= 30 * H)) { need30 = T; break; } }
      }
      // tag-on suggestions keyed by the day they report
      const tags = {};
      const avail = new Set([...pot.map((p) => `${p.pairing}|${this._iso(p.start, y)}`)]);
      const tbAvail = new Set(tb.map((p) => `${p.pairing}|${this._iso(p.start, y)}`));
      const vacDays = (a, b) => items.some((it) => it.trip === "VAC" && a <= it.end && b >= it.start);
      const blkDays = (a, b) => [...blocked].some((d) => a <= d && d <= b);
      if (pk) {
        for (let i = 0; i < own.length; i++) {
          const o = own[i]; if (!o.rel || o.it.start < key) continue;
          const nextRep = own.slice(i + 1).map((x) => x.rep).find((x) => x) || Infinity;
          const d0 = this._d(o.rel), d1 = this._d(o.rel + 24 * H);
          const found = [];
          for (const p of Object.values(pk)) {
            if (own.some((x) => x.it.trip.slice(0, 5) === p.id)) continue;
            for (const sd of [d0, d1]) {
              if (!p.days.has(sd)) continue;
              const rep = this._t(sd, p.report);
              const depH = parseInt(p.dep, 10);
              const need = (p.firstDuty >= 720 && (depH >= 14 || depH < 4)) ? 18 : 11;
              const gap = rep - o.rel;
              if (gap < need * H || gap > 36 * H) continue;
              const rel = this._t(sd, p.release) + p.relDays * 24 * H;
              if (nextRep - rel < 11 * H) continue;
              if (vacDays(sd, this._d(rel)) || blkDays(sd, this._d(rel))) continue;
              found.push({ p, sd, rep, rel, gap, need });
            }
          }
          found.sort((a, b) => a.rep - b.rep);
          for (const f of found.slice(0, 4)) {
            const k = `${f.p.id}|${f.sd}`;
            const src = avail.has(k) ? "O" : (tbAvail.has(k) ? "T" : "");
            const dest = f.p.route.split("-").slice(1, -1).join("/");
            const md = (iso) => `${MON3[parseInt(iso.slice(5, 7), 10) - 1][0]}${MON3[parseInt(iso.slice(5, 7), 10) - 1].slice(1).toLowerCase()} ${parseInt(iso.slice(8), 10)}`;
            const hc = (v) => String(v || "").replace("h", ":");
            const title = [`${f.p.id}  ${f.p.route}`, `Report ${f.p.report} ${md(f.sd)}`, `Release ${this._hm(f.rel)} ${md(this._d(f.rel))}`,
              `Credit ${hc(f.p.credit)}   TAFB ${hc(f.p.tafb)}`, `Rest after ${o.it.trip}: ${this._dur(f.gap)} (need ${f.need}:00)`,
              src === "O" ? "In open time now" : src === "T" ? "On the Tradeboard now" : "Not in open time"].join("\n");
            (tags[f.sd] = tags[f.sd] || []).push(`<span class="tag${src ? " avail" : ""}" title="${this._esc(title)}">` +
              `${this._esc(dest)}(${this._esc(f.p.id)}) ${this._esc(f.p.report)}${src ? ` <b>${src}</b>` : ""}</span>`);
          }
        }
      } else if (pk === false) note = `No ${MONTHS[m]} pairing package on file, so no tag-on ideas.`;
      { const sc0 = this._school(key + "-15"); if (sc0 === false) note += (note ? " " : "") + `No HPA school calendar file for this school year (school_YYYY-YY.json); holidays shown instead.`; }
      const sum = { blk: 0, cr: 0, soft: 0, gross: 0, net: 0, vac: 0, vacDays: 0 };
      const tripFull = (cr, blk, crew, lay, k, seat) => { const n = crewN(crew); seat = (seat || "FO").toUpperCase();
        const ov = blk != null ? (seat === "RO" ? blk * IRO_OVERRIDE : (seat !== "CA" && n === 3 ? blk * 3.00 : 0)) : 0;
        return cr == null ? null : cr * RATE + ov + (erOn(k, lay, n) ? cr * RATE * ER_PCT : 0); };
      // month price of a version (same rules as the rows): Awarded-Pay-Gross and Improved-Pay-Gross
      const price = (mm, tr) => { let g = 0; for (const [d, trip, lay] of ((mm && mm.days) || [])) { if (d.slice(0, 7) !== key) continue;
          if (trip === "VAC") { g += VAC_H * RATE; continue; } if (!trip || !/^[A-Z]\d{4}/.test(trip)) continue;
          const ot = tr[`${trip}|${d}`] || {}; const pr = pk ? (pk[trip.slice(0, 5)] || {}) : {};
          let cH = hrs(ot.credit); if (cH == null) cH = hx(pr.credit); let bH = hrs(ot.blk); if (bH == null) bH = hx(pr.block);
          let share = 1; if (ot.duties && ot.duties.length && ot.duties[0].blk != null) { const base = this._t(d, "0:0"); let inM = 0, all = 0;
            for (const du of ot.duties) { all += du.blk; if (this._d(base + du.dep * 60e3).slice(0, 7) === key) inM += du.blk; } share = all ? inM / all : 1; }
          const v = tripFull(cH == null ? null : cH * share, bH == null ? null : bH * share, pr.crew, lay, `${trip}|${d}`, ot.seat); g += v || 0; }
        return g; };
      const tripPay = {};
      // v51 (Ryan): swap / pick-up ideas. A swap may move off the trip's footprint onto any neighbouring day that is not
      // blocked and has no other assignment; legal rest before and after (11 h at domicile, PWA 10.E.1.a); pay from the
      // package credit (PWA 4.C.3 min 5:00 per calendar day already in it) with crew overrides (PWA 4.O.1).
      const allItems = [...prevItems, ...items, ...nextItems];
      const busyDay = (iso, excl) => blocked.has(iso) || allItems.some((it) => it !== excl && it.trip && it.start <= iso && iso <= it.end);
      const addD = (iso, n) => this._d(Date.parse(iso + "T00:00:00Z") + n * 24 * H);
      const ideasFor = (d, trip) => {
        if (!pk) return null;
        const o = trip && trip !== "VAC" ? own.find((x) => x.it.trip === trip && x.it.start === d) : null;
        if (trip && !o) return null;
        if (!trip && busyDay(d, null)) return null;
        const oEnd = o ? (o.rel ? this._d(o.rel) : o.it.end) : d;
        let a = o ? o.it.start : d, b = oEnd;
        for (let k = 0; k < 4 && !busyDay(addD(a, -1), o && o.it); k++) a = addD(a, -1);
        for (let k = 0; k < 4 && !busyDay(addD(b, 1), o && o.it); k++) b = addD(b, 1);
        if (!o) a = d;
        const others = own.filter((x) => x !== o);
        const cur = o ? (tripPay[o.it.trip + "|" + o.it.start] || 0) : 0;
        const out = [];
        for (const p of Object.values(pk)) {
          for (const sd of p.days) {
            if (sd < a || sd > b || (!o && sd !== d)) continue;
            const end = addD(sd, p.relDays || 0);
            if (end > b) continue;
            if (o && (end < o.it.start || sd > oEnd)) continue;  // a swap overlaps the trip it replaces
            if (o && p.id === o.it.trip.slice(0, 5) && sd === o.it.start) continue;
            let clash = false; for (let x = sd; x <= end; x = addD(x, 1)) if (busyDay(x, o && o.it)) { clash = true; break; }
            if (clash) continue;
            const rep = this._t(sd, p.report), rel = this._t(sd, p.release) + (p.relDays || 0) * 24 * H;
            const prev = others.filter((x) => x.rel && x.rel <= rep).map((x) => x.rel).sort((u, v) => v - u)[0];
            const next = others.filter((x) => x.rep && x.rep >= rel).map((x) => x.rep).sort((u, v) => u - v)[0];
            if ((prev && rep - prev < 11 * H) || (next && next - rel < 11 * H)) continue;
            const lay = (p.route || "").split("-").filter((x) => x !== "HNL").join("/");
            const pay = tripFull(hx(p.credit), hx(p.block), p.crew, lay, `${p.id}|${sd}`, "FO");
            const k = `${p.id}|${sd}`;
            out.push({ p, sd, end, rep, rel, lay, pay, delta: pay - cur, src: avail.has(k) ? "O" : (tbAvail.has(k) ? "T" : ""),
              rest: [prev ? `${this._dur(rep - prev)} rest before` : "", next ? `${this._dur(next - rel)} rest after` : ""].filter(Boolean).join(", ") });
          }
        }
        out.sort((u, v) => (!!v.src - !!u.src) || (v.delta - u.delta));
        return { o, a, b, cur, list: out };
      };
      const ideaBtn = (d, trip) => {
        const r = ideasFor(d, trip); if (!r || !r.list.length) return "";
        const nO = r.list.filter((x) => x.src).length, best = Math.max(...r.list.map((x) => x.delta));
        return `<span class="idb${nO ? " live" : ""}" data-d="${d}" data-trip="${this._esc(trip || "")}" title="${r.o ? "Swap ideas" : "Pick-up ideas"}: ${nO} open now, ${r.list.length} in the package">&#9992;&#xFE0E;${nO ? " " + nO : ""}${best > 0 ? ` <small>+${usd(best)}</small>` : ""}</span>`;
      };
      const rows = (mon.days || []).map(([d, trip, lay]) => {
        const dt = new Date(d + "T12:00:00"); const wk = dt.getDay() === 0 || dt.getDay() === 6;
        const other = dt.getMonth() !== m;
        const sc = this._school(d); const noSchool = !!(sc && sc.days.has(d));
        const t = trip === "VAC" ? `<span class="vac">VAC</span>` : (trip ? `<span class="trip${trade.has(trip + "|" + d) ? " tr" : ""}" data-k="${this._esc(trip + "|" + d)}" title="${this._esc(((ownT[`${trip}|${d}`] || {}).crew || []).join("\n") || "crew not read yet")}">${this._esc(trip)}</span>${d <= today ? "" : `<span class="trb${trade.has(trip + "|" + d) ? " on" : ""}" data-k="${this._esc(trip + "|" + d)}" title="${trade.has(trip + "|" + d) ? "Marked: would trade this trip for a better one. Tap to unmark." : "Tap to mark this trip as one you would trade for a better one."}">&#8644;</span>`}${d <= today ? "" : `<span class="drb${dropM.has(trip + "|" + d) ? (dropR[trip + "|" + d] ? " on rdy" : " on") : ""}" data-k="${this._esc(trip + "|" + d)}" title="${dropR[trip + "|" + d] ? "Grid green on every day: drop request ready (Test mode, nothing filed). Tap to unmark." : dropM.has(trip + "|" + d) ? "Marked: would DROP this trip once the reserve grid is green on every day of it. Tap to unmark." : "Tap to mark this trip as one you would DROP when the grid allows it."}">&#8615;</span>`}` : "");
        const sw = (swapFor[trip + "|" + d] || []).slice(0, 2).map((i) => `<span class="tag sw" title="${this._esc([`Swap ${trip} for ${i.pairing}`, `${i.dates}  ${i.layover || i.turn || ""}`, i.why, i.src === "T" ? "On the Tradeboard" : "In open time"].join("\n"))}">&#8644; ${this._esc(i.layover || i.turn || "")}(${this._esc(i.pairing)}) ${this._esc(i.soft_gain)}</span>`).join("<br>");
        const crewT = this._esc(((ownT[`${trip}|${d}`] || {}).crew || []).join("\n") || "crew not read yet");
        const rp = repOn[d] ? ` <span class="tm tag" title="${trip && trip !== "VAC" ? `${trip} crew:\n${crewT}\n\nReport ${repOn[d]}` : `Report ${repOn[d]}`}">R ${repOn[d]}</span>` : "";
        const rl = relOn[d] ? ` <span class="tm">Rel ${relOn[d]}</span>` : "";
        // a turn (no layover) shows "-" on FLICA; show the turn station(s) from the pairing package instead (HNL-PPG-HNL -> PPG)
        const pkt = lay === "-" && trip && pk ? pk[trip.slice(0, 5)] : null;
        const turn = pkt && pkt.route ? [...new Set(pkt.route.split("-").slice(1, -1).filter((x) => x !== "HNL"))].join("/") : "";
        const l0 = lay === "-" && !inTrip(d) ? "" : (lay === "-" && turn ? `<b>${this._esc(turn)}</b>` : this._esc(lay));
        // v44 (Ryan): the layover cell carries the trip's crew (tap on a phone, hover on a Mac)
        const cov = items.find((it) => it.trip !== "VAC" && it.start <= d && d <= it.end);
        const covT = cov ? (ownT[`${cov.trip}|${cov.start}`] || {}) : null;
        const nowH = new Date(Date.now() - 10 * H); const nowHM = `${String(nowH.getUTCHours()).padStart(2, "0")}:${String(nowH.getUTCMinutes()).padStart(2, "0")}`;
        const tOwn = cov ? (ownT[`${cov.trip}|${cov.start}`] || {}) : {};
        const done = cov && (cov.end < today || (cov.end === today && tOwn.last_arr && nowHM >= tOwn.last_arr));
        const flying = cov && !done && (cov.start < today || (cov.start === today && (!tOwn.report || nowHM >= tOwn.report)));
        const st = cov && d === cov.start ? (done ? ` <span class="st" title="Trip complete: Block and Credit are the final times">&#10004;</span>` : (flying ? ` <span class="st fly" title="Trip in progress: Block and Credit update every 6 h">&#9992;</span>` : "")) : "";
        const l = l0 && cov ? `<span class="tag lay" title="${this._esc(`${cov.trip} ${cov.start} crew:\n${(covT && covT.crew || []).join("\n") || "crew not read yet"}`)}">${l0}</span>${st}` : l0;
        const g = grid[d]; const gc = g ? g.color : ""; const gb = gc === "green";
        const gcell = g ? `<span class="g ${gc}" title="Net reserves ${g.net}: ${gb ? "drop or swap off this day OK" : "add only (no drop/swap off this day)"}">${g.net}</span>` : "";
        const ot = trip && trip !== "VAC" ? (ownT[`${trip}|${d}`] || {}) : {};
        const pkr = trip && trip !== "VAC" && pk ? (pk[trip.slice(0, 5)] || {}) : {};
        const bcsAll = trip && trip !== "VAC" ? [ot.blk || "", ot.credit || pkr.credit || "", ot.soft || ""] : ["", "", ""];
        // PWA 4.A: a segment pays on the date it originates, so duties that start next month are next month's pay
        let share = 1, blkOut = 0, nextMon = "";
        if (trip && trip !== "VAC" && ot.duties && ot.duties.length && ot.duties[0].blk != null) {
          const base = this._t(d, "0:0"); let inM = 0, all = 0;
          for (const du of ot.duties) { const dm = this._d(base + du.dep * 60e3).slice(0, 7); all += du.blk; if (dm === key) inM += du.blk; else { blkOut += du.blk; nextMon = dm; } }
          share = all ? inM / all : 1;
        }
        const hm2 = (h) => { const mm = Math.round(h * 60); return `${Math.floor(mm / 60)}:${String(mm % 60).padStart(2, "0")}`; };
        const bcs = share < 1 ? [hm2((hrs(bcsAll[0]) || 0) * share), hm2((hrs(bcsAll[1]) || 0) * share), hm2(Math.max(0, (hrs(bcsAll[1]) || 0) * share - (hrs(bcsAll[0]) || 0) * share))] : bcsAll;
        const splitNote = share < 1 ? `${trip}: ${bcsAll[0]} block / ${bcsAll[1]} credit in all; ${hm2(blkOut / 60)} block flown from ${nextMon} pays next month (PWA 4.A). Credit split by block share${hrs(bcsAll[2]) ? ", estimate" : ""}.` : "";
        const cH = hrs(bcs[1]), bH = hrs(bcs[0]);
        const gross = cH != null ? cH * RATE : null;
        const seat = (ot.seat || "").toUpperCase();
        const nP = crewN(pkr.crew);
        const roV = bH != null ? (seat === "RO" ? bH * IRO_OVERRIDE : (seat !== "CA" && nP === 3 ? bH * 3.00 : 0)) : 0;
        const ro = bH != null && roV ? usd(roV) : "";
        const erK = trip + "|" + d, erIs = cH != null && erOn(erK, l, nP);
        const erV = erIs ? cH * RATE * ER_PCT : 0;
        const total = gross != null ? gross + roV + erV : null;
        const net = total != null ? total * (1 - (fed + stt) / 100) : null;
        if (trip && trip !== "VAC") tripPay[trip + "|" + d] = tripFull(hrs(bcsAll[1]) != null ? hrs(bcsAll[1]) : hx(pkr.credit), hrs(bcsAll[0]) != null ? hrs(bcsAll[0]) : hx(pkr.block), pkr.crew, l, trip + "|" + d, seat);
        if (trip && trip !== "VAC" && d.slice(0, 7) === key) { sum.blk += bH || 0; sum.cr += cH || 0; sum.soft += hrs(bcs[2]) || 0; sum.gross += total || 0; sum.net += net || 0; }
        if (trip === "VAC" && d.slice(0, 7) === key) { sum.vacDays += 1; sum.vac += VAC_H; sum.gross += VAC_H * RATE; sum.net += VAC_H * RATE * (1 - (fed + stt) / 100); }
        const lines = gross != null ? [`Pay-Credit ${usd(gross)} (${bcs[1]} x $${RATE.toFixed(2)})`]
          .concat(seat === "RO" ? [`IRO override ${usd(roV)} (${bcs[0]} block x $${IRO_OVERRIDE.toFixed(2)}, PWA 4.O.1.a)`] : (roV ? [`IRO crew FO override ${usd(roV)} (${bcs[0]} block x $3.00, PWA 4.O.1.a)`] : []))
          .concat(erIs ? [`Extended Range type-rated FO +15% ${usd(erV)} (PWA 4.O.1.b)`] : []) : [];
        const payT = lines.join("\n");
        const erBtn = cH != null ? `<span class="er tag${erIs ? " on" : ""}" data-k="${this._esc(erK)}">RO+15% ${erIs ? "ON, tap to turn off" : "off, tap to turn on (4-pilot Extended Range trip, not IOE)"}</span>` : "";
        const fo = farOn[d] || null;
        // trip box in the Layover column: top edge on the report day, bottom edge on the release day
        const tripSpan = own.find((o) => o.it.start <= d && d <= (o.rel ? this._d(o.rel) : o.it.end));
        const bx = tripSpan ? " bx" + (tripSpan.it.start === d ? " bxs" : "") + ((o => o.rel ? this._d(o.rel) : o.it.end)(tripSpan) === d ? " bxe" : "") : "";
        const lg = legalOn[d]; const lcell = lg ? `<span class="tag lgl" title="${this._esc([`Released ${lg.rel}`, `Legal to report ${lg.t} (11 h, PWA 10.E.1.a)`, `For a 12 h+ duty leaving 1400-0359: ${lg.t18} (18 h, PWA 10.E.1.b)`].join("\n"))}">${lg.t}</span>` : "";
        return `<tr data-d="${d}" class="${wk ? "wk" : ""}${noSchool ? " hol" : (this._hol(d) ? " hol2" : "")}${other ? " oth" : ""}${blocked.has(d) ? " blk" : ""}${trip === "VAC" ? " vac" : ""}${gb ? " gg" : (gc ? " gx" : "")}${r30.has(d) ? " r30" : ""}${bx}"><td>${DOW[dt.getDay()]}</td><td class="n" title="${r30.has(d) ? this._esc(r30Notes[d]) : ""}">${d.slice(8)}</td>` +
          `<td>${t}</td><td>${l}${rp}${rl}</td><td class="t${splitNote ? " split" : ""}" title="${this._esc(splitNote)}">${this._esc(bcs[0])}</td><td class="t${splitNote ? " split" : ""}" title="${this._esc(splitNote)}">${this._esc(bcs[1])}</td><td class="t">${this._esc(bcs[2])}</td><td class="t tot1"><span class="pay" data-info="${this._esc(payT)}" data-btn="${this._esc(erBtn)}" title="${this._esc(payT)}">${usd(total)}</span></td><td class="t" title="Pay-Gross less ${fed}% federal and ${stt}% state">${usd(net)}</td><td class="gr">${gcell}</td><td class="t far${fo && fo.bad30 ? " bad" : ""}${fo && fo.ok30 ? " ok30" : ""}${fo && fo.t30 === "&#8211;" ? " mid" : ""}" title="${fo ? this._esc(fo.t30t) : ""}">${fo ? fo.t30 : ""}</td><td class="t far${fo && fo.over ? " bad" : ""}" title="${fo ? this._esc(fo.bt) : ""}">${fo ? fo.b : ""}</td><td class="t far${fo && fo.rbad ? " bad" : ""}" title="${fo ? this._esc(fo.rt) : ""}">${fo ? fo.room : ""}</td><td class="lg">${lcell}</td><td class="o">${(opens[d] || []).join("<br>")}</td><td class="tg">${ideaBtn(d, trip)}</td></tr>`;
      }).join("");
      const tt = mon.totals || {};
      const fl = (v) => { const m = /^(\d+)[.:](\d{2})$/.exec(String(v || "")); return m ? parseInt(m[1], 10) + parseInt(m[2], 10) / 60 : null; };
      const fBlk = fl(tt.block), fCr = fl(tt.credit), crAll = sum.cr + sum.vac;
      const chk = (mine, flica) => flica == null ? "" : Math.abs(mine - flica) < 1 / 60 ? ` <span class="okc" title="matches FLICA">&#10003;</span>` : ` <span class="bad" title="FLICA shows ${hm(flica)}">FLICA ${hm(flica)}</span>`;
      const bAv = 98 - (fBlk != null ? fBlk : sum.blk);
      const n30 = need30 ? `<span class="${need30 - nowHst < 48 * H ? "bad" : ""}" title="The first report after which you need 30 h off first (FAR 117.25(b)), from the schedule on file">${this._d(need30).slice(5).replace("-", "/")} ${this._hm(need30)}</span>` : `<span title="FAR 117.25(b) met for any report through the end of the schedule on file">end of sched</span>`;
      const tot = [["Credit", hm(crAll) + chk(crAll, fCr)], ["Block", hm(sum.blk) + chk(sum.blk, fBlk)], ["Block Avail", `<span class="${bAv <= 0 ? "bad" : ""}" title="98:00 bid-month block cap (crew scheduling) minus FLICA's bid-period Block">${bAv < 0 ? "-" + hm(-bAv) : hm(bAv)}</span>`], ["Soft", hm(sum.soft)],
        ["Vacation", sum.vacDays ? `${hm(sum.vac)} <span class="k">(${sum.vacDays} d x ${hm(VAC_H)})</span>` : ""],
        ["Pay-Gross", usd(sum.gross)], ["Pay-Net", usd(sum.net)], ["Days Off", tt.days_off], ["Need 30 h off by", n30]]
        .filter(([, v]) => v !== undefined && v !== null && v !== "")
        .map(([k, v]) => `<span><span class="k">${k}</span> ${v}</span>`).join("");
      if (this._idea && this._idea.key === key) {
        const r = ideasFor(this._idea.d, this._idea.trip);
        const md = (iso) => `${MON3[parseInt(iso.slice(5, 7), 10) - 1].slice(0, 1)}${MON3[parseInt(iso.slice(5, 7), 10) - 1].slice(1).toLowerCase()} ${parseInt(iso.slice(8), 10)}`;
        if (r) {
          const rowsI = r.list.slice(0, 25).map((x) => `<tr class="${x.src ? "on" : "off"}"><td><b>${this._esc(x.p.id)}</b></td><td>${md(x.sd)}${x.end !== x.sd ? " - " + md(x.end) : ""}</td><td>${this._esc(x.lay || x.p.route)}</td><td class="t">${(x.p.relDays || 0) + 1}</td><td class="t">${this._esc(String(x.p.credit).replace("h", ":"))}</td><td class="t">${usd(x.pay)}</td><td class="t ${x.delta >= 0 ? "up" : "dn"}">${x.delta >= 0 ? "+" : "-"}${usd(Math.abs(x.delta))}</td><td>${x.src === "O" ? "Open time" : x.src === "T" ? "Tradeboard" : "not open now"}</td><td class="k">R ${this._esc(x.p.report)} ${x.p.crew ? "· " + this._esc(x.p.crew) : ""}${x.rest ? " · " + x.rest : ""}</td></tr>`).join("");
          panel = `<div class="ipanel"><div class="ihd"><b>${r.o ? `Swap ideas for ${this._esc(r.o.it.trip)} ${md(r.o.it.start)} (yours ${usd(r.cur)})` : `Pick-up ideas starting ${md(this._idea.d)}`}</b> <span class="k">window ${md(r.a)} - ${md(r.b)}: days you have not blocked and have nothing else on</span><span class="ix" title="Close">&#10005;</span></div>` +
            (rowsI ? `<div class="wrap"><table class="itab"><tr><th>Trip</th><th>Dates</th><th>Layover</th><th>Days</th><th>Credit</th><th>Pay-Gross</th><th>${r.o ? "vs yours" : "adds"}</th><th>Where</th><th>Report · crew · rest</th></tr>${rowsI}</table></div>` : `<div class="k">Nothing fits that window.</div>`) +
            `<div class="k">Pay-Gross = package credit x $${RATE.toFixed(2)} (min 5:00 per calendar day, PWA 4.C.3) + IRO crew FO $3.00 per block hour or Extended Range type-rated FO +15% (PWA 4.O.1). Rest: 11 h at domicile (PWA 10.E.1.a). FAR 117 is not checked here: see the FAR columns once it is on your line. Swaps go through FLICA; nothing is filed from here.</div></div>`;
        }
      }
      // versions bar: Awarded-Pay-Gross (version .001, the awarded line) and Improved-Pay-Gross (current minus awarded)
      if (vl.length && liveMon) {
        const awd = price(vl[0], mergeT(liveOwnT, vl[0].trips)), curG = price(liveMon, liveOwnT), imp = curG - awd;
        const shown = vsel || vl[vl.length - 1];
        const cg = vsel ? price(mon, ownT) : curG;
        const isCur = !vsel;
        vhtml = `<div class="vbar"><span class="vb" data-v="prev" title="Older version">&#9664;</span> <b>v${this._esc(shown.ver)}</b> <span class="vb" data-v="next" title="Newer version">&#9654;</span> <span class="vb${isCur ? " here" : ""}" data-v="home" title="Current version">&#127968;</span> <span class="k">${vl.length} versions${isCur ? " (current)" : " · viewing " + this._esc((shown.at || "").slice(0, 10)) + ", Pay-Gross " + usd(cg)}</span>` +
          ` &nbsp;<span class="k">Awarded-Pay-Gross</span> <b>${usd(awd)}</b> <span class="k">(v${this._esc(vl[0].ver)})</span> &nbsp;<span class="k">Improved-Pay-Gross</span> <b class="${imp >= 0 ? "up" : "dn"}">${imp >= 0 ? "+" : "-"}${usd(Math.abs(imp))}</b>` +
          `</div>`;
        const chg = (shown.changes || []).filter((c) => !/ \? -> /.test(c));
        chtml = `<details class="chg"><summary>Changes in v${this._esc(shown.ver)}${shown.at ? " (" + this._esc(String(shown.at).slice(0, 10)) + ")" : ""}</summary>${chg.length ? "<ul>" + chg.map((c) => "<li>" + this._esc(c) + "</li>").join("") + "</ul>" : "<div>No trip or pay changes (first reads of seat or times only).</div>"}</details>`;
        const sig = `${key}|${Math.round(awd)}|${Math.round(curG)}|${vl[vl.length - 1].ver}`;
        this._impSig = this._impSig || {};
        if (this._impSig[key] !== sig && this._h) {
          this._impSig[key] = sig;
          this._h.callService("mqtt", "publish", { topic: "flight_watcher/improved/set", payload: JSON.stringify({ month: key, awarded: Math.round(awd * 100) / 100, current: Math.round(curG * 100) / 100, ver: vl[vl.length - 1].ver, awarded_ver: vl[0].ver }) });
        }
      }
      const head = `<tr class="hd"><th></th><th></th><th>Trip</th><th>Layover</th><th>Block</th><th>Credit</th><th>Soft</th><th title="Credit pay + RO + RO+15%; hover or tap for the breakdown">Pay-Gross</th><th>Pay-Net</th><th title="Reserve grid net reserves">Res Grid</th><th title="Check MM/DD = a 30 h break falls in the 168 h before a report that day and ended on MM/DD, FAR 117.25(b). The teal edge on a day marks the break itself. Hover for the hours and 'covered until'.">FAR-30/7</th><th title="Block flown in the 672 h ending that day, FAR 117.23(b)(1)">FAR-100/672</th><th title="100:00 minus the busiest 672 h window the day falls in, back and forward">Room</th><th title="Earliest report for another trip">Legal next</th><th>Open</th><th title="Tap the airplane: swap or pick-up ideas for that day, with the Pay-Gross difference">Ideas</th></tr>`;
      body = `<div class="wrap"><table class="cal">${head}${rows}</table></div><div class="tot" title="${this._esc(`${MONTHS[m]} totals: flying credited to the month each segment originates (PWA 4.A) plus vacation days at ${hm(VAC_H)} (PWA 6.J). Pay at $${RATE.toFixed(2)}/credit h incl. RO and RO+15% where on; net after the tax settings. Checked against FLICA's Block and Credit.`)}">${tot}</div>`;
    }
    const upd = st ? (st.attributes.updated || "") : "";
    const sel = (lo, hi, step, cur, suf) => { const o = []; for (let v = lo; v <= hi + 1e-9; v += step) { const r = Math.round(v * 100) / 100; o.push(`<option value="${r}"${Math.abs(r - cur) < 1e-9 ? " selected" : ""}>${r}${suf}</option>`); } return o.join(""); };
    this.shadowRoot.innerHTML = `<style>
      ha-card{padding:10px 8px 12px;font-size:12.5px;line-height:1.25;box-sizing:border-box}
      .wrap{overflow-x:auto;-webkit-overflow-scrolling:touch;max-width:100%}
      .cal td:nth-child(1),.cal td:nth-child(2),.cal th:nth-child(1),.cal th:nth-child(2){position:sticky;background:var(--card-background-color,#fff);z-index:1}
      .cal td:nth-child(1),.cal th:nth-child(1){left:0}.cal td:nth-child(2),.cal th:nth-child(2){left:34px}
      .cal th{background:var(--card-background-color,#fff)}
      @media (max-width:700px){ha-card{font-size:10.5px;padding:6px 3px 8px}.cal td{padding:1px 3px}
        .cal td:nth-child(1),.cal th:nth-child(1){position:static}.cal td:nth-child(2),.cal th:nth-child(2){left:0;border-left:none}
        .lt td:first-child{width:90px}.set span{display:block;margin:2px 0}.nav{font-size:20px}}
      .vbar{text-align:left;font-size:12px;margin:0 0 6px;padding-left:0}.vbar .vb{cursor:pointer;padding:0 6px;color:var(--primary-color)}.vbar .vb.here{opacity:.5}.vbar .vch{opacity:.7;font-size:11px}.vbar .up,.ipanel .up{color:#2e7d32}.vbar .dn,.ipanel .dn{color:#c62828}
      .idb{cursor:pointer;color:#888;white-space:nowrap}.idb.live{color:var(--primary-color);font-weight:700}.idb small{color:#2e7d32}
      .ipanel{margin:10px 0;padding:8px;border:1px solid var(--divider-color,#ccc);border-radius:8px}.ipanel .ihd{margin-bottom:6px}.ipanel .ix{float:right;cursor:pointer;padding:0 6px}
      .itab{border-collapse:collapse;font-size:12px;width:100%}.itab td,.itab th{border-bottom:1px solid var(--divider-color,#ddd);padding:3px 5px;text-align:left}.itab td.t{text-align:right}.itab tr.off{opacity:.55}
      .hd2{display:flex;align-items:center;gap:8px;margin:0 0 6px;flex-wrap:wrap}.hd2 .sp{flex:1}.frame{width:fit-content;max-width:100%;margin:0 auto}.chg{margin:6px auto 0;max-width:620px;font-size:11px;color:var(--secondary-text-color);text-align:center}.chg summary{cursor:pointer;font-weight:600;font-size:11px;list-style:none}.chg summary::-webkit-details-marker{display:none}.chg summary::before{content:"\\25B8 "}.chg[open] summary::before{content:"\\25BE "}.chg ul{display:inline-block;text-align:left;margin:4px 0 0;padding-left:16px}.chg li{margin:1px 0}
      .nav{cursor:pointer;font-size:22px;line-height:1;padding:0 8px;border-radius:6px;color:var(--primary-color);user-select:none}
      .nav.now{font-size:11px;padding:3px 8px;border:1px solid var(--divider-color)}.nav:hover{background:rgba(0,0,0,.06)}
      h3{margin:0;font-size:16px}
      .u{font-size:11px;color:var(--secondary-text-color)}
      table{border-collapse:collapse;margin:0 auto}
      .cal{border:1px solid var(--divider-color)}
      .cal td{padding:1px 6px;white-space:nowrap;vertical-align:top;border-left:1px solid var(--divider-color,#e0e0e0);border-bottom:1px solid var(--divider-color,#e0e0e0)}
      .cal th{border-left:1px solid var(--divider-color,#e0e0e0)}.cal td:first-child,.cal th:first-child{border-left:none}
      .cal td:nth-child(2){border-left:none}
      .cal th{padding:2px 6px;font-size:10.5px;font-weight:600;text-align:left;color:var(--secondary-text-color);border-bottom:1px solid var(--divider-color);white-space:nowrap}
      .cal th:nth-child(n+5):nth-child(-n+12){text-align:right}
      .far{font-size:11px}.far.bad{color:#c62828;font-weight:700}.far.ok30{color:#2e7d32;font-weight:700;text-align:center;white-space:nowrap}.far.ok30 .k{font-weight:400;font-size:10px;color:#555}
      .cal td.t{text-align:right;font-size:11px}
      .cal td.n{text-align:right;padding-right:10px}
      .cal tr.r30 td:nth-child(1){box-shadow:inset 4px 0 0 #00897b}
      .cal td.far.mid{color:#999;text-align:center}
      .cal tr.bx td:nth-child(4){box-shadow:inset 2px 0 0 #444,inset -2px 0 0 #444}
      .cal tr.bxs td:nth-child(4){box-shadow:inset 2px 0 0 #444,inset -2px 0 0 #444,inset 0 2px 0 #444}
      .cal tr.bxe td:nth-child(4){box-shadow:inset 2px 0 0 #444,inset -2px 0 0 #444,inset 0 -2px 0 #444}
      .cal tr.bxs.bxe td:nth-child(4){box-shadow:inset 2px 0 0 #444,inset -2px 0 0 #444,inset 0 2px 0 #444,inset 0 -2px 0 #444}
      .tot1{font-weight:600}
      .cal tr.gg td:nth-child(4),.cal tr.gg td:nth-child(10){background:rgba(76,175,80,.16)}
      .cal tr.gx td:nth-child(4),.cal tr.gx td:nth-child(10){background:rgba(229,57,53,.16)}
      .cal tr.wk td:nth-child(1),.cal tr.wk td:nth-child(2){background:#dde6f3;color:#1f2a44}
      .cal tr.hol td:nth-child(1),.cal tr.hol td:nth-child(2){background:#fff0a8;color:#4e3b00}
      .cal tr.hol2 td:nth-child(1),.cal tr.hol2 td:nth-child(2){background:#fff0a8;color:#4e3b00;background-image:repeating-linear-gradient(135deg,transparent 0 5px,rgba(0,0,0,.06) 5px 7px)}
      .cal tr.oth td:nth-child(1),.cal tr.oth td:nth-child(2){opacity:.75}
      @media (prefers-color-scheme: dark){
        .cal tr.gg td:nth-child(4),.cal tr.gg td:nth-child(10){background:rgba(76,175,80,.28)}
        .cal tr.gx td:nth-child(4),.cal tr.gx td:nth-child(10){background:rgba(229,57,53,.3)}
        .cal tr.bx td:nth-child(4){box-shadow:inset 2px 0 0 #bbb,inset -2px 0 0 #bbb}
        .cal tr.bxs td:nth-child(4){box-shadow:inset 2px 0 0 #bbb,inset -2px 0 0 #bbb,inset 0 2px 0 #bbb}
        .cal tr.bxe td:nth-child(4){box-shadow:inset 2px 0 0 #bbb,inset -2px 0 0 #bbb,inset 0 -2px 0 #bbb}
        .cal tr.bxs.bxe td:nth-child(4){box-shadow:inset 2px 0 0 #bbb,inset -2px 0 0 #bbb,inset 0 2px 0 #bbb,inset 0 -2px 0 #bbb}
        .g.green{color:#81c784}.g.red{color:#ef9a9a}.far.bad{color:#ef9a9a}.far.ok30{color:#81c784}.far.ok30 .k{color:#bdbdbd}.lgl{color:#90caf9}.er.on{color:#81c784}.sw{color:#ffb74d}.trb.on{color:#ffb74d}
        .fit{color:#81c784}.tag.avail{color:#81c784}.trip.tr{background:rgba(255,160,0,.4)}
        .nav:hover{background:rgba(255,255,255,.1)}.trb:hover{background:rgba(255,255,255,.12)}
      }
      .cal tr.oth td{color:var(--secondary-text-color)}
      .cal tr[data-d] td:nth-child(-n+2){cursor:pointer}
      .cal tr.blk td.n::after{content:" \\2298";color:#e53935;font-weight:700}
      .cal tr.vac td.n::after{content:" \\2298";color:#e53935;font-weight:700;opacity:.8}
      .lock{cursor:pointer;font-size:16px;line-height:1;padding:2px 6px;border-radius:6px;user-select:none;margin-right:auto}.lock:hover{background:rgba(0,0,0,.06)}
      .lock.open{opacity:.9}.lock.shut{opacity:.6}
      .trip{color:var(--primary-color);font-weight:600}
      .vac{font-weight:600}
      .cal tr.gg td:nth-child(1),.cal tr.gg td:nth-child(2){font-weight:700}
      .gr{text-align:right;font-size:11px}.g.green{color:#2e7d32;font-weight:700}.g.red{color:#c62828;font-weight:700}.g.black{color:var(--primary-text-color)}
      .er{color:var(--secondary-text-color);cursor:pointer;text-decoration:underline dotted}.er.on{color:#2e7d32;font-weight:700}.pay{cursor:help}
      .set{margin:8px auto 0;max-width:620px;font-size:11px;color:var(--secondary-text-color);text-align:center}
      .set summary{cursor:pointer;font-weight:600;font-size:11px;list-style:none;margin-bottom:3px}.set summary::before{content:"\\25B8 "}.set[open] summary::before{content:"\\25BE "}
      .set span{margin:0 8px;white-space:nowrap}.set select{font-size:11px;margin-left:3px}.set .r{margin-top:3px}
      .lg{font-size:11px}.lgl{color:#1565c0;font-weight:600;cursor:help}
      .trip.tr{background:rgba(255,160,0,.28);border-radius:4px;padding:0 3px}
      .trb{display:inline-block;font-size:19px;line-height:1;padding:0 6px;margin-left:2px;color:#b0b0b0;cursor:pointer;vertical-align:middle;border-radius:5px}
      .trb.on{color:#ef6c00;background:rgba(255,160,0,.28)}
      .drb{display:inline-block;font-size:17px;line-height:1;padding:0 5px;margin-left:1px;color:#b0b0b0;cursor:pointer;vertical-align:middle;border-radius:5px}
      .drb.on{color:#c62828;background:rgba(229,57,53,.18)}.drb.on.rdy{color:#fff;background:#2e7d32}
      .trb:hover{background:rgba(0,0,0,.08)}
      .sw{color:#ef6c00;font-weight:600;cursor:help}
      .tm{font-size:10.5px;color:var(--secondary-text-color)}
      .o{font-size:11px}.fit{font-weight:700;color:var(--success-color,#2e7d32)}
      .clash{text-decoration:line-through;color:var(--secondary-text-color)}
      .tg{font-size:10.5px;color:var(--secondary-text-color)}
      .tag{cursor:help}.lay{display:inline-block;min-width:28px}
      .st{color:#2e7d32;font-weight:700;cursor:help}.st.fly{color:#1565c0}
      @media (prefers-color-scheme: dark){.st{color:#81c784}.st.fly{color:#90caf9}}.more{color:var(--primary-color);font-weight:700;padding:0 3px}.tag.avail{color:var(--success-color,#2e7d32);font-weight:600}
      .tot{margin-top:8px;font-size:14px;font-weight:700;text-align:center;display:flex;flex-wrap:wrap;justify-content:center;gap:4px 18px}.tot .k{font-weight:600;color:var(--secondary-text-color);font-size:12px;margin-right:4px}
      .lt{margin:0 auto;text-align:left}.lt td{padding:1px 6px;vertical-align:top}.lt td:first-child{font-weight:700;white-space:nowrap}
      .leg{font-size:10.5px;color:var(--secondary-text-color);text-align:center;margin-top:6px}
      .leg summary{cursor:pointer;font-weight:600;font-size:11px;list-style:none}.leg summary::before{content:"\\25B8 "}.leg[open] summary::before{content:"\\25BE "}
      .info{display:none;position:fixed;left:8px;right:8px;bottom:14px;z-index:9;margin:0 auto;max-width:460px;font-size:12px;padding:8px 10px 8px;border-radius:8px;background:var(--secondary-background-color);color:var(--primary-text-color);box-shadow:0 4px 18px rgba(0,0,0,.35);cursor:pointer}
      .info::after{content:"tap to close";display:block;margin-top:6px;font-size:10px;color:var(--secondary-text-color);text-align:right}
      .none{text-align:center;color:var(--secondary-text-color);padding:12px}
    </style><ha-card><div class="frame"><div class="hd2"><span class="lock ${this._locked ? "shut" : "open"}" title="${this._locked ? "Locked: availability, trade and drop marks cannot be changed by a tap. Tap to unlock." : "Unlocked: taps change availability, trade and drop marks. Tap to lock."}">${this._locked ? "&#128274;" : "&#128275;"}</span><span class="sp"></span><span class="nav" data-nav="-1" title="Previous month">&#8249;</span><h3>${MONTHS[m]} ${y}</h3><span class="nav" data-nav="1" title="Next month">&#8250;</span><span class="nav now" data-nav="0" title="This month">Now</span><span class="u">updated ${this._esc(upd)}</span></div>${vhtml}${body}</div>${panel}
    <div class="info"></div>
    <details class="leg"><summary>Key</summary><table class="lt">
    <tr><td>Trip</td><td>Your pairing. R = report time. Tap &#8644; to mark it "would trade" (orange).</td></tr>
    <tr><td>Layover</td><td>Layover city. <b>Bold</b> = turn, no layover. Rel = release time (block-in + 15 min).</td></tr>
    <tr><td>Block / Credit / Soft</td><td>Your trip's block, credit and soft time (credit minus block), from FLICA's pairing page. Purple = this month's share only; the rest pays next month (PWA 4.A), hover for the split.</td></tr>
    <tr><td>Totals</td><td>Month totals incl. vacation at ${hm(VAC_H)} a day (PWA 6.J); &#10003; = matches FLICA's figure, red = FLICA differs.</td></tr>
    <tr><td>Pay-Gross / Pay-Net</td><td>Gross = credit x $${RATE.toFixed(2)} + RO + RO+15%; hover or tap it for the breakdown. Net = gross after the tax settings below.</td></tr>
    <tr><td>Teal edge</td><td>Thin teal mark left of the day = that day falls inside a break of 30+ consecutive hours free of all duty (FAR 117.25(b)), between duty periods, a long layover included. Hover the date for the break's start, end and 'covers reports until'. The FAR-30/7 column gives the date that counts: &#10003; MM/DD = the day the qualifying break ended (on a day still inside a break, usually that day's own date).</td></tr>
    <tr><td>RO / RO+15%</td><td>Add-ons inside Pay-Gross. RO = only on trips where you are listed RO: block x $${IRO_OVERRIDE.toFixed(2)} (PWA 4.O.1.a). RO+15% = Extended Range crew, 4 pilots, type-rated FO: 15% of pay (PWA 4.O.1.b); on by itself for SIN, tap Pay-Gross to switch any trip on or off.</td></tr>
    <tr><td>Res Grid</td><td>FLICA net reserves. <span class="g green">Green</span> = drop or swap off this day OK. <span class="g red">Red</span> = add only.</td></tr>
    <tr><td>FAR-30/7, FAR-100/672, Room</td><td>A break of 30 h+ off all duty (teal edge on its days, a long layover counts) covers any report up to 138 h after it ends (FAR 117.25(b): 30 h free in the 168 h before report). FAR-30/7: &#10003; MM/DD = a report that day is covered, and the date the qualifying 30 h break ended; red 'need 30' = it is not; ? = the window reaches before the schedule on file; &#8211; = mid-trip, no report that day. Hover for the hours and 'covered until'. Training (SIM, OEB, ground school) and reserve days count as duty. Need 30 h off by (totals): the first report time after which you need 30 h off first. 100/672: block flown in the 28 days ending that day, leg by leg (117.23(b)(1)). Room: 100:00 minus the busiest 28-day window the day falls in, back and forward: the most block you could add that day. ~ = a window reaches past the schedule on file. Block Avail: 98:00 bid-month cap minus FLICA's bid-period Block.</td></tr>
    <tr><td>Legal next</td><td>Earliest report for another trip: release + 11 h (PWA 10.E.1.a). Tap for the 18 h case.</td></tr>
    <tr><td>Open</td><td>Open time trips starting that day: <span class="fit">fits</span>, <span class="clash">clashes or blocked</span>.</td></tr>
    <tr><td>Ideas</td><td>Tag-ons after your release with legal rest, <b>O</b> = in open time, <b>T</b> = on the Tradeboard. Orange = better trip for a marked one. Tap for details.</td></tr>
    <tr><td>Day</td><td>Blue = weekend, yellow = no school at HPA (from the school year file), hatched yellow = US or Hawaii holiday with no school file loaded. Tap a day to block it (&#8856;), tap again to unblock; VAC days are always &#8856; and cannot be changed. The lock at the top left (&#128274;) freezes availability, trade and drop taps. All times HNL.</td></tr>
    </table>${note ? `<div>${note}</div>` : ""}</details>
    <details class="set"><summary>Pay settings</summary>
      <span>Federal tax <select data-e="input_number.flight_watcher_federal_tax_pct">${sel(0, 45, 0.5, fed, "%")}</select></span>
      <span>State tax <select data-e="input_number.flight_watcher_state_tax_pct">${sel(0, 15, 0.25, stt, "%")}</select></span>
      <span>Longevity year <select data-e="input_number.flight_watcher_longevity_year">${sel(1, 12, 1, lyr, "")}</select></span>
      <div class="r">Rate $${RATE.toFixed(2)}/credit h: A330 PAX FO, PWA 3.D.6, year ${lyr} (DOH ${DOH} = year ${dohYear(today)}, table caps at 12), effective ${RATE_DATES.filter((x) => x <= today).pop()}. Net = gross less federal and state only; estimate.</div>
    </details>${chtml}</ha-card>`;
    this._wire();
  }
  // one line per day: the first item, then "+N" that opens the rest in the info box
  _one(items, what) {
    if (!items.length) return "";
    if (items.length === 1) return items[0];
    const rest = items.slice(1).map((h) => h.replace(/<[^>]+>/g, "")).join("\n");
    return `${items[0]} <span class="tag more" title="${this._esc(`${items.length - 1} more ${what}${items.length > 2 ? "s" : ""}:\n${rest}`)}">+${items.length - 1}</span>`;
  }
  _wire() {
    this.shadowRoot.querySelectorAll(".set select").forEach((inp) => {
      inp.addEventListener("change", () => { this._h.callService("input_number", "set_value", { entity_id: inp.dataset.e, value: parseFloat(inp.value) }); });
    });
  }
  getCardSize() { return 12; }
}
customElements.define("flight-watcher-schedule-card", FlightWatcherScheduleCard);
window.customCards = window.customCards || [];
window.customCards.push({ type: "flight-watcher-schedule-card", name: "Flight Watcher schedule", description: "Compact month schedule like FLICA" });
